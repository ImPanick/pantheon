# SPDX-License-Identifier: AGPL-3.0-or-later
"""`H21` — the `.search-fallback-chain` cluster, styling for chips nothing drew.

`H21` named it among the dead weight safe to delete on its own evidence, and
its third correction re-measured it: one block in `static/style.css`
(`.search-fallback-chain`, `.search-fb-chip`, `-grip`, `-logo`, `-remove`,
`-add`) for a drag-to-reorder chip row that was never built. Settings' search
fallback chain is drawn by `settings.js:_renderFallbackChain` as a list of
`.settings-fallback-row`s. Re-measured on the day it was deleted
(2026-10-27): no JS, HTML or test named any of those classes.

Read with the comments blanked (`Law 20`): the note left where the block was
names it, and a note is not a rule.
"""
import re
from pathlib import Path

from tests.helpers.source_text import blank

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "static" / "style.css"
SETTINGS = ROOT / "static" / "js" / "settings.js"

_DEAD = re.compile(r"\.search-(?:fallback-chain|fb-[\w-]+)\b")


def test_no_rule_styles_the_chips_nothing_drew():
    css = blank(STYLE)
    assert _DEAD.findall(css) == []


def test_the_fallback_chain_settings_does_draw_keeps_its_rules():
    """The widget that is drawn is untouched: every class its renderer writes
    still has a rule."""
    drawn = set(re.findall(r"className\s*=\s*'(settings-fallback-[\w-]+)'", blank(SETTINGS)))
    assert {"settings-fallback-row", "settings-fallback-num", "settings-fallback-remove"} <= drawn
    css = blank(STYLE)
    assert all(re.search(rf"\.{name}\b", css) for name in drawn), drawn
