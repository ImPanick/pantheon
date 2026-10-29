# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B421` — the fallback PDF is drawn by jsPDF's own `html()`, from three
published files, and a link in the document is a link in the file.

*Print as PDF* prints the document in a frame (`B1333`). Where the frame
cannot print, `_rasterisePdf` hands over a file instead, and until this row it
did that through `html2pdf.bundle.min.js` — one 946 KB bundle carrying jsPDF
4.0.0 and DOMPurify 3.3.1, twenty-seven open advisories between them, which
could move only when html2pdf.js published a rebuild. The owner's call
(`D-2026-10-29-02` §2): jsPDF 4.2.1's `html()`, with `html2canvas` 1.4.1 and
`DOMPurify` 3.4.17 beside it as their own published files.

Driven here, in Chromium, against the running app: a markdown document is
opened, the print frame is made unwritable (`contentDocument` answers `null`
for it — the case `printHtmlInFrame` returns `false` on), *Print as PDF* is
clicked, and the file that downloads is read with `pypdf`. What is measured:

  * the three libraries load in order and nothing else — the old bundle is
    never requested;
  * the string `_rasterisePdf` hands `html()` goes through the shipped
    DOMPurify (its `sanitize` is counted);
  * the file is text, not tiles: html2pdf's file had an empty text layer
    (`B1333` measured `''` from `pypdf`), this one carries the document's words
    and no images;
  * html2pdf's link plugin, rebuilt: each `https:` link is a `/URI` annotation
    on the page where its words are, over them; the in-page `#anchor` is not
    a link out of the file;
  * what html2pdf's page-break plugin would have acted on, counted on the very
    container jsPDF hands html2canvas: nothing.

