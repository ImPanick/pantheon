# SPDX-License-Identifier: AGPL-3.0-or-later
"""Same-origin proxy for remote images in rendered content (`P16-08`).

**The problem.** `img-src` allowed any `https:` host, so an `![](…)` in model
output, a RAG document or an **email** made the reader's browser fetch from a
host nobody chose. Content the user did not author, causing their browser to
announce — with their IP, their user-agent, and the timing of when they read it
— that they had opened it. That is a tracking pixel, and mail is full of them.

**Why a proxy is not, on its own, the answer.** Routing the fetch through the
server protects the reader's browser and IP, and caching means one fetch serves
every view — but the request still leaves the machine, for content the user
never chose. Under `Law 16` that is the same defect one hop further away.

**So the default is `ask`, and the proxy is what "yes" does.** A remote image
renders as a placeholder naming its host until someone clicks it. Three modes,
`remote_images`:

  * `ask`   — placeholder, click to load (**default**; nothing leaves unasked)
  * `proxy` — fetch through here automatically; the browser still never talks
              to the third party, and the fetch is cached and deduped
  * `block` — never fetch, ever

The proxy itself is deliberately boring and suspicious of what it gets back:
auth required, SSRF-guarded and DNS-pinned via `outbound_fetch`, paced by the
`P15` limiter, size-capped, `image/*` only, **`image/svg+xml` refused** because
SVG carries script (`FORBIDDEN.md` Part 2 keeps `svg` out of `IMAGE_EXTS` for
the same reason), and cached on disk by URL hash.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024

# What a browser may be told to render. SVG is absent on purpose: it executes.
ALLOWED_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}

MODE_ASK = "ask"
MODE_PROXY = "proxy"
MODE_BLOCK = "block"
VALID_MODES = (MODE_ASK, MODE_PROXY, MODE_BLOCK)


def remote_image_mode() -> str:
    """How to treat images the user did not author. Defaults to `ask`."""
    try:
        from src.settings import get_setting

        mode = str(get_setting("remote_images", MODE_ASK) or MODE_ASK).strip().lower()
    except Exception:
        return MODE_ASK
    return mode if mode in VALID_MODES else MODE_ASK


def _cache_dir() -> Path:
    from src.constants import DATA_DIR

    d = Path(DATA_DIR) / "remote_image_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _cached(url: str) -> Optional[tuple[bytes, str]]:
    key = _cache_key(url)
    for ctype, ext in ALLOWED_TYPES.items():
        f = _cache_dir() / f"{key}{ext}"
        if f.exists():
            try:
                return f.read_bytes(), ctype
            except OSError:
                return None
    return None


def _store(url: str, body: bytes, ctype: str) -> None:
    ext = ALLOWED_TYPES.get(ctype)
    if not ext:
        return
    try:
        tmp = _cache_dir() / f"{_cache_key(url)}{ext}.tmp"
        tmp.write_bytes(body)
        os.replace(tmp, _cache_dir() / f"{_cache_key(url)}{ext}")
    except OSError:
        logger.debug("could not cache remote image", exc_info=True)


def _require_session(request: Request) -> None:
    """Refuse an unauthenticated caller, belt-and-braces.

    `AuthMiddleware` already 401s every `/api/` path when `AUTH_ENABLED` is on,
    so in the normal build this never fires. It is here because this route
    fetches an arbitrary URL on the caller's behalf: if the global gate is ever
    reordered, relaxed, or mounted differently, an *open proxy* is the failure
    mode, and that is not a failure to discover in production. When auth is
    switched off entirely the middleware is absent by design and so is this —
    the operator has said the box is trusted.
    """
    from src.owner_identity import auth_disabled

    if auth_disabled():
        return
    if not getattr(request.state, "current_user", None):
        raise HTTPException(401, "Not authenticated")


def setup_image_proxy_routes() -> APIRouter:
    router = APIRouter(tags=["images"])

    @router.get("/api/img")
    async def proxy_image(request: Request, u: str = Query(..., max_length=2048)) -> Response:
        """Fetch a remote image server-side so the reader's browser never does.

        Not an open proxy: it requires a session, refuses anything that is not
        a bitmap image, and cannot be pointed at a private address — the
        SSRF guards and DNS pinning in `outbound_fetch` see to that.
        """
        _require_session(request)

        if remote_image_mode() == MODE_BLOCK:
            raise HTTPException(403, "Remote images are turned off.")

        parsed = urlparse(u)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HTTPException(400, "Not an http(s) image URL.")

        hit = _cached(u)
        if hit:
            body, ctype = hit
            return Response(content=body, media_type=ctype, headers={
                "Cache-Control": "private, max-age=86400",
                "X-Content-Type-Options": "nosniff",
                "X-Pantheon-Image": "cache",
            })

        from src.outbound_fetch import _get_public_url
        from src.rate_limiter import OutboundRateLimited, host_of, outbound

        try:
            outbound.acquire(host_of(u))
        except OutboundRateLimited as e:
            raise HTTPException(429, str(e)) from e

        try:
            fetched = _get_public_url(
                u,
                {"Accept": "image/*", "User-Agent": "Pantheon/1.0 (+image-proxy)"},
                timeout=15,
                max_bytes=MAX_IMAGE_BYTES,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.info("remote image fetch failed for %s: %s", host_of(u), e)
            raise HTTPException(502, "Could not fetch that image.") from e

        status = getattr(fetched, "status_code", 200) or 200
        headers = {str(k).lower(): str(v) for k, v in dict(getattr(fetched, "headers", {}) or {}).items()}
        outbound.observe(host_of(u), status, headers)
        if status >= 400:
            raise HTTPException(502, "That image could not be fetched.")

        ctype = (headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype not in ALLOWED_TYPES:
            # Includes image/svg+xml, refused deliberately: SVG executes script,
            # and this path serves bytes a stranger chose to a logged-in origin.
            raise HTTPException(415, "That URL is not a supported image type.")

        body = getattr(fetched, "content", b"") or b""
        if not body:
            raise HTTPException(502, "That image was empty.")
        if len(body) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "That image is too large.")

        _store(u, body, ctype)
        return Response(content=body, media_type=ctype, headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "X-Pantheon-Image": "fetch",
        })

    @router.get("/api/img/mode")
    async def get_mode(request: Request) -> dict:
        """What the frontend should do with remote images."""
        _require_session(request)
        return {"mode": remote_image_mode()}

    return router
