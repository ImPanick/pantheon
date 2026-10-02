// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/refusal.js
//
// `P22-05`. What the server said when it refused, as one sentence — for every
// door in the Workbench. `refusalText` was `canvas.js`'s (`P22-02`); it lives
// here so the workflow data layer (`workflowApi.js`) reads a refusal the way
// the canvas does, and the canvas imports it back from here (design § 6.3), so
// there is one reading of a refusal in the room (`Law 7`).

/** FastAPI answers `{ detail: "…" }` for an `HTTPException` and
 *  `{ detail: [{ msg }] }` for a body it could not parse; an object detail is
 *  read for its words. */
export function refusalText(detail) {
  if (typeof detail === 'string') return detail.trim();
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && (d.msg || d.message)) || '').filter(Boolean).join(' ').trim();
  }
  if (detail && typeof detail === 'object') {
    return String(detail.message || detail.sentence || detail.reason || detail.detail || '').trim();
  }
  return '';
}

/**
 * A refused response, read once: its sentence, and — for a workflow document
 * the engine refused — the engine's `reason` and the steps it names
 * (`node_ids`), which the workflow routes add beside `detail`.
 * `fallback` is said when the body has no words (a proxy's 502, say).
 */
export async function readRefusal(res, fallback) {
  let body = null;
  try { body = await res.json(); } catch (_) { body = null; }
  const sentence = refusalText(body && body.detail)
    || fallback || `The server refused (${res && res.status}).`;
  return {
    status: res ? res.status : 0,
    sentence,
    reason: body && typeof body.reason === 'string' ? body.reason : null,
    nodeIds: body && Array.isArray(body.node_ids) ? body.node_ids.map(String) : [],
    // `P22-09` (`C-W`). The setting a document refusal is about, or ''.
    field: body && typeof body.field === 'string' ? body.field : '',
  };
}

export default { refusalText, readRefusal };
