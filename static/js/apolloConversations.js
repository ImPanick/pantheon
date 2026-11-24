// SPDX-License-Identifier: AGPL-3.0-or-later
//
// apolloConversations.js — start a new conversation with Apollo, and open an
// earlier one.
//
// The owner's test on a fresh deploy (2026-11-24): Apollo was "another generic
// Chat page that can't be cleared". Apollo's chat was one session for life and
// the generic delete refuses a chat with messages. `POST
// /api/apollo/conversations/new` starts a fresh chat and keeps the work
// (tasks, notebook, what Apollo knows, Spaces); the old chat is filed as an
// earlier conversation, listed by `GET /api/apollo/conversations/earlier`.
//
// Both controls sit in Apollo's bar (`apolloView.js`, `extraButtons`). The
// Earlier list opens in the page's flow under the bar, not over it.

import uiModule from './ui.js';
import { selectSession } from './sessions.js';

const EARLIER_ID = 'apollo-earlier';

const NEW = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
const CLOCK = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>';

let _onFresh = null;
let _earlierBtn = null;  // the bar's Earlier button, marked open while the list shows   // called with the new session id once Apollo has moved to it

function _say(msg) {
  try { uiModule.showToast(msg); } catch (_) { /* no toast host */ }
}

async function _api(path, { method = 'GET', body } = {}) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const why = data && typeof data.detail === 'string' ? data.detail : `Apollo could not do that (${res.status}).`;
    throw new Error(why);
  }
  return data;
}

async function _space() {
  try {
    const Sp = await import('./apolloSpaces.js');
    return Sp.currentSpace();
  } catch (_) {
    return null;
  }
}

function _button(id, label, svg, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.id = id;
  b.className = 'apo-bar-btn apo-bar-btn-text';
  b.title = label;
  b.setAttribute('aria-label', label);
  b.innerHTML = svg;
  const words = document.createElement('span');
  words.className = 'apo-bar-btn-words';
  words.textContent = label;
  b.appendChild(words);
  b.addEventListener('click', onClick);
  return b;
}

/** Start a new conversation in the space Apollo is in. Resolves to the
 *  response, or null when it was refused (the reason is said in a toast). */
export async function startNewConversation() {
  closeEarlier();
  let out;
  try {
    out = await _api('/api/apollo/conversations/new', { method: 'POST', body: { space_id: await _space() } });
  } catch (e) {
    _say(e.message);
    return null;
  }
  if (out.unchanged) {
    _say('This conversation is already empty.');
    return out;
  }
  try { await _onFresh?.(out.session_id); } catch (_) { /* the caller's own trouble */ }
  // A space's chat is found from the spaces list, which still names the old
  // chat: read it again so the new one is recognised as that space's.
  try { await (await import('./apolloSpaces.js')).loadSpaces(); } catch (_) { /* spaces off */ }
  await selectSession(out.session_id);
  return out;
}

export function closeEarlier() {
  document.getElementById(EARLIER_ID)?.remove();
  _earlierBtn?.setAttribute('aria-expanded', 'false');
}

function _when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** Show the earlier conversations under the bar; pressing one opens it. */
export async function toggleEarlier() {
  if (document.getElementById(EARLIER_ID)) { closeEarlier(); return; }
  const history = document.getElementById('chat-history');
  if (!history || !history.parentNode) return;
  const box = document.createElement('section');
  box.id = EARLIER_ID;
  box.className = 'apo-earlier';
  box.setAttribute('aria-label', 'Earlier conversations');
  const head = document.createElement('div');
  head.className = 'apo-earlier-t';
  head.textContent = 'Earlier conversations';
  box.appendChild(head);
  history.parentNode.insertBefore(box, history);
  _earlierBtn?.setAttribute('aria-expanded', 'true');

  let rows = [];
  try {
    rows = (await _api('/api/apollo/conversations/earlier')).conversations || [];
  } catch (e) {
    rows = null;
    const p = document.createElement('p');
    p.className = 'apo-earlier-none';
    p.textContent = e.message;
    box.appendChild(p);
  }
  if (rows && !rows.length) {
    const p = document.createElement('p');
    p.className = 'apo-earlier-none';
    p.textContent = 'No earlier conversations yet. Start a new one and this one moves here.';
    box.appendChild(p);
  }
  for (const r of rows || []) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'apo-earlier-row';
    b.dataset.session = r.session_id;
    const name = document.createElement('span');
    name.className = 'apo-earlier-name';
    name.textContent = r.name;
    const when = document.createElement('span');
    when.className = 'apo-earlier-when';
    when.textContent = _when(r.last_message_at);
    b.appendChild(name);
    b.appendChild(when);
    b.addEventListener('click', () => { closeEarlier(); selectSession(r.session_id); });
    box.appendChild(b);
  }
}

/** The two bar buttons, as factories for `enterApolloView({ extraButtons })`.
 *  `onFresh(sessionId)` runs once Apollo has moved to a new chat, before it
 *  is opened, so the caller can drop what it cached about the old one. */
export function barButtons({ onFresh } = {}) {
  _onFresh = onFresh || null;
  return [
    () => _button('apollo-new-btn', 'New conversation', NEW, () => { startNewConversation(); }),
    () => {
      const b = _button('apollo-earlier-btn', 'Earlier', CLOCK, () => { toggleEarlier(); });
      b.setAttribute('aria-expanded', 'false');
      _earlierBtn = b;
      return b;
    },
  ];
}
