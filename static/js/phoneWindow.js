// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B1747`. The phone's window: a real Android device, in a phone you can hold.
//
// The owner (2026-11-02): *"a mobile device emulator... with various real
// device emulation (Samsung Galaxy Z Fold, Google Pixel Pro, etc...) with the
// real OS, "touch" controls (via mouse)"* — and, less pressing, *"a no shit
// rendered phone on the screen too so the user can click the side buttons"*.
//
// The phone is Google's Android Emulator in the person's workstation
// (`workstation/phone.py`), on a screen of its own streamed through
// Pantheon's own copy of KasmVNC's client, exactly as the live browser is
// (`browserWindow.js`). This window draws the device around that stream —
// `B1748`: a bezel at the device's own shape, its side keys where its maker
// puts them (Google: power above the volume rocker; Samsung: the rocker above
// power), each a real key press on the device — and the controls a phone on a
// desk does not have: which device it is, power, rotate, fold, and an address
// to open on it.
//
// **Touch is the stream's.** While the person holds the screens (*Take
// over*, the workstation's one holder), the mouse on the screen is a finger:
// click to tap, drag to swipe, the wheel to fling, right click for Back.
// While the agent holds them a glass lies over the screen, and a click on it
// takes over. The side keys, the device and the power are the person's own
// explicit acts and work whoever holds the screen.
//
// **Every rule is the server's.** `routes/workstation_routes.py` and the
// daemon behind it say whether there is a phone here, why not, and what each
// press may be. A refusal is shown in their words. Markup is built with
// `createElement`; no server string is parsed as HTML.

import * as Modals from './modalManager.js?v=20261009census';
import { makeWindowDraggable } from './windowDrag.js';

export const MODAL_ID = 'phone-modal';

const TIMING = { STATE_MS: 2500, BOOTING_MS: 1500, HOLDER_MS: 4000 };
const LIVE_CLIENT = '/api/workstation/desktop/client/';

const PHONE_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
  + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
  + 'aria-hidden="true"><rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/></svg>';

const SAY = {
  checking: 'Looking for your phone…',
  off: 'Your phone is off. Press Power to turn it on.',
  starting: 'Your phone is booting. The first boot of a device takes a minute or two.',
  on: 'Ready.',
  holding: 'You have the phone: click to tap, drag to swipe, scroll to fling, right click for Back.',
  agent: 'The agent has the screens. Click the phone or Take over to use it yourself.',
  // `B1749`: where there is no KVM, the phone is a phone-shaped browser.
  mobileStarting: 'Opening the mobile view…',
  mobile: 'Mobile view: web pages only, laid out as this device shows them. The real Android needs KVM.',
};

/** `B1749`. Whether the phone is the mobile view rather than Android. */
export function isMobileView(state) {
  return !!(state && state.mode === 'mobile_view');
}

/** `B1749`. Which keys work: the mobile view has no volume or recents. */
export function keyWorks(state, id) {
  if (!isMobileView(state)) return true;
  return id === 'power' || id === 'back' || id === 'home';
}

let _win = null;
let _state = null;       // the server's answer, shaped by `_phone_state`
let _holder = null;
let _client = '';        // the live client's page, while the phone streams
let _frame = null;
let _timer = null;
let _busy = false;       // a press on its way

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
  _win.status.dataset.state = error ? 'down' : (_state && _state.state === 'on' ? 'up' : 'checking');
}

/** The device's entry in the server's list, or a stand-in. */
export function deviceOf(state) {
  const list = (state && Array.isArray(state.devices)) ? state.devices : [];
  return list.find((d) => d.id === (state && state.device)) || list[0] || { id: '', name: 'Phone', maker: '', kind: 'phone' };
}

/** `B1748`. The bezel's shape for the state: the screen's own, or a closed
 *  foldable's cover — `{ w, h }`, the screen's pixels as the server sent them. */
export function bezelShape(state) {
  const screen = (state && Array.isArray(state.screen) && state.screen.length === 2) ? state.screen : [492, 1100];
  const [w, h] = screen;
  const d = deviceOf(state);
  // The mobile view's screen is already the cover's shape (`B1749`).
  if (d.foldable && state.posture === 'closed' && !isMobileView(state)) return { w: Math.round(w / 2), h };
  return { w, h };
}

/** `B1748`. Where a maker puts the side keys, top to bottom, on the right edge. */
export function sideKeys(maker) {
  return maker === 'Samsung'
    ? [{ id: 'volume_up', label: 'Volume up' }, { id: 'volume_down', label: 'Volume down' }, { id: 'power', label: 'Power' }]
    : [{ id: 'power', label: 'Power' }, { id: 'volume_up', label: 'Volume up' }, { id: 'volume_down', label: 'Volume down' }];
}

