# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-28` — the engine's second conditional.

The only conditional in this engine was `run.status == "success"`, written
inline beside the code that follows the chain. So a workflow could say what
comes next and never what to do when the step failed: the failure ended the
chain, and the only trace was an Activity row.

`else_task_id` is the other branch, stored the same way `then_task_id` is and
projected the same way by `task_edges` (`P8-26`). Two things this file holds:

  * **The migration is proved against a database that does not have the
    column.** `Law 20`, and the trap `P8-25` fell into: a migration test run
    against a schema `create_all` just built is a test of `create_all`.
  * **Both failure shapes take the branch.** A task that RETURNED an error and
    a task that RAISED are the same failure to whoever built the workflow, and
    the inline conditional only ever saw the first.
"""

import asyncio
import json
import sqlite3
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
from src.task_scheduler import (  # noqa: E402
    EDGE_COLUMNS,
    EDGE_CONDITIONS,
    EDGE_WHEN_ERROR,
    EDGE_WHEN_SUCCESS,
    TaskScheduler,
    task_edges,
)

# `scheduled_tasks` exactly as it was before `else_task_id`, written out rather
# than derived from the model — a schema derived from the model is the schema
# that already has the column, which is the whole failure this guards.
_LEGACY_SCHEDULED_TASKS = """
CREATE TABLE scheduled_tasks (
    id VARCHAR NOT NULL,
    owner VARCHAR,
    name VARCHAR NOT NULL,
    prompt TEXT,
    task_type VARCHAR,
    action VARCHAR,
    schedule VARCHAR,
    scheduled_time VARCHAR,
    scheduled_day INTEGER,
    scheduled_date DATETIME,
    trigger_type VARCHAR,
    trigger_event VARCHAR,
    trigger_count INTEGER,
    trigger_counter INTEGER,
    next_run DATETIME,
    last_run DATETIME,
    status VARCHAR,
    output_target VARCHAR,
    session_id VARCHAR,
    model VARCHAR,
    endpoint_url VARCHAR,
    run_count INTEGER,
    cron_expression VARCHAR,
    then_task_id VARCHAR,
    webhook_token VARCHAR,
    crew_member_id VARCHAR,
    character_id VARCHAR,
    max_steps INTEGER,
    email_results BOOLEAN,
    notifications_enabled BOOLEAN,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(then_task_id) REFERENCES scheduled_tasks (id) ON DELETE SET NULL,
    UNIQUE (webhook_token)
)
"""


def _legacy_db(tmp_path):
    path = tmp_path / "legacy-tasks.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(_LEGACY_SCHEDULED_TASKS)
        conn.execute(
            "INSERT INTO scheduled_tasks (id, name, task_type, status, "
            "created_at, updated_at) VALUES "
            "('old', 'An existing task', 'llm', 'active', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _columns(path, table="scheduled_tasks"):
    conn = sqlite3.connect(path)
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def test_a_database_without_the_column_rejects_the_write(tmp_path):
    """The defect, stated as a test: this is what an upgraded install does."""
    path = _legacy_db(tmp_path)
    assert "else_task_id" not in _columns(path)
    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO scheduled_tasks (id, name, else_task_id, "
                "created_at, updated_at) VALUES "
                "('new', 'x', 'old', '2026-01-02 00:00:00', '2026-01-02 00:00:00')"
            )
    finally:
        conn.close()


def test_the_migration_adds_the_column_to_a_database_that_never_had_it(
        monkeypatch, tmp_path):
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")

    cdb._migrate_add_scheduled_task_else_column()

    cols = _columns(path)
    assert "else_task_id" in cols, f"migration did not add the column; table is {cols}"

    conn = sqlite3.connect(path)
    try:
        # The row that was already there survives, unset rather than lost.
        assert conn.execute(
            "SELECT else_task_id FROM scheduled_tasks WHERE id='old'"
        ).fetchone()[0] is None
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO scheduled_tasks (id, name, else_task_id, "
            "created_at, updated_at) VALUES "
            "('new', 'x', 'old', '2026-01-02 00:00:00', '2026-01-02 00:00:00')"
        )
        conn.commit()
        assert conn.execute(
            "SELECT else_task_id FROM scheduled_tasks WHERE id='new'"
        ).fetchone()[0] == "old"
        # The foreign key came across with the column, so a migrated database
        # behaves like a fresh one rather than silently accepting a dead id.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scheduled_tasks (id, name, else_task_id, "
                "created_at, updated_at) VALUES "
                "('bad', 'x', 'ghost', '2026-01-02 00:00:00', '2026-01-02 00:00:00')"
            )
    finally:
        conn.close()


def test_the_migration_is_idempotent(monkeypatch, tmp_path):
    """`init_db` runs every migration on every boot."""
    path = _legacy_db(tmp_path)
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_scheduled_task_else_column()
    cdb._migrate_add_scheduled_task_else_column()
    assert _columns(path).count("else_task_id") == 1


def test_init_db_runs_the_migration():
    """A migration nobody calls is the same defect wearing a fix (`Law 13`).

    `init_db`'s own body is walked with `ast` rather than grepped: the name
    appears in this file and in a comment, and `Law 20` is about exactly that
    difference. Parsed from the path rather than through `inspect.getsource`,
    which resolves by the line number recorded at import (`Law 19`).
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(cdb.__file__).read_text(encoding="utf-8"))
    init_db = next(
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "init_db"
    )
    called = {
        node.func.id for node in ast.walk(init_db)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_migrate_add_scheduled_task_else_column" in called


# ── the branch itself ──────────────────────────────────────────────────────

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
        f"sqlite:///{tmp_path / 'branch.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _seed_branch(factory):
    """`head` → `happy` on success, `sad` on failure."""
    db = factory()
    try:
        for tid in ("happy", "sad"):
            db.add(ScheduledTask(
                id=tid, owner=None, name=tid, prompt="", task_type="action",
                action="tidy_sessions", trigger_type="webhook",
                status="active", output_target="session"))
        db.add(ScheduledTask(
            id="head", owner=None, name="head", prompt="", task_type="action",
            action="tidy_sessions", trigger_type="webhook",
            status="active", output_target="session"))
        db.commit()
        head = db.query(ScheduledTask).filter(ScheduledTask.id == "head").first()
        head.then_task_id = "happy"
        head.else_task_id = "sad"
        db.add(TaskRun(id="run-head", task_id="head", status="queued"))
        db.commit()
    finally:
        db.close()


async def _settle():
    """Let the chained task the engine spawned actually start.

    `_advance_chain` hands the next task to `asyncio.create_task`, which
    schedules it rather than running it — so a test that asserts immediately is
    asserting about a coroutine that has not been entered yet. Two yields is
    one more than it needs and does not depend on how many awaits the stub has.
    """
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def _scheduler(chained):
    s = TaskScheduler.__new__(TaskScheduler)
    s._task_handles = {}
    s._task_defer_counts = {}
    s._session_manager = None
    s._notify_run_outcome = MagicMock(return_value=True)
    s.add_notification = MagicMock()
    s._log_to_assistant = MagicMock()

    async def _deliver(*a, **k):
        return None

    async def _run_chained(task_id, *, handoff=None):
        # `P8-29` gave the chain a payload to hand on, so the stub takes it.
        # A stub that pins an internal signature is a test to update when that
        # signature grows, which is what `B603` says about the one in
        # `test_task_shell_tools.py`. This file asserts about WHICH edge is
        # taken; what travels along it is `tests/test_a_chain_hands_on_what_it_made.py`.
        chained.append(task_id)

    s._deliver_task_result = _deliver
    s._run_chained = _run_chained
    return s


def test_a_task_projects_both_of_its_edges():
    node = SimpleNamespace(id="head", then_task_id="happy", else_task_id="sad")
    assert task_edges(node) == [
        {"from": "head", "to": "happy", "when": EDGE_WHEN_SUCCESS},
        {"from": "head", "to": "sad", "when": EDGE_WHEN_ERROR},
    ]
    # Either one alone, and neither.
    assert task_edges(SimpleNamespace(id="h", then_task_id=None, else_task_id="sad")) == [
        {"from": "h", "to": "sad", "when": EDGE_WHEN_ERROR}]
    assert task_edges(SimpleNamespace(id="h", then_task_id=None, else_task_id=None)) == []
    # `Law 1`: a task object from before the column still projects its success
    # edge instead of raising inside a list endpoint.
    assert task_edges(SimpleNamespace(id="h", then_task_id="happy")) == [
        {"from": "h", "to": "happy", "when": EDGE_WHEN_SUCCESS}]


def test_every_condition_names_a_column():
    """`Law 7`. The projection, the engine and the validator read one table."""
    assert set(EDGE_COLUMNS) == set(EDGE_CONDITIONS)
    assert EDGE_COLUMNS[EDGE_WHEN_SUCCESS] == "then_task_id"
    assert EDGE_COLUMNS[EDGE_WHEN_ERROR] == "else_task_id"
    for column in EDGE_COLUMNS.values():
        assert hasattr(ScheduledTask, column), column


@pytest.mark.asyncio
async def test_a_successful_run_takes_the_success_edge(task_db, monkeypatch):
    """`Law 1`. The branch that already existed behaves exactly as it did."""
    _seed_branch(task_db)
    import src.builtin_actions as ba

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        return "all good", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)
    chained = []
    await _scheduler(chained)._execute_task_locked(
        "head", "run-head", gate_foreground=False, release_executing=False)
    await _settle()
    assert chained == ["happy"]


