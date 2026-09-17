# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B300`/`B302` — a link is not a beacon, and a DOCTYPE stopped naming a host.

`B160` left the preview gate **element-blind**: it saw attribute values and not
the elements they hang on, so `<a href="https://…">` and
`<image href="https://…">` were the same string to it and both were refused.
They are not the same thing. Nothing fetches a hyperlink until a click, and
inside an `<img>` — which is how every preview in this product is drawn — there
is no click. An `<image>` is fetched the moment the picture is drawn. That is
`Law 16`'s distinction exactly, and the cost of not being able to make it was
that a diagram whose boxes are hyperlinks — the commonest shape an exported
architecture diagram has — was refused whole.

**What was built, and what was not.** There is still no XML parser here,
nothing is re-serialised and no entity is ever expanded — `B160`'s ruling
stands. What `_hyperlink_spans` is, is a tokenizer whose entire output is a set
of byte spans: *these attribute values sit on an `<a>` start tag*. It **fails
closed**: any construct it cannot account for — an unterminated comment, an
unquoted attribute value, a stray `<` — makes it return nothing, and nothing
means `B160`'s allowlist judges every reference exactly as before. It can add an
exemption to a file it has read end to end; it can never remove a check.

**`B302`.** A DOCTYPE's `PUBLIC`/`SYSTEM` identifier is an address in a file
whose every other address this gate checks to the letter, and *"no browser
fetches an external DTD"* is precisely the argument `B103` rejected for
`xlink:href` beacons. The row forbade closing it with a blanket DOCTYPE
refusal — Inkscape emitted one for a decade — so neither: the declaration stays
and its external identifier does not. The **download** arm is untouched.

