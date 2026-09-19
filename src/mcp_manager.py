# SPDX-License-Identifier: AGPL-3.0-or-later
"""
mcp_manager.py

Manages connections to MCP (Model Context Protocol) tool servers.
Each server exposes tools that are made available to the agent loop.
"""

import json
import logging
import os
import re
import asyncio 
from typing import Any, Dict, List, Optional, Set, Tuple
from src.database import McpServer, SessionLocal

from src.runtime_paths import get_app_root

logger = logging.getLogger(__name__)

def _format_mcp_connection_error(name: str, command: str = "", args: Optional[List[str]] = None, error: Exception = None) -> str:
    """Return a user-actionable MCP connection error message."""
    args = args or []
    raw_error = str(error) if error else "Unknown error"
    command_line = " ".join([command or "", *args]).strip()
    lower_command = command_line.lower()

    if "@playwright/mcp" in lower_command:
        return (
            f"{raw_error}\n\n"
            "Browser MCP could not start. On fresh installs, cache the Playwright MCP package once before connecting:\n\n"
            "npx -y @playwright/mcp@latest --version\n\n"
            "Then restart Pantheon and reconnect the Browser MCP server."
        )

    return raw_error


# Caps for rendering untrusted MCP tool schemas into the agent prompt (issue #2660).
# MCP servers are third-party/user-added, so field names and parameter counts are
# untrusted input — bound them so an odd or hostile schema cannot distort the prompt.
_MCP_PARAM_MAX = 12   # max params rendered per tool
_MCP_TOKEN_MAX = 40   # max chars per rendered name / type token
_MCP_HINT_MAX = 300   # total-length backstop for the whole hint


def _sanitize_schema_token(value: Any, limit: int = _MCP_TOKEN_MAX) -> str:
    """Make an untrusted JSON-Schema token safe to splice into the prompt.

    Replaces control chars / newlines with a space, collapses whitespace, and
    length-caps the result, so a weird field name or type cannot inject newlines
    or run on. Normal short identifiers pass through unchanged.
    """
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


# ── One reader for a tool's input schema (`Law 14`) ────────────────────────
#
# Two renderings were wanted and there is exactly one read. `_format_mcp_params`
# renders the compact prompt hint; `summarize_tool_parameters` renders the
# structured list `manage_mcp list_tools` hands the model (`B867`). Both walk
# `properties` / `required` through `_read_schema_params`, so the cap, the
# sanitizer and every schema quirk are handled once and the two can never
# disagree about what a tool takes.
_MCP_PARAM_DESC_MAX = 160   # max chars of a parameter's own description
_MCP_ENUM_MAX = 12          # max enum choices listed per parameter


def _read_schema_params(input_schema: Any) -> Tuple[List[Dict[str, Any]], int]:
    """Read an MCP tool's JSON-Schema inputs. Returns (params, omitted).

    `params` preserves the schema's own property order — the prompt hint has
    always rendered them that way and reordering here would change a prompt
    that is already pinned. Every name, type and enum value comes from a
    third-party server, so all of them go through `_sanitize_schema_token`.
    """
    if not isinstance(input_schema, dict):
        return [], 0
    props = input_schema.get("properties")
    if not isinstance(props, dict) or not props:
        return [], 0
    required = set(input_schema.get("required") or [])
    params: List[Dict[str, Any]] = []
    for pname, pinfo in list(props.items())[:_MCP_PARAM_MAX]:
        pinfo = pinfo if isinstance(pinfo, dict) else {}
        ptype = pinfo.get("type") or "any"
        if isinstance(ptype, list):
            ptype = "|".join(str(x) for x in ptype)
        entry: Dict[str, Any] = {
            "name": _sanitize_schema_token(pname),
            "type": _sanitize_schema_token(ptype),
            "required": pname in required,
        }
        desc = pinfo.get("description")
        if isinstance(desc, str) and desc.strip():
            entry["description"] = _sanitize_schema_token(desc, _MCP_PARAM_DESC_MAX)
        choices = pinfo.get("enum")
        if isinstance(choices, list) and choices:
            entry["enum"] = [_sanitize_schema_token(c) for c in choices[:_MCP_ENUM_MAX]]
        params.append(entry)
    return params, max(0, len(props) - len(params))


def _format_mcp_params(input_schema: Any) -> str:
    """Render an MCP tool's JSON-Schema inputs as a compact prompt hint.

    Without this the agent only sees a tool's name + description and has to
    guess its arguments (issue #2509). Produces e.g.
    ` Args (JSON): {"path": string (required), "limit": integer}` — names,
    coarse types, and required-ness, kept short so it stays prompt-friendly.
    Returns "" when there are no parameters.

    MCP servers are third-party, so names/types are sanitized and the parameter
    count + total length are capped (issue #2660); normal schemas are unaffected.
    """
    params, omitted = _read_schema_params(input_schema)
    if not params:
        return ""
    parts = []
    for p in params:
        tag = f'"{p["name"]}": {p["type"]}'
        if p["required"]:
            tag += " (required)"
        parts.append(tag)
    if omitted > 0:
        parts.append(f"…+{omitted} more")
    hint = " Args (JSON): {" + ", ".join(parts) + "}"
    if len(hint) > _MCP_HINT_MAX:
        hint = hint[:_MCP_HINT_MAX - 1].rstrip() + "…"
    return hint


def summarize_tool_parameters(input_schema: Any) -> Dict[str, Any]:
    """Structured form of the same read, for callers that hand JSON to a model.

    `{"parameters": [{name, type, required, description?, enum?}, ...],
      "omitted": <count of properties past the cap>}`.
    `B867`: `manage_mcp list_tools` used to project a tool to
    `{name, server, description[:100]}`, so the model could not see what a tool
    took through its own tool. This is what it sees instead — the same read the
    prompt hint uses, with the parameter's own description and its enum choices
    kept, because those are the two things that decide a call.
    """
    params, omitted = _read_schema_params(input_schema)
    return {"parameters": params, "omitted": omitted}


