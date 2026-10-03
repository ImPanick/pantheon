// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/backStack.js
//
// `P23-01` — one back stack (`D-2026-10-03-01` §2, Doc 2 § 2).
//
// **What was wrong, measured on `9560d50`.** Nothing in `static/` called
// `history.pushState` and nothing listened to `popstate`: the browser's (and the
// phone's) Back button left the app from every screen, opening a window never
// wrote the URL, so a reload forgot it, and six windows had no URL at all
// (NAV-M-1, NAV-M-8, NAV-M-9, CHAT-M-7, SET-M-24, WB-M-1's Back half).
//
// **The model.** The windows on screen are one stack, oldest first, each
// `{ id, from, tab }` — `from` is the window it was opened from and `tab` that
// window's tab at the moment (contract C-NAV, `modalManager.showWindow`). Every
// window that opens pushes ONE history entry whose state carries the whole
// stack, and whose URL names the top window (`/brain`, `/skills`,
// `/settings/shortcuts`, `/workbench/integrations`), with the chat beneath it
// as the `#hash`. So:
//
//   * Back (`popstate`) closes what the entry it lands on does not hold — the
//     top window — through the same close path as ×, so a window that asks
//     before it closes (`B1052`'s *Save / Discard / Keep editing*) still asks;
//     a menu or an inner layer on `escMenuStack.js` is dismissed first, and the
//     entry is put back, so one Back peels one layer exactly as Escape does;
//   * a window closed in the app (×, Escape, `←`, a door) whose push made the
//     current entry takes that entry back off (`history.back()`, a pop this
//     module expects and does not act on); any other close rewrites the current
//     entry in place;
//   * a reload restores the windows the entry names, opener and tab included;
//   * a user chat switch pushes an entry with the same windows and the new
//     `#chat` (`chatSwitched`), so Back is the previous chat (CHAT-U-1).
//
// The stack is read off the page, not told: one `MutationObserver` watches the
// tool windows' own `class`/`style` and their arrival and removal, so a window
// opened by any of its many doors (a sidebar button, the palette, a slash
// command, `ui_control`, a chat link) is on the stack without that door knowing
// this module exists. Only this module calls `pushState` or listens to
// `popstate` (FIX-WAVES C-NAV).
//
// **It never leaves the app by itself.** The only `history.back()` it makes is
// off an entry it pushed in this document (`doc`) above the first (`idx > 0`).

/** Window id → its URL segment. The first spelling is the one written; the
 *  aliases are read (`/memory` was the Brain's route before it had its name,
 *  `/forge` is the label the Cookbook wears, `D-2026-09-18-04`). */
export const ROUTES = {
  'memory-modal': 'brain',
  'skills-modal': 'skills',
  'workbench-modal': 'workbench',
  'settings-modal': 'settings',
  'cookbook-modal': 'cookbook',
  'calendar-modal': 'calendar',
  'gallery-modal': 'gallery',
  'tasks-modal': 'tasks',
  'doclib-modal': 'library',
  'notes-panel': 'notes',
  'email-lib-modal': 'email',
  'research-overlay': 'research',
  'theme-modal': 'theme',
  'compare-model-overlay': 'compare',
};
export const ROUTE_ALIASES = { memory: 'memory-modal', forge: 'cookbook-modal' };

/** The phone drawer (the sidebar over the chat, ≤768px) is a layer too: Back
 *  closes it (NAV-U-7). Not a window; no URL. */
export const DRAWER = 'sidebar-drawer';

/** Windows with no URL of their own that still take a place on the stack, so
 *  Back closes them. */
const UNROUTED = ['custom-preset-modal', 'ge-shortcuts-modal', 'workstation-screen-modal', DRAWER];
export const TRACKED = [...Object.keys(ROUTES), ...UNROUTED];
const _TRACKED = new Set(TRACKED);

/** The element a window id draws: Notes registers `notes-panel` and draws
 *  `#notes-pane` (`notes.js`). */
