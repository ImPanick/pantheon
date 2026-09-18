# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P0-17` — the AGPL-3.0 §13 source offer, on every page the app serves.

§13 obliges whoever offers a modified version over a network to give its users
an opportunity to receive the Corresponding Source. Pantheon is a modified
Odysseus, so the obligation is the operator's the moment they put it in front of
anybody else.

**Both branches, because the shipped one is the dark one** (`D-2026-09-08-06`,
*"prime it, but dont flip that switch yet"*). With no `source_url` there is no
link: the repository is private, the default bind is loopback, no §13 offer is
being made, and a link a stranger gets a 404 from would be an offer that cannot
be honoured — the mistake `B25` recorded in `CHANGELOG.md`. With one set, the
link is there, on every page, with the provenance sentence on it.

**The page list is derived, not typed** (`Law 13`). `app.py` already holds the
one answer to *which documents do routes serve* —
`ROUTE_OWNED_STATIC_PAGES` — so these tests read it. A third page added there
is covered the day it lands; a list here would be a second source of truth and
would be wrong by exactly one page.
"""

import ast
import pathlib
import re
import types

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette.responses")
from starlette.datastructures import Headers

from src.app_helpers import _PAGE_CACHE, serve_html_with_nonce
from src.source_link import (
    SOURCE_LINK_TITLE,
    normalise_source_url,
    source_link_html,
)

_REPO = pathlib.Path(__file__).resolve().parents[1]
_URL = "https://github.com/ImPanick/pantheon"


def _route_owned_pages():
    """The shipped documents a route serves, read off `app.py`'s own map.

    Parsed rather than imported: importing `app.py` starts the application.
    Entries the build does not ship (`backgrounds.html`, `B140`) drop out by
    not being on disk.
    """
    tree = ast.parse((_REPO / "app.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "ROUTE_OWNED_STATIC_PAGES"
                   for t in node.targets):
            continue
        for key in node.value.keys:
            page = _REPO / "static" / key.value
            if page.is_file():
                yield page
        return
    raise AssertionError("ROUTE_OWNED_STATIC_PAGES not found in app.py")


@pytest.fixture(autouse=True)
def _clean_page_cache():
    _PAGE_CACHE.clear()
    yield
    _PAGE_CACHE.clear()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("PANTHEON_SOURCE_URL", _URL)
    _PAGE_CACHE.clear()


@pytest.fixture
def dark(monkeypatch):
    monkeypatch.delenv("PANTHEON_SOURCE_URL", raising=False)
    _PAGE_CACHE.clear()


def _request(**headers):
    return types.SimpleNamespace(
        state=types.SimpleNamespace(csp_nonce="n"), headers=Headers(headers or {}),
    )


def _render(page):
    resp = serve_html_with_nonce(_request(), str(page))
    return resp.body.decode("utf-8")


def test_the_derivation_finds_the_pages_it_is_supposed_to_find():
    # A derivation that matched nothing would make every test below vacuous.
    names = {p.name for p in _route_owned_pages()}
    assert {"index.html", "login.html"} <= names


# ── the lit branch ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("page", list(_route_owned_pages()), ids=lambda p: p.name)
def test_a_configured_repository_puts_the_offer_on_every_served_page(configured, page):
    html = _render(page)
    assert 'data-source-offer="1"' in html, f"{page.name} carries no §13 source offer"
    assert f'href="{_URL}"' in html
    assert SOURCE_LINK_TITLE in html


@pytest.mark.parametrize("page", list(_route_owned_pages()), ids=lambda p: p.name)
def test_the_offer_is_inside_the_document(configured, page):
    html = _render(page)
    assert html.rstrip().endswith("</html>")
    assert html.index('data-source-offer="1"') < html.rindex("</body>"), (
        "the offer must be in the body, not trailing after it")


def test_the_login_page_carries_it_before_anyone_has_authenticated(configured):
    # The surface that matters most for §13: a user interacting with this
    # instance over a network meets the login page first, and may never get
    # past it.
    login = _REPO / "static" / "login.html"
    assert 'data-source-offer="1"' in _render(login)


# ── the dark branch, which is what ships ──────────────────────────────────────


@pytest.mark.parametrize("page", list(_route_owned_pages()), ids=lambda p: p.name)
def test_no_configured_repository_means_no_control_at_all(dark, page):
    html = _render(page)
    assert "data-source-offer" not in html
    assert SOURCE_LINK_TITLE not in html


def test_the_shipped_default_is_empty():
    # `D-2026-09-08-06`: built and left dark. If this ever ships non-empty, the
    # product starts making a §13 offer nobody decided to make.
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["source_url"] == ""


def test_the_address_is_the_only_switch():
    # `D-2026-09-05-01`, `Law 14`. A second boolean can disagree with the
    # address, and the disagreement is silent in the direction that matters.
    from src.settings import DEFAULT_SETTINGS
    beside = [k for k in DEFAULT_SETTINGS
              if k.startswith("source") and k != "source_url"]
    assert not beside, f"a second control appeared beside source_url: {beside}"


# ── what may be in the href ───────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "vbscript:msgbox(1)",
    "  ",
    "github.com/ImPanick/pantheon",   # no scheme
    "https://",                        # no host
    None,
    12345,
    # These carry a netloc, so rejecting "no host" does not reach them and the
    # scheme allowlist is the only thing standing between an operator's typo —
    # or a settings write — and script execution on the pre-auth page. The `//`
    # opens a JavaScript comment and the newline closes it, which is why the
    # host-shaped middle is harmless to the payload.
    "javascript://example.com/%0Aalert(1)",
    "JavaScript://example.com/%0Aalert(1)",   # scheme comparison is case-folded
    "vbscript://example.com/%0Amsgbox(1)",
    "data://example.com/,<script>alert(1)</script>",
    "file://example.com/etc/passwd",
])
def test_a_non_http_address_renders_nothing(bad):
    # The login page is served before authentication, so this href is the one
    # in the product with the least between it and an anonymous visitor.
    assert normalise_source_url(bad) == ""
    assert source_link_html(bad) == ""


def test_the_href_is_escaped():
    html = source_link_html('https://example.com/a"><script>alert(1)</script>')
    assert "<script>" not in html
    assert "&quot;" in html or "&#x27;" in html


def test_an_unreadable_setting_does_not_take_the_app_down(monkeypatch):
    # This runs on the path that serves `/`. A licence control may not be able
    # to 500 the application.
    import src.source_link as sl

    def boom(*a, **k):
        raise RuntimeError("settings file is a directory")

    monkeypatch.setattr(sl, "load_settings", boom, raising=False)
    monkeypatch.setattr("src.settings.load_settings", boom)
    _PAGE_CACHE.clear()
    html = _render(_REPO / "static" / "login.html")
    assert html.rstrip().endswith("</html>")


# ── themes are protected ──────────────────────────────────────────────────────


def test_the_control_names_no_colour_and_defines_no_token():
    """Sixteen themes, and `--accent` is never defined in `:root`.

    The control consumes tokens that already exist and defines none. A literal
    colour here would be the one element in the product that does not change
    with the theme.
    """
    html = source_link_html(_URL)
    assert re.search(r"#[0-9a-fA-F]{3,8}\b", html) is None, "a literal colour"
    assert re.search(r"\b(rgb|rgba|hsl|hsla)\(", html) is None, "a literal colour"
    # Consuming `var(--accent, …)` is fine and is what the rest of the product
    # does; *defining* it is what the ruling forbids.
    assert "--accent:" not in html
    assert ":root" not in html
    for token in ("var(--accent", "var(--fg-muted)", "var(--border)", "var(--panel)"):
        assert token in html, f"{token} missing — the control must inherit, not name"


def test_the_control_cannot_swallow_a_click_meant_for_the_app():
    # It is `position: fixed` over a dense shell. The wrapper takes no pointer
    # events; only the anchor does.
    html = source_link_html(_URL)
    wrapper, anchor = html.split("<a ", 1)
    assert "pointer-events:none" in wrapper
    assert "pointer-events:auto" in anchor


def test_the_link_opens_out_of_the_app_safely():
    html = source_link_html(_URL)
    assert 'target="_blank"' in html
    assert "noopener" in html and "noreferrer" in html


# ── the cache may not outlive the decision ────────────────────────────────────


def test_turning_it_on_changes_the_next_response_without_a_restart(monkeypatch):
    login = _REPO / "static" / "login.html"
    monkeypatch.delenv("PANTHEON_SOURCE_URL", raising=False)
    assert "data-source-offer" not in _render(login)
    monkeypatch.setenv("PANTHEON_SOURCE_URL", _URL)
    assert "data-source-offer" in _render(login), (
        "the page cache is keyed on the file alone, so the operator's change "
        "would not appear until a restart")


def test_the_validator_describes_the_bytes_that_were_sent(monkeypatch):
    login = _REPO / "static" / "login.html"
    monkeypatch.delenv("PANTHEON_SOURCE_URL", raising=False)
    _PAGE_CACHE.clear()
    dark_etag = serve_html_with_nonce(_request(), str(login)).headers["etag"]
    monkeypatch.setenv("PANTHEON_SOURCE_URL", _URL)
    _PAGE_CACHE.clear()
    lit = serve_html_with_nonce(_request(), str(login))
    assert lit.headers["etag"] != dark_etag, (
        "two different documents shared an ETag; a client would keep the one "
        "it had (RFC 9111 §4.3.4)")
    # And the ETag is over the bytes actually sent, injection included.
    import hashlib
    assert lit.headers["etag"] == '"' + hashlib.sha256(lit.body).hexdigest()[:32] + '"'


def test_a_conditional_request_still_gets_a_304(configured):
    login = _REPO / "static" / "login.html"
    etag = serve_html_with_nonce(_request(), str(login)).headers["etag"]
    again = serve_html_with_nonce(_request(**{"if-none-match": etag}), str(login))
    assert again.status_code == 304


def test_the_injection_adds_no_inline_script(configured):
    # `serve_html_with_nonce` authorises inline blocks by hash. An injected
    # script would have to be hashed with them, and a control that widens the
    # page's CSP is not the way to satisfy a licence.
    from src.app_helpers import inline_script_hashes
    login = (_REPO / "static" / "login.html").read_text(encoding="utf-8")
    assert "<script" not in source_link_html(_URL)
    assert inline_script_hashes(login) == inline_script_hashes(
        login.replace("</body>", source_link_html(_URL) + "</body>"))
