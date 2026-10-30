// SPDX-License-Identifier: AGPL-3.0-or-later
//
// cockpitWorkspace.js — the workspace dock: the right-hand column of the
// cockpit shell (`static/cockpit.css`, note 8 of the V4 study).
//
// The column holds three surfaces, one or several at once: the Document
// editor, the Workstation screen and the agent's Browser. **It builds none of
// them.** Each is the window its own module already draws —
//
//   Document     `#doc-editor-pane`        document.js (opened by `#overflow-doc-btn`)
//   Workstation  `#workstation-screen-modal` workstationScreen.js
//   Browser      `#agent-browser-modal`      browserWindow.js
//
// — and this module only decides WHERE it sits: in a pane of the column, or
// floating over the page. A tool window floats exactly as it always did
// (`windowDrag`, `tileManager`, the minimized dock); docking it moves the same
// node into a pane, and the window's own buttons (Take over, Hand back, the
// address bar, the editor's toolbar) keep working because nothing about them
// changed. The pane header — title, who holds it, float, fill, close — is the
// one header every surface shares; its close is the window's own close.
//
// Layouts: one at a time, side by side, stacked, one large over two small.
// Drag a pane by its header to float it; drop a floating window on the column
// to dock it. `toggle_workspace` (Ctrl+\) tucks the column to a tab.

import { icon } from './cockpit.js';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const byId = (id) => document.getElementById(id);
const LS = 'pantheon-cockpit-workspace';
const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const EASE = 'cubic-bezier(.22,.9,.24,1)';

const SURFACES = {
  doc: { label: 'Document', icon: 'doc', node: () => byId('doc-editor-pane') },
  vm: { label: 'Workstation', icon: 'monitor', node: () => byId('workstation-screen-modal') },
  browser: { label: 'Browser', icon: 'browser', node: () => byId('agent-browser-modal') },
};
const ORDER = ['doc', 'vm', 'browser'];

const W = {
  layout: 'rows', focus: 'doc', max: null,
  floating: new Set(),   // surfaces the person floated; they stay floating until docked
  off: false, width: '',
};

function load() {
  try {
    const s = JSON.parse(localStorage.getItem(LS) || 'null');
    if (s && typeof s === 'object') {
      if (['one', 'cols', 'rows', 'main'].includes(s.layout)) W.layout = s.layout;
      W.off = !!s.off;
      if (typeof s.width === 'string' && /^\d+(\.\d+)?(px|%)$/.test(s.width)) W.width = s.width;
      if (Array.isArray(s.floating)) s.floating.filter((k) => SURFACES[k]).forEach((k) => W.floating.add(k));
    }
  } catch (_) { /* a fresh column */ }
}
function save() {
  try { localStorage.setItem(LS, JSON.stringify({ layout: W.layout, off: W.off, width: W.width, floating: [...W.floating] })); } catch (_) {}
}

let ws, grid, empty, tab, ghost, resizer;
const panes = {};

/** Is this surface open at all (docked or floating), and not minimized? */
function isOpen(key) {
  const n = SURFACES[key].node();
  if (!n || !n.isConnected) return false;
  if (key === 'doc') return document.body.classList.contains('doc-view') || !!n.closest('.ck-pane');
  return !n.classList.contains('hidden') && !n.classList.contains('modal-minimized') && n.style.display !== 'none';
}

function openSurface(key) {
  if (key === 'doc') {
    if (window.documentModule && !window.documentModule.isPanelOpen?.()) byId('overflow-doc-btn')?.click();
  } else if (key === 'vm') {
    import('./workstationScreen.js').then((m) => m.openWorkstationScreen({ focus: false })).catch(() => {});
  } else if (key === 'browser') {
    import('./browserWindow.js').then((m) => m.openAgentBrowser({})).catch(() => {});
  }
}

function closeSurface(key) {
  if (key === 'doc') {
    if (window.documentModule?.closePanel) window.documentModule.closePanel();
    else byId('overflow-doc-btn')?.click();
  } else {
    const n = SURFACES[key].node();
    const close = n && $('.modal-header .close-btn', n);
    if (close) close.click();
  }
  W.floating.delete(key);
  if (W.max === key) W.max = null;
}

/* ───────────── panes ───────────── */

