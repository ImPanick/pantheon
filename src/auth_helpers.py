# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared auth helpers used by all route files."""

import os
from typing import Any, Optional
from fastapi import Request, HTTPException

from src.owner_identity import auth_disabled, effective_storage_owner


def get_current_user(request: Request) -> Optional[str]:
    """Get current username from request state (set by auth middleware)."""
    return getattr(request.state, 'current_user', None)


def effective_user(request: Request) -> Optional[str]:
    """The real human behind the request, for ownership/attribution.

    Cookie sessions resolve to the logged-in username. Bearer API-token callers
    come through as the sandboxed pseudo-user "api" so they can't wander into
    cookie/user routes by default, but their token was minted by, and belongs
    to, a real owner stamped on ``request.state.api_token_owner``. Routes that
    should attribute a token's actions to that owner (sessions, chat history)
    call this instead of :func:`get_current_user`, so a paired client sees and
    creates the SAME data as the owner's desktop UI rather than a separate
    "api"-owned silo.

    For cookie sessions this is identical to :func:`get_current_user`, so
    swapping a route over is a no-op for browser users. A bearer token with no
    owner falls back to :func:`get_current_user` (the "api" pseudo-user), so it
    never escalates.
    """
    if getattr(request.state, "api_token", False):
        owner = getattr(request.state, "api_token_owner", None)
        if owner:
            return owner
    return get_current_user(request)


def _is_api_token_request(request: Request) -> bool:
    """Return True when middleware authenticated a bearer API token."""
    return bool(getattr(request.state, "api_token", False))


def is_delegated_credential(request: Request) -> bool:
    """Whether this request arrived on a credential acting FOR a human.

    `B70`. A bearer API token is minted by a person and then handed to
    something else: an integration, a script, a third party.
    :func:`effective_user` resolves it back to that person for ownership and
    attribution, which is **correct for data and wrong for authority**. Only
    admins can mint tokens, so every token resolves to an admin, and any gate
    asking *is the owner an admin?* answers yes for a credential the owner has
    given away.

    Security decisions about what the AGENT may do ask this instead, so a token
    cannot inherit the shell merely because its owner could use one.
    """
    return _is_api_token_request(request)


def require_api_token_scope(request: Request, scope: str) -> Optional[str]:
    """Require ``scope`` when the request is authenticated by an API token.

    Browser sessions are unaffected. Scoped bearer routes call this before
    touching owner data, so resolving a token back to its owner never also
    hands it the owner's interactive-session authority.
    """
    if not _is_api_token_request(request):
        return get_current_user(request)
    scopes = set(getattr(request.state, "api_token_scopes", []) or [])
    if scope not in scopes:
        raise HTTPException(403, f"API token missing required scope: {scope}")
    owner = getattr(request.state, "api_token_owner", None)
    if not owner:
        raise HTTPException(403, "API token has no owner")
    return owner


def require_chat_api_token_scope(request: Request) -> Optional[str]:
    """FastAPI dependency for the chat and session bearer surfaces."""
    return require_api_token_scope(request, "chat")


def require_authenticated_request(request: Request) -> str:
    """Allow either a browser session or a valid bearer API token.

    This is intentionally narrower than :func:`require_user`: use it only for
    routes that need authentication but do not read or mutate owner-scoped
    user data. Owner-scoped routes should use ``require_user`` for browser
    sessions or their own API-token scope/owner gate.
    """
    if _is_api_token_request(request):
        return effective_user(request) or ""
    return require_user(request)


def _auth_disabled() -> bool:
    """True when the operator has explicitly turned off auth via .env.
    Mirrors the AUTH_ENABLED parse in app.py / core/middleware.py so the
    three call sites agree on what "off" means."""
    return auth_disabled()


def storage_owner_for_request(request: Request) -> Optional[str]:
    """Resolve the storage owner for code paths that need an owner bucket.

    This does not replace route authentication. It only gives auth-disabled
    no-login mode a stable storage identity instead of writing new data as
    legacy NULL/ownerless state.
    """
    return effective_storage_owner(effective_user(request))


def require_user(request: Request) -> str:
    """FastAPI dependency: reject unauthenticated callers when the upstream
    auth middleware was bypassed unexpectedly (e.g. SSRF from a sibling
    service). Returns the resolved username, or "" in single-user / anonymous
    modes where no username is available.

    The three "" cases are:
      1. AUTH_ENABLED=false — the operator explicitly turned auth off.
         The full /login flow is skipped (issue #622), so route-level
         require_user must let the request through too instead of 401-ing
         and forcing the browser to /login.
      2. Unconfigured first-run + loopback caller — pre-setup access from
         localhost so the operator can hit the SPA before creating the
         first admin.
      3. LOCALHOST_BYPASS=true + loopback caller — documented dev bypass.

    Use this on routes that touch user data so middleware misconfig can't
    open them up.
    """
    if _is_api_token_request(request):
        raise HTTPException(403, "API tokens must use a scope-aware API route")

    u = get_current_user(request)
    if u:
        return u
    # Operator-disabled auth: honor it at the route layer too. Without this,
    # routes that depend on require_user 401, the front-end fetch wrapper
    # redirects to /login, and the user sees a login page despite
    # AUTH_ENABLED=false (issue #622). Docker / reverse-proxy deployments
    # hit this because requests arrive from a non-loopback client.host, so
    # the loopback fall-through below never fires.
    if _auth_disabled():
        return ""
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    client = getattr(request, "client", None)
    host = (client.host if client else "") or ""
    is_loopback = host in ("127.0.0.1", "::1", "localhost")
    # LOCALHOST_BYPASS=true is the dev-only "I'm on loopback, skip auth"
    # switch. Mirror the middleware so routes don't 401 the same caller
    # the middleware just let through.
    # env-spelling: the middleware half of this switch is held on its own rule
    # for the reason written at `app.py`. The two must always agree, so neither
    # moves alone (`B91`).
    if is_loopback and os.getenv("LOCALHOST_BYPASS", "false").lower() == "true":
        return ""
    if auth_mgr is not None and getattr(auth_mgr, "is_configured", False):
        raise HTTPException(401, "Not authenticated")
    # Unconfigured / first-run mode: only allow loopback callers.
    if is_loopback:
        return ""
    raise HTTPException(401, "Not authenticated")


