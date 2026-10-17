# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1404` — a control's boundary clears 3:1, and a panel edge is left alone.

WCAG 1.4.11 asks **3:1** of the visual boundary of a UI component against its
background. Measured over all 23 palettes, `--border` misses that against
`--panel` on **22** of them: `organs` **1.21**, `claude` 1.49, `light` 1.47,
`midnight` 1.42 — and the best, `cyberpunk`, reaches only **3.82**.

**The row was filed rather than fixed, then classified, and the classification
is what made it a review.** 1.4.11 asks nothing of a decorative edge, and of
the stylesheet's border reads, **932** are exactly that — panel edges, card
outlines, dividers, table rules. **139** are on a selector naming an `input`,
`textarea`, `select`, `button`, a `:focus` state, `[contenteditable]`, or a
class the shipped markup puts on a focusable element. So the rule applies to
**13%** of the population, and lifting the whole of it would flatten the
difference between a text field and a panel edge on 23 palettes — what
`D-2026-08-26-03` protects the themes from. `D-2026-10-17-02` §3 ruled for a
second token.

**Two censuses shipped before that one and both were wrong, which is why the
figures above are the only place they are written down outside the function
that computes them.** The first said 176 and 785: `\\b(input|textarea|select|
button)\\b` matches inside `.chat-input-bar` and `.input-divider`, because `-`
is a word boundary, so hyphenated class names with a tag name inside them were
counted as controls — the bucket was inflated 39%. The second said 127 and 834,
measured after that fix and stale within the hour: the converted spelling
`var(--border-control, var(--border))` **contains** the plain one, so a census
grepping `var(--border)` double-counts every read it just fixed. The classifier
strips classes, ids, attributes and pseudos now, `_css_border_read_census()`
recomputes the split on every CI run, and `check-contrast.py` prints it.

**What the token is.** `controlBorderFor()` mixes the theme's own `--border`
toward its own `--fg` by the **smallest** amount that clears the floor, so a
palette keeps its border's character where it can afford to: `cyberpunk` needs
0%, `copper` 4%, `forest` 10%, `ume` 14%. The two that move a long way are
`cute` (84%) and `retrowave` (68%), and that is `B15` showing through — a border
at 1.5:1 on its own panel has to move a long way to become visible, and the
alternative is a control nobody can find.

**There is no first-paint mirror, deliberately**, unlike `--accent` and
`--on-accent`. The stylesheet reads `var(--border-control, var(--border))`, so
before the module boots a control paints with today's border: one frame of a
*weaker* outline, which is the appearance that shipped yesterday rather than an
illegible one. `--on-accent` needed its mirrors because its fallback was white
on a yellow button.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
THEME = ROOT / "static" / "js" / "theme.js"
STYLE = ROOT / "static" / "style.css"


