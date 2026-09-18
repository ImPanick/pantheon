# SPDX-License-Identifier: AGPL-3.0-or-later
# app.py — slim orchestrator
import mimetypes
import os
import sys
import asyncio
import time

# On Windows, asyncio.create_subprocess_exec/shell require the ProactorEventLoop.
# When started via `python -m uvicorn` from a terminal, uvicorn sets this
# automatically. But the VS Code debugger (and other non-uvicorn entrypoints)
# use the default SelectorEventLoop, which raises NotImplementedError on any
# subprocess call. Force ProactorEventLoop here so the right loop is always
# used, regardless of how the process is launched.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def register_static_mime_types() -> None:
    """Force stable JS module MIME types across platforms.

    Some native Windows setups inherit stale/incorrect registry mappings for
    ``.js``/``.mjs``, which can make Starlette serve ES modules with a non-JS
    ``Content-Type`` and cause the UI to load but fail on click. Re-register the
    standard MIME types at startup so static assets are served consistently.
    """

    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("application/javascript", ".mjs")


register_static_mime_types()

# Windows: force HuggingFace/fastembed to COPY model files instead of symlinking.
# On a network-share/UNC data dir Windows can't follow HF's symlinks ([WinError
# 1463]), so the ONNX embedding model fails to load. huggingface_hub reads this
# at import time, so set it before anything pulls it in. (Mirrored in
# src/embeddings.py for non-server entrypoints.)
if os.name == "nt":
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from dotenv import load_dotenv
# encoding="utf-8-sig" tolerates a UTF-8 BOM in .env — a common Windows gotcha
# when the file is saved from Notepad. Without this, the first key parses as
# "﻿AUTH_ENABLED" instead of "AUTH_ENABLED", so AUTH_ENABLED=false (etc.)
# is silently ignored and the user is unexpectedly forced to log in (issue #142).
# utf-8-sig reads plain UTF-8 (no BOM) identically, so this is safe everywhere.
load_dotenv(encoding="utf-8-sig")

import asyncio
import logging
import secrets
from datetime import datetime, timezone
from typing import Dict

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

# Core imports
from core.constants import (
    BASE_DIR, STATIC_DIR, SESSIONS_FILE,
    REQUEST_TIMEOUT, OPENAI_API_KEY, AUTH_FILE,
)
from core.database import SessionLocal, ApiToken
from core.api_tokens import (
    bearer_credential as _bearer_credential,
    register_cache_invalidator as _register_token_cache_invalidator,
)
from core.middleware import (
    SecurityHeadersMiddleware,
    get_application_route_path,
    is_cors_preflight,
    path_is_route_or_child,
    with_asgi_root_path,
)
from core.auth import AuthManager, normalize_known_username
from core.exceptions import (
    SessionNotFoundError, InvalidFileUploadError,
    LLMServiceError, WebSearchError,
)

import bcrypt as _bcrypt

from src.app_helpers import (
    abs_join,
    inline_script_hashes_for_file,
    serve_generated_html,
    serve_html_with_nonce,
)
from src.env_flags import env_flag
from src.generated_images import GENERATED_IMAGE_HEADERS, resolve_generated_image_path
from src.owner_identity import auth_disabled
from starlette.responses import RedirectResponse

# ========= LOGGING =========
import logging.handlers
from core.constants import DATA_DIR

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)
_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Clear existing handlers to avoid duplicates
for _h in list(_root_logger.handlers):
    _root_logger.removeHandler(_h)

_console_h = logging.StreamHandler()
_console_h.setFormatter(_formatter)
_root_logger.addHandler(_console_h)

try:
    _log_dir = os.path.join(DATA_DIR, "logs")
    os.makedirs(_log_dir, exist_ok=True)
    _log_file = os.path.join(_log_dir, "app.log")

    # RotatingFileHandler is not multi-process safe (e.g. if uvicorn is run with --workers N).
    # Pantheon is single-process by convention, so this is acceptable, but be aware that
    # concurrent log rotation issues can arise if multiple workers are configured.
    _file_h = logging.handlers.RotatingFileHandler(
        _log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    _file_h.setFormatter(_formatter)
    _root_logger.addHandler(_file_h)
except Exception as e:
    _root_logger.warning(f"Failed to initialize file logging handler (falling back to console-only): {e}")

logger = logging.getLogger(__name__)

# ========= APP =========
# Lifespan is defined below (after all helpers it references are in scope)
# and passed to FastAPI so we can use the modern context-manager lifecycle
# instead of the deprecated @app.on_event("startup"/"shutdown") decorators.
app = FastAPI(
    title="AI Chat Application",
    description="Comprehensive AI chat with memory, research, and multi-modal capabilities",
    version="1.0.0",
    # `B212`. The framework's own `/docs` and `/redoc` handlers are switched
    # off so this file can serve the same documents from this origin instead —
    # see `serve_swagger_ui` below. This is not "docs off": `/docs` is
    # registered again a few hundred lines down, from vendored bytes, and it
    # renders for the first time in this repository's history. `openapi_url` is
    # deliberately NOT disabled — `src/tools/system.py` (`do_app_api`,
    # `action: "endpoints"`) fetches `/openapi.json` over the loopback with the
    # internal-tool header, so the schema is a shipped feature with a caller in
    # the tree and turning it off would break the agent's API discovery.
    docs_url=None,
    redoc_url=None,
)

# ========= CORS =========
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=CORS_ALLOW_METHODS,
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Auth-Token",
        "X-Pantheon-Internal-Token",
        "X-Pantheon-Owner",
        "X-Requested-With",
        "X-TZ-Offset",
    ],
)

# ========= RESPONSE COMPRESSION (gzip) =========
# The frontend's text assets (style.css, index.html, the JS bundles) shipped
# uncompressed on every cold load. gzip cuts CSS/JS/HTML by ~75-85% on the wire
# with no behavioural change. Starlette's GZipMiddleware excludes
# `text/event-stream` by default, so the SSE streams (chat, shell, research,
# model-probe — all served with media_type="text/event-stream") are never
# compressed or buffered; only complete bodies over minimum_size are. The
# security-header middleware composes cleanly on top.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

# ========= SECURITY HEADERS MIDDLEWARE =========
app.add_middleware(SecurityHeadersMiddleware)


# ========= REQUEST TIMEOUT (FALLBACK FOR HUNG HANDLERS) =========
# If a single request takes longer than REQUEST_HARD_TIMEOUT, abort it and
# return 504 instead of holding the event loop hostage. Whitelisted paths
# (streaming, long-running shell exec, research) are exempt because they
# legitimately stay open. Without this, a single hung subprocess.run or
# missing-timeout httpx call locks up the entire server for everyone.
import asyncio as _asyncio
from starlette.middleware.base import BaseHTTPMiddleware as _BaseHTTPMiddleware
from starlette.responses import JSONResponse as _JSONResponse

REQUEST_HARD_TIMEOUT = float(os.getenv("REQUEST_HARD_TIMEOUT", "45"))
_TIMEOUT_EXEMPT_PREFIXES = (
    "/api/chat",            # streaming
    "/api/shell/stream",    # SSE
    "/api/research",        # multi-minute jobs
    "/api/model/download",  # tmux setup may run pip installs
    "/api/model/probe",     # SSE; iterates models with up to 8s timeout each
    "/api/model-endpoints", # /probe sub-route also iterates models
    "/api/cookbook/setup",  # remote pacman/apt installs
    "/api/upload",          # large files
    "/api/image",           # diffusion proxies (inpaint/harmonize/upscale/etc.) — own 120s httpx timeout
    "/api/memory/audit",    # retains own 120s LLM inactivity timeout
)


