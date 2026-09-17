# SPDX-License-Identifier: AGPL-3.0-or-later
"""P1-01 — `--accent`, defined per theme and at every place the palette is written.

The token is written in three places, because `--red` is written in three
places and only one of them is `applyColors()`:

  * `static/js/theme.js` `applyColors()` — the module, which runs on the main
    app once `initThemeUI()` gets past its `#themeGrid` guard;
  * `static/index.html`'s first-paint script — which runs before the module
    exists. `style.css` carries 202 bare `var(--accent)` declarations that are
    invalid at computed-value time while nothing defines the token, so without
    this site every cold load paints them dead and then repaints them alive;
  * `static/login.html`'s own bootstrap — `initThemeUI()` returns at the
    `#themeGrid` that page does not have, above the `applyColors()` call, so
    the module never reaches it. That is the page's own comment, and it is
    true.

`Law 13` is why all three are pinned together rather than one each: a token
set in one of three places is exactly the defect class the law names, and it
is invisible from any single file.

What each test holds, and why it is a defect if it breaks:

  * **every palette writer writes the accent.** The set is derived from who
    writes `--red` rather than hard-coded, so a fourth writer added later fails
    this rather than silently shipping a fourth accent-less path;

  * **each of the sixteen themes gets its own red**, and the sixteen are not
    all the same colour. `DECISIONS.md` D-2026-08-26-03 protects the themes;
    the failure this guards is a `:root` definition, which retires the fallback
    in `var(--accent, var(--red))` at all 553 of those sites in `style.css` at
    once and gives every theme one global accent;

  * **the guard survives a palette with no red.** Dropping `if (_ac)` writes
    the literal token `undefined`, and `var(--accent)` then resolves to it —
    invalid at computed-value time at all 970 `--accent…` sites in `style.css`.
    That is the same shape as `P1-09`'s `CI:` line: a theme token half-added
    breaks every theme at once, so it is measured, not assumed;

  * **the accent is not a theme-editor key.** `ADV_KEYS` and
    `computeAdvancedDefaults()` are indexed by the same `key` in six loops and
    must move in lockstep. `--accent` is a core token set beside `--red`, and
    `--red` is not in `ADV_KEYS` either — the test pins both the lockstep and
    the accent's absence from it, so nobody "fixes" the CI line by adding a
    picker that would then need a fourth and fifth mirror;

  * **`--accent` is defined in no `:root` rule** of any file the theme system
    governs. Scope is derived from what `index.html` actually links plus the
    two documents the server renders, because the three `*-variants.html`
    design prototypes each define an `--accent` in their own `:root` and are
    entitled to: they load neither `style.css` nor `theme.js`, so they cannot
    flatten a theme. A hand-maintained exclusion list would be exempted again.

Counts above were re-derived from `static/style.css` on 2026-08-30 and move as
it grows; `test_the_counts_the_comments_quote_are_still_the_counts` re-derives
them so a stale number fails rather than misleading the next reader.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

# One harness — the DOM shim and sandbox builder the JS suites share.
from test_tool_effect_surfaces_js import _DOM, _make_sandbox  # noqa: E402
from tests.helpers.source_text import blank, blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "static" / "js" / "theme.js"
INDEX = ROOT / "static" / "index.html"
LOGIN = ROOT / "static" / "login.html"
STYLE = ROOT / "static" / "style.css"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The sixteen shipped palettes are read out of `theme.js` rather than restated,
# so adding a seventeenth extends the coverage instead of leaving it behind.
THEME_NAMES = tuple(
    re.findall(
        r"^\s{2,}(\w+):\s*\{\s*bg:",
        THEME.read_text(encoding="utf-8")[
            THEME.read_text(encoding="utf-8").index("export const THEMES = {"):
        ],
        re.M,
    )
)


# ── Shared shim ─────────────────────────────────────────────────────────────

# `documentElement` is what all three sites write to and the shim's `installDom`
# does not build one. `readyState` is pinned to 'loading' so `theme.js`'s
# auto-init defers to a `DOMContentLoaded` that never fires — a floating
# `_initWithSync()` could call `applyColors` itself and mask a broken one.
_SHIM_HEAD = """
import { installDom, Node } from './dom.js';
export const document = installDom();
document.documentElement = new Node('html');
document.readyState = 'loading';
globalThis.location = { pathname: '/', origin: 'http://test.local' };
globalThis.window.location = globalThis.location;
globalThis.window.matchMedia = () => ({ matches: false });
export const root = document.documentElement;

