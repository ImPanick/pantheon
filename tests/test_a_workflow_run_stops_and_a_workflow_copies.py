# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1869`, `B1845` — the Workbench stops a run it shows, and copies a
workflow, through routes of the workflow's own.

**Measured before this file:** a run on the Runs tab had no Stop (the only
stop was the Tasks window's, by task); the delete route existed and nothing in
the Workbench called it; there was no way to copy a workflow but Export and
Import, which marks every step to be checked and drops what an export never
carries.

`POST /api/workflows/{id}/runs/{run_id}/stop` ends the run the person is
looking at — a parked one where it waits, with its record saying so — and a
second press is told the run has ended (409). Somebody else's workflow is a
404 and stops nothing. `POST /api/workflows/{id}/duplicate` makes
"<name> (copy)", switched off, with the same steps and the same start.

Real (`Law 20`): the routes through an ASGI client over the real scheduler on
a real SQLite file (`walker_harness`).
"""

import json

import pytest

from core.database import ScheduledTask, Workflow
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
)

pytestmark = pytest.mark.asyncio

WAITS = ([node("w", "Wait an hour", "wait", mode="for", minutes=60),
          node("x", "Then", "action", action="tidy_sessions")], [arrow("w", "x")])
ALICE = {"x-test-user": "alice"}
BOB = {"x-test-user": "bob"}


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "stop.db")


async def _parked(factory):
    seed_workflow(factory, *WAITS)
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting"
    return s, run


async def test_stop_ends_the_waiting_run_it_names_and_says_so(factory, monkeypatch):
    s, parked = await _parked(factory)
    path = f"/api/workflows/w-wf/runs/{parked['id']}/stop"
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        theirs = await client.post(path, headers=BOB)
        assert theirs.status_code == 404, theirs.text
        assert runs_of(factory, "wf")[0]["status"] == "waiting", "somebody else's press stops nothing"
        res = await client.post(path, headers=ALICE)
        assert res.status_code == 200, res.text
        assert res.json()["sentence"].startswith("Stopped where it waited.")
        run = runs_of(factory, "wf")[0]
        assert run["status"] == "aborted"
        rec = [r for r in records_of(factory, run["id"]) if r["node_id"] == "w"][0]
        assert rec["status"] == "aborted"
        again = await client.post(path, headers=ALICE)
        assert again.status_code == 409 and again.json()["detail"] == "This run has already ended."


async def test_stop_names_a_run_of_this_workflow_only(factory, monkeypatch):
    s, _ = await _parked(factory)
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/workflows/w-wf/runs/not-a-run/stop", headers=ALICE)
    assert res.status_code == 404
    assert runs_of(factory, "wf")[0]["status"] == "waiting"


async def test_duplicate_makes_a_switched_off_copy_with_the_same_steps_and_start(factory, monkeypatch):
    seed_workflow(factory, *WAITS)
    db = factory()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first()
        task.status = "active"
        task.trigger_type = "schedule"
        task.schedule = "weekly"
        task.scheduled_time = "07:30"
        task.scheduled_day = 2
        task.tz_name = "Europe/London"
        db.commit()
        original_graph = json.loads(db.query(Workflow).filter(Workflow.id == "w-wf").first().graph)
    finally:
        db.close()
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        theirs = await client.post("/api/workflows/w-wf/duplicate", headers=BOB)
        assert theirs.status_code == 404
        res = await client.post("/api/workflows/w-wf/duplicate", headers=ALICE)
        assert res.status_code == 200, res.text
        again = await client.post("/api/workflows/w-wf/duplicate", headers=ALICE)
        assert again.status_code == 200, again.text
    body = res.json()
    made = body["workflow"]
    assert made["name"] == "Morning digest (copy)"
    assert again.json()["workflow"]["name"] != made["name"], "a second copy takes the next free name"
    assert any("switched off" in n for n in body["notes"])
    db = factory()
    try:
        copy = db.query(Workflow).filter(Workflow.id == made["id"]).first()
        assert copy is not None and copy.id != "w-wf" and copy.owner == "alice"
        start = db.query(ScheduledTask).filter(ScheduledTask.id == copy.task_id).first()
        assert start.id != "wf" and start.status == "paused" and start.task_type == "workflow"
        assert (start.schedule, start.scheduled_time, start.scheduled_day, start.tz_name) == (
            "weekly", "07:30", 2, "Europe/London")
        graph = json.loads(copy.graph)
        assert [n["id"] for n in graph["nodes"]] == [n["id"] for n in original_graph["nodes"]]
        assert graph["edges"] == original_graph["edges"]
        # The original is untouched, and still on.
        assert db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first().status == "active"
    finally:
        db.close()
