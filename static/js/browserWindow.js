// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P25-06`. The agent browser's window: watch the agent browse, take it over,
// hand it back.
//
// The owner (2026-10-24): *"we need an agent browser that's in app."* The
// browser is the person's own Firefox in their workstation (`P25-05`); this
// window shows the page itself — frames of the page, not the desktop — with
// its address, back, forward, reload and its tabs, a few frames a second while
// the window is open and the page is visible (`workstationScreen.js`'s rule,
// and its pure parts: `mapPoint`, `keyAction`, `wheelClicks`).
//
// **Two kinds of hand.** The address bar, back, forward, reload and the tabs
// are the person's own explicit acts, and work whenever the window answers.
// Pointing and typing *on the page* only while the person holds it: *Take
// over* is the screen's own (`POST /api/workstation/control`), because the
// browser is on that screen — one holder, and while the person holds it the
// agent's browser calls are refused with the daemon's sentence.
//
// **Every rule is the server's.** Whose browser, whether this person may use
// one, every bound on an action: `routes/workstation_routes.py` and the
// daemon behind it. A refusal is shown in their words. Markup is built with
// `createElement`; no server string is parsed as HTML.

import * as Modals from './modalManager.js?v=20261009census';
import { makeWindowDraggable } from './windowDrag.js';
import { keyAction, mapPoint, wheelClicks } from './workstationScreen.js';

export const MODAL_ID = 'agent-browser-modal';

const TIMING = {
  FRAME_MS: 500,
  HOLDER_MS: 4000,
  RETRY_MS: 5000,
  AFTER_INPUT_MS: 150,
  TYPE_FLUSH_MS: 60,
  WHEEL_FLUSH_MS: 100,
};

const BROWSER_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
  + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
  + 'aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/>'
  + '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>';

const HINT = {
  watching: 'This is the agent\'s browser. Take over to click and type on the page yourself; the agent waits until you hand it back.',
  holding: 'Click the page, then type: your keys go to the browser. Shift+Esc gives the keyboard back to this page.',
};

// xdotool's key names (what `keyAction` answers) as the browser's.
const XDO_TO_BROWSER = {
  Return: 'enter', BackSpace: 'backspace', Tab: 'tab', Escape: 'escape', Delete: 'delete',
  Home: 'home', End: 'end', Prior: 'pageup', Next: 'pagedown', Left: 'left', Right: 'right',
  Up: 'up', Down: 'down', space: 'space', super: 'meta', ctrl: 'ctrl', alt: 'alt', shift: 'shift',
};

/** `keyAction`'s `keys` (`ctrl+l`, `Return`) as the browser route names them,
 *  or null for a key the browser does not take (F-keys, punctuation names). */
export function browserKeys(xdo) {
  const parts = String(xdo || '').split('+').filter(Boolean);
  if (!parts.length) return null;
  const out = [];
  for (const p of parts) {
    if (XDO_TO_BROWSER[p]) out.push(XDO_TO_BROWSER[p]);
    else if (/^[a-z0-9]$/.test(p)) out.push(p);
    else return null;
  }
  return out.join('+');
}

/** What a person typed in the address bar, as an address: a bare name is
 *  https, anything with a scheme is left for the server to judge, and words
 *  that are not an address are '' — Pantheon picks no search engine for
 *  anyone (`Law 16`); the person types the one they use. */
export function addressOf(text) {
  const t = String(text || '').trim();
  if (!t) return '';
  // A scheme is a word and `://` (or about:blank); `localhost:5173` is a host and its port.
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(t) || t === 'about:blank') return t;
  const host = t.split(/[/:?#]/)[0].toLowerCase();
  // A machine on this network is reached as it is served: plain http.
  const local = host === 'localhost' || host.endsWith('.local') || host.endsWith('.lan')
    || /^\d{1,3}(\.\d{1,3}){3}$/.test(host);
  if (local) return `http://${t}`;
  if (/\s/.test(t) || !/\./.test(t)) return '';
  return `https://${t}`;
}

let _win = null;
let _digest = '';
let _size = { w: 1280, h: 800 };
let _holder = null;
let _state = 'checking';
let _timer = null;
let _inFlight = false;
let _soon = false;
let _holderAt = 0;
let _sendChain = Promise.resolve();
let _typed = '';
let _typeTimer = null;
let _wheel = null;
let _editingAddress = false;
let _lastUrl = '';

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text) n.textContent = text;
  return n;
}

