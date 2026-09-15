# SPDX-License-Identifier: AGPL-3.0-or-later
"""B14 — the run tells the client whether a steer can reach it.

`P6-18` gated the steer bar on the composer's own mode getter, which closed the
chat-mode case. Three others stayed open — a research turn, an image-generation
session and a compare pane all draw a bar the server then refuses with
`no_active_run` — and none of them is visible from the composer:

  * research is decided server-side. `research_pending` auto-triggers research
    on the NEXT message (`chat_routes.py` ~:1424) and `chat.js` clears the
    research toggle at send (~:2947), so the composer says "not research" for a
    turn that is;
  * the same decision runs the other way. `can_use_research: False`, a tool
    policy that blocks `trigger_research`, and auto-escalation from chat to
    agent all produce a steerable run the composer would have called
    unsteerable;
  * image sessions and compare panes the composer never knew about at all.

So the client cannot derive this, and `P6-18`'s capability probe cannot either:
it fires once per page load and answers a per-BUILD question. The run answers
it, with the same value `agent_runs.start` is given, as the stream's first
event.

What is pinned:

  * the announcement is the FIRST event, because the composer has already drawn
    the bar by the time the POST goes out;
  * the announced value and `agent_runs.is_steerable` agree, on every branch.
    Two readers, one decision — if they could drift, the affordance and the
    refusal would drift apart and this row would be back;
  * a research turn announces False while still being a live, resumable run;
  * a compare pane announces False, because it is never registered and a steer
    aimed at it is refused for want of a run.
"""

import json
from types import SimpleNamespace

import pytest

import routes.chat_routes as chat_routes
from src import agent_runs

from tests.test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint


async def _drain(response):
    """Every SSE event the stream produced, in order."""
    events = []
    async for chunk in response.body_iterator:
        for line in str(chunk).splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                continue
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


async def _first_steerable(response):
    """The announced value, read without draining the rest of the stream."""
    async for chunk in response.body_iterator:
        for line in str(chunk).splitlines():
            if line.startswith("data: ") and '"stream_steerable"' in line:
                return json.loads(line[6:])["steerable"]
    return None


def _request(mode, *, research=False, compare=False):
    req = _RouteRequest(mode)
    req._form["compare_mode"] = "true" if compare else "false"
    if research:
        req._form["use_research"] = "true"
    return req


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, expected", [("agent", True), ("chat", False)])
async def test_the_first_event_says_whether_this_run_can_be_steered(monkeypatch, mode, expected):
    endpoint = _chat_stream_endpoint(monkeypatch, mode, {})
    agent_runs._RUNS.pop("session-1", None)
    try:
        response = await endpoint(_request(mode))
        events = await _drain(response)
    finally:
        agent_runs._RUNS.pop("session-1", None)

    assert events, "the stream produced no parseable events"
    first = events[0]
    assert first["type"] == "stream_steerable", (
        "the composer draws the bar before this POST goes out, so a correction "
        f"that arrives behind other events is a longer lie; got {first['type']!r}"
    )
    assert first["steerable"] is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["agent", "chat"])
async def test_the_announcement_is_the_value_the_steer_route_gates_on(monkeypatch, mode):
    """One decision, two readers. `agent_runs.is_steerable` is what refuses the
    steer; the announcement is what draws the bar. If these can disagree, the
    control is offered exactly where it cannot work, which is the row."""
    endpoint = _chat_stream_endpoint(monkeypatch, mode, {})
    agent_runs._RUNS.pop("session-1", None)
    try:
        response = await endpoint(_request(mode))
        announced = await _first_steerable(response)
        assert announced is not None
        # The registry entry `is_steerable` reads, caught before the run's own
        # liveness can expire — that half of `is_steerable` is not this row's
        # question and would make the test a race.
        run = agent_runs._RUNS.get("session-1")
        assert run is not None, "a non-compare stream is registered as a detached run"
        assert run.steerable is announced
    finally:
        agent_runs._RUNS.pop("session-1", None)


