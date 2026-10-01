# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1001`. A chat message saved before `P21-03` still named its attachments
by their ASCII fold.

`attachments[].name` is saved with the message (`ChatHandler.preprocess_message`)
and was the upload row's `name` — `secure_filename`'s `Q3_Board_Pack_final_v2.pdf`
— until `P21-03`. So a chip in an old chat read the fold after every reload,
and *open as document* from it titled the document `Q3_Board_Pack_final_v2`.
The row behind it now answers with the person's own name
(`upload_display_name`, recovered from the `original_name` every row has
carried).

**What is honest for an old message** (decided here, and the row's own
suggestion): the name is resolved through the upload row when the history is
read — the row's name when the upload is still indexed and is the reader's own,
and what was saved otherwise (the upload has gone, or it is somebody else's).
Nothing is rewritten: the stored row and the in-memory message keep what they
said when they were saved, and the lookup does not touch the upload index the
way `resolve_upload`'s reservation does.

Driven through `GET /api/history/{id}` — all three of its branches (the page
read from the database, the in-memory session, the database fallback) — on a
real SQLite database and a real `UploadHandler` over a temp store. Nothing
reads a source file (`Law 20`).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, ChatMessage as DbChatMessage, Session as DbSession
from core.models import ChatMessage
from routes.history import history_routes
from src.upload_handler import UploadHandler

Q3 = "Q3 Board Pack – final (v2).pdf"
FOLD = "Q3_Board_Pack_final_v2.pdf"

MINE_OLD = "a" * 32 + ".pdf"        # a row from before P21-03: no display_name
MINE_NEW = "c" * 32 + ".txt"        # a row since: display_name
THEIRS = "b" * 32 + ".pdf"          # bob's upload, named in alice's message
GONE = "d" * 32 + ".pdf"            # cleaned up since: no row
SPLIT = "e" * 32 + ".pdf"           # two rows that disagree about the owner
NAMELESS = "f" * 32 + ".pdf"        # a row that names nothing


def _saved_attachments():
    """What a message saved before `P21-03` carries."""
    return [
        {"id": MINE_OLD, "name": FOLD, "mime": "application/pdf", "size": 9},
        {"id": THEIRS, "name": "Bobs_plan.pdf", "mime": "application/pdf", "size": 9},
        {"id": MINE_NEW, "name": "Notes_today.txt", "mime": "text/plain", "size": 5},
        {"id": GONE, "name": "Old_minutes.pdf", "mime": "application/pdf", "size": 9},
        {"id": SPLIT, "name": "Split_owner.pdf", "mime": "application/pdf", "size": 9},
        {"id": NAMELESS, "name": "Kept_name.pdf", "mime": "application/pdf", "size": 9},
    ]


@pytest.fixture
def store(tmp_path):
    handler = UploadHandler(str(tmp_path / "base"), str(tmp_path / "uploads"))
    root = Path(handler.upload_dir)
    day = root / "2026" / "09" / "30"
    day.mkdir(parents=True)

    def row(upload_id, owner, **names):
        path = day / upload_id
        path.write_bytes(b"x")
        stamp = "2026-09-30T10:00:00"
        return {"id": upload_id, "path": str(path), "mime": "application/pdf", "size": 1,
                "hash": upload_id[:8], "owner": owner, "uploaded_at": stamp,
                "created_at": stamp, "last_accessed": stamp, **names}

    index = {
        "alice:old": row(MINE_OLD, "alice", name=FOLD, original_name=Q3),
        "bob:theirs": row(THEIRS, "bob", name="Bobs_plan.pdf", original_name="Bob's plan.pdf"),
        "alice:new": row(MINE_NEW, "alice", name="Notes_today.txt",
                         original_name="Notes – today.txt", display_name="Notes – today.txt"),
        "alice:split": row(SPLIT, "alice", name="Split_owner.pdf", original_name="Split: owner.pdf"),
        "bob:split": row(SPLIT, "bob", name="Split_owner.pdf", original_name="Split: owner.pdf"),
        "alice:nameless": row(NAMELESS, "alice"),
    }
    handler._atomic_write_json(str(root / "uploads.json"), index)
    return handler


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[DbSession.__table__, DbChatMessage.__table__])
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    s = factory()
    s.add(DbSession(id="s1", name="board", endpoint_url="http://m/v1", model="m",
                    owner="alice", message_count=2))
    s.add(DbChatMessage(id="m1", session_id="s1", role="user", content="see attached",
                        timestamp=datetime(2026, 9, 30, 10, 0, 0),
                        meta_data=json.dumps({"attachments": _saved_attachments()})))
    s.add(DbChatMessage(id="m2", session_id="s1", role="assistant", content="read it",
                        timestamp=datetime(2026, 9, 30, 10, 0, 1)))
    s.commit()
    s.close()
    monkeypatch.setattr(history_routes, "SessionLocal", factory)
    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda *_a, **_k: None)
    yield factory
    engine.dispose()


