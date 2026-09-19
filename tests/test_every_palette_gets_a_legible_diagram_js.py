# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B872` — a Mermaid diagram you can read, on all sixteen palettes.

**What was on the tree before this, measured 2026-09-19 at `HEAD`.**
`static/js/markdown.js:94` was

    window.mermaid.initialize({ startOnLoad: false, theme: 'dark',
                                securityLevel: 'loose' })

called once by `ensureMermaid` (`:90`), which is the only place this product
initialises Mermaid and therefore the theme every diagram it draws gets: chat
(`chatRenderer.js:3939`, `:4271`), the document preview (`document.js:9831`),
the slash-command preview (`slashCommands.js:476`) and `P8-34`'s workflow card
(`tasks.js:2329`). Four of the sixteen shipped palettes are light — `light`,
`paper`, `lavender`, `cute` (`theme.js:15,18,25,30`).

Measured against `.mermaid-container`'s own backdrop (`style.css:10592`,
`color-mix(in srgb, var(--bg) 95%, var(--fg))`), the dark theme on those four
palettes drew

    arrows (`lineColor: lightgrey`)   1.17, 1.29, 1.21, 1.29 : 1
    node outlines (`nodeBorder: #ccc`) 1.26, 1.39, 1.30, 1.38 : 1

against a 3:1 floor for a graphical object. That is not "hard to read", it is
the same colour. `P8-34` worked around it for its own surface only, with a
per-diagram `%%{init:…}%%` directive, and reported the rest as this row.

**How this is asserted, and why it is not a grep.**

  1. The scheme each palette resolves to comes from `theme.js`'s **own**
     `_isLightBackground`, run under node —
     `test_color_scheme_follows_the_palette.py` already extracts and drives it
     and this file imports that rather than writing a second luminance rule
     (`Law 14`).
  2. The theme each scheme resolves to, and the ink that theme actually
     carries, come from **the real vendored `static/lib/mermaid.min.js`**,
     through `tests/harness/mermaid_diagram_parse.js`, which calls the shipped
     `applyMermaidTheme` — the same function `ensureMermaid` calls — and reads
     `mermaidAPI.getConfig().themeVariables` back out. No assertion written in
     a test can say what colour Mermaid will draw with; only Mermaid can.
  3. The backdrop comes from `style.css`'s own declaration, parsed rather than
     retyped, so a change to the container's background moves these numbers
     instead of quietly invalidating them.

