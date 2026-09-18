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


# ===========================================================================
# `P10-05` — verifying the coverage, and the three things the audit missed.
#
# `P10-05` asks for a verification rather than a feature: does the guard cover
# **all 160 keyframes and the 7 canvas animators, including the 12 that
# `slashCommands.js` injects at runtime**? Re-measured 2026-09-18, and four of
# those numbers are wrong — two of them already corrected by `P1-12` on its own
# row, and two of them not:
#
#   * **139 `@keyframes` in `static/style.css`**, not 148 and not 149.
#     (`grep -c "@keyframes"` says 142; three of those lines are prose about
#     keyframes, in this file's own comments and in `P1-12`'s. That gap is why
#     the count is taken with comments blanked.)
#   * **5 distinct injected by `slashCommands.js`**, not 12 — the module carries
#     the same three-keyframe `egg-styles` string ten times verbatim, guarded by
#     an id check so only the first can ever apply. `P1-12` corrected this.
#   * **A sixth runtime injection nobody counted**: `chatStream.js` writes
#     `steer-pulse` into `document.head`. It carries its own narrow block, so it
#     was never a defect — but it was never in the audit either, and the next
#     one might not bring its own guard.
#   * **`static/login.html` defines `login-spin` and no guard reached it.** That
#     is the row's real finding and the only live defect here. The login page
#     does not load `style.css` — it mirrors the palette by hand so its first
#     paint owes nothing to the app's stylesheet — so it owed nothing to the
#     app's guard either. A person who has asked their operating system to stop
#     moving things got a ring spinning at 86rpm on the first screen the
#     product ever shows them.
#
# And one animator the row could not have named, because it is not a keyframe
# and not a canvas: `scrollHistory()` in `static/js/ui.js` lerps `scrollTop`
# frame by frame on its own `requestAnimationFrame` loop. It is invisible to the
# CSS guard (which describes declarative scrolling), to `P1-15`'s sweep (which
# looks for the literal `behavior: 'smooth'`), and to `theme.js`'s canvas check.
# Eight JS animators, not seven.
# ===========================================================================

