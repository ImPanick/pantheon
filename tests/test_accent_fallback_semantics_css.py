# SPDX-License-Identifier: AGPL-3.0-or-later
from tests.helpers.source_text import blank, blank_text  # B290
"""P1-01 — the accent token, and the sites whose fallback was never an accent.

`P1-01` defines `--accent` per theme, beside `--red`, at three sites
(`theme.js` `applyColors()`, the first-paint script in `static/index.html`,
and `static/login.html`). It is deliberately never defined in `:root`: the
sixteen palettes are protected territory (`DECISIONS.md` D-2026-08-26-03) and a
`:root` rule would out-rank every `var(--accent, …)` fallback at once and flip
the whole stylesheet to one global colour.

`static/style.css` named `--accent` 828 times before this file, 817 after,
814 since `B23` moved SIX links off it — four spelled `var(--accent, var(--red))`
and the two `details a` rules, which were bare — and 813 since `H21` deleted the
`.search-fb-*` chips nothing drew (one `var(--accent, var(--red))` border).
Three populations, and they are not the same kind of thing:

  * **561 sites reach the theme's red through their fallback.** 552 of them
    spell it `var(--accent, var(--red))`; nine take a longer road —
    `var(--red, #e53935)` and two more literals, plus two routed through the
    undefined `--accent-primary` first. They resolved to the theme's red before
    the row and resolve to it after. They are the row's proof of safety and
    nothing here may edit them — but both counts are pinned, because a fallback
    quietly rewritten is exactly the edit that would move a site into one of
    the other two populations without anyone noticing. The two numbers are also
    what the comments on this row quote, and they measure different things,
    which has already cost a review pass;

  * **204 sites paint nothing today** — 202 a bare `var(--accent)`, one a
    fallback to the undefined `--accent-primary`, one a fallback to the
    undefined `--blue` — and gain the accent for the first time. That is what
    the row exists to deliver, and nothing here touches them either;

  * **50 sites carried a hand-picked fallback** that resolves today, and change
    colour. The row never named this class; before the corrections below there
    were 60 of them, plus three more whose `--blue` fallback made them look
    like gaining sites while carrying an unmistakable intent. Most genuinely
    wanted an accent — a hover border, a focus ring, a selection highlight, a
    drag ghost — and keep it. Twelve `var(--accent, …)` uses, across eleven
    declarations and nine rules, did not, and are corrected here.

The twelve were not accent sites. They carried semantic colour, and the author
reached for `var(--accent, <the real colour>)` only because `--accent` did not
exist yet and the fallback was the actual intent. Under a red accent each of
them collides with a sibling that means the opposite:

  * `.skill-verified` sat between `.skill-teachermark` (`--color-warning`) and
    `.skill-needsmark` (`--color-danger`) and was the one badge in the set that
    did not name a `--color-*` band. A "verified" mark rendering in the colour
    two lines below it means "needs work" is a `Law 15` defect that ships
    silently;
  * the tasks rail draws "finished" and "failed" as two 7px dots, and a third
    rule deliberately lets failure win when both are pending — an override
    that only means something while the two differ;
  * the supervisor ladder's whole purpose is to separate "the agent
    recovering" from the stop rung, and the stop rung dilutes `var(--red)` to
    the same 60% on the same dot;
  * `.note-checkbox-edit:hover` sits beside `.note-checkbox-rm:hover`
    (`var(--red)`), same geometry, same 12% tint — a red accent gives the
    destructive control and the benign one next to it an identical hover;
  * two links in rendered body text, where blue is the convention and red is
    the colour this product uses to say something is broken.

What is pinned below, and why each is a defect if it breaks:

  * **`--accent` is defined nowhere in this stylesheet.** The single failure
    mode the row is built to avoid, asserted directly rather than inferred;
  * **the no-change population stays 552 spelled and 561 resolved**, so a
    fallback rewritten in place is visible in the diff of a test rather than
    only in a screenshot;
  * **every token named inside an `--accent` fallback exists**, with the one
    known-dead exception named. `--blue` has never been defined anywhere in
    this sheet; a fallback naming it is a declaration that silently paints
    nothing;
  * **full-strength accent text clears 4.5:1 against `--panel` on exactly nine
    of the sixteen palettes**, and the seven it does not are named. This is not
    this row's defect to fix — `--red` is the theme's own brand colour and the
    shortfall is a property of the palette, which is what `P1-08`'s
    `--on-accent` guard is for — but the *set* is pinned so a new palette, or a
    dimmed red, cannot join it in silence, and the *population* is pinned so
    the number of declarations living under that exception cannot grow;
  * **the corrected sites stay corrected**, measured on all sixteen palettes as
    a colour difference and not as a substring: a verified badge, a finished
    task, a recovering supervisor and an edit button each resolve to something
    the eye can tell from the failure/destructive colour beside them.

Deliberately not pinned here: text painted *on* an accent background. 33 rules
do it — a hard-coded `#fff` in 19 of them, `var(--bg)` or `var(--panel)` in the
rest — and on every one of the sixteen palettes at least 14 of the 33 fall
under 4.5:1; on `light`, `paper`, `retrowave`, `lavender`, `claude` and `cute`
all 33 do. Nothing in this file can fix that, because the fix is a foreground
token that knows what the accent is. That is `P1-08` (`--on-accent`), and
writing a weaker assertion here would make it look handled.

Read out of `static/style.css` and `static/js/theme.js`. A stylesheet cannot be
driven under node the way `tests/test_trust_ladder_js.py` and
`tests/test_tool_effect_surfaces_js.py` drive their modules, so the colour
resolver and the contrast maths from the latter's theme block are reproduced
here in the same shape — deliberately narrow, so an expression it cannot
resolve fails the test rather than being skipped. A silently unmeasured colour
is how the original defect stayed invisible.
"""

