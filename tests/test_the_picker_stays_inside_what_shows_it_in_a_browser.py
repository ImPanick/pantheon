# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1882` (`picker-clipped-and-never-false-alarm`) — the field list opened above its button stays inside the part of the window that shows it.

`placeNear` kept the list inside the window's frame (`.modal-content`), but
what cuts it off is the scrolling body inside the frame
(`.modal-body.workbench-body`, which starts below the window's title bar).
Measured at 1440 × 900 on an If step: the list's top at y 108, the body's at
y 155 — the list's title, "Pick a field", and its first line were hidden.
The list is now kept inside every element around it that cuts off what
overflows it (`visibleBounds`).

Driven: the real `fieldPicker.js` and `static/style.css` in Chromium, through
the driver of `test_display_and_motion_in_a_browser.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_display_and_motion_in_a_browser import NODE, _drive, _page  # noqa: E402
from test_the_command_palette_in_a_browser import _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

# A window at y 40 whose body starts 115 px lower (its title bar), cuts off
# what overflows it, and holds the layer the list is drawn in. The field is
# low enough that the list opens above it, and the list is taller than the
# room between the body's top and the field.
_CLIPPED = """
<div class="modal-content" style="position:fixed;left:100px;top:40px;width:900px;height:800px;padding:0;border:0">
  <div class="modal-header" style="height:115px;box-sizing:border-box;margin:0">Workbench</div>
  <div class="modal-body workbench-body" id="body"
       style="position:relative;height:685px;overflow:hidden;padding:0;border:0;margin:0">
    <div id="layer" style="position:relative;height:685px">
      <input id="field" style="position:absolute;top:485px;left:20px;height:20px">
      <div class="wf-slot" style="position:absolute;top:485px;left:300px;margin:0">
        <button class="wf-slot-pick" id="pick" style="height:20px">Insert a field…</button></div>
    </div>
  </div>
</div>
"""

_MODULE = """
import { placeNear, visibleBounds } from '/static/js/workbench/fieldPicker.js';
await new Promise((r) => setTimeout(r, 400));
const box = document.createElement('div');
box.className = 'wf-picker';
box.style.height = '600px';
document.getElementById('layer').appendChild(box);
placeNear(box, document.getElementById('field'));
const b = box.getBoundingClientRect(), p = document.getElementById('pick').getBoundingClientRect();
const body = document.getElementById('body').getBoundingClientRect();
const win = document.querySelector('.modal-content').getBoundingClientRect();
const v = visibleBounds(box, document.getElementById('field'));
window.__placed = { top: Math.round(b.top), bottom: Math.round(b.bottom), left: Math.round(b.left),
  pickTop: Math.round(p.top), bodyTop: Math.round(body.top), winTop: Math.round(win.top),
  visibleTop: Math.round(v.top), visibleBottom: Math.round(v.bottom) };
"""

_PLACED = "return await page.evaluate(() => window.__placed);"


def test_the_list_opened_above_its_button_starts_below_the_windows_title_bar(tmp_path):
    r = _drive(tmp_path, html=_page(_CLIPPED, _MODULE), steps=_PLACED, viewport=(1440, 900))["result"]
    assert r["bodyTop"] - r["winTop"] >= 100, r            # the page is what it says
    assert r["pickTop"] - r["bodyTop"] < 520, r            # the list is taller than the room above
    assert 0 <= r["pickTop"] - r["bottom"] <= 8, r         # it opened above its button, just above
    assert r["top"] >= r["bodyTop"], r                     # and is not cut off: was 40 px above it
    assert r["visibleTop"] == r["bodyTop"], r              # what shows it starts where the body does
    assert r["visibleBottom"] <= r["bodyTop"] + 685, r
