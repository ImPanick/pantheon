# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1793` — opening a document leaves the mode the person chose.

`static/js/document.js` `openPanel` called `_ensureAgentMode`, which pressed
the composer's Agent button whenever a document became visible: opened the way
the Library opens one, restored from its dock chip, put back open with its chat
after a reload, or opened by the model's own `create_document` or
`update_document` result. The press is the person's own control, so it saved
`mode: 'agent'` in the stored toggles and switched Deep Research off: a chat
set to Chat with Research on was left in Agent with Research off, and Agent was
what every chat and every reload came back to. `B701` keeps a mode something
else set from becoming the person's default; this press went round it, and for
a person without Agent it pressed a chip they are not shown. Upstream Odysseus
removed the press for issue #3780 (cad14f81, #6945).

Now opening a document changes neither. The model still gets its document
tools: a turn sent with a document open already goes as Agent for that turn
(`chat.js`, and the route's own `B1285`), and so now does a turn sent from an
editor that is open but still empty, which the press used to cover.

Driven in headless Chromium on the real app, booted as
`tests/test_the_command_palette_in_a_browser.py` boots it. The one stand-in is
the chat stream, answered by the page's own `route` so that the request each
send makes can be read. The last test is the same rule where no browser is
installed: a name absent from the whole of `document.js`, where its presence
anywhere would be this defect (`Law 20`).
"""
import json
import subprocess
from pathlib import Path

import pytest

from tests.helpers.source_text import blank
from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

DOCUMENT_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "document.js"

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [], sent: [] };
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  ctx.setDefaultTimeout(60000);
  ctx.setDefaultNavigationTimeout(120000);
  await ctx.addInitScript(() => {
    try {
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
      // The person's own choice, made once: Chat. A reload reads what the
      // page saved since, never this seed again.
      if (!localStorage.getItem('b1793-chosen')) {
        localStorage.setItem('b1793-chosen', '1');
        localStorage.setItem('pantheon-toggles', JSON.stringify({ mode: 'chat' }));
      }
    } catch (_) {}
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  // The chat stream is answered here, so what each send asked for is read.
  await page.route('**/api/chat_stream', async (route) => {
    const body = (route.request().postDataBuffer() || Buffer.alloc(0)).toString('utf8');
    const field = (name) => {
      const m = body.match(new RegExp('name="' + name + '"\\r\\n\\r\\n([^\\r\\n]*)'));
      return m ? m[1] : null;
    };
    out.sent.push({ mode: field('mode'), doc: field('active_doc_id'), research: field('use_research') });
    await route.fulfill({ status: 200, contentType: 'text/event-stream',
                          body: 'data: {"delta": "Noted."}\n\ndata: [DONE]\n\n' });
  });

  const creds = { username: 'ada', password: 'ada-pass-1234' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  out.login = (await page.request.post(BASE + '/api/auth/login',
    { data: { ...creds, remember: true } })).status();
  const chat = async (name) => (await (await page.request.post(BASE + '/api/session',
    { multipart: { name, skip_validation: 'true' } })).json()).id;
  const planChat = await chat('Plan');
  const emptyChat = await chat('Nothing yet');
  const made = await page.request.post(BASE + '/api/document', { data: {
    session_id: planChat, title: 'Plan', language: 'markdown', content: '# Plan\n\nThree steps.\n' } });
  out.created = made.status();
  const docId = (await made.json()).id;

  const state = () => page.evaluate(() => {
    let t = {};
    try { t = JSON.parse(localStorage.getItem('pantheon-toggles') || '{}'); } catch (_) {}
    const on = (id) => { const b = document.getElementById(id); return !!b && b.classList.contains('active'); };
    const box = document.getElementById('research-toggle');
    return { mode: t.mode || null, research: !!t.research,
             chatPressed: on('mode-chat-btn'), agentPressed: on('mode-agent-btn'),
             researchOn: !!(box && box.checked),
             editorOpen: !!(window.documentModule && window.documentModule.isPanelOpen()) };
  });
  const boot = async () => {
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(1500);
  };
  const settle = (open) => page.waitForFunction((open) => !!window.documentModule
      && window.documentModule.isPanelOpen() === open
      && !!document.getElementById('doc-editor-pane') === open, open, { timeout: 20000 })
    .then(() => page.waitForTimeout(900)).catch(() => {});
  const press = (sel) => page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (el) el.click();
    return !!el;
  }, sel);
  // Deep Research is switched on per visit to a chat (`sessions.js` clears it
  // on every switch), so the person turns it on in the chat, as they can type.
  // (`/research` alone opens the Deep Research window.)
  const researchOn = async () => {
    await page.fill('#message', '/toggle research on');
    await page.press('#message', 'Enter');
    await page.waitForFunction(() => !!document.getElementById('research-toggle')?.checked,
      null, { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(1200);
  };
  // The person picks Chat again, by its button, so that each opening below is
  // seen from Chat and not from what an earlier opening left behind.
  const chooseChat = async () => {
    await press('#mode-chat-btn');
    await page.waitForTimeout(800);
  };
  const send = async (words) => {
    const before = out.sent.length;
    await page.fill('#message', words);
    await page.press('#message', 'Enter');
    for (let i = 0; i < 150 && out.sent.length === before; i++) await page.waitForTimeout(200);
    await page.waitForFunction(() => {
      const b = document.querySelector('.send-btn');
      return !b || (b.dataset.mode !== 'streaming' && b.dataset.mode !== 'pending');
    }, null, { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(900);
    return out.sent.length > before ? out.sent[out.sent.length - 1] : null;
  };

  // A chat with a document comes back with the document in the dock.
  await page.goto(BASE + '/#' + planChat, { waitUntil: 'load' });
  await boot();
  out.chip = await page.waitForSelector('.minimized-dock-chip[data-modal-id="doc-panel"]', { timeout: 20000 })
    .then(() => true).catch(() => false);
  await researchOn();
  out.atLoad = await state();

  // 1. Restored from its dock chip.
  await press('.minimized-dock-chip[data-modal-id="doc-panel"] .minimized-dock-restore');
  await settle(true);
  out.fromChip = await state();

  // 2. Its chat loaded again with the document left open: it opens with it.
  await page.reload({ waitUntil: 'load' });
  await boot();
  await settle(true);
  out.reloaded = await state();

  // 3. Chat and Research chosen again; the document closed, then opened the
  // way the Library opens one.
  await chooseChat();
  await researchOn();
  await page.evaluate(() => window.documentModule.closePanel());
  await settle(false);
  await page.evaluate(async (id) => {
    window.documentModule.openPanel();
    await window.documentModule.loadDocument(id);
  }, docId);
  await settle(true);
  out.fromLibrary = await state();

  // The person switches Deep Research off by its chip, so a turn is a turn.
  out.typedSends = out.sent.length;
  if ((await state()).researchOn) await press('#research-toggle-btn');
  await page.waitForTimeout(500);
  out.researchOff = await state();

  // 4. A turn sent beside the document.
  out.sentBesideDocument = await send('Tighten the second step.');
  out.afterBesideDocument = await state();

  // 5. Another chat, nothing in it: the Document button opens an empty editor.
  await page.evaluate(async (id) => { await window.sessionModule.selectSession(id); }, emptyChat);
  await page.waitForTimeout(1500);
  await chooseChat();
  await press('#overflow-doc-btn');
  await settle(true);
  out.emptyEditor = await state();
  out.sentFromEmptyEditor = await send('Write a packing list here.');
  out.afterEmptyEditor = await state();

  // 6. The editor closed by the same button: a turn with nothing open.
  await press('#overflow-doc-btn');
  await settle(false);
  out.sentWithNothingOpen = await send('Thanks.');
  out.afterNothingOpen = await state();

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""

#: What the person chose, as the page shows it and stores it.
CHOSEN = ("mode", "research", "chatPressed", "agentPressed", "researchOn")
CHAT_WITH_RESEARCH = {"mode": "chat", "research": True, "chatPressed": True,
                      "agentPressed": False, "researchOn": True}


def _chosen(seen: dict) -> dict:
    return {key: seen[key] for key in CHOSEN}


def _still_chat(seen: dict) -> bool:
    return (seen["mode"], seen["chatPressed"], seen["agentPressed"]) == ("chat", True, False)


@pytest.fixture(scope="module")
def run(app_url, tmp_path_factory):  # noqa: F811
    if NODE is None:
        pytest.skip(_SKIP)
    script = tmp_path_factory.mktemp("doc-mode") / "doc_mode.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_document_restored_from_its_dock_chip_keeps_chat_and_research(run):
    """Not vacuous: the chat loaded in the mode the person left it, with its
    document in the dock and Research turned on by `/toggle research on`
    (typed, never sent), and the chip's restore opened the document."""
    assert run["login"] == 200 and run["created"] == 200, run
    assert run["chip"] is True and _chosen(run["atLoad"]) == CHAT_WITH_RESEARCH, run["atLoad"]
    assert run["typedSends"] == 0, "a typed /research reached the chat stream"
    assert run["fromChip"]["editorOpen"] is True, run["fromChip"]
    assert _chosen(run["fromChip"]) == CHAT_WITH_RESEARCH, run["fromChip"]


def test_a_chat_loaded_again_with_its_document_open_keeps_its_mode(run):
    """The mode only: loading a chat clears Research by design (`sessions.js`)."""
    assert run["reloaded"]["editorOpen"] is True, run["reloaded"]
    assert _still_chat(run["reloaded"]), run["reloaded"]


def test_a_document_opened_the_way_the_library_opens_one_keeps_them(run):
    assert run["fromLibrary"]["editorOpen"] is True, run["fromLibrary"]
    assert _chosen(run["fromLibrary"]) == CHAT_WITH_RESEARCH, run["fromLibrary"]


def test_a_turn_sent_beside_a_document_still_goes_as_agent(run):
    """The model keeps its document tools, for the turn, and nothing is saved."""
    assert run["researchOff"]["research"] is False and _still_chat(run["researchOff"]), run["researchOff"]
    sent = run["sentBesideDocument"]
    assert sent and sent["mode"] == "agent" and sent["doc"] and not sent["research"], sent
    assert _still_chat(run["afterBesideDocument"]), run["afterBesideDocument"]


def test_a_turn_sent_from_an_empty_editor_still_goes_as_agent(run):
    """What the press gave that a turn did not: an editor open with nothing in
    it yet is a request to write in it, so the turn goes as Agent, unsaved."""
    assert run["emptyEditor"]["editorOpen"] is True, run["emptyEditor"]
    assert _still_chat(run["emptyEditor"]), run["emptyEditor"]
    sent = run["sentFromEmptyEditor"]
    assert sent and sent["mode"] == "agent" and not sent["doc"], sent
    assert _still_chat(run["afterEmptyEditor"]), run["afterEmptyEditor"]


def test_a_turn_with_nothing_open_goes_in_the_mode_the_person_chose(run):
    assert run["afterNothingOpen"]["editorOpen"] is False, run["afterNothingOpen"]
    sent = run["sentWithNothingOpen"]
    assert sent and sent["mode"] == "chat" and not sent["doc"], sent
    assert run["errors"] == [], run["errors"]


def test_document_js_never_presses_or_sets_the_composer_mode():
    """The rule where no browser is installed. Showing a document is not the
    person choosing a mode, so nothing in `document.js` presses the mode
    buttons or calls the composer's own setter."""
    code = blank(DOCUMENT_JS)
    for name in ("mode-agent-btn", "mode-chat-btn", "__pantheonSetChatMode"):
        assert name not in code, f"document.js reaches for {name}"
