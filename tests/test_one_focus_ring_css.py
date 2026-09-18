# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-01` — one focus ring, and the hundred declarations that were silencing it.

The ring was never missing. `:focus-visible { outline: 2px solid var(--red) }`
has been in `static/style.css` the whole time — and it is written at (0,1,0),
which is less than almost anything else in a 44,000-line sheet. **100 rules in
that same file out-rank it**, and the row's premise about how many was stale:

  * the row said **97 `outline: none` plus 2 `outline: 0`, so 99**. Re-measured
    2026-09-18 with comments blanked: **98 and 2, so 100**, in 100 distinct
    rules. One arrived between 2026-08-27 and today, which is `Law 6` in
    miniature — the number was right when it was written;
  * the row said **35 `:focus-visible` rules**. There were **45 occurrences**
    of the selector across **42 rules** the morning this landed, and there are
    **49 across 46** once this row's guard and `P10-03`'s three handle
    selectors are in. Both figures are measured below rather than quoted, so
    the next reader gets today's number and not this sentence's.

Split by what they are scoped to, because the three kinds fail differently:

  * **47 spell `outline: none` with no focus pseudo-class at all.**
    `outline-style`'s initial value is already `none`, so such a declaration
    changes nothing except in the one state where something else would have
    set it — which is the focus state. They are ring suppressions wearing
    plain clothes;
  * **45 are scoped to `:focus`**, at (0,2,0) or heavier, so they beat a
    (0,1,0) `:focus-visible` rule on specificity and the ring never paints;
  * **8 are scoped to `:focus-visible` itself** and substitute a ring of their
    own — a `border-color` plus a 1px `box-shadow`. Six distinct styles between
    them, which is the "six competing ring styles" the row names.

Two of the hundred are `!important`, and they are why the new rule is
`!important` too: between two `!important` author declarations specificity
decides before order does, so a polite rule cannot reach
`.doc-editor-textarea` or `.email-quote-fold` however late in the file it is
written.

**Nothing is deleted here, and that is a decision rather than an omission.**
Every one of the hundred is now dead *as a ring suppression* —
`test_the_ring_out_ranks_every_suppression_in_the_sheet` proves it rule by
rule, which is the "shown to be dead" `Law 1` asks for before a subtraction.
But "dead in the cascade" is not "dead in the file": several carry `border`,
`background` and `box-shadow` in the same block, and the eight `:focus-visible`
ones now read as extra emphasis rather than as a replacement. The sweep is
`B662`, with this file as its evidence.

Read out of `static/style.css`. A stylesheet cannot be driven under node, so
this follows `Law 20`'s second option in the shape
`tests/test_the_trace_folds_open_css.py` established for this file's
neighbours: resolve the rule first, then assert inside it. The one thing it
does file-wide is count a declaration's *absence* pattern across every rule,
which is the census the cascade arithmetic is performed on — and it is
performed on resolved rules, never on a substring.
"""

import re
from pathlib import Path

from tests.helpers.source_text import blank

_PATH = Path(__file__).resolve().parents[1] / "static" / "style.css"
CSS = blank(_PATH)

# `outline: none` / `outline: 0`, anchored on a declaration boundary so
# `outline-offset: 0` and `outline-color: none` can never answer for it.
_SUPPRESSION = re.compile(
    r"(?:^|[{;])\s*outline\s*:\s*(none|0)\s*(!important)?\s*(?=[;}])", re.M
)
_GUARD_SELECTOR = re.compile(r":is\((?:#\\9)+,\s*\*\):focus-visible")


def _rules():
    """(selector, declarations) for every rule in the sheet, flat.

    Nested at-rules (`@media`) are transparent to this: their braces are not
    matched by `[^{}]+\\{[^{}]*\\}`, so what comes back is the innermost rules,
    which is what a cascade question is about."""
    return [
        (m.group(1).strip(), m.group(2))
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS)
    ]


def _line_of(offset: int) -> int:
    return CSS.count("\n", 0, offset) + 1


def _specificity(selector: str) -> tuple:
    """(ids, classes, types) for one complex selector.

    Deliberately small, and it refuses what it cannot weigh rather than
    guessing: every selector it is asked about here comes out of this sheet,
    and a silently mis-weighed one would make the cascade claim below false
    while every assertion stayed green — which is the failure mode this whole
    file exists to catch one level down.

    `:is()` / `:not()` / `:has()` take the weight of their most specific
    argument, which is the entire point of the guard's `#\\9` armour.
    """
    s = selector.strip()
    ids = classes = types = 0

    # Functional pseudo-classes first: recurse into the argument list and take
    # the heaviest arm, then blank the whole construct out of the string.
    def _eat_functional(text):
        nonlocal ids, classes, types
        out = []
        i = 0
        while i < len(text):
            m = re.compile(r":(is|not|has|matches|-moz-any|-webkit-any)\(").search(text, i)
            if not m:
                out.append(text[i:])
                break
            out.append(text[i:m.start()])
            depth, j = 1, m.end()
            while j < len(text) and depth:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                j += 1
            inner = text[m.end(): j - 1]
            arms = [_specificity(a) for a in _split_top(inner)] or [(0, 0, 0)]
            best = max(arms)
            ids += best[0]
            classes += best[1]
            types += best[2]
            i = j
        return "".join(out)

    s = _eat_functional(s)
    # `:where()` contributes nothing.
    s = re.sub(r":where\([^()]*\)", " ", s)
    # Escapes (`#\9`) are consumed by the id pattern below, which is why the
    # guard's three fake ids weigh three ids.
    ids += len(re.findall(r"#(?:\\.|[\w-])+", s))
    s = re.sub(r"#(?:\\.|[\w-])+", " ", s)
    classes += len(re.findall(r"\.(?:\\.|[\w-])+", s))
    s = re.sub(r"\.(?:\\.|[\w-])+", " ", s)
    classes += len(re.findall(r"\[[^\]]*\]", s))
    s = re.sub(r"\[[^\]]*\]", " ", s)
    classes += len(re.findall(r"::?(?!:)[\w-]+", s)) - len(
        re.findall(r"::[\w-]+", s)
    )
    types += len(re.findall(r"::[\w-]+", s))
    s = re.sub(r"::?[\w-]+(?:\([^()]*\))?", " ", s)
    types += len([t for t in re.findall(r"[\w-]+", s) if t != "*"])
    return (ids, classes, types)


def _split_top(text: str) -> list:
    """Split a selector list on commas outside parentheses."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def _suppressions() -> list:
    """(line, selector, is_important, weight) for every outline suppression."""
    found = []
    for selector, block in _rules():
        for m in _SUPPRESSION.finditer(block):
            for one in _split_top(selector):
                found.append(
                    (
                        _line_of(CSS.index(block) + m.start()),
                        one,
                        bool(m.group(2)),
                        _specificity(one),
                    )
                )
    return found


