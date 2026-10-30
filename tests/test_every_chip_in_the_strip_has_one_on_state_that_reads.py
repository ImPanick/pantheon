# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1552` — every chip in the composer strip has one on-state, and its label
reads on its own tint on every palette.

`B781` joined the plan chip's on-state to the indicators' and left two:
`.tool-indicator.active` / `.plan-mode-btn.active` painted the theme's red on a
12% red tint, and Web and Shell kept `.input-icon-btn.active`'s neutral `--fg`
on a 9% `--fg` tint. Measured here before the fix, on the composer and the
composer in plan mode: the red label missed 4.5:1 on eleven palettes (`paper`
1.95, `cute` 2.14, `light` 2.52 …) and the neutral one on two (`retrowave`
3.85, `cute` 3.90).

Now one rule paints every `.tool-chip.active`, and its label is
`--chip-on-fg` — the palette's red, moved by `applyColors` only as far as 4.5:1
on the tint needs, toward black or white so its hue holds. The palettes that
cleared keep their red exactly; which ones moved is pinned, so a change in that
set is a decision someone sees.

Driven in Chromium (`Law 20`): the real app, every shipped palette applied by
the real `applyColors()`, every chip in the strip switched on, and the
browser's own computed colours composited over the composer's own computed
background — the cascade is the browser's, not a reading of the sheet.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

