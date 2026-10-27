# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-01` / `B643` — the confidence is on screen, and the two sides agree on it.

`P13-01` landed its server half on 2026-09-18 and said so plainly: *"the pill
is NOT done and is the remaining half … the number has nowhere to be read
yet"*, because `static/**` belonged to another agent that wave. `B643` is the
row that names the shape — *"The Brain records confidence, provenance and typed
edges, and shows none of them"* — and calls it `Law 13`'s unwired half and
`Law 15`'s acceptance criterion: **a confidence a person cannot see is a
confidence they cannot correct.**

So it is shown in two places, for two different reasons. The chat pill's
popover, because that is where you ask *why did it say that*; and the Brain
list, because that is where you can fix it.

**`None` renders nothing, and that is the whole design.** A memory written
before the field existed reads `None`. So does one a person typed in — they are
not a 1.0, they are a producer nobody asked, and writing one would make
hand-entered memories outrank extracted ones on a confidence sort for no
defensible reason. A pill reading `80%` over a record nobody assessed is the
`PandAtlas` failure this phase's preamble cites. A recorded **zero** does
render: somebody looked and was not sure, which is a fact about the memory
rather than an absence of one.

**Two implementations, one table.** `normalise_confidence` is in
`src/memory.py` and `normaliseConfidence` is in `static/js/memoryFacts.js`,
because one is Python and one is a browser — the arrangement
`MEMORY_ENGINE_LABELS` already uses a few lines from the pill, and the one
`--on-accent` and `--border-control` use. Driving both over one table found
**four** divergences that reading either would not have:

  * `""` — `Number('')` is **0** in JavaScript and `float('')` raises, so an
    empty confidence rendered `0%`: *somebody looked and was sure it was
    wrong*, which is the opposite of *nobody looked*. The browser was wrong.
  * `inf` and `-inf` — `json.loads("1e999")` is `inf`, straight out of a
    model, and Python's clamp turned it into **1.0, the most confident memory
    on the page**. The NaN guard one line above rejects an unusable number for
    being unusable; infinity went past it into the clamp written for `1.5`.
    **The server was wrong**, and that is a defect this row found rather than
    introduced.
  * `0.0625` — Python's `round` takes a tie to even and `toFixed` takes it away
    from zero, so the two stored `0.062` and `0.063`. That is `B1404`'s defect
    for the second time in one day, in a second pair of implementations.

All four are fixed and the table is below, so a fifth cannot arrive quietly.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "static" / "js" / "memoryFacts.js"
MEMJS = ROOT / "static" / "js" / "memory.js"
RENDERER = ROOT / "static" / "js" / "chatRenderer.js"
STYLE = ROOT / "static" / "style.css"

sys.path.insert(0, str(ROOT))
from src.memory import normalise_confidence  # noqa: E402
from tests.helpers.source_text import blank  # noqa: E402  (`B290`)

#: Every input worth disagreeing about. The dyadic values in the middle are the
#: only ones that can land on an exact three-decimal tie, which is where the
#: two rounding rules part company.
TABLE = [
    None, True, False, 0, 0.0, 1, 1.0,
    0.6, 0.66, 0.666, 0.6665, 0.665, 0.5,
    0.125, 0.0625, 0.1875, 0.3125, 0.4375, 0.5625, 0.6875, 0.8125, 0.9375,
    1.5, -0.3, 2, "0.85", "0", "1", " 0.5 ", "", "   ", "abc",
    float("nan"), float("inf"), float("-inf"),
    0.9995, 0.005, 0.015, 0.025, 0.045, 0.1234567, 0.999, 0.001,
]

_SENTINELS = {"__NAN__": float("nan"), "__INF__": float("inf"), "__NINF__": float("-inf")}


def _wire(value):
    """JSON cannot carry NaN or infinity, so they travel as names."""
    for name, special in _SENTINELS.items():
        if isinstance(value, float) and (
                (special != special and value != value) or (special == special and value == special)):
            return name
    return value


