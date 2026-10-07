# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared owner identity constants and helpers."""

from __future__ import annotations

import logging
import os
from typing import Optional


DEFAULT_LOCAL_OWNER = "__pantheon_local__"
DEFAULT_LOCAL_OWNER_LABEL = "Local"
INTERNAL_TOOL_USER = "internal-tool"

REQUEST_SENTINEL_OWNERS = frozenset({INTERNAL_TOOL_USER, "api", "demo", "system"})
RESERVED_AUTH_USERNAMES = REQUEST_SENTINEL_OWNERS | {DEFAULT_LOCAL_OWNER}


# `D-2026-10-07-02` §2 — the owner, verbatim: *"there is always authentication.
# What's toggleable is registration. We keep it this way."*
#
# Three variables once let Pantheon answer without a sign-in, and none of them
# does now. Each is still READ — by `ignored_auth_switches` alone — so that a
# host carrying one is told, once, at start, that it changed nothing; a setting
# that silently stops working is the `B96` failure in the other direction.
# The value each names is its no-sign-in value: `AUTH_ENABLED` off, the other
# two on. `PANTHEON_SINGLE_USER` defaulted ON, so it is named only when an
# operator wrote an on-word for it — unset was every install, and is not news.
_NO_SIGN_IN_VALUE = {
    "AUTH_ENABLED": False,
    "LOCALHOST_BYPASS": True,
    "PANTHEON_SINGLE_USER": True,
}

_IGNORED_WHY = {
    "AUTH_ENABLED": "it used to turn sign-in off",
    "LOCALHOST_BYPASS": "it used to let a request from this machine in without a sign-in",
    "PANTHEON_SINGLE_USER": "it used to file a calendar request with no sign-in under "
                            "a shared owner",
}


def ignored_auth_switches() -> dict[str, str]:
    """Each no-sign-in switch this environment sets to its no-sign-in value,
    with the value as the operator wrote it.

    Read through the shared vocabulary (`B91`, `src/env_flags.env_truthy`), so
    `AUTH_ENABLED=0`, `no`, `off` and `false` are all named — every one of them
    turned sign-in off before 2026-10-07 (`B96`) — and `LOCALHOST_BYPASS=1` is
    named although only `true` ever enabled it: either way the operator asked for
    a door that no longer exists. The literal reads are deliberate:
    `.pantheon/check-env-declared.py` counts a variable as read from a literal.
    """
    from src.env_flags import env_truthy

    raw = {
        "AUTH_ENABLED": os.environ.get("AUTH_ENABLED"),
        "LOCALHOST_BYPASS": os.environ.get("LOCALHOST_BYPASS"),
        "PANTHEON_SINGLE_USER": os.environ.get("PANTHEON_SINGLE_USER"),
    }
    return {name: value for name, value in raw.items()
            if env_truthy(value) is _NO_SIGN_IN_VALUE[name]}


def warn_ignored_auth_switches(logger: logging.Logger | None = None) -> dict[str, str]:
    """Say once, at start, that a no-sign-in switch this host sets is ignored.

    `D-2026-10-07-02` §2. Ignored and logged rather than refused at start, and
    the reason is the first run: an instance that ignores the switch stays up
    behind sign-in, and if it has no account yet its sign-in page asks for the
    admin account (`/api/auth/setup`) — the operator's next step is on the
    screen they open. Refusing to start would put the same instruction in a log
    and nothing on the screen. `log_once` keys each line by name, so a second
    caller in the same process says it at DEBUG.
    """
    from src.log_once import log_once

    log = logger or logging.getLogger(__name__)
    found = ignored_auth_switches()
    for name, value in found.items():
        log_once(
            log, logging.WARNING, f"auth-switch-ignored:{name}",
            "%s=%r is ignored: %s, and Pantheon always asks for a sign-in now "
            "(D-2026-10-07-02: \"there is always authentication. What's toggleable "
            "is registration.\"). An admin turns registration on or off in "
            "Settings > Users. Remove %s from your environment to silence this.",
            name, value, _IGNORED_WHY[name], name,
        )
    return found


def normalize_owner(owner: str | None) -> Optional[str]:
    """Normalize an owner-like value without inventing a fallback identity."""
    value = str(owner or "").strip()
    return value or None


def owner_key(owner: str | None) -> Optional[str]:
    normalized = normalize_owner(owner)
    return normalized.lower() if normalized else None


def is_request_sentinel_owner(owner: str | None) -> bool:
    return owner_key(owner) in REQUEST_SENTINEL_OWNERS


def effective_storage_owner(owner: str | None) -> Optional[str]:
    """Resolve the owner used for storage writes that need a real bucket.

    ``None`` means no signed-in owner. A request sentinel (``internal-tool``,
    ``api``…) is not a person and owns nothing. Until `D-2026-10-07-02` §2 an
    auth-off install resolved ``None`` to the reserved local owner; there is no
    such install now, and rows already written under that owner stay where they
    are (`DEFAULT_LOCAL_OWNER` stays reserved, so no account can take them).
    """
    normalized = normalize_owner(owner)
    if normalized:
        if is_request_sentinel_owner(normalized):
            return None
        return normalized
    return None


def is_default_local_owner(owner: str | None) -> bool:
    return owner_key(owner) == DEFAULT_LOCAL_OWNER
