// SPDX-License-Identifier: AGPL-3.0-or-later
// agentMeter.js — the live prep breakdown and the step / tool-call meter.
//
// `P4-08`. The agent loop has always timed four preparation steps — request
// setup, tool selection, prompt build, context trim — and until this row it
// said so once, after the last of them had finished, in an event the chat route
// then dropped. What a person saw was a static spinner label: *Processing
// request*, for as long as preparation plus the model's first token took. The
// loop now sends a frame as each step starts (`agent_prep`, `status: running`)
// and one when all four are done; the label under the spinner is the step that
// is running, and the line beneath it is the ones that have finished, each with
// the time the server measured.
//
// `P4-23`. A run is held to a step limit and, optionally, a tool-call limit, and
// the first either of them reached the screen was the event announcing the run
// had hit one. `agent_budget` carries the loop's own counters and caps — the
// numbers the `for` and the budget check read, after the local-inference lift —
// at the top of every round and after every counted tool call. The meter under
// the spinner is drawn from nothing else, so it cannot disagree with the stop.
//
// `B907`. And the wait after preparation: what the reply's spinner says when
// the model's first token is slow, which reads what the prep line knows rather
// than guessing why (`firstTokenWaitText`), and which events end that wait
// (`endsFirstTokenWait`).
//
// `P7-10`. And before any of it: *how far can it run unattended* was a
// settings tab away from the moment of choosing Agent mode. The composer now
// says it beside the mode toggle (`limitsPreview`, `renderLimitsHint`), from
// `GET /api/chat/agent-limits` — the four limit keys of a run's first
// `agent_budget` frame, resolved on the server with the loop's own helpers
// before there is a run. Read by the same parser and put into the same rule
// sentences as the live meter, so the promise before the run and the meter
// during it are one vocabulary (`Law 14`) and neither re-derives the lift.
//
// ── Measured, estimated, unknown (`Law 10`) ────────────────────────────────
// A figure printed plainly was measured on the server. A figure with `~` is the
// browser counting up while a step is still running, and it is replaced by the
// measured one when the step finishes — the same `~` the Message Stats popup
// already uses for an estimated token count. A step that has not run has no
// figure at all, and a limit that does not exist says "no limit", never `0`.
//
// ── One render path (`Law 14`) ─────────────────────────────────────────────
// The meter is not a widget of its own. It is a line of detail under whichever
// spinner is showing — the reply's first spinner while the agent prepares, the
// "Thinking" spinner between tools, the spinner a new round opens with — and it
// goes when that spinner goes (`Spinner.attachDetail`). Every stream handler
// hands it events through `presentMeterEvent`, which is the call a resumed
// background stream (`P4-24`) and a compare pane (`B916`) make to draw the
// same thing the same way.
//
// This module imports nothing, so a test can load it without the app.

/** The four preparation steps, in the order the loop runs them. `running` is
 *  what the spinner says while the step is under way; `done` names it once it
 *  has a measured time — the two label forms `P4-01` settled for tool cards. */
export const PREP_PHASES = Object.freeze([
  Object.freeze({ key: 'request_setup', running: 'Reading the request', done: 'Request setup' }),
  Object.freeze({ key: 'tool_selection', running: 'Choosing tools', done: 'Tool selection' }),
  Object.freeze({ key: 'prompt_build', running: 'Building the prompt', done: 'Prompt build' }),
  Object.freeze({ key: 'context_trim', running: 'Fitting the context window', done: 'Context trim' }),
]);

const PREP_KEYS = PREP_PHASES.map((p) => p.key);

/** What the spinner says once preparation is over and the model has the prompt. */
export const WAITING_FOR_MODEL = 'Waiting for the model';

/** Every event the meter reads. The first two exist for it; the last two are
 *  the stops it predicts, recorded so the meter ends on what actually happened. */
export const METER_EVENT_TYPES = Object.freeze(
  new Set(['agent_prep', 'agent_budget', 'rounds_exhausted', 'budget_exceeded']));

// `P7-12`: `raised_for_run` — a cap the agent raised for this run, never saved.
const RAISED_FOR_RUN = 'raised_for_run';
const ROUND_LIMIT_SOURCES = ['configured', 'local_lift', 'forced_lift', RAISED_FOR_RUN];

/** A step cap the local-inference lift (or `PANTHEON_FORCE_UNLIMITED`) set,
 *  which is said as lifted and drawn with no bar. A raised one is a number the
 *  run is really held to, and keeps its bar. */