_PRIVILEGE_KEY_PREFIX = "can_"


def privilege_denied_message(key: str) -> str:
    """The 403 detail for a denied privilege `key`, as a readable sentence.

    Privilege keys are named `can_<verb phrase>` — `can_use_research`,
    `can_generate_images`, `can_manage_memory`, `can_use_documents`. Dropping
    the raw key into "Your account is not allowed to …" produced "Your account
    is not allowed to can use research." Strip the `can_` first so the sentence
    reads "…is not allowed to use research."

    Wording only: nothing here decides anything. Keys that don't carry the
    prefix are still rendered, with underscores turned into spaces, so a new
    or misspelled key degrades to a readable sentence rather than a blank one.
    """
    phrase = str(key or "").strip()
    if phrase.startswith(_PRIVILEGE_KEY_PREFIX):
        phrase = phrase[len(_PRIVILEGE_KEY_PREFIX):]
    phrase = phrase.replace("_", " ").strip()
    if not phrase:
        return "Your account is not allowed to perform this action."
    return f"Your account is not allowed to {phrase}."


def resolve_privilege(privs: Any, key: str) -> Any:
    """Resolve one privilege for a caller. The single source of truth for what
    a privilege key means when the user's stored map does not answer.

    Three cases, in order:

    1. **The user's map names the key** — that value wins. Nothing else is
       consulted.
    2. **`DEFAULT_PRIVILEGES` names the key** — the registry's declared value
       is the answer. This is what keeps a deploy safe: adding a new key to the
       registry resolves to whatever that key declares for every existing user
       who has no entry yet, so a permissive new key does not lock anyone out
       mid-deploy and a restrictive one is restrictive from the first request.
    3. **Nobody declares the key** — denied. A key that is in neither map is a
       typo at a call site or a privilege someone forgot to register; the only
       safe answer to "may this user do a thing nobody defined?" is no.

    Case 3 is the fix. It used to be `privs.get(key, True)`, so
    `require_privilege(request, "can_use_reserch")` granted the route to
    everyone, silently, forever — the comment justified it with "the UI gates
    display-side" and `P2-18` proved that gate does not work. All four keys any
    route passes today (`can_use_research`, `can_use_documents`,
    `can_generate_images`, `can_manage_memory`) are declared in the 11-key
    registry, so no shipped route changes behaviour; only a typo does.

    Case 2 is why the answer is not simply `privs.get(key, False)`.
    `AuthManager.get_privileges` already merges `{**DEFAULT_PRIVILEGES,
    **stored}`, so on the real path the key is present either way — but that
    merge lives in `core/auth.py` and this default lived here, which is one
    fact in two places (`Law 13`). Reading the registry here makes the answer
    the same whether or not the caller merged: a partial map, a duck-typed auth
    manager in a test, or a corrupt `auth.json` that leaves `privs` empty all
    degrade to the declared defaults instead of to `True`.

    The registry is imported per call, not bound at module import, so a key
    added to `DEFAULT_PRIVILEGES` is live without restarting the process.

    Returns the raw value, not a bool: the registry holds an int
    (`max_messages_per_day`) and a list (`allowed_models`) alongside its nine
    booleans, and callers that read those need the value, not its truthiness.
    """
    from core.auth import DEFAULT_PRIVILEGES

    if isinstance(privs, dict) and key in privs:
        return privs[key]
    if key in DEFAULT_PRIVILEGES:
        return DEFAULT_PRIVILEGES[key]
    return False


def require_privilege(request: Request, key: str) -> str:
    """Reject callers whose `auth.json` privilege flag for `key` is False.
    Returns the username so the route handler can keep using it.

    Admins hold every *declared* privilege via `auth_manager.get_privileges`
    (which returns ADMIN_PRIVILEGES wholesale), so this is a no-op for them on
    any registered key. An **undeclared** key denies admins too — see
    `resolve_privilege` case 3; that is deliberate, because a typo'd key is a
    bug and a 403 on the first request is how it gets found. In
    unauthenticated single-user mode (`require_user` returns ""), privileges
    aren't enforced.
    """
    user = require_user(request)
    if not user:
        return user
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    if auth_mgr is None:
        return user
    try:
        privs = auth_mgr.get_privileges(user) or {}
    except Exception:
        return user
    if not isinstance(privs, dict):
        privs = {}
    # Declared key -> stored value, else the registry's declared default.
    # Undeclared key -> denied. `resolve_privilege` carries the reasoning.
    if not resolve_privilege(privs, key):
        raise HTTPException(403, privilege_denied_message(key))
    return user


def owner_filter(query, model_cls, user: str, *, include_shared: bool = True):
    """Filter `query` so only rows owned by `user` (and optionally null-owner
    'shared' rows) come through. No-op when `user` is empty (single-user
    mode). Returns the modified query."""
    if not user:
        return query
    if include_shared:
        return query.filter((model_cls.owner == user) | (model_cls.owner == None))  # noqa: E711
    return query.filter(model_cls.owner == user)
