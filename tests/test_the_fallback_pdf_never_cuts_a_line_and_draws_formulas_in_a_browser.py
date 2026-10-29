# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1675` and `B1676` — the fallback PDF draws a formula the way KaTeX lays it
out, and never cuts a line of text in half at a page edge.

*Print as PDF* prints the document in a frame (`B1333`); where the frame cannot
print, `_rasterisePdf` hands over a file drawn by jsPDF's own `html()`
(`B421`), from a clone of the export that html2canvas lays out. Two things were
wrong with that file, both measured here in Chromium on the tree before these
rows:

  * `B1675`. `B1322` strips every stylesheet from the clone, KaTeX's with the
    page's, so `$x^2$` came out as *x2* — the `2` at full size on x's baseline,
    after a gap where the browser laid out the MathML copy KaTeX's sheet hides —
    and a display formula was drawn twice, once flat and once by the browser's
    own MathML. The clone now keeps KaTeX's sheet (it names no colour the
    rasteriser cannot read, which is what `B1322` was about) and drops the
    MathML copy.
  * `B1676`. `autoPaging: true` slices the drawing at each page edge, so a line
    lying across one was drawn on both pages, clipped: half a line closing one
    page, the other half opening the next, and the clipped-off copy left in the
    file's text. `_keepLinesOffPageEdges` now lays the clone out with every
    line clear of the edges before anything is measured, and the links are
    measured in that layout.

