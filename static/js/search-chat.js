// SPDX-License-Identifier: AGPL-3.0-or-later
// Search Chat Module — the Ctrl+K search overlay, which is also the command
// palette (`P9-01`): chats, tools, Settings panels and slash commands in one box.
//
// `P9-01`. **Extended, not rebuilt.** The markup has said "Ctrl+K command
// palette" since before the fork and this module has always owned
// `#search-overlay`, `#search-input` and `#search-results` (FORBIDDEN.md Part
// 1), so the palette is this overlay learning to find more than chat messages
// — not a second overlay beside it (`Law 14`). Its callers are unchanged:
// the rail and sidebar Search buttons and `init` in `app.js`, the Escape chain
// in `app.js`, and the `search` keybind (Ctrl+K) in `keyboard-shortcuts.js`.
// `/find` is not one of them and never was: it calls `/api/search` itself and
// replies in the chat (`slashCommands.js:_cmdSearch`).
//
// **Every source is a registry that already existed, read, never copied:**
//   * Tools — `_AUTO_WIRE` and `_LABELS` in `modalManager.js`, through
//     `listWindows()`; opened by `showWindow()`, which presses the door a
//     person would press (`openClosedWindow`, `P9-11`) or restores/raises a
//     window that is already up. Settings and Skills have no button to
//     press, and open through `settingsModule.open` and `openSkillsWindow`.
//   * Settings — `SETTINGS_PANELS` and its own `searchSettingsPanels`, with the
//     same harvested control text and the same admin filter the Settings
//     finder uses; opened by `settingsModule.open(panel)`, the door
//     `/settings <tab>` and `adminModule.open` go through.
//   * Commands — the slash catalogue the composer's autocomplete shows
//     (`slashCatalog()`); chosen commands are **put in the message box**, never
//     run from here (see `_fillComposer`).
//   * Chats — `/api/search`, exactly as before (see `_searchChats`).
//
// **The palette changes nothing itself.** It opens windows through their own
// doors, opens Settings through `settingsModule.open`, and hands commands to
// the composer, whose submit path is the only thing that runs one. So there is
// no approval, `require_admin` check or setting it could route around: it has
// no path of its own to any of them.
//
// **The route table the row names is `app.js:_routeOpen`** — eight URL paths
// that open a tool on page load (`/calendar`, `/email`, …). It is read here as
// a premise and deliberately NOT as a source: it is a closure inside
// `initializeEventListeners`, its seven windows are ones `_AUTO_WIRE` already
// names, and its openers are page-load deep links — `/email` presses
// `#rail-new-session` first, so pointing the palette at it would make "Email"
// start a new chat.

import sessionModule from './sessions.js';
import settingsModule from './settings.js?v=20260930wavethree2';
import { listWindows, showWindow } from './modalManager.js?v=20260930wavethree2';
import { openSkillsWindow } from './skills.js';
import { slashCatalog, insertSlashToken } from './slashAutocomplete.js';
import { SETTINGS_GROUPS, searchSettingsPanels } from './settings/registry.js';
import { controlTextFor } from './settings/search.js';
import { topPortalZ } from './toolWindowZOrder.js';

let API_BASE = '';
let debounceTimer = null;

// The chat lane's answer, and which query it answers. `_chatSeq` moves on every
// keystroke and on close, so a response for a query that is no longer typed is
// dropped instead of drawn over the newer one — the old handler drew whichever
// answer arrived last.
let _chatSeq = 0;
let _chat = { query: '', state: 'idle', results: [], error: '' };

let _options = [];      // [{ el, entry }] in listbox order
let _active = -1;       // index into _options, mirrored by aria-activedescendant
let _returnFocus = null; // what had focus before the overlay opened
let _catalog = null;    // the slash catalogue; static, so read once
let _seq = 0;           // ids for options and group headings

// Per-group caps, so commands never crowd the chat hits off the screen. The
// chat lane keeps its own `limit=20`.
const CAPS = { tools: 5, settings: 5, commands: 6 };

