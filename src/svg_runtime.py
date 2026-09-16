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

import html
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


# ── what a caption means for a drawing that is made of words (`B163`) ───────
#
# `/api/upload/{id}/vision` gated on ``mime.startswith("image/")``, which
# ``image/svg+xml`` satisfies, so the Caption button base64'd an SVG's XML and
# posted it to a vision model — labelled ``data:image/jpeg`` at that, because
# ``analyze_image_with_vl_result``'s ``mime_map`` has no ``.svg`` and falls back
# to jpeg. An outbound call that cannot succeed (`Law 16`), and the module
# docstring above already says why: SVG is markup to the model.
#
# The button is still the right button. What a vision model does for a raster is
# recover the words in the picture; an SVG *carries* its words, in `<title>`,
# `<desc>` and its `<text>` runs, where `<title>` and `<desc>` are precisely the
# accessible name and description the format defines for this purpose. So the
# caption is read out of the file, with no model and no network, and it is more
# accurate than a description of the same drawing would have been.
SVG_CAPTION_MAX_CHARS = 2000

# Regex, not an XML parser, and for the same reason the safety gate above is:
# these bytes are untrusted, and ``xml.etree`` on untrusted input is a parser
# that expands entities. Nothing here is trying to understand the drawing — it
# collects the character data of three element names and stops.
_SVG_NAMED_RE = re.compile(br"<\s*(title|desc)\b[^>]*>(.*?)<\s*/\s*\1\s*>",
                           re.IGNORECASE | re.DOTALL)
_SVG_TEXT_RE = re.compile(br"<\s*text\b[^>]*>(.*?)<\s*/\s*text\s*>",
                          re.IGNORECASE | re.DOTALL)
_SVG_INNER_TAG_RE = re.compile(br"<[^>]*>")
_WHITESPACE_RE = re.compile(r"\s+")


def _svg_chardata(fragment: bytes) -> str:
    """The words inside one element, with child markup (``<tspan>``) removed."""
    stripped = _SVG_INNER_TAG_RE.sub(b" ", fragment)
    text = html.unescape(stripped.decode("utf-8", errors="replace"))
    return _WHITESPACE_RE.sub(" ", text).strip()


def svg_caption_text(content: bytes, max_chars: int = SVG_CAPTION_MAX_CHARS) -> str:
    """The caption an SVG already contains, or ``""`` when it contains none.

    ``<title>`` and ``<desc>`` first, in document order, then every ``<text>``
    run — a labelled diagram captions itself. Bounded twice: the scan stops at
    ``MAX_PREVIEW_SVG_BYTES`` and the answer at *max_chars*, because this runs on
    a file someone else supplied.

    An empty answer is a real answer ("this drawing has no words in it") and the
    caller says so rather than falling back to the model — a shape-only SVG is
    the case the vision model could have helped with and is exactly the case it
    cannot be handed, since the type is what it rejects.
    """
    if not isinstance(content, bytes) or not content:
        return ""
    head = content[:MAX_PREVIEW_SVG_BYTES]
    named = [_svg_chardata(m.group(2)) for m in _SVG_NAMED_RE.finditer(head)]
    runs = [_svg_chardata(m.group(1)) for m in _SVG_TEXT_RE.finditer(head)]
    lines = [part for part in named if part]
    joined_runs = " ".join(part for part in runs if part).strip()
    if joined_runs:
        lines.append(joined_runs)
    caption = "\n".join(lines).strip()
    return caption[:max_chars]
