# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1691` — a Latin document's box-drawing, block, maths and dingbat
characters are drawn in the fallback PDF, from a 73 KB face of their own; a
pasted `tree` listing lost every connector.

*Print as PDF* prints the document in a frame (`B1333`); where the frame cannot
print, `_rasterisePdf` hands over a file drawn by jsPDF's `html()` (`B421`),
whose built-in fonts are Windows-1252. `B1674` embeds Inter for Latin, Greek
and Cyrillic and a Noto Sans CJK SC subset for Chinese, Japanese and Korean,
the CJK face fetched by block (`_PDF_CJK`) and Inter by its own table (`B1687`).
`├ ─ └ │`, `█ ▁`, `∀ ∈ ≡ ⊂`, `ⓐ ⑴` and `☎ ♠ ♣` are in neither Inter nor those
blocks, so a document with them fetched no face, left a blank where each was,
and named them in the export's sentence — 295 characters the 6.4 MB CJK face
draws (measured with the vendored jsPDF, below). The CJK face is not fetched
for a `─`: `scripts/build-pdf-cjk-font.py` cuts a second face from the same
pinned source, `NotoSansCJKsc-Symbols.subset.ttf`, holding the 532 characters
of it outside `_PDF_CJK`'s blocks that neither Windows-1252 nor Inter draws,
and the export decides on it by its own table, as it does on Inter.