@pytest.mark.asyncio
async def test_a_failing_run_takes_the_failure_edge(task_db, monkeypatch):
    """The row. Before this the chain simply stopped."""
    _seed_branch(task_db)
    import src.builtin_actions as ba

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        return "the mailbox is unreachable", False

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)
    chained = []
    sched = _scheduler(chained)
    await sched._execute_task_locked(
        "head", "run-head", gate_foreground=False, release_executing=False)
    await _settle()
    assert chained == ["sad"]

    db = task_db()
    try:
        run = db.query(TaskRun).filter(TaskRun.id == "run-head").first()
        assert run.status == "error"
        steps = json.loads(run.steps)
    finally:
        db.close()
    # And the run says so, in the surface a person actually opens.
    assert "sad" in steps[-1]["detail"]


@pytest.mark.asyncio
async def test_a_run_that_raised_takes_the_same_edge(task_db, monkeypatch):
    """A task that RETURNED a failure and one that RAISED are the same failure
    to whoever built the workflow. The inline conditional only saw the first,
    because an exception left the function before ever reaching it."""
    _seed_branch(task_db)
    import src.builtin_actions as ba

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        raise RuntimeError("the mailbox exploded")

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)
    chained = []
    await _scheduler(chained)._execute_task_locked(
        "head", "run-head", gate_foreground=False, release_executing=False)
    await _settle()
    assert chained == ["sad"]


