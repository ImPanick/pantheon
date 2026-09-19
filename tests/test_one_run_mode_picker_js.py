# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P5-17` — one run-mode picker, driven.

`P6-06` shipped the queue's sequential-vs-parallel popover as a **clone** of
`research/panel.js`'s and wrote down that it had. Re-measured 2026-09-19, the
two were identical in the popover class, both row classes, both glyphs byte for
byte, the whole drop-down-or-flip-up arithmetic, the `_rrmClose` toggle-shut
contract and both capture-phase dismissals.

**The row counts three differences and there are four.** Id, titles/subtitles
and callbacks — plus **row order**: the queue lists *sequential* first and the
research panel lists *parallel* first. A shared picker that took two named
callbacks would have silently reordered one of its callers, which is a `Law 15`
regression arriving through a parameter list, so the shared module takes an
ordered `rows` array and each caller states its own order.

The row is also explicit that **sharing naively is worse than the duplication**:
the queue's subtitle says *"Opens N new chats, one per message"* and the
research panel opens no chats. So the assertion that matters is not "one module
builds it" — that is easy and provable by grep — but **"the queue's words do
not reach the research panel"**, which grep cannot answer because both callers
now resolve to the same builder. That one is driven: the module is imported in
node under a DOM shim, called with each caller's real options, and the markup
it actually emits is read back.

`Law 20`, all three preferences, in order: the builder is *called*; the two call
sites are *resolved by scope* before being read; and the one file-wide
substring is an **absence** — `.research-run-mode-popover` must not be
constructed anywhere but the shared module, and its presence anywhere else
would be the clone coming back.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.source_text import blank  # B290

ROOT = Path(__file__).resolve().parents[1]
PICKER = ROOT / "static" / "js" / "runModePicker.js"
QUEUE = ROOT / "static" / "js" / "queuePanel.js"
PANEL = ROOT / "static" / "js" / "research" / "panel.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# A DOM small enough to read and large enough to run the picker. `innerHTML`
# is recorded rather than parsed; `querySelectorAll` finds the rows by their
# `data-mode`, which is the one thing the module writes for itself to read
# back — so a shim bug shows up as no rows rather than as a wrong assertion.
SHIM = r"""
const listeners = [];
const byId = new Map();
function makeEl(tag) {
  const el = {
    tagName: tag, id: '', className: '', innerHTML: '', offsetHeight: 40,
    style: {}, dataset: {}, _classes: [], _listeners: [], _removed: false,
    classList: { add(c) { el._classes.push(c); } },
    addEventListener(t, fn) { el._listeners.push([t, fn]); },
    remove() { el._removed = true; byId.delete(el.id); },
    contains() { return false; },
    getBoundingClientRect() { return { top: 100, bottom: 130, right: 400, left: 300 }; },
    // Memoised: a fresh array each call would hand the test different row
    // objects from the ones the module attached its handlers to, and the
    // click assertion would be testing the shim.
    querySelectorAll(sel) {
      if (sel !== '.research-run-mode-row') return [];
      if (!el._rows) {
        el._rows = [...el.innerHTML.matchAll(/data-mode="([^"]+)"/g)].map(m => {
          const row = makeEl('button');
          row.dataset.mode = m[1];
          return row;
        });
      }
      return el._rows;
    },
  };
  return el;
}
globalThis.document = {
  body: { appendChild(el) { if (el.id) byId.set(el.id, el); } },
  createElement: makeEl,
  getElementById(id) { return byId.get(id) || null; },
  addEventListener(t) { listeners.push(t); },
  removeEventListener(t) {
    const i = listeners.indexOf(t);
    if (i >= 0) listeners.splice(i, 1);
  },
};
globalThis.window = { innerHeight: 900, innerWidth: 1400 };
globalThis.__listeners = listeners;
globalThis.__makeAnchor = () => makeEl('button');
"""


def _run(body: str):
    script = SHIM + "\nconst mod = await import(" + json.dumps(PICKER.as_uri()) + ");\n" + body
    proc = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e",
         "(async () => {\n" + script + "\n})().catch(e => { console.error(e); process.exit(1); });"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── The Verify line: built in exactly one module ────────────────────────────


