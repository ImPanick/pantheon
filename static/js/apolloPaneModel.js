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

/* ───────────── the task chat (phase 2b) ───────────── */

function _textOf(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.map((p) => (typeof p === 'string' ? p : (p && typeof p.text === 'string' ? p.text : ''))).join('');
  }
  return '';
}

/** The task chat's lines from `GET /api/history/{id}`: the person's words and
 *  the lead's answers, in order. Tool chatter, system lines and the hidden
 *  stand-in a paused approval leaves are not lines a person reads here. */
export function chatEntries(history) {
  const out = [];
  for (const m of (Array.isArray(history) ? history : [])) {
    if (!m || (m.role !== 'user' && m.role !== 'assistant')) continue;
    const meta = m.metadata || {};
    if (meta.hidden) continue;
    const text = _textOf(m.content).trim();
    if (!text) continue;
    out.push({ role: m.role, text, id: meta._db_id || null });
  }
  return out;
}

/** Split what a `chat_stream` reply has sent so far into its `data:` events.
 *  Returns `{ events, rest }`: whole events parsed as JSON (a line that isn't
 *  JSON is skipped), and the unfinished tail to keep for the next chunk. */
export function sseEvents(buffer) {
  const lines = String(buffer || '').split('\n');
  const rest = lines.pop() || '';
  const events = [];
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const data = line.slice(6).trim();
    if (!data || data === '[DONE]') continue;
    try { events.push(JSON.parse(data)); } catch (_) { /* not an event */ }
  }
  return { events, rest };
}

/** An approval the lead is waiting on, from a stream's `ask_user` event:
 *  `{ id, question, options: [{ label, decision }] }`, or null. */
export function approvalOf(event) {
  const d = event && event.type === 'ask_user' ? event.data : null;
  if (!d || d.kind !== 'tool_approval' || !d.approval_id) return null;
  const options = (Array.isArray(d.options) ? d.options : [])
    .map((o) => ({ label: String((o && (o.label || o.text)) || o || ''), decision: String((o && o.value) || '').toLowerCase() }))
    .filter((o) => o.label && o.decision);
  return options.length ? { id: String(d.approval_id), question: String(d.question || 'Allow this?'), options } : null;
}

/** How the pane shows a phone from `GET /api/workstation/phone`. */
export function phoneCard(phone) {
  const p = phone || {};
  const state = p.state || 'unavailable';
  const label = { on: 'Running', starting: 'Starting', installing: 'Installing', off: 'Off', unavailable: 'Not available' }[state] || 'Unknown';
  const dev = (Array.isArray(p.devices) ? p.devices : []).find((d) => d && d.id === p.device);
  return { label, state, name: (dev && dev.name) || 'Phone', sentence: state === 'unavailable' ? String(p.why || '') : '', opens: state === 'on' || state === 'starting' || state === 'off' };
}

/** An approval still waiting in a task chat's history: the newest lead
 *  message's tool call that asked and was never answered. Answered calls
 *  carry `ask_user.resolved`, which the server writes. */
export function pendingApproval(history) {
  const list = Array.isArray(history) ? history : [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const m = list[i];
    if (!m) continue;
    if (m.role === 'user') return null;   // the person has spoken since
    if (m.role !== 'assistant') continue;
    const events = (m.metadata && Array.isArray(m.metadata.tool_events)) ? m.metadata.tool_events : [];
    for (let j = events.length - 1; j >= 0; j -= 1) {
      const ask = events[j] && events[j].ask_user;
      if (ask && !ask.resolved) return approvalOf({ type: 'ask_user', data: ask });
    }
    return null;
  }
  return null;
}

/* ───────────── spaces (phase 3) ───────────── */

/** The words for where Apollo is: the top layer or a space's path. */
export function spaceLabel(space) {
  if (!space) return 'Apollo';
  return String(space.path || space.name || 'A space');
}

/** One line for a child space, as its parent sees it: counts, never
 *  contents. An airgapped child says only whether something needs you. */
export function childLine(child) {
  const c = child || {};
  if (c.sealed) return c.needs_you ? 'Locked. Something there needs you.' : 'Locked.';
  const open = Number(c.open) || 0;
  const needs = Number(c.needs_you) || 0;
  if (!open) return 'Nothing open.';
  const bits = [`${open} open`];
  if (needs) bits.push(`${needs} need${needs === 1 ? 's' : ''} you`);
  return `${bits.join(', ')}.`;
}

/** The spaces a space may be given read of: in the open, not itself, not
 *  one above it (it already reads those), and not one it already reads for
 *  that kind of content. */
