# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P3-19` — the seven canvas backgrounds fall back instead of falling over.

The row exists because a competitor's Brain graph *crashed outright* on
machines with hardware acceleration disabled. The graph half of it is moot —
`D-2026-08-26-08` cut the canvas and the force layout — but the canvas half
shipped here: seven full-screen `requestAnimationFrame` animators, one per
background pattern, all opening with the same eight lines::

    document.body.prepend(canvas);
    const ctx = canvas.getContext('2d');
    ...
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);     // two lines later

**`getContext` returns `null` rather than throwing** when 2D canvas is
unavailable — acceleration off, a hardened profile, a device out of video
memory — so `setTransform` threw a TypeError out of `_initSynapse`, out of
`applyBgPattern`, out of `applyTheme`, and **the theme did not apply at all**.
Not a missing background: a missing theme.

These tests run the real `applyBgPattern` under `node` against a DOM whose
canvas refuses a context, and check the outcome the row asks for — the
`bg-pattern-*` class stays on the body, so the pattern degrades to its static
styling; nothing throws; and no half-built canvas is left covering the page.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _DOM, _make_sandbox  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
_THEME = _REPO / "static" / "js" / "theme.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# Every canvas pattern in `_CANVAS_PATTERNS`, and the canvas id each one makes.
PATTERNS = ["synapse", "rain", "constellations", "perlin-flow",
            "petals", "sparkles", "embers"]

