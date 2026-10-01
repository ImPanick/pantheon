# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B925` — what the main thread did when a document landed, and the two
forced-layout patterns removed from it.

**Measured first** (`B923`'s repro, rebuilt): the app served locally, a
scripted OpenAI-compatible model streaming a reply whose `create_document`
fence carries a 44,000-character document, Chromium driving the composer with a
50 ms heartbeat, the longtask observer and a CDP sampling profile. On
`4e65b71`, three runs on a shared two-CPU host: the worst heartbeat gap at the
moment the document landed was 1,210 / 1,075 / 1,682 ms, inside a busy window
of ~1.7 s that was **73% `getBoundingClientRect`**. Its caller was the inline
scroll-to-bottom script in `index.html`: a `MutationObserver` on the whole chat
history that called `reposition()` — a forced layout — on every batch of chat
mutations. The next largest were the editor's line-number gutter: 1,347 probe
layouts (`_measureLineNumberHeights`, 336 ms) and a style copy that read the
textarea's computed style between writes to the probe, fifteen forced
recalculations a call (138 ms self).

**Changed:** the scroll button updates once a frame, not once a mutation; the
probe's style is read in one pass and written only when it changed; and a line
plainly narrower than the text column (a canvas measurement in the textarea's
font, no layout) is one row without asking the probe.

**Measured after**, the same three runs: JS time in the long busy stretches fell
from 2.25–2.85 s to 0.55–1.25 s, but **the worst gap at landing did not** —
1,498 / 1,199 / 1,441 ms. The window is now spread across other forced layouts
of the 44k-character editor (the probe that remains for wrapped lines, the tab
strip's `updateArrowVisibility` and `_scrollTabIntoView`, `syncGutterScroll`,
`app.js`'s `checkToolbarOverflow`) and rendering. So `B925`'s `Verify` (under
200 ms) is not met and the row stays open; this file pins the two patterns that
were removed (`Law 20`: the inline script and the gutter functions are run under
node, not grepped).
"""

import json
import re
import shutil
import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.helpers.js_source import js_definition
from tests.helpers.source_text import blank_text

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
DOC_JS = ROOT / "static" / "js" / "document.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _node(script: str) -> dict:
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the scroll-to-bottom button ────────────────────────────────────────────

class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.blocks, self._in = [], False

    def handle_starttag(self, tag, attrs):
        if tag == "script" and not dict(attrs).get("src"):
            self._in = True
            self.blocks.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in = False

    def handle_data(self, data):
        if self._in:
            self.blocks[-1] += data


def _scroll_button_script() -> str:
    p = _Scripts()
    p.feed(INDEX.read_text(encoding="utf-8"))
    [block] = [b for b in p.blocks if "scroll-bottom-btn" in b]
    return block


_SCROLL_SHIM = r"""
const counts = { rect: 0, frames: 0 };
const frames = [];
globalThis.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
const flush = () => { const run = frames.splice(0); counts.frames += run.length; run.forEach((f) => f(0)); };
let observer = null;
globalThis.MutationObserver = class { constructor(fn) { this.fn = fn; observer = this; } observe() {} };
globalThis.ResizeObserver = class { constructor(fn) { this.fn = fn; } observe() {} };
globalThis.window = globalThis;
globalThis.innerHeight = 800; globalThis.innerWidth = 1400;
globalThis.addEventListener = () => {};
const classes = new Set();
const el = (props) => Object.assign({ style: {}, addEventListener() {},
  classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) } }, props);