`Law 9` and the hostile half: every fixture in
`tests/test_svg_preview_explains_refusals.py` is re-driven here **in the
widened mode**, because a gate that stopped refusing is not a fix. That file's
own tests still run unchanged and still pass, which is the other half of the
same evidence.
"""
import asyncio
import inspect
import os
import time
from types import SimpleNamespace

import pytest

import src.svg_runtime as svg_runtime
from tests.test_svg_preview_explains_refusals import DIAGRAM_SVG, HOSTILE

# `getattr`/`inspect` rather than a bare call, so this file reports nine
# separate failures on the tree as it stood instead of one TypeError. On that
# tree `svg_refusal_reason` took no `allow_hyperlinks` at all.
_WIDENS = "allow_hyperlinks" in inspect.signature(
    svg_runtime.svg_refusal_reason).parameters
PREVIEW = (dict(allow_data_images=True, allow_hyperlinks=True) if _WIDENS
           else dict(allow_data_images=True))
preview_bytes = getattr(svg_runtime, "preview_bytes", lambda content: content)
_hyperlink_spans = getattr(svg_runtime, "_hyperlink_spans", lambda content: set())
MAX_SVG_REFERENCES = getattr(svg_runtime, "MAX_SVG_REFERENCES", 20000)

# The row's `Verify:` fixture: a diagram whose boxes link out.
LINKED_DIAGRAM = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" width="400" height="200">'
    '<a href="https://example.com/services/auth">'
    '<rect x="10" y="10" width="120" height="40" fill="#456"/>'
    '<text x="20" y="35">auth</text></a>'
    '<a xlink:href="http://example.com/services/db">'
    '<rect x="160" y="10" width="120" height="40" fill="#456"/>'
    '<text x="170" y="35">db</text></a>'
    '<line x1="130" y1="30" x2="160" y2="30" stroke="#999"/>'
    '</svg>'
).encode()

PUBLIC_DOCTYPE = (
    b'<?xml version="1.0" standalone="no"?>\n'
    b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
    b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<rect width="10" height="10"/></svg>'
)


class _Request:
    def __init__(self):
        self.state = SimpleNamespace(current_user=None)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))
        self.client = SimpleNamespace(host="127.0.0.1")


def _serve(tmp_path, monkeypatch, body: bytes, *, thumb: int = 1,
           name="diagram.svg"):
    """Drive the real `GET /api/upload/{file_id}` over one real file on disk."""
    import fastapi.dependencies.utils as dependency_utils
    import routes.upload_routes as upload_routes
    from src.upload_handler import UploadHandler

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed",
                        lambda: None)
    upload_dir = tmp_path / "uploads" / "2026" / "09" / "16"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = "e" * 32 + os.path.splitext(name)[1]
    path = upload_dir / file_id
    path.write_bytes(body)

    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    index = {"owner:hash": {
        "id": file_id, "path": str(path), "mime": "image/svg+xml",
        "size": len(body), "name": name, "original_name": name,
        "owner": "owner",
    }}
    monkeypatch.setattr(handler, "_load_upload_index", lambda: index)
    router, _cleanup = upload_routes.setup_upload_routes(handler)
    endpoint = {r.endpoint.__name__: r.endpoint
                for r in router.routes}["download_file"]
    return asyncio.run(endpoint(_Request(), file_id, thumb=thumb)), path


# ── the widening (`B300`) ───────────────────────────────────────────────────


def test_a_diagram_whose_boxes_are_hyperlinks_previews(tmp_path, monkeypatch):
    """`B300`'s `Verify:`, first clause, through the real route.

    On the tree as it stood this answered `external-reference` and the person
    got a drawn *"Preview blocked. It loads from another site."* for a file that
    loads nothing.
    """
    assert svg_runtime.svg_refusal_reason(
        LINKED_DIAGRAM, svg_runtime.MAX_PREVIEW_SVG_BYTES,
        allow_data_images=True) == svg_runtime.SVG_REFUSAL_EXTERNAL_REF
    assert svg_runtime.svg_refusal_reason(
        LINKED_DIAGRAM, svg_runtime.MAX_PREVIEW_SVG_BYTES, **PREVIEW) is None

    response, _ = _serve(tmp_path, monkeypatch, LINKED_DIAGRAM)
    assert svg_runtime.SVG_REFUSAL_HEADER not in response.headers
    # The links are intact in what the browser is handed — the row's
    # *"with the links intact"* clause, which a stripping sanitiser would fail.
    assert b'href="https://example.com/services/auth"' in response.body
    assert b'xlink:href="http://example.com/services/db"' in response.body


def test_the_same_address_on_an_image_still_refuses(tmp_path, monkeypatch):
    """The whole row in one assertion: identical URL, different element.

    This is what the byte scan could not do and is the only reason the widening
    is defensible. An `<image>` is fetched on render; an `<a>` is not.
    """
    beacon = (b'<svg xmlns="http://www.w3.org/2000/svg">'
              b'<image href="https://example.com/services/auth"/></svg>')
    assert svg_runtime.svg_refusal_reason(
        beacon, svg_runtime.MAX_PREVIEW_SVG_BYTES,
        **PREVIEW) == svg_runtime.SVG_REFUSAL_EXTERNAL_REF
    response, _ = _serve(tmp_path, monkeypatch, beacon)
    assert b"example.com" not in response.body


def test_a_beacon_inside_a_hyperlink_is_still_a_beacon():
    """The nesting case, which is where an element-blind rule fails open if you
    write the exemption as "this file has an `<a>` in it"."""
    nested = (b'<svg xmlns="http://www.w3.org/2000/svg">'
              b'<a href="https://example.com/ok">'
              b'<image href="https://tracker.example/p.png"/></a></svg>')
    assert svg_runtime.svg_refusal_reason(
        nested, svg_runtime.MAX_PREVIEW_SVG_BYTES,
        **PREVIEW) == svg_runtime.SVG_REFUSAL_EXTERNAL_REF


@pytest.mark.parametrize("value", [
    b"javascript:alert(1)",
    b"&#106;avascript:alert(1)",
    b"data:text/html;base64,PHNjcmlwdD4=",
    b"//tracker.example/p.png",
    b"ftp://tracker.example/x",
    b"https:notaurl",
    b"../../etc/passwd",
])
def test_a_hyperlink_may_only_be_an_ordinary_web_address(value):
    """The exemption is `http://` and `https://` and nothing else.

    The argument for allowing a hyperlink is that a browser does not fetch it
    until a click. That argument is about a web address; it is not about
    `javascript:`, a `data:` document, a protocol-relative host or a scheme
    nobody enumerated, and none of those may ride in on it.
    """
    content = (b'<svg xmlns="http://www.w3.org/2000/svg"><a href="'
               + value + b'">x</a></svg>')
    assert svg_runtime.svg_refusal_reason(
        content, svg_runtime.MAX_PREVIEW_SVG_BYTES, **PREVIEW) is not None


def test_only_href_on_an_anchor_gets_the_exemption():
    """`src` is not an SVG attribute on an `<a>` and nothing fetches it — but a
    rule that exempted every URL-ish attribute on an anchor would be a rule
    about the element rather than about what the browser does with the value.
    The gate is wider than SVG's own grammar on purpose (`_URL_ATTR_RE` matches
    `src=` and `data-href=`), so the exemption has to be narrower than the gate.
    """
    content = (b'<svg xmlns="http://www.w3.org/2000/svg">'
               b'<a src="https://tracker.example/p.png">x</a></svg>')
    assert svg_runtime.svg_refusal_reason(
        content, svg_runtime.MAX_PREVIEW_SVG_BYTES,
        **PREVIEW) == svg_runtime.SVG_REFUSAL_EXTERNAL_REF


def test_a_prefixed_anchor_gets_no_exemption():
    """`<svg:a>` needs namespace resolution to be called an anchor, and
    resolving namespaces is the parser this module does not have. Strict is the
    only honest answer when the tokenizer cannot see the binding."""
    content = (b'<svg xmlns:svg="http://www.w3.org/2000/svg">'
               b'<svg:a href="https://example.com/x">y</svg:a></svg>')
    assert svg_runtime.svg_refusal_reason(
        content, svg_runtime.MAX_PREVIEW_SVG_BYTES, **PREVIEW) is not None


@pytest.mark.parametrize("label,content", [
    ("unquoted-value",
     b'<svg xmlns="http://www.w3.org/2000/svg"><a href=https://example.com/x>y</a></svg>'),
    # The same two faults with the anchor itself perfectly well formed. This is
    # the shape that separates "the tokenizer read the whole file" from "the
    # tokenizer read as far as the anchor": an exemption handed out on the
    # strength of a partial read is an exemption for a file nobody understood.
    ("unquoted-elsewhere",
     b'<svg xmlns="http://www.w3.org/2000/svg"><rect width=10 height=10/>'
     b'<a href="https://example.com/x">y</a></svg>'),
    ("unparseable-tag-after-the-anchor",
     b'<svg xmlns="http://www.w3.org/2000/svg">'
     b'<a href="https://example.com/x">y</a><rect 123="y"/></svg>'),
    ("unterminated-comment",
     b'<svg xmlns="http://www.w3.org/2000/svg"><!-- <a href="https://example.com/x">'),
    ("stray-less-than",
     b'<svg xmlns="http://www.w3.org/2000/svg"><text>a < b</text>'
     b'<a href="https://example.com/x">y</a></svg>'),
    ("unterminated-tag",
     b'<svg xmlns="http://www.w3.org/2000/svg"><a href="https://example.com/x"'),
])
def test_a_file_the_tokenizer_cannot_read_gets_no_exemption(label, content):
    """The fail-closed property, driven on four ways to confuse a scanner.

    A tokenizer that guesses is worse than no tokenizer, because the guess is
    what a payload is shaped to exploit. Each of these leaves the file judged by
    `B160`'s allowlist, which refuses it.
    """
    assert _hyperlink_spans(content) == set(), label
    assert svg_runtime.svg_refusal_reason(
        content, svg_runtime.MAX_PREVIEW_SVG_BYTES, **PREVIEW) is not None, label


def test_the_widening_is_opt_in_and_the_emoji_route_did_not_get_it():
    """`B160`'s rule for `allow_data_images`, one row on. The emoji route
    serves 4,147 vendored monochrome glyphs and has nothing to gain from a
    hyperlink; a narrower gate on known-good bytes is free."""
    assert svg_runtime.svg_refusal_reason(
        LINKED_DIAGRAM, svg_runtime.MAX_SVG_BYTES) == \
        svg_runtime.SVG_REFUSAL_EXTERNAL_REF
    assert svg_runtime.is_safe_svg(LINKED_DIAGRAM, svg_runtime.MAX_SVG_BYTES) is False
    assert svg_runtime.is_safe_svg(LINKED_DIAGRAM,
                                   svg_runtime.MAX_PREVIEW_SVG_BYTES,
                                   **PREVIEW) is True


# ── the hostile half, re-driven in the widened mode ─────────────────────────


@pytest.mark.parametrize("label", sorted(HOSTILE))
def test_every_hostile_fixture_still_refuses_with_hyperlinks_allowed(label):
    """`B160`'s 22 fixtures, in the mode this row added. Extended, not weakened.

    If any of these returns `None` the row traded a usability fix for a beacon
    or a stored XSS, which is the trade this file exists to make impossible to
    land quietly.
    """
    assert svg_runtime.svg_refusal_reason(
        HOSTILE[label], svg_runtime.MAX_PREVIEW_SVG_BYTES,
        **PREVIEW) is not None


@pytest.mark.parametrize("label", sorted(HOSTILE))
def test_no_hostile_fixture_reaches_the_browser_through_the_widened_route(
        tmp_path, monkeypatch, label):
    """The same list through the real route, looking at the bytes served.

    The route is the caller that takes the widening, so the route is where the
    proof has to be: `tracker.example` in a preview response means the browser
    was handed a beacon.
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
    assert headers["content-disposition"].startswith("attachment")


