// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/planWindow.js

/**
 * The docked plan window (P6-11) and the step model behind it (P6-13).
 *
 * Four prompt strings have been telling the model that "the user's docked plan
 * window updates live" — `src/agent_loop.py:759`, `:3402`, `src/tool_index.py:109`
 * and `src/tool_schemas.py:545`. Nothing ever drew it. `chat.js` received the
 * `plan_update` SSE event, wrote the markdown to `localStorage` under a comment
 * that claimed it refreshed that window, and rendered nothing. This module is
 * the window those strings describe.
 *
 * ── Ownership ───────────────────────────────────────────────────────────────
 * This module owns the active plan *string* as well as the window, so there is
 * exactly one write path: anything that stores a plan repaints the window,
 * because storing and repainting are the same call. `chat.js` keeps its
 * `_getStoredPlan` / `_setStoredPlan` / `_clearStoredPlan` / `_extractPlanText`
 * names and delegates here — no second store, no second extractor (Law 7/14).
 *
 * ── The step model, and why the ids are derived (P6-13) ─────────────────────
 * `update_plan`'s schema (`src/tool_schemas.py:545`) tells the model to send the
 * COMPLETE markdown checklist every time, never a diff, and that file is not
 * ours to change. Silently teaching the model a different wire format would
 * make the prompt lie a second time. So ids are **derived from the markdown,
 * deterministically**: id = FNV-1a of the step's normalised text, plus an
 * occurrence ordinal when two steps read identically. Ticking a box does not
 * change a step's text, so the id survives every `update_plan` the model is
 * actually instructed to send, and per-step status / bound tool / effect /
 * elapsed / result attach to something stable instead of to a line number.
 *
 * A step whose *text* is edited gets a new id; its metadata is carried over by
 * position among the steps that failed to match, which is the only reading of a
 * reworded step that is ever right.
 */

import Storage from './storage.js';

/** The active plan markdown. Same key `chat.js` has always used. */
export const PLAN_STORAGE_KEY = 'pantheon-active-plan';

/**
 * Per-step runtime metadata (bound tool, effect, elapsed, result) + the window's
 * fold state. Deliberately a SEPARATE key from the plan: the plan string is posted
 * to the server as `approved_plan` and is read by `_getStoredPlan()`, so its
 * shape is a contract. This key holds only things derived from live events —
 * never a second copy of the plan itself.
 */
const PLAN_META_KEY = 'pantheon-plan-window';

const RESULT_MAX = 90;   // chars of tool output kept as a step's result line
const CMD_MAX = 64;      // chars of the bound tool's command shown as its target
const STALE_MS = 24 * 60 * 60 * 1000;  // a plan older than a day is not "active"

/**
 * One grammar for what counts as a checklist line, used by both the extractor
 * and the parser. Identical to the detector `chat.js` has always used
 * (`/^\s*(?:[-*]|\d+\.)\s+\[[ x-]\]\s+/i`) — same bullets, same markers — with
 * capture groups added so it can parse as well as detect.
 */
const STEP_LINE_RE = /^\s*(?:[-*]|\d+\.)\s+\[([ xX-])\]\s+(.*)$/;

const PLAN_HEADING_RE = /^\s{0,3}#{1,4}\s+.*plan/i;
const PLAN_LABEL_RE = /^\s*(?:plan|proposed plan)\s*:?$/i;

// ── Step model (P6-13) ──────────────────────────────────────────────────────

/** True when `line` is a plan checklist item. */
export function isPlanStepLine(line) {
  return STEP_LINE_RE.test(String(line == null ? '' : line));
}

