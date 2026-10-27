# SPDX-License-Identifier: AGPL-3.0-or-later
"""The app shell's glyphs, drawn by the server from the one table. `B398`.

`static/js/icons.js` is the glyph table: a module draws a chevron by calling
`chevronPoints(direction)`, and the only chevron geometry in the tree is its
`CHEVRON_POINTS`. The shell could not call it — markup cannot import a module,
and a `<script>` that rewrote the markup after the parser had read it would
flash, which is the cost `B141` paid to remove — so `B292` left the shell
spelling its chevrons out and pinned them to the table with a test. That kept
the copies from drifting; it did not make them one.

Here the server reads the table and draws them. `static/index.html` writes
`points="{{chevron:right}}"` where it used to write the numbers, and
`app_helpers._read_page` renders the page through `render` before it is hashed,
cached and served — so the browser receives finished markup at first paint (no
flash, no script) and the geometry exists once, in `icons.js`.

**What is read, and what is mirrored.** The table's *data* is read out of
`icons.js` — `CHEVRON_POINTS`, the base DOWN polyline, and `_CHEVRON_TURNS`, the
quarter turn (and traversal) for each direction — so a change to either reaches
the shell with no edit here. The rotation that turns one into the other is
eight lines and is mirrored below, because Python cannot run the module; a test
drives `chevronPoints()` in node for every direction and holds this one equal to
it. The base orientation stays DOWN, as `icons.js` explains: fourteen stylesheet
rules and six handlers rotate a chevron whose base points down.

A table that cannot be read leaves the page as written and says so in the log:
an invisible caret is a defect, a shell that answers 500 is an outage.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from src.constants import STATIC_DIR

logger = logging.getLogger(__name__)

ICONS_JS = os.path.join(STATIC_DIR, "js", "icons.js")

_PLACEHOLDER = re.compile(r"\{\{chevron:([a-z]+)\}\}")
_BASE = re.compile(r"export\s+const\s+CHEVRON_POINTS\s*=\s*'([^']+)'")
_TURNS_BLOCK = re.compile(r"const\s+_CHEVRON_TURNS\s*=\s*\{(.*?)\n\};", re.S)
_TURN = re.compile(r"(\w+)\s*:\s*\{\s*angle\s*:\s*(-?\d+)\s*,\s*reverse\s*:\s*(true|false)\s*\}")

_cache: dict = {}


def version() -> tuple:
    """What says the table is still the one the shell was drawn from — part of
    the page cache's key, so an edit to `icons.js` re-draws the shell."""
    try:
        st = os.stat(ICONS_JS)
        return (st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return ()


def _table() -> Optional[dict]:
    """`{direction: points}` for every direction `icons.js` names."""
    key = version()
    if _cache.get("key") == key and "table" in _cache:
        return _cache["table"]
    try:
        with open(ICONS_JS, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError:
        logger.exception("B398: cannot read %s; the shell's chevrons are not drawn", ICONS_JS)
        return None
    base = _BASE.search(src)
    block = _TURNS_BLOCK.search(src)
    turns = _TURN.findall(block.group(1)) if block else []
    if not base or not turns:
        logger.error("B398: %s no longer declares CHEVRON_POINTS and _CHEVRON_TURNS "
                     "as this reader expects; the shell's chevrons are not drawn", ICONS_JS)
        return None
    nums = [int(n) for n in re.split(r"[\s,]+", base.group(1).strip())]
    table = {name: _rotate(nums, int(angle), reverse == "true") for name, angle, reverse in turns}
    _cache.update(key=key, table=table)
    return table


def _rotate(nums: list, angle: int, reverse: bool) -> str:
    """`icons.js` `chevronPoints`, for a quarter turn about the 24-box's centre."""
    cos = {0: 1, 90: 0, 180: -1, 270: 0}[angle % 360]
    sin = {0: 0, 90: 1, 180: 0, 270: -1}[angle % 360]
    out = []
    for i in range(0, len(nums), 2):
        x, y = nums[i] - 12, nums[i + 1] - 12
        out.append(f"{12 + x * cos - y * sin} {12 + x * sin + y * cos}")
    if reverse:
        out.reverse()
    return " ".join(out)


def chevron_points(direction: str = "down") -> Optional[str]:
    table = _table()
    return table.get(direction) if table else None


def render(html: str) -> str:
    """The page with every `{{chevron:<direction>}}` drawn. A direction the
    table does not name is left as written and logged, like an unreadable
    table — the same answer `chevronPoints` gives it, which is to refuse."""
    if "{{chevron:" not in html:
        return html
    table = _table()
    if not table:
        return html

    def draw(m):
        got = table.get(m.group(1))
        if got is None:
            logger.error("B398: the shell asks for a chevron '%s' that icons.js does not draw",
                         m.group(1))
            return m.group(0)
        return got

    return _PLACEHOLDER.sub(draw, html)
