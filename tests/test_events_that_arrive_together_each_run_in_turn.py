# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1865` — events that arrive while their task is busy each run, in the
order they came, with their own payload.

`ScheduledTask.pending_trigger` held ONE envelope and every event wrote over
it, so three documents created while a run went left the third waiting and the
second gone: the run after was handed the third, and the second never ran.
And `_handle_event` logged "triggered task" for every event and threw
`run_task_now`'s `False` away. Now the row holds a queue, oldest first, one
event to a run (`event_bus.pending_triggers_of`, `change_pending_triggers`);
the task stays due while it holds anything; past `PENDING_TRIGGERS_MAX` an
event is a `skipped` run that says so; a row written before is a queue of one;
and the log says what each event did.

Driven (`Law 20`): the real bus in this process and in one with no scheduler
(the email server's), the real `TaskScheduler`'s loop and walker on one SQLite
file; only the model is a recorder (`walker_harness.recording_scheduler`).
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

import src.event_bus as bus
from core.database import ScheduledTask
from src.event_bus import (
    PENDING_TRIGGERS_MAX, TRIGGER_SOURCE_EVENT, build_trigger, change_pending_triggers,
    pending_triggers_of, pending_triggers_text,
)
from tests.helpers.walker_harness import (
    OWNER, arrow, make_db, node, records_of, recording_scheduler, row, runs_of,
    seed_workflow, settle,
)
from tests.test_an_event_from_another_process_reaches_its_task_with_its_payload import (  # noqa: F401
    _loop_once, _row, world,
)

ONE = {"document_id": "doc-1", "title": "One"}
TWO = {"document_id": "doc-2", "title": "Two"}
THREE = {"document_id": "doc-3", "title": "Three"}


def _fire_elsewhere(payload, event="document_updated"):
    """An event where no scheduler runs: the email server's process."""
    return bus._handle_event(event, OWNER, payload)


def _handed(scheduler):
    return [c["trigger"]["data"] if c["trigger"] else None for c in scheduler.calls]


# ── a task that is not a workflow ──────────────────────────────────────────

def test_three_events_queued_elsewhere_each_run_in_the_order_they_came(world, monkeypatch):
    monkeypatch.setattr(bus, "_task_scheduler", None)
    for payload in (ONE, TWO, THREE):
        asyncio.run(_fire_elsewhere(payload))
    assert [e["data"] for e in pending_triggers_of(_row(world).pending_trigger)] == [ONE, TWO, THREE]

    s = recording_scheduler()
    for _ in range(3):
        asyncio.run(_loop_once(s))
    assert _handed(s) == [ONE, TWO, THREE], "an event written over by the next one never ran"
    assert _row(world).pending_trigger is None and _row(world).next_run is None

    asyncio.run(_loop_once(s))
    assert len(s.calls) == 3, "nothing is left to run"


def test_a_run_handed_its_own_event_takes_the_older_one_first(world, monkeypatch):
    """An event queued where no scheduler runs is still waiting for the loop
    when a second one fires here, where the bus starts the task at once: the
    run takes the older event, and the newer keeps its place for the next."""
    monkeypatch.setattr(bus, "_task_scheduler", None)
    asyncio.run(_fire_elsewhere(ONE))
    s = recording_scheduler()
    monkeypatch.setattr(bus, "_task_scheduler", s)

    async def here_then_settle():
        await bus._handle_event("document_updated", OWNER, TWO)
        await settle(s)
    asyncio.run(here_then_settle())
    assert _handed(s) == [ONE]
    assert [e["data"] for e in pending_triggers_of(_row(world).pending_trigger)] == [TWO]
    assert _row(world).next_run is not None, "still due, for the event that waits"

    asyncio.run(_loop_once(s))
    assert _handed(s) == [ONE, TWO]
    assert _row(world).pending_trigger is None and _row(world).next_run is None


def test_a_row_written_before_is_a_queue_of_one(world, monkeypatch):
    """`B1075` wrote one envelope, alone. Read as a queue of one, it runs
    first, and an event after it runs after it."""
    db = world()
    task = db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first()
    task.pending_trigger = json.dumps(build_trigger(TRIGGER_SOURCE_EVENT, "document_updated", ONE))
    db.commit()
    db.close()

    monkeypatch.setattr(bus, "_task_scheduler", None)
    asyncio.run(_fire_elsewhere(TWO))
    s = recording_scheduler()
    asyncio.run(_loop_once(s))
    asyncio.run(_loop_once(s))
    assert _handed(s) == [ONE, TWO]


def test_past_the_cap_an_event_is_a_skipped_run_that_says_so(world, monkeypatch):
    monkeypatch.setattr(bus, "_task_scheduler", None)
    for n in range(PENDING_TRIGGERS_MAX + 1):
        asyncio.run(_fire_elsewhere({"document_id": f"doc-{n}"}))
    queue = pending_triggers_of(_row(world).pending_trigger)
    assert len(queue) == PENDING_TRIGGERS_MAX == 20
    assert queue[0]["data"] == {"document_id": "doc-0"}, "the oldest waits first"
    [skipped] = runs_of(world, "t1")
    assert skipped["status"] == "skipped"
    assert skipped["result"] == "Did not start: 20 events were already waiting for this task."
    assert skipped["error"] == skipped["result"]

    s = recording_scheduler()
    asyncio.run(_loop_once(s))
    assert _handed(s) == [{"document_id": "doc-0"}]


# ── a workflow ─────────────────────────────────────────────────────────────

@pytest.fixture()
def factory(monkeypatch, tmp_path):
    import src.task_scheduler as ts
    monkeypatch.setattr(ts, "dispatch_hold", lambda *a, **k: 0.0)   # no `P15-10` jitter here
    return make_db(monkeypatch, tmp_path / "burst.db")


def _event_workflow(factory):
    seed_workflow(factory, [
        node("which", "Which doc", "set",
             fields=[{"name": "title", "value": "{{ steps.start.data.title }}"}]),
        node("hold", "Hold", "action", action="tidy_documents"),
    ], [arrow("start", "which"), arrow("which", "hold")],
        trigger_type="event", trigger_event="document_created", trigger_count=1,
        schedule=None, scheduled_time=None)


def _held_first():
    inside, release = asyncio.Event(), asyncio.Event()
    first = {"yes": True}

    async def hold(task, run_id):
        if first.pop("yes", False):
            inside.set()
            await asyncio.wait_for(release.wait(), timeout=5)
        return "held"
    return inside, release, hold


def _titles(factory):
    out = []
    for run in runs_of(factory, "wf"):
        by = {r["node_id"]: r for r in records_of(factory, run["id"])}
        out.append((run["status"], (by["which"]["output"] or {}).get("data", {}).get("title")))
    return out


@pytest.mark.asyncio
async def test_documents_created_while_a_workflow_runs_each_run_after_it_in_turn(
        factory, monkeypatch):
    """The audit's burst: three documents, the second and third while the
    first one's run is going."""
    _event_workflow(factory)
    inside, release, hold = _held_first()
    s = recording_scheduler({"Morning digest · Hold": hold})
    monkeypatch.setattr(bus, "_task_scheduler", s)
    await bus._handle_event("document_created", OWNER, {"title": "burst doc 1"})
    await asyncio.wait_for(inside.wait(), timeout=5)
    await bus._handle_event("document_created", OWNER, {"title": "burst doc 2"})
    await bus._handle_event("document_created", OWNER, {"title": "burst doc 3"})
    release.set()
    await settle(s)
    assert row(factory, "wf").next_run is not None, "still due for the two that wait"
    for _ in range(3):
        await s._check_due_tasks()
        await settle(s)
    assert _titles(factory) == [("success", "burst doc 1"), ("success", "burst doc 2"),
                                ("success", "burst doc 3")]
    assert row(factory, "wf").pending_trigger is None and row(factory, "wf").next_run is None


@pytest.mark.asyncio
async def test_a_workflow_past_the_cap_says_workflow(factory, monkeypatch):
    _event_workflow(factory)
    monkeypatch.setattr(bus, "_task_scheduler", None)
    for n in range(PENDING_TRIGGERS_MAX + 1):
        await _fire_elsewhere({"title": f"doc {n}"}, event="document_created")
    [skipped] = runs_of(factory, "wf")
    assert (skipped["status"], skipped["result"]) == (
        "skipped", "Did not start: 20 events were already waiting for this workflow.")


# ── the log says what each event did ───────────────────────────────────────

@pytest.mark.asyncio
async def test_the_log_says_which_event_started_and_which_waits(factory, monkeypatch, caplog):
    _event_workflow(factory)
    inside, release, hold = _held_first()
    s = recording_scheduler({"Morning digest · Hold": hold})
    monkeypatch.setattr(bus, "_task_scheduler", s)
    caplog.set_level(logging.INFO, logger=bus.logger.name)
    await bus._handle_event("document_created", OWNER, {"title": "first"})
    await asyncio.wait_for(inside.wait(), timeout=5)
    await bus._handle_event("document_created", OWNER, {"title": "second"})
    release.set()
    await settle(s)
    lines = [r.getMessage() for r in caplog.records if r.name == bus.logger.name]
    assert "Event 'document_created' started task 'Morning digest' (every 1)" in lines
    assert ("Event 'document_created' did not start task 'Morning digest' yet: a run of it "
            "is going, and the event waits its turn") in lines
    assert not any("triggered task" in line for line in lines)


@pytest.mark.asyncio
async def test_the_log_says_when_a_parked_run_answered_the_event(factory, monkeypatch, caplog):
    seed_workflow(factory, [node("w", "Wait an hour", "wait", mode="for", minutes=60)],
                  trigger_type="event", trigger_event="document_created", trigger_count=1,
                  schedule=None, scheduled_time=None)
    s = recording_scheduler()
    await s._execute_task("wf")
    assert [r["status"] for r in runs_of(factory, "wf")] == ["waiting"]
    monkeypatch.setattr(bus, "_task_scheduler", s)
    caplog.set_level(logging.INFO, logger=bus.logger.name)
    await bus._handle_event("document_created", OWNER, {"title": "while it waits"})
    runs = runs_of(factory, "wf")
    assert [r["status"] for r in runs] == ["waiting", "skipped"]
    lines = [r.getMessage() for r in caplog.records if r.name == bus.logger.name]
    said = [line for line in lines if "a skipped run says" in line]
    assert said and said[0].endswith(runs[1]["result"]), lines
    assert row(factory, "wf").pending_trigger is None, "the skip answered its event"


# ── the queue itself ───────────────────────────────────────────────────────

def test_the_queue_reads_both_shapes_and_writes_one_event_as_before():
    one = build_trigger(TRIGGER_SOURCE_EVENT, "document_updated", ONE)
    two = build_trigger(TRIGGER_SOURCE_EVENT, "document_updated", TWO)
    assert pending_triggers_of(None) == [] and pending_triggers_of("") == []
    assert pending_triggers_of("not json") == []
    assert pending_triggers_of(json.dumps(one)) == [one]
    assert pending_triggers_of(json.dumps([one, two])) == [one, two]
    assert pending_triggers_text([]) is None
    assert pending_triggers_text([one]) == json.dumps(one, default=str), "the bytes B1075 wrote"
    assert json.loads(pending_triggers_text([one, two])) == [one, two]


def test_an_event_appended_between_a_read_and_a_write_is_not_lost(world):
    """The bus appends in one process while a scheduler takes in another:
    the take is a compare-and-set, so an append that lands between its read
    and its write is read again, not written over."""
    one = build_trigger(TRIGGER_SOURCE_EVENT, "document_updated", ONE)
    two = build_trigger(TRIGGER_SOURCE_EVENT, "document_updated", TWO)
    db = world()
    change_pending_triggers(db, "t1", lambda q: ([*q, one], True))
    db.commit()
    db.close()

    asked = []

    def take_oldest(queue):
        asked.append([e["data"] for e in queue])
        if len(asked) == 1:                      # another process appends, now
            other = world()
            change_pending_triggers(other, "t1", lambda q: ([*q, two], True))
            other.commit()
            other.close()
        return queue[1:], queue[0]

    db = world()
    taken = change_pending_triggers(db, "t1", take_oldest)
    db.commit()
    db.close()
    assert taken["data"] == ONE
    assert asked == [[ONE], [ONE, TWO]], "the write saw the column change and read it again"
    assert [e["data"] for e in pending_triggers_of(_row(world).pending_trigger)] == [TWO]
