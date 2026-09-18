# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P11-02` — a role is a named overlay, resolved in one place.

Everything here drives the real objects: a real `AuthManager` on a real
`auth.json` in `tmp_path`, the real `src.auth_helpers.resolve_privilege`, and
the real `src.settings.resolve_limit` through the real
`src.upload_limits.resolve_byte_limit_with_source`. Nothing greps a source
file (`Law 20`) — the thing under test is a *resolution order*, and an order is
only observable by asking for an answer.

Two properties are load-bearing and each has its own test:

* **`Law 1`.** An install that has never named a role resolves exactly as it
  did before roles existed, and `is_admin` still short-circuits to
  `ADMIN_PRIVILEGES` before anything else is consulted. Those two tests pass on
  the tree before this row as well as after — that is what an invariance proof
  is for, and it is said out loud rather than counted as evidence of the
  feature.
* **`Law 13`.** The role layer is inside `resolve_privilege` and the limit
  layer is the provider `P12-01` registered and left empty. A role that only
  worked through `get_privileges` would be a second resolution path, so the
  tests ask both the privilege side and the limit side for the same role.
"""
import importlib

import pytest

from src import roles as roles_mod
from src.auth_helpers import resolve_privilege


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_leaked_provider():
    """The limit provider is process-wide. Install it deliberately, and never
    leave it installed for the next test in the session."""
    roles_mod.clear_role_layer()
    yield
    roles_mod.clear_role_layer()


def _mgr(tmp_path):
    """A real AuthManager on a real file, with bcrypt stubbed for speed."""
    auth_mod = importlib.import_module("core.auth")
    auth_mod._hash_password = lambda password: f"hash:{password}"
    auth_mod._verify_password = lambda password, hashed: hashed == f"hash:{password}"
    mgr = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    mgr.create_user("admin", "pw-123456", is_admin=True)
    mgr.create_user("bob", "pw-123456")
    return auth_mod, mgr


def _registry():
    """The live registry, resolved the way the code resolves it — per call.

    `tests/test_security_regressions.py` pops `core.auth` out of `sys.modules`,
    so a module-level `from core.auth import DEFAULT_PRIVILEGES` in a test file
    binds a dict object the product later stops using. `P11-01`'s own test
    file records that reproduction; this one does not repeat the mistake.
    """
    return importlib.import_module("core.auth").DEFAULT_PRIVILEGES


# ---------------------------------------------------------------------------
# Law 1 — the invariance proofs. These pass before this row and after it.
# ---------------------------------------------------------------------------

def test_with_no_roles_defined_every_user_resolves_to_the_old_merge(tmp_path):
    """The rule this replaced, recomputed here and held equal."""
    auth_mod, mgr = _mgr(tmp_path)
    assert mgr.roles == {}

    for username in ("bob", "admin"):
        stored = mgr.users[username].get("privileges") or {}
        if mgr.is_admin(username):
            expected = dict(auth_mod.ADMIN_PRIVILEGES)
        else:
            expected = {**_registry(), **stored}
        assert mgr.get_privileges(username) == expected

    mgr.set_privileges("bob", {"can_use_bash": True, "max_messages_per_day": 50})
    assert mgr.get_privileges("bob") == {
        **_registry(), "can_use_bash": True, "max_messages_per_day": 50}


def test_is_admin_is_still_the_superuser_role_and_outranks_every_named_one(tmp_path):
    """107 `require_admin` sites read this flag. A role cannot touch it."""
    auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("locked-down", {"can_use_agent": False, "can_use_research": False})
    mgr.set_user_role("bob", "locked-down")
    assert mgr.get_privileges("bob")["can_use_agent"] is False

    # Promote bob. The role is still on his row and must stop applying.
    assert mgr.set_admin("bob", True, "admin") is auth_mod.SetAdminResult.OK
    assert mgr.get_privileges("bob") == dict(auth_mod.ADMIN_PRIVILEGES)
    assert mgr.role_overrides_for_user("bob") == {}

    # And a role cannot be handed to an admin at all: it would store a
    # decision that never applies.
    with pytest.raises(roles_mod.RoleError):
        mgr.set_user_role("bob", "locked-down")


def test_the_admin_short_circuit_is_what_answers_not_a_complete_stored_map(tmp_path):
    """The superuser answer cannot depend on the stored map being full.

    A mutation that deletes `get_privileges`'s `is_admin` short-circuit
    survives every obvious test, because `set_admin` writes `ADMIN_PRIVILEGES`
    into the stored map on promotion and the merge then produces the same
    answer by accident. The flag is the authority, not the copy: `auth.json` is
    hand-editable and setting `is_admin` on a row is how an operator recovers
    admin access, and a future promote path that does not rewrite the map must
    not silently demote them to defaults-plus-role.
    """
    auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("locked-down", {"can_use_agent": False, "can_use_browser": False})
    mgr.set_user_role("bob", "locked-down")

    # The flag alone, on a row whose stored map is empty — the state
    # `create_user` now leaves and a hand-edit produces.
    mgr._config["users"]["bob"]["is_admin"] = True
    assert mgr.users["bob"].get("privileges") == {}

    assert mgr.get_privileges("bob") == dict(auth_mod.ADMIN_PRIVILEGES)
    assert mgr.get_privileges("bob")["can_use_agent"] is True
    assert mgr.get_privileges("bob")["can_use_bash"] is True


# ---------------------------------------------------------------------------
# the resolution order
# ---------------------------------------------------------------------------

def test_a_role_answers_a_key_the_user_has_not_overridden(tmp_path):
    _auth_mod, mgr = _mgr(tmp_path)
    assert mgr.get_privileges("bob")["can_use_bash"] is False   # the registry

    mgr.define_role("operator", {"can_use_bash": True, "max_messages_per_day": 500})
    mgr.set_user_role("bob", "operator")

    privs = mgr.get_privileges("bob")
    assert privs["can_use_bash"] is True
    assert privs["max_messages_per_day"] == 500
    # Untouched keys still come from the registry, not from the role.
    assert privs["can_use_documents"] is _registry()["can_use_documents"]


def test_a_per_user_override_beats_the_role(tmp_path):
    _auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("operator", {"can_use_bash": True})
    mgr.set_user_role("bob", "operator")
    assert mgr.get_privileges("bob")["can_use_bash"] is True

    mgr.set_privileges("bob", {"can_use_bash": False})
    assert mgr.get_privileges("bob")["can_use_bash"] is False

    # ...and `None` gives the key back to the role rather than storing a value.
    mgr.set_privileges("bob", {"can_use_bash": None})
    assert mgr.get_privileges("bob")["can_use_bash"] is True


def test_the_order_lives_in_resolve_privilege_and_nowhere_else():
    """Four cases, asked of the function directly, with no AuthManager at all."""
    declared = next(k for k, v in _registry().items() if isinstance(v, bool))
    default = _registry()[declared]

    assert resolve_privilege({declared: not default}, declared,
                             role_overrides={declared: default}) is (not default)
    assert resolve_privilege({}, declared,
                             role_overrides={declared: not default}) is (not default)
    assert resolve_privilege({}, declared, role_overrides={}) is default
    assert resolve_privilege({}, "can_use_nothing_in_particular",
                             role_overrides={}) is False


def test_a_role_cannot_grant_a_key_nobody_declared():
    """`P11-01`'s rule, held through the new layer.

    `auth.json` is hand-editable, so a role body reaching the resolver with an
    undeclared key is a real input, not a hypothetical. It must not grant.
    """
    assert resolve_privilege({}, "can_use_reserch",
                             role_overrides={"can_use_reserch": True}) is False


# ---------------------------------------------------------------------------
# what made the overlay reachable at all
# ---------------------------------------------------------------------------

def test_a_new_user_stores_no_overrides_so_a_role_can_reach_them(tmp_path):
    """The defect that would have made this whole row dead code.

    `create_user` stored a full copy of `DEFAULT_PRIVILEGES` on every non-admin.
    A stored map that names all eleven keys is eleven per-user overrides, and
    per-user beats role — so a role would have been shadowed for every user
    created through the normal path, silently, with the catalogue looking right.
    """
    _auth_mod, mgr = _mgr(tmp_path)
    assert mgr.users["bob"].get("privileges") == {}
    # ...and the EFFECTIVE map is unchanged by that.
    assert mgr.get_privileges("bob") == dict(_registry())


def test_saving_one_privilege_does_not_freeze_the_whole_role_into_the_user(tmp_path):
    """`set_privileges` stores overrides, not the resolved map."""
    _auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("operator", {"can_use_bash": True, "can_use_research": False})
    mgr.set_user_role("bob", "operator")

    mgr.set_privileges("bob", {"can_generate_images": False})

    assert mgr.users["bob"]["privileges"] == {"can_generate_images": False}
    privs = mgr.get_privileges("bob")
    assert privs["can_generate_images"] is False    # the override
    assert privs["can_use_bash"] is True            # still the role
    assert privs["can_use_research"] is False       # still the role


def test_a_promote_demote_round_trip_leaves_the_role_working(tmp_path):
    auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("operator", {"can_use_bash": True})
    mgr.set_user_role("bob", "operator")

    assert mgr.set_admin("bob", True, "admin") is auth_mod.SetAdminResult.OK
    assert mgr.set_admin("bob", False, "admin") is auth_mod.SetAdminResult.OK

    assert mgr.users["bob"]["privileges"] == {}
    assert mgr.get_privileges("bob")["can_use_bash"] is True


# ---------------------------------------------------------------------------
# the limit half — `P12-01`'s provider, finally installed
# ---------------------------------------------------------------------------

def test_a_role_sets_a_limit_and_every_limit_in_the_product_inherits_it(tmp_path, monkeypatch):
    """One `install_role_layer` call, and the byte caps and the throttles move.

    Driven through `resolve_byte_limit_with_source` and `settings.resolve_limit`
    rather than the provider, because the claim `P12-01` made is about the
    product's limits, not about a registry holding a function.
    """
    from src.settings import resolve_limit
    from src.upload_limits import resolve_byte_limit_with_source

    _auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("big-uploads", {
        "gallery_upload_max_bytes": 500 * 1024 * 1024,
        "auth_login_rate_limit": 3,
    })
    mgr.set_user_role("bob", "big-uploads")

    # Before the layer is installed, nothing answers — the honest empty state.
    assert resolve_byte_limit_with_source("gallery_upload_max_bytes", "bob")[1] \
        == "built-in default"

    roles_mod.install_role_layer(mgr)

    value, source = resolve_byte_limit_with_source("gallery_upload_max_bytes", "bob")
    assert (value, source) == (500 * 1024 * 1024, "role profile")
    assert resolve_limit("auth_login_rate_limit", 15, owner="bob") == (3, "role profile")

    # Somebody without the role is untouched, and so is a nameless caller.
    assert resolve_byte_limit_with_source("gallery_upload_max_bytes", "admin")[1] \
        == "built-in default"
    assert resolve_byte_limit_with_source("gallery_upload_max_bytes", None)[1] \
        == "built-in default"


def test_the_role_provider_never_answers_with_a_privilege(tmp_path):
    """A role spans two namespaces and the limit leg must only see one.

    `True` is an `int` in Python: a boolean privilege reaching
    `settings._coerce_limit` would become a cap of one byte.
    """
    from src.settings import role_limit

    _auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("mixed", {"can_use_bash": True,
                              "gallery_upload_max_bytes": 1234567})
    mgr.set_user_role("bob", "mixed")
    roles_mod.install_role_layer(mgr)

    assert role_limit("gallery_upload_max_bytes", "bob") == 1234567
    assert role_limit("can_use_bash", "bob") is None


def test_with_no_role_the_provider_answers_nothing_for_every_limit_key(tmp_path):
    """`Law 1`, on the limit side."""
    from src.settings import LIMIT_RANGES, role_limit

    _auth_mod, mgr = _mgr(tmp_path)
    roles_mod.install_role_layer(mgr)
    for key in LIMIT_RANGES:
        assert role_limit(key, "bob") is None


# ---------------------------------------------------------------------------
# the catalogue: what may be stored, and what happens when one is removed
# ---------------------------------------------------------------------------

def test_a_role_may_only_name_keys_a_registry_already_declares(tmp_path):
    _auth_mod, mgr = _mgr(tmp_path)
    with pytest.raises(roles_mod.RoleError):
        mgr.define_role("typo", {"can_use_bsah": True})
    assert mgr.roles == {}


def test_the_two_namespaces_are_the_two_live_registries():
    """No third list of keys (`Law 14`).

    The limit half was `LIMIT_RANGES` until `P12-02`, which found that table
    answering a narrower question than the role layer needs — *which settings
    keys are **nullable** integer limits* — and four limits consulting the role
    leg on every call that were not in it. `role_limit_ranges()` is that table
    plus those four, each bound imported from the module that owns the limit.
    The assertion is unchanged in intent and stronger in fact: it now also
    proves the derivation contains the table rather than replacing it.
    """
    from src.settings import DEFAULT_SETTINGS, LIMIT_RANGES, role_limit_ranges

    assert roles_mod.privilege_keys() == frozenset(_registry())
    assert roles_mod.limit_keys() == frozenset(role_limit_ranges())
    assert set(LIMIT_RANGES) < set(role_limit_ranges())
    # And the limit keys really are settings keys, not a parallel vocabulary.
    assert set(role_limit_ranges()) <= set(DEFAULT_SETTINGS)


def test_a_role_cannot_talk_a_limit_down_to_off(tmp_path):
    """`FORBIDDEN.md` Part 2: the auth rate limiters and the upload caps are
    controls that never lift. A role is not the way around a list saying never."""
    _auth_mod, mgr = _mgr(tmp_path)
    with pytest.raises(roles_mod.RoleError):
        mgr.define_role("off", {"auth_login_rate_limit": 0})
    with pytest.raises(roles_mod.RoleError):
        mgr.define_role("off", {"gallery_upload_max_bytes": True})
    assert mgr.roles == {}


def test_a_privilege_override_has_to_match_its_declared_type(tmp_path):
    _auth_mod, mgr = _mgr(tmp_path)
    with pytest.raises(roles_mod.RoleError):
        mgr.define_role("weird", {"can_use_bash": "yes"})
    with pytest.raises(roles_mod.RoleError):
        mgr.define_role("weird", {"max_messages_per_day": True})
    with pytest.raises(roles_mod.RoleError):
        mgr.define_role("weird", {"allowed_models": "gpt-4"})


def test_the_superuser_names_are_reserved(tmp_path):
    _auth_mod, mgr = _mgr(tmp_path)
    for name in ("admin", "superuser", "Owner"):
        with pytest.raises(roles_mod.RoleError):
            mgr.define_role(name, {})


def test_an_unknown_role_cannot_be_assigned(tmp_path):
    """A role assigned before it exists grants nothing and looks configured."""
    _auth_mod, mgr = _mgr(tmp_path)
    with pytest.raises(roles_mod.RoleError):
        mgr.set_user_role("bob", "ghost")
    assert mgr.get_role("bob") is None


def test_deleting_a_role_takes_it_off_everyone_holding_it(tmp_path):
    _auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("operator", {"can_use_bash": True})
    mgr.set_user_role("bob", "operator")
    assert mgr.get_privileges("bob")["can_use_bash"] is True

    assert mgr.delete_role("operator") is True

    assert mgr.get_role("bob") is None
    assert mgr.users["bob"].get("role") is None
    assert mgr.get_privileges("bob")["can_use_bash"] is False
    assert mgr.delete_role("operator") is False


def test_a_role_name_nobody_defined_is_not_a_role(tmp_path):
    """`auth.json` is hand-editable and role names are strings.

    A row naming a role the catalogue does not have must read as *no role*, not
    as a role that happens to grant nothing — otherwise a panel shows somebody
    holding "operator" while the resolver ignores it, which is a permission
    nobody can see or revoke.
    """
    _auth_mod, mgr = _mgr(tmp_path)
    mgr._config["users"]["bob"]["role"] = "ghost"

    assert mgr.get_role("bob") is None
    assert mgr.role_overrides_for_user("bob") == {}
    assert mgr.get_privileges("bob") == dict(_registry())
    assert {row["username"]: row["role"] for row in mgr.list_users()}["bob"] is None


def test_a_role_survives_a_restart(tmp_path):
    """It is in `auth.json`, which is the file that already answers who may do
    what — not a second store."""
    auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("operator", {"can_use_bash": True})
    mgr.set_user_role("bob", "operator")

    reloaded = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    assert reloaded.get_role("bob") == "operator"
    assert reloaded.get_privileges("bob")["can_use_bash"] is True


def test_list_users_carries_the_role_so_a_panel_can_show_it(tmp_path):
    _auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("operator", {"can_use_bash": True})
    mgr.set_user_role("bob", "operator")
    rows = {row["username"]: row for row in mgr.list_users()}
    assert rows["bob"]["role"] == "operator"
    assert rows["admin"]["role"] is None


def test_the_status_route_says_which_role_the_caller_holds(tmp_path):
    """The resolved privileges carry the role's effect; the name is what lets a
    surface explain it (`Law 15`)."""
    _auth_mod, mgr = _mgr(tmp_path)
    mgr.define_role("operator", {"can_use_bash": True})
    mgr.set_user_role("bob", "operator")
    token = mgr.create_session_trusted("bob")

    status = mgr.status(token)
    assert status["role"] == "operator"
    assert status["privileges"]["can_use_bash"] is True
    assert mgr.status(mgr.create_session_trusted("admin"))["role"] is None


def test_the_agent_cannot_reach_the_role_routes(tmp_path):
    """A role can set the six auth throttles `_SELF_RESTRAINT_KEYS` keeps the
    agent away from, so it must not become a second door to them.

    `app_api`'s prefix blocklist already refuses `/api/auth`, and every role
    route is under it. Asserted against the two real objects — the live router
    and the live blocklist tuple — rather than against either file's text.
    """
    from routes.auth_routes import setup_auth_routes
    from src.tools.system import _APP_API_BLOCKLIST_PREFIXES

    _auth_mod, mgr = _mgr(tmp_path)
    router = setup_auth_routes(mgr)
    role_paths = [r.path for r in router.routes
                  if "/roles" in getattr(r, "path", "")
                  or getattr(r, "path", "").endswith("/role")]
    assert len(role_paths) == 4
    for path in role_paths:
        assert any(path.startswith(prefix)
                   for prefix in _APP_API_BLOCKLIST_PREFIXES), path


def test_a_corrupt_privilege_map_resolves_to_the_declared_defaults(tmp_path):
    """`{**DEFAULT_PRIVILEGES, **stored}` raised on a non-dict, and
    `require_privilege` answers an exception by returning the user — i.e. by
    granting. It degrades to the registry now."""
    _auth_mod, mgr = _mgr(tmp_path)
    mgr._config["users"]["bob"]["privileges"] = ["can_use_bash"]
    assert mgr.get_privileges("bob") == dict(_registry())
