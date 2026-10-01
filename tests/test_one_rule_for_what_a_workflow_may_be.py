# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-01` — one rule for what a workflow may be, checked at save and at run.

**The premise, measured 2026-10-01 by driving it on the tree before this
change.** `_chain_refusal` followed `then_task_id` and nothing else, while
`_advance_chain` takes both `EDGE_COLUMNS` edges. So *"if the backup fails run
cleanup; when cleanup works run the backup"* was accepted by `PUT /api/tasks`,
and `_chain_refusal` answered `None` from both ends of it — the two could run
each other with no cap — and `None` again from step two of a thirteen-step chain
wired on failure alone. Nothing checked at save beyond one edge's own target.

Separately, `_advance_chain` wrote *"Continued to X"* and then `_run_chained`
returned without a word when X was already in flight, so the run said it
continued to a task that never ran.

Everything here drives the real code (`Law 20`): the real routes through
`TestClient` against a real SQLite file, the real `_execute_task_locked` /
`_advance_chain` against rows written straight to the database (the way a graph
the route would refuse can still exist), and `validate_graph` itself against
the walk it replaced, on graphs this file generates.

The new names are imported inside the tests that need them, so on the old tree
each test fails on its own assertion about behaviour rather than the whole file
failing to import.
"""

import asyncio
import json
import random
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import src.builtin_actions as ba  # noqa: E402
import src.task_scheduler as ts  # noqa: E402
from core.database import ScheduledTask, TaskRun  # noqa: E402
from src.task_scheduler import (  # noqa: E402
    CHAIN_CROSS_OWNER,
    CHAIN_CYCLE,
    CHAIN_MAX_DEPTH,
    CHAIN_REFUSAL_REASONS,
    CHAIN_TOO_DEEP,
    EDGE_CONDITIONS,
    TaskScheduler,
)

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
        f"sqlite:///{tmp_path / 'workflow.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


@pytest.fixture()
def client(task_db, monkeypatch):
    """The real task router, behind a stand-in for the auth middleware that
    sets `request.state.current_user` from a header — the attribute
    `get_current_user` reads and nothing else."""
    import routes.task.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(MagicMock()))
    return TestClient(app)


def _create(client, name, *, user="alice", **fields):
    body = {"name": name, "prompt": "do the thing", "task_type": "llm",
            "trigger_type": "webhook", **fields}
    return client.post("/api/tasks", json=body, headers={"x-test-user": user})


def _put(client, task_id, *, user="alice", **fields):
    return client.put(f"/api/tasks/{task_id}", json=fields,
                      headers={"x-test-user": user})


def _made(client, name, **kw):
    r = _create(client, name, **kw)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _row(factory, task_id):
    db = factory()
    try:
        t = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        return None if t is None else {
            "name": t.name, "then": t.then_task_id, "else": t.else_task_id}
    finally:
        db.close()


def _write(factory, rows, edges):
    """Rows, then edges, straight into the database — the way a graph the
    route now refuses can still exist: written before this row, or by any
    path that is not the route."""
    db = factory()
    try:
        for tid, owner, extra in rows:
            db.add(ScheduledTask(
                id=tid, owner=owner, name=extra.get("name", tid), prompt="",
                task_type=extra.get("task_type", "action"),
                action=extra.get("action", "tidy_sessions"),
                trigger_type="webhook", status="active", output_target="session"))
        db.commit()
        for src, column, dst in edges:
            row = db.query(ScheduledTask).filter(ScheduledTask.id == src).first()
            setattr(row, column, dst)
        db.commit()
    finally:
        db.close()


# ── at save: the row's own Verify, through the real route ──────────────────

def test_the_failure_loop_is_refused_on_save_and_names_both(client, task_db):
    """The row's `Verify:`, word for word. The person wires *"when cleanup works
    run the backup"*, then *"if the backup fails run cleanup"*, and Save says it
    loops — from the link they just drew, naming both."""
    backup = _made(client, "Backup")
    cleanup = _made(client, "Cleanup", then_task_id=backup)

    r = _put(client, backup, else_task_id=cleanup)

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == (
        "The chain loops back on itself: if “Backup” fails it runs "
        "“Cleanup”, and if “Cleanup” works it runs "
        "“Backup” again. Remove one of those links to save it.")
    # Refused means not saved.
    assert _row(task_db, backup)["else"] is None


def test_the_same_loop_closed_from_the_other_end_is_refused_too(client, task_db):
    cleanup = _made(client, "Cleanup")
    backup = _made(client, "Backup", else_task_id=cleanup)   # fine on its own

    r = _put(client, cleanup, then_task_id=backup)

    assert r.status_code == 400, r.text
    assert r.json()["detail"].startswith(
        "The chain loops back on itself: if “Cleanup” works it runs "
        "“Backup”, and if “Backup” fails it runs "
        "“Cleanup” again.")
    assert _row(task_db, cleanup)["then"] is None


def test_a_mixed_loop_of_three_is_refused_naming_every_link(client, task_db):
    a = _made(client, "Fetch")
    b = _made(client, "Summarise")
    c = _made(client, "Alert me")
    assert _put(client, a, then_task_id=b).status_code == 200
    assert _put(client, b, else_task_id=c).status_code == 200

    r = _put(client, c, then_task_id=a)

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == (
        "The chain loops back on itself: if “Alert me” works it runs "
        "“Fetch”, if “Fetch” works it runs “Summarise”, "
        "and if “Summarise” fails it runs “Alert me” again. "
        "Remove one of those links to save it.")
    assert _row(task_db, c)["then"] is None


def test_a_loop_waiting_downstream_is_refused_at_create(client, task_db):
    """Nothing can lead to a task that does not exist yet, so a loop THROUGH a
    new task cannot be made by creating it. What create can find is a loop the
    new task would lead into — here one written before this row, on failure."""
    _write(task_db,
           [("x", "alice", {"name": "Prepare"}),
            ("a", "alice", {"name": "Backup"}), ("b", "alice", {"name": "Cleanup"})],
           [("x", "then_task_id", "a"),
            ("a", "else_task_id", "b"), ("b", "then_task_id", "a")])

    r = _create(client, "Nightly", else_task_id="x")

    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail.startswith(CHAIN_REFUSAL_REASONS[CHAIN_CYCLE].capitalize()), detail
    assert "“Backup” fails it runs “Cleanup”" in detail
    assert "“Cleanup” works it runs “Backup” again" in detail
    # The loop, and only the loop: the step that leads into it is not in it.
    assert "Prepare" not in detail
    db = task_db()
    try:
        assert db.query(ScheduledTask).filter(ScheduledTask.name == "Nightly").count() == 0
    finally:
        db.close()


def test_a_chain_too_long_on_failure_edges_is_refused_where_it_is_made(client, task_db):
    """The cap counts failure edges now. A head plus ten — what runs today — is
    saved; the edit that makes it a head plus eleven is refused, at the tail
    where the person made it, by the walk from step two that it lengthens."""
    ids = [_made(client, f"e{i}") for i in range(CHAIN_MAX_DEPTH + 2)]
    for a, b in zip(ids[:CHAIN_MAX_DEPTH], ids[1:CHAIN_MAX_DEPTH + 1]):
        assert _put(client, a, else_task_id=b).status_code == 200

    r = _put(client, ids[CHAIN_MAX_DEPTH], else_task_id=ids[CHAIN_MAX_DEPTH + 1])

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == (
        f"The chain is longer than {CHAIN_MAX_DEPTH} steps: from “e1” to "
        f"“e{CHAIN_MAX_DEPTH + 1}” is {CHAIN_MAX_DEPTH + 1} tasks in a row. "
        f"Shorten it, or give part of it its own trigger.")
    assert _row(task_db, ids[CHAIN_MAX_DEPTH])["else"] is None


def test_a_failure_edge_into_another_owners_chain_is_refused_unnamed(client, task_db):
    """The route already 404s a direct edge to someone else's task. Through a
    failure edge one step further on — written before this row — it did not,
    and must not name the other person's task while refusing it."""
    _write(task_db,
           [("x", "alice", {"name": "My handler"}),
            ("y", "bob", {"name": "Bob's payroll export"})],
           [("x", "else_task_id", "y")])

    r = _create(client, "Nightly", else_task_id="x")

    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail == (
        "The chain reaches another owner's task, after “My handler”. "
        "A chain can only run your own tasks.")
    assert "payroll" not in detail


