# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P23-06` — display and motion, driven in headless Chromium.

What only a browser computes is the cascade and the gesture, so each case here
loads a small harness page against:

  * the real `static/style.css`, whole;
  * the real modules it names (`static/js/ui.js`, `static/js/modalManager.js`,
    …) and everything they import, served from `static/` through `page.route`
    exactly as `tests/test_the_workbench_has_room_on_a_phone.py` serves them;
  * a fixture of the markup the real windows draw (a `.modal` with its
    `.modal-header`, the Brain's and Settings' own content classes, Notes'
    header) — the parts each assertion is about, nothing more.

The touch gesture is the browser's own: `Input.dispatchTouchEvent` through the
DevTools protocol, the same swipe the audit's phone drive made (`exp4.py`).

Cases, by finding:

  * **NAV-U-2 / NAV-M-13 (× half).** At 390 px every sheet shows × and `_` as
    40 px targets — measured before as `display:none` on all eleven windows.
  * **NAV-M-13 (swipe half).** A swipe-down on a sheet presses its × — the
    Calendar's too, which the swipe used to minimise to a chip — and fires no
    `modal-dismissed`.
  * **NAV-M-17.** Under reduced motion a chip dragged onto the dock's ✕ closes
    its windows with no whirl (`rotate(720deg)`) and the chain does not
    spring-follow; with motion allowed both still happen.
  * **The orphaned drawer layer.** With the drawer shut (and no rail over the
    chat), `#sidebar-backdrop.visible` takes no tap — found at 390 px after
    Notes closed, when ☰ and every row on the page were dead.

Skips, with the reason, where node, Playwright or Chromium is absent.
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

# One case = one browser. `CASE.steps` is the body of an async function given
# `page`, `touch` (a CDP finger) and `globalListeners()` (how many listeners sit
# on `document` and `window`, by DevTools) and returning what the test asserts on.
_DRIVER = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const STATIC = process.argv[2];
const CASE = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const TYPES = { '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' };
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({
    viewport: CASE.viewport, hasTouch: !!CASE.touch,
    reducedMotion: CASE.reduced ? 'reduce' : 'no-preference',
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route('http://pantheon.test/**', async (route) => {
    const u = new URL(route.request().url());
    if (u.pathname === '/harness') return route.fulfill({ contentType: 'text/html', body: CASE.html });
    const file = path.join(STATIC, decodeURIComponent(u.pathname).replace(/^\/static\//, ''));
    if (!file.startsWith(STATIC) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      return route.fulfill({ status: 404, body: '' });
    }
    return route.fulfill({ path: file, contentType: TYPES[path.extname(file)] || 'application/octet-stream' });
  });
  await page.goto('http://pantheon.test/harness');
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 20000 });
  const cdp = await ctx.newCDPSession(page);
  const point = (x, y) => ({ x, y, radiusX: 2, radiusY: 2, force: 1, id: 1 });
  const touch = {
    async drag(x, y, x2, y2, steps = 8) {
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point(x, y)] });
      for (let i = 1; i <= steps; i++) {
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove',
          touchPoints: [point(x + (x2 - x) * i / steps, y + (y2 - y) * i / steps)] });
        await page.waitForTimeout(16);
      }
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    },
  };
  // Listeners on `document` and `window`, counted by the browser itself.
  const globalListeners = async () => {
    let n = 0;
    for (const expr of ['document', 'window']) {
      const { result } = await cdp.send('Runtime.evaluate', { expression: expr });
      n += (await cdp.send('DOMDebugger.getEventListeners', { objectId: result.objectId })).listeners.length;
    }
    return n;
  };
  const steps = new (Object.getPrototypeOf(async function () {}).constructor)('page', 'touch', 'globalListeners', CASE.steps);
  const result = await steps(page, touch, globalListeners);
  process.stdout.write(JSON.stringify({ result, errors }) + '\n');
  await browser.close();
})().catch((e) => { process.stdout.write(JSON.stringify({ crash: String(e && e.stack || e) }) + '\n'); process.exit(0); });
"""


def _page(body: str, module: str = "") -> str:
    script = f'<script type="module">{module}\nwindow.__ready = true;</script>' if module else (
        "<script>window.__ready = true;</script>")
    return ('<!doctype html><html><head><meta charset="utf-8">'
            '<link rel="stylesheet" href="/static/style.css"></head>'
            f'<body>{body}{script}</body></html>')


def _drive(tmp_path: Path, *, html: str, steps: str, viewport=(390, 844), touch=False,
           reduced=False) -> dict:
    driver = tmp_path / "driver.js"
    driver.write_text(_DRIVER)
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "viewport": {"width": viewport[0], "height": viewport[1]}, "touch": touch,
        "reduced": reduced, "html": html, "steps": steps,
    }))
    proc = subprocess.run([NODE, str(driver), str(STATIC), str(case)], capture_output=True, text=True,
                          timeout=120, cwd=str(ROOT))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, proc.stderr
    out = json.loads(lines[-1])
    assert "crash" not in out, out["crash"]
    return out


# ── NAV-U-2 / NAV-M-13: a phone sheet shows its way out ─────────────────────

_SHEETS = """
<div id="tasks-modal" class="modal"><div class="modal-content"><div class="modal-header"><h4>Tasks</h4>
  <button class="minimize-btn" title="Minimize"></button><button class="close-btn">✖</button></div></div></div>