function buildPane(key) {
  const s = SURFACES[key];
  const pane = document.createElement('article');
  pane.className = 'ck-pane';
  pane.dataset.pane = key;
  pane.hidden = true;
  pane.innerHTML = `<header class="ck-pane-h">${icon(s.icon)}<span class="ttl">${s.label}</span><span class="ck-holder"></span><span class="grow"></span>`
    + `<button type="button" class="ck-ibtn act-pop" title="Float" aria-label="Float">${icon('popout')}</button>`
    + `<button type="button" class="ck-ibtn act-max" title="Fill workspace" aria-label="Fill workspace">${icon('max')}</button>`
    + `<button type="button" class="ck-ibtn act-close" title="Close" aria-label="Close">${icon('x')}</button></header>`
    + '<div class="ck-pane-b"></div>';
  $('.act-close', pane).addEventListener('click', () => { closeSurface(key); render(); });
  $('.act-max', pane).addEventListener('click', () => { W.max = W.max === key ? null : key; render(); });
  $('.act-pop', pane).addEventListener('click', () => floatSurface(key));
  $('.ck-pane-h', pane).addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || e.target.closest('button')) return;
    startPaneDrag(key, e);
  });
  return pane;
}

/** The window's own title and holder, read into the pane header. */
function syncHeader(key) {
  const pane = panes[key];
  const node = SURFACES[key].node();
  if (!pane || !node) return;
  const ttl = $('.ttl', pane);
  const holder = $('.ck-holder', pane);
  let title = SURFACES[key].label;
  let hold = '', cls = '';
  if (key === 'doc') {
    const active = document.querySelector('.doc-tab.active .doc-tab-title, .doc-tab.active .doc-tab-name, .doc-tab.active');
    const t = byId('doc-title-input')?.value || (active ? active.textContent.trim() : '');
    if (t) title = t;
    const streaming = byId('doc-stream-indicator');
    if (streaming && streaming.style.display !== 'none') { hold = 'Agent editing'; cls = 'agent'; }
    else { const v = byId('doc-version-badge')?.textContent?.trim(); hold = v ? `Saved · ${v}` : ''; }
  } else if (key === 'vm') {
    const give = $('.wsv-give', node);
    const statusText = $('.ws-status-text', node)?.textContent?.trim() || '';
    if (give && !give.hidden) { hold = 'You have control'; cls = 'you'; }
    else if (/agent/i.test(statusText) && /driv|work|using/i.test(statusText)) { hold = 'Agent driving'; cls = 'agent'; }
    else hold = 'Watching';
    title = 'Workstation';
  } else if (key === 'browser') {
    const t = $('.modal-header h4, .modal-header .abw-title, .modal-header [class*="title"]', node)?.textContent?.trim();
    if (t) title = t;
    if (node.classList.contains('abw-agent-busy')) { hold = 'Agent browsing'; cls = 'agent'; }
    else hold = 'Watching';
  }
  ttl.textContent = title;
  holder.textContent = hold;
  holder.className = 'ck-holder' + (cls ? ' ' + cls : '');
}

/** Put a surface's node in its pane (docked) or back on the body (floating). */
function seat(key) {
  const node = SURFACES[key].node();
  if (!node) return;
  const pane = panes[key];
  const body = $('.ck-pane-b', pane);
  if (key === 'doc') {
    if (!W.floating.has(key)) {
      if (node.parentElement !== body) body.appendChild(node);
      pane.classList.remove('ck-floating');
    }
    return;
  }
  if (W.floating.has(key)) {
    if (node.parentElement !== document.body) {
      node.classList.remove('ck-docked');
      document.body.appendChild(node);
    }
  } else if (node.parentElement !== pane) {
    node.classList.add('ck-docked');
    // A docked window has no snap state of its own.
    $('.modal-content', node)?.classList.remove('modal-left-docked', 'modal-right-docked', 'tile-snapped');
    pane.appendChild(node);
  }
}

/* ───────────── render ───────────── */

