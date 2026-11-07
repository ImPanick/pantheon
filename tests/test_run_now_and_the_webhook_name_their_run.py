# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1866` — *Run now* and a webhook say which run they started.

Measured before this row, on `ea80706`: `POST /api/tasks/{id}/run` answered
`{ok, dry, message}` and a webhook `{ok, message}`, so a page that pressed
Run now, or a sender that rang the doorbell, could not open or match the run
it had started without guessing from the Runs list. Both now add `run_id` —
the id the `queued` row is written under BEFORE the run is spawned (the
machinery `B1852`'s test run uses), so the run can be opened at once. Every
key that was on the reply still is (`Law 1`).

Driven through the real routes over the real scheduler (`walker_harness`).
"""

import pytest

from core.database import ScheduledTask, TaskRun
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, recording_scheduler, runs_of, seed_workflow,
    settle,
)

pytestmark = pytest.mark.asyncio

ALICE = {"x-test-user": "alice"}
SET_THEN_ACT = ([node("s", "Make it", "set", fields=[{"name": "n", "value": 3}]),
                 node("a", "Tidy", "action", action="tidy_sessions")],
                [arrow("start", "s"), arrow("s", "a")])
WAIT = ([node("w", "Wait a minute", "wait", mode="for", minutes=1)], [arrow("start", "w")])


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "run-id.db")


def _plain_action_task(factory, task_id="plain", **kw):
    db = factory()
    try:
        db.add(ScheduledTask(id=task_id, owner="alice", name="Chats Tidy", task_type="action",
                             action="tidy_sessions", trigger_type=kw.pop("trigger_type", "schedule"),
                             schedule="daily", scheduled_time="08:00", status="active", **kw))
        db.commit()
    finally:
        db.close()


async def test_run_now_names_the_run_it_started_and_the_run_is_there_at_once(
        factory, monkeypatch):
    seed_workflow(factory, *SET_THEN_ACT)
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/tasks/wf/run", headers=ALICE)
        assert res.status_code == 200, res.text
        body = res.json()
        assert {k: body[k] for k in ("ok", "dry", "message")} == {
            "ok": True, "dry": False, "message": "Task triggered"}, "every old key, unchanged"
        opened = await client.get(f"/api/workflows/w-wf/runs/{body['run_id']}", headers=ALICE)
        assert opened.status_code == 200, opened.text
        await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["id"] == body["run_id"] and run["status"] == "success", run


async def test_run_now_of_a_plain_task_in_parallel_names_its_run(factory, monkeypatch):
    _plain_action_task(factory)
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/tasks/plain/run?force=true", headers=ALICE)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["message"] == "Task triggered in parallel"
        await settle(s)
    [run] = runs_of(factory, "plain")
    assert run["id"] == body["run_id"]
    assert [c["name"] for c in s.calls] == ["Chats Tidy"]


async def test_a_dry_run_still_answers_with_the_run_that_holds_its_plan(factory, monkeypatch):
    """`P22-04`'s `run_id`, unchanged: the dry run's own, not a new one."""
    seed_workflow(factory, *SET_THEN_ACT)
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/tasks/wf/run?dry=true", headers=ALICE)
        assert res.status_code == 200, res.text
        body = res.json()
    [run] = runs_of(factory, "wf")
    assert body["dry"] is True and body["run_id"] == run["id"]
    assert s.calls == []


async def test_a_webhook_names_the_run_its_call_started(factory, monkeypatch):
    seed_workflow(factory, *SET_THEN_ACT, trigger_type="webhook", webhook_token="tok",
                  schedule=None)
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/tasks/wf/webhook/tok", json={"issue": 7})
        assert res.status_code == 200, res.text
        body = res.json()
        assert {k: body[k] for k in ("ok", "message")} == {
            "ok": True, "message": "Task triggered via webhook"}
        await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["id"] == body["run_id"] and run["status"] == "success", run
    assert s.calls[0]["name"] == "Morning digest · Tidy"


async def test_a_webhook_that_did_not_start_a_run_names_none(factory, monkeypatch):
    """`B674`'s 409 is kept: a parked run holds the workflow, and the reply
    names no run — the `skipped` row is the one the engine wrote, not one the
    caller started."""
    seed_workflow(factory, *WAIT, trigger_type="webhook", webhook_token="tok", schedule=None)
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        first = await client.post("/api/tasks/wf/webhook/tok", json={})
        await settle(s)
        again = await client.post("/api/tasks/wf/webhook/tok", json={})
    assert first.status_code == 200 and isinstance(first.json()["run_id"], str)
    assert again.status_code == 409, again.text
    assert "run_id" not in again.json()
    db = factory()
    try:
        statuses = sorted(r.status for r in db.query(TaskRun).all())
    finally:
        db.close()
    assert statuses == ["skipped", "waiting"]