class _Session:
    def __init__(self, history):
        self.history = history
        self.model = "m"
        self.endpoint_url = "http://m/v1"
        self.name = "board"


class _Manager:
    def __init__(self, history):
        self.session = _Session(history)

    def get_session(self, _sid):
        return self.session


def _client(monkeypatch, manager, handler, *, viewer="alice"):
    monkeypatch.setattr(history_routes, "effective_user", lambda _request: viewer)
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(manager, upload_handler=handler))
    return TestClient(app)


def _names(response):
    assert response.status_code == 200, response.text
    [user] = [e for e in response.json()["history"] if e["role"] == "user"]
    return {a["id"]: a["name"] for a in user["metadata"]["attachments"]}


EXPECTED = {
    MINE_OLD: Q3,                       # the row's name: recovered from original_name
    MINE_NEW: "Notes – today.txt",      # the row's name: its display_name
    THEIRS: "Bobs_plan.pdf",            # not alice's upload: what was saved, nothing of bob's
    GONE: "Old_minutes.pdf",            # no row any more: what was saved
    SPLIT: "Split_owner.pdf",           # rows disagree about the owner: what was saved
    NAMELESS: "Kept_name.pdf",          # the row names nothing (not even its file's id): what was saved
}


# ── the row's `Verify:`, through each branch of the route ───────────────────

def test_an_old_chat_shows_the_attachments_own_name_after_a_reload(db, store, monkeypatch):
    """The page read straight from the database — what the browser asks for
    when it opens a chat."""
    client = _client(monkeypatch, _Manager([]), store)
    assert _names(client.get("/api/history/s1", params={"limit": 50})) == EXPECTED


def test_the_in_memory_session_answers_the_same_and_is_not_changed(db, store, monkeypatch):
    """The in-memory branch hands `msg.metadata` out by reference; the names
    are resolved on a copy, so the live session — which is what is saved back
    and what the model is given — still says what it said."""
    saved = {"attachments": _saved_attachments()}
    message = ChatMessage(role="user", content="see attached", metadata=saved)
    client = _client(monkeypatch, _Manager([message]), store)
    assert _names(client.get("/api/history/s1")) == EXPECTED
    assert message.metadata is saved
    assert saved == {"attachments": _saved_attachments()}, "the live message was rewritten"


def test_the_database_fallback_answers_the_same(db, store, monkeypatch):
    client = _client(monkeypatch, _Manager([]), store)
    assert _names(client.get("/api/history/s1")) == EXPECTED


# ── nothing is rewritten ─────────────────────────────────────────────────────

def test_the_saved_message_and_the_upload_index_are_left_as_they_were(db, store, monkeypatch):
    index = Path(store.upload_dir) / "uploads.json"
    before = index.read_bytes()
    client = _client(monkeypatch, _Manager([]), store)
    client.get("/api/history/s1", params={"limit": 50})
    client.get("/api/history/s1")
    s = db()
    try:
        saved = json.loads(s.query(DbChatMessage).filter_by(id="m1").one().meta_data)
    finally:
        s.close()
    assert saved == {"attachments": _saved_attachments()}, "history was rewritten on disk"
    assert index.read_bytes() == before, "showing a name touched the upload index"


