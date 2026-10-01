# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1035` — the library's AI tidy does not mark the documents it keeps as edited.

`POST /api/documents/ai-tidy` asks a model whether each unreviewed document is
junk, deletes the junk and writes `tidy_verdict = "keep"` on the rest so it never
asks about them again. That write went through the ORM, and `updated_at` is
`TimestampMixin`'s `onupdate` column, so measured on the tree before this row:
two documents last edited 2025-01-02, both judged "keep", came back with
`updated_at` at the moment of the tidy — at the top of the library's default
sort, reading "edited just now". A review reported as edits, which is exactly
what `document_folders`' header records filing used to do.

The verdict is now written the way `document_folders._refile` writes a folder
and `B1019`'s `remember_kept` writes the person's own mark — an UPDATE that
writes `updated_at` back to itself — through one writer both tidies' verdicts
share (`document_actions.write_tidy_verdict`).

Driven through the library's real routes on `B1006`'s real SQLite harness, with
only the model's reply faked (`Law 20`).
"""

import json
import re
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_the_documents_tidy_asks_first import LONG_AGO, cdb, doc, world  # noqa: F401


@pytest.fixture
def library(world, monkeypatch):
    """The library's real routes, as bob. The model answers by title from
    `library.verdicts` (anything unnamed is "keep"), and records what it was
    asked."""
    import routes.document.document_routes as droutes
    import src.llm_core as llm_core
    import src.task_endpoint as task_endpoint

    verdicts, asked = {}, []

    async def model(url, model_name, messages, **kwargs):
        prompt = messages[-1]["content"]
        asked.append(prompt)
        titles = re.findall(r'^\[\d+\] title="(.*?)"', prompt, re.MULTILINE)
        return json.dumps([verdicts.get(t, "keep") for t in titles])

    monkeypatch.setattr(llm_core, "llm_call_async", model)
    monkeypatch.setattr(task_endpoint, "resolve_task_endpoint",
                        lambda owner=None: ("http://127.0.0.1:1/v1", "m", {}))
    monkeypatch.setattr(droutes, "SessionLocal", world.db)
    monkeypatch.setattr(droutes, "get_current_user", lambda request: "bob")
    app = FastAPI()
    app.include_router(droutes.setup_document_routes(None, None))
    client = TestClient(app)

    def tidy():
        res = client.post("/api/documents/ai-tidy")
        assert res.status_code == 200, res.text
        return res.json()

    def shelf():
        """The library as a person sees it: the default sort, with each
        document's edited time."""
        res = client.get("/api/documents/library")
        assert res.status_code == 200, res.text
        return [(d["title"], d["updated_at"]) for d in res.json()["documents"]]

    return type("Library", (), {"verdicts": verdicts, "asked": asked,
                                "tidy": staticmethod(tidy), "shelf": staticmethod(shelf)})


#: Edited a month after it was made, so "its own time" is not its creation time.
LATER = LONG_AGO + timedelta(days=30)


def edited(world, doc_id, when):
    db = world.db()
    db.query(cdb.Document).filter(cdb.Document.id == doc_id).update(
        {cdb.Document.updated_at: when})
    db.commit()
    db.close()


def rows(world):
    db = world.db()
    try:
        return {d.title: (d.updated_at, d.tidy_verdict, d.current_content)
                for d in db.query(cdb.Document).all()}
    finally:
        db.close()


# ── the row ─────────────────────────────────────────────────────────────────

def test_a_document_the_ai_tidy_keeps_keeps_its_edited_time(world, library):
    doc(world, "Budget 2026", content="real numbers")
    edited(world, doc(world, "Trip plan", content="Lisbon in May"), LATER)
    out = library.tidy()
    assert (out["reviewed"], out["deleted"]) == (2, 0), out
    assert rows(world) == {
        "Budget 2026": (LONG_AGO, "keep", "real numbers"),
        "Trip plan": (LATER, "keep", "Lisbon in May"),
    }


def test_the_library_reads_the_same_after_a_tidy_that_kept_everything(world, library):
    """The row's Verify, as the library shows it: nothing jumps to the top of
    the default sort, and no "edited" time moves."""
    doc(world, "Budget 2026", content="real numbers")
    doc(world, "Trip plan", content="Lisbon in May", created=LONG_AGO + timedelta(days=1))
    doc(world, "Today's notes", content="typed a minute ago",
        created=datetime.utcnow() - timedelta(minutes=1))
    before = library.shelf()
    assert [title for title, _t in before] == ["Today's notes", "Trip plan", "Budget 2026"]
    assert library.tidy()["reviewed"] == 3
    assert library.shelf() == before


def test_any_answer_but_junk_is_a_keep_and_not_an_edit(world, library):
    """The route keeps whatever is not "junk" — an odd or empty answer too."""
    doc(world, "Budget 2026", content="real numbers")
    doc(world, "Trip plan", content="Lisbon in May")
    library.verdicts.update({"Budget 2026": "maybe", "Trip plan": ""})
    assert library.tidy()["reviewed"] == 2
    assert {t: r[:2] for t, r in rows(world).items()} == {
        "Budget 2026": (LONG_AGO, "keep"), "Trip plan": (LONG_AGO, "keep")}


def test_junk_is_still_removed_and_the_rest_keep_their_time(world, library):
    doc(world, "Budget 2026", content="real numbers")
    doc(world, "asdf", content="qwerty")
    doc(world, "Trip plan", content="Lisbon in May")
    library.verdicts["asdf"] = "junk"
    out = library.tidy()
    assert (out["reviewed"], out["deleted"]) == (3, 1), out
    assert rows(world) == {
        "Budget 2026": (LONG_AGO, "keep", "real numbers"),
        "Trip plan": (LONG_AGO, "keep", "Lisbon in May"),
    }


# ── what does not move ──────────────────────────────────────────────────────

def test_the_verdict_is_remembered(world, library):
    """The keep is still written: the next tidy has nothing to ask about."""
    doc(world, "Budget 2026", content="real numbers")
    library.tidy()
    assert library.tidy() == {"deleted": 0, "reviewed": 0,
                              "message": "All documents already reviewed"}
    assert len(library.asked) == 1


def test_a_document_already_reviewed_is_not_touched(world, library):
    """A row with a verdict — the AI's own, or the person's `kept:` mark — is
    skipped, as before."""
    reviewed = doc(world, "Budget 2026", content="real numbers")
    kept = doc(world, "test", content="a test the person kept")
    db = world.db()
    db.query(cdb.Document).filter(cdb.Document.id == reviewed).update(
        {cdb.Document.tidy_verdict: "keep", cdb.Document.updated_at: LONG_AGO})
    db.query(cdb.Document).filter(cdb.Document.id == kept).update(
        {cdb.Document.tidy_verdict: "kept:abc", cdb.Document.updated_at: LONG_AGO})
    db.commit()
    db.close()
    doc(world, "Trip plan", content="Lisbon in May")
    assert library.tidy()["reviewed"] == 1
    assert {t: r[:2] for t, r in rows(world).items()} == {
        "Budget 2026": (LONG_AGO, "keep"), "test": (LONG_AGO, "kept:abc"),
        "Trip plan": (LONG_AGO, "keep")}
    [prompt] = library.asked
    assert 'title="Trip plan"' in prompt and 'title="Budget 2026"' not in prompt
