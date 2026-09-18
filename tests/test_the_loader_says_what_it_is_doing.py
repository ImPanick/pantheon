# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-07` — the boot loader: a stage line, no `innerHTML` per frame, and a
reduced-motion guard. **The wave is kept.**

Three defects in nine lines of inline script, and the first one is the reason
the other two are worth fixing rather than deleting:

  * **Boot was silent.** Three bars bobbed and nothing said what was being
    waited for. A cold load and a load that is about to fail after five
    seconds looked identical, which is a `Law 15` surface — the thing on
    screen cannot tell you what it is doing or what to do next;
  * **`innerHTML` per frame.** `el.innerHTML = '<span style="…">•</span><span>▁▂▃</span>'`
    ran every 150ms — about seven times a second, on the critical path of a
    cold boot, re-parsing a string of markup and rebuilding two elements while
    the module graph is still downloading. Nothing about a frame changes except
    one glyph run and one translate;
  * **No reduced-motion guard.** `P1-12`'s global CSS guard cannot reach a
    `setInterval`, and this script runs before any module, so `motion.js` is
    not loaded yet either. It has to ask `matchMedia` itself.

Driven under node against the **real script extracted from the shipped
`static/index.html`**, in the sandbox pattern
`tests/test_tool_effect_surfaces_js.py` owns. Extracting it is what makes this
`Law 20` option 1 rather than option 3: the bytes the browser runs are the
bytes the test runs, and a comment about `innerHTML` cannot be mistaken for a
use of it.

The `innerHTML` assertion is made the way `describeCard` makes its own in that
file: the shim's node records the RAW string behind an `innerHTML` assignment
separately from its text, and reading it back through `textContent` would strip
the tags and make the two spellings indistinguishable. Refutation has already
shipped exactly that mutation past a full green run once in this repo, which is
why the property is read and not the text.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _DOM, _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
STARTUP_SHELL = ROOT / "static" / "js" / "startupShell.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _loader_script() -> str:
    """The inline bootstrap that owns the loader, out of the shipped page."""
    start = INDEX.index('<div id="app-loader"')
    open_tag = INDEX.index("<script>", start)
    close = INDEX.index("</script>", open_tag)
    body = INDEX[open_tag + len("<script>"): close]
    assert "loader-wave" in body, "the loader's inline script moved"
    return body


def _loader_markup() -> str:
    start = INDEX.index('<div id="app-loader"')
    return INDEX[start: INDEX.index("<script>", start)]


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

/** A clock we pump by hand. `installDom` wraps setInterval to unref it; the
 *  loader's whole behaviour is about WHEN things fire, so both are replaced. */
const intervals = [];
const timeouts = [];
globalThis.setInterval = (fn, ms) => { intervals.push({ fn, ms, live: true }); return intervals.length; };
globalThis.clearInterval = (id) => { if (intervals[id - 1]) intervals[id - 1].live = false; };
globalThis.setTimeout = (fn, ms) => { timeouts.push({ fn, ms, fired: false }); return timeouts.length; };
globalThis.clearTimeout = (id) => { if (timeouts[id - 1]) timeouts[id - 1].fired = true; };

export function tick(n = 1) {
  for (let i = 0; i < n; i++) {
    for (const iv of intervals) if (iv.live) iv.fn();
  }
}
export function liveIntervals() { return intervals.filter((i) => i.live).length; }
export function intervalCount() { return intervals.length; }
/** Fire every timeout whose delay is <= ms and has not fired yet. */
export function advance(ms) {
  for (const t of timeouts) {
    if (!t.fired && t.ms <= ms) { t.fired = true; t.fn(); }
  }
}

export function setReducedMotion(on) {
  globalThis.window.matchMedia = (q) => ({
    matches: on && /prefers-reduced-motion/.test(q),
    media: q,
  });
}

const loader = document.body.appendChild(new Node('div'));
loader.setAttribute('id', 'app-loader');
export const wave = loader.appendChild(new Node('div'));
wave.setAttribute('id', 'loader-wave');
wave.textContent = '▁▂▃';
export const stage = loader.appendChild(new Node('div'));
stage.setAttribute('id', 'loader-stage');
stage.textContent = 'Starting Pantheon…';
export { loader };

export function waveFrame() {
  const kids = wave.children;
  return {
    /** The RAW innerHTML string, never read through textContent — that getter
     *  strips tags out of `_html` and makes both spellings look identical. */
    html: wave._html,
    children: kids.length,
    transform: kids.length ? (kids[0].style.transform || null) : null,
    bars: kids.length > 1 ? kids[1].textContent : null,
    dot: kids.length ? kids[0].textContent : null,
  };
}

