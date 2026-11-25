# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agent mode in a plain chat works in the person's workstation with no folder picked.

The owner's test on the dev build (2026-11-25), Agent mode in a normal chat,
the Workstation open in the Workspace panel: "Setup the VM in the workspace..
It's under workstation. I need you to open terminal, get everything updated
with apt update and apt upgrade -y ... get Docker installed on this VM." The
turn was answered "No active workspace is set. Use /workspace pick or
/workspace set /absolute/path, then rerun the request." and never reached the
model, twice.

The turn named "the workspace", no folder had been picked, and the agent loop
stops such a turn before the model. On Pantheon's own machine that stands: the
file tools are confined to a picked folder and there is none. But a person
whose tools run in their workstation always has somewhere to work: with no
folder picked, the shell and file tools start in their workstation home
(`get_workspace` answers it, `B968`). So for them the turn runs.
"""
from __future__ import annotations

import asyncio

import pytest

ASK = ("Setup the VM in the workspace.. It's under workstation. I need you to open terminal, "
       "get everything updated with apt update and apt upgrade -y. Once you're done with this, "
       "I need you to get Docker installed on this VM. Proceed. If you have questions, ask.")


@pytest.fixture
def loop(monkeypatch):
    import src.agent_loop as al
    from src.agent_tools import workstation_tools
    monkeypatch.setattr(al, "get_setting", lambda key, default=None: default, raising=False)
    monkeypatch.setattr(al, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(al, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(al, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    # "panick" has a workstation; "admin" works on Pantheon's own machine.
    monkeypatch.setattr(workstation_tools, "_routes_tools", lambda owner: owner == "panick")
    called = []

    async def model(*args, **kwargs):
        called.append(True)
        yield 'data: {"delta": "On it."}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(al, "stream_llm_with_fallback", model, raising=False)
    return al, called


def _run(al, owner):
    async def go():
        gen = al.stream_agent_loop(
            "http://127.0.0.1:1234/v1", "gemma-4-26b-a4b-qat",
            [{"role": "user", "content": ASK}],
            max_rounds=1, relevant_tools=None, owner=owner, workspace=None,
        )
        return "".join([c async for c in gen])
    return asyncio.run(go())


def test_with_a_workstation_the_turn_reaches_the_model(loop):
    al, called = loop
    text = _run(al, "panick")
    assert "No active workspace is set" not in text
    assert called, "the turn was stopped before the model"


def test_on_pantheons_own_machine_a_missing_folder_still_stops_the_turn(loop):
    al, called = loop
    text = _run(al, "admin")
    assert "No active workspace is set" in text
    assert not called


def test_the_check_itself():
    from src.agent_tools import workstation_tools
    import src.agent_loop as al
    real = workstation_tools._routes_tools
    try:
        workstation_tools._routes_tools = lambda owner: owner == "panick"
        assert al._explicitly_references_missing_workspace(ASK, None, "panick") is False
        assert al._explicitly_references_missing_workspace(ASK, None, "admin") is True
        assert al._explicitly_references_missing_workspace(ASK, None) is True
        assert al._explicitly_references_missing_workspace(ASK, "/home/admin/proj", "admin") is False
    finally:
        workstation_tools._routes_tools = real
