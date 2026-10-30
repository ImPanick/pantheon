// SPDX-License-Identifier: AGPL-3.0-or-later
//
// cockpit.js — the cockpit shell (the accepted V4 "material pass" study,
// 2026-10-29). `static/cockpit.css` carries the look; this module carries the
// few changes a stylesheet cannot make, and nothing else:
//
//   * the light field behind every slab (`#ck-field`);
//   * the rail in its three bands, with a sidebar door at the top;
//   * the drawer's brand mark and the keys beside its two actions;
//   * Nobody, moved into the top bar beside the chat's name;
//   * the ready state: a preflight of six cells read from the live system;
//   * one strip holding the plan, the queue and the mail awaiting approval;
//   * the loadout row under the message box, where attachments and the
//     indicator chips now live;
//   * the context ring, drawn at the instrument's size.
//
// **It moves elements; it never rebuilds them.** Every control keeps its id,
// its classes and every listener its own module bound (`Law 2`, `Law 14`): a
// node moved with `appendChild` takes its listeners with it. Nothing here owns
// state another module owns — the cells read what the page and the server
// already say, and a press on a cell is a press on the control that already
// does the job.

import { KEYBIND_DEFAULTS, formatKeybind } from './keyboard-shortcuts.js';

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || '') || /Mac OS X/.test(navigator.userAgent || '');
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const byId = (id) => document.getElementById(id);

