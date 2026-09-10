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


# ── the CSS half, added by `B65` ──────────────────────────────────────────────
#
# The scan above reads **JavaScript**. `B65` slipped through it for months
# because `.cp-popover` pins its z-index in **style.css** — the JS only appends
# the element to `document.body` and sets `left`/`top`. A rule that looks in one
# language cannot see a defect that lives in the other, and this is the same
# lesson as `Law 20` pointed sideways: the test was reading the wrong file.

_CLASS_ASSIGN = re.compile(
    r"([A-Za-z_$][\w$]*)\.className\s*=\s*['\"]([^'\"]+)['\"]")


def _css_pinned_portal_zs() -> list:
    """(file, class, z) for classes JS portals to body whose z is pinned in CSS.

    Only flags a class when the JS **never** sets `.style.zIndex` on that
    element: a stylesheet fallback beneath a live reading is fine, and is what
    `.cp-popover` does now.
    """
    css = (_REPO / "static" / "style.css").read_text(encoding="utf-8")
    found = []
    for rel in _js_files():
        text = (_REPO / rel).read_text(encoding="utf-8")
        portaled = set(re.findall(
            r"document\.body\.appendChild\(\s*([A-Za-z_$][\w$]*)\s*\)", text))
        for var, classes in _CLASS_ASSIGN.findall(text):
            if var not in portaled:
                continue
            if re.search(rf"{re.escape(var)}\.style\.zIndex\s*=", text):
                continue  # JS sets it live; the stylesheet value is a fallback
            if re.search(rf"{re.escape(var)}\.style\.setProperty\(\s*['\"]z-index['\"]",
                         text):
                continue  # the other spelling of the same thing (notes.js uses it)
            for cls in classes.split():
                rule = re.search(rf"\.{re.escape(cls)}\s*\{{([^}}]*)\}}", css)
                if not rule:
                    continue
                body = rule.group(1)
                if "position: fixed" not in body.replace(";", "; "):
                    continue
                z = _ZVALUE.search(body)
                if z:
                    found.append((rel, cls, int(z.group(1))))
    return found


# The CSS half of `BELOW_THE_FLOOR_ON_PURPOSE`, keyed the same way: file and
# name, with the reason it belongs underneath. `B65` opened this list with nine
# names it had not yet converted; `P3-24` converted eight of them and this is the
# one that is genuinely meant to sit low.
#
# It is a reasoned exemption, not a ratchet, because a ratchet with one entry is
# a place to hide the tenth. A name may only be added here with a reason someone
# can argue with.
CSS_BELOW_THE_FLOOR_ON_PURPOSE = {
    ("static/js/theme.js", "theme-zone-highlight"):
        "it outlines page elements to show where a theme colour lands, and "
        "skips anything inside #theme-modal on purpose — drawn over the modal "
        "it was opened from, the highlight would be noise rather than a guide",
}


def test_no_portaled_popover_pins_its_z_in_the_stylesheet_either():
    """`B65`. `.cp-popover` was `position: fixed; z-index: 10000` in style.css
    and portaled to `document.body` by `colorPicker.js`, which set no z at all.

    `ui.js` promotes every visible `.modal` with an `!important` z from a
    counter that only climbs, and `#styled-confirm-overlay` is a `.modal` at
    99999 — so the first styled confirm of a session latches that counter to
    100000, and every modal after it outranks a literal 10000 for the rest of
    the page's life. The colour picker opened behind the card it was opened
    from, on every row, permanently."""
    floor = _floor()
    offenders = [(rel, cls, z) for rel, cls, z in _css_pinned_portal_zs()
                 if z <= floor and (rel, cls) not in CSS_BELOW_THE_FLOOR_ON_PURPOSE]
    assert offenders == [], (
        "these are portaled to document.body by JS and given a fixed position "
        "and a literal z-index by the stylesheet, so they compete with a "
        "counter that climbs past them. Set the z from topPortalZ() when the "
        f"element is shown: {offenders}"
    )


def test_the_css_scan_can_actually_see_the_shape_it_looks_for():
    """An empty result would make the test above pass forever. `.cp-popover` is
    still portaled and still styled `position: fixed` in CSS — what changed is
    that JS now sets its z live, which is exactly the exemption being asserted."""
    css = (_REPO / "static" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"\.cp-popover\s*\{([^}]*)\}", css)
    assert rule and "position: fixed" in rule.group(1), (
        ".cp-popover is no longer a fixed-position rule; this scan has lost its anchor")
    picker = (_REPO / "static" / "js" / "colorPicker.js").read_text(encoding="utf-8")
    assert "document.body.appendChild(p)" in picker, "the popover is no longer portaled"
    assert re.search(r"p\.className\s*=\s*'cp-popover'", picker), (
        "the popover no longer takes its class the way the scan detects")


def test_the_colour_picker_reads_the_live_stack():
    """The import is asserted as a real `import` statement, not as a substring.

    The fix's own comment names both `topPortalZ` and `toolWindowZOrder.js` while
    explaining why they are there, so a substring test passes with the import
    deleted — and a deleted import is a `ReferenceError` on the first open that
    `node --check` cannot see. Mutation testing caught exactly that (`Law 20`,
    and my own trap for the fourth time this week)."""
    picker = (_REPO / "static" / "js" / "colorPicker.js").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in picker.splitlines() if not ln.lstrip().startswith("//"))
    assert re.search(
        r"^import\s*\{[^}]*\btopPortalZ\b[^}]*\}\s*from\s*['\"]\./toolWindowZOrder\.js['\"]",
        code, re.M), "colorPicker.js no longer imports topPortalZ"
    assert re.search(r"_popover\.style\.zIndex\s*=\s*String\(topPortalZ\(\)\)", code)


