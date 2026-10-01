// SPDX-License-Identifier: AGPL-3.0-or-later
// agentStops.js — the line that says why the agent stopped itself, and (`B915`,
// at the end of this file) the turn's other notes: the step limit and its
// Continue offer, the tool budget, the teacher's takeover, the skill notes, and
// (`B921`) a compaction of the turn's context.
//
// `P4-10`. Two guards in the agent loop end work the model did not end: the
// loop-breaker (the same call over and over) and the unkept-promise stop (it
// kept writing "Let me check the logs" and never made the call). Both used to
// reach the page as one fixed sentence in brackets —
// `[Agent guard: The loop-breaker detected repeated tool calls …]` — which said
// neither which tool, nor how often, nor what the model kept promising.
//
// And the sentence did not stay. It was appended to the round's own bubble:
// the next `agent_step` finalizes that bubble, and a round that wrote nothing —
// which is exactly what a loop-breaker round is — is hidden with everything in
// it; the unkept-promise stop ends the stream, and the end-of-stream render
// replaces the bubble's body. `rounds_exhausted` in `chat.js` found the same
// thing and says so beside its own note. So the line flashed and was gone, and
// after a reload it had never existed.
//
// Now: the server composes the words once (`src/agent_stops.py`) and saves the
// same event with the reply (`agent_stops` on the metrics envelope). This
// module is the one place that draws them, for the live stream and for history
// replay alike, always as a sibling in the chat history and never inside a
// message bubble. Everything is set through `textContent`: the headline quotes
// the model's own words and the argument excerpt is a command line, and neither
// may become markup.
//
// No imports on purpose: it is loaded by `chat.js` and `chatRenderer.js`, and
// the test sandboxes that copy either of those copy this too.

/** The two stream events that mean "a guard stopped this turn". */
export const AGENT_STOP_TYPES = Object.freeze(['loop_breaker_triggered', 'intent_nudge_exhausted']);

/** Said when the arguments were withheld. One reason exists: see
 *  `safe_arguments` in `src/agent_stops.py`. */
export const ARGUMENTS_WITHHELD_TEXT = 'Its arguments are not shown here because they may hold a credential.';

export function isAgentStop(event) {
  return !!event && AGENT_STOP_TYPES.includes(event.type);
}

/** The headline for `event`. An event saved before `P4-10` carries only the
 *  old fixed `message`, and that is still better than nothing. */
export function agentStopHeadline(event) {
  const message = event && typeof event.message === 'string' ? event.message.trim() : '';
  if (message) return message;
  return event && event.type === 'intent_nudge_exhausted'
    ? 'Stopped: it said it would act and did not make a call.'
    : 'Stopped: it kept repeating the same tool calls.';
}

/** Build the line. Returns the node; the caller decides where it goes. */
export function agentStopNode(doc, event) {
  const d = doc || (typeof document !== 'undefined' ? document : null);
  if (!d || !isAgentStop(event)) return null;
  const node = d.createElement('div');
  node.className = 'agent-stop';
  node.setAttribute('role', 'note');
  if (event.kind) node.dataset.stopKind = String(event.kind);
  if (Number.isInteger(Number(event.round)) && Number(event.round) >= 1) {
    node.dataset.round = String(Number(event.round));
  }

  const head = d.createElement('div');
  head.className = 'agent-stop-headline';
  head.textContent = agentStopHeadline(event);
  node.appendChild(head);

  if (event.arguments_state === 'shown' && typeof event.arguments === 'string' && event.arguments) {
    const args = d.createElement('code');
    args.className = 'agent-stop-args';
    args.textContent = event.arguments;
    node.appendChild(args);
  } else if (event.arguments_state === 'withheld') {
    const withheld = d.createElement('div');
    withheld.className = 'agent-stop-withheld';
    withheld.textContent = ARGUMENTS_WITHHELD_TEXT;
    node.appendChild(withheld);
  }

  const next = typeof event.next === 'string' ? event.next.trim() : '';
  if (next) {
    const hint = d.createElement('div');
    hint.className = 'agent-stop-next';
    hint.textContent = next;
    node.appendChild(hint);
  }
  return node;
}

