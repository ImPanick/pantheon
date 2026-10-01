// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P20-05`. A window onto the workstation: watch it, take it over, hand it back.
//
// The person's own workstation screen in a tool window, a few frames a second,
// drawn from the same screenshots the agent sees (`D-2026-09-30-03`: a
// screenshot stream, not VNC — Pantheon serves no websocket). *Take over* gives
// the person the mouse and keyboard: from then on the agent's `computer` calls
// are refused with the daemon's sentence (`busy`), and clicks, keys and the
// wheel on the picture go to the workstation. *Hand back* returns them.
// *Reset to clean* is the Settings panel's own reset, behind its own
// confirmation (`workstation.js`, `confirmAndResetMine`).
//
// **Every rule is the server's.** Whose screen it is, whether this person may
// see it, whether the workstation is on and answering, and every bound on an
// input — all of it is answered by `routes/workstation_routes.py` and the
// daemon behind it; this module shows what they say. A refusal is shown in
// their words, as plain status text, and the window keeps asking slowly so it
// comes back on its own when the workstation does.
//
// **Only while someone is looking.** Frames are asked for one at a time, never
// overlapping, at most every `FRAME_MS`, and only while the window is open, not
// minimized, and the page is visible. A frame the person already has is not
// sent again (`304` on the digest). Who holds the screen is read every
// `HOLDER_MS` — a person can take over from another tab.
//
// **Coordinates.** The picture is drawn at whatever size the window gives it,
// keeping the screen's shape, and a point on it is mapped from that drawn size
// to the screen's own pixels (`mapPoint`) — 1280×800 by the protocol, read off
// each frame rather than assumed.
//
// **The keyboard.** While the person holds the screen and the picture has the
// focus, every key goes to the workstation — Tab and Escape included, because
// a terminal needs both. Shift+Escape gives the keyboard back to the page,
// and the line under the picture says so while it has the focus.
//
// Nothing here animates. The window is a tool window like the others
// (`modalManager` for the minimized dock, `windowDrag` for moving and resizing
// it, from the keyboard too — `P10-06`); its markup is built with
// `createElement`, so no server string is ever parsed as HTML.

import * as Modals from './modalManager.js?v=20261001workbench2';
import { makeWindowDraggable } from './windowDrag.js';
import { confirmAndResetMine } from './workstation.js';

export const MODAL_ID = 'workstation-screen-modal';

// The cadence, in milliseconds. A few frames a second is the row; a frame
// through Pantheon took about 200 ms under load in `P20-01`'s measurement, so
// the loop is paced from the start of one request to the start of the next and
// never runs two at once.
const TIMING = {
  FRAME_MS: 300,          // ~3 frames a second while the screen is changing
  HOLDER_MS: 4000,        // who holds it, re-read this often
  RETRY_MS: 5000,         // asking again after a refusal or a failure
  AFTER_INPUT_MS: 120,    // a frame soon after the person did something
  CLICK_SETTLE_MS: 250,   // a second click inside this is a double click
  TYPE_FLUSH_MS: 40,      // typed characters are sent together
  WHEEL_FLUSH_MS: 80,     // wheel turns are summed, then sent
};
const DRAG_PX = 4;              // further than this between press and release is a drag
const WHEEL_PX_PER_CLICK = 100; // a pixel-mode wheel delta per wheel click
const MAX_WHEEL_CLICKS = 50;    // the protocol's `MAX_SCROLL_CLICKS`; the daemon checks it too

const SCREEN_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
  + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
  + 'aria-hidden="true"><rect x="2" y="3" width="20" height="14" rx="2"/>'
  + '<path d="M8 21h8M12 17v4"/></svg>';

// The lines a person reads under the picture. The sentences about who holds
// the screen come from the server with each answer (`holder_sentence`).
const HINT = {
  watching: 'Take over to use the mouse and keyboard yourself. The agent stops until you hand them back.',
  holding: 'Click the picture, then type: your keys go to the workstation.',
  typing: 'Your keys go to the workstation. Shift+Esc gives the keyboard back to this page.',
};

// ── pure parts (exported for the tests) ──────────────────────────────────────

/**
 * A point on the drawn picture, in the screen's own pixels — or `null` when it
 * is not on the picture. `rect` is the picture's box on the page.
 */
