# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1530` — a forked chat is marked by one drawn fork, not by a font's U+2ADD.

**What was wrong.** `sessions.js` drew a fork's sidebar icon as the text `⫝`
(U+2ADD) and `POST /api/session/{id}/fork` named the new chat `"⫝ <name>"`, so
the header, the toast and every list that shows a name drew the character too —
and what a character looks like is the font's business: `B1204`'s audit saw ⫝
in the toast and ⤓ in the header and the row, on one screen. The message action
that makes a fork drew the same character. The agent's own fork
(`manage_session`) meanwhile named its forks `"Fork: <name>"`: two spellings of
one fact.

**Now**, driven at 1440×900 through the real app (`Law 20`) — a chat with two
messages, forked from the message's own action:

  * the route names the fork `"Fork: <name>"`, the agent's spelling;
  * the toast reads *Forked → <name>* — no glyph, the word says it;
  * the sidebar row, the chat's header and the action that made it draw the
    SAME drawn fork (`icons.js` `FORK_GLYPH`), and none of them, nor the row's
    tooltip, carries U+2ADD;
  * the header's name is the name without its prefix, and a screen reader
    hears "Fork:" before it;
  * a chat stored under the old `"⫝ <name>"` still reads as a fork, with the
    same mark (`Law 1`: nobody's history is renamed).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402
from test_a_skill_card_keeps_its_name_beside_its_pills import (  # noqa: F401,E402
    PASSWORD, USER, app_url,
)

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
const { chromium } = require('playwright');
const [BASE, USER, PASSWORD] = process.argv.slice(2);
const GLYPHS = /[⫝⤓]/;
const marks = (root) => [...root.querySelectorAll('svg')].map((s) => s.innerHTML);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  await (await browser.newContext()).request.post(BASE + '/api/auth/setup',
    { data: { username: USER, password: PASSWORD } });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  await context.request.post(BASE + '/api/auth/login', { data: { username: USER, password: PASSWORD, remember: true } });
  const chat = async (name) => {
    const r = await context.request.post(BASE + '/api/session', { multipart: {
      name, endpoint_url: 'http://127.0.0.1:9/v1', model: 'demo-model', skip_validation: 'true' } });
    if (!r.ok()) throw new Error('could not make a chat: ' + r.status() + ' ' + await r.text());
    return (await r.json()).id;
  };
  const source = await chat('Budget for May');
  for (const [role, content] of [['user', 'What is the budget?'], ['assistant', 'About four hundred.']]) {
    const r = await context.request.post(BASE + '/api/session/' + source + '/message', { data: { role, content } });
    if (!r.ok()) throw new Error('could not add a message: ' + r.status());
  }
  const legacy = await chat('⫝ Old plan');   // a fork as the route used to name one
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String(e)));
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForSelector(`.list-item[data-session-id="${source}"]`, { state: 'attached', timeout: 30000 });
  await page.evaluate((id) => document.querySelector(`.list-item[data-session-id="${id}"]`).click(), source);
  await page.waitForSelector('#chat-history .msg-ai .msg-actions', { timeout: 30000 });
  await page.waitForTimeout(500);
  // The message's own Fork action — on the row, or in its overflow menu.
  const forkWasShown = await page.evaluate(() => !!document.querySelector('#chat-history .msg-ai [data-action="fork"]'));
  if (!forkWasShown) {
    await page.evaluate(() => document.querySelector('#chat-history .msg-ai .msg-more-btn').click());
    await page.waitForSelector('.msg-overflow-item[title="Fork"]', { timeout: 10000 });
  }
  out.action = await page.evaluate(() => {
    const b = document.querySelector('#chat-history .msg-ai [data-action="fork"]')
      || document.querySelector('.msg-overflow-item[title="Fork"]');
    return { text: b.textContent, svgs: [...b.querySelectorAll('svg')].map((s) => s.innerHTML) };
  });
  await page.evaluate(() => (document.querySelector('#chat-history .msg-ai [data-action="fork"]')
    || document.querySelector('.msg-overflow-item[title="Fork"]')).click());
  await page.waitForFunction(() => [...document.querySelectorAll('.toast')].some((n) => /Forked/.test(n.textContent)),
    null, { timeout: 30000 });
  await page.waitForTimeout(700);
  out.fork = await page.evaluate(({ source, legacy }) => {
    const toast = [...document.querySelectorAll('.toast')].find((n) => /Forked/.test(n.textContent));
    const row = document.querySelector('.list-item.active-session');
    const meta = document.getElementById('current-meta');
    const old = document.querySelector(`.list-item[data-session-id="${legacy}"]`);
    const rowOf = (r) => ({ id: r.dataset.sessionId, label: r.querySelector('.grow').textContent,
      tip: r.querySelector('.grow').title, text: r.textContent,
      svgs: [...r.querySelector('.session-icon').querySelectorAll('svg')].map((s) => s.innerHTML),
      iconName: r.querySelector('.session-icon').getAttribute('aria-label'),
      shown: !!r.offsetParent && r.getBoundingClientRect().width > 0 });
    return { toast: toast.textContent, row: rowOf(row), old: rowOf(old), source,
             header: { text: meta.textContent, svgs: [...meta.querySelectorAll('svg')].map((s) => s.innerHTML),
                       spoken: meta.querySelector('[aria-label]') && meta.querySelector('[aria-label]').getAttribute('aria-label') } };
  }, { source, legacy });
  // The header's own Rename, abandoned two ways: Escape, and leaving the
  // field with the name unchanged.
  out.renamed = {};
  for (const how of ['Escape', 'unchanged']) {
    await page.evaluate(() => document.getElementById('export-rename-btn').click());
    await page.waitForSelector('#current-meta input.session-rename-input', { timeout: 10000 });
    if (how === 'Escape') await page.keyboard.press('Escape');
    else await page.evaluate(() => document.querySelector('#current-meta input.session-rename-input').blur());
    await page.waitForTimeout(400);
    out.renamed[how] = await page.evaluate(() => {
      const m = document.getElementById('current-meta');
      return { text: m.textContent, input: !!m.querySelector('input'),
               svgs: [...m.querySelectorAll('svg')].map((s) => s.innerHTML) };
    });
  }
  const list = await (await context.request.get(BASE + '/api/sessions')).json().catch(() => null);
  const all = Array.isArray(list) ? list : (list && (list.sessions || list.items)) || [];
  out.names = all.map((s) => s.name);
  out.forkId = out.fork.row.id;
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("fork-mark")
    script = d / "fork.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _glyph_free(*texts):
    return not any(ch in t for t in texts for ch in ("⫝", "⤓"))


