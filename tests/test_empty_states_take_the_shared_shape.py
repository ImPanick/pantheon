# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B730` — the inventory of hand-made empty states only goes down.

`P9-07` wrote the one empty state (`ui.renderEmptyState`, three kinds — nothing
yet, nothing matched, it broke — each with its way out) and `B730` inventoried
the rest of the product's empty states rather than leave them as an implied
promise. A list brought onto the shared shape passes its old class as
`className:` in an object literal, so it leaves this census; a new list that
draws its own `*-empty` line joins it. This holds the number where it is, so
the second is a decision someone sees and the first is a line lowered here.

Scope (`Law 5`, the row's own): class names containing `empty` written as a
`class="…"` attribute, a `classList.add(…)` argument or a `className = '…'`
assignment, in `static/**/*.js` outside `static/lib/**` and in
`static/*.html`, with comments blanked (`tests/helpers/source_text.py`) —
minus `ui.js`'s own `empty-state*` classes, which are the shared shape.

Measured 2026-10-27 after the Brain's memory list and the notes list moved
onto the shape (`tests/test_a_list_says_which_empty_it_is.py`): the ceiling
below. The surfaces that remain are the row's to work through; `admin.js` is
`B732`'s and the Library modal's `doclib-empty` is `B734`/`P9-14`'s.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.helpers.source_text import blank

ROOT = Path(__file__).resolve().parents[1]

#: Sites, not names. Lower it when a list moves onto the shared shape.
CEILING = 53   # 58 before the Brain's list and the notes list moved

_ATTR = re.compile(r'class="([^"]*)"')
_ADD = re.compile(r"classList\.add\(([^)]*)\)")
_ASSIGN = re.compile(r"className\s*=\s*(['\"])([^'\"]*)\1")
_QUOTED = re.compile(r"['\"]([^'\"]+)['\"]")


def _files():
    js = [p for p in (ROOT / "static").rglob("*.js") if "static/lib/" not in p.as_posix()]
    return sorted(js) + sorted((ROOT / "static").glob("*.html"))


def census() -> list[tuple[str, str]]:
    found = []
    for path in _files():
        text = blank(path)
        names = []
        for m in _ATTR.finditer(text):
            names += m.group(1).split()
        for m in _ADD.finditer(text):
            names += _QUOTED.findall(m.group(1))
        for m in _ASSIGN.finditer(text):
            names += m.group(2).split()
        rel = path.relative_to(ROOT).as_posix()
        for name in names:
            if "empty" not in name or "${" in name:
                continue
            if rel == "static/js/ui.js" and name.startswith("empty-state"):
                continue
            found.append((rel, name))
    return found


def test_no_new_hand_made_empty_state():
    sites = census()
    assert len(sites) <= CEILING, (
        f"{len(sites)} hand-made empty-state class sites (ceiling {CEILING}). Draw a new "
        "list's empty state with ui.renderEmptyState — empty, filtered or error, and the "
        "way out of it — rather than a line of its own.")


def test_the_lists_moved_onto_the_shape_stay_there():
    files = {f for f, _ in census()}
    names = {n for _, n in census()}
    assert "notes-empty-msg" not in names, "the notes list draws its own empty line again"
    memory = [n for f, n in census() if f == "static/js/memory.js"]
    # Three remain, and none is an empty state of the memory list: its loading
    # row (a fourth state, not an empty one), the import's suggestion box and
    # the chat-extraction box (`Nothing to keep from this chat.`).
    assert len(memory) <= 3, memory
    assert "static/js/ui.js" not in files
