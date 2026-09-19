# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-05` — the row closes as done, and the evidence is that nothing was built.

The row was already carrying one dated correction (*"both views already
exist"*). Re-measured 2026-09-19, the half it kept open — *"what is missing is
the full-view presentation, not the feature"* — is **also** already satisfied,
by machinery that post-dates the row:

  * **Compare was never in a box.** `static/js/compare/index.js` renders the
    N-way comparison into `#chat-container`, the main content area, by hiding
    that container's existing children (`"preserves event listeners"`, the
    constraint the row cites, at `:331-339` — it said `:328-336`). The
    ~780px draggable thing the row worries about is `#compare-model-overlay`,
    which `compare/selector.js:69` builds and which is the **model picker**, not
    the comparison. There is no view to promote and the promotion the row
    describes is the rework `FORBIDDEN.md` protects against.
  * **Calendar already goes true full-screen.** `static/js/tileManager.js`
    listens on `document` for a header drag — `_findDragTarget` matches any
    `.modal-header` inside a `.modal`, which `#calendar-modal` is — and
    `_zoneForPointer` returns a `fullscreen` zone covering the whole viewport
    the moment the cursor passes `y <= 0`, with a `maximize` zone just below it.
    Three windows are deliberately narrowed (`settings-modal` to `right-half`;
    `cookbook-modal` and `theme-modal` to `fullscreen` only). Calendar is not
    one of them.

AND THE THING THAT MADE THIS LOOK UNDONE IS A DEAD OPTION.
`static/js/windowDrag.js:65` reads `const enableFullscreen = false;` — a
constant, three lines under a JSDoc that says *"enableFullscreen: bool — enable
top-edge fullscreen snap. Default true when onEnterFullscreen is supplied"*. The
option is never read from `options`, so `_enterFs` has no caller in the product,
`_showSnapHint` can never fire for the top band, and `memory.js`'s
`onEnterFullscreen` callback and `documentLibrary.js`'s explicit
`enableFullscreen: false` are both arguing about a branch that cannot run. It is
inherited — it reads the same at the fork point — and it is `Law 14`'s second
implementation, the one that went stale. Filed, not deleted (`Law 1`).

This file exists so the closure cannot rot: if Compare ever stops rendering into
`#chat-container`, or Calendar is ever excluded from the tiling zones, the row
becomes real again and these assertions say so.
"""

import re
from pathlib import Path

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
TILE_JS = JS / "tileManager.js"
DRAG_JS = JS / "windowDrag.js"


def test_the_comparison_renders_into_the_main_content_area_not_a_window():
    """The Compare half of the row, measured. `#chat-container` is the main
    area; a view that owns it is already the fullest view in the app."""
    src = (JS / "compare" / "index.js").read_text(encoding="utf-8")
    hide = src[src.index("Hide existing chat container children"):]
    hide = hide[:hide.index("container.classList.add('compare-active')")]
    assert "getElementById('chat-container')" in hide
    assert "preserves event listeners" in src[:src.index("Hide existing chat container children") + 80]
    # And the draggable overlay the row worries about is the picker.
    sel = (JS / "compare" / "selector.js").read_text(encoding="utf-8")
    assert "overlay.id = 'compare-model-overlay'" in sel


def test_any_window_with_a_header_can_be_dragged_to_true_fullscreen():
    """The Calendar half. The gesture is owned by `tileManager`, on `document`,
    for every `.modal-header` in a `.modal` — which is what makes this a
    property of the product rather than of one tool."""
    src = TILE_JS.read_text(encoding="utf-8")
    finder = js_function(src, "function _findDragTarget")
    assert ".modal-header" in finder
    assert "closest('.modal, .research-overlay')" in finder
    zones = js_function(src, "function _zoneForPointer")
    assert re.search(r"if \(y <= 0\) \{[\s\S]{0,200}name: 'fullscreen'", zones), (
        "dragging over the top edge no longer maximises a window"
    )
    assert "name: 'maximize'" in zones


def test_the_calendar_is_not_one_of_the_windows_excluded_from_tiling():
    """Three are narrowed on purpose. If Calendar ever joins them, its full view
    goes away and this row reopens."""
    narrowed = js_function(TILE_JS.read_text(encoding="utf-8"), "function _zoneForContent")
    assert "settings-modal" in narrowed and "cookbook-modal" in narrowed and "theme-modal" in narrowed
    assert "calendar-modal" not in narrowed
    # And the calendar modal really does carry the markup the finder needs.
    cal = (JS / "calendar.js").read_text(encoding="utf-8")
    shell = cal[cal.index("_modal.id = 'calendar-modal'"):]
    shell = shell[:shell.index("document.body.appendChild(_modal)")]
    assert 'class="modal-content cal-modal-content"' in shell
    assert 'class="modal-header"' in shell


def test_windowdrags_own_fullscreen_branch_is_dead_and_says_otherwise():
    """The finding the row's Calendar half actually produced, pinned so that
    closing the row does not bury it. Two statements about the same option, in
    the same file, twenty-eight lines apart, that contradict each other."""
    src = DRAG_JS.read_text(encoding="utf-8")
    assert "Default true when onEnterFullscreen is supplied" in src, (
        "the JSDoc promise moved; re-read the option table"
    )
    body = js_function(src, "export function makeWindowDraggable")
    assert "const enableFullscreen = false;" in body, (
        "windowDrag's fullscreen gate is no longer a constant — if it now reads "
        "`options.enableFullscreen`, the branch is live and B812 can close"
    )
    assert "options.enableFullscreen" not in body, (
        "the documented option is still never read"
    )
    # Which makes both of its callers arguments about a branch that cannot run.
    assert "onEnterFullscreen" in (JS / "memory.js").read_text(encoding="utf-8")
    assert "enableFullscreen: false" in (JS / "documentLibrary.js").read_text(encoding="utf-8")


def test_the_calendar_did_not_grow_a_second_way_to_go_fullscreen():
    """`Law 14`, as a test. The obvious fix for this row was to hand Calendar
    the Brain's `onEnterFullscreen` callback; it would have wired a real
    behaviour to a dead branch and shipped looking done."""
    cal = (JS / "calendar.js").read_text(encoding="utf-8")
    call = cal[cal.index("makeWindowDraggable(_modal"):]
    call = call[:call.index("\n    }")]
    assert "onEnterFullscreen" not in call
    assert "fsClass" not in call