/**
 * Draw `event` at the end of `box` (the `#chat-history` element) and return
 * the line, or `null` when there is nothing to draw.
 *
 * The one entry point. The live stream calls it from its SSE branch, history
 * replay calls it after the round the stop happened in, and a resumed stream
 * (`P4-24`) should call it for the same two event types rather than drawing a
 * third version.
 */
export function renderAgentStop(box, event) {
  if (!box || typeof box.appendChild !== 'function') return null;
  const node = agentStopNode(box.ownerDocument || (typeof document !== 'undefined' ? document : null), event);
  if (!node) return null;
  box.appendChild(node);
  return node;
}

// ── `B915` · The turn's other notes ──────────────────────────────────────────
//
// Six more events draw a line into the history beside the reply, as siblings
// and never inside a bubble, for the reason above: the step limit and its
// Continue offer (`rounds_exhausted`), the tool budget (`budget_exceeded`), the
// teacher taking over (`teacher_takeover`), and what became of a skill
// (`skill_saved`, `escalation_failed`, `skill_save_failed`). Each was drawn by
// its own arm in `chat.js` and saved nowhere, so any reload dropped them — and
// Continue ▸ went with its note, so a run that hit the step limit could not be
// continued from the button after a reload; a resumed stream, which ends in a
// reload, drew two of them and lost those at its end. The route saves them now
// (`agent_notes`, collected by `AgentNotes` in `src/agent_stops.py`), and this
// is the one place that draws them: the live stream, a resumed one and history
// replay. Every word is set through `textContent` — a skill's name, a teacher's
// model and the reason a student failed (which can quote a tool's output) are
// all somebody else's text — where the three teacher arms used `innerHTML`.

/** The events drawn here. `AGENT_NOTE_TYPES` in `src/agent_stops.py` is the
 *  server's copy, and a test holds the two equal. */
export const AGENT_NOTE_TYPES = Object.freeze(['rounds_exhausted', 'budget_exceeded',
  'teacher_takeover', 'skill_saved', 'escalation_failed', 'skill_save_failed',
  // `B921`. The turn's context summarised to fit (`P4-13`'s event). Live it is
  // a toast (`chat.js`), which a reload cannot redraw; the route saves it with
  // the reply now, and the reload draws it as a line where it happened.
  'compacted']);

/**
 * `P4-13` / `B921`. What a `compacted` event says, in the trim notice's words:
 * *Context compacted — older messages summarized (9/42 messages kept, 81,400 →
 * 12,200 tokens)*. The figures are read out of `data`, where the event puts
 * them; with none, or with none that shrank, it is the bare sentence, never a
 * `0/0` that would read as a measurement. The live toast and the saved line
 * both say it through here, so the two cannot drift.
 */
export function compactionNoticeText(event) {
  const cd = (event && event.data) || {};
  const cBefore = Number(cd.messages_before || 0);
  const cAfter = Number(cd.messages_after || 0);
  const tBefore = Number(cd.tokens_before || 0);
  const tAfter = Number(cd.tokens_after || 0);
  const parts = [];
  if (cBefore && cAfter && cBefore > cAfter) {
    parts.push(`${cAfter}/${cBefore} messages kept`);
  }
  if (tBefore && tAfter && tBefore > tAfter) {
    parts.push(`${tBefore.toLocaleString()} → ${tAfter.toLocaleString()} tokens`);
  }
  const cDetail = parts.length ? ` (${parts.join(', ')})` : '';
  return `Context compacted — older messages summarized${cDetail}`;
}

/**
 * `B953`. The `compacted` event a saved reply's record says happened, or
 * `null`. `P4-13` saves a chat turn's compaction on its record —
 * `context_compacted` and, when it was measured, the messages and tokens
 * before and after (`compaction_metric_figures`, `src/context_compactor.py`) —
 * and nothing drew it: the live toast said it and a reload said nothing. An
 * agent turn's is saved as a note (`B921`); a chat reply is one bubble and has
 * no notes, so this is read off its record, in the event's own shape, and drawn
 * through `renderAgentNote` in the words the toast used.
 */
