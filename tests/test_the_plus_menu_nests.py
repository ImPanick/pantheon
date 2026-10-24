# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P25-01` — the composer's + menu, nested.

The owner, 2026-10-24, with two references: *"I like the sheer amount of
options - but i love how anthropic nests them."* So the top level is short —
*Add files*, *Documents*, *Workspace*, then *Agents ›*, *Skills ›*, *Modes ›*,
then *Prompt* — every row with a hint, and a › row opens its submenu beside the
menu (over it, as a page with a back row, on a phone).

Driven, not read (`Law 20`): the real app out of process on its own data
directory, a published skill planted through `SkillsManager`, signed in, in
headless Chromium at 1440×900 and 390×844; the real `app.js`, `composerMenu.js`,
`summon.js` and `static/style.css`.

**Measured before this row, on `386f80f`:** the menu was one flat list of six
(*Attach files / Documents / RAG / Workspace / Agents / Prompt*), *Agents*
opened a dialog of its own above the composer, a skill could be reached only
by typing its slash command, and a chip collapsed for room was reached by a
mirror row the menu grew at its top.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, _free_port  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
USER, PASSWORD = "plus", "plus-pass-1"


def _plant(data: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from services.memory.skills import SkillsManager

    SkillsManager(str(data)).add_skill(
        name="tidy-downloads", description="Sort the downloads folder by kind", category="files",
        tags=["files"], when_to_use="When downloads pile up", procedure=["List", "Sort", "Report"],
        owner=USER, status="published", source="user")


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    data = tmp_path_factory.mktemp("plus-menu")
    _plant(data)
    port = _free_port()
    env = dict(os.environ, PANTHEON_DATA_DIR=str(data), APP_PORT=str(port), APP_BIND="127.0.0.1",
               PANTHEON_DISABLE_MCP="1", AUTH_ENABLED="true", LOCALHOST_BYPASS="false")
    env.pop("DATABASE_URL", None)
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
const [BASE, USER, PASSWORD] = process.argv.slice(2);
const SUB = '.composer-submenu';
const labels = (page, sel) => page.$$eval(sel, (ns) => ns.map((n) => n.textContent.trim()));
const rect = (page, sel) => page.$eval(sel, (n) => { const r = n.getBoundingClientRect();
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width }; });
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  await (await browser.newContext()).request.post(BASE + '/api/auth/setup',
    { data: { username: USER, password: PASSWORD } });
  for (const [w, h] of [[1440, 900], [390, 844]]) {
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
    await page.waitForTimeout(800);
    await page.evaluate(() => document.getElementById('mode-agent-btn').click());
    await page.waitForTimeout(300);
    const o = {};
    await page.click('#overflow-plus-btn');
    await page.waitForTimeout(500);
    o.top = await page.$$eval('#overflow-menu .overflow-menu-item', (ns) => ns
      .filter((n) => n.offsetParent !== null).map((n) => n.querySelector('span').textContent.trim()));
    o.hints = await labels(page, '#overflow-menu .overflow-hint');
    o.seps = (await page.$$('#overflow-menu .overflow-menu-sep')).length;

    // Agents ›, opened the way each screen opens it.
    if (phone) await page.click('#overflow-agents-btn');
    else await page.hover('#overflow-agents-btn');
    await page.waitForSelector(`${SUB}[data-submenu="agents"] .composer-submenu-list .composer-submenu-row`, { timeout: 20000 });
    await page.waitForTimeout(300);
    o.agents = (await labels(page, `${SUB} .composer-submenu-list .composer-submenu-label`)).slice(0, 3);
    o.foot = await labels(page, `${SUB} .composer-submenu-foot`);
    const menu = await rect(page, '#overflow-menu');
    const sub = await rect(page, SUB);
    o.beside = sub.left >= menu.right - 1;
    o.covers = Math.abs(sub.bottom - menu.bottom) < 2 && sub.left <= menu.left + 1;
    o.menuHiddenUnder = await page.$eval('#overflow-menu', (n) => getComputedStyle(n).visibility === 'hidden');
    o.back = await labels(page, '.composer-submenu-back');
    await page.fill('.composer-submenu-search', 'morning');
    await page.waitForTimeout(150);
    o.filtered = await labels(page, `${SUB} .composer-submenu-list .composer-submenu-label`);

    if (phone) {
      await page.click('.composer-submenu-back');
      await page.waitForTimeout(200);
      o.afterBack = { sub: (await page.$$(SUB)).length,
        menu: await page.$eval('#overflow-menu', (n) => !n.classList.contains('hidden') && getComputedStyle(n).visibility !== 'hidden') };
      await page.click('#overflow-agents-btn');
      await page.waitForSelector(`${SUB} .composer-submenu-row`, { timeout: 20000 });
      await page.fill('.composer-submenu-search', 'morning');
      await page.waitForTimeout(150);
      await page.click(`${SUB} .composer-submenu-list .composer-submenu-row:has-text("Morning Brief")`);
      await page.waitForTimeout(600);
      o.chip = await page.$eval('#summon-indicator-name', (n) => n.textContent);
      o.closed = await page.$eval('#overflow-menu', (n) => n.classList.contains('hidden')) && !(await page.$(SUB));
    } else {
      // The keyboard: Escape in the submenu goes back to its row; then down
      // to Modes, → opens it with its first row focused.
      await page.keyboard.press('Escape');
      await page.waitForTimeout(150);
      o.escBack = { sub: (await page.$$(SUB)).length,
                    focus: await page.evaluate(() => document.activeElement && document.activeElement.id),
                    menuOpen: await page.$eval('#overflow-menu', (n) => !n.classList.contains('hidden')) };
      for (let i = 0; i < 4; i++) await page.keyboard.press('ArrowDown');   // Skills, Git, Browser, Modes
      o.down = await page.evaluate(() => document.activeElement && document.activeElement.id);
      await page.keyboard.press('ArrowRight');
      await page.waitForSelector(`${SUB}[data-submenu="modes"] .composer-submenu-row`, { timeout: 5000 });
      await page.waitForTimeout(150);
      o.modes = await labels(page, `${SUB} .composer-submenu-label`);
      o.modeFocus = await page.evaluate(() => document.activeElement && document.activeElement.textContent);
      // A mode is a switch: the menu stays open and the row shows the chip's state.
      const before = await page.$eval('#bash-toggle-btn', (n) => n.classList.contains('active'));
      await page.click(`${SUB} .composer-submenu-row:has-text("Shell")`);
      await page.waitForTimeout(300);
      o.shell = { flipped: before !== await page.$eval('#bash-toggle-btn', (n) => n.classList.contains('active')),
        row: await page.$eval(`${SUB} .composer-submenu-row:has-text("Shell")`, (n) => n.getAttribute('aria-checked')),
        chip: await page.$eval('#bash-toggle-btn', (n) => String(n.classList.contains('active'))),
        open: !!(await page.$(SUB)) };
      // Skills ›: a pick is the slash command the composer already reads.
      await page.hover('#overflow-menu [data-submenu="skills"]');
      await page.waitForSelector(`${SUB}[data-submenu="skills"] .composer-submenu-list .composer-submenu-row`, { timeout: 20000 });
      o.skills = await labels(page, `${SUB} .composer-submenu-list .composer-submenu-label`);
      o.skillsFoot = await labels(page, `${SUB} .composer-submenu-foot`);
      await page.click(`${SUB} .composer-submenu-row:has-text("tidy-downloads")`);
      await page.waitForTimeout(600);
      o.message = await page.$eval('#message', (n) => n.value);
      o.closed = await page.$eval('#overflow-menu', (n) => n.classList.contains('hidden')) && !(await page.$(SUB));
    }
    out[w] = o;
    await context.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def driven(app_url, tmp_path_factory):
    d = tmp_path_factory.mktemp("plus-menu-js")
    script = d / "plus.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, USER, PASSWORD], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_nothing_threw(driven):
    assert driven["errors"] == []


@pytest.mark.parametrize("width", ["1440", "390"])
def test_the_top_level_is_short_and_says_what_each_row_does(driven, width):
    o = driven[width]
    assert o["top"] == ["Add files", "Documents", "Workspace", "Agents", "Skills", "Git", "Browser",
                        "Modes", "Prompt"], "RAG lives under Modes; every other row kept"
    assert o["hints"] == ["From this device", "Write beside the chat", "A folder the agent works in",
                          "Watch the agent browse, or browse with it", "Persona and system prompt"]
    assert o["seps"] == 2


def test_a_submenu_opens_beside_the_menu_on_a_wide_screen(driven):
    o = driven["1440"]
    assert o["beside"] is True and o["menuHiddenUnder"] is False and o["back"] == []
    assert o["foot"] == ["New agent…", "Open the hall"], "it ends with the doors to where agents are managed"
    assert len(o["agents"]) == 3
    assert "Morning Brief" in o["filtered"] and len(o["filtered"]) < 10, "typing filters the list"


def test_a_submenu_is_a_page_with_a_back_row_on_a_phone(driven):
    o = driven["390"]
    assert o["covers"] is True and o["menuHiddenUnder"] is True and o["back"] == ["‹ Agents"]
    assert o["afterBack"] == {"sub": 0, "menu": True}
    assert o["chip"] == "Morning Brief" and o["closed"] is True, "a pick summons and closes the menu"


def test_the_keyboard_walks_in_and_out(driven):
    o = driven["1440"]
    assert o["escBack"] == {"sub": 0, "focus": "overflow-agents-btn", "menuOpen": True}, \
        "Escape in a submenu goes back to its row, not out of the menu"
    assert o["down"] == "overflow-modes-btn"
    assert o["modes"][:3] == ["Plan mode", "Web search", "Shell"], "RAG joins them where it is switched on"
    assert "Plan mode" in o["modeFocus"], "→ opens it with its first row focused"


def test_a_mode_is_a_switch_that_leaves_the_menu_open(driven):
    s = driven["1440"]["shell"]
    assert s["flipped"] is True and s["open"] is True
    assert s["row"] == s["chip"], "the row shows the chip's own state"


def test_a_skill_picked_is_its_slash_command(driven):
    o = driven["1440"]
    assert "tidy-downloads" in o["skills"] and o["skillsFoot"] == ["Manage skills"]
    assert o["message"] == "/tidy-downloads " and o["closed"] is True


# ── the pure parts, under node ──────────────────────────────────────────────

def _node(tmp_path, script):
    import shutil
    js = ROOT / "static" / "js"
    shutil.copy(js / "composerMenu.js", tmp_path / "composerMenu.js")
    (tmp_path / "summon.js").write_text("export const pickerRows = (a) => a; export default {};")
    (tmp_path / "workspace.js").write_text("export default { getWorkspace: () => '' };")
    (tmp_path / "case.mjs").write_text(script)
    proc = subprocess.run([NODE, "case.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


_FAKE_DOC = """
const cls = (...c) => { const s = new Set(c); return { contains: (x) => s.has(x), toggle: (x, on) => (on ? s.add(x) : s.delete(x)), add: (x) => s.add(x) }; };
const node = (id, c, extra = {}) => ({ id, classList: cls(...c), style: { display: extra.display || '' }, hidden: false,
  getAttribute: (a) => (a === 'aria-pressed' ? extra.pressed || null : null) });
const nodes = {};
const doc = { getElementById: (id) => nodes[id] || null };
"""


def test_filtering_matches_every_word_anywhere_in_a_row(tmp_path):
    out = _node(tmp_path, """
        const m = await import('./composerMenu.js');
        const rows = [{ label: 'Morning Brief', hint: 'One page each morning' },
                      { label: 'Evening Wrap', hint: 'What got done' },
                      { label: 'Topic Watcher', hint: 'web', search: 'Topic Watcher research morning' }];
        const f = (q) => m.filterRows(rows, q).map((r) => r.label);
        console.log(JSON.stringify({ all: f(''), one: f('MORNING page'), search: f('research'), none: f('morning zebra') }));
    """)
    assert out == {"all": ["Morning Brief", "Evening Wrap", "Topic Watcher"], "one": ["Morning Brief"],
                   "search": ["Topic Watcher"], "none": []}


def test_the_modes_row_lights_when_an_on_mode_is_out_of_sight(tmp_path):
    out = _node(tmp_path, _FAKE_DOC + """
        const m = await import('./composerMenu.js');
        nodes['overflow-modes-btn'] = node('overflow-modes-btn', []);
        nodes['plan-toggle-btn'] = node('plan-toggle-btn', [], { pressed: 'true' });
        nodes['web-toggle-btn'] = node('web-toggle-btn', ['active']);
        nodes['bash-toggle-btn'] = node('bash-toggle-btn', [], { display: 'none' });
        nodes['overflow-rag-btn'] = node('overflow-rag-btn', ['composer-menu-folded']);
        const rows = m.modeRows(doc).map((r) => [r.label, r.on]);
        const quiet = m.syncModesDot(doc) || nodes['overflow-modes-btn'].classList.contains('active');
        nodes['overflow-rag-btn'].classList.add('active');
        const changed = m.syncModesDot(doc);
        const lit = nodes['overflow-modes-btn'].classList.contains('active');
        nodes['overflow-rag-btn'] = node('overflow-rag-btn', ['composer-menu-folded']);
        nodes['web-toggle-btn'].classList.add('toolbar-collapsed');
        m.syncModesDot(doc);
        console.log(JSON.stringify({ rows, quiet, changed, lit, collapsed: nodes['overflow-modes-btn'].classList.contains('active') }));
    """)
    assert out["rows"] == [["Plan mode", True], ["Web search", True], ["RAG", False]], \
        "a mode whose chip is hidden is not offered; aria-pressed counts as on"
    assert out["quiet"] is False, "on modes the bar shows do not light the row"
    assert out["changed"] is True and out["lit"] is True, "RAG on, folded into the menu"
    assert out["collapsed"] is True, "a chip collapsed for room that is on"
