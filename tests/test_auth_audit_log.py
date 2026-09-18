# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P11-08` — logins, role changes, privilege grants and failures are written
down, into the table that already exists.

The row says *feeds `D-05`'s telemetry table rather than inventing a second
store*. `D-05` is a parked decision; the table it argued for was built by
`P14-01` and is `core.database.Event`, written through `src.events`. So this is
`record_event` with a fixed `kind`, and these tests read the rows back out of a
real SQLite database rather than asserting that a function was called — a mock
would pass whether or not anything reached a table (`Law 20`).

Every test drives a real route handler with a real `AuthManager` on a real
`auth.json`. The four things that would make an audit log worthless are each
pinned:

  * a refusal is recorded as a refusal, not omitted;
  * an admin action records who did it AND who it was done to;
  * a credential never reaches a row;
  * a database with no `events` table does not take the login route down with
    it (`Law 20` again, and the trap `P8-25` fell into: the write path has to
    be proved against a database created *without* the new thing).
"""
import asyncio
import importlib
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from types import SimpleNamespace

import core.database as core_db
from core.database import Base, Event
from src import events as ev
from src import roles as roles_mod


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    """A private file-backed database per test.

    `sqlite:///:memory:` gives every new connection a fresh empty database, so
    a table created here is simply absent the next time `SessionLocal()` opens
    one — `tests/test_events_table.py` records ten tests that passed alone for
    that reason and failed in a full run.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/audit.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    ev._last_prune = 0.0
    yield maker
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_leaked_provider():
    roles_mod.clear_role_layer()
    yield
    roles_mod.clear_role_layer()


def _rows(maker, action=None):
    db = maker()
    try:
        q = db.query(Event).filter(Event.kind == ev.AUTH_EVENT_KIND)
        if action:
            q = q.filter(Event.name == action)
        return list(q.order_by(Event.id).all())
    finally:
        db.close()


def _detail(row):
    return json.loads(row.detail) if row.detail else {}


def _mgr(tmp_path):
    auth_mod = importlib.import_module("core.auth")
    auth_mod._hash_password = lambda password: f"hash:{password}"
    auth_mod._verify_password = lambda password, hashed: hashed == f"hash:{password}"
    mgr = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    mgr.create_user("admin", "pw-123456", is_admin=True)
    mgr.create_user("bob", "pw-123456")
    return mgr


def _endpoint(mgr, path, method):
    from routes.auth_routes import setup_auth_routes
    router = setup_auth_routes(mgr)
    for route in router.routes:
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} not registered")


def _request(mgr, user="admin", token="tok"):
    """A request shaped like the one `require_admin` and `_get_current_user`
    each read — the two gates the auth routes actually use."""
    return SimpleNamespace(
        cookies={"pantheon_session": token},
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
        url=SimpleNamespace(scheme="http"),
        state=SimpleNamespace(current_user=user),
        app=SimpleNamespace(state=SimpleNamespace(auth_manager=mgr)),
    )


# ---------------------------------------------------------------------------
# logins
# ---------------------------------------------------------------------------

def test_a_successful_login_writes_one_row_naming_the_account(tmp_path, _db):
    from routes.auth_routes import LoginRequest

    mgr = _mgr(tmp_path)
    login = _endpoint(mgr, "/api/auth/login", "POST")
    response = SimpleNamespace(set_cookie=lambda **kw: None)

    out = asyncio.run(login(body=LoginRequest(username="Bob", password="pw-123456"),
                            request=_request(mgr), response=response))
    assert out["ok"] is True

    rows = _rows(_db, "login")
    assert len(rows) == 1
    assert rows[0].owner == "bob"
    assert rows[0].outcome == "ok"