export function mapPoint(clientX, clientY, rect, screenW, screenH) {
  if (!rect || !(rect.width > 0) || !(rect.height > 0)) return null;
  if (!(screenW > 0) || !(screenH > 0)) return null;
  const fx = (clientX - rect.left) / rect.width;
  const fy = (clientY - rect.top) / rect.height;
  if (!(fx >= 0 && fx <= 1 && fy >= 0 && fy <= 1)) return null;
  return {
    x: Math.min(screenW - 1, Math.floor(fx * screenW)),
    y: Math.min(screenH - 1, Math.floor(fy * screenH)),
  };
}

// xdotool's names for the keys a browser names differently. Anything not here
// and not a single character is not sent (`keyAction` answers `null`).
const KEY_NAMES = {
  Enter: 'Return', Backspace: 'BackSpace', Tab: 'Tab', Escape: 'Escape', Delete: 'Delete',
  Insert: 'Insert', Home: 'Home', End: 'End', PageUp: 'Prior', PageDown: 'Next',
  ArrowLeft: 'Left', ArrowRight: 'Right', ArrowUp: 'Up', ArrowDown: 'Down',
  ContextMenu: 'Menu', ' ': 'space',
};
// Punctuation with a modifier held (Ctrl+-, Ctrl+/ …) goes by its keysym: the
// daemon's key syntax is letters, digits, `_`, `+` and `-`.
const PUNCTUATION = {
  '-': 'minus', '=': 'equal', '+': 'plus', '[': 'bracketleft', ']': 'bracketright',
  ';': 'semicolon', "'": 'apostrophe', ',': 'comma', '.': 'period', '/': 'slash',
  '\\': 'backslash', '`': 'grave', ' ': 'space',
};
const MODIFIER_ONLY = new Set(['Shift', 'Control', 'Alt', 'Meta', 'AltGraph', 'CapsLock',
  'NumLock', 'ScrollLock', 'OS', 'Super', 'Hyper', 'Fn', 'Dead', 'Process', 'Unidentified',
  'Compose']);

/**
 * One keydown as the protocol's input: `{ action: 'type', text }` for a
 * character, `{ action: 'key', keys }` for anything with a name or a modifier
 * (`ctrl+l`, `shift+Tab`, `Return`), or `null` when there is nothing to send.
 */
export function keyAction(ev) {
  if (!ev || ev.isComposing) return null;
  const key = typeof ev.key === 'string' ? ev.key : '';
  if (!key || MODIFIER_ONLY.has(key)) return null;
  const altGraph = typeof ev.getModifierState === 'function' && ev.getModifierState('AltGraph');
  const ctrl = !!ev.ctrlKey && !altGraph;
  const alt = !!ev.altKey && !altGraph;
  const meta = !!ev.metaKey;
  if (key.length === 1 && key !== ' ' && !ctrl && !alt && !meta) {
    return { action: 'type', text: key };
  }
  if (key === ' ' && !ctrl && !alt && !meta) return { action: 'type', text: ' ' };
  let name = null;
  if (key.length === 1) {
    if (/^[A-Za-z0-9]$/.test(key)) name = key.toLowerCase();
    else name = PUNCTUATION[key] || null;
  } else if (KEY_NAMES[key]) {
    name = KEY_NAMES[key];
  } else if (/^F([1-9]|1[0-9]|2[0-4])$/.test(key)) {
    name = key;
  }
  if (!name) return null;
  const mods = [];
  if (ctrl) mods.push('ctrl');
  if (alt) mods.push('alt');
  if (meta) mods.push('super');
  // Shift is already in a typed character; with a letter under Ctrl, or with a
  // named key (Shift+Tab), it is part of the chord.
  if (ev.shiftKey && (key.length > 1 || /^[A-Za-z]$/.test(key))) mods.push('shift');
  return { action: 'key', keys: [...mods, name].join('+') };
}

/** Wheel deltas, summed, as whole wheel clicks within the protocol's bound. */
export function wheelClicks(delta, deltaMode) {
  const perClick = deltaMode === 1 ? 3 : (deltaMode === 2 ? 1 / 3 : WHEEL_PX_PER_CLICK);
  const clicks = Math.trunc(delta / perClick) || (delta ? Math.sign(delta) : 0);
  return Math.max(-MAX_WHEEL_CLICKS, Math.min(MAX_WHEEL_CLICKS, clicks));
}

