# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1065` — the first-run tour hint gives way to a window opened after it.

The half of `B1056` the toast's stacking could not reach. `tourHints.js`'s
`_show` places the hint beside the window that triggered it, above everything
(`topPortalZ()`), for 14 s; a window opened in that time — the Workbench,
measured by verify-a — had its −/+/Fit and its window buttons under the hint.
And the module stopped watching windows the moment it had shown the hint, so
nothing could tell it.

Now a window that comes up while the hint is on screen, or in the moment
before it appears, sends it away. It is not marked seen (it was not read): a
later visit shows it again.

Driven in headless Chromium (the `playwright` node package): the real
`static/style.css` and `static/js/tourHints.js` (with the real
`toolWindowZOrder.js` it imports) served to a page with two windows shaped as
the shipped ones are (`.modal` > `.modal-content`); the Tasks window opens, the
hint comes up beside it, then the Workbench opens where the hint is. The row's
`Verify:` is that no control of the later window is under the hint.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

_PAGE = r"""<!doctype html><html><head><link rel="stylesheet" href="/static/style.css"></head><body>
<!-- Placed by hand, not by the window manager: the Tasks window on the left,
     so the hint comes up to its right (`_show`'s first choice); the Workbench
     opened later with its header row where the hint is. -->
<div id="tasks-modal" class="modal hidden" style="z-index:1001">
  <div class="modal-content" style="position:fixed;left:40px;top:60px;width:420px;height:320px;margin:0">
    <div class="modal-header">Tasks</div></div>
</div>
<div id="workbench-modal" class="modal hidden" style="z-index:1002">
  <div class="modal-content" style="position:fixed;left:470px;top:90px;width:700px;height:420px;margin:0">
    <div class="modal-header" style="display:flex;gap:6px;justify-content:flex-start;align-items:center">
      <button id="wb-zoom-out" type="button">−</button><button id="wb-zoom-in" type="button">+</button>
      <button id="wb-fit" type="button">Fit</button><button id="wb-close" type="button">×</button>
      <span>Workbench</span>
    </div>
  </div>
</div>
<script type="module">
  window.H = await import('/static/js/tourHints.js');
  window.ready = true;
</script>
</body></html>"""

_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const [STATIC, PAGE, DELAY] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1400, height: 860 } });
  await page.route('http://t.local/**', (route) => {
    const u = new URL(route.request().url());
    if (u.pathname === '/') return route.fulfill({ contentType: 'text/html', body: PAGE });
    const file = path.join(STATIC, u.pathname.replace(/^\/static\//, ''));
    if (!file.startsWith(STATIC) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
    const type = file.endsWith('.css') ? 'text/css' : 'text/javascript';
    return route.fulfill({ contentType: type, body: fs.readFileSync(file) });
  });
  await page.goto('http://t.local/');
  await page.waitForFunction(() => window.ready === true);
  await page.waitForTimeout(120);                              // `init` watches after 50 ms
  await page.evaluate(() => document.getElementById('tasks-modal').classList.remove('hidden'));
  await page.waitForTimeout(Number(DELAY));                    // the hint is up (or about to be)
  const before = await page.evaluate(() => {
    const h = document.querySelector('.tour-hint');
    return h ? h.getBoundingClientRect().toJSON() : null;
  });
  await page.evaluate(() => document.getElementById('workbench-modal').classList.remove('hidden'));
  await page.waitForTimeout(800);
  const out = await page.evaluate(() => {
    const ids = ['wb-zoom-out', 'wb-zoom-in', 'wb-fit', 'wb-close'];
    const covered = ids.filter((id) => {
      const r = document.getElementById(id).getBoundingClientRect();
      const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !(at && at.id === id);
    });
    return { covered, hints: document.querySelectorAll('.tour-hint').length,
             seen: localStorage.getItem('pantheon-hint-drag-to-snap-seen') };
  });
  out.before = before;
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _drive(tmp_path, delay_ms: int) -> dict:
    (tmp_path / "page.html").write_text(_PAGE, encoding="utf-8")
    (tmp_path / "run.cjs").write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(tmp_path / "run.cjs"), str(STATIC), _PAGE, str(delay_ms)],
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_window_opened_while_the_hint_is_up_is_not_under_it(tmp_path):
    """The row's `Verify:`."""
    out = _drive(tmp_path, 900)
    assert out["before"] is not None, "the premise: the hint came up beside the first window"
    assert out["covered"] == [], f"the later window's controls are under the hint: {out['covered']}"
    assert out["hints"] == 0
    assert out["seen"] is None, "a hint that gave way was not read, so it is not marked seen"


def test_a_window_opened_before_the_hint_appears_is_not_under_it_either(tmp_path):
    """The 380 ms between the first window opening and the hint appearing."""
    out = _drive(tmp_path, 100)
    assert out["before"] is None, "the premise: the hint had not come up yet"
    assert out["covered"] == [], out
    assert out["hints"] == 0 and out["seen"] is None
