# SPDX-License-Identifier: AGPL-3.0-or-later
"""Roles — named overlays on the registries that already declare policy.

`P11-02`, and the first word of it is *overlay*. This is not a second
authorization system: `core.auth.DEFAULT_PRIVILEGES` has been a control plane
since before the fork (nine booleans, one integer quota, one model allowlist)
and `src.settings`'s limit keys have been one since `P12-01`. A role is a
**named set of overrides on keys those two registries already declare**, and
nothing here can invent a key either of them does not.

RESOLUTION ORDER, and it is stated once, in one function.
`src.auth_helpers.resolve_privilege` answers *what does this privilege resolve
to* — stored value → role → the registry's declared value → denied — and
`AuthManager.get_privileges` is the caller that supplies the role. For limits
the same order already existed: `settings.resolve_limit` resolves role profile
→ instance setting → environment → built-in default, and `P12-01` left the role
leg as a **registered provider that nothing installed**, saying so out loud on
five `P12` rows. :func:`install_role_layer` installs it. That one call is why a
role can set a byte cap, an upload throttle and a login throttle without any of
those call sites changing.

`is_admin` IS the superuser role and is not replaced. 107 `require_admin` sites
depend on it (`.pantheon/P11-AUTH-MAP.md`), and an admin's privileges still
short-circuit to `ADMIN_PRIVILEGES` before a role is ever consulted. A role
cannot make somebody an admin and cannot take it away; that is
`PUT /api/auth/users/{u}/admin` and it is a different decision.

TWO NAMESPACES, ONE STORE, AND THE SPLIT IS DERIVED. A role's overrides are
validated key by key against the registry that declares the key —
`DEFAULT_PRIVILEGES` for privileges, `settings.LIMIT_RANGES` for limits — so
there is no third list here to go stale (`Law 14`). A key in neither is refused
at the door rather than stored and ignored (`P17-09`'s reasoning), because a
role that silently drops half of what an operator typed is worse than one that
says no.

An install with no roles defined behaves exactly as it did before this module
existed: every function here returns empty, the provider answers `None`, and
every layer below it decides (`Law 1`).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Mapping

logger = logging.getLogger(__name__)

#: Where a user's role is recorded on their `auth.json` row, and where the
#: catalogue lives in the same file. Both are absent on every install that has
#: never defined a role, which is what makes this additive.
USER_ROLE_FIELD = "role"
ROLE_CATALOGUE_KEY = "roles"

#: Names that would read as "this is the superuser role" and are not.
#: `is_admin` is the superuser role; a *different* thing called `admin` is the
#: `_ADMIN_TOOLS` collision (`P11-02c`) waiting to happen in a second medium.
RESERVED_ROLE_NAMES = frozenset({
    "admin", "admins", "administrator", "superuser", "super-user", "owner",
    "root", "none", "default",
})

#: Lowercase, no leading space, no punctuation that would need escaping in a
#: URL path segment. The name is an identity, a JSON key and a path parameter.
_ROLE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

MAX_ROLES = 64


class RoleError(ValueError):
    """A role definition that cannot be stored, with the reason in the message.

    A `ValueError` subclass rather than an `HTTPException` so this module stays
    importable without FastAPI and testable without a request: the route layer
    turns it into a 400 and keeps the sentence.
    """


def normalize_role_name(name: Any) -> str:
    """The stored spelling of a role name, or raise :class:`RoleError`.

    Case-folded and stripped, because a role assigned as `Operator` and defined
    as `operator` that silently never matches is the worst possible failure for
    a permission system — it grants nothing and looks configured.
    """
    text = str(name or "").strip().lower()
    if not text:
        raise RoleError("A role needs a name.")
    if text in RESERVED_ROLE_NAMES:
        raise RoleError(
            f"'{text}' is reserved. Administrator access is the `is_admin` flag, "
            "not a role — see PUT /api/auth/users/{username}/admin."
        )
    if not _ROLE_NAME_RE.match(text):
        raise RoleError(
            "A role name is 1-40 characters of a-z, 0-9, '-' or '_', starting "
            "with a letter or digit."
        )
    return text


def privilege_keys() -> frozenset[str]:
    """The privilege keys a role may override — the live registry, per call.

    Imported per call rather than bound at module import, for the reason
    `resolve_privilege` already carries: a key added to `DEFAULT_PRIVILEGES` is
    live without restarting the process, and a module-level binding here would
    quietly make that untrue for roles alone.
    """
    from core.auth import DEFAULT_PRIVILEGES
    return frozenset(DEFAULT_PRIVILEGES)


def limit_keys() -> frozenset[str]:
    """The limit keys a role may override — `settings.role_limit_ranges()`.

    Was `LIMIT_RANGES`, which answers a narrower question: *which settings keys
    are **nullable** integer limits*, i.e. what `POST /api/auth/settings`
    validates. `P12-02` found four limits that resolve through
    `settings.resolve_limit` **with an owner** — so the role leg is consulted
    for them on every call — and ship a real default rather than `None`:
    `task_concurrency_cap`, `upload_burst_limit`, `upload_burst_window_seconds`
    and `approval_timeout_seconds`. The provider could never answer for any of
    them, which is `Law 13`'s unwired half wearing a resolution order.

    `role_limit_ranges()` is `LIMIT_RANGES` plus those four, with each one's
    bounds imported from the module that owns the limit. It is a derivation, not
    a third list (`Law 14`), and it is still the same table
    `POST /api/auth/settings` clamps the nullable keys against — so a role and
    an instance setting still refuse exactly the same values.
    """
    from src.settings import role_limit_ranges
    return frozenset(role_limit_ranges())


def _check_privilege_value(key: str, value: Any) -> Any:
    from core.auth import DEFAULT_PRIVILEGES
    declared = DEFAULT_PRIVILEGES[key]
    if isinstance(declared, bool):
        if not isinstance(value, bool):
            raise RoleError(f"{key} must be true or false.")
        return value
    if isinstance(declared, int):
        # `True` is an `int` in Python and a message quota of 1 is not what
        # anyone meant — the same trap `settings._coerce_limit` refuses.
        if isinstance(value, bool) or not isinstance(value, int):
            raise RoleError(f"{key} must be a whole number.")
        if value < 0:
            raise RoleError(f"{key} cannot be negative.")
        return value
    if isinstance(declared, list):
        if not isinstance(value, (list, tuple)):
            raise RoleError(f"{key} must be a list of model names.")
        out = [str(v) for v in value]
        if any(not v.strip() for v in out):
            raise RoleError(f"{key} cannot contain an empty name.")
        return out
    raise RoleError(f"{key} is declared with a type roles cannot carry.")


def _check_limit_value(key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RoleError(f"{key} must be a whole number.")
    # The floor is 1 and there is no value meaning *off*: `FORBIDDEN.md` Part 2
    # keeps the upload caps and the auth rate limiters as controls that never
    # lift, and a role is not a way around a list that says *never*. The
    # ceiling is `settings.resolve_limit`'s, applied at read time to every
    # layer alike, so a role cannot be the one layer that skips the clamp.
    if value < 1:
        raise RoleError(f"{key} must be at least 1 — there is no value meaning 'off'.")
    return value


def validate_overrides(overrides: Any) -> Dict[str, Any]:
    """A role's stored body, or raise :class:`RoleError` naming the first fault.

    Refuses an unknown key rather than dropping it. A permission system that
    accepts `can_use_bsah: true` with a 200 has told the operator they granted
    something they did not, which is `P11-01`'s fail-open defect wearing the
    other hat — there, a typo granted; here, a typo would appear to.
    """
    if overrides is None:
        return {}
    if not isinstance(overrides, Mapping):
        raise RoleError("A role is an object of key/value overrides.")
    allowed_privs = privilege_keys()
    allowed_limits = limit_keys()
    clean: Dict[str, Any] = {}
    for raw_key, value in overrides.items():
        key = str(raw_key)
        if key in allowed_privs:
            clean[key] = _check_privilege_value(key, value)
        elif key in allowed_limits:
            clean[key] = _check_limit_value(key, value)
        else:
            raise RoleError(
                f"'{key}' is not a privilege or a limit this build declares. "
                "A role may only override keys that already exist."
            )
    return clean


def privilege_overrides(role_body: Any) -> Dict[str, Any]:
    """The privilege half of a stored role body. Never raises."""
    if not isinstance(role_body, Mapping):
        return {}
    keys = privilege_keys()
    return {k: v for k, v in role_body.items() if k in keys}


def limit_overrides(role_body: Any) -> Dict[str, Any]:
    """The limit half of a stored role body. Never raises."""
    if not isinstance(role_body, Mapping):
        return {}
    keys = limit_keys()
    return {k: v for k, v in role_body.items() if k in keys}


def describe(name: str, role_body: Any) -> Dict[str, Any]:
    """One catalogue entry, split into the two namespaces it spans.

    Split rather than handed over flat because a screen that lists nine
    booleans next to a byte count with no divider is the surface `Law 15`
    fails: they are read at different times by different people.
    """
    return {
        "name": name,
        "privileges": privilege_overrides(role_body),
        "limits": limit_overrides(role_body),
    }


# ── the limit layer `P12-01` left registered and empty ──────────────────────

def install_role_layer(auth_manager: Any) -> None:
    """Point `settings.role_limit` at this instance's role catalogue.

    `P12-01` built the registry and said what would fill it: *"`P11-02` builds
    roles as named overlays on `DEFAULT_PRIVILEGES`; when it lands it calls
    `set_role_limit_provider` once at start-up and every limit in the product
    inherits the layer in that one edit."* This is that call, and the whole
    reason it is one line is that `resolve_limit` is already the only place a
    numeric limit is decided.

    The provider answers **only** keys `settings.LIMIT_RANGES` declares. A role
    may also carry privilege keys and those are not limits; answering one here
    would put a boolean into `_coerce_limit`, and `True` is an `int`.

    Never raises into the caller: `settings.role_limit` swallows and logs, and
    a role system that throws must not take an upload route down with it.
    """
    def _provider(key: str, owner: Any) -> Any:
        if key not in limit_keys():
            return None
        return role_overrides_for(auth_manager, owner).get(key)

    from src.settings import set_role_limit_provider
    set_role_limit_provider(_provider)
    logger.info("Role limit layer installed")


def clear_role_layer() -> None:
    """Remove the provider. Tests use this; so does a torn-down role system."""
    from src.settings import clear_role_limit_provider
    clear_role_limit_provider()


def role_overrides_for(auth_manager: Any, username: Any) -> Dict[str, Any]:
    """Every override the named user's role carries, or `{}`. Never raises.

    Duck-typed on purpose. The provider above is installed from `app.py`'s one
    `AuthManager`, and this is also reached from tests with a stand-in; an
    object that cannot answer is the same case as a user with no role.
    """
    try:
        getter = getattr(auth_manager, "role_overrides_for_user", None)
        if getter is None:
            return {}
        found = getter(username)
        return found if isinstance(found, dict) else {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("role lookup failed for %r: %s", username, exc)
        return {}
