// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/summon.js
//
// `P24-26`. Summon an agent into a chat. The composer's + menu has *Agents ›*
// (Agent mode only, like Workspace); its submenu lists the hall — the agents
// this person has summoned to work for them first, then every agent,
// searchable (`composerMenu.js`, `P25-01`) — and the one picked shows as a
// chip beside the Workspace pill.
// While the chip is there each Agent-mode send carries `agent=<id>`, and the
// server narrows the turn to that agent's runbook, tools and effects table
// (`src/agents/summon.py`). A click on the chip dismisses it.
//
// The list is `GET /api/agents`, the hall's own answer (`Law 14`); nothing here
// decides what an agent may do. Text from a manifest is drawn as letters.

import Storage, { KEYS } from './storage.js';

function _isChatMode() {
  const b = document.getElementById('mode-chat-btn');
  return !!(b && b.classList.contains('active'));
}

export function getSummoned() {
  const raw = Storage.get(KEYS.SUMMONED_AGENT, '');
  if (!raw) return null;
  try {
    const v = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return v && v.id ? { id: String(v.id), name: String(v.name || v.id) } : null;
  } catch (_) {
    return null;
  }
}

export function sync() {
  const chat = _isChatMode();
  const s = getSummoned();
  const chip = document.getElementById('summon-indicator-btn');
  const name = document.getElementById('summon-indicator-name');
  const item = document.getElementById('overflow-agents-btn');
  if (chip) {
    chip.style.display = (s && !chat) ? '' : 'none';
    chip.classList.toggle('active', !!s);
    if (s) chip.title = `${s.name} is summoned: this chat uses its runbook and only its tools.\nClick to dismiss.`;
  }
  if (name) name.textContent = s ? s.name : '';
  if (item) {
    item.style.display = chat ? 'none' : '';
    item.classList.toggle('active', !!s);
  }
  try { document.dispatchEvent(new CustomEvent('overflow-state-change')); } catch (_) {}
}

export function summon(agent) {
  Storage.set(KEYS.SUMMONED_AGENT, JSON.stringify({ id: agent.id, name: agent.name }));
  sync();
}

export function dismiss() {
  Storage.remove(KEYS.SUMMONED_AGENT);
  sync();
}

export function applyMode(_mode) {
  sync();
}

/** The picker's rows for `agents`, those `mine` names first, filtered by `query`. */
export function pickerRows(agents, mine, query) {
  const q = String(query || '').trim().toLowerCase();
  const hits = (agents || []).filter((a) => !q
    || `${a.name} ${a.tagline} ${a.section_label || ''}`.toLowerCase().includes(q));
  const own = new Set(mine || []);
  return hits.filter((a) => own.has(a.id)).concat(hits.filter((a) => !own.has(a.id)));
}

/** The *Agents ›* row is a submenu (`composerMenu.js`, `P25-01`) — the
 *  list it shows is `pickerRows`, and a pick is `summon`. */
export function initSummon() {
  const chip = document.getElementById('summon-indicator-btn');
  if (chip) chip.addEventListener('click', dismiss);
  sync();
}

export default { initSummon, getSummoned, summon, dismiss, applyMode, sync, pickerRows };