def test_every_chain_that_runs_today_still_saves(client, task_db):
    """`Law 1`. Each of these runs on the engine before and after this row, so
    each must still save."""
    # A head plus ten on success — the longest chain the engine runs.
    straight = [_made(client, f"s{i}") for i in range(CHAIN_MAX_DEPTH + 1)]
    for a, b in zip(straight, straight[1:]):
        assert _put(client, a, then_task_id=b).status_code == 200
    # One task, both branches.
    happy, sad = _made(client, "Happy"), _made(client, "Sad")
    assert _create(client, "Branch", then_task_id=happy,
                   else_task_id=sad).status_code == 200
    # A diamond: the same task reached two ways is not a loop.
    join = _made(client, "Join")
    left = _made(client, "Left", then_task_id=join)
    assert _create(client, "Fork", then_task_id=join,
                   else_task_id=left).status_code == 200
    # Two tasks failing into one handler, which is itself a short chain.
    page = _made(client, "Page me")
    handler = _made(client, "Log it", then_task_id=page)
    for name in ("Backup", "Sync"):
        assert _create(client, name, else_task_id=handler).status_code == 200
    # And clearing an edge is always allowed.
    assert _put(client, straight[0], then_task_id="").status_code == 200


def test_an_edit_that_moves_no_edge_is_not_refused_for_an_older_loop(client, task_db):
    """`Law 1`. A loop written before this row is the engine's to refuse at
    run, in that run's log; renaming a task in it is not the save that made it."""
    _write(task_db,
           [("a", "alice", {"name": "Backup"}), ("b", "alice", {"name": "Cleanup"})],
           [("a", "else_task_id", "b"), ("b", "then_task_id", "a")])

    assert _put(client, "a", name="Backup (nightly)").status_code == 200
    # The form sends both pickers on every save; the same values are no change.
    assert _put(client, "a", then_task_id="", else_task_id="b",
                name="Backup").status_code == 200
    assert _row(task_db, "a") == {"name": "Backup", "then": None, "else": "b"}


