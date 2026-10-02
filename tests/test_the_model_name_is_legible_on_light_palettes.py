# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1072` — the model's name above a reply is legible on the light palettes.

`static/js/chatRenderer.js:modelColor()` coloured the role line
`hsl(hue, 55%, 65%)` from a hash of the model name on every palette — a
lightness chosen for dark backgrounds — and `applyModelColor` set it inline.
Measured on the seeded demo before this row: `scripted-demo` `rgb(117, 212,
215)` on `light`'s bubble `rgb(250, 246, 240)`, **1.60:1**; over 410 names the
worst was a yellow at **1.41:1** on `light`, and no light palette did better
than 1.73:1. The sixteen palettes must stay legible (`D-2026-09-14-03`).

Now a `light-dark()` pair: the dark arm is the old colour exactly (every dark
palette unchanged), the light arm the same hue and saturation at the lightness
whose relative luminance is `MODEL_NAME_LIGHT_Y`.

Two halves:

  * the shipped functions, cut out of `chatRenderer.js` and run under node
    against the shipped `THEMES` table cut out of `theme.js`; the colour
    arithmetic checking them is Python's own (`colorsys`), not a copy of the
    module's;
  * the real app in headless Chromium: each of the sixteen palettes applied by
    the page's own `theme.js:applyColors`, a reply's role line coloured by the
    page's own `applyModelColor` for sixty names, and the contrast read from
    what the browser resolved against what the bubble paints.