// Presence and value are reported separately: `setProperty('--accent',
// undefined)` leaves the key in place holding `undefined`, which is exactly
// the mutation the guard test is looking for and which `JSON.stringify` would
// otherwise drop from the object entirely.
export function vars() {
  const names = Object.keys(root.style).filter((k) => k.startsWith('--'));
  const values = {};
  for (const k of names) values[k] = String(root.style[k]);
  return { names, values };
}
"""

_THEME_SHIM = _SHIM_HEAD

_PAINT_SHIM = _SHIM_HEAD + """
export function seed(theme) {
  if (theme === null) globalThis.localStorage.removeItem('pantheon-theme');
  else globalThis.localStorage.setItem('pantheon-theme', JSON.stringify(theme));
}
"""

_THEME_STUBS = {
    "storage.js": """
const mem = new Map();
export default {
  getJSON(k, d) { return mem.has(k) ? mem.get(k) : d; },
  setJSON(k, v) { mem.set(k, v); },
  remove(k) { mem.delete(k); },
};
""",
    "ui.js": "export default { styledConfirm: async () => false, showToast() {} };\n",
    "colorPicker.js": "export function initColorPickers() {}\nexport function attachColorPicker() {}\n",
    "color/hex.js": """
export function hexToRgb(hex) {
  const d = String(hex || '').replace('#', '');
  if (d.length !== 6) return null;
  return { r: parseInt(d.slice(0, 2), 16), g: parseInt(d.slice(2, 4), 16), b: parseInt(d.slice(4, 6), 16) };
}
""",
    "windowDrag.js": "export function makeWindowDraggable() {}\n",
    "tileManager.js": "export function snapModalToZone() {}\n",
}

# `generateHarmonyColors`, `ADV_KEYS` and `computeAdvancedDefaults` are module
# private and stay that way — the sandbox copy gets one appended statement so
# the tests can drive the real definitions instead of a transcription of them.
# Nothing above the appended line is touched.
_TEST_EXPORTS = (
    "\nexport { generateHarmonyColors as _generateHarmonyColors,"
    " ADV_KEYS as _ADV_KEYS,"
    " computeAdvancedDefaults as _computeAdvancedDefaults };\n"
)


def _inline_script(html: Path) -> str:
    """The one inline block in `html` that writes the palette.

    Selected by what it does, not by its position, so re-ordering the head does
    not silently start testing a different script.
    """
    blocks = [
        body
        for body in re.findall(
            r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html.read_text(encoding="utf-8"), re.S
        )
        if "setProperty('--red'" in body
    ]
    assert len(blocks) == 1, f"{html.name}: expected one palette-writing inline script, found {len(blocks)}"
    return blocks[0]


@pytest.fixture(scope="module")
def theme_sandbox(tmp_path_factory):
    sandbox = _make_sandbox(tmp_path_factory.mktemp("accenttheme"), THEME, _THEME_SHIM, _THEME_STUBS)
    with (sandbox / THEME.name).open("a", encoding="utf-8") as handle:
        handle.write(_TEST_EXPORTS)
    return sandbox


@pytest.fixture(scope="module")
def paint_sandbox(tmp_path_factory):
    sandbox = tmp_path_factory.mktemp("accentpaint")
    (sandbox / "dom.js").write_text(_DOM)
    (sandbox / "shim.js").write_text(_PAINT_SHIM)
    (sandbox / "index_paint.js").write_text(_inline_script(INDEX))
    (sandbox / "login_paint.js").write_text(_inline_script(LOGIN))
    return sandbox


def _run(sandbox: Path, preamble: str, script: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(preamble + textwrap.dedent(script))
    proc = subprocess.run(
        ["node", str(entry)], cwd=sandbox, capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


_THEME_PREAMBLE = (
    "import { vars } from './shim.js';\n"
    "const tm = await import('./theme.js');\n"
)
_PAINT_PREAMBLE = "import { seed, vars } from './shim.js';\n"


def _module(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _THEME_PREAMBLE, script)


def _paint(page: str, theme, sandbox: Path) -> dict:
    """Run one page's real first-paint script over a seeded `pantheon-theme`."""
    return _run(
        sandbox,
        _PAINT_PREAMBLE,
        f"""
        seed({json.dumps(theme)});
        await import('./{page}_paint.js');
        console.log(JSON.stringify(vars()));
        """,
    )


