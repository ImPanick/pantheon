# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-03` — the three resize handles, and the two that were mouse-only.

**Two premises corrected, both dated.**

*(1) `Depends: P1-01` is no longer a block.* `P1-01` landed on 2026-08-30 and
is ticked. With `--accent` defined per theme, `.sidebar-resize-handle:hover`
and `.rail-resize-handle:hover` — which spell a **bare** `var(--accent)` and
were two of that row's "204 sites that paint nothing today" — resolve and
paint. So the half of this row that read *"they are invisible because their
entire treatment routes through the accent token"* was already delivered by
somebody else. What was left is the other half, and it is the half the row is
actually named after: **they are mouse-only.** No tabindex, no role, no key
binding, no announced value.

*(2) `#settings-sidebar-resize-handle` is the template, and it really is done.*
`role="separator"`, `aria-orientation`, `aria-label`, all three `aria-value*`,
`tabindex="0"`, ArrowLeft/ArrowRight to resize and Enter/Space to collapse, in
`static/js/settings/sidebar.js`. This row copies it onto the other two rather
than inventing a fourth treatment (`Law 14`).

One thing the template could not answer, because the settings navigation only
ever sits on the left: **the arrows move the separator, not the width.** The
main sidebar and the icon rail can both be moved to the right of the window
(`.right-side`, which the existing drag handler already reads), and there
"wider" is to the LEFT. Binding ArrowRight to "wider" unconditionally would
have been the literal copy and backwards half the time, so what is bound is
the direction the edge visibly moves — and that is what this file drives.

Driven under node against the real `static/js/init.js`, in the sandbox pattern
`tests/test_tool_effect_surfaces_js.py` owns. `init.js` is a top-level script
module that wires a dozen unrelated things on import, so the shim below builds
only what it reaches for and patches the three browser APIs the shared DOM
does not carry — `getBoundingClientRect`, `getComputedStyle` and a window-level
`addEventListener` — **in this sandbox and not in the shared shim**, because a
measurement that changes the instrument changes every other test that uses it.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _DOM, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INIT_JS = ROOT / "static" / "js" / "init.js"
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_HANDLES = {
    "sidebar-resize-handle": "Resize sidebar",
    "rail-resize-handle": "Expand sidebar",
}
_TEMPLATE = "settings-sidebar-resize-handle"


def _attrs(element_id: str) -> dict:
    """Every attribute on the element with this id, from the shipped markup."""
    m = re.search(rf"<[a-z]+\b([^>]*\bid=\"{re.escape(element_id)}\"[^>]*)>", INDEX)
    assert m, f"#{element_id} is not in static/index.html"
    return dict(re.findall(r'([a-zA-Z-]+)="([^"]*)"', m.group(1)))


# ── the markup half, against the template ──────────────────────────────────


def test_all_three_handles_carry_the_same_treatment():
    """The template's own attribute set, read off the template rather than
    listed here — so a change to the one that shipped done propagates to the
    two that copied it instead of silently diverging from them."""
    template = _attrs(_TEMPLATE)
    wanted = {
        k: v for k, v in template.items()
        if k in {"role", "aria-orientation", "tabindex"}
    }
    assert wanted == {
        "role": "separator",
        "aria-orientation": "vertical",
        "tabindex": "0",
    }, f"the template changed shape: {wanted}"

    for handle, label in _HANDLES.items():
        got = _attrs(handle)
        for key, value in wanted.items():
            assert got.get(key) == value, (
                f"#{handle} has `{key}={got.get(key)!r}`, the template has "
                f"`{key}={value!r}`"
            )
        assert got.get("aria-label") == label, (
            f"#{handle} is announced as {got.get('aria-label')!r}; a separator "
            "with no label is announced as 'separator'"
        )
        for key in ("aria-valuemin", "aria-valuemax", "aria-valuenow"):
            assert key in got, (
                f"#{handle} has no {key}; a focusable separator without a value "
                "range announces nothing when the arrows move it"
            )
        assert int(got["aria-valuemin"]) < int(got["aria-valuemax"])


# ── the behaviour half, driven ─────────────────────────────────────────────

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

// Three browser APIs `init.js` reaches for that the shared shim does not
// carry. Patched on the prototype HERE rather than in `dom.js`: every other
// sandbox imports that file, and a module that currently throws on a missing
// method is a module whose test would silently start taking a different path.
// A browser reflows before it answers `getBoundingClientRect`, so a module
// that writes `style.width` and measures on the next line reads the NEW width.
// Modelling that is not a convenience: without it the aria value trails the
// geometry by one press and the test would pass on a defect instead of
// catching one.
Node.prototype.getBoundingClientRect = function () {
  let w = this._width || 0;
  const px = parseInt(this.style && this.style.width, 10);
  if (!Number.isNaN(px)) w = px;
  if (this._classes().includes('hidden')) w = 0;
  return { width: w, height: 0, top: 0, left: 0, right: w, bottom: 0, x: 0, y: 0 };
};

