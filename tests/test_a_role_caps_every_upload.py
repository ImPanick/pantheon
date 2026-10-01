# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B932` — a role's byte cap reaches every upload route, for the person uploading.

`P12-01` resolves each upload cap role profile → instance setting → env →
built-in default, and `P11-02`'s done text says every limit in the product
inherits the role layer "with no call site changing". Five route files did not:
each called `resolve_byte_limit("<key>")` with no owner, and the role provider
was asked about `None`. Measured 2026-09-30:
`resolve_byte_limit_with_source("stt_max_audio_bytes")` →
`(26214400, 'built-in default')`, with `"alice"` → `(1024, 'role profile')`.

Each route below now passes the caller, and each is driven through its real
router with a real multipart upload (`Law 20`). The role provider caps `alice`
at 1 KB and says nothing about `bob`. Three things are asked of every route:

  * `alice`'s 2 KB upload is refused with **the role's** number (1 KB);
  * `bob`'s same 2 KB upload is **not** refused by the cap;
  * `bob`'s 8 KB upload, with the environment capping the key at 4 KB, is
    refused with the environment's number — which proves `bob`'s request
    reaches the cap at all, so the second point is not a route failing early.

The personal-document route refuses an oversized file by counting it failed
rather than with a 413 (`P12-03`), so there the same three facts are read off
its `failed` / `indexed` counts.
"""

import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import src.settings as S
from src.upload_limits import BYTE_LIMITS

pytest.importorskip("sqlalchemy")

CAPPED, FREE = "alice", "bob"
SMALL, LARGE = b"x" * 2048, b"x" * 8192


@pytest.fixture
def roles(tmp_path, monkeypatch):
    """`alice` is in a role that caps every upload at 1 KB; `bob` is in none."""
    monkeypatch.setattr(S, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    for env_name, _default in BYTE_LIMITS.values():
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(S, "_role_limit_provider",
                        lambda key, owner: 1024 if owner == CAPPED else None)
    S._invalidate_caches()
    yield
    S._invalidate_caches()


def _app(*routers) -> FastAPI:
    app = FastAPI()
    for r in routers:
        app.include_router(r)

    @app.middleware("http")
    async def _who(request: Request, call_next):
        # What the auth middleware does: name the person on the request.
        request.state.current_user = request.headers.get("x-test-user")
        return await call_next(request)

    return app


def _client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _three(post, env_name, monkeypatch, refused):
    """The three facts, for one route. `post(user, body)` returns a response;
    `refused(resp, kb)` says whether it was refused by a cap of `kb` KB."""
    capped = post(CAPPED, SMALL)
    assert refused(capped, 1), (capped.status_code, capped.text[:300])
    free = post(FREE, SMALL)
    assert not refused(free, None), (
        f"bob, in no role, was refused: {free.status_code} {free.text[:300]}")
    monkeypatch.setenv(env_name, "4096")
    reached = post(FREE, LARGE)
    assert refused(reached, 4), (reached.status_code, reached.text[:300])


def _413(resp, kb):
    if resp.status_code != 413:
        return False
    return kb is None or f"exceeds {kb} KB" in resp.text


# ── STT ────────────────────────────────────────────────────────────────────

def test_speech_to_text(roles, monkeypatch):
    from routes.stt_routes import setup_stt_routes

    class _Stt:
        available = True

        def transcribe(self, audio):
            return "heard"

    client = _client(_app(setup_stt_routes(_Stt())))

    def post(user, body):
        return client.post("/api/stt/transcribe", files={"file": ("a.webm", body)},
                           headers={"x-test-user": user})

    _three(post, "PANTHEON_STT_MAX_AUDIO_BYTES", monkeypatch, _413)
    assert post(FREE, SMALL).json() == {"text": "heard"}


# ── a calendar's .ics import ───────────────────────────────────────────────

def _ics(size: int) -> bytes:
    head = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//EN\r\nBEGIN:VEVENT\r\n"
            "UID:e1@test\r\nDTSTART:20261001T090000Z\r\nDTEND:20261001T100000Z\r\n"
            "SUMMARY:standup\r\nDESCRIPTION:")
    tail = "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    return (head + "x" * (size - len(head) - len(tail)) + tail).encode()


def test_a_calendar_import(roles, monkeypatch):
    import core.database as cdb
    import routes.calendar_routes as cr
    from tests.helpers.sqlite_db import make_temp_sqlite

    Session, _engine, _tmp = make_temp_sqlite(cdb.Base.metadata)
    monkeypatch.setattr(cr, "SessionLocal", Session)
    client = _client(_app(cr.setup_calendar_routes()))

    def post(user, body):
        # A real calendar of the same size, so bob's is imported, not refused.
        return client.post("/api/calendar/import", files={"file": ("cal.ics", _ics(len(body)))},
                           headers={"x-test-user": user})

    _three(post, "PANTHEON_ICS_MAX_BYTES", monkeypatch, _413)
    monkeypatch.delenv("PANTHEON_ICS_MAX_BYTES")
    assert post(FREE, SMALL).status_code == 200


# ── a file attached to an email being written ──────────────────────────────

def test_an_email_attachment(roles, monkeypatch, tmp_path):
    import routes.email_helpers as EH
    import routes.email_routes as E

    compose = tmp_path / "compose"
    compose.mkdir()
    monkeypatch.setattr(E, "_start_poller", lambda: None)
    monkeypatch.setattr(EH, "COMPOSE_UPLOADS_DIR", compose)
    monkeypatch.setattr(E, "COMPOSE_UPLOADS_DIR", compose)
    client = _client(_app(E.setup_email_routes()))

    def post(user, body):
        return client.post("/api/email/compose-upload", files={"file": ("notes.txt", body)},
                           headers={"x-test-user": user})

    _three(post, "PANTHEON_EMAIL_COMPOSE_UPLOAD_MAX_BYTES", monkeypatch, _413)
    monkeypatch.delenv("PANTHEON_EMAIL_COMPOSE_UPLOAD_MAX_BYTES")
    staged = post(FREE, SMALL).json()
    assert staged["success"] is True and staged["size"] == len(SMALL)


def test_an_email_attachment_staged_from_pantheon_is_capped_for_its_owner(roles, monkeypatch, tmp_path):
    """The two staging helpers behind "attach a Pantheon document" and "attach
    several as a zip" check the same cap; they are handed the owner now."""
    import routes.email_helpers as EH
    import routes.email_routes as E

    compose = tmp_path / "compose"
    compose.mkdir()
    monkeypatch.setattr(E, "_start_poller", lambda: None)
    monkeypatch.setattr(EH, "COMPOSE_UPLOADS_DIR", compose)
    monkeypatch.setattr(E, "COMPOSE_UPLOADS_DIR", compose)
    import core.database as cdb
    from tests.helpers.sqlite_db import make_temp_sqlite

    Session, _engine, _tmp = make_temp_sqlite(cdb.Base.metadata)
    monkeypatch.setattr(cdb, "SessionLocal", Session)
    db = Session()
    for owner in (CAPPED, FREE):
        db.add(cdb.Document(id=f"d-{owner}", title="minutes", language="markdown",
                            current_content=SMALL.decode(), owner=owner, is_active=True))
    db.commit()
    db.close()
    client = _client(_app(E.setup_email_routes()))

    def post(user):
        return client.post("/api/email/compose-from-pantheon",
                           json={"kind": "document", "id": f"d-{user}"},
                           headers={"x-test-user": user})

    capped = post(CAPPED)
    assert capped.status_code == 413, capped.text
    assert post(FREE).json()["success"] is True


