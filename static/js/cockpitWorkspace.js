// SPDX-License-Identifier: AGPL-3.0-or-later
//
// cockpitWorkspace.js — the workspace dock: the right-hand column of the
// cockpit shell (`static/cockpit.css`, note 8 of the V4 study).
//
// The column holds four surfaces, one or several at once: Documents,
// Workstation, Browser and Mobile Emulator. **It builds none of
// them.** Each is the window its own module already draws —
//
//   Document     `#doc-editor-pane`        document.js (opened by `#overflow-doc-btn`)
//   Workstation  `.modal.wsv-modal`  workstationScreen.js (its MODAL_ID)
//   Browser      `.modal.abw-modal`  browserWindow.js (its MODAL_ID)
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
import { prefersReducedMotion } from './motion.js';
import { renderEmptyState } from './ui.js';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const byId = (id) => document.getElementById(id);
const LS = 'pantheon-cockpit-workspace';
const reduced = prefersReducedMotion;
const EASE = 'cubic-bezier(.22,.9,.24,1)';

const SURFACES = {
  doc: { label: 'Documents', icon: 'doc', node: () => byId('doc-editor-pane') },
  vm: { label: 'Workstation', icon: 'monitor', node: () => document.querySelector('.modal.wsv-modal') },
  browser: { label: 'Browser', icon: 'browser', node: () => document.querySelector('.modal.abw-modal') },
  phone: { label: 'Mobile Emulator', icon: 'phone', node: () => document.querySelector('.modal.phw-modal') },
};
const ORDER = ['doc', 'vm', 'browser', 'phone'];
const LAYOUTS = [['one', 'l1', 'One at a time'], ['cols', 'lcols', 'Side by side'], ['rows', 'lrows', 'Stacked'], ['main', 'lmain', 'One large, the rest below']];
const MODAL_IDS = { vm: 'workstation-screen-modal', browser: 'agent-browser-modal', phone: 'phone-modal' };

const W = {
  layout: 'rows', focus: 'doc', max: null,
  floating: new Set(),   // surfaces the person floated; they stay floating until docked
  off: false, width: '',
};

function load() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(LS) || 'null'); } catch (_) { /* a fresh column */ }
  if (s && typeof s === 'object') {
    if (['one', 'cols', 'rows', 'main'].includes(s.layout)) W.layout = s.layout;
    W.off = !!s.off;
    if (typeof s.width === 'string' && /^\d+(\.\d+)?(px|%)$/.test(s.width)) W.width = s.width;
    if (Array.isArray(s.floating)) s.floating.filter((k) => SURFACES[k]).forEach((k) => W.floating.add(k));
  } else if (window.matchMedia('(max-width: 1023px)').matches) {
    // A fresh column on a tablet starts tucked. Beside the rail and the drawer,
    // the workspace's 280px minimum left the chat 162px at 820 wide: the ready
    // screen's cards one letter per line, the header title gone (alignment
    // audit, 2026-11-07). The tab opens it; the person's own choice is saved.
    W.off = true;
  }
}
function save() {
  try { localStorage.setItem(LS, JSON.stringify({ layout: W.layout, off: W.off, width: W.width, floating: [...W.floating] })); } catch (_) {}
}

