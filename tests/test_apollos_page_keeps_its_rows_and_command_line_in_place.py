# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's page: the fixes from the owner's test of 2026-11-25, and what he
already approved held in place beside them.

His screenshot: a goal's second line spilled over the CHATS heading in the
control pane; the command line was cut off under the board; the bar said
"Apollo" twice (the name, then the space switcher's top layer). Fixed here,
and pinned: the deck's three columns, the control pane in the sidebar's place,
and the Chat / Apollo switch, which he approved and which these fixes must not
move ("no regression", 2026-11-25).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "cockpit.css").read_text(encoding="utf-8")
VIEW = (ROOT / "static" / "js" / "apolloView.js").read_text(encoding="utf-8")
SPACES = (ROOT / "static" / "js" / "apolloSpaces.js").read_text(encoding="utf-8")
SWITCH = (ROOT / "static" / "js" / "modeSwitch.js").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_the_pane_rows_never_squeeze_into_the_next_heading():
    assert re.search(r"html\.cockpit \.apo-control > \*,[^{]*\.apo-deck-goals > \*,[^{]*"
                     r"\.apo-goal > \* \{ flex-shrink: 0; \}", CSS)


def test_the_command_line_keeps_its_room_under_the_deck():
    assert "flex: 1 1 0;" in _rule("html.cockpit.apollo-view .apo-deck")
    assert "flex: none !important" in _rule("html.cockpit.apollo-view .chat-container > .chat-input-bar")


def test_the_bar_names_apollo_once():
    assert "createSwitcher({ topLabel: 'All spaces' })" in VIEW
    assert "const top = topLabel || M.spaceLabel(null);" in SPACES
    assert "menu.appendChild(item(top, null, 0, false));" in SPACES


def test_what_he_approved_stays_where_it_is():
    deck = _rule("html.cockpit.apollo-view .apo-deck")
    assert "grid-template-columns: minmax(220px, 250px) minmax(0, 1fr) minmax(240px, 280px);" in deck
    assert 'grid-template-areas: "rail board needs" "status status status";' in deck
    assert "html.cockpit.apollo-view.apollo-docked .sidebar-inner { display: none !important; }" in CSS
    assert "_btn('chat', 'Chat'," in SWITCH and "_btn('apollo', 'Apollo'," in SWITCH