def test_the_diagram_b160_bought_still_previews():
    """`Law 1`. `B160`'s own fixture — embedded raster, gradient, `<use>`, a
    same-document `<a>` — is unchanged by this row in either mode."""
    assert svg_runtime.svg_refusal_reason(
        DIAGRAM_SVG, svg_runtime.MAX_PREVIEW_SVG_BYTES,
        allow_data_images=True) is None
    assert svg_runtime.svg_refusal_reason(
        DIAGRAM_SVG, svg_runtime.MAX_PREVIEW_SVG_BYTES, **PREVIEW) is None


# ── the size bound (`B300`, second clause) ──────────────────────────────────


def _big_svg(target: int) -> bytes:
    """An export shaped like a real one: long path runs, few references."""
    import random
    random.seed(11)
    out = [b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 900">',
           b'<a href="https://example.com/legend"><rect width="8" height="8"/></a>']
    size = sum(len(p) for p in out)
    while size < target:
        d = " ".join("%s%.2f %.2f" % (random.choice("MLCQ"),
                                      random.random() * 900,
                                      random.random() * 900)
                     for _ in range(60))
        piece = ('<path d="%s" fill="#%06x"/>' % (d, random.randrange(1 << 24))).encode()
        out.append(piece)
        size += len(piece)
    out.append(b"</svg>")
    return b"".join(out)