def test_the_popover_markup_is_built_in_exactly_one_module():
    """The row's own `Verify`. An absence assertion, which is the one thing a
    file-wide substring is good for."""
    builders = []
    for path in sorted(ROOT.joinpath("static").rglob("*.js")):
        if "static/lib/" in path.as_posix():
            continue
        src = blank(path)
        # Naming the popover's *id* is a caller's job and stays in both panels;
        # writing the ROW class is what only a builder does.
        if "research-run-mode-row" in src:
            builders.append(path.relative_to(ROOT).as_posix())
    assert builders == ["static/js/runModePicker.js"], builders


def test_the_research_panel_no_longer_carries_its_own_copy():
    src = blank(PANEL)
    assert "research-run-mode-row" not in src
    assert "rrm-title" not in src
    # What is left of the function is a vocabulary, not a popover: no element
    # is created, positioned or torn down inside it any more.
    body = _call_args(PANEL, "function _promptParallelOrSequential(")
    for gone in ("createElement", "getBoundingClientRect", "addEventListener",
                 "offsetHeight", "_rrmClose", "rrm-up"):
        assert gone not in body, f"{gone} is still inside the research panel's copy"


def test_the_glyphs_are_defined_once():
    """Both copies spelled the two SVGs out in full and they were byte
    identical. Two literals is two things to drift."""
    holders = []
    for path in (QUEUE, PANEL, PICKER):
        if 'x1="4" y1="6" x2="20" y2="6"' in blank(path):
            holders.append(path.name)
    assert holders == [PICKER.name], holders


# ── Driven: each caller's words, and only its own ───────────────────────────


QUEUE_ROWS = """
const pop = mod.promptRunMode({
  id: 'queue-run-mode-popover', anchor: __makeAnchor(),
  rows: [
    { mode: 'sequential', title: 'One after another', sub: 'Here in this chat, in the order below' },
    { mode: 'parallel', title: 'All at once', sub: 'Opens 4 new chats, one per message' },
  ],
});
"""
PANEL_ROWS = """
const pop = mod.promptRunMode({
  id: 'research-run-mode-popover', anchor: __makeAnchor(),
  rows: [
    { mode: 'parallel', title: 'Parallel' },
    { mode: 'sequential', title: 'Sequential' },
  ],
});
"""


def test_the_research_panels_popover_says_parallel_and_sequential_with_no_subtitle():
    """The row's `Verify`, second clause — and the reason it did not simply
    share: a chat-opening subtitle on a panel that opens no chats."""
    html = _run(PANEL_ROWS + "console.log(JSON.stringify(pop.innerHTML));")
    assert ">Parallel<" in html and ">Sequential<" in html, html
    assert "rrm-sub" not in html, html
    assert "new chats" not in html, html
    assert html.index("Parallel") < html.index("Sequential"), "research lists parallel first"


def test_the_queues_popover_keeps_its_consequence_subtitles_and_its_count():
    html = _run(QUEUE_ROWS + "console.log(JSON.stringify(pop.innerHTML));")
    assert "Opens 4 new chats, one per message" in html, html
    assert "Here in this chat, in the order below" in html, html
    assert html.index("One after another") < html.index("All at once"), \
        "the queue lists sequential first — the fourth difference the row did not count"


def test_a_callers_label_cannot_inject_markup():
    html = _run("""
const pop = mod.promptRunMode({
  id: 'x', anchor: __makeAnchor(),
  rows: [{ mode: 'parallel', title: '<img src=x onerror=1>' }],
});
console.log(JSON.stringify(pop.innerHTML));
""")
    assert "<img" not in html, html
    assert "&lt;img" in html, html


# ── The defect that used to need patching twice ─────────────────────────────


def test_toggling_shut_removes_both_capture_phase_listeners():
    """Both copies leaked their pair on the toggle-shut path and both were
    patched by hand on 2026-08-29. One implementation, one patch."""
    left = _run("""
const anchor = __makeAnchor();
const opts = { id: 'p', anchor, rows: [{ mode: 'parallel', title: 'P' }] };
mod.promptRunMode(opts);
await new Promise(r => setTimeout(r, 0));
const afterOpen = __listeners.length;
mod.promptRunMode(opts);            // second click on the anchor = toggle shut
console.log(JSON.stringify({ afterOpen, afterToggle: __listeners.length }));
""")
    assert left["afterOpen"] == 2, left
    assert left["afterToggle"] == 0, left