const container = el({ scrollHeight: 5000, clientHeight: 600, scrollTop: 4400 });
const chatBar = el({ getBoundingClientRect() { counts.rect += 1; return { top: 700, right: 1300 }; } });
const button = el({});
globalThis.document = {
  getElementById: (id) => ({ 'chat-history': container, 'scroll-bottom-btn': button })[id] || null,
  querySelector: (sel) => sel === '.chat-input-bar' ? chatBar : null,
};
"""


def test_a_burst_of_chat_mutations_lays_the_page_out_once():
    """A streamed reply and a landed document are hundreds of mutation batches;
    each one used to force a layout through `reposition()`."""
    out = _node(_SCROLL_SHIM + _scroll_button_script() + """
        const atStart = counts.rect;
        for (let i = 0; i < 50; i++) observer.fn([{ type: 'childList' }]);
        const beforeFrame = counts.rect - atStart;
        flush();
        console.log(JSON.stringify({ beforeFrame, inFrame: counts.rect - atStart - beforeFrame, frames: counts.frames }));
    """)
    assert out["beforeFrame"] == 0, "the observer forced a layout per mutation batch"
    assert out["inFrame"] == 1 and out["frames"] == 1


def test_the_button_still_follows_the_history():
    """Scrolled up past the threshold it shows; at the bottom it slides out —
    one frame after the mutations that changed it."""
    out = _node(_SCROLL_SHIM + _scroll_button_script() + """
        container.scrollTop = 1000;
        observer.fn([{ type: 'childList' }]); flush();
        const up = classes.has('show');
        container.scrollTop = 4400;
        observer.fn([{ type: 'childList' }]); flush();
        console.log(JSON.stringify({ up, down: classes.has('show'), out: classes.has('slide-out'),
                                     bottom: button.style.bottom }));
    """)
    assert out == {"up": True, "down": False, "out": True, "bottom": "116px"}


# ── the line-number gutter ─────────────────────────────────────────────────

def _gutter_fns() -> str:
    src = DOC_JS.read_text(encoding="utf-8")
    code = blank_text(src, "js")
    parts = []
    for name in ("_lineHeightPx", "_syncLineNumberMeasureStyle", "_fitsOnOneRow",
                 "_measureLineNumberHeights"):
        parts.append(js_definition(src, code.index(f"function {name}(")))
    for binding in ("_MEASURE_PROPS",):
        m = re.search(r"^[ \t]*const " + binding + r"\b", code, re.M)
        parts.append(js_definition(src, m.start()).strip() + ";")
    return "\n".join(parts)


_GUTTER_SHIM = r"""
const writes = [];
let probeReads = 0;
// A monospace column: every character 7px wide; the probe wraps at `width`.
const style = { fontFamily: 'monospace', fontSize: '12px', fontWeight: '400', fontStyle: 'normal',
  lineHeight: '18px', letterSpacing: 'normal', tabSize: '4', fontFeatureSettings: 'normal',
  fontVariantLigatures: 'normal', fontKerning: 'auto', textRendering: 'auto', whiteSpace: 'pre-wrap',
  wordWrap: 'break-word', overflowWrap: 'break-word' };
const probeStyle = new Proxy({}, { set(t, k, v) { writes.push(k); t[k] = v; return true; } });
const probe = {
  style: probeStyle, value: '',
  get scrollHeight() { probeReads += 1; return Math.max(1, Math.ceil(this.value.length * 7 / parseFloat(probeStyle.width))) * 18; },
};
const _lineNumberMeasureEl = () => probe;
let _lineNumberCanvas = null;
globalThis.document = { createElement: () => ({ getContext: () => ({ font: '', measureText: (t) => ({ width: t.length * 7 }) }) }) };
"""


def _gutter(script: str) -> dict:
    return _node(_GUTTER_SHIM + _gutter_fns() + "\n" + textwrap.dedent(script))


def test_the_probe_style_is_written_once_for_the_same_style_and_width():
    out = _gutter("""
        _measureLineNumberHeights({}, ['a'], 700, style);
        const first = writes.length;
        _measureLineNumberHeights({}, ['b'], 700, style);
        _measureLineNumberHeights({}, ['c'], 700, style);
        const repeated = writes.length - first;
        _measureLineNumberHeights({}, ['d'], 500, style);
        console.log(JSON.stringify({ first, repeated, resized: writes.length - first - repeated }));
    """)
    assert out["first"] == 15, out          # width and the fourteen properties
    assert out["repeated"] == 0, "the same style and width were written again"
    assert out["resized"] == 15


def test_a_line_that_plainly_fits_is_not_laid_out_and_the_rest_are():
    """Column 700px (100 characters). Short lines and blank ones are one row
    with no probe layout; a line within 15% of the column, or wider, goes to the
    probe, and its wrapped height is the probe's."""
    out = _gutter("""
        const lines = ['', 'short', 'x'.repeat(80), 'x'.repeat(90), 'x'.repeat(250), '\\t\\t' + 'x'.repeat(78)];
        const heights = _measureLineNumberHeights({}, lines, 700, style);
        console.log(JSON.stringify({ heights, probeReads }));
    """)
    assert out["heights"] == [18, 18, 18, 18, 54, 18], out
    # '' 'short' and 80 chars skip; 90 chars (630px > 85% of 700) and 250 go to
    # the probe; two tabs at tab-size 4 make the last line 86 columns, 602px,
    # which is past 85% too.
    assert out["probeReads"] == 3


def test_without_a_canvas_every_line_still_goes_to_the_probe():
    out = _gutter("""
        globalThis.document = { createElement: () => { throw new Error('no canvas'); } };
        const heights = _measureLineNumberHeights({}, ['a', 'b'], 700, style);
        console.log(JSON.stringify({ heights, probeReads }));
    """)
    assert out == {"heights": [18, 18], "probeReads": 2}
