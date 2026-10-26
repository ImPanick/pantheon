# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1492` — "retry twice" on a *Once* task means two retries, then it ends.

**Measured before this file:** `failure_next_run` asks `compute_next_run` for
the task's next occurrence and answered "no retry" when there is none — and a
one-off whose date has passed has none, by definition. So a one-off set to
retry twice (the form draws the retry box for *Once*, and the API stores the
count) failed once, was marked `completed`, and its count did nothing.

Now a one-off's retries come back on the same ladder a schedule's do, through
`next_run` — the column the scheduler's loop reads, so they survive a restart
as any due task does — and when they are used up it ends and says so. Driven
(`Law 20`): the real scheduler's own tick (`_check_due_tasks`) on a real SQLite
file, both ways a run fails (an action that RETURNS a failure, a Prompt task
whose executor RAISES); the executors are recorders and the waits shortened.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from tests.helpers.walker_harness import make_db


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import src.task_scheduler as ts
    from src.builtin_actions import NodeResult
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "once.db")
    monkeypatch.setattr(ts, "failure_backoff_seconds", lambda failures: 0.05)
    monkeypatch.setattr(ts, "min_task_interval_seconds", lambda: 0)
    monkeypatch.setattr(ts, "dispatch_hold", lambda task, **kw: 0.0)
    s = TaskScheduler(None)
    s.ran = []

    async def action(task, run_id=None):
        s.ran.append(task.id)
        return NodeResult("error", payload="The provider answered 503.")

    async def llm(task, db, run_id=None):
        s.ran.append(task.id)
        raise RuntimeError("The provider answered 503.")

    s._execute_action = action
    s._execute_llm_task = llm
    s._log_to_assistant = lambda *a, **k: None
    return factory, s


def _seed(factory, kind, **kw):
    from core.database import ScheduledTask
    when = datetime.utcnow() - timedelta(seconds=5)
    extra = ({"task_type": "action", "action": "tidy_documents"} if kind == "action"
             else {"task_type": "llm", "prompt": "File the invoice."})
    db = factory()
    db.add(ScheduledTask(id="once", owner="alice", name="Send the invoice once",
                         status="active", trigger_type="schedule", schedule="once",
                         scheduled_date=when, next_run=when, **extra, **kw))
    db.commit()
    db.close()


def _task(factory):
    from core.database import ScheduledTask
    db = factory()
    try:
        t = db.query(ScheduledTask).filter(ScheduledTask.id == "once").first()
        return {"status": t.status, "next_run": t.next_run}
    finally:
        db.close()


def _runs(factory):
    from core.database import TaskRun
    db = factory()
    try:
        return [{"status": r.status,
                 "notes": [st.get("detail") for st in (json.loads(r.steps) if r.steps else [])
                           if st.get("kind") == "progress"]}
                for r in db.query(TaskRun).filter(TaskRun.task_id == "once")
                .order_by(TaskRun.started_at, TaskRun.id).all()]
    finally:
        db.close()


async def _tick_until_quiet(s, factory, ticks=60):
    """The scheduler's own tick, again and again, until nothing is due or
    running — what its loop does, without its sleep."""
    for _ in range(ticks):
        await s._check_due_tasks()
        await asyncio.sleep(0.1)
        task = _task(factory)
        if not s._executing and (task["next_run"] is None or task["status"] != "active"):
            return


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["action", "llm"])
async def test_a_one_off_set_to_retry_twice_is_retried_twice_then_ends(world, kind):
    factory, s = world
    _seed(factory, kind, max_retries=2)

    await _tick_until_quiet(s, factory)

    runs = _runs(factory)
    assert [r["status"] for r in runs] == ["error"] * 3, (
        f"a one-off set to retry twice ran {len(runs)} time(s): {runs}")
    assert len(s.ran) == 3
    for attempt in (1, 2):
        assert any(n.startswith(f"Failed — retrying (attempt {attempt} of 2)")
                   for n in runs[attempt - 1]["notes"]), runs
    assert any("2 retry attempt(s) used up" in n and "one-off" in n
               for n in runs[2]["notes"]), runs[2]
    task = _task(factory)
    assert task == {"status": "completed", "next_run": None}, task


@pytest.mark.asyncio
async def test_a_one_off_with_no_retries_ends_after_its_one_run(world):
    """`Law 1`: what every one-off without a count has always done."""
    factory, s = world
    _seed(factory, "action")
    await _tick_until_quiet(s, factory)
    assert [r["status"] for r in _runs(factory)] == ["error"]
    assert _task(factory) == {"status": "completed", "next_run": None}


@pytest.mark.asyncio
async def test_a_retried_one_off_that_then_works_is_completed(world):
    factory, s = world
    from src.builtin_actions import NodeResult
    _seed(factory, "action", max_retries=3)
    answers = iter(["error", "success"])

    async def flaky(task, run_id=None):
        s.ran.append(task.id)
        return NodeResult(next(answers), payload="done")

    s._execute_action = flaky
    await _tick_until_quiet(s, factory)
    assert [r["status"] for r in _runs(factory)] == ["error", "success"]
    assert _task(factory) == {"status": "completed", "next_run": None}
