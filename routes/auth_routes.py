# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authentication routes — login, logout, signup, status, user management."""

from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel
from typing import Optional
import asyncio
import logging
import os

import json
import re
from pathlib import Path

from core.atomic_io import atomic_write_json, atomic_write_text
from core.auth import (
    AuthManager, DEFAULT_PRIVILEGES, RESERVED_USERNAMES, SetAdminResult, TOKEN_TTL,
)
from core.middleware import require_admin
from src.events import record_auth_event
# Imported under its own name, never aliased. An aliased auth call is
# invisible to `.pantheon/check-auth-map.py`'s call-graph closure — which
# is the exact defect that hid five `require_admin` gates in
# `webhook_routes.py` and made `P11-02b`'s count wrong in both directions.
from src.auth_helpers import get_current_user
from src.roles import RoleError, describe as describe_role
from src.constants import DEEP_RESEARCH_DIR, MEMORY_FILE, PASSWORD_MIN_LENGTH, SKILLS_DIR
from src.rate_limiter import RateLimiter
from src.settings_scrub import scrub_settings
from src.settings import (
    load_settings as _load_settings,
    save_settings as _save_settings,
    load_features as _load_features,
    save_features as _save_features,
    DEFAULT_SETTINGS,
    ENV_BACKED_FLAGS,
    LIMIT_RANGES,
    RETIRED_SETTING_KEYS,
    without_retired_settings,
)
from src.tool_capabilities import TrustRung
from src.integrations import (
    load_integrations,
    add_integration,
    update_integration,
    delete_integration,
    get_integration,
    mask_integration_secret,
    execute_api_call,
    INTEGRATION_PRESETS,
    migrate_from_settings,
)

logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = True
    totp_code: Optional[str] = None


class SetupRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class DeleteUserRequest(BaseModel):
    username: str


class RenameUserRequest(BaseModel):
    username: str


class SetAdminRequest(BaseModel):
    is_admin: bool


class SetOpenRegistrationRequest(BaseModel):
    enabled: bool


class DefineRoleRequest(BaseModel):
    """A role body: the overrides, flat, keyed exactly as the registries key
    them. Deliberately not split into `privileges` / `limits` on the wire — the
    split is derived from which registry declares each key (`src/roles.py`), and
    asking the caller to classify a key is asking them to get it wrong."""
    overrides: dict = {}


class SetUserRoleRequest(BaseModel):
    """`role: null` takes the role away; there is no separate DELETE for it."""
    role: Optional[str] = None

SESSION_COOKIE = "pantheon_session"


def _secure_cookie(request: Request) -> bool:
    """Decide the ``Secure`` attribute of the session cookie.

    ``SECURE_COOKIES`` stays authoritative when it holds an explicit value:
    ``true`` always marks the cookie Secure (the documented knob for a TLS
    proxy), ``false`` never does, which is the escape hatch for an install
    that still answers on plain HTTP alongside HTTPS. Anything else —
    unset, or the present-but-empty value docker-compose injects for a
    variable the host has not defined — derives it from the request, so an
    HTTPS login gets a Secure cookie without any configuration.

    Either the connection scheme or ``X-Forwarded-Proto`` saying https is
    enough, which is the same test ``core/middleware.py`` applies before it
    sends HSTS. Uvicorn's proxy-headers middleware already folds that header
    into the scheme for the proxies it trusts, so reading it here only adds
    the case of a terminator that is not on a trusted address; the cost is
    that a client talking to the app directly can set the header and lock
    its own session out over plain HTTP.
    """
    # env-spelling: `B91` holds this one, and it is the only site whose
    # tri-state is deliberate rather than accidental — `env_flags.env_truthy`
    # returns `None` for exactly this shape and this site is why. It stays on
    # its own rule because widening it would make `SECURE_COOKIES=1` mean *true*
    # where it means *auto-detect* today, and on a plain-HTTP deployment that
    # sets a Secure cookie the browser will not send back: the operator is
    # locked out of their own instance by an upgrade.
    configured = os.getenv("SECURE_COOKIES", "").strip().lower()
    if configured in ("true", "false"):
        return configured == "true"
    # A chained proxy sends a list — the client-facing hop comes first.
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0]
    return request.url.scheme == "https" or forwarded_proto.strip().lower() == "https"


