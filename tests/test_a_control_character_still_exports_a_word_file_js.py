# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B422` — a control character in a document still exports a `.docx` Word
can open.

Measured 2026-09-17 while evaluating `B335`'s docx bump, and again on
`03f50081`: `static/js/document.js`'s `exportAsDocx` handed each line of the
editor's text to `new TextRun(...)`, and `docx` writes it into
`word/document.xml` escaping only `&`, `<` and `>`. XML 1.0 forbids the C0
controls other than tab, LF and CR outright — they cannot be escaped, only
removed — so a vertical tab (`U+000B`), a form feed (`U+000C`) or a `U+0001`
pasted from a PDF or a terminal made a file whose `word/document.xml` does not
parse (`minidom`: *"not well-formed (invalid token)"*; Word: corrupt).

Driven (`Law 20`): the real `exportAsDocx`, cut out of `document.js` with
`js_source`, runs under node against the REAL vendored
`static/lib/docx.umd.min.js`; the blob it would download is captured, unzipped
here and `word/document.xml` parsed with `xml.dom.minidom`.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.dom import minidom

import pytest

from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parents[1]
DOCJS = (ROOT / "static" / "js" / "document.js").read_text(encoding="utf-8")
DOCX_BUNDLE = ROOT / "static" / "lib" / "docx.umd.min.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _export(tmp_path: Path, text: str) -> bytes:
    """What *Export as Word* downloads for a document whose editor holds `text`."""
    fn = js_definition(DOCJS, DOCJS.index("async function exportAsDocx("))
    out = tmp_path / "export.docx"
    case = tmp_path / "case.cjs"
    case.write_text(
        "globalThis.self = globalThis; globalThis.window = globalThis;\n"
        f"globalThis.docx = require({json.dumps(str(DOCX_BUNDLE))});\n"
        "const fs = require('fs');\n"
        "let saved = null, toast = null;\n"
        "const textarea = { value: JSON.parse(process.argv[2]) };\n"
        "const document = {\n"
        "  getElementById: (id) => (id === 'doc-editor-textarea' ? textarea : null),\n"
        "  createElement: () => ({ click() {} }),\n"
        "};\n"
        "globalThis.URL.createObjectURL = (b) => { saved = b; return 'blob:x'; };\n"
        "globalThis.URL.revokeObjectURL = () => {};\n"
        "const activeDocId = 'd1';\n"
        "const ensureDocx = async () => {};\n"
        "const uiModule = { showToast: (m) => { toast = m; }, showError: (m) => { toast = 'ERR ' + m; } };\n"
        "const _getExportBaseName = () => 'probe';\n"
        + fn + "\n"
        "exportAsDocx().then(async () => {\n"
        "  fs.writeFileSync(process.argv[3], Buffer.from(await saved.arrayBuffer()));\n"
        "  console.log(JSON.stringify({ toast }));\n"
        "}).catch((e) => { console.error(e); process.exit(1); });\n",
        encoding="utf-8")
    proc = subprocess.run(["node", str(case), json.dumps(text), str(out)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"toast": "Exported as DOCX"}
    return out.read_bytes()


def _document_xml(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return z.read("word/document.xml").decode("utf-8")


def _texts(xml: str) -> list[str]:
    dom = minidom.parseString(xml)   # raises on a document that is not well-formed
    return ["".join(n.data for n in t.childNodes if n.nodeType == n.TEXT_NODE)
            for t in dom.getElementsByTagName("w:t")]


@pytest.mark.parametrize("control", ["\u000b", "\u000c", "\u0001", "\u001f", "￾"])
def test_a_document_with_a_forbidden_control_exports_a_word_file_that_parses(tmp_path, control):
    """`Verify:` a document containing `U+000B` exports to a `.docx` whose
    `word/document.xml` parses — and the four others in the forbidden range."""
    xml = _document_xml(_export(tmp_path, f"# Notes\n\nport{control}8080 is **open**\nlast line"))
    texts = _texts(xml)
    joined = "".join(texts)
    assert "port" in joined and "8080" in joined and "open" in joined and "last line" in joined
    assert control not in xml


def test_a_vertical_tab_or_form_feed_is_a_line_break_not_glue(tmp_path):
    """They were line breaks where they came from, so the words either side
    stay apart — on lines of their own."""
    texts = _texts(_document_xml(_export(tmp_path, "alpha\u000bbeta\u000cgamma")))
    assert texts == ["alpha", "beta", "gamma"], texts


def test_tab_and_the_allowed_characters_are_kept(tmp_path):
    """Tab and U+00A0 were always fine (measured), and emoji: unchanged."""
    texts = _texts(_document_xml(_export(tmp_path, "a\tb c 🎉")))
    assert texts == ["a\tb c 🎉"], texts
