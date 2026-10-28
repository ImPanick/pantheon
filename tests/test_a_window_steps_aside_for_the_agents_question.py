# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1586` — a window lying over the agent's question steps aside for it, and
comes back when it is answered.

At 1440×900 the agent browser (1040×780) and the Design window (980×820) lie
over the chat column, where the agent's question is drawn; Chromium reported
the window taking the press on *Allow* (`P25-00`, `P26-00` — those drives are
the row's `Verify:` and pass now). This holds the window manager's half in
detail: the real `renderAskUserCard` announces the question, the real
`modalManager` lowers the window over it — the way the window's own `_` does,
nothing restacked — the card says which, the window is back when the card is
answered, and a window the person brought back themselves is theirs.

Driven in headless Chromium: the real modules and `static/style.css`, served
to a page with a chat column and one tool window over it; every `/api/` answer
is empty.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const STATIC = process.argv[2];
// The measured case: at 1440×900 a 1040×780 window over the chat column.
const PAGE = '<!doctype html><html><head><link rel="stylesheet" href="/static/style.css"></head><body>'
  + '<div id="chat-container" style="position:fixed;inset:0;display:flex;flex-direction:column">'
  + '<div id="chat-history" style="flex:1 1 auto;width:100%;overflow-y:auto">'
  + '<div style="height:1400px">earlier turns</div></div>'
  + '<textarea id="message" style="height:48px"></textarea></div>'
  + '<div id="design-modal" class="modal" style="display:flex">'
  + '<div class="modal-content" style="position:fixed;left:200px;top:60px;width:1040px;height:780px;'
  + 'max-width:none;max-height:none">'
  + '<div class="modal-header"><h3>Design</h3><button class="close-btn" type="button">x</button></div>'
  + '<p>the design</p></div></div></body></html>';
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String(e.message || e)));
  await page.route('http://t.local/**', (route) => {
    const u = new URL(route.request().url());
    if (u.pathname === '/') return route.fulfill({ contentType: 'text/html', body: PAGE });
    if (u.pathname.startsWith('/api/')) return route.fulfill({ contentType: 'application/json', body: '{}' });
    const file = path.join(STATIC, u.pathname.replace(/^\/static\//, ''));
    if (!file.startsWith(STATIC) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ contentType: file.endsWith('.css') ? 'text/css' : 'text/javascript',
                           body: fs.readFileSync(file) });
  });
  await page.goto('http://t.local/');
  // The end state is the subject, not a window's opening animation.
  await page.addStyleTag({ content: '*, *::before, *::after { animation: none !important; transition: none !important; }' });
  await page.evaluate(async () => {
    window.__mm = await import('/static/js/modalManager.js?v=20261009census');
    window.__cr = await import('/static/js/chatRenderer.js');
  });
  const ask = (id) => page.evaluate((id) => {
    const card = window.__cr.renderAskUserCard({
      kind: 'tool_approval', approval_id: id, question: 'Allow this exact action once?',
      options: [{ label: 'Allow once', value: 'approve' }, { label: 'Deny', value: 'deny' }],
      action: { tool: 'write_file', content: 'design/shop/index.html' },
    }, { scroll: false });
    return !!card;
  }, id);
  const state = () => page.evaluate(() => {
    const m = document.getElementById('design-modal');
    const allow = document.querySelector('.ask-user-card button[data-decision="approve"]');
    let onTop = null;
    if (allow) {
      allow.scrollIntoView({ block: 'nearest' });
      const r = allow.getBoundingClientRect();
      const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      onTop = at ? (at.closest('.ask-user-card') ? 'card' : (at.closest('.modal') || {}).id || at.tagName) : null;
    }
    return {
      lowered: m.classList.contains('modal-minimized') && m.classList.contains('hidden'),
      minimized: window.__mm.isMinimized('design-modal'),
      onTop,
      note: [...document.querySelectorAll('.ask-user-lowered-note')].map((n) => n.textContent),
      cards: document.querySelectorAll('.ask-user-card').length,
    };
  });
  const answer = (decision) => page.evaluate((d) => {
    document.querySelector(`.ask-user-card button[data-decision="${d}"]`).click();
  }, decision);
  const settle = () => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0))));

  // Over the chat at the start: the window covers where Allow would be.
  out.before = await page.evaluate(() => {
    const r = document.getElementById('chat-history').getBoundingClientRect();
    const at = document.elementFromPoint(r.left + r.width / 2, r.bottom - 40);
    return (at && at.closest('.modal') || {}).id || '';
  });
  // 1. Asked: the window steps aside, the card says so, and Allow is on top.
  await ask('a1');
  out.asked = await state();
  // 2. Answered: the window is back.
  await answer('approve');
  await settle();
  out.answered = await state();
  // 3. Asked twice in a row: one card replaces the last, and the window stays
  //    aside until the second is answered.
  await ask('a2');
  await ask('a3');
  await settle();
  out.replaced = await state();
  await answer('deny');
  await settle();
  out.afterSecond = await state();
  // 4. The person brings the window back while the question waits: it is
  //    theirs, and answering leaves it as they left it — here, lowered again
  //    by their own `_`.
  await ask('a4');
  await page.evaluate(() => window.__mm.restore('design-modal'));
  await page.evaluate(() => window.__mm.minimize('design-modal'));
  await answer('approve');
  await settle();
  out.theirs = await state();
  await page.evaluate(() => window.__mm.restore('design-modal'));
  // 5. A window that does not lie over the question is left alone.
  await page.evaluate(() => {
    const c = document.querySelector('#design-modal .modal-content');
    c.style.left = '1100px'; c.style.top = '0px'; c.style.width = '300px'; c.style.height = '200px';
  });
  await ask('a5');
  out.clear = await state();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drove(tmp_path_factory):
    d = tmp_path_factory.mktemp("b1586")
    (d / "run.cjs").write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(d / "run.cjs"), str(STATIC)], capture_output=True, text=True,
                          timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(drove):
    assert drove["errors"] == [], drove["errors"]


def test_the_window_lay_over_the_chat_to_begin_with(drove):
    assert drove["before"] == "design-modal", "the drive's window does not cover the chat"


def test_asked_the_window_steps_aside_and_the_card_says_so(drove):
    s = drove["asked"]
    assert s["lowered"] and s["minimized"], s
    assert s["onTop"] == "card", s
    assert s["note"] == ["“Design” is lowered so you can answer this; it comes back when you do."], s


def test_answered_the_window_comes_back(drove):
    s = drove["answered"]
    assert s["cards"] == 0 and not s["lowered"] and not s["minimized"], s


def test_a_question_that_replaces_another_keeps_the_window_aside_until_it_is_answered(drove):
    assert drove["replaced"]["cards"] == 1 and drove["replaced"]["lowered"], drove["replaced"]
    assert drove["replaced"]["onTop"] == "card", drove["replaced"]
    assert not drove["afterSecond"]["lowered"], drove["afterSecond"]


def test_a_window_the_person_took_back_is_left_as_they_left_it(drove):
    assert drove["theirs"]["minimized"], drove["theirs"]


def test_a_window_that_is_not_over_the_question_is_left_alone(drove):
    s = drove["clear"]
    assert not s["lowered"] and s["note"] == [] and s["onTop"] == "card", s
