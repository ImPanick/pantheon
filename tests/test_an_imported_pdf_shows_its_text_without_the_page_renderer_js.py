# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW` (f-import) — with no PyMuPDF, an imported PDF opens showing the
text the import read, under one line saying why the pages are not drawn.

PyMuPDF draws the PDF view's pages and is optional (`requirements-optional.txt`);
the default image does not install it, and `GET /api/document/{id}/render-pages`
then answers 503 with *"PDF viewer requires PyMuPDF. Install optional PDF
dependencies with `pip install -r requirements-optional.txt` (PyMuPDF is
AGPL-3.0)."* On the tree before this row the Documents panel put that in red as
*"Failed to load PDF view: …"* where the PDF should be — measured by `f-import`
in Chromium, and by the first case here — while the text the import extracted
(`[Page 1 text]: …`) was in the document all along.

Driven (`Law 20`): the panel's ``_renderPdfPane`` and its helpers, cut out of
``document.js`` with ``js_source`` and run under node on the shared DOM shim,
fetching from the REAL document routes served on a loopback socket (the
`P21-03` harness), with a real PDF imported through the real ``import-pdf`` and
PyMuPDF absent the way the product sees it.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests.helpers.esc_stub import ui_default_stub
from tests.helpers.js_source import js_definition
from tests.test_a_file_imported_from_device_opens_readable import _run_js, live  # noqa: F401
from tests.test_an_uploaded_document_keeps_its_name import env  # noqa: F401
from tests.test_attachment_extension_registers import _minimal_pdf
from tests.test_tool_effect_surfaces_js import _DOM

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

ROOT = Path(__file__).resolve().parents[1]
DOCJS = (ROOT / "static" / "js" / "document.js").read_text(encoding="utf-8")


def _cut(signature: str) -> str:
    return js_definition(DOCJS, DOCJS.index(signature))


@pytest.fixture
def no_pymupdf(monkeypatch):
    import src.pdf_runtime as pr

    def missing():
        raise RuntimeError(pr.PDF_VIEWER_PYMUPDF_MISSING)

    monkeypatch.setattr(pr, "load_pymupdf_for_pdf_viewer", missing)


def _import_pdf(live, name, text):  # noqa: F811
    r = live.client.post("/api/documents/import-pdf",
                         files={"file": (name, _minimal_pdf(text), "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def _pane(live, doc_id, content):  # noqa: F811
    """The panel showing *doc_id* in the PDF view: what the pane holds after
    `_renderPdfPane()` runs."""
    work = live.tmp / "pdf-pane"
    work.mkdir(parents=True, exist_ok=True)
    (work / "dom.js").write_text(_DOM, encoding="utf-8")
    (work / "ui.js").write_text(ui_default_stub(), encoding="utf-8")
    cuts = []
    for sig in ("async function _pdfResponseErrorMessage(", "function _showPdfTextInstead(",
                "async function _renderPdfPane(", "function _escHtml("):
        if sig in DOCJS:
            cuts.append(_cut(sig))
    source = (
        "import { installDom } from './dom.js';\n"
        "import uiModule from './ui.js';\n"
        "const realFetch = globalThis.fetch;\n"
        "const document = installDom();\n"
        "globalThis.fetch = realFetch;   // the shim stubs it; this page talks to the server\n"
        f"const API_BASE = {json.dumps(live.base)};\n"
        "const pane = document.createElement('div'); pane.id = 'doc-pdf-view';\n"
        "document.body.appendChild(pane);\n"
        f"let activeDocId = {json.dumps(doc_id)};\n"
        f"const docs = new Map([[activeDocId, {{ id: activeDocId, content: {json.dumps(content)} }}]]);\n"
        "function _wirePdfPaneProximity() {}\n"
        + "\n".join(cuts) +
        "\nawait _renderPdfPane();\n"
        "const pick = (cls) => pane._walk([]).find((n) => n.className === cls) || null;\n"
        "const note = pick('doc-pdf-text-note'), page = pick('doc-pdf-text-page');\n"
        "console.log(JSON.stringify({\n"
        "  text: pane.textContent,\n"
        "  note: note && note.textContent, role: note && note.getAttribute('role'),\n"
        "  page: page && page.textContent,\n"
        "  pageNodes: page ? page.childNodes.map((n) => n.tagName) : null,\n"
        "}));\n"
    )
    return _run_js(work, source)


def test_with_no_page_renderer_the_pdf_opens_as_its_text(live, no_pymupdf):  # noqa: F811
    doc = _import_pdf(live, "Signed lease – 2026.pdf", "PDFSENTINEL the tenant pays rent")
    shown = _pane(live, doc["id"], doc["current_content"])
    assert "Failed to load PDF view" not in shown["text"]
    from src.pdf_runtime import PDF_VIEWER_PYMUPDF_MISSING
    assert shown["note"] == "Showing the text read from this PDF. " + PDF_VIEWER_PYMUPDF_MISSING
    assert shown["role"] == "note"
    page = shown["page"]
    assert "PDFSENTINEL the tenant pays rent" in page
    assert page.startswith("# Signed lease – 2026")
    # The hidden markers stay hidden.
    assert "<!--" not in page and "pdf_source" not in page and "upload_id" not in page


def test_the_text_is_shown_as_text_never_as_markup(live, no_pymupdf):  # noqa: F811
    hostile = "<img src=x onerror=alert(1)> PAGESENTINEL"
    doc = _import_pdf(live, "Odd.pdf", "x")
    content = doc["current_content"].replace("[Page 1 text]:", "[Page 1 text]:\n" + hostile)
    shown = _pane(live, doc["id"], content)
    assert hostile in shown["page"]
    assert shown["pageNodes"] in ([], ["#TEXT"])


def test_a_pdf_with_no_text_says_so_in_place_of_a_page(live, no_pymupdf):  # noqa: F811
    doc = _import_pdf(live, "Scan.pdf", "x")
    shown = _pane(live, doc["id"], '<!-- pdf_source upload_id="u1" -->\n\n')
    assert shown["page"] == "No text could be read from this PDF."
    assert shown["note"].startswith("Showing the text read from this PDF.")


def test_any_other_failure_is_still_said_as_a_failure(live, no_pymupdf):  # noqa: F811
    """Only the server's "cannot draw pages here" (503) falls back to the text;
    a document that is gone is still an error, in words."""
    shown = _pane(live, "no-such-document", "PDFSENTINEL")
    assert shown["text"].startswith("Failed to load PDF view: ")
    assert shown["page"] is None and "PDFSENTINEL" not in shown["text"]
