# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-31` — an event trigger fires on every event unless you say otherwise.

Premise corrected 2026-09-18. The row says the default is 5; the server had no
default at all. `POST /api/tasks` **refused** an event-triggered task that
omitted `trigger_count` with a 400, and the UI only ever avoided that by
pre-filling 5 — so the number a person got was a form default nobody chose and
the API had no opinion about. The bus has always read `trigger_count or 1`, so
1 was already the behaviour of a null; this makes it the behaviour of an
omission too, and writes it down rather than leaving a null that means one
thing at the bus and another in the form (`Law 10`).
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import routes.task_routes as task_routes  # noqa: E402
from core.database import ScheduledTask  # noqa: E402
from src.event_bus import DEFAULT_TRIGGER_COUNT  # noqa: E402


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tasks.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(task_routes, "SessionLocal", factory)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _req(user=None):
    return SimpleNamespace(state=SimpleNamespace(current_user=user))


def _endpoint(method, path):
    router = task_routes.setup_task_routes(MagicMock())
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise RuntimeError(f"{method} {path} not found")


@pytest.mark.asyncio
async def test_omitting_the_count_creates_a_task_that_fires_every_time(task_db):
    create_task = _endpoint("POST", "/api/tasks")

    out = await create_task(_req(), task_routes.TaskCreate(
        name="On every new document",
        prompt="summarize it",
        task_type="llm",
        trigger_type="event",
        trigger_event="document_created",
    ))

    assert out["trigger_count"] == DEFAULT_TRIGGER_COUNT == 1
    db = task_db()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == out["id"]).first()
        # Stored, not left null: the row says what it does.
        assert task.trigger_count == 1
    finally:
        db.close()


@pytest.mark.asyncio
async def test_an_explicit_count_is_still_honoured(task_db):
    create_task = _endpoint("POST", "/api/tasks")

    out = await create_task(_req(), task_routes.TaskCreate(
        name="Every fifth document",
        prompt="summarize it",
        task_type="llm",
        trigger_type="event",
        trigger_event="document_created",
        trigger_count=5,
    ))

    assert out["trigger_count"] == 5


@pytest.mark.asyncio
async def test_the_event_name_is_still_required(task_db):
    """The default fills in the count. It does not guess the event."""
    from fastapi import HTTPException

    create_task = _endpoint("POST", "/api/tasks")

    with pytest.raises(HTTPException) as exc:
        await create_task(_req(), task_routes.TaskCreate(
            name="No event", prompt="x", task_type="llm", trigger_type="event",
        ))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_a_legacy_row_with_no_count_fires_on_the_first_event(task_db, monkeypatch):
    """Rows created before this carry NULL. The bus has always read them as 1
    and must keep doing so — driven through `_handle_event`, not asserted about
    (`Law 20`)."""
    import src.event_bus as eb

    db = task_db()
    try:
        db.add(ScheduledTask(
            id="legacy", owner=None, name="legacy", prompt="x", task_type="llm",
            trigger_type="event", trigger_event="document_updated",
            trigger_count=None, trigger_counter=0, status="active",
            output_target="session",
        ))
        db.commit()
    finally:
        db.close()

    ran = []

    class _Sched:
        async def run_task_now(self, task_id):
            ran.append(task_id)
            return True

    monkeypatch.setattr(eb, "_task_scheduler", _Sched(), raising=False)
    monkeypatch.setattr(eb, "_resolve_event_owner", lambda owner: None)

    await eb._handle_event("document_updated", None)

    assert ran == ["legacy"], "a NULL trigger_count no longer fires every event"