# ── the gallery: an upload, and the two image transforms ───────────────────

def _png(size: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 90, 160)).save(buf, "PNG")
    data = buf.getvalue()
    return data + b"\0" * max(0, size - len(data))


@pytest.fixture
def gallery(roles, monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    import core.database as cdb
    import routes.gallery.gallery_routes as G

    engine = create_engine(f"sqlite:///{tmp_path / 'gallery.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(G, "SessionLocal", Session)
    monkeypatch.setattr(cdb, "SessionLocal", Session)
    images = tmp_path / "gallery"
    images.mkdir()
    monkeypatch.setattr(G, "GALLERY_IMAGE_DIR", images)
    # One picture each, for the routes that work on an image a person owns.
    db = Session()
    for owner in (CAPPED, FREE):
        (images / f"{owner}.png").write_bytes(_png(0))
        db.add(cdb.GalleryImage(id=f"img-{owner}", filename=f"{owner}.png", prompt="", model="",
                                tags="", ai_tags="", owner=owner, is_active=True, file_size=10))
    db.commit()
    db.close()
    client = _client(_app(G.setup_gallery_routes()))
    client.images = images
    return client


def test_a_gallery_upload(gallery, monkeypatch):
    def post(user, body):
        return gallery.post("/api/gallery/upload", files={"file": ("p.png", _png(len(body)), "image/png")},
                            headers={"x-test-user": user})

    _three(post, "PANTHEON_GALLERY_UPLOAD_MAX_BYTES", monkeypatch, _413)


def test_a_gallery_picture_replaced(gallery, monkeypatch):
    def post(user, body):
        return gallery.post(f"/api/gallery/img-{user}/replace",
                            files={"image": ("p.png", _png(len(body)), "image/png")},
                            headers={"x-test-user": user})

    _three(post, "PANTHEON_GALLERY_UPLOAD_MAX_BYTES", monkeypatch, _413)


def test_a_gallery_picture_attached_to_an_email(gallery, monkeypatch, tmp_path):
    """The other staging helper: a gallery image is copied from disk, and its
    size checked against the same cap — for its owner."""
    import routes.email_helpers as EH
    import routes.email_routes as E

    compose = tmp_path / "compose"
    compose.mkdir()
    monkeypatch.setattr(E, "_start_poller", lambda: None)
    monkeypatch.setattr(EH, "COMPOSE_UPLOADS_DIR", compose)
    monkeypatch.setattr(E, "COMPOSE_UPLOADS_DIR", compose)
    for owner in (CAPPED, FREE):
        (gallery.images / f"{owner}.png").write_bytes(_png(len(SMALL)))
    client = _client(_app(E.setup_email_routes()))

    def post(user):
        return client.post("/api/email/compose-from-pantheon",
                           json={"kind": "gallery", "id": f"img-{user}"},
                           headers={"x-test-user": user})

    capped = post(CAPPED)
    assert capped.status_code == 413, capped.text
    assert post(FREE).json()["success"] is True


@pytest.mark.parametrize("route", ["/api/gallery/ai-upscale", "/api/gallery/style-transfer"])
def test_a_gallery_transform(gallery, monkeypatch, route):
    def post(user, body):
        return gallery.post(route, files={"image": ("p.png", _png(len(body)), "image/png")},
                            data={"prompt": "ink"}, headers={"x-test-user": user})

    _three(post, "PANTHEON_GALLERY_TRANSFORM_UPLOAD_MAX_BYTES", monkeypatch, _413)


# ── a document added to the personal library ───────────────────────────────

def test_a_personal_document(roles, monkeypatch, tmp_path):
    import routes.personal_routes as P

    class _Rag:
        def _split_into_chunks(self, text, chunk_size=500):
            return [text]

        def add_document(self, chunk, meta):
            return True

    monkeypatch.setattr(P, "UPLOADS_DIR", str(tmp_path / "personal"))
    monkeypatch.setattr(P, "get_rag_manager", lambda: _Rag())
    manager = type("M", (), {"add_directory": lambda *a, **k: None})()
    client = _client(_app(P.setup_personal_routes(manager, _Rag(), True)))

    def post(user, body):
        return client.post("/api/personal/upload", files=[("files", ("notes.txt", body, "text/plain"))],
                           headers={"x-test-user": user})

    def refused(resp, _kb):
        # `P12-03`: an oversized file is counted failed, not answered 413.
        body = resp.json()
        return resp.status_code == 200 and body.get("failed_count") == 1 and not body.get("indexed_count")

    _three(post, "PANTHEON_PERSONAL_UPLOAD_MAX_BYTES", monkeypatch, refused)
