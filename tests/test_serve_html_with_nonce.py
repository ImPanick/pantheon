# SPDX-License-Identifier: AGPL-3.0-or-later
"""Behavior tests for src.app_helpers.serve_html_with_nonce.

Every caller of this helper serves a fixed, app-bundled template
(index/login), never a client-supplied path. So a read failure — a missing
file (broken deployment) or a permission/IO error — is a server fault, not a
client "not found", and must surface as a logged 500 rather than hiding behind
a 404 where 5xx alerting can't see it. These tests lock that intent (raised in
the PR #4637 review). `GET /backgrounds` is the case where 404 *is* right — an
optional sandbox page this build does not ship — and `B140` put that branch at
the call site in `app.py`, which is what the docstring asks a caller to do
rather than defaulting this shared helper to 404.

**`B141`/`B121` added the second half of this file.** The helper used to
substitute a per-request CSP nonce into the page and return it with no
validator; it now authorises the page's inline blocks with `'sha256-…'`
computed from the file and gives the response an ETag, a Last-Modified and
`Cache-Control: no-cache`, so a conditional request for an unchanged template
is a `304`. The nonce path is **kept**, not replaced (`Law 1`): a template that
still carries `{{CSP_NONCE}}` is still substituted — and, because its body then
varies per request, still correctly gets no validator.
"""
import os
import types

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette.responses")
from fastapi import HTTPException
from starlette.datastructures import Headers

from src.app_helpers import inline_script_hashes, serve_html_with_nonce


def _request_with_nonce(nonce: str = "", **headers):
    """Minimal stand-in for a Starlette Request: request.state and .headers."""
    return types.SimpleNamespace(
        state=types.SimpleNamespace(csp_nonce=nonce),
        headers=Headers(headers or {}),
    )


def test_missing_fixed_template_returns_500_not_404(tmp_path):
    missing = tmp_path / "does_not_exist.html"
    with pytest.raises(HTTPException) as exc_info:
        serve_html_with_nonce(_request_with_nonce(), str(missing))
    assert exc_info.value.status_code == 500
    # Generic detail — no OS error string or absolute path leaked to the client.
    assert exc_info.value.detail == "Internal server error"


def test_unreadable_template_returns_500(tmp_path):
    # A directory at the path makes open() raise an OSError subtype
    # (IsADirectoryError on POSIX, PermissionError on Windows) — same branch.
    a_dir = tmp_path / "a_dir.html"
    a_dir.mkdir()
    with pytest.raises(HTTPException) as exc_info:
        serve_html_with_nonce(_request_with_nonce(), str(a_dir))
    assert exc_info.value.status_code == 500


def test_readable_template_injects_nonce(tmp_path):
    page = tmp_path / "page.html"
    page.write_text('<script nonce="{{CSP_NONCE}}">x</script>', encoding="utf-8")
    req = _request_with_nonce("nonce-abc")
    resp = serve_html_with_nonce(req, str(page))
    assert resp.status_code == 200
    body = resp.body.decode("utf-8")
    assert "nonce-abc" in body
    assert "{{CSP_NONCE}}" not in body
    # `Law 1`: the nonce mechanism is intact, and the middleware is told to put
    # a `'nonce-…'` source in `script-src` for exactly this response.
    assert req.state.csp_nonce_used is True


# ── `B121`: a page that does not vary can carry a validator ──────────────────


def test_a_page_with_no_placeholder_carries_a_validator(tmp_path):
    """The whole of `B121`. `/` was the one precached URL of 213 that answered
    an unchanged `CACHE_NAME` bump with a full body, because the nonce made the
    response un-describable."""
    page = tmp_path / "page.html"
    page.write_text("<html><body>hi</body></html>", encoding="utf-8")
    resp = serve_html_with_nonce(_request_with_nonce(), str(page))
    assert resp.status_code == 200
    assert resp.headers["etag"]
    assert resp.headers["last-modified"]
    # The directive `_RevalidatingStatic` (app.py) stamps on every .html it
    # serves. Without it this response had heuristic freshness and a browser
    # could paint a stale shell for days without asking.
    assert resp.headers["cache-control"] == "no-cache"


def test_the_validator_is_derived_from_the_bytes_not_the_clock(tmp_path):
    """`FileResponse` derives an ETag from `mtime`+`size`; this one is a hash
    of the served body. Two checkouts of the same commit, a redeploy that
    rewrites mtimes, or two replicas behind a load balancer then agree — and a
    real edit that happens to preserve the size still changes it."""
    page = tmp_path / "page.html"
    page.write_text("<html>a</html>", encoding="utf-8")
    first = serve_html_with_nonce(_request_with_nonce(), str(page)).headers["etag"]

    same_bytes = tmp_path / "copy.html"
    same_bytes.write_text("<html>a</html>", encoding="utf-8")
    # Same bytes, deliberately a different mtime — which is the input
    # `FileResponse.set_stat_headers` would have hashed instead.
    os.utime(same_bytes, (0, 0))
    assert same_bytes.stat().st_mtime_ns != page.stat().st_mtime_ns
    assert serve_html_with_nonce(_request_with_nonce(), str(same_bytes)).headers["etag"] == first

    page.write_text("<html>b</html>", encoding="utf-8")
    assert serve_html_with_nonce(_request_with_nonce(), str(page)).headers["etag"] != first