import bisect
import functools
import re
from pathlib import Path

from tests.helpers import css_colour  # B396: the one resolver

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "static" / "style.css"
THEME_JS = ROOT / "static" / "js" / "theme.js"

# WCAG 1.4.3 body-text floor. The 3:1 large-text floor is not used anywhere
# below: every site measured here is small text or a 7px dot.
FLOOR = 4.5


# ── Reading the stylesheet ──────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _css() -> str:
    """The sheet with comments blanked and byte offsets preserved.

    Offsets have to survive, because a `--accent` written inside a comment is
    not a use of it and every count below would be wrong by the number of
    times the comments happen to mention the token — which, in a sheet that
    documents its own corrections in place, is not a small number.
    """
    return blank(STYLE)


@functools.lru_cache(maxsize=1)
def _line_starts() -> list:
    """Offsets of every line start, for `_line_of`.

    Counting newlines from position zero for each of 817 hits re-reads a
    1.6MB string 817 times; the whole file measures in under two seconds with
    this and in a minute and a half without it.
    """
    return [0] + [m.end() for m in re.finditer(r"\n", _css())]


def _line_of(pos: int) -> int:
    return bisect.bisect_right(_line_starts(), pos)


@functools.lru_cache(maxsize=8)
def _var_uses(token: str) -> tuple:
    """Every `var(--<token>…)` in the sheet, as (line, whole expression).

    Balanced by hand rather than by regex: the fallbacks nest — a `color-mix`
    inside a `var()` inside another `var()` — and a non-greedy `\\)` stops at
    the first inner paren and reports half an expression.
    """
    css = _css()
    needle = "var(--" + token
    found = []
    i = 0
    while True:
        start = css.find(needle, i)
        if start < 0:
            return tuple(found)
        i = start + 1
        # `--accent-warm` and `--accent-primary` are different tokens.
        if css[start + len(needle):start + len(needle) + 1] not in (")", ",", " "):
            continue
        depth = 0
        for pos in range(css.index("(", start), len(css)):
            depth += (css[pos] == "(") - (css[pos] == ")")
            if depth == 0:
                found.append((_line_of(start), css[start:pos + 1]))
                break


def _fallback(expr: str) -> str:
    """The fallback half of a `var(--x, …)`, or "" when there is none."""
    inner = expr[len("var("):-1]
    depth = 0
    for i, ch in enumerate(inner):
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            return inner[i + 1:].strip()
    return ""


