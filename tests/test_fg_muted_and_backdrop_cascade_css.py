"""P1-03 — the muted foreground token; P1-04 — the backdrop that could never show.

Two rows, one file, because both are claims about what `static/style.css`
*resolves to* rather than about what it contains, and both need the same two
machines: a colour resolver that knows the sixteen palettes, and a cascade
walk that knows which rules a given viewport actually applies.

── P1-03 ────────────────────────────────────────────────────────────────────

`--fg-muted` was named 101 times in this stylesheet and declared nowhere. 93 of
those uses are bare, so the declaration was invalid at computed-value time and
dropped: the element inherited body text at full strength. The row's own
framing — "every one of those elements was authored as secondary text and
renders at full strength" — is right but undersells it. Three of the sites are
tab strips (`.cookbook-tab`, `.lib-tab`, `.admin-tab`) that hover to
`var(--fg)`, so base and hover were the same colour and the hover did nothing;
four more are hover-border rules that painted no border at all; and
`.ge-adj-hist-handle` is a triangle drawn purely from `border-color`, so it was
invisible. Defining the token repairs those as a side effect, which is why they
are asserted here and not merely counted.

Three populations, and — unlike `P1-01`, whose lesson was that its two-class
model had a third class hiding in the fallbacks — this row's fallbacks are
uniform:

  * **93 bare uses gain the muted colour.** 87 `color:`, 4 `border-color:`,
    2 `background:`. This is the row's deliverable;

  * **8 uses carry a fallback and move.** Six spell it `#888` and two spell it
    `var(--fg)`. Both spellings were hand-rolled stand-ins for the token that
    did not exist: the two `var(--fg)` sites are class-one sites in disguise
    (`.cookbook-server-cancel-btn`'s own comment says "muted" and its
    `:hover { color: var(--fg) }` was a no-op), and the `#888` sites reach a
    theme-blind grey that the token replaces with a theme-aware one;

  * **0 uses carry a fallback the token flattens.** This was checked with the
    criterion `P1-01` established — after the change, is this element
    indistinguishable from a sibling that means the opposite? — against every
    rule in the sheet that sets the same property on a selector sharing the
    base class. The one candidate that looked like class three ran the other
    way: `.cookbook-serve-downloading-pill.is-stalled` reads "stalled, not
    progressing" in `#888`, and on `gpt` — whose `--red` is `#949494` — that
    grey sits 20.8 sRGB units from the accent its sibling pill paints, so the
    stalled pill and the progressing one were already the same colour there.
    Under the token they are 45.6 apart. The fallback was not protecting
    anything; it was hiding a collision.

Where the third class *did* exist was in the value, which is what
`test_the_muted_token_is_not_any_palettes_accent` is for. A token defined as
`color-mix(in srgb, var(--fg) N%, var(--bg))` — the obvious form, and the one
the row proposed — travels the straight segment from `--fg` to `--bg`, and
`forest`'s accent `#7cb871` lies within 22 sRGB units of that segment at every
ratio between 0 and 100%. On `forest` that made an inactive tab and the active
tab beside it one colour, at 33 opposition pairs found by that same scan.
Pivoting through `--color-muted` leaves the segment; the closest approach over
all sixteen palettes becomes 45.6, and the 33 pairs become zero.

── P1-04 ───────────────────────────────────────────────────────────────────

`#sidebar-backdrop` is created by `static/js/sidebar-layout.js` and thirteen
sites across four modules toggle `.visible` on it. Every style it owns lives
inside `@media (max-width:768px)`; a `display:none !important` at brace depth
zero out-ranked that block at every width, so the mobile drawer never dimmed
the page and the backdrop never took the tap that closes it.

The rule could not simply be deleted. Outside the mobile block the element has
no `position`, so it is not an overlay — it is a bare flex child of
`body { display: flex }`. It is now scoped to `@media (min-width: 769px)`, the
exact complement the sheet already uses in thirteen other places, so desktop
resolves to exactly what it resolved to before and mobile resolves to a
positioned overlay. Both are asserted through the cascade — matching rules
ordered by importance, specificity and source position — rather than by
grepping for a selector, because the defect was never a missing selector. It
was two selectors and the wrong one winning.

`#mobile-backdrop` is a different case and is asserted separately. It and
`#mobile-menu-btn` are markup in `static/index.html` that no script references
at all, and `#mobile-menu-btn` is a `<button>` holding a hamburger glyph, so
hiding them at every width is correct. That rule stays.
"""

import bisect
import functools
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "static" / "style.css"
THEME_JS = ROOT / "static" / "js" / "theme.js"
STATIC = ROOT / "static"

# WCAG 1.4.3 body text. `--fg-muted` is secondary text and is held to it
# anyway: `.cookbook-tab` and `.lib-tab` are navigation labels, not decoration.
FLOOR = 4.5

# Below this, "secondary" stops being a hierarchy and becomes an absence. Two
# palettes cannot reach FLOOR at all (see `_UNDER_FLOOR`); none may fall here.
HARD_FLOOR = 3.0

# Plain euclidean sRGB distance, 0..441 — the same crude measure
# `tests/test_accent_fallback_semantics_css.py` uses, and for the same reason:
# the question is never whether two colours are pleasant together, only whether
# a reader can tell them apart. 40 is that file's threshold for text and badges.
SAME_PIXEL = 40