// ── state ────────────────────────────────────────────────────────────────────

let _win = null;          // { modal, content, header, status, statusText, take, give, reset,
                          //   stage, screen, img, empty, hint }
let _digest = '';         // the frame on screen
let _size = { w: 1280, h: 800 };   // the screen's own pixels, from the last frame
let _holder = null;       // 'agent' | 'person' | null (not known yet)
let _state = 'checking';  // 'checking' | 'up' | 'down' | 'off' | 'not_permitted'
let _timer = null;
let _inFlight = false;
let _soon = false;
let _holderAt = 0;
let _holderSentence = '';   // the server's words for who holds it, last said
let _error = false;         // the status line is showing a refusal or a failure
let _sendChain = Promise.resolve();
let _typed = '';
let _typeTimer = null;
let _wheel = null;        // { point, dx, dy, mode, timer }
let _press = null;        // { cx, cy, point }
let _clicks = null;       // { point, cx, cy, count, timer }

function _hidden(node, on) {
  if (node) node.hidden = !!on;
}

function _say(text) {
  if (!_win) return;
  const t = String(text || '');
  if (_win.statusText.textContent !== t) _win.statusText.textContent = t;
}

/** A refusal or a failure, kept on screen until something works again — the
 *  next re-read of who holds the screen does not talk over it. */
function _sayError(text) {
  _error = true;
  _say(text);
}

function _cleared() {
  if (!_error) return;
  _error = false;
  _say(_holderSentence);
}

function _isMinimized() {
  if (!_win) return true;
  const m = _win.modal;
  return m.classList.contains('hidden') || m.classList.contains('modal-minimized')
    || m.style.display === 'none';
}

function _pageHidden() {
  return (typeof document.visibilityState === 'string' && document.visibilityState === 'hidden')
    || document.hidden === true;
}

/** Frames are asked for only while somebody can see them. */
function _shouldPoll() {
  return !!_win && _win.modal.isConnected !== false && !_isMinimized() && !_pageHidden();
}

// ── talking to Pantheon ──────────────────────────────────────────────────────

async function _detail(res) {
  let detail = `The workstation could not be reached (${res.status}).`;
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string' && body.detail) detail = body.detail;
  } catch (_) { /* a non-JSON refusal keeps its status */ }
  return detail;
}

function _stateFor(status) {
  if (status === 403) return 'not_permitted';
  if (status === 409) return 'off';
  return 'down';
}

async function _post(url, body, extra = {}) {
  return fetch(url, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), ...extra,
  });
}

// ── drawing ──────────────────────────────────────────────────────────────────

function _render() {
  if (!_win) return;
  const up = _state === 'up';
  _win.status.dataset.state = up ? 'up' : (_state === 'checking' ? 'checking' : _state);
  const holding = up && _holder === 'person';
  _hidden(_win.take, !up || _holder !== 'agent');
  _hidden(_win.give, !holding);
  _hidden(_win.reset, !up);
  // A picture is shown only while it is the screen as it is: when the
  // workstation stops answering, the last frame goes with it rather than
  // standing under a sentence that says it is down.
  _hidden(_win.stage, !up && _state !== 'checking');
  _win.screen.classList.toggle('wsv-holding', holding);
  _win.stage.classList.toggle('wsv-held', holding);
  _win.screen.setAttribute('role', holding ? 'application' : 'img');
  _win.screen.setAttribute('aria-label', holding
    ? 'The workstation screen. You have the mouse and keyboard.'
    : 'The workstation screen.');
  let hint = '';
  if (up && _holder === 'agent') hint = HINT.watching;
  if (holding) hint = (document.activeElement === _win.screen) ? HINT.typing : HINT.holding;
  _win.hint.textContent = hint;
  _hidden(_win.hint, !hint);
}

function _setUp() {
  const back = _state !== 'up' && _state !== 'checking';
  _state = 'up';
  if (back) {
    // Answering again: the refusal is over, and who holds the screen is read
    // again at once rather than at the next turn of `HOLDER_MS`.
    _error = false;
    _holderAt = 0;
    _say(_holderSentence);
  }
  _render();
}

