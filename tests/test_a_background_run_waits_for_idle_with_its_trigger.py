# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1060` — a background run the foreground gate stopped while it was queued
never came back unless it was a scheduled task, though its row said "Paused".

**Measured 2026-10-01 in Chromium** by `wb-runs` while driving `B1047`: a
webhook-fired task's run waited "Queued — waiting for Pantheon to be idle…"
while the page was open, then ended `aborted · Paused because Pantheon became
active`; `next_run` stayed NULL and no run followed — the webhook's payload was
gone. Re-measured here on the tree before this file, through the real scheduler
and the real gate (the first test below is that measurement, red there).

**Why, read in the source and confirmed by these tests failing on it:** the
idle wait was inside `_execute_task_locked`, i.e. INSIDE the model slot, so a
waiting background run held the slot every other run needed — and the gate
stopped waiting runs for that reason; `_execute_task`'s cancel branch re-queued
only through `_defer_immediately_due_task`, which needs a past `next_run`, so a
webhook's, an event's or a chained run was simply lost; and a RUNNING background
run the gate stopped got `next_run = now + 15 min` for any trigger type, so it
came back a quarter of an hour later as a plain run without its payload.

**The integrator's call, recorded on the row:** a background run waits for idle
*before* it takes the model slot, so the gate need not stop a queued run; it runs
with its trigger once Pantheon is idle and its row says it waited; only a running
background run is stopped, and it is re-queued with its trigger or says it will
not be retried.

Everything is real (`Law 20`): the real `src.interactive_gate`, the real
`TaskScheduler` (`run_task_now` → `_execute_task` → `_execute_task_locked`), the
real event bus's `_handle_event`, a real SQLite file, real asyncio. Only the
model is absent: the executors are recorders that note which task ran with which
trigger. Nothing waits on the wall clock but the monitor test `B1047` already
pays for; the quiet window is 0 and every step is driven by the notifies the
real request tracker sends.
"""

import asyncio
import json
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.event_bus as event_bus  # noqa: E402
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

TAKEOVER = "Paused because Pantheon became active"
WILL_RUN_AGAIN = (f"{TAKEOVER}. It will run again, with what started it, once "
                  f"Pantheon is idle.")


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'idle.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


@pytest.fixture()
def gate(monkeypatch):
    """The real gate, on, from a clean slate. Quiet window 0."""
    monkeypatch.delenv("BACKGROUND_TASK_FOREGROUND_GATE", raising=False)
    monkeypatch.setenv("BACKGROUND_TASK_QUIET_MS", "0")
    monkeypatch.setenv("BACKGROUND_TASK_BROWSER_ACTIVE_SECONDS", "45")
    monkeypatch.setenv("BACKGROUND_TASK_MAX_WAIT_SECONDS", "0")
    for name, value in (("_ACTIVE_REQUESTS", 0), ("_LAST_ACTIVITY", 0.0),
                        ("_LAST_BROWSER_ACTIVITY", 0.0), ("_COND", None),
                        ("_COND_LOOP", None)):
        monkeypatch.setattr(ig, name, value)
    monkeypatch.setattr(ig, "_has_active_chat_stream", lambda: False)


def _seed(factory, *rows):
    db = factory()
    try:
        for row in rows:
            db.add(row)
        db.commit()
    finally:
        db.close()


def _hook(**kw):
    """A webhook-fired Prompt task — the row's own case."""
    fields = dict(id="hook", owner="alice", name="Webhook digest",
                  prompt="Summarise what arrived.", task_type="llm",
                  trigger_type="webhook", status="active", output_target="session")
    fields.update(kw)
    return ScheduledTask(**fields)


def _runs(factory, task_id):
    db = factory()
    try:
        return [{"status": r.status, "error": r.error, "result": r.result,
                 "steps": json.loads(r.steps) if r.steps else []}
                for r in db.query(TaskRun).filter(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at, TaskRun.id).all()]
    finally:
        db.close()


def _task(factory, task_id):
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    finally:
        db.close()


