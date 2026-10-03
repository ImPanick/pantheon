# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1102` — a plain task's question is put in front of the person by the same
notice a workflow step's is, and answered at the task's own door.

The scheduler puts a parked plain Prompt task's card on its notification queue
as `review: { kind: "task_approval", task_id, task, run_id, node_id, item,
label, since, approval }`; `tasks.js`'s poll hands it to
`workflowApprovalNotice.js` (one notice for "a run is waiting for your yes",
`Law 14`), which answers it at `POST /api/tasks/{id}/runs/{run_id}/answer` with
`approve_task` or `deny` and offers it again on load from
`GET /api/tasks/waiting`. A workflow step's question is unchanged
(`tests/test_a_workflow_question_is_answered_from_the_notice_js.py`).

Driven: the real `workflowApprovalNotice.js`, `approvalBox.js` and
`escMenuStack.js` in the DOM shim, the network a recorder at `fetch`; and
`tasks.js`'s notification poll cut out of the shipped file (`js_function`).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_cw_fake import build_sandbox  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub  # noqa: E402
from tests.helpers.js_source import js_function  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_UI = ui_default_stub(
    "showToast: (m, o) => { calls.toasts.push([String(m), o && o.action ? o.action : null]); "
    "if (o && o.onAction) calls.actions.push(o.onAction); },\n"
    "  showError: (m) => { calls.errors.push(String(m)); },",
    exports="export const calls = { toasts: [], errors: [], actions: [] };")

_WORKBENCH = (
    "export const opened = [];\n"
    "export function openWorkbench(o) { opened.push({ workflowId: o.workflowId, runId: o.runId }); return true; }\n"
)

_REVIEW = {
    "kind": "task_approval", "task_id": "t1", "task": "Morning replies", "run_id": "r1",
    "node_id": "task", "item": None, "label": "Morning replies", "since": "2026-10-02T03:12:00Z",
    "approval": {"approval_id": "ap1", "question": "Allow this exact action once? <img src=x onerror=alert(1)>",
                 "action": {"tool": "bash", "content": "printf reply-sent",
                            "effects": ["execute_code"], "digest": "ab12cd34"}},
}

