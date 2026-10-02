// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/approvalBox.js
//
// `P22-17` (wf-canvas; design § 2's P22-17). The card for one action that
// waits for a person's yes, outside a chat: the question, the exact action
// (its tool, its content, its effects, the approval's fingerprint), and two
// buttons. Lifted out of `skills.js:_skillApprovalBox` — the skill test's
// pause (`P8-09`, `P8-18`) — so a workflow step that waits for a yes is
// answered with the same card (`Law 14`: one card, not a second set of buttons
// that could drift from the first). Nothing about the gate moves: the card
// draws and asks; the caller posts the answer (`onDecide`) to its own route,
// and that route re-checks owner, session and the sealed action before it
// consumes anything (`FORBIDDEN.md` Part 2: the store's seal, TTL, single use
// and owner binding).
//
// **Which yes is the caller's.** The skill test posts `approve` (its run is a
// chat-scoped one, and `skills.js` still posts exactly that — `Law 1`); a
// workflow step posts `approve_task` (`allowValue`), the row's scope word:
// Allow once, the gate re-arms behind it.
//
// **Every value is text.** The question and the action came from a model and
// from outside data; they reach the page through `textContent` only. The class
// names are the skill test's, so the card looks the same in both places.

/**
 * `approval` — `{ approval_id, question, action: { tool, content, effects,
 *   workspace, digest } }` (the `ask_user` public payload).
 * `allowValue` — the decision the Allow button sends (`approve` for the skill
 *   test, `approve_task` for a workflow step).
 * `allowLabel` / `denyLabel` — the buttons' words.
 * `onDecide(decision)` — posts it; a throw re-enables the buttons and is
 *   handed to `onError(message)`.
 */
export function approvalBox(approval, {
  allowValue = 'approve', allowLabel = 'Allow once', denyLabel = 'Deny', onDecide = null, onError = null,
} = {}) {
  const a = approval && typeof approval === 'object' ? approval : {};
  const box = document.createElement('div');
  box.className = 'skill-test-approval approval-box';
  const question = document.createElement('div');
  question.className = 'skill-test-meta';
  question.textContent = a.question || 'Allow this exact action once?';
  box.appendChild(question);
  if (a.action) {
    const action = document.createElement('pre');
    action.className = 'skill-test-out';
    action.textContent = [
      a.action.tool || 'tool',
      a.action.content || '',
      Array.isArray(a.action.effects)
        ? `Effects: ${a.action.effects.join(', ')}`
        : '',
      a.action.workspace ? `Workspace: ${a.action.workspace}` : '',
      a.action.digest ? `Approval fingerprint: ${a.action.digest}` : '',
    ].filter(Boolean).join('\n');
    box.appendChild(action);
  }
  const actions = document.createElement('div');
  actions.className = 'modal-footer';
  const decide = async (decision) => {
    actions.querySelectorAll('button').forEach((btn) => { btn.disabled = true; });
    try {
      if (typeof onDecide === 'function') await onDecide(decision);
    } catch (error) {
      if (typeof onError === 'function') onError(String((error && (error.sentence || error.message)) || error));
      actions.querySelectorAll('button').forEach((btn) => { btn.disabled = false; });
    }
  };
  for (const [decision, label, cls] of [
    ['deny', denyLabel, 'confirm-btn confirm-btn-secondary'],
    [allowValue, allowLabel, 'confirm-btn confirm-btn-primary'],
  ]) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = cls;
    button.dataset.decision = decision;
    button.textContent = label;
    button.addEventListener('click', () => decide(decision));
    actions.appendChild(button);
  }
  box.appendChild(actions);
  return box;
}

export default { approvalBox };