def _scheduler(ran, *, block_first=None):
    """The real scheduler with recording executors. Each records `(task id,
    the trigger its run was handed)`. With `block_first`, a task's FIRST run
    waits on that event (so the gate can find it running); later runs return."""
    s = TaskScheduler(None)
    seen = {}

    async def _record(task, run_id):
        ran.append((task.id, s.run_trigger(run_id)))
        seen[task.id] = seen.get(task.id, 0) + 1
        if block_first is not None and seen[task.id] == 1:
            await block_first.wait()

    async def _llm(task, db, run_id=None):
        await _record(task, run_id)
        return f"{task.name}: done"

    async def _action(task, run_id=None):
        from src.builtin_actions import NodeResult
        await _record(task, run_id)
        return NodeResult("success", payload=f"{task.name}: done")

    s._execute_llm_task = _llm
    s._execute_action = _action
    s._log_to_assistant = lambda *a, **k: None

    async def _deliver(*a, **k):
        return None
    s._deliver_task_result = _deliver
    return s


async def _until(predicate, what, limit=600):
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"never happened: {what}")


async def _turns(n=60):
    for _ in range(n):
        await asyncio.sleep(0)


async def _page_request(scheduler, path="/api/email/accounts", method="GET"):
    """One foreground request, as `_InteractiveActivityMiddleware` makes it."""
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
    ig._LAST_BROWSER_ACTIVITY = 0.0
    async with ig.track_interactive_request("/api/x", "GET"):
        pass


def _webhook(body):
    return event_bus.build_trigger(event_bus.TRIGGER_SOURCE_WEBHOOK, "webhook",
                                   {"body": body},
                                   fields=("body", "json", "query", "headers"))


# ── the row's `Verify:` ─────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["llm", "action"])
async def test_with_pantheon_open_a_webhook_run_waits_runs_with_its_payload_and_says_it_waited(
        task_db, gate, kind):
    """`B1060`'s `Verify:`, word for word: with Pantheon open, a webhook-fired
    task runs once Pantheon is idle, with its payload, and its row says it
    waited. Both doors into the run: a Prompt task (through the model slot) and
    a housekeeping action (no slot)."""
    extra = {} if kind == "llm" else {"task_type": "action", "action": "tidy_sessions"}
    _seed(task_db, _hook(**extra))
    ran = []
    s = _scheduler(ran)
    await _heartbeat(s)
    payload = _webhook("invoice #42 arrived")

    assert await s.run_task_now("hook", trigger=payload) is True
    await _until(lambda: _runs(task_db, "hook")
                 and _runs(task_db, "hook")[0]["result"] == ts.WAITING_FOR_IDLE,
                 "the row says it waits for idle")
    await _turns(10)
    # The page goes on: its polls, a heartbeat, another poll. None stops it.
    await _page_request(s)
    await _heartbeat(s)
    await _page_request(s, "/api/tasks")
    await _turns(100)
    (waiting,) = _runs(task_db, "hook")
    assert waiting["status"] == "queued", "the page stopped a run that was only waiting"
    assert ran == []

    await _tab_closes()
    await _until(lambda: [r["status"] for r in _runs(task_db, "hook")] == ["success"],
                 "it ran once idle")
    assert ran == [("hook", payload)], "it ran without what started it"
    (run,) = _runs(task_db, "hook")
    assert run["steps"][0]["kind"] == "trigger"
    assert "invoice #42 arrived" in run["steps"][0]["detail"]
    assert run["steps"][1]["kind"] == "progress"
    assert run["steps"][1]["detail"].startswith("Waited ")
    assert run["steps"][1]["detail"].endswith("for Pantheon to be idle, then started")
    assert not s._executing