_SHIM = """
import { installDom, Node } from './dom.js';

export const warnings = [];
export const document = installDom();
document.documentElement = new Node('html');

// The shared shim has no `prepend`; the animators use it to put the canvas
// behind everything else.
Node.prototype.prepend = function (node) {
  node.parentNode = this;
  this.childNodes.unshift(node);
  return node;
};

// How the browser answers `getContext`, set per case.
export const canvasBehaviour = { mode: 'ok' };

const realCreate = document.createElement;
document.createElement = (tag) => {
  const el = realCreate(tag);
  if (String(tag).toLowerCase() === 'canvas') {
    el.getContext = () => {
      if (canvasBehaviour.mode === 'null') return null;
      if (canvasBehaviour.mode === 'throw') throw new Error('canvas is disabled');
      // A context that answers every call, because the animators chain:
      // `ctx.createLinearGradient(...).addColorStop(...)`. Every method hands
      // back another one of these, and the handful of properties read as
      // numbers read as 0. The exception is the 'broken' case, where the first
      // real call fails — an animator that gets a context and then hits a wall
      // must not take the theme down either.
      const NUMERIC = new Set(['width', 'height', 'actualBoundingBoxAscent',
                               'actualBoundingBoxDescent', 'length']);
      const fake = () => new Proxy({}, {
        get(_t, prop) {
          if (NUMERIC.has(prop)) return 0;
          if (prop === Symbol.toPrimitive) return () => 0;
          if (canvasBehaviour.mode === 'broken' && prop === 'setTransform') {
            return () => { throw new Error('software rasteriser gave up'); };
          }
          return () => fake();
        },
        set() { return true; },
      });
      return fake();
    };
  }
  return el;
};

globalThis.window = globalThis;
globalThis.innerWidth = 1400;
globalThis.innerHeight = 900;
globalThis.devicePixelRatio = 1;
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.console = { ...console, warn: (...a) => { warnings.push(a.map(String).join(' ')); } };

export function bodyState() {
  return {
    classes: String(document.body.className || '').split(/\\s+/).filter(Boolean),
    canvases: document.body.childNodes
      .filter((n) => n.tagName === 'CANVAS')
      .map((n) => n.id),
  };
}
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
    "color/hex.js": "export function hexToRgb() { return null; }\n",
    "windowDrag.js": "export function makeWindowDraggable() {}\n",
    "tileManager.js": "export function snapModalToZone() {}\n",
    # The real one reads `matchMedia`; the point of these tests is the canvas,
    # so motion is pinned off and P1-12 owns the reduced-motion path.
    "motion.js": (
        "export function prefersReducedMotion() { return false; }\n"
        "export function scrollBehavior() { return 'smooth'; }\n"
        "export function onMotionPreferenceChange() {}\n"
    ),
}


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("bgcanvas"), _THEME, _SHIM, _STUBS)


def _apply(sandbox: Path, pattern: str, mode: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(textwrap.dedent(f"""
        import {{ bodyState, canvasBehaviour, warnings }} from './shim.js';
        const tm = await import('./theme.js');
        canvasBehaviour.mode = {mode!r};
        let threw = null;
        try {{ tm.applyBgPattern({pattern!r}); }} catch (e) {{ threw = String(e && e.message || e); }}
        console.log(JSON.stringify({{ ...bodyState(), threw, warnings }}));
    """), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"node produced no stdout\n{proc.stderr}"
    return json.loads(lines[-1])


@pytest.mark.parametrize("pattern", PATTERNS)
def test_a_working_canvas_still_gets_its_animator(sandbox, pattern):
    # The control. Without it every assertion below would also pass on a
    # `applyBgPattern` that had stopped creating canvases at all.
    out = _apply(sandbox, pattern, "ok")
    assert out["threw"] is None
    assert out["canvases"] == [f"{pattern}-canvas"]
    assert f"bg-pattern-{pattern}" in out["classes"]


@pytest.mark.parametrize("pattern", PATTERNS)
def test_a_browser_that_refuses_a_context_gets_the_static_pattern(sandbox, pattern):
    # `getContext` returning null is the real-world case: it does not throw, so
    # nothing before this row noticed until the *next* line dereferenced it.
    out = _apply(sandbox, pattern, "null")
    assert out["threw"] is None, "a refused canvas context took the whole theme down"
    assert f"bg-pattern-{pattern}" in out["classes"], (
        "the class is what makes this a *degraded* background rather than none"
    )
    assert out["canvases"] == [], "an unusable canvas was left covering the page"
    assert any("static" in w for w in out["warnings"]), (
        "silently doing nothing is how this stayed unnoticed; say it out loud"
    )


@pytest.mark.parametrize("mode, said", [
    # `getContext` throwing is the browser refusing, the same event as it
    # returning null, and it is reported that way — a person reading the
    # console learns their browser has no canvas, not that this one pattern is
    # buggy. A failure *after* a context was handed over is the other message.
    ("throw", "no 2D canvas context"),
    ("broken", "could not start"),
])
def test_an_animator_that_fails_anyway_does_not_take_the_theme_with_it(sandbox, mode, said):
    # Two ways past the null check: `getContext` itself throwing, and a context
    # that hands back an object whose first real call fails. Neither may escape
    # `applyBgPattern` — everything after that line in `applyTheme` still has to
    # run, and the class is already applied.
    out = _apply(sandbox, "synapse", mode)
    assert out["threw"] is None
    assert "bg-pattern-synapse" in out["classes"]
    assert out["canvases"] == []
    assert any(said in w for w in out["warnings"]), (
        f"expected the {mode} case to be reported as {said!r}, got {out['warnings']}"
    )


def test_reduced_motion_stops_the_animator_and_keeps_the_theme(tmp_path_factory):
    # `P1-12`'s claim, executed. `test_reduced_motion_guard.py` used to pin the
    # exact source line that implements it, which failed the day `P3-19` wrapped
    # that line in a try/catch — working code, failing test. The behaviour is
    # what matters: no canvas starts, and the person keeps their theme.
    stubs = dict(_STUBS)
    stubs["motion.js"] = (
        "export function prefersReducedMotion() { return true; }\n"
        "export function scrollBehavior() { return 'auto'; }\n"
        "export function onMotionPreferenceChange() {}\n"
    )
    still = _make_sandbox(tmp_path_factory.mktemp("bgcanvasstill"), _THEME, _SHIM, stubs)
    out = _apply(still, "synapse", "ok")
    assert out["threw"] is None
    assert out["canvases"] == [], "reduced motion must stop the animator"
    assert "bg-pattern-synapse" in out["classes"], (
        "reduced motion stops the motion; it does not take the theme away"
    )


def test_switching_away_from_a_pattern_clears_its_canvas(sandbox):
    entry = sandbox / "switch.mjs"
    entry.write_text(textwrap.dedent("""
        import { bodyState, canvasBehaviour } from './shim.js';
        const tm = await import('./theme.js');
        canvasBehaviour.mode = 'ok';
        tm.applyBgPattern('rain');
        const withRain = bodyState();
        tm.applyBgPattern('none');
        console.log(JSON.stringify({ withRain, after: bodyState() }));
    """), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])
    assert out["withRain"]["canvases"] == ["rain-canvas"]
    assert out["after"]["canvases"] == []
    assert out["after"]["classes"] == []


def test_no_animator_reaches_a_context_without_checking_it():
    # The rule behind the cases above, so an eighth pattern added later cannot
    # reintroduce the shape by copying one of the seven.
    src = _THEME.read_text(encoding="utf-8")
    assert src.count("_bgCanvas(") == len(PATTERNS) + 1, (
        "every animator must take its canvas from the one guarded helper "
        f"(expected {len(PATTERNS)} calls and 1 definition)"
    )
    # From the helper's doc comment, not from its `function` line: the comment
    # quotes `canvas.getContext('2d')` to explain the defect, and slicing below
    # it would leave that quotation in "outside" and fail the last assertion on
    # its own prose. `Law 20` — the file is not the code.
    start = src.rindex("/**", 0, src.index("function _bgCanvas("))
    body = src[start:src.index("\nfunction _initSynapse")]
    assert "if (!ctx)" in body, "the helper stopped checking the context it returns"
    # And nobody may go around it.
    outside = src.replace(body, "")
    assert "canvas.getContext(" not in outside, (
        "an animator reaches getContext directly again; route it through _bgCanvas"
    )
