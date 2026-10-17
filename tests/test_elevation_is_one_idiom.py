# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P1-13` — elevation is a shadow everywhere, and the light arm is derived.

Before this, `static/style.css` carried **two** theme-aware elevation idioms
that do not look alike, plus 25 spellings of a third that was not theme-aware
at all:

  * **127** occurrences hard-coded `rgba(0,0,0,α)` inside a shadow, across 25
    distinct alphas from 0.05 to 0.66 — three of them the same number spelled
    twice (`.38` beside `0.38`, `.4` beside `0.4`, `.28` beside `0.28`);
  * **41** used `color-mix(in srgb, var(--fg) N%, transparent)` in 14
    spellings. That is *ink at low alpha*: a dark shadow on the 8 light
    palettes and a **light glow** on the other 15, because `--fg` is lighter
    than `--panel` there (`claude` 0.904 against 0.029).

`D-2026-10-17-02` §1 ruled for the shadow. A rim light genuinely does read as
elevation on dark UI, which is why this was a question rather than an obvious
call — but ink at low alpha makes *elevation* mean two different things
depending on the palette, so no one sentence describes what a raised surface
looks like in this product.

**The light arm is derived, and that is what this file mostly holds.** A black
overlay at alpha α drops a panel's relative luminance to `Y(1-α)` exactly:
compositing is linear in channel space and relative luminance is a linear
combination of linearised channels. Matching the **perceptual** step — CIE
`L*`, uniform where `Y` is not — on the median light panel against the median
dark panel puts the light arm at **one fifth** of the dark arm, four times
over, to within 3.2%. So the four light arms are `dark / 5` rather than four
separately derived magic values, and the ratio is re-derived from the live
palettes on every CI run.

Matching the *contrast ratio* was tried first and is wrong: today's dark
shadows reach 1.01:1 to 1.08:1 against a near-black panel, so a light arm
matched to that would be invisible. A shadow is a lightness step, not a
boundary — WCAG 1.4.11 has nothing to say about it, and the 4.5826 proof
(`P1-09`) does not apply either.

**What is deliberately not done here.** The 236 distinct shadow *geometries*
are untouched: every site keeps its own offsets and blur, and these tokens are
the shadow's ink. Collapsing geometry to four whole shadows is the other half
of the row and it needs eyes.
"""

from __future__ import annotations

import importlib.util
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STYLE = ROOT / "static" / "style.css"
CHECKER = ROOT / ".pantheon" / "check-elevation.py"


def _checker():
    spec = importlib.util.spec_from_file_location("_check_elevation", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CE = _checker()
CSS = CE.strip_comments(STYLE.read_text(encoding="utf-8"), STYLE)


# ── The idiom ───────────────────────────────────────────────────────────────

def test_no_shadow_carries_its_own_ink():
    """The 127, gone. Driven through the checker's own census so CI and this
    file cannot disagree about what counts as a shadow."""
    found = CE.census()
    assert found["own_ink"] == [], (
        f"{len(found['own_ink'])} shadow(s) still hard-code "
        f"`rgba(0,0,0,α)`: {sorted(set(found['own_ink']))}")


def test_no_shadow_uses_ink_at_low_alpha():
    """The 41, gone — and this is the half that changes pixels, on 15 palettes."""
    found = CE.census()
    assert found["ink_form"] == [], (
        f"{len(found['ink_form'])} shadow(s) still use `color-mix(in srgb, "
        f"var(--fg) N%, transparent)`, which glows on the 15 dark palettes")


def test_the_population_did_not_shrink():
    """Non-vacuity in the direction that matters: a sweep is only green because
    the sites were converted, not because they were deleted."""
    found = CE.census()
    assert found["token_uses"] >= CE.BASELINE_USES, (
        f"{found['token_uses']} shadows read an ink token, {CE.BASELINE_USES} did "
        "when the sweep ran")
    assert found["declarations"] >= 320, (
        f"only {found['declarations']} shadow declarations found; the file had 331")


def test_a_coloured_glow_is_not_elevation_and_was_left_alone():
    """The thing a blind sweep would have broken. Focus rings, error states and
    the cookbook's server tint are shadows painted in `--red`, `--accent`,
    `--color-error` and friends — they are *not* elevation, and converting them
    to a black ink would have turned every focus ring into a drop shadow."""
    coloured = [v for v in re.findall(
        r"(?:^|[;{])\s*box-shadow\s*:\s*([^;}]+)", CSS, re.M)
        if re.search(r"var\(--(red|accent|green|color-|notif|cookbook|hl-|ev-)", v)]
    assert len(coloured) >= 60, (
        f"only {len(coloured)} coloured shadows left — the sweep has eaten the "
        "focus rings")
    for value in coloured:
        assert "--shadow-ink-" not in value or "rgba" not in value


# ── The ladder ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier,dark", list(enumerate(CE.TIERS, start=1)))
def test_the_dark_arm_is_the_literal_the_file_was_tuned_with(tier, dark):
    """The whole safety argument for this form over the other one: the 15 dark
    palettes are pixel-identical because the dark arm is today's value."""
    defined = CE.token_definitions()
    assert tier in defined, f"--shadow-ink-{tier} is not defined"
    assert defined[tier][1] == pytest.approx(dark), (
        f"--shadow-ink-{tier}'s dark arm is {defined[tier][1]}, not {dark}")


