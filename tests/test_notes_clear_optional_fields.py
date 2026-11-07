# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1802`. Removing a note's reminder, tags, image or colour did not stick.

The Notes editor removes an optional field by sending it as null: the x on a
reminder tag empties the due date, removing the last tag sends `label: null`,
removing the image sends `image_url: null`, and a card's "no colour" dot sends
`color: null`. `PUT /api/notes/{id}` applied each field only when it was not
None, so null meant "unchanged": the save answered 200, the field came back on
reload, and a reminder the person had removed still fired from the stored due
date.

Now a field left out of the body keeps its value, and an explicit null clears
content, items, color, label, due_date and image_url. Title, type, pin,
archive, repeat, order and the agent-run fields (`B80`) keep the old rule: no
control removes them.

Ported from upstream Odysseus 41278905 (#6585). Upstream's cases are here
without its gallery_id (Pantheon's notes have none), with the editor's real
save payload and the agent-run fields added. Driven through the real route
over a real SQLite file.
"""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
import routes.note_routes as nr

_PEER = ("203.0.113.7", 54321)
ALICE = {"x-test-user": "alice"}
BOB = {"x-test-user": "bob"}

SAVED = {
    "content": "Ask about Tuesday",
    "items": [{"text": "Saved item", "done": False}],
    "color": "blue",
    "label": "home reminder",
    "due_date": "2030-10-08T09:00:00",
    "image_url": "/api/uploads/note-photo.png",
}


class _Identity:
    """Pure-ASGI identity shim, for the reason test_notes_fail_closed_auth gives."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            user = headers.get(b"x-test-user")
            if user:
                scope.setdefault("state", {})["current_user"] = user.decode()
        await self.app(scope, receive, send)


@pytest.fixture
def notes(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'notes.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    monkeypatch.setattr(nr, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("LOCALHOST_BYPASS", raising=False)
    app = FastAPI()
    # `B1191`: the router asks the person's `can_use_notes` switch; none overridden.
    app.state.auth_manager = SimpleNamespace(is_configured=True, get_privileges=lambda _name: {})
    app.include_router(nr.setup_note_routes())
    transport = httpx.ASGITransport(app=_Identity(app), client=_PEER)
    return httpx.AsyncClient(transport=transport, base_url="http://notes.test")


async def _saved_note(c, **extra):
    created = await c.post("/api/notes", json={"title": "Call the plumber", "repeat": "weekly",
                                               **SAVED, **extra}, headers=ALICE)
    assert created.status_code == 200, created.text
    return f"/api/notes/{created.json()['id']}"


@pytest.mark.parametrize("field", sorted(SAVED))
async def test_an_explicit_null_clears_the_saved_field(notes, field):
    async with notes as c:
        path = await _saved_note(c)
        assert (await c.get(path, headers=ALICE)).json()[field] == SAVED[field]

        updated = await c.put(path, json={field: None}, headers=ALICE)

        assert updated.status_code == 200, updated.text
        assert updated.json()[field] is None
        reloaded = (await c.get(path, headers=ALICE)).json()
        assert reloaded[field] is None, f"{field} came back on reload"
        for other, value in SAVED.items():
            if other != field:
                assert reloaded[other] == value, f"clearing {field} also changed {other}"


async def test_the_editor_s_own_save_removes_the_reminder_the_tags_and_the_image(notes):
    """The payload `notes.js` sends when the person has removed all three and saves."""
    async with notes as c:
        path = await _saved_note(c)
        note_id = path.rsplit("/", 1)[1]
        payload = {
            "id": note_id, "title": "Call the plumber", "note_type": "note",
            "color": "", "label": None, "due_date": None, "repeat": "none",
            "image_url": None, "content": "Ask about Tuesday", "sort_order": -1,
        }

        assert (await c.put(path, json=payload, headers=ALICE)).status_code == 200

        reloaded = (await c.get(path, headers=ALICE)).json()
        assert reloaded["due_date"] is None, "the removed reminder is still due"
        assert reloaded["label"] is None
        assert reloaded["image_url"] is None
        assert reloaded["color"] == ""
        assert reloaded["repeat"] == "none"
        assert reloaded["content"] == "Ask about Tuesday"


@pytest.mark.parametrize("body", [
    {"title": "Call the plumber today"},
    {"archived": True},
    {"pinned": True},
    {"due_date": "2030-10-15T09:00:00"},
], ids=["title", "archive", "pin", "recurring-advance"])
async def test_a_field_left_out_of_the_body_keeps_its_value(notes, body):
    async with notes as c:
        path = await _saved_note(c)

        assert (await c.put(path, json=body, headers=ALICE)).status_code == 200

        reloaded = (await c.get(path, headers=ALICE)).json()
        for field, value in {**SAVED, **body}.items():
            assert reloaded[field] == value, field


async def test_a_null_from_someone_else_clears_nothing(notes):
    async with notes as c:
        path = await _saved_note(c)

        refused = await c.put(path, json={field: None for field in SAVED}, headers=BOB)

        assert refused.status_code == 404
        reloaded = (await c.get(path, headers=ALICE)).json()
        assert {field: reloaded[field] for field in SAVED} == SAVED


async def test_the_agent_run_fields_still_treat_null_as_unchanged(notes):
    """`B80`'s writer sends only the fields it changes; a null there never cleared."""
    async with notes as c:
        path = await _saved_note(c)
        started = {"agent_session_id": "sess-9", "agent_session_title": "Agent: plumber",
                   "agent_status": "running", "agent_stream_completed_at": ""}
        await c.put(path, json=started, headers=ALICE)

        await c.put(path, json={"agent_session_id": None, "agent_session_title": None,
                                "agent_status": "stream_complete"}, headers=ALICE)

        reloaded = (await c.get(path, headers=ALICE)).json()
        assert reloaded["agent_session_id"] == "sess-9"
        assert reloaded["agent_session_title"] == "Agent: plumber"
        assert reloaded["agent_status"] == "stream_complete"
