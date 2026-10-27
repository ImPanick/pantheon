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
B15_THEMES: set = set()   # `B390` (`D-2026-10-26-01` §13) retired it: both clear now

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
#: Empty since `B390` (`D-2026-10-26-01` §13) moved `cute` and `retrowave` over
#: the floor: `outline` now clears every palette (offering it is the redesign's
#: call, after the owner's *system and function first*), and `tinted` fails on
#: those two on its own account (4.05).
BLOCKED_ON_B15: tuple = ()


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


#: `B1408`. The alpha below which text mixed toward `transparent` misses 4.5:1
#: on at least one shipped palette, measured over the 21 that are not `B15`'s.
#: It is this high because mixing toward transparent lets the **background**
#: through: at 80% the worst palette (`light`) still only reaches 4.36:1.
TRANSPARENT_TEXT_FLOOR_PCT = 82.0

#: The population as it stands. A ratchet (`P3-20`): it was 191 when the rule
#: was written, and **exactly** the count then, not one above it — a ratchet
#: with slack in it is a ratchet that ratchets nothing.
#:
#: 191 -> 6 (2026-10-27, `B1408`). 185 moved onto the ladder that keeps their
#: order and clears the floor (`LADDER_IDIOM`); the six left are the
#: decoration `DECORATION_TRANSPARENT_TEXT` records, and nothing else may be.
BASELINE_TRANSPARENT_TEXT = 6

#: `B1408`. What the 185 became: `color-mix(in oklab, var(--fg) N%,
#: var(--fg-muted))`. Every rung of it lies between `--fg-muted` and `--fg`,
#: both pinned over 4.5:1 against `--panel` and `--bg` on every palette
#: (`P1-03`, `B1486`), and interpolated in OKLab — where lightness moves
#: monotonically between the two — rather than in sRGB, where `retrowave`'s
#: red `--fg` dipped the middle rungs to 4.44:1. The de-emphasis ladder keeps
#: its order (a lower N is still the quieter line); what it loses is the
#: rungs under the floor. `_ladder_failures()` measures every N the sheet
#: uses, on every palette, each time this runs.
LADDER_IDIOM = re.compile(
    r"color-mix\(\s*in oklab,\s*var\(--fg\)\s*([0-9.]+)%\s*,\s*var\(--fg-muted\)\s*\)")

#: `B1408`'s `Verify:` — each surviving transparent mix recorded as
#: decoration, with why; its measurement is printed beside it every run
#: (`_transparent_worst`), not copied here (`Law 6`).
DECORATION_TRANSPARENT_TEXT = {
    ".scenery-olympus": "the welcome screen's ASCII scenery, a picture behind the text",
    ".scenery-temple": "the same scenery's second layer",
    ".ghost-text-overlay .ghost-suggestion": "ghost text: an inline suggestion that must read as not yet typed",
    ".model-picker-list .mp-fav-dot": "the favourite star at rest, a hover reveal (it rises to 68% on hover and focus)",
    ".vis-icon": "an icon beside the label that names the row",
    ".hwfit-fit-dot": "a fit dot whose meaning is the row's text beside it",
}

#: `B1408`'s other half: the same arithmetic wearing `opacity:` — the element
#: and everything in it let the background through. Counted, not swept: an
#: opacity dims icon buttons, hover reveals, disabled controls and pictures as
#: well as text, and telling which is which needs eyes. Scope (`Law 5`):
#: `opacity:` declarations with a value above 0 and under 0.82 in
#: `static/style.css`, comments blanked. 0 is hidden, not dim; 0.82 is the
#: alpha the transparent-mix rule found nothing under clears 4.5:1 with.
#: It may fall; it may not rise.
#:
#: 965 -> 407 (2026-10-27, `B1577`). 558 rules that dimmed **text** by
#: opacity moved onto the ladder at the same N (`opacity: 0.6` became
#: `color-mix(in oklab, var(--fg) 60%, var(--fg-muted))`, or lost the opacity
#: where the colour was already `--fg-muted`), and the states that lifted them
#: (`:hover`, `.active`, a context at full opacity) set the colour they now
#: lift to. The 407 left are not text a person reads at rest: 41 inside
#: `@keyframes`, the disabled, off, done, paused, dragging and loading states
#: of whole controls and cards (their dimming is the state), icons, dots,
#: separators, scenery and previews, hover-revealed controls whose own state
#: is a hue (`.cookbook-gpu-btn`, `.gallery-tag-x`, `.agent-tool-output-copy`),
#: and text in a hue (`--red`, `--accent`, success, syntax colours), which a
#: rung of `--fg` would recolour.
BASELINE_OPACITY_DIMMING = 407