def test_a_five_megabyte_export_previews(tmp_path, monkeypatch):
    """`B300`'s `Verify:`, second clause. The 2 MiB bound was a byte bound
    standing in for a work bound, and it told a person *"It is too large to
    check"* about their own drawing."""
    body = _big_svg(5 * 1024 * 1024)
    assert len(body) > 5 * 1024 * 1024
    assert svg_runtime.MAX_PREVIEW_SVG_BYTES >= len(body)
    started = time.monotonic()
    assert svg_runtime.svg_refusal_reason(
        body, svg_runtime.MAX_PREVIEW_SVG_BYTES, **PREVIEW) is None
    # Not a benchmark — a ceiling, so a future rewrite that makes the gate
    # quadratic in the file's size is caught here rather than in production.
    assert time.monotonic() - started < 10.0

    response, _ = _serve(tmp_path, monkeypatch, body)
    assert svg_runtime.SVG_REFUSAL_HEADER not in response.headers
    assert len(response.body) == len(body)


def test_the_work_bound_is_about_work_and_refuses_rather_than_stopping():
    """A file dense in references is what a byte bound was standing in for.

    Past `MAX_SVG_REFERENCES` the gate cannot claim to have checked the file, so
    it refuses — a scan that merely *stopped* would be a hole with a number on
    it. The tokenizer's own bound is the opposite and deliberately so: it hands
    out exemptions, so running out of budget means no exemption.
    """
    dense = (b'<svg xmlns="http://www.w3.org/2000/svg">'
             + b'<use href="#g"/>' * (MAX_SVG_REFERENCES + 5)
             + b"</svg>")
    assert svg_runtime.svg_refusal_reason(
        dense, svg_runtime.MAX_PREVIEW_SVG_BYTES,
        **PREVIEW) == svg_runtime.SVG_REFUSAL_TOO_LARGE


