# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B883` — the vendored Mermaid accepts an unknown theme name in silence.

**What is on the tree, measured 2026-09-19 against
`static/lib/mermaid.min.js` (11.17.2) through
`tests/harness/mermaid_diagram_parse.js`.**

`mermaid.initialize({theme: 'light'})` does not throw, does not warn and does
not fall back visibly. `mermaidAPI.getConfig()` afterwards reports

    theme: 'light'                       <- the argument, stored and handed back
    themeVariables: <271 keys>           <- `default`'s, to the byte

The whole-variable-set fingerprints the harness prints say it exactly:

    default                 0b7768f674c76518   (271 keys)
    light                   0b7768f674c76518   (271 keys)
    pantheon-not-a-theme    0b7768f674c76518   (271 keys)
    base                    4aa75816a8a57a45
    dark                    0b92806f45c90401
    forest                  5363cb7b0ee9a78f
    neutral                 57023d3fc590bed7

So `getConfig().theme` is an echo of the argument. A test that asserts it is
asserting its own input — `Law 20` one level down, inside a vendored library —
and it stays green for **any** name, including one nobody shipped.

That matters here because `light` is not a silly mistake. It is the obvious
name for the light `color-scheme`, it is what `B872` would have written if it
had trusted the config object, and it draws `default`: a purple node outline
measuring 2.95–3.25:1 on the four light palettes, under `1.4.11`'s 3:1 line.
`B872` read `themeVariables` for exactly this reason and said so in its own
tests. This file is the general guard behind that reading, so the next person
to set a Mermaid theme anywhere in this repository cannot check the wrong
thing: `theme_really_loaded()` below is the check, and
`tests/test_every_palette_gets_a_legible_diagram_js.py` calls it rather than
keeping a second copy (`Law 14`).

**Why a fingerprint of all 271 variables and not of the eight inks.**
Two themes can agree on `lineColor` and `textColor` and still be different
themes; `forest` and `default` share `textColor: '#333'`. The fingerprint is a
sorted, recursive canonicalisation of the entire `themeVariables` object —
including the five nested ones (`cynefin`, `packet`, `radar`, `wardley`,
`xyChart`) — hashed in the harness. The keys Pantheon itself overrides
(`nodeBorder` today, learned from what `applyMermaidTheme` returned rather than
listed anywhere) are excluded from the comparison fingerprint, because they are
the same in every scheme by construction and would make two different themes
look more alike than they are. Both fingerprints are reported; the tests below
use each where it belongs.

This measures the library. It cannot rasterise — `render()` needs `getBBox`, a
real stylesheet and a live SVG tree, and there is no browser here — which is
why the claim is about the variables a theme computed rather than about pixels.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

from test_vendored_bumps_still_render import run_harness  # noqa: E402


@pytest.fixture(scope="module")
def report():
    got = run_harness("mermaid_diagram_parse.js")
    assert got["ok"], got
    return got


# ── The guard itself ───────────────────────────────────────────────────────

def theme_really_loaded(report, scheme, expected):
    """Assert that `scheme` is drawing in the theme named `expected`.

    The check that the name alone cannot make. `applyMermaidTheme(mermaid,
    scheme)` is compared against `initialize({theme: expected})` on the same
    bundle, on everything the theme computed rather than on what the config
    object repeated back.

    Importable. Anything in this repository that sets a Mermaid theme should
    come through here; `getConfig().theme` is an echo and proves nothing.
    """
    got = report["schemes"][scheme]
    probe = report["themes"][expected]
    assert probe["reported"] == expected, probe
    assert got["vars"]["hash"] == probe["vars"]["hash"], (
        f"the {scheme!r} scheme reports theme {got['theme']!r} but the "
        f"{got['vars']['count']} variables it computed are not {expected!r}'s "
        f"({got['vars']['hash']} vs {probe['vars']['hash']}). A theme name "
        "mermaid does not have is accepted in silence and draws `default` — "
        "check what it drew, not what it echoed."
    )
    return got


# ── The defect, driven ─────────────────────────────────────────────────────

def test_an_unknown_theme_name_is_echoed_back_as_if_it_had_been_applied(report):
    """The first half of the defect: the config object agrees with you.

    Both names below are refused by nothing. If a future mermaid starts
    throwing on an unknown theme — which is the fix upstream would ship — this
    goes red and the row can be closed the other way.
    """
    for name in ("light", "pantheon-not-a-theme"):
        got = report["themes"][name]
        assert got["reported"] == name, (
            f"mermaid no longer echoes an unknown theme name back: {got}"
        )


