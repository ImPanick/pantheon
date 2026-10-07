# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B969` (found by `P20-04`): `host_shell` had never run through the dispatcher.

Every registry tool is called `TOOL_HANDLERS[tool](content, ctx)`, and
`HostShellTool.execute` took no positional context, so each call answered
*"takes 2 positional arguments but 3 were given"*. The tests beside `P17-11`
drove the network agent and the policy, never the dispatch, so they stayed
green. This drives `execute_tool_block` itself (`Law 20`), with the network
agent's client faked at its boundary.
"""
from __future__ import annotations

import asyncio
import json

import src.tool_execution as te
from src import host_exec_policy, netagent_client
from src.agent_tools import ToolBlock
from tests.helpers.signed_in import ADMIN, signed_in


def test_an_admin_s_host_command_reaches_the_host_agent(monkeypatch, tmp_path):
    # The install's admin, signed in (`D-2026-10-07-02` §2 — this was the
    # single-user owner, nobody, under a patched `_auth_disabled`).
    signed_in(monkeypatch, tmp_path / "auth", members=())
    monkeypatch.setattr(netagent_client, "configured", lambda: True)
    sent = []

    async def exec_on_host(command, **kw):
        sent.append((command, kw))
        return {"stdout": "hi\n", "stderr": "", "exit_code": 0}

    monkeypatch.setattr(netagent_client, "exec_on_host", exec_on_host)
    monkeypatch.setattr(host_exec_policy, "check_from_settings",
                        lambda command: type("D", (), {"allowed": True})())
    desc, result = asyncio.run(te.execute_tool_block(
        ToolBlock("host_shell", json.dumps({"command": "echo hi"})), owner=ADMIN,
        security_context=te.NO_TOOL_SECURITY_CONTEXT))
    assert "positional" not in str(result.get("error", "")), result
    assert sent and sent[0][0] == "echo hi"
    assert result["output"] == "hi\n" and result["exit_code"] == 0 and result["host"] is True
