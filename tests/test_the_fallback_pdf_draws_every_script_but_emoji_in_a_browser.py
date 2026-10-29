# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1674` — the fallback PDF draws Cyrillic, Greek, Chinese, Japanese and
Korean, and fetches the fonts for them only when a document has them.

*Print as PDF* prints the document in a frame (`B1333`); where the frame cannot
print, `_rasterisePdf` hands over a file drawn by jsPDF's `html()` (`B421`),
whose built-in fonts are Windows-1252. Measured in Chromium before this row:
*Привет* came out as `@825B`, *你好世界* as Latin-1 noise, an emoji as
nothing, and the export said so. The owner's call (`D-2026-10-29-03` §3,
"Inter + a CJK font"): the UI's own typeface as TrueType for Latin, Cyrillic
and Greek, and a CJK font for Chinese, Japanese and Korean, loaded only when a
document needs it; emoji out of scope.

Driven against the running app the way
`tests/test_the_fallback_pdf_is_jspdfs_own_with_its_links_in_a_browser.py`
drives `B421`: two documents are exported with the print frame made
unwritable — a Latin-only one, then one in every script the row names, with
an emoji, a bold heading, a code block and enough Cyrillic to run over several
pages — every request for `static/lib/pdf-fonts/` is counted, and each file is
read with `pypdf`. Skips, with the reason, where node, Playwright or Chromium
is absent.
"""

import collections
import json
import re
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

MARGIN_PT = 10 * 72 / 25.4
CYRILLIC_LINES = 70

#: What each script's probe line says, as the file's text layer must carry it.
SCRIPTS = {
    "Cyrillic": "Привет мир",
    "Greek": "Γειά σου κόσμε",
    "Simplified Chinese": "你好世界",
    "Traditional Chinese": "繁體中文測試",
    "Japanese": "こんにちは、カタカナ漢字",
    "Korean": "안녕하세요 세계",
}

_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, OUT_DIR, SCRIPTS, LINES] = [process.argv[2], process.argv[3], JSON.parse(process.argv[4]),
  Number(process.argv[5])];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, acceptDownloads: true });
  const creds = { username: 'scripts', password: 'scripts-pass-1' };
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

  async function exportOne(title, content, file) {
    fonts = [];
    const id = (await (await page.request.post(BASE + '/api/document',
      { data: { title, language: 'markdown', content } })).json()).id;
    await page.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, id);
    await page.waitForFunction((id) => !!document.querySelector(`.doc-tab.active[data-doc-id="${id}"]`),
      id, { timeout: 30000 });
    await page.waitForTimeout(800);
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
    const t0 = Date.now();
    for (let i = 0; i < 480 && !downloaded; i++) await page.waitForTimeout(250);
    page.off('download', onDownload);
    await page.waitForTimeout(500);
    const result = { title, seconds: (Date.now() - t0) / 1000,
      downloadedName: downloaded ? downloaded.suggestedFilename() : null, fonts: [...fonts] };
    if (downloaded) await downloaded.saveAs(`${OUT_DIR}/${file}`);
    result.toasts = await page.evaluate(() => [...document.querySelectorAll('.toast, .toast-error, [role="alert"]')]
      .map((n) => n.textContent.trim()).filter(Boolean));
    out.exports.push(result);
  }

  await exportOne('Latin only', ['# Latin only', '', 'Plain words, café and naïve, € and “quotes”.', '',
    '```', 'print("LATINPROBE")', '```'].join('\n'), 'latin.pdf');

  const lines = [];
  for (let i = 1; i <= LINES; i++) {
    lines.push(`Строка ${i}: паром отходит в полдень, КИРИЛЛИЦА${i} и снова слова.\n`);
  }
  const content = [
    '# Заголовок по-русски',
    '',
    ...Object.entries(SCRIPTS).map(([name, words]) => `${name.replace(/ /g, '')}PROBE: ${words}\n`),
    'Mixed in one word: abc你好def and Ωmega.',
    '',
    'A formula with Greek in it: $\\alpha^2 + \\beta$ MATHPROBE.',
    '',
    'An emoji the fonts do not draw: 🎉 EMOJIPROBE.',
    '',
    '```python',
    'print("Привет из кода")  # CODEPROBE 🎉',
    '```',
    '',
    ...lines,
  ].join('\n');
  await exportOne('Every script', content, 'scripts.pdf');
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("scripts-pdf")
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    proc = subprocess.run([NODE, str(script), app_url, str(d), json.dumps(SCRIPTS), str(CYRILLIC_LINES)],
                          capture_output=True, text=True, timeout=600, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    latin, scripts = out["exports"]
    assert latin["downloadedName"] == "Latin only_v1.pdf", (latin["toasts"], out["errors"])
    assert scripts["downloadedName"] == "Every script_v1.pdf", (scripts["toasts"], out["errors"])
    import pypdf
    out["latin"], out["scripts"] = latin, scripts
    latin["reader"] = pypdf.PdfReader(str(d / "latin.pdf"))
    scripts["reader"] = pypdf.PdfReader(str(d / "scripts.pdf"))
    latin["size"] = (d / "latin.pdf").stat().st_size
    scripts["size"] = (d / "scripts.pdf").stat().st_size
    return out


class Run(collections.namedtuple("Run", "page x y size font face text")):
    """One text-showing operation: its page, start and baseline in points,
    size, the font's `/BaseFont`, the embedded face's style (read from the
    `name` table jsPDF copies into the font program it embeds — every face of
    a family has the family's `/BaseFont`), and its text."""


def _face(font) -> str:
    """`bold`, `italic`, `bolditalic` or `regular`, for an embedded face."""
    try:
        program = (font["/DescendantFonts"][0].get_object()["/FontDescriptor"].get_object()
                   ["/FontFile2"].get_object().get_data())
    except (KeyError, TypeError, AttributeError):
        return ""
    style = ("bold" if "Bold".encode("utf-16-be") in program else "") \
        + ("italic" if "Italic".encode("utf-16-be") in program else "")
    return style or "regular"


def _runs(reader) -> list[Run]:
    found = []
    for i, page in enumerate(reader.pages):
        def visit(text, cm, tm, font, size, i=i):
            if text.strip():
                found.append(Run(i, tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5], size * tm[3] * cm[3],
                                 str((font or {}).get("/BaseFont")), _face(font or {}), text.strip()))
        page.extract_text(visitor_text=visit)
    return found


