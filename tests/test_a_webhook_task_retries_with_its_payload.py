# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B805` — "retry 3 times" on a webhook- or event-triggered task means three
retries, each with the payload that started it.

**Measured before this file:** `failure_next_run` answered "no retry" for any
task whose trigger is not a schedule, while the API accepted `max_retries` on
every task — so a webhook task set to retry three times failed once and was
silent; the payload it brought was dropped. (Re-firing it on a clock would
make it a different kind of task, and its `next_run` means "deferred", which
is why the answer was no — and still is: the retry is the same TRIGGER again.)

Now a failed event or webhook run with retries left is dispatched again after
the backoff ladder's wait, with the envelope the failed run was handed
(`run_trigger`), its row saying so; the attempts are counted from the run
history, as a schedule's are. Driven (`Law 20`): the real scheduler from
`run_task_now` (the webhook route's door) on a real SQLite file; the executors
are recorders that fail, and the waits are shortened.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.helpers.walker_harness import make_db  # noqa: E402
from test_one_task_form_in_two_places_js import sandbox, task_db  # noqa: E402,F401


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import src.task_scheduler as ts
    from src.builtin_actions import NodeResult
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "retry.db")
    monkeypatch.setattr(ts, "failure_backoff_seconds", lambda failures: 0.05)
    monkeypatch.setattr(ts, "min_task_interval_seconds", lambda: 0)
    monkeypatch.setattr(TaskScheduler, "RETRY_BUSY_SECONDS", 0.05, raising=False)
    s = TaskScheduler(None)
    s.handed = []

    async def action(task, run_id=None):
        s.handed.append((task.id, s.run_trigger(run_id)))
        return NodeResult("error", payload="The provider answered 503.")

    async def llm(task, db, run_id=None):
        s.handed.append((task.id, s.run_trigger(run_id)))
        raise RuntimeError("The provider answered 503.")

    s._execute_action = action
    s._execute_llm_task = llm
    s._log_to_assistant = lambda *a, **k: None
    return factory, s


def _seed(factory, task_id, **kw):
    from core.database import ScheduledTask
    db = factory()
    db.add(ScheduledTask(id=task_id, owner="alice", name=f"Hook {task_id}", status="active",
                         trigger_type="webhook", **kw))
    db.commit()
    db.close()


def _runs(factory, task_id):
    from core.database import TaskRun
    db = factory()
    try:
        return [{"status": r.status, "steps": json.loads(r.steps) if r.steps else []}
                for r in db.query(TaskRun).filter(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at, TaskRun.id).all()]
    finally:
        db.close()


async def _settle(factory, s, task_id, n, limit=400):
    for _ in range(limit):
        await asyncio.sleep(0.02)
        if len(_runs(factory, task_id)) >= n and not s._executing \
                and not getattr(s, "_pending_retries", None):
            return
    raise AssertionError(f"{task_id}: {len(_runs(factory, task_id))} runs, wanted {n}")


def _webhook(body):
    from src.event_bus import TRIGGER_SOURCE_WEBHOOK, build_trigger
    return build_trigger(TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": body},
                         fields=("body", "json", "query", "headers"))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["action", "llm"])
async def test_three_retries_each_with_the_payload_that_started_it(world, kind):
    """Both ways a run fails: an action that RETURNS a failure, a Prompt task
    whose executor RAISES — the two places `failure_next_run` is asked."""
    factory, s = world
    extra = ({"task_type": "action", "action": "tidy_documents"} if kind == "action"
             else {"task_type": "llm", "prompt": "File the invoice."})
    _seed(factory, "hook", max_retries=3, **extra)
    payload = _webhook("invoice #42 arrived")

    assert await s.run_task_now("hook", trigger=payload) is True
    await _settle(factory, s, "hook", 4)
    await asyncio.sleep(0.3)                       # and nothing after the third retry

    runs = _runs(factory, "hook")
    assert [r["status"] for r in runs] == ["error"] * 4, runs
    assert s.handed == [("hook", payload)] * 4, "a retry ran without what started it"
    notes = [[st["detail"] for st in r["steps"] if st.get("kind") == "progress"] for r in runs]
    for attempt in (1, 2, 3):
        assert any(n.startswith(f"Failed — retrying (attempt {attempt} of 3)")
                   and n.endswith("with what started it") for n in notes[attempt - 1]), notes
    assert any("3 retry attempt(s) used up" in n for n in notes[3]), notes[3]


@pytest.mark.asyncio
async def test_with_no_retries_set_a_failed_webhook_task_waits_for_its_next_trigger(world):
    """`Law 1`: the task with no budget behaves exactly as every one did."""
    factory, s = world
    _seed(factory, "plain", task_type="action", action="tidy_documents")
    assert await s.run_task_now("plain", trigger=_webhook("x")) is True
    await _settle(factory, s, "plain", 1)
    await asyncio.sleep(0.3)
    assert [r["status"] for r in _runs(factory, "plain")] == ["error"]
    assert len(s.handed) == 1


# ── where a person sets it ──────────────────────────────────────────────────
#
# The task form drew the retry box for a scheduled task only, and sent the
# count only for one (`static/js/tasks/taskFields.js`); the card said "N
# retries if it fails" only for one. Both now hold for every trigger. Driven
# with the real form and card under node (`test_one_task_form_in_two_places_js`'
# harness).

def test_the_form_offers_and_sends_retries_for_a_webhook_task(task_db, sandbox):
    from test_one_task_form_in_two_places_js import _edit_and_save, _served_row
    row = _served_row(task_db, trigger_type="webhook", schedule=None, scheduled_time=None,
                      webhook_token="tok", max_retries=2)
    out = _edit_and_save(sandbox, row, """
        if (q(host, 'task-form-retries').value !== '2') throw new Error('not shown: ' + q(host, 'task-form-retries').value);
        q(host, 'task-form-retries').value = '3';
    """)
    assert out["errors"] == [], out["errors"]
    (write,) = out["writes"]
    assert write["body"]["trigger_type"] == "webhook"
    assert write["body"]["max_retries"] == 3
