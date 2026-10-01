# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-05`…`P22-08` (wf-ui) — the Automations room: the chains, and every workflow beside them.

`static/js/workbench/workflowRoom.js` (`mountAutomations`) is what a person
meets in the Workbench after Slice B (design § 6): the tasks-and-chains canvas
`P22-02` shipped, still the landing view, and a shelf listing every workflow —
a named, versioned document started by one task. These cases drive the room
the way a person does:

  * the shelf: *Tasks and chains* first and selected, then each workflow with
    its On/Off word and its last run as a mark and a word (`P22-05`);
  * a workflow opens on the same canvas (`Law 14`) with its toolbar: the name
    (a rename is part of the draft), *Save* with "Unsaved changes" in words,
    the switch with what Off means, *Versions…*, *Run now*, *Show me what this
    would do*, and Edit | Runs;
  * *Save* goes through the source; a stale save says the server's sentence and
    offers to open the saved workflow again;
  * leaving with unsaved changes — another entry, the tasks, the window —
    asks *Save / Discard / Keep editing*, and Escape keeps editing;
  * a chain made a workflow, switched on, and the old chain put back with one
    click, in the server's own words (`P22-06`);
  * Runs: a failed run opens on its failed step with what it was handed open,
    every value drawn as text (`P22-07`);
  * *Test this step*: a step that does something real shows its plan and asks
    first, runs nothing else, and a pinned sample says it is never used by a
    scheduled run (`P22-08`);
  * the palette adds a step by kind; *New workflow* is named, then made
    switched off; a workflow's own start opens it; and a room whose workflow
    layer did not load still has every chain (`Law 1`).

**What is real and what is not.** The room, the canvas, the task source, the
panels, the layout and every module they import are the real ones. The task
form is the recorded `P22` panel contract (its modes are driven for real in
`test_one_form_for_a_step_and_a_start_js.py`). The workflow layer —
`workflowApi.js` and `workflowSource.js`, wf-api's — is a fake written to C3's
shapes (`tests/helpers/workflow_fakes.py`), loaded through the room's own
`import()`, because those two modules are on wf-api's branch, not this one.
The tasks are answered by the canvas test's fake server.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM, _UP, _TASKS  # noqa: E402
from helpers.workflow_fakes import WORKFLOW_API_JS, WORKFLOW_SOURCE_JS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
ROOM_JS = JS / "workbench" / "workflowRoom.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = _CANVAS_SHIM + r"""
// ── the task form, as the `P22` panel contract: recorded ───────────────────
export const fields = { mounts: [] };
export function mountTaskFields(host, args) {
  const rec = { host, args, destroyed: false };
  fields.mounts.push(rec);
  const i = host.appendChild(new Node('input'));
  i.className = 'stub-field';
  return { destroy() { rec.destroyed = true; } };
}
export const itemOf = (root, id) => root.querySelectorAll('.wb-node').find((n) => n.dataset.itemId === id) || null;
export const shelf = (root) => root.querySelectorAll('.wf-shelf-item').map((b) => ({
  key: b.dataset.key, text: b.querySelectorAll('span').filter((s) => !s.querySelector('span'))
    .map((s) => s.textContent).join('|'), current: b.getAttribute('aria-current') === 'true' }));
