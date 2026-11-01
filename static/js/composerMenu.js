// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/composerMenu.js
//
// `P25-01`. The composer's + menu, nested.
//
// The owner (2026-10-24) sent two references: one menu with a great many verbs,
// each with a grey hint beside it, and one whose short top level opens a second
// menu to the side (*Skills ›*, *Connectors ›*, *Plugins ›*, each ending with
// its *Manage* door) — *"I like the sheer amount of options - but i love how
// anthropic nests them."* So: the top level stays short (Add files,
// Documents, Workspace, then the rows with a ›), and every row says what it
// does. A row with `data-submenu` opens its menu **beside** it on a wide
// screen, and **over** the menu, as a page with a back row, on a phone.
//
// **One list per submenu** (`SUBMENUS`, `Law 7`): what it shows, whether it
// filters as you type, and the doors at its foot. Nothing here decides what a
// row does — each row calls the module that already owns the act: summoning
// is `summon.js`'s, a mode is its own chip's click, a skill is the slash
// command the composer already reads (`/name`), the hall and the skills
// library are their own windows. Text from the server is drawn as letters.
//
// **Keyboard.** In the menu, ↑/↓ move, → or Enter opens a submenu, and in a
// submenu ← or Escape goes back to its row; typing filters a list that
// filters. Escape on the top level is `app.js`'s, as before.
//
// `app.js` owns opening and closing the + menu itself; this module listens
// for its close (the `hidden`/`closing` classes) and asks for one with
// `composer-menu-close` after a pick.

import summon, { pickerRows } from './summon.js';
import workspaceModule from './workspace.js';
import { STARTS as DESIGN_STARTS } from './design/starts.js';

const PHONE_MAX = 640;
const HOVER_OPEN_MS = 140;
const LIST_MAX = 40;

/** The modes the Modes submenu shows: each is a chip the composer already
 *  has, flipped by its own click. A mode whose chip the visibility table hid
 *  (`ui_visibility.js`) is not offered. */
export const MODES = [
  { id: 'plan-toggle-btn', label: 'Plan mode', hint: 'Plan first, act on your yes' },
  { id: 'web-toggle-btn', label: 'Web search', hint: 'Search and read the web' },
  { id: 'bash-toggle-btn', label: 'Shell', hint: 'Run commands' },
  { id: 'overflow-rag-btn', label: 'RAG', hint: 'Answer from your indexed files' },
  // `B1730`: the agent says its replies out loud, in your voice of choice.
  { id: 'conversation-toggle-btn', label: 'Conversation', hint: 'Replies said out loud' },
];

function _modeOn(node) {
  return !!node && (node.classList.contains('active') || node.getAttribute('aria-pressed') === 'true');
}

function _offered(node) {
  return !!node && node.style.display !== 'none' && !node.hidden;
}

/** The modes offered right now, with their state. */
export function modeRows(doc = document) {
  return MODES.map((m) => ({ ...m, node: doc.getElementById(m.id) }))
    .filter((m) => _offered(m.node))
    .map((m) => ({ id: m.id, label: m.label, hint: m.hint, on: _modeOn(m.node) }));
}

async function _json(url) {
  try {
    const res = await fetch(url, { credentials: 'same-origin' });
    return res.ok ? await res.json() : null;
  } catch (_) {
    return null;
  }
}

function _insertSlash(name) {
  const box = document.getElementById('message');
  if (!box) return;
  const rest = box.value.replace(/^\/\S+\s*/, '');
  box.value = `/${name} ${rest}`;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  try { box.focus(); box.setSelectionRange(box.value.length, box.value.length); } catch (_) {}
}

/** `P25-04`. What *Git ›* asks the agent for, in the person's words — the
 *  same list `/git <action>` reads (`slashCommands.js`), so the menu and the
 *  command cannot drift (`Law 7`). The agent answers with the `git` tool, as
 *  the person, in the repository the chat is attached to. */
