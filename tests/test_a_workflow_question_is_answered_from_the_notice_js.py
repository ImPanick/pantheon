# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-17` (wf-canvas) — a workflow step that waits for a yes is answered from a notice, with Allow once (`approve_task`) or Deny.

The row: "a scheduled run that reaches an approval … parks as `waiting` instead,
reusing the skill test's pause … and the `approve_task` scope, and the card
reaches notifications and the executions view. Allow resumes once". Design
§ 1.5: the card goes on the scheduler's notification queue as `review`
(`{ kind: "workflow_approval", workflow_id, run_id, node_id, item, approval }`),
it is "re-offered on page load like `_offerWaitingDocumentPlans`" from
`GET /api/workflows/waiting`, and it is answered by
`POST /api/workflows/{id}/runs/{run_id}/answer {node_id, item, approval_id,
decision}` with `approve_task` or `deny` (`approve`, the chat scope, is the
server's 400). The card is the skill test's (`approvalBox.js`, lifted out of
`skills.js:_skillApprovalBox`); `skills.js` still posts `approve` (`Law 1`).

Driven: the real `workflowApprovalNotice.js`, `approvalBox.js` and
`escMenuStack.js`, the real `workflowApi.js` with C-W's four functions beside
it over the C-W fake server; `tasks.js`'s two new loaders and its
notification poll cut out of the shipped file (`js_function`); and the skill
test's real `_skillApprovalBox` with the shared card, its fetch recorded.
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
from helpers.workflow_cw_fake import build_sandbox, palette_json  # noqa: E402
from tests.helpers.esc_stub import ui_default_stub  # noqa: E402
from tests.helpers.js_source import js_function, js_definition  # noqa: E402

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
    "kind": "workflow_approval", "workflow_id": "wf1", "run_id": "r1", "node_id": "reply", "item": None,
    "workflow": "Overnight replies", "label": "Send reply", "since": "2026-10-02T03:12:00Z",
    "approval": {"approval_id": "ap1", "question": "Allow this exact action once? <img src=x onerror=alert(1)>",
                 "action": {"tool": "send_reply", "content": "{\"to\": \"ann@example.com\"}",
                            "effects": ["sends_external"], "digest": "ab12cd34"}},
}

_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "import { server as cw, net as cwnet, seed, cwApi } from './cwfake.js';\n"
    "import { calls as ui } from '../ui.js';\n"
    "import { opened } from './workbench.js';\n"
    "import { dismissTopMenu } from '../escMenuStack.js';\n"
    "const notice = await import('../workflowApprovalNotice.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "cw.palette = %s;\n"
    "seed({ id: 'wf1', name: 'Overnight replies', task_id: 't1', trigger_status: 'active', version: 4,\n"
    "  trigger_task: { id: 't1', status: 'active' }, graph: { v: 1, start: { position: null }, nodes: [], edges: [] } });\n"
    "notice.setWorkflowApi(cwApi(cwnet));\n"
    "const REVIEW = %s;\n"
    "const dialog = () => document.body.querySelector('.wf-approval-dialog');\n"
    "const answers = () => cw.calls.filter((c) => c.url.endsWith('/answer')).map((c) => [c.method, c.url, c.body]);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("question")
    sandbox = build_sandbox(root, _CANVAS_SHIM, stubs={"ui.js": _UI, "workbench/workbench.js": _WORKBENCH})
    shutil.copy(JS / "workflowApprovalNotice.js", root / "workflowApprovalNotice.js")
    return sandbox


def _case(box, script):
    return _run(box, _PREAMBLE % (palette_json(), json.dumps(_REVIEW)), script)


