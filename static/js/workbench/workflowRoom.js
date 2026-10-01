// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/workflowRoom.js
//
// `P22-05`…`P22-08` (wf-ui). The Workbench's *Automations* room: the tasks and
// chains that run today (`P22-02`'s canvas, unchanged — it is still the room's
// landing view, so its `Verify:` is unchanged) and, on a shelf beside them,
// every workflow — a named, versioned document started by one task
// (`D-2026-10-01-05` §1). Design: `/work/notes/SLICE-B-DESIGN.md` § 6.
//
//   export function mountAutomations(host, { mountTaskFields, describeTrigger, focusId, workflowId })
//     → { ready, focusChain(taskId), openWorkflow(workflowId), canClose(onClose), destroy() }
//
// **One canvas (`Law 14`).** A workflow is drawn by the same `canvas.js` the
// chains are, behind the canvas source contract (C3): the chains through
// `taskSource.js`, a document through `workflowSource.js`, which holds the
// draft and talks to `workflowApi.js` (both wf-api's). This module draws what
// is around the canvas — the shelf, the workflow's toolbar, its runs — and
// hands the source the panels it opens (`workflowPanels.js`).
//
// **The workflow layer is loaded when the room is, not imported with it.**
// `workflowApi.js` and `workflowSource.js` come in through `import()`, so a
// failure to load them leaves the chains canvas — everything a person could do
// before Slice B — working, with the shelf saying the workflows could not be
// loaded (`Law 1`: Slice A may not regress). A test hands the two in instead
// (`loadWorkflowModules`).
//
// **Nothing unsaved is lost by a door (`B1052`, `B1067`'s rule, room-wide).**
// Leaving a workflow with unsaved changes — another workflow, the tasks, *New
// workflow*, a chain made a workflow, closing the window — asks *Save /
// Discard / Keep editing* first; Escape is *Keep editing*.
//
// **Every word that came from a person is text**: names, notes, sentences and
// run records reach the page through `textContent` and attribute values.

import { mountCanvas } from './canvas.js';
import { createWorkflowPanels } from './workflowPanels.js';
import { runStatusTone, runStatusLabel } from '../runStatus.js';
import { registerMenuDismiss } from '../escMenuStack.js';

const OUTCOME_MARKS = { ok: '✓', error: '✗', pending: '…', info: '·', none: '○' };
/** The shelf's first entry: the canvas `P22-02` shipped. */
const TASKS_KEY = 'tasks';
/** How many runs the Runs tab lists. */
const RUNS_SHOWN = 30;
/** Said when a workflow is off — the design's words (§ 6.2). */
export const OFF_WORDS = 'Switched off — it will not run until you switch it on.';
export const ON_WORDS = 'On — it runs whenever what starts it happens.';

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _button(cls, text, title) {
  const b = _el('button', cls, text);
  b.type = 'button';
  if (title) b.title = title;
  return b;
}

/** The words of a refusal a door threw (`WorkflowRefusal`) or answered. */
function _sentence(err, fallback) {
  return String((err && (err.sentence || err.message)) || fallback || '').trim();
}

function _firstLine(text) {
  const t = String(text || '').trim();
  const line = t.split('\n').find((l) => l.trim()) || '';
  return line.length > 200 ? line.slice(0, 199) + '…' : line;
}

function _when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
}

/** A run or a last run, as a mark, a word and a tone. */
export function runWords(run) {
  if (!run || !run.status) return { tone: 'none', mark: OUTCOME_MARKS.none, word: 'Not run yet' };
  const tone = runStatusTone(run.status) || 'info';
  return { tone, mark: OUTCOME_MARKS[tone] || OUTCOME_MARKS.info, word: runStatusLabel(run.status, 'job') || String(run.status) };
}

/** Whether a run row is a dry run: the row says so (`dry`), or — on a list
 *  that does not carry the flag — its steps are a plan (`kind: "dry-run"`, a
 *  stored step kind, not words). */
export function isDryRun(run) {
  if (!run) return false;
  if (typeof run.dry === 'boolean') return run.dry;
  return run.status === 'skipped' && Array.isArray(run.steps) && run.steps.some((s) => s && s.kind === 'dry-run');
}

/** A workflow summary's switch: its trigger task's status (design § 0.9 — the
 *  task's `status` IS the on/off switch, there is no second one). */
export function isOn(doc) {
  const status = doc && (doc.trigger_status || (doc.trigger_task && doc.trigger_task.status));
  return status === 'active';
}