const html = document.appendChild(new Node('html'));
document.documentElement = html;

globalThis.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
globalThis.window.getComputedStyle = globalThis.getComputedStyle;
globalThis.window.innerHeight = 900;
globalThis.window.innerWidth = 1400;
globalThis.requestAnimationFrame = () => 0;
const _winListeners = {};
globalThis.addEventListener = (t, fn) => { (_winListeners[t] = _winListeners[t] || []).push(fn); };
globalThis.removeEventListener = () => {};
// `init.js` schedules a 1.2s splash fallback at module scope; a real timer
// would keep node alive past the end of the case for no reason.
globalThis.setTimeout = (fn) => { void fn; return 0; };

const IDS = ['icon-rail', 'sidebar'];
for (const id of IDS) {
  const n = document.body.appendChild(new Node('div'));
  n.setAttribute('id', id);
}
export const sidebar = document.getElementById('sidebar');
export const rail = document.getElementById('icon-rail');
sidebar._width = 340;

const HANDLES = __HANDLES__;
export const handles = {};
for (const [id, cls] of Object.entries(HANDLES)) {
  const parent = id.startsWith('rail') ? rail : sidebar;
  const h = parent.appendChild(new Node('div'));
  h.className = cls;
  h.setAttribute('id', id);
  h.setAttribute('tabindex', '0');
  handles[id] = h;
}

export function setWidth(px) {
  sidebar.style.width = px + 'px';
  sidebar._width = px;
  sidebar.classList.remove('hidden');
}

export function setSide(right) {
  if (right) sidebar.classList.add('right-side');
  else sidebar.classList.remove('right-side');
}

export function hide() {
  sidebar.classList.add('hidden');
  sidebar.style.width = '';
  sidebar._width = 0;
}

export function press(handleId, key) {
  const h = handles[handleId];
  let prevented = false;
  h.dispatchEvent({
    type: 'keydown', key, target: h,
    preventDefault() { prevented = true; },
  });
  return prevented;
}

export function state(handleId) {
  return {
    width: sidebar.getBoundingClientRect().width,
    inlineWidth: sidebar.style.width || null,
    hidden: sidebar.className.split(/\s+/).includes('hidden'),
    valueNow: handles[handleId].getAttribute('aria-valuenow'),
    valueMin: handles[handleId].getAttribute('aria-valuemin'),
    valueMax: handles[handleId].getAttribute('aria-valuemax'),
  };
}

