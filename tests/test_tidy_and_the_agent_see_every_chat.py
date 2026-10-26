# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1224` (fx-ops) — Tidy and the agent's chat list read a person's own chats
from the database, not the boot cache.

`PERF-M-5` moved `/api/sessions` onto `SessionManager.list_page`. Tidy
(`POST /api/sessions/auto-sort`) and the agent's `list_sessions` tool still
called `get_sessions_for_user`, which filters the cache `load_sessions` fills at
boot with the 100 most recently used chats **of every owner** — so on a shared
install a person whose chats were older than someone else's last 100 got an
empty Tidy (*"No unfiled chats to sort"*) and an agent that said they had no
chats. Now Tidy pages through `list_page` and the tool reads its first page.

Driven: a real `SessionManager` booted over a real SQLite file where another
person's 120 chats are all newer than this person's three; the real Tidy route
(its model call answered by a stand-in) and the real tool.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import ChatMessage as DbMessage
from core.database import Session as DbSession

ANNS = {"ann-0001-aaaa": "Sourdough starter", "ann-0002-bbbb": "Tax return questions",
        "ann-0003-cccc": "Bike gears"}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.session_routes as session_routes

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, cdb):
        monkeypatch.setattr(mod, "SessionLocal", factory)
    db = factory()
    old = datetime(2026, 1, 1)
    for sid, name in ANNS.items():
        db.add(DbSession(id=sid, owner="ann", name=name, endpoint_url="x", model="m",
                         created_at=old, updated_at=old, last_accessed=old, last_message_at=old))
        for i in range(6):
            db.add(DbMessage(id=f"{sid}-{i}", session_id=sid, role="user" if i % 2 == 0 else "assistant",
                             content=f"{name} {i}", timestamp=old + timedelta(minutes=i)))
    recent = datetime(2026, 10, 1)
    for n in range(120):
        sid = f"bob-{n:04d}"
        t = recent + timedelta(minutes=n)
        db.add(DbSession(id=sid, owner="bob", name=f"bob {n}", endpoint_url="x", model="m",
                         created_at=t, updated_at=t, last_accessed=t, last_message_at=t))
        db.add(DbMessage(id=f"{sid}-0", session_id=sid, role="user", content="hi", timestamp=t))
    db.commit()
    db.close()
    sm = smod.SessionManager()
    assert not [s for s in sm.sessions.values() if s.owner == "ann"], "the premise: ann is not in the boot cache"
    return sm, factory


def test_tidy_sorts_a_persons_chats_that_the_boot_cache_does_not_hold(world, monkeypatch):
    import routes.session_routes as session_routes
    import src.llm_core as llm_core
    import src.task_endpoint as task_endpoint
    sm, factory = world
    asked = []

    def answer(url, model, messages, **_kw):
        asked.append(messages[0]["content"])
        return json.dumps({"folders": {"Home": [sid[:8] for sid in ANNS]}})

    monkeypatch.setattr(session_routes, "effective_user", lambda request: "ann")
    monkeypatch.setattr(task_endpoint, "resolve_task_endpoint", lambda *a, **k: ("http://u/v1", "util", {}))
    monkeypatch.setattr(llm_core, "llm_call", answer)
    app = FastAPI()
    app.include_router(session_routes.setup_session_routes(sm, {}))
    res = TestClient(app).post("/api/sessions/auto-sort")
    assert res.status_code == 200, res.text
    assert res.json()["updated"] == 3
    assert all(name in asked[0] for name in ANNS.values())
    assert "bob " not in asked[0], "another person's chats were offered"
    db = factory()
    try:
        assert {r.id: r.folder for r in db.query(DbSession).filter(DbSession.owner == "ann")} == {
            sid: "Home" for sid in ANNS}
    finally:
        db.close()


def test_the_agents_chat_list_holds_the_persons_own_chats(world, monkeypatch):
    import src.agent_tools.session_tools as session_tools
    sm, _ = world
    monkeypatch.setattr(session_tools, "get_session_manager", lambda: sm)
    out = asyncio.run(session_tools.list_sessions("", owner="ann"))
    text = out["results"]
    assert text.startswith("Found 3 session(s)"), text
    assert all(f"id: `{sid}`" in text for sid in ANNS)
    assert "bob-" not in text
    bob = asyncio.run(session_tools.list_sessions("", owner="bob"))["results"]
    assert bob.startswith("Found 100 session(s)") and "Older chats exist" in bob
