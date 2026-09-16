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
    evaluated against the vendored bundle, so the options and the source the
    worker ends up holding are the app's rather than a copy of them.

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

@pytest.fixture(scope="module")
def chain():
    return run_harness("html2pdf_export_chain.js")


def test_pdf_export_options_survive_the_jspdf_major(chain):
    """The feature. Every option `document.js:9689` passes is still understood
    by the shipped bundle after html2pdf 0.10.2 -> 0.14.0 and jsPDF 2 -> 4.

    `margin: 10` coming back as `[10, 10, 10, 10]` is the load-bearing part:
    it means `set()` *normalised* the value rather than storing a number it
    would later ignore. A key that quietly stopped being read is the shape of
    break that reaches a user as a wrong page rather than as an error.
    """
    assert chain["ok"], chain
    assert chain["exportsFunction"], "the bundle no longer publishes window.html2pdf"
    el = chain["element"]
    assert "error" not in el, el
    assert el["margin"] == [10, 10, 10, 10], el
    assert el["filename"] == "pantheon-export.pdf", el
    assert el["image"] == {"type": "jpeg", "quality": 0.95}, el
    assert el["html2canvasScale"] == 2, el
    assert el["jsPDF"] == {"unit": "mm", "format": "a4", "orientation": "portrait"}, el


def test_the_export_call_site_passes_an_element_and_not_a_string(chain):
    """`B334`. `Worker.prototype.from` switches on the source's type: a string
    goes through `createElement('div', {innerHTML: src})` — the sink
    CVE-2026-22787 is about — and an element is stored as-is.

    `static/js/document.js` builds a detached `<div>` and passes the node, so
    Pantheon is on the element branch. That is measured here by running the real
    `exportAsPdf` and reporting what it handed `from()`, rather than by reading
    the call site: a refactor to `.from(container.innerHTML)` would be a
    one-word change that turned a HIGH advisory live, and it fails here.
    """
    cs = chain["callSite"]
    assert cs and "error" not in cs, cs
    assert cs["fromType"] == "object", (
        "exportAsPdf passed a string to html2pdf().from() — that is the "
        f"innerHTML branch, which is CVE-2026-22787's sink: {cs}"
    )
    assert cs["fromNodeName"] == "DIV", cs
    assert "body text" in (cs["fromInnerHTML"] or ""), cs


def test_the_export_options_come_from_the_one_call_site(chain):
    """`Law 13`. The options this file feeds the bundle are read out of
    `document.js`, so the two cannot drift; asserting their values here is what
    makes the reading visible to somebody changing them."""
    opts = chain["callSite"]["options"]
    assert opts["margin"] == 10, opts
    assert opts["filename"].endswith(".pdf"), opts
    assert opts["image"] == {"type": "jpeg", "quality": 0.95}, opts
    assert opts["html2canvas"] == {"scale": 2}, opts
    assert opts["jsPDF"] == {"unit": "mm", "format": "a4",
                             "orientation": "portrait"}, opts


def test_pdf_export_passes_a_node_and_keeps_it(chain):
    """`document.js` hands `from()` a detached element, so the export takes the
    element branch and the string branch — the one with the sink in it — is not
    on Pantheon's path. Asserted by identity on the node that came back, which
    only the element branch can produce; the string branch builds a new `<div>`.
    """
    el = chain["element"]
    assert el["srcIsTheElementWeGave"] is True, el
    assert el["srcInnerHTML"] == "<p>hello</p>", el


def test_a_string_source_no_longer_hands_back_the_payload(chain):
    """`B334`'s differential. **Fails on html2pdf.js 0.10.2**, the version
    shipped until 2026-09-16 (CVE-2026-22787 / GHSA-w8x4-x68c-m6fc, HIGH).

    0.10.2's `createElement` set `innerHTML` and then removed `<script>`
    elements, which does nothing about `<img onerror>`, `<svg onload>` or
    `<iframe srcdoc>` — none of which is a `<script>` and all of which run.
    Running the same harness against the 0.10.2 bundle returns
    `srcInnerHTML == '<img src=x onerror="pantheonWasHere()"><b>kept</b>'`: the
    payload verbatim, in the tree the exporter was about to rasterise.
    0.14.0 replaced that block with `DOMPurify.sanitize(opt.innerHTML)`.

    The assertion is on what comes back rather than on how it failed, because
    those are different in a browser and here: with a real DOM the sanitizer
    strips the handler and returns the `<b>`, and in this shim DOMPurify
    declines to run at all. Both are "the payload did not survive"; neither is
    0.10.2's answer.

    Pantheon does not take this branch today (the test above measures that).
    The branch is one refactor from being taken, and that is reason enough to
    be on the version where it is sanitised.
    """
    s = chain["string"]
    assert "onerror" not in json.dumps(s), (
        "a string source handed the raw payload back to the exporter — this is "
        f"html2pdf 0.10.2's behaviour: {s}"
    )
    assert "pantheonWasHere" not in json.dumps(s), s
