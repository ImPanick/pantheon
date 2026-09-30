# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-01` in a real browser — the keyboard and focus path, end to end.

`tests/test_the_search_box_is_the_command_palette_js.py` drives the palette's
logic under node. This file boots the real app out of process (a temporary data
directory, a free port, the built-in MCP servers off) and drives it with a real
headless Chromium through Playwright, because three things cannot be shown any
other way:

  * **the callers in `app.js`** — the rail button, the sidebar button and the
    page-wide Escape chain live inside a 3,900-line initialiser that no sandbox
    loads, and they are the FORBIDDEN.md Part 1 reason the three ids exist;
  * **real keys and real focus** — Ctrl+K reaching the `search` keybind,
    Escape handing the caret back to the element it came from, `Enter` on a
    highlighted tool opening the real window;
  * **stacking** — measured before this row: with Calendar open (z 1001), the
    overlay (z 300) opened *behind* it; `elementFromPoint` at the box's centre
    answered `#cal-quickadd`.

The chat search is answered by the test (`page.route`) so a hostile chat title
can be put in its path; everything else is the app.

Skipped, with the reason, where node, the `playwright` package or its Chromium
is not installed.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _browser():
    node = shutil.which("node")
    if not node:
        return None, "node binary not on PATH"
    probe = subprocess.run(
        [node, "-e",
         "const { chromium } = require('playwright');"
         "const fs = require('fs');"
         "const p = chromium.executablePath();"
         "process.stdout.write(fs.existsSync(p) ? p : '');"],
        capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        return None, "the playwright node package is not installed"
    if not probe.stdout.strip():
        return None, "playwright has no Chromium downloaded"
    return node, None


NODE, _SKIP = _browser()
pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    data = tmp_path_factory.mktemp("palette-app")
    port = _free_port()
    env = dict(os.environ, PANTHEON_DATA_DIR=str(data), APP_PORT=str(port),
               APP_BIND="127.0.0.1", PANTHEON_DISABLE_MCP="1")
    log = open(data / "app.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
        while True:
            if proc.poll() is not None:
                log.flush()
                pytest.fail("the app exited during start-up:\n"
                            + (data / "app.log").read_text(encoding="utf-8")[-3000:])
            try:
                with urllib.request.urlopen(url + "/login", timeout=2) as res:
                    if res.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.monotonic() > deadline:
                pytest.fail("the app did not answer /login within 120 s")
            time.sleep(0.5)
        yield url
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()


_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const HOSTILE = '<img src=x onerror="window.__pwned=1">';
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String((e && e.stack) || e)));
  const out = { errors };
  const creds = { username: 'palette', password: 'palette-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  // The chat lane, answered here: one hostile chat for "needle", nothing else.
  await page.route('**/api/search?**', (route) => {
    const q = new URL(route.request().url()).searchParams.get('q');
    const body = q === 'needle' ? [{ message_id: 'm1', session_id: 's-evil', session_name: HOSTILE,
      role: 'user', content_snippet: '<script>window.__pwned=2</script> a needle here', timestamp: null }] : [];
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true && window._isAdmin === true,
                             null, { timeout: 60000 });
  await page.waitForTimeout(1500);

  const state = () => page.evaluate(() => {
    const ov = document.getElementById('search-overlay');
    const inp = document.getElementById('search-input');
    const act = inp.getAttribute('aria-activedescendant');
    const actEl = act ? document.getElementById(act) : null;
    const a = document.activeElement;
    return {
      open: !ov.classList.contains('hidden') && getComputedStyle(ov).display !== 'none',
      z: parseInt(getComputedStyle(ov).zIndex, 10) || 0,
      focus: a ? (a.id || a.tagName) : null,
      expanded: inp.getAttribute('aria-expanded'),
      active: actEl ? ((actEl.querySelector('.search-palette-label, .search-result-snippet') || actEl).textContent) : null,
      groups: [...document.querySelectorAll('#search-results [role="group"]')]
        .map((g) => (document.getElementById(g.getAttribute('aria-labelledby')) || {}).textContent || null),
      options: [...document.querySelectorAll('#search-results [role="option"]')].length,
      status: (document.getElementById('search-status') || {}).textContent || null,
    };
  });
  const k = (key) => page.keyboard.press(key);
  const typeIn = async (text) => { await page.keyboard.type(text); await page.waitForTimeout(80); };
  // Each scenario starts from the same place — box shut, composer empty, caret
  // in it — so one scenario's outcome cannot decide the next one's (the same
  // script is run against the tree before this row, where Enter chose nothing).
  const fresh = async () => {
    for (let i = 0; i < 3; i++) {
      const open = await page.evaluate(() => !document.getElementById('search-overlay').classList.contains('hidden'));
      if (!open) break;
      await k('Escape');
    }
    await page.evaluate(() => { const m = document.getElementById('message'); m.value = ''; m.dispatchEvent(new Event('input', { bubbles: true })); });
    await page.focus('#message');
  };

  // Ctrl+K from the composer — the `search` keybind.
  await page.focus('#message');
  await k('Control+k');
  out.ctrlK = await state();
  await typeIn('calendar');
  out.typed = await state();
  await k('ArrowDown'); out.down = await state();
  await k('ArrowUp'); out.up = await state();
  await k('Escape'); out.escaped = await state();

  // Ctrl+K a second time closes it.
  await k('Control+k'); await k('Control+k'); out.toggled = await state();

  // The sidebar's Search button; Escape hands focus back to it.
  await page.click('#sidebar-search-btn'); out.sidebar = await state();
  await k('Escape'); out.sidebarEsc = await state();

  // `app.js`'s own Escape chain, with the caret moved off the box.
  await page.focus('#message');
  await k('Control+k');
  await page.evaluate(() => document.activeElement.blur());
  await k('Escape'); out.chain = await state();

  // The rail's Search button, with the sidebar folded to the rail.
  await page.evaluate(() => { document.getElementById('sidebar').classList.add('hidden'); window.syncRailSide && window.syncRailSide(); });
  await page.waitForTimeout(200);
  out.railVisible = await page.evaluate(() => document.getElementById('rail-search-btn').getClientRects().length > 0);
  if (out.railVisible) {
    await page.click('#rail-search-btn'); out.rail = await state();
    await k('Escape'); out.railEsc = await state();
  }
  await page.evaluate(() => { document.getElementById('sidebar').classList.remove('hidden'); window.syncRailSide && window.syncRailSide(); });

  // A tool, by keyboard alone; then the box over it; then the same tool again.
  await fresh();
  await k('Control+k'); await typeIn('calendar'); await k('Enter');
  // Tolerant waits: the same script is run against the tree before this row,
  // where Enter chose nothing, and must still report rather than die.
  out.calendarOpened = await page.waitForFunction(() => {
    const m = document.getElementById('calendar-modal');
    return m && !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none';
  }, null, { timeout: 10000 }).then(() => true, () => false);
  if (!out.calendarOpened) await page.evaluate(() => document.getElementById('tool-calendar-btn').click());
  await page.waitForTimeout(800);
  out.calendarZ = await page.evaluate(() => parseInt(getComputedStyle(document.getElementById('calendar-modal')).zIndex, 10) || 0);
  await k('Control+k');
  out.over = await page.evaluate(() => {
    const inp = document.getElementById('search-input');
    const r = inp.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { inputIsTop: hit === inp, hit: hit ? (hit.id || hit.className) : null };
  });
  await typeIn('calendar'); await k('Enter');
  await page.waitForTimeout(400);
  out.calendarStillOpen = await page.evaluate(() => {
    const m = document.getElementById('calendar-modal');
    return !!m && !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none';
  });
  await page.evaluate(() => { const b = document.querySelector('#calendar-modal .close-btn, #calendar-modal .modal-close'); if (b) b.click(); });
  await page.waitForTimeout(400);

  // A Settings panel.
  await fresh();
  await k('Control+k'); await typeIn('network');
  out.network = await state();
  await k('Enter');
  await page.waitForTimeout(600);
  out.settings = await page.evaluate(() => {
    const m = document.getElementById('settings-modal');
    const p = m && m.querySelector('[data-settings-panel="networks"]');
    return { open: !!m && !m.classList.contains('hidden'), panel: !!p && !p.classList.contains('hidden') };
  });
  await page.evaluate(() => { const b = document.querySelector('#settings-modal .close-btn, #settings-modal .modal-close, #settings-modal [data-close]'); if (b) b.click(); });
  await page.waitForTimeout(300);

  // The Skills window (`P9-06`) — through its own door, not the Brain's.
  await fresh();
  await k('Control+k'); await typeIn('skills'); out.skillsFound = await state(); await k('Enter');
  out.skillsOpened = await page.waitForFunction(() => {
    const m = document.getElementById('skills-modal');
    return m && !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none';
  }, null, { timeout: 8000 }).then(() => true, () => false);
  out.brainAfterSkills = await page.evaluate(() => {
    const m = document.getElementById('memory-modal');
    return !!m && !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none';
  });
  await page.evaluate(() => { const b = document.getElementById('close-skills-modal'); if (b) b.click(); });
  await page.waitForTimeout(400);

  // A command, into the message box.
  await fresh();
  await k('Control+k'); await typeIn('rename'); out.rename = await state(); await k('Enter');
  out.command = await page.evaluate(() => ({ value: document.getElementById('message').value,
    focus: document.activeElement && document.activeElement.id }));
  await page.evaluate(() => { const m = document.getElementById('message'); m.value = ''; m.dispatchEvent(new Event('input', { bubbles: true })); });

  // A hostile chat title.
  await fresh();
  await k('Control+k'); await typeIn('needle');
  await page.waitForSelector('#search-results [data-session]', { timeout: 5000 }).catch(() => null);
  out.hostile = await page.evaluate(() => ({
    headings: [...document.querySelectorAll('#search-results .search-group-header')].map((h) => h.textContent),
    snippet: (document.querySelector('#search-results .search-result-snippet') || {}).textContent || null,
    imgs: document.querySelectorAll('#search-results img, #search-results script').length,
    pwned: window.__pwned || null,
  }));
  await k('Escape');
  out.searchChatErrors = errors.filter((e) => e.includes('search-chat.js'));
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def run(app_url, tmp_path_factory):
    script = tmp_path_factory.mktemp("palette-pw") / "palette.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=240, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def test_ctrl_k_opens_the_box_with_the_caret_in_it_and_escape_hands_it_back(run):
    assert run["ctrlK"]["open"] is True
    assert run["ctrlK"]["focus"] == "search-input"
    assert run["ctrlK"]["expanded"] == "false"
    assert run["escaped"]["open"] is False
    # Before `P9-01` this was <body>: the composer lost its caret.
    assert run["escaped"]["focus"] == "message"
    assert run["toggled"]["open"] is False


def test_the_keyboard_alone_finds_moves_and_is_told_what_it_found(run):
    typed = run["typed"]
    assert typed["groups"][0] == "Tools"
    assert typed["active"] == "Calendar"
    assert typed["expanded"] == "true"
    assert typed["status"].split(" ", 1)[0].isdigit() and "Esc to close" in typed["status"]
    assert run["down"]["active"] != "Calendar"
    assert run["up"]["active"] == "Calendar"


def test_the_callers_in_app_js_still_open_and_close_it(run):
    """The sidebar button, the rail button and the page-wide Escape chain —
    the reason FORBIDDEN.md keeps the three ids."""
    assert run["sidebar"]["open"] is True and run["sidebar"]["focus"] == "search-input"
    assert run["sidebarEsc"]["open"] is False
    assert run["sidebarEsc"]["focus"] == "sidebar-search-btn"
    assert run["chain"]["open"] is False
    assert run["railVisible"] is True
    assert run["rail"]["open"] is True
    assert run["railEsc"]["open"] is False


def test_a_tool_opens_and_the_box_is_drawn_over_it(run):
    """Measured on the tree before this row: Calendar at z 1001 over a box at
    z 300, and `elementFromPoint` at the box's centre was `#cal-quickadd`."""
    assert run["calendarOpened"] is True
    assert run["calendarZ"] > 300
    assert run["over"]["inputIsTop"] is True, run["over"]
    # Choosing Calendar with Calendar open raises it; the door would close it.
    assert run["calendarStillOpen"] is True


def test_a_settings_panel_opens_where_it_lives(run):
    assert "Settings" in run["network"]["groups"]
    assert run["network"]["active"] == "Networks"
    assert run["settings"] == {"open": True, "panel": True}


def test_the_skills_window_opens_and_the_brain_stays_shut(run):
    """`P9-06`'s window has no rail or sidebar button; the palette opens it
    with `openSkillsWindow`, as the Brain's own launcher card does."""
    assert run["skillsFound"]["active"] == "Skills"
    assert run["skillsOpened"] is True
    assert run["brainAfterSkills"] is False


def test_a_command_lands_in_the_message_box_ready_for_its_arguments(run):
    assert run["rename"]["active"] == "/rename"
    assert run["command"] == {"value": "/rename ", "focus": "message"}


def test_a_hostile_chat_title_is_drawn_as_its_characters(run):
    hostile = run["hostile"]
    assert '<img src=x onerror="window.__pwned=1">' in hostile["headings"]
    assert hostile["snippet"] == "<script>window.__pwned=2</script> a needle here"
    assert hostile["imgs"] == 0
    assert hostile["pwned"] is None
    assert run["searchChatErrors"] == []
