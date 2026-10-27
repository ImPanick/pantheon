# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1573` in a real browser: a member adds a service connection of their own
in Workbench → MCP & Integrations, as an admin would — without the *Shared*
switch, told where it is called from — and sees an admin's shared one
read-only, told their agents do not call it.

`tests/test_a_members_own_connection_is_called_from_their_workstation.py`
drives the routes, the dispatcher and the workstation. This boots the real app
out of process (the harness of `test_the_forge_hubs_switch_in_a_browser.py`,
imported) and drives headless Chromium as the member. The app has no
workstation, so the member is told their agents cannot call it yet.

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
  const admin = { username: 'ada', password: 'ada-pass-1234' };
  const member = { username: 'mia', password: 'mia-pass-1234' };
  const fresh = async () => {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
    await ctx.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    return ctx;
  };

  // The admin: the install, a member, and a connection shared with everyone.
  const actx = await fresh();
  const ap = await actx.newPage();
  await ap.request.post(BASE + '/api/auth/setup', { data: admin });
  await ap.request.post(BASE + '/api/auth/login', { data: { ...admin, remember: true } });
  out.memberMade = (await ap.request.post(BASE + '/api/auth/users', { data: { ...member, is_admin: false } })).status();
  out.sharedMade = (await ap.request.post(BASE + '/api/auth/integrations', {
    data: { name: 'House API', base_url: 'http://house.lan:8080', auth_type: 'bearer', api_key: 'HOUSE-KEY-1', shared: true } })).status();

  // The member, in a browser of their own.
  const mctx = await fresh();
  const page = await mctx.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  await page.request.post(BASE + '/api/auth/login', { data: { ...member, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(800);
  await page.evaluate(() => document.getElementById('rail-workbench').click());
  await page.waitForSelector('#workbench-rooms [data-room="integrations"]', { timeout: 30000 });
  await page.click('#workbench-rooms [data-room="integrations"]');
  await page.waitForSelector('#unified-intg-add-btn', { state: 'visible', timeout: 30000 });
  await page.waitForSelector('#unified-integrations-list .intg-card[data-intg-type="api"]', { timeout: 30000 });
  const cards = async () => page.evaluate(() => [...document.querySelectorAll('#unified-integrations-list .intg-card[data-intg-type="api"]')]
    .map((c) => ({ name: c.querySelector('.intg-card-open').textContent.trim(),
                   detail: c.querySelector(':scope > div > div:nth-child(2)').textContent.trim(),
                   removable: !!c.querySelector('.intg-del-btn') })));
  out.before = await cards();

  // Add one: API Service.
  await page.click('#unified-intg-add-btn');
  await page.waitForSelector('.uf-type-option[data-value="api"]', { state: 'visible' });
  await page.click('.uf-type-option[data-value="api"]');
  await page.waitForSelector('#uf-api-name', { state: 'visible' });
  await page.waitForTimeout(400);
  out.sharedRowHidden = await page.evaluate(() => document.getElementById('uf-api-shared-row').hidden);
  out.newNote = await page.evaluate(() => { const n = document.getElementById('uf-api-readonly'); return n.hidden ? null : n.textContent; });
  await page.fill('#uf-api-name', "Mia's Gitea");
  await page.fill('#uf-api-url', 'http://gitea.mia.lan:3000');
  await page.fill('#uf-api-key', 'MIA-KEY-9');
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/auth/integrations') && r.request().method() === 'POST');
  await page.click('#uf-api-save');
  const res = await saved;
  out.saveStatus = res.status();
  out.saved = await res.json();
  await page.waitForTimeout(800);
  out.after = await cards();

  // Open it again from its card: where it is called from, said.
  await page.click('#uf-api-cancel');
  await page.click("#unified-integrations-list .intg-card[data-intg-type=\"api\"] .intg-card-open >> text=Mia's Gitea");
  await page.waitForSelector('#uf-api-name', { state: 'visible' });
  await page.waitForTimeout(600);
  out.ownNote = await page.evaluate(() => document.getElementById('uf-api-readonly').textContent);

  // The admin's shared one: read-only, and not the member's agents'.
  await page.click('#uf-api-cancel');
  await page.click('#unified-integrations-list .intg-card[data-intg-type="api"] .intg-card-open >> text=House API');
  await page.waitForSelector('#uf-api-name', { state: 'visible' });
  await page.waitForTimeout(600);
  out.shared = await page.evaluate(() => ({
    note: document.getElementById('uf-api-readonly').textContent,
    nameDisabled: document.getElementById('uf-api-name').disabled,
    saveHidden: document.getElementById('uf-api-save').hidden,
    testHidden: document.getElementById('uf-api-test').hidden,
  }));
  out.stored = await (await ap.request.get(BASE + '/api/auth/integrations')).json();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drove(world, tmp_path_factory):
    work = tmp_path_factory.mktemp("member-connection-pw")
    script = work / "drive.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    env = dict(os.environ)
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(var, None)
    proc = subprocess.run([NODE, str(script), world["url"]], capture_output=True,
                          text=True, timeout=420, cwd=str(work), env=env)
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_the_member_adds_one_without_a_shared_switch_and_is_told_where_it_is_called_from(drove):
    assert (drove["memberMade"], drove["sharedMade"]) == (200, 200)
    assert drove["sharedRowHidden"] is True
    assert drove["newNote"] == ("Yours alone: your agents call it from your workstation, "
                                "and the server makes no request for it.")
    assert drove["saveStatus"] == 200, drove["saved"]
    made = drove["saved"]["integration"]
    assert (made["owner"], made["shared"], made["called_from"]) == ("mia", False, "workstation")
    mine = next(c for c in drove["after"] if c["name"] == "Mia's Gitea")
    assert mine["detail"] == "http://gitea.mia.lan:3000 · called from your workstation" and mine["removable"]
    assert drove["ownNote"] == ("Yours alone, called from your workstation — and this account has none "
                                "turned on, so your agents cannot call it yet. Ask an admin for one.")
    assert drove["errors"] == []


def test_the_admins_shared_one_is_read_only_and_not_the_members_agents(drove):
    assert [c["name"] for c in drove["before"]] == ["House API"]
    house = drove["before"][0]
    assert house["detail"] == "http://house.lan:8080 · shared by ada" and not house["removable"]
    assert drove["shared"] == {
        "note": ("Shared by ada: the server uses it for reminders and briefs. Your agents call only your "
                 "own connections, from your workstation. Only ada can change or remove it."),
        "nameDisabled": True, "saveHidden": True, "testHidden": True}


def test_the_admin_never_sees_the_members_own(drove):
    assert [i["name"] for i in drove["stored"]["integrations"]] == ["House API"]