The `Verify:` is driven against the running app the way
`tests/test_the_fallback_pdf_draws_the_symbols_inter_has_in_a_browser.py`
drives `B1687`: a Latin document with a pasted `tree` listing in a code block,
and one with the same connectors beside Chinese, are exported with the print
frame made unwritable, every request for `static/lib/pdf-fonts/` is counted,
and each file's text layer is read with `pypdf`. Skips, with the reason, where
node, Playwright or Chromium is absent. What the decision is for every
character the CJK face draws, and what the symbols face holds, are asked under
node alone, beside it.
"""

import json
import re
import string
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402
from test_vendored_libraries_still_work import run_harness

needs_browser = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

SYMBOLS_FACE = "NotoSansCJKsc-Symbols.subset.ttf"
CJK_FACE = "NotoSansCJKsc-Regular.subset.ttf"
SYMBOLS_FONT = "/pantheonpdfsymbols"
#: Every character the row names.
ROW = "├─└│█▁∀∈≡⊂ⓐ⑴☎♠♣"

#: A `tree` listing pasted into a code block, as `tree` prints it.
TREE = "\n".join([
    ".",
    "├── app.py",
    "├── static",
    "│   ├── js",
    "│   │   └── document.js",
    "│   └── style.css",
    "└── tests TREEEND",
])
#: A Latin document, but for the row's characters: the listing, blocks and
#: maths in prose, enclosed numbers, and dingbats — `☎ ♠ ♣`, which
#: `markdown.js` draws in prose as icons — and a double-line frame in inline
#: code and in a code block, which the CJK face does not carry either. Nothing
#: in it is drawn by Inter, so the symbols face is the one face it needs.
LATIN = "\n".join([
    "# Project layout TREEHEAD",
    "",
    "```",
    TREE,
    "```",
    "",
    "Blocks ▁▂▃▅▇█ SPARKPROBE, maths ∀x ∈ A, a ≡ b, A ⊂ B MATHPROBE.",
    "",
    "Enclosed ⓐ ⑴ ❶ ENCPROBE, a phone ☎ and suits ♠ ♣ PROSEDING.",
    "",
    "Inline code `╔═╗` INLINEBOX and a frame:",
    "",
    "```",
    "╔══╗",
    "║ok║ FRAMEPROBE",
    "╚══╝",
    "```",
])
#: The same connectors beside Chinese: the CJK face is fetched for the
#: Chinese, and the connectors are still drawn from the symbols face — the
#: same glyphs as in a Latin document — with `║`, which the CJK face lacks.
BESIDE_CJK = "\n".join([
    "# 目录 CJKHEAD",
    "",
    "```",
    "├── 你好.txt CJKTREE",
    "└── ║ BOXPROBE",
    "```",
])

_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, OUT_DIR, DOCS] = [process.argv[2], process.argv[3], JSON.parse(process.argv[4])];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, acceptDownloads: true });
  const creds = { username: 'treelisting', password: 'treelisting-pass-1' };
  await ctx.request.post(BASE + '/api/auth/setup', { data: creds });
  await ctx.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const page = await ctx.newPage();
  const out = { errors: [], exports: [] };
  let fonts = [];
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  page.on('request', (r) => {
    const u = r.url();
    if (u.includes('/static/lib/pdf-fonts/')) fonts.push(u.split('/').pop().split('?')[0]);
  });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    const desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentDocument');
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentDocument', {
      configurable: true,
      get() { return this.id === 'doc-print-frame' ? null : desc.get.call(this); },
    });
  });

  for (const { title, content, file } of DOCS) {
    fonts = [];
    const id = (await (await page.request.post(BASE + '/api/document',
      { data: { title, language: 'markdown', content } })).json()).id;
    await page.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, id);
    await page.waitForFunction((id) => !!document.querySelector(`.doc-tab.active[data-doc-id="${id}"]`),
      id, { timeout: 30000 });
    await page.waitForTimeout(800);
    await page.evaluate(() => { const t = document.getElementById('toast'); if (t) t.textContent = ''; });
    let downloaded = null;
    const onDownload = (d) => { downloaded = d; };
    page.on('download', onDownload);
    await page.click('#doc-footer-export-btn');
    await page.waitForTimeout(400);
    await page.evaluate(() => {
      const item = [...document.querySelectorAll('#doc-export-menu .doc-overflow-item')]
        .find((b) => b.textContent === 'Print as PDF');
      if (item) item.click();
    });
    for (let i = 0; i < 480 && !downloaded; i++) await page.waitForTimeout(250);
    page.off('download', onDownload);
    await page.waitForTimeout(500);
    const result = { title, downloadedName: downloaded ? downloaded.suggestedFilename() : null,
      fonts: [...fonts] };
    if (downloaded) await downloaded.saveAs(`${OUT_DIR}/${file}`);
    result.toasts = await page.evaluate(() => [...document.querySelectorAll('.toast, .toast-error, [role="alert"]')]
      .map((n) => n.textContent.trim()).filter(Boolean));
    out.exports.push(result);
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("tree-pdf")
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    docs = [{"title": "A tree listing", "content": LATIN, "file": "tree.pdf"},
            {"title": "Beside Chinese", "content": BESIDE_CJK, "file": "cjk.pdf"}]
    proc = subprocess.run([NODE, str(script), app_url, str(d), json.dumps(docs)],
                          capture_output=True, text=True, timeout=600, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    import pypdf
    for doc, result in zip(docs, out["exports"]):
        assert result["downloadedName"] == doc["title"] + "_v1.pdf", (result, out["errors"])
        result["reader"] = pypdf.PdfReader(str(d / doc["file"]))
        result["size"] = (d / doc["file"]).stat().st_size
        result["source"] = doc["content"]
    out["latin"], out["cjk"] = out["exports"]
    return out


def _runs(reader) -> list[tuple[str, str]]:
    """Each text-showing operation's text and the `/BaseFont` it is drawn in."""
    found = []
    for page in reader.pages:
        page.extract_text(visitor_text=lambda text, cm, tm, font, size:
                          found.append((text, str((font or {}).get("/BaseFont")))))
    return found


def _drawn(result) -> str:
    return "".join(text for text, _ in _runs(result["reader"]))


def _text(result) -> str:
    """The file's text as it reads on the page: each text-showing operation on
    the line its baseline is on (within 2 pt — a run in one face beside one in
    Courier sits a fraction of a point off it), in order across that line."""
    runs = []
    for i, page in enumerate(result["reader"].pages):
        def visit(text, cm, tm, font, size, i=i):
            if text.strip():
                runs.append((i, tm[5] * cm[3] + cm[5], tm[4] * cm[0] + cm[4], text))
        page.extract_text(visitor_text=visit)
    lines = []
    for page, y, x, text in sorted(runs, key=lambda r: (r[0], -r[1], r[2])):
        if lines and lines[-1][0] == page and abs(lines[-1][1] - y) < 2:
            lines[-1][2].append((x, text))
        else:
            lines.append([page, y, [(x, text)]])
    return "\n".join(" ".join(text for _, text in sorted(parts)) for _, _, parts in lines)


