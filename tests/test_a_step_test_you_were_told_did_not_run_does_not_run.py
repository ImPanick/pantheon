# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1093` — *Test this step* that the person was told did not run does not run
afterwards, and a test leaves no chat behind.

**Measured on the merged tree** (drive runs 1 and 2, the server log): a test of
a Prompt step on a local model answered "Not tested: Request exceeded 45s
timeout" — `app.py`'s request ceiling, a 504 — and the test kept running on
the server: its model round completed 91 s after the press, 46 s after the
504. `_RequestTimeoutMiddleware`'s `wait_for` stops waiting for the handler,
not the handler (`BaseHTTPMiddleware` lets the endpoint finish). And the press
made a chat, "[Task] Morning inbox brief", in the Tasks folder — empty, before
the workflow had ever run, and kept on its trigger.

Now the route awaits the test only while the request is waiting for it, and a
test removes the chat it made. Driven (`Law 20`): the real route helper
(`_while_the_request_waits`), the real `test_workflow_node`, the real Prompt
executor and agent loop, and a real `SessionManager` on one SQLite file. (The
out-of-process drive through the request ceiling moved to
`tests/test_a_slow_step_test_waits_for_its_answer.py` when `B1496` exempted
the route from that ceiling.)
"""
from __future__ import annotations

import json

import pytest

from tests.helpers.walker_harness import make_db, node, seed_workflow

ENDPOINT = dict(model="scripted", endpoint_url="http://127.0.0.1:9/v1")


# ── the chat ────────────────────────────────────────────────────────────────

@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.session_manager as sm_mod
    import src.agent_loop as agent_loop
    import src.task_endpoint as task_endpoint
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "chat.db")
    monkeypatch.setattr(sm_mod, "SessionLocal", factory)

    async def model(candidates, messages, **kwargs):
        yield f"data: {json.dumps({'delta': 'The summary.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", model)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(task_endpoint, "resolve_task_candidates", lambda **kw: [])
    manager = sm_mod.SessionManager()
    s = TaskScheduler(manager)
    s._log_to_assistant = lambda *a, **k: None
    return factory, s, manager


def _chats(factory):
    from core.database import Session as DbSession
    db = factory()
    try:
        return [(r.id, r.name, r.folder) for r in db.query(DbSession).all()]
    finally:
        db.close()


def _trigger(factory):
    from core.database import ScheduledTask
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first()
    finally:
        db.close()


STEP = node("n1", "Send me the summary", prompt="Summarise my inbox.", **ENDPOINT)


@pytest.mark.asyncio
async def test_a_tested_prompt_step_leaves_no_chat(world):
    factory, s, manager = world
    seed_workflow(factory, [STEP], [], name="Morning inbox brief")
    out = await s.test_workflow_node(_trigger(factory), "Morning inbox brief", STEP)
    assert (out["status"], out["text"]) == ("success", "The summary."), out
    assert _chats(factory) == [], "the test left a chat in the sidebar"
    assert _trigger(factory).session_id is None, "…or one kept on the trigger"
    assert manager.sessions == {}


@pytest.mark.asyncio
async def test_a_workflow_that_has_a_chat_keeps_it_through_a_test(world):
    """`Law 1`: a chat a real run made is the workflow's; a test runs in it and
    leaves it exactly where it was."""
    factory, s, manager = world
    seed_workflow(factory, [STEP], [], name="Morning inbox brief")
    await s._execute_task("wf")
    [(chat, name, folder)] = _chats(factory)
    assert (name, folder) == ("[Task] Morning inbox brief", "Tasks")
    assert _trigger(factory).session_id == chat
    out = await s.test_workflow_node(_trigger(factory), "Morning inbox brief", STEP)
    assert out["status"] == "success"
    assert [c[0] for c in _chats(factory)] == [chat]
    assert _trigger(factory).session_id == chat


# ── the page that asked stops waiting ───────────────────────────────────────
#
# `B1496` changed how this is reached. The out-of-process case here drove the
# request ceiling: a step test slower than it answered 504 and — since this
# row — did not run on. The step-test route is exempt from that ceiling now (a
# slow model's step can be tested, within the test's own budget), so that
# case moved to `tests/test_a_slow_step_test_waits_for_its_answer.py`, which
# holds the new answer. What still ends a test early is the page that asked
# for it going away, and that is what `_while_the_request_waits` watches for:
# driven here with the real route helper, the real `test_workflow_node` and
# the real agent loop, the model scripted and slower than the page's patience.

class _PageThatLeaves:
    """A request whose `receive` answers `http.disconnect` once `when()` is
    true — what a closed tab or a cancelled fetch looks like to the endpoint.

    `B1598`. It left after 0.3 s, and the test's premise — the model round had
    begun by then — held only because the run's start-up reads (approval mode,
    run limits, the run-config row) blocked the event loop, so the timer could
    not fire until the model was called. Those reads are a worker thread's
    now, the loop answers the page on time, and 0.3 s came before the model.
    The page leaves on the condition the test is about: the round started."""

    def __init__(self, when):
        self.when = when

    async def receive(self):
        import asyncio
        for _ in range(3000):
            if self.when():
                break
            await asyncio.sleep(0.01)
        return {"type": "http.disconnect"}


@pytest.mark.asyncio
async def test_a_test_whose_page_stopped_waiting_does_not_run_on(world, monkeypatch):
    import asyncio
    import src.agent_loop as agent_loop
    from routes.workflow.workflow_routes import TEST_REQUEST_GONE, _while_the_request_waits
    from src.workflow_store import WorkflowRefused

    factory, s, manager = world
    rounds = {"started": 0, "completed": 0}

    async def slow_model(candidates, messages, **kwargs):
        rounds["started"] += 1
        await asyncio.sleep(1.5)               # a local model, slower than the page waits
        rounds["completed"] += 1
        yield f"data: {json.dumps({'delta': 'The summary.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", slow_model)
    seed_workflow(factory, [STEP], [], name="Morning inbox brief")
    test = s.test_workflow_node(_trigger(factory), "Morning inbox brief", STEP)
    with pytest.raises(WorkflowRefused) as told:
        await _while_the_request_waits(_PageThatLeaves(lambda: rounds["started"] == 1), test)
    assert told.value.status == 503 and told.value.sentence == TEST_REQUEST_GONE
    await asyncio.sleep(2.0)                   # past when the round would have finished
    assert rounds == {"started": 1, "completed": 0}, \
        f"the test they were told did not run, ran: {rounds}"
    assert _chats(factory) == [], "the cancelled test left a chat"
