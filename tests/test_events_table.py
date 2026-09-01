"""The time dimension is written down (`P14-01`).

`core/database.py` stored `message_count`, `total_input_tokens` and
`total_output_tokens` as running counters on a session row. Pantheon therefore
knew what a conversation had cost in total and could never say what it cost on
Tuesday, whether one model was cheaper than another, or whether a change helped.
The query was never the hard part — the event was not recorded.

These tests hold three things that are easy to get wrong in exactly this kind of
code, and that a "does it write a row" test would miss entirely:

  1. It must never break a chat. Measuring is worth nothing if the measured
     thing stops working.
  2. It must not write a credential. Endpoint URLs carry them.
  3. The running counters must still work. We add; we never subtract.
"""
import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as core_db
from core.database import Base, Event, Session as DBSession, utcnow_naive
from src import events as ev

SessionLocal = None   # bound per test by the fixture below


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    """A private, file-backed database per test.

    The suite runs on `sqlite:///:memory:` (see tests/conftest.py), where every
    new connection is a NEW EMPTY database — so a table created by `init_db()`
    is simply absent the next time `SessionLocal()` opens one. These tests
    passed alone, because a single pooled connection happened to be reused, and
    failed the moment the rest of the suite churned the pool. Ten of them, all
    green in isolation.

    A file-backed temp DB removes the ambiguity entirely, and stops these tests
    writing to (and pruning!) whatever database the developer is actually using.
    `src/events.py` imports `SessionLocal` inside its functions, so patching the
    module attribute reaches it; `routes/chat_helpers.py` binds it at import, so
    that one is patched too.
    """
    global SessionLocal
    engine = create_engine(f"sqlite:///{tmp_path}/t14.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    monkeypatch.setattr("routes.chat_helpers.SessionLocal", maker)
    SessionLocal = maker
    ev._last_prune = 0.0
    yield
    SessionLocal = None
    engine.dispose()


def make_session(session_id, **kw):
    """A minimal valid session row. `sessions` requires name, endpoint_url and
    model; they are irrelevant to every assertion here, so they are filled once."""
    db = SessionLocal()
    try:
        db.add(DBSession(id=session_id, name="t14", endpoint_url="http://localhost:8000",
                         model="test-model", **kw))
        db.commit()
    finally:
        db.close()


def drop_session(session_id):
    db = SessionLocal()
    try:
        db.query(DBSession).filter(DBSession.id == session_id).delete()
        db.commit()
    finally:
        db.close()


def rows(session_id):
    db = SessionLocal()
    try:
        return db.query(Event).filter(Event.session_id == session_id).all()
    finally:
        db.close()


# --- what it records ------------------------------------------------------

def test_a_round_is_one_row_with_a_timestamp():
    assert ev.record_llm_round("t14-a", {
        "input_tokens": 120, "output_tokens": 45,
        "model": "qwen2.5-coder-7b", "endpoint_label": "Local llama.cpp",
    })
    (r,) = rows("t14-a")
    assert r.ts is not None
    assert (r.input_tokens, r.output_tokens) == (120, 45)
    assert r.model == "qwen2.5-coder-7b"
    assert r.endpoint == "Local llama.cpp"
    assert r.outcome == "ok"
    assert r.kind == "llm_round"


def test_a_zero_token_failure_is_still_recorded():
    """The reason the event is written before `accumulate_token_usage`'s early
    return. A round that produced no tokens is usually a round that FAILED, and
    "how often does this endpoint fail" is precisely what the running counters
    can never answer."""
    assert ev.record_llm_round("t14-b", {"input_tokens": 0, "output_tokens": 0,
                                         "model": "m"}, outcome="error")
    (r,) = rows("t14-b")
    assert r.outcome == "error"


def test_a_zero_token_failure_survives_the_callers_early_return():
    """Through `accumulate_token_usage`, not around it.

    The test above calls `record_llm_round` directly and therefore says nothing
    about WHERE the call sits — a mutation that moved the write below
    `accumulate_token_usage`'s `if not (in_t or out_t): return` passed it
    cleanly. That early return is exactly what discards failed rounds, so the
    placement is the behaviour and it needs its own test.
    """
    from routes import chat_helpers
    make_session("t14-early")
    chat_helpers.accumulate_token_usage(
        "t14-early", {"input_tokens": 0, "output_tokens": 0, "model": "m"},
        outcome="error")
    drop_session("t14-early")
    recorded = rows("t14-early")
    assert len(recorded) == 1, "a zero-token round was dropped by the early return"
    assert recorded[0].outcome == "error"


def test_duration_is_null_and_that_is_honest():
    """Round latency is not available at this insertion point; threading it
    through is `P14-02`. The column exists so that row needs no migration."""
    ev.record_llm_round("t14-c", {"input_tokens": 1, "output_tokens": 1})
    (r,) = rows("t14-c")
    assert r.duration_ms is None
    assert hasattr(Event, "duration_ms")


def test_owner_is_carried_from_the_session():
    make_session("t14-owned", owner="alice")
    ev.record_llm_round("t14-owned", {"input_tokens": 5, "output_tokens": 5})
    (r,) = rows("t14-owned")
    assert r.owner == "alice"
    drop_session("t14-owned")


# --- it must not write a credential ---------------------------------------

def test_an_endpoint_url_handed_in_by_mistake_is_redacted():
    """The metrics dict is supposed to carry `endpoint_label`, a human name. A
    caller that hands over the URL instead is a mistake to absorb, not to store:
    endpoint URLs carry credentials in userinfo and query, and these rows are
    rendered by usage views and may travel in a `P16-14` bundle."""
    ev.record_llm_round("t14-url", {
        "input_tokens": 1, "output_tokens": 1,
        "endpoint_label": "https://user:hunter2@llm.lan:8000/v1?api_key=abc123",
    })
    (r,) = rows("t14-url")
    assert "hunter2" not in (r.endpoint or "")
    assert "abc123" not in (r.endpoint or "")
    assert "llm.lan" in (r.endpoint or ""), "over-redacted — the host is the useful part"


def test_no_message_content_is_stored():
    """The table holds shape, not conversation. That is what makes keeping it
    after a session is deleted defensible."""
    ev.record_llm_round("t14-priv", {
        "input_tokens": 1, "output_tokens": 1,
        "model": "m", "thinking": "SECRETTHOUGHT", "response": "SECRETREPLY",
        "user_message": "SECRETPROMPT",
    })
    (r,) = rows("t14-priv")
    blob = json.dumps({c.name: str(getattr(r, c.name)) for c in Event.__table__.columns})
    for secret in ("SECRETTHOUGHT", "SECRETREPLY", "SECRETPROMPT"):
        assert secret not in blob


def test_a_giant_label_cannot_grow_a_row_without_bound():
    ev.record_llm_round("t14-big", {"input_tokens": 1, "output_tokens": 1,
                                    "model": "x" * 5000})
    (r,) = rows("t14-big")
    assert len(r.model) <= 200


# --- it must never break a chat -------------------------------------------

def test_recording_never_raises_even_when_the_database_is_gone(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("no such table: events")
    monkeypatch.setattr("core.database.SessionLocal", boom)
    assert ev.record_llm_round("t14-boom", {"input_tokens": 1, "output_tokens": 1}) is False


def test_accumulate_token_usage_still_updates_the_counters(monkeypatch):
    """We add; we never subtract. The counters worked before this existed."""
    from routes import chat_helpers
    make_session("t14-count", total_input_tokens=10, total_output_tokens=20)
    chat_helpers.accumulate_token_usage("t14-count", {"input_tokens": 5, "output_tokens": 7})
    db = SessionLocal()
    try:
        s = db.query(DBSession).filter(DBSession.id == "t14-count").first()
        assert (s.total_input_tokens, s.total_output_tokens) == (15, 27)
    finally:
        db.close()
    drop_session("t14-count")


def test_a_broken_event_write_does_not_break_the_counters(monkeypatch):
    """The reason `record_llm_round` opens its OWN session. Sharing the one the
    counters use would let a failed commit here roll back their update."""
    from routes import chat_helpers
    monkeypatch.setattr("src.events.record_llm_round",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    make_session("t14-safe", total_input_tokens=0, total_output_tokens=0)
    chat_helpers.accumulate_token_usage("t14-safe", {"input_tokens": 3, "output_tokens": 4})
    db = SessionLocal()
    try:
        s = db.query(DBSession).filter(DBSession.id == "t14-safe").first()
        assert (s.total_input_tokens, s.total_output_tokens) == (3, 4)
    finally:
        db.close()
    drop_session("t14-safe")


# --- retention ------------------------------------------------------------

def test_retention_ships_finite():
    """An append-only table with no ceiling is a defect on someone's home
    server, not a feature."""
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["events_retention_days"] == 90


def test_prune_removes_only_rows_past_the_window():
    db = SessionLocal()
    try:
        db.add(Event(session_id="t14-old", kind="llm_round",
                     ts=utcnow_naive() - timedelta(days=200)))
        db.add(Event(session_id="t14-new", kind="llm_round", ts=utcnow_naive()))
        db.commit()
    finally:
        db.close()
    ev.prune_events(days=90)
    assert rows("t14-old") == []
    assert len(rows("t14-new")) == 1


def test_zero_means_keep_everything_and_says_so_by_doing_nothing():
    """A retention setting that silently ignores the value you gave it is worse
    than not having one."""
    db = SessionLocal()
    try:
        db.add(Event(session_id="t14-forever", kind="llm_round",
                     ts=utcnow_naive() - timedelta(days=9000)))
        db.commit()
    finally:
        db.close()
    assert ev.prune_events(days=0) == 0
    assert len(rows("t14-forever")) == 1


def test_events_survive_deleting_the_session_they_describe():
    """Deliberately not a cascading foreign key. "What did last month cost" has
    to outlive tidying up, and nothing here is conversation content."""
    make_session("t14-gone")
    ev.record_llm_round("t14-gone", {"input_tokens": 9, "output_tokens": 9})
    drop_session("t14-gone")
    assert len(rows("t14-gone")) == 1
    cols = {c.name for c in Event.__table__.columns}
    assert "session_id" in cols
    assert not Event.__table__.c.session_id.foreign_keys, \
        "a cascading FK would delete the cost along with the conversation"


# --- it has a reader ------------------------------------------------------

def test_usage_summary_answers_the_question_that_started_the_phase():
    ev.record_llm_round("t14-s", {"input_tokens": 100, "output_tokens": 10, "model": "a"})
    ev.record_llm_round("t14-s", {"input_tokens": 50, "output_tokens": 5, "model": "b"})
    ev.record_llm_round("t14-s", {"input_tokens": 0, "output_tokens": 0, "model": "b"},
                        outcome="error")
    s = ev.usage_summary(days=1)
    assert s["rounds"] >= 3
    assert s["by_model"]["a"]["input_tokens"] >= 100
    assert s["by_model"]["b"]["rounds"] >= 2
    assert s["errors"] >= 1


def test_the_terminal_paths_tag_their_rounds_as_errors():
    """`outcome` defaults to "ok", so a call site that forgets it records a
    failure as a success — silently, and in the one column that makes "how often
    does this endpoint fail" answerable.

    Both `accumulate_token_usage` calls in `chat_routes.py` are terminal paths;
    each is followed by `_stream_set(session, status="error")`. Stripping the
    tag broke nothing until this test existed.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "routes" /
           "chat_routes.py").read_text(encoding="utf-8")
    calls = [ln.strip() for ln in src.splitlines()
             if "accumulate_token_usage(" in ln and "import" not in ln]
    assert calls, "no call sites found — the test would be vacuous"
    for call in calls:
        assert 'outcome="error"' in call, (
            f"a terminal path records its round as a success: {call}")


def test_the_table_is_not_write_only():
    """`P14-01` ships with a door. The whole `H` series is finished work that
    had none, and a measurement phase should not open by adding another."""
    from pathlib import Path
    routes = (Path(__file__).resolve().parent.parent / "routes" /
              "diagnostics_routes.py").read_text(encoding="utf-8")
    assert "/api/diagnostics/usage" in routes
    assert "usage_summary" in routes
