# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1853` — a start that runs only when you run it (`trigger_type: manual`).

Measured before this row, on `ea80706`: a workflow had to start on a
schedule, an event or a webhook (`START_TRIGGER_TYPES`), so one that should
only ever be run by hand was given a webhook nobody called or a schedule in
2099. `clean_trigger_fields` turned `manual` into a webhook — an address that
answers anyone who holds it — and a plain task created `manual` was stored
`completed`, never to run. Now `manual` is a start that is never due: switched
on it MAY be run (Run now, a test run, the assistant, the API), nothing on a
clock starts it, and it has no next time.

Driven through the real routes, the real scheduler and `manage_tasks`
(`walker_harness`); only an Action step's far end is a recorder.
"""

import json
from datetime import datetime, timedelta

import pytest

from core.database import ScheduledTask, TaskRun
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, recording_scheduler, row, runs_of,
    seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio

ALICE = {"x-test-user": "alice"}
SET_THEN_ACT = ([node("s", "Make it", "set", fields=[{"name": "n", "value": 3}]),
                 node("a", "Tidy", "action", action="tidy_sessions")],
                [arrow("start", "s"), arrow("s", "a")])


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "manual.db")


def test_a_manual_start_is_kept_as_one_not_made_a_webhook():
    from src.workflow_store import START_TRIGGER_TYPES, clean_trigger_fields
    assert "manual" in START_TRIGGER_TYPES
    fields, notes = clean_trigger_fields({"trigger_type": "manual", "schedule": "daily",
                                          "scheduled_time": "07:00"})
    assert fields == {"trigger_type": "manual", "schedule": None, "scheduled_time": None}
    assert notes == []
    # `Law 1`: a webhook is still a webhook.
    hook, _ = clean_trigger_fields({"trigger_type": "webhook"})
    assert hook["trigger_type"] == "webhook"


async def test_a_manual_workflow_switched_on_is_never_due_and_runs_when_run(
        factory, monkeypatch):
    seed_workflow(factory, *SET_THEN_ACT, status="paused", trigger_type="manual",
                  schedule=None, scheduled_time=None)
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        on = await client.post("/api/tasks/wf/resume", headers=ALICE)
        assert on.status_code == 200, on.text
        body = on.json()
        assert body["status"] == "active" and body["next_run"] is None
        assert ("Only when you run it: Run now, your assistant or the API start it, "
                "and nothing starts it by itself.") in body["notes"]

        # Never due — even with a next time an older row or a hand edit left.
        db = factory()
        db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first().next_run = (
            datetime.utcnow() - timedelta(hours=1))
        db.commit()
        db.close()
        await s._check_due_tasks()
        await settle(s)
        assert runs_of(factory, "wf") == [], "nothing on a clock starts it"

        res = await client.post("/api/tasks/wf/run", headers=ALICE)
        assert res.status_code == 200, res.text
        await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["id"] == res.json()["run_id"] and run["status"] == "success", run
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy"]
    after = row(factory, "wf")
    assert after.status == "active" and after.next_run is None, "still on, still never due"


async def test_a_plain_task_made_manual_is_on_with_no_next_time(factory, monkeypatch):
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        made = await client.post("/api/tasks", headers=ALICE, json={
            "name": "Tidy by hand", "task_type": "action", "action": "tidy_sessions",
            "trigger_type": "manual"})
        assert made.status_code == 200, made.text
        task_id = made.json()["id"]
        made_row = row(factory, task_id)
        assert made_row.status == "active", "not `completed` before it ever ran"
        assert made_row.next_run is None

        daily = await client.post("/api/tasks", headers=ALICE, json={
            "name": "Tidy daily", "task_type": "action", "action": "tidy_sessions",
            "schedule": "daily", "scheduled_time": "07:00"})
        daily_id = daily.json()["id"]
        assert row(factory, daily_id).next_run is not None
        edited = await client.put(f"/api/tasks/{daily_id}", headers=ALICE,
                                  json={"trigger_type": "manual"})
        assert edited.status_code == 200, edited.text
        assert row(factory, daily_id).next_run is None, "its schedule's next time goes"
        assert row(factory, daily_id).schedule == "daily", "and its schedule is kept"
        await client.post(f"/api/tasks/{daily_id}/pause", headers=ALICE)
        resumed = await client.post(f"/api/tasks/{daily_id}/resume", headers=ALICE)
        assert resumed.json()["next_run"] is None

        res = await client.post(f"/api/tasks/{task_id}/run", headers=ALICE)
        assert res.status_code == 200, res.text
        await settle(s)
    assert [r["status"] for r in runs_of(factory, task_id)] == ["success"]
    assert row(factory, task_id).next_run is None


async def test_the_assistant_can_make_list_and_edit_a_manual_task(factory):
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.tools.system import do_manage_tasks
    schema = next(t["function"] for t in FUNCTION_TOOL_SCHEMAS
                  if t.get("function", {}).get("name") == "manage_tasks")
    assert "manual" in schema["parameters"]["properties"]["trigger_type"]["enum"]

    made = await do_manage_tasks(json.dumps({
        "action": "create", "task_type": "action", "action_name": "tidy_sessions",
        "name": "Tidy by hand", "trigger_type": "manual"}), owner="alice")
    assert made["exit_code"] == 0, made
    task = row(factory, made["task_id"])
    assert task.trigger_type == "manual" and task.status == "active" and task.next_run is None

    daily = await do_manage_tasks(json.dumps({
        "action": "create", "task_type": "action", "action_name": "tidy_sessions",
        "name": "Tidy daily", "schedule": "daily", "scheduled_time": "07:00"}), owner="alice")
    assert row(factory, daily["task_id"]).next_run is not None
    edited = await do_manage_tasks(json.dumps({
        "action": "edit", "task_id": daily["task_id"], "trigger_type": "manual"}), owner="alice")
    assert edited["exit_code"] == 0, edited
    assert row(factory, daily["task_id"]).next_run is None

    listed = await do_manage_tasks(json.dumps({"action": "list"}), owner="alice")
    lines = {ln.split(" (")[0].split(". ", 1)[1]: ln for ln in listed["response"].splitlines()[1:]}
    assert lines["Tidy by hand"].endswith("— active, only when you run it")
    assert lines["Tidy daily"].endswith("— active, only when you run it"), (
        "the schedule left on the row is not read out as when it runs")


async def test_a_manual_runs_retry_survives_a_restart(factory, monkeypatch):
    """A manual start's retry is the same start again (as an event's), and a
    restart re-arms it (`B1494`'s sweep reads `manual` too)."""
    import src.task_scheduler as ts
    from src.builtin_actions import NodeResult
    from src.task_scheduler import RETRY_PLAN_KEY, TaskScheduler
    monkeypatch.setattr(ts, "failure_backoff_seconds", lambda failures: 3600)
    db = factory()
    db.add(ScheduledTask(id="hand", owner="alice", name="File it", status="active",
                         trigger_type="manual", task_type="action", action="tidy_documents",
                         max_retries=2))
    db.commit()
    db.close()
    first = recording_scheduler({"File it": NodeResult("error", payload="503")})
    assert await first.run_task_now("hand") is True
    await settle(first)
    for job in list(getattr(first, "_pending_retries", None) or ()):
        job.cancel()
    db = factory()
    try:
        [failed] = db.query(TaskRun).filter(TaskRun.task_id == "hand").all()
        steps = json.loads(failed.steps)
    finally:
        db.close()
    assert failed.status == "error"
    assert any(RETRY_PLAN_KEY in st for st in steps), steps
    assert any("retrying (attempt 1 of 2)" in (st.get("detail") or "") for st in steps)
    assert row(factory, "hand").next_run is None
    after = TaskScheduler(None)
    try:
        assert after._rearm_pending_retries() == 1
    finally:
        for job in list(getattr(after, "_pending_retries", None) or ()):
            job.cancel()
