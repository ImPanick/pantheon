// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/workbench.js
//
// `P22-02`. The Workbench window: `#workbench-modal` in `static/index.html`,
// registered with the window system the way every other tool window is
// (`modalManager.js` `_LABELS` and `_AUTO_WIRE`, the `_` button, the dock chip,
// left and right docking through `windowDrag.js`), opened from the last row of
// the sidebar's Tools and its rail twin (`app.js`), and from ⋮ → *Workflow* on
// a task card (`tasks.js`).
//
// **This file is glue and stays thin.** It owns the window — wiring, the room
// switcher, open and close — and nothing that is drawn inside a room. It is the
// one module that imports the task form (`tasks/taskFields.js`, the `P22` panel
// contract) and hands it to the Automations room (`workflowRoom.js`), which
// mounts it as the canvas's `mountPanel` and — in its step and start modes — in
// a workflow's panels (`P22-05`). That is what lets `canvas.js` and the room be
// driven in a test with a stub in its place, and keeps one form for both
// windows and every panel (`Law 7`).
//
// **Rooms (`P22-21`).** `ROOMS` is the switcher, in order: Automations, Skills,
// and MCP & Integrations. Each room has a panel of its own in the window
// (`panel`, an id), and the panels are siblings under `.workbench-body`: a
// switch hides one and shows another, and **a room is not destroyed by a
// switch** — it used to be (`host.replaceChildren()` on every switch, design
// § 0.7), which took an unsaved Automations draft with it. A room with a
// `mount` is mounted the first time it is shown and kept; closing the window
// takes down Automations only (after its `canClose`), as before.
//
//   * Skills mounts `skills.js` — the same module the Skills window runs, not a
//     copy (`D-2026-10-02-02` §2) — into `#skills-room` (`mountSkills`).
//   * MCP & Integrations is Settings' Integrations card, moved here with its
//     ids (`P9-06`'s precedent): its first show asks `settings.js` to draw it
//     (`initUnifiedIntegrations`, idempotent), from the module instance the
//     page already has.
//
// **Loaded on first use.** Both doors `import()` this module when pressed, so a
// page that never opens the Workbench never fetches it, and a browser on a
// branch where `taskFields.js` has not landed yet fails here rather than at
// boot. The Skills and Integrations rooms `import()` their modules when first
// shown, for the same reason.

import { mountTaskFields } from '../tasks/taskFields.js';
import { mountAutomations } from './workflowRoom.js';
import { makeWindowDraggable } from '../windowDrag.js';
import { registerMenuDismiss } from '../escMenuStack.js';
import * as EscStack from '../escMenuStack.js';
import * as Modals from '../modalManager.js?v=20261002slicesce';
// `P22-04`. The step renderer the Tasks card draws a plan with, for the
// canvas's full plan. Spelled exactly as `app.js` imports `tasks.js` — a
// different spelling is a second module instance (`runStatus.js`'s header) —
// so this is the instance already on the page, and the cache-buster moves with
// the other importers.
import { renderRunSteps } from '../tasks.js?v=20261002slicesce';
// `P22-21`. A door that is not the Tasks window's — Settings → Integrations,
// the Brain — opens the Workbench without handing in the schedule words; the
// Tasks module's own (`scheduleLabel`) are used then. A namespace import, so a
// page whose `tasks.js` has no default export still links.
import * as Tasks from '../tasks.js?v=20261002slicesce';

export const WORKBENCH_ID = 'workbench-modal';

/** `P22-21`. The Skills room: the Skills module, mounted into `#skills-room`.
 *  `skills.js` is the page's own instance — the page loads it as
 *  `/static/js/skills.js`, which is what this specifier resolves to. */