def _js(values: list) -> list:
    """`[normaliseConfidence(v), confidencePercent(v)]` per input, from the module."""
    # The payload is substituted into the source, not passed as argv: with
    # `--input-type=module` reading stdin, a trailing positional is taken as a
    # file to run and node fails resolving it. The sibling harness in
    # `test_mentions_are_not_uses.py` does the same for the same reason.
    script = """
    import { normaliseConfidence, confidencePercent } from '%s';
    const t = %s.map((v) =>
      v === '__NAN__' ? NaN : v === '__INF__' ? Infinity : v === '__NINF__' ? -Infinity : v);
    console.log(JSON.stringify(t.map((v) => [normaliseConfidence(v), confidencePercent(v)])));
    """ % (FACTS.as_posix(), json.dumps([_wire(v) for v in values]))
    run = subprocess.run(["node", "--input-type=module"],
                         input=script, capture_output=True, text=True,
                         cwd=str(ROOT), timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def _py_percent(value):
    confidence = normalise_confidence(value)
    return None if confidence is None else math.floor(confidence * 100 + 0.5)


# ── The two implementations ─────────────────────────────────────────────────

def test_the_browser_and_the_server_agree_on_every_input():
    """One table, both sides, no exceptions. This is the case that found all
    four divergences; it is written as one assertion over the whole table so a
    new disagreement names itself rather than hiding behind a passing sibling."""
    disagree = []
    for value, (js_norm, js_pct) in zip(TABLE, _js(TABLE)):
        py_norm, py_pct = normalise_confidence(value), _py_percent(value)
        if py_norm != js_norm or py_pct != js_pct:
            disagree.append(f"{value!r}: python {py_norm} ({py_pct}%) vs browser "
                            f"{js_norm} ({js_pct}%)")
    assert not disagree, "\n".join(disagree)


def test_not_recorded_stays_not_recorded():
    """The design, as a list. Each of these has to read as *nobody assessed
    this*, and each one of them has been a bug in one implementation or the
    other."""
    for value in (None, "", "   ", "abc", True, False,
                  float("nan"), float("inf"), float("-inf")):
        assert normalise_confidence(value) is None, f"python turned {value!r} into a number"
    for value, (js_norm, js_pct) in zip(
            [None, "", "   ", "abc", True, False, float("nan"),
             float("inf"), float("-inf")],
            _js([None, "", "   ", "abc", True, False, float("nan"),
                 float("inf"), float("-inf")])):
        assert js_norm is None and js_pct is None, (
            f"the browser turned {value!r} into {js_norm} ({js_pct}%)")


def test_infinity_is_not_maximum_confidence():
    """The server defect this row found. `json.loads("1e999")` is `inf` — a
    model emitting an absurd number — and the clamp written for `1.5` turned it
    into 1.0, the most confident memory on the page."""
    assert json.loads("1e999") == float("inf"), "the premise moved"
    assert normalise_confidence(json.loads("1e999")) is None
    assert normalise_confidence(json.loads("-1e999")) is None
    # And the clamp it slipped past still does its own job.
    assert normalise_confidence(1.5) == 1.0
    assert normalise_confidence(-0.3) == 0.0


def test_a_recorded_zero_is_not_an_absence():
    """`0` is falsy in both languages, which is how a recorded zero disappears.
    Somebody looked and was not sure: that renders.

    All the way to the pill, not just through the two helpers: the first draft
    stopped at `confidencePercent` and a mutation swapping `=== null` for a
    truthiness check walked past it, because `0` survives the helpers and then
    vanishes at the last gate."""
    assert normalise_confidence(0) == 0.0
    (js_norm, js_pct), = _js([0])
    assert js_norm == 0 and js_pct == 0
    pill = _pill({"confidence": 0})
    assert pill is not None, "a recorded zero produced no pill"
    assert pill["text"] == "0%"


# ── What reaches a reader ───────────────────────────────────────────────────

def _pill(memory):
    script = """
    import { memoryConfidencePill } from '%s';
    console.log(JSON.stringify(memoryConfidencePill(%s) ?? null));
    """ % (FACTS.as_posix(), json.dumps(memory))
    run = subprocess.run(["node", "--input-type=module"],
                         input=script, capture_output=True, text=True,
                         cwd=str(ROOT), timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("confidence,text", [
    (0.87, "87%"), (0.9, "90%"), (1.0, "100%"), (0, "0%"), (0.005, "1%"), (0.001, "0%"),
])
def test_the_pill_reads_as_a_percent(confidence, text):
    pill = _pill({"confidence": confidence})
    assert pill and pill["text"] == text


@pytest.mark.parametrize("memory", [
    {}, {"confidence": None}, {"confidence": ""}, {"confidence": True},
    {"uses": 4, "mention_sessions": 2},
])
def test_a_memory_nobody_assessed_gets_no_pill_at_all(memory):
    """`null`, not an empty pill: *nobody assessed this* and *assessed at 0%*
    are different claims and an empty box says neither."""
    assert _pill(memory) is None


def test_the_title_says_which_number_it_is():
    """`PandAtlas` merges confidence with corroboration and it reads
    `CONFIDENCE 66%` beside `1 mentions` — two-thirds certainty from a single
    unconfirmed statement, which looks like evidence and is not. The title has
    to distinguish them or the pill invites the same reading."""
    pill = _pill({"confidence": 0.66})
    assert pill, "no pill to read"
    title = pill["title"].lower()
    assert "extractor" in title or "when it wrote this down" in title
    assert "separately" in title or "does not change" in title, (
        "the title does not distinguish a self-report from corroboration")


# ── Both surfaces are wired ────────────────────────────────────────────────

def test_the_chat_pill_renders_the_confidence_it_is_sent():
    """`B61`'s lesson, which this row is a second instance of: a helper can be
    perfect and the pill still show nothing. So the wire is asserted, not just
    the helper."""
    js = blank(RENDERER)
    assert re.search(r"import \{[^}]*memoryConfidencePill[^}]*\} from '\./memoryFacts\.js'", js), (
        "the renderer has its own copy instead of the shared one")
    assert "memory-used-confidence" in js, "nothing carries the pill into the row"

    # The LINK, not the presence of the names. A mutant that computed the pill
    # and then assigned `null` over it left every identifier in this file
    # untouched and survived the first draft of this case — which is `B61`'s
    # family again, and the second time in one day that a source-text
    # assertion proved too weak (`B1404`'s guard checked for the *name*
    # `half_up` and `half_up = (v) => round(v)` walked past it). So: whatever
    # the helper's result is bound to has to be what the row reads.
    bound = re.search(r"const (\w+) = memoryConfidencePill\(", js)
    assert bound, "the renderer does not call the pill builder into a binding"
    name = bound.group(1)
    after = js[bound.end():]
    assert re.search(rf"\b{name}\.text\b", after), (
        f"`{name}` is computed and its text never read — the value is discarded")
    assert re.search(rf"\b{name}\.title\b", after), (
        f"`{name}`'s title never reaches the row, so the number has no explanation")
    assert not re.search(rf"const {name} = (null|undefined|false)\b", js), (
        f"`{name}` is overwritten with a constant")


def test_the_brain_list_renders_it_too_because_that_is_where_it_is_corrected():
    js = "\n".join(ln for ln in MEMJS.read_text(encoding="utf-8").splitlines()
                   if not ln.lstrip().startswith("//"))
    assert "memoryConfidencePill" in js, "the Brain list does not show confidence"
    assert re.search(r"for \(const pill of .*memoryConfidencePill", js), (
        "the confidence pill is not in the list's pill loop")


def test_the_shared_module_imports_nothing():
    """The reason it exists. `chatRenderer.js` cannot import `memory.js` —
    `memory.js` -> `sessions.js` -> `chatRenderer.js` is a cycle, which
    `sessions.js` documents at its own call site — so the helpers live in a
    module with no imports at all, the way `src/memory_edges.py` was carved out
    of the Python for the same reason in `P13-02`.

    An import here would reintroduce the cycle silently, so it fails here."""
    source = blank(FACTS)
    imports = re.findall(r"^\s*import\s+.*$", source, re.M)
    assert imports == [], f"memoryFacts.js imports {imports}"
    # Comments blanked first: this module's own header explains the cycle by
    # naming `window.memoryModule`, and the first draft of this case failed on
    # its own prose. `B290`, for the third time today.
    assert "window." not in source and "document." not in source, (
        "memoryFacts.js reaches for the DOM, so it is no longer importable "
        "outside a browser — which is what lets a test load it directly")


def test_both_pill_styles_exist_and_are_theme_aware():
    css = STYLE.read_text(encoding="utf-8")
    for selector in (".memory-confidence", ".memory-used-confidence", ".memory-used-why"):
        assert selector in css, f"{selector} has no style"
    block = css[css.index(".memory-used-confidence"):]
    block = block[:block.index("}")]
    # `var(--fg-muted)` since `B1408`: the first draft used `var(--fg)` at
    # `opacity: 0.4`, which measures 1.90:1 on `light`. Still a palette token
    # — which is what this case is about — and now one pinned at the floor.
    assert "var(--fg-muted)" in block, (
        "the chat pill's confidence is painted a literal colour")


# ── The id, finally used ───────────────────────────────────────────────────

def test_the_click_opens_the_memory_the_pill_names():
    """`P13-10` put `id` on the payload *"so the panel can open the memory the
    pill names rather than matching on text"*, and then nothing passed it: the
    click opened the window at whatever it last showed."""
    js = "\n".join(ln for ln in RENDERER.read_text(encoding="utf-8").splitlines()
                   if not ln.lstrip().startswith("//"))
    assert "revealMemory" in js, "the click still ignores the id"
    assert re.search(r"revealMemory\(m\.id\)", js), (
        "the click calls revealMemory without the id it was given")
    brain = MEMJS.read_text(encoding="utf-8")
    assert re.search(r"export async function revealMemory\(id\)", brain), (
        "revealMemory is not exported from the Brain")
    assert "revealMemory" in brain[brain.index("const memoryModule = {"):], (
        "revealMemory is not on `window.memoryModule`, which is how the "
        "renderer reaches it without importing memory.js")


def test_revealing_a_memory_honours_reduced_motion():
    """`P1-15`. A scroll that glides when the reader asked for no motion is the
    row this mirrors, and `skills.js` already does it this way."""
    brain = MEMJS.read_text(encoding="utf-8")
    body = brain[brain.index("export async function revealMemory"):]
    body = body[:body.index("\n}\n")]
    assert "scrollBehavior()" in body, (
        "revealMemory scrolls with a hard-coded behaviour")
    assert "scrollIntoView" in body


# ── `B1408`: text mixed toward transparent ─────────────────────────────────

def test_the_confidence_label_does_not_mix_itself_toward_transparent():
    """`B1408`, found by this row shipping the defect.

    The label's first draft was
    `color-mix(in srgb, var(--fg) 40%, transparent)`, which measures **1.90:1**
    on `light` — a WCAG failure on a number whose whole job is to be read.
    Mixing text toward `transparent` does not dim the foreground, it *replaces
    part of it with the background*, and over the 21 non-`B15` palettes no
    alpha under **82%** clears 4.5:1.

    `--fg-muted` is the idiom that works and the product already had it:
    `color-mix(in srgb, var(--fg) 45%, var(--color-muted))` mixes toward an
    **opaque** colour, which is why `P1-03` could pin it at the floor. The
    de-emphasis survives and the text stays legible, which the alpha form
    cannot manage at once."""
    css = blank(STYLE)
    for selector in (".memory-confidence", ".memory-used-confidence"):
        rule = css[css.index(selector + " {"):]
        rule = rule[:rule.index("}")]
        assert "transparent" not in rule, (
            f"{selector} mixes its text toward transparent")
        assert "opacity" not in rule, (
            f"{selector} dims its text with opacity, which lets the "
            "background through exactly as a transparent mix does")
        assert "var(--fg-muted)" in rule, (
            f"{selector} does not use the one token pinned at the floor")


def test_the_audit_ratchets_the_rest_of_the_population():
    """191 more declarations did the same thing — a 30-step de-emphasis ladder
    somebody built on purpose. So the audit counts them and fails a **new**
    one, which is `check-zindex`'s pattern and `P3-20`'s rule: the ratchet is
    the value, not the number. (`B1408` moved 185 of them onto a ladder that
    keeps their order and clears the floor; the six left are recorded
    decoration — `tests/test_secondary_text_clears_the_floor_on_every_palette.py`.)"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_contrast_for_b1408", ROOT / ".pantheon" / "check-contrast.py")
    module = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = ["check-contrast", "--imported-by-test"]
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    finally:
        sys.argv = argv

    found = module._css_transparent_text()
    assert len(found) == module.BASELINE_TRANSPARENT_TEXT, (
        f"{len(found)} declarations mix text toward transparent and the "
        f"ratchet records {module.BASELINE_TRANSPARENT_TEXT}")
    # Exactly the count, with no slack: a ratchet one above the truth lets a
    # new site in free, which the first draft of this rule did.
    assert module.TRANSPARENT_TEXT_FLOOR_PCT == 82.0
    assert all(pct < 82.0 for _token, pct in found)