export function grantSources(spaces, current, context, scope) {
  const list = Array.isArray(spaces) ? spaces : [];
  const here = list.find((s) => s && s.id === current);
  if (!here || here.sealed) return [];
  const above = new Set();
  let at = here;
  while (at && at.parent_id) {
    above.add(at.parent_id);
    at = list.find((s) => s.id === at.parent_id);
  }
  const have = new Set(((context && context.reads_from) || [])
    .filter((r) => r && r.how === 'grant' && r.scope === scope).map((r) => r.space_id));
  return list.filter((s) => s && s.id !== current && !s.sealed && !above.has(s.id) && !have.has(s.id));
}

/** What a Context row says: where the read comes from and what it reads. */
export function contextLine(row) {
  const r = row || {};
  const what = { memory: 'what you told Apollo there', outcomes: 'what its tasks came to' }[r.scope] || '';
  if (r.how === 'above') return `${r.name}: everything, because it's above this space.`;
  if (r.how === 'below') return `${r.name}: everything here, because it's inside this space.`;
  return `${r.name}: ${what}, read only.`;
}

/** Locked spaces where something needs the person, from the spaces list,
 *  leaving out the space Apollo is in and those above or inside it (whose
 *  needs the pane already shows). */
export function lockedNeeds(spaces, current) {
  const list = Array.isArray(spaces) ? spaces : [];
  const byId = new Map(list.map((s) => [s && s.id, s]));
  const chain = (id) => {
    const out = [];
    let at = byId.get(id);
    while (at && out.length <= list.length) { out.push(at.id); at = byId.get(at.parent_id); }
    return out;
  };
  const above = new Set(current ? chain(current) : []);
  return list.filter((s) => s && s.sealed && s.needs_you && !above.has(s.id)
    && !(current && chain(s.id).includes(current)));
}

/** What the pane says of a locked space that needs the person. */
export function lockedLine(space) {
  return `${(space && space.name) || 'A locked space'} is locked. Something there needs you.`;
}

/* ───────────── rhythm (phase 4) ───────────── */

/** The check-in intervals the server takes, in hours; 0 is off. */
export const CHECKIN_HOURS = [0, 1, 2, 3, 4, 6, 8, 12];

/** What a check-in interval is called in the picker. */
export function checkinLabel(hours) {
  const h = Number(hours) || 0;
  if (!h) return 'Off';
  return h === 1 ? 'Every hour' : `Every ${h} hours`;
}

/** One plain line on when Apollo speaks unasked, for the main view. */
export function rhythmLine(r) {
  const x = r || {};
  const on = (x.briefings || []).filter((b) => b && b.enabled);
  const parts = [];
  if (!on.length) parts.push('No briefings set.');
  else if (on.length === 1) parts.push(`${on[0].name} at ${on[0].time}.`);
  else parts.push(`${on[0].name} at ${on[0].time}, and ${on.length - 1} more ${on.length === 2 ? 'briefing' : 'briefings'}.`);
  const h = Number(x.checkin_hours) || 0;
  parts.push(h ? `Check-ins ${checkinLabel(h).toLowerCase()}, only when something changed.` : 'No check-ins.');
  const q = x.quiet || {};
  if (q.start && q.end) parts.push(`Quiet ${q.start} to ${q.end}.`);
  return parts.join(' ');
}

/** A time for a new briefing: 07:00 for the first, otherwise the first whole
 *  hour from 12:00 on that no briefing has. */
export function nextBriefingTime(briefings) {
  const taken = new Set((briefings || []).map((b) => b && b.time));
  if (!taken.size) return '07:00';
  for (let h = 12; h < 36; h += 1) {
    const t = `${String(h % 24).padStart(2, '0')}:00`;
    if (!taken.has(t)) return t;
  }
  return '';
}

/** When Apollo last spoke unasked, in plain words. */
export function lastSpoke(iso, now = Date.now()) {
  const at = Date.parse(iso || '');
  if (!Number.isFinite(at)) return 'Apollo hasn’t spoken unasked yet.';
  const min = Math.max(0, Math.round((now - at) / 60000));
  if (min < 1) return 'Apollo last spoke just now.';
  if (min < 60) return `Apollo last spoke ${min} ${min === 1 ? 'minute' : 'minutes'} ago.`;
  const h = Math.round(min / 60);
  if (h < 24) return `Apollo last spoke ${h} ${h === 1 ? 'hour' : 'hours'} ago.`;
  const d = Math.round(h / 24);
  return `Apollo last spoke ${d} ${d === 1 ? 'day' : 'days'} ago.`;
}

