# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B15` (carrying `B16`), `B22` (carrying `B23`) — what the sixteen palettes
actually resolve to, measured against the shipped stylesheet.

Four rows the owner parked on 2026-09-14 under `D-2026-09-14-03` — *"We don't
have to touch themes unless its absolutely critical. They're all customizable
(look at how themes work as a whole)."* — and then unparked. This file is the
"look at how themes work as a whole" part, made executable.

── How themes work as a whole, since every claim below rests on it ──────────

A theme in this product is FIVE hex values: `bg`, `fg`, `panel`, `border`,
`red`. `static/js/theme.js` ships sixteen of them in `THEMES`, a person can
edit any of them in the theme editor, save up to eight of their own, export and
import them as JSON, generate one from an accent with `generateHarmonyColors()`
and create one from an agent tool. There is no seventeenth mechanism.

`applyColors()` turns those five into THIRTY inline custom properties on
`documentElement` — the five, `--accent` (the theme's own `red` unless the
palette names one), ten `--hl-*` DERIVED from the five by `deriveSyntaxColors`,
and fourteen `ADV_KEYS` the editor exposes — plus `color-scheme`, derived from
the background's WCAG luminance (`P3-09`). Two more writers do the same thing
for the same reason: `static/index.html`'s first-paint script, because the
module has not booted when the shell paints, and `static/login.html`, because
`initThemeUI()` returns at a `#themeGrid` that page does not have.

Everything else is `static/style.css`. There is **no theme-name selector and no
theme class** — `:root.light` exists in the sheet and nothing has ever added
that class (`tests/test_root_class_wiring.py`). So the only two things the
stylesheet can scope on are the five values themselves and `color-scheme`. That
is the whole mechanism, and it is why `B22`'s fix is `light-dark()` and could
not have been a theme-name rule.

`--accent` is never defined in `:root`. That is absolute (`P1-01`,
`D-2026-08-26-03`) and `test_accent_fallback_semantics_css.py` holds it.

── What this file measures, and how ────────────────────────────────────────

The palettes are not transcribed. Each of the sixteen is pushed through the
REAL `applyColors()` in node and the thirty properties it sets are read back,
so `--hl-function` here is the value `deriveSyntaxColors` computes for that
palette rather than `:root`'s `dark` literal — which is the difference between
measuring the product and measuring a constant. The `:root` declarations are
read from the shipped sheet and resolved against that, `light-dark()` included,
keyed off the `color-scheme` the palette writer itself set.

── `B15`: two palettes put every string under AA, and they are not repainted ─

`cute` renders `--fg` on `--panel` at **3.44:1** and `retrowave` at **4.15:1**,
against 4.5:1 for body text. Every other palette clears it with room; the next
lowest is `light` at 7.13 and the default `dark` is 12.72. Re-measured
2026-09-16 and every figure holds to two decimal places for the third time.

**The defect is real and it is not fixed here, and that is a decision rather
than an omission.** `cute` is `#d4608a` on `#fff8fa` — pink text on pink-white.
No fix exists that does not move one of those two hexes, and moving one of them
is not fixing a defect in how a theme's choices are applied, it is substituting
different choices. The arithmetic says so: `retrowave` clears AA at a panel
lightness change of −3.5, but `cute` needs −84.5, at which point it is not
`cute`. So the candidate repaints are filed as `B390` with the exact hexes and
the exact resulting ratios, for the owner, and this file holds the other branch
of the row's own `Verify`: *"the sixteen palettes are measured in a test, and
either every one clears 4.5:1 or the exceptions are named on purpose."*

Named on purpose, with the purpose written down: they are two of sixteen, both
opt-in by name, neither is the default, and every one of them is editable in
thirty seconds by the person using it.

── `B16`: the row's headline is false and is recorded as false ─────────────

`B16` says the accent falls below the 3:1 graphic floor on THREE light themes
and then quotes `light` at **3.03**, which is above 3.0. Against `--panel`
exactly two fail — `paper` 2.24 and `cute` 2.56. The third is true only against
`--bg`, where `light` is 2.75. The row conflated two surfaces, and the fix for
a false headline is a test that measures both surfaces separately.

