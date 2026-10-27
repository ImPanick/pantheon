# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1576` — the Library, a chat's transcript and the chat list are reached from a keyboard.

`B661` measured 140 elements built as a `<div>`/`<span>`/`<li>`/`<td>`/`<tr>`
and given a click handler, cut the email library's, and left 129. The biggest
holders were `sessions.js` 21, `documentLibrary.js` 9 and `chatRenderer.js` 7:

  * every item in a chat's ⋮ menu, its *Move to folder* submenu and the
    Library's menus was a `<div>` — a keyboard opened the menu and could press
    nothing in it. They are buttons now, as the email library's are;
  * the chat list is a listbox whose rows were all `tabindex="-1"`, so Tab never
    reached it; one row is its tab stop now, and the arrows move it;
  * a Library card holds its own controls, so its title is its button
    (`.doclib-card-open`, the shape `B661` gave the email card);
  * in a transcript, an attached file, an attached picture, the memory and
    skill rows and the reply's timings were a mouse's alone; they are focusable
    and pressed by `a11y.js`'s delegated activation.

The census (`tests/test_the_email_library_is_reached_from_a_keyboard.py`)
holds the rest at 1. This is the row's `Verify:`, driven in Chromium against
the real app: real chats and real documents made through the API, the
transcript drawn by the real `chatRenderer.js`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try {
      localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
      localStorage.setItem('pantheon-hint-drag-to-snap-seen', '1');
    } catch (_) {}
  });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'keys', password: 'keys-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  for (const name of ['First chat', 'Second chat']) {
    await page.request.post(BASE + '/api/session', { form: {
      name, endpoint_url: 'http://127.0.0.1:9/v1/chat/completions', model: 'm', skip_validation: '1' } });
  }
  for (const title of ['Harbour notes', 'Rye loaf']) {
    await page.request.post(BASE + '/api/document', { data: { title, content: '# ' + title + '\n\nbody', language: 'markdown' } });
  }
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 120000 });
  const focused = () => page.evaluate(() => {
    const a = document.activeElement;
    return a ? { tag: a.tagName, cls: String(a.className || ''), id: a.id || '',
                 sid: (a.closest && a.closest('[data-session-id]') || {}).dataset?.sessionId || null,
                 doc: (a.closest && a.closest('[data-doc-id]') || {}).dataset?.docId || null } : null;
  });

  // ── The chat list ────────────────────────────────────────────────────────
  await page.waitForFunction(() => document.querySelectorAll('#session-list .list-item[data-session-id]').length >= 2);
  // The Chats section starts folded; its chevron is a button, pressed here
  // from the keyboard.
  if (await page.evaluate(() => document.getElementById('sessions-section').classList.contains('collapsed'))) {
    await page.focus('#sessions-section .section-collapse-btn');
    await page.keyboard.press('Enter');
  }
  await page.waitForFunction(() => {
    const r = document.querySelector('#session-list .list-item[data-session-id]');
    return !!r && r.getBoundingClientRect().height > 0;
  });
  out.listStops = await page.evaluate(() => [...document.querySelectorAll('#session-list .list-item[data-session-id]')]
    .filter((r) => r.getAttribute('tabindex') === '0').length);
  // In the tab order: from the row's neighbour, Tab comes back to it.
  await page.focus('#session-list .list-item[data-session-id][tabindex="0"]');
  const stop = await focused();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Tab');
  out.tabbedBackToTheList = (await focused()).sid === stop.sid && stop.sid !== null;
  await page.keyboard.press('ArrowDown');
  // ArrowDown also opens that chat, which redraws the list; the focus is
  // given back to its row when the redraw lands, so wait on that, not a clock.
  await page.waitForFunction((sid) => {
    const a = document.activeElement;
    const row = a && a.closest && a.closest('#session-list .list-item[data-session-id]');
    return !!row && row.dataset.sessionId !== sid;
  }, stop.sid, { timeout: 20000 });
  const moved = await focused();
  out.arrowMoved = moved.sid !== null && moved.sid !== stop.sid;
  out.stopFollowed = await page.evaluate((sid) => {
    const r = document.querySelector(`#session-list .list-item[data-session-id="${sid}"]`);
    return !!r && r.getAttribute('tabindex') === '0';
  }, moved.sid);
  // The chat's menu, opened from the keyboard: every item is a button.
  await page.evaluate((sid) => {
    document.querySelector(`#session-list .list-item[data-session-id="${sid}"] .session-menu-btn`).focus();
  }, moved.sid);
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => [...document.querySelectorAll('.session-dropdown-menu')]
    .some((d) => getComputedStyle(d).display !== 'none'));
  out.chatMenu = await page.evaluate(() => {
    const dd = [...document.querySelectorAll('.session-dropdown-menu')].find((d) => getComputedStyle(d).display !== 'none');
    return [...dd.querySelectorAll('.dropdown-item-compact')].filter((n) => n.offsetParent !== null)
      .map((n) => ({ tag: n.tagName, text: n.textContent.trim().slice(0, 30) }));
  });
  await page.keyboard.press('Escape');
  await page.evaluate(() => document.querySelectorAll('.session-dropdown-menu').forEach((d) => { d.style.display = 'none'; }));

  // ── The Library ──────────────────────────────────────────────────────────
  await page.evaluate(() => document.getElementById('rail-archive').click());
  await page.waitForFunction(() => document.querySelectorAll('.doclib-card[data-doc-id]').length >= 2);
  out.docIds = await page.evaluate(() => [...document.querySelectorAll('.doclib-card[data-doc-id]')].map((c) => c.dataset.docId));
  await page.focus('#doclib-search');
  const libReached = [];
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press('Tab');
    const at = await focused();
    if (at && at.doc) libReached.push({ doc: at.doc, tag: at.tag, cls: at.cls });
  }
  out.libReached = libReached;
  // Enter on a card's title opens the card.
  await page.focus(`.doclib-card[data-doc-id="${out.docIds[0]}"] .doclib-card-open`);
  await page.keyboard.press('Enter');
  await page.waitForFunction((id) => document.querySelector(`.doclib-card[data-doc-id="${id}"]`)
    .classList.contains('doclib-card-expanded'), out.docIds[0]);
  out.libOpened = true;
  await page.keyboard.press('Escape');

  // ── A transcript ─────────────────────────────────────────────────────────
  out.transcript = await page.evaluate(async () => {
    const r = await import('/static/js/chatRenderer.js');
    r.hideWelcomeScreen();
    document.querySelectorAll('.modal').forEach((m) => m.classList.add('hidden'));
    window.__opened = [];
    window.chatModule = window.chatModule || {};
    window.chatModule.openAttachment = (att) => window.__opened.push(att.name);
    const history = document.getElementById('chat-history');
    const before = document.createElement('button');
    before.id = 'b1576-before'; before.textContent = 'before';
    history.appendChild(before);
    const msg = document.createElement('div');
    msg.className = 'msg msg-user';
    const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
    msg.appendChild(r.buildAttachCards([
      { id: 'u1', name: 'notes.pdf', mime: 'application/pdf', size: 2048 },
      { id: 'u2', name: 'cat.png', mime: 'image/png', previewUrl: png },
    ]));
    history.appendChild(msg);
    const reply = document.createElement('div');
    reply.className = 'msg msg-assistant';
    reply.textContent = 'An answer.';
    history.appendChild(reply);
    r.displayMetrics(reply, { response_time: 1.2, input_tokens: 10, output_tokens: 20, model: 'm' });
    return {
      card: !!history.querySelector('.attach-card'),
      image: !!history.querySelector('.attach-image-preview'),
      metrics: !!history.querySelector('.response-metrics'),
    };
  });
  await page.focus('#b1576-before');
  const tReached = [];
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Tab');
    const at = await focused();
    if (at) tReached.push(at.cls);
  }
  out.transcriptReached = tReached;
  await page.focus('#chat-history .attach-card');
  await page.keyboard.press('Enter');
  out.opened = await page.evaluate(() => window.__opened.slice());
  await page.focus('#chat-history .response-metrics');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.ctx-popup');
  out.metricsOpened = true;
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def walked(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("b1576") / "keys.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(walked):
    assert walked["errors"] == [], walked["errors"]


def test_tab_reaches_the_chat_list_and_the_arrows_carry_its_one_stop(walked):
    assert walked["listStops"] == 1, walked["listStops"]
    assert walked["tabbedBackToTheList"] is True
    assert walked["arrowMoved"] is True and walked["stopFollowed"] is True


def test_a_chats_menu_is_buttons(walked):
    menu = walked["chatMenu"]
    assert menu and all(item["tag"] == "BUTTON" for item in menu), menu
    assert any("Rename" in item["text"] for item in menu), menu


def test_tab_through_the_library_reaches_every_card_and_enter_opens_one(walked):
    reached = walked["libReached"]
    for doc in walked["docIds"]:
        assert any(r["doc"] == doc and "doclib-card-open" in r["cls"] and r["tag"] == "BUTTON"
                   for r in reached), (doc, reached)
    assert walked["libOpened"] is True


def test_tab_through_a_transcript_reaches_its_file_its_picture_and_its_timings(walked):
    assert walked["transcript"] == {"card": True, "image": True, "metrics": True}
    reached = " | ".join(walked["transcriptReached"])
    for cls in ("attach-card", "attach-image-preview", "response-metrics"):
        assert cls in reached, (cls, walked["transcriptReached"])
    assert walked["opened"] == ["notes.pdf"], "Enter on the file did not open it"
    assert walked["metricsOpened"] is True