def _guard_rule() -> tuple:
    """(selector, declarations) for `P10-01`'s armoured rule. Exactly one."""
    hits = [(sel, block) for sel, block in _rules() if _GUARD_SELECTOR.search(sel)]
    assert len(hits) == 1, f"expected exactly one armoured focus rule, found {len(hits)}"
    return hits[0]


def _decl(block: str, prop: str):
    m = re.search(rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;}}]+)", block)
    return m.group(1).strip() if m else None


# ── the census, corrected ──────────────────────────────────────────────────


def test_the_suppression_population_is_a_hundred_not_ninety_nine():
    """The row's premise, re-measured. It said 97 + 2; it is 98 + 2.

    Pinned so the next one to arrive is a decision somebody made rather than a
    number that drifted. If a suppression is legitimately added or removed,
    move this and say which rule in the commit.
    """
    nones = len(re.findall(r"(?:^|[{;])\s*outline\s*:\s*none\s*(?:!important)?\s*(?=[;}])", CSS, re.M))
    zeros = len(re.findall(r"(?:^|[{;])\s*outline\s*:\s*0\s*(?:!important)?\s*(?=[;}])", CSS, re.M))
    assert (nones, zeros) == (98, 2), (
        f"expected 98 `outline: none` and 2 `outline: 0`, found {nones} and {zeros}"
    )


def test_the_suppressions_split_three_ways():
    """47 with no focus pseudo-class, 45 on `:focus`, 8 on `:focus-visible`.

    The split is the argument for the fix: the 47 look harmless (an outline is
    already `none` by default) and are ring suppressions all the same, because
    the only state in which anything sets an outline on them is the one the
    browser sets it in.
    """
    bare = focus = focus_visible = 0
    for selector, block in _rules():
        if not _SUPPRESSION.search(block):
            continue
        if ":focus-visible" in selector:
            focus_visible += 1
        elif ":focus" in selector:
            focus += 1
        else:
            bare += 1
    assert (bare, focus, focus_visible) == (47, 45, 8), (
        f"expected 47 / 45 / 8, found {bare} / {focus} / {focus_visible}. "
        "Counted by RULE, not by selector: 100 rules carry a suppression and "
        "118 selectors are listed across them, and those are answers to "
        "different questions (`Law 5`)."
    )


def test_the_focus_visible_rules_are_forty_two_not_thirty_five():
    """The row's other stale number, measured in both of its readings."""
    occurrences = len(re.findall(r":focus-visible", CSS))
    rules = sum(1 for sel, _b in _rules() if ":focus-visible" in sel)
    assert (occurrences, rules) == (49, 46), (
        f"expected 49 occurrences across 46 rules, found {occurrences} / {rules}. "
        "The row says 35 rules; it said so on 2026-08-27, and it was 45 "
        "occurrences across 42 rules the morning this one landed — `P10-01` "
        "adds the armoured guard and `P10-03` adds `:focus-visible` to three "
        "resize-handle selector lists, which is the whole of the difference."
    )


# ── the ring itself ────────────────────────────────────────────────────────