── `B22`: the semantic tokens were not theme-scoped ────────────────────────

Nineteen `:root` literals, 375 `var()` uses, 177 of them `color:`. `theme.js`
never touched any of them, so a *success* green was one hex on `terminal` and
on `paper`, where it measures **1.37:1**. And a third of it ran backwards:
`--color-muted-alt` was light-tuned and failed on 13 of the 16 palettes,
`--color-danger` on 12.

Fifteen of them now name a value per surface through `light-dark()`, and the
arm for the surface each literal was already tuned for **is that literal**, so
the twelve dark palettes resolve every one of them to exactly the hex they
resolved to before. That is asserted below, and it is what makes this scoping
rather than recolouring. Four are deliberately not scoped and each is a
measurement, written where they are declared.

── `B23`: seven link idioms, and the one that wins is not a taste call ─────

The row said two, the 2026-09-14 re-measure said five, and every rule in this
sheet that sets a colour on an `a` says seven. `--hl-function` is the only one
that clears 4.5:1 against `--panel` on all sixteen palettes, the only one
derived per theme, the hue on the two highest-traffic link surfaces in the
product, and the one that was already `!important`-ed over the accent at
`:31393`. It is now `--link-fg`, named once.

Against `--bg` it lands 4.19 on `light`, 4.36 on `lavender` and 4.38 on `cute`
— just under AA, against 2.1 to 2.8 for every alternative. That residual is
named in the test rather than rounded away, and it is `B395`.

The hover was the unnamed defect underneath: `details a:hover` went to
`--color-link-hover`, which on the four light palettes DROPPED the link's
contrast — 3.03 to 1.74 on `light`. So hovering made the link harder to see.
`--color-link-hover` is scoped by `B22` and the invariant is asserted directly:
a hover may not be lower-contrast than the base it replaces, on any palette.

── `Law 9` ─────────────────────────────────────────────────────────────────

Every assertion here is about a VALUE the shipped CSS resolves to, not about a
string it contains, so it protects a seventeenth palette and a re-tuned token
as well as today's. On the tree as it stood before this commit,
`test_every_semantic_token_clears_its_floor_or_is_a_named_exception` fails on
fourteen tokens across four palettes, `test_there_is_one_link_colour` fails
with six idioms, and `test_a_link_hover_never_loses_contrast` fails on four
palettes. That was checked by running this file against the tree at `b0ec056`,
not assumed.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

# One resolver, one contrast function, one sandbox builder. `Law 14` — these
# exist and are the same machines this measurement needs.
from test_tool_effect_surfaces_js import _DOM, _make_sandbox  # noqa: E402
from test_accent_token_js import _THEME_STUBS, THEME_NAMES  # noqa: E402
from test_fg_muted_and_backdrop_cascade_css import (  # noqa: E402
    _contrast,
    _css,
    _distance,
    _relative_luminance,
    _resolve,
    _rgb,
    _root_expressions,
)

ROOT = Path(__file__).resolve().parents[1]
THEME_JS = ROOT / "static" / "js" / "theme.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

BODY_FLOOR = 4.5      # WCAG AA, body text
GRAPHIC_FLOOR = 3.0   # WCAG AA, large text / UI components and graphics


# ── The palettes, as the product actually resolves them ─────────────────────

_SHIM = """
import { installDom, Node } from './dom.js';
export const document = installDom();
document.documentElement = new Node('html');
document.readyState = 'loading';
globalThis.location = { pathname: '/', origin: 'http://test.local' };
globalThis.window.location = globalThis.location;
globalThis.window.matchMedia = () => ({ matches: false });
const root = document.documentElement;

// Every property `applyColors()` set, custom or not — `color-scheme` is not a
// custom property and it is the one `light-dark()` keys off, so a reader that
// filtered on `--` would measure the wrong arm and never know.
export function painted() {
  const out = {};
  for (const k of Object.keys(root.style)) out[k] = String(root.style[k]);
  return out;
}
"""


