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
// `P25-10`. **Browse it yourself.** The owner (2026-10-25): *"Give the users
// control of the in-application's browser too … navigate freely and tell the
// agent 'This is the page I am talking about.'"* A click or a scroll on the
// page while the agent is idle — no reply running, no step in the last few
// seconds — takes the browser as *Take over* would, and the click lands. While
// the agent is working it still asks for *Take over* or *Stop*: a page moving
// under its hand would make its next step wrong. Sending a message hands the
// browser back (not after *Stop*, which stays the person's until they say),
// so the agent can act on what the message asks. *Point at…* and *This page*
// say which element or page the person means: the daemon keeps it for the
// agent's `inspect` (`pointed: true`) and the composer gets a line naming it,
// with a picture, for the person to finish and send.
//
// `P25-11` / `P25-12`. **Watch it look and think.** An inspection outlines
// what it looked at; every step shows the agent's own *why* under its words;
// and the reply's live reasoning (`chat.js`, `pantheon:live-thinking`) runs in
// a strip under the page while the window is open.
//
// **Every rule is the server's.** Whose browser, whether this person may use
// one, every bound on an action: `routes/workstation_routes.py` and the
// daemon behind it. A refusal is shown in their words. Markup is built with
// `createElement`; no server string is parsed as HTML.

import * as Modals from './modalManager.js?v=20261009census';
import { makeWindowDraggable } from './windowDrag.js';
import { keyAction, mapPoint, wheelClicks } from './workstationScreen.js';
import { createNotes, cropBox } from './pageNotes.js';

export const MODAL_ID = 'agent-browser-modal';

