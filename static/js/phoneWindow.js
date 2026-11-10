// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B1751`. The phone's window: a real Android device, in a phone you can hold.
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
// `B1752`: a bezel at the device's own shape, its side keys where its maker
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
import { prefersReducedMotion } from './motion.js';

export const MODAL_ID = 'phone-modal';

const TIMING = { STATE_MS: 2500, BOOTING_MS: 1500, HOLDER_MS: 4000, MOTION_MS: 650 };
const LIVE_CLIENT = '/api/workstation/desktop/client/';

const PHONE_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
  + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
  + 'aria-hidden="true"><rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/></svg>';

const SAY = {
  checking: 'Looking for your phone…',
  off: 'Your phone is off. Press Power to turn it on.',
  starting: 'Android is booting. Its live display appears as soon as it is available.',
  on: 'Ready.',
  holding: 'You have the phone: click to tap, drag to swipe, scroll to fling, right click for Back.',
  agent: 'The agent has the screens. Click the phone or Take over to use it yourself.',
  // `B1753`: where there is no KVM, the phone is a phone-shaped browser.
  mobileStarting: 'Opening the mobile view…',
  mobile: 'Browser preview: web pages only. Android apps are unavailable in this mode.',
  // `B1756`: a device picked that the workstation does not have yet.
  installing: 'Installing the device. Pantheon downloads its Android image, then turns it on.',
  moved: 'Your phone is open in its own window. Close it there to use it here.',
};

/** `B1756`. The devices as the Phone room lists them: grouped by maker, each
 *  with whether it is this one, whether it is on the workstation, and what
 *  picking it does — the words of its button. */
export function catalogueOf(state) {
  const s = state || {};
  const list = Array.isArray(s.devices) ? s.devices : [];
  const mobile = isMobileView(s);
  const groups = [];
  for (const d of list) {
    let g = groups.find((x) => x.maker === (d.maker || ''));
    if (!g) { g = { maker: d.maker || '', devices: [] }; groups.push(g); }
    const current = d.id === s.device;
    // The mobile view has nothing to install: it is the workstation's browser.
    const installed = d.installed === true;
    let verb = installed ? 'Use this device' : 'Install and use';
    if (!s.mode) verb = 'Select profile';
    if (mobile) verb = 'Preview this profile';
    if (current && (s.state === 'on' || s.state === 'starting')) verb = 'In use';
    else if (current && s.state === 'installing') verb = 'Installing…';
    g.devices.push({
      id: d.id, name: d.name || d.id, maker: d.maker || '', kind: d.kind || 'phone',
      foldable: !!d.foldable, android: d.android || '', installed, current, verb,
      finish: lookOf(d).finish, finishName: lookOf(d).finishName,
      busy: s.state === 'installing' || s.state === 'starting',
    });
  }
  return groups;
}

/** `B1756`. The install's progress in words and a number 0–100, or null. */
export function installLine(state) {
  const s = state || {};
  const inst = s.install && typeof s.install === 'object' ? s.install : null;
  if (!inst || (inst.state !== 'running' && s.state !== 'installing')) {
    if (inst && inst.state === 'failed') return { text: inst.why || 'The install did not finish.', percent: null, failed: true };
    return null;
  }
  const pct = Number.isInteger(inst.percent) ? Math.max(0, Math.min(100, inst.percent)) : null;
  const what = inst.android ? ` (${inst.android})` : '';
  return { text: `${inst.step_label || 'Installing'}${what}`, percent: pct, failed: false };
}

/** `B1756`. Whether picking `id` first needs the person to accept the Android
 *  SDK License — a real device not on the workstation, never accepted here. */
export function needsLicense(state, id) {
  const s = state || {};
  if (isMobileView(s)) return false;
  if ((s.edition === 'google_play' || s.google_play) && !(s.license && s.license.accepted === true)) return true;
  const d = (Array.isArray(s.devices) ? s.devices : []).find((x) => x.id === id);
  if (!d || d.installed === true) return false;
  return !(s.license && s.license.accepted === true);
}

/** `B1753`. Whether the phone is the mobile view rather than Android. */
export function isMobileView(state) {
  return !!(state && state.mode === 'mobile_view');
}

/** `B1753`. Which keys work: the mobile view has no volume or recents. */
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
let _room = null;        // `B1756`: the Phone room's host, while it is mounted
let _pending = '';       // `B1756`: a device waiting on the license's Accept
let _pose = null;
let _animations = [];
let _screenKey = '';
let _error = '';
let _sending = false;
let _transferText = '';
let _revision = 0;
let _pollSequence = 0;
let _actionSequence = 0;
let _controlSequence = 0;
let _controlTail = Promise.resolve();
const _pendingTakeovers = new Map();

/** Keep runtime identity in view even while a person holds the screen. */
export function runtimeOf(state) {
  const s = state || {};
  if (isMobileView(s)) return {
    label: 'Browser preview · Web only',
    detail: `Android is unavailable. ${s.why_not_android || 'This is Firefox; Android apps and the Android home screen are unavailable.'}`,
  };
  if (s.mode === 'android') return {
    label: s.google_play ? 'Android · Google Play developer image' : 'Generic Android',
    detail: (s.google_play ? 'Google Play is supplied by the separately licensed SDK image. Sign in on Android itself. '
      : s.image_kind === 'google_apis' ? 'The Google APIs image includes Play services but no Play Store. '
        : s.image_kind === 'aosp' ? 'This is AOSP Android without Google Play software. '
          : 'This is the configured Android SDK image. ')
      + 'Your agents use this same device. Profiles model size and appearance; OEM software is not included.',
  };
  return { label: 'Android unavailable', detail: s.why || 'Checking the workstation’s Android runtime.' };
}

