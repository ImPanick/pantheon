# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1054` — a dry run was a step's "Last run"; `B1043` (its server note) — and
reading that last run loaded every run of every task.

**Measured before this file** (`/tmp/scratch-wb-runs/probe_last_run.py`, the
real route on a real SQLite file): after a dry run, `GET
/api/tasks?include_last_run=true` served the task `last_run_status:
"skipped"` with the plan as its result — verify-a saw a step that read
"✗ Last run: Failed" read "· Last run: Skipped" after one *Show me what this
would do*. And `include_last_run` read `t.runs[0]` through a lazy relationship
ordered by `started_at`: 20 tasks with 50 runs each cost 21 statements and
loaded 1,001 `TaskRun` rows to serve 20; 40 × 200 cost 41 and 8,001.

Now a dry run — a plan, or a dry run the engine declined — is never a last
run, and the list reads every task's last real run in one statement that
loads three short columns per task. Real route, real scheduler writing the
dry runs, real SQLite (`Law 20`); statements counted on the engine itself.
"""

import json
import sys
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.builtin_actions as ba  # noqa: E402
import src.task_scheduler as ts  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}

T0 = datetime(2026, 9, 1, 9, 0)


@pytest.fixture()
def engine_and_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'last-run.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return engine, factory


@pytest.fixture()
def task_db(engine_and_db):
    return engine_and_db[1]


@pytest.fixture()
def client(task_db, monkeypatch):
    import routes.task.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    for name in list(ba.BUILTIN_ACTIONS):
        async def recorder(**kwargs):
            raise AssertionError("a dry run ran an action")
        monkeypatch.setitem(ba.BUILTIN_ACTIONS, name, recorder)
    scheduler = TaskScheduler(None)

    async def _ensure_defaults(owner):
        return None
    scheduler.ensure_defaults = _ensure_defaults
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = "alice"
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(scheduler))
    return TestClient(app)


def _task(factory, task_id, *, name=None, action="tidy_sessions", prompt=None):
    db = factory()
    try:
        db.add(ScheduledTask(
            id=task_id, owner="alice", name=name or task_id, task_type="action",
            action=action, prompt=prompt, trigger_type="webhook", status="active",
            output_target="session"))
        db.commit()
    finally:
        db.close()


def _run(factory, task_id, status, minutes, *, result=None, error=None, steps=None):
    db = factory()
    try:
        db.add(TaskRun(id=str(uuid.uuid4()), task_id=task_id, status=status,
                       started_at=T0 + timedelta(minutes=minutes),
                       result=result, error=error, steps=steps))
        db.commit()
    finally:
        db.close()


def _listed(client):
    r = client.get("/api/tasks?include_last_run=true")
    assert r.status_code == 200, r.text
    return {t["id"]: t for t in r.json()["tasks"]}


def _mark(row):
    return (row.get("last_run_status"), row.get("last_run_result"))


# ── B1054 ──────────────────────────────────────────────────────────────────

def test_a_dry_run_leaves_a_failed_steps_last_run_as_it_was(client, task_db):
    """The row's `Verify:`, through the doors the canvas uses: a step whose
    last real run failed, then *Show me what this would do* (the real
    `POST /run?dry=true`), and the list still says it failed."""
    _task(task_db, "bk", name="Nightly backup")
    _run(task_db, "bk", "error", 0, result="RuntimeError: No model/endpoint configured",
         error="RuntimeError: No model/endpoint configured")
    before = _mark(_listed(client)["bk"])
    assert before == ("error", "RuntimeError: No model/endpoint configured")

    plan = client.post("/api/tasks/bk/run?dry=true")
    assert plan.status_code == 200 and plan.json()["run"]["status"] == "skipped"

    assert _mark(_listed(client)["bk"]) == before


def test_a_step_with_only_dry_runs_has_not_run_yet(client, task_db):
    _task(task_db, "new", name="Draft")

    for _ in range(2):
        assert client.post("/api/tasks/new/run?dry=true").status_code == 200

    row = _listed(client)["new"]
    assert "last_run_status" not in row and "last_run_result" not in row


def test_a_dry_run_the_engine_declined_is_not_a_last_run_either(
        client, task_db, monkeypatch):
    """Declined at the engine (the privilege gone between the route's check
    and the engine's): its row is led by the dry-run mark too."""
    import src.task_action_policy as policy
    monkeypatch.setattr(policy, "owner_has_admin_task_privileges", lambda o: True)
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", lambda o: False)
    _task(task_db, "ssh", action="ssh_command", prompt="reboot")
    _run(task_db, "ssh", "success", 0, result="rebooted")

    assert client.post("/api/tasks/ssh/run?dry=true").json()["run"]["status"] == "skipped"

    assert _mark(_listed(client)["ssh"]) == ("success", "rebooted")


def test_skips_and_stops_that_are_not_dry_runs_still_count(client, task_db):
    """`Law 1`. A housekeeping "nothing to do" (`TaskNoop`, `skipped`) and a
    stop (`aborted`) are real runs and stay a task's last run."""
    _task(task_db, "noop")
    _run(task_db, "noop", "error", 0, error="boom")
    _run(task_db, "noop", "skipped", 5, result="No new email to tidy")
    _task(task_db, "stopped")
    _run(task_db, "stopped", "success", 0, result="ok")
    _run(task_db, "stopped", "aborted", 5, result="Stopped by user", error="Stopped by user")

    listed = _listed(client)
    assert _mark(listed["noop"]) == ("skipped", "No new email to tidy")
    assert _mark(listed["stopped"]) == ("aborted", "Stopped by user")


def test_the_last_run_result_is_clipped_as_it_was(client, task_db):
    """`Law 1`: 500 characters of `result`, or of `error` when there is none."""
    _task(task_db, "long")
    _run(task_db, "long", "success", 0, result="x" * 2000)
    _task(task_db, "err")
    _run(task_db, "err", "error", 0, result="", error="e" * 900)

    listed = _listed(client)
    assert listed["long"]["last_run_result"] == "x" * 500
    assert listed["err"]["last_run_result"] == "e" * 500


def test_without_include_last_run_nothing_is_added(client, task_db):
    _task(task_db, "t")
    _run(task_db, "t", "success", 0, result="ok")

    row = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}["t"]
    assert "last_run_status" not in row


