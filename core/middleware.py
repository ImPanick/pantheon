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

from src.owner_identity import INTERNAL_TOOL_USER, REQUEST_SENTINEL_OWNERS


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

    **Supported: `uvicorn --root-path`. Not supported: Pantheon mounted inside
    another Starlette app** (`B371`). `Mount.matches` sets
    ``"app_root_path": scope.get("app_root_path", root_path)``, so the *outer*
    mount records the outer app's own prefix (``""``) on the scope it hands
    Pantheon, and a redirect built here — the sign-in redirect and the
    ``/static`` page redirects alike — drops ``/pantheon``. The row that found
    this said Starlette's own ``Request.url_for`` was wrong in the same shape;
    measured on Starlette 1.10.0 it is not (it resolves through the outermost
    router), so this is a limitation of this helper, written down rather than
    answered with a second derivation of "what prefix is this deployment
    behind" (`Law 14`) for a shape nobody deploys. `docs/setup.md` § *Serving
    under a path prefix* tells the operator to put a proxy in front, and
    `tests/test_a_nested_mount_is_written_down_as_unsupported.py` drives both
    shapes.

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


def _internal_request_person(request: Request):
    """Whether `request` is Pantheon's own loopback, and the person it names.

    Returns ``(internal, person)``. ``internal`` is the in-process tool
    loopback's two signals: (a) the request carries the internal-tool token
    (header-direct), or (b) the auth middleware already validated it and
    stamped ``request.state.current_user``. ``person`` is who the loopback acts
    for: the user the middleware attributed it to (`app.py`, from
    `X-Pantheon-Owner`), else the header's own value — a name the middleware
    did not find is still a person named, and is asked about, not dropped
    (`B1175`). ``None`` when the loopback names nobody: Pantheon itself.
    """
    internal = False
    try:
        hdr = request.headers.get(INTERNAL_TOOL_HEADER)
        if hdr and secrets.compare_digest(hdr, INTERNAL_TOOL_TOKEN):
            internal = True
        stamped = getattr(request.state, "current_user", None)
        if stamped == INTERNAL_TOOL_USER:
            internal = True
        if not internal:
            return False, None
        if stamped and stamped != INTERNAL_TOOL_USER:
            return True, stamped
        named = (request.headers.get("X-Pantheon-Owner") or "").strip()
        return True, (named or None)
    except Exception:
        # Unreadable is not "nobody named": fall through to the session check,
        # which a loopback cannot pass (fail closed).
        return False, None


def require_admin(request: Request):
    """Raise 403 if the current user isn't an admin.
    Allows access when the request is the in-process internal-tool loopback and
    names no person (Pantheon itself: the scheduler, the Forge lifecycle loop).

    `B1175`. **The assistant acts with its person's privileges, never more.**
    A loopback that names a person (`X-Pantheon-Owner`, which `app_api`, the
    image and research tools send) is asked the question that person's own
    request is asked: are they an admin. Until 2026-10-03 the token returned
    early whoever it named, so on every `require_admin` route the `app_api`
    blocklists do not name a non-admin's loopback was an admin — measured
    through the real `do_app_api` and the real app: bob, not an admin, got
    **403** from `GET /api/mcp/servers` in person and **200** through his
    loopback, with every server's `env` (where MCP servers keep their tokens).
    The dispatcher's `_ADMIN_ONLY_TOOLS` refuses `app_api` to a non-admin
    first, so the hole was one gate deep, not open; this is the route's own
    control holding under it. The adversary (`Law 17`): text a non-admin's
    assistant reads — a mail, a page, a document — steering it to an admin
    route. A single-user install's owner is its first account, the admin.
    `FORBIDDEN.md` Part 2 lists this control: tightened, never lifted.

    `D-2026-10-07-02` §2: there is always authentication, so there is no
    auth-off install to pass. Until 2026-10-07 `AUTH_ENABLED=false` returned
    here for everyone, a caller with no session included.
    """
    auth_mgr, user = _gated_person(request, "Admin only")
    if user is None:
        return
    if not auth_mgr.is_admin(user):
        raise HTTPException(403, "Admin only")