function render() {
  if (!ws) return;
  const docked = ORDER.filter((k) => isOpen(k) && !W.floating.has(k));
  ORDER.forEach((k) => { if (isOpen(k)) seat(k); });
  if (W.max && !docked.includes(W.max)) W.max = null;
  if (W.layout === 'one' && !docked.includes(W.focus)) W.focus = docked[0] || W.focus;
  const shown = W.max ? [W.max] : (W.layout === 'one' ? docked.filter((k) => k === W.focus) : docked);
  ORDER.forEach((k) => {
    const p = panes[k];
    p.hidden = !shown.includes(k);
    p.style.gridArea = '';
    if (!p.hidden) syncHeader(k);
    $('.act-max', p).innerHTML = icon(W.max === k ? 'lmain' : 'max');
    // A floating Document travels with its pane.
    if (k === 'doc') {
      p.classList.toggle('ck-floating', W.floating.has('doc') && isOpen('doc'));
      if (W.floating.has('doc') && isOpen('doc')) p.hidden = false;
    }
  });
  empty.hidden = shown.length > 0;
  const n = shown.length;
  let cols = '1fr', rows = '1fr';
  if (n > 1) {
    const lay = W.max ? 'one' : W.layout;
    if (lay === 'cols') cols = `repeat(${n}, minmax(0,1fr))`;
    else if (lay === 'rows') rows = `repeat(${n}, minmax(0,1fr))`;
    else if (lay === 'main') {
      cols = n === 2 ? '1fr' : '1fr 1fr';
      rows = n === 2 ? '1.4fr 1fr' : '1.5fr 1fr';
      if (n === 3) panes[shown[0]].style.gridArea = '1 / 1 / 2 / 3';
    }
  }
  grid.style.gridTemplateColumns = cols;
  grid.style.gridTemplateRows = rows;
  $$('.ck-surf', ws).forEach((b) => {
    const k = b.dataset.surf;
    b.setAttribute('aria-pressed', String(isOpen(k)));
    const live = (k === 'browser' && SURFACES.browser.node()?.classList.contains('abw-agent-busy'))
      || (k === 'doc' && byId('doc-stream-indicator') && byId('doc-stream-indicator').style.display !== 'none');
    let act = $('.act', b);
    if (live && !act) b.insertAdjacentHTML('beforeend', '<span class="act" aria-hidden="true"></span>');
    if (!live && act) act.remove();
  });
  $$('.ck-layouts button', ws).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.layout === W.layout)));
  document.documentElement.classList.toggle('ck-ws-off', W.off);
  const anyLive = $$('.ck-surf .act', ws).length > 0;
  $('.act', tab).hidden = !anyLive;
  if (W.width) document.documentElement.style.setProperty('--ck-ws-w', W.width);
}

/* ───────────── float and dock ───────────── */

const rectOf = (el) => { const r = el.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height }; };
const px = (b) => ({ left: b.left + 'px', top: b.top + 'px', width: b.width + 'px', height: b.height + 'px' });

function floatSurface(key, at) {
  const pane = panes[key];
  const from = rectOf(pane);
  W.floating.add(key);
  if (W.max === key) W.max = null;
  save();
  if (key === 'doc') {
    pane.classList.add('ck-floating');
    const w = Math.min(560, window.innerWidth - 80), h = Math.min(480, window.innerHeight - 120);
    const to = at ? { left: at.x, top: at.y, width: w, height: h }
      : { left: Math.max(20, from.left - 80), top: Math.max(60, from.top + 20), width: w, height: h };
    Object.assign(pane.style, px(to));
    document.body.appendChild(pane);
    $('.act-pop', pane).innerHTML = icon('dockin');
    $('.act-pop', pane).title = 'Dock in workspace';
    render();
    if (!reduced() && from.width && !at) pane.animate([px(from), px(to)], { duration: 480, easing: EASE });
    return;
  }
  const node = SURFACES[key].node();
  render();
  // The tool window takes its own place again: where it was before, or near the pane.
  const content = node && $('.modal-content', node);
  if (content) {
    const to = at ? { left: at.x, top: at.y } : { left: Math.max(20, from.left - 60), top: Math.max(60, from.top + 20) };
    content.style.position = 'fixed';
    content.style.left = to.left + 'px';
    content.style.top = to.top + 'px';
    content.style.margin = '0';
    if (!reduced() && from.width && !at) content.animate([{ transform: `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(.96)`, opacity: .6 }, { transform: 'none', opacity: 1 }], { duration: 480, easing: EASE });
  }
}

function dockSurface(key) {
  const pane = panes[key];
  const node = SURFACES[key].node();
  const from = key === 'doc' ? rectOf(pane) : (node && $('.modal-content', node) ? rectOf($('.modal-content', node)) : null);
  W.floating.delete(key);
  W.off = false;
  save();
  if (key === 'doc') {
    pane.classList.remove('ck-floating');
    pane.style.cssText = '';
    grid.insertBefore(pane, empty);
    $('.act-pop', pane).innerHTML = icon('popout');
    $('.act-pop', pane).title = 'Float';
  } else if (node) {
    const content = $('.modal-content', node);
    if (content) ['position', 'left', 'top', 'margin', 'width', 'height', 'transform'].forEach((p) => content.style.removeProperty(p));
  }
  ORDER.forEach((k) => { if (k !== 'doc') grid.insertBefore(panes[k], empty); });
  render();
  const to = rectOf(pane);
  if (!reduced() && from && from.width && to.width) {
    pane.animate([{ transform: `translate(${from.left - to.left}px, ${from.top - to.top}px)`, width: from.width + 'px', height: from.height + 'px' },
      { transform: 'none', width: to.width + 'px', height: to.height + 'px' }], { duration: 480, easing: EASE });
  }
}

