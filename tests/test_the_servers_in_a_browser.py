# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1258` in a real browser: a server added at its home, Settings → Forge,
is in the Forge's dropdowns and in the Forge's own Settings tab — one editor,
two windows — and a Forge left open in another tab, drawn from the list as it
was, can neither save over it nor post it away.

`tests/test_the_servers_have_one_editor_and_their_own_door.py` drives the
routes. This boots the real app out of process (the harness of
`test_the_forge_hubs_switch_in_a_browser.py`, imported) and drives two tabs of
headless Chromium as an admin would.

Skipped, with the reason, where node, `playwright` or its Chromium is missing.
"""

import json
import os
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402
from test_the_forge_hubs_switch_in_a_browser import world  # noqa: E402,F401  (fixture)

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
  const boot = async () => {
    const p = await ctx.newPage();
    p.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
    await p.goto(BASE + '/', { waitUntil: 'load' });
    await p.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await p.waitForTimeout(800);
    return p;
  };
  const first = await ctx.newPage();
  await first.request.post(BASE + '/api/auth/setup', { data: creds });
  await first.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await first.close();
  const servers = async (p) => (await (await p.request.get(BASE + '/api/cookbook/servers')).json());

  // The stale tab: the Forge's Settings tab open on the list as it is now.
  const stale = await boot();
  await stale.evaluate(() => window.cookbookModule.open({ tab: 'Settings' }));
  await stale.waitForSelector('#cookbook-servers .cookbook-server-entry', { timeout: 30000 });
  out.staleBefore = await stale.evaluate(() => document.querySelectorAll('#cookbook-servers .cookbook-server-entry').length);

  // The home: Settings → Forge, add a server, save it.
  const page = await boot();
  await page.evaluate(() => document.getElementById('rail-settings').click());
  await page.waitForSelector('#settings-modal [data-settings-tab="forge"]', { timeout: 15000 });
  await page.click('#settings-modal [data-settings-tab="forge"]');
  await page.waitForSelector('#set-forgeServers .cookbook-server-entry', { timeout: 30000 });
  out.homeBefore = await page.evaluate(() => document.querySelectorAll('#set-forgeServers .cookbook-server-entry').length);
  await page.click('#set-forgeServers .cookbook-servers-add');
  const fresh = '#set-forgeServers .cookbook-server-entry[data-is-new="1"]';
  await page.waitForSelector(fresh);
  await page.fill(`${fresh} .cookbook-srv-name`, 'Lab box');
  await page.fill(`${fresh} .cookbook-srv-host`, 'me@labbox');
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/cookbook/servers') && r.request().method() === 'PUT');
  await page.click(`${fresh} .cookbook-server-save-btn`);
  out.saveStatus = (await saved).status();
  await page.waitForTimeout(600);
  out.homeAfter = await page.evaluate(() => [...document.querySelectorAll('#set-forgeServers .cookbook-srv-host')].map((i) => i.value));
  out.stored = await servers(page);

  // The Forge in the same tab: its dropdowns and its own Settings tab.
  await page.evaluate(() => window.cookbookModule.open({ tab: 'Search' }));
  await page.waitForSelector('#hwfit-server-select', { timeout: 30000 });
  await page.waitForTimeout(800);
  out.dropdowns = await page.evaluate(() => ['hwfit-server-select', 'hwfit-dl-server', 'hwfit-cache-server', 'hwfit-deps-server']
    .map((id) => { const s = document.getElementById(id); return s && s.tagName === 'SELECT' ? [...s.options].map((o) => o.textContent.replace('● ', '')) : null; }));
  await page.evaluate(() => window.cookbookModule.open({ tab: 'Settings' }));
  await page.waitForSelector('#cookbook-servers .cookbook-server-entry', { timeout: 30000 });
  await page.waitForTimeout(500);
  out.forgeCopy = await page.evaluate(() => [...document.querySelectorAll('#cookbook-servers .cookbook-srv-host')].map((i) => i.value));

  // Back in the stale tab: its whole-state save posts its old list; its editor
  // saves a change made on the old list.
  await stale.evaluate(() => document.dispatchEvent(new CustomEvent('cookbook:state-dirty')));
  await stale.waitForTimeout(1500);
  out.afterStalePost = await servers(stale);
  const answered = stale.waitForResponse((r) => r.url().endsWith('/api/cookbook/servers') && r.request().method() === 'PUT');
  await stale.fill('#cookbook-servers .cookbook-server-entry .cookbook-srv-name', 'Renamed here');
  await stale.press('#cookbook-servers .cookbook-server-entry .cookbook-srv-name', 'Tab');
  out.staleSave = (await answered).status();
  await stale.waitForTimeout(600);
  out.staleRedrawn = await stale.evaluate(() => ({
    hosts: [...document.querySelectorAll('#cookbook-servers .cookbook-srv-host')].map((i) => i.value),
    said: document.querySelector('#cookbook-servers .cookbook-servers-said').textContent,
  }));
  out.afterStaleSave = await servers(stale);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(world, tmp_path_factory):
    work = tmp_path_factory.mktemp("servers-pw")
    script = work / "drive.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    env = dict(os.environ)
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(var, None)
    proc = subprocess.run([NODE, str(script), world["url"]], capture_output=True,
                          text=True, timeout=420, cwd=str(work), env=env)
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_a_server_added_at_home_is_in_the_forge(drive):
    assert drive["errors"] == [], drive["errors"]
    assert drive["homeBefore"] == 1 and drive["staleBefore"] == 1, "a fresh install: Local only"
    assert drive["saveStatus"] == 200
    assert drive["homeAfter"] == ["", "me@labbox"]
    assert [s["host"] for s in drive["stored"]["servers"]] == ["", "me@labbox"] and drive["stored"]["rev"] == 1
    for options in drive["dropdowns"]:
        if options is not None:
            assert "Lab box" in options, drive["dropdowns"]
    assert drive["dropdowns"][0] is not None, "the scan's own dropdown is drawn"
    assert drive["forgeCopy"] == ["", "me@labbox"], "the Forge's Settings tab is the same editor, the same list"


def test_a_stale_forge_tab_cannot_overwrite_it(drive):
    assert [s["host"] for s in drive["afterStalePost"]["servers"]] == ["", "me@labbox"], \
        "its whole-state save left the servers alone"
    assert drive["staleSave"] == 409
    assert drive["staleRedrawn"]["hosts"] == ["", "me@labbox"], "it draws the list as it is now"
    assert "another window" in drive["staleRedrawn"]["said"]
    assert [s["host"] for s in drive["afterStaleSave"]["servers"]] == ["", "me@labbox"]
    assert drive["afterStaleSave"]["rev"] == 1