function mountSkillsRoom(panel, opts = {}) {
  const host = panel.querySelector('#skills-room') || panel;
  let handle = null;
  const want = { view: opts.view || null, skill: opts.skill || null };
  const ready = import('../skills.js').then((mod) => {
    const mount = mod.mountSkills || (mod.default && mod.default.mountSkills);
    handle = typeof mount === 'function' ? mount(host, want) : null;
    if (!handle) host.textContent = 'The skills did not load. Reload the page and try again.';
    return !!handle;
  }).catch((err) => {
    console.error('The Skills room did not load:', err);
    host.textContent = 'The skills did not load. Reload the page and try again.';
    return false;
  });
  return {
    ready,
    shown() { ready.then(() => handle && handle.shown()); },
    land(o = {}) {
      ready.then(() => {
        if (!handle) return;
        if (o.view) handle.showView(o.view);
        if (o.skill) handle.focusSkill(o.skill);
      });
    },
  };
}

/** `P22-21`. MCP & Integrations: the card moved here with its ids, drawn by
 *  `settings.js` (`initUnifiedIntegrations`, which returns at once after its
 *  first run). Spelled as `app.js` imports `settings.js`, so it is the one
 *  instance on the page and its list is the one Settings drew.
 *
 *  The integration form (`#unified-intg-form`) opens over the list; while it
 *  is open the room holds a layer on the Escape stack (`B1052`'s mechanism,
 *  `data-esc-layer`), so Escape closes the form before the window — the rule
 *  `ui.js` keeps for it inside Settings, which no longer holds it. */
function mountIntegrationsRoom(panel, opts = {}) {
  const form = panel.querySelector('#unified-intg-form');
  let release = null;
  // Open is how `settings.js` opens it — `style.display = ''` over the
  // markup's `display:none` — with something drawn in it.
  const formOpen = () => !!(form && form.style.display !== 'none' && form.children.length > 0);
  const watch = () => {
    if (formOpen() && !release) {
      const unregister = registerMenuDismiss(() => {
        release = null;
        delete panel.dataset.escLayer;
        form.style.display = 'none';
        form.replaceChildren();
      });
      panel.dataset.escLayer = 'open';
      release = () => { unregister(); release = null; delete panel.dataset.escLayer; };
    } else if (!formOpen() && release) {
      release();
    }
  };
  if (form && typeof MutationObserver === 'function') {
    new MutationObserver(watch).observe(form, { attributes: true, attributeFilter: ['style'], childList: true });
  }
  const ready = import('../settings.js?v=20261002slicesce').then((mod) => {
    const s = mod.default || mod;
    if (typeof s.initUnifiedIntegrations === 'function') return s.initUnifiedIntegrations();
    return null;
  }).catch((err) => {
    console.error('MCP & Integrations did not load:', err);
  });
  const handle = {
    ready,
    /** `serverId` opens that MCP server's card — the list's own Manage. */
    land(o = {}) {
      if (o.serverId == null) return;
      ready.then(() => {
        const card = [...panel.querySelectorAll('.intg-card[data-intg-type="mcp"]')]
          .find((n) => String(n.dataset.intgId) === String(o.serverId));
        if (card) { card.scrollIntoView?.({ block: 'nearest' }); card.click(); }
      });
    },
    releaseEscape() { if (release) release(); },
  };
  handle.land(opts);
  return handle;
}

/** The rooms, in the order the switcher shows them. A room is
 *  `{ id, label, panel, mount? }`: `panel` is the id of its element in the
 *  window, and `mount(panelEl, opts) → handle` draws into it the first time it
 *  is shown. A handle may offer `shown()` (shown again), `land(opts)`,
 *  `canClose(onClose)` and `destroy()`. */
export const ROOMS = [
  {
    id: 'automations',
    label: 'Automations',
    panel: 'workbench-room',
    // `P22-05` (wf-ui). The room is the chains canvas and, beside it, the
    // workflows (`workflowRoom.js`); the form and the step renderer are handed
    // in from here, as they were to the canvas.
    mount: (host, opts) => mountAutomations(host, { ...opts, mountTaskFields, renderSteps: renderRunSteps }),
  },
  { id: 'skills', label: 'Skills', panel: 'workbench-room-skills', mount: mountSkillsRoom },
  { id: 'integrations', label: 'MCP & Integrations', panel: 'workbench-room-integrations', mount: mountIntegrationsRoom },
];

