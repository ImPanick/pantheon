# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B160` — the refused SVG preview says why, and refuses strictly more than before.

`B103` put one gate in front of the preview and served a blank 1x1 for anything
that failed it. Measured on the tree before this row, by driving
`GET /api/upload/{id}?thumb=1` over real files on disk:

* An Inkscape/Figma-shaped export — one embedded `data:image/png` raster, a
  gradient referenced as `url(#g)`, a box wrapped in `<a href="#detail">` and a
  `<use href="#g">` — was **refused twice over**: by `<image>` being on the
  blocked-element list, and by `xlink:href="data:` being on the blocked-scheme
  list. Neither refusal was about anything the file does.
* The person saw a 1x1 SVG, which an `<img>` sized to a 150x150 patch of
  nothing, with **no indication that a decision had been made**. A diagram with
  a screenshot in it and a file carrying `<script>` produced byte-identical
  answers.

So this row bought two things and this file pins both, plus the thing it must
not have cost.

**What is now allowed**: a reference whose value is a same-document `#fragment`
or a `data:image/<raster>;base64,…` payload, in the *preview* only.

**What is now refused that was not**: `ftp:` and every other scheme nobody
enumerated, an unquoted `href=https://…`, an `href` reached through a renamed
xlink prefix, a `javascript:` spelled `&#106;avascript:`, `@import` and
`url(https://…)` anywhere in CSS, and any `<!ENTITY` declaration. The old rule
was a blacklist of four schemes on quoted attribute values; the new one is an
allowlist of two shapes on every reference in the file, so the set it refuses is
a strict superset — `test_the_allowlist_refuses_everything_the_old_pattern_caught`
drives that as an identity rather than asserting it in prose.

