// SPDX-License-Identifier: AGPL-3.0-or-later
//
// apolloPaneModel.js — what the Apollo pane says, worked out from what
// `/api/apollo/*` answers, with no DOM and no fetch, so node can drive it.
//
// The pane (`apolloPane.js`) only draws what these return. Every sentence the
// server wrote (a task's title, its question, a line of what Apollo knows)
// stays text: these functions never build markup.

/** The four task states, in the order the Activity list groups ties. */
export const STATES = ['needs_you', 'working', 'waiting', 'done'];

/** A task's state as the dot beside it: its class suffix and its words. */
export function dotOf(state) {
  const words = { needs_you: 'Needs you', working: 'Working', waiting: 'Waiting', done: 'Done' }[state];
  return words ? { cls: `apo-dot-${state.replace('_', '-')}`, words } : { cls: 'apo-dot-waiting', words: String(state || '') };
}

/** The header's status line from `GET /state`: the server's words, and a tone
 *  the header colours (needs, working, idle). */
export function headline(state) {
  const s = state && state.status ? state.status : null;
  if (!s) return { words: 'Idle', tone: 'idle' };
  const tone = s.state === 'needs_you' ? 'needs' : s.state === 'working' ? 'working' : 'idle';
  return { words: s.words || 'Idle', tone };
}

/** The Activity list: newest first, `limit` rows, and how many more there are.
 *  A task that needs the person stays in the list too; the Needs you section
 *  above it is where they answer. */
export function activityRows(tasks, { limit = 6 } = {}) {
  const list = Array.isArray(tasks) ? tasks.slice() : [];
  list.sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')));
  const shown = list.slice(0, Math.max(0, limit));
  return { rows: shown, more: Math.max(0, list.length - shown.length) };
}

/** The tasks waiting on the person's answer, oldest question first. */
export function needsYou(tasks) {
  return (Array.isArray(tasks) ? tasks : [])
    .filter((t) => t && t.state === 'needs_you')
    .sort((a, b) => String(a.updated_at || '').localeCompare(String(b.updated_at || '')));
}

/** Outputs: what finished tasks came to, newest first. A task's outcome line
 *  is its output until runs record files and pull requests of their own. */
export function outputs(tasks, { limit = 5 } = {}) {
  return (Array.isArray(tasks) ? tasks : [])
    .filter((t) => t && t.state === 'done' && t.outcome)
    .sort((a, b) => String(b.done_at || b.updated_at || '').localeCompare(String(a.done_at || a.updated_at || '')))
    .slice(0, limit)
    .map((t) => ({ id: t.id, title: t.title, outcome: t.outcome }));
}

/** A budget in words: tokens as people read them (12k, 2.5M). */
export function tokens(n) {
  const v = Number(n) || 0;
  if (v >= 1e6) return `${+(v / 1e6).toFixed(v % 1e6 === 0 ? 0 : 1)}M`;
  if (v >= 1e3) return `${+(v / 1e3).toFixed(v % 1e3 === 0 ? 0 : 1)}k`;
  return String(v);
}

/** The budget line in the activity view. The cap counts only paid models, so
 *  the line says so; a local model runs without one. */
export function budgetLine(task) {
  const t = task || {};
  const spent = Number(t.spent_tokens) || 0;
  const limit = t.budget_limit;
  if (limit === null || limit === undefined) {
    return `${tokens(spent)} tokens on paid models, no limit set. Local models run uncapped.`;
  }
  const own = t.budget_tokens !== null && t.budget_tokens !== undefined && Number(t.budget_tokens) === Number(limit);
  return `${tokens(spent)} of ${tokens(limit)} tokens on paid models${own ? '' : ' (the admin cap)'}. Local models run uncapped.`;
}

/** Parse what a person typed as a budget: "250k", "2M", "40000", or empty to
 *  clear it back to the admin cap. Returns `{ ok, value }`; value null clears. */
export function parseBudget(text) {
  const raw = String(text == null ? '' : text).trim().toLowerCase().replace(/[,\s_]/g, '');
  if (!raw) return { ok: true, value: null };
  const m = /^(\d+(?:\.\d+)?)([km]?)$/.exec(raw);
  if (!m) return { ok: false, value: null };
  const mult = m[2] === 'm' ? 1e6 : m[2] === 'k' ? 1e3 : 1;
  const value = Math.round(parseFloat(m[1]) * mult);
  return value >= 0 && Number.isFinite(value) ? { ok: true, value } : { ok: false, value: null };
}

/** The verb for the activity view's run button: start, run again, or none
 *  while it runs or without a lead to run it. */
export function runVerb(task) {
  const t = task || {};
  if (!t.lead_agent) return '';
  if (t.state === 'working' && t.hire_id) return '';
  return t.hire_id ? 'Run again' : 'Start';
}

/** What Apollo knows, split the way the page shows it: what the person said
 *  (stated) above what Apollo worked out (inferred), each newest first. */
export function knowsGroups(lines) {
  const all = (Array.isArray(lines) ? lines : []).slice()
    .sort((a, b) => (Number(b.since) || 0) - (Number(a.since) || 0));
  return {
    stated: all.filter((l) => l && l.basis === 'stated'),
    inferred: all.filter((l) => l && l.basis !== 'stated'),
  };
}

/** The Computer card from `GET /api/workstation/status`: its words, a dot, and
 *  whether a click can open the live screen. */
export function computerCard(ws) {
  const s = ws || {};
  const state = s.state || 'off';
  const label = { up: 'Running', down: 'Stopped', off: 'Off', unconfigured: 'Not set up', not_permitted: 'Not available to you' }[state] || 'Unknown';
  return { label, state, sentence: s.sentence || '', opens: state === 'up' || state === 'down' };
}
