# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import builtins
import json
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _AuthManager:
    is_configured = True

    def __init__(self, admins=()):
        self._admins = set(admins)

    def is_admin(self, user):
        return user in self._admins


class _Request:
    def __init__(self, user=None, auth_manager=None, body=None):
        self.state = SimpleNamespace(current_user=user)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=auth_manager))
        self.client = SimpleNamespace(host="127.0.0.1")
        self._body = body

    async def json(self):
        return self._body


def _upload_endpoints(upload_handler, monkeypatch):
    import fastapi.dependencies.utils as dependency_utils
    from routes.upload_routes import setup_upload_routes

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed", lambda: None)
    # B53: the router is built inside `setup_upload_routes` now, so it carries
    # this call's routes and nothing else. This used to read
    # `before = len(router.routes)` and slice off the tail — a workaround for a
    # module-level router that accumulated a fresh copy of every route on each
    # call, and the clearest evidence anyone had noticed.
    router, _cleanup = setup_upload_routes(upload_handler)
    return {route.endpoint.__name__: route.endpoint for route in router.routes}


def _make_upload_store(tmp_path, monkeypatch):
    from src.upload_handler import UploadHandler
    from src import constants

    upload_dir = tmp_path / "uploads"
    dated = upload_dir / "2026" / "06" / "02"
    dated.mkdir(parents=True)

    alice_id = "a" * 32 + ".png"
    bob_id = "b" * 32 + ".png"
    alice_path = dated / alice_id
    bob_path = dated / bob_id
    alice_path.write_bytes(b"alice image bytes")
    bob_path.write_bytes(b"bob image bytes")

    index = {
        "alice:h1": {
            "id": alice_id,
            "path": str(alice_path),
            "mime": "image/png",
            "size": alice_path.stat().st_size,
            "name": "alice.png",
            "original_name": "alice.png",
            "owner": "alice",
        },
        "bob:h2": {
            "id": bob_id,
            "path": str(bob_path),
            "mime": "image/png",
            "size": bob_path.stat().st_size,
            "name": "bob.png",
            "original_name": "bob.png",
            "owner": "bob",
        },
    }
    (upload_dir / "uploads.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(constants, "UPLOAD_DIR", str(upload_dir))
    return UploadHandler(str(tmp_path), str(upload_dir)), alice_id, bob_id, upload_dir


def _guard_cache_open(monkeypatch, cache_path, blocked_modes):
    original_open = builtins.open

    def guarded_open(path, mode="r", *args, **kwargs):
        if str(path) == str(cache_path) and any(flag in mode for flag in blocked_modes):
            raise AssertionError(f"owner gate should run before opening {cache_path}")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)


def _add_upload_row(upload_dir, row):
    db_path = upload_dir / "uploads.json"
    index = json.loads(db_path.read_text(encoding="utf-8"))
    index[f"{row.get('owner')}:{row['id']}"] = row
    db_path.write_text(json.dumps(index), encoding="utf-8")


def _add_upload_symlink(upload_dir, file_id, target_path, owner="alice"):
    dated = upload_dir / "2026" / "06" / "02"
    link_path = dated / file_id
    try:
        os.symlink(target_path, link_path)
    except (AttributeError, NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    _add_upload_row(
        upload_dir,
        {
            "id": file_id,
            "path": str(link_path),
            "mime": "image/png",
            "size": target_path.stat().st_size,
            "name": "escape.png",
            "original_name": "escape.png",
            "owner": owner,
        },
    )
    return link_path


def test_download_file_denies_anonymous_when_auth_is_configured(tmp_path, monkeypatch):
    handler, alice_id, _bob_id, _upload_dir = _make_upload_store(tmp_path, monkeypatch)
    download_file = _upload_endpoints(handler, monkeypatch)["download_file"]

    with pytest.raises(HTTPException) as exc:
        asyncio.run(download_file(_Request(auth_manager=_AuthManager()), alice_id))

    assert exc.value.status_code == 403


def test_download_file_denies_cross_owner_without_leaking_file(tmp_path, monkeypatch):
    handler, _alice_id, bob_id, _upload_dir = _make_upload_store(tmp_path, monkeypatch)
    download_file = _upload_endpoints(handler, monkeypatch)["download_file"]

    with pytest.raises(HTTPException) as exc:
        asyncio.run(download_file(_Request(user="alice", auth_manager=_AuthManager()), bob_id))

    assert exc.value.status_code == 404


def test_download_file_allows_same_owner(tmp_path, monkeypatch):
    handler, alice_id, _bob_id, _upload_dir = _make_upload_store(tmp_path, monkeypatch)
    download_file = _upload_endpoints(handler, monkeypatch)["download_file"]

    response = asyncio.run(
        download_file(_Request(user="alice", auth_manager=_AuthManager()), alice_id)
    )

    assert response.path.endswith(alice_id)
    assert response.media_type == "image/png"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_download_file_allows_admin_to_read_other_owner_upload(tmp_path, monkeypatch):
    handler, _alice_id, bob_id, _upload_dir = _make_upload_store(tmp_path, monkeypatch)
    download_file = _upload_endpoints(handler, monkeypatch)["download_file"]

    response = asyncio.run(
        download_file(
            _Request(user="admin", auth_manager=_AuthManager(admins={"admin"})),
            bob_id,
        )
    )

    assert response.path.endswith(bob_id)
    assert response.media_type == "image/png"


def test_download_file_rejects_upload_symlink_escape(tmp_path, monkeypatch):
    handler, _alice_id, _bob_id, upload_dir = _make_upload_store(tmp_path, monkeypatch)
    download_file = _upload_endpoints(handler, monkeypatch)["download_file"]
    escape_id = "c" * 32 + ".png"
    outside = tmp_path / "outside-upload-root.png"
    outside.write_bytes(b"outside upload root")
    _add_upload_symlink(upload_dir, escape_id, outside)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            download_file(
                _Request(user="alice", auth_manager=_AuthManager()),
                escape_id,
            )
        )

    assert exc.value.status_code == 403


