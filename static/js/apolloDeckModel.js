// SPDX-License-Identifier: AGPL-3.0-or-later
//
// apolloDeckModel.js — what Apollo's deck says, worked out from what
// `/api/apollo/*` answers, with no DOM and no fetch, so node can drive it.
//
// The deck (`apolloDeck.js`) is Apollo's page: the goals rail, the board of
// the open goal (its plan, who is on it, the handoffs between them), Needs you,
// and home. These functions only decide what goes where and in which words;
// every sentence the server wrote stays text.

import { teamLine, teamRole, tokens, dotOf } from './apolloPaneModel.js';

const ORDER = { needs_you: 0, working: 1, waiting: 2, done: 3 };

/** A goal is a task with no parent: delegates sit on their goal's board. */
export function goalsOf(tasks) {
  return (Array.isArray(tasks) ? tasks : []).filter((t) => t && !t.parent_id);
}

/** The rail: open goals first (needs you, then working, then waiting), newest
 *  touched first within each; finished goals after, `doneLimit` of them. */
export function railRows(tasks, { doneLimit = 5 } = {}) {
  const goals = goalsOf(tasks);
  const newest = (a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || ''));
  const open = goals.filter((t) => t.state !== 'done')
    .sort((a, b) => (ORDER[a.state] ?? 9) - (ORDER[b.state] ?? 9) || newest(a, b));
  const done = goals.filter((t) => t.state === 'done').sort(newest);
  return { open, done: done.slice(0, doneLimit), moreDone: Math.max(0, done.length - doneLimit) };
}

/** One rail card's lines: the goal, its state, who leads it and its spend. */
export function cardOf(task) {
  const t = task || {};
  const dot = dotOf(t.state);
  const lead = t.lead_name || (t.lead_agent ? t.lead_agent : 'Apollo');
  const spent = Number(t.spent_tokens) || 0;
  return {
    id: t.id, title: t.title || '', dot,
    lead: `Led by ${lead}`,
    spend: spent ? `${tokens(spent)} tokens` : '',
    line: t.state === 'needs_you' ? (t.question || '') : (t.state === 'done' ? (t.outcome || '') : (t.next_step || '')),
  };
}

/** The plan on the board: the goal and every delegate under it, in order,
 *  each as a step with its owner, its role, its state and its depth. */
export function planSteps(team) {
  const members = team && Array.isArray(team.members) ? team.members : [];
  return members.map((m) => ({
    id: m.id, title: m.title || '', depth: Number(m.depth) || 0,
    owner: m.lead_name || m.lead || 'Apollo', role: teamRole(m), dot: dotOf(m.state),
  }));
}

/** The handoffs on the board, newest last: who handed what to whom, asked,
 *  reviewed, reported or escalated, in one line each. */
export function handoffs(team, { limit = 30 } = {}) {
  const members = team && Array.isArray(team.members) ? team.members : [];
  const names = {};
  for (const m of members) if (m.lead && m.lead_name) names[m.lead] = m.lead_name;
  const msgs = team && Array.isArray(team.messages) ? team.messages : [];
  return msgs.slice(-limit).map((m) => ({ id: m.id, kind: m.kind, at: m.at, line: teamLine(m, names) }));
}

/** Who is on the goal right now: each member that is working, once per agent. */
export function runningNow(team) {
  const seen = new Set();
  const out = [];
  for (const s of planSteps(team)) {
    if (s.dot.words !== 'Working' || seen.has(s.owner)) continue;
    seen.add(s.owner);
    out.push({ owner: s.owner, on: s.title });
  }
  return out;
}

/** Home: what moved since the person last looked, what is running, what
 *  needs them and what has been spent, from the task list and the approvals. */
export function home(tasks, approvals, sinceIso) {
  const all = Array.isArray(tasks) ? tasks : [];
  const since = String(sinceIso || '');
  const moved = since
    ? all.filter((t) => String(t.updated_at || '') > since)
      .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    : [];
  const running = goalsOf(all).filter((t) => t.state === 'working');
  const needs = all.filter((t) => t.state === 'needs_you').length + (Array.isArray(approvals) ? approvals.length : 0);
  const spent = all.reduce((n, t) => n + (Number(t.spent_tokens) || 0), 0);
  return {
    moved: moved.map((t) => ({ id: t.id, title: t.title, words: dotOf(t.state).words })),
    running: running.map((t) => ({ id: t.id, title: t.title, lead: t.lead_name || t.lead_agent || 'Apollo' })),
    needs,
    spent: spent ? `${tokens(spent)} tokens on paid models` : 'Nothing spent on paid models',
    headline: needs ? `${needs} ${needs === 1 ? 'thing needs' : 'things need'} you`
      : running.length ? `${running.length} ${running.length === 1 ? 'goal' : 'goals'} running, nothing needs you`
        : 'Nothing running. Give Apollo a goal.',
  };
}

/** The control pane's Chats: the person's other chats, as the sidebar lists
 *  them (not archived, not Apollo's own, not a Nobody chat), favourites first
 *  and then the most recently active, `limit` of them. `incognito(id)` says
 *  whether a chat is a Nobody chat the sidebar leaves out. */
export function chatRows(sessions, currentId, { limit = 6, incognito = () => false } = {}) {
  const rows = (Array.isArray(sessions) ? sessions : []).filter((s) => s && s.id
    && s.id !== currentId && !s.archived && s.folder !== 'Assistant' && !incognito(s.id)
    && !['Nobody', 'Incognito'].includes(String(s.name || '').trim()));
  const when = (s) => String(s.last_message_at || s.updated_at || s.created_at || '');
  rows.sort((a, b) => (Number(!!b.is_important) - Number(!!a.is_important)) || when(b).localeCompare(when(a)));
  return {
    rows: rows.slice(0, limit).map((s) => ({ id: s.id, name: String(s.name || '').trim() || 'Untitled chat', pinned: !!s.is_important })),
    more: Math.max(0, rows.length - limit),
  };
}
