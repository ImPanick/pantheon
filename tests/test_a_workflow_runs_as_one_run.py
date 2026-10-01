# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05` / `P22-07` / `P22-08` — a workflow is one document, run as ONE run
by the real scheduler, every step recorded.

Before this, a "workflow" was `ScheduledTask` rows joined by `then_task_id` /
`else_task_id`, each step its own `TaskRun`: a two-step morning digest was two
runs under two names, and nothing grouped them. `task_type="workflow"` is a
trigger task whose run walks a document (`TaskScheduler._run_workflow`) through
the executors that exist, each step recorded in `task_run_nodes`.

Everything is real (`Law 20`, option 1): the real `TaskScheduler` from
`_execute_task` down, the real gates (switched off — nobody is using Pantheon —
except where a test needs them), the real event bus, a real SQLite file. Only
the model is absent: the three executors are recorders (and in the first test,
the real Prompt executor runs down to `_run_agent_loop`, which is the recorder),
so what each step was handed and what it returned is observed, not assumed.
"""

import asyncio
import json
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.interactive_gate as ig  # noqa: E402
import src.task_scheduler as ts  # noqa: E402
from core.database import ScheduledTask, TaskRun, TaskRunNode, Workflow  # noqa: E402
from src import workflow_document as wd  # noqa: E402
from src import workflow_runs as wr  # noqa: E402
from src.builtin_actions import NodeResult  # noqa: E402
from src.event_bus import TRIGGER_SOURCE_TASK, build_trigger  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402

OWNER = "alice"


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(f"sqlite:///{tmp_path / 'wf.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    # Nobody is using Pantheon: the gate lets every run straight through.
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "0")
    # Only `root` may run admin-only actions.
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", lambda owner: owner == "root")
    import src.tool_index as tool_index
    monkeypatch.setattr(tool_index, "get_tool_index", lambda: None)
    return factory


def node(node_id, label, kind="llm", **config):
    if kind in ("llm", "research") and "prompt" not in config:
        config["prompt"] = f"Do {label}."
    return {"id": node_id, "kind": kind, "label": label, "config": config}


def arrow(a, b, port="success"):
    return {"from": a, "port": port, "to": b}


def seed_workflow(factory, nodes, edges=(), *, task_id="wf", name="Morning digest",
                  status="active", owner=OWNER, **task_kw):
    db = factory()
    try:
        db.add(ScheduledTask(id=task_id, owner=owner, name=name, task_type="workflow",
                             trigger_type=task_kw.pop("trigger_type", "schedule"),
                             schedule="daily", scheduled_time="08:00", status=status,
                             **task_kw))
        db.add(Workflow(id=f"w-{task_id}", owner=owner, name=name, task_id=task_id,
                        graph=json.dumps({"v": 1, "nodes": list(nodes), "edges": list(edges)}),
                        version=3))
        db.commit()
    finally:
        db.close()


def seed_task(factory, task_id, name, **kw):
    db = factory()
    try:
        fields = dict(id=task_id, owner=OWNER, name=name, prompt=f"Do {name}.",
                      task_type="llm", trigger_type="schedule", schedule="daily",
                      scheduled_time="09:00", status="active")
        fields.update(kw)
        db.add(ScheduledTask(**fields))
        db.commit()
    finally:
        db.close()


def runs_of(factory, task_id):
    db = factory()
    try:
        return [{"id": r.id, "status": r.status, "result": r.result, "error": r.error,
                 "model": r.model, "steps": json.loads(r.steps) if r.steps else []}
                for r in db.query(TaskRun).filter(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at, TaskRun.id).all()]
    finally:
        db.close()


def records_of(factory, run_id):
    db = factory()
    try:
        return [wr.node_record_to_dict(r) for r in wr.run_node_records(db, run_id)]
    finally:
        db.close()


def row(factory, task_id):
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    finally:
        db.close()


def recording_scheduler(outcomes=None):
    """The real scheduler; its three executors record the stand-in they were
    handed, the step's slot and what that slot's trigger was, and answer the
    outcome named for that stand-in (a `NodeResult`, a string, or an async
    callable)."""
    outcomes = dict(outcomes or {})
    s = TaskScheduler(None)
    s.calls = []

    async def answer(kind, task, run_id):
        s.calls.append({"kind": kind, "name": task.name, "slot": run_id,
                        "trigger": s.run_trigger(run_id), "task": task})
        out = outcomes.get(task.name)
        if callable(out):
            out = await out(task, run_id)
        if kind == "action":
            return out if isinstance(out, NodeResult) else NodeResult(
                "success", payload=out or f"{task.name}: done")
        if isinstance(out, BaseException):
            raise out
        return out or f"{task.name}: done"

    async def llm(task, db, run_id=None):
        return await answer("llm", task, run_id)

    async def research(task, db, run_id=None):
        return await answer("research", task, run_id)

    async def action(task, run_id=None):
        return await answer("action", task, run_id)

    s._execute_llm_task = llm
    s._execute_research_task = research
    s._execute_action = action
    s._log_to_assistant = lambda *a, **k: None
    s.delivered = []

    async def deliver(task, result, db, model=None):
        s.delivered.append((task.name, result))
    s._deliver_task_result = deliver
    return s


# ── one run, every step ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_morning_summarise_my_inbox_then_send_me_the_summary(task_db, monkeypatch):
    """`P22-05`'s `Verify:`, as the integrator set it for this wave: *"every
    morning: summarise my inbox → send me the summary"* — one named workflow,
    and tomorrow one run with two results under that name. The real Prompt
    executor runs both steps down to the agent loop; step two is handed step
    one's summary wrapped untrusted, with the post-external gate armed
    (`P8-29`, `FORBIDDEN.md` Part 2), and delivers through its own output
    setting (a notification)."""
    from src.tool_capabilities import messages_contain_external_untrusted_context

    seed_workflow(task_db, [
        node("n1", "Summarise my inbox", model="m", endpoint_url="http://127.0.0.1:9/v1",
             prompt="Summarise my unread mail."),
        node("n2", "Send me the summary", model="m", endpoint_url="http://127.0.0.1:9/v1",
             prompt="Write me the summary.", output_target="notification"),
    ], [arrow("n1", "n2")])
    s = TaskScheduler(None)
    s._log_to_assistant = lambda *a, **k: None
    seen = []

    async def agent_loop(endpoint_url, model, task, session_id, **kw):
        seen.append({"name": task.name, "session": session_id,
                     "trigger": kw.get("trigger_context_msg")})
        return {"Morning digest · Summarise my inbox": "Three bills and a letter from Ana.",
                "Morning digest · Send me the summary": "You have 3 bills; Ana wrote."}[task.name]
    s._run_agent_loop = agent_loop

    await s._execute_task("wf")

    runs = runs_of(task_db, "wf")
    assert len(runs) == 1, "one workflow, one run"
    run = runs[0]
    assert run["status"] == "success"
    assert run["result"] == "You have 3 bills; Ana wrote."
    assert run["model"] == "m"
    records = records_of(task_db, run["id"])
    assert [(r["seq"], r["node_id"], r["label"], r["status"], r["port"]) for r in records] == [
        (1, "n1", "Summarise my inbox", "success", "success"),
        (2, "n2", "Send me the summary", "success", None),
    ]
    assert [r["output"]["text"] for r in records] == [
        "Three bills and a letter from Ana.", "You have 3 bills; Ana wrote."]
    assert all(r["workflow_version"] == 3 and r["model"] == "m" and not r["dry"] for r in records)
    # A scheduled first step is handed nothing; the second, the first's result.
    assert records[0]["input"] is None
    handed = records[1]["input"]
    assert handed["source"] == TRIGGER_SOURCE_TASK
    assert handed["data"]["result"] == "Three bills and a letter from Ana."
    assert records[1]["input_summary"].startswith("Continued from Summarise my inbox")
    # What the model was given: nothing extra for step one; for step two the
    # hand-off, wrapped, and the tool gate armed.
    assert seen[0]["trigger"] is None
    wrapped = seen[1]["trigger"]
    assert wrapped["metadata"]["tool_gate_untrusted"] is True
    assert messages_contain_external_untrusted_context([wrapped])
    assert "Three bills and a letter from Ana." in wrapped["content"]
    # Both steps ran as "workflow · step", in the workflow's one chat.
    assert [x["name"] for x in seen] == ["Morning digest · Summarise my inbox",
                                         "Morning digest · Send me the summary"]
    assert seen[0]["session"] and seen[0]["session"] == seen[1]["session"]
    assert row(task_db, "wf").session_id == seen[0]["session"]
    # Step two's own delivery, and the run's own notification.
    notes = s.pop_notifications()
    assert {"task_name": "Morning digest · Send me the summary", "status": "success",
            "body": "You have 3 bills; Ana wrote."}.items() <= notes[0].items()
    assert [(n["task_name"], n["status"]) for n in notes[1:]] == [("Morning digest", "success")]
    # The run's own log: one line per step, and the arrow it followed.
    kinds = [(st["kind"], st.get("label") or st.get("detail")) for st in run["steps"]]
    assert ("node", "Summarise my inbox") in kinds and ("node", "Send me the summary") in kinds
    assert ("progress", "Continued to Send me the summary") in kinds
    assert not s._run_state, "every slot — the run's and each step's — is dropped"


@pytest.mark.asyncio
async def test_a_scheduled_run_never_reads_a_pinned_sample(task_db):
    """`P22-08`. A sample pinned on a step is for *Test this step* only."""
    pinned = node("n1", "Classify")
    pinned["pinned"] = build_trigger("event", "email_received", {"account": "PINNED"})
    seed_workflow(task_db, [pinned], trigger_type="event", trigger_event="email_received")
    s = recording_scheduler()
    real = build_trigger("event", "email_received", {"account": "work", "message_key": "7"})
    await s._execute_task("wf", trigger=real)
    assert s.calls[0]["trigger"]["data"] == {"account": "work", "message_key": "7"}


# ── how a run ends ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_failure_takes_the_if_it_fails_arrow_and_a_handled_failure_is_a_successful_run(task_db):
    seed_workflow(task_db, [node("n1", "Fetch", "action", action="daily_brief"),
                            node("n2", "Tell me it failed"),
                            node("n3", "Never")],
                  [arrow("n1", "n3"), arrow("n1", "n2", "error")])
    s = recording_scheduler({"Morning digest · Fetch": NodeResult("error", payload="IMAP refused")})
    await s._execute_task("wf")
    run = runs_of(task_db, "wf")[0]
    assert run["status"] == "success", "a failure routed to a step that works"
    records = records_of(task_db, run["id"])
    assert [(r["node_id"], r["status"], r["port"]) for r in records] == [
        ("n1", "error", "error"), ("n2", "success", None)]
    assert records[0]["error"] == "IMAP refused"
    handed = s.calls[1]["trigger"]["data"]
    assert (handed["status"], handed["result"]) == ("error", "IMAP refused")
    assert ("progress", "Failed, so continued to Tell me it failed") in [
        (st["kind"], st.get("detail")) for st in run["steps"]]
    assert [c["name"] for c in s.calls] == ["Morning digest · Fetch",
                                            "Morning digest · Tell me it failed"]


@pytest.mark.asyncio
async def test_an_unhandled_failure_fails_the_run_and_backs_off(task_db):
    """The task's own retry budget (`P8-32`) and backoff (`P15-08`) apply to a
    workflow unchanged (`D-2026-10-01-05` §1)."""
    seed_workflow(task_db, [node("n1", "Fetch", "action", action="daily_brief"),
                            node("n2", "Never")], [arrow("n1", "n2")], max_retries=2)
    s = recording_scheduler({"Morning digest · Fetch": NodeResult("error", payload="IMAP refused")})
    await s._execute_task("wf")
    run = runs_of(task_db, "wf")[0]
    assert (run["status"], run["error"]) == ("error", "IMAP refused")
    assert any("retrying (attempt 1 of 2)" in (st.get("detail") or "") for st in run["steps"])
    db = task_db()
    try:
        assert ts.consecutive_failures(db, "wf") == 1
    finally:
        db.close()
    assert row(task_db, "wf").next_run is not None
    assert [r["status"] for r in records_of(task_db, run["id"])] == ["error"]


@pytest.mark.asyncio
async def test_a_skip_ends_the_branch_and_the_run_is_skipped_not_deleted(task_db):
    seed_workflow(task_db, [node("n1", "Tidy", "action", action="tidy_sessions"),
                            node("n2", "Never")], [arrow("n1", "n2")])
    s = recording_scheduler({"Morning digest · Tidy": NodeResult("skipped", payload="Nothing to tidy")})
    await s._execute_task("wf")
    runs = runs_of(task_db, "wf")
    assert len(runs) == 1 and runs[0]["status"] == "skipped"
    assert runs[0]["result"] == "Nothing to tidy"
    assert [(r["status"], r["port"]) for r in records_of(task_db, runs[0]["id"])] == [("skipped", None)]
    assert len(s.calls) == 1


@pytest.mark.asyncio
async def test_a_step_that_asks_to_wait_ends_the_branch_and_never_deletes_the_run(task_db):
    """A task's `deferred` deletes its queued run row (the `TaskDeferred`
    branch). A workflow's run carries step records — CASCADE would take them
    — so a step that asks to wait is recorded `skipped`, with why."""
    seed_workflow(task_db, [node("n1", "Summarise"), node("n2", "Urgent?", "action",
                                                         action="check_email_urgency")],
                  [arrow("n1", "n2")])
    s = recording_scheduler({"Morning digest · Urgent?":
                             NodeResult("deferred", payload="Quiet hours", retry_after=60)})
    await s._execute_task("wf")
    runs = runs_of(task_db, "wf")
    assert len(runs) == 1 and runs[0]["status"] == "success", "one step worked"
    records = records_of(task_db, runs[0]["id"])
    assert [r["status"] for r in records] == ["success", "skipped"]
    assert records[1]["output"]["text"].startswith("It asked to wait")
    assert row(task_db, "wf").next_run is not None


@pytest.mark.asyncio
async def test_stop_leaves_the_running_step_aborted(task_db):
    seed_workflow(task_db, [node("n1", "Slow", "action", action="daily_brief"),
                            node("n2", "Never")], [arrow("n1", "n2")])
    started = asyncio.Event()

    async def slow(task, run_id):
        started.set()
        await asyncio.Event().wait()
    s = recording_scheduler({"Morning digest · Slow": slow})
    running = asyncio.create_task(s._execute_task("wf"))
    await asyncio.wait_for(started.wait(), 5)
    assert await s.stop_task("wf")
    await asyncio.wait_for(running, 5)
    run = runs_of(task_db, "wf")[0]
    assert run["status"] == "aborted" and run["error"] == ts.STOPPED_BY_USER
    records = records_of(task_db, run["id"])
    assert [(r["status"], r["error"]) for r in records] == [("aborted", ts.NODE_STOPPED)]
    assert len(s.calls) == 1


@pytest.mark.asyncio
async def test_the_time_limit_leaves_the_step_aborted_and_fails_the_run(task_db, monkeypatch):
    seed_workflow(task_db, [node("n1", "Slow", "action", action="daily_brief")])
    monkeypatch.setattr(ts, "task_timeout_seconds", lambda task: 0.2 if task.id == "wf" else 0)

    async def slow(task, run_id):
        await asyncio.Event().wait()
    s = recording_scheduler({"Morning digest · Slow": slow})
    await asyncio.wait_for(s._execute_task("wf"), 10)
    run = runs_of(task_db, "wf")[0]
    assert run["status"] == "error" and run["error"].startswith("Timed out after")
    assert [r["status"] for r in records_of(task_db, run["id"])] == ["aborted"]


@pytest.mark.asyncio
async def test_a_document_the_save_would_refuse_fails_the_run_in_the_same_words(task_db):
    nodes = [node("n1", "Backup"), node("n2", "Cleanup")]
    edges = [arrow("n1", "n2", "error"), arrow("n2", "n1")]
    seed_workflow(task_db, nodes, edges)
    s = recording_scheduler()
    await s._execute_task("wf")
    run = runs_of(task_db, "wf")[0]
    said = wd.validate_document(wd.parse_graph({"v": 1, "nodes": nodes, "edges": edges}),
                                owner=OWNER, tasks_by_id={}, crew_ids=(), owner_is_admin=False,
                                own_task_id="wf").sentence
    assert (run["status"], run["error"]) == ("error", said)
    assert records_of(task_db, run["id"]) == [] and s.calls == []


@pytest.mark.asyncio
async def test_a_trigger_with_no_document_says_so(task_db):
    seed_task(task_db, "orphan", "Orphan", task_type="workflow", prompt=None)
    s = recording_scheduler()
    await s._execute_task("orphan")
    run = runs_of(task_db, "orphan")[0]
    assert (run["status"], run["error"]) == ("error", ts.WORKFLOW_DOCUMENT_MISSING)


# ── the admin rule, at run and at dry run ───────────────────────────────────

@pytest.mark.asyncio
async def test_an_admin_only_step_is_refused_before_any_step_runs(task_db):
    seed_workflow(task_db, [node("n1", "Summarise"),
                            node("n2", "Deploy", "action", action="run_local", prompt="make deploy")],
                  [arrow("n1", "n2")])
    s = recording_scheduler()
    await s._execute_task("wf")
    run = runs_of(task_db, "wf")[0]
    assert run["status"] == "skipped"
    assert run["error"] == "Action 'run_local' requires admin privileges"
    assert row(task_db, "wf").status == "paused", "as a task's refusal does"
    assert s.calls == [] and records_of(task_db, run["id"]) == []


@pytest.mark.asyncio
async def test_a_dry_run_of_an_admin_only_step_is_declined_and_pauses_nothing(task_db):
    """`B1036`'s ruling, kept for a workflow: declined in the same words,
    nothing paused, no step planned — so a dry run reads no command."""
    seed_workflow(task_db, [node("n1", "Deploy", "action", action="run_local",
                                 prompt="make deploy")])
    s = recording_scheduler()
    run_id = await s.run_task_now("wf", dry=True)
    run = [r for r in runs_of(task_db, "wf") if r["id"] == run_id][0]
    assert run["status"] == "skipped"
    assert run["error"] == "Action 'run_local' requires admin privileges"
    assert run["result"].startswith(ts.DRY_RUN_MARK)
    assert "make deploy" not in json.dumps(run)
    assert row(task_db, "wf").status == "active"
    assert records_of(task_db, run_id) == [] and s.calls == []


# ── the dry run of a document ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_dry_run_plans_every_step_breadth_first_and_runs_none(task_db):
    seed_task(task_db, "t2", "Weekly report", status="paused")
    seed_workflow(task_db, [node("n1", "Summarise"),
                            node("n2", "Tidy", "action", action="tidy_sessions"),
                            node("n3", "Report", "run_task", task_id="t2"),
                            node("n4", "Look it up", "research", prompt="What changed?")],
                  [arrow("n1", "n3"), arrow("n1", "n2", "error"), arrow("n3", "n4")],
                  status="paused")
    s = recording_scheduler()
    before = row(task_db, "wf")
    run_id = await s.run_task_now("wf", dry=True)
    assert s.calls == [] and s.delivered == [] and s.pop_notifications() == []
    run = [r for r in runs_of(task_db, "wf") if r["id"] == run_id][0]
    assert run["status"] == "skipped" and run["result"].startswith(ts.DRY_RUN_HEADLINE)
    db = task_db()
    try:
        assert ts.is_dry_run(db.query(TaskRun).filter(TaskRun.id == run_id).first())
        entries = wr.dry_node_entries(db, run_id)
        assert wr.last_node_record(db, "wf", "n1") is None, "a plan is never a last run"
    finally:
        db.close()
    assert [(e["node_id"], e["when"], e["depth"]) for e in entries] == [
        ("n1", None, 0), ("n3", "success", 1), ("n2", "error", 1), ("n4", "success", 2)]
    plan = {e["node_id"]: [st["detail"] for st in e["steps"]] for e in entries}
    assert "It would: deletes data inside Pantheon" in plan["n2"]
    assert "Where the result would go: only to the next step" in plan["n1"]
    assert plan["n3"][0] == "Would run the task “Weekly report”, as its own run with its own history."
    assert "It is paused, so a real run would not start it." in plan["n3"]
    assert all(e["declined"] is None for e in entries)
    lines = run["result"].splitlines()
    assert lines[1].startswith("Step 1, “Summarise”:")
    assert lines[3].startswith("Step 3, “Tidy” (if the step before fails):")
    assert lines[-1] == "It is paused, so a real run would not start it."
    after = row(task_db, "wf")
    assert (after.last_run, after.next_run, after.run_count, after.status) == (
        before.last_run, before.next_run, before.run_count, "paused")
    assert runs_of(task_db, "t2") == [], "a planned Run task step runs nothing"


# ── Run task ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_run_task_step_runs_its_task_as_itself_and_lets_its_claim_go(task_db):
    seed_task(task_db, "t2", "Weekly report")
    seed_workflow(task_db, [node("n1", "Summarise"), node("n2", "Report", "run_task", task_id="t2")],
                  [arrow("n1", "n2")])
    s = recording_scheduler({"Weekly report": "Report: all quiet."})
    handles = []
    original = s._execute_task

    async def watch(task_id, **kw):
        handles.append((task_id, s._task_handles.get(task_id), kw.get("register_handle")))
        return await original(task_id, **kw)
    s._execute_task = watch
    await s._execute_task("wf")
    run = runs_of(task_db, "wf")[0]
    assert run["status"] == "success" and run["result"] == "Report: all quiet."
    target_runs = runs_of(task_db, "t2")
    assert [r["status"] for r in target_runs] == ["success"], "its own run, its own history"
    assert target_runs[0]["steps"][0]["detail"].startswith("Continued from Summarise")
    assert "t2" not in s._executing and "wf" not in s._executing
    assert ("t2", None, False) in handles, "stopping the target cannot cancel the workflow"
    assert [r["output"]["text"] for r in records_of(task_db, run["id"])][-1] == "Report: all quiet."


@pytest.mark.asyncio
async def test_a_busy_run_task_target_is_said_and_not_dropped(task_db):
    seed_task(task_db, "t2", "Weekly report")
    seed_workflow(task_db, [node("n1", "Report", "run_task", task_id="t2")])
    s = recording_scheduler()
    s._executing.add("t2")          # already running somewhere else
    await s._execute_task("wf")
    run = runs_of(task_db, "wf")[0]
    assert (run["status"], run["error"]) == (
        "error", "Did not run “Weekly report”: it was already running")
    assert runs_of(task_db, "t2") == []
    assert "t2" in s._executing, "someone else's claim is left alone"


@pytest.mark.asyncio
async def test_a_workflow_is_not_a_run_task_target(task_db):
    seed_workflow(task_db, [node("n1", "Other")], task_id="w2", name="Other flow")
    seed_workflow(task_db, [node("n1", "Run the other", "run_task", task_id="w2")])
    s = recording_scheduler()
    await s._execute_task("wf")
    run = runs_of(task_db, "wf")[0]
    assert run["status"] == "error" and "which is a workflow" in run["error"]
    assert runs_of(task_db, "w2") == []


# ── the model slot and notifications ────────────────────────────────────────

@pytest.mark.parametrize("nodes,needs", [
    ([node("n1", "A", "action", action="tidy_sessions"),
      node("n2", "B", "action", action="tidy_research")], False),
    ([node("n1", "A", "action", action="tidy_sessions"),
      node("n2", "B", "action", action="summarize_emails")], True),
    ([node("n1", "A", "action", action="tidy_sessions"), node("n2", "B")], True),
    ([node("n1", "A", "research")], True),
    ([node("n1", "A", "run_task", task_id="t2")], True),
])
def test_a_workflow_waits_for_the_model_slot_only_if_a_step_may_call_a_model(task_db, nodes, needs):
    seed_workflow(task_db, nodes)
    assert TaskScheduler(None)._task_needs_model_slot("wf") is needs


def test_a_workflow_notifies_on_success_as_a_prompt_task_does():
    s = TaskScheduler(None)
    for task_type, told in (("workflow", True), ("llm", True), ("action", False)):
        task = ScheduledTask(id=task_type, name=task_type, owner=OWNER, task_type=task_type,
                             notifications_enabled=True)
        assert s._notify_run_outcome(task, "success", quiet_for_actions=True) is told, task_type
    assert ts.NOTIFY_ON_SUCCESS_TASK_TYPES == ("llm", "research", "workflow")


# ── Test this step (`P22-08`) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_testing_a_step_runs_it_alone_and_writes_nothing(task_db, monkeypatch):
    """No run, no step record, no delivery, no notification, no next step —
    and it never waits on the quiet gate (both waits raise if called)."""
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "1")

    async def never(*a, **k):
        raise AssertionError("a step test waited for Pantheon to be quiet")
    monkeypatch.setattr(ig, "wait_for_interactive_quiet", never)
    monkeypatch.setattr(ig, "wait_for_chat_quiet", never)
    seed_workflow(task_db, [node("n1", "Classify", output_target="notification"),
                            node("n2", "Never")], [arrow("n1", "n2")],
                  trigger_type="event", trigger_event="email_received")
    s = TaskScheduler(None)
    seen = []

    async def agent_loop(endpoint_url, model, task, session_id, **kw):
        seen.append((task.name, kw.get("trigger_context_msg"), s._run_waits_for(kw.get("run_id"))))
        return "Looks like a bill."
    s._run_agent_loop = agent_loop
    trigger = row(task_db, "wf")
    sample = build_trigger("event", "email_received", {"account": "work", "message_key": "9"})
    graph = wd.parse_graph(json.loads(_graph_text(task_db)))
    step = graph["nodes"][0]
    step["config"].update(model="m", endpoint_url="http://127.0.0.1:9/v1",
                          prompt="Classify it, edited and not yet saved.")
    out = await s.test_workflow_node(trigger, "Morning digest", step, input_envelope=sample)
    assert set(out) == {"status", "text", "data", "steps", "model", "took_ms"}
    assert (out["status"], out["text"], out["model"]) == ("success", "Looks like a bill.", "m")
    assert seen[0][0] == "Morning digest · Classify" and seen[0][2] is None
    assert '"message_key": "9"' in seen[0][1]["content"]
    assert runs_of(task_db, "wf") == []
    db = task_db()
    try:
        assert db.query(TaskRunNode).count() == 0
    finally:
        db.close()
    assert s.pop_notifications() == [], "a test delivers nothing"
    assert len(seen) == 1, "and continues to nothing"
    assert not s._run_state


def _graph_text(factory):
    db = factory()
    try:
        return db.query(Workflow).filter(Workflow.task_id == "wf").first().graph
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_step_test_that_raises_or_overruns_answers_an_error(task_db):
    seed_workflow(task_db, [node("n1", "Fetch", "action", action="daily_brief")])

    async def slow(task, run_id):
        await asyncio.Event().wait()
    s = recording_scheduler({"Morning digest · Fetch": slow})
    out = await s.test_workflow_node(row(task_db, "wf"), "Morning digest",
                                     node("n1", "Fetch", "action", action="daily_brief"),
                                     timeout=0.2)
    assert out["status"] == "error" and out["text"].startswith("Timed out")
    assert not s._run_state