def _audit():
    spec = importlib.util.spec_from_file_location(
        "check_contrast_b1404", ROOT / ".pantheon" / "check-contrast.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CC = _audit()
PALETTES = sorted(CC.themes().items())
FLOOR = CC.LARGE_FLOOR


# ── the floor, on every palette ────────────────────────────────────────────


def test_the_decorative_border_is_the_measurement_this_row_rests_on():
    """Non-vacuity, and the number that makes the row worth doing: if
    `--border` already cleared 3:1 there would be nothing here."""
    failing = [n for n, p in PALETTES
               if CC.contrast(p["border"], p["panel"]) < FLOOR]
    assert len(failing) >= 20, (
        f"only {len(failing)} of {len(PALETTES)} palettes miss {FLOOR}:1 on "
        "their own panel; re-derive this row")
    best = max((CC.contrast(p["border"], p["panel"]), n) for n, p in PALETTES)
    assert best[0] < 4.5, (
        f"{best[1]} now reaches {best[0]:.2f}:1 — the palettes moved, re-measure")


@pytest.mark.parametrize("name,pal", PALETTES, ids=[n for n, _ in PALETTES])
def test_the_control_border_clears_the_floor_on_every_palette(name, pal):
    value = CC.control_border_for(pal["border"], pal["panel"], pal["fg"])
    ratio = CC.contrast(value, pal["panel"])
    assert ratio >= FLOOR, f"{name}: {value} only reaches {ratio:.2f}:1"


def test_the_mix_is_the_least_that_clears_it():
    """*Smallest amount* is the design, not a side effect: a fixed ratio that
    cleared `cute` would overshoot the other 22, and a border is part of a
    palette's character."""
    for name, pal in PALETTES:
        value = CC.control_border_for(pal["border"], pal["panel"], pal["fg"])
        if value.lower() == pal["border"].lower():
            continue          # already clear; nothing was added
        # One step less must fail, or this is not the least mix.
        digits = [int(value.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        b = [int(pal["border"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        f = [int(pal["fg"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        span = max(abs(f[i] - b[i]) for i in range(3)) or 1
        pct = round(100 * max(abs(digits[i] - b[i]) for i in range(3)) / span)
        if pct <= 1:
            continue
        lesser = "#" + "".join(
            f"{round(f[i] * (pct - 2) / 100 + b[i] * (1 - (pct - 2) / 100)):02x}"
            for i in range(3))
        assert CC.contrast(lesser, pal["panel"]) < FLOOR, (
            f"{name}: a smaller mix ({pct - 2}%) already clears the floor, so "
            f"{pct}% is not the least")


# ── the two implementations agree ──────────────────────────────────────────


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_module_and_the_audit_compute_the_same_border(tmp_path_factory):
    """Two implementations, 23 palettes, one answer — the arrangement `P1-08`
    uses for `--on-accent`, because a formula copied is a formula that rots."""
    from test_accent_token_js import (_TEST_EXPORTS, _THEME_SHIM, _THEME_STUBS,
                                      _make_sandbox, THEME as THEME_PATH)

    sandbox = _make_sandbox(tmp_path_factory.mktemp("ctlborder"), THEME_PATH,
                            _THEME_SHIM, _THEME_STUBS)
    with (sandbox / THEME_PATH.name).open("a", encoding="utf-8") as handle:
        handle.write(_TEST_EXPORTS)
    entry = sandbox / "case.mjs"
    payload = json.dumps({n: p for n, p in PALETTES})
    entry.write_text(
        "import './shim.js';\n"
        "const tm = await import('./theme.js');\n"
        f"const pals = {payload};\n"
        "const out = {};\n"
        "for (const [name, p] of Object.entries(pals)) {\n"
        "  out[name] = tm.controlBorderFor(p.border, p.panel, p.fg);\n"
        "}\n"
        "console.log(JSON.stringify(out));\n"
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    got = json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])
    assert got, "the sandbox produced nothing"
    for name, pal in PALETTES:
        expected = CC.control_border_for(pal["border"], pal["panel"], pal["fg"])
        assert got[name].lower() == expected.lower(), (
            f"{name}: theme.js says {got[name]}, the audit says {expected}")


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_applycolors_writes_the_token(tmp_path_factory):
    from test_accent_token_js import (_TEST_EXPORTS, _THEME_SHIM, _THEME_STUBS,
                                      _make_sandbox, THEME as THEME_PATH)

    sandbox = _make_sandbox(tmp_path_factory.mktemp("ctlwrite"), THEME_PATH,
                            _THEME_SHIM, _THEME_STUBS)
    with (sandbox / THEME_PATH.name).open("a", encoding="utf-8") as handle:
        handle.write(_TEST_EXPORTS)
    entry = sandbox / "case.mjs"
    payload = json.dumps({n: p for n, p in PALETTES})
    entry.write_text(
        "import { vars } from './shim.js';\n"
        "const tm = await import('./theme.js');\n"
        f"const pals = {payload};\n"
        "const out = {};\n"
        "for (const [name, p] of Object.entries(pals)) {\n"
        "  tm.applyColors(p);\n"
        "  out[name] = vars().values['--border-control'] ?? null;\n"
        "}\n"
        "console.log(JSON.stringify(out));\n"
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    got = json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])
    for name, pal in PALETTES:
        assert got[name], f"{name}: applyColors wrote no --border-control"
        assert CC.contrast(got[name], pal["panel"]) >= FLOOR


# ── the sweep, and the half it deliberately did not touch ──────────────────


def test_no_control_boundary_still_reads_the_decorative_border():
    """The audit's own reader, so CI and this file cannot disagree."""
    assert CC._css_control_border_readers() == []


def test_the_decorative_population_was_left_alone():
    """The ruling's other half: 1.4.11 asks nothing of panel edges and card
    outlines, so a sweep that converted them too would be the flattening
    `D-2026-08-26-03` protects the palettes from.

    Derived from the census, not from a figure typed here. `B1404` typed the
    figure twice and got it wrong twice — once inflated 39% by the hyphen bug,
    once stale the moment the sweep ran."""
    control, decorative = CC._css_border_read_census()
    assert decorative > control * 3, (
        f"{control} control reads against {decorative} decorative ones — the "
        "decorative population is meant to dwarf the control one; a ratio "
        "this close means the sweep reached edges it was told to leave alone")
    # Two units, and mixing them is its own trap: the census counts
    # declaration×**selector** pairs, while a `findall` over the stylesheet
    # counts declarations. A rule with three selectors and one border read is 1
    # here and 3 there, so the two totals are not comparable and the first
    # draft of this test asserted `plain >= decorative` and failed on arithmetic
    # rather than on anything about the sweep.
    css = CC._blank(STYLE)
    converted = len(re.findall(r"var\(--border-control,\s*var\(--border\)\)", css))
    plain = len(re.findall(r"var\(\s*--border\s*[,)]", css)) - converted
    assert converted > 0, "nothing was converted; the sweep is gone"
    assert plain > converted * 3, (
        f"{plain} plain declarations left against {converted} converted — in "
        "the same unit, the untouched population must still dwarf the swept "
        "one, or edges 1.4.11 asks nothing of have been swept")


def test_the_census_is_computed_not_quoted():
    """The rot guard. Both wrong figures `B1404` shipped lived in prose: the
    first in this classifier's docstring, the second in a tracker row. A census
    the audit prints every run cannot go stale between two readers, so the
    docstring is not allowed to name one."""
    doc = CC._css_control_border_readers.__doc__ or ""
    stale = re.findall(r"\b\d{3,}\b", doc)
    assert not stale, (
        f"the classifier's docstring names {stale} — a census belongs in "
        "`_css_border_read_census()`, which recomputes it, not in a comment "
        "nobody recomputes")


def test_the_audit_prints_the_census_it_computes():
    """`Law 20`: drive it, don't grep it. The printed line and the function
    have to be the same two numbers, or the audit is reassuring CI about a
    figure it did not measure."""
    control, decorative = CC._css_border_read_census()
    result = subprocess.run(
        [sys.executable, str(ROOT / ".pantheon" / "check-contrast.py")],
        capture_output=True, text=True, cwd=str(ROOT), timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    wanted = (f"{control} on a control boundary, {decorative} decorative "
              f"({control + decorative} total)")
    assert wanted in result.stdout, (
        f"the audit does not print {wanted!r}; its census and this one disagree")


def test_both_derivations_round_a_tie_the_way_the_browser_does():
    """A channel can land exactly on `.5` — `video` does, twice — and Python
    rounds a tie to the even number while `Math.round` rounds it up. The
    browser paints, so the audit rounds the browser's way. This is the defect
    `test_the_module_and_the_audit_compute_the_same_border` caught as one wrong
    hex digit on one palette; pinned here so the *reason* is findable without
    re-deriving it (`Law 15`)."""
    ties = []
    for name, pal in PALETTES:
        b = tuple(int(pal["border"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        f = tuple(int(pal["fg"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        for pct in range(0, 101):
            t = pct / 100
            for i in range(3):
                v = f[i] * t + b[i] * (1 - t)
                if abs(v - math.floor(v) - 0.5) < 1e-9 and round(v) != math.floor(v + 0.5):
                    ties.append((name, pct, i, v))
    assert ties, (
        "no palette lands a channel on a tie any more, so this guard proves "
        "nothing — re-derive it or retire it")
    # Driven, not grepped (`Law 20`): the first draft of this guard asserted
    # the name `half_up` was in the source, and `half_up = lambda v: round(v)`
    # walked straight past it.
    def derive(pal, rounder):
        b = tuple(int(pal["border"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        f = tuple(int(pal["fg"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        for pct in range(0, 101):
            t = pct / 100
            mixed = "#" + "".join(
                f"{max(0, min(255, rounder(f[i] * t + b[i] * (1 - t)))):02x}"
                for i in range(3))
            if CC.contrast(mixed, pal["panel"]) >= FLOOR:
                return mixed
        return pal["fg"]

    up = {n: derive(p, lambda v: math.floor(v + 0.5)) for n, p in PALETTES}
    even = {n: derive(p, round) for n, p in PALETTES}
    divergent = sorted(n for n in up if up[n] != even[n])
    assert divergent, (
        "no palette's answer changes with the tie rule any more, so this guard "
        "proves nothing — re-derive it or retire it")
    for name, pal in PALETTES:
        got = CC.control_border_for(pal["border"], pal["panel"], pal["fg"])
        assert got.lower() == up[name].lower(), (
            f"{name}: the audit says {got}, rounding the browser's way says "
            f"{up[name]} (Python's own `round` would say {even[name]}) — the "
            f"audit is back on banker's rounding and disagrees with theme.js "
            f"on {len(divergent)} palette(s): {', '.join(divergent)}")
    assert "Math.round(" in THEME.read_text(encoding="utf-8"), (
        "theme.js no longer uses Math.round, so the audit's half-up rule is "
        "now the one that is wrong")


def test_the_classifier_does_not_read_a_tag_name_inside_a_class_name():
    """The defect that inflated the first census by 39%: `\\binput\\b` matches
    inside `.chat-input-bar`, because `-` is a word boundary."""
    css = CC._blank(STYLE)
    assert ".chat-input-bar" in css, "the class this case is named for is gone"
    readers = CC._css_control_border_readers()
    assert not any("chat-input-bar" in r or "input-divider" in r for r in readers), (
        "a hyphenated class with a tag name inside it is being read as a control")


def test_there_is_no_first_paint_mirror_and_the_fallback_is_todays_border():
    """Stated as a rule, because the absence of a mirror is a decision here and
    an omission everywhere else in this file's neighbourhood (`P1-01`)."""
    css = CC._blank(STYLE)
    assert "var(--border-control, var(--border))" in css, (
        "the fallback chain is what makes the missing mirror safe")
    for page in ("index.html", "login.html"):
        text = (ROOT / "static" / page).read_text(encoding="utf-8")
        assert "--border-control" not in text, (
            f"{page} now writes --border-control at first paint; if that is "
            "wanted, this file needs the four-implementation treatment "
            "`tests/test_the_button_clears_the_floor_js.py` gives --on-accent")
    assert "controlBorderFor" in THEME.read_text(encoding="utf-8")


def test_the_audit_passes_on_this_tree():
    result = subprocess.run(
        [sys.executable, str(ROOT / ".pantheon" / "check-contrast.py")],
        capture_output=True, text=True, cwd=str(ROOT), timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "control-boundary border" in result.stdout
    assert "all clear" in result.stdout
