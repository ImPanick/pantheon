# SPDX-License-Identifier: AGPL-3.0-or-later
"""P3-01 / P3-02 — two elements whose applied style nobody wrote.

CSS resolves a property by importance first, then specificity, then document
order. Nothing warns when two authors set the same property on the same
element; the loser simply does not happen, and the winner is often a line
neither of them would have chosen.

**`P3-01`.** `.chat-input-bar textarea#message` authors the chat composer at
14px, line-height 1.5. A bare `#message` block 1,200 lines below set
`font-size: 13px !important`, `line-height: 1.4 !important`, plus `overflow-y`
and `font-family` — four `!important` declarations at id specificity, so the
composer had never once rendered as authored.

That block is not a competing opinion. It belongs to a `/* Unified chat input
area */` section in which **every other selector is dead** — no markup, no
script — an older composer layout kept in the file. It is the one selector in
it that still reaches something, because an id is an id wherever it is written.
Scoped to `.chat-input-form #message` rather than deleted (`Law 1`): intact,
reversible, and matching only the layout it describes.

**`P3-02`.** `.attach-strip` was declared three times at identical specificity —
twice within three lines of each other, once 5,200 lines away. Each replaced
part of the one before, so the applied rule was written by none of the three.
Collapsed into one, at the values the cascade already produced.
"""
import pathlib
import re

import pytest
from tests.helpers.source_text import blank, blank_text  # B290

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
NO_COMMENTS = blank_text(CSS, "css")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

# Every selector in the dead `/* Unified chat input area */` section except the
# one that reaches the live composer.
DEAD_SECTION = [
    "chat-input-area", "chat-input-form", "chat-controls-row",
    "chat-controls-left", "chat-controls-right", "control-group",
    "control-label", "preset-buttons-row", "toggle-switch", "toggle-slider",
    "action-button",
]


def _rules():
    """(selector_list, body, inside_at_rule) for each rule, in document order.

    A one-level at-rule tracker is enough: this file nests `@media` around
    plain rules and nothing deeper."""
    out, media, i = [], None, 0
    src = NO_COMMENTS
    while True:
        brace = src.find("{", i)
        if brace == -1:
            break
        prelude = src[i:brace].strip()
        if prelude.startswith("@"):
            media = prelude
            i = brace + 1
            continue
        end, depth, j = None, 1, brace + 1
        while j < len(src):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
            j += 1
        if end is None:
            break
        prelude = prelude.lstrip("}").strip()
        out.append((prelude, src[brace + 1:end], media))
        # A `}` immediately after closes the at-rule we are inside.
        rest = src[end + 1:end + 40].lstrip()
        if media and rest.startswith("}"):
            media = None
        i = end + 1
    return out


def _declares(body, prop):
    m = re.search(rf"(?<![a-z-]){prop}\s*:([^;{{}}]*)", body)
    return m.group(1).strip() if m else None


def test_the_extractor_sees_the_rules_this_file_is_about():
    """Every assertion below is vacuous against a parser that returns nothing."""
    rules = _rules()
    assert len(rules) > 3000, len(rules)
    sels = [r[0] for r in rules]
    assert ".chat-input-bar textarea#message" in sels
    assert ".chat-input-form #message" in sels


def test_only_one_rule_sets_the_composer_font_size_outside_a_media_query():
    """The composer is `<textarea id="message">` inside `.chat-input-bar`.
    Anything that can match it and sets `font-size` is competing for it."""
    hits = []
    for sel, body, media in _rules():
        if media:
            continue
        for one in sel.split(","):
            one = one.strip()
            if "#message" not in one:
                continue
            # A selector requiring a class that no markup has cannot match.
            required = set(re.findall(r"\.([A-Za-z0-9_-]+)", one))
            if required & set(DEAD_SECTION):
                continue
            size = _declares(body, "font-size")
            if size:
                hits.append((one, size))
    assert len(hits) == 1, f"more than one rule claims the composer's size: {hits}"
    sel, size = hits[0]
    assert size == "14px", f"the composer renders at {size}, not its authored 14px"
    assert "!important" not in size


