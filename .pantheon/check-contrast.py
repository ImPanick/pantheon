#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""check-contrast.py — every theme clears the WCAG floor, measured not asserted.

`P1-09`, `P10-04`. The phase plan asked for *"a contrast audit across all 16
themes with the guard from P1-09 enforcing it"*, and the first thing measuring
it says is that **there are no longer 16 themes**: `static/js/theme.js` now
defines more, so a row that names a count was going to rot the moment somebody
added a palette. This reads `THEMES` and audits whatever is in it.

WCAG 2.x, which is one formula and worth writing down rather than importing:
relative luminance is the sRGB channel values linearised by
`c <= 0.04045 ? c/12.92 : ((c+0.055)/1.055) ** 2.4`, weighted
`0.2126 R + 0.7152 G + 0.0722 B`; contrast is `(Lmax + 0.05) / (Lmin + 0.05)`.
Floors: **4.5:1** for body text, **3:1** for large text and for UI component
boundaries.

What it checks, and each pair is a thing a person actually looks at:

  A. `fg` on `panel` — body text in a panel. A theme that fails this cannot be
     fixed by any other row, because no foreground token reaches the floor;
     that is `B15`, and those themes are reported as `B15` rather than as new
     failures.
  B. `fg` on `bg` — body text on the page.
  C. `#fff` on the accent — the hard-coded white that `P1-08` measured on
     `.send-btn`, kept because 19 rules still do it.
  D. the accent on `panel` — accent-coloured text, which `P1-08` measured at
     187 `color:` declarations.
  E. the worst case a *computed* foreground can reach, over every colour that
     exists rather than over the palettes that happen to ship — **4.5826:1**,
     which is `P1-09`'s whole answer: the guard that row asks for has no case
     left to catch. See `worst_possible_on_accent()`.