<div id="cookbook-modal" class="modal"><div class="modal-content"><div class="modal-header"><h4>Forge</h4>
  <button class="modal-minimize-btn" title="Minimize">_</button><button class="close-btn">✖</button></div></div></div>
<div id="memory-modal" class="modal"><div class="memory-modal-content"><div class="modal-header"><h4>Brain</h4>
  <button class="modal-minimize-btn" title="Minimize">_</button><button class="close-btn">✖</button></div></div></div>
<div id="settings-modal" class="modal"><div class="settings-modal-content"><div class="modal-header"><h4>Settings</h4>
  <button class="modal-minimize-btn" title="Minimize">_</button><button class="modal-close">✖</button></div></div></div>
<div id="theme-modal" class="modal"><div id="theme-popup"><div class="modal-header"><h4>Theme</h4>
  <button class="close-btn">✖</button></div></div></div>
<div id="notes-pane" class="notes-pane"><div class="notes-pane-header"><h4>Notes</h4>
  <button class="modal-minimize-btn" title="Minimize">_</button><button class="close-btn">✖</button></div></div>
"""

_MEASURE_BUTTONS = r"""
  await page.waitForTimeout(600);   // past every entrance animation
  return await page.evaluate(() => [...document.querySelectorAll(
    '.modal-header button, .notes-pane-header button')].map((b) => {
      const cs = getComputedStyle(b); const r = b.getBoundingClientRect();
      const where = b.closest('.modal, .notes-pane').id;
      return { where, cls: b.className, shown: cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0,
               w: Math.round(r.width), h: Math.round(r.height) };
    }));
"""


def test_every_phone_sheet_shows_close_and_minimize_as_40px_targets(tmp_path):
    out = _drive(tmp_path, html=_page(_SHEETS), steps=_MEASURE_BUTTONS)
    buttons = out["result"]
    assert len(buttons) == 11, buttons
    hidden = [b for b in buttons if not b["shown"]]
    assert not hidden, f"hidden on a phone sheet: {hidden}"
    small = [b for b in buttons if b["w"] < 40 or b["h"] < 40]
    assert not small, f"under a 40px target on a phone sheet: {small}"


def test_the_desktop_header_is_not_resized_by_the_phone_rule(tmp_path):
    out = _drive(tmp_path, html=_page(_SHEETS), steps=_MEASURE_BUTTONS, viewport=(1440, 900))
    tasks_x = next(b for b in out["result"] if b["where"] == "tasks-modal" and "close" in b["cls"])
    assert tasks_x["shown"] and tasks_x["h"] < 40, tasks_x


# ── NAV-M-13: swipe-down is Back — it presses × ──────────────────────────────

_SWIPE_PAGE = _page(
    """
<div id="calendar-modal" class="modal" style="display:flex"><div class="modal-content">
  <div class="modal-header"><h4>Calendar</h4><button class="close-btn" id="x">✖</button></div>
  <div class="modal-body" style="height:600px">body</div></div></div>
""",
    """
import * as Modals from '/static/js/modalManager.js';
import '/static/js/ui.js';
window.__closed = 0; window.__dismissed = 0;
window.addEventListener('modal-dismissed', () => { window.__dismissed += 1; });
const modal = document.getElementById('calendar-modal');
// What the Calendar's × does: its own teardown, registered with the manager.
const shut = () => { window.__closed += 1; modal.style.display = 'none'; modal.classList.add('hidden'); };
document.getElementById('x').addEventListener('click', () => Modals.close('calendar-modal'));
Modals.register('calendar-modal', { closeFn: shut, restoreFn: () => {} });
""",
)

_SWIPE_STEPS = r"""
  await page.waitForTimeout(400);
  const box = await page.locator('#calendar-modal .modal-header').boundingBox();
  const x = box.x + box.width / 2, y = box.y + 12;
  await touch.drag(x, y, x, y + 320);
  await page.waitForTimeout(800);
  return await page.evaluate(() => ({
    closed: window.__closed,
    dismissed: window.__dismissed,
    hidden: document.getElementById('calendar-modal').classList.contains('hidden'),
    minimized: document.getElementById('calendar-modal').classList.contains('modal-minimized'),
    chips: document.querySelectorAll('.minimized-dock-chip').length,
    transform: document.querySelector('#calendar-modal .modal-content').style.transform,
  }));
