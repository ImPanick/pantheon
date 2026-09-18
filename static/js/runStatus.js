// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/runStatus.js

/**
 * `B13`, extended by `B78`+`B84`. Everything derived from the six shipped run
 * statuses — the word, the tone, the dot class, and which values mean "still
 * in flight" — once, for every surface that reads them.
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
 * `tasks.js` is only ever reached by `import('./tasks.js?v=…')`. A static
 * import of it from `queuePanel.js` would both pull the whole Tasks view onto
 * every page with a composer and register a SECOND module instance under the
 * query-less URL — two `_activitySources` maps, one of them invisible. So
 * everything three modules need lives here, in a module with no imports of its
 * own, which all three can take.
 *
 * ── `B78`: why `runStatusTone` moved here ───────────────────────────────────
 * `B13` left it in `tasks.js` on the stated ground that "every one of its
 * callers is inside that file". Measured on the tree that shipped, that was
 * false: `queuePanel.js` `statusClass` is a caller outside the file, and being
 * unable to import `tasks.js` it had HAND-WRITTEN the same ladder — which is
 * how the two came to disagree. `runStatusDotClass('failed')` answered `info`
 * in the panel and `error` in the Activity view, off one input, because the
 * copy was made by a reader rather than by a call. The tone lives here now and
 * `tasks.js` re-exports it, so nothing that imported it from there breaks.
 *
 * ── `B84`: why the `job` column is six entries now ──────────────────────────
 * It held two, on the argument that the Activity view shows a relative time
 * rather than a word once a run is terminal, so a third-to-sixth entry would be
 * a column filled past its consumers (`Law 13`). The Activity view still shows
 * a time and that is still right — but it was never the only `job` surface.
 * The run-history list and the task card's last-run badge are both about jobs,
 * both were already on screen when `B13` landed, and both were spelling their
 * own words: the history list printed the STORED ENUM at the user (`success`,
 * `aborted`) and the badge mixed *Failed (no detail)* with a raw
 * `${last_run_status} (no detail)` six lines apart. The column was not past its
 * consumers; it was two consumers short of them.
 *
 * The status *values* are not this file's business and are not touched here:
 * they are stored in rows and pinned by `FORBIDDEN.md`.
 */

/** `queued → running → success | error | skipped | aborted` — core/database.py. */
export const RUN_STATUSES = ['queued', 'running', 'success', 'error', 'skipped', 'aborted'];

/** The two that mean "still in flight". The same pair Python exports as
 *  `TASK_RUN_ACTIVE_STATUSES`; a test asserts the two lists are equal, because
 *  before `B78` the JS half was spelled out by hand at each site that needed
 *  it and one of them had quietly grown a third member. */
export const RUN_ACTIVE_STATUSES = ['queued', 'running'];

/** Both subjects a run status can belong to. An enum, not a boolean: a third
 *  kind of thing is a new column here, not a new argument (`Law 10`). */
export const RUN_SUBJECTS = ['job', 'message'];

const WORDS = {
  //          job         message
  queued:   ['Queued',   'Waiting'],
  running:  ['Running',  'Sending'],
  // `B84`. These four were empty strings while the run-history list printed the
  // raw stored value at the user and the badge said `${status} (no detail)`.
  // `Success` and `Failed` are the badge's OWN two words, moved rather than
  // rewritten, so the string on that surface is byte-identical after the change
  // — the Activity view is untouched because it only ever asks for a word
  // inside its in-flight branch, which these four cannot reach.
  success:  ['Success',  'Sent'],
  error:    ['Failed',   'Failed'],
  skipped:  ['Skipped',  'Skipped'],
  aborted:  ['Stopped',  'Stopped'],
};

/**
 * The three things every renderer needs to know about a status, from the six.
 *
 * `B07` derived three of the four JS ladders from this; `B78` moved it here
 * from `tasks.js` because the fourth — `queuePanel.js` `statusClass` — could
 * not import that file and so re-typed the rule instead of calling it.
 *
 * `ok` / `error` are the two SCORED names: a status collapsing to `error` here
 * is what the Errors chip counts, so `core/database.py`'s rule that neither an
 * infrastructure abort nor a deliberate skip may corrupt an error rate is
 * enforced in exactly one expression.
 */
export function runStatusTone(status) {
  switch (status) {
    case 'success': return 'ok';
    case 'error':
    case 'failed': return 'error';      // `failed` is not in the vocabulary;
                                        // accepted because older rows carry it.
    case 'queued':
    case 'running': return 'pending';
    case 'skipped':
    case 'aborted': return 'info';
    default: return null;               // unknown / absent — caller decides.
  }
}

/**
 * The `.task-log-status-*` suffix a row's dot and stripe take.
 *
 * `''` for a value outside the vocabulary, because the two callers answer that
 * differently on purpose: the docked panel has nothing else to go on and says
 * `info`, while the Activity view falls back to a text scan of the result,
 * which is how rows written before the column existed still get a colour.
 * Returning a made-up answer here would delete that fallback (`Law 1`).
 *
 * `failed` is the one input the two callers used to disagree about — `info` in
 * the panel, `error` in the Activity view. `error` wins because that is what
 * `runStatusTone` already scores it as and what the Errors chip already counts,
 * and because `.task-log-status-failed` is not a rule that exists.
 */
export function runStatusDotClass(status) {
  const tone = runStatusTone(status);
  if (!tone) return '';
  if (tone === 'ok') return 'ok';
  if (tone === 'error') return 'error';
  return status;                        // queued | running | skipped | aborted
}