def test_a_file_that_previews_today_takes_the_same_path(monkeypatch):
    """The tokenizer runs only for a file the unwidened scan already refused.

    That is what makes the widening affordable, and it is asserted rather than
    described: a clean file must not pay for `B300` at all.
    """
    clean = _big_svg(256 * 1024).replace(
        b'<a href="https://example.com/legend"><rect width="8" height="8"/></a>',
        b'<rect width="8" height="8"/>')
    calls = []
    real = _hyperlink_spans
    monkeypatch.setattr(svg_runtime, "_hyperlink_spans",
                        lambda c: (calls.append(len(c)), real(c))[1])
    assert svg_runtime.svg_refusal_reason(
        clean, svg_runtime.MAX_PREVIEW_SVG_BYTES, **PREVIEW) is None
    assert calls == [], "the tokenizer ran on a file that already previewed"


# ── the DOCTYPE (`B302`) ────────────────────────────────────────────────────


def test_a_public_doctype_previews_with_no_external_identifier(tmp_path,
                                                               monkeypatch):
    """`B302`'s `Verify:`, first branch, through the real route.

    The row forbade closing this with a blanket DOCTYPE refusal, so the
    declaration is still there and still says `svg`. What left is the one
    address in the file the allowlist never saw.
    """
    response, path = _serve(tmp_path, monkeypatch, PUBLIC_DOCTYPE)
    served = response.body
    assert svg_runtime.SVG_REFUSAL_HEADER not in response.headers
    assert b"<!DOCTYPE svg>" in served
    assert b"w3.org/Graphics/SVG" not in served
    assert b"PUBLIC" not in served
    assert b"<rect" in served
    # `Law 1`: the file on disk is untouched, and the DOWNLOAD arm serves it
    # whole — which is the promise `build_user_content`'s banner already makes.
    assert path.read_bytes() == PUBLIC_DOCTYPE
    download, _ = _serve(tmp_path, monkeypatch, PUBLIC_DOCTYPE, thumb=0)
    assert download.path == str(path)


@pytest.mark.parametrize("declaration,expect_removed", [
    (b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://w3.org/x.dtd">', True),
    (b'<!DOCTYPE svg SYSTEM "http://evil.example/x.dtd">', True),
    (b'<!DOCTYPE svg SYSTEM \'local.dtd\'>', True),
    (b'<!DOCTYPE svg>', False),
])
def test_every_doctype_shape_keeps_the_declaration_and_drops_the_address(
        declaration, expect_removed):
    content = declaration + b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    out = preview_bytes(content)
    assert out.startswith(b"<!DOCTYPE svg")
    assert b"dtd" not in out.lower() if expect_removed else out == content
    assert svg_runtime.is_safe_svg(out, svg_runtime.MAX_PREVIEW_SVG_BYTES,
                                   **PREVIEW)


def test_a_file_with_no_doctype_is_returned_byte_for_byte():
    """The overwhelming majority of files, and the case a rewriter must not
    touch. Identity, not equality-after-a-round-trip."""
    assert preview_bytes(DIAGRAM_SVG) is DIAGRAM_SVG
    assert preview_bytes(LINKED_DIAGRAM) is LINKED_DIAGRAM


def test_an_entity_declaration_is_still_refused_before_any_of_this_runs():
    """`B160`'s `<!ENTITY` refusal is what keeps an internal subset small, and
    it is the reason the DOCTYPE walk above can be bounded to the prolog."""
    bomb = (b'<!DOCTYPE svg [<!ENTITY a "aaaa">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg"><text>&a;</text></svg>')
    assert svg_runtime.svg_refusal_reason(
        bomb, svg_runtime.MAX_PREVIEW_SVG_BYTES,
        **PREVIEW) == svg_runtime.SVG_REFUSAL_ENTITY
