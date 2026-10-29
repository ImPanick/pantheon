# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1685` — a character the fallback PDF cannot draw is left out of the file,
not written into it as Latin-1 noise, and the export's sentence says so.

*Print as PDF* prints the document in a frame (`B1333`); where the frame cannot
print, `_rasterisePdf` hands over a file drawn by jsPDF's `html()` (`B421`).
Its built-in fonts are Windows-1252, and `B1674` embeds Inter and a CJK face
for the scripts the owner named; what none of them draws — emoji, Hebrew,
Arabic, anything past U+FFFF — is named in the export's sentence. But the file
still carried it: jsPDF writes a string with any character past U+00FF as
UTF-16 bytes, and a built-in font draws those bytes as Windows-1252 letters,
so `# CODEPROBE 🎉` came out as `# CODEPROBE Ø<ß‰` (measured in `B1674`'s
probe), and a Hebrew word as `\\x05é\\x05Ü…`. An emoji in prose never had the
problem — `markdown.js` draws it as an icon with no text — but in a code block,
in inline code, or beside a TrueType face that lacks it, the character itself
reached jsPDF. Now `_pdfFontRuns` hides it in html2canvas's clone: laid out,
so everything around it keeps its place, and not drawn, so the file has a
blank where it was.

Driven against the running app the way
`tests/test_the_fallback_pdf_draws_every_script_but_emoji_in_a_browser.py`
drives `B1674`: two documents are exported with the print frame made
unwritable — a Latin-only one, which fetches no font and is drawn in the
built-in ones alone, and one with Cyrillic in it, drawn in Inter — each with
an emoji and a Hebrew word in a code block, in inline code and in prose, and
each file's text layer is read with `pypdf`. Skips, with the reason, where
node, Playwright or Chromium is absent.
"""

import json
import re
import string
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

HEBREW = "שלום"
#: A space the built-in fonts lack. It is whitespace: it fetches no font, is
#: named in no sentence, and stays with its run (`_pdfFontFor`), because
#: html2canvas draws the words either side of it and never it — measured here,
#: and the reason a whitespace character is not hidden like the rest.
THIN = "A thin space: 10\u2009000 THINPROBE."

#: Each document's markdown. Nothing in either is outside ASCII but what the
#: test is about, so any other character in a file's text is noise.
LATIN = "\n".join([
    "# Latin only LATINHEAD",
    "",
    f"Prose with Hebrew {HEBREW} PROSEHEB and an emoji 🎉 PROSEEMOJI in it.",
    "",
    "Inline code `x🎉y` INLINEPROBE and `{h}` INLINEHEB.".format(h=HEBREW),
    "",
    THIN,
    "",
    "```python",
    "# CODEPROBE 🎉",
    f'greeting = "{HEBREW}"  # CODEHEB',
    "```",
])
EMBEDDED = "\n".join([
    "# Привет CYRHEAD",
    "",
    f"Prose in Inter, Привет, with Hebrew {HEBREW} PROSEHEB and an emoji 🎉 PROSEEMOJI.",
    "",
    "Inline code `x🎉y` INLINEPROBE and `{h}` INLINEHEB.".format(h=HEBREW),
    "",
    THIN,
    "",
    "```python",
    'print("Привет из кода")  # CODEPROBE 🎉',
    f'greeting = "{HEBREW}"  # CODEHEB',
    "```",
])

_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, OUT_DIR, DOCS] = [process.argv[2], process.argv[3], JSON.parse(process.argv[4])];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, acceptDownloads: true });
  const creds = { username: 'leftout', password: 'leftout-pass-1' };
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
    // The sentence of the export before this one is not this one's: the one
    // toast element is emptied (`ui.js` refills it for each message).
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
    d = tmp_path_factory.mktemp("left-out-pdf")
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    docs = [{"title": "Latin left out", "content": LATIN, "file": "latin.pdf"},
            {"title": "Embedded left out", "content": EMBEDDED, "file": "embedded.pdf"}]
    proc = subprocess.run([NODE, str(script), app_url, str(d), json.dumps(docs)],
                          capture_output=True, text=True, timeout=600, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    import pypdf
    for doc, result in zip(docs, out["exports"]):
        assert result["downloadedName"] == doc["title"] + "_v1.pdf", (result, out["errors"])
        result["reader"] = pypdf.PdfReader(str(d / doc["file"]))
        result["source"] = doc["content"]
    out["latin"], out["embedded"] = out["exports"]
    return out


def _runs(reader) -> list[str]:
    """The text of every text-showing operation, in the order it is drawn."""
    found = []
    for page in reader.pages:
        page.extract_text(visitor_text=lambda text, *_: found.append(text))
    return found


def _noise(result) -> set[str]:
    """Characters the file draws that its document does not have: what a
    built-in font makes of UTF-16 bytes. A list's bullet would be the
    exporter's own, and there is no list here."""
    drawn = set("".join(_runs(result["reader"])))
    return {ch for ch in drawn - set(result["source"]) - set(string.printable)}