def test_a_conditional_request_for_an_unchanged_page_is_a_304(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<html><body>hi</body></html>", encoding="utf-8")
    etag = serve_html_with_nonce(_request_with_nonce(), str(page)).headers["etag"]

    resp = serve_html_with_nonce(
        _request_with_nonce(**{"if-none-match": etag}), str(page))
    assert resp.status_code == 304
    assert resp.body == b""
    # The ETag rides along on the 304 so the stored copy keeps its validator.
    assert resp.headers["etag"] == etag

    stale = serve_html_with_nonce(
        _request_with_nonce(**{"if-none-match": '"nope"'}), str(page))
    assert stale.status_code == 200
    assert stale.body


def test_a_page_that_still_uses_the_nonce_gets_no_validator(tmp_path):
    """The failure `B121` refused to ship. An ETag over a body that varies is
    not useless, it is wrong: RFC 9111 §4.3.4 updates the stored response's
    headers from the `304`, so the client ends up holding the stored HTML with
    nonce A under a policy naming nonce B and every inline script blocked."""
    page = tmp_path / "page.html"
    page.write_text('<script nonce="{{CSP_NONCE}}">x</script>', encoding="utf-8")
    resp = serve_html_with_nonce(_request_with_nonce("abc"), str(page))
    assert resp.status_code == 200
    assert "etag" not in resp.headers
    assert "last-modified" not in resp.headers


def test_an_edited_template_is_re_read_without_a_restart(tmp_path):
    """The parse is cached per file version because the shell is 285 KB and
    this is on the hot path for every navigation. Keying the cache on the
    file's identity and mtime is what stops that becoming a server that serves
    yesterday's page — the property `_RevalidatingStatic` gives the browser,
    kept on the server side of the same file."""
    page = tmp_path / "page.html"
    page.write_text("<html>a</html>", encoding="utf-8")
    first = serve_html_with_nonce(_request_with_nonce(), str(page))
    page.write_text("<html>bb</html>", encoding="utf-8")
    second = serve_html_with_nonce(_request_with_nonce(), str(page))
    assert second.body == b"<html>bb</html>"
    assert second.headers["etag"] != first.headers["etag"]


# ── `B141`: what gets a hash, read the way a browser reads it ────────────────


def test_the_hash_is_over_the_script_text_and_authorises_only_that():
    """The browser's rule: base64 of the SHA-256 of the block's source text."""
    import base64
    import hashlib

    body = "\n  console.log(1);\n"
    want = "'sha256-" + base64.b64encode(
        hashlib.sha256(body.encode()).digest()).decode() + "'"
    assert inline_script_hashes(f"<script>{body}</script>") == (want,)
    # One byte different is a different source. This is the property a nonce
    # does not have: a nonce authorises whatever sits inside a tag carrying it.
    assert inline_script_hashes(f"<script>{body} </script>") != (want,)


def test_a_script_tag_inside_an_html_comment_is_not_a_block():
    """`static/index.html:313` carries the string `<script` inside a comment.
    A regex counts eight inline blocks in that file and the browser executes
    seven, and a hash list one entry long in the wrong direction is a page that
    does not run — so the reading is done by a parser that knows comment
    state."""
    html = "<!-- <script>evil()</script> --><script>real()</script>"
    assert inline_script_hashes(html) == inline_script_hashes("<script>real()</script>")


def test_an_external_script_gets_no_hash():
    """`<script src>` is authorised by `'self'` and has no inline source. A
    hash for its (empty) body would be a source in the policy authorising the
    empty script, which is not a thing this page ships."""
    assert inline_script_hashes('<script src="/static/js/app.js"></script>') == ()
    assert inline_script_hashes(
        '<script type="module" src="/static/js/app.js"></script>') == ()


def test_a_module_script_gets_a_hash_and_a_data_block_does_not():
    """`login.html`'s third block is `type="module"` and executes. A
    `type="application/json"` block is inert markup the parser hands to script,
    never to the JS engine — hashing it would put a source in the policy that
    authorises text nobody executes."""
    assert len(inline_script_hashes('<script type="module">import "./a.js";</script>')) == 1
    assert inline_script_hashes('<script type="application/json">{"a":1}</script>') == ()
    assert inline_script_hashes('<script type="text/template"><b></b></script>') == ()


def test_line_endings_are_normalised_the_way_the_parser_normalises_them():
    """HTML's input-stream preprocessing turns CRLF and a lone CR into LF
    before the parser sees them, so on a CRLF checkout the bytes on disk and
    the bytes the browser hashes are different documents — and every inline
    block on the page is blocked."""
    assert inline_script_hashes("<script>a\r\nb</script>") == \
        inline_script_hashes("<script>a\nb</script>")
    assert inline_script_hashes("<script>a\rb</script>") == \
        inline_script_hashes("<script>a\nb</script>")


def test_two_identical_blocks_are_one_source():
    assert len(inline_script_hashes("<script>x()</script><script>x()</script>")) == 1


def test_the_served_page_hands_its_hashes_to_the_middleware(tmp_path):
    """How the policy reaches the response. `SecurityHeadersMiddleware` reads
    these off `request.state` after `call_next` — which is what keeps it from
    holding a second list of which route serves which template (`Law 14`)."""
    page = tmp_path / "page.html"
    page.write_text("<script>hello()</script>", encoding="utf-8")
    req = _request_with_nonce()
    serve_html_with_nonce(req, str(page))
    assert req.state.csp_script_hashes == inline_script_hashes("<script>hello()</script>")
    assert getattr(req.state, "csp_nonce_used", False) is False
