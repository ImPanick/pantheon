# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P5-12` — the composer's tool strip is one chip, not nine hand-styles.

Re-measured 2026-09-18, scope `static/index.html`'s `.chat-input-left` block:
**seven** `input-icon-btn tool-indicator` buttons and **two** bare-icon toggles
(`#web-toggle-btn`, `#bash-toggle-btn`), exactly as the row says. What the row
does not say is where the hand-styling lived: **every one of the seven label
spans carried its own `style="font-size:11px;margin-left:2px…"` attribute** —
seven copies of one type ramp, two of them with a differing `max-width`, none
of them reachable from a stylesheet and so none of them themeable. That is the
"makes the strip themeable for the first time" clause, measured.

There was already a chip: `.plan-mode-btn` + `.plan-mode-btn-label`, written
for `P6-12`, with its own `height / padding / gap` and its own `11px / 600 /
line-height 1`. `Law 14` says extend that rather than write a tenth thing, so
the component is that geometry lifted onto `.tool-chip` / `.tool-chip-label`
and the nine — plan included — all wear it.

**`P5-15` is why the shape matters.** That row adds a second tool strip a few
pixels above this one and is a `Law 14` dependency on this row rather than a
scheduling one. So the assertions below are about the component being
*reusable* — a class on a button and a class on its label, with no id in the
geometry — not merely about the strip looking tidy today.