export const sayOf = (root) => {
  const all = root.querySelectorAll('.wb-say-text').filter((s) => {
    for (let n = s; n; n = n.parentNode) if (n.hidden) return false;
    return true;
  });
  return all.length ? all[all.length - 1].textContent : root.querySelector('.wf-say-text').textContent;
};
export const sayButton = (root) => {
  const all = root.querySelectorAll('.wb-say-action').filter((b) => !b.hidden && (() => {
    for (let n = b; n; n = n.parentNode) if (n.hidden) return false; return true; })());
  return all.length ? all[all.length - 1] : null;
};
export const by = (root, cls) => root.querySelector('.' + cls);
export const typed = (el, value) => {
  el.value = value;
  el.dispatchEvent({ type: 'input', target: el, stopPropagation() {}, preventDefault() {} });
};
"""

_WORLD = {
    "calls": [],
    "tasks": [
        {"id": "tw1", "name": "Morning brief", "task_type": "workflow", "status": "paused",
         "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "08:00", "workflow_id": "w1"},
    ],
    "workflows": [{
        "id": "w1", "name": "Morning brief", "task_id": "tw1", "version": 3,
        "graph": {"v": 1, "start": {"position": None}, "nodes": [
            {"id": "n1", "kind": "llm", "label": "Summarise my inbox",
             "config": {"prompt": "Summarise my unread mail"}, "pinned": None},
            {"id": "n2", "kind": "action", "label": "Send me the summary",
             "config": {"action": "web_fetch_digest", "prompt": "https://example.com"}, "pinned": None}],
            "edges": [{"from": "n1", "port": "success", "to": "n2"}]},
        "last_run": {"id": "r2", "status": "error", "started_at": "2026-09-30T08:00:00Z",
                     "finished_at": "2026-09-30T08:00:09Z", "dry": False},
        "versions": [
            {"version": 3, "name": "Morning brief", "saved_at": "2026-09-30T07:00:00Z", "source": "user",
             "step_count": 2, "current": True},
            {"version": 2, "name": "Morning brief", "saved_at": "2026-09-29T07:00:00Z", "source": "user",
             "step_count": 1, "current": False}],
    }],
    "runs": [
        {"id": "r2", "task_id": "tw1", "status": "error", "started_at": "2026-09-30T08:00:00Z",
         "finished_at": "2026-09-30T08:00:09Z", "steps": [{"kind": "node", "detail": "Summarise my inbox"}]},
        {"id": "r1", "task_id": "tw1", "status": "success", "started_at": "2026-09-29T08:00:00Z",
         "finished_at": "2026-09-29T08:00:30Z", "steps": []},
        {"id": "r0", "task_id": "tw1", "status": "skipped", "result": "Dry run — nothing ran, nothing changed.",
         "started_at": "2026-09-28T08:00:00Z", "steps": [{"kind": "dry-run", "detail": "Would run a model."}]},
    ],
    "executions": {
        "r2": {"run": {"id": "r2", "status": "error"}, "nodes": [
            {"id": "x1", "node_id": "n1", "kind": "llm", "label": "Summarise my inbox", "seq": 1,
             "status": "error", "attempt": 1, "dry": False, "port": "error", "workflow_version": 3,
             "started_at": "2026-09-30T08:00:00Z", "finished_at": "2026-09-30T08:00:09Z",
             "input": {"source": "event", "event": "email_received", "at": "2026-09-30T07:59:58Z",
                       "data": {"subject": "<img src=x onerror=alert(1)> Your statement"}},
             "input_summary": "Triggered by email received — subject=Your statement",
             "output": {"text": "", "data": None}, "error": "RuntimeError: model unavailable\nTraceback…",
             "steps": [], "model": "local-llm"}]},
    },
}

_PREAMBLE = (
    "import { document, Node, server, net, fire, settle, host, nodeOf, fields, mountTaskFields, itemOf,"
    " shelf, sayOf, sayButton, by, typed, markup } from './shim.js';\n"
    "import { dismissTopMenu } from '../escMenuStack.js';\n"
    "server.tasks = %s;\n"
    "globalThis.__wf = %s;\n"
    "const W = globalThis.__wf;\n"
    "W.testReply = (b) => {\n"
    "  if (b.node && b.node.kind === 'action' && !b.confirm) return { outcome: 'needs_confirmation',\n"
    "    plan: ['Would run: web_fetch_digest — Fetch a page and summarise it', 'Would fetch https://example.com'],\n"
    "    effects: ['It reaches a site on the internet.'], input_used: null, dropped: [] };\n"
    "  return { outcome: 'ran', status: 'success', text: 'Three new statements; one fee change.',\n"
    "    data: null, steps: [{ kind: 'tool', tool: 'read', status: 'ok', detail: 'read 3 messages' }],\n"
    "    model: 'local-llm', took_ms: 840,\n"
    "    input_used: { source: 'event', event: 'email_received', at: 'x', data: { subject: 'Your statement' } },\n"
    "    dropped: [] };\n"
    "};\n"
    "const { mountAutomations, OFF_WORDS } = await import('./workflowRoom.js');\n"
    "const describeTrigger = (t) => t.trigger_words || (t.scheduled_time ? 'Daily at ' + t.scheduled_time : '');\n"
    "const room = async (o = {}) => {\n"
    "  const root = host();\n"
    "  const h = mountAutomations(root, { fetch: net, mountTaskFields, describeTrigger, ...o });\n"
    "  await h.ready; await settle(5);\n"
    "  return { root, h };\n"
    "};\n"
    "const openW = async (root, key = 'w1') => {\n"
    "  fire(root.querySelectorAll('.wf-shelf-item').find((b) => b.dataset.key === key), 'click');\n"
    "  await settle(10);\n"
    "};\n"
    "const named = (root, name) => root.querySelectorAll('button').find((b) => b.textContent === name && !b.hidden);\n"
    "const called = (name) => W.calls.filter((c) => c[0] === name);\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbroom")
    (root / "workbench").mkdir()
    sandbox = _make_sandbox(root / "workbench", ROOM_JS, _SHIM, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    # The workflow layer, faked to C3, where the room's `import()` finds it.
    (sandbox / "workflowApi.js").write_text(WORKFLOW_API_JS, encoding="utf-8")
    (sandbox / "workflowSource.js").write_text(WORKFLOW_SOURCE_JS, encoding="utf-8")
    return sandbox


def _case(box, script, world=None):
    return _run(box, _PREAMBLE % (json.dumps(_TASKS), json.dumps(world or _WORLD)), script)


def test_the_room_opens_on_the_chains_and_lists_every_workflow_on_the_shelf(box):
    o = _case(box, """
        const { root } = await room();
        out({ shelf: shelf(root), tasks: ['a', 'b', 'c'].map((id) => !!nodeOf(root, id)),
              pick: root.querySelector('.wf-shelf-select').querySelectorAll('option').map((x) => [x.value, x.textContent]),
              view: by(root, 'wf-view').hidden, listed: called('listWorkflows').length,
              aria: root.querySelectorAll('.wf-shelf-item')[1].getAttribute('aria-label') });
    """)
    assert o["shelf"][0] == {"key": "tasks", "text": "Tasks and chains|Every task, and the arrows between them",
                             "current": True}
    assert o["shelf"][1] == {"key": "w1", "text": "Morning brief|Off|✗|Last run: Failed", "current": False}
    assert o["aria"] == "Morning brief. Off. Last run: Failed."
    assert o["tasks"] == [True, True, True], "the chains canvas is the landing view, unchanged (P22-02)"
    assert o["pick"] == [["tasks", "Tasks and chains"], ["w1", "Morning brief (Off)"]]
    assert o["view"] is True and o["listed"] == 1


def test_a_workflow_opens_on_the_same_canvas_with_its_toolbar(box):
    o = _case(box, """
        const { root } = await room();
        await openW(root);
        out({ name: by(root, 'wf-name').value, sw: by(root, 'wf-switch').textContent,
              checked: by(root, 'wf-switch').getAttribute('aria-checked'), word: by(root, 'wf-switch-word').textContent,
              dirty: by(root, 'wf-dirty').textContent,
              items: ['__start__', 'n1', 'n2'].map((id) => itemOf(root, id) && itemOf(root, id).querySelector('.wb-node-title').textContent),
              tasksGone: !nodeOf(root, 'a'), shelf: shelf(root).map((s) => s.current),
              tabs: root.querySelectorAll('.wf-tab').map((t) => [t.textContent, t.getAttribute('aria-selected')]),
              buttons: ['Save', 'Versions…', 'Run now', 'Show me what this would do'].map((n) => !!named(root, n)) });
    """)
    assert o["name"] == "Morning brief"
    assert (o["sw"], o["checked"]) == ("Off", "false")
    assert o["word"] == "Switched off — it will not run until you switch it on."
    assert o["dirty"] == ""
    assert o["items"] == ["Starts · Daily at 08:00", "Summarise my inbox", "Send me the summary"]
    assert o["tasksGone"] is True and o["shelf"] == [False, True]
    assert o["tabs"] == [["Edit", "true"], ["Runs", "false"]]
    assert o["buttons"] == [True, True, True, True]


def test_save_goes_through_the_source_and_a_stale_save_offers_to_open_it_again(box):
    o = _case(box, """
        const { root } = await room();
        await openW(root);
        typed(by(root, 'wf-name'), 'Morning inbox brief');
        const dirty = by(root, 'wf-dirty').textContent;
        fire(by(root, 'wf-save'), 'click'); await settle(10);
        const saved = { said: sayOf(root), dirty: by(root, 'wf-dirty').textContent, put: called('saveWorkflow') };
        W.workflows[0].version = 9;                    // saved elsewhere meanwhile
        typed(by(root, 'wf-name'), 'Morning brief again');
        fire(by(root, 'wf-save'), 'click'); await settle(10);
        const stale = { said: sayOf(root), action: sayButton(root) && sayButton(root).textContent };
        fire(sayButton(root), 'click'); await settle(20);
        out({ dirty, saved, stale, reopened: { said: sayOf(root), name: by(root, 'wf-name').value, discards: W.discarded } });
    """)
    assert o["dirty"] == "Unsaved changes"
    assert o["saved"]["put"][0][2]["baseVersion"] == 3, "the save starts from the version it was opened at"
    assert o["saved"]["said"] == "Saved as version 4. It is switched off, so it will not run until you switch it on."
    assert o["saved"]["dirty"] == "Saved"
    assert o["stale"]["said"].startswith("Not saved: This workflow was saved somewhere else since you opened it")
    assert o["stale"]["action"] == "Open it again"
    assert o["reopened"]["said"] == "This is the workflow as it is saved now. Your changes were not kept."
    assert o["reopened"]["discards"] == 1


def test_leaving_with_unsaved_changes_asks_and_escape_keeps_editing(box):
    o = _case(box, """
        const { root, h } = await room();
        await openW(root);
        typed(by(root, 'wf-name'), 'Changed');
        fire(by(root, 'wf-shelf-tasks'), 'click'); await settle(5);
        const ask = by(root, 'wf-ask');
        const asked = { shown: !ask.hidden, text: ask.querySelector('.wf-ask-text').textContent,
          buttons: ask.querySelectorAll('button').map((b) => b.textContent), stillHere: !by(root, 'wf-view').hidden,
          layer: root.dataset.escLayer || null };
        dismissTopMenu(); await settle(5);
        const kept = { hidden: ask.hidden, still: !by(root, 'wf-view').hidden, said: sayOf(root) };
        fire(by(root, 'wf-shelf-tasks'), 'click'); await settle(5);
        fire(named(root, 'Discard'), 'click'); await settle(10);
        const discarded = { tasks: !!nodeOf(root, 'a'), discards: W.discarded };
        await openW(root);
        typed(by(root, 'wf-name'), 'Changed again');
        let closed = 0;
        const can = h.canClose(() => { closed += 1; });
        fire(named(root, 'Save'), 'click'); await settle(10);
        out({ asked, kept, discarded, can, closed, saves: called('saveWorkflow').length,
              clean: h.canClose(() => { closed += 100; }) });
    """)
    assert o["asked"] == {"shown": True, "text": "“Changed” has changes that are not saved.",
                          "buttons": ["Save", "Discard", "Keep editing"], "stillHere": True, "layer": "open"}
    assert o["kept"] == {"hidden": True, "still": True, "said": "Kept. Nothing was saved or dropped."}
    assert o["discarded"] == {"tasks": True, "discards": 1}
    assert o["can"] is False and o["closed"] == 1 and o["saves"] == 1, "Save, then the window closes"
    assert o["clean"] is True


def test_a_chain_made_a_workflow_is_switched_on_and_the_chain_put_back_with_one_click(box):
    o = _case(box, """
        const { root } = await room();
        fire(nodeOf(root, 'a'), 'click'); await settle(5);
        const offer = sayButton(root) && sayButton(root).textContent;
        fire(sayButton(root), 'click'); await settle(20);
        const made = { call: called('createWorkflow'), said: sayOf(root), name: by(root, 'wf-name').value,
                       sw: by(root, 'wf-switch').textContent };
        fire(by(root, 'wf-switch'), 'click'); await settle(10);
        const on = { said: sayOf(root), action: sayButton(root) && sayButton(root).textContent,
                     sw: by(root, 'wf-switch').getAttribute('aria-checked'), chainBtn: !by(root, 'wf-chain-back').hidden };
        fire(sayButton(root), 'click'); await settle(10);
        out({ offer, made, on, back: { said: sayOf(root), sw: by(root, 'wf-switch').getAttribute('aria-checked'),
              chainBtn: !by(root, 'wf-chain-back').hidden, calls: called('restoreChain').length } });
    """)
    assert o["offer"] == "Make this chain a workflow"
    assert o["made"]["call"] == [["createWorkflow", {"fromTaskId": "a"}]]
    assert o["made"]["said"] == ("Made “Nightly backup (workflow)” from 3 steps. It is switched off, "
                                 "and the chain still runs as before.")
    assert o["made"]["name"] == "Nightly backup (workflow)" and o["made"]["sw"] == "Off"
    assert o["on"]["said"] == "Switched on. The chain’s first step, “Nightly backup”, is paused so the two do not both run."
    assert o["on"]["action"] == "Put the old chain back" and o["on"]["sw"] == "true" and o["on"]["chainBtn"] is True
    assert o["back"] == {"said": "The chain runs again and this workflow is switched off. Nothing was deleted.",
                         "sw": "false", "chainBtn": False, "calls": 1}


def test_a_failed_run_opens_on_its_failed_step_with_what_it_was_handed_open(box):
    o = _case(box, """
        const { root } = await room();
        await openW(root);
        fire(root.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs'), 'click'); await settle(20);
        const list = root.querySelectorAll('.wf-run-item').map((b) => [b.dataset.runId,
          b.querySelector('.wf-run-word').textContent, b.getAttribute('aria-current')]);
        const run = by(root, 'wf-run-canvas');
        const rec = run.querySelector('.wf-record');
        const parts = rec.querySelectorAll('details').map((d) => [d.querySelector('summary').textContent, !!d.open]);
        out({ list, listed: called('listExecutions'), said: sayOf(root),
              readOnly: run._classes().includes('wb-read-only'), ports: run.querySelectorAll('.wb-port').length,
              head: rec.querySelector('.wf-record-head').textContent, parts,
              handed: rec.querySelector('.wf-record-input').querySelector('pre').textContent,
              summary: rec.querySelector('.wf-record-summary').textContent,
              error: rec.querySelector('.wf-record-error').querySelector('pre').textContent,
              selected: !!itemOf(run, 'n1') && itemOf(run, 'n1')._classes().includes('wb-node-selected'),
              markup: markup(root) });
    """)
    assert o["listed"] == [["listExecutions", "tw1", {"limit": 30}]]
    assert o["list"] == [["r2", "Failed", "true"], ["r1", "Success", None], ["r0", "Dry run", None]]
    assert o["readOnly"] is True and o["ports"] == 0
    assert o["selected"] is True, "the failed step is the one opened, without being told where to look"
    assert o["said"] == "“Summarise my inbox” failed: RuntimeError: model unavailable. Its panel is open at What it was handed."
    assert o["head"] == "✗Failed"
    assert o["parts"][0] == ["What it was handed", True] and ["What went wrong", True] in o["parts"]
    assert '"subject": "<img src=x onerror=alert(1)> Your statement"' in o["handed"]
    assert o["summary"] == "Triggered by email received — subject=Your statement"
    assert o["error"].startswith("RuntimeError: model unavailable")
    assert o["markup"] == [], "every value of a run is text"


def test_testing_a_step_that_does_something_real_asks_first_and_runs_nothing_else(box):
    o = _case(box, """
        const { root } = await room();
        await openW(root);
        fire(itemOf(root, 'n2'), 'click'); await settle(5);
        const form = fields.mounts[fields.mounts.length - 1].args;
        const sel = by(root, 'wf-test-source');
        const sources = sel.querySelectorAll('option').map((x) => x.value);
        sel.value = 'custom'; sel.dispatchEvent({ type: 'change', target: sel });
        typed(by(root, 'wf-test-input'), '{"subject": "Your statement is ready"}');
        fire(by(root, 'wf-test-go'), 'click'); await settle(10);
        const confirm = by(root, 'wf-test-confirm');
        const asked = { shown: !confirm.hidden,
          plan: by(confirm, 'wf-test-plan').querySelectorAll('li').map((l) => l.textContent),
          effects: by(confirm, 'wf-test-effects').querySelectorAll('li').map((l) => l.textContent),
          calls: called('testNode').map((c) => c[3].confirm), said: by(root, 'wf-test-say').textContent };
        fire(named(root, 'Run it for real'), 'click'); await settle(10);
        const result = by(root, 'wf-test-result');
        out({ form: { mode: form.mode, task: form.task }, sources, asked,
              ran: { calls: called('testNode').map((c) => [c[2], c[3].source, c[3].confirm, c[3].input]),
                     outcome: result.querySelector('.wf-test-outcome').textContent,
                     made: result.querySelector('pre').textContent,
                     alone: result.querySelector('.wf-test-alone').textContent },
              other: W.calls.map((c) => c[0]).filter((n) => !['listWorkflows', 'getWorkflow', 'testNode'].includes(n)) });
    """)
    assert o["form"]["mode"] == "node"
    assert o["form"]["task"] == {"action": "web_fetch_digest", "prompt": "https://example.com",
                                 "name": "Send me the summary", "task_type": "action"}
    assert o["sources"] == ["last", "custom", "example", "none"], "no pinned sample yet, so none offered"
    assert o["asked"]["shown"] is True and o["asked"]["calls"] == [False]
    assert o["asked"]["plan"] == ["Would run: web_fetch_digest — Fetch a page and summarise it",
                                  "Would fetch https://example.com"]
    assert o["asked"]["effects"] == ["It reaches a site on the internet."]
    assert o["asked"]["said"] == "Nothing has run yet."
    assert o["ran"]["calls"] == [["n2", "custom", False, {"subject": "Your statement is ready"}],
                                 ["n2", "custom", True, {"subject": "Your statement is ready"}]]
    assert o["ran"]["outcome"].startswith("✓Test: Success · 840 ms")
    assert o["ran"]["made"] == "Three new statements; one fee change."
    assert o["ran"]["alone"] == "Nothing else ran: no other step, no delivery, no notification."
    assert o["other"] == [], "a test runs one step: no run, no save, no switch"


def test_cancelling_the_confirmation_runs_nothing(box):
    o = _case(box, """
        const { root } = await room();
        await openW(root);
        fire(itemOf(root, 'n2'), 'click'); await settle(5);
        fire(by(root, 'wf-test-go'), 'click'); await settle(10);
        fire(by(root, 'wf-test-no'), 'click'); await settle(5);
        out({ calls: called('testNode').length, said: by(root, 'wf-test-say').textContent,
              result: by(root, 'wf-test-result').hidden, confirm: by(root, 'wf-test-confirm').hidden });
    """)
    assert o == {"calls": 1, "said": "Not tested. Nothing ran.", "result": True, "confirm": True}


def test_a_pinned_sample_is_marked_and_says_a_scheduled_run_never_uses_it(box):
    o = _case(box, """
        const { root } = await room();
        await openW(root);
        fire(itemOf(root, 'n1'), 'click'); await settle(5);
        const sel = by(root, 'wf-test-source');
        sel.value = 'example'; sel.dispatchEvent({ type: 'change', target: sel });
        fire(by(root, 'wf-test-go'), 'click'); await settle(10);
        const pinShown = !by(root, 'wf-test-pin').hidden;
        fire(by(root, 'wf-test-pin'), 'click'); await settle(10);
        const pinned = { said: by(root, 'wf-test-say').textContent, call: called('savePins'),
          mark: itemOf(root, 'n1').querySelectorAll('.wb-node-badge').map((b) => b.textContent),
          sources: by(root, 'wf-test-source').querySelectorAll('option').map((x) => x.value),
          note: by(root, 'wf-test-pin-note').textContent, panelOpen: !root.querySelector('.wb-panel').hidden };
        fire(by(root, 'wf-test-unpin'), 'click'); await settle(10);
        out({ pinShown, pinned, unpinned: { said: by(root, 'wf-test-say').textContent, call: called('savePins')[1],
              mark: itemOf(root, 'n1').querySelectorAll('.wb-node-badge').length },
              versions: called('saveWorkflow').length });
    """)
    assert o["pinShown"] is True
    p = o["pinned"]
    assert p["call"] == [["savePins", "w1", {"n1": {"subject": "Your statement"}}]], \
        "the fields the test was handed are pinned, not the envelope around them"
    assert p["said"] == "Pinned. A pinned sample is only used when you press Test. Scheduled runs never use it."
    assert p["note"] == "A pinned sample is only used when you press Test. Scheduled runs never use it."
    assert p["mark"] == ["Sample pinned"], "the canvas marks the step"
    assert p["sources"][:2] == ["last", "pinned"] and p["panelOpen"] is True
    assert o["unpinned"] == {"said": "Unpinned. Test uses another input now.",
                             "call": ["savePins", "w1", {"n1": None}], "mark": 0}
    assert o["versions"] == 0, "a pin is never a version"


def test_the_palette_adds_a_step_by_kind_and_escape_adds_nothing(box):
    o = _case(box, """
        const { root } = await room();
        await openW(root);
        const add = root.querySelectorAll('.wb-tool-new').find((b) => !b.hidden);
        fire(add, 'click'); await settle(5);
        const pal = by(root, 'wf-palette');
        const kinds = pal.querySelectorAll('.wf-palette-kind').map((b) => b.querySelector('.wf-palette-word').textContent);
        const first = pal.querySelectorAll('.wf-palette-kind')[0];
        fire(pal, 'keydown', { key: 'ArrowDown', target: first });   // keys reach the box (no bubbling here)
        const moved = pal.querySelectorAll('.wf-palette-kind')[1].focused === true;
        dismissTopMenu(); await settle(10);
        const escaped = { gone: !by(root, 'wf-palette'), steps: root.querySelectorAll('.wb-node').length };
        fire(add, 'click'); await settle(5);
        fire(by(root, 'wf-palette').querySelectorAll('.wf-palette-kind')[1], 'click'); await settle(20);
        const form = fields.mounts[fields.mounts.length - 1].args;
        out({ kinds, moved, escaped, steps: root.querySelectorAll('.wb-node').length,
              form: { mode: form.mode, kind: form.task.task_type }, dirty: by(root, 'wf-dirty').textContent });
    """)
    assert o["kinds"] == ["Prompt", "Research", "Action", "Run task"]
    assert o["moved"] is True, "the arrow keys go between the kinds"
    assert o["escaped"] == {"gone": True, "steps": 3}
    assert o["steps"] == 4 and o["form"] == {"mode": "node", "kind": "research"}
    assert o["dirty"] == "Unsaved changes"


def test_new_workflow_is_named_then_made_switched_off(box):
    o = _case(box, """
        const { root } = await room();
        fire(by(root, 'wf-shelf-new'), 'click'); await settle(5);
        const form = !by(root, 'wf-new').hidden;
        by(root, 'wf-new-name').value = 'Bank mail';
        fire(by(root, 'wf-new-go'), 'click'); await settle(20);
        out({ form, call: called('createWorkflow'), said: sayOf(root), name: by(root, 'wf-name').value,
              shelf: shelf(root).map((s) => [s.key, s.current]) });
    """)
    assert o["form"] is True
    assert o["call"] == [["createWorkflow", {"name": "Bank mail"}]]
    assert o["said"] == "Made “Bank mail”. It is switched off: it will not run until you switch it on."
    assert o["name"] == "Bank mail"
    assert o["shelf"] == [["tasks", False], ["w1", False], ["w2", True]]


def test_versions_can_be_looked_at_and_put_back(box):
    o = _case(box, """
        const { root } = await room();
        await openW(root);
        fire(by(root, 'wf-versions'), 'click'); await settle(5);
        const rows = root.querySelectorAll('.wf-versions-row').map((r) => r.querySelectorAll('button').map((b) => b.textContent));
        fire(root.querySelectorAll('.wf-versions-look')[1], 'click'); await settle(10);
        const looking = { bar: !by(root, 'wf-viewing').hidden, text: by(root, 'wf-viewing-text').textContent,
          save: by(root, 'wf-save').disabled, readOnly: by(root, 'wf-edit')._classes().includes('wb-read-only') };
        fire(by(root, 'wf-viewing-restore'), 'click'); await settle(10);
        out({ rows, looking, call: called('restoreVersion'), said: sayOf(root), bar: by(root, 'wf-viewing').hidden });
    """)
    assert o["rows"] == [["Look at it"], ["Look at it", "Put this version back"]], "the one in use is not put back"
    assert o["looking"] == {"bar": True, "text": "You are looking at version 2. It cannot be changed here.",
                            "save": True, "readOnly": True}
    assert o["call"] == [["restoreVersion", "w1", 2, 3]]
    assert o["said"] == "Version 2 is back, saved as version 4. Nothing was lost: the version before it is still in Versions…."
    assert o["bar"] is True


def test_a_workflows_own_start_opens_its_document(box):
    o = _case(box, """
        const { root, h } = await room({ focusId: 'tw1' });
        const first = { name: by(root, 'wf-name').value, view: !by(root, 'wf-view').hidden };
        h.focusChain('a'); await settle(10);
        out({ first, back: !!nodeOf(root, 'a'), current: shelf(root)[0].current });
    """)
    assert o["first"] == {"name": "Morning brief", "view": True}, "⋮ → Workflow on a workflow's card opens it"
    assert o["back"] is True and o["current"] is True


def test_a_workflows_start_on_the_tasks_canvas_opens_its_document(box):
    # Design § 6.1: on the tasks canvas, a task that starts a workflow reads
    # "Workflow · …" and opens its document, not the task form (which cannot
    # edit a document of steps); a door naming that task does the same.
    o = _case(box, """
        server.tasks.push({ id: 'tw1', name: 'Morning brief', task_type: 'workflow', status: 'paused',
          trigger_words: 'Daily at 08:00', workflow_id: 'w1', then_task_id: null, else_task_id: null });
        const { root, h } = await room();
        const sub = nodeOf(root, 'tw1').querySelector('.wb-node-sub').textContent;
        fire(nodeOf(root, 'tw1'), 'click'); await settle(20);
        const clicked = { name: by(root, 'wf-name').value, view: !by(root, 'wf-view').hidden,
          forms: fields.mounts.length };
        h.focusChain('a'); await settle(10);
        const back = !!nodeOf(root, 'a');
        h.focusChain('tw1'); await settle(20);
        out({ sub, clicked, back, door: { name: by(root, 'wf-name').value, view: !by(root, 'wf-view').hidden } });
    """)
    assert o["sub"] == "Workflow · Daily at 08:00 · paused"
    assert o["clicked"] == {"name": "Morning brief", "view": True, "forms": 0}
    assert o["back"] is True
    assert o["door"] == {"name": "Morning brief", "view": True}

def test_when_the_workflow_layer_cannot_load_every_chain_still_works(box):
    o = _case(box, """
        const { root } = await room({ loadWorkflowModules: () => Promise.reject(new Error('Failed to fetch dynamically imported module')) });
        fire(nodeOf(root, 'a'), 'click'); await settle(5);
        out({ tasks: ['a', 'b', 'c'].map((id) => !!nodeOf(root, id)), note: by(root, 'wf-shelf-note').textContent,
              newDisabled: by(root, 'wf-shelf-new').disabled, panel: !root.querySelector('.wb-panel').hidden,
              shelf: shelf(root).map((s) => s.key) });
    """)
    assert o["tasks"] == [True, True, True] and o["panel"] is True
    assert o["note"] == ("Your workflows could not be loaded (Failed to fetch dynamically imported module). "
                         "The tasks and chains still work.")
    assert o["newDisabled"] is True and o["shelf"] == ["tasks"]


def test_closing_the_window_with_an_edited_step_open_asks_once(box):
    # The window's close asks the room (`canClose`), and once the question is
    # answered the room closes the window — which asks the room again. After
    # Discard the open step's form still holds what was typed in it, so the
    # second ask must not be a second question.
    o = _case(box, """
        const { root, h } = await room();
        await openW(root);
        fire(itemOf(root, 'n1'), 'click'); await settle(5);
        const ph = root.querySelector('.wb-panel-host');
        ph.dispatchEvent({ type: 'input', target: ph, stopPropagation() {}, preventDefault() {} });
        let closed = 0;
        const close = () => { if (h.canClose(close)) closed += 1; };
        close();
        const asked = { text: by(root, 'wf-ask').querySelector('.wf-ask-text').textContent, closed };
        fire(named(root, 'Discard'), 'click'); await settle(10);
        out({ asked, closed, askShown: !by(root, 'wf-ask').hidden, discards: W.discarded });
    """)
    assert o["asked"] == {"text": "“Morning brief” has changes that are not saved. The open step’s own changes "
                                  "are only kept if you press Done in it first.", "closed": 0}
    assert o["closed"] == 1 and o["askShown"] is False and o["discards"] == 1


def test_a_workflow_that_cannot_be_read_says_so_and_the_chains_stay(box):
    o = _case(box, """
        const { root, h } = await room();
        h.openWorkflow('w404'); await settle(20);
        out({ said: sayOf(root), tasks: ['a', 'b', 'c'].map((id) => !!nodeOf(root, id)),
              view: by(root, 'wf-view').hidden, current: shelf(root)[0].current });
    """)
    assert o["said"] == "That workflow could not be opened: Workflow not found."
    assert o["tasks"] == [True, True, True] and o["view"] is True and o["current"] is True


def test_a_run_that_worked_after_a_handled_failure_is_not_opened_as_a_failure(box):
    world = json.loads(json.dumps(_WORLD))
    world["runs"] = [{"id": "r3", "task_id": "tw1", "status": "success",
                      "started_at": "2026-10-01T08:00:00Z", "finished_at": "2026-10-01T08:00:20Z", "steps": []}]
    world["executions"] = {"r3": {"run": {"id": "r3", "status": "success"}, "nodes": [
        {"id": "x1", "node_id": "n1", "kind": "llm", "label": "Summarise my inbox", "seq": 1, "status": "error",
         "port": "error", "input": None, "output": {"text": ""}, "error": "RuntimeError: busy", "steps": []},
        {"id": "x2", "node_id": "n2", "kind": "action", "label": "Send me the summary", "seq": 2,
         "status": "success", "port": "success", "input": None, "output": {"text": "sent"}, "steps": []}]}}
    o = _case(box, """
        const { root } = await room();
        await openW(root);
        fire(root.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs'), 'click'); await settle(20);
        const run = by(root, 'wf-run-canvas');
        out({ said: sayOf(root), panel: !run.querySelector('.wb-panel').hidden,
              marks: ['n1', 'n2'].map((id) => itemOf(run, id).dataset.outcome) });
    """, world)
    assert o["marks"] == ["error", "ok"], "the step that failed still reads failed"
    assert o["panel"] is False, "a run that worked is not opened as a failure"
    assert o["said"] == "This run worked. Open a step to read what it was handed and what it made."
