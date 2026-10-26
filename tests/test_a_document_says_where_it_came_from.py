# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1325` — a document records how its text was made, and the envelope its
open copy reaches the model in is chosen from that.

`B1300` gave the person's own material its own envelope (no accusing header,
the tool gate not armed) and could move only memory onto it: a document was
typed in the editor, imported from a file, or made by the agent, and nothing
afterwards could tell which. So the open document stayed on the untrusted
envelope — right for an imported PDF, wrong for a note the person wrote.

The row's `Verify:` — *a case per path that creates a document and asserts which
envelope its injection uses* — is driven on the real routes, the real agent
tools and a real SQLite file (`tests/test_an_uploaded_document_keeps_its_name.py`'s
harness), and the envelope is read off the message the agent loop builds
(`_minimal_pantheon_doc_messages`) for the stored row.

The adversary (`Law 17`) is text somebody else wrote steering a tool call, so
the safe side is the default: only `authored_here` is the person's own; NULL
(every document older than the column), `imported` and `derived` keep the gate.
"""
import ast
import asyncio
from pathlib import Path

import core.database as cdb
from src import document_provenance as prov
from src.prompt_security import OWN_MATERIAL_HEADER, UNTRUSTED_CONTEXT_HEADER
from tests.helpers.office_fixtures import office_fixture
from tests.test_an_uploaded_document_keeps_its_name import (  # noqa: F401
    OWNER, _auto_document, _doc, _email_with, _open_from_mailbox, _upload, env,
)

ROOT = Path(__file__).resolve().parent.parent


def _envelope(doc):
    """The active-document message the agent loop builds for *doc*."""
    from src.agent_loop import _minimal_pantheon_doc_messages

    out = _minimal_pantheon_doc_messages([{"role": "user", "content": "tidy this"}], doc)
    (msg,) = [m for m in out if "active editor document" in str(m.get("content"))]
    own = msg["content"].startswith(OWN_MATERIAL_HEADER)
    assert own != msg["content"].startswith(UNTRUSTED_CONTEXT_HEADER)
    return ("own" if own else "untrusted"), msg["metadata"]["tool_gate_untrusted"]


def _create(env, **body):
    r = env.client.post("/api/document", json={"session_id": "chat-1", "title": "t",
                                               "content": "words", **body})
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == _doc(env, r.json()["id"]).provenance
    return _doc(env, r.json()["id"])


# ── a case per path ─────────────────────────────────────────────────────────

def test_a_page_typed_in_the_editor_is_the_persons_own(env):
    doc = _create(env, provenance="authored_here")
    assert doc.provenance == "authored_here"
    assert _envelope(doc) == ("own", False)


def test_a_file_imported_in_the_browser_is_imported_whatever_it_asks(env):
    doc = _create(env, source_name="notes.txt", provenance="authored_here")
    assert doc.provenance == "imported"
    assert _envelope(doc) == ("untrusted", True)


def test_a_caller_that_says_nothing_is_not_trusted_by_default(env):
    """*Save to Docs* from a chat, a reply quoting an email: `derived`."""
    doc = _create(env)
    assert doc.provenance == "derived"
    assert _envelope(doc) == ("untrusted", True)
    assert _create(env, provenance="nonsense").provenance == "derived"


def test_a_file_opened_as_a_document_is_imported(env):
    r = env.client.post("/api/documents/import-office",
                        files={"file": ("brief.docx", office_fixture(".docx"), "")})
    assert r.status_code == 200, r.text
    doc = _doc(env, r.json()["id"])
    assert doc.provenance == "imported"
    assert _envelope(doc) == ("untrusted", True)


def test_a_chat_attachments_document_is_imported(env):
    doc, _said = _auto_document(env, _upload(env, "brief.docx", office_fixture(".docx")))
    assert doc.provenance == "imported"
    assert _envelope(doc) == ("untrusted", True)


def test_a_mail_attachment_opened_as_a_document_is_imported(env, monkeypatch):
    doc = _open_from_mailbox(env, monkeypatch, _email_with("notes.txt", b"from the mailbox"))
    assert doc.provenance == "imported"
    assert _envelope(doc) == ("untrusted", True)


def test_a_document_the_agent_writes_is_derived(env):
    from src.agent_tools.document_tools import CreateDocumentTool

    out = asyncio.run(CreateDocumentTool().execute(
        "Plan\nmarkdown\nthe agent's words", {"session_id": "chat-1", "owner": None}))
    doc = _doc(env, out.get("doc_id") or out.get("id"))
    assert doc.provenance == "derived"
    assert _envelope(doc) == ("untrusted", True)


def test_the_agent_editing_the_persons_page_makes_it_derived(env):
    from src.agent_tools.document_tools import UpdateDocumentTool

    doc = _create(env, provenance="authored_here")
    out = asyncio.run(UpdateDocumentTool().execute("rewritten by the agent",
                                                   {"doc_id": doc.id, "owner": OWNER}))
    assert not out.get("error"), out
    after = _doc(env, doc.id)
    assert after.current_content == "rewritten by the agent"
    assert after.provenance == "derived"
    assert _envelope(after) == ("untrusted", True)


def test_the_persons_own_edit_changes_nothing(env):
    mine = _create(env, provenance="authored_here")
    r = env.client.put(f"/api/document/{mine.id}", json={"content": "my second draft"})
    assert r.status_code == 200, r.text
    assert _doc(env, mine.id).provenance == "authored_here"
    imported = _create(env, source_name="paste.txt")
    env.client.put(f"/api/document/{imported.id}", json={"content": "corrected by me"})
    assert _doc(env, imported.id).provenance == "imported"


def test_a_document_older_than_the_column_keeps_the_envelope_it_had(env):
    db = env.Session()
    try:
        db.add(cdb.Document(id="old-1", title="old", current_content="text", owner=None))
        db.commit()
    finally:
        db.close()
    doc = _doc(env, "old-1")
    assert doc.provenance is None
    assert _envelope(doc) == ("untrusted", True)


def test_the_migration_adds_the_column_and_backfills_nothing(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE documents (id VARCHAR PRIMARY KEY, title VARCHAR)"))
        conn.execute(text("INSERT INTO documents (id, title) VALUES ('d1', 'kept')"))
    monkeypatch.setattr(cdb, "engine", engine)
    cdb._migrate_add_document_provenance_column()
    cdb._migrate_add_document_provenance_column()   # idempotent
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(documents)"))}
        row = conn.execute(text("SELECT title, provenance FROM documents")).one()
    assert "provenance" in cols and tuple(row) == ("kept", None)


# ── both injections read it ─────────────────────────────────────────────────

def test_both_places_the_open_document_is_injected_choose_by_provenance():
    """The full agent loop is one long function; its document message is the
    second of the two sites. Scoped by AST (`Law 20` option 2): every call that
    builds an "active editor document" message goes through
    `document_context_message`, none through the untrusted envelope directly."""
    tree = ast.parse((ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8"))
    builders = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "active editor document"):
            builders.append(ast.unparse(node.func))
    assert builders == ["document_context_message", "document_context_message"], builders


def test_the_vocabulary_is_three_words_and_resolves_safely():
    assert prov.resolve_created("authored_here") == "authored_here"
    assert prov.resolve_created("IMPORTED ") == "imported"
    assert prov.resolve_created(None) == "derived"
    assert prov.resolve_created("authored_here", source_name="x.pdf") == "imported"
