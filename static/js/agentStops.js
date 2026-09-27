// SPDX-License-Identifier: AGPL-3.0-or-later
// agentStops.js — the line that says why the agent stopped itself.
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

export default {
  AGENT_STOP_TYPES, ARGUMENTS_WITHHELD_TEXT,
  isAgentStop, agentStopHeadline, agentStopNode, renderAgentStop,
};
