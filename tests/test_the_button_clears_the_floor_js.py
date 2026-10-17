# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P1-08`, `P1-09`, `P10-04`. The foreground on an accent, computed and agreed.

Three implementations have to produce the same answer for every palette, and
none of them can import the others:

  * `onAccentFor()` in `static/js/theme.js`, which `applyColors()` writes;
  * the inline first-paint script in `static/index.html`, which runs before any
    module loads — without it the send button paints with the stylesheet
    fallback on every cold load, which is the unreadable flash this row ends;
  * the same script in `static/login.html`, the one screen `initThemeUI()`
    never reaches;
  * and `.pantheon/check-contrast.py`, which audits the formula in CI.

So the test drives all four over **every** palette in `THEMES` and fails if any
pair disagrees. That is the only way this stays true: the module's own comment
records that the two first-paint mirrors "may not carry a key this one lacks,
because nothing else ever clears one", and a copied formula is exactly the
thing that rots.

**Measured 2026-10-17, re-deriving the row's own numbers before changing
anything.** The row's 2026-08-30 figures reproduced exactly — `paper` 2.24,
`cute` 2.56, `light` 3.03, `claude` 3.26, `lavender` 3.63, `organs` 3.72,
`retrowave` 4.15 for accent-on-panel — which is what made the rest of its
measurements trustworthy. Two things it could not have known:

  * there are **23** palettes now, not sixteen. Seven were added after it was
    written, which is why the audit reads `THEMES` and this file parametrises
    over it rather than either naming a count;
  * **46** CSS rules painted a hard-coded white on an accent background, not
    the 19 the row measured. The surface grew.

`D-2026-09-08-01` ruled that the owner picks one global button design and every
option must clear 4.5:1 on every palette *by construction*. Measurement says
exactly one does — `filled` with a computed foreground, worst case `claude` at
5.18:1 — and that it is the only design that also clears the two palettes `B15`
records as having no legible foreground against their own panel (`cute` 7.84,
`retrowave` 5.48). `outline` and `tinted` clear everywhere else and fail only
there, so they are blocked on `B15` rather than broken, and the audit says so
in those words.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytestmark = pytest.mark.skipif(
    not shutil.which("node"), reason="node binary not on PATH"
)