@pytest.fixture(scope="module")
def palettes(tmp_path_factory) -> dict:
    """The sixteen palettes as `applyColors()` leaves them on `documentElement`.

    Driven rather than transcribed (`Law 20`). `deriveSyntaxColors()` is module
    private and computes ten of the thirty properties from the palette's own
    five; a Python re-implementation of it would be a second copy of the thing
    under test, and the ten include `--hl-function`, which `B23` turns on.
    """
    sandbox = _make_sandbox(
        tmp_path_factory.mktemp("contrast"), THEME_JS, _SHIM, _THEME_STUBS
    )
    entry = sandbox / "case.mjs"
    entry.write_text(textwrap.dedent("""
        import { painted } from './shim.js';
        const tm = await import('./theme.js');
        const out = {};
        for (const name of Object.keys(tm.THEMES)) {
          tm.applyColors(tm.THEMES[name]);
          out[name] = painted();
        }
        console.log(JSON.stringify(out));
    """))
    proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    painted = json.loads([l for l in proc.stdout.splitlines() if l.strip()][-1])

    assert sorted(painted) == sorted(THEME_NAMES), sorted(painted)
    assert len(painted) == 16, sorted(painted)

    out = {}
    for name, props in painted.items():
        theme = dict(_root_expressions())
        for key, value in props.items():
            theme[key[2:] if key.startswith("--") else key] = value
        # The palette writer is the authority on both of these.
        assert theme.get("color-scheme") in ("light", "dark"), name
        assert theme.get("accent"), name
        out[name] = theme
    return out


def _light(palettes: dict) -> list:
    return sorted(n for n, t in palettes.items() if t["color-scheme"] == "light")


def _surfaces(theme: dict) -> dict:
    return {"panel": _resolve("var(--panel)", theme),
            "bg": _resolve("var(--bg)", theme)}


def _worst(expr: str, theme: dict) -> float:
    return min(_contrast(_resolve(expr, theme), s)
               for s in _surfaces(theme).values())


# ── `B15` ───────────────────────────────────────────────────────────────────

# Named on purpose, per the row's own `Verify` and `D-2026-09-14-03`. Values
# pinned so neither can get quietly worse and a THIRD palette cannot join them.
_B15_UNDER_AA = {"cute": (3.44, 3.26), "retrowave": (4.15, 4.46)}


def test_body_text_clears_aa_on_every_palette_but_the_two_named_ones(palettes):
    """`B15`'s `Verify`, measured over all sixteen against both surfaces."""
    measured = {
        name: (_contrast(_resolve("var(--fg)", theme), _resolve("var(--panel)", theme)),
               _contrast(_resolve("var(--fg)", theme), _resolve("var(--bg)", theme)))
        for name, theme in palettes.items()
    }
    under = {n for n, (p, b) in measured.items() if min(p, b) < BODY_FLOOR}
    assert under == set(_B15_UNDER_AA), (
        "the set of palettes whose own body text misses 4.5:1 against their own "
        "surfaces has changed.\n  now: "
        + ", ".join(f"{n} ({measured[n][0]:.2f} panel / {measured[n][1]:.2f} bg)"
                    for n in sorted(under))
        + "\n  named on purpose: " + ", ".join(sorted(_B15_UNDER_AA))
        + "\nA palette joining this set is a new instance of `B15` and is not "
        "covered by the ruling that named these two. A palette leaving it means "
        "`B390` shipped and this exception can retire."
    )
    for name, (want_panel, want_bg) in _B15_UNDER_AA.items():
        got_panel, got_bg = measured[name]
        assert round(got_panel, 2) == want_panel, (name, got_panel)
        assert round(got_bg, 2) == want_bg, (name, got_bg)
    # The row's other two numbers, because a ruling that rests on "the default
    # is fine and these two are opt-in" stops being true if either moves.
    assert round(measured["dark"][0], 2) == 12.72
    clear = sorted((v[0], n) for n, v in measured.items() if n not in _B15_UNDER_AA)
    assert clear[0][1] == "light" and round(clear[0][0], 2) == 7.13, clear[:3]


