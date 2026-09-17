# SPDX-License-Identifier: AGPL-3.0-or-later
# src/middleware.py
# Shared middleware, decorators, and request helpers

import os
import secrets
from collections.abc import Mapping

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.routing import get_route_path

from src.owner_identity import INTERNAL_TOOL_USER, auth_disabled


# Per-process token that lets the in-app tool layer hit admin-gated
# routes via HTTP loopback (the agent's tool calls don't carry the
# admin user's session cookie). Set once at import; tools read the
# same value from this module. Never persisted or exposed externally.
INTERNAL_TOOL_TOKEN = os.environ.get("PANTHEON_INTERNAL_TOKEN") or secrets.token_hex(32)
INTERNAL_TOOL_HEADER = "X-Pantheon-Internal-Token"


def get_application_route_path(scope: Mapping[str, object]) -> str:
    """Return the application-relative path used by Starlette routing.

    Uvicorn prefixes ``scope["path"]`` with a configured ASGI ``root_path``;
    Starlette removes that prefix before matching routes. Middleware policy
    must use the same path form or a deployment prefix can change which policy
    applies to an otherwise unchanged application route.
    """
    return get_route_path(scope)


def with_asgi_root_path(scope: Mapping[str, object], path: str) -> str:
    """Prefix an application path for a client-facing redirect target.

    ``app_root_path`` is consulted first, and that is not cosmetic. Starlette's
    ``Mount`` rewrites ``root_path`` for the scope it hands its child —
    ``root_path + matched_path`` — while carrying the *deployment's* prefix
    forward unchanged as ``app_root_path``. So inside the ``/static`` mount
    ``root_path`` is ``/pantheon/static`` and only ``app_root_path`` is
    ``/pantheon``: a redirect built from ``root_path`` there would send a
    client asking for ``/pantheon/static/index.html`` to
    ``/pantheon/static/`` rather than to ``/pantheon/`` (`B262`). Outside a
    mount ``app_root_path`` is absent — Starlette sets it only when a mount
    matches — so every existing caller, `AuthMiddleware` included, reads the
    same ``root_path`` it always has.

    **Presence and not truthiness**, and the difference is the whole bug. On a
    deployment with no prefix at all, ``Mount`` still sets
    ``app_root_path = ""`` while rewriting ``root_path`` to ``/static``; a
    check that treated the empty string as "not set" would fall through to
    ``root_path`` and redirect ``/static/index.html`` to ``/static/``, which
    is what this did when it was first written and what the measurement
    caught. An ``app_root_path`` in the scope is the answer, empty or not.
    """
    root_path = scope.get("app_root_path")
    if not isinstance(root_path, str):
        root_path = scope.get("root_path", "")
    if not isinstance(root_path, str) or not root_path:
        return path
    return f"{root_path.rstrip('/')}{path}"


def path_is_route_or_child(path: str, prefix: str) -> bool:
    """Return whether ``path`` is exactly ``prefix`` or below that route."""
    return path == prefix or path.startswith(prefix + "/")


def is_cors_preflight(method: str, headers) -> bool:
    """True for a genuine CORS preflight: an OPTIONS request carrying the
    Access-Control-Request-Method header. Such requests are credential-less by
    design and must reach CORSMiddleware to be answered -- gating them on auth
    401s the preflight and breaks every cross-origin browser/WebView client.
    Pure so it can be unit-tested without standing up the app."""
    return method == "OPTIONS" and "access-control-request-method" in headers


