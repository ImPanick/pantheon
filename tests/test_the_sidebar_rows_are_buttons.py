# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-02` — the sidebar's action rows, authored as the buttons they behave as.

Twelve rows in `static/index.html` carried `class="list-item"` on a `<div>` and
a click handler: New Chat, Search, and the ten Tools launchers. A `<div>` is
not in the tab order and is not announced as anything, which `static/js/a11y.js`
has been compensating for since it was written — its own header says the focus
ring "simply never fired because the rows were never focusable".

**The class does not move.** `FORBIDDEN.md` Part 1 names `.list-item`: the
accessibility shim queries it, `dragSort.js` queries it, and several hundred
declarations style it. The tag moved; the class did not, and this file asserts
both halves because a rename would break two modules silently and a
half-converted row breaks nothing at all until somebody presses Tab.

**Eleven of the twelve, not twelve** — and the twelfth is the premise this row
did not have. `#tool-library-btn` *contains* a `<button>` (`#library-new-doc-btn`,
the inline "+ document" action). A button inside a button is invalid markup, axe
calls it `nested-interactive`, and screen readers disagree about which of the
two they are on. That is the same case `a11y.js` already declines `role="button"`
for, so the shim's rule and this row's exception are one decision rather than
two. It stays a `<div>`, focusable through the shim exactly as it was.

A `<button>` does not look like a `<div>` without help, and the help is the
second half of the change: the UA paints `color: buttontext`, a 13.333px system
font and `text-align: center`, so eleven converted rows would have rendered a
different colour, a different face and centred beside the session rows below
them — which are still `<div>`s and always will be, because those are the ones
that contain nested buttons. Those six declarations are asserted here for the
same reason the tag is: nothing else would catch it but a screenshot.
"""

import re
from pathlib import Path

from tests.helpers.source_text import blank

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = blank(ROOT / "static" / "style.css")

# The eleven that convert. Named rather than derived, so a row silently
# dropping out of the sidebar fails here instead of shrinking the assertion.
_AS_BUTTONS = [
    "sidebar-new-chat-btn",
    "sidebar-search-btn",
    "tool-memory-btn",
    "tool-calendar-btn",
    "tool-compare-btn",
    "tool-cookbook-btn",
    "tool-research-btn",
    "tool-gallery-btn",
    "tool-notes-btn",
    "tool-tasks-btn",
    "tool-theme-btn",
]
_STAYS_A_DIV = "tool-library-btn"

_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


def _rows() -> dict:
    """id -> (tag, inner markup) for every element whose class is exactly
    `list-item`, resolved by walking to its own closing tag.

    `Law 20` option 2. A substring search for `<button class="list-item"`
    cannot tell how far the element reaches, and "does this row contain a
    button" is a question about the element's contents and nothing else's.
    """
    out = {}
    for m in re.finditer(r'<(div|button)\b([^>]*\bclass="list-item"[^>]*)>', INDEX):
        tag = m.group(1)
        ident = re.search(r'id="([^"]+)"', m.group(2))
        if not ident:
            continue
        i, depth = m.end(), 1
        while depth and i < len(INDEX):
            t = re.search(r"<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>", INDEX[i:])
            if not t:
                raise AssertionError(f"unbalanced markup after #{ident.group(1)}")
            name = t.group(2).lower()
            closing = t.group(1) == "/"
            selfclosing = t.group(4) == "/" or name in _VOID
            if name == tag:
                depth += -1 if closing else (0 if selfclosing else 1)
            i += t.end()
        out[ident.group(1)] = (tag, INDEX[m.end(): i - len(f"</{tag}>")])
    return out


def _rule(selector_line: str) -> str:
    """The one rule whose selector list starts with this exact line."""
    pattern = r"(?:^|\})[ \t\n]*" + re.escape(selector_line) + r"[^{}]*\{"
    found = [
        CSS[m.end(): CSS.index("}", m.end())]
        for m in re.finditer(pattern, CSS, re.MULTILINE)
    ]
    assert len(found) == 1, f"expected one `{selector_line}` rule, found {len(found)}"
    return found[0]


def _decl(block: str, prop: str):
    m = re.search(rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;}}]+)", block)
    return m.group(1).strip() if m else None


def test_the_eleven_action_rows_are_buttons():
    rows = _rows()
    wrong = {i: rows[i][0] for i in _AS_BUTTONS if i in rows and rows[i][0] != "button"}
    missing = [i for i in _AS_BUTTONS if i not in rows]
    assert not missing, f"rows vanished from the sidebar: {missing}"
    assert not wrong, (
        f"these rows are still `<div>`: {wrong}. A div is not in the tab order "
        "and is not announced as anything, which is the whole row."
    )


def test_the_class_did_not_move():
    """`FORBIDDEN.md` Part 1. The shim and `dragSort.js` both query it."""
    rows = _rows()
    for ident in _AS_BUTTONS + [_STAYS_A_DIV]:
        assert ident in rows, f"#{ident} no longer carries `class=\"list-item\"`"
    assert 'querySelectorAll(itemSelector)' in (
        ROOT / "static" / "js" / "dragSort.js"
    ).read_text(encoding="utf-8"), "dragSort.js no longer queries by selector"
    assert "'#sidebar .list-item'" in (
        ROOT / "static" / "js" / "a11y.js"
    ).read_text(encoding="utf-8"), "the a11y shim no longer queries `.list-item`"


def test_the_converted_rows_are_type_button():
    """Without `type`, a `<button>` inside a form submits it. None of these is
    in a form today, which is exactly the kind of fact that changes later and
    takes a whole page's state with it."""
    for ident in _AS_BUTTONS:
        m = re.search(rf'<button\b([^>]*\bid="{re.escape(ident)}"[^>]*)>', INDEX)
        assert m, f"#{ident} is not a button"
        assert 'type="button"' in m.group(1), f"#{ident} has no explicit type"


