# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B532` — what an admin holds for a privilege is declared, not guessed from its type.

`ADMIN_PRIVILEGES` was built from `DEFAULT_PRIVILEGES` by type — every bool to
`True`, every int to `0`, everything else to `[]` — and then the two keys where
that was wrong (`allowed_models_restricted`, `block_all_models`) were patched
back by hand underneath, with a comment saying the comprehension was backwards
for a sentinel. A third sentinel-shaped key added to the registry would have
been switched ON for every admin, silently.

Driven through the real derivation (`core.auth._admin_privileges`) with the real
registry and a registry grown by one key, the way `P11-02`'s roles will grow it.
"""
import importlib

import pytest


def _auth():
    # Per call: `tests/test_security_regressions.py` pops `core.auth` from
    # `sys.modules`, so a module-level import would bind a stale registry.
    return importlib.import_module("core.auth")


def test_the_shipped_admin_map_is_every_key_at_its_granted_value():
    auth = _auth()
    admin = auth.ADMIN_PRIVILEGES
    assert set(admin) == set(auth.DEFAULT_PRIVILEGES)
    for key, declared in auth.DEFAULT_PRIVILEGES.items():
        if key.startswith("can_"):
            assert admin[key] is True, key
    # The two sentinels: an admin is never restricted to a list, never blocked.
    assert admin["block_all_models"] is False
    assert admin["allowed_models_restricted"] is False
    assert admin["allowed_models"] == []
    assert admin["max_messages_per_day"] == 0


def test_a_new_sentinel_is_refused_rather_than_switched_on_for_admins():
    """The row's case. `block_web_search: False` is a boolean whose `True` takes
    something away; the type-based rule would have handed every admin `True`."""
    auth = _auth()
    grown = {**auth.DEFAULT_PRIVILEGES, "block_web_search": False}
    with pytest.raises(RuntimeError) as err:
        auth._admin_privileges(grown, auth.ADMIN_GRANTS)
    assert "block_web_search" in str(err.value)
    assert "ADMIN_GRANTS" in str(err.value)


def test_a_new_cap_is_refused_rather_than_read_as_unlimited():
    """`max_uploads_per_day: 20` is not "unlimited at 0" unless somebody says so."""
    auth = _auth()
    grown = {**auth.DEFAULT_PRIVILEGES, "max_uploads_per_day": 20}
    with pytest.raises(RuntimeError) as err:
        auth._admin_privileges(grown, auth.ADMIN_GRANTS)
    assert "max_uploads_per_day" in str(err.value)


def test_declared_beside_the_key_it_resolves_with_no_second_line():
    """One entry in `ADMIN_GRANTS` and the sentinel resolves off for admins; a
    new `can_*` key needs nothing at all — its name is its declaration."""
    auth = _auth()
    grown = {**auth.DEFAULT_PRIVILEGES, "block_web_search": False, "can_use_radio": False}
    grants = {**auth.ADMIN_GRANTS, "block_web_search": False}
    admin = auth._admin_privileges(grown, grants)
    assert admin["block_web_search"] is False
    assert admin["can_use_radio"] is True