def _audit():
    spec = importlib.util.spec_from_file_location(
        "check_contrast", ROOT / ".pantheon" / "check-contrast.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CC = _audit()
PALETTES = sorted(CC.themes().items())
BODY_FLOOR = CC.BODY_FLOOR


def _expected(accent: str) -> str:
    return ("#000000"
            if CC.contrast("#000000", accent) >= CC.contrast("#ffffff", accent)
            else "#ffffff")


# ── the audit itself ───────────────────────────────────────────────────────


def test_there_is_more_than_one_palette_and_the_row_s_count_is_stale():
    """Non-vacuity, and the finding that reframed the row: it says sixteen."""
    assert len(PALETTES) >= 23, f"only {len(PALETTES)} palettes parsed"


def test_the_contrast_audit_passes_on_this_tree():
    """End to end, as CI runs it."""
    result = subprocess.run(
        [sys.executable, str(ROOT / ".pantheon" / "check-contrast.py")],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "contrast OK" in result.stdout


def test_no_css_rule_paints_a_hard_coded_white_on_an_accent():
    """46 did. The audit's own reader, so the test and CI cannot disagree."""
    assert CC._css_white_on_accent() == []


@pytest.mark.parametrize("name,pal", PALETTES, ids=[n for n, _ in PALETTES])
def test_the_computed_foreground_clears_the_floor_on_every_palette(name, pal):
    """The property the ruling asked for: by construction, not by validation."""
    accent = pal.get("red", pal["fg"])
    ratio = CC.contrast(_expected(accent), accent)
    assert ratio >= BODY_FLOOR, f"{name}: best foreground only reaches {ratio:.2f}:1"


def test_the_filled_design_is_the_only_one_offered_and_why():
    """`D-2026-09-08-01` plus measurement. If `B15` is ever fixed, `outline`
    and `tinted` clear everywhere and the audit says to offer them — so this
    case pins today's answer *and* the reason, rather than the number 1."""
    designs = CC.button_designs()
    assert CC.OFFERABLE == ("filled",)
    for theme in CC.B15_THEMES:
        assert designs[theme]["filled"] >= BODY_FLOOR, (
            f"filled no longer clears {theme}; B15 would have no fix left")
        for blocked in CC.BLOCKED_ON_B15:
            assert designs[theme][blocked] < BODY_FLOOR, (
                f"{blocked} now clears {theme} — B15 looks fixed, so offer it")
    # And the legacy white button is kept in the table as the thing that failed.
    legacy = [t for t, r in designs.items()
              if r["filled_white_legacy"] < BODY_FLOOR]
    assert len(legacy) >= 18, (
        f"only {len(legacy)} palettes fail white-on-accent; the row measured 18")


# ── P1-09: the guard that has no case to catch ─────────────────────────────


def test_the_computed_foreground_cannot_fail_on_any_colour_that_exists():
    """`P1-09`. The arithmetic, against a sweep that does not know it.

    `worst_possible_on_accent()` solves `min max(20x, 1.05/x)` in closed form.
    This re-derives the same number by brute force over a wide sample of the
    24-bit space, so the algebra and the measurement have to agree — if the
    closed form is ever "simplified" wrongly, the sweep catches it.
    """
    floor = CC.worst_possible_on_accent()
    assert floor >= BODY_FLOOR, (
        f"the best of black and white bottoms out at {floor:.4f}:1, under the "
        f"{BODY_FLOOR}:1 body floor — P1-09 needs a real guard after all")

    worst, where = 99.0, None
    for r in range(0, 256, 3):
        for g in range(0, 256, 17):
            for b in range(0, 256, 17):
                colour = f"#{r:02x}{g:02x}{b:02x}"
                best = CC.contrast(CC.on_accent_for(colour), colour)
                if best < worst:
                    worst, where = best, colour
    assert worst >= BODY_FLOOR, f"{where} only reaches {worst:.4f}:1"
    # The sweep cannot beat the analytic floor, and lands within a hair of it —
    # which is what makes the closed form trustworthy rather than merely tidy.
    assert worst >= floor - 1e-9, f"sweep found {worst:.6f} below the proof {floor:.6f}"
    assert worst - floor < 0.01, (
        f"the sweep's worst ({worst:.4f}) is far above the proof ({floor:.4f}) — "
        "the sample no longer reaches the luminance the minimum sits at")


def test_the_harmony_generator_cannot_emit_a_palette_that_misses_the_floor(
        tmp_path_factory):
    """`P1-09`'s other half, driven rather than read (`Law 20`).

    The row asks for a guard inside `generateHarmonyColors()`. The generator is
    run here over its whole input space — every hue, four saturations, three
    lightnesses, all four harmonies, both modes — and **none** of the palettes
    it can emit misses the body floor, on either surface. The pins `fgL` to
    84–87 against a `bgL` of 12–14 in dark mode and 13–18 against 95–99 in
    light, so the floor is a property of those constants. Lower one and this
    fails, which is the guard, located where it can actually be true.
    """
    from test_accent_token_js import (_TEST_EXPORTS, _THEME_SHIM, _THEME_STUBS,
                                      _make_sandbox, THEME)

    sandbox = _make_sandbox(tmp_path_factory.mktemp("harmony"), THEME,
                            _THEME_SHIM, _THEME_STUBS)
    with (sandbox / THEME.name).open("a", encoding="utf-8") as handle:
        handle.write(_TEST_EXPORTS)
    entry = sandbox / "sweep.mjs"
    entry.write_text(
        "import './shim.js';\n"
        "const tm = await import('./theme.js');\n"
        "const HS = ['complementary', 'analogous', 'triadic', 'monochromatic'];\n"
        "function hsl(h, s, l) {\n"
        "  s /= 100; l /= 100;\n"
        "  const a = s * Math.min(l, 1 - l);\n"
        "  const f = (n) => { const k = (n + h / 30) % 12;\n"
        "    return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };\n"
        "  const t = (v) => Math.round(v * 255).toString(16).padStart(2, '0');\n"
        "  return '#' + t(f(0)) + t(f(8)) + t(f(4));\n"
        "}\n"
        "const out = [];\n"
        "for (let h = 0; h < 360; h += 5)\n"
        "  for (const sat of [20, 45, 70, 95])\n"
        "    for (const li of [35, 50, 65])\n"
        "      for (const ht of HS)\n"
        "        for (const mode of ['dark', 'light']) {\n"
        "          const acc = hsl(h, sat, li);\n"
        "          out.push([acc, ht, mode, tm._generateHarmonyColors(acc, ht, mode)]);\n"
        "        }\n"
        "console.log(JSON.stringify(out));\n"
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    rows = json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])
    assert len(rows) >= 4000, f"the sweep only produced {len(rows)} palettes"

    def _fails(surface):
        return [(acc, ht, mode, round(CC.contrast(c["fg"], c[surface]), 2))
                for acc, ht, mode, c in rows
                if CC.contrast(c["fg"], c[surface]) < BODY_FLOOR]

    for surface in ("bg", "panel"):
        bad = _fails(surface)
        assert not bad, (
            f"{len(bad)} of {len(rows)} generated palettes put body text under "
            f"{BODY_FLOOR}:1 on their own {surface}; worst {min(bad, key=lambda r: r[3])}")

    # And the accent half: every accent the generator is handed gets a legible
    # foreground, which is the claim `--on-accent` makes for custom themes.
    illegible = [acc for acc, _, _, _ in rows
                 if CC.contrast(CC.on_accent_for(acc), acc) < BODY_FLOOR]
    assert not illegible, f"{len(illegible)} generated accents have no legible foreground"


# ── the four implementations, held equal ───────────────────────────────────


@pytest.fixture(scope="module")
def module_values(tmp_path_factory):
    """`--on-accent` as `applyColors()` writes it, per palette."""
    from test_accent_token_js import (_TEST_EXPORTS, _THEME_SHIM, _THEME_STUBS,
                                      _make_sandbox, THEME)

    sandbox = _make_sandbox(tmp_path_factory.mktemp("onaccent"), THEME,
                            _THEME_SHIM, _THEME_STUBS)
    with (sandbox / THEME.name).open("a", encoding="utf-8") as handle:
        handle.write(_TEST_EXPORTS)
    entry = sandbox / "case.mjs"
    payload = json.dumps({n: p for n, p in PALETTES})
    entry.write_text(
        "import { vars } from './shim.js';\n"
        "const tm = await import('./theme.js');\n"
        f"const pals = {payload};\n"
        "const out = {};\n"
        "for (const [name, pal] of Object.entries(pals)) {\n"
        "  tm.applyColors(pal);\n"
        "  // `vars` is a function returning {names, values}, and the shim's own\n"
        "  // comment says why: setProperty(k, undefined) keeps the key holding\n"
        "  // undefined, which JSON.stringify would drop from a plain object.\n"
        "  out[name] = vars().values['--on-accent'] ?? null;\n"
        "}\n"
        "console.log(JSON.stringify(out));\n"
    )
    proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


@pytest.fixture(scope="module", params=["index", "login"])
def paint_values(request, tmp_path_factory):
    """`--on-accent` as each first-paint inline script writes it."""
    from test_accent_token_js import _DOM, _PAINT_SHIM, _inline_script, INDEX, LOGIN

    html = INDEX if request.param == "index" else LOGIN
    sandbox = tmp_path_factory.mktemp("paint-" + request.param)
    (sandbox / "dom.js").write_text(_DOM)
    (sandbox / "shim.js").write_text(_PAINT_SHIM)
    (sandbox / "paint.js").write_text(_inline_script(html))
    out = {}
    for name, pal in PALETTES:
        entry = sandbox / "case.mjs"
        # The shape both scripts read: `JSON.parse(localStorage...)` and then
        # `if (t && t.colors)`. A bare palette seeded as `t` skips the whole
        # block silently and every assertion below would read "never wrote it",
        # which is a true statement about the harness and nothing about the page.
        stored = {"name": name, "colors": pal}
        entry.write_text(
            "import { seed, vars } from './shim.js';\n"
            f"seed({json.dumps(stored)});\n"
            "await import('./paint.js');\n"
            "console.log(JSON.stringify({v: vars().values['--on-accent'] ?? null}));\n"
        )
        proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, f"{request.param}/{name}: {proc.stderr}"
        line = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
        out[name] = json.loads(line)["v"]
    return request.param, out


def test_the_module_computes_the_same_foreground_as_the_audit(module_values):
    """Two implementations, 23 palettes, one answer."""
    assert module_values, "the sandbox produced no values"
    for name, pal in PALETTES:
        accent = pal.get("red", pal["fg"])
        assert module_values[name] == _expected(accent), (
            f"{name}: theme.js says {module_values[name]}, "
            f"the audit says {_expected(accent)}")


def test_each_first_paint_script_agrees_too(paint_values):
    """The mirrors. Their own comments say nothing else ever clears a key they
    lack, so a mirror that drifts is a flash the module cannot repair."""
    which, values = paint_values
    assert values, f"{which}: no values produced"
    missing = [n for n, v in values.items() if not v]
    assert not missing, f"{which} never wrote --on-accent for: {missing}"
    for name, pal in PALETTES:
        accent = pal.get("red", pal["fg"])
        assert values[name] == _expected(accent), (
            f"{which}/{name}: paints {values[name]}, audit says {_expected(accent)}")