# ── at run: the engine asks the same rule ──────────────────────────────────

def _scheduler(chained=None):
    s = TaskScheduler.__new__(TaskScheduler)
    s._task_handles = {}
    s._task_defer_counts = {}
    s._session_manager = None
    s._notify_run_outcome = MagicMock(return_value=True)
    s.add_notification = MagicMock()
    s._log_to_assistant = MagicMock()
    s._deliver_task_result = AsyncMock(return_value=None)
    if chained is not None:
        async def _run_chained(task_id, *, handoff=None, started_by=None):  # `B1047` passes who started the chain
            chained.append(task_id)
        s._run_chained = _run_chained
    return s


async def _settle():
    for _ in range(3):
        await asyncio.sleep(0)


def _steps(factory, run_id):
    db = factory()
    try:
        return json.loads(db.query(TaskRun).filter(TaskRun.id == run_id).first().steps)
    finally:
        db.close()


def _queue(factory, task_id, run_id):
    db = factory()
    try:
        db.add(TaskRun(id=run_id, task_id=task_id, status="queued"))
        db.commit()
    finally:
        db.close()


def _failing(monkeypatch):
    async def broke(**kwargs):
        return "the disk is full", False
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", broke)


@pytest.mark.asyncio
async def test_the_engine_refuses_a_failure_loop_written_straight_to_the_database(
        task_db, monkeypatch):
    """Bypassing the route entirely. On the old tree the failing Backup
    continued to Cleanup — and Cleanup, working, would have continued back."""
    _write(task_db,
           [("a", None, {"name": "Backup"}), ("b", None, {"name": "Cleanup"})],
           [("a", "else_task_id", "b"), ("b", "then_task_id", "a")])
    _queue(task_db, "a", "run-a")
    _failing(monkeypatch)
    chained = []

    await _scheduler(chained)._execute_task_locked(
        "a", "run-a", gate_foreground=False, release_executing=False)
    await _settle()

    assert chained == []
    assert _steps(task_db, "run-a")[-1]["detail"] == (
        f"Did not continue to Cleanup: {CHAIN_REFUSAL_REASONS[CHAIN_CYCLE]}")


