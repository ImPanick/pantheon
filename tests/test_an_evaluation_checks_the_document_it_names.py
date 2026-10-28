# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — a case's document check reads the document it names.

The harness's `document` check took every document whose title *contains* the
one named and read the last of them. That is right for a title with a date in
it ("Inbox triage" finds "Inbox triage — 27 Oct"), and wrong the moment an
agent writes a document named after the one it read: Style Keeper writes
"Restyled — Launch note" beside "Launch note", so a case asking "is the
original still as it was?" read the restyled copy and could never pass —
and a case asking the reverse would pass for the wrong document. Found writing
Style Keeper's and Translator's evaluations. A document with exactly the
title named is the one read; with none, the check matches as before.
"""

from __future__ import annotations

import uuid

from src.agents import evals as E


def _check(want):
    from core.database import Document
    with E.isolated() as (factory, data):
        db = factory()
        db.add(Document(id=str(uuid.uuid4()), owner=E.EVAL_OWNER, title="Launch note",
                        current_content="We will e-mail 3 customers."))
        db.commit()
        db.add(Document(id=str(uuid.uuid4()), owner=E.EVAL_OWNER, title="Restyled — Launch note",
                        current_content="We will email three customers."))
        db.commit()
        out = E._check("document", want, db=db, owner=E.EVAL_OWNER, answer="", status="success",
                       world=E.World({}), notebook="", project_root=data)
        db.close()
    return out


def test_the_document_with_exactly_the_title_named_is_the_one_read():
    assert _check({"title": "Launch note", "contains": ["e-mail 3 customers"]})["ok"]
    assert not _check({"title": "Launch note", "contains": ["three customers"]})["ok"]


def test_a_title_named_in_part_still_finds_the_longer_one():
    assert _check({"title": "Restyled", "contains": ["email three customers"]})["ok"]


def test_a_file_check_can_say_what_the_file_must_lack(tmp_path):
    """`P24-27`. A document check could say what it must lack — the check of
    a *never* — and a file check could not: Mockup Maker's "never load a font
    or a script from the internet" had nothing to hold it to. A file now may
    lack words as a document may, and the bar counts that as a never."""
    page = tmp_path / "mockups" / "a.html"
    page.parent.mkdir()
    page.write_text('<link href="https://fonts.example/css">', encoding="utf-8")

    def check(want):
        return E._check("file", want, db=None, owner=E.EVAL_OWNER, answer="", status="success",
                        world=E.World({}), notebook="", project_root=str(tmp_path))

    assert check({"path": "mockups/a.html", "contains": ["<link"]})["ok"]
    bad = check({"path": "mockups/a.html", "lacks": ["https://"]})
    assert not bad["ok"] and "https://" in bad["detail"]
    from tests.test_an_agent_has_substance import _negative
    assert _negative({"file": {"path": "mockups/a.html", "lacks": ["https://"]}})
    assert not _negative({"file": {"path": "mockups/a.html", "contains": ["<link"]}})