function overWorkspace(x, y) {
  if (W.off) return x > window.innerWidth - 60;
  const r = ws.getBoundingClientRect();
  return x > r.left && x < r.right && y > r.top && y < r.bottom;
}

function showGhost(on) {
  if (on) {
    const r = W.off ? { left: window.innerWidth * 0.56, top: 18, right: 18, bottom: 18 }
      : (() => { const b = ws.getBoundingClientRect(); return { left: b.left + 8, top: b.top + 54, right: window.innerWidth - b.right + 8, bottom: window.innerHeight - b.bottom + 8 }; })();
    Object.assign(ghost.style, { left: r.left + 'px', top: r.top + 'px', right: r.right + 'px', bottom: r.bottom + 'px' });
  }
  ghost.classList.toggle('show', on);
  document.documentElement.classList.toggle('ck-ghosting', on);
}

/** Drag a docked pane by its header: it floats; drop it back on the column to dock. */
function startPaneDrag(key, e) {
  const pane = panes[key];
  const sx = e.clientX, sy = e.clientY;
  let moved = false, ox = 0, oy = 0, target = null;
  const move = (ev) => {
    if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 6) return;
    if (!moved) {
      moved = true;
      const r = pane.getBoundingClientRect();
      ox = sx - r.left; oy = sy - r.top;
      if (!W.floating.has(key)) floatSurface(key, { x: r.left, y: r.top });
      target = key === 'doc' ? pane : $('.modal-content', SURFACES[key].node());
      document.documentElement.classList.add('ck-dragging');
    }
    if (!target) return;
    const x = Math.max(0, Math.min(ev.clientX - ox, window.innerWidth - 120));
    const y = Math.max(0, Math.min(ev.clientY - oy, window.innerHeight - 40));
    target.style.left = x + 'px';
    target.style.top = y + 'px';
    showGhost(W.floating.has(key) && overWorkspace(ev.clientX, ev.clientY) && ev.clientX < sx - 40 ? false : overWorkspace(ev.clientX, ev.clientY) && moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) > 80);
  };
  const up = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    document.documentElement.classList.remove('ck-dragging');
    if (ghost.classList.contains('show')) { showGhost(false); dockSurface(key); }
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

/** A floating tool window dragged by its own header and dropped on the column docks there. */
function watchWindowDrops() {
  let dragging = null;
  document.addEventListener('pointerdown', (e) => {
    const header = e.target.closest && e.target.closest('.modal-header');
    if (!header || e.target.closest('button, input, select, label')) return;
    const key = ORDER.find((k) => k !== 'doc' && SURFACES[k].node() && SURFACES[k].node().contains(header));
    if (!key || !W.floating.has(key)) return;
    dragging = { key, x: e.clientX, y: e.clientY };
  }, true);
  window.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    if (Math.hypot(e.clientX - dragging.x, e.clientY - dragging.y) < 12) return;
    showGhost(overWorkspace(e.clientX, e.clientY));
  });
  window.addEventListener('pointerup', () => {
    if (!dragging) return;
    const { key } = dragging;
    dragging = null;
    if (ghost.classList.contains('show')) {
      showGhost(false);
      // after tileManager has settled the drop, take the window into the column
      setTimeout(() => dockSurface(key), 0);
    }
  });
}

/* ───────────── resizer, tuck ───────────── */

function bindResizer() {
  resizer.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    document.documentElement.classList.add('ck-dragging');
    const move = (ev) => {
      const w = Math.max(280, Math.min(window.innerWidth - ev.clientX - 18, window.innerWidth * 0.66));
      W.width = Math.round(w) + 'px';
      document.documentElement.style.setProperty('--ck-ws-w', W.width);
    };
    const up = () => {
      document.documentElement.classList.remove('ck-dragging');
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      save();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
  resizer.addEventListener('dblclick', () => { W.width = ''; document.documentElement.style.removeProperty('--ck-ws-w'); save(); });
  resizer.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const cur = ws.getBoundingClientRect().width;
    W.width = Math.round(cur + (e.key === 'ArrowLeft' ? 24 : -24)) + 'px';
    document.documentElement.style.setProperty('--ck-ws-w', W.width);
    save();
  });
}

export function toggleWorkspace(force) {
  W.off = typeof force === 'boolean' ? force : !W.off;
  save();
  render();
}

/* ───────────── boot ───────────── */

