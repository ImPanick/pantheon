# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P5-01` / `P5-02` / `P5-05` — how the trace opens, and how it says it opens.

Three rows, one file, because they are one property of one surface: a person
reading an agent thread meets folds, and before these rows the folds did not
agree with each other about how to open or what an openable thing looks like.

  * `P5-01`. The reasoning fold was `max-height: 0 -> 300px` with
    `overflow-y: auto` at the open end. Long reasoning therefore landed in a
    300px scroller nested inside the page scroller — two wheels on one page,
    the inner one eating the gesture. The tool-output `<pre>` had the same
    300px clip. Re-measured before the work: **two** CSS rules in trace markup
    paired `max-height: 300px` with `overflow-y: auto`, exactly as the row
    said, and the other five sites in the sheet are dropdowns, the preset
    template list, the research library list and the settings nav search — none
    of them trace.
  * `P5-02`. Tool cards were `display: none` -> `display: block` while the
    reasoning fold a few pixels above them animated, so two folds in one thread
    behaved visibly differently.
  * `P5-05`. The global `summary::before` drew `▶` on the LEFT and rotated it
    90°, while reasoning, sources, tool output, both hwfit folds and the email
    folds had each independently gone to a chevron on the RIGHT.

Source-text assertions are the narrow exception `TESTING_STANDARD.md` allows
and `test_agent_thread_dot_alignment_css.py` established for this file's
neighbour: the invariant is pure CSS, and driving it would need a layout
engine the suite has no runner for. So this follows `Law 20`'s second option
rather than its first — **resolve the rule, then assert inside it** — and
never greps the sheet for a bare word. `_block()` returns one selector's
declarations and every assertion below is made against one of those.
"""

import re
from pathlib import Path

from tests.helpers.source_text import blank

_PATH = Path(__file__).resolve().parents[1] / "static" / "style.css"
_RAW = _PATH.read_text(encoding="utf-8")
# Comments out before anything is parsed. A declaration preceded by an inline
# comment is invisible to a `;`-anchored scan otherwise, and a selector picks
# up the comment above it as part of its own text — both of which this file hit
# on its first run.
#
# Through the shared blanker, not a hand-written `/\*.*?\*/`: a regex cannot
# tell a comment from a string literal, which is `B290` — the run where a naive
# one erased 7,277 lines across fifteen modules and no asserted count moved.
# `tests/test_one_comment_blanker.py` is the rule and it caught this file.
CSS = blank(_PATH)

# Every glyph this codebase has used to mean "this opens". `▶ ▸ ▾ ▼` are the
# four in the sheet today; the carets in the two hwfit folds are drawn with
# borders and carry `content: ''`, which is why they are not here.
DISCLOSURE_GLYPHS = "\u25b6\u25b8\u25be\u25bc"

# Selectors that are a disclosure control rather than, say, a list bullet.
# `.research-body-product ul li::before` also draws `▸` and is a bullet; a scan
# that counted it would be measuring typography, not this row.
_CONTROL = re.compile(r"summary|details|toggle|-fold|collaps", re.I)


def _blocks(selector: str) -> list[str]:
    """Declaration blocks for each rule written with this exact selector.
    More than one is normal — a breakpoint restates the selector to override
    part of it."""
    pattern = r"(?:^|\})[ \t\n]*" + re.escape(selector) + r"[ \t]*\{"
    return [
        CSS[m.end(): CSS.index("}", m.end())]
        for m in re.finditer(pattern, CSS, re.MULTILINE)
    ]


def _block(selector: str) -> str:
    """The one rule with this selector. Use `_values` where a breakpoint
    restates it."""
    found = _blocks(selector)
    assert len(found) == 1, f"expected exactly one `{selector}` rule, found {len(found)}"
    return found[0]


def _decl(block: str, prop: str) -> str | None:
    """One declaration's value, or None. Anchored on `;` or the block start so
    `max-height` never answers for `min-height`."""
    m = re.search(rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;}}]+)", block)
    return m.group(1).strip() if m else None


def _content(block: str) -> str:
    """A rule's `content`, with CSS escapes decoded. The sheet spells the same
    glyph both ways — `content: '▼'` in one rule and `content: '\\25BC'` in the
    next — and a test that only understood one spelling would be asserting on
    typing habits rather than on what renders."""
    raw = _decl(block, "content") or ""
    return re.sub(r"\\([0-9A-Fa-f]{1,6})\s?", lambda m: chr(int(m.group(1), 16)), raw)


def _values(selector: str, prop: str) -> list[str]:
    """Every value this property takes across every rule using this selector."""
    return [v for v in (_decl(b, prop) for b in _blocks(selector)) if v is not None]


def _rules() -> list[tuple[str, str]]:
    """(selector, declarations) for every rule in the sheet, flat."""
    return [
        (m.group(1).strip(), m.group(2))
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS)
    ]


# ── P5-01 · the nested scrollers ───────────────────────────────────────────


def test_no_rule_clips_trace_content_into_a_scroller_of_its_own():
    """The defect itself, stated as the property rather than as two selectors:
    nothing in the trace may pair a 300px cap with its own vertical scrollbar.
    The five survivors elsewhere in the sheet are named, so this cannot pass by
    the scan quietly narrowing."""
    offenders = []
    for selector, block in _rules():
        height = _decl(block, "max-height")
        overflow_y = _decl(block, "overflow-y") or _decl(block, "overflow")
        if height and height.replace(" ", "") == "300px" and overflow_y == "auto":
            offenders.append(selector.split()[-1])
    assert offenders == [
        ".pane-model-dropdown",
        ".add-pane-dropdown",
        ".prompt-templates-list",
        ".research-library-list",
        ".settings-nav-search-results",
    ], offenders


def test_the_reasoning_fold_opens_onto_the_content_and_not_onto_300px():
    shut = _block(".thinking-content")
    open_ = _block(".thinking-content.expanded")
    assert _decl(shut, "display") == "grid"
    assert _decl(shut, "grid-template-rows") == "0fr"
    assert _decl(open_, "grid-template-rows") == "1fr"
    assert _decl(open_, "max-height") is None, (
        "a cap on the open state is the defect this row removed"
    )
    assert _decl(open_, "overflow-y") is None
    transition = _decl(shut, "transition") or ""
    assert "grid-template-rows" in transition, (
        "0fr -> 1fr with nothing transitioning it is a snap, not a fold"
    )


def test_the_grid_item_may_actually_shrink_to_zero():
    """The half of the `0fr` idiom that is invisible in a diff and silently
    holds every fold open at full height: a grid item's `min-height` defaults
    to `auto`, which refuses to go below its content."""
    assert _decl(_block(".thinking-content > *"), "min-height") == "0"
    assert _values(".agent-thread-content-inner", "min-height") == ["0"]


def test_tool_output_is_bounded_by_its_data_and_not_by_a_magic_number():
    # Restated at the mobile breakpoint, so every rule using the selector is
    # checked rather than whichever one happens to come first in the file.
    assert _values(".agent-tool-output pre", "max-height") == ["none"]
    assert _values(".agent-tool-output pre", "overflow-y") == []


# ── P5-02 · the tool card opens the same way ───────────────────────────────


def test_a_tool_card_fold_animates_like_the_reasoning_fold_beside_it():
    shut = _block(".agent-thread-content")
    open_ = _block(".agent-thread-node.open .agent-thread-content")
    assert _decl(shut, "display") == "grid"
    assert _decl(shut, "grid-template-rows") == "0fr"
    assert _decl(open_, "grid-template-rows") == "1fr"
    assert _decl(open_, "display") is None, (
        "a `display` swap on the open state defeats the transition entirely — "
        "that is what this row replaced"
    )
    assert "grid-template-rows" in (_decl(shut, "transition") or "")


def test_both_folds_move_on_the_same_property():
    """"The same open/close transition as reasoning" is the row's words. Two
    folds that both animate, on different properties, on different curves, is
    the defect wearing a nicer coat."""
    reasoning = _decl(_block(".thinking-content"), "transition") or ""
    tool = _decl(_block(".agent-thread-content"), "transition") or ""
    assert "grid-template-rows" in reasoning and "grid-template-rows" in tool
    assert "max-height" not in reasoning and "max-height" not in tool


# ── P5-05 · one disclosure idiom ───────────────────────────────────────────


def test_nothing_draws_a_disclosure_glyph_on_the_left_any_more():
    """The whole point of the row. A `::before` carrying one of the four
    disclosure glyphs is a left-side marker, wherever it lives."""
    offenders = [
        selector for selector, block in _rules()
        if "::before" in selector and _CONTROL.search(selector)
        and any(g in _content(block) for g in DISCLOSURE_GLYPHS)
    ]
    assert offenders == [], offenders


def test_the_one_marker_every_details_inherits_is_a_right_side_flip():
    marker = _block("summary::after")
    assert "▼" in (_decl(marker, "content") or "")
    assert _decl(marker, "margin-left") == "auto", (
        "without this the chevron sits against the label instead of the edge"
    )
    assert "transform" in (_decl(marker, "transition") or "")
    assert _decl(_block("details[open] > summary::after"), "transform") == "rotate(180deg)"


def test_the_shared_rule_is_a_child_selector_and_not_a_descendant_one():
    """A nested `<details>` inside an open one used to take its parent's
    rotation as well as its own, so the inner marker pointed the wrong way at
    exactly the moment somebody was looking at it."""
    assert not _blocks("details[open] summary::after")
    assert _blocks("details[open] > summary::after")


def test_the_three_folds_the_row_names_all_flip_the_same_glyph():
    """Reasoning, sources and tool output. Sources was the odd one: right side
    already, but swapping `▶` for `▼` with `transition: none`, which is a third
    mechanism wearing the second one's clothes."""
    thinking = _block(".thinking-toggle::after")
    sources = _block(".sources-toggle::after")
    output = _block(".agent-tool-output summary::after")
    for rule in (thinking, sources, output):
        assert "▼" in _content(rule)
    assert "\u25b6" not in _content(sources) + _content(_block(".sources-toggle"))
    assert _decl(_block(".thinking-toggle.expanded"), "transform") == "rotate(180deg)"
    assert _decl(_block('.sources-toggle[data-arrow="down"]'), "transform") == "rotate(180deg)"
    assert _decl(_block(".agent-tool-output[open] > summary::after"), "transform") == "rotate(180deg)"


def test_the_tool_output_chevron_does_not_fight_the_diff_stats_for_the_gap():
    """`.agent-tool-output summary` is already `justify-content: space-between`,
    and the diff header's stats already claim `margin-left: auto`. A second
    auto margin splits the free space between them instead of pinning the
    chevron to the edge, which is a layout bug you only see on file edits."""
    assert _decl(_block(".agent-tool-output summary::after"), "margin-left") == "0"