def test_a_refused_login_is_recorded_as_a_refusal_with_its_reason(tmp_path, _db):
    from fastapi import HTTPException
    from routes.auth_routes import LoginRequest

    mgr = _mgr(tmp_path)
    login = _endpoint(mgr, "/api/auth/login", "POST")
    response = SimpleNamespace(set_cookie=lambda **kw: None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(login(body=LoginRequest(username="bob", password="wrong"),
                          request=_request(mgr), response=response))
    assert exc.value.status_code == 401

    rows = _rows(_db, "login")
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert _detail(rows[0])["reason"] == "invalid_credentials"


def test_a_login_for_an_account_that_does_not_exist_reads_the_same(tmp_path, _db):
    """No username oracle. Every admin can read this table."""
    from fastapi import HTTPException
    from routes.auth_routes import LoginRequest

    mgr = _mgr(tmp_path)
    login = _endpoint(mgr, "/api/auth/login", "POST")
    response = SimpleNamespace(set_cookie=lambda **kw: None)

    with pytest.raises(HTTPException):
        asyncio.run(login(body=LoginRequest(username="ghost", password="whatever"),
                          request=_request(mgr), response=response))

    rows = _rows(_db, "login")
    assert len(rows) == 1
    assert _detail(rows[0])["reason"] == "invalid_credentials"


def test_a_logout_names_the_session_it_ended(tmp_path, _db):
    mgr = _mgr(tmp_path)
    token = mgr.create_session_trusted("bob")
    logout = _endpoint(mgr, "/api/auth/logout", "POST")
    response = SimpleNamespace(delete_cookie=lambda *a, **kw: None)

    asyncio.run(logout(request=_request(mgr, token=token), response=response))

    rows = _rows(_db, "logout")
    assert len(rows) == 1
    assert rows[0].owner == "bob"


# ---------------------------------------------------------------------------
# role changes and privilege grants
# ---------------------------------------------------------------------------

def test_a_role_change_records_who_did_it_and_who_it_was_done_to(tmp_path, _db):
    from routes.auth_routes import DefineRoleRequest, SetUserRoleRequest

    mgr = _mgr(tmp_path)
    define = _endpoint(mgr, "/api/auth/roles/{name}", "PUT")
    assign = _endpoint(mgr, "/api/auth/users/{username}/role", "PUT")

    asyncio.run(define(name="operator",
                       body=DefineRoleRequest(overrides={"can_use_bash": True}),
                       request=_request(mgr)))
    asyncio.run(assign(username="bob", body=SetUserRoleRequest(role="operator"),
                       request=_request(mgr)))

    defined = _rows(_db, "role_define")
    assert len(defined) == 1
    assert defined[0].owner == "admin"
    assert _detail(defined[0])["subject"] == "operator"
    assert _detail(defined[0])["overrides"] == {"can_use_bash": True}

    changed = _rows(_db, "role_change")
    assert len(changed) == 1
    assert changed[0].owner == "admin"          # who did it
    assert _detail(changed[0])["subject"] == "bob"   # who it was done to
    assert _detail(changed[0])["role"] == "operator"


def test_a_rejected_role_definition_is_recorded_as_a_failure(tmp_path, _db):
    from fastapi import HTTPException
    from routes.auth_routes import DefineRoleRequest

    mgr = _mgr(tmp_path)
    define = _endpoint(mgr, "/api/auth/roles/{name}", "PUT")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(define(name="typo",
                           body=DefineRoleRequest(overrides={"can_use_bsah": True}),
                           request=_request(mgr)))
    assert exc.value.status_code == 400

    rows = _rows(_db, "role_define")
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert "can_use_bsah" in _detail(rows[0])["reason"]


def test_a_privilege_grant_records_the_keys_that_moved(tmp_path, _db):
    mgr = _mgr(tmp_path)
    update = _endpoint(mgr, "/api/auth/users/{username}/privileges", "PUT")

    class _Req(SimpleNamespace):
        async def json(self):
            return {"can_use_bash": True, "can_use_research": None}

    req = _Req(cookies={"pantheon_session": "tok"},
               client=SimpleNamespace(host="127.0.0.1"), headers={},
               state=SimpleNamespace(current_user="admin"),
               app=SimpleNamespace(state=SimpleNamespace(auth_manager=mgr)))
    mgr.get_username_for_token = lambda tok: "admin"

    asyncio.run(update(username="bob", request=req))

    rows = _rows(_db, "privilege_change")
    assert len(rows) == 1
    assert rows[0].owner == "admin"
    detail = _detail(rows[0])
    assert detail["subject"] == "bob"
    assert detail["set"] == {"can_use_bash": True}
    assert detail["cleared"] == ["can_use_research"]


def test_promoting_someone_to_admin_is_recorded(tmp_path, _db):
    from routes.auth_routes import SetAdminRequest

    mgr = _mgr(tmp_path)
    set_admin = _endpoint(mgr, "/api/auth/users/{username}/admin", "PUT")
    mgr.get_username_for_token = lambda tok: "admin"

    asyncio.run(set_admin(username="bob", body=SetAdminRequest(is_admin=True),
                          request=_request(mgr)))

    rows = _rows(_db, "admin_change")
    assert len(rows) == 1
    assert rows[0].outcome == "ok"
    assert _detail(rows[0]) == {"is_admin": True, "subject": "bob"}


# ---------------------------------------------------------------------------
# the two ways an audit log does damage
# ---------------------------------------------------------------------------

def test_a_credential_never_reaches_a_row():
    """Rule 2 of `src/events.py`, enforced rather than requested.

    The function holding a password is the function recording the login, so a
    deny-list beats a docstring asking every future caller to remember.
    """
    cleaned = ev._audit_detail({
        "password": "hunter2", "totp_code": "123456",
        "session_token": "abc", "api_key": "sk-1", "Authorization": "Bearer x",
        "reason": "invalid_credentials", "subject": "bob",
    })
    assert cleaned["reason"] == "invalid_credentials"
    assert cleaned["subject"] == "bob"
    for key in ("password", "totp_code", "session_token", "api_key", "Authorization"):
        assert cleaned[key] == "[redacted]"
    assert "hunter2" not in json.dumps(cleaned)


def test_a_database_with_no_events_table_does_not_break_a_login(tmp_path, monkeypatch):
    """`Law 20`, and `P8-25`'s trap: prove the write path against a database
    created WITHOUT the thing it writes to.

    An install upgraded from before `P14-01` has no `events` table. A login has
    to keep working there, and it has to keep working without the caller having
    to check a return value.
    """
    from routes.auth_routes import LoginRequest

    engine = create_engine(f"sqlite:///{tmp_path}/bare.db",
                           connect_args={"check_same_thread": False})
    # Deliberately NOT Base.metadata.create_all — this database has no tables.
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", maker)
    ev._last_prune = 0.0

    mgr = _mgr(tmp_path)
    login = _endpoint(mgr, "/api/auth/login", "POST")
    response = SimpleNamespace(set_cookie=lambda **kw: None)

    out = asyncio.run(login(body=LoginRequest(username="bob", password="pw-123456"),
                            request=_request(mgr), response=response))

    assert out["ok"] is True
    assert ev.record_auth_event("login", actor="bob") is False
    engine.dispose()


def test_auth_rows_share_the_one_table_and_the_one_retention_window(tmp_path, _db):
    """Not a second store (`Law 14`), and not an append-only file nobody
    prunes: the rows are `Event`s and `prune_events` reaches them."""
    from datetime import timedelta
    from core.database import utcnow_naive

    ev.record_auth_event("login", actor="bob")
    rows = _rows(_db)
    assert len(rows) == 1

    db = _db()
    try:
        row = db.query(Event).first()
        row.ts = utcnow_naive() - timedelta(days=400)
        db.commit()
    finally:
        db.close()

    assert ev.prune_events(days=90) == 1
    assert _rows(_db) == []
