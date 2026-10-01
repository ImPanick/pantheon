# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-05` (wf-ui) — the doors from the Tasks window and the window's own close, for a workflow.

A workflow is a document of steps started by one task (`task_type="workflow"`,
`D-2026-10-01-05` §1). That task is listed in the Tasks window like any other,
so its card is a door to the document:

  * its *Edit* — the kebab's and the card's — opens the workflow in the
    Workbench rather than the task form, which cannot edit a document of steps
    and would offer to make it a Prompt; the kebab says so ("Edit in the
    Workbench");
  * ⋮ → *Workflow* opens the Workbench on the document itself (`workflowId`,
    the key `GET /api/tasks` adds to the row), and an ordinary task's door is
    unchanged (`Law 1`);
  * a run's per-step line in History reads "step", never "node" (design § 2.4,
    § 6.6: a word a person never meets).

And the window: `closeWorkbench` asks the room first (`canClose`), so unsaved
work is asked about whichever door closes it — the close button, Escape's
arbiter (which presses it), the dock — and the window closes once answered;
`openWorkbench({ workflowId })` opens the room on that document, and a second
door press while it is open moves to it.

Driven: the real `tasks.js` in the Tasks sandbox the kebab's other cases use,
with the Workbench recorded; the real `workbench.js` glue, with the real room,
canvas and task source, in the window test's harness, and the workflow layer
faked to C3 (`tests/helpers/workflow_fakes.py`) where the room's `import()`
finds it.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_palette_moves_to_the_server_js import _SHIM as _TASKS_SHIM  # noqa: E402
from test_the_workbench_window_js import (  # noqa: E402
    _TASKS_STUBS_WB, _EXPORT, _GLUE_SHIM, _GLUE_STUBS, _UP, _window_tree,
)
from helpers.workflow_fakes import WORKFLOW_API_JS, WORKFLOW_SOURCE_JS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
TASKS_JS = JS / "tasks.js"
WORKBENCH_JS = JS / "workbench" / "workbench.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the Tasks window's doors ────────────────────────────────────────────────

_STUBS = dict(_TASKS_STUBS_WB)
_STUBS["workbench/workbench.js"] = (
    "globalThis.__opened = [];\n"
    "export function openWorkbench(o) { globalThis.__opened.push({ focusId: o.focusId,\n"
    "  workflowId: o.workflowId == null ? null : o.workflowId,\n"
    "  words: typeof o.describeTrigger === 'function' ? o.describeTrigger({ trigger_type: 'webhook' }) : null });\n"
    "  return true; }\n"
)
_TASKS_EXPORT = _EXPORT.replace("_renderList };", "_renderList, renderRunSteps: _renderRunSteps };")


@pytest.fixture(scope="module")
def tasks_box(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("wfcard"), TASKS_JS, _TASKS_SHIM, _STUBS)
    copy = box / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + _TASKS_EXPORT, encoding="utf-8")
    return box


_SERVED = {
    "tasks": [
        {"id": "tw", "name": "Morning brief", "task_type": "workflow", "status": "paused", "workflow_id": "w1",
         "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "08:00",
         "then_task_id": None, "else_task_id": None, "run_count": 0},
        {"id": "a", "name": "Nightly backup", "task_type": "llm", "status": "active",
         "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "02:00",
         "then_task_id": None, "else_task_id": None, "run_count": 0},
    ],
    "graph": {"nodes": [{"id": "tw", "name": "Morning brief"}, {"id": "a", "name": "Nightly backup"}],
              "edges": [], "conditions": ["success", "error"], "max_depth": 10},
}

_CARDS = """
import { document, Node, mockFetch, res, tick } from './shim.js';
// The form's and the step list's own markup is what is read (the shim parses it).
import { installHtmlParsing } from './dom.js';
installHtmlParsing();
const { __k } = await import('./tasks.js');
mockFetch(async () => res(200, %s));
await __k._fetchTasks();
const modal = document.body.appendChild(new Node('div'));
modal.setAttribute('id', 'tasks-modal');
const body = modal.appendChild(new Node('div'));
body.className = 'modal-body';
const list = body.appendChild(new Node('div'));
list.setAttribute('id', 'tasks-list');
__k._renderList();
const ev = { stopPropagation() {}, preventDefault() {} };
const card = (id) => list.querySelectorAll('.task-card').find((c) => c.dataset.id === id);
const menu = () => document.querySelectorAll('.task-dropdown').slice(-1)[0];
const openMenu = (id) => card(id).querySelector('.memory-item-btn').dispatchEvent({ type: 'click', ...ev });
const item = (label) => menu().children.find((b) => b.textContent === label);
const formShown = () => !!document.querySelector('#task-form-save');
""" % json.dumps(_SERVED)