@pytest.mark.asyncio
async def test_a_background_run_waiting_for_idle_holds_no_model_slot(task_db, gate):
    """The reason the gate had to stop waiting runs: the wait was inside the
    model slot. At the default cap of one, a background run waiting for the
    person to stop using Pantheon held the ONE slot — so the person's own
    *Run now* of another Prompt task queued behind it, "waiting for a free
    slot", for as long as they kept the page open."""
    _seed(task_db, _hook(),
          ScheduledTask(id="mine", owner="alice", name="My own task", prompt="Do it.",
                        task_type="llm", trigger_type="webhook", status="active"))
    ran = []
    s = _scheduler(ran)
    assert s._concurrency_cap == 1
    await _heartbeat(s)

    assert await s.run_task_now("hook", trigger=_webhook("x")) is True
    await _until(lambda: _runs(task_db, "hook")
                 and _runs(task_db, "hook")[0]["result"] == ts.WAITING_FOR_IDLE,
                 "the background run waits")
    await _turns(10)

    assert await s.run_task_now("mine", started_by=ts.STARTED_BY_PERSON) is True
    await _until(lambda: [r["status"] for r in _runs(task_db, "mine")] == ["success"],
                 "the person's run went ahead of the waiting one")
    assert [t for t, _ in ran] == ["mine"]
    assert _runs(task_db, "hook")[0]["status"] == "queued"

    await _tab_closes()
    await _until(lambda: [t for t, _ in ran] == ["mine", "hook"], "then the waiting one")


@pytest.mark.asyncio
async def test_a_person_who_arrives_while_it_waits_for_the_slot_gets_the_slot_back(
        task_db, gate):
    """Idle when it started waiting for the slot is not idle when it gets it.
    A run that got past the idle wait and then queued behind another model run
    checks again once it holds the slot; if somebody arrived meanwhile it gives
    the slot back and waits for idle again, holding nothing."""
    _seed(task_db, _hook(),
          ScheduledTask(id="long", owner="alice", name="Long one", prompt="Slowly.",
                        task_type="llm", trigger_type="webhook", status="active"))
    ran = []
    release = asyncio.Event()
    s = _scheduler(ran, block_first=release)

    assert await s.run_task_now("long", started_by=ts.STARTED_BY_PERSON) is True
    await _until(lambda: [t for t, _ in ran] == ["long"], "a person's run holds the slot")
    assert await s.run_task_now("hook", trigger=_webhook("y")) is True
    await _turns(50)          # idle: it is past the idle wait, at the semaphore
    await _heartbeat(s)       # the person arrives while it waits for the slot
    release.set()
    await _until(lambda: [r["status"] for r in _runs(task_db, "long")] == ["success"],
                 "the slot comes free")
    await _turns(100)
    assert [t for t, _ in ran] == ["long"], "it took the slot with somebody using Pantheon"
    assert _runs(task_db, "hook")[0]["status"] == "queued"
    assert s._run_semaphore._value == 1, "it kept the slot while it waited"

    await _tab_closes()
    await _until(lambda: [t for t, _ in ran] == ["long", "hook"], "then it ran")


# ── a RUNNING background run the gate stops ─────────────────────────────────

@pytest.mark.asyncio
async def test_a_running_background_run_the_gate_stops_goes_back_in_the_queue_with_its_trigger(
        task_db, gate):
    """It was `next_run = now + 15 min` for any trigger type, so a webhook's
    task came back a quarter of an hour later as a plain run with no payload.
    Now the stopped row says it will run again, a new run waits for idle, and
    it runs with the same trigger."""
    _seed(task_db, _hook())
    ran = []
    release = asyncio.Event()
    s = _scheduler(ran, block_first=release)
    payload = _webhook("the body that started it")
    cancels = []
    recording = s._execute_llm_task

    async def _llm(task, db, run_id=None):
        cancels.append(asyncio.current_task().cancelling())
        return await recording(task, db, run_id=run_id)
    s._execute_llm_task = _llm

    assert await s.run_task_now("hook", trigger=payload) is True
    await _until(lambda: len(ran) == 1, "it is running")
    await _heartbeat(s)
    await _until(lambda: len(_runs(task_db, "hook")) == 2, "it goes back in the queue")
    await _turns(20)

    stopped, again = _runs(task_db, "hook")
    assert stopped["status"] == "aborted"
    assert stopped["error"] == TAKEOVER
    assert stopped["result"] == WILL_RUN_AGAIN
    assert again["status"] == "queued" and again["result"] == ts.WAITING_FOR_IDLE
    assert "hook" in s._executing, "the claim was let go between the two runs"
    assert _task(task_db, "hook").next_run is None

    release.set()
    await _tab_closes()
    await _until(lambda: [r["status"] for r in _runs(task_db, "hook")] == ["aborted", "success"],
                 "it ran again once idle")
    assert ran == [("hook", payload), ("hook", payload)]
    assert "the body that started it" in _runs(task_db, "hook")[1]["steps"][0]["detail"]
    assert not s._executing and "hook" not in s._task_handles
    # The cancel the first attempt answered is not still owed by the second:
    # asyncio's own `timeout`/`TaskGroup` read this count.
    assert cancels == [0, 0], cancels


