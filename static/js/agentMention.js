// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/agentMention.js
//
// `B1738`. Typing `@` in the message box opens the agent picker: the hall's
// agents (the person's own and summoned ones first, `summon.pickerRows`),
// narrowed by what follows the `@`. A pick summons that agent into the chat
// the way the + menu's *Agents ›* does (`summon.summon`), switching to Agent
// mode first when the chat is in Chat mode, and takes the `@words` back out
// of the box. The list is `GET /api/agents`, the hall's own answer; nothing
// here decides what an agent may do. Manifest text is drawn as letters.
//
// The `@` counts at the start of the box or after a space, so an address
// like name@example.com never opens it.

import summon, { pickerRows } from './summon.js';
import { topPortalZ } from './toolWindowZOrder.js';

const POPUP_ID = 'agent-mention-popup';
const MAX_ROWS = 40;
const CACHE_MS = 60000;
// What the `@` opens on: the words since it, up to the caret, with no second
// `@` and no line break.
const TRIGGER = /(^|\s)@([^\s@]*(?: [^\s@]+){0,3})$/;

let _cache = null;   // { at, agents, mine }

async function _load() {
  if (_cache && Date.now() - _cache.at < CACHE_MS) return _cache;
  try {
    const res = await fetch('/api/agents', { credentials: 'same-origin' });
    if (!res.ok) return _cache || { at: 0, agents: [], mine: [], failed: true };
    const data = await res.json();
    const mine = (data.hires || []).filter((h) => h.owner === data.me).map((h) => h.agent_id);
    _cache = { at: Date.now(), agents: Array.isArray(data.agents) ? data.agents : [], mine };
    return _cache;
  } catch (_) {
    return _cache || { at: 0, agents: [], mine: [], failed: true };
  }
}

/** The `@words` before the caret, as `{ start, query }`, or `null`. Exported
 *  for the tests. */
export function mentionAt(value, caret) {
  const before = String(value || '').slice(0, caret == null ? undefined : caret);
  const line = before.slice(before.lastIndexOf('\n') + 1);
  const m = TRIGGER.exec(line);
  if (!m) return null;
  const start = before.length - m[0].length + m[1].length;
  return { start, query: m[2] || '' };
}

function _isChatMode() {
  const b = document.getElementById('mode-chat-btn');
  return !!(b && b.classList.contains('active'));
}

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