@pytest.mark.asyncio
async def test_the_engine_refuses_a_failure_chain_past_the_cap(task_db, monkeypatch):
    ids = [f"d{i}" for i in range(CHAIN_MAX_DEPTH + 3)]
    _write(task_db, [(i, None, {}) for i in ids],
           [(a, "else_task_id", b) for a, b in zip(ids, ids[1:])])
    _queue(task_db, "d0", "run-d0")
    _failing(monkeypatch)
    chained = []

    await _scheduler(chained)._execute_task_locked(
        "d0", "run-d0", gate_foreground=False, release_executing=False)
    await _settle()

    assert chained == []
    assert _steps(task_db, "run-d0")[-1]["detail"] == (
        f"Did not continue to d1: {CHAIN_REFUSAL_REASONS[CHAIN_TOO_DEEP]}")


@pytest.mark.asyncio
async def test_the_engine_refuses_a_failure_edge_into_another_owner(task_db, monkeypatch):
    _write(task_db,
           [("h", "alice", {"name": "Backup"}), ("x", "alice", {"name": "Handler"}),
            ("y", "bob", {"name": "Theirs"})],
           [("h", "else_task_id", "x"), ("x", "else_task_id", "y")])
    _queue(task_db, "h", "run-h")
    _failing(monkeypatch)
    chained = []

    await _scheduler(chained)._execute_task_locked(
        "h", "run-h", gate_foreground=False, release_executing=False)
    await _settle()

    assert chained == []
    assert _steps(task_db, "run-h")[-1]["detail"] == (
        f"Did not continue to Handler: {CHAIN_REFUSAL_REASONS[CHAIN_CROSS_OWNER]}")


def test_has_chain_cycle_keeps_its_name_and_its_boolean(task_db):
    """`Law 1`. The old question, asked the old way, about the new walk."""
    _write(task_db, [("a", "alice", {}), ("b", "alice", {}), ("c", "alice", {})],
           [("a", "else_task_id", "b"), ("b", "then_task_id", "a")])
    s = TaskScheduler.__new__(TaskScheduler)
    db = task_db()
    try:
        assert s._has_chain_cycle(db, "b", owner="alice") is True
        assert s._chain_refusal(db, "b", owner="alice") == CHAIN_CYCLE
        assert s._has_chain_cycle(db, "c", owner="alice") is False
    finally:
        db.close()


def test_save_and_run_ask_the_same_function(client, task_db, monkeypatch):
    """`Law 7`, driven rather than grepped: wrap the one function and watch both
    callers reach it — the route's save and the engine's continue."""
    from src.task_scheduler import validate_graph
    asked = []

    def watching(tasks, **kw):
        asked.append(kw.get("starts"))
        return validate_graph(tasks, **kw)

    monkeypatch.setattr(ts, "validate_graph", watching)
    a, b = _made(client, "A"), _made(client, "B")
    assert _put(client, a, else_task_id=b).status_code == 200
    assert asked, "the save did not ask validate_graph"

    asked.clear()
    db = task_db()
    try:
        TaskScheduler.__new__(TaskScheduler)._chain_refusal(db, b, owner="alice")
    finally:
        db.close()
    assert asked == [[b]], asked


# ── nothing the old walk refused is now permitted ──────────────────────────

def _old_walk(rows, start_id, owner, max_depth=CHAIN_MAX_DEPTH):
    """`_chain_refusal` as it stood before `P22-01`, verbatim but for the
    query, which is a dict lookup here. The reference this file holds the new
    rule to."""
    visited = set()
    current = start_id
    for _ in range(max_depth):
        if current in visited:
            return CHAIN_CYCLE
        visited.add(current)
        task = rows.get(current)
        if owner is not None and task and task.owner != owner:
            return CHAIN_CROSS_OWNER
        if not task or not task.then_task_id:
            return None
        current = task.then_task_id
    return CHAIN_TOO_DEEP