@pytest.mark.asyncio
async def test_a_research_turn_announces_that_it_cannot_take_a_steer(monkeypatch):
    """The row's case. A research turn is `mode: 'agent'` as far as the composer
    is concerned, and the server refuses its steers — so the bar was offered on
    the one turn that could only decline."""
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {})
    agent_runs._RUNS.pop("session-1", None)
    try:
        response = await endpoint(_request("agent", research=True))
        announced = await _first_steerable(response)
        assert announced is False, (
            "research returns from its own block before the branch that drains "
            "the steer inbox; a bar drawn here can only be refused"
        )
        # And it is a real, registered, resumable run — which is why the client
        # could never tell it apart from a steerable one by looking at liveness.
        run = agent_runs._RUNS.get("session-1")
        assert run is not None and run.steerable is False
    finally:
        agent_runs._RUNS.pop("session-1", None)


@pytest.mark.asyncio
async def test_a_compare_pane_announces_that_it_cannot_take_a_steer(monkeypatch):
    """A compare pane never reaches `agent_runs.start`, so `is_steerable` is
    False for it whatever the mode. The predicate has to say so, or the one
    stream that is returned raw would be the one the announcement lies about."""
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {})
    agent_runs._RUNS.pop("session-1", None)
    try:
        response = await endpoint(_request("agent", compare=True))
        events = await _drain(response)
        assert events[0] == {"type": "stream_steerable", "steerable": False}
        assert agent_runs.is_steerable("session-1") is False
    finally:
        agent_runs._RUNS.pop("session-1", None)


@pytest.mark.parametrize("compare_mode, expected", [(False, True), (True, False)])
def test_compare_mode_is_stated_inside_the_predicate(compare_mode, expected):
    """It used to live at the one call site, which ran after compare mode had
    already returned. `B14` gave the predicate a second reader that DOES run on
    a compare pane, so the clause moved in with the other three."""
    assert chat_routes._stream_is_steerable(
        chat_mode="agent",
        is_image_session=False,
        do_research=False,
        compare_mode=compare_mode,
    ) is expected


def test_an_image_session_still_refuses(monkeypatch):
    """Unchanged by this row and easy to lose: an image-generation session
    generates and returns, so it drains no inbox either."""
    assert chat_routes._stream_is_steerable(
        chat_mode="agent", is_image_session=True, do_research=False,
    ) is False


@pytest.mark.parametrize("kwargs, asked", [
    ({"chat_mode": "agent", "do_research": False}, True),
    ({"chat_mode": "chat", "do_research": False}, False),
    ({"chat_mode": "agent", "do_research": True}, False),
    ({"chat_mode": "agent", "do_research": False, "compare_mode": True}, False),
])
def test_the_database_backed_term_is_only_reached_when_it_can_change_the_answer(kwargs, asked):
    """`_is_image_generation_session` opens a DB session and queries the endpoint
    table; the other three terms are locals. The route has an answer already
    (`image_generation_session`, `chat_routes.py:1457`) and cannot reuse it —
    that one is computed before `build_chat_context` normalises the session's
    model, and this predicate asks about the normalised one — so the choice is a
    second query or a deferred one. Moving the call up to where the announcement
    needs it would otherwise have put that second query on every compare pane as
    well, since compare mode used to return before the old call site."""
    calls = []

    def _image_check():
        calls.append(1)
        return False

    chat_routes._stream_is_steerable(is_image_session=_image_check, **kwargs)
    assert bool(calls) is asked


@pytest.mark.asyncio
async def test_the_route_makes_no_second_image_query_on_a_turn_locals_settle(monkeypatch):
    """The same property through the real route, stated as a difference so it
    does not pin the route's other, unrelated image checks: the steerability
    decision costs one query on an agent turn and none on a chat turn."""
    async def _count(mode):
        endpoint = _chat_stream_endpoint(monkeypatch, mode, {})
        calls = []
        monkeypatch.setattr(
            chat_routes, "_is_image_generation_session",
            lambda *a, **k: (calls.append(1), False)[1],
        )
        agent_runs._RUNS.pop("session-1", None)
        try:
            response = await endpoint(_request(mode))
            await _first_steerable(response)
            return len(calls)
        finally:
            agent_runs._RUNS.pop("session-1", None)

    assert await _count("agent") - await _count("chat") == 1