Contrast is then computed here and asserted. The thresholds are WCAG 2.2:
**3:1** for the arrows and the node outlines (1.4.11, non-text contrast — they
are the graphical objects the diagram is read by, and `P8-34` encodes what a
node *is* purely as its shape) and **4.5:1** for label text (1.4.3, at
Mermaid's 16px default).

`test_the_old_pin_would_still_fail_this` is the control: the same measurement
run against the literal that used to be in `markdown.js` has to come out red,
or this file is asserting nothing.

The one thing this cannot reach is the rasteriser: `mermaid.render()` needs
`getBBox`, a real stylesheet and a live SVG tree, and there is no browser and
no `node_modules` here (`Law 16` — nothing gets installed to run a test). So
this measures the ink Mermaid says it will use. The bundle's own flowchart
stylesheet is `.node rect, .node circle, … { fill: ${mainBkg}; stroke:
${nodeBorder} }` and `.label { color: ${nodeTextColor || textColor} }`, so
those are the declarations these five variables end up in.
"""

from __future__ import annotations

import colorsys
import pathlib
import re
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

from test_color_scheme_follows_the_palette import (  # noqa: E402
    THRESHOLD, _luminance, _theme_backgrounds,
)
from test_vendored_bumps_still_render import run_harness  # noqa: E402

# WCAG 2.2. 1.4.11 for anything the diagram is read by that is not text;
# 1.4.3 for the text, at Mermaid's 16px default (`fontSize` comes back "16px").
GRAPHIC_MIN = 3.0
TEXT_MIN = 4.5

_NAMED = {"lightgrey": "#d3d3d3", "white": "#ffffff", "black": "#000000"}


def _rgb(colour):
    """sRGB triple for the spellings Mermaid's themes actually use."""
    text = str(colour).strip()
    text = _NAMED.get(text.lower(), text)
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        assert len(digits) == 6, colour
        return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
    hsl = re.match(r"hsla?\(\s*([-\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%", text)
    if hsl:
        h, s, lightness = (float(hsl.group(i)) for i in (1, 2, 3))
        r, g, b = colorsys.hls_to_rgb((h % 360) / 360, lightness / 100, s / 100)
        return tuple(round(c * 255) for c in (r, g, b))
    rgb = re.match(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", text)
    if rgb:
        return tuple(round(float(rgb.group(i))) for i in (1, 2, 3))
    raise AssertionError(f"mermaid handed back a colour this test cannot read: {colour!r}")


def _rel_luminance(rgb):
    chans = [c / 255 for c in rgb]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = _rel_luminance(_rgb(a)), _rel_luminance(_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _container_mix():
    """`.mermaid-container`'s background, read out of the stylesheet.

    Parsed rather than retyped so the numbers below track the panel a diagram
    is really drawn on. Returns `(first_token, share, second_token)` for
    `color-mix(in srgb, var(--X) N%, var(--Y))`.
    """
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    block = re.search(r"\.mermaid-container\s*\{([^}]*)\}", css)
    assert block, "static/style.css no longer has a .mermaid-container rule"
    mix = re.search(
        r"background:\s*color-mix\(\s*in srgb,\s*var\(--(\w+)\)\s*([\d.]+)%\s*,\s*var\(--(\w+)\)\s*\)",
        block.group(1),
    )
    assert mix, (
        "the .mermaid-container background is no longer a two-token color-mix; "
        "this test measures against it and has to be updated with it: "
        + " ".join(block.group(1).split())
    )
    return mix.group(1), float(mix.group(2)) / 100, mix.group(3)


def _panel(theme_colours):
    """The backdrop a diagram sits on, for one palette."""
    first, share, second = _container_mix()
    a, b = _rgb(theme_colours[first]), _rgb(theme_colours[second])
    return "#%02x%02x%02x" % tuple(
        round(a[i] * share + b[i] * (1 - share)) for i in range(3)
    )


def _palette_colours():
    """`bg` and `fg` per shipped theme, out of `theme.js`'s own table."""
    src = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
    body = src[src.index("export const THEMES = {"):]
    body = body[:body.index("\n};")]
    out = {}
    for m in re.finditer(r"^\s{2,}([\w-]+):\s*\{(.*?)\}[,\s]*$", body, re.M | re.S):
        colours = dict(re.findall(r"(\w+):\s*'(#[0-9a-fA-F]{6})'", m.group(2)))
        if "bg" in colours and "fg" in colours:
            out[m.group(1)] = colours
    return out


@pytest.fixture(scope="module")
def mermaid_schemes():
    """What the real bundle says it will draw with, per `color-scheme`."""
    report = run_harness("mermaid_diagram_parse.js")
    assert report["ok"], report
    return report["schemes"]


@pytest.fixture(scope="module")
def palettes():
    colours = _palette_colours()
    assert len(colours) == 16, sorted(colours)
    return colours


def _scheme_for(bg):
    """`theme.js`'s answer, not a second one. Backed by
    `test_color_scheme_follows_the_palette.py`, which runs the shipped
    `_isLightBackground` under node against all sixteen and compares it with an
    independent implementation."""
    return "light" if _luminance(bg) > THRESHOLD else "dark"


def _ink_for(mermaid_schemes, palette_bg):
    return mermaid_schemes[_scheme_for(palette_bg)]["ink"]


def test_the_measurement_still_has_all_sixteen_palettes_and_both_schemes(palettes, mermaid_schemes):
    """Guards every number below. A parser that stopped finding palettes, or a
    harness that stopped answering one of the schemes, would make the rest of
    this file vacuous rather than red."""
    schemes = {_scheme_for(c["bg"]) for c in palettes.values()}
    assert schemes == {"light", "dark"}, schemes
    light = {n for n, c in palettes.items() if _scheme_for(c["bg"]) == "light"}
    assert light == {"light", "paper", "lavender", "cute"}, sorted(light)
    assert set(mermaid_schemes) >= {"light", "dark", "unset"}, sorted(mermaid_schemes)
    for name, got in mermaid_schemes.items():
        assert got["ink"]["lineColor"], (name, got["ink"])
        assert got["securityLevel"] == "loose", (name, got)


def test_every_palette_gets_a_theme_mermaid_actually_has(mermaid_schemes):
    """`initialize({theme: 'light'})` is accepted in silence and draws
    `default` — measured on this bundle: the name comes back as asked and the
    variables come back as another theme's. So the theme name alone proves
    nothing and the ink is read back with it."""
    assert mermaid_schemes["dark"]["theme"] == "dark", mermaid_schemes["dark"]
    assert mermaid_schemes["light"]["theme"] == "neutral", mermaid_schemes["light"]
    # Two themes, two different sets of ink. Identical ink would mean one of
    # the names silently fell through to the other.
    assert (mermaid_schemes["dark"]["ink"]["lineColor"]
            != mermaid_schemes["light"]["ink"]["lineColor"]), mermaid_schemes
    # A document that has not been told yet gets the shipped default.
    assert mermaid_schemes["unset"]["ink"] == mermaid_schemes["dark"]["ink"]


@pytest.mark.parametrize("palette", sorted(_palette_colours()))
def test_the_arrows_and_the_outlines_are_visible_on_this_palette(palette, palettes, mermaid_schemes):
    """The two strokes the diagram is read by, against the panel they are drawn
    on. `lineColor` is every arrow; `nodeBorder` is the outline of every box,
    and on `P8-34`'s workflow card the outline is the *only* thing that says
    whether a step is a prompt, a research run or an action."""
    colours = palettes[palette]
    panel = _panel(colours)
    ink = _ink_for(mermaid_schemes, colours["bg"])
    for key in ("lineColor", "nodeBorder"):
        got = contrast(ink[key], panel)
        assert got >= GRAPHIC_MIN, (
            f"{palette}: mermaid's {key} ({ink[key]}) against the "
            f".mermaid-container panel ({panel}) is {got:.2f}:1, under "
            f"{GRAPHIC_MIN}:1"
        )


@pytest.mark.parametrize("palette", sorted(_palette_colours()))
def test_the_labels_are_readable_on_this_palette(palette, palettes, mermaid_schemes):
    """Node text sits on the node's own fill, and the arrow words ("if it
    works" / "if it fails") sit on `edgeLabelBackground` — not on the panel, so
    each is measured against what is actually behind it."""
    colours = palettes[palette]
    ink = _ink_for(mermaid_schemes, colours["bg"])
    node_text = ink["nodeTextColor"] or ink["textColor"]
    on_node = contrast(node_text, ink["mainBkg"])
    assert on_node >= TEXT_MIN, (
        f"{palette}: node label {node_text} on node fill {ink['mainBkg']} is "
        f"{on_node:.2f}:1, under {TEXT_MIN}:1"
    )
    on_edge = contrast(ink["textColor"], ink["edgeLabelBackground"])
    assert on_edge >= 4.0, (
        f"{palette}: edge label {ink['textColor']} on {ink['edgeLabelBackground']} "
        f"is {on_edge:.2f}:1"
    )


def test_the_old_pin_would_still_fail_this(palettes, mermaid_schemes):
    """The control. `markdown.js` pinned `theme: 'dark'` for all sixteen; this
    re-runs the same measurement with that one decision put back and requires
    it to come out red on the four light palettes, and only on those four.

    Without this, a `SCHEME_THEMES` that mapped both schemes to the same theme
    would pass every test above by making `dark` the answer everywhere.
    """
    dark_ink = mermaid_schemes["dark"]["ink"]
    failures = {}
    for name, colours in palettes.items():
        panel = _panel(colours)
        worst = min(contrast(dark_ink[k], panel) for k in ("lineColor", "nodeBorder"))
        if worst < GRAPHIC_MIN:
            failures[name] = round(worst, 2)
    assert set(failures) == {"light", "paper", "lavender", "cute"}, failures
    # Not marginal: every one of the four is at or near 1:1 — the same colour.
    assert max(failures.values()) < 1.5, failures
