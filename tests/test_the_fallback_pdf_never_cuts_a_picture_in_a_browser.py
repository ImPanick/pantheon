# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1678` — the fallback PDF never cuts a picture at a page edge it could
have cleared.

*Print as PDF* prints the document in a frame (`B1333`); where the frame cannot
print, `_rasterisePdf` hands over a file drawn by jsPDF's `html()` (`B421`),
which slices the drawing at every page edge (`autoPaging: true`). `B1676` laid
the clone out with every line of **text** clear of the edges first
(`_keepLinesOffPageEdges`), but `_lineAcrossEdge` walked text nodes only, so a
picture — an `<img>` alone in its paragraph, or one taller than the text on its
line — could still lie across an edge and be drawn in two clipped halves, one
closing a page and one opening the next.

Driven in Chromium against the running app, the way
`tests/test_the_fallback_pdf_never_cuts_a_line_and_draws_formulas_in_a_browser.py`
drives `B1676`: a markdown document of pictures between paragraphs — pictures
alone in a paragraph, pictures inline with words and taller than them, and one
picture taller than a page — is exported with the print frame made unwritable,
and every picture the file draws is read out of the page content with `pypdf`.
The pictures are this test's own PNGs, answered at a same-origin path by
the context's `route` (`markdown.js` loads only same-origin images; a context
route also sees what the service worker fetches). Skips, with the reason, where
node, Playwright or Chromium is absent.
"""

import collections
import json
import struct
import subprocess
import zlib

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

# The export's 10 mm margin (`PDF_MARGIN_MM`), in points.
MARGIN_PT = 10 * 72 / 25.4

#: Each picture: name -> (width, height) in pixels, drawn at that size in CSS
#: px (`img{max-width:100%}` and every width here is under the 718 px column).
#: A4's inner height is 1,047 CSS px, so `tall` is taller than a page and the
#: rest are not.
ALONE = {f"alone{i}": (300 + 4 * i, 250 + 3 * i) for i in range(1, 15)}
INLINE = {f"inline{i}": (90 + 2 * i, 110 + 2 * i) for i in range(1, 11)}
TALL = {"tall": (240, 1900)}
PICTURES = {**ALONE, **INLINE, **TALL}


def _png(width: int, height: int, seed: int) -> bytes:
    """A PNG of one colour per picture, so no two are the same bytes (jsPDF
    stores identical images once)."""
    colour = bytes(((seed * 53) % 200 + 30, (seed * 97) % 200 + 30, (seed * 31) % 200 + 30))
    raw = b"".join(b"\x00" + colour * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const [BASE, PDF_PATH, PICS_DIR, NAMES] = [process.argv[2], process.argv[3], process.argv[4],
  JSON.parse(process.argv[5])];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, acceptDownloads: true });
  const creds = { username: 'pictures', password: 'pictures-pass-1' };
  await ctx.request.post(BASE + '/api/auth/setup', { data: creds });
  await ctx.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const page = await ctx.newPage();
  const out = { errors: [], served: {} };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  // The context's route, not the page's: it also sees what the service
  // worker fetches for the page.
  await ctx.route('**/static/pdf-probe/*.png', (route) => {
    const name = route.request().url().split('/').pop().replace('.png', '');
    out.served[name] = (out.served[name] || 0) + 1;
    route.fulfill({ status: 200, contentType: 'image/png', body: fs.readFileSync(`${PICS_DIR}/${name}.png`) });
  });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);

  const filler = (n, k) => Array.from({ length: k }, (_, j) =>
    `Filler ${n}.${j}: the harbour master logs each ferry that leaves before noon.`).join(' ');
  const parts = ['# Picture probe', ''];
  NAMES.alone.forEach((name, i) => {
    parts.push(filler(`a${i}`, (i % 4) + 1), '', `![${name}](/static/pdf-probe/${name}.png)`, '');
  });
  NAMES.inline.forEach((name, i) => {
    parts.push(`Before ${name} the words run on ![${name}](/static/pdf-probe/${name}.png) and after it `
      + `INLINEPROBE${i + 1} they run on again.`, '', filler(`b${i}`, (i % 3) + 2), '');
  });
  parts.push(filler('t', 9), '', '![tall](/static/pdf-probe/tall.png)', '', 'After the tall picture, TAILPROBE.');
  const content = parts.join('\n');
  const id = (await (await page.request.post(BASE + '/api/document',
    { data: { title: 'Picture probe', language: 'markdown', content } })).json()).id;
  await page.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, id);
  await page.waitForFunction((id) => !!document.querySelector(`.doc-tab.active[data-doc-id="${id}"]`),
    id, { timeout: 30000 });
  await page.waitForTimeout(800);

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
  for (let i = 0; i < 480 && !downloaded; i++) await page.waitForTimeout(250);
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
    d = tmp_path_factory.mktemp("picture-pdf")
    pics = d / "pics"
    pics.mkdir()
    for seed, (name, (w, h)) in enumerate(PICTURES.items(), start=1):
        (pics / f"{name}.png").write_bytes(_png(w, h, seed))
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    pdf = d / "pictures.pdf"
    names = {"alone": list(ALONE), "inline": list(INLINE)}
    proc = subprocess.run([NODE, str(script), app_url, str(pdf), str(pics), json.dumps(names)],
                          capture_output=True, text=True, timeout=480, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["downloadedName"] == "Picture probe_v1.pdf", out
    import pypdf
    out["reader"] = pypdf.PdfReader(str(pdf))
    return out


class Draw(collections.namedtuple("Draw", "page x0 y0 x1 y1 width height")):
    """One picture drawn on one page: where, in PDF points (y up), and the
    picture's own size in pixels, which names it."""


