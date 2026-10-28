# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import json
from src import mcp_oauth


def test_registry_resolve_returns_code_and_state():
    async def go():
        fut = mcp_oauth.register_pending("st-1")
        assert mcp_oauth.resolve_pending("st-1", "the-code") is True
        return await asyncio.wait_for(fut, timeout=1)
    # `B621`: and the redirect's RFC 9207 `iss`, `None` when it carried none.
    code, state, iss = asyncio.run(go())
    assert code == "the-code"
    assert state == "st-1"
    assert iss is None


def test_the_issuer_on_the_redirect_reaches_the_sdk():
    """`B621`. mcp 2.x's provider takes an `AuthorizationCodeResult` from the
    callback, and checks its `iss` against the authorization server's metadata
    — refusing one **without** it from a server that advertises
    `authorization_response_iss_parameter_supported`. Driven through the real
    provider's own two handlers, the way the SDK calls them."""
    async def go():
        p = mcp_oauth.build_provider("srv-iss", "https://example.com/mcp")
        await p.context.redirect_handler("https://as.example/authorize?state=st-iss&x=1")
        assert mcp_oauth.resolve_pending("st-iss", "the-code", "https://as.example") is True
        return await p.context.callback_handler()

    result = asyncio.run(go())
    assert (result.code, result.state, result.iss) == ("the-code", "st-iss", "https://as.example")


def test_the_callback_route_reads_the_issuer_from_the_query():
    """`B621`. The route the browser lands on declares `iss` as an optional
    query parameter — read from FastAPI's own parse of the handler, which is
    what decides whether `?iss=` reaches it — and hands it on."""
    import unittest.mock as mock
    from types import SimpleNamespace

    from routes.mcp.mcp_routes import setup_mcp_routes

    router = setup_mcp_routes(SimpleNamespace())
    route = next(r for r in router.routes if r.path == "/api/mcp/oauth/callback")
    query = {p.name: p for p in route.dependant.query_params}
    assert set(query) >= {"code", "state", "iss"} and not query["iss"].field_info.is_required()

    handed = []
    with mock.patch("routes.mcp.mcp_routes.require_admin", lambda request: None), \
            mock.patch("src.mcp_oauth.resolve_pending",
                       lambda state, code, iss=None: handed.append((state, code, iss)) or True):
        asyncio.run(route.endpoint(code="c", state="s", request=None, iss="https://as.example"))
    assert handed == [("s", "c", "https://as.example")]


def test_resolve_unknown_state_is_false():
    assert mcp_oauth.resolve_pending("nope", "x") is False


def test_register_pending_prunes_abandoned_flows():
    import time as _t

    async def go():
        mcp_oauth._pending.clear()
        mcp_oauth._pending_ts.clear()
        old = mcp_oauth.register_pending("old-state")
        # Backdate the entry past the authorization window.
        mcp_oauth._pending_ts["old-state"] = _t.monotonic() - (mcp_oauth.AUTH_WAIT_SECONDS + 1)
        # A new registration triggers a prune of the stale one.
        mcp_oauth.register_pending("new-state")
        return old

    old = asyncio.run(go())
    assert "old-state" not in mcp_oauth._pending
    assert "old-state" not in mcp_oauth._pending_ts
    assert "new-state" in mcp_oauth._pending
    assert old.cancelled()


def test_build_provider_has_pantheon_client_metadata():
    p = mcp_oauth.build_provider("srv-1", "https://example.com/mcp")
    md = p.context.client_metadata
    assert md.client_name == "Pantheon"
    assert "authorization_code" in md.grant_types
    assert "refresh_token" in md.grant_types
    assert str(md.redirect_uris[0]).rstrip("/") == mcp_oauth.REDIRECT_URI.rstrip("/")


def test_db_token_storage_round_trip():
    from mcp.shared.auth import OAuthToken

    class FakeSrv:
        oauth_tokens = None

    srv = FakeSrv()

    class FakeQuery:
        def filter(self, *a):
            return self

        def first(self):
            return srv

    class FakeSession:
        def query(self, *a):
            return FakeQuery()

        def commit(self):
            pass

        def close(self):
            pass

    storage = mcp_oauth.DbTokenStorage("srv-1", session_factory=lambda: FakeSession())

    async def go():
        await storage.set_tokens(OAuthToken(access_token="abc", token_type="Bearer"))
        return await storage.get_tokens()

    t = asyncio.run(go())
    assert t.access_token == "abc"
    assert srv.oauth_tokens is not None  # persisted as JSON


def _fake_storage(oauth_tokens):
    class FakeSrv:
        pass

    srv = FakeSrv()
    srv.oauth_tokens = oauth_tokens

    class FakeQuery:
        def filter(self, *a):
            return self

        def first(self):
            return srv

    class FakeSession:
        def query(self, *a):
            return FakeQuery()

        def commit(self):
            pass

        def close(self):
            pass

    return srv, mcp_oauth.DbTokenStorage("srv-1", session_factory=lambda: FakeSession())


def test_load_falls_back_to_empty_dict_for_non_dict_json():
    # A corrupted/migrated oauth_tokens column holding a JSON array, not an
    # object, must not crash _load()'s callers with AttributeError.
    _srv, storage = _fake_storage('["stale", "data"]')
    assert storage._load() == {}


def test_get_tokens_returns_none_for_non_dict_oauth_tokens():
    _srv, storage = _fake_storage("42")

    async def go():
        return await storage.get_tokens()

    assert asyncio.run(go()) is None