@functools.lru_cache(maxsize=1)
def _rule_index() -> dict:
    """Every declaration block in the sheet, keyed by each selector that opens it.

    A brace-stack walk over the punctuation rather than a regex per lookup. The
    regex form — anchor, non-greedy selector, `[^{}]*` body — backtracks its way
    through 1.6MB for seven seconds *per selector asked about*, which turned a
    two-second file into a ninety-second one.

    Only innermost blocks are recorded, so `@media` and `@keyframes` wrappers
    contribute their children and not themselves, and the children keep their
    document order — which, for selectors of equal specificity, is the cascade.
    `#…task-completion-pending::after` restates a background the grouped rule
    above it already set, and only the later one paints.
    """
    css = _css()
    index, stack, mark = {}, [], 0
    for match in re.finditer(r"[{};]", css):
        pos, ch = match.start(), match.group(0)
        if ch == "{":
            stack.append((css[mark:pos], pos + 1))
        elif ch == "}":
            if stack:
                selector_text, body_start = stack.pop()
                body = css[body_start:pos]
                selector_text = selector_text.strip()
                if "{" not in body and not selector_text.startswith("@"):
                    for part in selector_text.split(","):
                        key = re.sub(r"\s+", " ", part).strip()
                        if key:
                            index.setdefault(key, []).append(body)
        mark = pos + 1
    return index


def _rules(selector: str) -> list:
    """Every rule whose selector list contains this exact selector, in order."""
    bodies = _rule_index().get(selector)
    assert bodies, f"no rule in the sheet selects {selector!r}"
    return bodies


def _decl(selector: str, prop: str) -> str:
    """What `prop` resolves to for `selector`, after the cascade and `!important`."""
    value = None
    for body in _rules(selector):
        stripped = blank_text(body, "css")
        for chunk in _split_decls(stripped):
            match = re.match(r"\s*([a-z-]+)\s*:\s*(\S.*?)\s*$", chunk, re.S)
            if match and match.group(1) == prop:
                value = re.sub(r"\s*!important\s*$", "", match.group(2))
    assert value is not None, f"{selector!r} sets no {prop!r}"
    return re.sub(r"\s+", " ", value)