def _draws(reader) -> list[Draw]:
    """Every image XObject the pages draw, placed by the transformation in
    force at its `Do` (`q`/`Q`/`cm` followed; jsPDF places each picture with
    its own `q … cm /In Do Q`)."""
    from pypdf.generic import ContentStream

    def mul(m, n):
        a, b, c, d, e, f = m
        a2, b2, c2, d2, e2, f2 = n
        return (a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2,
                e * a2 + f * c2 + e2, e * b2 + f * d2 + f2)

    found = []
    for i, page in enumerate(reader.pages):
        xobjects = (page.get("/Resources") or {}).get("/XObject") or {}
        content = ContentStream(page.get_contents(), reader)
        ctm, stack = (1, 0, 0, 1, 0, 0), []
        for operands, op in content.operations:
            if op == b"q":
                stack.append(ctm)
            elif op == b"Q":
                # jsPDF's canvas saves on one page and restores on the next,
                # so a page can open with a `Q`: its state is the page's own.
                ctm = stack.pop() if stack else (1, 0, 0, 1, 0, 0)
            elif op == b"cm":
                ctm = mul(tuple(float(v) for v in operands), ctm)
            elif op == b"Do":
                xobj = xobjects[operands[0]].get_object()
                if xobj.get("/Subtype") != "/Image":
                    continue
                a, b, c, d, e, f = ctm
                xs = [e, a + e, c + e, a + c + e]
                ys = [f, b + f, d + f, b + d + f]
                found.append(Draw(i, min(xs), min(ys), max(xs), max(ys),
                                  int(xobj["/Width"]), int(xobj["/Height"])))
    return found


def _name(draw: Draw) -> str:
    """Which picture a draw is, by its pixel size (each is unique)."""
    names = [n for n, (w, h) in PICTURES.items() if (w, h) == (draw.width, draw.height)]
    assert len(names) == 1, (draw, names)
    return names[0]


def _cut(reader, draw: Draw) -> bool:
    """A draw that reaches past its page's margins is a clipped half."""
    height = float(reader.pages[draw.page].mediabox.height)
    return draw.y0 < MARGIN_PT - 0.5 or draw.y1 > height - MARGIN_PT + 0.5


def test_every_picture_is_in_the_file(drive):
    """The pictures load (the route answered each) and each is drawn."""
    assert set(drive["served"]) == set(PICTURES), drive["served"]
    drawn = {_name(d) for d in _draws(drive["reader"])}
    assert drawn == set(PICTURES), set(PICTURES) - drawn


def test_the_document_runs_over_several_pages(drive):
    """The rest of this file is only evidence if there are edges to cut."""
    assert len(drive["reader"].pages) >= 6, len(drive["reader"].pages)


def test_no_picture_shorter_than_a_page_is_cut_at_an_edge(drive):
    """`B1678`'s `Verify:`, first half: a picture alone in its paragraph, or
    taller than the words on its line, is drawn whole on one page. A cut one
    is in the file twice, each half reaching past the margin it is clipped
    to."""
    reader = drive["reader"]
    by_name = collections.defaultdict(list)
    for draw in _draws(reader):
        by_name[_name(draw)].append(draw)
    cut = {name: draws for name, draws in by_name.items()
           if name not in TALL and (len(draws) != 1 or _cut(reader, draws[0]))}
    assert not cut, cut


def test_a_picture_taller_than_a_page_is_cut_once(drive):
    """`B1678`'s `Verify:`, second half. 1,900 px is under two pages (2,094),
    so started at the top of a page it crosses one edge; started lower, it
    crosses two and is drawn on three pages."""
    reader = drive["reader"]
    draws = [d for d in _draws(reader) if _name(d) == "tall"]
    assert len(draws) == 2, draws
    first, second = sorted(draws)
    assert second.page == first.page + 1, draws
    height = float(reader.pages[first.page].mediabox.height)
    assert abs(first.y1 - (height - MARGIN_PT)) < 2, ("it does not open its page", first)


def test_the_words_beside_a_moved_picture_move_with_it(drive):
    """A picture taller than its line moves the line — the words beside it
    stay on its page, on its baseline."""
    reader = drive["reader"]
    draws = {_name(d): d for d in _draws(reader) if _name(d) in INLINE}
    words = {}
    for i, page in enumerate(reader.pages):
        def visit(text, cm, tm, font, size, i=i):
            if text.strip().startswith("INLINEPROBE"):
                words[text.strip()] = (i, tm[5] * cm[3] + cm[5])
        page.extract_text(visitor_text=visit)
    for n, name in enumerate(INLINE, start=1):
        page, y = words[f"INLINEPROBE{n}"]
        draw = draws[name]
        assert draw.page == page and draw.y0 - 6 <= y <= draw.y1, (name, draw, (page, y))


def test_the_export_finished_with_no_error(drive):
    assert drive["errors"] == [], drive["errors"]
    assert not any("failed" in t for t in drive["toasts"]), drive["toasts"]
