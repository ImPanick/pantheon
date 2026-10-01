# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1055` — a failed run showed "Starting…" and handed "Starting…" to its
failure branch.

**Measured** by verify-a on the merged tree, and again before this file on the
real `_execute_task_locked`: a Prompt task that raised `RuntimeError: No
model/endpoint configured` was recorded `status=error`, `error=<that>`,
`result="Starting…"` — the placeholder written when the run flipped to
running. History draws `result` ahead of `error`, so it read "Failed ·
Starting…"; and `_handoff_from` hands `result` on, so the failure branch's
cause line read `status=error, result=Starting…` — the step built to say
"the backup failed" was not told why.

Real scheduler, real chain (`_advance_chain` → `_run_chained` →
`_execute_task`), real history route, real SQLite (`Law 20`). The gate is off
here; `tests/test_run_now_runs_while_pantheon_is_open.py` holds the gate.
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
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}

WHY = "RuntimeError: No model/endpoint configured"


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "0")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'why.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _seed(factory, *, head_type="llm", action=None):
    db = factory()
    try:
        db.add(ScheduledTask(
            id="msg", owner=None, name="Message me", prompt="Tell me the backup failed.",
            task_type="llm", trigger_type="webhook", status="active", output_target="session"))
        db.add(ScheduledTask(
            id="bk", owner=None, name="Nightly backup", prompt="Back up the notes folder.",
            task_type=head_type, action=action, trigger_type="webhook", status="active",
            output_target="session"))
        db.commit()
        db.query(ScheduledTask).filter(ScheduledTask.id == "bk").first().else_task_id = "msg"
        db.commit()
    finally:
        db.close()


def _runs(factory, task_id):
    db = factory()
    try:
        return [{"status": r.status, "result": r.result, "error": r.error,
                 "steps": json.loads(r.steps) if r.steps else []}
                for r in db.query(TaskRun).filter(TaskRun.task_id == task_id).all()]
    finally:
        db.close()


def _scheduler(seen, *, fail_with=RuntimeError("No model/endpoint configured")):
    """The real scheduler. The head's model executor raises as a Pantheon with
    no model does; the successor's records what fired it."""
    s = TaskScheduler(None)

    async def _llm(task, db, run_id=None):
        if task.id == "bk":
            raise fail_with
        seen.append(s.run_trigger(run_id))
        return "told"

    s._execute_llm_task = _llm
    s._log_to_assistant = lambda *a, **k: None

    async def _deliver(*a, **k):
        return None
    s._deliver_task_result = _deliver
    return s


async def _until(predicate, what):
    for _ in range(400):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"never happened: {what}")


@pytest.mark.asyncio
async def test_a_run_that_raised_says_why_in_its_result(task_db):
    _seed(task_db)
    seen = []
    s = _scheduler(seen)

    await s.run_task_now("bk")
    await _until(lambda: _runs(task_db, "msg") and _runs(task_db, "msg")[0]["status"] == "success",
                 "the failure branch ran")

    (head,) = _runs(task_db, "bk")
    assert head["status"] == "error"
    assert head["error"] == head["result"] == WHY


@pytest.mark.asyncio
async def test_the_failure_branch_is_handed_the_reason(task_db):
    """`P8-29`'s hand-off, the second half of the row's `Verify:`: the step the
    failure leads to is told why, in its cause line and in what its model is
    given (the run's trigger envelope)."""
    _seed(task_db)
    seen = []
    s = _scheduler(seen)

    await s.run_task_now("bk")
    await _until(lambda: _runs(task_db, "msg") and _runs(task_db, "msg")[0]["status"] == "success",
                 "the failure branch finished")

    (handoff,) = seen
    assert handoff["data"]["status"] == "error"
    assert handoff["data"]["result"] == WHY
    (branch,) = _runs(task_db, "msg")
    cause = branch["steps"][0]
    assert cause["kind"] == "trigger"
    assert f"result={WHY}" in cause["detail"]
    assert "Starting" not in cause["detail"]


def test_history_shows_the_reason(task_db, monkeypatch):
    """The run as `GET /api/tasks/{id}/runs` serves it to History."""
    import routes.task.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    _seed(task_db)
    seen = []
    s = _scheduler(seen)

    async def _go():
        await s.run_task_now("bk")
        await _until(lambda: seen, "the failure branch ran")
    asyncio.run(_go())

    app = FastAPI()
    app.include_router(task_routes.setup_task_routes(s))
    (run,) = TestClient(app).get("/api/tasks/bk/runs").json()["runs"]
    assert run["status"] == "error" and run["result"] == WHY


@pytest.mark.asyncio
async def test_output_made_before_a_failed_delivery_is_kept(task_db):
    """`Law 1`. A run that produced its output and then failed to deliver it
    keeps the output as its result; the error says what failed."""
    _seed(task_db)
    s = TaskScheduler(None)

    async def _llm(task, db, run_id=None):
        return "Backed up 3 files."
    s._execute_llm_task = _llm
    s._log_to_assistant = lambda *a, **k: None

    async def _deliver(*a, **k):
        raise RuntimeError("the mail server refused it")
    s._deliver_task_result = _deliver
    s._run_chained = lambda *a, **k: asyncio.sleep(0)

    db = task_db()
    try:
        db.add(TaskRun(id="r1", task_id="bk", status="queued"))
        db.commit()
    finally:
        db.close()
    await s._execute_task_locked("bk", "r1", gate_foreground=False, release_executing=False)

    (head,) = _runs(task_db, "bk")
    assert head["status"] == "error"
    assert head["result"] == "Backed up 3 files."
    assert head["error"] == "RuntimeError: the mail server refused it"


@pytest.mark.asyncio
async def test_a_returned_failure_is_what_it_was(task_db, monkeypatch):
    """`Law 1`. An action that RETURNS a failure already put its words in
    `result`; nothing about that path moves."""
    _seed(task_db, head_type="action", action="tidy_sessions")

    async def broke(**kwargs):
        return "the disk is full", False
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", broke)
    seen = []
    s = _scheduler(seen)

    await s.run_task_now("bk")
    await _until(lambda: seen, "the failure branch ran")

    (head,) = _runs(task_db, "bk")
    assert head["status"] == "error"
    assert head["result"] == head["error"] == "the disk is full"
    assert seen[0]["data"]["result"] == "the disk is full"
