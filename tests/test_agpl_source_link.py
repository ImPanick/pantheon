# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P0-17` — the AGPL-3.0 §13 source offer, on every page the app serves.

§13 obliges whoever offers a modified version over a network to give its users
an opportunity to receive the Corresponding Source. Pantheon is a modified
Odysseus, so the obligation is the operator's the moment they put it in front of
anybody else.

**Both branches** (`Law 20`). From 2026-09-18 to 2026-10-02 the shipped branch
was the dark one (`D-2026-09-08-06`, *"prime it, but dont flip that switch
yet"*): the repository was private, and a link a stranger gets a 404 from is an
offer that cannot be honoured — the mistake `B25` recorded in `CHANGELOG.md`.
The repository is public now, and `D-2026-10-02-04` §2 points the offer at it by
default: **with nothing configured, every page offers
`https://github.com/ImPanick/pantheon`**, the source an unmodified install runs.
**With `PANTHEON_SOURCE_URL` or the stored `source_url` set** — what a modified
copy owes its users — every page offers that instead. Both are driven through
the page the server actually sends, and so is the one way left to draw no link:
an address that is not http(s).

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
    DEFAULT_SOURCE_URL,
    SOURCE_LINK_TITLE,
    normalise_source_url,
    source_link_html,
    source_url,
)

_REPO = pathlib.Path(__file__).resolve().parents[1]
_URL = "https://github.com/ImPanick/pantheon"
# A modified copy's own source — anything that is not the default.
_FORK = "https://git.example.org/someone/pantheon-fork"


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
    """A modified copy pointing the offer at its own source."""
    monkeypatch.setenv("PANTHEON_SOURCE_URL", _FORK)
    _PAGE_CACHE.clear()


@pytest.fixture
def unconfigured(monkeypatch):
    """What ships: no variable, and the stored setting at its default."""
    monkeypatch.delenv("PANTHEON_SOURCE_URL", raising=False)
    _PAGE_CACHE.clear()


@pytest.fixture
def stored(monkeypatch):
    """Point the stored `source_url` at a value, as `POST /api/auth/settings`
    or `data/settings.json` would."""
    import src.settings as settings

    real = settings.load_settings

    def _set(value):
        monkeypatch.setattr(settings, "load_settings",
                            lambda *a, **k: {**real(*a, **k), "source_url": value})
        _PAGE_CACHE.clear()
    return _set


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


# ── the configured branch: a modified copy names its own source ──────────────


@pytest.mark.parametrize("page", list(_route_owned_pages()), ids=lambda p: p.name)
def test_a_configured_repository_puts_the_offer_on_every_served_page(configured, page):
    html = _render(page)
    assert 'data-source-offer="1"' in html, f"{page.name} carries no §13 source offer"
    assert f'href="{_FORK}"' in html
    assert f'href="{_URL}"' not in html, "the default must not survive an override"
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


# ── the default branch, which is what ships ───────────────────────────────────


@pytest.mark.parametrize("page", list(_route_owned_pages()), ids=lambda p: p.name)
def test_an_unconfigured_install_offers_the_public_repository(unconfigured, page):
    """`D-2026-10-02-04` §2. Until 2026-10-02 this was the dark branch —
    `test_no_configured_repository_means_no_control_at_all` — and an unmodified
    install offered nothing."""
    html = _render(page)
    assert html.count('data-source-offer="1"') == 1, page.name
    assert f'href="{_URL}"' in html
    assert SOURCE_LINK_TITLE in html


def test_the_default_is_this_repository_and_sits_beneath_the_stored_setting(unconfigured):
    """The default is a code constant under the stored layer, not a stored
    value: `DEFAULT_SETTINGS["source_url"]` ships empty, so the variable stays
    reachable beneath it (`H06`, `B20`) — one admin save of the settings panel
    cannot materialise the default over a variable the operator set."""
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["source_url"] == ""
    assert DEFAULT_SOURCE_URL == _URL
    assert source_url() == _URL


