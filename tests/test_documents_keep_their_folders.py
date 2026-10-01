# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P21-01` — documents live in folders a person makes, and the folders stay.

The owner, 2026-10-01: *"I'd like to be able to make folders to sort through
documents, and keep things tidy and organized."*

Before this row a document had no folder at all (`core.database.Document`), and
the only folders in the product were chats' — a bare string per chat, so a chat
folder exists exactly while a chat is in it. Every test below drives the real
routes through `TestClient`, against a real SQLite database built from the real
models (`Law 20`), and reads the answer back through the routes or the rows:

  * a folder is made, nested, renamed and moved, and the documents in it go
    with it — without being reported as edited;
  * an EMPTY folder survives, because a person makes a folder first and fills it
    later;
  * removing a folder never deletes a document silently: with something in it,
    the route refuses until told `move_up` or `delete`, its dry run says how
    many, and each answer does what it says;
  * another person's folder and documents are refused, and refusing touches
    nothing;
  * the library lists one folder, or Unfiled, and its search matches the folder
    path (`P21-04`'s folder half);
  * a database from before the column gains it, and its documents start Unfiled.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

import core.database as cdb  # noqa: E402
import routes.document_routes as droutes  # noqa: E402
import routes.document.document_folder_routes as froutes  # noqa: E402

ALICE = {"X-Test-User": "alice"}
BOB = {"X-Test-User": "bob"}
LONG_AGO = datetime(2025, 1, 2, 3, 4, 5)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """The document routes on a fresh database; `lib.db()` opens a session on it."""
    engine = create_engine(f"sqlite:///{tmp_path / 'docs.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    ts = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(droutes, "SessionLocal", ts)
    monkeypatch.setattr(froutes, "SessionLocal", ts)
    monkeypatch.setenv("AUTH_ENABLED", "true")

    app = FastAPI()

    @app.middleware("http")
    async def _who(request: Request, call_next):
        request.state.current_user = request.headers.get("X-Test-User")
        return await call_next(request)

    app.include_router(droutes.setup_document_routes(MagicMock(), None))
    client = TestClient(app)
    client.db = ts
    return client


def _doc(lib, owner, title, folder=None, **extra):
    doc_id = str(uuid.uuid4())
    db = lib.db()
    try:
        db.add(cdb.Document(id=doc_id, title=title, current_content=f"{title} body",
                            owner=owner, is_active=True, folder=folder,
                            created_at=LONG_AGO, updated_at=LONG_AGO, **extra))
        db.commit()
    finally:
        db.close()
    return doc_id


def _row(lib, doc_id):
    db = lib.db()
    try:
        d = db.query(cdb.Document).filter(cdb.Document.id == doc_id).one()
        return {"folder": d.folder, "is_active": d.is_active, "updated_at": d.updated_at}
    finally:
        db.close()


def _folders(lib, who=ALICE, archived=False):
    res = lib.get("/api/document-folders" + ("?archived=true" if archived else ""), headers=who)
    assert res.status_code == 200, res.text
    return res.json()


def _paths(lib, who=ALICE):
    return [f["path"] for f in _folders(lib, who)["folders"]]


def _post(lib, path, body, who=ALICE):
    return lib.post(path, json=body, headers=who)


# ── making and nesting ──────────────────────────────────────────────────────

def test_a_folder_is_made_nested_and_listed_with_its_parents(lib):
    res = _post(lib, "/api/document-folders", {"folder": "Clients/Acme"})
    assert res.status_code == 200, res.text
    assert res.json()["path"] == "Clients/Acme"
    made = [c["to"] for c in res.json()["changes"] if c["change"] == "created"]
    assert made == ["Clients", "Clients/Acme"]

    listed = {f["path"]: f for f in _folders(lib)["folders"]}
    assert listed["Clients"]["parent"] is None and listed["Clients"]["depth"] == 0
    assert listed["Clients/Acme"]["parent"] == "Clients"
    assert listed["Clients/Acme"]["name"] == "Acme" and listed["Clients/Acme"]["depth"] == 1


def test_an_empty_folder_stays_until_it_is_removed(lib):
    """The chats' model could not do this: a chat folder is a string on a chat,
    so a folder with nothing in it does not exist. A person makes a folder first
    and fills it later; it has to be there when they come back."""
    _post(lib, "/api/document-folders", {"folder": "Receipts"})
    doc = _doc(lib, "alice", "Lunch")
    _post(lib, "/api/document-folders/file", {"document_ids": [doc], "to": "Receipts"})
    _post(lib, "/api/document-folders/file", {"document_ids": [doc], "to": None})

    folders = {f["path"]: f for f in _folders(lib)["folders"]}
    assert "Receipts" in folders, "a folder emptied of its last document disappeared"
    assert folders["Receipts"]["total"] == 0


def test_making_a_folder_that_exists_says_so(lib):
    _post(lib, "/api/document-folders", {"folder": "Clients"})
    res = _post(lib, "/api/document-folders", {"folder": " Clients/ "})
    assert res.status_code == 409
    assert "already a folder called 'Clients'" in res.json()["detail"]


@pytest.mark.parametrize("bad, words", [
    ("Unfiled/Thing", "Unfiled"),
    ("a/../b", "not a folder name"),
    ("bad\x07name", "control characters"),
    ("x" * 81, "at most 80"),
    ("/".join("abcdefghi"), "at most 8 deep"),
])
def test_a_name_that_cannot_be_a_folder_is_refused_and_says_why(lib, bad, words):
    res = _post(lib, "/api/document-folders", {"folder": bad})
    assert res.status_code == 400
    assert words in res.json()["detail"]
    assert _paths(lib) == []


# ── filing ──────────────────────────────────────────────────────────────────

def test_filing_documents_moves_them_and_is_not_an_edit(lib):
    """Filing goes through an UPDATE that writes `updated_at` back to itself.
    Without that, filing twenty documents made all twenty the most recently
    edited in the library's default sort."""
    a, b = _doc(lib, "alice", "Board pack"), _doc(lib, "alice", "Minutes")
    res = _post(lib, "/api/document-folders/file",
                {"document_ids": [a, b], "to": "Clients/Acme"})
    assert res.status_code == 200, res.text
    moved = [c for c in res.json()["changes"] if c["change"] == "moved"]
    assert {(c["id"], c["from"], c["to"]) for c in moved} == {(a, None, "Clients/Acme"),
                                                             (b, None, "Clients/Acme")}
    for doc_id in (a, b):
        row = _row(lib, doc_id)
        assert row["folder"] == "Clients/Acme"
        assert row["updated_at"] == LONG_AGO, "filing a document stamped it as edited"

    counts = _folders(lib)
    assert counts["unfiled"] == 0 and counts["all"] == 2
    by = {f["path"]: f for f in counts["folders"]}
    assert (by["Clients"]["count"], by["Clients"]["total"]) == (0, 2)
    assert (by["Clients/Acme"]["count"], by["Clients/Acme"]["total"]) == (2, 2)


def test_the_library_lists_one_folder_or_the_unfiled_ones(lib):
    filed = _doc(lib, "alice", "Board pack", folder="Clients/Acme")
    deeper = _doc(lib, "alice", "Contract", folder="Clients/Acme/Legal")
    loose = _doc(lib, "alice", "Shopping list")

    def ids(query):
        res = lib.get(f"/api/documents/library?{query}", headers=ALICE)
        assert res.status_code == 200, res.text
        return {d["id"]: d["folder"] for d in res.json()["documents"]}

    assert ids("folder=Clients/Acme") == {filed: "Clients/Acme"}
    assert ids("folder=Clients/%20Acme/") == {filed: "Clients/Acme"}
    assert ids("unfiled=true") == {loose: None}
    assert ids("") == {filed: "Clients/Acme", deeper: "Clients/Acme/Legal", loose: None}


def test_the_library_search_matches_the_folder_a_document_is_in(lib):
    """`P21-04`, the folder half: "acme" finds what is filed in Clients/Acme
    even when neither its title nor its text says Acme."""
    filed = _doc(lib, "alice", "Q3 Board Pack", folder="Clients/Acme")
    _doc(lib, "alice", "Shopping list")
    res = lib.get("/api/documents/library?search=acme", headers=ALICE)
    assert [d["id"] for d in res.json()["documents"]] == [filed]


# ── renaming and moving a folder ────────────────────────────────────────────

def test_renaming_a_folder_takes_its_documents_and_folders_with_it(lib):
    a = _doc(lib, "alice", "Board pack", folder="Clients/Acme")
    b = _doc(lib, "alice", "Note", folder="Clients")
    _post(lib, "/api/document-folders", {"folder": "Clients/Empty"})
    res = _post(lib, "/api/document-folders/rename", {"folder": "Clients", "name": "Customers"})
    assert res.status_code == 200, res.text
    assert res.json()["changes"] == [{"change": "moved", "kind": "folder", "from": "Clients",
                                      "to": "Customers", "documents": 2}]
    assert _row(lib, a)["folder"] == "Customers/Acme"
    assert _row(lib, b)["folder"] == "Customers"
    assert _paths(lib) == ["Customers", "Customers/Acme", "Customers/Empty"]
    assert _row(lib, a)["updated_at"] == LONG_AGO


def test_a_rename_onto_an_existing_folder_or_with_a_slash_is_refused(lib):
    _post(lib, "/api/document-folders", {"folder": "Clients"})
    _post(lib, "/api/document-folders", {"folder": "Customers"})
    taken = _post(lib, "/api/document-folders/rename", {"folder": "Clients", "name": "Customers"})
    assert taken.status_code == 409
    slash = _post(lib, "/api/document-folders/rename", {"folder": "Clients", "name": "A/B"})
    assert slash.status_code == 400 and "can't contain '/'" in slash.json()["detail"]
    assert _paths(lib) == ["Clients", "Customers"]


def test_moving_a_folder_nests_it_and_it_cannot_go_inside_itself(lib):
    doc = _doc(lib, "alice", "Contract", folder="Legal/2026")
    _post(lib, "/api/document-folders", {"folder": "Clients/Acme"})
    res = _post(lib, "/api/document-folders/move", {"folder": "Legal", "to": "Clients/Acme"})
    assert res.status_code == 200, res.text
    assert _row(lib, doc)["folder"] == "Clients/Acme/Legal/2026"
    assert _paths(lib) == ["Clients", "Clients/Acme", "Clients/Acme/Legal",
                           "Clients/Acme/Legal/2026"]

    into_self = _post(lib, "/api/document-folders/move",
                      {"folder": "Clients", "to": "Clients/Acme/Legal"})
    assert into_self.status_code == 400 and "into itself" in into_self.json()["detail"]

    back = _post(lib, "/api/document-folders/move", {"folder": "Clients/Acme/Legal", "to": None})
    assert back.status_code == 200
    assert _row(lib, doc)["folder"] == "Legal/2026"


def test_a_move_with_no_destination_key_is_refused_not_read_as_the_top(lib):
    """`to` is required-but-nullable: a client that forgets it must not move
    the folder to the top level by accident."""
    _post(lib, "/api/document-folders", {"folder": "Clients/Acme"})
    res = _post(lib, "/api/document-folders/move", {"folder": "Clients/Acme"})
    assert res.status_code == 422
    assert _paths(lib) == ["Clients", "Clients/Acme"]


# ── removing a folder: never a silent delete ────────────────────────────────

def test_removing_a_folder_with_things_in_it_is_refused_until_told_what_to_do(lib):
    _doc(lib, "alice", "Board pack", folder="Clients/Acme")
    _doc(lib, "alice", "Old", folder="Clients", archived=True)
    dry = _post(lib, "/api/document-folders/remove", {"folder": "Clients", "dry_run": True})
    assert dry.status_code == 200
    body = dry.json()
    assert (body["documents"], body["archived"], body["folders"]) == (2, 1, 1)
    assert body["changes"] == []

    refused = _post(lib, "/api/document-folders/remove", {"folder": "Clients"})
    assert refused.status_code == 400
    assert "holds 2 documents and 1 folder" in refused.json()["detail"]
    assert "Clients" in _paths(lib)


def test_removing_with_move_up_puts_everything_one_level_up(lib):
    top = _doc(lib, "alice", "Note", folder="Clients")
    inner = _doc(lib, "alice", "Board pack", folder="Clients/Acme")
    _post(lib, "/api/document-folders", {"folder": "Clients/Empty"})
    res = _post(lib, "/api/document-folders/remove", {"folder": "Clients", "contents": "move_up"})
    assert res.status_code == 200, res.text
    assert _row(lib, top)["folder"] is None, "a top-level folder's documents become Unfiled"
    assert _row(lib, inner)["folder"] == "Acme"
    assert _row(lib, top)["is_active"] and _row(lib, inner)["is_active"]
    assert _paths(lib) == ["Acme", "Empty"]


def test_removing_a_nested_folder_with_move_up_merges_into_the_parent(lib):
    doc = _doc(lib, "alice", "Board pack", folder="Clients/Acme/Legal")
    _post(lib, "/api/document-folders", {"folder": "Clients/Legal"})
    res = _post(lib, "/api/document-folders/remove",
                {"folder": "Clients/Acme", "contents": "move_up"})
    assert res.status_code == 200, res.text
    assert _row(lib, doc)["folder"] == "Clients/Legal"
    assert _paths(lib) == ["Clients", "Clients/Legal"]


def test_removing_a_folder_whose_child_has_its_own_name_keeps_the_child(lib):
    """Removing "a/a" moves "a/a/a" up onto the exact path being removed."""
    _post(lib, "/api/document-folders", {"folder": "a/a/a"})
    res = _post(lib, "/api/document-folders/remove", {"folder": "a/a", "contents": "move_up"})
    assert res.status_code == 200, res.text
    assert _paths(lib) == ["a", "a/a"]


def test_removing_with_delete_deletes_exactly_what_it_said(lib):
    a = _doc(lib, "alice", "Board pack", folder="Clients/Acme")
    b = _doc(lib, "alice", "Note", folder="Clients")
    keep = _doc(lib, "alice", "Shopping list")
    res = _post(lib, "/api/document-folders/remove", {"folder": "Clients", "contents": "delete"})
    assert res.status_code == 200, res.text
    deleted = {c["id"] for c in res.json()["changes"] if c["change"] == "deleted"}
    assert deleted == {a, b}
    assert not _row(lib, a)["is_active"] and not _row(lib, b)["is_active"]
    assert _row(lib, keep)["is_active"]
    assert _paths(lib) == []
    assert _folders(lib)["all"] == 1


def test_an_empty_folder_is_removed_without_a_choice(lib):
    _post(lib, "/api/document-folders", {"folder": "Clients/Acme"})
    res = _post(lib, "/api/document-folders/remove", {"folder": "Clients/Acme"})
    assert res.status_code == 200, res.text
    assert _paths(lib) == ["Clients"], "removing the last folder inside took the parent too"


def test_an_unknown_choice_is_refused(lib):
    doc = _doc(lib, "alice", "Board pack", folder="Clients")
    res = _post(lib, "/api/document-folders/remove", {"folder": "Clients", "contents": "shred"})
    assert res.status_code == 400
    assert _row(lib, doc) == {"folder": "Clients", "is_active": True, "updated_at": LONG_AGO}


# ── owner scope ─────────────────────────────────────────────────────────────

def test_another_persons_folders_and_documents_are_refused_and_untouched(lib):
    alices = _doc(lib, "alice", "Board pack", folder="Clients")
    bobs = _doc(lib, "bob", "Bob's note")

    assert _paths(lib, BOB) == []
    for path, body in [
        ("/api/document-folders/rename", {"folder": "Clients", "name": "Mine"}),
        ("/api/document-folders/move", {"folder": "Clients", "to": "Elsewhere"}),
        ("/api/document-folders/remove", {"folder": "Clients", "contents": "delete"}),
        ("/api/document-folders/remove", {"folder": "Clients", "dry_run": True}),
    ]:
        res = _post(lib, path, body, BOB)
        assert res.status_code == 404, (path, res.text)
        assert res.json()["detail"] == "Folder 'Clients' not found"

    stolen = _post(lib, "/api/document-folders/file", {"document_ids": [alices], "to": "Bob"}, BOB)
    assert stolen.status_code == 404

    # All or nothing: one foreign id in the list and bob's own document stays put too.
    mixed = _post(lib, "/api/document-folders/file",
                  {"document_ids": [bobs, alices], "to": "Bob"}, BOB)
    assert mixed.status_code == 404
    assert _row(lib, bobs)["folder"] is None
    assert _row(lib, alices) == {"folder": "Clients", "is_active": True, "updated_at": LONG_AGO}
    assert _paths(lib) == ["Clients"]
    assert _paths(lib, BOB) == []

    # The same name is a different folder for somebody else.
    assert _post(lib, "/api/document-folders", {"folder": "Clients"}, BOB).status_code == 200
    assert _post(lib, "/api/document-folders/remove", {"folder": "Clients"}, BOB).status_code == 200
    assert _paths(lib) == ["Clients"]


def test_nobody_signed_in_is_refused(lib):
    assert lib.get("/api/document-folders").status_code == 403
    assert lib.post("/api/document-folders", json={"folder": "X"}).status_code in (401, 403)


# ── an old database ─────────────────────────────────────────────────────────

_LEGACY_DOCUMENTS = """
CREATE TABLE documents (
    id VARCHAR NOT NULL PRIMARY KEY,
    session_id VARCHAR,
    title VARCHAR NOT NULL,
    language VARCHAR,
    current_content TEXT NOT NULL,
    version_count INTEGER,
    is_active BOOLEAN,
    archived BOOLEAN,
    owner VARCHAR,
    tidy_verdict VARCHAR,
    source_email_uid VARCHAR,
    source_email_folder VARCHAR,
    source_email_account_id VARCHAR,
    source_email_message_id VARCHAR,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""


def test_an_old_database_gains_the_column_and_its_documents_start_unfiled(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_DOCUMENTS)
    conn.execute("INSERT INTO documents (id, title, current_content, version_count, is_active, "
                 "archived, owner, created_at, updated_at) VALUES ('old', 'Old doc', 'x', 1, 1, 0, "
                 "'alice', '2025-01-01 00:00:00', '2025-01-01 00:00:00')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)    # what init_db does first: new tables only
    cols = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(documents)")]
    assert "folder" not in cols, "create_all is not supposed to alter an existing table"

    cdb._migrate_add_document_folder_column()
    cdb._migrate_add_document_folder_column()   # idempotent

    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
    indexes = [r[1] for r in conn.execute("PRAGMA index_list(documents)")]
    folder = conn.execute("SELECT folder FROM documents WHERE id='old'").fetchone()[0]
    conn.close()
    assert "folder" in cols
    assert "ix_documents_folder" in indexes
    assert folder is None

    # And the upgraded database works through the routes.
    ts = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(droutes, "SessionLocal", ts)
    monkeypatch.setattr(froutes, "SessionLocal", ts)
    app = FastAPI()

    @app.middleware("http")
    async def _who(request: Request, call_next):
        request.state.current_user = "alice"
        return await call_next(request)

    app.include_router(droutes.setup_document_routes(MagicMock(), None))
    client = TestClient(app)
    assert client.get("/api/document-folders").json()["unfiled"] == 1
    assert client.post("/api/document-folders/file",
                       json={"document_ids": ["old"], "to": "Archive"}).status_code == 200
    assert client.get("/api/documents/library?folder=Archive").json()["total"] == 1


# ── the admin wipe ──────────────────────────────────────────────────────────

def test_wiping_the_documents_wipes_their_folders_too(monkeypatch):
    """An admin's "wipe documents" that left every folder standing, empty,
    would not be a wiped library."""
    from fastapi import Request as _Request
    import routes.admin_wipe_routes as wipe

    engine = create_engine("sqlite:///:memory:")
    cdb.Base.metadata.create_all(bind=engine)
    ts = sessionmaker(bind=engine)
    db = ts()
    db.add(cdb.Document(id="d1", title="T", current_content="x", owner="alice", folder="Clients"))
    db.add(cdb.DocumentFolder(id="f1", owner="alice", path="Clients"))
    db.add(cdb.DocumentFolder(id="f2", owner="alice", path="Empty"))
    db.commit()
    db.close()
    monkeypatch.setattr(wipe, "SessionLocal", ts)
    monkeypatch.setattr(wipe, "require_admin", lambda r: None)
    router = wipe.setup_admin_wipe_routes(session_manager=None)
    handler = next(r for r in router.routes if r.path == "/api/admin/wipe/{kind}").endpoint
    result = handler(kind="documents", request=_Request(scope={"type": "http"}))
    db = ts()
    try:
        assert result["count"] == 1
        assert db.query(cdb.Document).count() == 0
        assert db.query(cdb.DocumentFolder).count() == 0
    finally:
        db.close()