def test_the_muted_foreground_floor_and_the_palette_B15_never_counted(palettes):
    """`B15`'s re-measure found a third palette under AA on `--fg-muted`/`--bg`
    and the row never counted it. It is `light`, and it is counted here.

    `--color-muted` is `--fg-muted`'s pivot and `B22` deliberately leaves it
    unscoped; this is the number that decision costs, stated rather than
    implied. `cute` and `retrowave` are under for the reason `P1-03` already
    wrote down — their own `--fg` is under, and no mix of it can climb above it.
    """
    measured = {n: (_contrast(_resolve("var(--fg-muted)", t), _resolve("var(--panel)", t)),
                    _contrast(_resolve("var(--fg-muted)", t), _resolve("var(--bg)", t)))
                for n, t in palettes.items()}
    under = {n for n, (p, b) in measured.items() if min(p, b) < BODY_FLOOR}
    assert under == {"cute", "retrowave", "light"}, sorted(under)
    assert round(measured["light"][1], 2) == 4.16, measured["light"]
    # All three still clear the 3:1 graphic floor, which is what `P1-03` chose
    # the value to guarantee and is why this is a note rather than a row.
    for name in under:
        assert min(measured[name]) >= GRAPHIC_FLOOR, (name, measured[name])


# ── `B16` ───────────────────────────────────────────────────────────────────


def test_the_accent_graphic_floor_fails_on_two_palettes_not_the_three_B16_named(palettes):
    """`B16`'s headline is false, and the two surfaces it conflated are split.

    Against `--panel`: `paper` 2.24 and `cute` 2.56 fail 3:1; `light` measures
    3.03, which passes. Against `--bg`: `light` is 2.75 and does fail. Two
    different claims about two different surfaces, and the row made one.
    """
    panel = {n: _contrast(_resolve("var(--accent, var(--red))", t),
                          _resolve("var(--panel)", t)) for n, t in palettes.items()}
    bg = {n: _contrast(_resolve("var(--accent, var(--red))", t),
                       _resolve("var(--bg)", t)) for n, t in palettes.items()}
    assert {n for n, r in panel.items() if r < GRAPHIC_FLOOR} == {"paper", "cute"}
    assert {n for n, r in bg.items() if r < GRAPHIC_FLOOR} == {"paper", "cute", "light"}
    assert round(panel["paper"], 2) == 2.24
    assert round(panel["cute"], 2) == 2.56
    assert round(panel["light"], 2) == 3.03, "the number `B16` quoted as a failure"
    assert panel["light"] > GRAPHIC_FLOOR, "`B16`'s third palette passes on `--panel`"
    assert round(bg["light"], 2) == 2.75, "and fails only against `--bg`"


# ── `B22` ───────────────────────────────────────────────────────────────────

# The nineteen. Floor per token is what the SHEET does with it: 4.5:1 where it
# paints text, 3:1 where it only draws a border, a dot or a background.
_SEMANTIC_FLOORS = {
    "green": BODY_FLOOR, "warn": BODY_FLOOR,
    "color-error": BODY_FLOOR, "color-error-light": GRAPHIC_FLOOR,
    "color-success": BODY_FLOOR, "color-warning": BODY_FLOOR,
    "color-danger": BODY_FLOOR, "color-recording": BODY_FLOOR,
    "color-recording-hover": GRAPHIC_FLOOR, "color-muted": BODY_FLOOR,
    "color-muted-alt": BODY_FLOOR, "color-accent": BODY_FLOOR,
    "color-agent-active": GRAPHIC_FLOOR, "color-brand-blue": GRAPHIC_FLOOR,
    "color-blind-orange": BODY_FLOOR, "color-save-green": BODY_FLOOR,
    "color-link-hover": BODY_FLOOR, "color-subheader": BODY_FLOOR,
    "accent-warm": BODY_FLOOR,
}

# Named exceptions, each with the reason and the row that owns it. A token
# joining this dict without a row is the thing this structure exists to stop.
_SEMANTIC_EXCEPTIONS = {
    "color-muted": "P1-06 — `--fg-muted`'s pivot; scoping it re-opens `P1-03`",
    "color-danger": "B393 — one token, two jobs; no single value satisfies both",
    "color-recording-hover": "B393 — same, a background with a white label",
    "color-error": "P1-08 — dark arm held; `#fff` sits on it at two rules",
    "color-recording": "P1-08 — dark arm held; `white` sits on it at two rules",
}