let ws, grid, empty, tab, ghost, resizer;
let pendingFocus = '';   // a surface asked for from its tab, until its window lands
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
  } else if (key === 'phone') {
    import('./phoneWindow.js').then((m) => m.openPhone()).catch(() => {});
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
  } else if (key === 'phone') {
    title = $('.phw-title', node)?.textContent?.trim() || title;
    const give = $('.phw-give', node);
    if (give && !give.hidden) { hold = 'You have control'; cls = 'you'; }
    else {
      // The image is the device chip's; the header says the phone's state.
      const st = $('.phw-bezel', node)?.dataset.state || 'checking';
      hold = { on: 'Watching', starting: 'Starting', off: 'Off', installing: 'Installing', unavailable: 'Unavailable' }[st] || 'Checking';
    }
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

// 'cols' and 'main' set panes side by side. A pane narrower than this cannot
// keep its own header (title, holder, Float, Fill, Close) or its window's
// toolbar inside it, so those layouts stack as 'rows' until the column is wide
// enough again. W.layout keeps the person's choice; only the grid falls back.
const MIN_PANE_W = 260;
let settledW = 0;    // the grid's inner width the last time the column stood still
let fitted = '', fittedN = 0;

function fitLayout(lay, n) {
  const across = lay === 'cols' ? n : (lay === 'main' && n > 2 ? n - 1 : 1);
  if (across < 2) return lay;
  const cs = getComputedStyle(grid);
  // While the column is tucked or sliding in or out its width is not the one
  // it will have, so the answer from when it last stood still holds.
  const sliding = document.documentElement.classList.contains('ck-ws-off') || (ws.getAnimations?.() || []).some((a) => a.playState === 'running');
  if (!sliding) settledW = grid.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  if (settledW <= 0) return lay;
  return (settledW - (parseFloat(cs.columnGap) || 0) * (across - 1)) / across < MIN_PANE_W ? 'rows' : lay;
}

function render() {
  if (!ws) return;
  const docked = ORDER.filter((k) => isOpen(k) && !W.floating.has(k));
  ORDER.forEach((k) => { if (isOpen(k)) seat(k); });
  if (W.max && !docked.includes(W.max)) W.max = null;
  if (pendingFocus && docked.includes(pendingFocus)) { W.focus = pendingFocus; pendingFocus = ''; }
  if (!docked.includes(W.focus) && (W.layout === 'one' || !pendingFocus)) W.focus = docked[0] || W.focus;
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
  const lay = fitLayout(W.max ? 'one' : W.layout, n);
  fitted = lay; fittedN = n;
  if (n > 1) {
    if (lay === 'cols') cols = `repeat(${n}, minmax(0,1fr))`;
    else if (lay === 'rows') rows = `repeat(${n}, minmax(0,1fr))`;
    else if (lay === 'main') {
      cols = n === 2 ? '1fr' : `repeat(${n - 1}, minmax(0,1fr))`;
      rows = n === 2 ? '1.4fr 1fr' : '1.5fr 1fr';
      if (n > 2) panes[shown[0]].style.gridArea = `1 / 1 / 2 / ${n}`;
    }
  }
  grid.style.gridTemplateColumns = cols;
  grid.style.gridTemplateRows = rows;
  $$('.ck-surf', ws).forEach((b) => {
    const k = b.dataset.surf;
    const open = isOpen(k);
    b.setAttribute('aria-pressed', String(open));
    const live = (k === 'browser' && SURFACES.browser.node()?.classList.contains('abw-agent-busy'))
      || (k === 'doc' && byId('doc-stream-indicator') && byId('doc-stream-indicator').style.display !== 'none')
      || (k === 'vm' && open && /agent/i.test($('.wsv-modal .ws-status-text')?.textContent || '') && /driv|work|using/i.test($('.wsv-modal .ws-status-text')?.textContent || ''));
    let act = $('.act', b);
    if (live && !act) b.insertAdjacentHTML('beforeend', '<span class="act" aria-hidden="true"></span>');
    if (!live && act) act.remove();
    // Where it is: a pane (and which), floating, open behind the one shown, or closed.
    const at = shown.indexOf(k);
    const where = !open ? 'closed' : W.floating.has(k) ? 'float' : at >= 0 ? 'pane' : 'behind';
    b.dataset.where = where;
    b.classList.toggle('is-focus', where === 'pane' && W.focus === k);
    const slot = $('.ck-slot', b);
    const mark = where === 'pane' ? `pane:${lay}:${n}:${at}` : where;
    if (slot.dataset.mark !== mark) {
      slot.dataset.mark = mark;
      slot.innerHTML = where === 'pane' ? slotGlyph(lay, n, at) : where === 'float' ? icon('popout') : '';
    }
    const name = SURFACES[k].label;
    const tip = where === 'pane' ? (n > 1 ? `${name} · pane ${at + 1} of ${n}` : `${name} · open`)
      : where === 'float' ? `${name} · floating. Bring it forward`
        : where === 'behind' ? `${name} · open behind. Show it` : `Open ${name}`;
    b.dataset.tip = live ? `${tip} · working now` : tip;
  });
  $$('.ck-layouts button', ws).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.layout === W.layout)));
  document.documentElement.classList.toggle('ck-ws-off', W.off);
  const anyLive = $$('.ck-surf .act', ws).length > 0;
  $('.act', tab).hidden = !anyLive;
  if (W.width) document.documentElement.style.setProperty('--ck-ws-w', W.width);
  $$('.ck-pane', grid).forEach((p) => p.classList.toggle('is-focus', n > 1 && p.dataset.pane === W.focus && !p.hidden));
  placeIndicator();
}