def require_admin(request: Request):
    """Raise 403 if the current user isn't an admin.
    Allows access when auth is explicitly disabled, or when the request carries
    the in-process internal-tool token used by loopback agent tools.
    """
    # In-process bypass for tool-layer loopback calls. Two paths:
    # (a) header-direct (caller set X-Pantheon-Internal-Token), or
    # (b) the auth middleware already validated the token and stamped
    #     request.state.current_user = "internal-tool".
    try:
        hdr = request.headers.get(INTERNAL_TOOL_HEADER)
        if hdr and secrets.compare_digest(hdr, INTERNAL_TOOL_TOKEN):
            return
        if getattr(request.state, "current_user", None) == INTERNAL_TOOL_USER:
            return
    except Exception:
        pass

    auth_mgr = getattr(request.app.state, "auth_manager", None)
    if auth_disabled():
        return
    if not auth_mgr or not auth_mgr.is_configured:
        raise HTTPException(403, "Admin only")
    user = getattr(request.state, "current_user", None)
    if not user or not auth_mgr.is_admin(user):
        raise HTTPException(403, "Admin only")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate a per-request nonce for inline scripts
        nonce = secrets.token_hex(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)
        path = request.url.path

        # Tool render endpoints
        is_tool_render = path.startswith("/api/tools/") and path.endswith("/render")
        # Document library PDF preview endpoint
        is_document_pdf_preview = path.startswith("/api/document/") and path.endswith("/render-pdf")
        # Visual report pages are self-contained HTML — need inline scripts + external images
        is_report = path.startswith("/api/research/report/")
        # Served-back uploads: `GET /api/upload/{file_id}` (and `?thumb=1`),
        # plus the sibling stats/cleanup/vision routes. Matched on the same
        # `path` form as the three above; see the NOTE on prefix deployments
        # in the `elif is_upload` branch below.
        is_upload = path.startswith("/api/upload/")

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"

        is_https = (
            request.url.scheme == "https"
            or request.headers.get("X-Forwarded-Proto") == "https"
        )
        if is_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        if is_report:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; "
                # `https:` was here until 2026-09-01 (`P16-08`). It let an
                # `![](…)` in model output, a RAG document or an **email** make
                # the reader's browser fetch from a host nobody chose — their IP,
                # their user-agent, and the moment they opened it. Remote images
                # now go through /api/img, same-origin, and only when the
                # `remote_images` setting says so.
                "img-src 'self' data: blob:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            )
        elif is_tool_render:
            # Skip framing headers for tools.
            pass
        elif is_document_pdf_preview:
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "frame-ancestors 'self'"
            )
        elif is_upload:
            # Uploads are user-supplied bytes replayed from this app's own
            # origin. If one is ever opened as a top-level document it must
            # not be able to script against the session, so it gets a sandbox
            # instead of the app CSP below.
            #
            # This branch cannot live at the route. `UPLOAD_RESPONSE_HEADERS`
            # (routes/upload_routes.py) is applied by the handler, this
            # middleware runs after it, and starlette's
            # `MutableHeaders.__setitem__` replaces rather than appends — so a
            # `Content-Security-Policy` key added there is overwritten here and
            # never reaches the wire.
            #
            # `sandbox` with no other token means an opaque origin with
            # scripting, forms, popups, plugins and top-level navigation all
            # off. `allow-downloads` is granted deliberately: the chat
            # attachment UI does `window.open('/api/upload/<id>')`
            # (static/js/chatRenderer.js, static/js/chat.js) and that response
            # carries `Content-Disposition: attachment`, which a sandbox
            # lacking `allow-downloads` blocks. CSP is not applied to
            # subresource loads, so the inline `?thumb=1` previews are
            # unaffected either way.
            #
            # Defence in depth *behind* the route's `Content-Disposition:
            # attachment` and the nosniff set above — neither of which moves.
            #
            # NOTE: like the three branches above, this matches on
            # `request.url.path`, which still carries any ASGI `root_path`
            # prefix. Under a prefixed deployment the match misses and the
            # response falls through to the app CSP in the else-branch. The
            # whole method has that property; switching it to
            # `get_application_route_path(request.scope)` (the form
            # `AuthMiddleware` in app.py uses) is the fix, but this dispatch is
            # pinned by the `_FakeRequest` stub in
            # tests/test_document_render_pdf_iframe.py, which has no `.scope`
            # — so the two have to move together.
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = (
                # `default-src 'none'` costs nothing here and is strictly
                # tighter: an upload is served as a leaf document, so it has no
                # legitimate subresource to fetch. It cannot affect `?thumb=1`
                # either — CSP is not applied to subresources, only to the
                # document that loads them.
                "default-src 'none'; "
                "sandbox allow-downloads; "
                "frame-ancestors 'none'"
            )
        else:
            response.headers["X-Frame-Options"] = "DENY"
            # `B141`. What authorises this response's inline scripts, if it has
            # any. `serve_html_with_nonce` (src/app_helpers.py) stamps the
            # `'sha256-…'` sources of the page it just served onto
            # `request.state`, so the policy is derived from the document the
            # response *is* — not from a table here mapping routes to
            # templates, which would be a second list to keep in step with
            # `app.py` (`Law 13`, `Law 14`).
            #
            # A response that served no such page — an API reply, a static
            # asset, FastAPI's own `/docs` — gets neither a hash nor a nonce,
            # which is strictly tighter than the per-request nonce that used to
            # go out on every response in the app. Nothing loses a script by
            # it: an inline block with no nonce attribute was already refused,
            # because a `script-src` naming ANY nonce or hash source refuses
            # every inline block it does not name.
            inline_script_sources = list(
                getattr(request.state, "csp_script_hashes", ()) or ()
            )
            # `Law 1`: the nonce path is kept, not replaced. A template that
            # still carries `{{CSP_NONCE}}` is still substituted per request
            # and still gets its `'nonce-…'` source — it just no longer costs
            # every other response one.
            if getattr(request.state, "csp_nonce_used", False):
                inline_script_sources.append(f"'nonce-{nonce}'")
            script_src = " ".join(
                ["'self'", *inline_script_sources, "'wasm-unsafe-eval'"]
            )
            # NOTE: `style-src 'unsafe-inline'` is intentionally retained.
            # `static/index.html` and `static/login.html` ship inline <style>
            # blocks, and several JS modules build runtime `style=""` attrs.
            # Migrating to nonce-only requires templating the HTML files +
            # auditing every JS-set style attribute. Since inline styles
            # don't execute script, the residual risk is visual-only.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                # `https://cdn.jsdelivr.net` was in all three of these
                # until 2026-09-01 (`P16-07`). Pyodide was the only thing
                # that used it, and it is vendored now, so the last
                # external allowance in this policy is gone: every byte
                # this page loads comes from this origin.
                #
                # `'wasm-unsafe-eval'` is NOT a loosening — it is what
                # makes the vendoring work at all. A page with any
                # `script-src` cannot compile WebAssembly without it, so
                # dropping jsDelivr without adding this would have moved
                # the failure rather than fixed it: no request leaves, and
                # Python still does not run. It permits compiling wasm
                # bytes and nothing else — not `eval`, not inline script,
                # and not a byte from another origin.
                #
                # `'nonce-…'` was here until 2026-09-16 (`B141`). It is now
                # `'sha256-…'` per inline block, computed from the served file,
                # because a nonce has to be in the body and a body that varies
                # per request cannot carry a validator — which made `/` the one
                # precached URL of 213 that could not answer a conditional
                # request with a `304`. A hash is not a loosening: a nonce
                # authorises whatever bytes sit inside a tag carrying it, a
                # hash authorises those bytes and nothing else.
                f"script-src {script_src}; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; "
                # `https:` was here until 2026-09-01 (`P16-08`). It let an
                # `![](…)` in model output, a RAG document or an **email** make
                # the reader's browser fetch from a host nobody chose — their IP,
                # their user-agent, and the moment they opened it. Remote images
                # now go through /api/img, same-origin, and only when the
                # `remote_images` setting says so.
                "img-src 'self' data: blob:; "
                "media-src 'self' blob:; "
                "connect-src 'self'; "
                "frame-src 'self'; "
                "frame-ancestors 'none'"
            )
        return response