def test_every_semantic_token_clears_its_floor_or_is_a_named_exception(palettes):
    """`B22`'s `Verify`, in full: every semantic token against every palette's
    own two surfaces.

    This is a test of VALUES resolved out of the shipped sheet, which is what
    makes it worth having — it protects a seventeenth palette and a re-tuned
    token, and a `light-dark()` arm edited the wrong way fails here rather than
    shipping.
    """
    failures, exercised = {}, set()
    for token, floor in _SEMANTIC_FLOORS.items():
        for name, theme in palettes.items():
            worst = _worst(f"var(--{token})", theme)
            if worst < floor:
                failures.setdefault(token, []).append((name, round(worst, 2)))
                exercised.add(token)
    unnamed = {t: v for t, v in failures.items() if t not in _SEMANTIC_EXCEPTIONS}
    assert not unnamed, (
        "these semantic tokens miss their floor on a palette and no row names "
        "them: " + json.dumps(unnamed, indent=1)
    )
    # Every named exception must still be a real one. A row kept alive past its
    # defect is the same defect as a defect kept alive past its row.
    stale = sorted(set(_SEMANTIC_EXCEPTIONS) - set(failures))
    assert not stale, (
        "these are named as exceptions and now pass everywhere — retire the "
        f"exception and close the row: {stale}"
    )
    # Two numbers the row is named after, kept honest: `--color-danger` on
    # `claude` is the worst of the twelve dark palettes it fails on, and
    # `--green` on `paper`'s panel was the row's headline before it was scoped.
    assert round(
        _contrast(_resolve("var(--color-danger)", palettes["claude"]),
                  _resolve("var(--panel)", palettes["claude"])), 2) == 2.43
    assert round(
        _contrast(_rgb("#50fa7b"), _resolve("var(--panel)", palettes["paper"])), 2) == 1.37


def test_scoping_a_token_did_not_move_it_on_the_surface_it_was_tuned_for(palettes):
    """The claim that makes `B22` a fix rather than a repaint, asserted.

    Twelve of the fourteen scoped tokens were tuned against a dark panel, and
    their dark arm IS the literal the sheet shipped — so on the twelve dark
    palettes not one of them changed colour. Only the four light palettes see
    anything, and what they see is the end of being handed a dark theme's
    value.

    Two ran backwards, which is `B22`'s own finding — `--color-muted-alt` was
    light-tuned and missed 4.5:1 on 13 of the 16, `--color-subheader` on 7 —
    and a token that failed on BOTH surface classes cannot keep either arm.
    They are named here with the distance each arm travelled, because "we moved
    two and here is how far" is the honest form of this claim.
    """
    dark_tuned = {
        "green": "#50fa7b", "warn": "#f0ad4e",
        "color-error": "#ff4444", "color-error-light": "#ff6666",
        "color-success": "#4caf50", "color-warning": "#f0ad4e",
        "color-recording": "#ff3b30", "color-accent": "#00aaff",
        "color-agent-active": "#00ff00", "color-blind-orange": "#ff9800",
        "color-link-hover": "#66c7ff", "accent-warm": "#d19a66",
    }
    light_tuned = {"color-muted-alt": "#6b7280", "color-subheader": "#6b8a94"}

    root = _root_expressions()
    scoped = {t for t, v in root.items() if v.startswith("light-dark(")}
    assert scoped == set(dark_tuned) | set(light_tuned), sorted(scoped)

    light = set(_light(palettes))
    assert light == {"cute", "lavender", "light", "paper"}, sorted(light)

    for token, literal in dark_tuned.items():
        for name, theme in palettes.items():
            got = _resolve(f"var(--{token})", theme)
            if name in light:
                assert got != _rgb(literal), (
                    f"--{token} still paints the dark literal on `{name}`, "
                    "which is the whole defect `B22` names"
                )
            else:
                assert got == _rgb(literal), (
                    f"--{token} changed on `{name}`, a dark palette. `B22` is "
                    "scoping, not recolouring: the dark arm is the literal."
                )
    # The two that had to move on both sides, and how far. A jump here means
    # somebody re-picked a colour rather than re-tuned one.
    travelled = {}
    for token, literal in light_tuned.items():
        for scheme, group in (("light", light), ("dark", set(palettes) - light)):
            name = sorted(group)[0]
            travelled[f"{token}/{scheme}"] = round(
                _distance(_resolve(f"var(--{token})", palettes[name]), _rgb(literal)), 1
            )
    assert travelled == {
        "color-muted-alt/light": 13.9, "color-muted-alt/dark": 65.3,
        "color-subheader/light": 46.6, "color-subheader/dark": 33.3,
    }, travelled


