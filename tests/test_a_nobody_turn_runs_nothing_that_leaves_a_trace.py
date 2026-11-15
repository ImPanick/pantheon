# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nobody mode runs nothing that leaves a trace.

The owner's ruling on Nobody (`B2097`): *"Nobody mode is 'incognito' which
should 'discard' everything in that session."* `B2097` withheld the tools that
write into what Pantheon keeps for the person (the `write_private` effect).
Measured on `dev@ad4aac6`, a Nobody turn was still offered every other tool
that leaves something behind once the chat is gone:

* running code: `bash`, `python`, `host_shell`, `computer`, `shell_with_login`;
* writing the workspace: `write_file`, `edit_file`, `apply_patch`, `git`,
  `download_attachment`;
* acting outside Pantheon under the person's name: `send_email`,
  `reply_to_email`, `delete_email`, `agent_browser` (its profile keeps cookies);
* changing the install: `manage_settings`, `manage_mcp`, `manage_tokens`,
  `serve_model`, `api_call`;
* and every tool of an MCP server the person added, which Pantheon cannot
  vouch for at all.

The reads stay (web search, workspace reads, a read-only MCP tool), and so do
the pictures, which keep nothing (`B2097`).
"""
from __future__ import annotations

import asyncio
import json

from test_nobody_mode_keeps_nothing import _disabled_in_a_turn, _nobody_request
from test_foreground_model_routing import _RouteRequest

#: One or more per effect that leaves something behind.
LEAVES_A_TRACE = (
    # running code
    "bash", "python", "host_shell", "computer", "shell_with_login", "manage_bg_jobs",
    # writing the workspace
    "write_file", "edit_file", "apply_patch", "git", "download_attachment",
    # outside Pantheon, under their name
    "send_email", "reply_to_email", "delete_email", "bulk_email", "agent_browser",
    # (an MCP server's qualified names, `mcp__email__send_email` among them,
    # are the agent loop's to withhold: the second half of this file)
    # the install
    "manage_settings", "manage_mcp", "manage_tokens", "serve_model", "api_call",
)

#: Reads, and what keeps nothing: still offered. (The web tools follow the
#: chat's search switch, which this request leaves off.)
STILL_OFFERED = ("read_file", "grep", "generate_image", "edit_image")


def test_a_nobody_turn_withholds_every_tool_that_leaves_a_trace(monkeypatch):
    from src.tool_policy import LIFTABLE_REASONS

    disabled = _disabled_in_a_turn(monkeypatch, _nobody_request("agent"))
    offered = [name for name in LEAVES_A_TRACE if name not in disabled]
    assert not offered, f"Nobody still offers {offered}"
    for name in LEAVES_A_TRACE:
        assert not (disabled.reasons_for(name) & LIFTABLE_REASONS), (
            f"{name} is withheld for a reason a clamp may lift: {disabled.reasons_for(name)}")
    withheld = [name for name in STILL_OFFERED if name in disabled]
    assert not withheld, f"Nobody withholds reads or pictures it should keep: {withheld}"


def test_an_ordinary_turn_is_still_offered_them(monkeypatch):
    request = _RouteRequest("agent")
    request._form["compare_mode"] = "false"
    disabled = _disabled_in_a_turn(monkeypatch, request)
    assert not [name for name in ("write_file", "send_email", "git") if name in disabled]


# ── an MCP server the person added ───────────────────────────────────────────

def _run_a_turn_naming(monkeypatch, tool, *, nobody, server="notes_cloud"):
    """The real agent loop, one model round that names `tool` in a text tool
    call; returns the calls the MCP server received."""
    import src.agent_loop as agent_loop
    import src.agent_tools as agent_tools
    import src.tool_execution as te
    from src import nobody_mode
    from src.mcp_manager import McpManager

    class _Mgr(McpManager):
        def __init__(self):
            super().__init__()
            self.calls = []
            self._connections[server] = {"status": "connected", "name": server}
            self._tools[server] = [
                {"name": "save_note", "description": "Save a note to the cloud", "input_schema": {}},
                {"name": "get_note", "description": "Read a note", "input_schema": {},
                 "annotations": {"readOnlyHint": True}},
            ]
            self._sessions[server] = object()

        async def call_tool(self, qualified_name, arguments, timeout=None):
            self.calls.append(qualified_name)
            return {"stdout": "ok", "stderr": "", "exit_code": 0}

    mgr = _Mgr()
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: mgr, raising=False)
    monkeypatch.setattr(agent_tools, "get_mcp_manager", lambda: mgr, raising=False)
    monkeypatch.setattr(agent_loop, "_load_mcp_disabled_map", lambda: {}, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    rounds = {"n": 0}

    async def fake_stream(*_a, **_k):
        rounds["n"] += 1
        txt = f"```{tool}\n{{}}\n```" if rounds["n"] == 1 else "done"
        yield f"data: {json.dumps({'delta': txt})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        with nobody_mode.turn_scope(nobody):
            return [c async for c in agent_loop.stream_agent_loop(
                "http://local.test/v1", "small-local-model",
                [{"role": "user", "content": "use my notes server"}],
                max_rounds=3, session_id="s-nobody", owner="admin")]

    asyncio.run(drain())
    return mgr.calls


def test_a_nobody_turn_does_not_run_an_added_servers_write_tool(monkeypatch):
    calls = _run_a_turn_naming(monkeypatch, "mcp__notes_cloud__save_note", nobody=True)
    assert calls == [], f"a Nobody turn ran an added MCP server's write tool: {calls}"


def test_a_nobody_turn_does_not_run_a_built_in_servers_send_by_its_qualified_name(monkeypatch):
    """The bare `send_email` is withheld at the route; its qualified spelling
    on the built-in `email` server is no way round."""
    calls = _run_a_turn_naming(monkeypatch, "mcp__email__save_note", nobody=True, server="email")
    assert calls == [], calls


def test_a_nobody_turn_still_runs_an_added_servers_read_only_tool(monkeypatch):
    calls = _run_a_turn_naming(monkeypatch, "mcp__notes_cloud__get_note", nobody=True)
    assert calls == ["mcp__notes_cloud__get_note"], calls


def test_an_ordinary_turn_still_runs_the_added_servers_write_tool(monkeypatch):
    """The control: the harness reaches the server, so the first test is a
    measurement and not an absence of one."""
    calls = _run_a_turn_naming(monkeypatch, "mcp__notes_cloud__save_note", nobody=False)
    assert calls == ["mcp__notes_cloud__save_note"], calls
