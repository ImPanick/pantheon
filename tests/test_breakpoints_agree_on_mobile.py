# SPDX-License-Identifier: AGPL-3.0-or-later
"""P3-07 — one number decides what "mobile" means, and one place disagreed.

`768px` is where this product switches to its mobile layout: 89 `@media
(max-width: 768px)` blocks and 14 `(min-width: 769px)` blocks in
`static/style.css`, the pre-paint script in `index.html`, and **105 JavaScript
tests** of `innerWidth` against the same number.

Two places did not.

`static/style.css` stacked the image editor at `max-width: 700px` — 558 lines,
72 selectors, every one of them the editor. Between 701 and 768 the app was in
its mobile layout while the editor kept the desktop three-column body that
block exists to unstack, which its own comment says ends with a zero-width
canvas.

Seven JavaScript sites said 700 too, and two of them mattered more than the
stylesheet did. `sidebar-layout.js` disagreed **with itself**: seven tests in
that file say 768 — including the one that shows the mobile backdrop — and
three said 700, among them the click-outside-to-close handler. Between 700 and
767 the sidebar was an overlay with a backdrop inviting the click that dismisses
it, and the handler for that click returned early. `calendar.js` remembered
whether to restore the sidebar at `>= 700`, under a comment saying that is what
desktop means and that on mobile the sidebar is one the user closed on purpose;
in the same band, closing the calendar popped it back. Both are `B50`.

`static/js/editor/build/right-panel.js` had four more, and they are the reason
moving only the stylesheet would have been a half-fix: they arm the editor's
swipe-to-dismiss and re-parent its controls panel, so at 701–768 the CSS would
have laid the panel out as a sheet that no gesture could dismiss.

**The row's "20px dead zone (701–719)" is withdrawn, with evidence.** The
`min-width: 720px` block it refers to holds one declaration —
`.ge-shortcuts-grid { grid-template-columns: repeat(4, 1fr) }` — and it is
paired not with a `max-width` but with an unconditional base rule two lines
above that sets two columns. Below 720 the base applies; at and above it the
media block does. No width is uncovered.

**And "canonicalise to three" is not what this fixes.** The remaining widths —
420, 460, 480, 520, 540, 600, 640, 820 — reflow individual components inside
modals and panels rather than switching the shell, and forcing them onto a
three-value grid would change when those components reflow to buy consistency
in a number nobody reads. What was worth fixing is the disagreement about where
mobile ends, and that is what this pins.
"""
import pathlib
import re
from tests.helpers.source_text import blank, blank_text  # B290

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = blank(ROOT / "static" / "style.css")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

MOBILE_MAX = 768
DESKTOP_MIN = 769

# Widths that legitimately differ: they reflow a component, not the shell.
COMPONENT_WIDTHS = {420, 460, 480, 520, 540, 600, 640, 720, 820, 821}


def _media_widths():
    out = []
    for m in re.finditer(r"@media[^{]*\{", CSS):
        for kind, px in re.findall(r"(max-width|min-width)\s*:\s*(\d+)px", m.group(0)):
            out.append((kind, int(px)))
    return out


def test_the_extractor_finds_the_breakpoints():
    widths = _media_widths()
    assert len(widths) > 100, len(widths)
    assert ("max-width", MOBILE_MAX) in widths


def test_the_shell_switches_at_one_width():
    """Any max-width between the largest component breakpoint and the desktop
    floor is claiming to be the shell's mobile boundary, and there is one."""
    shell = {px for kind, px in _media_widths()
             if kind == "max-width" and px not in COMPONENT_WIDTHS}
    assert shell == {MOBILE_MAX}, (
        f"more than one width claims to be where mobile ends: {sorted(shell)}"
    )


def test_the_desktop_floor_is_one_more_than_the_mobile_ceiling():
    """`max-width: 768` and `min-width: 769` must stay adjacent or a viewport
    exactly 768.5 CSS pixels wide — a real thing on fractional-scale
    displays — matches both, or neither."""
    mins = {px for kind, px in _media_widths()
            if kind == "min-width" and px not in COMPONENT_WIDTHS}
    assert mins == {DESKTOP_MIN}, sorted(mins)


def test_the_pre_paint_script_uses_the_same_number():
    """It runs before any stylesheet and decides whether to hide the sidebar; a
    different number there is a flash on exactly the widths it disagrees on.

    Every width it asks about, not merely that the right one is present
    somewhere: `index.html` names 768 three times, so a check for the string
    passed with one of them changed — mutation testing said so."""
    asked = [int(px) for px in re.findall(r"matchMedia\(\s*'\(max-width:\s*(\d+)px\)'", INDEX)]
    asked += [int(px) for px in re.findall(r"innerWidth\s*[<>]=?\s*(\d{3,4})", INDEX)]
    assert asked, "the pre-paint script asks about no width at all"
    off = sorted({px for px in asked
                  if px != MOBILE_MAX and px not in COMPONENT_WIDTHS
                  and abs(px - MOBILE_MAX) <= 100})
    assert not off, (
        f"index.html decides mobile at {off} as well as {MOBILE_MAX}; the "
        "pre-paint script runs before any stylesheet, so a disagreement here "
        "is a visible flash at exactly those widths"
    )


def test_no_script_has_its_own_idea_of_where_mobile_ends():
    """B50. `calendar.js` said 700 under a comment defining desktop. Any width
    within 100px of the boundary, compared against `innerWidth`, is making the
    same claim — and if it is not 768 it is making it differently."""
    offenders = []
    for path in sorted((ROOT / "static").rglob("*.js")):
        if "lib/" in str(path):
            continue
        # `galleryEditor.js` tests 820, which is the component width its own
        # nine `@media (max-width: 820px)` blocks use. That is a panel
        # reflowing, not a claim about where mobile ends, and COMPONENT_WIDTHS
        # is what separates the two.
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"innerWidth\s*[<>]=?\s*(\d{3,4})", text):
            px = int(m.group(1))
            if px in COMPONENT_WIDTHS or px == MOBILE_MAX:
                continue
            if abs(px - MOBILE_MAX) <= 100:
                line = text[:m.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}: {m.group(0)}")
    assert not offenders, (
        "these decide mobile at a width nothing else uses: " + repr(offenders)
    )


def test_the_image_editor_stacks_when_the_app_goes_mobile():
    """The 558-line block that unstacks the editor body. Its comment says the
    canvas ends up zero-width without it; it must fire when the shell does."""
    m = re.search(r"@media \(max-width: (\d+)px\) \{\s*\n\s*/", CSS)
    body = CSS[CSS.index(".ge-editor-body") - 4000:CSS.index(".ge-editor-body")]
    opener = re.findall(r"@media \(max-width: (\d+)px\)", body)
    assert opener, "the editor's responsive block moved and this test cannot find it"
    assert int(opener[-1]) == MOBILE_MAX, (
        f"the image editor stacks at {opener[-1]}px and the app goes mobile at "
        f"{MOBILE_MAX}px; between them the editor keeps a three-column body in "
        "a mobile layout"
    )


def test_the_min_width_720_block_is_not_a_dead_zone():
    """The row claimed 701–719 matched nothing. It matches the base rule — this
    asserts the pairing the correction rests on, so the claim cannot quietly
    come back."""
    i = CSS.index("@media (min-width: 720px)")
    before = CSS[max(0, i - 400):i]
    assert ".ge-shortcuts-grid" in before, "the base rule moved away from its override"
    assert "repeat(2, 1fr)" in before, "the base rule no longer sets a column count"
    inside = CSS[i:i + 200]
    assert "repeat(4, 1fr)" in inside