let _wired = false;
let _open = false;
let _current = null;       // the id of the room on show
const _handles = new Map(); // room id → handle, for every room mounted and kept
let _describe = null;      // the schedule words, from whoever opened the window
let _hiddenGuard = null;   // releases the Escape guard over a hidden room's layers

function _modal() { return document.getElementById(WORKBENCH_ID); }
function _panel(room) { return document.getElementById(room.panel); }
function _room(id) { return ROOMS.find((r) => r.id === id) || null; }

function _syncTabs() {
  const bar = document.getElementById('workbench-rooms');
  if (!bar) return;
  for (const tab of bar.children) {
    const on = tab.dataset.room === _current;
    tab.classList.toggle('active', on);
    tab.setAttribute('aria-selected', on ? 'true' : 'false');
    tab.tabIndex = on ? 0 : -1;
  }
}

/**
 * `P22-21`. A room that is not on show can still hold layers on the Escape
 * stack — the Automations room's step panel, left open when the person went to
 * Skills. The stack is last-in-first-out and knows nothing of panels, so the
 * next Escape would close that invisible panel, and nothing on screen would
 * move. While a hidden room holds a layer, one guard sits on the stack above
 * it: Escape closes the window (which asks first about unsaved work), and the
 * room on show is marked so the arbiter asks the stack (`B1052`). Coming back
 * to the room takes the guard away, and its own layers are on top again.
 */
/** Whether a room's panel holds an open layer — marked on the panel or on
 *  anything in it, which is how the arbiter in `ui.js` asks the window. */
function _holdsLayer(panel) {
  if (!panel) return false;
  if (panel.dataset && panel.dataset.escLayer && panel.dataset.escLayer !== 'guard') return true;
  return !!(panel.querySelector && panel.querySelector('[data-esc-layer]'));
}

function _guardHiddenLayers() {
  if (_hiddenGuard) { _hiddenGuard(); _hiddenGuard = null; }
  if (!_open) return;
  const held = ROOMS.some((r) => r.id !== _current && _holdsLayer(_panel(r)));
  if (!held) return;
  const shown = _room(_current) && _panel(_room(_current));
  const unregister = registerMenuDismiss(() => {
    _hiddenGuard = null;
    if (shown) delete shown.dataset.wbGuard;
    closeWorkbench();
    if (_open) _guardHiddenLayers();
  });
  if (shown) shown.dataset.wbGuard = 'open';
  if (shown && !shown.dataset.escLayer) shown.dataset.escLayer = 'guard';
  _hiddenGuard = () => {
    unregister();
    if (shown) {
      delete shown.dataset.wbGuard;
      if (shown.dataset.escLayer === 'guard') delete shown.dataset.escLayer;
    }
  };
}

function _showRoom(id, opts = {}) {
  const room = _room(id) || ROOMS[0];
  const panel = _panel(room);
  if (!panel) return null;
  const again = _current === room.id;
  for (const r of ROOMS) {
    const p = _panel(r);
    if (p) p.hidden = r.id !== room.id;
  }
  panel.setAttribute('aria-labelledby', 'workbench-room-tab-' + room.id);
  _current = room.id;
  let handle = _handles.get(room.id) || null;
  if (!_handles.has(room.id) && typeof room.mount === 'function') {
    handle = room.mount(panel, {
      ...opts,
      describeTrigger: (task) => {
        const words = _describe || (Tasks.default && Tasks.default.scheduleLabel);
        return typeof words === 'function' ? words(task) : '';
      },
    }) || {};
    _handles.set(room.id, handle);
  } else if (!again && handle && typeof handle.shown === 'function') {
    handle.shown();
  }
  _syncTabs();
  _guardHiddenLayers();
  return handle;
}