Exit 1 on a regression against the recorded baseline, 0 otherwise. The baseline
is in this file rather than in a side-car, so a palette added without reading
it cannot quietly move the floor.
"""
from __future__ import annotations

import json
import math as _math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEME_JS = ROOT / "static" / "js" / "theme.js"

BODY_FLOOR = 4.5
LARGE_FLOOR = 3.0

#: Themes whose own `fg` misses the body floor against their own `panel`, so no
#: foreground choice reaches it and the fix is a different design rather than a
#: different colour. `B15` owns these; they are not this check's failures.
B15_THEMES = {"cute", "retrowave"}

#: `advanced` is not a palette — it is the custom-theme slot. Skipped by name.
NOT_A_PALETTE = {"advanced"}


def _srgb_channel(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (0.2126 * _srgb_channel(r)
            + 0.7152 * _srgb_channel(g)
            + 0.0722 * _srgb_channel(b))


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def themes() -> dict:
    """`THEMES` from `static/js/theme.js`, read rather than duplicated."""
    src = THEME_JS.read_text(encoding="utf-8")
    start = src.index("export const THEMES = {")
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                block = src[i:j + 1]
                break
    out = {}
    for m in re.finditer(r"(?m)^\s{2}([a-z][a-z0-9_]*):\s*\{(.*?)\}(?:,|\s*$)", block, re.S):
        name, body = m.group(1), m.group(2)
        if name in NOT_A_PALETTE:
            continue
        pal = dict(re.findall(r"(\w+)\s*:\s*'(#[0-9a-fA-F]{3,8})'", body))
        if {"bg", "fg", "panel"} <= set(pal):
            out[name] = pal
    return out


def audit() -> dict:
    rows = {}
    for name, pal in sorted(themes().items()):
        accent = pal.get("red", pal["fg"])
        rows[name] = {
            "fg_on_panel": round(contrast(pal["fg"], pal["panel"]), 2),
            "fg_on_bg": round(contrast(pal["fg"], pal["bg"]), 2),
            "white_on_accent": round(contrast("#ffffff", accent), 2),
            "accent_on_panel": round(contrast(accent, pal["panel"]), 2),
        }
    return rows


#: `P1-08`. Button designs, each evaluated on every palette. A design is
#: offerable only if its text clears the body floor on **all** of them, which is
#: `D-2026-09-08-01`'s *"every option must clear 4.5:1 on all sixteen by
#: construction"* turned into something a script can refuse.
def button_designs() -> dict:
    def mix(a: str, b: str, t: float) -> str:
        ah, bh = a.lstrip("#"), b.lstrip("#")
        return "#%02x%02x%02x" % tuple(
            round(int(ah[i:i + 2], 16) * t + int(bh[i:i + 2], 16) * (1 - t))
            for i in (0, 2, 4))

    out = {}
    for name, p in sorted(themes().items()):
        accent = p.get("red", p["fg"])
        on_accent = ("#000000"
                     if contrast("#000000", accent) >= contrast("#ffffff", accent)
                     else "#ffffff")
        out[name] = {
            "filled": round(contrast(on_accent, accent), 2),
            "filled_white_legacy": round(contrast("#ffffff", accent), 2),
            "outline": round(contrast(p["fg"], p["panel"]), 2),
            "tinted": round(contrast(p["fg"], mix(accent, p["panel"], 0.12)), 2),
            "ghost": round(contrast(accent, p["panel"]), 2),
        }
    return out


#: The designs offered to the person, and today there is exactly **one**.
#:
#: `D-2026-09-08-01` requires every offered option to clear the floor on every
#: palette by construction, and measurement says only `filled` does — with a
#: computed foreground it reaches 5.18:1 at worst (`claude`) and clears even
#: `cute` (7.84) and `retrowave` (5.48), the two palettes `B15` records as
#: having no legible foreground against their own panel.
OFFERABLE = ("filled",)

#: Designs that clear the floor on every palette **except** the `B15` two, and
#: fail there only because those palettes' own `fg` misses the floor against
#: their own `panel`. They are not broken designs and they are not offerable
#: either; they are waiting on `B15`. Keeping them separate from the genuinely
#: failing designs below is the useful distinction: fixing two palettes' `fg`
#: turns one choice into three.
BLOCKED_ON_B15 = ("outline", "tinted")


#: `P1-09`. **The guard the row asks for cannot fire, and that is the finding.**
#:
#: The row asks for *"a contrast guard inside `generateHarmonyColors()` and
#: `applyColors()` (~15 lines) so every future custom theme clears the floor
#: too"*. A guard implies a case left to catch. There is none, and it is
#: provable rather than sampled.
#:
#: Write `x = L + 0.05` on `[0.05, 1.05]`. Contrast against black is
#: `x / 0.05 = 20x`, rising; against white it is `1.05 / x`, falling. The
#: better of the two is `max(20x, 1.05/x)`, and the smallest that maximum can
#: be is where the two branches cross — `20x = 1.05/x`, so `x = sqrt(0.0525)`
#: and the ratio is **4.5826:1**.
#:
#: So a foreground chosen as the better of black and white clears the 4.5:1
#: body floor on *every colour that exists*. Not on the 23 shipped palettes, and
#: not on the 6,912 palettes `generateHarmonyColors()` can emit — on all of
#: them, because there is no accent for which it fails. A guard would be dead
#: code, and a theme editor that refuses a colour on contrast grounds would be
#: refusing one that passes.
#:
#: The margin is thin on purpose-worth-knowing grounds: **1.8%** above the
#: floor, at `L = 0.1791` — `#ba40c0` is one such colour. That is why this is
#: computed and asserted rather than remembered.
def worst_possible_on_accent() -> float:
    """The floor of `max(contrast(black, c), contrast(white, c))` over all `c`."""
    x = 0.0525 ** 0.5
    return 20.0 * x


def on_accent_for(accent: str) -> str:
    """The same choice `onAccentFor()` makes in `static/js/theme.js`.

    Black wins a tie, exactly as both first-paint mirrors do.
    """
    return ("#000000"
            if contrast("#000000", accent) >= contrast("#ffffff", accent)
            else "#ffffff")


#: `B1404`. The control-boundary border, as `controlBorderFor()` in
#: `static/js/theme.js` computes it. One implementation in each language and a
#: test that runs both over every palette — the same arrangement `P1-08` uses
#: for `--on-accent`, and for the same reason: a formula copied is a formula
#: that rots.
def control_border_for(border: str, panel: str, fg: str, floor: float = LARGE_FLOOR) -> str:
    """The least mix of `fg` into `border` that clears `floor` against `panel`."""
    def rgb(value: str):
        digits = str(value or "").lstrip("#")
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        if len(digits) != 6:
            return None
        return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))

    b, f = rgb(border), rgb(fg)
    if not b or not f or not panel:
        return border
    # `floor(v + 0.5)`, not `round(v)`: a channel can land exactly on `.5`
    # (`video` does, at 15% and again at 55%), and Python rounds a tie to the
    # even number while `Math.round` in the browser rounds it up. The browser
    # is what paints, so the audit rounds the browser's way — otherwise the two
    # derivations disagree by one hex digit on the palettes that hit a tie, and
    # `test_the_module_and_the_audit_compute_the_same_border` is what caught it.
    half_up = lambda v: _math.floor(v + 0.5)
    for pct in range(0, 101):
        t = pct / 100
        mixed = "#" + "".join(
            f"{max(0, min(255, half_up(f[i] * t + b[i] * (1 - t)))):02x}" for i in range(3))
        if contrast(mixed, panel) >= floor:
            return mixed
    return fg


CONTROL_TAGS = {"input", "textarea", "select", "button"}


def _interactive_classes() -> set:
    """Every class the shipped markup puts on something focusable."""
    import re as _re

    html = _blank(ROOT / "static" / "index.html")
    out = set()
    for tag_match in _re.finditer(r"<(\w+)([^>]*)>", html):
        tag, attrs = tag_match.group(1).lower(), tag_match.group(2)
        if tag not in ("input", "textarea", "select", "button", "a") \
                and "tabindex" not in attrs and "contenteditable" not in attrs:
            continue
        found = _re.search(r'class="([^"]*)"', attrs)
        if found:
            out.update(c for c in found.group(1).split() if c)
    return out


def _is_control_selector(selector: str, interactive_classes: set) -> bool:
    """Whether `selector` paints a boundary WCAG 1.4.11 asks 3:1 of.

    One rule, one place (`Law 7`): the reader list and the census both ask this,
    and when they asked it separately the census was 39% wrong. A bare
    **element tag**, not a word inside a class name — `\b(input|…)\b` matched
    `.chat-input-bar` and `.input-divider`, because `-` is a word boundary in a
    regex. Classes, ids, attributes and pseudos are stripped first, so what is
    left is the element part of each compound selector.
    """
    import re as _re

    bare = _re.sub(r"[.#][A-Za-z0-9_-]+", " ", selector)
    bare = _re.sub(r"\[[^\]]*\]", " ", bare)
    bare = _re.sub(r"::?[A-Za-z-]+(\([^)]*\))?", " ", bare)
    tags = {t for t in _re.split(r"[\s>+~,]+", bare) if t}
    classes = set(_re.findall(r"\.([A-Za-z0-9_-]+)", selector))
    return (bool(tags & CONTROL_TAGS)
            or bool(classes & interactive_classes)
            or ":focus" in selector
            or "[contenteditable" in selector)


def _css_control_border_readers() -> list:
    """Rules that read `--border` on a selector that names an interactive element.

    A selector counts as a control when it names an `input`, `textarea`,
    `select` or `button` **tag**, carries a class the shipped markup puts on a
    focusable element, or mentions `:focus` or `[contenteditable]`. WCAG 1.4.11
    asks 3:1 of those boundaries and nothing of panel edges, card outlines,
    dividers and table rules.

    The census itself is **not written down here**. `B1404` first shipped one in
    this docstring and it was wrong twice over — inflated 39% by the hyphen bug
    below, then stale the moment the sweep ran — so the audit prints the split
    on every run instead (`_css_border_read_census`) and this says only how the
    two buckets are told apart. A figure in a comment is a figure nobody
    recomputes.

    This is a **candidate** split and says so: it reads the selector and the
    markup's focusable classes, so a card focusable only at runtime lands in the
    wrong bucket. It is a list to walk, not a verdict.
    """
    import re as _re

    css = _blank(ROOT / "static" / "style.css")
    interactive_classes = _interactive_classes()
    out = []
    for rule in _re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors, body = rule.group(1), rule.group(2)
        if "--border" not in body:
            continue
        # The converted form **contains** the plain one —
        # `var(--border-control, var(--border))` — so it has to be taken out
        # before asking whether a plain read is left. Without this the audit
        # counts every converted rule as still unconverted, which is how the
        # first sweep appeared to have done nothing.
        bare = body.replace("var(--border-control, var(--border))", "")
        bare = _re.sub(r"var\(\s*--border-control\s*,", "", bare)
        reads_plain = bool(_re.search(r"var\(\s*--border\s*[,)]", bare))
        for selector in selectors.split(","):
            selector = selector.strip().split("\n")[-1].strip()
            if not selector:
                continue
            control = _is_control_selector(selector, interactive_classes)
            if control and reads_plain:
                out.append(selector[:70])
    return out


def _css_border_read_census() -> tuple:
    """`(control, decorative)` border reads in the stylesheet, counted today.

    Counted over the **converted** spelling as well as the plain one, so the
    total does not move when a read is swept from `var(--border)` to
    `var(--border-control, var(--border))`. Without that normalisation the
    converted form counts twice — it contains the plain one — and the census
    appears to grow every time a control is fixed.
    """
    import re as _re

    MARK = "\u0000border-read\u0000"
    css = _blank(ROOT / "static" / "style.css")
    interactive = _interactive_classes()
    control = decorative = 0
    for rule in _re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors, body = rule.group(1), rule.group(2)
        norm = body.replace("var(--border-control, var(--border))", MARK)
        norm = _re.sub(r"var\(\s*--border\s*[,)]", MARK, norm)
        reads = norm.count(MARK)
        if not reads:
            continue
        for selector in selectors.split(","):
            selector = selector.strip().split("\n")[-1].strip()
            if not selector:
                continue
            if _is_control_selector(selector, interactive):
                control += reads
            else:
                decorative += reads
    return control, decorative


def _blank(path):
    """The repository's one comment blanker, loaded not reimplemented (`B290`)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_contrast_check_specifiers", ROOT / ".pantheon" / "check-specifiers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.strip_comments(path.read_text(encoding="utf-8"),
                                 mode=module.mode_for(path))