export function compactionFromRecord(record) {
  if (!record || record.context_compacted !== true) return null;
  const data = {};
  for (const [key, saved] of [['messages_before', 'context_messages_before_compact'],
    ['messages_after', 'context_messages_after_compact'],
    ['tokens_before', 'context_tokens_before_compact'],
    ['tokens_after', 'context_tokens_after_compact']]) {
    const value = Number(record[saved]);
    if (record[saved] != null && Number.isFinite(value)) data[key] = value;
  }
  return { type: 'compacted', data };
}

/** What Continue ▸ asks for after the step limit. */
export const STEP_LIMIT_CONTINUE_PROMPT = 'You hit the step limit before finishing — the task is not '
  + 'complete. Continue from exactly where you left off and keep going until it is done. Do NOT '
  + 'repeat work already done.';

export function isAgentNote(event) {
  return !!event && AGENT_NOTE_TYPES.includes(event.type);
}

function textPart(d, tag, text, { cls = '', opacity = '' } = {}) {
  const n = d.createElement(tag);
  if (cls) n.className = cls;
  if (opacity) n.style.opacity = opacity;
  n.textContent = text;
  return n;
}

function words(d, text) {
  return d.createTextNode(text);
}

/**
 * Continue ▸ after the step limit: the note goes, the next send is a
 * continuation of `reply` (the turn's first bubble), its prompt is hidden, and
 * it is sent. Through `window.chatModule`, which owns the send, as the history
 * renderer's own Continue already goes (`chatRenderer.js`). `B941`: it carries
 * the run's steps on (`{ steps: true }`) — the continuation stays where it is
 * drawn and the server joins the two replies — where a stopped reply's
 * Continue merges its text into the bubble it stopped in.
 */
function continueAfterStepLimit(d, note, reply) {
  note.remove();
  const chat = (typeof window !== 'undefined' && window.chatModule) || null;
  const target = typeof reply === 'function' ? reply() : reply;
  if (chat) {
    if (typeof chat.setHideUserBubble === 'function') chat.setHideUserBubble();
    if (typeof chat.setPendingContinue === 'function') chat.setPendingContinue(target || null, { steps: true });
  }
  const input = d.getElementById('message');
  if (input) {
    input.value = STEP_LIMIT_CONTINUE_PROMPT;
    const send = d.querySelector('.send-btn');
    if (send) send.click();
  }
}

/** The small muted line the tool budget's note is, and a compaction's. */
const QUIET_NOTE_STYLE = 'font-size:11px;opacity:0.6;font-style:italic;padding:4px 8px;margin:4px 0;';

/** Build the note for `event`, or `null` for anything else. `opts.reply` is the
 *  turn's first bubble (or a function returning it), for Continue ▸. */
