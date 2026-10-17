#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""check-elevation.py — one elevation idiom, four inks, and a derived light arm.

`P1-13`, ruled in `D-2026-10-17-02` §1. The row found elevation was **two**
idioms that do not look alike, and measured the population three times as it
grew: 288 declarations / 209 values in August, 322 / 232 in October, **331 /
236** when the sweep ran. What mattered was not the size but the split:

  * **127** occurrences hard-coded `rgba(0,0,0,α)` inside a shadow, across
    **25** distinct alphas from 0.05 to 0.66 — three of them the same number
    spelled twice (`.38` beside `0.38`, `.4` beside `0.4`, `.28` beside
    `0.28`), which is what a population with no vocabulary looks like;
  * **41** more used `color-mix(in srgb, var(--fg) N%, transparent)` in 14
    spellings — *ink at low alpha*, which is a dark shadow on the 8 light
    palettes and a **light glow** on the other 15, because `--fg` is lighter
    than `--panel` there (`claude` 0.904 against 0.029).

Ruled: elevation is a shadow everywhere, scoped by surface through
`light-dark()` — `B22`'s pattern, keyed off the `color-scheme` the palette
writers already set — with the **dark arm carrying the literal the file was
tuned with**. Ink at low alpha was ruled against because it makes *elevation*
mean two different things depending on the palette.

**The light arm is derived, and the derivation is the interesting part.** A
black overlay at alpha α drops a panel's relative luminance to `Y(1-α)`;
compositing is linear in channel space and relative luminance is a linear
combination of linearised channels, so that is exact and not an approximation.
Matching the **perceptual** step — CIE `L*`, which is uniform where `Y` is not
— on the median light panel against the median dark panel puts the light arm at
**one fifth** of the dark arm: 0.200, 0.206, 0.203 and 0.200 across the four
tiers. The same number four times, so it is held here as one rule rather than
four magic values, and it is also the measurement that explains the smudge: on
a near-white panel the same α removes five times the lightness it removes on a
near-black one.

Matching the *contrast ratio* instead was tried first and is wrong: today's
dark shadows reach only 1.01:1 to 1.08:1 against a near-black panel, so a light
arm matched to that would be invisible. A shadow is a lightness step, not a
boundary, and `1.4.11` has nothing to say about it.

**Four tiers, not 25.** The alphas collapse by nearest neighbour **in log
space**, because a shadow's alpha is perceived as a ratio and not as a distance.
No occurrence moves by more than **1.43×**; the occurrence-weighted mean is
**1.154×**. A linear rule would put 0.12, 0.24 and 0.4 one tier lower — 23
occurrences — and its worst move is **1.71×**.

What this checker does not do: collapse the 236 geometries. Every site keeps
its own offsets and blur, and reducing those to four whole shadows needs eyes.

    python3 .pantheon/check-elevation.py             # verify
    python3 .pantheon/check-elevation.py --report    # the ladder and the census

Exits 0 when no shadow carries ink of its own, the four tokens are present and
spell the derived ladder, and no 26th alpha has appeared.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLE = ROOT / "static" / "style.css"

#: The dark arm of each tier — the literal the stylesheet was tuned with.
TIERS = (0.07, 0.17, 0.31, 0.50)

#: The light arm is this fraction of the dark one, derived in the docstring
#: above and re-derived by `derived_light_ratio()` below.
LIGHT_RATIO = 0.2

#: `P1-13` swept 168 occurrences. A sweep that finds fewer has lost sites to a
#: refactor and should be re-measured, not quietly accepted.
BASELINE_USES = 168

SHADOW_DECL = re.compile(
    r"(?:^|[;{])\s*(?:box-shadow|text-shadow|-webkit-box-shadow)\s*:\s*([^;}]+)", re.M)