export function initAgentMention(textarea) {
  if (!textarea || textarea._agentMentionWired) return;
  textarea._agentMentionWired = true;

  let popup = null;
  let visible = false;
  let rows = [];
  let sel = 0;
  let at = null;       // { start, query } of the open mention
  let ticket = 0;

  const ensure = () => {
    if (popup) return popup;
    popup = document.getElementById(POPUP_ID);
    if (!popup) {
      popup = _el('div', 'slash-autocomplete-popup agent-mention-popup ck-pop');
      popup.id = POPUP_ID;
      popup.setAttribute('role', 'listbox');
      popup.setAttribute('aria-label', 'Summon an agent');
      document.body.appendChild(popup);
    }
    return popup;
  };

  const position = () => {
    const r = textarea.getBoundingClientRect();
    const maxH = Math.min(window.innerHeight * 0.55, 420);
    popup.style.maxHeight = maxH + 'px';
    popup.style.left = Math.round(r.left) + 'px';
    popup.style.width = Math.max(300, Math.round(Math.min(r.width, 520))) + 'px';
    if (r.top > maxH + 20) {
      popup.style.bottom = (window.innerHeight - r.top + 6) + 'px';
      popup.style.top = '';
    } else {
      popup.style.top = (r.bottom + 6) + 'px';
      popup.style.bottom = '';
    }
  };

  const hide = () => {
    visible = false;
    at = null;
    if (popup) popup.style.display = 'none';
    textarea.removeAttribute('aria-activedescendant');
  };

  const render = (emptyWords) => {
    popup.textContent = '';
    popup.appendChild(_el('div', 'slash-ac-cat', 'Summon an agent'));
    if (!rows.length) {
      popup.appendChild(_el('div', 'slash-ac-empty', emptyWords));
      return;
    }
    rows.forEach((row, i) => {
      const r = _el('div', 'slash-ac-row agent-mention-row' + (i === sel ? ' slash-ac-row-sel' : ''));
      r.setAttribute('role', 'option');
      r.id = `agent-mention-opt-${i}`;
      r.dataset.idx = String(i);
      r.appendChild(_el('span', 'slash-ac-token', row.label));
      r.appendChild(_el('span', 'slash-ac-help', row.hint || ''));
      if (row.badge) r.appendChild(_el('span', 'slash-ac-usage slash-ac-shelf', row.badge));
      popup.appendChild(r);
    });
    const s = popup.querySelector('.slash-ac-row-sel');
    if (s) {
      s.scrollIntoView({ block: 'nearest' });
      textarea.setAttribute('aria-activedescendant', s.id);
    }
  };

  const refresh = async () => {
    const found = mentionAt(textarea.value, textarea.selectionStart);
    if (!found) { hide(); return; }
    at = found;
    const mine = ++ticket;
    ensure();
    popup.style.zIndex = String(topPortalZ());
    if (!visible) {
      visible = true;
      popup.style.display = 'block';
      position();
      if (!_cache) render('Reading the Agents hall…');
    }
    const data = await _load();
    if (mine !== ticket || !visible) return;
    const now = summon.getSummoned();
    const list = pickerRows(data.agents, data.mine, found.query).slice(0, MAX_ROWS);
    rows = [];
    if (now && !found.query) {
      rows.push({ label: `Dismiss ${now.name}`, hint: 'Back to the chat on its own', dismiss: true });
    }
    list.forEach((a) => rows.push({
      label: a.name,
      hint: a.tagline || '',
      badge: (now && now.id === a.id) ? 'Summoned' : (a.source === 'own' ? 'Yours' : (data.mine.includes(a.id) ? 'Hired' : '')),
      agent: { id: a.id, name: a.name },
    }));
    // Words after a mention that matched nothing are the message going on.
    if (!list.length && /\s/.test(found.query)) { hide(); return; }
    sel = Math.min(sel, Math.max(0, rows.length - 1));
    render(data.failed ? 'The Agents hall could not be read. Try again in a moment.'
                       : `No agent matches “${found.query}”.`);
  };

  const pick = (row) => {
    if (!row || !at) return;
    const before = textarea.value.slice(0, at.start).replace(/\s+$/, '');
    const after = textarea.value.slice(textarea.selectionStart).replace(/^\s+/, '');
    const glue = before && after ? ' ' : '';
    textarea.value = before + glue + after;
    const caret = before.length + glue.length;
    hide();
    if (row.dismiss) {
      summon.dismiss();
    } else {
      if (_isChatMode()) {
        const agentBtn = document.getElementById('mode-agent-btn');
        if (agentBtn) agentBtn.click();
      }
      summon.summon(row.agent);
    }
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    textarea.focus();
    try { textarea.setSelectionRange(caret, caret); } catch (_) {}
  };

  textarea.addEventListener('input', () => { sel = 0; refresh(); });
  textarea.addEventListener('click', () => { if (visible || textarea.value.includes('@')) refresh(); });
  textarea.addEventListener('blur', () => { setTimeout(hide, 120); });

  // Capture on the document, so the picker answers Enter before the
  // composer's own listener sends the message.
  document.addEventListener('keydown', (e) => {
    if (e.target !== textarea || !visible) return;
    const take = () => { e.preventDefault(); e.stopImmediatePropagation(); };
    if (e.key === 'ArrowDown' && rows.length) {
      take(); sel = (sel + 1) % rows.length; render('');
    } else if (e.key === 'ArrowUp' && rows.length) {
      take(); sel = (sel - 1 + rows.length) % rows.length; render('');
    } else if ((e.key === 'Enter' && !e.shiftKey && !e.isComposing) || (e.key === 'Tab' && !e.shiftKey)) {
      if (!rows.length) { if (e.key === 'Enter') { take(); } hide(); return; }
      take(); pick(rows[sel]);
    } else if (e.key === 'Escape') {
      take(); hide();
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'Home' || e.key === 'End') {
      setTimeout(refresh, 0);
    }
  }, true);

  window.addEventListener('resize', () => { if (visible) position(); });

  document.addEventListener('mousedown', (e) => {
    if (!visible || !popup) return;
    const r = e.target.closest?.('.agent-mention-row');
    if (r && popup.contains(r)) {
      e.preventDefault();
      pick(rows[Number(r.dataset.idx)]);
    }
  });
}

export default { initAgentMention, mentionAt };