/** Normalised step text — the thing the id is derived from. */
function normaliseStepText(text) {
  return String(text == null ? '' : text)
    .toLowerCase()
    .replace(/[`*_~]/g, '')       // markdown emphasis is presentation, not identity
    .replace(/\s+/g, ' ')
    .trim();
}

/** FNV-1a, 32-bit, base36. Deterministic across reloads and browsers. */
function hash32(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(36);
}

/**
 * Stable id for a step. `dup` is the 0-based occurrence index among steps whose
 * normalised text is identical, so a plan with two "Run the tests" lines still
 * gives each one its own id.
 */
export function stepIdFor(text, dup) {
  const base = 'p' + hash32(normaliseStepText(text));
  return dup ? `${base}.${dup}` : base;
}

/**
 * Parse plan markdown into an ordered step model.
 * Returns `[{ id, ordinal, text, done }]`. Lines that are not checklist items
 * are ignored — the plan window shows steps, and the prose stays in the chat.
 */
export function parsePlan(markdown) {
  const lines = String(markdown == null ? '' : markdown).split('\n');
  const seen = Object.create(null);
  const steps = [];
  for (const line of lines) {
    const m = STEP_LINE_RE.exec(line);
    if (!m) continue;
    const text = String(m[2] || '').trim();
    if (!text) continue;
    const key = normaliseStepText(text);
    const dup = seen[key] || 0;
    seen[key] = dup + 1;
    steps.push({
      id: stepIdFor(text, dup),
      ordinal: steps.length,
      text,
      done: m[1] === 'x' || m[1] === 'X',
    });
  }
  return steps;
}

/**
 * Carry per-step runtime metadata from the previous parse onto the new one.
 * Matched by id first (the normal case: the model ticked a box). Steps that
 * matched nothing are then paired by position against the previously-unmatched
 * steps — that is the reworded-step case, and position is the only signal left.
 */
/**
 * Does the incoming plan overlap the one on screen at all — by stable id, or by
 * an ordinal that `reconcileMeta` would carry metadata across? If not, it is a
 * different plan rather than a revision of this one.
 */
function sharesAnyStep(prevSteps, nextSteps) {
  if (!prevSteps.length || !nextSteps.length) return false;
  const prevIds = new Set(prevSteps.map((s) => s.id));
  if (nextSteps.some((s) => prevIds.has(s.id))) return true;
  // An edited step keeps its ordinal, which is how reconcileMeta pairs them.
  // Treat that as a revision too, or editing every line of a plan would silently
  // revoke its approval mid-run.
  const prevText = new Set(prevSteps.map((s) => String(s.text || '').toLowerCase().trim()));
  return nextSteps.some((s) => prevText.has(String(s.text || '').toLowerCase().trim()));
}

function reconcileMeta(prevSteps, nextSteps, meta) {
  const prevById = new Map(prevSteps.map((s) => [s.id, s]));
  const orphanNext = [];
  const claimed = new Set();

  for (const step of nextSteps) {
    if (prevById.has(step.id)) {
      claimed.add(step.id);
    } else {
      orphanNext.push(step);
    }
  }
  const orphanPrev = prevSteps.filter((s) => !claimed.has(s.id));
  for (const step of orphanNext) {
    const partner = orphanPrev.find((p) => p.ordinal === step.ordinal);
    if (!partner) continue;
    const carried = meta.steps[partner.id];
    if (carried && !meta.steps[step.id]) meta.steps[step.id] = carried;
  }

  // Drop metadata for steps that are no longer in the plan, so the blob stays
  // the size of the plan rather than the size of every plan ever written.
  const live = new Set(nextSteps.map((s) => s.id));
  for (const id of Object.keys(meta.steps)) {
    if (!live.has(id)) delete meta.steps[id];
  }
}

// ── Persisted plan text ─────────────────────────────────────────────────────

/**
 * Pull the plan out of a model turn: everything from the first checklist line,
 * else everything from a "plan" heading, else the whole (think-stripped) text.
 * Moved here from `chat.js` unchanged so the extractor and the parser agree on
 * what a step line is.
 */
export function extractPlanText(text) {
  // `text || ''`, not `text == null`: kept byte-identical to the original so a
  // falsy non-null argument still extracts to '' exactly as it always did.
  const raw = String(text || '').trim();
  if (!raw) return '';
  const stripped = raw
    .replace(/<think[\s\S]*?<\/think>/gi, '')
    .replace(/<thought[\s\S]*?<\/thought>/gi, '')
    .trim();
  const lines = stripped.split('\n');
  const firstChecklist = lines.findIndex((line) => isPlanStepLine(line));
  if (firstChecklist >= 0) return lines.slice(firstChecklist).join('\n').trim();
  const firstPlanHeading = lines.findIndex(
    (line) => PLAN_HEADING_RE.test(line) || PLAN_LABEL_RE.test(line),
  );
  if (firstPlanHeading >= 0) return lines.slice(firstPlanHeading).join('\n').trim();
  return stripped;
}

/** The stored plan markdown, or '' — the exact contract `chat.js` relied on. */
export function getPlan() {
  try { return localStorage.getItem(PLAN_STORAGE_KEY) || ''; } catch (_) { return ''; }
}

// ── Metadata blob ───────────────────────────────────────────────────────────

function blankMeta() {
  return { v: 1, folded: false, approvedAt: 0, sessionId: '', updatedAt: 0, steps: {} };
}

function loadMeta() {
  const raw = Storage.getJSON(PLAN_META_KEY, null);
  const meta = blankMeta();
  if (raw && typeof raw === 'object') {
    meta.folded = !!raw.folded;
    meta.approvedAt = Number(raw.approvedAt) || 0;
    meta.sessionId = typeof raw.sessionId === 'string' ? raw.sessionId : '';
    meta.updatedAt = Number(raw.updatedAt) || 0;
    if (raw.steps && typeof raw.steps === 'object') {
      for (const [id, v] of Object.entries(raw.steps)) {
        if (v && typeof v === 'object') meta.steps[id] = v;
      }
    }
  }
  return meta;
}

function saveMeta() {
  Storage.setJSON(PLAN_META_KEY, _meta);
}

// ── Module state ────────────────────────────────────────────────────────────

let _meta = blankMeta();
let _steps = [];
let _planText = '';
let _executor = null;       // set by chat.js — the ONE execute path
let _sessionIdReader = null;
let _ticker = null;
let _activeStartedAt = 0;   // in-memory only: a reload does not fake a timer
let _wired = false;
let _els = null;
let _renderedSession = null; // what `render()` last resolved the session id to
let _renderedActive = -2;    // which step was last drawn as the active one

const ICON_CHEVRON =
  '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" ' +
  'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<polyline points="6 9 12 15 18 9"/></svg>';
const ICON_PLAN =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/>' +
  '<rect x="9" y="3" width="6" height="4" rx="1"/><path d="m9 13 1.5 1.5L14 11"/></svg>';

/**
 * Every id is looked up with a literal `getElementById` rather than through a
 * helper, on purpose: `.pantheon/check-wiring.py` only sees literals, so a
 * helper would hide this module's wiring from the drift metric that exists to
 * catch exactly this kind of half-built surface (Law 13).
 */
function collectEls() {
  const root = document.getElementById('plan-window');
  if (!root) return null;
  const els = {
    root,
    fold: document.getElementById('plan-window-fold'),
    chevron: document.getElementById('plan-window-chevron'),
    icon: document.getElementById('plan-window-icon'),
    count: document.getElementById('plan-window-count'),
    status: document.getElementById('plan-window-status'),
    origin: document.getElementById('plan-window-origin'),
    fill: document.getElementById('plan-window-fill'),
    body: document.getElementById('plan-window-body'),
    list: document.getElementById('plan-window-steps'),
    execute: document.getElementById('plan-window-execute'),
    clear: document.getElementById('plan-window-clear'),
    hint: document.getElementById('plan-window-hint'),
  };
  // A partial window is a broken window — draw nothing rather than half of it.
  return Object.values(els).every(Boolean) ? els : null;
}

// ── Derived state ───────────────────────────────────────────────────────────

function activeIndex() {
  return _steps.findIndex((s) => !s.done);
}

function isPlanModeOn() {
  try { return !!Storage.loadToggleState().plan_mode; } catch (_) { return false; }
}

function currentSessionId() {
  try { return (_sessionIdReader && _sessionIdReader()) || ''; } catch (_) { return ''; }
}

/** `draft` → never executed · `executing` → approved, steps outstanding · `done`. */
function planState() {
  if (!_steps.length) return 'draft';
  if (_steps.every((s) => s.done)) return 'done';
  return _meta.approvedAt ? 'executing' : 'draft';
}

function formatElapsed(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return '';
  if (n < 10000) return (n / 1000).toFixed(1) + 's';
  if (n < 60000) return Math.round(n / 1000) + 's';
  const mins = Math.floor(n / 60000);
  const secs = Math.round((n % 60000) / 1000);
  return mins + 'm ' + String(secs).padStart(2, '0') + 's';
}

function truncate(text, max) {
  const s = String(text == null ? '' : text).replace(/\s+/g, ' ').trim();
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}

// ── Rendering ───────────────────────────────────────────────────────────────

function chip(cls, text, title) {
  const span = document.createElement('span');
  span.className = 'plan-step-chip' + (cls ? ' ' + cls : '');
  span.textContent = text;
  if (title) span.title = title;
  return span;
}

function renderStep(step, index, active) {
  const meta = _meta.steps[step.id] || {};
  const li = document.createElement('li');
  li.className = 'plan-step task-item' + (step.done ? ' task-done' : '');
  if (!step.done && index === active) li.classList.add('plan-step-now');
  li.dataset.stepId = step.id;

  const box = document.createElement('span');
  box.className = 'task-check';
  // Name the state rather than hiding the box. The two surfaces share one row
  // system and must share its contract: chatRenderer.js gives the todo card's
  // box role="img" + a label, and this window — the wave's headline feature —
  // was announcing a completed step as nothing at all, its only "done" signal
  // being a fill and a strikethrough, both purely visual. The in-progress case
  // stays hidden because its visible chip already says the word, and labelling
  // both would announce it twice.
  if (!step.done && index === active) {
    box.setAttribute('aria-hidden', 'true');
  } else {
    box.setAttribute('role', 'img');
    box.setAttribute('aria-label', step.done ? 'done' : 'to do');
  }
  li.appendChild(box);

  const main = document.createElement('span');
  main.className = 'plan-step-main';

  const text = document.createElement('span');
  text.className = 'task-text';
  text.textContent = step.text;
  main.appendChild(text);

  const metaRow = document.createElement('span');
  metaRow.className = 'plan-step-meta';

  // The consequence leads the row. Which tool ran and how long it took are
  // details; what it could do to the user is the only thing here that would
  // change what they do next, so it is read first and drawn heaviest.
  if (meta.effect) {
    const c = chip('plan-step-effect', meta.effect, 'What this step can do');
    if (meta.effectBand) c.dataset.effectBand = meta.effectBand;
    metaRow.appendChild(c);
  }
  if (meta.tool) {
    metaRow.appendChild(chip('plan-step-tool', meta.tool, 'Ran while this step was next'));
  }
  if (meta.cmd) {
    metaRow.appendChild(chip('plan-step-target', truncate(meta.cmd, CMD_MAX), meta.cmd));
  }
  if (meta.result) {
    metaRow.appendChild(
      chip(meta.ok === false ? 'plan-step-bad' : 'plan-step-ok',
        truncate(meta.result, RESULT_MAX), meta.result),
    );
  }
  const showLive = !step.done && index === active && _activeStartedAt > 0;
  const elapsed = showLive ? Date.now() - _activeStartedAt : meta.elapsedMs;
  if (elapsed) {
    const c = chip('plan-step-elapsed', formatElapsed(elapsed),
      showLive ? 'Running — time on this step' : 'Time spent on this step');
    if (showLive) c.dataset.planLive = '1';
    metaRow.appendChild(c);
  }
  if (metaRow.childNodes.length) main.appendChild(metaRow);

  li.appendChild(main);
  return li;
}

const STATE_TEXT = {
  draft: 'Draft',
  executing: 'Executing',
  done: 'Complete',
};
const STATE_HINT = {
  draft: 'Review the steps, then Execute to run them in order.',
  executing: 'The agent ticks each step off here as it finishes.',
  done: 'Every step is done. Clear to start a new plan.',
};

function render() {
  if (!_els) return;
  const total = _steps.length;
  if (!total) {
    _els.root.hidden = true;
    stopTicker();
    return;
  }
  _els.root.hidden = false;

  const done = _steps.filter((s) => s.done).length;
  const active = activeIndex();
  const state = planState();

  _els.count.textContent = `${done} of ${total} done`;
  _els.status.textContent = STATE_TEXT[state];
  _els.status.dataset.planState = state;
  _els.hint.textContent = STATE_HINT[state];
  _els.fill.style.width = total ? Math.round((done / total) * 100) + '%' : '0%';

  const sid = currentSessionId();
  const foreign = !!(_meta.sessionId && sid && _meta.sessionId !== sid);
  _els.origin.hidden = !foreign;
  if (foreign) _els.origin.title = 'This plan was approved in a different chat.';

  _els.execute.textContent = '';
  const play = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  play.setAttribute('width', '12');
  play.setAttribute('height', '12');
  play.setAttribute('viewBox', '0 0 24 24');
  play.setAttribute('fill', 'currentColor');
  play.setAttribute('aria-hidden', 'true');
  const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
  poly.setAttribute('points', '7 4 20 12 7 20 7 4');
  play.appendChild(poly);
  _els.execute.appendChild(play);
  _els.execute.appendChild(
    document.createTextNode(state === 'executing' ? 'Run remaining steps' : 'Execute plan'),
  );
  _els.execute.hidden = state === 'done';

  // Rebuilding the rows throws the list's scroll position away; a plan longer
  // than the box is exactly when that matters, and tool events repaint often.
  const scrollTop = _els.list.scrollTop;
  const list = document.createDocumentFragment();
  _steps.forEach((s, i) => list.appendChild(renderStep(s, i, active)));
  _els.list.textContent = '';
  _els.list.appendChild(list);
  _els.list.scrollTop = scrollTop;

  // Follow the agent down a long plan — but only when the step actually moved,
  // so a user reading further up is never yanked back.
  if (active >= 0 && active !== _renderedActive) {
    const row = _els.list.children[active];
    if (row && typeof row.scrollIntoView === 'function') {
      row.scrollIntoView({ block: 'nearest' });
    }
  }
  _renderedActive = active;
  _renderedSession = sid;

  applyFold();
  if (state === 'executing' && active >= 0 && _activeStartedAt) startTicker();
  else stopTicker();
}

function applyFold() {
  if (!_els) return;
  const folded = !!_meta.folded;
  _els.root.classList.toggle('plan-window-folded', folded);
  _els.body.hidden = folded;
  _els.fold.setAttribute('aria-expanded', String(!folded));
  _els.fold.title = folded ? 'Show the plan steps' : 'Hide the plan steps';
}

// ── Live elapsed ticker ─────────────────────────────────────────────────────

function startTicker() {
  if (_ticker) return;
  _ticker = setInterval(() => {
    if (!_els || _els.root.hidden || !_activeStartedAt) return stopTicker();
    const node = _els.list.querySelector('[data-plan-live]');
    if (node) node.textContent = formatElapsed(Date.now() - _activeStartedAt);
  }, 1000);
}

function stopTicker() {
  if (!_ticker) return;
  clearInterval(_ticker);
  _ticker = null;
}

// ── Public plan writes ──────────────────────────────────────────────────────

/**
 * Store a plan and repaint the window. Storing and repainting are one call on
 * purpose — that is the bug this module exists to close.
 * Keeps `chat.js`'s original contract: an empty extraction is a no-op, never a
 * clear, so a stray turn cannot wipe an approved plan.
 */
export function setPlan(plan) {
  const text = extractPlanText(plan);
  if (!text) return;
  try { localStorage.setItem(PLAN_STORAGE_KEY, text); } catch (_) {}
  adoptPlanText(text);
}

function adoptPlanText(text) {
  const prevSteps = _steps;
  const prevActive = activeIndex();
  _planText = text;
  _steps = parsePlan(text);

  // A genuinely NEW plan is not an approved one. `reconcileMeta` carries
  // per-step metadata across a revision, which is right — but the approval
  // itself is not per-step, and leaving it set meant that approving one plan
  // approved every plan that browser ever saw afterwards: a brand-new
  // checklist rendered as "Executing", and the next unrelated tool call bound
  // straight to its step 1. A revision shares steps with what came before; a
  // new plan does not, and that is the test.
  const isNewPlan = prevSteps.length && !sharesAnyStep(prevSteps, _steps);
  if (isNewPlan) {
    _meta.approvedAt = 0;
    _meta.sessionId = '';
    _activeStartedAt = 0;
    // And the per-step history goes too. `reconcileMeta` pairs orphan steps by
    // ORDINAL, which is exactly right when a step was edited and exactly wrong
    // here: without this, the previous plan's step 1 hands its bound tool,
    // result and elapsed time to the new plan's step 1 purely because both are
    // first. Verified — the new plan rendered "write_file / Written:
    // /etc/filter.conf" against a step that had never run.
    _meta.steps = {};
  }

  // A new plan reconciles against nothing, which is the point: no carry-over.
  reconcileMeta(isNewPlan ? [] : prevSteps, _steps, _meta);

  // Freeze elapsed on any step that just flipped to done, then hand the clock
  // to whatever step is next.
  const nextActive = activeIndex();
  if (prevActive >= 0 && prevActive !== nextActive && _activeStartedAt) {
    const finished = prevSteps[prevActive];
    if (finished) {
      const rec = _meta.steps[finished.id] || (_meta.steps[finished.id] = {});
      if (!rec.elapsedMs) rec.elapsedMs = Date.now() - _activeStartedAt;
    }
    _activeStartedAt = nextActive >= 0 ? Date.now() : 0;
  }
  _meta.updatedAt = Date.now();
  saveMeta();
  render();
}

/** Forget the plan and take the window down. */
export function clearPlan() {
  try { localStorage.removeItem(PLAN_STORAGE_KEY); } catch (_) {}
  _planText = '';
  _steps = [];
  _activeStartedAt = 0;
  _renderedActive = -2;
  _meta = blankMeta();
  Storage.remove(PLAN_META_KEY);
  render();
}

/** The user pressed Execute (in the window or on the inline plan actions). */
export function markApproved() {
  _meta.approvedAt = Date.now();
  _meta.sessionId = currentSessionId();
  if (!_activeStartedAt && activeIndex() >= 0) _activeStartedAt = Date.now();
  saveMeta();
  render();
}

// ── Tool binding (the "bound tool / effect / elapsed / result" half of P6-11) ─

/**
 * Bind a tool to a step only when all four are true, because attributing an
 * unrelated tool call to a stale plan would make the window lie the way the
 * prompt did:
 *   · there is a step still outstanding;
 *   · the user actually pressed Execute — `approved_plan` only reaches the
 *     backend through that path, so nothing is executing without it;
 *   · plan mode is off, i.e. the agent is executing rather than drafting;
 *   · the plan belongs to the chat we are looking at (the `P6-01` lesson —
 *     a global store plus a session switch is how work lands in the wrong chat).
 */
function bindingAllowed() {
  if (!_steps.length || activeIndex() < 0) return false;
  if (!_meta.approvedAt || isPlanModeOn()) return false;
  const sid = currentSessionId();
  return !(_meta.sessionId && sid && _meta.sessionId !== sid);
}

/**
 * Tools that are the agent talking to this window rather than doing the step's
 * work. They must never bind: `agent_loop.py` ORDERS `update_plan` after every
 * step, and it arrives wrapped in the same tool_start/tool_output pair as real
 * work — so without this filter each step's real tool is overwritten with
 * "update_plan", its result deleted, and the raw plan JSON rendered as the
 * target chip. The window would corrupt itself with the one tool it exists to
 * listen to.
 */
const BOOKKEEPING_TOOLS = new Set(['update_plan', 'ask_user']);

function isBookkeeping(ev) {
  return BOOKKEEPING_TOOLS.has(String((ev && ev.tool) || ''));
}

/**
 * Copy the event's effect onto a step record.
 *
 * `describe_effects()` (`src/tool_capabilities.py`) has already ranked the
 * effects and resolved the words; `effect_label` IS the dominant one. Neither
 * the ranking nor the phrasing is recomputed here — one ordering, one home.
 * The record keeps the phrase and not the value: nothing past this point has
 * any use for the identifier, and an event that arrives without a phrase leaves
 * the row blank rather than printing one the reader would have to decode.
 *
 * It goes in the same per-step record as the bound tool and the result, so a
 * new plan drops it through the paths that already exist — `adoptPlanText`
 * reconciling against nothing and clearing `_meta.steps`. A parallel map would
 * have needed its own line there, and eventually not got one.
 *
 * `clear` is for `tool_start`, where the record is being handed to a different
 * tool: a stale phrase describing the previous one is worse than none.
 */
function applyEffect(rec, ev, clear) {
  const label = String((ev && ev.effect_label) || '').trim();
  if (label) {
    rec.effect = truncate(label, 120);
    const band = String((ev && ev.effect_band) || '').trim();
    if (band) rec.effectBand = band;
    else delete rec.effectBand;
  } else if (clear) {
    delete rec.effect;
    delete rec.effectBand;
  }
}

/** A tool started. Attribute it to the step the agent is currently on. */
export function noteToolStart(ev) {
  if (isBookkeeping(ev)) return;
  if (!bindingAllowed()) return;
  const step = _steps[activeIndex()];
  if (!step) return;
  const rec = _meta.steps[step.id] || (_meta.steps[step.id] = {});
  rec.tool = String((ev && ev.tool) || '') || rec.tool;
  const cmd = String((ev && ev.command) || '');
  if (cmd) rec.cmd = truncate(cmd, 240);
  applyEffect(rec, ev, true);
  delete rec.result;
  delete rec.ok;
  if (!_activeStartedAt) _activeStartedAt = Date.now();
  saveMeta();
  render();
}

/** A tool finished. Record its verdict and first output line as the result. */
export function noteToolEnd(ev) {
  if (isBookkeeping(ev)) return;
  if (!bindingAllowed()) return;
  const step = _steps[activeIndex()];
  if (!step) return;
  const rec = _meta.steps[step.id] || (_meta.steps[step.id] = {});
  // Usually `tool_output` is the back half of a pair and carries the same
  // description as its `tool_start`, so a missing phrase must not wipe one the
  // start event already recorded.
  //
  // **But the pair is not guaranteed.** An approval gate and a policy block both
  // emit `tool_output` with no `tool_start` before it (`src/agent_loop.py`), so
  // a refused tool's output can land on a step that a *different* tool has
  // already claimed — and refutation reproduced the worst direction of that: a
  // step that overwrote a file reading "Reads your private data" in the routine
  // band because an unrelated blocked tool finished on the same step. A
  // differing tool name is a hand-over, and a hand-over replaces the record
  // rather than editing it.
  const evTool = String((ev && ev.tool) || '');
  const handover = !!(evTool && rec.tool && evTool !== rec.tool);
  if (handover) rec.tool = evTool;
  applyEffect(rec, ev, handover);
  const code = ev ? ev.exit_code : null;
  rec.ok = code === 0 || code == null;
  const out = String((ev && ev.output) || '').split('\n').find((l) => l.trim()) || '';
  rec.result = out ? truncate(out, 240) : (rec.ok ? 'ok' : 'failed');
  saveMeta();
  render();
}

// ── Wiring ──────────────────────────────────────────────────────────────────

/**
 * `chat.js` owns the send path, so it owns Execute. The window calls the same
 * function the inline plan actions call — one execute path, two entry points.
 */
export function onExecute(fn) {
  _executor = typeof fn === 'function' ? fn : null;
}

/** Lets the window say "from another chat" without importing sessions.js. */
export function onSessionId(fn) {
  _sessionIdReader = typeof fn === 'function' ? fn : null;
}

/**
 * Called by chat.js's existing `#chat-history` MutationObserver — the one hook
 * this app has that catches a session switch — so the "from another chat" tag
 * cannot go stale under one. That observer also fires on every bubble appended
 * during a stream, so this repaints only when the session actually moved;
 * everything else already repaints through its own event.
 */
export function refresh() {
  if (!_els || _els.root.hidden) return;
  if (currentSessionId() !== _renderedSession) render();
}

function wire() {
  if (_wired || !_els) return;
  _wired = true;

  _els.fold.addEventListener('click', () => {
    _meta.folded = !_meta.folded;
    saveMeta();
    applyFold();
  });
  // chat.js's `_executeStoredPlan` calls `markApproved()` itself, so the window
  // does nothing here except hand the plan to the one execute path there is.
  _els.execute.addEventListener('click', () => {
    if (!_planText.trim() || !_executor) return;
    _executor(_planText);
  });
  _els.clear.addEventListener('click', () => { clearPlan(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopTicker();
    else if (_els && !_els.root.hidden && planState() === 'executing' && _activeStartedAt) startTicker();
  });
}

/**
 * Draw whatever is already stored. The plan has always survived a reload; until
 * now nothing showed that it had.
 */
export function init() {
  _els = collectEls();
  if (!_els || !_els.root) return false;
  _meta = loadMeta();
  if (_meta.updatedAt && Date.now() - _meta.updatedAt > STALE_MS) {
    // Old run: keep the plan and its ticks, but do not claim it is executing.
    _meta.approvedAt = 0;
  }
  _els.chevron.innerHTML = ICON_CHEVRON;
  _els.icon.innerHTML = ICON_PLAN;
  wire();
  const stored = getPlan();
  _planText = stored;
  _steps = parsePlan(stored);
  // Seed the "which step was drawn last" marker so the first paint of a
  // restored plan never scrolls anything: following the agent is for when the
  // step moves, not for page load.
  _renderedActive = activeIndex();
  render();
  return true;
}

const planWindow = {
  PLAN_STORAGE_KEY,
  init,
  isPlanStepLine,
  parsePlan,
  stepIdFor,
  extractPlanText,
  getPlan,
  setPlan,
  clearPlan,
  markApproved,
  noteToolStart,
  noteToolEnd,
  onExecute,
  onSessionId,
  refresh,
};

export default planWindow;