function _setRefused(state, sentence) {
  _state = state;
  // `_holder` is kept: a person who took over and then lost the workstation
  // for a moment still hands it back when they close the window.
  _holderAt = 0;
  _sayError(sentence);
  _render();
}

function _showFrame(frame) {
  if (!_win || !frame || typeof frame.data_b64 !== 'string') return;
  if (frame.mime !== 'image/jpeg' && frame.mime !== 'image/png') return;
  _win.img.src = `data:${frame.mime};base64,${frame.data_b64}`;
  _digest = typeof frame.digest === 'string' ? frame.digest : '';
  if (frame.width > 0 && frame.height > 0) _size = { w: frame.width, h: frame.height };
  _hidden(_win.img, false);
  _hidden(_win.empty, true);
}

function _applyHolder(answer, { announce = false } = {}) {
  if (!answer) return;
  const before = _holder;
  if (answer.holder === 'agent' || answer.holder === 'person') _holder = answer.holder;
  if (answer.sentence) _holderSentence = answer.sentence;
  _holderAt = Date.now();
  // Said when it changed, when the person just asked for it, or when nothing
  // else is on the line; an error stays until something works again.
  if (announce || _holder !== before || !_error) {
    _error = false;
    _say(_holderSentence);
  }
}

// ── the loop ─────────────────────────────────────────────────────────────────

function _schedule(ms) {
  if (_timer) clearTimeout(_timer);
  _timer = setTimeout(_tick, Math.max(0, ms));
}

/** A frame sooner than the cadence would ask for one — after an input, a take
 *  over or a reset. A request already on its way is followed by another. */
function _kick(ms = 0) {
  if (!_shouldPoll()) return;
  if (_inFlight) { _soon = true; return; }
  _schedule(ms);
}

async function _readHolder() {
  const res = await fetch('/api/workstation/control', { credentials: 'same-origin' });
  if (!res.ok) {
    _setRefused(_stateFor(res.status), await _detail(res));
    return false;
  }
  _applyHolder(await res.json());
  return true;
}

async function _tick() {
  _timer = null;
  if (_inFlight || !_shouldPoll()) return;
  _inFlight = true;
  const started = Date.now();
  let wait = TIMING.FRAME_MS;
  try {
    const url = '/api/workstation/screen'
      + (_digest ? `?if_none_match=${encodeURIComponent(_digest)}` : '');
    const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (res.status === 304) {
      if (_state !== 'up') _setUp();
    } else if (res.ok) {
      _showFrame(await res.json());
      if (_state !== 'up') _setUp();
    } else {
      _setRefused(_stateFor(res.status), await _detail(res));
      wait = TIMING.RETRY_MS;
    }
    if (_state === 'up' && (_holder === null || Date.now() - _holderAt >= TIMING.HOLDER_MS)) {
      if (!(await _readHolder())) wait = TIMING.RETRY_MS;
      _render();
    }
  } catch (e) {
    _setRefused('down', `Pantheon could not reach the workstation: ${String((e && e.message) || e)}`);
    wait = TIMING.RETRY_MS;
  } finally {
    _inFlight = false;
  }
  if (_soon) { _soon = false; wait = Math.min(wait, TIMING.AFTER_INPUT_MS); }
  if (_shouldPoll()) _schedule(wait - (Date.now() - started));
}

// ── the person's input ───────────────────────────────────────────────────────