**Not consolidated, deliberately, and said out loud so the next agent does not
read it as an oversight:** the `.active` colour. `.tool-indicator.active`
paints `var(--red)` and `.plan-mode-btn.active` paints
`var(--accent, var(--red))`. Moving either onto the other changes the
`--accent` population that `tests/test_accent_fallback_semantics_css.py` pins
at 814 / 553 / 562 / 181, and that file's whole point is that the population
does not move for convenience. `B781`.
"""
import re
from pathlib import Path

from tests.helpers.source_text import blank  # B290

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"

CHIP = "tool-chip"
CHIP_LABEL = "tool-chip-label"


def _strip() -> str:
    """The `.chat-input-left` block, comments blanked.

    Scoped rather than file-wide: `B41` is the standing example of a green
    assertion about the right string two functions away from where it had to
    be, and this page has 260 inline SVGs and several other button strips.
    """
    html = blank(INDEX)
    start = html.index('<div class="chat-input-left">')
    end = html.index('<div class="chat-input-right">', start)
    return html[start:end]


def _buttons():
    """(id, whole tag+body) for every `<button>` directly in the strip."""
    out = []
    for m in re.finditer(r"<button\b[^>]*>.*?</button>", _strip(), re.S):
        block = m.group(0)
        bid = re.search(r'id="([^"]+)"', block)
        out.append((bid.group(1) if bid else "", block))
    return out


def _chips():
    """The nine the row is about, by id — the seven indicators plus the two
    toggles — plus the plan chip that donated the geometry."""
    wanted = {
        "plan-toggle-btn", "web-toggle-btn", "bash-toggle-btn",
        "workspace-indicator-btn", "doc-indicator-btn", "rag-indicator-btn",
        "research-toggle-btn", "group-toggle-btn", "character-indicator-btn",
        "compare-indicator-btn",
    }
    return [(i, b) for i, b in _buttons() if i in wanted]


# ── The population the row counted ──────────────────────────────────────────


def test_the_strip_still_holds_the_nine_the_row_counted():
    """Re-measured, not carried (`Law 6`). If the strip gains or loses a chip
    the row's arithmetic is stale and the next agent should be told so here
    rather than discovering it in a diff."""
    strip = _strip()
    assert strip.count('class="input-icon-btn tool-indicator"') \
        + strip.count('class="input-icon-btn tool-indicator ') == 7, \
        "the seven tool indicators are no longer seven"
    assert len(_chips()) == 10, [i for i, _ in _chips()]


# ── One component ───────────────────────────────────────────────────────────


def test_no_chip_label_carries_a_hand_written_type_ramp():
    """Fails on the tree as it stood: seven inline `font-size:11px` attributes.

    An inline `style` is the one declaration a theme cannot reach, which is why
    the row calls this the change that makes the strip themeable.
    """
    offenders = []
    for cid, block in _chips():
        for style in re.findall(r'style="([^"]*)"', block):
            if "font-size" in style or "max-width" in style:
                offenders.append((cid, style))
    assert offenders == [], (
        "chip labels still carry hand-written type:\n  "
        + "\n  ".join(f"{cid}: {s}" for cid, s in offenders)
    )


def _own_classes(block: str) -> set:
    """The classes on the `<button>` itself, not on anything inside it.

    Tokenised rather than matched as a substring: `\\btool-chip\\b` is happy
    with `class="tool-chip-label"` on the label span two lines down, so the
    obvious regex passes on a button that lost the component entirely. That
    mutation survived the first version of this file.
    """
    open_tag = block[:block.index(">") + 1]
    m = re.search(r'class="([^"]*)"', open_tag)
    return set((m.group(1) if m else "").split())


def test_every_chip_wears_the_component():
    missing = [cid for cid, block in _chips() if CHIP not in _own_classes(block)]
    assert missing == [], f"chips not built from the component: {missing}"


def test_every_chip_label_wears_the_component():
    """A chip with text in it has to get that text from the shared label class,
    or the type ramp forks again the first time somebody adds a chip."""
    bad = []
    for cid, block in _chips():
        for span in re.findall(r"<span\b[^>]*>(?:[^<]*)</span>", block):
            if "tool-indicator-x" in span:
                continue
            text = re.sub(r"<[^>]+>", "", span).strip()
            has_id = 'id="' in span
            if (text or has_id) and CHIP_LABEL not in span:
                bad.append((cid, span[:90]))
    assert bad == [], "labels outside the component:\n  " + "\n  ".join(map(str, bad))


def test_the_two_bare_icon_toggles_are_no_longer_bare():
    """`Law 15`. `.plan-mode-btn`'s own CSS comment already states the rule —
    *"the button now carries a visible label (Law 15: no unlabelled icons)"* —
    and then Web and Shell sat beside it with no label at all. The strings are
    not invented here: the overflow mirror has been labelling both from
    `btn.title` since the menu was written."""
    for cid in ("web-toggle-btn", "bash-toggle-btn"):
        block = dict(_chips())[cid]
        label = re.search(rf'<span[^>]*class="[^"]*{CHIP_LABEL}[^"]*"[^>]*>([^<]+)</span>', block)
        assert label and label.group(1).strip(), f"{cid} still has no visible label"


# ── The geometry is declared once ───────────────────────────────────────────


def _rule(selector: str) -> str:
    css = blank(STYLE)
    m = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_the_chip_geometry_lives_in_one_rule():
    body = _rule(f".{CHIP} ")
    for prop in ("height", "padding", "gap"):
        assert re.search(rf"\b{prop}\s*:", body), f"{prop} missing from .{CHIP}"


def test_the_plan_chip_no_longer_declares_its_own_geometry():
    """The `Law 14` half: extending the first implementation means the first
    implementation stops carrying a second copy of what it donated."""
    css = blank(STYLE)
    m = re.search(r"\.plan-mode-btn\s*\{([^{}]*)\}", css)
    if m:
        for prop in ("height", "padding", "gap"):
            assert not re.search(rf"\b{prop}\s*:", m.group(1)), (
                f".plan-mode-btn still declares its own {prop} — two chip "
                "geometries is the fork this row closes"
            )


def test_the_label_type_lives_in_one_rule():
    body = _rule(f".{CHIP_LABEL} ")
    assert re.search(r"font-size\s*:\s*11px", body), body
    assert re.search(r"font-weight\s*:\s*600", body), body


def test_mobile_hides_every_chip_label_not_just_the_indicators():
    """The old rule was `.tool-indicator > span`, which reaches seven of the
    nine. Web and Shell are not indicators, so labelling them without moving
    this rule would leave two labels alone on a phone."""
    css = blank(STYLE)
    assert re.search(rf"\.{CHIP_LABEL}\s*\{{[^{{}}]*display:\s*none", css) or \
        re.search(rf"\.{CHIP}\s*>\s*\.{CHIP_LABEL}\s*\{{[^{{}}]*display:\s*none", css), \
        "no mobile rule hides the chip labels"
