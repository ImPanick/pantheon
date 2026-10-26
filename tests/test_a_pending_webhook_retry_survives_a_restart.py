# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1494` — a webhook task's retry that is pending when Pantheon restarts
still runs, with the payload that started the failed run.

**Measured before this file:** `B805` gave an event or webhook task its
retries — the same trigger again, after the backoff — and held the wait and the
envelope in the process (`_retry_with_trigger`, a sleeping `asyncio` task). A
restart before it was due dropped it: the failed run's row said "retrying
(attempt 1 of 3) … with what started it" and nothing ever did.

Now the plan — when it is due and the envelope — is written on the failed
run's own row (its plan step, `RETRY_PLAN_KEY`), through the run table that
already holds everything else about the run, and `TaskScheduler.start` re-arms
any plan a restart left untaken; a dispatched plan is marked taken, so a second
restart runs nothing twice. Driven (`Law 20`): two real schedulers over one
real SQLite file — the first fails the run and "dies" (its pending wait is
cancelled, as a process exit would), the second is started with `start()`.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from tests.helpers.walker_harness import make_db


def _scheduler(handed, *, fail):
    from src.builtin_actions import NodeResult
    from src.task_scheduler import TaskScheduler

    s = TaskScheduler(None)

    async def action(task, run_id=None):
        handed.append((task.id, s.run_trigger(run_id)))
        return NodeResult("error" if fail else "success", payload="The provider answered 503."
                          if fail else "Filed.")

    s._execute_action = action
    s._log_to_assistant = lambda *a, **k: None
    return s


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    import src.task_scheduler as ts
    from src.task_scheduler import TaskScheduler

    f = make_db(monkeypatch, tmp_path / "restart.db")
    monkeypatch.setattr(ts, "failure_backoff_seconds", lambda failures: 0.3)
    monkeypatch.setattr(ts, "min_task_interval_seconds", lambda: 0)
    monkeypatch.setattr(TaskScheduler, "RETRY_BUSY_SECONDS", 0.05, raising=False)
    from core.database import ScheduledTask
    db = f()
    db.add(ScheduledTask(id="hook", owner="alice", name="File the invoice", status="active",
                         trigger_type="webhook", webhook_token="tok", task_type="action",
                         action="tidy_documents", max_retries=3))
    db.commit()
    db.close()
    return f


def _runs(factory):
    from core.database import TaskRun
    db = factory()
    try:
        return [{"id": r.id, "status": r.status,
                 "steps": json.loads(r.steps) if r.steps else []}
                for r in db.query(TaskRun).filter(TaskRun.task_id == "hook")
                .order_by(TaskRun.started_at, TaskRun.id).all()]
    finally:
        db.close()


def _plans(run):
    from src.task_scheduler import RETRY_PLAN_KEY
    return [st[RETRY_PLAN_KEY] for st in run["steps"] if RETRY_PLAN_KEY in st]


def _webhook(body):
    from src.event_bus import TRIGGER_SOURCE_WEBHOOK, build_trigger
    return build_trigger(TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": body},
                         fields=("body", "json", "query", "headers"))


async def _die(s):
    """What a process exit does to the waits it was holding."""
    for job in list(getattr(s, "_pending_retries", None) or ()):
        job.cancel()
    await asyncio.sleep(0)


async def _until(predicate, limit=200):
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("it never happened")


@pytest.mark.asyncio
async def test_a_retry_pending_across_a_restart_runs_with_its_payload(factory):
    payload = _webhook("invoice #42 arrived")
    first_handed, after_handed = [], []

    # The first process: the webhook's run fails, a retry is planned — and the
    # process stops before it is due.
    first = _scheduler(first_handed, fail=True)
    assert await first.run_task_now("hook", trigger=payload) is True
    await _until(lambda: _runs(factory) and _runs(factory)[0]["status"] == "error"
                 and not first._executing)
    await _die(first)
    [failed] = _runs(factory)
    [plan] = _plans(failed)
    assert plan["trigger"] == payload, "the plan does not hold what started the run"
    assert "taken" not in plan

    # The next process starts, and the retry runs — with that payload.
    after = _scheduler(after_handed, fail=False)
    await after.start()
    try:
        await _until(lambda: len(_runs(factory)) == 2 and not after._executing
                     and not after._pending_retries)
    finally:
        await after.stop()
    assert first_handed == [("hook", payload)]
    assert after_handed == [("hook", payload)], (
        "the retry a restart left pending did not run with the payload that started it")
    runs = _runs(factory)
    assert [r["status"] for r in runs] == ["error", "success"]
    [plan] = _plans(runs[0])
    assert plan.get("taken") and "trigger" not in plan, plan

    # And a third start runs nothing again: the plan was taken.
    again_handed = []
    again = _scheduler(again_handed, fail=False)
    await again.start()
    try:
        await asyncio.sleep(0.6)
    finally:
        await again.stop()
    assert again_handed == [] and len(_runs(factory)) == 2


@pytest.mark.asyncio
async def test_a_retry_that_ran_before_the_restart_is_not_run_again(factory):
    """The ordinary case: the retry comes due in the same process, runs, and a
    later start finds nothing pending (`Law 1` for the in-process wait)."""
    handed = []
    s = _scheduler(handed, fail=False)
    first = _scheduler(handed, fail=True)
    assert await first.run_task_now("hook", trigger=_webhook("x")) is True
    await _until(lambda: len(_runs(factory)) == 2 and _runs(factory)[1]["status"] == "error"
                 and _plans(_runs(factory)[1]))
    await _die(first)                   # before the third attempt is due
    assert [r["status"] for r in _runs(factory)] == ["error", "error"]
    # The second failure planned the next retry; the first's plan is taken.
    first_plan, second_plan = (_plans(r)[0] for r in _runs(factory))
    assert first_plan.get("taken") and "trigger" not in first_plan
    assert "taken" not in second_plan

    await s.start()
    try:
        await _until(lambda: len(_runs(factory)) == 3 and not s._executing
                     and not s._pending_retries)
    finally:
        await s.stop()
    assert [r["status"] for r in _runs(factory)] == ["error", "error", "success"]
    assert len(handed) == 3, handed