OWN_INK = re.compile(r"rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*([0-9.]+)\s*\)")
INK_FORM = re.compile(r"color-mix\(\s*in srgb,\s*var\(--fg\)\s*([0-9.]+)%\s*,\s*transparent\s*\)")
TOKEN_USE = re.compile(r"var\(\s*--shadow-ink-([1-4])\s*\)")
TOKEN_DEF = re.compile(
    r"--shadow-ink-([1-4])\s*:\s*light-dark\(\s*rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*([0-9.]+)\s*\)\s*,"
    r"\s*rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*([0-9.]+)\s*\)\s*\)")


def strip_comments(text: str, path: Path) -> str:
    """The repository's one comment blanker, loaded not reimplemented (`B290`).

    A hand-written `/\\*.*?\\*/` cannot tell a comment from a string, and this
    file's own neighbour shipped that defect and was caught by
    `tests/test_one_comment_blanker.py` the same day.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_elevation_check_specifiers", ROOT / ".pantheon" / "check-specifiers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.strip_comments(text, mode=module.mode_for(path))


def lstar(luminance: float) -> float:
    """CIE `L*` from relative luminance — the perceptually uniform scale."""
    if luminance > 216 / 24389:
        return 116 * luminance ** (1 / 3) - 16
    return 24389 / 27 * luminance


def lightness_step(luminance: float, alpha: float) -> float:
    """How much `L*` a black overlay at `alpha` removes from a panel."""
    return lstar(luminance) - lstar(luminance * (1 - alpha))


def light_arm_for(alpha: float, light_panel: float, dark_panel: float) -> float:
    """The alpha that makes the same `L*` step on a light panel as `alpha` does on a dark one."""
    target = lightness_step(dark_panel, alpha)
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if lightness_step(light_panel, mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def tier_for(alpha: float) -> int:
    """The 1-based tier nearest `alpha` **in log space**.

    A shadow's alpha is perceived as a ratio, so a value between two tiers
    belongs to the one it is the smaller *multiple* away from — the boundaries
    are geometric means (0.109, 0.230, 0.394), not arithmetic ones (0.12, 0.24,
    0.405). Measured over the 26 alphas the sweep found, the two rules disagree
    on three of them — 0.12, 0.24 and 0.4, 23 occurrences — and the linear
    rule's worst move is **1.714×** against this one's 1.429×.
    """
    return min(range(len(TIERS)), key=lambda i: abs(math.log(alpha / TIERS[i]))) + 1


def _panel_luminances() -> tuple:
    """`(median light panel, median dark panel)` over the shipped palettes.

    Read through `check-contrast.py`'s palette reader rather than a second copy
    of it, so a palette added to the product is in this measurement too.
    """
    import importlib.util
    import statistics

    spec = importlib.util.spec_from_file_location(
        "_elevation_check_contrast", ROOT / ".pantheon" / "check-contrast.py")
    module = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["check-contrast", "--imported-by-check-elevation"]
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    finally:
        sys.argv = argv
    light, dark = [], []
    for _, palette in sorted(module.themes().items()):
        panel, fg = palette.get("panel"), palette.get("fg")
        if not (panel and fg):
            continue
        bucket = light if module.luminance(fg) < module.luminance(panel) else dark
        bucket.append(module.luminance(panel))
    return statistics.median(light), statistics.median(dark)


def derived_light_ratio() -> tuple:
    """`(ratios, worst)` — the light arm as a fraction of the dark one, per tier."""
    light_panel, dark_panel = _panel_luminances()
    ratios = [light_arm_for(a, light_panel, dark_panel) / a for a in TIERS]
    worst = max(abs(r - LIGHT_RATIO) / LIGHT_RATIO for r in ratios)
    return ratios, worst


def census() -> dict:
    """What the stylesheet's shadows are made of, counted today."""
    css = strip_comments(STYLE.read_text(encoding="utf-8"), STYLE)
    own_ink, ink_form, token_uses, declarations = [], [], 0, 0
    for match in SHADOW_DECL.finditer(css):
        value = match.group(1)
        declarations += 1
        own_ink.extend(float(a) for a in OWN_INK.findall(value))
        ink_form.extend(float(p) / 100 for p in INK_FORM.findall(value))
        token_uses += len(TOKEN_USE.findall(value))
    return {"declarations": declarations, "own_ink": own_ink,
            "ink_form": ink_form, "token_uses": token_uses}


