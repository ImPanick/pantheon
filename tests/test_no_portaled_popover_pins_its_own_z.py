# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P3-18` — a popover opened from inside a modal has to be visible.

`static/js/toolWindowZOrder.js` already says what goes wrong and why::

    Tool modals get a monotonically increasing z from the bring-to-front
    counter (modalManager), which climbs unbounded over a long session — so the
    hardcoded `z-index: 10001` these dropdowns historically used eventually
    rendered them BEHIND their own modal (#4720).

`topPortalZ()` is the answer: `max(topToolWindowZ(), 10030) + 1`, read live. A
literal cannot keep up with a counter, and 10030 is not arbitrary — it is where
a long-pressed dock chip sits (`.minimized-dock-chip.chip-long-press`).

`tests/test_portal_dropdown_z_js.py` pins that helper's arithmetic, and pins two
named files as having been converted. Two named files is a list, not a rule: it
says nothing about the next dropdown somebody writes. This is the rule. It finds
every element that is portaled to `document.body`, positioned `fixed`, and given
a z-index as a literal, and requires that literal to clear the floor — or to be
named below with the reason it belongs underneath.

`P3-18` found eight that did not, including one sitting on **10001 exactly**,
the value the comment above calls out by name.
"""

import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# `DOCK_OVERLAY_FLOOR` in static/js/toolWindowZOrder.js. Read from the source
# rather than copied, so the two cannot drift apart silently.
_FLOOR_RE = re.compile(r"const DOCK_OVERLAY_FLOOR = (\d+);")

# Elements that are portaled and fixed but are NOT popovers, or are popovers
# that belong *underneath* the window they decorate. Keyed by file and variable.
BELOW_THE_FLOOR_ON_PURPOSE = {
    ("static/js/modalSnap.js", "hint"):
        "the snap-zone hint decorates the window being dragged and must not cover it",
    ("static/js/modalSnap.js", "stripe"):
        "the edge-dock stripe sits just above the modal base layer, by design",
    ("static/js/editor/ai-inpaint.js", "canvasWpEl"):
        "a canvas wrapper inside the editor, not a popover",
    ("static/js/fileHandler.js", "t"):
        "the fallback toast; toasts have their own layer and sit below dialogs",
}


def _floor() -> int:
    src = (_REPO / "static" / "js" / "toolWindowZOrder.js").read_text(encoding="utf-8")
    match = _FLOOR_RE.search(src)
    assert match, "DOCK_OVERLAY_FLOOR is gone from toolWindowZOrder.js"
    return int(match.group(1))


def _js_files() -> list:
    out = subprocess.run(["git", "ls-files", "static/**/*.js", "static/*.js"],
                         cwd=_REPO, capture_output=True, text=True, check=True).stdout
    return [f for f in out.split() if "/lib/" not in f]


_CSSTEXT = re.compile(r"([A-Za-z_$][\w$.]*)\.style\.cssText\s*\+?=\s*(['\"`])([^'\"`]*)\2")
_ZINDEX = re.compile(r"([A-Za-z_$][\w$.]*)\.style\.zIndex\s*=\s*['\"](\d+)['\"]")
_ZVALUE = re.compile(r"z-index:\s*(\d+)")


def _pinned_portal_zs() -> list:
    """(file, line, variable, z) for body-portaled fixed elements with a literal z."""
    found = []
    for rel in _js_files():
        text = (_REPO / rel).read_text(encoding="utf-8")
        lines = text.splitlines()
        portaled = set(re.findall(
            r"document\.body\.appendChild\(\s*([A-Za-z_$][\w$]*)\s*\)", text))
        for i, line in enumerate(lines, 1):
            css = _CSSTEXT.search(line)
            if css and "position:fixed" in css.group(3).replace(" ", ""):
                z = _ZVALUE.search(css.group(3))
                var = css.group(1).split(".")[0]
                if z and var in portaled:
                    found.append((rel, i, var, int(z.group(1))))
                continue
            zi = _ZINDEX.search(line)
            if not zi:
                continue
            var = zi.group(1).split(".")[0]
            if var not in portaled:
                continue
            # `position: fixed` (or a `.modal` class, which the stylesheet fixes
            # for it) set nearby on the same element.
            window_ = "\n".join(lines[max(0, i - 13):i + 12])
            fixed = (
                re.search(rf"{re.escape(var)}\.style\.position\s*=\s*['\"]fixed", window_)
                or re.search(rf"{re.escape(var)}\.className\s*=\s*['\"][^'\"]*\bmodal\b", window_)
                or re.search(rf"{re.escape(var)}\.style\.cssText[^\n]*position:\s*fixed", window_)
            )
            if fixed:
                found.append((rel, i, var, int(zi.group(2))))
    return found


def test_the_floor_is_where_the_dock_chips_are():
    # If the chip layer moves and this does not, every dropdown in the product
    # goes under a dragged chip and nothing says so.
    css = (_REPO / "static" / "style.css").read_text(encoding="utf-8")
    match = re.search(r"\.minimized-dock-chip\.chip-long-press\s*\{[^}]*z-index:\s*(\d+)", css)
    assert match, "the long-press dock chip rule is gone; DOCK_OVERLAY_FLOOR has no anchor"
    assert int(match.group(1)) == _floor()


def test_no_portaled_popover_pins_a_z_below_the_stack_it_competes_with():
    floor = _floor()
    offenders = [
        (rel, line, var, z)
        for rel, line, var, z in _pinned_portal_zs()
        if z <= floor and (rel, var) not in BELOW_THE_FLOOR_ON_PURPOSE
    ]
    assert offenders == [], (
        "these are portaled to document.body and positioned fixed, so they "
        "compete with the tool-window stack directly — and a literal cannot "
        "keep up with a counter that climbs. Use topPortalZ() (a menu) or "
        "nextToolWindowZ() (a window), or name it in "
        f"BELOW_THE_FLOOR_ON_PURPOSE with why it belongs underneath: {offenders}"
    )


def test_the_scan_finds_something(monkeypatch):
    # An empty result would make the test above pass forever. The exemptions are
    # real sites, so finding them proves the scanner still resolves portaled
    # elements, `position: fixed`, and both spellings of setting a z-index.
    found = {(rel, var) for rel, _line, var, _z in _pinned_portal_zs()}
    missing = set(BELOW_THE_FLOOR_ON_PURPOSE) - found
    assert missing == set(), (
        f"the scan no longer finds {missing} — either they were fixed (remove "
        "the exemption) or the scanner stopped seeing this shape"
    )


def test_the_sites_p3_18_converted_read_the_live_stack():
    # Named because each was a specific defect, not because a name is a rule —
    # the rule is the test above. `compare/scoreboard.js` is the one that sat on
    # 10001, the literal `toolWindowZOrder.js` calls out by name.
    converted = {
        "static/js/calendar.js": "nextToolWindowZ()",
        "static/js/compare/scoreboard.js": "nextToolWindowZ()",
        "static/js/compare/index.js": "topPortalZ()",
        "static/js/document.js": "topPortalZ()",
        "static/js/sessions.js": "topPortalZ()",
        "static/js/editor/wire-import.js": "topPortalZ()",
        "static/js/editor/fx/adj-popup.js": "topPortalZ()",
    }
    for rel, call in converted.items():
        src = (_REPO / rel).read_text(encoding="utf-8")
        assert call in src, f"{rel} no longer reads the live stack"
        assert "toolWindowZOrder.js" in src, f"{rel} does not import the helper"


def test_the_fx_menu_and_its_backdrop_take_one_reading():
    # `topPortalZ()` is a live max over what is currently in the document, so
    # calling it twice with an append in between returns two different numbers —
    # and the backdrop, appended first, would come back *above* the menu it is
    # supposed to sit under and dismiss.
    src = (_REPO / "static" / "js" / "editor" / "fx" / "adj-popup.js").read_text(encoding="utf-8")
    body = src[src.index("const _fxZ = topPortalZ();"):]
    body = body[:body.index("const items = [")]
    assert body.count("topPortalZ()") == 1, "the pair must share one reading"
    assert "z-index:' + _fxZ + ';" in body
    assert "String(_fxZ + 1)" in body
