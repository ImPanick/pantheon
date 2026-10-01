# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1047` — "Run now" with Pantheon open was recorded "Stopped by user", and
the run later went ahead anyway.

**Measured 2026-10-01 on the tree before this file, through the code in it**
(`/tmp/scratch-wb-runs/probe_b1047.py`, Python 3.11.15): with a heartbeat
recorded, `run_task_now` on a Prompt task whose failure branch is wired left the
run `queued` behind the idle gate; one foreground request — the page's own
`GET /api/email/accounts`, reproduced as `_InteractiveActivityMiddleware` makes
it — wrote the row `aborted · "Stopped by user"`, while the run's task was NOT
done and its `_executing` claim was still held; when the heartbeat lapsed the
"stopped" run executed and chained into its failure branch. Three causes, each
held by a test here:

  (a) `stop_background_tasks_for_foreground` called `_mark_run_aborted(task_id)`
      with its default message, so a pre-emption by the gate read as the
      person's own act;
  (b) `wait_for_interactive_quiet` waited with `asyncio.wait_for(cond.wait())`,
      and on 3.11 `wait_for` drops a cancel that lands in the same tick as the
      notify that completes the inner wait — which is exactly the middleware's
      order (schedule the stop, then notify). 3.12 and 3.13 do not swallow it
      (verify-a's standalone repro: 3.11.15 "kept running after cancel()",
      3.12.3 and 3.13.13 "cancelled");
  (c) every run waited for Pantheon to be idle — no request in the quiet
      window and no visible tab's heartbeat in 45 s — so a run a person
      started never ran while the page they started it from stayed open.

Everything is real (`Law 20`): the real `src.interactive_gate`, the real
`TaskScheduler` (`run_task_now` → `_execute_task` → `_execute_task_locked` →
`_advance_chain` → `_run_chained`), the real task route's handler, a real
SQLite file, real asyncio. Only the model is absent: `_execute_llm_task` fails
the way a Pantheon with no model fails, or hands straight to the real
`_run_agent_loop` with `stream_agent_loop` answering one line. Nothing waits on
the wall clock: the gate's quiet window is 0 and every step is driven by the
notifies the real request tracker sends.
"""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.interactive_gate as ig  # noqa: E402
import src.task_scheduler as ts  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}

NO_MODEL = "No model/endpoint configured"


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'run-now.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


@pytest.fixture()
def gate(monkeypatch):
    """The real gate, on, from a clean slate: no requests, no heartbeat, no
    chat. The quiet window is 0 so nothing here waits on the wall clock."""
    monkeypatch.delenv("BACKGROUND_TASK_FOREGROUND_GATE", raising=False)
    monkeypatch.setenv("BACKGROUND_TASK_QUIET_MS", "0")
    monkeypatch.setenv("BACKGROUND_TASK_BROWSER_ACTIVE_SECONDS", "45")
    monkeypatch.setenv("BACKGROUND_TASK_MAX_WAIT_SECONDS", "0")
    for name, value in (("_ACTIVE_REQUESTS", 0), ("_LAST_ACTIVITY", 0.0),
                        ("_LAST_BROWSER_ACTIVITY", 0.0), ("_COND", None),
                        ("_COND_LOOP", None)):
        monkeypatch.setattr(ig, name, value)
    chat = {"busy": False}
    monkeypatch.setattr(ig, "_has_active_chat_stream", lambda: chat["busy"])
    return chat


def _seed(factory, *, wire_failure=True):
    db = factory()
    try:
        db.add(ScheduledTask(
            id="msg", owner=None, name="Message me", prompt="Tell me the backup failed.",
            task_type="llm", trigger_type="webhook", status="active",
            output_target="session"))
        db.add(ScheduledTask(
            id="bk", owner=None, name="Nightly backup", prompt="Back up the notes folder.",
            task_type="llm", trigger_type="schedule", schedule="daily",
            scheduled_time="02:00", status="active", output_target="session"))
        db.commit()
        if wire_failure:
            db.query(ScheduledTask).filter(ScheduledTask.id == "bk").first().else_task_id = "msg"
            db.commit()
    finally:
        db.close()


def _runs(factory, task_id):
    db = factory()
    try:
        return [{"status": r.status, "error": r.error, "result": r.result,
                 "steps": json.loads(r.steps) if r.steps else []}
                for r in db.query(TaskRun).filter(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at).all()]
    finally:
        db.close()


def _next_run(factory, task_id):
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first().next_run
    finally:
        db.close()


def _scheduler(ran, *, block=None):
    """The real scheduler. Its model executor records the task and either fails
    as a Pantheon with no model does, or (with `block`) waits on an event."""
    s = TaskScheduler(None)

    async def _llm(task, db, run_id=None):
        ran.append(task.id)
        if block is not None:
            await block.wait()
            return "finished"
        raise RuntimeError(NO_MODEL)

    s._execute_llm_task = _llm
    s._log_to_assistant = lambda *a, **k: None

    async def _deliver(*a, **k):
        return None
    s._deliver_task_result = _deliver
    return s


async def _until(predicate, what, limit=400):
    """Let the loop run until `predicate()` holds — by loop turns, not time."""
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"never happened: {what}")


async def _turns(n=60):
    for _ in range(n):
        await asyncio.sleep(0)


async def _settled_in_the_wait():
    """A few more turns, so the run is parked INSIDE the gate's condition wait
    — its inner `cond.wait()` registered as a waiter — rather than on the way
    into it. That is the state a run sits in for as long as the page is open,
    and the only one in which a request's notify completes the inner wait in
    the same tick as the cancel: the case 3.11's `wait_for` swallowed. (Fired
    the instant the row says "waiting", the inner wait has not registered yet,
    the notify wakes nothing, and the cancel goes through on either version.)"""
    await _turns(10)


async def _page_request(scheduler, path="/api/email/accounts", method="GET"):
    """One foreground request, as `_InteractiveActivityMiddleware.dispatch`
    makes it: schedule the stop, then enter the request tracker — which
    notifies the gate's condition — in the same tick."""
    async def _stop_background():
        await scheduler.stop_background_tasks_for_foreground(
            reason=f"foreground request {method} {path}")
    asyncio.create_task(_stop_background())
    async with ig.track_interactive_request(path, method):
        await asyncio.sleep(0)