def test_an_unknown_theme_name_draws_the_default_theme_to_the_byte(report):
    """The second half, and the reason the first half matters.

    Not "close to default" — identical. Every one of the 271 variables,
    including the five nested objects, hashes the same as `default`'s.
    """
    default = report["themes"]["default"]["all"]
    for name in ("light", "pantheon-not-a-theme"):
        got = report["themes"][name]["all"]
        assert got == default, (
            f"{name!r} no longer comes back byte-identical to `default` "
            f"({got} vs {default}); the guard below is measuring something "
            "else now and this file needs re-reading"
        )
        assert got["count"] == 271, got


def test_the_name_check_passes_on_a_theme_nobody_ships_and_the_ink_check_fails(report):
    """The control (`Law 9`). Without it this file asserts nothing.

    Asserting `getConfig().theme == 'light'` is green for a theme that does not
    exist. Asserting the fingerprint is red for it. Both are run here on the
    same measurement so the difference is visible rather than argued.
    """
    wrong = report["themes"]["light"]
    assert wrong["reported"] == "light", wrong          # the check that lies
    assert wrong["vars"]["hash"] == report["themes"]["default"]["vars"]["hash"]
    assert wrong["vars"]["hash"] != report["themes"]["neutral"]["vars"]["hash"], wrong

    # And the guard, pointed at the same wrong answer, refuses it.
    faked = {
        "schemes": {"light": dict(report["schemes"]["light"], vars=wrong["vars"],
                                  theme="light")},
        "themes": report["themes"],
    }
    with pytest.raises(AssertionError, match="accepted in silence"):
        theme_really_loaded(faked, "light", "neutral")


def test_the_five_themes_mermaid_ships_are_five_different_themes(report):
    """What makes a fingerprint comparison mean anything.

    If two of these collided, every assertion in this file and in
    `test_every_palette_gets_a_legible_diagram_js.py` would pass by accident.
    A name that stopped existing collapses onto `default` here — which is
    precisely how `light` shows up — so this is also the alarm for a vendored
    bump that dropped a theme.
    """
    shipped = {name: got for name, got in report["themes"].items() if got["shipped"]}
    assert set(shipped) == {"default", "base", "dark", "forest", "neutral"}, sorted(shipped)
    hashes = {name: got["all"]["hash"] for name, got in shipped.items()}
    assert len(set(hashes.values())) == 5, hashes


# ── The guard applied to what this product ships ───────────────────────────

def test_every_theme_this_product_asks_for_is_one_mermaid_has(report):
    """`SCHEME_THEMES`, checked against the library rather than against itself.

    The harness probes every value in `markdown/mermaidTheme.js`'s own
    `SCHEME_THEMES` — read out of the module, not retyped here — and this
    asserts each one loaded. Setting either scheme to a name mermaid does not
    have fails here; setting it to `'light'` in particular fails here and
    nowhere else, because the config object would report it as applied.
    """
    asked = {name for name, got in report["themes"].items() if got["askedByProduct"]}
    assert asked, report["themes"]
    for name in asked:
        got = report["themes"][name]
        assert got["all"]["hash"] != report["themes"]["default"]["all"]["hash"] or name == "default", (
            f"mermaidTheme.js asks for the theme {name!r} and mermaid drew "
            f"`default` instead: {got}"
        )
    theme_really_loaded(report, "dark", "dark")
    theme_really_loaded(report, "light", "neutral")
    theme_really_loaded(report, "unset", "dark")


def test_the_guard_is_bound_to_the_keys_the_product_actually_overrides(report):
    """The exclusion set is derived, not typed.

    `overriddenKeys` is the union of the keys `applyMermaidTheme` returned in
    its `themeVariables`, collected by the harness from the call itself. If the
    override list grows — `B884` adds one — the comparison keeps excluding
    exactly the keys Pantheon writes, with nothing to update here.
    """
    overridden = set(report["overriddenKeys"])
    assert overridden, report["overriddenKeys"]
    src = (ROOT / "static" / "js" / "markdown" / "mermaidTheme.js").read_text(encoding="utf-8")
    for key in overridden:
        assert re.search(rf"\b{re.escape(key)}\b", src), (
            f"the harness says applyMermaidTheme wrote {key!r} and the module "
            "does not mention it; one of the two moved"
        )
    for scheme in ("dark", "light"):
        applied = report["schemes"][scheme]["applied"].get("themeVariables") or {}
        assert set(applied) <= overridden, (scheme, applied, overridden)
