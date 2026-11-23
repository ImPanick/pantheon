// SPDX-License-Identifier: AGPL-3.0-or-later
// Apollo's orb (phase 6): a small sun that floats over the page while Apollo's
// chat is open. It breathes at rest, pulses while the person dictates, swirls
// while Apollo thinks, ripples with its voice when a reply is read aloud, and
// turns amber when something needs the person. Apollo can move it to point at
// something: the pane, one task, the composer, or a line range in a code block
// or in any code view that registers itself here.
//
// It is never docked: the person drags it where they like, and it goes back
// there after pointing. A click opens Apollo's pane. "Keep it still" (or the
// operating system's reduced motion) draws it at rest and moves it without
// gliding; "Show the orb" off removes it. Both live in this browser.
//
// What moves it:
//   `pantheon:chat-busy-change` (chat.js)       thinking
//   `pantheon:dictation`        (voiceRecorder) listening
//   `pantheon:speaking`         (tts-ai.js)     speaking, with the audio element
//   `pantheon:apollo-state`     (apolloPane.js) needs you
//   `pantheon:orb-show`         (chatStream.js) a place to point at, from the
//                                               model's `ui_control show`
// A code view (an editor, a diff) registers with
//   window.pantheonOrb.registerCodeView(name, { element(), rangeRects(from, to), reveal(from, to) })
// and Apollo can then point at its lines with `show view <name> lines=A-B`.

import * as M from './apolloOrbModel.js';
import { prefersReducedMotion, scrollBehavior } from './motion.js';

export const SIZE = 56;
const KEYS = { show: 'pantheon.apolloOrb.show', still: 'pantheon.apolloOrb.still', pos: 'pantheon.apolloOrb.pos' };
const POLL_MS = 60000;      // a look at Needs you while the pane is shut
const SPOT_MS = 12000;      // how long a show stays before the orb goes back
const GLIDE_MS = 650;
const FIND_MS = 2500;       // how long to wait for the pane to draw a place

let _apolloChat = false;
let _root = null;           // { el, canvas, ctx, say, spot }
const _signals = { listening: false, speaking: false, thinking: false, needs: false };
let _at = null;             // where it is now
let _glide = null;          // { from, to, start }
let _raf = 0;
let _poll = 0;
let _show = null;           // { rect: () => rect|null, timer }
let _audio = null;          // { ctx, analyser, buf, el }
let _drag = null;
const _views = new Map();
const _sources = new WeakSet();

/* ───────────── what the person set ───────────── */

function _read(key, fallback) {
  try {
    const v = globalThis.localStorage && localStorage.getItem(key);
    return v === null || v === undefined ? fallback : v;
  } catch (_) { return fallback; }
}

function _write(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch (_) { /* private window: it just won't be remembered */ }
}

export function orbShown() { return _read(KEYS.show, '1') !== '0'; }
export function orbStill() { return _read(KEYS.still, '0') === '1'; }
function _still() { return orbStill() || prefersReducedMotion(); }

export function setOrbShown(on) { _write(KEYS.show, on ? '1' : '0'); _sync(); }
export function setOrbStill(on) { _write(KEYS.still, on ? '1' : '0'); _glide = null; _place(_at); _loop(); }

function _saved() {
  try {
    const p = JSON.parse(_read(KEYS.pos, 'null'));
    return p && Number.isFinite(p.x) && Number.isFinite(p.y) ? p : null;
  } catch (_) { return null; }
}

function _vw() { return window.innerWidth || 1024; }
function _vh() { return window.innerHeight || 768; }

/** Where it rests: where the person last put it, else home. */
function _rest() {
  const p = _saved();
  return p ? M.clamp(p, SIZE, _vw(), _vh()) : M.home(SIZE, _vw(), _vh());
}

/* ───────────── showing and hiding ───────────── */

/** The Apollo chat opened (true) or closed (false); `assistant.js` says. */
export function setApolloChat(on) {
  _apolloChat = !!on;
  _sync();
}