def test_the_ring_is_one_rule_and_it_is_armoured():
    selector, block = _guard_rule()
    assert _decl(block, "outline"), "the guard sets no outline"
    assert "!important" in _decl(block, "outline"), (
        "the guard's outline is not !important — two of the hundred "
        "suppressions are, and specificity cannot reach an !important "
        "declaration from a normal one"
    )
    assert _decl(block, "outline-offset"), (
        "the ring must sit outside the box; without an offset it overlaps the "
        "border it is supposed to be distinguishable from"
    )
    assert "!important" in _decl(block, "outline-offset")
    assert ":focus-visible" in selector and ":focus " not in selector + " ", (
        "the ring is scoped to :focus-visible, so a mouse click does not leave "
        "a sticky outline — which is what the sheet's own comment at "
        "`.list-item:focus` asks for"
    )


def test_the_ring_does_not_reach_for_the_accent():
    """`--accent` full-strength misses 4.5:1 against `--panel` on seven of the
    sixteen palettes (`tests/test_accent_fallback_semantics_css.py` names the
    set). A focus ring is the last thing to paint in a colour a reader cannot
    find, and painting one there would also add an accent site to a population
    that file pins at 814 precisely so a new one has to be a decision.
    """
    _selector, block = _guard_rule()
    outline = _decl(block, "outline")
    assert "--accent" not in outline, f"the focus ring reaches for the accent: {outline!r}"
    root = re.search(r"(?:^|\})\s*:root\s*\{([^{}]*)\}", CSS)
    assert root, ":root block not found"
    ring = _decl(root.group(1), "--focus-ring")
    assert ring, "`--focus-ring` is not declared in :root"
    assert "--accent" not in ring, f"`--focus-ring` resolves through the accent: {ring!r}"
    assert "--red" in ring, (
        "`--focus-ring` should resolve to the palette's own `--red`, which is "
        f"what the previous global rule already painted; got {ring!r}"
    )


def test_the_ring_out_ranks_every_suppression_in_the_sheet():
    """The whole claim, computed rather than asserted.

    For every one of the hundred: the guard wins. `!important` beats normal
    whatever the weight, and between two `!important` declarations weight
    decides. A suppression that out-ranked the guard would be a selector whose
    focus ring silently does not exist, which is exactly the defect this row
    is named after and is invisible in any screenshot nobody thought to take.
    """
    selector, block = _guard_rule()
    guard_weight = max(_specificity(s) for s in _split_top(selector))
    guard_important = "!important" in (_decl(block, "outline") or "")
    losers = []
    for line, sel, important, weight in _suppressions():
        if important and not guard_important:
            losers.append((line, sel, weight, "!important"))
        elif important == guard_important and weight >= guard_weight:
            losers.append((line, sel, weight, "specificity"))
    assert not losers, (
        f"{len(losers)} outline suppressions out-rank the focus ring "
        f"(guard weight {guard_weight}, important={guard_important}):\n  "
        + "\n  ".join(f"line {l}: {s} at {w} — wins on {why}" for l, s, w, why in losers)
    )


def test_the_armour_is_still_enough_headroom():
    """The ceiling, recomputed from the sheet rather than remembered.

    Scoped to `!important` declarations of `outline`, and the scope is the
    whole argument (`Law 5`): the guard is `!important`, so a normal
    declaration cannot reach it at any weight, and the only rules that can are
    the eleven that spell an outline `!important` — of which the heaviest that
    is not the guard itself is `body.doc-find-active mark.doc-find-mark.current`
    at (0,3,2). Comparing against every selector in a 44,000-line sheet would
    be a different and much stricter claim, and it would demand more armour
    every time an unrelated rule got specific.

    `P1-12`'s motion guard carries the same three-id armour and the same
    argument: how many ids the guard needs is a fact about the rest of the
    file, and a rule that climbs above it takes the ring away from whatever it
    matches without failing anything else.
    """
    selector, _block = _guard_rule()
    guard_weight = max(_specificity(s) for s in _split_top(selector))
    heaviest, worst = (0, 0, 0), ""
    important = re.compile(r"(?:^|[;{])\s*outline[a-z-]*\s*:\s*[^;}]*!important")
    for sel, block in _rules():
        if not important.search(block):
            continue
        for one in _split_top(sel):
            if _GUARD_SELECTOR.search(one):
                continue
            w = _specificity(one)
            if w > heaviest:
                heaviest, worst = w, one
    assert heaviest != (0, 0, 0), (
        "no !important outline rule was found at all — the scan has stopped "
        "measuring anything, which passes silently"
    )
    assert guard_weight > heaviest, (
        f"the focus ring sits at {guard_weight} and `{worst}` sits at "
        f"{heaviest}; add another `#\\9` to the armour"
    )


def test_the_old_global_rule_is_still_there():
    """`Law 1`. The (0,1,0) rule is the base the armoured one sits on top of,
    and removing it would be a subtraction nobody asked for — it is also what
    a browser with no `:is()` support falls back to."""
    plain = [sel for sel, _b in _rules() if sel.strip() == ":focus-visible"]
    assert len(plain) == 1, (
        "the original bare `:focus-visible` rule is gone; it is the fallback "
        "for anything that cannot parse `:is()`"
    )
