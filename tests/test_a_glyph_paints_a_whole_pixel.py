# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B782` — no glyph paints a stroke under one device pixel.

An inline `<svg>` with a 24-unit viewBox scales its `stroke-width` by
`size / 24`, so a stroke-2 glyph at 11px paints **0.917** device pixels at 1×.
A browser cannot draw that: it smears the line across two pixels at reduced
opacity or drops one side of it, which is why a sub-pixel stroke reads as a
faint grey glyph rather than a thin one. `P5-13` wrote that sentence as an
example and `B782` measured it: **115** such glyphs on 2026-09-19, **117** when
the sweep ran three weeks later, 103 of them exactly that pair.

**The ruling and where the implementation corrected it.** `D-2026-10-17-02` §4
said raise the **size**, arguing that a stroke rise *adds* a width to a ladder
`P5-13` exists to shrink while 11 → 12 *removes* a size and lands on one the
tree already uses. That is right for the 107 sites whose stroke is the house
stroke 2 and wrong for four of the eight failing pairs, whose strokes are the
rare value: `1.4` appears **once** in the tree, and moving it to `1.5` paints
exactly 1.000px, changes no glyph's size, and deletes a width from the ladder.
So what was applied is §4's criterion rather than its conclusion — move
whichever value is rarer, only onto one the tree already uses — and the result
is that both ladders got **shorter**: sizes 19 → 18, strokes 14 → 11.

**The ladders themselves are not enforced, and that is `B291`'s evidence.** Its
three 8px chevrons carry `stroke-width: 3.5` *because* 2.5 at that size paints
0.83px. That is correct compensation, and a pass that collapsed the ladder onto
one stroke would delete it along with the drift. The floor is a rule; the ladder
is a design sitting, and `P5-13`, `P5-14` and `B394` stay open for one.

**Two parser traps, both of which produced a wrong census first.** A quoted
attribute may contain spaces, and `viewBox="0 0 24 24"` is the whole subject
here — an unquoted-value pattern reads it as `0` and silently finds nothing at
all. And `\\b` is not a left boundary for an attribute name, because `-` is a
word boundary: `\\bwidth=` matches inside `stroke-width=`, which read eleven
strokes as sizes and put `2` and `2.5` in the size ladder. That is `B1404`'s
hyphen bug a second time, two days later, in a second census.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-icon-floor.py"