Driven against the running app (`tests/test_the_command_palette_in_a_browser.py`'s
`app_url`), the way
`tests/test_the_fallback_pdf_is_jspdfs_own_with_its_links_in_a_browser.py`
drives `B421`: a markdown document long enough for several pages — a wrapped
paragraph, a code block, a list, a table and paragraphs, with a link in each —
is exported with the print frame made unwritable, and the file is read with
`pypdf`. Skips, with the reason, where node, Playwright or Chromium is absent.
"""

import collections
import json
import re
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

# A4 in points, and the export's 10 mm margin (`PDF_MARGIN_MM`).
MARGIN_PT = 10 * 72 / 25.4

WRAP_WORDS = 160
CODE_LINES = 50
LIST_ITEMS = 30
TABLE_ROWS = 20
ROWS = 60

_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, PDF_PATH, SIZES] = [process.argv[2], process.argv[3], JSON.parse(process.argv[4])];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, acceptDownloads: true });
  const creds = { username: 'edges', password: 'edges-pass-1' };
  await ctx.request.post(BASE + '/api/auth/setup', { data: creds });
  await ctx.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const page = await ctx.newPage();
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);

  const words = [];
  for (let i = 1; i <= SIZES.wrap; i++) {
    words.push(i % 9 === 0 ? `[WRAPLINK${i}](https://example.org/w${i})` : `wrapword${i}`);
  }
  const code = [];
  for (let i = 1; i <= SIZES.code; i++) code.push(`codeline_${i} = ${i}  # CODEPROBE${i}`);
  const items = [];
  for (let i = 1; i <= SIZES.list; i++) items.push(`- LISTPROBE${i} has [LISTLINK${i}](https://example.com/l${i}) in it`);
  const table = ['| cell | link |', '| --- | --- |'];
  for (let i = 1; i <= SIZES.table; i++) table.push(`| TABLEPROBE${i} | [TABLELINK${i}](https://example.com/t${i}) |`);
  const rows = [];
  for (let i = 1; i <= SIZES.rows; i++) {
    rows.push(`Line ${i}: the ferry timetable WORDPROBE${i} lists [ROWLINK${i}](https://example.com/r${i}) departures.\n`);
  }
  const content = [
    '# Edge probe',
    '',
    'The square $x^2$ SUPPROBE sits in this line.',
    '',
    '$$q^2 + w^2 = z^2$$',
    '',
    words.join(' '),
    '',
    '```python', ...code, '```',
    '',
    ...items,
    '',
    ...table,
    '',
    ...rows,
  ].join('\n');
  const id = (await (await page.request.post(BASE + '/api/document',
    { data: { title: 'Edge probe', language: 'markdown', content } })).json()).id;
  await page.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, id);
  await page.waitForFunction((id) => !!document.querySelector(`.doc-tab.active[data-doc-id="${id}"]`),
    id, { timeout: 30000 });
  await page.waitForTimeout(800);

  // The browser this path is for: the print frame cannot be written, so
  // `printHtmlInFrame` answers `false` and the export falls back.
  await page.evaluate(() => {
    const desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentDocument');
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentDocument', {
      configurable: true,
      get() { return this.id === 'doc-print-frame' ? null : desc.get.call(this); },
    });
  });
  let downloaded = null;
  page.on('download', async (d) => { downloaded = d; });
  await page.click('#doc-footer-export-btn');
  await page.waitForTimeout(400);
  await page.evaluate(() => {
    const item = [...document.querySelectorAll('#doc-export-menu .doc-overflow-item')]
      .find((b) => b.textContent === 'Print as PDF');
    if (item) item.click();
  });
  const t0 = Date.now();
  for (let i = 0; i < 480 && !downloaded; i++) await page.waitForTimeout(250);
  out.seconds = (Date.now() - t0) / 1000;
  out.downloadedName = downloaded ? downloaded.suggestedFilename() : null;
  if (downloaded) await downloaded.saveAs(PDF_PATH);
  out.toasts = await page.evaluate(() => [...document.querySelectorAll('.toast, .toast-error, [role="alert"]')]
    .map((n) => n.textContent.trim()).filter(Boolean));
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("edge-pdf")
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    pdf = d / "edges.pdf"
    sizes = {"wrap": WRAP_WORDS, "code": CODE_LINES, "list": LIST_ITEMS, "table": TABLE_ROWS,
             "rows": ROWS}
    proc = subprocess.run([NODE, str(script), app_url, str(pdf), json.dumps(sizes)],
                          capture_output=True, text=True, timeout=480, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["downloadedName"] == "Edge probe_v1.pdf", out
    import pypdf
    out["reader"] = pypdf.PdfReader(str(pdf))
    return out


class Run(collections.namedtuple("Run", "page x y size font text")):
    """One text-showing operation: its page, its start and baseline in PDF
    points (y up), its size in points, its font, and its text."""


def _runs(reader) -> list[Run]:
    found = []
    for i, page in enumerate(reader.pages):
        def visit(text, cm, tm, font, size, i=i):
            if text.strip():
                found.append(Run(i, tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5],
                                 size * tm[3] * cm[3], (font or {}).get("/BaseFont"), text.strip()))
        page.extract_text(visitor_text=visit)
    return found


def _links(reader):
    """Every link annotation: (page index, (x0, y0, x1, y1), uri)."""
    found = []
    for i, page in enumerate(reader.pages):
        for ref in page.get("/Annots") or []:
            a = ref.get_object()
            if a.get("/Subtype") == "/Link" and "/A" in a:
                r = [float(v) for v in a["/Rect"]]
                x0, x1 = sorted(r[0::2])
                y0, y1 = sorted(r[1::2])
                found.append((i, (x0, y0, x1, y1), str(a["/A"].get("/URI"))))
    return found


# ── `B1675`: KaTeX's layout reaches the file ────────────────────────────────

def test_katexs_sheet_names_no_colour_the_rasteriser_cannot_read():
    """`B1322`'s reason for stripping the page's sheets is a colour syntax
    html2canvas 1.4.1 throws on. The clone keeps KaTeX's sheet on the strength
    of it naming none, so a KaTeX bump that brings one in fails here, by the
    export's own list of what the parser cannot read (`_PDF_UNREADABLE_COLOUR`),
    before it fails a person's export."""
    source = (ROOT / "static/js/document.js").read_text(encoding="utf-8")
    m = re.search(r"const _PDF_UNREADABLE_COLOUR = /(.+)/i;", source)
    assert m, "_PDF_UNREADABLE_COLOUR moved; this test reads the export's own list"
    unreadable = re.compile(m.group(1), re.I)
    css = (ROOT / "static/lib/katex/katex.min.css").read_text(encoding="utf-8")
    assert not unreadable.findall(css), unreadable.findall(css)


def test_an_exponent_is_drawn_raised_and_smaller_beside_its_base(drive):
    """`B1675`'s `Verify:`. Before: `x` and `2` on one baseline at one size."""
    runs = _runs(drive["reader"])
    (probe,) = [r for r in runs if r.text == "SUPPROBE"]
    line = [r for r in runs if r.page == probe.page and r.x < probe.x]
    bases = [r for r in line if r.text == "x" and abs(r.y - probe.y) < 1]
    assert len(bases) == 1, [r for r in line if abs(r.y - probe.y) < 15]
    x = bases[0]
    sups = [r for r in line if r.text == "2" and x.x < r.x < probe.x]
    assert len(sups) == 1, (x, [r for r in line if abs(r.y - probe.y) < 15])
    two = sups[0]
    assert two.y - x.y >= 0.25 * x.size, ("the exponent sits on the base's baseline", x, two)
    assert two.size <= 0.8 * x.size, ("the exponent is drawn at the base's size", x, two)
    assert two.x - x.x < 1.5 * x.size, ("a gap opens between the base and its exponent", x, two)


