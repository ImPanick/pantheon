# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-11` — a Wait parks the run, and the run survives a restart.

"Restarted" means what it means in production: a SECOND `TaskScheduler` over
the same SQLite file, its restart sweep run (`_sweep_runs_left_by_a_restart`),
its sweeper (`_resume_due_waits`) asked — nothing carried in memory from the
first. The records are the run state (`workflow_runs.RunState`, `Law 7`), so
what the brief is handed after the restart comes out of the records the first
process wrote.
"""

import json
from datetime import timedelta

import pytest

from core.database import TaskRun, TaskRunNode, Workflow, WorkflowVersion
from src.task_scheduler import TaskScheduler, _utcnow
from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, row, runs_of, seed_workflow,
    settle, skip_ahead,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "wait.db")


FEEDS_THEN_WAIT = (
    [node("a", "Feed A", "action", action="tidy_sessions"),
     node("b", "Feed B", "action", action="tidy_documents"),
     node("c", "Feed C", "action", action="consolidate_memory"),
     node("m", "Merge", "merge", mode="all"),
     node("w", "Until later", "wait", mode="for", minutes=1),
     node("brief", "Brief me")],
    [arrow("start", "a"), arrow("start", "b"), arrow("start", "c"),
     arrow("a", "m"), arrow("b", "m"), arrow("c", "m"), arrow("m", "w"), arrow("w", "brief")],
)


async def test_three_feeds_merge_wait_restart_brief_is_one_run(factory, monkeypatch):
    """`P22-11`'s `Verify:` — "check three feeds at once, merge, wait, brief
    me" is ONE execution and survives a restart during the wait."""
    seed_workflow(factory, *FEEDS_THEN_WAIT)
    first = recording_scheduler({"Morning digest · Feed A": "A: 3 new",
                                 "Morning digest · Feed B": "B: 2 new",
                                 "Morning digest · Feed C": "C: 1 new"})
    await first._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting", run
    assert run["result"].startswith("Waiting until ")
    assert run["finished_at"] is None
    assert not first._executing and not first._run_state, "a parked run holds nothing"
    waiting = {r["node_id"]: r for r in records_of(factory, run["id"])}["w"]
    assert waiting["status"] == "waiting" and waiting["waiting"]["kind"] == "time"
    assert row(factory, "wf").next_run is not None, "a scheduled task keeps its next time"

    # ── Pantheon restarts during the wait ──
    second = recording_scheduler(scheduler=TaskScheduler(None))
    second._sweep_runs_left_by_a_restart()
    assert runs_of(factory, "wf")[0]["status"] == "waiting", "the restart sweep left it waiting"
    skip_ahead(monkeypatch, 61)                   # the Wait's time comes
    assert await second._resume_due_waits() == 1
    await settle(second)

    runs = runs_of(factory, "wf")
    assert len(runs) == 1, "the same run went on — not a new one"
    run = runs[0]
    assert run["status"] == "success", run
    records = records_of(factory, run["id"])
    assert sorted(r["node_id"] for r in records) == ["a", "b", "brief", "c", "m", "w"]
    assert len(records) == 6, "six records, each step once"
    # The brief was run by the SECOND process and handed the merge's output,
    # read back from the record the FIRST process wrote.
    [brief] = [c for c in second.calls if c["name"] == "Morning digest · Brief me"]
    assert first.calls and not [c for c in first.calls if "Brief" in c["name"]]
    texts = sorted(i["text"] for i in brief["trigger"]["data"]["data"]["inputs"])
    assert texts == ["A: 3 new", "B: 2 new", "C: 1 new"]
    assert {r["node_id"]: r["status"] for r in records}["w"] == "success"
    assert any(st.get("detail", "").startswith("Resumed") for st in run["steps"])


async def test_a_wait_not_yet_due_is_left_waiting(factory):
    seed_workflow(factory, [node("w", "Wait an hour", "wait", mode="for", minutes=60),
                            node("x", "Then", "action", action="tidy_sessions")],
                  [arrow("w", "x")])
    s = recording_scheduler()
    await s._execute_task("wf")
    assert runs_of(factory, "wf")[0]["status"] == "waiting"
    assert await s._resume_due_waits() == 0
    assert s.calls == []
    # `_loop` wakes for it: the earliest time a parked step is due.
    due = s._next_resume_at()
    assert due is not None and timedelta(minutes=59) < due - _utcnow() <= timedelta(minutes=60)


