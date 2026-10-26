# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1222` — on a phone the Workbench's canvas starts under its toolbar, not 36 px below it.

**Measured before the fix** (Chromium, this tree at `9297d85a`, 390×844, the
Workbench's Automations view): the toolbar ended at y = 264 and the canvas's
top rule began at y = 300 — a 36 px band with nothing in it. The row guessed
the hidden hint line; the hint is `display: none` at this width already. The
band was the say box (`.wb-say`, the canvas's one line of words): 24 px of
`min-height` and both of the room's 6 px gaps, held while it had nothing to
say.

**Now**, at phone width, an empty say box leaves the flow, so:

  * with nothing to say, the canvas starts one gap (6 px) under the toolbar;
  * the moment there are words — a step picked up from the keyboard says how
    to move it — the line is back between the toolbar and the canvas, its
    words in the `role="status"` region that never left the accessibility tree
    (`display: none` would have taken it out, and a live region that is not
    there when its words arrive is one a screen reader may not read);
  * the desktop keeps its reserved line (1440×900, unchanged).

Driven, not read (`Law 20`): the real app, the real Workbench opened from its
sidebar row, the real canvas's own keyboard move (`m`) producing the words.
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
const LAYOUT = () => {
  const box = (s) => { const n = document.querySelector('#workbench-modal ' + s); const r = n.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, h: r.height }; };
  const text = document.querySelector('#workbench-modal .wb-say-text');
  return { toolbar: box('.wb-toolbar'), say: box('.wb-say'), stage: box('.wb-stage'),
           words: text.textContent, status: text.getAttribute('role'),
           statusRendered: getComputedStyle(text).display !== 'none'
             && getComputedStyle(text.parentElement).display !== 'none' };
};
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  await (await browser.newContext()).request.post(BASE + '/api/auth/setup',
    { data: { username: USER, password: PASSWORD } });
  for (const [label, w, h] of [['390', 390, 844], ['1440', 1440, 900]]) {
    const phone = w < 500;
    const context = await browser.newContext({ viewport: { width: w, height: h }, isMobile: phone, hasTouch: phone });
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    await context.request.post(BASE + '/api/auth/login', { data: { username: USER, password: PASSWORD, remember: true } });
    if (label === '390') {
      // One step of the person's own, so the canvas has something to pick up.
      const made = await context.request.post(BASE + '/api/tasks',
        { data: { name: 'Band check', prompt: 'Say hello.', schedule: 'daily' } });
      if (!made.ok()) throw new Error('could not make a task: ' + made.status() + ' ' + await made.text());
    }
    const page = await context.newPage();
    page.on('pageerror', (e) => out.errors.push(String(e)));
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await page.waitForTimeout(900);
    await page.evaluate(() => document.getElementById('tool-workbench-btn').click());
    await page.waitForSelector('#workbench-modal .wb-stage', { state: 'visible', timeout: 30000 });
    await page.waitForTimeout(900);
    const row = { empty: await page.evaluate(LAYOUT) };
    // Words, the canvas's own way: pick the step up from the keyboard.
    await page.waitForSelector('#workbench-modal .wb-node', { timeout: 30000 });
    await page.focus('#workbench-modal .wb-node');
    await page.keyboard.press('m');
    await page.waitForTimeout(400);
    row.saying = await page.evaluate(LAYOUT);
    out[label] = row;
    await context.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("wb-band")
    script = d / "band.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_with_nothing_to_say_the_canvas_starts_under_the_toolbar(measured):
    assert measured["errors"] == []
    got = measured["390"]["empty"]
    assert got["words"] == ""
    band = got["stage"]["top"] - got["toolbar"]["bottom"]
    assert band <= 6.5, f"a {band:.0f}px empty band between the toolbar and the canvas"   # before: 36
    assert got["status"] == "status" and got["statusRendered"], (
        "the say line's live region left the accessibility tree while it was empty")


def test_words_bring_the_line_back_between_the_toolbar_and_the_canvas(measured):
    got = measured["390"]["saying"]
    assert got["words"].startswith("Moving "), got["words"]
    assert got["say"]["h"] >= 24, got["say"]
    assert got["toolbar"]["bottom"] <= got["say"]["top"] and got["say"]["bottom"] <= got["stage"]["top"], got


def test_the_desktop_keeps_its_line(measured):
    got = measured["1440"]
    assert got["empty"]["say"]["h"] == 24, got["empty"]["say"]
    assert got["empty"]["say"]["top"] < got["empty"]["stage"]["top"], got["empty"]