/** A physical quarter-turn can wrap 270 -> 0 without spinning backwards. */
export function rotationStep(from, to) {
  const delta = ((to - from) % 4 + 4) % 4;
  return delta === 3 ? -90 : delta * 90;
}

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

let _noun = 'phone';   // `B1757`: "tablet" while the device is one

/** One of `SAY`'s sentences for the device in hand: a tablet is a tablet. */
function _words(text) {
  return _noun === 'phone' ? text : String(text || '').replace(/\byour phone\b/gi, (m) => (m[0] === 'Y' ? 'Your ' : 'your ') + _noun);
}

function _say(text, { error = false } = {}) {
  if (!_win) return;
  _win.statusText.textContent = _words(String(text || ''));
  _win.status.dataset.state = error ? 'down' : (_state && _state.state === 'on' ? 'up' : 'checking');
}

/** The device's entry in the server's list, or a stand-in. */
export function deviceOf(state) {
  const list = (state && Array.isArray(state.devices)) ? state.devices : [];
  return list.find((d) => d.id === (state && state.device)) || list[0] || { id: '', name: 'Phone', maker: '', kind: 'phone' };
}

/** `B1752`. The bezel's shape for the state: the screen's own, or a closed
 *  foldable's cover — `{ w, h }`, the screen's pixels as the server sent them. */
export function bezelShape(state) {
  const screen = (state && Array.isArray(state.screen) && state.screen.length === 2) ? state.screen : [492, 1100];
  const [w, h] = screen;
  const d = deviceOf(state);
  // The mobile view's screen is already the cover's shape (`B1753`).
  if (d.foldable && state.posture === 'closed' && !isMobileView(state) && !state.screen_is_active) return { w: Math.round(w / 2), h };
  return { w, h };
}

/** `B1752`. Where a maker puts the side keys, top to bottom, on the right edge. */
export function sideKeys(maker) {
  return maker === 'Samsung'
    ? [{ id: 'volume_up', label: 'Volume up' }, { id: 'volume_down', label: 'Volume down' }, { id: 'power', label: 'Power' }]
    : [{ id: 'power', label: 'Power' }, { id: 'volume_up', label: 'Volume up' }, { id: 'volume_down', label: 'Volume down' }];
}

const KEY_LABELS = { power: 'Power', volume_up: 'Volume up', volume_down: 'Volume down' };
const KEY_SIDES = ['left', 'right', 'top'];

/** `B1757`. How the device looks from the front, as the server sent it, with
 *  a stand-in for anything missing. */
export function lookOf(device) {
  const l = (device && device.look && typeof device.look === 'object') ? device.look : {};
  const num = (v, d) => (typeof v === 'number' && Number.isFinite(v) ? v : d);
  return {
    finish: typeof l.finish === 'string' && /^#[0-9a-f]{6}$/i.test(l.finish) ? l.finish : '',
    finishName: typeof l.finish_name === 'string' ? l.finish_name : '',
    corner: Math.max(0, Math.min(0.2, num(l.corner, 0.1))),
    bezel: Math.max(0, Math.min(0.1, num(l.bezel, 0.03))),
    cutout: typeof l.cutout === 'string' ? l.cutout : 'punch-center',
    keys: l.keys && typeof l.keys === 'object' ? l.keys : null,
  };
}

/** `B1757`. The device's side keys, edge by edge: its own when the server
 *  says where they are, else its maker's (`sideKeys`) on the right. */
export function keysOf(device) {
  const look = lookOf(device);
  const out = { left: [], right: [], top: [] };
  if (look.keys) {
    for (const side of KEY_SIDES) {
      for (const id of (Array.isArray(look.keys[side]) ? look.keys[side] : [])) {
        if (KEY_LABELS[id]) out[side].push({ id, label: KEY_LABELS[id] });
      }
    }
  }
  if (!out.left.length && !out.right.length && !out.top.length) out.right = sideKeys(device && device.maker);
  return out;
}

/** `B1757`. The body drawn to fit `W`×`H`: the screen at its own shape
 *  (`shape`), the bezel around it at the device's share of its short side,
 *  and its corners as round as the device's. `{ screenW, screenH, rim,
 *  radius, inner }`, in CSS pixels. */
export function bodyGeometry(look, shape, W, H) {
  const l = look || lookOf(null);
  const aspect = shape && shape.w > 0 && shape.h > 0 ? shape.w / shape.h : 492 / 1100;
  const f = l.bezel;
  const m = Math.min(aspect, 1);   // the short side, as a share of the screen's height
  const sh = Math.max(0, Math.min(H / (1 + 2 * f * m), W / (aspect + 2 * f * m)));
  const rim = Math.max(4, f * m * sh);
  const screenH = Math.floor(sh);
  const screenW = Math.floor(sh * aspect);
  const short = Math.min(screenW, screenH) + 2 * rim;
  const radius = Math.max(rim + 2, l.corner * short);
  return { screenW, screenH, rim: Math.round(rim), radius: Math.round(radius),
    inner: Math.max(2, Math.round(radius - rim * 0.85)) };
}

async function _get(url) {
  const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
  let body = null;
  try { body = await res.json(); } catch (_) { body = null; }
  if (!res.ok) throw new Error((body && (body.detail || body.message)) || `HTTP ${res.status}`);
  return body;
}

