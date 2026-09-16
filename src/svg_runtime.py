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

**And deliberately still no XML parser** (`B160`). The row that closed asked for
one — parse, drop the dangerous nodes, re-serialise — and the answer here is no,
for a reason this module already states two paragraphs down about captions:
``xml.etree`` on untrusted input is a parser that expands entities, and
``defusedxml`` is not a dependency of this project. A sanitiser that is wrong is
worse than a gate that refuses, because a gate that refuses fails closed and a
rewriter that misses one node fails open. So `B160` bought what a gate *can*
buy: the refusal names its reason, the reason is drawn where the person can read
it, and the one shape that was refused for its element name rather than for
anything it does — a raster embedded as a `data:` URI — is allowed through the
gate unchanged. The reference check became an **allowlist** in the same pass,
which is the part that makes the widening defensible: a value is refused unless
it is a same-document `#fragment` or an accepted `data:image`, where before it
was accepted unless it *started with* one of four bad schemes.
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

# The elements that make an SVG a program rather than a picture, listed once so
# the two regexes below cannot drift apart (`Law 13`). `<image>` is on its own
# line because `B160` separated the two questions it used to answer at once: an
# `<image>` pointing at somebody else's server is a beacon, an `<image>` holding
# a `data:image/png` payload is a diagram with a screenshot in it, and refusing
# the element refused both.
_ACTIVE_ELEMENTS = ("script", "foreignObject", "iframe", "object", "embed")
_RASTER_ELEMENTS = ("image",)

_EVENT_HANDLER_PATTERN = br"\bon[a-z0-9_-]+\s*="


def _element_pattern(names) -> bytes:
    return br"<\s*(?:" + b"|".join(n.encode() for n in names) + br")\b"


# Kept under its original name because `routes/emoji_routes.py` aliases it and
# `tests/test_svg_attachment_preview.py` asserts the alias is the same object.
# It is the strict element set — active content *and* `<image>` — and it is what
# the emoji route still refuses on.
BLOCKED_SVG_RE = re.compile(
    _element_pattern(_ACTIVE_ELEMENTS + _RASTER_ELEMENTS) + br"|" + _EVENT_HANDLER_PATTERN,
    re.IGNORECASE,
)
# Active content alone. A preview may carry a raster; it may never carry a
# script, and no mode of this gate ever lets one of these through.
ACTIVE_CONTENT_RE = re.compile(
    _element_pattern(_ACTIVE_ELEMENTS) + br"|" + _EVENT_HANDLER_PATTERN,
    re.IGNORECASE,
)
RASTER_ELEMENT_RE = re.compile(_element_pattern(_RASTER_ELEMENTS), re.IGNORECASE)

# An SVG that reaches out is a beacon: it tells a third party that this person
# opened this file, from this address, at this moment (`Law 16` — nothing routes
# to an external service unless someone linked it). Browsers already refuse this
# for an SVG drawn inside an `<img>`; the check is here because "the browser
# would have stopped it" is not a control we own.
#
# `B160` replaced this **blacklist of schemes** with the allowlist of reference
# *values* below, which refuses a strict superset: `ftp:`, an unquoted value, an
# `href` reached through a renamed xlink prefix and a `javascript:` smuggled as
# `&#106;avascript:` all matched nothing here and are all refused now. The name
# stays because it is imported elsewhere and because it is the property the new
# rule has to keep — `tests/test_svg_preview_explains_refusals.py` drives every
# string this pattern matches back through the allowlist and requires a refusal.
EXTERNAL_REF_RE = re.compile(
    br"\b(?:href|xlink:href)\s*=\s*['\"](?:https?:|//|data:|javascript:)",
    re.IGNORECASE,
)

