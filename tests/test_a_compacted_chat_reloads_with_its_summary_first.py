# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1506` — a compacted chat reloads with its summary before the messages it kept.

`history_routes.compact_session` kept the last four rows where they were and
added the hidden summary and the visible *Chat compacted* marker as two new rows
stamped *now* — later than every kept row. In memory the history read
[summary, marker, kept…]; from the database [kept…, summary, marker]. So after a
reload the marker drew under the messages it introduces, and the model's replay
had its summary after them. The route now writes the compacted history through
`SessionManager.replace_messages` — the seam `session_routes`' compact and
`context_compactor` already used — in one ordered transaction.

Driven (`Law 20`): the real route over a real `SessionManager` and a real
SQLite file, a ten-message chat compacted, then a **fresh** manager (nothing
cached) rehydrates it from the database: `get_context_messages` starts with the
summary, and `/api/history` — paged as the browser asks and whole — starts with
the marker (the summary is `hidden`, for the model only), the kept messages
after it in the order they were said.

The same reload is asked of `session_routes`' compact, the handler `app.py`
registers first for this path, so whichever of the two answers keeps the order.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Session as DbSession
from core.models import ChatMessage


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.session_manager as smod
    import routes.history_routes as history_routes
    import routes.session_routes as session_routes
    import src.agent_runs as agent_runs
    import src.endpoint_resolver as endpoint_resolver
    import src.llm_core as llm_core
    import src.model_context as model_context

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for mod in (smod, session_routes, history_routes):
        monkeypatch.setattr(mod, "SessionLocal", factory)

    async def summarise(*_a, **_k):
        return "They planned the launch week."

    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda request, sid: None)
    monkeypatch.setattr(session_routes, "_verify_session_owner", lambda request, sid, *a: None)
    monkeypatch.setattr(agent_runs, "is_active", lambda sid: False)
    monkeypatch.setattr(endpoint_resolver, "resolve_endpoint",
                        lambda kind, owner=None: ("http://model.test/v1", "m", {}))
    monkeypatch.setattr(llm_core, "llm_call_async", summarise)
    monkeypatch.setattr(model_context, "estimate_tokens", lambda messages: 100)
    monkeypatch.setattr(model_context, "get_context_length", lambda url, model: 1000)
    # `B1731`: the cut is sized to the window the wheel draws, read with its proof.
    monkeypatch.setattr(model_context, "get_context_length_known", lambda url, model: (8000, True))

    db = factory()
    db.add(DbSession(id="c1", owner="ann", name="Launch week", endpoint_url="http://model.test/v1", model="m"))
    db.commit()
    db.close()
    manager = smod.SessionManager()
    for i in range(10):
        manager.add_message("c1", ChatMessage("user" if i % 2 == 0 else "assistant", f"line {i}"))
    return smod, history_routes, session_routes, manager


def _reloaded(smod):
    """A manager that has never seen the chat: it reads the database."""
    fresh = smod.SessionManager()
    fresh.sessions.pop("c1", None)
    return fresh, fresh.get_session("c1")


def test_the_compacted_chat_reloads_summary_marker_then_kept(world):
    smod, history_routes, _session_routes, manager = world
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(manager))
    client = TestClient(app)
    assert client.post("/api/session/c1/compact").status_code == 200

    fresh, session = _reloaded(smod)
    context = session.get_context_messages()
    assert context[0]["role"] == "system"
    assert context[0]["content"].startswith("[Conversation summary — 9 earlier messages were compacted]")
    assert [m["content"] for m in context[1:]] == [
        "**Chat compacted** — 9 messages summarized, 1 kept.", "line 9"]

    reload_app = FastAPI()
    reload_app.include_router(history_routes.setup_history_routes(fresh))
    reload_client = TestClient(reload_app)
    for url in ("/api/history/c1?limit=24", "/api/history/c1"):
        drawn = [e["content"] for e in reload_client.get(url).json()["history"]]
        assert drawn == ["**Chat compacted** — 9 messages summarized, 1 kept.",
                         "line 9"], url


def test_with_both_routers_mounted_in_the_apps_order_the_marker_is_kept(world):
    """`app.py` includes `session_routes` before `history_routes`. That
    shadowed this handler (`B1529`) until `session_routes` stopped declaring
    the path; mounted in the app's order, the compact that answers is this one,
    marker and order and all."""
    smod, history_routes, session_routes, manager = world
    app = FastAPI()
    app.include_router(session_routes.setup_session_routes(manager, {}))
    app.include_router(history_routes.setup_history_routes(manager))
    answer = TestClient(app).post("/api/session/c1/compact").json()
    assert (answer["ok"], answer["summarized"], answer["kept"]) == (True, 9, 1)

    _fresh, session = _reloaded(smod)
    context = session.get_context_messages()
    assert context[0]["role"] == "system"
    assert context[0]["content"].startswith("[Conversation summary — 9 earlier messages were compacted]")
    assert [m["content"] for m in context[1:]] == [
        "**Chat compacted** — 9 messages summarized, 1 kept.", "line 9"]
