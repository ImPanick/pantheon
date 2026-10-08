# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1068` — with reduced motion on, every tool window opens and the tab lives.

`P1-12`'s guard gives every element `transition-duration: 0.01ms !important`.
On a window whose `transition-property` is the initial `all` — the Workbench
and the Forge — that turns `z-index` into a transitioning property, and until a
frame is painted `getComputedStyle().zIndex` answers the value it is leaving.
`ui.js`'s auto-promote read that value inside its own MutationObserver, never
saw the window on top, and raised it again in microtasks, forever: measured on
`76d8bb5` (the `showcase` probe, a breaker at 500 writes) the Workbench and the
Forge each took **501** `z-index` writes and no frame was painted; every other
window took 1–2. `modalManager.js`'s bring-to-front read the same stale value
and pushed a window `ui.js` had just raised to 1001 back to 301.

Two halves:

  * the helper both now read through, `toolWindowZOrder.js:toolWindowZ`, driven
    under node with a window whose computed `z-index` lags its own;
  * the real app in headless Chromium with `reducedMotion: 'reduce'` (the
    `playwright` node package, booted as
    `tests/test_the_command_palette_in_a_browser.py` boots it): each tool
    window's own door in the sidebar, `z-index` writes counted with the
    `showcase` probe's breaker, and the page asked a question afterwards. The
    guard itself is checked to still apply — reduced motion stays honoured.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "static" / "js" / "toolWindowZOrder.js"

_needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _node_eval(source: str):
    proc = subprocess.run(["node", "--input-type=module"], input=source, cwd=ROOT,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip())


# A window as the browser has it mid-transition: its own style says one z (with
# or without `!important`), its computed style still says the one it is leaving.
_WINDOW = """
const cls = (...names) => ({ contains: (n) => names.includes(n) });
const win = (id, own, important, computed) => ({
  id, classList: cls(),
  style: {
    getPropertyValue: (k) => (k === 'z-index' ? own : ''),
    getPropertyPriority: (k) => (k === 'z-index' && important ? 'important' : ''),
  },
  computed: { zIndex: computed, display: 'block', visibility: 'visible' },
});
const getStyle = (el) => el.computed;
"""


@_needs_node
def test_a_window_is_read_at_the_z_it_was_given_not_the_one_it_is_leaving():
    got = _node_eval(textwrap.dedent(f"""
        import {{ toolWindowZ }} from '{HELPER.as_uri()}';
        {_WINDOW}
        console.log(JSON.stringify({{
          raised: toolWindowZ(win('wb', '1001', true, '250'), getStyle),
          notImportant: toolWindowZ(win('a', '900', false, '250'), getStyle),
          nothingOwn: toolWindowZ(win('b', '', false, '260'), getStyle),
          auto: toolWindowZ(win('c', '', false, 'auto'), getStyle),
        }}));
    """))
    # Raised inline with `!important`, which only a transition outranks: that
    # is where the window is going, whatever the computed style says yet.
    assert got["raised"] == 1001
    # A plain inline value can lose to a stylesheet `!important`, so the
    # cascade's answer stands; so does a window nobody has raised.
    assert got["notImportant"] == 250
    assert got["nothingOwn"] == 260
    assert got["auto"] is None  # NaN → JSON null: "unknown", which callers read as 0


@_needs_node
def test_the_stack_counts_another_window_at_the_z_it_was_given():
    got = _node_eval(textwrap.dedent(f"""
        import {{ topToolWindowZ, nextToolWindowZ }} from '{HELPER.as_uri()}';
        {_WINDOW}
        const forge = win('forge', '1001', true, '260');   // raised a moment ago
        const brain = win('brain', '', false, '250');
        const root = {{ querySelectorAll: () => [forge, brain] }};
        console.log(JSON.stringify({{
          top: topToolWindowZ({{ root, getStyle }}),
          next: nextToolWindowZ({{ root, getStyle, exclude: brain, current: 250 }}),
        }}));
    """))
    # Read at its computed 260, the Forge would be "below" a window raised to
    # 261 — the next window opened would land under it on the next frame.
    assert got == {"top": 1001, "next": 1002}


# ── the real app ───────────────────────────────────────────────────────────

