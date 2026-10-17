# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P1-10`, `P1-11`. The z ladder: named, measured, and ratcheted.

`P1-10` asked to normalise z-index to seven named tiers and measured **259
declarations, 64 distinct values** in `static/style.css`, range −1 to 1,000,000.
Re-measured 2026-10-17 and three of those four numbers had moved — **349**
literals, **74** distinct, range **−1 to 2,147,483,646** — and the reason the
first one moved is the row's own scope line, *"`static/style.css` only"*: 69 of
the 349 are in 28 other files.

The part the row could not have known is the useful one. **Sixty-four further sites
are already derived**: `topPortalZ()`, `nextToolWindowZ()` and
`topToolWindowZ()` read the live stack, so the top of the ladder is a runtime
value and no table can hold it. That is why a tier table is a *vocabulary*
here and not a remap.

What this file holds:

  * every literal falls inside one of the seven tiers, or `below`, which is not
    a tier but the absence of one;
  * the tier ranges are a **partition** — no overlap, in ascending order, so
    *which tier is this* has exactly one answer;
  * the checker catches a new magic number, and catches a literal outside every
    tier, and says which;
  * the population may shrink but not grow;
  * `P1-11`: the toast is above the tour hint, and the `9999` that put it
    underneath is gone from the stylesheet rather than merely out-ranked.

**`P1-11`'s premise is stale and that is how it closed.** The row says *"toasts
sit at 9999, below every image-editor popover at 10001–10006"*. `B1056` fixed
that on 2026-10-01, driven in Chromium, by adding `#toast.toast { z-index:
2147483000 }` — an id-qualified rule whose whole job was to out-rank the `9999`
still sitting in `.toast`. So the occlusion was gone and the dead declaration
was not. `P1-11` moves the value onto `.toast` and retires the override: the
computed value is identical, because there is exactly one toast element in the
product, and `tests/test_a_toast_is_read_over_the_tour_hint.py` — which drives
the real stylesheet in headless Chromium — is the proof that it is.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STYLE = ROOT / "static" / "style.css"