"""


def test_a_swipe_down_closes_the_sheet_the_way_its_close_button_does(tmp_path):
    out = _drive(tmp_path, html=_SWIPE_PAGE, steps=_SWIPE_STEPS, touch=True)
    r = out["result"]
    assert r["closed"] == 1, r          # the window's own close ran, once
    assert r["hidden"] and not r["minimized"] and r["chips"] == 0, r   # closed, not a chip
    assert r["dismissed"] == 0, r       # one meaning: no second event for a swipe
    assert r["transform"] == "", r      # the sheet is put back for its next opening


def test_a_short_drag_leaves_the_sheet_open(tmp_path):
    steps = _SWIPE_STEPS.replace("y + 320", "y + 24")
    out = _drive(tmp_path, html=_SWIPE_PAGE, steps=steps, touch=True)
    r = out["result"]
    assert r["closed"] == 0 and not r["hidden"], r


# ── NAV-M-17: reduced motion stops the dock's whirl and chain ───────────────

_DOCK_PAGE = _page(
    """
<div id="tasks-modal" class="modal"><div class="modal-content"><div class="modal-header"><h4>Tasks</h4>
  <button class="close-btn">✖</button></div></div></div>
<div id="calendar-modal" class="modal"><div class="modal-content"><div class="modal-header"><h4>Calendar</h4>
  <button class="close-btn">✖</button></div></div></div>
""",
    """
