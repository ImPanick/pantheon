# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where this Pantheon is reachable from, according to whoever knows best.

`P18-04`. The row said *"`app_public_url` is a setting an operator can type and
no OAuth path reads"*. That is true and it undersells it, because the reason is
worse than an oversight:

**THERE IS A SETTING CALLED `app_public_url` AND AN ENVIRONMENT VARIABLE CALLED
`APP_PUBLIC_URL`, AND THEY WERE NEVER THE SAME THING.**

`src/settings.py` ships `app_public_url`, the Settings panel has a field for it,
and `src/mcp_oauth.py` reads `os.environ["APP_PUBLIC_URL"]`. An operator typing
their public URL into the box changed nothing about either OAuth flow, and the
two names are indistinguishable when anybody describes the problem out loud. The
panel's own label says the field is *"used for deep-links in outgoing alert
emails"* — which was accurate, and is the smallest possible slice of what a
reader assumes a setting named *public URL* controls.

The email OAuth path did not consult either. It built its redirect from the
request's **`Host` header and `request.url.scheme`**, and behind a reverse proxy
both are wrong in the same direction: uvicorn only honours `X-Forwarded-Proto`
from a peer inside `--forwarded-allow-ips`, which defaults to `127.0.0.1` and
excludes a proxy arriving over the Docker bridge. So an HTTPS deployment builds
an `http://` redirect, Google compares it to the registered URI and answers
`redirect_uri_mismatch` — the whole *"it works on my laptop and not on my
server"* class, from one header.

**THE REQUEST STAYS AS A FALLBACK, WHICH IS THE POINT OF THE ORDER BELOW.**
Somebody reaching Pantheon at `http://192.168.1.71:7000` today works *because*
of the `Host` header, and the fix must not take that away (`Law 1`). So nothing
is removed: higher-precedence sources are added above it, and the derived
localhost default stays underneath for the case where there is no request at all
(a module-level constant, a background job).

Order, most trusted first — each one is somebody making a claim, and they are
ranked by how much they could know:

  1. `OAUTH_REDIRECT_BASE_URL` — a deployment saying this exact origin, for this
     exact purpose.
  2. `APP_PUBLIC_URL` — a deployment saying where it is reachable.
  3. the `app_public_url` **setting** — an operator saying so in the panel.
  4. the request — the browser saying which door it came through. Right far more
     often than not, and wrong in precisely the case the three above exist for.
  5. `http://localhost:{APP_PORT}` — no information at all, and `APP_PORT`
     rather than a fixed 7000 because the macOS launcher binds 7860 when AirPlay
     Receiver holds 7000, and a callback on the wrong port reaches nothing.

Environment outranks the setting because a deployment's declaration should not
be silently overridden from a web form — **but a field that is being overridden
has to say so**, or it is the same defect wearing a hat. `source_of()` exists
for that, and `routes/email_routes.py` reports it beside the computed redirect
URI so an operator can see both what will be used and who decided it.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

ENV_EXPLICIT = "OAUTH_REDIRECT_BASE_URL"
ENV_PUBLIC = "APP_PUBLIC_URL"
SETTING = "app_public_url"

# Read the same way `app.py` and `launcher.py` read it.
DEFAULT_PORT = "7000"


def _clean(value) -> str:
    return str(value or "").strip().rstrip("/")


def _from_setting() -> str:
    """The operator's typed value, or `""` if settings cannot be read.

    Imported inside the call rather than at module scope: this module is
    imported by `src/mcp_oauth.py`, which is imported during startup, and
    `src.settings` reads a file. A settings read that fails must not take an
    import down — it only means nobody typed anything, which is the common case.
    """
    try:
        from src.settings import get_setting

        return _clean(get_setting(SETTING, ""))
    except Exception:
        return ""


def _from_request(request) -> str:
    """The origin the browser used, as far as this process can tell.

    Wrong behind a proxy that this app is not configured to trust, which is
    exactly why it sits below the three deliberate sources.
    """
    if request is None:
        return ""
    try:
        host = request.headers.get("host", "")
        if not host:
            return ""
        return _clean(f"{request.url.scheme}://{host}")
    except Exception:
        return ""


def _derived() -> str:
    return f"http://localhost:{os.environ.get('APP_PORT', DEFAULT_PORT)}"


def resolve(request=None) -> Tuple[str, str]:
    """The origin, and the name of whoever supplied it."""
    explicit = _clean(os.environ.get(ENV_EXPLICIT))
    if explicit:
        return explicit, ENV_EXPLICIT
    public = _clean(os.environ.get(ENV_PUBLIC))
    if public:
        return public, ENV_PUBLIC
    setting = _from_setting()
    if setting:
        return setting, SETTING
    from_request = _from_request(request)
    if from_request:
        return from_request, "request"
    return _derived(), "default"


def public_origin(request: Optional[object] = None) -> str:
    """Scheme and authority with no trailing slash, e.g. `https://pan.example`."""
    return resolve(request)[0]


def source_of(request: Optional[object] = None) -> str:
    """Which source won. Shown to the operator so an override is never silent."""
    return resolve(request)[1]


def setting_is_overridden() -> bool:
    """True when the panel's field is set and an environment variable outranks it.

    The field going quiet is the defect this whole module is about, so the
    panel is given a way to say *your value is not the one being used* rather
    than leaving somebody to discover it from a `redirect_uri_mismatch`.
    """
    if not _from_setting():
        return False
    return bool(_clean(os.environ.get(ENV_EXPLICIT)) or _clean(os.environ.get(ENV_PUBLIC)))
