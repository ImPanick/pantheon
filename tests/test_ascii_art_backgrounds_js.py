# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-16` — ASCII art as a ninth background pattern: per theme, subtle, still under reduced motion.

The owner, unprompted, twice (`D-2026-08-26-03`): *"possibly even ASCII art
subtle in the background for the entire platform depending on the theme
selected."* Built on the machinery the eight patterns use (`FORBIDDEN.md` §
The theme system — extended, not replaced): `bg-pattern-ascii` in
`_BG_CLASSES`, `ascii: _initAscii` in `_CANVAS_PATTERNS`, a `_bgCanvas`, and
`--bg-effect-color` / `--bg-effect-intensity` / `--bg-effect-size`. No
existing theme's default pattern moved; *ASCII art* is in the pattern picker
and the agent's `create_theme` vocabulary.

**Reduced motion stops the animation without hiding the art.** Every other
canvas pattern starts nothing under `prefers-reduced-motion` (`P1-12`), which
for motion is right and for art would be the art gone. ASCII art is in
`_STILL_FRAME_PATTERNS`: it draws one frame and requests no animation frame.

Driven (`Law 20`): the real `theme.js` under node, over a canvas context that
records what is drawn; and the row's `Verify:` in Chromium against the real
app — the pattern renders behind the app at the configured intensity, moves,
and under emulated reduced motion is drawn and does not move.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.helpers.motion_stub import motion_stub
from test_background_animators_degrade import _SHIM as _DEGRADE_SHIM, _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox  # noqa: E402
from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402

ROOT = Path(__file__).resolve().parent.parent
_THEME = ROOT / "static" / "js" / "theme.js"
_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The degrade suite's DOM, with a context that records what it is asked to
# draw, a `requestAnimationFrame` that counts, and the effect tokens readable.
_SHIM = _DEGRADE_SHIM.replace(
    "export const canvasBehaviour = { mode: 'ok' };",
    """export const canvasBehaviour = { mode: 'ok' };
export const drawn = { text: [], fonts: [], fills: [], frames: 0 };
export const tokens = { '--bg-effect-color': '#123456', '--bg-effect-size': '1', '--fg': '#ffffff' };""",
).replace(
    "      return fake();\n    };",
    """      if (canvasBehaviour.mode === 'record') {
        return new Proxy({}, {
          get(_t, prop) {
            if (prop === 'fillText') return (t) => { drawn.text.push(String(t)); };
            return () => {};
          },
          set(_t, prop, value) {
            if (prop === 'font') drawn.fonts.push(String(value));
            if (prop === 'fillStyle') drawn.fills.push(String(value));
            return true;
          },
        });
      }
      return fake();
    };""",
).replace(
    "globalThis.requestAnimationFrame = () => 0;",
    "globalThis.requestAnimationFrame = () => { drawn.frames += 1; return 0; };",
).replace(
    "globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });",
    "globalThis.getComputedStyle = () => ({ getPropertyValue: (k) => tokens[k] || '' });\n"
    "globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });",
)


def _sandbox(tmp_path_factory, reduced: bool):
    stubs = dict(_STUBS)
    stubs["motion.js"] = motion_stub(reduced=reduced)
    return _make_sandbox(tmp_path_factory.mktemp("ascii-still" if reduced else "ascii"),
                         _THEME, _SHIM, stubs)


@pytest.fixture(scope="module")
def moving(tmp_path_factory):
    return _sandbox(tmp_path_factory, reduced=False)


@pytest.fixture(scope="module")
def still(tmp_path_factory):
    return _sandbox(tmp_path_factory, reduced=True)