function build() {
  const cc = byId('chat-container');
  if (!cc || byId('ck-workspace')) return;
  resizer = document.createElement('div');
  resizer.id = 'ck-resizer';
  resizer.setAttribute('role', 'separator');
  resizer.setAttribute('aria-orientation', 'vertical');
  resizer.setAttribute('aria-label', 'Resize workspace');
  resizer.tabIndex = 0;
  ws = document.createElement('section');
  ws.id = 'ck-workspace';
  ws.setAttribute('aria-label', 'Workspace');
  ws.innerHTML = '<div class="ck-ws-head"><span class="lbl">Workspace</span>'
    + '<div class="ck-surf-list" role="group" aria-label="Surfaces">'
    + ORDER.map((k) => `<button type="button" class="ck-surf" data-surf="${k}" aria-pressed="false">${icon(SURFACES[k].icon)}<span class="tx">${SURFACES[k].label}</span></button>`).join('')
    + '</div><span class="grow"></span><div class="ck-layouts" role="group" aria-label="Layout">'
    + [['one', 'l1', 'One at a time'], ['cols', 'lcols', 'Side by side'], ['rows', 'lrows', 'Stacked'], ['main', 'lmain', 'One large, two small']]
      .map(([v, ic, t]) => `<button type="button" data-layout="${v}" aria-pressed="false" title="${t}" aria-label="${t}">${icon(ic)}</button>`).join('')
    + `</div><button type="button" class="ck-ibtn" id="ck-ws-tuck" title="Tuck workspace" aria-label="Tuck workspace">${icon('chev')}</button></div>`
    + '<div id="ck-ws-grid"></div>';
  grid = $('#ck-ws-grid', ws);
  ORDER.forEach((k) => { panes[k] = buildPane(k); grid.appendChild(panes[k]); });
  empty = document.createElement('div');
  empty.className = 'ck-ws-empty';
  empty.innerHTML = '<span>Nothing open. Turn on Document, Workstation or Browser above.</span>';
  grid.appendChild(empty);
  cc.insertAdjacentElement('afterend', resizer);
  resizer.insertAdjacentElement('afterend', ws);
  tab = document.createElement('button');
  tab.type = 'button';
  tab.id = 'ck-ws-tab';
  tab.title = 'Show workspace';
  tab.setAttribute('aria-label', 'Show workspace');
  tab.innerHTML = `${icon('back')}<span class="vert">Workspace</span><span class="act" hidden></span>`;
  document.body.appendChild(tab);
  ghost = document.createElement('div');
  ghost.id = 'ck-ghost';
  document.body.appendChild(ghost);

  $$('.ck-surf', ws).forEach((b) => b.addEventListener('click', () => {
    const k = b.dataset.surf;
    if (W.layout === 'one' && isOpen(k) && W.focus !== k && !W.floating.has(k)) { W.focus = k; render(); return; }
    if (isOpen(k)) closeSurface(k);
    else { W.focus = k; W.off = false; openSurface(k); }
    setTimeout(render, 60);
  }));
  $$('.ck-layouts button', ws).forEach((b) => b.addEventListener('click', () => { W.layout = b.dataset.layout; W.max = null; save(); render(); }));
  $('#ck-ws-tuck', ws).addEventListener('click', () => toggleWorkspace(true));
  tab.addEventListener('click', () => toggleWorkspace(false));
  document.addEventListener('pantheon:toggle-workspace', () => toggleWorkspace());
  bindResizer();
  watchWindowDrops();

  // A surface opened anywhere — the + menu, a slash command, an agent's door —
  // lands in the column; one closed anywhere leaves it.
  const mo = new MutationObserver(() => { clearTimeout(mo._t); mo._t = setTimeout(render, 30); });
  mo.observe(document.body, { childList: true, attributes: true, attributeFilter: ['class'] });
  const cc2 = byId('chat-container');
  if (cc2) mo.observe(cc2, { childList: true });
  ORDER.forEach((k) => {
    // Watch the windows' own state (hidden, minimized, holder) once they exist.
    const watch = () => { const n = SURFACES[k].node(); if (n && !n.dataset.ckWatched) { n.dataset.ckWatched = '1'; mo.observe(n, { attributes: true, subtree: true, attributeFilter: ['class', 'hidden', 'style'] }); } };
    setInterval(watch, 1500);
  });
  render();
}

export function initWorkspace() {
  if (!document.documentElement.classList.contains('cockpit')) return;
  if (window.matchMedia('(max-width: 768px)').matches) return;   // a phone keeps its own windows
  load();
  build();
  window.pantheonCockpit = Object.assign(window.pantheonCockpit || {}, { toggleWorkspace });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initWorkspace);
else initWorkspace();
