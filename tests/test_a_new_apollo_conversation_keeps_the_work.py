# SPDX-License-Identifier: AGPL-3.0-or-later
"""A new conversation with Apollo starts a fresh chat and keeps the work.

The owner's test on a fresh deploy (2026-11-24): Apollo was "another generic
Chat page that can't be cleared". Its chat was one pinned session for life and
the generic delete refuses a chat with messages, so there was no way to start
over.

Driven through the real router as two people: a new conversation moves Apollo
to a fresh chat, files the old one as an earlier conversation (renamed, kept,
unpinned), moves the briefings that spoke into it, keeps tasks, leaves an
empty chat alone, waits while Apollo is mid-run, works per space, and is the
person's own.
"""
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.apollo import conversations as C, knows
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)
from tests.helpers.signed_in import ADMIN, MEMBER, as_person, signed_in


@pytest.fixture
def apollo_as(apollo_db, tmp_path, monkeypatch):
    from src.memory import MemoryManager
    (tmp_path / "brain").mkdir()
    monkeypatch.setattr(knows, "_manager", MemoryManager(str(tmp_path / "brain")))
    monkeypatch.setattr(knows, "_sealed", {})
    monkeypatch.setattr("src.apollo.goal_lead.write", lambda *a, **k: None)
    manager = signed_in(monkeypatch, tmp_path / "auth")
    import routes.apollo_routes as apollo_routes

    def client(who):
        app = as_person(FastAPI(), who, auth_manager=manager)
        app.include_router(apollo_routes.setup_apollo_routes())
        return TestClient(app)
    return client


def _apollo(apollo_db, owner, sid=None, said=True):
    from core.database import ChatMessage, CrewMember, ScheduledTask, Session as DbSession
    sid = sid or f"s-{owner}"
    db = apollo_db()
    db.add(DbSession(id=sid, name="Apollo", endpoint_url="http://localhost:1234/v1", model="qwen",
                     owner=owner, is_important=True, mode="agent", folder="Assistant",
                     crew_member_id=f"crew-{owner}", last_message_at=datetime(2026, 11, 23, 21, 5)))
    db.add(CrewMember(id=f"crew-{owner}", owner=owner, name="Apollo", session_id=sid,
                      is_default_assistant=True))
    db.add(ScheduledTask(id=f"brief-{owner}", owner=owner, name="First light", prompt="brief",
                         task_type="llm", status="active", crew_member_id=f"crew-{owner}",
                         session_id=sid))
    if said:
        db.add(ChatMessage(id=f"m-{owner}", session_id=sid, role="user", content="hello"))
    db.commit()
    db.close()
    return sid


def _row(apollo_db, model, key):
    db = apollo_db()
    try:
        return db.query(model).filter(model.id == key).first()
    finally:
        db.close()


def test_a_new_conversation_moves_apollo_to_a_fresh_chat_and_keeps_the_old_one(apollo_as, apollo_db):
    from core.database import CrewMember, ScheduledTask, Session as DbSession
    old = _apollo(apollo_db, ADMIN)
    ada = apollo_as(ADMIN)
    ada.post("/api/apollo/tasks", json={"title": "Ship the re-theme", "start": False})

    r = ada.post("/api/apollo/conversations/new", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    new = body["session_id"]
    assert body["earlier_id"] == old and body["unchanged"] is False and new != old

    crew = _row(apollo_db, CrewMember, f"crew-{ADMIN}")
    assert crew.session_id == new
    fresh = _row(apollo_db, DbSession, new)
    assert (fresh.owner, fresh.name, fresh.model, fresh.mode, fresh.is_important, fresh.crew_member_id) == \
        (ADMIN, "Apollo", "qwen", "agent", True, f"crew-{ADMIN}")
    kept = _row(apollo_db, DbSession, old)
    assert kept is not None, "the old conversation is kept, not deleted"
    assert kept.name == "Apollo, Nov 23, 2026" and kept.folder == C.EARLIER_FOLDER and not kept.is_important
    assert _row(apollo_db, ScheduledTask, f"brief-{ADMIN}").session_id == new

    assert [t["title"] for t in ada.get("/api/apollo/tasks").json()["tasks"]] == ["Ship the re-theme"]
    earlier = ada.get("/api/apollo/conversations/earlier").json()["conversations"]
    assert [e["session_id"] for e in earlier] == [old]


def test_an_empty_conversation_is_left_as_it_is(apollo_as, apollo_db):
    old = _apollo(apollo_db, ADMIN, said=False)
    r = apollo_as(ADMIN).post("/api/apollo/conversations/new")
    assert r.status_code == 200, r.text
    assert r.json() == {"session_id": old, "earlier_id": None, "unchanged": True}


def test_a_new_conversation_waits_while_apollo_is_working(apollo_as, apollo_db, monkeypatch):
    from src import agent_runs
    old = _apollo(apollo_db, ADMIN)
    monkeypatch.setattr(agent_runs, "is_active", lambda sid: sid == old)
    r = apollo_as(ADMIN).post("/api/apollo/conversations/new", json={})
    assert r.status_code == 409
    assert "still working" in r.json()["detail"]


def test_a_spaces_chat_starts_over_on_its_own(apollo_as, apollo_db):
    from core.database import ChatMessage, CrewMember
    top = _apollo(apollo_db, ADMIN)
    ada = apollo_as(ADMIN)
    space = ada.post("/api/apollo/spaces", json={"name": "CyberKnox"}).json()["id"]
    chat = ada.post(f"/api/apollo/spaces/{space}/chat").json()["session_id"]
    db = apollo_db()
    db.add(ChatMessage(id="m-space", session_id=chat, role="user", content="work"))
    db.commit()
    db.close()

    body = ada.post("/api/apollo/conversations/new", json={"space_id": space}).json()
    assert body["earlier_id"] == chat and body["session_id"] != chat
    assert ada.post(f"/api/apollo/spaces/{space}/chat").json()["session_id"] == body["session_id"]
    assert _row(apollo_db, CrewMember, f"crew-{ADMIN}").session_id == top, "Apollo's main chat is untouched"


def test_one_person_cannot_start_over_anothers_apollo(apollo_as, apollo_db):
    from core.database import CrewMember
    _apollo(apollo_db, ADMIN)
    bob = apollo_as(MEMBER)
    r = bob.post("/api/apollo/conversations/new", json={})
    assert r.status_code == 409, "bob has no Apollo yet"
    assert _row(apollo_db, CrewMember, f"crew-{ADMIN}").session_id == f"s-{ADMIN}"
    assert bob.get("/api/apollo/conversations/earlier").status_code == 409