function _button(cls, text, onClick, label) {
  const b = _el('button', `memory-toolbar-btn ${cls}`, text);
  b.type = 'button';
  if (label) { b.title = label; b.setAttribute('aria-label', label); }
  b.addEventListener('click', (e) => { e.preventDefault(); onClick(); });
  return b;
}

function _say(text, { error = false } = {}) {
  if (!_win) return;
  _win.statusText.textContent = String(text || '');
  _win.status.dataset.state = error ? 'down' : (_state === 'up' ? 'up' : 'checking');
}

function _shouldPoll() {
  if (!_win || _win.modal.isConnected === false) return false;
  const m = _win.modal;
  if (m.classList.contains('hidden') || m.classList.contains('modal-minimized') || m.style.display === 'none') return false;
  return !(document.visibilityState === 'hidden' || document.hidden === true);
}

async function _detail(res) {
  let detail = `The browser could not be reached (${res.status}).`;
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string' && body.detail) detail = body.detail;
  } catch (_) { /* keep the status */ }
  return detail;
}

function _holding() { return _state === 'up' && _holder === 'person'; }

function _render() {
  if (!_win) return;
  const up = _state === 'up';
  const holding = _holding();
  _win.take.hidden = !up || _holder !== 'agent';
  _win.give.hidden = !holding;
  _win.stage.classList.toggle('abw-held', holding);
  _win.page.classList.toggle('abw-holding', holding);
  _win.page.setAttribute('role', holding ? 'application' : 'img');
  _win.page.setAttribute('aria-label', holding ? 'The page. You have the mouse and keyboard.' : 'The page the agent is on.');
  [_win.back, _win.forward, _win.reload, _win.go].forEach((b) => { b.disabled = !up; });
  _win.address.disabled = !up;
  _win.hint.textContent = up ? (holding ? HINT.holding : HINT.watching) : '';
  _win.hint.hidden = !up;
}

function _drawTabs(tabs) {
  if (!_win) return;
  const row = _win.tabs;
  row.textContent = '';
  (tabs || []).forEach((t) => {
    const tab = _el('div', `abw-tab${t.current ? ' abw-tab-current' : ''}`);
    let label = t.url || 'New tab';
    try { const u = new URL(t.url); label = u.hostname || t.url; } catch (_) { /* keep */ }
    const pick = _button('abw-tab-pick', label, () => _act({ action: 'tab_switch', tab: t.tab }), t.url || 'New tab');
    pick.setAttribute('aria-pressed', String(!!t.current));
    tab.appendChild(pick);
    if ((tabs || []).length > 1) {
      tab.appendChild(_button('abw-tab-close', '×', () => _act({ action: 'tab_close', tab: t.tab }), `Close ${label}`));
    }
    row.appendChild(tab);
  });
  row.appendChild(_button('abw-tab-new', '+', () => _act({ action: 'tab_new' }), 'New tab'));
}

function _showFrame(f) {
  if (!_win || !f || typeof f.data_b64 !== 'string') return;
  if (f.mime !== 'image/png' && f.mime !== 'image/jpeg') return;
  _win.img.src = `data:${f.mime};base64,${f.data_b64}`;
  _digest = typeof f.digest === 'string' ? f.digest : '';
  if (f.width > 0 && f.height > 0) _size = { w: f.width, h: f.height };
  _win.img.hidden = false;
  _win.empty.hidden = true;
  // The page moved: its address is shown, over anything half-typed — a
  // half-typed address for a page that is no longer there is a wrong one.
  if (!_editingAddress || (f.url || '') !== _lastUrl) _win.address.value = f.url || '';
  _lastUrl = f.url || '';
  _win.title.textContent = f.title || 'Agent browser';
  _drawTabs(f.tabs);
}