/** The lit slide under the surface in use: the focused pane's tab. */
function placeIndicator() {
  if (!ws) return;
  const list = $('.ck-surf-list', ws);
  const ind = $('.ck-surf-ind', ws);
  const on = $('.ck-surf.is-focus', ws) || (fittedN === 1 ? $('.ck-surf[data-where="pane"]', ws) : null);
  if (!on || !list.offsetWidth) { ind.style.opacity = '0'; return; }
  ind.style.opacity = '1';
  ind.style.width = on.offsetWidth + 'px';
  ind.style.transform = `translateX(${on.offsetLeft}px)`;
}

/** A small map of the layout with this surface's pane filled in. */
function slotGlyph(lay, n, at) {
  const cells = [];
  const X = 3, Y = 4, Wd = 18, H = 16, g = 1.6;
  if (n <= 1 || lay === 'one') cells.push([X, Y, Wd, H]);
  else if (lay === 'cols') for (let i = 0; i < n; i += 1) { const w = (Wd - g * (n - 1)) / n; cells.push([X + i * (w + g), Y, w, H]); }
  else if (lay === 'main' && n > 2) {
    const top = H * 0.58, bot = H - top - g, w = (Wd - g * (n - 2)) / (n - 1);
    cells.push([X, Y, Wd, top]);
    for (let i = 0; i < n - 1; i += 1) cells.push([X + i * (w + g), Y + top + g, w, bot]);
  } else {
    const weights = lay === 'main' ? [1.4, 1] : Array(n).fill(1);
    const sum = weights.reduce((a, b) => a + b, 0), free = H - g * (n - 1);
    let y = Y;
    for (const wt of weights) { const h = free * wt / sum; cells.push([X, y, Wd, h]); y += h + g; }
  }
  const r = (v) => Math.round(v * 10) / 10;
  return `<svg class="ck-i" viewBox="0 0 24 24" aria-hidden="true">${cells.map(([x, y, w, h], i) =>
    `<rect x="${r(x)}" y="${r(y)}" width="${r(w)}" height="${r(h)}" rx="1.2" class="${i === at ? 'on' : ''}"/>`).join('')}</svg>`;
}

/** A floating window, brought to the top and given the focus. */
function raiseFloating(k) {
  if (k === 'doc') { const p = panes.doc; p.style.zIndex = String((parseInt(getComputedStyle(p).zIndex, 10) || 1000) + 1); p.focus?.(); return; }
  import('./modalManager.js?v=20261009census').then((M) => {
    M.raiseWindow(MODAL_IDS[k]);
    M.focusWindowHandle(MODAL_IDS[k]);
  }).catch(() => {});
  const c = $('.modal-content', SURFACES[k].node());
  if (c && !reduced()) c.animate([{ boxShadow: '0 0 0 2px var(--ck-accent-line)' }, { boxShadow: '0 0 0 0 transparent' }], { duration: 700, easing: EASE });
}