def _palette(name: str, **extra) -> dict:
    """A stored theme in the shape the two paint scripts read."""
    src = THEME.read_text(encoding="utf-8")
    body = src[src.index("export const THEMES = {"):]
    entry = re.search(rf"^\s{{2,}}{name}:\s*\{{(.*?)\}},?\s*$", body, re.M | re.S).group(1)
    colors = dict(re.findall(r"(\w+)\s*:\s*'(#[0-9a-fA-F]{3,8})'", entry))
    colors.update(extra)
    return {"name": name, "colors": colors}


# ── The three sites ─────────────────────────────────────────────────────────


def test_every_place_the_palette_is_written_also_writes_the_accent():
    """`Law 13`. Derived from who writes `--red`, so a fourth writer fails too."""
    writers = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "static").rglob("*")
        if path.is_file()
        and path.suffix in {".js", ".html"}
        and "setProperty('--red'" in path.read_text(encoding="utf-8", errors="ignore")
    )
    assert writers == ["static/index.html", "static/js/theme.js", "static/login.html"], (
        "the set of files that write the core palette changed; every one of them "
        f"has to write `--accent` beside `--red` — found {writers}"
    )
    for name in writers:
        text = (ROOT / name).read_text(encoding="utf-8")
        # Read the expression, not the property name: an accent wired to
        # something other than the theme's own accent-or-red is the failure
        # `:root` would have caused, spelled differently.
        assert re.search(
            r"(\w+)\s*=\s*(\w+)\.accent\s*\|\|\s*\2\.red\s*;[\s\S]{0,120}?"
            r"setProperty\(\s*'--accent'\s*,\s*\1\s*\)",
            text,
        ), f"{name} does not set `--accent` from `accent || red`"


@pytest.mark.parametrize("name", THEME_NAMES)
def test_the_module_gives_each_shipped_theme_its_own_red_as_its_accent(name, theme_sandbox):
    out = _module(
        f"""
        tm.applyColors(tm.THEMES[{json.dumps(name)}]);
        console.log(JSON.stringify({{ ...vars(), red: tm.THEMES[{json.dumps(name)}].red }}));
        """,
        theme_sandbox,
    )
    assert "--accent" in out["names"], f"{name} boots without an accent"
    assert out["values"]["--accent"] == out["red"], (
        f"{name}'s accent is {out['values']['--accent']}, not its own red {out['red']}"
    )


def test_the_sixteen_accents_are_not_one_colour(theme_sandbox):
    """The failure a `:root` definition causes, measured on values not names."""
    out = _module(
        """
        const seen = {};
        for (const [name, colors] of Object.entries(tm.THEMES)) {
          tm.applyColors(colors);
          seen[name] = vars().values['--accent'];
        }
        console.log(JSON.stringify(seen));
        """,
        theme_sandbox,
    )
    assert len(out) >= 16, f"expected every shipped theme, got {sorted(out)}"
    assert len(set(out.values())) >= 14, (
        "the themes have collapsed onto a shared accent: "
        f"{len(set(out.values()))} distinct values across {len(out)} themes"
    )


@pytest.mark.parametrize("page,name", [("index", "ocean"), ("index", "cute"), ("login", "ocean"), ("login", "terminal")])
def test_the_first_paint_scripts_set_the_accent_before_the_module_boots(page, name, paint_sandbox):
    stored = _palette(name)
    out = _paint(page, stored, paint_sandbox)
    assert "--accent" in out["names"], (
        f"{page}.html paints without an accent; every bare `var(--accent)` in "
        "style.css is dead until the module boots"
    )
    assert out["values"]["--accent"] == stored["colors"]["red"]


