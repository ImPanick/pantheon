# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1595` — Settings opened before the person's status has answered shows an
admin's and an operator's panels once it does.

Found driving `tests/test_the_servers_in_a_browser.py` with its server held to
a tenth of a CPU (`scratchpad/starve.py` at 0.9): the admin opened Settings,
and the Forge tab — an operator's (`operator-only`) — stayed hidden for the
whole of a 120 s wait. `settings.js`'s `syncAdminVisibility` ran once, when
Settings opened; opened before `GET /api/auth/status` answered (seconds on a
loaded server), it drew the admin as a member, and nothing drew it again until
Settings was opened a second time. The status reaches the page through
`ui_visibility.applyToolVisibility`, whose hook Settings already listens on for
its Appearance rows; the panels follow it there now.

Driven in headless Chromium against the real app (`app_url`), with the status
held back by the browser so Settings is certainly open before it lands — the
race made deterministic, no clock in the assertion.
"""

import json
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
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  await ctx.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const creds = { username: 'ada', password: 'ada-pass-1234' };
  await ctx.request.post(BASE + '/api/auth/setup', { data: creds });
  await ctx.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  // The status is held until Settings is open — a loaded server's seconds.
  let release;
  const held = new Promise((r) => { release = r; });
  await page.route('**/api/auth/status', async (route) => { await held; await route.continue(); });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => !!document.getElementById('rail-settings'), null, { timeout: 90000 });
  await page.evaluate(() => document.getElementById('rail-settings').click());
  await page.waitForSelector('#settings-modal [data-settings-tab="forge"]', { state: 'attached', timeout: 60000 });
  const shown = () => page.evaluate(() => {
    const tab = document.querySelector('#settings-modal [data-settings-tab="forge"]');
    return !!tab && getComputedStyle(tab).display !== 'none';
  });
  out.beforeStatus = await shown();
  const answered = page.waitForResponse((r) => r.url().endsWith('/api/auth/status'), { timeout: 60000 });
  release();
  out.status = (await answered).status();
  out.afterStatus = await page.waitForFunction(() => {
    const tab = document.querySelector('#settings-modal [data-settings-tab="forge"]');
    return !!tab && getComputedStyle(tab).display !== 'none';
  }, null, { timeout: 30000 }).then(() => true, () => false);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("status-pw") / "drive.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=420, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_the_premise_settings_opened_before_the_status_answered(drive):
    """Not shown yet is right: unknown is not an admin (`B1523`)."""
    assert drive["beforeStatus"] is False, "the status was not held — this measures nothing"
    assert drive["status"] == 200


def test_the_admins_panels_appear_when_the_status_lands(drive):
    assert drive["afterStatus"] is True, "the Forge tab stayed hidden from the admin who opened Settings"
    assert drive["errors"] == [], drive["errors"]