def _random_graph(rng, n, *, else_edges=True):
    ids = [f"n{i}" for i in range(n)]
    rows = {}
    for tid in ids:
        rows[tid] = SimpleNamespace(
            id=tid, owner="bob" if rng.random() < 0.08 else "alice",
            then_task_id=rng.choice(ids + [None, None, "gone"]) if rng.random() < 0.85 else None,
            else_task_id=(rng.choice(ids + [None, None]) if else_edges and rng.random() < 0.4
                          else None))
    return rows


def test_nothing_the_old_walk_refused_is_permitted():
    """The row's own guarantee, over 600 generated graphs and every start in
    them: wherever the success-only walk refused, the new rule refuses for the
    SAME reason; and with no failure edge in the graph the two agree exactly.
    Graphs run long on purpose — the chains here pass the cap often."""
    from src.task_scheduler import validate_graph
    rng = random.Random(22_01)
    new_refusals_only_via_else = 0
    for trial in range(600):
        rows = _random_graph(rng, rng.randint(2, 16), else_edges=trial % 3 != 0)
        has_else = any(r.else_task_id for r in rows.values())
        for start in rows:
            for owner in ("alice", None):
                old = _old_walk(rows, start, owner)
                found = validate_graph(list(rows.values()), starts=[start], owner=owner)
                new = found.reason if found else None
                if old is not None:
                    assert new == old, (trial, start, owner, old, new)
                elif not has_else:
                    assert new is None, (trial, start, owner, new)
                elif new is not None:
                    new_refusals_only_via_else += 1
    # The generator reaches the case this row is about, or the test proves less
    # than it claims.
    assert new_refusals_only_via_else > 100, new_refusals_only_via_else


def test_the_engine_reads_enough_of_the_database_to_answer(task_db):
    """`load_chain_rows` fetches a level at a time and stops at the cap. If it
    stopped one level short, a long chain would look like it ended — permitted.
    Generated graphs written to the real database, `_chain_refusal` against the
    pure rule over every row."""
    from src.task_scheduler import validate_graph
    rng = random.Random(1001)
    s = TaskScheduler.__new__(TaskScheduler)
    for trial in range(30):
        rows = _random_graph(rng, rng.randint(8, 18))
        db = task_db()
        try:
            db.query(ScheduledTask).delete()
            db.commit()
            for r in rows.values():
                db.add(ScheduledTask(id=r.id, owner=r.owner, name=r.id, prompt="",
                                     task_type="llm", trigger_type="webhook",
                                     status="active", output_target="session"))
            db.commit()
            for r in rows.values():
                row = db.query(ScheduledTask).filter(ScheduledTask.id == r.id).first()
                row.then_task_id = r.then_task_id if r.then_task_id in rows else None
                row.else_task_id = r.else_task_id
            db.commit()
            stored = db.query(ScheduledTask).all()
            for start in rows:
                whole = validate_graph(stored, starts=[start], owner="alice")
                assert s._chain_refusal(db, start, owner="alice") == (
                    whole.reason if whole else None), (trial, start)
        finally:
            db.close()


def test_every_condition_has_words_and_every_reason_a_sentence():
    """`Law 10`. A third condition, or a fourth reason, cannot ship without the
    words a person reads for it."""
    from src.task_scheduler import EDGE_WORDS, GraphRefusal, describe_graph_refusal
    assert set(EDGE_WORDS) == set(EDGE_CONDITIONS)
    for reason in CHAIN_REFUSAL_REASONS:
        said = describe_graph_refusal(GraphRefusal(reason, "a", ()))
        assert said.startswith(CHAIN_REFUSAL_REASONS[reason].capitalize())


# ── the run says what happened to the next step ────────────────────────────

def _seed_chain(factory, heads=("head",)):
    rows = [(h, None, {"name": f"Step {h}"}) for h in heads]
    rows.append(("tail", None, {"name": "Second step"}))
    _write(factory, rows, [(h, "then_task_id", "tail") for h in heads])
    for h in heads:
        _queue(factory, h, f"run-{h}")


