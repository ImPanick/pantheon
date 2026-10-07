# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-9`, its early fetch): the chat list, and the chat the
address names, are asked for while the modules are still loading.

Measured on `32df791` (seeded showcase, a deep-linked chat, three cold loads):
`/api/sessions` was sent at DOMContentLoaded (0.92–1.17 s) — only once every
module had evaluated — and `/api/history/<id>` 0.12–0.2 s after it; the chat
drew at 1.45–1.68 s. Now an inline script ahead of the module tags starts both,
and `sessions.js` takes each answer when its URL is the one it would ask for.
Driven in the real app in Chromium: each is asked for exactly once (the module
did not ask again), and while the page was still being parsed — before any
module ran (`domInteractive`).
"""

import json
import os
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'helper', password: 'helper-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  // A chat to link to.
  const made = await page.request.post(BASE + '/api/session', {
    form: { name: 'Linked chat', endpoint_url: 'http://127.0.0.1:9/v1/chat/completions', model: 'm', skip_validation: '1' } });
  out.made = made.status();
  const sid = (await made.json()).id;
  out.sid = sid;
  await page.goto(BASE + '/#' + sid, { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(2500);
  out.timing = await page.evaluate((id) => {
    const nav = performance.getEntriesByType('navigation')[0];
    const dcl = nav.domContentLoadedEventStart;
    const pick = (re) => performance.getEntriesByType('resource')
      .filter(r => re.test(r.name)).map(r => Math.round(r.startTime));
    const app = performance.getEntriesByType('resource').find(r => /\/static\/app\.js/.test(r.name));
    return {
      dcl: Math.round(dcl),
      appJsEnd: app ? Math.round(app.responseEnd) : null,
      // The parser is done here; module scripts run after it.
      parsed: Math.round(nav.domInteractive),
      sessions: pick(/\/api\/sessions(\?|$)/),
      history: pick(new RegExp('/api/history/' + id + '(\\?|$)')),
    };
  }, sid);
  out.current = await page.evaluate(() => window.sessionModule && window.sessionModule.getCurrentSessionId
    ? window.sessionModule.getCurrentSessionId() : null);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def file_database(tmp_path_factory):
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_path_factory.mktemp("early-db") / "app.db")
    yield
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def drive(file_database, app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("early-pw") / "early.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_the_chat_list_is_asked_for_once_and_before_the_modules_are_done(drive):
    t = drive["timing"]
    assert len(t["sessions"]) == 1, t
    # Asked for while the page was still being parsed — before any module ran.
    assert t["sessions"][0] < t["parsed"], t


def test_the_linked_chat_is_asked_for_once_and_early(drive):
    t = drive["timing"]
    assert len(t["history"]) == 1, t
    assert t["history"][0] < t["parsed"], t


def test_the_linked_chat_is_the_one_open(drive):
    assert drive["current"] == drive["sid"]
    assert drive["errors"] == []
