# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1540` — an event committed between the finishing run's read and its commit still runs.

`B1512` made the finishing run read the row again (`_queued_event_due`) and keep
a queued event due; it named its own residual: an event committed after that
read and before the run's commit was still overwritten — the ORM wrote
`next_run = None` from the read's answer, so the event's `pending_trigger`
stood with no `next_run` and the loop never ran it. Now the clear is one
conditional `UPDATE … WHERE pending_trigger IS NULL` (`_settle_event_next_run`).

Driven (`Law 20`): the real bus with no scheduler (the email server's process)
and the real `TaskScheduler`'s loop on one SQLite file, as `B1512`'s test is;
the second event is fired at exactly the moment the row has been read and not
yet written — after the real `_queued_event_due` answers *nothing queued*.
"""
from __future__ import annotations

import asyncio

import src.event_bus as bus
from src.task_scheduler import TaskScheduler
from tests.helpers.walker_harness import OWNER, recording_scheduler
from tests.test_an_event_from_another_process_reaches_its_task_with_its_payload import (  # noqa: F401
    _loop_once, _row, world,
)

ONE = {"document_id": "doc-1", "title": "One"}
TWO = {"document_id": "doc-2", "title": "Two"}


def _fire_elsewhere_now(payload):
    """`document_updated` where no scheduler runs, committed before this
    returns: with no scheduler the bus never awaits, so its coroutine runs to
    the end in one step."""
    coro = bus._handle_event("document_updated", OWNER, payload)
    try:
        coro.send(None)
    except StopIteration:
        return
    coro.close()
    raise AssertionError("the bus awaited something; it did not commit in one step")


def _handed(scheduler):
    return [c["trigger"]["data"] if c["trigger"] else None for c in scheduler.calls]


def test_an_event_committed_after_the_read_and_before_the_commit_still_runs(world, monkeypatch):
    monkeypatch.setattr(bus, "_task_scheduler", None)
    _fire_elsewhere_now(ONE)

    real = TaskScheduler._queued_event_due
    landed = []

    def read_then_event_lands(self, db, task):
        due = real(self, db, task)
        if not landed:                           # the first run's finish only
            landed.append(due)
            _fire_elsewhere_now(TWO)
        return due

    monkeypatch.setattr(TaskScheduler, "_queued_event_due", read_then_event_lands)
    s = recording_scheduler()
    asyncio.run(_loop_once(s))
    assert _handed(s) == [ONE]
    assert landed == [None], "the read saw nothing queued: the event landed after it"
    row = _row(world)
    assert row.pending_trigger is not None
    assert row.next_run is not None, "the event committed in the window was overwritten"

    asyncio.run(_loop_once(s))
    assert _handed(s) == [ONE, TWO], "the queued event did not run, or ran without its payload"
    row = _row(world)
    assert row.pending_trigger is None and row.next_run is None


def test_with_nothing_queued_the_finished_run_still_clears_its_time(world, monkeypatch):
    """The other half: no event in the window, and the run that finished
    leaves the task not due — `next_run` cleared, run count moved."""
    monkeypatch.setattr(bus, "_task_scheduler", None)
    _fire_elsewhere_now(ONE)
    s = recording_scheduler()
    asyncio.run(_loop_once(s))
    row = _row(world)
    assert _handed(s) == [ONE]
    assert row.next_run is None and row.pending_trigger is None
    assert row.run_count == 1 and row.last_run is not None
    asyncio.run(_loop_once(s))
    assert _handed(s) == [ONE], "a task nothing triggered ran again"
