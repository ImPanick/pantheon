// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workflowApprovalNotice.js

/**
 * `P22-17` (wf-canvas). A workflow step that waits for a person's yes, put in
 * front of that person — the way `documentPlanNotice.js` puts the Documents
 * Tidy's proposal there (`B1006`), on the same queue and with the same shape.
 *
 * A step a model drives that reaches an action needing a yes parks the run as
 * `waiting` and mints its card (design § 1.5); the scheduler puts a
 * notification on its queue with the card attached as `review`:
 * `{ kind: "workflow_approval", workflow_id, run_id, node_id, item, approval }`
 * (and, from the waiting list, the workflow's name and the step's label). This
 * module is what the person sees: a notice with **Answer**, and the gate card
 * (`approvalBox.js`, the one the skill test answers with) in a small window
 * with **Open the run** beside it. The answer goes to C-W's
 * answer route (`answerStep`) through `workflowApi.js`
 * (one door, `Law 14`) with `approve_task` — Allow once, the only yes a
 * workflow has: there is no chat to remember it in — or `deny`. The server
 * re-checks the owner, the run, the step and the sealed action before it
 * consumes anything; nothing here decides.
 *
 *   **Allow once** → `approve_task`: this one action runs, the run goes on,
 *                    and the next action that needs a yes asks again.
 *   **Deny**       → `deny`: the step takes its "if it fails" way.
 *   **Not now** / Esc → nothing: the card keeps waiting (until its deadline,
 *                    `workflow_approval_timeout_seconds`, 12 h by default —
 *                    `D-2026-10-02-01` §1) and is offered again when
 *                    Pantheon is next opened (`offerWaitingWorkflowApprovals`).
 *
 * `B1102`. A plain scheduled Prompt task's run parks on its card the same way,
 * and this module puts that question in front of the person too — one notice
 * for "a run is waiting for your yes" (`Law 14`). Its `review` is
 * `{ kind: "task_approval", task_id, task, run_id, node_id, item, label, since,
 * approval }`; it is answered at `POST /api/tasks/{id}/runs/{run_id}/answer`
 * (the same server core as a workflow's), re-offered from
 * `GET /api/tasks/waiting`, and **Deny** ends that run without the action.
 *
 * Every string from the server reaches the page as text: the question and the
 * action came from a model reading outside data.
 */

import uiModule from './ui.js';
import { approvalBox } from './approvalBox.js';
import { registerMenuDismiss } from './escMenuStack.js';
// `P3-18`'s rule: a window portaled to the body takes its z from the live
// counter when shown, never a literal a long session climbs past.
import { topPortalZ } from './toolWindowZOrder.js';

const NOTICE_MS = 30000;
const API_BASE = window.location.origin;

// Approval ids offered on this page, so the queue's push and the reload's
// catch-up never put the same question on screen twice; and the ones answered.
const _offered = new Set();
const _answered = new Set();

/** The workflow data layer, loaded on first use (the Workbench's own door:
 *  `workbench/workflowApi.js`, spelled as the room spells it so the page holds
 *  one instance). A test hands its own in with `setWorkflowApi`. */
let _apiOverride = null;
export function setWorkflowApi(api) { _apiOverride = api || null; }
async function _api() {
  if (_apiOverride) return _apiOverride;
  const m = await import('./workbench/workflowApi.js');
  return m.createWorkflowApi();
}

function _when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

/** `B1102`. A plain task's question rather than a workflow step's. */
const isTask = (review) => !!(review && review.kind === 'task_approval');

/** What the notice says: `{ title, summary }`. */
export function workflowApprovalWords(review) {
  const r = review || {};
  if (isTask(r)) {
    const name = String(r.task || r.task_name || '').trim();
    const used = r.approval && r.approval.action && r.approval.action.tool ? String(r.approval.action.tool) : '';
    return {
      title: name ? `“${name}” is waiting for your yes` : 'A task is waiting for your yes',
      summary: `It wants to ${used ? `use ${used}` : 'do something that needs your yes'}.`,
    };
  }
  const wf = String(r.workflow || r.workflow_name || '').trim();
  const step = String(r.label || r.node_label || '').trim();
  const item = r.item == null ? '' : ` (item ${Number(r.item) + 1})`;
  // `B1111`. The tool as the step's panel names it ("Chat: send_message"),
  // which the server sends beside the card (`tool_label`); the card's sealed
  // name (`mcp__0e311a43__send_message`) only when there are no such words.
  const sealed = r.approval && r.approval.action && r.approval.action.tool ? String(r.approval.action.tool) : '';
  const tool = String(r.tool_label || '').trim() || sealed;
  return {
    title: wf ? `“${wf}” is waiting for your yes` : 'A workflow is waiting for your yes',
    summary: `${step ? `“${step}”${item}` : 'A step'} wants to ${tool ? `use ${tool}` : 'do something that needs your yes'}.`,
  };
}