# ── Reading the stylesheet ──────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _css() -> str:
    """The sheet with comments blanked and byte offsets preserved.

    Offsets have to survive: this file's own `:root` comment names
    `--fg-muted`, `--color-muted` and `#sidebar-backdrop` several times each,
    and a count that includes them is wrong by however much the sheet happens
    to document itself — which, in a sheet that keeps its corrections in place,
    is not a small number.
    """
    raw = STYLE.read_text(encoding="utf-8")
    out = list(raw)
    for match in re.finditer(r"/\*.*?\*/", raw, re.S):
        for i in range(match.start(), match.end()):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


@functools.lru_cache(maxsize=1)
def _line_starts() -> list:
    return [0] + [m.end() for m in re.finditer(r"\n", _css())]


def _line_of(pos: int) -> int:
    return bisect.bisect_right(_line_starts(), pos)


@functools.lru_cache(maxsize=8)
def _var_uses(token: str) -> tuple:
    """Every `var(--<token>…)` in the sheet, as (line, whole expression).

    Balanced by hand rather than by regex: after this row `--fg-muted` resolves
    to a `color-mix`, and two sites already sit *inside* a `color-mix`, so the
    expressions nest two deep and a non-greedy `\\)` returns half of one.
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
        # `--fg-muted-2` would be a different token.
        if css[start + len(needle):start + len(needle) + 1] not in (")", ",", " "):
            continue
        depth = 0
        for pos in range(css.index("(", start), len(css)):
            depth += (css[pos] == "(") - (css[pos] == ")")
            if depth == 0:
                found.append((_line_of(start), css[start:pos + 1]))
                break


def _split_top_level(text: str, sep: str) -> list:
    """Split on `sep` at paren depth zero. `color-mix()` is full of commas."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += (ch == "(") - (ch == ")")
        if ch == sep and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return out


def _fallback(expr: str) -> str:
    """The fallback half of a `var(--x, …)`, or "" when there is none."""
    parts = _split_top_level(expr[len("var("):-1], ",")
    return parts[1].strip() if len(parts) > 1 else ""


@functools.lru_cache(maxsize=1)
def _blocks() -> tuple:
    """Every innermost declaration block, in document order.

    (source index, at-rule preludes outermost-first, selector text, body).
    A brace-stack walk over the punctuation; only innermost blocks are
    recorded, so `@media` and `@keyframes` contribute their children and not
    themselves, and the at-rule stack is carried down so a rule knows which
    queries it lives under. Source order is kept because for selectors of equal
    specificity and importance it *is* the cascade.
    """
    css = _css()
    out, stack, mark = [], [], 0
    for match in re.finditer(r"[{};]", css):
        pos, ch = match.start(), match.group(0)
        if ch == "{":
            stack.append((re.sub(r"\s+", " ", css[mark:pos].strip()), pos + 1))
        elif ch == "}":
            if stack:
                prelude, body_start = stack.pop()
                body = css[body_start:pos]
                if "{" not in body and not prelude.startswith("@"):
                    media = [p for p, _ in stack if p.startswith("@")]
                    out.append((len(out), tuple(media), prelude, body, body_start))
        mark = pos + 1
    return tuple(out)


def _decls(body: str) -> list:
    """(property, value, important) for each declaration in a rule body."""
    found = []
    for chunk in _split_top_level(body, ";"):
        match = re.match(r"\s*([a-z-]+)\s*:\s*(\S.*?)\s*$", chunk, re.S)
        if match:
            value = match.group(2)
            important = bool(re.search(r"!\s*important\s*$", value))
            value = re.sub(r"\s*!\s*important\s*$", "", value)
            found.append((match.group(1), re.sub(r"\s+", " ", value), important))
    return found


@functools.lru_cache(maxsize=1)
def _rule_index() -> dict:
    """Rule bodies keyed by each selector that opens them, in document order."""
    index = {}
    for _, _, prelude, body, _ in _blocks():
        for part in prelude.split(","):
            key = re.sub(r"\s+", " ", part).strip()
            if key:
                index.setdefault(key, []).append(body)
    return index


def _decl(selector: str, prop: str) -> str:
    """What `prop` resolves to for `selector`, after source order and `!important`.

    Deliberately ignores media context: every caller below asks about a
    property no media query overrides. The cascade that *does* depend on the
    viewport is `_winning_display`, which models it properly.
    """
    bodies = _rule_index().get(selector)
    assert bodies, f"no rule in the sheet selects {selector!r}"
    value = None
    for body in bodies:
        for prop_name, prop_value, _ in _decls(body):
            if prop_name == prop:
                value = prop_value
    assert value is not None, f"{selector!r} sets no {prop!r}"
    return value


# ── Reading the palettes ────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _root_expressions() -> dict:
    """Every custom property `:root` declares, as its unresolved expression.

    Not just the hex ones: `--fg-muted` is a `color-mix` over two other
    tokens, and reading only literals would silently skip the thing this file
    exists to measure.
    """
    css = _css()
    start = css.index(":root {")
    block = css[start:css.index("}", start)]
    return {
        name: value.strip()
        for name, value in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;}]+)", block)
    }