function _schedule(ms) {
  if (_timer) clearTimeout(_timer);
  _timer = setTimeout(_tick, Math.max(0, ms));
}

function _kick(ms = 0) {
  if (!_shouldPoll()) return;
  if (_inFlight) { _soon = true; return; }
  _schedule(ms);
}

async function _readHolder() {
  try {
    const res = await fetch('/api/workstation/control', { credentials: 'same-origin' });
    if (!res.ok) return;
    const a = await res.json();
    if (a && (a.holder === 'agent' || a.holder === 'person')) _holder = a.holder;
    _holderAt = Date.now();
  } catch (_) { /* the frame loop says so */ }
}

async function _tick() {
  _timer = null;
  if (_inFlight || !_shouldPoll()) return;
  _inFlight = true;
  const started = Date.now();
  let wait = TIMING.FRAME_MS;
  try {
    const url = '/api/workstation/browser' + (_digest ? `?if_none_match=${encodeURIComponent(_digest)}` : '');
    const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (res.status === 304 || res.ok) {
      if (res.ok) _showFrame(await res.json());
      if (_state !== 'up') { _state = 'up'; _say('Your browser, in your workstation.'); }
    } else {
      _state = res.status === 403 ? 'not_permitted' : 'down';
      _say(await _detail(res), { error: true });
      _win.img.hidden = true;
      _win.empty.hidden = false;
      _win.empty.textContent = 'No browser to show.';
      wait = TIMING.RETRY_MS;
    }
    if (_state === 'up' && (_holder === null || Date.now() - _holderAt >= TIMING.HOLDER_MS)) await _readHolder();
    _render();
  } catch (e) {
    _state = 'down';
    _say(`Pantheon could not reach the browser: ${String((e && e.message) || e)}`, { error: true });
    wait = TIMING.RETRY_MS;
  } finally {
    _inFlight = false;
  }
  if (_soon) { _soon = false; wait = Math.min(wait, TIMING.AFTER_INPUT_MS); }
  if (_shouldPoll()) _schedule(wait - (Date.now() - started));
}

/** One of the person's own acts on their browser, in order after the last. */
function _act(body) {
  _sendChain = _sendChain.then(async () => {
    try {
      const res = await fetch('/api/workstation/browser', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!res.ok) _say(await _detail(res), { error: true });
      else _say('');
    } catch (e) {
      _say(`Pantheon could not reach the browser: ${String((e && e.message) || e)}`, { error: true });
    }
    _kick(TIMING.AFTER_INPUT_MS);
  });
  return _sendChain;
}

function _flushTyped() {
  if (_typeTimer) { clearTimeout(_typeTimer); _typeTimer = null; }
  if (!_typed) return;
  const text = _typed;
  _typed = '';
  _act({ action: 'type', text });
}

function _flushWheel() {
  if (!_wheel) return;
  const w = _wheel;
  _wheel = null;
  if (w.timer) clearTimeout(w.timer);
  const dy = wheelClicks(w.dy, w.mode);
  const dx = wheelClicks(w.dx, w.mode);
  if (dx || dy) _act({ action: 'scroll', dx, dy });
}

function _pointAt(ev) {
  return mapPoint(ev.clientX, ev.clientY, _win.img.getBoundingClientRect(), _size.w, _size.h);
}

function _onClick(ev) {
  if (!_holding()) return;
  const p = _pointAt(ev);
  if (!p) return;
  ev.preventDefault();
  try { _win.page.focus(); } catch (_) {}
  _flushTyped();
  _act({ action: 'click', x: p.x, y: p.y, double: ev.detail === 2 || undefined });
}

function _onWheel(ev) {
  if (!_holding()) return;
  ev.preventDefault();
  if (!_wheel) _wheel = { dx: 0, dy: 0, mode: ev.deltaMode || 0, timer: null };
  _wheel.dx += Number(ev.deltaX) || 0;
  _wheel.dy += Number(ev.deltaY) || 0;
  if (!_wheel.timer) _wheel.timer = setTimeout(_flushWheel, TIMING.WHEEL_FLUSH_MS);
}