/** The pane of a tab pressed while it is already shown: in view, and lit once. */
function flashPane(k) {
  const p = panes[k];
  if (!p || p.hidden) return;
  p.scrollIntoView?.({ block: 'nearest' });
  if (!reduced()) p.animate([{ boxShadow: '0 0 0 2px var(--ck-accent-line)' }, { boxShadow: '0 0 0 0 transparent' }], { duration: 700, easing: EASE });
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
    // Near the pane, but whole on screen, so its Fill, Close and Save stay in reach.
    const to = at ? { left: at.x, top: at.y, width: w, height: h }
      : { left: Math.max(20, Math.min(from.left - 80, window.innerWidth - w - 20)), top: Math.max(60, Math.min(from.top + 20, window.innerHeight - h - 20)), width: w, height: h };
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
    content.style.position = 'fixed';
    content.style.margin = '0';
    // The window keeps its own size (980×720, 1040×780; read once it is fixed,
    // since inside its overlay it is narrower) unless the viewport is smaller,
    // and lands whole on screen with 20px clear: placed only by the pane, its
    // title bar's Minimize and Close fell past the right edge.
    let to = { left: at?.x, top: at?.y };
    if (!at) {
      const cw = Math.min(content.offsetWidth, window.innerWidth - 40), ch = Math.min(content.offsetHeight, window.innerHeight - 40);
      if (cw < content.offsetWidth) content.style.width = cw + 'px';
      if (ch < content.offsetHeight) content.style.height = ch + 'px';
      to = { left: Math.max(20, Math.min(from.left - 60, window.innerWidth - cw - 20)), top: Math.max(20, Math.min(Math.max(60, from.top + 20), window.innerHeight - ch - 20)) };
    }
    content.style.left = to.left + 'px';
    content.style.top = to.top + 'px';
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
  // `PHW-CTL`. One track: the surfaces as tabs, a lit slide under the one in
  // use, each tab marking where its surface is (which pane, or floating), and
  // the layouts at the end of the same track.
  ws.innerHTML = '<div class="ck-ws-head"><span class="lbl">Workspace</span>'
    + '<div class="ck-switch" role="toolbar" aria-label="Workspace surfaces and layout">'
    + '<div class="ck-surf-list" role="group" aria-label="Surfaces"><span class="ck-surf-ind" aria-hidden="true"></span>'
    + ORDER.map((k) => `<button type="button" class="ck-surf ctl-tip" data-surf="${k}" aria-label="${SURFACES[k].label}" data-tip="${SURFACES[k].label}" aria-pressed="false">${icon(SURFACES[k].icon)}<span class="tx">${SURFACES[k].label}</span><span class="ck-slot" aria-hidden="true"></span></button>`).join('')
    + '</div><span class="ck-switch-rule" aria-hidden="true"></span><div class="ck-layouts" role="group" aria-label="Layout">'
    + LAYOUTS.map(([v, ic, t]) => `<button type="button" class="ctl-tip" data-layout="${v}" aria-pressed="false" data-tip="${t}" aria-label="${t}">${icon(ic)}</button>`).join('')
    + `</div></div><span class="grow"></span><button type="button" class="ck-ibtn ctl-tip" id="ck-ws-tuck" data-tip="Tuck workspace" aria-label="Tuck workspace">${icon('chev')}</button></div>`
    + '<div id="ck-ws-grid"></div>';
  grid = $('#ck-ws-grid', ws);
  ORDER.forEach((k) => { panes[k] = buildPane(k); grid.appendChild(panes[k]); });
  // The shared empty shape (`ui.renderEmptyState`), built without a host so
  // the panes beside it stay where they are.
  empty = renderEmptyState(null, {
    kind: 'empty', className: 'ck-ws-empty', title: 'Nothing open',
    message: 'Open Documents, Workstation, Browser or Mobile Emulator above.',
  });
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
    // A tab never closes its surface (the pane's × does): open brings it
    // forward — the floating window raised, the pane in view and lit.
    if (isOpen(k) && W.floating.has(k)) { raiseFloating(k); return; }
    if (isOpen(k)) { W.focus = k; render(); flashPane(k); return; }
    W.focus = k; pendingFocus = k; W.off = false; openSurface(k);
    setTimeout(render, 60);
  }));
  $('.ck-surf-list', ws).addEventListener('keydown', (e) => {
    // Delete closes the open surface under the focus, as its pane's × would.
    const b = e.target.closest('.ck-surf');
    if (!b || (e.key !== 'Delete' && e.key !== 'Backspace')) return;
    if (!isOpen(b.dataset.surf)) return;
    e.preventDefault();
    closeSurface(b.dataset.surf);
    setTimeout(render, 60);
  });
  $('.ck-switch', ws).addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    const items = $$('.ck-switch button', ws).filter((x) => x.offsetParent !== null);
    const at = items.indexOf(document.activeElement);
    if (at < 0) return;
    e.preventDefault();
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : (at + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
    items[next].focus();
  });
  // The pane a person works in is the one the slide sits under.
  grid.addEventListener('pointerdown', (e) => {
    const pane = e.target.closest && e.target.closest('.ck-pane');
    if (pane && pane.dataset.pane && W.focus !== pane.dataset.pane) { W.focus = pane.dataset.pane; render(); }
  }, true);
  window.addEventListener('resize', () => placeIndicator());
  $$('.ck-layouts button', ws).forEach((b) => b.addEventListener('click', () => { W.layout = b.dataset.layout; W.max = null; save(); render(); }));
  $('#ck-ws-tuck', ws).addEventListener('click', () => toggleWorkspace(true));
  tab.addEventListener('click', () => toggleWorkspace(false));
  document.addEventListener('pantheon:toggle-workspace', () => toggleWorkspace());
  bindResizer();
  watchWindowDrops();
  // The resizer, a window resize or the end of the tuck slide can move the
  // column across MIN_PANE_W: lay the grid out again only when the fit changed.
  const refit = () => { if (fitLayout(W.max ? 'one' : W.layout, fittedN) !== fitted) render(); };
  if (typeof ResizeObserver === 'function') new ResizeObserver(refit).observe(ws);
  ws.addEventListener('transitionend', (e) => { if (e.target === ws) refit(); });

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
