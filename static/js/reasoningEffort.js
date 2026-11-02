// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/reasoningEffort.js
//
// Reasoning effort: how hard a thinking model is asked to think — Auto (the
// model's own default), Low, Medium, High, Extra, Max.
//
// One chip at the bottom of the composer, beside the approval mode, that names
// the level and opens a menu of the six. It is shown only while the selected
// model has some way to take a level: the server says so
// (`GET /api/chat/reasoning-effort`, `src/reasoning_effort.py`) and sends, per
// level, one line on how that level reaches this model (its own setting, or
// words in the system prompt where its setting stops short). Asked again
// whenever the model or chat changes.
//
// The level is this person's, in this browser (`localStorage`), and goes with
// every send as `reasoning_effort` while the chip is shown. Typing
// `ultrathink` in a message runs that one turn at Max (the server reads it).
//
// The menu is the model picker's (`.model-picker-menu`, `.model-switch-item`,
// `pickerKeys.js`), dismissed through the one Escape stack, as the approval
// mode's is (`Law 14`).

import { bindMenuDismiss } from './escMenuStack.js';
import { whenShut } from './motion.js';
import { handlePickerKeydown } from './pickerKeys.js';

const STORE_KEY = 'pantheon-reasoning-effort';
const AUTO = 'auto';
const LEVELS = ['low', 'medium', 'high', 'extra', 'max'];
const LABELS = { auto: 'Auto', low: 'Low', medium: 'Medium', high: 'High', extra: 'Extra', max: 'Max' };
const ITEM = '.reasoning-effort-item';

let _level = _readStored();
let _support = null;        // the server's last answer for the selected model
let _routeOf = null;        // () => {model, endpoint_url, endpoint_id}
let _seq = 0;
let _dismiss = null;
let _chipShown = null;

function _readStored() {
  try {
    const v = localStorage.getItem(STORE_KEY);
    return v === AUTO || LEVELS.includes(v) ? v : AUTO;
  } catch (_) {
    return AUTO;
  }
}

function _store(level) {
  try { localStorage.setItem(STORE_KEY, level); } catch (_) { /* private window */ }
}

function _nodes() {
  const doc = typeof document !== 'undefined' ? document : null;
  if (!doc) return {};
  return {
    wrap: doc.getElementById('reasoning-effort-wrap'),
    chip: doc.getElementById('reasoning-effort-btn'),
    label: doc.getElementById('reasoning-effort-label'),
    menu: doc.getElementById('reasoning-effort-menu'),
    options: doc.getElementById('reasoning-effort-options'),
  };
}

function _items(n) {
  return n.options ? [...n.options.querySelectorAll(ITEM)] : [];
}

// What each level does for the person, in the owner's words (2026-11-01).
// How it reaches this model (its own setting, or a note) is the row's tooltip.
const WHAT = {
  auto: "The model's own default.",
  low: 'Light thinking. Quick replies.',
  medium: 'Thinks a little harder. A bit more detail.',
  high: 'Thinks hard. Takes longer to reply.',
  extra: 'Thinks hardest. Fuller, longer answers.',
  max: 'Ultrathink: checks its own work before you see it.',
};

function _howFor(level) {
  if (level === AUTO) return 'Nothing is sent.';
  const row = _support && Array.isArray(_support.levels)
    ? _support.levels.find((l) => l && l.id === level) : null;
  return row && row.how ? row.how : '';
}

/** Whether the chip is up: the model takes a level. */
export function isShown() {
  return !!(_support && _support.supported);
}

/** The level a send carries, or '' when it carries none. */
export function levelForSend() {
  return isShown() && _level !== AUTO ? _level : '';
}

export function currentLevel() {
  return _level;
}

export function render() {
  const n = _nodes();
  const shown = isShown();
  if (n.wrap) n.wrap.style.display = shown ? '' : 'none';
  if (n.chip) {
    n.chip.style.display = shown ? '' : 'none';
    n.chip.classList.toggle('active', _level !== AUTO);
    n.chip.dataset.level = _level;
    const name = `Reasoning effort: ${LABELS[_level]}`;
    n.chip.setAttribute('aria-label', name);
    n.chip.title = name + ' (type "ultrathink" in a message for one turn at Max)';
  }
  if (n.label) n.label.textContent = LABELS[_level];
  for (const item of _items(n)) {
    const level = item.getAttribute('data-effort');
    item.setAttribute('aria-checked', level === _level ? 'true' : 'false');
    const desc = item.querySelector('.reasoning-effort-item-desc');
    if (desc) desc.textContent = WHAT[level] || '';
    const how = _howFor(level);
    if (how) item.title = how; else item.removeAttribute('title');
  }
  if (!shown) closeMenu();
  if (_chipShown !== null && _chipShown !== shown) {
    try { document.dispatchEvent(new CustomEvent('overflow-state-change')); } catch (_) {}
  }
  _chipShown = shown;
}

