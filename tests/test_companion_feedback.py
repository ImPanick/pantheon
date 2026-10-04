# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pip feedback belongs to one saved reply and stays out of model context."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, Session as DbSession, ChatMessage as DbMessage, AssistantFeedback
from routes import session_routes
from routes.history import history_routes


@pytest.fixture
def feedback_env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        db.add_all([
            DbSession(id="alice-chat", name="Alice", endpoint_url="http://model.test", model="m", owner="alice"),
            DbSession(id="bob-chat", name="Bob", endpoint_url="http://model.test", model="m", owner="bob"),
        ])
        db.add_all([
            DbMessage(id="old", session_id="alice-chat", role="assistant", content="old reply", meta_data='{"model":"m"}', timestamp=datetime(2026, 1, 1)),
            DbMessage(id="latest", session_id="alice-chat", role="assistant", content="latest reply", meta_data='{"model":"m"}', timestamp=datetime(2026, 1, 1) + timedelta(seconds=1)),
            DbMessage(id="user", session_id="alice-chat", role="user", content="prompt", timestamp=datetime(2026, 1, 1) + timedelta(seconds=2)),
            DbMessage(id="bob", session_id="bob-chat", role="assistant", content="private reply", timestamp=datetime(2026, 1, 1)),
        ])
        db.commit()
    finally:
        db.close()
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(session_routes, "SessionLocal", factory)
    monkeypatch.setattr(history_routes, "SessionLocal", factory)
    app = FastAPI()
    owner = {"name": "alice"}

    @app.middleware("http")
    async def signed_in(request, call_next):
        request.state.current_user = owner["name"]
        return await call_next(request)

    app.include_router(history_routes.setup_history_routes(SimpleNamespace()))
    with TestClient(app) as client:
        yield client, factory, owner
    engine.dispose()


def _url(session="alice-chat", message="latest"):
    return f"/api/session/{session}/message/{message}/feedback"


def test_rating_is_idempotent_and_not_added_to_message_or_model_metadata(feedback_env):
    client, factory, _ = feedback_env
    assert client.get(_url()).json() == {"rating": None, "correction": ""}
    for _ in range(2):
        result = client.post(_url(), json={"rating": "helpful", "correction": ""})
        assert result.status_code == 200, result.text
    result = client.post(_url(), json={"rating": "off_track", "correction": "Use the second example."})
    assert result.status_code == 200, result.text
    assert client.get(_url()).json() == {"rating": "off_track", "correction": "Use the second example."}
    db = factory()
    try:
        assert db.query(AssistantFeedback).count() == 1
        assert json.loads(db.get(DbMessage, "latest").meta_data) == {"model": "m"}
    finally:
        db.close()


def test_stale_other_session_and_nonassistant_targets_are_refused(feedback_env):
    client, _, owner = feedback_env
    payload = {"rating": "helpful"}
    assert client.post(_url(message="old"), json=payload).status_code == 409
    assert client.post(_url(message="user"), json=payload).status_code == 404
    assert client.post(_url(message="bob"), json=payload).status_code == 404
    owner["name"] = "bob"
    assert client.post(_url(), json=payload).status_code == 404


@pytest.mark.parametrize("payload", [
    {"rating": "approve_tool"}, {"rating": "helpful", "correction": "extra"},
    {"rating": "off_track", "correction": 3},
    {"rating": "off_track", "correction": "x" * 281},
    {"rating": "off_track", "correction": "bad\x00note"},
])
def test_payload_is_bounded(feedback_env, payload):
    client, _, _ = feedback_env
    assert client.post(_url(), json=payload).status_code == 400


def test_feedback_stays_plain_text_and_is_deleted_with_reply(feedback_env):
    client, factory, _ = feedback_env
    note = "<script>alert(1)</script> is the text I want removed"
    assert client.post(_url(), json={"rating": "off_track", "correction": note}).status_code == 200
    assert client.get(_url()).json()["correction"] == note
    db = factory()
    try:
        db.delete(db.get(DbMessage, "latest"))
        db.commit()
        assert db.query(AssistantFeedback).count() == 0
    finally:
        db.close()


def test_paged_history_exposes_reply_id_for_precise_targeting(feedback_env):
    client, _, _ = feedback_env
    response = client.get("/api/history/alice-chat?limit=10")
    assert response.status_code == 200, response.text
    assistant = next(m for m in response.json()["history"] if m["content"] == "latest reply")
    assert assistant["metadata"]["_db_id"] == "latest"
