# SPDX-License-Identifier: AGPL-3.0-or-later
"""An MCP tool the operator switched off does not run.

`McpServer.disabled_tools` hid the tool from the prompt and the function
schemas, but the agent loop never refused it at call time: a model that named
`mcp__srv1__wipe` in a text tool call (or from memory of an earlier turn) ran
it. On main this test records one call to the switched-off tool.
"""
import asyncio
import json

import src.agent_loop as agent_loop
import src.agent_tools as agent_tools
from src.mcp_manager import McpManager


class _Mgr(McpManager):
    def __init__(self):
        super().__init__()
        self.calls = []
        self._connections["srv1"] = {"status": "connected", "name": "Files"}
        self._tools["srv1"] = [
            {"name": "wipe", "description": "Delete everything", "input_schema": {}},
            {"name": "lookup", "description": "Look up", "input_schema": {}},
        ]
        self._sessions["srv1"] = object()

    async def call_tool(self, qualified_name, arguments, timeout=None):
        self.calls.append((qualified_name, arguments))
        return {"stdout": "wiped", "stderr": "", "exit_code": 0}


def test_a_switched_off_mcp_tool_is_refused_at_call_time(monkeypatch):
    mgr = _Mgr()
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: mgr, raising=False)
    monkeypatch.setattr(agent_tools, "get_mcp_manager", lambda: mgr, raising=False)
    # The operator switched `wipe` off on server srv1.
    monkeypatch.setattr(agent_loop, "_load_mcp_disabled_map", lambda: {"srv1": {"wipe"}}, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    import src.tool_execution as te
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    rounds = {"n": 0}

    async def fake_stream(*_a, **_k):
        rounds["n"] += 1
        if rounds["n"] == 1:
            txt = "```mcp__srv1__wipe\n{}\n```"
        else:
            txt = "done"
        yield f"data: {json.dumps({'delta': txt})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "clean up with the files tool"}],
            max_rounds=3, session_id="s-disabled", owner="admin")]

    asyncio.run(drain())
    assert mgr.calls == [], f"switched-off MCP tool was executed: {mgr.calls}"
