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


_warned_auth_spelling = False


def _warn_old_auth_spelling(raw: str) -> None:
    """Say it out loud, once, when this boot is one the old rule read differently.

    `B96`. Until 2026-09-15 only the literal `false` disabled authentication, so
    `AUTH_ENABLED=0` left it **on** — an operator typed the disabling value,
    believed the switch was off, and it was not. Correcting that is the fix and
    it is also the only change in this row that can surprise a running host: the
    three spellings below used to leave auth enabled and now disable it.

    Logged rather than migrated because there is nothing to migrate — the value
    lives in the operator's environment, not in a file this process may rewrite.
    Announcing it at the moment it takes effect is the honest half of the
    `B90` `_warn_stored_no_beats_env` answer, applied to the layer below.
    """
    global _warned_auth_spelling
    if _warned_auth_spelling:
        return
    _warned_auth_spelling = True
    logging.getLogger(__name__).warning(
        "AUTH_ENABLED=%r now DISABLES authentication. Before 2026-09-15 only the "
        "literal `false` did, so this host booted with auth ENABLED despite this "
        "setting (`B96`). If you meant auth on, set AUTH_ENABLED=true or unset it.",
        raw,
    )


def auth_disabled() -> bool:
    """Return True only when auth is explicitly disabled by configuration.

    `B96`. Reads the shared vocabulary (`B91`), so `0`, `no` and `off` disable
    auth alongside `false` — they are the words `.env.example` documents as the
    opposite of `true`, and until 2026-09-15 every one of them left auth on.
    The default is ON: an unset, blank or unrecognised value keeps
    authentication, which is the direction this switch must fail in.
    """
    from src.env_flags import OFF_VALUES, env_flag
    disabled = not env_flag("AUTH_ENABLED", True)
    if disabled:
        raw = os.getenv("AUTH_ENABLED", "")
        # `false` is the one spelling that already disabled auth, so a host
        # carrying it is not changing behaviour and has nothing to be told.
        if raw.strip().lower() in (OFF_VALUES - {"false"}):
            _warn_old_auth_spelling(raw)
    return disabled


def normalize_owner(owner: str | None) -> Optional[str]:
    """Normalize an owner-like value without inventing a fallback identity."""
    value = str(owner or "").strip()
    return value or None


def owner_key(owner: str | None) -> Optional[str]:
    normalized = normalize_owner(owner)
    return normalized.lower() if normalized else None


def is_request_sentinel_owner(owner: str | None) -> bool:
    return owner_key(owner) in REQUEST_SENTINEL_OWNERS


def effective_storage_owner(owner: str | None, *, auth_is_disabled: bool | None = None) -> Optional[str]:
    """Resolve the owner used for storage writes that need a real bucket.

    ``None`` still means no authenticated owner when auth is enabled. In the
    explicit no-login mode, it resolves to the reserved local owner instead of
    conflating local-operator writes with legacy NULL/ownerless rows.
    """
    normalized = normalize_owner(owner)
    if normalized:
        if is_request_sentinel_owner(normalized):
            return None
        return normalized
    disabled = auth_disabled() if auth_is_disabled is None else auth_is_disabled
    if disabled:
        return DEFAULT_LOCAL_OWNER
    return None


def is_default_local_owner(owner: str | None) -> bool:
    return owner_key(owner) == DEFAULT_LOCAL_OWNER
