# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1201` (`PERF-M-14`'s rest): `GET /api/session/{id}/context` reads the
chat's row once.

It runs on every chat open. `P23-04` took its endpoint half to one read and
`P23-07` took `get_session` to two statements; the handler still read the
chat's `sessions` row three times — `_verify_session_owner`, then
`SessionManager.get_session`'s metadata refresh, then (with no `?mode=`)
`core.database.get_session_mode`. Now the owner check reads the whole row and
returns it, the refresh is handed it (`get_session(row=...)`), and the chat's
last mode is that row's column.

Driven, counted as `tests/test_reading_a_chat_is_two_statements.py` counts:
the real route, the real owner check and the real manager over a real SQLite
file, every statement seen by the engine.
"""
from __future__ import annotations

import re
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession

_ROW_READ = re.compile(r"^\s*SELECT\b.*\bFROM sessions\b", re.I | re.S)


@pytest.fixture()
def chat(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.history_routes as history_routes
    import routes.session_routes as session_routes
    import src.model_context as model_context

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(smod, "SessionLocal", factory)
    monkeypatch.setattr(session_routes, "SessionLocal", factory)
    db = factory()
    db.add(DbSession(id="c1", owner="ann", name="a chat", endpoint_url="x", model="m",
                     mode="agent", last_accessed=datetime(2026, 1, 1)))
    db.add(DbSession(id="c2", owner="bob", name="bob's", endpoint_url="x", model="m",
                     last_accessed=datetime(2026, 1, 1)))
    for i in range(3):
        db.add(DbMessage(id=f"m{i}", session_id="c1", role="user" if i % 2 == 0 else "assistant",
                         content=f"hi {i}", timestamp=datetime(2026, 1, 1, 0, i)))
    db.commit()
    db.close()

    who = {"user": "ann"}
    monkeypatch.setattr(session_routes, "effective_user", lambda request: who["user"])
    # The endpoint table is `P23-04`'s and is measured there; this counts the chat's row.
    monkeypatch.setattr(model_context, "get_context_length_known", lambda url, model: (128_000, False))
    import src.settings as settings
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: default)

    statements = []
    event.listen(engine, "before_cursor_execute", lambda *a, **k: statements.append(a[2]))
    sm = smod.SessionManager()
    sm.get_session("c1")          # the first read hydrates and stamps the chat
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(sm))
    client = TestClient(app)
    statements.clear()
    return client, statements, who


def _row_reads(statements):
    return [s for s in statements if _ROW_READ.search(s)]


@pytest.mark.parametrize("query", ["", "?mode=agent", "?mode=chat"])
def test_the_context_route_reads_the_chats_row_once(chat, query):
    client, statements, _ = chat
    res = client.get(f"/api/session/c1/context{query}")
    assert res.status_code == 200, res.text
    reads = _row_reads(statements)
    assert len(reads) == 1, f"the chat's row was read {len(reads)} times: {reads}"
    writes = [s for s in statements if s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
    assert writes == [], writes


def test_without_a_mode_the_chats_last_mode_comes_from_that_one_read(chat):
    """The mode `get_session_mode` read with a statement of its own is the
    row's column: this chat was last used in Agent mode."""
    client, statements, _ = chat
    out = client.get("/api/session/c1/context").json()
    assert out["mode"] == "agent" and out["agent_budget"] == 6000
    assert out["messages"] == 3


def test_someone_elses_chat_is_still_refused_before_anything_is_read(chat):
    client, statements, who = chat
    who["user"] = "ann"
    res = client.get("/api/session/c2/context")
    assert res.status_code == 404
    assert res.json()["detail"] == "That chat no longer exists."
    assert len(_row_reads(statements)) == 1
    assert not [s for s in statements if "chat_messages" in s], "a refused caller's chat was read"