def test_the_login_page_is_the_one_the_module_never_reaches():
    """Pins the reason login.html needs its own line, not just that it has one."""
    src = THEME.read_text(encoding="utf-8")
    guard = src.index("document.getElementById('themeGrid')")
    apply_call = src.index("applyColors(currentColors)")
    assert guard < apply_call, (
        "`initThemeUI()` now reaches `applyColors()` before its `#themeGrid` "
        "guard — re-derive whether login.html still needs its own accent write"
    )
    assert "if (!grid) return;" in src[guard:apply_call]


# ── The palettes that are not one of the sixteen ────────────────────────────


def test_an_explicit_accent_key_outranks_the_themes_red(theme_sandbox, paint_sandbox):
    """No shipped theme carries one; the function is driven with one directly."""
    dark = _palette("dark")
    assert "accent" not in dark["colors"], "a shipped theme grew an `accent:` key — retune this test, not the assertion"

    out = _module(
        """
        tm.applyColors({ ...tm.THEMES.dark, accent: '#123456' });
        console.log(JSON.stringify({ ...vars(), red: tm.THEMES.dark.red }));
        """,
        theme_sandbox,
    )
    assert out["values"]["--accent"] == "#123456"
    assert out["values"]["--red"] == out["red"], "an accent key must not move the red"

    for page in ("index", "login"):
        painted = _paint(page, _palette("dark", accent="#123456"), paint_sandbox)
        assert painted["values"]["--accent"] == "#123456", f"{page}.html ignores an explicit accent"
        assert painted["values"]["--red"] == dark["colors"]["red"]


def test_a_generated_custom_palette_carries_no_accent_and_still_gets_one(theme_sandbox, paint_sandbox):
    """The eight custom slots come from `generateHarmonyColors()`, which returns
    no `accent` key — so `accent || red` falls through to the harmony's own red.
    """
    out = _module(
        """
        const made = {};
        for (const type of ['complementary', 'analogous', 'triadic', 'monochromatic']) {
          for (const mode of ['dark', 'light']) {
            const colors = tm._generateHarmonyColors('#7dd3fc', type, mode);
            tm.applyColors(colors);
            made[type + '/' + mode] = { keys: Object.keys(colors), accent: vars().values['--accent'], red: colors.red };
          }
        }
        console.log(JSON.stringify(made));
        """,
        theme_sandbox,
    )
    for label, made in out.items():
        assert "accent" not in made["keys"], (
            f"{label}: generateHarmonyColors() now returns an accent — the "
            "fall-through this row relies on no longer applies"
        )
        assert made["red"], f"{label}: a generated palette with no red gets no accent"
        assert made["accent"] == made["red"], f"{label}: custom slot accent is {made['accent']}, red is {made['red']}"

    # The same palette through the other two sites, as a stored custom theme.
    harmony = _module(
        "console.log(JSON.stringify(tm._generateHarmonyColors('#7dd3fc', 'triadic', 'dark')));",
        theme_sandbox,
    )
    for page in ("index", "login"):
        painted = _paint(page, {"name": "custom", "colors": harmony}, paint_sandbox)
        assert painted["values"]["--accent"] == harmony["red"], f"{page}.html drops a custom theme's accent"


@pytest.mark.parametrize("page", ["index", "login"])
def test_a_palette_with_no_red_leaves_the_accent_unset_rather_than_undefined(page, paint_sandbox):
    """Dropping the `if (_ac)` guard writes the token `undefined`, which voids
    every `var(--accent)` declaration in the sheet instead of falling back.
    """
    out = _paint(page, {"name": "broken", "colors": {"bg": "#000000", "fg": "#ffffff", "panel": "#111111", "border": "#222222"}}, paint_sandbox)
    assert "--accent" not in out["names"], (
        f"{page}.html wrote `--accent: {out['values'].get('--accent')}` for a palette "
        "with no red; an unset token falls back, a token holding `undefined` does not"
    )


def test_the_module_leaves_the_accent_unset_rather_than_undefined(theme_sandbox):
    out = _module(
        """
        tm.applyColors({ bg: '#000000', fg: '#ffffff', panel: '#111111', border: '#222222' });
        console.log(JSON.stringify(vars()));
        """,
        theme_sandbox,
    )
    assert "--accent" not in out["names"], (
        f"applyColors wrote `--accent: {out['values'].get('--accent')}` for a palette with no red"
    )


# ── The lockstep the accent stays out of ────────────────────────────────────