def setup_auth_routes(auth_manager: AuthManager) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    # `P12-05b`. The numbers below are the BUILT-IN DEFAULTS, not the limits.
    # Each limiter re-reads `auth_*_rate_limit` / `auth_*_rate_window_seconds`
    # from the settings store on every `check()`, so an admin who lowers the
    # login-attempt limit has the next attempt honour it with no restart.
    # Until 2026-09-18 these three were literals and an operator could not
    # change a throttle without a rebuild — the thing the owner asked for by
    # name ("adding admin controls, such as throttling and such").
    #
    # `FORBIDDEN.md` Part 2 keeps these as a control that never lifts, and
    # `RateLimiter.effective` resolves with `minimum=1`: the number is policy,
    # the limiter is not. The agent may read these keys and may not write them
    # — see `_SELF_RESTRAINT_KEYS` in `src/agent_tools/admin_tools.py`.
    _login_limiter = RateLimiter(
        max_requests=15, window_seconds=60,
        limit_key="auth_login_rate_limit",
        window_key="auth_login_rate_window_seconds")
    _signup_limiter = RateLimiter(
        max_requests=3, window_seconds=300,
        limit_key="auth_signup_rate_limit",
        window_key="auth_signup_rate_window_seconds")
    _setup_limiter = RateLimiter(
        max_requests=3, window_seconds=300,
        limit_key="auth_setup_rate_limit",
        window_key="auth_setup_rate_window_seconds")

    def _get_current_user(request: Request) -> Optional[str]:
        token = request.cookies.get(SESSION_COOKIE)
        return auth_manager.get_username_for_token(token)

    @router.post("/setup")
    async def first_run_setup(body: SetupRequest, request: Request):
        """Create initial admin account. Only works if no accounts exist."""
        if not _setup_limiter.check(request.client.host):
            record_auth_event("setup", outcome="error",
                              detail={"reason": "rate_limited"})
            raise HTTPException(429, "Too many requests — try again later")
        if auth_manager.is_configured:
            raise HTTPException(400, "Already configured")
        if len(body.password) < PASSWORD_MIN_LENGTH:
            raise HTTPException(400, f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
        if len(body.username.strip()) < 1:
            raise HTTPException(400, "Username is required")
        if body.username.lower() in RESERVED_USERNAMES:
            raise HTTPException(403, "Username is reserved")
        ok = await asyncio.to_thread(auth_manager.setup, body.username, body.password)
        if not ok:
            record_auth_event("setup", subject=body.username, outcome="error",
                              detail={"reason": "setup_failed"})
            raise HTTPException(500, "Setup failed")
        record_auth_event("user_create", actor=body.username,
                          subject=body.username,
                          detail={"via": "setup", "is_admin": True})
        return {"ok": True, "message": "Admin account created"}

    @router.post("/signup")
    async def signup(body: SignupRequest, request: Request):
        """Create a new user account. Only works if signup is enabled by admin."""
        if not _signup_limiter.check(request.client.host):
            record_auth_event("user_create", outcome="error",
                              detail={"via": "signup", "reason": "rate_limited"})
            raise HTTPException(429, "Too many requests — try again later")
        if not auth_manager.is_configured:
            raise HTTPException(400, "Run setup first")
        if not auth_manager.signup_enabled:
            record_auth_event("user_create", subject=body.username, outcome="error",
                              detail={"via": "signup", "reason": "signup_disabled"})
            raise HTTPException(403, "Registration is disabled. Ask an admin for an account.")
        if len(body.password) < PASSWORD_MIN_LENGTH:
            raise HTTPException(400, f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
        if len(body.username.strip()) < 1:
            raise HTTPException(400, "Username is required")
        if body.username.lower() in RESERVED_USERNAMES:
            raise HTTPException(403, "Username is reserved")
        ok = await asyncio.to_thread(auth_manager.create_user, body.username, body.password, is_admin=False)
        if not ok:
            record_auth_event("user_create", subject=body.username, outcome="error",
                              detail={"via": "signup", "reason": "username_taken"})
            raise HTTPException(409, "Username already taken")
        record_auth_event("user_create", actor=body.username, subject=body.username,
                          detail={"via": "signup", "is_admin": False})
        return {"ok": True, "message": "Account created"}

    @router.post("/login")
    async def login(body: LoginRequest, request: Request, response: Response):
        if not _login_limiter.check(request.client.host):
            record_auth_event("login", actor=body.username, outcome="error",
                              detail={"reason": "rate_limited"})
            raise HTTPException(429, "Too many requests — try again later")
        # Verify password first
        username = body.username.strip().lower()
        if not await asyncio.to_thread(auth_manager.verify_password, username, body.password):
            # The reason is `invalid_credentials` whether the account exists or
            # not, deliberately: the 401 above does not distinguish them and an
            # audit row that does would be a username oracle for anyone who can
            # read it, which on a shared instance is every admin.
            record_auth_event("login", actor=username, outcome="error",
                              detail={"reason": "invalid_credentials"})
            raise HTTPException(401, "Invalid credentials")
        # Check 2FA if enabled
        if auth_manager.totp_enabled(username):
            if not body.totp_code:
                # Password OK but need TOTP — tell client to show code input
                return {"ok": False, "requires_totp": True, "username": username}
            if not auth_manager.totp_verify(username, body.totp_code):
                record_auth_event("login", actor=username, outcome="error",
                                  detail={"reason": "invalid_totp"})
                raise HTTPException(401, "Invalid 2FA code")
        # All checks passed — create session (password already verified above)
        token = await asyncio.to_thread(auth_manager.create_session_trusted, username)
        if not token:
            record_auth_event("login", actor=username, outcome="error",
                              detail={"reason": "session_refused"})
            raise HTTPException(401, "Invalid credentials")
        cookie_kwargs = dict(
            key=SESSION_COOKIE,
            value=token,
            httponly=True,
            samesite="lax",
            secure=_secure_cookie(request),
            path="/",
        )
        if body.remember:
            cookie_kwargs["max_age"] = TOKEN_TTL
        response.set_cookie(**cookie_kwargs)
        record_auth_event("login", actor=username,
                          detail={"remember": bool(body.remember),
                                  "totp": auth_manager.totp_enabled(username)})
        return {"ok": True, "username": username}

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            # Resolved before the revoke, or there is nobody to name.
            record_auth_event("logout", actor=auth_manager.get_username_for_token(token))
            auth_manager.revoke_token(token)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @router.get("/status")
    async def auth_status(request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        result = auth_manager.status(token)
        result["signup_enabled"] = auth_manager.signup_enabled
        # Include the caller's effective privileges so the frontend can
        # hide / dim UI controls the user isn't allowed to use. Admins get
        # ADMIN_PRIVILEGES (everything on), regular users get their stored
        # set merged with DEFAULT_PRIVILEGES.
        try:
            u = result.get("username")
            if u:
                result["privileges"] = auth_manager.get_privileges(u)
        except Exception:
            pass
        return result

    @router.get("/policy")
    async def auth_policy():
        """Return public auth policy constants for the frontend."""
        return auth_manager.policy()

    @router.post("/change-password")
    async def change_password(body: ChangePasswordRequest, request: Request):
        user = _get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        if len(body.new_password) < PASSWORD_MIN_LENGTH:
            raise HTTPException(400, f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
        current_token = request.cookies.get(SESSION_COOKIE)
        ok = await asyncio.to_thread(auth_manager.change_password, user, body.current_password, body.new_password)
        if not ok:
            raise HTTPException(400, "Current password is incorrect")
        await asyncio.to_thread(auth_manager.revoke_user_sessions, user, current_token)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Two-factor authentication
    # ------------------------------------------------------------------

    @router.post("/2fa/setup")
    async def totp_setup(request: Request):
        """Generate a TOTP secret and return the QR code URI."""
        user = _get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        if auth_manager.totp_enabled(user):
            raise HTTPException(400, "2FA is already enabled")
        secret = auth_manager.totp_generate_secret(user)
        if not secret:
            raise HTTPException(500, "Failed to generate secret")
        uri = auth_manager.totp_get_provisioning_uri(user, secret)
        # Generate QR code as base64 PNG
        import qrcode, io, base64
        qr = qrcode.make(uri, box_size=6, border=2)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {"secret": secret, "uri": uri, "qr_code": f"data:image/png;base64,{qr_b64}"}

    class TotpVerifyRequest(BaseModel):
        code: str

    @router.post("/2fa/confirm")
    async def totp_confirm(body: TotpVerifyRequest, request: Request):
        """Verify a TOTP code to confirm 2FA setup. Returns backup codes."""
        user = _get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        if not auth_manager.totp_confirm_enable(user, body.code):
            raise HTTPException(400, "Invalid code — try again")
        backup = auth_manager.users.get(user, {}).get("totp_backup_codes", [])
        return {"ok": True, "backup_codes": backup}

    class TotpDisableRequest(BaseModel):
        password: str

    @router.post("/2fa/disable")
    async def totp_disable(body: TotpDisableRequest, request: Request):
        """Disable 2FA. Requires password confirmation."""
        user = _get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        if not auth_manager.totp_disable(user, body.password):
            raise HTTPException(400, "Invalid password")
        return {"ok": True}

    @router.get("/2fa/status")
    async def totp_status(request: Request):
        """Check if 2FA is enabled for the current user."""
        user = _get_current_user(request)
        if not user:
            raise HTTPException(401, "Not authenticated")
        return {"enabled": auth_manager.totp_enabled(user)}

    # Admin-only routes
    @router.get("/users")
    async def list_users(request: Request):
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        return {"users": auth_manager.list_users()}

    @router.post("/users")
    async def admin_create_user(body: CreateUserRequest, request: Request):
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        if len(body.password) < PASSWORD_MIN_LENGTH:
            raise HTTPException(400, f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
        if len(body.username.strip()) < 1:
            raise HTTPException(400, "Username is required")
        if body.username.lower() in RESERVED_USERNAMES:
            raise HTTPException(403, "Username is reserved")
        ok = auth_manager.create_user(body.username, body.password, body.is_admin)
        if not ok:
            record_auth_event("user_create", actor=user, subject=body.username,
                              outcome="error",
                              detail={"via": "admin", "reason": "username_taken"})
            raise HTTPException(409, "Username already taken")
        record_auth_event("user_create", actor=user, subject=body.username,
                          detail={"via": "admin", "is_admin": bool(body.is_admin)})
        return {"ok": True}

    @router.put("/users/{username}/privileges")
    async def update_user_privileges(username: str, request: Request):
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        body = await request.json()
        ok = auth_manager.set_privileges(username, body)
        if not ok:
            record_auth_event("privilege_change", actor=user, subject=username,
                              outcome="error",
                              detail={"reason": "not_found_or_admin"})
            raise HTTPException(404, "User not found or is admin")
        # The keys the admin actually moved, and what to. `P11-08` asks for
        # privilege grants specifically; a row saying only "privileges changed"
        # cannot answer *which* grant let somebody do the thing they did.
        record_auth_event(
            "privilege_change", actor=user, subject=username,
            detail={"set": {k: v for k, v in (body or {}).items() if v is not None},
                    "cleared": sorted(k for k, v in (body or {}).items() if v is None)})
        return {"ok": True, "privileges": auth_manager.get_privileges(username)}

    # ---- Roles (`P11-02`) ----
    #
    # These four are the caller `P11-02`'s role layer would otherwise not have.
    # A resolution layer nothing can reach is `Law 13`'s unwired half, and
    # "hand-edit auth.json and restart" is the failure `P11-11` was filed to
    # stop. `P11-11` is the SCREEN for these; this is the API under it.
    #
    # They gate with `core.middleware.require_admin` rather than this module's
    # inline `_get_current_user(...) + is_admin(...)` pattern, on purpose.
    # Only `require_admin` consults `auth_disabled()` (`B543`,
    # `.pantheon/P11-AUTH-MAP.md`), so the inline one refuses the single
    # operator of an auth-disabled box access to their own role catalogue; and
    # `check-auth-map.py`'s rule C ratchets the count of admin decisions taken
    # some other way, which may fall and may not rise. Both reasons point the
    # same way.

    @router.get("/roles")
    async def list_roles(request: Request):
        """Every defined role, split into its privilege and limit halves."""
        require_admin(request)
        return {"roles": auth_manager.list_roles(),
                "privilege_keys": sorted(DEFAULT_PRIVILEGES),
                "limit_keys": sorted(LIMIT_RANGES)}

    @router.put("/roles/{name}")
    async def upsert_role(name: str, body: DefineRoleRequest, request: Request):
        """Create or replace one role. Admin only."""
        require_admin(request)
        actor = get_current_user(request)
        try:
            stored = auth_manager.define_role(name, body.overrides)
        except RoleError as exc:
            record_auth_event("role_define", actor=actor, subject=name,
                              outcome="error", detail={"reason": str(exc)})
            raise HTTPException(400, str(exc))
        record_auth_event("role_define", actor=actor, subject=stored,
                          detail={"overrides": dict(body.overrides or {})})
        return {"ok": True, "role": describe_role(stored, auth_manager.roles.get(stored))}

    @router.delete("/roles/{name}")
    async def remove_role(name: str, request: Request):
        """Delete a role and take it off every user holding it. Admin only."""
        require_admin(request)
        actor = get_current_user(request)
        if not auth_manager.delete_role(name):
            record_auth_event("role_delete", actor=actor, subject=name,
                              outcome="error", detail={"reason": "not_found"})
            raise HTTPException(404, "No such role")
        record_auth_event("role_delete", actor=actor, subject=name)
        return {"ok": True}

    @router.put("/users/{username}/role")
    async def set_user_role(username: str, body: SetUserRoleRequest, request: Request):
        """Assign a role to a user, or clear it with `role: null`. Admin only."""
        require_admin(request)
        actor = get_current_user(request)
        try:
            ok = auth_manager.set_user_role(username, body.role)
        except RoleError as exc:
            record_auth_event("role_change", actor=actor, subject=username,
                              outcome="error", detail={"reason": str(exc)})
            raise HTTPException(400, str(exc))
        if not ok:
            record_auth_event("role_change", actor=actor, subject=username,
                              outcome="error", detail={"reason": "user_not_found"})
            raise HTTPException(404, "User not found")
        record_auth_event("role_change", actor=actor, subject=username,
                          detail={"role": body.role})
        return {"ok": True, "username": (username or "").strip().lower(),
                "role": auth_manager.get_role(username),
                "privileges": auth_manager.get_privileges(
                    (username or "").strip().lower())}

    @router.put("/users/{username}/rename")
    async def rename_user(username: str, body: RenameUserRequest, request: Request):
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        old_username = (username or "").strip().lower()
        new_username = (body.username or "").strip().lower()
        if not new_username:
            raise HTTPException(400, "Username required")
        if old_username == new_username:
            return {"ok": True, "username": new_username, "renamed_self": old_username == user}
        if old_username not in auth_manager.users:
            raise HTTPException(404, "User not found")
        if new_username in auth_manager.users:
            raise HTTPException(409, "Username already taken")

        # Gate on auth first. Every mutation below is contingent on this
        # succeeding — doing it last meant a rejected rename (e.g. reserved
        # username) left file-backed owner fields already rewritten with no
        # way to roll them back.
        ok = auth_manager.rename_user(old_username, new_username, user)
        if not ok:
            raise HTTPException(400, "Cannot rename user")

        def _rollback_auth_rename() -> bool:
            # On self-rename the admin session has already moved to the new
            # username, so the rollback must authenticate as the new user.
            rollback_user = new_username if user == old_username else user
            try:
                return bool(auth_manager.rename_user(new_username, old_username, rollback_user))
            except Exception as rollback_err:
                logger.error(
                    "Failed to roll back auth rename %s -> %s after owner migration failure: %s",
                    new_username, old_username, rollback_err,
                )
                return False

        # Usernames are ownership keys for user data. Rename the common
        # owner-scoped DB rows so the account keeps access to its sessions,
        # docs, email accounts, tasks, etc.
        try:
            from sqlalchemy import func
            from core.database import (
                Base,
                EmailAccount,
                SessionLocal,
                lock_email_account_owner_mutations,
            )
            db = SessionLocal()
            try:
                # Email-account defaults are protected by per-owner mutex rows.
                # A rename crosses two owner partitions, so lock both in the
                # shared helper's canonical order before inspecting either.
                lock_email_account_owner_mutations(
                    db, old_username, new_username
                )

                source_default_ids = [
                    row[0]
                    for row in (
                        db.query(EmailAccount.id)
                        .filter(
                            func.lower(EmailAccount.owner) == old_username,
                            EmailAccount.is_default == True,  # noqa: E712
                        )
                        .order_by(EmailAccount.created_at.asc(), EmailAccount.id.asc())
                        .all()
                    )
                ]
                destination_default_ids = [
                    row[0]
                    for row in (
                        db.query(EmailAccount.id)
                        .filter(
                            func.lower(EmailAccount.owner) == new_username,
                            EmailAccount.is_default == True,  # noqa: E712
                        )
                        .order_by(EmailAccount.created_at.asc(), EmailAccount.id.asc())
                        .all()
                    )
                ]
                if destination_default_ids:
                    clear_default_ids = (
                        destination_default_ids[1:] + source_default_ids
                    )
                else:
                    clear_default_ids = source_default_ids[1:]
                if clear_default_ids:
                    (
                        db.query(EmailAccount)
                        .filter(EmailAccount.id.in_(clear_default_ids))
                        .update(
                            {EmailAccount.is_default: False},
                            synchronize_session=False,
                        )
                    )

                for mapper in Base.registry.mappers:
                    model = mapper.class_
                    if not hasattr(model, "owner"):
                        continue
                    (
                        db.query(model)
                        .filter(func.lower(model.owner) == old_username)
                        .update({"owner": new_username}, synchronize_session=False)
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        except Exception as e:
            logger.error("Failed to rename owner references %s -> %s: %s", old_username, new_username, e)
            if not _rollback_auth_rename():
                logger.error(
                    "Auth rename %s -> %s could not be rolled back after owner migration failure",
                    old_username, new_username,
                )
            raise HTTPException(500, "Failed to rename user data")

        # Per-user prefs are JSON-backed, not SQL-backed.
        try:
            from routes.prefs_routes import _load as _load_prefs, _save as _save_prefs
            prefs = _load_prefs()
            users = prefs.get("_users") if isinstance(prefs, dict) else None
            if isinstance(users, dict):
                prefs_key = next(
                    (k for k in users if str(k).strip().lower() == old_username),
                    None,
                )
                new_taken = any(str(k).strip().lower() == new_username for k in users)
                if prefs_key is not None and not new_taken:
                    users[new_username] = users.pop(prefs_key)
                    _save_prefs(prefs)
        except Exception as e:
            logger.warning("Failed to rename user prefs %s -> %s: %s", old_username, new_username, e)

        # In-flight deep-research tasks live in the process-local
        # ResearchHandler registry. They are not covered by the persisted JSON
        # migration above, but the research routes filter and cancel by this
        # owner field while the job is running. Do this before sweeping
        # completed JSON files so a job that finishes during the rename saves
        # with the new owner or is caught by the disk sweep below.
        try:
            rh = getattr(request.app.state, "research_handler", None)
            rename_owner = getattr(rh, "rename_owner", None)
            if callable(rename_owner):
                rename_owner(old_username, new_username)
        except Exception as e:
            logger.warning("Failed to rename active research tasks %s -> %s: %s", old_username, new_username, e)

        # deep_research: each completed report is a standalone JSON file with
        # an `owner` field. research_routes filters by d.get("owner") == user,
        # so a stale owner makes every report invisible to the renamed user.
        try:
            dr_dir = Path(DEEP_RESEARCH_DIR)
            if dr_dir.is_dir():
                for p in dr_dir.glob("*.json"):
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                        if str(d.get("owner", "")).strip().lower() == old_username:
                            d["owner"] = new_username
                            atomic_write_json(str(p), d)
                    except Exception as err:
                        logger.warning("Failed to update research owner in %s: %s", p.name, err)
        except Exception as e:
            logger.warning("Failed to rename research owner references %s -> %s: %s", old_username, new_username, e)

        # memory.json: a flat JSON array where each entry carries an `owner`
        # field. memory_manager.load(owner=user) filters on it, so stale
        # entries disappear from the memory panel.
        try:
            if os.path.isfile(MEMORY_FILE):
                with open(MEMORY_FILE, encoding="utf-8") as fh:
                    entries = json.loads(fh.read())
                if isinstance(entries, list):
                    changed = False
                    for entry in entries:
                        if isinstance(entry, dict) and str(entry.get("owner", "")).strip().lower() == old_username:
                            entry["owner"] = new_username
                            changed = True
                    if changed:
                        atomic_write_json(MEMORY_FILE, entries)
        except Exception as e:
            logger.warning("Failed to rename memory.json owner references %s -> %s: %s", old_username, new_username, e)

        # uploads.json: upload rows use owner metadata for access checks and
        # owner-prefixed index keys for dedupe. Rename both so attachments keep
        # resolving after the account username changes.
        try:
            upload_handler = getattr(request.app.state, "upload_handler", None)
            rename_owner = getattr(upload_handler, "rename_owner", None)
            if callable(rename_owner):
                rename_owner(old_username, new_username)
        except Exception as e:
            logger.warning("Failed to rename upload owner references %s -> %s: %s", old_username, new_username, e)

        # direct personal RAG uploads live in per-owner directories and the
        # vector metadata also carries the username used for owner-filtered
        # search. Keep both in sync with the auth rename.
        try:
            from routes.personal_routes import rename_personal_upload_owner
            personal_docs_manager = getattr(request.app.state, "personal_docs_manager", None)
            if personal_docs_manager is not None:
                rag_manager = getattr(personal_docs_manager, "rag_manager", None)
                rename_personal_upload_owner(
                    old_username,
                    new_username,
                    personal_docs_manager=personal_docs_manager,
                    rag_manager=rag_manager,
                )
        except Exception as e:
            logger.warning("Failed to rename personal RAG upload owner references %s -> %s: %s", old_username, new_username, e)

        # skills: SKILL.md frontmatter carries owner: <username>; the usage
        # sidecar (_usage.json) keys entries as owner::skill-name. Both must
        # be updated or the renamed user's Skills panel goes empty.
        try:
            skills_root = Path(SKILLS_DIR)
            if skills_root.is_dir():
                _owner_re = re.compile(
                    r'(?m)^(owner:\s*)' + re.escape(old_username) + r'\s*$',
                    re.IGNORECASE,
                )
                for p in skills_root.rglob("SKILL.md"):
                    try:
                        text = p.read_text(encoding="utf-8")
                        new_text = _owner_re.sub(r'\g<1>' + new_username, text)
                        if new_text != text:
                            atomic_write_text(str(p), new_text)
                    except Exception as err:
                        logger.warning("Failed to update skill owner in %s: %s", p, err)
                usage_path = skills_root / "_usage.json"
                if usage_path.is_file():
                    try:
                        usage = json.loads(usage_path.read_text(encoding="utf-8"))
                        if isinstance(usage, dict):
                            new_usage = {}
                            changed = False
                            for k, v in usage.items():
                                owner_part, sep, skill_part = k.partition("::")
                                if sep and owner_part.lower() == old_username:
                                    new_usage[new_username + "::" + skill_part] = v
                                    changed = True
                                else:
                                    new_usage[k] = v
                            if changed:
                                atomic_write_json(str(usage_path), new_usage)
                    except Exception as err:
                        logger.warning("Failed to update skills usage keys %s -> %s: %s", old_username, new_username, err)
        except Exception as e:
            logger.warning("Failed to rename skills owner references %s -> %s: %s", old_username, new_username, e)

        # The in-memory session cache (session_manager.sessions) stores each
        # session's owner at load time. Without this patch the renamed user's
        # sessions are invisible on the next /api/sessions call because
        # get_sessions_for_user does an exact `s.owner == username` comparison
        # against stale in-memory values.
        sm = getattr(request.app.state, "session_manager", None)
        if sm is not None:
            for sess in list(getattr(sm, "sessions", {}).values()):
                if str(getattr(sess, "owner", None) or "").strip().lower() == old_username:
                    sess.owner = new_username

        # The owner-rename loop above updated ApiToken.owner in the DB, but the
        # bearer-token cache still maps each token to the OLD owner. Without
        # refreshing it, the renamed user's API tokens resolve to the old (now
        # non-existent) owner and stop reaching their data until the cache next
        # goes dirty. Invalidate it now, like the token CRUD routes do.
        invalidator = getattr(request.app.state, "invalidate_token_cache", None)
        if callable(invalidator):
            invalidator()
        return {"ok": True, "username": new_username, "renamed_self": old_username == user}

    @router.put("/users/{username}/admin")
    async def set_user_admin(username: str, body: SetAdminRequest, request: Request):
        """Promote/demote a user to/from admin. Admin only.

        The last remaining admin can't be demoted (no lockout). Self-demotion
        is allowed while another admin exists; the `self` flag tells the UI to
        reload the acting user into the normal-user view.
        """
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        result = auth_manager.set_admin(username, body.is_admin, user)
        if result is not SetAdminResult.OK:
            record_auth_event("admin_change", actor=user, subject=username,
                              outcome="error",
                              detail={"is_admin": bool(body.is_admin),
                                      "reason": result.value})
        if result is SetAdminResult.USER_NOT_FOUND:
            raise HTTPException(404, "User not found")
        if result is SetAdminResult.NOT_AUTHORIZED:
            raise HTTPException(403, "Admin only")
        if result is SetAdminResult.LAST_ADMIN:
            raise HTTPException(400, "Cannot demote the last admin")
        record_auth_event("admin_change", actor=user, subject=username,
                          detail={"is_admin": bool(body.is_admin)})
        target = (username or "").strip().lower()
        return {
            "ok": True,
            "is_admin": body.is_admin,
            "self": target == (user or "").strip().lower(),
        }

    @router.post("/signup-toggle", deprecated=True)
    async def toggle_signup(request: Request):
        """
        Toggle open registration on/off. Admin only.

        DEPRECATED: This endpoint uses toggle semantics which can lead to unsafe state changes.
        Use PUT /open-signup instead.

        This endpoint is kept for backward compatibility and may be removed in future versions.
        """
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        auth_manager.signup_enabled = not auth_manager.signup_enabled
        return {"ok": True, "signup_enabled": auth_manager.signup_enabled}

    @router.put("/open-signup")
    async def set_signup_enabled(body: SetOpenRegistrationRequest, request: Request):
        """Set open signup enabled state. Admin only."""
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        auth_manager.signup_enabled = body.enabled
        return {"ok": True,"signup_enabled": auth_manager.signup_enabled}

    @router.delete("/users")
    async def admin_delete_user(body: DeleteUserRequest, request: Request):
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")

        def _invalidate_api_token_cache():
            try:
                invalidator = getattr(request.app.state, "invalidate_token_cache", None)
                if invalidator:
                    invalidator()
            except Exception:
                pass

        try:
            ok = auth_manager.delete_user(body.username, user)
        except Exception:
            # delete_user can touch ApiToken rows before a later auth-store write
            # fails. Dirty the bearer cache anyway so a partial token purge does
            # not leave already-cached tokens authenticating until restart.
            _invalidate_api_token_cache()
            raise
        if not ok:
            record_auth_event("user_delete", actor=user, subject=body.username,
                              outcome="error", detail={"reason": "refused"})
            raise HTTPException(400, "Cannot delete user")
        record_auth_event("user_delete", actor=user, subject=body.username)
        # delete_user removes the user's ApiToken rows, but the bearer-auth
        # middleware serves from an in-memory prefix->token cache that only
        # rebuilds when flagged dirty. Without this, a deleted user's already
        # cached token keeps authenticating until some other token op or a
        # restart clears the cache. Mirror what the token routes do.
        _invalidate_api_token_cache()
        return {"ok": True}

    # ---- Feature visibility (admin-managed) ----

    @router.get("/features")
    async def get_features():
        """Public: returns which UI features are enabled."""
        return _load_features()

    @router.post("/features")
    async def set_features(request: Request):
        """Admin only: update feature toggles."""
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        body = await request.json()
        current = _load_features()
        for key in current:
            if key in body and isinstance(body[key], bool):
                current[key] = body[key]
        _save_features(current)
        return current

    # ---- App settings (admin-managed) ----

    @router.get("/settings")
    async def get_settings(request: Request):
        """Returns app settings. Admins get the full set; non-admins get
        a scrubbed copy with secret keys blanked. The frontend uses this
        for keybinds + TTS prefs, so it stays callable without admin."""
        user = _get_current_user(request)
        settings = without_retired_settings(_load_settings())
        if user and auth_manager.is_admin(user):
            return settings
        return scrub_settings(settings)

    @router.post("/networks/check")
    async def check_networks(request: Request):
        """Admin only: validate a proposed `networks` value and say what it claims.

        `P17-09`. One endpoint answering both questions the panel has, because
        both are answered by the same Python and a JavaScript copy of CIDR
        matching would be the rule living in two places (`Law 13`). Nothing is
        saved here — the panel asks about what is on screen, before the operator
        commits to it.
        """
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        body = await request.json()
        value = body.get("networks", [])
        probe = str(body.get("probe") or "").strip()
        from src.networks import matches_for, validate_networks
        return {
            "problems": validate_networks(value),
            "probe": probe,
            "matched": matches_for(value, probe) if probe else None,
        }

    @router.get("/networks/agent")
    async def network_agent_health(request: Request):
        """Admin only: is the network agent there, and is it the agent?

        `P17-01`. A 200 from the configured address is not enough — the most
        likely other listener on a LAN port is a router's admin page, and
        reporting that as a healthy agent sends the operator hunting the wrong
        fault. `netagent_client.health()` checks the name.
        """
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        from src import netagent_client
        if not netagent_client.configured():
            return {"configured": False, "reachable": False,
                    "detail": "No agent address and credential are set."}
        verdict = await netagent_client.health()
        verdict["configured"] = True
        return verdict

    @router.get("/networks/guard")
    async def host_guard_rules(request: Request):
        """Admin only: the agent's permanent list, read-only.

        `P17-11`. A boundary nobody can read is a boundary nobody can check, and
        showing it beside the editable list is the clearest way to say that only
        one of the two can be edited. Fetched from the agent when one is
        configured, so what is displayed is what that agent will actually apply —
        falling back to this build's copy when it is not, rather than showing
        nothing and letting the page imply there is no boundary.
        """
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        from src import netagent_client
        if netagent_client.configured():
            answer = await netagent_client.call("guard")
            if isinstance(answer.get("rules"), list):
                answer["source"] = "the configured agent"
                return answer
        from netagent import guard
        rules = guard.rules()
        return {"rules": rules, "count": len(rules),
                "source": "this build (no agent configured)"}

    @router.get("/networks/devices")
    async def network_devices(request: Request):
        """Admin only: the device inventory, refreshed from the agent if it is up.

        `P17-04`. The agent observes and this remembers, so a refresh is a merge
        rather than a replacement — a device that has gone quiet keeps its record
        and its name, because *"where is the printer"* has an answer even on a
        day the printer has not spoken.
        """
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        from src import device_inventory, netagent_client

        refreshed = None
        if netagent_client.configured():
            answer = await netagent_client.call("neighbours")
            rows = answer.get("neighbours") if isinstance(answer, dict) else None
            if isinstance(rows, list):
                refreshed = device_inventory.observe(rows)
            elif answer.get("error"):
                refreshed = {"error": answer["error"]}
        try:
            state = device_inventory.inventory()
        except device_inventory.DeviceStoreUnreadable as e:
            raise HTTPException(500, str(e))
        state["refreshed"] = refreshed
        return state

    @router.post("/networks/devices/name")
    async def name_network_device(request: Request):
        """Admin only: give a device a name that survives a DHCP reshuffle.

        It is hung on the MAC, which is the identity, so it survives by
        construction rather than by anybody remembering to move it.
        """
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        body = await request.json()
        from src import device_inventory
        mac = str(body.get("mac") or "")
        if not device_inventory.rename(mac, str(body.get("name") or "")):
            raise HTTPException(400, f"{mac!r} is not a MAC address")
        return {"ok": True}

    @router.get("/settings/flag-sources")
    async def settings_flag_sources(request: Request):
        """Admin only: which layer answers each tri-state env-backed flag.

        `B95`. `metrics_enabled`, `searxng_widen_engines` and
        `allow_model_download` ship `None` so a stored `False` can mean *no*
        rather than *unset* (`B90`, `D-2026-09-15-01`). A two-state checkbox
        cannot express that, and one that wrote `false` on first paint would
        manufacture for every operator who opens the panel exactly the choice
        `B90` was filed to stop. The panel needs three states and it needs to
        know what *unset* currently resolves to on this host — a compose file
        forwarding `${PANTHEON_ALLOW_MODEL_DOWNLOAD:-0}` makes "unset" a
        different sentence from "unset with nothing underneath".

        Admin-only for the same reason the full settings read is: it reports
        what the process environment says, which is deployment configuration.
        """
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        from src.settings import env_backed_flag_report
        return {"flags": env_backed_flag_report()}

    @router.post("/settings")
    async def set_settings(request: Request):
        """Admin only: update app settings."""
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        body = await request.json()
        current = _load_settings()
        # Per-key validation for numeric settings: coerce to int and clamp to a
        # sane range so a bad value can't disable the agent or let it run away.
        #
        # `P12`'s three limits import their bounds rather than restating them,
        # so the number this route stores and the number the resolver enforces
        # cannot drift into a settings page that lies about itself.
        from src.tool_approvals import (
            MAX_APPROVAL_TTL_SECONDS,
            MIN_APPROVAL_TTL_SECONDS,
        )
        from src.upload_limits import (
            MAX_UPLOAD_BURST_LIMIT,
            MAX_UPLOAD_BURST_WINDOW_SECONDS,
            MIN_UPLOAD_BURST_LIMIT,
            MIN_UPLOAD_BURST_WINDOW_SECONDS,
        )
        _INT_RANGES = {
            # `P12-06`. The per-client upload burst gate — N uploads per W
            # seconds, not N uploads in flight, whatever it used to be called.
            "upload_burst_limit": (
                MIN_UPLOAD_BURST_LIMIT, MAX_UPLOAD_BURST_LIMIT,
            ),
            "upload_burst_window_seconds": (
                MIN_UPLOAD_BURST_WINDOW_SECONDS, MAX_UPLOAD_BURST_WINDOW_SECONDS,
            ),
            # `P12-10`. How long an approval card stays answerable before it
            # closes as denied. The floor is not decoration: `0` here would be
            # an approval that never lapses, and `FORBIDDEN.md` Part 2 keeps
            # this store's TTL.
            "approval_timeout_seconds": (
                MIN_APPROVAL_TTL_SECONDS, MAX_APPROVAL_TTL_SECONDS,
            ),
            "agent_max_rounds": (1, 200),
            "agent_max_tool_calls": (0, 1000),  # 0 = unlimited
            # `P3-21`. 0 means "no lift — run presets at their own numbers",
            # which is a reachable, documented value rather than a disabled
            # setting. The top is a machine ceiling, not a budget: ten million
            # tokens is past any local context window and stops a typo from
            # becoming an unbounded generation.
            "local_inference_max_tokens": (0, 10_000_000),
            # `P16-19`. The exporter floors this itself; clamping here too keeps
            # the STORED value and the EFFECTIVE value the same number, so the
            # settings page never shows a `1` that is really a `10`.
            "otlp_interval_seconds": (10, 86400),
            # `H16`. Both feed a `while True` loop at startup. An hour of 25
            # makes `next_daily_run` compute a delay for a time that never
            # comes; a batch of 0 runs an audit that audits nothing, every
            # night, forever. Clamped here so the stored value and the
            # effective value are the same number.
            "skill_audit_hour": (0, 23),
            "skill_audit_batch": (1, 100),
            # `P14-07`. The two ceilings on document indexing, in MiB. `0` is a
            # real answer on both — no ceiling — so the floor of the range is 0
            # and not 1. The tops are sanity, not policy: a 4 GiB single file
            # and a 16 GiB in-memory index are past the point where the number
            # is a decision rather than a typo. Clamped here for the reason
            # stated above: `index_walk` falls back to the default on a value it
            # cannot use, and a stored number that is not the effective one is
            # the settings page lying about itself.
            "index_max_file_mb": (0, 4096),
            "index_budget_mb": (0, 16384),
            # `P15-08`. The floor under a schedulable task, in minutes. `0`
            # turns it off, which an operator whose tasks only touch their own
            # LAN is entitled to; a day is the top, because past that the floor
            # is not a floor, it is the schedule.
            "min_task_interval_minutes": (0, 1440),
        }
        # Per-key validation for settings whose values are a closed set. A
        # security setting must not be *quietly* rejected: `coerce_trust_rung`
        # deliberately falls back to the default rather than the strictest rung,
        # so an unrecognised value stored here would hand the operator less
        # protection than they asked for while answering 200 and echoing their
        # typo back. Refutation reproduced exactly that with `ask_every_tim`,
        # `Ask every time` and `ask-every-time`. Reject at the door instead.
        _ENUMS = {
            "trust_rung": tuple(rung.value for rung in TrustRung),
        }
        # `P12-01` / `P12-05b`. The eighteen numeric limits, whose shipped value
        # is `None` — the third value an integer needs so the flat merged dict
        # can hold *nothing is stored here* apart from *an operator typed this*
        # (`B90`, applied to numbers). `null` is therefore a legal value and
        # means "let the environment or the built-in default answer"; anything
        # else must be an integer, and is clamped here so the STORED value and
        # the EFFECTIVE value are the same number — the reasoning
        # `otlp_interval_seconds` and `index_max_file_mb` already carry.
        #
        # **The floor is 1 on every one of them, and it is deliberate.** A byte
        # cap of 0 rejects every upload while reading as a configured limit, and
        # `FORBIDDEN.md` Part 2 keeps the auth rate limiters as a control that
        # never lifts: there must be no value here meaning *off*. The ceilings
        # are sanity rather than policy — a terabyte cap and a day-long throttle
        # window are past the point where the number is a decision rather than a
        # typo.
        # `P11-02` moved the table to `src.settings.LIMIT_RANGES`: a role is a
        # named set of overrides and has to refuse exactly the keys this route
        # refuses, and two lists answering "which settings keys are limits" is
        # the fork `Law 14` exists to stop. The name below is unchanged, so the
        # validation under it reads as it did.
        _NULLABLE_INT_RANGES = LIMIT_RANGES
        # Settings whose value must be a map of strings. `otlp_headers` given a
        # list is *ignored* by the exporter rather than refused, which is the
        # same defect as the enum above wearing different clothes: a 200, the
        # operator's value echoed back, and a collector that never gets an auth
        # header. (`P16-19`)
        _STRING_MAPS = ("otlp_headers", "otlp_resource_attributes")
        for key in DEFAULT_SETTINGS:
            if key in RETIRED_SETTING_KEYS:
                continue
            if key not in body:
                continue
            val = body[key]
            if key in _ENUMS:
                if not isinstance(val, str) or val.strip().casefold() not in _ENUMS[key]:
                    raise HTTPException(
                        400,
                        f"{key} must be one of: {', '.join(_ENUMS[key])}",
                    )
                val = val.strip().casefold()
            if key in _INT_RANGES:
                lo, hi = _INT_RANGES[key]
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{key} must be an integer")
                val = max(lo, min(val, hi))
            if key in _NULLABLE_INT_RANGES:
                lo, hi = _NULLABLE_INT_RANGES[key]
                if val is None or (isinstance(val, str) and not val.strip()):
                    val = None
                else:
                    if isinstance(val, bool):
                        # `True` is an int in Python and a cap of 1 is not what
                        # anyone meant. Refuse rather than store a limit of one
                        # byte or one request.
                        raise HTTPException(
                            400,
                            f"{key} must be a whole number of "
                            f"{'seconds' if key.endswith('_seconds') else 'bytes or requests'}, "
                            f"or null to use the default")
                    try:
                        val = int(val)
                    except (TypeError, ValueError):
                        raise HTTPException(
                            400,
                            f"{key} must be an integer, or null to let the "
                            f"environment or the built-in default decide")
                    val = max(lo, min(val, hi))
            if key == "netagent_url" and str(val or "").strip():
                # `P17-01`. Same reasoning as the `networks` block below, and
                # `P17-09`'s lesson applied before it can happen again: this
                # route accepts the key only because the loop iterates
                # `DEFAULT_SETTINGS`, so an unparseable address would be stored
                # and then rejected silently by `agent_base()` on every call —
                # leaving the operator with a configured-looking agent that never
                # answers and nothing saying why. Empty stays legal; empty is
                # "no agent", which is the shipped state.
                from src.netagent_client import parse_agent_base
                if not parse_agent_base(val):
                    raise HTTPException(
                        400,
                        "netagent_url must be a plain http(s) origin such as "
                        "http://127.0.0.1:7010 — no path, no query string, and "
                        "no credentials in the URL.")
            if key in ("host_exec_denylist", "host_exec_allowlist"):
                # `P17-09`'s lesson a third time: a list stored and then silently
                # ignored is worse than a refusal, because the operator believes
                # they set a rule and the rule is not there.
                from src.host_exec_policy import validate as _validate_host_lists
                _problems = _validate_host_lists(val, key=key)
                if _problems:
                    raise HTTPException(400, " ".join(_problems))
            if key == "networks":
                # `P17-09`. `src/networks.py` is enforcing — it is consulted
                # inside `check_outbound_url` and `outbound_fetch` before DNS —
                # and until now this route accepted it with no validation at all,
                # purely because the loop iterates `DEFAULT_SETTINGS`. An
                # unparseable CIDR was stored, then dropped by `Network.__init__`
                # with a `logger.warning`, and the operator got a 200 with their
                # own text echoed back and a network that classifies nothing.
                # Same defect as `B63`'s compose warning and `P16-19`'s
                # unparseable OTLP endpoint: accepted, logged, and silently inert.
                #
                # The validator lives in `src/networks.py` beside the loader, so
                # the rule and the thing it describes cannot drift (`Law 13`).
                from src.networks import validate_networks
                problems = validate_networks(val)
                if problems:
                    raise HTTPException(400, "networks: " + " ".join(problems))
            if key in ENV_BACKED_FLAGS:
                # `B95`. The tri-state, refused at the door rather than stored
                # and silently misread. `null` is *unset* — let the environment
                # or the default answer — and `true`/`false` are the operator's
                # own yes and no. A string in this slot is judged by
                # `env_flags.env_truthy` downstream, so `"maybe"` would store
                # cleanly, read as unset, and leave the panel showing a choice
                # that is not being honoured: the `P17-09` shape, on the one
                # group of keys where one of them is a `Law 16` gate.
                if not (val is None or isinstance(val, bool)):
                    raise HTTPException(
                        400,
                        f"{key} must be true, false, or null (null means "
                        f"'let {ENV_BACKED_FLAGS[key][0]} or the default decide')")
            if key in _STRING_MAPS:
                if not isinstance(val, dict) or not all(
                        isinstance(k, str) and isinstance(v, (str, int, float, bool))
                        for k, v in val.items()):
                    raise HTTPException(400, f"{key} must be a map of names to values")
                val = {k: str(v) for k, v in val.items()}
            if key == "otlp_endpoint":
                # `P16-19`. Empty is the shipped state and means "no push". A
                # non-empty value that will not parse must be refused HERE: the
                # push loop only logs a warning and carries on, so accepting a
                # typo returns 200, echoes it back, and leaves the operator
                # watching a collector that will never receive anything. Same
                # reasoning as `trust_rung` above — a setting that does nothing
                # must not answer as though it did.
                val = (val or "").strip() if isinstance(val, str) else ""
                if val:
                    from src.otlp_export import normalise_endpoint
                    try:
                        normalise_endpoint(val)
                    except ValueError as e:
                        raise HTTPException(400, f"otlp_endpoint: {e}")
            if key == "source_url":
                # `P0-17`. Same reasoning as `otlp_endpoint` above and one step
                # sharper: this value is written into an `href` on the **login
                # page**, the one document served before anyone authenticates.
                # The renderer already refuses a non-http(s) scheme, so a bad
                # value cannot reach the DOM — but accepting it here would
                # answer 200, echo it back, and leave the operator looking at a
                # settings field that holds their URL and a page that shows no
                # link, with nothing saying why.
                val = (val or "").strip() if isinstance(val, str) else ""
                if val:
                    from src.source_link import normalise_source_url
                    if not normalise_source_url(val):
                        raise HTTPException(
                            400,
                            "source_url: must be an absolute http:// or https:// URL "
                            "(empty means no source link is shown)")
            current[key] = val
        _save_settings(current)
        return without_retired_settings(current)

    # ---- Integrations CRUD ----

    # Run migration on startup
    migrate_from_settings()

    @router.get("/integrations")
    async def list_integrations_route(request: Request):
        """List all integrations (admin only, keys masked)."""
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        items = load_integrations()
        # Mask API keys for frontend display
        safe = [mask_integration_secret(item) for item in items]
        return {"integrations": safe}

    @router.get("/integrations/presets")
    async def list_presets():
        """List available integration presets."""
        return {"presets": {k: {kk: vv for kk, vv in v.items() if kk != "api_key"} for k, v in INTEGRATION_PRESETS.items()}}

    @router.post("/integrations")
    async def create_integration(request: Request):
        """Create a new integration (admin only)."""
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        body = await request.json()
        item = add_integration(body)
        return {"ok": True, "integration": mask_integration_secret(item)}

    @router.put("/integrations/{integration_id}")
    async def update_integration_route(integration_id: str, request: Request):
        """Update an existing integration (admin only)."""
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        body = await request.json()
        item = update_integration(integration_id, body)
        if not item:
            raise HTTPException(404, "Integration not found")
        return {"ok": True, "integration": mask_integration_secret(item)}

    @router.delete("/integrations/{integration_id}")
    async def delete_integration_route(integration_id: str, request: Request):
        """Delete an integration (admin only)."""
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        ok = delete_integration(integration_id)
        if not ok:
            raise HTTPException(404, "Integration not found")
        return {"ok": True}

    @router.post("/integrations/{integration_id}/test")
    async def test_integration_route(integration_id: str, request: Request):
        """Test connectivity to an integration (admin only)."""
        user = _get_current_user(request)
        if not user or not auth_manager.is_admin(user):
            raise HTTPException(403, "Admin only")
        integ = get_integration(integration_id)
        if not integ:
            raise HTTPException(404, "Integration not found")
        preset = (integ.get("preset") or integ.get("name", "")).lower()

        # ntfy is special: a GET / proves the server is reachable but
        # publishes nothing, so the user has no way to know whether
        # subscribers will actually receive notifications. Instead, do
        # the real thing — POST a one-line "connectivity test" message
        # to the topic the Reminders panel is configured to use. If the
        # subscriber app is wired up correctly, this is what the green
        # checkmark + a phone ping confirms together.
        if preset == "ntfy":
            import httpx
            from urllib.parse import urlparse
            # Strip any path/query the user accidentally pasted in the
            # base URL (e.g. `http://host:8091/pantheon`) — otherwise
            # the topic gets appended after the path and we publish to
            # `/pantheon/pantheon` (which ntfy 404s on). ntfy itself
            # only ever serves from the root.
            raw_base = (integ.get("base_url") or "").strip()
            parsed = urlparse(raw_base)
            base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else raw_base.rstrip("/")
            settings = _load_settings()
            topic = (settings.get("reminder_ntfy_topic") or "reminders").strip() or "reminders"
            full_url = f"{base}/{topic}"
            api_key = integ.get("api_key", "")
            auth_type = (integ.get("auth_type") or "none").lower()
            headers = {
                "Title": "Pantheon connectivity test",
                "Tags": "white_check_mark",
                "Priority": "default",
            }
            if api_key:
                if auth_type == "bearer":
                    headers["Authorization"] = f"Bearer {api_key}"
                elif auth_type == "header":
                    headers[integ.get("auth_header") or "Authorization"] = api_key
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    r = await client.post(
                        full_url,
                        content="Connectivity test from Pantheon. If you see this on your phone, ntfy is wired up correctly.",
                        headers=headers,
                    )
                if r.is_success:
                    # Tell the user EXACTLY where it went and what to
                    # subscribe to on their phone, so they can match
                    # without guesswork. The doubled-topic / wrong-host
                    # mistakes are easier to spot when the actual URL
                    # is right there in the success line.
                    return {
                        "ok": True,
                        "message": (
                            f"Sent to {full_url} — on your ntfy app, "
                            f"subscribe to topic \"{topic}\" with server "
                            f"\"{base}\" (or paste the full URL: {full_url})."
                        ),
                    }
                return {"ok": False, "message": f"ntfy returned HTTP {r.status_code} from {full_url}: {r.text[:200]}"}
            except Exception as e:
                hint = ""
                if parsed.hostname not in ("127.0.0.1", "localhost"):
                    hint = " If this is Docker Compose ntfy, set NTFY_BIND to that host/Tailscale IP and NTFY_BASE_URL to the same server URL in .env, then recreate ntfy."
                return {"ok": False, "message": f"ntfy publish to {full_url} failed: {e}.{hint}"[:500]}

        if preset == "discord_webhook":
            import httpx
            webhook_url = (integ.get("base_url") or "").strip()
            if not webhook_url:
                return {"ok": False, "message": "No webhook URL set — paste the full Discord webhook URL into the Base URL field."}
            payload = {
                "embeds": [{
                    "title": "Pantheon connectivity test",
                    "description": "If you see this, your Discord Webhook integration is wired up correctly.",
                    "color": 5793266,
                }]
            }
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    r = await client.post(webhook_url, json=payload)
                if r.is_success:
                    return {"ok": True, "message": "Test embed sent — check your Discord channel to confirm it arrived."}
                return {"ok": False, "message": f"Discord returned HTTP {r.status_code}: {r.text[:200]}"}
            except Exception as e:
                return {"ok": False, "message": f"Request failed: {e}"[:400]}

        # All other presets: GET against a known health endpoint.
        # Fall back to detecting from name if preset is missing.
        health_paths = {
            "miniflux": "/v1/me",
            "gitea": "/api/v1/version",
            "linkding": "/api/tags/",
            "homeassistant": "/api/",
            "home assistant": "/api/",
        }
        path = health_paths.get(preset, "/")
        result = await execute_api_call(integration_id, "GET", path)
        if result.get("exit_code", 1) == 0:
            return {"ok": True, "message": "Connection successful"}
        return {"ok": False, "message": (result.get("error") or "Connection failed")[:300]}

    return router
