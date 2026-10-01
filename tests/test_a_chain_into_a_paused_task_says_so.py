# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1037` — a chain into a paused task said it continued.

**Measured** by `wb-graph` on 2026-10-01 and again here on the tree before this
file: the head's last step read "Continued to Tail" while the paused Tail was
recorded `skipped` ("Task no longer active (status=paused)") and notified —
the same false claim `P22-01` made honest for a successor that was already
running. Now the head's run says "Did not continue to Tail: it is paused".

What Tail itself records is `B112`'s notification-policy call (the row says
so), so it is left exactly as it was — a `skipped` run and a notification —
and held here as it stands.

Real `_execute_task_locked` → `_advance_chain` → `_run_chained` →
`_execute_task` on a real SQLite file (`Law 20`); the gate is off here.
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
import src.builtin_actions as ba  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import TaskScheduler  # noqa: E402

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "0")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'paused-tail.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


@pytest.fixture()
def ran(monkeypatch):
    seen = []

    async def works(**kwargs):
        seen.append("works")
        return "tidied", True

    async def fails(**kwargs):
        seen.append("fails")
        return "the disk is full", False

    async def tail(**kwargs):
        seen.append("tail")
        return "told", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", works)
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_documents", fails)
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_research", tail)
    return seen


def _seed(factory, *, head_action, edge, tail_status):
    db = factory()
    try:
        db.add(ScheduledTask(id="tail", owner=None, name="Tail", task_type="action",
                             action="tidy_research", trigger_type="webhook",
                             status=tail_status, output_target="session"))
        db.add(ScheduledTask(id="head", owner=None, name="Head", task_type="action",
                             action=head_action, trigger_type="webhook", status="active",
                             output_target="session"))
        db.commit()
        setattr(db.query(ScheduledTask).filter(ScheduledTask.id == "head").first(), edge, "tail")
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


async def _run_head(factory):
    s = TaskScheduler(None)
    s._log_to_assistant = lambda *a, **k: None
    assert await s.run_task_now("head") is True
    for _ in range(400):
        tail = _runs(factory, "tail")
        if tail and tail[0]["status"] not in ("queued", "running") and not s._executing:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("the chain did not settle")
    return s


@pytest.mark.asyncio
@pytest.mark.parametrize("head_action,edge", [
    ("tidy_sessions", "then_task_id"), ("tidy_documents", "else_task_id")],
    ids=["if-it-works", "if-it-fails"])
async def test_a_chain_into_a_paused_task_says_it_did_not_continue(
        task_db, ran, head_action, edge):
    """The row's `Verify:` on either edge: the run that stopped says so."""
    _seed(task_db, head_action=head_action, edge=edge, tail_status="paused")

    s = await _run_head(task_db)

    (head,) = _runs(task_db, "head")
    assert head["steps"][-1]["detail"] == "Did not continue to Tail: it is paused"
    assert "tail" not in ran
    # Tail's own record is B112's call, unchanged: a skipped run, and told.
    (tail,) = _runs(task_db, "tail")
    assert tail["status"] == "skipped"
    assert tail["error"] == "Task no longer active (status=paused)"
    assert [n["status"] for n in s._pending_notifications if n["task_name"] == "Tail"] == [
        "skipped"]


@pytest.mark.asyncio
async def test_a_chain_into_a_one_off_that_already_ran_says_so(task_db, ran):
    _seed(task_db, head_action="tidy_sessions", edge="then_task_id", tail_status="completed")

    await _run_head(task_db)

    (head,) = _runs(task_db, "head")
    assert head["steps"][-1]["detail"] == (
        "Did not continue to Tail: it was a one-off and has already run")


@pytest.mark.asyncio
@pytest.mark.parametrize("head_action,edge,line", [
    ("tidy_sessions", "then_task_id", "Continued to Tail"),
    ("tidy_documents", "else_task_id", "Failed, so continued to Tail")],
    ids=["if-it-works", "if-it-fails"])
async def test_a_chain_into_an_active_task_still_continues(task_db, ran, head_action, edge, line):
    """`Law 1`."""
    _seed(task_db, head_action=head_action, edge=edge, tail_status="active")

    await _run_head(task_db)

    (head,) = _runs(task_db, "head")
    assert head["steps"][-1]["detail"] == line
    assert "tail" in ran
    assert _runs(task_db, "tail")[0]["status"] == "success"
