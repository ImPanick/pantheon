# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`static/js/tourAutoplay.js` — the first-run walkthroughs, and when they hold back.

The module was switched off for a year behind `init()` stubbed with *"Disabled
for v1 stability: opening ordinary app windows must never auto-spawn tour
overlays or interfere with close/backdrop behavior"*, and nobody wrote down what
the instability was. `P3-10b` turned it back on, so what protects the user now
is a set of gates rather than a stub, and gates that nothing exercises are a
stub with extra steps.

The whole real module runs here under `node`, against stubs for the two things
it imports and a small DOM. The tests drive it the way the browser does — a
modal element appearing on `document.body` — and read what came out the other
side: whether a tour fired, with which options, and whether the one-shot marker
was written.

The distinction that matters most is between *seen* and *deferred*. Three gates
decline to play a tour without marking it seen, because a walkthrough skipped on
a narrow window, or over a half-typed message, is one the user has still never
had. Getting that wrong burns the only first run they get, silently.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "static" / "js" / "tourAutoplay.js"
_HAS_NODE = shutil.which("node") is not None

pytestmark = pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")

_SLASH_STUB = """
export const calls = [];
export let setupMode = false;
export function setSetupMode(v) { setupMode = v; }
export async function handleSlashCommand(input, options) {
  calls.push({ input, options });
  return true;
}
export function getSetupMode() { return setupMode; }
"""

_UI_STUB = """
export const toasts = [];
export default { showToast(t) { toasts.push(t); } };
"""

