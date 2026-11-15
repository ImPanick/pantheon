# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Whose pointer is over a live screen, driven in headless Chromium.

Found by hand on the dev build: with the agent holding the workstation, the
person's own pointer vanished the moment it crossed the live desktop. The
desktop's KasmVNC client is an `<iframe>` that fills the stage, and nothing
stood between it and the pointer, so whoever held the mouse and keyboard the
client took the pointer and drew the workstation's cursor in its place
(nothing, while the agent's pointer was elsewhere or hidden).

What is pinned, against the real `static/style.css` and the markup each window
draws (`workstationScreen.js`, `phoneWindow.js`, `browserWindow.js`), with a
stand-in client page that hides the cursor as KasmVNC's does and counts the
pointer moves that reach it:

  * **watching** (*Take control* off): the pointer moves over the screen and
    never reaches the client; the person's own cursor stays, never `none`;
  * **holding** (*Take control* on): the pointer reaches the client, which
    draws the workstation's cursor in place of the person's — one cursor;
  * **live**: flipping control while the pointer rests over the screen moves
    it to the client and back with no reload.

For each of the three live screens: the workstation's desktop, the phone and
the agent's browser. Skips, with the reason, where node, Playwright or
Chromium is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_display_and_motion_in_a_browser import NODE, _drive, _page  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason="node, Playwright or Chromium is absent")

# The client's page: no cursor of the person's (KasmVNC draws the remote one,
# or none), and every pointer move that reaches it told to the parent.
_CLIENT = ("<style>html,body{margin:0;height:100%;cursor:none;background:#000}</style>"
           "<script>addEventListener('pointermove',()=>parent.postMessage('moved','*'))</script>")


def _srcdoc() -> str:
    return _CLIENT.replace("&", "&amp;").replace('"', "&quot;")


# Each surface: its markup (the client's frame first, as each window inserts
# it), the element whose class says the person holds it, and that class.
SURFACES = {
    "workstation": {
        "markup": f"""
<div class="wsv-stage" style="position:relative;width:640px;height:400px">
  <div id="screen" class="wsv-screen wsv-is-live" style="position:absolute;inset:0">
    <img class="wsv-frame" hidden alt=""><div class="wsv-empty" hidden></div>
    <iframe class="wsv-live" srcdoc="{_srcdoc()}"></iframe>
  </div>
  <div class="wsv-agent" aria-hidden="true"><span class="wsv-hand" hidden></span></div>
</div>""",
        "holder": "#screen", "watching": [], "holding": ["wsv-driving"],
    },
    "phone": {
        "markup": f"""
<div class="phw-stage" style="width:420px;height:800px">
  <div class="phw-bezel" style="position:relative;width:300px;height:640px">
    <div id="screen" class="phw-screen" style="position:absolute;inset:0">
      <iframe class="phw-live-frame" style="left:0;width:100%" srcdoc="{_srcdoc()}"></iframe>
      <div class="phw-empty" hidden></div>
      <div class="phw-glass" title="Take over to use the phone"></div>
    </div>
  </div>
</div>""",
        "holder": "#screen", "watching": [], "holding": ["phw-holding"],
    },
    "browser": {
        "markup": f"""
<div id="screen" class="abw-page abw-live" style="position:relative;width:640px;height:400px">
  <iframe class="abw-live-frame" srcdoc="{_srcdoc()}"></iframe>
  <img class="abw-frame" alt="">
  <div class="abw-glass" aria-hidden="true"></div>
</div>""",
        "holder": "#screen", "watching": [], "holding": ["abw-holding"],
    },
}

_MODULE = """
window.__moves = 0;
addEventListener('message', (e) => { if (e.data === 'moved') window.__moves += 1; });
await Promise.all([...document.querySelectorAll('iframe')].map((f) =>
  f.contentDocument && f.contentDocument.readyState === 'complete'
    ? null : new Promise((r) => f.addEventListener('load', r, { once: true }))));
"""

# Rest the pointer over the screen's middle under each control state in turn,
# and say what took it: the client (moves counted) or the page, and the cursor
# the page shows there.
_STEPS = r"""
const C = %s;
const holder = await page.$(C.holder);
const box = await holder.boundingBox();
const x = box.x + box.width / 2, y = box.y + box.height / 2;
const states = [];
for (const st of C.order) {
  await holder.evaluate((el, add) => {
    for (const c of %s) el.classList.remove(c);
    for (const c of add) el.classList.add(c);
  }, C[st]);
  await page.evaluate(() => { window.__moves = 0; });
  // The pointer moves within the screen, as a hand on a mouse does.
  for (let i = 0; i < 6; i++) await page.mouse.move(x + i * 3, y + i * 2);
  await page.waitForTimeout(80);
  const top = await page.evaluate(([px, py]) => {
    const el = document.elementFromPoint(px, py);
    return { tag: el && el.tagName, cursor: el && getComputedStyle(el).cursor };
  }, [x + 15, y + 10]);
  states.push({ state: st, moves: await page.evaluate(() => window.__moves), ...top });
}
return states;
"""


def _run(tmp_path: Path, surface: str, order: list[str]) -> list[dict]:
    s = SURFACES[surface]
    case = {"holder": s["holder"], "watching": s["watching"], "holding": s["holding"], "order": order}
    steps = _STEPS % (json.dumps(case), json.dumps(s["holding"]))
    out = _drive(tmp_path, html=_page(s["markup"], _MODULE), steps=steps, viewport=(1100, 900))
    assert out["errors"] == [], out["errors"]
    return out["result"]


def _watching_keeps_the_persons_cursor(r: dict) -> None:
    assert r["moves"] == 0, "the pointer reached the client while the person was only watching"
    assert r["tag"] != "IFRAME", "the client's frame is what the pointer is over while watching"
    assert r["cursor"] != "none", "the person's cursor is hidden while they are only watching"


def _holding_hands_it_to_the_client(r: dict) -> None:
    assert r["moves"] > 0, "the pointer never reached the client while the person holds it"
    assert r["tag"] == "IFRAME", "something lies over the client while the person holds it"


@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_watching_a_live_screen_keeps_the_persons_own_cursor(tmp_path, surface):
    [r] = _run(tmp_path, surface, ["watching"])
    _watching_keeps_the_persons_cursor(r)


@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_holding_a_live_screen_gives_the_pointer_to_the_screens_own_cursor(tmp_path, surface):
    [r] = _run(tmp_path, surface, ["holding"])
    _holding_hands_it_to_the_client(r)


@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_flipping_control_moves_the_pointer_live_with_no_reload(tmp_path, surface):
    a, b, c = _run(tmp_path, surface, ["watching", "holding", "watching"])
    _watching_keeps_the_persons_cursor(a)
    _holding_hands_it_to_the_client(b)
    _watching_keeps_the_persons_cursor(c)