export function stageText() { return stage.textContent; }
export function removeLoader() { loader.remove(); }
"""

_PREAMBLE_HEAD = (
    "import { document, loader, wave, stage, tick, advance, liveIntervals,"
    " intervalCount, setReducedMotion, waveFrame, stageText, removeLoader }"
    " from './shim.js';\n"
)


@pytest.fixture(scope="module")
def loader_sandbox(tmp_path_factory):
    # The extracted script is written OUTSIDE the sandbox and copied in by the
    # shared builder, so this file uses that builder rather than a second one.
    tmp = tmp_path_factory.mktemp("bootloader")
    extracted = tmp_path_factory.mktemp("bootloader-src") / "loader-bootstrap.js"
    extracted.write_text(_loader_script(), encoding="utf-8")
    return _make_sandbox(tmp, extracted, _SHIM, {})


def _boot(script: str, sandbox: Path, reduced: bool = False) -> dict:
    preamble = (
        _PREAMBLE_HEAD
        + f"setReducedMotion({json.dumps(reduced)});\n"
        + "await import('./loader-bootstrap.js');\n"
    )
    return _run(sandbox, preamble, script)


# ── the wave is kept, and it no longer rebuilds itself ─────────────────────


def test_the_wave_still_waves(loader_sandbox):
    """`Keep the wave` is the row's own instruction, in those words."""
    out = _boot(
        """
        const first = waveFrame();
        tick(1);
        const second = waveFrame();
        tick(3);
        const later = waveFrame();
        console.log(JSON.stringify({ first, second, later }));
        """,
        loader_sandbox,
    )
    assert out["first"]["bars"], "no wave rendered at all"
    assert out["second"]["bars"] != out["first"]["bars"], (
        "the wave stopped moving between frames"
    )
    assert out["second"]["transform"] != out["first"]["transform"], (
        "the bobbing dot stopped moving"
    )
    assert len({out[k]["bars"] for k in ("first", "second", "later")}) == 3


def test_no_frame_is_written_as_markup(loader_sandbox):
    """The property, not the word (`Law 20`). A frame built by assigning
    `innerHTML` leaves the raw string behind; a frame built by mutating two
    nodes leaves it empty."""
    out = _boot(
        """
        tick(5);
        const f = waveFrame();
        console.log(JSON.stringify({ f }));
        """,
        loader_sandbox,
    )
    assert out["f"]["html"] == "", (
        "the loader is still assigning innerHTML per frame: "
        f"{out['f']['html']!r}"
    )
    assert out["f"]["children"] == 2, (
        "the frame should be two nodes built once and mutated, found "
        f"{out['f']['children']}"
    )


def test_the_two_nodes_are_built_once_and_reused(loader_sandbox):
    """Counting children after many frames is what separates 'stopped using
    innerHTML' from 'rebuilds the same two elements with createElement'."""
    out = _boot(
        """
        const before = waveFrame().children;
        tick(40);
        console.log(JSON.stringify({ before, after: waveFrame().children }));
        """,
        loader_sandbox,
    )
    assert out["before"] == out["after"] == 2


# ── reduced motion ─────────────────────────────────────────────────────────


def test_reduced_motion_starts_no_interval_and_still_draws_a_wave(loader_sandbox):
    out = _boot(
        """
        console.log(JSON.stringify({
          intervals: intervalCount(),
          frame: waveFrame(),
        }));
        """,
        loader_sandbox,
        reduced=True,
    )
    assert out["intervals"] == 0, (
        "the wave interval was started under `prefers-reduced-motion: reduce`. "
        "The CSS guard in style.css cannot reach a setInterval and this script "
        "runs before motion.js exists, so it has to ask for itself."
    )
    assert out["frame"]["bars"], (
        "the wave vanished under reduced motion. The row says keep it: a still "
        "frame is the answer, an empty box is a different product."
    )
    assert out["frame"]["children"] == 2


def test_motion_is_the_default_when_nothing_says_otherwise(loader_sandbox):
    out = _boot(
        """
        console.log(JSON.stringify({ intervals: intervalCount() }));
        """,
        loader_sandbox,
        reduced=False,
    )
    assert out["intervals"] == 1, (
        "the animation stopped starting for everyone, which is the mutation "
        "that makes the test above pass for the wrong reason"
    )


# ── the stage line ─────────────────────────────────────────────────────────


