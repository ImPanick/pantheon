# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1575` — the sign-in page's secondary text reads on every palette.

`static/login.html` links no stylesheet (it mirrors the palette by hand so its
first paint owes nothing to `style.css`), so it had no `--fg-muted` and painted
its secondary text by mixing `--fg` toward `transparent` — the labels at 65%,
the setup note at 60%, the sign-up line at 50%, the eye button at 40%, the
remember-me ring at 25% — and its version at `opacity: 0.25` and its error in a
fixed `#e55`. Measured on `retrowave`: labels 2.53:1, setup note 2.33:1,
sign-up line 1.96:1; the error 3.22:1 on `light`. `.pantheon/check-contrast.py`
named the page in `_INLINE_SCAN_EXEMPT` so its scan could not see it.

Now the page declares the muted pivot as `style.css` does, its text is on
`B1408`'s ladder, and the exemption is gone.

Driven in Chromium (`Law 20`): the real page, served as the app serves it, with
each of the 23 shipped palettes (`THEMES`, read from `theme.js` by the checker)
saved as the app saves a theme, so the page's own head script applies it — the
`color-scheme` arm, `light-dark()` and the OKLab mixes are the browser's. Each
colour is composited over the surface it sits on by a canvas, so whatever
syntax the browser serialises a colour in, it is measured as painted.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]


def _checker():
    spec = importlib.util.spec_from_file_location("check_contrast", ROOT / ".pantheon" / "check-contrast.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SCRIPT = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const ROOT = process.argv[2];
const PALETTES = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const BASE = 'http://signin.test';
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
                '.woff2': 'font/woff2', '.json': 'application/json', '.svg': 'image/svg+xml',
                '.png': 'image/png' };
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1000, height: 800 } });
  await context.route('**/*', (route) => {
    const url = new URL(route.request().url());
    let file = null;
    if (url.pathname === '/login') file = path.join(ROOT, 'static', 'login.html');
    else if (url.pathname.startsWith('/static/')) file = path.join(ROOT, url.pathname);
    else if (url.pathname === '/api/version') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"version":"9.9.9"}' });
    }
    if (file && fs.existsSync(file)) {
      return route.fulfill({ status: 200, body: fs.readFileSync(file),
                             contentType: TYPES[path.extname(file)] || 'application/octet-stream' });
    }
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });
  const page = await context.newPage();
  const out = { errors: [], palettes: {} };
  page.on('pageerror', (e) => out.errors.push(String((e && e.stack) || e)));
  await page.goto(BASE + '/login', { waitUntil: 'load' });
  for (const [name, colors] of Object.entries(PALETTES)) {
    await page.evaluate(([n, c]) => localStorage.setItem('pantheon-theme',
      JSON.stringify({ name: n, colors: c })), [name, colors]);
    await page.goto(BASE + '/login', { waitUntil: 'load' });
    // The end state is the subject, not the dot's 150 ms ease (`B1552`'s note).
    await page.addStyleTag({ content: '*, *::before, *::after { transition: none !important; }' });
    out.palettes[name] = await page.evaluate(() => {
      const ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
      // A colour as painted over `under`: the browser composites it, whatever
      // syntax `getComputedStyle` serialises it in.
      const paint = (colour, under) => {
        ctx.clearRect(0, 0, 1, 1);
        ctx.globalAlpha = 1; ctx.fillStyle = under; ctx.fillRect(0, 0, 1, 1);
        ctx.fillStyle = colour; ctx.fillRect(0, 0, 1, 1);
        return [...ctx.getImageData(0, 0, 1, 1).data.slice(0, 3)];
      };
      const lum = (rgb) => {
        const [r, g, b] = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
      const cs = (el) => getComputedStyle(el);
      const panel = cs(document.querySelector('.card')).backgroundColor;
      const page = cs(document.body).backgroundColor;
      const field = cs(document.getElementById('password')).backgroundColor;
      const pageOpaque = paint(page, '#000');
      const panelOver = paint(panel, `rgb(${pageOpaque.join(',')})`);
      const fieldOver = paint(field, `rgb(${panelOver.join(',')})`);
      const rgb = (a) => `rgb(${a.join(',')})`;
      // Text and marks, each over the surface it sits on, at its own opacity.
      const measure = (el, prop, under) => {
        const s = cs(el);
        let alpha = 1;
        for (let n = el; n && n !== document.documentElement; n = n.parentElement) alpha *= parseFloat(cs(n).opacity);
        const fg = paint(s[prop], rgb(under));
        const mixed = fg.map((v, i) => v * alpha + under[i] * (1 - alpha));
        return Math.round(ratio(mixed, under) * 100) / 100;
      };
      const q = (sel) => document.querySelector(sel);
      return {
        scheme: cs(document.documentElement).colorScheme,
        label: measure(q('label[for="username"]'), 'color', panelOver),
        setupNote: measure(q('#setupNote'), 'color', panelOver),
        toggle: measure(q('#toggleText'), 'color', panelOver),
        error: measure(q('#error'), 'color', panelOver),
        version: measure(q('#version-label'), 'color', pageOpaque),
        eye: measure(q('#pwToggle'), 'color', fieldOver),
        // Checked (the page's default) the switch is a filled dot; unchecked,
        // a ring. Each is the whole control.
        rememberOn: (q('#remember').checked = true, measure(q('.remember-dot'), 'backgroundColor', fieldOver)),
        rememberOff: (q('#remember').checked = false, measure(q('.remember-dot'), 'borderTopColor', fieldOver)),
      };
    });
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("signin")
    palettes = tmp / "palettes.json"
    palettes.write_text(json.dumps(_checker().themes()))
    script = tmp / "measure.js"
    script.write_text(_SCRIPT)
    proc = subprocess.run([NODE, str(script), str(ROOT), str(palettes)], capture_output=True,
                          text=True, timeout=240, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


TEXT = ("label", "setupNote", "toggle", "error", "version")


def test_the_sign_in_pages_text_clears_4_5_to_1_on_every_palette(measured):
    """The row's `Verify:` — its labels clear 4.5:1 on every palette."""
    assert len(measured["palettes"]) == 23, sorted(measured["palettes"])
    misses = [f"{name}: {what} {row[what]}:1" for name, row in sorted(measured["palettes"].items())
              for what in TEXT if row[what] < 4.5]
    assert not misses, misses


def test_its_controls_clear_3_to_1_on_every_palette(measured):
    """The eye button's icon and the remember-me switch's ring are each the
    only thing that draws their control (WCAG 1.4.11's 3:1)."""
    misses = [f"{name}: {what} {row[what]}:1" for name, row in sorted(measured["palettes"].items())
              for what in ("eye", "rememberOn", "rememberOff") if row[what] < 3.0]
    assert not misses, misses


def test_a_light_palette_gets_the_light_arm(measured):
    """`light-dark()` reads `color-scheme`, which the head script sets from
    the saved background — the pivot is darker than the text on a light page."""
    assert measured["palettes"]["light"]["scheme"] == "light"
    assert measured["palettes"]["dark"]["scheme"] == "dark"


def test_the_checker_no_longer_exempts_the_page_and_holds_its_copy_equal():
    checker = _checker()
    assert "static/login.html" not in checker._INLINE_SCAN_EXEMPT
    assert "static/login.html" in checker.LADDER_PAGES
    assert checker._mirror_drift() == []
    assert checker._inline_transparent_text() == []