const ELEMENT_OF = { 'notes-panel': 'notes-pane' };
const _ELEMENT_IDS = new Set(TRACKED.map((id) => ELEMENT_OF[id] || id).concat(['sidebar', 'sidebar-backdrop']));

/** `/brain/rag` → `{ id: 'memory-modal', tab: 'rag' }`; `/` or an unknown path → null. */
export function windowForPath(pathname) {
  const parts = String(pathname || '').split('/').filter(Boolean);
  if (!parts.length) return null;
  const seg = parts[0].toLowerCase();
  const id = ROUTE_ALIASES[seg] || Object.keys(ROUTES).find((k) => ROUTES[k] === seg) || null;
  if (!id) return null;
  let tab = null;
  if (parts[1]) { try { tab = decodeURIComponent(parts[1]); } catch (_) { tab = parts[1]; } }
  return { id, tab };
}

/** The path a stack is at: the top window that has a route, with its tab. */
export function pathFor(wins) {
  for (let i = (wins || []).length - 1; i >= 0; i--) {
    const w = wins[i];
    const seg = w && ROUTES[w.id];
    if (seg) return '/' + seg + (w.tab ? '/' + encodeURIComponent(String(w.tab)) : '');
  }
  return '/';
}

// ── state ─────────────────────────────────────────────────────────────────
const DOC = Math.random().toString(36).slice(2, 10);
const _stack = [];              // [{ id, from, tab }], oldest first
const _pending = new Map();     // id → { from, tab, at } — showWindow before the window is up
const _closing = new Map();     // id → time: a close this module asked for, not yet drawn
let _hooks = {};
let _openers = {};
let _expect = 0;                // pops our own history.back() will cause
let _expectTimer = null;
let _booted = false;
let _restoring = false;
let _idx = 0;
let _syncQueued = false;

const _now = () => Date.now();
const _hist = () => globalThis.history;
const _loc = () => globalThis.location;
const _isOurs = (s) => !!(s && typeof s === 'object' && s.pn === 1 && Array.isArray(s.wins));

/** What the rest of the page provides (`modalManager.js` sets these):
 *  `labelOf(id)`, `tabHooks(id) → { getTab, setTab } | null`,
 *  `closeWindow(id)`, `raise(id)`, `drawBack(id, fromId | null)`,
 *  `dismissTopMenu() → boolean`. */
export function configure(hooks) { _hooks = Object.assign({}, _hooks, hooks || {}); }

/** How to open each window when a reload or Forward needs it: id → `(tab) => void`. */
export function setOpeners(openers) { _openers = Object.assign({}, _openers, openers || {}); }

export function stack() { return _stack.map((e) => ({ id: e.id, from: e.from, tab: e.tab })); }
export function top() { return _stack.length ? _stack[_stack.length - 1].id : null; }
export function isTracked(id) { return _TRACKED.has(id); }

function _el(id) {
  if (typeof document === 'undefined') return null;
  return document.getElementById(ELEMENT_OF[id] || id);
}

/** Is this window on screen now? A window animating shut, minimized to a chip,
 *  or being closed by this module counts as gone. */
export function isOpenNow(id) {
  if (_closing.has(id)) {
    if (_now() - _closing.get(id) < 600) return false;
    _closing.delete(id);
  }
  if (id === DRAWER) {
    const sb = document.getElementById('sidebar');
    const bd = document.getElementById('sidebar-backdrop');
    return !!(sb && bd && !sb.classList.contains('hidden') && bd.classList.contains('visible'));
  }
  const el = _el(id);
  if (!el || el.hidden) return false;
  const cl = el.classList;
  if (cl.contains('hidden') || cl.contains('modal-minimized') || cl.contains('notes-pane-leaving')) return false;
  if (el.style && el.style.display === 'none') return false;
  const content = typeof el.querySelector === 'function' ? el.querySelector('.modal-content') : null;
  if (content && content.classList.contains('modal-closing')) return false;
  return true;
}

