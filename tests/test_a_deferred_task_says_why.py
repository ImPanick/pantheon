# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B675` — somebody whose automation has not run for three hours can tell
that it deferred, and until when.

**Measured before this file:** a run that raised `TaskDeferred` (an action's
quiet window, an agent waiting for capacity) had its queued `TaskRun` row
deleted — deliberately, so a quiet-window defer does not fill Activity — and
only `next_run` moved. No field anywhere said it deferred or why (`grep` of
`src`, `routes` and `static` for one: empty). A task that deferred on every
tick was, from every surface, a task that simply was not running.

Now the task keeps its last deferral — until when, and the action's own words
— served on the task (`GET /api/tasks`) and said on the card's next-run line,
until a run of it next starts. Driven (`Law 20`): the real scheduler from
`_execute_task` (the action's far end raising the deferral, as the skills
audit does), the real route, the real `static/js/tasks.js` card under node,
and the real migration against a table that never had the columns.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core.database as cdb  # noqa: E402
import src.builtin_actions as ba  # noqa: E402
from tests.helpers.walker_harness import make_db  # noqa: E402
from test_show_me_what_this_would_do_js import _case, sandbox  # noqa: E402,F401
from test_a_task_says_when_and_how_long import _columns, _legacy_db  # noqa: E402

WHY = "audit model m was used 30s ago; waiting for quiet window"


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import routes.task.task_routes as task_routes
    from tests.helpers.signed_in import signed_in
    from core.database import ScheduledTask
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "defer.db")
    monkeypatch.setattr(task_routes, "SessionLocal", factory)
    signed_in(monkeypatch, tmp_path / "auth", admin="alice", members=())
    outcome = {"defer": True}

    async def audit(**kwargs):
        if outcome["defer"]:
            raise ba.TaskDeferred(WHY, delay_seconds=20 * 60)
        return "Audited 2 skills", True
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "audit_skills", audit)
    db = factory()
    db.add(ScheduledTask(id="audit", owner="alice", name="Skills Audit", task_type="action",
                         action="audit_skills", trigger_type="schedule", schedule="cron",
                         cron_expression="0 * * * *", status="active",
                         output_target="none", notifications_enabled=False))
    db.commit()
    db.close()
    s = TaskScheduler(None)
    s._log_to_assistant = lambda *a, **k: None
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = "alice"
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(s))
    return factory, s, TestClient(app), outcome


def _row(factory):
    from core.database import ScheduledTask
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == "audit").first()
    finally:
        db.close()


def _runs(factory):
    from core.database import TaskRun
    db = factory()
    try:
        return [r.status for r in db.query(TaskRun).all()]
    finally:
        db.close()


def test_a_deferred_run_says_it_deferred_and_until_when(world, sandbox):
    import src.task_scheduler as ts
    factory, s, client, outcome = world
    before = ts._utcnow()
    asyncio.run(s._execute_task("audit"))

    assert _runs(factory) == [], "a deferral is still not an Activity row (`Law 1`)"
    row = _row(factory)
    assert row.deferred_until is not None and row.deferred_until == row.next_run
    assert timedelta(minutes=19) < row.deferred_until - before < timedelta(minutes=21)
    assert row.defer_reason == WHY

    served = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}["audit"]
    assert served["defer_reason"] == WHY
    assert served["deferred_until"] == served["next_run"] == row.deferred_until.isoformat() + "Z"

    # Where the person looks: the card's next-run line.
    out = _case(sandbox, {"tasks": [served]}, """
        const body = await openTasksList();
        console.log(JSON.stringify({ meta: body.querySelector('.task-card').querySelector('.memory-item-meta').textContent }));
    """)
    assert "Deferred until " in out["meta"] and out["meta"].endswith(f"(in 20m): {WHY}"), out["meta"]
    assert "Next:" not in out["meta"]

    # The next run that goes ends it.
    outcome["defer"] = False
    asyncio.run(s._execute_task("audit"))
    assert _runs(factory) == ["success"]
    row = _row(factory)
    assert row.deferred_until is None and row.defer_reason is None
    served = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}["audit"]
    out = _case(sandbox, {"tasks": [served]}, """
        const body = await openTasksList();
        console.log(JSON.stringify({ meta: body.querySelector('.task-card').querySelector('.memory-item-meta').textContent }));
    """)
    assert "Deferred" not in out["meta"] and "Next: in" in out["meta"], out["meta"]


def test_an_old_install_gains_the_two_columns(monkeypatch, tmp_path):
    path = _legacy_db(tmp_path)
    assert "deferred_until" not in _columns(path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_scheduled_task_execution_columns()
    cols = _columns(path)
    assert "deferred_until" in cols and "defer_reason" in cols
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT deferred_until, defer_reason FROM scheduled_tasks "
                            "WHERE id='old'").fetchone() == (None, None)
    finally:
        conn.close()