def test_a_question_is_offered_once_and_allow_once_sends_approve_task(box):
    o = _case(box, """
        const first = notice.offerWorkflowApproval(REVIEW);
        const again = notice.offerWorkflowApproval(REVIEW);
        const toast = ui.toasts[0];
        await ui.actions[0]();
        const d = dialog();
        const read = { title: d.querySelector('.wf-approval-title').textContent,
          sub: d.querySelector('.wf-approval-sub').textContent.split(' Waiting since')[0],
          question: d.querySelector('.skill-test-meta').textContent, action: d.querySelector('.skill-test-out').textContent,
          buttons: d.querySelectorAll('button').map((b) => [b.textContent, b.dataset.decision || null]),
          note: d.querySelector('.wf-approval-note').textContent, markup: markup(d) };
        fire(d.querySelectorAll('button').find((b) => b.dataset.decision === 'approve_task'), 'click');
        await settle(10);
        out({ first, again, toast, read, answers: answers(), gone: !dialog(), last: ui.toasts[ui.toasts.length - 1] });
    """)
    assert o["first"] is True and o["again"] is False, "a question is offered once a page"
    assert o["toast"] == ["“Overnight replies” is waiting for your yes: “Send reply” wants to use send_reply.", "Answer"]
    r = o["read"]
    assert r["title"] == "“Overnight replies” is waiting for your yes"
    assert r["sub"] == "“Send reply” wants to use send_reply."
    assert r["question"] == "Allow this exact action once? <img src=x onerror=alert(1)>" and r["markup"] == []
    assert r["action"] == ('send_reply\n{"to": "ann@example.com"}\nEffects: sends_external\n'
                           'Approval fingerprint: ab12cd34')
    assert r["buttons"] == [["Deny", "deny"], ["Allow once", "approve_task"], ["Open the run", None], ["Not now", None]]
    assert r["note"].startswith("Allow once lets this one action run, and the next one asks again.")
    assert o["answers"] == [["POST", "/api/workflows/wf1/runs/r1/answer",
                             {"node_id": "reply", "item": None, "approval_id": "ap1", "decision": "approve_task"}]]
    assert o["gone"] is True
    assert o["last"] == ["Overnight replies: Allowed once by joseph at 07:42: send_reply. The run goes on.", None]


def test_a_refused_answer_keeps_the_card_and_deny_sends_deny(box):
    o = _case(box, """
        notice.offerWorkflowApproval(REVIEW);
        await ui.actions[0]();
        cw.answerReply = () => ({ status: 409, body: { detail: 'That question was answered somewhere else.' } });
        fire(dialog().querySelectorAll('button').find((b) => b.dataset.decision === 'approve_task'), 'click');
        await settle(10);
        const refused = { said: dialog().querySelector('.wf-approval-said').textContent,
          enabled: dialog().querySelectorAll('.confirm-btn').map((b) => !b.disabled) };
        cw.answerReply = null;
        fire(dialog().querySelectorAll('button').find((b) => b.dataset.decision === 'deny'), 'click');
        await settle(10);
        out({ refused, answers: answers().map((a) => a[2].decision), gone: !dialog() });
    """)
    assert o["refused"] == {"said": "Not answered: That question was answered somewhere else.", "enabled": [True, True]}
    assert o["answers"] == ["approve_task", "deny"] and o["gone"] is True


def test_escape_and_not_now_leave_it_waiting_and_open_the_run_opens_the_workbench_on_it(box):
    o = _case(box, """
        notice.offerWorkflowApproval(REVIEW);
        await ui.actions[0]();
        dismissTopMenu();
        const esc = !dialog();
        await ui.actions[0]();
        fire(dialog().querySelectorAll('button').find((b) => b.textContent === 'Not now'), 'click');
        const later = !dialog();
        await ui.actions[0]();
        fire(dialog().querySelectorAll('button').find((b) => b.textContent === 'Open the run'), 'click');
        await settle(10);
        out({ esc, later, opened, answers: answers().length, gone: !dialog() });
    """)
    assert o["esc"] is True and o["later"] is True and o["answers"] == 0, "nothing is answered by closing it"
    assert o["opened"] == [{"workflowId": "wf1", "runId": "r1"}] and o["gone"] is True


def test_questions_still_waiting_are_offered_again_when_pantheon_opens(box):
    o = _case(box, """
        cw.waiting = [
          { workflow_id: 'wf1', workflow: 'Overnight replies', run_id: 'r1', node_id: 'reply', item: null, label: 'Send reply',
            kind: 'approval', since: '2026-10-02T03:12:00Z', until: '2026-10-02T15:12:00Z', approval: REVIEW.approval },
          { workflow_id: 'wf1', workflow: 'Overnight replies', run_id: 'r2', node_id: 'hold', item: null, label: 'Wait',
            kind: 'time', since: '2026-10-02T03:00:00Z', until: '2026-10-02T08:00:00Z', approval: null },
          // A step waiting for Pantheon to be idle is not a question, whatever else it carries.
          { workflow_id: 'wf1', workflow: 'Overnight replies', run_id: 'r4', node_id: 'post', item: null, label: 'Post',
            kind: 'idle', since: '2026-10-02T03:00:00Z', approval: { ...REVIEW.approval, approval_id: 'ap4' } },
          { workflow_id: 'wf1', workflow: 'Overnight replies', run_id: 'r3', node_id: 'each', item: 2, label: 'Summarise',
            kind: 'approval', since: '2026-10-02T03:00:00Z', approval: { ...REVIEW.approval, approval_id: 'ap3' } },
        ];
        const shown = await notice.offerWaitingWorkflowApprovals();
        const again = await notice.offerWaitingWorkflowApprovals();
        out({ shown, again, toasts: ui.toasts.map((t) => t[0]),
              reads: cw.calls.filter((c) => c.url === '/api/workflows/waiting').length });
    """)
    assert o["shown"] == 2 and o["again"] == 0, "the questions only, each once"
    assert o["toasts"] == ["“Overnight replies” is waiting for your yes: “Send reply” wants to use send_reply.",
                           "“Overnight replies” is waiting for your yes: “Summarise” (item 3) wants to use send_reply."]
    assert o["reads"] == 2


