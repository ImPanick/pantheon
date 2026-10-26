# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B680` — an account created as an admin, then demoted, holds the role it is given.

`AuthManager.set_admin`'s demote branch fell back to a full copy of
`DEFAULT_PRIVILEGES` when there was no `privileges_before_admin` stash, and an
account created with `is_admin=True` never has one. Every key in that copy is a
per-user override, and per-user beats role, so a role given to the demoted
person afterwards granted nothing. Driven through the real `AuthManager` on a
real `auth.json`.
"""
import importlib


def _mgr(tmp_path):
    auth = importlib.import_module("core.auth")
    auth._hash_password = lambda password: f"hash:{password}"
    auth._verify_password = lambda password, hashed: hashed == f"hash:{password}"
    mgr = auth.AuthManager(str(tmp_path / "auth.json"))
    mgr.create_user("root", "pw-123456", is_admin=True)
    mgr.create_user("dana", "pw-123456", is_admin=True)
    return auth, mgr


def test_a_role_given_after_demotion_is_the_one_they_hold(tmp_path):
    auth, mgr = _mgr(tmp_path)
    mgr.define_role("builder", {"can_use_bash": True, "can_use_browser": False,
                                "max_messages_per_day": 40})

    assert mgr.set_admin("dana", False, "root") is auth.SetAdminResult.OK
    assert mgr.set_user_role("dana", "builder") is True

    held = mgr.get_privileges("dana")
    assert held["can_use_bash"] is True
    assert held["can_use_browser"] is False
    assert held["max_messages_per_day"] == 40


def test_demotion_leaves_no_admin_privilege_behind(tmp_path):
    """The reason the old fallback existed — `can_use_bash` is an admin's and not
    a person's — still holds with no override stored."""
    auth, mgr = _mgr(tmp_path)
    assert mgr.set_admin("dana", False, "root") is auth.SetAdminResult.OK
    assert mgr.users["dana"]["privileges"] == {}
    assert mgr.get_privileges("dana") == auth.DEFAULT_PRIVILEGES


def test_the_role_survives_a_reload(tmp_path):
    auth, mgr = _mgr(tmp_path)
    mgr.define_role("reader", {"can_use_agent": False})
    mgr.set_admin("dana", False, "root")
    mgr.set_user_role("dana", "reader")
    again = auth.AuthManager(str(tmp_path / "auth.json"))
    assert again.get_privileges("dana")["can_use_agent"] is False
