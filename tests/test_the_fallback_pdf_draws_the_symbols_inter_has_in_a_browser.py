# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1687` — a Latin document's ™, ↔, ▶, ❤ or ‼ is drawn in the fallback PDF,
in Inter, which has them; it was left out of the file.

*Print as PDF* prints the document in a frame (`B1333`); where the frame cannot
print, `_rasterisePdf` hands over a file drawn by jsPDF's `html()` (`B421`),
whose built-in fonts are Windows-1252. `B1674` embeds Inter for what they
cannot draw, fetched only when a document needs it — and `_pdfFontsNeeded`
decided that by script, skipping every `\\p{Extended_Pictographic}` character
as an emoji neither face draws. That property covers ™, ↔, ↕, ▶, ◀, ❤, ☀, ‼,
⁉ and ↩, and Inter-Regular.ttf draws every one of them (jsPDF's
`characterToGlyph` over its cmap). Measured on the tree before this row, in
Chromium: `Brand™` fetched no font, the file had a blank where `™` was, and
the sentence named it as a character the PDF cannot draw.

A second way to lose them stood behind the first: `markdown.js` draws every
`\\p{Extended_Pictographic}` character in prose — `©` and `®` among them — as a
monochrome icon, a `span.emoji` with no text, and the clone's plain styles draw
it as nothing. So `©` in prose was a blank in every fallback PDF, said to
nobody, because the built-in fonts have it.

Now the decision is the font's own (`static/js/pdfFontCoverage.js`, read out of
the vendored file by the vendored jsPDF, `scripts/build-pdf-font-coverage.mjs`),
and an icon whose character a font of the file draws is that character again in
html2canvas's clone (`_pdfFontRuns`).

The `Verify:` is driven against the running app the way
`tests/test_the_fallback_pdf_leaves_out_what_it_cannot_draw_in_a_browser.py`
drives `B1685`: two Latin documents are exported with the print frame made
unwritable, every request for `static/lib/pdf-fonts/` is counted, and each
file's text layer is read with `pypdf`. Skips, with the reason, where node,
Playwright or Chromium is absent. The table's freshness and the decision for
each character the row names are asked under node alone, beside it.
"""

import json
import re
import string
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402
from test_vendored_libraries_still_work import run_harness

ROOT = Path(__file__).resolve().parents[1]
needs_browser = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

INTER = ["Inter-Bold.ttf", "Inter-BoldItalic.ttf", "Inter-Italic.ttf", "Inter-Regular.ttf"]
#: The characters the row names that Inter draws, and the two it does not.
DRAWN_BY_INTER = "™↔↕▶◀❤☀‼⁉↩"
NOT_IN_INTER = "✔⌚"

#: A Latin document, but for the row's symbols: in a heading, in prose (where
#: `markdown.js` makes each an icon), in inline code and in a code block (where
#: it does not). `✔` is the one Inter lacks: it is what the sentence still
#: names, with a private-use code point (a Powerline arrow pasted from a
#: terminal), which Inter maps to a glyph of its own that is not the author's.
#: Nothing else in it is outside Windows-1252, so before this row it fetched
#: no face at all.
PRIVATE = "\ue0a0"
SYMBOLS = "\n".join([
    "# Brand™ SYMHEAD",
    "",
    "Prose: Brand™ PROSETM, A ↔ B PROSEARROW, ▶ PROSEPLAY, I ❤ it PROSEHEART, ‼ PROSEBANG.",
    "",
    "Copyright © PROSECOPY.",
    "",
    f"Inline code `x™y` INLINETM, a check ✔ PROSECHECK and a branch {PRIVATE} PROSEPUA.",
    "",
    "```",
    "# CODEPROBE ™ ↔ ▶",
    "```",
])
#: `❤️` typed the way an emoji keyboard types it, with U+FE0F after it. Before
#: this row the selector alone fetched Inter (it is `Script=Inherited`, and not
#: `Extended_Pictographic`), the heart in prose was still a blank, and the
#: sentence named the selector — an invisible character — as one the PDF
#: cannot draw.
HEART = "\n".join([
    "# Heart HEARTHEAD",
    "",
    "I ❤\ufe0f it PROSEHEART.",
    "",
    "```",
    "love = '❤\ufe0f'  # CODEHEART",
    "```",
])
#: Latin with nothing Inter draws that the built-in fonts do not: it fetches no
#: face. `©` is drawn by the built-in font.
NO_FACE = "\n".join([
    "# Nothing for Inter NOFACEHEAD",
    "",
    "Done ✔ CHECKPROBE, an emoji 🎉 EMOJIPROBE, and © NOFACECOPY.",
    "",
    "```",
    "ok ✔ CODECHECK",
    "```",
])

_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, OUT_DIR, DOCS] = [process.argv[2], process.argv[3], JSON.parse(process.argv[4])];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, acceptDownloads: true });
  const creds = { username: 'symbols', password: 'symbols-pass-1' };
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
    d = tmp_path_factory.mktemp("symbols-pdf")
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    docs = [{"title": "Symbols in Inter", "content": SYMBOLS, "file": "symbols.pdf"},
            {"title": "A heart", "content": HEART, "file": "heart.pdf"},
            {"title": "Nothing for Inter", "content": NO_FACE, "file": "noface.pdf"}]
    proc = subprocess.run([NODE, str(script), app_url, str(d), json.dumps(docs)],
                          capture_output=True, text=True, timeout=600, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    import pypdf
    for doc, result in zip(docs, out["exports"]):
        assert result["downloadedName"] == doc["title"] + "_v1.pdf", (result, out["errors"])
        result["reader"] = pypdf.PdfReader(str(d / doc["file"]))
        result["source"] = doc["content"]
    out["symbols"], out["heart"], out["noface"] = out["exports"]
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
    """The file's text as it reads on the page. Each text-showing operation is
    put on the line its baseline is on (within 2 pt: a run in Inter beside one
    in Courier sits a fraction of a point off it) and in order across that
    line — html2canvas paints an inline element's text after the line around
    it, so `x™y` in inline code is drawn `x`, `y`, then `™` between them."""
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


def _named(result) -> str:
    """What the export's sentence names, or `''` when it said nothing."""
    toasts = " ".join(result["toasts"])
    return toasts.split("can't draw", 1)[1].split(",", 1)[0] if "can't draw" in toasts else ""