function _tabOf(id) {
  try {
    const h = _hooks.tabHooks && _hooks.tabHooks(id);
    const t = h && typeof h.getTab === 'function' ? h.getTab() : null;
    return t == null || t === '' ? null : String(t);
  } catch (_) { return null; }
}

function _setTab(id, tab) {
  if (tab == null) return;
  try {
    const h = _hooks.tabHooks && _hooks.tabHooks(id);
    if (h && typeof h.setTab === 'function') h.setTab(tab);
  } catch (_) { /* the window keeps the tab it is on */ }
}

function _zOf(id) {
  const el = _el(id);
  return (el && parseInt(el.style && el.style.zIndex, 10)) || 0;
}

/** `C-NAV`: `showWindow(id, { from, tab })` lands here. With the window already
 *  on the stack the opener is written now; otherwise when it comes up. */
export function noteOpener(id, from, tab) {
  if (!id || !from || from === id) return;
  const t = tab != null ? tab : _tabOf(from);
  const e = _stack.find((x) => x.id === id);
  if (e) {
    e.from = from; e.tab = t;
    _drawBack(e);
    _queueSync();
    return;
  }
  _pending.set(id, { from, tab: t, at: _now() });
}

function _drawBack(e) {
  try {
    if (_hooks.drawBack) _hooks.drawBack(e.id, e.from && isOpenNow(e.from) ? e.from : null);
  } catch (_) { /* a header we cannot draw into keeps its own buttons */ }
}

// ── the stack, read off the page ─────────────────────────────────────────
/** Bring `_stack` in line with what is on screen; returns `{ opened, closed }`. */
function _readPage() {
  const opened = [];
  const closed = [];
  for (let i = _stack.length - 1; i >= 0; i--) {
    if (!isOpenNow(_stack[i].id)) closed.push(_stack.splice(i, 1)[0]);
  }
  const fresh = TRACKED.filter((id) => !_stack.some((e) => e.id === id) && isOpenNow(id))
    .sort((a, b) => _zOf(a) - _zOf(b));
  for (const id of fresh) {
    const p = _pending.get(id);
    _pending.delete(id);
    const e = { id, from: null, tab: null };
    if (p && _now() - p.at < 5000 && p.from !== id && isOpenNow(p.from)) { e.from = p.from; e.tab = p.tab; }
    _stack.push(e);
    opened.push(e);
  }
  for (const e of closed) {
    // Its `←` goes with it; a window it opened loses its way back to it.
    try { if (_hooks.drawBack) _hooks.drawBack(e.id, null); } catch (_) {}
    for (const x of _stack) if (x.from === e.id) { x.from = null; x.tab = null; _drawBack(x); }
    // C-NAV: closing a window opened from another re-raises the opener on the
    // tab it was on (`setTab(tab)`) — Skills → `← Brain` lands on RAG.
    if (e.from && isOpenNow(e.from)) {
      try { if (_hooks.raise) _hooks.raise(e.from); } catch (_) {}
      _setTab(e.from, e.tab);
      _focusHandle(e.from);
    }
  }
  for (const e of opened) _drawBack(e);
  return { opened, closed };
}

function _focusHandle(id) {
  const el = _el(id);
  const handle = el && typeof el.querySelector === 'function'
    ? el.querySelector('.window-move-handle, .modal-header [tabindex], .modal-header button') : null;
  if (handle && typeof handle.focus === 'function') { try { handle.focus({ preventScroll: true }); } catch (_) {} }
}

function _stateFor(opened) {
  return {
    pn: 1, doc: DOC, idx: _idx,
    // `tab` is the window's own tab (the URL's `/settings/<tab>`); `fromTab`
    // the opener's at the moment it opened this one, which closing re-raises.
    wins: _stack.map((e) => ({ id: e.id, from: e.from || null, tab: _tabOf(e.id),
      fromTab: e.from ? (e.tab == null ? null : e.tab) : null })),
    opened: opened || null,
  };
}