# ── The namespaced tool name (`P8-44`) ─────────────────────────────────────
#
# `mcp__<server_id>__<tool_name>` is parsed by ONE `split("__", 2)` in
# `call_tool`, and nothing anywhere held the invariant that makes that parse
# correct. A server id containing `__` does not fail — it ROUTES: id `a__b`
# with tool `t` qualifies to `mcp__a__b__t`, which splits to server `a`, tool
# `b__t`, and the call goes to a different server's session if one named `a`
# exists. Unreachable while ids are uuid4-derived, which is exactly why it is
# worth pinning now rather than after `P8-47` lets people name their servers.
#
# The invariant is held where the ids enter the manager (`connect_server`), so
# every registration path — the admin route, `manage_mcp add`, `pantheon-mcp`,
# the built-ins — gets the same rule without any of them restating it.
MCP_NAME_SEPARATOR = "__"
_MCP_SERVER_ID_MAX = 64
_MCP_SERVER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_mcp_server_id(server_id: Any) -> Optional[str]:
    """Return a sentence naming what is wrong with a server id, or None.

    The hard rule is the separator; the character class is the readable form of
    it (`_` alone is allowed, `__` is not, because one `_` cannot make two).
    """
    if not isinstance(server_id, str) or not server_id.strip():
        return "server id must be a non-empty string"
    if server_id != server_id.strip():
        return f"server id {server_id!r} has leading or trailing whitespace"
    if len(server_id) > _MCP_SERVER_ID_MAX:
        return (
            f"server id is {len(server_id)} characters; the limit is "
            f"{_MCP_SERVER_ID_MAX}"
        )
    if MCP_NAME_SEPARATOR in server_id:
        return (
            f"server id {server_id!r} contains '{MCP_NAME_SEPARATOR}', which is "
            "the separator in the tool name 'mcp__<server>__<tool>'. A call to "
            "this server's tools would be parsed as a call to a different "
            "server. Use a single underscore, a dash or a dot."
        )
    if not _MCP_SERVER_ID_RE.match(server_id):
        return (
            f"server id {server_id!r} must start with a letter or digit and "
            "contain only letters, digits, '.', '-' and '_'"
        )
    return None


def qualify_mcp_tool_name(server_id: str, tool_name: str) -> str:
    """Build the namespaced name. One spelling, so it matches the one parse."""
    return f"mcp{MCP_NAME_SEPARATOR}{server_id}{MCP_NAME_SEPARATOR}{tool_name}"


def split_mcp_tool_name(qualified_name: Any) -> Optional[Tuple[str, str]]:
    """Parse `mcp__<server_id>__<tool_name>`. Returns (server_id, tool) or None.

    The sole parse, named so it can be tested and so the invariant above has
    something to point at. `maxsplit=2` is correct **because** ids cannot hold
    the separator; tool names still may, and the third field keeps them whole.
    """
    if not isinstance(qualified_name, str):
        return None
    parts = qualified_name.split(MCP_NAME_SEPARATOR, 2)
    if len(parts) != 3 or parts[0] != "mcp" or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


# ── args / env entry types (`B865`) ────────────────────────────────────────
#
# `StdioServerParameters` is a pydantic model with `env: dict[str, str] | None`
# and `args: list[str]`, and it is constructed inside `_connect_stdio`'s try —
# so a `{"PORT": 3000}` that got past the route was reported to the operator as
# *this server's connection error*, in pydantic's own words, with a link to
# pydantic's documentation:
#
#   1 validation error for StdioServerParameters
#   env.PORT
#     Input should be a valid string [type=string_type, input_value=3000, ...]
#     For further information visit https://errors.pydantic.dev/...
#
# The rule lives here, beside the code that spawns the process, and the route
# and the agent tool both call it — so the operator is refused before anything
# is stored, and a row that somehow holds a bad value still gets a sentence
# instead of a traceback.
def _type_word(value: Any) -> str:
    return {
        bool: "boolean", int: "number", float: "number",
        list: "array", dict: "object", type(None): "null",
    }.get(type(value), type(value).__name__)


def validate_mcp_args(args: Any) -> Optional[str]:
    """Every argv entry must be a string. Returns a sentence, or None."""
    if args is None:
        return None
    if not isinstance(args, list):
        return f"args must be a JSON array, got {_type_word(args)}"
    for i, entry in enumerate(args):
        if not isinstance(entry, str):
            return (
                f"args[{i}] must be a string, got {_type_word(entry)} "
                f"({json.dumps(entry, default=str)}). Arguments are handed to "
                f"the command as text — quote it: "
                f"{json.dumps(str(entry))}."
            )
    return None


def validate_mcp_env(env: Any) -> Optional[str]:
    """Every env key and value must be a string. Returns a sentence, or None."""
    if env is None:
        return None
    if not isinstance(env, dict):
        return f"env must be a JSON object, got {_type_word(env)}"
    for key, value in env.items():
        if not isinstance(key, str) or not key:
            return f"env keys must be non-empty strings, got {_type_word(key)}"
        if not isinstance(value, str):
            return (
                f'env["{key}"] must be a string, got {_type_word(value)} '
                f"({json.dumps(value, default=str)}). Environment variables are "
                f"always text — quote it: {json.dumps(str(value))}."
            )
    return None


def validate_mcp_launch_fields(args: Any = None, env: Any = None) -> Optional[str]:
    """Both of the above, in the order an operator reads the form."""
    return validate_mcp_args(args) or validate_mcp_env(env)