function _sync() {
  const want = _apolloChat && orbShown();
  if (want && !_root) _mount();
  else if (!want && _root) _unmount();
}

function _mount() {
  const el = document.createElement('div');
  el.id = 'apollo-orb';
  el.className = 'apollo-orb';
  el.tabIndex = 0;
  el.setAttribute('role', 'button');
  const canvas = document.createElement('canvas');
  canvas.className = 'apollo-orb-canvas';
  const dpr = Math.min(3, window.devicePixelRatio || 1);
  canvas.width = Math.round(SIZE * dpr);
  canvas.height = Math.round(SIZE * dpr);
  canvas.setAttribute('aria-hidden', 'true');
  el.appendChild(canvas);
  const say = document.createElement('div');
  say.className = 'apollo-orb-say';
  say.setAttribute('role', 'status');
  say.setAttribute('aria-live', 'polite');
  say.hidden = true;
  const spot = document.createElement('div');
  spot.className = 'apollo-orb-spot';
  spot.setAttribute('aria-hidden', 'true');
  spot.hidden = true;
  document.body.appendChild(spot);
  document.body.appendChild(el);
  document.body.appendChild(say);
  let ctx = null;
  try { ctx = canvas.getContext && canvas.getContext('2d'); } catch (_) { ctx = null; }
  if (ctx && ctx.setTransform) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  _root = { el, canvas, ctx, say, spot };
  el.addEventListener('pointerdown', _down);
  el.addEventListener('keydown', _key);
  el.addEventListener('click', _click);
  _place(_rest());
  _label();
  _loop();
  _startPoll();
}

function _unmount() {
  _endShow(false);
  if (_raf) cancelAnimationFrame(_raf);
  _raf = 0;
  if (_poll) clearInterval(_poll);
  _poll = 0;
  for (const k of ['el', 'say', 'spot']) _root[k].remove();
  _root = null;
  _glide = null;
}

export function isOrbShowing() { return !!_root; }

/* ───────────── the person moves it ───────────── */

function _down(ev) {
  if (ev.button !== undefined && ev.button !== 0) return;
  _drag = { sx: ev.clientX, sy: ev.clientY, ox: _at.x, oy: _at.y, moved: false };
  try { _root.el.setPointerCapture(ev.pointerId); } catch (_) { /* old browsers */ }
  _root.el.addEventListener('pointermove', _move);
  _root.el.addEventListener('pointerup', _up, { once: true });
  _root.el.addEventListener('pointercancel', _up, { once: true });
}

function _move(ev) {
  if (!_drag) return;
  const dx = ev.clientX - _drag.sx;
  const dy = ev.clientY - _drag.sy;
  if (!_drag.moved && Math.hypot(dx, dy) < 4) return;
  _drag.moved = true;
  _glide = null;
  _place(M.clamp({ x: _drag.ox + dx, y: _drag.oy + dy }, SIZE, _vw(), _vh()));
}

function _up() {
  if (!_root) return;
  _root.el.removeEventListener('pointermove', _move);
  if (_drag && _drag.moved) {
    _write(KEYS.pos, JSON.stringify(_at));
    _endShow(false);   // they've put it somewhere: it stays there
    _root.el.dataset.dragged = '1';
  }
  _drag = null;
}

function _click() {
  if (_root && _root.el.dataset.dragged) { delete _root.el.dataset.dragged; return; }
  _openPane();
}

function _key(ev) {
  const step = ev.shiftKey ? 48 : 16;
  const by = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[ev.key];
  if (by) {
    ev.preventDefault();
    _glide = null;
    _place(M.clamp({ x: _at.x + by[0], y: _at.y + by[1] }, SIZE, _vw(), _vh()));
    _write(KEYS.pos, JSON.stringify(_at));
    return;
  }
  if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); _openPane(); }
  if (ev.key === 'Escape' && _show) _endShow(true);
}

function _openPane() {
  import('./apolloPane.js').then((m) => m.openApolloPane()).catch(() => {});
}