export const GIT_ACTIONS = [
  { id: 'status', label: 'Status', hint: 'What changed, on which branch',
    say: 'Show the git status of this repository: the branch, and what changed.' },
  { id: 'commit', label: 'Commit…', hint: 'Commit the changes, with a message',
    say: 'Commit the changes in this repository, with a message that says what changed and why.' },
  { id: 'pull', label: 'Pull', hint: 'Bring in what the remote has',
    say: 'Pull the latest changes into this repository.' },
  // `B1585` / `D-2026-10-29-01` §2. A push follows the chat's trust rung like
  // every other action, so the hint promises nothing about asking: on the
  // default rung a clean chat's push goes out unasked (`P25-00`, driven).
  { id: 'push', label: 'Push', hint: 'Send your commits to the remote',
    say: 'Push this branch to its remote.' },
  { id: 'branch', label: 'New branch…', hint: 'Start a branch from here',
    say: 'Create a new branch in this repository called ' },
  { id: 'clone', label: 'Clone a repository…', hint: 'Copy one from GitHub or another host',
    say: 'Clone the repository at https://' },
];

/** Put `text` in the message box for the person to finish or send. */
export function sayInComposer(text) {
  const box = document.getElementById('message');
  if (!box) return;
  box.value = text;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  try { box.focus(); box.setSelectionRange(box.value.length, box.value.length); } catch (_) {}
}

function _openGitSettings() {
  return import('./settings.js?v=20261009census').then((m) => {
    const mod = m.default || m;
    if (mod && typeof mod.open === 'function') return mod.open('git');
    return null;
  });
}

function _openDesign(opts = {}) {
  return import('./design/designWindow.js').then((m) => m.openDesign(opts));
}

async function _openHall({ workshop = false, seed = '' } = {}) {
  const m = await import('./agents/agentsWindow.js');
  await m.openAgents();
  if (workshop && m.openWorkshop) m.openWorkshop({ text: null, mode: 'talk', seed });
}

/** `P25-08`. The chat on screen as words — what *Build one from this chat*
 *  hands the agent builder as context: who said what, newest last. */
export function chatTranscript(doc = document, maxChars = 8000) {
  const rows = Array.from(doc.querySelectorAll('#chat-history .msg.msg-user, #chat-history .msg.msg-ai'));
  const lines = rows.map((m) => {
    const b = m.querySelector('.body');
    const text = ((b && (b.innerText || b.textContent)) || '').replace(/\s+\n/g, '\n').trim();
    if (!text) return '';
    return `${m.classList.contains('msg-user') ? 'Person' : 'Assistant'}: ${text}`;
  }).filter(Boolean);
  const all = lines.join('\n\n');
  return all.length > maxChars ? all.slice(all.length - maxChars) : all;
}

/** Every submenu, from one list. `load()` answers `{ rows, empty }`; a row is
 *  `{ label, hint?, badge?, on?, pick(), keep? }` — `keep` leaves the menu
 *  open (a switch), otherwise a pick closes it. `foot` rows are the doors to
 *  where that kind of thing is managed. */
