# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW` (f-import) — on a default install, one `.docx` and one `.xlsx` are
the same document whichever door they come through.

Measured by `f-import` and again here on the tree before this row, with
markitdown absent (the default image installs neither it nor `python-docx`):
the Library (and *Import from device*, its one per-file function since `B400`)
converts in the browser with the vendored mammoth and SheetJS — `# Quarterly
Report`, `## Highlights`, `- Revenue rose…`, a table; and a CSV — while the
server doors read the same `.docx` with the bare `<w:t>` walk (paragraphs, no
headings, no list, the table's cells as loose lines) and refused the `.xlsx`
(*"Office/EPUB document extraction requires markitdown"*): `import-office` (a
chat chip's *open as document*) 422, the chat's auto-document none, the
mailbox's `attachment-as-doc` an error.

Now the server reads both with the standard library (`src/ooxml_native.py`,
rungs of `markitdown_runtime._NATIVE_EXTRACTORS`). What every case compares is
the stored document — title, language, text — door by door (`Law 20`):

  * **the Library** — the browser's own converters run in Chromium (the vendored
    mammoth with the Library's real ``htmlToMarkdown`` cut out of
    ``documentLibrary.js``; the vendored SheetJS), their output stored the way
    ``importFileAsDocuments`` stores it (``POST /api/document``; `B400`'s test
    drives that function itself);
  * **a chat chip's *open as document*** — ``POST /api/documents/import-office``;
  * **a chat attachment** — the chat send turn (``preprocess_message``), whose
    auto-document is the one the panel opens;
  * **an email attachment** — ``POST /api/email/attachment-as-doc``;

all on the `P21-03` harness (the real routers, real ``UploadHandler``, a real
SQLite file), with markitdown made absent the way the product sees it. Files:
LibreOffice's (`tests/helpers/office_fixtures.py`). Chromium runs with every
request refused and counted (none is made).
"""

import base64
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

import core.database as cdb
from tests.helpers.js_source import js_definition
from tests.helpers.office_fixtures import OFFICE_SENTINEL, office_fixture, office_sample
from tests.test_an_uploaded_document_keeps_its_name import (  # noqa: F401
    OWNER, _auto_document, _doc, _email_with, _open_from_mailbox, _upload, env,
)
from tests.test_one_office_register_across_both_doors import _without_markitdown
from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCLIB = (ROOT / "static" / "js" / "documentLibrary.js").read_text(encoding="utf-8")
LIB = ROOT / "static" / "lib"

FILES = {
    "Q3 Board Pack.docx": office_fixture(".docx"),
    "Board minutes.docx": office_sample("structured.docx"),
    "Regional sales.xlsx": office_fixture(".xlsx"),
    "Formats.xlsx": office_sample("formats.xlsx"),
    "Ledger 2026.xlsx": office_sample("ledger.xlsx"),
}

_CONVERT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [lib, work] = process.argv.slice(2);
  const files = JSON.parse(fs.readFileSync(work + '/files.json', 'utf8'));
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  let requests = 0;
  await page.route('**/*', (route) => { requests++; route.abort(); });
  await page.setContent('<!doctype html><html><body></body></html>');
  await page.addScriptTag({ path: lib + '/mammoth.browser.min.js' });
  await page.addScriptTag({ path: lib + '/xlsx.full.min.js' });
  await page.addScriptTag({ path: work + '/h2m.js' });
  const out = {};
  for (const [name, b64] of Object.entries(files)) {
    out[name] = await page.evaluate(async ([name, b64]) => {
      const buf = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer;
      if (name.endsWith('.docx')) {
        const r = await window.mammoth.convertToHtml({ arrayBuffer: buf });
        return { markdown: window.htmlToMarkdown(r.value) };
      }
      const wb = window.XLSX.read(buf, { type: 'array' });
      return { sheets: wb.SheetNames.map((n) => [n, window.XLSX.utils.sheet_to_csv(wb.Sheets[n])]) };
    }, [name, b64]);
  }
  await browser.close();
  console.log(JSON.stringify({ out, requests }));
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    """What the Library's browser converters make of each file, in Chromium."""
    if NODE is None:
        pytest.skip(_SKIP)
    work = tmp_path_factory.mktemp("library-converters")
    h2m = js_definition(DOCLIB, DOCLIB.index("function htmlToMarkdown("))
    (work / "h2m.js").write_text(h2m + "\nwindow.htmlToMarkdown = htmlToMarkdown;\n",
                                 encoding="utf-8")
    (work / "files.json").write_text(json.dumps(
        {n: base64.b64encode(b).decode() for n, b in FILES.items()}), encoding="utf-8")
    (work / "convert.js").write_text(_CONVERT, encoding="utf-8")
    proc = subprocess.run([NODE, str(work / "convert.js"), str(LIB), str(work)],
                          capture_output=True, text=True, timeout=180, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got["requests"] == 0, "the converters asked the network for something"
    return got["out"]


def _library_documents(env, name, converted):  # noqa: F811
    """The Library's documents for *name*: its conversion, stored the way
    ``importFileAsDocuments`` stores it — one markdown document for a `.docx`,
    one `csv` document per sheet with anything in it for a workbook."""
    base = name.rsplit(".", 1)[0]
    if "markdown" in converted:
        bodies = [{"source_name": name, "language": "markdown", "content": converted["markdown"]}]
    else:
        filled = [(s, csv) for s, csv in converted["sheets"] if csv.strip()]
        bodies = [{"title": f"{base} - {s}" if len(converted["sheets"]) > 1 else base,
                   "language": "csv", "content": csv, "source_name": name} for s, csv in filled]
    made = []
    for body in bodies:
        r = env.client.post("/api/document", json=body)
        assert r.status_code == 200, r.text
        made.append(_doc(env, r.json()["id"]))
    return made


def _server_documents(env, monkeypatch, name, body):  # noqa: F811
    """The same file through the three server doors: `{door: document}`."""
    r = env.client.post("/api/documents/import-office", files={"file": (name, body, "")})
    assert r.status_code == 200, r.text
    chip = _doc(env, r.json()["id"])
    chat, _said = _auto_document(env, _upload(env, name, body))
    mail = _open_from_mailbox(env, monkeypatch, _email_with(name, body))
    return {"open as document": chip, "chat attachment": chat, "email attachment": mail}


def _shape(doc):
    return (doc.title, doc.language, doc.current_content)


@pytest.mark.parametrize("name", ["Q3 Board Pack.docx", "Board minutes.docx"])
def test_a_docx_is_one_document_at_every_door(env, monkeypatch, library, name):  # noqa: F811
    _without_markitdown(monkeypatch)
    [lib] = _library_documents(env, name, library[name])
    doors = _server_documents(env, monkeypatch, name, FILES[name])
    for door, doc in doors.items():
        assert _shape(doc) == _shape(lib), door
    # And it is the document, not its zip: headings, the list, the table.
    text = lib.current_content
    assert text.startswith("# ") and "\n## " in text and "\n- " in text and "| --- |" in text


def test_the_structure_the_library_keeps_is_kept(env, monkeypatch, library):  # noqa: F811
    """`structured.docx`, line by line: what the bare `<w:t>` walk lost."""
    _without_markitdown(monkeypatch)
    doc = _server_documents(env, monkeypatch, "Board minutes.docx",
                            FILES["Board minutes.docx"])["open as document"]
    for line in ("# Board minutes",
                 "Held on **2 October**, chaired by *Rowan Ames*. STRUCTSENTINEL7c1",
                 "## Decisions", "1. Approve the Q3 budget.", "2. Hire two engineers.",
                 "3. Move the offsite to [the lake house](https://example.com/offsite).",
                 "### Risks", "- Supplier delay", "#### Figures",
                 "| Item | Amount | Note |", "| --- | --- | --- |",
                 '| Rent, office | 1200 | He said "fine" |', "Signed, ***the secretary***.",
                 # Two runs each (a colour changes mid-word), one word each.
                 "Totals are **provisional** until *audited*."):
        assert line in doc.current_content.splitlines(), line


@pytest.mark.parametrize("name", ["Regional sales.xlsx", "Formats.xlsx"])
def test_a_one_sheet_workbook_is_one_document_at_every_door(env, monkeypatch, library, name):  # noqa: F811
    _without_markitdown(monkeypatch)
    [lib] = _library_documents(env, name, library[name])
    assert lib.language == "csv"
    doors = _server_documents(env, monkeypatch, name, FILES[name])
    for door, doc in doors.items():
        assert _shape(doc) == _shape(lib), door
    if name == "Regional sales.xlsx":
        assert OFFICE_SENTINEL in lib.current_content


def test_a_workbook_of_several_sheets_is_the_librarys_sheets_in_one_document(
        env, monkeypatch, library):  # noqa: F811
    """The Library makes one `csv` document per sheet; a server door answers
    with one document, so it holds each of those sheets, word for word, under
    its name — the one-document form the Library's reader writes for a
    workbook (`readFileContent`). The empty sheet is left out at every door."""
    _without_markitdown(monkeypatch)
    name = "Ledger 2026.xlsx"
    libs = _library_documents(env, name, library[name])
    assert [d.title for d in libs] == ["Ledger 2026 - Q3 ledger", "Ledger 2026 - Notes"]
    expected = "\n\n".join(f"# Sheet: {d.title.split(' - ', 1)[1]}\n\n{d.current_content}"
                           for d in libs)
    doors = _server_documents(env, monkeypatch, name, FILES[name])
    for door, doc in doors.items():
        assert (doc.title, doc.language, doc.current_content) == \
            ("Ledger 2026", "markdown", expected), door


# ── the number formats are SheetJS's own ────────────────────────────────────

_FORMATS = ["General", "0", "0.00", "0.000", "#,##0", "#,##0.00", "0%", "0.00%",
            "#,##0.00;\\(#,##0.00\\)", "[$$]#,##0.00", '"USD "#,##0', "m/d/yy",
            "yyyy\\-mm\\-dd", "d\\ mmm\\ yyyy", "d-mmm-yy", "mmm-yy", "h:mm", "h:mm:ss",
            "hh:mm", "h:mm AM/PM", "m/d/yyyy\\ h:mm\\ AM/PM", "dddd, mmmm d, yyyy"]


def test_a_cell_reads_as_sheetjs_shows_it(tmp_path):
    """`format_cell` against SheetJS's own `SSF.format` (the vendored
    `xlsx.full.min.js`, under node), value by value: 1,200 values across
    twenty-nine orders of magnitude, both signs, rounded and not, in the
    twenty-two formats above. Equal below 10^11; past it, where `v * 10^d`
    outgrows a double's 53 bits, the two may differ in the last digit and that
    is not asserted."""
    from src.ooxml_native import format_cell

    rng = random.Random(1137)
    values = [0, 1, -1, 0.5, 1 / 3, 2 / 3, 0.1 + 0.2, 9.0855, -755808.415, 0.00075, 46297.75]
    for _ in range(1200):
        v = rng.random() * 10 ** rng.randint(-12, 16) * (-1 if rng.random() < 0.3 else 1)
        values.append(round(v, rng.randint(0, 6)) if rng.random() < 0.3 else v)
    (tmp_path / "in.json").write_text(json.dumps({"values": values, "formats": _FORMATS}))
    script = (
        "const X = require(" + json.dumps(str(LIB / "xlsx.full.min.js")) + ");"
        "const fs = require('fs');"
        "const { values, formats } = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));"
        "const out = formats.map((f) => values.map((v) => { try { return X.SSF.format(f, v); }"
        " catch (e) { return null; } }));"
        "process.stdout.write(JSON.stringify(out));")
    proc = subprocess.run(["node", "-e", script, str(tmp_path / "in.json")],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    sheetjs = json.loads(proc.stdout)
    compared, differ = 0, []
    for f, row in zip(_FORMATS, sheetjs):
        for v, want in zip(values, row):
            if want is None or abs(v) >= 1e11:
                continue
            compared += 1
            got = format_cell(v, f)
            if got != want:
                differ.append((f, v, want, got))
    assert compared > 20000
    assert differ == [], differ[:10]


# ── what did not change ─────────────────────────────────────────────────────


def test_with_markitdown_installed_it_still_answers_first(tmp_path, monkeypatch):
    """`Law 1`: an install that has markitdown keeps markitdown's rendering."""
    import src.markitdown_runtime as mr

    class _Result:
        text_content = "MARKITDOWN SAID SO"

    class _MarkItDown:
        def convert(self, path):
            return _Result()

    monkeypatch.setattr(mr, "load_markitdown", lambda: _MarkItDown)
    for name, body in (("a.docx", FILES["Board minutes.docx"]), ("b.xlsx", FILES["Formats.xlsx"])):
        path = tmp_path / name
        path.write_bytes(body)
        text = mr.convert_to_markdown(str(path))
        assert text == "MARKITDOWN SAID SO" and mr.extracted_language(text) == "markdown"


def test_a_hostile_or_broken_part_reads_as_nothing_and_says_so(env, monkeypatch, tmp_path):  # noqa: F811
    """The bundled readers' bounds: an entity-declaring part is not parsed
    (`_parse_office_xml`), a part past `PART_LIMIT` is not read whole, and
    what then has no text is refused as having none — not as a missing
    dependency, since a reader ran."""
    import io
    import zipfile

    import src.ooxml_native as ox
    from src.markitdown_runtime import NO_EXTRACTABLE_TEXT

    _without_markitdown(monkeypatch)
    good = FILES["Regional sales.xlsx"]
    src_zip = zipfile.ZipFile(io.BytesIO(good))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for info in src_zip.infolist():
            data = src_zip.read(info.filename)
            if info.filename == "xl/sharedStrings.xml":
                data = data.replace(b"<sst", b'<!DOCTYPE x [<!ENTITY a "aaaa">]><sst', 1)
            if info.filename.startswith("xl/worksheets/"):
                data = data.replace(b"<worksheet", b'<!DOCTYPE x [<!ENTITY a "b">]><worksheet', 1)
            z.writestr(info, data)
    r = env.client.post("/api/documents/import-office",
                        files={"file": ("hostile.xlsx", out.getvalue(), "")})
    assert r.status_code == 422 and r.json()["detail"] == NO_EXTRACTABLE_TEXT, r.text

    monkeypatch.setattr(ox, "PART_LIMIT", 200)
    (tmp_path / "big.docx").write_bytes(FILES["Board minutes.docx"])
    assert ox.docx_markdown(str(tmp_path / "big.docx")) is None
    (tmp_path / "big.xlsx").write_bytes(good)
    assert ox.xlsx_text(str(tmp_path / "big.xlsx")) is None
