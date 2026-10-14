# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reusable proof that Pantheon's whole tool suite reaches the model.

The owner, 2026-10-14, verbatim: *"The LLM's use of tools is still very much
intermittent... even with its own MCP's provided. Ensure its capable of using
Pantheon's entire suite of tooling and skills etc."*

This module is the **measurement**, not the fix. It answers two questions for
every tool in the suite, in one configuration at a time:

  1. **Does it reach the model?** Is the name in the request's `tools` array —
     or, where the route has no native channel, in the fenced prompt — on a
     turn whose text names the tool outright and whose person's privileges
     allow it. A turn that names the tool is the most favourable turn there
     is; a tool that cannot reach the model on *that* turn cannot reach it on
     any.
  2. **Can it be called?** When the model emits a call for it, in each of the
     five shapes a server actually emits, does Pantheon parse it, build a
     `ToolBlock` with that tool's name, and hand it to the dispatcher — or
     refuse it with one sentence a person can read.

Three verdicts, never a boolean (`Law 10`):

  * `reached`  — the name was in the channel this route carries.
  * `held`     — a named gate withheld it, and the gate's own sentence is
                 recorded beside it. **This is a pass.** A tool the person may
                 not use must not be offered, and `FORBIDDEN.md` Part 2 says so.
  * `missing`  — every gate allowed it and it still did not reach the model.
                 That is the defect the owner is describing.

Nothing here is a second opinion about the product's rules. The inventory is
read from `src/tool_schemas.py`'s own register, the MCP names from a real
`McpManager` holding a real stdio server, the skills from `SkillsManager`, and
the gates from `src/tool_security.py`'s own sets — so a tool added tomorrow
appears in the inventory with nobody editing this file, which is the point.

The one seam is the model: there is no model on this machine, so
`stream_llm_with_fallback` is scripted and the request it was handed is
recorded. `drive_turn(..., wire=True)` closes that seam against a recording
OpenAI-compatible server on loopback, so the number this module reports can be
checked against the bytes on the wire (`anchor_matches_wire`).

Run the matrix with `scripts/tool-suite-matrix.py` (one command, prints the
commit — `Law 19`).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── the configuration matrix ────────────────────────────────────────────────

EMBEDDINGS = ("up", "down")
MCP_STATES = ("up", "down", "absent")
WINDOWS = ("large", "medium", "small")
MODES = ("chat", "agent")
PRIVILEGES = ("admin", "user")

#: The window each `WINDOWS` name means, as the endpoint reports it. 18,300
#: tokens is the whole built-in register (`FIX-2026-10-14.md`), so `small` is a
#: window the suite genuinely does not fit and `large` is one it fits twice over.
WINDOW_TOKENS = {"large": 131072, "medium": 32768, "small": 8192}

#: One model name per window so `src/model_context.py`'s per-(url, model) cache
#: holds three answers rather than one.
WINDOW_MODELS = {
    "large": "suite-probe-large",
    "medium": "suite-probe-medium",
    "small": "suite-probe-small",
}


@dataclass(frozen=True)
class Cell:
    """One configuration of the product, named the way the brief names it."""

    embeddings: str = "up"
    mcp: str = "up"
    window: str = "large"
    mode: str = "chat"
    privilege: str = "admin"

    @property
    def id(self) -> str:
        return (f"emb={self.embeddings} mcp={self.mcp} win={self.window} "
                f"mode={self.mode} who={self.privilege}")

    @property
    def model(self) -> str:
        return WINDOW_MODELS[self.window]

    @property
    def admin(self) -> bool:
        return self.privilege == "admin"


def full_matrix() -> List[Cell]:
    """Every cell. 2 x 3 x 3 x 2 x 2 = 72."""
    return [
        Cell(embeddings=e, mcp=m, window=w, mode=d, privilege=p)
        for e in EMBEDDINGS for m in MCP_STATES for w in WINDOWS
        for d in MODES for p in PRIVILEGES
    ]


# ── the inventory, read from the source of truth ────────────────────────────

def builtin_tool_names() -> List[str]:
    """Every built-in, from `FUNCTION_TOOL_SCHEMAS` and nowhere else.

    `Law 7`. A hand-written list is a second register that goes stale the first
    time somebody adds a tool, which is exactly the defect class this harness
    exists to catch.
    """
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    return sorted(
        (entry.get("function") or {}).get("name")
        for entry in FUNCTION_TOOL_SCHEMAS
        if entry.get("type") == "function" and (entry.get("function") or {}).get("name")
    )


def mcp_tool_names(mcp_mgr) -> List[str]:
    """Every registered MCP tool, under its protected qualified name.

    `FORBIDDEN.md` Part 1: `mcp__{server_id}__{tool_name}`.
    """
    if mcp_mgr is None:
        return []
    names: Set[str] = set()
    for schema in mcp_mgr.get_all_openai_schemas() or []:
        name = (schema.get("function") or {}).get("name")
        if name:
            names.add(name)
    return sorted(names)