def test_the_advanced_keys_and_their_defaults_still_move_in_lockstep(theme_sandbox):
    """`P1-09`'s `CI:` line, measured. A key in one and not the other resolves to
    `undefined` through `adv[key] || defaults[key]` and breaks all sixteen.
    """
    out = _module(
        """
        console.log(JSON.stringify({
          keys: tm._ADV_KEYS.map((e) => e.key),
          css: tm._ADV_KEYS.map((e) => e.css),
          defaults: Object.keys(tm._computeAdvancedDefaults(tm.THEMES.dark)),
        }));
        """,
        theme_sandbox,
    )
    assert sorted(out["keys"]) == sorted(out["defaults"]), (
        "ADV_KEYS and computeAdvancedDefaults() have drifted: "
        f"{sorted(set(out['keys']) ^ set(out['defaults']))}"
    )


def test_the_accent_is_not_a_theme_editor_key(theme_sandbox):
    """`--accent` is a core token set beside `--red`, which is not in `ADV_KEYS`
    either. Adding it there would add a picker, a default, and three more
    mirrors — and would answer the CI line by breaking what it protects.
    """
    out = _module(
        """
        console.log(JSON.stringify({
          css: tm._ADV_KEYS.map((e) => e.css),
          defaults: Object.keys(tm._computeAdvancedDefaults(tm.THEMES.dark)),
        }));
        """,
        theme_sandbox,
    )
    assert "--accent" not in out["css"]
    assert "--red" not in out["css"], "the core palette does not belong in ADV_KEYS"
    assert "accent" not in out["defaults"]


# ── `:root` ─────────────────────────────────────────────────────────────────


def _themed_files() -> list:
    """The files the theme system governs: the two documents the server renders
    and every stylesheet `index.html` links. Derived rather than listed, so a
    second stylesheet is covered the day it is linked.
    """
    files = [INDEX, LOGIN]
    for href in re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', INDEX.read_text(encoding="utf-8")):
        path = ROOT / href.split("?")[0].lstrip("/")
        assert path.is_file(), f"index.html links a stylesheet that is not in the tree: {href}"
        files.append(path)
    assert STYLE in files, "index.html no longer links style.css — re-derive this scope"
    return files


def test_the_accent_is_never_defined_in_root():
    """A `:root` definition retires the fallback in `var(--accent, var(--red))`
    at all 553 of those sites in `style.css` at once, and every theme loses its
    own colour. `DECISIONS.md` D-2026-08-26-03.
    """
    offenders = []
    for path in _themed_files():
        text = blank(path)
        for block in re.finditer(r":root\b[^{}]*\{([^{}]*)\}", text):
            if re.search(r"(^|[;\s])--accent\s*:", block.group(1)):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{text[:block.start()].count(chr(10)) + 1}")
    assert not offenders, f"`--accent` is defined in a `:root` rule at {offenders}"


def test_the_counts_the_accent_comments_quote_are_still_the_counts():
    """`Law 6`. Three documents in this repo have carried a stale accent count;
    the two comments that quote one are re-derived here rather than trusted.
    """
    css = blank(STYLE)
    bare = len(re.findall(r"var\(\s*--accent(?![-\w])\s*\)", css))
    through_red = len(re.findall(r"var\(\s*--accent(?![-\w])\s*,\s*var\(\s*--red\s*\)\s*\)", css))

    for path in (THEME, INDEX):
        text = path.read_text(encoding="utf-8")
        # The P1-01 comment block, from its marker down to the line it explains.
        block = text[text.index("P1-01"):text.index("setProperty('--accent'")]
        # Row ids and the date the counts were taken are not counts.
        block = re.sub(r"\bP\d+-\d+\b|\b\d{4}-\d{2}-\d{2}\b", "", block)
        quoted = {int(n) for n in re.findall(r"\b(\d{2,4})\b", block)}
        # Equality, not membership: a second mention left behind at the old
        # value is exactly how a count goes half-stale and reads as current.
        assert quoted == {bare, through_red}, (
            f"{path.name}'s P1-01 comment quotes {sorted(quoted)}; style.css now "
            f"has {bare} bare `var(--accent)` and {through_red} "
            "`var(--accent, var(--red))` sites"
        )