@functools.lru_cache(maxsize=1)
def _themes() -> dict:
    """The sixteen shipped palettes, each a token name -> expression map.

    `:root`'s tokens first, then the palette's own `bg/fg/panel/border/red`
    over the top — which is exactly what the three writers do with
    `setProperty` on `documentElement`. `--fg-muted` therefore arrives from
    `:root` as an *expression* naming `--fg`, and resolves per palette, which
    is the whole claim the row makes about declaring it once.
    """
    src = THEME_JS.read_text(encoding="utf-8")
    body = src[src.index("export const THEMES = {"):]
    body = body[body.index("{"):]
    depth = 0
    for i, ch in enumerate(body):
        depth += (ch == "{") - (ch == "}")
        if depth == 0:
            body = body[:i + 1]
            break

    out = {}
    for match in re.finditer(r"(\w+)\s*:\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", body):
        fields = dict(re.findall(r"(\w+)\s*:\s*'(#[0-9a-fA-F]{3,8})'", match.group(2)))
        if not {"bg", "fg", "panel"} <= set(fields):
            continue
        resolved = dict(_root_expressions())
        resolved.update(fields)
        # `applyColors()` resolves the accent as `colors.accent || colors.red`,
        # and no shipped palette names an accent — see P1-01.
        resolved["accent"] = fields.get("accent") or resolved["red"]
        out[match.group(1)] = resolved
    assert len(out) == 16, f"expected the sixteen shipped palettes, found {sorted(out)}"
    return out


# ── Colour ─────────────────────────────────────────────────────────────────


class _PaintsNothing(AssertionError):
    """A chain that dead-ends on a token nothing defines.

    A real CSS outcome — invalid at computed-value time, the declaration is
    dropped — and the state all 93 bare uses were in before this row.
    """


def _rgb(value: str) -> tuple:
    digits = value.lstrip("#")
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


def _resolve(expr: str, theme: dict, ground=None) -> tuple:
    """Resolve the colour expressions this sheet uses, and no others.

    Narrow on purpose, in the shape `test_accent_fallback_semantics_css.py`
    established: an expression it cannot resolve fails the test rather than
    being skipped, because a silently unmeasured colour is how a token that
    resolves to nothing survives 101 uses.

    Unlike that file's resolver this one splits `color-mix()` on balanced
    parens and recurses into token *expressions*, not just token literals —
    `--fg-muted` is itself a mix, and two sites nest it inside another one.

    `ground` is what `color-mix(…, transparent)` composites onto.
    """
    expr = expr.strip()
    if expr.startswith("color-mix("):
        inner = expr[len("color-mix("):-1]
        parts = [p.strip() for p in _split_top_level(inner, ",")]
        assert len(parts) == 3 and parts[0] == "in srgb", (
            f"the colour check cannot read {expr!r} — teach `_resolve` its form"
        )
        head = re.fullmatch(r"(.+?)\s+([\d.]+)%", parts[1])
        assert head, f"expected `<color> N%` in {parts[1]!r}"
        first = _resolve(head.group(1), theme, ground)
        share = float(head.group(2)) / 100
        if parts[2] == "transparent":
            assert ground is not None, f"{expr!r} needs a ground to composite onto"
            second = ground
        else:
            second = _resolve(parts[2], theme, ground)
        return tuple(first[i] * share + second[i] * (1 - share) for i in range(3))
    if expr.startswith("var("):
        inner = expr[len("var("):-1]
        parts = _split_top_level(inner, ",")
        name = parts[0].strip().lstrip("-")
        fallback = parts[1].strip() if len(parts) > 1 else None
        if name in theme and theme[name] is not None:
            return _resolve(theme[name], theme, ground)
        if fallback is None:
            raise _PaintsNothing(
                f"--{name} resolves to nothing and has no fallback; a bare "
                f"var(--{name}) voids the whole declaration"
            )
        return _resolve(fallback, theme, ground)
    assert expr.startswith("#"), (
        f"the colour check cannot resolve {expr!r} — teach `_resolve` its form"
    )
    return _rgb(expr)