Boots the app as `tests/test_the_command_palette_in_a_browser.py` does (its
`app_url` fixture) and skips, with the reason, where node, Playwright or
Chromium is absent.
"""

import json
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const PDF_PATH = process.argv[3];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, acceptDownloads: true });
  const creds = { username: 'editor', password: 'editor-pass-1' };
  await ctx.request.post(BASE + '/api/auth/setup', { data: creds });
  await ctx.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const page = await ctx.newPage();
  const out = { errors: [], libRequests: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  page.on('request', (r) => {
    const u = r.url();
    if (u.includes('/static/lib/')) out.libRequests.push(u.replace(BASE, '').split('?')[0]);
  });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);

  const lines = [];
  for (let i = 1; i <= 90; i++) lines.push(`Line ${i}: the ferry timetable WORDPROBE${i} lists departures.`);
  const content = [
    '# Fallback probe',
    '',
    'An opening paragraph with a [LINKPROBE](https://example.com/linkprobe) in it, '
      + 'and an [in-page anchor](#somewhere) that is not a way out of the file.',
    '',
    '```python',
    'print("FENCEDPROBE")',
    '```',
    '',
    'Latin-1 survives: café naïve façade.',
    '',
    'Cyrillic too, since `B1674`: Привет CYRPROBE.',
    '',
    ...lines.map((l) => l + '\n'),
    'And on a later page, [LATEPROBE](https://example.net/late) at the end.',
  ].join('\n');
  const id = (await (await page.request.post(BASE + '/api/document',
    { data: { title: 'Fallback probe', language: 'markdown', content } })).json()).id;
  await page.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, id);
  await page.waitForFunction((id) => !!document.querySelector(`.doc-tab.active[data-doc-id="${id}"]`),
    id, { timeout: 30000 });
  await page.waitForTimeout(800);

  await page.evaluate(() => {
    // The browser this path is for: the print frame cannot be written, so
    // `printHtmlInFrame` answers `false` and the export falls back.
    const desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentDocument');
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentDocument', {
      configurable: true,
      get() { return this.id === 'doc-print-frame' ? null : desc.get.call(this); },
    });
    window.__probe = { sanitized: 0, breakRules: null, h2cCalls: 0 };
    // Watch the two globals jsPDF's `html()` reaches for as they arrive.
    let dp;
    Object.defineProperty(window, 'DOMPurify', { configurable: true, get: () => dp, set: (v) => {
      const sanitize = v.sanitize.bind(v);
      v.sanitize = (...a) => { window.__probe.sanitized++; return sanitize(...a); };
      dp = v;
    } });
    let h2c;
    Object.defineProperty(window, 'html2canvas', { configurable: true, get: () => h2c, set: (fn) => {
      h2c = function (el, opts) {
        window.__probe.h2cCalls++;
        // What html2pdf's page-break plugin read, on the container it ran
        // on: computed break rules, and its private class.
        const rule = ['always', 'page', 'left', 'right'];
        const avoid = ['avoid', 'avoid-page'];
        let n = 0;
        for (const e of [el, ...el.querySelectorAll('*')]) {
          const s = getComputedStyle(e);
          if (rule.includes(s.breakBefore || s.pageBreakBefore)
              || rule.includes(s.breakAfter || s.pageBreakAfter)
              || avoid.includes(s.breakInside || s.pageBreakInside)
              || e.classList.contains('html2pdf__page-break')) n++;
        }
        window.__probe.breakRules = { elements: el.querySelectorAll('*').length, breaking: n };
        return fn(el, opts);
      };
    } });
  });

  let downloaded = null;
  page.on('download', async (d) => { downloaded = d; });
  await page.click('#doc-footer-export-btn');
  await page.waitForTimeout(400);
  out.menu = await page.evaluate(() => {
    const items = [...document.querySelectorAll('#doc-export-menu .doc-overflow-item')];
    const item = items.find((b) => b.textContent === 'Print as PDF');
    if (item) item.click();
    return items.map((b) => b.textContent);
  });
  const t0 = Date.now();
  for (let i = 0; i < 240 && !downloaded; i++) await page.waitForTimeout(250);
  out.seconds = (Date.now() - t0) / 1000;
  out.downloadedName = downloaded ? downloaded.suggestedFilename() : null;
  if (downloaded) await downloaded.saveAs(PDF_PATH);
  out.probe = await page.evaluate(() => window.__probe);
  out.errorToast = await page.evaluate(() => {
    const t = [...document.querySelectorAll('.toast, .toast-error, [role="alert"]')]
      .map((n) => n.textContent.trim()).filter(Boolean);
    return t;
  });
  out.overlayLeft = await page.evaluate(() => document.querySelectorAll('.html2pdf__overlay').length);
  // `B334`'s differential, on the branch Pantheon now takes: what jsPDF's
  // string branch, with the shipped DOMPurify, leaves of a hostile string.
  out.payload = await page.evaluate(async () => {
    const P = '<img src=x onerror="window.__pwned=1"><b>kept</b>';
    let html = null;
    await new window.jspdf.jsPDF().html(P, { worker: true }).from(P)
      .then(function () { html = this.prop.src.innerHTML; });
    await new Promise((r) => setTimeout(r, 300));
    return { html, pwned: window.__pwned || null };
  });
  out.globals = await page.evaluate(() => ({
    jspdf: !!(window.jspdf && window.jspdf.jsPDF), version: window.jspdf && window.jspdf.jsPDF.version,
    html2pdf: typeof window.html2pdf,
  }));
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("fallback-pdf")
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    pdf = d / "fallback.pdf"
    proc = subprocess.run([NODE, str(script), app_url, str(pdf)], capture_output=True, text=True,
                          timeout=480, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    out["pdf"] = pdf
    return out


def _reader(drive):
    import pypdf
    assert drive["downloadedName"] == "Fallback probe_v1.pdf", drive
    return pypdf.PdfReader(str(drive["pdf"]))


def _links(reader):
    """Every link annotation: (page index, rect, uri)."""
    found = []
    for i, page in enumerate(reader.pages):
        for ref in page.get("/Annots") or []:
            a = ref.get_object()
            if a.get("/Subtype") == "/Link" and "/A" in a:
                found.append((i, [float(v) for v in a["/Rect"]], str(a["/A"].get("/URI"))))
    return found


def _word_at(reader, word):
    """(page index, x, y) of the text run that starts `word`, in PDF points."""
    hits = []
    for i, page in enumerate(reader.pages):
        def visit(text, cm, tm, font, size, i=i):
            if word in text:
                hits.append((i, tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5]))
        page.extract_text(visitor_text=visit)
    return hits


def test_the_three_published_files_load_in_order_and_the_bundle_never_does(drive):
    pdf_libs = {"purify.min.js", "html2canvas.min.js", "jspdf.umd.min.js"}
    libs = [u for u in drive["libRequests"] if u.rsplit("/", 1)[-1] in pdf_libs]
    assert libs == ["/static/lib/purify.min.js", "/static/lib/html2canvas.min.js",
                        "/static/lib/jspdf.umd.min.js"], libs
    assert not any("html2pdf" in u for u in drive["libRequests"]), drive["libRequests"]
    assert drive["globals"]["jspdf"] is True and drive["globals"]["version"] == "4.2.1", drive["globals"]
    assert drive["globals"]["html2pdf"] == "undefined"


def test_the_html_handed_to_jspdf_goes_through_the_shipped_dompurify(drive):
    """The third file does something: `_rasterisePdf` hands `html()` a string,
    and `html()` sanitises a string before it puts it into the page."""
    assert drive["probe"]["sanitized"] >= 1, drive["probe"]
    assert drive["probe"]["h2cCalls"] == 1, drive["probe"]


def test_a_hostile_string_does_not_survive_jspdfs_string_branch(drive):
    """`B334` pinned the element branch because html2pdf 0.10.2's string
    branch handed `<img onerror>` back verbatim (CVE-2026-22787). Pantheon
    takes the string branch now (`B421`), so the question moves with it:
    jsPDF 4.2.1's `from(string)` with the shipped DOMPurify 3.4.17, in a real
    DOM, keeps the markup and drops the handler, and nothing ran."""
    payload = drive["payload"]
    assert payload["html"] and "<b>kept</b>" in payload["html"], payload
    assert "onerror" not in payload["html"], payload
    assert payload["pwned"] is None, payload


def test_the_fallback_pdf_is_text_not_tiles(drive):
    """html2pdf's file was JPEG tiles with an empty text layer (`B1333`
    measured `''`). jsPDF's `html()` draws text as text."""
    reader = _reader(drive)
    assert len(reader.pages) >= 2, len(reader.pages)
    text = "".join(p.extract_text() or "" for p in reader.pages)
    assert "Fallback probe" in text, text[:300]
    assert "WORDPROBE1 " in text and "WORDPROBE90" in text, text[:300]
    assert 'print("FENCEDPROBE")' in text
    assert "café naïve façade" in text
    assert sum(len(p.images) for p in reader.pages) == 0
    assert drive["pdf"].stat().st_size < 400_000, drive["pdf"].stat().st_size