def _run(sandbox: Path, script: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(textwrap.dedent("""
        import { bodyState, canvasBehaviour, drawn, tokens, warnings } from './shim.js';
        const tm = await import('./theme.js');
        canvasBehaviour.mode = 'record';
    """) + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


_DRAW_FOR = """
const drawFor = (theme) => {
  drawn.text.length = 0; drawn.fonts.length = 0; drawn.fills.length = 0; drawn.frames = 0;
  tm.save(theme, tm.THEMES[theme]);
  tm.applyBgPattern('ascii');
  return { ...bodyState(), text: [...drawn.text], fonts: [...drawn.fonts],
           fills: [...drawn.fills], frames: drawn.frames,
           art: tm.asciiArtFor(theme).flat() };
};
"""


@_node
def test_the_art_depends_on_the_theme_showing(moving):
    out = _run(moving, _DRAW_FOR + """
        console.log(JSON.stringify({ terminal: drawFor('terminal'), ume: drawFor('ume'),
                                     dark: drawFor('dark') }));
    """)
    for theme in ("terminal", "ume", "dark"):
        case = out[theme]
        assert case["canvases"] == ["ascii-canvas"], case
        assert "bg-pattern-ascii" in case["classes"], case
        assert case["text"], f"{theme}: nothing was drawn"
        assert set(case["text"]) <= set(case["art"]), (theme, set(case["text"]) - set(case["art"]))
    assert set(out["terminal"]["art"]).isdisjoint(out["ume"]["art"]), \
        "terminal and ume were given the same art"


@_node
def test_it_reads_the_effect_colour_and_size(moving):
    out = _run(moving, _DRAW_FOR + """
        const one = drawFor('terminal');
        tokens['--bg-effect-size'] = '2';
        tokens['--bg-effect-color'] = '#abcdef';
        const two = drawFor('terminal');
        console.log(JSON.stringify({ one, two }));
    """)
    assert "#123456" in out["one"]["fills"] and "#abcdef" in out["two"]["fills"], out
    assert out["one"]["fonts"][0].startswith("12px"), out["one"]["fonts"]
    assert out["two"]["fonts"][0].startswith("24px"), out["two"]["fonts"]
    assert out["one"]["frames"] >= 1, "the moving pattern asked for no animation frame"


@_node
def test_reduced_motion_draws_the_art_once_and_does_not_animate(still):
    """The row's `Verify:`, second half, in the module: the art is drawn and no
    animation frame is requested — and the editor's colour change repaints
    the still frame rather than leaving the old ink."""
    out = _run(still, _DRAW_FOR + """
        const once = drawFor('ume');
        drawn.text.length = 0; drawn.fills.length = 0;
        tm.applyBgEffectColor('#00ff00');
        const repainted = { text: drawn.text.length, fills: [...drawn.fills], frames: drawn.frames };
        tm.applyBgPattern('rain');
        const rain = bodyState();
        console.log(JSON.stringify({ once, repainted, rain, warnings }));
    """)
    once = out["once"]
    assert once["canvases"] == ["ascii-canvas"], "reduced motion hid the art"
    assert once["text"], "the still frame drew nothing"
    assert once["frames"] == 0, "an animation frame was requested under reduced motion"
    assert out["repainted"]["text"] > 0 and out["repainted"]["frames"] == 0, out["repainted"]
    # The motion patterns are still stopped, as `P1-12` has them.
    assert out["rain"]["canvases"] == [], out["rain"]


# ── the row's `Verify:`, in a browser against the real app ───────────────────

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const creds = { username: 'ascii', password: 'ascii-pass-123' };
  const setup = await browser.newContext();
  await setup.request.post(BASE + '/api/auth/setup', { data: creds });
  await setup.close();
  for (const motion of ['no-preference', 'reduce']) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 },
                                               reducedMotion: motion, serviceWorkers: 'block' });
    await context.addInitScript(() => {
      try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => out.errors.push(motion + ': ' + String((e && e.message) || e)));
    await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
    await page.goto(BASE + '/', { waitUntil: 'load' });
    await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 120000 });
    await page.evaluate(() => {
      const tm = window.themeModule;
      tm.save('terminal', tm.THEMES.terminal);
      tm.applyBgEffectIntensity(0.4);
      tm.applyBgPattern('ascii');
    });
    await page.waitForSelector('#ascii-canvas', { state: 'attached', timeout: 10000 });
    await page.waitForTimeout(400);
    const look = () => page.evaluate(() => {
      const c = document.getElementById('ascii-canvas');
      const px = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let inked = 0, sum = 0;
      for (let i = 3; i < px.length; i += 4) { if (px[i]) { inked += 1; sum = (sum + px[i] * (i % 9973)) % 1000000007; } }
      const cs = getComputedStyle(c);
      return { inked, sum, opacity: cs.opacity, position: cs.position, z: cs.zIndex,
               pointer: cs.pointerEvents, first: document.body.firstElementChild === c,
               cls: document.body.classList.contains('bg-pattern-ascii') };
    });
    const a = await look();
    await page.waitForTimeout(700);
    const b = await look();
    out[motion] = { a, b };
    await context.close();
  }
  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def file_database(tmp_path_factory):
    import os
    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "sqlite:///" + str(tmp_path_factory.mktemp("ascii-db") / "app.db")
    yield
    if before is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = before


@pytest.fixture(scope="module")
def browsed(file_database, app_url, tmp_path_factory):  # noqa: F811
    if NODE is None:
        pytest.skip(_SKIP or "no browser")
    script = tmp_path_factory.mktemp("ascii-pw") / "ascii.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url], capture_output=True, text=True,
                          timeout=600, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_pattern_renders_behind_the_app_at_the_configured_intensity_and_moves(browsed):
    assert browsed["errors"] == [], browsed["errors"]
    a, b = browsed["no-preference"]["a"], browsed["no-preference"]["b"]
    assert a["cls"] and a["first"], a
    assert a["position"] == "fixed" and a["z"] == "0" and a["pointer"] == "none", a
    assert a["opacity"] == "0.4", a
    assert a["inked"] > 0, "nothing was painted"
    assert a["sum"] != b["sum"], "the moving pattern did not move"


def test_reduced_motion_keeps_the_art_and_stops_it(browsed):
    a, b = browsed["reduce"]["a"], browsed["reduce"]["b"]
    assert a["cls"] and a["opacity"] == "0.4", a
    assert a["inked"] > 0, "reduced motion hid the art"
    assert (a["inked"], a["sum"]) == (b["inked"], b["sum"]), "it moved under reduced motion"