class _RequestTimeoutMiddleware(_BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path or ""
        if any(path.startswith(p) for p in _TIMEOUT_EXEMPT_PREFIXES):
            return await call_next(request)
        try:
            return await _asyncio.wait_for(call_next(request), timeout=REQUEST_HARD_TIMEOUT)
        except _asyncio.TimeoutError:
            return _JSONResponse(
                {"detail": f"Request exceeded {REQUEST_HARD_TIMEOUT:.0f}s timeout"},
                status_code=504,
            )


class _InteractiveActivityMiddleware(_BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        from src.interactive_gate import should_track_interactive_request, track_interactive_request

        path = request.url.path or ""
        if not should_track_interactive_request(path, request.method):
            return await call_next(request)
        async def _stop_background():
            try:
                await task_scheduler.stop_background_tasks_for_foreground(reason=f"foreground request {request.method} {path}")
            except Exception:
                logging.getLogger("app.foreground_gate").debug("foreground task stop failed", exc_info=True)
        asyncio.create_task(_stop_background())
        async with track_interactive_request(path, request.method):
            return await call_next(request)


class _SlowRequestLogMiddleware(_BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = getattr(response, "status_code", 0) or 0
            return response
        finally:
            elapsed = time.perf_counter() - start
            try:
                threshold = float(os.getenv("PANTHEON_SLOW_REQUEST_LOG_SECONDS", "0.75") or "0.75")
            except Exception:
                threshold = 0.75
            if elapsed >= threshold:
                logging.getLogger("app.slow_request").warning(
                    "slow_request method=%s path=%s status=%s elapsed=%.3fs",
                    request.method,
                    request.url.path,
                    status,
                    elapsed,
                )


app.add_middleware(_RequestTimeoutMiddleware)
app.add_middleware(_InteractiveActivityMiddleware)
app.add_middleware(_SlowRequestLogMiddleware)

# ========= AUTH =========
from routes.auth_routes import setup_auth_routes, SESSION_COOKIE
from src.roles import install_role_layer

auth_manager = AuthManager()
app.state.auth_manager = auth_manager
# `P11-02`. The one line `P12-01` left this registry waiting for: from here on
# `settings.resolve_limit` consults the caller's role profile before the
# instance setting, the environment and the built-in default — for every byte
# cap, every upload throttle and every auth throttle at once, with no call site
# changing. With no roles defined the provider answers `None` for every key and
# the layers below decide exactly as they did (`Law 1`).
install_role_layer(auth_manager)
AUTH_ENABLED = not auth_disabled()
# env-spelling: `B91` holds this one. Widening to the shared vocabulary would
# turn an AUTH BYPASS on for every host already carrying `LOCALHOST_BYPASS=1`,
# where it does nothing today — an upgrade that silently unlocks loopback.
# `.pantheon/FORBIDDEN.md` Part 2 lists this control. Moves only with a release
# note and the same change made at `src/auth_helpers.py` in the same commit.
LOCALHOST_BYPASS = os.getenv("LOCALHOST_BYPASS", "false").lower() == "true"
if LOCALHOST_BYPASS:
    logger.warning("LOCALHOST_BYPASS is enabled, loopback requests bypass authentication. Do not expose this instance to a network.")

if AUTH_ENABLED:
    AUTH_EXEMPT_EXACT = {
        "/api/auth/setup",
        "/api/auth/signup",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/status",
        "/api/auth/features",
        "/api/auth/settings",
        "/api/auth/integrations/presets",
        "/api/health",
        "/api/version",
        "/login",
    }
    AUTH_EXEMPT_PREFIXES = ["/static"]
    # Dynamic paths whose own handler proves identity via a path-embedded
    # secret instead of the session/bearer auth. The route handler at
    # routes/task_routes.py validates the per-task `webhook_token` itself
    # and returns 404 on mismatch, so the path is the credential — the
    # UI labels these URLs "no auth needed" precisely because external
    # callers (Zapier, n8n, curl) can't supply a session cookie. Without
    # this exemption AuthMiddleware rejects every POST with 401 before
    # the token is ever checked.
    import re as _re
    AUTH_EXEMPT_PATTERNS = [
        _re.compile(r"^/api/tasks/[^/]+/webhook/[^/]+/?$"),
    ]

    def _is_auth_exempt(path: str) -> bool:
        if path in AUTH_EXEMPT_EXACT:
            return True
        if any(path_is_route_or_child(path, p) for p in AUTH_EXEMPT_PREFIXES):
            return True
        return any(p.match(path) for p in AUTH_EXEMPT_PATTERNS)

    # In-memory token cache: prefix → list[(token_id, token_hash, owner, scopes)]. The DB
    # query was running on every API-bearer request and scanning bcrypt
    # checks linearly. With this cache, we hit the DB only when the cache
    # version bumps (token created/revoked) — see _token_cache_invalidate
    # in app.state, called by routes/api_token_routes.
    _token_cache: dict = {}
    _token_cache_lock = _asyncio.Lock()
    _token_cache_dirty = True

    def _token_cache_invalidate():
        nonlocal_dict = app.state.__dict__
        nonlocal_dict["_token_cache_dirty"] = True
    app.state.invalidate_token_cache = _token_cache_invalidate
    # Same setter, reachable without a `Request`. Routes keep using
    # `app.state.invalidate_token_cache` exactly as before; the agent's tool
    # layer runs inside the model loop and has no request to reach through, so
    # before this line its `manage_tokens delete` left the revoked token
    # authenticating out of the cache until the next restart (`B43`).
    _register_token_cache_invalidator(_token_cache_invalidate)
    app.state._token_cache = _token_cache
    app.state._token_cache_dirty = True

    def _refresh_token_cache():
        """Rebuild the prefix→[(id,hash)] map from the DB."""
        from collections import defaultdict
        new_map = defaultdict(list)
        db = SessionLocal()
        try:
            rows = db.query(ApiToken).filter(ApiToken.is_active == True).all()
            for r in rows:
                owner_key = normalize_known_username(auth_manager.users, getattr(r, "owner", None))
                if not owner_key:
                    logger.warning(
                        "Ignoring active API token '%s' for unknown auth user '%s'",
                        getattr(r, "id", ""),
                        getattr(r, "owner", None),
                    )
                    continue
                scopes = [s.strip() for s in (getattr(r, "scopes", "") or "chat").split(",") if s.strip()]
                new_map[r.token_prefix].append((r.id, r.token_hash, owner_key, scopes))
        finally:
            db.close()
        _token_cache.clear()
        _token_cache.update(new_map)
        app.state._token_cache_dirty = False

    # Headers that prove a request was forwarded by a proxy/tunnel (cloudflared,
    # nginx, Caddy, Tailscale Funnel, …). cloudflared connects to the app FROM
    # 127.0.0.1, so without this check every tunneled request would look like
    # loopback and could bypass auth.
    _PROXY_FWD_HEADERS = (
        "cf-connecting-ip", "cf-ray", "cf-visitor",
        "x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded",
    )

    def _is_trusted_loopback(request: Request) -> bool:
        """True ONLY for a DIRECT loopback connection with no proxy/tunnel
        forwarding headers. A bare ``client.host in ('127.0.0.1','::1')`` check is
        unsafe behind a Cloudflare tunnel / reverse proxy: those connect from
        loopback, so a remote visitor would otherwise inherit local trust and
        slip past LOCALHOST_BYPASS or spoof the internal-tool path. Pantheon's own
        in-process agent loopback calls carry none of these headers, so they still
        qualify."""
        host = request.client.host if request.client else None
        if host not in ("127.0.0.1", "::1"):
            return False
        for _h in _PROXY_FWD_HEADERS:
            if request.headers.get(_h):
                return False
        return True

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = get_application_route_path(request.scope)
            # A genuine CORS preflight (OPTIONS + Access-Control-Request-Method)
            # carries no credentials by design and must reach CORSMiddleware to be
            # answered. AuthMiddleware is the outermost middleware, so gating the
            # preflight on auth 401s it before CORS can respond -- which blocks
            # every cross-origin browser/WebView client before the real request
            # is sent. Let real preflights through (only OPTIONS w/ the ACRM
            # header; never a credentialed request).
            if is_cors_preflight(request.method, request.headers):
                return await call_next(request)
            if _is_auth_exempt(path):
                return await call_next(request)
            # In-process internal-tool token bypass. Used by the agent
            # tool layer when it HTTP-loopbacks to admin-gated routes
            # (no admin cookie available in that context). Restricted to
            # loopback clients + matching token to keep it locked down.
            try:
                from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN as _ITT, INTERNAL_TOOL_USER
                _hdr = request.headers.get(INTERNAL_TOOL_HEADER)
                if _hdr and secrets.compare_digest(_hdr, _ITT) and _is_trusted_loopback(request):
                    # Impersonation: when the agent's loopback call sets
                    # X-Pantheon-Owner, attribute the request to that user only
                    # if they exist. Authorization checks remain separate; this
                    # is just owner attribution for notes/calendar/etc.
                    _impersonate = (request.headers.get("X-Pantheon-Owner") or "").strip()
                    _auth_mgr = getattr(request.app.state, "auth_manager", None) or auth_manager
                    if _impersonate and _impersonate in getattr(_auth_mgr, "users", {}):
                        request.state.current_user = _impersonate
                    else:
                        request.state.current_user = INTERNAL_TOOL_USER
                    request.state.api_token = False
                    return await call_next(request)
            except Exception as _e:
                logger.warning("Internal tool auth header check failed", exc_info=_e)
            # Allow DIRECT localhost requests (internal service calls from
            # heartbeats etc.). Tunnel/proxy-forwarded requests are excluded by
            # _is_trusted_loopback so LOCALHOST_BYPASS can't be abused over a
            # Cloudflare tunnel / reverse proxy. Keep LOCALHOST_BYPASS=false for
            # network-exposed deployments regardless.
            if LOCALHOST_BYPASS and _is_trusted_loopback(request):
                return await call_next(request)
            if not auth_manager.is_configured:
                # No users yet — redirect to login for first-time setup
                if not path.startswith("/api/"):
                    return RedirectResponse(
                        url=with_asgi_root_path(request.scope, "/login"),
                        status_code=302,
                    )
                return JSONResponse(status_code=401, content={"error": "Setup required"})

            # --- Bearer token auth (API tokens for external integrations) ---
            auth_header = request.headers.get("authorization", "")
            # `bearer_credential` knows every prefix this build accepts, which
            # is one today and two the moment `P0-31`'s rename lands: tokens
            # already pasted into a scrape config or a paired phone were minted
            # under the old prefix and have to keep working. It also matches the
            # scheme case-insensitively, as RFC 7235 requires — that widens what
            # is *offered* to the bcrypt check below and nothing else.
            raw_token = _bearer_credential(auth_header)
            if raw_token is not None:
                # Sanity check: tokens are a 4-char prefix + 43 chars of base64
                if len(raw_token) < 12 or len(raw_token) > 100:
                    return JSONResponse(status_code=401, content={"error": "Invalid API token"})
                prefix = raw_token[:8]
                try:
                    if app.state._token_cache_dirty:
                        async with _token_cache_lock:
                            if app.state._token_cache_dirty:
                                await _asyncio.to_thread(_refresh_token_cache)
                    candidates = list(_token_cache.get(prefix, ()))
                    matched_id = None
                    matched_owner = None
                    matched_scopes = []
                    for tid, thash, owner, scopes in candidates:
                        if _bcrypt.checkpw(raw_token.encode(), thash.encode()):
                            matched_id = tid
                            matched_owner = owner
                            matched_scopes = scopes or []
                            break
                    if matched_id:
                        # Update last_used_at off the hot path. Doing it
                        # inline used to keep the request open across an
                        # extra commit; do it fire-and-forget instead.
                        async def _touch_last_used(tid: str):
                            def _do():
                                _db = SessionLocal()
                                try:
                                    _db.query(ApiToken).filter(ApiToken.id == tid).update(
                                        {"last_used_at": datetime.utcnow()}
                                    )
                                    _db.commit()
                                finally:
                                    _db.close()
                            try:
                                await _asyncio.to_thread(_do)
                            except Exception as _e:
                                logger.debug("Failed to update token last_used_at", exc_info=_e)
                        _asyncio.create_task(_touch_last_used(matched_id))
                        # Keep bearer-token callers out of normal cookie/user
                        request.state.current_user = "api"
                        request.state.api_token = True
                        request.state.api_token_id = matched_id
                        request.state.api_token_owner = matched_owner
                        request.state.api_token_scopes = matched_scopes
                        return await call_next(request)
                except Exception:
                    logger.warning("API token auth error", exc_info=False)
                # Invalid bearer token — reject immediately
                return JSONResponse(status_code=401, content={"error": "Invalid API token"})

            # --- Cookie-based session auth ---
            token = request.cookies.get(SESSION_COOKIE)
            if not auth_manager.validate_token(token):
                if path.startswith("/api/"):
                    return JSONResponse(status_code=401, content={"error": "Not authenticated"})
                return RedirectResponse(
                    url=with_asgi_root_path(request.scope, "/login"),
                    status_code=302,
                )

            # Attach current username to request state for downstream routes
            request.state.current_user = auth_manager.get_username_for_token(token)
            request.state.api_token = False
            return await call_next(request)

    app.add_middleware(AuthMiddleware)
    logger.info("Auth middleware enabled (AUTH_ENABLED=true)")
else:
    logger.info("Auth middleware disabled (set AUTH_ENABLED=true to enable)")

# ========= STATIC FILES =========
os.makedirs(STATIC_DIR, exist_ok=True)


# `B262`. Every document under `static/` that a **route** serves, and the route
# that serves it. Three handlers below read their template path out of this
# table and `_RevalidatingStatic` reads the same table, so "which pages does a
# route own?" is answered in one place instead of four (`Law 13`). A page added
# to a route without an entry here is a page the route cannot find, which is
# the direction the drift has to fail in.
#
# **Why the mount has to know.** `AUTH_EXEMPT_PREFIXES` contains `/static` and
# has to: the login page's stylesheet, its modules and its fonts all load from
# there before anyone is logged in. `static/index.html` simply lived inside that
# exemption, so with `AUTH_ENABLED=true` measured 2026-09-16 against the real
# app: `GET /` was `302 → /login` and `GET /static/index.html` was **200 with
# all 292,260 bytes** of the app shell; `/static/login.html` was 200 as well.
# Not a data bypass — every call the shell makes is a separate request
# `AuthMiddleware` still gates — but the whole frontend, every panel and every
# endpoint path its modules fetch, handed to an unauthenticated port.
ROUTE_OWNED_STATIC_PAGES = {
    "index.html": "/",
    "login.html": "/login",
    # Not shipped in this build and never has been (`B140`, `B210`). The entry
    # is here so that if a deployment drops the sandbox page in, the one URL
    # that serves it is still the route — not the mount, and not both.
    "backgrounds.html": "/backgrounds",
}


def route_owned_page(filename: str) -> str:
    """Absolute path of a `static/` document a route serves (`B262`)."""
    return abs_join(STATIC_DIR, filename)


class _RevalidatingStatic(StaticFiles):
    """Serve static assets normally, but force the browser to REVALIDATE
    source files (.js/.css/.html) on every load instead of serving a stale
    copy from disk cache. The app ships raw ES modules with no build step or
    versioned URLs, so browsers were caching modules across deploys — a code
    change wouldn't appear without a manual hard-refresh. `no-cache` keeps the
    cached bytes but requires a conditional request; unchanged files still
    return a cheap 304 (ETag/Last-Modified are preserved).

    `B211`: it also authorises the inline scripts of the HTML documents it
    serves. `serve_html_with_nonce` gives `/` and `/login` a `'sha256-…'`
    source per inline block (`B141`); the documents under this mount went out
    with nothing, because a mount has no route handler to stamp
    `request.state` from. A `script-src` naming any nonce or hash source
    refuses every inline block it does not name, so
    `static/wave-variants.html` and `static/whirlpool-variants.html` — which
    are *entirely* one inline block each — have been served 200 and rendered
    an empty frame since before the fork.

    **The fix is at the mount and not at the two pages** (`Law 13`). Fixing the
    two that are broken today leaves the third `*-variants.html` prototype and
    the next page anyone adds to be found by whoever opens it. Every `.html`
    this mount serves gets the sources for its own inline blocks, derived from
    the bytes on disk and written down nowhere.

    **This is not a widening and it cannot become one.** A hash authorises
    exactly the bytes it was computed over, and `STATIC_DIR` is the shipped
    bundle: no route in this tree writes into it (`grep STATIC_DIR` is
    `src/constants.py`, `theme_advanced_keys.py`, the `makedirs` above and this
    mount), so nothing user-supplied can arrive here and be hashed. If that
    ever changes, this is the line that has to change with it.
    """

    async def get_response(self, path, scope):
        """Send a client asking for a route-owned document to that route.

        **`B262`.** `index.html` and `login.html` are templates the app renders
        through `serve_html_with_nonce`; a raw second copy of them reachable at
        `/static/…` is the defect, and the auth bypass is only its first
        consequence. The second is `B120`: `sw.js` narrowed its navigation
        handler precisely so a `/static/*.html` navigation is never answered
        with the app shell, and the shell was sitting at a `/static/*.html`
        URL — so "Add to Home Screen" from there installed a PWA whose launch
        URL the worker holds no document for.

        **A redirect and not a 404** (`Law 1`). The file is on disk and a 404
        would be a lie about that; nothing is taken away, the bytes are still
        reachable from this URL, they just arrive from the route that owns
        them and therefore through the gate that route is behind. That is also
        what keeps the fix from touching the rest of the mount: three
        filenames are redirected and every other byte under `/static` — the
        stylesheet, the modules, the fonts, the icons, the two `*-variants`
        prototypes `B120` and `B122` both require to keep reaching the
        network — is served exactly as before, unauthenticated, because the
        login page needs all of it *while logged out*.

        **302 and not 301**: a permanent redirect is cached by browsers until
        they are cleared, so it would outlive the decision. This one is
        reversible by redeploying.

        `path` is what `StaticFiles.get_path` produced — `os.path.normpath` of
        the URL's remainder — so `/static/./index.html`, `/static//index.html`
        and `/static/index.html/` all arrive here as `index.html`. Matched
        casefolded because a case-insensitive filesystem (macOS, Windows)
        serves `INDEX.HTML` out of `index.html`, and a rule that guards an
        auth boundary may not be the one thing on the path that is
        case-sensitive.
        """
        owner = ROUTE_OWNED_STATIC_PAGES.get(path.replace(os.sep, "/").casefold())
        # Only what a mount answers at all. `StaticFiles.get_response` refuses
        # anything but GET and HEAD with a 405, and redirecting a POST instead
        # would be this rule quietly widening the methods the mount accepts.
        if owner is not None and scope.get("method") in ("GET", "HEAD"):
            return RedirectResponse(
                url=with_asgi_root_path(scope, owner), status_code=302,
            )
        resp = await super().get_response(path, scope)
        if path.endswith((".js", ".css", ".html")):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    def file_response(self, full_path, stat_result, scope, status_code=200):
        """Stamp the page's inline-script sources, then serve it as usual.

        **This override is here and not in `get_response`, and the reason is
        the `304`.** `StaticFiles.file_response` is the one place both answers
        come from: it builds the `FileResponse`, and when the client's copy is
        still good it throws that away and returns a `NotModifiedResponse`
        carrying only headers — no body and no `.path` to hash. A hook further
        out sees a 304 it cannot identify a file from, and a `304` that goes
        out under a policy naming no hashes is the RFC 9111 §4.3.4 hazard
        `B121` measured: the client updates its stored headers from the `304`
        and is left holding the stored HTML under a policy that authorises
        none of it. Hashing here means both answers carry the same sources
        because both are functions of the same file.

        A read failure leaves the response exactly as it was — no sources,
        every inline block refused, which is where this started. It may not
        turn a served file into a 500.
        """
        page = os.fspath(full_path)
        if page.endswith(".html"):
            try:
                hashes = inline_script_hashes_for_file(page)
            except Exception:
                logger.exception("Failed to hash inline scripts in %s", page)
            else:
                if hashes:
                    # `SecurityHeadersMiddleware` reads this off its own
                    # `Request` after `call_next`; both are views on the same
                    # `scope["state"]` dict, which is the channel
                    # `serve_html_with_nonce` uses from a route handler.
                    scope.setdefault("state", {})["csp_script_hashes"] = hashes
        return super().file_response(full_path, stat_result, scope, status_code)


app.mount("/static", _RevalidatingStatic(directory=STATIC_DIR), name="static")

# ========= GENERATED IMAGES =========
@app.get("/api/generated-image/{filename}")
async def serve_generated_image(filename: str, request: Request):
    """Serve generated images from the data directory."""
    img_path = resolve_generated_image_path(filename)
    # SECURITY: filename is the only key, so anyone who knows / guesses a
    # 12-hex content hash could pull another user's image bytes. Require
    # auth and verify ownership via the gallery row (when one exists).
    try:
        from src.auth_helpers import get_current_user
        from core.database import SessionLocal as _SL, GalleryImage as _GI
        _user = get_current_user(request)
        if _user:
            _db = _SL()
            try:
                _row = _db.query(_GI).filter(_GI.filename == filename).first()
                # Generated-but-not-yet-imported images have no row → allow.
                # Row exists with a different owner → 404 (don't confirm existence).
                if _row is not None and _row.owner and _row.owner != _user:
                    raise HTTPException(status_code=404, detail="Image not found")
            finally:
                _db.close()
    except HTTPException:
        raise
    except Exception as _e:
        logger.warning("Image ownership verification failed for %r", filename, exc_info=_e)
    ext = filename.rsplit('.', 1)[-1].lower()
    mime = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif",
        "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
        "mkv": "video/x-matroska", "m4v": "video/mp4",
    }.get(ext, "application/octet-stream")
    # Generated-image filenames are content hashes → the bytes for a given
    # filename never change. Cache them hard so the gallery doesn't
    # re-download every full-size image each time it's opened. `immutable`
    # tells the browser it never needs to revalidate within the max-age.
    return FileResponse(
        str(img_path),
        media_type=mime,
        headers=GENERATED_IMAGE_HEADERS,
    )

# ========= YOUTUBE INIT =========
from services.youtube import init_youtube
init_youtube()

# ========= RAG (vector document RAG) =========
# VectorRAG (ChromaDB-backed personal-document semantic search). Initialized
# lazily via get_rag_manager() — returns None if ChromaDB isn't reachable
# (no server running on the configured host:port), in which case personal-doc
# routes return a clean 503 instead of busy-retrying every request.
#
# Note: this was previously hardcoded off because chromadb 1.4.1 / pydantic
# 2.12 were mutually incompatible at the time. With the current pins
# (chromadb 1.5.x + pydantic 2.13.x) the init works and Personal Docs
# (POST /api/personal/add_directory etc.) is functional again.
from src.rag_singleton import get_rag_manager
rag_manager = get_rag_manager()
rag_available = rag_manager is not None
if rag_available:
    logger.info("Vector document RAG initialized")
else:
    logger.info(
        "Vector document RAG not available at startup "
        "(ChromaDB may not be reachable yet — routes will retry lazily)"
    )

# ========= IMPORT CONFIG =========
from src.config import config

# ========= COMPONENT INITIALIZATION =========
from src.app_initializer import initialize_managers

components = initialize_managers(BASE_DIR, rag_manager)

session_manager   = components["session_manager"]
from src.assistant_log import set_session_manager as _set_asst_sm
_set_asst_sm(session_manager)
# Set the global session manager singleton (used by core.models.Session.add_message)
from core.models import set_session_manager_instance
set_session_manager_instance(session_manager)
app.state.session_manager = session_manager
memory_manager    = components["memory_manager"]
memory_vector     = components.get("memory_vector")
upload_handler    = components["upload_handler"]
app.state.upload_handler = upload_handler
personal_docs_mgr = components["personal_docs_manager"]
app.state.personal_docs_manager = personal_docs_mgr
api_key_manager   = components["api_key_manager"]
preset_manager    = components["preset_manager"]
chat_processor    = components["chat_processor"]
research_handler  = components["research_handler"]
app.state.research_handler = research_handler
chat_handler      = components["chat_handler"]
model_discovery   = components["model_discovery"]
skills_manager    = components["skills_manager"]

# TTS
from services.tts import get_tts_service

tts_service = get_tts_service()
logger.info("TTS service initialized (provider managed via admin settings)")

# ========= EXCEPTION HANDLERS =========
@app.exception_handler(SessionNotFoundError)
async def session_not_found_handler(request: Request, exc: SessionNotFoundError):
    return JSONResponse(status_code=404, content={"error": "SESSION_NOT_FOUND", "message": str(exc)})

@app.exception_handler(InvalidFileUploadError)
async def invalid_file_upload_handler(request: Request, exc: InvalidFileUploadError):
    return JSONResponse(status_code=400, content={"error": "INVALID_FILE_UPLOAD", "message": str(exc)})

@app.exception_handler(LLMServiceError)
async def llm_service_error_handler(request: Request, exc: LLMServiceError):
    return JSONResponse(status_code=502, content={"error": "LLM_SERVICE_ERROR", "message": str(exc)})

@app.exception_handler(WebSearchError)
async def web_search_error_handler(request: Request, exc: WebSearchError):
    return JSONResponse(status_code=502, content={"error": "WEB_SEARCH_ERROR", "message": str(exc)})

# ========= WEBHOOK MANAGER =========
from src.webhook_manager import WebhookManager

webhook_manager = WebhookManager(api_key_manager=api_key_manager)

# ========= INCLUDE ROUTERS =========

# Auth
auth_router = setup_auth_routes(auth_manager)
app.include_router(auth_router)


@app.post("/api/activity/heartbeat")
async def activity_heartbeat():
    from src.interactive_gate import (
        mark_browser_activity,
        maybe_stop_background_tasks_for_heartbeat,
    )

    await mark_browser_activity()

    async def _stop_background():
        try:
            await maybe_stop_background_tasks_for_heartbeat(
                task_scheduler.stop_background_tasks_for_foreground
            )
        except Exception:
            logging.getLogger("app.foreground_gate").debug(
                "heartbeat task stop failed",
                exc_info=True,
            )

    asyncio.create_task(_stop_background())
    return {"ok": True}


# Uploads
from routes.upload_routes import setup_upload_routes
upload_router, upload_cleanup_func = setup_upload_routes(upload_handler)
app.include_router(upload_router)
upload_cleanup_task = None

# Emoji SVG proxy (same-origin, lazy-cached Twemoji) — lets the chat render
# emojis as flat SVG instead of system color glyphs.
from routes.emoji_routes import setup_emoji_routes
app.include_router(setup_emoji_routes())
from routes.image_proxy_routes import setup_image_proxy_routes
app.include_router(setup_image_proxy_routes())

# Sessions
from routes.session_routes import setup_session_routes
session_config = {"REQUEST_TIMEOUT": REQUEST_TIMEOUT, "OPENAI_API_KEY": OPENAI_API_KEY, "SESSIONS_FILE": SESSIONS_FILE}
app.include_router(setup_session_routes(
    session_manager,
    session_config,
    webhook_manager=webhook_manager,
    upload_handler=upload_handler,
))

# Admin Danger Zone wipes (Settings → System → Danger Zone)
from routes.admin_wipe.admin_wipe_routes import setup_admin_wipe_routes
app.include_router(setup_admin_wipe_routes(session_manager))

# Memory
from routes.memory.memory_routes import setup_memory_routes
memory_router = setup_memory_routes(memory_manager, session_manager, memory_vector=memory_vector)
app.include_router(memory_router)
from routes.skills_routes import setup_skills_routes
app.include_router(setup_skills_routes(skills_manager))

# Chat
from routes.chat_routes import setup_chat_routes
app.include_router(setup_chat_routes(
    session_manager, chat_handler, chat_processor,
    memory_manager, research_handler, upload_handler,
    memory_vector=memory_vector,
    webhook_manager=webhook_manager,
    skills_manager=skills_manager,
))

# Research (background deep-research tasks)
from routes.research.research_routes import setup_research_routes
app.include_router(setup_research_routes(research_handler, session_manager=session_manager))

# History
from routes.history.history_routes import setup_history_routes
app.include_router(setup_history_routes(session_manager, upload_handler=upload_handler))

# Search
from routes.search.search_routes import setup_search_routes
app.include_router(setup_search_routes(config))

# Presets
from routes.preset_routes import setup_preset_routes
app.include_router(setup_preset_routes(preset_manager))

# Diagnostics
from routes.diagnostics_routes import setup_diagnostics_routes
app.include_router(setup_diagnostics_routes(rag_manager, rag_available, research_handler, memory_vector))

# Cleanup
from routes.cleanup.cleanup_routes import setup_cleanup_routes
app.include_router(setup_cleanup_routes(session_manager))

# Personal docs
from routes.personal_routes import setup_personal_routes
app.include_router(setup_personal_routes(personal_docs_mgr, rag_manager, rag_available))

# Embedding model management
from routes.embedding_routes import setup_embedding_routes
app.include_router(setup_embedding_routes())

# Models
from routes.model_routes import setup_model_routes
app.include_router(setup_model_routes(model_discovery))

# GitHub Copilot device-flow login
from routes.copilot_routes import setup_copilot_routes
app.include_router(setup_copilot_routes())

# ChatGPT Subscription device-flow login
from routes.chatgpt_subscription_routes import setup_chatgpt_subscription_routes
app.include_router(setup_chatgpt_subscription_routes())

# TTS
from routes.tts_routes import setup_tts_routes
app.include_router(setup_tts_routes(tts_service))

# STT
from services.stt import get_stt_service
stt_service = get_stt_service()
from routes.stt_routes import setup_stt_routes
app.include_router(setup_stt_routes(stt_service))
logger.info("STT service initialized (provider managed via settings)")

# Documents (artifacts/canvas)
from routes.document.document_routes import setup_document_routes
document_router = setup_document_routes(session_manager, upload_handler)
app.include_router(document_router)

# Signatures (reusable image stamps)
from routes.signature_routes import setup_signature_routes
app.include_router(setup_signature_routes())

# Gallery (image library)
from routes.gallery.gallery_routes import setup_gallery_routes
app.include_router(setup_gallery_routes())

# Persisted image-editor drafts (server-backed projects)
from routes.editor_draft_routes import setup_editor_draft_routes
app.include_router(setup_editor_draft_routes())

# Scheduled tasks + event bus
from src.task_scheduler import TaskScheduler
task_scheduler = TaskScheduler(session_manager)
from src.event_bus import set_task_scheduler
set_task_scheduler(task_scheduler)
from routes.task.task_routes import setup_task_routes
app.include_router(setup_task_routes(task_scheduler))

from routes.assistant_routes import setup_assistant_routes
app.include_router(setup_assistant_routes(task_scheduler))

# Calendar (CalDAV)
from routes.calendar_routes import setup_calendar_routes
calendar_router = setup_calendar_routes(upload_handler=upload_handler)
app.include_router(calendar_router)

# Shell (user-facing command execution)
from routes.shell_routes import setup_shell_routes
app.include_router(setup_shell_routes())

# Forge (model download/serve/cache, cookbook state sync)
from routes.cookbook_routes import setup_cookbook_routes
app.include_router(setup_cookbook_routes())

from routes.workspace_routes import setup_workspace_routes
app.include_router(setup_workspace_routes())

# Hardware model fitting (cookbook "What Fits?" tab)
from routes.hwfit_routes import setup_hwfit_routes
app.include_router(setup_hwfit_routes())

# Model A/B Comparison
from routes.compare.compare_routes import setup_compare_routes
app.include_router(setup_compare_routes(session_manager))

# User Preferences
from routes.prefs_routes import setup_prefs_routes
app.include_router(setup_prefs_routes())

# Backup (export/import user data)
from routes.backup_routes import setup_backup_routes
app.include_router(setup_backup_routes(memory_manager, preset_manager, skills_manager))

from routes.font_routes import setup_font_routes
app.include_router(setup_font_routes())


# MCP (Model Context Protocol)
from src.mcp_manager import McpManager
from src.agent_tools import set_mcp_manager
from routes.mcp.mcp_routes import setup_mcp_routes

mcp_manager = McpManager()
set_mcp_manager(mcp_manager)
app.include_router(setup_mcp_routes(mcp_manager))
logger.info("MCP routes initialized")

# AI Interaction tools (debates, pipelines, self-managing AI, UI control)
from src.ai_interaction import set_session_manager as set_ai_session_manager, set_memory_manager as set_ai_memory_manager, set_rag_manager as set_ai_rag_manager
set_ai_session_manager(session_manager)
set_ai_memory_manager(memory_manager, memory_vector)
set_ai_rag_manager(rag_manager, personal_docs_mgr)
logger.info("AI interaction tools initialized (session, memory, RAG, UI control)")

# Webhooks
from routes.webhook.webhook_routes import setup_webhook_routes
app.include_router(setup_webhook_routes(webhook_manager, auth_manager, session_manager, api_key_manager))

# API Tokens
from routes.api_token_routes import setup_api_token_routes
app.include_router(setup_api_token_routes())

logger.info("Webhook & API token routes initialized")

# Notes (Google Keep-style notes/todos)
from routes.note.note_routes import setup_note_routes
app.include_router(setup_note_routes(task_scheduler, upload_handler=upload_handler))

# Email
from routes.email_routes import setup_email_routes
email_router = setup_email_routes()
app.include_router(email_router)

# Codex integration — HTTP surface for the Codex plugin/MCP bridge. Reuses
# api_token scopes (todos:read|write, email:read|draft|send) so external
# Codex sessions can only touch the data the user explicitly allowed. Mounted
# AFTER email so the codex_routes can borrow the email router for shared
# search/threading helpers.
from routes.codex_routes import setup_codex_routes, setup_claude_routes
app.include_router(setup_codex_routes(
    email_router=email_router,
    memory_router=memory_router,
    calendar_router=calendar_router,
    document_router=document_router,
))
app.include_router(setup_claude_routes())

from routes.vault.vault_routes import setup_vault_routes
app.include_router(setup_vault_routes())

# Contacts (CardDAV)
from routes.contacts.contacts_routes import setup_contacts_routes
app.include_router(setup_contacts_routes())

from companion import setup_companion_routes
app.include_router(setup_companion_routes())

# ========= ROUTES (kept in app.py) =========

@app.get("/")
async def serve_index(request: Request):
    # `B262`: the path comes from `ROUTE_OWNED_STATIC_PAGES`, the same table
    # the `/static` mount reads to know this document has a route.
    static_path = route_owned_page("index.html")
    if os.path.exists(static_path):
        return serve_html_with_nonce(request, static_path)
    # No static bundle — fall back to a root-level index.html if one is shipped.
    # If neither exists, serve_html_with_nonce logs it and returns a generic 500:
    # a missing index.html is a broken deployment (server fault), not a client
    # "not found". This keeps the app-shell route consistent with the other
    # bundled-template routes instead of mislabelling the fault as a 404.
    return serve_html_with_nonce(request, abs_join(BASE_DIR, "index.html"))

@app.get("/notes")
async def serve_notes(request: Request):
    return await serve_index(request)

@app.get("/calendar")
async def serve_calendar(request: Request):
    return await serve_index(request)

# Per-tool deep-link routes — all serve the same SPA, the JS auto-opens
# the matching modal based on window.location.pathname. Each route also
# gets a unique favicon + page title via inline script in index.html so
# bookmarks render with tool-specific icons.
@app.get("/cookbook")
async def serve_cookbook(request: Request):
    return await serve_index(request)

@app.get("/email")
async def serve_email(request: Request):
    return await serve_index(request)

@app.get("/memory")
async def serve_memory(request: Request):
    return await serve_index(request)

@app.get("/gallery")
async def serve_gallery(request: Request):
    return await serve_index(request)

@app.get("/tasks")
async def serve_tasks(request: Request):
    return await serve_index(request)

@app.get("/library")
async def serve_library(request: Request):
    return await serve_index(request)

@app.get("/backgrounds")
async def serve_backgrounds(request: Request):
    """The background sandbox page is not shipped in this build.

    A deployment that drops `static/backgrounds.html` in is served it here.
    Nothing in this repository ships that file, so this route answers 404 and
    names what is missing.
    \f
    **`B210`.** This docstring opened with *"Sandbox page for prototyping
    background effects"* until 2026-09-16, and FastAPI publishes a route's
    docstring as its `description` in `/openapi.json` — so the sentence was
    not an internal note, it was a served claim, rendered in the API browser
    at `/docs` and read by `src/tools/system.py`'s endpoint discovery. It
    described a page that `git log --all -- static/backgrounds.html` finds in
    **none** of this repository's 167 commits and no deletion commit names.
    `Law 1` protects a behaviour that exists; a claim that something exists
    when it never has is not a behaviour, it is a false statement, and the
    fix for a false statement is to correct it.

    Writing the page was the other option and was declined. The two surviving
    prototypes of this family — `static/wave-variants.html` and
    `static/whirlpool-variants.html` — say in their own first comment that
    they are developer sandboxes the app does not link to, each a single
    self-contained inline block with its own copy of the styling. A third one
    for the seven canvas animators in `static/js/theme.js` would either copy
    them, which `D-2026-08-26-03` makes worse than having no sandbox at all
    (a copy that drifts from the protected originals), or import the real
    module, which is a new served document on a route, an eleventh entry in a
    precache list `B57` derives, and a page to keep in step forever — for a
    tool with no user outside development. If someone wants it later, this
    route serves the page the moment the file exists — nothing has to change
    here for that.

    `B140`. The page is **optional and this build does not ship it** —
    `static/backgrounds.html` is in no commit of this repository, no page or
    module links to `/backgrounds`, and `H21` re-measured that three times.
    The route still served it through `serve_html_with_nonce`, whose contract
    is that a missing template is a broken deployment: every request to an
    unauthenticated route wrote a `logger.exception` with a stack trace into
    5xx alerting and answered `{"detail":"Internal server error"}`.

    The route is **not removed** (`Law 1`): a deployment that drops the
    sandbox page in is served it, exactly as before. What changes is the
    answer when it is absent — a 404 naming the file it wants, which is what
    that state actually is, instead of a 500 claiming the server is broken.
    The name is repo-relative on purpose. This docstring read "No auth
    required" until 2026-09-16, which described the *handler* and not the path:
    `/backgrounds` is in neither `AUTH_EXEMPT_EXACT` nor the `/static` prefix,
    so with `AUTH_ENABLED=true` `AuthMiddleware` gates it like any other page —
    and with auth off anyone who can reach the app can reach this. Either way a
    reply from here must not hand out the deployment's absolute paths.
    Whether to write the page at all was the product decision `B140` left
    open; `B210` closed it above, as "not shipped, and the documents that said
    otherwise now say so".
    """
    page = route_owned_page("backgrounds.html")
    if not os.path.isfile(page):
        raise HTTPException(404, "static/backgrounds.html is not shipped in this build")
    return serve_html_with_nonce(request, page)

@app.get("/login")
async def serve_login(request: Request):
    if not AUTH_ENABLED:
        return RedirectResponse(url="/", status_code=302)
    return serve_html_with_nonce(request, route_owned_page("login.html"))


# ========= API BROWSER (`B212`) =========
# FastAPI's own `/docs` and `/redoc` are off at the constructor above, and
# these replace them. What changed and why, measured 2026-09-16 against the
# real app:
#
#   * `/docs` named `cdn.jsdelivr.net` twice and `fastapi.tiangolo.com` once;
#     `/redoc` named `cdn.jsdelivr.net`, `fonts.googleapis.com` and
#     `fastapi.tiangolo.com`. No request left — `default-src 'self'`,
#     `font-src 'self'` and `img-src 'self' data: blob:` refused all of them —
#     so this was never a live leak. It was a **published intent to fetch from
#     three hosts nobody chose**, sitting in the one part of the served surface
#     the CDN scan could not see, because that scan read `static/**` and these
#     documents are generated by a library at request time.
#
#   * The Swagger page has never rendered in this repository. Its bootstrap is
#     an inline `<script>` with no nonce attribute, and the app CSP has named a
#     nonce or a hash since the fork baseline (`fff72ec`) — a `script-src`
#     naming either refuses every inline block it does not name. So there is no
#     working behaviour here to preserve and none to lose: vendoring the two
#     assets and hashing the bootstrap makes `/docs` work for the first time,
#     which is an addition (`Law 1`).
#
#   * `/redoc` is the one that DID work at the baseline — its only script is
#     external and `script-src` allowed jsDelivr until `P16-07`. It is not
#     restored here and the reason is stated rather than waved at: the
#     `redoc.standalone.js` bundle builds its search index in
#     `new Worker(URL.createObjectURL(new Blob(…)))`, and `worker-src` falls
#     back through `child-src` to `default-src 'self'`, so a `blob:` worker is
#     refused; it also carries an Ajv `new Function(…)` code path, which needs
#     `'unsafe-eval'`. Both would mean widening the policy, and the policy does
#     not widen. So `/redoc` keeps its route and answers honestly — the
#     `B140` shape — instead of shipping 1.1 MB under a policy that refuses
#     part of it. `B261` weighed vendoring it anyway and decided against:
#     one API browser is enough, the 404 is the answer and not a placeholder,
#     and the reasoning is in `serve_redoc`'s own docstring below.


def _swagger_docs_html(request: Request) -> str:
    """FastAPI's own docs page, with every URL pointing at this origin.

    Built by `fastapi.openapi.docs.get_swagger_ui_html` rather than by a
    template of ours (`Law 14`): the page is FastAPI's, the parameters are
    FastAPI's, and the only edits are the three URLs that used to leave.
    `openapi_url` is taken from the app so a `root_path` deployment keeps
    working.
    """
    from fastapi.openapi.docs import get_swagger_ui_html

    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        # Vendored by `scripts/fetch-swagger-ui.py`, hashes pinned in
        # `static/lib/swagger-ui/MANIFEST.json`. The stylesheet's every `url()`
        # is a `data:` URI, so the page needs nothing from `font-src`.
        swagger_js_url="/static/lib/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/lib/swagger-ui/swagger-ui.css",
        # Was `https://fastapi.tiangolo.com/img/favicon.png`. This app has its
        # own icon and it is already served.
        swagger_favicon_url="/static/icons/icon-192.png",
    ).body.decode("utf-8")


@app.get("/docs", include_in_schema=False)
async def serve_swagger_ui(request: Request):
    """The interactive API browser, served from this origin.

    The inline bootstrap is authorised the way `B141` authorises the app's
    own inline blocks: a `'sha256-…'` over exactly those bytes, derived from
    the document being served and written down nowhere. Not `'unsafe-inline'`,
    which a browser ignores anyway whenever a hash source is present, and which
    would read safe while behaving safe only until the hashes went away.
    """
    return serve_generated_html(request, _swagger_docs_html(request))


@app.get("/docs/oauth2-redirect", include_in_schema=False)
async def serve_swagger_ui_oauth2_redirect(request: Request):
    """Swagger's OAuth2 callback page — 3,012 bytes of inline script.

    A fourth route `B212` did not name and the same defect: FastAPI mounts it
    alongside `/docs`, it is all inline script, and it was refused. Kept rather
    than dropped (`Law 1`) — the Authorize dialog needs somewhere to land the
    moment this app's schema grows an OAuth2 security scheme — and now hashed
    like the page that opens it.
    """
    from fastapi.openapi.docs import get_swagger_ui_oauth2_redirect_html

    return serve_generated_html(
        request, get_swagger_ui_oauth2_redirect_html().body.decode("utf-8")
    )


@app.get("/redoc", include_in_schema=False)
async def serve_redoc(request: Request):
    """This app ships one API browser, and it is at `/docs`.

    `/redoc` is kept as a route so a build that vendors ReDoc serves it from
    here, and answers 404 naming `/docs` until one does.
    \f
    **`B261` decided it, 2026-09-16: one API browser is enough.** ReDoc did
    work at the fork baseline — its only script is external and `script-src`
    named `cdn.jsdelivr.net` then — and `P16-07` removed that host for
    Pyodide's sake and took ReDoc with it without noticing. `B212` measured
    why it cannot simply be restored, in the published bundle:
    `redoc.standalone.js` builds its search index in
    `new Worker(URL.createObjectURL(new Blob(…)))`, which `default-src 'self'`
    refuses through the `worker-src` → `child-src` fallback, and it carries an
    Ajv `new Function(…)` path that needs `'unsafe-eval'`.

    **The two ways back were both weighed and both declined.**

    *Widen the policy.* Not negotiable and not proposed. `'unsafe-eval'` is in
    `.pantheon/FORBIDDEN.md` Part 2. `worker-src 'self' blob:` scoped to this
    one response is the smaller of the two and is still a real loosening: a
    `blob:` worker is the standard way a script that has got onto a page runs
    code the policy did not hash, and this app's `script-src` is
    `'self' 'wasm-unsafe-eval'` plus per-document `'sha256-…'` sources
    precisely so that nothing unhashed runs. Spending that on a second
    renderer of a schema `/docs` already renders is a bad trade at any price.

    *Vendor it and measure whether the worker is reachable.* Whether ReDoc
    needs the worker to render a spec — it may be search-only — and whether
    the Ajv path is dead in the standalone build cannot be answered by reading
    the bundle; it needs a browser, and no agent in this project has one.
    "Ship 1.1 MB of third-party JavaScript, then find out in production which
    half of it the policy refuses" is not a measurement, and a half-working
    API browser is worse than an honest 404 because its failure is silent.

    **What is lost is small and is named.** ReDoc is a three-pane read-only
    renderer of the same `/openapi.json` that `/docs` renders interactively,
    and `/docs` is vendored, served from this origin, and hashed. A reader who
    wants ReDoc's layout can point their own copy at `/openapi.json`.
    """
    raise HTTPException(
        404,
        "This build ships one API browser and it is at /docs. ReDoc is not "
        "vendored: it renders its search index in a blob: worker and carries "
        "a new Function() code path, and this app's Content-Security-Policy "
        "grants neither. The same schema is at /openapi.json.",
    )


@app.get("/api/version")
async def get_version():
    from core.constants import APP_VERSION
    return {"version": APP_VERSION}

@app.get("/api/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/api/client-perf")
async def client_perf(request: Request):
    """Low-volume frontend timing reports for stalls that happen before SSE logs."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        kind = str(data.get("type") or "client").replace("\n", " ")[:80]
        total_ms = float(data.get("total_ms") or 0)
        stages = data.get("stages") if isinstance(data.get("stages"), list) else []
        stage_txt = " ".join(
            f"{str(s.get('name') or '')[:40]}={float(s.get('delta_ms') or 0):.0f}ms"
            for s in stages[:20]
            if isinstance(s, dict)
        )
        extra = str(data.get("extra") or "").replace("\n", " ")[:200]
        logging.getLogger("app.client_perf").warning(
            "client_perf type=%s total=%.0fms %s%s",
            kind,
            total_ms,
            stage_txt,
            f" extra={extra}" if extra else "",
        )
    except Exception:
        logging.getLogger("app.client_perf").debug("client_perf log failed", exc_info=True)
    return {"ok": True}

@app.get("/api/ready")
async def readiness_check() -> JSONResponse:
    """Readiness / integrity self-check — DB, data dir, local-first storage.

    Unlike /api/health (liveness), this returns 503 unless every critical
    subsystem is whole, so an orchestrator can gate traffic on real readiness.
    """
    from src.readiness import check_readiness
    result = check_readiness()
    return JSONResponse(status_code=200 if result.get("ready") else 503, content=result)

@app.get("/api/runtime")
async def runtime_info() -> Dict[str, object]:
    in_docker = os.path.exists("/.dockerenv")
    if not in_docker:
        try:
            with open("/proc/1/cgroup", "r", encoding="utf-8", errors="ignore") as fh:
                cg = fh.read()
            in_docker = any(marker in cg for marker in ("docker", "containerd", "kubepods"))
        except Exception:
            in_docker = False
    ollama_url = (
        os.getenv("OLLAMA_BASE_URL")
        or os.getenv("OLLAMA_URL")
        or ("http://host.docker.internal:11434/v1" if in_docker else "http://127.0.0.1:11434/v1")
    )
    return {
        "in_docker": in_docker,
        "ollama_base_url": ollama_url,
    }

# ========= LIFECYCLE =========

@asynccontextmanager
async def _lifespan(app):
    """Modern lifespan context manager replacing deprecated @app.on_event."""
    # ── STARTUP ──
    await _startup_event()
    yield
    # ── SHUTDOWN ──
    await _shutdown_event()

app.router.lifespan_context = _lifespan


async def _startup_event():
    global upload_cleanup_task
    logger.info("Application starting up...")
    webhook_manager.set_loop(asyncio.get_running_loop())
    # Wipe any leftover incognito sessions from previous process — they're
    # ephemeral by design and must not survive a restart.
    try:
        from core.database import SessionLocal as _SL, Session as _DbSess, ChatMessage as _DbMsg
        _db = _SL()
        try:
            _ghosts = _db.query(_DbSess).filter(_DbSess.name.in_(("Nobody", "Incognito"))).all()
            for _g in _ghosts:
                _db.query(_DbMsg).filter(_DbMsg.session_id == _g.id).delete()
                _db.delete(_g)
            if _ghosts:
                _db.commit()
                logger.info(f"Purged {len(_ghosts)} leftover incognito session(s)")
        finally:
            _db.close()
    except Exception as e:
        logger.debug(f"Incognito purge skipped: {e}")
    # Strong refs to fire-and-forget startup tasks. Without this, Python may
    # GC tasks created with `asyncio.create_task(...)` before they finish.
    _startup_tasks: list[asyncio.Task] = getattr(app.state, "_startup_tasks", [])
    app.state._startup_tasks = _startup_tasks
    if upload_cleanup_func:
        upload_cleanup_task = asyncio.create_task(upload_cleanup_func())
    # Always-on monitor that auto-continues the agent when a background bash
    # job (#!bg) finishes — re-invokes the turn with the job output.
    try:
        from src.bg_monitor import start_bg_monitor
        _startup_tasks.append(start_bg_monitor())
    except Exception as _e:
        logger.warning("Failed to start background-job monitor: %s", _e)
    # MCP servers can be slow or blocked by local tooling. Connect them after
    # the web server is accepting traffic instead of delaying the whole UI.
    async def _startup_mcp_connections():
        try:
            from src.builtin_mcp import register_builtin_servers
            await register_builtin_servers(mcp_manager)
        except BaseException as e:
            logger.warning(f"Built-in MCP registration failed (non-critical): {type(e).__name__}: {e}")
        try:
            await mcp_manager.connect_all_enabled()
        except asyncio.TimeoutError:
            logger.warning("User MCP startup timed out (non-critical)")
        except BaseException as e:
            logger.warning(f"MCP startup failed (non-critical): {type(e).__name__}: {e}")

    _startup_tasks.append(asyncio.create_task(_startup_mcp_connections()))

    # Startup warmups are opt-in. They make later requests a little warmer, but
    # they also compete with the first seconds of real UI use on slow or busy
    # machines. Default to clear/idle startup and let requests warm what they use.
    _startup_warmups_enabled = env_flag("PANTHEON_STARTUP_WARMUPS", False)
    if _startup_warmups_enabled:
        async def _warmup_tool_index():
            try:
                from src.tool_index import get_tool_index
                idx = await asyncio.to_thread(get_tool_index)
                if idx:
                    await asyncio.to_thread(idx.get_tools_for_query, "warmup", 8)
                    logger.info("[startup] Tool index pre-warmed")
            except Exception as e:
                logger.warning(f"Tool index warmup failed (non-critical): {type(e).__name__}: {e}")

        _startup_tasks.append(asyncio.create_task(_warmup_tool_index()))

        async def _warmup_endpoints():
            try:
                import httpx
                urls = (
                    await asyncio.to_thread(model_discovery.warmup_ping_urls)
                    if model_discovery else []
                )
                for url in urls:
                    try:
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            await client.get(url)
                        logger.info(f"Warmup ping OK: {url}")
                    except Exception as e:
                        logger.debug(f"Warmup ping failed for endpoint: {e}")
            except Exception as e:
                logger.debug(f"Warmup ping skipped: {e}")

        _startup_tasks.append(asyncio.create_task(_warmup_endpoints()))
    else:
        logger.info("Startup warmups disabled (set PANTHEON_STARTUP_WARMUPS=1 to enable)")

    # Keep-alive is opt-in. The ping path performs model discovery, and when
    # stale LAN endpoints are configured it can add periodic backend pressure
    # that delays unrelated UI requests such as Notes/Documents.
    _keepalive_enabled = env_flag("PANTHEON_MODEL_KEEPALIVE", False)
    if _keepalive_enabled:
        async def _keepalive_loop():
            # `P15-10` — jittered. This one pings every configured endpoint,
            # so an exact sixty seconds means every install with the same
            # provider knocks in the same instant.
            from src.jitter import sleep_jittered
            while True:
                try:
                    await sleep_jittered(60)
                    await _warmup_endpoints()
                except Exception as e:
                    logger.warning(f"Keepalive loop error: {e}")
                    # Back off on error — and jittered especially here, because
                    # a provider outage fails every install at once and an exact
                    # backoff brings them all back together.
                    await sleep_jittered(300)

        _startup_tasks.append(asyncio.create_task(_keepalive_loop()))

    async def _ensure_default_tasks():
        # Create/reconcile default automation tasks + personal assistant for every user.
        owners = set()
        try:
            import json as _json
            auth_path = AUTH_FILE
            with open(auth_path, encoding="utf-8") as f:
                users = _json.load(f).get("users", {})
            owners.update(users.keys())
        except Exception as e:
            logger.debug(f"Default task auth-owner scan: {e}")

        # Also reconcile owners already present in scheduled_tasks. This cleans
        # up stale/demo/deleted-user built-ins that are no longer in auth.json;
        # otherwise their old scheduled rows can keep firing forever.
        try:
            from core.database import SessionLocal, ScheduledTask
            from src.task_scheduler import HOUSEKEEPING_DEFAULTS
            builtin_names = []
            for defs in HOUSEKEEPING_DEFAULTS.values():
                builtin_names.append(defs["name"])
                builtin_names.extend(defs.get("legacy_names") or [])
            db_seed = SessionLocal()
            try:
                rows = db_seed.query(ScheduledTask.owner).filter(
                    (ScheduledTask.action.in_(list(HOUSEKEEPING_DEFAULTS.keys())))
                    | (ScheduledTask.name.in_(builtin_names))
                ).distinct().all()
                owners.update(row[0] for row in rows if row[0])
            finally:
                db_seed.close()
        except Exception as e:
            logger.debug(f"Default task existing-owner scan: {e}")

        try:
            for uname in sorted(owners):
                try:
                    await task_scheduler.ensure_defaults(uname)
                except Exception as e:
                    logger.debug(f"ensure_defaults({uname}): {e}")
        except Exception as e:
            logger.debug(f"Default tasks: {e}")

    # Reconcile built-in tasks before the runner starts. Otherwise legacy
    # scheduled built-ins can fire once before being converted to event tasks.
    await _ensure_default_tasks()

    # Disk-backed skills are not covered by the DB legacy-owner sweep. Repair
    # ownerless or deleted/test-owner SKILL.md files so strict owner filtering
    # does not make an existing library look empty after auth/account changes.
    try:
        import json as _json
        auth_path = AUTH_FILE
        with open(auth_path, encoding="utf-8") as f:
            users = _json.load(f).get("users", {})
        primary_owner = None
        for uname, udata in users.items():
            if udata.get("is_admin") is True:
                primary_owner = uname
                break
        if not primary_owner and users:
            primary_owner = next(iter(users))
        if primary_owner:
            changed = skills_manager.backfill_owner(primary_owner, set(users.keys()))
            if changed:
                logger.info("Assigned %s legacy skill file(s) to %s", changed, primary_owner)
    except Exception as e:
        logger.debug(f"Skill owner backfill skipped: {e}")

    # Start scheduled task runner — skip when running under a cron-driven
    # deployment where an external worker drives task firing. Mirrors
    # `PANTHEON_INPROCESS_POLLERS` from the email pollers.
    # `B91`. Was an inline off-list that read a bare `PANTHEON_INPROCESS_TASKS=`
    # as *off*; blank now means unset, which is the rule `settings.env_backed`
    # already established for the string half of this question.
    if env_flag("PANTHEON_INPROCESS_TASKS", True):
        await task_scheduler.start()
    else:
        logger.info(
            "In-process task scheduler disabled (PANTHEON_INPROCESS_TASKS=0); "
            "drive task firing externally (e.g. cron)."
        )
    # Periodic null-owner sweep — re-runs the legacy-owner assignment hourly
    # so any data created while auth was disabled / localhost-bypassed gets
    # claimed by the admin instead of staying world-visible (M19).
    async def _null_owner_sweep_loop():
        # `P15-10` — jittered. This one is local-only, so it is not part of the
        # cross-install herd; it is spread anyway because "every recurring job"
        # is a rule worth being able to check mechanically, and an exception
        # that has to be argued each time is an exception nobody checks.
        from src.jitter import sleep_jittered
        while True:
            try:
                await sleep_jittered(3600)
                from core.database import _migrate_assign_legacy_owner
                await asyncio.to_thread(_migrate_assign_legacy_owner)
            except Exception as e:
                logger.debug(f"Null-owner sweep skipped: {e}")
                await sleep_jittered(3600)

    _startup_tasks.append(asyncio.create_task(_null_owner_sweep_loop()))

    # Nightly skill audit — at ~02:00 local, test + judge a batch of the
    # least-recently-checked skills, auto-fixing/escalating weak ones (never
    # deletes). Rotates through the library so each night covers different
    # skills. Gated by the `skill_audit_nightly` setting (default on); hour via
    # `skill_audit_hour` (default 2), batch size via `skill_audit_batch` (8).
    async def _skill_audit_nightly_loop():
        # `P15-10` — the worked example of why this matters. A nightly job at
        # exactly 02:00 is the single worst time to pick, because it is the time
        # everyone picks, and it is the job whose spike lands when nobody is
        # awake to see it. Spread across the five minutes after the hour.
        from src.jitter import next_daily_run
        while True:
            try:
                from src.settings import get_setting
                hour = int(get_setting("skill_audit_hour", 2) or 2)
            except Exception:
                hour = 2
            await asyncio.sleep(max(60, next_daily_run(hour)))
            try:
                from src.settings import get_setting
                if not get_setting("skill_audit_nightly", True):
                    continue
                batch = int(get_setting("skill_audit_batch", 8) or 8)
                from routes.skills_routes import run_scheduled_skill_audit
                await run_scheduled_skill_audit(skills_manager, owner=None, max_skills=batch)
            except Exception as e:
                logger.warning(f"Nightly skill audit failed: {e}")

    _startup_tasks.append(asyncio.create_task(_skill_audit_nightly_loop()))

    # Forge serve lifecycle — kills scheduler-launched serves whose
    # window-end has passed. Paired with the cookbook_serve builtin
    # action; both are no-ops unless a scheduled task actually launches
    # something with end_after_min set. Removing this line + the
    # cookbook_serve entry in BUILTIN_ACTIONS + src/cookbook_serve_lifecycle.py
    # removes the feature.
    from src.cookbook_serve_lifecycle import cookbook_serve_lifecycle_loop
    _startup_tasks.append(asyncio.create_task(cookbook_serve_lifecycle_loop()))

    # OTLP metrics push (`P16-19`) — the push half of `P16-12`, for a Pantheon
    # a collector cannot scrape into. The loop is unconditional and the WORK is
    # not: it wakes, reads `otlp_endpoint`, and goes back to sleep unless the
    # operator has set one. Gating the task on a setting read at startup would
    # mean turning the exporter on needed a restart, and the shipped state is
    # off, so that is the state that must be cheap to leave.
    from src.otlp_export import push_loop as _otlp_push_loop
    _startup_tasks.append(asyncio.create_task(_otlp_push_loop()))

    logger.info("Application startup complete")

async def _shutdown_event():
    logger.info("Application shutting down...")
    if upload_cleanup_task:
        upload_cleanup_task.cancel()
        try:
            await upload_cleanup_task
        except asyncio.CancelledError:
            pass
    # Stop task scheduler (no-op if it never started under the gate)
    try:
        await task_scheduler.stop()
    except Exception:
        pass
    # Close webhook manager
    try:
        await webhook_manager.close()
    except Exception as e:
        logger.warning(f"Webhook manager shutdown error: {e}")
    # Disconnect all MCP servers
    try:
        await mcp_manager.disconnect_all()
    except Exception as e:
        logger.warning(f"MCP shutdown error: {e}")
    logger.info("Application shutdown complete")


if __name__ == "__main__":
    import uvicorn

    bind_host = os.getenv("APP_BIND", "127.0.0.1")
    bind_port = int(os.getenv("APP_PORT", "7000"))

    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