def test_choosing_a_row_calls_that_rows_handler_and_no_other():
    got = _run("""
const fired = [];
const pop = mod.promptRunMode({
  id: 'p', anchor: __makeAnchor(),
  rows: [
    { mode: 'sequential', title: 'S', onSelect: () => fired.push('sequential') },
    { mode: 'parallel', title: 'P', onSelect: () => fired.push('parallel') },
  ],
});
const rows = pop.querySelectorAll('.research-run-mode-row');
rows.find(r => r.dataset.mode === 'parallel')._listeners[0][1]();
console.log(JSON.stringify(fired));
""")
    assert got == ["parallel"], got


# ── The two call sites, resolved by scope ───────────────────────────────────


def _call_args(path: Path, needle: str) -> str:
    """The text of the one `openRunModePicker({…})` call in `needle`'s body."""
    src = blank(path)
    start = src.index(needle)
    depth, out, seen = 0, [], False
    for ch in src[start:]:
        out.append(ch)
        if ch == "{":
            depth += 1
            seen = True
        elif ch == "}":
            depth -= 1
            if seen and depth == 0:
                break
    body = "".join(out)
    assert "openRunModePicker(" in body, body[:400]
    return body


def test_each_caller_passes_its_own_id():
    assert "'queue-run-mode-popover'" in _call_args(QUEUE, "export function promptRunMode(")
    assert "'research-run-mode-popover'" in _call_args(PANEL, "function _promptParallelOrSequential(")


def test_each_caller_states_its_own_row_order():
    """The fourth difference the row did not count, asserted where it lives.

    The driven tests above pass their own `rows`, so they prove the builder
    honours an order — they cannot prove the two callers still ask for
    different ones. Flipping either list survived the first version of this
    file, which is the whole reason `Law 20` prefers a resolved scope over a
    happy path.
    """
    queue = _call_args(QUEUE, "export function promptRunMode(")
    assert queue.index("'sequential'") < queue.index("'parallel'"), \
        "the queue no longer lists 'one after another' first"
    panel = _call_args(PANEL, "function _promptParallelOrSequential(")
    assert panel.index("'parallel'") < panel.index("'sequential'"), \
        "the research panel no longer lists Parallel first"


def test_the_queues_subtitle_still_interpolates_the_count():
    """"Opens N new chats" without the N is a sentence about somebody else's
    queue. The driven test supplies its own string and cannot see this."""
    queue = _call_args(QUEUE, "export function promptRunMode(")
    assert "${count}" in queue, queue


def test_the_queue_still_names_consequences_and_not_mechanisms():
    """`P6-06`'s `Law 15` half, which is the reason the two popovers were not
    simply shared: *"Parallel" and "Sequential" name a mechanism, not a
    consequence, and a first-time user cannot tell from those two words that
    one of them opens new chats.* A title reverting to either noun survived
    every other assertion in this file, subtitle and all."""
    queue = _call_args(QUEUE, "export function promptRunMode(")
    titles = re.findall(r"title:\s*'([^']+)'", queue)
    assert titles == ["One after another", "All at once"], titles


def test_the_builder_supplies_no_words_of_its_own():
    """The row's sharp edge: shipping the queue's copy to the research panel is
    a `Law 15` regression. A default title inside the builder is that same
    mistake one layer down, where no caller can see it."""
    src = blank(PICKER)
    body = src[src.index("export function promptRunMode("):]
    for word in ("Parallel", "Sequential", "One after another", "All at once",
                 "new chats", "in this chat"):
        assert word not in body, f"the shared builder names {word!r}"


def test_the_queue_still_reaches_its_driver_when_no_handlers_are_given():
    """`promptRunMode(count, anchorBtn)` with no third argument fell back to
    `_driver.runSequential()` / `runParallel()`, and the queue's own Run button
    calls it exactly that way."""
    body = _call_args(QUEUE, "export function promptRunMode(")
    assert "_driver.runSequential()" in body
    assert "_driver.runParallel()" in body
    assert "handlers && handlers.onParallel" in body