# ── the Verify: drawn as nothing, in a Latin-only document too ─────────────

def test_the_latin_only_document_is_drawn_in_the_built_in_fonts_alone(drive):
    """What makes the next test about the built-in fonts: no face fetched,
    none embedded — `B1685`'s *a Latin-only document too*."""
    assert drive["latin"]["fonts"] == [], drive["latin"]["fonts"]


@pytest.mark.parametrize("which", ["latin", "embedded"])
def test_no_undrawable_character_reaches_the_file_as_noise(drive, which):
    """`B1685`'s `Verify:`. Before: `Ø<ß‰` for the emoji, `\\x05é\\x05Ü\\x05Õ\\x05Ý`
    for the Hebrew, and every other letter of a string holding either drawn
    after a NUL. After: every character the file draws is one its document has."""
    result = drive[which]
    noise = _noise(result)
    assert not noise, (sorted(noise), [r for r in _runs(result["reader"]) if set(r) & noise])
    drawn = "".join(_runs(result["reader"]))
    assert "🎉" not in drawn and not set(HEBREW) & set(drawn), drawn


@pytest.mark.parametrize("which", ["latin", "embedded"])
def test_the_rest_of_each_line_is_drawn_as_it_was(drive, which):
    """Only the character goes: the words beside it are in the file, once,
    and the code line that held the emoji ends at the word before it (its
    place is a blank)."""
    reader = drive[which]["reader"]
    text = "".join(p.extract_text() or "" for p in reader.pages)
    for probe in ("PROSEHEB", "PROSEEMOJI", "INLINEPROBE", "INLINEHEB", "THINPROBE", "CODEPROBE",
                  "CODEHEB"):
        assert len(re.findall(probe, text)) == 1, (probe, text)
    (line,) = [ln for ln in text.splitlines() if "CODEPROBE" in ln]
    assert line.rstrip().endswith("# CODEPROBE"), line
    assert re.search(r"\bx\s*y\b", text), "the inline code's letters either side of the emoji"
    assert re.search(r'greeting = "\s*"\s+# CODEHEB', text), text
    assert re.search(r"\b10\s*000 THINPROBE", text), text


def test_the_embedded_document_still_draws_its_cyrillic(drive):
    """Leaving a character out must not take the font run beside it with it."""
    text = "".join(p.extract_text() or "" for p in drive["embedded"]["reader"].pages)
    assert text.count("Привет") == 3 and "Привет из кода" in text, text


# ── and the sentence says what happened to them ─────────────────────────────

@pytest.mark.parametrize("which", ["latin", "embedded"])
def test_the_sentence_names_them_and_says_they_are_left_out(drive, which):
    toasts = " ".join(drive[which]["toasts"])
    assert "Saved" in toasts and "can't draw" in toasts, drive[which]["toasts"]
    named = toasts.split("can't draw", 1)[1].split(",", 1)[0]
    assert "🎉" in named and all(ch in named for ch in HEBREW), named
    assert "left out of the file" in toasts, toasts
    assert "Export as Word keeps every character" in toasts, toasts


def test_the_exports_finished_with_no_error(drive):
    assert drive["errors"] == [], drive["errors"]
    for which in ("latin", "embedded"):
        assert not any("failed" in t for t in drive[which]["toasts"]), drive[which]["toasts"]
