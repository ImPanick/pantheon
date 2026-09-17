# SPDX-License-Identifier: AGPL-3.0-or-later
"""P1-12 — one guard for everything that moves, and the two ways it fails quietly.

Before this there were 20 narrow `prefers-reduced-motion` blocks in
`static/style.css` against 149 `@keyframes` there and 5 more injected into
`document.head` at runtime, plus seven full-screen canvas background animators
running on `requestAnimationFrame` with nothing stopping them at all.

Both failure modes of the obvious fix are silent, which is why they are tested
rather than reviewed:

**`animation: none` breaks cleanup.** Modules across this product wait for
`animationend` / `transitionend` — `compare/panes.js` clears an inline
`animation` in that handler, `app.js` restarts the welcome animation by
toggling it off and on. With `none` the event never fires and the handler never
runs, so the "safer" spelling is the one that leaves state stuck. A duration
under a frame is invisible and still fires the event.

**A universal selector loses the cascade.** 21 `!important` declarations of
`animation`/`transition` already exist in this file across 34 selectors, and
between two `!important` author declarations *specificity* decides before order
does. `* { animation-duration: 0.01ms !important }` loses to every one of them
while reading as correct.

The row asking for this said a CSS-only guard could not reach the runtime-
injected keyframes. It can — an `!important` author declaration beats a normal
one whatever stylesheet it came from. What CSS cannot reach is a script
painting frames, which is what `static/js/motion.js` and the `theme.js` guard
are for.
"""
import json
import re
import shutil
import subprocess

