# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import tempfile
from pathlib import Path

import pytest

_tmp_data = Path(tempfile.mkdtemp(prefix="pantheon-email-imap-test-"))
os.environ.setdefault("DATA_DIR", str(_tmp_data))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp_data / 'app.db'}")

from routes.email_helpers import (
    _IMAP_CONNECT_SECONDS,
    _IMAP_TIMEOUT_SECONDS,
    _coerce_imap_timeout_seconds,
    _open_imap_connection,
)


class _FakeSock:
    def __init__(self):
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout


class _FakeIMAP:
    calls = []

    def __init__(self, host, port, timeout=None, ssl_context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        # `B2096`: imaplib's own signature. Every TLS dial now hands one in.
        self.ssl_context = ssl_context
        self.sock = _FakeSock()
        self.starttls_called = False
        _FakeIMAP.calls.append(("connect", self.__class__.__name__, host, port, timeout))

    def starttls(self, ssl_context=None):
        self.starttls_called = True
        self.ssl_context = ssl_context
        _FakeIMAP.calls.append(("starttls", self.host, self.port))

    def login(self, user, password):
        _FakeIMAP.calls.append(("login", user, password))

    def logout(self):
        _FakeIMAP.calls.append(("logout", self.host, self.port))


class _FakeIMAPSSL(_FakeIMAP):
    pass


def test_imap_timeout_defaults_and_clamps():
    assert _coerce_imap_timeout_seconds(None) == 30
    assert _coerce_imap_timeout_seconds("nonsense") == 30
    assert _coerce_imap_timeout_seconds("2") == 5
    assert _coerce_imap_timeout_seconds("999") == 300


def test_open_imap_connection_uses_shared_timeout_for_implicit_ssl(monkeypatch):
    import routes.email_helpers as helpers

    _FakeIMAP.calls = []
    monkeypatch.setattr(helpers.imaplib, "IMAP4", _FakeIMAP)
    monkeypatch.setattr(helpers.imaplib, "IMAP4_SSL", _FakeIMAPSSL)

    conn = _open_imap_connection("imap.one.com", 993, starttls=False)

    # `P23-07`: the connection opens within its own cap; the session's reads
    # then run on the shared timeout.
    assert _FakeIMAP.calls == [
        ("connect", "_FakeIMAPSSL", "imap.one.com", 993, _IMAP_CONNECT_SECONDS)
    ]
    assert conn.sock.timeout == _IMAP_TIMEOUT_SECONDS


def test_open_imap_connection_supports_starttls(monkeypatch):
    import routes.email_helpers as helpers

    _FakeIMAP.calls = []
    monkeypatch.setattr(helpers.imaplib, "IMAP4", _FakeIMAP)
    monkeypatch.setattr(helpers.imaplib, "IMAP4_SSL", _FakeIMAPSSL)

    _open_imap_connection("imap.local", 143, starttls=True)

    assert _FakeIMAP.calls == [
        ("connect", "_FakeIMAP", "imap.local", 143, _IMAP_CONNECT_SECONDS),
        ("starttls", "imap.local", 143),
    ]


@pytest.mark.asyncio
async def test_account_config_uses_shared_imap_timeout(monkeypatch):
    import routes.email_routes as email_routes

    captured = {}

    class _Conn:
        def login(self, user, password):
            captured["login"] = (user, password)

        def logout(self):
            captured["logout"] = True

    def fake_open(host, port, *, starttls, timeout, owner="", reach=None):
        captured["open"] = (host, port, starttls, timeout)
        return _Conn()

    class _Req:
        async def json(self):
            return {
                "imap_host": "imap.one.com",
                "imap_port": 993,
                "imap_user": "user@example.com",
                "imap_password": "pw",
                "imap_starttls": False,
            }

    monkeypatch.setattr(email_routes, "_open_imap_connection", fake_open)

    router = email_routes.setup_email_routes()
    endpoint = next(route.endpoint for route in router.routes if route.path == "/api/email/accounts/test")

    result = await endpoint(_Req(), owner="")

    assert result["imap"] == {"ok": True}
    assert captured["open"] == ("imap.one.com", 993, False, _IMAP_TIMEOUT_SECONDS)
    assert captured["login"] == ("user@example.com", "pw")
    assert captured["logout"] is True


# ── `B1963`: port 993 is implicit TLS whatever the STARTTLS flag says ──
# An account a person adds for a host with no preset keeps the form's defaults,
# port 993 with STARTTLS ticked, and so does a row the legacy settings POST
# makes from the column defaults. Both openers honoured the flag and dialled a
# plain socket into the server's TLS listener; the read of a greeting that never
# comes timed out, and the person read only "timed out". Upstream Odysseus #6990.


class _FakeIMAPSSLWithContext(_FakeIMAP):
    def __init__(self, host, port, timeout=None, ssl_context=None):
        super().__init__(host, port, timeout=timeout)
        self.ssl_context = ssl_context


class _FakeIMAPUpgradeWithContext(_FakeIMAP):
    def starttls(self, ssl_context=None):
        super().starttls()


def test_an_account_on_993_with_starttls_ticked_dials_implicit_tls(monkeypatch):
    import routes.email_helpers as helpers

    _FakeIMAP.calls = []
    monkeypatch.setattr(helpers.imaplib, "IMAP4", _FakeIMAP)
    monkeypatch.setattr(helpers.imaplib, "IMAP4_SSL", _FakeIMAPSSL)

    conn = _open_imap_connection("imap.example.com", 993, starttls=True)

    assert _FakeIMAP.calls == [
        ("connect", "_FakeIMAPSSL", "imap.example.com", 993, _IMAP_CONNECT_SECONDS)
    ]
    assert not conn.starttls_called
    assert conn.sock.timeout == _IMAP_TIMEOUT_SECONDS


def test_the_test_buttons_tls_context_still_reaches_the_implicit_tls_dial(monkeypatch):
    import routes.email_helpers as helpers

    _FakeIMAP.calls = []
    monkeypatch.setattr(helpers.imaplib, "IMAP4", _FakeIMAPUpgradeWithContext)
    monkeypatch.setattr(helpers.imaplib, "IMAP4_SSL", _FakeIMAPSSLWithContext)
    context = object()

    conn = _open_imap_connection(
        "imap.gmail.com", 993, starttls=True, ssl_context=context,
    )

    assert _FakeIMAP.calls == [
        ("connect", "_FakeIMAPSSLWithContext", "imap.gmail.com", 993, _IMAP_CONNECT_SECONDS)
    ]
    assert conn.ssl_context is context


@pytest.fixture
def mcp_mail_config(monkeypatch, tmp_path):
    import mcp_servers.email_server as email_server

    for name in ("IMAP_SSL", "IMAP_STARTTLS", "PANTHEON_MCP_EMAIL_OWNER", "PANTHEON_EMAIL_OWNER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(email_server, "_SETTINGS_FILE", str(tmp_path / "missing-settings.json"))
    monkeypatch.setattr(email_server, "_ACCOUNT_CACHE", {})
    return email_server


def test_the_agents_mail_server_reads_imap_port_993_from_the_environment_as_implicit_tls(
        monkeypatch, mcp_mail_config):
    email_server = mcp_mail_config
    monkeypatch.setenv("IMAP_PORT", "993")      # IMAP_STARTTLS left at its default, on
    monkeypatch.setattr(email_server, "_read_accounts_from_db", lambda: [])

    cfg = email_server._load_config()

    assert (cfg["imap_ssl"], cfg["imap_starttls"]) == (True, False)


def test_the_agents_mail_server_reads_a_993_account_with_starttls_ticked_as_implicit_tls(
        monkeypatch, mcp_mail_config):
    email_server = mcp_mail_config
    monkeypatch.delenv("IMAP_PORT", raising=False)
    row = {
        "id": "acct-1", "owner": None, "name": "Work", "is_default": 1, "enabled": 1,
        "imap_host": "mail.example.com", "imap_port": 993, "imap_user": "ada@example.com",
        "imap_password": "", "imap_starttls": 1,
        "smtp_host": "mail.example.com", "smtp_port": 465, "smtp_security": "ssl",
        "smtp_user": "ada@example.com", "smtp_password": "", "from_address": "ada@example.com",
        "oauth_provider": "", "oauth_access_token": "", "oauth_refresh_token": "",
        "oauth_token_expiry": "",
    }
    monkeypatch.setattr(email_server, "_read_accounts_from_db", lambda: [row])

    cfg = email_server._load_config()

    assert cfg["account_id"] == "acct-1"
    assert (cfg["imap_ssl"], cfg["imap_starttls"]) == (True, False)