def _contrast(fore: tuple, back: tuple) -> float:
    def channel(value):
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def relative(colour):
        r, g, b = (channel(c) for c in colour)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    high, low = sorted((relative(fore), relative(back)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _distance(a: tuple, b: tuple) -> float:
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def _muted(theme: dict) -> tuple:
    """`--fg-muted` as this palette resolves it, read from the sheet."""
    return _resolve("var(--fg-muted)", theme)


# ── P1-03: the token exists, exactly once, and reaches every palette ────────


def _declarations_of(token: str) -> list:
    """(line, text) for every `--<token>: …` declaration in the sheet."""
    return [
        (_line_of(m.start(1)), m.group(0).strip())
        for m in re.finditer(r"[{;]\s*(--%s)\s*:[^;}]*" % re.escape(token), _css())
    ]


def test_fg_muted_is_declared_exactly_once_and_only_in_root():
    """One declaration, in `:root`, is the whole shape of this row.

    A second one — in `:root.light`, in a media query, or mirrored into the
    three palette writers — is `B21` repeating itself: those three have already
    drifted to 14, 13 and 17 keys, and the reason a `:root` rule is safe here
    is precisely that it is *one* place. It is also why `P1-01`'s prohibition
    does not transfer: that row had 553 sites carrying a `var(--red)` fallback
    for a `:root` rule to flip, and this one has eight fallbacks in total.
    """
    declared = _declarations_of("fg-muted")
    assert len(declared) == 1, (
        "--fg-muted must be declared exactly once; found "
        + "; ".join(f"line {line}: {text}" for line, text in declared)
    )
    # The one declaration has to be inside `:root` itself, not merely near it.
    root_start = _css().index(":root {")
    root_end = _css().index("}", root_start)
    position = _css().index("--fg-muted:", root_start)
    assert root_start < position < root_end, (
        "--fg-muted is declared outside the `:root` block, so it no longer "
        "tracks the `--fg` the three palette writers set on documentElement"
    )
    # P1-01's guard is load-bearing for this file too: a `:root { --accent }`
    # would change what several of the sibling colours below resolve to.
    assert not _declarations_of("accent"), "--accent must never be declared here"


def test_fg_muted_resolves_on_all_sixteen_palettes():
    """The point of expressing it in `--fg` is that it follows every palette.

    Resolving is not enough on its own — `#888` resolves too — so this also
    pins that the token *moves*: sixteen palettes must produce sixteen
    distinct colours, or the token has quietly become a constant.
    """
    seen = {}
    for name, theme in _themes().items():
        colour = _muted(theme)
        assert all(0 <= c <= 255 for c in colour), f"{name}: {colour}"
        seen[name] = tuple(round(c) for c in colour)
    assert len(set(seen.values())) == 16, (
        "--fg-muted resolves to the same colour on more than one palette, so "
        f"it is no longer derived from --fg: {sorted(seen.items())}"
    )
    # And it is derived from `--fg` specifically: perturbing the palette's
    # foreground has to move it.
    for name, theme in _themes().items():
        altered = dict(theme, fg="#ff00ff")
        assert _muted(altered) != _muted(theme), (
            f"--fg-muted does not track --fg on {name}"
        )


# ── P1-03: the populations, re-derived ──────────────────────────────────────


def test_the_three_populations_hold_at_their_counts():
    """93 bare, 8 with a fallback, 101 in all.

    The bare count is the row's deliverable and the fallback count is where a
    third class would hide, so both are pinned by spelling as well as by total.
    Converting one bare use into `var(--fg-muted, <something>)` is a one-token
    edit that changes what a site paints on every palette at once and shows up
    nowhere else; converting a `#888` fallback into a `var(--fg)` one changes
    which population a site belongs to without changing the total.
    """
    uses = _var_uses("fg-muted")
    assert len(uses) == 101, f"expected 101 uses of --fg-muted, found {len(uses)}"

    bare = [expr for _, expr in uses if not _fallback(expr)]
    assert len(bare) == 93, (
        f"expected 93 bare `var(--fg-muted)` uses, found {len(bare)}. If a site "
        "was legitimately added or removed, move this number and say which in "
        "the commit — do not widen the assertion."
    )

    spellings = {}
    for _, expr in uses:
        fallback = _fallback(expr)
        if fallback:
            spellings[fallback] = spellings.get(fallback, 0) + 1
    assert spellings == {"#888": 6, "var(--fg)": 2}, (
        f"the fallback population changed shape: {spellings}. Six sites reach a "
        "theme-blind grey and two reach full-strength body text; both were "
        "stand-ins for this token and both are superseded by it."
    )


def test_the_bare_uses_split_across_properties_as_measured():
    """87 `color`, 4 `border-color`, 2 `background`.

    Worth pinning separately from the total because the three do different
    things when the token is undefined and the row's framing only covers one
    of them. A dropped `color` inherits — the element still paints. A dropped
    `border-color` on `.ge-adj-hist-handle`, whose whole triangle is borders,
    paints nothing at all, and a dropped `background` on `.ge-history-row-dot`
    leaves every history dot but the current one invisible. A new bare use
    landing on `background` is a different kind of change from one landing on
    `color`, and the counts are how that stays visible.
    """
    css = _css()
    tally = {}
    for line, expr in _var_uses("fg-muted"):
        if _fallback(expr):
            continue
        offset = css.index(expr, _line_starts()[line - 1] - 1)
        boundary = max(css.rfind(";", 0, offset), css.rfind("{", 0, offset))
        match = re.match(r"\s*([a-z-]+)\s*:", css[boundary + 1:offset])
        assert match, f"line {line}: could not read the property for {expr!r}"
        tally[match.group(1)] = tally.get(match.group(1), 0) + 1
    assert tally == {"color": 87, "border-color": 4, "background": 2}, tally


def test_the_javascript_uses_are_recorded_but_not_this_rows_work():
    """Thirteen more live in inline styles under `static/js/`, ten of them bare.

    Not this row's to edit — none of those files belongs to this batch — and
    they need no edit to start working, because a `:root` declaration reaches
    an inline `style="color:var(--fg-muted)"` exactly as it reaches a
    stylesheet rule. They are pinned so the next row that touches them starts
    from a measured number rather than a grep, and so the three that carry a
    fallback (`admin.js`, `settings.js`, `emailLibrary.js`) stay visible as the
    same hand-rolled stand-ins the stylesheet had.
    """
    found = []
    for path in sorted(STATIC.rglob("*.js")) + sorted(STATIC.rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"var\(--fg-muted", text):
            depth = 0
            for pos in range(text.index("(", match.start()), len(text)):
                depth += (text[pos] == "(") - (text[pos] == ")")
                if depth == 0:
                    found.append(text[match.start():pos + 1])
                    break
    assert len(found) == 13, f"expected 13 --fg-muted uses outside the sheet, found {len(found)}"
    bare = [e for e in found if e == "var(--fg-muted)"]
    assert len(bare) == 10, f"expected 10 of them bare, found {len(bare)}"
    # Nothing under `static/js/theme.js` may declare it — that is the mirror
    # `B21` is about, and the reason this row put the token in `:root`.
    assert "--fg-muted" not in THEME_JS.read_text(encoding="utf-8"), (
        "theme.js must not carry --fg-muted; a fourth palette writer is B21"
    )


# ── P1-03: the contrast floor, and whose problem it is ─────────────────────
#
# `cute` and `retrowave` put their own `--fg` under 4.5:1 against their own
# `--panel` — 3.44 and 4.15. That is `B15`, a property of the palette, and no
# derivative of `--fg` can beat its source. What this row can do, and does, is
# keep both above the 3:1 line at which secondary text stops being secondary:
# `--fg-muted` measures 3.54 on `cute` and 3.97 on `retrowave`, so on `cute` the
# muted token is *higher* contrast than the palette's own body text. Mixing
# toward `--bg` instead would have put them at 2.36 and 2.59, and `light` — a
# shipped palette with no B15 problem at all — at 2.96.

_UNDER_FLOOR = {"cute", "retrowave"}


def test_muted_text_clears_the_floor_on_fourteen_palettes():
    """Measured against `--panel`, which is the ground almost every one of
    these 101 sites sits on: the doclib, cookbook, hwfit, image-editor,
    slash-autocomplete and research surfaces are all panels or popups.
    `--bg` is checked too, and the two never disagree by much — no palette
    separates its `--bg` from its `--panel` by more than 1.35:1.
    """
    against_panel, against_bg = {}, {}
    for name, theme in _themes().items():
        colour = _muted(theme)
        against_panel[name] = _contrast(colour, _rgb(theme["panel"]))
        against_bg[name] = _contrast(colour, _rgb(theme["bg"]))

    under = {n for n, r in against_panel.items() if r < FLOOR}
    assert under == _UNDER_FLOOR, (
        f"the set of palettes on which --fg-muted misses {FLOOR}:1 against "
        "--panel has changed.\n"
        "  now under: " + ", ".join(f"{n} ({against_panel[n]:.2f})" for n in sorted(under))
        + "\n  expected:  " + ", ".join(sorted(_UNDER_FLOOR))
        + "\nA palette joining this set means secondary text got less legible "
        "somewhere; a palette leaving it means the B15 ceiling moved."
    )
    assert len(against_panel) - len(under) == 14

    # The hard floor holds everywhere, including on the two above.
    for name, ratio in sorted(against_panel.items()):
        assert ratio >= HARD_FLOOR, (
            f"--fg-muted is {ratio:.2f}:1 against --panel on {name}, under the "
            f"{HARD_FLOOR}:1 line where muted text stops being readable at all"
        )
    for name, ratio in sorted(against_bg.items()):
        assert ratio >= HARD_FLOOR, (
            f"--fg-muted is {ratio:.2f}:1 against --bg on {name}"
        )


def test_the_two_palettes_under_the_floor_are_under_their_own_ceiling():
    """Naming `cute` and `retrowave` is only honest if the shortfall really is
    the palette's. Both put full-strength `--fg` under 4.5:1 against `--panel`,
    so the exception is a ceiling and not a value this row chose badly — and on
    `cute`, `--fg-muted` clears more contrast than `--fg` does, which is the
    strongest evidence available that the token is not the weak link.
    """
    for name in sorted(_UNDER_FLOOR):
        theme = _themes()[name]
        own = _contrast(_rgb(theme["fg"]), _rgb(theme["panel"]))
        assert own < FLOOR, (
            f"{name} now clears {FLOOR}:1 with its own --fg ({own:.2f}); it no "
            "longer belongs in the B15 exception and --fg-muted should be "
            "measured against the floor there like everywhere else"
        )
    cute = _themes()["cute"]
    assert _contrast(_muted(cute), _rgb(cute["panel"])) > _contrast(
        _rgb(cute["fg"]), _rgb(cute["panel"])
    ), "on cute, --fg-muted should out-contrast the palette's own body text"


def test_the_population_compounding_with_opacity_cannot_grow():
    """35 of the 101 uses — 33 rules, since the stalled pill spends three on
    one rule — sit somewhere that also sets `opacity`.

    Those were the sheet muting by hand where the token could not, and the
    reductions multiply: `.cookbook-task-session` is `opacity: 0.35` on top of
    a token that is already 45% of `--fg`. Nothing in this row can fix them —
    removing an `opacity` changes icon buttons and hover reveals, not just
    text — but a *new* one is a new instance of a known defect, so the number
    is pinned and the worst case is named. Thirteen sit at 0.45 or below and
    three at 0, all of them controls a parent hover reveals.
    """
    compounding = []
    for _, media, prelude, body, body_start in _blocks():
        if "--fg-muted" not in body:
            continue
        opacity = [v for p, v, _ in _decls(body) if p == "opacity"]
        if opacity:
            compounding.append((_line_of(body_start), prelude, opacity[-1]))
    assert len(compounding) == 33, (
        f"expected 33 rules that both name --fg-muted and set an opacity, "
        f"found {len(compounding)}: {sorted(c[1] for c in compounding)}"
    )
    faint = [c for c in compounding if float(c[2]) <= 0.45]
    assert len(faint) == 13, f"expected 13 at 0.45 or below, found {len(faint)}"


# ── P1-03: what the value had to avoid ─────────────────────────────────────


def test_the_muted_token_is_not_any_palettes_accent():
    """This is the assertion the value was chosen to satisfy.

    `color-mix(in srgb, var(--fg) N%, var(--bg))` — the obvious form — walks
    the segment from `--fg` to `--bg`, and `forest`'s accent `#7cb871` sits
    within 22 sRGB units of that segment at every N. Since the sheet paints
    "inactive" in `--fg-muted` and "active" in `--accent` at more than thirty
    places — three tab strips, the image-editor history dots, the research
    category chips, every icon button that hovers to the accent — a token on
    that segment made active and inactive one colour on a shipped palette.
    Mixing through `--color-muted` leaves the segment. The margin below is the
    evidence that it stays off it.
    """
    close = {}
    for name, theme in _themes().items():
        gap = _distance(_muted(theme), _rgb(theme["accent"]))
        if gap < SAME_PIXEL:
            close[name] = gap
    assert not close, (
        "--fg-muted is within %d sRGB units of the palette's own accent on %s. "
        "Secondary text and the accent-coloured active state next to it are "
        "the same colour there." % (
            SAME_PIXEL,
            ", ".join(f"{n} ({g:.1f})" for n, g in sorted(close.items())),
        )
    )


# `terminal` is `#00ff41` on black, so every colour it derives from `--fg` is a
# green and `--color-success` (`#4caf50`) is a green too. `--fg-muted` lands
# 28.1 units from it there and nowhere near it on the other fifteen. Two sites
# put the two beside each other — `.research-job-action` next to its
# `.research-job-action-copied` confirmation, and `.research-cat` next to the
# `.research-cat-badge.research-cat-standard` badge — and the first of those
# also swaps the button's `innerHTML` (`static/js/research/panel.js:1212`), so
# colour is a second signal there rather than the only one. Not closable from
# this file: it would need a success colour that knows what the foreground is,
# which is the same shape of problem as `P1-08`'s `--on-accent`. Pinned so the
# palette set cannot grow and so a *new* site pairing the two is visible.
_SUCCESS_COLLISION = {"terminal"}


def test_the_muted_token_meets_the_semantic_colours_on_one_palette_only():
    tokens = ("color-error", "color-warning", "color-danger", "color-accent",
              "green", "warn")
    for token in tokens:
        for name, theme in _themes().items():
            gap = _distance(_muted(theme), _resolve(f"var(--{token})", theme))
            assert gap >= SAME_PIXEL, (
                f"on {name}, --fg-muted is {gap:.1f} from --{token}; muted text "
                "and a status colour are the same colour there"
            )
    close = {
        name for name, theme in _themes().items()
        if _distance(_muted(theme), _resolve("var(--color-success)", theme)) < SAME_PIXEL
    }
    assert close == _SUCCESS_COLLISION, (
        "the set of palettes where --fg-muted meets --color-success has "
        f"changed: now {sorted(close)}, expected {sorted(_SUCCESS_COLLISION)}"
    )


def test_muted_is_visibly_muted_and_visibly_not_the_border():
    """Two affordances depend on the token differing from something else.

    `.cookbook-tab`, `.lib-tab` and `.admin-tab` hover from `--fg-muted` to
    `var(--fg)`; if the two are the same colour the hover is invisible, which
    is exactly the state the sheet was in when the token was undefined and the
    base rule fell through to inherited `--fg`. Four rules hover a border from
    `var(--border)` to `--fg-muted` and need the same separation.
    """
    for name, theme in _themes().items():
        from_fg = _distance(_muted(theme), _rgb(theme["fg"]))
        assert from_fg >= SAME_PIXEL, (
            f"on {name}, --fg-muted is {from_fg:.1f} from --fg, so a tab that "
            "hovers to var(--fg) does not visibly change"
        )
        from_border = _distance(_muted(theme), _rgb(theme["border"]))
        assert from_border >= SAME_PIXEL, (
            f"on {name}, --fg-muted is {from_border:.1f} from --border, so a "
            "hover that repaints a border in it does not visibly change"
        )


def test_the_tab_strips_can_finally_show_which_tab_is_active():
    """Three strips, one shape: base `--fg-muted`, hover `--fg`, active accent.

    Two palettes make `--fg` and `--red` the *same colour* — `retrowave` sets
    both to `#e94560`, `terminal` both to `#00ff41` — so before this row the
    inactive tab, the hovered tab and the active tab were one colour there, on
    every strip. That is not a subtle regression; it is a navigation control
    with no state. It is asserted per palette because it is the clearest thing
    the row actually delivers.
    """
    for base_selector, active_selector in (
        (".cookbook-tab", ".cookbook-tab.active"),
        (".lib-tab", ".lib-tab.active"),
        (".admin-tab", ".admin-tab.active"),
    ):
        base = _decl(base_selector, "color")
        active = _decl(active_selector, "color")
        assert "--fg-muted" in base, f"{base_selector} should be muted; got {base!r}"
        for name, theme in _themes().items():
            ground = _rgb(theme["panel"])
            gap = _distance(_resolve(base, theme, ground), _resolve(active, theme, ground))
            assert gap >= SAME_PIXEL, (
                f"on {name}, {base_selector} and {active_selector} are {gap:.1f} "
                "apart — the active tab is not distinguishable"
            )


def test_a_stalled_download_is_not_the_colour_of_a_running_one():
    """The one site that looked like `P1-01`'s third class, measured.

    `.cookbook-serve-downloading-pill.is-stalled` spelled its fallback `#888`
    and reads "stalled, not progressing" beside `.cookbook-serve-downloading-
    pill`, which paints the accent. On `gpt`, whose `--red` is `#949494`, that
    hand-picked grey was 20.8 units from the accent — the two pills were
    already the same colour there. The token is not flattening a distinction
    here; it is restoring one, so the assertion is that the distinction now
    holds on all sixteen rather than that the fallback was preserved.
    """
    stalled = _decl(".cookbook-serve-downloading-pill.is-stalled", "color")
    running = _decl(".cookbook-serve-downloading-pill", "color")
    assert "--fg-muted" in stalled, f"got {stalled!r}"
    for name, theme in _themes().items():
        ground = _rgb(theme["panel"])
        gap = _distance(_resolve(stalled, theme, ground), _resolve(running, theme, ground))
        assert gap >= SAME_PIXEL, (
            f"on {name}, a stalled download and a running one are {gap:.1f} apart"
        )
    # And the grey it replaced really was the collision, not the protection.
    gpt = _themes()["gpt"]
    assert _distance(_rgb("#888888"), _rgb(gpt["accent"])) < SAME_PIXEL


def test_no_use_of_the_token_paints_nothing_on_any_palette():
    """Every one of the 101 expressions has to resolve on all sixteen.

    Before this row, 93 of them resolved to nothing on all sixteen and no test,
    console warning or visual cue said so. Resolving them here is the direct
    inverse of that: `_resolve` raises `_PaintsNothing` on a dead chain rather
    than returning a colour, so a token quietly renamed out from under these
    sites fails instead of silently blanking them again.
    """
    for name, theme in _themes().items():
        ground = _rgb(theme["panel"])
        for line, expr in _var_uses("fg-muted"):
            try:
                _resolve(expr, theme, ground)
            except _PaintsNothing as exc:
                raise AssertionError(f"line {line} on {name}: {expr} -> {exc}")


# ── P1-04: the cascade the backdrop actually resolves through ──────────────


def _specificity(selector: str) -> tuple:
    """(#ids, #classes/attrs/pseudo-classes, #elements) — enough for these rules."""
    body = re.sub(r"::[a-z-]+", " ", selector)
    ids = len(re.findall(r"#[A-Za-z0-9_-]+", body))
    classes = len(re.findall(r"\.[A-Za-z0-9_-]+|\[[^\]]*\]|:[a-z-]+(?:\([^)]*\))?", body))
    elements = len(re.findall(r"(?:^|[\s>+~])([a-z][a-z0-9-]*)", body))
    return (ids, classes, elements)


def _media_matches(prelude: str, width: int, media_type: str = "screen") -> bool:
    """Evaluate the at-rule forms this sheet uses on the backdrop, and no others.

    Narrow like `_resolve`: an unrecognised query raises instead of quietly
    reporting False, because a query that silently never matches is how a rule
    disappears from a cascade model without disappearing from the sheet.
    """
    if not prelude.startswith("@media"):
        raise AssertionError(f"not a media query: {prelude!r}")
    for branch in prelude[len("@media"):].split(","):
        branch = branch.strip()
        ok = True
        remainder = branch
        type_match = re.match(r"(?:only\s+)?(screen|print|all)\b", branch)
        if type_match:
            ok = type_match.group(1) in (media_type, "all")
            remainder = branch[type_match.end():].lstrip()
            remainder = re.sub(r"^and\s+", "", remainder)
        for feature in re.findall(r"\(([^)]*)\)", remainder):
            name, _, value = (p.strip() for p in feature.partition(":"))
            if name == "max-width":
                ok = ok and width <= float(value.rstrip("px"))
            elif name == "min-width":
                ok = ok and width >= float(value.rstrip("px"))
            elif name in ("hover", "pointer", "prefers-reduced-motion",
                          "prefers-color-scheme", "display-mode", "orientation"):
                ok = False  # not modelled; treated as not matching a plain screen
            else:
                raise AssertionError(
                    f"the cascade model cannot evaluate `({feature})` — teach "
                    "`_media_matches` its form rather than letting it vanish"
                )
        if ok:
            return True
    return False


def _cascade(element_id: str, classes: frozenset, prop: str, width: int,
             media_type: str = "screen"):
    """What `prop` wins for `#<id>` with `classes`, at this viewport.

    Returns (value, line, selector) or None. Ordered the way CSS orders it:
    importance first, then specificity, then source position.
    """
    winners = []
    for order, media, prelude, body, body_start in _blocks():
        for part in prelude.split(","):
            part = part.strip()
            if f"#{element_id}" not in part:
                continue
            # Queries are evaluated only for rules that could match this
            # element: `_media_matches` deliberately refuses forms it does not
            # model, and the sheet is full of `@supports` and container-ish
            # queries that have nothing to do with these two elements.
            if not all(_media_matches(query, width, media_type) for query in media):
                continue
            # Only the simple `#id` / `#id.class` forms appear for these two
            # elements; anything with a combinator would need a real matcher.
            simple = part.replace(f"#{element_id}", "", 1)
            wanted = set(re.findall(r"\.([A-Za-z0-9_-]+)", simple))
            if re.sub(r"\.[A-Za-z0-9_-]+", "", simple).strip():
                continue  # combinator or extra compound — not this element
            if not wanted <= set(classes):
                continue
            for name, value, important in _decls(body):
                if name == prop:
                    winners.append(
                        (important, _specificity(part), order,
                         value, _line_of(body_start), part)
                    )
    if not winners:
        return None
    best = max(winners)
    return best[3], best[4], best[5]


MOBILE_WIDTHS = (375, 640, 768)
DESKTOP_WIDTHS = (769, 1024, 1440)


def test_the_sidebar_backdrop_can_show_at_every_mobile_width():
    """`display` must not resolve to `none` where the drawer lives, and the
    element must actually be an overlay there — position, stacking, a dimming
    background — because "not hidden" is not the same as "visible".

    Both narrow breakpoints are checked, not just 768: the drawer's own query
    is `max-width:768px` and the sheet has four `max-width:640px` blocks, and a
    backdrop that dimmed at 768 but not at 640 would be a distinction on the
    form factor with the least room to guess.
    """
    for width in MOBILE_WIDTHS:
        display = _cascade("sidebar-backdrop", frozenset(), "display", width)
        assert display is None or display[0] != "none", (
            f"at {width}px the backdrop still resolves to `display:{display[0]}` "
            f"from line {display[1]} ({display[2]}) — the drawer cannot dim"
        )
        for prop, expected in (("position", "fixed"), ("inset", "0")):
            got = _cascade("sidebar-backdrop", frozenset(), prop, width)
            assert got and got[0] == expected, (
                f"at {width}px the backdrop has no {prop}:{expected} ({got})"
            )
        background = _cascade("sidebar-backdrop", frozenset(), "background", width)
        assert background and background[0] != "none" and "0)" not in background[0], (
            f"at {width}px the backdrop paints nothing to dim with: {background}"
        )
        # Tap-to-close needs the element to receive the tap once it is shown.
        visible = frozenset({"visible"})
        events = _cascade("sidebar-backdrop", visible, "pointer-events", width)
        assert events and events[0] == "auto", (
            f"at {width}px a visible backdrop does not take pointer events: {events}"
        )
        opacity = _cascade("sidebar-backdrop", visible, "opacity", width)
        assert opacity and float(opacity[0]) > 0, (
            f"at {width}px a visible backdrop is still transparent: {opacity}"
        )


def test_the_sidebar_backdrop_cannot_show_at_any_desktop_width():
    """Desktop has to resolve exactly as it did before the row.

    The element is created unconditionally and appended to `body`, and `body`
    is a flex container, so without a `display:none` it is not "invisible" — it
    is a zero-width flex child in the layout. That is why the rule could not
    simply be deleted, and the `body` assertion below is here so the reason
    stays pinned to the fix rather than living only in a commit message.
    """
    for width in DESKTOP_WIDTHS:
        display = _cascade("sidebar-backdrop", frozenset(), "display", width)
        assert display and display[0] == "none", (
            f"at {width}px the backdrop is not hidden ({display}); it becomes a "
            "flex child of body rather than nothing"
        )
        # Even with `.visible` on it — thirteen call sites toggle that class,
        # and not all of them check the viewport first.
        with_class = _cascade("sidebar-backdrop", frozenset({"visible"}), "display", width)
        assert with_class and with_class[0] == "none", (
            f"at {width}px a `.visible` backdrop is not hidden ({with_class})"
        )
    assert _decl("body", "display") == "flex", (
        "body is no longer a flex container; re-check whether the desktop "
        "`display:none` on #sidebar-backdrop is still doing anything"
    )


def test_the_hide_rule_no_longer_sits_outside_every_query():
    """The defect stated structurally, so it cannot come back in another form.

    A `#sidebar-backdrop` rule at brace depth zero out-ranks the mobile block
    whatever it says, because the mobile block is earlier in the sheet and no
    more specific. Any declaration for this element must therefore live under
    a query — and the guard is on all of them, not just on `display`, because
    the next unconditional rule will not necessarily be a `display` one.
    """
    unscoped = []
    for _, media, prelude, body, body_start in _blocks():
        if any(f"#sidebar-backdrop" in p for p in prelude.split(",")) and not media:
            unscoped.append((_line_of(body_start), prelude, body.strip()[:60]))
    assert not unscoped, (
        "a #sidebar-backdrop rule sits outside every media query: "
        + "; ".join(f"line {l}: {p} {{ {b} }}" for l, p, b in unscoped)
    )
    # And the block that replaced it is the exact complement of the drawer's.
    assert "@media (min-width: 769px)" in _css()
    assert "@media (max-width:768px)" in _css()


def test_mobile_backdrop_is_dead_markup_and_stays_hidden_everywhere():
    """The rule immediately above the one this row fixed is *not* the same bug.

    `#mobile-backdrop` and `#mobile-menu-btn` are in `static/index.html` and no
    script anywhere queries, binds or toggles them — they are the previous
    mobile implementation, superseded by the JS-created `#sidebar-backdrop` and
    by `#hamburger-btn`. `#mobile-menu-btn` is a `<button>` holding a hamburger
    glyph, so unhiding it puts a second, dead hamburger on the page at every
    width. It is hidden unconditionally on purpose, and this test is what tells
    a future reader that the adjacency was a coincidence rather than a pattern.
    """
    for width in MOBILE_WIDTHS + DESKTOP_WIDTHS:
        for element in ("mobile-backdrop", "mobile-menu-btn"):
            display = _cascade(element, frozenset(), "display", width)
            assert display and display[0] == "none", (
                f"#{element} is not hidden at {width}px ({display}), but nothing "
                "in the application drives it"
            )
    referenced = []
    for path in sorted(STATIC.rglob("*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for element in ("mobile-backdrop", "mobile-menu-btn"):
            if element in text:
                referenced.append(f"{path.name}:{element}")
    assert not referenced, (
        "a script now references " + ", ".join(referenced) + " — if this markup "
        "is live again, the unconditional `display:none` above #sidebar-backdrop "
        "needs the same treatment #sidebar-backdrop got"
    )
    assert '<div id="mobile-backdrop">' in (STATIC / "index.html").read_text(
        encoding="utf-8"
    ), "the dead markup was removed; this rule can go with it"
