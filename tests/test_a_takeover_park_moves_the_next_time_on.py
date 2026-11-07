# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1859` — a scheduled workflow parked by a foreground takeover moves its
next time on, as a run parked on a Wait or a person's yes does.

The takeover park branch of `_execute_task_locked`'s cancel handler wrote the
run `waiting` and committed, and left the task's `next_run` where the due tick
found it — in the past. The very next tick dispatched the task again, and
`B674` turned that dispatch into a `skipped` run ("Did not start: … waiting for
Pantheon to be idle") for an 08:00 that had already run. The `TaskWaiting`
park calls `_set_next_run_after` before its commit; the takeover park now does
too. Driven through the real gate (`stop_background_tasks_for_foreground`),
the real due tick (`_check_due_tasks`) and the real sweeper.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from src.task_scheduler import TAKEOVER_PARKED
from tests.helpers.walker_harness import (
    make_db, node, recording_scheduler, row, runs_of, seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "takeover_next_run.db")


def _held_once():
    """A step that holds for half a minute the first time it runs (a person
    arrives while it runs) and answers at once after that."""
    inside = asyncio.Event()
    hold = {"first": True}

    async def slow(task, run_id):
        if hold["first"]:
            hold["first"] = False
            inside.set()
            await asyncio.sleep(30)
        return "fetched"
    return inside, slow


async def _park_by_a_takeover(factory, **task_kw):
    inside, slow = _held_once()
    # A Prompt step: since `B1864` a takeover stops only a run that uses a
    # model — a workflow of housekeeping steps goes on beside the person.
    seed_workflow(factory, [node("fetch", "Fetch")], [], **task_kw)
    s = recording_scheduler({"Morning digest · Fetch": slow})
    assert await s.run_task_now("wf") is True        # as the due tick would (background)
    await asyncio.wait_for(inside.wait(), timeout=5)
    assert await s.stop_background_tasks_for_foreground() >= 1
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting" and run["result"] == TAKEOVER_PARKED, run
    return s


async def test_a_scheduled_workflow_parked_by_a_takeover_moves_its_next_time_on(factory):
    past = datetime.utcnow() - timedelta(minutes=1)
    await _park_by_a_takeover(factory, next_run=past)
    nr = row(factory, "wf").next_run
    assert nr is not None and nr > datetime.utcnow(), (
        f"the parked run left next_run at {nr}, in the past")


async def test_the_next_tick_after_a_takeover_starts_nothing_and_writes_no_skipped_run(
        factory, monkeypatch):
    import src.task_scheduler as ts
    monkeypatch.setattr(ts, "dispatch_hold", lambda *a, **k: 0.0)
    past = datetime.utcnow() - timedelta(minutes=1)
    s = await _park_by_a_takeover(factory, next_run=past)
    # The next tick: only the due-task half, so the sweeper does not resume
    # the parked run inside the same call.
    monkeypatch.setattr(s, "_resume_due_waits", lambda: asyncio.sleep(0, result=0))
    await s._check_due_tasks()
    await settle(s)
    runs = runs_of(factory, "wf")
    assert [r["status"] for r in runs] == ["waiting"], (
        "a second (skipped) run was written for a time that had already run: "
        f"{[(r['status'], r['result']) for r in runs]}")


async def test_the_parked_run_still_goes_on_once_pantheon_is_idle(factory):
    """The sweeper reads the step records, not `next_run`: moving the next
    time on does not strand the parked run."""
    past = datetime.utcnow() - timedelta(minutes=1)
    s = await _park_by_a_takeover(factory, next_run=past)
    assert await s._resume_due_waits() == 1
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    nr = row(factory, "wf").next_run
    assert nr is not None and nr > datetime.utcnow()


async def test_a_webhook_workflow_parked_by_a_takeover_is_not_left_due(factory):
    """An event or webhook task runs when it is triggered: parked with no
    event queued, it is due for nothing (`_settle_event_next_run`)."""
    past = datetime.utcnow() - timedelta(minutes=1)
    await _park_by_a_takeover(factory, trigger_type="webhook", schedule=None,
                              scheduled_time=None, next_run=past)
    assert row(factory, "wf").next_run is None


async def test_a_wait_park_still_moves_the_next_time_on(factory):
    """The control: the `TaskWaiting` park was already right."""
    past = datetime.utcnow() - timedelta(minutes=1)
    seed_workflow(factory, [node("w", "Wait", "wait", mode="for", minutes=5)], [],
                  next_run=past)
    s = recording_scheduler({})
    assert await s.run_task_now("wf") is True
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting"
    nr = row(factory, "wf").next_run
    assert nr is not None and nr > datetime.utcnow()
