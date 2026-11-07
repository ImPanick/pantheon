# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1900`. A person's own privilege was stored as whatever it was sent.

`PUT /api/auth/users/{username}/privileges` handed its body to
`AuthManager.set_privileges`, which kept the declared keys and stored every
value but `None` as it came. A role's override was already checked by
`src/roles.py`, but a person's own outranks the role, and nothing checked it.
So a hand-made request storing `{"can_use_browser": "false"}` left that
person's browser tools on (`resolve_privilege` hands back the stored string,
and a non-empty string is true), `{"max_messages_per_day": "50x"}` made every
chat send of theirs raise in `int()`, and a body that was a list, or not JSON,
answered 500.

Now every value goes through the role layer's own check,
`src.roles.check_privilege_value` (`Law 14`), before anything is stored. One
mistyped value refuses the whole body with a 400 that names it, nothing moves,
and the refusal is written to the audit log like any other (`P11-08`). `None`
still clears an override (`P11-02`, `B90`), which upstream's check refused.
The Settings switches send a boolean and the daily limit a whole number, so
nothing they do changes.

Ported from upstream Odysseus 9974841c (#6829, #6830), re-implemented on
Pantheon's validator; the mistyped values are upstream's and a few more.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.auth as A
from src.roles import RoleError
from tests.helpers import signed_in
from tests.helpers.signed_in import ADMIN, MEMBER, as_person
# `P11-08`'s own database per test, and its reader of the audit rows.
from tests.test_auth_audit_log import _db, _detail, _rows  # noqa: F401 — the fixture

MISTYPED = {
    "a word for a switch": {"can_use_bash": "no"},
    "the string false": {"can_use_browser": "false"},
    "a number for a switch": {"can_use_email": 0},
    "a word for the daily limit": {"max_messages_per_day": "abc"},
    "digits for the daily limit": {"max_messages_per_day": "50"},
    "true for the daily limit": {"max_messages_per_day": True},
    "a fraction for the daily limit": {"max_messages_per_day": 2.5},
    "a negative daily limit": {"max_messages_per_day": -1},
    "one name for the model list": {"allowed_models": "gpt"},
    "an empty name in the model list": {"allowed_models": ["", "m"]},
    "a word for the block-all sentinel": {"block_all_models": "yes"},
}


@pytest.fixture
def people(tmp_path, monkeypatch):
    """`tests.helpers.signed_in.people`: `ada` the admin, `bob` not, on their
    own `auth.json`, with password hashing stubbed for speed."""
    monkeypatch.setattr(A, "_hash_password", lambda pw: f"hash:{pw}")
    monkeypatch.setattr(A, "_verify_password", lambda pw, h: h == f"hash:{pw}")
    return signed_in.people(tmp_path)


@pytest.fixture
def admin_client(people, _db):
    """The real auth routes, with the admin signed in."""
    from routes.auth_routes import setup_auth_routes

    app = FastAPI()
    app.include_router(setup_auth_routes(people))
    return TestClient(as_person(app, ADMIN, auth_manager=people))


def _privilege_rows(maker):
    return [(row.outcome, _detail(row)) for row in _rows(maker, "privilege_change")]


def _put(client, body=None, *, raw=None):
    url = f"/api/auth/users/{MEMBER}/privileges"
    if raw is not None:
        return client.put(url, content=raw, headers={"Content-Type": "application/json"})
    return client.put(url, json=body)


# ── the manager ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("privileges", list(MISTYPED.values()), ids=list(MISTYPED))
def test_a_mistyped_value_is_refused_by_name_and_nothing_is_stored(people, privileges):
    before = people.get_privileges(MEMBER)
    stored = dict(people.users[MEMBER].get("privileges") or {})
    with pytest.raises(RoleError) as refused:
        people.set_privileges(MEMBER, privileges)
    assert next(iter(privileges)) in str(refused.value)
    assert people.get_privileges(MEMBER) == before
    assert dict(people.users[MEMBER].get("privileges") or {}) == stored


def test_one_mistyped_value_refuses_the_whole_body(people, tmp_path):
    """Every value is checked before anything moves: the well-typed switch
    beside the bad one is not stored, and the `None` beside it does not clear."""
    assert people.set_privileges(MEMBER, {"can_use_research": False})
    before = dict(people.users[MEMBER]["privileges"])
    with pytest.raises(RoleError):
        people.set_privileges(MEMBER, {"can_use_email": False, "can_use_research": None,
                                       "max_messages_per_day": "50x"})
    assert people.users[MEMBER]["privileges"] == before
    assert A.AuthManager(str(tmp_path / "auth.json")).users[MEMBER]["privileges"] == before


@pytest.mark.parametrize("privileges", [["can_use_bash"], "can_use_bash", None],
                         ids=["a list", "a string", "nothing"])
def test_privileges_that_are_not_an_object_are_refused(people, privileges):
    with pytest.raises(RoleError):
        people.set_privileges(MEMBER, privileges)


# ── the route ───────────────────────────────────────────────────────────────

def test_a_mistyped_value_is_a_400_that_names_it_and_is_recorded_as_a_refusal(
        admin_client, people, _db):
    res = _put(admin_client, {"can_use_browser": "false"})
    assert res.status_code == 400, res.text
    assert "can_use_browser" in res.json()["detail"]
    assert people.get_privileges(MEMBER)["can_use_browser"] is True
    [(outcome, detail)] = _privilege_rows(_db)
    assert outcome == "error"
    assert detail["subject"] == MEMBER
    assert "can_use_browser" in detail["reason"]

    # What the Settings switch sends is stored, and `null` still clears it.
    assert _put(admin_client, {"can_use_browser": False}).status_code == 200
    assert people.get_privileges(MEMBER)["can_use_browser"] is False
    assert _put(admin_client, {"can_use_browser": None}).status_code == 200
    assert "can_use_browser" not in people.users[MEMBER]["privileges"]
    assert [outcome for outcome, _ in _privilege_rows(_db)] == ["error", "ok", "ok"]


@pytest.mark.parametrize("raw", ['["can_use_bash"]', '"can_use_bash"', "null", "{"],
                         ids=["a list", "a string", "null", "not JSON"])
def test_a_body_that_is_not_a_json_object_is_a_400_recorded_as_a_refusal(
        admin_client, people, _db, raw):
    before = people.get_privileges(MEMBER)
    res = _put(admin_client, raw=raw)
    assert res.status_code == 400, res.text
    assert people.get_privileges(MEMBER) == before
    [(outcome, detail)] = _privilege_rows(_db)
    assert outcome == "error"
    assert detail["subject"] == MEMBER
