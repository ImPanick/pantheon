# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1347` — on a phone the model picker on the message row is a thumb's height.

**Measured before the fix** (Chromium, this tree at `9297d85a`, a signed-in
chat with no model): `#model-picker-btn` was **109 × 21 px** at 390×844 and at
360×800 — the one control on the message row that says *Select model*, at half
the 44 px a thumb needs (`D-2026-10-09-01` §4). The turn sheet's Model row is a
second door; the first one was still a 21 px target on every phone.

**Now** the phone block gives it a 44 px box that grows down from where it sits,
with the label held on its line, so:

  * at 390×844 and 360×800 the button's box is at least 44 px tall, and a tap
    at the bottom of that box lands on the picker;
  * the label sits exactly where the 21 px box put it, and the box does not
    reach the row of controls under the message box;
  * the desktop is untouched (21 px at 1440×900).

Driven, not read (`Law 20`): the real app booted out of process, signed in, the
real stylesheet laid out by headless Chromium with touch emulation on the
phones.
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
const MEASURE = () => {
  const btn = document.getElementById('model-picker-btn');
  const label = document.getElementById('model-picker-label');
  const b = btn.getBoundingClientRect();
  const l = label.getBoundingClientRect();
  const row = document.querySelector('.chat-input-bottom').getBoundingClientRect();
  const hit = document.elementFromPoint(b.left + b.width / 2, b.bottom - 3);
  return { h: Math.round(b.height * 10) / 10, w: Math.round(b.width), top: b.top, bottom: b.bottom,
           labelOffset: Math.round((l.top - b.top) * 10) / 10, text: label.textContent,
           rowTop: row.top, hitIsPicker: !!(hit && btn.contains(hit)),
           shown: getComputedStyle(document.getElementById('model-picker-wrap')).display !== 'none' };
};
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  await (await browser.newContext()).request.post(BASE + '/api/auth/setup',
    { data: { username: USER, password: PASSWORD } });
  for (const [label, w, h] of [['390', 390, 844], ['360', 360, 800], ['1440', 1440, 900]]) {
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
    await page.waitForSelector('#model-picker-btn', { state: 'visible' });
    await page.waitForTimeout(900);
    out[label] = await page.evaluate(MEASURE);
    await context.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("picker-phone")
    script = d / "picker.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("phone", ["390", "360"])
def test_on_a_phone_the_picker_is_a_thumbs_height(measured, phone):
    assert measured["errors"] == []
    got = measured[phone]
    assert got["shown"] and got["text"] == "Select model", got   # a chat with no model
    assert got["h"] >= 44, f"the model picker is {got['h']}px tall at {phone}px wide"  # before: 21
    assert got["hitIsPicker"], "a tap at the bottom of the box misses the picker"


@pytest.mark.parametrize("phone", ["390", "360"])
def test_the_label_keeps_its_line_and_the_box_keeps_off_the_row_below(measured, phone):
    got, desk = measured[phone], measured["1440"]
    assert got["labelOffset"] == desk["labelOffset"], (got, desk)
    assert got["bottom"] <= got["rowTop"], "the 44px box reaches the controls under the message box"


def test_the_desktop_picker_is_unchanged(measured):
    assert measured["1440"]["h"] == 21, measured["1440"]
