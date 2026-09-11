# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P18-02` and `P18-03` — one answer to how a mailbox proves who it is.

**THE DEFECT HAD A CONSEQUENCE YOU COULD SEE.** *Can this account send mail* was
written by hand three times:

    routes/email_routes.py        host and user and (password or oauth_provider)
    routes/note/note_routes.py    host and user and (password or oauth_provider)
    mcp_servers/email_server.py   host and user and  password

Two agreed. The third omitted OAuth, and it is the copy the agent's own email
tools run. A mailbox linked with the Connect button sent mail from the web app,
sent mail from notes, and told the agent *"has no SMTP configured"* — the
feature working everywhere except where a person would most reasonably try it.

It was worse than one predicate. `mcp_servers/email_server.py` never selected
the four `oauth_*` columns at all, so a linked account arrived in that process
as an account with a blank password and failed as `AUTHENTICATIONFAILED` —
which reads like a wrong password, and sends the operator off to re-enter a
credential that was never wrong.

`P18-03` is the same disease facing the other way: XOAUTH2 was spelled four
times, and fixing `P18-02` by hand would have made six.

**SO THE TESTS HERE ARE MOSTLY ABOUT AGREEMENT.** Any one of these modules can
be made correct on its own and the bug comes back the next time somebody adds a
provider to two of the three. What has to hold is that there is one rule.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import mail_auth  # noqa: E402


def _oauth_cfg(**over):
    cfg = {
        "account_id": "acct-1",
        "imap_user": "someone@gmail.com",
        "smtp_host": "smtp.gmail.com",
        "smtp_user": "someone@gmail.com",
        "smtp_password": "",
        "oauth_provider": "google",
    }
    cfg.update(over)
    return cfg


# --------------------------------------------------------------------------
# The predicate the three modules disagreed about
# --------------------------------------------------------------------------


def test_a_linked_account_can_send_without_a_password():
    """The row in one sentence."""
    assert mail_auth.can_send(_oauth_cfg()) is True


def test_a_password_account_still_can():
    """`Law 1`: the OAuth clause is an addition, not a replacement."""
    assert mail_auth.can_send(
        {"smtp_host": "h", "smtp_user": "u", "smtp_password": "p"}
    ) is True


def test_neither_credential_cannot():
    assert mail_auth.can_send({"smtp_host": "h", "smtp_user": "u"}) is False


def test_a_host_with_no_user_cannot():
    assert mail_auth.can_send({"smtp_host": "h", "smtp_password": "p"}) is False


def test_all_three_callers_now_give_the_same_answer():
    """The actual regression guard.

    Each module is asked through **its own public name**, so this fails if any
    one of them grows a private copy of the rule again — which is exactly how
    the original defect happened.
    """
    import mcp_servers.email_server as email_server
    import routes.email_routes as email_routes

    cfg = _oauth_cfg()
    assert email_routes._smtp_ready(cfg) is True
    assert email_server._smtp_ready(cfg) is True
    assert mail_auth.can_send(cfg) is True

    starved = {"smtp_host": "h", "smtp_user": "u"}
    assert email_routes._smtp_ready(starved) is False
    assert email_server._smtp_ready(starved) is False


def test_the_itemised_form_agrees_with_the_boolean():
    """`note_routes` needs to name the missing field; same rule, two shapes.

    Stated as a property rather than as two example rows, because the way these
    drift is one being updated and not the other.
    """
    for cfg in (
        _oauth_cfg(),
        {"smtp_host": "h", "smtp_user": "u", "smtp_password": "p"},
        {"smtp_host": "h", "smtp_user": "u"},
        {"smtp_host": "h"},
        {},
    ):
        assert bool(mail_auth.missing_send_fields(cfg)) == (not mail_auth.can_send(cfg))


def test_note_routes_no_longer_carries_its_own_copy():
    source = (ROOT / "routes" / "note" / "note_routes.py").read_text(encoding="utf-8")
    assert 'cfg.get("smtp_password") or cfg.get("oauth_provider")' not in source
    assert "missing_send_fields" in source


