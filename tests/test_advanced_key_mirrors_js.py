# SPDX-License-Identifier: AGPL-3.0-or-later
"""P1-02 / B21 — one advanced-key set, mirrored six times, and nothing that checked.

A theme's *advanced* colours are one object — `theme.colors.advanced` in one
localStorage entry — and six places in three files claim to describe it:

  * `ADV_KEYS` in `static/js/theme.js` — the authority. It is what
    `applyColors()` walks on every theme switch, what `syncAdvancedPickers()`
    fills, and what the live-update and reset paths index;
  * `computeAdvancedDefaults()` in the same file — the value half of the same
    list, read as `adv[key] || defaults[key]`;
  * the `advMap` in `static/index.html`'s first-paint script;
  * the `id="adv-…"` colour inputs in `static/index.html`'s theme editor —
    every loop above reaches them as `getElementById('adv-' + key)`;
  * their `data-reset-adv="…"` reset buttons, in the same markup;
  * the `ADV` map in `static/login.html`'s own bootstrap, which the module
    never reaches (`initThemeUI()` returns at the `#themeGrid` that page does
    not have).

Drift in either direction is a defect, and the two look nothing alike:

  * **a key a mirror has and `ADV_KEYS` lacks is written once and never again.**
    `applyColors()` only walks `ADV_KEYS`, so the token keeps the value the
    theme the user has *left* gave it, through every later switch, for the life
    of the tab. That is `P1-02`'s actual defect, and it had four instances;
  * **a key `ADV_KEYS` has and a mirror lacks paints the default first and the
    user's override a frame later** — the flash the first-paint script exists
    to prevent. `hamburgerColor` was that, in `index.html`;
  * **`ADV_KEYS` and `computeAdvancedDefaults()` out of lockstep breaks all
    sixteen themes at once**, which is `P1-09`'s `CI:` line. A key in the first
    and not the second makes `adv[key] || defaults[key]` `undefined`, and
    `setProperty(css, undefined)` leaves the token holding the *string*
    `undefined` — invalid at computed-value time, so every `var(--that, …)`
    site stops falling back rather than falling back. The same hole makes
    `syncAdvancedPickers()` write `undefined` into a colour input, which
    silently reverts to `#000000` and re-arms the bug the comment above
    `syncAdvancedPickers`'s init call describes: the first edit of any advanced
    input then stores every other `#000000` as a real override.

`P1-02`'s row asked whether to wire `accentPrimary` into `ADV_KEYS` or delete
it, and the same question for `accentError`, `sectionAccent` and `toggleBg`.
Measured 2026-08-30, `Law 14`, one decision for the four: **deleted.**

  * `--accent-error`, `--section-accent` and `--toggle-bg` have **zero**
    readers anywhere under `static/`. `create_theme` accepted them, the
    first-paint script wrote them, and nothing has ever read one. There is
    nothing to wire them to;
  * `--accent-primary` has **131** readers and every one is a
    `var(--accent-primary, …)`. **124 of the 130 that carry a fallback resolve
    to the theme's own red** — which is what `--accent` (P1-01) resolves to on
    all sixteen shipped palettes and all eight harmony slots. It was a second
    spelling of `--accent` that no writer maintained. The other six fall back
    to three *different* non-accent colours, which is what a token with no
    agreed meaning looks like, not a second accent;
  * wiring it would have been worse than leaving it. `applyColors()` writes
    every `ADV_KEYS` entry unconditionally, so adding `accentPrimary` would
    **define** `--accent-primary` on every load of every theme, retiring the
    fallback at all 131 sites at once. 124 keep their colour; six change —
    which is the flattening `DECISIONS.md` D-2026-08-26-03 protects the
    sixteen themes from and `P1-01` refused for `--accent`, spelled with a
    different token name.

What each test holds, and why it is a defect if it breaks — nothing below is
a hand-kept list; every set is read out of the file that owns it:

  * **the six sets are one set.** Adding a key to any one of them fails until
    it is added to all, in both directions;
  * **`ADV_KEYS` and `computeAdvancedDefaults()` move in lockstep**, driven
    through the real definitions rather than transcribed;
  * **a theme switch leaves nothing stale.** The real first-paint script writes
    a marker into every advanced key, the real `applyColors()` then switches to
    each of the sixteen themes, and no marker may survive. This is the defect
    itself, not a proxy for it, and it fails on any future key a mirror grows
    alone;
  * **every advanced token a writer can set has a reader.** The generic form of
    what killed three of the four: a key whose CSS variable nothing reads is a
    write into nothing;
  * **the four retired keys are gone from all three files**, and
    `--accent-primary`'s population is re-derived rather than quoted, so the
    "synonym for `--accent`" finding cannot quietly stop being true;
  * **`src/` is the same set, not a bounded gap** (`B21`, 2026-09-14). It used
    to be four more copies — an `adv_keys` set and the usage error string in
    `ai_interaction.py`, an `adv_keys` list and the `create_theme` JSON schema
    in `tool_schemas.py` — agreeing with each other at 16 keys and with the
    front end at neither end: they accepted `accentPrimary`, `accentError`,
    `sectionAccent` and `toggleBg`, which no writer writes, and lacked
    `brandMixTo` and `hamburgerColor`, which the editor offers. All four derive
    from `src/theme_advanced_keys.py`, which parses `ADV_KEYS` out of
    `static/js/theme.js`, and each is still measured separately here — by
    running it — because a half-applied derivation is the same defect with
    fewer places to look. The old bound also could not see two of the four: it
    matched `adv_keys\\s*=\\s*[\\{\\[]` and the error string and JSON schema had
    no such literal.

Counts were re-derived from the tree on 2026-08-30 and move as it grows; the
tests below re-derive rather than trust them.
"""

