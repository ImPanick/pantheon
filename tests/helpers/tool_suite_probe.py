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
from contextlib import asynccontextmanager, contextmanager
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

#: The `pantheon-qwen3` finetune, under its own name and the same three windows
#: (`fx11-order`). `src/agent_loop._is_pantheon_qwen_model` is a prefix test on
#: the model's **name**, which is the whole of how a turn reaches the three
#: finetune modes — so a probe that cannot name the model cannot reach them at
#: all, and `B1353` (fx11-order) lives in exactly one of them. The windows are
#: `WINDOW_TOKENS`' so the endpoint reports a real one and the planner's `room`
#: is not the `window_unknown` branch (`D-2026-10-07-02` §1: a window is read
#: from the endpoint, never from the name).
FINETUNE_MODELS = {
    "large": "pantheon-qwen3-8b",
    "medium": "pantheon-qwen3-8b-medium",
    "small": "pantheon-qwen3-8b-small",
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


def split_name(qualified: str):
    """`split_mcp_tool_name`, re-exported so a test asks the product's own rule.

    `FORBIDDEN.md` Part 1 owns the `mcp__{server_id}__{tool_name}` shape and
    `src/mcp_manager.py` owns the rule that decides whether a string is one.
    A second regex here would be a second rule (`Law 7`).
    """
    from src.mcp_manager import split_mcp_tool_name

    return split_mcp_tool_name(qualified)


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
        from src.agent_loop import _skill_active_toolsets
    except Exception:
        return []
    sm = SkillsManager(data_dir)
    if active_toolsets is None:
        # `B1381`. The product's own gate for a turn that withholds nothing,
        # asked rather than restated: it was `TOOL_SECTIONS`, and the helper
        # copied it.
        active_toolsets = _skill_active_toolsets(set())
    try:
        idx = sm.index_for(owner=owner, active_toolsets=active_toolsets) or []
    except Exception:
        return []
    return sorted({str(s.get("name")) for s in idx if s.get("name")})


def tools_with_no_prompt_section() -> List[str]:
    """Register names that `TOOL_SECTIONS` has no prose for.

    Until `B1381` this was a gate: `_build_base_prompt` handed
    `set(TOOL_SECTIONS) - disabled` to `SkillsManager.index_for`, which drops
    any skill whose `requires_toolsets` is not wholly inside it, so a tool with
    no prompt section could not be the declared requirement of **any** indexed
    skill. Measured on `0bd089d`: 74 names in the register, 61 sections, 13
    names here. The gate now reads the callable register
    (`agent_loop._skill_active_toolsets`), so this list is a fact about prose
    and no longer about which skills reach anyone.
    """
    from src.agent_loop import TOOL_SECTIONS

    return sorted(set(builtin_tool_names()) - set(TOOL_SECTIONS.keys()))


def skill_toolset_blocker(requires: Sequence[str]) -> List[str]:
    """Which of a skill's declared toolsets would exclude it from the index of
    a turn that withholds nothing — asked of the product's own gate
    (`_skill_active_toolsets`, `B1381`), so the answer cannot drift from it."""
    from src.agent_loop import _skill_active_toolsets

    active = set(_skill_active_toolsets(set()))
    return sorted(name for name in (requires or []) if name not in active)


def skills_in_store(data_dir: str, owner: Optional[str]) -> List[str]:
    """Every skill the store holds for this person, before any gate.

    The counterpart to `skill_names`, which is the **indexed** list the prompt
    gets. A skill in the store and not in the index is either switched off by
    its package (`P8-51`) or excluded by `requires_toolsets`; the difference
    between these two lists is how many skills nobody can reach, and reporting
    only the index would hide it.
    """
    try:
        from services.memory.skills import SkillsManager
    except Exception:
        return []
    try:
        sm = SkillsManager(data_dir)
        # `B1419`. The install's published shipped skills are offered to every
        # person too, beside their own store (`load_active` adds them). The
        # vendored drafts are a catalogue nobody is offered, so not counted.
        # `B1737`. The core set is catalogued like the rest now.
        rows = sm.load(owner=owner) + [s for s in sm.load_all()
                                       if s.get("bundled") and s.get("status") == "published"]
        return sorted({str(s.get("name")) for s in rows if s.get("name")})
    except Exception:
        return []


@dataclass
class Inventory:
    builtins: List[str]
    mcp: List[str]
    skills: List[str]
    #: Every skill in the store, indexed or not. `skills` is what reaches the
    #: prompt; the gap between the two is reported rather than hidden.
    skills_stored: List[str] = field(default_factory=list)

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
        skills_stored=skills_in_store(data_dir, owner) if data_dir else [],
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
    if tool == "computer":
        # `computer` has a per-turn gate of its own, in its own module, with
        # its own sentence: `computer_tools.unavailable_reason`, which
        # `stream_agent_loop` adds to `disabled_tools`. Asked here so a tool
        # withheld because there is no workstation reads as `held` and not as
        # a gap. Measured while building this harness: without it, `computer`
        # was the one name missing in all 72 cells, and it was missing because
        # the install has no workstation, which is correct.
        try:
            from src.agent_tools.computer_tools import unavailable_reason

            why = unavailable_reason(None)
        except Exception as exc:                 # noqa: BLE001
            why = f"the workstation gate could not be read: {exc}"
        if why:
            return Gate("workstation gate", str(why))
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
                for table in (WINDOW_MODELS, FINETUNE_MODELS)
                for window, name in table.items()
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
"""A real stdio MCP server for the tool-suite probe. Two read-only tools.

`B621`: mcp 2.x renamed `FastMCP` to `MCPServer`; `mcp.server.fastmcp` now
raises on import, pointing at the migration guide."""
import sys
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("suite-probe")


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
        # A non-empty `env` is deliberate: `_connect_stdio` passes
        # `{**os.environ, **env}` when there is one and `None` — the SDK's
        # five-variable `get_default_environment()` — when there is not
        # (`P8-42`). A child interpreter starting from five variables under
        # CPU contention is how this handshake was seen to die mid-initialize.
        env = {"PANTHEON_TOOL_SUITE_PROBE": "1"}
        last = ""
        for attempt in range(4):
            try:
                if await mgr.connect_server("probe", "suite-probe", "stdio",
                                            command=sys.executable,
                                            args=[script_path], env=env):
                    break
                last = str(mgr.get_server_status("probe"))
            except asyncio.CancelledError:
                # anyio cancels `stdio_client`'s scope when the child's
                # transport goes, and `connect_server` only catches
                # `Exception`, so the relayed cancellation arrives here.
                # Measured on this machine (2 CPUs shared by six agents): the
                # handshake dies mid-`initialize` on roughly one start in
                # three, and succeeds on the next. Re-raised on the last
                # attempt rather than swallowed — a run that cannot start its
                # own MCP server must say so, not report an empty MCP column.
                last = "the handshake was cancelled mid-initialize"
                if attempt == 3:
                    raise
            except Exception as exc:          # noqa: BLE001 — reported below
                last = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(0.4 * (attempt + 1))
        else:
            raise RuntimeError(
                "the probe's own MCP server would not start, so this run can "
                f"say nothing about MCP: {last}")
    else:
        # A command that exits at once: registered, never answers. This is the
        # state a person's install is in when the command is wrong or the
        # dependency is missing, and `fx6-tools`' `B1307` is about what the
        # model is told then.
        #
        # `except BaseException` is not laziness. Measured here on `0bd089d`,
        # roughly half of these registrations end with
        # `asyncio.CancelledError: Cancelled via cancel scope …` escaping
        # `connect_server` — anyio cancels `stdio_client`'s scope when the
        # child exits during `initialize()`, and `connect_server` catches
        # `Exception`, which a `CancelledError` is not. The other half come
        # back `False` with `status: error, error: "Connection closed"`. Both
        # are the same install state, so the probe records it the same way;
        # that the product's own boot path does **not** is filed as a defect
        # rather than smoothed over here.
        try:
            await mgr.connect_server("probe", "suite-probe", "stdio",
                                     command="/bin/false", args=[],
                                     env={"PANTHEON_TOOL_SUITE_PROBE": "1"})
        except BaseException:                 # noqa: BLE001 — see above
            mgr._connections["probe"] = {
                "status": "error", "name": "suite-probe",
                "error": "Connection closed",
            }
            mgr._tools["probe"] = []
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
    #: The `AuthManager` holding this world's two accounts, registered as the
    #: process's shared one for the length of the probe.
    auth: Any = None

    def owner(self, cell: Cell) -> str:
        return ADMIN_USER if cell.admin else PLAIN_USER

    def manager(self, cell: Cell):
        return self.managers.get(cell.mcp)


def _seed_accounts(data_dir: str):
    """A real admin and a real non-admin, through the tree's own `signed_in`.

    `Law 14`: `tests/helpers/signed_in.py` is already the one way a test in
    this tree is a person (`D-2026-10-07-02` §2), and it is the only way that
    makes *every* policy check answer about the same people —
    `owner_is_admin` in the loop and `_owner_is_admin` in the
    dispatcher both ask `shared_auth_manager()`.

    Without the registration the install is in its pre-setup window, where
    `owner_is_admin` answers False for everybody and the
    non-admin policy holds two thirds of the register. Measured while building
    this harness: an `auth.json` written beside the probe's data directory and
    *not* registered gave an admin the admin tool list from the loop and
    `Public tool policy blocked owner='probe-admin'` from the dispatcher —
    offered and refused in the same run, which is precisely the defect shape
    this file exists to detect, arriving from the harness instead of the
    product.
    """
    from tests.helpers.signed_in import people

    return people(data_dir, admin=ADMIN_USER, members=(PLAIN_USER,))


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


@asynccontextmanager
async def probe_world(scratch: str, *, mcp_states: Sequence[str] = MCP_STATES):
    """Build the world, hand it over, tear every process down by its own handle.

    **Async, and one event loop for the whole probe.** An `McpManager` stdio
    session is owned by a task on the loop that opened it (`_open_owned`,
    `B880`); opening it on a throwaway loop and then driving the agent loop on
    a fresh `asyncio.run` cancels the owner mid-handshake. A booted server has
    one loop for its life, so the harness has one too.
    """
    import core.auth
    from src import constants

    data_dir = os.path.join(scratch, "data")
    os.makedirs(data_dir, exist_ok=True)
    manager = _seed_accounts(data_dir)
    # `src/constants.py` resolves `DATA_DIR` at import, so a process that was
    # started with `PANTHEON_DATA_DIR` already set (which is what
    # `scripts/tool-suite-matrix.py` does, and what an install does) needs
    # nothing here. A test session is not started that way, so the two values
    # the product reads at call time are pointed at this world and put back
    # afterwards: the data directory, and the shared auth manager. Anything
    # that binds a path at import time is left alone rather than reached into.
    saved_data_dir = constants.DATA_DIR
    saved_auth = getattr(core.auth, "_SHARED_AUTH_MANAGER", None)
    constants.DATA_DIR = data_dir
    core.auth.register_shared_auth_manager(manager)
    script = write_mcp_server(os.path.join(scratch, "mcp"))
    _seed_skills(data_dir)
    endpoint = ProbeEndpoint()
    world = ProbeWorld(data_dir=data_dir, endpoint=endpoint, mcp_script=script,
                       auth=manager)
    try:
        for state in mcp_states:
            world.managers[state] = await build_mcp_manager(state, script)
        yield world
    finally:
        for mgr in world.managers.values():
            if mgr is not None:
                try:
                    await mgr.disconnect_all()
                except Exception:
                    pass
        endpoint.stop()
        constants.DATA_DIR = saved_data_dir
        core.auth.register_shared_auth_manager(saved_auth)


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

# `{1,60}` rather than `{2,60}` (fx10-channel, `Law 3` against the instrument):
# the old minimum was three characters, so **`ls` could never be found** — it is
# the register's only two-character name, and this extractor would have reported
# it `missing` on a prompt that named it outright. Both patterns are filtered
# against `known_tool_names()` below, so widening them cannot start counting an
# English word as a tool.
_BACKTICKED = re.compile(r"`([a-z][a-z0-9_]{1,60})`")
_FENCE_TAG = re.compile(r"```([a-z][a-z0-9_]{1,60})")


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


async def drive_turn(world: ProbeWorld, cell: Cell, text: str, *,
               script: Optional[Sequence[Any]] = None,
               dispatch: str = "boundary",
               wire: bool = False,
               max_rounds: Optional[int] = None,
               url: Optional[str] = None,
               model: Optional[str] = None,
               plan_mode: bool = False,
               disabled_tools: Optional[Set[str]] = None) -> TurnRecord:
    """Run one turn of the product's own loop in this cell. Nothing is stubbed
    except the model, and `dispatch="real"` removes even the dispatcher stub.

    `script` is what the model says, in order: a string is text, anything else
    is fed to the loop's own stream reader as a `data:` frame (so the five
    reply shapes are driven through the code that reads them, not around it).

    `model` overrides `cell.model` (`fx11-order`), because the three
    `pantheon-qwen3` finetune modes are reached by the model's **name** and by
    nothing else; `FINETUNE_MODELS` carries the names the probe endpoint
    declares a window for. `plan_mode` is `stream_agent_loop`'s own flag, and
    on a finetune route it is the one state that stands the fixed prompt down
    while the finetune clamps still run — the turn where the partial-suite
    notice actually reaches the model.

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

    from src.tool_utils import get_mcp_manager, set_mcp_manager

    saved_stream = al.stream_llm_with_fallback
    saved_exec = al.execute_tool_block
    saved_mcp = get_mcp_manager()
    if not wire:
        al.stream_llm_with_fallback = scripted
    al.execute_tool_block = recording_real if dispatch == "real" else boundary
    # `set_mcp_manager` is `app.py`'s own registration door, and both readers —
    # `agent_loop` for the schemas and `tool_execution` for the call — go
    # through `tool_utils._mcp_manager`, so registering it here is what a
    # booted server does rather than a second accessor this harness invented.
    set_mcp_manager(world.manager(cell))

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
            url or world.endpoint.url,
            model or cell.model,
            turn,
            max_rounds=max_rounds or (len(steps) + 1),
            owner=world.owner(cell),
            disabled_tools=set(disabled_tools or ()),
            tool_policy=ToolPolicy(),
            context_length=WINDOW_TOKENS[cell.window],
            prompt_type="agent" if cell.mode == "agent" else None,
            plan_mode=plan_mode,
        ):
            out.append(chunk)
        return out

    started = time.time()
    try:
        chunks = await collect()
    finally:
        al.stream_llm_with_fallback = saved_stream
        al.execute_tool_block = saved_exec
        set_mcp_manager(saved_mcp)
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

#: How much of a tool's own prose the probe turn carries. Long enough to hold
#: every keyword hint the tool has, short enough to still be a thing a person
#: could type.
NAMING_TURN_CHARS = 700


def naming_turn(tool: str, *, mcp_mgr=None) -> str:
    """The most favourable turn this tool can have, built from the tool itself.

    The question is not whether retrieval ranks a tool for a vague request; it
    is whether the tool can reach the model **at all** in this configuration.
    So the turn says the name, and then quotes the tool's own two descriptions
    — `BUILTIN_TOOL_DESCRIPTIONS` (the text agent-mode retrieval embeds) and
    the schema's own `description` (what the model is shown) — because those
    hold every keyword any selector could key on. Measured on `0bd089d`: using
    only the first sentence put `bulk_email`, `computer`, `list_cached_models`
    and `trigger_research` in the missing column when the full text reaches
    them, so a short query over-reports. A tool still missing on **this** turn
    is missing because nothing in the product can select it, which is a finding
    and not a wording accident.
    """
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

    parts = []
    indexed = (BUILTIN_TOOL_DESCRIPTIONS.get(tool) or "").strip()
    if indexed:
        parts.append(indexed)
    for entry in FUNCTION_TOOL_SCHEMAS:
        fn = entry.get("function") or {}
        if fn.get("name") == tool and fn.get("description"):
            parts.append(str(fn["description"]).strip())
            break
    if tool.startswith("mcp__") and mcp_mgr is not None:
        for schema in mcp_mgr.get_all_openai_schemas() or []:
            fn = schema.get("function") or {}
            if fn.get("name") == tool and fn.get("description"):
                parts.append(str(fn["description"]).strip())
                break
    prose = " ".join(parts)[:NAMING_TURN_CHARS] or tool.replace("_", " ")
    return f"Use the `{tool}` tool now. {prose} Call `{tool}` to do it."


def bare_naming_turn(tool: str) -> str:
    """The shortest favourable turn: the person names the tool and nothing else.

    The brief's own words for what must never happen: *"it never silently drops
    a tool the request named."* This is that turn.
    """
    return f"Use the `{tool}` tool now. Call `{tool}` to do it."


#: The verdicts, as an enum rather than a boolean (`Law 10`).
REACH_VERDICTS = ("reached", "prompt_only", "held", "missing")


@dataclass
class ReachRow:
    tool: str
    kind: str
    verdict: str                  # reached | prompt_only | held | missing
    channels: List[str]           # the request shapes that carried it
    turn: str = ""                # which favourable turn got it there
    gate: Optional[str] = None
    sentence: Optional[str] = None


async def reach_report(world: ProbeWorld, cell: Cell, inventory: Inventory, *,
                 names: Optional[Sequence[str]] = None) -> List[ReachRow]:
    """For every tool, the strongest verdict any favourable turn earns it.

    Two turns per tool, because one is not a fair question. `named` is the bare
    name — the request naming the tool, which is the case the brief says must
    never be silently dropped. `described` adds the tool's own prose, which is
    what any keyword selector could possibly key on. Measured on `0bd089d`,
    neither dominates: the short turn misses `bulk_email` and `trigger_research`
    (no keyword hint fires on a bare name), the long one misses the whole email
    family (its prose trips `_looks_like_local_computer_request`, and the
    Terminus clamp **replaces** the turn's tool set). A tool missing on both is
    missing because nothing in the product selects it.

    `prompt_only` is its own verdict and not a pass: the prompt named the tool
    on a route whose request carries a `tools` array that did not. That is the
    `Law 13` split the model complains about in the owner's export — it looks
    for a tool the prompt promised and the request withheld.
    """
    from src.settings import load_features

    try:
        features = load_features()
    except Exception:
        features = {}
    rows: List[ReachRow] = []
    for tool in (names if names is not None else inventory.tools):
        gate = gate_holding(tool, admin=cell.admin, features=features)
        best: Tuple[int, str, List[str]] = (-1, "", [])
        for label, text in (("named", bare_naming_turn(tool)),
                            ("described", naming_turn(tool, mcp_mgr=world.manager(cell)))):
            record = await drive_turn(world, cell, text)
            shapes = record.shapes(cell.model)
            carried = [s for s in REQUEST_SHAPES if tool in set(shapes[s])]
            native = [s for s in carried if s != "fenced"]
            has_array = bool(record.first.get("tools"))
            rank = 2 if native else (1 if (carried and has_array) else
                                     (2 if carried else 0))
            if rank > best[0]:
                best = (rank, label, carried)
        rank, label, carried = best
        if rank == 2:
            verdict = "reached"
        elif rank == 1:
            verdict = "prompt_only"
        elif gate is not None:
            verdict = "held"
        else:
            verdict = "missing"
        rows.append(ReachRow(tool=tool, kind=inventory.kind(tool), verdict=verdict,
                             channels=carried, turn=label,
                             gate=gate.name if gate else None,
                             sentence=gate.sentence if gate else None))
    return rows


async def skill_reach(world: ProbeWorld, cell: Cell, inventory: Inventory) -> List[ReachRow]:
    """A skill reaches the model when the catalogue the loop injects names it.

    Driven through the loop, because `suppress_skills`, the low-signal
    predicate and the toolset gate are all decided there and a direct call to
    `render_skill_index_block` would answer a question nobody asked.
    """
    rows: List[ReachRow] = []
    if not inventory.skills:
        return rows
    record = await drive_turn(
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

#: Arguments the probe would rather name itself than derive, because the
#: derived placeholder would do something. Everything else comes from the
#: tool's own schema (`minimal_args`).
CALL_ARGS: Dict[str, dict] = {
    "mcp__probe__probe_echo": {"text": "probe"},
    "mcp__probe__probe_inventory": {"kind": "all"},
}

#: A value per JSON type that a schema-to-grammar converter and a handler will
#: both accept. Deliberately inert strings — `probe` is not a path, a URL or a
#: command.
_PLACEHOLDERS = {
    "string": "probe", "integer": 1, "number": 1, "boolean": False,
    "array": [], "object": {},
}


def minimal_args(tool: str, *, mcp_mgr=None) -> dict:
    """The smallest argument object this tool's **own schema** calls complete.

    `src/tool_schemas.py` refuses a native call that omits a required argument
    (`_REQUIRED_NATIVE_TOOL_ARGS`, and `function_call_to_tool_block` returns
    `None`), and a handler refuses one its action needs. Either is a correct
    refusal, and probing with `{}` would measure the probe's own omission
    rather than Pantheon's routing. So the arguments are read from the register
    the model is shown: every `required` property gets a placeholder of its
    declared type, an `enum` gets its first member, and nothing else is sent.
    """
    if tool in CALL_ARGS:
        return dict(CALL_ARGS[tool])
    params: dict = {}
    if tool.startswith("mcp__"):
        if mcp_mgr is not None:
            for schema in mcp_mgr.get_all_openai_schemas() or []:
                fn = schema.get("function") or {}
                if fn.get("name") == tool:
                    params = fn.get("parameters") or {}
                    break
    else:
        from src.tool_schemas import FUNCTION_TOOL_SCHEMAS

        for entry in FUNCTION_TOOL_SCHEMAS:
            fn = entry.get("function") or {}
            if fn.get("name") == tool:
                params = fn.get("parameters") or {}
                break
    props = (params or {}).get("properties") or {}
    required = list((params or {}).get("required") or [])
    try:
        from src.tool_schemas import _REQUIRED_NATIVE_TOOL_ARGS

        for group in [_REQUIRED_NATIVE_TOOL_ARGS.get(tool) or ()]:
            if group and not any(name in required for name in group):
                required.append(group[0])
    except Exception:
        pass
    args: dict = {}
    for name in required:
        spec = props.get(name) or {}
        enum = spec.get("enum")
        if isinstance(enum, list) and enum:
            args[name] = enum[0]
            continue
        declared = spec.get("type")
        if isinstance(declared, list):
            declared = next((d for d in declared if d != "null"), "string")
        args[name] = _PLACEHOLDERS.get(declared, "probe")
    return args


#: `answered` the dispatcher ran it and a result came back; `refused` a
#: readable sentence came back instead; `held` the approval gate or a privilege
#: gate stopped it, with its sentence (a **pass** — `FORBIDDEN.md` Part 2);
#: `nudged` the loop declined to dispatch on purpose and told the model why;
#: `dropped` nothing parsed, nothing ran and nobody was told.
CALL_VERDICTS = ("answered", "refused", "held", "nudged", "dropped", "routed")


@dataclass
class CallRow:
    tool: str
    kind: str
    shape: str
    verdict: str          # one of CALL_VERDICTS
    detail: str = ""


#: The loop's own words when it declines to dispatch a first-act `ask_user`
#: and tells the model to look first instead (`_MAX_ASK_FIRST_NUDGES`). Matched
#: on the sentence the loop appends to `messages`, so the probe reads the
#: product's decision rather than guessing at it from an absence.
ASK_FIRST_NUDGE = "You asked the user a question as the first thing this turn"


def _call_verdict(record: TurnRecord, tool: str,
                  emitted: str = "") -> Tuple[str, str]:
    """Read the loop's own events for what became of the call.

    `emitted` is the content the scripted model wrote. It is subtracted from
    the reply text before that text counts as a refusal: when a fenced or
    bare-JSON call is **not** parsed, the loop has nothing to execute and
    streams the model's own words straight through, so the person reads the
    unparsed call itself. Measured while building this harness: without this,
    making `_MCP_TOOL_BLOCK_RE` unmatchable — fx6's `B1306` put back —
    reddened nothing, because the dropped fence was echoed to the person and
    read as "the person was told something".
    """
    for request in record.requests[1:]:
        if ASK_FIRST_NUDGE in (request.get("prompt") or ""):
            # Not dropped: deliberately not dispatched, with an instruction
            # back to the model. `ask_user` as the first act of a turn, before
            # anything has been looked at, is held on purpose.
            return "nudged", ASK_FIRST_NUDGE
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
    # Nothing ran. A sentence the person reads is still a refusal, and the
    # product has refusals that arrive as ordinary reply text rather than as a
    # tool event — `_explicitly_references_missing_workspace` ends the turn
    # with *"No active workspace is set. Use `/workspace pick` …"* before the
    # model is called at all, which is a correct answer to a request for a
    # file tool on an install with no workspace. Reading only `tool_output`
    # would file that as a silent drop, which is the opposite of what happened.
    said = "".join(str(ev.get("delta") or "") for ev in record.events).strip()
    if emitted:
        for fragment in (emitted, emitted.strip()):
            said = said.replace(fragment, "")
        said = said.strip()
    if said:
        return "refused", said[:160]
    return "dropped", "no ToolBlock reached the dispatcher and the person was told nothing"


async def call_report(world: ProbeWorld, cell: Cell, inventory: Inventory, *,
                shapes: Sequence[str] = REPLY_SHAPES,
                names: Optional[Sequence[str]] = None,
                real: bool = False) -> List[CallRow]:
    """For every tool and every reply shape: was the call parsed, routed, answered?"""
    rows: List[CallRow] = []
    for tool in (names if names is not None else inventory.tools):
        args = minimal_args(tool, mcp_mgr=world.manager(cell))
        drive_real = real and tool not in DESTRUCTIVE
        for shape in shapes:
            step = reply_shapes(tool, args)[shape]
            record = await drive_turn(world, cell,
                                naming_turn(tool, mcp_mgr=world.manager(cell)),
                                script=[step, "Done."],
                                dispatch="real" if drive_real else "boundary",
                                max_rounds=3)
            verdict, detail = _call_verdict(
                record, tool, emitted=step if isinstance(step, str) else "")
            rows.append(CallRow(tool=tool, kind=inventory.kind(tool), shape=shape,
                                verdict=verdict, detail=detail))
    return rows


#: An Ollama-shaped URL. `tool_schema_offer` answers `fenced` for it by URL and
#: not by model name (`B39`'s measured policy, which `fx6-tools` left exactly as
#: it found it), and port 11434 is the discriminator
#: (`_is_ollama_openai_compat_url`). Nothing has to be listening: the model is
#: scripted, so no request leaves the process.
FENCED_ROUTE_URL = "http://127.0.0.1:11434/v1"


@dataclass
class FencedReport:
    """What a route with no `tools` array at all can reach."""

    offered_array: int
    named_in_prompt: List[str]
    missing: List[str]
    held: List[str]

    @property
    def reached(self) -> int:
        return len(self.named_in_prompt)


async def fenced_route_reach(world: ProbeWorld, cell: Cell,
                             inventory: Inventory) -> FencedReport:
    """On a fenced route the prompt is the only channel, so measure the prompt.

    The matrix's cells all run an OpenAI-compatible route, where a tool can
    reach the model through the `tools` array. An Ollama endpoint that has not
    declared `supports_tools` carries **no array at all** (`B39`), so every
    tool in the suite either appears in the prompt or cannot be called on that
    install. One turn per tool, the bare name — the turn the brief says must
    never be silently dropped.
    """
    from src.settings import load_features

    try:
        features = load_features()
    except Exception:
        features = {}
    named: List[str] = []
    missing: List[str] = []
    held: List[str] = []
    array_sizes: List[int] = []
    for tool in inventory.tools:
        record = await drive_turn(world, cell, bare_naming_turn(tool),
                                  url=FENCED_ROUTE_URL)
        array_sizes.append(len(record.first.get("tools") or []))
        if tool in prompt_tool_names(record.first.get("prompt", "")):
            named.append(tool)
        elif gate_holding(tool, admin=cell.admin, features=features) is not None:
            held.append(tool)
        else:
            missing.append(tool)
    return FencedReport(offered_array=max(array_sizes or [0]),
                        named_in_prompt=named, missing=missing, held=held)


@dataclass
class BootReport:
    """What `connect_all_enabled` leaves behind when one server is dead."""

    registered: int
    raised: str
    connected: List[str]
    tools: List[str]
    statuses: Dict[str, Any]

    @property
    def verdict(self) -> str:
        if self.raised:
            return "aborted"
        return "completed"


async def boot_connect_report(scratch: str) -> BootReport:
    """Register three stdio servers — two that answer, one that exits at once —
    and run the product's own boot connect over them.

    This is a separate question from the matrix's `mcp=down` cell, which hands
    the loop a manager already in that state. The question here is what boot
    does: `connect_all_enabled` gathers one task per enabled server with no
    `return_exceptions`, and `_connect_with_timeout` catches
    `asyncio.TimeoutError` only — so whatever `connect_server` lets through
    reaches the gather. Reported as a number rather than asserted, because
    `src/mcp_manager.py` is not this lane's file: when it is fixed, `verdict`
    changes from `aborted` to `completed` and `tools` stops being empty.
    """
    import json as _json

    from core.database import McpServer, SessionLocal
    from src.mcp_manager import McpManager

    script = write_mcp_server(os.path.join(scratch, "boot-mcp"))
    rows = [("probe-good-1", sys.executable, [script]),
            ("probe-dead-1", "/bin/false", []),
            ("probe-good-2", sys.executable, [script])]
    db = SessionLocal()
    try:
        for server_id, command, args in rows:
            if db.query(McpServer).filter(McpServer.id == server_id).first():
                continue
            db.add(McpServer(id=server_id, name=server_id, transport="stdio",
                             command=command, args=_json.dumps(args),
                             env=_json.dumps({"PANTHEON_TOOL_SUITE_PROBE": "1"}),
                             is_enabled=True))
        db.commit()
    finally:
        db.close()
    mgr = McpManager()
    raised = ""
    try:
        await mgr.connect_all_enabled()
    except BaseException as exc:              # noqa: BLE001 — the measurement
        raised = f"{type(exc).__name__}: {exc}"
    statuses = {}
    try:
        statuses = mgr.get_all_statuses() or {}
    except Exception:
        pass
    report = BootReport(
        registered=len(rows), raised=raised,
        connected=sorted(sid for sid, st in statuses.items()
                         if (st or {}).get("status") == "connected"),
        tools=mcp_tool_names(mgr), statuses=statuses,
    )
    try:
        await mgr.disconnect_all()
    except BaseException:                     # noqa: BLE001
        pass
    db = SessionLocal()
    try:
        for server_id, _c, _a in rows:
            row = db.query(McpServer).filter(McpServer.id == server_id).first()
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()
    return report


async def unknown_name_control(world: ProbeWorld, cell: Cell) -> CallRow:
    """The control that must never be stood down: a name nobody registered is
    refused, not silently dropped and not routed."""
    bogus = "definitely_not_a_pantheon_tool"
    record = await drive_turn(world, cell, "Do the thing.",
                        script=[reply_shapes(bogus, {})["native"], "Done."],
                        max_rounds=3)
    routed = any(name == bogus for name, _ in record.dispatched)
    if routed:
        return CallRow(bogus, "control", "native", "routed",
                       "an unknown name was dispatched")
    # Not routed is the control. What the *person* was told is the second
    # question, and it is asked of every surface a person reads: the tool
    # events and the reply text.
    said = " ".join(
        str(ev.get("output") or ev.get("reason") or ev.get("message") or ev.get("delta") or "")
        for ev in record.events
        if ev.get("type") in ("tool_output", "tool_blocked") or "delta" in ev).strip()
    return CallRow(bogus, "control", "native",
                   "refused" if said else "dropped", said[:160])


# ── the matrix ─────────────────────────────────────────────────────────────

# ── question 3 (fx11-reach): a selectable name is a callable name ───────────
#
# `B1354` (agent:`fx11-reach`). `fx9-proof`'s inventory is derived from
# `FUNCTION_TOOL_SCHEMAS` (`builtin_tool_names`), and `fx10-channel`'s fenced
# count is derived from that inventory, so **neither can see a name that has no
# schema and no prose** — which is exactly the shape that defect takes. The
# denominator below is the other register: what the turn's planner may *offer*.
# Measured on `747cda6`, an admin's ordinary turn handed `_assemble_prompt` 84
# names, of which 4 were in no channel at all.

#: `both` the request's array and the fenced prompt carry it; `native_only` the
#: array alone (the fenced prompt cannot name it); `fenced_only` the prompt
#: alone (no function schema, so a native-tools turn has nothing to call);
#: `neither` selectable and uncallable. An enum, not a boolean (`Law 10`).
CHANNEL_VERDICTS = ("both", "native_only", "fenced_only", "neither")


@dataclass
class ChannelRow:
    """Which of the product's two channels can carry a call for one name."""

    name: str
    native: bool
    fenced: bool
    routed: bool

    @property
    def verdict(self) -> str:
        if self.native and self.fenced:
            return "both"
        if self.native:
            return "native_only"
        if self.fenced:
            return "fenced_only"
        return "neither"


@dataclass
class ChannelReport:
    rows: List[ChannelRow]

    def of(self, verdict: str) -> List[str]:
        return sorted(r.name for r in self.rows if r.verdict == verdict)

    @property
    def neither(self) -> List[str]:
        return self.of("neither")

    @property
    def fenced_only(self) -> List[str]:
        return self.of("fenced_only")

    @property
    def unroutable(self) -> List[str]:
        """Names the prompt or the array advertises that nothing will route."""
        return sorted(r.name for r in self.rows
                      if (r.native or r.fenced) and not r.routed)


def offerable_names(mcp_mgr=None, *, disabled: Iterable[str] = ()) -> List[str]:
    """Every name this turn's planner may put in front of the model.

    `src.agent_loop.plan_turn_tool_suite`'s own candidate line — the built-in
    register's selectable half plus every enabled MCP tool, minus what the
    privileges already removed. Asked of the product rather than restated here
    (`Law 7`): a name added to either register tomorrow is in this list with
    nobody editing this file.
    """
    import src.agent_loop as al
    from src.tool_policy import selectable_tool_names

    drop = {str(name) for name in (disabled or ())}
    mcp_names, _costs, _by_server = al._suite_mcp_tools(mcp_mgr, {})
    return sorted((set(selectable_tool_names()) | set(mcp_names)) - drop)


def channel_report(names: Sequence[str], *, mcp_mgr=None) -> ChannelReport:
    """For each name, which channel carries it — by building the real prompt
    and by asking the real converters, never by comparing registers.

    `Law 20`: the fenced answer is `_assemble_prompt`'s own output read back
    through `prompt_tool_names` **and** a fence the real `parse_tool_blocks`
    routes; the native answer is a `FUNCTION_TOOL_SCHEMAS` entry **and** a call
    the real `function_call_to_tool_block` converts. A register comparison
    would pass while either converter refused the name.
    """
    import src.agent_loop as al
    from src.tool_parsing import parse_tool_blocks
    from src.tool_schemas import function_call_to_tool_block

    offered = set(names)
    prompt_named = prompt_tool_names(al._assemble_prompt(offered, set(), compact=False))
    schema_backed = set(al._schema_backed_tool_names())
    mcp_schema_names = {
        (schema.get("function") or {}).get("name")
        for schema in ((mcp_mgr.get_all_openai_schemas() or []) if mcp_mgr else [])
    }
    rows: List[ChannelRow] = []
    for name in sorted(offered):
        args = minimal_args(name, mcp_mgr=mcp_mgr)
        converted = function_call_to_tool_block(name, json.dumps(args))
        fenced_blocks = parse_tool_blocks(reply_shapes(name, args)["fenced"])
        rows.append(ChannelRow(
            name=name,
            native=(name in schema_backed or name in mcp_schema_names)
                   and converted is not None,
            fenced=name in prompt_named and bool(fenced_blocks),
            routed=converted is not None or bool(fenced_blocks),
        ))
    return ChannelReport(rows=rows)


@dataclass
class OfferGap:
    """One real turn's offer, and what of it reached neither channel."""

    offered: List[str]
    disabled: List[str]
    array: List[str]
    prompt_named: List[str]

    @property
    def effective(self) -> List[str]:
        """What the prompt and the array were actually built from: the offer
        minus the names the route disabled after the plan was made."""
        return sorted(set(self.offered) - set(self.disabled))

    @property
    def neither(self) -> List[str]:
        return sorted(set(self.effective) - set(self.array) - set(self.prompt_named))


async def offer_channel_gap(world: ProbeWorld, cell: Cell,
                            text: str = "") -> OfferGap:
    """Drive one ordinary turn and read the offer out of `_assemble_prompt`.

    The set the loop hands the prompt builder is the only place the turn's
    whole offer exists — the array is filtered by what has a schema and the
    prompt by what has prose, so reading either one back cannot tell an
    unreachable name from a name nobody selected. Spied the way the brief's own
    measurement spies, and put back in a `finally` whatever happens.
    """
    import src.agent_loop as al

    seen: List[Tuple[Set[str], Set[str]]] = []
    real = al._assemble_prompt

    def spy(tool_names, disabled_tools=None, compact=False, suite_notice=""):
        seen.append((set(tool_names), set(disabled_tools or ())))
        return real(tool_names, disabled_tools, compact, suite_notice)

    al._assemble_prompt = spy
    try:
        record = await drive_turn(world, cell, text or ORDINARY_TURN)
    finally:
        al._assemble_prompt = real
    offered: Set[str] = set()
    disabled: Set[str] = set()
    for names, dis in seen:
        offered |= names
        disabled |= dis
    return OfferGap(
        offered=sorted(offered),
        disabled=sorted(disabled),
        array=sorted(record.offered()),
        prompt_named=sorted(prompt_tool_names(record.first.get("prompt", ""))),
    )


@dataclass
class SuiteOrder:
    """One turn's suite plan, the cap it was planned against, and the records.

    `fx11-order`. `OfferGap` above answers *what reached the model*; this
    answers *what the turn said about itself*, which is a different question
    and the one `Law 10` is about. Four readings of one turn:

    * `plan_*` — what `plan_turn_tool_suite` returned, and the size of the
      `disabled_tools` it was handed **at the moment it ran**.
    * `cap_at_prompt` — the same object when the prompt was built, after every
      clamp. A number larger than `cap_at_plan` means a writer ran across the
      planner.
    * `notice` / `notice_reached_model` — the partial-suite sentence
      `_suite_notice_for` computed, and whether the prompt the model was
      actually sent contains it. The two are different facts on a finetune
      route, which replaces the assembled prompt wholesale.
    * `receipt` — the `suite` payload `src.events.record_run_config` stored.
    """

    plan_candidates: int = 0
    plan_offered: int = 0
    plan_reason: str = ""
    plan_withheld: List[str] = field(default_factory=list)
    plan_partial: bool = False
    cap_at_plan: int = 0
    cap_at_prompt: int = 0
    cap_at_prompt_names: List[str] = field(default_factory=list)
    prompt_tool_names: List[str] = field(default_factory=list)
    notice: str = ""
    notice_reached_model: bool = False
    receipt: Dict[str, Any] = field(default_factory=dict)
    array: List[str] = field(default_factory=list)
    prompt: str = ""

    @property
    def notice_numbers(self):
        """`(offered, total)` as the notice states them, or `None`."""
        m = re.search(r"You have (\d+) of your (\d+) tools", self.notice or "")
        return (int(m.group(1)), int(m.group(2))) if m else None

    @property
    def receipt_numbers(self):
        """`(offered, candidates)` as the receipt stores them, or `None`."""
        if not self.receipt:
            return None
        return (int(self.receipt.get("offered") or 0),
                int(self.receipt.get("candidates") or 0))


async def suite_order(world: ProbeWorld, cell: Cell, text: str = "", *,
                      model: Optional[str] = None,
                      plan_mode: bool = False) -> SuiteOrder:
    """Drive one real turn and read the plan, the cap, the notice and the receipt.

    Spied at the three seams the product itself writes through —
    `plan_turn_tool_suite`, `_assemble_prompt` and
    `src.events.record_run_config` — and every one put back in a `finally`.
    `disabled_tools` is read by `len()` at each seam rather than copied,
    because it is one mutated object and its size is the measurement.
    """
    import src.agent_loop as al
    import src.events as events

    seen: Dict[str, Any] = {}
    real_plan = al.plan_turn_tool_suite
    real_asm = al._assemble_prompt
    real_record = events.record_run_config

    def plan_spy(*a, **k):
        out = real_plan(*a, **k)
        seen["plan"] = out
        seen["cap_at_plan"] = len(set(k.get("disabled_tools") or ()))
        return out

    def asm_spy(tool_names, disabled_tools=None, compact=False, suite_notice=""):
        seen["cap_at_prompt"] = len(set(disabled_tools or ()))
        seen["cap_at_prompt_names"] = sorted(set(disabled_tools or ()))
        seen["prompt_tool_names"] = sorted(set(tool_names))
        if suite_notice:
            seen["notice"] = suite_notice
        return real_asm(tool_names, disabled_tools, compact, suite_notice)

    def record_spy(**k):
        if k.get("suite") is not None:
            seen["receipt"] = json.loads(json.dumps(k["suite"]))
        return real_record(**k)

    al.plan_turn_tool_suite = plan_spy
    al._assemble_prompt = asm_spy
    events.record_run_config = record_spy
    try:
        record = await drive_turn(world, cell, text or ORDINARY_TURN,
                                  model=model, plan_mode=plan_mode)
    finally:
        al.plan_turn_tool_suite = real_plan
        al._assemble_prompt = real_asm
        events.record_run_config = real_record

    plan = seen.get("plan")
    prompt = record.first.get("prompt", "") or ""
    notice = seen.get("notice", "")
    head = notice.split("\n")[0] if notice else ""
    return SuiteOrder(
        plan_candidates=len(plan.candidates) if plan else 0,
        plan_offered=len(plan.offered) if plan else 0,
        plan_reason=getattr(plan, "reason", "") if plan else "",
        plan_withheld=list(getattr(plan, "withheld", ())) if plan else [],
        plan_partial=bool(getattr(plan, "partial", False)) if plan else False,
        cap_at_plan=int(seen.get("cap_at_plan") or 0),
        cap_at_prompt=int(seen.get("cap_at_prompt") or 0),
        cap_at_prompt_names=list(seen.get("cap_at_prompt_names") or []),
        prompt_tool_names=list(seen.get("prompt_tool_names") or []),
        notice=notice,
        notice_reached_model=bool(head and head in prompt),
        receipt=dict(seen.get("receipt") or {}),
        array=sorted(record.offered()),
        prompt=prompt,
    )


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
    def prompt_only(self) -> List[str]:
        return [r.tool for r in self.reach if r.verdict == "prompt_only"]

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


async def run_cell(world: ProbeWorld, cell: Cell, *, repeats: int = 5,
             reach: bool = True, calls: bool = False,
             call_names: Optional[Sequence[str]] = None,
             real_calls: bool = False) -> CellResult:
    """One cell, measured. The product is built once and driven many times."""
    started = time.time()
    inventory = suite_inventory(world.manager(cell), data_dir=world.data_dir,
                               owner=world.owner(cell))
    offered_repeats = []
    for _ in range(repeats):
        record = await drive_turn(world, cell, ORDINARY_TURN)
        offered_repeats.append(sorted(record.offered()))
    turns = {}
    for label, text in SAMPLE_TURNS.items():
        turns[label] = sorted((await drive_turn(world, cell, text)).offered())
    result = CellResult(
        cell=cell, suite=inventory.total, builtins=len(inventory.builtins),
        mcp=len(inventory.mcp), skills=len(inventory.skills),
        repeats=offered_repeats, turns=turns,
    )
    if reach:
        result.reach = await reach_report(world, cell, inventory)
        result.skill_rows = await skill_reach(world, cell, inventory)
    if calls:
        result.calls = await call_report(world, cell, inventory, names=call_names,
                                         real=real_calls)
        result.control = await unknown_name_control(world, cell)
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
            "prompt only | held (gate) | missing | identical over repeats |")
    rule = "|---|---|---|---|---|---|---|---|---|"
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
            f"{spread} | {res.reached} | {len(res.prompt_only)} | {res.held} | {miss} | "
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