const TIMING = {
  FRAME_MS: 500,
  BUSY_FRAME_MS: 200,     // `P25-07`: while the agent's hand is moving
  BUSY_FOR_MS: 4000,      // how long after its last action it counts as moving
  CAPTION_MS: 1800,       // how long a finished action's caption stays
  GLIDE_MS: 420,          // the hand's glide to where it acts
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

// `P25-07`. The agent's pointer: an arrow in the theme's own accent (its colour
// is `.abw-hand`'s, in the stylesheet), outlined in the panel colour so it reads
// on any page in any theme.
const HAND_SVG = '<svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">'
  + '<path d="M4 2.5 L4 19 L8.6 14.8 L11.6 21.5 L14.4 20.3 L11.4 13.7 L17.6 13.4 Z" '
  + 'fill="currentColor" stroke="var(--panel)" stroke-width="1.6" stroke-linejoin="round"/></svg>';

const HINT = {
  watching: 'Browse here yourself: click or scroll the page whenever the agent is idle. Point at… or This page tells the agent which one you mean.',
  busy: 'The agent is using the browser. Take over or Stop to use it yourself.',
  holding: 'You have the browser: click the page, then type. Sending a message hands it back to the agent. Shift+Esc gives the keyboard back to this page.',
  pointing: 'Click what you mean on the page — or press This page.',
};
const THINKING_SHOWN = 1200;   // `P25-12`: the tail of the live reasoning shown

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
// `P25-07`. What the browser has done that this window has drawn, and the hand.
let _since = 0;
let _lastAgentAt = 0;
let _hand = { x: null, y: null };
let _captionTimer = null;
let _feed = [];             // [{id, label, phase, who}], newest first
let _stopped = false;
const FEED_KEPT = 6;
let _lastUrl = '';
let _notes = null;           // `P26-01`: the notes layer (`pageNotes.js`)
let _chatBusy = false;       // `P25-10`: a reply is running (`chat.js`)
let _pointing = false;       // `P25-10`: the next click on the page says *this*
let _thinking = '';          // `P25-12`: the reply's live reasoning
let _boxTimer = null;

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

/** `P25-10`. The agent is not acting: no reply running, no step lately. */
export function agentIdle() {
  return !_chatBusy && Date.now() - _lastAgentAt >= TIMING.BUSY_FOR_MS;
}

function _render() {
  if (!_win) return;
  const up = _state === 'up';
  const holding = _holding();
  _win.take.hidden = !up || _holder !== 'agent';
  _win.give.hidden = !holding;
  _win.stop.hidden = !up || holding;
  if (holding) _win.hand.hidden = true;
  _win.stage.classList.toggle('abw-held', holding);
  _win.page.classList.toggle('abw-holding', holding);
  _win.page.setAttribute('role', holding ? 'application' : 'img');
  _win.page.setAttribute('aria-label', holding ? 'The page. You have the mouse and keyboard.' : 'The page the agent is on.');
  [_win.back, _win.forward, _win.reload, _win.go].forEach((b) => { b.disabled = !up; });
  _win.address.disabled = !up;
  _win.hint.textContent = !up ? '' : (_pointing ? HINT.pointing
    : (holding ? HINT.holding : (agentIdle() || _stopped ? HINT.watching : HINT.busy)));
  _win.hint.hidden = !up;
  _win.point.disabled = !up;
  _win.pointPage.disabled = !up;
  _win.point.setAttribute('aria-pressed', String(_pointing));
  _win.page.classList.toggle('abw-pointing', _pointing);
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
  if (_notes) _notes.onFrame();   // `P26-01`: where the notes' elements are now
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

// ── `P25-07`: the agent's hand, its words, its trail ──────────────────────────

/** A point on the page (the frame's own pixels) as a place on the drawn picture,
 *  relative to the page box — `mapPoint` the other way round. */
export function placeOf(x, y, imgRect, pageRect, w, h) {
  if (!imgRect || !pageRect || !(imgRect.width > 0) || !(w > 0) || !(h > 0)) return null;
  return {
    left: imgRect.left - pageRect.left + (x / w) * imgRect.width,
    top: imgRect.top - pageRect.top + (y / h) * imgRect.height,
  };
}

/** The theme's accent, as the hand's colour — read from the page's own
 *  tokens each time, so a theme change is followed. */
function _handColour() {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
    return v || '';
  } catch (_) { return ''; }
}

function _moveHand(x, y) {
  if (!_win || x == null || y == null) return;
  const colour = _handColour();
  if (colour) { _win.hand.style.color = colour; _win.caption.style.color = ''; }
  const at = placeOf(x, y, _win.img.getBoundingClientRect(), _win.page.getBoundingClientRect(), _size.w, _size.h);
  if (!at) return;
  _hand = { x, y };
  _win.hand.hidden = false;
  _win.hand.style.transform = `translate(${Math.round(at.left)}px, ${Math.round(at.top)}px)`;
}

/** `P25-11`. What an inspection looked at, outlined on the picture. */
function _outline(box) {
  if (!_win) return;
  const ir = _win.img.getBoundingClientRect();
  const pr = _win.page.getBoundingClientRect();
  const a = placeOf(box[0], box[1], ir, pr, _size.w, _size.h);
  const b = placeOf(box[0] + box[2], box[1] + box[3], ir, pr, _size.w, _size.h);
  if (!a || !b) return;
  const o = _win.outline;
  o.style.color = _handColour() || '';
  o.style.left = `${Math.round(a.left)}px`;
  o.style.top = `${Math.round(a.top)}px`;
  o.style.width = `${Math.max(2, Math.round(b.left - a.left))}px`;
  o.style.height = `${Math.max(2, Math.round(b.top - a.top))}px`;
  o.hidden = false;
  if (_boxTimer) clearTimeout(_boxTimer);
  _boxTimer = setTimeout(() => { if (_win) _win.outline.hidden = true; }, TIMING.CAPTION_MS * 2);
}

function _ripple(x, y) {
  if (!_win) return;
  const at = placeOf(x, y, _win.img.getBoundingClientRect(), _win.page.getBoundingClientRect(), _size.w, _size.h);
  if (!at) return;
  const r = _el('span', 'abw-ripple');
  r.style.color = _win.hand.style.color || '';
  r.style.left = `${Math.round(at.left)}px`;
  r.style.top = `${Math.round(at.top)}px`;
  _win.page.appendChild(r);
  setTimeout(() => { if (r.parentNode) r.parentNode.removeChild(r); }, 700);
}

function _caption(text, phase, why) {
  if (!_win) return;
  const c = _win.caption;
  c.textContent = text;
  // `P25-12`: the agent's own sentence for why, under what it does.
  if (why) c.appendChild(_el('span', 'abw-caption-why', why));
  c.dataset.phase = phase;
  c.hidden = false;
  if (_captionTimer) { clearTimeout(_captionTimer); _captionTimer = null; }
  if (phase !== 'doing') _captionTimer = setTimeout(() => { if (_win) _win.caption.hidden = true; }, TIMING.CAPTION_MS);
}

function _drawFeed() {
  if (!_win) return;
  const list = _win.feed;
  list.textContent = '';
  _feed.forEach((f) => {
    const li = _el('li', `abw-step abw-step-${f.phase}`);
    li.appendChild(_el('span', 'abw-step-mark', f.phase === 'doing' ? '…' : (f.phase === 'failed' ? '!' : '✓')));
    li.appendChild(_el('span', 'abw-step-who', f.who === 'person' ? 'You' : 'Agent'));
    li.appendChild(_el('span', 'abw-step-label', f.label));
    if (f.why) li.appendChild(_el('span', 'abw-step-why', f.why));
    list.appendChild(li);
  });
  _win.feed.hidden = !_feed.length;
}

/** What the browser did since this window last looked, drawn as it was done:
 *  the hand glides to where it acts, says what it is doing, and a click
 *  ripples where it landed. Only the agent's hand is drawn — the person's
 *  own is theirs. */
export function applyActivity(entries) {
  (entries || []).forEach((a) => {
    const known = _feed.find((f) => f.id === a.id);
    if (known) { known.phase = a.phase; known.label = a.label; known.why = a.why || known.why || ''; }
    else _feed.unshift({ id: a.id, label: a.label, phase: a.phase, who: a.who, why: a.why || '' });
    if (a.seq > _since) _since = a.seq;
    if (a.who !== 'agent') return;
    _lastAgentAt = Date.now();
    if (a.x != null && a.y != null) _moveHand(a.x, a.y);
    if (Array.isArray(a.box) && a.box.length === 4) _outline(a.box);
    _caption(a.label, a.phase, a.why);
    if (a.phase === 'done' && a.action === 'click' && a.x != null) _ripple(a.x, a.y);
  });
  _feed = _feed.slice(0, FEED_KEPT);
  _drawFeed();
  if (_win) _win.modal.classList.toggle('abw-agent-busy', Date.now() - _lastAgentAt < TIMING.BUSY_FOR_MS);
}

/** *Stop*: the browser is taken from the agent at once — every call it makes
 *  after this is refused — and the reply on screen is stopped too. Handing
 *  it back is the person's own, later, act. */
export async function emergencyStop() {
  _stopped = true;
  document.dispatchEvent(new CustomEvent('pantheon-stop-reply'));
  const ok = await _control('person');
  if (_win) {
    _win.caption.hidden = true;
    _say(ok ? 'Stopped. The agent cannot use the browser until you hand it back.'
      : 'The reply was stopped, but the browser did not answer: it may still be finishing one step.', { error: !ok });
  }
  return ok;
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
    const q = [`since=${_since}`];
    if (_digest) q.push(`if_none_match=${encodeURIComponent(_digest)}`);
    const url = `/api/workstation/browser?${q.join('&')}`;
    const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (res.status === 304 || res.ok) {
      if (res.ok) {
        const f = await res.json();
        _showFrame(f);
        applyActivity(f.activity);
      }
      if (Date.now() - _lastAgentAt < TIMING.BUSY_FOR_MS) wait = TIMING.BUSY_FRAME_MS;
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

/** `P25-10`. The page is the person's to use when the agent is idle: the
 *  first click or scroll takes it, as *Take over* does. Answers whether they
 *  hold it now. */
async function _takeIfIdle() {
  if (_holding()) return true;
  if (_state !== 'up' || _holder !== 'agent') return false;
  if (!agentIdle()) { _say(HINT.busy); return false; }
  return _control('person');
}

async function _onClick(ev) {
  const p = _pointAt(ev);
  if (_pointing) {
    if (!p) return;
    ev.preventDefault();
    _pointing = false;
    _render();
    await pointAt({ x: p.x, y: p.y });
    return;
  }
  if (!_holding()) {
    if (!p) return;
    ev.preventDefault();
    if (!(await _takeIfIdle())) return;
  }
  if (!p) return;
  ev.preventDefault();
  try { _win.page.focus(); } catch (_) {}
  _flushTyped();
  _act({ action: 'click', x: p.x, y: p.y, double: ev.detail === 2 || undefined });
}

function _onWheel(ev) {
  if (!_holding()) {
    // `P25-10`: a scroll while the agent is idle takes the page; this
    // wheel's distance is the first of what follows.
    if (_state === 'up' && _holder === 'agent' && agentIdle()) {
      ev.preventDefault();
      _takeIfIdle();
    }
    return;
  }
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
  _stopped = false;
  _flushTyped();
  _flushWheel();
  await _sendChain;
  return _control('agent');
}

// ── `P25-10`: "this is the page I mean" ──────────────────────────────────────

/** The line the composer gets for what the person pointed at. */
export function pointMessage(p) {
  if (!p) return '';
  const page = `${p.title ? `“${p.title}”` : 'the page'}${p.url ? ` (${p.url})` : ''}`;
  const what = p.page ? `this page, ${page}` : `<${p.tag || 'element'}>${p.text ? ` “${p.text}”` : ''} on ${page}`;
  return `[In the browser I am pointing at ${what} — agent_browser inspect with pointed: true reads it.]`;
}

/** Put the reference into the composer, before what is already typed (a
 *  reference already there is replaced), with a picture of it; not sent. */
async function _intoComposer(p) {
  const box = document.getElementById('message');
  if (!box) { _say('There is no chat to point the agent from.', { error: true }); return false; }
  try {
    if (_win && _win.img.naturalWidth > 0 && typeof document.createElement('canvas').getContext === 'function') {
      const c = cropBox(p.page ? null : p.box, _win.img.naturalWidth, _win.img.naturalHeight);
      const canvas = document.createElement('canvas');
      canvas.width = c.w;
      canvas.height = c.h;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.drawImage(_win.img, c.x, c.y, c.w, c.h, 0, 0, c.w, c.h);
        if (!p.page && p.box) {
          const k = _win.img.naturalWidth / (_size.w || _win.img.naturalWidth);
          ctx.strokeStyle = _handColour() || '#e5484d';
          ctx.lineWidth = 3;
          ctx.strokeRect(p.box[0] * k - c.x, p.box[1] * k - c.y, p.box[2] * k, p.box[3] * k);
        }
        const blob = await new Promise((r) => canvas.toBlob(r, 'image/png'));
        const fh = await import('./fileHandler.js?v=20261009census');
        if (blob && typeof fh.addFiles === 'function') {
          await fh.addFiles([new File([blob], 'pointed.png', { type: 'image/png' })], { skipCrop: true });
        }
      }
    }
  } catch (_) { /* the words still go in; the picture is a help, not the reference */ }
  const line = pointMessage(p);
  const rest = String(box.value || '').replace(/^\[In the browser I am pointing at [^\n]*\]\n*/, '');
  box.value = `${line}\n${rest}`;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  try { box.focus(); box.setSelectionRange(box.value.length, box.value.length); } catch (_) {}
  return true;
}

/** Point at the element under `{x, y}` (page pixels), or `{page: true}`. */
export async function pointAt(where) {
  _pointing = false;
  let answer = null;
  try {
    const res = await fetch('/api/workstation/browser', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'point', ...where }),
    });
    if (!res.ok) { _say(await _detail(res), { error: true }); _render(); return false; }
    answer = await res.json();
  } catch (e) {
    _say(`Pantheon could not reach the browser: ${String((e && e.message) || e)}`, { error: true });
    return false;
  }
  _render();
  _kick(TIMING.AFTER_INPUT_MS);
  if (!answer || !answer.pointed) return false;
  if (!answer.pointed.page && Array.isArray(answer.pointed.box)) _outline(answer.pointed.box);
  const ok = await _intoComposer(answer.pointed);
  if (ok) _say('In your message: say what you want of it, and send.');
  return ok;
}