# ── whose name is whose ─────────────────────────────────────────────────────

def test_another_reader_is_not_told_the_names_of_alices_uploads(db, store, monkeypatch):
    """The lookup is the reader's: a viewer who is not the upload's owner
    gets the saved names, never the row's."""
    client = _client(monkeypatch, _Manager([]), store, viewer="mallory")
    names = _names(client.get("/api/history/s1", params={"limit": 50}))
    assert names == {a["id"]: a["name"] for a in _saved_attachments()}


def test_a_single_user_install_resolves_unowned_uploads_only(db, tmp_path, monkeypatch):
    """With nobody signed in (auth off), an upload with no owner is the
    reader's; one stamped with an owner from when auth was on is not."""
    handler = UploadHandler(str(tmp_path / "b2"), str(tmp_path / "u2"))
    root = Path(handler.upload_dir)
    (root / "x").mkdir(parents=True)
    for upload_id in (MINE_OLD, MINE_NEW):
        (root / "x" / upload_id).write_bytes(b"x")
    handler._atomic_write_json(str(root / "uploads.json"), {
        "k1": {"id": MINE_OLD, "path": str(root / "x" / MINE_OLD), "owner": None,
               "name": FOLD, "original_name": Q3},
        "k2": {"id": MINE_NEW, "path": str(root / "x" / MINE_NEW), "owner": "alice",
               "name": "Notes_today.txt", "display_name": "Notes – today.txt"},
    })
    client = _client(monkeypatch, _Manager([]), handler, viewer=None)
    names = _names(client.get("/api/history/s1", params={"limit": 50}))
    assert names[MINE_OLD] == Q3
    assert names[MINE_NEW] == "Notes_today.txt"


def test_without_an_upload_handler_the_saved_names_stand_quietly(db, monkeypatch, caplog):
    """A router mounted with no upload handler has nothing to ask: the saved
    names stand, and nothing is logged as if a lookup had failed."""
    client = _client(monkeypatch, _Manager([]), None)
    with caplog.at_level("WARNING", logger=history_routes.logger.name):
        names = _names(client.get("/api/history/s1", params={"limit": 50}))
    assert names == {a["id"]: a["name"] for a in _saved_attachments()}
    assert not [r for r in caplog.records if r.name == history_routes.logger.name]


def test_an_unreadable_upload_index_still_opens_the_chat(db, store, monkeypatch):
    """A name is a nicety; the chat is not. A lookup that fails leaves the
    saved names and the history still answers."""
    def broken(*_a, **_k):
        raise ValueError("uploads.json is not JSON")

    monkeypatch.setattr(store, "display_names_for", broken)
    client = _client(monkeypatch, _Manager([]), store)
    names = _names(client.get("/api/history/s1", params={"limit": 50}))
    assert names == {a["id"]: a["name"] for a in _saved_attachments()}


def test_the_lookup_is_read_only_and_owner_scoped(store):
    """`display_names_for` directly: the reader's ids answer, others do not,
    an id that is not an upload id is not looked up, and nothing is written."""
    index = Path(store.upload_dir) / "uploads.json"
    before = index.read_bytes()
    assert store.display_names_for(
        [MINE_OLD, MINE_NEW, THEIRS, GONE, SPLIT, NAMELESS, "../../etc/passwd", ""], owner="alice",
    ) == {MINE_OLD: Q3, MINE_NEW: "Notes – today.txt"}
    assert store.display_names_for([THEIRS], owner="bob") == {THEIRS: "Bob's plan.pdf"}
    assert store.display_names_for([], owner="alice") == {}
    assert index.read_bytes() == before
