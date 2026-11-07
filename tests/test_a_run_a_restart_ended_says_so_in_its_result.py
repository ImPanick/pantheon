# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1868` — a run a restart ended says so in its result, not only its error.

`_sweep_runs_left_by_a_restart` marked every run the last process left
queued or running `aborted` and wrote "Server restarted while task was …" to
its `error` — and left its `result` as the old process last wrote it. The Runs
list shows a run's result, so a webhook's run that had been waiting for
Pantheon to be idle read "Queued — waiting for Pantheon to be idle…" under
`aborted`, for ever. Now the result is the same sentence. Nothing is resumed
across the restart (what the run was handed went with that process), and a
parked run (`waiting`) is left exactly as it was.

Driven (`Law 20`): the real scheduler puts the runs in those states on a real
SQLite file — waiting for idle behind the real gate, and mid-step — then a
second scheduler over the same file runs its start-up sweep, and the runs are
read back through the real Runs route.
"""

import asyncio

import pytest

from src.task_scheduler import TaskScheduler
from core.database import ScheduledTask
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, records_of, recording_scheduler, runs_of,
    seed_workflow,
)
from tests.test_a_workflow_with_no_model_runs_while_pantheon_is_open import (  # noqa: F401
    IDLE_WAIT, _someone_is_here, _tab_closes, _until, gate,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "restart.db")


async def _the_old_process_is_gone():
    """What a dead process leaves: nothing of it runs on. Its runs' rows are
    what the next process finds."""
    left = [t for t in asyncio.all_tasks()
            if t is not asyncio.current_task() and "_execute_task" in repr(t.get_coro())]
    for t in left:
        t.cancel()
    await asyncio.gather(*left, return_exceptions=True)


async def _runs_through_the_route(factory, monkeypatch, task_id):
    app = app_for(factory, TaskScheduler(None), monkeypatch)
    async with client_for(app) as client:
        res = await client.get(f"/api/tasks/{task_id}/runs", headers={"x-test-user": "alice"})
    assert res.status_code == 200, res.text
    return res.json()["runs"]


async def test_a_run_waiting_for_idle_when_the_server_stopped_says_it_was_ended(
        factory, gate, monkeypatch):
    db = factory()
    db.add(ScheduledTask(id="hook", owner="alice", name="Tidy", task_type="action",
                         action="tidy_sessions", trigger_type="webhook", status="active"))
    db.commit()
    db.close()
    first = recording_scheduler()
    await _someone_is_here()
    assert await first.run_task_now("hook") is True
    await _until(lambda: [r["result"] for r in runs_of(factory, "hook")] == [IDLE_WAIT],
                 "the run waits for Pantheon to be idle")

    TaskScheduler(None)._sweep_runs_left_by_a_restart()        # the next process starts

    [run] = await _runs_through_the_route(factory, monkeypatch, "hook")
    assert run["status"] == "aborted"
    assert run["result"] == "Server restarted while task was queued", run
    assert run["error"] == run["result"]
    assert first.calls == [], "nothing ran"
    await _the_old_process_is_gone()
    await _tab_closes()


async def test_a_run_mid_step_when_the_server_stopped_says_it_was_ended(factory, monkeypatch):
    """`B1896`: a workflow run mid-step is parked on its step when it is
    younger than `RESTART_RESUME_MAX_AGE` (`test_a_restart_keeps_what_it_can.
    py`); with that age at nothing, it is one that is ended, and says so."""
    import src.task_scheduler as ts
    from datetime import timedelta
    monkeypatch.setattr(ts, "RESTART_RESUME_MAX_AGE", timedelta(0))
    inside = asyncio.Event()

    async def slow(task, run_id):
        inside.set()
        await asyncio.sleep(30)
    seed_workflow(factory, [node("brief", "Brief me")], [arrow("start", "brief")])
    first = recording_scheduler({"Morning digest · Brief me": slow})
    assert await first.run_task_now("wf") is True
    await asyncio.wait_for(inside.wait(), timeout=5)
    [before] = runs_of(factory, "wf")
    assert before["status"] == "running" and before["result"] != before["error"]

    TaskScheduler(None)._sweep_runs_left_by_a_restart()

    [run] = await _runs_through_the_route(factory, monkeypatch, "wf")
    assert (run["status"], run["result"], run["error"]) == (
        "aborted", "Server restarted while task was running",
        "Server restarted while task was running")
    assert [r["status"] for r in records_of(factory, run["id"])] == ["aborted"]
    await _the_old_process_is_gone()


async def test_a_parked_run_keeps_its_words(factory, monkeypatch):
    """The control: `P22-11` — a parked run is held by no process, so a
    restart leaves it waiting, saying what it waits for."""
    seed_workflow(factory, [node("w", "Wait an hour", "wait", mode="for", minutes=60)])
    await recording_scheduler()._execute_task("wf")
    [before] = runs_of(factory, "wf")
    assert before["status"] == "waiting"

    TaskScheduler(None)._sweep_runs_left_by_a_restart()

    [run] = runs_of(factory, "wf")
    assert (run["status"], run["result"], run["error"]) == (
        "waiting", before["result"], before["error"])
