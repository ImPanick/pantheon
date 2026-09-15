// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/runStatus.js

/**
 * `B13`. The words the six shipped run statuses are shown as — once, for every
 * surface that shows them.
 *
 * ── What was measured ───────────────────────────────────────────────────────
 * One queued composer message can be on screen in three places at the same
 * time, and before this file it was called something different in each:
 *
 *   `queuePanel.js` docked row      Waiting  Sending  Sent  Failed  Skipped  Stopped
 *   `tasks.js` Activity row         Queued   Running  —     —       —        —
 *   `chat.js` transcript bubble     Queued   (n/a)    —     —       —        —
 *
 * Open the docked panel with the sidebar Activity view showing and the same
 * message reads *Waiting* in one and *Queued* in the other. Neither word is
 * wrong; having both is. (The Activity view has no word at all for the four
 * terminal values — it replaces the label with a relative time — which is why
 * the `job` column below is two entries and not six. A column filled past its
 * consumers is the drift `Law 13` names, not thoroughness.)
 *
 * ── Why two columns and not one ─────────────────────────────────────────────
 * *Waiting / Sending* describes a **message**; *Queued / Running* describes a
 * **job**. The composer's queue holds messages and the Tasks list holds jobs,
 * and `tasks.js`'s Activity view renders both — so one word per status would
 * have to be wrong for one of them. The subject, not the status, is what picks
 * the column, and a row says which it is (`entry.subject`) rather than the
 * renderer guessing from an id.
 *
 * ── Why this is a leaf module ───────────────────────────────────────────────
 * `runStatusTone` — the other thing derived from a status — lives in
 * `tasks.js`, and stays there: it decides a CSS class and every one of its
 * callers is inside that file. These words have three callers in three modules,
 * and `tasks.js` is only ever reached by `import('./tasks.js?v=…')`. A static
 * import of it from `queuePanel.js` would both pull the whole Tasks view onto
 * every page with a composer and register a SECOND module instance under the
 * query-less URL — two `_activitySources` maps, one of them invisible. So the
 * words live in a module with no imports of its own, which all three can take.
 *
 * The status *values* are not this file's business and are not touched here:
 * they are stored in rows and pinned by `FORBIDDEN.md`.
 */

/** `queued → running → success | error | skipped | aborted` — core/database.py. */
export const RUN_STATUSES = ['queued', 'running', 'success', 'error', 'skipped', 'aborted'];

/** Both subjects a run status can belong to. An enum, not a boolean: a third
 *  kind of thing is a new column here, not a new argument (`Law 10`). */
export const RUN_SUBJECTS = ['job', 'message'];

const WORDS = {
  //          job         message
  queued:   ['Queued',   'Waiting'],
  running:  ['Running',  'Sending'],
  // The Activity view shows a relative time instead of a word once a run is
  // over, so there is no `job` word to give — an empty string, which every
  // caller already treats as "use what you used before".
  success:  ['',         'Sent'],
  error:    ['',         'Failed'],
  skipped:  ['',         'Skipped'],
  aborted:  ['',         'Stopped'],
};

/**
 * The word to show for `status` on a row about `subject`.
 *
 * Returns `''` when the pair has no word, and the raw status for a value
 * outside the six — older rows carry `failed`, and printing what the row
 * actually says beats printing nothing.
 */
export function runStatusLabel(status, subject = 'job') {
  const row = WORDS[status];
  if (!row) return status || '';
  return row[subject === 'message' ? 1 : 0] || '';
}

/**
 * What an in-flight row says once it has been running long enough to look
 * stuck. Not a status — `tasks.js` derives it from elapsed time — but it is a
 * word a person reads out of the same slot as the ones above, so it is spelled
 * here with them rather than inline at the one branch that needs it.
 */
export function runStaleLabel(subject = 'job') {
  return subject === 'message' ? 'Still sending' : 'Still running';
}
