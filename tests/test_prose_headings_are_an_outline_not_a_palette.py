# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P5-10` — `h1`–`h6` in a chat answer are a document outline, not a legend.

Premise re-measured 2026-09-18 and it holds **exactly**, value for value, in
`static/style.css`'s "HEADER SIZING FOR CHAT MESSAGES" block:

    h1  1.15em / 700  var(--hl-keyword)      the syntax highlighter's keyword
    h2  1.1em  / 600  var(--hl-function)     …its function name
    h3  1.05em / 600  var(--hl-string)       …its string literal
    h4  1.02em / 600  var(--hl-builtin)      …its builtin
    h5  1em    / 600  var(--hl-variable)     …its variable
    h6  0.95em / 600  var(--hl-number)       …its numeric literal

Six hues over a **1.21×** size range: h1 is 21% larger than h6 and every level
below the first is within 5% of the one above it. So a five-heading answer
arrives as five colours and effectively one size, and the only thing separating
"Summary" from "Step 3" is a hue borrowed from a code highlighter — where those
six colours mean six *unrelated* things and are chosen to be maximally
distinguishable from each other, which is the opposite of what a nesting
hierarchy wants.

The row's instruction is exact and this file holds it: **keep the syntax hue on
`h1` and `h2` only** — that pairing is the tell that this product renders
markdown from a model — and put the outline back in size and weight, where a
reader already knows how to read it.

`Law 20`: the block is resolved by scope (the six rules, parsed) rather than
grepped, because `--hl-keyword` appears at nine other places in this sheet and
three of them are inside `.msg`.
"""
import re
from pathlib import Path

from tests.helpers.source_text import blank  # B290

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "static" / "style.css"

LEVELS = ("h1", "h2", "h3", "h4", "h5", "h6")
# The six the highlighter owns. A heading painted in any of these is a heading
# painted in a token whose job is to mean something else.
SYNTAX_TOKENS = (
    "--hl-keyword", "--hl-function", "--hl-string",
    "--hl-builtin", "--hl-variable", "--hl-number",
    "--hl-params", "--hl-comment",
)


def _heading_rules() -> dict:
    """`{level: {prop: value}}` for the six single-level `.msg hN` rules.

    Scoped to rules whose selector is exactly `.msg hN` — the grouped
    `.msg h1, .msg h2, …` reset that sets margins is a different rule and
    folding it in here would report a margin as a heading's colour.
    """
    css = blank(STYLE)
    out = {}
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel = m.group(1).strip()
        if not re.fullmatch(r"\.msg\s+h[1-6]", sel):
            continue
        level = sel[-2:]
        decls = {}
        for piece in m.group(2).split(";"):
            if ":" in piece:
                k, _, v = piece.partition(":")
                decls[k.strip().lower()] = v.strip()
        out[level] = decls
    return out


def _em(value: str) -> float:
    m = re.fullmatch(r"([0-9.]+)em", value.strip())
    assert m, f"expected an em size, got {value!r}"
    return float(m.group(1))


def test_the_six_rules_are_all_still_here():
    """Scope check before any assertion about them (`B41`)."""
    got = _heading_rules()
    assert sorted(got) == list(LEVELS), sorted(got)
    for level in LEVELS:
        assert "font-size" in got[level], level


def test_only_h1_and_h2_keep_a_syntax_hue():
    """The row's own instruction, and the whole of it.

    Fails on the tree as it stood: all six named a `--hl-*` token.
    """
    offenders = {}
    for level, decls in _heading_rules().items():
        colour = decls.get("color", "")
        if any(tok in colour for tok in SYNTAX_TOKENS):
            offenders[level] = colour
    assert set(offenders) <= {"h1", "h2"}, (
        "headings still painted from the syntax palette: "
        + ", ".join(f"{k} -> {v}" for k, v in sorted(offenders.items()))
    )


def test_h1_and_h2_do_keep_theirs():
    """The other half of "h1 and h2 only". Dropping all six would satisfy the
    test above and lose the pairing the row calls the tell."""
    rules = _heading_rules()
    assert "--hl-keyword" in rules["h1"].get("color", ""), rules["h1"]
    assert "--hl-function" in rules["h2"].get("color", ""), rules["h2"]


def test_the_outline_has_a_range_a_reader_can_see():
    sizes = [_em(_heading_rules()[level]["font-size"]) for level in LEVELS]
    assert sizes == sorted(sizes, reverse=True), f"not monotonic: {sizes}"
    assert sizes[0] / sizes[-1] >= 1.5, (
        f"h1 is only {sizes[0] / sizes[-1]:.2f}x h6 ({sizes}) — a five-heading "
        "answer still arrives as one size"
    )


def test_no_two_adjacent_levels_are_within_a_rounding_error():
    """1.05 → 1.02 → 1.00 is three levels inside three per cent. At a 0.95em
    body in a 13px-ish message that is under half a pixel between h3, h4 and
    h5, so the *only* thing distinguishing them was the hue this row removes."""
    sizes = [_em(_heading_rules()[level]["font-size"]) for level in LEVELS]
    tight = [(LEVELS[i], LEVELS[i + 1], sizes[i], sizes[i + 1])
             for i in range(len(sizes) - 1) if sizes[i] / sizes[i + 1] < 1.06]
    assert tight == [], f"levels a reader cannot tell apart by size: {tight}"


def test_every_level_below_the_second_paints_the_body_colour():
    """Not merely "not a syntax token" — a heading that names no colour at all
    inherits, and inheriting is fine, but an explicit `--fg` is what makes the
    rule readable to the next person and mutation-visible to this file."""
    for level in ("h3", "h4", "h5", "h6"):
        colour = _heading_rules()[level].get("color", "")
        assert "var(--fg" in colour, f"{level} paints {colour!r}"


def test_the_ramp_is_carried_by_weight_as_well_as_size():
    """h1 has always been the one bold heading; the row's complaint is that
    everything under it was one weight *and* one size *and* six colours."""
    weights = {level: _heading_rules()[level].get("font-weight", "")
               for level in LEVELS}
    assert weights["h1"] == "700", weights
    assert len({w for w in weights.values()}) >= 2, weights
