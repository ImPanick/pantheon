# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1577` — quiet text is a rung of the ladder, not the foreground under an opacity.

`B1408` moved text that mixed `--fg` toward `transparent` onto the de-emphasis
ladder, `color-mix(in oklab, var(--fg) N%, var(--fg-muted))`, and counted the
other spelling of the same arithmetic — `opacity:` under 0.82, which lets the
background through the element and everything in it — at 965 declarations in
`static/style.css` (`BASELINE_OPACITY_DIMMING`). The text among them read under
4.5:1: `.memory-used-engine`, which `B1408` named, was `--fg` at `opacity:
0.45`, 1.79:1 on `retrowave`.

Now 558 text rules name the rung at the same N and set no opacity, the states
that lifted them (`:hover`, `.active`, a context at full opacity) set the colour
they lift to, and the ratchet is 407. What is left is named below, rule by
rule, with why.

`Law 20`, option 2 (`tests/helpers/css_rules.py`): a stylesheet is not driven
under node, so each rule is found first and asserted inside; the colours are
resolved on the 23 shipped palettes by the suite's one resolver.
"""

import importlib.util
import re
from pathlib import Path

from tests.helpers import css_colour
from tests.helpers.css_rules import css_rules, decl
from tests.helpers.source_text import blank

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "static" / "style.css"

LADDER = re.compile(r"color-mix\(in oklab, var\(--fg\) ([\d.]+)%, var\(--fg-muted\)\)")
TYPE = re.compile(r"(?:^|;)\s*(?:font-size|font-weight|font-family|text-transform|"
                  r"letter-spacing|text-overflow|font-style|font)\s*:")
FOREGROUND = re.compile(r"var\(--fg\)|inherit|" + LADDER.pattern
                        + r"|var\(--fg-muted(?:, [^)]*)?\)")

#: Rules that set type, paint in the foreground and still dim by `opacity`,
#: each because what it draws is not text a person reads at rest.
LEFT = {
    ".user-bar-avatar": "the account's initial in its avatar disc; the name is beside it",
    ".item-drag-handle": "a drag grip",
    ".folder-drag-handle": "a drag grip",
    ".compare-probe-spinner": "a spinner",
    ".pane-title-caret": "a caret glyph",
    ".agent-thread-chevron": "a chevron glyph",
    ".doc-divider-collapse": "a collapse arrow on the split divider",
    ".doc-tab-arrow": "a tab-strip scroll arrow",
    ".md-dd-ico": "an icon glyph in a dropdown row",
    ".gallery-tag-x": "a remove × whose hover is red; a colour here would out-rank it",
    ".cookbook-gpu-btn": "a GPU button whose free and busy states are green and red",
    ".task-log-row.is-skipped": "a whole skipped log row; the dimming is the state",
    ".report-spinner": "a spinner",
    ".ge-canvas-prompt-x": "a close ×",
    ".note-fullscreen-overlay .note-cl-grip": "a drag grip",
    ".note-reminder-menu-arrow": "a submenu arrow",
    ".note-cl-grip": "a drag grip",
    ".note-form-draw-text, .note-form-draw-line, .note-form-draw-circle, .note-form-draw-undo":
        "drawing-tool icon buttons",
    ".cal-dot-more": "a 7px more-events marker",
    ".agents-star": "a favourite star",
}


def _rules() -> list:
    return [(" ".join(sel.split()), body) for sel, body in css_rules(blank(STYLE))]


def _opacity(body: str):
    value = decl(body, "opacity")
    if value is None:
        return None
    try:
        return float(value.replace("!important", "").strip())
    except ValueError:
        return None


def test_the_rule_the_row_named_is_a_rung_and_reads_on_every_palette():
    """`.memory-used-engine`, the chat pill's engine line, at `opacity: 0.45`."""
    [body] = [b for s, b in _rules() if s == ".memory-used-engine"]
    assert _opacity(body) is None, "it is still dimmed by opacity"
    colour = decl(body, "color")
    assert LADDER.fullmatch(colour or ""), colour
    palettes = css_colour.palettes(css_colour.root_expressions(STYLE.read_text(encoding="utf-8")))
    misses = []
    for name, theme in sorted(palettes.items()):
        ink = css_colour.resolve(colour, theme)
        for ground in ("panel", "bg"):
            ratio = css_colour.contrast(ink, css_colour.resolve(f"var(--{ground})", theme))
            if ratio < 4.5:
                misses.append(f"{name} on --{ground}: {ratio:.2f}")
    assert not misses, misses


def test_no_foreground_text_is_quieted_by_an_opacity():
    """The row's `Verify:` — the text rules among the 965 moved onto the ladder.

    The shape, per rule: an `opacity` above 0 and under 0.82, a type property
    (so it draws characters), and a foreground colour or none (so the ladder
    is the colour it would take). Every such rule is in `LEFT`, with why."""
    found = {}
    for selector, body in _rules():
        if "@keyframes" in selector:
            continue
        value = _opacity(body)
        if value is None or not 0 < value < 0.82 or not TYPE.search(body):
            continue
        colour = decl(body, "color")
        if colour is not None and not FOREGROUND.fullmatch(colour.replace("!important", "").strip()):
            continue
        found[selector] = value
    assert set(found) == set(LEFT), (
        f"foreground text quieted by opacity, not on the ladder: "
        f"{sorted(set(found) - set(LEFT))[:12]}; named but gone: {sorted(set(LEFT) - set(found))}")


def test_every_rung_the_sheet_uses_clears_the_floor_and_the_ratchet_holds():
    spec = importlib.util.spec_from_file_location("check_contrast", ROOT / ".pantheon" / "check-contrast.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    rungs, failures = checker._ladder_failures()
    assert rungs and not failures, failures
    assert checker._css_opacity_dimming() == checker.BASELINE_OPACITY_DIMMING == 407


def test_a_state_that_lifted_the_text_lifts_its_colour():
    """`.session-bulk-btn` rested at `opacity: 0.4` and its hover lifted it to
    1. With the opacity gone a hover that only said `opacity: 1` would change
    nothing; it says the colour now."""
    rules = dict(_rules())
    assert LADDER.fullmatch(decl(rules[".session-bulk-btn"], "color") or "")
    assert decl(rules[".session-bulk-btn:hover"], "color") == "var(--fg)"
    # A state that is itself a hue keeps it: the parallel toggle is orange at
    # rest, and its hover says orange rather than the ladder's grey.
    assert decl(rules[".compare-parallel-toggle:hover"], "color") == "#e0a050"