def _text(reader) -> str:
    return "".join(p.extract_text() or "" for p in reader.pages)


def _embedded_fonts(reader) -> set[str]:
    names = set()
    for page in reader.pages:
        for ref in ((page.get("/Resources") or {}).get("/Font") or {}).values():
            font = ref.get_object()
            if font.get("/Subtype") == "/Type0":
                names.add(str(font["/BaseFont"]))
    return names


# ── loaded only when a document needs it ────────────────────────────────────

def test_a_latin_document_fetches_no_font_and_embeds_none(drive):
    latin = drive["latin"]
    assert latin["fonts"] == [], latin["fonts"]
    assert _embedded_fonts(latin["reader"]) == set()
    assert "LATINPROBE" in _text(latin["reader"])
    assert latin["toasts"] == [] or not any("can't draw" in t for t in latin["toasts"]), latin["toasts"]


def test_a_document_in_every_script_fetches_inter_and_the_cjk_face(drive):
    fetched = set(drive["scripts"]["fonts"])
    assert fetched == {"Inter-Regular.ttf", "Inter-Bold.ttf", "Inter-Italic.ttf", "Inter-BoldItalic.ttf",
                       "NotoSansCJKsc-Regular.subset.ttf"}, fetched


# ── every script drawn ──────────────────────────────────────────────────────

def test_the_text_layer_carries_every_script(drive):
    """`B1674`'s `Verify:` — *Привет* is in the file's text — and the same
    for every script the owner named."""
    text = _text(drive["scripts"]["reader"])
    squeezed = re.sub(r"\s+", "", text)
    assert "Привет" in text, text[:400]
    for name, words in SCRIPTS.items():
        assert re.sub(r"\s+", "", words) in squeezed, (name, words, text[:600])
    assert "Заголовок" in text and "Привет из кода" in text and "Ωmega" in text


def test_greek_in_a_formula_is_drawn_too(drive):
    """KaTeX's letters are drawn in the built-in Times, which has no `α`: the
    clone gives each the face that has it, inside KaTeX's own layout."""
    runs = _runs(drive["scripts"]["reader"])
    (probe,) = [r for r in runs if r.text.startswith("MATHPROBE")]
    greek = [r for r in runs if r.text in ("α", "β") and r.page == probe.page and abs(r.y - probe.y) < 12]
    assert sorted(r.text for r in greek) == ["α", "β"], [r for r in runs if abs(r.y - probe.y) < 12]
    assert all(r.font == "/pantheonpdfsans" for r in greek), greek