async def _heartbeat(scheduler):
    """`POST /api/activity/heartbeat`, as `app.activity_heartbeat` handles it."""
    await ig.mark_browser_activity()

    async def _stop_background():
        await ig.maybe_stop_background_tasks_for_heartbeat(
            scheduler.stop_background_tasks_for_foreground)
    asyncio.create_task(_stop_background())


async def _tab_closes():
    """No heartbeat for longer than the window, and the next request's notify
    wakes whatever was waiting on it."""
    ig._LAST_BROWSER_ACTIVITY = 0.0
    async with ig.track_interactive_request("/api/x", "GET"):
        pass


def _route_run_now(factory, monkeypatch, scheduler):
    """The real `POST /api/tasks/{id}/run` handler, called in this loop."""
    import routes.task.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", factory)
    router = task_routes.setup_task_routes(scheduler)
    endpoint = next(
        r.endpoint for r in router.routes
        if getattr(r, "path", None) == "/api/tasks/{task_id}/run"
        and "POST" in getattr(r, "methods", set()))
    request = SimpleNamespace(state=SimpleNamespace(current_user=None))
    return lambda task_id, **kw: endpoint(request, task_id, **kw)


# ── (b) the cause: a cancel that lands with a notify is not swallowed ───────

@pytest.mark.asyncio
@pytest.mark.parametrize("wait", ["wait_for_interactive_quiet", "wait_for_chat_quiet"])
async def test_a_cancel_that_lands_with_the_requests_notify_stops_the_wait(gate, wait):
    """The middleware's exact order — schedule a task that cancels the waiter,
    then notify the condition — against the gate's own waits. On 3.11 the old
    `wait_for(cond.wait())` returned instead of raising, and the waiter went
    back to waiting with nobody able to tell."""
    if wait == "wait_for_interactive_quiet":
        await ig.mark_browser_activity()      # Pantheon is open
    else:
        gate["busy"] = True                   # a chat reply is being written
    waiter = asyncio.create_task(getattr(ig, wait)("probe"))
    await _turns(5)
    assert not waiter.done(), "the wait did not wait"

    async def _cancel():
        waiter.cancel()
    asyncio.create_task(_cancel())
    async with ig.track_interactive_request("/api/email/accounts", "GET"):
        await asyncio.sleep(0)
    await _turns(10)

    assert waiter.done(), "the cancel was swallowed: the wait is still waiting"
    assert waiter.cancelled()


