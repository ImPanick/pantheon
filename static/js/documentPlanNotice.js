// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/documentPlanNotice.js

/**
 * The scheduled Documents Tidy's proposal, put in front of the person. `B1006`.
 *
 * The owner, 2026-10-01 (`D-2026-10-01-03`): *propose, don't delete.* The
 * seeded tidy used to hard-delete what its rules called clutter after every
 * fifth new document, unasked. It now holds the list as a plan
 * (`src/document_actions.py`) and says so on the scheduler's notification
 * queue, with the list attached as `review`. This module is what the person
 * sees: a notice with **Review**, and the list in the confirm dialog every
 * destructive step already uses (`uiModule.styledConfirm`, `P9-10`'s
 * `details`), with three answers —
 *
 *   **Delete**          → "Apply the plan"
 *   **Keep**            → "Don't change anything"
 *   **Not now** / Esc   → nothing: it keeps waiting, and is offered again
 *                         when Pantheon is next opened
 *
 * The answer goes to `POST /api/document-folders/plans/{id}/answer`, which
 * only a person can call (`B1005`): the assistant has no way to press these.
 *
 * Every string from the server reaches the page as text — `showToast` and
 * `styledConfirm` both write `textContent` — because a document's title is the
 * person's to type and anything's to import.
 */

import uiModule from './ui.js';

const API_BASE = window.location.origin;
const NOTICE_MS = 20000;

// Plan ids offered on this page, so the queue's push and the reload's catch-up
// never put the same proposal on screen twice.
const _offered = new Set();

function _count(review) {
  const n = Number(review && review.count) || 0;
  return `${n} document${n === 1 ? '' : 's'}`;
}

/**
 * What the person chose, as the label the server reads — or `null` for
 * "not now". `styledConfirm` answers `true` (confirm), `'alternate'` (the
 * third button) or `false` (cancel, Esc, the backdrop).
 */
export function answerFor(review, choice) {
  if (choice === true) return review.approve;
  if (choice === 'alternate') return review.decline;
  return null;
}

export async function reviewDocumentPlan(review) {
  const items = Array.isArray(review.items) ? review.items : [];
  const more = Number(review.more) || 0;
  const choice = await uiModule.styledConfirm(review.question || 'Delete these documents?', {
    title: review.title || 'Documents Tidy',
    // One word each: three buttons share a 360px dialog, and a two-word
    // label wrapped out of its button there (measured, `B1006`). The
    // question above them carries the count.
    confirmText: 'Delete',
    danger: true,
    alternateText: 'Keep',
    cancelText: 'Not now',
    details: {
      heading: 'What it would delete, and why',
      items,
      footnote: more
        ? `And ${more} more after these — the next tidy offers them. Nothing is deleted until you choose Delete.`
        : 'Nothing is deleted until you choose Delete.',
    },
  });
  const answer = answerFor(review, choice);
  if (!answer) return null;
  let res;
  let data = {};
  try {
    res = await fetch(`${API_BASE}/api/document-folders/plans/${encodeURIComponent(review.plan_id)}/answer`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    });
    data = await res.json().catch(() => ({}));
  } catch (_) {
    uiModule.showError('Documents Tidy: Pantheon could not be reached, so nothing was changed.');
    return null;
  }
  if (!res.ok) {
    uiModule.showError(`Documents Tidy: ${data.detail || 'that answer was not taken'}`);
    return null;
  }
  uiModule.showToast(`Documents Tidy: ${data.message || 'done'}`, { duration: 6000 });
  return data;
}

/** Put one proposal on screen: a notice with Review, and the system
 *  notification too when the person has allowed them. Once per page. */
export function offerDocumentPlan(review) {
  if (!review || review.kind !== 'document_plan' || !review.plan_id) return false;
  if (_offered.has(review.plan_id)) return false;
  _offered.add(review.plan_id);
  const title = review.title || 'Documents Tidy';
  const summary = review.summary || `${_count(review)} to review.`;
  const open = () => { reviewDocumentPlan(review); };
  try {
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      const note = new Notification(title, { body: summary, tag: `document-plan-${review.plan_id}` });
      note.onclick = () => {
        try { window.focus(); } catch (_) {}
        try { note.close(); } catch (_) {}
        open();
      };
    }
  } catch (_) {}
  uiModule.showToast(`${title}: ${summary}`, { duration: NOTICE_MS, action: 'Review', onAction: open });
  return true;
}

/** The proposals still waiting, offered again after a reload — the queue
 *  says a thing once, and a person may not have been looking. */
export async function offerWaitingDocumentPlans() {
  try {
    const res = await fetch(`${API_BASE}/api/document-folders/plans`, { credentials: 'same-origin' });
    if (!res.ok) return 0;
    const data = await res.json();
    let shown = 0;
    for (const review of (data && data.plans) || []) {
      if (offerDocumentPlan(review)) shown += 1;
    }
    return shown;
  } catch (_) {
    return 0;
  }
}