function el(id) { return document.getElementById(id); }

function _inside(node, root) {
  for (let n = node; n; n = n.parentNode) if (n === root) return true;
  return false;
}

function hideMobileSidebarForSearch() {
  if (window.innerWidth >= 768) return;
  const sidebar = el('sidebar');
  const rail = el('icon-rail');
  const backdrop = el('sidebar-backdrop');
  let changed = false;
  if (sidebar && !sidebar.classList.contains('hidden')) {
    sidebar.classList.add('hidden');
    changed = true;
  }
  if (rail && rail.classList.contains('mobile-mini')) {
    rail.classList.remove('mobile-mini');
    rail.style.cssText = '';
    changed = true;
  }
  if (backdrop) backdrop.classList.remove('visible');
  if (changed && typeof window.syncRailSide === 'function') {
    try { window.syncRailSide(); } catch (_) {}
  }
}

export function openSearch() {
  hideMobileSidebarForSearch();
  const overlay = el('search-overlay');
  if (!overlay) return;
  // Remember where the person was, so Escape can take them back there. Measured
  // before `P9-01`: Escape left focus on <body> — the composer the person had
  // been typing in lost its caret every time they looked something up.
  const was = document.activeElement;
  if (was && !_inside(was, overlay)) _returnFocus = was;
  // `P9-01`, measured: the stylesheet pins this overlay at z-index 300, and
  // both counters that raise tool windows start above that — `ui.js` promotes
  // every visible `.modal` from 1000 (`_zCounter`), `modalManager` from 300
  // (`_modalTopZ`). So any open window was drawn over the search: with Calendar
  // open (z 1001), Ctrl+K put the caret in a box hidden behind the calendar —
  // `elementFromPoint` at the input's centre answered `#cal-quickadd`. Read the
  // live stack instead, the answer `P3-18` gave every portaled popover.
  overlay.style.zIndex = String(topPortalZ());
  overlay.classList.remove('hidden');
  const input = el('search-input');
  if (input) {
    input.value = '';
    input.focus();
  }
  _reset();
  _draw();
}

/** Dismiss — Escape, Ctrl+K again, or a click on the backdrop. Hands focus back. */
export function closeSearch() {
  const wasOpen = isOpen();
  _hide();
  if (wasOpen) _returnFocusHome();
}

export function isOpen() {
  const overlay = el('search-overlay');
  return !!overlay && !overlay.classList.contains('hidden');
}

function _reset() {
  if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
  _chatSeq += 1;
  _chat = { query: '', state: 'idle', results: [], error: '' };
  _options = [];
  _active = -1;
}

function _hide() {
  const overlay = el('search-overlay');
  if (!overlay) return;
  overlay.classList.add('hidden');
  _reset();
  const container = el('search-results');
  if (container) container.replaceChildren();
  // Clears `aria-activedescendant` too: left pointing at a row this just
  // removed, the box would name an option that no longer exists.
  _setActive(-1);
  _syncInput();
  _say('');
}

function _returnFocusHome() {
  const target = _returnFocus;
  _returnFocus = null;
  if (!target || target === document.body || typeof target.focus !== 'function') return;
  if (target.isConnected === false) return;
  try { target.focus(); } catch (_) { /* gone, or not focusable any more */ }
}

// ── the commands ────────────────────────────────────────────────────────────

function _norm(s) {
  return String(s == null ? '' : s).trim().toLowerCase().replace(/\s+/g, ' ');
}

