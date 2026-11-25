# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Pantheon look (getpantheon.ai) is the default theme, in light and dark.

Someone who has never picked a theme gets `THEMES.pantheon`, or
`THEMES.pantheonlight` when their system is in light mode. Every theme opens in
the `hairline` finish (`static/hairline.css`), each in its own colours; glass is
a pick in Customize -> Finish. A reply's bold and italics are the reply's own
ink on every palette, not the syntax hues.

The palettes live in four places that must agree, or the first frame paints one
colour and the module repaints another a moment later:

  * `THEMES` in `static/js/theme.js`, the authority;
  * the first-paint script in `static/index.html` (base colours and advanced
    keys);
  * the first-paint script in `static/login.html` (base colours only; that page
    reads no advanced keys);
  * `DEFAULT_FINISH`, and the `'hairline'` fallback both first-paint scripts
    use for the same answer.

And `static/hairline.css`'s generated block must be what
`scripts/make-hairline-css.py` would write from today's cockpit.css, so a later
change to the glass rules can't leave the hairline finish half-converted.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEME_JS = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
LOGIN = (ROOT / "static" / "login.html").read_text(encoding="utf-8")

BASE = ("bg", "fg", "panel", "border", "red")


def _pairs(text: str) -> dict[str, str]:
    return dict(re.findall(r"([A-Za-z]+)\s*:\s*'(#[0-9a-fA-F]{3,8})'", text))


def _theme_js_preset(name: str) -> dict[str, str]:
    m = re.search(rf"^\s*{name}:\s*\{{(.*?)\}}\s*\}},", THEME_JS, re.S | re.M)
    assert m, f"THEMES.{name} not found in theme.js"
    return _pairs(m.group(1))


def _first_paint_preset(html: str, name: str) -> dict[str, str]:
    m = re.search(rf"name:\s*'{name}',\s*colors:\s*\{{(.*?)\}}\s*\}}", html, re.S)
    assert m, f"first-paint copy of {name} not found"
    return _pairs(m.group(1))


def test_both_presets_exist_with_all_base_colours():
    for name in ("pantheon", "pantheonlight"):
        p = _theme_js_preset(name)
        assert set(BASE) <= set(p), (name, p)


def test_the_presets_set_no_code_colours():
    # Syntax colours are tuned against --hl-bg; a preset codeBg would sit
    # behind them untested.
    for name in ("pantheon", "pantheonlight"):
        assert "codeBg" not in _theme_js_preset(name)
        assert "codeFg" not in _theme_js_preset(name)


def test_index_first_paint_matches_theme_js():
    for name in ("pantheon", "pantheonlight"):
        assert _first_paint_preset(INDEX, name) == _theme_js_preset(name), name


def test_login_first_paint_matches_theme_js_base_colours():
    for name in ("pantheon", "pantheonlight"):
        js = {k: v for k, v in _theme_js_preset(name).items() if k in BASE}
        assert _first_paint_preset(LOGIN, name) == js, name


def test_default_names_point_at_the_presets():
    assert re.search(r"DEFAULT_THEME\s*=\s*'pantheon'", THEME_JS)
    assert re.search(r"DEFAULT_LIGHT_THEME\s*=\s*'pantheonlight'", THEME_JS)
    assert "prefers-color-scheme: light" in THEME_JS


def test_every_theme_opens_in_hairline_and_first_paint_agrees():
    assert re.search(r"export const DEFAULT_FINISH\s*=\s*'hairline'", THEME_JS)
    m = re.search(r"export function defaultFinishFor\([^)]*\)\s*\{(.*?)\}", THEME_JS, re.S)
    assert m and m.group(1).strip() == "return DEFAULT_FINISH;", m and m.group(1)
    assert "THEME_DEFAULT_FINISH" not in THEME_JS
    assert "applyFinish(opts.finish || 'glass')" not in THEME_JS
    for html in (INDEX, LOGIN):
        assert "? t.finish\n          : 'hairline');" in html
        assert ": 'glass'" not in html


COCKPIT = (ROOT / "static" / "cockpit.css").read_text(encoding="utf-8")


def test_reply_emphasis_is_the_replys_own_ink_on_every_palette():
    """style.css gives bold, italics and bold italics the syntax hues; on gold
    those land on teal and pink. The cockpit (every page carries it) puts them
    back in the reply's ink, in both finishes."""
    for sel, val in (
        (r"html\.cockpit \.msg \.body :is\(strong, b\) \{ color: inherit;", None),
        (r"html\.cockpit \.msg \.body :is\(em, i\),\s*html\.cockpit \.msg \.body :is\(strong, b\) :is\(em, i\),"
         r"\s*html\.cockpit \.msg \.body :is\(em, i\) :is\(strong, b\) \{ color: inherit; \}", None),
        (r"html\.cockpit \.msg \.body :is\(h4, h5, h6\) \{ color: var\(--ck-text\); \}", None),
    ):
        assert re.search(sel, COCKPIT), sel
    assert 'class="cockpit"' in INDEX


def test_index_links_hairline_after_cockpit():
    a = INDEX.index('href="/static/cockpit.css"')
    b = INDEX.index('href="/static/hairline.css"')
    assert a < b


def test_hairline_generated_block_is_current():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make-hairline-css.py"), "--check"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
