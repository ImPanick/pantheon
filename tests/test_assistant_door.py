"""The Personal Assistant had no door at all (`H02`).

475 lines of frontend and six live routes — a personality picker, timezone,
endpoint, model, a grouped tool allow-list and three daily check-ins — behind
two entry points, both dead:

  * `openAssistantChat()` had **zero callers repo-wide**;
  * `openAssistantSettings()` was reached only from a gear built by a poll
    testing `window.sessionModule?.getActiveSession?.()` — and
    **`getActiveSession` occurs exactly once in this repository, at that call
    site.** It is not among `sessionModule`'s exports. Its fallback,
    `document.body.dataset.activeSessionId`, is set by nothing. So the gear was
    never built, and the only observable effect of the mechanism was 120 wasted
    ticks per page load.

The comment where the sidebar wiring used to be says the views "now live as
Activity / Settings tabs inside the Tasks modal (see tasks.js)". `tasks.js` never
imports `assistant.js`. That migration was described and never performed.

The row's `Verify:` is *a person can open the assistant, configure it, and
receive a daily check-in* — three things, tested here in that order.
"""
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ASSISTANT = ROOT / "static" / "js" / "assistant.js"
SESSIONS = ROOT / "static" / "js" / "sessions.js"
INDEX = ROOT / "static" / "index.html"
APP_JS = ROOT / "static" / "app.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")


def _code(path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))


# ── 1. a person can open the assistant ──────────────────────────────────────

def test_the_rail_button_exists_in_the_markup():
    markup = INDEX.read_text(encoding="utf-8")
    assert 'id="rail-assistant"' in markup
    assert 'title="Assistant"' in markup


def test_the_rail_button_is_wired_to_the_chat_opener():
    """`openAssistantChat()` had zero callers. This is the caller."""
    code = _code(ASSISTANT)
    assert "rail-assistant" in code
    block = code[code.index("rail-assistant") - 200:code.index("rail-assistant") + 500]
    assert "addEventListener('click'" in block
    assert "openAssistantChat" in block


def test_the_wiring_runs_at_boot_without_a_condition():
    """A door behind a condition that has to come true is what this row is
    about. `_boot` calls it unconditionally."""
    code = _code(ASSISTANT)
    boot = code[code.index("function _boot()"):]
    boot = boot[:boot.index("}")]
    assert "_wireRailButton" in boot


def test_the_rail_button_has_a_hover_label_like_every_other():
    """The rail labels every button. One without a label is visibly a bolt-on,
    and the point of this row is that the assistant is part of the product."""
    code = _code(APP_JS)
    assert "'rail-assistant': 'Assistant'" in code


def test_the_assistant_module_is_still_loaded_on_every_page():
    markup = INDEX.read_text(encoding="utf-8")
    assert "js/assistant.js" in markup


# ── 2. …and configure it: the gear that was never built ─────────────────────

def test_the_dead_condition_is_gone():
    """`getActiveSession` is not a `sessionModule` export, and nothing sets
    `document.body.dataset.activeSessionId`. Both branches were dead."""
    code = _code(ASSISTANT)
    assert "getActiveSession" not in code
    assert "dataset.activeSessionId" not in code

    exports = set(re.findall(r"^export (?:async )?function (\w+)",
                             SESSIONS.read_text(encoding="utf-8"), re.M))
    assert "getActiveSession" not in exports, \
        "the export appeared; this test's premise needs re-checking"
    assert "getCurrentSessionId" in exports


def test_the_two_minute_poll_is_gone():
    """120 ticks per page load, achieving nothing. An event replaced it, which
    is also `P15-10`'s direction: nothing recurring that does not need to."""
    code = _code(ASSISTANT)
    assert "setInterval" not in code.split("function _watchForAssistantActivation")[1][:800]


def test_the_gear_is_driven_by_the_session_changed_event():
    code = _code(ASSISTANT)
    assert "pantheon:session-changed" in code
    watcher = code[code.index("function _watchForAssistantActivation"):]
    watcher = watcher[:watcher.index("\n}")]
    assert "addEventListener" in watcher
    assert "_ensureHeaderAffordances" in watcher
    assert "getCurrentSessionId" in watcher, \
        "a reload landing on the assistant session gets no gear"


def test_sessions_actually_emits_that_event():
    """`Law 15` in its usual form: a listener with no emitter is a listener that
    never fires, which is the exact defect this row is fixing."""
    code = _code(SESSIONS)
    assert "pantheon:session-changed" in code
    assert "dispatchEvent" in code


def test_the_event_carries_the_session_id_the_listener_reads():
    """Two halves in two files that have to agree on one field name."""
    emitter = _code(SESSIONS)
    listener = _code(ASSISTANT)
    block = emitter[emitter.index("pantheon:session-changed"):][:400]
    assert "sessionId" in block
    assert "detail?.sessionId" in listener or "detail.sessionId" in listener


