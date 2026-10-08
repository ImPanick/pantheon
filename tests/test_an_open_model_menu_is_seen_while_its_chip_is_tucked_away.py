# SPDX-License-Identifier: AGPL-3.0-or-later
"""`D-2026-10-07-02` §1 — the model menu the composer's note opens is seen.

"Started a chat with no model fails clearly, and states why", with the door to
fix it: a saved default its endpoint does not list now says so in the composer
(`chat.js` `_sayNoModel`) with **Pick a model**, which opens the model menu.

**Driven before this case** (fx4-models, 8751, Chromium, the showcase world
with its scripted model stopped): at 390×844 the note's button removed the note
and nothing could be seen. The menu was open — `#model-picker-menu` without
`hidden`, 1.5 s later — inside a chip that was faded out: the composer tucks
the model chip away while the message box is busy (`app.js`
`initModelPickerResponsive`: `picker-auto-hidden` on a touch screen with any
text; `_syncModelPickerAutohide`: `model-picker-autohide` from 23 characters at
any width; plan mode), and the message is kept after a refused send, so the
chip was always tucked away when the button was pressed — at 1440 too, for a
message of 23 characters or more.

Driven, not read (`Law 20`): the real `static/style.css`, whole, in headless
Chromium, on a fixture of the composer's own markup (`static/index.html`'s
`.chat-input-bar > .chat-input-top > #model-picker-wrap`), with the classes
`app.js` sets and the menu shown the way `modelPicker.js` shows it (removing
`hidden`). Measured: what the browser hit-tests at the menu's Retry, and the
chip's computed opacity.
"""

from __future__ import annotations

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402
from test_display_and_motion_in_a_browser import _drive, _page  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

_COMPOSER = """
<div style="position:fixed; left:16px; right:16px; bottom:16px;">
 <div class="chat-input-bar">
  <div class="chat-input-top">
   <textarea id="message" rows="1">Morning summary please, and the backup status too</textarea>
   <div class="model-picker-wrap" id="model-picker-wrap">
    <button type="button" class="model-picker-btn" id="model-picker-btn"><span id="model-picker-label">Select model</span></button>
    <div class="model-picker-menu hidden" id="model-picker-menu">
     <div class="model-picker-search-row"><div class="model-picker-search-wrap">
      <input type="text" id="model-picker-search" placeholder="Search models...">
     </div></div>
     <div class="model-picker-list" id="model-picker-list">
      <div class="model-switch-down"><span class="model-switch-down-text">Demo model isn't answering.</span><button type="button" class="model-switch-down-retry">Retry</button></div>
      <div class="model-switch-item"><span class="mp-model-name">alpha-7b</span><span class="model-switch-ep">Office LLM</span></div>
     </div>
    </div>
   </div>
  </div>
 </div>
</div>
"""

_STEPS = r"""
  await page.evaluate((cls) => {
    const wrap = document.getElementById('model-picker-wrap');
    for (const c of cls.tucked) wrap.classList.add(c);
    if (cls.plan) document.body.classList.add('plan-mode-active');
    if (cls.open) document.getElementById('model-picker-menu').classList.remove('hidden');
  }, %s);
  await page.waitForTimeout(500);   // past the chip's 0.22 s fade
  return await page.evaluate(() => {
    const retry = document.querySelector('.model-switch-down-retry');
    const r = retry.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { opacity: getComputedStyle(document.getElementById('model-picker-wrap')).opacity,
             chip: getComputedStyle(document.getElementById('model-picker-btn')).visibility,
             retryHit: hit === retry,
             inView: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth };
  });
"""


def _case(tmp_path, *, tucked, open_, viewport, touch=False, plan=False):
    import json
    out = _drive(tmp_path, html=_page(_COMPOSER), viewport=viewport, touch=touch,
                 steps=_STEPS % json.dumps({"tucked": tucked, "open": open_, "plan": plan}))
    assert not out["errors"], out["errors"]
    return out["result"]


@pytest.mark.parametrize("tucked, viewport, touch, plan", [
    (["picker-auto-hidden"], (390, 844), True, False),       # a phone, any text
    (["model-picker-autohide"], (1440, 900), False, False),  # 23 characters or more
    ([], (1440, 900), False, True),                          # plan mode
], ids=["phone-with-text", "long-message", "plan-mode"])
def test_the_menu_opened_while_the_chip_is_tucked_away_is_seen_and_pressed(tmp_path, tucked, viewport,
                                                                           touch, plan):
    got = _case(tmp_path, tucked=tucked, open_=True, viewport=viewport, touch=touch, plan=plan)
    assert got["inView"], got
    assert got["opacity"] == "1", f"the open menu is drawn inside a chip at opacity {got['opacity']}"
    assert got["retryHit"], "a press on the menu's Retry does not reach it"
    # The chip itself stays tucked away: drawn, it sat over the kept message
    # (driven at 390 after the menu was made visible).
    assert got["chip"] == "hidden", got


def test_the_chip_still_tucks_away_while_its_menu_is_shut(tmp_path):
    """The rule is the open menu's, not the chip's: shut, it fades as before;
    untucked and open, the chip is drawn as before."""
    got = _case(tmp_path, tucked=["picker-auto-hidden"], open_=False, viewport=(390, 844), touch=True)
    assert got["opacity"] == "0"
    got = _case(tmp_path, tucked=[], open_=True, viewport=(1440, 900))
    assert got["opacity"] == "1" and got["chip"] == "visible" and got["retryHit"]
