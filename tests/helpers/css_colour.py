# SPDX-License-Identifier: AGPL-3.0-or-later
"""One colour resolver for the suite's measurements of `static/style.css`.

`B396`. Three test files each carried their own `_rgb`, `_resolve`,
`_contrast`, `_distance` and `_themes` — `test_fg_muted_and_backdrop_cascade_css.py`,
`test_accent_fallback_semantics_css.py` and `test_tool_effect_surfaces_js.py` —
and `B22` had to teach two of them `light-dark()` separately. The narrower two
split `color-mix()` with a regex, and the narrowest read only hex literals
and could not see `:root` at all, so a token it could not read fell through to
its `var(--x, <fallback>)` branch and the test measured the fallback on every
palette (`test_the_supervisor_ladder_still_separates_recovering_from_stop`
reporting a collision on two palettes whose values had not moved). This is the
widest of the three, moved here unchanged; the files import it (`Law 14`).

It stays deliberately narrow about what it accepts: an expression it cannot
resolve fails the caller rather than being skipped, because a silently
unmeasured colour is how a token that paints nothing survives. Teach it the
new form here, once.
"""
import re
from pathlib import Path
from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parents[2]
THEME_JS = ROOT / "static" / "js" / "theme.js"

#: How many palettes `theme.js` ships. A count here rather than in each
#: caller, so a new palette is one edit. Twenty since the cockpit retired
#: `terminal`, `retrowave` and `cyberpunk` (theme.js `RETIRED_THEMES`).
SHIPPED_PALETTES = 20


class PaintsNothing(AssertionError):
    """A chain that dead-ends on a token nothing defines.

    A real CSS outcome — invalid at computed-value time, the declaration is
    dropped — rather than a gap in the resolver, so a caller counting what a
    site paints can catch it. Everywhere else it is still an `AssertionError`.
    """


