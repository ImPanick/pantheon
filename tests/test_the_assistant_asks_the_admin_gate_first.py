# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1038` — `manage_tasks` skipped the admin gate the route applies, and
reported success.

**Measured before this file** (`/tmp/scratch-wb-runs/probe_b1038.py`), with
`owner_has_admin_task_privileges` answering False: a non-admin's `create` of
`ssh_command` stored the task and replied "Created task 'reboot'"; `edit`
switched a task's action to `ssh_command`; `resume` put a refused task back on
("Task 'Restart' resumed"); `run` replied "Task 'Restart' triggered" and
reached the scheduler — exit 0 each time. The route refuses all four
(`_require_admin_for_task_action` → 403). No command ran: the engine's own gate
holds (`FORBIDDEN.md` Part 2). The defect is the tool telling the model a
refused thing happened, and a create the route would not allow — the row named
`create` and `run`; `edit` and `resume` are the same door shape, measured the
same, and asked the same question here.

The real tool against a real SQLite file and the real route through
`TestClient` (`Law 20`); only who is an admin is decided by the test.
"""

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
import src.event_bus as event_bus  # noqa: E402
import src.task_action_policy as policy  # noqa: E402
from core.database import ScheduledTask  # noqa: E402
from src.tools.system import do_manage_tasks  # noqa: E402

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
}

REFUSAL = "Action 'ssh_command' requires admin privileges"


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'gate.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    db = factory()
    try:
        db.add(ScheduledTask(id="plain", owner="bob", name="Tidy", task_type="action",
                             action="tidy_sessions", trigger_type="webhook", status="active"))
        db.add(ScheduledTask(id="adm", owner="bob", name="Restart", task_type="action",
                             action="ssh_command", prompt="reboot", trigger_type="webhook",
                             status="paused"))
        db.commit()
    finally:
        db.close()
    return factory


@pytest.fixture()
def dispatched(monkeypatch):
    seen = []

    class _Scheduler:
        async def run_task_now(self, task_id, **kwargs):
            seen.append(task_id)
            return True

    monkeypatch.setattr(event_bus, "_task_scheduler", _Scheduler())
    return seen


def _admin(monkeypatch, yes):
    monkeypatch.setattr(policy, "owner_has_admin_task_privileges", lambda owner: yes)


def _rows(factory):
    db = factory()
    try:
        return {t.id: (t.name, t.task_type, t.action, t.status)
                for t in db.query(ScheduledTask).all()}
    finally:
        db.close()


async def _ask(args):
    return await do_manage_tasks(json.dumps(args), owner="bob")


CREATE = {"action": "create", "task_type": "action", "action_name": "ssh_command",
          "name": "reboot", "prompt": "reboot"}
DOORS = {
    "create": CREATE,
    "edit": {"action": "edit", "task_id": "plain", "action_name": "ssh_command"},
    "resume": {"action": "resume", "task_id": "adm"},
    "run": {"action": "run", "task_id": "adm"},
}


@pytest.mark.asyncio
async def test_asked_by_a_non_admin_to_schedule_ssh_command_the_assistant_is_told_no(
        task_db, dispatched, monkeypatch):
    """The row's `Verify:`, word for word: told it needs an admin, and no task
    is created."""
    _admin(monkeypatch, False)
    before = _rows(task_db)

    out = await _ask(CREATE)

    assert out == {"error": REFUSAL, "exit_code": 1}
    assert _rows(task_db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("door", sorted(DOORS))
async def test_every_door_the_route_gates_is_gated_here_and_changes_nothing(
        task_db, dispatched, monkeypatch, door):
    _admin(monkeypatch, False)
    before = _rows(task_db)

    out = await _ask(DOORS[door])

    assert out == {"error": REFUSAL, "exit_code": 1}, out
    assert _rows(task_db) == before
    assert dispatched == []


@pytest.mark.asyncio
@pytest.mark.parametrize("door", sorted(DOORS))
async def test_an_admin_is_answered_exactly_as_before(task_db, dispatched, monkeypatch, door):
    """`Law 1`."""
    _admin(monkeypatch, True)

    out = await _ask(DOORS[door])

    assert out["exit_code"] == 0, out
    if door == "run":
        assert dispatched == ["adm"]


@pytest.mark.asyncio
async def test_a_non_admin_still_manages_their_ordinary_tasks(task_db, dispatched, monkeypatch):
    """`Law 1`. The gate is about four actions, not about the person."""
    _admin(monkeypatch, False)

    made = await _ask({"action": "create", "task_type": "action", "action_name": "tidy_sessions",
                       "name": "Tidy again"})
    edited = await _ask({"action": "edit", "task_id": "plain", "name": "Tidy up"})
    ran = await _ask({"action": "run", "task_id": "plain"})
    paused = await _ask({"action": "pause", "task_id": "adm"})

    assert [o["exit_code"] for o in (made, edited, ran, paused)] == [0, 0, 0, 0]
    assert dispatched == ["plain"]


def test_the_tool_and_the_route_refuse_in_the_same_words(task_db, monkeypatch):
    """`Law 7`, driven: the route's 403 for the same create carries the same
    sentence the tool now answers with."""
    import asyncio
    import routes.task.task_routes as task_routes
    from unittest.mock import MagicMock

    _admin(monkeypatch, False)
    monkeypatch.setattr(task_routes, "owner_has_admin_task_privileges", lambda owner: False)
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = "bob"
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(MagicMock()))
    r = TestClient(app).post("/api/tasks", json={
        "name": "reboot", "task_type": "action", "action": "ssh_command",
        "prompt": "reboot", "trigger_type": "webhook"})

    assert r.status_code == 403
    assert r.json()["detail"] == asyncio.run(_ask(CREATE))["error"] == REFUSAL