@pytest.mark.parametrize("tier,dark", list(enumerate(CE.TIERS, start=1)))
def test_the_light_arm_is_a_fifth_of_the_dark_one(tier, dark):
    defined = CE.token_definitions()
    assert defined[tier][0] == pytest.approx(round(dark * CE.LIGHT_RATIO, 3)), (
        f"--shadow-ink-{tier}'s light arm is {defined[tier][0]}, not "
        f"{round(dark * CE.LIGHT_RATIO, 3)}")


def test_the_fifth_is_derived_from_the_live_palettes_not_chosen():
    """`Law 20`. The ratio is a measurement, so it is measured here rather than
    read out of the stylesheet — add a light palette dark enough to move the
    median and this fails, which is the signal wanted."""
    ratios, worst = CE.derived_light_ratio()
    assert len(ratios) == len(CE.TIERS)
    assert worst <= 0.05, (
        f"matching the L* step now derives {[round(r, 3) for r in ratios]}, and "
        f"the ladder is written for {CE.LIGHT_RATIO} — off by {worst:.1%}")
    # The claim is *one number four times*, so what is held is the spread
    # between the four, not each one rounded — `round(0.206, 2)` is 0.21 and
    # `round(0.200, 2)` is 0.2, which would fail a claim the data supports.
    spread = (max(ratios) - min(ratios)) / (sum(ratios) / len(ratios))
    assert spread <= 0.05, (
        f"the four tiers no longer agree on one ratio: "
        f"{[round(r, 3) for r in ratios]}, spread {spread:.1%} — the ladder is "
        f"written as `dark / 5` for all four and would need four values again")


def test_matching_the_contrast_ratio_would_have_been_invisible():
    """Why the derivation uses `L*` and not contrast — recorded as a failing
    alternative rather than as a sentence, because the sentence is the kind of
    claim that rots (`Law 15`)."""
    light_panel, dark_panel = CE._panel_luminances()

    def ratio(lum, alpha):
        shadowed = lum * (1 - alpha)
        return (max(lum, shadowed) + 0.05) / (min(lum, shadowed) + 0.05)

    for dark in CE.TIERS:
        assert ratio(dark_panel, dark) < 1.1, (
            f"a black shadow at {dark} now reaches {ratio(dark_panel, dark):.3f}:1 "
            "on the median dark panel; it used to be invisible, and the argument "
            "for using L* instead of contrast rests on that")
    # And the contrast-matched light arm would be about a fifth of the L*-matched
    # one, which is the quantified version of "invisible".
    target = ratio(dark_panel, CE.TIERS[2])
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ratio(light_panel, mid) < target else (lo, mid)
    contrast_matched = (lo + hi) / 2
    perceptual = CE.light_arm_for(CE.TIERS[2], light_panel, dark_panel)
    assert contrast_matched < perceptual, (
        "the contrast-matched light arm is no longer the smaller of the two, so "
        "this file's reasoning about which rule to use needs re-reading")


# ── The collapse ────────────────────────────────────────────────────────────

