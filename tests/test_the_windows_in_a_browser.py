# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wave three's window rows, in a real browser against the running app.

The node files beside this one drive each module on its own; what only the
real app can show is the modules together — `app.js`'s 3,900-line initialiser,
the `ui.js` Escape arbiter, the real stylesheet, the real windows opened
through their real doors:

  * **`B945`** — with a reply's stop wrapped and counted, Escape from the
    message box closes the window that is open and the reply is not stopped;
    with nothing open, the same key stops it. Settings with its own finder
    focused, measured before the fix, closed *and* stopped.
  * **`B949`** — Tasks, built at runtime, and the static windows carry
    `role="dialog"` and no `aria-modal`; a blocking overlay built the way the
    PDF export builds it does; the styled confirm keeps its own; and at a phone
    width, where every window is a sheet over a backdrop, Tasks is modal.
  * **`B950`** — at the 1.25x text size on a 1400x800 screen, Compare, Deep
    Research and the Brain's Browse tab, each filled past its cap, stay on
    screen with their close buttons reachable, and a docked Notes pane ends at
    the bottom edge.
  * **`B947` (f)** — Tasks chosen in the command palette with Enter takes the
    focus on its move handle, and Escape there hands it back to the message box.
  * **`B952`** — the edge of a docked Notes pane is a separator one Shift+Tab
    from the pane; the arrows move it 16px the way they point (a right dock
    widens on ArrowLeft, a left dock on ArrowRight), the value is announced and
    the width saved like a drag's.