"""

import colorsys
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP, app_url  # noqa: F401,E402
from tests.helpers.js_source import js_binding, js_definition

ROOT = Path(__file__).resolve().parents[1]
RENDERER = (ROOT / "static" / "js" / "chatRenderer.js").read_text(encoding="utf-8")
THEME_JS = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")

_needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _decl(src: str, head: str) -> str:
    """The declaration starting at `head`, without its `export`."""
    i = src.index(head)
    return js_definition(src, i).replace("export ", "", 1)


def _luminance(rgb):
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (v / 255 for v in rgb)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hsl(text):
    """`hsl(h, s%, l%)` → 8-bit sRGB, the way a browser stores it."""
    h, s, l = (float(x) for x in re.fullmatch(r"hsl\(([\d.]+), ([\d.]+)%, ([\d.]+)%\)", text.strip()).groups())
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return tuple(round(c * 255) for c in (r, g, b))


def _arms(value):
    m = re.fullmatch(r"light-dark\((hsl\([^)]*\)), (hsl\([^)]*\))\)", value)
    assert m, f"not a light-dark pair: {value!r}"
    return m.group(1), m.group(2)


def _hue_of(name):
    # The module's hash, restated in Python as the oracle for which hue a name gets.
    # JavaScript's `| 0` keeps 32 signed bits; `((h % 360) + 360) % 360` is
    # the mathematical modulus, which is Python's `%`.
    h = 0
    for ch in name.lower():
        h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
    h = h - (1 << 32) if h >= (1 << 31) else h
    return h % 360


_NAMES = ["scripted-demo", "gpt-4o", "claude-sonnet-4", "llama3.1:8b", "qwen2.5-coder:32b", "mistral-large",
          "gemma2:9b", "deepseek-r1", "phi-4", "o3-mini"] + [f"model-{i}" for i in range(50)]


@pytest.fixture(scope="module")
def shipped():
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    source = "\n".join([
        _decl(RENDERER, "export const MODEL_NAME_LIGHT_Y"),
        _decl(RENDERER, "function _hslLuminance("),
        _decl(RENDERER, "export function modelColorForHue("),
        _decl(RENDERER, "export function modelColor("),
        js_binding(THEME_JS, "THEMES").replace("export ", "", 1),
        "console.log(JSON.stringify({",
        "  hues: Array.from({ length: 360 }, (_, h) => modelColorForHue(h)),",
        f"  names: Object.fromEntries({json.dumps(_NAMES)}.map((n) => [n, modelColor(n)])),",
        "  empty: modelColor(''),",
        "  themes: THEMES,",
        "}));",
    ])
    proc = subprocess.run(["node", "--input-type=module"], input=source, capture_output=True, text=True,
                          timeout=30, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _light_palettes(themes):
    # `theme.js:_isLightBackground`'s rule: the background's luminance over 0.5.
    return {n: t for n, t in themes.items() if _luminance(_hex(t["bg"])) > 0.5}


def test_the_sixteen_palettes_are_all_here_and_four_are_light(shipped):
    assert len(shipped["themes"]) == 16
    assert set(_light_palettes(shipped["themes"])) == {"light", "paper", "lavender", "cute"}


def test_every_hue_reads_at_least_4_5_to_1_on_every_light_palettes_bubble(shipped):
    # The bubble is `var(--ai-bubble-bg, var(--panel))`; a built-in palette sets
    # no `--ai-bubble-bg`, so it is the panel (measured in Chromium below).
    worst = None
    for name, theme in _light_palettes(shipped["themes"]).items():
        bubble = _hex(theme["panel"])
        for hue, value in enumerate(shipped["hues"]):
            r = _ratio(_hsl(_arms(value)[0]), bubble)
            if worst is None or r < worst[0]:
                worst = (r, name, hue, value)
    assert worst[0] >= 4.5, f"{worst[1]}: hue {worst[2]} reads {worst[0]:.2f}:1 ({worst[3]})"


def test_the_light_arm_keeps_the_names_hue(shipped):
    for hue, value in enumerate(shipped["hues"]):
        light, _ = _arms(value)
        assert light.startswith(f"hsl({hue}, 55%, "), value


def test_every_dark_palette_keeps_the_colour_it_had(shipped):
    # The dark arm is the old `hsl(hue, 55%, 65%)` to the character.
    for hue, value in enumerate(shipped["hues"]):
        assert _arms(value)[1] == f"hsl({hue}, 55%, 65%)"


def test_a_name_gets_its_hues_pair_and_no_name_gets_none(shipped):
    for name, value in shipped["names"].items():
        assert value == shipped["hues"][_hue_of(name)], name
    assert shipped["empty"] is None


# ── the real app ───────────────────────────────────────────────────────────

_SCRIPT = r"""
const { chromium } = require('playwright');
const BASE = process.argv[2];
const NAMES = JSON.parse(process.argv[3]);
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1400, height: 860 }, serviceWorkers: 'block' });
  await context.addInitScript(() => {
    try { localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false })); } catch (_) {}
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String((e && e.message) || e)));
  const creds = { username: 'legible', password: 'legible-pass-1' };
  await page.request.post(BASE + '/api/auth/setup', { data: creds });
  await page.request.post(BASE + '/api/auth/login', { data: { ...creds, remember: true } });
  await page.goto(BASE + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__pantheonAppStarted === true, null, { timeout: 90000 });
  const out = await page.evaluate(async (names) => {
    const theme = await import('/static/js/theme.js');
    const renderer = await import('/static/js/chatRenderer.js');
    const parse = (s) => { const m = String(s).match(/rgba?\(([^)]+)\)/); if (!m) return null;
      const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
    // What the bubble paints behind the line: its own and its ancestors' backgrounds, composited.
    const behind = (el) => { const layers = [];
      for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
        const c = parse(getComputedStyle(n).backgroundColor);
        if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } }
      let px = [255, 255, 255];
      for (const c of layers.reverse()) px = px.map((v, i) => c[i] * c[3] + v * (1 - c[3]));
      return px.map(Math.round); };
    const host = document.getElementById('chat-history');
    const msg = document.createElement('div'); msg.className = 'msg msg-ai';
    const role = document.createElement('div'); role.className = 'role';
    const probe = document.createElement('div'); probe.className = 'role';
    msg.append(role, probe); host.appendChild(msg);
    const result = {};
    for (const [name, colours] of Object.entries(theme.THEMES)) {
      theme.applyColors(colours);
      const rows = [];
      for (const n of names) {
        role.textContent = n; renderer.applyModelColor(role, n);
        const hue = /hsl\((\d+),/.exec(renderer.modelColor(n))[1];
        probe.style.color = `hsl(${hue}, 55%, 65%)`;   // the colour this line had before
        rows.push({ n, fg: parse(getComputedStyle(role).color), old: parse(getComputedStyle(probe).color) });
      }
      result[name] = { scheme: getComputedStyle(document.documentElement).colorScheme, bubble: behind(role), rows };
    }
    msg.remove();
    return result;
  }, NAMES);
  console.log(JSON.stringify({ palettes: out, errors }));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def painted(app_url, tmp_path_factory):  # noqa: F811
    if NODE is None:
        pytest.skip(_SKIP or "")
    script = tmp_path_factory.mktemp("legible-pw") / "legible.cjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), app_url, json.dumps(_NAMES)], capture_output=True,
                          text=True, timeout=300, cwd=str(script.parent))
    assert proc.returncode == 0, proc.stderr[-4000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def test_in_a_browser_every_light_palette_reads_at_least_4_5_to_1(painted):
    light = {n: p for n, p in painted["palettes"].items() if p["scheme"] == "light"}
    assert set(light) == {"light", "paper", "lavender", "cute"}
    for name, p in light.items():
        worst = min(p["rows"], key=lambda r: _ratio(r["fg"][:3], p["bubble"]))
        ratio = _ratio(worst["fg"][:3], p["bubble"])
        assert ratio >= 4.5, f"{name}: {worst['n']} {worst['fg']} on {p['bubble']} is {ratio:.2f}:1"


def test_in_a_browser_every_dark_palette_paints_what_it_did(painted):
    dark = {n: p for n, p in painted["palettes"].items() if p["scheme"] == "dark"}
    assert len(dark) == 12
    for name, p in dark.items():
        for row in p["rows"]:
            assert row["fg"] == row["old"], f"{name}: {row['n']} {row['fg']} was {row['old']}"


def test_in_a_browser_nothing_threw(painted):
    assert painted["errors"] == []
