# SPDX-License-Identifier: AGPL-3.0-or-later
import io

import pytest
from fastapi import HTTPException, UploadFile

from src import chat_helpers
from src.upload_handler import UploadHandler
from src.upload_limits import (
    DEFAULT_CHAT_UPLOAD_MAX_BYTES,
    get_chat_upload_max_bytes,
    read_byte_limit_env,
)


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


def test_chat_upload_limit_defaults_to_10mb(monkeypatch):
    monkeypatch.delenv("PANTHEON_CHAT_UPLOAD_MAX_BYTES", raising=False)

    assert get_chat_upload_max_bytes() == DEFAULT_CHAT_UPLOAD_MAX_BYTES


def test_chat_upload_limit_uses_env_bytes(monkeypatch):
    monkeypatch.setenv("PANTHEON_CHAT_UPLOAD_MAX_BYTES", "12345")

    assert get_chat_upload_max_bytes() == 12345


def test_chat_upload_limit_rejects_invalid_env(monkeypatch):
    monkeypatch.setenv("PANTHEON_CHAT_UPLOAD_MAX_BYTES", "not-bytes")

    with pytest.raises(ValueError, match="PANTHEON_CHAT_UPLOAD_MAX_BYTES"):
        get_chat_upload_max_bytes()


def test_read_byte_limit_env_rejects_non_positive(monkeypatch):
    monkeypatch.setenv("PANTHEON_CHAT_UPLOAD_MAX_BYTES", "0")

    with pytest.raises(ValueError, match="greater than 0"):
        read_byte_limit_env("PANTHEON_CHAT_UPLOAD_MAX_BYTES", 10)


def test_validate_file_upload_is_deleted():
    """P2-04: `src.chat_helpers.validate_file_upload` was dead code, deleted.

    It advertised a 19-extension allowlist and an UNSUPPORTED_FILE_TYPE error
    shape that no route ever reached — the live chat upload path is
    UploadHandler.save_upload. Its only two references outside its own def were
    an import and a call in this file, so the test below it was the only thing
    keeping it alive.

    The env-var coverage that call provided is not lost: the FILE_TOO_LARGE
    branch of the *live* path is pinned by the next test, with the same 4-byte
    limit and the same message. Pinned as an absence so a later agent restoring
    the helper has to notice it enforces nothing first.
    """
    assert not hasattr(chat_helpers, "validate_file_upload")


def test_upload_handler_uses_configured_chat_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("PANTHEON_CHAT_UPLOAD_MAX_BYTES", "4")
    handler = UploadHandler(base_dir=str(tmp_path), upload_dir=str(tmp_path / "uploads"))

    with pytest.raises(HTTPException) as exc:
        handler.save_upload(_upload("too-large.txt", b"abcde"), client_ip="127.0.0.1")

    assert exc.value.status_code == 400
    assert exc.value.detail == "File size exceeds 4 bytes limit"
