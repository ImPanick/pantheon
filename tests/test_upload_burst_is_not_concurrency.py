# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P12-06` — the upload gate is a burst limit, and now it says so and is settable.

Two defects, both measured in the source before this file was written:

  * **`3` was a hardcoded constant** — `src/upload_handler.py`, `self.
    max_concurrent_uploads = 3`. `src/config.py` declares the same name with
    the same default and **nothing reads it**, which is the second copy
    `P12-05b` already found for `upload_rate_limit` (60 in the handler, 5 in
    the config class).
  * **"concurrent" was a ten-second window.** `count_recent_uploads` counts
    entries in `upload_rate_log`, which `save_upload` appends to when a file is
    *accepted* and never decrements when one finishes. Nothing in the gate
    knows how many uploads are in flight; it knows how many *completed* in the
    last ten seconds. That is a rate limit, and the 429 it raised said
    "Maximum concurrent uploads (3) exceeded" — a sentence that sends an
    operator looking for three simultaneous uploads that do not exist
    (`Law 10`).

The row let either fix stand. **It is renamed rather than reimplemented**, and
the argument is on the row: turning a 3-per-10s burst limit into a 3-in-flight
concurrency limit would silently *relax* a live control on the path that
already produced issue #1346, and nobody asked for that.

Every test below drives the real route or the real handler (`Law 20`).
"""

import json
import types

import pytest
from fastapi import HTTPException

import routes.upload_routes as up
import src.limit_policy as lp
import src.settings as settings
from src.upload_handler import UploadHandler, count_recent_uploads
from src.upload_limits import (
    DEFAULT_UPLOAD_BURST_LIMIT,
    DEFAULT_UPLOAD_BURST_WINDOW_SECONDS,
)

_NOW = 5_000.0


@pytest.fixture(autouse=True)
def _freeze_time_and_clear_roles(monkeypatch):
    monkeypatch.setattr(up.time, "time", lambda: _NOW)
    lp.clear_role_limit_provider()
    yield
    lp.clear_role_limit_provider()


@pytest.fixture
def stored(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_FILE", str(path))

    def write(**values):
        path.write_text(json.dumps(values), encoding="utf-8")
        monkeypatch.setattr(settings, "_settings_cache", None)

    write()
    return write


def _handler():
    """The same stand-in the #1346 regression tests use, plus the new names."""
    h = types.SimpleNamespace()
    h.upload_rate_log = {}
    h.upload_burst_limit = DEFAULT_UPLOAD_BURST_LIMIT
    h.upload_burst_window_seconds = DEFAULT_UPLOAD_BURST_WINDOW_SECONDS

    def save_upload(u, client_ip, owner=None):
        h.upload_rate_log.setdefault(client_ip, []).append(_NOW)
        return {
            "id": "0" * 32 + ".txt", "name": getattr(u, "filename", "f"),
            "mime": "text/plain", "size": 1, "hash": "h",
            "uploaded_at": "now", "width": None, "height": None,
            "is_duplicate": False,
        }

    h.save_upload = save_upload
    return h


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


def _drive(handler, files=1, recent=()):
    handler.upload_rate_log["1.2.3.4"] = list(recent)
    router, _ = up.setup_upload_routes(handler)
    return _endpoint(router)(_request(), _files(files))


# ── the number is no longer a constant ───────────────────────────────────────


async def test_an_operator_setting_lowers_the_burst_limit(stored):
    """Three recent uploads pass at the shipped 3; a stored 2 rejects them."""
    assert (await _drive(_handler(), recent=[_NOW - 1, _NOW - 2]))["files"]

    stored(upload_burst_limit=2)
    with pytest.raises(HTTPException) as ei:
        await _drive(_handler(), recent=[_NOW - 1, _NOW - 2])
    assert ei.value.status_code == 429


async def test_an_operator_setting_raises_the_burst_limit(stored):
    """The gate fires at the shipped 3, and a stored 5 lets the same batch in.

    This is the row's actual complaint: before it, the only way past `3` was a
    rebuild.
    """
    recent = [_NOW - 1, _NOW - 2, _NOW - 3]
    with pytest.raises(HTTPException):
        await _drive(_handler(), recent=recent)

    stored(upload_burst_limit=5)
    assert (await _drive(_handler(), recent=recent))["files"]


async def test_the_limit_changes_without_a_restart(stored):
    """`P12-03`'s property, held here: the value is resolved per request.

    The handler is built once and the router once; only the settings file
    moves between the two calls.
    """
    handler = _handler()
    router, _ = up.setup_upload_routes(handler)
    endpoint = _endpoint(router)
    handler.upload_rate_log["1.2.3.4"] = [_NOW - 1, _NOW - 2]

    assert (await endpoint(_request(), _files(1)))["files"]

    stored(upload_burst_limit=1)
    with pytest.raises(HTTPException) as ei:
        await endpoint(_request(), _files(1))
    assert ei.value.status_code == 429


