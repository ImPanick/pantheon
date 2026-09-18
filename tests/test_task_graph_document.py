# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-26` — the workflow this engine already runs, said out loud.

A workflow here is one nullable column: `ScheduledTask.then_task_id`, "run this
next if the last one succeeded". That is a graph, and nothing in the product
ever called it one, so nothing could draw it, validate it or extend it.

Two things are held here.

  * **The projection is a projection.** The successor is read at request time
    and there is no second place an edge can live, so a stored chain and a
    drawn graph cannot disagree (`Law 14`). Everything that reads
    `then_task_id` keeps working (`Law 1`).
  * **The depth cap had no name.** `_has_chain_cycle` walked ten steps and
    returned "cycle" when it ran out, so an eleven-step chain was refused under
    the name of a different defect and the log said so. Both refusals stand;
    they are now distinguishable.
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
from core.database import ScheduledTask  # noqa: E402
from src.task_scheduler import (  # noqa: E402
    CHAIN_CROSS_OWNER,
    CHAIN_CYCLE,
    CHAIN_MAX_DEPTH,
    CHAIN_REFUSAL_REASONS,
    CHAIN_TOO_DEEP,
    EDGE_WHEN_SUCCESS,
    TaskScheduler,
    build_task_graph,
    task_edges,
)

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
}


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'graph.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


def _chain(factory, ids, owner="alice", loop=False):
    """A straight chain a → b → c …, optionally closed into a loop.

    Rows first, successors second: `then_task_id` is a self-referential foreign
    key, so a row cannot point at one that does not exist yet.
    """
    db = factory()
    try:
        for tid in ids:
            db.add(ScheduledTask(
                id=tid, owner=owner, name=tid, prompt="do work",
                task_type="llm", trigger_type="webhook", status="active",
                output_target="session",
            ))
        db.commit()
        rows = {t.id: t for t in db.query(ScheduledTask).filter(
            ScheduledTask.id.in_(ids)).all()}
        for i, tid in enumerate(ids):
            nxt = ids[i + 1] if i + 1 < len(ids) else (ids[0] if loop else None)
            rows[tid].then_task_id = nxt
        db.commit()
    finally:
        db.close()


# ── the projection ─────────────────────────────────────────────────────────

def test_a_successor_is_one_edge_and_no_successor_is_none():
    assert task_edges(SimpleNamespace(id="a", then_task_id=None)) == []
    assert task_edges(SimpleNamespace(id="a", then_task_id="b")) == [
        {"from": "a", "to": "b", "when": EDGE_WHEN_SUCCESS}]
    # A task object that predates the column at all — the projection reads it
    # defensively rather than raising inside a list endpoint.
    assert task_edges(SimpleNamespace(id="a")) == []


def test_the_graph_is_built_from_the_rows_and_nothing_else(task_db):
    _chain(task_db, ["a", "b", "c"])
    db = task_db()
    try:
        tasks = db.query(ScheduledTask).order_by(ScheduledTask.id).all()
        graph = build_task_graph(tasks)
    finally:
        db.close()

    assert [n["id"] for n in graph["nodes"]] == ["a", "b", "c"]
    assert [(e["from"], e["to"], e["when"]) for e in graph["edges"]] == [
        ("a", "b", EDGE_WHEN_SUCCESS), ("b", "c", EDGE_WHEN_SUCCESS)]
    assert all(e["dangling"] is False for e in graph["edges"])
    assert graph["max_depth"] == CHAIN_MAX_DEPTH
    # Read from the module rather than written out here: `P8-28` adds the
    # second condition and a list transcribed into a test is the copy that goes
    # stale (`Law 6`).
    from src.task_scheduler import EDGE_CONDITIONS
    assert graph["conditions"] == list(EDGE_CONDITIONS)
    assert EDGE_WHEN_SUCCESS in graph["conditions"]


def test_an_edge_out_of_the_set_is_kept_and_marked(task_db):
    """A chain into a task this caller cannot see is a real fact about the
    workflow. Dropping it draws a graph that stops for no reason.

    Reached the way it is actually reached: the list endpoint filters by
    `status`, so a chain into a paused task leaves the set while the row is
    still there. The column's own `ondelete="SET NULL"` means a deleted target
    can never leave a stale id behind, so the filter is the only way this
    arises — and it arises on the default screen.
    """
    _chain(task_db, ["a", "b"], owner="alice")
    db = task_db()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == "b").first().status = "paused"
        db.commit()
        tasks = db.query(ScheduledTask).filter(
            ScheduledTask.status == "active").all()
        graph = build_task_graph(tasks)
    finally:
        db.close()
    assert [n["id"] for n in graph["nodes"]] == ["a"]
    (edge,) = graph["edges"]
    assert (edge["to"], edge["dangling"]) == ("b", True)