def test_the_stylesheet_fallback_clears_the_dock_floor():
    """It only applies between append and open, but if it is below the floor it
    is below a dragged dock chip — and the whole point is that a literal under
    the floor is never right for a portaled popover."""
    css = (_REPO / "static" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"\.cp-popover\s*\{([^}]*)\}", css)
    z = _ZVALUE.search(rule.group(1))
    assert z and int(z.group(1)) > _floor()


def test_a_modal_pinned_at_99999_is_what_latches_the_counter():
    """The mechanism, named so nobody re-derives it. `#styled-confirm-overlay`
    is created with `className = 'modal'`, appended to body, and styled
    `z-index: 99999 !important` — so `ui.js`'s promote counter, which takes a
    max over every visible `body > .modal`, jumps to six figures the first time
    a styled confirm is shown and never comes back down."""
    ui = (_REPO / "static" / "js" / "ui.js").read_text(encoding="utf-8")
    assert "overlay.id = 'styled-confirm-overlay'" in ui
    assert re.search(r"overlay\.className\s*=\s*'modal'", ui)
    assert "document.body.appendChild(overlay)" in ui
    css = (_REPO / "static" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"#styled-confirm-overlay\s*\{([^}]*)\}", css)
    assert rule and re.search(r"z-index:\s*99999", rule.group(1))


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


def test_every_css_exemption_is_still_a_real_site():
    """The counterpart to `test_the_scan_finds_something`, for the CSS half.

    An exemption that no longer names anything the scan finds makes the test
    above pass forever — either the site was fixed (delete the entry) or the
    scanner stopped seeing the shape, and those must not look the same. `B65`
    got through for months precisely because the JS-side rule was reading a
    population that did not include it."""
    floor = _floor()
    found = {(rel, cls) for rel, cls, z in _css_pinned_portal_zs() if z <= floor}
    missing = set(CSS_BELOW_THE_FLOOR_ON_PURPOSE) - found
    assert missing == set(), (
        f"{missing} is exempted from the stylesheet rule but the scan no longer "
        "finds it below the floor — remove the entry, or find out why the scan "
        "went blind")


def test_p3_24_converted_the_population_b65_found():
    """`P3-24`. Named because each was a specific site, not because a name is a
    rule — the rule is `test_no_portaled_popover_pins_its_z_in_the_stylesheet_either`.

    `sessions.js` is the one worth remembering: it already imported the helper
    and set the z on the *mobile long-press* path, so a file-level "this file
    reads the live stack" skip in the scanner marked it clean while the desktop
    open path — the one nearly everybody uses — set no z at all. A scan that
    exempts a whole file exempts the bug in it."""
    converted = {
        "static/js/chatRenderer.js": ("attach-lightbox, vision-editor-overlay, ctx-detail-popup", 3),
        "static/js/cookbookRunning.js": ("cookbook-edit-overlay", 2),
        "static/js/cookbookServe.js": ("cookbook-gpu-popup", 5),
        "static/js/document.js": ("doc-suggestion-card", 5),
        "static/js/notes.js": ("tour-hint", 3),
        "static/js/sessions.js": ("session-dropdown-menu, session-folder-submenu", 3),
        "static/js/slashAutocomplete.js": ("slash-autocomplete-popup", 1),
        "static/js/slashCommands.js": ("tour-halo", 12),
        "static/js/tourHints.js": ("tour-hint", 1),
        "static/js/compare/selector.js": ("compare-probe-overlay", 1),
        "static/js/editor/slider-ux.js": ("ge-slider-bubble", 1),
    }
    for rel, (what, sites) in converted.items():
        src = (_REPO / rel).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))
        helper = "./toolWindowZOrder.js" if rel.count("/") == 2 else "../toolWindowZOrder.js"
        assert re.search(
            r"^import\s*\{[^}]*\btopPortalZ\b[^}]*\}\s*from\s*['\"]"
            + re.escape(helper) + r"['\"]", code, re.M), (
            f"{rel} no longer imports topPortalZ ({what})")
        assert code.count("topPortalZ()") >= sites, (
            f"{rel} reads the live stack fewer than {sites} times ({what})")


def test_the_submenu_outranks_the_dropdown_it_flies_out_of():
    """`topPortalZ()` counts only `body > .modal / .research-overlay /
    .notes-pane-backdrop`, so a portaled dropdown does not raise the number the
    next call returns. The session folder submenu and the session dropdown would
    take the *same* z, and the submenu — appended first — would lose on DOM
    order and open behind the menu it flew out of."""
    src = (_REPO / "static" / "js" / "sessions.js").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))
    assert "sub.style.zIndex = String(topPortalZ() + 1);" in code
    assert "dropdown.style.zIndex = String(topPortalZ());" in code
    assert code.index("document.body.appendChild(sub)") < code.index(
        "document.body.appendChild(dropdown)"), (
        "the submenu is no longer appended first, so the tie this guards "
        "against may now break the other way — re-derive the +1")
