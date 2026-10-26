# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1079` — a *Run task* step's target, stopped because the workflow it ran
inside was stopped, says why on its own row.

**Measured before this file** (the first test below, red on the tree before
it): the foreground gate marks only the workflow's run (`B1138`), and the
cancel reaches the target through the workflow's step. The target's cancel
branch asked `_stopped_as` and `_is_takeover` about its OWN run, found nothing,
and wrote "Stopped by user" — `B1047`'s mislabel one level down — while the
workflow's row said "Waiting for Pantheon to be idle … It goes on from that
step once Pantheon is idle" — and when the workflow went on, its step ran the
task again from the start, after a run whose row blamed the person. The same
fallback named the person for a stop that was the workflow's own time limit.
Now the target's row says which, and (a takeover) is not re-queued beside the
step that runs it again.

Driven (`Law 20`): the real gate (`stop_background_tasks_for_foreground`), the
real cancel branch, the real walker and its sweeper, the real Stop and the
real time limit, on a real SQLite file (the walker harness: only the steps'
far ends record).
"""
import asyncio

import pytest

from src.task_scheduler import FOREGROUND_TAKEOVER, STOPPED_BY_USER, TAKEOVER_PARKED
from tests.helpers.walker_harness import (
    make_db, node, recording_scheduler, runs_of, seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "inside.db")


def _world(factory, **wf_kw):
    """A workflow ("Morning digest") whose one step runs the task "Backup";
    Backup's first run blocks until it is stopped."""
    from core.database import ScheduledTask

    db = factory()
    db.add(ScheduledTask(id="bk", owner="alice", name="Backup", task_type="action",
                         action="tidy_documents", trigger_type="webhook", status="active"))
    db.commit()
    db.close()
    seed_workflow(factory, [node("n1", "Run the backup", "run_task", task_id="bk")], [], **wf_kw)
    inside, hold = asyncio.Event(), {"first": True}

    async def backup(task, run_id):
        if hold["first"]:
            hold["first"] = False
            inside.set()
            await asyncio.sleep(30)
        return "backed up"
    return recording_scheduler({"Backup": backup}), inside


async def test_a_gate_stop_during_the_step_leaves_the_targets_row_saying_why(factory):
    s, inside = _world(factory)
    assert await s.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)

    assert await s.stop_background_tasks_for_foreground() >= 1
    await settle(s)
    [parked] = runs_of(factory, "wf")
    assert parked["status"] == "waiting" and parked["result"] == TAKEOVER_PARKED, parked
    [stopped] = runs_of(factory, "bk")
    assert stopped["status"] == "aborted"
    assert stopped["error"] == FOREGROUND_TAKEOVER, "it said the person stopped it"
    assert stopped["result"] == (f"{FOREGROUND_TAKEOVER}. It was a step of the workflow "
                                 f"“Morning digest”, which runs it again from the start "
                                 f"when the workflow goes on.")
    assert len(runs_of(factory, "bk")) == 1, "it re-queued itself beside the workflow's step"

    # The workflow goes on once Pantheon is idle: its step runs the task again,
    # once, from the start — and that is the only other run of it.
    assert await s._resume_due_waits() == 1
    await settle(s)
    assert runs_of(factory, "wf")[0]["status"] == "success"
    assert [r["status"] for r in runs_of(factory, "bk")] == ["aborted", "success"]


async def test_stop_on_the_workflow_still_says_the_person_stopped_it(factory):
    """`Law 1`: a person's Stop reaches the target the same way, and that one
    was the person — said in the workflow's own words."""
    s, inside = _world(factory)
    assert await s.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    assert await s.stop_task("wf") is True
    await settle(s)
    [stopped] = runs_of(factory, "bk")
    assert (stopped["status"], stopped["error"]) == ("aborted", STOPPED_BY_USER)


async def test_the_workflows_time_limit_is_not_called_a_person(factory, monkeypatch):
    import src.task_scheduler as ts
    monkeypatch.setattr(ts, "MIN_TASK_TIMEOUT_SECONDS", 1)   # a second, not the floor's thirty
    s, inside = _world(factory, timeout_seconds=1)
    assert await s.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    await settle(s, rounds=400)
    [wf] = runs_of(factory, "wf")
    assert wf["status"] == "error" and "this task's own timeout" in wf["error"], wf
    [stopped] = runs_of(factory, "bk")
    assert stopped["status"] == "aborted"
    assert stopped["error"] == "Stopped because the workflow “Morning digest” that ran it stopped"
