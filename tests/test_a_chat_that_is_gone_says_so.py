# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1216` — a stale chat id is refused in one sentence: *That chat no longer
exists.*

The routes said *Session not found* — and *Session 'x' not found* and
*Session x not found*, with the id in them — in 37 places across six route
files; a person reads it on a chat deleted in another tab, and a chat is a
chat (`D-2026-10-03-01` §3). `src/chat_helpers.py` already said the sentence;
it is `CHAT_GONE` now and every stale-chat 404 in `routes/` says it.

Driven: the real owner check, the real history route and the real delete
route over a real SQLite file, for a chat that is not there and one that is
somebody else's (the same sentence — an id is no oracle).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Session as DbSession
from src.chat_helpers import CHAT_GONE

ROOT = Path(__file__).resolve().parents[1]


def test_the_sentence_is_the_one_the_row_names():
    assert CHAT_GONE == "That chat no longer exists."


def test_no_route_refuses_a_chat_in_the_old_words():
    """Every string constant in `routes/` — not comments, not docstrings'
    prose about the old words — read for the retired refusal."""
    old = re.compile(r"\bSession\b[^\n]{0,20}\bnot found\b")

    def text(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):   # f"Session {sid} not found"
            return "".join(text(v) if isinstance(v, ast.Constant) else "{}" for v in node.values)
        return ""

    hits = []
    for path in sorted((ROOT / "routes").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HTTPException"):
                continue
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if any(old.search(text(part)) for part in ast.walk(arg)):
                    hits.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert hits == [], hits
    # The scan sees the shape it was written for (`Law 20`): an f-string one.
    probe = ast.parse('HTTPException(404, f"Session {sid} not found")').body[0].value
    assert any(old.search(text(p)) for p in ast.walk(probe.args[1]))


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.history_routes as history_routes
    import routes.session_routes as session_routes

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, history_routes):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    db = factory()
    db.add(DbSession(id="bobs", owner="bob", name="bob's chat", endpoint_url="x", model="m"))
    db.commit()
    db.close()
    monkeypatch.setattr(session_routes, "effective_user", lambda request: "ann")
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(smod.SessionManager()))
    return TestClient(app), session_routes


@pytest.mark.parametrize("chat", ["gone-chat", "bobs"])
def test_a_stale_or_strange_chat_is_refused_in_the_sentence(world, chat):
    client, session_routes = world
    for res in (client.get(f"/api/history/{chat}?limit=24"),
                client.post(f"/api/session/{chat}/delete-messages", json={"msg_ids": ["x"]})):
        assert res.status_code == 404
        assert res.json() == {"detail": CHAT_GONE}
    with pytest.raises(HTTPException) as exc:
        session_routes._verify_session_owner(type("R", (), {})(), chat)
    assert exc.value.detail == CHAT_GONE
