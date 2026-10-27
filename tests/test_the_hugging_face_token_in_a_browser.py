# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1258` in a real browser: the Hugging Face token set at its home, Settings →
Forge, is the token the Forge's own Settings tab shows — one editor, two
windows — and the `allow_model_download` door lands on its one control.

`tests/test_the_hugging_face_token_has_one_editor_and_its_own_door.py` drives
the routes and the module under node. This boots the real app out of process
(the harness of `test_the_forge_hubs_switch_in_a_browser.py`, imported) and
drives it in headless Chromium as an admin would.

Skipped, with the reason, where node, `playwright` or its Chromium is missing.
"""

import json
import os
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402
from test_the_forge_hubs_switch_in_a_browser import world  # noqa: E402,F401  (fixture)

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

TOKEN = "hf_browserDriveToken0987"

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const TOKEN = process.argv[3];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  await ctx.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  const creds = { username: 'ada', password: 'ada-pass-1234' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1000);

  // Settings → Forge, its home.
  await page.evaluate(() => document.getElementById('rail-settings').click());
  await page.waitForSelector('#settings-modal [data-settings-tab="forge"]', { timeout: 15000 });
  await page.click('#settings-modal [data-settings-tab="forge"]');
  await page.waitForSelector('#set-forgeHfTokenInput', { timeout: 15000 });
  await page.waitForTimeout(500);
  const status = () => page.evaluate(() =>
    document.querySelector('#set-forgeHfToken [role="status"]').textContent);
  out.before = await status();
  out.download = await page.evaluate(() => document.getElementById('set-forgeModelDownload').textContent);
  await page.fill('#set-forgeHfTokenInput', TOKEN);
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/cookbook/hf-token') && r.request().method() === 'PUT');
  await page.click('#set-forgeHfToken button:has-text("Save")');
  out.saveStatus = (await saved).status();
  await page.waitForTimeout(300);
  out.after = await status();
  out.inputAfter = await page.inputValue('#set-forgeHfTokenInput');
  out.stored = await (await page.request.get(BASE + '/api/cookbook/hf-token')).json();
  out.stateHasIt = (await (await page.request.get(BASE + '/api/cookbook/state')).text()).includes(TOKEN);

  // The door to the other Hugging Face switch lands on it.
  await page.click('#settings-modal [data-forge-door="settings:system"]');
  await page.waitForTimeout(1500);
  out.focused = await page.evaluate(() => document.activeElement && document.activeElement.id);

  // The Forge's own Settings tab: the same editor, saying the same thing.
  await page.evaluate(() => window.cookbookModule.open({ tab: 'Settings' }));
  await page.waitForSelector('#cookbook-hf-token-input', { timeout: 30000 });
  await page.waitForTimeout(800);
  out.forge = await page.evaluate(() => ({
    said: document.querySelector('#cookbook-hf-token [role="status"]').textContent,
    oldField: !!document.getElementById('hwfit-hftoken'),
    label: document.querySelector('label[for="cookbook-hf-token-input"]')?.textContent || null,
  }));
  // Removing it in the Forge is seen at home.
  await page.click('#cookbook-hf-token button:has-text("Remove")');
  await page.waitForTimeout(600);
  out.afterRemove = (await (await page.request.get(BASE + '/api/cookbook/hf-token')).json()).configured;
  out.homeAfterRemove = await status();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def drive(world, tmp_path_factory):
    work = tmp_path_factory.mktemp("hf-token-pw")
    script = work / "drive.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    env = dict(os.environ)
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(var, None)
    proc = subprocess.run([NODE, str(script), world["url"], TOKEN], capture_output=True,
                          text=True, timeout=300, cwd=str(work), env=env)
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_the_token_is_set_at_its_home_and_kept_encrypted_unseen(drive):
    assert drive["before"].startswith("None stored."), drive["before"]
    assert drive["saveStatus"] == 200
    assert drive["after"].startswith("Saved. Stored (hf_b...0987)."), drive["after"]
    assert drive["inputAfter"] == "", "the field does not keep the token"
    assert drive["stored"] == {"configured": True, "masked": "hf_b...0987", "from_environment": False}
    assert drive["stateHasIt"] is False, "the Forge's state never carries it back"


def test_the_forge_shows_the_same_token_through_the_same_editor(drive):
    assert drive["forge"]["oldField"] is False
    assert drive["forge"]["label"] == "Hugging Face token"
    assert drive["forge"]["said"] == "Stored (hf_b...0987). Downloads of gated and private models use it."
    assert drive["afterRemove"] is False
    assert drive["homeAfterRemove"].startswith("None stored."), "the other window's copy follows"


def test_the_other_hugging_face_switch_is_read_here_and_its_door_lands_on_it(drive):
    assert drive["download"].startswith("Shipped default: off."), drive["download"]
    assert drive["focused"] == "set-envflag-allow_model_download"


def test_nothing_broke_on_the_page(drive):
    assert drive["errors"] == [], drive["errors"]
