# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1995`. A `%` or `_` typed into a document search was read as a wildcard.

The Library's document search (`GET /api/documents/library?search=`) and the
agent's `manage_documents` list split a search into words and matched each one
with `ILIKE '%word%'`, the word exactly as typed. `%` and `_` are LIKE's
wildcards, so "100%" also found "1000 complete", "report_v2" found a document
made from "reportXv2.pdf", and a lone "_" or "%" found every document the
person has; on PostgreSQL a backslash was eaten as well, because ILIKE escapes
with it by default. Only the person's own documents were ever searched, so
nothing leaked: the list was wrong.

Now each word is escaped with `src.session_search.escape_like_pattern`, the
escaper the chat and Gallery searches already use (`B2004`), and matched with
`ESCAPE '\\'`, in the Library and in the agent's list alike (`P21-04` made
them one rule).

Ported from upstream Odysseus 70fc5822 (#6944). The cases are upstream's, run
over the four columns Pantheon searches (`P21-04` added the folder and the
name of the file a document was made from) and through the agent's list.

Driven (`Law 20`) through the real library route and the real
`manage_documents` dispatch on a real SQLite database, with the fixtures of
`tests/test_documents_keep_their_folders.py` and
`tests/test_the_agent_files_documents.py`.
"""
from __future__ import annotations

import pytest

import core.database as cdb
from tests.test_documents_keep_their_folders import ALICE, LONG_AGO, lib  # noqa: F401
from tests.test_the_agent_files_documents import call
from tests.test_the_agent_files_documents import lib as agent_lib  # noqa: F401

# (what is typed, a document holding exactly that, one a wildcard would also find)
CASES = [
    ("100%", "100% complete", "1000 complete"),
    ("a_b", "a_b", "axb"),
    ("%", "price 10%", "price 100"),
    ("_", "a_b", "axb"),
    (r"path\notes", r"path\notes", "pathnotes"),
    (r"path\_tag", r"path\_tag", r"path\Xtag"),
    ("50%_done", "50%_done", "500Xdone"),
    ("can't", "can't stop", "cannot stop"),
    ("mixed case", "Case ordered Mixed", "Mixed without"),
]


def _put(db_factory, doc_id, *, owner="alice", is_active=True, archived=False, **fields):
    values = {"title": "Document", "current_content": "Body", **fields}
    db = db_factory()
    try:
        db.add(cdb.Document(id=doc_id, owner=owner, is_active=is_active, archived=archived,
                            language="text", created_at=LONG_AGO, updated_at=LONG_AGO, **values))
        db.commit()
    finally:
        db.close()


def _clear(db_factory):
    db = db_factory()
    try:
        db.query(cdb.Document).delete()
        db.commit()
    finally:
        db.close()


def _library(lib, search, **params):
    res = lib.get("/api/documents/library", params={"search": search, **params}, headers=ALICE)
    assert res.status_code == 200, res.text
    return res.json()


def _ids(page):
    return {d["id"] for d in page["documents"]}


@pytest.mark.parametrize("column", ["title", "current_content", "folder", "source_name"])
def test_the_library_finds_each_word_as_it_was_typed(lib, column):
    wrong = {}
    for query, literal, lookalike in CASES:
        _clear(lib.db)
        for doc_id, owner, is_active, archived, text in (
            ("literal", "alice", True, False, literal),
            ("lookalike", "alice", True, False, lookalike),
            ("foreign", "bob", True, False, literal),
            ("inactive", "alice", False, False, literal),
            ("archived", "alice", True, True, literal),
        ):
            _put(lib.db, doc_id, owner=owner, is_active=is_active, archived=archived,
                 **{column: text})
        found = _library(lib, query)
        shelved = _library(lib, query, archived="true")
        if (_ids(found), found["total"], _ids(shelved)) != ({"literal"}, 1, {"archived"}):
            wrong[query] = {"found": sorted(_ids(found)), "archived view": sorted(_ids(shelved))}
    assert not wrong, f"searching the {column} matched more than was typed: {wrong}"


def test_a_literal_search_still_needs_every_word_and_still_pages(lib):
    for doc_id, title, content in (
        ("first", "100% ready", "done"),
        ("second", "done", "100% ready"),
        ("lookalike", "1000 ready", "done"),
        ("missing-term", "100% ready", "waiting"),
    ):
        _put(lib.db, doc_id, title=title, current_content=content)
    pages = [_library(lib, "100% done", language="text", sort="alpha", offset=offset, limit=1)
             for offset in (0, 1)]
    assert [page["total"] for page in pages] == [2, 2]
    assert set().union(*map(_ids, pages)) == {"first", "second"}


@pytest.mark.parametrize("column", ["title", "folder", "source_name"])
def test_the_agent_s_document_list_finds_each_word_as_it_was_typed(agent_lib, column):
    wrong = {}
    for query, literal, lookalike in CASES:
        _clear(agent_lib)
        for doc_id, owner, is_active, text in (
            ("literal", "alice", True, literal),
            ("lookalike", "alice", True, lookalike),
            ("foreign", "bob", True, literal),
            ("inactive", "alice", False, literal),
        ):
            _put(agent_lib, doc_id, owner=owner, is_active=is_active, **{column: text})
        found = call({"action": "list", "search": query})
        ids = {d["id"] for d in found.get("documents") or []}
        if ids != {"literal"}:
            wrong[query] = sorted(ids)
    assert not wrong, f"the agent's search of the {column} matched more than was typed: {wrong}"
