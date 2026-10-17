# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-13` — the zone highlighter announces itself, and says when it has nothing.

Hovering a colour row in the theme editor outlines, on the live page behind the
modal, the element that colour controls. The row that filed this calls it *"the
best explainability feature in the app"* and its whole complaint is that
**nothing said so**: no label, no legend, no hint.

Three things were wrong, and only the first is the one the row names.

  * **Nobody was told.** A feature discovered by accident is a feature most
    people never discover.
  * **The map was a 12-key subset of a 14-key register.** `ADV_KEYS` carries
    fourteen advanced colours and `_THEME_ZONE_MAP` had twelve, so hovering
    `brandMixTo` or `hamburgerColor` did nothing at all — indistinguishable
    from the feature being broken. `B21`'s closure recorded the subset as
    documented; it is no longer a subset.
  * **Zero outlined is a real answer and was silent.** `--brand-mix-to` is read
    at exactly one rule — the welcome wordmark's gradient — so hovering that
    row with a conversation open correctly outlines nothing. A feature that is
    sometimes quiet for a good reason, and quiet in the same way when it is
    broken, is one a person stops trusting.

So the highlighter answers **how many** elements it drew, and one live line
under the grid says which of the three happened. It is `aria-live="polite"`,
because a screen reader user gets the sentence where a sighted user gets the
outline.

Driven under node against the real `theme.js` and the real `index.html`
markup: the map, the wiring and the counting are read by running them, not by
grepping for them (`Law 20`).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.source_text import blank  # B290

ROOT = Path(__file__).resolve().parent.parent
THEME = ROOT / "static" / "js" / "theme.js"
INDEX = ROOT / "static" / "index.html"
CSS = ROOT / "static" / "style.css"

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")


# ── the register and the map agree ─────────────────────────────────────────


def test_every_advanced_colour_has_a_zone():
    """`B21`'s documented 12-of-14 subset is closed. Derived from both sides,
    so a fifteenth advanced colour fails here rather than hovering to
    nothing."""
    # Comment-blanked (`B290`). The first draft read the raw source and a
    # mutation that commented one zone out survived it: `// 'adv-x': '.y',`
    # matches the regex exactly as the live line does, so the map looked
    # complete while the feature was silent on that row.
    src = blank(THEME)
    adv = re.findall(r"\{ key: '(\w+)',", src)
    zones = {m[4:] for m in re.findall(r"'(adv-\w+)':\s*'", src)}
    assert len(adv) >= 14, f"only {len(adv)} ADV_KEYS parsed; the shape moved"
    missing = sorted(set(adv) - zones)
    assert not missing, f"advanced colours with no zone: {missing}"


def test_every_zone_selector_is_valid_and_names_something_in_the_markup():
    """A zone pointing at a selector the product does not draw is a row that
    can only ever say *not on screen*. Checked against the shipped markup,
    which is the only place the answer lives."""
    src = blank(THEME)
    block = src[src.index("const _THEME_ZONE_MAP = {"):]
    block = block[:block.index("\n};")]
    pairs = re.findall(r"'([\w-]+)':\s*'([^']+)'", block)
    assert len(pairs) >= 14, f"only {len(pairs)} zones parsed"
    html = INDEX.read_text(encoding="utf-8")
    for picker, selector in pairs:
        for one in selector.split(","):
            one = one.strip()
            # The last simple token is what has to exist: `#id`, `.class` or a
            # tag. `body` is always there.
            token = re.split(r"[\s>+~]", one)[-1]
            ident = re.match(r"[#.]?([\w-]+)", token)
            assert ident, f"{picker}: cannot read a name out of {one!r}"
            name = ident.group(1)
            if token.startswith("#"):
                assert f'id="{name}"' in html, f"{picker} points at #{name}, not in index.html"
            elif token.startswith("."):
                assert re.search(rf'class="[^"]*\b{re.escape(name)}\b', html), (
                    f"{picker} points at .{name}, which index.html never draws")
            else:
                assert name in ("body", "pre", "code", "input"), (
                    f"{picker} points at the bare tag {name!r}")


# ── the hint exists, is live, and is reserved space ────────────────────────


def test_the_markup_carries_a_live_hint_with_a_default():
    html = INDEX.read_text(encoding="utf-8")
    hint = re.search(r'<p class="theme-zone-hint" id="theme-zone-hint"[^>]*>', html)
    assert hint, "the Customize tab has no hint line"
    assert 'aria-live="polite"' in hint.group(0), (
        "a screen reader gets the sentence where a sighted user gets the outline")
    assert 'data-default=' in hint.group(0), (
        "the hint needs a default to return to when the hover ends")
    assert "Hover a colour" in html


def test_the_hint_reserves_its_own_height():
    """The text changes on every hover. Without a reserved line the grid above
    it shifts by one line-height each time a message appears, which turns a
    help line into a jitter."""
    css = CSS.read_text(encoding="utf-8")
    rule = re.search(r"\.theme-zone-hint \{([^}]*)\}", css)
    assert rule, "the hint has no rule"
    assert re.search(r"min-height:\s*[\d.]+", rule.group(1)), (
        "no min-height, so the grid moves whenever the message changes")
    assert "--accent" not in rule.group(1), (
        "`P1-01` keeps the accent for the chrome; this is help text")