export const stored = {};
export const storageStub = {
  KEYS: { SIDEBAR_WIDTH: 'sidebar-width', SIDEBAR_COLLAPSED: 'sidebar-collapsed' },
  get: (k, d) => (k in stored ? stored[k] : d),
  set: (k, v) => { stored[k] = String(v); },
  getJSON: (_k, d) => d,
};
globalThis.__storageStub = storageStub;
"""

_STUBS = {
    "storage.js": "export default globalThis.__storageStub;\n",
}

_PREAMBLE = (
    "import { document, sidebar, rail, handles, setWidth, setSide, hide, press,"
    " state, stored } from './shim.js';\n"
    "await import('./init.js');\n"
)


@pytest.fixture(scope="module")
def init_sandbox(tmp_path_factory):
    shim = _SHIM.replace(
        "__HANDLES__",
        json.dumps({
            "sidebar-resize-handle": "sidebar-resize-handle",
            "rail-resize-handle": "rail-resize-handle",
        }),
    )
    return _make_sandbox(tmp_path_factory.mktemp("resizekeys"), INIT_JS, shim, _STUBS)


def _drive(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _PREAMBLE, script)


def test_the_arrows_resize_the_sidebar(init_sandbox):
    out = _drive(
        """
        setWidth(340);
        press('sidebar-resize-handle', 'ArrowRight');
        const wider = state('sidebar-resize-handle');
        press('sidebar-resize-handle', 'ArrowLeft');
        press('sidebar-resize-handle', 'ArrowLeft');
        const narrower = state('sidebar-resize-handle');
        console.log(JSON.stringify({ wider, narrower }));
        """,
        init_sandbox,
    )
    assert out["wider"]["width"] > 340, (
        "ArrowRight on a left-side sidebar did not widen it: "
        f"{out['wider']}"
    )
    assert out["narrower"]["width"] < out["wider"]["width"], out["narrower"]


def test_the_arrows_follow_the_edge_not_the_word_wider(init_sandbox):
    """The question the template could not answer. On a right-side sidebar the
    separator's `wider` direction is LEFT, and a keyboard user watching the
    edge move has to see it go where they pushed it."""
    out = _drive(
        """
        setSide(true); setWidth(340);
        press('sidebar-resize-handle', 'ArrowLeft');
        const leftOnRightSide = state('sidebar-resize-handle').width;
        setWidth(340);
        press('sidebar-resize-handle', 'ArrowRight');
        const rightOnRightSide = state('sidebar-resize-handle').width;
        setSide(false);
        console.log(JSON.stringify({ leftOnRightSide, rightOnRightSide }));
        """,
        init_sandbox,
    )
    assert out["leftOnRightSide"] > 340, (
        "on a right-side sidebar ArrowLeft must widen — that is the direction "
        f"the edge moves; got {out['leftOnRightSide']}"
    )
    assert out["rightOnRightSide"] < 340, out["rightOnRightSide"]


def test_the_narrowing_arrow_collapses_at_the_minimum(init_sandbox):
    """Without an explicit boundary transition the clamp puts 184px back to
    200px forever and keyboard collapse is unreachable — the trap the settings
    template documents in its own comment."""
    out = _drive(
        """
        setWidth(200);
        press('sidebar-resize-handle', 'ArrowLeft');
        const atMin = state('sidebar-resize-handle');
        console.log(JSON.stringify({ atMin }));
        """,
        init_sandbox,
    )
    assert out["atMin"]["hidden"] is True, (
        f"ArrowLeft at the minimum width left the sidebar open at "
        f"{out['atMin']['width']} — the clamp has swallowed the press"
    )


def test_the_rail_handle_opens_a_collapsed_sidebar(init_sandbox):
    """This handle's whole job: it is the strip you drag to get the sidebar
    back. From a keyboard that has to be one press, not a drag."""
    out = _drive(
        """
        hide();
        const before = state('rail-resize-handle');
        press('rail-resize-handle', 'ArrowRight');
        const afterArrow = state('rail-resize-handle');
        hide();
        press('rail-resize-handle', 'Enter');
        const afterEnter = state('rail-resize-handle');
        console.log(JSON.stringify({ before, afterArrow, afterEnter }));
        """,
        init_sandbox,
    )
    assert out["before"]["hidden"] is True
    assert out["afterArrow"]["hidden"] is False and out["afterArrow"]["width"] >= 200
    assert out["afterEnter"]["hidden"] is False, (
        "Enter on the rail separator must open the sidebar; a separator that "
        "only answers to arrows is a separator most people never find"
    )


def test_enter_toggles_and_space_does_the_same(init_sandbox):
    out = _drive(
        """
        setWidth(340);
        press('sidebar-resize-handle', 'Enter');
        const afterEnter = state('sidebar-resize-handle');
        press('sidebar-resize-handle', ' ');
        const afterSpace = state('sidebar-resize-handle');
        console.log(JSON.stringify({ afterEnter, afterSpace }));
        """,
        init_sandbox,
    )
    assert out["afterEnter"]["hidden"] is True
    assert out["afterSpace"]["hidden"] is False, (
        "Space must do what Enter does — the browser fires both on a focused "
        "control and a person who tries one and not the other is common"
    )


def test_the_announced_value_follows_the_width(init_sandbox):
    """An `aria-valuenow` that never moves is worse than none: it is a number
    a screen reader reads out confidently and it is wrong."""
    out = _drive(
        """
        setWidth(340);
        press('sidebar-resize-handle', 'ArrowRight');
        const after = state('sidebar-resize-handle');
        const railSide = state('rail-resize-handle');
        console.log(JSON.stringify({ after, rail: railSide }));
        """,
        init_sandbox,
    )
    assert int(out["after"]["valueNow"]) == out["after"]["width"], (
        f"announced {out['after']['valueNow']}, actual {out['after']['width']}"
    )
    assert int(out["rail"]["valueNow"]) == out["after"]["width"], (
        "the two handles measure the same sidebar and must agree about it"
    )
    assert int(out["after"]["valueMin"]) == 200
    assert int(out["after"]["valueMax"]) == 700


def test_an_unbound_key_reaches_the_page(init_sandbox):
    out = _drive(
        """
        setWidth(340);
        const prevented = press('sidebar-resize-handle', 'ArrowUp');
        console.log(JSON.stringify({ prevented, width: state('sidebar-resize-handle').width }));
        """,
        init_sandbox,
    )
    assert not out["prevented"] and out["width"] == 340


def test_the_width_a_keyboard_sets_is_the_width_that_persists(init_sandbox):
    """A drag saves; a keypress has to as well, or the sidebar springs back on
    the next load and the keyboard path looks broken rather than unsaved."""
    out = _drive(
        """
        setWidth(340);
        press('sidebar-resize-handle', 'ArrowRight');
        console.log(JSON.stringify({ stored, width: state('sidebar-resize-handle').width }));
        """,
        init_sandbox,
    )
    assert out["stored"].get("sidebar-width") == str(out["width"]), out["stored"]
