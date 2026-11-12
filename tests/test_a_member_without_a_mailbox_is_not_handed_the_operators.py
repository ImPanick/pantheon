# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit 2026-11-11 #10. A member with no mail account got the operator's.

`_get_email_config` fell back, for any owner with no `email_accounts` row, to
the install's own mailbox: the flat keys in `settings.json`, then `IMAP_*` /
`SMTP_*` from the environment, credentials included. Measured on
`dev@ad4aac6`: a member's `GET /api/email/config` answered the operator's
host, user and address, and the config every IMAP read and SMTP send is made
from carried the operator's passwords.

The install's own mailbox is the admin's, and the system's (a poller asks with
no owner). A member with no account of their own has no mailbox configured.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ADMIN, MEMBER = "alice", "bob"
SECRETS = ("op-imap-secret", "op-smtp-secret")


class _Auth:
    is_configured = True

    def get_privileges(self, name):
        return {}

    def is_admin(self, name):
        return name == ADMIN


@pytest.fixture(autouse=True)
def operator_mailbox(monkeypatch, tmp_path):
    """The install's mailbox in the environment, no `settings.json` mail keys,
    an empty accounts table, and two people."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import core.database as D
    import src.settings as S

    for key, value in dict(IMAP_HOST="imap.operator.example", IMAP_USER="ops@operator.example",
                           IMAP_PASSWORD=SECRETS[0], SMTP_HOST="smtp.operator.example",
                           SMTP_USER="ops@operator.example", SMTP_PASSWORD=SECRETS[1],
                           EMAIL_FROM="ops@operator.example").items():
        monkeypatch.setenv(key, value)
    sp = tmp_path / "settings.json"
    sp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    S._invalidate_caches()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    D.Base.metadata.create_all(engine)
    monkeypatch.setattr(D, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr("src.auth_manager_access.shared_auth_manager", lambda: _Auth())
    yield
    S._invalidate_caches()
    engine.dispose()


def _get(who):
    import routes.email_routes as E
    from routes.email_helpers import require_owner, require_user
    app = FastAPI()
    app.include_router(E.setup_email_routes())
    app.dependency_overrides[require_owner] = lambda: who
    app.dependency_overrides[require_user] = lambda: who
    r = TestClient(app, raise_server_exceptions=False).get("/api/email/config")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_member_with_no_account_is_shown_no_mailbox():
    shown = _get(MEMBER)
    for key in ("imap_host", "imap_user", "smtp_host", "smtp_user", "from_address"):
        assert not shown.get(key), f"a member was shown the operator's {key}: {shown.get(key)!r}"


def test_a_member_with_no_account_connects_and_sends_as_nobody():
    """What every IMAP read and SMTP send for them is made from."""
    from routes.email_helpers import _get_email_config
    cfg = _get_email_config(None, owner=MEMBER)
    leaked = [k for k, v in cfg.items() if isinstance(v, str) and (
        v in SECRETS or "operator.example" in v)]
    assert not leaked, f"a member's mail config carries the operator's {leaked}"


def _agent_config(monkeypatch, who):
    """The agent's mail tools' own resolver (`mcp_servers/email_server.py`), on
    an install whose accounts table is empty."""
    import mcp_servers.email_server as email_server
    monkeypatch.setattr(email_server, "_read_accounts_from_db", lambda: [])
    monkeypatch.setattr(email_server, "_ACCOUNT_CACHE", {})
    token = email_server._CURRENT_OWNER.set(who)
    try:
        return email_server._load_config()
    finally:
        email_server._CURRENT_OWNER.reset(token)


def test_a_members_agent_does_not_read_or_send_from_the_operators_mailbox(monkeypatch):
    try:
        cfg = _agent_config(monkeypatch, MEMBER)
    except ValueError:
        return   # refused: no mailbox for them, which is the answer
    leaked = [k for k, v in cfg.items() if isinstance(v, str) and (
        v in SECRETS or "operator.example" in v)]
    assert not leaked, f"a member's agent mail config carries the operator's {leaked}"


# ── still the install's ───────────────────────────────────────────────────────

def test_the_admins_agent_still_has_the_install_mailbox(monkeypatch):
    cfg = _agent_config(monkeypatch, ADMIN)
    assert cfg["imap_host"] == "imap.operator.example"
    assert cfg["smtp_password"] == SECRETS[1]

def test_the_admin_still_has_the_install_mailbox():
    from routes.email_helpers import _get_email_config
    cfg = _get_email_config(None, owner=ADMIN)
    assert cfg["imap_host"] == "imap.operator.example"
    assert cfg["imap_password"] == SECRETS[0]
    assert _get(ADMIN)["imap_user"] == "ops@operator.example"


def test_a_poller_asking_for_no_one_still_has_the_install_mailbox():
    from routes.email_helpers import _get_email_config
    cfg = _get_email_config(None)
    assert cfg["smtp_host"] == "smtp.operator.example"
    assert cfg["smtp_password"] == SECRETS[1]