async def test_a_wait_until_a_clock_time_and_its_cap(factory, monkeypatch):
    """`{mode: until, time: "HH:MM"}` on the trigger's clock, never more than
    `workflow_wait_max_hours` ahead — refused with that name, nothing run."""
    seed_workflow(factory, [node("w", "Until 08:00", "wait", mode="until", time="08:00",
                                 tz="Australia/Sydney"),
                            node("x", "Then", "action", action="tidy_sessions")],
                  [arrow("w", "x")])
    s = recording_scheduler()
    await s._execute_task("wf")
    run = runs_of(factory, "wf")[0]
    rec = [r for r in records_of(factory, run["id"]) if r["node_id"] == "w"][0]
    from zoneinfo import ZoneInfo
    from datetime import datetime, timezone
    until = datetime.fromisoformat(rec["waiting"]["until"].rstrip("Z")).replace(tzinfo=timezone.utc)
    local = until.astimezone(ZoneInfo("Australia/Sydney"))
    assert (local.hour, local.minute) == (8, 0)
    assert timedelta(0) < until - datetime.now(timezone.utc) <= timedelta(hours=24)

    seed_workflow(factory, [node("w", "A month", "wait", mode="for", minutes=60 * 24 * 30),
                            node("x", "Then", "action", action="tidy_sessions")],
                  [arrow("w", "x")], task_id="wf2")
    await s._execute_task("wf2")
    run = runs_of(factory, "wf2")[0]
    assert run["status"] == "error"
    assert "workflow_wait_max_hours" in run["error"] and "168 hours" in run["error"]
    assert [c for c in s.calls] == []


async def test_a_run_resumes_on_the_version_it_started_with(factory, monkeypatch):
    """Edited while it waited: it goes on with the document it started with."""
    nodes = [node("w", "Wait", "wait", mode="for", minutes=1),
             node("x", "Old step", "action", action="tidy_sessions")]
    seed_workflow(factory, nodes, [arrow("w", "x")], version=3)
    db = factory()
    db.add(WorkflowVersion(id="v3", workflow_id="w-wf", version=3, name="Morning digest",
                           graph=json.dumps({"v": 1, "nodes": nodes, "edges": [arrow("w", "x")]}),
                           fingerprint="f3", source="user"))
    db.commit()
    db.close()
    s = recording_scheduler()
    await s._execute_task("wf")
    assert runs_of(factory, "wf")[0]["status"] == "waiting"
    db = factory()
    wf = db.query(Workflow).first()
    wf.graph = json.dumps({"v": 1, "nodes": [nodes[0], node("x", "New step", "action",
                                                            action="tidy_documents")],
                           "edges": [arrow("w", "x")]})
    wf.version = 4
    db.commit()
    db.close()
    skip_ahead(monkeypatch, 61)
    await s._resume_due_waits()
    await settle(s)
    assert [c["name"] for c in s.calls] == ["Morning digest · Old step"]
    assert runs_of(factory, "wf")[0]["status"] == "success"

    # Its version pruned since: it cannot go on, and says so.
    seed_workflow(factory, nodes, [arrow("w", "x")], task_id="wf2", version=7)
    await s._execute_task("wf2")
    db = factory()
    wf = db.query(Workflow).filter(Workflow.task_id == "wf2").first()
    wf.version = 8
    db.commit()
    db.close()
    skip_ahead(monkeypatch, 61)
    await s._resume_due_waits()
    await settle(s)
    run = runs_of(factory, "wf2")[0]
    assert run["status"] == "error"
    assert "version 7" in run["result"] and "no longer kept" in run["result"]