function isLifted(b) {
  return b.source === 'local_lift' || b.source === 'forced_lift';
}

/** Where a person changes the two limits. Admin-only, and said so. */
const SETTINGS_PATH = 'Settings › Agent Tools';

// ── small readers ─────────────────────────────────────────────────────────

function positiveInt(v) {
  const n = Number(v);
  return Number.isInteger(n) && n >= 1 ? n : null;
}

function countOf(v) {
  const n = Number(v);
  return Number.isInteger(n) && n >= 0 ? n : null;
}

function seconds(v) {
  if (v === null || v === undefined || typeof v === 'boolean' || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function num(n) {
  return Number(n).toLocaleString('en-US');
}

/** A measured duration, as the prep line prints it. Never `0.00s`: a step the
 *  server timed at under ten milliseconds took *some* time, and a zero would
 *  read as a step that did not happen. */
export function formatPrepSeconds(v) {
  const s = seconds(v);
  if (s === null) return '';
  if (s < 0.01) return '<0.01s';
  if (s < 10) return `${s.toFixed(2)}s`;
  if (s < 60) return `${s.toFixed(1)}s`;
  const whole = Math.round(s);
  return `${Math.floor(whole / 60)}m ${String(whole % 60).padStart(2, '0')}s`;
}

/** The name of a prep step in `form` ('running' | 'done'). A key this module
 *  does not know keeps its own name rather than being given a wrong one. */
export function prepPhaseLabel(key, form = 'done') {
  const phase = PREP_PHASES.find((p) => p.key === key);
  if (!phase) return String(key == null ? '' : key);
  return form === 'running' ? phase.running : phase.done;
}

/** `[{ key, label, value }]` for a finished breakdown, in step order — what the
 *  Message Stats popup prints, so the popup and the live line use one set of
 *  words for the same four figures. Unknown keys follow, under their own name. */
export function prepBreakdownRows(breakdown) {
  if (!breakdown || typeof breakdown !== 'object') return [];
  const rows = [];
  for (const phase of PREP_PHASES) {
    if (Object.prototype.hasOwnProperty.call(breakdown, phase.key) && seconds(breakdown[phase.key]) !== null) {
      rows.push({ key: phase.key, label: phase.done, value: formatPrepSeconds(breakdown[phase.key]) });
    }
  }
  for (const [key, value] of Object.entries(breakdown)) {
    if (PREP_KEYS.includes(key) || seconds(value) === null) continue;
    rows.push({ key, label: String(key), value: formatPrepSeconds(value) });
  }
  return rows;
}

// ── state ─────────────────────────────────────────────────────────────────

/** An empty meter. `teacher` marks the run a takeover started (`teacher_takeover`
 *  stamps every event it relays), because that run has limits of its own. */
export function createMeterState() {
  return { teacher: false, prep: null, budget: null, stop: null };
}

/**
 * The limit half of an `agent_budget` frame — or of `GET /api/chat/agent-limits`,
 * which answers with the same four keys before a run exists (`P7-10`). One
 * reader for both, so the promise before a run and the meter during it cannot
 * read a payload two ways.
 */
function limitsFrom(payload) {
  const roundLimit = positiveInt(payload.round_limit);
  const source = ROUND_LIMIT_SOURCES.includes(payload.round_limit_source)
    ? payload.round_limit_source : 'configured';
  const hasToolLimitKey = Object.prototype.hasOwnProperty.call(payload, 'tool_call_limit');
  return {
    roundLimit,
    source,
    configured: positiveInt(payload.round_limit_configured) || roundLimit,
    // Three states, not two: a number, `null` for "no limit", and
    // `undefined` for a frame that did not say — which is not the same as
    // saying there is none.
    toolLimit: hasToolLimitKey
      ? (payload.tool_call_limit === null ? null : positiveInt(payload.tool_call_limit))
      : undefined,
    // `P7-12`. Absent on a frame from before it, which is the same as configured.
    toolSource: payload.tool_call_limit_source === RAISED_FOR_RUN ? RAISED_FOR_RUN : 'configured',
  };
}

function timingsFrom(data) {
  const out = {};
  if (!data || typeof data !== 'object') return out;
  for (const key of PREP_KEYS) {
    const s = seconds(data[key]);
    if (s !== null) out[key] = s;
  }
  return out;
}

/**
 * The meter's next state after `event`. Pure: the same events in the same order
 * give the same state, which is what lets a stream replayed from its start —
 * `/api/chat/resume` replays the whole run buffer — rebuild the meter exactly.
 * Returns `state` itself (the same object) when the event changes nothing.
 *
 * `nowMs` is the browser's clock, used for one thing only: when the running
 * prep step started, so its `~` counter can count. It never touches a measured
 * figure.
 */
export function reduceMeter(state, event, nowMs = Date.now()) {
  const s0 = state || createMeterState();
  if (!event || typeof event !== 'object' || !METER_EVENT_TYPES.has(event.type)) return s0;
  const teacher = event.teacher === true;
  // A takeover is a new run with limits of its own: start it clean rather than
  // letting the student's step count bleed into the teacher's.
  const s = teacher !== s0.teacher ? { ...createMeterState(), teacher } : s0;

  if (event.type === 'agent_prep') {
    // A frame with no `status` is the one the loop sent before `P4-08`, which
    // only ever went out once everything was done.
    const status = event.status === 'running' ? 'running' : 'done';
    const phase = status === 'running' && PREP_KEYS.includes(event.phase) ? event.phase : null;
    if (status === 'running' && !phase) return s0;
    const prev = s.prep;
    const timings = timingsFrom(event.data);
    return {
      ...s,
      prep: {
        status,
        phase,
        // The same step announced twice keeps its first start time, so a
        // replayed frame does not reset the counter to zero.
        phaseSince: phase && prev && prev.phase === phase && prev.status === 'running'
          ? prev.phaseSince : nowMs,
        timings,
        total: status === 'done' ? seconds(event.total) : null,
      },
    };
  }

  if (event.type === 'agent_budget') {
    const round = positiveInt(event.round);
    if (round === null) return s0;
    return {
      ...s,
      budget: {
        round,
        ...limitsFrom(event),
        toolCalls: countOf(event.tool_calls),
      },
    };
  }

  if (event.type === 'rounds_exhausted') {
    const limit = positiveInt(event.rounds) || (s.budget && s.budget.roundLimit) || null;
    return { ...s, stop: { kind: 'rounds', limit } };
  }

  // budget_exceeded
  const limit = positiveInt(event.limit) || (s.budget && s.budget.toolLimit) || null;
  return { ...s, stop: { kind: 'tool_calls', limit, used: countOf(event.used) } };
}

/** True once there is anything to draw. */
export function meterHasContent(state) {
  return !!(state && (state.prep || state.budget || state.stop));
}

/** True while a prep step is running — the only time the `~` counter moves. */
export function prepIsRunning(state) {
  return !!(state && state.prep && state.prep.status === 'running');
}

// ── words ─────────────────────────────────────────────────────────────────

/** What the spinner should say, from the prep state alone. `''` when prep has
 *  not started, so a caller leaves the label it already has. */
export function prepSpinnerLabel(state) {
  const p = state && state.prep;
  if (!p) return '';
  if (p.status === 'running') return prepPhaseLabel(p.phase, 'running');
  return WAITING_FOR_MODEL;
}

/** Whether the prep line still belongs on screen. It is about the wait before
 *  the run gets going, so it gives way once a tool call has been counted or a
 *  second step has started — otherwise it would ride every spinner for the
 *  rest of the turn, saying the same finished thing. */
export function prepLineVisible(state) {
  const b = state && state.budget;
  return !b || (b.round <= 1 && !b.toolCalls);
}

/** The prep line: finished steps with their measured times, the running one
 *  with the browser's `~` count (or an ellipsis in its first second). */
export function prepLineText(state, nowMs = Date.now()) {
  const p = state && state.prep;
  if (!p || !prepLineVisible(state)) return '';
  const parts = [];
  for (const phase of PREP_PHASES) {
    if (Object.prototype.hasOwnProperty.call(p.timings, phase.key)) {
      parts.push(`${phase.done} ${formatPrepSeconds(p.timings[phase.key])}`);
    } else if (p.status === 'running' && p.phase === phase.key) {
      const counted = Math.floor(Math.max(0, nowMs - p.phaseSince) / 1000);
      parts.push(counted >= 1 ? `${phase.done} ~${counted}s` : `${phase.done}…`);
    }
  }
  if (p.status === 'done') {
    const lead = p.total !== null ? `Prepared in ${formatPrepSeconds(p.total)}` : 'Prepared';
    return parts.length ? `${lead} · ${parts.join(' · ')}` : lead;
  }
  return parts.length ? `Preparing · ${parts.join(' · ')}` : 'Preparing';
}

// ── the wait for a first token (`B907`) ──────────────────────────────────

/** How long after sending, with nothing back from the model, before the reply's
 *  spinner starts saying the wait is long. */
export const FIRST_TOKEN_WAIT_FROM_MS = 20000;

/** Events that end the wait for a first token: the model's own output — a token,
 *  thinking included, or a tool call and what only follows one — plus the two
 *  that replace the spinner's words themselves (research progress, an approval
 *  resolved). Not `stream_steerable`, not a prep or budget frame, not metadata:
 *  every stream opens with those, and the wait messages used to be called off by
 *  the first `data:` line of any kind, before they could say anything. */
const FIRST_OUTPUT_TYPES = Object.freeze(new Set([
  'tool_start', 'tool_blocked', 'tool_output', 'tool_progress', 'ask_user',
  'doc_stream_open', 'doc_stream_delta', 'generated_image',
  'agent_step', 'loop_breaker_triggered', 'intent_nudge_exhausted',
  'research_progress', 'tool_approval_resolved',
]));

/** True when `event` is the model answering (or something that replaces the
 *  wait on screen), so there is no longer a first token to wait for. */
export function endsFirstTokenWait(event) {
  if (!event || typeof event !== 'object') return false;
  if (typeof event.delta === 'string' && event.delta) return true;
  return FIRST_OUTPUT_TYPES.has(event.type);
}

function countText(s) {
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}

/**
 * `B907`. What the reply's spinner says once the first token is slow in coming:
 * `waitedMs` after sending, with nothing back from the model yet. Only what the
 * page knows, never a guess about why:
 *
 *   - a prep step is running: `''`, which leaves the step's own label up — it,
 *     and the `~` count on the line under it, already say more;
 *   - preparation has finished: *Waiting for the model*, and how long it has
 *     had the prompt — counted in the browser from the frame that said prep was
 *     done, so marked `~` like every figure the browser counts (`Law 10`);
 *   - no prep frames at all (a chat turn, or an agent run whose first frame has
 *     not arrived): the plain fact that nothing has come back, and roughly for
 *     how long, in words that stay true while the spinner shows them.
 *
 * The 60s line used to say *Large local model is pre-filling context* — about
 * every model, local or not, whatever it was actually doing.
 */
export function firstTokenWaitText(state, waitedMs, nowMs = Date.now()) {
  const p = state && state.prep;
  if (p && p.status === 'running') return '';
  if (p) {
    const s = Math.floor(Math.max(0, nowMs - p.phaseSince) / 1000);
    return s >= 1 ? `${WAITING_FOR_MODEL} · ~${countText(s)}` : WAITING_FOR_MODEL;
  }
  const w = Number(waitedMs);
  if (!(w >= FIRST_TOKEN_WAIT_FROM_MS)) return '';
  if (w >= 120000) return 'Still working - no tokens yet from the model';
  if (w >= 60000) return 'Still waiting for first token - over a minute';
  return 'Still waiting for first token';
}

function nearThreshold(limit) {
  return Math.max(2, Math.ceil(limit * 0.2));
}

/** `'at'`, `'near'` or `''` for `used` of `limit`. */
function toneFor(used, limit) {
  if (!limit || used === null) return '';
  if (used >= limit) return 'at';
  return limit - used <= nearThreshold(limit) ? 'near' : '';
}

/**
 * Everything the budget line and its note say, as data. `null` before the
 * first `agent_budget` frame.
 *
 *   steps  { text, value, max, tone }   `max` is null when there is no bar
 *   tools  { text, value, max, tone } | null
 *   note   { text, tone }               what happens at the limit, in words
 *   title  string                       the whole rule, and where it is set
 *
 * `opts.offersContinue` — whether the surface drawing this offers Continue at
 * the step limit. The chat does (`rounds_exhausted`'s box); a compare pane
 * does not (`B916`), and a meter there that said "and offers Continue" would
 * promise a button that never comes (`Law 10`). Defaults to true.
 */
export function budgetView(state, opts = {}) {
  const b = state && state.budget;
  if (!b) return null;
  const offersContinue = !(opts && opts.offersContinue === false);
  const andContinue = offersContinue ? ' and offers Continue' : '';
  const who = state.teacher ? 'Teacher · ' : '';
  const lifted = isLifted(b);
  const liftedWhere = b.source === 'local_lift' ? 'local model' : 'this server';
  const raised = b.source === RAISED_FOR_RUN;
  const toolsRaised = b.toolSource === RAISED_FOR_RUN;

  let steps;
  if (b.roundLimit && !lifted) {
    steps = {
      text: `${who}Step ${num(b.round)} of ${num(b.roundLimit)}${raised ? ' · raised for this run' : ''}`,
      value: Math.min(b.round, b.roundLimit),
      max: b.roundLimit,
      tone: toneFor(b.round, b.roundLimit),
    };
  } else if (b.roundLimit) {
    steps = { text: `${who}Step ${num(b.round)} · limit lifted (${liftedWhere})`, value: b.round, max: null, tone: '' };
  } else {
    steps = { text: `${who}Step ${num(b.round)}`, value: b.round, max: null, tone: '' };
  }

  let tools = null;
  if (b.toolCalls !== null) {
    if (b.toolLimit) {
      tools = {
        text: `Tool calls ${num(b.toolCalls)} of ${num(b.toolLimit)}${toolsRaised ? ' · raised for this run' : ''}`,
        value: Math.min(b.toolCalls, b.toolLimit),
        max: b.toolLimit,
        tone: toneFor(b.toolCalls, b.toolLimit),
      };
    } else if (b.toolLimit === null) {
      tools = {
        text: `Tool calls ${num(b.toolCalls)} · ${toolsRaised ? 'limit removed for this run' : 'no limit'}`,
        value: b.toolCalls, max: null, tone: '',
      };
    } else {
      tools = { text: `Tool calls ${num(b.toolCalls)}`, value: b.toolCalls, max: null, tone: '' };
    }
  }

  // What happens at each limit, said before it happens: at the start of the
  // run (step 1), and again once either limit is close.
  const start = b.round <= 1;
  const clauses = [];
  // `P7-12`. A limit the agent raised for itself is said for as long as it
  // holds: the run was given more than Settings says, and nothing was saved.
  if (raised && b.roundLimit) clauses.push(`Raised to ${num(b.roundLimit)} steps for this run — nothing saved`);
  if (toolsRaised) {
    clauses.push(b.toolLimit ? `Tool-call limit raised to ${num(b.toolLimit)} for this run — nothing saved`
      : 'Tool-call limit removed for this run — nothing saved');
  }
  if (b.roundLimit && !lifted) {
    if (steps.tone === 'at') clauses.push(`Last step — if it needs more, it stops here${andContinue}`);
    else if (steps.tone === 'near' || start) clauses.push(`Stops after step ${num(b.roundLimit)}${andContinue}`);
  } else if (b.roundLimit && start) {
    clauses.push(`Step limit lifted to ${num(b.roundLimit)} on this ${liftedWhere}`);
  }
  if (tools && b.toolLimit) {
    const left = b.toolLimit - b.toolCalls;
    if (tools.tone === 'at') clauses.push('Tool-call limit reached — one more call stops it');
    else if (tools.tone === 'near') clauses.push(`${num(left)} tool call${left === 1 ? '' : 's'} left, then it stops`);
    else if (start) clauses.push(`Stops outright after ${num(b.toolLimit)} tool calls`);
  } else if (tools && b.toolLimit === null && start) {
    clauses.push('No tool-call limit');
  }
  let note = {
    text: clauses.join(' · '),
    tone: [steps.tone, tools ? tools.tone : ''].includes('at') ? 'at'
      : ([steps.tone, tools ? tools.tone : ''].includes('near') ? 'near' : ''),
  };
  if (state.stop) {
    note = state.stop.kind === 'rounds'
      ? { text: state.stop.limit ? `Stopped at the ${num(state.stop.limit)}-step limit` : 'Stopped at the step limit', tone: 'at' }
      : { text: state.stop.limit ? `Stopped at the ${num(state.stop.limit)}-tool-call limit` : 'Stopped at the tool-call limit', tone: 'at' };
  }

  return {
    steps, tools, note,
    title: limitsTitle(b, 'This run', andContinue),
  };
}

// ── the rule, in words (`P4-23`, `P7-10`) ──────────────────────────────────

/** The step rule for limits `b` (`limitsFrom`'s shape). `subject` names who
 *  stops: *This run* under the spinner, *Each message in Agent mode* before
 *  there is a run. */
function stepRuleText(b, subject, andContinue = ' and offers Continue') {
  if (b.roundLimit && b.source === RAISED_FOR_RUN) {
    return `The assistant raised this run's step limit from ${num(b.configured)} to ${num(b.roundLimit)}, `
      + `for this run only; nothing was saved. ${subject} stops after step ${num(b.roundLimit)}${andContinue}.`;
  }
  if (b.roundLimit && b.source === 'configured') {
    return `${subject} stops after step ${num(b.roundLimit)}${andContinue}.`;
  }
  if (b.roundLimit && b.source === 'local_lift') {
    return `On a local model the ${num(b.configured)}-step limit is lifted to ${num(b.roundLimit)}; `
      + 'saving "Max steps per message" keeps it.';
  }
  if (b.roundLimit) return `This server lifts the ${num(b.configured)}-step limit to ${num(b.roundLimit)}.`;
  return 'The step limit for this run was not reported.';
}

function toolRuleText(b) {
  if (b.toolSource === RAISED_FOR_RUN) {
    return b.toolLimit
      ? `The assistant raised its tool-call limit to ${num(b.toolLimit)} for this run only; nothing was saved. `
        + `It stops outright after ${num(b.toolLimit)} tool calls.`
      : 'The assistant removed its tool-call limit for this run only; nothing was saved.';
  }
  if (b.toolLimit) return `It stops outright after ${num(b.toolLimit)} tool calls.`;
  if (b.toolLimit === null) return 'There is no tool-call limit.';
  return 'The tool-call limit for this run was not reported.';
}

/** The whole rule, and where it is set: the meter's hover text, and the
 *  composer's before a run. */
function limitsTitle(b, subject, andContinue) {
  return `${stepRuleText(b, subject, andContinue)} ${toolRuleText(b)} Both are set in ${SETTINGS_PATH}.`;
}

// ── before the run (`P7-10`) ──────────────────────────────────────────────

/**
 * What the composer says beside the mode toggle, from `GET /api/chat/agent-limits`.
 * `null` when the answer has no step limit in it — the chip then says nothing
 * rather than guessing (`Law 10`).
 *
 *   text   the short form, e.g. *Up to 20 steps · 10 tool calls*
 *   title  the whole rule and where it is set, in the meter's own sentences
 *   source the step limit's `round_limit_source`
 */
export function limitsPreview(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const b = limitsFrom(payload);
  if (!b.roundLimit) return null;
  const lifted = isLifted(b);
  const liftedWhere = b.source === 'local_lift' ? 'local model' : 'this server';
  const steps = lifted ? `Step limit lifted (${liftedWhere})` : `Up to ${num(b.roundLimit)} steps`;
  const tools = b.toolLimit ? `${num(b.toolLimit)} tool call${b.toolLimit === 1 ? '' : 's'}` : '';
  const raise = raiseRules(b, payload);
  return {
    text: tools ? `${steps} · ${tools}` : steps,
    title: `${stepRuleText(b, 'Each message in Agent mode')}${raise.steps} `
      + `${toolRuleText(b)}${raise.tools} Both are set in ${SETTINGS_PATH}.`,
    source: b.source,
  };
}

/**
 * `P7-12`. Who may raise the limits for one run, from the route's
 * `round_limit_raise` / `tool_call_limit_raise` (`without_asking` ·
 * `asks_you`). Said before the run because it is part of the answer to *how
 * far can it run unattended*: a step limit nobody typed, the assistant may
 * lengthen for one run on its own, up to what a person could type. Each part
 * is `''` when the route did not say, or when a lifted limit leaves nothing to
 * raise; otherwise it starts with a space, to follow the rule it qualifies.
 */
function raiseRules(b, payload) {
  const out = { steps: '', tools: '' };
  if (b.source === 'configured') {
    const ceiling = positiveInt(payload.round_limit_raise_ceiling);
    if (payload.round_limit_raise === 'without_asking' && ceiling) {
      out.steps = ` The assistant may raise it for one run, up to ${num(ceiling)} steps, without `
        + 'asking; it is stopped sooner if a few rounds in a row bring nothing new.';
    } else if (payload.round_limit_raise === 'asks_you') {
      out.steps = ' The assistant has to ask you before it raises a step limit you set.';
    }
  }
  if (b.toolLimit && payload.tool_call_limit_raise === 'asks_you') {
    out.tools = ' It has to ask you before it raises the tool-call limit.';
  }
  return out;
}

/** Draw `payload` into the composer's hint node (`#agent-limits-hint`). Text
 *  only: the words are this module's, the numbers came off the wire. Hidden
 *  when there is nothing true to say. Returns the preview drawn, or `null`. */
export function renderLimitsHint(node, payload) {
  if (!node) return null;
  const view = limitsPreview(payload);
  node.textContent = view ? view.text : '';
  node.title = view ? view.title : '';
  node.hidden = !view;
  if (view) node.dataset.source = view.source;
  else delete node.dataset.source;
  return view;
}

// ── DOM ───────────────────────────────────────────────────────────────────

function el(doc, tag, className) {
  const n = doc.createElement(tag);
  n.className = className;
  return n;
}

function bar(doc, kind, label) {
  const track = el(doc, 'span', 'agent-meter-bar');
  track.dataset.kind = kind;
  track.setAttribute('role', 'progressbar');
  track.setAttribute('aria-label', label);
  track.setAttribute('aria-valuemin', '0');
  track.appendChild(el(doc, 'span', 'agent-meter-fill'));
  return track;
}

/** The meter's node, empty. Built once per turn and moved between spinners. */
export function buildMeterNode(doc) {
  const root = el(doc, 'div', 'agent-meter');
  root.appendChild(el(doc, 'div', 'agent-meter-prep'));
  const budget = el(doc, 'div', 'agent-meter-budget');
  budget.appendChild(el(doc, 'span', 'agent-meter-steps'));
  budget.appendChild(bar(doc, 'steps', 'Steps used'));
  budget.appendChild(el(doc, 'span', 'agent-meter-tools'));
  budget.appendChild(bar(doc, 'tools', 'Tool calls used'));
  root.appendChild(budget);
  root.appendChild(el(doc, 'div', 'agent-meter-note'));
  return root;
}

function part(node, cls) {
  return node.querySelector('.' + cls);
}

function paintBar(track, seg) {
  const fill = track && part(track, 'agent-meter-fill');
  if (!track || !fill) return;
  const show = !!(seg && seg.max);
  track.hidden = !show;
  if (!show) return;
  const frac = Math.max(0, Math.min(1, seg.value / seg.max));
  fill.style.width = `${Math.round(frac * 1000) / 10}%`;
  track.setAttribute('aria-valuemax', String(seg.max));
  track.setAttribute('aria-valuenow', String(seg.value));
  if (seg.tone) track.dataset.tone = seg.tone; else delete track.dataset.tone;
}

function paintText(n, text, tone) {
  if (!n) return;
  n.textContent = text || '';
  n.hidden = !text;
  if (tone) n.dataset.tone = tone; else delete n.dataset.tone;
}

/** Draw `state` into a node from `buildMeterNode`. Text only, never markup: the
 *  words are this module's, but the numbers come off the wire. `opts` is
 *  `budgetView`'s. */
export function renderMeterNode(node, state, nowMs = Date.now(), opts = {}) {
  if (!node) return node;
  const prepText = prepLineText(state, nowMs);
  const prep = part(node, 'agent-meter-prep');
  paintText(prep, prepText, '');
  if (prep) {
    prep.title = prepText
      ? 'Times were measured on the server as each step finished. A figure with ~ '
        + 'is still counting in your browser.'
      : '';
  }

  const view = budgetView(state, opts);
  const budget = part(node, 'agent-meter-budget');
  if (budget) budget.hidden = !view;
  if (view) {
    budget.title = view.title;
    paintText(part(node, 'agent-meter-steps'), view.steps.text, view.steps.tone);
    // `Array.from`: a browser answers with a NodeList, which has no `find`.
    const bars = Array.from(node.querySelectorAll('.agent-meter-bar'));
    paintBar(bars.find((b) => b.dataset.kind === 'steps'), view.steps);
    paintText(part(node, 'agent-meter-tools'), view.tools ? view.tools.text : '', view.tools ? view.tools.tone : '');
    paintBar(bars.find((b) => b.dataset.kind === 'tools'), view.tools);
  }
  const note = view ? view.note : { text: '', tone: '' };
  paintText(part(node, 'agent-meter-note'), note.text, note.tone);
  node.hidden = !meterHasContent(state);
  return node;
}

/**
 * The per-turn meter: its state, its one node, and the `~` counter's ticker.
 *
 * `opts.document`, `opts.now`, `opts.setInterval` and `opts.clearInterval` exist
 * so a test can drive it without a browser; the defaults are the page's own.
 * The ticker runs only while a prep step is running and the node is on the
 * page, and stops itself otherwise, so a turn that ends mid-prep leaves nothing
 * behind to clean up.
 *
 * `opts.offersContinue: false` is for a surface with no Continue at the step
 * limit — a compare pane (`B916`) — so the meter's words do not promise one.
 */
export function createAgentMeter(opts = {}) {
  const doc = opts.document || (typeof document !== 'undefined' ? document : null);
  const now = typeof opts.now === 'function' ? opts.now : () => Date.now();
  const every = opts.setInterval || ((fn, ms) => setInterval(fn, ms));
  const stopEvery = opts.clearInterval || ((id) => clearInterval(id));
  const words = { offersContinue: opts.offersContinue !== false };
  let state = createMeterState();
  let node = null;
  let ticker = null;

  const ensureNode = () => {
    if (!node && doc) node = buildMeterNode(doc);
    return node;
  };
  const paint = () => {
    if (node) renderMeterNode(node, state, now(), words);
  };
  const stopTicker = () => {
    if (ticker !== null) {
      stopEvery(ticker);
      ticker = null;
    }
  };
  const tick = () => {
    if (!node || !node.isConnected || !prepIsRunning(state)) {
      stopTicker();
      return;
    }
    paint();
  };
  const startTicker = () => {
    if (ticker === null && prepIsRunning(state)) ticker = every(tick, 1000);
  };

  return {
    get state() { return state; },
    get node() { return node; },
    /** Apply one stream event. True when it changed anything. */
    update(event) {
      const next = reduceMeter(state, event, now());
      if (next === state) return false;
      state = next;
      if (meterHasContent(state)) {
        ensureNode();
        paint();
      }
      if (!prepIsRunning(state)) stopTicker();
      return true;
    },
    /** The spinner label the prep state implies, or `''`. */
    spinnerLabel() { return prepSpinnerLabel(state); },
    /** Put the meter under `host` (a `Spinner`). A spinner that cannot hold a
     *  detail line, or a meter with nothing to say, attaches nothing. */
    attachTo(host) {
      if (!host || typeof host.attachDetail !== 'function' || !host.element) return false;
      if (!meterHasContent(state) || !ensureNode()) return false;
      paint();
      host.attachDetail(node);
      startTicker();
      return true;
    },
    /** Redraw now — the `~` counter, after a pause the ticker did not see. */
    refresh() { paint(); },
    /**
     * `B916`. Leave the meter at the end of `container` as a line of its own,
     * under no spinner, so no spinner takes it away. For a stream that stops
     * at a limit with nothing after it to wait for — a compare pane, which has
     * no Continue box to say why — the meter, ending on the stop, is the last
     * word. Nothing to say, nothing placed.
     */
    placeIn(container) {
      if (!container || typeof container.appendChild !== 'function') return false;
      if (!meterHasContent(state) || !ensureNode()) return false;
      // The spinner it last hung under keeps a stale reference and removes the
      // node only while it is still the host (`Spinner.attachDetail`).
      node._spinnerHost = null;
      paint();
      container.appendChild(node);
      stopTicker();
      return true;
    },
    dispose() { stopTicker(); },
  };
}

/**
 * The one call a stream handler makes for a meter event. `P4-08` / `P4-23`.
 *
 * Applies the event, and when there is a spinner on screen (`host`) points its
 * label at the running prep step and hangs the meter under it. `host` is `null`
 * for a background stream: the state still advances, nothing is drawn.
 *
 * `chat.js` calls this from its live stream handler. `P4-24` — a stream resumed
 * after navigating away — calls it from `resumeStream` with that path's own
 * spinner, which is the whole of what makes the two render the meter alike.
 */
export function presentMeterEvent(meter, event, host) {
  if (!meter || !event) return false;
  const changed = meter.update(event);
  if (host && host.element) {
    if (event.type === 'agent_prep') {
      const label = meter.spinnerLabel();
      if (label && typeof host.updateMessage === 'function') host.updateMessage(label);
    }
    meter.attachTo(host);
  }
  return changed;
}

export default {
  PREP_PHASES, WAITING_FOR_MODEL, METER_EVENT_TYPES,
  formatPrepSeconds, prepPhaseLabel, prepBreakdownRows,
  createMeterState, reduceMeter, meterHasContent, prepIsRunning,
  prepSpinnerLabel, prepLineVisible, prepLineText, budgetView,
  buildMeterNode, renderMeterNode, createAgentMeter, presentMeterEvent,
  FIRST_TOKEN_WAIT_FROM_MS, endsFirstTokenWait, firstTokenWaitText,
  limitsPreview, renderLimitsHint,
};
