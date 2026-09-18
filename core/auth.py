# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Authentication module — multi-user password hashing, session tokens, config persistence.
Config stored in data/auth.json. Uses bcrypt directly.
"""

import enum
import json
import os
import secrets
import threading
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import bcrypt
import pyotp

logger = logging.getLogger(__name__)


from core.atomic_io import (  # noqa: E402
    UnreadableTargetError,
    atomic_write_json as _atomic_write_json,
)

DEFAULT_PRIVILEGES = {
    "can_use_agent": True,
    "can_use_browser": True,
    "can_use_bash": False,
    "can_use_documents": True,
    "can_use_research": True,
    "can_generate_images": True,
    "can_manage_memory": True,
    "max_messages_per_day": 0,
    "allowed_models": [],
    "allowed_models_restricted": False,
    # Explicit "block every model" sentinel. An empty `allowed_models` list is
    # ambiguous — it's also what gets sent when the admin clicks "[All]" — so
    # we need a dedicated flag to express "this user may use no models at all"
    # distinctly from "this user has no restriction".
    "block_all_models": False,
}

# Admins get everything
ADMIN_PRIVILEGES = {k: (True if isinstance(v, bool) else (0 if isinstance(v, int) else [])) for k, v in DEFAULT_PRIVILEGES.items()}
ADMIN_PRIVILEGES["allowed_models_restricted"] = False
# Admins must never be blocked from using models — the generic dict
# comprehension above flips every boolean default to True, which would be
# backwards for this sentinel.
ADMIN_PRIVILEGES["block_all_models"] = False

from src.constants import AUTH_FILE, PASSWORD_MIN_LENGTH
from src.owner_identity import RESERVED_AUTH_USERNAMES
# One spelling for the two `auth.json` keys `P11-02` adds. They are defined in
# `src/roles.py` beside the rules that govern them and imported here rather
# than written out again, so a rename cannot land on one file only (`Law 7`).
from src.roles import ROLE_CATALOGUE_KEY, USER_ROLE_FIELD
DEFAULT_AUTH_PATH = AUTH_FILE
TOKEN_TTL = 60 * 60 * 24 * 7  # 7 days

# Usernames the auth + middleware layer reserves for request sentinels and
# internal storage owners; they must never belong to a real login account.
# "internal-tool" is the most dangerous because `core.middleware.require_admin`
# treats it as the in-process tool loopback. "api" collides with bearer-token
# attribution. "demo"/"system" are synthetic owners already special-cased by
# scheduler/assistant/research paths. The Default/Local owner is a storage
# bucket for explicit auth-disabled no-login mode, not a login username.
RESERVED_USERNAMES = frozenset(RESERVED_AUTH_USERNAMES)


def normalize_known_username(users: Dict[str, Any], username: str | None) -> Optional[str]:
    """Return a normalized username only when it exists in the auth user map."""
    key = str(username or "").strip().lower()
    if not key or key not in users:
        return None
    return key


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


class SetAdminResult(enum.Enum):
    """Outcome of AuthManager.set_admin, so callers can map each case to a
    precise response instead of guessing from a bare bool."""
    OK = "ok"
    USER_NOT_FOUND = "user_not_found"
    NOT_AUTHORIZED = "not_authorized"   # requester is not an admin
    LAST_ADMIN = "last_admin"           # would remove the last remaining admin


class AuthManager:
    """Manages multi-user password + session-token auth system."""

    def __init__(self, auth_path: str = DEFAULT_AUTH_PATH):
        self.auth_path = auth_path
        self._sessions_path = os.path.join(os.path.dirname(auth_path), "sessions.json")
        self._config: Dict[str, Any] = {}
        # `P3-16`. Set when `auth.json` exists and could not be read. An
        # unreadable user database is not an empty one, and the difference
        # decides whether this process offers first-run setup to a stranger and
        # then saves their new account over everybody else's.
        self._load_error: Optional[str] = None
        self._sessions: Dict[str, Dict[str, Any]] = {}  # token -> {username, expiry}
        # Guards mutations of self._sessions and the on-disk sessions.json.
        # Validate/create/revoke run concurrently from the FastAPI threadpool.
        self._sessions_lock = threading.RLock()
        # Guards all mutations of self._config and the on-disk auth.json so
        # concurrent create/delete/rename/privilege operations don't interleave
        # and corrupt the user database.
        self._config_lock = threading.Lock()
        # Guards the first-run setup check-and-write so concurrent requests
        # cannot both observe is_configured==False and both create admin accounts.
        self._setup_lock = threading.Lock()
        self._load()
        self._load_sessions()
        self._migrate_single_user()
        self._drop_reserved_loaded_users()
        self._migrate_legacy_admin_role()

    def _load(self):
        try:
            if os.path.exists(self.auth_path):
                with open(self.auth_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                # Normalize all stored usernames to lowercase so they match
                # the .strip().lower() applied at login/verify time. Fixes
                # "Invalid credentials" when auth.json was written with
                # mixed-case keys (e.g. via manual edit or a future migration).
                if "users" in self._config:
                    self._config["users"] = {
                        k.strip().lower(): v
                        for k, v in self._config["users"].items()
                    }
                logger.info("Auth config loaded")
            else:
                self._config = {}
                logger.info("No auth config found — first-run setup required")
        except Exception as e:
            # `P3-16`, and this is the PandaOS failure exactly. The old line
            # here was `self._config = {}` and nothing else — so a truncated,
            # unparseable or unreadable `auth.json` became "no users", which
            # makes `is_configured` False, which puts the app into first-run
            # setup. The first person to reach that box gets an admin account,
            # and `create_user` calls `_save()`, which writes the one-user
            # config straight over the file nobody could read. Total account
            # loss and a handover, from one failed `json.load`.
            #
            # Remembered rather than re-derived: if the operator repairs the
            # file while this process is running, `self._config` is still the
            # empty dict this branch produced, and a write-time check alone
            # would happily persist it over the repaired file.
            self._load_error = f"{e.__class__.__name__}: {e}"
            logger.critical(
                "Failed to load auth config from %s: %s. Refusing to treat this "
                "as an empty user database: first-run setup stays closed and "
                "nothing will be written to that file until it can be read.",
                self.auth_path, e,
            )
            self._config = {}

    def _load_sessions(self):
        """Load persisted session tokens from disk, pruning expired ones."""
        try:
            if os.path.exists(self._sessions_path):
                with open(self._sessions_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                now = time.time()
                self._sessions = {k: v for k, v in data.items() if v.get("expiry", 0) > now}
                pruned = len(data) - len(self._sessions)
                if pruned > 0:
                    self._save_sessions()
                logger.info(f"Loaded {len(self._sessions)} session(s) from disk")
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")
            self._sessions = {}

    def _save_sessions(self):
        """Persist session tokens to disk (atomic, lock-guarded)."""
        try:
            with self._sessions_lock:
                snapshot = dict(self._sessions)
            _atomic_write_json(self._sessions_path, snapshot)
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    def _migrate_single_user(self):
        """Migrate old single-user format to multi-user format."""
        if "password_hash" in self._config and "users" not in self._config:
            old_user = str(self._config.get("username", "admin") or "admin").strip().lower()
            if old_user in RESERVED_USERNAMES:
                logger.warning(
                    "Migrating legacy single-user reserved username '%s' to 'admin'",
                    old_user,
                )
                old_user = "admin"
            old_hash = self._config["password_hash"]
            with self._config_lock:
                self._config = {
                    "users": {
                        old_user: {
                            "password_hash": old_hash,
                            "created": time.time(),
                            "is_admin": True,
                        }
                    }
                }
                self._save()
            logger.info(f"Migrated single-user auth to multi-user (admin: {old_user})")

    def _drop_reserved_loaded_users(self):
        """Fail closed for legacy/manual auth rows that collide with sentinels."""
        users = self._config.get("users")
        if not isinstance(users, dict):
            return
        normalized = {}
        removed = []
        for username, data in users.items():
            key = str(username or "").strip().lower()
            if not key:
                continue
            if key in RESERVED_USERNAMES:
                removed.append(key)
                continue
            normalized[key] = data
        if removed or normalized != users:
            with self._config_lock:
                self._config["users"] = normalized
                self._save()
        if removed:
            logger.warning(
                "Removed reserved username(s) from auth config: %s",
                ", ".join(sorted(set(removed))),
            )

    def _migrate_legacy_admin_role(self):
        """Normalize setup.py's old role='admin' marker to is_admin=True."""
        changed = False
        for username, user in self.users.items():
            if user.get("role") == "admin" and "is_admin" not in user:
                user["is_admin"] = True
                changed = True
                logger.info(f"Migrated legacy admin role for '{username}'")
        if changed:
            self._save()

    def _save(self):
        if self._load_error:
            # `P3-16`: no write may be derived from a read that failed.
            raise UnreadableTargetError(
                f"refusing to write {self.auth_path}: this process could not read "
                f"it at startup ({self._load_error}), so the user database in "
                "memory is empty for that reason and not because there are no "
                "users. Repair the file and restart."
            )
        _atomic_write_json(self.auth_path, self._config, indent=2, preserve_unreadable=True)

    @property
    def users(self) -> Dict[str, Any]:
        return self._config.get("users", {})

    @property
    def signup_enabled(self) -> bool:
        return self._config.get("signup_enabled", False)

    @signup_enabled.setter
    def signup_enabled(self, value: bool):
        with self._config_lock:
            self._config["signup_enabled"] = value
            self._save()

    @property
    def is_configured(self) -> bool:
        # `P3-16`. False is the permissive answer everywhere this is consumed —
        # it means "first run", which opens setup (`setup`), lets loopback
        # callers through unauthenticated (`auth_helpers`), redirects to the
        # setup page (`app.py`) and hands note admin rights to anyone
        # (`note_routes`). An unreadable file must never produce it. True is
        # the safe answer: with no users loaded, `is_admin` says no and every
        # gate closes.
        if self._load_error:
            return True
        return len(self.users) > 0

    def policy(self) -> dict:
        """Return public auth policy constants for the frontend."""
        return {
            "password_min_length": PASSWORD_MIN_LENGTH,
            "reserved_usernames": sorted(RESERVED_USERNAMES),
            "signup_enabled": self.signup_enabled,
            "session_days": TOKEN_TTL // 86400,
        }

    # ------------------------------------------------------------------
    # Account management
    # ------------------------------------------------------------------

    def setup(self, username: str, password: str) -> bool:
        """First-run admin setup. Only works if no users exist."""
        with self._setup_lock:
            if self.is_configured:
                return False
            return self.create_user(username, password, is_admin=True)

    def create_user(self, username: str, password: str, is_admin: bool = False) -> bool:
        """Create a new user account."""
        username = username.strip().lower()
        if not username:
            return False
        if username in RESERVED_USERNAMES:
            logger.warning("Refused to create reserved username '%s'", username)
            return False
        with self._config_lock:
            if username in self.users:
                return False
            if "users" not in self._config:
                self._config["users"] = {}
            self._config["users"][username] = {
                "password_hash": _hash_password(password),
                "created": time.time(),
                "is_admin": is_admin,
                # `P11-02`. A new non-admin starts with NO per-user overrides,
                # not a full copy of the registry. The effective map is
                # identical — `get_privileges` resolves an absent key to what
                # `DEFAULT_PRIVILEGES` declares — and the difference is the
                # whole role layer: a stored map that names all eleven keys is
                # eleven per-user overrides, and per-user beats role, so a copy
                # of the defaults here would have shadowed every role on every
                # user created through the normal path. Admins keep theirs:
                # the map is inert while `is_admin` is set (`get_privileges`
                # short-circuits) and `set_admin` reads it as the demotion
                # stash.
                "privileges": dict(ADMIN_PRIVILEGES) if is_admin else {},
            }
            self._save()
        logger.info(f"Created user '{username}' (admin={is_admin})")
        return True

    def delete_user(self, username: str, requesting_user: str) -> bool:
        """Delete a user. Only admins can delete, and can't delete themselves.

        SECURITY: also revoke every active session token belonging to this
        user so any open browser tab they have gets kicked back to /login
        on the next request. Without this the user kept full access until
        their cookie expired naturally (default ~30 days).
        """
        username = username.strip().lower()
        with self._config_lock:
            if username not in self.users:
                return False
            if username == requesting_user:
                return False
            if not self.users.get(requesting_user, {}).get("is_admin"):
                return False
            # Revoke API bearer tokens before removing the auth row. The bearer
            # path authenticates from ApiToken rows and does not require the
            # owner to still exist, so a successful delete must not leave active
            # rows behind. If the token store is unavailable, fail closed and
            # keep the user/session state intact so the admin can retry.
            try:
                from core.database import get_db_session, ApiToken
                with get_db_session() as db:
                    removed_tokens = db.query(ApiToken).filter(ApiToken.owner == username).delete()
                if removed_tokens:
                    logger.info(
                        f"Revoked {removed_tokens} API token(s) owned by deleted user '{username}'"
                    )
            except Exception:
                logger.warning(f"Failed to revoke API tokens for deleted user '{username}'")
                return False
            del self._config["users"][username]
            self._save()
        # Purge all sessions belonging to this user. validate_token doesn't
        # cross-check `self.users`, so without this step a deleted user's
        # cookie keeps authenticating.
        revoked = 0
        with self._sessions_lock:
            to_drop = [tok for tok, sess in self._sessions.items()
                       if (sess or {}).get("username") == username]
            for tok in to_drop:
                self._sessions.pop(tok, None)
                revoked += 1
        if revoked:
            self._save_sessions()
        logger.info(f"Deleted user '{username}' (by {requesting_user}); revoked {revoked} active session(s)")
        return True

    def rename_user(self, old_username: str, new_username: str, requesting_user: str) -> bool:
        """Rename a user in auth config and active sessions. Admin only."""
        old_username = old_username.strip().lower()
        new_username = new_username.strip().lower()
        requesting_user = (requesting_user or "").strip().lower()
        if not old_username or not new_username:
            return False
        if new_username in RESERVED_USERNAMES:
            logger.warning("Refused to rename '%s' into reserved username '%s'", old_username, new_username)
            return False
        with self._config_lock:
            if old_username not in self.users:
                return False
            if new_username in self.users:
                return False
            if not self.users.get(requesting_user, {}).get("is_admin"):
                return False
            self._config.setdefault("users", {})[new_username] = self._config["users"].pop(old_username)
            self._save()

        renamed_sessions = 0
        with self._sessions_lock:
            for sess in self._sessions.values():
                sess_user = str((sess or {}).get("username") or "").strip().lower()
                if sess_user == old_username:
                    sess["username"] = new_username
                    renamed_sessions += 1
        if renamed_sessions:
            self._save_sessions()
        logger.info(
            "Renamed user '%s' -> '%s' (by %s); updated %d active session(s)",
            old_username, new_username, requesting_user, renamed_sessions,
        )
        return True

    def is_admin(self, username: str) -> bool:
        return self.users.get(username, {}).get("is_admin", False)

    def list_users(self) -> List[Dict[str, Any]]:
        return [
            {"username": u, "is_admin": d.get("is_admin", False),
             "role": self.get_role(u),
             "privileges": self.get_privileges(u)}
            for u, d in self.users.items()
        ]

    def get_privileges(self, username: str) -> Dict[str, Any]:
        """Get privileges for a user. Admins get all privileges.

        `P11-02`. Three layers, resolved **built-in default → role → user**,
        and the order lives in exactly one function:
        `src.auth_helpers.resolve_privilege`. This method's job is to say who
        the user is and what their role carries; it does not decide anything
        itself, because a second place that decides is how the two answers
        drift apart (`Law 13`).

        `is_admin` still short-circuits, and still to `ADMIN_PRIVILEGES`. It is
        the superuser role: it outranks every named role, a role cannot confer
        it, and the 107 `require_admin` sites in
        `.pantheon/P11-AUTH-MAP.md` keep reading exactly the flag they read
        before.

        With no roles defined the loop below returns what
        `{**DEFAULT_PRIVILEGES, **stored}` returned — for every declared key,
        `resolve_privilege` with no role IS that merge — so an install that has
        never named a role is byte-for-byte unchanged (`Law 1`).
        """
        from src.auth_helpers import resolve_privilege

        user = self.users.get(username, {})
        if user.get("is_admin"):
            return dict(ADMIN_PRIVILEGES)
        stored = user.get("privileges", {})
        if not isinstance(stored, dict):
            # A hand-edited or truncated `auth.json` can put anything here, and
            # `{**DEFAULT_PRIVILEGES, **stored}` raised on it — which
            # `require_privilege` catches and answers by returning the user,
            # i.e. granting. Degrading to "no per-user overrides" resolves to
            # the declared defaults instead, which is `P11-01`'s rule applied
            # to the shape of the map rather than to one key.
            logger.warning(
                "Privileges for '%s' are %s, not an object — resolving to the "
                "declared defaults.", username, type(stored).__name__,
            )
            stored = {}
        role_overrides = self.role_overrides_for_user(username)
        # Keys nobody declared are carried through untouched: they are not
        # resolvable (nothing reads them) and dropping them would lose an
        # operator's hand-edit without saying so (`Law 1`).
        merged = {**DEFAULT_PRIVILEGES, **stored}
        for key in DEFAULT_PRIVILEGES:
            merged[key] = resolve_privilege(
                stored, key, role_overrides=role_overrides)
        return merged

    def set_privileges(self, username: str, privileges: Dict[str, Any]) -> bool:
        """Update privileges for a user. Can't modify admin privileges."""
        username = username.strip().lower()
        with self._config_lock:
            if username not in self.users:
                return False
            if self.users[username].get("is_admin"):
                return False  # admins always have full access
            # Only allow known privilege keys.
            #
            # `P11-02`. What is stored is the user's OVERRIDES, built on what
            # they already had — not the resolved map. Storing the resolved map
            # wrote every declared key on every save, which turned each of them
            # into a per-user override and made the role layer invisible for
            # anybody an admin had ever edited. Effective privileges are
            # unchanged either way, because an unstored key resolves to the
            # role's value and then to the registry's.
            #
            # `None` CLEARS an override rather than storing it: it is the third
            # value `B90` established for booleans, here meaning *inherit* —
            # the role's answer if it has one, the registry's if not. Without
            # it an admin can express "false" and "true" and has no way back to
            # "whatever the role says".
            stored = self.users[username].get("privileges")
            current = dict(stored) if isinstance(stored, dict) else {}
            for k, v in privileges.items():
                if k not in DEFAULT_PRIVILEGES:
                    continue
                if v is None:
                    current.pop(k, None)
                else:
                    current[k] = v
            self._config["users"][username]["privileges"] = current
            self._save()
        logger.info(f"Updated privileges for '{username}': {current}")
        return True

    # ------------------------------------------------------------------
    # Roles (`P11-02`) — named overlays on the registries, stored beside the
    # users they apply to.
    #
    # `auth.json` is the store because it is already the file that answers
    # "who may do what", it is already written atomically through `_save`, and
    # it is already the thing `P3-16` refuses to overwrite from a failed read.
    # A role table in a second place would be a second answer to the same
    # question (`Law 14`), and a database table would make authorization depend
    # on the database being up.
    #
    # Both keys are ABSENT on every install that has never defined a role, and
    # every method below returns empty in that case.
    # ------------------------------------------------------------------

    @property
    def roles(self) -> Dict[str, Dict[str, Any]]:
        """The role catalogue: name -> overrides. `{}` when none are defined."""
        found = self._config.get(ROLE_CATALOGUE_KEY)
        return found if isinstance(found, dict) else {}

    def list_roles(self) -> List[Dict[str, Any]]:
        """Every role, split into its privilege and limit halves."""
        from src.roles import describe
        return [describe(name, body) for name, body in sorted(self.roles.items())]

    def get_role(self, username: str) -> Optional[str]:
        """The role name on this user's row, or `None`.

        A name that is no longer in the catalogue answers `None`: deleting a
        role has to take its grants away, and a dangling name that kept
        resolving would be a permission nobody can see or revoke.
        """
        user = self.users.get(str(username or "").strip().lower(), {})
        name = user.get(USER_ROLE_FIELD)
        if not isinstance(name, str) or not name:
            return None
        return name if name in self.roles else None

    def role_overrides_for_user(self, username: Any) -> Dict[str, Any]:
        """Everything this user's role overrides. `{}` for admins and for
        users with no role — an admin's privileges are `ADMIN_PRIVILEGES`
        wholesale and no role layer applies to the superuser role."""
        key = str(username or "").strip().lower()
        if not key:
            return {}
        if self.users.get(key, {}).get("is_admin"):
            return {}
        name = self.get_role(key)
        if not name:
            return {}
        body = self.roles.get(name)
        return dict(body) if isinstance(body, dict) else {}

    def define_role(self, name: str, overrides: Dict[str, Any]) -> str:
        """Create or replace a role. Returns its stored name.

        Raises `src.roles.RoleError` with a sentence for the operator when the
        name or any override is refused — validation happens before anything is
        written, so a rejected definition leaves the catalogue exactly as it
        was.
        """
        from src.roles import RoleError, normalize_role_name, validate_overrides, MAX_ROLES

        key = normalize_role_name(name)
        body = validate_overrides(overrides)
        with self._config_lock:
            catalogue = self._config.get(ROLE_CATALOGUE_KEY)
            if not isinstance(catalogue, dict):
                catalogue = {}
            if key not in catalogue and len(catalogue) >= MAX_ROLES:
                raise RoleError(
                    f"This install already has {len(catalogue)} roles, which is "
                    "the ceiling. Delete one first."
                )
            catalogue[key] = body
            self._config[ROLE_CATALOGUE_KEY] = catalogue
            self._save()
        logger.info("Defined role '%s' with %d override(s)", key, len(body))
        return key

    def delete_role(self, name: str) -> bool:
        """Remove a role and take it off every user holding it.

        Both halves in one critical section and one `_save`. Leaving the name
        on a user row would be a grant with nothing behind it — `get_role`
        already refuses to resolve a dangling name, and leaving the row dirty
        would mean re-creating a role silently re-granted it to whoever used to
        hold it.
        """
        key = str(name or "").strip().lower()
        with self._config_lock:
            catalogue = self._config.get(ROLE_CATALOGUE_KEY)
            if not isinstance(catalogue, dict) or key not in catalogue:
                return False
            catalogue.pop(key, None)
            cleared = 0
            for row in self._config.get("users", {}).values():
                if isinstance(row, dict) and row.get(USER_ROLE_FIELD) == key:
                    row.pop(USER_ROLE_FIELD, None)
                    cleared += 1
            self._save()
        logger.info("Deleted role '%s'; cleared it from %d user(s)", key, cleared)
        return True

    def set_user_role(self, username: str, role: Optional[str]) -> bool:
        """Give a user a role, or `None` to take it away.

        Refuses an unknown role name rather than storing it: a role assigned
        before it is defined grants nothing and looks configured, which is the
        failure mode a permission surface can least afford.

        Admins are refused for the same reason `set_privileges` refuses them —
        `is_admin` is the superuser role and outranks every named one, so
        assigning a second role to an admin would store a decision that never
        applies.
        """
        from src.roles import RoleError

        key = str(username or "").strip().lower()
        with self._config_lock:
            row = self._config.get("users", {}).get(key)
            if row is None:
                return False
            if row.get("is_admin"):
                raise RoleError(
                    f"'{key}' is an admin. Administrator access is the superuser "
                    "role and outranks every named role; demote them first."
                )
            if role is None or not str(role).strip():
                if row.pop(USER_ROLE_FIELD, None) is None:
                    return True
                self._save()
                logger.info("Cleared role for '%s'", key)
                return True
            wanted = str(role).strip().lower()
            if wanted not in self.roles:
                raise RoleError(f"There is no role called '{wanted}'.")
            row[USER_ROLE_FIELD] = wanted
            self._save()
        logger.info("Set role '%s' for '%s'", wanted, key)
        return True

    def set_admin(self, username: str, is_admin: bool,
                  requesting_user: str) -> SetAdminResult:
        """Promote/demote an existing user to/from admin. Admin only.

        Refuses to remove the last remaining admin so the instance can never
        be locked out of admin access; self-demotion is allowed as long as
        another admin remains. Admin status is re-checked live on every
        request, so unlike delete/rename no session or token revocation is
        needed — a demoted admin simply fails the next is_admin() gate.

        Promotion stashes the user's current privilege map and demotion
        restores it, so a temporary admin stint can't silently broaden a
        user's non-admin access; users without a stash (created as admin,
        or promoted before stashing existed) demote to DEFAULT_PRIVILEGES.

        Counting admins and flipping the flag happen in one critical section
        so two concurrent demotions can't race the admin count to zero.
        """
        username = (username or "").strip().lower()
        requesting_user = (requesting_user or "").strip().lower()
        is_admin = bool(is_admin)
        with self._config_lock:
            target = self._config.get("users", {}).get(username)
            if target is None:
                return SetAdminResult.USER_NOT_FOUND
            if not self.users.get(requesting_user, {}).get("is_admin"):
                return SetAdminResult.NOT_AUTHORIZED
            currently_admin = bool(target.get("is_admin"))
            if currently_admin == is_admin:
                return SetAdminResult.OK  # no-op; leave privileges untouched
            if currently_admin and not is_admin:
                admin_count = sum(1 for d in self.users.values() if d.get("is_admin"))
                if admin_count <= 1:
                    return SetAdminResult.LAST_ADMIN
            # Write order matters for lock-free readers: get_privileges()
            # reads without _config_lock and trusts is_admin, so the admin
            # flag must be flipped while the stored map is safe to expose —
            # before writing admin privileges on promote, after restoring
            # the pre-admin map on demote.
            if is_admin:
                target["is_admin"] = True
                # Stash the pre-admin map so a later demotion can restore it.
                # While is_admin is set the stored map is inert: get_privileges
                # short-circuits to ADMIN_PRIVILEGES and set_privileges refuses
                # admins, so only set_admin ever touches the stash.
                # `dict(... or {})`, not `or DEFAULT_PRIVILEGES`: a user with
                # no per-user overrides has an empty map, and stashing the
                # registry instead would restore eleven overrides at demotion
                # and shadow their role forever after (`P11-02`). The
                # no-stash-at-all case is still answered with the defaults, on
                # demotion, where the reasoning belongs.
                target["privileges_before_admin"] = dict(
                    target.get("privileges") or {}
                )
                target["privileges"] = dict(ADMIN_PRIVILEGES)
            else:
                # Restore the stashed pre-admin map. Fall back to defaults for
                # users created as admins (their stored map is ADMIN_PRIVILEGES,
                # which must not leak past demotion — e.g. can_use_bash) and
                # for admins promoted before the stash existed.
                # `is None`, not falsiness: an empty stash is a real answer
                # ("this user had no per-user overrides") and `or` cannot tell
                # it from "there was no stash". The fallback below is for the
                # second case only.
                stash = target.pop("privileges_before_admin", None)
                target["privileges"] = (
                    dict(stash) if isinstance(stash, dict)
                    else dict(DEFAULT_PRIVILEGES)
                )
                target["is_admin"] = False
            self._save()
        logger.info("Set is_admin=%s for '%s' (by '%s')", is_admin, username, requesting_user)
        return SetAdminResult.OK

    def change_password(self, username: str, current_password: str, new_password: str) -> bool:
        username = username.strip().lower()
        if username not in self.users:
            return False
        if not _verify_password(current_password, self.users[username]["password_hash"]):
            return False
        with self._config_lock:
            self._config["users"][username]["password_hash"] = _hash_password(new_password)
            self._save()
        return True

    # ------------------------------------------------------------------
    # TOTP two-factor authentication
    # ------------------------------------------------------------------

    def totp_enabled(self, username: str) -> bool:
        """Check if 2FA is enabled for a user."""
        user = self.users.get(username.strip().lower(), {})
        return bool(user.get("totp_enabled"))

    def totp_generate_secret(self, username: str) -> Optional[str]:
        """Generate a new TOTP secret for a user. Returns the secret (not yet enabled)."""
        username = username.strip().lower()
        if username not in self.users:
            return None
        secret = pyotp.random_base32()
        with self._config_lock:
            self._config["users"][username]["totp_secret_pending"] = secret
            self._save()
        return secret

    def totp_get_provisioning_uri(self, username: str, secret: str) -> str:
        """Get the otpauth:// URI for QR code generation."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=username, issuer_name="Pantheon")

    def totp_confirm_enable(self, username: str, code: str) -> bool:
        """Verify a TOTP code against the pending secret, then enable 2FA."""
        username = username.strip().lower()
        user = self.users.get(username, {})
        secret = user.get("totp_secret_pending")
        if not secret:
            return False
        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=1):
            return False
        # Enable 2FA
        with self._config_lock:
            self._config["users"][username]["totp_secret"] = secret
            self._config["users"][username]["totp_enabled"] = True
            self._config["users"][username].pop("totp_secret_pending", None)
            # Generate backup codes
            backup = [secrets.token_hex(4) for _ in range(8)]
            self._config["users"][username]["totp_backup_codes"] = backup
            self._save()
        logger.info(f"2FA enabled for '{username}'")
        return True

    def totp_verify(self, username: str, code: str) -> bool:
        """Verify a TOTP code for login."""
        username = username.strip().lower()
        user = self.users.get(username, {})
        if not user.get("totp_enabled"):
            return True  # 2FA not enabled, always pass
        secret = user.get("totp_secret")
        if not secret:
            # 2FA is enabled but no secret is stored (corrupt/partially-written
            # auth.json). Fail closed — returning True here bypassed the second
            # factor entirely.
            return False
        # Check backup codes first
        backup = user.get("totp_backup_codes", [])
        if code in backup:
            with self._config_lock:
                backup.remove(code)
                self._config["users"][username]["totp_backup_codes"] = backup
                self._save()
            logger.info(f"Backup code used for '{username}' ({len(backup)} remaining)")
            return True
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)

    def totp_disable(self, username: str, password: str) -> bool:
        """Disable 2FA for a user. Requires password confirmation."""
        username = username.strip().lower()
        if not self.verify_password(username, password):
            return False
        with self._config_lock:
            self._config["users"][username].pop("totp_secret", None)
            self._config["users"][username].pop("totp_secret_pending", None)
            self._config["users"][username].pop("totp_backup_codes", None)
            self._config["users"][username]["totp_enabled"] = False
            self._save()
        logger.info(f"2FA disabled for '{username}'")
        return True

    # ------------------------------------------------------------------
    # Login / logout / session tokens
    # ------------------------------------------------------------------

    def verify_password(self, username: str, password: str) -> bool:
        username = username.strip().lower()
        if username not in self.users:
            return False
        return _verify_password(password, self.users[username]["password_hash"])

    def create_session(self, username: str, password: str) -> Optional[str]:
        """Verify credentials and return a session token, or None."""
        username = username.strip().lower()
        if not self.verify_password(username, password):
            return None
        return self.create_session_trusted(username)

    def create_session_trusted(self, username: str) -> Optional[str]:
        """Issue a session token for an already-verified user.
        Call only after verify_password (and TOTP if enabled) have passed."""
        username = username.strip().lower()
        token = secrets.token_hex(32)
        with self._config_lock:
            if username not in self.users:
                logger.warning("Refused to issue session for missing user '%s'", username)
                return None
            with self._sessions_lock:
                self._sessions[token] = {
                    "username": username,
                    "expiry": time.time() + TOKEN_TTL,
                }
        self._save_sessions()
        return token

    def validate_token(self, token: Optional[str]) -> bool:
        if not token:
            return False
        expired = False
        deleted_user = False
        with self._sessions_lock:
            session = self._sessions.get(token)
            if session is None:
                return False
            if time.time() > session["expiry"]:
                self._sessions.pop(token, None)
                expired = True
            else:
                # SECURITY: if the user record has since been removed (admin
                # deleted them while their cookie was still valid), drop the
                # session so the next request kicks them out instead of
                # silently authenticating against a non-existent account.
                if session.get("username") not in self.users:
                    self._sessions.pop(token, None)
                    deleted_user = True
        if expired or deleted_user:
            self._save_sessions()
            return False
        return True

    def get_username_for_token(self, token: Optional[str]) -> Optional[str]:
        """Return the username associated with a valid token."""
        if not token:
            return None
        expired = False
        deleted_user = False
        with self._sessions_lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if time.time() > session["expiry"]:
                self._sessions.pop(token, None)
                expired = True
            else:
                _u = session["username"]
                # SECURITY: orphan check — same rationale as validate_token.
                if _u not in self.users:
                    self._sessions.pop(token, None)
                    deleted_user = True
                else:
                    return _u
        if expired or deleted_user:
            self._save_sessions()
        return None

    def revoke_token(self, token: str):
        with self._sessions_lock:
            self._sessions.pop(token, None)
        self._save_sessions()

    def revoke_user_sessions(self, username: str, except_token: Optional[str] = None) -> int:
        """Revoke active browser sessions for a user, optionally preserving one."""
        username = username.strip().lower()
        revoked = 0
        with self._sessions_lock:
            to_drop = [
                token for token, session in self._sessions.items()
                if token != except_token and (session or {}).get("username") == username
            ]
            for token in to_drop:
                self._sessions.pop(token, None)
                revoked += 1
            if revoked:
                self._save_sessions()
        return revoked

    def status(self, token: Optional[str]) -> Dict[str, Any]:
        username = self.get_username_for_token(token)
        authenticated = username is not None
        result = {
            "configured": self.is_configured,
            "authenticated": authenticated,
            "username": username,
            "is_admin": self.is_admin(username) if username else False,
        }
        if authenticated:
            result["privileges"] = self.get_privileges(username)
            # `P11-02`. The resolved privileges already carry the role's effect;
            # the NAME is what lets a surface say *why* — "Operator" rather than
            # nine booleans a person has to reverse-engineer (`Law 15`). `None`
            # for an admin and for anyone with no role.
            result["role"] = self.get_role(username)
        return result