# A workspace chip is `.active` while a workspace is set, and is drawn as a
# place shown by name, not as a switch that is on (its own rule, by id).
NOT_A_SWITCH = {"workspace-indicator-btn"}

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  const out = { errors: [] };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  const creds = { username: 'chips', password: 'chips-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  await page.waitForTimeout(600);
  // A chip eases its colour in over 150 ms (`.input-icon-btn`'s transition),
  // so a style read straight after `.active` is the START of the change — the
  // previous palette's colour, at half opacity. The end state is the subject.
  await page.addStyleTag({ content: '*, *::before, *::after { transition: none !important; }' });
  out.palettes = await page.evaluate(async () => {
    const tm = await import('/static/js/theme.js');
    // `rgb()`, `rgba()` and `color(srgb …)`, as Chromium serialises them.
    const parse = (s) => {
      let m = s.match(/^rgba?\(([^)]+)\)$/);
      if (m) {
        const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
        return { c: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 };
      }
      m = s.match(/^color\(srgb ([^)]+)\)$/);
      if (m) {
        const p = m[1].split(/[\s/]+/).filter(Boolean).map(Number);
        return { c: p.slice(0, 3).map((v) => v * 255), a: p.length > 3 ? p[3] : 1 };
      }
      // Fully transparent, in whatever space Chromium kept it (`oklab(0 0 0 / 0)`).
      if (/\/\s*0\)$/.test(s)) return { c: [0, 0, 0], a: 0 };
      // The cockpit's glass mixes in OKLab, and Chromium keeps the space:
      // `oklab(L a b / α)`, converted to sRGB by Ottosson's matrices.
      m = s.match(/^oklab\(([^)]+)\)$/);
      if (m) {
        const p = m[1].split(/[\s/]+/).filter(Boolean).map(Number);
        const [L, A, B] = p;
        const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
        const mm = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
        const q = (L - 0.0894841775 * A - 1.2914855480 * B) ** 3;
        const lin = [4.0767416621 * l - 3.3077115913 * mm + 0.2309699292 * q,
                     -1.2684380046 * l + 2.6097574011 * mm - 0.3413193965 * q,
                     -0.0041960863 * l - 0.7034186147 * mm + 1.7076147010 * q];
        const enc = (v) => { v = Math.min(1, Math.max(0, v)); return 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055); };
        return { c: lin.map(enc), a: p.length > 3 ? p[3] : 1 };
      }
      throw new Error('cannot read colour ' + s);
    };
    const over = (top, under) => top.c.map((v, i) => v * top.a + under[i] * (1 - top.a));
    const lum = (rgb) => {
      const [r, g, b] = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const bar = document.querySelector('.chat-input-bar');
    // `B1706`: the bottom row, not only its left strip — the approval-mode
    // chip moved from the strip to the row's right and is the same chip
    // (`.tool-chip`, its on-state Auto), so it is measured where it is.
    // The cockpit (2026-10-30) keeps Plan, Web and Shell in the row and moves
    // the indicator chips to the loadout under the text box: the same eleven.
    const chips = [...document.querySelectorAll('.chat-input-bottom .tool-chip, .ck-loadout .tool-chip')];
    const res = {};
    for (const name of Object.keys(tm.THEMES)) {
      tm.applyColors(tm.THEMES[name]);
      const root = getComputedStyle(document.documentElement);
      const row = { red: root.getPropertyValue('--red').trim(),
                    chipOn: root.getPropertyValue('--chip-on-fg').trim(), chips: {} };
      for (const plan of [false, true]) {
        document.body.classList.toggle('plan-mode-active', plan);
        // The cockpit's composer is glass: its tint is laid over the page's
        // own `--bg`, which is what shows through it.
        const page = parse(getComputedStyle(document.documentElement).backgroundColor);
        const glass = parse(getComputedStyle(bar).backgroundColor);
        const ground = { c: over(glass, page.c), a: 1 };
        for (const chip of chips) {
          const had = chip.classList.contains('active');
          chip.classList.add('active');
          const cs = getComputedStyle(chip);
          const ink = parse(cs.color), tint = parse(cs.backgroundColor);
          const under = over(tint, ground.c);
          const r = ratio(over(ink, under), under);
          const prev = row.chips[chip.id];
          row.chips[chip.id] = { color: cs.color, background: cs.backgroundColor, opacity: cs.opacity,
                                 ratio: prev ? Math.min(prev.ratio, r) : r };
          if (!had) chip.classList.remove('active');
        }
      }
      document.body.classList.remove('plan-mode-active');
      const badge = document.getElementById('chat-auto-approve-badge');
      row.badge = badge ? getComputedStyle(badge).color : null;
      res[name] = row;
    }
    return res;
  });
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(app_url, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("chip-on")
    script = d / "chips.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _switches(row):
    return {cid: c for cid, c in row["chips"].items() if cid not in NOT_A_SWITCH}


def test_every_palette_and_every_chip_was_measured(measured):
    assert measured["errors"] == []
    assert len(measured["palettes"]) == 20, sorted(measured["palettes"])  # three retired: theme.js `RETIRED_THEMES`
    for row in measured["palettes"].values():
        assert {"plan-toggle-btn", "web-toggle-btn", "bash-toggle-btn"} <= set(row["chips"]), sorted(row["chips"])
        # Eleven still after `B1706`: ten in the strip and the approval-mode
        # chip, which left the strip for the row's right and is measured there.
        assert "approval-mode-btn" in row["chips"], sorted(row["chips"])
        assert len(_switches(row)) == 11, sorted(row["chips"])


def test_every_chip_wears_one_on_state(measured):
    """The row's first half: Web and Shell are the same on-state as the rest,
    on every palette — one colour, one tint, full opacity.

    The cockpit gives Auto approval its own lamp: the warning colour, because
    on means "steps run without asking" (`static/cockpit.css`). It is the one
    chip outside the shared look, and the header badge says its colour."""
    for name, row in measured["palettes"].items():
        switches = _switches(row)
        auto = switches.pop("approval-mode-btn")
        looks = {(c["color"], c["background"], c["opacity"]) for c in switches.values()}
        assert len(looks) == 1, (name, sorted(looks))
        # And the Auto-approve badge says the chip's colour (`D-2026-10-09-01` §2).
        assert row["badge"] == auto["color"], (name, row["badge"], auto)


def test_the_on_label_clears_aa_on_its_tint_on_every_palette(measured):
    """The row's `Verify:`, measured over the composer and the composer in plan
    mode, worst of the two."""
    under = {(name, cid): round(c["ratio"], 2)
             for name, row in measured["palettes"].items()
             for cid, c in _switches(row).items() if c["ratio"] < 4.5}
    assert not under, under


def test_only_the_palettes_that_missed_moved(measured):
    """`--chip-on-fg` is the palette's red wherever the red already cleared:
    eleven keep it exactly, and these twelve moved the least that clears —
    pinned, so a palette joining or leaving the set is seen.

    Read from the token `applyColors` writes: the cockpit's switches label
    their on-state in the text colour, so no chip paints it any more. Ten now,
    `retrowave` and `cyberpunk` retired (theme.js `RETIRED_THEMES`)."""
    def rgb(s):
        return s.replace(" ", "")
    moved = set()
    for name, row in measured["palettes"].items():
        red = row["red"].lstrip("#")
        want = f"rgb({int(red[0:2], 16)},{int(red[2:4], 16)},{int(red[4:6], 16)})"
        if rgb(row["chipOn"]).lower() not in (want, "#" + red.lower()):
            moved.add(name)
    assert moved == {"paper", "cute", "light", "claude", "lavender", "organs", "gpt",
                     "dark", "midnight", "codehost"}, sorted(moved)
