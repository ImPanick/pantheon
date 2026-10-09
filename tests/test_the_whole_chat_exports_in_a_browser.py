# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx6-export in a real browser — the Export menu, and a document's PDF.

The owner, 2026-10-09: *"it only exports 1 page (top portion of the chat) -
never the FULL chat.. i had to 'save to documents' which puts the chat into the
docs... exporting it from the docs as a pdf doesnt work, only markdown and docx
works."*

Three things cannot be shown any other way, which is why this file boots the
real app on a throwaway data directory and drives it with a real headless
Chromium:

  * **the page really is one page.** `sessions.js` asks `/api/history/{sid}`
    for `HISTORY_PAGE_LIMIT_DESKTOP` (24) messages, so a 42-message chat draws
    24 `.msg` and the first question is not among them. No sandbox renders a
    chat; only a browser does.
  * **the menu's own handlers**, which live inside `app.js`'s 4,000-line
    initialiser that no sandbox loads, and the frame the PDF item prints.
  * **the document PDF**, which failed inside a vendored rasteriser reading
    this page's *computed* styles — `color(srgb 0.611765 0.870588 0.94902 /
    0.05)`, Chromium's form of a `color-mix(in srgb, …)` rule on
    `.code-block-header`. Nothing but the real stylesheet in a real browser
    produces that value, and nothing else explains why Markdown and Word
    worked while PDF did not.

The chat is seeded straight into the database before the app starts, with the
reasoning and tool-event shapes the chat route saves, so no model is needed.

Driven by hand on port 8774 while this lane was built; the test takes a free
port so it can run beside the suite.

Skipped, with the reason, where node, the `playwright` package or its Chromium
is not installed.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TURNS = 21          # 42 messages
PAGE = 24           # `sessions.js` HISTORY_PAGE_LIMIT_DESKTOP
SID = "fx6-export-long"
CREDS = {"username": "exporter", "password": "exporter-pass-1"}


def _browser():
    node = shutil.which("node")
    if not node:
        return None, "node binary not on PATH"
    probe = subprocess.run(
        [node, "-e",
         "const { chromium } = require('playwright');"
         "const fs = require('fs');"
         "const p = chromium.executablePath();"
         "process.stdout.write(fs.existsSync(p) ? p : '');"],
        capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        return None, "the playwright node package is not installed"
    if not probe.stdout.strip():
        return None, "playwright has no Chromium downloaded"
    return node, None


NODE, _SKIP = _browser()
pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_SEED = r'''
import json, sys, uuid
from datetime import datetime, timedelta
sys.path.insert(0, sys.argv[1])
from core.database import SessionLocal, Session as DbSession, ChatMessage as DbChatMessage, init_db

SID, TURNS = sys.argv[2], int(sys.argv[3])
init_db()
db = SessionLocal()
t0 = datetime(2026, 10, 1, 9, 0, 0)
try:
    s = DbSession(id=SID, name="The long export chat", owner=sys.argv[4], headers={},
                  endpoint_url="http://127.0.0.1:1/v1/chat/completions", model="gemma-4-26b")
    db.add(s)
    n = 0
    for i in range(1, TURNS + 1):
        db.add(DbChatMessage(id=str(uuid.uuid4()), session_id=SID, role="user",
                             content=f"Question {i}: what happens on step {i}?",
                             timestamp=t0 + timedelta(minutes=2 * i)))
        n += 1
        meta = {"model": "gemma-4-26b"}
        if i % 3 == 1:
            meta["thinking"] = f"REASONING-{i}: look this up before answering step {i}."
        if i % 3 == 2:
            meta["round_thinking"] = [f"REASONING-{i}-ROUND-1: plan the search for step {i}.",
                                      f"REASONING-{i}-ROUND-2: read what came back for step {i}."]
            meta["thinking"] = "\n\n".join(meta["round_thinking"])
            meta["tool_events"] = [{"type": "tool_output", "tool": "web_search", "round": 1,
                                    "command": f"step {i} details",
                                    "output": f"TOOLOUT-{i}: three sources about step {i}."}]
        db.add(DbChatMessage(id=str(uuid.uuid4()), session_id=SID, role="assistant",
                             content=f"Answer {i}: step {i} does the thing.",
                             meta_data=json.dumps(meta),
                             timestamp=t0 + timedelta(minutes=2 * i, seconds=30)))
        n += 1
    s.message_count = n
    s.last_message_at = t0 + timedelta(minutes=2 * TURNS, seconds=30)
    db.commit()
    print(n)
finally:
    db.close()
'''


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    data = tmp_path_factory.mktemp("export-app")
    # `tests/conftest.py` puts `DATABASE_URL=sqlite:///:memory:` in the
    # environment for the suite, and a child process inherits it — the seeder
    # and the app would each get an in-memory database of their own and the
    # seeded chat would never reach the app (measured: the chat drew 0
    # messages and the session list was empty). This run wants one file.
    env = dict(os.environ, PANTHEON_DATA_DIR=str(data), APP_BIND="127.0.0.1",
               PANTHEON_DISABLE_MCP="1",
               DATABASE_URL=f"sqlite:///{data / 'app.db'}")
    # Seeded before the app starts, so `load_sessions` sees the chat.
    seeder = data / "seed.py"
    seeder.write_text(_SEED, encoding="utf-8")
    seeded = subprocess.run([sys.executable, "-I", str(seeder), str(ROOT), SID, str(TURNS),
                             CREDS["username"]],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert seeded.returncode == 0, seeded.stderr[-2000:]
    assert seeded.stdout.strip().splitlines()[-1] == str(2 * TURNS), seeded.stdout

    port = _free_port()
    env["APP_PORT"] = str(port)
    log = open(data / "app.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
        while True:
            if proc.poll() is not None:
                log.flush()
                pytest.fail("the app exited during start-up:\n"
                            + (data / "app.log").read_text(encoding="utf-8")[-3000:])
            try:
                with urllib.request.urlopen(url + "/login", timeout=2) as res:
                    if res.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() > deadline:
                pytest.fail("the app did not answer /login within 120 s")
            time.sleep(0.5)
        yield url
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()


_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const SID = process.argv[3];
const OWNER_DOC = process.argv[4];
// Out here, so a failure is reported with everything the run had already
// measured rather than with a bare timeout.
const out = { errors: [], downloads: [] };
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 },
                                             acceptDownloads: true });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  page.on('download', (d) => out.downloads.push(d.suggestedFilename()));
  const creds = { username: 'exporter', password: 'exporter-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 60000 });
  await page.waitForTimeout(1200);
  await page.evaluate(async (sid) => { await window.sessionModule.selectSession(sid); }, SID);
  await page.waitForTimeout(2500);

  // 1. What the chat actually drew.
  out.page = await page.evaluate(() => {
    const box = document.getElementById('chat-history');
    return { msgs: box.querySelectorAll('.msg').length, text: box.textContent };
  });
  out.page = { msgs: out.page.msgs,
               first: out.page.text.includes('Question 1:'),
               last: out.page.text.includes('Question 21:') };

  // Each step records what it saw rather than throwing: the same script is run
  // against the tree before this lane, where two of the controls it reaches for
  // do not exist, and a run that dies at the first one is evidence about
  // nothing. `out.failed` names whatever would not work.
  out.failed = {};
  const step = async (name, fn) => {
    try { out[name] = await fn(); }
    catch (e) { out.failed[name] = String((e && e.message) || e).split('\n')[0].slice(0, 160); }
  };
  const openMenu = async () => {
    await page.click('#export-dl-btn', { timeout: 15000 });
    await page.waitForTimeout(250);
  };
  const clickItem = async (id) => {
    await openMenu();
    await page.click(id, { timeout: 10000 });
  };

  // 2. Copy Chat.
  await step('copied', async () => {
    await clickItem('#export-copy-btn');
    await page.waitForTimeout(2500);
    return page.evaluate(async () => {
      const t = await navigator.clipboard.readText();
      return { len: t.length, first: t.includes('Question 1:'), last: t.includes('Answer 21:'),
               reasoning: /REASONING-1:/.test(t), tool: /TOOLOUT-2:/.test(t) };
    });
  });

  // 3. PDF — read the print frame from its own removal: print() tears it down
  // the moment it returns.
  await page.evaluate(() => {
    window.__printed = null;
    const make = document.createElement.bind(document);
    document.createElement = function (tag, ...rest) {
      const el = make(tag, ...rest);
      if (String(tag).toLowerCase() === 'iframe') {
        el.remove = function () {
          try {
            const d = el.contentDocument;
            if (d && window.__printed === null) {
              window.__printed = { title: d.title, msgs: d.querySelectorAll('.msg').length,
                                   think: d.querySelectorAll('details.think').length,
                                   tools: d.querySelectorAll('details.tool').length,
                                   text: d.body ? d.body.innerText : '' };
            }
          } catch (e) { window.__printed = String(e && e.message); }
          return HTMLElement.prototype.remove.call(el);
        };
      }
      return el;
    };
  });
  await step('printed', async () => {
    await clickItem('#export-pdf-btn');
    await page.waitForTimeout(4000);
    return page.evaluate(() => {
      const p = window.__printed;
      if (!p || typeof p === 'string') return p;
      return { title: p.title, msgs: p.msgs, think: p.think, tools: p.tools,
               first: p.text.includes('Question 1:'), last: p.text.includes('Answer 21:'),
               reasoning: /REASONING-1:/.test(p.text), tool: /TOOLOUT-2:/.test(p.text) };
    });
  });
  out.frameGone = await page.evaluate(() => !document.getElementById('export-print-frame'));

  // 4. Download Chat (.md).
  await step('downloadedChat', async () => {
    await openMenu();
    const dl = page.waitForEvent('download', { timeout: 30000 })
      .then((d) => d.suggestedFilename(), () => 'NO DOWNLOAD');
    await page.click('#export-file-btn', { timeout: 10000 });
    return dl;
  });
  await page.waitForTimeout(600);
  // Saving a file must not navigate the chat away (`download`, not a bare
  // href: measured without it, Chromium saved the file AND left the page on
  // the export URL).
  out.afterDownload = await page.evaluate(() => ({
    url: location.pathname,
    chat: !!document.getElementById('chat-history'),
    msgs: document.querySelectorAll('#chat-history .msg').length,
  }));

  // 5. Save to Documents — the door the owner had to use.
  await step('saved', async () => {
    await clickItem('#export-doc-btn');
    await page.waitForTimeout(5000);
    return page.evaluate(() => {
      const v = document.getElementById('doc-editor-textarea')?.value || '';
      return { len: v.length, first: v.includes('Question 1:'), last: v.includes('Answer 21:'),
               reasoning: /REASONING-1:/.test(v), tool: /TOOLOUT-2:/.test(v) };
    });
  });

  // 6. A document exported as PDF — on text with a fenced code block in it,
  // which is what carries `.code-block-header` and its unreadable colour.
  const doc = await page.request.post(BASE + '/api/document', {
    data: { session_id: SID, title: 'Export probe', content: OWNER_DOC } });
  const docId = (await doc.json()).id;
  await page.evaluate(async (id) => { await window.documentModule.loadDocument(id); }, docId);
  await page.waitForTimeout(2500);
  out.docPane = await page.evaluate(() => ({
    textarea: (document.getElementById('doc-editor-textarea') || {}).value?.length ?? null,
    lang: (document.getElementById('doc-language-select') || {}).value ?? null,
    exportBtn: !!document.getElementById('doc-footer-export-btn')?.getClientRects().length,
  }));
  await step('docPdf', async () => {
    const t0 = Date.now();
    const pdf = page.waitForEvent('download', { timeout: 180000 })
      .then((d) => ({ file: d.suggestedFilename(), ms: Date.now() - t0 }),
            () => ({ file: null, ms: Date.now() - t0 }));
    await page.click('#doc-footer-export-btn', { timeout: 15000 });
    await page.waitForTimeout(400);
    out.docMenu = await page.evaluate(() => {
      const items = [...document.querySelectorAll('#doc-export-menu .doc-overflow-item')];
      const item = items.find((b) => b.textContent === 'Print as PDF');
      if (item) item.click();
      return items.map((b) => b.textContent);
    });
    return pdf;
  });
  out.docErrors = await page.evaluate(() =>
    [...document.querySelectorAll('.toast-error, .toast')].map((n) => n.textContent));

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => {
  out.fatal = String((e && e.message) || e);
  console.log(JSON.stringify(out));
  process.exit(1);
});
"""


# A document with a fenced code block: the strip `markdown.js` puts on one is
# `.code-block-header`, whose `color-mix(in srgb, …)` background is the colour
# the rasteriser could not read. The owner's own export is full of them.
DOC = (
    "# The chat, saved to documents\n\n"
    "User: Research the Fractured Archive raid.\n\n"
    "[Tool calls]\n"
    "- Web Search [done]\n"
    "  out: ```sources\n[1] Old (film) - Wikipedia\n```\n\n"
    "gemma-4-26b: <think>The user is asking for research into the raid.</think>\n\n"
    "Here is what I found, in a list:\n\n"
    "```python\nprint('a fenced code block')\n```\n\n"
    + "Some more body text to make the document a page long.\n\n" * 20
)


@pytest.fixture(scope="module")
def driven(app_url, tmp_path_factory):
    script = tmp_path_factory.mktemp("export-drive") / "drive.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, SID, DOC],
                          capture_output=True, text=True, timeout=600, cwd=ROOT)
    assert proc.returncode == 0, (proc.stdout[-4000:], proc.stderr[-4000:])
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "fatal" not in out, (out.get("fatal"), out.get("failed"))
    return out


# ── the page is one page ────────────────────────────────────────────────────

def test_the_chat_draws_one_page_of_a_long_conversation(driven):
    """The premise, measured rather than assumed: a DOM-built export of this
    chat cannot hold the first question, because the browser never had it."""
    assert driven["page"]["msgs"] == PAGE, driven["page"]
    assert driven["page"]["last"] is True
    assert driven["page"]["first"] is False, \
        "the chat drew all 42 — this test needs a conversation long enough to be paged"


# ── every item in the menu ─────────────────────────────────────────────────

def _step(driven, name):
    assert name in driven, f"{name} never ran: {driven['failed'].get(name)}"
    return driven[name]


def test_copy_chat_copies_the_whole_chat_with_its_reasoning(driven):
    got = _step(driven, "copied")
    assert got["first"] and got["last"], got
    assert got["reasoning"], "the model's thinking is what the owner was capturing"
    assert got["tool"], "the tool call and its output"


def test_the_pdf_item_prints_the_whole_chat(driven):
    got = _step(driven, "printed")
    assert isinstance(got, dict), got
    assert got["msgs"] == 2 * TURNS, got
    assert got["first"] and got["last"], got
    assert got["reasoning"] and got["tool"], got
    assert got["think"] == 7 + 14 and got["tools"] == 7, got
    assert got["title"] == "The long export chat"
    assert driven["frameGone"] is True, "the print frame is taken out again"


def test_the_menu_downloads_the_whole_chat_as_a_file(driven):
    assert _step(driven, "downloadedChat").startswith("conversation_The_long_export_chat_")
    assert driven["downloadedChat"].endswith(".md")


def test_saving_the_file_does_not_take_the_chat_away(driven):
    """A bare `href` click on an attachment response saved the file *and* put
    the page on the export URL, chat and menu gone. Measured here: the file
    arrives **and** the chat is still on screen behind it."""
    assert _step(driven, "downloadedChat") != "NO DOWNLOAD"
    assert driven["afterDownload"] == {"url": "/", "chat": True, "msgs": PAGE}, \
        driven["afterDownload"]


def test_save_to_documents_saves_the_whole_chat(driven):
    got = _step(driven, "saved")
    assert got["first"] and got["last"], got
    assert got["reasoning"] and got["tool"], got


# ── a document exports as PDF ──────────────────────────────────────────────

def test_a_document_with_a_code_block_exports_as_pdf(driven):
    """`B-NEW-3`. On `99134cf` this item produced no file at all and said
    nothing: html2canvas threw `Attempting to parse an unsupported color
    function "color"` on `.code-block-header`'s computed background, and
    nothing awaited the call."""
    assert driven["docPane"]["exportBtn"] is True
    assert "Print as PDF" in driven["docMenu"], driven["docMenu"]
    assert _step(driven, "docPdf")["file"] == "Export probe_v1.pdf", driven["docPdf"]
    assert driven["docPdf"]["ms"] < 180000


def test_the_page_logged_no_unhandled_error_while_exporting(driven):
    """The colour throw arrived as an unhandled rejection — a page error with
    nothing in the interface to show for it."""
    colour = [e for e in driven["errors"] if "unsupported color function" in e]
    assert colour == [], colour
    assert driven["errors"] == [], driven["errors"]
