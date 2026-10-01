# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1036` — a dry run of a paused task planned nothing, and notified.

**Measured on the tree before this file** (and by both agents who filed the
row): `_execute_task_locked` returned at its `status != "active"` check, above
the dry branch, so `POST /run?dry=true` on a paused task recorded a `skipped`
run with `error = "Task no longer active (status=paused)"`, left `result` at
the "Queued — waiting for a free slot…" placeholder, and queued a `skipped`
NOTIFICATION — for pressing *Show me what this would do*. The admin-only branch
beside it did worse on the dry path: `record_admin_refusal` paused the task and
moved its `last_run`. The cases below fail on that tree.

The fix is in the engine, where the promise is kept: the dry branch comes
first, a paused (or spent one-off) task is planned and its plan says a real run
would not start it, a deleted task and an admin-only task of a non-admin owner
are declined in words without touching the task, and no dry run tells anyone.

Real scheduler, real route, real tool, real SQLite (`Law 20`); every executor,
delivery and chain is a recorder that must stay empty.
"""

import asyncio
import json
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.builtin_actions as ba  # noqa: E402
import src.event_bus as event_bus  # noqa: E402
import src.task_scheduler as ts  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import DRY_RUN_HEADLINE, TaskScheduler  # noqa: E402
from src.tools.system import do_manage_tasks  # noqa: E402

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}

PAUSED_LINE = "It is paused, so a real run would not start it."


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'switched-off.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


@pytest.fixture()
def calls(monkeypatch):
    seen = []
    for name in list(ba.BUILTIN_ACTIONS):
        async def recorder(_name=name, **kwargs):
            seen.append(("action", _name))
            return "I RAN", True
        monkeypatch.setitem(ba.BUILTIN_ACTIONS, name, recorder)
    return seen


@pytest.fixture()
def scheduler(monkeypatch, calls):
    """The real scheduler, with its real notification queue — the thing a dry
    run must leave empty — and every way out of a run recorded."""
    s = TaskScheduler(None)

    def recorded(label):
        async def _rec(*a, **k):
            calls.append((label, a[:1]))
            return "I RAN"
        return _rec

    s._execute_llm_task = recorded("llm")
    s._execute_research_task = recorded("research")
    s._deliver_task_result = recorded("deliver")
    s._run_chained = recorded("chain")
    s._log_to_assistant = lambda *a, **k: calls.append(("chat", a[:1]))
    monkeypatch.setattr(event_bus, "_task_scheduler", s)
    return s


def _seed(factory, *, status="active", action="tidy_sessions", owner=None,
          task_type="action", prompt=None):
    db = factory()
    try:
        db.add(ScheduledTask(
            id="t1", owner=owner, name="Draft digest", prompt=prompt,
            task_type=task_type, action=action, trigger_type="schedule",
            schedule="daily", scheduled_time="09:00", status=status,
            output_target="session", run_count=4))
        db.commit()
    finally:
        db.close()


def _task(factory, task_id="t1"):
    db = factory()
    try:
        t = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        return None if t is None else {
            "status": t.status, "last_run": t.last_run, "next_run": t.next_run,
            "run_count": t.run_count}
    finally:
        db.close()


def _runs(factory, task_id="t1"):
    db = factory()
    try:
        return [{"id": r.id, "status": r.status, "result": r.result, "error": r.error,
                 "steps": json.loads(r.steps) if r.steps else []}
                for r in db.query(TaskRun).filter(TaskRun.task_id == task_id).all()]
    finally:
        db.close()


def _privileges(monkeypatch, granted):
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", lambda owner: granted)


# ── a switched-off task is planned ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_paused_task_is_planned_and_its_plan_says_a_real_run_would_not_start_it(
        task_db, scheduler, calls):
    _seed(task_db, status="paused")
    before = _task(task_db)

    run_id = await scheduler.run_task_now("t1", dry=True)

    (run,) = _runs(task_db)
    assert run["id"] == run_id and run["status"] == "skipped"
    lines = [s["detail"] for s in run["steps"]]
    assert {s["kind"] for s in run["steps"]} == {"dry-run"}
    assert lines[0] == DRY_RUN_HEADLINE
    assert any(line.startswith("Would run: tidy_sessions") for line in lines), lines
    assert lines[-1] == PAUSED_LINE
    assert run["result"] == "\n".join(lines)
    assert run["error"] is None
    assert _task(task_db) == before, "the dry run changed the task"
    assert calls == [] and scheduler._pending_notifications == []


def test_the_rows_verify_through_the_route(task_db, scheduler, calls, monkeypatch):
    """`Verify:` someone presses the dry run on a switched-off draft and reads
    its plan, with no notification — through `POST /run?dry=true`."""
    import routes.task.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    app = FastAPI()
    app.include_router(task_routes.setup_task_routes(scheduler))
    _seed(task_db, status="paused", task_type="llm", action=None,
          prompt="Summarise my inbox")

    r = TestClient(app).post("/api/tasks/t1/run?dry=true")

    assert r.status_code == 200, r.text
    run = r.json()["run"]
    assert run["status"] == "skipped"
    details = [s["detail"] for s in run["steps"]]
    assert details[0] == DRY_RUN_HEADLINE
    assert "Would send this task's prompt to a model, with tools." in details
    assert details[-1] == PAUSED_LINE
    assert scheduler._pending_notifications == []
    assert calls == []


@pytest.mark.asyncio
async def test_the_assistant_is_told_the_plan_of_a_paused_task(task_db, scheduler, calls):
    """`manage_tasks` `dry_run` answered *"'X' was not planned: Task no longer
    active (status=paused)"*; it reads the plan back now."""
    _seed(task_db, status="paused")

    out = await do_manage_tasks(json.dumps({"action": "dry_run", "task_id": "t1"}))

    assert out["exit_code"] == 0, out
    assert out["response"].startswith(f"Task 'Draft digest': {DRY_RUN_HEADLINE}")
    assert out["response"].endswith(PAUSED_LINE)
    assert scheduler._pending_notifications == [] and calls == []


