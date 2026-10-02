# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B674` / `P22-11` — one workflow runs once at a time, and that is ONE rule.

`workflow_runs.run_in_flight` is the question; a run that is parked (`waiting`)
holds its workflow exactly as a running one does. Every door that can start a
run asks it: the scheduler's own tick, an app event through the real bus, the
webhook and *Run now* through the real routes (their 409 says which run and
what it waits for), and the email subprocess's guard. Stop ends a waiting run —
which no coroutine holds to cancel — and retires its card.
"""

import asyncio
import json

import pytest

from core.database import ScheduledTask, TaskRun
from src.task_scheduler import TaskScheduler
from src.tool_approvals import tool_approval_store
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, records_of, recording_scheduler, row,
    runs_of, seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio

WAITS = ([node("w", "Wait an hour", "wait", mode="for", minutes=60),
          node("x", "Then", "action", action="tidy_sessions")], [arrow("w", "x")])


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "hold.db")


async def _parked(factory, **task_kw):
    seed_workflow(factory, *WAITS, **task_kw)
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting"
    return s, run


async def test_a_scheduled_tick_while_it_waits_is_a_skipped_run_that_says_why(factory, monkeypatch):
    import src.task_scheduler as ts
    monkeypatch.setattr(ts, "dispatch_hold", lambda *a, **k: 0.0)   # no `P15-10` jitter here
    s, parked = await _parked(factory)
    db = factory()
    task = db.query(ScheduledTask).first()
    task.next_run = task.next_run.replace(year=2000)       # due now
    db.commit()
    db.close()
    await s._check_due_tasks()
    await settle(s)
    runs = runs_of(factory, "wf")
    assert len(runs) == 2
    skipped = runs[1]
    assert skipped["status"] == "skipped"
    assert skipped["result"].startswith("Did not start: the ")
    assert "run is still waiting until " in skipped["result"]
    assert runs[0]["status"] == "waiting", "the waiting run is untouched"
    assert s.calls == [], "nothing ran beside it"
    assert row(factory, "wf").next_run.year > 2000, "the schedule moved on"
    assert [n for n in s.pop_notifications() if n["status"] == "skipped"] == []


async def test_an_event_while_it_waits_is_skipped_once_and_not_queued_again(factory, monkeypatch):
    """Through the real bus: `_handle_event` writes `next_run = now` and asks
    `run_task_now`; the skipped row clears it, so the loop's next tick does not
    run the task a second time."""
    import src.event_bus as bus
    s, parked = await _parked(factory, trigger_type="event", trigger_event="document_updated",
                              trigger_count=1)
    monkeypatch.setattr(bus, "_task_scheduler", s)
    await bus._handle_event("document_updated", "alice", {"document_id": "d1", "title": "Plan"})
    await s._check_due_tasks()
    await settle(s)
    runs = runs_of(factory, "wf")
    assert [r["status"] for r in runs] == ["waiting", "skipped"]
    assert row(factory, "wf").next_run is None
    assert s.calls == []


async def test_the_webhook_keeps_its_409_with_the_waiting_runs_words(factory, monkeypatch):
    s, parked = await _parked(factory, trigger_type="webhook", webhook_token="tok")
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.post("/api/tasks/wf/webhook/tok", json={"issue": 7})
        assert res.status_code == 409, res.text
        detail = res.json()["detail"]
        assert detail.startswith("Did not start: the ") and "waiting until" in detail
        again = await client.post("/api/tasks/wf/run", headers={"x-test-user": "alice"})
        assert again.status_code == 409 and again.json()["detail"] == detail
        # A dry run plans and touches nothing, so it is not held.
        dry = await client.post("/api/tasks/wf/run?dry=true", headers={"x-test-user": "alice"})
        assert dry.status_code == 200, dry.text
    statuses = [r["status"] for r in runs_of(factory, "wf")]
    assert statuses.count("skipped") == 3 and statuses[0] == "waiting"
    assert sum(1 for r in runs_of(factory, "wf") if (r["result"] or "") == detail) == 2


async def test_stop_ends_a_waiting_run_and_retires_its_card(factory):
    """Stop (`stop_task`) reaches a run no coroutine holds: it is `aborted`,
    its waiting step says so, and the card it waited on can no longer be
    answered."""
    from src.tool_capabilities import capabilities_for_action
    s, parked = await _parked(factory)
    pending = tool_approval_store.create(
        owner="alice", session_id="", origin_run_id=f"{parked['id']}:w", tool_name="bash",
        content="echo hi", workspace=None, external_untrusted_context_seen=False,
        capabilities=capabilities_for_action("bash", "echo hi"))
    db = factory()
    from core.database import TaskRunNode
    rec = db.query(TaskRunNode).filter(TaskRunNode.node_id == "w").first()
    rec.waiting = json.dumps({"kind": "approval", "approval_id": pending.approval_id,
                              "session_id": ""})
    db.commit()
    db.close()
    assert await s.stop_task("wf") is True
    run = runs_of(factory, "wf")[0]
    assert run["status"] == "aborted" and run["error"] == "Stopped by user"
    rec = [r for r in records_of(factory, run["id"]) if r["node_id"] == "w"][0]
    assert rec["status"] == "aborted" and rec["error"] == "Stopped by user"
    assert tool_approval_store.peek(pending.approval_id) is None, "the card was retired"
    # And it holds the workflow no longer.
    await s._execute_task("wf")
    assert [r["status"] for r in runs_of(factory, "wf")] == ["aborted", "waiting"]


async def test_a_waiting_workflow_cannot_be_deleted(factory, monkeypatch):
    s, parked = await _parked(factory)
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await client.delete("/api/workflows/w-wf", headers={"x-test-user": "alice"})
    assert res.status_code == 409 and "is running" in res.json()["detail"]


async def test_the_email_subprocess_guard_asks_the_same_question(factory, monkeypatch):
    """No scheduler in this process (the email MCP server is a subprocess):
    an event for a workflow whose run waits leaves its counter and its
    `next_run` alone (`event_bus._workflow_run_in_flight` →
    `run_in_flight`)."""
    import src.event_bus as bus
    s, parked = await _parked(factory, trigger_type="event", trigger_event="document_updated",
                              trigger_count=1)
    monkeypatch.setattr(bus, "_task_scheduler", None)
    db = factory()
    assert bus._workflow_run_in_flight(db, db.query(ScheduledTask).first()) is True
    db.close()
    await bus._handle_event("document_updated", "alice", {"document_id": "d1"})
    task = row(factory, "wf")
    assert task.next_run is None and (task.trigger_counter or 0) == 0