def test_update_recovers_from_non_dict_oauth_tokens():
    # _update() must not raise TypeError trying to item-assign into a list.
    srv, storage = _fake_storage('["stale", "data"]')
    storage._update("tokens", {"access_token": "new"})
    assert json.loads(srv.oauth_tokens) == {"tokens": {"access_token": "new"}}


# ── Callback origin ───────────────────────────────────────────────
#
# The redirect URI is registered with the authorization server (dynamically for
# remote MCP servers, by hand for Google ones) and the browser is sent to it
# after authorizing. It is resolved once, outside any request, so it cannot be
# derived from the request the way the email OAuth routes derive theirs — an
# operator-supplied origin is the only thing that can be right behind a proxy.
# What the default can get right is the port, which the app knows.

_REDIRECT_ENV = ("OAUTH_REDIRECT_BASE_URL", "APP_PUBLIC_URL", "APP_PORT")


def _resolve_base(monkeypatch, **env):
    for key in _REDIRECT_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return mcp_oauth._resolve_redirect_base()


def test_redirect_base_defaults_to_the_bound_port(monkeypatch):
    # The macOS launcher serves on 7860 because AirPlay Receiver holds 7000; a
    # callback pinned to 7000 lands on AirPlay instead of Pantheon.
    assert _resolve_base(monkeypatch, APP_PORT="7860") == "http://localhost:7860"


def test_redirect_base_keeps_7000_when_app_port_is_unset(monkeypatch):
    assert _resolve_base(monkeypatch) == "http://localhost:7000"


def test_redirect_base_prefers_the_explicit_origin(monkeypatch):
    # Only an operator-supplied origin can be right behind a TLS proxy, so it
    # outranks the derived default — and its trailing slash is trimmed.
    resolved = _resolve_base(
        monkeypatch, OAUTH_REDIRECT_BASE_URL="https://pantheon.example/", APP_PORT="7860"
    )
    assert resolved == "https://pantheon.example"


def test_redirect_base_accepts_app_public_url_as_the_alias(monkeypatch):
    assert (
        _resolve_base(monkeypatch, APP_PUBLIC_URL="https://public.example", APP_PORT="7860")
        == "https://public.example"
    )


# ── Paste-back form origin ────────────────────────────────────────

def _authorize_page():
    from routes.mcp.mcp_routes import _oauth_authorize_page

    return _oauth_authorize_page(
        "https://accounts.google.com/o/oauth2/v2/auth?state=srv-1",
        "srv-1",
        "https://pantheon.example.com/api/mcp/oauth/callback",
    )


def test_paste_back_form_action_is_relative():
    # Remote users finish the flow by pasting the callback URL into this form,
    # so it has to post back to the origin they are on. An absolute action
    # cannot: an http:// one is mixed content on an HTTPS page and gets blocked,
    # and the app cannot reliably tell that it is behind TLS, because uvicorn
    # only honours X-Forwarded-Proto from a peer inside --forwarded-allow-ips
    # (default 127.0.0.1, which a proxy on the Docker bridge is not). A relative
    # action is resolved by the browser and is right in every one of those cases.
    page = _authorize_page()
    assert 'action="/api/mcp/oauth/exchange/srv-1"' in page
    assert 'action="http' not in page


# ── Docker configurability ────────────────────────────────────────
#
# The override above is the only fix available to a Docker install: the
# container always listens on 7000 and cannot see the host port map, so the
# derived default cannot be right there. Compose has to forward the variable
# or the escape hatch does not exist.

_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.gpu-nvidia.yml",
    "docker-compose.gpu-amd.yml",
)


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


def test_redirect_base_override_is_forwarded_into_the_container():
    import yaml

    for name in _COMPOSE_FILES:
        path = _repo_root() / name
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
        environment = set(compose["services"]["pantheon"]["environment"])
        assert "OAUTH_REDIRECT_BASE_URL=${OAUTH_REDIRECT_BASE_URL:-}" in environment, name


def test_redirect_base_override_is_documented():
    import pytest

    env_example = _repo_root() / ".env.example"
    if not env_example.exists():
        pytest.skip("this checkout does not include the optional .env.example file")
    assert "# OAUTH_REDIRECT_BASE_URL=" in env_example.read_text(encoding="utf-8")


# ── Launcher port propagation ─────────────────────────────────────
#
# The derived default is only as good as APP_PORT, and every launcher hands the
# port to uvicorn as a command-line flag, which the app cannot read back. Each
# one has to put the same value in the environment or the callback falls back to
# 7000 — which is the macOS-launcher-on-7860 case this whole change is about.
# internal_api_base() and companion pairing read APP_PORT too, so they go wrong
# in the same way.

_LAUNCHERS = (
    # file, the export, the uvicorn flag it has to agree with
    ("start-macos.sh", 'export APP_PORT="$PORT"', '--port "$PORT"'),
    ("build-macos-app.sh", 'export APP_PORT="$PORT"', '--port "$PORT"'),
    ("launch-windows.ps1", "$env:APP_PORT = $Port", "--port $Port"),
)


def test_launchers_export_the_port_they_serve_on():
    for name, export, uvicorn_flag in _LAUNCHERS:
        text = (_repo_root() / name).read_text(encoding="utf-8")
        assert uvicorn_flag in text, f"{name}: launcher no longer passes {uvicorn_flag}"
        assert export in text, f"{name}: serves on a port the app cannot read back"