def split_top_level(text: str, sep: str) -> list:
    """Split on `sep` at paren depth zero. `color-mix()` is full of commas."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += (ch == "(") - (ch == ")")
        if ch == sep and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return out


def rgb(value: str) -> tuple:
    digits = value.lstrip("#")
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


def resolve(expr: str, theme: dict, ground=None) -> tuple:
    """Resolve the colour expressions this sheet uses, and no others.

    Splits `color-mix()` on balanced parens and recurses into token
    *expressions*, not just token literals — `--fg-muted` is itself a mix, and
    two sites nest it inside another one.

    `ground` is what `color-mix(…, transparent)` composites onto — a dot tinted
    to 60% is not a colour until you know what is behind it.
    """
    expr = expr.strip()
    if expr.startswith("light-dark("):
        # `B22`. The sheet's per-surface semantic tokens. Which arm applies is
        # decided by `color-scheme`, which all three palette writers set from
        # the background's WCAG luminance (`P3-09`) — so the palette carries the
        # answer and this does not re-derive it. A theme dict that does not say
        # fails here rather than silently picking one.
        arms = [a.strip() for a in split_top_level(expr[len("light-dark("):-1], ",")]
        assert len(arms) == 2, f"expected two arms in {expr!r}"
        scheme = theme.get("color-scheme")
        assert scheme in ("light", "dark"), (
            f"{expr!r} needs the palette's `color-scheme`; this one says {scheme!r}"
        )
        return resolve(arms[0] if scheme == "light" else arms[1], theme, ground)
    if expr.startswith("color-mix("):
        inner = expr[len("color-mix("):-1]
        parts = [p.strip() for p in split_top_level(inner, ",")]
        # `B1577`. `in oklab` too: `B1408`'s de-emphasis ladder,
        # `color-mix(in oklab, var(--fg) N%, var(--fg-muted))`, interpolated
        # where the browser interpolates it. Opaque operands only, as the
        # ladder's are; a mix toward `transparent` stays an sRGB composite.
        assert len(parts) == 3 and parts[0] in ("in srgb", "in oklab"), (
            f"the colour check cannot read {expr!r} — teach `resolve` its form"
        )
        head = re.fullmatch(r"(.+?)\s+([\d.]+)%", parts[1])
        assert head, f"expected `<color> N%` in {parts[1]!r}"
        first = resolve(head.group(1), theme, ground)
        share = float(head.group(2)) / 100
        if parts[2] == "transparent":
            assert parts[0] == "in srgb", f"{expr!r}: an OKLab mix toward transparent is not read here"
            assert ground is not None, f"{expr!r} needs a ground to composite onto"
            second = ground
        else:
            second = resolve(parts[2], theme, ground)
        if parts[0] == "in oklab":
            a, b = oklab(first), oklab(second)
            return from_oklab(tuple(a[i] * share + b[i] * (1 - share) for i in range(3)))
        return tuple(first[i] * share + second[i] * (1 - share) for i in range(3))
    if expr.startswith("var("):
        inner = expr[len("var("):-1]
        parts = split_top_level(inner, ",")
        name = parts[0].strip().lstrip("-")
        fallback = parts[1].strip() if len(parts) > 1 else None
        if name in theme and theme[name] is not None:
            return resolve(theme[name], theme, ground)
        if fallback is None:
            raise PaintsNothing(
                f"--{name} resolves to nothing and has no fallback; a bare "
                f"var(--{name}) voids the whole declaration"
            )
        return resolve(fallback, theme, ground)
    assert expr.startswith("#"), (
        f"the colour check cannot resolve {expr!r} — teach `resolve` its form"
    )
    return rgb(expr)


def oklab(colour: tuple) -> tuple:
    """sRGB 0..255 to OKLab (Björn Ottosson's matrices, as CSS Color 4 uses)."""
    def linear(value):
        value /= 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in colour)
    lms = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b,
           0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
           0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    l_, m_, s_ = (x ** (1 / 3) for x in lms)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def from_oklab(lab: tuple) -> tuple:
    """OKLab back to sRGB 0..255, clipped into gamut."""
    big_l, a, b = lab
    l_ = (big_l + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (big_l - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (big_l - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb_linear = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
                  -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
                  -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)

    def encode(value):
        value = max(0.0, min(1.0, value))
        return 255.0 * (12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055)

    return tuple(encode(v) for v in rgb_linear)


def relative_luminance(colour: tuple) -> float:
    def channel(value):
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fore: tuple, back: tuple) -> float:
    high, low = sorted((relative_luminance(fore), relative_luminance(back)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def distance(a: tuple, b: tuple) -> float:
    """Plain euclidean sRGB distance, 0..441.

    Crude on purpose: it is asked only whether two colours are the same
    pixel, not whether they are pleasant together.
    """
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def root_expressions(css: str) -> dict:
    """Every custom property `:root` declares, as its unresolved expression.

    Not just the hex ones: `--fg-muted` is a `color-mix` over two other
    tokens, and reading only literals silently skips the thing being measured.
    """
    start = css.index(":root {")
    block = css[start:css.index("}", start)]
    return {
        name: value.strip()
        for name, value in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;}]+)", block)
    }


def palettes(root_tokens: dict) -> dict:
    """The shipped palettes, each a token name -> expression map.

    `root_tokens` first, then the palette's own `bg/fg/panel/border/red` over
    the top — which is exactly what the three writers do with `setProperty` on
    `documentElement`. `--accent` is `colors.accent || colors.red`, as
    `applyColors()` resolves it, and `color-scheme` is the arm `light-dark()`
    takes, by `theme.js`'s own `_isLightBackground` rule (`P3-09`).
    """
    src = THEME_JS.read_text(encoding="utf-8")
    # The object literal, cut by the shared reader (`B876`: strings, comments
    # and regexes skipped) rather than a hand-rolled brace counter.
    at = src.index("export const THEMES = {")
    body = js_definition(src, src.index("{", at))

    out = {}
    for match in re.finditer(r"(\w+)\s*:\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", body):
        fields = dict(re.findall(r"(\w+)\s*:\s*'(#[0-9a-fA-F]{3,8})'", match.group(2)))
        if not {"bg", "fg", "panel"} <= set(fields):
            continue
        resolved = dict(root_tokens)
        # theme.js only writes `--red` when the palette names one; an unnamed
        # one keeps `:root`'s.
        resolved.update(fields)
        resolved["accent"] = fields.get("accent") or resolved["red"]
        resolved["color-scheme"] = (
            "light" if relative_luminance(rgb(resolved["bg"])) > 0.5 else "dark"
        )
        out[match.group(1)] = resolved
    assert len(out) == SHIPPED_PALETTES, (
        f"expected the {SHIPPED_PALETTES} shipped palettes, found {sorted(out)}")
    return out
