# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pip feedback belongs to one saved reply and stays out of model context."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, Session as DbSession, ChatMessage as DbMessage, AssistantFeedback
from core.middleware import INTERNAL_TOOL_HEADER
from routes import session_routes
from routes.history import history_routes
from src.tools.system import do_app_api


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
    manager = SimpleNamespace()
    owner["manager"] = manager

    @app.middleware("http")
    async def signed_in(request, call_next):
        request.state.current_user = owner["name"]
        request.state.api_token = owner.get("delegated", False)
        return await call_next(request)

    app.include_router(history_routes.setup_history_routes(manager))
    with TestClient(app) as client:
        yield client, factory, owner
    engine.dispose()


def _url(session="alice-chat", message="latest"):
    return f"/api/session/{session}/message/{message}/feedback"


def _post(client, url, *, json, headers=None):
    """Submit feedback for the reply version fetched by a person."""
    request = dict(json)
    seen = client.get(url, params={"variant_index": request.get("variant_index", 0)}, headers=headers)
    request["content_digest"] = seen.json().get("content_digest", "0" * 64)
    return client.post(url, json=request, headers=headers)


def test_rating_is_idempotent_and_not_added_to_message_or_model_metadata(feedback_env):
    client, factory, _ = feedback_env
    first = client.get(_url()).json()
    assert first["rating"] is None and first["correction"] == ""
    assert first["content"] == "latest reply"
    assert len(first["content_digest"]) == 64
    assert client.post(_url(), json={"rating": "helpful"}).status_code == 400
    for _ in range(2):
        result = _post(client, _url(), json={"rating": "helpful", "correction": ""})
        assert result.status_code == 200, result.text
    result = _post(client, _url(), json={"rating": "off_track", "correction": "Use the second example."})
    assert result.status_code == 200, result.text
    assert client.get(_url()).json()["correction"] == "Use the second example."
    db = factory()
    try:
        assert db.query(AssistantFeedback).count() == 1
        assert json.loads(db.get(DbMessage, "latest").meta_data) == {"model": "m"}
    finally:
        db.close()


def test_stale_other_session_and_nonassistant_targets_are_refused(feedback_env):
    client, _, owner = feedback_env
    payload = {"rating": "helpful"}
    assert _post(client, _url(message="old"), json=payload).status_code == 409
    assert _post(client, _url(message="user"), json=payload).status_code == 404
    assert _post(client, _url(message="bob"), json=payload).status_code == 404
    owner["name"] = "bob"
    assert _post(client, _url(), json=payload).status_code == 404


@pytest.mark.parametrize("payload", [
    {"rating": "approve_tool"}, {"rating": "helpful", "correction": "extra"},
    {"rating": "off_track", "correction": 3},
    {"rating": "off_track", "correction": "x" * 281},
    {"rating": "off_track", "correction": "bad\x00note"},
])
def test_payload_is_bounded(feedback_env, payload):
    client, _, _ = feedback_env
    assert _post(client, _url(), json=payload).status_code == 400


def test_feedback_stays_plain_text_and_is_deleted_with_reply(feedback_env):
    client, factory, _ = feedback_env
    note = "<script>alert(1)</script> is the text I want removed"
    assert _post(client, _url(), json={"rating": "off_track", "correction": note}).status_code == 200
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


def test_earlier_draft_feedback_table_gains_identity_columns(tmp_path, monkeypatch):
    import core.database as database

    prior = create_engine(f"sqlite:///{tmp_path / 'draft.db'}")
    with prior.begin() as connection:
        connection.execute(text("CREATE TABLE assistant_feedback (message_id VARCHAR PRIMARY KEY, session_id VARCHAR NOT NULL, rating VARCHAR(12) NOT NULL, correction TEXT NOT NULL, updated_at DATETIME NOT NULL)"))
        connection.execute(text("INSERT INTO assistant_feedback VALUES ('m', 's', 'helpful', '', '2026-01-01')"))
    monkeypatch.setattr(database, "engine", prior)
    database._migrate_assistant_feedback_identity()
    database._migrate_assistant_feedback_identity()
    assert {"variant_index", "content_digest"} <= {c["name"] for c in inspect(prior).get_columns("assistant_feedback")}
    with prior.connect() as connection:
        assert connection.execute(text("SELECT variant_index, content_digest FROM assistant_feedback")).one() == (0, "")
    prior.dispose()