/* ───────────── where it is ───────────── */

function _place(p) {
  if (!_root || !p) return;
  _at = { x: p.x, y: p.y };
  _root.el.style.transform = `translate(${Math.round(p.x)}px, ${Math.round(p.y)}px)`;
  _sayAt();
}

/** Glide to `p`; jump there when it should keep still. */
export function glideTo(p) {
  if (!_root) return false;
  const to = M.clamp(p, SIZE, _vw(), _vh());
  if (_still()) { _glide = null; _place(to); return true; }
  _glide = { from: { ..._at }, to, start: _now() };
  _loop();
  return true;
}

function _stepGlide(now) {
  if (!_glide) return;
  const k = Math.min(1, (now - _glide.start) / GLIDE_MS);
  const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
  _place({ x: _glide.from.x + (_glide.to.x - _glide.from.x) * e, y: _glide.from.y + (_glide.to.y - _glide.from.y) * e });
  if (k >= 1) _glide = null;
}

function _sayAt() {
  if (!_root || _root.say.hidden) return;
  const left = _at.x + SIZE + 8 + 260 > _vw() ? Math.max(8, _at.x - 268) : _at.x + SIZE + 8;
  _root.say.style.transform = `translate(${Math.round(left)}px, ${Math.round(_at.y + SIZE / 2 - 16)}px)`;
}

/* ───────────── mood and drawing ───────────── */

export function currentMood() { return M.mood(_signals); }

function _label() {
  if (!_root) return;
  const m = currentMood();
  _root.el.dataset.mood = m;
  _root.el.setAttribute('aria-label', `Apollo, ${M.MOOD_WORDS[m]}. Opens Apollo's pane. Arrow keys move it.`);
}

function _now() { return (globalThis.performance && performance.now) ? performance.now() : Date.now(); }

function _loop() {
  if (!_root || _raf) return;
  if (typeof requestAnimationFrame !== 'function') { _paint(0); return; }
  const tick = (now) => {
    _raf = 0;
    if (!_root) return;
    _stepGlide(now);
    _follow();
    _paint(now / 1000);
    // Still and settled: one frame is enough until something changes.
    const moving = !_still() || _glide || _show;
    if (moving && !(typeof document !== 'undefined' && document.hidden)) _raf = requestAnimationFrame(tick);
  };
  _raf = requestAnimationFrame(tick);
}

function _levelNow() {
  if (!_audio || !_audio.analyser) return null;
  try {
    _audio.analyser.getByteTimeDomainData(_audio.buf);
    let sum = 0;
    for (let i = 0; i < _audio.buf.length; i += 1) { const v = (_audio.buf[i] - 128) / 128; sum += v * v; }
    return Math.min(1, Math.sqrt(sum / _audio.buf.length) * 4);
  } catch (_) { return null; }
}

function _paint(t) {
  const c = _root && _root.ctx;
  if (!c) return;
  const m = currentMood();
  const L = M.look(m);
  const still = _still();
  const level = m === 'speaking' ? _levelNow() : null;
  const g = M.glow(m, t, level, still);
  const mid = SIZE / 2;
  const r = SIZE * 0.2 * g;
  c.clearRect(0, 0, SIZE, SIZE);
  const halo = c.createRadialGradient(mid, mid, r * 0.6, mid, mid, SIZE * 0.48);
  halo.addColorStop(0, `${L.halo}0.55)`);
  halo.addColorStop(1, `${L.halo}0)`);
  c.fillStyle = halo;
  c.beginPath(); c.arc(mid, mid, SIZE * 0.48, 0, Math.PI * 2); c.fill();
  if (!still && L.ring) {
    for (let i = 0; i < L.ring; i += 1) {
      const p = ((t / L.period) + i / L.ring) % 1;
      c.strokeStyle = `${L.halo}${(0.5 * (1 - p)).toFixed(3)})`;
      c.lineWidth = 1.5;
      c.beginPath(); c.arc(mid, mid, r * (1.1 + p * 1.1), 0, Math.PI * 2); c.stroke();
    }
  }
  const core = c.createRadialGradient(mid - r * 0.3, mid - r * 0.3, r * 0.1, mid, mid, r);
  core.addColorStop(0, '#fffbe8');
  core.addColorStop(0.45, L.core);
  core.addColorStop(1, L.rim);
  c.fillStyle = core;
  c.beginPath(); c.arc(mid, mid, r, 0, Math.PI * 2); c.fill();
  if (L.swirl) {
    const a0 = still ? 0 : t * L.swirl * Math.PI;
    c.strokeStyle = `${L.halo}0.8)`;
    c.lineWidth = 2;
    c.lineCap = 'round';
    for (let i = 0; i < 3; i += 1) {
      const a = a0 + (i * Math.PI * 2) / 3;
      c.beginPath(); c.arc(mid, mid, r * 1.35, a, a + 0.9); c.stroke();
    }
  }
}