export function mountAutomations(host, opts = {}) {
  const mountTaskFields = typeof opts.mountTaskFields === 'function' ? opts.mountTaskFields : null;
  const renderSteps = typeof opts.renderSteps === 'function' ? opts.renderSteps : null;
  const describe = typeof opts.describeTrigger === 'function' ? opts.describeTrigger : () => '';
  const loadModules = typeof opts.loadWorkflowModules === 'function'
    ? opts.loadWorkflowModules
    : () => Promise.all([import('./workflowApi.js'), import('./workflowSource.js')])
      .then(([a, s]) => ({ ...a, ...s }));

  const R = {
    view: null, destroyed: false,
    mods: null, api: null, modsError: '',
    workflows: [], listed: false,
    tasksCanvas: null,
    wf: null,            // { id, source, canvas, tab, runs, runSource, runCanvas, runId, failFocus }
    asking: null, versions: null, newForm: null,
  };

  // ── the skeleton ─────────────────────────────────────────────────────────
  // `wb-room` stays on the room's host: it is the Workbench's room, whichever
  // view is in it (the canvas marks its own root the same way).
  host.classList.add('wf-room', 'wb-room');

  const shelf = _el('nav', 'wf-shelf');
  shelf.setAttribute('aria-label', 'Automations');
  const shelfHead = _el('p', 'wf-shelf-head', 'Automations');
  const shelfList = _el('ul', 'wf-shelf-list');
  const newWfBtn = _button('wf-shelf-new', 'New workflow',
    'A workflow is one named set of steps with one start. It is made switched off.');
  const newForm = _el('div', 'wf-new');
  newForm.setAttribute('role', 'group');
  newForm.setAttribute('aria-label', 'New workflow');
  newForm.hidden = true;
  const newLabel = _el('label', 'wf-new-field');
  newLabel.appendChild(_el('span', 'wf-new-label', 'Name'));
  const newName = _el('input', 'wf-new-name');
  newName.type = 'text';
  newName.placeholder = 'e.g. Morning inbox summary';
  newName.maxLength = 120;
  newLabel.appendChild(newName);
  const newGo = _button('wf-new-go', 'Make it');
  const newCancel = _button('wf-new-cancel', 'Cancel');
  const newRow = _el('div', 'wf-new-buttons');
  newRow.appendChild(newGo);
  newRow.appendChild(newCancel);
  newForm.appendChild(newLabel);
  newForm.appendChild(newRow);
  const shelfNote = _el('p', 'wf-shelf-note');
  shelfNote.setAttribute('role', 'status');
  // At phone width the shelf is one row at the top — this select and *New
  // workflow* — so the canvas keeps its height (`B1051`'s lesson).
  const pickLabel = _el('label', 'wf-shelf-pick');
  pickLabel.appendChild(_el('span', 'wf-shelf-pick-word', 'Showing'));
  const pick = _el('select', 'wf-shelf-select');
  pickLabel.appendChild(pick);
  for (const n of [shelfHead, pickLabel, shelfList, newWfBtn, newForm, shelfNote]) shelf.appendChild(n);

  const main = _el('div', 'wf-main');
  const ask = _el('div', 'wf-ask');
  ask.setAttribute('role', 'alertdialog');
  ask.hidden = true;
  const sayLine = _el('div', 'wf-say');
  const sayText = _el('span', 'wf-say-text');
  sayText.setAttribute('role', 'status');
  sayText.setAttribute('aria-live', 'polite');
  const sayAction = _button('wf-say-action', '');
  sayAction.hidden = true;
  sayLine.appendChild(sayText);
  sayLine.appendChild(sayAction);
  sayLine.hidden = true;
  const tasksHost = _el('div', 'wf-tasks');
  const view = _el('div', 'wf-view');
  view.hidden = true;
  for (const n of [ask, sayLine, tasksHost, view]) main.appendChild(n);
  host.appendChild(shelf);
  host.appendChild(main);

  // The workflow's toolbar (§ 6.2).
  const bar = _el('div', 'wf-bar');
  const nameInput = _el('input', 'wf-name');
  nameInput.type = 'text';
  nameInput.maxLength = 120;
  nameInput.setAttribute('aria-label', 'Workflow name');
  const saveBtn = _button('wf-save', 'Save', 'Keep these steps as a new version of the workflow');
  const dirtyWord = _el('span', 'wf-dirty');
  dirtyWord.setAttribute('aria-live', 'polite');
  const versionsBtn = _button('wf-versions', 'Versions…', 'Every saved version of this workflow; look at one or put it back');
  const switchBtn = _button('wf-switch', 'Off');
  switchBtn.setAttribute('role', 'switch');
  switchBtn.setAttribute('aria-checked', 'false');
  const switchWord = _el('span', 'wf-switch-word', OFF_WORDS);
  const chainBtn = _button('wf-chain-back', 'Put the old chain back',
    'Resume the chain this workflow was made from, and switch this workflow off. Nothing is deleted.');
  chainBtn.hidden = true;
  const runBtn = _button('wf-run-now', 'Run now', 'Run the saved workflow once, now');
  const dryBtn = _button('wf-dry', 'Show me what this would do',
    'Plans a run of the saved workflow and shows the plan on the canvas. Nothing runs and nothing changes.');
  const tabs = _el('div', 'wf-tabs');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Workflow');
  const editTab = _button('wf-tab', 'Edit');
  const runsTab = _button('wf-tab', 'Runs');
  for (const [t, key] of [[editTab, 'edit'], [runsTab, 'runs']]) {
    t.setAttribute('role', 'tab');
    t.dataset.tab = key;
    tabs.appendChild(t);
  }
  const nameGroup = _el('span', 'wf-bar-group');
  nameGroup.appendChild(nameInput);
  nameGroup.appendChild(saveBtn);
  nameGroup.appendChild(dirtyWord);
  const switchGroup = _el('span', 'wf-bar-group');
  switchGroup.appendChild(switchBtn);
  switchGroup.appendChild(switchWord);
  switchGroup.appendChild(chainBtn);
  const runGroup = _el('span', 'wf-bar-group');
  for (const n of [versionsBtn, runBtn, dryBtn]) runGroup.appendChild(n);
  for (const n of [nameGroup, switchGroup, runGroup, tabs]) bar.appendChild(n);

  const viewing = _el('div', 'wf-viewing');
  viewing.setAttribute('role', 'status');
  viewing.hidden = true;
  const viewingText = _el('span', 'wf-viewing-text');
  const viewingBack = _button('wf-viewing-restore', 'Put this version back');
  const viewingCurrent = _button('wf-viewing-current', 'Back to the current one');
  for (const n of [viewingText, viewingBack, viewingCurrent]) viewing.appendChild(n);

  const editHost = _el('div', 'wf-edit');
  editHost.id = 'wf-edit-panel';
  editHost.setAttribute('role', 'tabpanel');
  const runsView = _el('div', 'wf-runs');
  runsView.id = 'wf-runs-panel';
  runsView.setAttribute('role', 'tabpanel');
  runsView.hidden = true;
  const runList = _el('ul', 'wf-run-list');
  runList.setAttribute('aria-label', 'Runs, newest first');
  const runHost = _el('div', 'wf-run-canvas');
  runsView.appendChild(runList);
  runsView.appendChild(runHost);
  editTab.setAttribute('aria-controls', editHost.id);
  runsTab.setAttribute('aria-controls', runsView.id);
  for (const n of [bar, viewing, editHost, runsView]) view.appendChild(n);

  // ── Escape: the room's own layers ────────────────────────────────────────
  // The question, Versions…, the palette and *New workflow* are layers on
  // `escMenuStack.js`, and the room carries `data-esc-layer` while one is open
  // — `ui.js`'s arbiter then asks the stack before it closes the window
  // (`B1052`'s mechanism; the canvas marks its own root the same way).
  let held = 0;
  function holdEscape(dismiss) {
    let released = false;
    let unregister = () => {};
    const release = () => {
      if (released) return;
      released = true;
      unregister();
      held = Math.max(0, held - 1);
      if (!held) delete host.dataset.escLayer;
    };
    unregister = registerMenuDismiss(() => { release(); dismiss(); });
    held += 1;
    host.dataset.escLayer = 'open';
    return release;
  }

  // ── one sentence at a time ───────────────────────────────────────────────
  // What the room says goes on the line the person is reading — the canvas's
  // own sentence while a canvas is up, so there is one status line, not two.
  function activeCanvas() {
    if (R.view === 'tasks') return R.tasksCanvas;
    if (R.view === 'workflow' && R.wf) return R.wf.tab === 'runs' ? R.wf.runCanvas : R.wf.canvas;
    return null;
  }
  let sayRun = null;
  function say(text, o = {}) {
    const c = activeCanvas();
    if (c && typeof c.say === 'function') {
      sayLine.hidden = true;
      c.say(text, o);
      return;
    }
    sayText.textContent = text || '';
    sayLine.hidden = !text;
    sayLine.classList.toggle('wf-say-refusal', !!o.refusal);
    sayRun = o.action ? o.action.run : null;
    sayAction.textContent = o.action ? o.action.label : '';
    sayAction.hidden = !o.action;
  }
  sayAction.addEventListener('click', () => { if (sayRun) sayRun(); });

  // ── the workflow layer ───────────────────────────────────────────────────
  let modsPromise = null;
  function ensureMods() {
    if (!modsPromise) {
      modsPromise = Promise.resolve().then(() => loadModules()).then((m) => {
        R.mods = m || {};
        if (typeof R.mods.createWorkflowApi !== 'function' || typeof R.mods.createWorkflowSource !== 'function') {
          throw new Error('the workflow modules did not load');
        }
        R.api = R.mods.createWorkflowApi(typeof opts.fetch === 'function' ? { fetch: opts.fetch } : {});
        return R.mods;
      }).catch((err) => {
        R.modsError = _sentence(err, 'the workflow modules did not load');
        R.mods = null;
        R.api = null;
        return null;
      });
    }
    return modsPromise;
  }

  const panels = createWorkflowPanels({
    mountTaskFields, renderSteps, holdEscape,
    layer: () => host,
    onRecordShown: (info) => recordShown(info),
    // A pin is saved at once and makes no version; the step's "Sample pinned"
    // mark is the canvas's, so it is redrawn (the open panel stays open).
    onChanged: () => { if (R.wf && R.wf.canvas) R.wf.canvas.reload(); },
  });

  function stateOf(source) {
    if (!source || typeof source.state !== 'function') return {};
    try { return source.state() || {}; } catch (_) { return {}; }
  }
  function docOf(source) {
    const st = stateOf(source);
    return st.workflow || st.doc || {};
  }
  function wfName(source) {
    const st = stateOf(source);
    return String((st.name != null ? st.name : docOf(source).name) || 'This workflow');
  }
  function docDirty() {
    return !!(R.view === 'workflow' && R.wf && R.wf.source && stateOf(R.wf.source).dirty);
  }
  /** The version being looked at, or null. C3 leaves its shape open: a
   *  number, or `{ version, … }` (what `workflowSource.js` keeps). */
  function viewingOf(source) {
    const v = stateOf(source).viewing;
    if (v == null) return null;
    return typeof v === 'object' ? (v.version != null ? v.version : null) : v;
  }
  /** Why a source could not be read, or ''. A source may reject `ready`, or
   *  settle it and keep the refusal (`state().loadError`); both are a refusal. */
  function loadErrorOf(source) {
    const e = stateOf(source).loadError;
    return e ? String(e.sentence || e) : '';
  }
  /** A source's answer that is a refusal: C3's sources answer `{ ok: false,
   *  sentence }` where a door throws (`WorkflowRefusal`); both are read. */
  const refused = (err, reply) => !!(err || (reply && reply.ok === false));

  // ── the shelf ────────────────────────────────────────────────────────────
  function selectedKey() {
    return R.view === 'workflow' && R.wf ? String(R.wf.id) : TASKS_KEY;
  }

  function drawShelf() {
    const key = selectedKey();
    const items = [];
    const tasksBtn = _button('wf-shelf-item wf-shelf-tasks', null);
    tasksBtn.dataset.key = TASKS_KEY;
    tasksBtn.appendChild(_el('span', 'wf-shelf-name', 'Tasks and chains'));
    tasksBtn.appendChild(_el('span', 'wf-shelf-sub', 'Every task, and the arrows between them'));
    tasksBtn.addEventListener('click', () => openTasks());
    items.push(tasksBtn);
    for (const w of R.workflows) {
      const b = _button('wf-shelf-item', null);
      b.dataset.key = String(w.id);
      const on = isOn(w);
      const last = runWords(w.last_run && !w.last_run.dry ? w.last_run : null);
      b.appendChild(_el('span', 'wf-shelf-name', String(w.name || 'Untitled workflow')));
      const sub = _el('span', 'wf-shelf-sub');
      const state = _el('span', 'wf-shelf-state', on ? 'On' : 'Off');
      state.dataset.on = on ? 'true' : 'false';
      sub.appendChild(state);
      const mark = _el('span', 'wf-shelf-mark', last.mark);
      mark.setAttribute('aria-hidden', 'true');
      mark.dataset.tone = last.tone;
      sub.appendChild(mark);
      sub.appendChild(_el('span', 'wf-shelf-last', last.tone === 'none' ? last.word : `Last run: ${last.word}`));
      b.appendChild(sub);
      b.setAttribute('aria-label', `${String(w.name || 'Untitled workflow')}. ${on ? 'On' : 'Off'}. `
        + (last.tone === 'none' ? last.word : `Last run: ${last.word}`) + '.');
      b.addEventListener('click', () => openWorkflow(w.id));
      items.push(b);
    }
    shelfList.replaceChildren(...items.map((b) => {
      const li = _el('li', 'wf-shelf-row');
      const on = b.dataset.key === key;
      // Drawn fresh each time, so only the selected entry needs the mark.
      if (on) b.setAttribute('aria-current', 'true');
      b.classList.toggle('wf-shelf-selected', on);
      li.appendChild(b);
      return li;
    }));
    // The phone's select: the same entries.
    const opt = (value, text) => { const o = _el('option', null, text); o.value = value; return o; };
    pick.replaceChildren(opt(TASKS_KEY, 'Tasks and chains'),
      ...R.workflows.map((w) => opt(String(w.id), `${String(w.name || 'Untitled workflow')} (${isOn(w) ? 'On' : 'Off'})`)));
    pick.value = key;
  }

  // The arrow keys go along the shelf; Tab leaves it.
  shelfList.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const btns = [...shelfList.querySelectorAll('button')];
    const i = btns.indexOf(e.target);
    if (i < 0) return;
    e.preventDefault();
    const j = Math.max(0, Math.min(btns.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)));
    btns[j].focus();
  });
  pick.addEventListener('change', () => {
    const value = pick.value;
    pick.value = selectedKey();           // until the door says yes
    if (value === TASKS_KEY) openTasks(); else openWorkflow(value);
  });

  async function refreshShelf() {
    const mods = await ensureMods();
    if (R.destroyed) return false;
    if (!mods) {
      shelfNote.textContent = `Your workflows could not be loaded (${R.modsError.replace(/\.$/, '')}). The tasks and chains still work.`;
      newWfBtn.disabled = true;
      drawShelf();
      return false;
    }
    let reply;
    try {
      reply = await R.api.listWorkflows();
    } catch (err) {
      if (R.destroyed) return false;
      shelfNote.textContent = `Your workflows could not be loaded: ${_sentence(err, 'no answer').replace(/\.$/, '')}.`;
      drawShelf();
      return false;
    }
    if (R.destroyed) return false;
    R.workflows = Array.isArray(reply && reply.workflows) ? reply.workflows : [];
    R.listed = true;
    newWfBtn.disabled = false;
    shelfNote.textContent = R.workflows.length ? '' : 'No workflows yet. A workflow is a named set of steps with one start.';
    drawShelf();
    return true;
  }

  // ── leaving with unsaved changes ─────────────────────────────────────────
  /** What would be lost by leaving now, or null. */
  function unsaved() {
    if (R.view === 'workflow' && R.wf) {
      const stepEdits = !!(R.wf.canvas && typeof R.wf.canvas.isDirty === 'function' && R.wf.canvas.isDirty());
      if (docDirty() || stepEdits) return { name: wfName(R.wf.source), canSave: true, stepEdits };
    }
    if (R.view === 'tasks' && R.tasksCanvas && typeof R.tasksCanvas.isDirty === 'function' && R.tasksCanvas.isDirty()) {
      return { name: 'The open step', canSave: false, stepEdits: true };
    }
    return null;
  }

  function closeAsk() {
    const a = R.asking;
    if (!a) return;
    R.asking = null;
    a.release();
    ask.hidden = true;
    ask.replaceChildren();
  }

  /** Run `cont` now if nothing is unsaved; otherwise ask Save / Discard /
   *  Keep editing first, and run it after Save (if the save worked) or
   *  Discard. True when `cont` ran now. */
  function guardLeave(cont) {
    const u = unsaved();
    if (!u) { cont(); return true; }
    closeAsk();
    const text = u.canSave
      ? `“${u.name}” has changes that are not saved.`
      : `${u.name} has changes that are not saved.`;
    ask.setAttribute('aria-label', text);
    ask.appendChild(_el('p', 'wf-ask-text', text + (u.canSave && u.stepEdits
      ? ' The open step’s own changes are only kept if you press Done in it first.' : '')));
    const row = _el('div', 'wf-ask-buttons');
    const saveIt = _button('wf-ask-save', 'Save');
    const drop = _button('wf-ask-discard', 'Discard');
    const keep = _button('wf-ask-keep', 'Keep editing');
    if (u.canSave) row.appendChild(saveIt);
    row.appendChild(drop);
    row.appendChild(keep);
    ask.appendChild(row);
    ask.hidden = false;
    const keepEditing = () => { closeAsk(); say('Kept. Nothing was saved or dropped.'); };
    // Escape is *Keep editing*. (The stack has already released this layer
    // when it calls back; `closeAsk` releasing it again does nothing.)
    R.asking = { release: holdEscape(() => keepEditing()) };
    saveIt.addEventListener('click', async () => {
      saveIt.disabled = true;
      const ok = await save({ withoutStepEdits: true });
      if (R.destroyed) return;
      saveIt.disabled = false;
      if (ok) { closeAsk(); cont(); }
    });
    drop.addEventListener('click', async () => {
      closeAsk();
      if (u.canSave && R.wf && R.wf.source && typeof R.wf.source.discard === 'function') {
        try { await R.wf.source.discard(); } catch (_) { /* leaving it anyway */ }
      }
      cont();
    });
    keep.addEventListener('click', keepEditing);
    (u.canSave ? saveIt : keep).focus();
    return false;
  }

  // ── the tasks and chains ─────────────────────────────────────────────────
  function mountTasks(focusId) {
    if (R.tasksCanvas) return R.tasksCanvas;
    tasksHost.replaceChildren();
    R.tasksCanvas = mountCanvas(tasksHost, {
      mountPanel: mountTaskFields,
      renderSteps,
      describeTrigger: describe,
      focusId,
      fetch: typeof opts.fetch === 'function' ? opts.fetch : undefined,
      // § 6.1: a step that is a workflow's start opens its document.
      openWorkflow: (workflowId, task) => openWorkflowOfTask(workflowId, task),
      // `P22-06`: *Make this chain a workflow*, offered on a chained step.
      onMakeWorkflow: (headId) => makeFromChain(headId),
    });
    return R.tasksCanvas;
  }

  function showTasks(focusId = null) {
    teardownWorkflow();
    R.view = 'tasks';
    view.hidden = true;
    tasksHost.hidden = false;
    sayLine.hidden = true;
    const had = !!R.tasksCanvas;
    const c = mountTasks(focusId);
    if (had && focusId != null) c.focusChain(focusId);
    drawShelf();
    return c;
  }

  function openTasks(focusId = null) {
    if (R.view === 'tasks') {
      if (focusId != null && R.tasksCanvas) R.tasksCanvas.focusChain(focusId);
      return true;
    }
    return guardLeave(() => { showTasks(focusId); });
  }

  // ── a workflow ───────────────────────────────────────────────────────────
  function teardownRun() {
    const w = R.wf;
    if (!w) return;
    if (w.runCanvas) { try { w.runCanvas.destroy(); } catch (_) { /* gone */ } }
    if (w.runSource && typeof w.runSource.destroy === 'function') { try { w.runSource.destroy(); } catch (_) { /* gone */ } }
    w.runCanvas = null;
    w.runSource = null;
    w.runId = null;
    runHost.replaceChildren();
  }

  function teardownWorkflow() {
    const w = R.wf;
    closeVersions();
    closeAsk();
    if (!w) return;
    teardownRun();
    if (w.canvas) { try { w.canvas.destroy(); } catch (_) { /* gone */ } }
    if (w.source && typeof w.source.destroy === 'function') { try { w.source.destroy(); } catch (_) { /* gone */ } }
    R.wf = null;
    editHost.replaceChildren();
    runList.replaceChildren();
  }

  function leaveTasksView() {
    if (R.tasksCanvas) { try { R.tasksCanvas.destroy(); } catch (_) { /* gone */ } }
    R.tasksCanvas = null;
    tasksHost.replaceChildren();
    tasksHost.hidden = true;
  }

  /** Open workflow `id` (no question asked — callers ask through
   *  `guardLeave`). `notes` are the server's own sentences to say once it is
   *  drawn (what was made, what was paused). */
  async function showWorkflow(id, { notes = null, focusName = false } = {}) {
    const mods = await ensureMods();
    if (R.destroyed) return false;
    if (!mods) {
      say(`Workflows could not be loaded (${R.modsError.replace(/\.$/, '')}).`, { refusal: true });
      return false;
    }
    teardownWorkflow();
    leaveTasksView();
    R.view = 'workflow';
    view.hidden = false;
    sayLine.hidden = true;
    const w = { id: String(id), source: null, canvas: null, tab: 'edit', runs: null, runSource: null,
      runCanvas: null, runId: null, failFocus: null };
    R.wf = w;
    drawShelf();
    setTab('edit', { quiet: true });
    let source;
    try {
      source = mods.createWorkflowSource({
        api: R.api, workflowId: w.id, mode: 'edit', describeTrigger: describe, panels,
        onState: () => { if (R.wf === w) syncBar(); },
      });
      w.source = source;
      await source.ready;
      const why = loadErrorOf(source);
      if (why) throw new Error(why);
    } catch (err) {
      if (R.destroyed || R.wf !== w) return false;
      const sentence = _sentence(err, 'it could not be read');
      teardownWorkflow();
      showTasks();
      say(`That workflow could not be opened: ${sentence.replace(/\.$/, '')}.`, { refusal: true });
      return false;
    }
    if (R.destroyed || R.wf !== w) return false;
    w.canvas = mountCanvas(editHost, { source, renderSteps });
    syncBar();
    await w.canvas.ready;
    if (R.destroyed || R.wf !== w) return false;
    const words = (Array.isArray(notes) ? notes : []).map(String).filter(Boolean).join(' ');
    if (words) say(words);
    if (focusName) { nameInput.focus(); if (typeof nameInput.select === 'function') nameInput.select(); }
    return true;
  }

  function openWorkflow(id) {
    if (id == null) return false;
    if (R.view === 'workflow' && R.wf && R.wf.id === String(id)) return true;
    return guardLeave(() => { showWorkflow(id); });
  }

  /** A workflow's start, clicked on the tasks canvas. The row carries its
   *  document's id (`workflow_id`, an added key on `GET /api/tasks`); a server
   *  without it is answered from the shelf's list. */
  function openWorkflowOfTask(workflowId, task) {
    let id = workflowId;
    if (id == null && task) {
      const w = R.workflows.find((x) => String(x.task_id) === String(task.id));
      id = w ? w.id : null;
    }
    if (id == null) {
      say('That task starts a workflow, and its document could not be found. Open it from the list on the left.', { refusal: true });
      return;
    }
    openWorkflow(id);
  }

  // ── the toolbar ──────────────────────────────────────────────────────────
  let justSaved = false;
  function syncBar() {
    const w = R.wf;
    if (!w || !w.source) return;
    const st = stateOf(w.source);
    const doc = docOf(w.source);
    const name = String((st.name != null ? st.name : doc.name) || '');
    if (document.activeElement !== nameInput && nameInput.value !== name) nameInput.value = name;
    const dirty = !!st.dirty;
    if (dirty) justSaved = false;
    dirtyWord.textContent = dirty ? 'Unsaved changes' : (justSaved ? 'Saved' : '');
    dirtyWord.dataset.dirty = dirty ? 'true' : 'false';
    const on = isOn(doc);
    switchBtn.textContent = on ? 'On' : 'Off';
    switchBtn.setAttribute('aria-checked', on ? 'true' : 'false');
    switchBtn.setAttribute('aria-label', `${name || 'This workflow'} is ${on ? 'on' : 'off'}`);
    switchBtn.title = on ? 'Switch it off' : 'Switch it on';
    switchWord.textContent = on ? ON_WORDS : OFF_WORDS;
    const from = doc.converted_from;
    chainBtn.hidden = !(from && from.head_status === 'paused');
    const v = viewingOf(w.source);
    viewing.hidden = v == null;
    if (v != null) {
      viewingText.textContent = `You are looking at version ${v}. It cannot be changed here.`;
    }
    for (const b of [saveBtn, switchBtn, runBtn, dryBtn]) b.disabled = v != null;
    nameInput.readOnly = v != null;
  }

  nameInput.addEventListener('input', () => {
    const w = R.wf;
    if (w && w.source && typeof w.source.rename === 'function') w.source.rename(nameInput.value);
  });
  nameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
  });

  let saving = false;
  /** Save the workflow. A step whose form has edits not yet applied (`Done`)
   *  is said first, and a second Save is the yes — the canvas's own rule. */
  async function save({ withoutStepEdits = false } = {}) {
    const w = R.wf;
    if (!w || !w.source || saving) return false;
    if (!withoutStepEdits && w.canvas && w.canvas.isDirty() && !w.askedSave) {
      w.askedSave = true;
      say('The open step has changes you have not applied. Press Done in it first, or Save again to save without them.',
        { action: { label: 'Save without them', run: () => save({ withoutStepEdits: true }) } });
      return false;
    }
    w.askedSave = false;
    saving = true;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    let reply = null;
    let err = null;
    try { reply = await w.source.save(); } catch (e) { err = e; }
    saving = false;
    if (R.destroyed || R.wf !== w) return false;
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save';
    if (refused(err, reply)) {
      const why = err || reply;
      const sentence = _sentence(why, 'the workflow was not saved');
      const stale = why.status === 409 || why.stale === true;
      // The steps the server's refusal names: the first is shown.
      const nodeIds = Array.isArray(why.nodeIds) ? why.nodeIds.map(String) : [];
      if (nodeIds.length && w.canvas) w.canvas.focusChain(nodeIds[0]);
      say(`Not saved: ${sentence}`, {
        refusal: true,
        action: stale ? { label: 'Open it again', run: () => reopenSaved() } : null,
      });
      syncBar();
      return false;
    }
    justSaved = true;
    const doc = (reply && reply.workflow) || docOf(w.source);
    const unchanged = reply && reply.saved === 'unchanged';
    say(unchanged
      ? 'Nothing had changed since the last save, so no new version was made.'
      : `Saved${doc && doc.version != null ? ` as version ${doc.version}` : ''}.`
        + (isOn(doc) ? '' : ' It is switched off, so it will not run until you switch it on.'));
    syncBar();
    refreshShelf();
    return true;
  }

  /** After a stale save: drop the draft and draw what is saved now. */
  async function reopenSaved() {
    const w = R.wf;
    if (!w) return;
    try { if (typeof w.source.discard === 'function') await w.source.discard(); } catch (_) { /* reopened below */ }
    await showWorkflow(w.id, { notes: ['This is the workflow as it is saved now. Your changes were not kept.'] });
  }

  async function toggleSwitch() {
    const w = R.wf;
    if (!w || !w.source) return;
    const on = !isOn(docOf(w.source));
    switchBtn.disabled = true;
    let reply = null;
    let err = null;
    try { reply = await w.source.switchOn(on); } catch (e) { err = e; }
    if (R.destroyed || R.wf !== w) return;
    switchBtn.disabled = false;
    if (err || (reply && reply.ok === false)) {
      say(`Not switched ${on ? 'on' : 'off'}: ${_sentence(err || reply, 'the server refused')}`, { refusal: true });
      syncBar();
      return;
    }
    const notes = (Array.isArray(reply && reply.notes) ? reply.notes : []).map(String).filter(Boolean);
    let words = notes.join(' ') || (on ? 'Switched on.' : OFF_WORDS);
    if (on && stateOf(w.source).dirty) words += ' It runs the saved version; your unsaved changes are not in it.';
    // The route's `chain_paused`, or the same as a source names it.
    const paused = on && reply && (reply.chain_paused || reply.chainPaused);
    say(words, { action: paused ? { label: 'Put the old chain back', run: () => restoreChain() } : null });
    syncBar();
    refreshShelf();
  }

  async function restoreChain() {
    const w = R.wf;
    if (!w || !w.source || typeof w.source.restoreChain !== 'function') return;
    chainBtn.disabled = true;
    let reply = null;
    let err = null;
    try { reply = await w.source.restoreChain(); } catch (e) { err = e; }
    if (R.destroyed || R.wf !== w) return;
    chainBtn.disabled = false;
    if (err || (reply && reply.ok === false)) {
      say(`The chain was not put back: ${_sentence(err || reply, 'the server refused')}`, { refusal: true });
      return;
    }
    const notes = (Array.isArray(reply && reply.notes) ? reply.notes : []).map(String).filter(Boolean);
    say(notes.join(' ') || 'The chain runs again and this workflow is switched off. Nothing was deleted.');
    syncBar();
    refreshShelf();
  }

  async function runNow() {
    const w = R.wf;
    if (!w || !w.source) return;
    runBtn.disabled = true;
    let reply = null;
    let err = null;
    try { reply = await w.source.runNow(); } catch (e) { err = e; }
    if (R.destroyed || R.wf !== w) return;
    runBtn.disabled = false;
    if (err || (reply && reply.ok === false)) {
      say(`Not started: ${_sentence(err || reply, 'the server refused')}`, { refusal: true });
      return;
    }
    say('Started. Its run will be listed under Runs.'
      + (stateOf(w.source).dirty ? ' It runs the saved version; your unsaved changes are not in it.' : ''),
    { action: { label: 'Show the runs', run: () => setTab('runs') } });
    if (w.tab === 'runs') loadRuns();
  }

  function dryRun() {
    const w = R.wf;
    if (!w || !w.canvas) return;
    if (w.tab !== 'edit') setTab('edit', { quiet: true });
    w.canvas.dryRun(null, { title: wfName(w.source) });
  }

  saveBtn.addEventListener('click', () => save());
  switchBtn.addEventListener('click', () => toggleSwitch());
  chainBtn.addEventListener('click', () => restoreChain());
  runBtn.addEventListener('click', () => runNow());
  dryBtn.addEventListener('click', () => dryRun());
  versionsBtn.addEventListener('click', () => openVersions());

  // ── Versions… ────────────────────────────────────────────────────────────
  function closeVersions(restoreFocus) {
    const v = R.versions;
    if (!v) return;
    R.versions = null;
    v.release();
    v.box.remove();
    if (restoreFocus) versionsBtn.focus();
  }

  const SOURCE_WORDS = { user: 'saved', converted: 'made from a chain', restored: 'an older version put back' };

  async function openVersions() {
    const w = R.wf;
    if (!w || !w.source) return;
    closeVersions();
    let reply = null;
    let err = null;
    try { reply = await w.source.versions(); } catch (e) { err = e; }
    if (R.destroyed || R.wf !== w) return;
    if (err || !reply || reply.ok === false) {
      say(`The versions could not be listed: ${_sentence(err || reply, 'no answer')}`, { refusal: true });
      return;
    }
    const list = Array.isArray(reply.versions) ? reply.versions : [];
    const box = _el('div', 'wf-versions-box');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Versions');
    box.appendChild(_el('p', 'wf-versions-head', 'Versions'));
    box.appendChild(_el('p', 'wf-versions-note',
      'A version is kept each time a save changes the steps or the name; moving a step or pinning a sample makes none.'));
    const ul = _el('ul', 'wf-versions-list');
    if (!list.length) ul.appendChild(_el('li', 'wf-versions-empty', 'No versions are kept yet.'));
    for (const v of list) {
      const li = _el('li', 'wf-versions-row');
      const steps = Number(v.step_count);
      const what = [
        `Version ${v.version}`,
        _when(v.saved_at),
        Number.isFinite(steps) ? `${steps} step${steps === 1 ? '' : 's'}` : '',
        SOURCE_WORDS[v.source] || '',
        v.current ? 'the one in use' : '',
      ].filter(Boolean).join(' · ');
      li.appendChild(_el('span', 'wf-versions-what', what));
      const look = _button('wf-versions-look', 'Look at it');
      look.setAttribute('aria-label', `Look at version ${v.version}`);
      look.addEventListener('click', () => lookAt(v.version));
      li.appendChild(look);
      if (!v.current) {
        const back = _button('wf-versions-restore', 'Put this version back');
        back.setAttribute('aria-label', `Put version ${v.version} back`);
        back.addEventListener('click', () => restoreVersion(v.version));
        li.appendChild(back);
      }
      ul.appendChild(li);
    }
    box.appendChild(ul);
    const close = _button('wf-versions-close', 'Close');
    close.addEventListener('click', () => closeVersions(true));
    box.appendChild(close);
    view.insertBefore(box, viewing);
    R.versions = { box, release: holdEscape(() => { R.versions = null; box.remove(); versionsBtn.focus(); }) };
    const first = box.querySelector('button');
    if (first) first.focus();
  }

  async function lookAt(version) {
    const w = R.wf;
    if (!w || !w.source || typeof w.source.showVersion !== 'function') return;
    closeVersions();
    if (w.tab !== 'edit') setTab('edit', { quiet: true });
    let err = null;
    let reply = null;
    try { reply = await w.source.showVersion(version); } catch (e) { err = e; }
    if (R.destroyed || R.wf !== w) return;
    if (refused(err, reply)) {
      say(`Version ${version} could not be shown: ${_sentence(err || reply, 'no answer')}`, { refusal: true });
      return;
    }
    await w.canvas.reload();
    syncBar();
    say(`This is version ${version}. Nothing here can be changed; put it back to use it again.`);
  }

  async function backToCurrent() {
    const w = R.wf;
    if (!w || !w.source) return;
    try { await w.source.showVersion(null); } catch (_) { /* drawn below either way */ }
    if (R.destroyed || R.wf !== w) return;
    await w.canvas.reload();
    syncBar();
    say('Back to the version in use.');
  }

  function restoreVersion(version) {
    const w = R.wf;
    if (!w || !w.source) return;
    closeVersions();
    const go = async () => {
      let reply = null;
      let err = null;
      try { reply = await w.source.restoreVersion(version); } catch (e) { err = e; }
      if (R.destroyed || R.wf !== w) return;
      if (err || (reply && reply.ok === false)) {
        say(`Version ${version} was not put back: ${_sentence(err || reply, 'the server refused')}`, { refusal: true });
        return;
      }
      await w.canvas.reload();
      justSaved = true;
      syncBar();
      const doc = (reply && reply.workflow) || docOf(w.source);
      say(`Version ${version} is back${doc && doc.version != null ? `, saved as version ${doc.version}` : ''}. `
        + 'Nothing was lost: the version before it is still in Versions….');
      refreshShelf();
    };
    // Putting a version back replaces the draft: unsaved changes are asked
    // about first, as leaving would.
    if (docDirty()) {
      guardLeave(() => { go(); });
      return;
    }
    go();
  }

  viewingBack.addEventListener('click', () => {
    const v = R.wf ? viewingOf(R.wf.source) : null;
    if (v != null) restoreVersion(v);
  });
  viewingCurrent.addEventListener('click', () => backToCurrent());

  // ── Edit | Runs ──────────────────────────────────────────────────────────
  function setTab(tab, { quiet = false } = {}) {
    const w = R.wf;
    if (!w) return;
    w.tab = tab === 'runs' ? 'runs' : 'edit';
    for (const t of [editTab, runsTab]) {
      const on = t.dataset.tab === w.tab;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
      t.classList.toggle('active', on);
    }
    editHost.hidden = w.tab !== 'edit';
    runsView.hidden = w.tab !== 'runs';
    if (w.tab === 'runs' && !quiet) loadRuns();
  }
  editTab.addEventListener('click', () => setTab('edit'));
  runsTab.addEventListener('click', () => setTab('runs'));
  tabs.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = R.wf && R.wf.tab === 'edit' ? 'runs' : 'edit';
    setTab(next);
    (next === 'edit' ? editTab : runsTab).focus();
  });

  async function loadRuns() {
    const w = R.wf;
    if (!w || !R.api) return;
    const doc = docOf(w.source);
    const taskId = doc.task_id || (doc.trigger_task && doc.trigger_task.id);
    if (!taskId) { runList.replaceChildren(_el('li', 'wf-run-empty', 'This workflow has no start, so it has no runs.')); return; }
    runList.replaceChildren(_el('li', 'wf-run-empty', 'Loading the runs…'));
    let reply = null;
    let err = null;
    try { reply = await R.api.listExecutions(taskId, { limit: RUNS_SHOWN }); } catch (e) { err = e; }
    if (R.destroyed || R.wf !== w) return;
    if (err) {
      runList.replaceChildren(_el('li', 'wf-run-empty', `The runs could not be loaded: ${_sentence(err, 'no answer')}`));
      return;
    }
    w.runs = Array.isArray(reply && reply.runs) ? reply.runs : [];
    drawRuns();
    if (!w.runs.length) {
      teardownRun();
      say('No runs yet. Run now runs it once; otherwise it runs when what starts it happens, while it is on.');
      return;
    }
    // Opened on the newest run, or the one already open.
    const keep = w.runId && w.runs.find((r) => String(r.id) === w.runId);
    if (!keep) openRun(w.runs[0].id);
  }

  function drawRuns() {
    const w = R.wf;
    if (!w) return;
    runList.replaceChildren(...(w.runs || []).map((r) => {
      const li = _el('li', 'wf-run-row');
      const words = runWords(r);
      const dry = isDryRun(r);
      const b = _button('wf-run-item', null);
      b.dataset.runId = String(r.id);
      b.dataset.tone = dry ? 'plan' : words.tone;
      const mark = _el('span', 'wf-run-mark', dry ? '→' : words.mark);
      mark.setAttribute('aria-hidden', 'true');
      b.appendChild(mark);
      b.appendChild(_el('span', 'wf-run-word', dry ? 'Dry run' : words.word));
      b.appendChild(_el('span', 'wf-run-when', _when(r.started_at || r.finished_at)));
      b.setAttribute('aria-label', `${dry ? 'Dry run' : words.word}, ${_when(r.started_at || r.finished_at)}`);
      if (String(r.id) === w.runId) b.setAttribute('aria-current', 'true');
      b.addEventListener('click', () => openRun(r.id));
      li.appendChild(b);
      return li;
    }));
  }

  /** Which step of a run to open: the last one that failed, by the order it
   *  ran in — read from the run source's records when it exposes them, or
   *  else from what the canvas draws. */
  function failedStep(runSource, canvas) {
    const st = stateOf(runSource);
    // A source that names it (`state().failed`: the step a failed run ended
    // on, or null when the run did not fail) is taken at its word.
    if (Object.prototype.hasOwnProperty.call(st, 'failed')) {
      return st.failed && st.failed.nodeId != null ? String(st.failed.nodeId) : null;
    }
    const recs = [st.nodes, st.records, st.execution && st.execution.nodes].find(Array.isArray);
    if (recs) {
      const failed = recs.filter((n) => n && runStatusTone(n.status) === 'error')
        .sort((a, b) => (Number(a.seq) || 0) - (Number(b.seq) || 0));
      if (failed.length) return String(failed[failed.length - 1].node_id);
    }
    const items = canvas && typeof canvas.items === 'function' ? canvas.items() : [];
    const bad = items.filter((i) => i && i.outcome && i.outcome.tone === 'error');
    return bad.length ? String(bad[bad.length - 1].id) : null;
  }

  async function openRun(runId) {
    const w = R.wf;
    if (!w || !R.mods) return;
    teardownRun();
    w.runId = String(runId);
    drawRuns();
    let rs;
    try {
      rs = R.mods.createWorkflowSource({
        api: R.api, workflowId: w.id, mode: 'run', runId: w.runId, describeTrigger: describe, panels,
      });
      w.runSource = rs;
      await rs.ready;
      const why = loadErrorOf(rs);
      if (why) throw new Error(why);
    } catch (err) {
      if (R.destroyed || R.wf !== w || w.runSource !== rs) return;
      runHost.replaceChildren(_el('p', 'wf-run-empty', `This run could not be drawn: ${_sentence(err, 'no answer')}`));
      return;
    }
    if (R.destroyed || R.wf !== w || w.runSource !== rs) return;
    const rc = mountCanvas(runHost, { source: rs, renderSteps });
    w.runCanvas = rc;
    await rc.ready;
    if (R.destroyed || R.wf !== w || w.runCanvas !== rc) return;
    const run = (w.runs || []).find((r) => String(r.id) === w.runId) || {};
    const failed = failedStep(rs, rc);
    if (failed) {
      // `P22-07`: a failed run opens on its failed step, with what it was
      // handed open — "without being told where to look".
      w.failFocus = failed;
      rc.focusChain(failed);
      rc.select(failed);
      return;
    }
    rc.say(isDryRun(run)
      ? 'A dry run: each step says what it would have done. Nothing ran.'
      : `This run ${runWords(run).word === 'Success' ? 'worked' : 'ended: ' + runWords(run).word.toLowerCase()}. Open a step to read what it was handed and what it made.`);
  }

  function recordShown({ node, record }) {
    const w = R.wf;
    if (!w || !w.runCanvas || w.failFocus == null) return;
    const id = String((node && node.id) || (record && record.node_id) || '');
    if (id !== w.failFocus) return;
    w.failFocus = null;
    const label = String((record && record.label) || (node && node.label) || 'A step');
    const line = _firstLine(record && record.error) || 'it left no message';
    w.runCanvas.say(`“${label}” failed: ${line.replace(/\.$/, '')}. Its panel is open at What it was handed.`);
  }

  // ── New workflow, and a chain made one ───────────────────────────────────
  function closeNewForm() {
    const f = R.newForm;
    if (!f) return;
    R.newForm = null;
    f.release();
    newForm.hidden = true;
    newWfBtn.hidden = false;
  }

  function openNewForm() {
    closeNewForm();
    newWfBtn.hidden = true;
    newForm.hidden = false;
    newName.value = '';
    R.newForm = { release: holdEscape(() => { R.newForm = null; newForm.hidden = true; newWfBtn.hidden = false; newWfBtn.focus(); }) };
    newName.focus();
  }

  async function makeNew() {
    if (!R.api) return;
    const name = newName.value.trim();
    newGo.disabled = true;
    let reply = null;
    let err = null;
    try { reply = await R.api.createWorkflow(name ? { name } : {}); } catch (e) { err = e; }
    if (R.destroyed) return;
    newGo.disabled = false;
    if (err || !reply || !reply.workflow) {
      shelfNote.textContent = `Not made: ${_sentence(err, 'the server answered without a workflow')}`;
      return;
    }
    closeNewForm();
    await refreshShelf();
    await showWorkflow(reply.workflow.id, { notes: reply.notes, focusName: !name });
  }

  newWfBtn.addEventListener('click', () => guardLeave(() => openNewForm()));
  newGo.addEventListener('click', () => makeNew());
  newCancel.addEventListener('click', () => { closeNewForm(); newWfBtn.focus(); });
  newName.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); makeNew(); } });

  /** `P22-06`. *Make this chain a workflow*: the server copies each step's
   *  settings into the document and makes it switched off; the chain keeps
   *  running until the workflow is switched on. */
  function makeFromChain(headId) {
    return guardLeave(async () => {
      const mods = await ensureMods();
      if (R.destroyed) return;
      if (!mods) {
        say(`Workflows could not be loaded (${R.modsError.replace(/\.$/, '')}).`, { refusal: true });
        return;
      }
      let reply = null;
      let err = null;
      try { reply = await R.api.createWorkflow({ fromTaskId: String(headId) }); } catch (e) { err = e; }
      if (R.destroyed) return;
      if (err || !reply || !reply.workflow) {
        say(`Not made: ${_sentence(err, 'the server answered without a workflow')}`, { refusal: true });
        return;
      }
      await refreshShelf();
      await showWorkflow(reply.workflow.id, { notes: reply.notes });
    });
  }

  // ── doors for the window ─────────────────────────────────────────────────
  function focusChain(taskId) {
    if (taskId == null) return;
    const w = R.workflows.find((x) => String(x.task_id) === String(taskId));
    if (w) { openWorkflow(w.id); return; }
    openTasks(taskId);
  }

  /** Whether the window may close now. With unsaved work it asks, and once
   *  answered (Save worked, or Discard) calls `onClose` — which asks this
   *  again, and is told yes: an open step's own edits are still in its form
   *  after a Discard, and asking twice about one close would be a loop. */
  function canClose(onClose) {
    if (R.closeAnswered) { R.closeAnswered = false; return true; }
    if (!unsaved()) return true;
    guardLeave(() => {
      R.closeAnswered = true;
      if (typeof onClose === 'function') onClose();
      R.closeAnswered = false;
    });
    return false;
  }

  function destroy() {
    if (R.destroyed) return;
    R.destroyed = true;
    closeNewForm();
    teardownWorkflow();
    leaveTasksView();
    host.replaceChildren();
    host.classList.remove('wf-room', 'wb-room');
    delete host.dataset.escLayer;
  }

  // ── start ────────────────────────────────────────────────────────────────
  if (opts.workflowId != null) {
    R.view = 'workflow';
    tasksHost.hidden = true;
  } else {
    showTasks(opts.focusId != null ? String(opts.focusId) : null);
  }
  drawShelf();
  const ready = (async () => {
    const listed = refreshShelf();
    if (opts.workflowId != null) {
      const ok = await showWorkflow(opts.workflowId);
      if (!ok && !R.destroyed && R.view !== 'tasks') showTasks();
    }
    if (R.tasksCanvas) await R.tasksCanvas.ready;
    await listed;
    // Opened on a task that is a workflow's start (⋮ → *Workflow* on its
    // card): the document is what that task runs, so it opens.
    if (opts.workflowId == null && opts.focusId != null && !R.destroyed && R.view === 'tasks') {
      const w = R.workflows.find((x) => String(x.task_id) === String(opts.focusId));
      if (w) await showWorkflow(w.id);
    }
    return !R.destroyed;
  })();

  return {
    ready,
    focusChain,
    openWorkflow: (id) => openWorkflow(id),
    canClose,
    destroy,
    /** The canvas on screen (tests and the glue's Escape reach the room
     *  through its handle). */
    canvas: () => activeCanvas(),
  };
}

export default { mountAutomations, runWords, isDryRun, isOn, OFF_WORDS, ON_WORDS };
