# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-25` — a run records what it did, not just what it ended up saying.

`TaskRun.steps` was declared and never written: a run stored one result string
for the whole task, so the Activity view could say a task succeeded and never
say what it touched. Both executors are driven here rather than asserted about
(`Law 20`) — the action path through `_execute_action`'s progress callback, and
the LLM path through the agent loop's own SSE stream.
"""

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
    engine = create_engine(
        f"sqlite:///{tmp_path / 'runs.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _seed(factory, *, action="tidy_sessions", task_type="action"):
    db = factory()
    try:
        db.add(ScheduledTask(
            id="t1", owner=None, name="Steps task", prompt="echo hi",
            task_type=task_type, action=action, trigger_type="webhook",
            status="active", output_target="session",
        ))
        db.add(TaskRun(id="r1", task_id="t1", status="queued"))
        db.commit()
    finally:
        db.close()


def _scheduler():
    s = TaskScheduler.__new__(TaskScheduler)
    s._task_handles = {}
    s._task_defer_counts = {}
    s._session_manager = None
    s._notify_run_outcome = MagicMock(return_value=True)
    s.add_notification = MagicMock()
    s._log_to_assistant = MagicMock()
    return s


def _stored_steps(factory, run_id="r1"):
    db = factory()
    try:
        run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
        assert run is not None
        return run.status, (json.loads(run.steps) if run.steps else None)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_an_action_run_records_the_progress_it_reported(task_db, monkeypatch):
    """`_execute_action` already hands every action a progress callback. Those
    lines were overwritten into `result` one after another and lost; the last
    one survived and the rest never existed anywhere."""
    _seed(task_db)

    import src.builtin_actions as ba

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        progress_cb("Scanned 3 sessions")
        progress_cb("Deleted 1 empty session")
        return "Removed 1 session", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)

    sched = _scheduler()
    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)

    status, steps = _stored_steps(task_db)
    assert status == "success"
    assert steps is not None, "TaskRun.steps is still never written"
    assert [s.get("detail") for s in steps] == [
        "Scanned 3 sessions", "Deleted 1 empty session"]
    assert all(s.get("kind") == "progress" for s in steps)


@pytest.mark.asyncio
async def test_an_llm_run_records_the_tools_the_agent_called(task_db, monkeypatch):
    _seed(task_db, action=None, task_type="llm")

    events = [
        'data: {"type": "tool_start", "tool": "web_search", "round": 1, '
        '"command": "search pantheon"}\n\n',
        'data: {"type": "tool_output", "tool": "web_search", "round": 1, '
        '"output": "three results", "exit_code": 0}\n\n',
        'data: {"type": "tool_start", "tool": "write_file", "round": 2, '
        '"command": "notes.md"}\n\n',
        'data: {"type": "tool_output", "tool": "write_file", "round": 2, '
        '"output": "written", "exit_code": 0}\n\n',
        'data: {"delta": "All done."}\n\n',
        'data: [DONE]\n\n',
    ]

    async def fake_stream(**kwargs):
        for e in events:
            yield e

    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_stream, raising=False)

    sched = _scheduler()
    task = SimpleNamespace(
        id="t1", name="Steps task", prompt="do the thing", owner=None,
        max_steps=None,
    )
    text = await sched._run_agent_loop(
        "http://localhost:11434/v1/chat/completions", "m", task, "sess-1",
        run_id="r1")

    assert text.strip() == "All done."
    # `P8-27`. The log is addressed by run now, not by "whichever run this
    # scheduler touched last".
    steps = sched.run_steps("r1")
    assert steps, "the agent loop recorded no steps"
    assert [(s["tool"], s["round"], s["status"]) for s in steps] == [
        ("web_search", 1, "ok"), ("write_file", 2, "ok")]
    # `detail` only ever comes from `tool_start` and `output` only from
    # `tool_output`, so asserting both is what makes this a test of the pair
    # rather than of whichever half happened to fire last: dropping the start
    # events still yields two steps with the right tool, round and status.
    assert [s["detail"] for s in steps] == ["search pantheon", "notes.md"]
    assert [s["output"] for s in steps] == ["three results", "written"]


@pytest.mark.asyncio
async def test_steps_survive_a_failing_run(task_db, monkeypatch):
    """The run that failed is the one somebody opens the step log for."""
    _seed(task_db)

    import src.builtin_actions as ba

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        progress_cb("Opened the mailbox")
        raise RuntimeError("mailbox went away")

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)

    sched = _scheduler()
    await sched._execute_task_locked(
        "t1", "r1", gate_foreground=False, release_executing=False)

    status, steps = _stored_steps(task_db)
    assert status == "error"
    assert steps and steps[0]["detail"] == "Opened the mailbox"


@pytest.mark.asyncio
async def test_the_step_log_reaches_the_wire(task_db, monkeypatch):
    """`P8-25` said filling the column "upgrades the shipped activity view
    instantly with no new UI". It could not have: no response had ever carried
    the column. `GET /api/tasks/{id}/runs` carries it now, and the Activity
    feed carries the count."""
    import routes.task_routes as task_routes

    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    _seed(task_db)

    db = task_db()
    try:
        run = db.query(TaskRun).filter(TaskRun.id == "r1").first()
        run.status = "success"
        run.result = "done"
        run.steps = json.dumps([
            {"kind": "progress", "detail": "Scanned 3 sessions"},
            {"kind": "progress", "detail": "Deleted 1 empty session"},
        ])
        db.commit()
    finally:
        db.close()

    def _endpoint(method, path):
        router = task_routes.setup_task_routes(MagicMock())
        for route in router.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route.endpoint
        raise RuntimeError(f"{method} {path} not found")

    req = SimpleNamespace(state=SimpleNamespace(current_user=None))

    history = await _endpoint("GET", "/api/tasks/{task_id}/runs")(req, "t1")
    row = history["runs"][0]
    assert [s["detail"] for s in row["steps"]] == [
        "Scanned 3 sessions", "Deleted 1 empty session"]
    assert row["step_count"] == 2

    # The list feed carries the count and not two hundred step bodies per row.
    recent = await _endpoint("GET", "/api/tasks/runs/recent")(req)
    feed_row = next(r for r in recent["runs"] if r["id"] == "r1")
    assert feed_row["step_count"] == 2
    assert feed_row["steps"] == []


def test_a_run_from_before_the_column_reads_as_no_log():
    """Every existing row. It must not raise and must not invent a log."""
    from routes.task_routes import _run_steps

    assert _run_steps(SimpleNamespace(id="r", steps=None)) == []
    assert _run_steps(SimpleNamespace(id="r", steps="")) == []
    assert _run_steps(SimpleNamespace(id="r", steps="not json")) == []
    assert _run_steps(SimpleNamespace(id="r", steps='{"not": "a list"}')) == []
    assert _run_steps(SimpleNamespace(id="r", steps='[{"kind": "progress"}]')) == [
        {"kind": "progress"}]