def test_download_file_keeps_owner_gate_before_path_resolution(tmp_path, monkeypatch):
    handler, _alice_id, _bob_id, upload_dir = _make_upload_store(tmp_path, monkeypatch)
    download_file = _upload_endpoints(handler, monkeypatch)["download_file"]
    bob_escape_id = "d" * 32 + ".png"
    outside = tmp_path / "bob-outside-upload-root.png"
    outside.write_bytes(b"bob outside upload root")
    _add_upload_symlink(upload_dir, bob_escape_id, outside, owner="bob")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            download_file(
                _Request(user="alice", auth_manager=_AuthManager()),
                bob_escape_id,
            )
        )

    assert exc.value.status_code == 404


def test_get_vision_text_denies_cross_owner_before_cache_read(tmp_path, monkeypatch):
    handler, _alice_id, bob_id, upload_dir = _make_upload_store(tmp_path, monkeypatch)
    get_vision_text = _upload_endpoints(handler, monkeypatch)["get_vision_text"]
    cache_dir = upload_dir / ".vision"
    cache_dir.mkdir()
    cache_path = cache_dir / f"{bob_id}.txt"
    cache_path.write_text("bob private cached text", encoding="utf-8")
    _guard_cache_open(monkeypatch, cache_path, blocked_modes=("r",))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            get_vision_text(
                _Request(user="alice", auth_manager=_AuthManager()),
                bob_id,
            )
        )

    assert exc.value.status_code == 404


def test_get_vision_text_denies_cross_owner_before_image_analysis(tmp_path, monkeypatch):
    handler, _alice_id, bob_id, _upload_dir = _make_upload_store(tmp_path, monkeypatch)
    get_vision_text = _upload_endpoints(handler, monkeypatch)["get_vision_text"]

    def fail_analysis(_path):
        raise AssertionError("owner gate should run before image analysis")

    monkeypatch.setattr("src.document_processor.analyze_image_with_vl", fail_analysis)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            get_vision_text(
                _Request(user="alice", auth_manager=_AuthManager()),
                bob_id,
                force=1,
            )
        )

    assert exc.value.status_code == 404


def test_get_vision_text_rejects_upload_symlink_escape_before_analysis(tmp_path, monkeypatch):
    handler, _alice_id, _bob_id, upload_dir = _make_upload_store(tmp_path, monkeypatch)
    get_vision_text = _upload_endpoints(handler, monkeypatch)["get_vision_text"]
    escape_id = "e" * 32 + ".png"
    outside = tmp_path / "vision-outside-upload-root.png"
    outside.write_bytes(b"outside upload root")
    _add_upload_symlink(upload_dir, escape_id, outside)

    def fail_analysis(_path):
        raise AssertionError("upload root gate should run before image analysis")

    monkeypatch.setattr("src.document_processor.analyze_image_with_vl", fail_analysis)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            get_vision_text(
                _Request(user="alice", auth_manager=_AuthManager()),
                escape_id,
                force=1,
            )
        )

    assert exc.value.status_code == 403