def test_tasks_js_offers_a_question_from_its_queue_and_when_it_loads(box):
    src = (JS / "tasks.js").read_text(encoding="utf-8")
    loaders = "".join(
        f"function {name}(review) {js_function(src, 'function ' + name)}\n"
        for name in ("_offerWorkflowApproval", "_offerWaitingWorkflowApprovals", "_offerDocumentPlan"))
    poll = "async function _pollTaskNotifications() " + js_function(src, "async function _pollTaskNotifications")
    start = "function startNotificationPolling() " + js_function(src, "function startNotificationPolling")
    o = _case(box, """
        // `tasks.js`'s loaders import './workflowApprovalNotice.js' beside it: the case runs one folder down.
        const loaded = [];
        const API_BASE = '';
        let _open = false;
        const uiModule = null;
        const runStatusTone = () => 'ok';
        const runStatusLabel = () => '';
        let _notifInterval = null;
        const _offerWaitingDocumentPlans = () => {};
        const _pollTaskNotifications_ = null;
        %s
        %s
        %s
        // The queue's review, as the wire carries it: no workflow name, no step label.
        const { workflow, label, since, ...wire } = REVIEW;
        globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => ({ notifications: [
          { task_name: 'Overnight replies', status: 'waiting', review: wire }] }) });
        cw.waiting = [{ workflow_id: 'wf1', workflow: 'Overnight replies', run_id: 'r9', node_id: 'reply', item: null,
          label: 'Send reply', kind: 'approval', approval: { ...REVIEW.approval, approval_id: 'ap9' } }];
        await _pollTaskNotifications();
        _offerWaitingWorkflowApprovals();
        await settle(50);
        out({ toasts: ui.toasts });
    """.replace("./workflowApprovalNotice.js", "../workflowApprovalNotice.js") % (loaders.replace(
        "'./workflowApprovalNotice.js'", "'../workflowApprovalNotice.js'").replace(
        "'./documentPlanNotice.js'", "'../nothing.js'"), poll, start))
    assert o["toasts"] == [
        ["“Overnight replies” is waiting for your yes: A step wants to use send_reply.", "Answer"],
        ["“Overnight replies” is waiting for your yes: “Send reply” wants to use send_reply.", "Answer"],
    ], "one from the queue (named by the task the notification came from), one still waiting on load"


def test_the_skill_test_still_posts_approve_through_the_same_card(box):
    skills = (JS / "skills.js").read_text(encoding="utf-8")
    abox = (JS / "approvalBox.js").read_text(encoding="utf-8")
    shared = js_definition(abox, abox.index("function approvalBox("))
    skill_box = ("function _skillApprovalBox(approval, name, { onAnswered, onError } = {}) "
                 + js_function(skills, "function _skillApprovalBox"))
    o = _case(box, """
        const API = '';
        const sent = [];
        globalThis.fetch = async (url, init) => { sent.push([url, JSON.parse(init.body)]); return { ok: true, status: 200 }; };
        %s
        %s
        const answered = [];
        const card = _skillApprovalBox(REVIEW.approval, 'packer', { onAnswered: (d) => answered.push(d) });
        const buttons = card.querySelectorAll('button').map((b) => [b.textContent, b.dataset.decision]);
        fire(card.querySelectorAll('button').find((b) => b.textContent === 'Allow once'), 'click');
        await settle(5);
        fire(card.querySelectorAll('button').find((b) => b.textContent === 'Deny'), 'click');
        await settle(5);
        out({ buttons, sent, answered, cls: card.className });
    """ % (shared, skill_box))
    assert o["buttons"] == [["Deny", "deny"], ["Allow once", "approve"]]
    assert o["sent"] == [["/api/skills/packer/test-approval", {"approval_id": "ap1", "decision": "approve"}],
                         ["/api/skills/packer/test-approval", {"approval_id": "ap1", "decision": "deny"}]], \
        "the skill test answers its own route with the chat-scoped yes it always sent (Law 1)"
    assert o["answered"] == ["approve", "deny"]
    assert o["cls"] == "skill-test-approval approval-box", "one card, the skill test's look"