def skill_names(data_dir: str, owner: Optional[str], *, active_toolsets=None) -> List[str]:
    """Every skill the product would index for this person.

    `SkillsManager.index_for` is what `_build_base_prompt` reads, so this asks
    the same store the same question — not `load()`, which is the Skills window
    and includes the ones a switched-off package holds (`P8-51`).
    """
    try:
        from services.memory.skills import SkillsManager
        from src.agent_loop import TOOL_SECTIONS
    except Exception:
        return []
    sm = SkillsManager(data_dir)
    if active_toolsets is None:
        active_toolsets = list(TOOL_SECTIONS.keys())
    try:
        idx = sm.index_for(owner=owner, active_toolsets=active_toolsets) or []
    except Exception:
        return []
    return sorted({str(s.get("name")) for s in idx if s.get("name")})


@dataclass
class Inventory:
    builtins: List[str]
    mcp: List[str]
    skills: List[str]

    @property
    def tools(self) -> List[str]:
        """Every *tool* — the two things that go in a `tools` array."""
        return list(self.builtins) + list(self.mcp)

    @property
    def total(self) -> int:
        return len(self.builtins) + len(self.mcp) + len(self.skills)

    def kind(self, name: str) -> str:
        if name in set(self.mcp):
            return "mcp"
        if name in set(self.skills):
            return "skill"
        return "builtin"


def suite_inventory(mcp_mgr=None, *, data_dir: Optional[str] = None,
                    owner: Optional[str] = None) -> Inventory:
    """The whole suite, enumerated from the registers the product reads."""
    return Inventory(
        builtins=builtin_tool_names(),
        mcp=mcp_tool_names(mcp_mgr),
        skills=skill_names(data_dir, owner) if data_dir else [],
    )


# ── the gates, asked of the product's own sets ──────────────────────────────

@dataclass(frozen=True)
class Gate:
    name: str
    sentence: str


def gate_holding(tool: str, *, admin: bool, features: Optional[dict] = None,
                 disabled: Optional[Set[str]] = None) -> Optional[Gate]:
    """The gate that withholds `tool` from this person, or None.

    Every answer comes from `src/tool_security.py` — the module the loop and
    the dispatcher both read — so this cannot disagree with the product about
    who may use what. `NON_ADMIN_BLOCKED_REASONS` supplies the sentence, which
    is why "held" can be reported with a reason rather than as a bare False.
    """
    from src import tool_security as ts

    if disabled and tool in disabled:
        return Gate("route disabled_tools", f"`{tool}` is switched off for this route.")
    if not admin and ts.is_public_blocked_tool(tool):
        reason = (getattr(ts, "NON_ADMIN_BLOCKED_REASONS", {}) or {}).get(tool)
        if reason is None and tool.startswith("mcp__"):
            reason = ("an MCP server is an operator-configured capability; a "
                      "non-admin is not offered one")
        return Gate("non-admin policy", reason or "admin-only under public-user policy")
    feature_off = ts.feature_disabled_tools(features) if features is not None else set()
    if tool in feature_off:
        return Gate("feature flag", f"the feature that owns `{tool}` is switched off")
    return None


# ── the loopback endpoint: a window it reports, and a wire to record ────────