function _urlFor(wins) {
  const loc = _loc();
  return pathFor(wins) + ((loc && loc.search) || '') + ((loc && loc.hash) || '');
}

function _write(kind, state) {
  const h = _hist();
  if (!h) return;
  const url = _urlFor(state.wins);
  try {
    if (kind === 'push') h.pushState(state, '', url);
    else h.replaceState(state, '', url);
  } catch (_) { /* a sandboxed frame without history keeps the old URL */ }
  _remember();
}

const _ids = (wins) => (wins || []).map((w) => w.id);
const _prefix = (a, b) => a.every((x, i) => b[i] === x);
const _sameWins = (a, b) => a.length === b.length && a.every((w, i) => w.id === b[i].id
  && (w.from || null) === (b[i].from || null) && (w.tab || null) === (b[i].tab || null)
  && (w.fromTab || null) === (b[i].fromTab || null));

function _current() {
  const h = _hist();
  return h && _isOurs(h.state) ? h.state : null;
}

/** Reconcile the history entry with the stack. Runs after every change the
 *  observer sees, after a popstate, and on a tab change in a window. */
export function sync() {
  _syncQueued = false;
  _readPage();
  if (!_booted || _restoring || _expect > 0) return;
  const cur = _current();
  const curIds = cur ? _ids(cur.wins) : [];
  const ids = _ids(_stack);
  if (cur) _idx = cur.idx;
  // Opened on top of what the entry holds: one entry per window.
  if (ids.length > curIds.length && _prefix(curIds, ids)) {
    for (let n = curIds.length + 1; n <= ids.length; n++) {
      _idx += 1;
      const s = _stateFor(ids[n - 1]);
      s.wins = s.wins.slice(0, n);
      _write('push', s);
    }
    return;
  }
  // The window whose push made this entry has closed: take the entry back off.
  // Off an entry this document pushed only, never the first — so this never
  // leaves the app or reloads a page an older document pushed.
  if (cur && ids.length === curIds.length - 1 && _prefix(ids, curIds)
      && cur.opened === curIds[curIds.length - 1] && cur.doc === DOC && cur.idx > 0) {
    _expectPop();
    try { _hist().back(); } catch (_) { _expect = 0; }
    return;
  }
  const next = _stateFor(cur && cur.opened && ids[ids.length - 1] === cur.opened ? cur.opened : null);
  if (cur && cur.doc !== DOC) next.doc = cur.doc;
  const loc = _loc();
  const url = _urlFor(next.wins);
  const here = loc ? loc.pathname + (loc.search || '') + (loc.hash || '') : url;
  if (cur && _sameWins(cur.wins, next.wins) && url === here && cur.opened === next.opened) return;
  _write('replace', next);
}

function _queueSync() {
  if (_syncQueued) return;
  _syncQueued = true;
  const run = () => { try { sync(); } catch (e) { console.warn('back stack:', e); } };
  if (typeof queueMicrotask === 'function') queueMicrotask(run); else setTimeout(run, 0);
}

function _expectPop() {
  _expect += 1;
  clearTimeout(_expectTimer);
  // A traversal the browser drops (a sandboxed frame, a page being unloaded)
  // must not leave the stack waiting for ever.
  _expectTimer = setTimeout(() => { if (_expect) { _expect = 0; _queueSync(); } }, 1500);
}

// ── Back ─────────────────────────────────────────────────────────────────
let _lastEntry = null;   // { state, url } of the entry we were on before a pop

function _remember() {
  const h = _hist();
  const loc = _loc();
  if (!h || !loc) return;
  _lastEntry = { state: _isOurs(h.state) ? h.state : null, url: loc.pathname + (loc.search || '') + (loc.hash || '') };
}

/** Put back the entry a Back just took off, because Back only peeled an inner
 *  layer (or a window asked first and is still open). */
