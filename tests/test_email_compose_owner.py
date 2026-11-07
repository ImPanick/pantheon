# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1967`. Only its owner attaches a document or a gallery image to a mail.

`compose-from-pantheon` and its zip variant stage a document or a gallery image
as a compose upload, which can then be downloaded or sent out of the box. The
loader's owner checks were still shaped like auth-off: a gallery image with no
owner passed (`if owner and img.owner and ...`), and so did a document with no
owner and no chat, or one whose chat had no owner. Rows like that are real: the
agent's images were saved with no owner until `B1922`, and a row with no owner
keeps it until the next boot gives it to the admin. So anyone signed in who had
the id could stage an image or a document that was not theirs.

The loader now asks the gallery's and the documents' own rules
(`gallery_helpers._owner_filter`, `document_helpers._verify_doc_owner`): the
row's owner, or for a legacy document with none, the owner of its chat. The
picker lists only a person's own rows, so nothing a person could pick is lost.
From upstream Odysseus #6559 (8f36a363, issue #5460), with the document half
upstream left alone; its auth-off case no longer exists here (`D-2026-10-07-02`
§2).
"""
from __future__ import annotations

import os

import pytest
from fastapi import HTTPException


@pytest.fixture
def compose(tmp_path, monkeypatch):
    import core.database as cdb
    import routes.email_helpers as EH
    import routes.email_routes as E
    import routes.gallery.gallery_routes as gallery_routes
    from tests.helpers.sqlite_db import make_temp_sqlite

    image = tmp_path / "pic.png"
    image.write_bytes(b"\x89PNG fake")
    staged = tmp_path / "compose"
    staged.mkdir()
    monkeypatch.setattr(EH, "COMPOSE_UPLOADS_DIR", staged)
    monkeypatch.setattr(E, "COMPOSE_UPLOADS_DIR", staged)
    monkeypatch.setattr(gallery_routes, "_gallery_image_path", lambda filename: image)
    monkeypatch.setattr(E, "_start_poller", lambda: None)

    Session, engine, tmpfile = make_temp_sqlite(cdb.Base.metadata)
    monkeypatch.setattr(cdb, "SessionLocal", Session)
    db = Session()
    db.add_all([
        cdb.GalleryImage(id="orphan", filename="orphan.png", owner=None, is_active=True),
        cdb.GalleryImage(id="alices", filename="alices.png", owner="alice", is_active=True),
        cdb.Session(id="nobodys-chat", name="chat", owner=None,
                    endpoint_url="http://127.0.0.1:1", model="m"),
        cdb.Session(id="alices-chat", name="chat", owner="alice",
                    endpoint_url="http://127.0.0.1:1", model="m"),
    ])
    for doc_id, owner, session_id in (
        ("orphan-doc", None, None),
        ("nobodys-chat-doc", None, "nobodys-chat"),
        ("alices-doc", "alice", None),
        ("alices-chat-doc", None, "alices-chat"),
    ):
        db.add(cdb.Document(id=doc_id, title=doc_id, language="markdown", current_content="# x",
                            owner=owner, session_id=session_id, is_active=True))
    db.commit()
    db.close()

    router = E.setup_email_routes()
    endpoints = {getattr(r, "name", ""): r.endpoint for r in router.routes}
    one, several = endpoints["compose_from_pantheon"], endpoints["compose_from_pantheon_zip"]

    def attach(kind, item_id, person):
        result = one({"kind": kind, "id": item_id}, owner=person)
        assert result["success"] is True and (staged / result["token"]).is_file()
        return result

    def attach_zip(items, person):
        return several({"items": items}, owner=person)

    yield attach, attach_zip
    engine.dispose()
    tmpfile.close()
    os.unlink(tmpfile.name)


def _refused(call, *args):
    with pytest.raises(HTTPException) as refused:
        call(*args)
    return refused.value.status_code, refused.value.detail


def test_a_gallery_image_is_attached_by_its_owner_and_by_nobody_else(compose):
    attach, _zip = compose
    attach("gallery", "alices", "alice")
    for image_id, person in (("alices", "bob"), ("orphan", "bob"), ("orphan", "alice")):
        assert _refused(attach, "gallery", image_id, person) == (404, "Image not found"), (image_id, person)


def test_a_document_is_attached_by_its_owner_or_its_chats_and_by_nobody_else(compose):
    attach, _zip = compose
    attach("document", "alices-doc", "alice")
    attach("document", "alices-chat-doc", "alice")
    for doc_id in ("alices-doc", "alices-chat-doc", "orphan-doc", "nobodys-chat-doc"):
        assert _refused(attach, "document", doc_id, "bob") == (404, "Document not found"), doc_id


def test_a_zip_holding_an_image_that_is_nobodys_is_refused_whole(compose):
    _attach, attach_zip = compose
    items = [{"kind": "gallery", "id": "alices"}, {"kind": "gallery", "id": "orphan"}]
    assert _refused(attach_zip, items, "alice") == (404, "Image not found")