/* ───────────── voice (phase 4) ───────────── */

/** The words at each end of a dial and at its centre. */
export const DIAL_ENDS = { warmth: ['Terse', 'Warm'], play: ['Dry', 'Playful'] };

/** Where a dial sits, in words: "Warm", "A little terse", "Apollo's own". */
export function dialWords(dial, value) {
  const v = Number(value) || 0;
  const [lo, hi] = DIAL_ENDS[dial] || ['', ''];
  if (!v) return 'Apollo’s own';
  const end = v < 0 ? lo : hi;
  return Math.abs(v) === 1 ? `A little ${end.toLowerCase()}` : end;
}

/** What the pane says of how Apollo held its ground on its talk model. */
export function heldLine(held) {
  const h = held || {};
  if (!h.model) return 'Pushback hasn’t been measured: no talk model is set.';
  if (h.badge === 'not-measured') return `Pushback hasn’t been measured on ${h.model} yet.`;
  if (h.badge === 'needs-bigger') return `On ${h.model}, Apollo sometimes caved when pushed. A bigger model holds better.`;
  return `On ${h.model}, Apollo held its ground when pushed.`;
}

/** How a team member came to work on the goal, in a few words. */
export function teamRole(member) {
  const m = member || {};
  if (!m.parent_id) return 'Leads the goal';
  if (m.via === 'review') return 'Reviewing';
  if (m.via === 'ask') return 'Answering a question';
  if (m.review_by === 'person') return m.stage === 'in_review' ? 'Waiting on your review' : 'Delegate, you review';
  if (m.review_by) return 'Delegate, reviewed';
  return 'Delegate';
}

const _SAID = { delegate: 'handed', ask: 'asked', review: 'sent for review to', report: 'reported to', escalate: 'asked you', gap: 'found no agent for' };

/** One line of a goal's log: who said what to whom, first line only. */
export function teamLine(msg, names = {}) {
  const m = msg || {};
  const who = (id) => (id === 'person' ? 'You' : (names[id] || id || 'Apollo'));
  const verb = _SAID[m.kind] || m.kind || 'said';
  const first = String(m.body || '').split('\n').find((l) => l.trim()) || '';
  const short = first.length > 140 ? `${first.slice(0, 139)}…` : first;
  const to = (m.kind === 'escalate' || m.kind === 'gap') ? '' : ` ${m.to === 'person' ? 'you' : (names[m.to] || m.to || '')}`;
  return `${who(m.from)} ${verb}${to}${short ? `: ${short}` : ''}`.replace(/\s+:/, ':');
}

/* ───────────── phase 5b: missing agents ───────────── */

const _FIT = { 'runs-well': 'Runs well', 'runs-slowly': 'Runs, slowly',
  'needs-bigger': 'Needs a bigger model', 'not-measured': 'Not measured' };

/** A fit badge in words, as the hall says it. */
export function fitWords(badge) { return _FIT[badge] || ''; }

/** The person's proposals worth showing: every open one, and the settled
 *  ones from the last week, newest first, six at most. */
export function madeList(proposals, now = Date.now()) {
  const week = 7 * 24 * 3600 * 1000;
  return (Array.isArray(proposals) ? proposals : [])
    .filter((p) => ['drafting', 'proving', 'waiting'].includes(p.state)
      || (now - Date.parse(p.updated_at || p.created_at || 0)) < week)
    .slice(0, 6);
}

/** What a drafted agent asks for, in one line an admin can weigh. */
export function asksLine(asks) {
  const a = asks || {};
  if (a.error) return `Its file doesn't pass its check: ${a.error}`;
  const tools = (a.tools || []).join(', ') || 'no tools';
  const fx = Object.entries(a.effects || {}).map(([k, v]) => `${k} ${v}`).join(', ');
  return `Uses ${tools}.${fx ? ` Effects: ${fx}.` : ''}`;
}

/** How its proof run went, in a line. */
export function proofLine(p) {
  const r = (p && p.proof) || null;
  if (!r) return '';
  const fit = fitWords(p.badge);
  const n = Number(r.runs);
  const passed = n > 0 && Number.isFinite(Number(r.pass_rate))
    ? ` ${Math.round(Number(r.pass_rate) * n)} of ${n} runs passed.` : '';
  return `Proven on ${p.model || r.model || 'your model'}${fit ? `: ${fit}` : ''}.${passed}`;
}