def test_a_light_arm_is_the_dark_arm_at_a_different_lightness(palettes):
    """No token gains a hue it did not have. Same hue, same saturation, the
    lightness walked until the floor is cleared — which is the difference
    between scoping a colour and choosing a new one."""
    import colorsys

    def hs(rgb):
        h, _, s = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
        return h * 360, s * 100

    for token, expr in _root_expressions().items():
        if not expr.startswith("light-dark("):
            continue
        arms = re.fullmatch(r"light-dark\(\s*(#[0-9a-fA-F]{3,8})\s*,\s*"
                            r"(#[0-9a-fA-F]{3,8})\s*\)", expr)
        assert arms, f"--{token}: {expr!r} — both arms should be plain hex"
        lh, ls_ = hs(_rgb(arms.group(1)))
        dh, ds = hs(_rgb(arms.group(2)))
        hue_gap = min(abs(lh - dh), 360 - abs(lh - dh))
        assert hue_gap <= 2.0, (
            f"--{token}'s light arm is hue {lh:.1f} against the dark arm's "
            f"{dh:.1f} — that is a different colour, not the same one scoped"
        )
        assert abs(ls_ - ds) <= 25.0, (
            f"--{token}'s two arms differ in saturation by {abs(ls_ - ds):.1f}"
        )


def test_the_two_error_tokens_stay_two_colours_on_every_palette(palettes):
    """`--color-error-light` is the hover of a control whose base is
    `--color-error` (`.close-split-btn`, `.pane-close-btn`). Scoping both to a
    light surface is where they could have collapsed into one value — the
    naive light arm for both is the same darkened red, and a hover that paints
    the base colour is the defect `P1-03` found in three tab strips.

    So the light arm is picked in the direction the word "light" means on a
    light page: MORE emphasis, which is darker. The invariant is the pair, not
    either value — distinguishable, and the hover never the weaker of the two.

    **This was already broken and nobody had named it.** Before `B22` the pair
    was `#ff4444` hovering to `#ff6666` on every palette, and on the four light
    ones the hover LOWERED the contrast: `light` 3.17 → 2.66 against `--panel`
    and 2.87 → 2.41 against `--bg`, `paper` 3.41 → 2.86, `lavender` 3.22 → 2.70,
    `cute` 3.26 → 2.73. Same shape as the `details a:hover` defect `B23` found,
    found by the same invariant, on a control rather than a link — which is the
    argument for asserting the invariant instead of the four palette names.
    """
    for name, theme in palettes.items():
        base = _resolve("var(--color-error)", theme)
        hover = _resolve("var(--color-error-light)", theme)
        gap = _distance(base, hover)
        assert gap >= 40, (
            f"on `{name}`, the close button's hover is {gap:.1f} sRGB units "
            "from its base — the hover does nothing there"
        )
        for surface, ground in _surfaces(theme).items():
            assert _contrast(hover, ground) >= _contrast(base, ground) - 0.005, (
                f"on `{name}` against --{surface}, hovering the close button "
                "LOWERS its contrast"
            )


# ── `B23` ───────────────────────────────────────────────────────────────────

# The two rules that deliberately do not take the link hue, and why. Both are
# `Law 1`: they were making a different point before this row and still are.
_NOT_LINK_HUE = {
    ".mcp-tools-panel .mcp-tools-header a": "var(--fg)",
    ".cal-event-loc a, .cal-event-time a": "inherit",
}