async def test_switched_off_while_it_waited_it_ends_and_says_so(factory):
    seed_workflow(factory, [node("w", "Wait", "wait", mode="for", minutes=60),
                            node("x", "Then", "action", action="tidy_sessions")],
                  [arrow("w", "x")])
    s = recording_scheduler()
    await s._execute_task("wf")
    db = factory()
    from core.database import ScheduledTask
    db.query(ScheduledTask).filter(ScheduledTask.id == "wf").update({"status": "paused"})
    db.commit()
    db.close()
    assert await s._resume_due_waits() == 1, "a switched-off workflow's run is gone on with"
    await settle(s)
    run = runs_of(factory, "wf")[0]
    assert run["status"] == "aborted" and run["error"] == "Switched off while it waited"
    rec = [r for r in records_of(factory, run["id"]) if r["node_id"] == "w"][0]
    assert rec["status"] == "aborted" and rec["waiting"] is None
    assert s.calls == []


async def test_the_restart_sweep_aborts_a_running_run_and_ends_its_waiting_steps(factory):
    """ACTIVE runs are aborted (a dead process held them); a step of such a run
    that was waiting waits for nothing now. A PARKED run is left alone."""
    db = factory()
    from core.database import ScheduledTask
    db.add(ScheduledTask(id="t", owner="alice", name="X", task_type="workflow", status="active"))
    db.add(TaskRun(id="running", task_id="t", status="running"))
    db.add(TaskRun(id="parked", task_id="t", status="waiting"))
    db.commit()
    for rid, nid, status in (("running", "a", "waiting"), ("running", "b", "running"),
                             ("parked", "a", "waiting")):
        db.add(TaskRunNode(id=f"{rid}-{nid}", run_id=rid, node_id=nid, seq=1, status=status,
                           waiting=json.dumps({"kind": "time"}) if status == "waiting" else None))
    db.commit()
    db.close()
    TaskScheduler(None)._sweep_runs_left_by_a_restart()
    db = factory()
    got = {r.id: r.status for r in db.query(TaskRun).all()}
    recs = {r.id: r.status for r in db.query(TaskRunNode).all()}
    db.close()
    assert got == {"running": "aborted", "parked": "waiting"}
    assert recs == {"running-a": "aborted", "running-b": "aborted", "parked-a": "waiting"}


async def test_a_parked_runs_records_are_never_pruned(factory):
    """Its finished records ARE its state; a short retention window must not
    take them from under a long Wait."""
    from src import workflow_runs as wr
    db = factory()
    from core.database import ScheduledTask
    db.add(ScheduledTask(id="t", owner="alice", name="X", task_type="workflow", status="active"))
    db.add(TaskRun(id="parked", task_id="t", status="waiting"))
    db.add(TaskRun(id="done", task_id="t", status="success"))
    db.commit()
    old = _utcnow() - timedelta(days=40)
    for rid in ("parked", "done"):
        db.add(TaskRunNode(id=f"{rid}-a", run_id=rid, node_id="a", seq=1, status="success",
                           finished_at=old))
    db.commit()
    assert wr.prune_node_records(db, days=30) == 1
    left = [r.id for r in db.query(TaskRunNode).all()]
    db.close()
    assert left == ["parked-a"]


async def test_after_a_restart_a_step_still_reads_what_started_the_run(factory, monkeypatch):
    """The trigger lives on the run's slot in memory; after a restart it comes
    back from the records (the input of the step the start led to), so a step
    after the Wait still reads `steps.start.data` — the webhook body."""
    from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger
    seed_workflow(factory, [
        node("w", "Wait", "wait", mode="for", minutes=1),
        node("say", "Say it", "set", fields=[{"name": "said",
                                             "value": "{{ steps.start.data.body }}"}]),
    ], [arrow("w", "say")], trigger_type="webhook")
    first = recording_scheduler()
    await first._execute_task("wf", trigger=build_trigger(
        TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": "deploy done"},
        fields=WEBHOOK_PAYLOAD_FIELDS))
    assert runs_of(factory, "wf")[0]["status"] == "waiting"
    second = recording_scheduler(scheduler=TaskScheduler(None))
    second._sweep_runs_left_by_a_restart()
    skip_ahead(monkeypatch, 61)
    assert await second._resume_due_waits() == 1
    await settle(second)
    [run] = runs_of(factory, "wf")
    said = {r["node_id"]: r for r in records_of(factory, run["id"])}["say"]
    assert said["output"]["data"] == {"said": "deploy done"}