import asyncio
import functools
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from src import ai_interaction, theme_advanced_keys, tool_schemas

# One harness — the DOM shim and sandbox builder the JS suites share — and the
# palette-writing-script selector from the closest sibling row, so "the inline
# script that paints the theme" has exactly one definition in the suite.
from test_tool_effect_surfaces_js import _DOM, _make_sandbox  # noqa: E402
from test_accent_token_js import _inline_script  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "static" / "js" / "theme.js"
INDEX = ROOT / "static" / "index.html"
LOGIN = ROOT / "static" / "login.html"
STATIC = ROOT / "static"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The four keys `P1-02` retired. Named once, here, because three separate tests
# have to agree on which four they are.
RETIRED = {
    "accentPrimary": "--accent-primary",
    "accentError": "--accent-error",
    "sectionAccent": "--section-accent",
    "toggleBg": "--toggle-bg",
}

# A colour no palette derives, written into every advanced key so the tokens a
# writer touches are visible by value rather than by name.
MARK = "#0b0c0d"

THEME_NAMES = tuple(
    re.findall(
        r"^\s{2,}(\w+):\s*\{\s*bg:",
        THEME.read_text(encoding="utf-8")[THEME.read_text(encoding="utf-8").index("export const THEMES = {"):],
        re.M,
    )
)


# ── Reading the six sets ────────────────────────────────────────────────────


def _object_literal(text: str, decl: str, where: str) -> dict:
    """`key → CSS variable` for the object literal introduced by `decl`.

    Brace-matched rather than line-matched: `index.html`'s map is one long line
    and `login.html`'s is fifteen, and a regex that handles one mis-reads the
    other into a silently short set.
    """
    assert text.count(decl) == 1, f"{where}: expected one `{decl}`, found {text.count(decl)}"
    brace = text.index("{", text.index(decl))
    depth = 0
    body = None
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                body = text[brace + 1 : i]
                break
    assert body is not None, f"{where}: `{decl}` is not brace-balanced"
    pairs = re.findall(r"(\w+)\s*:\s*'(--[a-z0-9-]+)'", body)
    keys = [k for k, _ in pairs]
    assert len(keys) == len(set(keys)), f"{where}: duplicate key in `{decl}`"
    return dict(pairs)


def _index_map() -> dict:
    return _object_literal(_inline_script(INDEX), "var advMap", "index.html")


def _login_map() -> dict:
    return _object_literal(_inline_script(LOGIN), "var ADV", "login.html")


def _route_favicon_script() -> str:
    """`index.html`'s second favicon writer — the per-route one, which runs on
    the same cold load as the palette script and must reach the same colour."""
    blocks = [
        body
        for body in re.findall(
            r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", INDEX.read_text(encoding="utf-8"), re.S
        )
        if "var SHAPES = {" in body
    ]
    assert len(blocks) == 1, f"expected one per-route favicon script, found {len(blocks)}"
    return blocks[0]


def _picker_ids() -> set:
    return set(re.findall(r'id="adv-(\w+)"', INDEX.read_text(encoding="utf-8")))