def test_a_display_formula_is_drawn_once_with_its_exponents_raised(drive):
    """Before: drawn twice — flat by the unstyled HTML, and again by the
    browser's own MathML, which KaTeX's sheet hides. With the sheet and
    without the MathML copy, once, typeset."""
    runs = _runs(drive["reader"])
    zs = [r for r in runs if r.text == "z"]
    assert len(zs) == 1, zs
    z = zs[0]
    raised = [r for r in runs if r.page == z.page and r.text == "2" and 0 < r.x - z.x < 1.5 * z.size]
    assert raised and raised[0].y - z.y >= 0.25 * z.size, (z, raised)
    assert len([r for r in runs if r.text == "q"]) == 1, "the formula's letters are in the file once"


# ── `B1676`: no line across a page edge ─────────────────────────────────────

def _words(runs, prefix):
    return [r for r in runs if re.fullmatch(prefix + r"\d+", r.text)]


def test_the_document_runs_over_several_pages(drive):
    """The rest of this file is only evidence if there are edges to cut."""
    assert len(drive["reader"].pages) >= 4, len(drive["reader"].pages)


def test_no_text_is_drawn_across_a_page_edge(drive):
    """`B1676`'s `Verify:`, first half. A run jsPDF drew across an edge is in
    the file twice, once on each page, and on each page part of it lies past
    the margin the page is clipped to. So every run's glyphs — a fifth of its
    size below the baseline, three quarters above, which holds the three
    built-in fonts' ascenders and descenders — lie inside its page's margins."""
    reader = drive["reader"]
    height = float(reader.pages[0].mediabox.height)
    cut = [r for r in _runs(reader)
           if r.y - 0.22 * r.size < MARGIN_PT - 0.5 or r.y + 0.75 * r.size > height - MARGIN_PT + 0.5]
    assert not cut, cut


def test_every_word_is_in_the_file_once(drive):
    """The other face of a cut line: its clipped-off copy stays in the text,
    so a search finds the word twice and a copy pastes it twice."""
    runs = _runs(drive["reader"])
    for prefix, n in (("WORDPROBE", ROWS), ("CODEPROBE", CODE_LINES), ("LISTPROBE", LIST_ITEMS),
                      ("TABLEPROBE", TABLE_ROWS), ("wrapword", WRAP_WORDS - WRAP_WORDS // 9)):
        seen = collections.Counter(r.text for r in _words(runs, prefix))
        assert len(seen) == n and set(seen.values()) == {1}, (prefix, seen)


def test_every_link_still_sits_over_its_words(drive):
    """`B1676`'s `Verify:`, second half. Lines moved down to clear an edge move
    every line after them; the links are measured in that layout, so each is
    on the page its word is on, starts where the word starts, and holds its
    baseline."""
    reader = drive["reader"]
    runs = _runs(reader)
    links = _links(reader)
    expected = ({f"https://example.org/w{i}" for i in range(9, WRAP_WORDS + 1, 9)}
                | {f"https://example.com/l{i}" for i in range(1, LIST_ITEMS + 1)}
                | {f"https://example.com/t{i}" for i in range(1, TABLE_ROWS + 1)}
                | {f"https://example.com/r{i}" for i in range(1, ROWS + 1)})
    assert sorted(u for _, _, u in links) == sorted(expected)
    words = {"w": "WRAPLINK", "l": "LISTLINK", "t": "TABLELINK", "r": "ROWLINK"}
    misplaced = []
    for page, (x0, y0, x1, y1), uri in links:
        kind, n = re.search(r"/([wltr])(\d+)$", uri).groups()
        (word,) = [r for r in runs if r.text == words[kind] + n]
        if not (word.page == page and abs(word.x - x0) < 1 and x1 > word.x and y0 <= word.y <= y1):
            misplaced.append((uri, (page, x0, y0, x1, y1), word))
    assert not misplaced, misplaced


def test_a_list_marker_stays_on_its_items_line(drive):
    """A line that opens its block moves the block, so what html2canvas draws
    from the block's own box — a list item's marker, a code block's
    background — goes with the words, not left behind on the page before."""
    runs = _runs(drive["reader"])
    markers = [r for r in runs if r.text == "•"]
    for item in _words(runs, "LISTPROBE"):
        assert any(m.page == item.page and abs(m.y - item.y) < 2 and m.x < item.x for m in markers), \
            (item, [m for m in markers if m.page == item.page])


def test_the_export_finished_with_no_error(drive):
    assert drive["errors"] == [], drive["errors"]
    assert not any("failed" in t for t in drive["toasts"]), drive["toasts"]