def _css_white_on_accent() -> list:
    """Rules that still paint a hard-coded white on an accent background.

    `P1-08` measured 19 and this found **46** — the surface grew between the
    2026-08-30 measurement and now, which is the argument for checking it in CI
    rather than counting it in a row.
    """
    import re

    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    accent = re.compile(r"(--red|--accent|--send-btn-bg|--toggle-active|--brand-color)\b")
    white = re.compile(r"color:\s*(?:#fff(?:fff)?|white)\b", re.I)
    bg = re.compile(r"(?:^|[;{]|\s)(background(?:-color)?)\s*:\s*([^;}]+)", re.I)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        body = m.group(2)
        if not white.search(body):
            continue
        found = bg.search(body)
        if found and accent.search(found.group(2)):
            out.append(m.group(1).strip().split("\n")[-1].strip()[:70])
    return out


def main() -> int:
    rows = audit()
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    problems, b15, notes = [], [], []
    for name, r in rows.items():
        if r["fg_on_panel"] < BODY_FLOOR:
            (b15 if name in B15_THEMES else problems).append(
                f"{name}: body text {r['fg_on_panel']}:1 on its own panel")
        if r["white_on_accent"] < BODY_FLOOR:
            notes.append(f"{name}: #fff on accent {r['white_on_accent']}:1")
        if r["accent_on_panel"] < BODY_FLOOR:
            notes.append(f"{name}: accent text {r['accent_on_panel']}:1 on panel")

    width = max(len(n) for n in rows)
    print(f"contrast audit — {len(rows)} themes, WCAG 2.x, body floor {BODY_FLOOR}:1\n")
    print(f"  {'theme':<{width}}  fg/panel  fg/bg  #fff/accent  accent/panel")
    for name, r in rows.items():
        flag = "  B15" if name in B15_THEMES else ""
        print(f"  {name:<{width}}  {r['fg_on_panel']:>8}  {r['fg_on_bg']:>5}  "
              f"{r['white_on_accent']:>11}  {r['accent_on_panel']:>12}{flag}")

    print(f"\n{len(notes)} accent findings (P1-08's population):")
    for n in notes:
        print(f"  · {n}")
    if b15:
        print(f"\n{len(b15)} theme(s) owned by B15 — no foreground reaches the floor:")
        for n in b15:
            print(f"  ~ {n}")
    # ── P1-08 / P1-09: which button designs may be offered at all ─────────
    designs = button_designs()
    width2 = max(len(n) for n in designs)
    keys = list(next(iter(designs.values())).keys())
    print(f"\nbutton designs — a design is offerable only if it clears "
          f"{BODY_FLOOR}:1 on every palette\n")
    print("  " + "design".ljust(22) + "min   worst theme   verdict")
    for k in keys:
        vals = {t: designs[t][k] for t in designs}
        worst = min(vals, key=lambda t: vals[t])
        fails = sorted(t for t, v in vals.items() if v < BODY_FLOOR)
        non_b15_fails = [t for t in fails if t not in B15_THEMES]
        if k in OFFERABLE:
            verdict = "OFFERED" if not fails else f"REGRESSED — fails on {', '.join(fails)}"
            if fails:
                problems.append(f"offered button design {k!r} fails on: {', '.join(fails)}")
        elif k in BLOCKED_ON_B15:
            if non_b15_fails:
                verdict = f"REGRESSED — now fails outside B15 on {', '.join(non_b15_fails)}"
                problems.append(
                    f"button design {k!r} was blocked only by B15 and now fails on "
                    f"{', '.join(non_b15_fails)} as well")
            elif fails:
                verdict = f"blocked on B15 ({', '.join(fails)})"
            else:
                verdict = "B15 is fixed — this can be offered now"
                notes.append(
                    f"button design {k!r} now clears every palette; B15 appears "
                    f"fixed, so add it to OFFERABLE")
        else:
            verdict = f"not offered ({len(fails)} fail)" if fails else "not offered (passes)"
        print(f"  {k:<22}{vals[worst]:>5.2f}  {worst:<13} {verdict}")

    # `filled` is the only design that reaches the floor on the B15 themes too,
    # which is why it is the default. If that stops being true, say so.
    for t in sorted(B15_THEMES):
        if designs[t]["filled"] < BODY_FLOOR:
            problems.append(
                f"the filled button no longer clears the floor on {t} "
                f"({designs[t]['filled']}:1) — B15 has no fix left")

    # `P1-09`. The reason there is no guard, stated as a number every run.
    floor = worst_possible_on_accent()
    print(f"\ncomputed foreground, worst case over every colour that exists: "
          f"{floor:.4f}:1 (body floor {BODY_FLOOR}:1)")
    if floor < BODY_FLOOR:
        problems.append(
            f"the arithmetic behind P1-09 has changed: the best of black and "
            f"white now bottoms out at {floor:.4f}:1, under the {BODY_FLOOR}:1 "
            f"floor — a guard inside applyColors() is needed after all")

    # `B1404`. The control-boundary border, and the two things that can go
    # wrong with it: the derivation stops clearing the floor on a palette, or a
    # control goes back to reading the decorative `--border`.
    control_fails = []
    for name, palette in sorted(themes().items()):
        border, panel, fg = palette.get("border"), palette.get("panel"), palette.get("fg")
        if not (border and panel and fg):
            continue
        value = control_border_for(border, panel, fg)
        ratio = round(contrast(value, panel), 2)
        if ratio < LARGE_FLOOR:
            control_fails.append(f"{name}: control border {value} only reaches {ratio}:1")
    print(f"\ncontrol-boundary border — {len(themes())} palettes, "
          f"{LARGE_FLOOR}:1 against their own panel: "
          f"{'all clear' if not control_fails else f'{len(control_fails)} fail'}")
    if control_fails:
        problems.extend(control_fails)

    control_reads, decorative_reads = _css_border_read_census()
    print(f"  border reads in the stylesheet: {control_reads} on a control "
          f"boundary, {decorative_reads} decorative "
          f"({control_reads + decorative_reads} total)")

    plain = _css_control_border_readers()
    print(f"controls still reading the decorative `--border`: {len(plain)} selector(s)")
    for selector in plain[:10]:
        print(f"  E {selector}")
    if plain:
        problems.append(
            f"{len(plain)} control-boundary selector(s) read `var(--border)`, which "
            f"misses {LARGE_FLOOR}:1 on 22 of 23 palettes; use "
            f"`var(--border-control, var(--border))`")

    stray = _css_white_on_accent()
    print(f"\nhard-coded white on an accent background: {len(stray)} rule(s)")
    for sel in stray[:10]:
        print(f"  E {sel}")
    if stray:
        problems.append(
            f"{len(stray)} CSS rule(s) paint a hard-coded white on an accent "
            f"background; use var(--on-accent, #fff)")

    if problems:
        print(f"\ncontrast FAILED — {len(problems)} problem(s):")
        for p in problems:
            print(f"  E {p}")
        return 1
    print("\ncontrast OK — every palette's body text clears the floor or is B15's, "
          f"all {len(OFFERABLE)} offered button designs clear it everywhere, and no "
          "rule paints a hard-coded white on an accent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
