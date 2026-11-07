# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1896` — a restart keeps a webhook's queued run, and a workflow's place.

The audit (`restart-loses-queued-webhook-and-aborts-running`): the start-up
sweep aborted every run the last process left queued or running. A webhook's
run still queued — waiting for Pantheon to be idle — lost its body for good
(the webhook had answered 202; nothing sends it again). A workflow run on its
third step lost the rest of the run, though its finished steps were on disk
and a takeover already parks such a run to go on from its step.

Now:
  (1) a queued run handed a webhook's or an event's trigger, of any kind of
      task, keeps that trigger on its row while it waits, and the next process
      runs it — the same run, with that trigger — instead of aborting it;
  (2) a workflow run that was on a step is parked on it, `waiting {kind:
      idle, restarted: true}`, its finished steps kept, and the sweeper's
      existing resume goes on from that step once Pantheon is idle.
Neither for a run older than `RESTART_RESUME_MAX_AGE`, nor for a task switched
off meanwhile, and the task's claim is held while it runs, so the due loop
cannot start it twice.

Driven (`Law 20`): the real scheduler puts the runs in those states on a real
SQLite file — waiting for idle behind the real gate, mid-step — and a second
scheduler over the file as the first left it runs what `start` runs (its
sweep, its dispatch) and its real due tick. A dead process writes nothing as
it dies, so the next one reads a copy of the file taken at the moment it
stopped (`_the_old_process_dies`).
"""

import asyncio
import json
import sqlite3
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
import src.task_scheduler as ts
from core.database import ScheduledTask, TaskRun, TaskRunNode
from src import workflow_runs as wr
from src.event_bus import (
    TRIGGER_SOURCE_EVENT, TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger,
)
from src.task_scheduler import TaskScheduler, _utcnow
from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, row, runs_of, seed_workflow, settle,
)
from tests.test_a_workflow_with_no_model_runs_while_pantheon_is_open import (  # noqa: F401
    IDLE_WAIT, _someone_is_here, _tab_closes, _until, gate,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "restart.db")


async def _the_old_process_dies(monkeypatch, tmp_path, factory):
    """The old process stops where it stands, and the next one finds the file
    as it was at that moment. The file is copied first; then the old
    process's tasks are cancelled — what they write as they unwind lands on
    the old file, since a dead process writes nothing — and the copy is what
    `SessionLocal` opens from now on. Answers the copy's session factory."""
    path = factory.kw["bind"].url.database
    copy = tmp_path / "after-the-restart.db"
    src, dst = sqlite3.connect(path), sqlite3.connect(str(copy))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    left = [t for t in asyncio.all_tasks()
            if t is not asyncio.current_task() and "_execute_task" in repr(t.get_coro())]
    for t in left:
        t.cancel()
    await asyncio.gather(*left, return_exceptions=True)
    after = sessionmaker(bind=create_engine(f"sqlite:///{copy}",
                                            connect_args={"check_same_thread": False},
                                            poolclass=NullPool),
                         autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", after)
    return after


async def _the_next_process_starts():
    """What `start` does about runs the last process left: its sweep, then
    its dispatch of what the sweep left queued."""
    s = recording_scheduler(scheduler=TaskScheduler(None))
    s._sweep_runs_left_by_a_restart()
    await s._dispatch_runs_queued_before_a_restart()
    return s


def _kept_trigger(factory, run_id):
    db = factory()
    try:
        return db.query(TaskRun.trigger_envelope).filter(TaskRun.id == run_id).first()[0]
    finally:
        db.close()


def _a_task(factory, task_id="hook", *, trigger_type="webhook", status="active", **kw):
    db = factory()
    try:
        kw.setdefault("task_type", "action")
        kw.setdefault("action", "tidy_sessions")
        db.add(ScheduledTask(id=task_id, owner="alice", name="Tidy", trigger_type=trigger_type,
                             status=status, **kw))
        db.commit()
    finally:
        db.close()


def _a_queued_run_left(factory, run_id, task_id, trigger, *, age=timedelta(0)):
    """A `queued` row as a dead process left it, its trigger kept."""
    db = factory()
    try:
        db.add(TaskRun(id=run_id, task_id=task_id, status="queued", result=IDLE_WAIT,
                       started_at=_utcnow() - age,
                       trigger_envelope=json.dumps(trigger) if trigger else None))
        db.commit()
    finally:
        db.close()


# ── (1) A webhook's queued run runs after the restart ────────────────────────

async def test_a_webhooks_queued_run_runs_after_a_restart_with_its_body(
        factory, gate, monkeypatch, tmp_path):
    _a_task(factory)
    body = build_trigger(TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": "the server is down"},
                         fields=WEBHOOK_PAYLOAD_FIELDS)
    first = recording_scheduler()
    await _someone_is_here()
    assert await first.run_task_now("hook", trigger=body, run_id="r1") is True
    await _until(lambda: [r["result"] for r in runs_of(factory, "hook")] == [IDLE_WAIT],
                 "the run waits for Pantheon to be idle")
    assert json.loads(_kept_trigger(factory, "r1"))["source"] == "webhook", \
        "kept on its row while it is queued"
    factory = await _the_old_process_dies(monkeypatch, tmp_path, factory)

    second = await _the_next_process_starts()
    assert "hook" in second._executing, "its claim is held, so the due loop cannot start it too"
    await _until(lambda: [r["result"] for r in runs_of(factory, "hook")] == [IDLE_WAIT],
                 "the same run waits its turn again")
    [waiting] = runs_of(factory, "hook")
    assert (waiting["id"], waiting["status"]) == ("r1", "queued")
    await _tab_closes()
    await settle(second)

    [run] = runs_of(factory, "hook")
    assert (run["id"], run["status"]) == ("r1", "success"), run
    assert first.calls == [], "the old process ran nothing"
    [call] = second.calls
    assert call["trigger"]["source"] == "webhook"
    assert "the server is down" in json.dumps(call["trigger"]), "with the body it was sent"
    kinds = [(st.get("kind"), st.get("detail")) for st in run["steps"]]
    cause = next(i for i, (k, _d) in enumerate(kinds) if k == "trigger")
    assert kinds[cause + 1] == ("progress", ts.REQUEUED_AFTER_RESTART_STEP), kinds
    assert _kept_trigger(factory, "r1") is None, "let go of once it ran"


async def test_an_events_queued_run_of_a_prompt_task_runs_too(factory):
    _a_task(factory, "ev", trigger_type="event", task_type="llm", prompt="Sum it up",
            action=None, trigger_event="email_received")
    event = build_trigger(TRIGGER_SOURCE_EVENT, "email_received", {"subject": "Invoice 42"})
    _a_queued_run_left(factory, "e1", "ev", event)

    second = await _the_next_process_starts()
    await settle(second)
    [run] = runs_of(factory, "ev")
    assert (run["id"], run["status"]) == ("e1", "success"), run
    [call] = second.calls
    assert call["kind"] == "llm" and "Invoice 42" in json.dumps(call["trigger"])


async def test_the_sweep_says_a_kept_run_is_queued_again(factory):
    _a_task(factory)
    _a_queued_run_left(factory, "r1", "hook",
                       build_trigger(TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": "x"}))
    TaskScheduler(None)._sweep_runs_left_by_a_restart()
    [run] = runs_of(factory, "hook")
    assert (run["status"], run["result"], run["error"]) == (
        "queued", ts.REQUEUED_AFTER_RESTART, None)
    assert ts.REQUEUED_AFTER_RESTART == ("Queued again: Pantheon restarted before this run "
                                         "started, and it runs with what started it.")


@pytest.mark.parametrize("why,setup", [
    ("older than a day", dict(age=timedelta(hours=25))),
    ("its task was switched off", dict(status="paused")),
    ("a schedule's run: no trigger kept", dict(trigger=None)),
    ("a chained run's trigger", dict(trigger={"source": "task", "name": "Earlier"})),
])
async def test_a_queued_run_it_may_not_keep_is_ended_as_before(factory, why, setup):
    _a_task(factory, status=setup.get("status", "active"))
    trigger = setup.get("trigger", build_trigger(TRIGGER_SOURCE_WEBHOOK, "webhook", {"b": 1}))
    _a_queued_run_left(factory, "r1", "hook", trigger, age=setup.get("age", timedelta(0)))
    second = await _the_next_process_starts()
    [run] = runs_of(factory, "hook")
    assert (run["status"], run["result"]) == (
        "aborted", "Server restarted while task was queued"), why
    assert second._executing == set() and second.calls == [], why


# ── (2) A workflow run goes on from the step it was on ───────────────────────

STEPS = ([node("fetch", "Fetch", "action", action="tidy_sessions"),
          node("brief", "Brief me"),
          node("file", "File it", "action", action="tidy_documents")],
         [arrow("start", "fetch"), arrow("fetch", "brief"), arrow("brief", "file")])


async def _mid_step(factory, *, trigger=None, steps=STEPS, **seed):
    """A workflow run whose second step is still running when the process
    stops."""
    inside = asyncio.Event()

    async def slow(task, run_id):
        inside.set()
        await asyncio.sleep(30)
    seed_workflow(factory, *steps, **seed)
    first = recording_scheduler({"Morning digest · Brief me": slow})
    assert await first.run_task_now("wf", trigger=trigger) is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    return first


async def test_a_workflow_run_mid_step_goes_on_from_that_step(factory, monkeypatch, tmp_path):
    await _mid_step(factory)
    factory = await _the_old_process_dies(monkeypatch, tmp_path, factory)

    second = await _the_next_process_starts()
    [run] = runs_of(factory, "wf")
    assert (run["status"], run["result"], run["error"], run["finished_at"]) == (
        "waiting", ts.RESTART_PARKED, None, None)
    recs = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert recs["fetch"]["status"] == "success", "a finished step is kept"
    assert recs["brief"]["status"] == "waiting" and recs["brief"]["waiting"]["kind"] == "idle"
    db = factory()
    try:
        brief = db.query(TaskRunNode).filter(TaskRunNode.id == recs["brief"]["id"]).first()
        assert wr.waiting_of(brief)["restarted"] is True, "the sweeper's resume reads why"
    finally:
        db.close()
    assert "file" not in recs
    said = [st.get("detail") for st in run["steps"]]
    assert "Stopped because Pantheon restarted; it runs again once Pantheon is idle" in said
    # `B1859`: its next time moved on, so the due tick finds nothing to start.
    assert row(factory, "wf").next_run > _utcnow()

    await second._check_due_tasks()              # the real tick: the sweeper resumes it
    await settle(second)
    runs = runs_of(factory, "wf")
    assert len(runs) == 1, "the same run went on, and no `skipped` run was written"
    run = runs[0]
    assert run["status"] == "success", run
    assert [c["name"] for c in second.calls] == ["Morning digest · Brief me",
                                                 "Morning digest · File it"], \
        "Fetch is not run again"
    recs = records_of(factory, run["id"])
    assert sorted(r["node_id"] for r in recs) == ["brief", "fetch", "file"]
    assert {r["node_id"]: r["attempt"] for r in recs}["brief"] == 2
    said = [st.get("detail") for st in run["steps"]]
    assert "“Brief me” runs again: Pantheon restarted while it ran" in said, said


async def test_a_webhooks_workflow_run_says_its_cause_again_and_reads_its_body(
        factory, monkeypatch, tmp_path):
    """The log the old process held in memory is gone with it; the cause is
    said again from the trigger kept on the row (`B1861`), and the step that
    runs again is handed the webhook's body."""
    body = build_trigger(TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": "the server is down"},
                         fields=WEBHOOK_PAYLOAD_FIELDS)
    nodes, edges = STEPS
    nodes = [nodes[0], node("brief", "Brief me", prompt="Brief me on: {{ steps.start.data.body }}"),
             nodes[2]]
    await _mid_step(factory, trigger=body, steps=(nodes, edges), trigger_type="webhook",
                    schedule=None, scheduled_time=None)
    factory = await _the_old_process_dies(monkeypatch, tmp_path, factory)
    second = await _the_next_process_starts()
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting"
    assert run["steps"][0]["kind"] == "trigger" and "webhook" in run["steps"][0]["detail"].lower()
    assert row(factory, "wf").next_run is None, "a webhook's task has no next time"
    await second._check_due_tasks()
    await settle(second)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    brief = next(c for c in second.calls if c["name"] == "Morning digest · Brief me")
    # The body goes to the model as the untrusted data it is, named in the
    # prompt and carried beside it.
    said = "\n".join(m["content"] for m in brief["slot_state"].get("context_messages") or ())
    assert "the server is down" in said, (brief["prompt"], said)


async def test_a_workflow_run_older_than_a_day_is_ended_as_before(factory, monkeypatch, tmp_path):
    await _mid_step(factory)
    factory = await _the_old_process_dies(monkeypatch, tmp_path, factory)
    monkeypatch.setattr(ts, "RESTART_RESUME_MAX_AGE", timedelta(0))
    await _the_next_process_starts()
    [run] = runs_of(factory, "wf")
    assert (run["status"], run["result"]) == ("aborted", "Server restarted while task was running")
    assert [r["status"] for r in records_of(factory, run["id"])] == ["success", "aborted"]


async def test_a_workflow_run_on_no_step_is_ended_as_before(factory):
    """Nothing running to go on from: it ends, as ever."""
    seed_workflow(factory, *STEPS)
    db = factory()
    try:
        db.add(TaskRun(id="r9", task_id="wf", status="running", started_at=_utcnow()))
        db.commit()
    finally:
        db.close()
    TaskScheduler(None)._sweep_runs_left_by_a_restart()
    assert runs_of(factory, "wf")[0]["status"] == "aborted"


async def test_a_for_each_and_its_item_are_parked_together(factory):
    """A For-each that was running parks with the item it was on, so the
    For-each's own resume goes on with that item on its own record."""
    each = node("each", "Each mail", "foreach", list="{{ steps.start.data.items }}",
                step={"kind": "llm", "label": "Sum", "config": {"prompt": "Sum it"}})
    seed_workflow(factory, [each], [arrow("start", "each")])
    db = factory()
    try:
        db.add(TaskRun(id="r9", task_id="wf", status="running", started_at=_utcnow()))
        db.commit()
        wr.record_node_start(db, run_id="r9", node=each, seq=1, input_envelope=None,
                             workflow_version=3)
        wr.record_node_start(db, run_id="r9", node=each, seq=2, input_envelope=None,
                             workflow_version=3, item=0, label="Sum · item 1 of 2")
    finally:
        db.close()
    TaskScheduler(None)._sweep_runs_left_by_a_restart()
    assert runs_of(factory, "wf")[0]["status"] == "waiting"
    db = factory()
    try:
        recs = db.query(TaskRunNode).filter(TaskRunNode.run_id == "r9").all()
        got = {(r.item, r.status, json.loads(r.waiting)["kind"],
                json.loads(r.waiting).get("restarted")) for r in recs}
        assert got == {(None, "waiting", "idle", True), (0, "waiting", "idle", True)}
    finally:
        db.close()