def _working(monkeypatch):
    async def fine(**kwargs):
        return "done", True
    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fine)


def _real_chain_scheduler(started):
    """The real `_run_chained` and the real `_executing` set; only the
    successor's own execution is recorded instead of run."""
    s = _scheduler()
    s._executing = set()
    s._executing_lock = asyncio.Lock()

    async def _execute_task(task_id, **kwargs):
        started.append(task_id)

    s._execute_task = _execute_task
    return s


@pytest.mark.asyncio
async def test_a_successor_already_running_is_said_rather_than_claimed(
        task_db, monkeypatch):
    """The row's second half. On the old tree this run's log said
    "Continued to Second step" and `_run_chained` dropped it in silence."""
    _seed_chain(task_db)
    _working(monkeypatch)
    started = []
    s = _real_chain_scheduler(started)
    s._executing.add("tail")          # already in flight: a tick, a button, a chain

    await s._execute_task_locked("head", "run-head", gate_foreground=False,
                                 release_executing=False)
    await _settle()

    assert started == []
    last = _steps(task_db, "run-head")[-1]["detail"]
    assert last != "Continued to Second step", "the run claims a step that never ran"
    from src.task_scheduler import CHAIN_ALREADY_RUNNING
    assert last == f"Did not continue to Second step: {CHAIN_ALREADY_RUNNING}"


@pytest.mark.asyncio
async def test_the_claim_is_held_when_the_line_is_written(task_db, monkeypatch):
    """"Continued to" is written only with the claim already taken, so nothing
    can take it between the line and the run."""
    _seed_chain(task_db)
    _working(monkeypatch)
    started = []
    s = _real_chain_scheduler(started)

    await s._execute_task_locked("head", "run-head", gate_foreground=False,
                                 release_executing=False)

    assert "tail" in s._executing        # before the spawned run has started
    assert _steps(task_db, "run-head")[-1]["detail"] == "Continued to Second step"
    await _settle()
    assert started == ["tail"]


@pytest.mark.asyncio
async def test_two_steps_into_one_successor_one_continues_and_one_says_why(
        task_db, monkeypatch):
    """A join. Both finish in the same tick; one continues, and the other's run
    says the next step was already running — not that it continued."""
    _seed_chain(task_db, heads=("h1", "h2"))
    _working(monkeypatch)
    started = []
    s = _real_chain_scheduler(started)

    await s._execute_task_locked("h1", "run-h1", gate_foreground=False,
                                 release_executing=False)
    await s._execute_task_locked("h2", "run-h2", gate_foreground=False,
                                 release_executing=False)
    await _settle()

    assert started == ["tail"]
    assert _steps(task_db, "run-h1")[-1]["detail"] == "Continued to Second step"
    assert _steps(task_db, "run-h2")[-1]["detail"].startswith(
        "Did not continue to Second step: ")


@pytest.mark.asyncio
async def test_the_claim_is_released_when_the_chained_run_ends(task_db, monkeypatch):
    """The real scheduler end to end: the successor runs through the real
    `_execute_task`, whose `finally` gives the claim back — so moving the claim
    did not leave a chained task stuck "running" for ever."""
    _seed_chain(task_db)
    ran = []

    async def fine(**kwargs):
        ran.append(1)
        return "done", True

    monkeypatch.setitem(ba.BUILTIN_ACTIONS, "tidy_sessions", fine)
    s = TaskScheduler(None)
    s._notify_run_outcome = MagicMock(return_value=True)
    s.add_notification = MagicMock()
    s._log_to_assistant = MagicMock()
    s._deliver_task_result = AsyncMock(return_value=None)

    await s._execute_task_locked("head", "run-head", gate_foreground=False,
                                 release_executing=False)
    for _ in range(50):
        await asyncio.sleep(0)
        if len(ran) == 2 and "tail" not in s._executing:
            break

    assert len(ran) == 2, "the successor did not run"
    assert "tail" not in s._executing