# ── B1043 ──────────────────────────────────────────────────────────────────

def test_the_list_reads_every_last_run_in_one_statement(client, engine_and_db):
    """20 tasks with 30 runs each, a dry run newest on half of them. One
    statement reads `task_runs`, and no whole `TaskRun` row is loaded."""
    engine, factory = engine_and_db
    for i in range(20):
        _task(factory, f"t{i:02d}")
        for j in range(30):
            _run(factory, f"t{i:02d}", "error" if j == 29 else "success", j,
                 result=f"run {j}", steps=json.dumps([{"kind": "progress", "detail": "x" * 300}] * 5))
        if i % 2:
            _run(factory, f"t{i:02d}", "skipped", 60,
                 result=ts.DRY_RUN_HEADLINE + "\nWould run: tidy_sessions")

    statements = []
    loaded = []

    def _count(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    def _load(target, context):
        loaded.append(target.id)

    event.listen(engine, "before_cursor_execute", _count)
    event.listen(TaskRun, "load", _load)
    try:
        listed = _listed(client)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
        event.remove(TaskRun, "load", _load)

    assert len([s for s in statements if "task_runs" in s]) == 1, statements
    assert loaded == []
    assert {t: _mark(row) for t, row in listed.items()} == {
        f"t{i:02d}": ("error", "run 29") for i in range(20)}


def test_a_tie_on_started_at_takes_one_run_not_two(client, task_db):
    """Written down rather than left to row order: the highest id wins."""
    _task(task_db, "tie")
    db = task_db()
    try:
        db.add(TaskRun(id="a", task_id="tie", status="success", started_at=T0, result="first"))
        db.add(TaskRun(id="b", task_id="tie", status="error", started_at=T0, result="second"))
        db.commit()
    finally:
        db.close()

    assert _mark(_listed(client)["tie"]) == ("error", "second")


def test_a_dry_run_at_the_same_instant_as_a_real_run_does_not_win_the_tie(client, task_db):
    _task(task_db, "same")
    db = task_db()
    try:
        db.add(TaskRun(id="real", task_id="same", status="error", started_at=T0, result="failed"))
        db.add(TaskRun(id="zzz-dry", task_id="same", status="skipped", started_at=T0,
                       result=ts.DRY_RUN_HEADLINE + "\nWould run: tidy_sessions"))
        db.commit()
    finally:
        db.close()

    assert _mark(_listed(client)["same"]) == ("error", "failed")
