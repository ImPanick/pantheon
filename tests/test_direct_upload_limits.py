# SPDX-License-Identifier: AGPL-3.0-or-later
import io
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

import ast

from src.upload_limits import (
    BYTE_LIMITS,
    format_byte_limit,
    read_upload_limited,
    resolve_byte_limit,
)

REPO = Path(__file__).resolve().parent.parent


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


def _source(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


async def test_read_upload_limited_accepts_exact_limit():
    assert await read_upload_limited(_upload("ok.bin", b"abcd"), 4, "Test upload") == b"abcd"


async def test_read_upload_limited_rejects_oversized_upload():
    with pytest.raises(HTTPException) as exc:
        await read_upload_limited(_upload("too-big.bin", b"abcde"), 4, "Test upload")

    assert exc.value.status_code == 413
    assert exc.value.detail == "Test upload exceeds 4 bytes limit"


def test_upload_limit_formatting_is_human_readable():
    assert format_byte_limit(25 * 1024 * 1024) == "25 MB"
    assert format_byte_limit(512 * 1024) == "512 KB"
    assert format_byte_limit(7) == "7 bytes"


def _bounded_read_limits(path: str) -> list:
    """Every `read_upload_limited(...)` in a route file, as its limit argument.

    `Law 20`. This was a file-wide substring search for
    `"read_upload_limited(file, STT_MAX_AUDIO_BYTES"` — which tests the file,
    not the code, and which `P12-03` broke by wrapping the argument onto the
    next line without changing a single thing the test was there to protect.
    Parsing resolves the scope first and then asserts inside it, so a limit
    passed from anywhere but `src.upload_limits` fails here however it is
    spelled or wrapped.
    """
    tree = ast.parse(_source(path))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "read_upload_limited" or len(node.args) < 2:
            continue
        out.append(node.args[1])
    return out


def _limit_key(arg) -> str:
    """The `BYTE_LIMITS` key an argument resolves to, or `""`."""
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) \
            and arg.func.id == "resolve_byte_limit" and arg.args \
            and isinstance(arg.args[0], ast.Constant):
        return str(arg.args[0].value)
    return ""


def test_direct_upload_routes_use_bounded_reads():
    """Every direct upload read is capped, and the cap comes from one module."""
    expectations = {
        "routes/stt_routes.py": {"stt_max_audio_bytes"},
        "routes/gallery/gallery_routes.py": {
            "gallery_upload_max_bytes", "gallery_transform_upload_max_bytes"},
        "routes/memory/memory_routes.py": {"memory_import_max_bytes"},
        "routes/calendar_routes.py": {"ics_max_bytes"},
        "routes/email_routes.py": {"email_compose_upload_max_bytes"},
    }
    for path, keys in expectations.items():
        args = _bounded_read_limits(path)
        assert args, f"{path} makes no bounded read at all"
        found = set()
        for arg in args:
            key = _limit_key(arg)
            assert key, (
                f"{path}: read_upload_limited at line {arg.lineno} is passed a "
                f"limit that does not come from src.upload_limits")
            assert key in BYTE_LIMITS, f"{path}: {key!r} is not a known byte cap"
            found.add(key)
        assert keys <= found, f"{path} lost a cap: expected {keys}, found {found}"


async def test_the_cap_a_route_asks_for_is_the_one_that_is_enforced(monkeypatch):
    """`Law 20` again, one level down: drive the pair the routes drive.

    A route naming a key wired to nothing would pass the parse above and cap
    nothing. This resolves a real key through the environment layer and hands
    the answer to `read_upload_limited`, which is exactly what every call site
    checked above does.
    """
    monkeypatch.setenv("PANTHEON_ICS_MAX_BYTES", "4")
    limit = resolve_byte_limit("ics_max_bytes")
    assert limit == 4
    with pytest.raises(HTTPException) as exc:
        await read_upload_limited(_upload("big.ics", b"abcde"), limit, "ICS file")
    assert exc.value.status_code == 413
    assert exc.value.detail == "ICS file exceeds 4 bytes limit"