def _css_transparent_text() -> list:
    """`color:` declarations that paint text by mixing a token toward transparent.

    `B1408`. `--fg-muted` mixes toward `--color-muted`, an **opaque** colour,
    which is why `P1-03` could pin it at 4.5:1 on fourteen palettes. Mixing
    toward `transparent` instead lets the background through, so the result is
    not a dimmer foreground — it is a foreground partly replaced by whatever is
    behind it, and no alpha under 82% clears the body floor anywhere.

    Found while adding a confidence label for `P13-01`: it shipped at 40%,
    which measures **1.90:1** on `light`. The two pills beside it, written by
    `P13-15`, are at 45% and 55% and fail the same way — and this audit could
    not see any of them, because everything else it checks is a palette token
    against a surface and these are arbitrary rules with an alpha in them.

    Reported as a count rather than a list, and ratcheted rather than failed:
    sweeping 192 declarations onto `--fg-muted` flattens a 30-step de-emphasis
    ladder that somebody built on purpose, and that needs a person looking at
    screens. What this stops is the ladder growing a 31st step.
    """
    import re as _re

    css = _blank(ROOT / "static" / "style.css")
    out = []
    pattern = _re.compile(
        r"(?:^|[;{])\s*color\s*:\s*color-mix\(\s*in srgb,\s*var\(--([a-z0-9-]+)\)"
        r"\s*([0-9.]+)%\s*,\s*transparent\s*\)", _re.M)
    for match in pattern.finditer(css):
        token, pct = match.group(1), float(match.group(2))
        if pct < TRANSPARENT_TEXT_FLOOR_PCT:
            out.append((token, pct))
    return out


def _css_transparent_text_sites() -> list:
    """`(selector, pct)` for every declaration `_css_transparent_text` counts —
    the rule's selector, so the decoration register can name it."""
    import re as _re

    css = _blank(ROOT / "static" / "style.css")
    out = []
    pattern = _re.compile(
        r"(?:^|[;{])\s*color\s*:\s*color-mix\(\s*in srgb,\s*var\(--([a-z0-9-]+)\)"
        r"\s*([0-9.]+)%\s*,\s*transparent\s*\)", _re.M)
    for match in pattern.finditer(css):
        pct = float(match.group(2))
        if pct >= TRANSPARENT_TEXT_FLOOR_PCT:
            continue
        brace = css.rfind("{", 0, match.start(1))
        selector = " ".join(css[css.rfind("}", 0, brace) + 1:brace].split())
        out.append((selector, pct))
    return out


def _mix_srgb(a: str, b: str, t: float) -> str:
    ah, bh = a.lstrip("#"), b.lstrip("#")
    ah = ah if len(ah) == 6 else "".join(c * 2 for c in ah)
    bh = bh if len(bh) == 6 else "".join(c * 2 for c in bh)
    return "#%02x%02x%02x" % tuple(
        round(int(ah[i:i + 2], 16) * t + int(bh[i:i + 2], 16) * (1 - t)) for i in (0, 2, 4))