function _changed() {
  _label();
  _loop();
}

/* ───────────── its voice ───────────── */

function _hear(audio) {
  _audio = null;
  // Only a same-origin or blob voice is routed through an analyser: routing a
  // cross-origin one would silence it, and routing into a context that isn't
  // running yet would too. Anything else gets the speaking mood's own beat.
  if (!audio || typeof audio !== 'object' || !('src' in audio)) return;
  const Ctx = globalThis.AudioContext || globalThis.webkitAudioContext;
  if (!Ctx) return;
  let same = false;
  try {
    const u = new URL(audio.currentSrc || audio.src, location.href);
    same = u.protocol === 'blob:' || u.protocol === 'data:' || u.origin === location.origin;
  } catch (_) { same = false; }
  if (!same || _sources.has(audio)) return;
  try {
    const ctx = _hear.ctx || (_hear.ctx = new Ctx());
    if (ctx.state !== 'running') { ctx.resume && ctx.resume().catch(() => {}); return; }
    const src = ctx.createMediaElementSource(audio);
    _sources.add(audio);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    src.connect(analyser);
    analyser.connect(ctx.destination);
    _audio = { ctx, analyser, buf: new Uint8Array(analyser.fftSize), el: audio };
  } catch (_) { _audio = null; }
}

/* ───────────── pointing ───────────── */

/** Point at a rect (or a function returning one, followed as the page
 *  scrolls), with `words` beside the orb. */
export function point(rect, words = '') {
  if (!_root) return false;
  const get = typeof rect === 'function' ? rect : () => rect;
  const r = get();
  if (!r) return false;
  _endShow(false);
  _show = { rect: get, timer: setTimeout(() => _endShow(true), SPOT_MS) };
  _spotTo(r);
  glideTo(M.besideRect(r, SIZE, _vw(), _vh()));
  _say(words);
  return true;
}

function _spotTo(r) {
  const s = _root.spot;
  s.hidden = false;
  s.style.transform = `translate(${Math.round(r.left - 4)}px, ${Math.round(r.top - 4)}px)`;
  s.style.width = `${Math.round(r.width + 8)}px`;
  s.style.height = `${Math.round(r.height + 8)}px`;
}

function _say(words) {
  if (!_root) return;
  _root.say.textContent = words || '';
  _root.say.hidden = !words;
  _sayAt();
}

function _follow() {
  if (!_show || _glide) return;
  const r = _show.rect();
  if (!r) return;
  _spotTo(r);
}

function _endShow(goBack) {
  if (_show && _show.timer) clearTimeout(_show.timer);
  _show = null;
  if (!_root) return;
  _root.spot.hidden = true;
  _say('');
  if (goBack) glideTo(_rest());
}

/** Back to where the person put it. */
export function goHome() { _endShow(true); }

function _rectOf(el) {
  if (!el || !el.getBoundingClientRect) return null;
  const b = el.getBoundingClientRect();
  return { left: b.left, top: b.top, width: b.width, height: b.height };
}

