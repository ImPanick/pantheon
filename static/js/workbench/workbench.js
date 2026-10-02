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
// **Rooms.** `ROOMS` is the switcher, in order. Automations is the only room
// today; `P22-21` mounts the Skills and MCP modules here as rooms by adding
// entries — nothing is drawn for a room that does not exist yet (`Law 13`).
//
// **Loaded on first use.** Both doors `import()` this module when pressed, so a
// page that never opens the Workbench never fetches it, and a browser on a
// branch where `taskFields.js` has not landed yet fails here rather than at
// boot.

import { mountTaskFields } from '../tasks/taskFields.js';
import { mountAutomations } from './workflowRoom.js';
import { makeWindowDraggable } from '../windowDrag.js';
import * as Modals from '../modalManager.js?v=20261002slicebee';
// `P22-04`. The step renderer the Tasks card draws a plan with, for the
// canvas's full plan. Spelled exactly as `app.js` imports `tasks.js` — a
// different spelling is a second module instance (`runStatus.js`'s header) —
// so this is the instance already on the page, and the cache-buster moves with
// the other importers.
import { renderRunSteps } from '../tasks.js?v=20261002slicebee';

export const WORKBENCH_ID = 'workbench-modal';

/** The rooms, in the order the switcher shows them. A room is
 *  `{ id, label, mount(host, opts) → { focusChain?, destroy } }`. */
export const ROOMS = [
  {
    id: 'automations',
    label: 'Automations',
    // `P22-05` (wf-ui). The room is the chains canvas and, beside it, the
    // workflows (`workflowRoom.js`); the form and the step renderer are handed
    // in from here, as they were to the canvas.
    mount: (host, opts) => mountAutomations(host, { ...opts, mountTaskFields, renderSteps: renderRunSteps }),
  },
];

let _wired = false;
let _open = false;
let _room = null;          // { id, handle }
let _describe = null;      // the schedule words, from whoever opened the window

function _modal() { return document.getElementById(WORKBENCH_ID); }

function _syncTabs() {
  const bar = document.getElementById('workbench-rooms');
  if (!bar) return;
  for (const tab of bar.children) {
    const on = !!_room && tab.dataset.room === _room.id;
    tab.classList.toggle('active', on);
    tab.setAttribute('aria-selected', on ? 'true' : 'false');
    tab.tabIndex = on ? 0 : -1;
  }
}

function _showRoom(id, opts = {}) {
  const room = ROOMS.find((r) => r.id === id) || ROOMS[0];
  if (_room && _room.id === room.id) return _room.handle;
  const host = document.getElementById('workbench-room');
  if (!host) return null;
  if (_room && _room.handle && typeof _room.handle.destroy === 'function') _room.handle.destroy();
  host.replaceChildren();
  host.setAttribute('aria-labelledby', 'workbench-room-tab-' + room.id);
  _room = { id: room.id, handle: null };
  _room.handle = room.mount(host, {
    ...opts,
    describeTrigger: (task) => (_describe ? _describe(task) : ''),
  });
  _syncTabs();
  return _room.handle;
}

function _wire() {
  if (_wired) return;
  const modal = _modal();
  if (!modal) return;
  _wired = true;
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
      tab.setAttribute('aria-controls', 'workbench-room');
      tab.textContent = room.label;
      tab.addEventListener('click', () => _showRoom(room.id));
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

/**
 * Open the Workbench, or bring it back.
 *
 * `focusId` opens the Automations room on the workflow that task is part of;
 * `workflowId` (`P22-05`) opens it on that workflow document;
 * `runId` (`P22-17`, wf-canvas) opens that workflow's run — a waiting run on
 * the step it waits on (a workflow question's *Open the run*);
 * `describeTrigger(task)` is the schedule wording (`tasks.js:_scheduleLabel`),
 * handed in by the door so the words exist once.
 */
export function openWorkbench({ focusId = null, workflowId = null, runId = null, describeTrigger = null } = {}) {
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
  if (!_open) {
    _open = true;
    _room = null;
    _showRoom(ROOMS[0].id, { focusId, workflowId, runId });
  } else if (workflowId != null && runId != null && _room && _room.handle && typeof _room.handle.openRun === 'function') {
    _room.handle.openRun(workflowId, runId);
  } else if (workflowId != null && _room && _room.handle && typeof _room.handle.openWorkflow === 'function') {
    _room.handle.openWorkflow(workflowId);
  } else if (focusId != null && _room && _room.handle && typeof _room.handle.focusChain === 'function') {
    _room.handle.focusChain(focusId);
  }
  return true;
}

export function closeWorkbench() {
  if (!_open) return;
  // `P22-05` (wf-ui). A room holding unsaved work asks first (*Save / Discard
  // / Keep editing*) and closes the window itself once answered — the close
  // button, Escape's arbiter (which presses it) and the dock all come here.
  if (_room && _room.handle && typeof _room.handle.canClose === 'function'
      && !_room.handle.canClose(() => closeWorkbench())) return;
  _open = false;
  if (_room && _room.handle && typeof _room.handle.destroy === 'function') _room.handle.destroy();
  _room = null;
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

export default { openWorkbench, closeWorkbench, isWorkbenchOpen, ROOMS, WORKBENCH_ID };