# A DOM just wide enough for the module: elements that can be looked up by id or
# by attribute selector, a body whose additions the observers see, and a
# `MutationObserver` the test drives by hand.
_DOM = """
export const store = new Map();
export const byId = new Map();
export const bySelector = new Map();

class ClassList {
  constructor(el) { this.el = el; }
  _list() { return String(this.el.className || '').split(/\\s+/).filter(Boolean); }
  contains(c) { return this._list().includes(c); }
  add(c) { if (!this.contains(c)) this.el.className = (this.el.className + ' ' + c).trim(); }
  remove(c) { this.el.className = this._list().filter(x => x !== c).join(' '); }
}

export class El {
  constructor(id, { width = 200, height = 100, className = '' } = {}) {
    this.id = id;
    this.className = className;
    this.style = {};
    this.dataset = {};
    this.value = '';
    this.checked = false;
    this._w = width; this._h = height;
    this._listeners = {};
    this.classList = new ClassList(this);
  }
  getBoundingClientRect() { return { width: this._w, height: this._h, top: 0, left: 0 }; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatchEvent(ev) { (this._listeners[ev.type] || []).forEach(fn => fn(ev)); return true; }
  click() { this.dispatchEvent({ type: 'click' }); }
}

const observers = [];
class FakeMutationObserver {
  constructor(cb) { this.cb = cb; this.targets = []; observers.push(this); }
  observe(target) { this.targets.push(target); }
  disconnect() {}
}

export function openModal(id) {
  const el = new El(id);
  byId.set(id, el);
  // The doc observer watches document.body for added nodes; that is the path a
  // dynamically-built modal (gallery, research, compare, library) takes.
  observers.forEach(o => {
    if (!o.targets.includes(globalThis.document.body)) return;
    o.cb([{ addedNodes: [el], attributeName: null, target: globalThis.document.body }]);
  });
  return el;
}

export function installDom() {
  const body = new El('body');
  globalThis.document = {
    body,
    readyState: 'complete',
    getElementById: (id) => byId.get(id) || null,
    querySelector: (sel) => bySelector.get(sel) || null,
    addEventListener() {},
  };
  globalThis.window = { innerWidth: 1400 };
  globalThis.HTMLElement = El;
  globalThis.MutationObserver = FakeMutationObserver;
  globalThis.Event = class { constructor(type) { this.type = type; } };
  globalThis.localStorage = {
    _m: new Map(),
    getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
    setItem(k, v) { this._m.set(k, String(v)); },
    removeItem(k) { this._m.delete(k); },
  };
  // The module waits 400ms for the modal's enter animation before firing.
  // Collapse that to a microtask: the ordering under test is "marker written
  // before the timer, tour fired inside it", which survives, and nine cases
  // times 400ms does not.
  globalThis.setTimeout = (fn) => { queueMicrotask(fn); return 0; };
  return { body };
}
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("tours")
    (d / "slashCommands.js").write_text(_SLASH_STUB, encoding="utf-8")
    (d / "ui.js").write_text(_UI_STUB, encoding="utf-8")
    (d / "dom.js").write_text(_DOM, encoding="utf-8")
    shutil.copy(_SRC, d / "tourAutoplay.js")
    return d


_PREAMBLE = """
import { installDom, openModal, byId, bySelector, El } from './dom.js';
installDom();
const slash = await import('./slashCommands.js?v=20260815approvalsave1');
const ui = await import('./ui.js');
const tours = await import('./tourAutoplay.js');
const settle = () => new Promise(r => setTimeout(r, 0));
"""


def _run(sandbox: Path, script: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(_PREAMBLE + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(entry)], cwd=sandbox, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"node produced no stdout\n{proc.stderr}"
    return json.loads(lines[-1])


_SEEN = "pantheon-tour-autoplay-seen-tour-cookbook"


def test_the_first_open_of_a_tool_plays_its_tour_quietly(sandbox):
    # The row's Verify line: cleared storage, open the Forge (cookbook) modal,
    # get its walkthrough. And it must arrive as a tour, not as a command the
    # user appears to have typed — that is the defect the stub was hiding.
    out = _run(sandbox, """
        tours.init();
        openModal('cookbook-modal');
        await settle();
        console.log(JSON.stringify({
          calls: slash.calls,
          seen: localStorage.getItem('%s'),
        }));
    """ % _SEEN)
    assert out["calls"] == [{"input": "/tour-cookbook", "options": {"echo": False, "persist": False}}]
    assert out["seen"] == "1"


def test_the_second_open_does_not(sandbox):
    out = _run(sandbox, """
        tours.init();
        openModal('cookbook-modal');
        await settle();
        const first = slash.calls.length;
        openModal('cookbook-modal');
        await settle();
        console.log(JSON.stringify({ first, total: slash.calls.length }));
    """)
    assert out == {"first": 1, "total": 1}


def test_a_tour_fires_once_even_if_the_module_is_initialised_twice(sandbox):
    # `init()` binds the replay button outside the once-only latch so a late
    # caller can still get it bound, which means the observer setup is the part
    # that has to stay single. Pinned as an outcome rather than a mechanism:
    # today the one-shot marker is written before the 400ms timer and would
    # catch a doubled observer anyway, so this holds the guarantee even if the
    # implementation of it moves.
    out = _run(sandbox, """
        tours.init();
        tours.init();
        openModal('cookbook-modal');
        await settle();
        console.log(JSON.stringify({ calls: slash.calls.length }));
    """)
    assert out["calls"] == 1


def test_a_modal_with_no_tour_of_its_own_is_ignored(sandbox):
    out = _run(sandbox, """
        tours.init();
        openModal('tasks-modal');
        await settle();
        console.log(JSON.stringify({ calls: slash.calls.length }));
    """)
    assert out["calls"] == 0


# ── the three gates that defer rather than consume ────────────────────────────

_DEFERRING_GATES = {
    "a draft in the composer": """
        const msg = new El('message');
        msg.value = '  half a thought  ';
        byId.set('message', msg);
    """,
    # 760, not 700: the whole point of `B50` is the 701-767 band where the
    # product used to disagree with itself about where mobile ends. A test at
    # 700 passes against either threshold and proves nothing.
    "a narrow window": "window.innerWidth = 760;",
    "the setup wizard": "slash.setSetupMode(true);",
}

_UNDO = {
    "a draft in the composer": "byId.get('message').value = '';",
    "a narrow window": "window.innerWidth = 1400;",
    "the setup wizard": "slash.setSetupMode(false);",
}


@pytest.mark.parametrize("gate", sorted(_DEFERRING_GATES))
def test_a_wrong_moment_defers_the_tour_without_burning_it(sandbox, gate):
    # Two claims, and the second is the one worth having: the tour does not
    # play, AND the one-shot marker is not written — so when the moment is
    # right, the user still gets the walkthrough they have never seen.
    out = _run(sandbox, """
        %s
        tours.init();
        openModal('cookbook-modal');
        await settle();
        const during = { calls: slash.calls.length, seen: localStorage.getItem('%s') };
        %s
        openModal('cookbook-modal');
        await settle();
        console.log(JSON.stringify({ during, after: slash.calls.length }));
    """ % (_DEFERRING_GATES[gate], _SEEN, _UNDO[gate]))
    assert out["during"] == {"calls": 0, "seen": None}, f"{gate} should defer, not fire"
    assert out["after"] == 1, f"{gate} burned the tour instead of deferring it"


# ── the preference ────────────────────────────────────────────────────────────


def test_turning_walkthroughs_off_stops_them(sandbox):
    out = _run(sandbox, """
        localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
        tours.init();
        openModal('cookbook-modal');
        await settle();
        console.log(JSON.stringify({ calls: slash.calls.length, seen: localStorage.getItem('%s') }));
    """ % _SEEN)
    assert out == {"calls": 0, "seen": None}


def test_an_unexpressed_preference_means_on(sandbox):
    # Absent, empty, and unparseable all have to mean "show them". A user who
    # has never opened Settings is exactly the user the tours are for.
    out = _run(sandbox, """
        const answers = {};
        answers.absent = tours.toursEnabled();
        localStorage.setItem('pantheon-ui-visibility', '{}');
        answers.empty = tours.toursEnabled();
        localStorage.setItem('pantheon-ui-visibility', 'not json');
        answers.broken = tours.toursEnabled();
        localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': true }));
        answers.on = tours.toursEnabled();
        localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
        answers.off = tours.toursEnabled();
        console.log(JSON.stringify(answers));
    """)
    assert out == {"absent": True, "empty": True, "broken": True, "on": True, "off": False}


def test_the_preference_is_read_when_a_tour_would_fire_not_at_boot(sandbox):
    # Gating inside init() would freeze the answer at page load, so a user who
    # turned tours back on in Settings would have to reload to see one — and
    # would reasonably conclude the setting does nothing.
    out = _run(sandbox, """
        localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
        tours.init();
        openModal('cookbook-modal');
        await settle();
        const whileOff = slash.calls.length;
        localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': true }));
        openModal('cookbook-modal');
        await settle();
        console.log(JSON.stringify({ whileOff, afterTurningOn: slash.calls.length }));
    """)
    assert out == {"whileOff": 0, "afterTurningOn": 1}


# ── the way back ──────────────────────────────────────────────────────────────


def test_show_again_clears_every_marker(sandbox):
    out = _run(sandbox, """
        const tourNames = ['tour-library','tour-cookbook','tour-research','tour-compare',
                           'tour-theme','tour-settings','tour-gallery'];
        tourNames.forEach(t => localStorage.setItem('pantheon-tour-autoplay-seen-' + t, '1'));
        localStorage.setItem('unrelated-key', 'keep me');
        tours.resetSeenTours();
        console.log(JSON.stringify({
          left: tourNames.filter(t => localStorage.getItem('pantheon-tour-autoplay-seen-' + t)),
          unrelated: localStorage.getItem('unrelated-key'),
        }));
    """)
    assert out == {"left": [], "unrelated": "keep me"}


def test_show_again_also_turns_the_preference_back_on(sandbox):
    # Clearing the markers while tours are switched off would clear them and
    # show nothing, which reads as a broken button.
    out = _run(sandbox, """
        localStorage.setItem('pantheon-ui-visibility', JSON.stringify({ 'first-run-tours': false }));
        const btn = new El('set-replay-tours');
        byId.set('set-replay-tours', btn);
        const toggle = new El('tours-toggle');
        toggle.checked = false;
        let changes = 0;
        toggle.addEventListener('change', () => { changes += 1; });
        bySelector.set('[data-ui-key="first-run-tours"]', toggle);
        localStorage.setItem('%s', '1');
        tours.init();
        btn.click();
        console.log(JSON.stringify({
          seen: localStorage.getItem('%s'),
          checked: toggle.checked,
          changes,
          toasted: ui.toasts.length,
        }));
    """ % (_SEEN, _SEEN))
    assert out["seen"] is None
    assert out["checked"] is True
    assert out["changes"] == 1, "the change event is what saves the preference"
    assert out["toasted"] == 1, "the user gets told the reset happened"


def test_the_replay_button_is_bound_once(sandbox):
    out = _run(sandbox, """
        const btn = new El('set-replay-tours');
        byId.set('set-replay-tours', btn);
        tours.init();
        tours.init();
        localStorage.setItem('%s', '1');
        btn.click();
        console.log(JSON.stringify({ handlers: (btn._listeners.click || []).length }));
    """ % _SEEN)
    assert out["handlers"] == 1