class _ProbeHandler(BaseHTTPRequestHandler):
    """`/v1/models` with a declared window, `/v1/chat/completions` recorded."""

    server_version = "ToolSuiteProbe/1"

    def log_message(self, *a):  # keep the harness quiet
        pass

    def _json(self, code: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"object": "list", "data": [
                {"id": name, "object": "model", "context_length": tokens,
                 "max_model_len": tokens}
                for window, name in WINDOW_MODELS.items()
                for tokens in (WINDOW_TOKENS[window],)
            ]})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:
            body = {"_unparsed": raw.decode("utf-8", "replace")}
        self.server.recorded.append(body)  # type: ignore[attr-defined]
        reply = self.server.reply  # type: ignore[attr-defined]
        if body.get("stream"):
            chunks = [
                "data: " + json.dumps({
                    "choices": [{"index": 0, "delta": {"content": reply}}],
                }) + "\n\n",
                "data: " + json.dumps({
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }) + "\n\n",
                "data: [DONE]\n\n",
            ]
            payload = "".join(chunks).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self._json(200, {
            "id": "probe", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": reply},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })


class ProbeEndpoint:
    """A loopback OpenAI-compatible server: declares a window, records bodies."""

    def __init__(self, port: int = 0):
        self._srv = ThreadingHTTPServer(("127.0.0.1", port), _ProbeHandler)
        self._srv.recorded = []            # type: ignore[attr-defined]
        self._srv.reply = "Nothing to do." # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._srv.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def recorded(self) -> List[dict]:
        return self._srv.recorded  # type: ignore[attr-defined]

    def clear(self):
        self.recorded.clear()

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()
        self._thread.join(timeout=5)


# ── a real MCP server, in three states ──────────────────────────────────────

MCP_SERVER_SOURCE = '''# SPDX-License-Identifier: AGPL-3.0-or-later
"""A real stdio MCP server for the tool-suite probe. Two read-only tools."""
import sys
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("suite-probe")


@mcp.tool()
def probe_echo(text: str) -> str:
    """Echo a string back. Read-only; exists so a call can be driven for real."""
    return f"probe_echo: {text}"


@mcp.tool()
def probe_inventory(kind: str = "all") -> str:
    """List what this probe server holds. Read-only."""
    return f"probe_inventory: {kind}"


if __name__ == "__main__":
    mcp.run()
'''


def write_mcp_server(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "suite_probe_mcp.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(MCP_SERVER_SOURCE)
    return path


async def build_mcp_manager(state: str, script_path: str):
    """A real `McpManager` in the state this cell asks for.

    `up` — a real stdio server, connected, serving two tools.
    `down` — registered through the same `connect_server` and not answering,
             which is the state a person's install is in when the command is
             wrong or the dependency is missing.
    `absent` — no manager at all, the native install with nothing registered.
    """
    if state == "absent":
        return None
    from src.mcp_manager import McpManager

    mgr = McpManager()
    if state == "up":
        await mgr.connect_server("probe", "suite-probe", "stdio",
                                 command=sys.executable, args=[script_path], env={})
    else:
        # A command that exits at once: registered, never answers.
        await mgr.connect_server("probe", "suite-probe", "stdio",
                                 command="/bin/false", args=[], env={})
    return mgr


# ── the world one cell runs in ──────────────────────────────────────────────

ADMIN_USER = "probe-admin"
PLAIN_USER = "probe-user"

#: Skills written into the throwaway store so the skills half of the suite has
#: something to be about. One per tool family so a reach failure names a family.
PROBE_SKILLS = [
    ("probe-email-triage", "email", ["list_emails", "read_email"],
     "Triage the inbox: list the newest mail, read what matters, say what needs a reply."),
    ("probe-file-sweep", "files", ["ls", "grep", "read_file"],
     "Sweep a folder: list it, grep for the pattern, read the files that matched."),
    ("probe-web-dig", "web", ["web_search", "web_fetch"],
     "Dig on the web: search, fetch the best page, quote what it said."),
    ("probe-note-keeping", "notes", ["manage_notes", "manage_tasks"],
     "Keep notes: write the note, then the task it implies."),
]


@dataclass
class ProbeWorld:
    """A throwaway install: data dir, accounts, skills, MCP server, endpoint."""

    data_dir: str
    endpoint: ProbeEndpoint
    mcp_script: str
    managers: Dict[str, Any] = field(default_factory=dict)
    features: Dict[str, Any] = field(default_factory=dict)

    def owner(self, cell: Cell) -> str:
        return ADMIN_USER if cell.admin else PLAIN_USER

    def manager(self, cell: Cell):
        return self.managers.get(cell.mcp)


def _seed_accounts(data_dir: str) -> None:
    """A real admin and a real non-admin, through `AuthManager`'s own doors.

    Without this the install is in its pre-setup window, where
    `owner_is_admin_or_single_user` answers False for everybody and the
    non-admin policy holds two thirds of the register — true, and not the
    thing being measured.
    """
    from core.auth import AuthManager

    auth = AuthManager(os.path.join(data_dir, "auth.json"))
    if not auth.is_configured:
        auth.setup(ADMIN_USER, "probe-password-1")
    auth.create_user(PLAIN_USER, "probe-password-2", is_admin=False)


def _seed_skills(data_dir: str) -> None:
    from services.memory.skills import SkillsManager

    sm = SkillsManager(data_dir)
    for name, category, toolsets, body in PROBE_SKILLS:
        try:
            sm.add_skill(
                name=name,
                description=body,
                category=category,
                when_to_use=body,
                procedure=["Do the first thing.", "Report what happened."],
                requires_toolsets=list(toolsets),
                status="published",
                source="user",
                owner=ADMIN_USER,
            )
        except Exception:
            # The store's own validation is the authority on what a skill is;
            # a refusal here is reported by the inventory being short, not
            # papered over.
            pass


@contextmanager
def probe_world(scratch: str, *, mcp_states: Sequence[str] = MCP_STATES):
    """Build the world, hand it over, tear every process down by its own handle."""
    data_dir = os.path.join(scratch, "data")
    os.makedirs(data_dir, exist_ok=True)
    _seed_accounts(data_dir)
    _seed_skills(data_dir)
    script = write_mcp_server(os.path.join(scratch, "mcp"))
    endpoint = ProbeEndpoint()
    world = ProbeWorld(data_dir=data_dir, endpoint=endpoint, mcp_script=script)
    loop = asyncio.new_event_loop()
    try:
        for state in mcp_states:
            world.managers[state] = loop.run_until_complete(
                build_mcp_manager(state, script))
        yield world
    finally:
        for mgr in world.managers.values():
            if mgr is not None:
                try:
                    loop.run_until_complete(mgr.disconnect_all())
                except Exception:
                    pass
        try:
            loop.close()
        except Exception:
            pass
        endpoint.stop()


# ── the five reply shapes a local server actually emits ─────────────────────

def reply_shapes(tool: str, args: dict) -> Dict[str, Any]:
    """The five shapes `fx6-tools` measured, keyed by name.

    `native` is the OpenAI `tool_calls` channel (a dict the harness feeds the
    loop's own reader). The other four are **content**: what a server emits
    when its chat template's tool section does not fire, which is the only
    channel on a route that carries no `tools` array at all.
    """
    body = json.dumps({"name": tool, "arguments": args})
    return {
        "native": {"type": "tool_calls",
                   "calls": [{"name": tool, "arguments": json.dumps(args)}]},
        "xml": f"<tool_call>{body}</tool_call>",
        "leaked_function": json.dumps(
            {"function": {"name": tool, "arguments": json.dumps(args)}}),
        "bare_json": body,
        "fenced": f"```{tool}\n{json.dumps(args)}\n```",
    }


REPLY_SHAPES = ("native", "xml", "leaked_function", "bare_json", "fenced")


# ── the four request shapes the suite has to survive ────────────────────────

def request_shapes(tools: Optional[List[dict]], prompt: str, model: str) -> Dict[str, List[str]]:
    """The tool names each provider shape would carry, from one captured request.

    Asked of `src/llm_core.py`'s own builders, so this is what the provider is
    sent and not a second rendering of it:

      * `openai`    — the `tools` array as the OpenAI-compatible payload carries it;
      * `anthropic` — `_build_anthropic_payload`'s `tools`, with `input_schema`;
      * `harmony`   — `_alias_harmony_tools` applied, the gpt-oss surface, where
                      a colliding built-in name is renamed on the way out;
      * `fenced`    — the names the prompt itself advertises, which is the only
                      channel on a route that carries no array.
    """
    from src import llm_core

    out: Dict[str, List[str]] = {}
    tools = list(tools or [])
    out["openai"] = sorted(
        (t.get("function") or {}).get("name") for t in tools
        if (t.get("function") or {}).get("name"))
    anthropic = llm_core._build_anthropic_payload(
        model, [{"role": "user", "content": "x"}], 0.3, 1024, tools=tools)
    out["anthropic"] = sorted(
        t.get("name") for t in (anthropic.get("tools") or []) if t.get("name"))
    harmony = llm_core._alias_harmony_tools(tools, "gpt-oss-20b") or []
    out["harmony"] = sorted(
        (t.get("function") or {}).get("name") for t in harmony
        if (t.get("function") or {}).get("name"))
    out["fenced"] = sorted(prompt_tool_names(prompt))
    return out


REQUEST_SHAPES = ("openai", "anthropic", "harmony", "fenced")

_BACKTICKED = re.compile(r"`([a-z][a-z0-9_]{2,60})`")
_FENCE_TAG = re.compile(r"```([a-z][a-z0-9_]{2,60})")


def prompt_tool_names(prompt: str) -> Set[str]:
    """Tool names the prompt itself names — the fenced channel's advertisement.

    Both spellings the prompt uses: a backticked name and a fence tag. Filtered
    against the register (`known_tool_names`) plus the qualified MCP shape, so
    an English word in backticks is not counted as a tool (`Law 20`: the shape,
    not the word).
    """
    try:
        from src.tool_policy import known_tool_names
        known = set(known_tool_names())
    except Exception:
        known = set()
    found: Set[str] = set()
    for match in _BACKTICKED.findall(prompt) + _FENCE_TAG.findall(prompt):
        if match in known or match.startswith("mcp__"):
            found.add(match)
    # Qualified MCP names carry `__`, which the backtick pattern catches, but
    # the prompt also lists them bare in the MCP block.
    for match in re.findall(r"\bmcp__[a-z0-9_-]{1,64}__[A-Za-z0-9_-]{1,64}\b", prompt):
        found.add(match)
    return found


# ── driving one turn of the real loop ───────────────────────────────────────

@dataclass
class TurnRecord:
    """What one turn of the real loop sent, and what came back."""

    requests: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    dispatched: List[Tuple[str, str]]
    seconds: float

    @property
    def first(self) -> Dict[str, Any]:
        return self.requests[0] if self.requests else {"tools": [], "prompt": "", "schemas": []}

    def shapes(self, model: str) -> Dict[str, List[str]]:
        return request_shapes(self.first.get("schemas"), self.first.get("prompt", ""), model)

    def offered(self) -> Set[str]:
        return set(self.first.get("tools") or [])

    def blocked_sentences(self) -> List[str]:
        out = []
        for ev in self.events:
            if ev.get("type") in ("tool_blocked", "tool_output"):
                text = ev.get("reason") or ev.get("message") or ev.get("output") or ""
                if text:
                    out.append(str(text))
        return out


def _pantheon_prompt(messages: Sequence[dict], injected: Set[str]) -> str:
    """Everything in the request that Pantheon wrote, and nothing the probe did.

    The prompt channel is the only one a fenced route has, so "is the tool
    named in the prompt" is a real reach question — but the probe's own turn
    text names the tool in backticks, and counting that would make every tool
    reach the model in every cell. The messages the probe put in are dropped by
    content; everything Pantheon added, including the MCP block and the skills
    catalogue it ships as `user`-role context messages, is kept.
    """
    return "\n".join(
        m.get("content") for m in messages
        if isinstance(m.get("content"), str) and m.get("content") not in injected
    )


def drive_turn(world: ProbeWorld, cell: Cell, text: str, *,
               script: Optional[Sequence[Any]] = None,
               dispatch: str = "boundary",
               wire: bool = False,
               max_rounds: Optional[int] = None,
               disabled_tools: Optional[Set[str]] = None) -> TurnRecord:
    """Run one turn of the product's own loop in this cell. Nothing is stubbed
    except the model, and `dispatch="real"` removes even the dispatcher stub.

    `script` is what the model says, in order: a string is text, anything else
    is fed to the loop's own stream reader as a `data:` frame (so the five
    reply shapes are driven through the code that reads them, not around it).

    `dispatch="boundary"` records the `ToolBlock` the loop handed
    `execute_tool_block` and answers with a canned result — the seam
    `tests/test_an_ai_step_uses_only_its_tools.py` uses, and the right one for
    a tool whose real call writes to the operator's machine. `dispatch="real"`
    calls the product's dispatcher. **The approval gate is never stood down in
    either mode** (`FORBIDDEN.md` Part 2): a held call is a recorded verdict,
    not a failure to work around.
    """
    import src.agent_loop as al
    from src.tool_policy import ToolPolicy

    requests: List[Dict[str, Any]] = []
    dispatched: List[Tuple[str, str]] = []
    steps = list(script or ["Nothing to do."])
    cursor = iter(steps)

    async def scripted(candidates, messages, **kwargs):
        schemas = list(kwargs.get("tools") or [])
        requests.append({
            "tools": sorted((t.get("function") or {}).get("name") for t in schemas
                            if (t.get("function") or {}).get("name")),
            "schemas": schemas,
            "prompt": _pantheon_prompt(messages, injected),
            "has_tools_key": "tools" in kwargs and kwargs.get("tools") is not None,
        })
        step = next(cursor, "All done.")
        if isinstance(step, str):
            yield "data: " + json.dumps({"delta": step}) + "\n\n"
        else:
            yield "data: " + json.dumps(step) + "\n\n"
        yield "data: [DONE]\n\n"

    real_execute = al.execute_tool_block

    async def boundary(block, *a, **k):
        dispatched.append((getattr(block, "tool_type", "?"), getattr(block, "content", "")))
        return getattr(block, "tool_type", "?"), {"output": "probe-ok", "exit_code": 0}

    async def recording_real(block, *a, **k):
        dispatched.append((getattr(block, "tool_type", "?"), getattr(block, "content", "")))
        return await real_execute(block, *a, **k)

    saved_stream = al.stream_llm_with_fallback
    saved_exec = al.execute_tool_block
    saved_mcp = al.get_mcp_manager
    if not wire:
        al.stream_llm_with_fallback = scripted
    al.execute_tool_block = recording_real if dispatch == "real" else boundary
    mgr = world.manager(cell)
    al.get_mcp_manager = lambda: mgr

    # Chat mode and Agent mode are one route and one loop: `routes/chat_routes.py`
    # passes `agent_mode=(chat_mode == "agent")` into `build_chat_context`, and
    # the two things it decides there are the preface `build_context_preface`
    # assembles and — `routes/chat_helpers.py:1102` — whether the current
    # date/time context message is inserted before the latest user turn. Chat
    # mode inserts it; Agent mode does not. So the mode is carried here as the
    # message the route would have built, from the product's own function, and
    # not as a flag this harness invented.
    turn: List[Dict[str, Any]] = [{"role": "user", "content": text}]
    if cell.mode == "chat":
        try:
            from src.user_time import current_datetime_context_message
            turn.insert(0, current_datetime_context_message())
        except Exception:
            pass
    injected = {m["content"] for m in turn if isinstance(m.get("content"), str)}

    async def collect():
        out = []
        async for chunk in al.stream_agent_loop(
            world.endpoint.url,
            cell.model,
            turn,
            max_rounds=max_rounds or (len(steps) + 1),
            owner=world.owner(cell),
            disabled_tools=set(disabled_tools or ()),
            tool_policy=ToolPolicy(),
            context_length=WINDOW_TOKENS[cell.window],
            prompt_type="agent" if cell.mode == "agent" else None,
        ):
            out.append(chunk)
        return out

    started = time.time()
    try:
        chunks = asyncio.run(collect())
    finally:
        al.stream_llm_with_fallback = saved_stream
        al.execute_tool_block = saved_exec
        al.get_mcp_manager = saved_mcp
    elapsed = time.time() - started

    events = []
    for chunk in chunks:
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                events.append(json.loads(chunk[6:]))
            except Exception:
                pass
    if wire:
        for body in world.endpoint.recorded:
            schemas = list(body.get("tools") or [])
            requests.append({
                "tools": sorted((t.get("function") or {}).get("name") for t in schemas
                                if (t.get("function") or {}).get("name")),
                "schemas": schemas,
                "prompt": _pantheon_prompt(body.get("messages") or [], injected),
                "has_tools_key": "tools" in body,
            })
    return TurnRecord(requests=requests, events=events, dispatched=dispatched,
                      seconds=elapsed)


# ── question 1: does every tool reach the model? ────────────────────────────

def naming_turn(tool: str, *, inventory: Optional[Inventory] = None) -> str:
    """A turn whose text names the tool outright — the best case there is.

    Deliberately not a paraphrase. The question is not whether retrieval ranks
    a tool for a vague request; it is whether a tool can reach the model *at
    all* in this configuration. A turn that says the name and asks for the
    tool's own job is the turn on which a `missing` verdict cannot be explained
    away.
    """
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS

    described = (BUILTIN_TOOL_DESCRIPTIONS.get(tool) or "").strip()
    first_sentence = described.split(".")[0][:160] if described else ""
    plain = tool.replace("_", " ")
    if tool.startswith("mcp__"):
        return (f"Use the MCP tool `{tool}` now. Call {tool} to do its job on "
                f"this request.")
    if first_sentence:
        return f"Use the `{tool}` tool now: {first_sentence}. Call {tool}."
    return f"Use the `{tool}` tool now — {plain}. Call {tool}."


@dataclass
class ReachRow:
    tool: str
    kind: str
    verdict: str                  # reached | held | missing
    channels: List[str]           # the request shapes that carried it
    gate: Optional[str] = None
    sentence: Optional[str] = None


def reach_report(world: ProbeWorld, cell: Cell, inventory: Inventory, *,
                 names: Optional[Sequence[str]] = None) -> List[ReachRow]:
    """For every tool: `reached`, `held` (with the gate's sentence), or `missing`."""
    from src.settings import load_features

    try:
        features = load_features()
    except Exception:
        features = {}
    rows: List[ReachRow] = []
    for tool in (names if names is not None else inventory.tools):
        gate = gate_holding(tool, admin=cell.admin, features=features)
        record = drive_turn(world, cell, naming_turn(tool))
        shapes = record.shapes(cell.model)
        carried = [shape for shape in REQUEST_SHAPES if tool in set(shapes[shape])]
        if carried:
            verdict = "reached"
        elif gate is not None:
            verdict = "held"
        else:
            verdict = "missing"
        rows.append(ReachRow(tool=tool, kind=inventory.kind(tool), verdict=verdict,
                             channels=carried,
                             gate=gate.name if gate else None,
                             sentence=gate.sentence if gate else None))
    return rows


def skill_reach(world: ProbeWorld, cell: Cell, inventory: Inventory) -> List[ReachRow]:
    """A skill reaches the model when the catalogue the loop injects names it.

    Driven through the loop, because `suppress_skills`, the low-signal
    predicate and the toolset gate are all decided there and a direct call to
    `render_skill_index_block` would answer a question nobody asked.
    """
    rows: List[ReachRow] = []
    if not inventory.skills:
        return rows
    record = drive_turn(
        world, cell,
        "Follow the relevant saved skill for this: triage my email, sweep the "
        "project folder, dig on the web and keep notes about what you find.")
    text = "\n".join(
        [record.first.get("prompt", "")]
        + [json.dumps(ev) for ev in record.events if ev.get("type") == "skills_injected"])
    for name in inventory.skills:
        rows.append(ReachRow(
            tool=name, kind="skill",
            verdict="reached" if name in text else "missing",
            channels=["prompt"] if name in text else []))
    return rows


# ── question 2: can every tool be called? ──────────────────────────────────

#: Tools driven to the **dispatch boundary** rather than executed, because a
#: real call writes to the operator's machine, spends money, sends mail, or
#: starts a subprocess. The verdict for these is "Pantheon parsed the call,
#: built a `ToolBlock` for this tool and handed it to the dispatcher".
DESTRUCTIVE = frozenset({
    "api_call", "app_api", "apply_patch", "archive_email", "ask_teacher", "bash",
    "bulk_email", "cancel_download", "chat_with_model", "computer",
    "create_document", "create_session", "delete_email", "download_model",
    "edit_document", "edit_file", "edit_image", "generate_image", "host_shell",
    "manage_endpoints", "manage_mcp", "manage_session", "manage_settings",
    "manage_tokens", "manage_webhooks", "mark_email_read", "pipeline", "python",
    "reply_to_email", "send_email", "send_to_session", "serve_model",
    "serve_preset", "stop_served_model", "suggest_document", "trigger_research",
    "ui_control", "unsubscribe_email", "update_document", "web_fetch",
    "web_search", "write_file",
})

#: An argument a tool's own schema will accept enough of to route. Empty is the
#: default: a handler that refuses a missing argument with its own sentence has
#: still *run*, which is the thing being proven, and nothing happens.
CALL_ARGS: Dict[str, dict] = {
    "mcp__probe__probe_echo": {"text": "probe"},
    "mcp__probe__probe_inventory": {"kind": "all"},
}


@dataclass
class CallRow:
    tool: str
    kind: str
    shape: str
    verdict: str          # answered | refused | held | dropped
    detail: str = ""


def _call_verdict(record: TurnRecord, tool: str) -> Tuple[str, str]:
    """Read the loop's own events for what became of the call."""
    saw_block = any(name == tool for name, _ in record.dispatched)
    blocked = [ev for ev in record.events if ev.get("type") == "tool_blocked"]
    outputs = [ev for ev in record.events if ev.get("type") == "tool_output"]
    if saw_block:
        for ev in outputs:
            text = str(ev.get("output") or ev.get("result") or "")
            if "Unknown tool" in text:
                return "dropped", text[:160]
        if blocked:
            return "held", str(blocked[0].get("reason") or blocked[0].get("message") or "")[:160]
        if outputs:
            return "answered", str(outputs[0].get("output") or "")[:160]
        return "answered", "dispatched"
    if blocked:
        return "held", str(blocked[0].get("reason") or blocked[0].get("message") or "")[:160]
    for ev in outputs:
        text = str(ev.get("output") or ev.get("result") or "")
        if text:
            return "refused", text[:160]
    return "dropped", "no ToolBlock reached the dispatcher"


def call_report(world: ProbeWorld, cell: Cell, inventory: Inventory, *,
                shapes: Sequence[str] = REPLY_SHAPES,
                names: Optional[Sequence[str]] = None,
                real: bool = False) -> List[CallRow]:
    """For every tool and every reply shape: was the call parsed, routed, answered?"""
    rows: List[CallRow] = []
    for tool in (names if names is not None else inventory.tools):
        args = CALL_ARGS.get(tool, {})
        drive_real = real and tool not in DESTRUCTIVE and not tool.startswith("mcp__")
        for shape in shapes:
            step = reply_shapes(tool, args)[shape]
            record = drive_turn(world, cell, naming_turn(tool),
                                script=[step, "Done."],
                                dispatch="real" if drive_real else "boundary",
                                max_rounds=3)
            verdict, detail = _call_verdict(record, tool)
            rows.append(CallRow(tool=tool, kind=inventory.kind(tool), shape=shape,
                                verdict=verdict, detail=detail))
    return rows


def unknown_name_control(world: ProbeWorld, cell: Cell) -> CallRow:
    """The control that must never be stood down: a name nobody registered is
    refused, not silently dropped and not routed."""
    bogus = "definitely_not_a_pantheon_tool"
    record = drive_turn(world, cell, "Do the thing.",
                        script=[reply_shapes(bogus, {})["native"], "Done."],
                        max_rounds=3)
    routed = any(name == bogus for name, _ in record.dispatched)
    said = " ".join(str(ev.get("output") or ev.get("reason") or "")
                    for ev in record.events
                    if ev.get("type") in ("tool_output", "tool_blocked"))
    if routed:
        return CallRow(bogus, "control", "native", "dropped", "an unknown name was dispatched")
    return CallRow(bogus, "control", "native",
                   "refused" if said else "dropped", said[:160])


# ── the matrix ─────────────────────────────────────────────────────────────

#: The turn the variance measurement repeats: an ordinary request that names no
#: tool, trips no keyword list and asks for something a person would actually
#: ask for. The point is what the suite offers on a *normal* turn.
ORDINARY_TURN = (
    "Can you help me work out what to do about the leaking pipe under the "
    "kitchen sink before the weekend?"
)

#: One turn per domain, run once each, so the table can say *which* of the
#: suite reached the model and how much the answer depends on the wording.
#: `owner` is the owner's own question from
#: `/work/notes/owner-shots/2026-10-09-osrs-chat-export.md`, verbatim — note
#: that it contains the word "archive", which `_ADMIN_KEYWORDS` matches as a
#: substring, so it is also the turn that shows the admin force-include.
SAMPLE_TURNS: Dict[str, str] = {
    "plain": ORDINARY_TURN,
    "owner": ("Research: Find out the ins and outs of the new Oldschool RuneScape "
              "Raids releasing on October 20th... its called the fractured archive. "
              "I mostly want to know, what are we going to expect to fight, and a "
              "strategy to defeat the mobs."),
    "email": "What came in overnight that I need to answer?",
    "files": "Have a look through the project and tell me what the build does.",
    "mcp": "Use my own MCP server to look this up for me.",
    "skill": "Do the thing we worked out last time for triaging my inbox.",
}


@dataclass
class CellResult:
    cell: Cell
    suite: int
    builtins: int
    mcp: int
    skills: int
    #: One set of offered names per repeat of the ordinary turn.
    repeats: List[List[str]]
    #: One set of offered names per sample turn — the spread across wordings.
    turns: Dict[str, List[str]] = field(default_factory=dict)
    reach: List[ReachRow] = field(default_factory=list)
    skill_rows: List[ReachRow] = field(default_factory=list)
    calls: List[CallRow] = field(default_factory=list)
    control: Optional[CallRow] = None
    seconds: float = 0.0

    @property
    def ordinary_counts(self) -> List[int]:
        return [len(r) for r in self.repeats]

    @property
    def identical(self) -> bool:
        """Is the offered set the same on every repeat of this one cell?"""
        if len(self.repeats) < 2:
            return True
        first = set(self.repeats[0])
        return all(set(r) == first for r in self.repeats[1:])

    @property
    def drift(self) -> List[str]:
        """Names that were offered on some repeats of this cell and not others."""
        if not self.repeats:
            return []
        sets = [set(r) for r in self.repeats]
        everywhere = set.intersection(*sets)
        anywhere = set.union(*sets)
        return sorted(anywhere - everywhere)

    @property
    def reached(self) -> int:
        return sum(1 for r in self.reach if r.verdict == "reached")

    @property
    def held(self) -> int:
        return sum(1 for r in self.reach if r.verdict == "held")

    @property
    def missing(self) -> List[str]:
        return [r.tool for r in self.reach if r.verdict == "missing"]

    @property
    def uncallable(self) -> List[str]:
        return sorted({f"{r.tool}/{r.shape}" for r in self.calls if r.verdict == "dropped"})

    @property
    def turn_spread(self) -> str:
        """`n` per sample turn, and how many distinct sets the six produced."""
        if not self.turns:
            return "—"
        counts = ", ".join(f"{label} {len(names)}" for label, names in self.turns.items())
        distinct = len({tuple(v) for v in self.turns.values()})
        return f"{counts} ({distinct} distinct sets)"


def run_cell(world: ProbeWorld, cell: Cell, *, repeats: int = 5,
             reach: bool = True, calls: bool = False,
             call_names: Optional[Sequence[str]] = None,
             real_calls: bool = False) -> CellResult:
    """One cell, measured. The product is built once and driven many times."""
    started = time.time()
    inventory = suite_inventory(world.manager(cell), data_dir=world.data_dir,
                               owner=world.owner(cell))
    offered_repeats = []
    for _ in range(repeats):
        record = drive_turn(world, cell, ORDINARY_TURN)
        offered_repeats.append(sorted(record.offered()))
    turns = {}
    for label, text in SAMPLE_TURNS.items():
        turns[label] = sorted(drive_turn(world, cell, text).offered())
    result = CellResult(
        cell=cell, suite=inventory.total, builtins=len(inventory.builtins),
        mcp=len(inventory.mcp), skills=len(inventory.skills),
        repeats=offered_repeats, turns=turns,
    )
    if reach:
        result.reach = reach_report(world, cell, inventory)
        result.skill_rows = skill_reach(world, cell, inventory)
    if calls:
        result.calls = call_report(world, cell, inventory, names=call_names,
                                   real=real_calls)
        result.control = unknown_name_control(world, cell)
    result.seconds = time.time() - started
    return result


# ── the table ──────────────────────────────────────────────────────────────

def commit_sha() -> str:
    """The tree this run is evidence about, and nothing else (`Law 19`)."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=20)
        sha = (out.stdout or "").strip()[:12] or "unknown"
    except Exception:
        return "unknown"
    try:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                               capture_output=True, text=True, timeout=30)
        if (dirty.stdout or "").strip():
            return sha + " (tree dirty — this run is evidence about nothing frozen)"
    except Exception:
        pass
    return sha


def render_table(results: Sequence[CellResult]) -> str:
    """The matrix, as the brief asks for it. Every number here was measured."""
    head = ("| cell | suite | ordinary turn | spread over 6 turns | reached by name | "
            "held (gate) | missing | identical over repeats |")
    rule = "|---|---|---|---|---|---|---|---|"
    lines = [head, rule]
    for res in results:
        counts = res.ordinary_counts
        span = (f"{min(counts)}" if len(set(counts)) == 1
                else f"{min(counts)}–{max(counts)}") if counts else "—"
        missing = res.missing
        miss = "0" if not missing else f"{len(missing)} ({', '.join(missing[:4])}" + (
            ", …)" if len(missing) > 4 else ")")
        spread = "—"
        if res.turns:
            sizes = sorted(len(v) for v in res.turns.values())
            distinct = len({tuple(v) for v in res.turns.values()})
            spread = f"{sizes[0]}–{sizes[-1]}, {distinct} distinct sets"
        lines.append(
            f"| {res.cell.id} | {res.suite} | {span}/{res.builtins + res.mcp} | "
            f"{spread} | {res.reached} | {res.held} | {miss} | "
            f"{'yes' if res.identical else 'NO — ' + ', '.join(res.drift[:4])} |")
    return "\n".join(lines)


def render_summary(results: Sequence[CellResult], *, seconds: float) -> str:
    lines = [
        f"commit: {commit_sha()}",
        f"cells: {len(results)}   wall clock: {seconds:.1f}s",
    ]
    if results:
        first = results[0]
        lines.append(
            f"suite enumerated: {first.builtins} built-ins "
            f"(src/tool_schemas.py FUNCTION_TOOL_SCHEMAS) + up to {max(r.mcp for r in results)} "
            f"MCP tools + {max(r.skills for r in results)} skills")
        varying = [r.cell.id for r in results if not r.identical]
        lines.append(f"cells whose offered set varied across repeats: {len(varying)}")
        every_missing: Dict[str, int] = {}
        for res in results:
            for name in res.missing:
                every_missing[name] = every_missing.get(name, 0) + 1
        lines.append(f"tools missing in at least one cell: {len(every_missing)}")
        skills_missing = {r.tool for res in results for r in res.skill_rows
                          if r.verdict == "missing"}
        lines.append(f"skills that did not reach the model in some cell: {len(skills_missing)}")
        dropped = sorted({f"{r.tool}/{r.shape}" for res in results for r in res.calls
                          if r.verdict == "dropped"})
        lines.append(f"tool/shape pairs a call was dropped on: {len(dropped)}")
    return "\n".join(lines)
