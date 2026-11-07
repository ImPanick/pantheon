# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1759`–`B1764` — the cockpit's alignment audit of 2026-11-07, held.

The owner, 2026-11-07, with a picture of the workspace's layout pill and a
pane's Float / Fill / Close: *"We still have alignment issues."* Every view was
swept in Chromium at 1440, 1024, 820, 412 and 360 wide, light and dark, and
each control's box was measured against its row, its icon and its
neighbours: ninety findings across the workspace, the rail's windows,
Settings, the composer, the chat and the left rail. Each was fixed and swept
again. Those numbers are in the rows; what is pinned here is the shape of
each fix, so a later rule cannot quietly undo it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COCKPIT = (ROOT / "static" / "cockpit.css").read_text(encoding="utf-8")
WORKSPACE = (ROOT / "static" / "js" / "cockpitWorkspace.js").read_text(encoding="utf-8")
RAIL_JS = (ROOT / "static" / "js" / "cockpit.js").read_text(encoding="utf-8")
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

SLICES = ("workspace", "rail", "settings", "composer", "chat", "sidebar")


def test_the_braces_balance():
    assert COCKPIT.count("{") == COCKPIT.count("}")


def test_each_slice_has_its_own_section_in_order():
    at = [COCKPIT.index(f"/* ── alignment audit 2026-11-07: {s} ──") for s in SLICES]
    assert at == sorted(at), dict(zip(SLICES, at))


# ── B1759: the workspace ─────────────────────────────────────────────────────

def test_an_icon_button_of_the_workspace_holds_its_icon_in_the_middle():
    """Red before: style.css's `button { padding: 0 10px }` pushed the layout
    pill's glyphs, the tuck chevron and Float / Fill / Close 3-4px right."""
    assert re.search(
        r"html\.cockpit \.ck-layouts button,\s*html\.cockpit \.ck-ibtn \{ padding: 0 !important; min-width: 0; \}",
        COCKPIT)


def test_side_by_side_stacks_as_rows_while_a_pane_would_be_too_narrow():
    assert "const MIN_PANE_W = 260;" in WORKSPACE
    body = re.search(r"function fitLayout\(lay, n\) \{(.*?)\n\}", WORKSPACE, flags=re.S).group(1)
    assert "< MIN_PANE_W ? 'rows' : lay" in body
    # The person's choice is kept: only the grid falls back.
    assert "W.layout =" not in body
    assert "new ResizeObserver(refit).observe(ws)" in WORKSPACE


def test_a_floated_window_lands_whole_on_screen():
    assert "window.innerWidth - cw - 20" in WORKSPACE
    assert "window.innerHeight - ch - 20" in WORKSPACE


def test_a_fresh_tablet_starts_with_the_workspace_tucked():
    fresh = re.search(r"\} else if \(window\.matchMedia\('\(max-width: 1023px\)'\)\.matches\) \{(.*?)\}",
                      WORKSPACE, flags=re.S)
    assert fresh and "W.off = true;" in fresh.group(1)


# ── B1763: the chat ──────────────────────────────────────────────────────────

def test_a_table_frame_hugs_its_rows_and_still_scrolls():
    assert "html.cockpit .msg .body table { width: max-content !important; min-width: 0; max-width: 100%; }" in COCKPIT
    # B1745's sideways scroll is not undone.
    table = re.search(r"html\.cockpit \.msg \.body table \{([^}]*overflow[^}]*)\}", COCKPIT).group(1)
    assert "overflow: auto hidden" in table


def test_the_chat_menu_stays_on_a_narrow_phone():
    """Red before: right-aligned to the ⋯, the 343px menu ran off the left
    side of a phone under 405px wide."""
    assert "window.innerWidth - exportMenu.offsetWidth - 8" in APP
    assert "exportMenu.style.right = Math.max(8, fit) + 'px';" in APP


# ── B1764: the left rail ─────────────────────────────────────────────────────

def test_the_rails_spacer_is_found_as_chromium_reports_it():
    """Red before: the test read `style.flex === '1'`, which Chromium reads
    back as `1 1 0%`, so the spacer stayed and the rail's first button floated
    46-116px under the wordmark."""
    assert "c.style.flexGrow === '1'" in RAIL_JS
    assert "c.style.flex === '1'" not in RAIL_JS


def test_a_rail_label_is_drawn_above_the_chat_bar():
    """The rail sits under the top bar; the collapsed rail's own rule is
    (0,3,2), so only an id selector lifts it, one step over the bar."""
    assert "html.cockpit #icon-rail:is(:hover, :focus-within) { z-index: calc(var(--ck-z-topbar) + 1); }" in COCKPIT
    tokens = re.search(r"--ck-z-rail: (\d+);.*?--ck-z-topbar: (\d+);", COCKPIT, flags=re.S)
    assert tokens and int(tokens.group(1)) < int(tokens.group(2))