function _keepEntry(prev) {
  if (!prev || !prev.state) return;
  try { _hist().pushState(prev.state, '', prev.url); } catch (_) {}
}

export function onPopState(ev) {
  const prev = _lastEntry;
  const landing = ev && _isOurs(ev.state) ? ev.state : null;
  if (_expect > 0) {
    _expect -= 1;
    if (!_expect) clearTimeout(_expectTimer);
    _remember();
    sync();
    _remember();
    return;
  }
  const forward = !!(landing && prev && prev.state && landing.idx > prev.state.idx);
  if (!forward) {
    // One Back peels one layer, like Escape: a menu, a panel, a form on the
    // Escape stack goes first and the window stays.
    let peeled = false;
    try { peeled = !!(_hooks.dismissTopMenu && _hooks.dismissTopMenu()); } catch (_) {}
    if (peeled) { _keepEntry(prev); _remember(); return; }
    const want = new Set(landing ? _ids(landing.wins) : []);
    const goes = _stack.slice().reverse().filter((e) => !want.has(e.id));
    for (const e of goes) {
      try { if (_hooks.closeWindow) _hooks.closeWindow(e.id); } catch (_) {}
      if (isOpenNow(e.id)) {
        // It asked before closing (`B1052`): the entry stays, with the window.
        _keepEntry(prev);
        _remember();
        return;
      }
      _closing.set(e.id, _now());
      setTimeout(_queueSync, 650);
    }
  } else {
    _restore(landing.wins.filter((w) => !isOpenNow(w.id)));
  }
  _remember();
  _queueSync();
}

// ── reload / Forward ─────────────────────────────────────────────────────
function _waitOpen(id, ms = 2500) {
  return new Promise((resolve) => {
    const t0 = _now();
    const tick = () => {
      if (isOpenNow(id)) return resolve(true);
      if (_now() - t0 > ms) return resolve(false);
      setTimeout(tick, 50);
    };
    tick();
  });
}

async function _restore(wins) {
  if (!wins || !wins.length) return;
  _restoring = true;
  try {
    for (const w of wins) {
      const open = _openers[w.id];
      if (typeof open !== 'function') continue;
      const fromTab = w.fromTab == null ? null : w.fromTab;
      if (w.from) noteOpener(w.id, w.from, fromTab);
      try { await open(w.tab || null); } catch (e) { console.warn('could not reopen', w.id, e); continue; }
      if (await _waitOpen(w.id)) {
        _readPage();
        const e = _stack.find((x) => x.id === w.id);
        // Its opener and the opener's tab, as they were when it was opened.
        if (e && w.from && isOpenNow(w.from)) { e.from = w.from; e.tab = fromTab; _drawBack(e); }
        // Its own tab.
        if (w.tab) _setTab(w.id, w.tab);
      }
    }
  } finally {
    _restoring = false;
    _queueSync();
  }
}

/** Open these windows, in order, each on its tab and with its opener — a link
 *  to `/brain/rag` or `/settings/shortcuts`, a reload, Forward. */
export function openWindows(wins) { return _restore((wins || []).filter((w) => w && !isOpenNow(w.id))); }

/**
 * Called once the app has wired its modules (`app.js`, through the startup
 * shell's deferred route opener). With an entry this module wrote — a reload,
 * or a Back into a page an older document pushed — the windows it names are
 * opened again and `true` comes back; otherwise the caller runs its deep-link
 * opener for the path.
 */
export function restoreFromHistory() {
  const h = _hist();
  const st = h && _isOurs(h.state) ? h.state : null;
  if (!st || !st.wins.length) return false;
  _restore(st.wins.slice());
  return true;
}

// ── chats ────────────────────────────────────────────────────────────────
/** `sessions.js` calls this when the chat in the URL changes. A user's switch
 *  from one chat to another is a push (Back = the previous chat); the first
 *  chat of a load, a new chat materialising and a switch Back itself made are
 *  a replace. */
