# SPDX-License-Identifier: AGPL-3.0-or-later
"""The document editor in a real browser — `B1333`, `B1233`, `B1212`.

  * **`B1333`** — *Print as PDF* prints the document, not a picture of it.
    Measured on `03f50081` with this file's script: a 120-line markdown
    document came back as a 1.49 MB download in 11.6 s, four pages of 16 JPEG
    tiles and an **empty** text layer (`pypdf` extracts `''`), because
    `exportAsPdf` rasterised through html2canvas. Now it prints the standalone
    HTML *Export HTML* builds in a frame (`printFrame.js`, the chat's PDF item's
    frame since `B1320`). The frame's document is captured as it is taken out,
    rendered to PDF by Chromium's own print path (`page.pdf()`, what *Save as
    PDF* does), and its text layer read with `pypdf`.
  * **`B1233`** — a `text` document showed a blank type picker (no `text`
    option), and switching away and back turned it into markdown: measured,
    the picker then said `markdown` and the markdown Edit/Preview toggle came
    on, because `saveCurrentToMap` copied the picker's `''` into the tab map.
  * **`B1212`** — the email toolbar's AI button said *Reply* on a new mail
    that replies to nothing, as drawn and as put back after a draft.

Boots the app out of process exactly as
`tests/test_the_command_palette_in_a_browser.py` does (its `app_url` fixture,
imported) and skips, with the reason, where node, Playwright or Chromium is
absent.
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
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  // No model here: the AI draft answers as a server with none would.
  await page.route(BASE + '/api/email/ai-reply', (r) => r.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ success: false, error: 'No model is set up.' }) }));
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  const mk = async (data) => (await (await page.request.post(BASE + '/api/document', { data })).json()).id;
  const open = async (id) => {
    await page.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, id);
    await page.waitForTimeout(1200);
  };

  // ── B1333 ──────────────────────────────────────────────────────────────
  const lines = [];
  for (let i = 1; i <= 120; i++) lines.push(`Line ${i}: the ferry timetable WORDPROBE${i} lists departures.`);
  const printId = await mk({ title: 'Export probe', language: 'markdown',
    content: '# Export probe\n\n```python\nprint("FENCEDPROBE")\n```\n\n' + lines.join('\n\n') });
  await open(printId);
  await page.evaluate(() => {
    window.__printed = null;
    const make = document.createElement.bind(document);
    document.createElement = function (tag, ...rest) {
      const el = make(tag, ...rest);
      if (String(tag).toLowerCase() === 'iframe') {
        el.remove = function () {
          try {
            const d = el.contentDocument;
            if (d && window.__printed === null) window.__printed = '<!DOCTYPE html>\n' + d.documentElement.outerHTML;
          } catch (e) { window.__printed = 'ERR ' + e.message; }
          return HTMLElement.prototype.remove.call(el);
        };
      }
      return el;
    };
  });
  let downloaded = null;
  page.on('download', (d) => { downloaded = d.suggestedFilename(); });
  await page.click('#doc-footer-export-btn');
  await page.waitForTimeout(400);
  out.menu = await page.evaluate(() => {
    const items = [...document.querySelectorAll('#doc-export-menu .doc-overflow-item')];
    const item = items.find((b) => b.textContent === 'Print as PDF');
    if (item) item.click();
    return items.map((b) => b.textContent);
  });
  await page.waitForFunction(() => window.__printed !== null, null, { timeout: 30000 }).catch(() => {});
  const printed = await page.evaluate(() => window.__printed);
  out.downloaded = downloaded;
  out.printed = !!printed && !printed.startsWith('ERR');
  if (out.printed) {
    const p2 = await ctx.newPage();
    // Same origin, so the page's own sheets (KaTeX's) resolve as they did in the frame.
    await p2.route(BASE + '/__printed', (r) => r.fulfill({ status: 200, contentType: 'text/html', body: printed }));
    await p2.goto(BASE + '/__printed', { waitUntil: 'load' });
    await p2.pdf({ path: PDF_PATH, format: 'A4' });
    await p2.close();
  }
  out.printFrameLeft = await page.evaluate(() => !!document.getElementById('doc-print-frame'));

  // ── B1233 ──────────────────────────────────────────────────────────────
  const pick = () => page.evaluate(() => {
    const s = document.getElementById('doc-language-select');
    const t = document.getElementById('doc-md-view-toggle');
    return { value: s.value, shown: s.selectedIndex >= 0 ? s.options[s.selectedIndex].textContent : null,
      mdToggle: t ? getComputedStyle(t).display !== 'none' : null };
  });
  const textId = await mk({ title: 'packing-list.txt', language: 'text', content: 'socks\ntoothbrush\n**not bold**' });
  const mdId = await mk({ title: 'notes', language: 'markdown', content: '# hi' });
  await open(textId);
  out.text = await pick();
  await open(mdId);
  out.md = await pick();
  await open(textId);
  out.textAgain = await pick();

  // ── B1212 ──────────────────────────────────────────────────────────────
  const ai = () => page.evaluate(() => {
    const b = document.getElementById('doc-email-ai-reply-btn');
    return { label: b.textContent.trim(), title: b.title, shown: getComputedStyle(b).display !== 'none' };
  });
  const newMail = await mk({ title: 'New mail', language: 'email', content: 'To: a@example.com\nSubject: Hello\n---\n' });
  const reMail = await mk({ title: 'Re: mail', language: 'email',
    content: 'To: a@example.com\nSubject: Re: Hello\nIn-Reply-To: <abc@example.com>\n---\n' });
  await open(newMail);
  out.newMail = await ai();
  // A draft asked for and failed: the label is put back — as *Draft*.
  // DOM clicks: what is over the button is not this row's question (the old
  // raster export left html2pdf's overlay on the page for a while).
  await page.evaluate(() => document.getElementById('doc-email-ai-reply-btn').click());
  await page.waitForTimeout(300);
  await page.evaluate(() => {
    const b = document.querySelector('.doc-ai-reply-choice [data-mode="ai-reply-fast"]');
    if (b) b.click();
  });
  await page.waitForTimeout(1500);
  out.newMailAfterDraft = await ai();
  await open(reMail);
  out.reply = await ai();
  await open(newMail);
  out.newMailAgain = await ai();

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("doc-editor-browser")
    script = d / "drive.js"
    script.write_text(_SCRIPT)
    pdf = d / "printed.pdf"
    proc = subprocess.run([NODE, str(script), app_url, str(pdf)], capture_output=True, text=True,
                          timeout=480, cwd=str(d))
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    out["pdf"] = pdf
    return out


def test_print_as_pdf_prints_text_a_reader_can_select(drive):
    """`B1333`'s `Verify:` the PDF's text layer holds a word from the document."""
    import pypdf
    assert "Print as PDF" in drive["menu"], drive["menu"]
    assert drive["printed"] is True, "Print as PDF printed no frame"
    assert drive["downloaded"] is None, "Print as PDF downloaded a rasterised file"
    assert drive["printFrameLeft"] is False, "the print frame is taken out again"
    reader = pypdf.PdfReader(str(drive["pdf"]))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert "WORDPROBE1 " in text and "WORDPROBE120" in text, text[:400]
    assert 'print("FENCEDPROBE")' in text, "the code block is text too"
    assert "Copy" not in text, "the code block's Copy button is not printed"
    # Text, not tiles: tens of KB where the raster was 1.49 MB.
    assert drive["pdf"].stat().st_size < 200_000, drive["pdf"].stat().st_size
    assert sum(len(p.images) for p in reader.pages) == 0


def test_a_text_document_shows_text_and_stays_text(drive):
    """`B1233`'s `Verify`: a text document's picker says `text`, and moving to
    another document and back leaves it text — not markdown."""
    assert drive["text"] == {"value": "text", "shown": "text", "mdToggle": False}
    assert drive["md"] == {"value": "markdown", "shown": "markdown", "mdToggle": True}
    assert drive["textAgain"] == {"value": "text", "shown": "text", "mdToggle": False}, (
        "the text document came back as markdown")


def test_a_new_mails_ai_button_says_draft_and_a_reply_says_reply(drive):
    """`B1212`: *Draft* when the mail has no `In-Reply-To`, *Reply* when it has
    one — as drawn, and as put back after a draft."""
    draft = {"label": "Draft", "title": "Draft this mail with AI (fast + optional context)", "shown": True}
    reply = {"label": "Reply", "title": "Draft a reply with AI (fast + optional context)", "shown": True}
    assert drive["newMail"] == draft
    assert drive["newMailAfterDraft"] == draft, "the label put back after a draft said Reply"
    assert drive["reply"] == reply
    assert drive["newMailAgain"] == draft


def test_the_editor_logged_no_page_error(drive):
    assert drive["errors"] == [], drive["errors"]