/** Lower-case words, split on anything that is not a letter or a digit. */
function _words(s) {
  return _norm(s).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

/**
 * Every typed word starts some word of the entry. Tools and commands match
 * this way; measured with plain substrings first, "cal" offered `/setup` and
 * `/usage` because their help text says "local". Settings keeps its own
 * registry's matcher, so the palette and the Settings finder always agree
 * about which panels a word finds.
 */
function _wordsMatch(terms, text) {
  const words = _words(text);
  return terms.every((t) => words.some((w) => w.startsWith(t)));
}

/** Exact beats prefix beats a word that starts with the first term; ties keep registry order. */
function _rank(entries, q) {
  const typed = q.replace(/^\//, '');
  const first = _words(q)[0] || '';
  const score = (entry) => {
    const label = _norm(entry.label);
    const bare = label.replace(/^\//, '');
    if (label === q || bare === typed) return 3;
    if (label.startsWith(q) || bare.startsWith(typed)) return 2;
    return first && _words(label).some((w) => w.startsWith(first)) ? 1 : 0;
  };
  return entries
    .map((entry, i) => ({ entry, i, s: score(entry) }))
    .sort((a, b) => (b.s - a.s) || (a.i - b.i))
    .map((x) => x.entry);
}

/**
 * The two windows `_AUTO_WIRE` names with no button to press, and the one
 * function every other way in already calls. The palette calls the same one.
 *
 *   * Settings — its entry names `tool-settings-btn`, which no template
 *     renders; the rail gear and the cog both call `settingsModule.open()`.
 *   * Skills (`P9-06`) — `{ rail: null, sidebar: null }` by design; the Brain's
 *     launcher card, `[data-open-skills]` and a chat's skills pill all go
 *     through `openSkillsWindow`, which restores a minimized window and raises
 *     an open one itself. Never the Brain's button: that opens the Brain.
 */
const _DOOR_FUNCTIONS = {
  'settings-modal': () => settingsModule.open(),
  'skills-modal': () => openSkillsWindow('browse'),
};

function _toolEntries(terms) {
  const out = [];
  for (const w of listWindows()) {
    const door = _DOOR_FUNCTIONS[w.id];
    if (!w.door && !door) continue;
    // The id's first word as well as the label, so the names people learned
    // still find the tool: "cookbook" finds Forge, "memory" finds Brain.
    if (!_wordsMatch(terms, `${w.label} ${w.id.split('-')[0]}`)) continue;
    out.push({
      kind: 'tool', key: 'tool:' + w.id, label: w.label, detail: '',
      run: door || (() => showWindow(w.id)),
    });
  }
  return out;
}

function _settingsEntries(q) {
  const modal = el('settings-modal');
  let panels = [];
  try {
    panels = searchSettingsPanels(q, {
      isAdmin: !!window._isAdmin,
      controlText: modal ? controlTextFor(modal) : {},
    });
  } catch (_) { panels = []; }
  return panels.map((panel) => ({
    kind: 'settings', key: 'settings:' + panel.id, label: panel.label,
    detail: (SETTINGS_GROUPS.find((g) => g.id === panel.group) || {}).label || '',
    run: () => settingsModule.open(panel.id),
  }));
}

function _commandEntries(terms) {
  if (!_catalog) {
    try { _catalog = slashCatalog(); } catch (_) { _catalog = []; }
  }
  return _catalog
    .filter((c) => _wordsMatch(terms, [c.token, ...(c.aliases || []), c.help, c.category].join(' ')))
    .map((c) => ({
      kind: 'command', key: 'command:' + c.token, label: c.token, detail: c.help || '',
      token: c.token,
    }));
}

/**
 * The command half of the list for `query`, as `[{ label, entries }]` groups in
 * the order they are drawn: Tools, Settings, Commands. Chats follow them.
 *
 * Commands come first because they are known at once and the chats arrive
 * after the debounce: drawn the other way round, every chat answer would push
 * the highlighted row down under the person's finger.
 */
export function commandGroups(query) {
  const q = _norm(query);
  if (!q) return [];
  const terms = _words(q);
  const groups = [];
  // A bare "/" names no tool and no panel; it asks for the commands.
  if (terms.length) {
    const tools = _rank(_toolEntries(terms), q).slice(0, CAPS.tools);
    if (tools.length) groups.push({ label: 'Tools', entries: tools });
    const settings = _rank(_settingsEntries(q), q).slice(0, CAPS.settings);
    if (settings.length) groups.push({ label: 'Settings', entries: settings });
  }
  const commands = _rank(_commandEntries(terms), q).slice(0, CAPS.commands);
  if (commands.length) groups.push({ label: 'Commands', entries: commands });
  return groups;
}

// ── the chats ───────────────────────────────────────────────────────────────

function _chatGroups(results) {
  const groups = [];
  const bySession = new Map();
  results.forEach((r, i) => {
    const sid = String((r && r.session_id) || '');
    if (!bySession.has(sid)) {
      const group = { label: (r && r.session_name) || 'Untitled chat', entries: [] };
      bySession.set(sid, group);
      groups.push(group);
    }
    bySession.get(sid).entries.push({
      kind: 'chat',
      key: 'chat:' + ((r && r.message_id) || `${sid}:${i}`),
      label: (r && r.session_name) || '',
      sessionId: sid,
      role: r && r.role,
      snippet: (r && r.content_snippet) || '',
      timestamp: r && r.timestamp,
      run: () => (sessionModule && sessionModule.selectSession
        ? sessionModule.selectSession(sid) : undefined),
    });
  });
  return groups;
}

/**
 * The chat lane: what `/api/search` answers for `query`, exactly as this
 * overlay has always asked it (same URL, same `limit=20`, same 300 ms debounce).
 *
 * `P9-15c` — keyword and meaning in one box — is a change to what this asks,
 * not to how the answer is drawn: it returns the same rows, so it replaces the
 * fetch below and nothing else. A row it tags (`match: 'meaning'`, say) reaches
 * `_optionNode` intact.
 */
function _searchChats(query) {
  const seq = _chatSeq;
  debounceTimer = setTimeout(async () => {
    debounceTimer = null;
    let next;
    try {
      const res = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}&limit=20`);
      if (!res.ok) {
        next = { state: 'error', results: [], error: `${res.status}${res.statusText ? ' ' + res.statusText : ''}` };
      } else {
        const data = await res.json();
        next = { state: 'done', results: Array.isArray(data) ? data : ((data && data.results) || []), error: '' };
      }
    } catch (err) {
      next = { state: 'error', results: [], error: (err && err.message) || 'no answer' };
    }
    if (seq !== _chatSeq || !isOpen()) return;
    _chat = { query, ...next };
    _draw();
  }, 300);
}

// ── drawing ─────────────────────────────────────────────────────────────────
//
// Every string below reaches the page through `textContent` or a text node —
// chat titles, message snippets and the words the registries carry. The old
// renderer built this list as an `innerHTML` template and escaped each value;
// there is no template left to get wrong.

function formatTimestamp(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diff = now - d;
  if (diff < 86400000) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  if (diff < 604800000) {
    return d.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

/**
 * The snippet with every occurrence of the query marked — built from text
 * nodes. The old version ran its regex over the ESCAPED snippet, so a query of
 * "amp" or "lt" matched inside `&amp;` and `&lt;` and the row printed the
 * entity's letters.
 */
function _highlight(node, text, query) {
  const s = String(text == null ? '' : text);
  if (!query) { node.textContent = s; return; }
  const re = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  let at = 0;
  let m;
  while ((m = re.exec(s)) !== null) {
    if (!m[0]) { re.lastIndex += 1; continue; }
    if (m.index > at) node.appendChild(document.createTextNode(s.slice(at, m.index)));
    const mark = document.createElement('mark');
    mark.className = 'search-highlight';
    mark.textContent = m[0];
    node.appendChild(mark);
    at = m.index + m[0].length;
  }
  if (at < s.length) node.appendChild(document.createTextNode(s.slice(at)));
}

function _optionNode(entry, query) {
  const row = document.createElement('div');
  row.id = 'search-opt-' + (++_seq);
  row.setAttribute('role', 'option');
  row.setAttribute('aria-selected', 'false');
  row.dataset.paletteKind = entry.kind;
  if (entry.kind === 'chat') {
    row.className = 'search-result-item';
    row.dataset.session = entry.sessionId;
    const who = document.createElement('div');
    who.className = 'search-result-role';
    who.textContent = entry.role === 'user' ? 'You' : 'AI';
    const snippet = document.createElement('div');
    snippet.className = 'search-result-snippet';
    _highlight(snippet, entry.snippet, query);
    const when = document.createElement('div');
    when.className = 'search-result-time';
    when.textContent = formatTimestamp(entry.timestamp);
    row.appendChild(who);
    row.appendChild(snippet);
    row.appendChild(when);
  } else {
    row.className = 'search-result-item search-palette-row';
    const label = document.createElement('span');
    label.className = 'search-palette-label';
    label.textContent = entry.label;
    row.appendChild(label);
    if (entry.detail) {
      const detail = document.createElement('span');
      detail.className = 'search-palette-detail';
      detail.textContent = entry.detail;
      row.appendChild(detail);
    }
  }
  const index = _options.length;
  _options.push({ el: row, entry });
  // Keep the caret in the box while a row is pressed: the box owns the
  // keyboard, and a click that blurred it would strand focus on <body>.
  row.addEventListener('mousedown', (e) => { if (e && e.preventDefault) e.preventDefault(); });
  row.addEventListener('click', () => { _setActive(index); _activate(entry); });
  return row;
}

function _groupNode(label, entries, query) {
  const group = document.createElement('div');
  group.className = 'search-palette-group';
  group.setAttribute('role', 'group');
  const head = document.createElement('div');
  head.className = 'search-group-header';
  head.id = 'search-grp-' + (++_seq);
  // Named by the heading, which is hidden from the tree itself so a listbox
  // holds groups of options and nothing else.
  head.setAttribute('aria-hidden', 'true');
  head.textContent = label;
  group.setAttribute('aria-labelledby', head.id);
  group.appendChild(head);
  for (const entry of entries) group.appendChild(_optionNode(entry, query));
  return group;
}

function _draw() {
  const container = el('search-results');
  if (!container) return;
  const input = el('search-input');
  const query = input ? String(input.value || '').trim() : '';
  const keep = _active >= 0 && _options[_active] ? _options[_active].entry.key : null;
  _options = [];
  _active = -1;
  const frag = document.createDocumentFragment();
  if (query) {
    for (const group of commandGroups(query)) {
      frag.appendChild(_groupNode(group.label, group.entries, ''));
    }
    if (_chat.query === query && _chat.state === 'done') {
      for (const group of _chatGroups(_chat.results)) {
        frag.appendChild(_groupNode(group.label, group.entries, query));
      }
    }
  }
  container.replaceChildren(frag);
  // The highlighted row survives a redraw — the chats arriving must not move it.
  const kept = keep ? _options.findIndex((o) => o.entry.key === keep) : -1;
  _setActive(kept >= 0 ? kept : (_options.length ? 0 : -1));
  _syncInput();
  _say(_statusText(query));
}

function _setActive(i) {
  _active = i;
  _options.forEach((o, n) => {
    const on = n === i;
    o.el.classList.toggle('selected', on);
    o.el.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  const input = el('search-input');
  if (input) {
    if (i >= 0 && _options[i]) input.setAttribute('aria-activedescendant', _options[i].el.id);
    else input.removeAttribute('aria-activedescendant');
  }
  const row = i >= 0 && _options[i] ? _options[i].el : null;
  if (row && typeof row.scrollIntoView === 'function') row.scrollIntoView({ block: 'nearest' });
}

function _syncInput() {
  const input = el('search-input');
  if (input) input.setAttribute('aria-expanded', _options.length ? 'true' : 'false');
}

/** The status line under the list: seen, and read out (`role="status"`). */
function _say(text) {
  const status = el('search-status');
  if (status) status.textContent = text;
}

function _statusText(query) {
  if (!query) return '';
  const n = _options.length;
  const found = n ? `${n} ${n === 1 ? 'result' : 'results'}. ↑ ↓ to move, Enter to select, Esc to close.` : '';
  if (_chat.query === query && _chat.state === 'error') {
    return `Couldn't search your chats (${_chat.error}).${found ? ' ' + found : ''}`;
  }
  if (found) return found;
  // Nothing yet, and the chats have not answered: say nothing rather than
  // "nothing matches" a moment before they do.
  if (_chat.query !== query || _chat.state !== 'done') return '';
  return `Nothing matches “${query}”.`;
}

// ── choosing ────────────────────────────────────────────────────────────────

function _activate(entry) {
  if (!entry) return;
  if (entry.kind === 'command') { _fillComposer(entry); return; }
  _hide();
  try {
    Promise.resolve(entry.run()).catch((err) => console.error('Search: could not open', entry.label, err));
  } catch (err) {
    console.error('Search: could not open', entry.label, err);
  }
  // Hand focus back unless what just opened took it.
  const now = document.activeElement;
  if (!now || now === document.body || _inside(now, el('search-overlay'))) _returnFocusHome();
  else _returnFocus = null;
}

/**
 * A slash command goes into the message box, ready for its arguments — the
 * same thing picking it from the composer's own `/` popup does
 * (`insertSlashToken`). It is not run from here: the person presses Enter and
 * the composer's submit path runs it, with every check that path makes. A
 * palette calling `handleSlashCommand` directly would skip them.
 *
 * A draft is never overwritten. Something typed that is not already a command
 * is the person's writing, and replacing it to save them a keystroke would be
 * the palette destroying work.
 */
function _fillComposer(entry) {
  const box = el('message');
  if (!box) { _say('There is no message box to put the command in.'); return; }
  const draft = String(box.value || '').trim();
  if (draft && !/^[/!]/.test(draft)) {
    _say(`Your message box has a draft. Send or clear it, then choose ${entry.token} again.`);
    return;
  }
  _hide();
  _returnFocus = null;
  insertSlashToken(box, entry.token);
}

// ── keys ────────────────────────────────────────────────────────────────────

function handleKeydown(e) {
  if (!isOpen()) return;
  const n = _options.length;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (n) _setActive(_active < 0 ? 0 : Math.min(_active + 1, n - 1));
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (n) _setActive(Math.max(_active - 1, 0));
  } else if (e.key === 'Enter') {
    if (e.isComposing) return;
    e.preventDefault();
    if (_active >= 0 && _options[_active]) _activate(_options[_active].entry);
  } else if (e.key === 'Escape') {
    // Handled here and kept here. Bubbling on, it reached `cancel: 'escape'`
    // in `keyboard-shortcuts.js` — `abortCurrentRequest()` — so closing the
    // search also stopped a reply that was streaming behind it; and a calendar
    // open underneath took the same Escape as its own.
    e.preventDefault();
    e.stopPropagation();
    closeSearch();
  } else if (e.key === 'Tab') {
    // The box is the one stop in this dialog — the options are reached with
    // the arrows — so Tab stays here instead of walking into the page behind.
    e.preventDefault();
  }
}

function handleInput(e) {
  const query = String((e && e.target ? e.target.value : '') || '').trim();
  if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
  _chatSeq += 1;
  _chat = query
    ? { query, state: 'pending', results: [], error: '' }
    : { query: '', state: 'idle', results: [], error: '' };
  _draw();
  if (query) _searchChats(query);
}

export function init(apiBase) {
  API_BASE = apiBase || '';

  const input = el('search-input');
  if (input) {
    input.addEventListener('input', handleInput);
    input.addEventListener('keydown', handleKeydown);
  }

  // Close on overlay click (not popup click)
  const overlay = el('search-overlay');
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeSearch();
    });
  }
}

const searchChatModule = {
  init,
  openSearch,
  closeSearch,
  isOpen,
  commandGroups,
};

export default searchChatModule;