# ── driven: the three answers ──────────────────────────────────────────────


def _run(tmp_path, *, zone_targets: dict, hover: str) -> dict:
    """Run the real `initThemeZoneHighlight` over a fake Customize tab.

    `zone_targets` maps a selector to how many elements `querySelectorAll`
    should answer with, and how big they are — which is the only thing the
    highlighter decides on, so the sandbox models exactly that and nothing
    else.
    """
    from test_accent_token_js import _THEME_SHIM, _THEME_STUBS
    from test_tool_effect_surfaces_js import _make_sandbox

    sandbox = _make_sandbox(tmp_path, THEME, _THEME_SHIM, _THEME_STUBS)
    entry = sandbox / "case.mjs"
    entry.write_text(
        "import { document } from './shim.js';\n"
        f"const TARGETS = {json.dumps(zone_targets)};\n"
        "const hint = { textContent: '', dataset: { default: 'DEFAULT' } };\n"
        "const rows = [];\n"
        "function mkRow(id, label, title) {\n"
        "  const input = { id, _h: {},\n"
        "    addEventListener(k, f) { this._h[k] = f; } };\n"
        "  const labelEl = { textContent: label,\n"
        "    getAttribute: (a) => (a === 'title' ? (title || null) : null) };\n"
        "  const row = { _h: {},\n"
        "    addEventListener(k, f) { this._h[k] = f; },\n"
        "    querySelector: (s) => (s === 'label' ? labelEl : input) };\n"
        "  rows.push(row);\n"
        "  return row;\n"
        "}\n"
        "const made = [];\n"
        "document.getElementById = (id) => {\n"
        "  if (id === 'theme-tab-customize') return {\n"
        "    dataset: {},\n"
        "    querySelectorAll: () => rows,\n"
        "  };\n"
        "  if (id === 'theme-zone-hint') return hint;\n"
        "  return null;\n"
        "};\n"
        "document.querySelectorAll = (sel) => {\n"
        "  const n = TARGETS[sel] || 0;\n"
        "  return Array.from({ length: n }, () => ({\n"
        "    closest: () => null,\n"
        "    getBoundingClientRect: () => ({ top: 10, left: 10, width: 50, height: 20 }),\n"
        "  }));\n"
        "};\n"
        "document.createElement = (tag) => { const el = { style: {}, tagName: tag };\n"
        "  made.push(el); return el; };\n"
        "document.body = { appendChild: () => {}, classList: { add() {} } };\n"
        "globalThis.MutationObserver = class { observe() {} };\n"
        "const tm = await import('./theme.js');\n"
        "mkRow('clr-bg', 'Background');\n"
        "mkRow('adv-brandMixTo', 'Wordmark fade');\n"
        "mkRow('adv-hamburgerColor', '', 'Hamburger menu');\n"
        "mkRow('theme-font-size', 'Not a colour zone');\n"
        "tm.initThemeZoneHighlight();\n"
        f"const row = rows.find(r => r.querySelector('x').id === {json.dumps(hover)});\n"
        "row._h.mouseenter();\n"
        "const after = hint.textContent;\n"
        "row._h.mouseleave();\n"
        "console.log(JSON.stringify({ hover: after, cleared: hint.textContent,\n"
        "                             drawn: made.length }));\n"
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_it_names_the_element_it_outlined(tmp_path):
    out = _run(tmp_path, zone_targets={"body": 1}, hover="clr-bg")
    assert out["drawn"] == 1
    assert out["hover"] == "Outlined: Background."
    assert out["cleared"] == "DEFAULT", "the hover's end returns the default"


def test_it_says_when_the_element_is_not_on_screen(tmp_path):
    """`--brand-mix-to`'s only consumer is the welcome wordmark, so this is the
    ordinary case on an open conversation, not an edge."""
    out = _run(tmp_path, zone_targets={}, hover="adv-brandMixTo")
    assert out["drawn"] == 0
    assert "not on screen right now" in out["hover"]
    assert "Wordmark fade" in out["hover"]


def test_it_says_when_a_colour_has_no_zone_at_all(tmp_path):
    """A third answer, and the one that used to be silence."""
    out = _run(tmp_path, zone_targets={"body": 1}, hover="theme-font-size")
    assert out["drawn"] == 0
    assert "has no preview" in out["hover"]


def test_a_row_labelled_only_by_an_icon_still_names_itself(tmp_path):
    """`adv-hamburgerColor`'s label is an inline SVG and the words live in
    `title=`. Reading `textContent` alone would have called it *this colour*."""
    out = _run(tmp_path, zone_targets={".hamburger-btn": 1},
               hover="adv-hamburgerColor")
    assert out["drawn"] == 1
    assert out["hover"] == "Outlined: Hamburger menu."