def _split_decls(body: str) -> list:
    """Split a rule body on top-level `;` only — `color-mix()` contains commas
    but no semicolons, so depth tracking is enough."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(body):
        depth += (ch == "(") - (ch == ")")
        if ch == ";" and depth == 0:
            out.append(body[start:i])
            start = i + 1
    out.append(body[start:])
    return out


@functools.lru_cache(maxsize=1)
def _root_tokens() -> dict:
    """The tokens `:root` defines, as expressions. `--accent` is not among them,
    and `test_accent_is_defined_nowhere_in_the_stylesheet` is why.

    EVERY custom property `:root` declares, since `B396` — this read hex
    literals, then `light-dark()` pairs and `var()`s (`B22`), and each widening
    was a correction rather than a refinement: a token this function cannot
    see is absent from the theme dict, so the resolver silently takes the
    `var(--x, <fallback>)` branch and measures the fallback on every palette.
    That is how `test_the_supervisor_ladder_still_separates_recovering_from_stop`
    reported a collision on `claude` and `copper`, whose values had not moved.
    """
    return css_colour.root_expressions(_css())


# ── Reading the palettes ────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _themes() -> dict:
    """The shipped palettes, with `--accent` resolved the way `applyColors()`
    resolves it today (`css_colour.palettes`).

    `colors.accent` exists in no palette and `generateHarmonyColors()` produces
    none, so `colors.accent || colors.red` is the theme's red at every one of
    the three sites that set it. When a palette gains its own `accent:` key
    this starts reporting it and every measurement below re-runs against the
    new value, which is the point of reading it from source.
    """
    return css_colour.palettes(_root_tokens())


# ── Colour ─────────────────────────────────────────────────────────────────

# Tokens an `--accent` fallback may name that no `:root` rule and no
# `setProperty` call defines. Both are inert now that `--accent` always
# resolves; they are listed so the list cannot grow without a test failing.
#
#   --blue            `.note-check-text[contenteditable="true"]`. The two other
#                     sites that named it — `.note-checkbox-edit:hover`'s colour
#                     and its tint — were corrected, because a red hover there
#                     is indistinguishable from the delete button beside it.
#                     This one is a focus outline on the text being edited and
#                     genuinely wanted the accent, so it keeps it.
#   --accent-primary  `theme.js` `ADV_KEYS` does not carry it (only
#                     `static/index.html`'s `advMap` does, and only for a custom
#                     theme that names one), so it is undefined for all sixteen
#                     shipped palettes.
_DEAD_FALLBACK_TOKENS = {"blue", "accent-primary"}


# `B396`. One resolver for the suite: this file's copy split `color-mix()`
# with a regex and did not recurse into a token's expression.
_PaintsNothing = css_colour.PaintsNothing
_rgb = css_colour.rgb
_resolve = css_colour.resolve
_contrast = css_colour.contrast
_distance = css_colour.distance


def test_accent_is_defined_nowhere_in_the_stylesheet():
    """A `:root { --accent: … }` would out-rank all 813 fallbacks at once.

    `--accent` is set per theme, beside `--red`, at the three places that set
    `--red`. Defining it here as well — in `:root`, in `:root.light`, in a
    media query, anywhere — makes the fallback half of every
    `var(--accent, …)` in this file dead text and hands all sixteen palettes
    the same colour. That is the whole failure mode, so it is asserted
    directly.
    """
    defined = [
        (_line_of(m.start()), m.group(0).strip())
        for m in re.finditer(r"(?:^|[{;])\s*--accent\s*:[^;}]*", _css())
    ]
    assert not defined, (
        "--accent must never be defined in the stylesheet; found "
        + "; ".join(f"line {line}: {text}" for line, text in defined)
    )
    # `--accent-warm` is a different token and is allowed to live in `:root`.
    assert "--accent-warm:" in _css(), "the warm accent token should still exist"


def test_the_no_change_population_holds_at_both_of_its_counts():
    """A site whose fallback resolves to the theme's red resolved to it before
    the row and resolves to it after. That is the row's evidence that nothing
    moved, and it is only evidence while the count holds. Rewriting one of
    these fallbacks to `var(--fg)` or a literal is a one-token edit that
    changes what a site paints and shows up nowhere else.

    Two counts, because the two that get quoted about this row are counts of
    different things and disagreeing about it has already cost one review pass:
    552 sites spell the fallback `var(--red)` exactly, and a further nine reach
    the same colour through a chain — `var(--red, #e53935)` and friends, plus
    two that route through the undefined `--accent-primary` first.