def _anchor_colour_rules() -> list:
    """Every rule in the sheet that sets a colour on an `<a>`.

    The census `B23` is a `Law 13` row about. Selector-shaped, not a list of the
    selectors somebody remembered: a link rule added tomorrow is in this
    population whether or not anybody updates a fixture.
    """
    css = _css()
    out = []
    for m in re.finditer(r"(?m)^([^{}/@][^{}]*?)\{([^{}]*)\}", css):
        selector, body = " ".join(m.group(1).split()), m.group(2)
        if not re.search(r"(?:^|[\s,>+~])a(?::[a-z-]+)?(?=\s*(?:[,{]|$))", selector):
            continue
        for decl in re.finditer(r"(?<![-\w])(color|border-bottom-color)\s*:\s*([^;]+)",
                                body):
            line = css[:m.start()].count("\n") + 1
            out.append((line, selector, decl.group(1), decl.group(2).strip()))
    return out


def test_there_is_one_link_colour_and_it_is_named_once():
    """`B23`'s `Verify`. Seven idioms before, one token now.

    The print rule is excluded by what it is rather than by name: inside
    `@media print` the sheet forces `#000`, which is ink on paper and not a
    theme at all.
    """
    idioms, offenders = set(), []
    for line, selector, prop, value in _anchor_colour_rules():
        if "!important" in value and "#000" in value:
            continue                      # @media print
        if _NOT_LINK_HUE.get(selector) and _NOT_LINK_HUE[selector] in value:
            continue
        idioms.add(re.sub(r"\s*!important\s*$", "", value))
        if "--link-fg" not in value and "--link-hover-fg" not in value:
            offenders.append((line, selector, prop, value))
    assert not offenders, (
        "these paint a link in something other than the one named link token: "
        + json.dumps(offenders, indent=1)
    )
    assert idioms == {"var(--link-fg)", "var(--link-hover-fg)",
                      "var(--link-fg, var(--hl-function, #5b8def))"}, sorted(idioms)


def test_the_dead_accent_primary_link_rule_agrees_with_the_one_that_wins():
    """`B23` found a rule that never painted: `.email-reader-body a` at `:30875`
    set `var(--accent-primary, var(--red))` and the `!important` 500 lines below
    out-ranked it. `--accent-primary` is set by no writer in this tree, so the
    fallback was the accent and the winner was `--hl-function` — two different
    colours, one of them unreachable.

    Deleting the loser would have been a subtraction (`Law 1`) and leaving it
    would have kept a second answer alive. Both now name `--link-fg`, so the
    `!important` can go whenever somebody wants and nothing moves.
    """
    rules = [(line, value) for line, selector, _, value in _anchor_colour_rules()
             if selector.startswith(".email-reader-body a,")]
    assert len(rules) == 2, rules
    values = {re.sub(r"\s*!important\s*$", "", v) for _, v in rules}
    assert values == {"var(--link-fg)"}, rules
    assert "--accent-primary" not in _css()[_css().index(".email-reader-body a,"):
                                            _css().index(".email-reader-body a,") + 400]


def test_a_link_hover_never_loses_contrast(palettes):
    """The unnamed defect `B23` found while measuring, asserted as an invariant
    rather than as four palette names.

    `details a:hover` fell from 3.03 to 1.74 on `light` — the hover made the
    link harder to see. That is not a taste question; a hover state that
    reduces contrast is backwards on every palette that has one.
    """
    worse = []
    for name, theme in palettes.items():
        for surface, ground in _surfaces(theme).items():
            base = _contrast(_resolve("var(--link-fg)", theme), ground)
            hover = _contrast(_resolve("var(--link-hover-fg)", theme), ground)
            if hover < base - 0.005:
                worse.append((name, surface, round(base, 2), round(hover, 2)))
    assert not worse, (
        "hovering a link LOWERS its contrast here: " + json.dumps(worse, indent=1)
    )


