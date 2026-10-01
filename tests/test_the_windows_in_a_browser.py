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
  // The reply's stop, counted. `abortCurrentRequest` is what the key calls.
  await page.evaluate(() => {
    window.__stops = 0;
    const real = window.chatModule.abortCurrentRequest;
    window.chatModule.abortCurrentRequest = function (...a) { window.__stops += 1; return real.apply(this, a); };
  });
  const stops = () => page.evaluate(() => { const n = window.__stops; window.__stops = 0; return n; });
  await page.focus('#message'); await stops();
  await page.keyboard.press('Escape'); await settle(300);
  out.nothingOpen = await stops();

  const fresh = async () => {
    // Settings re-closes itself on the next open when its close animation
    // lost the race with its 250 ms fallback (filed with `B945`'s note), so
    // each Settings case starts from a page that has not closed it yet.
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await settle(1500);
    await page.evaluate(() => {
      window.__stops = 0;
      const real = window.chatModule.abortCurrentRequest;
      window.chatModule.abortCurrentRequest = function (...a) { window.__stops += 1; return real.apply(this, a); };
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


def test_nothing_threw(run):
    assert run["errors"] == []
