# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-04`, the chain dry run's server half — the contract in
`/work/notes/P22-WAVE-B.md`, which wb-polish's canvas codes to:

    POST /api/tasks/{id}/run?dry=true&chain=true
      → 200 { ok, dry: true, message, run_id, run,
              chain: [ { task_id, name, when, depth, steps, declined }, ... ] }

Every task reachable from `{id}` along either edge, each once, breadth first,
the head first (`when` None, depth 0, the steps of its recorded dry run); a
successor's `when` is the edge from its first parent in that order; its
`steps` are planned and recorded nowhere; `declined` is None or why it would
not be planned, and a paused successor is planned and says it is paused. A
graph `validate_graph` refuses is 400 with its sentence, before anything is
written. Without `chain=true` the reply is what it was.

**Measured before this file:** `?chain=true` was ignored — the reply had no
`chain`, and a dry run planned the head and advanced nothing (`P8-33`).

Real route through `TestClient`, real `TaskScheduler`, real SQLite file
(`Law 20`); every executor, delivery, chain step and notification is a
recorder that must stay empty.
"""

import json
import sys

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
from src.task_scheduler import CHAIN_MAX_DEPTH, DRY_RUN_HEADLINE, TaskScheduler  # noqa: E402

_REAL_DATABASE_ATTRS = {
    "Base": cdb.Base,
    "SessionLocal": cdb.SessionLocal,
    "ScheduledTask": ScheduledTask,
    "TaskRun": TaskRun,
}

ENTRY_KEYS = {"task_id", "name", "when", "depth", "steps", "declined"}


@pytest.fixture()
def task_db(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "core.database", cdb)
    for attr, value in _REAL_DATABASE_ATTRS.items():
        monkeypatch.setattr(cdb, attr, value, raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'chain-dry.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    return factory


@pytest.fixture()
def calls(monkeypatch):
    seen = []
    for name in list(ba.BUILTIN_ACTIONS):
        async def recorder(_name=name, **kwargs):
            seen.append(("action", _name))
            return "I RAN", True
        monkeypatch.setitem(ba.BUILTIN_ACTIONS, name, recorder)
    return seen


@pytest.fixture()
def scheduler(calls):
    s = TaskScheduler(None)

    def recorded(label):
        async def _rec(*a, **k):
            calls.append((label, a[:1]))
            return "I RAN"
        return _rec

    s._execute_llm_task = recorded("llm")
    s._execute_research_task = recorded("research")
    s._deliver_task_result = recorded("deliver")
    s._run_chained = recorded("chain")
    s._log_to_assistant = lambda *a, **k: calls.append(("chat", a[:1]))
    return s


@pytest.fixture()
def client(task_db, scheduler, monkeypatch, tmp_path):
    import routes.task.task_routes as task_routes
    from tests.helpers.signed_in import signed_in
    # alice is the install's admin, bob is not (`D-2026-10-07-02` §2: before it,
    # an install with no account answered every owner as an admin).
    signed_in(monkeypatch, tmp_path / "auth", admin="alice", members=("bob",))
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    app = FastAPI()

    @app.middleware("http")
    async def _who(request, call_next):
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    app.include_router(task_routes.setup_task_routes(scheduler))
    return TestClient(app)


def _write(factory, rows, edges):
    """Rows, then edges, straight into the database — the way a graph the save
    route would refuse can still exist."""
    db = factory()
    try:
        for tid, extra in rows:
            db.add(ScheduledTask(
                id=tid, owner=extra.get("owner", "alice"), name=extra.get("name", tid),
                prompt=extra.get("prompt"), task_type=extra.get("task_type", "action"),
                action=extra.get("action", "tidy_sessions"),
                trigger_type="webhook", status=extra.get("status", "active"),
                output_target="session", run_count=2))
        db.commit()
        for src, column, dst in edges:
            setattr(db.query(ScheduledTask).filter(ScheduledTask.id == src).first(), column, dst)
        db.commit()
    finally:
        db.close()


def _dry(client, task_id, *, chain=True, user="alice"):
    query = "dry=true&chain=true" if chain else "dry=true"
    return client.post(f"/api/tasks/{task_id}/run?{query}", headers={"x-test-user": user})


def _all_runs(factory):
    db = factory()
    try:
        return [(r.task_id, r.status) for r in db.query(TaskRun).all()]
    finally:
        db.close()


def _tasks(factory):
    db = factory()
    try:
        return {t.id: (t.status, t.last_run, t.next_run, t.run_count)
                for t in db.query(ScheduledTask).all()}
    finally:
        db.close()


# A diamond (Log it is reached from Report and from Page me) with a branch that
# hangs off the second task of a level only (Tell the team), so both "each
# once" and "breadth first" are visible in the order.
DIAMOND = (
    [("h", {"name": "Backup"}), ("a", {"name": "Report"}), ("b", {"name": "Page me"}),
     ("c", {"name": "Log it"}), ("e", {"name": "Tell the team"}), ("d", {"name": "Archive"})],
    [("h", "then_task_id", "a"), ("h", "else_task_id", "b"),
     ("a", "then_task_id", "c"), ("b", "then_task_id", "e"), ("b", "else_task_id", "c"),
     ("c", "then_task_id", "d")],
)


# ── the contract ───────────────────────────────────────────────────────────

def test_every_reachable_task_once_breadth_first_with_the_edge_that_leads_to_it(
        client, task_db, scheduler, calls):
    _write(task_db, *DIAMOND)

    r = _dry(client, "h")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["dry"] is True
    chain = body["chain"]
    assert all(set(entry) == ENTRY_KEYS for entry in chain), chain
    assert [(e["task_id"], e["name"], e["when"], e["depth"]) for e in chain] == [
        ("h", "Backup", None, 0),
        ("a", "Report", "success", 1),
        ("b", "Page me", "error", 1),
        # Reached from Report (works) and from Page me (fails): once, from the
        # first parent in breadth-first order.
        ("c", "Log it", "success", 2),
        ("e", "Tell the team", "success", 2),
        ("d", "Archive", "success", 3),
    ]
    assert all(e["declined"] is None for e in chain)


def test_the_head_is_its_recorded_dry_run_and_the_rest_are_shaped_like_it(
        client, task_db, scheduler, calls):
    _write(task_db, *DIAMOND)

    body = _dry(client, "h").json()

    head = body["chain"][0]
    assert head["steps"] == body["run"]["steps"]
    assert body["run_id"] == body["run"]["id"]
    for entry in body["chain"][1:]:
        assert entry["steps"], entry
        assert {tuple(sorted(step)) for step in entry["steps"]} == {("at", "detail", "kind")}
        assert {step["kind"] for step in entry["steps"]} == {"dry-run"}
        assert entry["steps"][0]["detail"] == DRY_RUN_HEADLINE


def test_successors_are_planned_not_recorded(client, task_db, scheduler, calls):
    """No run row, no history entry, no notification for any of them, and
    nothing about any task moves — the head's dry run is the one row."""
    _write(task_db, *DIAMOND)
    before = _tasks(task_db)

    assert _dry(client, "h").status_code == 200

    assert _all_runs(task_db) == [("h", "skipped")]
    assert _tasks(task_db) == before
    assert scheduler._pending_notifications == []
    assert calls == []
    assert client.get("/api/tasks/a/runs", headers={"x-test-user": "alice"}).json()["runs"] == []