# ── the Verify: ™ and ↔ fetch Inter, are in the file, and are not named ─────

@needs_browser
def test_a_latin_document_with_the_symbols_fetches_inter(drive):
    """Before: no request at all — the document was drawn in the built-in
    fonts alone. Inter's four faces, and not the CJK one."""
    assert sorted(set(drive["symbols"]["fonts"])) == INTER, drive["symbols"]["fonts"]


@needs_browser
def test_its_text_layer_carries_every_symbol_where_it_was_typed(drive):
    """`™` in the heading, in prose (an icon on the page), in inline code and
    in the code block; `↔` and `▶` in prose and in the code block; `❤`, `‼`
    and `©` in prose. Before: none of them — each was a blank."""
    drawn = _drawn(drive["symbols"])
    for ch, times in (("™", 4), ("↔", 2), ("▶", 2), ("❤", 1), ("‼", 1), ("©", 1)):
        assert drawn.count(ch) == times, (ch, drawn.count(ch), drawn)
    text = _text(drive["symbols"])
    for pattern in (r"Brand\s*™\s*SYMHEAD", r"Brand\s*™\s*PROSETM", r"A\s*↔\s*B PROSEARROW",
                    r"▶\s*PROSEPLAY", r"I\s*❤\s*it PROSEHEART", r"‼\s*PROSEBANG",
                    r"Copyright\s*©\s*PROSECOPY", r"x\s*™\s*y\s*INLINETM", r"branch\s*PROSEPUA",
                    r"# CODEPROBE\s*™\s*↔\s*▶"):
        assert re.search(pattern, text), (pattern, text)


@needs_browser
def test_each_symbol_is_drawn_in_inter(drive):
    """A built-in font would write any of them as UTF-16 bytes (`B1685`): each
    is in a run of the embedded face, in the code block's Courier line too."""
    runs = [(text, font) for text, font in _runs(drive["symbols"]["reader"]) if set(text) & set("™↔▶❤‼")]
    assert runs and all(font == "/pantheonpdfsans" for _, font in runs), runs


@needs_browser
def test_the_sentence_names_none_of_them(drive):
    """Only `✔`, which Inter lacks, and the private-use character are named —
    not `™`, not `↔`. Before: all of them."""
    named = _named(drive["symbols"])
    assert set(named.split()) == {"✔", PRIVATE}, (named, drive["symbols"]["toasts"])
    assert "left out of the file" in " ".join(drive["symbols"]["toasts"])


@needs_browser
def test_a_heart_with_its_variation_selector_is_drawn_and_nothing_is_named(drive):
    """`❤️`: Inter fetched, the heart drawn in prose and in code, and no
    sentence — the selector after it only chooses how the heart is drawn, and
    nobody can be told about a character they cannot see. Before: the heart
    in prose was a blank and the sentence named U+FE0F."""
    heart = drive["heart"]
    assert sorted(set(heart["fonts"])) == INTER, heart["fonts"]
    drawn = _drawn(heart)
    assert drawn.count("❤") == 2, drawn
    text = _text(heart)
    assert re.search(r"I\s*❤\s*it PROSEHEART", text) and re.search(r"'\s*❤\s*'\s*# CODEHEART", text), text
    assert not any("can't draw" in t for t in heart["toasts"]), heart["toasts"]