def _checker():
    spec = importlib.util.spec_from_file_location(
        "check_zindex", ROOT / ".pantheon" / "check-zindex.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CZ = _checker()


@pytest.fixture(scope="module")
def sites():
    return CZ.population()


@pytest.fixture(scope="module")
def literals(sites):
    return [s for s in sites if s["kind"] == "literal"]


# ── the ladder is a partition ──────────────────────────────────────────────


def test_the_tiers_are_a_partition_in_ascending_order():
    """*Which tier is this* has to have exactly one answer.

    Overlapping ranges would make `tier_of()` depend on the order of the table,
    and a gap would let a literal sit in no tier while the checker still passed
    — the two failures a classification can have.
    """
    bounds = [(low, high) for _, low, high, _ in CZ.TIERS]
    assert len(bounds) == 8, "seven tiers plus `below`"
    for (low, high) in bounds:
        assert low <= high, f"tier range {low}..{high} is inverted"
    for (a_low, a_high), (b_low, b_high) in zip(bounds, bounds[1:]):
        assert a_high < b_low, f"tiers {a_low}..{a_high} and {b_low}..{b_high} overlap"


def test_every_tier_is_named_and_says_what_it_is_for():
    for name, _, _, what in CZ.TIERS:
        assert name and name.islower(), name
        assert len(what) > 20, f"{name}'s purpose line is too thin to pick a tier from"


def test_the_baseline_names_only_values_inside_their_own_tier():
    """A recorded value in the wrong tier would silently widen that tier."""
    for name, low, high, _ in CZ.TIERS:
        for value in CZ.BASELINE.get(name, ()):
            assert low <= value <= high, (
                f"BASELINE[{name!r}] holds {value}, which is outside {low}..{high}")


# ── the population ─────────────────────────────────────────────────────────


def test_the_scan_finds_the_population_it_claims(sites, literals):
    """Non-vacuity. A scan that finds nothing passes every test below it."""
    derived = [s for s in sites if s["kind"] == "derived"]
    assert len(literals) >= 340, f"only {len(literals)} literals found"
    assert len(derived) >= 60, f"only {len(derived)} derived sites found"
    assert len({s["file"] for s in literals}) >= 20


def test_no_literal_sits_outside_every_tier(literals):
    orphans = sorted({s["value"] for s in literals if CZ.tier_of(s["value"]) is None})
    assert not orphans, f"values in no tier: {orphans}"


def test_the_literal_population_has_not_grown(literals):
    assert len(literals) <= CZ.BASELINE_LITERALS, (
        f"{len(literals)} literals against a baseline of {CZ.BASELINE_LITERALS}; "
        "the population may shrink, not grow")


def test_the_checker_passes_on_this_tree():
    result = subprocess.run(
        [sys.executable, str(ROOT / ".pantheon" / "check-zindex.py")],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "z-index OK" in result.stdout


def test_the_vendored_bundles_are_not_ours_to_tier(sites):
    """`swagger-ui.css` alone carries 19 and we do not maintain it."""
    assert not [s for s in sites if s["file"].startswith("static/lib/")]


def test_a_comment_cannot_hold_a_z_index_and_a_string_cannot_open_one(tmp_path):
    """Offsets have to survive comment stripping, and a string must not open a
    comment — the two halves of `B290`, which this checker shipped wrong once.

    The hand-written version read `'image/*,video/*'` as the start of a comment
    and ate everything to the next `*/`, hiding six real sites in JS modules.
    The second assertion here is that exact string.
    """
    css = tmp_path / "x.css"
    blanked = CZ._strip_comments("a/* z-index: 4242; */b", css)
    assert len(blanked) == len("a/* z-index: 4242; */b")
    assert "4242" not in blanked
    assert blanked.startswith("a") and blanked.endswith("b")

    js = tmp_path / "x.js"
    live = "input.accept = 'image/*,video/*';\nel.style.zIndex = '4242';\n/* gone */\n"
    kept = CZ._strip_comments(live, js)
    assert "4242" in kept, (
        "a string literal opened a comment and ate the site after it — B290")
    assert "gone" not in kept, "a real comment survived"
    kept_url = CZ._strip_comments("const u = 'https://x/y';\n", js)
    assert "https://x/y" in kept_url, "a protocol's // is not a comment"


# ── what the checker catches ───────────────────────────────────────────────


def _run_on(tmp_path, mutate):
    """Drive the checker over a copy of `static/` with one file mutated.

    The checker reads `ROOT / "static"`, so the copy is what it is pointed at —
    this drives the real scan rather than re-implementing it (`Law 20`).
    """
    import shutil
    stage = tmp_path / "tree"
    (stage / "static").mkdir(parents=True)
    shutil.copytree(ROOT / "static", stage / "static", dirs_exist_ok=True)
    mutate(stage / "static")
    original = CZ.ROOT
    try:
        CZ.ROOT = stage
        population = CZ.population()
    finally:
        CZ.ROOT = original
    return population


def test_a_new_magic_number_is_caught(tmp_path):
    """The failure that produced 2,147,483,000: reach for a bigger number."""
    def mutate(static):
        css = static / "style.css"
        css.write_text(css.read_text(encoding="utf-8")
                       + "\n.probe-new-magic { position: fixed; z-index: 777777; }\n",
                       encoding="utf-8")
    values = {s["value"] for s in _run_on(tmp_path, mutate) if s["kind"] == "literal"}
    assert 777777 in values, "the scan missed the mutation"
    assert CZ.tier_of(777777) == "top"
    assert 777777 not in CZ.BASELINE["top"], (
        "777777 is recorded as a known value, so this mutation proves nothing")


def test_a_literal_in_no_tier_is_caught(tmp_path):
    """The gap between `below` and `base` is the one a negative can fall into."""
    def mutate(static):
        css = static / "style.css"
        css.write_text(css.read_text(encoding="utf-8")
                       + "\n.probe-orphan { position: fixed; z-index: -9; }\n",
                       encoding="utf-8")
    values = {s["value"] for s in _run_on(tmp_path, mutate) if s["kind"] == "literal"}
    assert -9 in values
    assert CZ.tier_of(-9) is None, "-9 now has a tier; the ranges moved"


def test_a_literal_hidden_in_a_template_string_is_still_found(tmp_path):
    """`emailLibrary.js` and `slashCommands.js` write z inline in markup, which
    is a different spelling and the same defect. The scan reads the context,
    not the syntax, so there is one rule rather than seven."""
    def mutate(static):
        js = static / "js" / "notes.js"
        js.write_text(js.read_text(encoding="utf-8")
                      + "\nexport const _probe = `<div style=\"z-index:424242\"></div>`;\n",
                      encoding="utf-8")
    hits = [s for s in _run_on(tmp_path, mutate)
            if s["kind"] == "literal" and s["value"] == 424242]
    assert hits, "a z-index inside a template literal was not seen"


def test_a_derived_site_is_not_read_as_a_literal(tmp_path):
    """`String(topPortalZ() + 1)` contains a `1`. Reading it as a literal would
    report the correct sites as defects and make the checker worthless."""
    def mutate(static):
        js = static / "js" / "notes.js"
        js.write_text(js.read_text(encoding="utf-8")
                      + "\nexport function _p(el){ el.style.zIndex = String(topPortalZ() + 1); }\n",
                      encoding="utf-8")
    added = [s for s in _run_on(tmp_path, mutate)
             if s["file"].endswith("notes.js") and "topPortalZ() + 1" in s["text"]]
    assert added, "the added site was not seen at all"
    assert all(s["kind"] == "derived" for s in added), added


# ── P1-11 ──────────────────────────────────────────────────────────────────


def test_the_toast_is_not_left_on_a_literal_the_window_counter_can_reach():
    """`P1-11`, `B1056`. Read from the stylesheet, against the `top` tier's own
    floor, rather than against the number — so raising the tier moves this
    with it and a toast dropped back to 9999 fails."""
    css = CZ._strip_comments(STYLE.read_text(encoding="utf-8"), STYLE)
    rule = re.search(r"\n    \.toast \{(.*?)\n    \}", css, re.S)
    assert rule, "the `.toast` rule has moved; re-derive this test"
    value = re.search(r"z-index:\s*(\d+)", rule.group(1))
    assert value, "`.toast` sets no z-index, so the stylesheet fallback paints it"
    low = next(lo for name, lo, _, _ in CZ.TIERS if name == "top")
    assert int(value.group(1)) >= low, (
        f"the toast sits at {value.group(1)}, below the `top` tier's {low} — "
        "`B1056` measured the tour hint covering it at 9999")


def test_the_id_qualified_override_is_gone_not_merely_out_ranked():
    """What `P1-11` actually was. `B1056` beat the `9999` with an id; the `9999`
    stayed. Two rules, one dead, and the dead one is the one a new `.toast`
    would have inherited."""
    # Comment-stripped, because the rule this test forbids is *named* in the
    # comment that replaced it — the first draft of this test read its own
    # explanation as the defect.
    css = CZ._strip_comments(STYLE.read_text(encoding="utf-8"), STYLE)
    assert "#toast.toast" not in css, (
        "the id-qualified toast rule is back — put the value on `.toast` instead, "
        "or the base rule is dead again")
    toast_rules = [
        body for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        if "toast" in selector.split("\n")[-1].lower() and "z-index" in body
    ]
    assert len(toast_rules) == 1, (
        f"{len(toast_rules)} toast rules set a z-index; one of them is dead")