async function _get(url) {
  const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
  let body = null;
  try { body = await res.json(); } catch (_) { body = null; }
  if (!res.ok) throw new Error((body && (body.detail || body.message)) || `HTTP ${res.status}`);
  return body;
}

async function _post(url, payload) {
  const res = await fetch(url, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  let body = null;
  try { body = await res.json(); } catch (_) { body = null; }
  if (!res.ok) throw new Error((body && (body.detail || body.message)) || `HTTP ${res.status}`);
  return body;
}

/** One of the person's own presses on the phone. */
export async function act(payload) {
  if (_busy) return null;
  _busy = true;
  try {
    const answer = await _post('/api/workstation/phone', payload);
    _state = answer;
    _render();
    return answer;
  } catch (e) {
    _say(e.message, { error: true });
    return null;
  } finally {
    _busy = false;
    _kick(TIMING.BOOTING_MS);
  }
}

export function press(button) { return act({ action: 'button', button }); }

export async function takeOver() {
  try {
    const a = await _post('/api/workstation/control', { holder: 'person' });
    _holder = a && a.holder;
  } catch (e) { _say(e.message, { error: true }); }
  _render();
}

export async function handBack() {
  try {
    const a = await _post('/api/workstation/control', { holder: 'agent' });
    _holder = a && a.holder;
  } catch (e) { _say(e.message, { error: true }); }
  _render();
}

async function _tick() {
  _timer = null;
  if (!_win) return;
  try {
    _state = await _get('/api/workstation/phone');
  } catch (e) {
    _state = { available: false, state: 'unavailable', why: e.message, devices: [] };
  }
  if (_state.state === 'on') {
    try {
      const s = await _get('/api/workstation/phone/screen');
      if (s && (s.holder === 'agent' || s.holder === 'person')) _holder = s.holder;
      const client = s && s.kind === 'kasmvnc' && typeof s.client === 'string'
        && s.client.startsWith(LIVE_CLIENT) ? s.client : '';
      if (client !== _client) { _dropFrame(); _client = client; }
    } catch (_) { /* the state says enough; the screen is asked again */ }
  } else if (_client) {
    _dropFrame();
    _client = '';
  }
  _render();
  _kick(_state.state === 'starting' ? TIMING.BOOTING_MS : TIMING.STATE_MS);
}

function _kick(ms) {
  if (!_win) return;
  if (_timer) clearTimeout(_timer);
  _timer = setTimeout(_tick, ms);
}

function _mountFrame() {
  if (!_win || !_client || _frame) return;
  const frame = document.createElement('iframe');
  frame.className = 'phw-live-frame';
  frame.title = 'Your phone, live';
  frame.setAttribute('referrerpolicy', 'no-referrer');
  frame.src = _client;
  _frame = frame;
  _win.screen.insertBefore(frame, _win.screen.firstChild);
}

function _dropFrame() {
  if (!_frame) return;
  if (_frame.parentNode) _frame.parentNode.removeChild(_frame);
  _frame = null;
}

/** The stream laid in the bezel's screen at the phone screen's own shape,
 *  centred: a closed foldable's cover is the middle of that screen, and the
 *  bezel's narrower screen shows just it. */
function _placeFrame() {
  if (!_win || !_frame || !_state) return;
  const box = _win.screen.getBoundingClientRect();
  const [w, h] = _state.screen || [492, 1100];
  if (!box.height || !h) return;
  const width = box.height * (w / h);
  _frame.style.width = `${width}px`;
  _frame.style.height = `${box.height}px`;
  _frame.style.left = `${(box.width - width) / 2}px`;
}

function _render() {
  if (!_win) return;
  const s = _state || { state: 'checking', devices: [] };
  const d = deviceOf(s);
  const on = s.state === 'on';
  const holding = _holder === 'person';
  const mobile = isMobileView(s);
  _win.title.textContent = d.name ? `Phone · ${d.name}${mobile ? ' · mobile view' : ''}` : 'Phone';
  _win.title.title = mobile ? (s.why_not_android || '') : '';

  // The device list, grouped by maker; made once, kept selected.
  if (Array.isArray(s.devices) && s.devices.length && _win.device.options.length !== s.devices.length) {
    _win.device.textContent = '';
    const groups = {};
    for (const dev of s.devices) {
      if (!groups[dev.maker]) {
        groups[dev.maker] = document.createElement('optgroup');
        groups[dev.maker].label = dev.maker || 'Devices';
        _win.device.appendChild(groups[dev.maker]);
      }
      const o = document.createElement('option');
      o.value = dev.id;
      o.textContent = dev.name;
      groups[dev.maker].appendChild(o);
    }
  }
  if (d.id) _win.device.value = d.id;
  _win.device.disabled = s.state === 'unavailable' || s.state === 'starting';

  _win.power.textContent = on || s.state === 'starting' ? 'Turn off' : 'Turn on';
  _win.power.disabled = s.state === 'unavailable';
  _win.rotate.hidden = !on;
  _win.fold.hidden = !(on && d.foldable);
  _win.fold.textContent = s.posture === 'closed' ? 'Unfold' : 'Fold';
  _win.take.hidden = !on || holding;
  _win.give.hidden = !on || !holding;
  _win.openForm.hidden = !on;

  // `B1748`. The bezel: the device's shape, its keys on its maker's side.
  const shape = bezelShape(s);
  _win.bezel.style.setProperty('--phw-aspect', `${shape.w} / ${shape.h}`);
  _win.bezel.dataset.kind = d.kind || 'phone';
  _win.bezel.dataset.maker = (d.maker || '').toLowerCase();
  const keys = sideKeys(d.maker);
  if (_win.sideKeys.dataset.maker !== d.maker) {
    _win.sideKeys.textContent = '';
    for (const k of keys) {
      const b = _el('button', `phw-side phw-side-${k.id}`);
      b.type = 'button';
      b.title = k.label;
      b.setAttribute('aria-label', k.label);
      b.dataset.key = k.id;
      b.addEventListener('click', (e) => { e.preventDefault(); press(k.id); });
      _win.sideKeys.appendChild(b);
    }
    _win.sideKeys.dataset.maker = d.maker || '';
  }
  for (const b of _win.sideKeys.querySelectorAll('button')) {
    b.disabled = !on || !keyWorks(s, b.dataset.key);
  }
  for (const b of _win.nav.querySelectorAll('button')) {
    b.disabled = !on || !keyWorks(s, b.dataset.key);
  }

  _win.screen.classList.toggle('phw-holding', holding);
  _win.empty.hidden = on && !!_client;
  if (on && _client) {
    _mountFrame();
    _placeFrame();
  } else {
    _dropFrame();
    _win.empty.textContent = s.state === 'unavailable' ? (s.why || 'There is no phone here.')
      : (mobile && s.state === 'starting' ? SAY.mobileStarting : (SAY[s.state] || SAY.checking));
  }
  if (s.state === 'unavailable') _say(s.why || 'There is no phone here.', { error: true });
  else if (on && mobile && !holding) _say(SAY.mobile);
  else if (on) _say(holding ? (mobile ? 'You have the phone: click to tap, scroll to move the page.' : SAY.holding) : SAY.agent);
  else _say(mobile && s.state === 'starting' ? SAY.mobileStarting : (SAY[s.state] || SAY.checking));
}

function _build() {
  const modal = _el('div', 'modal phw-modal');
  modal.id = MODAL_ID;
  const content = _el('div', 'modal-content phw-content');
  const header = _el('div', 'modal-header');
  const h = _el('h4', 'phw-heading');
  const icon = _el('span', 'phw-icon');
  icon.innerHTML = PHONE_ICON;   // a constant above, never server text
  const title = _el('span', 'phw-title', 'Phone');
  h.appendChild(icon);
  h.appendChild(title);
  const close = _el('button', 'close-btn');
  close.type = 'button';
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '✖';
  close.addEventListener('click', (e) => { e.preventDefault(); closePhone(); });
  header.appendChild(h);
  header.appendChild(close);

  const bar = _el('div', 'phw-bar');
  const device = document.createElement('select');
  device.className = 'phw-device';
  device.setAttribute('aria-label', 'Device');
  device.addEventListener('change', () => act({ action: 'device', device: device.value }));
  const power = _button('phw-power', 'Turn on', () => {
    const s = _state && _state.state;
    act({ action: s === 'on' || s === 'starting' ? 'stop' : 'start' });
  }, 'Turn the phone on or off');
  const rotate = _button('phw-rotate', 'Rotate', () => act({ action: 'rotate' }), 'Turn the phone a quarter');
  const fold = _button('phw-fold', 'Fold', () => act({
    action: 'posture', posture: _state && _state.posture === 'closed' ? 'open' : 'closed',
  }), 'Fold or unfold the phone');
  const take = _button('phw-take', 'Take over', () => { takeOver(); });
  const give = _button('phw-give', 'Hand back', () => { handBack(); });
  bar.appendChild(device);
  bar.appendChild(power);
  bar.appendChild(rotate);
  bar.appendChild(fold);
  bar.appendChild(take);
  bar.appendChild(give);

  const openForm = _el('form', 'phw-open');
  const address = document.createElement('input');
  address.type = 'text';
  address.className = 'phw-address';
  address.spellcheck = false;
  address.autocomplete = 'off';
  address.placeholder = 'Open an address on the phone';
  address.setAttribute('aria-label', 'Address to open on the phone');
  const go = _el('button', 'memory-toolbar-btn phw-go', 'Open');
  go.type = 'submit';
  openForm.appendChild(address);
  openForm.appendChild(go);
  openForm.addEventListener('submit', (e) => {
    e.preventDefault();
    let url = address.value.trim();
    if (!url) return;
    if (!/^https?:\/\//i.test(url)) url = `https://${url}`;
    act({ action: 'open_url', url });
  });

  const status = _el('div', 'ws-status phw-status');
  status.dataset.state = 'checking';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  const dot = _el('span', 'ws-status-dot');
  dot.setAttribute('aria-hidden', 'true');
  const statusText = _el('span', 'ws-status-text', SAY.checking);
  status.appendChild(dot);
  status.appendChild(statusText);

  // `B1748`. The device itself.
  const stage = _el('div', 'phw-stage');
  const bezel = _el('div', 'phw-bezel');
  const speaker = _el('span', 'phw-speaker');
  speaker.setAttribute('aria-hidden', 'true');
  const screen = _el('div', 'phw-screen');
  const empty = _el('div', 'phw-empty', SAY.checking);
  const glass = _el('div', 'phw-glass');
  glass.title = 'Take over to use the phone';
  glass.addEventListener('click', (e) => { e.preventDefault(); takeOver(); });
  screen.appendChild(empty);
  screen.appendChild(glass);
  const sideKeysBox = _el('div', 'phw-side-keys');
  bezel.appendChild(speaker);
  bezel.appendChild(screen);
  bezel.appendChild(sideKeysBox);
  stage.appendChild(bezel);

  const nav = _el('div', 'phw-nav');
  nav.setAttribute('role', 'toolbar');
  nav.setAttribute('aria-label', 'Android navigation');
  for (const [glyph, key, label] of [['◁', 'back', 'Back'], ['○', 'home', 'Home'], ['▢', 'recents', 'Recent apps']]) {
    const b = _button('phw-nav-btn', glyph, () => press(key), label);
    b.dataset.key = key;
    nav.appendChild(b);
  }

  content.appendChild(header);
  content.appendChild(bar);
  content.appendChild(openForm);
  content.appendChild(status);
  content.appendChild(stage);
  content.appendChild(nav);
  modal.appendChild(content);

  return { modal, content, header, title, device, power, rotate, fold, take, give, openForm, address,
    status, statusText, stage, bezel, screen, empty, glass, sideKeys: sideKeysBox, nav };
}

function _teardown() {
  if (!_win) return;
  if (_timer) { clearTimeout(_timer); _timer = null; }
  if (_holder === 'person') {
    fetch('/api/workstation/control', {
      method: 'POST', credentials: 'same-origin', keepalive: true,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ holder: 'agent' }),
    }).catch(() => {});
  }
  _dropFrame();
  const modal = _win.modal;
  _win = null;
  _state = null;
  _client = '';
  _holder = null;
  if (modal.parentNode) modal.parentNode.removeChild(modal);
}