/** The WAI-ARIA tablist keys: Left/Right move to the neighbouring room (and
 *  wrap), Home and End to the first and last; the room follows the focus. */
function _onTabKey(e) {
  const keys = { ArrowLeft: -1, ArrowRight: 1, Home: 'first', End: 'last' };
  if (!(e.key in keys)) return;
  const i = ROOMS.findIndex((r) => r.id === _current);
  const step = keys[e.key];
  const next = step === 'first' ? 0 : step === 'last' ? ROOMS.length - 1
    : (i + step + ROOMS.length) % ROOMS.length;
  e.preventDefault();
  _showRoom(ROOMS[next].id);
  document.getElementById('workbench-room-tab-' + ROOMS[next].id)?.focus();
}

/**
 * `P22-21`. The menus the Skills and Integrations rooms open — a skill's ⋯,
 * *Add Integration*'s list — are drawn on `<body>` and sit on the Escape stack,
 * but `ui.js`'s arbiter closes a registered window under the pointer before it
 * asks the stack, unless the window marks an open layer (`B1052`). Settings was
 * never a registered window, so the Integrations card's menus never met this;
 * moved here, one Escape over an open *Add Integration* menu closed the whole
 * Workbench (measured in the P22-21 drive). So while anything is on the stack,
 * the room on show is marked for the length of that key press — this listener
 * is on `window` in the capture phase, which runs before the arbiter's on
 * `document` — and the stack answers first: the menu, then the window.
 */
function _markForEscape(e) {
  if (!e || e.key !== 'Escape' || !_open) return;
  const count = typeof EscStack._openMenuCount === 'function' ? EscStack._openMenuCount() : 0;
  const room = _room(_current);
  const panel = room && _panel(room);
  if (!panel || !count || panel.dataset.escLayer) return;
  panel.dataset.escLayer = 'menu';
  setTimeout(() => { if (panel.dataset.escLayer === 'menu') delete panel.dataset.escLayer; }, 0);
}

function _wire() {
  if (_wired) return;
  const modal = _modal();
  if (!modal) return;
  _wired = true;
  window.addEventListener('keydown', _markForEscape, true);
  document.getElementById('workbench-close')?.addEventListener('click', closeWorkbench);
  const bar = document.getElementById('workbench-rooms');
  if (bar) {
    bar.replaceChildren(...ROOMS.map((room) => {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'memory-tab workbench-room-tab';
      tab.id = 'workbench-room-tab-' + room.id;
      tab.dataset.room = room.id;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', room.panel);
      tab.textContent = room.label;
      tab.addEventListener('click', () => _showRoom(room.id));
      tab.addEventListener('keydown', _onTabKey);
      return tab;
    }));
  }
  const content = modal.querySelector('.modal-content');
  const header = modal.querySelector('.modal-header');
  if (content && header) {
    makeWindowDraggable(modal, {
      content, header, skipSelector: 'button, input, select, label',
      enableDock: true, enableLeftDock: true,
    });
  }
}

/** Move an open room to what the door asked for. */
function _land(roomId, handle, { focusId, workflowId, runId, view, skill, serverId }) {
  if (!handle) return;
  if (roomId === 'automations') {
    if (workflowId != null && runId != null && typeof handle.openRun === 'function') {
      handle.openRun(workflowId, runId);
    } else if (workflowId != null && typeof handle.openWorkflow === 'function') {
      handle.openWorkflow(workflowId);
    } else if (focusId != null && typeof handle.focusChain === 'function') {
      handle.focusChain(focusId);
    }
  } else if (typeof handle.land === 'function') {
    handle.land({ view, skill, serverId });
  }
}