export function agentNoteNode(doc, event, opts = {}) {
  const d = doc || (typeof document !== 'undefined' ? document : null);
  if (!d || !isAgentNote(event)) return null;
  const node = d.createElement('div');
  node.setAttribute('role', 'note');
  switch (event.type) {
    case 'rounds_exhausted': {
      node.className = 'stopped-indicator rounds-exhausted';
      node.appendChild(textPart(d, 'span', `Reached the ${event.rounds || ''}-step limit — not finished.`,
        { cls: 'rounds-exhausted-label' }));
      const btn = d.createElement('button');
      btn.className = 'continue-btn';
      btn.title = 'Continue the task';
      btn.textContent = 'Continue ▸';
      btn.addEventListener('click', () => continueAfterStepLimit(d, node, opts.reply));
      node.appendChild(btn);
      return node;
    }
    case 'budget_exceeded':
      node.className = 'budget-exceeded-note';
      node.style.cssText = QUIET_NOTE_STYLE;
      node.textContent = `Tool budget reached (${event.used}/${event.limit} calls). Agent stopped.`;
      return node;
    case 'compacted':   // `B921`: the tool budget's quiet line, in the toast's words
      node.className = 'context-compacted-note';
      node.style.cssText = QUIET_NOTE_STYLE;
      node.textContent = compactionNoticeText(event);
      return node;
    case 'teacher_takeover': {
      node.className = 'teacher-takeover-banner';
      node.style.cssText = 'margin:10px 0;padding:8px 12px;border-left:3px solid #c08a3e;background:rgba(192,138,62,0.08);font-size:12px;color:var(--fg);border-radius:4px;';
      node.appendChild(textPart(d, 'strong', 'Teacher takeover:'));
      node.appendChild(words(d, ' escalating to '));
      node.appendChild(textPart(d, 'code', String(event.teacher_model || 'teacher')));
      if (event.student_failure) {
        node.appendChild(words(d, ' — '));
        node.appendChild(textPart(d, 'span', String(event.student_failure), { opacity: '0.7' }));
      }
      return node;
    }
    case 'skill_saved':
      node.className = 'skill-saved-note';
      node.style.cssText = 'margin:6px 0;padding:6px 10px;border-left:3px solid #4a8a4a;background:rgba(74,138,74,0.07);font-size:12px;color:var(--fg);border-radius:4px;';
      node.appendChild(textPart(d, 'strong', 'Skill learned:'));
      node.appendChild(words(d, ' '));
      node.appendChild(textPart(d, 'code', String(event.name || '')));
      if (event.category) {
        node.appendChild(words(d, ' '));
        node.appendChild(textPart(d, 'span', `[${event.category}]`, { opacity: '0.6' }));
      }
      return node;
    default:   // escalation_failed, skill_save_failed
      node.className = 'escalation-failed-note';
      node.style.cssText = 'margin:6px 0;padding:6px 10px;border-left:3px solid #8a4a4a;background:rgba(138,74,74,0.07);font-size:12px;color:var(--fg);border-radius:4px;';
      node.appendChild(textPart(d, 'strong',
        event.type === 'escalation_failed' ? 'Teacher could not solve it:' : 'Skill not saved:'));
      node.appendChild(words(d, ' '));
      node.appendChild(textPart(d, 'span', String(event.reason || ''), { opacity: '0.75' }));
      return node;
  }
}

/**
 * Draw `event` at the end of `box` (the `#chat-history` element) and return the
 * note, or `null` when there is nothing to draw. One Continue at a time: a
 * later step limit takes an earlier one's box away first, as the live arm
 * always did, so a reloaded history keeps only the last.
 */
export function renderAgentNote(box, event, opts = {}) {
  if (!box || typeof box.appendChild !== 'function') return null;
  const node = agentNoteNode(box.ownerDocument || (typeof document !== 'undefined' ? document : null),
    event, opts);
  if (!node) return null;
  if (event.type === 'rounds_exhausted' && typeof box.querySelectorAll === 'function') {
    Array.from(box.querySelectorAll('.rounds-exhausted')).forEach((old) => old.remove());
  }
  box.appendChild(node);
  return node;
}

/**
 * A later message withdraws a step limit's Continue offer: the note stays, its
 * button goes. Continue carries on the conversation's latest reply — the
 * server merges the last two — so offered from an earlier turn it would merge
 * the wrong ones; and once the offer is saved, a reload would put it back under
 * every turn that ever hit the limit. Called where a user message is drawn,
 * live and on reload alike (`addMessage`). Returns how many it withdrew.
 */
export function withdrawContinueOffers(root) {
  if (!root || typeof root.querySelectorAll !== 'function') return 0;
  let withdrawn = 0;
  for (const note of Array.from(root.querySelectorAll('.rounds-exhausted'))) {
    for (const btn of Array.from(note.querySelectorAll('.continue-btn'))) {
      btn.remove();
      withdrawn += 1;
    }
  }
  return withdrawn;
}

export default {
  AGENT_STOP_TYPES, ARGUMENTS_WITHHELD_TEXT,
  isAgentStop, agentStopHeadline, agentStopNode, renderAgentStop,
  AGENT_NOTE_TYPES, STEP_LIMIT_CONTINUE_PROMPT,
  isAgentNote, agentNoteNode, renderAgentNote, withdrawContinueOffers,
  compactionNoticeText, compactionFromRecord,
};
