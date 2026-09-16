# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one gate that decides whether an SVG is safe to render, and its headers.

`B103`. SVG is markup, not a picture: it can carry `<script>`, `on*` handlers
and references to other origins, which is why `.pantheon/DECISIONS.md`
D-2026-08-26-01 names it the one real stored-XSS vector in the upload area. The
product already answered that question once — `routes/emoji_routes.py` checked
every vendored glyph before serving it and shipped it under a fixed header set —
but the answer lived inside a route module, so the upload preview could not ask
it. This is that code, lifted to where both callers can reach it (`Law 13`);
`emoji_routes` imports these names and its behaviour is unchanged.

Two questions, deliberately kept apart:

* **Is this an image the vision model can read?** ``upload_handler.is_image_file``
  answers that, and the answer for SVG is *no* — most vision models reject
  ``image/svg+xml``. `B76` routed SVG to the text arm instead, so the model gets
  the XML source and can edit it. Nothing here changes that, and adding `.svg`
  to ``is_image_file`` would undo it: the file would be base64'd into an
  ``image_url`` the model cannot use, and the source would stop arriving.
* **Can this be shown as a picture?** That is this module, and it is only ever
  answered by rendering bytes the sanitiser has passed.

Deliberately no rasteriser. The row that asked for this assumed "a
PIL-regenerated raster thumbnail", and PIL cannot parse SVG at all — measured,
``Image.open`` on a valid SVG raises ``UnidentifiedImageError``. The only
rasteriser within reach is PyMuPDF, which is optional (``requirements-optional.txt``)
and would mean parsing untrusted markup in a C library to produce a picture the
browser can already draw from the same bytes. Sanitise and serve inert is the
smaller, testable answer; ``is_safe_svg`` is conservative and refuses more than
a tree-rewriting sanitiser would (see `B160`).
"""

import re

SVG_EXTS = frozenset({".svg"})
SVG_MIME_TYPES = frozenset({"image/svg+xml"})

# Work bound on the scan below, per caller. The emoji route keeps its own
# 256 KiB — a vendored line-art glyph is under 4 KiB and anything larger is not
# one — while an uploaded diagram is allowed 2 MiB before it stops being a thing
# worth previewing.
MAX_SVG_BYTES = 256 * 1024
MAX_PREVIEW_SVG_BYTES = 2 * 1024 * 1024

BLOCKED_SVG_RE = re.compile(
    br"<\s*(?:script|foreignObject|iframe|object|embed|image)\b|"
    br"\bon[a-z0-9_-]+\s*=",
    re.IGNORECASE,
)
# An SVG that reaches out is a beacon: it tells a third party that this person
# opened this file, from this address, at this moment (`Law 16` — nothing routes
# to an external service unless someone linked it). Browsers already refuse this
# for an SVG drawn inside an `<img>`; the check is here because "the browser
# would have stopped it" is not a control we own.
EXTERNAL_REF_RE = re.compile(
    br"\b(?:href|xlink:href)\s*=\s*['\"](?:https?:|//|data:|javascript:)",
    re.IGNORECASE,
)

# Every response carrying SVG bytes gets these. `sandbox` with no allow-list
# kills script in the contexts `<img>` does not already make inert (a direct
# navigation, an `<iframe>`, an `<object>`), `nosniff` stops a mislabelled file
# being re-typed into one, and the CORP header keeps another origin from
# embedding it.
SVG_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",
    "Cross-Origin-Resource-Policy": "same-origin",
}

# Shown instead of an SVG that fails the check: a valid, empty, 1x1 image. The
# preview slot collapses to nothing rather than sitting on a spinner, and the
# refused bytes are never sent.
BLANK_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>'


def is_svg(filename: str = "", content_type: str | None = None) -> bool:
    """True when *filename* or *content_type* says SVG.

    Name first, because ``mimetypes.guess_type`` is the only classifier on a
    pip/venv install (python-magic ships in the Docker image alone) and a file
    stored as ``<uuid32>.svg`` still carries the suffix.
    """
    name = (filename or "").lower()
    if any(name.endswith(ext) for ext in SVG_EXTS):
        return True
    return (content_type or "").split(";")[0].strip().lower() in SVG_MIME_TYPES


def is_safe_svg(content: bytes, max_bytes: int = MAX_SVG_BYTES) -> bool:
    """True when these bytes can be rendered without running anything.

    Conservative by construction: it refuses a file rather than rewriting it, so
    a legitimate diagram carrying an embedded raster (``<image href="data:…">``)
    or a hyperlink is refused too. That is the right trade for a preview — the
    upload itself is untouched and still downloads — and the cost is written
    down as `B160` rather than left as a surprise.
    """
    if not isinstance(content, bytes) or not content:
        return False
    if len(content) > max_bytes:
        return False
    if b"<svg" not in content[:256].lower():
        return False
    if BLOCKED_SVG_RE.search(content) or EXTERNAL_REF_RE.search(content):
        return False
    return True
