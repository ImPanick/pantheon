# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio

from routes import emoji_routes


def _emoji_endpoint():
    router = emoji_routes.setup_emoji_routes()
    for route in router.routes:
        if route.path == "/api/emoji/{code}.svg" and "GET" in route.methods:
            return route.endpoint
    raise AssertionError("emoji route not found")


def test_svg_safety_rejects_active_or_external_svg_content():
    assert emoji_routes._is_safe_svg(
        b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
    )

    assert not emoji_routes._is_safe_svg(b'<svg><script>alert(1)</script></svg>')
    assert not emoji_routes._is_safe_svg(b'<svg onload="alert(1)"></svg>')
    assert not emoji_routes._is_safe_svg(b'<svg><image href="https://example.com/x.png"/></svg>')
    assert not emoji_routes._is_safe_svg(b"<svg>" + b"a" * (emoji_routes._MAX_SVG_BYTES + 1))


def test_a_vendored_glyph_is_served_with_the_security_headers(monkeypatch):
    """Was `test_cached_svg_served_with_security_headers`, against the disk cache
    the CDN fetch filled. `P16-06` replaced that with a vendored library, so the
    source changed — the property did not, and it is the property that matters:
    an SVG leaving this route carries every header that keeps it inert.
    """
    monkeypatch.setattr(emoji_routes, "_GLYPHS", {"1f600": '<path d="M0 0"/>'})

    response = asyncio.run(_emoji_endpoint()("1f600"))

    assert b'<path d="M0 0"/>' in response.body
    assert response.body.startswith(b"<svg")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"


def test_an_active_svg_returns_blank_even_from_the_vendored_set(monkeypatch):
    """The eviction half of the old test is gone with the cache it evicted from.
    The half worth keeping is that unsafe content never reaches the browser —
    and it is checked on the *trusted* path too, because a guard that only runs
    where you expect trouble is one you have already argued yourself out of.
    """
    monkeypatch.setattr(emoji_routes, "_GLYPHS", {"1f600": '<script>alert(1)</script>'})

    response = asyncio.run(_emoji_endpoint()("1f600"))

    assert response.body == emoji_routes._BLANK_SVG
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"


def test_an_unknown_codepoint_is_blank_not_an_error(monkeypatch):
    monkeypatch.setattr(emoji_routes, "_GLYPHS", {})
    response = asyncio.run(_emoji_endpoint()("1f600"))
    assert response.body == emoji_routes._BLANK_SVG


def test_a_malformed_code_never_reaches_the_library(monkeypatch):
    """The codepoint regex is the first gate; keep it that way."""
    monkeypatch.setattr(emoji_routes, "_GLYPHS", {"../../etc/passwd": "<path/>"})
    for bad in ("../../etc/passwd", "1f600;rm", "ZZZZ", ""):
        response = asyncio.run(_emoji_endpoint()(bad))
        assert response.body == emoji_routes._BLANK_SVG, bad