def test_a_workflows_edit_opens_its_document_in_the_workbench(tasks_box):
    o = _run(tasks_box, _CARDS, """
        openMenu('tw');
        const labels = menu().children.map((b) => b.textContent);
        item('Edit in the Workbench').dispatchEvent({ type: 'click', ...ev });
        await tick();
        const byKebab = { opened: globalThis.__opened.slice(), form: formShown() };
        const editBtn = card('tw').querySelector('.task-detail-edit-btn');
        const title = editBtn.title;
        editBtn.dispatchEvent({ type: 'click', ...ev });
        await tick();
        console.log(JSON.stringify({ labels, byKebab, title, opened: globalThis.__opened, form: formShown() }));
    """)
    assert "Edit in the Workbench" in o["labels"] and "Edit" not in o["labels"]
    assert o["byKebab"] == {"opened": [{"focusId": "tw", "workflowId": "w1", "words": "Webhook"}], "form": False}
    assert o["title"] == "Open this workflow in the Workbench"
    assert o["opened"][1] == {"focusId": "tw", "workflowId": "w1", "words": "Webhook"}
    assert o["form"] is False, "the task form is not offered for a document of steps"


def test_an_ordinary_tasks_doors_are_unchanged(tasks_box):
    o = _run(tasks_box, _CARDS, """
        openMenu('a');
        const labels = menu().children.map((b) => b.textContent);
        item('Workflow').dispatchEvent({ type: 'click', ...ev });
        await tick();
        const opened = globalThis.__opened.slice();
        openMenu('a');
        item('Edit').dispatchEvent({ type: 'click', ...ev });
        await tick();
        console.log(JSON.stringify({ labels, opened, form: formShown(), after: globalThis.__opened.length }));
    """)
    assert "Edit" in o["labels"] and "Edit in the Workbench" not in o["labels"]
    assert o["opened"] == [{"focusId": "a", "workflowId": None, "words": "Webhook"}]
    assert o["form"] is True and o["after"] == 1, "Edit on a task is still the task form"


def test_a_workflow_door_opens_the_document_itself(tasks_box):
    o = _run(tasks_box, _CARDS, """
        openMenu('tw');
        item('Workflow').dispatchEvent({ type: 'click', ...ev });
        await tick();
        console.log(JSON.stringify({ opened: globalThis.__opened }));
    """)
    assert o["opened"] == [{"focusId": "tw", "workflowId": "w1", "words": "Webhook"}]


def test_a_workflow_runs_steps_read_step_in_history(tasks_box):
    o = _run(tasks_box, _CARDS, """
        const html = __k.renderRunSteps({ steps: [
          { kind: 'trigger', detail: 'Started on schedule' },
          { kind: 'node', node: 'n1', label: 'Summarise my inbox', status: 'success', detail: 'Summarise my inbox — worked' },
        ] });
        const box = document.body.appendChild(new Node('div'));
        box.innerHTML = html;
        console.log(JSON.stringify({ words: box.querySelectorAll('.task-run-step-kind').map((s) => s.textContent) }));
    """)
    assert o["words"] == ["cause", "step"], "a workflow's step is a step, never a node"


# ── the window: closing asks the room; a door to a document ──────────────────