function _onKeyDown(ev) {
  if (!_holding()) return;
  if (ev.key === 'Escape' && ev.shiftKey) {
    ev.preventDefault();
    _flushTyped();
    try { _win.give.focus(); } catch (_) {}
    return;
  }
  const act = keyAction(ev);
  if (!act) return;
  ev.preventDefault();
  ev.stopPropagation();
  if (act.action === 'type') {
    _typed += act.text;
    if (_typeTimer) clearTimeout(_typeTimer);
    _typeTimer = setTimeout(_flushTyped, TIMING.TYPE_FLUSH_MS);
    return;
  }
  const keys = browserKeys(act.keys);
  if (!keys) return;
  _flushTyped();
  _act({ action: 'press', keys });
}

async function _control(holder) {
  try {
    const res = await fetch('/api/workstation/control', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ holder }),
    });
    if (!res.ok) { _say(await _detail(res), { error: true }); return false; }
    const a = await res.json();
    _holder = a.holder;
    _holderAt = Date.now();
    _say(a.sentence || '');
  } catch (e) {
    _say(`Pantheon could not reach the browser: ${String((e && e.message) || e)}`, { error: true });
    return false;
  }
  _render();
  _kick(0);
  return true;
}

export async function takeOver() {
  const ok = await _control('person');
  if (ok && _win) try { _win.page.focus(); } catch (_) {}
  return ok;
}

export async function handBack() {
  _flushTyped();
  _flushWheel();
  await _sendChain;
  return _control('agent');
}

/** Open an address in the person's browser, as their own act. */
export function openAddress(text) {
  const url = addressOf(text);
  if (!url) {
    if (String(text || '').trim()) _say('That is not an address. Type one, like example.org.', { error: true });
    return Promise.resolve();
  }
  return _act({ action: 'open', url });
}

function _build() {
  const modal = _el('div', 'modal abw-modal');
  modal.id = MODAL_ID;
  const content = _el('div', 'modal-content abw-content');
  const header = _el('div', 'modal-header');
  const h = _el('h4', 'abw-heading');
  const icon = _el('span', 'abw-icon');
  icon.innerHTML = BROWSER_ICON;   // a constant above, never server text
  const title = _el('span', 'abw-title', 'Agent browser');
  h.appendChild(icon);
  h.appendChild(title);
  const close = _el('button', 'close-btn');
  close.type = 'button';
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '✖';
  close.addEventListener('click', (e) => { e.preventDefault(); closeAgentBrowser(); });
  header.appendChild(h);
  header.appendChild(close);

  const tabs = _el('div', 'abw-tabs');
  tabs.setAttribute('role', 'toolbar');
  tabs.setAttribute('aria-label', 'Tabs');

  const bar = _el('form', 'abw-bar');
  const back = _button('abw-nav', '←', () => _act({ action: 'back' }), 'Back');
  const forward = _button('abw-nav', '→', () => _act({ action: 'forward' }), 'Forward');
  const reload = _button('abw-nav', '⟳', () => _act({ action: 'reload' }), 'Reload');
  const address = document.createElement('input');
  address.type = 'text';
  address.className = 'abw-address';
  address.spellcheck = false;
  address.autocomplete = 'off';
  address.placeholder = 'Type an address';
  address.setAttribute('aria-label', 'Address');
  address.addEventListener('focus', () => { _editingAddress = true; address.select(); });
  address.addEventListener('blur', () => { _editingAddress = false; });
  const go = _el('button', 'memory-toolbar-btn abw-go', 'Go');
  go.type = 'submit';
  bar.appendChild(back);
  bar.appendChild(forward);
  bar.appendChild(reload);
  bar.appendChild(address);
  bar.appendChild(go);
  bar.addEventListener('submit', (e) => {
    e.preventDefault();
    _editingAddress = false;
    openAddress(address.value);
    if (typeof address.blur === 'function') address.blur();
  });

  const strip = _el('div', 'abw-strip');
  const status = _el('div', 'ws-status abw-status');
  status.dataset.state = 'checking';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  const dot = _el('span', 'ws-status-dot');
  dot.setAttribute('aria-hidden', 'true');
  const statusText = _el('span', 'ws-status-text', 'Starting the browser…');
  status.appendChild(dot);
  status.appendChild(statusText);
  const take = _button('abw-take', 'Take over', () => { takeOver(); });
  const give = _button('abw-give', 'Hand back', () => { handBack(); });
  take.hidden = true;
  give.hidden = true;
  strip.appendChild(status);
  strip.appendChild(take);
  strip.appendChild(give);

  const stage = _el('div', 'abw-stage');
  const page = _el('div', 'abw-page');
  page.tabIndex = 0;
  const img = _el('img', 'abw-frame');
  img.alt = '';
  img.draggable = false;
  img.hidden = true;
  const empty = _el('div', 'abw-empty', 'Starting your browser — the first time takes a few seconds…');
  page.appendChild(img);
  page.appendChild(empty);
  stage.appendChild(page);
  const hint = _el('p', 'abw-hint');
  hint.hidden = true;

  content.appendChild(header);
  content.appendChild(tabs);
  content.appendChild(bar);
  content.appendChild(strip);
  content.appendChild(stage);
  content.appendChild(hint);
  modal.appendChild(content);

  page.addEventListener('click', _onClick);
  page.addEventListener('wheel', _onWheel, { passive: false });
  page.addEventListener('keydown', _onKeyDown);
  page.addEventListener('blur', _flushTyped);
  img.addEventListener('dragstart', (e) => e.preventDefault());

  return { modal, content, header, title, tabs, back, forward, reload, address, go, status, statusText,
    take, give, stage, page, img, empty, hint };
}