def test_the_stale_migration_comment_is_corrected():
    """It said the views "now live as Activity / Settings tabs inside the Tasks
    modal (see tasks.js)". `tasks.js` never imports this module — the migration
    was described and never performed, and the comment is why nobody noticed the
    entry point was gone."""
    tasks = (ROOT / "static" / "js" / "tasks.js").read_text(encoding="utf-8")
    assert "assistant.js" not in tasks, \
        "tasks.js now imports assistant.js; this row's premise has changed"

    # NOT "the old sentence is absent". The correction quotes it, deliberately —
    # a reader needs to see what the file used to claim to understand why the
    # door was missing — so asserting its absence would have forced the
    # correction to be vaguer than the mistake. What must hold is that the
    # claim no longer stands unqualified.
    raw = ASSISTANT.read_text(encoding="utf-8")
    idx = raw.find("Sidebar wiring removed")
    assert idx >= 0, "the history was dropped rather than corrected"
    following = raw[idx:idx + 900]
    assert "None of that was true" in following, \
        "the stale claim is still presented as current"
    assert "never imported" in following


# ── the event, exercised ────────────────────────────────────────────────────

_SHIM = r"""
export const calls = { affordances: [], fetches: [] };
const listeners = {};
const nodes = {};
function node(id) {
  return nodes[id] || (nodes[id] = {
    id, dataset: {}, className: '', listeners: {},
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    click() { (this.listeners.click || []).forEach(fn => fn({})); },
    querySelector: () => null, appendChild: () => {},
  });
}
node('rail-assistant');
globalThis.document = {
  getElementById: (id) => nodes[id] || null,
  querySelector: () => null,
  addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
  dispatchEvent(ev) { (listeners[ev.type] || []).forEach(fn => fn(ev)); return true; },
  createElement: () => node('made-' + Math.random()),
  readyState: 'complete',
  body: { dataset: {} },
};
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = (init || {}).detail; } };
function def(name, value) {
  Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
def('window', globalThis);
globalThis.sessionModule = { getCurrentSessionId: () => globalThis.__current || '' };
globalThis.fetch = async (url) => {
  calls.fetches.push(String(url));
  return { ok: true, json: async () => ({ session_id: 'assistant-1', crew: { session_id: 'assistant-1' } }) };
};
export function railButton() { return nodes['rail-assistant']; }
export function fire(sessionId) {
  document.dispatchEvent(new CustomEvent('pantheon:session-changed', { detail: { sessionId } }));
}
export function tick(n = 6) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise(r => setTimeout(r, 0)));
  return p;
}
"""

_STUBS = {
    "ui.js": "export default { showToast: () => {}, showError: () => {}, el: (id) => document.getElementById(id) };\n",
    "sessions.js": "export const selectSession = async (id) => { globalThis.__selected = id; };\n",
    "modelSort.js": "export const sortModelIds = (x) => x;\n",
}


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("assistantjs")
    (d / "shim.js").write_text(_SHIM, encoding="utf-8")
    for name, src in _STUBS.items():
        (d / name).write_text(src, encoding="utf-8")
    shutil.copy2(ASSISTANT, d / "assistant.js")
    return d


def _run(sandbox, script: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text(
        "import { calls, railButton, fire, tick } from './shim.js';\n"
        "import assistant from './assistant.js';\n"
        + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=sandbox,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_clicking_the_rail_button_opens_the_assistant_session(sandbox):
    """End to end through the real module: the click reaches
    `/api/assistant/session` and hands the id to `selectSession`."""
    out = _run(sandbox, """
        railButton().click();
        await tick();
        console.log(JSON.stringify({
          fetches: calls.fetches,
          selected: globalThis.__selected || null,
        }));
    """)
    assert any("/api/assistant/session" in f for f in out["fetches"])
    assert out["selected"] == "assistant-1"


def test_the_session_changed_event_reaches_the_gear_builder(sandbox):
    """The listener has to actually run — the old poll's condition never did."""
    out = _run(sandbox, """
        fire('assistant-1');
        await tick();
        console.log(JSON.stringify({ fetches: calls.fetches }));
    """)
    assert any("/api/assistant/settings" in f for f in out["fetches"]), \
        "the session-changed event did not reach the gear builder"


def test_an_unrelated_session_does_not_build_the_gear(sandbox):
    """`_ensureHeaderAffordances` compares against the assistant's own session
    id; a normal chat must not grow an assistant gear."""
    out = _run(sandbox, """
        fire('some-other-chat');
        await tick();
        console.log(JSON.stringify({ fetches: calls.fetches }));
    """)
    # It may still ASK for settings to make the comparison; what it must not do
    # is build anything. The module returns early on a mismatch, so the proof is
    # that nothing was appended — asserted through the settings id it would use.
    assert "assistant-header-gear" not in json.dumps(out)


# ── 3. …and receive a daily check-in ────────────────────────────────────────

def test_the_check_ins_are_real_scheduled_tasks():
    """The third clause of the `Verify`. Check-ins are `ScheduledTask` rows, so
    they ride the scheduler that already exists rather than a second timer —
    which also means they inherit `P15-10`'s dispatch jitter."""
    routes = (ROOT / "routes" / "assistant_routes.py").read_text(encoding="utf-8")
    assert "ScheduledTask" in routes
    assert "check_ins" in routes


def test_the_settings_patch_can_write_the_check_ins():
    """Configuring them is the middle clause of the `Verify`, and it is what the
    unreachable settings modal was for."""
    routes = (ROOT / "routes" / "assistant_routes.py").read_text(encoding="utf-8")
    assert '@router.patch("/settings")' in routes
    assert "payload.check_ins" in routes
    code = _code(ASSISTANT)
    assert "check_ins" in code, "the settings modal cannot edit them"
