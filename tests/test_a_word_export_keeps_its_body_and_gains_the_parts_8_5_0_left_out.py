# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B424` — *Export as Word* runs on docx 9.7.1, and Pantheon's body did not move.

The owner's call (`D-2026-10-29-02` §4): take docx 9.7.1, with every package
its build reveals declared. `B335` measured the bump on 2026-09-17 and found it
safe — `Document`, `Packer`, `Paragraph`, `TextRun` and `HeadingLevel`
unchanged, and the `word/document.xml` body emitted for Pantheon's paragraph
and run shapes byte-identical to 8.5.0's — and named three OOXML package
defects in 8.5.0. Re-measured here on 2026-10-29 through Pantheon's own
`exportAsDocx`, two of them are real and 9.7.1 fixes both:

  * the package declares footnotes and ships no `word/endnotes.xml`;
  * `word/fontTable.xml` is an orphan part — content-typed and present in the
    zip, the target of no relationship from `word/_rels/document.xml.rels`.

The third does not hold on this path: 8.5.0's `w:document` *does* carry
`mc:Ignorable="w14 w15 wp14"` for what Pantheon writes (at the end of its
attribute list, where 9.7.1 puts it first). It is still pinned below, as a
property, not as a differential.

What stopped the bump was attribution (forty-five packages its Vite build
names; `check-licences.py` rule 7 holds them now), not behaviour. So this file
measures behaviour, as `tests/test_a_control_character_still_exports_a_word_file_js.py`
does: the real `exportAsDocx`, cut out of `static/js/document.js`, runs under
node against the REAL vendored `static/lib/docx.umd.min.js`, and the `.docx`
it would download is unzipped here.