@pytest.mark.asyncio
async def test_a_scheduled_run_the_gate_stops_runs_again_when_idle_not_in_fifteen_minutes(
        task_db, gate):
    """The timing change the integrator's call names: a scheduled run the gate
    stopped happens when Pantheon goes idle, not fifteen minutes later — and its
    schedule is untouched until the run it describes has happened."""
    _seed(task_db, ScheduledTask(
        id="bk", owner="alice", name="Nightly backup", prompt="Back up.",
        task_type="llm", trigger_type="schedule", schedule="daily",
        scheduled_time="02:00", status="active"))
    ran = []
    release = asyncio.Event()
    s = _scheduler(ran, block_first=release)
    before = _task(task_db, "bk").next_run

    assert await s.run_task_now("bk") is True
    await _until(lambda: len(ran) == 1, "it is running")
    await _heartbeat(s)
    await _until(lambda: len(_runs(task_db, "bk")) == 2, "back in the queue")
    assert _task(task_db, "bk").next_run == before

    release.set()
    await _tab_closes()
    await _until(lambda: [r["status"] for r in _runs(task_db, "bk")] == ["aborted", "success"],
                 "it ran once idle")
    after = _task(task_db, "bk").next_run
    assert after is not None and after > ts._utcnow()
    assert after.hour == 2 and after.minute == 0, after


@pytest.mark.asyncio
async def test_a_run_switched_off_while_it_ran_is_not_retried_and_says_so(task_db, gate):
    _seed(task_db, _hook())
    ran = []
    s = _scheduler(ran, block_first=asyncio.Event())

    assert await s.run_task_now("hook", trigger=_webhook("z")) is True
    await _until(lambda: len(ran) == 1, "it is running")
    db = task_db()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == "hook").first().status = "paused"
        db.commit()
    finally:
        db.close()
    await _heartbeat(s)
    await _until(lambda: "hook" not in s._executing, "the claim is let go")
    await _turns(50)

    (run,) = _runs(task_db, "hook")
    assert run["status"] == "aborted" and run["error"] == TAKEOVER
    assert run["result"] == f"{TAKEOVER}. It will not be retried: it is paused."
    assert len(ran) == 1


@pytest.mark.asyncio
async def test_a_run_stopped_three_times_in_a_row_is_let_go_and_says_so(task_db, gate):
    """`FOREGROUND_STOPS_LIMIT`. A run longer than the person's idle spells
    would otherwise start again from the beginning every time they look away."""
    _seed(task_db, _hook())
    ran = []
    s = _scheduler(ran)

    gate_open = asyncio.Event()

    async def _long(task, db, run_id=None):
        ran.append((task.id, s.run_trigger(run_id)))
        await gate_open.wait()
        return "done"
    s._execute_llm_task = _long

    assert await s.run_task_now("hook", trigger=_webhook("w")) is True
    for n in range(1, ts.FOREGROUND_STOPS_LIMIT + 1):
        await _until(lambda: len(ran) == n, f"attempt {n} is running")
        await _heartbeat(s)
        await _until(lambda: _runs(task_db, "hook")[n - 1]["status"] == "aborted",
                     f"attempt {n} is stopped")
        await _tab_closes()
    await _until(lambda: "hook" not in s._executing, "it is let go")
    await _turns(100)

    rows = _runs(task_db, "hook")
    assert [r["status"] for r in rows] == ["aborted"] * ts.FOREGROUND_STOPS_LIMIT
    assert [r["result"] for r in rows[:-1]] == [WILL_RUN_AGAIN] * (ts.FOREGROUND_STOPS_LIMIT - 1)
    assert rows[-1]["result"] == (
        f"{TAKEOVER}. It will not be retried: it was stopped "
        f"{ts.FOREGROUND_STOPS_LIMIT} times in a row because Pantheon became active.")
    assert len(ran) == ts.FOREGROUND_STOPS_LIMIT