function _togglePointing() {
  _pointing = !_pointing;
  _render();
}

// ── `P25-12`: the reply's reasoning, beside the page ─────────────────────────

/** The tail of the live reasoning, as the strip shows it. */
export function thinkingTail(text, n = THINKING_SHOWN) {
  const t = String(text || '').replace(/\s+$/, '');
  if (t.length <= n) return t;
  const cut = t.slice(t.length - n);
  const sp = cut.indexOf(' ');
  return `…${sp > 0 && sp < 40 ? cut.slice(sp + 1) : cut}`;
}

function _drawThinking() {
  if (!_win) return;
  const t = thinkingTail(_thinking);
  _win.thinkingText.textContent = t;
  _win.thinking.hidden = !t;
  _win.thinking.classList.toggle('abw-thinking-live', _chatBusy);
  _win.thinkingHead.textContent = _chatBusy ? 'The agent is thinking' : 'What the agent was thinking';
  _win.thinkingText.scrollTop = _win.thinkingText.scrollHeight;
}

function _onLiveThinking(ev) {
  const d = (ev && ev.detail) || {};
  _thinking = String(d.text || '');
  _drawThinking();
}

function _onChatBusy(ev) {
  const was = _chatBusy;
  _chatBusy = !!(ev && ev.detail && ev.detail.active);
  if (was !== _chatBusy) { _drawThinking(); _render(); }
}