export function chatSwitched(id, { push = false } = {}) {
  const h = _hist();
  const loc = _loc();
  if (!h || !loc || !id) return;
  const url = loc.pathname + (loc.search || '') + '#' + id;
  const cur = _current();
  try {
    if (push && _booted && !_restoring && _expect === 0) {
      _readPage();
      _idx = (cur ? cur.idx : _idx) + 1;
      const s = _stateFor(null);
      h.pushState(s, '', url);
    } else {
      h.replaceState(cur || _stateFor(null), '', url);
    }
  } catch (_) { /* keep the URL it had */ }
  _remember();
}

// ── wiring ───────────────────────────────────────────────────────────────
let _inited = false;

/** Install the listeners and stamp the first entry. Idempotent. */
export function init() {
  if (_inited || typeof window === 'undefined' || typeof document === 'undefined') return;
  _inited = true;
  const h = _hist();
  // Six callers rewrite the URL with `replaceState(null, …)` to drop a hash or
  // a query (`sessions.js`, `chatRenderer.js`, `emailInbox.js`, `settings.js`,
  // `group.js`): they mean the URL, not the state, and a `null` would wipe the
  // stack this entry holds. Their URL is kept; the stack stays.
  if (h && typeof h.replaceState === 'function' && !h.replaceState._pantheonBack) {
    const native = h.replaceState;
    const keep = function replaceState(state, title, url) {
      if (state == null && _isOurs(this.state)) state = this.state;
      return native.call(this, state, title, url);
    };
    keep._pantheonBack = true;
    try { h.replaceState = keep; } catch (_) {}
  }
  const cur = _current();
  if (cur) { _idx = cur.idx; } else {
    _idx = 0;
    try { h.replaceState({ pn: 1, doc: DOC, idx: 0, wins: [], opened: null }, '', _loc().href); } catch (_) {}
  }
  _remember();
  window.addEventListener('popstate', onPopState);
  if (typeof MutationObserver === 'function') {
    new MutationObserver((muts) => {
      for (const m of muts) {
        const t = m.target;
        if (m.type === 'attributes') {
          if (t && (_ELEMENT_IDS.has(t.id) || (t.classList && t.classList.contains('modal-content')
              && t.parentNode && _ELEMENT_IDS.has(t.parentNode.id)))) { _queueSync(); return; }
        } else {
          for (const n of m.addedNodes) if (n && _ELEMENT_IDS.has(n.id)) { _queueSync(); return; }
          for (const n of m.removedNodes) if (n && _ELEMENT_IDS.has(n.id)) { _queueSync(); return; }
        }
      }
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style', 'hidden'] });
  }
  // A tab picked inside a window rewrites the URL (`/settings/shortcuts`), with
  // no new entry: Back closes the window, it does not walk its tabs.
  const tabChanged = (e) => {
    const t = e && e.target;
    if (!_stack.length || !t || typeof t.closest !== 'function') return;
    if (t.closest('.modal, .notes-pane')) setTimeout(_queueSync, 0);
  };
  document.addEventListener('click', tabChanged, true);
  document.addEventListener('keyup', tabChanged, true);
}

/** The app has wired its modules: from here on, a change is written. */
export function ready() {
  _booted = true;
  _queueSync();
}

/** Tests only: start again. */
export function _reset() {
  _stack.length = 0; _pending.clear(); _closing.clear();
  _hooks = {}; _openers = {}; _expect = 0; _booted = false; _restoring = false; _idx = 0;
  _syncQueued = false; _lastEntry = null; _inited = false;
}
export const _DOC = DOC;

const backStack = {
  ROUTES, ROUTE_ALIASES, TRACKED, DRAWER, windowForPath, pathFor, configure, setOpeners, stack, top,
  isTracked, isOpenNow, noteOpener, sync, onPopState, restoreFromHistory, openWindows, chatSwitched, init, ready,
};
export default backStack;
