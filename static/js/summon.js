// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/summon.js
//
// `P24-26`. Summon an agent into a chat. The composer's `^` menu has *Agents*
// (Agent mode only, like Workspace); it opens a picker over the hall — the
// agents this person has summoned to work for them first, then every agent,
// searchable — and the one picked shows as a chip beside the Workspace pill.
// While the chip is there each Agent-mode send carries `agent=<id>`, and the
// server narrows the turn to that agent's runbook, tools and effects table
// (`src/agents/summon.py`). A click on the chip dismisses it.
//
// The list is `GET /api/agents`, the hall's own answer (`Law 14`); nothing here
// decides what an agent may do. Text from a manifest is drawn as letters.

import Storage, { KEYS } from './storage.js';

let _picker = null;

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

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _close() {
  if (_picker && _picker.parentNode) _picker.parentNode.removeChild(_picker);
  _picker = null;
}

/** The picker's rows for `agents`, those `mine` names first, filtered by `query`. */
export function pickerRows(agents, mine, query) {
  const q = String(query || '').trim().toLowerCase();
  const hits = (agents || []).filter((a) => !q
    || `${a.name} ${a.tagline} ${a.section_label || ''}`.toLowerCase().includes(q));
  const own = new Set(mine || []);
  return hits.filter((a) => own.has(a.id)).concat(hits.filter((a) => !own.has(a.id)));
}

export async function openPicker() {
  _close();
  const box = _el('div', 'summon-picker');
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-label', 'Summon an agent');
  box.appendChild(_el('div', 'summon-picker-title', 'Summon an agent into this chat'));
  const search = document.createElement('input');
  search.type = 'search';
  search.className = 'summon-picker-search';
  search.placeholder = 'Search agents…';
  search.setAttribute('aria-label', 'Search agents');
  box.appendChild(search);
  const list = _el('div', 'summon-picker-list');
  box.appendChild(list);
  const note = _el('p', 'summon-picker-note',
    'Its runbook guides the chat and only its tools are offered, until you dismiss it.');
  box.appendChild(note);
  const bar = document.querySelector('.chat-input-bar') || document.body;
  bar.appendChild(box);
  _picker = box;

  let data = null;
  try {
    const res = await fetch('/api/agents', { credentials: 'same-origin' });
    data = res.ok ? await res.json() : null;
  } catch (_) { data = null; }
  if (_picker !== box) return;
  if (!data) {
    list.appendChild(_el('p', 'summon-picker-empty', "The Agents hall could not be read. Try again in a moment."));
    return;
  }
  const mine = (data.hires || []).filter((h) => h.owner === data.me).map((h) => h.agent_id);
  const draw = () => {
    list.textContent = '';
    const rows = pickerRows(data.agents, mine, search.value).slice(0, 60);
    if (!rows.length) {
      list.appendChild(_el('p', 'summon-picker-empty', 'No agent matches that.'));
      return;
    }
    rows.forEach((a) => {
      const row = _el('button', 'summon-picker-row');
      row.type = 'button';
      row.dataset.agent = a.id;
      row.appendChild(_el('span', 'summon-picker-name', a.name));
      if (mine.includes(a.id)) row.appendChild(_el('span', 'summon-picker-mine', 'Yours'));
      row.appendChild(_el('span', 'summon-picker-tag', a.tagline));
      row.addEventListener('click', () => { summon(a); _close(); });
      list.appendChild(row);
    });
  };
  search.addEventListener('input', draw);
  search.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); _close(); } });
  draw();
  try { search.focus(); } catch (_) {}
}

export function initSummon() {
  const item = document.getElementById('overflow-agents-btn');
  if (item) item.addEventListener('click', () => { openPicker(); });
  const chip = document.getElementById('summon-indicator-btn');
  if (chip) chip.addEventListener('click', dismiss);
  document.addEventListener('click', (e) => {
    if (_picker && !_picker.contains(e.target) && !(item && item.contains(e.target))) _close();
  });
  sync();
}

export const _test = { picker: () => _picker, close: _close };

export default { initSummon, openPicker, getSummoned, summon, dismiss, applyMode, sync, pickerRows };