import pathlib
import pytest
from tests.helpers.source_text import blank, blank_text  # B290

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
THEME = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
MOTION = (ROOT / "static" / "js" / "motion.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
_HAS_NODE = shutil.which("node") is not None

MARKER = "P1-12 — one guard for everything that moves."
# The shape, not the spelling. How many ids the guard needs is a fact about
# the rest of the file, and `test_the_guard_outranks_…` computes it — pinning
# the exact string here would mean a guard that is provably sufficient still
# fails a test, which is testing spelling.
GUARD_SHAPE = re.compile(r":is\((?:#\\9)+, \*\)")


def _before_guard(css):
    """Everything above the global block, comments stripped."""
    return blank_text(css.split(MARKER)[0], "css")


def _guard_rules(css):
    """The guard's declarations, with its explanation left behind.

    The marker sits *inside* the comment that introduces the block, so
    splitting on it lands mid-comment and a later `/* … */` strip finds no
    opening delimiter and removes nothing. Cut at the comment's terminator
    instead. (Found by a test asserting `animation: none` is absent, against a
    paragraph explaining why `animation: none` is wrong — `Law 20` twice in one
    file.)"""
    after = css.split(MARKER, 1)[1]
    return after.split("*/", 1)[1]


def _top_level_commas(text):
    """Split a selector list on commas that are not inside parentheses.

    `:is(#\\9#\\9#\\9, *)` contains a comma, so a plain `split(",")` turns three
    selectors into six halves — which is what it did, and the halves were not
    selectors at all."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    return [x.strip() for x in parts if x.strip()]


def _specificity(sel):
    """(ids, classes, types) for one compound/complex selector.

    Deliberately crude and deliberately *generous* to the existing rules: a
    functional pseudo-class is flattened away rather than expanded, which can
    only under-count what is already in the file. Under-counting there is the
    safe direction — it would make the guard look sufficient when it is not,
    and the assertion below uses a strict `>`."""
    s = re.sub(r"::?[a-z-]+\([^)]*\)", " ", sel.strip())
    # `#\9` is an id selector whose name is an escape, and a bare `[\w-]+`
    # does not match a backslash — which made this return (0,0,0) for the
    # guard itself on the first run. The guard was the one selector the
    # function existed to measure.
    ids = len(re.findall(r"#(?:\\.|[\w-])+", s))
    classes = (len(re.findall(r"\.[\w-]+", s))
               + len(re.findall(r"\[[^\]]*\]", s))
               + len(re.findall(r"(?<!:):(?!:)[a-z-]+", s)))
    types = len(re.findall(r"(?:^|[\s>+~])[a-z][\w-]*", s))
    return (ids, classes, types)


def _important_motion_selectors(css):
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel, body = m.group(1), m.group(2)
        if not re.search(r"(?:animation|transition)[a-z-]*\s*:[^;{}]*!important", body):
            continue
        for one in sel.split(","):
            one = one.strip()
            if one and not one.startswith("@"):
                out.append(one)
    return out


def test_the_guard_exists_and_is_the_last_word_on_motion():
    assert MARKER in CSS, "the global guard is gone"
    block = _guard_rules(CSS)
    assert GUARD_SHAPE.search(block), block[:200]
    for decl in ("animation-duration: 0.01ms !important",
                 "animation-iteration-count: 1 !important",
                 "transition-duration: 0.01ms !important",
                 "scroll-behavior: auto !important"):
        assert decl in block, decl
    assert CSS.rstrip().endswith("}"), "something was appended after the guard"


def test_the_guard_does_not_use_animation_none():
    """`none` stops `animationend` firing, and this product cleans up in that
    handler. The bug would be invisible until a modal refused to close.

    Comments stripped first: the paragraph above the block explains the trap by
    quoting `animation: none`, and matching that would be testing the
    explanation rather than the rule (`Law 20`). It failed exactly that way on
    the first run."""
    block = _guard_rules(CSS)
    assert "animation: none" not in block
    assert "transition: none" not in block
    assert "0.01ms" in block


def test_the_guard_outranks_every_important_motion_rule_already_here():
    """The ratchet. If somebody adds `#a .b .c { animation: … !important }`
    tomorrow, this fails and the guard needs another id — rather than the guard
    silently ceasing to apply to that one rule."""
    existing = _important_motion_selectors(_before_guard(CSS))
    assert len(existing) >= 30, (
        f"only {len(existing)} important motion selectors found — the parser "
        "stopped working, and every comparison below is vacuous"
    )
    worst = max(_specificity(s) for s in existing)

    # EVERY selector in the guard, not a sample. A mutation that rewrote two of
    # the three back to `*` and left the third survived a check that only
    # looked for the id form *somewhere* in the block.
    block = _guard_rules(CSS)
    # The text between the `@media {` and the rule's own `{` is the selector
    # list. Splitting on the first brace gives the media prelude instead, which
    # is what this did on the first run — it found no selectors and passed.
    parts = block.split("{")
    assert len(parts) >= 3, block[:200]
    selectors = _top_level_commas(parts[1])
    assert len(selectors) == 3, selectors
    for sel in selectors:
        # `:is()` takes the specificity of its most specific argument.
        inner = re.search(r":is\(([^,]+)", sel)
        assert inner, f"{sel} is not the :is() form and carries no weight"
        got = _specificity(inner.group(1))
        assert got > worst, (
            f"{sel} is {got} and the most specific !important motion rule in "
            f"the file is {worst}; between two !important author declarations "
            "specificity wins before order, so the guard would not apply "
            "there. Add another id to the :is()."
        )


def test_the_narrow_blocks_are_kept():
    """Law 1. Several of the 20 earlier blocks substitute a static appearance
    rather than merely freezing a moving one, so the global guard is an
    addition, not a replacement."""
    assert len(re.findall(r"@media \(prefers-reduced-motion: reduce\)", CSS)) >= 20


# --- the half CSS cannot reach --------------------------------------------


def test_one_module_owns_the_media_query_string():
    assert "'(prefers-reduced-motion: reduce)'" in MOTION
    assert "export function prefersReducedMotion" in MOTION
    others = []
    for path in sorted((ROOT / "static" / "js").rglob("*.js")):
        if path.name == "motion.js" or "lib/" in str(path):
            continue
        text = path.read_text(encoding="utf-8")
        if "matchMedia" in text and "prefers-reduced-motion" in text:
            others.append(path.name)
    assert others == [], (
        "a second copy of the query: " + repr(others) + ". Import "
        "prefersReducedMotion from ./motion.js instead."
    )


def test_theme_js_asks_before_starting_a_canvas_animator():
    assert "import { prefersReducedMotion } from './motion.js';" in THEME
    body = THEME.split("export function applyBgPattern", 1)[1].split("\nexport ", 1)[0]
    assert "prefersReducedMotion()" in body
    # The claim is that the guard is *consulted*, not that it is written on one
    # line: `P3-19` wrapped this call in a try/catch and the old exact-string
    # assertion failed on working code. What the guard does is proved by
    # execution in `test_background_animators_degrade.py`, which runs the real
    # `applyBgPattern` with the preference on and finds no canvas.
    assert "_CANVAS_PATTERNS[p] && !reduced" in body, (
        "the seven canvas animators are the whole JS half of this row"
    )
    assert "classList.add('bg-pattern-' + p)" in body, (
        "the theme class must still be applied — reduced motion stops the "
        "motion, it does not take the person's theme away"
    )


def test_the_panel_says_why_the_background_is_still():
    assert 'id="theme-reduced-motion-note"' in INDEX
    note = INDEX.split('id="theme-reduced-motion-note"', 1)[1].split("</div>", 1)[0]
    assert "hidden" in note
    assert "reduce" in note.lower() and "motion" in note.lower()
    assert "note.hidden = !(reduced" in THEME, "nothing ever shows it"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_applybgpattern_starts_nothing_under_reduced_motion():
    """The behaviour, not the source. Runs the real function with the canvas
    registry stubbed and the preference flipped both ways."""
    src = THEME.split("export function applyBgPattern", 1)[1]
    depth, i = 0, src.index("{")
    j = i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    body = "function applyBgPattern" + src[:j + 1]

    harness = """
    let started = [];
    let reduced = REDUCED;
    function prefersReducedMotion() { return reduced; }
    const _BG_CLASSES = ['bg-pattern-rain', 'bg-pattern-dots'];
    const _CANVAS_PATTERNS = { rain: () => started.push('rain') };
    const _STATIC_PATTERNS = new Set(['none', 'dots']);
    const added = [];
    const els = {};
    const mkEl = () => ({ style: {}, hidden: false });
    for (const id of ['theme-bg-intensity-group', 'theme-bg-size-group',
                      'theme-reduced-motion-note']) els[id] = mkEl();
    const document = {
      body: { classList: { remove: () => {}, add: (c) => added.push(c) } },
      querySelectorAll: () => [],
      getElementById: (id) => els[id] || null,
    };
    BODY
    applyBgPattern('rain');
    console.log(JSON.stringify({
      started, added,
      intensityHidden: els['theme-bg-intensity-group'].style.display,
      noteHidden: els['theme-reduced-motion-note'].hidden,
    }));
    """

    def run(reduced):
        script = harness.replace("REDUCED", "true" if reduced else "false").replace("BODY", body)
        p = subprocess.run(["node", "--input-type=module", "-e", script],
                           cwd=ROOT, capture_output=True, text=True, timeout=20)
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout.strip().splitlines()[-1])

    on = run(True)
    assert on["started"] == [], "a canvas animator started under reduced motion"
    assert "bg-pattern-rain" in on["added"], "the theme class was dropped too"
    assert on["intensityHidden"] == "none", "sliders for a paused effect stayed"
    assert on["noteHidden"] is False, "nothing told the person why"

    off = run(False)
    assert off["started"] == ["rain"], "the animator stopped starting for everyone"
    assert off["intensityHidden"] == "", "the sliders vanished for everyone"
    assert off["noteHidden"] is True, "the note showed to someone who wants motion"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
@pytest.mark.parametrize("matches", [True, False])
def test_the_helper_reports_what_matchmedia_says(matches):
    """The helper itself, with `matchMedia` stubbed both ways. Every other test
    here stubs `prefersReducedMotion`, so a helper hardwired to `false` passed
    all of them — mutation testing said so."""
    script = MOTION.replace("export function", "function") + f"""
    let asked = null;
    globalThis.window = {{ matchMedia: (q) => {{ asked = q; return {{ matches: {str(matches).lower()} }}; }} }};
    console.log(JSON.stringify({{
      reduced: prefersReducedMotion(),
      behavior: scrollBehavior(),
      asked,
    }}));
    """
    p = subprocess.run(["node", "--input-type=module", "-e", script],
                       cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out["asked"] == "(prefers-reduced-motion: reduce)"
    assert out["reduced"] is matches
    assert out["behavior"] == ("auto" if matches else "smooth")


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_the_helper_survives_a_webview_with_no_matchmedia():
    """Some embedded webviews throw. Erring towards motion is what a browser
    with no preference set does, and throwing here would take a background
    animator down with it."""
    script = MOTION.replace("export function", "function") + """
    globalThis.window = { get matchMedia() { throw new Error('nope'); } };
    console.log(JSON.stringify({ reduced: prefersReducedMotion() }));
    """
    p = subprocess.run(["node", "--input-type=module", "-e", script],
                       cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout.strip().splitlines()[-1])["reduced"] is False