@pytest.mark.asyncio
async def test_a_no_op_takes_no_edge_at_all(task_db, monkeypatch):
    """`skipped` is not a failure and is not a success, and the engine's other
    terminal statuses return before the branch. Nothing new fires on them."""
    _seed_branch(task_db)
    import src.builtin_actions as ba

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        raise ba.TaskNoop("nothing to do")

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)
    chained = []
    await _scheduler(chained)._execute_task_locked(
        "head", "run-head", gate_foreground=False, release_executing=False)
    await _settle()
    assert chained == []


@pytest.mark.asyncio
async def test_a_task_with_no_failure_edge_behaves_as_before(task_db, monkeypatch):
    """Every task in every existing install. `else_task_id` is NULL and a
    failed run ends the chain exactly as it always did."""
    _seed_branch(task_db)
    db = task_db()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == "head").first().else_task_id = None
        db.commit()
    finally:
        db.close()

    import src.builtin_actions as ba

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        return "broke", False

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)
    chained = []
    await _scheduler(chained)._execute_task_locked(
        "head", "run-head", gate_foreground=False, release_executing=False)
    await _settle()
    assert chained == []


# ── the API ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_failure_edge_is_created_validated_and_served(task_db, monkeypatch):
    import routes.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    _seed_branch(task_db)

    scheduler = MagicMock()

    async def _ensure(owner):
        return None

    scheduler.ensure_defaults = _ensure
    router = task_routes.setup_task_routes(scheduler)

    def _endpoint(method, path):
        for route in router.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route.endpoint
        raise RuntimeError(f"{method} {path} not found")

    req = SimpleNamespace(state=SimpleNamespace(current_user=None))
    created = await _endpoint("POST", "/api/tasks")(
        req, task_routes.TaskCreate(
            name="Branching", prompt="p", task_type="llm",
            trigger_type="webhook", then_task_id="happy", else_task_id="sad"))
    new_id = created["task"]["id"] if "task" in created else created["id"]

    listed = await _endpoint("GET", "/api/tasks")(req)
    row = next(t for t in listed["tasks"] if t["id"] == new_id)
    assert row["else_task_id"] == "sad"
    assert {(e["when"], e["to"]) for e in row["edges"]} == {
        (EDGE_WHEN_SUCCESS, "happy"), (EDGE_WHEN_ERROR, "sad")}
    assert set(listed["graph"]["conditions"]) == set(EDGE_CONDITIONS)

    # It is validated by the same function the success edge is: a task cannot
    # branch to itself, and cannot branch to a task it does not own.
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await _endpoint("PUT", "/api/tasks/{task_id}")(
            req, new_id, task_routes.TaskUpdate(else_task_id=new_id))
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        await _endpoint("PUT", "/api/tasks/{task_id}")(
            req, new_id, task_routes.TaskUpdate(else_task_id="no-such-task"))
    assert exc.value.status_code == 404