/** Whether `review` is a question this module can put on screen: a workflow
 *  step's, or a plain task's (`B1102`). */
const isQuestion = (review) => !!(review
  && ((review.kind === 'workflow_approval' && review.workflow_id != null)
    || (review.kind === 'task_approval' && review.task_id != null))
  && review.run_id != null && review.approval && review.approval.approval_id);

/** `B1102`. A plain task's answer, at its own door — the same server core. */
async function _answerTask(review, decision) {
  let res;
  try {
    res = await fetch(`${API_BASE}/api/tasks/${encodeURIComponent(review.task_id)}/runs/${encodeURIComponent(review.run_id)}/answer`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approval_id: review.approval.approval_id, decision }),
    });
  } catch (_) {
    throw new Error('Pantheon could not be reached, so nothing was answered.');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'The answer was not taken.');
  return data;
}

/**
 * Send the answer. `decision` is `approve_task` or `deny`. Answers the
 * route's reply `{ ok, outcome, sentence }`, or throws with the server's
 * sentence.
 */
export async function answerWorkflowApproval(review, decision) {
  if (decision !== 'approve_task' && decision !== 'deny') throw new Error('A step is answered with Allow once or Deny.');
  if (isTask(review)) return _answerTask(review, decision);
  const api = await _api();
  if (!api || typeof api.answerStep !== 'function') throw new Error('This Pantheon cannot answer a waiting step.');
  return api.answerStep(review.workflow_id, review.run_id, {
    nodeId: review.node_id, item: review.item == null ? null : review.item,
    approvalId: review.approval.approval_id, decision,
  });
}

/** The Workbench on this question's run (Runs, the run, opened on the step);
 *  for a plain task's question, the task in the Tasks window (`B1102`). */
function openRun(review) {
  if (isTask(review)) {
    if (window.tasksModule && typeof window.tasksModule.openTasks === 'function') {
      window.tasksModule.openTasks(review.task_id);
    }
    return Promise.resolve();
  }
  return import('./workbench/workbench.js')
    .then((wb) => wb.openWorkbench({
      workflowId: review.workflow_id, runId: review.run_id,
      describeTrigger: window.tasksModule && window.tasksModule.scheduleLabel,
    }))
    .catch(() => uiModule.showError('The Workbench did not load. Reload the page and try again.'));
}

let _open = null;   // { box, release }

function _close() {
  const o = _open;
  if (!o) return;
  _open = null;
  try { o.release(); } catch (_) { /* already released */ }
  o.box.remove();
}

/** The question, with its card, in a small window. Answers the window. */
export function openWorkflowApproval(review) {
  if (!isQuestion(review)) return null;
  _close();
  const words = workflowApprovalWords(review);
  const box = document.createElement('div');
  box.className = 'wf-approval-dialog';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-label', words.title);
  const head = document.createElement('h3');
  head.className = 'wf-approval-title';
  head.textContent = words.title;
  box.appendChild(head);
  const sub = document.createElement('p');
  sub.className = 'wf-approval-sub';
  sub.textContent = words.summary + (review.since ? ` Waiting since ${_when(review.since)}.` : '');
  box.appendChild(sub);
  const said = document.createElement('p');
  said.className = 'wf-approval-said';
  said.setAttribute('role', 'status');
  said.setAttribute('aria-live', 'polite');
  box.appendChild(approvalBox(review.approval, {
    allowValue: 'approve_task',
    allowLabel: 'Allow once',
    onDecide: async (decision) => {
      said.textContent = decision === 'deny' ? 'Denying…' : 'Allowing it once…';
      const reply = await answerWorkflowApproval(review, decision);
      if (reply && reply.ok === false) throw new Error(reply.sentence || 'The answer was not taken.');
      _answered.add(String(review.approval.approval_id));
      const denied = isTask(review) ? 'Denied. The run ends without it.' : 'Denied. The step takes its “if it fails” way.';
      const sentence = (reply && reply.sentence) || (decision === 'deny' ? denied : 'Allowed once. The run goes on.');
      _close();
      const name = String(review.workflow || review.workflow_name || review.task || '').trim()
        || (isTask(review) ? 'The task' : 'The workflow');
      uiModule.showToast(`${name}: ${sentence}`, { duration: 8000 });
    },
    onError: (message) => { said.textContent = `Not answered: ${String(message).replace(/\.$/, '')}.`; },
  }));
  const note = document.createElement('p');
  note.className = 'wf-approval-note';
  note.textContent = 'Allow once lets this one action run, and the next one asks again. '
    + (isTask(review) ? 'Deny ends this run without it.' : 'Deny takes the step’s “if it fails” way.');
  box.appendChild(note);
  box.appendChild(said);
  const row = document.createElement('div');
  row.className = 'wf-approval-buttons';
  const runBtn = document.createElement('button');
  runBtn.type = 'button';
  runBtn.className = 'wf-approval-open';
  runBtn.textContent = isTask(review) ? 'Open the task' : 'Open the run';
  runBtn.addEventListener('click', () => { _close(); openRun(review); });
  const later = document.createElement('button');
  later.type = 'button';
  later.className = 'wf-approval-later';
  later.textContent = 'Not now';
  later.addEventListener('click', () => _close());
  row.appendChild(runBtn);
  row.appendChild(later);
  box.appendChild(row);
  box.style.zIndex = String(topPortalZ());
  document.body.appendChild(box);
  _open = { box, release: registerMenuDismiss(() => { _open = null; box.remove(); }) };
  const first = box.querySelector('.confirm-btn-primary');
  if (first && typeof first.focus === 'function') first.focus();
  return box;
}