Boots the app out of process exactly as
`tests/test_the_command_palette_in_a_browser.py` does (its `app_url` fixture,
imported) and skips, with the reason, where node, Playwright or Chromium is
absent.
"""

import json
import subprocess

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1400, height: 800 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String((e && e.stack) || e)));
  const creds = { username: 'windows', password: 'windows-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(1500);
  const out = { errors };

  const shown = (id) => page.evaluate((id) => {
    const m = document.getElementById(id);
    return !!m && !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none'
      && m.getBoundingClientRect().width > 0;
  }, id);
  const settle = (ms = 700) => page.waitForTimeout(ms);
  const closeAll = async () => {
    for (let i = 0; i < 4; i++) {
      await page.evaluate(() => document.activeElement && document.activeElement.blur());
      await page.keyboard.press('Escape'); await settle(250);
    }
  };

  // ── B945 ────────────────────────────────────────────────────────────────
  // The reply's stop, counted. `stopCurrentReply` is what the key calls
  // (`P23-04`, CHAT-M-1: the Stop button's own path; it was
  // `abortCurrentRequest`, which left the server finishing the reply).
  await page.evaluate(() => {
    window.__stops = 0;
    const real = window.chatModule.stopCurrentReply;
    window.chatModule.stopCurrentReply = function (...a) { window.__stops += 1; return real.apply(this, a); };
  });
  const stops = () => page.evaluate(() => { const n = window.__stops; window.__stops = 0; return n; });
  await page.focus('#message'); await stops();
  await page.keyboard.press('Escape'); await settle(300);
  out.nothingOpen = await stops();

  // ── B947 (f) ────────────────────────────────────────────────────────────
  // A tool chosen in the palette from the keyboard takes the focus, and gives
  // it back to the message box when it closes.
  await page.focus('#message');
  await page.keyboard.press('Control+k'); await settle(200);
  await page.keyboard.type('tasks'); await settle(200);
  await page.keyboard.press('Enter'); await settle(1500);
  out.paletteLaunch = await page.evaluate(() => {
    const a = document.activeElement;
    return { cls: a ? a.className : null, inTasks: !!(a && a.closest && a.closest('#tasks-modal')) };
  });
  await page.keyboard.press('Escape'); await settle(800);
  out.paletteLaunchBack = await page.evaluate(() => document.activeElement && document.activeElement.id);
  await stops();

  const fresh = async () => {
    // Settings re-closes itself on the next open when its close animation
    // lost the race with its 250 ms fallback (filed with `B945`'s note), so
    // each Settings case starts from a page that has not closed it yet.
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await settle(1500);
    await page.evaluate(() => {
      window.__stops = 0;
      const real = window.chatModule.stopCurrentReply;
      window.chatModule.stopCurrentReply = function (...a) { window.__stops += 1; return real.apply(this, a); };
    });
  };

  out.fromComposer = {};
  for (const [id, door] of [['tasks-modal', 'tool-tasks-btn'], ['calendar-modal', 'tool-calendar-btn'],
                            ['theme-modal', 'tool-theme-btn'], ['settings-modal', 'user-bar-settings']]) {
    if (id === 'settings-modal') await fresh();
    await page.evaluate((door) => document.getElementById(door).click(), door);
    await settle(1500);
    const opened = await shown(id);
    await page.focus('#message'); await stops();
    await page.keyboard.press('Escape'); await settle(600);
    out.fromComposer[id] = { opened, stops: await stops(), stillOpen: await shown(id) };
    await closeAll(); await stops();
  }

  await fresh();
  await page.evaluate(() => document.getElementById('user-bar-settings').click()); await settle(1000);
  const finderOpened = await shown('settings-modal');
  await page.focus('#settings-nav-search'); await stops();
  const finderFocus = await page.evaluate(() => document.activeElement && document.activeElement.id);
  await page.keyboard.press('Escape'); await settle(600);
  out.settingsFinder = { opened: finderOpened, focus: finderFocus, stops: await stops(),
                         stillOpen: await shown('settings-modal') };
  await closeAll(); await stops();

  // ── B949 ────────────────────────────────────────────────────────────────
  const modality = (sel) => page.evaluate((sel) => {
    const c = document.querySelector(sel);
    return c ? { role: c.getAttribute('role'), modal: c.getAttribute('aria-modal') } : null;
  }, sel);
  await page.evaluate(() => document.getElementById('tool-tasks-btn').click()); await settle(1500);
  out.tasks = await modality('#tasks-modal .modal-content');
  out.statics = {};
  for (const id of ['memory-modal', 'theme-modal', 'settings-modal', 'cookbook-modal']) {
    out.statics[id] = await modality('#' + id + ' .modal-content, #' + id + ' #theme-popup');
  }
  // A blocking overlay, built the way `document.js` builds the PDF export.
  await page.evaluate(() => {
    const o = document.createElement('div');
    o.className = 'modal pdf-export-overlay';
    o.id = 'probe-export';
    o.style.cssText = 'pointer-events:auto;background:rgba(0,0,0,0.5);';
    o.innerHTML = '<div class="modal-content"><div class="modal-header"><h4>Export</h4></div></div>';
    document.body.appendChild(o);
  });
  await settle(300);
  out.exportOverlay = await modality('#probe-export .modal-content');
  await page.evaluate(() => document.getElementById('probe-export').remove());
  await page.evaluate(() => { window.__confirm = window.styledConfirm('Probe?'); }); await settle(300);
  out.confirm = await modality('#styled-confirm-overlay .modal-content');
  await page.evaluate(() => document.getElementById('styled-confirm-cancel').click()); await settle(300);
  await page.setViewportSize({ width: 600, height: 800 }); await settle(600);
  out.tasksOnAPhone = await modality('#tasks-modal .modal-content');
  await page.setViewportSize({ width: 1400, height: 800 }); await settle(600);
  out.tasksBackOnADesktop = await modality('#tasks-modal .modal-content');
  await closeAll();

  // ── B950 ────────────────────────────────────────────────────────────────
  // The 1.25x text size, each window filled past its cap: the window and its
  // close button must be on screen, and a docked pane must end at the bottom.
  await page.evaluate(() => document.documentElement.classList.add('ui-scale-125'));
  await settle(400);
  const measure = (sel, closeSel) => page.evaluate(([sel, closeSel]) => {
    const c = document.querySelector(sel);
    if (!c) return null;
    const r = c.getBoundingClientRect();
    const b = closeSel ? c.querySelector(closeSel) : null;
    let closeOnScreen = null;
    if (b) {
      const br = b.getBoundingClientRect();
      const hit = document.elementFromPoint(br.left + br.width / 2, br.top + br.height / 2);
      closeOnScreen = !!hit && (hit === b || b.contains(hit));
    }
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), screen: innerHeight, closeOnScreen };
  }, [sel, closeSel]);
  const fill = (sel) => page.evaluate((sel) => {
    const c = document.querySelector(sel);
    if (!c) return;
    const f = document.createElement('div');
    f.style.cssText = 'height:3000px;flex:0 0 auto';
    (c.querySelector('.modal-body, .research-pane-body, #memory-list') || c).appendChild(f);
  }, sel);
  const CLOSE = '.close-btn, .modal-close, [data-close], #research-close-btn';
  await page.evaluate(() => document.getElementById('tool-compare-btn').click()); await settle(1200);
  await fill('#compare-model-overlay .modal-content'); await settle(300);
  out.zoomCompare = await measure('#compare-model-overlay .modal-content', CLOSE);
  await page.evaluate(() => { const o = document.getElementById('compare-model-overlay'); if (o) o.remove(); });
  await settle(400);
  await page.evaluate(() => document.getElementById('tool-research-btn').click()); await settle(1200);
  await fill('#research-pane'); await settle(300);
  out.zoomResearch = await measure('#research-pane', CLOSE);
  // `P23-01` (NAV-M-7): a door raises, it no longer closes — the window's ×.
  await page.evaluate(() => document.getElementById('research-panel-close').click()); await settle(800);
  await page.evaluate(() => document.getElementById('tool-memory-btn').click()); await settle(1200);
  await page.evaluate(() => { const t = document.querySelector('[data-memory-tab="browse"]'); if (t) t.click(); });
  await settle(400);
  await fill('#memory-modal .memory-modal-content'); await settle(300);
  out.zoomBrain = await measure('#memory-modal .memory-modal-content', CLOSE);
  await page.evaluate(() => document.querySelector('#memory-modal .close-btn').click()); await settle(600);
  await page.evaluate(() => document.getElementById('tool-notes-btn').click()); await settle(1500);
  out.zoomNotes = await measure('.notes-pane.modal-right-docked', null);
  await page.evaluate(() => document.documentElement.classList.remove('ui-scale-125'));
  await settle(400);
  out.notesAtDefault = await measure('.notes-pane.modal-right-docked', null);

  // ── B952 ────────────────────────────────────────────────────────────────
  // Notes is docked on the right. Its edge, from the keyboard.
  const RIGHT = '.edge-dock-resize-handle-right';
  const handle = (sel) => page.evaluate((sel) => {
    const h = document.querySelector(sel);
    return h && { role: h.getAttribute('role'), tabindex: h.getAttribute('tabindex'),
                  label: h.getAttribute('aria-label'), orientation: h.getAttribute('aria-orientation'),
                  now: Number(h.getAttribute('aria-valuenow')), min: Number(h.getAttribute('aria-valuemin')),
                  max: Number(h.getAttribute('aria-valuemax')), shown: h.style.display !== 'none',
                  focused: document.activeElement === h,
                  ring: getComputedStyle(h).outlineStyle !== 'none' };
  }, sel);
  const paneWidth = (sel) => page.evaluate((sel) => Math.round(document.querySelector(sel).getBoundingClientRect().width), sel);
  await page.evaluate(() => {
    const first = document.querySelector('.notes-pane button, .notes-pane input, .notes-pane [tabindex="0"]');
    if (first) first.focus();
  });
  let presses = 0;
  for (; presses < 10; presses++) {
    if ((await handle(RIGHT)).focused) break;
    await page.keyboard.press('Shift+Tab');
  }
  out.dockShiftTabs = presses;
  await page.focus(RIGHT);
  out.dockHandle = await handle(RIGHT);
  out.dockStart = await paneWidth('.notes-pane');
  for (let i = 0; i < 3; i++) await page.keyboard.press('ArrowLeft');
  out.dockWider = await paneWidth('.notes-pane');
  await page.keyboard.press('ArrowRight');
  out.dockNarrower = await paneWidth('.notes-pane');
  out.dockAria = (await handle(RIGHT)).now;
  out.dockSaved = await page.evaluate(() => localStorage.getItem('pantheon-edge-dock-width:right:notes-pane'));
  await page.evaluate(() => document.documentElement.classList.add('ui-scale-125')); await settle(400);
  await page.focus(RIGHT);
  const zoomBefore = await paneWidth('.notes-pane');
  await page.keyboard.press('ArrowLeft');
  out.dockZoomStep = (await paneWidth('.notes-pane')) - zoomBefore;
  await page.evaluate(() => document.documentElement.classList.remove('ui-scale-125')); await settle(400);
  // A left dock: the separator sits on the window's right edge, so there
  // ArrowRight widens it. Notes is put away first, so the chat beside the
  // dock has the room a wider window needs (the clamp keeps 380px for it).
  // `P23-01` (NAV-U-8): Notes has a × of its own now; its door raises.
  await page.evaluate(() => document.getElementById('notes-close-btn').click()); await settle(800);
  await page.evaluate(() => document.getElementById('tool-tasks-btn').click()); await settle(1500);
  await page.evaluate(async () => {
    const snap = await import('/static/js/modalSnap.js');
    snap.applyEdgeDock(document.getElementById('tasks-modal'), 'left');
  });
  await settle(600);
  await page.focus('.edge-dock-resize-handle-left');
  const leftStart = await paneWidth('#tasks-modal .modal-content');
  await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight');
  out.leftWider = (await paneWidth('#tasks-modal .modal-content')) - leftStart;
  await page.keyboard.press('ArrowLeft');
  out.leftNarrower = (await paneWidth('#tasks-modal .modal-content')) - leftStart;
  out.leftHandle = await handle('.edge-dock-resize-handle-left');

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def run(app_url, tmp_path_factory):  # noqa: F811
    script = tmp_path_factory.mktemp("windows-pw") / "windows.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


# ── B945 ───────────────────────────────────────────────────────────────────

def test_escape_with_nothing_open_stops_the_reply(run):
    assert run["nothingOpen"] == 1


@pytest.mark.parametrize("window", ["tasks-modal", "calendar-modal", "theme-modal", "settings-modal"])
def test_escape_from_the_message_box_closes_the_window_and_keeps_the_reply(run, window):
    got = run["fromComposer"][window]
    assert got["opened"] is True, f"{window} did not open through its door"
    assert got["stillOpen"] is False, f"{window} did not close"
    assert got["stops"] == 0, f"closing {window} also stopped the reply"


def test_escape_in_settings_own_finder_keeps_the_reply(run):
    got = run["settingsFinder"]
    assert got["opened"] is True and got["focus"] == "settings-nav-search", got
    assert got["stops"] == 0, got


# ── B949 ───────────────────────────────────────────────────────────────────

def test_a_tool_window_is_a_dialog_and_not_modal(run):
    assert run["tasks"] == {"role": "dialog", "modal": None}
    for window, got in run["statics"].items():
        assert got and got["modal"] is None, f"{window} is announced as blocking: {got}"


def test_a_blocking_overlay_is_modal_and_the_confirm_keeps_its_own(run):
    assert run["exportOverlay"] == {"role": "dialog", "modal": "true"}
    assert run["confirm"]["modal"] == "true"


def test_on_a_phone_a_window_is_a_sheet_and_is_modal(run):
    assert run["tasksOnAPhone"]["modal"] == "true"
    assert run["tasksBackOnADesktop"]["modal"] is None


# ── B950 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("window, cap", [
    ("zoomCompare", lambda screen: 720),            # its own cap, min(720px, 100dvh - 48px)
    ("zoomResearch", lambda screen: 0.85 * screen),  # its classes' 85vh
    ("zoomBrain", lambda screen: 0.78 * screen),     # the Browse tab's 78vh
], ids=["compare", "research", "brain"])
def test_at_the_larger_text_size_a_full_window_keeps_its_footprint(run, window, cap):
    """The row's `Verify` at 1400x800: measured before the fix, Compare stood
    900px tall with its header 50px above the top, Deep Research 25px above,
    and the Brain's Browse tab 780px (97.5% — on screen, and still
    uncompensated). Compensated, each renders the footprint its own cap gives
    it at the default size, with the close button on screen."""
    got = run[window]
    assert got is not None, f"{window}: the window did not open"
    assert got["top"] >= 0 and got["bottom"] <= got["screen"], got
    assert got["closeOnScreen"] is True, got
    assert got["bottom"] - got["top"] <= cap(got["screen"]) + 1, (
        f"{window} is taller than its own cap at the default size: {got}")


def test_at_the_larger_text_size_a_docked_pane_ends_at_the_bottom(run):
    """Measured before the fix: a docked Notes pane 1000px tall on an 800px
    screen. And at the default size it still fills the height."""
    for key in ("zoomNotes", "notesAtDefault"):
        got = run[key]
        assert got is not None, f"{key}: Notes did not dock"
        assert got["top"] == 0 and got["bottom"] == got["screen"], (key, got)


# ── B952 ───────────────────────────────────────────────────────────────────

def test_a_docked_window_s_edge_is_a_separator_in_the_tab_order(run):
    """`P10-03`'s treatment: role, orientation, a name, the three values, a
    tab stop — and the global focus ring, not a rule of its own."""
    h = run["dockHandle"]
    assert h["role"] == "separator" and h["orientation"] == "vertical"
    assert h["tabindex"] == "0" and h["label"] == "Resize docked window"
    assert h["shown"] and h["focused"] and h["ring"], h
    assert 0 < h["min"] <= h["now"] <= h["max"], h
    assert h["now"] == run["dockStart"], (
        "the announced width is not the pane's width before any key was pressed "
        f"(a drag or the dock must keep it current): {h['now']} vs {run['dockStart']}")
    assert run["dockShiftTabs"] <= 3, (
        f"the edge is {run['dockShiftTabs']} Shift+Tab presses from the docked pane")


def test_the_arrows_move_the_edge_where_they_point_and_the_width_is_kept(run):
    """The row's `Verify`: Tab to the edge of a docked Notes pane and widen it
    with the arrows. On a right dock the edge is the window's left side, so
    ArrowLeft widens it; 16px a press, like the sidebar's separators."""
    assert run["dockWider"] - run["dockStart"] == 48
    assert run["dockNarrower"] - run["dockStart"] == 32
    assert run["dockAria"] == run["dockNarrower"]
    assert run["dockSaved"] == str(run["dockNarrower"])


def test_on_a_left_dock_the_right_arrow_widens(run):
    assert run["leftHandle"]["focused"], run["leftHandle"]
    assert run["leftWider"] == 32
    assert run["leftNarrower"] == 16


def test_at_the_larger_text_size_a_press_is_still_one_step(run):
    """16 CSS pixels, which the 1.25x scale draws as 20. Taken from the edge's
    on-screen position instead, a press jumped 195."""
    assert run["dockZoomStep"] == 20


# ── B947 (f) ───────────────────────────────────────────────────────────────

def test_a_tool_chosen_from_the_palette_by_keyboard_takes_the_focus(run):
    assert run["paletteLaunch"]["inTasks"] is True, run["paletteLaunch"]
    assert "window-move-handle" in run["paletteLaunch"]["cls"]
    assert run["paletteLaunchBack"] == "message"


def test_nothing_threw(run):
    assert run["errors"] == []
