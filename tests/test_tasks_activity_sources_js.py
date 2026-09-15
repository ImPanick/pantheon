# SPDX-License-Identifier: AGPL-3.0-or-later
"""P6-07 — the Activity view accepts live rows from another module.

The Tasks activity view already renders every status with a shared elapsed
timer, a force button and a stop button. `P6-07` points it at the chat queue
rather than growing a second queue UI, and the half that lives in
`static/js/tasks.js` is the registry plus the rule that decides which shared
controls a row gets.

Driven under node against the real file, with stubs for the nine browser modules
it imports. `tasks.js` does no DOM work at import time (only
`window.location.origin`), so the contract functions can be exercised directly.

What is pinned:

  * a source's rows reach the view, and a throwing source is skipped instead of
    taking the whole panel down;
  * a row earns "Start now" / stop / "Open in chat" from its own callbacks, so a
    queue item with no `taskId` gets the same controls a task run does;
  * `force` stays a `queued`-only affordance, which is what that button has
    always meant;
  * the six-value status vocabulary is the *only* thing a source may send —
    documented at `core/database.py` and pinned as stored enum values in
    `FORBIDDEN.md`.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TASKS_JS = ROOT / "static" / "js" / "tasks.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_STUBS = {
    "ui.js": """
export const errors = [];
export default {
  esc: (s) => String(s == null ? '' : s),
  showToast: () => {}, showError: (m) => errors.push(String(m)),
  copyToClipboard: () => {}, el: () => null, debounce: (f) => f,
};
""",
    "markdown.js": "export default { mdToHtml: (s) => s, processWithThinking: (s) => s, squashOutsideCode: (s) => s };\n",
    "spinner.js": "export function createLoadingRow(){return{};}\nexport function createWhirlpool(){return{element:{style:{}}};}\n",
    "windowDrag.js": "export function makeWindowDraggable(){}\n",
    "toolWindowZOrder.js": "export function topPortalZ(){return 1;}\n",
    "modelSort.js": "export function sortModelIds(a){return a;}\n",
    "escMenuStack.js": "export function bindMenuDismiss(){return()=>{};}\nexport function dismissOrRemove(){}\n",
    "appConfig.js": "export function getSettings(){return{};}\nexport function invalidateSettings(){}\n",
    "util/ordinal.js": "export function ordinalSuffix(n){return String(n);}\n",
}

_SHIM = r"""
function _defineGlobal(name, value) {
  Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
_defineGlobal('window', globalThis);
_defineGlobal('location', { origin: 'http://test.local' });
globalThis.document = {
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  addEventListener: () => {},
  createElement: () => ({ style: {}, classList: { add(){}, remove(){}, toggle(){} },
                          appendChild(){}, setAttribute(){}, addEventListener(){} }),
};
export const ok = true;
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("tasksjs")
    (d / "util").mkdir()
    (d / "shim.js").write_text(_SHIM)
    for name, src in _STUBS.items():
        (d / name).write_text(src)
    shutil.copy(TASKS_JS, d / "tasks.js")
    # `B13`: the status words are a leaf module with no imports of its own, so
    # the real one is copied rather than stubbed — a stub here would let the
    # Activity view and the queue panel drift apart again without this file
    # noticing, which is the defect that module exists to close.
    shutil.copy(ROOT / "static" / "js" / "runStatus.js", d / "runStatus.js")
    return d


def _run(sandbox, script: str) -> dict:
    entry = sandbox / "case.mjs"
    entry.write_text("import './shim.js';\n" + textwrap.dedent(script))
    proc = subprocess.run(
        ["node", str(entry)], cwd=sandbox, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


# ── the registry ────────────────────────────────────────────────────────────

def test_a_registered_source_reaches_the_view(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        t.registerActivitySource('chat-queue', () => ([
          { status: 'queued', taskName: 'Queued message', ts: '2026-08-29T10:00:00Z',
            result: 'ship the thing', category: 'queue' },
        ]));
        console.log(JSON.stringify({ rows: t.collectActivitySourceEntries() }));
    """)
    assert len(out["rows"]) == 1
    row = out["rows"][0]
    assert row["status"] == "queued"
    assert row["taskName"] == "Queued message"
    assert row["category"] == "queue"
    assert row["sourceId"] == "chat-queue", "tasks.js stamps the owning source on every row"
    assert row["kind"] == "llm", "an unspecified kind defaults rather than rendering iconless"


def test_re_registering_an_id_replaces_it_rather_than_doubling_the_rows(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        t.registerActivitySource('q', () => ([{ status: 'queued', taskName: 'first' }]));
        t.registerActivitySource('q', () => ([{ status: 'queued', taskName: 'second' }]));
        console.log(JSON.stringify({ names: t.collectActivitySourceEntries().map(r => r.taskName) }));
    """)
    assert out["names"] == ["second"]


def test_unregister_removes_the_rows(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        t.registerActivitySource('q', () => ([{ status: 'queued', taskName: 'x' }]));
        const before = t.collectActivitySourceEntries().length;
        const removed = t.unregisterActivitySource('q');
        console.log(JSON.stringify({ before, removed, after: t.collectActivitySourceEntries().length,
                                     removedAgain: t.unregisterActivitySource('q') }));
    """)
    assert out == {"before": 1, "removed": True, "after": 0, "removedAgain": False}


def test_bad_registrations_are_refused(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        console.log(JSON.stringify({
          noId: t.registerActivitySource('', () => []),
          noFn: t.registerActivitySource('q', null),
          notAFn: t.registerActivitySource('q', 'nope'),
          rows: t.collectActivitySourceEntries().length,
        }));
    """)
    assert out == {"noId": False, "noFn": False, "notAFn": False, "rows": 0}


def test_a_throwing_source_is_skipped_not_fatal(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        t.registerActivitySource('bad', () => { throw new Error('boom'); });
        t.registerActivitySource('good', () => ([{ status: 'running', taskName: 'alive' }]));
        t.registerActivitySource('wrongtype', () => 'not an array');
        console.log(JSON.stringify({ names: t.collectActivitySourceEntries().map(r => r.taskName) }));
    """)
    assert out["names"] == ["alive"], "one broken source must not blank the Activity view"


def test_non_object_rows_are_dropped(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        t.registerActivitySource('q', () => ([null, 'nope', 7, { status: 'queued', taskName: 'real' }]));
        console.log(JSON.stringify({ names: t.collectActivitySourceEntries().map(r => r.taskName) }));
    """)
    assert out["names"] == ["real"]


def test_refresh_is_a_no_op_when_the_modal_is_closed(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        console.log(JSON.stringify({ refreshed: t.refreshActivityView() }));
    """)
    assert out == {"refreshed": False}


# ── which controls a row earns ──────────────────────────────────────────────

def test_a_task_run_keeps_exactly_the_controls_it_had(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        const q = t.activityEntryControls({ status: 'queued',  taskId: 'T1', kind: 'llm' });
        const r = t.activityEntryControls({ status: 'running', taskId: 'T1', kind: 'llm' });
        const d = t.activityEntryControls({ status: 'success', taskId: 'T1', kind: 'llm' });
        console.log(JSON.stringify({ q, r, d }));
    """)
    assert out["q"] == {"force": True, "stop": True, "open": True}
    assert out["r"] == {"force": False, "stop": True, "open": True}, "'Start now' is a queued-row verb"
    assert out["d"] == {"force": False, "stop": False, "open": True}


def test_a_source_row_earns_the_same_controls_through_callbacks(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        const noop = () => {};
        console.log(JSON.stringify({
          full: t.activityEntryControls({ status: 'queued', kind: 'queue',
                                          onForce: noop, onStop: noop, onOpen: noop }),
          bare: t.activityEntryControls({ status: 'queued', kind: 'queue' }),
        }));
    """)
    assert out["full"] == {"force": True, "stop": True, "open": True}, (
        "a queue item has no taskId — the callbacks are what earn the buttons"
    )
    assert out["bare"] == {"force": False, "stop": False, "open": False}, (
        "no taskId and no callback means no dead button"
    )


def test_controls_survive_a_missing_entry(sandbox):
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        console.log(JSON.stringify({ none: t.activityEntryControls(undefined) }));
    """)
    assert out["none"] == {"force": False, "stop": False, "open": False}


def test_only_queued_and_running_are_in_flight_for_a_task_run(sandbox):
    # `aborted` and `skipped` are terminal and are NOT failures — folding either
    # into `error` corrupts every error-rate statistic (core/database.py).
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        const all = {};
        for (const s of ['queued','running','success','error','skipped','aborted']) {
          all[s] = t.activityEntryControls({ status: s, taskId: 'T1' });
        }
        console.log(JSON.stringify(all));
    """)
    assert sorted(s for s, c in out.items() if c["stop"]) == ["queued", "running"]
    assert [s for s, c in out.items() if c["force"]] == ["queued"]


def test_a_source_row_stays_removable_after_it_goes_terminal(sandbox):
    # A queued message whose chat was deleted is `skipped` — deliberately did
    # not run, not a failure — and it still needs a way out of the list.
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        const noop = () => {};
        const all = {};
        for (const s of ['queued','running','success','error','skipped','aborted']) {
          all[s] = t.activityEntryControls({ status: s, onStop: noop });
        }
        console.log(JSON.stringify(all));
    """)
    assert all(c["stop"] for c in out.values()), (
        "a source that supplies onStop owns removal at every status"
    )
    assert [s for s, c in out.items() if c["force"]] == [], "force needs onForce, not onStop"


def test_status_block_documents_the_same_six_values(sandbox):
    # The JS contract and the stored vocabulary must not drift apart (Law 7).
    doc = (ROOT / "core" / "database.py").read_text()
    block = doc.split("TaskRun.status vocabulary")[1].split("TASK_RUN_ACTIVE_STATUSES")[0]
    for value in ("queued", "running", "success", "error", "skipped", "aborted"):
        assert value in block
    src = TASKS_JS.read_text()
    contract = src.split("_activitySources = new Map()")[0].rsplit("Activity sources (P6-07)", 1)[1]
    for value in ("queued", "running", "success", "error", "skipped", "aborted"):
        assert value in contract, f"the accepted-shape comment omits {value!r}"


def test_entry_status_still_prefers_the_rows_own_status_over_a_text_scan(sandbox):
    # Fixed 2026-08-27 and called out in core/database.py: an `aborted` run whose
    # partial output mentions "error" must not be filed under Errors.
    #
    # This was three assertions about the SHAPE of `_entryStatus`'s source — the
    # order of its lines and the exact spelling of one condition — which is a
    # test of the file, not of the code (`Law 20`). It failed when `B07` moved
    # the same decision behind the shared `runStatusTone`, while the behaviour it
    # names was unchanged. Asserted by calling the derivation now, so the next
    # refactor of the ladder is free and the next change of MEANING is not.
    out = _run(sandbox, """
        const t = await import('./tasks.js');
        const all = {};
        for (const s of ['queued','running','success','error','skipped','aborted','failed']) {
          all[s] = t.runStatusTone(s);
        }
        all._unknown = t.runStatusTone('something-new');
        console.log(JSON.stringify(all));
    """)
    assert out["aborted"] == "info", "an infra event is not a failure"
    assert out["skipped"] == "info", "a deliberate non-run is not a failure"
    assert out["error"] == "error" and out["failed"] == "error"
    assert out["success"] == "ok"
    # Only an unrecognised status may fall through to the text scan. Anything
    # the vocabulary names is decided here, whatever its output happens to say.
    assert out["_unknown"] is None
