# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P18-04` — the setting called `app_public_url`, and the one that was read.

The row said *"`app_public_url` is a setting an operator can type and no OAuth
path reads"*. True, and it undersells the reason:

**THERE IS A SETTING `app_public_url` AND AN ENVIRONMENT VARIABLE
`APP_PUBLIC_URL`, AND THEY WERE NEVER CONNECTED.** `src/settings.py` ships the
setting, the Settings panel has a field for it, and `src/mcp_oauth.py` read
`os.environ["APP_PUBLIC_URL"]`. Typing the value where it is discoverable
changed nothing, and the two names are indistinguishable when anybody describes
the problem out loud.

The email OAuth path consulted neither. It built its redirect from the request's
`Host` header and `request.url.scheme`, and behind a reverse proxy both are
wrong in the same direction — uvicorn honours `X-Forwarded-Proto` only from a
peer inside `--forwarded-allow-ips`, default `127.0.0.1`, which excludes a proxy
on the Docker bridge. An HTTPS deployment built an `http://` redirect and Google
answered `redirect_uri_mismatch`.

**THE HARDEST PART OF THIS ROW WAS NOT BREAKING WHAT WORKED.** Somebody reaching
Pantheon at `http://192.168.1.71:7000` works *because* of the `Host` header.
Replacing it with a configured origin would have fixed the proxy case by
breaking every direct-access deployment. So nothing was removed — three
deliberate sources were added above the request, and the request kept its place
above the localhost default. Several tests below exist only to pin that.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import public_origin  # noqa: E402

_ENV = ("OAUTH_REDIRECT_BASE_URL", "APP_PUBLIC_URL", "APP_PORT")


class _FakeURL:
    def __init__(self, scheme):
        self.scheme = scheme


class _FakeRequest:
    def __init__(self, scheme="http", host="pantheon.local:7000"):
        self.url = _FakeURL(scheme)
        self.headers = {"host": host}


@pytest.fixture()
def clean(monkeypatch):
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(public_origin, "_from_setting", lambda: "")
    return monkeypatch


# --------------------------------------------------------------------------
# The order, which is the whole design
# --------------------------------------------------------------------------


def test_the_setting_is_read_at_all(clean):
    """The row, in one assertion."""
    clean.setattr(public_origin, "_from_setting", lambda: "https://typed.example")
    assert public_origin.public_origin() == "https://typed.example"
    assert public_origin.source_of() == "app_public_url"


def test_an_explicit_env_outranks_everything(clean):
    clean.setenv("OAUTH_REDIRECT_BASE_URL", "https://explicit.example/")
    clean.setenv("APP_PUBLIC_URL", "https://public.example")
    clean.setattr(public_origin, "_from_setting", lambda: "https://typed.example")
    assert public_origin.public_origin(_FakeRequest()) == "https://explicit.example"
    assert public_origin.source_of() == "OAUTH_REDIRECT_BASE_URL"


def test_the_public_env_outranks_the_setting(clean):
    """A deployment's declaration is not silently overridden from a web form."""
    clean.setenv("APP_PUBLIC_URL", "https://public.example")
    clean.setattr(public_origin, "_from_setting", lambda: "https://typed.example")
    assert public_origin.public_origin() == "https://public.example"


def test_the_setting_outranks_the_request(clean):
    """The proxy case: the request is wrong and the operator said so."""
    clean.setattr(public_origin, "_from_setting", lambda: "https://proxied.example")
    assert public_origin.public_origin(_FakeRequest(scheme="http")) == "https://proxied.example"


def test_the_request_still_wins_over_the_default(clean):
    """`Law 1`. Direct-access deployments work *because* of the Host header.

    This is the assertion that stops the fix for one deployment shape becoming
    a regression for every other one.
    """
    assert (
        public_origin.public_origin(_FakeRequest(host="192.168.1.71:7000"))
        == "http://192.168.1.71:7000"
    )
    assert public_origin.source_of(_FakeRequest()) == "request"


def test_with_nothing_at_all_it_uses_the_bound_port(clean):
    """`APP_PORT`, not a fixed 7000: the macOS launcher binds 7860."""
    clean.setenv("APP_PORT", "7860")
    assert public_origin.public_origin() == "http://localhost:7860"
    assert public_origin.source_of() == "default"


def test_no_request_means_no_request_source(clean):
    """Module-level constants and background jobs have no request to consult."""
    assert public_origin.public_origin() == "http://localhost:7000"


# --------------------------------------------------------------------------
# Shapes that would otherwise produce a silently wrong URI
# --------------------------------------------------------------------------


def test_trailing_slashes_are_trimmed_everywhere(clean):
    """Google compares the redirect URI as a string; one slash is a mismatch."""
    clean.setenv("OAUTH_REDIRECT_BASE_URL", "https://a.example///")
    assert public_origin.public_origin() == "https://a.example"


def test_whitespace_is_not_a_value(clean):
    clean.setenv("APP_PUBLIC_URL", "   ")
    clean.setattr(public_origin, "_from_setting", lambda: "https://typed.example")
    assert public_origin.public_origin() == "https://typed.example"