// The study's icon set, drawn at 1.6 stroke. Constant markup, never server text.
export const ICONS = {
  sidebar: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M9.5 5v14"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  chat: '<path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17H10l-5 4V6.5A1.5 1.5 0 0 1 5 5z"/>',
  doc: '<path d="M7 3.5h7l4.5 4.5v12.5H7z"/><path d="M14 3.5V8h4.5M10 13h5.5M10 16.5h5.5"/>',
  agents: '<path d="M12 3.5l7.5 4.2v8.6L12 20.5l-7.5-4.2V7.7z"/><path d="M12 12l7.5-4.3M12 12v8.5M12 12L4.5 7.7"/>',
  tasks: '<path d="M4.5 6.5l1.8 1.8 3-3M12 7h7.5M4.5 13.5l1.8 1.8 3-3M12 14h7.5M12 19.5h7.5"/>',
  mail: '<rect x="3.5" y="5.5" width="17" height="13" rx="1.5"/><path d="M4 7l8 6 8-6"/>',
  cal: '<rect x="4" y="5.5" width="16" height="14.5" rx="1.5"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  notes: '<path d="M6 4h12v16H6z"/><path d="M9.5 9h5M9.5 12.5h5M9.5 16h3"/>',
  spark: '<path d="M12 4v4M12 16v4M4 12h4M16 12h4M7 7l2 2M15 15l2 2M7 17l2-2M15 9l2-2"/>',
  flame: '<path d="M12 3.5c2.5 3.5 6 5.6 6 10a6 6 0 0 1-12 0c0-2.3 1.2-4.2 3-5.2 0 2 .8 3.2 2 3.7-.4-3 .1-5.6 1-8.5z"/>',
  research: '<circle cx="10.5" cy="10.5" r="6"/><path d="M20 20l-5-5M8 10.5h5M10.5 8v5"/>',
  compare: '<rect x="3.5" y="5" width="7.5" height="14" rx="1"/><rect x="13" y="5" width="7.5" height="14" rx="1"/>',
  flow: '<rect x="3.5" y="4" width="6" height="5" rx="1"/><rect x="14.5" y="15" width="6" height="5" rx="1"/><path d="M9.5 6.5h3a2 2 0 0 1 2 2v4a2 2 0 0 0 2 2.5"/>',
  brain: '<circle cx="12" cy="6" r="2.3"/><circle cx="6" cy="17" r="2.3"/><circle cx="18" cy="17" r="2.3"/><path d="M12 8.3v3.7M12 12l-4.4 3.3M12 12l4.4 3.3M8.3 17h7.4"/>',
  library: '<path d="M5 4h3v16H5zM10 4h3v16h-3zM15 5.2l2.8-.8 3.4 14.8-2.8.8z"/>',
  image: '<rect x="4" y="5" width="16" height="14" rx="1.5"/><path d="M4 16l5-5 4 4 2.5-2.5L20 17"/><circle cx="15.5" cy="9" r="1.2"/>',
  theme: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16z" fill="currentColor"/>',
  sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  sort: '<path d="M8 5v14M5 16l3 3 3-3M16 19V5M13 8l3-3 3 3"/>',
  mask: '<path d="M3 9.5c3-2.5 15-2.5 18 0-.6 5-3.6 7.2-6 5.4-1.2-.9-1.9-1.4-3-1.4s-1.8.5-3 1.4c-2.4 1.8-5.4-.4-6-5.4z"/><circle cx="8.5" cy="11" r=".9" fill="currentColor"/><circle cx="15.5" cy="11" r=".9" fill="currentColor"/>',
  chev: '<path d="M9.5 6l6 6-6 6"/>', chevd: '<path d="M6 9.5l6 6 6-6"/>', back: '<path d="M14.5 6l-6 6 6 6"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c3 3 3 14 0 17M12 3.5c-3 3-3 14 0 17"/>',
  term: '<rect x="3.5" y="5" width="17" height="14" rx="1.5"/><path d="M7.5 10l2.5 2-2.5 2M12.5 15h4"/>',
  plan: '<path d="M5 6.5h14M5 12h10M5 17.5h6"/>',
  queue: '<path d="M5 7h14M5 12h14M5 17h8"/><path d="M17 15.5l2 1.5-2 1.5"/>',
  hand: '<path d="M8 12.5V6.8a1.4 1.4 0 0 1 2.8 0V11M10.8 10.5V5.3a1.4 1.4 0 0 1 2.8 0v5.2M13.6 10.5V6.8a1.4 1.4 0 0 1 2.8 0v6.7a6 6 0 0 1-6 6h-.6a5 5 0 0 1-4-2l-2.6-3.6a1.4 1.4 0 0 1 2.2-1.7L8 13.5"/>',
  folder: '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  monitor: '<rect x="3.5" y="4.5" width="17" height="11.5" rx="1.5"/><path d="M8.5 20h7M12 16v4"/>',
  browser: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M3.5 9h17"/><circle cx="6.3" cy="6.8" r=".6" fill="currentColor"/><circle cx="8.5" cy="6.8" r=".6" fill="currentColor"/>',
  l1: '<rect x="4.5" y="5.5" width="15" height="13" rx="1.5"/>',
  lcols: '<rect x="4.5" y="5.5" width="15" height="13" rx="1.5"/><path d="M12 5.5v13"/>',
  lrows: '<rect x="4.5" y="5.5" width="15" height="13" rx="1.5"/><path d="M4.5 12h15"/>',
  lmain: '<rect x="4.5" y="5.5" width="15" height="13" rx="1.5"/><path d="M4.5 12.5h15M12 12.5v6"/>',
  popout: '<path d="M14 4.5h5.5V10M19.5 4.5L12 12M17.5 14v5.5h-13v-13H10"/>',
  dockin: '<rect x="4.5" y="5.5" width="15" height="13" rx="1.5"/><path d="M13 5.5v13"/><path d="M13 12h6"/>',
  max: '<path d="M4.5 9V4.5H9M19.5 9V4.5H15M4.5 15v4.5H9M19.5 15v4.5H15"/>',
  x: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  db: '<ellipse cx="12" cy="6" rx="7" ry="2.6"/><path d="M5 6v12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6V6M5 12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6"/>',
  lock: '<rect x="5.5" y="11" width="13" height="9" rx="1.5"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>',
};
export const icon = (name) => `<svg class="ck-i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;

/** A keybind as the drawer prints it: `Ctrl+Alt+B`, or `⌘⌥B` on a Mac. */
export function keyLabel(action) {
  const live = window._pantheonKeybinds;
  const combo = (live && typeof live[action] === 'string') ? live[action] : (KEYBIND_DEFAULTS[action] || '');
  if (!combo) return '';
  if (!IS_MAC) return formatKeybind(combo);
  const glyph = { ctrl: '⌘', alt: '⌥', shift: '⇧' };
  return combo.split('+').map((p) => glyph[p] || (p.length === 1 ? p.toUpperCase() : formatKeybind(p))).join('');
}

/* ───────────────────────── tone ───────────────────────── */

/** `light` or `dark`, from the theme's own background — the material tunables
 *  follow it. The same luminance test theme.js uses for `color-scheme`. */
export function toneOf(bgHex) {
  const h = String(bgHex || '').trim().replace('#', '');
  if (!/^[0-9a-f]{6}$/i.test(h)) return 'dark';
  const lin = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return (0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]) > 0.5 ? 'light' : 'dark';
}

function syncTone() {
  const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg');
  document.documentElement.dataset.ckTone = toneOf(bg);
}

/* ───────────────────────── the light field ───────────────────────── */

function mountField() {
  if (byId('ck-field')) return;
  const field = document.createElement('div');
  field.id = 'ck-field';
  field.setAttribute('aria-hidden', 'true');
  field.innerHTML = '<span></span><span></span><span></span><span></span>';
  document.body.insertBefore(field, document.body.firstChild);
}

/* ───────────────────────── 1 · the rail ───────────────────────── */

// Three bands: work, inbox, make. Theme and Settings sit at the foot.
const RAIL_BANDS = [
  [['ck-rail-sidebar', 'sidebar', 'Sidebar', 'toggle_sidebar'], ['rail-search-btn', 'search', 'Search', 'search'], ['rail-new-session', 'plus', 'New chat', 'new_session']],
  [['rail-chats', 'chat', 'Chats'], ['rail-documents', 'doc', 'Documents'], ['rail-agents', 'agents', 'Agents'], ['rail-tasks', 'tasks', 'Tasks']],
  [['rail-email', 'mail', 'Email'], ['rail-calendar', 'cal', 'Calendar'], ['rail-notes', 'notes', 'Notes'], ['rail-assistant', 'spark', 'Assistant']],
  [['rail-cookbook', 'flame', 'Forge'], ['rail-research', 'research', 'Deep Research'], ['rail-compare', 'compare', 'Compare'],
    ['rail-workbench', 'flow', 'Workbench'], ['rail-memory', 'brain', 'Brain'], ['rail-archive', 'library', 'Library'], ['rail-gallery', 'image', 'Gallery']],
];
const RAIL_FOOT = [['rail-theme', 'theme', 'Theme'], ['rail-settings', 'sliders', 'Settings', 'settings']];

function toggleSidebar() {
  // The sidebar's own door, so its module keeps the state, the stored
  // preference and every class it already writes.
  const btn = byId('sidebar-toggle-btn') || byId('hamburger-btn');
  if (btn) btn.click();
}

function buildRail() {
  const rail = byId('icon-rail');
  if (!rail || rail.dataset.ckBands) return;
  rail.dataset.ckBands = '1';
  if (!byId('ck-rail-sidebar')) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'icon-rail-btn';
    b.id = 'ck-rail-sidebar';
    b.setAttribute('aria-label', 'Sidebar');
    b.addEventListener('click', toggleSidebar);
    rail.appendChild(b);
  }
  const place = ([id, ic, tip, key]) => {
    const b = byId(id);
    if (!b) return;
    b.innerHTML = icon(ic) + Array.from(b.children).filter((c) => !(c instanceof SVGElement) && !c.classList.contains('rail-hover-label')).map((c) => c.outerHTML).join('');
    const k = key ? keyLabel(key) : '';
    b.dataset.ckTip = k ? `${tip}  ${k}` : tip;
    if (!b.getAttribute('aria-label')) b.setAttribute('aria-label', tip);
    rail.appendChild(b);
  };
  const handle = byId('rail-resize-handle');
  RAIL_BANDS.forEach((band, i) => {
    if (i) { const s = document.createElement('div'); s.className = 'ck-band'; s.setAttribute('aria-hidden', 'true'); rail.appendChild(s); }
    band.forEach(place);
  });
  // Whatever the rail held that the bands do not name stays, after them.
  $$('.icon-rail-btn', rail).forEach((b) => {
    const named = [...RAIL_BANDS.flat(), ...RAIL_FOOT].some(([id]) => id === b.id);
    if (!named && b.id !== 'rail-delete-session') rail.appendChild(b);
  });
  $$('.rail-separator, .icon-rail-divider', rail).forEach((s) => s.remove());
  Array.from(rail.children).forEach((c) => { if (c.tagName === 'DIV' && c.style.flex === '1') c.remove(); });
  const spacer = document.createElement('div');
  spacer.style.flex = '1';
  spacer.className = 'ck-rail-spacer';
  rail.appendChild(spacer);
  RAIL_FOOT.forEach(place);
  const del = byId('rail-delete-session');
  if (del) rail.appendChild(del);   // kept, hidden: Delete lives in the chat's menu
  if (handle) rail.insertBefore(handle, rail.firstChild);

  // Chats is a destination: with nothing waiting it opens the drawer.
  const chats = byId('rail-chats');
  if (chats) {
    chats.addEventListener('click', () => {
      if (chats.dataset.targetSession) return;   // app.js opens the finished chat
      const html = document.documentElement;
      if (html.classList.contains('pan-sidebar-mini') || html.classList.contains('pan-sidebar-off')) toggleSidebar();
    });
  }
  syncRailCurrent();
}

/** The rail item you are on carries `aria-current`: Chats, unless a tool's
 *  window is open in front, which modalManager already marks `.active-section`. */
function syncRailCurrent() {
  const chats = byId('rail-chats');
  if (!chats) return;
  const toolOpen = !!$('.icon-rail .icon-rail-btn.active-section');
  chats.setAttribute('aria-current', String(!toolOpen));
}

/* ───────────────────────── 2 · the drawer ───────────────────────── */

function buildDrawer() {
  const brand = byId('sidebar-brand-btn');
  if (brand && !$('.ck-wave', brand)) {
    brand.insertAdjacentHTML('afterbegin', '<span class="ck-wave" aria-hidden="true"><i></i><i></i><i></i></span>');
    const k = keyLabel('toggle_sidebar');
    if (k) brand.insertAdjacentHTML('beforeend', `<span class="ck-kbd">${k}</span>`);
  }
  [['sidebar-new-chat-btn', 'plus', 'new_session'], ['sidebar-search-btn', 'search', 'search']].forEach(([id, ic, key]) => {
    const b = byId(id);
    if (!b || b.dataset.ckDone) return;
    b.dataset.ckDone = '1';
    const svg = $('svg', b);
    if (svg) svg.outerHTML = icon(ic);
    const k = keyLabel(key);
    if (k) b.insertAdjacentHTML('beforeend', `<span class="ck-kbd">${k}</span>`);
  });
  const t = byId('chats-section-title');
  if (t && !t.dataset.ckDone) { t.dataset.ckDone = '1'; }
}

/* ───────────────────────── top bar ───────────────────────── */

function buildTopBar() {
  const overlay = $('.chat-meta-overlay');
  const nobody = byId('incognito-btn');
  if (!overlay) return;
  if (!$('.ck-grow', overlay)) {
    const g = document.createElement('span');
    g.className = 'ck-grow';
    const wrap = byId('export-dropdown-wrap');
    overlay.insertBefore(g, wrap || null);
  }
  if (nobody && nobody.parentElement !== overlay) {
    const svg = $('svg.eye-open', nobody);
    if (svg) svg.outerHTML = icon('mask').replace('class="ck-i"', 'class="ck-i eye-open"');
    overlay.insertBefore(nobody, byId('export-dropdown-wrap') || null);
    nobody.setAttribute('aria-pressed', String(nobody.classList.contains('active')));
    new MutationObserver(() => nobody.setAttribute('aria-pressed', String(nobody.classList.contains('active'))))
      .observe(nobody, { attributes: true, attributeFilter: ['class'] });
  }
  const exp = byId('export-dl-btn');
  if (exp && !exp.getAttribute('aria-label')) exp.setAttribute('aria-label', 'Chat menu');
}

/* ───────────────────────── 9 · ready: a preflight ───────────────────────── */

const READY = {
  model: { k: 'Model' }, workstation: { k: 'Workstation' }, brain: { k: 'Brain' },
  workspace: { k: 'Workspace' }, tools: { k: 'Tools' }, approval: { k: 'Approval' },
};
const _readyData = {};

async function getJSON(url) {
  try {
    const r = await fetch(url, { credentials: 'same-origin' });
    return r.ok ? await r.json() : null;
  } catch (_) { return null; }
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function hostOf(url) {
  try { return new URL(url).host; } catch (_) { return ''; }
}

function isLocalHost(host) {
  return /^(localhost|127\.|0\.0\.0\.0|\[::1\]|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|[^.]+$|.*\.local(:|$)|.*\.lan(:|$))/i.test(host || '');
}

function ago(iso) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '';
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function contextFigures() {
  const pill = byId('chat-context-pill');
  const m = pill && /of\s+([\d.]+[KM]?)\s+tokens/i.exec(pill.title || '');
  return m ? m[1].replace('K', 'k') : '';
}

function toolState() {
  const on = (id) => { const b = byId(id); return !!(b && (b.classList.contains('active') || b.getAttribute('aria-pressed') === 'true')); };
  return { plan: on('plan-toggle-btn'), web: on('web-toggle-btn'), shell: on('bash-toggle-btn'), agent: on('mode-agent-btn') };
}

function readyCells() {
  const d = _readyData;
  const cells = [];
  const dc = d.defaultChat || window.__pantheonDefaultChat || null;
  const label = (byId('model-picker-label')?.textContent || '').trim();
  const model = (dc && dc.model) ? String(dc.model).split('/').pop() : (label && !/select model/i.test(label) ? label : '');
  const host = dc ? hostOf(dc.endpoint_url) : '';
  const local = host ? isLocalHost(host) : false;
  cells.push({
    key: 'model', led: model ? '' : 'warn', v: model || 'No model yet',
    s: model ? [host, host ? (local ? 'local' : 'API') : ''].filter(Boolean).join(' · ') || 'Default model' : 'Add a model endpoint to start',
    go: () => (model ? byId('model-picker-btn')?.click() : byId('rail-settings')?.click()),
  });
  const ws = d.workstation;
  const wsOn = ws && ws.state && ws.state !== 'off' && ws.state !== 'error' && ws.enabled !== false;
  cells.push({
    key: 'workstation', led: ws && ws.state === 'error' ? 'warn' : '',
    v: !ws ? 'Checking' : (wsOn ? 'Online' : (ws.enabled === false ? 'Off' : String(ws.state || 'Off').replace(/^./, (c) => c.toUpperCase()))),
    s: ws ? (ws.sentence || '') : '',
    go: () => import('./workstationScreen.js').then((m) => m.openWorkstationScreen({ focus: true })).catch(() => {}),
  });
  const mem = d.memory ? d.memory.length : null;
  const skills = d.skills ? d.skills.length : null;
  cells.push({
    key: 'brain', led: '',
    v: mem == null ? '—' : `${mem.toLocaleString()} ${mem === 1 ? 'memory' : 'memories'}`,
    s: skills == null ? '' : `${skills.toLocaleString()} ${skills === 1 ? 'skill' : 'skills'} published`,
    go: () => byId('rail-memory')?.click(),
  });
  const wsName = (byId('workspace-indicator-name')?.textContent || '').trim();
  const wsVisible = byId('workspace-indicator-btn') && byId('workspace-indicator-btn').style.display !== 'none' && wsName;
  cells.push({
    key: 'workspace', led: '', mono: !!wsVisible,
    v: wsVisible ? wsName.replace(/\//g, '/​') : 'No folder',
    s: wsVisible ? 'The folder the agent works in' : 'Pick a folder the agent works in',
    go: () => byId('overflow-workspace-btn')?.click(),
  });
  const t = toolState();
  const onTools = [t.web && 'Web', t.shell && 'Shell'].filter(Boolean);
  const mcp = d.mcp ? d.mcp.reduce((n, s) => n + (Array.isArray(s.tools) ? s.tools.length : Number(s.tool_count || 0)), 0) : null;
  cells.push({
    key: 'tools', led: '',
    v: !t.agent ? 'Chat only' : (onTools.length ? onTools.join(' · ') : 'None on'),
    s: [`Plan ${t.plan ? 'on' : 'off'}`, mcp != null ? `${mcp} MCP ${mcp === 1 ? 'tool' : 'tools'}` : ''].filter(Boolean).join(' · '),
    go: () => byId('overflow-plus-btn')?.click(),
  });
  const auto = document.body.classList.contains('ck-auto-approve');
  const apLabel = (byId('approval-mode-label')?.textContent || '').trim();
  cells.push({
    key: 'approval', led: 'warn',
    v: apLabel || (auto ? 'Auto-approve' : 'Manual'),
    s: auto ? 'Steps run without asking' : 'Every step asks first',
    go: () => { const b = byId('approval-mode-btn'); if (b && b.offsetParent) b.click(); else byId('turn-chip')?.click(); },
  });
  return cells;
}

function readySentence() {
  const cells = readyCells();
  const model = cells[0];
  const ws = _readyData.workstation;
  const wsOn = ws && ws.state && ws.state !== 'off' && ws.enabled !== false;
  const ctx = contextFigures();
  if (model.led === 'warn') {
    return { led: 'warn', html: '<b>Not ready.</b> No model is set up yet; add one in Settings and Pantheon is ready to go.' };
  }
  const where = /local/.test(model.s) ? 'on this machine' : (model.s.includes('API') ? 'through its API' : '');
  const parts = [`${esc(model.v)}${where ? ' ' + where : ''}`];
  if (ctx) parts.push(`${esc(ctx)} context`);
  parts.push(ws ? `workstation ${wsOn ? 'online' : 'off'}` : 'checking the workstation');
  return { led: 'ok', html: `<b>Ready.</b> ${parts.join(', ')}.` };
}

function renderReady({ animate = false } = {}) {
  const host = byId('ck-ready');
  if (!host) return;
  const st = readySentence();
  const cells = readyCells();
  $('.ck-ready-state', host).innerHTML = `<span class="ck-led ${st.led}"></span><span>${st.html}</span>`;
  const grid = $('.ck-preflight', host);
  grid.innerHTML = cells.map((c, i) => `<button type="button" class="ck-pf" role="listitem" data-cell="${c.key}" data-i="${i}">`
    + `<span class="k"><span class="ck-led ${c.led}"></span>${READY[c.key].k}</span>`
    + `<span class="v${c.mono ? ' mono' : ''}">${esc(c.v)}</span><span class="s">${esc(c.s)}</span></button>`).join('');
  $$('.ck-pf', grid).forEach((b) => b.addEventListener('click', () => { const c = cells[Number(b.dataset.i)]; if (c && c.go) c.go(); }));
  renderLeftOpen();
  if (animate) {
    const inner = $('.ck-ready-in', host);
    inner.classList.remove('ck-run-in'); void inner.offsetWidth; inner.classList.add('ck-run-in');
  }
}

function renderLeftOpen() {
  const box = $('.ck-left-open', byId('ck-ready'));
  if (!box) return;
  const rows = [];
  const current = window.sessionModule?.getCurrentSessionId?.() || '';
  (_readyData.sessions || [])
    .filter((s) => s && !s.archived && s.id !== current && Number(s.message_count || 0) > 0 && s.folder !== 'Assistant')
    .sort((a, b) => Date.parse(b.last_message_at || b.updated_at || 0) - Date.parse(a.last_message_at || a.updated_at || 0))
    .slice(0, 2)
    .forEach((s) => rows.push({
      ic: s.mode === 'agent' ? 'agents' : 'chat', t: s.name || 'Untitled chat',
      sub: `${s.mode === 'agent' ? 'Agent chat' : 'Chat'} · ${Number(s.message_count || 0)} messages · ${ago(s.last_message_at || s.updated_at)}`,
      go: 'Resume', act: () => window.sessionModule?.selectSession?.(s.id),
    }));
  const doc = (_readyData.documents || [])[0];
  if (doc) {
    rows.push({
      ic: 'doc', t: doc.title || doc.name || 'Untitled document',
      sub: `Document · edited ${ago(doc.updated_at || doc.created_at)}`.replace(/ · edited $/, ''),
      go: 'Open', act: () => { if (doc.session_id) window.sessionModule?.selectSession?.(doc.session_id); else byId('rail-archive')?.click(); },
    });
  }
  box.hidden = !rows.length;
  box.innerHTML = rows.length ? '<div class="h">Left open</div>' + rows.map((r, i) =>
    `<button type="button" class="ck-lo" data-i="${i}">${icon(r.ic)}<span class="t">${esc(r.t)}<small>${esc(r.sub)}</small></span><span class="go">${r.go}</span></button>`).join('') : '';
  $$('.ck-lo', box).forEach((b) => b.addEventListener('click', () => rows[Number(b.dataset.i)].act()));
}

async function refreshReadyData() {
  const [defaultChat, workstation, memory, skills, mcp, sessions, documents] = await Promise.all([
    getJSON('/api/default-chat'), getJSON('/api/workstation/status'), getJSON('/api/memory'),
    getJSON('/api/skills'), getJSON('/api/mcp/servers'), getJSON('/api/sessions'), getJSON('/api/documents/library?limit=1'),
  ]);
  Object.assign(_readyData, {
    defaultChat: defaultChat && defaultChat.model ? defaultChat : (window.__pantheonDefaultChat || null),
    workstation,
    memory: memory && Array.isArray(memory.memory) ? memory.memory : null,
    skills: skills && Array.isArray(skills.skills) ? skills.skills : null,
    mcp: Array.isArray(mcp) ? mcp : (mcp && Array.isArray(mcp.servers) ? mcp.servers : null),
    sessions: Array.isArray(sessions) ? sessions : null,
    documents: documents && Array.isArray(documents.documents) ? documents.documents : null,
  });
  renderReady();
}

function buildReady() {
  const screen = byId('welcome-screen');
  if (!screen || byId('ck-ready')) return;
  const ready = document.createElement('section');
  ready.id = 'ck-ready';
  ready.className = 'ck-ready';
  ready.setAttribute('aria-label', 'System ready');
  ready.innerHTML = '<div class="ck-ready-in ck-run-in" style="display:flex;flex-direction:column;gap:20px">'
    + '<div class="ck-ready-head"><span class="ck-wave lg" aria-hidden="true"><i></i><i></i><i></i></span><h2 class="ck-ready-word">Pantheon</h2></div>'
    + '<div class="ck-ready-state" role="status" aria-live="polite"></div>'
    + '<div class="ck-preflight" role="list"></div>'
    + '<div class="ck-left-open" hidden></div></div>';
  screen.insertBefore(ready, screen.firstChild);
  renderReady();
  refreshReadyData();
  // Re-read when the things the cells show change.
  const rerender = () => { clearTimeout(rerender._t); rerender._t = setTimeout(() => renderReady(), 60); };
  ['web-toggle-btn', 'bash-toggle-btn', 'plan-toggle-btn', 'mode-agent-btn', 'workspace-indicator-btn', 'approval-mode-label', 'model-picker-label', 'chat-context-pill']
    .forEach((id) => { const n = byId(id); if (n) new MutationObserver(rerender).observe(n, { attributes: true, childList: true, characterData: true, subtree: true }); });
  const cc = byId('chat-container');
  if (cc) {
    let wasWelcome = cc.classList.contains('welcome-active');
    new MutationObserver(() => {
      const now = cc.classList.contains('welcome-active');
      if (now && !wasWelcome) { refreshReadyData(); renderReady({ animate: true }); }
      wasWelcome = now;
    }).observe(cc, { attributes: true, attributeFilter: ['class'] });
  }
  setInterval(() => { if (document.visibilityState === 'visible' && cc && cc.classList.contains('welcome-active')) refreshReadyData(); }, 60000);
}

/* ───────────────────────── 6 · one strip ───────────────────────── */

const STRIP_TABS = [
  { id: 'plan-window', tab: 'plan', icon: 'plan', label: 'Plan', count: 'plan-window-count' },
  { id: 'queue-panel', tab: 'queue', icon: 'queue', label: 'Queue', count: 'queue-panel-count' },
  { id: 'agent-drafts-panel', tab: 'needs', icon: 'hand', label: 'Needs you', count: 'agent-drafts-count', attn: true },
];

function buildStrip() {
  const cc = byId('chat-container');
  const first = byId('plan-window');
  if (!cc || !first || byId('ck-strip')) return;
  const strip = document.createElement('div');
  strip.id = 'ck-strip';
  strip.hidden = true;
  strip.innerHTML = '<div class="ck-strip-tabs" role="tablist" aria-label="Plan, queue and approvals">'
    + STRIP_TABS.map((t) => `<button type="button" class="ck-stab${t.attn ? ' attn' : ''}" role="tab" aria-selected="false" data-tab="${t.tab}" data-for="${t.id}" hidden>${icon(t.icon)}${t.label} <span class="n"></span></button>`).join('')
    + `</div><button type="button" class="ck-ibtn ck-strip-fold" style="width:24px;height:24px" aria-label="Fold" aria-expanded="true">${icon('chevd')}</button><div class="ck-strip-body"></div>`;
  first.parentElement.insertBefore(strip, first);
  const body = $('.ck-strip-body', strip);
  STRIP_TABS.forEach((t) => { const n = byId(t.id); if (n) body.appendChild(n); });
  let chosen = '';
  const sync = () => {
    const shown = STRIP_TABS.filter((t) => { const n = byId(t.id); return n && !n.hidden; });
    strip.hidden = !shown.length;
    if (!shown.length) return;
    // What needs you comes forward by itself; otherwise the tab you chose, or the first.
    const needs = shown.find((t) => t.attn);
    let active = shown.find((t) => t.tab === chosen) || shown[0];
    if (needs && strip.dataset.lastNeeds !== '1') active = needs;
    strip.dataset.lastNeeds = needs ? '1' : '';
    STRIP_TABS.forEach((t) => {
      const tab = $(`.ck-stab[data-tab="${t.tab}"]`, strip);
      const panel = byId(t.id);
      const on = shown.includes(t);
      tab.hidden = !on;
      tab.setAttribute('aria-selected', String(t === active));
      if (panel) panel.classList.toggle('ck-strip-active', t === active);
      const count = byId(t.count);
      $('.n', tab).textContent = count ? count.textContent.replace(/[()]/g, '').trim() : '';
    });
  };
  $$('.ck-stab', strip).forEach((tab) => tab.addEventListener('click', () => { chosen = tab.dataset.tab; strip.classList.remove('folded'); sync(); }));
  $('.ck-strip-fold', strip).addEventListener('click', (e) => {
    const folded = strip.classList.toggle('folded');
    e.currentTarget.setAttribute('aria-expanded', String(!folded));
  });
  const mo = new MutationObserver(sync);
  STRIP_TABS.forEach((t) => {
    const n = byId(t.id);
    if (n) mo.observe(n, { attributes: true, attributeFilter: ['hidden'] });
    const c = byId(t.count);
    if (c) mo.observe(c, { childList: true, characterData: true, subtree: true });
  });
  sync();
}

/* ───────────────────────── 3 · the loadout ───────────────────────── */

const LOADOUT_IDS = ['workspace-indicator-btn', 'summon-indicator-btn', 'doc-indicator-btn', 'rag-indicator-btn',
  'research-toggle-btn', 'group-toggle-btn', 'character-indicator-btn', 'compare-indicator-btn'];

function buildLoadout() {
  const bar = $('.chat-input-bar');
  const top = $('.chat-input-top', bar || document);
  if (!bar || !top || byId('ck-loadout')) return;
  const row = document.createElement('div');
  row.id = 'ck-loadout';
  row.className = 'ck-loadout';
  top.insertAdjacentElement('afterend', row);
  LOADOUT_IDS.forEach((id) => { const n = byId(id); if (n) row.appendChild(n); });
  const strip = byId('attach-strip');
  if (strip) row.insertBefore(strip, row.firstChild);
  // The study's chips: an icon, the name, and a × that does what the chip's own click does.
  const folder = byId('workspace-indicator-btn');
  if (folder && !$('.ck-i', folder)) {
    const svg = $('svg', folder);
    if (svg) svg.outerHTML = icon('folder');
  }
}

/* ───────────────────────── composer details ───────────────────────── */

function buildComposer() {
  const left = $('.chat-input-left');
  const wrap = $('.overflow-wrapper', left || document);
  if (left && wrap && !$('.ck-vsep', left)) {
    const sep = document.createElement('span');
    sep.className = 'ck-vsep';
    sep.setAttribute('aria-hidden', 'true');
    wrap.insertAdjacentElement('afterend', sep);
  }
  [['plan-toggle-btn', 'plan'], ['web-toggle-btn', 'globe'], ['bash-toggle-btn', 'term']].forEach(([id, ic]) => {
    const b = byId(id);
    if (!b || b.dataset.ckIcon) return;
    b.dataset.ckIcon = '1';
    const svg = $('svg', b);
    if (svg) svg.outerHTML = icon(ic);
    else b.insertAdjacentHTML('afterbegin', icon(ic));
  });
  const plus = byId('overflow-plus-btn');
  if (plus) {
    const menu = byId('overflow-menu');
    const sync = () => plus.setAttribute('aria-expanded', String(!!(menu && !menu.classList.contains('hidden'))));
    if (menu) new MutationObserver(sync).observe(menu, { attributes: true, attributeFilter: ['class'] });
    sync();
  }
  // Where the model runs, said beside its name.
  const label = byId('model-picker-label');
  const btn = byId('model-picker-btn');
  const syncLoc = () => {
    if (!btn) return;
    let loc = $('.ck-loc', btn);
    const dc = window.__pantheonDefaultChat;
    const host = dc ? hostOf(dc.endpoint_url) : '';
    const text = host ? (isLocalHost(host) ? 'LOCAL' : 'API') : '';
    if (!text) { if (loc) loc.remove(); return; }
    if (!loc) { loc = document.createElement('span'); loc.className = 'ck-loc'; label.insertAdjacentElement('afterend', loc); }
    loc.textContent = text;
  };
  if (label) new MutationObserver(syncLoc).observe(label, { childList: true, characterData: true, subtree: true });
  syncLoc();
  // The mode lock follows this chat's approval mode, which approvalMode.js
  // already shows with the header badge (visible only while Auto is on).
  const badge = byId('chat-auto-approve-badge');
  const syncAuto = () => document.body.classList.toggle('ck-auto-approve', !!(badge && !badge.hidden));
  if (badge) new MutationObserver(syncAuto).observe(badge, { attributes: true, attributeFilter: ['hidden'] });
  syncAuto();
}

/* ───────────────────────── 5 · the ring ───────────────────────── */

function buildRing() {
  const pill = byId('chat-context-pill');
  if (!pill) return;
  if (!$('svg', pill)) {
    import('./contextUsage.js').then((m) => { if (!$('svg', pill)) m.renderPill(pill, null); }).catch(() => {});
  }
}

/* ───────────────────────── boot ───────────────────────── */

export function initCockpit() {
  if (!document.documentElement.classList.contains('cockpit')) return;
  syncTone();
  new MutationObserver(syncTone).observe(document.documentElement, { attributes: true, attributeFilter: ['style'] });
  mountField();
  buildRail();
  buildDrawer();
  buildTopBar();
  buildReady();
  buildStrip();
  buildLoadout();
  buildComposer();
  buildRing();
  const rail = byId('icon-rail');
  if (rail) new MutationObserver(syncRailCurrent).observe(rail, { attributes: true, subtree: true, attributeFilter: ['class'] });
  // The drawer's keys follow the person's own binds once they have loaded.
  setTimeout(() => {
    $$('.icon-rail-btn[data-ck-tip]').forEach((b) => {
      const band = [...RAIL_BANDS.flat(), ...RAIL_FOOT].find(([id]) => id === b.id);
      if (band && band[3]) { const k = keyLabel(band[3]); b.dataset.ckTip = k ? `${band[2]}  ${k}` : band[2]; }
    });
  }, 3000);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initCockpit);
else initCockpit();
