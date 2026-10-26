# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1185` — a reload keeps the windows minimised to the dock.

`static/js/modalManager.js` kept which windows were minimised in `_state`, in
memory only; `_saveDockState` wrote the dock's position and the free chips'
positions and nothing else, so a reload brought back neither the chips nor the
windows (`NAV-M-19`'s second half). The back stack (`P23-01`) restores the
windows that were *open*; a minimised window is off it by design.

Now the dock state names the minimised windows, each with the tab it was on,
and a load draws their chips again. A chip from the last load opens its window
through the opener a reload uses (`backStack.setOpeners`, `app.js`) when it is
pressed, not at boot: the row held the fix back over "every such tool opened at
boot to be minimised again", and that cost is not paid — measured here as no
window drawn by the load. The Document pane is not among them: it has its own
per-chat state (`document.js:_markDocVisibleState`) and comes back as a chip
with its chat already.

The row's `Verify:` — *minimise two windows, reload — both chips are back and
each restores its window* — driven in headless Chromium on the real app,
booted as `tests/test_the_command_palette_in_a_browser.py` boots it.
"""
import json
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const admin = { username: 'boss', password: 'boss-pass-123' };
  const setup = await browser.newContext();
  await setup.request.post(BASE + '/api/auth/setup', { data: admin });
  await setup.close();
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
  out.login = (await page.request.post(BASE + '/api/auth/login', { data: { ...admin, remember: true } })).status();

  const boot = async () => {
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(2500);
  };
  const shown = (id) => page.evaluate((id) => {
    const el = document.getElementById(id);
    return !!el && !el.classList.contains('hidden') && !el.classList.contains('modal-minimized')
      && el.style.display !== 'none';
  }, id);
  const chips = () => page.evaluate(() =>
    [...document.querySelectorAll('.minimized-dock-chip')].map((c) => c.dataset.modalId));
  // Press a control if it is there; a missing one is an answer, not a crash.
  const press = (sel) => page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (el) el.click();
    return !!el;
  }, sel);
  const minimise = async (id) => {
    await page.evaluate((id) => document.querySelector('#' + id + ' .modal-minimize-btn').click(), id);
    await page.waitForFunction((id) => !!document.querySelector(
      '.minimized-dock-chip[data-modal-id="' + id + '"]'), id, { timeout: 10000 });
  };

  await page.goto(BASE + '/', { waitUntil: 'load' });
  await boot();

  // Calendar, by its sidebar door.
  await page.evaluate(() => document.getElementById('tool-calendar-btn').click());
  await page.waitForFunction(() => {
    const m = document.getElementById('calendar-modal');
    return m && !m.classList.contains('hidden') && m.querySelector('.modal-minimize-btn');
  }, null, { timeout: 15000 });
  await minimise('calendar-modal');

  // Settings, on a panel that is not its first.
  await page.evaluate(() => document.getElementById('rail-settings').click());
  await page.waitForFunction(() => {
    const m = document.getElementById('settings-modal');
    return m && !m.classList.contains('hidden')
      && m.querySelectorAll('[data-settings-tab]').length > 2 && m.querySelector('.modal-minimize-btn');
  }, null, { timeout: 15000 });
  out.tab = await page.evaluate(() => {
    const tabs = [...document.querySelectorAll('#settings-modal [data-settings-tab]')];
    const pick = tabs.find((b) => !b.classList.contains('active') && b.offsetParent !== null) || tabs[2];
    pick.click();
    return pick.dataset.settingsTab;
  });
  await page.waitForTimeout(300);
  await minimise('settings-modal');

  out.before = await chips();
  out.stored = await page.evaluate(() => JSON.parse(localStorage.getItem('pantheon.mobileDockState.v1') || 'null'));

  // The reload.
  await page.reload({ waitUntil: 'load' });
  await boot();
  out.after = await chips();
  out.openAtBoot = { calendar: await shown('calendar-modal'), settings: await shown('settings-modal') };
  out.badge = await page.evaluate(() => {
    const b = document.getElementById('rail-calendar');
    return !!b && b.classList.contains('rail-minimized');
  });

  // Each chip restores its window.
  await press('.minimized-dock-chip[data-modal-id="calendar-modal"] .minimized-dock-restore');
  await page.waitForTimeout(1500);
  out.calendarOpened = await shown('calendar-modal');
  out.chipsAfterCalendar = await chips();
  await press('#calendar-modal .modal-minimize-btn');
  await page.waitForTimeout(300);

  await press('.minimized-dock-chip[data-modal-id="settings-modal"] .minimized-dock-restore');
  await page.waitForTimeout(1500);
  out.settingsOpened = await shown('settings-modal');
  out.settingsTab = await page.evaluate(() =>
    document.querySelector('#settings-modal [data-settings-tab].active')?.dataset?.settingsTab || null);

  // A chip from the last load closed with its × stays closed across the next.
  await press('#settings-modal .modal-minimize-btn');
  await page.waitForTimeout(300);
  await page.reload({ waitUntil: 'load' });
  await boot();
  out.secondReload = await chips();
  await press('.minimized-dock-chip[data-modal-id="settings-modal"] .minimized-dock-x');
  await page.waitForTimeout(300);
  await page.reload({ waitUntil: 'load' });
  await boot();
  out.thirdReload = await chips();
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def run(app_url, tmp_path_factory):  # noqa: F811
    if NODE is None:
        pytest.skip(_SKIP)
    script = tmp_path_factory.mktemp("dock-reload") / "dock.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_premise_two_windows_were_minimised(run):
    assert run["login"] == 200
    assert set(run["before"]) == {"calendar-modal", "settings-modal"}, run
    assert [w["id"] for w in run["stored"]["minimized"]] == run["before"], run["stored"]


def test_both_chips_are_back_after_a_reload(run):
    """The row's `Verify:`, first half."""
    assert run["after"] == run["before"], run
    assert run["badge"] is True, "the rail did not say Calendar is in the dock"


def test_the_load_opens_neither_window(run):
    """The cost the row held the fix back over: nothing is opened at boot."""
    assert run["openAtBoot"] == {"calendar": False, "settings": False}, run


def test_each_chip_restores_its_window(run):
    """The row's `Verify:`, second half — Settings on the panel it was left on."""
    assert run["calendarOpened"] is True, run
    assert "calendar-modal" not in run["chipsAfterCalendar"], run
    assert run["settingsOpened"] is True, run
    assert run["settingsTab"] == run["tab"], run
    assert run["errors"] == [], run["errors"]


def test_a_window_minimised_again_is_kept_and_a_closed_chip_is_forgotten(run):
    assert set(run["secondReload"]) == {"calendar-modal", "settings-modal"}, run
    assert run["thirdReload"] == ["calendar-modal"], run
