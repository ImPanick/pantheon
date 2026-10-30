# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1557` — an off chip in the composer strip is a switch you can read.

`.input-icon-btn` drew every off chip as `--fg` at `opacity: 0.5`, and half the
text colour over the composer measured under 4.5:1 on all 23 palettes
(`retrowave` 1.96, `cute` 2.14, `light` 2.29 … `organs` 4.36). Off is a state
of an operable toggle — Plan, Web, Shell, Research and the rest are pressed to
turn them on — not a disabled control, and WCAG's text floor applies to it.
The workspace chip, which is drawn in that look while a folder is set, carried
the folder's name in it.

Now the off look is `--chip-off-fg` at full opacity: `applyColors` starts from
what was painted (`--fg` half-way over the composer) and moves it toward `--fg`
the least that clears 4.5:1, so off stays quieter than on and reads.

Driven in Chromium (`Law 20`), the way `B1552`'s on-state is
(`tests/test_every_chip_in_the_strip_has_one_on_state_that_reads.py`): the real
app, every shipped palette applied by the real `applyColors()`, every chip in
the strip measured switched **off**, its colour and its opacity composited over
the composer's own computed background, and in plan mode.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]

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
  const creds = { username: 'offchips', password: 'offchips-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  // The end state is the subject, not a 150 ms colour ease (`B1552`'s note).
  await page.addStyleTag({ content: '*, *::before, *::after { transition: none !important; }' });
  out.palettes = await page.evaluate(async () => {
    const tm = await import('/static/js/theme.js');
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
    // The cockpit (2026-10-30) moves the indicator chips to the loadout under
    // the text box; they are the same chips.
    const chips = [...document.querySelectorAll('.chat-input-bottom .tool-chip, .ck-loadout .tool-chip')];
    const ws = document.getElementById('workspace-indicator-btn');
    const res = {};
    for (const name of Object.keys(tm.THEMES)) {
      tm.applyColors(tm.THEMES[name]);
      const row = {};
      for (const plan of [false, true]) {
        document.body.classList.toggle('plan-mode-active', plan);
        // The cockpit's composer is glass: its tint is laid over the page's
        // own `--bg`, which is what shows through it.
        const ground = over(parse(getComputedStyle(bar).backgroundColor),
                            parse(getComputedStyle(document.documentElement).backgroundColor).c);
        for (const chip of chips) {
          const had = chip.classList.contains('active');
          // Off, except the workspace chip, whose "a folder is set" state
          // wears the off look (`#workspace-indicator-btn.active`).
          chip.classList.toggle('active', chip === ws);
          const cs = getComputedStyle(chip);
          const o = Number(cs.opacity);
          const ink = parse(cs.color), tint = parse(cs.backgroundColor);
          // Opacity fades the label and the tint into what is behind them.
          const under = over({ c: tint.c, a: tint.a * o }, ground);
          const seen = over({ c: ink.c, a: ink.a * o }, under);
          const r = ratio(seen, under);
          const prev = row[chip.id];
          row[chip.id] = { color: cs.color, opacity: o, ratio: prev ? Math.min(prev.ratio, r) : r };
          chip.classList.toggle('active', had);
        }
      }
      document.body.classList.remove('plan-mode-active');
      // The on-state, to show off is still a different look.
      const plan = document.getElementById('plan-toggle-btn');
      const had = plan.classList.contains('active');
      plan.classList.add('active');
      row.__on = getComputedStyle(plan).color;
      plan.classList.toggle('active', had);
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
    d = tmp_path_factory.mktemp("chip-off")
    script = d / "chips.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=300, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _chips(row):
    return {cid: c for cid, c in row.items() if not cid.startswith("__")}


def test_every_palette_and_every_chip_was_measured(measured):
    assert measured["errors"] == []
    assert len(measured["palettes"]) == 20, sorted(measured["palettes"])  # three retired: theme.js `RETIRED_THEMES`
    for row in measured["palettes"].values():
        assert {"plan-toggle-btn", "web-toggle-btn", "bash-toggle-btn",
                "workspace-indicator-btn",
                # `B1706`: the approval-mode chip, now at the row's right.
                "approval-mode-btn"} <= set(_chips(row)), sorted(row)


def test_the_off_label_clears_aa_on_every_palette(measured):
    """The row's `Verify:` — every strip chip's off-state label against the
    composer, and the composer in plan mode, worst of the two."""
    under = {(name, cid): round(c["ratio"], 2)
             for name, row in measured["palettes"].items()
             for cid, c in _chips(row).items() if c["ratio"] < 4.5}
    assert not under, under


def test_off_is_drawn_at_full_opacity_and_still_differs_from_on(measured):
    for name, row in measured["palettes"].items():
        for cid, c in _chips(row).items():
            assert c["opacity"] == 1, (name, cid, c)
        assert row["plan-toggle-btn"]["color"] != row["__on"], name