def _reset_buttons() -> set:
    return set(re.findall(r'data-reset-adv="(\w+)"', INDEX.read_text(encoding="utf-8")))


# ── Sandbox ─────────────────────────────────────────────────────────────────

_SHIM = """
import { installDom, Node } from './dom.js';
export const document = installDom();
document.documentElement = new Node('html');
// Pinned to 'loading' so `theme.js`'s auto-init defers to a `DOMContentLoaded`
// that never fires; a floating `_initWithSync()` would call `applyColors()`
// itself and hide a broken one.
document.readyState = 'loading';
globalThis.location = { pathname: '/', origin: 'http://test.local' };
globalThis.window.location = globalThis.location;
globalThis.window.matchMedia = () => ({ matches: false });
export const root = document.documentElement;

export function vars() {
  const values = {};
  for (const k of Object.keys(root.style)) {
    if (k.startsWith('--')) values[k] = String(root.style[k]);
  }
  return values;
}

export function seed(theme) {
  if (theme === null) globalThis.localStorage.removeItem('pantheon-theme');
  else globalThis.localStorage.setItem('pantheon-theme', JSON.stringify(theme));
}

// All three favicon writers look the icon up as `link[rel='icon']`, with the
// single quotes the shared shim's attribute matcher does not read. Without a
// link they can find, each one appends a fresh element and the test would be
// measuring element order instead of the colour written.
const _icon = document.head.appendChild(new Node('link'));
_icon.setAttribute('rel', 'icon');
const _query = document.querySelector.bind(document);
document.querySelector = (sel) =>
  /^link\\[rel=['"]icon['"]\\]$/.test(String(sel).trim()) ? _icon : _query(sel);

export function favicon() { return String(_icon.href || ''); }
"""

