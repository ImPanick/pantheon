// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/stepSettings.js
//
// `B1855`, `B1856`. A workflow step's `settings` — how often it tries again
// after failing, how long it waits between tries, how long one try may take —
// and its switch, in the document's shape and in words. A leaf (it imports
// nothing), so the step panel (`workflowPanels.js`), the source that draws
// the step's box (`workflowSource.js`) and a test read one rule.
//
// The bounds are the server's (`src/workflow_document.py`): `retries` 0–5,
// `retry_wait_seconds` 1–3600 (30 when absent), `timeout_seconds` 0 or
// 5–86400 (0 or absent: no limit). Absent settings are today's behaviour.

export const STEP_RETRIES_MAX = 5;
export const STEP_WAIT_DEFAULT = 30;
export const STEP_LIMITS = Object.freeze([
  [0, 'No time limit'], [30, '30 seconds'], [60, '1 minute'], [300, '5 minutes'], [900, '15 minutes'],
  [3600, '1 hour'], [21600, '6 hours'], [86400, '24 hours'],
]);

/** A time in seconds as a person says it: "45 seconds", "5 minutes", "2 hours". */
export function secondsWords(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  if (s % 3600 === 0 && s >= 3600) return s === 3600 ? '1 hour' : `${s / 3600} hours`;
  if (s % 60 === 0 && s >= 60) return s === 60 ? '1 minute' : `${s / 60} minutes`;
  return s === 1 ? '1 second' : `${s} seconds`;
}

/** A step's `settings` as the document keeps it: only what differs from the
 *  default, or null when nothing does (the step then reads as it always
 *  did, and its fingerprint does not move). */
export function settingsOf(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const out = {};
  const retries = Math.round(Number(r.retries) || 0);
  if (retries > 0) {
    out.retries = Math.min(STEP_RETRIES_MAX, retries);
    const wait = Math.round(Number(r.retry_wait_seconds));
    if (Number.isFinite(wait) && wait > 0 && wait !== STEP_WAIT_DEFAULT) out.retry_wait_seconds = wait;
  }
  const limit = Math.round(Number(r.timeout_seconds) || 0);
  if (limit > 0) out.timeout_seconds = limit;
  return Object.keys(out).length ? out : null;
}

/** What a step's settings say on its box, in words ("" for none). */
export function settingsWords(raw, disabled = false) {
  const st = settingsOf(raw);
  const bits = [];
  if (st && st.retries) bits.push(`${st.retries + 1} tries`);
  if (st && st.timeout_seconds) bits.push(`${secondsWords(st.timeout_seconds)} limit`);
  if (disabled) bits.unshift('Switched off');
  return bits.join(' · ');
}

export default { STEP_RETRIES_MAX, STEP_WAIT_DEFAULT, STEP_LIMITS, secondsWords, settingsOf, settingsWords };