It was 552 until 2026-09-18, and the one that arrived is named rather than
    absorbed: `.skill-lint-problem`'s `border-left-color`, the rule that ranks a
    `problem` finding in `P8-12`'s pre-save lint panel. It is a **border** and
    not a `color:` deliberately — the population below holds at 181 because a
    182nd full-strength accent `color:` would be a 182nd site failing 4.5:1 on
    seven palettes, and a panel of things somebody has to read and act on is the
    last place to add one.

    It was 556 until `B23`, and the four that left are named rather than
    absorbed: `.doclib-research-sources a`, the Gmail chip link inside
    `.email-reader-body`, `.note-form-content-reader a` and
    `.note-fullscreen-overlay .note-cl-text-reader a`. All four are LINKS in
    running text, all four measured 2.24:1 on `paper`, and all four now name
    `--link-fg` — the one link idiom that clears AA against `--panel` on all
    sixteen palettes. `B23` moved two more that this count does not see,
    because `details a` and its second rule spelled the accent BARE: they are
    in the total below, which fell 815 → 813, and rose to 814 on 2026-09-18
    with `.skill-lint-problem`. None of the six stopped being an
    accent site by accident.

    It was 553 until 2026-10-27, and the one that left is named: the
    `border-color` of `.search-fb-add:focus, .search-fb-add:hover`, deleted
    with the `.search-fallback-chain` block by `H21` — chips nothing ever drew
    (Settings' fallback chain is `.settings-fallback-row`). 562 → 561 resolved
    and 814 → 813 in total with it.
    """
    exact = [expr for _, expr in _var_uses("accent")
             if _fallback(expr) == "var(--red)"]
    # 553 -> 551, 562 -> 560 and 814 -> 812: `B781` moved `.plan-mode-btn.active`
    # (its `color` and its tint, two `var(--accent, var(--red))`) onto the
    # composer strip's one on-state, `.tool-indicator.active`, which is
    # `var(--red)`. Deliberately, in the direction that removes accent sites;
    # on every shipped palette `--accent` IS the red, so no pixel of the chip's
    # colour moved.
    # 551 -> 550, 560 -> 559, 812 -> 811: `H21` deleted the `.search-fb-*`
    # chips nothing drew, whose `.search-fb-add` border was one of them.
    assert len(exact) == 550, (
        f"expected 550 sites spelling the fallback `var(--red)` exactly, found "
        f"{len(exact)}. If a site was legitimately added or removed, move this "
        "number and say which site in the commit — do not widen the assertion."
    )

    theme = _themes()["dark"]
    red = _resolve("var(--red)", theme)
    resolving = []
    for _, expr in _var_uses("accent"):
        fallback = _fallback(expr)
        if not fallback:
            continue
        try:
            painted = _resolve(fallback, theme, _rgb(theme["panel"]))
        except _PaintsNothing:
            continue  # a gaining site, counted by the population above
        if painted == red:
            resolving.append(expr)
    assert len(resolving) == 559, (
        f"expected 559 sites whose fallback resolves to the theme's red, found "
        f"{len(resolving)}"
    )
    assert len(_var_uses("accent")) == 811, (
        f"expected 811 uses of --accent in total, found {len(_var_uses('accent'))}"
    )


def test_every_token_named_in_an_accent_fallback_exists():
    """A fallback naming a token nothing defines is a declaration that paints
    nothing — silently, with no console warning and no visual cue that anything
    was meant to be there. `--blue` was that, in three places, for as long as
    the sheet has existed.
    """
    known = set(_root_tokens()) | set(
        re.findall(r"setProperty\('--([a-z-]+)'", THEME_JS.read_text(encoding="utf-8"))
    )
    missing = {}
    for line, expr in _var_uses("accent"):
        for name in re.findall(r"var\(--([a-z-]+)", _fallback(expr)):
            if name not in known:
                missing.setdefault(name, []).append(line)
    assert set(missing) <= _DEAD_FALLBACK_TOKENS, (
        "an --accent fallback names a token nothing defines: "
        + ", ".join(f"--{n} (lines {v})" for n, v in sorted(missing.items())
                    if n not in _DEAD_FALLBACK_TOKENS)
    )
    assert sum(len(v) for n, v in missing.items() if n == "blue") == 1, (
        "--blue is defined nowhere; exactly one site may still name it as a "
        f"fallback, found {missing.get('blue')}"
    )


# ── The contrast floor, and whose problem it is ─────────────────────────────
#
# `--red` is the palette's own brand colour rather than an error colour —
# `terminal` sets it to `#00ff41` and `ocean` to `#4facfe`. On seven of the
# sixteen it does not clear 4.5:1 against that palette's `--panel`, and no edit
# to this stylesheet can change that: the shortfall belongs to the palette. Two
# of them (`cute`, `retrowave`) put their own *body text* under 4.5:1 as well,
# so the floor is unreachable there for any colour at all.
#
# Closing it is `P1-08`'s job — an `--on-accent` companion, and a guard that
# picks a legible foreground per theme. What these two tests do is stop the
# exception from growing while that is outstanding: the named palettes cannot
# gain a member without a failure, and the number of declarations sheltering
# under the exception cannot go up.

# `B390` (`D-2026-10-26-01` §13) darkened `retrowave`'s surfaces, and its
# accent on the new `--panel` clears — so it left this set.
_ACCENT_TEXT_UNDER_FLOOR = {
    "light", "paper", "organs", "lavender", "claude", "cute",
}


def _full_strength_accent_colour_decls() -> list:
    """Every `color:` whose value *is* the accent, undiluted.

    A `color-mix(… var(--accent) 80%, var(--fg))` is excluded on purpose: it is
    pulled back toward the text colour and measures differently per theme.
    """
    return [
        (_line_of(m.start()), re.sub(r"\s*!important\s*$", "", m.group(1)))
        for m in re.finditer(
            r"(?:^|[{;])\s*color\s*:\s*(var\(--accent[,)][^;{}]*?)\s*(?=[;}])",
            _css(), re.M,
        )
    ]


def test_full_strength_accent_text_clears_the_floor_on_nine_palettes():
    measured = {
        name: _contrast(_rgb(theme["accent"]), _rgb(theme["panel"]))
        for name, theme in _themes().items()
    }
    under = {n for n, r in measured.items() if r < FLOOR}
    assert under == _ACCENT_TEXT_UNDER_FLOOR, (
        "the set of palettes on which accent-coloured text misses "
        f"{FLOOR}:1 against --panel has changed.\n"
        "  now under: " + ", ".join(f"{n} ({measured[n]:.2f})" for n in sorted(under))
        + "\n  expected:  " + ", ".join(sorted(_ACCENT_TEXT_UNDER_FLOOR))
        + "\nA palette joining this set means a shipped theme got less legible; "
        "a palette leaving it means P1-08 has work it can retire."
    )
    clears = {n: r for n, r in measured.items() if n not in under}
    assert len(clears) == 17, f"expected seventeen palettes above the floor, got {sorted(clears)}"


def test_the_population_under_the_contrast_exception_cannot_grow():
    """181 declarations paint text in the undiluted accent. Every one of them
    is illegible on the seven palettes above, and none of them can be fixed
    here — but a *new* one is a new instance of a known defect, and a semantic
    site converted into one is the regression this file exists to catch.
    """
    decls = _full_strength_accent_colour_decls()
    # 181 -> 180: `B781`, the plan chip's on-state, now `.tool-indicator.active`'s
    # `var(--red)` (see the population test above). One fewer, on purpose.
    assert len(decls) == 180, (
        f"expected 180 full-strength accent `color:` declarations, found "
        f"{len(decls)}. Adding one adds a site that fails the contrast floor on "
        "seven of the sixteen palettes."
    )
    # Every one of them must at least resolve; a bare `var(--accent)` is fine
    # (the token is always set) but a chain dead-ending elsewhere is not.
    for theme in _themes().values():
        for line, value in decls:
            _resolve(value, theme)


# ── The corrections, measured rather than grepped ──────────────────────────


def test_a_verified_badge_is_not_the_colour_of_a_needs_work_one():
    """`.skill-verified` was the one badge of three that named no `--color-*`
    band. Under a red accent it renders in `.skill-needsmark`'s colour, which
    is the same claim inverted, on every palette at once.
    """
    verified = _decl(".skill-verified", "color")
    needswork = _decl(".skill-needsmark", "color")
    assert "--accent" not in verified, (
        f".skill-verified must not reach for the accent; got {verified!r}"
    )
    same = []
    for name, theme in _themes().items():
        if _distance(_resolve(verified, theme), _resolve(needswork, theme)) < 40:
            same.append(name)
    assert not same, (
        "'verified' and 'needs work' are the same colour on " + ", ".join(sorted(same))
    )


def test_finished_and_failed_never_paint_the_same_dot():
    """The tasks rail draws both as a 7px dot with a glow. A third rule lets
    failure win when a session has both pending — an override that is a no-op
    the moment the two rungs resolve alike.
    """
    done_text = _decl("#tool-tasks-btn.task-completion-pending", "color")
    fail_text = _decl("#tool-tasks-btn.task-failure-pending", "color")
    done_dot = _decl("#tool-tasks-btn.task-completion-pending::after", "background")
    fail_dot = _decl("#tool-tasks-btn.task-failure-pending::after", "background")
    assert "--accent" not in done_text and "--accent" not in done_dot, (
        f"the completion rung must not reach for the accent; got {done_text!r} "
        f"and {done_dot!r}"
    )
    collisions = []
    for name, theme in _themes().items():
        ground = _rgb(theme["panel"])
        for label, done, failed in (
            ("label", done_text, fail_text), ("dot", done_dot, fail_dot),
        ):
            if _distance(_resolve(done, theme, ground),
                         _resolve(failed, theme, ground)) < 40:
                collisions.append(f"{name} ({label})")
    assert not collisions, (
        "'tasks finished' and 'tasks failed' are indistinguishable on "
        + ", ".join(collisions)
    )


def test_the_supervisor_ladder_still_separates_recovering_from_stop():
    """The tint exists so a reader can tell "the agent is recovering" from
    "the agent stopped". The stop rung dilutes `var(--red)` to 60% on the same
    dot, so an accent-tinted base rung produces two identical circles.
    """
    base = _decl(".agent-thread-node.supervisor-step .agent-thread-dot", "background")
    stop = _decl(
        '.agent-thread-node.supervisor-step[data-rung="stop"] .agent-thread-dot',
        "background",
    )
    assert "--accent" not in base, (
        f"the recovering rung must not reach for the accent; got {base!r}"
    )
    same = []
    for name, theme in _themes().items():
        ground = _rgb(theme["panel"])
        if _distance(_resolve(base, theme, ground), _resolve(stop, theme, ground)) < 25:
            same.append(name)
    assert not same, (
        "the recovering rung and the stop rung draw the same dot on "
        + ", ".join(sorted(same))
    )


def test_editing_a_checklist_item_does_not_look_like_deleting_it():
    """The two buttons are the same size, adjacent, and hover with the same
    12% tint. Colour is the only thing separating them, and one of them is
    destructive.
    """
    edit = _decl(".note-checkbox-edit:hover", "color")
    remove = _decl(".note-checkbox-rm:hover", "color")
    assert "--accent" not in edit, (
        f"the edit control must not hover in the accent; got {edit!r}"
    )
    same = []
    for name, theme in _themes().items():
        if _distance(_resolve(edit, theme), _resolve(remove, theme)) < 60:
            same.append(name)
    assert not same, (
        "edit-hover and delete-hover are the same colour on " + ", ".join(sorted(same))
    )


def test_links_in_rendered_body_text_are_not_the_accent():
    """Two of them: a task log's markdown body and a composed email's body.
    Both are running text a reader scans for the blue-link convention.

    `P1-01` moved these two off the accent and onto `--color-accent`, on the
    strength of this sheet's own comment calling that token "the sheet's link
    hue". `B23` measured it and the comment was false: `--color-accent` had 14
    `var()` uses in the whole file and missed 4.5:1 on all four light palettes
    (2.38 on `light`). The hue this product actually uses for a link is
    `--hl-function` — `.msg a` and every link in every email body, the only
    idiom clearing AA on all sixteen palettes. It is now named once, as
    `--link-fg`, and this test holds the stronger claim: not the accent, AND
    the one named token.
    """
    for selector in (".task-log-row-body a", ".doc-email-richbody a"):
        value = _decl(selector, "color")
        assert "--accent" not in value, (
            f"{selector} must not paint a link in the accent; got {value!r}"
        )
        assert "--link-fg" in value, (
            f"{selector} should name the sheet's one link token; got {value!r}"
        )
    # How far the link hue sits from each palette's red is NOT measured here,
    # and that is deliberate rather than dropped. `--link-fg` resolves to
    # `--hl-function`, which `applyColors()` DERIVES per palette
    # (`deriveSyntaxColors`, hue 210 at a fixed lightness); this file's
    # `_themes()` overlays only `bg/fg/panel/border/red`, so it would read
    # `:root`'s `#61afef` — the `dark` palette's value — on all sixteen and
    # call that a measurement. `tests/test_theme_contrast_floor_css.py` drives
    # the real `applyColors()` in node and makes the claim properly, over all
    # sixteen palettes: closest approach to the palette's own accent is 46.2
    # sRGB units on `ocean` and 57.5 on `gpt`, both blue-accented themes, and
    # that has been true of `.msg a` since long before `B23` named the token.


def test_a_success_tick_is_not_flashed_in_the_failure_colour():
    """The refresh button flashes a checkmark when a sync completes. The mark
    is a tick; a tick in the theme's red says the sync failed.
    """
    value = _decl("#cal-sync.cal-sync-done svg", "color")
    assert "--accent" not in value, f"got {value!r}"
    assert "--color-success" in value, f"got {value!r}"