def test_the_touch_override_survives():
    """16px on a coarse pointer is what stops iOS zooming the page on focus. It
    is `!important` on purpose and must keep winning."""
    found = [
        (sel, body) for sel, body, media in _rules()
        if media and "pointer: coarse" in media and "#message" in sel
    ]
    assert found, "the composer lost its touch font-size"
    assert "16px" in found[0][1] and "!important" in found[0][1]


def test_the_old_composer_block_is_scoped_and_still_intact():
    """Scoped, not deleted: every declaration it carried is still there, under a
    selector that matches only the layout it was written for."""
    body = next(b for s, b, _ in _rules() if s == ".chat-input-form #message")
    for decl in ("flex: 1", "min-height: 34px", "max-height: 120px",
                 "resize: none", "font-size: 13px !important",
                 "overflow-y: auto !important", "line-height: 1.4 !important",
                 "font-family: inherit !important"):
        assert decl in re.sub(r"\s+", " ", body), decl


@pytest.mark.parametrize("cls", DEAD_SECTION)
def test_the_layout_it_was_scoped_to_is_still_absent(cls):
    """The ratchet. If one of these ever appears in markup, that layout is back
    and the scoped block starts applying again — at which point somebody should
    look at it rather than discover it through a 13px composer."""
    assert not re.search(rf"""["'\s]{re.escape(cls)}["'\s]""", INDEX), (
        f"{cls} is in the markup now — the `/* Unified chat input area */` "
        "section is no longer dead, and `.chat-input-form #message` will "
        "override the composer again"
    )


def test_attach_strip_is_declared_once_with_the_values_the_cascade_produced():
    blocks = [(s, b) for s, b, media in _rules()
              if not media and s.strip() == ".attach-strip"]
    assert len(blocks) == 1, f"{len(blocks)} `.attach-strip` blocks"
    body = re.sub(r"\s+", " ", blocks[0][1])
    for decl in ("display: flex", "gap: 6px", "flex-wrap: wrap",
                 "margin: 6px auto 0", "min-height: 32px", "padding: 2px 8px",
                 "max-width: 800px", "width: 100%", "box-sizing: border-box"):
        assert decl in body, f"{decl} was lost in the merge"
    # The merge must not resurrect what never applied.
    assert "margin: 0 0 8px" not in body and "min-height: 0" not in body


def test_attach_strip_empty_is_declared_once():
    empties = [s for s, _, media in _rules()
               if not media and s.strip() == ".attach-strip:empty"]
    assert len(empties) == 1, empties


def test_the_ghost_overlay_and_the_composer_share_their_metrics():
    """What the 13px override actually cost, and the proof 14px was intended.

    `#message-ghost.ghost-text-overlay` is absolutely positioned over the
    textarea and renders the inline autocomplete suggestion in transparent
    text so the visible glyphs line up with what is being typed. It authors
    `font-size: 14px; line-height: 1.5; font-family: inherit` — the composer's
    authored values, and not the 13px/1.4 the composer was actually getting.
    Two layers meant to be pixel-aligned were a point apart in size and a tenth
    apart in leading, so the ghost drifted further right with every character
    and sat on a different baseline. Nobody had written that down.

    They must agree. Which value they agree on is a design decision; that they
    agree is not."""
    rules = {s.strip(): b for s, b, media in _rules() if not media}
    composer = rules[".chat-input-bar textarea#message"]
    ghost = rules[".ghost-text-overlay"]
    for prop in ("font-size", "line-height", "font-family"):
        a, b = _declares(composer, prop), _declares(ghost, prop)
        assert a is not None and b is not None, (prop, a, b)
        assert a == b, (
            f"the composer and the ghost overlay disagree on {prop}: "
            f"{a!r} vs {b!r}. They are drawn on top of each other; a "
            "difference here is visible drift on every keystroke."
        )
