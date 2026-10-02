# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1131` — at phone width Settings' tabs are one row, and the panel has the screen.

**Measured before the fix** (Chromium, this tree, 390x844): the tab list was
**555px tall** — sixteen items in sixteen rows — and the panel under it got
**102px**. Both narrow-layout blocks in `static/style.css` (`@media (max-width:
600px)` and `@container settings-modal (max-width: 620px)`) turn the sidebar
and `.settings-sidebar-content` into a sideways rail, but the items live one
level down, in `.settings-nav-list`, which stayed a column. And the phone's
full-height sheet kept the centred window's cap on the layout (`85vh - 60px`),
so the panel stopped 96px above the sheet's bottom.

**Now** the list is the rail in both blocks, and on a phone the layout fills
its sheet: one row of tabs (~45px), the panel to the bottom of the screen. The
desktop's column of tabs is unchanged, and a Settings window snapped narrow on
a desktop (the container block) gets the same rail.

Driven, not read (`Law 20`): the real app booted out of process (the B1124
file's fixture), signed in, Settings opened from the command palette as a
person opens it, the real stylesheet laid out by headless Chromium.
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
const BOXES = () => {
  const box = (sel) => { const r = document.querySelector(sel).getBoundingClientRect();
    return { top: Math.round(r.top), h: Math.round(r.height), bottom: Math.round(r.bottom), w: Math.round(r.width) }; };
  const items = [...document.querySelectorAll('#settings-modal .settings-nav-item')].filter((n) => n.offsetParent);
  return { sheet: box('#settings-modal .modal-content'), tabs: box('#settings-modal .settings-sidebar'),
           panel: box('#settings-modal .settings-panels'), items: items.length,
           rows: new Set(items.map((n) => Math.round(n.getBoundingClientRect().top))).size,
           pageScrollX: document.documentElement.scrollWidth - document.documentElement.clientWidth };
};
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  await (await browser.newContext()).request.post(BASE + '/api/auth/setup',
    { data: { username: USER, password: PASSWORD } });
  for (const [label, w, h, narrow] of [['390', 390, 844, false], ['1400', 1400, 860, false],
                                        ['snapped', 1400, 860, true]]) {
    const phone = w < 500;
    const context = await browser.newContext({ viewport: { width: w, height: h }, isMobile: phone, hasTouch: phone });
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    await context.request.post(BASE + '/api/auth/login', { data: { username: USER, password: PASSWORD, remember: true } });
    const page = await context.newPage();
    page.on('pageerror', (e) => out.errors.push(String(e)));
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await page.waitForTimeout(1200);
    await page.keyboard.press('Control+k');
    await page.waitForSelector('#search-input', { state: 'visible' });
    await page.keyboard.type('Settings', { delay: 20 });
    await page.waitForTimeout(800);
    await page.keyboard.press('Enter');
    await page.waitForSelector('#settings-modal:not(.hidden) .settings-nav-item', { timeout: 30000 });
    await page.waitForTimeout(900);
    if (narrow) {
      // A Settings window snapped narrow on a desktop: the container block's case.
      await page.evaluate(() => { const m = document.querySelector('#settings-modal .modal-content');
        m.style.width = '560px'; m.style.maxWidth = '560px'; m.style.minWidth = '0'; });
      await page.waitForTimeout(500);
    }
    out[label] = await page.evaluate(BOXES);
    await context.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):
    d = tmp_path_factory.mktemp("settings-phone")
    script = d / "settings.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_at_390_the_tabs_are_one_row_and_the_panel_has_the_screen(measured):
    assert measured["errors"] == []
    got = measured["390"]
    assert got["items"] >= 10 and got["rows"] == 1, got
    assert got["tabs"]["h"] <= 60, got["tabs"]          # measured before: 555
    assert got["panel"]["h"] >= 0.75 * got["sheet"]["h"], got   # measured before: 102 of 844
    assert got["panel"]["bottom"] == got["sheet"]["bottom"], "the panel stops short of the sheet"
    assert got["pageScrollX"] == 0


def test_a_settings_window_snapped_narrow_on_a_desktop_gets_the_same_rail(measured):
    got = measured["snapped"]
    assert got["sheet"]["w"] == 560 and got["rows"] == 1 and got["tabs"]["h"] <= 60, got


def test_the_desktops_column_of_tabs_is_unchanged(measured):
    got = measured["1400"]
    assert got["rows"] == got["items"] >= 10, got
    assert got["tabs"]["w"] == 220 and got["tabs"]["top"] == got["panel"]["top"], got