# ── (a)+(b) background work stopped by the page says so and stays stopped ───

@pytest.mark.asyncio
async def test_a_background_run_the_page_finds_waiting_keeps_waiting_and_runs_once_idle(
        task_db, gate):
    """A run nobody pressed — the event bus, the webhook and the schedule call
    `run_task_now` with no `started_by` — keeps the gate it was built for: it
    waits for Pantheon to be idle.

    `B1060` changed the second half of this test, on the integrator's call
    recorded on that row. It said the page STOPPED a waiting background run —
    "Paused because Pantheon became active" — and nothing ran afterwards; and
    for a webhook's or an event's run that was the payload gone for good. A
    waiting run now waits before it takes the model slot, holding nothing, so
    the page leaves it waiting, and once the tab closes it runs (and its
    failure branch with it). `tests/test_a_background_run_waits_for_idle_with_its_trigger.py`
    holds the rest of `B1060`."""
    _seed(task_db)
    ran = []
    s = _scheduler(ran)
    await _heartbeat(s)

    assert await s.run_task_now("bk") is True
    await _until(lambda: _runs(task_db, "bk") and _runs(task_db, "bk")[0]["result"]
                 == "Queued — waiting for Pantheon to be idle…", "the run waits for idle")
    await _settled_in_the_wait()

    await _page_request(s)
    await _turns(100)
    (run,) = _runs(task_db, "bk")
    assert run["status"] == "queued", "the page stopped a run that was only waiting"
    assert "bk" in s._executing and ran == []

    await _tab_closes()
    await _until(lambda: [r["status"] for r in _runs(task_db, "msg")] == ["error"],
                 "the run and its failure branch, once idle")
    assert ran == ["bk", "msg"]
    assert [r["status"] for r in _runs(task_db, "bk")] == ["error"]


@pytest.mark.asyncio
async def test_a_running_background_run_the_page_stops_keeps_the_gates_words_and_comes_back(
        task_db, gate):
    """The same stop landing while the executor is running. The cancel branch
    used to overwrite the row with its own guess — "Stopped by user", since its
    monitor had not fired — and reschedule the task as if the person had.

    `B1060` changed how it comes back: it was `next_run = now + 15 min` for any
    trigger; it is back in the queue at once, waiting for Pantheon to be idle,
    and its row says so. The gate's own words stay the run's `error`."""
    _seed(task_db, wire_failure=False)
    ran = []
    release = asyncio.Event()
    s = _scheduler(ran, block=release)
    before = _next_run(task_db, "bk")

    assert await s.run_task_now("bk") is True
    await _until(lambda: ran == ["bk"], "the run starts")
    await _heartbeat(s)          # the tab is open: whatever goes back waits
    await _page_request(s)
    await _until(lambda: len(_runs(task_db, "bk")) == 2, "the run goes back in the queue")
    await _settled_in_the_wait()

    stopped, again = _runs(task_db, "bk")
    assert stopped["status"] == "aborted"
    assert stopped["error"] == "Paused because Pantheon became active"
    assert stopped["result"] == ("Paused because Pantheon became active. It will run "
                                 "again, with what started it, once Pantheon is idle.")
    assert again["status"] == "queued"
    assert _next_run(task_db, "bk") == before, "the schedule moved for a run still to come"

    release.set()
    await _tab_closes()
    await _until(lambda: [r["status"] for r in _runs(task_db, "bk")] == ["aborted", "success"],
                 "it ran again once idle")


