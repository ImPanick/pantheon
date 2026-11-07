# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1901`. A new account could be given a name Pantheon cannot address.

The first-run setup, sign-up and an admin's *Add user* checked only that a
name was not empty and not reserved, and a rename only that the new name was
not empty. So an account could be called `a/b`, `.` or `..`, carry a newline,
a carriage return or a NUL, or run to any length. The admin routes that carry
the name in the URL path (privileges, role, rename, admin, avatar) cannot reach
a name with a `/` in it, since the server decodes `%2F` before it routes, nor
`.` or `..`, which the browser drops from a path; such an account could only be
deleted. And a CR, LF or NUL in the name breaks that person's own loopback
tool calls, which carry it in the `X-Pantheon-Owner` header.

Now `core.auth.username_error` refuses a new name with a `/` or a `\\`, with
any character `str.isprintable()` calls unprintable (control characters, and
also a no-break space or a zero-width joiner), that is `.` or `..`, or that is
longer than `USERNAME_MAX_LENGTH` (64) characters. Setup, sign-up, *Add user*
and a rename's new name answer 400 with its sentence and store nothing. A name
an account already has is never checked: it still signs in, and a rename is
the way out of it.

Ported from upstream Odysseus 7fdc9788 (#6820, #6821); the names are its own
and a few more.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import core.auth as A
from tests.helpers import signed_in
from tests.helpers.signed_in import ADMIN, MEMBER, PASSWORD, as_person
# A sign-in is written to the audit log: `P11-08`'s own database per test.
from tests.test_auth_audit_log import _db  # noqa: F401 — the fixture
from tests.test_rename_user_owner_sync import _request, rename_endpoint  # noqa: F401 — the fixture

REFUSED = {
    "a slash": "a/b",
    "a path up": "../x",
    "a backslash": "a\\b",
    "a tab": "tab\tname",
    "a newline": "new\nline",
    "a carriage return": "cr\rname",
    "a NUL": "nul\x00name",
    "a no-break space": "no break",
    "a zero-width joiner": "zero‍joiner",
    "dot": ".",
    "dot dot": "..",
    "65 characters": "u" * 65,
}
ACCEPTED = ["alice", "Bob Smith", "j.doe", "user@example.com", "日本語", "u" * 64]


@pytest.fixture(autouse=True)
def _fast_hashing(monkeypatch):
    """Password hashing stubbed for speed."""
    monkeypatch.setattr(A, "_hash_password", lambda pw: f"hash:{pw}")
    monkeypatch.setattr(A, "_verify_password", lambda pw, h: h == f"hash:{pw}")


@pytest.fixture
def no_one_yet(tmp_path):
    """A real `AuthManager` on its own `auth.json`, before its first account."""
    return A.AuthManager(str(tmp_path / "auth.json"))


@pytest.fixture
def people(tmp_path):
    """`tests.helpers.signed_in.people`: `ada` the admin and `bob`, who is not."""
    return signed_in.people(tmp_path)


def _client(manager, person=None):
    """The real auth routes; ``person`` is who is signed in, if anyone."""
    from routes.auth_routes import setup_auth_routes

    app = FastAPI()
    app.include_router(setup_auth_routes(manager))
    return TestClient(as_person(app, person, auth_manager=manager))


def test_the_rule_refuses_what_a_path_or_a_header_cannot_carry_and_nothing_else():
    for name in REFUSED.values():
        assert A.username_error(name), repr(name)
    for name in ACCEPTED:
        assert A.username_error(name) is None, name
    assert A.username_error("   ") == "Username is required"
    assert A.username_error("u" * 65) == "Username must be at most 64 characters"


@pytest.mark.parametrize("name", list(REFUSED.values()), ids=list(REFUSED))
def test_add_user_refuses_such_a_name_and_makes_no_account(people, name):
    res = _client(people, ADMIN).post("/api/auth/users", json={"username": name, "password": PASSWORD})
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == A.username_error(name)
    assert set(people.users) == {ADMIN, MEMBER}


def test_first_run_setup_refuses_such_a_name_and_makes_no_account(no_one_yet):
    res = _client(no_one_yet).post("/api/auth/setup", json={"username": "a/b", "password": PASSWORD})
    assert res.status_code == 400, res.text
    assert not no_one_yet.is_configured


def test_sign_up_refuses_such_a_name_and_an_account_that_has_one_still_signs_in(people):
    """The rule is asked of a name being given. An account given one before
    the rule (`create_user` is below it, as every route was) is not locked out."""
    assert people.create_user("old/name", PASSWORD)
    people.signup_enabled = True
    client = _client(people)
    res = client.post("/api/auth/signup", json={"username": "a/b", "password": PASSWORD})
    assert res.status_code == 400, res.text
    assert set(people.users) == {ADMIN, MEMBER, "old/name"}

    res = client.post("/api/auth/login", json={"username": "old/name", "password": PASSWORD})
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True, "username": "old/name"}


def test_a_rename_is_held_to_the_rule_for_its_new_name_only(rename_endpoint):
    """An account may already have a name the rule refuses: it was made
    before the rule. It is not locked out; renaming it to an ordinary name is
    the way out, and only the new name is checked."""
    endpoint, am, tmp_path = rename_endpoint
    old = "x" * 65
    am.users = {old: {}}

    with pytest.raises(HTTPException) as refused:
        endpoint(old, SimpleNamespace(username="a/b"), _request(tmp_path))
    assert refused.value.status_code == 400
    am.rename_user.assert_not_called()

    out = endpoint(old, SimpleNamespace(username="x-renamed"), _request(tmp_path))
    assert out["ok"] is True
    am.rename_user.assert_called_once_with(old, "x-renamed", "admin")
