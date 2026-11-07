# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1948`. The library's Tidy deleted documents that had text in them.

The Tidy button in the document library runs two passes, and both delete for
good. The rules pass (`POST /api/documents/tidy`) deleted every document
titled "Untitled", "Untitled document", "Document", "Draft", "test" or another
throwaway name, whatever was written in it, and every document whose current
text was empty, although its saved versions held text and were deleted with
it. Those titles are what the agent's and the API's documents are called when
nobody names them, what an import is called after its file ("Untitled
document.docx"), and what a person calls a draft. The model pass
(`POST /api/documents/ai-tidy`) applied the model's verdicts by position, so an
answer that skipped one gave every later document its neighbour's verdict and
deleted the wrong one; and it sent documents made a minute ago, although the
dialog says the last 15 minutes are left alone.

Now a junk title or an empty page deletes only what holds no text, now or in a
saved version (`document_actions.has_saved_text`), as `B1781` did for chats;
an empty envelope and a throwaway still go. The model pass leaves the last 15
minutes alone and changes nothing when the number of verdicts is off. What the
model calls junk is still deleted for good: archiving it instead, as upstream
Odysseus #6590 (71177469) does, is the owner's call.

Driven (`Law 20`): the library's real routes over `B1006`'s real SQLite
harness, with only the model's reply faked.
"""

import json
import re
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_the_documents_tidy_asks_first import LONG_AGO, cdb, doc, world  # noqa: F401
from tests.test_a_document_the_ai_tidy_keeps_is_not_edited import library  # noqa: F401

TEXT = "Ship the migration in stages and keep every customer record."


def version(world, doc_id, number, content, summary="Saved version"):
    db = world.db()
    db.add(cdb.DocumentVersion(id=f"{doc_id}-v{number}", document_id=doc_id,
                               version_number=number, content=content, summary=summary,
                               source="user", created_at=LONG_AGO))
    db.commit()
    db.close()


def mail(world, title, content):
    """A mail draft as Compose makes one: a document in `email`."""
    doc_id = "e-" + uuid.uuid4().hex[:10]
    db = world.db()
    db.add(cdb.Document(id=doc_id, title=title, current_content=content, owner="bob",
                        language="email", is_active=True, created_at=LONG_AGO,
                        updated_at=LONG_AGO))
    db.commit()
    db.close()
    return doc_id


def client():
    """The library's real routes; `library` has pointed them at this world's
    database and signed in bob."""
    import routes.document.document_routes as droutes

    app = FastAPI()
    app.include_router(droutes.setup_document_routes(None, None))
    return TestClient(app)


def tidy_by_the_rules():
    res = client().post("/api/documents/tidy")
    assert res.status_code == 200, res.text
    return res.json()


def library_now(world):
    db = world.db()
    try:
        return {d.id: (d.title, d.tidy_verdict) for d in db.query(cdb.Document).all()}
    finally:
        db.close()


def versions(world, doc_id):
    db = world.db()
    try:
        return [v.content for v in db.query(cdb.DocumentVersion)
                .filter(cdb.DocumentVersion.document_id == doc_id)
                .order_by(cdb.DocumentVersion.version_number).all()]
    finally:
        db.close()


# ── the rules pass ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", ["Untitled", "Untitled document", "Document", "Draft", "test"])
def test_a_document_with_text_is_never_deleted_for_its_title(world, library, title):
    kept = doc(world, title, content=TEXT)
    out = tidy_by_the_rules()
    assert kept in library_now(world), f"{title!r} had text in it and was deleted for its title"
    assert out["deleted"] == 0, out


@pytest.mark.parametrize("title", ["Quarterly plan", "Untitled"])
def test_an_emptied_page_whose_saved_versions_hold_text_is_kept_with_them(world, library, title):
    emptied = doc(world, title, content="")
    version(world, emptied, 1, TEXT, summary="Initial version")
    version(world, emptied, 2, "", summary="Manual edit")
    tidy_by_the_rules()
    assert emptied in library_now(world), "the delete would have taken its saved text with it"
    assert versions(world, emptied) == [TEXT, ""]


def test_an_untitled_document_that_stays_is_named_from_its_text(world, library):
    named = doc(world, "Untitled", content="# Quarterly plan\n\n" + TEXT)
    out = tidy_by_the_rules()
    assert library_now(world)[named][0] == "Quarterly plan"
    assert out["fixed_titles"] == 1, out


def test_what_holds_no_text_still_goes_and_nothing_else_does(world, library):
    """What the dialog's "empty and junk" means: nothing to keep in it, now or
    in any saved version."""
    gone = {
        "an empty page": doc(world, "Untitled", content=""),
        "a placeholder": doc(world, "Untitled", content="# Untitled"),
        "an envelope nobody typed into": mail(world, "New Email", "To: \nSubject: \n---"),
        "a test name with a throwaway in it": doc(world, "test", content="asdf"),
        "a junk title whose versions are throwaways": doc(world, "Draft", content=""),
    }
    version(world, gone["a junk title whose versions are throwaways"], 1, "scratch")
    stays = {
        "a page with text": doc(world, "Budget 2026", content="real numbers"),
        "a test name with text": doc(world, "test", content=TEXT),
        "an emptied draft with a saved version": doc(world, "Draft", content=""),
    }
    version(world, stays["an emptied draft with a saved version"], 1, TEXT)
    out = tidy_by_the_rules()
    left = library_now(world)
    for what, doc_id in gone.items():
        assert doc_id not in left, f"{what} is what Tidy is for"
    for what, doc_id in stays.items():
        assert doc_id in left, f"{what} was deleted"
    assert out["deleted"] == len(gone), out


# ── the model pass ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("off_by", [-1, 1], ids=["one-verdict-short", "one-verdict-over"])
def test_an_answer_whose_count_is_off_changes_nothing(world, library, monkeypatch, off_by):
    """By position, a skipped verdict hands each later document the verdict of
    the one after it, and a junk verdict deletes for good."""
    import src.llm_core as llm_core

    judged = {"asdf": "junk", "Thesis chapter 3": "keep", "scratch": "junk", "Budget 2026": "keep"}
    for title in judged:
        doc(world, title, content=f"{title} notes")
    before = library_now(world)

    async def model(url, model_name, messages, **kwargs):
        titles = re.findall(r'^\[\d+\] title="(.*?)"', messages[-1]["content"], re.MULTILINE)
        answer = [judged[t] for t in titles]
        return json.dumps(answer[1:] if off_by < 0 else answer + ["junk"])

    monkeypatch.setattr(llm_core, "llm_call_async", model)
    res = client().post("/api/documents/ai-tidy")
    assert res.status_code == 500, res.text
    assert f"{4 + off_by} verdicts for 4 documents" in res.json()["detail"]
    assert library_now(world) == before, "a misaligned answer deleted or marked documents"


def test_a_document_made_in_the_last_15_minutes_is_not_sent_to_the_model(world, library):
    fresh = doc(world, "asdf", content="qwerty", created=datetime.utcnow() - timedelta(minutes=1))
    doc(world, "Budget 2026", content="real numbers")
    library.verdicts["asdf"] = "junk"
    out = library.tidy()
    assert (out["reviewed"], out["deleted"]) == (1, 0), out
    assert library_now(world)[fresh] == ("asdf", None)
    [prompt] = library.asked
    assert 'title="asdf"' not in prompt and 'title="Budget 2026"' in prompt