# Every attribute in the file that can name a resource, with or without a
# namespace prefix, quoted or not. Deliberately wider than SVG's own grammar:
# `src=` is not an SVG attribute and `data-href=` is not a reference, and
# matching them costs nothing but a refusal on a file that has no business
# carrying either.
_URL_ATTR_RE = re.compile(
    br"""(?:[a-z_][a-z0-9_.-]*:)?(?:href|src)\s*=\s*"""
    br"""(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""",
    re.IGNORECASE,
)
# CSS reaches out too, and nothing checked it before `B160`: a `<style>` block
# carrying `@import url(https://…)` passed the old scheme blacklist untouched
# because it is not an attribute. `url(#gradient)` — the common, legitimate case
# by a wide margin — goes through the same allowlist and is fine.
_CSS_URL_RE = re.compile(
    r"""url\s*\(\s*(?:"([^"]*)"|'([^']*)'|([^)'"]*))\s*\)""", re.IGNORECASE
)
_CSS_IMPORT_RE = re.compile(r"@import", re.IGNORECASE)
# An entity declaration is either a way to smuggle a string past a byte scan
# (`<!ENTITY x "javascript:…">` then `href="&x;"`) or a way to make a parser
# expand 2^n copies of it. Neither belongs in a drawing. A plain
# `<!DOCTYPE svg PUBLIC …>` with no internal subset is left alone — Inkscape
# emitted one for years — and what that still costs is `B302`.
_ENTITY_DECL_RE = re.compile(br"<!\s*ENTITY\b", re.IGNORECASE)

# The one reference shape a preview may carry besides a same-document fragment.
# Explicitly not `image/svg+xml`: a nested SVG is markup again, and this gate
# would have to run on the payload to say anything about it. Explicitly base64
# only, because a percent-encoded payload can spell `<` and this pattern is what
# lets the scans below treat the payload as opaque.
_DATA_IMAGE_RE = re.compile(
    r"data:image/(?:png|jpe?g|gif|webp|bmp|apng|x-icon|vnd\.microsoft\.icon)"
    r"(?:;[a-z0-9_.+-]+=[a-z0-9_.+-]*)*;base64,[a-z0-9+/=]+\Z",
    re.IGNORECASE,
)
# Whitespace inside an attribute value is not part of the URL — a base64 payload
# is routinely line-wrapped — and a C0 control inside one is an attempt to break
# a scanner rather than a character a browser will honour.
_REF_NOISE_RE = re.compile(r"[\s\x00-\x20\x7f]+")

# ── the refusal vocabulary (`B160`) ─────────────────────────────────────────
#
# A fixed set of slugs, and a sentence for each. Nothing from the file ever
# reaches the placeholder: the person is told which rule fired, not what their
# bytes said, so the explanation cannot itself become a way to draw attacker
# text inside the product.
SVG_REFUSAL_EMPTY = "empty"
SVG_REFUSAL_TOO_LARGE = "too-large"
SVG_REFUSAL_NOT_SVG = "not-svg"
SVG_REFUSAL_ACTIVE_CONTENT = "active-content"
SVG_REFUSAL_EXTERNAL_REF = "external-reference"
SVG_REFUSAL_ENTITY = "entity-declaration"
SVG_REFUSAL_EMBEDDED_IMAGE = "embedded-image"

SVG_REFUSAL_TEXT = {
    SVG_REFUSAL_EMPTY: "The file is empty.",
    SVG_REFUSAL_TOO_LARGE: "It is too large to check.",
    SVG_REFUSAL_NOT_SVG: "It is not an SVG drawing.",
    SVG_REFUSAL_ACTIVE_CONTENT: "It contains a script.",
    SVG_REFUSAL_EXTERNAL_REF: "It loads from another site.",
    SVG_REFUSAL_ENTITY: "It declares XML entities.",
    SVG_REFUSAL_EMBEDDED_IMAGE: "It embeds another image.",
}
_SVG_REFUSAL_FALLBACK = "It did not pass the safety check."

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
# Names the refusal on the response itself. An `<img>` cannot read a header, so
# this is not how the person is told — `refused_preview_svg` is — but it is how
# anything that `fetch`es the preview, and every test here, reads the verdict
# without re-deriving it.
SVG_REFUSAL_HEADER = "X-Preview-Refused"

# Shown instead of an SVG that fails the check: a valid, empty, 1x1 image. The
# preview slot collapses to nothing rather than sitting on a spinner, and the
# refused bytes are never sent. Still the answer for the emoji route, where a
# missing glyph is not a refusal and there is nothing to explain.
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


def _normalise_ref(text: str) -> str:
    r"""What a browser will actually resolve, from the text of one reference.

    Whitespace and C0 controls come out: ``href=" java\tscript:…"`` is a
    `javascript:` URL to a browser and is not one to a scanner reading bytes,
    and a `data:` payload is routinely line-wrapped by the tools that write it,
    so a base64 run split over forty lines has to normalise back to one value
    or the legitimate half of `B160` does not work.

    Entity decoding is **not** done here — it is done by each caller that has a
    reason to, because the two callers have different reasons. See
    ``_scan_references``.
    """
    return _REF_NOISE_RE.sub("", text)