def test_a_successors_plan_is_the_one_its_own_dry_run_would_write(
        client, task_db, scheduler, calls):
    """`Law 7`, driven: one planner. Each successor's lines are exactly what a
    dry run of that task alone records."""
    _write(task_db,
           [("h", {"name": "Fetch"}),
            ("s", {"name": "Summarise", "task_type": "llm", "action": None,
                   "prompt": "Summarise what came in"}),
            ("x", {"name": "Restart", "action": "ssh_command", "prompt": "systemctl restart web"})],
           [("h", "then_task_id", "s"), ("s", "else_task_id", "x")])

    chain = _dry(client, "h").json()["chain"]

    for entry in chain[1:]:
        alone = _dry(client, entry["task_id"], chain=False).json()["run"]
        assert [s["detail"] for s in entry["steps"]] == [s["detail"] for s in alone["steps"]]
    assert any("systemctl restart web" in s["detail"] for s in chain[2]["steps"])


def test_a_paused_successor_is_planned_and_says_it_is_paused(client, task_db, scheduler, calls):
    _write(task_db,
           [("h", {"name": "Backup"}), ("p", {"name": "Message me", "status": "paused"})],
           [("h", "else_task_id", "p")])

    chain = _dry(client, "h").json()["chain"]

    (paused,) = [e for e in chain if e["task_id"] == "p"]
    assert paused["declined"] is None
    assert paused["steps"][0]["detail"] == DRY_RUN_HEADLINE
    assert paused["steps"][-1]["detail"] == "It is paused, so a real run would not start it."
    assert _tasks(task_db)["p"][0] == "paused"