def _reads(text: str, phrase: str) -> bool:
    """Whether one line of `text` holds `phrase`'s characters in order.
    html2canvas draws a code block a character or a word at a time, so the
    runs `_text` sets on a line have spaces between them (`├ ─ ─ app . py`)."""
    pattern = r"[ \t]*".join(re.escape(ch) for ch in phrase if not ch.isspace())
    return re.search(pattern, text) is not None


def _embedded_fonts(reader) -> set[str]:
    names = set()
    for page in reader.pages:
        for ref in ((page.get("/Resources") or {}).get("/Font") or {}).values():
            font = ref.get_object()
            if font.get("/Subtype") == "/Type0":
                names.add(str(font["/BaseFont"]))
    return names


# ── the Verify: the listing fetches a face, is in the file, is not named ────

@needs_browser
def test_a_latin_document_with_a_tree_listing_fetches_the_symbols_face_alone(drive):
    """Before: no request at all, and the CJK face (6.4 MB) is not what it
    fetches now — the symbols face, 73 KB, cut from the same source. (Asked
    for twice: by the export for jsPDF, and by the clone's `@font-face`.)"""
    assert sorted(set(drive["latin"]["fonts"])) == [SYMBOLS_FACE], drive["latin"]["fonts"]


@needs_browser
def test_its_text_layer_carries_the_listing_where_it_was_typed(drive):
    """Every connector of the listing, on its own line beside its name, and
    the row's blocks, maths, enclosed numbers and dingbats (the dingbats are
    icons in prose, given back their character). Before: each was a blank."""
    drawn = _drawn(drive["latin"])
    for ch, times in (("├", 3), ("└", 3), ("│", 4), ("─", 12), ("█", 1), ("∀", 1), ("ⓐ", 1),
                      ("⑴", 1), ("☎", 1), ("♠", 1), ("♣", 1), ("║", 2), ("╔", 2), ("═", 5)):
        assert drawn.count(ch) == times, (ch, drawn.count(ch), drawn)
    text = _text(drive["latin"])
    for phrase in ("├── app.py", "├── static", "│ ├── js", "│ │ └── document.js", "│ └── style.css",
                   "└── tests TREEEND", "▁▂▃▅▇█ SPARKPROBE", "∀x ∈ A, a ≡ b, A ⊂ B MATHPROBE",
                   "ⓐ ⑴ ❶ ENCPROBE", "phone ☎ and suits ♠ ♣ PROSEDING", "╔═╗ INLINEBOX",
                   "╔══╗", "║ok║ FRAMEPROBE", "╚══╝"):
        assert _reads(text, phrase), (phrase, text)


@needs_browser
def test_each_of_them_is_drawn_from_the_symbols_face(drive):
    """A built-in font would write any of them as UTF-16 bytes (`B1685`): each
    is in a run of the symbols face, in the code block's Courier lines too."""
    runs = [(text, font) for text, font in _runs(drive["latin"]["reader"]) if set(text) & set(ROW + "╔║═❶")]
    assert runs and all(font == SYMBOLS_FONT for _, font in runs), runs


@needs_browser
def test_the_sentence_names_none_of_them(drive):
    """Nothing in the document is left out, so nothing is said. Before:
    `Saved — but this PDF can't draw ├ ─ │ └ ▁ ▂ ▃ ▅ …`."""
    assert not any("can't draw" in t for t in drive["latin"]["toasts"]), drive["latin"]["toasts"]