**What it did not cost**: all 4,147 vendored emoji glyphs still pass the gate at
the emoji route's own bound, and that route still refuses everything it refused
before, including the embedded raster the preview now accepts (`B160`'s
`Verify:` — it serves known-good line art and has no use for the widening).
"""
import asyncio
import base64
import os
from types import SimpleNamespace

import pytest

import src.svg_runtime as svg_runtime

# A one-pixel PNG, so the embedded raster in the fixture below is a real image
# and not a placeholder string that happens to match the pattern.
_PNG_B64 = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100ffff03000006"
    "000557bfabd40000000049454e44ae426082"
)).decode()

# The row's `Verify:` fixture, and deliberately not a minimal one: an embedded
# raster AND a hyperlink AND a gradient reference AND a `<use>`, because each of
# those is a separate way the old rule could refuse the same drawing.
DIAGRAM_SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" width="200" height="100">'
    '<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
    '<rect width="200" height="100" style="fill:url(#g)"/>'
    '<a href="#detail"><rect x="10" y="10" width="50" height="20"/></a>'
    f'<image x="70" y="10" width="40" height="40" xlink:href="data:image/png;base64,{_PNG_B64}"/>'
    '<use href="#g"/>'
    '<text x="12" y="24">box</text></svg>'
).encode()

# Every shape that must still be refused. The friendly cases above are the point
# of the row; these are the reason the row could have been a mistake.
HOSTILE = {
    "script": b'<svg xmlns="http://www.w3.org/2000/svg"><script>fetch("/api/settings")</script></svg>',
    "event-handler": b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect/></svg>',
    "foreign-object": b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><b>x</b></foreignObject></svg>',
    "javascript-href": b'<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)">x</a></svg>',
    "entity-smuggled-javascript":
        b'<svg xmlns="http://www.w3.org/2000/svg"><a href="&#106;avascript:alert(1)">x</a></svg>',
    "whitespace-broken-javascript":
        b'<svg xmlns="http://www.w3.org/2000/svg"><a href="java\tscript:alert(1)">x</a></svg>',
    "external-image":
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://tracker.example/p.png"/></svg>',
    "external-use":
        b'<svg xmlns="http://www.w3.org/2000/svg"><use xlink:href="https://tracker.example/s.svg#i"/></svg>',
    "protocol-relative":
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="//tracker.example/p.png"/></svg>',
    "unenumerated-scheme":
        b'<svg xmlns="http://www.w3.org/2000/svg"><use href="ftp://tracker.example/s.svg"/></svg>',
    "unquoted-href":
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href=https://tracker.example/p.png /></svg>',
    "renamed-xlink-prefix":
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xl="http://www.w3.org/1999/xlink">'
        b'<use xl:href="https://tracker.example/s.svg#i"/></svg>',
    "css-import":
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://tracker.example/x.css);</style></svg>',
    # `@import "…";` carries no `url(`, so only the `@import` rule itself can
    # refuse it — and the entity-encoded spelling is what an XML parser turns
    # back into `@import` after a byte scan has already looked at it.
    "css-import-string":
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://tracker.example/x.css";</style></svg>',
    "css-import-entity-encoded":
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>&#64;import "https://tracker.example/x.css";</style></svg>',
    # The unquoted value runs up to the first `>`, so an unanchored data: match
    # would blank the file's own `<script` opening tag along with the payload.
    "payload-swallowing-its-own-tag":
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b'<image href=data:image/png;base64,AAAA<script>alert(1)</script></svg>',
    "css-url":
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://tracker.example/x.png)"/></svg>',
    "relative-reference":
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="../../etc/passwd"/></svg>',
    "nested-svg-payload":
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/svg+xml;base64,AAAA"/></svg>',
    "html-payload":
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:text/html;base64,PHNjcmlwdD4="/></svg>',
    "entity-declaration":
        b'<!DOCTYPE svg [<!ENTITY lol "lololol">]><svg xmlns="http://www.w3.org/2000/svg"><text>&lol;</text></svg>',
    "markup-after-a-payload":
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AAAA">'
        b'<script>alert(1)</script></svg>',
}


class _Request:
    def __init__(self):
        self.state = SimpleNamespace(current_user=None)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))
        self.client = SimpleNamespace(host="127.0.0.1")


def _serve(tmp_path, monkeypatch, body: bytes, *, thumb: int = 1, name="diagram.svg"):
    """Drive the real `GET /api/upload/{file_id}` over one real file on disk."""
    import fastapi.dependencies.utils as dependency_utils
    import routes.upload_routes as upload_routes
    from src.upload_handler import UploadHandler

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed", lambda: None)
    upload_dir = tmp_path / "uploads" / "2026" / "09" / "16"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = "e" * 32 + os.path.splitext(name)[1]
    path = upload_dir / file_id
    path.write_bytes(body)

    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    index = {"owner:hash": {
        "id": file_id, "path": str(path), "mime": "image/svg+xml", "size": len(body),
        "name": name, "original_name": name, "owner": "owner",
    }}
    monkeypatch.setattr(handler, "_load_upload_index", lambda: index)
    router, _cleanup = upload_routes.setup_upload_routes(handler)
    endpoint = {r.endpoint.__name__: r.endpoint for r in router.routes}["download_file"]
    return asyncio.run(endpoint(_Request(), file_id, thumb=thumb)), path


# --------------------------------------------------------------------------
# The widening — what the row exists for
# --------------------------------------------------------------------------

def test_a_diagram_with_an_embedded_raster_and_a_hyperlink_previews(tmp_path, monkeypatch):
    """`B160`'s `Verify:`, first clause, driven over the real route.

    Refused on the pre-change tree by two independent rules at once. The bytes
    served are the file's own, unchanged — this row widened a gate, it did not
    add a rewriter, and a preview that differed from the file would be a claim
    this module is not making.
    """
    response, _ = _serve(tmp_path, monkeypatch, DIAGRAM_SVG)
    assert response.body == DIAGRAM_SVG
    assert svg_runtime.SVG_REFUSAL_HEADER not in response.headers
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["content-security-policy"] == "sandbox"
    assert headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize("fragment", [
    b'<a href="#detail"><rect/></a>',                       # an internal hyperlink
    b'<use href="#icon"/>',                                 # a symbol reference
    b'<use xlink:href="#icon"/>',                           # the same, namespaced
    b'<rect style="fill:url(#grad)"/>',                      # a gradient, by far the common case
    b'<rect fill="url(\'#grad\')"/>',                        # quoted inside url()
    b'<a href="">x</a>',                                     # an empty reference
    b'<a href="&#35;detail">x</a>',                          # the same fragment, entity-encoded
    b'<image href="data:image/png;base64,\n   iVBORw0K\n   Ggo="/>',   # a line-wrapped payload
])
def test_same_document_references_are_not_external(fragment):
    """The allowlist has to let the ordinary drawing through or it is a denial.

    Each of these resolves inside the file itself and reaches nobody. `url(#…)`
    is the one that matters most: gradients, filters, clip paths and markers all
    spell their reference that way, and nothing checked CSS at all before this
    row — which means nothing had to be careful about it either.
    """
    content = b'<svg xmlns="http://www.w3.org/2000/svg">' + fragment + b"</svg>"
    assert svg_runtime.svg_refusal_reason(
        content, svg_runtime.MAX_PREVIEW_SVG_BYTES, allow_data_images=True) is None


# --------------------------------------------------------------------------
# The hostile half — a widened gate that stopped refusing is not a fix
# --------------------------------------------------------------------------

@pytest.mark.parametrize("label", sorted(HOSTILE))
def test_hostile_svg_is_still_refused_by_the_gate(label):
    """Every shape above, against the gate in the mode the preview uses.

    `allow_data_images=True` is the widened mode. If any of these returns
    ``None`` the row traded a usability fix for a stored-XSS or a beacon, which
    is the trade this file exists to make impossible to land quietly.
    """
    assert svg_runtime.svg_refusal_reason(
        HOSTILE[label], svg_runtime.MAX_PREVIEW_SVG_BYTES,
        allow_data_images=True) is not None


@pytest.mark.parametrize("label", sorted(HOSTILE))
def test_hostile_svg_never_reaches_the_browser(tmp_path, monkeypatch, label):
    """The same list again, through the route, looking at the bytes sent.

    `Law 16` is the clause with teeth here: `tracker.example` appearing anywhere
    in a preview response means the browser was handed a beacon, and eight of
    these files are exactly that in eight different spellings.
    """
    body = HOSTILE[label]
    response, _ = _serve(tmp_path, monkeypatch, body)
    served = response.body
    assert served != body
    assert b"tracker.example" not in served
    assert b"<script" not in served
    assert b"javascript:" not in served
    assert b"@import" not in served
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["content-security-policy"] == "sandbox"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    assert headers["content-disposition"].startswith("attachment")
    assert headers["cache-control"] == "no-store"


@pytest.mark.parametrize("scheme", [b"https://x/y", b"http://x/y", b"//x/y",
                                    b"javascript:alert(1)", b"data:text/html,x"])
def test_the_allowlist_refuses_everything_the_old_pattern_caught(scheme):
    """`Law 1`, stated as an identity rather than as a promise.

    ``EXTERNAL_REF_RE`` is the blacklist this row replaced. It is still exported,
    and it is still the *specification*: every value it matches must still be
    refused, or the allowlist that replaced it gave something away. The reverse
    does not hold, and that asymmetry is the improvement — `ftp://` matches
    nothing in the old pattern and is refused by the new rule.
    """
    content = (b'<svg xmlns="http://www.w3.org/2000/svg"><image href="'
               + scheme + b'"/></svg>')
    assert svg_runtime.EXTERNAL_REF_RE.search(content)
    assert svg_runtime.svg_refusal_reason(
        content, svg_runtime.MAX_PREVIEW_SVG_BYTES, allow_data_images=True) is not None


def test_a_data_payload_cannot_hide_markup_from_the_scan():
    """The one mechanism in this row that could fail open, driven directly.

    An accepted `data:image` payload is blanked before the element and CSS scans
    run, so a megabyte of base64 that happens to contain `+onload=` does not
    refuse a legitimate file. That is only sound because the payload had to match
    to its end against an alphabet with no `<`, no quote and no parenthesis. Both
    halves are asserted: the noisy-but-harmless payload passes, and markup that
    merely *follows* a payload is still seen.
    """
    noisy = (b'<svg xmlns="http://www.w3.org/2000/svg">'
             b'<image href="data:image/png;base64,AAAA+onload=BBBB"/></svg>')
    assert svg_runtime.svg_refusal_reason(
        noisy, svg_runtime.MAX_PREVIEW_SVG_BYTES, allow_data_images=True) is None

    escaped = (b'<svg xmlns="http://www.w3.org/2000/svg">'
               b'<image href="data:image/png;base64,AAAA"><script>alert(1)</script></svg>')
    assert svg_runtime.svg_refusal_reason(
        escaped, svg_runtime.MAX_PREVIEW_SVG_BYTES, allow_data_images=True) == \
        svg_runtime.SVG_REFUSAL_ACTIVE_CONTENT


# --------------------------------------------------------------------------
# The explanation — the other half of the row
# --------------------------------------------------------------------------

def test_a_refusal_is_drawn_where_the_person_can_read_it(tmp_path, monkeypatch):
    """`B160`'s second complaint: the refusals were invisible.

    Before this row every refusal was the same 1x1. Now the placeholder carries
    the heading, the sentence for this particular rule, and the reassurance the
    upload banner already makes in writing — that refusing the *preview* did not
    refuse the *file*.
    """
    response, _ = _serve(tmp_path, monkeypatch, HOSTILE["script"])
    served = response.body
    assert served != svg_runtime.BLANK_SVG
    assert b"Preview blocked" in served
    assert svg_runtime.SVG_REFUSAL_TEXT[
        svg_runtime.SVG_REFUSAL_ACTIVE_CONTENT].encode() in served
    assert b"The file itself is unchanged." in served
    assert response.headers[svg_runtime.SVG_REFUSAL_HEADER] == \
        svg_runtime.SVG_REFUSAL_ACTIVE_CONTENT


@pytest.mark.parametrize("reason", sorted(svg_runtime.SVG_REFUSAL_TEXT))
def test_every_reason_has_a_sentence_and_draws_a_valid_image(reason):
    """A vocabulary with a hole in it is a placeholder that says nothing.

    And the placeholder is put through the gate it explains: it is an SVG served
    from the same route with the same headers, so a refusal picture that could
    not itself pass ``is_safe_svg`` would be the one bug this module cannot
    afford to ship.
    """
    import xml.etree.ElementTree as ET   # our own bytes, not the uploader's

    drawn = svg_runtime.refused_preview_svg(reason)
    assert svg_runtime.SVG_REFUSAL_TEXT[reason].encode() in drawn
    assert drawn.startswith(b"<svg") and drawn.endswith(b"</svg>")
    assert svg_runtime.is_safe_svg(drawn)
    assert svg_runtime.is_safe_svg(drawn, allow_data_images=True)
    # A browser draws nothing at all for malformed XML, so a placeholder that
    # does not parse is the same blank box this row set out to remove.
    root = ET.fromstring(drawn.decode("utf-8"))
    assert root.tag.endswith("svg")
    assert root.get("width") and root.get("height") and root.get("viewBox")


def test_the_placeholder_never_quotes_the_file(tmp_path, monkeypatch):
    """The explanation must not become the injection.

    The reason is a slug from a fixed set and the sentence is ours, so nothing
    an uploader wrote can reach the bytes drawn back at them — including the
    filename, which is the one attacker-chosen string the route is holding at
    the moment it builds this response.
    """
    marker = b"MARKER-FROM-THE-UPLOADED-FILE"
    body = (b'<svg xmlns="http://www.w3.org/2000/svg"><script>'
            + marker + b'</script><desc>' + marker + b'</desc></svg>')
    response, _ = _serve(tmp_path, monkeypatch, body,
                         name="<img src=x onerror=alert(1)>.svg")
    assert marker not in response.body
    assert b"onerror" not in response.body
    assert b"Preview blocked" in response.body


def test_an_unknown_reason_still_draws_something(tmp_path, monkeypatch):
    """A slug added to the gate without a sentence must not produce an empty card."""
    drawn = svg_runtime.refused_preview_svg("a-reason-nobody-wrote-a-sentence-for")
    assert b"Preview blocked" in drawn
    assert svg_runtime.is_safe_svg(drawn)


# --------------------------------------------------------------------------
# What the widening cost — measured, not assumed
# --------------------------------------------------------------------------

def test_escaped_markup_in_a_label_is_text_and_not_a_script():
    """The other direction of the entity question, and why it is per-caller.

    An XML parser resolves `&#106;` inside an *attribute value* and inside the
    character data of a `<style>`, so both are decoded before they are judged. It
    does **not** turn `&lt;script&gt;` into a tag — that is a label on a diagram
    that happens to be about scripts — so the element scan reads the raw bytes.
    Unescaping everything before every scan would have been the obvious
    simplification and would refuse this file.
    """
    content = (b'<svg xmlns="http://www.w3.org/2000/svg">'
               b'<text>&lt;script&gt;alert(1)&lt;/script&gt;</text></svg>')
    assert svg_runtime.svg_refusal_reason(
        content, svg_runtime.MAX_PREVIEW_SVG_BYTES, allow_data_images=True) is None


def test_the_emoji_route_still_refuses_the_image_element_itself():
    """`FORBIDDEN.md` Part 2: *the emoji SVG guards* do not lift.

    `<image>` is on ``BLOCKED_SVG_RE`` and the emoji route is the caller that
    still refuses on the element name, not merely on where the element points.
    An `<image>` with no reference at all is the case that separates the two
    rules, and it is the one this asserts.
    """
    from routes import emoji_routes

    bare = b'<svg xmlns="http://www.w3.org/2000/svg"><image/></svg>'
    assert not emoji_routes._is_safe_svg(bare)
    assert svg_runtime.svg_refusal_reason(bare) == svg_runtime.SVG_REFUSAL_EMBEDDED_IMAGE
    assert b"image" in svg_runtime.BLOCKED_SVG_RE.pattern


def test_the_emoji_route_does_not_get_the_widening():
    """`B160`'s `Verify:`, last clause. The emoji route keeps refusing.

    It serves vendored line art, so an embedded raster there is a file that
    should not be in the library rather than a diagram someone drew. The
    widening is a keyword argument the preview passes and this route does not,
    which is why "both callers share one gate" and "the two callers refuse
    different things" are both true.
    """
    from routes import emoji_routes

    embedded = (b'<svg xmlns="http://www.w3.org/2000/svg">'
                b'<image href="data:image/png;base64,' + _PNG_B64.encode() + b'"/></svg>')
    assert svg_runtime.svg_refusal_reason(
        embedded, svg_runtime.MAX_PREVIEW_SVG_BYTES, allow_data_images=True) is None
    assert not emoji_routes._is_safe_svg(embedded)
    assert svg_runtime.svg_refusal_reason(embedded) == \
        svg_runtime.SVG_REFUSAL_EMBEDDED_IMAGE


def test_every_vendored_glyph_still_passes_the_tightened_gate():
    """`Law 1`, on the only SVG corpus this project owns.

    The reference check became an allowlist and CSS and entity declarations
    became refusals, all of which tighten the emoji route as well. Run over the
    whole vendored set — 4,147 glyphs, assembled exactly as the route assembles
    them — the tightening refuses none of them, and the corpus contains no
    `href`, no `<image`, no `url(` and no event handler at all.
    """
    from routes import emoji_routes

    glyphs = emoji_routes._glyphs()
    assert len(glyphs) > 4000, "vendored emoji library missing; this is not a pass"
    refused = []
    for code, body in glyphs.items():
        content = (emoji_routes._SVG_OPEN + body + emoji_routes._SVG_CLOSE).encode("utf-8")
        if not emoji_routes._is_safe_svg(content):
            refused.append(code)
    assert refused == []