def test_an_admin_only_successor_is_declined_with_the_refusal_and_not_planned(
        client, task_db, scheduler, calls, monkeypatch):
    """The engine would refuse it for this owner, so its plan is not shown
    (the command is the configuration an admin-only task keeps from its
    non-admin owner) and nothing about it changes."""
    monkeypatch.setattr(ts, "owner_has_admin_task_privileges", lambda owner: False)
    _write(task_db,
           [("h", {"name": "Backup"}),
            ("x", {"name": "Reboot", "action": "ssh_command", "prompt": "reboot"})],
           [("h", "else_task_id", "x")])
    before = _tasks(task_db)

    chain = _dry(client, "h").json()["chain"]

    (refused,) = [e for e in chain if e["task_id"] == "x"]
    assert refused["declined"] == "Action 'ssh_command' requires admin privileges"
    assert refused["steps"] == []
    assert _tasks(task_db) == before and calls == []


def test_a_chain_that_runs_today_is_planned_in_full(client, task_db, scheduler, calls):
    """`Law 1`, at the cap: a head plus ten on failure edges runs today, so it
    is planned — eleven entries, depths 0 to 10."""
    ids = [f"e{i}" for i in range(CHAIN_MAX_DEPTH + 1)]
    _write(task_db, [(i, {}) for i in ids],
           [(a, "else_task_id", b) for a, b in zip(ids, ids[1:])])

    r = _dry(client, "e0")

    assert r.status_code == 200, r.text
    assert [(e["task_id"], e["depth"], e["when"]) for e in r.json()["chain"]] == (
        [("e0", 0, None)] + [(f"e{i}", i, "error") for i in range(1, CHAIN_MAX_DEPTH + 1)])


# ── a refused graph ────────────────────────────────────────────────────────

@pytest.mark.parametrize("graph,sentence", [
    (([("h", {"name": "Backup"}), ("c", {"name": "Cleanup"})],
      [("h", "else_task_id", "c"), ("c", "then_task_id", "h")]),
     "The chain loops back on itself: if “Backup” fails it runs “Cleanup”, and if "
     "“Cleanup” works it runs “Backup” again. Remove one of those links to save it."),
    (([(f"e{i}", {}) for i in range(CHAIN_MAX_DEPTH + 2)],
      [(f"e{i}", "else_task_id", f"e{i + 1}") for i in range(CHAIN_MAX_DEPTH + 1)]),
     f"The chain is longer than {CHAIN_MAX_DEPTH} steps: from “e1” to "
     f"“e{CHAIN_MAX_DEPTH + 1}” is {CHAIN_MAX_DEPTH + 1} tasks in a row. Shorten it, "
     f"or give part of it its own trigger."),
    (([("h", {"name": "Backup"}), ("x", {"name": "My handler"}),
       ("y", {"name": "Bob's payroll", "owner": "bob"})],
      [("h", "else_task_id", "x"), ("x", "else_task_id", "y")]),
     "The chain reaches another owner's task, after “My handler”. "
     "A chain can only run your own tasks."),
], ids=["loop", "too-long", "another-owner"])
def test_a_graph_the_rule_refuses_is_400_with_its_sentence_and_nothing_is_written(
        client, task_db, scheduler, calls, graph, sentence):
    """Written straight to the database, as a graph the save route now refuses
    can still exist (from before `P22-01`, or any path that is not the route)."""
    _write(task_db, *graph)
    head = graph[0][0][0]

    r = _dry(client, head)

    assert r.status_code == 400, r.text
    assert r.json()["detail"] == sentence
    assert "payroll" not in r.text
    assert _all_runs(task_db) == [], "a refused chain dry run wrote a run"
    assert calls == []


# ── what did not change ────────────────────────────────────────────────────

def test_without_chain_the_reply_is_what_it_was(client, task_db, scheduler, calls):
    _write(task_db, *DIAMOND)

    body = _dry(client, "h", chain=False).json()

    assert set(body) == {"ok", "dry", "message", "run_id", "run"}
    assert _all_runs(task_db) == [("h", "skipped")]


def test_chain_without_dry_is_refused_in_words(client, task_db, scheduler, calls):
    _write(task_db, *DIAMOND)

    r = client.post("/api/tasks/h/run?chain=true", headers={"x-test-user": "alice"})

    assert r.status_code == 400
    assert r.json()["detail"] == (
        "chain=true goes with dry=true: a real run already continues along its chain.")
    assert _all_runs(task_db) == [] and calls == []


def test_someone_elses_chain_is_not_planned(client, task_db, scheduler, calls):
    _write(task_db, *DIAMOND)

    r = _dry(client, "h", user="bob")

    assert r.status_code == 403
    assert _all_runs(task_db) == []
