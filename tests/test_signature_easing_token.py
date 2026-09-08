# SPDX-License-Identifier: AGPL-3.0-or-later
"""P1-14 — the curve that defines how this product feels had no name.

`cubic-bezier(0.34, 1.56, 0.64, 1)` is the overshoot easing on 34 transitions
and animations across `static/style.css`. Twenty distinct `cubic-bezier()`
values live in that file; this is the one that carries the identity, and until
2026-09-07 changing it meant find-and-replace across 34 lines, which is another
way of saying it was never going to be changed.

Three near-misses are deliberately left literal: `0.34, 1.2, 0.64, 1` (twice),
`0.34, 1.32, 0.55, 1` and `0.34, 1, 0.64, 1` are the same shape with a gentler
overshoot. That is either a considered choice or drift from the signature, and
nobody here knows which — so they stay, named, and the question survives being
asked (`Law 1`). Sweeping them in would answer it by accident.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

SIGNATURE = "cubic-bezier(0.34, 1.56, 0.64, 1)"
TOKEN = "--ease-signature"

# The same shape, a gentler overshoot. Kept literal on purpose.
NEAR_MISSES = {
    "cubic-bezier(0.34, 1.2, 0.64, 1)": 2,
    "cubic-bezier(0.34, 1.32, 0.55, 1)": 1,
    "cubic-bezier(0.34, 1, 0.64, 1)": 1,
}


def _root_block():
    start = CSS.index(":root {")
    return CSS[start:CSS.index("\n}", start)]


def test_the_token_is_declared_once_and_carries_the_curve():
    assert CSS.count(f"{TOKEN}:") == 1, "declared more than once"
    assert f"{TOKEN}: {SIGNATURE};" in _root_block(), (
        "the token is not in :root, so it does not reach every rule that uses it"
    )


def test_no_use_site_still_spells_the_curve():
    """One literal survives — the declaration. Every other occurrence was a
    place the value had to be edited by hand."""
    assert CSS.count(SIGNATURE) == 1, (
        f"{CSS.count(SIGNATURE) - 1} rule(s) still hardcode the signature curve"
    )


def test_the_token_is_actually_used():
    """A named constant nobody references is worse than the literal: it looks
    like the value is centralised when it is not."""
    uses = CSS.count(f"var({TOKEN})")
    assert uses >= 34, f"only {uses} uses — did a sweep get reverted?"


def test_every_use_sits_where_a_timing_function_belongs():
    """`var()` substitutes text, so a token in the wrong slot produces a rule
    the browser drops silently rather than an error anyone sees."""
    for m in re.finditer(rf"var\({TOKEN}\)", CSS):
        line_start = CSS.rfind("\n", 0, m.start()) + 1
        # Multi-line shorthands exist; walk back to the declaration's property.
        window = CSS[max(0, line_start - 200):m.end()]
        assert re.search(r"(transition|animation)[a-z-]*\s*:", window), (
            "a use outside a transition/animation declaration: "
            + repr(CSS[line_start:m.end() + 40])
        )


def test_the_near_misses_are_left_alone_and_still_named():
    """If one of these is ever swept into the token, this fails — and it should,
    because that is a decision about how the product moves, not a cleanup."""
    for curve, expected in NEAR_MISSES.items():
        assert CSS.count(curve) == expected, (
            f"{curve} now appears {CSS.count(curve)} times, expected {expected}. "
            "If it was folded into the signature token that is a taste "
            "decision — record it rather than letting this test be edited to "
            "match."
        )
    root = _root_block()
    assert "near-misses" in root or "near-miss" in root, (
        "the reason they are still literal is not written where the token is"
    )