/** Ask the server whether the selected model takes a level. */
export async function refresh() {
  const route = typeof _routeOf === 'function' ? (_routeOf() || {}) : {};
  const seq = ++_seq;
  let support = null;
  if (route.model) {
    const q = new URLSearchParams();
    q.set('model', route.model);
    if (route.endpoint_id) q.set('endpoint_id', route.endpoint_id);
    if (route.endpoint_url) q.set('endpoint_url', route.endpoint_url);
    try {
      const res = await fetch('/api/chat/reasoning-effort?' + q.toString(), { credentials: 'same-origin' });
      if (res && res.ok) support = await res.json();
    } catch (_) {
      support = null;
    }
  }
  if (seq !== _seq) return _support;
  _support = support;
  render();
  return _support;
}

export function choose(level) {
  _level = level === AUTO || LEVELS.includes(level) ? level : AUTO;
  _store(_level);
  render();
}

// ── the menu ───────────────────────────────────────────────────────────────

export function isMenuOpen() {
  const { menu } = _nodes();
  return !!(menu && !menu.classList.contains('hidden') && !menu.classList.contains('closing'));
}

export function closeMenu() {
  if (_dismiss) { const d = _dismiss; _dismiss = null; d(); return true; }
  return false;
}

function _shut(n) {
  _dismiss = null;
  const focused = typeof document !== 'undefined' ? document.activeElement : null;
  const held = !!(focused && n.menu && n.menu.contains(focused));
  if (n.chip) {
    n.chip.setAttribute('aria-expanded', 'false');
    if (held) n.chip.focus({ preventScroll: true });
  }
  _items(n).forEach((item) => item.classList.remove('kb-active'));
  if (!n.menu) return;
  n.menu.classList.add('closing');
  whenShut(n.menu, () => {
    if (!n.menu.classList.contains('closing')) return;
    n.menu.classList.remove('closing');
    n.menu.classList.add('hidden');
  }, 200);
}

export function openMenu() {
  const n = _nodes();
  if (!n.chip || !n.menu || n.chip.style.display === 'none') return false;
  if (isMenuOpen()) return true;
  render();
  n.menu.classList.remove('closing', 'hidden');
  n.chip.setAttribute('aria-expanded', 'true');
  const items = _items(n);
  items.forEach((item) => item.classList.remove('kb-active'));
  const start = items.find((item) => item.getAttribute('aria-checked') === 'true') || items[0];
  if (start) {
    start.classList.add('kb-active');
    try { start.focus({ preventScroll: true }); } catch (_) {}
  }
  const inside = n.wrap || n.menu;
  _dismiss = bindMenuDismiss(n.menu, () => _shut(n), (ev) => !inside.contains(ev.target));
  return true;
}

export function toggleMenu() {
  return isMenuOpen() ? (closeMenu(), false) : openMenu();
}

function _onMenuKey(e) {
  const n = _nodes();
  if (!n.options) return;
  if (e.key === 'Tab') {
    closeMenu();
    if (e.shiftKey) e.preventDefault();
    return;
  }
  handlePickerKeydown(e, n.options, ITEM, closeMenu, { roving: true });
}

/**
 * Wire the chip once. `routeOf` returns the selected model and endpoint (the
 * chat module's `selectedRoute`), so this module never keeps its own copy of
 * which model is chosen (`Law 7`).
 */
export function init(routeOf) {
  _routeOf = routeOf;
  const n = _nodes();
  if (n.chip && !n.chip._pantheonEffort) {
    n.chip._pantheonEffort = true;
    n.chip.addEventListener('click', () => { toggleMenu(); });
  }
  if (n.options && !n.options._pantheonEffort) {
    n.options._pantheonEffort = true;
    n.options.addEventListener('keydown', _onMenuKey);
    for (const item of _items(n)) {
      item.addEventListener('click', () => {
        const level = item.getAttribute('data-effort');
        closeMenu();
        choose(level);
      });
    }
  }
  const again = () => { refresh(); };
  document.addEventListener('pantheon:model-picked', again);
  document.addEventListener('pantheon:session-changed', again);
  render();
  refresh();
}

const reasoningEffortModule = {
  init, refresh, render, choose, currentLevel, levelForSend, isShown,
  openMenu, closeMenu, toggleMenu, isMenuOpen,
};
export default reasoningEffortModule;

if (typeof window !== 'undefined') {
  window.reasoningEffortModule = reasoningEffortModule;
}