def test_a_request_with_no_host_header_falls_through(clean):
    request = _FakeRequest()
    request.headers = {}
    assert public_origin.public_origin(request) == "http://localhost:7000"


def test_an_unreadable_settings_file_is_not_an_import_failure(monkeypatch):
    """`_from_setting` is the only source that touches disk; it must not raise.

    This module is imported by `src/mcp_oauth.py` during startup. A settings
    read that throws must read as *nobody typed anything*, which is the common
    case, rather than taking the import down.
    """
    def _boom(*a, **k):
        raise OSError("settings.json is a directory")

    monkeypatch.setattr("src.settings.get_setting", _boom)
    assert public_origin._from_setting() == ""


# --------------------------------------------------------------------------
# Telling the operator, which is the half that stops it happening again
# --------------------------------------------------------------------------


def test_an_overridden_setting_is_reported(clean):
    """A field that silently does nothing is the defect this row is about.

    Fixing the plumbing and leaving the panel quiet would have reproduced it
    one layer down: the operator types a value, an environment variable wins,
    and nothing says so.
    """
    clean.setattr(public_origin, "_from_setting", lambda: "https://typed.example")
    assert public_origin.setting_is_overridden() is False
    clean.setenv("APP_PUBLIC_URL", "https://public.example")
    assert public_origin.setting_is_overridden() is True


def test_an_empty_setting_is_not_reported_as_overridden(clean):
    clean.setenv("APP_PUBLIC_URL", "https://public.example")
    assert public_origin.setting_is_overridden() is False


# --------------------------------------------------------------------------
# The two callers
# --------------------------------------------------------------------------


def test_both_halves_of_the_email_flow_build_the_uri_the_same_way():
    """Google rejects the exchange if authorize and callback differ by a character.

    They were the same *expression* twice, which worked and was one edit away
    from not working — with a failure that says only `redirect_uri_mismatch`.
    """
    source = (ROOT / "routes" / "email_routes.py").read_text(encoding="utf-8")
    # `P18-05` made the provider a parameter, so the shared expression is now
    # `_provider_redirect_uri(provider, request)`. Still counted rather than
    # eyeballed: the point is that there is **one** expression used twice, not
    # what it is spelled.
    assert source.count("redirect_uri = _provider_redirect_uri(provider, request)") == 2
    assert "request.headers.get('host'" not in source, (
        "the Host header is back in the redirect path"
    )


def test_the_email_redirect_honours_the_explicit_variable(clean, monkeypatch):
    import routes.email_routes as er

    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://set.example/cb")
    assert er._google_redirect_uri(_FakeRequest()) == "https://set.example/cb"
    assert er._redirect_uri_source(_FakeRequest()) == "GOOGLE_OAUTH_REDIRECT_URI"


def test_the_email_redirect_uses_the_setting_when_nothing_else_is_set(clean, monkeypatch):
    import routes.email_routes as er

    monkeypatch.delenv("GOOGLE_OAUTH_REDIRECT_URI", raising=False)
    clean.setattr(public_origin, "_from_setting", lambda: "https://proxied.example")
    assert (
        er._google_redirect_uri(_FakeRequest())
        == "https://proxied.example/api/email/oauth/google/callback"
    )


def test_the_provider_list_shows_the_uri_to_register(clean, monkeypatch):
    """`Law 15`. Before this the only way to learn the value was to fail the flow.

    An operator has to paste this exact string into Google Cloud Console, and
    it was never displayed anywhere — it came back as `redirect_uri_mismatch`,
    which names the problem and not the answer.
    """
    import routes.email_routes as er

    monkeypatch.delenv("GOOGLE_OAUTH_REDIRECT_URI", raising=False)
    google = next(p for p in er._oauth_providers(_FakeRequest()) if p["id"] == "google")
    assert google["redirect_uri"].endswith("/api/email/oauth/google/callback")
    assert google["redirect_uri_source"] == "request"
    assert google["public_url_overridden"] is False


def test_the_panel_renders_the_redirect_uri():
    js = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "provider.redirect_uri" in js
    assert "uf-oauth-redirect" in js
    # The field's own description used to say it was for deep-links in alert
    # emails only, which was accurate and is the smallest slice of what a
    # setting named "public URL" looks like it does. Asserting the substance
    # rather than the key: naming the setting inside its own description would
    # satisfy a grep and tell a reader nothing.
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    card = html[html.index("Public App URL"):]
    card = card[: card.index("set-app-public-url-msg")]
    assert "OAuth" in card, "the field must say it now affects the OAuth redirect"
    assert "redirect" in card.lower()
    assert "reverse proxy" in card.lower(), "say when it is needed, not just that it exists"


def test_mcp_oauth_delegates_rather_than_keeping_its_own_ladder():
    """`Law 14`. Two resolvers is how the setting got orphaned in the first place."""
    source = (ROOT / "src" / "mcp_oauth.py").read_text(encoding="utf-8")
    assert "from src.public_origin import public_origin" in source
    assert 'os.environ.get("APP_PUBLIC_URL")' not in source
    assert 'os.environ.get("OAUTH_REDIRECT_BASE_URL")' not in source