def test_a_word_of_two_scripts_is_drawn_in_order_on_one_line(drive):
    """`abc你好def` is one word in two fonts: three runs, each where the
    browser put it — one baseline, left to right."""
    runs = _runs(drive["scripts"]["reader"])
    (abc,) = [r for r in runs if r.text.endswith("abc")]
    (cjk,) = [r for r in runs if r.text == "你好" and r.page == abc.page and abs(r.y - abc.y) < 1]
    (deff,) = [r for r in runs if r.text.startswith("def") and r.page == abc.page and abs(r.y - abc.y) < 1]
    assert abc.x < cjk.x < deff.x, (abc, cjk, deff)


def test_each_script_is_drawn_in_the_font_that_has_it(drive):
    """Cyrillic and Greek in Inter (the UI's typeface), CJK in the CJK face,
    the heading in Inter's bold, the code's Latin still in the built-in
    monospace beside its Cyrillic in Inter."""
    runs = _runs(drive["scripts"]["reader"])
    fonts_of = collections.defaultdict(set)
    for run in runs:
        for ch in run.text:
            fonts_of[ch].add(run.font)
    for ch in "ПриветΓειά":
        assert fonts_of[ch] and all("pantheonpdfsans" in f for f in fonts_of[ch]), (ch, fonts_of[ch])
    for ch in "你好繁體こカ안녕":
        assert fonts_of[ch] == {"/pantheonpdfcjk"}, (ch, fonts_of[ch])
    heading = [r for r in runs if "Заголовок" in r.text]
    assert heading and heading[0].face == "bold", heading
    body = [r for r in runs if "Привет" in r.text and "кода" not in r.text]
    assert body and body[0].face == "regular", body
    code = [r for r in runs if "CODEPROBE" in r.text or r.text.startswith("print(")]
    assert code and all("Courier" in r.font for r in code), code
    cyrillic_in_code = [r for r in runs if r.text in ("Привет", "из", "кода")
                        and any(c.page == r.page and abs(c.y - r.y) < 1 for c in code)]
    assert cyrillic_in_code and all(r.font == "/pantheonpdfsans" for r in cyrillic_in_code), \
        cyrillic_in_code


def test_only_the_faces_the_file_draws_with_are_in_it(drive):
    """jsPDF writes only the glyphs a file uses, and — `putOnlyUsedFonts` —
    only the faces it draws with: 8 MB of faces fetched, a file a small
    fraction of that, and no bold italic face in a document with none (the
    italic is the formula's `α`, which KaTeX sets in italic)."""
    reader = drive["scripts"]["reader"]
    assert _embedded_fonts(reader) == {"/pantheonpdfsans", "/pantheonpdfcjk"}
    faces = {_face(ref.get_object()) for page in reader.pages
             for ref in ((page.get("/Resources") or {}).get("/Font") or {}).values()
             if ref.get_object().get("/Subtype") == "/Type0"}
    assert faces == {"regular", "bold", "italic"}, faces
    assert drive["scripts"]["size"] < 1_000_000, drive["scripts"]["size"]


def test_no_line_of_the_new_fonts_is_cut_at_a_page_edge(drive):
    """`B1676`'s rule holds in the new faces: the lines are laid out in the
    font they are drawn in, so every run's glyphs lie inside its page."""
    reader = drive["scripts"]["reader"]
    assert len(reader.pages) >= 3, len(reader.pages)
    height = float(reader.pages[0].mediabox.height)
    cut = [r for r in _runs(reader)
           if r.y - 0.25 * r.size < MARGIN_PT - 0.5 or r.y + 0.75 * r.size > height - MARGIN_PT + 0.5]
    assert not cut, cut[:5]
    seen = collections.Counter(r.text for r in _runs(reader) if re.fullmatch(r"КИРИЛЛИЦА\d+", r.text))
    assert len(seen) == CYRILLIC_LINES and set(seen.values()) == {1}, seen


# ── what is still undrawable is said ────────────────────────────────────────

def test_only_the_emoji_is_named_as_undrawable(drive):
    toasts = " ".join(drive["scripts"]["toasts"])
    assert "Saved" in toasts and "can't draw 🎉," in toasts, drive["scripts"]["toasts"]
    for words in SCRIPTS.values():
        assert not any(ch in toasts for ch in words if not ch.isspace() and ch not in "、"), (words, toasts)
    assert "Export as Word" in toasts


def test_the_exports_finished_with_no_error(drive):
    assert drive["errors"] == [], drive["errors"]
    for result in (drive["latin"], drive["scripts"]):
        assert not any("failed" in t for t in result["toasts"]), result["toasts"]
