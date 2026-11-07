# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1949`. The next autosave rewrote the version a person had saved.

The editor saves with `PUT /api/document/{id}` 800 ms after typing stops, and
a save within 60 seconds of the newest version a person made
(`source="user"`) rewrote that version in place, so that one burst of typing
is one version. It never asked what kind of version that was. An edit made a
minute after an import replaced "Imported from report.docx", and the imported
text was gone from the history; the "Saved version" a person pressed Save for
took the next autosave's text under its own label; a "Restored from v1" took
whatever was typed next.

Now an autosave extends only a version an autosave made, the one labelled
"Manual edit", and every other version is a checkpoint the next autosave
leaves alone. A forced save that names nothing is labelled "Saved version"
rather than "Manual edit", so the label tells the two apart. Upstream Odysseus
fixed this in #6586 (a43915b5) with a new column, a migration and a write lock
on every save; the label already said which versions were autosaves.

Driven (`Law 20`): the real document routes over `B1006`'s real SQLite
harness. Versions are stamped with the time they are written, so the 60-second
window holds without a fake clock.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_the_documents_tidy_asks_first import LONG_AGO, cdb, doc, world  # noqa: F401

ARRIVED = "The quarterly report, as it arrived."


@pytest.fixture
def editor(world, monkeypatch):
    """The document routes, as bob, over this world's database."""
    import routes.document.document_routes as droutes

    monkeypatch.setattr(droutes, "SessionLocal", world.db)
    monkeypatch.setattr(droutes, "get_current_user", lambda request: "bob")
    app = FastAPI()
    app.include_router(droutes.setup_document_routes(None, None))
    return TestClient(app)


def page(world, *versions):
    """A document of bob's with `versions` — `(summary, content, source, made)`,
    oldest first — whose current text is the newest one's."""
    doc_id = doc(world, "Quarterly report", content=versions[-1][1])
    db = world.db()
    for number, (summary, content, source, made) in enumerate(versions, start=1):
        db.add(cdb.DocumentVersion(id=f"{doc_id}-v{number}", document_id=doc_id,
                                   version_number=number, content=content, summary=summary,
                                   source=source, created_at=made))
    db.query(cdb.Document).filter(cdb.Document.id == doc_id).update(
        {cdb.Document.version_count: len(versions)})
    db.commit()
    db.close()
    return doc_id


def history(world, doc_id):
    db = world.db()
    try:
        return [(v.summary, v.content) for v in db.query(cdb.DocumentVersion)
                .filter(cdb.DocumentVersion.document_id == doc_id)
                .order_by(cdb.DocumentVersion.version_number).all()]
    finally:
        db.close()


def put(editor, doc_id, **body):
    res = editor.put(f"/api/document/{doc_id}", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def autosave(editor, doc_id, content):
    """What the editor sends 800 ms after typing stops: the text, nothing else."""
    return put(editor, doc_id, content=content)


@pytest.mark.parametrize("summary", ["Imported from report.docx", "Initial version"])
def test_the_text_a_document_arrived_with_survives_an_edit_a_minute_later(world, editor, summary):
    doc_id = page(world, (summary, ARRIVED, "user", datetime.utcnow()))
    out = autosave(editor, doc_id, "corrected by me")
    assert history(world, doc_id) == [(summary, ARRIVED), ("Manual edit", "corrected by me")]
    assert out["version_count"] == 2


@pytest.mark.parametrize("named", [True, False], ids=["saved-version", "forced-unnamed"])
def test_a_saved_version_survives_the_next_autosave(world, editor, named):
    """The footer's Save sends `force_version` and names the version "Saved
    version"; a caller that forces one without a name gets that label too."""
    doc_id = page(world, ("Initial version", ARRIVED, "user", LONG_AGO))
    put(editor, doc_id, content="the text I saved", force_version=True,
        **({"summary": "Saved version"} if named else {}))
    autosave(editor, doc_id, "typed after saving")
    assert history(world, doc_id) == [
        ("Initial version", ARRIVED),
        ("Saved version", "the text I saved"),
        ("Manual edit", "typed after saving"),
    ]


def test_a_restored_version_survives_the_next_autosave(world, editor):
    doc_id = page(world, ("Initial version", ARRIVED, "user", LONG_AGO),
                  ("Manual edit", "a later draft", "user", LONG_AGO))
    res = editor.post(f"/api/document/{doc_id}/restore/1")
    assert res.status_code == 200, res.text
    autosave(editor, doc_id, "typed after restoring")
    assert history(world, doc_id) == [
        ("Initial version", ARRIVED),
        ("Manual edit", "a later draft"),
        ("Restored from v1", ARRIVED),
        ("Manual edit", "typed after restoring"),
    ]


def test_typing_after_a_checkpoint_is_still_one_version(world, editor):
    """The coalescing stays: the autosaves after a checkpoint are one version,
    holding the newest text — they just no longer land on the checkpoint."""
    doc_id = page(world, ("Saved version", "the text I saved", "user", datetime.utcnow()))
    autosave(editor, doc_id, "typing")
    out = autosave(editor, doc_id, "typing, and more")
    assert history(world, doc_id) == [
        ("Saved version", "the text I saved"),
        ("Manual edit", "typing, and more"),
    ]
    assert out["version_count"] == 2
