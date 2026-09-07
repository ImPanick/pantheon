# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rest of the loop is measured (`P14-02`).

`P14-01` gave the table a timestamp. This fills it in: how long a turn took,
which tools ran and which failed, whether retrieval found anything, and whether
anyone answers the approval ladder.

The tests that matter here are not "does it write a row". They are:

  - a tool that FAILS BY RETURNING is counted as a failure. Almost every tool in
    this codebase reports errors in its result dict rather than by raising, so
    counting exceptions alone reports a 0% failure rate — a metric worse than
    none, because it is reassuring.
  - retrieval that returns nothing because the store is DOWN is distinguished
    from retrieval that returned nothing because there was no match. They look
    identical to a user and are different bugs, and conflating them makes the
    hit rate flattering.
  - instrumentation never changes behaviour. A measured tool returns what an
    unmeasured one did, and a raising tool still raises.
"""
import asyncio
import json
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_db
from core.database import Base, Event
from src import events as ev


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/p1402.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    monkeypatch.setattr("routes.chat_helpers.SessionLocal", maker)
    monkeypatch.setattr(ev, "_last_prune", 0.0)   # no pruning mid-test
    monkeypatch.setattr(ev.time, "monotonic", ev.time.monotonic)
    global _maker
    _maker = maker
    yield maker
    engine.dispose()


def rows(kind=None):
    db = _maker()
    try:
        q = db.query(Event)
        if kind:
            q = q.filter(Event.kind == kind)
        return q.all()
    finally:
        db.close()


# --- turn latency ---------------------------------------------------------

def test_turn_latency_lands_on_the_round(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(ev.time, "monotonic", lambda: clock["t"])
    ev._turn_started.set(None)
    ev.mark_turn_start()
    clock["t"] = 102.5
    ev.record_llm_round("p1402-a", {"input_tokens": 1, "output_tokens": 1})
    (r,) = rows("llm_round")
    assert r.duration_ms == 2500


def test_without_a_marked_start_duration_is_null_not_zero(monkeypatch):
    """A missing measurement is not a fast one. Zero would sit in a dashboard
    looking like the best turn ever recorded."""
    ev._turn_started.set(None)
    ev.record_llm_round("p1402-b", {"input_tokens": 1, "output_tokens": 1})
    (r,) = rows("llm_round")
    assert r.duration_ms is None


def test_marking_twice_does_not_restart_the_clock(monkeypatch):
    clock = {"t": 10.0}
    monkeypatch.setattr(ev.time, "monotonic", lambda: clock["t"])
    ev._turn_started.set(None)
    ev.mark_turn_start()
    clock["t"] = 15.0
    ev.mark_turn_start()          # a retry inside one request
    clock["t"] = 20.0
    assert ev._turn_elapsed_ms() == 10000


def test_both_chat_entry_points_start_the_clock():
    """The tests above call `mark_turn_start` directly, so they say nothing
    about whether anything ever calls it — deleting the call from `chat_stream`
    passed all of them cleanly.

    Two handlers, and both matter: `/api/chat` and `/api/chat_stream` are
    separate paths, and an unmeasured one shows up as a dashboard where half the
    turns have no latency at all.
    """
    src = open("routes/chat_routes.py", encoding="utf-8").read()
    for handler in ("async def chat_endpoint(", "async def chat_stream("):
        i = src.index(handler)
        body = src[i:i + 900]
        assert "_mark_turn_start()" in body, f"{handler} never starts the turn clock"
    # ...and the shim it calls actually reaches the real function.
    i = src.index("def _mark_turn_start()")
    assert "from src.events import mark_turn_start" in src[i:i + 400]


# --- tool calls -----------------------------------------------------------

class _Block:
    def __init__(self, tool_type="shell", content="x"):
        self.tool_type = tool_type
        self.content = content


async def _run_tool(monkeypatch, result, raises=False):
    import src.tool_execution as te

    async def fake_impl(block, **kw):
        if raises:
            raise RuntimeError("tool blew up")
        return ("did a thing", result)

    monkeypatch.setattr(te, "_execute_tool_block_impl", fake_impl)
    return await te.execute_tool_block(
        _Block(), session_id="p1402-t", owner="alice",
        security_context=te.NO_TOOL_SECURITY_CONTEXT)


def test_a_successful_tool_call_is_recorded(monkeypatch):
    out = asyncio.run(_run_tool(monkeypatch, {"output": "fine"}))
    assert out[0] == "did a thing"          # behaviour unchanged
    (r,) = rows("tool_call")
    assert r.name == "shell" and r.outcome == "ok"
    assert r.owner == "alice" and r.session_id == "p1402-t"
    assert r.duration_ms is not None


def test_a_tool_that_fails_by_returning_is_counted_as_a_failure(monkeypatch):
    """The one that matters. Tools here report errors in the result dict; they
    do not raise. Counting exceptions alone would report a 0% failure rate."""
    asyncio.run(_run_tool(monkeypatch, {"error": "no such file", "exit_code": 1}))
    (r,) = rows("tool_call")
    assert r.outcome == "error"


def test_a_nonzero_exit_code_alone_is_a_failure(monkeypatch):
    asyncio.run(_run_tool(monkeypatch, {"output": "", "exit_code": 2}))
    (r,) = rows("tool_call")
    assert r.outcome == "error"


def test_a_raising_tool_is_recorded_and_still_raises(monkeypatch):
    with pytest.raises(RuntimeError):
        asyncio.run(_run_tool(monkeypatch, None, raises=True))
    (r,) = rows("tool_call")
    assert r.outcome == "exception"


def test_a_broken_recorder_cannot_break_a_tool_call(monkeypatch):
    monkeypatch.setattr("src.events.record_event",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    out = asyncio.run(_run_tool(monkeypatch, {"output": "fine"}))
    assert out[0] == "did a thing"


# --- retrieval ------------------------------------------------------------

def test_retrieval_records_what_was_asked_for_and_what_came_back():
    ev.record_event("retrieval", name="rag", outcome="ok",
                    detail={"asked": 5, "returned": 2})
    (r,) = rows("retrieval")
    assert json.loads(r.detail) == {"asked": 5, "returned": 2}


def test_an_unavailable_store_is_not_recorded_as_an_empty_result():
    """"Nothing came back because the store is down" and "nothing came back
    because nothing matched" look identical to a user and are different bugs.
    A hit rate that merges them is the flattering one.

    Driven through the real `search`, not asserted against the source: a test
    that greps for a string passes whether or not the branch is ever reached.
    """
    import src.memory_vector as mv

    store = mv.MemoryVectorStore.__new__(mv.MemoryVectorStore)
    store._healthy = False
    assert store.search("anything") == []

    (r,) = rows("retrieval")
    assert r.outcome == "unavailable", (
        "a store that is down reported the same outcome as a genuine miss")
    assert r.name == "memory"


def test_a_genuine_miss_is_recorded_as_empty(monkeypatch):
    """The other half. Without this, "unavailable" could be the outcome for
    every search and the test above would still pass."""
    import src.memory_vector as mv

    store = mv.MemoryVectorStore.__new__(mv.MemoryVectorStore)
    store._healthy = True
    monkeypatch.setattr(mv.MemoryVectorStore, "count", lambda self: 3)
    store._lanes = []
    assert store.search("anything") == []

    (r,) = rows("retrieval")
    assert r.outcome == "empty"
    assert json.loads(r.detail)["returned"] == 0


# --- approvals ------------------------------------------------------------

def test_a_claimed_approval_is_recorded():
    ev.record_event("approval", name="shell", outcome="claimed", owner="alice")
    (r,) = rows("approval")
    assert r.outcome == "claimed" and r.name == "shell"


def test_the_approval_paths_record_both_outcomes():
    """Claimed alone would say the ladder always works. Expiry is the outcome
    worth counting: a ladder answered rarely is one people have learned to
    ignore."""
    text = open("src/tool_approvals.py", encoding="utf-8").read()
    assert '_record_approval("claimed"' in text
    assert '_record_approval("expired"' in text


# --- the migration --------------------------------------------------------

def test_the_name_column_is_added_to_a_table_that_already_exists(tmp_path, monkeypatch):
    """`create_all` creates missing TABLES and never alters one. `events`
    shipped a commit earlier, so an install on that build has the table without
    this column and would fail every insert."""
    db_file = tmp_path / "old.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts DATETIME, "
                 "kind TEXT, session_id TEXT, owner TEXT, model TEXT, "
                 "endpoint TEXT, input_tokens INTEGER, output_tokens INTEGER, "
                 "duration_ms INTEGER, outcome TEXT, detail TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(core_db, "DATABASE_URL", f"sqlite:///{db_file}")
    core_db._migrate_add_events_name_column()

    conn = sqlite3.connect(db_file)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
    idx = [r[1] for r in conn.execute("PRAGMA index_list(events)")]
    conn.close()
    assert "name" in cols
    assert any("kind_name_ts" in i for i in idx)


def test_the_migration_is_idempotent(tmp_path, monkeypatch):
    db_file = tmp_path / "twice.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    monkeypatch.setattr(core_db, "DATABASE_URL", f"sqlite:///{db_file}")
    core_db._migrate_add_events_name_column()
    core_db._migrate_add_events_name_column()   # must not raise
    conn = sqlite3.connect(db_file)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
    conn.close()
    assert cols.count("name") == 1