@pytest.mark.asyncio
async def test_the_stop_button_still_says_stopped_by_user(task_db, gate, monkeypatch):
    """`Law 1`. The person's own stop is unchanged, on a run they started, and
    the run does not go ahead after it either."""
    _seed(task_db)
    ran = []
    s = _scheduler(ran)
    gate["busy"] = True
    run_now = _route_run_now(task_db, monkeypatch, s)

    await run_now("bk")
    await _until(lambda: _runs(task_db, "bk") and _runs(task_db, "bk")[0]["result"]
                 == ts.WAITING_FOR_CHAT, "the run waits for the chat")
    await _settled_in_the_wait()

    assert await s.stop_task("bk") is True
    await _until(lambda: "bk" not in s._executing, "the claim is let go")
    gate["busy"] = False
    await _tab_closes()
    await _turns(200)

    (run,) = _runs(task_db, "bk")
    assert run["status"] == "aborted"
    assert run["error"] == run["result"] == "Stopped by user"
    assert ran == []


# ── (c) a run a person started ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_now_with_pantheon_open_runs_the_step_and_its_failure_branch(
        task_db, gate, monkeypatch):
    """The row's `Verify:` — and `P22-02`'s. The tab is open (heartbeat), the
    person presses Run now on a step whose failure branch is wired, the page
    goes on making its own requests: the step runs, fails, and its failure
    branch runs, while the page is still open."""
    _seed(task_db)
    ran = []
    s = _scheduler(ran)
    run_now = _route_run_now(task_db, monkeypatch, s)
    await _heartbeat(s)

    reply = await run_now("bk")
    assert reply == {"ok": True, "dry": False, "message": "Task triggered"}
    # The page carries on: its polls, another heartbeat, one more poll.
    await _page_request(s)
    await _heartbeat(s)
    await _page_request(s, "/api/tasks", "GET")
    await _until(lambda: [r["status"] for r in _runs(task_db, "msg")] == ["error"],
                 "the failure branch has run")

    assert ran == ["bk", "msg"]
    (head,) = _runs(task_db, "bk")
    (branch,) = _runs(task_db, "msg")
    assert head["status"] == "error" and NO_MODEL in head["error"]
    assert head["steps"][-1]["detail"] == "Failed, so continued to Message me"
    assert branch["status"] == "error"
    assert branch["steps"][0]["kind"] == "trigger"
    assert branch["steps"][0]["detail"].startswith("Continued from Nightly backup")
    assert not s._executing


@pytest.mark.asyncio
async def test_while_a_chat_reply_is_written_run_now_says_it_is_waiting_then_runs(
        task_db, gate, monkeypatch):
    """The other half of the `Verify:` — and the gate's purpose kept: a run a
    person started does not take the model from the reply being written. It
    says so in its row, the page's requests and heartbeats do not stop it, and
    it runs — with its failure branch — when the reply is done."""
    _seed(task_db)
    ran = []
    s = _scheduler(ran)
    run_now = _route_run_now(task_db, monkeypatch, s)
    gate["busy"] = True

    await run_now("bk")
    await _until(lambda: _runs(task_db, "bk") and _runs(task_db, "bk")[0]["result"]
                 == "Queued — waiting for the chat reply in progress to finish…",
                 "the row says what it waits for")
    await _settled_in_the_wait()
    await _page_request(s)
    await _heartbeat(s)
    await _turns(50)
    assert ran == []
    assert _runs(task_db, "bk")[0]["status"] == "queued", "the page stopped a run a person started"

    gate["busy"] = False
    async with ig.track_interactive_request("/api/chat/stream_status", "GET"):
        pass
    await _until(lambda: [r["status"] for r in _runs(task_db, "msg")] == ["error"],
                 "both ran after the reply")
    assert ran == ["bk", "msg"]


@pytest.mark.asyncio
async def test_a_run_a_person_started_is_not_interrupted_while_they_use_pantheon(
        task_db, gate, monkeypatch):
    """The running half. Background work has a monitor that stops it within a
    quarter second of anyone using Pantheon; a run a person started must not,
    or every Run now longer than that is "Paused because Pantheon became active"
    by the page it was pressed on. The monitor polls on the wall clock (0.1 s,
    then every 0.25 s), so this one waits 0.6 s; it can only fail when the run
    is wrongly stopped."""
    _seed(task_db, wire_failure=False)
    ran = []
    release = asyncio.Event()
    s = _scheduler(ran, block=release)
    run_now = _route_run_now(task_db, monkeypatch, s)

    await run_now("bk")
    await _until(lambda: ran == ["bk"], "the run starts")
    await _heartbeat(s)
    await _page_request(s)
    await asyncio.sleep(0.6)
    assert _runs(task_db, "bk")[0]["status"] == "running", _runs(task_db, "bk")

    release.set()
    await _until(lambda: [r["status"] for r in _runs(task_db, "bk")] == ["success"],
                 "the run finishes")