@pytest.mark.asyncio
async def test_the_stop_button_on_a_run_back_in_the_queue_still_says_stopped_by_user(
        task_db, gate):
    """`Law 1`. The person's own stop ends it, in their words, and nothing
    runs afterwards."""
    _seed(task_db, _hook())
    ran = []
    s = _scheduler(ran, block_first=asyncio.Event())

    assert await s.run_task_now("hook", trigger=_webhook("v")) is True
    await _until(lambda: len(ran) == 1, "it is running")
    await _heartbeat(s)
    await _until(lambda: len(_runs(task_db, "hook")) == 2, "back in the queue")
    await _turns(20)

    assert await s.stop_task("hook") is True
    await _until(lambda: "hook" not in s._executing, "the claim is let go")
    await _tab_closes()
    await _turns(200)

    stopped, by_person = _runs(task_db, "hook")
    assert stopped["result"] == WILL_RUN_AGAIN
    assert by_person["status"] == "aborted"
    assert by_person["error"] == by_person["result"] == "Stopped by user"
    assert len(ran) == 1


@pytest.mark.asyncio
async def test_a_stop_pressed_while_the_stopped_attempt_winds_down_is_not_lost(
        task_db, gate):
    """The narrow window: the gate's stop has been answered and the row says it
    will run again, and the person presses Stop while that attempt is still
    winding down (its foreground monitor is being torn down, an `await` that
    absorbs a cancel). Their stop must win: nothing runs again, and the row that
    promised another attempt says they stopped it."""
    _seed(task_db, _hook())
    ran = []
    s = _scheduler(ran, block_first=asyncio.Event())
    told = []
    real_notify = s._notify_run_outcome

    def _notify(task, status, **kw):
        # The last thing the stopped attempt does before it answers REQUEUED.
        if status == "aborted" and not told:
            told.append(asyncio.ensure_future(s.stop_task("hook")))
        return real_notify(task, status, **kw)
    s._notify_run_outcome = _notify

    assert await s.run_task_now("hook", trigger=_webhook("u")) is True
    await _until(lambda: len(ran) == 1, "it is running")
    await _heartbeat(s)
    await _until(lambda: "hook" not in s._executing and told and told[0].done(),
                 "the stop is answered and the claim let go")
    await _tab_closes()
    await _turns(300)

    assert len(ran) == 1, "it ran again after the person stopped it"
    rows = _runs(task_db, "hook")
    assert [r["status"] for r in rows if r["status"] != "aborted"] == []
    assert rows[-1]["result"] == "Stopped by user"
    assert "hook" not in s._task_handles


@pytest.mark.asyncio
async def test_an_event_fired_while_pantheon_is_open_runs_with_its_payload(
        task_db, gate, monkeypatch):
    """The row's consequence: an event-triggered task — fired by the person's
    own action, while they use Pantheon — practically never ran with what fired
    it. Through the real event bus: the run waits, is not stopped by the page,
    and is handed the document the event named."""
    _seed(task_db, ScheduledTask(
        id="ev", owner="alice", name="On document", prompt="Summarise the document.",
        task_type="llm", trigger_type="event", trigger_event="document_updated",
        trigger_count=1, status="active"))
    ran = []
    s = _scheduler(ran)
    monkeypatch.setattr(event_bus, "_task_scheduler", s)
    await _heartbeat(s)

    await event_bus._handle_event("document_updated", "alice",
                                  {"document_id": "d-7", "title": "Quarterly plan"})
    await _until(lambda: _runs(task_db, "ev")
                 and _runs(task_db, "ev")[0]["result"] == ts.WAITING_FOR_IDLE,
                 "the event's run waits")
    await _page_request(s, "/api/documents/d-7", "PUT")
    await _turns(100)
    assert _runs(task_db, "ev")[0]["status"] == "queued"

    await _tab_closes()
    await _until(lambda: [r["status"] for r in _runs(task_db, "ev")] == ["success"],
                 "it ran once idle")
    ((task_id, trigger),) = ran
    assert task_id == "ev"
    assert trigger["event"] == "document_updated"
    assert trigger["data"] == {"document_id": "d-7", "title": "Quarterly plan"}