_KEYFRAMES = re.compile(r"@(?:-webkit-)?keyframes\s+([\w-]+)")
LOGIN = (ROOT / "static" / "login.html").read_text(encoding="utf-8")
UI_JS = (ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")


def _injected_keyframes() -> dict:
    """module path -> the distinct keyframe names it writes at runtime."""
    out = {}
    for path in sorted((ROOT / "static").rglob("*.js")):
        if "lib/" in str(path):
            continue
        names = set(_KEYFRAMES.findall(blank(path)))
        if names:
            out[str(path.relative_to(ROOT))] = sorted(names)
    return out


def test_the_keyframe_census_is_not_the_number_on_the_row():
    """`Law 6`. Every figure here is measured at read time; none is carried."""
    in_css = _KEYFRAMES.findall(blank_text(CSS, "css"))
    assert len(in_css) == 139, (
        f"expected 139 `@keyframes` in static/style.css, found {len(in_css)}. "
        "The row says 160 (148 + 12) and `P1-12` says 149; both were measured "
        "on an older file and neither is today's number."
    )
    assert len(set(in_css)) == len(in_css), (
        "two @keyframes share a name — they are global, so the last one wins "
        "for every consumer"
    )

    injected = _injected_keyframes()
    assert set(injected) == {
        "static/js/chatStream.js",
        "static/js/slashCommands.js",
    }, f"a module started injecting keyframes: {sorted(injected)}"
    assert len(injected["static/js/slashCommands.js"]) == 5, injected
    assert injected["static/js/chatStream.js"] == ["steer-pulse"], injected


# One exception, and it is one page rather than a pattern. `wave-variants.html`
# is a developer sandbox — it is *served*, because the `/static` mount has no
# allowlist, but nothing in the product links to it and its own first comment
# says so. What it animates it animates with a `setInterval` that no CSS guard
# could reach in any case: picking the shape of a moving thing side by side is
# the entire reason the page exists. Its two siblings,
# `whirlpool-variants.html` and `modal-control-variants.html`, are NOT excused
# — they simply declare no CSS motion, so the rule above passes on them
# honestly and will start failing the day one of them does. Named rather than
# matched by `*-variants.html`, so a real page cannot join the exception by
# being given a similar filename. The unguarded script motion in the two that
# animate from JavaScript is `B663`.
_DEVELOPER_SANDBOXES = {"wave-variants.html"}


def test_every_shipped_page_that_animates_is_under_a_guard():
    """The question the row asks, asked of pages rather than of one file.

    A page is covered when it links `static/style.css` (and therefore the
    global guard) **or** carries a `prefers-reduced-motion` block of its own.
    `login.html` failed this and nothing said so, because every previous audit
    was scoped to the stylesheet that already had the guard in it — which is
    the shape of this defect in one sentence: the audit was run inside the file
    that had already been fixed.
    """
    uncovered = []
    for page in sorted((ROOT / "static").glob("*.html")):
        if page.name in _DEVELOPER_SANDBOXES:
            continue
        text = page.read_text(encoding="utf-8")
        blanked = blank_text(text, "html")
        animates = bool(_KEYFRAMES.search(blanked)) or bool(
            re.search(r"(?:^|[{;])\s*(?:animation|transition)\s*:", blanked, re.M)
        )
        if not animates:
            continue
        links_sheet = "/static/style.css" in text
        own_guard = "prefers-reduced-motion" in blanked
        if not (links_sheet or own_guard):
            uncovered.append(page.name)
    assert uncovered == [], (
        f"these shipped pages animate and no reduced-motion guard reaches "
        f"them: {uncovered}"
    )


def test_the_excused_pages_are_still_the_sandboxes_they_claim_to_be():
    """An exception list that nobody re-reads is how a real page ends up
    excused. Each of the three still has to say what it is, in its own file."""
    for name in sorted(_DEVELOPER_SANDBOXES):
        page = ROOT / "static" / name
        assert page.exists(), f"{name} is gone; drop it from the exception list"
        head = page.read_text(encoding="utf-8")[:1200]
        assert "developer sandbox" in head.lower(), (
            f"{name} no longer declares itself a developer sandbox, so it is "
            "not obviously excused from the guard any more"
        )


def test_the_login_page_carries_the_same_guard_and_not_a_different_one():
    """It cannot borrow the app's: it deliberately links no stylesheet. So it
    gets the same shape, with the same two decisions behind it — `0.01ms`
    rather than `none`, and the `:is()` armour rather than `*` — because two
    idioms for one rule is how the second one goes stale (`Law 14`)."""
    assert "/static/style.css" not in LOGIN, (
        "the login page now links the app stylesheet, so it inherits the "
        "global guard and this local one is a second way to do one thing"
    )
    blanked = blank_text(LOGIN, "html")
    assert "@media (prefers-reduced-motion: reduce)" in blanked, (
        "the login page's spinner still animates for someone who asked it not "
        "to — and it is the first screen the product shows"
    )
    guard = blanked.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    guard = guard[: guard.index("}\n  }") + 4] if "}\n  }" in guard else guard[:600]
    assert GUARD_SHAPE.search(guard), (
        f"the login guard is not the armoured shape: {guard[:200]!r}"
    )
    assert "0.01ms" in guard and "animation: none" not in guard
    assert _KEYFRAMES.search(blanked), (
        "login.html no longer defines a keyframe, so this guard has nothing "
        "left to guard — check before deleting it, the spinner may just have "
        "moved"
    )


def test_the_canvas_registry_is_still_the_seven_the_row_counted():
    registry = THEME.split("const _CANVAS_PATTERNS", 1)[1].split("};", 1)[0]
    names = re.findall(r"'?([\w-]+)'?\s*:\s*_init", registry)
    assert len(names) == 7, f"expected seven canvas animators, found {names}"


def test_the_scroll_lerp_asks_before_it_animates():
    """The eighth animator, and the one nothing covered.

    `Law 20` option 2 — the function is resolved first and the assertion made
    inside it. `ui.js` is 2,000+ lines with five imports and a module-scope
    toast singleton, and `scrollHistory` is four lines; a file-wide search for
    `prefersReducedMotion` would be satisfied by the import statement alone,
    which is exactly the mistake `B41` shipped green.
    """
    from test_a_draft_skill_is_uncatalogued_not_inactive import js_function

    body = js_function(UI_JS, "export function scrollHistory")
    assert len(body.splitlines()) < 30, (
        f"js_function returned {len(body.splitlines())} lines for a short "
        "function; the scope resolution has drifted and this assertion is "
        "file-wide"
    )
    assert "prefersReducedMotion()" in body, (
        "`scrollHistory` starts a requestAnimationFrame lerp over `scrollTop` "
        "without asking. The CSS guard's `scroll-behavior: auto !important` "
        "does not reach it — that describes a declarative scroll, and this is "
        "a script writing a number every frame."
    )
    assert "scrollHistoryInstant()" in body, (
        "the reduced-motion path should use the instant scroller that already "
        "sits beside it rather than a second one"
    )
    assert "import { prefersReducedMotion } from './motion.js';" in UI_JS, (
        "one module owns the query (`P1-12`); ui.js must not grow a second copy"
    )


def test_the_one_copy_of_the_query_outside_a_module_is_the_one_that_has_to_be():
    """`test_one_module_owns_the_media_query_string` scopes itself to
    `static/js/**`, so the two inline scripts in the shipped pages are outside
    it. They are named here rather than left unmeasured.

    `index.html`'s boot loader genuinely cannot import `motion.js`: it runs
    before any module is fetched, and deciding whether to start a 150ms
    interval is the first thing it does. `login.html` has no guard in script at
    all — its answer is pure CSS. Anything else asking `matchMedia` about
    motion from a page rather than from a module is a third copy, and this
    fails.
    """
    asked = []
    for page in sorted((ROOT / "static").glob("*.html")):
        text = blank_text(page.read_text(encoding="utf-8"), "html")
        for m in re.finditer(r"matchMedia\s*\(\s*['\"]([^'\"]*)['\"]", text):
            if "prefers-reduced-motion" in m.group(1):
                asked.append(page.name)
    assert asked == ["index.html"], (
        f"expected the boot loader to be the only page-level copy, found {asked}"
    )
