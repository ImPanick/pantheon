# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for issue #1346 — attaching more than one file at once made
the model "not even see" the attachments.

Root cause: the per-IP concurrency guard in routes/upload_routes.py summed its
condition over `files`, and the condition didn't depend on the loop variable, so
it collapsed to `len(files)` whenever the IP had any recent upload. A multi-file
batch sent right after a single upload (the reporter's exact flow) therefore
counted itself as N concurrent uploads and tripped `max_concurrent_uploads`,
returning 429. The browser swallowed the 429 (no `files` in the body) and sent
the chat message with no attachments.

The fix counts genuine recent upload *events*, independent of the current
batch's file count. save_upload still enforces the per-minute rate limit.
"""
import io
import re
import types
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import GalleryImage
from src.upload_handler import (
    MAX_FILES_PER_REQUEST,
    count_recent_uploads,
    UploadHandler,
)
import routes.upload_routes as up

_REPO = Path(__file__).resolve().parent.parent


def test_count_recent_uploads_ignores_batch_size():
    now = 1_000.0
    # No prior uploads -> zero, regardless of how big the incoming batch is.
    assert count_recent_uploads([], now) == 0
    # Only events inside the window are counted.
    assert count_recent_uploads([now - 1, now - 2, now - 3], now, window=10) == 3
    assert count_recent_uploads([now - 1, now - 50], now, window=10) == 1
    assert count_recent_uploads([now - 11], now, window=10) == 0


def _fake_handler(reject=None, status=429, detail="Upload rate limit exceeded. Please try again later."):
    """A stand-in UploadHandler.

    ``reject`` is a set of filenames whose save_upload raises HTTPException,
    standing in for the real per-file rejections (429 rate limit, 400 empty /
    oversized file) that save_upload can raise part-way through a batch.
    """
    reject = set(reject or ())
    h = types.SimpleNamespace()
    h.upload_rate_log = {}
    h.max_concurrent_uploads = 3

    def save_upload(u, client_ip, owner=None):
        name = getattr(u, "filename", "f")
        if name in reject:
            raise HTTPException(status_code=status, detail=detail)
        # Mimic the real handler: every saved file logs a timestamp.
        h.upload_rate_log.setdefault(client_ip, []).append(_NOW)
        return {
            "id": "0" * 32 + "." + "txt",
            "name": name,
            "mime": "text/plain",
            "size": 1,
            "hash": "h",
            "uploaded_at": "now",
            "width": None,
            "height": None,
            "is_duplicate": False,
        }

    h.save_upload = save_upload
    return h


_NOW = 5_000.0


def _endpoint(router):
    for r in router.routes:
        if getattr(r, "path", None) == "/api/upload" and "POST" in getattr(r, "methods", set()):
            return r.endpoint
    raise AssertionError("upload endpoint not found")


def _request(ip="1.2.3.4", user="tester"):
    return types.SimpleNamespace(
        client=types.SimpleNamespace(host=ip),
        state=types.SimpleNamespace(current_user=user),
    )


def _files(n):
    return [types.SimpleNamespace(filename=f"f{i}.txt") for i in range(n)]


def _image_upload(name="photo.png", content=b"not really png but enough for route metadata"):
    return types.SimpleNamespace(filename=name, file=io.BytesIO(content))


@pytest.fixture(autouse=True)
def _freeze_time(monkeypatch):
    # This used to also swap in a fresh `up.router` before every test, with the
    # comment "Module-level router accumulates routes across setup calls; reset
    # it." It did, and three test files carried a workaround for it — that is
    # `B53`. `setup_upload_routes` builds its own router now and returns it, so
    # there is nothing to reset.
    #
    # Freeze time so the seeded "recent upload" is deterministic.
    monkeypatch.setattr(up.time, "time", lambda: _NOW)


async def test_multifile_after_a_recent_upload_is_not_rejected():
    """The bug: one prior upload + a 3-file batch -> 429. Must now succeed."""
    h = _fake_handler()
    h.upload_rate_log["1.2.3.4"] = [_NOW - 1]  # step 1: a single file moments ago
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    result = await endpoint(_request(), _files(3))

    assert [f["name"] for f in result["files"]] == ["f0.txt", "f1.txt", "f2.txt"]


async def test_fresh_multifile_upload_succeeds():
    h = _fake_handler()
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    result = await endpoint(_request(), _files(5))

    assert len(result["files"]) == 5


async def test_genuine_recent_volume_still_throttled():
    """The guard is preserved: enough genuine recent uploads still 429s."""
    from fastapi import HTTPException

    h = _fake_handler()
    h.upload_rate_log["1.2.3.4"] = [_NOW - 1, _NOW - 2, _NOW - 3]  # 3 recent events
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    with pytest.raises(HTTPException) as ei:
        await endpoint(_request(), _files(1))
    assert ei.value.status_code == 429


# ── #1346 follow-up: the per-minute rate limit must not reject a single
# full multi-file batch. The reporter found "5 attachments work, 6 fail":
# save_upload() counts each file against upload_rate_limit, which was 5 while
# the composer allows MAX_FILES=10. ──────────────────────────────────────────

def _max_files_from_frontend() -> int:
    src = (_REPO / "static/js/fileHandler.js").read_text(encoding="utf-8")
    m = re.search(r"MAX_FILES\s*=\s*(\d+)", src)
    assert m, "MAX_FILES not found in fileHandler.js"
    return int(m.group(1))


def test_rate_limit_accommodates_a_full_batch():
    # The per-minute file cap must comfortably exceed the frontend batch cap,
    # or a single legitimate multi-file attach trips it (issue #1346).
    h = UploadHandler.__new__(UploadHandler)
    UploadHandler.__init__(h, base_dir="/tmp", upload_dir="/tmp/_pantheon_test_uploads_cfg")
    assert h.upload_rate_limit >= _max_files_from_frontend()


def test_six_file_batch_is_not_rate_limited(tmp_path):
    from fastapi import HTTPException

    h = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "uploads"))
    saved = 0
    for i in range(6):
        u = types.SimpleNamespace(
            file=io.BytesIO(f"file number {i} unique content".encode()),
            filename=f"f{i}.txt",
        )
        try:
            meta = h.save_upload(u, client_ip="9.9.9.9", owner="tester")
        except HTTPException as e:
            raise AssertionError(f"file {i} rejected with {e.status_code}: {e.detail}")
        assert meta and meta.get("id")
        saved += 1
    assert saved == 6


# ── P2-11: the batch cap and the partial-write hazard ────────────────────────
# Before this, POST /api/upload had no server-side len(files) cap at all — the
# only ceilings were starlette's form parser (max_files=1000) and the per-IP
# rate limit, and the rate limit only fires part-way through a batch. The route
# then re-raised that per-file HTTPException, so the request failed with 429
# while the files saved before it stayed on disk and in the index.


def test_batch_cap_sits_between_the_frontend_cap_and_the_rate_limit():
    """Derived-state check: the server cap has to live inside a window.

    Below the browser's MAX_FILES and a legitimate full batch gets a 400.
    Above upload_rate_limit and the tail of an accepted batch 429s mid-write.
    Raising either end without moving MAX_FILES_PER_REQUEST fails here.
    """
    h = UploadHandler.__new__(UploadHandler)
    UploadHandler.__init__(h, base_dir="/tmp", upload_dir="/tmp/_pantheon_test_uploads_cfg")
    assert MAX_FILES_PER_REQUEST >= _max_files_from_frontend()
    assert MAX_FILES_PER_REQUEST <= h.upload_rate_limit


async def test_a_full_frontend_batch_is_accepted_by_the_server():
    h = _fake_handler()
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    result = await endpoint(_request(), _files(_max_files_from_frontend()))

    assert len(result["files"]) == _max_files_from_frontend()


async def test_oversized_batch_is_rejected_before_anything_is_written():
    h = _fake_handler()
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    with pytest.raises(HTTPException) as ei:
        await endpoint(_request(), _files(MAX_FILES_PER_REQUEST + 1))

    assert ei.value.status_code == 400
    assert str(MAX_FILES_PER_REQUEST) in str(ei.value.detail)
    # Rejected whole: save_upload was never reached, so nothing was logged.
    assert h.upload_rate_log == {}


async def test_batch_at_the_cap_is_accepted():
    h = _fake_handler()
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    result = await endpoint(_request(), _files(MAX_FILES_PER_REQUEST))

    assert len(result["files"]) == MAX_FILES_PER_REQUEST


async def test_one_rejected_file_does_not_discard_the_files_already_written():
    """The partial-write hazard: file 3 429s after files 1-2 are on disk."""
    h = _fake_handler(reject={"f2.txt"})
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    result = await endpoint(_request(), _files(4))

    assert [f["name"] for f in result["files"]] == ["f0.txt", "f1.txt", "f3.txt"]
    assert [r["name"] for r in result["rejected"]] == ["f2.txt"]
    assert result["rejected"][0]["status"] == 429


async def test_a_clean_batch_reports_no_rejections():
    h = _fake_handler()
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    result = await endpoint(_request(), _files(3))

    assert "rejected" not in result


async def test_when_every_file_is_rejected_the_original_status_survives():
    """Nothing was written, so there is no partial state to protect — the
    caller keeps the precise reason instead of a blanket 500."""
    h = _fake_handler(reject={"f0.txt"}, status=429)
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    with pytest.raises(HTTPException) as ei:
        await endpoint(_request(), _files(1))

    assert ei.value.status_code == 429
    assert "rate limit" in str(ei.value.detail).lower()


async def test_a_400_rejection_also_survives_when_nothing_was_written():
    h = _fake_handler(reject={"f0.txt", "f1.txt"}, status=400, detail="File is empty")
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    with pytest.raises(HTTPException) as ei:
        await endpoint(_request(), _files(2))

    assert ei.value.status_code == 400
    assert ei.value.detail == "File is empty"


# ── P2-01 (DECISIONS.md D-2026-08-26-01): the upload type blocklist is gone ──


def test_upload_type_blocklist_is_deleted():
    """is_safe_file_type and both 9-entry lists were deleted deliberately.

    Pinned so a later agent restoring "just the .exe entry" has to read the
    decision (and its reopen conditions) first rather than reflexively re-adding
    a check the audit proved was not buying what it looked like it bought.
    """
    assert not hasattr(UploadHandler, "is_safe_file_type")
    src = (_REPO / "src/upload_handler.py").read_text(encoding="utf-8")
    assert "dangerous_types" not in src
    assert "dangerous_extensions" not in src


def test_executable_named_upload_is_saved(tmp_path):
    """The cost the decision names out loud: the extension half really did
    catch .exe, and now does not."""
    h = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "uploads"))
    u = types.SimpleNamespace(
        file=io.BytesIO(b"MZ\x90\x00\x03 not really a PE but enough bytes"),
        filename="installer.exe",
    )

    meta = h.save_upload(u, client_ip="9.9.9.8", owner="tester")

    assert meta and meta.get("id")


def test_javascript_upload_is_saved(tmp_path):
    """The headline case: application/javascript was in the blocked MIME set."""
    h = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "uploads"))
    u = types.SimpleNamespace(
        file=io.BytesIO(b'(function () {\n  "use strict";\n  console.log("hi");\n})();\n'),
        filename="chat.js",
    )

    meta = h.save_upload(u, client_ip="9.9.9.7", owner="tester")

    assert meta and meta.get("id")


async def test_chat_image_upload_is_added_to_gallery(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'gallery.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    gallery_dir = tmp_path / "generated_images"

    monkeypatch.setattr(up, "SessionLocal", TestingSession)
    monkeypatch.setattr(up, "GENERATED_IMAGES_DIR", str(gallery_dir))

    h = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "uploads"))
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    result = await endpoint(_request(user="alice"), [_image_upload()])
    uploaded = result["files"][0]

    assert uploaded["gallery_id"]
    db = TestingSession()
    try:
        image = db.query(GalleryImage).filter(GalleryImage.id == uploaded["gallery_id"]).one()
        assert image.owner == "alice"
        assert image.model == "chat-upload"
        assert image.prompt == "photo.png"
        assert image.file_hash == uploaded["hash"]
        assert (gallery_dir / image.filename).exists()
    finally:
        db.close()


async def test_non_image_chat_upload_is_not_added_to_gallery(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'gallery.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(up, "SessionLocal", TestingSession)
    monkeypatch.setattr(up, "GENERATED_IMAGES_DIR", str(tmp_path / "generated_images"))

    h = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "uploads"))
    _router, _ = up.setup_upload_routes(h)
    endpoint = _endpoint(_router)

    result = await endpoint(_request(user="alice"), [types.SimpleNamespace(
        filename="notes.txt",
        file=io.BytesIO(b"plain text upload"),
    )])

    assert "gallery_id" not in result["files"][0]
    db = TestingSession()
    try:
        assert db.query(GalleryImage).count() == 0
    finally:
        db.close()