def test_the_link_hue_is_the_one_that_cleared_aa_and_the_others_did_not(palettes):
    """Why `--hl-function` and not one of the other six — measured, so the
    choice can be re-checked rather than believed.

    Against `--panel`, which is the surface both high-traffic link surfaces sit
    on (`.msg a` inside an AI bubble, which is `--ai-bubble-bg` and therefore
    `--panel`; `details a` inside a panel), it clears 4.5:1 on all sixteen and
    the worst is `cute` at 4.61 — on a palette whose own body text is 3.44,
    which is the property that makes a derived hue worth having.

    Against `--bg` it does not quite, on three light palettes: `light` 4.19,
    `lavender` 4.36, `cute` 4.38. That is named rather than rounded away, and
    it is filed as `B395`. It is also the best available by a wide margin —
    every alternative idiom measures 2.1 to 2.8 on the same surfaces — so it is
    the residual of a fix, not a reason not to make it.

    The alternatives are measured at the values they had BEFORE `B22` scoped
    them, because that is the tree `B23` chose against; scoring them at their
    post-`B22` values would be reading the answer back out of the fix.
    """
    panel = {n: _contrast(_resolve("var(--link-fg)", t), _resolve("var(--panel)", t))
             for n, t in palettes.items()}
    bg = {n: _contrast(_resolve("var(--link-fg)", t), _resolve("var(--bg)", t))
          for n, t in palettes.items()}
    assert min(panel.values()) >= BODY_FLOOR, (
        "the link hue has stopped clearing AA against --panel: "
        + json.dumps({n: round(r, 2) for n, r in panel.items() if r < BODY_FLOOR})
    )
    assert round(min(panel.values()), 2) == 4.61
    assert min(panel, key=panel.get) == "cute"
    assert {n for n, r in bg.items() if r < BODY_FLOOR} == {"light", "lavender", "cute"}
    assert [round(bg[n], 2) for n in ("light", "lavender", "cute")] == [4.19, 4.36, 4.38]

    # The six it beat, at their pre-`B22` literals.
    was = {"--accent / --accent, var(--red)": "var(--accent)",
           "--color-accent": "#00aaff",
           "--color-link-hover": "#66c7ff",
           "--accent-primary fallback": "var(--red)"}
    for label, expr in was.items():
        under = {n for n, t in palettes.items() if _worst(expr, t) < BODY_FLOOR}
        assert len(under) >= 4, (
            f"{label} now clears AA nearly everywhere — re-open the choice; "
            f"under on {sorted(under)}"
        )
    # And it is not the theme's own accent wearing a different name.
    gaps = {n: _distance(_resolve("var(--link-fg)", t),
                         _resolve("var(--accent)", t)) for n, t in palettes.items()}
    assert round(min(gaps.values()), 1) == 46.2, sorted(gaps.items(), key=lambda x: x[1])[:3]
    assert min(gaps, key=gaps.get) == "ocean"


# ── The mechanism `B22` rests on ────────────────────────────────────────────


def test_light_dark_has_a_scheme_to_key_off_on_every_path(palettes):
    """`light-dark()` resolves to its LIGHT arm when `color-scheme` is `normal`.

    So the four palette-reading paths all have to set it, and the sheet has to
    carry a default for the instant before any of them run. Three writers set it
    from the background's luminance (`P3-09`); `:root` declares `dark`, which is
    the scheme of the palette whose literals `:root` also declares.
    """
    for name, theme in palettes.items():
        want = "light" if _relative_luminance(_rgb(theme["bg"])) > 0.5 else "dark"
        assert theme["color-scheme"] == want, (name, theme["color-scheme"], want)
    root_block = _css()[_css().index(":root {"):]
    root_block = root_block[:root_block.index("}")]
    assert re.search(r"color-scheme\s*:\s*dark\s*;", root_block), (
        "`:root` must carry the default arm, or every `light-dark()` token "
        "paints its light value on a dark page until `theme.js` boots"
    )
    # And the default matches the literals beside it, which is the only thing
    # that makes it correct rather than merely present.
    assert _relative_luminance(_rgb(_root_expressions()["bg"])) <= 0.5
