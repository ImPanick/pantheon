// SPDX-License-Identifier: AGPL-3.0-or-later
//
// apolloSpaces.js — which of the person's spaces Apollo is in, and the
// switcher that moves between them.
//
// The outline (*Spaces*, "Where it shows"): a space switcher sits at the top
// of the Apollo chat and in the pane header. Each space has its own Apollo
// chat (`POST /api/apollo/spaces/{id}/chat`, `top` for Apollo's main chat),
// so switching space opens that chat, and the space Apollo is in is simply
// the space whose chat is open. An airgapped space carries a lock.
//
// What a space may see is the server's rule (`src/apollo/spaces.py`); this
// module only says where the person is and asks for the rest. No server
// string is parsed as HTML.

import uiModule from './ui.js';
import * as M from './apolloPaneModel.js';

const LOCK = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
  + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/>'
  + '<path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';

let _spaces = [];
let _loaded = false;
let _current = null;     // the space id Apollo is in; null is the top layer
const _listeners = new Set();
const _labels = new Set();     // switchers to redraw when the list is read again (a rename, a lock)

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null && text !== '') n.textContent = String(text);
  return n;
}

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

function _emit() {
  for (const fn of [..._listeners]) {
    try { fn(_current); } catch (_) { /* a listener's own trouble */ }
  }
}

/** Read the person's spaces again. */
export async function loadSpaces() {
  const out = await _api('/api/apollo/spaces');
  _spaces = (out && Array.isArray(out.spaces)) ? out.spaces : [];
  _loaded = true;
  if (_current && !_spaces.some((s) => s.id === _current)) { _current = null; _emit(); }
  for (const fn of [..._labels]) { try { fn(); } catch (_) { /* gone */ } }
  return _spaces;
}

export function spaceList() { return _spaces; }
export function currentSpace() { return _current; }
export function currentRow() { return _spaces.find((s) => s.id === _current) || null; }

/** The `?space=` value for where Apollo is. */
export function spaceParam() { return _current || 'top'; }

export function onSpaceChange(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

/** The space whose Apollo chat `sessionId` is: an id, or undefined when it
 *  is no space's chat. */
export async function spaceOfSession(sessionId) {
  if (!sessionId) return undefined;
  // Read once per page: a space's chat is made by `switchTo`, which reads
  // the list again after, so a later chat switch needn't ask the server.
  if (!_loaded) {
    try { await loadSpaces(); } catch (_) { return undefined; }
  }
  const row = _spaces.find((s) => s.session_id === sessionId);
  return row ? row.id : undefined;
}

/** The open chat is one of Apollo's: say which space that puts Apollo in. */
export function noteSpace(spaceId) {
  const next = spaceId || null;
  if (next === _current) return;
  _current = next;
  _emit();
}

/** Move Apollo to a space (null for the top layer): open that space's chat. */
export async function switchTo(spaceId) {
  const key = spaceId || 'top';
  try {
    const out = await _api(`/api/apollo/spaces/${encodeURIComponent(key)}/chat`, { method: 'POST' });
    if (spaceId) await loadSpaces();
    noteSpace(spaceId || null);
    const sessions = await import('./sessions.js');
    await sessions.selectSession(out.session_id);
    return true;
  } catch (err) {
    _say(err.message || 'That space could not be opened just now.');
    return false;
  }
}

/** Make a space, inside `parentId` (or at the top), and go to it. */
export async function makeSpace(name, { parentId = null, airgapped = false } = {}) {
  const row = await _api('/api/apollo/spaces', { method: 'POST', body: { name, parent_id: parentId, airgapped } });
  await loadSpaces();
  return row;
}

function _lock() {
  const l = _el('span', 'apo-lock');
  l.innerHTML = LOCK;            // a constant above, never server text
  l.setAttribute('title', 'Airgapped');
  return l;
}

/** The switcher: a button naming where Apollo is, opening a menu of spaces
 *  and a line to make a new one. Returns `{ el, destroy }`. */
export function createSwitcher() {
  const el = _el('div', 'apo-space');
  const btn = _el('button', 'apo-space-b');
  btn.type = 'button';
  btn.setAttribute('aria-haspopup', 'menu');
  btn.setAttribute('aria-expanded', 'false');
  const menu = _el('div', 'apo-space-menu');
  menu.setAttribute('role', 'menu');
  menu.hidden = true;
  el.appendChild(btn);
  el.appendChild(menu);

  function label() {
    btn.textContent = '';
    const row = currentRow();
    if (row && row.sealed) btn.appendChild(_lock());
    btn.appendChild(_el('span', 'apo-space-name', M.spaceLabel(row)));
    btn.appendChild(_el('span', 'apo-space-caret', '▾'));
    btn.setAttribute('aria-label', `Space: ${M.spaceLabel(row)}. Change space`);
  }

  function close() {
    menu.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
  }

  function item(text, spaceId, depth, sealed) {
    const b = _el('button', `apo-space-i apo-depth-${Math.min(depth, 3)}`);
    b.type = 'button';
    b.setAttribute('role', 'menuitemradio');
    b.setAttribute('aria-checked', String((spaceId || null) === _current));
    if (sealed) b.appendChild(_lock());
    b.appendChild(_el('span', '', text));
    b.addEventListener('click', async () => { close(); await switchTo(spaceId); });
    return b;
  }

  function draw() {
    menu.textContent = '';
    menu.appendChild(item('Apollo', null, 0, false));
    for (const s of _spaces) menu.appendChild(item(s.name, s.id, s.depth + 1, s.sealed));
    const form = _el('form', 'apo-space-new');
    const input = _el('input', 'apo-input');
    input.type = 'text';
    input.maxLength = 60;
    input.placeholder = 'New space';
    input.setAttribute('aria-label', 'Name a new space');
    const inside = _el('label', 'apo-check');
    const insideBox = _el('input');
    insideBox.type = 'checkbox';
    inside.appendChild(insideBox);
    inside.appendChild(_el('span', '', currentRow() ? `Inside ${currentRow().name}` : 'Inside this space'));
    inside.hidden = !currentRow();
    const gap = _el('label', 'apo-check');
    const gapBox = _el('input');
    gapBox.type = 'checkbox';
    gap.appendChild(gapBox);
    gap.appendChild(_el('span', '', 'Airgapped'));
    const make = _el('button', 'apo-btn apo-primary', 'Make');
    make.type = 'submit';
    form.appendChild(input);
    form.appendChild(inside);
    form.appendChild(gap);
    form.appendChild(make);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = input.value.trim();
      if (!name) return;
      try {
        const row = await makeSpace(name, { parentId: insideBox.checked ? _current : null, airgapped: gapBox.checked });
        close();
        await switchTo(row.id);
      } catch (err) { _say(err.message); }
    });
    menu.appendChild(form);
  }

  btn.addEventListener('click', async () => {
    if (!menu.hidden) { close(); return; }
    try { await loadSpaces(); } catch (err) { _say(err.message); }
    draw();
    menu.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
  });
  el.addEventListener('keydown', (e) => { if (e.key === 'Escape') { close(); btn.focus(); } });
  label();
  // A switcher taken out of the page (the chat header is rebuilt on a chat
  // switch) stops listening the next time the space changes.
  let seen = false;
  const relabel = () => {
    if (el.isConnected) seen = true;
    else if (seen) { off(); return; }
    label();
  };
  const offChange = onSpaceChange(relabel);
  _labels.add(relabel);
  const off = () => { offChange(); _labels.delete(relabel); };
  return { el, destroy: () => { off(); close(); } };
}

export { LOCK as LOCK_ICON };
