# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1592` — Enter on a chat in the sidebar opens it once.

The chat list's own keydown handler answered Enter with `selectSession`, and
`a11y.js`'s delegated activation answered the same press by clicking the row,
whose click handler calls `selectSession` again: two selections per Enter, so
two `/api/history` fetches and two renders of the transcript. The list's
branch is gone; Enter is the row's click, pressed by `a11y.js`, the one place
every activatable row's Enter is answered.

Driven in Chromium against the real app: two real chats made through the API,
the row focused, Enter pressed, and the history fetches for that chat counted
off the network.
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
  const creds = { username: 'enter', password: 'enter-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  for (const name of ['First chat', 'Second chat']) {
    await page.request.post(BASE + '/api/session', { form: {
      name, endpoint_url: 'http://127.0.0.1:9/v1/chat/completions', model: 'm', skip_validation: '1' } });
  }
  const history = {};          // sid -> [started, finished]
  const sidOf = (url) => { const m = /\/api\/history\/([^/?#]+)/.exec(url); return m ? m[1] : null; };
  page.on('request', (r) => { const s = sidOf(r.url()); if (s) (history[s] = history[s] || [0, 0])[0]++; });
  const done = (r) => { const s = sidOf(r.url()); if (s) (history[s] = history[s] || [0, 0])[1]++; };
  page.on('requestfinished', done);
  page.on('requestfailed', done);

  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 120000 });
  await page.waitForFunction(() => document.querySelectorAll('#session-list .list-item[data-session-id]').length >= 2);
  if (await page.evaluate(() => document.getElementById('sessions-section').classList.contains('collapsed'))) {
    await page.focus('#sessions-section .section-collapse-btn');
    await page.keyboard.press('Enter');
  }
  await page.waitForFunction(() => {
    const r = document.querySelector('#session-list .list-item[data-session-id]');
    return !!r && r.getBoundingClientRect().height > 0;
  });
  // A chat that is not the open one, so pressing it is a real switch.
  const sid = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#session-list .list-item[data-session-id]')];
    const row = rows.find((r) => !r.classList.contains('active-session'));
    return row.dataset.sessionId;
  });
  out.activatable = await page.evaluate((sid) => document.querySelector(
    `#session-list .list-item[data-session-id="${sid}"]`).getAttribute('data-a11y-activatable'), sid);
  const before = (history[sid] || [0, 0])[0];
  await page.evaluate((sid) => document.querySelector(
    `#session-list .list-item[data-session-id="${sid}"]`).focus(), sid);
  await page.keyboard.press('Enter');
  // Every selection fetches the chat's history before it marks the row open,
  // and both selections a press made start in that same press — so once the
  // row is open and every history request started has finished, the count
  // is final. Conditions, not a clock.
  await page.waitForFunction((sid) => {
    const r = document.querySelector(`#session-list .list-item[data-session-id="${sid}"]`);
    return !!r && r.classList.contains('active-session');
  }, sid, { timeout: 20000 });
  for (let i = 0; i < 400; i++) {
    const h = history[sid] || [0, 0];
    if (h[0] > before && h[0] === h[1]) break;
    await page.waitForTimeout(25);
  }
  out.fetchesForOnePress = (history[sid] || [0, 0])[0] - before;
  out.hash = await page.evaluate(() => location.hash);
  out.sid = sid;
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def pressed(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("b1592") / "enter.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(pressed):
    assert pressed["errors"] == []


def test_enter_opens_the_chat(pressed):
    assert pressed["activatable"] == "1", "the row is not one of a11y.js's activatable rows"
    assert pressed["hash"] == "#" + pressed["sid"]


def test_one_enter_is_one_selection(pressed):
    assert pressed["fetchesForOnePress"] == 1, (
        f"one Enter fetched the chat's history {pressed['fetchesForOnePress']} times")