def test_a_link_in_the_document_is_a_link_over_its_words_in_the_file(drive):
    """html2pdf's link plugin, which Pantheon had on by default and `html()`
    lacks, rebuilt in `_pdfLinkBoxes`. Each link is on the page its words are
    on, and its box covers where the words were drawn."""
    reader = _reader(drive)
    links = _links(reader)
    uris = sorted(u for _, _, u in links)
    assert uris == ["https://example.com/linkprobe", "https://example.net/late"], links
    for word, uri in (("LINKPROBE", "https://example.com/linkprobe"),
                      ("LATEPROBE", "https://example.net/late")):
        (page, x, y), = _word_at(reader, word)
        boxes = [r for p, r, u in links if u == uri]
        assert boxes and all(p == page for p, _, u in links if u == uri), (word, page, links)
        # jsPDF writes the rectangle top-first; a rectangle is two corners.
        x0, x1 = sorted(boxes[0][0::2])
        y0, y1 = sorted(boxes[0][1::2])
        # The run starts at the box's left edge and its baseline is inside it.
        assert abs(x - x0) < 1 and x < x1, (word, (x, y), boxes[0])
        assert y0 <= y <= y1, (word, (x, y), boxes[0])
    late_page = next(p for p, _, u in links if u == "https://example.net/late")
    assert late_page >= 1, "the late link should be past the first page"


def test_html2pdfs_page_break_plugin_had_nothing_to_act_on(drive):
    """The other plugin `D-2026-10-29-02` §2 drops, measured rather than
    assumed: on the container jsPDF hands html2canvas — the element
    html2pdf's plugin walked — no element carries a page-break rule or the
    plugin's class. `static/style.css`'s one break rule is inside
    `@media print`."""
    rules = drive["probe"]["breakRules"]
    assert rules and rules["elements"] > 50, rules
    assert rules["breaking"] == 0, rules


def test_cyrillic_is_drawn_in_inter_and_nothing_is_said_to_be_lost(drive):
    """`B1674` changed this test. It read: `html()` writes with the PDF's
    built-in fonts (WinAnsi), so `Привет` comes out as Latin-1 garbage, and
    the person is told which characters are wrong. Now a document with
    Cyrillic in it fetches Inter (`static/lib/pdf-fonts/`, the four faces and
    not the CJK one — "loaded only when a document needs it") and the file
    carries `Привет` as text; with nothing left undrawable, nothing is said.
    The sentence for what still is (emoji) is driven in
    `tests/test_the_fallback_pdf_draws_every_script_but_emoji_in_a_browser.py`."""
    toast = " ".join(drive["errorToast"])
    assert "can't draw" not in toast, drive["errorToast"]
    text = "".join(p.extract_text() or "" for p in _reader(drive).pages)
    assert "CYRPROBE" in text and "Привет" in text, text[:400]
    fonts = sorted({u.rsplit("/", 1)[-1] for u in drive["libRequests"] if "/pdf-fonts/" in u})
    assert fonts == ["Inter-Bold.ttf", "Inter-BoldItalic.ttf", "Inter-Italic.ttf",
                     "Inter-Regular.ttf"], fonts


def test_the_fallback_left_nothing_behind_and_logged_no_page_error(drive):
    assert drive["overlayLeft"] == 0
    assert drive["errors"] == [], drive["errors"]
