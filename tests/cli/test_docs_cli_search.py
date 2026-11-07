# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B2002`. `pantheon-docs search` found a phrase, not words, and `%` or `_` found everything.

`cmd_search` put the whole query into one `%{query}%` LIKE over a document's
title and text. Two words found only a document that held them side by side
and in that order ("machine learning" missed "machine notes on learning"). `%`
and `_` are LIKE's own wildcards, so a query of either listed every document.
And a query of spaces looked for that run of spaces.

Now every word has to appear, in the title or the text, in any order, and `%`,
`_` and `\` are matched as themselves: each word is escaped by
`src.session_search._escape_like`, the escaper the chat search uses, under
`ESCAPE '\'`. A query of only spaces lists every document, as an empty one did.

Ported from upstream Odysseus f00ae350 (#7007); the cases are upstream's, run
on a real SQLite file through the real `cmd_search`.
"""

import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Document
from tests.helpers.cli_loader import load_script

DOCUMENTS = {
    "doc-multiword": ("ML notes", "machine notes on learning"),
    "doc-percent": ("Fabric", "100% cotton"),
    "doc-underscore": ("sale_2024", "spring campaign"),
    "doc-backslash": ("Path", r"C:\photos\sunset"),
}


def _cli_with_documents(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'docs_cli_search.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    try:
        db.add_all([Document(id=doc_id, title=title, current_content=content)
                    for doc_id, (title, content) in DOCUMENTS.items()])
        db.commit()
    finally:
        db.close()
    cli = load_script("pantheon-docs")
    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    return cli


def _search_ids(cli, capsys, query):
    cli.cmd_search(SimpleNamespace(query=query, limit=50, pretty=False))
    return {doc["id"] for doc in json.loads(capsys.readouterr().out)}


def test_two_words_find_a_document_that_has_both_apart(monkeypatch, tmp_path, capsys):
    cli = _cli_with_documents(monkeypatch, tmp_path)

    assert _search_ids(cli, capsys, "machine learning") == {"doc-multiword"}
    # Every word, not any word.
    assert _search_ids(cli, capsys, "machine cotton") == set()


def test_a_percent_sign_finds_only_the_document_with_one(monkeypatch, tmp_path, capsys):
    cli = _cli_with_documents(monkeypatch, tmp_path)

    assert _search_ids(cli, capsys, "%") == {"doc-percent"}
    # The escape character is escaped too: unescaped, `\` would make the `%`
    # after it a literal one.
    assert _search_ids(cli, capsys, "\\") == {"doc-backslash"}


def test_an_underscore_finds_only_the_document_with_one(monkeypatch, tmp_path, capsys):
    cli = _cli_with_documents(monkeypatch, tmp_path)

    # Unescaped, `_` matches any one character, so every document matched.
    assert _search_ids(cli, capsys, "_") == {"doc-underscore"}


def test_a_query_of_only_spaces_lists_every_document(monkeypatch, tmp_path, capsys):
    cli = _cli_with_documents(monkeypatch, tmp_path)

    assert _search_ids(cli, capsys, "   ") == set(DOCUMENTS)