@needs_browser
def test_only_the_symbols_face_is_in_the_file(drive):
    """jsPDF writes only the faces the file draws with and only their glyphs:
    the symbols face, and a file far smaller than the 6.4 MB face would have
    made it."""
    assert _embedded_fonts(drive["latin"]["reader"]) == {SYMBOLS_FONT}
    assert drive["latin"]["size"] < 150_000, drive["latin"]["size"]


# ── beside Chinese, the same face draws them ────────────────────────────────

@needs_browser
def test_beside_chinese_the_connectors_come_from_the_symbols_face_too(drive):
    """The CJK face is fetched for `你好` and draws it; the connectors are
    drawn from the symbols face, which comes first, so a `─` looks the same
    whatever else the document holds — and `║`, which the CJK face lacks, is
    drawn too. Before: `║` was a blank and named, with the CJK face loaded."""
    cjk = drive["cjk"]
    assert sorted(set(cjk["fonts"])) == [CJK_FACE, SYMBOLS_FACE], cjk["fonts"]
    runs = _runs(cjk["reader"])
    for ch in "├└─║":
        fonts = {font for text, font in runs if ch in text}
        assert fonts == {SYMBOLS_FONT}, (ch, fonts, runs)
    assert {font for text, font in runs if "你好" in text} == {"/pantheonpdfcjk"}, runs
    text = _text(cjk)
    assert _reads(text, "├── 你好.txt CJKTREE") and _reads(text, "└── ║ BOXPROBE"), text
    assert not any("can't draw" in t for t in cjk["toasts"]), cjk["toasts"]


@needs_browser
def test_nothing_reaches_the_file_as_noise(drive):
    """`B1685`'s rule holds: every character drawn is one the document has."""
    for which in ("latin", "cjk"):
        result = drive[which]
        noise = set(_drawn(result)) - set(result["source"]) - set(string.printable)
        assert not noise, (which, sorted(noise))


@needs_browser
def test_the_exports_finished_with_no_error(drive):
    assert drive["errors"] == [], drive["errors"]
    for which in ("latin", "cjk"):
        assert not any("failed" in t for t in drive[which]["toasts"]), drive[which]["toasts"]


# ── under node: what is fetched for what ────────────────────────────────────

@pytest.fixture(scope="module")
def chain():
    out = run_harness("jspdf_export_chain.js")
    assert out["ok"], out
    return out


def test_every_character_the_row_names_fetches_the_symbols_face_and_not_the_cjk_one(chain):
    """The real `_pdfFontsNeeded`, lifted out of `document.js` by
    `tests/harness/jspdf_export_chain.js` with the real tables beside it.
    Before: none of them fetched anything. `╔` and `║` are in the symbols face
    and not in the CJK one."""
    for ch in ROW + "╔║":
        assert chain["needs"][ch] == {"sans": False, "symbols": True, "cjk": False}, (ch, chain["needs"][ch])
    assert chain["needs"]["├── 你好"] == {"sans": False, "symbols": True, "cjk": True}


def test_no_character_the_cjk_face_draws_is_left_without_a_face(chain):
    """Every character of `NotoSansCJKsc-Regular.subset.ttf`, read by the
    vendored jsPDF: one the built-in fonts cannot draw is fetched a face for.
    Before: 295 were not — the row's count, every one outside `_PDF_CJK`'s
    blocks and drawn by neither Windows-1252 nor Inter."""
    assert chain["cjkFaceCharacters"] == 20498, chain["cjkFaceCharacters"]
    assert chain["cjkOrphans"] == [], "".join(chain["cjkOrphans"])


def test_the_symbols_face_holds_only_what_nothing_else_draws(chain):
    """Each of its 532 characters, alone, fetches it and no other face: none
    is in `_PDF_CJK`'s blocks, in Windows-1252 or in Inter — read from its own
    table, which `node scripts/build-pdf-font-coverage.mjs --check` holds to
    the vendored file (`tests/test_the_fallback_pdf_draws_the_symbols_inter_has_in_a_browser.py`)."""
    assert chain["symbolsFaceCharacters"] == 532, chain["symbolsFaceCharacters"]
    assert chain["symbolsFaceElsewhere"] == [], "".join(chain["symbolsFaceElsewhere"])
