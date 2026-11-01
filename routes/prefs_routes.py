# SPDX-License-Identifier: AGPL-3.0-or-later
"""User preferences API — per-user key/value store backed by a JSON file."""
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from core.atomic_io import atomic_write_json
from src.auth_helpers import get_current_user
from src.constants import USER_PREFS_FILE
from services.tts.personal_voice import (
    CONVERSATION_PREF, CONVERSATION_VOICE_PREF, checked_conversation, checked_voice)

PREFS_FILE = USER_PREFS_FILE
_FOREGROUND_POLICY_KEYS = (
    "foreground_fallback_enabled",
    "foreground_model_fallbacks",
)


def _load():
    """Load the raw prefs file (internal use only).

    `{}` here means "nobody has saved a preference yet" to every caller, and
    `_save` writes whatever the caller then hands back. One file holds every
    user, so a corrupt read followed by one person changing one preference
    would erase everybody's — `P3-16`. `_save` refuses while the file is in
    that state, so the empty dict cannot become the file.
    """
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(prefs):
    atomic_write_json(PREFS_FILE, prefs, indent=2, preserve_unreadable=True)


def _load_for_user(user: Optional[str] = None) -> dict:
    """Load preferences for a specific user."""
    all_prefs = _load()
    users = all_prefs.get("_users")
    if isinstance(users, dict):
        if user is None:
            # Auth disabled — return first user's prefs for backward compat
            prefs = dict(next(iter(users.values()), {}))
            # Foreground fallback consent is never borrowed from a named
            # owner. Auth-disabled operation has a separate flat/root opt-in
            # that remains inert when authentication is enabled again.
            for key in _FOREGROUND_POLICY_KEYS:
                prefs.pop(key, None)
                if key in all_prefs:
                    prefs[key] = all_prefs[key]
            return prefs
        prefs = users.get(user, {})
        return dict(prefs) if isinstance(prefs, dict) else {}
    # A legacy flat store belongs only to auth-disabled single-user mode.
    # Copying it into the first named user's new `_users` record during an
    # auth transition would silently transfer another user's preferences and,
    # critically, foreground fallback consent. Named owners therefore start
    # with an empty record and must write their own preferences explicitly.
    return dict(all_prefs) if user is None else {}


def _save_for_user(user: Optional[str], prefs: dict):
    """Save preferences for a specific user."""
    all_prefs = _load()
    if user is None:
        # Auth disabled. If the store is already multi-user (e.g. auth was
        # turned off on a deployment that previously ran multi-user), writing
        # `prefs` flat would overwrite the whole `_users` map and destroy every
        # other user's preferences. Instead write back into the same (first)
        # slot _load_for_user(None) reads from, preserving the others.
        users = all_prefs.get("_users")
        if isinstance(users, dict):
            first_key = next(iter(users), None)
            if first_key is not None:
                existing_named = users.get(first_key)
                existing_named = (
                    dict(existing_named)
                    if isinstance(existing_named, dict)
                    else {}
                )
                named_foreground = {
                    key: existing_named[key]
                    for key in _FOREGROUND_POLICY_KEYS
                    if key in existing_named
                }
                users[first_key] = {
                    key: value
                    for key, value in prefs.items()
                    if key not in _FOREGROUND_POLICY_KEYS
                }
                users[first_key].update(named_foreground)
                for key in _FOREGROUND_POLICY_KEYS:
                    if key in prefs:
                        all_prefs[key] = prefs[key]
                _save(all_prefs)
                return
        _save(prefs)
        return
    if not isinstance(all_prefs.get("_users"), dict):
        # Preserve the flat single-user object as inert legacy data while
        # creating the first named-owner namespace. In particular, historical
        # fallback values must not be deleted or copied into the new owner.
        all_prefs = dict(all_prefs)
        all_prefs["_users"] = {}
    all_prefs["_users"][user] = prefs
    _save(all_prefs)


#: `B1196`. A person's own keyboard shortcuts — `{action: combo}` — over the
#: instance's (`POST /api/auth/settings` `keybinds`, an admin's, which is the
#: platform's default: `D-2026-10-25-04` §2, "a person's own pick still wins
#: for them"). Keybinds were instance-only, so a non-admin's rebind was refused
#: "Admin only." and could not be made at all. Held to a shape here because the
#: page merges this map over the defaults on every load.
KEYBINDS_PREF = "keybinds"
_KEYBIND_MAX_ENTRIES = 200
_KEYBIND_MAX_LEN = 64


def _checked_keybinds(value):
    """The stored map, or a 400 saying what is wrong with it."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(400, "Your shortcuts are an object of action → key combination.")
    if len(value) > _KEYBIND_MAX_ENTRIES:
        raise HTTPException(400, f"That is more than {_KEYBIND_MAX_ENTRIES} shortcuts.")
    clean = {}
    for action, combo in value.items():
        if not isinstance(action, str) or not action.strip() or len(action) > _KEYBIND_MAX_LEN:
            raise HTTPException(400, f"'{str(action)[:40]}' is not a shortcut's name.")
        if not isinstance(combo, str) or len(combo) > _KEYBIND_MAX_LEN:
            raise HTTPException(400, f"The key combination for '{action}' is not one.")
        clean[action] = combo.strip().lower()
    return clean


def setup_prefs_routes():
    router = APIRouter(prefix="/api/prefs", tags=["preferences"])

    @router.get("")
    async def get_all_prefs(request: Request):
        user = get_current_user(request)
        return _load_for_user(user)

    @router.get("/{key}")
    async def get_pref(request: Request, key: str):
        user = get_current_user(request)
        prefs = _load_for_user(user)
        return {"key": key, "value": prefs.get(key)}

    @router.put("/{key}")
    async def set_pref(request: Request, key: str, body: dict):
        user = get_current_user(request)
        prefs = _load_for_user(user)
        value = body.get("value")
        if key == KEYBINDS_PREF:
            value = _checked_keybinds(value)   # `B1196`
        elif key in (CONVERSATION_PREF, CONVERSATION_VOICE_PREF):
            # `B1730`. Each person's Conversation switch and their own voice,
            # which the voice service reads on every sentence it says to them.
            value = (checked_conversation(value) if key == CONVERSATION_PREF
                     else checked_voice(value))
        prefs[key] = value
        _save_for_user(user, prefs)
        return {"key": key, "value": prefs[key]}

    return router
