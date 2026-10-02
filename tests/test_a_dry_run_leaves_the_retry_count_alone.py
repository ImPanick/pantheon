# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1059` — a dry run reset a task's failure streak, so it handed out a fresh
retry budget.

**Measured 2026-10-01** by `wb-runs` (`/tmp/scratch-wb-runs/probe_streak.py`, the
real functions on a real SQLite file): a task with `max_retries=3` and three
failures in a row had `consecutive_failures == 3`; after one *Show me what this
would do* it was **0**, and the next failure was planned as *"Failed — retrying
(attempt 1 of 3) in 342 seconds"*. `consecutive_failures` stops at any `skipped`
row, and a dry run is recorded `skipped` (`P8-33`), so the one button that
promises no side effect reset `P8-32`'s retry budget and `P15-08`'s backoff
ladder — the half that keeps a provider from banning the owner.

Driven end to end (`Law 20`): the real `TaskScheduler` records every run —
three real failures through `_execute_task`, a real dry run through
`run_task_now(dry=True)`, a fourth real failure — on a real SQLite file. The
one executor is a recorder that fails, as a provider refusing would.
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
import src.task_scheduler as ts  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.builtin_actions import NodeResult  # noqa: E402

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
    engine = create_engine(
        f"sqlite:///{tmp_path / 'streak.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    # Nobody is using Pantheon: the gate lets every run straight through.
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "0")
    db = factory()
    try:
        db.add(ScheduledTask(
            id="sync", owner=None, name="Mail sync", task_type="action",
            action="tidy_sessions", trigger_type="schedule", schedule="daily",
            scheduled_time="02:00", status="active", max_retries=3))
        db.commit()
    finally:
        db.close()
    return factory


def _scheduler(outcomes):
    """The real scheduler; its one executor answers the next outcome."""
    s = ts.TaskScheduler(None)

    async def _action(task, run_id=None):
        status = outcomes.pop(0)
        return NodeResult(status, payload="IMAP refused: too many connections"
                          if status == "error" else "Nothing to do")
    s._execute_action = _action
    s._log_to_assistant = lambda *a, **k: None
    return s


def _steps(factory, run_id):
    db = factory()
    try:
        run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
        return [step.get("detail", "") for step in json.loads(run.steps or "[]")]
    finally:
        db.close()


def _streak(factory):
    db = factory()
    try:
        return ts.consecutive_failures(db, "sync")
    finally:
        db.close()


async def _fail(s, factory):
    run_id = await s._execute_task("sync")
    return _steps(factory, run_id)


@pytest.mark.asyncio
async def test_a_dry_run_between_two_failures_leaves_the_retry_count_where_it_was(task_db):
    """`B1059`'s `Verify:`. Three failures spend the three retries; a dry run;
    the fourth failure is not handed a fresh budget."""
    s = _scheduler(["error", "error", "error", "error"])
    for attempt in (1, 2, 3):
        steps = await _fail(s, task_db)
        assert any(f"retrying (attempt {attempt} of 3)" in d for d in steps), steps
    assert _streak(task_db) == 3

    plan_run = await s.run_task_now("sync", dry=True)
    assert isinstance(plan_run, str)
    db = task_db()
    try:
        assert ts.is_dry_run(db.query(TaskRun).filter(TaskRun.id == plan_run).first())
    finally:
        db.close()
    assert _streak(task_db) == 3, "the dry run reset the failure streak"

    steps = await _fail(s, task_db)
    assert not any("retrying (attempt" in d for d in steps), (
        f"the dry run handed out a fresh retry budget: {steps}")
    assert _streak(task_db) == 4


@pytest.mark.asyncio
async def test_a_dry_run_leaves_the_backoff_ladder_on_its_rung(task_db):
    """The other half: `failure_backoff_seconds` is read off the same count, so
    the gap after the next failure is the fourth rung's, not the first's."""
    s = _scheduler(["error", "error", "error"])
    for _ in range(3):
        await _fail(s, task_db)
    await s.run_task_now("sync", dry=True)

    db = task_db()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "sync").first()
        plan = ts.failure_next_run(db, task, run_id="the-next-one")
    finally:
        db.close()
    assert plan.attempt == 4, plan
    assert not plan.is_retry
    # The fourth rung is 300 × 2³ s before jitter (±20 %); the first was 300.
    assert plan.delay_seconds >= 300 * 8 * 0.8, plan


@pytest.mark.asyncio
async def test_a_real_skip_still_ends_the_streak(task_db):
    """`Law 1`. A housekeeping action that RAN and found nothing to do is not
    a failure and still ends the count, exactly as before."""
    s = _scheduler(["error", "error", "skipped"])
    await _fail(s, task_db)
    await _fail(s, task_db)
    assert _streak(task_db) == 2
    await s._execute_task("sync")
    assert _streak(task_db) == 0
