# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P5-11` — a section header has to out-rank the rows underneath it.

The row said *"headers are 10px/400 over 13px rows … both sizes already exist,
this is a swap."* **Half of that was true and the half that was false is the
reason the defect survived six audits.** Re-measured 2026-09-18:

  * `.section-header-flex .section-title` really is `font-size: 10px;
    font-weight: 400` (`static/style.css`, the "Section title text" rule);
  * `.list-item` really does declare `font-size: 13px` — and **no sidebar label
    ever receives it.** Every label in the sidebar is a `<span>`: `<span
    class="grow">Brain</span>` in the markup, `span.className = 'grow'` in
    `sessions.js`'s row builder. `.list-item span { font-size: 9.75px }` is
    (0,2,0) against `.list-item`'s (0,1,0), so the cascade throws the 13px away
    on every single row.

So what a person actually sees is a **10px/400 header over a 9.75px/400 row in
the same `--fg`** — a quarter of a pixel and nothing else. Not an inversion: no
hierarchy at all. A first-time reader cannot tell that "Tools" is the name of a
group and "Compare" is a thing to click, and both are clickable, so there is no
behavioural tell either.

This file therefore does not grep for `10px`. It **resolves the cascade** for
the two element paths that matter and compares what they render at, which is
the only form of the assertion that could have caught the original mistake —
a test that read `.list-item`'s declared 13px would have agreed with the row
and been wrong in the same way.

