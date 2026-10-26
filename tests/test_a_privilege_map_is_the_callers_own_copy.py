# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1522` — the privilege map `get_privileges` returns is the caller's own.

**Measured:** an admin's map was `dict(ADMIN_PRIVILEGES)`, a shallow copy, and
a person's map carried `resolve_privilege`'s answer — the registry's own
`allowed_models` list, or the role's, or the stored one. A caller that
appended to the `allowed_models` it was handed edited the registry, and every
later admin or person read the longer list.
"""

import core.auth as A


def _manager(tmp_path, monkeypatch):
    """A real `AuthManager` on a temp `auth.json`, hashing stubbed for speed."""
    monkeypatch.setattr(A, "_hash_password", lambda pw: f"hash:{pw}")
    monkeypatch.setattr(A, "_verify_password", lambda pw, h: h == f"hash:{pw}")
    mgr = A.AuthManager(str(tmp_path / "auth.json"))
    assert mgr.create_user("ada", "pw-123456", is_admin=True)
    assert mgr.create_user("bob", "pw-123456")
    assert mgr.create_user("cy", "pw-123456")
    assert mgr.set_privileges("cy", {"allowed_models": ["m-1"]})
    return mgr


def test_appending_to_a_returned_list_changes_nobody_elses(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    before_admin = list(A.ADMIN_PRIVILEGES["allowed_models"])
    before_default = list(A.DEFAULT_PRIVILEGES["allowed_models"])
    for name in ("ada", "bob", "cy"):
        mgr.get_privileges(name)["allowed_models"].append("smuggled")
    assert A.ADMIN_PRIVILEGES["allowed_models"] == before_admin
    assert A.DEFAULT_PRIVILEGES["allowed_models"] == before_default
    assert mgr.users["cy"]["privileges"]["allowed_models"] == ["m-1"]
    for name in ("ada", "bob", "cy"):
        assert "smuggled" not in mgr.get_privileges(name)["allowed_models"], name