def test_the_environment_overrides_the_default(configured):
    assert source_url() == _FORK


def test_a_stored_setting_overrides_the_environment(configured, stored):
    stored("https://code.example.net/ops/pantheon")
    assert source_url() == "https://code.example.net/ops/pantheon"
    assert 'href="https://code.example.net/ops/pantheon"' in _render(
        _REPO / "static" / "login.html")


def test_a_blank_stored_setting_falls_through_to_the_environment(configured, stored):
    """What the settings panel writes for a cleared field (`env_backed`)."""
    stored("   ")
    assert source_url() == _FORK


@pytest.mark.parametrize("page", list(_route_owned_pages()), ids=lambda p: p.name)
def test_an_address_that_is_not_http_draws_no_link_rather_than_a_wrong_one(
        monkeypatch, page):
    """The one way left to draw no control: a value that is set and is not an
    absolute http(s) URL. It does not fall back to the default — an operator
    who typed something meant to replace the offer, and a wrong offer is worse
    than none (`B25`)."""
    monkeypatch.setenv("PANTHEON_SOURCE_URL", "javascript:alert(1)")
    _PAGE_CACHE.clear()
    html = _render(page)
    assert "data-source-offer" not in html
    assert SOURCE_LINK_TITLE not in html


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
    if bad is not None:
        # `None` is `source_link_html`'s own "read the configuration" argument,
        # which since `D-2026-10-02-04` §2 answers with the default — driven by
        # the default branch above. Every other value here is an address.
        assert source_link_html(bad) == ""


def test_the_href_is_escaped():
    html = source_link_html('https://example.com/a"><script>alert(1)</script>')
    assert "<script>" not in html
    assert "&quot;" in html or "&#x27;" in html


def test_an_unreadable_setting_does_not_take_the_app_down(monkeypatch):
    # This runs on the path that serves `/`. A licence control may not be able
    # to 500 the application — and an unreadable settings file is not a reason
    # to withdraw the offer: the environment, then the default, still answer.
    import src.source_link as sl

    def boom(*a, **k):
        raise RuntimeError("settings file is a directory")

    monkeypatch.setattr(sl, "load_settings", boom, raising=False)
    monkeypatch.setattr("src.settings.load_settings", boom)
    monkeypatch.delenv("PANTHEON_SOURCE_URL", raising=False)
    _PAGE_CACHE.clear()
    html = _render(_REPO / "static" / "login.html")
    assert html.rstrip().endswith("</html>")
    assert f'href="{_URL}"' in html
    monkeypatch.setenv("PANTHEON_SOURCE_URL", _FORK)
    _PAGE_CACHE.clear()
    assert f'href="{_FORK}"' in _render(_REPO / "static" / "login.html")


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


def test_pointing_it_elsewhere_changes_the_next_response_without_a_restart(monkeypatch):
    login = _REPO / "static" / "login.html"
    monkeypatch.delenv("PANTHEON_SOURCE_URL", raising=False)
    assert f'href="{_URL}"' in _render(login)
    monkeypatch.setenv("PANTHEON_SOURCE_URL", _FORK)
    assert f'href="{_FORK}"' in _render(login), (
        "the page cache is keyed on the file alone, so the operator's change "
        "would not appear until a restart")


def test_the_validator_describes_the_bytes_that_were_sent(monkeypatch):
    login = _REPO / "static" / "login.html"
    monkeypatch.delenv("PANTHEON_SOURCE_URL", raising=False)
    _PAGE_CACHE.clear()
    default_etag = serve_html_with_nonce(_request(), str(login)).headers["etag"]
    monkeypatch.setenv("PANTHEON_SOURCE_URL", _FORK)
    _PAGE_CACHE.clear()
    lit = serve_html_with_nonce(_request(), str(login))
    assert lit.headers["etag"] != default_etag, (
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