@pytest.mark.asyncio
async def test_the_list_endpoint_carries_the_graph_beside_the_tasks(task_db, monkeypatch):
    """`Law 13`. The projection is only real if something is served it, and it
    rides the door that already lists tasks rather than a new one nothing
    fetches."""
    import routes.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    _chain(task_db, ["a", "b"], owner=None)

    scheduler = MagicMock()

    async def _ensure(owner):
        return None

    scheduler.ensure_defaults = _ensure
    router = task_routes.setup_task_routes(scheduler)
    endpoint = next(r.endpoint for r in router.routes
                    if getattr(r, "path", None) == "/api/tasks"
                    and "GET" in getattr(r, "methods", set()))

    out = await endpoint(SimpleNamespace(state=SimpleNamespace(current_user=None)))
    assert {n["id"] for n in out["graph"]["nodes"]} == {"a", "b"}
    assert [(e["from"], e["to"]) for e in out["graph"]["edges"]] == [("a", "b")]

    # And the task rows still carry the column they always carried, beside the
    # projection of it (`Law 1`).
    by_id = {t["id"]: t for t in out["tasks"]}
    assert by_id["a"]["then_task_id"] == "b"
    assert by_id["a"]["edges"] == [{"from": "a", "to": "b", "when": EDGE_WHEN_SUCCESS}]
    assert by_id["b"]["edges"] == []


# ── the cap that had no name ───────────────────────────────────────────────

def test_a_long_chain_is_refused_for_being_long_not_for_looping(task_db):
    """The row's own finding. Both refusals stand; they stop being the same
    word."""
    sched = TaskScheduler.__new__(TaskScheduler)
    ids = [f"n{i}" for i in range(CHAIN_MAX_DEPTH + 3)]
    _chain(task_db, ids)
    db = task_db()
    try:
        assert sched._chain_refusal(db, "n0", owner="alice") == CHAIN_TOO_DEEP
        # Unchanged for every existing caller: still refused.
        assert sched._has_chain_cycle(db, "n0", owner="alice") is True
    finally:
        db.close()


def test_a_real_loop_is_still_called_a_loop(task_db):
    sched = TaskScheduler.__new__(TaskScheduler)
    _chain(task_db, ["x", "y", "z"], loop=True)
    db = task_db()
    try:
        assert sched._chain_refusal(db, "x", owner="alice") == CHAIN_CYCLE
        assert sched._has_chain_cycle(db, "x", owner="alice") is True
    finally:
        db.close()


def test_a_chain_into_another_owner_is_its_own_reason(task_db):
    """It was `True` from `_has_chain_cycle` too, and it is not a cycle either.
    The refusal is unchanged; only the diagnosis improves."""
    sched = TaskScheduler.__new__(TaskScheduler)
    _chain(task_db, ["p", "q"], owner="alice")
    db = task_db()
    try:
        db.query(ScheduledTask).filter(ScheduledTask.id == "q").first().owner = "mallory"
        db.commit()
        assert sched._chain_refusal(db, "p", owner="alice") == CHAIN_CROSS_OWNER
        assert sched._has_chain_cycle(db, "p", owner="alice") is True
    finally:
        db.close()


def test_a_short_chain_runs(task_db):
    sched = TaskScheduler.__new__(TaskScheduler)
    _chain(task_db, ["s", "t"])
    db = task_db()
    try:
        assert sched._chain_refusal(db, "s", owner="alice") is None
        assert sched._has_chain_cycle(db, "s", owner="alice") is False
    finally:
        db.close()


@pytest.mark.asyncio
async def test_the_run_says_why_its_workflow_stopped(task_db, monkeypatch):
    """`Law 15` / `P8-00`. Whoever built the workflow is not reading the server
    log; they are looking at a chain that stopped at step ten for no stated
    reason. The step log is where they look, and it now says which of the three
    refusals happened — in the same words the enum resolves to."""
    import src.builtin_actions as ba
    from core.database import TaskRun
    import json

    ids = [f"d{i}" for i in range(CHAIN_MAX_DEPTH + 3)]
    _chain(task_db, ids, owner=None)
    db = task_db()
    try:
        head = db.query(ScheduledTask).filter(ScheduledTask.id == "d0").first()
        head.task_type = "action"
        head.action = "tidy_sessions"
        head.then_task_id = "d1"
        db.add(TaskRun(id="run-chain", task_id="d0", status="queued"))
        db.commit()
    finally:
        db.close()

    async def fake_action(owner=None, task_name="", progress_cb=None, **kwargs):
        return "did the first step", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fake_action)

    sched = TaskScheduler.__new__(TaskScheduler)
    sched._task_handles = {}
    sched._task_defer_counts = {}
    sched._session_manager = None
    sched._notify_run_outcome = MagicMock(return_value=True)
    sched.add_notification = MagicMock()
    sched._log_to_assistant = MagicMock()

    async def _deliver(*a, **k):
        return None

    sched._deliver_task_result = _deliver

    await sched._execute_task_locked("d0", "run-chain", gate_foreground=False,
                                     release_executing=False)

    db = task_db()
    try:
        steps = json.loads(
            db.query(TaskRun).filter(TaskRun.id == "run-chain").first().steps)
    finally:
        db.close()
    last = steps[-1]["detail"]
    assert CHAIN_REFUSAL_REASONS[CHAIN_TOO_DEEP] in last, last
    assert "cycle" not in last.lower()


def test_every_refusal_has_a_sentence():
    """`Law 10`. The log line is derived from the enum, so the two cannot
    describe the same refusal differently."""
    for reason in (CHAIN_CYCLE, CHAIN_TOO_DEEP, CHAIN_CROSS_OWNER):
        assert CHAIN_REFUSAL_REASONS[reason]
    assert set(CHAIN_REFUSAL_REASONS) == {CHAIN_CYCLE, CHAIN_TOO_DEEP, CHAIN_CROSS_OWNER}