async function _post(url, payload, { keepalive = false } = {}) {
  const res = await fetch(url, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    keepalive,
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
  const win = _win, action = ++_actionSequence;
  ++_revision;  // a pending status read predates this explicit act
  _busy = true;
  _error = '';
  try {
    const answer = await _post('/api/workstation/phone', payload);
    if (_win !== win || action !== _actionSequence) return null;
    ++_revision;
    _state = answer;
    if (['rotate', 'posture', 'device', 'install', 'stop', 'edition', 'preview'].includes(payload.action)) {
      _dropFrame();
      _client = '';
    }
    _render();
    return answer;
  } catch (e) {
    if (_win !== win || action !== _actionSequence) return null;
    _error = e.message;
    _say(e.message, { error: true });
    return null;
  } finally {
    if (_win === win && action === _actionSequence) {
      _busy = false;
      _kick(0);
    }
  }
}

function _turnOn() {
  const s = _state || {};
  if (isMobileView(s)) return act({ action: 'preview' });
  if (s.can_start) return act({ action: 'start' });
  if (needsLicense(s, s.device)) return useDevice(s.device);
  return act({ action: 'start' });
}

async function _sendFile({ file = null, documentId = '' }) {
  if (_sending || !_win || !_state || _state.state !== 'on' || isMobileView(_state)) return;
  const win = _win;
  if (file && file.size > (_state.transfer_max_bytes || 20000000)) {
    _transferText = 'Choose a file of 20 MB or less.'; _render(); return;
  }
  _sending = true;
  _transferText = 'Transferring to Android…';
  _render();
  try {
    const res = await fetch('/api/workstation/phone/files' + (file ? `?name=${encodeURIComponent(file.name)}` : ''), {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': file ? 'application/octet-stream' : 'application/json' },
      body: file || JSON.stringify({ document_id: documentId }),
    });
    let answer = null;
    try { answer = await res.json(); } catch (_) { answer = null; }
    if (!res.ok || !answer || !answer.ok) throw new Error(answer && answer.detail || 'The file transfer did not complete.');
    if (_win !== win) return;
    _transferText = `Sent ${answer.name} (${answer.bytes} bytes) to ${answer.destination}. Checksum verified by Android.`;
  } catch (e) {
    if (_win !== win) return;
    _transferText = e.message;
  } finally {
    if (_win === win) { _sending = false; _render(); }
  }
}

async function _findDocuments() {
  const win = _win;
  if (!win) return;
  win.docFind.disabled = true;
  try {
    const result = await _get(`/api/documents/library?limit=50&search=${encodeURIComponent(win.docSearch.value)}`);
    if (_win !== win) return;
    win.docSelect.textContent = '';
    for (const doc of result.documents || []) {
      const option = document.createElement('option');
      option.value = doc.id;
      option.textContent = doc.title || 'Untitled document';
      win.docSelect.appendChild(option);
    }
    win.docSelect.hidden = !win.docSelect.options.length;
    _transferText = win.docSelect.options.length ? 'Choose a document, then send its current text. Search to find other documents.' : 'No matching documents.';
  } catch (e) { if (_win === win) _transferText = e.message; }
  finally { if (_win === win) { win.docFind.disabled = false; _render(); } }
}

export function press(button) {
  if (button === 'power' && _state && !['on', 'starting'].includes(_state.state)) return _turnOn();
  return act({ action: 'button', button });
}

function _queueControl(holder, keepalive = false) {
  // Server mutations must keep their order too: ignoring a stale response
  // cannot undo a takeover that already happened. Cleanup precedes any newer
  // window's takeover, including when the earlier response is still pending.
  const request = _controlTail.then(() => _post('/api/workstation/phone/control', { holder }, { keepalive }));
  _controlTail = request.catch(() => null);
  return request;
}

async function _changeControl(holder) {
  const win = _win, request = ++_controlSequence;
  if (holder === 'person') _pendingTakeovers.set(win, (_pendingTakeovers.get(win) || 0) + 1);
  ++_revision;
  let changed = false;
  try {
    const a = await _queueControl(holder);
    if (_win !== win || request !== _controlSequence) return;
    _holder = a && a.holder;
    _error = '';
    changed = true;
  } catch (e) { if (_win !== win || request !== _controlSequence) return; _error = e.message; }
  finally {
    if (holder === 'person') {
      const left = (_pendingTakeovers.get(win) || 1) - 1;
      if (left) _pendingTakeovers.set(win, left);
      else _pendingTakeovers.delete(win);
    }
  }
  ++_revision;
  _render();
  _kick(changed ? 0 : TIMING.HOLDER_MS);
}

export function takeOver() { return _changeControl('person'); }
export function handBack() { return _changeControl('agent'); }

/** `B1756`. Whether the room's copy is out of sight — its room switched away
 *  from or the Workbench closed. It stops asking then, and gives the screens
 *  back; showing the room again resumes. */
function _roomHidden() {
  if (!_win) return false;
  const el = _win.modal;
  return !el.isConnected || (typeof el.getClientRects === 'function' && el.getClientRects().length === 0);
}

async function _tick() {
  if (_timer) clearTimeout(_timer);
  _timer = null;
  if (!_win) return;
  if (_busy) { _kick(TIMING.BOOTING_MS); return; }
  if (_roomHidden()) {
    if (_holder === 'person' || _pendingTakeovers.has(_win)) handBack();
    _dropFrame();
    _client = '';
    return;
  }
  const win = _win, revision = _revision, sequence = ++_pollSequence;
  const current = () => _win === win && revision === _revision && sequence === _pollSequence;
  let state;
  try {
    state = await _get('/api/workstation/phone');
  } catch (e) {
    state = { available: false, state: 'unavailable', why: e.message, devices: [] };
  }
  if (!current()) return;
  if (state.state === 'on' || state.state === 'starting') {
    try {
      const s = await _get('/api/workstation/phone/screen');
      if (!current()) return;
      if (s && (s.holder === 'agent' || s.holder === 'person')) _holder = s.holder;
      const client = s && s.kind === 'kasmvnc' && typeof s.client === 'string'
        && s.client.startsWith(LIVE_CLIENT) ? s.client : '';
      const key = JSON.stringify([state.device, state.screen, state.rotation, state.posture]);
      if (client !== _client || key !== _screenKey) { _dropFrame(); _client = client; _screenKey = key; }
    } catch (_) { /* the state says enough; the screen is asked again */ }
  } else if (_client) {
    _dropFrame();
    _client = '';
  }
  if (!current()) return;
  _state = state;
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

/** `B1757`. Size the body to the stage at the device's own proportions. */
function _shapeBody(shape, look, rotation = 0) {
  if (!_win) return;
  const box = _win.stage.getBoundingClientRect();
  if (!box.width || !box.height) return;   // not laid out yet: CSS's fallback holds
  const cs = typeof getComputedStyle === 'function' ? getComputedStyle(_win.stage) : null;
  const pad = (k) => (cs ? parseFloat(cs[k]) || 0 : 0);
  const W = box.width - pad('paddingLeft') - pad('paddingRight') - 12;   // room for the keys
  const H = box.height - pad('paddingTop') - pad('paddingBottom') - 12;
  const sideways = rotation % 2 === 1;
  const natural = sideways ? { w: shape.h, h: shape.w } : shape;
  const g = bodyGeometry(look, natural, sideways ? H : W, sideways ? W : H);
  const st = _win.bezel.style;
  st.setProperty('--phw-rim', `${g.rim}px`);
  st.setProperty('--phw-radius', `${g.radius}px`);
  st.setProperty('--phw-inner', `${g.inner}px`);
  st.width = `${g.screenW}px`;
  st.height = `${g.screenH}px`;
  st.maxWidth = 'none';
  st.transform = `rotate(${rotation * 90}deg)`;
}

/** The stream laid in the bezel's screen at the phone screen's own shape,
 *  centred: a closed foldable's cover is the middle of that screen, and the
 *  bezel's narrower screen shows just it. */
function _placeFrame() {
  if (!_win || !_frame || !_state) return;
  if (!_state.screen_is_active && !isMobileView(_state)) {
    // Existing workstation images stream the whole inner screen. Keep their
    // original centred crop until the daemon is upgraded with active geometry.
    const [sw, sh] = _state.screen || [492, 1100];
    const h = _win.screen.clientHeight, w = h * sw / sh;
    Object.assign(_frame.style, { width: `${w}px`, height: `${h}px`,
      left: `${(_win.screen.clientWidth - w) / 2}px`, top: '0px', transform: 'none' });
    return;
  }
  const rotation = _state.rotation || 0;
  const w = _win.screen.clientWidth, h = _win.screen.clientHeight;
  const turned = rotation % 2 === 1;
  const width = turned ? h : w, height = turned ? w : h;
  _frame.style.width = `${width}px`;
  _frame.style.height = `${height}px`;
  _frame.style.left = `${(w - width) / 2}px`;
  _frame.style.top = `${(h - height) / 2}px`;
  _frame.style.transform = `rotate(${-rotation * 90}deg)`;
}

function _cancelMotion() {
  for (const a of _animations) a.cancel();
  _animations = [];
  if (_win) _win.bezel.classList.remove('phw-moving');
}

/** Animate acknowledged state, including movement performed by an agent.
 * The stream is the real device; no simulated OS is painted here. */
function _moveBody(s, previous) {
  const next = { device: s.device, rotation: s.rotation || 0, posture: s.posture,
    width: _win.bezel.style.width, height: _win.bezel.style.height };
  const old = _pose;
  _pose = next;
  if (!old || old.device !== next.device || prefersReducedMotion() || !_win.bezel.animate) return;
  const turn = rotationStep(old.rotation, next.rotation);
  const fold = old.posture && next.posture && old.posture !== next.posture;
  if (!turn && !fold) return;
  _cancelMotion();
  _win.bezel.classList.add('phw-moving');
  const opts = { duration: TIMING.MOTION_MS, easing: 'cubic-bezier(.22,.9,.24,1)' };
  const end = next.rotation * 90;
  const body = _win.bezel.animate([
    { width: previous.width, height: previous.height, transform: `rotate(${end - turn}deg)` },
    { width: next.width, height: next.height, transform: `rotate(${end}deg)` },
  ], opts);
  _animations.push(body);
  if (fold) {
    const closing = next.posture === 'closed';
    _animations.push(_win.leaf.animate([
      { opacity: 0, transform: `rotateY(${closing ? 0 : -150}deg)` },
      { opacity: .9, transform: 'rotateY(-80deg)', offset: .5 },
      { opacity: 0, transform: `rotateY(${closing ? -150 : 0}deg)` },
    ], opts));
  }
  body.onfinish = () => { if (_animations.includes(body)) _cancelMotion(); };
}

function _render() {
  if (!_win) return;
  const s = _state || { state: 'checking', devices: [] };
  const d = deviceOf(s);
  const on = s.state === 'on';
  const holding = _holder === 'person';
  const mobile = isMobileView(s);
  const stream = (on || s.state === 'starting') && !!_client;
  // `B1757`: a tablet is called one.
  const noun = d.kind === 'tablet' ? 'Tablet' : 'Phone';
  _win.title.textContent = d.name ? `${noun} · ${d.name}${mobile ? ' · mobile view' : ''}` : 'Mobile Emulator';
  _noun = noun.toLowerCase();
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
  _win.device.disabled = s.state === 'starting' || s.state === 'installing';
  _win.edition.value = s.edition || 'standard';
  _win.edition.options[0].textContent = {
    google_apis: 'Android · Google APIs (no Play Store)', google_play: 'Android · Google Play (configured image)',
    aosp: 'Android · AOSP (no Google Play)', custom: 'Android · Configured SDK image',
  }[s.standard_image_kind || 'custom'];
  _win.edition.disabled = _busy || s.state === 'starting' || s.state === 'installing';
  _win.preview.hidden = !s.preview_available || mobile || on || ['starting', 'installing'].includes(s.state);
  _win.preview.disabled = _busy;
  _win.stage.hidden = !s.mode;
  _win.profile.hidden = !s.mode;

  _win.power.textContent = mobile ? (on || s.state === 'starting' ? 'Close preview' : 'Open browser preview')
    : (on || s.state === 'starting' ? 'Turn off' : 'Turn on');
  _win.power.disabled = (!s.mode && !s.can_start) || s.state === 'installing';
  _win.rotate.hidden = !on;
  _win.fold.hidden = !(on && d.foldable);
  _win.fold.textContent = s.posture === 'closed' ? 'Unfold' : 'Fold';
  _win.take.hidden = !on || holding;
  _win.give.hidden = !on || !holding;
  _win.tools.hidden = !on;
  _win.nav.hidden = !on;
  _win.transfer.hidden = !(on && !mobile && s.isolation === 'per_user_vm');
  _win.transferText.textContent = _transferText || 'Files go to Download/Pantheon on your Android device. Each file is limited to 20 MB. No folders are mounted.';
  _win.upload.disabled = _sending;
  _win.docSend.disabled = _sending || !_win.docSelect.value;
  const runtime = runtimeOf(s);
  _win.runtime.setAttribute('aria-live', s.state === 'unavailable' ? 'polite' : 'off');
  _win.runtimeLabel.textContent = runtime.label;
  _win.runtimeText.textContent = runtime.detail;
  _win.runtime.dataset.mode = s.mode || 'unavailable';
  _win.profile.textContent = [d.name, d.width && d.height ? `${d.width} × ${d.height}` : '',
    s.mode === 'android' ? d.android : '', s.posture ? `${s.posture === 'closed' ? 'Folded' : 'Unfolded'}` : '',
    `Rotation ${(s.rotation || 0) * 90}°`].filter(Boolean).join(' · ');

  // `B1752`. The bezel: the device's shape, its keys on its maker's side.
  // `B1757`: and the device as it looks — its finish, its corners, its bezel,
  // its camera, its hinge and its keys on the edges they are on.
  const shape = bezelShape(s);
  const look = lookOf(d);
  _win.bezel.style.setProperty('--phw-aspect', `${shape.w} / ${shape.h}`);
  if (look.finish) _win.bezel.style.setProperty('--phw-finish', look.finish);
  else _win.bezel.style.removeProperty('--phw-finish');
  _win.bezel.dataset.kind = d.kind || 'phone';
  _win.bezel.dataset.maker = (d.maker || '').toLowerCase();
  _win.bezel.dataset.device = d.id || '';
  _win.bezel.dataset.cutout = d.foldable && s.posture === 'closed' && !mobile ? 'punch-center' : look.cutout;
  _win.bezel.dataset.posture = d.foldable ? (s.posture || 'open') : '';
  _win.bezel.title = look.finishName ? `${d.name} · ${look.finishName}` : (d.name || '');
  const previous = { width: _win.bezel.style.width, height: _win.bezel.style.height };
  const rotation = s.screen_is_active || mobile ? (s.rotation || 0) : 0;
  _shapeBody(shape, look, rotation);
  _moveBody({ ...s, rotation }, previous);
  if (_win.sideKeys.dataset.device !== d.id) {
    const sides = keysOf(d);
    for (const side of KEY_SIDES) {
      const box = _win.keyBoxes[side];
      box.textContent = '';
      for (const k of sides[side]) {
        const b = _el('button', `phw-side phw-side-${k.id}`);
        b.type = 'button';
        b.title = k.label;
        b.setAttribute('aria-label', k.label);
        b.dataset.key = k.id;
        b.addEventListener('click', (e) => { e.preventDefault(); press(k.id); });
        box.appendChild(b);
      }
      box.hidden = !sides[side].length;
    }
    _win.sideKeys.dataset.device = d.id || '';
  }
  for (const b of _win.bezel.querySelectorAll('.phw-side')) {
    b.disabled = b.dataset.key === 'power' ? (!s.mode || s.state === 'starting' || s.state === 'installing')
      : (!on || !keyWorks(s, b.dataset.key));
  }
  for (const b of _win.nav.querySelectorAll('button')) {
    b.disabled = !on || !keyWorks(s, b.dataset.key);
    b.hidden = mobile && b.dataset.androidOnly === 'true';
  }

  _renderInstall(s);
  if (_win.catalogue) _renderCatalogue(s);

  _win.screen.classList.toggle('phw-holding', holding);
  _win.empty.hidden = stream;
  _win.bezel.dataset.state = s.state || 'checking';
  if (stream) {
    _mountFrame();
    _placeFrame();
  } else {
    _dropFrame();
    _win.empty.textContent = s.state === 'off' && mobile ? 'Browser preview is closed. Open preview to browse web pages.'
      : s.state === 'starting' && !mobile ? (s.boot_phase === 'android' ? 'Android is booting. Connecting to its live display.' : 'Starting virtual hardware. Waiting for the Android display.')
      : s.state === 'unavailable' ? (s.why || 'There is no phone here.')
      : _words(mobile && s.state === 'starting' ? SAY.mobileStarting : (SAY[s.state] || SAY.checking));
  }
  if (_error) _say(_error, { error: true });
  else if (s.state === 'unavailable') _say(s.why || 'There is no phone here.', { error: true });
  else if (on && mobile && !holding) _say(SAY.mobile);
  else if (on) _say(holding ? (mobile ? 'You have the phone: click to tap, scroll to move the page.' : SAY.holding) : SAY.agent);
  else if (s.state === 'installing') _say(_installSay(s));
  else if (s.state === 'off' && installLine(s) && installLine(s).failed) _say(installLine(s).text, { error: true });
  else if (s.state === 'off' && mobile) _say('Browser preview is closed. Android is unavailable on this workstation.');
  else _say(mobile && s.state === 'starting' ? SAY.mobileStarting : (SAY[s.state] || SAY.checking));
  // The runtime card already explains an unavailable device. Keep a
  // distinct action error visible, without repeating the same paragraph.
  _win.status.hidden = s.state === 'unavailable' && (!_error || _error === runtime.detail);
}

function _installSay(s) {
  const line = installLine(s);
  if (!line) return SAY.installing;
  return line.percent === null ? `${line.text}…` : `${line.text}… ${line.percent}%`;
}

/** `B1756`. The install's bar and the license notice, in both the window and
 *  the room. */
function _renderInstall(s) {
  const line = installLine(s);
  _win.progress.hidden = !line || line.failed;
  if (line && !line.failed) {
    // The status line says the step; under the bar, what the download last said.
    const inst = s.install && typeof s.install === 'object' ? s.install : {};
    _win.progressText.textContent = String(inst.said || '');
    _win.progressText.hidden = !inst.said;
    if (line.percent === null) _win.progressBar.removeAttribute('value');
    else _win.progressBar.value = line.percent;
  }
  _win.license.hidden = !_pending;
  if (_pending) {
    const d = (s.devices || []).find((x) => x.id === _pending);
    _win.licenseText.textContent = `${d ? d.name : 'This device'} runs Google's Android system image, `
      + 'which Pantheon downloads to your workstation once (about 4 GB). It is offered under the '
      + 'Android Software Development Kit License Agreement for Android development and testing. '
      + (_state.edition === 'google_play' || _state.google_play ? 'This includes proprietary Google Play software. ' : '')
      + 'Each image keeps separate device data. Accept only if these terms cover your use.';
    const url = s.license && typeof s.license.url === 'string' && /^https:\/\//.test(s.license.url)
      ? s.license.url : 'https://developer.android.com/studio/terms';
    _win.licenseLink.href = url;
  }
}

/** `B1756`. Pick a device as a person does in the list: switch to it, install
 *  it if the workstation lacks it, and turn it on — the request the agent's
 *  `use_device` sends too. */
export function useDevice(id, { accept = false } = {}) {
  if (!_state || !_state.mode) return act({ action: 'device', device: id });
  if (isMobileView(_state)) return act({ action: 'preview', device: id });
  if (!accept && needsLicense(_state, id)) {
    _pending = id;
    _render();
    return Promise.resolve(null);
  }
  _pending = '';
  const payload = { action: 'install', device: id };
  if (accept) payload.accept_license = true;
  return act(payload);
}

function _renderCatalogue(s) {
  const groups = catalogueOf(s);
  const key = JSON.stringify(groups);
  if (_win.catalogue.dataset.key === key) return;
  _win.catalogue.dataset.key = key;
  _win.catalogue.textContent = '';
  if (!groups.length) {
    _win.catalogue.appendChild(_el('p', 'phw-cat-empty', s.state === 'unavailable'
      ? (s.why || 'There is no phone here.') : SAY.checking));
    return;
  }
  for (const g of groups) {
    const section = _el('section', 'phw-cat-group');
    section.appendChild(_el('h5', 'phw-cat-maker', g.maker || 'Devices'));
    const ul = _el('ul', 'phw-cat-list');
    for (const d of g.devices) {
      const li = _el('li', 'phw-cat-item');
      if (d.current) li.classList.add('phw-cat-current');
      li.dataset.device = d.id;
      const text = _el('div', 'phw-cat-text');
      text.appendChild(_el('span', 'phw-cat-name', d.name));
      // `B1757`: a swatch of the device's finish, named.
      const swatch = _el('span', 'phw-cat-swatch');
      swatch.setAttribute('aria-hidden', 'true');
      swatch.dataset.kind = d.kind;
      if (d.finish) swatch.style.setProperty('--phw-finish', d.finish);
      li.insertBefore(swatch, li.firstChild);
      const what = [d.kind === 'tablet' ? 'Tablet' : (d.foldable ? 'Foldable' : 'Phone')];
      if (d.finishName) what.push(d.finishName);
      text.appendChild(_el('span', 'phw-cat-facts', what.join(' · ')));
      const where = [];
      if (d.android && !isMobileView(s)) where.push(d.android);
      where.push(d.installed ? (isMobileView(s) ? 'Mobile view' : 'Installed') : 'Not installed');
      const status = _el('span', 'phw-cat-facts phw-cat-status', where.join(' · '));
      status.dataset.installed = d.installed ? 'yes' : 'no';
      text.appendChild(status);
      li.appendChild(text);
      const b = _button('phw-cat-use', d.verb, () => useDevice(d.id), `${d.verb}: ${d.name}`);
      b.disabled = d.busy || (d.current && d.verb === 'In use');
      li.appendChild(b);
      ul.appendChild(li);
    }
    section.appendChild(ul);
    _win.catalogue.appendChild(section);
  }
}

function _build({ embedded = false } = {}) {
  const modal = _el('div', embedded ? 'phw-room' : 'modal phw-modal');
  if (!embedded) modal.id = MODAL_ID;
  const content = _el('div', embedded ? 'phw-room-device' : 'modal-content phw-content');
  const header = _el('div', 'modal-header');
  const h = _el('h4', 'phw-heading');
  const icon = _el('span', 'phw-icon');
  icon.innerHTML = PHONE_ICON;   // a constant above, never server text
  const title = _el('span', 'phw-title', 'Mobile Emulator');
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
  const edition = document.createElement('select');
  edition.className = 'phw-edition';
  edition.setAttribute('aria-label', 'Android image');
  for (const [value, label] of [['standard', 'Android · Standard image'], ['google_play', 'Android · Google Play (developer image)']]) {
    const option = document.createElement('option'); option.value = value; option.textContent = label;
    edition.appendChild(option);
  }
  edition.addEventListener('change', () => { _pending = ''; act({ action: 'edition', edition: edition.value }); });
  const power = _button('phw-power', 'Turn on', () => {
    const s = _state && _state.state;
    if (s === 'on' || s === 'starting') act({ action: 'stop' });
    else _turnOn();
  }, 'Turn the phone on or off');
  const rotate = _button('phw-rotate', 'Rotate', () => act({ action: 'rotate' }), 'Turn the phone a quarter');
  const fold = _button('phw-fold', 'Fold', () => act({
    action: 'posture', posture: _state && _state.posture === 'closed' ? 'open' : 'closed',
  }), 'Fold or unfold the phone');
  const take = _button('phw-take', 'Take over', () => { takeOver(); });
  const give = _button('phw-give', 'Hand back', () => { handBack(); });
  bar.appendChild(device);
  bar.appendChild(edition);
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
  const tools = _el('details', 'phw-tools');
  tools.appendChild(_el('summary', '', 'Open a web address'));
  tools.appendChild(openForm);

  const runtime = _el('div', 'phw-runtime');
  runtime.setAttribute('role', 'status');
  runtime.setAttribute('aria-live', 'off');
  const runtimeLabel = _el('strong', 'phw-runtime-label', 'Checking Android');
  const runtimeText = _el('span', 'phw-runtime-text');
  runtime.appendChild(runtimeLabel);
  runtime.appendChild(runtimeText);
  const preview = _button('phw-preview', 'Open browser preview (web only)', () => act({ action: 'preview' }));
  preview.hidden = true;
  runtime.appendChild(preview);
  const profile = _el('div', 'phw-profile');

  const transfer = _el('details', 'phw-transfer');
  transfer.hidden = true;
  transfer.appendChild(_el('summary', '', 'USB tether · send files to Android'));
  const transferText = _el('p', 'phw-runtime-text');
  transferText.setAttribute('role', 'status');
  transferText.setAttribute('aria-live', 'polite');
  const file = document.createElement('input'); file.type = 'file'; file.hidden = true;
  file.addEventListener('change', () => { if (file.files[0]) _sendFile({ file: file.files[0] }); file.value = ''; });
  const upload = _button('phw-upload', 'Upload a file', () => file.click());
  const docSearch = document.createElement('input'); docSearch.type = 'search';
  docSearch.className = 'phw-address'; docSearch.placeholder = 'Search your documents';
  docSearch.setAttribute('aria-label', 'Search documents to send');
  const docFind = _button('phw-doc-find', 'Find documents', _findDocuments);
  const docSelect = document.createElement('select'); docSelect.className = 'phw-doc-select'; docSelect.hidden = true;
  docSelect.setAttribute('aria-label', 'Document to send as text');
  docSelect.addEventListener('change', () => _render());
  const docSend = _button('phw-doc-send', 'Send document text', () => {
    if (docSelect.value) _sendFile({ documentId: docSelect.value });
  });
  const transferRow = _el('div', 'phw-file-row'); transferRow.append(upload, file);
  const documentRow = _el('div', 'phw-file-row'); documentRow.append(docSearch, docFind, docSelect, docSend);
  transfer.append(transferText, transferRow, documentRow);

  const status = _el('div', 'ws-status phw-status');
  status.dataset.state = 'checking';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  const dot = _el('span', 'ws-status-dot');
  dot.setAttribute('aria-hidden', 'true');
  const statusText = _el('span', 'ws-status-text', SAY.checking);
  status.appendChild(dot);
  status.appendChild(statusText);

  // `B1752`. The device itself.
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
  // `B1757`: the keys on each edge they are on, the front camera (in the
  // screen or in the rim, as the device has it) and a foldable's crease.
  const sideKeysBox = _el('div', 'phw-side-keys');
  const keyBoxes = {};
  for (const side of KEY_SIDES) {
    keyBoxes[side] = _el('div', `phw-keys phw-keys-${side}`);
    sideKeysBox.appendChild(keyBoxes[side]);
  }
  const camera = _el('span', 'phw-camera');
  camera.setAttribute('aria-hidden', 'true');
  const hinge = _el('span', 'phw-hinge');
  hinge.setAttribute('aria-hidden', 'true');
  screen.appendChild(hinge);
  const leaf = _el('span', 'phw-fold-leaf');
  leaf.setAttribute('aria-hidden', 'true');
  screen.appendChild(leaf);
  bezel.appendChild(speaker);
  bezel.appendChild(screen);
  bezel.appendChild(camera);
  bezel.appendChild(sideKeysBox);
  stage.appendChild(bezel);

  const nav = _el('div', 'phw-nav');
  nav.setAttribute('role', 'toolbar');
  nav.setAttribute('aria-label', 'Android device controls');
  for (const [glyph, key, label] of [
    ['Back', 'back', 'Back'], ['Home', 'home', 'Home'], ['Apps', 'recents', 'Recent apps'],
    ['Vol −', 'volume_down', 'Volume down'], ['Vol +', 'volume_up', 'Volume up'],
    ['Sleep / wake', 'power', 'Sleep or wake Android'],
  ]) {
    const b = _button('phw-nav-btn', glyph, () => press(key), label);
    b.dataset.key = key;
    if (['volume_down', 'volume_up', 'power'].includes(key)) b.dataset.androidOnly = 'true';
    nav.appendChild(b);
  }

  // `B1756`. The install's progress, and the license a person accepts once.
  const progress = _el('div', 'phw-progress');
  progress.hidden = true;
  const progressText = _el('span', 'phw-progress-text');
  const progressBar = document.createElement('progress');
  progressBar.className = 'phw-progress-bar';
  progressBar.max = 100;
  progressBar.setAttribute('aria-label', 'Install progress');
  progress.appendChild(progressText);
  progress.appendChild(progressBar);

  const license = _el('div', 'phw-license');
  license.hidden = true;
  license.setAttribute('role', 'region');
  license.setAttribute('aria-label', 'Android SDK License');
  const licenseText = _el('p', 'phw-license-text');
  const licenseLink = _el('a', 'phw-license-link', 'Read the license');
  licenseLink.target = '_blank';
  licenseLink.rel = 'noopener noreferrer';
  const licenseRow = _el('div', 'phw-license-row');
  const accept = _button('phw-license-accept', 'Accept and install', () => {
    if (_pending) useDevice(_pending, { accept: true });
  });
  const decline = _button('phw-license-decline', 'Not now', () => { _pending = ''; _render(); });
  licenseRow.appendChild(licenseLink);
  licenseRow.appendChild(decline);
  licenseRow.appendChild(accept);
  license.appendChild(licenseText);
  license.appendChild(licenseRow);

  if (embedded) {
    // The list beside it is the room's device picker; the select would say it twice.
    device.hidden = true;
    header.classList.remove('modal-header');
    header.classList.add('phw-room-head');
    close.remove();   // the room is closed with the Workbench
  }
  content.appendChild(header);
  content.appendChild(bar);
  content.appendChild(runtime);
  content.appendChild(status);
  content.appendChild(progress);
  content.appendChild(license);
  content.appendChild(stage);
  content.appendChild(profile);
  content.appendChild(nav);
  content.appendChild(tools);
  content.appendChild(transfer);

  let catalogue = null;
  if (embedded) {
    const aside = _el('div', 'phw-catalogue');
    aside.appendChild(_el('h4', 'phw-cat-head', 'Select a device'));
    aside.appendChild(_el('p', 'phw-cat-lede', 'Pick a phone or tablet to use. One not on your '
      + 'workstation yet is downloaded, installed and set up for you, then turned on. '
      + 'Your agents use the same phone, the same way.'));
    catalogue = _el('div', 'phw-cat-groups');
    aside.appendChild(catalogue);
    modal.appendChild(aside);
  }
  modal.appendChild(content);

  return { modal, content, header, title, device, edition, preview, power, rotate, fold, take, give, openForm, address,
    transfer, transferText, upload, docSearch, docFind, docSelect, docSend,
    tools, runtime, runtimeLabel, runtimeText, profile, leaf,
    status, statusText, stage, bezel, screen, empty, glass, sideKeys: sideKeysBox, keyBoxes, camera, hinge, nav,
    progress, progressText, progressBar, license, licenseText, licenseLink, catalogue, embedded };
}

function _teardown() {
  if (!_win) return;
  ++_revision;
  ++_actionSequence;
  ++_controlSequence;
  _busy = false;
  _cancelMotion();
  if (_win.observer) _win.observer.disconnect();
  if (_timer) { clearTimeout(_timer); _timer = null; }
  if (_holder === 'person' || _pendingTakeovers.has(_win)) {
    _queueControl('agent', true).catch((e) => {
      console.warn('The phone could not hand control back:', e.message);
    });
  }
  _dropFrame();
  const modal = _win.modal;
  const embedded = _win.embedded;
  _win = null;
  _state = null;
  _client = '';
  _holder = null;
  _pending = '';
  _pose = null;
  _screenKey = '';
  _error = '';
  _sending = false;
  _transferText = '';
  if (modal.parentNode) modal.parentNode.removeChild(modal);
  // The room keeps its place: a note says where the phone went (`B1756`).
  if (embedded && _room) {
    _room.textContent = '';
    _room.appendChild(_el('p', 'phw-room-moved', SAY.moved));
  }
}

function _resume() { _kick(0); }

function _observeSize() {
  if (!_win || typeof ResizeObserver !== 'function') return;
  _win.observer = new ResizeObserver(() => {
    if (!_win) return;
    _render();
    if (!_roomHidden()) _kick(0);
  });
  _win.observer.observe(_win.stage);
}

/** Open the window, or bring it forward. */
export function openPhone() {
  if (_win && Modals.isRegistered(MODAL_ID)) {
    if (Modals.isMinimized(MODAL_ID)) Modals.restore(MODAL_ID);
    else Modals.showWindow(MODAL_ID);
    _resume();
    return true;
  }
  if (_win) _teardown();   // the room's copy gives way to the window (`B1756`)
  _win = _build();
  document.body.appendChild(_win.modal);
  _observeSize();
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

/** `B1756`. The Workbench's Phone room: the device list beside the phone
 *  itself — the same window's parts, laid in the room. One copy runs at a time
 *  (one stream, one poll): showing the room closes the window, and opening the
 *  window leaves the room a note until it is shown again. */
let _roomGen = 0;
export function mountPhoneRoom(host) {
  _room = host;
  const gen = ++_roomGen;
  const show = () => {
    if (gen !== _roomGen) return;   // a later mount owns the room
    if (_win && _win.embedded && _win.modal.parentNode === host) { _resume(); return; }
    if (_win) {
      if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
      if (_win) _teardown();
    }
    host.textContent = '';
    _win = _build({ embedded: true });
    host.appendChild(_win.modal);
    _observeSize();
    _render();
    _kick(0);
  };
  show();
  return {
    shown: show,
    destroy() {
      if (gen !== _roomGen) return;   // already given way to a later mount
      _room = null;
      if (_win && _win.embedded) _teardown();
      host.textContent = '';
    },
  };
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
  _global.addEventListener('resize', () => { if (_win) _render(); });
}

export const _test = {
  TIMING, tick: _tick, win: () => _win, pending: () => _pending,
  state: () => ({ open: !!_win, state: _state, holder: _holder, client: _client, frame: _frame }),
};

export default { openPhone, closePhone, press, act, takeOver, handBack, useDevice, mountPhoneRoom };
