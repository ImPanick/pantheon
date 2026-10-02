# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1069`'s fallback half — round 1 of a fallback carries what the run added.

A fallback candidate's round-1 request is built from the route-neutral history
the run started with (`_initial_route_source_messages`), so that a candidate
with a larger window can recover history the primary's compaction set aside.
That history holds nothing the run itself has added, so before this row a
resumed turn's first round, when its primary was down, reached the fallback
without the approved result at all — the half of `B1069` the showcase could not
see, because its scripted model never fails — and a steer delivered at round 1
reached the primary and not the fallback. Later rounds build fallbacks from the
run's own messages and never had either loss.

Both are driven through the real chat route — the approval route, for the first
— the real agent loop and the real fallback wrapper, down to the payload
builders, with only the sockets faked (`B935`'s `wire`, the primary answering
503); the prompt builder and tool discovery are stubbed as `B935`'s and
`B1034`'s agent-door tests stub them. The approved call runs for real
(`update_plan`, which needs no store), and the card's record of the turn is the
one `agent_loop._paused_turn` makes, so what is checked is the resume, not a
hand-built transcript.
"""
import json

import pytest

import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
import src.llm_core as llm_core
import src.model_context as model_context
from src.tool_capabilities import capabilities_for_action
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_pr6020_rebase_regressions import _install_route_probe  # noqa: E402
from test_the_operator_s_token_ceiling_wins_on_every_door import (  # noqa: E402
    BRAINSTORM, CLOUD, OTHER, TASK, _drain, _fallback_to)
from test_the_qwen3_cap_guards_every_door import wire  # noqa: E402,F401  (a fixture)

BACKUP = "https://backup.example/v1"
STAND_IN = "Allow this task to continue?"
PLAN = json.dumps({"plan": "- [ ] read the tasks\n- [ ] plan the week"})
TASKS = json.dumps({"action": "list"})
TASKS_SAID = "### manage_tasks: list\nNo scheduled tasks yet."


@pytest.fixture(autouse=True)
def window(monkeypatch):
    monkeypatch.setattr(model_context, "_query_context_length",
                        lambda url, model: (32_768, True))
    monkeypatch.setattr(model_context, "_context_cache", {})


def _paused_turn():
    """What the run that minted the card had: one round (the task list) and the
    paused round, whose second call — the plan — the card stopped."""
    earlier = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "manage_tasks", "arguments": TASKS}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": TASKS_SAID,
         "metadata": {"trusted": False, "source": "tool result: manage_tasks",
                      "tool_gate_untrusted": True}},
    ]
    agent_loop._mark_in_turn(earlier)
    return agent_loop._paused_turn(
        [{"role": "user", "content": TASK[0]["content"]}] + earlier,
        round_response="", round_reasoning="", used_native=True,
        calls=[{"id": "call_2", "name": "update_plan", "arguments": PLAN}],
        tool_results=[], tool_result_texts=[], tool_result_records=[], round_num=2)


async def _resume(monkeypatch, wire):
    """The person answers the card; the primary is down for the continuation."""
    _install_route_probe(monkeypatch)
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", llm_core.stream_llm_with_fallback)
    pending = chat_routes.tool_approval_store.create(
        owner="alice", session_id="session-1", origin_run_id="run-1",
        tool_name="update_plan", content=PLAN, workspace=None,
        external_untrusted_context_seen=True, selected_tools=["update_plan", "manage_tasks"],
        capabilities=capabilities_for_action("update_plan", PLAN),
        continuation_turn=_paused_turn())
    history = TASK + [{"role": "assistant", "content": STAND_IN, "metadata": {
        "tool_events": [{"tool": "update_plan", "ask_user": {
            "kind": "tool_approval", "approval_id": pending.approval_id}}]}}]
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {}, model=OTHER, endpoint_url=CLOUD,
                                     context_overrides={"preset": BRAINSTORM, "messages": history,
                                                        "route_messages": history})
    _fallback_to(monkeypatch, BACKUP, OTHER)
    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent_loop.stream_agent_loop)
    wire.down.add("selected.example")
    request = _RouteRequest("agent")
    request._form.update({"tool_approval_id": pending.approval_id,
                          "tool_approval_decision": "approve_task", "compare_mode": "false"})
    await _drain(await endpoint(request))
    return wire.sent


def _after_the_request(payload):
    messages = payload["messages"]
    at = max(i for i, m in enumerate(messages)
             if m["role"] == "user" and TASK[0]["content"] in str(m.get("content")))
    return messages[at + 1:]


@pytest.mark.asyncio
async def test_a_resumed_turn_reaches_the_fallback_whole(wire, monkeypatch):
    """The primary is down when the person approves: the fallback is asked with
    the turn the card stopped — the task list and its result, then the plan
    call answered by the approved result — exactly as the primary was."""
    sent = await _resume(monkeypatch, wire)
    assert [url.split("//")[1].split("/")[0] for url, _p in sent] == [
        "selected.example", "backup.example"]
    primary, backup = (_after_the_request(payload) for _u, payload in sent)
    assert backup == primary
    assert [m["role"] for m in backup] == ["assistant", "tool", "assistant", "tool"]
    assert [c["function"]["name"] for m in backup[::2] for c in m["tool_calls"]] == [
        "manage_tasks", "update_plan"]
    assert [m["tool_call_id"] for m in backup[1::2]] == ["call_1", "call_2"]
    assert backup[1]["content"] == TASKS_SAID
    assert "Plan updated" in backup[3]["content"]
    assert STAND_IN not in json.dumps(backup)


@pytest.mark.asyncio
async def test_a_round_one_steer_reaches_the_fallback(wire, monkeypatch):
    """A course correction delivered at round 1 is in the fallback's request as
    it is in the primary's. (Sent as the run starts: the run's own start-of-run
    sweep, which drops a steer that missed its run, is held off for this one.)"""
    _install_route_probe(monkeypatch)
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", llm_core.stream_llm_with_fallback)
    monkeypatch.setattr(agent_loop, "clear_steers", lambda session_id: 0)
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {}, model=OTHER, endpoint_url=CLOUD,
                                     context_overrides={"preset": BRAINSTORM, "messages": TASK,
                                                        "route_messages": TASK})
    _fallback_to(monkeypatch, BACKUP, OTHER)
    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent_loop.stream_agent_loop)
    wire.down.add("selected.example")
    agent_loop.submit_steer("session-1", "Only the allocator's spilling stage, please.")
    try:
        await _drain(await endpoint(_RouteRequest("agent")))
    finally:
        agent_loop.take_steers("session-1")
    primary, backup = (payload["messages"] for _u, payload in wire.sent)
    assert backup == primary
    # Consecutive user messages are merged for the wire, so the steer is the
    # tail of the last one.
    assert "spilling stage" in backup[-1]["content"]


@pytest.mark.asyncio
async def test_a_fresh_turn_s_fallback_is_built_from_history_as_before(wire, monkeypatch):
    """Nothing added, nothing changed: round 1's fallback is still built from the
    route-neutral history, the reason it is built from there at all."""
    _install_route_probe(monkeypatch)
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", llm_core.stream_llm_with_fallback)
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {}, model=OTHER, endpoint_url=CLOUD,
                                     context_overrides={"preset": BRAINSTORM, "messages": TASK,
                                                        "route_messages": TASK})
    _fallback_to(monkeypatch, BACKUP, OTHER)
    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent_loop.stream_agent_loop)
    wire.down.add("selected.example")
    await _drain(await endpoint(_RouteRequest("agent")))
    primary, backup = (_after_the_request(payload) for _u, payload in wire.sent)
    assert backup == primary == []