export const SUBMENUS = {
  agents: {
    label: 'Agents',
    filter: 'Search agents…',
    async load() {
      const data = await _json('/api/agents');
      if (!data) return { rows: [], empty: 'The Agents hall could not be read. Try again in a moment.' };
      const mine = (data.hires || []).filter((h) => h.owner === data.me).map((h) => h.agent_id);
      const now = summon.getSummoned();
      const rows = [];
      if (now) {
        rows.push({ label: `Dismiss ${now.name}`, hint: 'Back to the chat on its own', pick: () => summon.dismiss() });
      }
      pickerRows(data.agents, mine, '').forEach((a) => rows.push({
        label: a.name, hint: a.tagline, on: !!(now && now.id === a.id),
        badge: a.source === 'own' ? 'Yours' : (mine.includes(a.id) ? 'Summoned' : ''),
        search: `${a.name} ${a.tagline} ${a.section_label || ''}`,
        pick: () => summon.summon(a),
      }));
      return { rows, empty: 'No agent matches that.' };
    },
    foot: [
      { label: 'New agent…', pick: () => _openHall({ workshop: true }) },
      { label: 'Build one from this chat…', pick: () => _openHall({ workshop: true, seed: chatTranscript() }) },
      { label: 'Open the hall', pick: () => _openHall() },
    ],
  },
  skills: {
    label: 'Skills',
    filter: 'Search skills…',
    async load() {
      const data = await _json('/api/skills/slash-catalog');
      if (!data) return { rows: [], empty: 'Your skills could not be read. Try again in a moment.' };
      const rows = (data.skills || []).map((s) => ({
        label: s.name, hint: s.help, search: `${s.name} ${s.help || ''} ${s.category || ''}`,
        pick: () => _insertSlash(s.name),
      }));
      return { rows, empty: rows.length ? 'No skill matches that.' : 'No skills yet — make one in the library.' };
    },
    foot: [
      { label: 'Manage skills', pick: () => import('./skills.js').then((m) => m.openSkillsWindow('browse')) },
    ],
  },
  git: {
    label: 'Git',
    filter: 'Search repositories…',
    async load() {
      const res = await (async () => {
        try {
          const r = await fetch('/api/git/repos', { credentials: 'same-origin' });
          let body = null;
          try { body = await r.json(); } catch (_) { body = null; }
          return { ok: r.ok, body };
        } catch (_) { return { ok: false, body: null }; }
      })();
      const now = workspaceModule.getWorkspace();
      const rows = [];
      const attached = (res.ok && res.body ? res.body.repos || [] : []).find((x) => x.abs === now);
      if (attached) {
        GIT_ACTIONS.forEach((a) => rows.push({ label: a.label, hint: a.hint, search: `${a.label} ${a.hint}`,
          pick: () => sayInComposer(a.say) }));
      }
      (res.ok && res.body ? res.body.repos || [] : []).forEach((r) => rows.push({
        label: r.name,
        hint: `${r.branch || 'no branch'} · ${r.changes ? `${r.changes} change${r.changes === 1 ? '' : 's'}` : 'clean'} · ${r.path}`,
        on: r.abs === now, search: `${r.name} ${r.path} ${r.branch || ''}`,
        pick: () => workspaceModule.vetAndSetWorkspace(r.abs),
      }));
      if (!attached) {
        const clone = GIT_ACTIONS.find((a) => a.id === 'clone');
        rows.push({ label: clone.label, hint: clone.hint, pick: () => sayInComposer(clone.say) });
      }
      const empty = !res.ok
        ? ((res.body && res.body.detail) || 'Your repositories could not be read. Try again in a moment.')
        : 'No repository matches that.';
      return { rows, empty };
    },
    foot: [
      { label: 'Git settings', pick: () => _openGitSettings() },
    ],
  },
  // `P26-04`. The Design window's starting points — its cards' own list.
  design: {
    label: 'Design',
    filter: null,
    async load() {
      const rows = DESIGN_STARTS.map((s) => ({
        label: s.label, hint: s.hint, search: `${s.label} ${s.hint}`,
        pick: () => _openDesign({ start: s.id }),
      }));
      return { rows, empty: '' };
    },
    foot: [
      { label: 'Design systems…', pick: () => _openDesign({ system: 'new' }) },
      { label: 'Open Design', pick: () => _openDesign() },
    ],
  },
  modes: {
    label: 'Modes',
    filter: null,
    async load() {
      const rows = modeRows().map((m) => ({
        label: m.label, hint: m.hint, on: m.on, keep: true, toggle: true,
        pick: () => { const n = document.getElementById(m.id); if (n) n.click(); },
      }));
      return { rows, empty: 'No modes are switched on for you.' };
    },
    foot: [],
  },
};