def token_definitions() -> dict:
    """`{tier: (light arm, dark arm)}` as the stylesheet spells them."""
    css = strip_comments(STYLE.read_text(encoding="utf-8"), STYLE)
    return {int(t): (float(lo), float(hi)) for t, lo, hi in TOKEN_DEF.findall(css)}


def main() -> int:
    report = "--report" in sys.argv
    problems = []
    found = census()
    defined = token_definitions()
    ratios, worst_ratio = derived_light_ratio()

    print(f"elevation — {found['declarations']} shadow declarations, "
          f"{found['token_uses']} reading one of {len(TIERS)} inks")

    for tier, dark in enumerate(TIERS, start=1):
        want_light = round(dark * LIGHT_RATIO, 3)
        if tier not in defined:
            problems.append(f"--shadow-ink-{tier} is not defined as a `light-dark()` of two black alphas")
            continue
        light, got_dark = defined[tier]
        if abs(got_dark - dark) > 1e-9:
            problems.append(
                f"--shadow-ink-{tier}'s dark arm is {got_dark}, not the tuned literal {dark} — "
                f"the 15 dark palettes are no longer pixel-identical, which is the whole "
                f"argument `D-2026-10-17-02` §1 chose this form on")
        if abs(light - want_light) > 1e-9:
            problems.append(
                f"--shadow-ink-{tier}'s light arm is {light}; the derived value is {want_light} "
                f"({LIGHT_RATIO} of {dark})")

    if worst_ratio > 0.05:
        problems.append(
            f"the derivation has moved: matching the L* step now puts the light arm at "
            f"{', '.join(f'{r:.3f}' for r in ratios)} of the dark one, and the ladder is "
            f"written for {LIGHT_RATIO} — the palettes shifted, re-derive the four tokens")

    if found["own_ink"]:
        shown = ", ".join(str(a) for a in sorted(set(found["own_ink"]))[:8])
        problems.append(
            f"{len(found['own_ink'])} shadow(s) hard-code their own ink ({shown}) — use "
            f"`var(--shadow-ink-N)`, which is a dark shadow on every palette instead of a "
            f"grey smudge on the 8 light ones")
    if found["ink_form"]:
        shown = ", ".join(f"{a:.0%}" for a in sorted(set(found["ink_form"]))[:8])
        problems.append(
            f"{len(found['ink_form'])} shadow(s) use `color-mix(in srgb, var(--fg) N%, "
            f"transparent)` ({shown}) — that is ink at low alpha, which glows on the 15 dark "
            f"palettes; `D-2026-10-17-02` §1 ruled elevation is a shadow everywhere")

    if found["token_uses"] < BASELINE_USES:
        problems.append(
            f"{found['token_uses']} shadows read an ink token and {BASELINE_USES} did when "
            f"`P1-13` swept — sites have been lost; re-measure rather than lowering this")

    print(f"  one idiom: {len(found['own_ink'])} own-ink, {len(found['ink_form'])} ink-form "
          f"(0 and 0 is the rule)")
    print(f"  light arm: {LIGHT_RATIO} of the dark arm, derived to within "
          f"{worst_ratio:.1%} across the ladder")

    if report:
        print(f"\n{'tier':>5} {'light':>7} {'dark':>6} {'uses':>5}   derived light arm")
        css = strip_comments(STYLE.read_text(encoding="utf-8"), STYLE)
        for tier, dark in enumerate(TIERS, start=1):
            uses = len(re.findall(rf"var\(\s*--shadow-ink-{tier}\s*\)", css))
            light = defined.get(tier, (float("nan"), float("nan")))[0]
            print(f"{tier:>5} {light:>7} {dark:>6} {uses:>5}   {ratios[tier-1] * dark:.4f}")

    if problems:
        print("\nelevation DRIFTED —")
        for problem in problems:
            print(f"  E {problem}")
        return 1
    print("\nelevation OK — every shadow reads one of four derived inks, and the dark arm "
          "is still the literal the file was tuned with.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
