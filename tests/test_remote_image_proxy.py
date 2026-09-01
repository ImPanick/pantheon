"""Content the reader did not write must not make their browser call a stranger.

`img-src` allowed any `https:` host, so an `![](…)` in model output, a RAG
document or an **email** made the reader's browser fetch from a host nobody
chose — announcing their IP, their user-agent, and the moment they opened it.
That is what a tracking pixel is, and mail is full of them.

**A proxy alone does not fix it**, which is the part worth holding on to: routing
the fetch through the server protects the browser and dedupes the request, but
it still leaves the machine for content nobody chose. Under `Law 16` that is the
same defect one hop further away. So the default is `ask`, and the proxy is what
"yes" does.
"""
import pathlib

import pytest

from routes import image_proxy_routes as ip

REPO = pathlib.Path(__file__).resolve().parent.parent


# ── the defaults ─────────────────────────────────────────────────────────

def test_nothing_loads_until_someone_asks(monkeypatch):
    from src.settings import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["remote_images"] == "ask", (
        "remote images load without being asked for"
    )


def test_an_unknown_mode_falls_back_to_ask(monkeypatch):
    monkeypatch.setattr("src.settings.get_setting", lambda *a, **k: "wide-open", raising=False)
    import src.settings as st
    monkeypatch.setattr(st, "get_setting", lambda *a, **k: "wide-open")
    assert ip.remote_image_mode() == "ask", "a bad value opened the gate instead of closing it"


def test_a_broken_settings_layer_falls_back_to_ask(monkeypatch):
    import src.settings as st

    def boom(*a, **k):
        raise RuntimeError("no settings")
    monkeypatch.setattr(st, "get_setting", boom)
    assert ip.remote_image_mode() == "ask"


# ── what the proxy will and will not serve ───────────────────────────────

def test_svg_is_not_a_servable_image_type():
    """SVG executes. `FORBIDDEN.md` Part 2 keeps it out of the gallery's
    IMAGE_EXTS for the same reason, and this path serves bytes a stranger chose
    to a logged-in origin."""
    assert "image/svg+xml" not in ip.ALLOWED_TYPES
    assert "text/html" not in ip.ALLOWED_TYPES
    assert "application/javascript" not in ip.ALLOWED_TYPES


def test_only_bitmap_types_are_allowed():
    for ctype in ip.ALLOWED_TYPES:
        assert ctype.startswith("image/"), ctype


def test_there_is_a_size_cap():
    assert 0 < ip.MAX_IMAGE_BYTES <= 32 * 1024 * 1024


def test_the_cache_key_is_per_url():
    assert ip._cache_key("https://a.test/x.png") != ip._cache_key("https://b.test/x.png")
    assert ip._cache_key("https://a.test/x.png") == ip._cache_key("https://a.test/x.png")


# ── the CSP, which is the half that makes the rest binding ───────────────

def test_the_csp_no_longer_allows_arbitrary_image_hosts():
    """Without this the proxy is optional and the beacon still fires."""
    mw = (REPO / "core/middleware.py").read_text(encoding="utf-8")
    live = [
        ln for ln in mw.splitlines()
        if "img-src" in ln and not ln.strip().startswith("#")
    ]
    assert live, "no img-src directive found"
    for ln in live:
        assert "https:" not in ln, f"img-src still allows any https host: {ln.strip()}"
        assert "'self'" in ln


def test_every_csp_site_was_tightened_not_just_one():
    """There are two — the report pages and the app. Missing one leaves the hole."""
    mw = (REPO / "core/middleware.py").read_text(encoding="utf-8")
    live = [ln for ln in mw.splitlines()
            if "img-src" in ln and not ln.strip().startswith("#")]
    assert len(live) >= 2, f"expected both CSP blocks to carry img-src, found {len(live)}"


# ── the renderer ─────────────────────────────────────────────────────────

def _markdown_js() -> str:
    return (REPO / "static/js/markdown.js").read_text(encoding="utf-8")


def test_same_origin_images_are_untouched():
    js = _markdown_js()
    i = js.index("function imageHtml(")
    body = js[i:i + 2400]
    assert "_isSameOrigin" in body, "our own images now go through the proxy too"


def test_remote_images_become_a_control_not_an_img():
    js = _markdown_js()
    i = js.index("function imageHtml(")
    body = js[i:i + 2400]
    assert "remote-img-ask" in body
    assert "/api/img?u=" in body, "the proxy is never used"
    assert "encodeURIComponent" in body, "the URL is interpolated without encoding"


def test_the_raw_remote_url_never_reaches_an_img_src():
    """Presence of the placeholder is not absence of the beacon.

    An earlier version of these tests only asserted that `remote-img-ask` and
    `/api/img?u=` appeared in the renderer. A mutation that emitted **both** a
    plain `<img src=rawUrl>` *and* the button sailed through — and the CSP would
    have caught it in a browser, which is exactly the kind of second layer that
    hides a first-layer regression. So: the third-party URL may appear in an
    `src` exactly once, on the same-origin path, and nowhere else.
    """
    js = _markdown_js()
    i = js.index("function imageHtml(")
    body = js[i:js.index("\n}", i)]
    uses = body.count('src="${escapeHtml(safeUrl)}"')
    assert uses == 1, (
        f"the un-proxied URL is used as an img src {uses} times; exactly one "
        "(the same-origin branch) is correct"
    )
    same_origin_at = body.index("_isSameOrigin(safeUrl)")
    after = body[same_origin_at:]
    first_use = after.index('src="${escapeHtml(safeUrl)}"')
    assert after[:first_use].count("return") == 0 or "proxied" not in after[:first_use], (
        "the raw URL is emitted after the same-origin branch has been left"
    )


def test_the_placeholder_names_the_host_it_would_call():
    """"Load image" tells you nothing. The host is the decision."""
    js = _markdown_js()
    i = js.index("function imageHtml(")
    body = js[i:i + 2400]
    assert "Load image from" in body
    assert ".host" in body


def test_the_placeholder_has_a_click_handler():
    """Law 13 — a button that does nothing is worse than no button."""
    js = _markdown_js()
    assert "remote-img-ask[data-remote-src]" in js, "the placeholder is never wired"
    assert "replaceWith(img)" in js


def test_the_mode_is_fetched_and_defaults_safe_until_it_answers():
    js = _markdown_js()
    assert "/api/img/mode" in js, "the client never learns the configured mode"
    assert "let _remoteImageMode = 'ask'" in js, (
        "the pre-answer default is not the safe one"
    )
