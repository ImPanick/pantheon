# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1044` — the Assistant has a door a person with the default layout can see.

Measured in Chromium at 1400×860 by `P22-02`: with the sidebar open (the
default on a desktop) `#icon-rail` is `display: none`, and every tool keeps a
door through its row in the sidebar's Tools. `#rail-assistant` — `H02`'s
*"The Personal Assistant's only door"* — had no row, so a person who never
collapses the sidebar never saw it; `UI_VIS_MAP['tool-assistant']` paired it
with nothing and Customize UI had no switch for it. `P22-02` hit the same
defect for the Workbench and gave it both doors; this is the Assistant's.

Driven in the real app in headless Chromium (booted as
`tests/test_the_command_palette_in_a_browser.py` boots it), with real clicks:
the row is where a person looks, it opens the Assistant's own chat (the session
`GET /api/assistant/session` names), the rail still does when the sidebar is
collapsed, and Settings → Appearance hides and restores both doors, across a
reload.
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
  const creds = { username: 'helper', password: 'helper-pass-1' };
  const open = async (size) => {
    const context = await browser.newContext({ viewport: size, serviceWorkers: 'block' });
    await context.addInitScript(() => {
      try {
        if (!localStorage.getItem('pantheon-ui-visibility')) {
          localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
        }
      } catch (_) {}
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
    await page.request.post(BASE + '/api/auth/setup', { data: creds });
    await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await page.waitForTimeout(600);
    return page;
  };
  const shown = (page, id) => page.evaluate((i) => {
    const e = document.getElementById(i);
    if (!e) return null;
    const r = e.getBoundingClientRect();
    return e.offsetParent !== null && r.width > 0 && r.height > 0;
  }, id);
  const current = (page) => page.evaluate(() => window.sessionModule && window.sessionModule.getCurrentSessionId
    ? window.sessionModule.getCurrentSessionId() : null);
  const assistantSession = async (page) => {
    const r = await page.request.get(BASE + '/api/assistant/session');
    return (await r.json()).session_id;
  };

  // ── desk, the default layout ──
  const page = await open({ width: 1400, height: 860 });
  const desk = {};
  desk.railShown = await shown(page, 'rail-assistant');
  desk.rowShown = await shown(page, 'tool-assistant-btn');
  desk.firstTool = await page.evaluate(() => {
    const first = document.querySelector('#tools-section > .list-item');
    return first ? first.id : null;
  });
  // A tree without the row or the switch records that and carries on, so each
  // case below fails on its own claim rather than all of them on one throw.
  const display = (id) => page.evaluate((i) => {
    const e = document.getElementById(i); return e ? getComputedStyle(e).display : null; }, id);
  desk.rowText = await page.evaluate(() => {
    const e = document.getElementById('tool-assistant-btn'); return e ? e.textContent.trim() : null; });
  const asked = [];
  page.on('request', (r) => { if (r.url().endsWith('/api/assistant/session')) asked.push(r.url()); });
  desk.before = await current(page);
  // The cockpit keeps the rail on a desktop and the Tools list in the phone
  // drawer, so whichever door is in sight is the one a person presses.
  if (desk.rowShown || desk.railShown) {
    await page.click(desk.rowShown ? '#tool-assistant-btn' : '#rail-assistant');
    await page.waitForTimeout(1500);
  }
  desk.asked = asked.length;
  desk.after = await current(page);
  desk.assistant = await assistantSession(page);

  // Customize UI: Settings → Appearance → the Assistant switch, the way a person flips it.
  const flip = async () => {
    await page.click('#user-bar-settings');
    await page.waitForSelector('#settings-modal:not(.hidden)', { timeout: 10000 });
    await page.click('[data-settings-tab="appearance"]');
    const sw = page.locator('label.vis-row', { has: page.locator('input[data-ui-key="tool-assistant"]') });
    if (!(await sw.count())) return null;
    const label = (await sw.locator('.vis-label').textContent()).trim();
    const on = await page.isChecked('input[data-ui-key="tool-assistant"]');
    await sw.click();
    await page.waitForTimeout(300);
    const after = await page.isChecked('input[data-ui-key="tool-assistant"]');
    await page.keyboard.press('Escape');
    return { label, on, after };
  };
  const first = await flip();
  desk.switchLabel = first && first.label;
  desk.switchOn = first && first.on;
  desk.switchAfter = first && first.after;
  desk.stored = await page.evaluate(() => JSON.parse(localStorage.getItem('pantheon-ui-visibility') || '{}')['tool-assistant']);
  desk.rowHidden = await display('tool-assistant-btn');
  desk.railHidden = await display('rail-assistant');
  desk.brainStill = (await shown(page, 'tool-memory-btn')) || (await shown(page, 'rail-memory'));
  // Across a reload the choice holds.
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(800);
  desk.rowAfterReload = await display('tool-assistant-btn');
  desk.railAfterReload = await display('rail-assistant');
  // And back on.
  await flip();
  desk.rowBack = await display('tool-assistant-btn');
  out.desk = desk;
  await page.context().close();

  // ── the rail, sidebar collapsed: H02's door still opens the same chat ──
  const railPage = await open({ width: 1400, height: 860 });
  const rail = {};
  // The sidebar's own ≡, pressed by its handler (`Ctrl+Alt+B` does the same).
  await railPage.evaluate(() => document.getElementById('sidebar-toggle-btn').click());
  await railPage.waitForTimeout(800);
  rail.railShown = await shown(railPage, 'rail-assistant');
  if (rail.railShown) {
    // Start from a different chat so the click has something to change.
    await railPage.evaluate(() => { const n = document.getElementById('rail-new-session'); if (n) n.click(); });
    await railPage.waitForTimeout(600);
    await railPage.click('#rail-assistant');
    await railPage.waitForTimeout(1500);
  }
  rail.after = await current(railPage);
  rail.assistant = await assistantSession(railPage);
  out.rail = rail;
  await railPage.context().close();

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def doors(app_url, tmp_path_factory):  # noqa: F811
    # `B1085`: `app_url` gives the server a database file of its own now, so
    # the module fixture this file kept to point `DATABASE_URL` at one is gone.
    if NODE is None:
        pytest.skip(_SKIP or "")
    script = tmp_path_factory.mktemp("assistant-pw") / "assistant.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True, timeout=300,
                          cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def test_with_the_sidebar_open_one_door_is_in_sight(doors):
    # The premise, measured in the run. Before the cockpit the rail hid while
    # the sidebar was open and the row was the door; the cockpit (2026-10-30)
    # keeps the rail on a desktop and the Tools list in the phone drawer, so
    # the rail is the door and the row is not drawn. One door either way.
    assert doors["desk"]["railShown"] is True
    assert doors["desk"]["rowShown"] is False
    assert doors["desk"]["rowText"] == "Assistant"
    # A before B, as on the rail — and `P24-12`'s Agents before the Assistant
    # (Ag before As), the one row added above it since.
    assert doors["desk"]["firstTool"] == "tool-agents-btn"


def test_the_row_opens_the_assistants_own_chat(doors):
    desk = doors["desk"]
    assert desk["asked"] >= 1, "the row did not ask for the Assistant's session"
    assert desk["after"] == desk["assistant"], desk
    assert desk["before"] != desk["assistant"]


def test_customize_ui_has_a_switch_and_it_hides_both_doors(doors):
    desk = doors["desk"]
    assert desk["switchLabel"] == "Assistant"
    assert desk["switchOn"] is True and desk["switchAfter"] is False
    assert desk["stored"] is False
    assert desk["rowHidden"] == "none"
    assert desk["railHidden"] == "none"
    assert desk["brainStill"] is True, "hiding the Assistant hid another tool"


def test_the_choice_holds_across_a_reload_and_comes_back(doors):
    desk = doors["desk"]
    assert desk["rowAfterReload"] == "none"
    assert desk["railAfterReload"] == "none"
    assert desk["rowBack"] != "none"


def test_with_the_sidebar_collapsed_the_rail_still_opens_it(doors):
    rail = doors["rail"]
    assert rail["railShown"] is True
    assert rail["after"] == rail["assistant"]


def test_nothing_threw(doors):
    assert doors["errors"] == []
