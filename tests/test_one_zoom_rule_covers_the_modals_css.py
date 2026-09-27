# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-08` — one rule compensates the modals for the 1.25x text size, and
every line beside it has to say why it is there.

**The row's corrected premise, measured before a line moved.** Under
`:root.ui-scale-125 { zoom: 1.25 }` a viewport-sized cap renders 1.25x taller,
so a modal capped at 85vh stands 106% of the screen tall and its header — with
the only control that turns the scale back down — sits above the top edge.
`:root.ui-scale-125 .modal-content { max-height: calc(85dvh / 1.25) }` is the
generic answer, and it is (0,3,0): it outranks a cap written on any class of
the modal's own, so a new modal is compensated with no line of its own. The
five per-modal lines beside it were the *exceptions* to that rule, and the row
asked which of them had a reason.

Measured 2026-09-27 in headless Chromium at 1400x900, each modal filled past
its cap, at 1.25x with its line in place and with it deleted from the live
stylesheet:

    calendar  88% of the screen with the line, 85% without  (cap is 88vh)
    settings  612px with the line, 612px without            (redundant)
    theme     600px with the line, 750px without            (id outranks)
    cookbook  94% with the line; 117% and header at -65px   (id outranks)
    pdf       86% with the line, 85% without                (cap is 86vh)

So four have a reason and one had none. This file is the cascade half of that
measurement, recomputed from the sheet on every run: a line here must either
carry a cap the generic rule would change, or protect a cap the generic rule
cannot outrank — and its arithmetic must be the base divided by 1.25. A line
with neither reason is the habit the row was rewritten to stop teaching, and
the test says so by name.

