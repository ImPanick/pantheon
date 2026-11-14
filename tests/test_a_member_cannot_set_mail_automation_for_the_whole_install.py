# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit 2026-11-11 #9. A member could change every mailbox's automation.

`PUT /api/email/config` without `account_id` wrote the install-wide settings
every mailbox poller reads: auto-reply (its message and subject), auto-spam,
auto-tag, auto-summarize, auto-calendar. `PUT /api/email/style` without
`account_id` wrote the shared writing style every account without its own
falls back to. Any signed-in person could do either. Measured on
`dev@ad4aac6`: a member's PUT answered 200 and the admin's own mailbox then
had an away reply active, carrying the member's message.

The install-wide settings are the admin's. A member still saves their own
account's away reply and writing style (`account_id` names an account they
own), and their own default account's server details.

Every case drives the real router; only the signed-in person is stood in for.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ADMIN, MEMBER, OPERATOR = "alice", "bob", "carol"


class _Auth:
    is_configured = True

    def get_privileges(self, name):
        # As the real manager answers: an admin holds every privilege.
        from core.auth import ADMIN_PRIVILEGES
        if name == ADMIN:
            return dict(ADMIN_PRIVILEGES)
        return {"can_run_instance": True} if name == OPERATOR else {}

    def is_admin(self, name):
        return name == ADMIN


@pytest.fixture
def store(tmp_path, monkeypatch):
    import src.settings as S
    import routes.email_helpers as EH

    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({
        "email_auto_reply": False,
        "email_auto_spam": False,
        "email_auto_tag": False,
        "email_writing_style": "the admin's style",
    }), encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    monkeypatch.setattr(EH, "SETTINGS_FILE", sp, raising=False)
    S._invalidate_caches()
    yield S
    S._invalidate_caches()


@pytest.fixture
def db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import core.database as D

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    D.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(D, "SessionLocal", factory)
    with factory() as s:
        s.add(D.EmailAccount(id="alice-acct", owner=ADMIN, name="Alice", is_default=True,
                             enabled=True, imap_host="imap.example.com", imap_user="alice@example.com"))
        s.add(D.EmailAccount(id="bob-acct", owner=MEMBER, name="Bob", is_default=True,
                             enabled=True, imap_host="imap.example.com", imap_user="bob@example.com"))
        s.commit()
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def auth(monkeypatch):
    monkeypatch.setattr("src.auth_manager_access.shared_auth_manager", lambda: _Auth())


def _client(who):
    import routes.email_routes as E
    from routes.email_helpers import require_owner, require_user
    app = FastAPI()
    app.include_router(E.setup_email_routes())
    app.dependency_overrides[require_owner] = lambda: who
    app.dependency_overrides[require_user] = lambda: who
    return TestClient(app, raise_server_exceptions=False)


def _on_disk(S):
    return json.loads(Path(S.SETTINGS_FILE).read_text(encoding="utf-8"))


AWAY = {"email_auto_reply": True,
        "email_auto_reply_message": "I have moved; send invoices to the new address"}


@pytest.mark.parametrize("change", [
    AWAY,
    {"email_auto_spam": True},
    {"email_auto_tag": True},
    {"email_auto_summarize": True},
    {"email_auto_calendar": True},
], ids=["away-reply", "auto-spam", "auto-tag", "auto-summarize", "auto-calendar"])
def test_a_member_cannot_change_the_install_wide_mail_automation(store, db, change):
    from routes.email_helpers import _load_settings
    from routes.email_pollers import _effective_settings_for_email_account, _away_reply_active

    before = _on_disk(store)
    r = _client(MEMBER).put("/api/email/config", json=change)
    assert r.status_code == 403, r.text
    assert _on_disk(store) == before, "a refused change was written anyway"
    eff = _effective_settings_for_email_account(_load_settings(), "alice-acct")
    assert not _away_reply_active(eff, "alice-acct")


def test_a_members_away_settings_cannot_ride_along_with_their_own_account(store, db):
    """The four automation flags are install-wide even when `account_id`
    names the member's own account, so naming it does not open them."""
    before = _on_disk(store)
    r = _client(MEMBER).put("/api/email/config?account_id=bob-acct", json={"email_auto_spam": True})
    assert r.status_code == 403, r.text
    assert _on_disk(store) == before


def test_a_member_cannot_change_the_shared_writing_style(store, db):
    r = _client(MEMBER).put("/api/email/style", json={"style": "sign every mail as the admin"})
    assert r.status_code == 403, r.text
    assert _on_disk(store)["email_writing_style"] == "the admin's style"


# ── still allowed ─────────────────────────────────────────────────────────────

def test_a_member_still_sets_the_away_reply_on_their_own_account(store, db):
    from routes.email_helpers import _load_settings
    from routes.email_pollers import _effective_settings_for_email_account, _away_reply_active

    r = _client(MEMBER).put("/api/email/config?account_id=bob-acct", json=AWAY)
    assert r.status_code == 200, r.text
    s = _load_settings()
    assert _away_reply_active(_effective_settings_for_email_account(s, "bob-acct"), "bob-acct")
    assert not _away_reply_active(_effective_settings_for_email_account(s, "alice-acct"), "alice-acct")


def test_a_member_still_sets_their_own_accounts_writing_style(store, db):
    r = _client(MEMBER).put("/api/email/style?account_id=bob-acct", json={"style": "short and plain"})
    assert r.status_code == 200, r.text
    on_disk = _on_disk(store)
    assert on_disk["email_writing_style"] == "the admin's style"
    assert "short and plain" in json.dumps(on_disk.get("email_writing_styles_by_account"))


def test_a_member_still_saves_their_own_server_details(store, db):
    r = _client(MEMBER).put("/api/email/config", json={"imap_host": "mail.example.org", "imap_port": 993})
    assert r.status_code == 200, r.text


def test_an_admin_still_sets_the_install_wide_automation(store, db):
    r = _client(ADMIN).put("/api/email/config", json={**AWAY, "email_auto_spam": True})
    assert r.status_code == 200, r.text
    on_disk = _on_disk(store)
    assert on_disk["email_auto_reply"] is True and on_disk["email_auto_spam"] is True
    r = _client(ADMIN).put("/api/email/style", json={"style": "the admin's new style"})
    assert r.status_code == 200, r.text
    assert _on_disk(store)["email_writing_style"] == "the admin's new style"


def test_someone_an_admin_lets_run_this_pantheon_sets_it_too(store, db):
    """The gate is the operator tier (`can_run_instance`, `B683`), asked
    through the one privilege resolver rather than as a further admin
    decision (`.pantheon/check-auth-map.py` rule C)."""
    r = _client(OPERATOR).put("/api/email/config", json={"email_auto_spam": True})
    assert r.status_code == 200, r.text
    assert _on_disk(store)["email_auto_spam"] is True