def _reference_verdict(ref: str, allow_data_images: bool) -> str:
    """``"local"``, ``"data-image"`` or a refusal slug, for one reference.

    An allowlist, which is the whole point. The rule it replaces asked whether a
    value *started with* one of four bad schemes, so every scheme nobody thought
    of — and every value that reached its scheme by a route other than the
    literal first characters — was accepted by default. Here a reference is
    refused unless it is one of exactly two things.
    """
    ref = _normalise_ref(ref)
    if not ref:
        return "local"
    if ref.startswith("#"):
        return "local"
    if _DATA_IMAGE_RE.match(ref):
        # Not ``external`` when the caller simply did not ask for rasters: the
        # payload travels inside the file and reaches nobody. Saying so keeps
        # the strict mode's reason true, which is the only thing a refusal slug
        # is for.
        return "data-image" if allow_data_images else SVG_REFUSAL_EMBEDDED_IMAGE
    return SVG_REFUSAL_EXTERNAL_REF


def _scan_references(content: bytes, allow_data_images: bool):
    r"""``(scrubbed, refusal_or_None)`` — every reference in the file, checked.

    *scrubbed* is *content* with the payload of each accepted ``data:image``
    overwritten by an equal run of ``D``. That is not sanitisation and is never
    served: it exists so the element and CSS scans below read the *markup*
    rather than a megabyte of base64 that happens to contain the letters
    ``+onload=``. It is sound because a payload only reaches this point after
    matching ``_DATA_IMAGE_RE`` **to the end of the value** — the `\Z` in that
    pattern is load-bearing, not decoration — and that alphabet cannot spell
    `<`, a quote or a parenthesis, so blanking the span can hide nothing. Drop
    the anchor and an unquoted ``href=data:image/png;base64,AA<script>`` blanks
    its own opening tag.

    **Attribute values are entity-decoded and the CSS text is too, and the
    element scan is deliberately not.** An XML parser resolves `&#106;` inside
    an attribute value and inside the character data of a `<style>`, so
    `&#106;avascript:` and `&#64;import` are what a browser will see; it does
    *not* resolve `&#60;script&#62;` into a tag, so unescaping before the
    element scan would refuse files over text that is only ever text.
    """
    scrubbed = bytearray(content)
    skip_until = 0
    for match in _URL_ATTR_RE.finditer(content):
        if match.start() < skip_until:
            continue
        group = next(i for i in (1, 2, 3) if match.group(i) is not None)
        raw = match.group(group).decode("utf-8", errors="replace")
        verdict = _reference_verdict(html.unescape(raw), allow_data_images)
        if verdict == "local":
            continue
        if verdict == "data-image":
            start, end = match.span(group)
            scrubbed[start:end] = b"D" * (end - start)
            skip_until = end
            continue
        return bytes(scrubbed), verdict
    body = bytes(scrubbed)
    css = html.unescape(body.decode("utf-8", errors="replace"))
    if _CSS_IMPORT_RE.search(css):
        # `@import` in either spelling — `@import url(…)` and the bare
        # `@import "…"` that carries no `url(` for the loop below to find.
        return body, SVG_REFUSAL_EXTERNAL_REF
    for match in _CSS_URL_RE.finditer(css):
        group = next(i for i in (1, 2, 3) if match.group(i) is not None)
        if _reference_verdict(match.group(group), allow_data_images) in ("local", "data-image"):
            continue
        return body, SVG_REFUSAL_EXTERNAL_REF
    return body, None