def test_the_route_names_a_fork_the_way_the_agent_does(measured):
    assert measured["errors"] == []
    assert measured["forkId"] != measured["fork"]["source"], "the fork opened the source, not a new chat"
    assert "Fork: Budget for May" in measured["names"], measured["names"]


def test_the_toast_says_forked_and_the_name_with_no_glyph(measured):
    toast = measured["fork"]["toast"]
    assert toast.startswith("Forked → Budget for May"), toast
    assert _glyph_free(toast), toast


def test_the_row_the_header_and_the_action_draw_one_mark(measured):
    row, header, action = measured["fork"]["row"], measured["fork"]["header"], measured["action"]
    assert len(row["svgs"]) == 1 and len(header["svgs"]) == 1 and len(action["svgs"]) == 1, (
        row["svgs"], header["svgs"], action["svgs"])
    assert row["svgs"][0] == header["svgs"][0] == action["svgs"][0], (
        "the fork is drawn differently in different places")
    assert '<circle cx="12" cy="19" r="2">' in row["svgs"][0], row["svgs"][0]   # icons.js FORK_GLYPH
    assert _glyph_free(row["text"], row["tip"], header["text"], action["text"])
    assert row["shown"], "the fork's row is not on screen at 1440"


def test_the_header_names_the_chat_and_says_fork_in_words(measured):
    header = measured["fork"]["header"]
    assert header["text"] == "Budget for May", header
    assert header["spoken"] == "Fork:", header
    assert measured["fork"]["row"]["label"] == "Budget for May"
    assert measured["fork"]["row"]["iconName"] == "Fork"


@pytest.mark.parametrize("how", ["Escape", "unchanged"])
def test_a_header_rename_given_up_puts_the_mark_back(measured, how):
    """The top bar's Rename swaps the header for a field, and giving it up put
    the header back as its TEXT — and the drawn fork has none, so a fork's
    header lost its mark until the next chat switch repainted it. The header is
    put back as it was (`static/app.js`, the Rename handler)."""
    got, header = measured["renamed"][how], measured["fork"]["header"]
    assert not got["input"], got
    assert got["text"] == header["text"] and got["svgs"] == header["svgs"], (got, header)


def test_a_chat_forked_under_the_old_name_is_still_a_fork(measured):
    old, row = measured["fork"]["old"], measured["fork"]["row"]
    assert old["label"] == "Old plan", old
    assert old["svgs"] == row["svgs"], "a stored ⫝ fork is drawn with a different mark"
    assert _glyph_free(old["label"], old["tip"])
