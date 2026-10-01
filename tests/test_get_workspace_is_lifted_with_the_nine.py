# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B985` — `get_workspace` is lifted with the nine, and says what holds where.

It is refused to a non-admin because on Pantheon's machine it "discloses the
absolute host path of the workspace" (`tool_security.NON_ADMIN_BLOCKED_REASONS`).
For a person whose tools run in their workstation (`routes_tools`) it answers a
folder in their own workstation home, or the home itself (`B968`'s
`describe_workspace`) — a folder they picked in a picker they may use, and that
their own `ls` would show. So it is lifted with `bash`, `python` and the file
tools, for exactly the people those are lifted for (`workstation_tools.
LIFTED_TOOLS`, the one list the dispatcher allows from and the loop offers
from), and nothing else is. Everyone else is refused as before, with a reason
that now says what would change it.

Its advertised description said *"File tools are confined to it"* whatever
machine the tools ran on; with the workstation on they start there and it is
not a boundary. The three places a model reads it — the native schema, the
fenced prompt section, the tool index — now say what holds on each machine, and
the answer says which one it is.

Driven (`Law 20`): the real dispatcher and the real agent loop, against the real
daemon (`P20-03`'s fixtures), for a granted non-admin, an ungranted one and an
admin, with the workstation on, off and routing off.
"""
from __future__ import annotations

import pytest

import src.agent_tools.workstation_tools as wt
from src.tool_security import blocked_tool_reason
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    WORKSTATION_TOOLS, _call, _home, _on, host_dir, people, settings, ws)


def test_the_lifted_set_is_the_nine_and_get_workspace_and_nothing_else():
    assert wt.LIFTED_TOOLS == WORKSTATION_TOOLS | {"get_workspace"}


def test_a_granted_person_is_answered_about_their_own_workstation_home(ws, settings, people):
    _on(settings, ws)
    home = _home(ws, "ann")
    (home / "proj").mkdir(parents=True)
    _, r = _call("get_workspace", "", "ann")
    assert r == {"output": "No workspace is set. The shell and file tools run in your workstation "
                           f"and start in your workstation home ({home}); relative paths are "
                           "relative to it.", "exit_code": 0}
    _, r = _call("get_workspace", "", "ann", workspace=str(home / "proj"))
    assert r["output"].startswith(f"{home / 'proj'}\n(In your workstation.")
    assert "restricted" not in str(r)


@pytest.mark.parametrize("owner, switch", [
    ("bob", {}),                                   # not granted
    ("ann", {"workstation_route_tools": False}),   # routing off: her tools run here
    ("ann", {"workstation_enabled": False}),       # off
], ids=["not-granted", "routing-off", "off"])
def test_everyone_else_is_refused_as_before_with_a_reason_that_says_what_changes_it(
        ws, settings, people, owner, switch):
    _on(settings, ws, **switch)
    _, r = _call("get_workspace", "", owner)
    assert r["exit_code"] == 1 and "restricted to admin users" in r["error"], r
    assert blocked_tool_reason("get_workspace") in r["error"]
    assert "absolute host path" in r["error"]
    assert "Not refused to a person whose tools run in their workstation" in r["error"]
    assert "ran_in" not in r


def test_an_admin_is_answered_as_before(ws, settings, people, host_dir):
    _on(settings, ws)
    _, r = _call("get_workspace", "", "boss")
    assert r["output"].startswith("No workspace is set. The shell and file tools run in your "
                                  "workstation")
    settings["workstation_route_tools"] = False
    _, r = _call("get_workspace", "", "boss", workspace=str(host_dir))
    assert r["output"].startswith(f"{host_dir}\n(File tools are confined to this folder")


def _turn(monkeypatch, owner):
    """One agent turn whose model calls `get_workspace` (`P20-03`'s `_loop`,
    with the tool the turn is about among the relevant ones): the events, and
    whether the turn offered the tool at all."""
    import asyncio
    import json

    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    # `{}`: an empty fence is not parsed as a call (filed — the prompt's own
    # example for this tool is one).
    replies, prompts = iter(["```get_workspace\n{}\n```"]), []

    async def fake_stream(*a, **k):
        prompts.append(json.dumps(a[1] if len(a) > 1 else k.get("messages"), default=str))
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "where am I working?"}], max_rounds=2, owner=owner,
            session_id="s1", workspace=None, relevant_tools={"get_workspace", "bash"})]

    events = [json.loads(c[6:]) for c in asyncio.run(drain())
              if c.startswith("data: {")]
    return events, "```get_workspace" in prompts[0]


def test_the_loop_offers_it_to_whom_the_dispatcher_allows_it(ws, settings, people, monkeypatch):
    """Offered and allowed are one decision: the granted person's turn is told
    of the tool, runs it and reads her home; the ungranted one's is not told of
    it, and a call is refused before it runs."""
    _on(settings, ws)
    events, offered = _turn(monkeypatch, "ann")
    out = next(e for e in events if e.get("type") == "tool_output")
    assert offered and out["exit_code"] == 0 and str(_home(ws, "ann")) in out["output"], out
    events, offered = _turn(monkeypatch, "bob")
    out = next(e for e in events if e.get("type") == "tool_output")
    assert not offered and out["exit_code"] == 1, out
    assert str(_home(ws, "bob")) not in json_dumps(out)


def json_dumps(value) -> str:
    import json
    return json.dumps(value)


# ── what it is described as ──────────────────────────────────────────────────


def _descriptions():
    from src.agent_loop import TOOL_SECTIONS
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    schema = next(s["function"]["description"] for s in FUNCTION_TOOL_SCHEMAS
                  if s.get("function", {}).get("name") == "get_workspace")
    return {"schema": schema, "section": TOOL_SECTIONS["get_workspace"],
            "index": BUILTIN_TOOL_DESCRIPTIONS["get_workspace"]}


@pytest.mark.parametrize("where", ["schema", "section", "index"])
def test_each_description_says_what_holds_on_each_machine(where):
    text = _descriptions()[where]
    here, _, there = text.partition("workstation")
    assert there, f"{where}: never says what holds in the workstation"
    # On Pantheon's machine: confined. In the workstation: where they start,
    # and not a boundary — the two claims each on its own machine's side.
    assert "Pantheon's own machine" in here and "confined" in here.lower(), where
    assert "not a boundary" in there.lower(), where
    assert "confined" not in there.lower(), where


def test_the_answer_names_the_workstation_as_the_descriptions_promise(ws, settings, people):
    """They say "the answer says so": the workstation's answer does."""
    _on(settings, ws)
    _, r = _call("get_workspace", "", "ann")
    assert "your workstation" in r["output"]
