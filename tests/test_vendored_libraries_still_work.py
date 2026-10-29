# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two user-visible paths through the vendored libraries, driven for real.

`B331`, `B334`. On 2026-09-16 `mammoth.browser.min.js` went 1.8.0 -> 1.12.3 and
`html2pdf.bundle.min.js` went 0.10.2 -> 0.14.0, the second of those crossing
jsPDF 2 -> 4. Those are the libraries behind `.docx` import and PDF export, and
a silent break in either is worse than the advisories the bump was for: a user
who exports a broken PDF finds out later, from the PDF.

So these tests do not check that a file changed. They run the shipped bundles:

  * `.docx` import — a real OOXML package is built here and handed to
    `readFileContent`, lifted out of `static/js/documentLibrary.js` and
    evaluated, which reaches the vendored mammoth itself.
  * PDF export — `exportAsPdf` is lifted out of `static/js/document.js` and
    evaluated against the vendored jsPDF, so the options and the source the
    worker ends up holding are the app's rather than a copy of them. (`B421`,
    2026-10-29: the html2pdf bundle is gone and the fallback PDF is jsPDF
    4.2.1's own `html()`; the PDF section below says what replaced what.)

Driving the call sites rather than copying their arguments is `Law 13`: the
options and the `from()` argument are set in one place, and a test that restated
them would keep passing after the one place changed.

Each file also carries the differential that makes this evidence rather than a
green light: an input the OLD bundle got wrong. Those are marked with the
version each one fails on, measured by checking out the previous bundle and
running the same harness (`Law 9`).

The fixtures are built in-process rather than committed as binaries, so a
reader can see exactly which OOXML shape is under test instead of unzipping
something to find out.
"""
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "harness"

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")

# ── Minimal OOXML ──────────────────────────────────────────────────────────
# Three parts is the whole of a valid-enough `.docx` for a converter: the
# content-type map, the package relationship naming the main part, and the main
# part. Word writes a dozen more and mammoth needs none of them.

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"'
)


def docx(body: str) -> bytes:
    """A `.docx` whose `word/document.xml` body is `body`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   f"<w:document {_NS}><w:body>{body}</w:body></w:document>")
    return buf.getvalue()