# --------------------------------------------------------------------------
# The columns the MCP server never asked for
# --------------------------------------------------------------------------


def test_the_mcp_server_selects_the_oauth_columns():
    """Without these the account arrives looking like a blank password."""
    source = (ROOT / "mcp_servers" / "email_server.py").read_text(encoding="utf-8")
    for column in (
        "oauth_provider",
        "oauth_access_token",
        "oauth_refresh_token",
        "oauth_token_expiry",
    ):
        assert column in source, f"{column} is never read by the agent's email tools"


def test_the_mcp_server_authenticates_through_the_shared_module():
    """`Law 20`: assert the call, not a comment mentioning it."""
    source = (ROOT / "mcp_servers" / "email_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    assert "_mail_auth.authenticate_imap" in calls
    assert "_mail_auth.authenticate_smtp" in calls


def test_the_mcp_server_no_longer_calls_login_directly():
    """A direct `conn.login` is the branch that cannot do XOAUTH2."""
    source = (ROOT / "mcp_servers" / "email_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    logins = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "login"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "conn"
    ]
    assert logins == [], "a bare conn.login() cannot authenticate a linked account"


# --------------------------------------------------------------------------
# The SASL exchange, which was spelled four times
# --------------------------------------------------------------------------


def test_the_xoauth2_string_is_the_sasl_form():
    raw = mail_auth.xoauth2_raw("me@example.com", "tok")
    assert raw == "user=me@example.com\x01auth=Bearer tok\x01\x01"
    assert mail_auth.xoauth2_bytes("me@example.com", "tok") == raw.encode()


def test_the_old_names_still_resolve_to_the_new_ones():
    """Ten test files and three modules import these. `Law 1`."""
    from routes import email_helpers

    assert email_helpers._xoauth2_raw is mail_auth.xoauth2_raw
    assert email_helpers._xoauth2_bytes is mail_auth.xoauth2_bytes


def test_only_one_module_spells_the_sasl_exchange():
    """The `P18-03` guard.

    Counted across the app rather than asserted per file: the failure mode is a
    fifth copy appearing somewhere nobody thought to look.
    """
    owners = set()
    for path in ROOT.glob("**/*.py"):
        parts = path.parts
        if "tests" in parts or ".git" in parts or "library" in parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "auth=Bearer" in text:
            owners.add(path.relative_to(ROOT).as_posix())
    assert owners == {"src/mail_auth.py"}, (
        f"the XOAUTH2 string is built in {sorted(owners)}; it belongs in one place"
    )


# --------------------------------------------------------------------------
# Authenticating a connection, and the branch each account takes
# --------------------------------------------------------------------------


class _FakeIMAP:
    def __init__(self):
        self.authenticated = None
        self.logged_in = None

    def authenticate(self, mechanism, callback):
        self.authenticated = (mechanism, callback(b""))

    def login(self, user, password):
        self.logged_in = (user, password)


class _FakeSMTP:
    def __init__(self):
        self.ehloed = False
        self.authed = None
        self.logged_in = None

    def ehlo(self):
        self.ehloed = True

    def auth(self, mechanism, callback, initial_response_ok=False):
        self.authed = (mechanism, callback(), initial_response_ok)

    def login(self, user, password):
        self.logged_in = (user, password)


def test_a_linked_account_authenticates_with_xoauth2(monkeypatch):
    monkeypatch.setattr(mail_auth, "access_token_for", lambda cfg: "tok")
    conn = _FakeIMAP()
    mail_auth.authenticate_imap(conn, _oauth_cfg())
    assert conn.logged_in is None
    assert conn.authenticated[0] == "XOAUTH2"
    assert b"auth=Bearer tok" in conn.authenticated[1]


def test_a_password_account_still_uses_login(monkeypatch):
    conn = _FakeIMAP()
    mail_auth.authenticate_imap(conn, {"imap_user": "u", "imap_password": "p"})
    assert conn.logged_in == ("u", "p")
    assert conn.authenticated is None


def test_smtp_says_ehlo_before_auth(monkeypatch):
    """Without it `smtplib` has no capability list and refuses a mechanism it supports."""
    monkeypatch.setattr(mail_auth, "access_token_for", lambda cfg: "tok")
    smtp = _FakeSMTP()
    mail_auth.authenticate_smtp(smtp, _oauth_cfg())
    assert smtp.ehloed is True
    assert smtp.authed[0] == "XOAUTH2"
    assert smtp.authed[2] is True, "initial_response_ok must be set for XOAUTH2"


def test_a_relay_with_no_credentials_is_left_unauthenticated():
    """`Law 1`. A Proton Mail Bridge takes no credentials and must keep working."""
    smtp = _FakeSMTP()
    mail_auth.authenticate_smtp(smtp, {"smtp_host": "127.0.0.1", "smtp_user": "", "smtp_password": ""})
    assert smtp.authed is None and smtp.logged_in is None


def test_a_linked_account_with_no_token_says_to_reconnect(monkeypatch):
    """The recovery is a button, not a password field, so the error says so."""
    monkeypatch.setattr(mail_auth, "access_token_for", lambda cfg: None)
    with pytest.raises(mail_auth.MailAuthUnavailable) as excinfo:
        mail_auth.authenticate_imap(_FakeIMAP(), _oauth_cfg())
    assert "reconnect" in str(excinfo.value).lower()


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def test_a_live_token_is_reused_without_a_network_call(monkeypatch):
    import time

    from src.secret_storage import encrypt as _enc

    called = []
    monkeypatch.setitem(
        mail_auth._REFRESHERS, "google", lambda aid: called.append(aid) or "new"
    )
    cfg = _oauth_cfg(
        oauth_access_token=_enc("live"),
        oauth_token_expiry=str(int(time.time()) + 3600),
    )
    assert mail_auth.access_token_for(cfg) == "live"
    assert called == []


def test_a_token_inside_the_skew_window_is_refreshed(monkeypatch):
    """A token expiring mid-handshake fails as a credential error, not a timeout."""
    import time

    from src.secret_storage import encrypt as _enc

    monkeypatch.setitem(mail_auth._REFRESHERS, "google", lambda aid: "fresh")
    cfg = _oauth_cfg(
        oauth_access_token=_enc("nearly-dead"),
        oauth_token_expiry=str(int(time.time()) + mail_auth.TOKEN_SKEW_SECONDS - 5),
    )
    assert mail_auth.access_token_for(cfg) == "fresh"


def test_an_unreadable_expiry_refreshes_rather_than_gambling(monkeypatch):
    from src.secret_storage import encrypt as _enc

    monkeypatch.setitem(mail_auth._REFRESHERS, "google", lambda aid: "fresh")
    cfg = _oauth_cfg(oauth_access_token=_enc("x"), oauth_token_expiry="not-a-number")
    assert mail_auth.access_token_for(cfg) == "fresh"


def test_an_unknown_provider_gets_no_token(monkeypatch):
    """The table is the dispatch. An account nobody can refresh returns None."""
    assert mail_auth.access_token_for({"oauth_provider": "yahoo"}) is None


def test_the_refresher_table_is_late_bound(monkeypatch):
    """A table holding the function object freezes the binding at import.

    Patching `refresh_google_token` then rebinds the module global and leaves
    the table pointing at the original — which is how this was written first,
    and a test caught it.
    """
    monkeypatch.setattr(mail_auth, "refresh_google_token", lambda aid: "late")
    assert mail_auth._REFRESHERS["google"]("acct") == "late"


def test_provider_detection_ignores_case_and_whitespace():
    assert mail_auth.provider_of({"oauth_provider": " Google "}) == "google"
    assert mail_auth.provider_of({"oauth_provider": "imap"}) == ""
    assert mail_auth.provider_of({}) == ""
    assert mail_auth.provider_of(None) == ""