/** One action to the workstation, in order after the ones before it. */
function _send(body) {
  _sendChain = _sendChain.then(async () => {
    try {
      const res = await _post('/api/workstation/input', body);
      if (!res.ok) _sayError(await _detail(res));
      else _cleared();
    } catch (e) {
      _sayError(`Pantheon could not reach the workstation: ${String((e && e.message) || e)}`);
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
  _send({ action: 'type', text });
}

function _flushWheel() {
  if (!_wheel) return;
  const w = _wheel;
  _wheel = null;
  if (w.timer) clearTimeout(w.timer);
  const dx = wheelClicks(w.dx, w.mode);
  const dy = wheelClicks(w.dy, w.mode);
  if (dx || dy) _send({ action: 'scroll', x: w.point.x, y: w.point.y, dx, dy });
}

function _flushClicks() {
  if (!_clicks) return;
  const c = _clicks;
  _clicks = null;
  if (c.timer) clearTimeout(c.timer);
  const action = c.count >= 3 ? 'triple_click' : (c.count === 2 ? 'double_click' : 'click');
  _send({ action, x: c.point.x, y: c.point.y });
}

function _holding() {
  return _state === 'up' && _holder === 'person';
}

function _pointAt(ev) {
  return mapPoint(ev.clientX, ev.clientY, _win.img.getBoundingClientRect(), _size.w, _size.h);
}

function _onPointerDown(ev) {
  if (!_holding()) return;
  if (ev.button === 1) { ev.preventDefault(); return; }   // no page autoscroll
  if (ev.button !== 0) return;
  const point = _pointAt(ev);
  if (!point) return;
  ev.preventDefault();
  try { _win.screen.focus(); } catch (_) {}
  _flushTyped();
  _press = { cx: ev.clientX, cy: ev.clientY, point };
}

function _onPointerUp(ev) {
  if (!_holding() || ev.button !== 0 || !_press) return;
  const press = _press;
  _press = null;
  const moved = Math.hypot(ev.clientX - press.cx, ev.clientY - press.cy) > DRAG_PX;
  const end = _pointAt(ev);
  if (moved && end) {
    _flushClicks();
    _send({ action: 'drag', x: press.point.x, y: press.point.y, to_x: end.x, to_y: end.y });
    return;
  }
  // A click waits a moment for the next one, so two quick clicks reach the
  // workstation as one double click rather than two clicks a round trip apart.
  if (_clicks && Math.hypot(ev.clientX - _clicks.cx, ev.clientY - _clicks.cy) <= DRAG_PX
      && _clicks.count < 3) {
    clearTimeout(_clicks.timer);
    _clicks.count += 1;
  } else {
    _flushClicks();
    _clicks = { point: press.point, cx: ev.clientX, cy: ev.clientY, count: 1, timer: null };
  }
  _clicks.timer = setTimeout(_flushClicks, TIMING.CLICK_SETTLE_MS);
}

function _onContextMenu(ev) {
  if (!_holding()) return;
  ev.preventDefault();
  const point = _pointAt(ev);
  if (!point) return;
  _flushTyped();
  _flushClicks();
  _send({ action: 'right_click', x: point.x, y: point.y });
}

function _onAuxClick(ev) {
  if (!_holding() || ev.button !== 1) return;
  ev.preventDefault();
  const point = _pointAt(ev);
  if (point) _send({ action: 'middle_click', x: point.x, y: point.y });
}

function _onWheel(ev) {
  if (!_holding()) return;
  const point = _pointAt(ev);
  if (!point) return;
  ev.preventDefault();
  if (!_wheel) _wheel = { point, dx: 0, dy: 0, mode: ev.deltaMode || 0, timer: null };
  _wheel.dx += Number(ev.deltaX) || 0;
  _wheel.dy += Number(ev.deltaY) || 0;
  if (!_wheel.timer) _wheel.timer = setTimeout(_flushWheel, TIMING.WHEEL_FLUSH_MS);
}

function _onKeyDown(ev) {
  if (!_holding()) return;
  if (ev.key === 'Escape' && ev.shiftKey && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
    // The way out, said under the picture while it has the focus.
    ev.preventDefault();
    ev.stopPropagation();
    _flushTyped();
    try { _win.give.focus(); } catch (_) {}
    _render();
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
  _flushTyped();
  _send(act);
}

function _onPaste(ev) {
  if (!_holding()) return;
  const text = ev.clipboardData && typeof ev.clipboardData.getData === 'function'
    ? ev.clipboardData.getData('text/plain') : '';
  ev.preventDefault();
  if (!text) return;
  _flushTyped();
  _send({ action: 'type', text });
}

// ── the controls ─────────────────────────────────────────────────────────────

async function _control(holder) {
  try {
    const res = await _post('/api/workstation/control', { holder });
    if (!res.ok) {
      _sayError(await _detail(res));
      return false;
    }
    _applyHolder(await res.json(), { announce: true });
  } catch (e) {
    _sayError(`Pantheon could not reach the workstation: ${String((e && e.message) || e)}`);
    return false;
  }
  _render();
  _kick(0);
  return true;
}

/** *Take over*: the person has the mouse and keyboard; the agent waits. */
export async function takeOver() {
  const ok = await _control('person');
  if (ok && _win) { try { _win.screen.focus(); } catch (_) {} _render(); }
  return ok;
}

/** *Hand back*: the agent has them again. Anything typed is sent first. */
export async function handBack() {
  _flushTyped();
  _flushClicks();
  _flushWheel();
  await _sendChain;
  const ok = await _control('agent');
  if (ok && _win) { try { _win.take.focus(); } catch (_) {} }
  return ok;
}

/** *Reset to clean*, behind the Settings panel's own confirmation. */
export async function resetToClean() {
  const answer = await confirmAndResetMine();
  if (!answer) return false;
  if (answer.ok) _say(answer.message);
  else _sayError(answer.message);
  if (answer.ok) {
    _digest = '';
    _holder = null;   // the daemon forgets who held it; read it again
    _kick(0);
  }
  return !!answer.ok;
}

// ── the window ───────────────────────────────────────────────────────────────

function _el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text) node.textContent = text;
  return node;
}

function _button(cls, text, onClick) {
  const b = _el('button', `memory-toolbar-btn ${cls}`, text);
  b.type = 'button';
  b.addEventListener('click', (e) => { e.preventDefault(); onClick(); });
  return b;
}

function _build() {
  const modal = _el('div', 'modal wsv-modal');
  modal.id = MODAL_ID;
  const content = _el('div', 'modal-content wsv-content');
  const header = _el('div', 'modal-header');
  const title = _el('h4', 'wsv-title');
  const icon = _el('span', 'wsv-title-icon');
  icon.innerHTML = SCREEN_ICON;   // a constant above, never server text
  title.appendChild(icon);
  title.appendChild(document.createTextNode('Workstation screen'));
  const close = _el('button', 'close-btn');
  close.type = 'button';
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '✖';
  close.addEventListener('click', (e) => { e.preventDefault(); closeWorkstationScreen(); });
  header.appendChild(title);
  header.appendChild(close);

  const bar = _el('div', 'wsv-bar');
  const status = _el('div', 'ws-status wsv-status');
  status.dataset.state = 'checking';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  const dot = _el('span', 'ws-status-dot');
  dot.setAttribute('aria-hidden', 'true');
  const statusText = _el('span', 'ws-status-text', 'Connecting…');
  status.appendChild(dot);
  status.appendChild(statusText);
  const actions = _el('div', 'wsv-actions');
  const take = _button('wsv-take', 'Take over', () => { takeOver(); });
  const give = _button('wsv-give', 'Hand back', () => { handBack(); });
  const reset = _button('wsv-reset', 'Reset to clean…', () => { resetToClean(); });
  take.hidden = true;
  give.hidden = true;
  reset.hidden = true;
  actions.appendChild(take);
  actions.appendChild(give);
  actions.appendChild(reset);
  bar.appendChild(status);
  bar.appendChild(actions);

  const stage = _el('div', 'wsv-stage');
  const screen = _el('div', 'wsv-screen');
  screen.tabIndex = 0;
  screen.setAttribute('role', 'img');
  screen.setAttribute('aria-label', 'The workstation screen.');
  const img = _el('img', 'wsv-frame');
  img.alt = '';
  img.draggable = false;
  img.hidden = true;
  const empty = _el('div', 'wsv-empty', 'Asking the workstation for its screen…');
  screen.appendChild(img);
  screen.appendChild(empty);
  stage.appendChild(screen);
  const hint = _el('p', 'wsv-hint');
  hint.id = 'wsv-hint';
  hint.hidden = true;
  screen.setAttribute('aria-describedby', 'wsv-hint');

  content.appendChild(header);
  content.appendChild(bar);
  content.appendChild(stage);
  content.appendChild(hint);
  modal.appendChild(content);

  screen.addEventListener('pointerdown', _onPointerDown);
  screen.addEventListener('pointerup', _onPointerUp);
  screen.addEventListener('contextmenu', _onContextMenu);
  screen.addEventListener('auxclick', _onAuxClick);
  screen.addEventListener('wheel', _onWheel, { passive: false });
  screen.addEventListener('keydown', _onKeyDown);
  screen.addEventListener('paste', _onPaste);
  screen.addEventListener('focus', _render);
  screen.addEventListener('blur', () => { _flushTyped(); _render(); });
  img.addEventListener('dragstart', (e) => e.preventDefault());

  return { modal, content, header, status, statusText, take, give, reset, stage, screen, img,
    empty, hint };
}

/** Everything the window started, stopped; the screen handed back if this
 *  person still held it — nobody is left holding a screen they cannot see. */
function _teardown() {
  if (!_win) return;
  if (_timer) { clearTimeout(_timer); _timer = null; }
  if (_typeTimer) { clearTimeout(_typeTimer); _typeTimer = null; }
  if (_clicks && _clicks.timer) clearTimeout(_clicks.timer);
  if (_wheel && _wheel.timer) clearTimeout(_wheel.timer);
  _flushTyped();
  _clicks = null;
  _wheel = null;
  _press = null;
  if (_holder === 'person') {
    _post('/api/workstation/control', { holder: 'agent' }, { keepalive: true }).catch(() => {});
  }
  const modal = _win.modal;
  _win = null;
  _digest = '';
  _holder = null;
  _holderSentence = '';
  _error = false;
  _state = 'checking';
  _soon = false;
  if (modal.parentNode) modal.parentNode.removeChild(modal);
}

function _resume() {
  _holderAt = 0;      // whoever held it may have changed while nobody looked
  _kick(0);
}

/**
 * Open the window, or bring it forward: restored from the dock when
 * minimized, raised when already open, built when closed.
 */
export function openWorkstationScreen({ focus = false } = {}) {
  if (_win && Modals.isRegistered(MODAL_ID)) {
    if (Modals.isMinimized(MODAL_ID)) Modals.restore(MODAL_ID);
    else Modals.showWindow(MODAL_ID);
    _resume();
  } else {
    if (_win) _teardown();
    _win = _build();
    document.body.appendChild(_win.modal);
    Modals.register(MODAL_ID, {
      restoreFn: _resume,
      closeFn: _teardown,
    });
    Modals.injectMinimizeButton(_win.modal, MODAL_ID);
    makeWindowDraggable(_win.modal, {
      content: _win.content, header: _win.header,
      skipSelector: 'button, input, select, label', minWidth: 360, minHeight: 280,
    });
    _render();
    _kick(0);
  }
  if (focus && _win) {
    // Opened from the keyboard somewhere `a11y.js` does not watch (a tool
    // card in the chat): the focus goes where it goes for any window.
    const handle = _win.header.querySelector('.window-move-handle');
    try { (handle || _win.take).focus(); } catch (_) {}
  }
  return true;
}

export function closeWorkstationScreen() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else _teardown();
}

// ── always on: the doors, the page's visibility, leaving the page ────────────

/**
 * Every door to the window — a workstation tool card's *View screen*, the
 * Settings panel's *Open the screen* — is a `[data-open-workstation-screen]`
 * control, answered here by one delegated listener, so a door added later
 * needs no wiring. In the capture phase on `document`: the card's own fold
 * listener sits on `document.body` (`chat.js`), and a press on a button in the
 * card's header must open the window without also folding the card.
 */
function _onDoor(ev) {
  const t = ev.target;
  const door = t && typeof t.closest === 'function'
    ? t.closest('[data-open-workstation-screen]') : null;
  if (!door) return;
  ev.preventDefault();
  ev.stopPropagation();
  openWorkstationScreen({ focus: ev.detail === 0 });
}

if (typeof document !== 'undefined' && document && typeof document.addEventListener === 'function') {
  document.addEventListener('click', _onDoor, true);
  document.addEventListener('visibilitychange', () => { if (_shouldPoll()) _resume(); });
}
if (typeof window !== 'undefined' && window && typeof window.addEventListener === 'function') {
  // A person who leaves the page while holding the screen cannot hand it
  // back; the page does, on the way out.
  window.addEventListener('pagehide', () => {
    if (_win && _holder === 'person') {
      _post('/api/workstation/control', { holder: 'agent' }, { keepalive: true }).catch(() => {});
    }
  });
}

export const _test = {
  TIMING, tick: _tick, shouldPoll: _shouldPoll, onDoor: _onDoor,
  state: () => ({ open: !!_win, state: _state, holder: _holder, digest: _digest,
    size: { ..._size }, polling: !!_timer || _inFlight }),
  win: () => _win,
  settled: () => _sendChain,
};

export default { openWorkstationScreen, closeWorkstationScreen, takeOver, handBack, resetToClean };