def svg_refusal_reason(content: bytes, max_bytes: int = MAX_SVG_BYTES,
                       *, allow_data_images: bool = False) -> str | None:
    """Why these bytes may not be rendered, or ``None`` when they may.

    `B160`. The gate used to answer yes/no, so the preview route had nothing to
    say and served a blank pixel: a person whose diagram was refused got no
    picture and no reason, which is a worse answer than the raw render they had
    before `B103` for the (majority) case where the file is harmless. One
    function still decides — ``is_safe_svg`` is this function — and the reason
    is a slug from a fixed vocabulary that never quotes the file.

    *allow_data_images* is the widening, and it is opt-in so that the caller
    that has no use for it does not get it. The upload preview passes it: an
    Inkscape or Figma export with one embedded bitmap carries
    ``<image href="data:image/png;base64,…">`` and was refused for the element
    alone. The emoji route does not: it serves 4,147 vendored monochrome glyphs,
    not one of which contains `href`, `<image`, `url(` or an event handler
    (measured), so there is nothing for it to gain and a narrower gate on
    known-good bytes is free.

    What is refused in **both** modes, and what the tests that matter drive:
    `<script>`, `<foreignObject>`, `<iframe>`, `<object>`, `<embed>`, any `on*=`
    handler, any reference that is not a same-document `#fragment` or an
    accepted `data:image`, `@import`, and any entity declaration.
    """
    if not isinstance(content, bytes) or not content:
        return SVG_REFUSAL_EMPTY
    if len(content) > max_bytes:
        return SVG_REFUSAL_TOO_LARGE
    if b"<svg" not in content[:256].lower():
        return SVG_REFUSAL_NOT_SVG
    if _ENTITY_DECL_RE.search(content):
        return SVG_REFUSAL_ENTITY
    scrubbed, ref_refusal = _scan_references(content, allow_data_images)
    if ACTIVE_CONTENT_RE.search(scrubbed):
        return SVG_REFUSAL_ACTIVE_CONTENT
    if ref_refusal is not None:
        return ref_refusal
    if not allow_data_images and RASTER_ELEMENT_RE.search(scrubbed):
        return SVG_REFUSAL_EMBEDDED_IMAGE
    return None


def is_safe_svg(content: bytes, max_bytes: int = MAX_SVG_BYTES,
                *, allow_data_images: bool = False) -> bool:
    """True when these bytes can be rendered without running anything.

    Kept as the name every caller already spells, and now a one-line reading of
    ``svg_refusal_reason`` so there is one rule and not two that agree today.
    Still conservative: it refuses a file rather than rewriting it, so a diagram
    whose boxes are `https://` hyperlinks is refused whole. That remains a
    deliberate trade — the upload itself is untouched and still downloads — and
    what is left of it is written down as `B300` rather than left as a surprise.
    """
    return svg_refusal_reason(content, max_bytes,
                              allow_data_images=allow_data_images) is None


def refused_preview_svg(reason: str) -> bytes:
    """A picture that says why there is no picture.

    The other half of `B160`. `B103` answered a refusal with a 1x1 empty SVG,
    which an `<img>` sized to 150x150 of nothing: the person saw an empty box
    and was told nothing, and the most common cause was a diagram that was never
    dangerous. This is the same slot, drawn.

    Self-contained on purpose: its own background (so it reads on all sixteen
    themes without knowing about any of them), a generic `sans-serif` family (so
    it fetches no font, `Law 16`), and every string from ``SVG_REFUSAL_TEXT``
    escaped on the way in even though none of them comes from the file. It is
    itself put through ``is_safe_svg`` by
    ``tests/test_svg_preview_explains_refusals.py`` — a refusal placeholder that
    could not pass the gate it explains would be the joke this module cannot
    afford.
    """
    message = html.escape(SVG_REFUSAL_TEXT.get(reason, _SVG_REFUSAL_FALLBACK))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" '
        'viewBox="0 0 320 180" role="img">'
        f"<title>Preview blocked. {message}</title>"
        '<rect x="1" y="1" width="318" height="178" rx="10" '
        'fill="#33363f" stroke="#7b818f" stroke-width="2"/>'
        '<g fill="none" stroke="#e7b34a" stroke-width="2.5" '
        'stroke-linecap="round" stroke-linejoin="round" '
        'transform="translate(140 34)">'
        '<path d="M20 4 L38 34 H2 Z"/><path d="M20 15 v9"/><path d="M20 29 v.5"/>'
        "</g>"
        '<text x="160" y="106" text-anchor="middle" fill="#f2f3f5" '
        'font-family="sans-serif" font-size="17" font-weight="600">'
        "Preview blocked</text>"
        '<text x="160" y="130" text-anchor="middle" fill="#cfd3da" '
        f'font-family="sans-serif" font-size="13">{message}</text>'
        '<text x="160" y="154" text-anchor="middle" fill="#9aa1ad" '
        'font-family="sans-serif" font-size="12">'
        "The file itself is unchanged.</text>"
        "</svg>"
    ).encode("utf-8")


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
