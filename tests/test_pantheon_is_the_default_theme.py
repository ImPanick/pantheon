# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Pantheon look (getpantheon.ai) is the default theme, in light and dark.

Someone who has never picked a theme gets `THEMES.pantheon`, or
`THEMES.pantheonlight` when their system is in light mode, both in the
`hairline` finish (`static/hairline.css`). Every other theme keeps the glass
cockpit it had.

The palettes live in four places that must agree, or the first frame paints one
colour and the module repaints another a moment later:

  * `THEMES` in `static/js/theme.js`, the authority;
  * the first-paint script in `static/index.html` (base colours and advanced
    keys);
  * the first-paint script in `static/login.html` (base colours only; that page
    reads no advanced keys);
  * `THEME_DEFAULT_FINISH`, and the `/^pantheon(light)?$/` test both first-paint
    scripts use for the same answer.

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


def test_default_finish_is_hairline_for_the_presets_and_agrees_with_first_paint():
    m = re.search(r"THEME_DEFAULT_FINISH\s*=\s*\{([^}]*)\}", THEME_JS)
    assert m
    table = dict(re.findall(r"(\w+)\s*:\s*'(\w+)'", m.group(1)))
    assert table == {"pantheon": "hairline", "pantheonlight": "hairline"}
    for html in (INDEX, LOGIN):
        assert "/^pantheon(light)?$/.test(t.name) ? 'hairline' : 'glass'" in html


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