`Law 20`: the shape, in scope, not the word.
"""
import re
from pathlib import Path

import pytest

from tests.helpers.source_text import blank  # B290

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "static" / "style.css"
INDEX = ROOT / "static" / "index.html"

# The two elements, root-first. Each is (tag, {classes}, id-or-None).
# Both are real: the header is `static/index.html`'s Tools section header, the
# row is the `#tool-compare-btn` beneath it.
HEADER_PATH = [
    ("div", {"sidebar-inner"}, None),
    ("div", {"section"}, "tools-section"),
    ("div", {"section-header-flex"}, None),
    ("span", {"section-title"}, None),
]
ROW_PATH = [
    ("div", {"sidebar-inner"}, None),
    ("div", {"section"}, "tools-section"),
    ("button", {"list-item"}, None),
    ("span", {"grow"}, None),
]


# ── A cascade small enough to trust ─────────────────────────────────────────


def _desktop_css() -> str:
    """The sheet with comments blanked and every `@media` block removed.

    The media blocks are dropped rather than evaluated because the defect is a
    desktop one: the 768px block already sets both labels to 14px, so a
    resolver that folded it in would report the two as equal and pass on a
    tree where the desktop sidebar is flat. Brace-matched, not regexed — the
    blocks nest and a non-greedy `}` stops at the first inner rule.
    """
    css = blank(STYLE)
    out, i = [], 0
    while True:
        at = css.find("@media", i)
        if at < 0:
            out.append(css[i:])
            return "".join(out)
        out.append(css[i:at])
        depth, pos = 0, css.index("{", at)
        for pos in range(pos, len(css)):
            depth += (css[pos] == "{") - (css[pos] == "}")
            if depth == 0:
                break
        i = pos + 1


def _rules():
    """(order, selector, {prop: (value, important)}) for every top-level rule."""
    css = _desktop_css()
    found, order = [], 0
    for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
        selectors, body = m.group(1).strip(), m.group(2)
        if not selectors or selectors.startswith(("@", "%")):
            continue
        decls = {}
        for piece in body.split(";"):
            if ":" not in piece:
                continue
            prop, _, value = piece.partition(":")
            prop, value = prop.strip().lower(), value.strip()
            if prop not in ("font-size", "font-weight"):
                continue
            important = "!important" in value.lower()
            decls[prop] = (value.lower().replace("!important", "").strip(), important)
        if not decls:
            continue
        for sel in selectors.split(","):
            order += 1
            found.append((order, sel.strip(), decls))
    return found


_COMPOUND = re.compile(r"(?:^|(?<=[\s>+~]))((?:[a-zA-Z][\w-]*|[.#][\w-]+|\*)+)")


def _specificity(sel: str):
    return (sel.count("#"), sel.count("."), len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", sel)))


def _compound_matches(compound: str, element) -> bool:
    tag, classes, el_id = element
    for token in re.findall(r"[.#]?[\w-]+|\*", compound):
        if token == "*":
            continue
        if token.startswith("."):
            if token[1:] not in classes:
                return False
        elif token.startswith("#"):
            if token[1:] != el_id:
                return False
        elif token.lower() != tag:
            return False
    return True


def _matches(sel: str, path) -> bool:
    """True when `sel` selects the last element of `path`.

    Only the subset the sidebar actually uses: tag / class / id compounds
    joined by descendant or child combinators. Anything richer (`:hover`,
    `:has()`, attribute selectors, `+`, `~`) is declined rather than guessed
    at — a wrong match here would be a silently wrong assertion, and the two
    rules under test use neither.
    """
    if re.search(r"[:\[\]()+~]", sel):
        return False
    sel = sel.strip()
    compounds = [p for p in re.split(r"\s*>\s*|\s+", sel) if p]
    combinators = re.findall(r"\s*>\s*|\s+", sel)
    if len(combinators) != len(compounds) - 1:
        return False
    if not compounds or not _compound_matches(compounds[-1], path[-1]):
        return False
    idx = len(path) - 2
    for k in range(len(compounds) - 2, -1, -1):
        child_combinator = ">" in combinators[k]
        if child_combinator:
            if idx < 0 or not _compound_matches(compounds[k], path[idx]):
                return False
            idx -= 1
        else:
            while idx >= 0 and not _compound_matches(compounds[k], path[idx]):
                idx -= 1
            if idx < 0:
                return False
            idx -= 1
    return True


def _resolve(path, prop, inherited):
    """Effective `prop` for the last element of `path`, walking root-first so
    inheritance is real rather than assumed."""
    value = inherited
    rules = _rules()
    for depth in range(1, len(path) + 1):
        prefix = path[:depth]
        winner = None
        for order, sel, decls in rules:
            if prop not in decls:
                continue
            if not _matches(sel, prefix):
                continue
            key = (decls[prop][1], _specificity(sel), order)
            if winner is None or key > winner[0]:
                winner = (key, decls[prop][0])
        # `inherit` is not a value, it is an instruction to keep the parent's —
        # and `.list-item { font-weight: inherit }` really is in the sheet, so
        # a resolver that treated it as a literal would compare the string
        # "inherit" against a number and report a type error as a hierarchy.
        if winner is not None and winner[1] != "inherit":
            value = winner[1]
    return value


def _px(value: str) -> float:
    m = re.fullmatch(r"([0-9.]+)px", value.strip())
    if not m:
        pytest.fail(f"expected a px length, got {value!r}")
    return float(m.group(1))


# ── The properties ──────────────────────────────────────────────────────────


def test_the_row_label_never_receives_list_items_own_font_size():
    """The premise correction, pinned so nobody re-derives the wrong number.

    `.list-item { font-size: 13px }` is real and reaches no label. If a future
    change makes it reach one, this fails and the row's arithmetic has to be
    redone rather than quietly inherited.
    """
    assert "font-size: 13px" in _desktop_css(), "the 13px declaration went away"
    assert _px(_resolve(ROW_PATH, "font-size", "16px")) != 13.0, (
        "`.list-item`'s 13px now reaches the row label — re-measure P5-11"
    )


def test_a_section_header_is_larger_than_the_rows_it_names():
    header = _px(_resolve(HEADER_PATH, "font-size", "16px"))
    row = _px(_resolve(ROW_PATH, "font-size", "16px"))
    assert header >= row + 1.0, (
        f"section header renders at {header}px over {row}px rows — a "
        f"{header - row:g}px difference is not a hierarchy. Both elements are "
        "clickable and both paint var(--fg), so size and weight are the only "
        "tells a first-time reader gets."
    )


def test_a_section_header_is_heavier_than_the_rows_it_names():
    header = _resolve(HEADER_PATH, "font-weight", "400")
    row = _resolve(ROW_PATH, "font-weight", "400")

    def _num(w):
        return {"normal": 400, "bold": 700}.get(w, w)
    assert int(_num(header)) > int(_num(row)), (
        f"section header weight {header} over row weight {row} — the header "
        "reads as one more row in the list"
    )


def test_the_header_label_sits_on_the_eleven_pixel_floor():
    """`P5-14`'s floor, applied here first because this is the row that moved.

    Not a restatement of the test above: that one only asks for separation, and
    separation is also achievable by shrinking the rows, which is the wrong
    direction on a surface whose smallest text is already 9.75px.
    """
    assert _px(_resolve(HEADER_PATH, "font-size", "16px")) >= 11.0


def test_every_sidebar_section_header_uses_the_one_rule():
    """Scope, not a substring: the header markup has to keep carrying the class
    the rule above is measured through, or the measurement is about an element
    nobody renders (`B41`)."""
    html = blank(INDEX)
    headers = re.findall(r'<div class="section-header-flex">', html)
    assert len(headers) >= 3, f"expected the sidebar's section headers, found {len(headers)}"
    for block in re.findall(r'<div class="section-header-flex">(.*?)</div>', html, re.S):
        assert 'class="section-title"' in block or "<h4" in block, block[:200]