_PREAMBLE = (
    "import { document, fire, settle, markup } from './shim.js';\n"
    "import { calls as ui } from '../ui.js';\n"
    "import { opened } from './workbench.js';\n"
    "import { dismissTopMenu } from '../escMenuStack.js';\n"
    "const notice = await import('../workflowApprovalNotice.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const REVIEW = %s;\n"
    "const dialog = () => document.body.querySelector('.wf-approval-dialog');\n"
    "// The network: every request recorded; `reply(url, init)` answers it.\n"
    "const sent = [];\n"
    "let reply = () => ({ status: 200, body: { ok: true, outcome: 'resumed',\n"
    "  sentence: 'Allowed once by alice at 07:42: bash' } });\n"
    "globalThis.fetch = async (url, init) => {\n"
    "  sent.push([init && init.method || 'GET', String(url), init && init.body ? JSON.parse(init.body) : null]);\n"
    "  const r = reply(String(url), init);\n"
    "  return { ok: r.status < 400, status: r.status, json: async () => r.body };\n"
    "};\n"
    "const tasksOpened = [];\n"
    "globalThis.tasksModule = { openTasks: (id) => tasksOpened.push(id) };\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("task-question")
    sandbox = build_sandbox(root, _CANVAS_SHIM, stubs={"ui.js": _UI, "workbench/workbench.js": _WORKBENCH})
    shutil.copy(JS / "workflowApprovalNotice.js", root / "workflowApprovalNotice.js")
    return sandbox


def _case(box, script):
    return _run(box, _PREAMBLE % json.dumps(_REVIEW), script)


def test_a_task_question_is_offered_once_and_allow_once_answers_at_the_tasks_door(box):
    o = _case(box, """
        const first = notice.offerWorkflowApproval(REVIEW);
        const again = notice.offerWorkflowApproval(REVIEW);
        const toast = ui.toasts[0];
        await ui.actions[0]();
        const d = dialog();
        const read = { title: d.querySelector('.wf-approval-title').textContent,
          sub: d.querySelector('.wf-approval-sub').textContent.split(' Waiting since')[0],
          question: d.querySelector('.skill-test-meta').textContent, markup: markup(d),
          buttons: d.querySelectorAll('button').map((b) => [b.textContent, b.dataset.decision || null]),
          note: d.querySelector('.wf-approval-note').textContent };
        fire(d.querySelectorAll('button').find((b) => b.dataset.decision === 'approve_task'), 'click');
        await settle(10);
        out({ first, again, toast, read, sent, gone: !dialog(), last: ui.toasts[ui.toasts.length - 1],
              workbench: opened.length });
    """)
    assert o["first"] is True and o["again"] is False, "a question is offered once a page"
    assert o["toast"] == ["“Morning replies” is waiting for your yes: It wants to use bash.", "Answer"]
    r = o["read"]
    assert r["title"] == "“Morning replies” is waiting for your yes"
    assert r["sub"] == "It wants to use bash."
    assert r["question"] == "Allow this exact action once? <img src=x onerror=alert(1)>" and r["markup"] == []
    assert r["buttons"] == [["Deny", "deny"], ["Allow once", "approve_task"], ["Open the task", None],
                            ["Not now", None]]
    assert r["note"] == ("Allow once lets this one action run, and the next one asks again. "
                         "Deny ends this run without it.")
    assert o["sent"] == [["POST", "http://test.local/api/tasks/t1/runs/r1/answer",
                          {"approval_id": "ap1", "decision": "approve_task"}]]
    assert o["gone"] is True and o["workbench"] == 0
    assert o["last"] == ["Morning replies: Allowed once by alice at 07:42: bash", None]


def test_a_refused_answer_keeps_the_card_and_deny_sends_deny(box):
    o = _case(box, """
        notice.offerWorkflowApproval(REVIEW);
        await ui.actions[0]();
        reply = () => ({ status: 409, body: { detail: 'This run is not waiting on this question any more.' } });
        fire(dialog().querySelectorAll('button').find((b) => b.dataset.decision === 'approve_task'), 'click');
        await settle(10);
        const refused = dialog().querySelector('.wf-approval-said').textContent;
        reply = () => ({ status: 200, body: { ok: true, outcome: 'denied' } });
        fire(dialog().querySelectorAll('button').find((b) => b.dataset.decision === 'deny'), 'click');
        await settle(10);
        out({ refused, decisions: sent.map((s) => s[2].decision), gone: !dialog(),
              last: ui.toasts[ui.toasts.length - 1][0] });
    """)
    assert o["refused"] == "Not answered: This run is not waiting on this question any more."
    assert o["decisions"] == ["approve_task", "deny"] and o["gone"] is True
    assert o["last"] == "Morning replies: Denied. The run ends without it."


def test_open_the_task_opens_it_in_the_tasks_window_and_answers_nothing(box):
    o = _case(box, """
        notice.offerWorkflowApproval(REVIEW);
        await ui.actions[0]();
        dismissTopMenu();
        const esc = !dialog();
        await ui.actions[0]();
        fire(dialog().querySelectorAll('button').find((b) => b.textContent === 'Open the task'), 'click');
        await settle(10);
        out({ esc, tasksOpened, workbench: opened.length, sent: sent.length, gone: !dialog() });
    """)
    assert o["esc"] is True and o["sent"] == 0, "nothing is answered by closing it"
    assert o["tasksOpened"] == ["t1"] and o["workbench"] == 0 and o["gone"] is True


def test_task_questions_still_waiting_are_offered_again_when_pantheon_opens(box):
    o = _case(box, """
        reply = (url) => url.endsWith('/api/tasks/waiting') ? { status: 200, body: { waiting: [
          { task_id: 't1', task: 'Morning replies', run_id: 'r1', node_id: 'task', item: null,
            label: 'Morning replies', kind: 'approval', since: '2026-10-02T03:12:00Z',
            until: '2026-10-02T15:12:00Z', approval: REVIEW.approval },
          // A card the store no longer holds is not offered.
          { task_id: 't2', task: 'Evening digest', run_id: 'r2', node_id: 'task', item: null,
            label: 'Evening digest', kind: 'approval', since: '2026-10-02T03:00:00Z', approval: null },
        ] } } : { status: 404, body: {} };
        const shown = await notice.offerWaitingWorkflowApprovals();
        const again = await notice.offerWaitingWorkflowApprovals();
        out({ shown, again, toasts: ui.toasts.map((t) => t[0]),
              reads: sent.filter((s) => s[1].endsWith('/api/tasks/waiting')).length });
    """)
    assert o["shown"] == 1 and o["again"] == 0, "the question once, and only one that can be answered"
    assert o["toasts"] == ["“Morning replies” is waiting for your yes: It wants to use bash."]
    assert o["reads"] == 2


def test_tasks_js_offers_a_task_question_from_its_queue(box):
    src = (JS / "tasks.js").read_text(encoding="utf-8")
    loaders = "".join(
        f"function {name}(review) {js_function(src, 'function ' + name)}\n"
        for name in ("_offerWorkflowApproval", "_offerDocumentPlan"))
    poll = "async function _pollTaskNotifications() " + js_function(src, "async function _pollTaskNotifications")
    o = _case(box, """
        const API_BASE = '';
        let _open = false;
        const uiModule = null;
        const runStatusTone = () => 'ok';
        const runStatusLabel = () => '';
        %s
        %s
        // The queue's review, as the wire carries it: no task name.
        const { task, ...wire } = REVIEW;
        reply = () => ({ status: 200, body: { notifications: [
          { task_name: 'Morning replies', status: 'waiting', review: wire }] } });
        await _pollTaskNotifications();
        await settle(50);
        out({ toasts: ui.toasts });
    """ % (loaders.replace("'./workflowApprovalNotice.js'", "'../workflowApprovalNotice.js'")
           .replace("'./documentPlanNotice.js'", "'../nothing.js'"), poll))
    assert o["toasts"] == [["“Morning replies” is waiting for your yes: It wants to use bash.", "Answer"]], \
        "answered, not announced — named by the task the notification came from"