/** Put one question on screen: a notice with Answer, and the system
 *  notification too when the person has allowed them. Once per page. */
export function offerWorkflowApproval(review) {
  if (!isQuestion(review)) return false;
  const id = String(review.approval.approval_id);
  if (_offered.has(id) || _answered.has(id)) return false;
  _offered.add(id);
  const words = workflowApprovalWords(review);
  const open = () => { openWorkflowApproval(review); };
  try {
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      const note = new Notification(words.title, { body: words.summary, tag: `workflow-approval-${id}` });
      note.onclick = () => {
        try { window.focus(); } catch (_) { /* a closed window */ }
        try { note.close(); } catch (_) { /* gone */ }
        open();
      };
    }
  } catch (_) { /* no system notifications here */ }
  uiModule.showToast(`${words.title}: ${words.summary}`, { duration: NOTICE_MS, action: 'Answer', onAction: open });
  return true;
}

/** The questions still waiting, offered again after a reload — the queue
 *  says a thing once, and a person may not have been looking (C-W's
 *  waiting list, `listWaiting`). Answers how many were put on screen. */
export async function offerWaitingWorkflowApprovals() {
  let listed;
  let shown = 0;
  try {
    const api = await _api();
    listed = (api && typeof api.listWaiting === 'function') ? await api.listWaiting() : null;
  } catch (_) {
    listed = null;
  }
  for (const w of (listed && Array.isArray(listed.waiting) ? listed.waiting : [])) {
    if (!w || w.kind !== 'approval' || !w.approval) continue;
    const review = {
      kind: 'workflow_approval', workflow_id: w.workflow_id, run_id: w.run_id, node_id: w.node_id,
      item: w.item == null ? null : w.item, approval: w.approval, workflow: w.workflow, label: w.label,
      since: w.since, until: w.until, tool_label: w.tool_label || null,
    };
    if (offerWorkflowApproval(review)) shown += 1;
  }
  return shown + await _offerWaitingTaskQuestions();
}

/** `B1102`. A plain task's questions still waiting, offered again the same way
 *  (`GET /api/tasks/waiting`). Answers how many were put on screen. */
async function _offerWaitingTaskQuestions() {
  let listed;
  try {
    const res = await fetch(`${API_BASE}/api/tasks/waiting`, { credentials: 'same-origin' });
    if (!res.ok) return 0;
    listed = await res.json();
  } catch (_) {
    return 0;
  }
  let shown = 0;
  for (const w of (listed && Array.isArray(listed.waiting) ? listed.waiting : [])) {
    if (!w || w.kind !== 'approval' || !w.approval) continue;
    const review = {
      kind: 'task_approval', task_id: w.task_id, task: w.task, run_id: w.run_id, node_id: w.node_id,
      item: null, approval: w.approval, label: w.label, since: w.since, until: w.until, tool_label: w.tool_label || null,
    };
    if (offerWorkflowApproval(review)) shown += 1;
  }
  return shown;
}

export default {
  offerWorkflowApproval, offerWaitingWorkflowApprovals, openWorkflowApproval, answerWorkflowApproval,
  workflowApprovalWords, setWorkflowApi,
};