def test_put_vision_text_denies_cross_owner_before_cache_write(tmp_path, monkeypatch):
    handler, _alice_id, bob_id, upload_dir = _make_upload_store(tmp_path, monkeypatch)
    put_vision_text = _upload_endpoints(handler, monkeypatch)["put_vision_text"]
    cache_path = upload_dir / ".vision" / f"{bob_id}.txt"
    _guard_cache_open(monkeypatch, cache_path, blocked_modes=("w", "a", "+"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            put_vision_text(
                _Request(
                    user="alice",
                    auth_manager=_AuthManager(),
                    body={"text": "edited text"},
                ),
                bob_id,
            )
        )

    assert exc.value.status_code == 404
    assert not cache_path.exists()


def test_put_vision_text_allows_same_owner_to_write_cache(tmp_path, monkeypatch):
    handler, alice_id, _bob_id, upload_dir = _make_upload_store(tmp_path, monkeypatch)
    put_vision_text = _upload_endpoints(handler, monkeypatch)["put_vision_text"]

    response = asyncio.run(
        put_vision_text(
            _Request(
                user="alice",
                auth_manager=_AuthManager(),
                body={"text": "edited alice text"},
            ),
            alice_id,
        )
    )

    assert response == {"ok": True}
    assert (upload_dir / ".vision" / f"{alice_id}.txt").read_text(
        encoding="utf-8"
    ) == "edited alice text"


def test_download_file_survives_corrupted_uploads_json(tmp_path, monkeypatch):
    # A truncated/corrupt uploads.json must not 500 the download endpoint —
    # metadata simply becomes unavailable and the file is still served.
    handler, alice_id, _bob_id, upload_dir = _make_upload_store(tmp_path, monkeypatch)
    download_file = _upload_endpoints(handler, monkeypatch)["download_file"]
    (upload_dir / "uploads.json").write_text('{"alice:h1": {', encoding="utf-8")

    # No auth configured -> owner gate skipped.
    response = asyncio.run(download_file(_Request(), alice_id))

    assert str(response.path).endswith(alice_id)
    # Metadata unreadable, so the display filename falls back to the file_id.
    assert response.filename == alice_id


def test_put_vision_text_returns_400_on_malformed_json(tmp_path, monkeypatch):
    # A non-JSON request body must yield 400, not an unhandled JSONDecodeError -> 500.
    handler, alice_id, _bob_id, _upload_dir = _make_upload_store(tmp_path, monkeypatch)
    put_vision_text = _upload_endpoints(handler, monkeypatch)["put_vision_text"]

    class _BadJsonRequest(_Request):
        async def json(self):
            raise json.JSONDecodeError("Expecting value", "not json", 0)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(put_vision_text(_BadJsonRequest(), alice_id))
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# `B1820`. A bearer token is not its owner's browser.
#
# Only an admin mints a token, so every token resolves to an admin
# (`auth_helpers.is_delegated_credential`), and the three owner gates above ask
# `is_admin(owner)`: a token of any scope, a `metrics:read` scrape token
# included, could read, re-caption and run vision on any upload whose id it
# held, and any token could upload. A token now needs an upload scope (`chat`,
# or `documents:read` to read and `documents:write` to write) and reaches only
# its owner's own files. Every cookie case above is unchanged. Ported from
# upstream Odysseus c74f4756's token half; its no-login half is not, because
# there is always authentication (`D-2026-10-07-02` §2).
# ---------------------------------------------------------------------------


class _TokenRequest(_Request):
    """What `app.py`'s auth middleware stamps on a matched bearer token. Its
    owner, bob, is an admin, as the owner of every token is."""

    def __init__(self, scopes, owner="bob", body=None):
        super().__init__(user="api", auth_manager=_AuthManager(admins={"bob"}), body=body)
        self.state.api_token = True
        self.state.api_token_owner = owner
        self.state.api_token_scopes = list(scopes)


def _a_text_file():
    import io

    from fastapi import UploadFile

    return [UploadFile(filename="notes.txt", file=io.BytesIO(b"plain words\n"))]


@pytest.fixture
def token_world(tmp_path, monkeypatch):
    handler, alice_id, bob_id, upload_dir = _make_upload_store(tmp_path, monkeypatch)
    ownerless_id = "f" * 32 + ".png"
    ownerless_path = upload_dir / "2026" / "06" / "02" / ownerless_id
    ownerless_path.write_bytes(b"nobody's image bytes")
    _add_upload_row(upload_dir, {
        "id": ownerless_id, "path": str(ownerless_path), "mime": "image/png",
        "size": ownerless_path.stat().st_size, "name": "old.png",
        "original_name": "old.png", "owner": None,
    })
    described = []

    def _vision(path, owner=None):
        described.append(path)
        return "described"

    monkeypatch.setattr("src.document_processor.analyze_image_with_vl", _vision)
    return SimpleNamespace(
        handler=handler, endpoints=_upload_endpoints(handler, monkeypatch),
        alice_id=alice_id, bob_id=bob_id, ownerless_id=ownerless_id,
        vision=upload_dir / ".vision", described=described,
    )


def test_a_chat_token_reaches_only_its_owners_uploads_though_its_owner_is_an_admin(token_world):
    w, endpoints = token_world, token_world.endpoints

    response = asyncio.run(endpoints["download_file"](_TokenRequest(["chat"]), w.bob_id))
    assert response.path.endswith(w.bob_id)

    # An admin's browser reads alice's file and a row nobody owns; the
    # admin's token reads neither, and writes neither's caption.
    for file_id in (w.alice_id, w.ownerless_id):
        for name, call in (
            ("download_file", lambda: endpoints["download_file"](_TokenRequest(["chat"]), file_id)),
            ("download_file_head", lambda: endpoints["download_file_head"](
                _TokenRequest(["chat"]), file_id)),
            ("get_vision_text", lambda: endpoints["get_vision_text"](
                _TokenRequest(["chat"]), file_id, force=1)),
            ("put_vision_text", lambda: endpoints["put_vision_text"](
                _TokenRequest(["chat"], body={"text": "rewritten"}), file_id)),
        ):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(call())
            assert exc.value.status_code == 404, (name, file_id)
    assert w.described == []
    assert not (w.vision / f"{w.alice_id}.txt").exists()


@pytest.mark.parametrize("scopes", [["metrics:read"], ["todos:read", "todos:write"],
                                    ["cookbook:read", "cookbook:launch"]])
def test_a_token_without_an_upload_scope_touches_no_upload_even_its_owners(token_world, scopes):
    w, endpoints = token_world, token_world.endpoints
    for name, call in (
        ("download_file", lambda: endpoints["download_file"](_TokenRequest(scopes), w.bob_id)),
        ("download_file_head", lambda: endpoints["download_file_head"](
            _TokenRequest(scopes), w.bob_id)),
        ("get_vision_text", lambda: endpoints["get_vision_text"](
            _TokenRequest(scopes), w.bob_id, force=1)),
        ("put_vision_text", lambda: endpoints["put_vision_text"](
            _TokenRequest(scopes, body={"text": "rewritten"}), w.bob_id)),
        ("api_upload", lambda: endpoints["api_upload"](
            _TokenRequest(scopes), files=_a_text_file(), session_id=None)),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(call())
        assert exc.value.status_code == 403, name
        assert "API token missing required scope" in exc.value.detail, name
    assert w.described == []
    assert not (w.vision / f"{w.bob_id}.txt").exists()
    assert len(w.handler._load_upload_index()) == 3   # nothing was saved


def test_documents_read_reads_its_owners_uploads_and_only_a_write_scope_changes_them(token_world):
    w, endpoints = token_world, token_world.endpoints
    reader = ["documents:read"]

    assert asyncio.run(endpoints["download_file"](_TokenRequest(reader), w.bob_id)).path.endswith(w.bob_id)
    assert asyncio.run(endpoints["get_vision_text"](_TokenRequest(reader), w.bob_id))["text"] == "described"
    for name, call in (
        ("put_vision_text", lambda: endpoints["put_vision_text"](
            _TokenRequest(reader, body={"text": "rewritten"}), w.bob_id)),
        ("api_upload", lambda: endpoints["api_upload"](
            _TokenRequest(reader), files=_a_text_file(), session_id=None)),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(call())
        assert exc.value.status_code == 403, name
    assert (w.vision / f"{w.bob_id}.txt").read_text(encoding="utf-8") == "described"

    for scopes, text in ((["documents:write"], "by an integration"), (["chat"], "by the phone")):
        assert asyncio.run(endpoints["put_vision_text"](
            _TokenRequest(scopes, body={"text": text}), w.bob_id)) == {"ok": True}
        assert (w.vision / f"{w.bob_id}.txt").read_text(encoding="utf-8") == text
        saved = asyncio.run(endpoints["api_upload"](
            _TokenRequest(scopes), files=_a_text_file(), session_id=None))
        assert len(saved["files"]) == 1, scopes


def test_a_token_with_no_owner_is_refused(token_world):
    w, endpoints = token_world, token_world.endpoints
    for name, call in (
        ("download_file", lambda: endpoints["download_file"](
            _TokenRequest(["chat"], owner=None), w.bob_id)),
        ("put_vision_text", lambda: endpoints["put_vision_text"](
            _TokenRequest(["chat"], owner=None, body={"text": "rewritten"}), w.bob_id)),
        ("api_upload", lambda: endpoints["api_upload"](
            _TokenRequest(["chat"], owner=None), files=_a_text_file(), session_id=None)),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(call())
        assert exc.value.status_code == 403, name
        assert exc.value.detail == "API token has no owner", name