_WORLD = {
    "calls": [],
    "tasks": [{"id": "tw", "name": "Morning brief", "task_type": "workflow", "status": "paused",
               "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "08:00", "workflow_id": "w1"}],
    "workflows": [{"id": "w1", "name": "Morning brief", "task_id": "tw", "version": 2,
                   "graph": {"v": 1, "start": {"position": None}, "nodes": [
                       {"id": "n1", "kind": "llm", "label": "Summarise my inbox",
                        "config": {"prompt": "Summarise my unread mail"}, "pinned": None}], "edges": []}}],
}


@pytest.fixture(scope="module")
def glue(tmp_path_factory):
    root = tmp_path_factory.mktemp("wfglue")
    (root / "workbench").mkdir()
    shim = _GLUE_SHIM.replace("__TREE__", json.dumps(_window_tree()))
    sandbox = _make_sandbox(root / "workbench", WORKBENCH_JS, shim, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    for rel, src in _GLUE_STUBS.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(src, encoding="utf-8")
    (sandbox / "workflowApi.js").write_text(WORKFLOW_API_JS, encoding="utf-8")
    (sandbox / "workflowSource.js").write_text(WORKFLOW_SOURCE_JS, encoding="utf-8")
    return sandbox


_GLUE_PREAMBLE = (
    "import { document, modal, server, fire, settle, $ } from './shim.js';\n"
    "globalThis.__wf = %s;\n"
    "const wb = await import('./workbench.js');\n"
    "const room = () => $('workbench-room');\n"
    "const nodeOf = (id) => room().querySelectorAll('.wb-node').find((n) => n.dataset.taskId === id);\n"
    "const by = (cls) => room().querySelector('.' + cls);\n"
    "const named = (name) => room().querySelectorAll('button').find((b) => b.textContent === name && !b.hidden);\n"
    "const typeInPanel = () => { const h = room().querySelector('.wb-panel-host');\n"
    "  h.dispatchEvent({ type: 'input', target: h, stopPropagation() {}, preventDefault() {} }); };\n"
    "const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };\n"
) % json.dumps(_WORLD)


def test_closing_with_an_edited_step_asks_and_closes_once_answered(glue):
    o = _run(glue, _GLUE_PREAMBLE, """
        wb.openWorkbench({});
        await settle(20);
        fire(nodeOf('a'), 'click');
        typeInPanel();
        fire($('workbench-close'), 'click');
        await settle(5);
        const asked = { open: wb.isWorkbenchOpen(), hidden: modal._classes().includes('hidden'),
          ask: !by('wf-ask').hidden, text: by('wf-ask').querySelector('.wf-ask-text').textContent,
          buttons: by('wf-ask').querySelectorAll('button').map((b) => b.textContent),
          form: !globalThis.__fields[0].destroyed };
        fire(named('Discard'), 'click');
        await settle(300);
        out({ asked, closed: { open: wb.isWorkbenchOpen(), hidden: modal._classes().includes('hidden'),
          form: globalThis.__fields[0].destroyed } });
    """)
    assert o["asked"] == {"open": True, "hidden": False, "ask": True,
                          "text": "The open step has changes that are not saved.",
                          "buttons": ["Discard", "Keep editing"], "form": True}
    assert o["closed"] == {"open": False, "hidden": True, "form": True}


def test_closing_with_nothing_unsaved_closes_at_once(glue):
    o = _run(glue, _GLUE_PREAMBLE, """
        wb.openWorkbench({});
        await settle(20);
        fire(nodeOf('a'), 'click');
        fire($('workbench-close'), 'click');
        out({ open: wb.isWorkbenchOpen() });
    """)
    assert o == {"open": False}


def test_a_door_to_a_document_opens_it_and_a_second_press_moves_to_it(glue):
    o = _run(glue, _GLUE_PREAMBLE, """
        wb.openWorkbench({ workflowId: 'w1' });
        await settle(30);
        const first = { name: by('wf-name').value, view: !by('wf-view').hidden,
          steps: room().querySelectorAll('.wb-node').map((n) => n.dataset.itemId) };
        fire(room().querySelectorAll('.wf-shelf-item').find((b) => b.dataset.key === 'tasks'), 'click');
        await settle(20);
        const back = { tasks: !!nodeOf('a'), view: by('wf-view').hidden };
        wb.openWorkbench({ workflowId: 'w1' });
        await settle(30);
        out({ first, back, again: { name: by('wf-name').value, view: !by('wf-view').hidden } });
    """)
    assert o["first"] == {"name": "Morning brief", "view": True, "steps": ["__start__", "n1"]}
    assert o["back"] == {"tasks": True, "view": True}
    assert o["again"] == {"name": "Morning brief", "view": True}