/** The band round lines `from`..`to` of a code element (its text, measured
 *  with a Range so wrapping and padding count), as wide as the block. */
export function codeRange(code, from, to) {
  if (!code) return null;
  const span = M.lineSpan(code.textContent, from, to);
  if (!span) return null;
  const box = code.closest ? (code.closest('pre') || code) : code;
  const at = (off) => {
    const walk = document.createTreeWalker(code, 4 /* NodeFilter.SHOW_TEXT */);
    let seen = 0;
    let node = walk.nextNode();
    let last = null;
    while (node) {
      const n = node.nodeValue.length;
      if (off <= seen + n) return [node, off - seen];
      seen += n;
      last = node;
      node = walk.nextNode();
    }
    return last ? [last, last.nodeValue.length] : null;
  };
  const a = at(span[0]);
  const b = at(span[1]);
  if (!a || !b) return null;
  let rects = [];
  try {
    const range = document.createRange();
    range.setStart(a[0], a[1]);
    range.setEnd(b[0], b[1]);
    rects = Array.from(range.getClientRects()).map((r) => ({ left: r.left, top: r.top, width: r.width, height: r.height }));
  } catch (_) { return null; }
  const band = M.union(rects);
  const outer = _rectOf(box);
  if (!band || !outer) return band || outer;
  return { left: outer.left, top: band.top, width: outer.width, height: band.height };
}

/** Bring lines into view inside a scrolling block, then mark them. */
export function highlightCode(code, from, to, words = '') {
  if (!code) return false;
  const box = code.closest ? (code.closest('pre') || code) : code;
  try { box.scrollIntoView({ block: 'nearest', behavior: scrollBehavior() }); } catch (_) { /* detached */ }
  const band = codeRange(code, from, to);
  const outer = _rectOf(box);
  if (band && outer && box.scrollHeight > box.clientHeight
      && (band.top < outer.top || band.top + band.height > outer.top + outer.height)) {
    box.scrollTop += band.top - outer.top - outer.height / 3;
  }
  return point(() => codeRange(code, from, to), words || M.showWords({ lines: [from, to] }));
}

/** An editor, a diff or any code view says how to find its lines. */
export function registerCodeView(name, adapter) {
  const key = String(name || '').trim();
  if (!key || !adapter) return () => {};
  _views.set(key, adapter);
  return () => { if (_views.get(key) === adapter) _views.delete(key); };
}

export function codeViews() { return Array.from(_views.keys()); }

function _wait(find) {
  return new Promise((resolve) => {
    const start = Date.now();
    const look = () => {
      const el = find();
      if (el || Date.now() - start > FIND_MS) return resolve(el || null);
      setTimeout(look, 100);
    };
    look();
  });
}

function _paneEl() { return document.getElementById('apollo-pane-modal'); }

function _paneSection(title) {
  const pane = _paneEl();
  if (!pane) return null;
  return Array.from(pane.querySelectorAll('.apo-sec'))
    .find((s) => { const t = s.querySelector('.apo-sec-t'); return t && t.textContent.trim() === title; }) || null;
}

function _paneTask(id) {
  const pane = _paneEl();
  if (!pane) return null;
  return Array.from(pane.querySelectorAll('[data-task-id]')).find((e) => e.dataset.taskId === String(id)) || null;
}

async function _withPane(find) {
  try {
    const P = await import('./apolloPane.js');
    if (!P.isApolloPaneOpen()) P.openApolloPane();
  } catch (_) { return null; }
  return _wait(find);
}