/** A message went: a hold the person took to browse goes back with it, so
 *  the agent can do what it asks; a new reply's reasoning starts empty. */
function _onMessageSent() {
  _thinking = '';
  _drawThinking();
  if (_win && _holder === 'person' && !_stopped) {
    handBack().then((ok) => { if (ok) _say('Handed back to the agent with your message.'); });
  }
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
  const stop = _button('abw-stop', 'Stop', () => { emergencyStop(); },
    'Stop the agent now: the browser is yours until you hand it back');
  stop.hidden = true;
  const take = _button('abw-take', 'Take over', () => { takeOver(); });
  const give = _button('abw-give', 'Hand back', () => { handBack(); });
  take.hidden = true;
  give.hidden = true;
  // `P25-10`: which page or element the person means.
  const point = _button('abw-point', 'Point at…', () => _togglePointing(),
    'Point at something on the page to tell the agent that is what you mean');
  const pointPage = _button('abw-point-page', 'This page', () => { pointAt({ page: true }); },
    'Tell the agent this page is the one you mean');
  strip.appendChild(status);
  strip.appendChild(point);
  strip.appendChild(pointPage);
  strip.appendChild(stop);
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
  // `P25-07`. The agent's hand and its words, over the page.
  const hand = _el('span', 'abw-hand');
  hand.setAttribute('aria-hidden', 'true');
  hand.innerHTML = HAND_SVG;   // a constant, never server text
  hand.hidden = true;
  const caption = _el('div', 'abw-caption');
  caption.setAttribute('role', 'status');
  caption.setAttribute('aria-live', 'polite');
  caption.hidden = true;
  // `P25-11`: what an inspection looked at.
  const outline = _el('span', 'abw-outline');
  outline.setAttribute('aria-hidden', 'true');
  outline.hidden = true;
  page.appendChild(outline);
  page.appendChild(hand);
  page.appendChild(caption);
  const feed = _el('ol', 'abw-feed');
  feed.setAttribute('aria-label', 'What the browser did');
  feed.hidden = true;
  stage.appendChild(page);
  // `P26-01` … `P26-03`. Notes on the page: their toolbar and their list.
  const notesBar = _el('div', 'abw-notes-slot');
  const notesList = _el('div', 'abw-notes-slot');
  const hint = _el('p', 'abw-hint');
  hint.hidden = true;
  // `P25-12`: the reply's live reasoning.
  const thinking = _el('section', 'abw-thinking');
  thinking.hidden = true;
  const thinkingHead = _el('h5', 'abw-thinking-head', 'The agent is thinking');
  const thinkingText = _el('div', 'abw-thinking-text');
  thinkingText.setAttribute('aria-live', 'off');
  thinking.appendChild(thinkingHead);
  thinking.appendChild(thinkingText);

  content.appendChild(header);
  content.appendChild(tabs);
  content.appendChild(bar);
  content.appendChild(strip);
  content.appendChild(notesBar);
  content.appendChild(stage);
  content.appendChild(notesList);
  content.appendChild(feed);
  content.appendChild(thinking);
  content.appendChild(hint);
  modal.appendChild(content);

  page.addEventListener('click', _onClick);
  page.addEventListener('wheel', _onWheel, { passive: false });
  page.addEventListener('keydown', _onKeyDown);
  page.addEventListener('blur', _flushTyped);
  img.addEventListener('dragstart', (e) => e.preventDefault());

  return { modal, content, header, title, tabs, back, forward, reload, address, go, status, statusText,
    take, give, stop, stage, page, img, empty, hint, hand, caption, feed, notesBar, notesList,
    point, pointPage, outline, thinking, thinkingHead, thinkingText };
}

