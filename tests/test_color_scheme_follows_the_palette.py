# SPDX-License-Identifier: AGPL-3.0-or-later
"""P3-09 — a light page that opened a black dropdown.

Native `<select>` popups, scrollbars, checkboxes and date pickers are painted by
the browser, not by this stylesheet, and `color-scheme` is the only thing that
tells it which way to paint them. Four rules in `static/style.css` hardcoded
`dark`, including `select` itself — so on the four light themes a light page
opened a black dropdown.

**The fix existed and could not run.** `:root.light select { color-scheme:
light }` sits behind a class nothing has ever added: light themes push their
values through the five palette tokens and never add a class. `:root.light` is
unreachable at the fork point too, so it has never applied to anything in this
product's history (`tests/test_root_class_wiring.py` records it).

So `color-scheme` is derived from the palette instead — from the background's
WCAG relative luminance, not from a theme name, so a custom palette gets the
right answer without being listed anywhere. The margin is not close: the four
light themes measure 0.83–0.94 and the lightest of the twelve dark ones measures
0.025.

Written in all three places the palette is written, for the same reason
`--accent` is: `index.html` and `login.html` paint before `theme.js` boots, and
`initThemeUI()` returns at its missing `#themeGrid` on the login page, so that
screen never reaches `applyColors()` at all.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
THEME = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", " ",
             (ROOT / "static" / "style.css").read_text(encoding="utf-8"), flags=re.S)
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
LOGIN = (ROOT / "static" / "login.html").read_text(encoding="utf-8")
_HAS_NODE = shutil.which("node") is not None

THRESHOLD = 0.5


def _luminance(hex_):
    d = hex_.lstrip("#")
    chans = [int(d[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _theme_backgrounds():
    body = THEME[THEME.index("export const THEMES = {"):]
    body = body[:body.index("\n};")]
    out = {}
    for m in re.finditer(r"^\s{2,}([\w-]+):\s*\{(.*?)\}[,\s]*$", body, re.M | re.S):
        bg = re.search(r"bg:\s*'(#[0-9a-fA-F]{6})'", m.group(2))
        if bg:
            out[m.group(1)] = bg.group(1)
    return out


def test_there_are_still_sixteen_themes_and_four_of_them_are_light():
    """Guards every claim below. A parser that stops finding themes makes the
    separation test vacuous, and the count is `FORBIDDEN.md`'s."""
    bgs = _theme_backgrounds()
    assert len(bgs) == 16, sorted(bgs)
    light = {n for n, hexv in bgs.items() if _luminance(hexv) > THRESHOLD}
    assert light == {"paper", "cute", "lavender", "light"}, sorted(light)


def test_the_threshold_is_nowhere_near_any_theme():
    """A rule that classifies by measurement is only as good as its margin.
    Darkest light theme 0.835, lightest dark theme 0.025 — the threshold sits
    in a gap of 0.81, so no rounding or colour tweak moves a theme across it."""
    lums = sorted(_luminance(v) for v in _theme_backgrounds().values())
    below = [x for x in lums if x <= THRESHOLD]
    above = [x for x in lums if x > THRESHOLD]
    assert below and above
    assert max(below) < 0.1 and min(above) > 0.8, (max(below), min(above))


def test_all_three_palette_writers_set_it():
    """`applyColors` is one of three places the palette is written, and the
    other two paint first. A fix in only the module is a flash on every load
    and nothing at all on the login page."""
    assert "s.setProperty('color-scheme'," in THEME
    for name, src in (("index.html", INDEX), ("login.html", LOGIN)):
        assert "setProperty('color-scheme'" in src, name
        assert "0.2126" in src, f"{name} does not measure the background"


def _rules_setting_color_scheme():
    """(selector, value) for every rule that sets `color-scheme`.

    Counted per rule, with its selector, rather than per line: the first
    version of this counted line-anchored declarations against rule matches and
    compared two different things."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
        v = re.search(r"(?<![a-z-])color-scheme\s*:\s*([^;]+)", m.group(2))
        if v:
            out.append((" ".join(m.group(1).split()), v.group(1).strip()))
    return out


def test_no_reachable_rule_pins_a_scheme_the_palette_disagrees_with():
    """`color-scheme: dark` on an element blocks the inheritance this fix
    depends on. The four rules that did are the whole bug."""
    rules = _rules_setting_color_scheme()
    assert rules, "the rule parser found no color-scheme at all"
    offenders = [
        (sel, val) for sel, val in rules
        if val in ("dark", "light") and ":root.light" not in sel
    ]
    assert not offenders, (
        "these pin a scheme regardless of the palette: " + repr(offenders)
    )
    assert any(val == "inherit" for _, val in rules), (
        "nothing defers to the root — the rules were deleted rather than "
        "pointed at it"
    )
    assert any(":root.light" in sel for sel, _ in rules), (
        "the unreachable light rules were removed; Law 1 keeps them"
    )


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_the_three_implementations_agree_on_every_theme():
    """Three copies of one rule is the shape `--accent` already had to fix
    twice. They must not drift, so all three are run against all sixteen
    palettes and compared with an independent implementation here."""
    def _extract(src, marker_start):
        i = src.index(marker_start)
        depth, j = 0, src.index("{", i)
        start = j
        while j < len(src):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        return src[i:j + 1]

    module_fn = _extract(THEME, "function _isLightBackground(hex)")
    bgs = _theme_backgrounds()
    script = module_fn + f"""
    const bgs = {json.dumps(bgs)};
    const inline = (c) => {{
      var d = String(c || '').replace('#', '');
      var light = false;
      if (d.length === 6) {{
        var lin = [0, 2, 4].map(function (i) {{
          var ch = parseInt(d.slice(i, i + 2), 16) / 255;
          return ch <= 0.03928 ? ch / 12.92 : Math.pow((ch + 0.055) / 1.055, 2.4);
        }});
        light = (0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]) > 0.5;
      }}
      return light;
    }};
    const out = {{}};
    for (const [name, hex] of Object.entries(bgs)) {{
      out[name] = [_isLightBackground(hex), inline(hex)];
    }}
    console.log(JSON.stringify(out));
    """
    p = subprocess.run(["node", "--input-type=module", "-e", script],
                       cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert p.returncode == 0, p.stderr
    got = json.loads(p.stdout.strip().splitlines()[-1])
    for name, hexv in bgs.items():
        expected = _luminance(hexv) > THRESHOLD
        module_says, inline_says = got[name]
        assert module_says is expected, (name, "theme.js disagrees")
        assert inline_says is expected, (name, "the first-paint script disagrees")


def test_the_inline_copies_are_the_same_arithmetic():
    """Not merely that both answer correctly on today's sixteen — that they are
    the same computation, so a seventeenth palette cannot split them."""
    for name, src in (("index.html", INDEX), ("login.html", LOGIN)):
        block = src[src.index("setProperty('color-scheme'") - 900:
                    src.index("setProperty('color-scheme'") + 60]
        for token in ("0.03928", "12.92", "1.055", "2.4", "0.2126", "0.7152",
                      "0.0722", "> 0.5"):
            assert token in block, f"{name} is missing {token}"


def test_the_unreachable_light_class_is_left_alone():
    """`:root.light` still carries the tuned light palette and still has no
    writer. Law 1: this row's fix does not need it deleted, and the row that
    proposed deleting it was written before anyone measured that its `--hl-*`
    tokens lose to the inline ones `theme.js` derives anyway."""
    assert ":root.light {" in CSS
    assert "--hl-keyword" in CSS.split(":root.light {", 1)[1][:800]