/** Follow one `show` from the model. Resolves true when it pointed. */
export async function show(detail) {
  const s = M.readShow(detail);
  if (!s || !_root) return false;
  if (s.place === 'home') { goHome(); return true; }
  let el = null;
  let words = s.words;
  if (s.place === 'pane') el = await _withPane(_paneEl);
  else if (s.place === 'needs_you') el = await _withPane(() => _paneSection('Needs you'));
  else if (s.place === 'activity') el = await _withPane(() => _paneSection('Activity'));
  else if (s.place === 'task') {
    el = await _withPane(() => _paneTask(s.target));
    if (!el) { el = _paneEl(); words = words || "That task isn't in the list right now."; }
  } else if (s.place === 'chat_input') el = document.getElementById('message');
  else if (s.place === 'selector') {
    try { el = document.querySelector(s.selector); } catch (_) { el = null; }
    if (s.glideOnly && el) {
      const r = _rectOf(el);
      if (r) glideTo(M.besideRect(r, SIZE, _vw(), _vh()));
      return !!r;
    }
  } else if (s.place === 'code') {
    const blocks = Array.from(document.querySelectorAll('#chat-container pre > code'));
    const n = Number.isInteger(s.target) ? s.target : 1;
    const code = blocks[blocks.length - n] || null;
    if (code && s.lines) return highlightCode(code, s.lines[0], s.lines[1], words);
    el = code ? (code.closest('pre') || code) : null;
  } else if (s.place === 'view') {
    const v = _views.get(String(s.target));
    if (!v) return false;
    try {
      if (s.lines && v.reveal) await v.reveal(s.lines[0], s.lines[1]);
      if (s.lines && v.rangeRects) {
        const get = () => M.union((v.rangeRects(s.lines[0], s.lines[1]) || []).map((r) => ({ left: r.left, top: r.top, width: r.width, height: r.height })));
        return point(get, words);
      }
      el = v.element ? v.element() : null;
    } catch (_) { return false; }
  }
  if (!el) return false;
  try { el.scrollIntoView({ block: 'nearest', behavior: scrollBehavior() }); } catch (_) { /* detached */ }
  return point(() => _rectOf(el), words);
}

/* ───────────── Needs you while the pane is shut ───────────── */

async function _look() {
  if (!_root || (typeof document !== 'undefined' && document.hidden)) return;
  try {
    const P = await import('./apolloPane.js');
    if (P.isApolloPaneOpen()) return;   // the pane says it itself
  } catch (_) { /* no pane: look anyway */ }
  let space = '';
  try { space = (await import('./apolloSpaces.js')).spaceParam() || ''; } catch (_) { space = ''; }
  try {
    const r = await fetch(`/api/apollo/state${space ? `?space=${encodeURIComponent(space)}` : ''}`, { credentials: 'same-origin' });
    if (!r.ok) return;
    const st = await r.json();
    _signals.needs = !!(st && st.status && st.status.state === 'needs_you');
    _changed();
  } catch (_) { /* offline: keep what it had */ }
}

function _startPoll() {
  _look();
  if (typeof setInterval === 'function') _poll = setInterval(_look, POLL_MS);
}

/* ───────────── listening to the page ───────────── */

function _on(target, type, fn) {
  if (target && target.addEventListener) target.addEventListener(type, fn);
}

_on(window, 'pantheon:chat-busy-change', (ev) => { _signals.thinking = !!(ev.detail && ev.detail.active); _changed(); });
_on(window, 'pantheon:dictation', (ev) => { _signals.listening = !!(ev.detail && ev.detail.state === 'listening'); _changed(); });
_on(window, 'pantheon:speaking', (ev) => {
  const d = ev.detail || {};
  _signals.speaking = !!d.active;
  if (d.active) _hear(d.audio);
  else _audio = null;
  _changed();
});
_on(document, 'pantheon:apollo-state', (ev) => { _signals.needs = !!(ev.detail && ev.detail.tone === 'needs'); _changed(); });
_on(document, 'pantheon:orb-show', (ev) => { show(ev.detail); });
_on(document, 'visibilitychange', () => { if (!document.hidden) _loop(); });
_on(window, 'resize', () => { if (_root && !_show) _place(_rest()); });

if (typeof window !== 'undefined') {
  window.pantheonOrb = { show, point, glideTo, goHome, highlightCode, registerCodeView, codeViews, currentMood };
}
