# SPDX-License-Identifier: AGPL-3.0-or-later
import types

import pytest

from src import auth_helpers
from src.auth_helpers import require_privilege


class _Mgr:
    def __init__(self, privs):
        self._privs = privs

    def get_privileges(self, user):
        return self._privs


def _request(mgr):
    state = types.SimpleNamespace(auth_manager=mgr)
    return types.SimpleNamespace(app=types.SimpleNamespace(state=state))


def test_require_privilege_tolerates_non_dict_privileges(monkeypatch):
    # A corrupt auth.json can make get_privileges return a non-dict (e.g. a
    # list). The privs.get(...) call sits outside the try, so the old code
    # raised AttributeError and turned a privilege check into a 500. It must
    # still answer, not crash.
    #
    # Updated 2026-09-18 for `P11-01`. This assertion used to read
    # `require_privilege(req, "do_x") == "bob"` and it was the one call site in
    # the tree that depended on the fail-open default: "do_x" is declared in
    # neither the user's map nor `DEFAULT_PRIVILEGES`, so it now denies. The
    # property this test was written for — a corrupt map produces an answer
    # rather than a 500 — is unchanged and is what the three cases below check.
    monkeypatch.setattr(auth_helpers, "require_user", lambda request: "bob")
    req = _request(_Mgr(["can_use_research"]))

    # 1. A declared key falls back to its registry value, so a corrupt file
    #    degrades to the documented defaults rather than locking users out.
    assert require_privilege(req, "can_use_research") == "bob"
    # 2. ... including the one registry default that is False.
    with pytest.raises(Exception) as denied:
        require_privilege(req, "can_use_bash")
    assert getattr(denied.value, "status_code", None) == 403
    # 3. An undeclared key denies with a 403, not an AttributeError/500.
    with pytest.raises(Exception) as unknown:
        require_privilege(req, "do_x")
    assert getattr(unknown.value, "status_code", None) == 403


def test_require_privilege_still_blocks_disallowed(monkeypatch):
    monkeypatch.setattr(auth_helpers, "require_user", lambda request: "bob")
    req = _request(_Mgr({"do_x": False}))
    with pytest.raises(Exception):
        require_privilege(req, "do_x")
