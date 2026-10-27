# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P5-12` — the composer's tool strip is one chip, not nine hand-styles.

Re-measured 2026-09-18, scope `static/index.html`'s `.chat-input-left` block:
**seven** `input-icon-btn tool-indicator` buttons and **two** bare-icon toggles
(`#web-toggle-btn`, `#bash-toggle-btn`), exactly as the row says.

**Re-measured again 2026-10-09** (`fx8-census`, after `D-2026-10-09-01`):
**eight** indicators and the same two toggles, so the component's population is
**eleven** rather than ten. The arrival is `#approval-mode-btn` — §2's per-chat
approval mode, put beside Plan / Web / Shell because it is the same kind of
switch — and it wears `.tool-chip` + `.tool-chip-label` already. That is the
only thing that moved, and the reason it is written down here rather than
silently accepted: `_chips()` below is a list of ids, so a new chip that is not
added to it escapes every "wears the component" assertion in this file while
the count assertion is the only thing that notices. The count noticing is what
this row's `Law 6` clause is for. What the row
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

**Not consolidated by this row, deliberately:** the `.active` colour.
`.tool-indicator.active` painted `var(--red)` and `.plan-mode-btn.active`
`var(--accent, var(--red))`, and moving either changed the `--accent`
population `tests/test_accent_fallback_semantics_css.py` pins. `B781` then did
it on purpose, in the direction that shrinks that population (814 / 553 / 562
/ 181 → 812 / 551 / 560 / 180): the plan chip's on-state is one selector in
`.tool-indicator.active`'s rule. Web and Shell were never in either rule — they
took `.input-icon-btn.active`'s neutral tint — and `B1552` joined them too:
the one rule now names `.tool-chip.active`, the component's own on-state, and
its label is `--chip-on-fg`, the red cleared to 4.5:1 on its tint per palette
(measured in Chromium in
`tests/test_every_chip_in_the_strip_has_one_on_state_that_reads.py`).
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
        # `D-2026-10-09-01` §2, measured into the strip 2026-10-09. Listed so
        # the four assertions below cover it; without the entry it is a chip
        # nothing in this file checks.
        "approval-mode-btn",
        # `P24-26`, 2026-10-24: the summoned agent's chip.
        "summon-indicator-btn",
    }
    return [(i, b) for i, b in _buttons() if i in wanted]


# ── The population the row counted ──────────────────────────────────────────


def test_the_strip_still_holds_the_nine_the_row_counted():
    """Re-measured, not carried (`Law 6`). If the strip gains or loses a chip
    the row's arithmetic is stale and the next agent should be told so here
    rather than discovering it in a diff.

    It did, on 2026-10-09: seven indicators became **eight** and the nine the
    row counted became **eleven** counting the plan chip that donated the
    geometry, because `D-2026-10-09-01` §2 put `#approval-mode-btn` in the
    strip. Discovered here rather than in a diff, which is what this case is
    for.

    And on 2026-10-24: **nine** and **twelve** — `P24-26` put the summoned
    agent's chip (`#summon-indicator-btn`) beside the Workspace pill."""
    strip = _strip()
    assert strip.count('class="input-icon-btn tool-indicator"') \
        + strip.count('class="input-icon-btn tool-indicator ') == 9, \
        "the nine tool indicators are no longer nine"
    assert len(_chips()) == 12, [i for i, _ in _chips()]


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


def _on_state_rules(selector: str) -> list:
    """Every rule body whose selector list names `selector` exactly."""
    css = blank(STYLE)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in [p.strip() for p in m.group(1).split(",")]:
            out.append((m.group(1), m.group(2)))
    return out


def test_the_plan_chip_and_the_indicators_share_one_on_state():
    """`B781`. One declaration block paints both, so they cannot drift apart
    again, and nothing else gives the plan chip an `.active` colour of its own."""
    shared = [(sel, body) for sel, body in _on_state_rules(".tool-indicator.active")
              if ".plan-mode-btn.active" in [p.strip() for p in sel.split(",")]]
    assert len(shared) == 1, "the plan chip and the indicators are not in one on-state rule"
    body = shared[0][1]
    # `B1552`: the label is the red cleared to AA on the tint, red before boot.
    assert re.search(r"(?:^|;)\s*color\s*:\s*var\(--chip-on-fg,\s*var\(--red\)\)", body), body
    assert "--accent" not in body, "the shared on-state reaches for the accent again"
    own = [b for _, b in _on_state_rules(".plan-mode-btn.active")
           if re.search(r"(?:^|;)\s*(?:color|background)\s*:", b)]
    assert len(own) == 1, f"the plan chip has an on-state of its own again: {own}"


def test_web_and_shell_take_the_strips_one_on_state():
    """`B1552`. Web and Shell were `.input-icon-btn` toggles whose `.active` was
    the neutral `--fg` tint, a second on-state in one strip (and 3.85:1 on
    `retrowave`). The shared rule names the component's own on-state,
    `.tool-chip.active`, and both wear the component — so neither can drift
    into a third. The neutral rule stays for the `.input-icon-btn`s that are not
    chips."""
    ids = {i for i, b in _chips()}
    assert {"web-toggle-btn", "bash-toggle-btn"} <= ids
    for i, block in _chips():
        if i in ("web-toggle-btn", "bash-toggle-btn"):
            assert CHIP in _own_classes(block), i
    shared = [(sel, body) for sel, body in _on_state_rules(".tool-indicator.active")
              if f".{CHIP}.active" in [p.strip() for p in sel.split(",")]]
    assert len(shared) == 1, "the component's on-state is not the strip's one rule"
    neutral = _on_state_rules(".input-icon-btn.active")
    assert neutral and re.search(r"(?:^|;)\s*color\s*:\s*var\(--fg\)", neutral[0][1]), neutral