/** `P26-03`. Write the notes into the chat as one message, with their
 *  pictures, and send it. */
async function _sendToChat(text, files) {
  const box = document.getElementById('message');
  if (!box) { _say('There is no chat to send the notes to.', { error: true }); return false; }
  try {
    // The same module instance the composer uses (its `?v=`), or the pictures
    // land in a pending list nothing sends.
    const fh = await import('./fileHandler.js?v=20261009census');
    if (files && files.length && typeof fh.addFiles === 'function') await fh.addFiles(files, { skipCrop: true });
  } catch (_) { /* the words still go; the pictures are a help, not the message */ }
  box.value = text;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  const sendBtn = document.querySelector('.send-btn');
  if (sendBtn) sendBtn.click();
  return true;
}

function _startNotes() {
  if (!_win || _notes) return;
  _notes = createNotes({
    win: _win, size: () => _size, say: (t, o) => _say(t, o), send: _sendToChat, mapPoint,
    frameInfo: () => ({ title: _win ? _win.title.textContent : '', url: _lastUrl }),
  });
  _win.notesBar.appendChild(_notes.bar);
  _win.notesList.appendChild(_notes.list);
}

function _teardown() {
  if (!_win) return;
  if (_timer) { clearTimeout(_timer); _timer = null; }
  if (_notes) { _notes.destroy(); _notes = null; }
  _flushTyped();
  if (_holder === 'person') {
    fetch('/api/workstation/control', {
      method: 'POST', credentials: 'same-origin', keepalive: true,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ holder: 'agent' }),
    }).catch(() => {});
  }
  const modal = _win.modal;
  if (_captionTimer) { clearTimeout(_captionTimer); _captionTimer = null; }
  if (_boxTimer) { clearTimeout(_boxTimer); _boxTimer = null; }
  _pointing = false;
  _win = null;
  _digest = '';
  _lastUrl = '';
  _since = 0;
  _feed = [];
  _lastAgentAt = 0;
  _stopped = false;
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
    _chatBusy = !!_global.__pantheonChatBusy;
    _render();
    _drawThinking();
    _startNotes();
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
  // `P25-00`. The click stops here, so the + menu's own close on a pick
  // never ran and the menu stayed open over the chat — over the card the
  // agent's next question draws. A door in it asks for the close the way a
  // submenu's pick does.
  if (typeof door.closest === 'function' && door.closest('#overflow-menu')) {
    document.dispatchEvent(new CustomEvent('composer-menu-close'));
  }
  openAgentBrowser({ focus: ev.detail === 0 });
}

if (typeof document !== 'undefined' && document && typeof document.addEventListener === 'function') {
  document.addEventListener('click', _onDoor, true);
  document.addEventListener('visibilitychange', () => { if (_shouldPoll()) _resume(); });
}
const _global = typeof window !== 'undefined' ? window : globalThis;
if (_global && typeof _global.addEventListener === 'function') {
  _global.addEventListener('pantheon:live-thinking', _onLiveThinking);
  _global.addEventListener('pantheon:chat-busy-change', _onChatBusy);
  _global.addEventListener('pantheon:message-sent', _onMessageSent);
}

export const _test = {
  TIMING, tick: _tick, win: () => _win, settled: () => _sendChain,
  state: () => ({ open: !!_win, state: _state, holder: _holder, digest: _digest, since: _since,
    feed: _feed.map((f) => ({ ...f })), hand: { ..._hand }, stopped: _stopped,
    pointing: _pointing, chatBusy: _chatBusy, thinking: _thinking }),
};

export default { openAgentBrowser, closeAgentBrowser, takeOver, handBack, openAddress, emergencyStop };
