# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P11-01` — `require_privilege` no longer grants on a key nobody declared.

Every test here calls the real `src.auth_helpers.require_privilege` against a
duck-typed auth manager, because the thing under test is the *resolution rule*
and the rule has to hold for whatever shape of privilege map reaches it —
`AuthManager.get_privileges` merges `DEFAULT_PRIVILEGES` in, a corrupt
`auth.json` does not, and a partial stored map is what an older install has on
disk. Asserting on the source text of `auth_helpers.py` would pass for all
three and mean nothing (`Law 20`).

The old line was `privs.get(key, True)`: a key in neither the user's map nor
the registry resolved to *permitted*.
"""
import importlib
import types

import pytest
from fastapi import HTTPException

from src import auth_helpers
from src.auth_helpers import require_privilege, resolve_privilege


def _registry():
    """The live registry, resolved the way `resolve_privilege` resolves it.

    Deliberately NOT a module-level `from core.auth import DEFAULT_PRIVILEGES`.
    That binds the dict object that existed when this file was collected, and
    the suite contains tests that pop `core.auth` out of `sys.modules`
    (`test_security_regressions.py:798`) or swap a fake module in for their
    duration. After one of those has run, `resolve_privilege`'s per-call import
    reads a *different* dict than the one captured here — so `monkeypatch.setitem`
    on the captured one is invisible, and the test passes on its own and fails
    only in a whole-suite run. It did: `11116 passed, 1 failed`, and the one was
    this file. Same class as `B524`.
    """
    return importlib.import_module("core.auth").DEFAULT_PRIVILEGES


class _Mgr:
    """Stands in for `AuthManager`; `require_privilege` only calls this one."""

    def __init__(self, privs):
        self._privs = privs

    def get_privileges(self, user):
        return self._privs


def _request(mgr):
    state = types.SimpleNamespace(auth_manager=mgr)
    return types.SimpleNamespace(app=types.SimpleNamespace(state=state))


def _as_user(monkeypatch, name="bob"):
    monkeypatch.setattr(auth_helpers, "require_user", lambda request: name)


def _merged(**overrides):
    """What `AuthManager.get_privileges` hands back: registry, then stored."""
    return {**_registry(), **overrides}


def test_typod_privilege_key_denies(monkeypatch):
    # The live defect the row names. `can_use_reserch` is a plausible typo of a
    # real key at a real call site (`research_routes.py` passes
    # `can_use_research`). It is in neither the user's map nor the registry, so
    # the old default granted it — and the route behind it ran ungated for
    # every non-admin, with nothing logged.
    _as_user(monkeypatch)
    req = _request(_Mgr(_merged()))
    with pytest.raises(HTTPException) as exc:
        require_privilege(req, "can_use_reserch")
    assert exc.value.status_code == 403
    # Same 403 body as any other denial: a typo must not be distinguishable
    # from a policy decision by probing the error string.
    assert exc.value.detail == auth_helpers.privilege_denied_message("can_use_reserch")


def test_typod_key_denies_an_admin_too(monkeypatch):
    # ADMIN_PRIVILEGES is every *declared* key set permissive, so an admin sails
    # through all eleven. An undeclared key is not in that map either, and it
    # denies here as well. That is deliberate: a typo'd gate that only ever
    # 403s non-admins gets found by a user; one that 403s the operator on the
    # first request gets found by the person who can fix it.
    from core.auth import ADMIN_PRIVILEGES

    _as_user(monkeypatch, "root")
    req = _request(_Mgr(dict(ADMIN_PRIVILEGES)))
    assert require_privilege(req, "can_use_research") == "root"
    with pytest.raises(HTTPException) as exc:
        require_privilege(req, "can_generate_imagez")
    assert exc.value.status_code == 403


def test_known_key_absent_from_user_map_resolves_to_the_registry(monkeypatch):
    # A stored map that predates a key — or any caller that did not merge
    # `DEFAULT_PRIVILEGES` in — must land on the registry's declared value, not
    # on True. `can_use_bash` is the one boolean the registry declares False, so
    # it is the only key where "registry default" and "old fail-open default"
    # give different answers, which makes it the whole test.
    assert _registry()["can_use_bash"] is False
    assert _registry()["can_use_research"] is True

    _as_user(monkeypatch)
    # Deliberately NOT `_merged()`: this is a partial map, the shape the merge
    # in `core/auth.py` exists to paper over.
    req = _request(_Mgr({"can_use_documents": True}))

    with pytest.raises(HTTPException) as exc:
        require_privilege(req, "can_use_bash")
    assert exc.value.status_code == 403
    # The permissive side of the same rule: a declared-True key absent from the
    # map still resolves True, so falling back to the registry is not a blanket
    # deny dressed up as a default.
    assert require_privilege(req, "can_use_research") == "bob"


def test_stored_value_beats_the_registry_in_both_directions(monkeypatch):
    # The registry is the *fallback*. An explicit stored value always wins, or
    # the admin panel's per-user editor would stop working.
    _as_user(monkeypatch)
    granted = _request(_Mgr(_merged(can_use_bash=True)))
    assert require_privilege(granted, "can_use_bash") == "bob"

    denied = _request(_Mgr(_merged(can_use_research=False)))
    with pytest.raises(HTTPException):
        require_privilege(denied, "can_use_research")


def test_new_registry_key_grants_while_its_typo_denies(monkeypatch):
    # The mid-deploy scenario, both halves in one run because they are the same
    # deploy: you add a key to `DEFAULT_PRIVILEGES` and ship the route that
    # checks it. Every existing user's stored map predates the key and must keep
    # working (the registry declares it True); the typo in the route you just
    # wrote must not.
    _as_user(monkeypatch)
    monkeypatch.setitem(_registry(), "can_use_teleporter", True)
    # An account created before the new key existed.
    req = _request(_Mgr({"can_use_documents": True, "can_use_research": True}))

    assert require_privilege(req, "can_use_teleporter") == "bob"
    with pytest.raises(HTTPException) as exc:
        require_privilege(req, "can_use_teleportr")
    assert exc.value.status_code == 403


def test_a_restrictive_new_registry_key_is_restrictive_immediately(monkeypatch):
    # The other half of case 2: the registry's value is honoured, whatever it
    # says. A key declared False denies from the first request rather than
    # waiting for someone to write it into every user's stored map.
    _as_user(monkeypatch)
    monkeypatch.setitem(_registry(), "can_wipe_everything", False)
    req = _request(_Mgr(_merged()))
    with pytest.raises(HTTPException):
        require_privilege(req, "can_wipe_everything")


def test_resolve_privilege_returns_non_boolean_values_intact():
    # Two of the eleven registry entries are not booleans. `require_privilege`
    # only ever sees `can_*` keys, but `resolve_privilege` is the single source
    # of truth for the whole registry (`chat_helpers` reads
    # `max_messages_per_day` and `allowed_models` the same way), so it returns
    # the value rather than a verdict. `0` and `[]` are both falsy and both mean
    # "no restriction" here — collapsing them to a bool would inverted-gate
    # every account.
    assert resolve_privilege({}, "max_messages_per_day") == 0
    assert resolve_privilege({}, "allowed_models") == []
    assert resolve_privilege({"max_messages_per_day": 50}, "max_messages_per_day") == 50
    assert resolve_privilege({}, "not_a_privilege") is False


def test_resolve_privilege_survives_a_non_dict_map():
    # A corrupt `auth.json` can make `get_privileges` return a list. The
    # registry still answers for declared keys; nothing raises.
    assert resolve_privilege(["can_use_research"], "can_use_research") is True
    assert resolve_privilege(None, "can_use_bash") is False
    assert resolve_privilege("garbage", "can_use_nothing_in_particular") is False