def test_the_page_ships_a_stage_line_with_something_already_in_it():
    markup = _loader_markup()
    m = re.search(r'<div\b([^>]*\bid="loader-stage"[^>]*)>(.*?)</div>', markup, re.S)
    assert m, "#loader-stage is not in the loader's markup"
    attrs, text = m.group(1), m.group(2).strip()
    assert text, (
        "the stage line ships empty, so the first thing a slow boot shows is "
        "still nothing"
    )
    assert 'role="status"' in attrs and 'aria-live="polite"' in attrs, (
        "a line that changes during boot and is not a live region is a line a "
        "screen-reader user never hears"
    )


def test_a_module_can_say_what_boot_is_doing(loader_sandbox):
    out = _boot(
        """
        const before = stageText();
        window.__pantheonLoaderStage('Loading your chats');
        console.log(JSON.stringify({ before, after: stageText() }));
        """,
        loader_sandbox,
    )
    assert out["after"] == "Loading your chats"
    assert out["before"] != out["after"]


def test_a_slow_boot_says_so_instead_of_bobbing(loader_sandbox):
    """The silence the row is named after. If nothing has reported by 2.5s the
    module graph is slow or broken, and saying so is the whole feature."""
    out = _boot(
        """
        const atStart = stageText();
        advance(2500);
        const atSlow = stageText();
        console.log(JSON.stringify({ atStart, atSlow }));
        """,
        loader_sandbox,
    )
    assert out["atSlow"] != out["atStart"], (
        "2.5 seconds into a stalled boot the loader still says what it said at "
        "0ms"
    )
    assert "longer" in out["atSlow"].lower() or "still" in out["atSlow"].lower()


def test_a_module_that_has_already_reported_is_not_overwritten(loader_sandbox):
    """The slow-boot line must not stamp on a real stage that arrived at 2.4s —
    that would replace information with an apology."""
    out = _boot(
        """
        window.__pantheonLoaderStage('Interface ready');
        advance(2500);
        console.log(JSON.stringify({ text: stageText() }));
        """,
        loader_sandbox,
    )
    assert out["text"] == "Interface ready", out["text"]


def test_the_five_second_fallback_still_retires_the_loader(loader_sandbox):
    """`Law 1`. `sessions.js` reads the node's presence as "startup in
    progress" and stops clearing the composer while it is around, so the
    fallback removing it is load-bearing and not cleanup."""
    out = _boot(
        """
        advance(5000);
        const opacity = loader.style.opacity;
        advance(5000);
        console.log(JSON.stringify({ opacity, live: liveIntervals() }));
        """,
        loader_sandbox,
    )
    assert out["opacity"] == "0"
    assert out["live"] == 0, "the wave kept ticking after the loader gave up"


def test_stopping_the_wave_stops_the_interval(loader_sandbox):
    out = _boot(
        """
        const before = liveIntervals();
        window.__pantheonLoaderWaveStop();
        console.log(JSON.stringify({ before, after: liveIntervals() }));
        """,
        loader_sandbox,
    )
    assert out["before"] == 1 and out["after"] == 0


def test_stopping_the_wave_twice_is_not_an_error(loader_sandbox):
    """`startupShell.js` calls it on reveal and again on removal."""
    out = _boot(
        """
        window.__pantheonLoaderWaveStop();
        window.__pantheonLoaderWaveStop();
        console.log(JSON.stringify({ ok: true, live: liveIntervals() }));
        """,
        loader_sandbox,
    )
    assert out["ok"] and out["live"] == 0


# ── the module that knows what boot is doing ───────────────────────────────


def test_startup_shell_reports_at_its_own_milestones():
    """`startupShell.js` already owns the loader's lifecycle, so it is where
    the stage names live — not a second module, and not `app.js`, which is one
    of the modules sharing the approval cache-buster string.

    Asserted by resolving the two functions and reading inside them
    (`Law 20` option 2); the calls themselves are driven in
    `tests/test_startup_shell_js.py`, which owns that module's harness.
    """
    from test_a_draft_skill_is_uncatalogued_not_inactive import js_function

    source = STARTUP_SHELL.read_text(encoding="utf-8")
    reveal = js_function(source, "export function revealApplicationShellAfterPaint")
    settle = js_function(source, "export function settleSessionHydration")
    assert len(reveal.splitlines()) < 20, (
        f"js_function returned {len(reveal.splitlines())} lines for a short "
        "function; the scope resolution has drifted and every assertion below "
        "is file-wide"
    )
    assert len(settle.splitlines()) < 60, len(settle.splitlines())
    assert "reportBootStage(" in reveal, (
        "the reveal milestone says nothing; the loader's line is still "
        "whatever the inline script last wrote"
    )
    assert "reportBootStage(" in settle
    assert settle.count("reportBootStage(") >= 2, (
        "hydration must report both that it started and that it failed — the "
        "failure case is the one a user is actually waiting through"
    )