/**
 * Open the Workbench, or bring it back. Contract C-R (`P22-21`):
 *
 * `room` — 'automations' | 'skills' | 'integrations' — is the room to show;
 * left out, a closed window opens on Automations and an open one stays where
 * it is, unless the door names a workflow, run or task (Automations' own).
 * `view` ('browse' | 'add') and `skill` (a name) land the Skills room;
 * `serverId` opens that MCP server's card in MCP & Integrations.
 *
 * Today's, unchanged: `focusId` opens the Automations room on the workflow that
 * task is part of; `workflowId` (`P22-05`) on that workflow document; `runId`
 * (`P22-17`, wf-canvas) on that workflow's run — a waiting run on the step it
 * waits on (a workflow question's *Open the run*); `describeTrigger(task)` is
 * the schedule wording (`tasks.js:_scheduleLabel`), handed in by the door so
 * the words exist once.
 */
export function openWorkbench({
  room = null, view = null, skill = null, serverId = null,
  focusId = null, workflowId = null, runId = null, describeTrigger = null,
} = {}) {
  if (typeof describeTrigger === 'function') _describe = describeTrigger;
  const modal = _modal();
  if (!modal) return false;
  _wire();
  if (Modals.isMinimized(WORKBENCH_ID)) {
    Modals.restore(WORKBENCH_ID);
  } else {
    modal.classList.remove('hidden');
    modal.style.display = '';
  }
  modal.querySelector('.modal-content')?.classList.remove('modal-closing');
  const asked = { focusId, workflowId, runId, view, skill, serverId };
  const automations = focusId != null || workflowId != null || runId != null;
  const target = (room && _room(room)) ? room
    : automations ? 'automations'
    : (_open && _current) ? _current : ROOMS[0].id;
  if (!_open) {
    _open = true;
    _current = null;
  }
  const fresh = !_handles.has(target);
  const handle = _current === target ? _handles.get(target) : _showRoom(target, asked);
  if (!fresh) _land(target, handle, asked);
  return true;
}

export function closeWorkbench() {
  if (!_open) return;
  // `P22-05` (wf-ui). A room holding unsaved work asks first (*Save / Discard
  // / Keep editing*) and closes the window itself once answered — the close
  // button, Escape's arbiter (which presses it) and the dock all come here.
  // `P22-21`: every mounted room is asked, on show or not, and a room that
  // asks is brought into view so the person can see what they are deciding.
  for (const [id, handle] of _handles) {
    if (handle && typeof handle.canClose === 'function' && !handle.canClose(() => closeWorkbench())) {
      if (_current !== id) _showRoom(id);
      return;
    }
  }
  _open = false;
  if (_hiddenGuard) { _hiddenGuard(); _hiddenGuard = null; }
  // Automations is taken down, as before; the Skills and Integrations rooms
  // are kept — their markup is the page's and nothing in them is half-done.
  const automations = _handles.get('automations');
  if (automations && typeof automations.destroy === 'function') automations.destroy();
  _handles.delete('automations');
  const intg = _handles.get('integrations');
  if (intg && typeof intg.releaseEscape === 'function') intg.releaseEscape();
  _current = null;
  const modal = _modal();
  if (!modal) return;
  const content = modal.querySelector('.modal-content');
  // Opened again before the closing animation ended: leave it open.
  const done = () => {
    if (content) content.classList.remove('modal-closing');
    if (!_open) modal.classList.add('hidden');
  };
  if (!content) { done(); return; }
  content.classList.add('modal-closing');
  content.addEventListener('animationend', done, { once: true });
  setTimeout(() => { if (!modal.classList.contains('hidden')) done(); }, 250);
}

export function isWorkbenchOpen() { return _open; }

/** The room on show, or null when the window is closed. */
export function currentRoom() { return _open ? _current : null; }

export default { openWorkbench, closeWorkbench, isWorkbenchOpen, currentRoom, ROOMS, WORKBENCH_ID };