_STUBS = {
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

# `ADV_KEYS` and `computeAdvancedDefaults()` are module-private and stay that
# way. The sandbox copy gets one appended statement so the tests drive the real
# definitions rather than a transcription; nothing above the line is touched.
_TEST_EXPORTS = "\nexport { ADV_KEYS as _ADV_KEYS, computeAdvancedDefaults as _computeAdvancedDefaults };\n"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """One sandbox holding all three writers, because the stale-token defect is
    only visible when the first-paint script and the module run in the same
    document — which is exactly how they run in a browser."""
    box = _make_sandbox(tmp_path_factory.mktemp("advmirrors"), THEME, _SHIM, _STUBS)
    with (box / THEME.name).open("a", encoding="utf-8") as handle:
        handle.write(_TEST_EXPORTS)
    (box / "index_paint.js").write_text(_inline_script(INDEX))
    (box / "login_paint.js").write_text(_inline_script(LOGIN))
    (box / "index_route_favicon.js").write_text(_route_favicon_script())
    return box


def _run(box: Path, script: str) -> dict:
    entry = box / "case.mjs"
    entry.write_text(textwrap.dedent(script))
    proc = subprocess.run(["node", str(entry)], cwd=box, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


def _base_palette(name: str) -> dict:
    src = THEME.read_text(encoding="utf-8")
    body = src[src.index("export const THEMES = {") :]
    entry = re.search(rf"^\s{{2,}}{name}:\s*\{{(.*?)\}},?\s*$", body, re.M | re.S).group(1)
    return dict(re.findall(r"(\w+)\s*:\s*'(#[0-9a-fA-F]{3,8})'", entry))


def _candidate_keys() -> list:
    """Every name anything in the tree has ever treated as an advanced key.

    Union rather than a list, so a key added to one mirror alone is still
    *offered* to the writers below — otherwise the observed-vs-parsed check
    could not tell "the map does not write it" from "the test never asked".
    """
    return sorted(
        set(_index_map()) | set(_login_map()) | set(_picker_ids()) | set(RETIRED) | set(_src_keys())
    )


def _paint(box: Path, page: str, colors: dict) -> dict:
    """One cold load of `page`'s real first-paint script over a stored theme.

    A process per load, not a second `import()`: these scripts are evaluated
    once for their side effects, and node's module cache hands the second call
    the already-run module, which reads as "the script wrote nothing".
    """
    return _run(
        box,
        f"""
        import {{ seed, vars }} from './shim.js';
        seed({json.dumps({"name": "dark", "colors": colors})});
        await import('./{page}_paint.js');
        console.log(JSON.stringify(vars()));
        """,
    )


def _observed(box: Path, page: str) -> set:
    """The CSS variables `page`'s real first-paint script writes for advanced
    overrides — measured as a difference against the same palette with no
    `advanced` at all, so core and syntax tokens cannot be miscounted."""
    palette = _base_palette("dark")
    plain = _paint(box, page, palette)
    marked = _paint(box, page, dict(palette, advanced={k: MARK for k in _candidate_keys()}))
    return {name for name, value in marked.items() if value == MARK and plain.get(name) != MARK}


@pytest.fixture(scope="module")
def adv_keys(sandbox) -> dict:
    out = _run(
        sandbox,
        """
        import './shim.js';
        const tm = await import('./theme.js');
        console.log(JSON.stringify({
          keys: tm._ADV_KEYS.map((e) => e.key),
          css: tm._ADV_KEYS.map((e) => e.css),
          labels: tm._ADV_KEYS.map((e) => e.label),
          groups: tm._ADV_KEYS.map((e) => e.group),
          defaults: Object.keys(tm._computeAdvancedDefaults(tm.THEMES.dark)),
        }));
        """,
    )
    assert len(out["keys"]) == len(set(out["keys"])), "ADV_KEYS has a duplicate key"
    return out


# ── The lockstep, and the six sets ──────────────────────────────────────────


def test_adv_keys_and_computed_defaults_move_in_lockstep(adv_keys):
    """`P1-09`'s `CI:` line. A key in one and not the other resolves to
    `undefined` through `adv[key] || defaults[key]`, and `setProperty` then
    parks the *string* `undefined` on the token — every `var(--that, …)` site
    stops falling back, on all sixteen themes at once.
    """
    assert sorted(adv_keys["keys"]) == sorted(adv_keys["defaults"]), (
        "ADV_KEYS and computeAdvancedDefaults() have drifted: "
        f"{sorted(set(adv_keys['keys']) ^ set(adv_keys['defaults']))}"
    )


def test_the_lockstep_holds_by_value_on_all_sixteen_themes(sandbox, adv_keys):
    """Names agreeing is not the whole of it — a default that computes to
    nothing is the same failure with a matching key. Every theme, every key."""
    out = _run(
        sandbox,
        """
        import './shim.js';
        const tm = await import('./theme.js');
        const bad = {};
        for (const [name, colors] of Object.entries(tm.THEMES)) {
          const d = tm._computeAdvancedDefaults(colors);
          for (const { key } of tm._ADV_KEYS) {
            if (!/^#[0-9a-fA-F]{6}$/.test(String(d[key] || ''))) (bad[name] = bad[name] || []).push(key);
          }
        }
        console.log(JSON.stringify({ bad, themes: Object.keys(tm.THEMES).length }));
        """,
    )
    assert out["themes"] >= 16, f"expected the sixteen shipped palettes, got {out['themes']}"
    assert out["bad"] == {}, f"computeAdvancedDefaults() returns no usable colour for {out['bad']}"


def test_every_mirror_of_the_advanced_keys_describes_the_same_theme(sandbox, adv_keys):
    """`B21`. Six sets, one theme object. Adding a key to any one of them fails
    here until it is added to all — and so does dropping one.
    """
    authority = dict(zip(adv_keys["keys"], adv_keys["css"]))

    sets = {
        "theme.js ADV_KEYS": authority,
        "index.html advMap": _index_map(),
        "login.html ADV": _login_map(),
    }
    for label, mapping in sets.items():
        assert mapping == authority, (
            f"`{label}` and `ADV_KEYS` disagree about what a theme is — "
            f"only in {label}: {sorted(set(mapping) - set(authority))}; "
            f"only in ADV_KEYS: {sorted(set(authority) - set(mapping))}; "
            f"mapped to a different variable: "
            f"{sorted(k for k in set(mapping) & set(authority) if mapping[k] != authority[k])}"
        )

    # The editor markup is the fourth and fifth mirror: every loop over
    # `ADV_KEYS` reaches its input as `getElementById('adv-' + key)`, and a
    # picker with no key is unreachable while a key with no picker is skipped.
    assert _picker_ids() == set(authority), (
        "index.html's `adv-…` colour inputs and ADV_KEYS disagree: "
        f"{sorted(_picker_ids() ^ set(authority))}"
    )
    assert _reset_buttons() == set(authority), (
        "index.html's `data-reset-adv` buttons and ADV_KEYS disagree: "
        f"{sorted(_reset_buttons() ^ set(authority))}"
    )

    # Read back through the real scripts, not just the literals: this is what
    # actually reaches `documentElement.style`, and it also proves the two
    # brace-matched parses above are complete.
    for page, mapping in (("index", _index_map()), ("login", _login_map())):
        assert _observed(sandbox, page) == set(mapping.values()), (
            f"{page}.html's first-paint script writes "
            f"{sorted(_observed(sandbox, page))}, but its map reads "
            f"{sorted(set(mapping.values()))}"
        )


def test_the_zone_highlighter_describes_only_rows_that_exist(adv_keys):
    """`_THEME_ZONE_MAP` is keyed by input id, so an `adv-` entry for a key
    `ADV_KEYS` lacks points at a row that is never rendered. A subset, not an
    equality: a key with no entry simply gets no hover highlight.
    """
    zone = set(re.findall(r"'adv-(\w+)'\s*:", THEME.read_text(encoding="utf-8")))
    assert zone <= set(adv_keys["keys"]), (
        "_THEME_ZONE_MAP highlights colour rows that do not exist: "
        f"{sorted(zone - set(adv_keys['keys']))}"
    )


# ── The defect itself ───────────────────────────────────────────────────────


@pytest.mark.parametrize("switch_to", THEME_NAMES)
def test_a_theme_switch_leaves_no_advanced_token_behind(sandbox, switch_to):
    """`P1-02`, driven end to end through both real writers.

    The first-paint script writes a marker into every advanced key it knows;
    `applyColors()` then switches theme. Any marker still standing is a token
    whose value belongs to a theme the user has left, and which nothing will
    ever update or clear again.
    """
    palette = dict(_base_palette("dark"), advanced={k: MARK for k in _candidate_keys()})
    out = _run(
        sandbox,
        f"""
        import {{ seed, vars }} from './shim.js';
        seed({json.dumps({"name": "dark", "colors": palette})});
        await import('./index_paint.js');
        const painted = vars();
        const tm = await import('./theme.js');
        tm.applyColors(tm.THEMES[{json.dumps(switch_to)}]);
        console.log(JSON.stringify({{ painted, after: vars() }}));
        """,
    )
    assert MARK in out["painted"].values(), (
        "the first-paint script wrote no advanced override at all — this test "
        "is measuring nothing; check that the seeded palette still matches "
        "what the script reads"
    )
    stale = sorted(name for name, value in out["after"].items() if value == MARK)
    assert not stale, (
        f"switching to `{switch_to}` left {stale} holding the previous theme's "
        "value. `applyColors()` only walks ADV_KEYS, so a token written at "
        "first paint and absent from that list is never updated or cleared."
    )


# ── The four retired keys ───────────────────────────────────────────────────


def test_the_four_retired_keys_are_gone_from_every_writer():
    """`Law 14`, one decision for the four. Named by CSS variable as well as by
    key, because a mirror can reintroduce either half alone — and allowed to
    survive only on comment lines, which is where the record of why they went
    lives.
    """
    for path in (THEME, INDEX, LOGIN):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            hits = [n for n in (*RETIRED, *RETIRED.values()) if n in line]
            if not hits:
                continue
            assert line.lstrip().startswith(("//", "*", "/*", "<!--")), (
                f"{path.name}:{number} names the retired {hits} in code: {line.strip()[:110]}"
            )


def test_every_advanced_token_a_writer_can_set_has_a_reader(adv_keys):
    """The generic form of what retired three of the four: `--accent-error`,
    `--section-accent` and `--toggle-bg` had no reader anywhere under
    `static/`. A token nothing reads is a write into nothing, and it cannot be
    "wired properly" because there is nothing on the other end.
    """
    readable = [
        path
        for path in STATIC.rglob("*")
        if path.is_file() and path.suffix in {".css", ".js", ".html"}
    ]
    corpus = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in readable)
    orphans = [css for css in adv_keys["css"] if f"var({css}" not in corpus]
    assert not orphans, f"nothing under static/ reads {orphans}, so writing them does nothing"

    for css in RETIRED.values():
        if css == "--accent-primary":
            continue  # has readers; retired on the evidence in the test below
        assert f"var({css}" not in corpus, (
            f"`{css}` grew a reader — it was retired as a write-only token, so "
            "re-derive whether it should be an ADV_KEYS entry after all"
        )


def test_accent_primary_is_still_a_second_spelling_of_the_accent():
    """The evidence that chose deletion over wiring, re-derived.

    Every remaining use carries a fallback, and the overwhelming majority of
    those fallbacks reach the theme's own red — which is what `--accent`
    resolves to on all sixteen palettes. If that stops being true, the token
    has acquired a meaning of its own and the decision is worth re-taking.
    """
    uses = _token_uses("--accent-primary")
    assert uses, "no `var(--accent-primary, …)` sites left at all — retire this test with the sweep"

    dead = [f"{f}:{n}" for f, n, fb, _ in uses if fb is None and not _]
    assert not dead, (
        f"{dead} reach `--accent-primary` with no fallback and nothing defines "
        "it, so they paint nothing. That is the failure `P1-01` fixed at the "
        "session rename input and `sessions.js` fixed at '+ New Folder'."
    )

    to_red = [u for u in uses if u[2] and re.search(r"var\(\s*--(red|accent)\b", u[2])]
    assert len(to_red) >= len(uses) * 0.9, (
        f"only {len(to_red)} of {len(uses)} `--accent-primary` uses still fall "
        "back to the theme's accent or red; it is no longer a synonym for "
        "`--accent` and the P1-02 decision needs re-taking"
    )


def _token_uses(token: str):
    """`(file, line, immediate fallback, is-itself-a-fallback)` per consuming site.

    Brace/paren-matched rather than regexed: three of these sites are nested
    inside a `var(--accent, …)` and a flat pattern reads them backwards.
    """
    out = []
    for path in sorted(STATIC.rglob("*")):
        if not path.is_file() or path.suffix not in {".css", ".js", ".html"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix == ".css":
            text = re.sub(
                r"/\*.*?\*/",
                lambda m: "".join(" " if c != "\n" else "\n" for c in m.group(0)),
                text,
                flags=re.S,
            )
        if path.suffix == ".js":
            text = re.sub(r"^\s*//.*$", lambda m: " " * len(m.group(0)), text, flags=re.M)
        i = 0
        while (j := text.find(token, i)) >= 0:
            i = j + len(token)
            k = text.rfind("var(", 0, j)
            if k < 0 or text[k + 4 : j].strip():
                continue  # a key in a writer's map, not a `var()` head
            depth, end = 0, None
            for p in range(k, len(text)):
                if text[p] == "(":
                    depth += 1
                elif text[p] == ")":
                    depth -= 1
                    if depth == 0:
                        end = p
                        break
            inner = text[k + 4 : end]
            fallback = inner.split(",", 1)[1].strip() if "," in inner else None
            nested = text.rfind("var(", 0, k) >= 0 and text[:k].rstrip().endswith(",")
            out.append((path.relative_to(ROOT).as_posix(), text[:j].count("\n") + 1, fallback, nested))
    return out


# ── What `src/` still accepts ───────────────────────────────────────────────


def _ui(command: str) -> dict:
    return asyncio.run(ai_interaction.do_ui_control(command))


def _create(tail: str = "") -> dict:
    """One real `create_theme` call over a fixed base palette."""
    return _ui(f"create_theme probe #000000 #ffffff #111111 #222222 #ff00ff {tail}".strip())


def _schema_color_properties() -> dict:
    """The `colors` properties block of the shipped `create_theme` schema."""
    tools = [s for s in tool_schemas.FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "ui_control"]
    assert len(tools) == 1, f"expected one ui_control schema, found {len(tools)}"
    return tools[0]["function"]["parameters"]["properties"]["colors"]["properties"]


def _schema_keys() -> set:
    return set(_schema_color_properties()) - set(theme_advanced_keys.BASE_COLOR_KEYS)


def _usage_error_keys() -> set:
    """The keys the usage error names — the list the model is handed when it
    gets the call wrong, and one of the two sites the old regex could not see."""
    err = _ui("create_theme too-few-args").get("error", "")
    named = re.search(r"advanced color key=value pairs \(([^)]*)\)", err)
    assert named, f"the usage error no longer names the advanced keys: {err[:200]}"
    return {k.strip() for k in named.group(1).split(",") if k.strip()}


def _accepted_keys(probe: set) -> set:
    """The keys a real `create_theme` call lands in `colors.advanced`.

    Driven rather than parsed: the acceptance test is `is_advanced_key(ak)` in
    a loop whose branches also claim `bgPattern` and friends, and only running
    it says which name reaches which branch.
    """
    landed = set()
    for key in sorted(probe):
        out = _create(f"{key}={MARK}")
        if out.get("colors", {}).get("advanced", {}).get(key) == MARK:
            landed.add(key)
    return landed


@functools.lru_cache(maxsize=1)
def _src_keys() -> frozenset:
    """The advanced keys `src/` describes — all four sites, driven not grepped.

    `B21` found this helper matching `adv_keys\\s*=\\s*[\\{\\[]` and therefore
    reading two of the four: the usage error string and the `create_theme` JSON
    schema were invisible to it, and both had drifted with the literals. All
    four derive from `src/theme_advanced_keys.py` now, which parses `ADV_KEYS`
    out of `static/js/theme.js` — the file `applyColors()` walks. They are still
    measured one by one, because a half-applied derivation leaves exactly the
    same defect with fewer places to look.
    """
    sets = {
        "src/theme_advanced_keys.py ADVANCED_KEYS": set(theme_advanced_keys.ADVANCED_KEY_NAMES),
        "create_theme's JSON schema": _schema_keys(),
        "create_theme's usage error": _usage_error_keys(),
    }
    # Probe with every name any writer, mirror or retired list has ever used, so
    # "the loop rejects it" is distinguishable from "the test never asked".
    probe = set().union(*sets.values()) | set(RETIRED) | _picker_ids()
    sets["the keys do_ui_control lands"] = _accepted_keys(probe)

    reference = sets["src/theme_advanced_keys.py ADVANCED_KEYS"]
    for label, keys in sets.items():
        assert keys == reference, (
            f"`{label}` and the derived ADVANCED_KEYS disagree — "
            f"only in {label}: {sorted(keys - reference)}; "
            f"only in ADVANCED_KEYS: {sorted(reference - keys)}"
        )
    return frozenset(reference)


def test_src_and_the_front_end_describe_one_set(adv_keys):
    """`B21`, and it is an equality now rather than a bound.

    It used to allow the gap to shrink but not grow, because `src/` was not
    that batch's to edit: `create_theme` accepted `accentPrimary`, `accentError`,
    `sectionAccent` and `toggleBg` — four keys no writer under `static/` writes,
    validated into the user's stored theme and counted in "with N advanced
    overrides" — and could not set `brandMixTo` or `hamburgerColor`, which the
    editor offers. Measured 2026-09-14 the four `src/` sites still carried 16
    keys against the front end's 14, wrong at both ends.

    `src/theme_advanced_keys.py` reads `ADV_KEYS` out of `static/js/theme.js`
    rather than restating it, so this equality is what a broken parse looks like
    as well as what drift looks like — which is why there is no fallback list
    behind the parse for it to pass on.
    """
    front = set(adv_keys["keys"])
    src = set(_src_keys())
    assert src == front, (
        "`create_theme` and the theme editor disagree about what a theme is — "
        f"only src/: {sorted(src - front)}; only ADV_KEYS: {sorted(front - src)}"
    )
    assert src, "no advanced keys parsed at all — ADV_KEYS in theme.js is unreadable to src/"


def test_the_model_is_told_each_key_by_its_editor_row_label(adv_keys):
    """The schema descriptions were hand-written prose and had drifted with the
    keys — `sectionAccent` was still documented as "Section header accent
    color" for a row that no longer exists. They come from `ADV_KEYS`'s own
    `label` and `group` now, so the name the model is given and the name the
    person reads above the colour input are the same string. The labels here
    come out of node evaluating the module; the schema's come out of `src/`
    parsing it, so agreeing means the parse read the whole entry.
    """
    properties = _schema_color_properties()
    for key, label, group in zip(adv_keys["keys"], adv_keys["labels"], adv_keys["groups"]):
        description = properties[key]["description"]
        assert label in description, f"`{key}` is described as {description!r}, not as `{label}`"
        assert group in description, f"`{key}` is described as {description!r}, not under `{group}`"


def test_the_native_call_converter_is_not_a_fifth_copy():
    """The fourth `src/` site was a filter, and a filter is a copy.

    `function_call_to_tool_block` held its own `adv_keys` list and appended only
    colours on it, so a key the list lacked was dropped between the model's
    arguments and `do_ui_control` — the same silent drop as the missing `else`,
    one layer up, where no error could ever be raised because the key was gone
    before anything validated it. It forwards every non-positional colour now,
    known or not, leaving `do_ui_control` as the one validator.
    """
    base = {"bg": "#000000", "fg": "#ffffff", "panel": "#111111", "border": "#222222", "accent": "#ff00ff"}
    for probe in ("brandMixTo", "hamburgerColor", "accentPrimary", "notAKeyAtAll"):
        block = tool_schemas.function_call_to_tool_block(
            "ui_control",
            json.dumps({"action": "create_theme", "name": "probe", "colors": dict(base, **{probe: MARK})}),
        )
        assert f"{probe}={MARK}" in block.content, (
            f"the converter dropped `{probe}` before any validator saw it: {block.content}"
        )
        out = asyncio.run(ai_interaction.do_ui_control(block.content))
        if probe in _src_keys():
            assert out.get("colors", {}).get("advanced", {}).get(probe) == MARK, out
        else:
            assert "error" in out and probe in out["error"], (
                f"`{probe}` reached do_ui_control and was neither applied nor refused: {out}"
            )


def test_the_retired_four_are_refused_by_every_src_surface():
    """`P1-02` deleted them from the front end; they lived on here as a dead
    parameter — accepted, stored, exported, and counted. The schema no longer
    offers them, the usage error no longer names them, and a call that asks for
    one fails instead of reporting an override that nothing will paint.
    """
    for key in RETIRED:
        assert key not in _schema_keys(), f"`{key}` is still advertised to the model"
        assert key not in _usage_error_keys(), f"the usage error still names `{key}`"
        out = _create(f"{key}={MARK}")
        assert "error" in out, f"`{key}` was accepted: {out}"
        assert "advanced" not in out.get("colors", {}), f"`{key}` still reached a stored theme: {out}"


# ── The favicon ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", THEME_NAMES)
def test_the_favicon_follows_the_accent_and_no_shipped_theme_moves(sandbox, name):
    """`B21`'s one-liner. `applyColors()` took `colors.red` under a comment
    reading "match theme accent color"; the two were the same value for every
    theme until `P1-01` made the accent separately settable. No shipped palette
    carries an `accent` key, so this is a no-op on all sixteen — which is the
    half that has to be shown, not the half that changed.
    """
    out = _run(
        sandbox,
        f"""
        import {{ favicon }} from './shim.js';
        const tm = await import('./theme.js');
        const colors = tm.THEMES[{json.dumps(name)}];
        tm.applyColors(colors);
        const plain = favicon();
        tm.applyColors({{ ...colors, accent: '#123456' }});
        console.log(JSON.stringify({{ plain, accented: favicon(), red: colors.red }}));
        """,
    )
    assert out["plain"].count(out["red"].replace("#", "%23")) >= 1, (
        f"{name}'s favicon is not drawn in its own colour: {out['plain'][:120]}"
    )
    assert "%23123456" in out["accented"], (
        f"{name} with an explicit accent still draws a {out['red']} favicon — "
        "an accent-coloured UI and a red boat"
    )


@pytest.mark.parametrize("script,path", [("index_paint", "/"), ("index_route_favicon", "/calendar")])
def test_the_first_paint_favicons_reach_the_same_colour_as_the_module(sandbox, script, path):
    """Both favicon writers in `index.html` run on a cold load, before the
    module exists. If either still reads `red` alone, a theme carrying its own
    accent paints one colour and repaints in another the moment `theme.js`
    boots. Driven, because both are wrapped in a `try {} catch(e){}` that would
    swallow a broken one and leave a substring check reading as green.
    """
    palette = dict(_base_palette("dark"), accent="#123456")
    out = _run(
        sandbox,
        f"""
        import {{ seed, favicon }} from './shim.js';
        globalThis.location.pathname = {json.dumps(path)};
        seed({json.dumps({"name": "dark", "colors": palette})});
        await import('./{script}.js');
        console.log(JSON.stringify({{ href: favicon(), red: {json.dumps(palette["red"])} }}));
        """,
    )
    assert out["href"], f"{script} wrote no favicon at all on `{path}`"
    assert "%23123456" in out["href"], (
        f"{script} draws the theme's red rather than its accent: {out['href'][:140]}"
    )
    assert out["red"].replace("#", "%23") not in out["href"], (
        f"{script} still carries the red alongside the accent: {out['href'][:140]}"
    )
