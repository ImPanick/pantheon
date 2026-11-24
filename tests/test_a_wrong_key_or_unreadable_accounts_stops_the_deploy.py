# SPDX-License-Identifier: AGPL-3.0-or-later
"""A wrong `.app_key` or an unreadable `auth.json` is said, not suffered.

Cybertooth, 2026-11-24: after a rebuild every sign-in answered "Invalid
credentials" and LM Studio refused Pantheon's API key, and nothing in Pantheon
said why. Both are the same shape: the app could not read what it had saved,
and degraded quietly. An unreadable account file looked like a wrong password;
a key that is not the one the secrets were sealed with turned every saved API
key into "" and the provider's 401 was the first sign.

Now `/api/ready` (the compose healthcheck and any deploy gate) fails on either
and names it, startup logs it, sign-in answers 503 with the reason instead of
401, and a repaired file is picked up without a restart.
"""

import json
import logging

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import core.auth as A
import src.readiness as R
import src.secret_storage as SS


@pytest.fixture
def key_at(tmp_path, monkeypatch):
    """Point the key store at a file of the test's own; return a writer."""
    path = tmp_path / ".app_key"
    monkeypatch.setattr(SS, "_KEY_PATH", path)
    monkeypatch.setattr(SS, "_fernet", None)

    def write(key: bytes):
        path.write_bytes(key)
        monkeypatch.setattr(SS, "_fernet", None)
        return key
    return write


@pytest.fixture
def secrets_db(tmp_path, monkeypatch):
    """A database of the app's own tables, with one saved endpoint key slot."""
    from core.database import Base
    import core.database as D

    eng = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(D, "engine", eng)

    def save_endpoint_key(sealed: str):
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO model_endpoints (id, name, base_url, api_key, created_at, updated_at) "
                "VALUES ('lm', 'LM Studio', 'http://host.docker.internal:1234/v1', :k, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {"k": sealed})
    return save_endpoint_key


def _sealed_with(key: bytes, secret: str = "lm-studio-key") -> str:
    return "enc:" + Fernet(key).encrypt(secret.encode()).decode()


# ── the key ────────────────────────────────────────────────────────────────

def test_secrets_sealed_with_another_key_fail_the_check_and_name_the_column(key_at, secrets_db):
    key_at(Fernet.generate_key())
    secrets_db(_sealed_with(Fernet.generate_key()))

    result = R.check_secrets(fresh=True)

    assert result["ok"] is False
    assert result["undecryptable"] == {"model_endpoints.api_key": 1}
    assert "model_endpoints.api_key" in result["error"]
    assert "not the one they were saved with" in result["error"]


def test_secrets_sealed_with_this_key_pass(key_at, secrets_db):
    key = key_at(Fernet.generate_key())
    secrets_db(_sealed_with(key))

    result = R.check_secrets(fresh=True)

    assert result["ok"] is True, result
    assert result["checked"] == 1


def test_a_key_file_that_cannot_be_read_is_named_not_turned_into_empty_secrets(
        tmp_path, monkeypatch, secrets_db, caplog):
    unreadable = tmp_path / "keydir"
    unreadable.mkdir()           # reading a directory fails the way a denied file does
    monkeypatch.setattr(SS, "_KEY_PATH", unreadable)
    monkeypatch.setattr(SS, "_fernet", None)

    with pytest.raises(SS.KeyUnavailable):
        SS._get_fernet()
    with caplog.at_level(logging.ERROR, logger=SS.logger.name):
        assert SS.decrypt(_sealed_with(Fernet.generate_key())) == ""
    assert "can't read it" in caplog.text

    result = R.check_secrets(fresh=True)
    assert result["ok"] is False
    assert "can't read it" in result["error"]
    assert unreadable.is_dir(), "a key that can't be read is never replaced"


def test_a_damaged_key_is_refused_rather_than_used(key_at):
    key_at(b"not a fernet key")
    with pytest.raises(SS.KeyUnavailable, match="not a usable key"):
        SS._get_fernet()


def test_a_repaired_key_is_used_without_a_restart(key_at):
    original = Fernet.generate_key()
    sealed = _sealed_with(original, "kept")
    key_at(b"not a fernet key")
    assert SS.decrypt(sealed) == ""

    key_at(original)
    assert SS.decrypt(sealed) == "kept"


def test_the_verdict_is_cached_so_a_health_probe_stays_cheap(key_at, secrets_db, monkeypatch):
    key = key_at(Fernet.generate_key())
    secrets_db(_sealed_with(key))
    assert R.check_secrets(fresh=True)["ok"] is True

    monkeypatch.setattr(SS, "_get_fernet", lambda: pytest.fail("cached verdict should be reused"))
    assert R.check_secrets()["ok"] is True


# ── the accounts ───────────────────────────────────────────────────────────

@pytest.fixture
def broken_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "_hash_password", lambda pw: f"hash:{pw}")
    monkeypatch.setattr(A, "_verify_password", lambda pw, h: h == f"hash:{pw}")
    path = tmp_path / "auth.json"
    good = {"users": {"panick": {"password_hash": "hash:right-password", "is_admin": True}}}
    path.write_text("{ this is not json", encoding="utf-8")
    mgr = A.AuthManager(str(path))
    assert mgr.load_error

    def repair():
        path.write_text(json.dumps(good), encoding="utf-8")
    return mgr, repair


def test_an_unreadable_account_file_fails_readiness_with_the_reason(broken_accounts, key_at, secrets_db):
    mgr, _ = broken_accounts
    key_at(Fernet.generate_key())

    report = R.check_readiness(mgr)

    assert report["ready"] is False
    assert report["checks"]["accounts"]["ok"] is False
    assert "could not be read" in report["checks"]["accounts"]["error"]


def test_a_repaired_account_file_is_read_again_without_a_restart(broken_accounts):
    mgr, repair = broken_accounts
    assert mgr.retry_load() is False
    assert mgr.load_error

    repair()
    assert mgr.retry_load() is True
    assert mgr.load_error is None
    assert mgr.verify_password("panick", "right-password")
    mgr.signup_enabled = False   # writes are allowed again once the file is read


def _login_client(mgr, monkeypatch):
    import routes.auth_routes as AR

    async def _no_audit(*a, **k):
        return None
    monkeypatch.setattr(AR, "_audit", _no_audit)
    app = FastAPI()
    app.include_router(AR.setup_auth_routes(mgr))
    return TestClient(app)


def test_sign_in_says_the_accounts_cant_be_read_instead_of_wrong_password(broken_accounts, monkeypatch):
    mgr, _ = broken_accounts
    client = _login_client(mgr, monkeypatch)

    r = client.post("/api/auth/login", json={"username": "panick", "password": "right-password"})

    assert r.status_code == 503
    assert "can't read its account file" in r.json()["detail"]


def test_sign_in_works_once_the_file_is_repaired(broken_accounts, monkeypatch):
    mgr, repair = broken_accounts
    client = _login_client(mgr, monkeypatch)
    repair()

    r = client.post("/api/auth/login", json={"username": "panick", "password": "right-password"})

    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
