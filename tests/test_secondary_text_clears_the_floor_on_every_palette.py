# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1408` — secondary text keeps its de-emphasis and clears 4.5:1 on every palette.

191 `color:` declarations in `static/style.css` painted text as
`color-mix(in srgb, var(--fg) N%, transparent)`: mixing toward `transparent`
lets the background through, so no alpha under 82% cleared 4.5:1 on every
shipped palette — 60%, the commonest, measured 2.33:1 at worst. Among them:
the shared empty state every list now draws (`ui.renderEmptyState`'s title,
message and reason), the chat's timestamps and meta line, the Brain's memory
metadata, Settings' row descriptions (`.admin-toggle-sub`), every input
placeholder in the sheet.

185 of them are on a ladder now — `color-mix(in oklab, var(--fg) N%,
var(--fg-muted))` — which keeps their order (a lower N is still the quieter
line) and puts every rung between `--fg-muted` and `--fg`, both pinned over
the floor. In OKLab, not sRGB: interpolating `retrowave`'s red `--fg` in sRGB
dipped the middle rungs to 4.44:1. The six left are decoration, recorded in
`check-contrast.py` with why and measured every run; the `opacity:` form of the
same arithmetic is counted and ratcheted there too.

Driven (`Law 20`): the checker's own functions over the real stylesheet and the
real palettes; and the OKLab arithmetic they measure with is checked against
what Chromium computes for the same `color-mix()`, so the measurement is of the
colour a person sees, not of a model of it.
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _checker():
    spec = importlib.util.spec_from_file_location(
        "_contrast_for_b1408_ladder", ROOT / ".pantheon" / "check-contrast.py")
    module = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = ["check-contrast", "--imported-by-test"]
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    finally:
        sys.argv = argv
    return module


@pytest.fixture(scope="module")
def cc():
    return _checker()


def test_every_rung_the_sheet_uses_clears_the_floor_on_every_palette(cc):
    rungs, failures = cc._ladder_failures()
    assert len(rungs) >= 20, f"the ladder has {len(rungs)} rungs; the sweep did not land"
    assert failures == [], failures


def test_the_ladder_keeps_its_order(cc):
    """Compressed, not flattened: on every palette a lower N is never further
    from the background than a higher one (the de-emphasis survives)."""
    rungs, _ = cc._ladder_failures()
    for name, palette in cc.themes().items():
        ratios = [cc.contrast(cc.ladder_rung(palette, n), palette["panel"]) for n in rungs]
        for (lo, a), (hi, b) in zip(zip(rungs, ratios), zip(rungs[1:], ratios[1:])):
            assert a <= b + 0.05, f"{name}: the {lo:g}% rung reads louder than the {hi:g}% one"


def test_what_is_left_toward_transparent_is_recorded_decoration(cc):
    """The row's `Verify:` — no `color:` mixes toward `transparent` under 82%,
    or each one is recorded as decoration (its measurement printed by the
    checker every run)."""
    sites = cc._css_transparent_text_sites()
    assert len(sites) == cc.BASELINE_TRANSPARENT_TEXT == len(cc.DECORATION_TRANSPARENT_TEXT)
    assert {sel for sel, _ in sites} == set(cc.DECORATION_TRANSPARENT_TEXT)


def test_the_text_people_read_most_is_on_the_ladder():
    """The worst-read surfaces, by name: the shared empty state, the chat's
    timestamps, Settings' descriptions, the Brain's metadata."""
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    for selector in (".empty-state-title", ".empty-state-message", ".empty-state-reason",
                     ".msg .timestamp", ".admin-toggle-sub", ".memory-desc", ".chat-meta"):
        rule = css[css.index(selector + " {"):]
        rule = rule[:rule.index("}")]
        color = re.search(r"(?:^|[;{\s])color\s*:\s*([^;]+);", rule)
        assert color and "var(--fg-muted)" in color.group(1) and "transparent" not in color.group(1), (
            selector, color and color.group(1))
        assert not re.search(r"(?:^|[;{\s])opacity\s*:\s*0?\.\d", rule), f"{selector} dims itself again"


def test_the_opacity_form_is_counted_and_cannot_grow(cc):
    count = cc._css_opacity_dimming()
    assert count <= cc.BASELINE_OPACITY_DIMMING, (count, cc.BASELINE_OPACITY_DIMMING)
    assert count == cc.BASELINE_OPACITY_DIMMING, "the ratchet has slack; lower it to the count"


# ── the arithmetic, against the browser ─────────────────────────────────────

_PROBE = r"""
const { chromium } = require('playwright');
const cases = JSON.parse(process.argv[2]);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setContent('<div id="x">x</div>');
  const out = await page.evaluate((cs) => cs.map(([fg, muted, pct]) => {
    const el = document.getElementById('x');
    el.style.color = `color-mix(in oklab, ${fg} ${pct}%, ${muted})`;
    // Resolve to sRGB through a canvas, the colour that is painted.
    const c = document.createElement('canvas'); c.width = c.height = 1;
    const ctx = c.getContext('2d'); ctx.fillStyle = getComputedStyle(el).color; ctx.fillRect(0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return [r, g, b];
  }), cases);
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def test_the_measured_rung_is_the_colour_chromium_paints(cc, tmp_path):
    from test_the_command_palette_in_a_browser import NODE, _SKIP
    if NODE is None:
        pytest.skip(_SKIP or "no browser")
    cases, expected = [], []
    for name in ("retrowave", "light", "terminal", "cute", "ume"):
        palette = cc.themes()[name]
        for pct in (30, 55, 75):
            cases.append([palette["fg"], cc.fg_muted(palette), pct])
            expected.append(cc.ladder_rung(palette, pct))
    script = tmp_path / "probe.cjs"
    script.write_text(_PROBE, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), json.dumps(cases)], capture_output=True,
                          text=True, timeout=120, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-2000:]
    painted = json.loads(proc.stdout.strip().splitlines()[-1])
    for (fg, muted, pct), want, got in zip(cases, expected, painted):
        w = [int(want[i:i + 2], 16) for i in (1, 3, 5)]
        assert max(abs(a - b) for a, b in zip(w, got)) <= 2, (fg, muted, pct, want, got)


def test_no_inline_style_mixes_text_toward_transparent(cc):
    """The same defect in a `style=` — 36 of them, in Settings' status lines,
    Compare and the email library, moved onto the ladder; the two pages that
    do not load `style.css` are named, not skipped silently."""
    assert cc._inline_transparent_text() == []
    assert cc._INLINE_SCAN_EXEMPT == {"static/login.html", "static/whirlpool-variants.html"}