**Fails on the tree before `B424`** (`Law 9`): the endnotes and font-table
tests below fail on docx 8.5.0 — measured by running this file against the
8.5.0 bundle — and `BODY_8_5_0` is what 8.5.0 emitted for `SHAPES`, captured the same way, so
the body test is the differential that says the bump moved nothing a person
wrote.
"""
from __future__ import annotations

import io
import json
import re
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

# Every shape `exportAsDocx` makes: the three heading levels, a plain line, a
# line of bold and italic runs between plain ones, an empty line, the three
# characters docx escapes, a tab, and text outside Latin-1.
SHAPES = "\n".join([
    "# Title",
    "## Section",
    "### Sub",
    "plain line",
    "a **bold** b *italic* c",
    "",
    "x < y & z > w",
    "tab\there",
    "Привет 你好 🎉",
])

# `<w:body>…</w:body>` as docx **8.5.0** wrote it for `SHAPES`, through the real
# `exportAsDocx`, on 2026-10-29 (the bundle as it stood at `558767a3`).
BODY_8_5_0 = (
    '<w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t xml:space="preserve">'
    'Title</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t xml:'
    'space="preserve">Section</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="Heading3"/></w:'
    'pPr><w:r><w:t xml:space="preserve">Sub</w:t></w:r></w:p><w:p><w:r><w:t xml:space="pres'
    'erve">plain line</w:t></w:r></w:p><w:p><w:r><w:t xml:space="preserve">a </w:t></w:r><w:'
    'r><w:rPr><w:b/><w:bCs/></w:rPr><w:t xml:space="preserve">bold</w:t></w:r><w:r><w:t xml'
    ':space="preserve"> b </w:t></w:r><w:r><w:rPr><w:i/><w:iCs/></w:rPr><w:t xml:space="pre'
    'serve">italic</w:t></w:r><w:r><w:t xml:space="preserve"> c</w:t></w:r></w:p><w:p><w:r>'
    '<w:t xml:space="preserve"></w:t></w:r></w:p><w:p><w:r><w:t xml:space="preserve">x &lt; '
    'y &amp; z &gt; w</w:t></w:r></w:p><w:p><w:r><w:t xml:space="preserve">tab\there</w:t></'
    'w:r></w:p><w:p><w:r><w:t xml:space="preserve">Привет 你好 🎉</w:t></w:r></w:p><w:sectPr>'
    '<w:pgSz w:w="11906" w:h="16838" w:orient="portrait"/><w:pgMar w:top="1440" w:right="14'
    '40" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/><w:pgNum'
    'Type/><w:docGrid w:linePitch="360"/></w:sectPr></w:body>'
)


def export(tmp_path: Path, text: str, bundle: Path = DOCX_BUNDLE) -> bytes:
    """What *Export as Word* downloads for a document whose editor holds `text`."""
    fn = js_definition(DOCJS, DOCJS.index("async function exportAsDocx("))
    out = tmp_path / "export.docx"
    case = tmp_path / "case.cjs"
    case.write_text(
        "globalThis.self = globalThis; globalThis.window = globalThis;\n"
        f"globalThis.docx = require({json.dumps(str(bundle))});\n"
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


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    blob = export(tmp_path_factory.mktemp("docx-9"), SHAPES)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return {name: z.read(name).decode("utf-8") for name in z.namelist()}


def _body(document_xml: str) -> str:
    return re.search(r"<w:body>.*</w:body>", document_xml, re.S).group(0)


def test_the_body_pantheon_writes_is_the_body_8_5_0_wrote(package):
    """`B424`'s `Verify:` — the export still round-trips: the body XML for
    every shape `exportAsDocx` makes is byte-identical to 8.5.0's, and it
    parses."""
    body = _body(package["word/document.xml"])
    assert body == BODY_8_5_0
    dom = minidom.parseString(package["word/document.xml"])
    texts = ["".join(n.data for n in t.childNodes if n.nodeType == n.TEXT_NODE)
             for t in dom.getElementsByTagName("w:t")]
    assert texts == ["Title", "Section", "Sub", "plain line", "a ", "bold", " b ", "italic",
                     " c", "", "x < y & z > w", "tab\there", "Привет 你好 🎉"], texts


def test_the_document_marks_its_newer_namespaces_ignorable(package):
    """Not a differential — 8.5.0 passes this too on Pantheon's path (see the
    module docstring). Pinned because a part that declares `w14`/`w15` without
    `mc:Ignorable` is one a strict consumer may refuse, and the next bump
    should not be able to lose it quietly."""
    dom = minidom.parseString(package["word/document.xml"])
    root = dom.documentElement
    assert root.tagName == "w:document"
    ignorable = root.getAttribute("mc:Ignorable").split()
    assert {"w14", "w15"} <= set(ignorable), ignorable
    for prefix in ignorable:
        assert root.hasAttribute(f"xmlns:{prefix}"), prefix


def test_the_endnotes_part_the_package_declares_is_there(package):
    """8.5.0 shipped footnotes and no `word/endnotes.xml`."""
    assert "word/footnotes.xml" in package
    assert "word/endnotes.xml" in package, sorted(package)
    minidom.parseString(package["word/endnotes.xml"])


def test_the_font_table_is_a_part_the_document_points_at(package):
    """8.5.0 left `word/fontTable.xml` an orphan: present and content-typed,
    the target of no relationship from the main part."""
    assert "word/fontTable.xml" in package
    rels = minidom.parseString(package["word/_rels/document.xml.rels"])
    targets = {r.getAttribute("Target") for r in rels.getElementsByTagName("Relationship")}
    assert "fontTable.xml" in targets, sorted(targets)


def test_loaded_as_a_script_it_publishes_docx_and_leaks_no_node_shim():
    """`ensureDocx` loads the file with a `<script>` tag, which takes the UMD's
    browser branch — not the `require` branch the tests above drive. 9.7.1's
    build carries vite-plugin-node-polyfills' `global` and `process` shims and
    a `Buffer`; run as a classic script in a bare global, it publishes
    `docx` and nothing of those. `setImmediate`/`clearImmediate` are JSZip's
    `setimmediate` polyfill, which 8.5.0 installed too (measured the same
    way). Driven in Chromium as well on 2026-10-29: *Export as Word* on 9.7.1
    downloads a `.docx` whose text is the document's, with `window.process`,
    `window.global` and `window.Buffer` still undefined after it."""
    script = (
        "const vm = require('vm'), fs = require('fs');\n"
        "const ctx = {}; ctx.window = ctx; ctx.self = ctx; vm.createContext(ctx);\n"
        "const before = new Set(Object.keys(ctx));\n"
        f"vm.runInContext(fs.readFileSync({json.dumps(str(DOCX_BUNDLE))}, 'utf8'), ctx);\n"
        "const d = ctx.docx || {};\n"
        "console.log(JSON.stringify({ added: Object.keys(ctx).filter((k) => !before.has(k)).sort(),\n"
        "  api: ['Document', 'Packer', 'Paragraph', 'TextRun', 'HeadingLevel']\n"
        "    .filter((k) => d[k] !== undefined) }));\n"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got["added"] == ["clearImmediate", "docx", "setImmediate"], got
    assert got["api"] == ["Document", "Packer", "Paragraph", "TextRun", "HeadingLevel"], got