function _resume() { _kick(0); }

/** Open the window, or bring it forward. */
export function openPhone() {
  if (_win && Modals.isRegistered(MODAL_ID)) {
    if (Modals.isMinimized(MODAL_ID)) Modals.restore(MODAL_ID);
    else Modals.showWindow(MODAL_ID);
    _resume();
    return true;
  }
  if (_win) _teardown();
  _win = _build();
  document.body.appendChild(_win.modal);
  Modals.register(MODAL_ID, { restoreFn: _resume, closeFn: _teardown });
  Modals.injectMinimizeButton(_win.modal, MODAL_ID);
  makeWindowDraggable(_win.modal, {
    content: _win.content, header: _win.header,
    skipSelector: 'button, input, select, label, form', minWidth: 320, minHeight: 420,
  });
  _render();
  _kick(0);
  return true;
}

export function closePhone() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else _teardown();
}

/** Every door is a `[data-open-phone]` control, answered here once. */
function _onDoor(ev) {
  const t = ev.target;
  const door = t && typeof t.closest === 'function' ? t.closest('[data-open-phone]') : null;
  if (!door) return;
  ev.preventDefault();
  ev.stopPropagation();
  if (typeof door.closest === 'function' && door.closest('#overflow-menu')) {
    document.dispatchEvent(new CustomEvent('composer-menu-close'));
  }
  openPhone();
}

if (typeof document !== 'undefined' && document && typeof document.addEventListener === 'function') {
  document.addEventListener('click', _onDoor, true);
}
const _global = typeof window !== 'undefined' ? window : globalThis;
if (_global && typeof _global.addEventListener === 'function') {
  _global.addEventListener('resize', () => _placeFrame());
}

export const _test = {
  TIMING, tick: _tick, win: () => _win,
  state: () => ({ open: !!_win, state: _state, holder: _holder, client: _client, frame: _frame }),
};

export default { openPhone, closePhone, press, act, takeOver, handBack };