def _oklab(hex_colour: str) -> tuple:
    h = hex_colour.lstrip("#")
    r, g, b = (_srgb_channel(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    lms = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
           0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
           0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    l_, m_, s_ = (x ** (1 / 3) for x in lms)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _from_oklab(lab: tuple) -> str:
    L, a, b = lab
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
           -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
           -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)

    def enc(c):
        c = max(0.0, min(1.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return "#%02x%02x%02x" % tuple(round(enc(c) * 255) for c in rgb)


def fg_muted(palette: dict) -> str:
    """`--fg-muted` as `:root` resolves it on `palette`: 30% `--fg` through the
    scoped pivot `--color-muted` (`B1486`), whose arm is the page's
    `color-scheme` (`theme.js` `_isLightBackground`, luminance over 0.5)."""
    pivot = "#747474" if luminance(palette["bg"]) > 0.5 else "#949494"
    return _mix_srgb(palette["fg"], pivot, 0.30)


def ladder_rung(palette: dict, pct: float) -> str:
    """`LADDER_IDIOM` at `pct` on `palette`, interpolated in OKLab as the
    browser does."""
    a, b = _oklab(palette["fg"]), _oklab(fg_muted(palette))
    t = pct / 100.0
    return _from_oklab(tuple(x * t + y * (1 - t) for x, y in zip(a, b)))


#: `B1575`. Pages that link no stylesheet and declare the muted pivot
#: themselves, so their rungs are measured with the sheet's and their copy of
#: the declarations is held equal to the sheet's (`_mirror_drift`).
LADDER_PAGES = ("static/login.html",)

#: The `:root` declarations such a page copies: `fg_muted()` and
#: `ladder_rung()` model `style.css`'s, so a copy that drifted would be
#: measured as something it is not.
MIRRORED_TOKENS = ("--color-muted", "--fg-muted", "--color-error")


def _root_declarations(text: str) -> dict:
    """`{token: value}` from the first `:root { … }` block in `text`."""
    match = re.search(r":root\s*\{(.*?)\}", text, re.S)
    out = {}
    if match:
        for decl in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", match.group(1)):
            out[decl.group(1)] = " ".join(decl.group(2).split())
    return out


def _mirror_drift() -> list:
    """`B1575`. Each `LADDER_PAGES` copy of a `MIRRORED_TOKENS` declaration
    that is missing or differs from `static/style.css`'s `:root`."""
    sheet = _root_declarations(_blank(ROOT / "static" / "style.css"))
    out = []
    for rel in LADDER_PAGES:
        page = _root_declarations(_blank(ROOT / rel))
        for token in MIRRORED_TOKENS:
            if page.get(token) != sheet.get(token):
                out.append(f"{rel}: {token} is {page.get(token)!r}, style.css has {sheet.get(token)!r}")
    return out


def _ladder_failures() -> tuple:
    """`(rungs, failures)`: every N the sheet — and each `LADDER_PAGES` page
    (`B1575`) — writes in `LADDER_IDIOM`, and each palette on which that rung
    misses 4.5:1 against `--panel` or `--bg`."""
    css = _blank(ROOT / "static" / "style.css")
    css += "\n".join(_blank(ROOT / rel) for rel in LADDER_PAGES)
    rungs = sorted({float(m.group(1)) for m in LADDER_IDIOM.finditer(css)})
    failures = []
    for name, palette in sorted(themes().items()):
        for pct in rungs:
            colour = ladder_rung(palette, pct)
            worst = min(contrast(colour, palette["panel"]), contrast(colour, palette["bg"]))
            if worst < BODY_FLOOR:
                failures.append(f"{name}: the {pct:g}% rung is {colour}, {worst:.2f}:1")
    return rungs, failures


def _transparent_worst(pct: float) -> tuple:
    """The worst a `pct`% mix toward transparent reads over `--panel` on any
    palette — what a decoration entry is recorded with."""
    worst = None
    for name, palette in sorted(themes().items()):
        ratio = contrast(_mix_srgb(palette["fg"], palette["panel"], pct / 100.0), palette["panel"])
        if worst is None or ratio < worst[0]:
            worst = (ratio, name)
    return worst


#: `B1408`. Pages that do not load `style.css` and so have no `--fg-muted`
#: to build the ladder from: the whirlpool sandbox is a developer page.
#: `B1575` took the sign-in page off this list: it declares the pivot itself
#: (`LADDER_PAGES`), its text is on the ladder, and it is scanned like any page.
_INLINE_SCAN_EXEMPT = {"static/whirlpool-variants.html"}


def _inline_transparent_text() -> list:
    """`(file, pct)` for inline `color:` mixes toward transparent under the
    floor in `static/**/*.js` (outside `static/lib/`) and `static/*.html` —
    the same defect `_css_transparent_text` counts, written in a `style=`.
    `B1408` moved the 36 it found onto the ladder; this keeps it at none."""
    out = []
    pattern = re.compile(r"color:\s*color-mix\(in srgb,\s*var\(--fg\)\s*([0-9.]+)%,\s*transparent\)")
    paths = [p for p in (ROOT / "static").rglob("*.js") if "static/lib/" not in p.as_posix()]
    paths += sorted((ROOT / "static").glob("*.html"))
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if rel in _INLINE_SCAN_EXEMPT:
            continue
        for m in pattern.finditer(path.read_text(encoding="utf-8", errors="replace")):
            if float(m.group(1)) < TRANSPARENT_TEXT_FLOOR_PCT:
                out.append((rel, float(m.group(1))))
    return out


def _css_opacity_dimming() -> int:
    """`opacity:` declarations above 0 and under 0.82 (`BASELINE_OPACITY_DIMMING`)."""
    css = _blank(ROOT / "static" / "style.css")
    count = 0
    for m in re.finditer(r"(?:^|[;{])\s*opacity\s*:\s*([0-9]*\.?[0-9]+)\s*(?:!important)?\s*(?=[;}])",
                         css, re.M):
        if 0 < float(m.group(1)) < TRANSPARENT_TEXT_FLOOR_PCT / 100:
            count += 1
    return count


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

    thin_text = _css_transparent_text()
    print(f"\ntext mixed toward transparent under {TRANSPARENT_TEXT_FLOOR_PCT:g}%: "
          f"{len(thin_text)} declaration(s) (`B1408`, ratchet at "
          f"{BASELINE_TRANSPARENT_TEXT})")
    if len(thin_text) > BASELINE_TRANSPARENT_TEXT:
        fresh = sorted({pct for _t, pct in thin_text})
        problems.append(
            f"{len(thin_text)} `color:` declarations mix a token toward "
            f"`transparent` below {TRANSPARENT_TEXT_FLOOR_PCT:g}%, and "
            f"{BASELINE_TRANSPARENT_TEXT} is the recorded population — a new one "
            f"has been added. Mixing text toward transparent lets the background "
            f"through and misses 4.5:1 on at least one palette at every alpha "
            f"under {TRANSPARENT_TEXT_FLOOR_PCT:g}%; use `var(--fg-muted)`, which "
            f"mixes toward an opaque colour and is pinned at the floor by "
            f"`P1-03`. Alphas present: {', '.join(f'{p:g}%' for p in fresh[:12])}")

    # `B1408`. Every surviving transparent mix is a recorded decoration, with
    # its measurement; anything else under the floor is a defect by name.
    sites = _css_transparent_text_sites()
    undeclared = sorted({sel for sel, _ in sites} - set(DECORATION_TRANSPARENT_TEXT))
    for selector, pct in sites:
        if selector in DECORATION_TRANSPARENT_TEXT:
            ratio, name = _transparent_worst(pct)
            print(f"  decoration  {selector} at {pct:g}% — {ratio:.2f}:1 on {name}: "
                  f"{DECORATION_TRANSPARENT_TEXT[selector]}")
    if undeclared:
        problems.append(
            f"{len(undeclared)} rule(s) paint text toward `transparent` under "
            f"{TRANSPARENT_TEXT_FLOOR_PCT:g}% and are not recorded as decoration: "
            f"{', '.join(undeclared[:8])}. Use `color-mix(in oklab, var(--fg) N%, "
            f"var(--fg-muted))` (every rung clears 4.5:1), or record it in "
            f"DECORATION_TRANSPARENT_TEXT with why.")
    inline = _inline_transparent_text()
    print(f"inline `style=` text mixed toward transparent under "
          f"{TRANSPARENT_TEXT_FLOOR_PCT:g}%: {len(inline)} (none allowed)")
    if inline:
        problems.append(
            f"{len(inline)} inline style(s) paint text toward `transparent` under "
            f"{TRANSPARENT_TEXT_FLOOR_PCT:g}%: "
            f"{', '.join(sorted({f for f, _ in inline})[:6])}. Use "
            f"`color-mix(in oklab, var(--fg) N%, var(--fg-muted))`.")
    drift = _mirror_drift()
    if drift:
        problems.append(
            f"a page's copy of the muted foreground differs from static/style.css's "
            f"`:root` (`B1575`): {'; '.join(drift[:4])}. Copy the sheet's value.")
    rungs, ladder_fails = _ladder_failures()
    print(f"the de-emphasis ladder (`B1408`): {len(rungs)} rung(s) in use, "
          f"{'all clear 4.5:1 on every palette' if not ladder_fails else f'{len(ladder_fails)} miss'}")
    problems.extend(ladder_fails)
    dimming = _css_opacity_dimming()
    print(f"opacity under {TRANSPARENT_TEXT_FLOOR_PCT / 100:g} (`B1408`'s other half): "
          f"{dimming} declaration(s) (ratchet at {BASELINE_OPACITY_DIMMING})")
    if dimming > BASELINE_OPACITY_DIMMING:
        problems.append(
            f"{dimming} `opacity:` declarations under {TRANSPARENT_TEXT_FLOOR_PCT / 100:g} "
            f"and {BASELINE_OPACITY_DIMMING} is the recorded population — a new one dims "
            f"whatever it is on by letting the background through; for text, use the "
            f"ladder (`color-mix(in oklab, var(--fg) N%, var(--fg-muted))`) instead.")

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
    body = ("every palette's body text clears the floor or is B15's" if B15_THEMES
            else "every palette's body text clears the floor")
    print(f"\ncontrast OK — {body}, "
          f"all {len(OFFERABLE)} offered button designs clear it everywhere, and no "
          "rule paints a hard-coded white on an accent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