import * as Modals from '/static/js/modalManager.js';
window.__closed = [];
for (const id of ['tasks-modal', 'calendar-modal']) {
  Modals.register(id, { closeFn: () => window.__closed.push(id), restoreFn: () => {} });
  Modals.minimize(id);
}
// Every transform and every left/top any chip or the dock is given, as it is given.
window.__seen = [];
new MutationObserver((muts) => { for (const m of muts) {
  const t = m.target; if (!t.classList) continue;
  if (t.classList.contains('minimized-dock-chip') || t.id === 'minimized-dock') window.__seen.push(t.getAttribute('style') || '');
} }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['style'] });
""",
)

_DOCK_STEPS = r"""
  await page.waitForTimeout(300);
  const chip = await page.locator('.minimized-dock-chip').first().boundingBox();
  const x = chip.x + chip.width / 2, y = chip.y + chip.height / 2;
  // Down onto the chip, a drag to set the chain going, then onto the ✕.
  await touch.drag(x, y, x + 40, y - 60, 6);
  const zone = await page.evaluate(() => {
    const z = document.getElementById('dock-trash-zone'); if (!z) return null;
    const r = z.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  // A second gesture, straight to the ✕ that the first one placed.
  const chip2 = await page.locator('.minimized-dock-chip').first().boundingBox();
  const cx = chip2.x + chip2.width / 2, cy = chip2.y + chip2.height / 2;
  await touch.drag(cx, cy, zone.x, zone.y, 12);
  await page.waitForTimeout(80);
  const mid = await page.evaluate(() => window.__closed.slice());
  await page.waitForTimeout(600);
  return await page.evaluate((mid) => ({
    closedAt80ms: mid,
    closed: window.__closed.slice().sort(),
    whirled: window.__seen.some((s) => /rotate\(720deg\)/.test(s)),
    chained: window.__seen.some((s) => /position:\s*fixed/.test(s) && /left:/.test(s)),
  }), mid);
"""


def test_reduced_motion_closes_the_dock_without_the_whirl_or_the_chain(tmp_path):
    out = _drive(tmp_path, html=_DOCK_PAGE, steps=_DOCK_STEPS, touch=True, reduced=True)
    r = out["result"]
    assert r["closed"] == ["calendar-modal", "tasks-modal"], r
    assert not r["whirled"], r
    assert not r["chained"], r
    assert sorted(r["closedAt80ms"]) == ["calendar-modal", "tasks-modal"], r   # at once, not after 320 ms


def test_with_motion_allowed_the_dock_still_whirls(tmp_path):
    out = _drive(tmp_path, html=_DOCK_PAGE, steps=_DOCK_STEPS, touch=True, reduced=False)
    r = out["result"]
    assert r["closed"] == ["calendar-modal", "tasks-modal"], r
    assert r["whirled"] and r["chained"], r


# ── the drawer's dim layer takes no tap while the drawer is shut ────────────

_DRAWER = """
<div class="icon-rail" id="icon-rail"></div>
<nav class="sidebar right-side hidden" id="sidebar"></nav>
<div id="sidebar-backdrop" class="visible"></div>
<button id="hamburger-btn" class="hamburger-btn" style="position:fixed;top:6px;right:6px;width:44px;height:44px">☰</button>
"""
_HIT = r"""
  return await page.evaluate(() => {
    const e = document.elementFromPoint(364, 28); return e && e.id;
  });
"""


def test_a_shut_drawer_leaves_no_layer_over_the_page(tmp_path):
    out = _drive(tmp_path, html=_page(_DRAWER), steps=_HIT)
    assert out["result"] == "hamburger-btn", out


def test_the_rail_over_the_chat_still_has_its_dim_layer(tmp_path):
    html = _page(_DRAWER.replace('class="icon-rail"', 'class="icon-rail mobile-mini"'))
    out = _drive(tmp_path, html=html, steps=_HIT)
    assert out["result"] == "sidebar-backdrop", out


# ── NAV-M-15: nothing behind a window moves — the Calendar keeps the sidebar ──

_CALENDAR_PAGE = _page(
    """
<div class="icon-rail" id="icon-rail"></div>
<nav class="sidebar" id="sidebar" style="width:260px">rows</nav>
<div id="chat-container"><textarea id="message"></textarea></div>
""",
    """
// The Calendar asks the server for its calendars; the harness has none to give.
window.fetch = async () => ({ ok: true, status: 200, json: async () => ([]) });
const cal = await import('/static/js/calendar.js');
cal.openCalendar();
window.__opened = !document.getElementById('calendar-modal').classList.contains('hidden');
""",
)
_SIDEBAR_STATE = r"""
  await page.waitForTimeout(300);
  return await page.evaluate(() => ({
    opened: window.__opened,
    sidebarHidden: document.getElementById('sidebar').classList.contains('hidden'),
  }));
"""


def test_opening_the_calendar_on_a_desktop_leaves_the_sidebar_where_it_was(tmp_path):
    out = _drive(tmp_path, html=_CALENDAR_PAGE, steps=_SIDEBAR_STATE, viewport=(1440, 900))
    assert out["result"] == {"opened": True, "sidebarHidden": False}, out


def test_on_a_phone_the_calendar_still_shuts_the_drawer_it_would_open_under(tmp_path):
    out = _drive(tmp_path, html=_CALENDAR_PAGE, steps=_SIDEBAR_STATE, viewport=(390, 844))
    assert out["result"] == {"opened": True, "sidebarHidden": True}, out


# ── NAV-U-10: one entrance — the 250 ms scale-fade ──────────────────────────

_ENTRANCES = """
<div id="cookbook-modal" class="modal"><div class="modal-content cookbook-modal-entering" id="forge"></div></div>
<div id="tasks-modal" class="modal"><div class="modal-content" id="tasks"><div id="tasks-list" class="tasks-just-opened">
  <div class="task-card memory-item" id="card"></div></div></div></div>
<div id="doclib-modal" class="modal"><div class="modal-content doclib-modal-content"><div class="doclib-just-opened">
  <div class="doclib-card memory-item" id="doc"></div></div></div></div>
<div id="gallery-modal" class="modal"><div class="modal-content"><div class="gallery-just-opened">
  <div class="gallery-card" id="photo"></div></div></div></div>
<div id="email-lib-modal" class="modal"><div class="modal-content"><div class="email-lib-just-opened">
  <div class="doclib-card" id="mail"></div></div></div></div>
"""
_ANIMATIONS = r"""
  return await page.evaluate(() => Object.fromEntries(['forge', 'tasks', 'card', 'doc', 'photo', 'mail'].map((id) => {
    const cs = getComputedStyle(document.getElementById(id));
    return [id, cs.animationName + ' ' + cs.animationDuration];
  })));
"""


def test_every_window_enters_with_one_250ms_scale_fade_and_no_card_cascade(tmp_path):
    out = _drive(tmp_path, html=_page(_ENTRANCES), steps=_ANIMATIONS, viewport=(1440, 900))
    r = out["result"]
    assert r["forge"] == "modal-enter 0.25s", r      # was cookbook-modal-enter 0.28s, an overshoot
    assert r["tasks"] == "modal-enter 0.25s", r
    for card in ("card", "doc", "photo", "mail"):    # was section-domino-in 0.36s, per card, per open
        assert r[card].startswith("none"), (card, r)


def test_on_a_phone_the_forge_slides_up_like_every_other_sheet(tmp_path):
    out = _drive(tmp_path, html=_page(_ENTRANCES), steps=_ANIMATIONS, viewport=(390, 844))
    r = out["result"]
    assert r["forge"] == r["tasks"] == "sheet-enter 0.2s", r


# ── NAV-M-18: a window keeps its own height after a right-dock ──────────────

_DOCKED_PAGE = _page(
    """
<div id="memory-modal" class="modal"><div class="modal-content memory-modal-content" id="brain"
  style="width:560px;height:690px"><div class="modal-header"><h4>Brain</h4></div></div></div>
""",
    """
import * as Modals from '/static/js/modalManager.js';
import { applyEdgeDock } from '/static/js/modalSnap.js';
const modal = document.getElementById('memory-modal');
Modals.register('memory-modal', { closeFn: () => modal.classList.add('hidden'), restoreFn: () => {} });
applyEdgeDock(modal, 'right');
window.__docked = modal.className;
Modals.minimize('memory-modal');
Modals.restore('memory-modal');
Modals.close('memory-modal');
window.__after = { minHeight: document.getElementById('brain').style.minHeight };
""",
)


def test_a_window_closed_after_a_right_dock_does_not_keep_the_screens_height(tmp_path):
    steps = r"return await page.evaluate(() => ({ docked: window.__docked, after: window.__after }));"
    out = _drive(tmp_path, html=_DOCKED_PAGE, steps=steps, viewport=(1440, 900))
    r = out["result"]
    assert "modal-right-docked" in r["docked"], r
    assert r["after"]["minHeight"] == "", r     # was 876px — the Brain reopened 560×876 at y 12


# ── PERF-M-4: six Gallery opens add no listener ─────────────────────────────

_GALLERY_PAGE = _page(
    """
<div class="icon-rail" id="icon-rail"></div><nav class="sidebar" id="sidebar"></nav>
<button id="tool-gallery-btn">Gallery</button>
<div id="chat-container"><textarea id="message"></textarea></div>
""",
    """
// A library with no photos and one album: what the Gallery asks for, answered small.
const album = { id: 'a1', name: 'Harbour', count: 0, image_count: 0, cover: null };
window.fetch = async () => ({ ok: true, status: 200,
  json: async () => ({ images: [], total: 0, albums: [album], ok: true }) });
window.__gallery = await import('/static/js/gallery.js');
""",
)
_GALLERY_STEPS = r"""
  const cycle = async () => {
    await page.evaluate(() => window.__gallery.openGallery());
    await page.waitForTimeout(250);
    // The Albums tab draws the album cards and their ⋯ menus.
    await page.evaluate(() => document.querySelector('#gallery-modal .gallery-tab[data-tab="albums"]').click());
    await page.waitForTimeout(150);
    await page.evaluate(() => window.__gallery.closeGallery());
    await page.waitForTimeout(350);
  };
  await cycle();                       // the first open makes what a page keeps once
  const before = await globalListeners();
  for (let i = 0; i < 6; i++) await cycle();
  const after = await globalListeners();
  const gone = await page.evaluate(() => !document.getElementById('gallery-modal'));
  // The album ⋯ menu still closes from outside, through the one listener.
  await page.evaluate(() => window.__gallery.openGallery());
  await page.waitForTimeout(250);
  await page.evaluate(() => document.querySelector('#gallery-modal .gallery-tab[data-tab="albums"]').click());
  await page.waitForTimeout(150);
  const menu = await page.evaluate(() => {
    const btn = document.querySelector('.gallery-album-menu-btn');
    if (!btn) return 'no album menu drawn';
    btn.click();
    const pop = document.querySelector('.gallery-album-menu-pop');
    const opened = !pop.hidden;
    document.getElementById('message').click();
    return { opened, closedFromOutside: pop.hidden };
  });
  return { before, after, gone, menu };
"""


def test_six_gallery_opens_add_no_listener_to_the_page(tmp_path):
    out = _drive(tmp_path, html=_GALLERY_PAGE, steps=_GALLERY_STEPS, viewport=(1440, 900))
    r = out["result"]
    assert r["gone"], r                        # the window really closed each time
    assert r["after"] == r["before"], r        # was +2 per open: the `scroll` capture and the album menu's dismiss
    assert r["menu"] == {"opened": True, "closedFromOutside": True}, r


# ── the Workbench at both widths: WB-M-7, WB-U-4, WB-U-13, WB-U-9 ───────────

_WORKBENCH = """
<div id="workbench-room-integrations" class="workbench-room workbench-room-integrations" style="height:500px">
  <div class="wb-intg"><div class="admin-card"><div class="mcp-tools-list" id="tools">
    <div style="height:600px">tools and the Try form</div></div></div></div></div>
<div class="wf-runs" style="height:400px;width:1100px">
  <ul class="wf-run-list" id="runs"><li class="wf-run-row"><button class="wf-run-item" id="run" title="Failed, 8:00 AM">
    <span class="wf-run-mark">✗</span><span class="wf-run-word" id="runword">Failed</span>
    <span class="wf-run-when">8:00 AM</span></button></li></ul>
  <div class="wf-run-canvas wb-room wb-panel-open" id="runcanvas"></div>
</div>
<div class="wf-bar" id="bar"><span class="wf-bar-group"><input class="wf-name"></span>
  <span class="wf-bar-group"><button class="wf-switch">Off</button><span class="wf-switch-word" id="switchword">Off</span></span>
  <button class="wf-bar-more" id="more">⋯</button>
  <span class="wf-bar-group wf-bar-runs" id="rungroup"><button>Versions…</button><button>Run now</button></span></div>
<aside class="wb-panel"><div class="wb-panel-body"></div>
  <div class="wb-panel-foot" id="foot-shown"><button class="wb-panel-remove">Remove step</button></div></aside>
<aside class="wb-panel"><div class="wb-panel-foot" id="foot-hidden"><button class="wb-panel-remove" hidden>Remove step</button></div></aside>
"""
_WORKBENCH_STEPS = r"""
  const shown = (id) => { const e = document.getElementById(id); return getComputedStyle(e).display !== 'none'; };
  const one = await page.evaluate((s) => eval(s), `({
    toolsMax: getComputedStyle(document.getElementById('tools')).maxHeight,
    runsW: Math.round(document.getElementById('runs').getBoundingClientRect().width),
    word: getComputedStyle(document.getElementById('runword')).display,
    more: getComputedStyle(document.getElementById('more')).display,
    rungroup: getComputedStyle(document.getElementById('rungroup')).display,
    switchword: getComputedStyle(document.getElementById('switchword')).display,
    footShown: getComputedStyle(document.getElementById('foot-shown')).display,
    footHidden: getComputedStyle(document.getElementById('foot-hidden')).display,
  })`);
  await page.evaluate(() => document.getElementById('bar').classList.add('wf-bar-more-open'));
  one.rungroupOpen = await page.evaluate(() => getComputedStyle(document.getElementById('rungroup')).display);
  return one;
"""


def test_the_workbench_on_a_desktop(tmp_path):
    r = _drive(tmp_path, html=_page(_WORKBENCH), steps=_WORKBENCH_STEPS, viewport=(1440, 900))["result"]
    assert r["toolsMax"] == "none", r          # WB-M-7: was a 200 px box inside the room
    assert r["runsW"] == 44 and r["word"] == "none", r   # WB-U-4: the run list folds beside a panel
    assert r["more"] == "none" and r["rungroup"] != "none" and r["switchword"] != "none", r
    assert r["footShown"] != "none" and r["footHidden"] == "none", r   # WB-U-13: Remove step under the form


def test_the_workbench_on_a_phone(tmp_path):
    r = _drive(tmp_path, html=_page(_WORKBENCH), steps=_WORKBENCH_STEPS, viewport=(390, 844))["result"]
    assert r["more"] != "none" and r["rungroup"] == "none" and r["switchword"] == "none", r  # name, switch, ⋯
    assert r["rungroupOpen"] != "none", r       # ⋯ shows the rest
    assert r["word"] != "none", r               # the phone keeps its run list as it is


def _picker_page(above: int) -> str:
    return _page(
        f"""
<div class="modal-content" style="position:fixed;left:100px;top:40px;width:900px;height:800px">
  <div id="layer" style="position:relative;height:800px;overflow:auto">
    <div style="height:{above}px"></div>
    <input id="field">
    <div class="wf-slot"><button class="wf-slot-pick" id="pick">Insert a field…</button></div>
  </div>
</div>
""",
        """
import { placeNear } from '/static/js/workbench/fieldPicker.js';
// After the window's entrance (a scale): a picker opens on a settled window.
await new Promise((r) => setTimeout(r, 400));
const box = document.createElement('div');
box.className = 'wf-picker';
box.style.height = '120px';
document.getElementById('layer').appendChild(box);
placeNear(box, document.getElementById('field'));
const b = box.getBoundingClientRect(), p = document.getElementById('pick').getBoundingClientRect();
window.__placed = { top: Math.round(b.top), left: Math.round(b.left), bottom: Math.round(b.bottom),
  pickTop: Math.round(p.top), pickBottom: Math.round(p.bottom), pickLeft: Math.round(p.left) };
""",
    )


_PLACED = "return await page.evaluate(() => window.__placed);"


def test_insert_a_field_opens_under_its_button(tmp_path):
    r = _drive(tmp_path, html=_picker_page(200), steps=_PLACED, viewport=(1440, 900))["result"]
    assert 0 <= r["top"] - r["pickBottom"] <= 8, r      # was the panel's top-right corner, 500 px away
    assert r["left"] == r["pickLeft"], r


def test_low_in_the_window_it_opens_above_its_button(tmp_path):
    r = _drive(tmp_path, html=_picker_page(640), steps=_PLACED, viewport=(1440, 900))["result"]
    assert 0 <= r["pickTop"] - r["bottom"] <= 8, r      # more room above: just above the button
    assert r["top"] >= 40, r                            # inside the window


# ── the Library, the Calendar, Mail and Settings at both widths ─────────────

_DOCS = """
<div id="doclib-modal" class="modal"><div class="modal-content doclib-modal-content" id="lib">
  <div class="modal-header"><h4>Library</h4></div><div class="modal-body">one folder, nearly empty</div></div></div>
<div id="calendar-modal" class="modal" style="display:flex"><div class="modal-content cal-modal-content" id="cal">
  <div class="modal-header"><h4>Calendar</h4></div>
  <div class="modal-body" id="cal-body"><div class="cal-grid" id="grid"><div class="cal-week-headers"><div class="cal-weekday">M</div></div>
    <div class="cal-week-row"><div class="cal-day">1</div></div><div class="cal-week-row"><div class="cal-day">8</div></div>
    <div class="cal-week-row"><div class="cal-day" id="busy"><span class="cal-day-num">15</span>
      <div class="cal-event-row">09:30 Team</div><div class="cal-event-row">10:00 Launch</div>
      <div class="cal-event-row">14:00 Review</div><div class="cal-event-more" id="more">+1 more</div></div></div><div class="cal-week-row"><div class="cal-day">22</div></div>
    <div class="cal-week-row"><div class="cal-day">29</div></div><div class="cal-week-row"><div class="cal-day">5</div></div></div>
    <div class="cal-splitter"></div><div class="cal-day-detail">the day</div></div></div></div>
<div id="styled-confirm-overlay" class="modal"><div class="modal-content styled-confirm-box" id="confirm">
  <div class="styled-confirm-details"><ul class="styled-confirm-details-list"><li class="styled-confirm-detail">
  <span class="styled-confirm-detail-label" id="label">Q3 Board Pack – Lumen 2.0 launch review, final, with the appendix</span>
  <span class="styled-confirm-detail-note">a duplicate</span></li></ul></div></div></div>
<div id="email-lib-modal" class="modal"><div class="email-reader-atts" id="atts">
  <span class="email-attachment-chip" style="width:220px" id="first">statement-september.pdf</span>
  <span class="email-attachment-chip" style="width:220px" id="second">fee-schedule-2027.pdf</span></div></div>
<div class="pan-source-offer" data-source-offer="1"
  style="position:fixed;right:10px;bottom:6px;z-index:9000;pointer-events:none;font-size:10px;line-height:1">
  <a href="#" id="source" style="pointer-events:auto;padding:3px 6px;border:1px solid var(--border)">Source</a></div>
<div class="doc-email-actions" id="footer"><button>Save</button></div>
<div class="admin-add-form"><input type="text" placeholder="Username"><input type="password" placeholder="Password (min 8)">
  <div class="admin-switch-inline"><label class="admin-switch"><input type="checkbox" id="isadmin"><span class="admin-slider"></span></label> Admin</div></div>
"""
_DOCS_STEPS = r"""
  await page.waitForTimeout(500);
  return await page.evaluate(() => {
    const r = (id) => document.getElementById(id).getBoundingClientRect();
    const g = document.getElementById('grid');
    return {
      lib: Math.round(r('lib').height), cal: Math.round(r('cal').height), vh: innerHeight,
      grid: [g.scrollHeight, g.clientHeight],
      busy: [document.getElementById('busy').scrollHeight, document.getElementById('busy').clientHeight],
      more: r('more').bottom <= r('busy').bottom + 1,
      confirm: Math.round(r('confirm').width),
      label: getComputedStyle(document.getElementById('label')).whiteSpace,
      atts: getComputedStyle(document.getElementById('atts')).flexWrap,
      second: [Math.round(r('second').top), Math.round(r('first').top)],
      source: { top: Math.round(r('source').top), left: Math.round(r('source').left), bottom: Math.round(r('source').bottom) },
      footerPad: getComputedStyle(document.getElementById('footer')).paddingBottom,
      check: Math.round(r('isadmin').right), width: innerWidth,
      pageWide: document.documentElement.scrollWidth,
    };
  });
"""


def test_the_documents_windows_on_a_desktop(tmp_path):
    r = _drive(tmp_path, html=_page(_DOCS), steps=_DOCS_STEPS, viewport=(1440, 900))["result"]
    assert r["lib"] == round(0.85 * 900), r          # DOCS-U-8: one height, not the content's
    assert r["cal"] == round(0.88 * 900), r
    assert r["grid"][0] <= r["grid"][1] + 1, r       # DOCS-U-15: every week shows, nothing behind a scroll
    assert r["busy"][0] <= r["busy"][1] + 1 and r["more"], r   # and a busy day is not cut: "+1 more" shows
    assert r["confirm"] == 480 and r["label"] == "normal", r   # DOCS-U-6: wide enough, names wrap
    assert r["footerPad"] == "30px", r               # CHAT-U-9: the editor's footer clears the Source tag


def test_the_documents_windows_on_a_phone(tmp_path):
    r = _drive(tmp_path, html=_page(_DOCS), steps=_DOCS_STEPS, viewport=(390, 844))["result"]
    assert r["atts"] == "nowrap" and r["second"][0] == r["second"][1], r   # DOCS-M-7: one row, sideways
    assert r["source"]["top"] < 30 and r["source"]["left"] < 20, r         # CHAT-U-9: top-left, off the send button
    assert r["check"] <= r["width"] and r["pageWide"] <= r["width"], r     # SET-M-21: nothing past the phone's edge


# ── fx-chat's CSS halves: B-NEW-5, B-NEW-6 ──────────────────────────────────

_CHAT_ROWS = """
<div class="agent-thread-node" id="done"><span class="agent-thread-dot" id="done-dot"></span>
  <div class="agent-thread-header"><span class="agent-thread-tool" id="done-tool">read</span></div></div>
<div class="agent-thread-node denied" id="denied"><span class="agent-thread-dot" id="denied-dot"></span>
  <div class="agent-thread-header"><span class="agent-thread-tool" id="denied-tool">shell</span></div></div>
<div class="agent-thread-node waiting" id="waiting"><span class="agent-thread-dot" id="waiting-dot"></span>
  <div class="agent-thread-header" id="waiting-head"><span class="agent-thread-tool">shell</span></div></div>
<div class="chat-input-bar" id="bar"></div>
<div class="preset-temp-hints" id="hints"><span>Precise</span><span>Balanced</span><span>Creative</span></div>
"""
_CHAT_STEPS = r"""
  return await page.evaluate(() => {
    const cs = (id) => getComputedStyle(document.getElementById(id));
    const plain = { style: cs('bar').borderTopStyle, bg: cs('bar').backgroundColor };
    document.body.classList.add('plan-mode-active');
    const plan = { style: cs('bar').borderTopStyle, bg: cs('bar').backgroundColor };
    return {
      done: [cs('done-dot').backgroundColor, cs('done-tool').textDecorationLine],
      denied: [cs('denied-dot').backgroundColor, cs('denied-tool').textDecorationLine],
      waiting: [cs('waiting-dot').borderTopStyle, cs('waiting-head').fontStyle],
      plain, plan, hintsTop: cs('hints').marginTop,
    };
  });
"""


def test_a_denied_or_waiting_tool_row_looks_its_own_and_plan_mode_leaves_the_composer(tmp_path):
    r = _drive(tmp_path, html=_page(_CHAT_ROWS), steps=_CHAT_STEPS, viewport=(1440, 900))["result"]
    assert r["denied"][1] == "line-through" and r["denied"][0] != r["done"][0], r
    assert r["done"][1] == "none", r
    assert r["waiting"] == ["dashed", "italic"], r
    assert r["plan"] == r["plain"], r          # CHAT-U-15: the chip and the pill say Plan; the composer does not
    assert r["hintsTop"] == "4px", r           # CHAT-U-21: the words clear the thumb


# ── fx-back's B-NEW-3: the opener beneath, dimmed and inert ─────────────────

_OPENER = """
<div id="memory-modal" class="modal" style="display:flex"><div class="modal-content memory-modal-content" id="brain">
  <div class="modal-header"><h4>Brain</h4><button class="close-btn" id="brain-x">✖</button></div></div></div>
<div id="skills-modal" class="modal" style="display:flex"><div class="modal-content" id="skills">
  <div class="modal-header"><button class="modal-back-btn" data-back-to="memory-modal">← Brain</button><h4>Skills</h4></div></div></div>
<div id="settings-modal" class="modal" style="display:flex"><div class="modal-content settings-modal-content" id="settings"></div></div>
"""
_OPENER_STEPS = r"""
  await page.waitForTimeout(400);
  return await page.evaluate(() => {
    const look = (id) => { const cs = getComputedStyle(document.getElementById(id)); return [cs.filter !== 'none', cs.pointerEvents]; };
    const open = { brain: look('brain'), settings: look('settings'), skills: look('skills') };
    document.getElementById('skills-modal').classList.add('hidden');
    return { open, closed: look('brain') };
  });
"""


def test_a_window_opened_from_another_leaves_its_opener_dimmed_and_inert(tmp_path):
    r = _drive(tmp_path, html=_page(_OPENER), steps=_OPENER_STEPS, viewport=(1440, 900))["result"]
    assert r["open"]["brain"] == [True, "none"], r          # the opener: dimmed, takes no pointer
    assert r["open"]["settings"] == [False, "auto"], r      # a window nobody opened from: as it was
    assert r["open"]["skills"] == [False, "auto"], r        # the window on top: live
    assert r["closed"] == [False, "auto"], r                # the window above it gone: the opener is back