def test_the_tiers_are_nearest_in_log_space_not_linear():
    """A shadow's alpha is perceived as a ratio, so a value sitting between two
    tiers belongs to the one it is the smaller *multiple* away from.

    Measured rather than asserted: with these four tiers the two rules disagree
    on exactly three of the 26 alphas — **0.12, 0.24 and 0.4**, 23 occurrences
    between them, each landing one tier lower under a linear rule — and the
    linear rule's worst move is **1.714×** (0.12 onto 0.07) against log's
    1.429×. The first draft of this case claimed the disagreement was at 0.05
    and 0.18 and it was not: those two land in the same buckets either way, so
    the mutation walked straight past it."""
    straddlers = {0.12: (2, 1), 0.24: (3, 2), 0.4: (4, 3)}
    for alpha, (in_log, in_linear) in straddlers.items():
        assert CE.tier_for(alpha) == in_log, (
            f"{alpha} now lands in tier {CE.tier_for(alpha)}, not {in_log} — "
            f"tier {in_linear} is where a linear rule puts it")
    # The boundaries themselves: geometric means, not arithmetic ones.
    for lower, upper in zip(CE.TIERS, CE.TIERS[1:]):
        geometric = math.sqrt(lower * upper)
        arithmetic = (lower + upper) / 2
        assert geometric < arithmetic
        assert CE.tier_for(geometric * 0.999) < CE.tier_for(geometric * 1.001)


def test_no_occurrence_moved_more_than_the_recorded_bound():
    """The figure `D-2026-10-17-02` §1 records, re-derived from the alphas the
    row measured — so the claim *"nothing moves by more than 1.43×"* is a
    computation and not a memory."""
    measured = {0.05: 1, 0.06: 4, 0.07: 2, 0.1: 3, 0.12: 4, 0.14: 8, 0.15: 2,
                0.16: 2, 0.18: 16, 0.2: 9, 0.22: 6, 0.24: 3, 0.25: 17, 0.28: 4,
                0.3: 23, 0.32: 3, 0.34: 1, 0.35: 14, 0.38: 4, 0.4: 16, 0.42: 3,
                0.45: 7, 0.5: 9, 0.55: 4, 0.6: 2, 0.66: 1}
    assert sum(measured.values()) == CE.BASELINE_USES
    moves = [(max(a / CE.TIERS[CE.tier_for(a) - 1], CE.TIERS[CE.tier_for(a) - 1] / a), n)
             for a, n in measured.items()]
    worst = max(m for m, _ in moves)
    mean = sum(m * n for m, n in moves) / sum(n for _, n in moves)
    assert worst == pytest.approx(1.43, abs=0.005), f"worst move is now {worst:.3f}x"
    assert mean == pytest.approx(1.154, abs=0.002), f"mean move is now {mean:.4f}x"


def test_every_tier_is_actually_used():
    """Four tiers is a claim about the file, not an aspiration. A tier nobody
    reads is a fifth spelling of nothing."""
    uses = Counter(CE.TOKEN_USE.findall(CSS))
    for tier in range(1, len(CE.TIERS) + 1):
        assert uses[str(tier)] > 0, f"--shadow-ink-{tier} is defined and never used"


# ── The wiring ──────────────────────────────────────────────────────────────

def test_light_dark_has_a_color_scheme_to_key_off_before_the_module_boots():
    """`light-dark()` resolves against `color-scheme`, and the tokens sit in
    `:root`. With scripting off entirely the arm has to be `dark`, because the
    dark arm is the literal the file was tuned with."""
    root = CSS.split(":root {", 1)[1].split("\n}", 1)[0]
    assert "color-scheme: dark" in root, (
        "`:root` no longer declares a default `color-scheme`, so with scripting "
        "off `light-dark()` follows the OS and a dark palette gets light shadows")
    theme = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
    assert "setProperty('color-scheme'" in theme, (
        "theme.js no longer sets color-scheme, so a custom palette gets the "
        "wrong arm (`P3-09`)")


def test_the_tokens_are_defined_once():
    """`Law 7`. A second definition in a `:root.light` block would be a fourth
    mirror of the palette (`B21`) and would make `light-dark()` pointless."""
    for tier in range(1, len(CE.TIERS) + 1):
        hits = len(re.findall(rf"--shadow-ink-{tier}\s*:", CSS))
        assert hits == 1, f"--shadow-ink-{tier} is defined {hits} times"


def test_the_checker_passes_on_this_tree():
    result = subprocess.run([sys.executable, str(CHECKER)],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "one idiom: 0 own-ink, 0 ink-form" in result.stdout


def test_the_checker_loads_the_one_comment_blanker():
    """`B290`, for the fifth time in this neighbourhood. A hand-written
    `/\\*.*?\\*/` cannot tell a comment from a string, and the sibling checker
    shipped exactly that and was caught the same day."""
    source = CHECKER.read_text(encoding="utf-8")
    assert "check-specifiers.py" in source, (
        "the checker no longer loads the repository's blanker")
    assert "re.sub(r\"/\\*" not in source and "/\\*.*?\\*/" not in source, (
        "the checker has grown its own comment stripper")