_DOORS = ["tool-workbench-btn", "tool-cookbook-btn", "tool-library-btn", "tool-tasks-btn",
          "tool-memory-btn", "tool-notes-btn", "tool-calendar-btn", "tool-theme-btn",
          "tool-gallery-btn", "tool-compare-btn", "tool-research-btn"]

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const DOORS = JSON.parse(process.argv[3]);
// The `showcase` probe: count every z-index write; past 500 the loop is
// broken by throwing, so a regression reads as a number, not a hung run.
const SPY = `
  window.__zn = 0; window.__zv = [];
  const _sp = CSSStyleDeclaration.prototype.setProperty;
  CSSStyleDeclaration.prototype.setProperty = function (k, v, pr) {
    if (k === 'z-index') {
      window.__zn++; if (window.__zv.length < 8) window.__zv.push(Number(v));
      if (window.__zn > 500) throw new Error('z-index loop broken by the probe');
    }
    return _sp.call(this, k, v, pr);
  };`;
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const creds = { username: 'motion', password: 'motion-pass-1' };
  const out = { doors: {}, errors: [] };
  const open = async (motion) => {
    const context = await browser.newContext({ viewport: { width: 1400, height: 860 },
                                               reducedMotion: motion, serviceWorkers: 'block' });
    await context.addInitScript(SPY);
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
    await page.request.post(BASE + '/api/auth/setup', { data: creds });
    await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await page.waitForTimeout(800);
    return page;
  };
  // Asked with a deadline: a page spinning in microtasks never answers.
  const ask = (page, fn, arg) => Promise.race([
    page.evaluate(fn, arg),
    new Promise((res) => setTimeout(() => res('no answer'), 5000)),
  ]);
  const first = await open('reduce');
  out.reduceMatches = await ask(first, () => matchMedia('(prefers-reduced-motion: reduce)').matches);
  for (const door of DOORS) {
    // Each window opened first on a fresh page, the way a person meets it —
    // with others open the stack's height hides a window pushed back down.
    // A new tab for each door, the last one closed, not one tab reloaded
    // eleven times (fx5-green): Playwright starts Chromium with
    // `--disable-dev-shm-usage`, so its shared memory is files in TMPDIR, and
    // the reloaded tab held them — measured 2,409 MB in 1,215 files at the
    // peak, on a disk with 3 GB free. In the full run the disk ran out first
    // and the page never started (`waitForFunction` timed out, 26 errors).
    const reduce = await first.context().newPage();
    reduce.on('pageerror', (e) => out.errors.push(String((e && e.message) || e)));
    await reduce.goto(BASE + '/', { waitUntil: 'load' });
    await reduce.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
    await reduce.waitForTimeout(600);
    await ask(reduce, () => { window.__zn = 0; window.__zv = []; });
    await reduce.evaluate((id) => document.getElementById(id).click(), door);
    await reduce.waitForTimeout(900);
    out.doors[door] = await ask(reduce, () => {
      const open = [...document.querySelectorAll('body > .modal, body > .notes-pane-backdrop')]
        .filter((m) => !m.classList.contains('hidden') && getComputedStyle(m).display !== 'none');
      const top = open.sort((a, b) => (parseInt(getComputedStyle(b).zIndex, 10) || 0)
                                    - (parseInt(getComputedStyle(a).zIndex, 10) || 0))[0];
      return { writes: window.__zn, values: window.__zv, top: top ? top.id : null,
               transition: top ? getComputedStyle(top).transitionDuration.split(',')[0].trim() : null };
    });
    // Closed with a deadline too: a tab spinning in microtasks is the regression.
    await Promise.race([reduce.close(), new Promise((res) => setTimeout(res, 5000))]);
  }
  // The same door with motion allowed, for the baseline the row measured.
  const motion = await open('no-preference');
  await motion.evaluate(() => { window.__zn = 0; document.getElementById('tool-workbench-btn').click(); });
  await motion.waitForTimeout(900);
  out.workbenchWithMotion = await ask(motion, () => window.__zn);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def run(app_url, tmp_path_factory):  # noqa: F811
    if NODE is None:
        pytest.skip(_SKIP or "")
    script = tmp_path_factory.mktemp("motion-pw") / "motion.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, json.dumps(_DOORS)], capture_output=True,
                          text=True, timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


@pytest.mark.parametrize("door", _DOORS)
def test_with_reduced_motion_each_window_opens_with_at_most_two_z_writes(run, door):
    got = run["doors"][door]
    assert got != "no answer", f"the page stopped answering after {door}"
    assert got["writes"] <= 2, f"{door}: {got['writes']} z-index writes (the loop is back)"


@pytest.mark.parametrize("door", _DOORS)
def test_a_window_once_raised_is_never_pushed_back_down(run, door):
    # Measured with `modalManager.js` reading the computed z: the Forge went
    # 1001 → 301 → 1002, `ui.js` raising it and the bring-to-front lowering it.
    values = run["doors"][door]["values"]
    assert values == sorted(values), f"{door}: z-index went {values}"


def test_the_workbench_and_the_forge_come_to_the_front(run):
    assert run["doors"]["tool-workbench-btn"]["top"] == "workbench-modal"
    assert run["doors"]["tool-cookbook-btn"]["top"] == "cookbook-modal"


def test_reduced_motion_is_still_honoured(run):
    # The browser says so, and `P1-12`'s guard still shortens the Workbench's
    # transitions to 0.01ms — the fix reads around the guard, it does not lift it.
    assert run["reduceMatches"] is True
    assert run["doors"]["tool-workbench-btn"]["transition"] == "1e-05s"


def test_with_motion_the_workbench_takes_one_write_as_before(run):
    assert run["workbenchWithMotion"] == 1


def test_nothing_threw(run):
    assert run["errors"] == []