def test_no_converted_row_contains_another_control():
    """`nested-interactive`. A button inside a button is invalid, and the row
    that has one is the row that stays a div."""
    rows = _rows()
    offenders = {}
    for ident in _AS_BUTTONS:
        inner = rows[ident][1]
        nested = re.findall(r"<(button|a|input|select|textarea)\b", inner, re.I)
        if nested:
            offenders[ident] = nested
    assert not offenders, (
        f"converted rows contain nested controls: {offenders}. Convert the row "
        "back to a `<div>` and say why, the way `#tool-library-btn` does."
    )


def test_the_library_row_stays_a_div_and_says_why():
    rows = _rows()
    tag, inner = rows[_STAYS_A_DIV]
    assert tag == "div", (
        f"#{_STAYS_A_DIV} became a `<{tag}>` — it contains "
        "`#library-new-doc-btn`, so that is a button inside a button"
    )
    assert re.search(r"<button\b", inner, re.I), (
        f"#{_STAYS_A_DIV} no longer contains a nested button, so the exception "
        "it is granted no longer has a reason. Convert it and delete this test."
    )
    before = INDEX[: INDEX.index(f'id="{_STAYS_A_DIV}"')]
    assert "nested-interactive" in before[-1200:], (
        "the exception has lost its explanation; the next person to read this "
        "markup sees eleven buttons and one div and no reason for the odd one"
    )


def test_a_button_row_is_dressed_down_to_match_the_div_rows():
    """Six declarations, and each undoes one UA default that would otherwise be
    visible beside the session rows — which stay `<div>` because they are the
    ones with nested buttons in them."""
    block = _rule(".list-item,")
    expected = {
        "appearance": "none",
        "font-family": "inherit",
        "color": "inherit",
        "text-align": "left",
        "width": "100%",
    }
    for prop, value in expected.items():
        got = _decl(block, prop)
        assert got == value, (
            f"`.list-item` sets `{prop}: {got}`, expected `{value}` — without "
            "it a converted row renders differently from the `<div>` rows "
            "beside it"
        )
    assert _decl(block, "font-size") == "13px", (
        "the row's own font-size must survive the `font-family: inherit` that "
        "sits beside it"
    )


def test_the_dynamic_session_rows_are_still_divs():
    """`Law 1` and the reason the class is forbidden from moving: session rows
    are built by `sessions.js` and they *contain* buttons. Converting those is
    not this row's job and would be the nested-interactive defect at scale."""
    sessions = (ROOT / "static" / "js" / "sessions.js").read_text(encoding="utf-8")
    made = re.findall(r"createElement\('(\w+)'\)[^;]{0,200}?list-item", sessions)
    assert "button" not in made, (
        "a session row is being built as a `<button>`; those rows carry "
        "rename, star and delete controls inside them"
    )