@pytest.mark.asyncio
async def test_a_one_off_that_already_ran_is_planned_and_says_so(task_db, scheduler, calls):
    _seed(task_db, status="completed")

    await scheduler.run_task_now("t1", dry=True)

    (run,) = _runs(task_db)
    assert run["steps"][-1]["detail"] == (
        "It was a one-off and has already run, so a real run would not start it.")
    assert _task(task_db)["status"] == "completed"


@pytest.mark.asyncio
async def test_an_active_tasks_plan_is_what_it_was(task_db, scheduler, calls):
    """`Law 1`. Nothing added to the plan of a task that would run."""
    _seed(task_db)

    await scheduler.run_task_now("t1", dry=True)

    (run,) = _runs(task_db)
    details = [s["detail"] for s in run["steps"]]
    assert details[0] == DRY_RUN_HEADLINE
    assert details[-1] == "Where the result would go: session"


# ── what is declined is declined in words, and changes nothing ─────────────

@pytest.mark.asyncio
async def test_an_admin_only_task_is_declined_without_pausing_it(
        task_db, scheduler, calls, monkeypatch):
    """The engine's own answer on the dry path, met when the privilege goes
    between a door's check and the engine's. It used to PAUSE the task and move
    `last_run` (`record_admin_refusal`)."""
    _privileges(monkeypatch, False)
    _seed(task_db, action="ssh_command", prompt="reboot", owner="bob")
    before = _task(task_db)

    await scheduler.run_task_now("t1", dry=True)

    (run,) = _runs(task_db)
    assert run["status"] == "skipped"
    assert run["error"] == "Action 'ssh_command' requires admin privileges"
    # Led by the dry-run mark (`B1054`), so it is never this task's last run.
    assert run["result"] == "Dry run — not planned: Action 'ssh_command' requires admin privileges"
    assert run["steps"] == [], "an admin-only task's command was shown to its non-admin owner"
    assert _task(task_db) == before, "the dry run paused the task"
    assert scheduler._pending_notifications == [] and calls == []


def _deleted_mid_run(factory):
    """A task deleted between the button and the engine. `task_runs.task_id`
    cascades (`ondelete="CASCADE"`, enforced), so its queued run goes with it."""
    _seed(factory)
    db = factory()
    try:
        db.add(TaskRun(id="r1", task_id="t1", status="queued",
                       result="Queued — waiting for a free slot…"))
        db.commit()
        db.delete(db.query(ScheduledTask).filter(ScheduledTask.id == "t1").first())
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_deleted_task_is_declined_and_nothing_is_written(task_db, scheduler, calls):
    _deleted_mid_run(task_db)

    await scheduler._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False, dry=True)

    assert _runs(task_db) == [] and _task(task_db) is None
    assert ts.dry_run_declined(None) == "Task no longer active (status=deleted)"
    assert scheduler._pending_notifications == [] and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["active", "paused", "completed", "admin-only", "deleted"])
async def test_no_dry_run_notifies(task_db, scheduler, calls, monkeypatch, case):
    """The row's second half, over every way a dry run can end."""
    if case == "admin-only":
        _privileges(monkeypatch, False)
        _seed(task_db, action="ssh_command", prompt="reboot", owner="bob")
    elif case != "deleted":
        _seed(task_db, status=case)
    if case == "deleted":
        _deleted_mid_run(task_db)
        await scheduler._execute_task_locked(
            "t1", "r1", gate_foreground=False, release_executing=False, dry=True)
    else:
        await scheduler.run_task_now("t1", dry=True)
    await asyncio.sleep(0)

    assert scheduler._pending_notifications == []
    assert calls == []


# ── a real run of a paused task is the run it was ──────────────────────────

@pytest.mark.asyncio
async def test_a_real_run_of_a_paused_task_still_skips_and_tells_but_says_why_in_result(
        task_db, scheduler, calls):
    """`Law 1` for the real path (`B112`'s policy: a skip that leaves the task
    stopped is told). One change: `result` carries the reason rather than the
    placeholder the run was created with, which History shows first."""
    _seed(task_db, status="paused")

    await scheduler.run_task_now("t1")
    for _ in range(20):
        await asyncio.sleep(0)

    (run,) = _runs(task_db)
    assert run["status"] == "skipped"
    assert run["error"] == run["result"] == "Task no longer active (status=paused)"
    assert [n["status"] for n in scheduler._pending_notifications] == ["skipped"]
    assert calls == []
