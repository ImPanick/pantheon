# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-27` / `B603` — a run's own facts belong to that run.

`_last_run_model` and `_last_run_steps` were single attributes on the
scheduler, so "which model this run resolved" and "what this run did" were
recorded in one slot shared by every run on the process. That is sound at
`TASK_CONCURRENCY_CAP_DEFAULT`, which is **1**. It is an operator setting with a
ceiling of **16**, and above one, two runs write the same slot between the
executor returning and the row being committed: run A gets stamped with run B's
model and B's step log.

Nothing in the tree measured it, which is why it survived. The measurement is
here: two runs are held mid-flight at the same time, deliberately interleaved,
and each row is read back.
"""

import asyncio
import json
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
from core.database import ScheduledTask, Session as DbSession, TaskRun  # noqa: E402
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
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _scheduler():
    s = TaskScheduler.__new__(TaskScheduler)
    s._task_handles = {}
    s._task_defer_counts = {}
    s._session_manager = None
    s._notify_run_outcome = MagicMock(return_value=True)
    s.add_notification = MagicMock()
    s._log_to_assistant = MagicMock()
    s._deliver_task_result = _noop_deliver
    return s


async def _noop_deliver(*a, **k):
    return None


def _seed_llm(factory, task_id, run_id, model):
    db = factory()
    try:
        db.add(DbSession(id=f"sess-{task_id}", name=f"[Task] {task_id}",
                         endpoint_url="http://endpoint/v1/chat/completions",
                         model=model, owner=None, folder="Tasks"))
        db.flush()
        db.add(ScheduledTask(
            id=task_id, owner=None, name=f"Task {task_id}",
            prompt=f"do {task_id}", task_type="llm", trigger_type="schedule",
            schedule="daily", scheduled_time="03:00", status="active",
            output_target="session", session_id=f"sess-{task_id}",
            endpoint_url="http://endpoint/v1/chat/completions", model=model,
            max_steps=3,
        ))
        db.add(TaskRun(id=run_id, task_id=task_id, status="queued"))
        db.commit()
    finally:
        db.close()


def _row(factory, run_id):
    db = factory()
    try:
        run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
        return run.status, run.model, (json.loads(run.steps) if run.steps else [])
    finally:
        db.close()


@pytest.mark.asyncio
async def test_two_overlapping_runs_keep_their_own_model_and_step_log(
        task_db, monkeypatch):
    """`B603`'s Verify, at the smallest cap that can show the defect.

    The two runs are forced to interleave — A's first tool, then B's first,
    then A's second, then B's second — so a shared slot cannot accidentally
    come out right by finishing one run before the other starts.
    """
    _seed_llm(task_db, "t-a", "run-a", "model-alpha")
    _seed_llm(task_db, "t-b", "run-b", "model-beta")

    turn = {"a": asyncio.Event(), "b": asyncio.Event()}
    turn["a"].set()

    async def fake_stream(**kwargs):
        who = "a" if kwargs["model"] == "model-alpha" else "b"
        other = "b" if who == "a" else "a"
        for round_num in (1, 2):
            await turn[who].wait()
            turn[who].clear()
            yield ('data: {"type": "tool_start", "tool": "tool_%s_%d", '
                   '"round": %d, "command": "cmd %s"}\n\n'
                   % (who, round_num, round_num, who))
            yield ('data: {"type": "tool_output", "tool": "tool_%s_%d", '
                   '"round": %d, "output": "out %s", "status": "ok"}\n\n'
                   % (who, round_num, round_num, who))
            turn[other].set()
        yield 'data: {"delta": "done %s"}\n\n' % who
        yield "data: [DONE]\n\n"
        # Release the other side so a failure is an assertion, not a hang.
        turn[other].set()

    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream, raising=False)
    monkeypatch.setattr("src.tool_index.get_tool_index", lambda: None)

    sched = _scheduler()
    await asyncio.wait_for(asyncio.gather(
        sched._execute_task_locked("t-a", "run-a", gate_foreground=False,
                                   release_executing=False),
        sched._execute_task_locked("t-b", "run-b", gate_foreground=False,
                                   release_executing=False),
    ), timeout=30)

    status_a, model_a, steps_a = _row(task_db, "run-a")
    status_b, model_b, steps_b = _row(task_db, "run-b")

    assert (status_a, status_b) == ("success", "success")
    assert model_a == "model-alpha", "run A was stamped with another run's model"
    assert model_b == "model-beta", "run B was stamped with another run's model"
    assert [s["tool"] for s in steps_a] == ["tool_a_1", "tool_a_2"], \
        "run A's step log holds another run's steps"
    assert [s["tool"] for s in steps_b] == ["tool_b_1", "tool_b_2"], \
        "run B's step log holds another run's steps"


@pytest.mark.asyncio
async def test_a_finished_run_leaves_nothing_behind(task_db, monkeypatch):
    """A dict keyed by run is only better than one slot if it is emptied. A
    scheduler up for a week holds what is in flight and nothing else."""
    _seed_llm(task_db, "t-c", "run-c", "model-gamma")

    async def fake_stream(**kwargs):
        yield 'data: {"type": "tool_start", "tool": "bash", "round": 1, "command": "ls"}\n\n'
        yield 'data: {"type": "tool_output", "tool": "bash", "round": 1, "output": "x", "status": "ok"}\n\n'
        yield 'data: {"delta": "done"}\n\n'
        yield "data: [DONE]\n\n"

    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream, raising=False)
    monkeypatch.setattr("src.tool_index.get_tool_index", lambda: None)

    sched = _scheduler()
    await sched._execute_task_locked("t-c", "run-c", gate_foreground=False,
                                     release_executing=False)

    assert _row(task_db, "run-c")[2], "the step log never reached the row"
    assert sched.run_steps("run-c") == []
    assert sched.run_model("run-c") is None
    assert sched._runs() == {}


@pytest.mark.asyncio
async def test_a_run_that_fails_still_drops_its_slot(task_db, monkeypatch):
    """The error path is the one a `finally` is for."""
    _seed_llm(task_db, "t-d", "run-d", "model-delta")

    async def fake_stream(**kwargs):
        raise RuntimeError("the endpoint went away")
        yield  # pragma: no cover - makes this an async generator

    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream, raising=False)
    monkeypatch.setattr("src.tool_index.get_tool_index", lambda: None)
    monkeypatch.setattr(
        "src.task_endpoint.task_llm_call_async",
        MagicMock(side_effect=RuntimeError("no fallback either")),
    )

    sched = _scheduler()
    await sched._execute_task_locked("t-d", "run-d", gate_foreground=False,
                                     release_executing=False)
    assert _row(task_db, "run-d")[0] == "error"
    assert sched._runs() == {}


def test_the_cap_this_defect_needed_is_an_operator_setting():
    """The premise `B603` rests on, re-measured from the module rather than
    quoted: the default is one and the ceiling is well above it."""
    from src.task_scheduler import (
        TASK_CONCURRENCY_CAP_DEFAULT, TASK_CONCURRENCY_CAP_MAX,
    )
    assert TASK_CONCURRENCY_CAP_DEFAULT == 1
    assert TASK_CONCURRENCY_CAP_MAX > 1