async def test_a_role_profile_can_set_it_per_person(stored):
    """`P11-02`'s seam, exercised. No role system registers a provider today —
    the row says so — but the layer the roles will arrive through is wired and
    the route reads it."""
    stored(upload_burst_limit=9)
    lp.set_role_limit_provider(
        lambda key, owner: 1 if (key, owner) == ("upload_burst_limit", "tester") else None
    )
    with pytest.raises(HTTPException) as ei:
        await _drive(_handler(), recent=[_NOW - 1])
    assert ei.value.status_code == 429


# ── the window is the thing that was misnamed ────────────────────────────────


async def test_the_window_is_a_setting_and_not_a_literal_ten(stored):
    """Three uploads five seconds ago trip the shipped ten-second window.

    Narrow the window to two seconds and the same three are outside it — which
    is only expressible because the window is now a named, settable number
    instead of a default argument nobody could reach.
    """
    recent = [_NOW - 5, _NOW - 5.5, _NOW - 6]
    with pytest.raises(HTTPException):
        await _drive(_handler(), recent=recent)

    stored(upload_burst_window_seconds=2)
    assert (await _drive(_handler(), recent=recent))["files"]


async def test_the_rejection_names_the_window_instead_of_claiming_concurrency(stored):
    """`Law 10`. The old sentence was "Maximum concurrent uploads (3)
    exceeded", and there were never three uploads in flight."""
    with pytest.raises(HTTPException) as ei:
        await _drive(_handler(), recent=[_NOW - 1, _NOW - 2, _NOW - 3])
    detail = str(ei.value.detail)
    assert "concurrent" not in detail.lower(), detail
    assert "3" in detail and "10" in detail, detail


def test_the_gate_counts_finished_uploads_and_not_uploads_in_flight(tmp_path):
    """The measurement behind the rename, driven rather than argued.

    A real upload is run to completion. Its timestamp is still in
    `upload_rate_log` afterwards, because nothing removes one when an upload
    finishes — so the number the gate reads cannot be a count of work in
    progress, whatever it is called. Three finished uploads inside the window
    therefore trip a limit of three, and that is a burst limit.
    """
    import io

    handler = UploadHandler(
        base_dir=str(tmp_path), upload_dir=str(tmp_path / "uploads")
    )
    upload = types.SimpleNamespace(
        file=io.BytesIO(b"finished before this line"), filename="done.txt"
    )
    meta = handler.save_upload(upload, client_ip="9.9.9.7", owner="tester")

    assert meta and meta.get("id"), "the upload completed"
    assert len(handler.upload_rate_log["9.9.9.7"]) == 1, (
        "a finished upload is still counted, so this is not a concurrency gauge"
    )
    assert count_recent_uploads(
        handler.upload_rate_log["9.9.9.7"], handler.upload_rate_log["9.9.9.7"][0]
    ) == 1


# ── `Law 1`: the old name still works ────────────────────────────────────────


def test_the_old_attribute_name_still_reads_the_same_number():
    handler = UploadHandler.__new__(UploadHandler)
    UploadHandler.__init__(
        handler, base_dir="/tmp", upload_dir="/tmp/_pantheon_burst_test_uploads"
    )
    assert handler.max_concurrent_uploads == handler.upload_burst_limit
    assert handler.upload_burst_limit == DEFAULT_UPLOAD_BURST_LIMIT


def test_writing_the_old_attribute_name_still_moves_the_limit():
    """Three test files and any downstream install set this attribute. It is an
    alias for one value, not a second copy of it (`Law 7`)."""
    handler = UploadHandler.__new__(UploadHandler)
    UploadHandler.__init__(
        handler, base_dir="/tmp", upload_dir="/tmp/_pantheon_burst_test_uploads"
    )
    handler.max_concurrent_uploads = 12
    assert handler.upload_burst_limit == 12
    handler.upload_burst_limit = 4
    assert handler.max_concurrent_uploads == 4


async def test_a_handler_that_only_knows_the_old_name_still_gates(stored):
    """The stand-in in `tests/test_upload_multifile.py` is exactly this shape."""
    legacy = types.SimpleNamespace()
    legacy.upload_rate_log = {"1.2.3.4": [_NOW - 1, _NOW - 2, _NOW - 3]}
    legacy.max_concurrent_uploads = 3
    legacy.save_upload = lambda u, client_ip, owner=None: {}
    router, _ = up.setup_upload_routes(legacy)
    with pytest.raises(HTTPException) as ei:
        await _endpoint(router)(_request(), _files(1))
    assert ei.value.status_code == 429