A stylesheet cannot be driven under node, so this follows `Law 20`'s second
option the way `tests/test_one_focus_ring_css.py` does: resolve the rules
first (media-aware, from `tests/test_fg_muted_and_backdrop_cascade_css.py`'s
brace walk), then weigh and evaluate inside them. Both helpers are imported,
not copied (`Law 14`).
"""

import re

from tests.test_fg_muted_and_backdrop_cascade_css import _blocks, _decls
from tests.test_one_focus_ring_css import _specificity, _split_top

_SCALE = 1.25
_PREFIX = ":root.ui-scale-125"
_GENERIC = f"{_PREFIX} .modal-content"
# A viewport to evaluate lengths against. Any size gives the same verdicts —
# the ratios are what is checked — and this one is the size measured above.
_VH, _VW = 900.0, 1400.0

# The four the measurement found a reason for. Pinned so a fifth arrives as a
# decision with its reason written beside it, not as a copy of its neighbour.
_EXPECTED = {
    ".cal-modal-content",
    "#theme-popup",
    "#cookbook-modal .modal-content",
    ".pdf-export-overlay .modal-content",
}


def _desktop(media: tuple) -> bool:
    """A rule that applies on a desktop-width screen.

    The mobile sheets are `max-width` queries with `!important` caps of their
    own; the comment above the rules says the compensation is desktop only,
    and a narrow-screen rule is not the base a desktop exception divides."""
    return not any("max-width" in m or "hover: none" in m or "pointer: coarse" in m for m in media)


def _rules_for(selector: str) -> list:
    """(index, specificity, {prop: value}) for desktop rules naming `selector`."""
    out = []
    for index, media, prelude, body, _start in _blocks():
        if not _desktop(media):
            continue
        parts = [re.sub(r"\s+", " ", p) for p in _split_top(prelude)]
        if selector in parts:
            decls = {prop: value for prop, value, _imp in _decls(body)}
            out.append((index, _specificity(selector), decls))
    return out


def _exceptions() -> dict:
    """{target selector: {prop: value}} for every per-modal ui-scale-125 rule."""
    found = {}
    for _index, media, prelude, body, _start in _blocks():
        if not _desktop(media):
            continue
        for part in _split_top(prelude):
            part = re.sub(r"\s+", " ", part)
            if not part.startswith(_PREFIX + " "):
                continue
            target = part[len(_PREFIX) + 1:]
            if target in ("body", ".modal-content"):
                continue
            decls = {p: v for p, v, _imp in _decls(body) if p in ("height", "max-height")}
            if decls:
                found[target] = decls
    return found


def _length(expr: str) -> float:
    """Evaluate a cap in px at `_VH` x `_VW`. Small on purpose: vh/dvh/svh/lvh,
    vw, px, `calc(a / n)`, `calc(a - b)`, `calc(a + b)`, `min()` and `max()`.
    Anything else is refused rather than guessed at."""
    s = expr.strip()
    m = re.fullmatch(r"(min|max)\((.*)\)", s)
    if m:
        arms = [_length(a) for a in _split_top(m.group(2))]
        return min(arms) if m.group(1) == "min" else max(arms)
    m = re.fullmatch(r"calc\((.*)\)", s)
    if m:
        return _length(m.group(1))
    # A top-level binary operator, lowest precedence first.
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        ch = s[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
        elif depth == 0 and ch in "+-" and i > 0 and s[i - 1] == " ":
            left, right = _length(s[:i]), _length(s[i + 1:])
            return left + right if ch == "+" else left - right
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        ch = s[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
        elif depth == 0 and ch in "*/":
            left, right = s[:i].strip(), s[i + 1:].strip()
            if ch == "/":
                return _length(left) / float(right)
            return _length(left) * float(right)
    m = re.fullmatch(r"(-?[\d.]+)(d|s|l)?vh", s)
    if m:
        return float(m.group(1)) * _VH / 100.0
    m = re.fullmatch(r"(-?[\d.]+)vw", s)
    if m:
        return float(m.group(1)) * _VW / 100.0
    m = re.fullmatch(r"(-?[\d.]+)px", s)
    if m:
        return float(m.group(1))
    if s.startswith("(") and s.endswith(")"):
        return _length(s[1:-1])
    raise AssertionError(f"cannot evaluate {expr!r}; teach `_length` rather than guess")


def _base(target: str, prop: str):
    """(value, specificity) the desktop cascade gives `target` for `prop` at
    the default scale — the last rule naming it in source order, which among
    rules of one selector is the cascade. None when nothing sets it."""
    hits = [(i, spec, d[prop]) for i, spec, d in _rules_for(target) if prop in d]
    if not hits:
        return None
    _i, spec, value = max(hits)
    return value, spec


def test_the_generic_rule_divides_the_default_cap():
    """The one rule every modal relies on, and the zoom it answers."""
    zoom = [d for _i, _s, d in _rules_for(_PREFIX) if "zoom" in d]
    assert zoom and zoom[-1]["zoom"] == "1.25", (
        f"`{_PREFIX} {{ zoom: 1.25 }}` moved or changed: {zoom}. Every "
        "number in this file is a division by that factor."
    )
    generic = [d for _i, _s, d in _rules_for(_GENERIC) if "max-height" in d]
    assert generic, f"`{_GENERIC}` is gone — nothing compensates a new modal"
    base = _base(".modal-content", "max-height")
    assert base and base[0] == "85vh", f"`.modal-content`'s cap moved: {base}"
    assert abs(_length(generic[-1]["max-height"]) * _SCALE - _length(base[0])) < 0.5, (
        f"`{_GENERIC}` is {generic[-1]['max-height']!r}, which is not "
        f"{base[0]} divided by {_SCALE}"
    )
    assert _specificity(_GENERIC) == (0, 3, 0), _specificity(_GENERIC)


def test_every_exception_has_a_reason_the_generic_rule_cannot_supply():
    """The row's question, answered per line and recomputed from the sheet.

    A line is needed when the modal's own cap is not the generic rule's 85vh
    (the generic rule would *change* it), or when that cap is written on a
    selector heavier than (0,3,0) (the generic rule cannot *reach* it). A
    line with neither reason renders the same pixels as the generic rule —
    measured for Settings: 612px with it and 612px without — and is the
    habit this row was rewritten to stop teaching.
    """
    generic_weight = _specificity(_GENERIC)
    generic_px = _length("85vh")
    redundant = []
    for target, decls in _exceptions().items():
        for prop in decls:
            base = _base(target, prop)
            assert base, (
                f"`{_PREFIX} {target}` compensates `{prop}`, but no desktop "
                f"rule gives `{target}` a {prop} to compensate"
            )
            value, weight = base
            differs = abs(_length(value) - generic_px) >= 0.5 or prop == "height"
            outranks = weight > generic_weight
            if not (differs or outranks):
                redundant.append(f"{target} ({prop}: {value} at {weight})")
    assert not redundant, (
        "these ui-scale-125 lines render exactly what the generic "
        f"`{_GENERIC}` already renders — fold them back: {redundant}"
    )


def test_every_exception_divides_its_own_cap_by_the_zoom():
    """A line that carries a cap has to carry the right one. The theme popup's
    px arm is the case a hand-edit gets wrong: 600px becomes 480px, and a
    stale 600 would let it render 750px tall at 1.25x."""
    wrong = []
    for target, decls in _exceptions().items():
        for prop, scaled in decls.items():
            base = _base(target, prop)
            assert base, f"no base {prop} for `{target}`"
            if abs(_length(scaled) * _SCALE - _length(base[0])) >= 0.5:
                wrong.append(f"{target} {prop}: {scaled!r} x {_SCALE} != {base[0]!r}")
    assert not wrong, wrong


def test_the_exceptions_are_the_four_with_a_reason():
    found = set(_exceptions())
    assert found == _EXPECTED, (
        f"expected the four measured exceptions {sorted(_EXPECTED)}, found "
        f"{sorted(found)}. A new line needs its reason written beside it and "
        "its name added here; a missing one needs its modal re-measured."
    )


def test_settings_is_compensated_by_the_generic_rule_alone():
    """The one that was folded back. Its cap is 85vh on a single class, so the
    generic rule outranks it at 1.25x and divides the same number."""
    assert ".settings-modal-content" not in _exceptions(), (
        "`.settings-modal-content` has a ui-scale-125 line again; the generic "
        "rule already renders it at the same 612px of a 900px screen"
    )
    value, weight = _base(".settings-modal-content", "max-height")
    assert value == "85vh", value
    assert weight < _specificity(_GENERIC), weight