@needs_browser
def test_nothing_reaches_the_file_as_noise(drive):
    """`B1685`'s rule holds: every character drawn is one the document has, and
    the one no face draws is a blank."""
    for which in ("symbols", "heart", "noface"):
        result = drive[which]
        drawn = _drawn(result)
        noise = set(drawn) - set(result["source"]) - set(string.printable)
        assert not noise, (which, sorted(noise))
        assert not set(drawn) & {"✔", "\ufe0f", PRIVATE}, (which, drawn)


# ── and a document with nothing for Inter still fetches nothing ─────────────

@needs_browser
def test_a_document_whose_symbols_inter_lacks_fetches_no_face(drive):
    """The decision is Inter's own table, not "any symbol": `✔` and `🎉` are
    drawn by no face, so none is fetched, and both are named. `©` — an icon in
    prose — is drawn by the built-in font; before, it was a blank said to
    nobody."""
    noface = drive["noface"]
    assert noface["fonts"] == [], noface["fonts"]
    named = _named(noface)
    assert "✔" in named and "🎉" in named and "©" not in named, (named, noface["toasts"])
    assert re.search(r"©\s*NOFACECOPY", _text(noface)), _text(noface)


@needs_browser
def test_the_exports_finished_with_no_error(drive):
    assert drive["errors"] == [], drive["errors"]
    for which in ("symbols", "heart", "noface"):
        assert not any("failed" in t for t in drive[which]["toasts"]), drive[which]["toasts"]


# ── under node: the table is the font's, and the decision is the table's ────

def test_the_table_is_what_jspdf_reads_from_the_vendored_inter():
    """`static/js/pdfFontCoverage.js` is written by
    `scripts/build-pdf-font-coverage.mjs` from the vendored face, read by the
    vendored jsPDF. Its `--check` writes nothing and fails on a table that is
    not what the file draws now — a bumped Inter with the table left behind."""
    proc = subprocess.run(["node", "scripts/build-pdf-font-coverage.mjs", "--check"], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_check_fails_on_a_table_that_is_not_the_fonts(tmp_path):
    """The check is a check: a table one character short of the font's is
    refused, and the sentence says what to run."""
    table = (ROOT / "static/js/pdfFontCoverage.js").read_text(encoding="utf-8")
    assert '"20-7e"' in table, "printable ASCII is one range of Inter's"
    stale = tmp_path / "pdfFontCoverage.js"
    stale.write_text(table.replace('"20-7e"', '"20-7d"', 1), encoding="utf-8")
    proc = subprocess.run(["node", "scripts/build-pdf-font-coverage.mjs", "--check", "--out", str(stale)],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "run `node scripts/build-pdf-font-coverage.mjs`" in proc.stdout, proc.stdout + proc.stderr
    assert stale.read_text(encoding="utf-8") != table, "--check writes nothing"


def test_each_symbol_the_row_names_is_decided_by_inters_own_table():
    """The real `_pdfFontsNeeded`, lifted out of `document.js` by
    `tests/harness/jspdf_export_chain.js` with the real table beside it. Every
    symbol the row names that Inter draws fetches Inter (before: none did);
    `✔` and `⌚`, which it lacks, fetch nothing — and neither do an emoji past
    U+FFFF or Hebrew, nor the box-drawing `─` and the variation selector U+FE0F,
    which the old rule fetched Inter for and Inter lacks, nor a private-use
    code point (a Powerline arrow), which Inter maps to a glyph of its own.
    The scripts `B1674` named are decided as before.

    `B1691` added a third face, the symbols face, so the answer has a third
    key; and `─`, which Inter lacks, now fetches that face rather than nothing
    (`tests/test_the_fallback_pdf_draws_a_pasted_tree_listing_in_a_browser.py`)
    — still not Inter."""
    chain = run_harness("jspdf_export_chain.js")
    assert chain["ok"], chain
    needs = chain["needs"]
    nothing = {"sans": False, "symbols": False, "cjk": False}
    for ch in DRAWN_BY_INTER:
        assert needs[ch] == {**nothing, "sans": True}, (ch, needs[ch])
    for ch in NOT_IN_INTER + "🎉" + "\ufe0f\ue0a0":
        assert needs[ch] == nothing, (ch, needs[ch])
    assert needs["─"] == {**nothing, "symbols": True}, needs["─"]
    assert needs["שלום"] == nothing, needs["שלום"]
    assert needs["Привет"] == {**nothing, "sans": True}, needs["Привет"]
    assert needs["Γειά"] == {**nothing, "sans": True}, needs["Γειά"]
    assert needs["你好"] == {**nothing, "cjk": True}, needs["你好"]
    assert needs["café “naïve” — €"] == nothing, needs["café “naïve” — €"]
