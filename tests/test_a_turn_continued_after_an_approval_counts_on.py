# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1199`: after an approval the continuation's steps count on from the turn's.

`CHAT-M-8`'s rest. A run resumed from an approval card counts its own rounds
from 1 — `round` indexes its `round_texts` and its budget, and has to — so a
turn read `list · APPROVED · 1 done` then `read · 1 done`, where the audit
asks for 1..n across the turn; and the history renderer drew the
continuation's round-1 bubble before the approved row, where the live stream
draws the row first.

The server stamps `step_offset` beside `round` on the continuation's own
events — the steps the turn took before this run's round 1: the round the card
was asked in, on top of the asking run's own offset — and the card names
`round + step_offset` (`agentThread.shownStep`). The approved call keeps the
asking run's numbering. A run paused again keeps its offset on the card it
mints, so a chain of approvals keeps counting.

This file drives the loop (the wire); the cards, live and after a reload, are
driven under node in `tests/test_one_agent_turn_is_one_reply.py`.
"""
import asyncio
import json

import src.agent_loop as agent_loop
from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import capabilities_for_action


def _patch(monkeypatch, script):
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set())
    monkeypatch.setattr(agent_loop, "_agent_route_tool_mode",
                        lambda *a, **k: (True, False, False))
    steps = iter(script)

    async def fake_stream(*args, **kwargs):
        step = next(steps, "Done.")
        if isinstance(step, list):
            yield f'data: {json.dumps({"type": "tool_calls", "calls": step})}\n\n'
        else:
            yield f"data: {json.dumps({'delta': step})}\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *args, **kwargs):
        return block.tool_type, {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute)


def _events(generator):
    async def _drain():
        return [chunk async for chunk in generator]

    out = []
    for chunk in asyncio.run(_drain()):
        if chunk.startswith("data: {"):
            try:
                out.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return out


def _grant(*, requested_round, continuation_turn=None):
    store = ToolApprovalStore()
    pending = store.create(
        owner="alice", session_id="s1", origin_run_id="r1", tool_name="bash",
        content="printf hi", workspace=None, external_untrusted_context_seen=True,
        requested_round=requested_round,
        capabilities=capabilities_for_action("bash", "printf hi"),
        continuation_turn=continuation_turn,
    )
    grant = store.consume(pending.approval_id, decision="approve",
                          owner="alice", session_id="s1")
    assert grant is not None
    return grant


def _continue(monkeypatch, grant, script):
    _patch(monkeypatch, script)
    return _events(agent_loop.stream_agent_loop(
        "http://local.test/v1", "small-local-model",
        [{"role": "user", "content": "yes, go ahead"}],
        max_rounds=4, owner="alice", session_id="s1", workspace=None,
        relevant_tools={"bash", "ask_user"}, exact_approval=grant,
    ))


READ = [{"name": "bash", "arguments": json.dumps({"command": "printf two"})}]


def _cards(events):
    return [e for e in events if e.get("type") in ("tool_start", "tool_output")]


def _persisted(events):
    metrics = next(e for e in events if e.get("type") == "metrics")
    return metrics["data"].get("tool_events") or []


def test_the_continuations_own_steps_count_on_from_the_card(monkeypatch):
    """Asked at step 3: the approved call is step 3, the continuation's own
    round 1 is step 4 — live and on the record a reload draws from."""
    events = _continue(monkeypatch, _grant(requested_round=3), [READ, "Done."])
    approved = [e for e in _cards(events) if e.get("approved")]
    own = [e for e in _cards(events) if not e.get("approved")]
    assert approved and own, events
    for e in approved:
        assert e["round"] == 3 and "step_offset" not in e, e
    for e in own:
        assert e["round"] == 1 and e["step_offset"] == 3, e
    persisted = _persisted(events)
    assert [(e["round"], e.get("step_offset")) for e in persisted] == [(3, None), (1, 3)]


def test_a_first_run_carries_no_offset(monkeypatch):
    """Absent, not 0, on a turn's first run: every event that never needed it
    is the shape it was (`tests/test_tool_effect_wire.py` pins that)."""
    _patch(monkeypatch, [READ, "Done."])
    events = _events(agent_loop.stream_agent_loop(
        "http://local.test/v1", "small-local-model",
        [{"role": "user", "content": "run it"}], max_rounds=3,
        relevant_tools={"bash"}, _is_teacher_run=True))
    assert _cards(events)
    assert not any("step_offset" in e for e in events), events


def test_a_chain_of_approvals_keeps_counting(monkeypatch):
    """The asking run was itself a continuation, at offset 2, and asked at its
    own round 3 — step 5 of the turn. Its approved call is step 5; this run's
    round 1 is step 6."""
    paused = agent_loop._paused_turn(
        [], round_response="", round_reasoning="", used_native=False, calls=[],
        tool_results=[], tool_result_texts=[], tool_result_records=[], round_num=3,
        step_offset=2)
    events = _continue(monkeypatch, _grant(requested_round=3, continuation_turn=paused),
                       [READ, "Done."])
    approved = [e for e in _cards(events) if e.get("approved")]
    own = [e for e in _cards(events) if not e.get("approved")]
    assert all(e["round"] + e.get("step_offset", 0) == 5 for e in approved), approved
    assert all(e["round"] + e["step_offset"] == 6 for e in own), own


def test_a_card_minted_by_a_continuation_keeps_its_runs_offset():
    """The other half of the chain: the record a card keeps of the turn it
    stopped says where that run's steps started."""
    turn = agent_loop._paused_turn(
        [], round_response="", round_reasoning="", used_native=False, calls=[],
        tool_results=[], tool_result_texts=[], tool_result_records=[], round_num=2,
        step_offset=4)
    assert turn is not None and turn.step_offset == 4