def _checker():
    spec = importlib.util.spec_from_file_location("_check_icon_floor", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CF = _checker()
GLYPHS = CF.glyphs()


# ── The floor ───────────────────────────────────────────────────────────────

def test_no_glyph_paints_under_one_device_pixel():
    under = [g for g in GLYPHS if g["painted"] < CF.FLOOR - 1e-9]
    assert under == [], "\n".join(
        f"{g['file']}:{g['line']} {g['size']:g}px @ {g['stroke']:g} = "
        f"{g['painted']:.3f}px" for g in under[:12])


def test_the_census_still_finds_the_population():
    """Non-vacuity, and the trap that made this file's first census read zero:
    `viewBox="0 0 24 24"` contains spaces, so an unquoted-value attribute
    pattern matches `0` and every glyph is skipped — a green result that means
    nothing was measured."""
    assert len(GLYPHS) >= 1000, (
        f"only {len(GLYPHS)} glyphs found; the population was 1,044 and a "
        "collapse this large means the parser stopped reading, not that the "
        "icons left")
    assert CF.attribute('<svg viewBox="0 0 24 24">', "viewBox") == "0 0 24 24"


def test_the_parser_does_not_read_a_stroke_as_a_size():
    """`B1404`'s hyphen bug, second occurrence. `-` is a word boundary, so
    `\\bwidth=` matches inside `stroke-width=` — which put `2` and `2.5` in the
    size ladder and inflated it from 19 values to 22."""
    tag = '<svg stroke-width="2.5" viewBox="0 0 24 24">'
    assert CF.attribute(tag, "width") is None, (
        "`stroke-width` is being read as `width`")
    assert CF.attribute(tag, "stroke-width") == "2.5"
    sizes = {g["size"] for g in GLYPHS}
    assert not (sizes & {2.0, 2.5, 3.0}), (
        f"the size ladder contains stroke widths: {sorted(sizes & {2.0, 2.5, 3.0})}")


@pytest.mark.parametrize("size,stroke,painted", [
    (11, 2, 0.9167), (10, 2.2, 0.9167), (10, 2, 0.8333), (16, 1.4, 0.9333),
    (14, 1.6, 0.9333), (14, 1.7, 0.9917), (8, 2.5, 0.8333), (6, 3, 0.75),
])
def test_the_eight_failing_pairs_are_gone_from_the_tree(size, stroke, painted):
    """Each pair `B782` measured, named, with the figure it painted — so a
    regression says which of the eight came back rather than just that one did."""
    assert round(stroke * size / 24, 4) == painted, "re-derive this row"
    back = [g for g in GLYPHS if g["size"] == size and g["stroke"] == stroke]
    where = ", ".join("{}:{}".format(g["file"], g["line"]) for g in back[:4])
    assert back == [], (
        f"{len(back)} glyph(s) are back at {size}px @ {stroke}, which paints "
        f"{painted}px: {where}")


def test_the_floor_is_one_device_pixel_and_the_minimum_size_inverts_it():
    assert CF.FLOOR == 1.0
    for stroke in (1.5, 2.0, 2.5, 3.0):
        smallest = CF.minimum_size(stroke, 24.0)
        assert stroke * smallest / 24.0 == pytest.approx(1.0)
        assert stroke * (smallest - 0.001) / 24.0 < 1.0


# ── The ladders, reported and not enforced ──────────────────────────────────

def test_both_ladders_got_shorter_rather_than_longer():
    """The claim that makes the ruling's criterion the right one: nothing new
    entered either ladder. Measured against the values that were there."""
    sizes = {g["size"] for g in GLYPHS}
    strokes = {g["stroke"] for g in GLYPHS}
    assert 6.0 not in sizes, "6px is back; it was the only glyph at that size"
    assert not (strokes & {1.4, 1.6, 1.7}), (
        f"a stroke width the sweep removed is back: {sorted(strokes & {1.4, 1.6, 1.7})}")
    assert len(sizes) <= 18, f"{len(sizes)} sizes — the ladder grew: {sorted(sizes)}"
    assert len(strokes) <= 11, f"{len(strokes)} strokes — the ladder grew: {sorted(strokes)}"


def test_the_compensated_small_glyphs_are_left_alone():
    """`B291`'s evidence, which is why the ladders are not collapsed: a small
    glyph with a heavy stroke is compensation, not drift, and a flattening pass
    would delete it. Here it is as a population rather than a sentence."""
    small = [g for g in GLYPHS if g["size"] <= 10]
    assert small, "no small glyphs left at all; re-read `B291` before widening this"
    heavy = [g for g in small if g["stroke"] > 2.0]
    assert heavy, (
        "every glyph at 10px or below now carries the house stroke — the "
        "compensation `B291` measured has been flattened")
    for glyph in small:
        assert glyph["painted"] >= CF.FLOOR - 1e-9


def test_the_checker_reports_the_ladders_without_failing_them():
    """`P5-13`, `P5-14` and `B394` are open on purpose. A checker that failed
    the ladder would close them by force, which is the flattening
    `D-2026-08-26-03` and `B291` both argue against."""
    result = subprocess.run([sys.executable, str(CHECKER), "--report"],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NOT enforced" in result.stdout
    assert re.search(r"\d+ sizes, \d+ stroke widths", result.stdout)
    sizes = {g["size"] for g in GLYPHS}
    assert f"{len(sizes)} sizes" in result.stdout, (
        "the printed ladder and the measured one disagree")


# ── The glyph whose size is an argument ─────────────────────────────────────

def test_a_parameterised_glyph_has_a_floor_on_its_callers():
    """The hole a census cannot see. `langIcon(lang, size = 14)` writes
    `width="${size}"` with a literal `stroke-width="2"`, so its floor is a
    *minimum size of 12* and nothing in that file says so. Today every caller
    passes 12, 13 or 14 — which is safe by luck until this holds it."""
    assert CF.PARAMETERISED, "the parameterised population is empty"
    assert CF.parameterised_problems() == [], CF.parameterised_problems()
    module, (function, stroke, view) = next(iter(CF.PARAMETERISED.items()))
    text = (ROOT / module).read_text(encoding="utf-8")
    assert f'width="${{size}}"' in text, (
        f"{module} no longer sizes its glyph from an argument; retire the entry")
    assert CF.minimum_size(stroke, view) == pytest.approx(12.0)


def test_a_caller_below_the_floor_is_caught():
    """`Law 9` — mutate to prove. The guard above is only worth having if a
    caller at 11px actually fails it, so one is written and checked.

    Driven as a **subprocess**, not by calling the function: the first draft
    asserted on `parameterised_problems()` directly, and a mutation that made
    `main()` return 0 with its problems printed walked straight past it. What
    CI reads is the exit code (`Law 20`)."""
    victim = ROOT / "static" / "js" / "document.js"
    original = victim.read_text(encoding="utf-8")
    needle = "langIcon(doc.language, 12,"
    assert needle in original, "re-pick the witness; this call site moved"
    try:
        victim.write_text(original.replace(needle, "langIcon(doc.language, 11,", 1))
        result = subprocess.run([sys.executable, str(CHECKER)], capture_output=True,
                                text=True, cwd=str(ROOT), timeout=300)
        assert result.returncode != 0, (
            "the checker passed a caller at 11px:\n" + result.stdout)
        assert "11px" in result.stdout and "document.js" in result.stdout, result.stdout
    finally:
        victim.write_text(original)
    clean = subprocess.run([sys.executable, str(CHECKER)], capture_output=True,
                           text=True, cwd=str(ROOT), timeout=300)
    assert clean.returncode == 0, clean.stdout + clean.stderr


def test_the_checker_fails_rather_than_reports_when_a_glyph_is_under():
    """The other half of the same gap: a glyph under the floor has to make CI
    red, not just print a line. Mutated in the tree the checker reads, because
    a census built from `sources()` cannot be pointed at a fixture."""
    victim = ROOT / "static" / "js" / "gallery.js"
    original = victim.read_text(encoding="utf-8")
    needle = 'width="12" height="12" viewBox="0 0 24 24"'
    assert needle in original, "re-pick the witness; this glyph moved"
    try:
        victim.write_text(original.replace(
            needle, 'width="11" height="11" viewBox="0 0 24 24"', 1))
        result = subprocess.run([sys.executable, str(CHECKER)], capture_output=True,
                                text=True, cwd=str(ROOT), timeout=300)
        assert result.returncode != 0, (
            "the checker passed an 11px glyph at stroke 2:\n" + result.stdout)
        assert "0.917px" in result.stdout, result.stdout
    finally:
        victim.write_text(original)


def test_the_checker_loads_the_one_comment_blanker():
    """`B290`. A commented-out glyph is not in the product, and a hand-written
    `/\\*.*?\\*/` cannot tell a comment from a string."""
    source = CHECKER.read_text(encoding="utf-8")
    assert "check-specifiers.py" in source
    assert "/\\*.*?\\*/" not in source, "the checker grew its own comment stripper"