def _gated_person(request: Request, refusal: str):
    """Who an admin-family gate is asked about: `(auth_manager, person)`.

    `(auth_manager, None)` is Pantheon itself — the internal-tool loopback
    naming nobody — which every such gate lets through. A loopback naming a
    person is that person (`B1175`). Anything else that names nobody, or names
    a request sentinel, is refused with `refusal`. One answer for
    `require_admin` and `require_operator` (`B683`), so the two gates cannot
    disagree about who is asking.
    """
    internal, person = _internal_request_person(request)
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    if internal and person is None:
        return auth_mgr, None
    if not auth_mgr or not auth_mgr.is_configured:
        raise HTTPException(403, refusal)
    user = person if internal else getattr(request.state, "current_user", None)
    # `B543`. A request sentinel is never an admin, whatever the store says:
    # `api` is what `AuthMiddleware` names a bearer-token request (`B70` — a
    # credential its owner handed to something else), and the others name no
    # person either. `routes/shell_routes.py` kept its own copy of this gate
    # for that one refusal; it is here now, so the shell asks this function
    # like every other admin route and there is one answer to "is this an
    # admin". All are reserved usernames, so no account can hold one — this
    # is the refusal said where it is decided, not a new one.
    if not user or user in REQUEST_SENTINEL_OWNERS:
        raise HTTPException(403, refusal)
    return auth_mgr, user


#: `B683`. What a person is told at an operator gate they may not pass — who
#: may, and where the door is (`Law 15`), never a bare "Admin only".
OPERATOR_REFUSAL = (
    "Only an admin, or someone an admin has let run this instance, can do this. "
    "An admin can turn on “Run this instance” for you in Settings → Users.")


def require_operator(request: Request):
    """`B683`. The gate for running the instance — `require_admin` with one more door.

    `.pantheon/P11-AUTH-MAP.md` tiers every admin gate, and its `operator`
    tier — models and endpoints, the Forge's serving, diagnostics and logs,
    webhooks, the embeddings, the personal index, the workstation's machines —
    is the work of keeping the box up, which needs none of the `superuser`
    tier above it. Until this gate those sites asked `is_admin`, so the only
    way to hand somebody the operator's job was to hand them the owner's.

    It answers **yes** to these callers and no others: Pantheon itself (the
    loopback naming nobody, as `require_admin`); an admin, asked through
    `require_admin` unchanged, so an admin's way in never depends on the
    privilege store (`B531`); and a person whose privileges resolve
    `can_run_instance` to `True` — per person, or through a role
    (`resolve_privilege`, the one rule: user → role → registry, and the
    registry declares it `False`). A loopback naming a person is that person
    (`B1175`); a bearer token is the `api` sentinel and is refused (`B70`).

    The adversary (`Law 17`) is a signed-in person nobody granted it, and
    text their assistant reads steering it here; both are refused. A store
    that cannot be read refuses a non-admin with `PRIVILEGE_STORE_SENTENCE`
    (`D-2026-10-26-01` §1) — it never grants.
    """
    try:
        require_admin(request)
        return
    except HTTPException:
        pass
    auth_mgr, user = _gated_person(request, OPERATOR_REFUSAL)
    if user is None:  # Pantheon itself — `require_admin` already said yes
        return
    from core.auth import OPERATOR_PRIVILEGE
    from src.auth_helpers import privileges_or_refuse, resolve_privilege
    if resolve_privilege(privileges_or_refuse(auth_mgr, user), OPERATOR_PRIVILEGE) is True:
        return
    raise HTTPException(403, OPERATOR_REFUSAL)