def test_feedback_follows_the_visible_variant_and_changed_text_fails_closed(feedback_env):
    client, factory, _ = feedback_env
    helpful = {"rating": "helpful", "variant_index": 0}
    assert _post(client, _url(), json=helpful).status_code == 200
    db = factory()
    try:
        reply = db.get(DbMessage, "latest")
        reply.meta_data = json.dumps({"variants": [
            {"raw": "latest reply", "label": "original"},
            {"raw": "new answer", "label": "regen"},
        ], "variantIndex": 1})
        db.commit()
    finally:
        db.close()
    assert client.get(_url(), params={"variant_index": 0}).json()["rating"] == "helpful"
    assert client.get(_url(), params={"variant_index": 1}).json()["rating"] is None
    assert _post(client, _url(), json={"rating": "off_track", "correction": "Use rain.", "variant_index": 1}).status_code == 200
    assert client.get(_url(), params={"variant_index": 0}).json()["rating"] is None
    assert client.get(_url(), params={"variant_index": 1}).json()["correction"] == "Use rain."
    db = factory()
    try:
        reply = db.get(DbMessage, "latest")
        meta = json.loads(reply.meta_data)
        meta["variants"][1]["raw"] = "edited new answer"
        reply.meta_data = json.dumps(meta)
        db.commit()
    finally:
        db.close()
    assert client.get(_url(), params={"variant_index": 1}).json()["rating"] is None
    assert client.get(_url(), params={"variant_index": 2}).status_code == 409
    assert _post(client, _url(), json={"rating": "helpful", "variant_index": True}).status_code == 400


def test_stale_cross_tab_feedback_cannot_rate_revised_reply(feedback_env):
    client, factory, _ = feedback_env
    observed = client.get(_url()).json()
    old_digest = observed["content_digest"]
    db = factory()
    try:
        db.get(DbMessage, "latest").content = "Revised in another tab"
        db.commit()
    finally:
        db.close()
    current = client.get(_url()).json()
    assert current["content_digest"] != old_digest
    stale = client.post(_url(), json={
        "rating": "helpful", "variant_index": 0, "content_digest": old_digest,
    })
    assert stale.status_code == 409
    db = factory()
    try:
        assert db.query(AssistantFeedback).count() == 0
    finally:
        db.close()
    assert _post(client, _url(), json={"rating": "helpful"}).status_code == 200


def test_editing_a_variant_updates_its_identity_without_losing_other_variants(feedback_env):
    client, factory, owner = feedback_env
    owner["manager"].get_session = lambda _sid: SimpleNamespace(history=[])
    db = factory()
    try:
        reply = db.get(DbMessage, "latest")
        reply.meta_data = json.dumps({"variants": [
            {"raw": "latest reply", "label": "original"},
            {"raw": "alternate", "label": "regen"},
        ], "variantIndex": 1})
        db.commit()
    finally:
        db.close()
    assert _post(client, _url(), json={"rating": "helpful", "variant_index": 1}).status_code == 200
    edited = client.post("/api/session/alice-chat/edit-message", json={
        "msg_id": "latest", "content": "edited alternate", "variant_index": 1,
    })
    assert edited.status_code == 200, edited.text
    db = factory()
    try:
        variants = json.loads(db.get(DbMessage, "latest").meta_data)["variants"]
        assert [v["raw"] for v in variants] == ["latest reply", "edited alternate"]
    finally:
        db.close()
    assert client.get(_url(), params={"variant_index": 1}).json()["rating"] is None
    assert _post(client, _url(), json={"rating": "helpful", "variant_index": 1}).status_code == 200
    assert client.get(_url(), params={"variant_index": 1}).json()["rating"] == "helpful"


def test_only_person_can_write_feedback_even_when_tool_uses_owner_identity(feedback_env):
    client, factory, owner = feedback_env
    payload = {"rating": "helpful"}
    assert _post(client, _url(), json=payload, headers={INTERNAL_TOOL_HEADER: "tool"}).status_code == 403
    assert client.get(_url(), headers={INTERNAL_TOOL_HEADER: "tool"}).status_code == 403
    owner["delegated"] = True
    assert _post(client, _url(), json=payload).status_code == 403
    owner["delegated"] = False
    db = factory()
    try:
        assert db.query(AssistantFeedback).count() == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_generic_app_api_cannot_discover_or_call_reply_feedback(feedback_env, monkeypatch):
    import httpx

    client, factory, _ = feedback_env
    real_init = httpx.AsyncClient.__init__

    def route_into_app(self, *args, **kwargs):
        kwargs.pop("timeout", None)
        kwargs["transport"] = httpx.ASGITransport(app=client.app)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", route_into_app)
    discovered = await do_app_api(json.dumps({"action": "endpoints", "filter": "feedback"}), owner="alice")
    assert discovered["exit_code"] == 0
    assert all("/feedback" not in row["path"] for row in discovered.get("endpoints", []))
    for path in (_url(), _url() + "?variant_index=0",
                 "/api/session/alice-chat/x/../message/latest/feedback",
                 "/api/session/alice-chat/message/latest/fee%64back"):
        for method in ("GET", "POST"):
            refused = await do_app_api(json.dumps({"action": "call", "method": method, "path": path,
                                                  "body": {"rating": "helpful"}}), owner="alice")
            assert refused["exit_code"] == 1
            assert "person" in refused["error"].lower()
    db = factory()
    try:
        assert db.query(AssistantFeedback).count() == 0
    finally:
        db.close()
