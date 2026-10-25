# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1453`, `B1454`, `B1263` — every route the deep audit found with no caller
is gone, or now has the door it lacked.

The 2026-10-25 audit traced each route `check-unreachable.py` flagged. The ones
nothing in the product, the agent's tools, the integrations or the docs ever
called were superseded (the notes POSTs by `PUT`, compare's server flow by the
browser's), one-off cleanups for past bugs, or a fetcher that would have
reached GitHub on a person's behalf — so they are retired. Four had a use and
no way in: the uploads' stats and cleanup, the RAG index's stats, and the
not-spam override. They have doors now. And two admin ways to delete every
chat disagreed about the chats' images; the one that remains is the thorough
one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

RETIRED = [
    ("routes/compare/compare_routes.py", '@router.post("/start")'),
    ("routes/compare/compare_routes.py", '@router.post("/{comp_id}/vote")'),
    ("routes/note/note_routes.py", '@router.post("/{note_id}/pin")'),
    ("routes/note/note_routes.py", '@router.post("/{note_id}/archive")'),
    ("routes/note/note_routes.py", '@router.post("/{note_id}/items/{index}/toggle")'),
    ("routes/gallery/gallery_routes.py", '@router.get("/api/gallery/tags")'),
    ("routes/gallery/gallery_routes.py", '@router.get("/api/gallery/stats")'),
    ("routes/gallery/gallery_routes.py", '@router.post("/api/gallery/dedupe-tags")'),
    ("routes/gallery/gallery_routes.py", '@router.post("/api/gallery/clear-user-tags")'),
    ("routes/session_routes.py", '@router.post("/session/openai")'),
    ("routes/session_routes.py", '@router.post("/session/{sid}/delete")'),
    ("routes/session_routes.py", '@router.delete("/sessions/all")'),
    ("routes/session_routes.py", '@router.post("/sessions/save")'),
    ("routes/history/history_routes.py", '@router.get("/api/conversations/topics")'),
    ("routes/shell_routes.py", '@router.post("/api/cookbook/packages/install")'),
    ("routes/email_routes.py", '@router.get("/contacts")'),
    ("routes/email_routes.py", '@router.post("/attachment-path/{uid}/{index}")'),
    ("routes/cookbook_routes.py", '@router.get("/api/cookbook/vllm-recipe-manifest")'),
    ("routes/cookbook_routes.py", '@router.get("/api/cookbook/vllm-recipe")'),
]


@pytest.mark.parametrize("path, decorator", RETIRED)
def test_a_route_with_no_caller_is_retired(path, decorator):
    assert decorator not in (ROOT / path).read_text(encoding="utf-8")


@pytest.mark.parametrize("js, url", [
    ("static/js/admin.js", "/api/upload/stats"),
    ("static/js/admin.js", "/api/upload/cleanup"),
    ("static/js/admin.js", "/api/rag/stats"),
    ("static/js/emailLibrary.js", "/unflag-spam"),
])
def test_a_route_with_a_use_has_a_door(js, url):
    assert url in (ROOT / js).read_text(encoding="utf-8")


def test_the_doors_are_drawn():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for el in ('id="adm-uploadsStats"', 'id="adm-uploadsCleanBtn"', 'id="adm-ragStats"'):
        assert el in html, el


def test_the_agent_is_not_told_about_routes_that_do_not_exist():
    loop = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    assert "/api/compare/start" not in loop and "/api/compare/sessions" not in loop


def test_every_chat_goes_with_its_images(tmp_path, monkeypatch):
    """The one way to delete every chat retires the chats' gallery images and
    their files too — what `DELETE /api/sessions/all` did and the Danger Zone's
    `chats` wipe did not."""
    import core.database as cdb
    import src.session_image_cleanup as sic
    from tests.helpers.sqlite_db import make_temp_sqlite

    SessionLocal, engine, tmpfile = make_temp_sqlite(cdb.Base.metadata)
    img_dir = tmp_path / "generated"
    img_dir.mkdir()
    (img_dir / "pic.png").write_bytes(b"png")
    monkeypatch.setattr(sic, "GENERATED_IMAGES_DIR", str(img_dir))

    db = SessionLocal()
    db.add(cdb.Session(id="s1", name="c", endpoint_url="http://x", model="m", owner="ada"))
    db.add(cdb.ChatMessage(id="m1", session_id="s1", role="user", content="hi"))
    db.add(cdb.GalleryImage(id="g1", filename="pic.png", session_id="s1", is_active=True,
                            owner="ada", prompt="p"))
    db.commit()

    class _SM:
        sessions = {"s1": object()}

    sm = _SM()
    done = sic.wipe_every_session(db, sm)
    assert done == {"count": 1, "images_deleted": 1}
    assert db.query(cdb.Session).count() == 0 and db.query(cdb.ChatMessage).count() == 0
    assert db.query(cdb.GalleryImage).filter_by(id="g1").one().is_active is False
    assert not (img_dir / "pic.png").exists()
    assert sm.sessions == {}
    db.close()


def test_the_danger_zone_chats_wipe_runs_the_thorough_delete():
    src = (ROOT / "routes" / "admin_wipe" / "admin_wipe_routes.py").read_text(encoding="utf-8")
    body = src[src.index('if kind == "chats":'):src.index('if kind == "memory":')]
    assert "wipe_every_session(db, session_manager)" in body