function _teardown() {
  if (!_win) return;
  if (_timer) { clearTimeout(_timer); _timer = null; }
  _flushTyped();
  if (_holder === 'person') {
    fetch('/api/workstation/control', {
      method: 'POST', credentials: 'same-origin', keepalive: true,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ holder: 'agent' }),
    }).catch(() => {});
  }
  const modal = _win.modal;
  _win = null;
  _digest = '';
  _lastUrl = '';
  _holder = null;
  _state = 'checking';
  if (modal.parentNode) modal.parentNode.removeChild(modal);
}

function _resume() {
  _holderAt = 0;
  _kick(0);
}

/** Open the window, or bring it forward; `url` is opened as the person's act. */
export function openAgentBrowser({ url = '', focus = false } = {}) {
  if (_win && Modals.isRegistered(MODAL_ID)) {
    if (Modals.isMinimized(MODAL_ID)) Modals.restore(MODAL_ID);
    else Modals.showWindow(MODAL_ID);
    _resume();
  } else {
    if (_win) _teardown();
    _win = _build();
    document.body.appendChild(_win.modal);
    Modals.register(MODAL_ID, { restoreFn: _resume, closeFn: _teardown });
    Modals.injectMinimizeButton(_win.modal, MODAL_ID);
    makeWindowDraggable(_win.modal, {
      content: _win.content, header: _win.header,
      skipSelector: 'button, input, select, label, form', minWidth: 380, minHeight: 300,
    });
    _render();
    _kick(0);
  }
  if (url) openAddress(url);
  if (focus && _win) try { _win.address.focus(); } catch (_) {}
  return true;
}

export function closeAgentBrowser() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else _teardown();
}

/** Every door — the + menu's *Browser*, a browser tool card's *View browser*
 *  — is a `[data-open-agent-browser]` control, answered here once. */
function _onDoor(ev) {
  const t = ev.target;
  const door = t && typeof t.closest === 'function' ? t.closest('[data-open-agent-browser]') : null;
  if (!door) return;
  ev.preventDefault();
  ev.stopPropagation();
  openAgentBrowser({ focus: ev.detail === 0 });
}

if (typeof document !== 'undefined' && document && typeof document.addEventListener === 'function') {
  document.addEventListener('click', _onDoor, true);
  document.addEventListener('visibilitychange', () => { if (_shouldPoll()) _resume(); });
}

export const _test = {
  TIMING, tick: _tick, win: () => _win, settled: () => _sendChain,
  state: () => ({ open: !!_win, state: _state, holder: _holder, digest: _digest }),
};

export default { openAgentBrowser, closeAgentBrowser, takeOver, handBack, openAddress };
