# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1812`. A password longer than 72 bytes was a bare 500, and at sign-in a
username oracle.

bcrypt reads at most 72 bytes of a password, and bcrypt 5 (pinned since
2026-09-16) refuses a longer one with a ValueError instead of cutting it short.
Pantheon checked only the 8-character minimum, so a long passphrase, or 19
emoji (76 bytes), answered 500 at setup, sign-up, change-password and the
admin's Add user with nothing said, `scripts/reset_password.py` died with a
traceback, and `setup.py` passed on bcrypt's advice to truncate. At sign-in the
error came only for an account that exists, because an unknown name returned
before bcrypt ran, so one request told anyone whether a username was real,
which `test_auth_audit_log.py` says a sign-in never does.

Now each door that sets a password refuses one over 72 bytes in words, a long
password at sign-in or as the current password is a wrong password like any
other, and a sign-in for an account that does not exist spends the bcrypt
check a wrong password costs. A password of exactly 72 bytes is still taken.
Upstream Odysseus has the same fix open as PR #5917; its checks (a clean 400
past 72 bytes, a valid password still accepted) are among these.

Driven: the real route handlers and a real `AuthManager` on a real
`auth.json`, with real bcrypt at its cheapest cost, not the `hash:` stand-ins
other auth tests use, which never raise.
"""
import asyncio
import importlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.auth as _auth_when_collected
import core.database as core_db
from core.database import Base, Event
from src import events as ev

ROOT = Path(__file__).resolve().parents[1]

# Taken when this file is collected, before any test runs: several auth tests
# replace these two with `hash:` stand-ins and never put them back.
_REAL_HASH = _auth_when_collected._hash_password
_REAL_VERIFY = _auth_when_collected._verify_password

PASSWORD = "correct horse battery"
LONG = "x" * 73                # one byte more than bcrypt takes
EMOJI = "\U0001F511" * 19      # 19 characters, past the 8-character minimum, and 76 bytes
EDGE = "y" * 72                # exactly what bcrypt takes
TOO_LONG = [pytest.param(LONG, id="73-bytes"), pytest.param(EMOJI, id="19-emoji")]
NO_COOKIE = SimpleNamespace(set_cookie=lambda **kw: None)


@pytest.fixture
def auth(monkeypatch):
    """`core.auth` as it is now, with real bcrypt at its cheapest cost."""
    assert (_REAL_HASH.__name__, _REAL_VERIFY.__name__) == ("_hash_password", "_verify_password")
    module = importlib.import_module("core.auth")
    monkeypatch.setattr(module, "_hash_password", _REAL_HASH)
    monkeypatch.setattr(module, "_verify_password", _REAL_VERIFY)
    gensalt = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, "gensalt", lambda rounds=4, prefix=b"2b": gensalt(rounds, prefix))
    return module


@pytest.fixture
def audit(tmp_path, monkeypatch):
    """The audit table, in a private SQLite file (as `test_auth_audit_log.py`)."""
    engine = create_engine(f"sqlite:///{tmp_path}/audit.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    ev._last_prune = 0.0
    yield maker
    engine.dispose()


def _accounts(auth, tmp_path, *, signup=False):
    """Ada, the admin, on a real auth.json."""
    mgr = auth.AuthManager(str(tmp_path / "auth.json"))
    assert mgr.setup("ada", PASSWORD)
    mgr.signup_enabled = signup
    return mgr


def _endpoint(mgr, path):
    from routes.auth_routes import setup_auth_routes
    for route in setup_auth_routes(mgr).routes:
        if getattr(route, "path", "") == path and "POST" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"POST {path} not registered")


def _request(mgr, user=None, token=None):
    return SimpleNamespace(
        cookies={"pantheon_session": token} if token else {},
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
        url=SimpleNamespace(scheme="http"),
        state=SimpleNamespace(current_user=user),
        app=SimpleNamespace(state=SimpleNamespace(auth_manager=mgr)),
    )


def _login_reasons(maker):
    db = maker()
    try:
        rows = (db.query(Event).filter(Event.kind == ev.AUTH_EVENT_KIND, Event.name == "login")
                .order_by(Event.id).all())
        return [json.loads(row.detail or "{}").get("reason") for row in rows]
    finally:
        db.close()


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("password", TOO_LONG)
def test_a_long_password_at_sign_in_is_a_wrong_one_whether_the_name_is_real_or_not(
        auth, audit, tmp_path, password):
    from routes.auth_routes import LoginRequest
    mgr = _accounts(auth, tmp_path)
    login = _endpoint(mgr, "/api/auth/login")

    answers = []
    for name in ("ada", "ghost"):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(login(body=LoginRequest(username=name, password=password),
                              request=_request(mgr), response=NO_COOKIE))
        answers.append((refused.value.status_code, refused.value.detail))

    assert answers == [(401, "Invalid credentials")] * 2
    assert _login_reasons(audit) == ["invalid_credentials"] * 2


def test_a_name_that_does_not_exist_costs_the_check_a_wrong_password_costs(auth, tmp_path, monkeypatch):
    mgr = _accounts(auth, tmp_path)
    checked = []

    def counting(password, hashed):
        checked.append(hashed)
        return _REAL_VERIFY(password, hashed)

    monkeypatch.setattr(auth, "_verify_password", counting)

    assert mgr.verify_password("ghost", "whatever-123") is False
    assert mgr.verify_password("ada", "wrong-password") is False
    # One bcrypt check each, so the time an answer takes does not tell them apart.
    assert len(checked) == 2
    assert checked[0].startswith("$2b$") and checked[0] != mgr.users["ada"]["password_hash"]


def test_change_password_with_a_long_password_answers_in_words_and_changes_nothing(auth, tmp_path):
    from routes.auth_routes import ChangePasswordRequest
    mgr = _accounts(auth, tmp_path)
    change = _endpoint(mgr, "/api/auth/change-password")
    request = _request(mgr, token=mgr.create_session_trusted("ada"))

    for current, new, said in ((LONG, "new-password-22", "Current password is incorrect"),
                               (PASSWORD, EMOJI, "at most 72 bytes")):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(change(body=ChangePasswordRequest(current_password=current, new_password=new),
                               request=request))
        assert refused.value.status_code == 400
        assert said in refused.value.detail

    assert mgr.verify_password("ada", PASSWORD), "the password is the one it was"


@pytest.mark.parametrize("password", TOO_LONG)
@pytest.mark.parametrize("door", ["setup", "signup", "add-user"])
def test_every_door_that_sets_a_password_refuses_one_over_72_bytes_in_words(auth, tmp_path, door, password):
    from routes.auth_routes import CreateUserRequest, SetupRequest, SignupRequest
    if door == "setup":
        mgr = auth.AuthManager(str(tmp_path / "auth.json"))
        path, kwargs = "/api/auth/setup", dict(
            body=SetupRequest(username="ada", password=password), request=_request(mgr))
    elif door == "signup":
        mgr = _accounts(auth, tmp_path, signup=True)
        path, kwargs = "/api/auth/signup", dict(
            body=SignupRequest(username="cy", password=password), request=_request(mgr))
    else:
        mgr = _accounts(auth, tmp_path)
        path, kwargs = "/api/auth/users", dict(
            body=CreateUserRequest(username="cy", password=password), request=_request(mgr, user="ada"))
    accounts = set(mgr.users)

    with pytest.raises(HTTPException) as refused:
        asyncio.run(_endpoint(mgr, path)(**kwargs))

    assert refused.value.status_code == 400
    assert "at most 72 bytes" in refused.value.detail
    assert set(mgr.users) == accounts, "no account was made"


def test_a_password_of_exactly_72_bytes_is_still_set_and_signs_in(auth, tmp_path):
    from routes.auth_routes import LoginRequest, SetupRequest
    mgr = auth.AuthManager(str(tmp_path / "auth.json"))

    made = asyncio.run(_endpoint(mgr, "/api/auth/setup")(
        body=SetupRequest(username="ada", password=EDGE), request=_request(mgr)))
    signed_in = asyncio.run(_endpoint(mgr, "/api/auth/login")(
        body=LoginRequest(username="ada", password=EDGE), request=_request(mgr), response=NO_COOKIE))

    assert made["ok"] is True and signed_in["ok"] is True


def test_the_policy_says_how_many_bytes_a_password_may_have(auth, tmp_path):
    assert auth.AuthManager(str(tmp_path / "auth.json")).policy()["password_max_bytes"] == 72


def test_the_reset_script_refuses_a_long_password_in_words(auth, tmp_path, capsys):
    reset = _load("reset_password_under_test", ROOT / "scripts" / "reset_password.py")
    _accounts(auth, tmp_path)

    code = reset.main(["ada", "--password-stdin"], stdin=io.StringIO(LONG + "\n"),
                      auth_path=str(tmp_path / "auth.json"))

    assert code == 1
    said = capsys.readouterr().err
    assert "at most 72 bytes" in said and "Nothing was changed" in said
    assert auth.AuthManager(str(tmp_path / "auth.json")).verify_password("ada", PASSWORD)


def test_setup_py_refuses_a_long_admin_password_in_words(auth, tmp_path, monkeypatch, capsys):
    setup_module = _load("pantheon_setup_under_test", ROOT / "setup.py")
    monkeypatch.setattr(setup_module, "AUTH_FILE", str(tmp_path / "auth.json"))
    monkeypatch.setenv("PANTHEON_ADMIN_USER", "ada")
    monkeypatch.setenv("PANTHEON_ADMIN_PASSWORD", EMOJI)

    assert setup_module.create_default_admin() == "failed"
    assert "at most 72 bytes" in capsys.readouterr().out
    assert not (tmp_path / "auth.json").exists()

    # Asked at the terminal, it says so and asks again.
    typed = iter([LONG, PASSWORD, PASSWORD])
    monkeypatch.setattr("builtins.input", lambda prompt="": "ada")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(typed))
    assert setup_module._prompt_admin_credentials() == ("ada", PASSWORD)
    assert "at most 72 bytes" in capsys.readouterr().out
