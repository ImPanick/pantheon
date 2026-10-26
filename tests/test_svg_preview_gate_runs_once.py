# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B403` — the SVG preview judges a file once, not on every paint.

`download_file`'s raster arm writes a JPEG into `.thumbs/` and serves it until
the source is newer; the SVG arm read the file and ran the whole gate on every
request. Measured when `B300` raised the preview cap to 8 MiB: 0.125 s for a
realistic 5 MiB export that passes, 0.545 s when the `B300` tokenizer re-judges
it, per request and per viewer — and a refusal carries `Cache-Control:
no-store`, so a refused file was re-scanned on **every** paint.

Driven (`Law 20`): the real `GET /api/upload/{id}?thumb=1` handler over real
files on disk (the `_serve` harness `B160`'s tests use), with the real gate
wrapped so its calls are counted.

`Verify:` a 5 MiB SVG previewed twice runs the gate once, and a refused SVG
previewed twice runs it once, with the refusal still `no-store` to the browser.
"""
import os
import time

import pytest

import routes.upload_routes as upload_routes
import src.svg_runtime as svg_runtime
from tests.test_svg_preview_explains_refusals import _serve


@pytest.fixture
def gate_calls(monkeypatch):
    real = svg_runtime.svg_refusal_reason
    calls = []

    def counted(content, *args, **kwargs):
        calls.append(len(content))
        return real(content, *args, **kwargs)

    monkeypatch.setattr(svg_runtime, "svg_refusal_reason", counted)
    return calls


def _big_drawing(mib: float) -> bytes:
    head = b'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400">'
    row = b'<rect x="1" y="2" width="3" height="4" fill="#123456" stroke="#abcdef"/>\n'
    body = row * int(mib * 1024 * 1024 / len(row))
    return head + body + b"</svg>"


def _headers(response) -> dict:
    return {k.lower(): v for k, v in response.headers.items()}


def _again(tmp_path, monkeypatch, path, body, thumb=1):
    """One more request for a file already on disk, through a fresh router —
    what a later paint of the chip, or a second viewer, asks. The file is not
    touched."""
    import asyncio

    import fastapi.dependencies.utils as dependency_utils
    from src.upload_handler import UploadHandler
    from tests.test_svg_preview_explains_refusals import _Request

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed", lambda: None)
    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    index = {"owner:hash": {"id": path.name, "path": str(path), "mime": "image/svg+xml",
                            "size": len(body), "name": "diagram.svg",
                            "original_name": "diagram.svg", "owner": "owner"}}
    monkeypatch.setattr(handler, "_load_upload_index", lambda: index)
    router, _ = upload_routes.setup_upload_routes(handler)
    endpoint = {r.endpoint.__name__: r.endpoint for r in router.routes}["download_file"]
    return asyncio.run(endpoint(_Request(), path.name, thumb=thumb))


def _preview_twice(tmp_path, monkeypatch, body: bytes):
    first, path = _serve(tmp_path, monkeypatch, body)
    return first, _again(tmp_path, monkeypatch, path, body), path


def test_a_5_mib_svg_previewed_twice_runs_the_gate_once(tmp_path, monkeypatch, gate_calls):
    body = _big_drawing(5)
    assert len(body) > 5 * 1024 * 1024 - 100
    first, second, _ = _preview_twice(tmp_path, monkeypatch, body)
    assert len(gate_calls) == 1, gate_calls
    for response in (first, second):
        assert response.body == body
        assert svg_runtime.SVG_REFUSAL_HEADER.lower() not in _headers(response)


def test_a_refused_svg_previewed_twice_runs_the_gate_once_and_stays_no_store(
        tmp_path, monkeypatch, gate_calls):
    body = b'<svg xmlns="http://www.w3.org/2000/svg"><script>fetch("/api/settings")</script></svg>'
    first, second, _ = _preview_twice(tmp_path, monkeypatch, body)
    assert len(gate_calls) == 1, gate_calls
    for response in (first, second):
        h = _headers(response)
        assert h["cache-control"] == "no-store", "the refusal must not be cached by the browser"
        assert h[svg_runtime.SVG_REFUSAL_HEADER.lower()] == "active-content"
        assert h[svg_runtime.SVG_REFUSAL_TEXT_HEADER.lower()]
        assert b"<script" not in response.body
    assert first.body == second.body


def test_a_rewritten_file_is_judged_again(tmp_path, monkeypatch, gate_calls):
    """The key is the file's version, not its id: new bytes, new verdict — a
    file that passed and is then rewritten with a handler is refused."""
    good = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>'
    first, path = _serve(tmp_path, monkeypatch, good)
    assert first.body == good
    bad = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect/></svg>'
    path.write_bytes(bad)
    later = time.time() + 5
    os.utime(path, (later, later))
    second = _again(tmp_path, monkeypatch, path, bad)
    assert len(gate_calls) == 2, gate_calls
    assert _headers(second)[svg_runtime.SVG_REFUSAL_HEADER.lower()] == "active-content"
    assert b"onload" not in second.body


def test_a_download_of_the_file_never_asks_the_gate(tmp_path, monkeypatch, gate_calls):
    """The person's own file back is served whole and unjudged (`B103`) —
    the cache changes nothing there."""
    body = b'<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>'
    response, _ = _serve(tmp_path, monkeypatch, body, thumb=0)
    assert gate_calls == []
    assert _headers(response)["content-disposition"].startswith("attachment")


def test_the_verdict_cache_is_bounded():
    key = ("/nowhere", 0, 0, 0)
    for i in range(upload_routes._SVG_VERDICT_MAX + 50):
        upload_routes._svg_remember_verdict(("/bound-probe", i, 0, 0), None)
    assert len(upload_routes._svg_verdicts) <= upload_routes._SVG_VERDICT_MAX
    assert upload_routes._svg_cached_verdict(key) == (False, None)


def test_a_pass_is_never_inherited_by_other_bytes(tmp_path, monkeypatch, gate_calls):
    """The hard case for a version key: the file rewritten in place with
    bytes of the same length and its timestamp put back — same path, inode,
    size and mtime. A pass is keyed on the bytes' digest, so the new bytes are
    judged, and refused."""
    good = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>'
    bad = b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()"><rect/></svg>'
    bad = bad[:-6] + b" " * (len(good) - len(bad)) + bad[-6:]
    assert len(bad) == len(good)
    first, path = _serve(tmp_path, monkeypatch, good)
    assert first.body == good
    st = os.stat(path)
    with open(path, "r+b") as fh:   # in place: the inode is kept
        fh.write(bad)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    after = os.stat(path)
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (st.st_ino, st.st_size, st.st_mtime_ns)
    second = _again(tmp_path, monkeypatch, path, bad)
    assert len(gate_calls) == 2, gate_calls
    assert _headers(second)[svg_runtime.SVG_REFUSAL_HEADER.lower()] == "active-content"
