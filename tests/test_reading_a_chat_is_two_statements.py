# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-14`, the session half `fx-chat` filed): reading a chat is
two statements, and it writes `last_accessed` at most once a minute.

`SessionManager.get_session` refreshed the metadata (read the row, count the
messages) and then `_touch_session` read the row again and wrote
`last_accessed` — four statements a call, a write on every read, and the
routes call it several times a request (`/api/session/{id}/context` four
times). Now the refresh's own read carries the touch. Driven: the real manager
over a real SQLite file, every statement counted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession


@pytest.fixture()
def chat(monkeypatch, tmp_path):
    import core.session_manager as smod

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(smod, "SessionLocal", factory)
    db = factory()
    db.add(DbSession(id="c1", owner="ann", name="a chat", endpoint_url="x", model="m",
                     last_accessed=datetime(2026, 1, 1)))
    for i in range(3):
        db.add(DbMessage(id=f"m{i}", session_id="c1", role="user", content=f"hi {i}",
                         timestamp=datetime(2026, 1, 1, 0, i)))
    db.commit()
    db.close()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *a, **k: statements.append(a[2]))
    sm = smod.SessionManager()
    sm.get_session("c1")          # the first read hydrates and stamps
    statements.clear()

    def stamp():
        d = factory()
        try:
            return d.query(DbSession).filter(DbSession.id == "c1").first().last_accessed
        finally:
            d.close()

    def age(minutes):
        d = factory()
        try:
            d.query(DbSession).filter(DbSession.id == "c1").update(
                {"last_accessed": datetime.now(timezone.utc) - timedelta(minutes=minutes)})
            d.commit()
        finally:
            d.close()
        statements.clear()

    return sm, statements, stamp, age


def test_a_warm_read_is_two_statements_and_writes_nothing(chat):
    sm, statements, stamp, age = chat
    before = stamp()
    statements.clear()            # the test's own read of the stamp
    session = sm.get_session("c1")
    assert len(session.history) == 3
    writes = [s for s in statements if s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
    assert writes == [], writes
    assert len(statements) == 2, statements
    assert stamp() == before


def test_a_read_a_minute_later_marks_the_chat_used(chat):
    sm, statements, stamp, age = chat
    age(2)
    old = stamp()
    statements.clear()
    sm.get_session("c1")
    assert stamp() > old
    assert sum(1 for s in statements if s.lstrip().upper().startswith("UPDATE")) == 1
