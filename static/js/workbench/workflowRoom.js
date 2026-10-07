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
//
// **Slice E (`P22-19`, `P22-20`, `P22-24`, wb-canvas-e; `SLICE-EF-DESIGN.md`
// § 2, § 3 B, contract C-A).** *New workflow* gains *Or describe it* — a box,
// *Draft it*, and at most six example sentences that fill the box
// (`D-2026-10-02-02` §1: the palette's `examples`; nothing is installed or
// fetched) — and *Or open a file…*. Either makes a workflow switched off with
// every step marked; the room opens it on what arrived: what it sends where
// (`destinations`) and what is missing (`missing`), each line with its door
// (`openWorkbench({ room })`, C-R). Switching on while a step is unchecked is
// refused by the server (409, `reason: "unchecked"`), and that refusal offers
// *Check them now*: every unchecked step with what it would do, *Looks right*
// each and *All look right*, then *Switch on*. *Export* downloads the saved
// workflow as a file. A failed step's *Why did this fail?* lives in its record
// panel; applying its fix and undoing it are this room's (`fixer`), because
// the room holds the document. Every word a model wrote — a drafted label, a
// reason, a missing line — is text.

import { mountCanvas } from './canvas.js';
import { createWorkflowPanels } from './workflowPanels.js';
import { needLine, needDoor, NEED_DOORS } from './stepFields.js';
import { runStatusTone, runStatusLabel, RUN_ACTIVE_STATUSES } from '../runStatus.js';
import { registerMenuDismiss } from '../escMenuStack.js';

const OUTCOME_MARKS = { ok: '✓', error: '✗', pending: '…', info: '·', none: '○' };
/** The shelf's first entry: the canvas `P22-02` shipped. */
const TASKS_KEY = 'tasks';
/** How many runs the Runs tab lists. */
const RUNS_SHOWN = 30;
/** `B1108`. How often the shelf is read again while a run it lists is in
 *  flight (queued or running), so a run that ends is read without opening
 *  the room again. Nothing is asked while no run is in flight. */
export const SHELF_WATCH_MS = 4000;
/** Said when a workflow is off — the design's words (§ 6.2). */
export const OFF_WORDS = 'Switched off — it will not run until you switch it on.';
export const ON_WORDS = 'On — it runs whenever what starts it happens.';
/** `P22-19`. At most this many example sentences are offered under *Describe
 *  it* (`D-2026-10-02-02` §1). */
export const EXAMPLES_MAX = 6;
/** `P22-19`, `P22-24`. Who decided the steps of a workflow that arrived. */
export const ARRIVED_WORDS = Object.freeze({
  drafted: 'Drafted by the model',
  imported: 'Imported from a file',
  // `integrate-e`: not an arrival — the origin of a step the assistant
  // changed, as *Check them now* lists it.
  assistant: 'Changed by your assistant',
});
/** Said over every workflow that arrived: it does nothing until checked. */
export const ARRIVED_LEDE = 'It is switched off, and each step is marked “check me” until you look at it: open a step '
  + 'and press Looks right, or press Check them now.';
/** `P22-24`. What the export says the file holds (C-A's export, design § 1.6). */
export const EXPORT_WORDS = 'It holds the saved steps and the names of what they use; keys, tokens, addresses and '
  + 'pinned samples are left out.';

/** `P22-24`. Hand `blob` to the browser as a download named `filename`. */
function _download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.hidden = true;
  document.body.appendChild(a);
  try {
    a.click();
  } finally {
    a.remove();
    setTimeout(() => { try { URL.revokeObjectURL(url); } catch (_) { /* gone */ } }, 0);
  }
}

/** `P22-19`. The person's time zone, for the drafter's start time; none when
 *  the browser cannot say. */
function _timeZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined; } catch (_) { return undefined; }
}

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

/** `P23-06` (WB-U-4): "3:44 AM" today, "Oct 2, 3:44 AM" another day this
 *  year, the year after that — `toLocaleString()` printed the full date and
 *  seconds on runs minutes apart. */