/** Whether a stored status means the run is over. The four terminal values,
 *  stated as the complement of the active pair so a seventh status added to
 *  `RUN_STATUSES` is terminal-by-default rather than silently neither. */
export function isRunFinished(status) {
  return !RUN_ACTIVE_STATUSES.includes(status || '');
}

/**
 * The word to show for `status` on a row about `subject`.
 *
 * Every one of the twelve pairs has a word since `B84`; `''` is now reachable
 * only for an absent status. A value outside the six returns the raw status —
 * older rows carry `failed`, and printing what the row actually says beats
 * printing nothing.
 */
export function runStatusLabel(status, subject = 'job') {
  const row = WORDS[status];
  if (!row) return status || '';
  return row[subject === 'message' ? 1 : 0] || '';
}

/**
 * Whether a run's stored text is an answer or the reason there is not one.
 *
 * `B171`. Three statuses reach the Completed tab and two of them left no
 * assistant turn behind: an `error` run's text is an exception message and an
 * `aborted` run's is *"Stopped by user"*. Both were being replayed into a chat
 * session as the assistant's own words. This is the one question that decides
 * that, derived from `runStatusTone` rather than from a fourth list of status
 * names — `error`/`failed` score `error` and `skipped`/`aborted` score `info`,
 * and those four are exactly the four that answer nothing.
 *
 * An absent or legacy status has no tone, and this says `false` for it on
 * purpose: the caller's old behaviour is what a row written before the column
 * existed still gets (`Law 1`). `queued` and `running` are `false` too — they
 * have not finished, so "left no answer" is not yet a fact about them.
 */
export function runLeftNoAnswer(status) {
  const tone = runStatusTone(status);
  return tone === 'error' || tone === 'info';
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

/* ─────────────────────────────────────────────────────────────────────────
 * `P15-11` — the word for a destination we have stopped calling
 *
 * `OutboundHostLimiter.snapshot()` has held per-host cooldowns, the 429 count
 * and the seconds waited since `P15-01`, and until this row its only readers
 * were a Prometheus scrape, a diagnostic bundle and an ADMIN-ONLY self-check
 * panel in Settings. The person watching a feature do nothing had nothing at
 * all: `routes/email_routes.py` has been answering the 60-second unread poll
 * with `sync.source: "unavailable"` and a `retry_in` since `P15-12` — written,
 * in the response, for this row — and both clients dropped it on the floor.
 *
 * WHY THE WORDS LIVE HERE AND NOT AT THE RENDERER.
 *
 * Six places in the product already know what a throttle is: the limiter, the
 * self-check, the metrics exporter, the diagnostic bundle, the unread poll and
 * the skill importer's message. `Law 13` is the rule that a seventh is a defect
 * — so the CLIENT gets one vocabulary, here, beside the other words a person
 * reads out of a status slot, and the renderers call it.
 *
 * A THROTTLE IS NOT A RUN STATUS, and that is why nothing above changes.
 * `RUN_STATUSES` are values stored in `task_runs.status` and pinned by
 * `FORBIDDEN.md`; a cooldown is a property of a DESTINATION, has no row, and
 * can be true while a run is queued, running or finished. Adding a seventh
 * member to that list would have been the quick version of this and would have
 * put a word that is not in the database into the enum that is.
 * ──────────────────────────────────────────────────────────────────────── */

/** The `sync.source` values that mean "we are not calling this right now". */
export const THROTTLED_SOURCES = ['unavailable', 'throttled', 'cooldown'];

export function isThrottledSource(source) {
  return THROTTLED_SOURCES.includes(String(source || '').toLowerCase());
}

/**
 * *"in 4 min"*, from a number of seconds. `''` when there is no number.
 *
 * An absent countdown is common and honest — a protocol with no `Retry-After`
 * gives us an escalating local cooldown and not a promise — so the caller gets
 * an empty string to leave out rather than a fabricated "in 0s". Rounded UP,
 * because a countdown that reads "in 0 min" for the last minute is a countdown
 * that looks stuck.
 */
export function clearsInLabel(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s <= 0) return '';
  if (s < 90) return `in ${Math.max(1, Math.ceil(s))}s`;
  const mins = Math.ceil(s / 60);
  if (mins < 90) return `in ${mins} min`;
  return `in ${Math.ceil(mins / 60)} h`;
}

/**
 * The full sentence for a throttled destination, or `''` when nothing is.
 *
 * `{ source, retryIn, what }` — `what` names the thing that is quiet ("This
 * mailbox", "GitHub"); the default is deliberately vague because a renderer
 * that does not know should say less rather than guess.
 *
 * The sentence says three things and always in this order: **it is paused**,
 * **when it clears**, and **that this is deliberate**. The third is the part
 * people get wrong — without it a pause reads as a fault, and the thing a user
 * does about a fault is press the button again, which is what deepens a rate
 * limit (`P15-03` learned that on a real ban).
 */
export function throttleNotice({ source, retryIn, what } = {}) {
  if (!isThrottledSource(source)) return '';
  const subject = what || 'This';
  const when = clearsInLabel(retryIn);
  return when
    ? `${subject} is paused — retrying ${when}`
    : `${subject} is paused until the service lets us back in`;
}

/** The dot/stripe class for a throttled row, from the same ladder as the rest. */
export function throttleDotClass() {
  return 'skipped';        // `runStatusTone('skipped') === 'info'` — not an error
}