/** Rows of `rows` matching `query` — every word, anywhere in the row. */
export function filterRows(rows, query) {
  const words = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return rows;
  return rows.filter((r) => {
    const hay = String(r.search || `${r.label} ${r.hint || ''}`).toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

// ── the panel ───────────────────────────────────────────────────────────────

let _panel = null;   // { node, key, row, list, search, rows, empty }
let _hoverTimer = null;

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _isPhone() {
  return (window.innerWidth || 1024) <= PHONE_MAX;
}

function _menu() { return document.getElementById('overflow-menu'); }

function _visibleItems(container) {
  const sel = container.classList.contains('composer-submenu') ? '.composer-submenu-row' : '.overflow-menu-item';
  return Array.from(container.querySelectorAll(sel))
    .filter((n) => n.style.display !== 'none' && !n.hidden && !n.classList.contains('composer-menu-folded')
      && n.offsetParent !== null);
}

export function closeSubmenu({ focusRow = false } = {}) {
  if (_hoverTimer) { clearTimeout(_hoverTimer); _hoverTimer = null; }
  if (!_panel) return;
  const { node, row } = _panel;
  _panel = null;
  if (node.parentNode) node.parentNode.removeChild(node);
  if (row) {
    row.setAttribute('aria-expanded', 'false');
    row.classList.remove('submenu-open');
    if (focusRow) try { row.focus(); } catch (_) {}
  }
  const menu = _menu();
  if (menu) menu.classList.remove('composer-menu-under');
}

function _closeAll() {
  closeSubmenu();
  document.dispatchEvent(new CustomEvent('composer-menu-close'));
}

function _place(node, row) {
  const menu = _menu();
  if (!menu) return;
  const m = menu.getBoundingClientRect();
  const vw = window.innerWidth || 1024;
  const vh = window.innerHeight || 768;
  if (_isPhone()) {
    node.classList.add('composer-submenu-page');
    // `P25-00`: as wide as the menu, but never past the screen's right edge —
    // it started at the menu's left (23 px at 390) and took the screen's
    // width less both margins, so it ran 7 px off the right.
    const left = Math.max(8, Math.min(m.left, vw - 8 - 260));
    node.style.left = `${left}px`;
    node.style.width = `${Math.min(vw - 8 - left, Math.max(m.width, 260))}px`;
    node.style.top = 'auto';
    node.style.bottom = `${Math.max(8, vh - m.bottom)}px`;
    node.style.maxHeight = `${Math.max(240, m.bottom - 16)}px`;
    menu.classList.add('composer-menu-under');
    return;
  }
  const r = row.getBoundingClientRect();
  const w = node.offsetWidth || 300;
  const h = node.offsetHeight || 200;
  const right = m.right + 6;
  const left = right + w <= vw - 8 ? right : Math.max(8, m.left - 6 - w);
  // Bottom-aligned to its row when it would run off the bottom, as the
  // reference does: a menu that opens upward from the composer.
  let top = r.top - 5;
  if (top + h > vh - 8) top = Math.max(8, r.bottom + 5 - h);
  node.style.left = `${left}px`;
  node.style.top = `${top}px`;
  node.style.maxHeight = `${vh - 16}px`;
}

function _drawList() {
  if (!_panel) return;
  const { list, rows, empty, search } = _panel;
  list.textContent = '';
  const hits = filterRows(rows || [], search ? search.value : '').slice(0, LIST_MAX);
  if (!hits.length) {
    list.appendChild(_el('p', 'composer-submenu-empty', rows === null ? 'Reading…' : empty));
    return;
  }
  hits.forEach((r) => list.appendChild(_rowButton(r)));
}

function _rowButton(r) {
  const b = _el('button', 'composer-submenu-row');
  b.type = 'button';
  b.setAttribute('role', r.toggle ? 'menuitemcheckbox' : 'menuitem');
  if (r.toggle) b.setAttribute('aria-checked', String(!!r.on));
  if (r.on) b.classList.add('active');
  const words = _el('span', 'composer-submenu-words');
  words.appendChild(_el('span', 'composer-submenu-label', r.label));
  if (r.hint) words.appendChild(_el('span', 'composer-submenu-hint', r.hint));
  b.appendChild(words);
  if (r.badge) b.appendChild(_el('span', 'composer-submenu-badge', r.badge));
  if (r.toggle) b.appendChild(_el('span', `composer-submenu-switch${r.on ? ' on' : ''}`));
  else if (r.on) b.appendChild(_el('span', 'composer-submenu-check', '✓'));
  b.addEventListener('pointerdown', (e) => e.preventDefault());
  b.addEventListener('click', (e) => {
    e.stopPropagation();
    r.pick();
    if (r.keep) {
      const key = _panel && _panel.key;
      if (key) _refresh(key);
    } else {
      _closeAll();
    }
  });
  return b;
}

async function _refresh(key) {
  if (!_panel || _panel.key !== key) return;
  const got = await SUBMENUS[key].load();
  if (!_panel || _panel.key !== key) return;
  _panel.rows = got.rows;
  _panel.empty = got.empty;
  _drawList();
}

/** The menu's own spring-in moves it with a transform, and a transformed
 *  parent would place a fixed child against itself, not the screen — so a
 *  submenu waits for that to end. */
async function _settled(menu) {
  if (!menu || typeof menu.getAnimations !== 'function') return;
  try { await Promise.all(menu.getAnimations().map((a) => a.finished)); } catch (_) {}
}

/** Open the submenu `key` beside `row` (on a phone: over the menu). */
export async function openSubmenu(key, row, { focus = false } = {}) {
  const def = SUBMENUS[key];
  if (!def) return;
  await _settled(_menu());
  if (_panel && _panel.key === key) { if (focus) _focusFirst(); return; }
  closeSubmenu();
  const node = _el('div', 'composer-submenu');
  node.setAttribute('role', 'menu');
  node.setAttribute('aria-label', def.label);
  node.dataset.submenu = key;
  if (_isPhone()) {
    const back = _el('button', 'composer-submenu-back');
    back.type = 'button';
    back.textContent = `‹ ${def.label}`;
    back.setAttribute('aria-label', `Back from ${def.label}`);
    back.addEventListener('pointerdown', (e) => e.preventDefault());
    back.addEventListener('click', (e) => { e.stopPropagation(); closeSubmenu({ focusRow: true }); });
    node.appendChild(back);
  }
  let search = null;
  if (def.filter) {
    search = document.createElement('input');
    search.type = 'search';
    search.className = 'composer-submenu-search';
    search.placeholder = def.filter;
    search.setAttribute('aria-label', def.filter.replace('…', ''));
    search.addEventListener('input', _drawList);
    node.appendChild(search);
  }
  const list = _el('div', 'composer-submenu-list');
  node.appendChild(list);
  if (def.foot.length) {
    node.appendChild(_el('div', 'composer-submenu-sep'));
    def.foot.forEach((f) => {
      const b = _el('button', 'composer-submenu-row composer-submenu-foot');
      b.type = 'button';
      b.setAttribute('role', 'menuitem');
      b.appendChild(_el('span', 'composer-submenu-label', f.label));
      b.addEventListener('pointerdown', (e) => e.preventDefault());
      b.addEventListener('click', (e) => { e.stopPropagation(); _closeAll(); f.pick(); });
      node.appendChild(b);
    });
  }
  node.addEventListener('keydown', _panelKeys);
  // Inside the menu, so it shares the menu's stacking tier (`check-zindex.py`:
  // no number of its own) and a click in it is a click in the menu.
  (_menu() || document.body).appendChild(node);
  _panel = { node, key, row, list, search, rows: null, empty: '' };
  row.setAttribute('aria-expanded', 'true');
  row.classList.add('submenu-open');
  _drawList();
  _place(node, row);
  if (focus && search) try { search.focus(); } catch (_) {}
  const got = await def.load();
  if (!_panel || _panel.node !== node) return;
  _panel.rows = got.rows;
  _panel.empty = got.empty;
  _drawList();
  _place(node, row);
  if (focus && !search) _focusFirst();
}

function _focusFirst() {
  if (!_panel) return;
  const first = _visibleItems(_panel.node)[0];
  if (first) try { first.focus(); } catch (_) {}
}

function _move(container, delta) {
  const items = _visibleItems(container);
  if (!items.length) return;
  const at = items.indexOf(document.activeElement);
  const next = items[(at + delta + items.length) % items.length];
  try { next.focus(); } catch (_) {}
}

function _panelKeys(e) {
  if (!_panel) return;
  if (e.key === 'ArrowDown') { e.preventDefault(); e.stopPropagation(); _move(_panel.node, 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); _move(_panel.node, -1); }
  else if (e.key === 'Escape' || (e.key === 'ArrowLeft' && !(e.target && e.target.type === 'search'))) {
    e.preventDefault();
    e.stopPropagation();
    closeSubmenu({ focusRow: true });
  }
}

function _menuKeys(e) {
  const menu = _menu();
  if (!menu || !menu.contains(e.target)) return;
  if (e.target.closest && e.target.closest('.composer-submenu')) return;
  if (e.key === 'ArrowDown') { e.preventDefault(); _move(menu, 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); _move(menu, -1); }
  else if ((e.key === 'ArrowRight' || e.key === 'Enter' || e.key === ' ') && e.target.dataset
    && e.target.dataset.submenu) {
    e.preventDefault();
    openSubmenu(e.target.dataset.submenu, e.target, { focus: true });
  }
}

/** The Modes row's dot: on when a mode is on that the bar is not showing —
 *  folded into the menu (RAG) or collapsed for room — so a mode that is on
 *  is always visible somewhere. */
export function syncModesDot(doc = document) {
  const row = doc.getElementById('overflow-modes-btn');
  if (!row) return false;
  const hidden = MODES.some((m) => {
    const n = doc.getElementById(m.id);
    return _offered(n) && _modeOn(n)
      && (n.classList.contains('composer-menu-folded') || n.classList.contains('toolbar-collapsed'));
  });
  const was = row.classList.contains('active');
  row.classList.toggle('active', hidden);
  return was !== hidden;
}

export function initComposerMenu() {
  const menu = _menu();
  if (!menu || menu.dataset.nested) return;
  menu.dataset.nested = '1';
  menu.querySelectorAll('[data-submenu]').forEach((row) => {
    const key = row.dataset.submenu;
    row.addEventListener('click', (e) => {
      e.stopPropagation();
      if (_panel && _panel.key === key && _isPhone()) return;
      openSubmenu(key, row, { focus: e.detail === 0 });
    });
    row.addEventListener('pointerenter', (e) => {
      if (e.pointerType !== 'mouse' || _isPhone()) return;
      if (_hoverTimer) clearTimeout(_hoverTimer);
      _hoverTimer = setTimeout(() => openSubmenu(key, row), HOVER_OPEN_MS);
    });
    row.addEventListener('pointerleave', () => { if (_hoverTimer) { clearTimeout(_hoverTimer); _hoverTimer = null; } });
  });
  // A plain row under the pointer closes an open submenu, as a menu bar does.
  menu.querySelectorAll('.overflow-menu-item:not([data-submenu])').forEach((row) => {
    row.addEventListener('pointerenter', (e) => {
      if (e.pointerType === 'mouse' && !_isPhone()) closeSubmenu();
    });
  });
  menu.addEventListener('keydown', _menuKeys);
  // The + menu closed (any way `app.js` closes it): the submenu goes with it.
  new MutationObserver(() => {
    if (menu.classList.contains('hidden') || menu.classList.contains('closing')) closeSubmenu();
  }).observe(menu, { attributes: true, attributeFilter: ['class'] });
  const modeObserver = new MutationObserver(() => {
    if (syncModesDot()) document.dispatchEvent(new CustomEvent('overflow-state-change'));
  });
  MODES.forEach((m) => {
    const n = document.getElementById(m.id);
    if (n) modeObserver.observe(n, { attributes: true, attributeFilter: ['class', 'style', 'aria-pressed'] });
  });
  syncModesDot();
  window.addEventListener('resize', () => { if (_panel) _place(_panel.node, _panel.row); });
}

/** Git runs where the agent's tools run, so *Git ›* is an Agent-mode row,
 *  as Workspace is (`workspace.js`). */
export function applyMode(mode) {
  const row = document.getElementById('overflow-git-btn');
  if (row) row.style.display = mode === 'chat' ? 'none' : '';
}

/** `/git`: the + menu, opened on *Git ›*. */
export async function openGitMenu() {
  const plus = document.getElementById('overflow-plus-btn');
  const row = document.getElementById('overflow-git-btn');
  if (!plus || !row) return false;
  const menu = _menu();
  if (!menu || menu.classList.contains('hidden')) plus.click();
  await openSubmenu('git', row, { focus: true });
  return true;
}

export const _test = { panel: () => _panel };

export default { initComposerMenu, openSubmenu, closeSubmenu, filterRows, modeRows, syncModesDot, applyMode,
  openGitMenu, sayInComposer, SUBMENUS, MODES, GIT_ACTIONS };