@pytest.mark.asyncio
async def test_run_now_of_a_prompt_task_reaches_the_model_with_the_page_open(
        task_db, gate, monkeypatch):
    """The second wait. `_run_agent_loop` waited for Pantheon to be idle before
    every model call, whoever started the run, so a person's Prompt task that
    got past the first wait sat at the second one while their tab was open. The
    executor here hands straight to the real `_run_agent_loop`."""
    import src.agent_loop as agent_loop
    import src.task_endpoint as task_endpoint

    _seed(task_db, wire_failure=False)
    asked = []

    async def _stream(**kwargs):
        asked.append(kwargs.get("model"))
        yield 'data: {"delta": "Backed up 3 files."}'
        yield "data: [DONE]"

    monkeypatch.setattr(agent_loop, "stream_agent_loop", _stream)
    monkeypatch.setattr(task_endpoint, "resolve_task_candidates", lambda **k: [])
    s = TaskScheduler(None)

    async def _llm(task, db, run_id=None):
        return await s._run_agent_loop("http://model.invalid", "m", task, "sess",
                                       run_id=run_id)
    s._execute_llm_task = _llm
    s._log_to_assistant = lambda *a, **k: None

    async def _deliver(*a, **k):
        return None
    s._deliver_task_result = _deliver
    run_now = _route_run_now(task_db, monkeypatch, s)
    await _heartbeat(s)

    await run_now("bk")
    await _until(lambda: [r["status"] for r in _runs(task_db, "bk")] == ["success"],
                 "the run reached the model and finished")
    assert asked == ["m"]
    assert _runs(task_db, "bk")[0]["result"] == "Backed up 3 files."


@pytest.mark.asyncio
async def test_a_background_runs_model_call_still_waits_for_pantheon_to_be_idle(
        task_db, gate, monkeypatch):
    """`Law 1`. The second wait is unchanged for background work: a run nobody
    pressed does not reach the model while the tab is open, and does once it
    closes."""
    import src.agent_loop as agent_loop
    import src.task_endpoint as task_endpoint

    _seed(task_db, wire_failure=False)
    asked = []

    async def _stream(**kwargs):
        asked.append(kwargs.get("model"))
        yield 'data: {"delta": "ok"}'

    monkeypatch.setattr(agent_loop, "stream_agent_loop", _stream)
    monkeypatch.setattr(task_endpoint, "resolve_task_candidates", lambda **k: [])
    s = TaskScheduler(None)

    async def _llm(task, db, run_id=None):
        return await s._run_agent_loop("http://model.invalid", "m", task, "sess",
                                       run_id=run_id)
    s._execute_llm_task = _llm
    s._log_to_assistant = lambda *a, **k: None
    await ig.mark_browser_activity()

    # Past the first wait on purpose (as a test driving the executor does), to
    # see the second one on its own.
    db = task_db()
    try:
        db.add(TaskRun(id="r1", task_id="bk", status="queued"))
        db.commit()
    finally:
        db.close()
    run = asyncio.create_task(s._execute_task_locked(
        "bk", "r1", gate_foreground=False, release_executing=False))
    await _turns(100)
    assert asked == [], "a background run reached the model with the tab open"

    await _tab_closes()
    await _until(lambda: asked == ["m"], "the model call after the tab closed")
    await run


@pytest.mark.asyncio
async def test_who_started_a_run_is_one_of_two_words(task_db, gate):
    """`Law 10`. A third word would be read as background by every reader."""
    _seed(task_db)
    with pytest.raises(ValueError):
        await _scheduler([]).run_task_now("bk", started_by="me")
    assert ig.STARTED_BY == ("background", "person")
