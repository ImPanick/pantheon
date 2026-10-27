# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1344`: a turn about to be cut off at the step cap is told so.

`stream_agent_loop` emitted the round limit to the browser every round
(`agent_budget`) and `rounds_exhausted` when it hit it — and nothing in the
request told the model. So a run about to be cut wrote no closing summary,
and the person's last bubble was a half-finished thought above a Continue
button.

`Verify:` drive `stream_agent_loop` with `max_rounds=2` and assert the final
round's request carries the figure, and that a turn with rounds to spare does
not. The figure is asserted equal to the `agent_budget` frame's
`round_limit` for the same run, so the model and the meter read one number.
"""
import asyncio
import json

import pytest

import src.agent_loop as agent_loop
from tests.helpers.no_endpoint import no_endpoint_answers  # B1520


@pytest.fixture(autouse=True)
def _no_endpoint_answers(monkeypatch):
    """`B1546`. These turns run against `https://models.example.com/v1`, and the agent loop
    asks it for its context window on the way in — six requests to the network
    that passed because they failed.
    The lookup now fails the way it did, with no socket opened."""
    no_endpoint_answers(monkeypatch)


URL = "https://models.example.com/v1"


def _drive(monkeypatch, *, max_rounds, script):
    requests = []
    rounds = iter(script)
    monkeypatch.setattr(agent_loop, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *args, **kwargs: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set())
    monkeypatch.setattr(
        agent_loop, "_agent_route_tool_mode", lambda *args, **kwargs: (True, False, False)
    )

    async def fake_stream(candidates, messages, **kwargs):
        # As `llm_core.stream_llm_with_fallback` does for every candidate:
        # the request is what the loop's factory builds, not the raw history.
        request = kwargs["candidate_request_factory"](0, *candidates[0])
        if hasattr(request, "__await__"):
            request = await request
        requests.append([dict(m) for m in request["messages"]])
        step = next(rounds, "All done.")
        if isinstance(step, list):
            yield f'data: {json.dumps({"type": "tool_calls", "calls": step})}\n\n'
        else:
            yield "data: " + json.dumps({"delta": step}) + "\n\n"
        yield "data: [DONE]\n\n"

    async def fake_execute(block, *args, **kwargs):
        return block.tool_type, {"output": "ok", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream)
    monkeypatch.setattr(agent_loop, "execute_tool_block", fake_execute)

    async def _drain():
        return [
            chunk
            async for chunk in agent_loop.stream_agent_loop(
                URL,
                "some-model",
                [{"role": "user", "content": "list the files and then summarise them"}],
                max_rounds=max_rounds,
                relevant_tools={"bash", "ask_user", "update_plan"},
                owner="local",
                _is_teacher_run=True,
            )
        ]

    events = []
    for chunk in asyncio.run(_drain()):
        if chunk.startswith("data: {"):
            try:
                events.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    limits = {e["round_limit"] for e in events if e.get("type") == "agent_budget"}
    return requests, limits


def _notes(request):
    return [m["content"] for m in request
            if m.get("role") == "system" and "This is step" in str(m.get("content"))]


BASH = [{"name": "bash", "arguments": json.dumps({"command": "ls"})}]


def test_the_last_steps_requests_carry_the_loops_own_figure(monkeypatch):
    requests, limits = _drive(monkeypatch, max_rounds=2, script=[BASH, "Here they are."])
    assert limits == {2}, "the meter and the note must read the same cap"
    assert len(requests) == 2
    (last,) = _notes(requests[-1])
    assert "step 2 of 2" in last and "last" in last
    # It is the request's final word, after the tool result it follows.
    assert requests[-1][-1]["content"] == last
    # The step before the last is told how many are left.
    (first,) = _notes(requests[0])
    assert "step 1 of 2" in first


def test_a_turn_with_rounds_to_spare_is_told_nothing(monkeypatch):
    requests, limits = _drive(monkeypatch, max_rounds=10, script=[BASH, "Here they are."])
    assert limits == {10}
    assert len(requests) == 2
    assert all(_notes(r) == [] for r in requests)


def test_the_note_rides_the_request_and_not_the_turns_history(monkeypatch):
    """Kept out of `messages`, so a turn paused for a card (`B1069`) does not
    carry a stale "step N of N" into a continuation with its own steps: the
    second request holds the round-2 note and not round 1's as well."""
    requests, _limits = _drive(monkeypatch, max_rounds=2, script=[BASH, "Here they are."])
    assert len(_notes(requests[-1])) == 1