function _when(iso, now = new Date()) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if (d.toDateString() === now.toDateString()) return time;
  const day = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== now.getFullYear()) day.year = 'numeric';
  return `${d.toLocaleDateString([], day)}, ${time}`;
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
    wf: null,            // { id, source, canvas, tab, runs, runSource, runCanvas, runId, failFocus, failSentence }
    asking: null, versions: null, newForm: null,
    // `P22-19`, `P22-24`. The open check layer, the arrival box, and the
    // example sentences (read once, from the palette).
    checking: null, arrived: null, examples: null, making: false,
    shelfTimer: null,    // `B1108`: the next read of the shelf while a run is in flight
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
  // `P22-19`. *Or describe it*: the model drafts the steps.
  const describeGroup = _el('div', 'wf-new-describe');
  const describeLabel = _el('label', 'wf-new-field');
  describeLabel.appendChild(_el('span', 'wf-new-label', 'Or describe it'));
  const describeBox = _el('textarea', 'wf-new-text');
  describeBox.rows = 4;
  describeBox.placeholder = 'When it starts, and each thing it does — e.g. every morning at 8, summarise my unread mail and send it to me';
  describeLabel.appendChild(describeBox);
  describeGroup.appendChild(describeLabel);
  const draftGo = _button('wf-new-draft', 'Draft it',
    'The model drafts the steps from what this Pantheon can reach. It is made switched off, and you check each step before it can run.');
  const draftRow = _el('div', 'wf-new-buttons');
  draftRow.appendChild(draftGo);
  describeGroup.appendChild(draftRow);
  const examples = _el('div', 'wf-new-examples');
  examples.setAttribute('role', 'group');
  examples.setAttribute('aria-label', 'Start from an example');
  examples.hidden = true;
  describeGroup.appendChild(examples);
  // `P22-24`. *Or open a file…*: a workflow someone exported.
  const fileGroup = _el('div', 'wf-new-file-group');
  const fileBtn = _button('wf-new-file', 'Or open a file…',
    'Import a workflow someone exported. It is made switched off, and you check each step before it can run.');
  const fileInput = _el('input', 'wf-new-file-input');
  fileInput.type = 'file';
  fileInput.accept = '.json,application/json';
  fileInput.hidden = true;
  fileInput.setAttribute('aria-hidden', 'true');
  fileInput.tabIndex = -1;
  fileGroup.appendChild(fileBtn);
  fileGroup.appendChild(fileInput);
  const newSay = _el('p', 'wf-new-say');
  newSay.setAttribute('role', 'status');
  newSay.setAttribute('aria-live', 'polite');
  for (const n of [describeGroup, fileGroup, newSay]) newForm.appendChild(n);
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
  // `P22-24`. The saved workflow as a file.
  const exportBtn = _button('wf-export', 'Export', 'Download the saved workflow as a file to hand someone. ' + EXPORT_WORDS);
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
  const runGroup = _el('span', 'wf-bar-group wf-bar-runs');
  for (const n of [versionsBtn, runBtn, dryBtn, exportBtn]) runGroup.appendChild(n);
  // `P23-06` (WB-U-13). On a phone the toolbar took 280 px over a 434 px
  // canvas. There it is the name, the switch and this ⋯, which shows the
  // rest (Versions…, Run now, the plan, Export) when pressed; on a desktop
  // the ⋯ is not drawn and the rest is always there (`style.css`).
  const moreBtn = _button('wf-bar-more', '⋯', 'Versions, Run now, the plan, Export');
  moreBtn.setAttribute('aria-label', 'More');
  moreBtn.setAttribute('aria-expanded', 'false');
  moreBtn.addEventListener('click', () => {
    const open = !bar.classList.contains('wf-bar-more-open');
    bar.classList.toggle('wf-bar-more-open', open);
    moreBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  for (const n of [nameGroup, switchGroup, moreBtn, runGroup, tabs]) bar.appendChild(n);

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
    // `P23-06` (WB-M-4). The Runs tab with no run on it has no canvas to say
    // things on, so its line ("No runs yet…") fell back to the room's line —
    // above the workflow's own toolbar, pushing it down, and still there after
    // Edit. It belongs in the empty run list.
    if (R.view === 'workflow' && R.wf && R.wf.tab === 'runs' && !R.wf.runCanvas && text && !o.action) {
      sayLine.hidden = true;
      const li = _el('li', 'wf-run-empty', text);
      if (o.refusal) li.classList.add('wf-say-refusal');
      runList.replaceChildren(li);
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
    // `P22-17` (wf-canvas). A waiting step answered from its record: the run
    // is drawn again, and the list says how it stands now.
    onAnswered: (info) => answered(info),
    // `P22-20` (wb-canvas-e). A fix is applied to the document, which this
    // room holds; a run's record panel holds only the run.
    fixer: {
      apply: (proposal) => applyFix(proposal),
      undo: (version) => undoFix(version),
      runAgain: () => runNow(),
    },
    // `P22-24`. The door beside what a step needs.
    openRoom: (room) => openRoom(room),
  });

  /** `P22-24`. Open the Workbench at `room` (C-R: `openWorkbench({ room })`,
   *  wb-rooms' — the rooms are kept when another is shown, so this room's
   *  draft survives). `workbench.js` is reached through `import()` with the
   *  spelling every other door uses, so it is the page's one instance. */
  function openRoom(room) {
    const load = typeof opts.loadWorkbench === 'function' ? opts.loadWorkbench : () => import('./workbench.js');
    return Promise.resolve().then(() => load()).then((m) => {
      const open = m && (typeof m.openWorkbench === 'function' ? m.openWorkbench
        : (m.default && typeof m.default.openWorkbench === 'function' ? m.default.openWorkbench : null));
      if (!open) throw new Error('no door');
      open({ room: String(room) });
      return true;
    }).catch(() => {
      if (!R.destroyed) say(`${NEED_DOORS[room] ? NEED_DOORS[room].replace(/^Open /, '') : 'That room'} could not be opened here.`, { refusal: true });
      return false;
    });
  }

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
      // `P23-06` (WB-U-16): two workflows drafted from one sentence were two
      // identical rows; how many steps each has tells them apart.
      const steps = Number(w.step_count);
      if (Number.isFinite(steps) && w.step_count != null) {
        sub.appendChild(_el('span', 'wf-shelf-steps', `${steps} step${steps === 1 ? '' : 's'}`));
      }
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
    watchShelf();
    return true;
  }

  // ── `B1108`: the shelf reads a run's state as it changes ───────────────────
  // Measured by `integrate-d`: with a workflow open, its Runs list read
  // "Waiting" and the shelf beside it "Not run yet" — the shelf was drawn when
  // the room opened and not when a run started or ended. Now: *Run now* and an
  // answer to a step's question read the shelf again; the Runs list, whenever
  // it is read, sets the open workflow's row from its newest real run (the
  // server's `last_real_runs` rule: a dry run is never a last run); and while
  // the server's shelf lists a run in flight it is read again every
  // `SHELF_WATCH_MS`, the open workflow's Runs list with it when its run
  // moved. Only a read of the server's shelf arms the next one, so the Runs
  // list and the shelf cannot set each other off.
  const lastOpenRun = () => {
    const w = R.wf && R.workflows.find((x) => String(x.id) === String(R.wf.id));
    return w && w.last_run ? `${w.last_run.id}:${w.last_run.status}` : '';
  };

  function stopWatchingShelf() {
    if (R.shelfTimer) { clearTimeout(R.shelfTimer); R.shelfTimer = null; }
  }

  function watchShelf() {
    stopWatchingShelf();
    if (R.destroyed) return;
    const inFlight = R.workflows.some((w) => w.last_run && !w.last_run.dry
      && RUN_ACTIVE_STATUSES.includes(w.last_run.status));
    if (!inFlight) return;
    R.shelfTimer = setTimeout(async () => {
      R.shelfTimer = null;
      const before = lastOpenRun();
      await refreshShelf();
      if (R.destroyed || !R.wf || R.wf.tab !== 'runs' || lastOpenRun() === before) return;
      loadRuns();
    }, SHELF_WATCH_MS);
  }

  /** The open workflow's shelf row, from a Runs list just read (newest first). */
  function shelfFromRuns(w) {
    if (!w || !Array.isArray(w.runs)) return;
    const row = R.workflows.find((x) => String(x.id) === String(w.id));
    if (!row) return;
    const newest = w.runs.find((r) => r && !isDryRun(r));
    const last = newest ? { id: newest.id, status: newest.status, started_at: newest.started_at || null,
      finished_at: newest.finished_at || null, dry: false } : null;
    const was = row.last_run ? `${row.last_run.id}:${row.last_run.status}` : '';
    if ((last ? `${last.id}:${last.status}` : '') === was) return;
    row.last_run = last;
    drawShelf();
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
    closeCheck();
    closeArrived();
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
  async function showWorkflow(id, { notes = null, focusName = false, arrived = null } = {}) {
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
    // What arrived is drawn before the canvas, so the canvas fits the room it
    // has left (measured in Chromium at 1400×860: drawn after, it pushed the
    // fitted steps to the window's bottom edge).
    if (arrived) drawArrived(arrived);
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
    for (const b of [saveBtn, switchBtn, runBtn, dryBtn, exportBtn]) b.disabled = v != null;
    // `P22-24`. Offered only where the data layer can export (C-A).
    exportBtn.hidden = !(R.api && typeof R.api.exportWorkflow === 'function');
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
      // `P22-09` (wf-canvas). A refusal about one field of a step — a
      // reference in a command, a URL, a recipient — opens that step, and its
      // panel says the sentence on the field (the source hands it the draft's
      // problem). Opened first and fitted after, as a failed run's step is.
      if (nodeIds.length && why.field && w.canvas && !(w.canvas.isDirty && w.canvas.isDirty())) w.canvas.select(nodeIds[0]);
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

  /** On or Off — the other way from now, or `want`. Answers `{ on, words,
   *  action }` (what it said, or with `quiet` would have), or null. */
  async function toggleSwitch(want = null, { quiet = false } = {}) {
    const w = R.wf;
    if (!w || !w.source) return null;
    const on = want == null ? !isOn(docOf(w.source)) : !!want;
    switchBtn.disabled = true;
    let reply = null;
    let err = null;
    try { reply = await w.source.switchOn(on); } catch (e) { err = e; }
    if (R.destroyed || R.wf !== w) return null;
    switchBtn.disabled = false;
    if (err || (reply && reply.ok === false)) {
      const why = err || reply;
      // `P22-19`. Switching on while a step is unchecked is refused (C-A: 409,
      // `reason: "unchecked"`, `node_ids`); the refusal is said as the server
      // wrote it, and offers the check.
      const unchecked = on && why.reason === 'unchecked';
      const ids = Array.isArray(why.nodeIds) ? why.nodeIds.map(String) : [];
      say(`Not switched ${on ? 'on' : 'off'}: ${_sentence(why, 'the server refused')}`, {
        refusal: true,
        action: unchecked ? { label: 'Check them now', run: () => openCheck(ids) } : null,
      });
      syncBar();
      return null;
    }
    const notes = (Array.isArray(reply && reply.notes) ? reply.notes : []).map(String).filter(Boolean);
    let words = notes.join(' ') || (on ? 'Switched on.' : OFF_WORDS);
    if (on && stateOf(w.source).dirty) words += ' It runs the saved version; your unsaved changes are not in it.';
    // The route's `chain_paused`, or the same as a source names it.
    const paused = on && reply && (reply.chain_paused || reply.chainPaused);
    const action = paused ? { label: 'Put the old chain back', run: () => restoreChain() } : null;
    // The start's box says On or Off too: redraw it from the source (wave C
    // merge — measured in Chromium, the box read "Switched off" after On until
    // the workflow was opened again). The draft lives in the source, so a
    // redraw keeps any unsaved change.
    if (w.canvas) await w.canvas.reload();
    if (R.destroyed || R.wf !== w) return null;
    if (!quiet) say(words, { action });
    syncBar();
    refreshShelf();
    return { on, words, action };
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
    if (w.canvas) await w.canvas.reload();     // the start's box says Off again (as `toggleSwitch`)
    if (R.destroyed || R.wf !== w) return;
    say(notes.join(' ') || 'The chain runs again and this workflow is switched off. Nothing was deleted.');
    syncBar();
    refreshShelf();
  }

  /** `lead` — what switching it on just said, said first. */
  async function runNow(lead = null) {
    const w = R.wf;
    if (!w || !w.source) return;
    // Measured on a merge of the three branches: a switched-off workflow's
    // Run now is recorded "skipped — Task no longer active (status=paused)",
    // and the room had already said "Started". A new workflow is made
    // switched off, so that was the first thing a person met. It says so
    // before asking, and offers the one click they meant.
    if (!isOn(docOf(w.source))) {
      say(`“${wfName(w.source)}” is switched off, so it would not run. Switch it on to run it; `
        + 'Show me what this would do and Test this step work while it is off.', {
        action: {
          label: 'Switch on and run now',
          run: async () => { const sw = await toggleSwitch(true, { quiet: true }); if (sw && sw.on) runNow(sw); },
        },
      });
      return;
    }
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
    // A chain paused by switching on keeps its way back as the action.
    say((lead && lead.words ? lead.words.replace(/\s*It runs the saved version;.*$/, '') + ' ' : '')
      + 'Started. Its run will be listed under Runs.'
      + (stateOf(w.source).dirty ? ' It runs the saved version; your unsaved changes are not in it.' : ''),
    { action: (lead && lead.action) || { label: 'Show the runs', run: () => setTab('runs') } });
    if (w.tab === 'runs') loadRuns();
    refreshShelf();      // `B1108`: the run just started, as the server has it
  }

  function dryRun() {
    const w = R.wf;
    if (!w || !w.canvas) return;
    if (w.tab !== 'edit') setTab('edit', { quiet: true });
    w.canvas.dryRun(null, { title: wfName(w.source) });
  }

  exportBtn.addEventListener('click', () => exportIt());
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

  // `P22-19`, `P22-20`, `P22-24`: the three sources Slice E adds (C-A's
  // `version.source`), each in the words of what made it.
  const SOURCE_WORDS = {
    user: 'saved', converted: 'made from a chain', restored: 'an older version put back',
    drafted: 'drafted by the model', imported: 'imported from a file', fixed: 'a fix you applied',
  };

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
    // `P23-06` (WB-M-4): a line the other tab left on the room goes with it.
    sayLine.hidden = true;
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
    shelfFromRuns(w);
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
      // `P23-06` (WB-U-4): folded to its mark while a step's panel is open,
      // a run still says what it is on hover.
      b.title = b.getAttribute('aria-label');
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
    // `P22-11`, `P22-17` (wf-canvas). A run that is waiting opens on the step
    // it waits on, with what it waits for — and, for a yes, its card — open
    // beside it.
    const waiting = stateOf(rs).waiting;
    if (waiting && waiting.nodeId != null) {
      const id = String(waiting.nodeId);
      rc.select(id);
      rc.focusChain(id);
      rc.say(waitingSentence(waiting));
      return;
    }
    if (failed) {
      // `P22-07`: a failed run opens on its failed step, with what it was
      // handed open — "without being told where to look".
      // The panel opens first and the step is fitted after, into what is
      // left beside it: fitted first, measured in Chromium, the panel then
      // covered the very step it was opened for. The fit says its own
      // sentence, so the failure's is said again after it.
      w.failFocus = failed;
      w.failSentence = '';
      rc.select(failed);
      rc.focusChain(failed);
      if (w.failSentence) rc.say(w.failSentence);
      return;
    }
    rc.say(isDryRun(run)
      ? 'A dry run: each step says what it would have done. Nothing ran.'
      : `This run ${runWords(run).word === 'Success' ? 'worked' : 'ended: ' + runWords(run).word.toLowerCase()}. Open a step to read what it was handed and what it made.`);
  }

  /** What a waiting run's line says when it opens on its waiting step. */
  function waitingSentence(wt) {
    const name = `“${wt.label || 'A step'}”` + (wt.item != null ? ` (item ${Number(wt.item) + 1})` : '');
    if (wt.kind === 'approval') return `${name} is waiting for your yes. Its question is open beside it: Allow once, or Deny.`;
    if (wt.kind === 'time') return `${name} is ${String(wt.words || 'waiting').replace(/^Waiting/, 'waiting')}. The run goes on by itself.`;
    if (wt.kind === 'idle') return `${name} is waiting for Pantheon to be idle; the run goes on from that step.`;
    return `${name} is waiting.`;
  }

  /** `P22-17`. After a waiting step was answered from its record. */
  async function answered({ reply } = {}) {
    const w = R.wf;
    if (!w || !w.runCanvas) return;
    const rc = w.runCanvas;
    await rc.reload();
    if (R.destroyed || R.wf !== w || w.runCanvas !== rc) return;
    const sentence = reply && reply.sentence ? String(reply.sentence) : 'Answered.';
    rc.say(sentence);
    // The run's row in the list says how it stands now.
    if (R.api && w.runs) {
      try {
        const doc = docOf(w.source);
        const taskId = doc.task_id || (doc.trigger_task && doc.trigger_task.id);
        const out = taskId ? await R.api.listExecutions(taskId, { limit: RUNS_SHOWN }) : null;
        if (R.destroyed || R.wf !== w) return;
        if (out && Array.isArray(out.runs)) { w.runs = out.runs; drawRuns(); shelfFromRuns(w); }
      } catch (_) { /* the list stays as it was */ }
    }
    refreshShelf();      // `B1108`: the run goes on (or ends) — as the server has it
  }

  function recordShown({ node, record }) {
    const w = R.wf;
    if (!w || !w.runCanvas || w.failFocus == null) return;
    const id = String((node && node.id) || (record && record.node_id) || '');
    if (id !== w.failFocus) return;
    w.failFocus = null;
    const label = String((record && record.label) || (node && node.label) || 'A step');
    const line = _firstLine(record && record.error) || 'it left no message';
    w.failSentence = `“${label}” failed: ${line.replace(/\.$/, '')}. Its panel is open at What it was handed.`;
    w.runCanvas.say(w.failSentence);
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
    newSay.textContent = '';
    newSay.classList.remove('wf-new-refusal');
    // `P22-19`, `P22-24`. Offered where the data layer can make a workflow
    // that arrives marked AND take its checks (C-A): a describe or a file
    // sent to a data layer without them would make an empty workflow.
    const can = canArrive();
    describeGroup.hidden = !can;
    fileGroup.hidden = !can;
    if (can) loadExamples();
    R.newForm = { release: holdEscape(() => { R.newForm = null; newForm.hidden = true; newWfBtn.hidden = false; newWfBtn.focus(); }) };
    newName.focus();
  }

  /** `P22-19`, `P22-24`. Whether the data layer has C-A's calls. */
  const canArrive = () => !!(R.api && typeof R.api.checkSteps === 'function');

  /** `P22-19` (`D-2026-10-02-02` §1). The example sentences under *Describe
   *  it*: the palette's `examples` (served by the drafter's package), at most
   *  six; picking one fills the box — nothing is sent, installed or fetched. */
  async function loadExamples() {
    if (R.examples == null) {
      R.examples = [];
      if (R.api && typeof R.api.getPalette === 'function') {
        try {
          const p = await R.api.getPalette();
          const list = p && Array.isArray(p.examples) ? p.examples : [];
          R.examples = list.map((x) => String(x == null ? '' : x).trim()).filter(Boolean).slice(0, EXAMPLES_MAX);
        } catch (_) { R.examples = []; }
      }
      if (R.destroyed) return;
    }
    examples.replaceChildren();
    if (!R.examples.length) { examples.hidden = true; return; }
    examples.appendChild(_el('p', 'wf-new-label', 'Start from an example'));
    const ul = _el('ul', 'wf-new-example-list');
    for (const text of R.examples) {
      const li = _el('li', null);
      const b = _button('wf-new-example', text, 'Put this sentence in the box. Nothing is drafted until you press Draft it.');
      b.addEventListener('click', () => {
        describeBox.value = text;
        describeBox.focus();
        newSay.textContent = '';
      });
      li.appendChild(b);
      ul.appendChild(li);
    }
    examples.appendChild(ul);
    examples.hidden = false;
  }

  function newSays(text, refusal = false) {
    newSay.textContent = text || '';
    newSay.classList.toggle('wf-new-refusal', !!refusal);
  }

  function making(on) {
    R.making = !!on;
    for (const b of [newGo, draftGo, fileBtn]) b.disabled = !!on;
    describeBox.readOnly = !!on;
  }

  /** `P22-19`. *Draft it*: C-A's create door with `{ describe, tz }`. The
   *  model's answer is made switched off and marked, or refused in the
   *  server's words (no model; a draft that could not be used). */
  async function draftIt() {
    if (!R.api || R.making) return;
    const text = describeBox.value.trim();
    if (!text) {
      newSays('Say what it should do first: when it starts, and each thing it does.', true);
      describeBox.focus();
      return;
    }
    making(true);
    newSays('Drafting… the model is writing the steps. This can take a minute.');
    let reply = null;
    let err = null;
    try { reply = await R.api.createWorkflow({ describe: text, tz: _timeZone() }); } catch (e) { err = e; }
    if (R.destroyed) return;
    making(false);
    if (err || !reply || !reply.workflow) {
      newSays(`Not drafted: ${_sentence(err, 'the server answered without a workflow')}`, true);
      return;
    }
    describeBox.value = '';
    await arrive(reply, 'drafted');
  }

  /** `P22-24`. *Or open a file…*: the file is read here and handed to C-A's
   *  create door as `{ file }`; the server checks it and says what this
   *  Pantheon is missing. A file that is not JSON is said here. */
  async function openFile() {
    const f = fileInput.files && fileInput.files[0];
    if (!f || !R.api || R.making) return;
    const name = String(f.name || 'That file');
    let data;
    try {
      data = JSON.parse(await f.text());
    } catch (_) {
      newSays(`“${name}” is not a workflow file: it is not JSON. Nothing was made.`, true);
      try { fileInput.value = ''; } catch (_) { /* a fresh pick works either way */ }
      return;
    }
    try { fileInput.value = ''; } catch (_) { /* as above */ }
    making(true);
    newSays(`Opening “${name}”…`);
    let reply = null;
    let err = null;
    try { reply = await R.api.createWorkflow({ file: data }); } catch (e) { err = e; }
    if (R.destroyed) return;
    making(false);
    if (err || !reply || !reply.workflow) {
      newSays(`Not imported: ${_sentence(err, 'the server answered without a workflow')}`, true);
      return;
    }
    await arrive(reply, 'imported');
  }

  /** A drafted or imported workflow is made: open it on what arrived. */
  async function arrive(reply, origin) {
    closeNewForm();
    await refreshShelf();
    if (R.destroyed) return;
    const arrived = {
      origin,
      missing: (Array.isArray(reply.missing) ? reply.missing : []).map((x) => String(x == null ? '' : x)).filter(Boolean),
      destinations: (Array.isArray(reply.destinations) ? reply.destinations : []).map((x) => String(x == null ? '' : x)).filter(Boolean),
    };
    guardLeave(() => { showWorkflow(reply.workflow.id, { notes: reply.notes, arrived }); });
  }

  // ── what arrived (`P22-19`, `P22-24`) ────────────────────────────────────
  function closeArrived() {
    const a = R.arrived;
    if (!a) return;
    R.arrived = null;
    a.remove();
  }

  /** A `missing` line's need, if one of the marked steps' needs is named in
   *  it verbatim (the server's sentence names what it could not find — C-A
   *  gives the line no kind, so its door is the need's). → `{ step, need }` */
  function needOfLine(line, pool) {
    const said = (x) => { const t = String(x == null ? '' : x).trim(); return t.length > 1 && line.includes(t); };
    const fits = pool.filter((p) => !p.used && (said(p.need.name) || said(p.need.tool) || said(p.need.server)));
    const best = fits.find((p) => said(p.step.label)) || fits[0] || null;
    if (best) best.used = true;
    return best;
  }

  function drawArrived({ origin = 'drafted', missing = [], destinations = [] } = {}) {
    closeArrived();
    const w = R.wf;
    if (!w) return;
    const o = Object.prototype.hasOwnProperty.call(ARRIVED_WORDS, origin) ? origin : 'drafted';
    const box = _el('section', 'wf-arrived');
    box.dataset.origin = o;
    box.setAttribute('aria-label', ARRIVED_WORDS[o]);
    box.appendChild(_el('p', 'wf-arrived-head', ARRIVED_WORDS[o]));
    box.appendChild(_el('p', 'wf-arrived-lede', ARRIVED_LEDE));
    if (destinations.length) {
      box.appendChild(_el('p', 'wf-arrived-sub', 'Where it sends things:'));
      const ul = _el('ul', 'wf-arrived-destinations');
      for (const line of destinations) ul.appendChild(_el('li', null, line));
      box.appendChild(ul);
    }
    if (missing.length) {
      box.appendChild(_el('p', 'wf-arrived-sub', o === 'imported'
        ? 'What this Pantheon is missing:' : 'What the model could not draft:'));
      const marks = typeof w.source.marked === 'function' ? w.source.marked() : [];
      const pool = [];
      for (const step of marks) for (const need of step.needs) pool.push({ step, need, used: false });
      const ul = _el('ul', 'wf-arrived-missing');
      for (const line of missing) {
        const li = _el('li', 'wf-arrived-line');
        li.appendChild(_el('span', 'wf-arrived-text', line));
        const hit = needOfLine(line, pool);
        if (hit) {
          li.dataset.nodeId = hit.step.id;
          const room = needDoor(hit.need);
          if (room) {
            const door = _button('wf-arrived-door', NEED_DOORS[room]);
            door.dataset.room = room;
            door.addEventListener('click', () => openRoom(room));
            li.appendChild(door);
          }
          const show = _button('wf-arrived-show', 'Show the step');
          show.setAttribute('aria-label', `Show “${hit.step.label}”`);
          show.addEventListener('click', () => showStep(hit.step.id));
          li.appendChild(show);
        }
        ul.appendChild(li);
      }
      box.appendChild(ul);
    }
    const row = _el('div', 'wf-arrived-buttons');
    const check = _button('wf-arrived-check', 'Check them now');
    check.addEventListener('click', () => openCheck(null));
    const close = _button('wf-arrived-close', 'Close');
    close.addEventListener('click', () => closeArrived());
    row.appendChild(check);
    row.appendChild(close);
    box.appendChild(row);
    view.insertBefore(box, viewing);
    R.arrived = box;
  }

  /** Open step `id` on the canvas (its panel, with its banner). */
  function showStep(id) {
    const w = R.wf;
    if (!w || !w.canvas) return;
    if (w.tab !== 'edit') setTab('edit', { quiet: true });
    w.canvas.select(String(id));
    w.canvas.focusChain(String(id));
  }

  // ── Check them now (`P22-19`) ────────────────────────────────────────────
  function closeCheck(restoreFocus) {
    const c = R.checking;
    if (!c) return;
    R.checking = null;
    c.alive = false;
    c.release();
    c.box.remove();
    if (restoreFocus) switchBtn.focus();
  }

  /** The layer: every step nobody has checked (`nodeIds` — the server's
   *  refusal names them — or, without, every marked step of the saved
   *  document), each with what it needs, what it would do, *Open it* and
   *  *Looks right*; *All look right* sends the rest at once. Once none is
   *  left it offers *Switch on*. */
  function openCheck(nodeIds = null) {
    const w = R.wf;
    if (!w || !w.source) return;
    closeCheck();
    closeVersions();
    // The layer says per step what the arrival box said (needs, doors), and
    // the two together would leave the canvas no room: the box goes.
    closeArrived();
    // `P23-06` (WB-M-5): the line that offered *Check them now* (a refused
    // switch-on) goes too — it stayed under the box with a second button.
    say('');
    if (w.tab !== 'edit') setTab('edit', { quiet: true });
    const all = typeof w.source.marked === 'function' ? w.source.marked() : [];
    const ids = Array.isArray(nodeIds) && nodeIds.length ? nodeIds.map(String) : all.map((m) => m.id);
    const docNodes = (docOf(w.source).graph && Array.isArray(docOf(w.source).graph.nodes)) ? docOf(w.source).graph.nodes : [];
    const steps = ids.map((id) => all.find((m) => m.id === id) || {
      id, label: String(((docNodes.find((n) => n && String(n.id) === id) || {}).label) || id),
      origin: 'drafted', needs: [], changed: false,
    });
    const C = { box: null, release: () => {}, alive: true, rows: new Map() };
    const box = _el('section', 'wf-check');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Check them now');
    box.appendChild(_el('p', 'wf-check-head', 'Check them now'));
    const lede = _el('p', 'wf-check-lede');
    box.appendChild(lede);
    if (stateOf(w.source).dirty) {
      box.appendChild(_el('p', 'wf-check-note', 'You have changes that are not saved: this checks the steps as they are saved.'));
    }
    const ul = _el('ul', 'wf-check-list');
    for (const st of steps) {
      const li = _el('li', 'wf-check-step');
      li.dataset.nodeId = st.id;
      const name = _el('p', 'wf-check-name');
      name.appendChild(_el('span', 'wf-check-label', st.label));
      name.appendChild(_el('span', 'wf-check-origin', ARRIVED_WORDS[st.origin] || ARRIVED_WORDS.drafted));
      li.appendChild(name);
      for (const need of st.needs || []) li.appendChild(needLine(need, { openRoom, cls: 'wf-check-need' }));
      if (st.changed) {
        li.appendChild(_el('p', 'wf-check-note', 'You changed this step. Save, and it is yours: it needs no check.'));
      }
      const plan = _el('ul', 'wf-check-plan');
      plan.appendChild(_el('li', 'wf-check-wait', 'Planning…'));
      li.appendChild(plan);
      const buttons = _el('div', 'wf-check-buttons');
      const open = _button('wf-check-open', 'Open it');
      open.setAttribute('aria-label', `Open “${st.label}”`);
      open.addEventListener('click', () => { closeCheck(); showStep(st.id); });
      const yes = _button('wf-check-yes', 'Looks right');
      yes.setAttribute('aria-label', `“${st.label}” looks right`);
      yes.addEventListener('click', () => checkThese([st.id]));
      buttons.appendChild(open);
      buttons.appendChild(yes);
      li.appendChild(buttons);
      const said = _el('p', 'wf-check-said');
      said.setAttribute('role', 'status');
      li.appendChild(said);
      ul.appendChild(li);
      C.rows.set(st.id, { li, plan, buttons, said, done: false, label: st.label });
    }
    box.appendChild(ul);
    const foot = _el('div', 'wf-check-foot');
    box.appendChild(foot);
    C.box = box;
    R.checking = C;

    function left() { return [...C.rows.entries()].filter(([, r]) => !r.done).map(([id]) => id); }
    function drawFoot() {
      const n = left().length;
      lede.textContent = n
        ? `${n} step${n === 1 ? '' : 's'} nobody has checked yet. Read what each would do, then press Looks right — `
          + 'or open it and change it, which makes it yours.'
        : 'Every step is checked.';
      const kids = [];
      if (n) {
        const allYes = _button('wf-check-all', 'All look right');
        allYes.addEventListener('click', () => checkThese(left()));
        kids.push(allYes);
      } else {
        const on = _button('wf-check-switch', 'Switch on');
        on.addEventListener('click', () => { closeCheck(); toggleSwitch(true); });
        kids.push(on);
      }
      const close = _button('wf-check-close', 'Close');
      close.addEventListener('click', () => closeCheck(true));
      kids.push(close);
      foot.replaceChildren(...kids);
    }

    async function checkThese(list) {
      const todo = list.filter((id) => C.rows.has(id) && !C.rows.get(id).done);
      if (!todo.length) return;
      for (const id of todo) { C.rows.get(id).buttons.querySelectorAll('button').forEach((b) => { b.disabled = true; }); }
      const r = await w.source.checkSteps(todo);
      if (!C.alive || R.destroyed || R.wf !== w) return;
      if (!r || r.ok === false) {
        for (const id of todo) {
          const row = C.rows.get(id);
          row.buttons.querySelectorAll('button').forEach((b) => { b.disabled = false; });
          row.said.textContent = `Not checked: ${_sentence(r, 'the server refused').replace(/\.$/, '')}.`;
        }
        return;
      }
      for (const id of todo) {
        const row = C.rows.get(id);
        row.done = true;
        row.li.dataset.checked = 'true';
        row.buttons.remove();
        row.said.textContent = 'Checked.';
      }
      if (w.canvas) await w.canvas.reload();
      if (!C.alive || R.destroyed || R.wf !== w) return;
      drawFoot();
      if (!left().length) {
        const on = foot.querySelector('.wf-check-switch');
        if (on) on.focus();
      }
    }

    drawFoot();
    view.insertBefore(box, viewing);
    C.release = holdEscape(() => { if (R.checking === C) { R.checking = null; C.alive = false; box.remove(); switchBtn.focus(); } });
    const first = box.querySelector('.wf-check-yes') || box.querySelector('button');
    if (first) first.focus();

    // What each would do: the saved version's dry-run plan, once.
    if (typeof w.source.planLines === 'function') {
      w.source.planLines().then((p) => {
        if (!C.alive) return;
        for (const [id, row] of C.rows) {
          if (!p || p.ok === false) {
            row.plan.replaceChildren(_el('li', 'wf-check-wait',
              `It could not be planned: ${_sentence(p, 'no answer').replace(/\.$/, '')}.`));
            continue;
          }
          const lines = p.plans.get(id);
          if (!lines) {
            row.plan.replaceChildren(_el('li', 'wf-check-wait', p.declined
              ? `It cannot be planned yet: ${String(p.declined).replace(/\.$/, '')}.` : 'The plan did not reach this step.'));
            continue;
          }
          row.plan.replaceChildren(...(lines.length ? lines : ['It would do nothing.']).map((l) => _el('li', null, l)));
        }
      });
    }
  }

  // ── a fix, its undo, and the file (`P22-20`, `P22-24`) ───────────────────
  /** `P22-20`. *Apply*: the proposal on the document (C-A's fix route, with
   *  the version it was proposed on), saved as a new version. */
  async function applyFix(proposal) {
    const w = R.wf;
    if (!w || !w.source || typeof w.source.fix !== 'function' || !proposal) {
      return { ok: false, sentence: 'The workflow is not open, so nothing was applied.' };
    }
    const r = await w.source.fix(proposal.node_id, { config: proposal.config, baseVersion: proposal.base_version });
    if (R.destroyed || R.wf !== w || !r || r.ok === false) return r;
    if (w.canvas) await w.canvas.reload();
    justSaved = true;
    syncBar();
    refreshShelf();
    return { ok: true, undoVersion: r.undoVersion, version: r.version,
      sentence: r.version != null ? `Applied as version ${r.version}.` : 'Applied.' };
  }

  /** `P22-20`. *Undo*: the version the fix was made on, put back
   *  (`restoreVersion`, source `restored`) — nothing is lost. */
  async function undoFix(version) {
    const w = R.wf;
    if (!w || !w.source) return { ok: false, sentence: 'The workflow is not open, so nothing was undone.' };
    const r = await w.source.restoreVersion(version);
    if (R.destroyed || R.wf !== w || !r || r.ok === false) return r;
    if (w.canvas) await w.canvas.reload();
    justSaved = true;
    syncBar();
    refreshShelf();
    const doc = docOf(w.source);
    return { ok: true, sentence: `Undone: version ${version} is back`
      + `${doc && doc.version != null ? `, saved as version ${doc.version}` : ''}. The fix is still in Versions….` };
  }

  /** `P22-24`. *Export*: the saved workflow, downloaded as a file. */
  async function exportIt() {
    const w = R.wf;
    if (!w || !w.source || typeof w.source.exportFile !== 'function') return;
    exportBtn.disabled = true;
    let r = null;
    try { r = await w.source.exportFile(); } catch (e) { r = { ok: false, sentence: _sentence(e, '') }; }
    if (R.destroyed || R.wf !== w) return;
    exportBtn.disabled = false;
    if (!r || r.ok === false) {
      say(`Not exported: ${_sentence(r, 'the server refused')}`, { refusal: true });
      return;
    }
    try {
      _download(r.blob, r.filename);
    } catch (e) {
      say(`Not downloaded: ${_sentence(e, 'the browser refused')}`, { refusal: true });
      return;
    }
    say(`Downloaded “${r.filename}”. ${EXPORT_WORDS}${r.unsaved ? ' Your unsaved changes are not in it.' : ''}`);
  }

  async function makeNew() {
    if (!R.api || R.making) return;
    const name = newName.value.trim();
    // `P23-06` (WB-M-8). *Make it* with the box empty made "New workflow" at
    // once — scheduled daily at 09:00 and listed on the shelf, on the canvas
    // and in Tasks — with nothing asking for a name.
    if (!name) {
      shelfNote.textContent = 'Give it a name first.';
      if (typeof newName.focus === 'function') newName.focus();
      return;
    }
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
  draftGo.addEventListener('click', () => draftIt());
  fileBtn.addEventListener('click', () => { if (typeof fileInput.click === 'function') fileInput.click(); });
  fileInput.addEventListener('change', () => openFile());
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
  /** `P22-17` (wf-canvas). Open workflow `workflowId` on its run `runId` —
   *  the notification's *Open the run*: Runs, that run, drawn and opened on
   *  the step it waits on. */
  async function openRunOf(workflowId, runId) {
    if (workflowId == null) return false;
    const go = async () => {
      if (!(R.view === 'workflow' && R.wf && R.wf.id === String(workflowId))) {
        const ok = await showWorkflow(workflowId);
        if (!ok) return false;
      }
      const w = R.wf;
      if (!w) return false;
      setTab('runs', { quiet: true });
      if (runId == null) { await loadRuns(); return true; }
      w.runId = String(runId);
      await loadRuns();
      if (R.wf === w && (!w.runCanvas || w.runId !== String(runId))) await openRun(runId);
      return true;
    };
    if (R.view === 'workflow' && R.wf && R.wf.id === String(workflowId)) return go();
    let result = false;
    const ran = guardLeave(() => { result = go(); });
    return ran ? result : false;
  }

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
    stopWatchingShelf();
    closeNewForm();
    closeCheck();
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
      const ok = opts.runId != null ? await openRunOf(opts.workflowId, opts.runId) : await showWorkflow(opts.workflowId);
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
    openRun: (workflowId, runId) => openRunOf(workflowId, runId),
    canClose,
    destroy,
    /** `B1136`. The Workbench shows this room again (`workbench.js`
     *  `_showRoom`), perhaps after an Integration, an MCP server or a skill
     *  was added in another room through a step's door: the open document's
     *  palette is read again, and the open step offers what was added. */
    shown: () => {
      const src = !R.destroyed && R.wf && R.wf.source;
      return src && typeof src.reloadPalette === 'function'
        ? src.reloadPalette().catch(() => null) : Promise.resolve(null);
    },
    /** The canvas on screen (tests and the glue's Escape reach the room
     *  through its handle). */
    canvas: () => activeCanvas(),
  };
}

export default {
  SHELF_WATCH_MS, mountAutomations, runWords, isDryRun, isOn, OFF_WORDS, ON_WORDS, EXAMPLES_MAX, ARRIVED_WORDS, ARRIVED_LEDE, EXPORT_WORDS,
};
