# SPDX-License-Identifier: AGPL-3.0-or-later
# routes/emoji_routes.py
# Same-origin emoji SVG proxy. The frontend rewrites emoji in chat to a
#   <span class="emoji" style="--em:url('/api/emoji/<codepoints>.svg')">
# which uses the returned SVG as a CSS mask tinted to the text color, so emoji
# render as monochrome line icons (project rule: never colorful emoji). The
# black line-art SVGs ship with the product (`P16-06`, 2026-09-01). They used to
# be lazily fetched from the OpenMoji CDN on first use — same-origin from the
# client's side, but the *server* reached a third party on roughly the first
# assistant reply, because models emit emoji constantly. Under `Law 16` that is
# an outbound call nobody asked for, and the codepoint sequence is a weak
# side-channel about what a message contained.
#
# Vendored as **one 5 MB JSON**, not 4,147 files: the same bytes cost 18 MB on
# disk as separate files, and a single blob is kinder to git and the filesystem.
# Each entry holds only the inner markup — the identical stroke attributes every
# glyph in this set repeats are hoisted onto one wrapping `<g>` at serve time,
# which is most of the 7.6 MB -> 5.0 MB saving.
#
# OpenMoji is **CC BY-SA 4.0** and was being used with no attribution anywhere in
# the repo until this row. See `CREDITS.md` and `licenses/`.
# Unknown/unreachable codepoints return a transparent SVG (not 404), so the CSS
# mask shows nothing rather than a solid currentColor box.
import logging
import re
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from src.constants import EMOJI_CACHE_DIR

logger = logging.getLogger(__name__)

# Vendored OpenMoji, loaded once and kept. 5 MB of JSON is a real amount of
# resident memory, so it loads lazily — an install that never renders an emoji
# never pays for it.
_GLYPHS: dict | None = None


def _library_path() -> Path:
    import os

    here = Path(__file__).resolve().parent.parent      # repo root
    return Path(os.environ.get("PANTHEON_EMOJI_LIBRARY")
                or here / "library" / "emoji" / "openmoji-black.json")


def _glyphs() -> dict:
    """The vendored set. Empty dict if absent — not an error, just no emoji."""
    global _GLYPHS
    if _GLYPHS is None:
        import json as _json
        try:
            _GLYPHS = _json.loads(_library_path().read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("emoji library unavailable: %s", e)
            _GLYPHS = {}
    return _GLYPHS


# The attributes hoisted out of every glyph at vendoring time, put back here.
_SVG_OPEN = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72">'
    '<g fill="none" stroke="#000000" stroke-linecap="round" '
    'stroke-linejoin="round" stroke-width="2">'
)
_SVG_CLOSE = "</g></svg>"

_CACHE_DIR = Path(EMOJI_CACHE_DIR)
# OpenMoji "black" set = monochrome line-art SVGs, keyed by the codepoints
# lowercased (FE0F dropped, same as we compute), '-' joined. The CDN base that
# used to live here is gone with the fetch that used it (`P16-06`).
# codepoints like "1f600" or "1f468-200d-1f469-200d-1f467" (lowercase hex, '-' joined)
_CODE_RE = re.compile(r"^[0-9a-f]{2,6}(?:-[0-9a-f]{2,6})*$")
_MAX_SVG_BYTES = 256 * 1024
_BLOCKED_SVG_RE = re.compile(
    br"<\s*(?:script|foreignObject|iframe|object|embed|image)\b|"
    br"\bon[a-z0-9_-]+\s*=",
    re.IGNORECASE,
)
_EXTERNAL_REF_RE = re.compile(
    br"\b(?:href|xlink:href)\s*=\s*['\"](?:https?:|//|data:|javascript:)",
    re.IGNORECASE,
)
_SVG_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",
    "Cross-Origin-Resource-Policy": "same-origin",
}
_SVG_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    **_SVG_SECURITY_HEADERS,
}
# Returned when a codepoint is unknown/unreachable: an empty (transparent) SVG,
# so the CSS mask renders nothing instead of a solid box. Not cached, so a later
# request can still pick up the real glyph once the CDN is reachable.
_BLANK_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>'
_BLANK_HEADERS = {"Cache-Control": "no-store", **_SVG_SECURITY_HEADERS}


def _is_safe_svg(content: bytes) -> bool:
    if not isinstance(content, bytes) or not content:
        return False
    if len(content) > _MAX_SVG_BYTES:
        return False
    if b"<svg" not in content[:256].lower():
        return False
    if _BLOCKED_SVG_RE.search(content) or _EXTERNAL_REF_RE.search(content):
        return False
    return True


def setup_emoji_routes() -> APIRouter:
    router = APIRouter(prefix="/api/emoji", tags=["emoji"])

    def _blank() -> Response:
        return Response(_BLANK_SVG, media_type="image/svg+xml", headers=_BLANK_HEADERS)

    @router.get("/{code}.svg")
    async def emoji_svg(code: str):
        code = code.lower()
        if not _CODE_RE.match(code):
            return _blank()

        body = _glyphs().get(code)
        if body is None:
            # Unknown codepoint, or the library is absent. Blank, not 404, so the
            # CSS mask shows nothing rather than a solid currentColor box.
            return _blank()

        content = (_SVG_OPEN + body + _SVG_CLOSE).encode("utf-8")
        # Still sanitised, even though these bytes shipped with the product. The
        # check is cheap, this is served to a logged-in origin, and a guard that
        # only runs on the path you distrust is one you have already reasoned
        # your way out of once.
        if not _is_safe_svg(content):
            logger.warning("vendored emoji %s failed the SVG check", code)
            return _blank()
        return Response(content, media_type="image/svg+xml", headers=_SVG_HEADERS)

    return router