def runs_instance(request: Request) -> bool:
    """`B683`. Whether `require_operator` would let this request through.

    For a route open to every signed-in person that shows the person who runs
    the instance more — the endpoint list (`GET /api/model-endpoints`), the
    workstation's status — asked of the gate itself rather than restated.
    """
    try:
        require_operator(request)
    except HTTPException:
        return False
    return True


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
        # `P26-07`. A design's page, framed by the Design window: its own
        # scripts and the picker run, in an opaque origin, reaching nothing.
        is_design_preview = path.startswith("/api/design/designs/") and path.endswith("/preview")
        # Served-back uploads: `GET /api/upload/{file_id}` (and `?thumb=1`),
        # plus the sibling stats/cleanup/vision routes. Matched on the same
        # `path` form as the three above; see the NOTE on prefix deployments
        # in the `elif is_upload` branch below.
        is_upload = path.startswith("/api/upload/")
        # `B1474`. The frame a person's Python block runs in (Pyodide), and
        # the vendored runtime it loads from an opaque origin.
        is_python_sandbox = path == "/python-sandbox"
        is_pyodide_asset = "/static/lib/pyodide/" in path
        # `D-2026-10-31-01`. The live desktop's web client (KasmVNC's), framed
        # by the Workstation window (`src/desktop_client.py`).
        is_desktop_client = path.startswith("/api/workstation/desktop/client/")

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
        elif is_python_sandbox:
            # An opaque origin like the design preview: no cookie, no storage,
            # no reach into this app's window. It runs this origin's vendored
            # Pyodide (`'wasm-unsafe-eval'` compiles its wasm and nothing else)
            # and fetches only from this origin — where a request carries no
            # session, because the frame is not same-site with anything.
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "script-src 'self' 'wasm-unsafe-eval'; "
                # The runner's Worker is a blob of the frame's own script, so
                # a block that never ends blocks that thread, not the page.
                "worker-src blob:; "
                "connect-src 'self'; "
                "sandbox allow-scripts; "
                "frame-ancestors 'self'"
            )
        elif is_design_preview:
            # A page the agent (or a hand) wrote, run as a design runs. The
            # sandbox makes it an opaque origin — no cookie, no storage, no
            # reach into this app or its window — and `default-src 'none'`
            # means it fetches nothing at all: its stylesheets, scripts and
            # small images arrive inlined (`design_files.bundle`), so a design
            # that names a remote font or script shows without it (`Law 16`).
            # Framed only by this app's own pages.
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; "
                "img-src data: blob:; "
                "font-src data:; "
                "media-src data: blob:; "
                "sandbox allow-scripts; "
                "frame-ancestors 'self'"
            )
        elif is_desktop_client:
            # Pantheon's own copy of a vendored client, framed by Pantheon's own
            # pages and nobody else's. Same-origin and not sandboxed, because
            # the client keeps its settings in this origin's storage and runs a
            # SharedWorker, and an opaque origin has neither; what keeps it
            # honest is that every byte of it is the image's (no route writes
            # under its folder), its inline block runs by its hash and nothing
            # else inline does, and it connects to nothing but this origin —
            # the desktop's stream, relayed. `'wasm-unsafe-eval'` is its frame
            # decoder; workers are its own files.
            inline_script_sources = " ".join(
                getattr(request.state, "csp_script_hashes", ()) or ())
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' {inline_script_sources} 'wasm-unsafe-eval'; ".replace("  ", " ")
                + "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "font-src 'self'; "
                "media-src 'self' data: blob:; "
                "connect-src 'self'; "
                "worker-src 'self' blob:; "
                "frame-src 'none'; "
                "object-src 'none'; "
                "base-uri 'none'; "
                "form-action 'none'; "
                "frame-ancestors 'self'"
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
        if is_pyodide_asset:
            # `B1474`. The Python sandbox is an opaque origin, so its fetches of
            # the runtime's wasm, stdlib and lock file are cross-origin. These
            # are public, vendored, checksum-pinned files and the requests carry
            # no credentials; nothing else under /static gets this.
            response.headers["Access-Control-Allow-Origin"] = "*"
        return response
