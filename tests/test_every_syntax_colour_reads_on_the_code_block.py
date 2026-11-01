# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1554` — every syntax colour clears 4.5:1 on the code block, on every palette.

`deriveSyntaxColors()` (`static/js/theme.js`) picks each `--hl-*` colour at one
fixed lightness per scheme, the same for every palette, so on the palettes
whose code block sits nearer the middle some landed under AA against the block
they are painted on (`--hl-bg`). `B395`'s pass counted them and named the
count in `test_theme_contrast_floor_css.py`: `comment` on 16 palettes,
`number` 8, `string` 7, `builtin` 5, `keyword` 3.

Now each is moved, per palette, the least that clears — toward whichever of
black or white is legible on the block — and a colour that already cleared is
left exactly as it was. Comments get no lower floor; they are text a person
reads.

Driven, not read (`Law 20`): the real `theme.js` in node, the fixed-lightness
derivation and the walked one side by side for all 23 palettes, and
`static/index.html`'s real first-paint script over the same 23 stored themes,
because it writes the same ten properties before the module boots and two
writers that disagree are a flash nobody can find (`Law 7`).
"""

from __future__ import annotations

import colorsys
import json

import pytest

from test_accent_token_js import (  # noqa: E402 — one harness
    INDEX, THEME, THEME_NAMES, _DOM, _PAINT_SHIM, _THEME_SHIM, _THEME_STUBS,
    _inline_script, _make_sandbox, _palette, _run,
)
from tests.helpers.css_colour import contrast, rgb

FLOOR = 4.5
TEXT = ("keyword", "string", "comment", "function", "number", "builtin", "variable", "params")

# What the fixed lightnesses left under the floor before this row, per token —
# `B395`'s count, which is also the set the walk had to move.
# Less the three presets the cockpit retired (theme.js `RETIRED_THEMES`).
WAS_UNDER = {"comment": 13, "number": 8, "string": 7, "builtin": 5, "keyword": 3}


@pytest.fixture(scope="module")
def syntax(tmp_path_factory):
    """{palette: {"fixed": {...}, "walked": {...}}} from the real module."""
    sandbox = _make_sandbox(tmp_path_factory.mktemp("syntax"), THEME, _THEME_SHIM, _THEME_STUBS)
    with (sandbox / THEME.name).open("a", encoding="utf-8") as handle:
        handle.write("\nexport { deriveSyntaxColors as _derive, "
                     "_syntaxAtFixedLightness as _fixed };\n")
    return _run(sandbox, "import './shim.js';\nconst tm = await import('./theme.js');\n", """
        const out = {};
        for (const [name, colors] of Object.entries(tm.THEMES)) {
          out[name] = { fixed: tm._fixed(colors), walked: tm._derive(colors) };
        }
        console.log(JSON.stringify(out));
    """)


@pytest.fixture(scope="module")
def first_paint(tmp_path_factory):
    """{palette: the `--hl-*` the first-paint script writes for it}."""
    sandbox = tmp_path_factory.mktemp("syntax-paint")
    (sandbox / "dom.js").write_text(_DOM)
    (sandbox / "shim.js").write_text(_PAINT_SHIM)
    (sandbox / "index_paint.js").write_text(_inline_script(INDEX))
    out = {}
    for name in THEME_NAMES:
        got = _run(sandbox, "import { seed, vars } from './shim.js';\n", f"""
            seed({json.dumps(_palette(name))});
            await import('./index_paint.js?' + {json.dumps(name)});
            console.log(JSON.stringify(vars()));
        """)
        out[name] = {k[len("--hl-"):]: v for k, v in got["values"].items() if k.startswith("--hl-")}
    return out


def _hue(hexv):
    h, _, s = colorsys.rgb_to_hls(*[c / 255 for c in rgb(hexv)])
    return h * 360, s


def test_all_shipped_palettes_were_derived(syntax):
    assert len(syntax) == 20 and set(syntax) == set(THEME_NAMES), sorted(syntax)  # three retired: theme.js `RETIRED_THEMES`


def test_every_syntax_colour_clears_the_code_block_on_every_palette(syntax):
    """The row's `Verify:` — the set empties. No token, no palette."""
    under = {(n, k): round(contrast(rgb(row["walked"][k]), rgb(row["walked"]["bg"])), 2)
             for n, row in syntax.items() for k in TEXT
             if contrast(rgb(row["walked"][k]), rgb(row["walked"]["bg"])) < FLOOR}
    assert not under, under


def test_only_what_was_under_moved_and_it_moved_the_least_that_clears(syntax):
    """The palette's character is what is left alone: a colour that cleared at
    its fixed lightness is byte-identical, and the ones that did not moved by
    the smallest whole percent toward the block's ink — one percent less and
    they would not clear — with their hue kept."""
    moved = {}
    for name, row in syntax.items():
        bg = rgb(row["walked"]["bg"])
        assert row["walked"]["bg"] == row["fixed"]["bg"] and row["walked"]["fg"] == row["fixed"]["fg"]
        ink = (0, 0, 0) if contrast((0, 0, 0), bg) >= contrast((255, 255, 255), bg) else (255, 255, 255)
        for key in TEXT:
            was, now = row["fixed"][key], row["walked"][key]
            if contrast(rgb(was), bg) >= FLOOR:
                assert now == was, (name, key, was, now)
                continue
            moved[key] = moved.get(key, 0) + 1
            pct = next(p for p in range(101)
                       if "#" + "".join(f"{round(i * p / 100 + w * (1 - p / 100)):02x}"
                                        for w, i in zip(rgb(was), ink)) == now)
            assert pct > 0
            back = tuple(round(i * (pct - 1) / 100 + w * (1 - (pct - 1) / 100)) for w, i in zip(rgb(was), ink))
            assert contrast(back, bg) < FLOOR, (name, key, "moved further than it needed")
            # Hue held — read where there is a hue to hold: a near-grey's hue
            # is set by 8-bit rounding, not by the walk (`light`'s comment,
            # `#a29e98`, is 6% saturated).
            (h0, s0), (h1, _) = _hue(was), _hue(now)
            if s0 > 0.15:
                assert min(abs(h0 - h1), 360 - abs(h0 - h1)) <= 2.0, (name, key, was, now)
    assert moved == WAS_UNDER, moved


def test_the_link_hue_did_not_move(syntax):
    """`--hl-function` is `--link-fg` (`B23`), whose figures `B395` pinned; it
    cleared the block everywhere and is the same colour it was."""
    assert all(row["walked"]["function"] == row["fixed"]["function"] for row in syntax.values())


def test_the_first_paint_writes_what_the_module_writes(syntax, first_paint):
    """`Law 7` across the two writers, palette by palette, all ten properties."""
    differ = {}
    for name in THEME_NAMES:
        module = {k: v.lower() for k, v in syntax[name]["walked"].items()}
        paint = {k: v.lower() for k, v in first_paint[name].items()}
        if module != paint:
            differ[name] = {k: (module.get(k), paint.get(k)) for k in set(module) | set(paint)
                            if module.get(k) != paint.get(k)}
    assert not differ, differ
