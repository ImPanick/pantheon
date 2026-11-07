# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1791`. Tasks → Activity named another member's endpoint for a run.

`GET /api/tasks/runs/recent` lists only the signed-in member's own task runs,
and each row carries the endpoint that *Open in chat* reopens the run against.
For a run whose task names no endpoint and no chat, `_resolve_run_endpoint`
found one by scanning every enabled endpoint of every owner and taking the
first whose model list named the run's model. When two members' endpoints
served the same name, one member was handed the other's private base URL (a
LAN, tailnet or proxy address), and Open in chat made a chat pointed at it.
The owner-scoped chat checks then refused that chat, so no key went with it.

Now the scan reads only what the run could have used: the task owner's own
endpoints and the shared ones (`owner_filter`), the scope the scheduler that
ran it uses (`src/task_scheduler.py`). A task with no owner reads the shared
ones only.

Ported from upstream Odysseus 72e8520f (#6922), the owner filter only: its
pinned-model selection is not Pantheon's rule (`B1259`, `D-2026-10-07-02` §1).
Driven (`Law 20`): the real function and the real route over a real SQLite file.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402

MODEL = "qwen3:8b"


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tasks.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


def _url(eid: str) -> str:
    return f"http://{eid}.lan:11434/v1"


def _endpoints(factory, rows):
    """`rows` is (id, owner) in the order they are written; each lists MODEL."""
    with factory() as db:
        for eid, owner in rows:
            db.add(cdb.ModelEndpoint(
                id=eid, name=eid, owner=owner, is_enabled=True, base_url=_url(eid),
                cached_models=json.dumps([MODEL]),
            ))
        db.commit()


@pytest.mark.parametrize("rows, owner, expected", [
    ([("bob-box", "bob")], "alice", ""),
    ([("bob-box", "bob"), ("alice-box", "alice")], "alice", _url("alice-box")),
    ([("shared-box", None)], "alice", _url("shared-box")),
    ([("bob-box", "bob")], None, ""),
    ([("bob-box", "bob"), ("shared-box", None)], None, _url("shared-box")),
], ids=["only-another-members", "another-members-listed-first", "shared",
        "no-owner", "no-owner-shared"])
def test_a_run_is_reopened_only_against_an_endpoint_its_owner_could_use(
        factory, rows, owner, expected):
    from routes.task.task_routes import _resolve_run_endpoint

    _endpoints(factory, rows)
    task = SimpleNamespace(owner=owner, endpoint_url="", session_id=None, model=MODEL)
    with factory() as db:
        assert _resolve_run_endpoint(db, task, SimpleNamespace(model=MODEL)) == expected


def test_the_activity_feed_does_not_carry_another_members_address(factory, monkeypatch):
    import routes.task_routes as task_routes

    monkeypatch.setattr(task_routes, "SessionLocal", factory)
    _endpoints(factory, [("bob-box", "bob")])
    with factory() as db:
        db.add(cdb.ScheduledTask(
            id="t1", owner="alice", name="Morning brief", prompt="brief me",
            task_type="llm", model=MODEL, endpoint_url="", status="active",
        ))
        db.add(cdb.TaskRun(id="r1", task_id="t1", status="success", model=MODEL,
                           started_at=datetime(2026, 11, 7, 9, 0)))
        db.commit()

    router = task_routes.setup_task_routes(MagicMock())
    recent = next(route.endpoint for route in router.routes
                  if getattr(route, "path", None) == "/api/tasks/runs/recent"
                  and "GET" in getattr(route, "methods", set()))
    feed = recent(SimpleNamespace(state=SimpleNamespace(current_user="alice")))
    assert [(row["id"], row["model"], row["endpoint_url"]) for row in feed["runs"]] == [
        ("r1", MODEL, "")]