# ── What a server told us about itself ─────────────────────────────────────
def _plain(value: Any) -> Any:
    """Best-effort conversion of an SDK pydantic model to plain JSON data.

    Nothing here is allowed to fail the connect. This runs on values a
    third-party server sent us during the handshake, on whatever pydantic
    version happens to be installed (the SDK has moved `dict` -> `model_dump`
    and the keyword set with it), and the worst outcome of getting it wrong is
    a status field we do not display. A raise here would instead cost the
    operator a working MCP server, so each attempt falls through to the next
    and the last resort is `str(value)`, which always works.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    for attr, kwargs in (("model_dump", {"exclude_none": True, "mode": "json"}),
                         ("dict", {"exclude_none": True})):
        fn = getattr(value, attr, None)
        if not callable(fn):
            continue
        try:
            return fn(**kwargs)
        except Exception:
            # Wrong keywords for this pydantic version — try the bare call,
            # and if that fails too, fall through to the next spelling and
            # finally to `str()`. Deliberately silent: see the docstring.
            pass
        try:
            return fn()
        except Exception:
            # Same reason. Not this object's serializer; keep looking.
            pass
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


def _normalize_annotations(ann: Any) -> Optional[Dict[str, Any]]:
    """An MCP `ToolAnnotations` as plain JSON, or None when absent/empty.

    The SDK hands back a pydantic model; the tests and the built-ins hand back
    a dict. `mcp_tool_is_readonly` has always accepted both, and now the value
    that leaves the manager is one shape, because it goes on the wire
    (`get_all_tools` → `GET /api/mcp/servers/{id}/tools` → the browser).
    """
    if ann is None:
        return None
    data = _plain(ann)
    if not isinstance(data, dict):
        return None
    data = {k: v for k, v in data.items() if v is not None}
    return data or None


_MCP_INSTRUCTIONS_MAX = 2000
# What of it goes into the system prompt. Shorter than what is kept, because
# the prompt pays for every character on every turn and the full text stays
# readable through `GET /api/mcp/servers` and `manage_mcp list`.
_MCP_PROMPT_INSTRUCTIONS_MAX = 600


def summarize_initialize_result(result: Any) -> Dict[str, Any]:
    """Keep what `initialize` told us (`P8-38`).

    The handshake was awaited and its return value dropped on the floor at all
    three connect sites. It carries the server's OWN name and version (which is
    not the label the operator typed into the form), the protocol version it
    negotiated, the capabilities it advertises, and `instructions` — prose the
    server wrote for whatever client connects, describing how its tools are
    meant to be used. None of it was recorded anywhere, so nothing could show
    it and the model never saw the one field written for it.
    """
    out: Dict[str, Any] = {}
    if result is None:
        return out
    info = _plain(getattr(result, "serverInfo", None))
    if isinstance(info, dict):
        name = info.get("name")
        version = info.get("version")
        title = info.get("title")
        if isinstance(name, str) and name.strip():
            out["server_name"] = _sanitize_schema_token(name, 80)
        if isinstance(version, str) and version.strip():
            out["server_version"] = _sanitize_schema_token(version, 40)
        if isinstance(title, str) and title.strip():
            out["server_title"] = _sanitize_schema_token(title, 80)
    proto = getattr(result, "protocolVersion", None)
    if isinstance(proto, str) and proto.strip():
        out["protocol_version"] = _sanitize_schema_token(proto, 40)
    caps = _plain(getattr(result, "capabilities", None))
    if isinstance(caps, dict) and caps:
        # The advertised feature names, not their nested config — this is the
        # line an operator reads to learn the server also serves prompts or
        # resources, which nothing in Pantheon consumes yet.
        out["capabilities"] = sorted(
            _sanitize_schema_token(k) for k, v in caps.items() if v is not None
        )
    instructions = getattr(result, "instructions", None)
    if isinstance(instructions, str) and instructions.strip():
        text = instructions.strip()
        if len(text) > _MCP_INSTRUCTIONS_MAX:
            text = text[:_MCP_INSTRUCTIONS_MAX - 1].rstrip() + "…"
        out["instructions"] = text
    return out


def _tool_entries(tools_result: Any) -> List[Dict[str, Any]]:
    """Build the manager's per-tool records from one `tools/list` result.

    `P8-40`. Three connect sites each built this dict inline and the HTTP one
    was written without `annotations`, so a remote server's `readOnlyHint` was
    honoured over stdio and SSE and silently dropped over HTTP — the same
    server got plan-mode read-only credit on one transport and not on another,
    however it advertised itself. Three spellings of one record is the `Law 13`
    shape; there is one now, and the next transport gets it without anyone
    remembering to.
    """
    entries: List[Dict[str, Any]] = []
    for tool in getattr(tools_result, "tools", None) or []:
        entries.append({
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": getattr(tool, "inputSchema", None) or {},
            # MCP tool annotations (readOnlyHint / destructiveHint) drive
            # plan-mode read-only gating. Absent on many servers, so we fall
            # back to a name heuristic in mcp_tool_is_readonly().
            "annotations": _normalize_annotations(getattr(tool, "annotations", None)),
        })
    return entries


# ── Call deadlines (`P8-37`) ───────────────────────────────────────────────
#
# Before this, `_do_call` awaited `session.call_tool(...)` with no bound of any
# kind. The MCP SDK's own `read_timeout_seconds` defaults to `None`
# (`mcp/shared/session.py:285-291`, `timeout = None` → `anyio.fail_after(None)`),
# so a server that accepts a `tools/call` and never answers left the await
# pending for as long as the process lived. That await is inside the agent's
# turn (`src/tool_execution.py:1345/1360`) and inside the scheduler's delivery
# path (`src/task_scheduler.py:2710/3588`), so one hung tool hung the turn and
# the task with it — with nothing in the UI to say why, because no exception
# was ever raised.
#
# The default is deliberately generous: real MCP tools drive browsers, index
# repositories and call slow third-party APIs, and a bound that fires on honest
# work is a bound operators raise until it is useless. What it must stop is
# *forever*.
MCP_CALL_TIMEOUT_SECONDS = 120.0

# The ceiling a caller may ask for. A per-call override exists so the test-call
# endpoint (`P8-36`) can use a short, interactive deadline, and so a genuinely
# long tool can be given room — but not so that "no timeout" can be spelled as
# a very large number, which is the state this replaces.
MCP_CALL_TIMEOUT_MAX_SECONDS = 600.0

# How much longer than the deadline the hard bound waits. The SDK's own timeout
# is the graceful one — it stops waiting on the response stream and raises a
# 408 — so it is given the deadline itself and should always fire first. The
# outer `asyncio.wait_for` is the backstop for everything the SDK's timer does
# not cover (a write that blocks, a session object that ignores the argument)
# and is therefore the layer that makes the bound enforceable rather than
# advisory.
_MCP_CALL_TIMEOUT_GRACE = 2.0

# The SDK spells its read timeout as an `McpError` carrying HTTP 408.
_MCP_TIMEOUT_CODE = 408


class McpCallTimeout(Exception):
    """One MCP tool call passed its deadline.

    A distinct type on purpose. `call_tool` reconnects a built-in server whose
    subprocess died and retries the call once; a hung tool is not a dead
    subprocess, and retrying it spends the deadline twice to learn the same
    thing. Carries the deadline so the message can name it.
    """

    def __init__(self, tool_name: str, timeout: float):
        self.tool_name = tool_name
        self.timeout = timeout
        super().__init__(
            f"MCP tool '{tool_name}' did not answer within {timeout:g}s and was "
            f"abandoned. The server may be hung, waiting on input it will never "
            f"get, or doing work that outlasts the limit."
        )


def resolve_mcp_call_timeout(timeout: Any = None) -> float:
    """Clamp a requested per-call deadline into the usable range.

    `None`, a non-number, or anything <= 0 means the default — a caller cannot
    switch the bound off, and a caller asking for a week gets the ceiling.
    """
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        return MCP_CALL_TIMEOUT_SECONDS
    if not value > 0:
        return MCP_CALL_TIMEOUT_SECONDS
    return min(value, MCP_CALL_TIMEOUT_MAX_SECONDS)


def _is_sdk_read_timeout(exc: BaseException) -> bool:
    """True for the MCP SDK's own read-timeout error.

    Duck-typed rather than imported: every other reference to `mcp` in this
    module is a lazy, guarded import because the package is optional, and a
    top-level `from mcp.shared.exceptions import McpError` here would undo
    that for the one path that must work when a server misbehaves.
    """
    return getattr(getattr(exc, "error", None), "code", None) == _MCP_TIMEOUT_CODE


def _session_takes_read_timeout(session: Any) -> bool:
    """Whether this session's `call_tool` accepts the SDK's timeout argument."""
    import inspect
    try:
        return "read_timeout_seconds" in inspect.signature(session.call_tool).parameters
    except (TypeError, ValueError):
        return False


# Tool-name prefixes that denote a read-only/inspection operation. Used to
# classify MCP tools for plan mode when the server provides no readOnlyHint.
# These are PREFIXES, not whole words (matched via str.startswith below), so a
# stem like "summar" intentionally covers "summarise"/"summarize"/"summary".
_MCP_READONLY_VERBS = (
    "list", "get", "read", "search", "fetch", "query", "find", "describe",
    "show", "view", "lookup", "count", "status", "info", "inspect", "summar",
)


def mcp_tool_is_readonly(tool: Dict) -> bool:
    """Classify an MCP tool as safe (non-mutating) for plan mode.

    Prefer the server's own annotations (readOnlyHint / destructiveHint). When
    absent, fall back to a tool-name verb heuristic, and FAIL CLOSED (treat as
    write) for anything that doesn't clearly read — plan mode must not run a
    write tool just because its intent is ambiguous.
    """
    ann = tool.get("annotations")
    # annotations may be a dict or a pydantic model
    read_hint = None
    destructive = None
    if ann is not None:
        if isinstance(ann, dict):
            read_hint = ann.get("readOnlyHint")
            destructive = ann.get("destructiveHint")
        else:
            read_hint = getattr(ann, "readOnlyHint", None)
            destructive = getattr(ann, "destructiveHint", None)
    if read_hint is True:
        return True
    if read_hint is False or destructive is True:
        return False
    # No usable hint — heuristic on the tool name's leading verb.
    name = (tool.get("name") or "").lower()
    return name.startswith(_MCP_READONLY_VERBS)


class McpManager:
    """Manages MCP server connections and tool routing."""

    def __init__(self):
        # server_id -> connection state
        self._connections: Dict[str, Dict[str, Any]] = {}
        # server_id -> list of tool schemas
        self._tools: Dict[str, List[Dict]] = {}
        # server_id -> MCP ClientSession
        self._sessions: Dict[str, Any] = {}
        # server_id -> exit stack (for cleanup)
        self._stacks: Dict[str, Any] = {}
        # server_id -> background connect task (HTTP transport / OAuth)
        self._connect_tasks: Dict[str, Any] = {}
        # Tracking updates to tools/connections for RAG indexing / prompt cache
        self._generation = 0

    async def connect_server(
        self,
        server_id: str,
        name: str,
        transport: str,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        url: Optional[str] = None,
    ) -> bool:
        """Connect to an MCP server via stdio, SSE, or Streamable HTTP transport."""
        # Every registration path in the product funnels through here — the
        # admin route, `manage_mcp add`, `pantheon-mcp`, `connect_all_enabled`
        # on boot and the built-ins — so the two invariants that the rest of
        # this module assumes are checked once, here, rather than in each of
        # them (`Law 13`).
        #
        # `P8-44`: an id holding `__` does not fail, it MISROUTES — see
        # `validate_mcp_server_id`. `B865`: a non-string args/env entry reaches
        # `StdioServerParameters` and comes back as a pydantic traceback that
        # is shown to the operator as this server's connection error.
        bad = validate_mcp_server_id(server_id)
        if bad is None and transport == "stdio":
            bad = validate_mcp_launch_fields(args, env)
        if bad is not None:
            logger.error("Refusing MCP server %r: %s", name, bad)
            self._connections[str(server_id)] = {
                "status": "error", "error": bad, "name": name,
            }
            self._generation += 1
            return False
        try:
            if transport == "stdio":
                res = await self._connect_stdio(server_id, name, command, args or [], env or {})
            elif transport == "sse":
                res = await self._connect_sse(server_id, name, url)
            elif transport == "http":
                res = await self._start_http_connect(server_id, name, url)
            else:
                logger.error(f"Unknown MCP transport: {transport}")
                res = False
            if res:
                self._generation += 1
            return res
        except Exception as e:
            logger.error(f"Failed to connect MCP server {name} ({server_id}): {e}")
            error_message = _format_mcp_connection_error(name, command or "", args or [], e)
            self._connections[server_id] = {"status": "error", "error": error_message, "name": name}
            self._generation += 1
            return False

    async def _connect_stdio(self, server_id: str, name: str, command: str, args: List[str], env: Dict[str, str]) -> bool:
        """Connect to an MCP server via stdio transport."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from contextlib import AsyncExitStack

            # `P8-42`. This read `{**os.environ, **env} if env else None`, and
            # `None` is not "no overrides" to the SDK — it is a request for
            # `get_default_environment()`, which inherits exactly
            # `DEFAULT_INHERITED_ENV_VARS` = HOME, LOGNAME, PATH, SHELL, TERM,
            # USER (`mcp/client/stdio/__init__.py`). So a server with an EMPTY
            # env dict — the overwhelmingly common case, and the default the
            # form produces — started with `PATH` and `HOME` intact and
            # `PYTHONPATH`, `NODE_PATH`, `NPM_CONFIG_CACHE`, `HTTP_PROXY`,
            # `HTTPS_PROXY` and `NO_PROXY` gone. That is the hard failure to
            # read: the interpreter resolves, the server starts, and then it
            # cannot import its own package or reach the network from behind a
            # corporate proxy — while the same server with one unrelated
            # variable set works, because one entry made the dict truthy.
            #
            # An empty dict now means what it says: no overrides. A server that
            # sets nothing and a server that sets one key inherit the same
            # parent environment.
            server_params = StdioServerParameters(
                command=command,
                args=args,
                env={**os.environ, **(env or {})},
            )

            stack = AsyncExitStack()
            registered = False

            try:
                transport = await stack.enter_async_context(stdio_client(server_params))
                read_stream, write_stream = transport
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))

                # `P8-38`: the handshake's return value used to be dropped here.
                handshake = summarize_initialize_result(await session.initialize())
                tools_result = await session.list_tools()

                tools = _tool_entries(tools_result)

                # Extract identity hints from env vars (e.g. email address, API name)
                # so tool descriptions can distinguish between multiple instances of
                # the same MCP server (e.g. two email accounts).
                identity_hints = []
                for k, v in (env or {}).items():
                    k_lower = k.lower()
                    if any(x in k_lower for x in ["email_address", "account", "user", "username"]):
                        identity_hints.append(v)
                identity = ", ".join(identity_hints) if identity_hints else ""

                self._sessions[server_id] = session
                self._stacks[server_id] = stack
                self._tools[server_id] = tools
                self._connections[server_id] = {
                    "status": "connected",
                    "name": name,
                    "transport": "stdio",
                    "tool_count": len(tools),
                    "identity": identity,
                    **handshake,
                }

                registered = True

            finally:
                if not registered:
                    await stack.aclose()

            logger.info(f"MCP server connected: {name} ({server_id}) - {len(tools)} tools via stdio")
            return True

        except ImportError:
            logger.warning("MCP package not installed. Install with: pip install mcp")
            self._connections[server_id] = {
                "status": "error",
                "error": "mcp package not installed",
                "name": name,
            }
            return False

    async def _connect_sse(self, server_id: str, name: str, url: str) -> bool:
        """Connect to an MCP server via SSE transport."""
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
            from contextlib import AsyncExitStack

            stack = AsyncExitStack()
            registered = False

            try:
                transport = await stack.enter_async_context(sse_client(url))
                read_stream, write_stream = transport
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))

                handshake = summarize_initialize_result(await session.initialize())
                tools_result = await session.list_tools()

                tools = _tool_entries(tools_result)

                self._sessions[server_id] = session
                self._stacks[server_id] = stack
                self._tools[server_id] = tools
                self._connections[server_id] = {
                    "status": "connected",
                    "name": name,
                    "transport": "sse",
                    "tool_count": len(tools),
                    **handshake,
                }

                registered = True

                logger.info(f"MCP server connected: {name} ({server_id}) - {len(tools)} tools via SSE")
                return True

            finally:
                if not registered:
                    await stack.aclose()

        except ImportError:
            logger.warning("MCP package not installed. Install with: pip install mcp")
            self._connections[server_id] = {"status": "error", "error": "mcp package not installed", "name": name}
            return False

    async def _start_http_connect(self, server_id: str, name: str, url: str, wait: float = 8.0) -> bool:
        """Begin a Streamable HTTP connect in the background. Returns within
        `wait` seconds: True if it connected (cached-token path), otherwise the
        flow is awaiting browser authorization and status becomes 'needs_auth'."""
        import asyncio
        self._connections[server_id] = {"status": "connecting", "name": name, "transport": "http"}
        task = asyncio.create_task(self._connect_http(server_id, name, url))
        self._connect_tasks[server_id] = task
        done, _ = await asyncio.wait({task}, timeout=wait)
        if task in done:
            try:
                return task.result()
            except Exception as e:
                self._connections[server_id] = {"status": "error", "error": str(e), "name": name}
                return False
        # Still running → either awaiting authorization, or discovery/DCR is
        # still in flight. If _on_redirect already published needs_auth+auth_url,
        # leave it; otherwise mark needs_auth (auth_url filled in once it fires).
        from src.mcp_oauth import pop_auth_url
        cur = self._connections.get(server_id, {})
        if cur.get("status") != "needs_auth":
            self._connections[server_id] = {
                "status": "needs_auth", "name": name, "transport": "http",
                "auth_url": pop_auth_url(server_id),
            }
        return False

    async def _connect_http(self, server_id: str, name: str, url: str) -> bool:
        """Connect to a Streamable HTTP MCP server (with automatic OAuth)."""
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
            from contextlib import AsyncExitStack
            from src.mcp_oauth import build_provider, clear_auth_url

            def _on_redirect(auth_url):
                # Publish needs_auth the moment the URL is known, independent of
                # how long discovery/DCR took (may exceed the bounded start wait).
                self._connections[server_id] = {
                    "status": "needs_auth", "name": name, "transport": "http",
                    "auth_url": auth_url,
                }

            provider = build_provider(server_id, url, on_redirect=_on_redirect)
            stack = AsyncExitStack()
            transport = await stack.enter_async_context(streamablehttp_client(url, auth=provider))
            read_stream, write_stream, _get_session_id = transport
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            handshake = summarize_initialize_result(await session.initialize())

            tools_result = await session.list_tools()
            tools = _tool_entries(tools_result)

            self._sessions[server_id] = session
            self._stacks[server_id] = stack
            self._tools[server_id] = tools
            self._connections[server_id] = {
                "status": "connected", "name": name, "transport": "http",
                "tool_count": len(tools),
                **handshake,
            }
            clear_auth_url(server_id)
            # Tools changed (this can complete after connect_server already
            # returned, via the background OAuth flow), so bump the generation
            # to invalidate the tool-prompt cache.
            self._generation += 1
            logger.info(f"MCP server connected: {name} ({server_id}) - {len(tools)} tools via http")
            return True
        except ImportError:
            logger.warning("MCP package not installed. Install with: pip install mcp")
            self._connections[server_id] = {"status": "error", "error": "mcp package not installed", "name": name}
            return False
        except Exception as e:
            logger.error(f"Failed to connect HTTP MCP server {name} ({server_id}): {e}")
            self._connections[server_id] = {"status": "error", "error": str(e), "name": name}
            return False

    async def disconnect_server(self, server_id: str):
        """Disconnect from an MCP server."""
        # Cancel any in-flight HTTP/OAuth background connect so it stops
        # publishing status for a server that may be getting deleted.
        task = self._connect_tasks.pop(server_id, None)
        if task is not None and not task.done():
            task.cancel()
        try:
            from src.mcp_oauth import clear_auth_url
            clear_auth_url(server_id)
        except Exception:
            pass

        stack = self._stacks.pop(server_id, None)
        if stack:
            try:
                await stack.aclose()
            except Exception as e:
                logger.warning(f"Error closing MCP server {server_id}: {e}")

        self._sessions.pop(server_id, None)
        self._tools.pop(server_id, None)
        self._connections.pop(server_id, None)
        self._generation += 1
        logger.info(f"MCP server disconnected: {server_id}")

    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        ids = list(self._sessions.keys())
        for sid in ids:
            await self.disconnect_server(sid)


    async def connect_all_enabled(self):
        db = SessionLocal()
        try:
            servers = db.query(McpServer).filter(McpServer.is_enabled == True).all()

            tasks = [
                asyncio.create_task(self._connect_with_timeout(srv))
                for srv in servers
            ]

            await asyncio.gather(*tasks)
        finally:
            db.close()


    async def _connect_with_timeout(self, srv):
        args = json.loads(srv.args) if srv.args else []
        env = json.loads(srv.env) if srv.env else {}

        try:
            await asyncio.wait_for(
                self.connect_server(
                    server_id=srv.id,
                    name=srv.name,
                    transport=srv.transport,
                    command=srv.command,
                    args=args,
                    env=env,
                    url=srv.url,
                ),
                timeout=20,
            )
        except asyncio.TimeoutError:
            logger.warning("Timed out connecting to %s", srv.name)
            self._connections[srv.id] = {
                "status": "timeout",
                "error": f"Timed out after 20 seconds",
                "name": srv.name,
            }

    async def call_tool(
        self,
        qualified_name: str,
        arguments: Dict,
        timeout: Optional[float] = None,
    ) -> Dict:
        """Call an MCP tool by its qualified name (mcp__{server_id}__{tool_name}).

        Returns a result dict compatible with agent_tools format. `timeout` is
        the deadline for this one call in seconds; `None` means
        `MCP_CALL_TIMEOUT_SECONDS` (`P8-37`). Every existing caller passes
        nothing and so inherits the default — which is the point: the hang was
        on the default path.
        """
        parsed = split_mcp_tool_name(qualified_name)
        if parsed is None:
            return {"error": f"Invalid MCP tool name: {qualified_name}", "exit_code": 1}

        server_id, tool_name = parsed

        session = self._sessions.get(server_id)
        if not session:
            return {"error": f"MCP server not connected: {server_id}", "exit_code": 1}

        try:
            result = await self._do_call(session, tool_name, arguments, timeout)
        except McpCallTimeout as e:
            # NOT the reconnect path below. A deadline means the server is
            # answering the socket and not the request; tearing it down and
            # asking again costs a second full deadline for the same silence.
            logger.warning("MCP tool call timed out: %s after %gs", qualified_name, e.timeout)
            return {"error": str(e), "exit_code": 1, "timed_out": True}
        except Exception as e:
            # Auto-reconnect for builtin servers whose subprocess may have died
            if self.is_builtin(server_id):
                logger.warning(f"MCP call failed for {qualified_name}, attempting reconnect: {e}")
                reconnected = await self._reconnect_builtin(server_id)
                if reconnected:
                    session = self._sessions.get(server_id)
                    if session:
                        try:
                            result = await self._do_call(session, tool_name, arguments, timeout)
                        except McpCallTimeout as e2:
                            logger.warning("MCP tool call timed out after reconnect: %s after %gs",
                                           qualified_name, e2.timeout)
                            return {"error": str(e2), "exit_code": 1, "timed_out": True}
                        except Exception as e2:
                            logger.error(f"MCP tool call failed after reconnect: {qualified_name}: {e2}")
                            return {"error": str(e2), "exit_code": 1}
                    else:
                        return {"error": f"Reconnected but no session for {server_id}", "exit_code": 1}
                else:
                    logger.error(f"MCP reconnect failed for {server_id}")
                    return {"error": f"MCP server crashed and reconnect failed: {server_id}", "exit_code": 1}
            else:
                logger.error(f"MCP tool call failed: {qualified_name}: {e}")
                return {"error": str(e), "exit_code": 1}

        return result

    @staticmethod
    async def _send_call(session, tool_name: str, arguments: Dict, deadline: float):
        """Send one `tools/call`, asking the SDK to bound the response wait.

        `read_timeout_seconds` is the SDK's own mechanism (`Law 14`): it stops
        waiting on the response stream and raises `McpError(408)` rather than
        cancelling the caller mid-await, which keeps the session usable for the
        next call. A session object that does not take the argument — an older
        SDK, a test double — still gets the hard bound in `_do_call`.
        """
        if _session_takes_read_timeout(session):
            from datetime import timedelta
            return await session.call_tool(
                tool_name, arguments, read_timeout_seconds=timedelta(seconds=deadline)
            )
        return await session.call_tool(tool_name, arguments)

    async def _do_call(
        self,
        session,
        tool_name: str,
        arguments: Dict,
        timeout: Optional[float] = None,
    ) -> Dict:
        """Execute a single MCP tool call and return result dict.

        Bounded in two layers (`P8-37`). The SDK's `read_timeout_seconds` gets
        the deadline and should fire first; `asyncio.wait_for` gets the
        deadline plus a small grace and is what makes the bound enforceable
        when the SDK's timer cannot see the stall. Either way the caller gets
        `McpCallTimeout`, never a pending await.
        """
        deadline = resolve_mcp_call_timeout(timeout)
        try:
            result = await asyncio.wait_for(
                self._send_call(session, tool_name, arguments, deadline),
                timeout=deadline + _MCP_CALL_TIMEOUT_GRACE,
            )
        except asyncio.TimeoutError:
            raise McpCallTimeout(tool_name, deadline) from None
        except Exception as exc:
            if _is_sdk_read_timeout(exc):
                raise McpCallTimeout(tool_name, deadline) from exc
            raise
        output_parts = []
        images = []
        for content in result.content:
            if hasattr(content, 'text'):
                output_parts.append(content.text)
            elif getattr(content, 'type', '') == 'image' and hasattr(content, 'data'):
                # Image content (e.g. Playwright screenshots)
                mime = getattr(content, 'mimeType', 'image/png')
                images.append({"data": content.data, "mimeType": mime})
                output_parts.append(f"[Screenshot captured ({mime})]")
            elif hasattr(content, 'data'):
                output_parts.append(str(content.data))

        output = "\n".join(output_parts)
        is_error = getattr(result, 'isError', False)

        result_dict = {
            "stdout": output if not is_error else "",
            "stderr": output if is_error else "",
            "exit_code": 1 if is_error else 0,
        }
        if is_error and output:
            result_dict["untrusted_content"] = True
        if images:
            result_dict["images"] = images
        return result_dict

    async def _reconnect_builtin(self, server_id: str) -> bool:
        """Tear down and reconnect a crashed builtin MCP server.

        `P8-43`. This used to consult `_BUILTIN_SERVERS` — the Python-script
        map — and return False for anything else, while `is_builtin` (which
        decides whether this function is even reached) says True for every id
        starting `builtin_`. `builtin_browser` is exactly that gap: a crashed
        Playwright subprocess turned every later call into "MCP server crashed
        and reconnect failed" and stayed dead until a person reconnected it by
        hand. `builtin_connect_spec` is now the one answer to "how does this
        built-in start", and boot and restart both ask it (`Law 14`).

        The npx cache gate that boot applies is deliberately NOT repeated here:
        it exists so a fresh install does not reach the network uninvited
        (`Law 16`), and a server that was running a second ago is by definition
        already on disk.
        """
        from src.builtin_mcp import builtin_connect_spec

        spec = builtin_connect_spec(server_id)
        if spec is None:
            return False

        name = spec["name"]
        if spec["script_path"] and not os.path.exists(spec["script_path"]):
            logger.error(
                f"Cannot reconnect builtin MCP server {name}: "
                f"{spec['script_path']} is missing"
            )
            return False

        # Clean up old connection
        await self.disconnect_server(server_id)

        try:
            ok = await self.connect_server(
                server_id=server_id,
                name=name,
                transport="stdio",
                command=spec["command"],
                args=spec["args"],
                env=spec["env"],
            )
            if ok:
                logger.info(f"Reconnected builtin MCP server: {name}")
            return ok
        except Exception as e:
            logger.error(f"Failed to reconnect builtin MCP server {name}: {e}")
            return False

    def get_all_openai_schemas(self, disabled_map: Optional[Dict[str, set]] = None) -> List[Dict]:
        """Return all MCP tools in OpenAI function-calling format.

        Tool names are namespaced as mcp__{server_id}__{tool_name}.
        disabled_map: optional {server_id: set_of_disabled_tool_names} to filter out.
        """
        schemas = []
        for server_id, tools in self._tools.items():
            # Skip builtin Python servers — they use the code-block tool format
            # But include NPX-based builtins (like browser) which need function calling
            if self.is_builtin(server_id) and server_id != "builtin_browser":
                continue
            conn = self._connections.get(server_id, {})
            server_name = conn.get("name", server_id)
            disabled = (disabled_map or {}).get(server_id, set())

            identity = conn.get("identity", "")
            label = f"{server_name} ({identity})" if identity else server_name

            for tool in tools:
                if tool["name"] in disabled:
                    continue
                qualified = qualify_mcp_tool_name(server_id, tool["name"])
                schema = {
                    "type": "function",
                    "function": {
                        "name": qualified,
                        "description": f"[MCP:{label}] {tool['description']}",
                        "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                    },
                }
                schemas.append(schema)

        return schemas

    def get_all_tools(self, disabled_map: Optional[Dict[str, set]] = None) -> List[Dict]:
        """Return a flat list of all discovered tools with server info.

        `B867`: `annotations` was captured at the connect sites and read by
        `mcp_tool_is_readonly`, and it was never copied onto these entries — so
        **nothing above this manager could see a tool's `readOnlyHint` or
        `destructiveHint`**. Not the tools route, not the browser, not
        `manage_mcp list_tools`. It is here now, beside `is_readonly`, which is
        the manager's own answer to the question the annotation exists to
        answer: is this tool callable in plan mode. Shipping the verdict as
        well as the evidence is deliberate — a consumer that re-derived it from
        the annotation alone would be a second, worse copy of
        `mcp_tool_is_readonly` that disagreed with the gate for every server
        that advertises nothing (`Law 13`).
        """
        result = []
        for server_id, tools in self._tools.items():
            conn = self._connections.get(server_id, {})
            disabled = (disabled_map or {}).get(server_id, set())
            for tool in tools:
                result.append({
                    "server_id": server_id,
                    "server_name": conn.get("name", server_id),
                    "name": tool["name"],
                    "qualified_name": qualify_mcp_tool_name(server_id, tool["name"]),
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema") or {},
                    "annotations": _normalize_annotations(tool.get("annotations")),
                    "is_readonly": mcp_tool_is_readonly(tool),
                    "is_disabled": tool["name"] in disabled,
                })
        return result

    def plan_mode_blocked_mcp(self) -> Tuple[Dict[str, Set[str]], Set[str]]:
        """Plan mode: block every MCP tool that isn't clearly read-only.

        Returns (disabled_map, qualified_names):
          - disabled_map: {server_id: {tool_name, ...}} to hide write tools from
            the prompt/schemas (merged into the existing mcp_disabled_map).
          - qualified_names: {"mcp__<server>__<tool>", ...} for runtime rejection
            in execute_tool_block (which matches the qualified name).
        """
        disabled_map: Dict[str, Set[str]] = {}
        qualified: Set[str] = set()
        for server_id, tools in self._tools.items():
            for tool in tools:
                if not mcp_tool_is_readonly(tool):
                    disabled_map.setdefault(server_id, set()).add(tool["name"])
                    qualified.add(qualify_mcp_tool_name(server_id, tool["name"]))
        return disabled_map, qualified

    def is_builtin(self, server_id: str) -> bool:
        """Check if a server is a built-in (auto-registered) server.

        Derived from `_BUILTIN_SERVERS`, never restated. This set used to be a
        literal here and it held `"memory"` for a day after `B67` removed the
        server from `builtin_mcp.py` — two spellings of one list, which is the
        `Law 13` shape. The divergence was not cosmetic: saying `True` here
        **mutes a server**. Built-in Python servers are skipped from the
        function schemas (`get_all_openai_schemas`) and from the prompt's MCP
        descriptions (`get_tool_descriptions_for_prompt`), and skipped by
        `task_scheduler`'s check-in discovery. So an operator registering their
        own server under a stale id — and `memory` is the id of the canonical
        upstream memory server, so this is a likely id, not a contrived one —
        would have had its tools hidden from both call channels with no error
        anywhere, which is exactly how `B66` went unnoticed.

        NPX built-ins keep the prefix test: their ids all start `builtin_`.
        """
        if server_id.startswith("builtin_"):
            return True
        from src.builtin_mcp import _BUILTIN_SERVERS
        return server_id in _BUILTIN_SERVERS

    def get_server_status(self, server_id: str) -> Dict:
        """Get connection status for a server."""
        return self._connections.get(server_id, {"status": "disconnected"})

    def get_all_statuses(self) -> Dict[str, Dict]:
        """Get connection statuses for all servers."""
        return dict(self._connections)

    _cached_prompt_desc = None
    _cached_prompt_desc_key = None

    def get_tool_descriptions_for_prompt(self, disabled_map: Optional[Dict[str, set]] = None) -> str:
        """Generate text describing MCP tools for the agent system prompt. Cached."""
        cache_key = (
            frozenset((k, frozenset(v)) for k, v in (disabled_map or {}).items()),
            len(self._tools),
            self._generation,
        )
        if self._cached_prompt_desc is not None and self._cached_prompt_desc_key == cache_key:
            return self._cached_prompt_desc
        tools = self.get_all_tools(disabled_map)
        if not tools:
            return ""

        lines = ["\n\nYou also have access to external MCP tool servers. These tools are called via native function calling:"]
        by_server = {}
        for t in tools:
            # Skip builtin Python servers — they're already in the agent prompt
            # But include NPX-based builtins (like browser) which aren't hardcoded
            if self.is_builtin(t["server_id"]) and t["server_id"] != "builtin_browser":
                continue
            if t.get("is_disabled"):
                continue
            sn = t["server_name"]
            if sn not in by_server:
                by_server[sn] = []
            by_server[sn].append(t)

        if not by_server:
            return ""

        for server_name, server_tools in by_server.items():
            # Include identity (e.g. email address) if available
            sid = server_tools[0]["server_id"] if server_tools else ""
            identity = self._connections.get(sid, {}).get("identity", "")
            label = f"{server_name} ({identity})" if identity else server_name
            lines.append(f"\n**{label}:**")
            # `P8-38`. `instructions` is the one field of the initialize
            # handshake the MCP spec writes for the model rather than for the
            # client: the server's own prose on how its tools are meant to be
            # used together. It was discarded at the connect site, so the model
            # had the tool list and never the note that came with it.
            server_instructions = self._connections.get(sid, {}).get("instructions")
            if server_instructions:
                one_line = re.sub(r"\s+", " ", server_instructions).strip()
                if len(one_line) > _MCP_PROMPT_INSTRUCTIONS_MAX:
                    one_line = one_line[:_MCP_PROMPT_INSTRUCTIONS_MAX - 1].rstrip() + "…"
                lines.append(f"  (server instructions: {one_line})")
            for t in server_tools:
                # Truncate long descriptions
                desc = t['description'][:120] + '...' if len(t['description']) > 120 else t['description']
                # Include the tool's declared inputs so the model calls it with
                # real argument names instead of guessing from the description
                # alone (issue #2509).
                args_hint = _format_mcp_params(t.get("input_schema"))
                lines.append(f"  - {t['qualified_name']}: {desc}{args_hint}")

        result = "\n".join(lines)
        self._cached_prompt_desc = result
        self._cached_prompt_desc_key = cache_key
        return result