def run_harness(script: str, *args, timeout: int = 60) -> dict:
    """Run a harness and parse its one line of JSON."""
    entry = HARNESS / script
    assert entry.is_file(), f"missing harness {entry}"
    proc = subprocess.run(
        ["node", str(entry), *args], cwd=ROOT,
        capture_output=True, text=True, timeout=timeout,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines, (
        f"{script} printed no JSON.\nexit={proc.returncode}\n"
        f"stdout tail: {proc.stdout[-600:]}\nstderr tail: {proc.stderr[-600:]}"
    )
    return json.loads(lines[-1])


def convert(body: str, tmp_path: Path) -> dict:
    path = tmp_path / "sample.docx"
    path.write_bytes(docx(body))
    return run_harness("mammoth_docx_import.js", str(path))


# ── .docx import ───────────────────────────────────────────────────────────

def test_docx_import_converts_a_document(tmp_path):
    """The feature, end to end through the shipped bundle.

    Headings, bold and italic are the three things the document library's
    `htmlToMarkdown` then turns into markdown, so a bundle that stopped
    emitting `<h1>`, `<strong>` or `<em>` would produce documents that import
    as flat text and nobody would see an error.
    """
    result = convert(
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        "<w:r><w:t>Vendored bump</w:t></w:r></w:p>"
        '<w:p><w:r><w:t xml:space="preserve">plain </w:t></w:r>'
        "<w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>"
        '<w:r><w:t xml:space="preserve"> and </w:t></w:r>'
        "<w:r><w:rPr><w:i/></w:rPr><w:t>italic</w:t></w:r></w:p>",
        tmp_path,
    )
    assert result["ok"], result
    assert "<h1>Vendored bump</h1>" in result["html"], result["html"]
    assert "<strong>bold</strong>" in result["html"], result["html"]
    assert "<em>italic</em>" in result["html"], result["html"]


def test_docx_import_survives_alternate_content_with_no_fallback(tmp_path):
    """`B331`'s differential. **Fails on mammoth 1.8.0**, the version shipped
    until 2026-09-16.

    `mc:AlternateContent` offers a renderer a choice of representations and is
    supposed to carry an `mc:Fallback`. Word writes one; other producers do not
    always. 1.8.0's `collapseAlternateContent` called `node.first("mc:Fallback")`
    and read `.children` off the result, so a document without the fallback
    raised `TypeError: Cannot read properties of undefined (reading 'children')`
    — as an UNHANDLED rejection, which is why the harness reports those: it
    never reached the `.catch` the import path relies on.

    Measured by checking out the previous bundle and running this same harness:
    1.8.0 returns `ok: false, unhandled: true`; 1.12.3 returns the document.
    A `.docx` somebody else authored is the whole feature, so a shape that
    denies the import is a defect whoever produced the file gets to trigger.
    """
    result = convert(
        "<w:p><w:r><w:t>before</w:t></w:r></w:p>"
        "<w:p><w:r><mc:AlternateContent>"
        '<mc:Choice Requires="wps"><w:drawing/></mc:Choice>'
        "</mc:AlternateContent></w:r></w:p>"
        "<w:p><w:r><w:t>after</w:t></w:r></w:p>",
        tmp_path,
    )
    assert result["ok"], (
        "a .docx with mc:AlternateContent and no mc:Fallback did not import: "
        f"{result.get('error')}"
    )
    assert "before" in result["html"] and "after" in result["html"], result["html"]


def test_docx_import_keeps_a_form_checkbox(tmp_path):
    """`B331`'s second differential. **Fails on mammoth 1.8.0**, which dropped
    the checkbox silently and imported only the label beside it — so a
    requirements document arrived with every box gone and no message saying so.
    1.11.0 added `documents.checkbox` and emits `<input type="checkbox">`.
    """
    result = convert(
        '<w:p><w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:checkBox>'
        '<w:checked w:val="true"/></w:checkBox></w:ffData></w:fldChar></w:r>'
        '<w:r><w:instrText xml:space="preserve"> FORMCHECKBOX </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        '<w:r><w:t xml:space="preserve"> ship the bump</w:t></w:r></w:p>',
        tmp_path,
    )
    assert result["ok"], result
    assert 'type="checkbox"' in result["html"], result["html"]
    assert 'checked="checked"' in result["html"], result["html"]
    assert "ship the bump" in result["html"], result["html"]


def test_docx_import_reports_a_problem_rather_than_throwing(tmp_path):
    """A file that is not a `.docx` at all has to come back as a rejected
    promise the import path can catch, not as a crash. `documentLibrary.js`
    awaits `convertToHtml` inside the import flow; an unhandled rejection there
    takes the whole import down with no toast.
    """
    path = tmp_path / "not-a-docx.docx"
    path.write_bytes(b"this is not a zip file at all")
    result = run_harness("mammoth_docx_import.js", str(path))
    assert result["ok"] is False
    assert not result.get("unhandled"), (
        "a non-.docx produced an unhandled rejection instead of a rejected "
        f"promise: {result}"
    )


# ── PDF export ─────────────────────────────────────────────────────────────
#
# `B421` (`D-2026-10-29-02` §2). The fallback PDF is jsPDF 4.2.1's own
# `html()` now, with html2canvas 1.4.1 and DOMPurify 3.4.17 beside it as their
# own published files; html2pdf.js and its bundle are gone. `B421`'s `Verify:`
# asked for this file's `exportAsPdf` chain to pass *unchanged* — that was
# written for splitting the bundle into html2pdf's own three files, and it
# cannot hold once html2pdf itself goes: there is no `html2pdf().set()` left to
# read an option back from. So the chain is the same span of `document.js`,
# driven against the real vendored jsPDF instead (`jspdf_export_chain.js`),
# and each test below says which of the old ones it stands in for. The drawing
# itself needs a browser and is driven in
# `tests/test_the_fallback_pdf_is_jspdfs_own_with_its_links_in_a_browser.py`.

@pytest.fixture(scope="module")
def chain():
    return run_harness("jspdf_export_chain.js")


def test_pdf_export_options_are_read_by_the_vendored_jspdf(chain):
    """The feature. Every option the call site passes is understood by the
    shipped jsPDF's `html()` Worker, read back after `set()` ran (was
    `test_pdf_export_options_survive_the_jspdf_major`, against html2pdf).

    `margin: 10` coming back as `[10, 10, 10, 10]` is the load-bearing part:
    `set()` normalised it rather than storing a number it would later ignore.
    `drawsIntoThePdf` is why the file is text: `html()` hands html2canvas
    jsPDF's own canvas, whose 2D context writes PDF operators, where html2pdf
    drew into a bitmap and pasted JPEG tiles.
    """
    assert chain["ok"], chain
    assert chain["version"] == "4.2.1", chain["version"]
    w = chain["worker"]
    assert w["margin"] == [10, 10, 10, 10], w
    assert w["width"] == pytest.approx(190, abs=0.01), w
    assert w["innerWidth"] == pytest.approx(w["width"]), (
        "the content is drawn as wide as the page between its margins", w)
    # 96 CSS px to the inch: 12px type is 9pt on the page, as it was.
    assert w["width"] / w["windowWidth"] == pytest.approx(25.4 / 96), w
    assert w["autoPaging"] is True, w
    assert w["allowTaint"] is False, w
    assert w["drawsIntoThePdf"] is True and w["sameDocument"] is True, w


def test_the_export_call_site_hands_jspdf_a_string_so_dompurify_runs(chain):
    """`B421` turned `B334`'s test around (`..._passes_an_element_and_not_a_string`).

    `B334` pinned the element branch because html2pdf 0.10.2's string branch
    was `innerHTML` with only `<script>` removed — CVE-2026-22787's sink. In
    jsPDF 4.2.1's `html()` the string branch is `DOMPurify.sanitize` with the
    DOMPurify shipped beside it (3.4.17, zero advisories), and the element
    branch is the one that uses no sanitiser at all: the string is how the
    third file does anything (`Law 13`). The browser test counts the
    `sanitize` call; this reads the type the real call site passes, so a
    refactor back to `.html(container)` is a one-word change that fails here.
    """
    cs = chain["callSite"]
    assert cs["errors"] == [], cs
    assert cs["srcType"] == "string", (
        "_rasterisePdf handed jsPDF a node — the branch DOMPurify never sees", cs)
    assert cs["fromIsSrc"] is True, cs
    assert "body text" in cs["src"], cs
    assert cs["src"].startswith('<div style="padding:20px;'), (
        "the container's own style travels with it — the string is its outerHTML", cs)
    assert cs["saved"] == "pantheon-export.pdf", cs


def test_the_export_options_come_from_the_one_call_site(chain):
    """`Law 13`. The options this file feeds jsPDF are read out of
    `document.js`, so the two cannot drift; asserting their values here is
    what makes the reading visible to somebody changing them."""
    cs = chain["callSite"]
    assert cs["ctor"] == {"unit": "mm", "format": "a4", "orientation": "portrait"}, cs
    opts = cs["options"]
    assert opts["worker"] is True and opts["margin"] == 10, opts
    assert opts["autoPaging"] is True, opts
    # `onclone` is a function and does not survive JSON; it is driven by
    # `test_the_rasteriser_is_shown_a_clone_with_none_of_this_pages_styles`.
    # No `scale`: `html()` derives it from `width`/`windowWidth`, and the
    # `scale: 2` html2pdf took would draw everything twice the size.
    assert opts["html2canvas"] == {"allowTaint": False, "onclone": "function"}, opts


def test_the_rasteriser_is_shown_a_clone_with_none_of_this_pages_styles(chain):
    """`B1322` (fx6-export). html2canvas reads *computed* styles, and
    `static/style.css`'s `color-mix(in srgb, …)` rules compute to
    `color(srgb …)`, which its colour parser cannot read: measured in Chromium
    on a document with a fenced code block (so `.code-block-header` applies),
    the export threw `Attempting to parse an unsupported color function
    "color"` and produced no file at all, while Markdown and Word — which
    never rasterise — worked. The bundle is vendored byte-identical
    (`FORBIDDEN.md` Part 1), so the fix is what the clone is allowed to carry.

    `B421`: html2canvas is the same 1.4.1 under jsPDF's `html()`, so this hook
    still stands between the page and the parser. And it was no longer
    enough — measured on the tree before `B421`, html2pdf and all, the same
    document failed again on `"oklab"`, because html2canvas copies the live
    page's computed style inline onto every SVG it clones, and the code
    block's icons compute to `oklab(…)`. The second half below is that SVG.

    Driven here, not read: the `onclone` the real call site passes is called on
    a clone and what it did is reported.
    """
    hook = chain["onclone"]
    assert hook["type"] == "function", (
        "exportAsPdf passes html2canvas no `onclone`, so the clone keeps this "
        f"page's stylesheets and the colour it cannot parse: {hook}"
    )
    assert "error" not in hook, hook
    assert hook["removed"] == ["link", "style"], \
        "the page's own stylesheets must not reach the clone"
    assert hook["added"] == 1, "the clone is given the export's own rules"
    assert "color-mix(" not in hook["rules"] and "color(srgb" not in hook["rules"], \
        "the rules the clone is given must be ones the rasteriser can read"
    assert "white-space:pre-wrap" in hook["rules"], \
        "without the page's stylesheet a <pre> falls back to the UA's "\
        "`white-space: pre`, and long lines run off the page"
    assert ".code-block-header button" in hook["rules"], \
        "the code block's buttons are hidden here as the printed frame hides them"
    # The SVG: every colour the parser cannot read is gone — the logical
    # longhand too — and nothing else was touched.
    assert hook["svgKept"] == ["border-top-width", "box-shadow", "outline-color",
                               "stroke-width"], hook["svgKept"]


def test_a_link_is_a_box_over_its_words_and_only_a_way_out_is_one(chain):
    """`B421`. html2pdf's link plugin, which Pantheon had on by default and
    jsPDF's `html()` does not have, rebuilt as `_pdfLinkBoxes` (stands in for
    `test_pdf_export_passes_a_node_and_keeps_it`, whose branch is gone).

    One box per line box, in millimetres from the drawn element's corner, so a
    link that wraps is clickable on both lines. An in-page `#anchor` and a
    `javascript:` URL are not links out of a file someone saves; `mailto:` is.
    """
    links = chain["links"]
    assert [(round(b["x"], 3), round(b["y"], 3), round(b["w"], 3), round(b["h"], 3), b["url"])
            for b in links] == [
        (5, 5, 15, 4, "https://example.com/x"),
        (125, 10, 50, 4, "https://example.com/wraps"),
        (5, 14, 20, 4, "https://example.com/wraps"),
        (5, 30, 10, 4, "mailto:someone@example.com"),
    ], links


def test_what_the_built_in_fonts_cannot_draw_is_named(chain):
    """`B421`. `html()` writes text with the PDF's built-in fonts (WinAnsi),
    so Cyrillic, CJK and emoji come out wrong — measured in Chromium, and
    said to the person by `_rasterisePdf`. Latin-1 and Windows-1252's extras
    (“ ” — €) draw; `™` is in the table and jsPDF draws a space for it. A
    zero-width space is not named: nobody can be told about what they cannot
    see."""
    assert chain["undrawable"] == ["™", "П", "р", "и", "в", "е", "т", "你", "好", "🎉"], \
        chain["undrawable"]
