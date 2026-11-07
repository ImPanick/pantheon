// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/canvas.js
//
// `P22-02`. The Workbench's first room, *Automations*: every task is a step on
// a canvas and every chain edge is an arrow between two steps, drawn from the
// `{ tasks, graph }` that `GET /api/tasks` has served since `P8-26` — the same
// door the Tasks window reads, asked for the last run too (`include_last_run`,
// a parameter the route already takes). No new route: `check-unreachable.py`
// is at its ceiling, and the graph is already on the wire.
//
// **What a person does here.** Each step has two ports on its right edge,
// *if it works* and *if it fails* — `workflowDiagram.js:EDGE_WORDS`, the words
// the Mermaid diagram puts on its arrows, so the control that makes an edge and
// the arrow it draws are one vocabulary (`B873` set that rule for the form).
// Dragging from a port to another step writes the edge through the EXISTING
// `PUT /api/tasks/{id}` with exactly one of `then_task_id` / `else_task_id`
// (`EDGE_COLUMNS`); the server decides whether it may (`P22-01`), and when it
// says no, the sentence it answered with is what the canvas shows. Nothing
// here second-guesses that rule — one rule, checked in one place (`Law 7`).
//
// **The keyboard path is a peer, not an afterthought.** The canvas is one tab
// stop and the arrow keys go from step to step and along the arrows
// (`B1048`); a step's *Connect…* button picks the outcome and the next step by
// name from two `<select>`s; M picks a step up and the arrow keys then move it
// by the window system's own step (`windowDrag.js:KEY_STEP`); an arrow is
// focusable too, and Delete removes it only after saying which arrow it is. Escape goes through `escMenuStack.js`,
// so it closes the innermost thing — the picker, the pending removal, the side
// panel — before `ui.js`'s arbiter closes the window; while one is open the
// room carries `data-esc-layer`, which is what makes the arbiter ask the stack
// first when the pointer is on the window (`B1052`, `holdEscape`).
//
// **Every word a person wrote is set as text.** Task names reach the page
// through `textContent` and attribute values only — never `innerHTML` — which
// is the property `P22`'s preamble weighed Drawflow on and found it lacked.
// One markup assignment exists, and its markup is not data's: a step's full
// dry-run plan is drawn by the Tasks card's own step renderer
// (`tasks.js:renderRunSteps`), which escapes every value with `ui.js:esc`
// (`P22-04`, so a plan is worded one way, `Law 7`).
//
// **A step's last outcome is a shape and a weight before it is a colour**
// (`P8-34`'s rule for sixteen palettes): a mark (✓ ✗ … · ○), the shared word
// (`runStatus.js:runStatusLabel`) and the border's style and width, read off
// `data-outcome`. Hue is only ever a third signal on top of those two.
//
// **The side panel is not drawn here.** Selecting a step mounts the task form
// through an injected `mountPanel` with the `P22` panel contract
// (`{ task, tasks, onSaved, onCancel }` → `{ destroy() }`); the glue module
// (`workbench.js`) hands in `tasks/taskFields.js:mountTaskFields`, so there is
// one form (`Law 7`) and this module is testable without it.
//
// **Where a step sits is the person's, and kept per person** — for a task,
// through the preferences door (`taskSource.js:POSITIONS_PREF`); for a step of
// a workflow document, inside the document.
//
// **What it draws is a source's (`P22-05`, wf-ui).** Slice B draws a workflow
// document on this same canvas — one canvas, not a second (`Law 14`) — so the
// canvas no longer knows what a task is. Everything it reads and writes goes
// through a SOURCE, the contract the design names C3
// (`/work/notes/SLICE-B-DESIGN.md` § 6.3, § 7):
//
//   { readOnly, words: { region, emptyTitle, emptyText, hint, newLabel },
//     load() → { items: [{ id, name, kind, sub, paused, outcome: { tone, word },
//                          ports, marks, accepts, missing }],
//                edges: [{ from, to, when, label?, fixed? }] },
//     connect(from, when, to) / disconnect(from, when, to) → { ok, sentence? },
//     loadPositions(), savePositions(map),
//     openPanel(host, item, { onSaved, onCancel }) → { destroy },
//     newItem?(anchor) → Promise<id|null>, removeItem?(id) → { ok, sentence? },
//     dryRun?() → { ok, sentence?, plans: Map<id, { steps, declined, when, depth }> } }
//
// `opts.source` is that object; without one the canvas makes today's
// (`taskSource.js:createTaskSource(opts)`), so every caller and test of
// `P22-02`'s canvas is unchanged. What the canvas adds for a document, and
// draws only when a source asks: an item with no `ports` (a workflow's start),
// an arrow that is `fixed` (the start's, which cannot be removed) or carries
// its own `label`, an item's `marks` as text badges ("Sample pinned"), a
// `readOnly` source (a run: no ports, no Connect…, no Delete, no New, no
// moving), a step removed by Delete pressed twice (`removeItem`, said first,
// done second — the arrows' rule), and the palette behind *New step*
// (`newItem`). Optional keys only this branch's sources use are named where
// they are read (`idKey`, `dryRunFrom`, `openItem`, `offer`, `item.fixed`,
// `item.builtin`, `words.*` beyond the five).
//
// **Named ports, fan-out and the start's port (`P22-10`, `P22-11`, wf-canvas;
// `/work/notes/SLICE-CD-DESIGN.md` § 3's JS contract).** A step of a workflow
// document may leave by ports of its own — an If's *if so* / *otherwise*, a
// Switch's one per case — so an item's `ports` are drawn one per row down its
// right edge, each with its own words (`item.portWords[port]`, falling back to
// `EDGE_WORDS` and then to the port itself), and the step is as tall as its
// ports need (`graphLayout.js:nodeHeight`); every arrow leaves from its own
// port (`portPoint(pos, when, ports)`). A source with `fanOut` keeps several
// arrows on one port: *Connect…* and a drag ADD an arrow there instead of
// moving the one that was. An item marked `entry` is where a run starts (a
// workflow's start, which since `P22-11` has one port, *starts*, and real
// arrows); its arrows read "When it starts, … runs.". With none of these keys
// a source is drawn exactly as `P22-02`'s and `P22-05`'s were.

import {
  layoutGraph, boundsOf, portPoint, portOffset, edgePath, edgeRoute,
  arrowPath, nodeAt, clampZoom, fitView, nodeHeight, NODE_W, NODE_H, PORTS, NARROW_FIT_WIDTH,
} from './graphLayout.js';
import { EDGE_WORDS, KIND_WORDS, componentOf } from '../tasks/workflowDiagram.js';
import { computeSnap } from '../editor/snap.js';
import { registerMenuDismiss } from '../escMenuStack.js';
import { KEY_STEP, MOVE_THRESHOLD } from '../windowDrag.js';
import { createTaskSource, outcomeOf, POSITIONS_PREF, TASKS_URL } from './taskSource.js';
// `P22-05`, design § 6.3: the one reading of a refusal lives in `refusal.js`.
import { refusalText } from './refusal.js';
// `B1833`. Each kind's glyph and family, drawn on the step's face.
import { kindIcon, kindCat } from './kindIcons.js';

// Re-exported: `P22-02`'s callers and tests read them from here.
export { refusalText, outcomeOf, POSITIONS_PREF, TASKS_URL };

const SVG_NS = 'http://www.w3.org/2000/svg';
const SAVE_DELAY_MS = 400;
/** How long after a drag ends the click a browser fires for it is ignored. */
const SWALLOW_MS = 400;
const ZOOM_STEP = 1.2;
/** `B1833`. The smallest zoom a drawing first opens at on a canvas wider than
 *  `NARROW_FIT_WIDTH`: a 232 px step's 13 px name still reads at 75 %. */
const OPEN_FLOOR = 0.75;
/** `.wb-connect`'s width in the sheet, so the picker can be kept on the stage. */
const CONNECT_W = 260;
/** `P22-04`. The Tasks card's words for the dry run (`tasks.js`), on purpose. */
const DRY_LABEL = 'Show me what this would do';
/** `.wb-plan-box`'s width in the sheet. */
const PLAN_W = 320;
/** The mark beside a step's line in a plan, by what the plan says of it. */
const PLAN_MARKS = { planned: '→', cannot: '?', declined: '⊘', aside: '–' };
/**
 * `B1066`. What a step says when the plan's verdict for it is `cannot`
 * (`DRY_CANNOT`: the two actions a dry run cannot describe,
 * `DRY_UNCOVERABLE_ACTIONS`). The verdict is served on each plan entry as
 * `dry` (`action_dry_verdict`); this was found by matching `dry_run_plan`'s
 * sentence in the plan's lines, so rewording it there made those steps say
 * what the action would run instead. The plan box still shows the server's
 * whole explanation.
 */
const DRY_CANNOT = 'cannot';
const CANNOT_SAY = 'A dry run cannot tell you what this would change.';
/** `B1083`. How far inside the canvas's edge a step opened beside its panel
 *  is kept (px on screen). */
const KEEP_MARGIN = 16;
const KEY_DIRS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
/** The mark beside a step's last-run word, by `runStatusTone`. `none` is a
 *  step that has not run. */
const OUTCOME_MARKS = { ok: '✓', error: '✗', pending: '…', info: '·', none: '○' };

function _cap(s) {
  const t = String(s || '');
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** "a", "a and b", "a, b and c" — at most four named, then "and N more". */
function _listWords(list) {
  const l = (list || []).map(String);
  if (l.length > 4) return `${l.slice(0, 3).join(', ')} and ${l.length - 3} more`;
  if (l.length < 2) return l[0] || '';
  return `${l.slice(0, -1).join(', ')} and ${l[l.length - 1]}`;
}

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

// SVG nodes take their class as an attribute: `className` on an SVG element is
// a read-only `SVGAnimatedString`, and assigning it throws in a module.
function _svg(tag, cls) {
  const n = document.createElementNS(SVG_NS, tag);
  if (cls) n.setAttribute('class', cls);
  return n;
}

/** Neutral words for a source that does not say its own. The task source says
 *  every one of these (`taskSource.js:TASK_WORDS`), so nothing here is what the
 *  tasks canvas has ever said. */
const DEFAULT_WORDS = Object.freeze({
  region: 'Steps',
  emptyTitle: 'Nothing here yet.',
  emptyTitleOwn: '',
  emptyText: '',
  hint: '',
  hintKeys: '',
  newLabel: 'New step',
  newTitle: '',
  unknownName: 'a step you cannot see',
  missingTitle: 'A step you cannot see',
  missingSub: '',
  loadFailed: 'This could not be loaded. Close the Workbench and open it again to retry.',
});
/** The key a new step's request is held under while the person is asked
 *  (`B1067`); no item id is the empty string. */
const NEW_KEY = '\u0000new';

/** A position map from a source: a `Map` or a plain object, each value
 *  `{ x, y }` or `[x, y]`. Anything unreadable is left out. */
function _points(value) {
  const out = new Map();
  if (!value) return out;
  const entries = value instanceof Map ? value.entries() : Object.entries(value);
  for (const [id, p] of entries) {
    const x = Number(Array.isArray(p) ? p[0] : p && p.x);
    const y = Number(Array.isArray(p) ? p[1] : p && p.y);
    if (Number.isFinite(x) && Number.isFinite(y)) out.set(String(id), { x, y });
  }
  return out;
}

/** The words of a refusal a source threw rather than answered. */
function _thrown(err) {
  return String((err && (err.sentence || err.message)) || '').trim();
}

/**
 * Draw a canvas into `root`.
 *
 * `opts.source` — what to draw (the C3 contract above). Without it:
 *   `createTaskSource(opts)`, whose options are `opts.mountPanel` (the `P22`
 *   panel contract, `mountTaskFields`), `opts.fetch` (defaults to the page's
 *   `fetch`; injected so a test sees every request), `opts.describeTrigger(task)`
 *   (the Tasks window's schedule words), `opts.openWorkflow` and
 *   `opts.onMakeWorkflow` (the room's two doors from a task to a workflow).
 * `opts.renderSteps` — `tasks.js:renderRunSteps`, for a step's full plan.
 * `opts.focusId` — open on the workflow this item is part of.
 *
 * Returns `{ ready, reload, focusChain, select, destroy, flush, say, newStep,
 * dryRun, items, current, isDirty }`; `ready` settles once the first drawing
 * is on the page.
 */
export function mountCanvas(root, opts = {}) {
  const src = opts.source || createTaskSource(opts);
  // `P22-04`. `tasks.js:renderRunSteps`, the Tasks card's step renderer,
  // handed in by the glue so a step's full plan is drawn the one way.
  const renderSteps = typeof opts.renderSteps === 'function' ? opts.renderSteps : null;
  const word = (k) => {
    const w = src.words && src.words[k];
    return w != null && w !== '' ? String(w) : DEFAULT_WORDS[k];
  };
  // Read each time: a source can become read-only (a version being looked at).
  const ro = () => !!src.readOnly;

  const S = {
    items: [], byId: new Map(), graph: { nodes: [], edges: [] },
    pos: new Map(), pinned: new Map(), missing: new Set(), order: [],
    nodeEls: new Map(), edgeEls: [],
    view: { x: 0, y: 0, zoom: 1 }, viewed: false, loaded: false, destroyed: false,
    // `P23-06`: the bounds the view was last fitted to, until the person
    // pans or zooms; the viewport's observer fits them again when it resizes.
    fitted: null, fitSize: null, resizeObs: null,
    focusId: opts.focusId != null ? String(opts.focusId) : null,
    selected: null, panel: null, connect: null,
    drag: null, link: null, pan: null, pinch: null, beside: null, swallow: null,
    pending: null, sayRun: null, saveTimer: null,
    plan: null, planBox: null, dryBusy: false,
    // `B1048`.
    showBuiltins: false, reveal: new Set(), hidden: new Set(), current: null, moving: null,
    // `B1841`. The steps picked together (Shift-click, a box, Ctrl+A), apart
    // from the one whose panel is open (`selected`); the box being drawn; the
    // right-click menu and the keys sheet, when open.
    sel: new Set(), selEsc: null, box: null, menu: null, keys: null,
  };

  // ── the skeleton ─────────────────────────────────────────────────────────
  root.classList.add('wb-room');
  const toolbar = _el('div', 'wb-toolbar');
  const newBtn = _el('button', 'wb-tool wb-tool-new', word('newLabel'));
  newBtn.type = 'button';
  if (word('newTitle')) newBtn.title = word('newTitle');
  const tidyBtn = _el('button', 'wb-tool', 'Tidy up');
  tidyBtn.type = 'button';
  tidyBtn.title = 'Forget where steps were moved and lay everything out again';
  const spacer = _el('span', 'wb-toolbar-spacer');
  // `B1839`. Undo and Redo, for a source that keeps a history (a workflow's
  // draft): every edit — a step, an arrow, a move, Tidy up — goes back.
  const undoBtn = _el('button', 'wb-tool wb-tool-icon wb-tool-undo', '↶');
  undoBtn.type = 'button';
  undoBtn.setAttribute('aria-label', 'Undo');
  undoBtn.title = 'Undo (Ctrl+Z)';
  const redoBtn = _el('button', 'wb-tool wb-tool-icon wb-tool-redo', '↷');
  redoBtn.type = 'button';
  redoBtn.setAttribute('aria-label', 'Redo');
  redoBtn.title = 'Redo (Ctrl+Shift+Z)';
  const keysBtn = _el('button', 'wb-tool wb-tool-icon wb-tool-keys', '?');
  keysBtn.type = 'button';
  keysBtn.setAttribute('aria-label', 'Keyboard shortcuts');
  keysBtn.title = 'Keyboard shortcuts (?)';
  const outBtn = _el('button', 'wb-tool wb-tool-icon', '−');
  outBtn.type = 'button';
  outBtn.setAttribute('aria-label', 'Zoom out');
  outBtn.title = 'Zoom out (−)';
  const zoomWord = _el('span', 'wb-zoom', '100%');
  zoomWord.setAttribute('aria-live', 'off');
  const inBtn = _el('button', 'wb-tool wb-tool-icon', '+');
  inBtn.type = 'button';
  inBtn.setAttribute('aria-label', 'Zoom in');
  inBtn.title = 'Zoom in (+)';
  const fitBtn = _el('button', 'wb-tool', 'Fit');
  fitBtn.type = 'button';
  fitBtn.title = 'Show every step (0)';
  // `B1048`. The housekeeping tasks every install comes with are not the
  // person's, and on a fresh install they were the whole first view. Set
  // aside until asked for, by a switch that says what they are — the word the
  // Tasks card puts on them, "built-in". Drawn only for a source whose items
  // say `builtin` (the tasks canvas's).
  const builtinsSwitch = _el('label', 'wb-tool-switch');
  builtinsSwitch.title = 'Pantheon’s own housekeeping tasks.';
  const builtinsBox = _el('input', 'wb-tool-switch-box');
  builtinsBox.type = 'checkbox';
  const builtinsWord = _el('span', 'wb-tool-switch-word', 'Show built-in tasks');
  builtinsSwitch.appendChild(builtinsBox);
  builtinsSwitch.appendChild(builtinsWord);
  builtinsSwitch.hidden = true;
  // The zoom controls wrap as one group: at phone width they split across two
  // rows, "−" on one and "52% + Fit" on the next (seen at 390px).
  const zoomGroup = _el('span', 'wb-toolbar-zoom');
  for (const n of [outBtn, zoomWord, inBtn, fitBtn]) zoomGroup.appendChild(n);
  // `B1833`. The view's controls float on the canvas's lower-left corner —
  // where a node editor keeps them, so the bar above holds what a person
  // does to the workflow, not to the view — with *Tidy up* beside them and
  // the map's switch. The bar keeps *New* and the built-ins switch.
  const mapBtn = _el('button', 'wb-tool wb-tool-map', 'Map');
  mapBtn.type = 'button';
  mapBtn.title = 'Show or hide the map of the whole canvas';
  mapBtn.setAttribute('aria-pressed', 'false');
  const dock = _el('div', 'wb-dock');
  dock.setAttribute('role', 'toolbar');
  dock.setAttribute('aria-label', 'View');
  for (const n of [zoomGroup, tidyBtn, mapBtn, keysBtn]) dock.appendChild(n);
  for (const n of [newBtn, undoBtn, redoBtn, builtinsSwitch, spacer]) toolbar.appendChild(n);
  // Drawn only for a source that keeps a history.
  undoBtn.hidden = typeof src.undo !== 'function';
  redoBtn.hidden = typeof src.redo !== 'function';

  const hint = _el('p', 'wb-hint', word('hint'));
  hint.hidden = !word('hint');
  if (word('hintKeys')) hint.title = word('hintKeys');   // `P23-05`: the keys, behind the one line

  const sayBox = _el('div', 'wb-say');
  const sayText = _el('span', 'wb-say-text');
  sayText.setAttribute('role', 'status');
  sayText.setAttribute('aria-live', 'polite');
  const sayAction = _el('button', 'wb-say-action');
  sayAction.type = 'button';
  sayAction.hidden = true;
  sayBox.appendChild(sayText);
  sayBox.appendChild(sayAction);

  const stage = _el('div', 'wb-stage');
  const viewport = _el('div', 'wb-viewport');
  viewport.setAttribute('role', 'region');
  viewport.setAttribute('aria-label', word('region'));
  // Focusable by a click on the empty canvas (not a Tab stop: the steps are),
  // so the canvas's keys — Ctrl+Z, Ctrl+V, ?, the zoom keys — reach it then.
  viewport.setAttribute('tabindex', '-1');
  const world = _el('div', 'wb-world');
  const nodesLayer = _el('div', 'wb-nodes');
  const svgEl = _svg('svg', 'wb-edges');
  const edgeLayer = _svg('g', 'wb-edge-layer');
  const ghost = _svg('path', 'wb-edge-ghost');
  const guides = _svg('g', 'wb-guides');
  svgEl.appendChild(edgeLayer);
  svgEl.appendChild(ghost);
  svgEl.appendChild(guides);
  // Steps first, so Tab reaches every step before any arrow; the stylesheet
  // draws the arrows underneath.
  world.appendChild(nodesLayer);
  world.appendChild(svgEl);
  viewport.appendChild(world);

  const empty = _el('div', 'wb-empty');
  const emptyTitle = _el('p', 'wb-empty-title', word('emptyTitle'));
  empty.appendChild(emptyTitle);
  const emptyText = _el('p', 'wb-empty-text', word('emptyText'));
  emptyText.hidden = !word('emptyText');
  empty.appendChild(emptyText);
  const emptyBuiltins = _el('p', 'wb-empty-text wb-empty-builtins',
    'Pantheon’s built-in tasks are hidden here. “Show built-in tasks” above shows them.');
  emptyBuiltins.hidden = true;
  empty.appendChild(emptyBuiltins);
  const emptyNew = _el('button', 'wb-tool wb-tool-new', word('newLabel'));
  emptyNew.type = 'button';
  empty.appendChild(emptyNew);
  empty.hidden = true;
  viewport.appendChild(empty);

  const panel = _el('aside', 'wb-panel');
  panel.setAttribute('aria-label', 'Step');
  panel.hidden = true;
  const panelHead = _el('div', 'wb-panel-head');
  const panelTitle = _el('h3', 'wb-panel-title');
  // `P22-04`. The question the Tasks card asks, on the step that is open — the
  // same words, so a person who met it on the card knows it here. A source
  // that plans from a step (`dryRunFrom: 'item'`, the tasks canvas) has it; a
  // workflow is planned whole, from the room's toolbar.
  const panelDry = _el('button', 'wb-panel-dry', DRY_LABEL);
  panelDry.type = 'button';
  panelDry.title = 'Plans a run of this step and every step after it, and shows the plan on the canvas. Nothing runs and nothing changes.';
  panelDry.hidden = true;
  // A step a source can remove, from the panel too — the mouse's way to what
  // Delete pressed twice does on the canvas.
  const panelRemove = _el('button', 'wb-panel-remove', 'Remove step');
  panelRemove.type = 'button';
  panelRemove.hidden = true;
  const panelClose = _el('button', 'wb-panel-close', 'Close');
  panelClose.type = 'button';
  panelHead.appendChild(panelTitle);
  panelHead.appendChild(panelDry);
  panelHead.appendChild(panelClose);
  const panelBody = _el('div', 'wb-panel-body');
  // `P23-06` (WB-U-13). *Remove step* sat in the head beside *Close* — the
  // destructive button one slip from the one that only shuts the panel. It
  // is under the form now, where it is read last.
  const panelFoot = _el('div', 'wb-panel-foot');
  panelFoot.appendChild(panelRemove);
  panel.appendChild(panelHead);
  panel.appendChild(panelBody);
  panel.appendChild(panelFoot);

  // `B1833`. The map: every step as a block in its family's colour and the
  // part of the canvas on show as a frame. Pressing or dragging on it moves
  // the view there. A pointer's aid — the keyboard has the arrow keys, Fit
  // and the zoom keys — so it is hidden from assistive technology.
  const map = _el('div', 'wb-minimap');
  map.setAttribute('aria-hidden', 'true');
  const mapSvg = _svg('svg', 'wb-minimap-svg');
  const mapNodes = _svg('g', 'wb-minimap-nodes');
  const mapFrame = _svg('rect', 'wb-minimap-frame');
  mapSvg.appendChild(mapNodes);
  mapSvg.appendChild(mapFrame);
  map.appendChild(mapSvg);
  map.hidden = true;

  // Both float on the viewport, so a step's panel opening beside the canvas
  // never covers them.
  viewport.appendChild(dock);
  viewport.appendChild(map);
  stage.appendChild(viewport);
  stage.appendChild(panel);
  for (const n of [toolbar, hint, sayBox, stage]) root.appendChild(n);

  // ── words ────────────────────────────────────────────────────────────────
  const nameOf = (id) => {
    const it = S.byId.get(String(id));
    return it && !it.missing ? String(it.name) : word('unknownName');
  };
  /** `P22-10`. The words on port `when` of item `id`: the item's own
   *  (`portWords` — an If's "if so", a Switch case's label), else the two every
   *  task has (`EDGE_WORDS`), else the port as it is stored. */
  const portWord = (id, when) => {
    const it = S.byId.get(String(id));
    const own = it && it.portWords && typeof it.portWords === 'object' ? it.portWords[String(when)] : null;
    return own != null && own !== '' ? String(own) : (EDGE_WORDS[when] || String(when));
  };
  /** Whether arrows from `id` start a run (a workflow's start, `entry`). */
  const isEntry = (id) => { const it = S.byId.get(String(id)); return !!(it && it.entry); };
  /** `P22-11`. A source that keeps several arrows on one port. */
  const fan = () => !!src.fanOut;
  /** `B1833`. Whether a step can be added straight after a port (the source
   *  connects it as it adds it: `newItem(anchor, { from, when })`). */
  const canAddAfter = () => !ro() && typeof src.newItem === 'function' && !!src.addsAfter;
  /** Whether any arrow leaves `from` by `when`. */
  const hasEdge = (from, when) => (S.graph.edges || []).some((e) => String(e.from) === String(from)
    && String(e.when) === String(when));
  const edgeOf = (from, when, to) => (S.graph.edges || []).find((e) => e.from === String(from)
    && e.when === String(when) && e.to === String(to)) || null;
  const edgeSentence = (from, when, to) => {
    // `P22-11`. An arrow from where a run starts: with fan-out several steps
    // may run when it starts, so none of them is "first".
    if (isEntry(from)) return `When it starts, ${nameOf(to)} runs.`;
    const e = edgeOf(from, when, to);
    // A fixed arrow with words of its own is a workflow's start: it always
    // leads to the step that goes first.
    if (e && e.fixed && e.label) return `${nameOf(to)} runs first.`;
    return `After ${nameOf(from)}, ${portWord(from, when)}, ${nameOf(to)} runs.`;
  };

  function say(text, { refusal = false, action = null } = {}) {
    sayText.textContent = text || '';
    sayBox.classList.toggle('wb-say-refusal', !!refusal);
    sayBox.dataset.tone = refusal ? 'refusal' : 'info';
    if (action) {
      sayAction.textContent = action.label;
      sayAction.hidden = false;
      S.sayRun = action.run;
    } else {
      sayAction.textContent = '';
      sayAction.hidden = true;
      S.sayRun = null;
    }
  }
  sayAction.addEventListener('click', () => { const run = S.sayRun; if (run) run(); });

  // ── Escape ───────────────────────────────────────────────────────────────
  // `B1052`. Everything this room opens over itself — the step panel, the
  // Connect… picker, an arrow being drawn, a removal waiting for its second
  // Delete — is a layer on `escMenuStack.js`, so Escape closes the innermost
  // thing first. `ui.js`'s arbiter closes the window under the pointer BEFORE
  // it asks that stack, and a mouse user's pointer is on the window they just
  // clicked in: measured on the merged tree, one Escape took the Workbench and
  // an unsaved step form with it. So while any layer is open the room says so
  // — `data-esc-layer` on its root — and the arbiter asks the stack first for
  // a window holding one. Every layer is registered through here, so the mark
  // and the stack cannot disagree.
  let escHeld = 0;
  function holdEscape(dismiss) {
    let released = false;
    let unregister = () => {};
    const release = () => {
      if (released) return;
      released = true;
      unregister();
      escHeld = Math.max(0, escHeld - 1);
      if (!escHeld) delete root.dataset.escLayer;
    };
    unregister = registerMenuDismiss(() => { release(); dismiss(); });
    escHeld += 1;
    root.dataset.escLayer = 'open';
    return release;
  }

  // ── the source ───────────────────────────────────────────────────────────
  async function savePositions() {
    if (S.saveTimer) { clearTimeout(S.saveTimer); S.saveTimer = null; }
    if (ro()) return;
    const map = new Map();
    for (const [id, p] of S.pinned) {
      if (S.byId.has(id)) map.set(id, { x: Math.round(p.x), y: Math.round(p.y) });
    }
    let res;
    try { res = await src.savePositions(map); } catch (_) { res = { ok: false }; }
    if (res && res.ok === false) {
      say('Where the steps sit could not be saved; they will be laid out again next time.', { refusal: true });
    }
  }

  function scheduleSave() {
    if (S.saveTimer) clearTimeout(S.saveTimer);
    S.saveTimer = setTimeout(() => { S.saveTimer = null; savePositions(); }, SAVE_DELAY_MS);
  }

  function take(data) {
    S.items = (Array.isArray(data && data.items) ? data.items : [])
      .filter((i) => i && i.id != null)
      .map((i) => ({ ...i, id: String(i.id), name: String(i.name == null ? '' : i.name) }));
    S.byId = new Map(S.items.map((i) => [i.id, i]));
    S.graph = {
      // An item a source says is missing is drawn as the far end of an arrow,
      // the way a dangling edge's target always was: not a node of the graph.
      nodes: S.items.filter((i) => !i.missing).map((i) => ({ id: i.id, name: i.name })),
      edges: (Array.isArray(data && data.edges) ? data.edges : [])
        .filter((e) => e && e.from != null && e.to != null)
        .map((e) => ({ ...e, from: String(e.from), to: String(e.to), when: String(e.when || '') })),
    };
  }

  async function reload() {
    let data;
    try {
      data = await src.load();
    } catch (_) {
      say(word('loadFailed'), { refusal: true });
      return false;
    }
    if (S.destroyed) return false;
    // A plan was of the steps as they were; after a change it may not be.
    dropPlan();
    take(data);
    render();
    applyFocusChain();
    return true;
  }

  /**
   * `B1095`. Each step's last-run mark, read again from the source (its
   * optional `outcomes()`) and redrawn where it moved — the plan, the open
   * panel, where the steps sit and the person's view are left as they are.
   * Measured: with the Workbench open on *Tasks and chains*, two tasks ran
   * and failed and both boxes still read "○ Not run yet" until the window was
   * opened again; this canvas never asked again. Waits (`deferred`) while a
   * step or an arrow is being dragged or moved, so a redraw cannot take the
   * thing in the person's hand. Answers `{ changed, active, deferred }`:
   * `active` while any step's run is queued or running.
   */
  async function refreshOutcomes() {
    const none = { changed: 0, active: false, deferred: false };
    if (S.destroyed || typeof src.outcomes !== 'function') return none;
    if (S.drag || S.link || S.pan || S.pinch || S.connect || S.moving) return { ...none, deferred: true };
    let next;
    try { next = await src.outcomes(); } catch (_) { return none; }
    if (S.destroyed || !(next instanceof Map)) return none;
    if (S.drag || S.link || S.pan || S.pinch || S.connect || S.moving) return { ...none, deferred: true };
    let changed = 0;
    let active = false;
    for (const it of S.items) {
      const o = next.get(it.id);
      if (!o) continue;
      if (o.active) active = true;
      const was = it.outcome || {};
      // `B1837`. The ports a run's step left by move with it.
      const tookMoved = Array.isArray(o.took) && String(o.took) !== String(it.took || '');
      if (was.tone !== o.tone || was.word !== o.word || tookMoved) {
        it.outcome = { tone: o.tone, word: o.word };
        if (Array.isArray(o.took)) it.took = o.took;
        changed += 1;
      }
    }
    if (changed) {
      // The step that had the keyboard keeps it: a redraw makes new boxes.
      let had = null;
      try {
        const a = typeof document !== 'undefined' ? document.activeElement : null;
        if (a && a.dataset && a.dataset.itemId != null && S.nodeEls.get(String(a.dataset.itemId)) === a) {
          had = String(a.dataset.itemId);
        }
      } catch (_) { had = null; }
      render();
      const back = had != null ? S.nodeEls.get(had) : null;
      if (back && typeof back.focus === 'function') back.focus();
    }
    return { changed, active, deferred: false };
  }

  // ── the view ─────────────────────────────────────────────────────────────
  function viewportRect() {
    try {
      const r = viewport.getBoundingClientRect();
      return { left: r.left || 0, top: r.top || 0, width: r.width || 0, height: r.height || 0 };
    } catch (_) {
      return { left: 0, top: 0, width: 0, height: 0 };
    }
  }

  function toWorld(cx, cy) {
    const r = viewportRect();
    return { x: (cx - r.left - S.view.x) / S.view.zoom, y: (cy - r.top - S.view.y) / S.view.zoom };
  }

  function applyView() {
    world.style.transform = `translate(${S.view.x}px, ${S.view.y}px) scale(${S.view.zoom})`;
    zoomWord.textContent = Math.round(S.view.zoom * 100) + '%';
    // `B1833`. The dot grid moves and scales with the drawing, so the canvas
    // reads as one surface under the steps rather than a pattern behind them.
    if (viewport.style && typeof viewport.style.setProperty === 'function') {
      viewport.style.setProperty('--wb-grid', `${Math.round(20 * S.view.zoom * 100) / 100}px`);
      viewport.style.setProperty('--wb-grid-x', `${Math.round(S.view.x * 10) / 10}px`);
      viewport.style.setProperty('--wb-grid-y', `${Math.round(S.view.y * 10) / 10}px`);
    }
    drawMapFrame();
  }

  // ── the map (`B1833`) ────────────────────────────────────────────────────
  const MAP_KEY = 'pantheon.workbench.map';
  const MAP_W = 180;
  const MAP_H = 112;
  let mapOn = true;
  try { mapOn = localStorage.getItem(MAP_KEY) !== 'off'; } catch (_) { /* storage off: the map shows */ }
  /** The world box the map shows: every step, with room around it. */
  function mapBox() {
    const b = boundsOf(S.pos.values());
    const pad = 80;
    return { x: b.x - pad, y: b.y - pad, w: Math.max(1, b.w + pad * 2), h: Math.max(1, b.h + pad * 2) };
  }
  function mapScale(box) { return Math.min(MAP_W / box.w, MAP_H / box.h); }
  function drawMap() {
    const real = S.order.filter((id) => !S.missing.has(id));
    map.hidden = !mapOn || real.length < 2;
    mapBtn.setAttribute('aria-pressed', mapOn ? 'true' : 'false');
    mapBtn.classList.toggle('active', mapOn);
    if (map.hidden) return;
    const box = mapBox();
    const k = mapScale(box);
    mapSvg.setAttribute('viewBox', `0 0 ${MAP_W} ${MAP_H}`);
    mapSvg.setAttribute('width', String(MAP_W));
    mapSvg.setAttribute('height', String(MAP_H));
    const ox = (MAP_W - box.w * k) / 2;
    const oy = (MAP_H - box.h * k) / 2;
    S.mapGeom = { box, k, ox, oy };
    const kids = [];
    for (const id of real) {
      const p = S.pos.get(id);
      if (!p) continue;
      const it = S.byId.get(id);
      const r = _svg('rect', 'wb-minimap-node');
      r.setAttribute('x', String(Math.round((ox + (p.x - box.x) * k) * 10) / 10));
      r.setAttribute('y', String(Math.round((oy + (p.y - box.y) * k) * 10) / 10));
      r.setAttribute('width', String(Math.max(2, Math.round(NODE_W * k * 10) / 10)));
      r.setAttribute('height', String(Math.max(2, Math.round((p.h || NODE_H) * k * 10) / 10)));
      r.setAttribute('rx', '2');
      r.setAttribute('data-cat', String((it && (it.cat || (it.entry ? 'trigger' : kindCat(it.kind)))) || 'model'));
      if (it && it.outcome && it.outcome.tone) r.setAttribute('data-outcome', String(it.outcome.tone));
      kids.push(r);
    }
    mapNodes.replaceChildren(...kids);
    drawMapFrame();
  }
  function drawMapFrame() {
    const g = S.mapGeom;
    if (!g || map.hidden) return;
    const v = viewSize();
    const z = S.view.zoom || 1;
    const x = (-S.view.x / z - g.box.x) * g.k + g.ox;
    const y = (-S.view.y / z - g.box.y) * g.k + g.oy;
    mapFrame.setAttribute('x', String(Math.round(x * 10) / 10));
    mapFrame.setAttribute('y', String(Math.round(y * 10) / 10));
    mapFrame.setAttribute('width', String(Math.max(4, Math.round((v.width / z) * g.k * 10) / 10)));
    mapFrame.setAttribute('height', String(Math.max(4, Math.round((v.height / z) * g.k * 10) / 10)));
    mapFrame.setAttribute('rx', '3');
  }
  /** Centre the view on the world point under map point (`mx`, `my`). */
  function mapPan(e) {
    const g = S.mapGeom;
    if (!g) return;
    const r = mapSvg.getBoundingClientRect ? mapSvg.getBoundingClientRect() : { left: 0, top: 0 };
    const wx = (e.clientX - r.left - g.ox) / g.k + g.box.x;
    const wy = (e.clientY - r.top - g.oy) / g.k + g.box.y;
    const v = viewSize();
    S.fitted = null; S.openFit = false;
    S.view = { ...S.view, x: v.width / 2 - wx * S.view.zoom, y: v.height / 2 - wy * S.view.zoom };
    applyView();
  }

  // `P23-06` (WB-M-3). A fit measures the viewport's layout size, not its
  // drawn rectangle: the window's entrance is a scale (0.95 → 1), so a fit made
  // while it played read a smaller box, and the same graph opened at 87 % one
  // time and 91 % the next.
  function viewSize() {
    const w = viewport.clientWidth;
    const h = viewport.clientHeight;
    if (w > 0 && h > 0) return { width: w, height: h };
    const r = viewportRect();
    return { width: r.width, height: r.height };
  }

  function fitTo(bounds) {
    const r = viewSize();
    S.view = fitView(bounds, r.width, r.height);
    S.fitted = bounds;
    S.openFit = false;
    S.fitSize = r;
    applyView();
  }

  function fitAll() { fitTo(boundsOf(S.pos.values())); }

  /** `B1833`. The first view of a drawing. A fit, unless the fit would make
   *  the words too small to read — then the readable floor, the start at the
   *  left padding and the drawing centred top to bottom (or its top row at
   *  the padding when it is taller than the canvas): the map and a pan show
   *  the rest, and *Fit* still shows everything. */
  function openView() {
    const b = boundsOf(S.pos.values());
    fitTo(b);
    const r = viewSize();
    if (!(r.width >= NARROW_FIT_WIDTH && S.view.zoom < OPEN_FLOOR && b.w > 0)) return;
    const z = OPEN_FLOOR;
    const pad = 40;
    const y = b.h * z > r.height - pad * 2 ? pad - b.y * z : (r.height - b.h * z) / 2 - b.y * z;
    S.view = { zoom: z, x: Math.round((pad - b.x * z) * 10) / 10, y: Math.round(y * 10) / 10 };
    S.fitted = null;
    // Still the first view: a resize (the window maximized) opens it again.
    S.openFit = true;
    S.fitSize = r;
    applyView();
  }

  function zoomAt(factor, px, py) {
    S.fitted = null; S.openFit = false;   // the person's own view now; a resize leaves it alone
    const z = clampZoom(S.view.zoom * factor);
    const k = z / S.view.zoom;
    S.view = { zoom: z, x: px - (px - S.view.x) * k, y: py - (py - S.view.y) * k };
    applyView();
  }

  function zoomBy(factor) {
    const r = viewportRect();
    zoomAt(factor, r.width / 2, r.height / 2);
  }

  function zoomKeys(e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return false;
    if (e.key === '+' || e.key === '=') zoomBy(ZOOM_STEP);
    else if (e.key === '-' || e.key === '_') zoomBy(1 / ZOOM_STEP);
    else if (e.key === '0') fitAll();
    else return false;
    e.preventDefault();
    return true;
  }

  // ── drawing ──────────────────────────────────────────────────────────────
  function place(node, p) {
    node.style.left = p.x + 'px';
    node.style.top = p.y + 'px';
  }

  function sizeSvg() {
    const b = boundsOf(S.pos.values());
    const x = Math.floor(b.x - 240);
    const y = Math.floor(b.y - 240);
    const w = Math.ceil(b.w + 480);
    const h = Math.ceil(b.h + 480);
    svgEl.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
    svgEl.setAttribute('width', String(w));
    svgEl.setAttribute('height', String(h));
    svgEl.style.left = x + 'px';
    svgEl.style.top = y + 'px';
  }

  /** The ports an item has: its own, or the two every task has. */
  const portsOf = (it) => (it && Array.isArray(it.ports) ? it.ports.map(String) : PORTS);
  /** `P22-10`. The port list an item's arrows are placed by: its own when it
   *  has some, else the two every task has (an item with none — a start
   *  drawn by a source without its port — leaves where the first would be). */
  const geomPorts = (it) => (it && Array.isArray(it.ports) && it.ports.length ? it.ports.map(String) : PORTS);
  /** How tall item `id` is drawn: by the ports it has (`nodeHeight`). */
  const heightOf = (it) => (it && !it.missing ? nodeHeight(portsOf(it)) : NODE_H);
  /** Whether an arrow may land on an item. */
  const accepts = (id) => {
    const it = S.byId.get(id);
    return !!it && !it.missing && it.accepts !== false;
  };

  function hitList() {
    return S.order.filter((id) => !S.missing.has(id) && accepts(id)).map((id) => ({ id, ...S.pos.get(id) }));
  }

  function markSelected() {
    const many = S.sel.size > 1;
    for (const [id, node] of S.nodeEls) {
      node.classList.toggle('wb-node-selected', id === S.selected);
      node.classList.toggle('wb-node-picked', many && S.sel.has(id));
    }
  }

  function focusNode(id) {
    const node = S.nodeEls.get(String(id));
    if (node) {
      setCurrent({ kind: 'node', id: String(id) });
      // `B1844`. Focus never scrolls the canvas: the browser's own "scroll it
      // into view" moved the clipped viewport under its transform, and the
      // drawing drifted off the left edge step by step. The view is panned
      // instead, just enough, when the step is outside it.
      if (typeof node.focus === 'function') {
        try { node.focus({ preventScroll: true }); } catch (_) { node.focus(); }
      }
      keepBeside(String(id), { remember: false });
    }
    return node || null;
  }

  function buildNode(lay) {
    const id = lay.id;
    const it = S.byId.get(id) || null;
    const node = _el('div', 'wb-node');
    node.dataset.itemId = id;
    // The tasks canvas's ids are task ids, and are also written where every
    // reader of `P22-02`'s canvas looks for them (`data-task-id`).
    if (src.idKey) node.dataset[src.idKey] = id;
    node.style.width = NODE_W + 'px';
    node.style.height = (Number(lay.h) > 0 ? lay.h : NODE_H) + 'px';
    place(node, lay);
    S.nodeEls.set(id, node);

    if (lay.missing || !it || it.missing) {
      // The far end of an edge the server kept on purpose (`dangling`): a
      // chain to a task this person cannot see is a real fact about the
      // workflow, so it is drawn — and it is not something to drag or open.
      node.classList.add('wb-node-missing');
      node.setAttribute('aria-hidden', 'true');
      node.appendChild(_el('div', 'wb-node-title', (it && it.missing && it.name) || word('missingTitle')));
      node.appendChild(_el('div', 'wb-node-sub', (it && it.missing && it.sub) || word('missingSub')));
      if (S.plan && !S.plan.partial && !S.plan.byId.has(id)) node.dataset.plan = 'aside';
      return node;
    }

    const name = it.name;
    const out = it.outcome && typeof it.outcome === 'object' ? it.outcome : { tone: 'none', word: '' };
    // `P22-04`. While a dry run's plan is on the canvas, a step says what the
    // run would do there instead of how its last run went.
    const plan = planFor(id, it);
    const subText = plan ? plan.sub : String(it.sub || '');

    // `B1048`. One tab stop for the whole canvas (`applyRoving`): a step is
    // reached with the arrow keys, and the one that is the stop says so.
    node.setAttribute('tabindex', '-1');
    node.setAttribute('role', 'group');
    const tail = String(plan ? plan.line : (out.word || '')).replace(/\.$/, '');
    node.setAttribute('aria-label', [name, subText, tail].filter(Boolean).join('. ') + '.');
    node.dataset.kind = it.kind || 'llm';
    if (plan) node.dataset.plan = plan.state;
    else node.dataset.outcome = out.tone || 'none';
    if (it.paused) node.dataset.paused = 'true';
    // `P22-19`, `P22-24` (wb-canvas-e). A step nobody has checked yet — drafted
    // by the model or imported from a file — carries its origin word, so its
    // border is a shape (dashed) beside the words its mark says.
    if (it.unchecked) node.dataset.unchecked = String(it.unchecked);
    // `B1856`. A step switched off is drawn faded and dashed, and its box
    // says so in words (its marks).
    if (it.off) node.dataset.off = 'true';

    // `B1833`. The kind's glyph on a tile tinted by its family (the
    // palette's group): what a step is, before its name is read. A source
    // may name the glyph itself (a workflow's start, by what starts it).
    const cat = String(it.cat || (it.entry ? 'trigger' : kindCat(it.kind)));
    node.dataset.cat = cat;
    const icon = _el('span', 'wb-node-icon');
    icon.dataset.cat = cat;
    icon.setAttribute('aria-hidden', 'true');
    icon.appendChild(kindIcon(it.glyph || it.kind || 'llm', { size: 18 }));
    const title = _el('div', 'wb-node-title', name);
    title.title = name;
    const sub = _el('div', 'wb-node-sub', subText);
    const last = _el('div', plan ? 'wb-node-plan' : 'wb-node-last');
    // A step that has no outcome to tell (a workflow's step being edited:
    // a draft has no last run) shows no mark — measured in Chromium, a lone
    // "○" under every step of a document, saying nothing.
    const mark = _el('span', 'wb-node-mark', plan ? PLAN_MARKS[plan.state]
      : (out.word ? (OUTCOME_MARKS[out.tone] || OUTCOME_MARKS.info) : ''));
    mark.setAttribute('aria-hidden', 'true');
    last.appendChild(mark);
    const said = _el('span', plan ? 'wb-node-plan-line' : 'wb-node-word', plan ? plan.line : (out.word || ''));
    if (plan) said.title = plan.line;
    last.appendChild(said);
    const actions = _el('div', 'wb-node-actions');
    const allPorts = portsOf(it);
    const ports = ro() ? [] : allPorts;
    if (ports.length) {
      const connectBtn = _el('button', 'wb-node-connect', 'Connect…');
      connectBtn.type = 'button';
      connectBtn.title = it.entry ? 'Choose what runs when it starts' : `Choose what runs after ${name}`;
      connectBtn.addEventListener('click', (e) => {
        if (e && e.stopPropagation) e.stopPropagation();
        openConnect(id, connectBtn);
      });
      actions.appendChild(connectBtn);
    }
    if (plan && plan.entry) {
      // The whole plan, on demand: the short line is one of several.
      const planBtn = _el('button', 'wb-node-plan-btn', 'Plan');
      planBtn.type = 'button';
      planBtn.title = `What ${name} would do, line by line`;
      planBtn.setAttribute('aria-label', `What ${name} would do`);
      planBtn.addEventListener('click', (e) => {
        if (e && e.stopPropagation) e.stopPropagation();
        openPlanBox(id);
      });
      actions.appendChild(planBtn);
    }
    // A source's marks — `P22-08`'s "Sample pinned" — are words on the step,
    // never a colour or an icon alone.
    // `B1833`: on the step's own bottom row, beside how it last went — the
    // step's actions float above it on hover, and a mark must not.
    const marks = (Array.isArray(it.marks) ? it.marks : []).map((m) => String(m || '')).filter(Boolean);
    let marksBox = null;
    if (marks.length) {
      marksBox = _el('span', 'wb-node-marks');
      for (const m of marks) marksBox.appendChild(_el('span', 'wb-node-badge', m));
    }
    for (const n of [icon, title, sub, last, marksBox, actions]) if (n) node.appendChild(n);
    if (!actions.children.length) actions.hidden = true;
    // `B1833`. Where arrows come in: a handle on the left edge, drawn on every
    // step an arrow may land on — a pointer target's look, not a control (the
    // drop target is the whole step, as it always was).
    if (!ro() && it.accepts !== false && !it.entry) {
      const inPort = _el('span', 'wb-port-in');
      inPort.setAttribute('aria-hidden', 'true');
      node.appendChild(inPort);
    }

    for (const when of ports) {
      const port = _el('span', 'wb-port');
      port.dataset.when = when;
      port.style.top = (portOffset(when, allPorts) - 7) + 'px';
      port.title = `${_cap(portWord(id, when))}: drag to the step that should run`
        + (fan() ? ' (another arrow is added; the ones there stay)' : '');
      // The keyboard's way to the same thing is Connect…; a port is a pointer
      // handle and is not announced twice.
      port.setAttribute('aria-hidden', 'true');
      port.appendChild(_el('span', 'wb-port-label', portWord(id, when)));
      port.addEventListener('pointerdown', (e) => startLink(e, id, when, port));
      port.addEventListener('pointermove', (e) => moveLink(e));
      port.addEventListener('pointerup', (e) => finishLink(e));
      port.addEventListener('pointercancel', () => endLink(null));
      node.appendChild(port);
      // `B1833`. A way out with nothing after it offers the next step: "+"
      // beside the port opens the step picker, and the step picked is added
      // with this arrow already drawn — n8n's way of building a flow left to
      // right without a drag. Only where the source can add a step that way.
      if (canAddAfter() && !hasEdge(id, when)) {
        const add = _el('button', 'wb-port-add', '+');
        add.type = 'button';
        add.dataset.when = when;
        add.style.top = (portOffset(when, allPorts) - 10) + 'px';
        add.title = `Add the step that runs ${portWord(id, when)}`;
        add.setAttribute('aria-label', `Add a step after ${name}, ${portWord(id, when)}`);
        add.addEventListener('pointerdown', (e) => { if (e && e.stopPropagation) e.stopPropagation(); });
        add.addEventListener('click', (e) => {
          if (e && e.stopPropagation) e.stopPropagation();
          newPressed(add, { from: id, when });
        });
        node.appendChild(add);
      }
    }

    node.addEventListener('pointerdown', (e) => startDrag(e, id, node));
    node.addEventListener('pointermove', (e) => moveDrag(e, id, node));
    node.addEventListener('pointerup', (e) => endDrag(e, id, node));
    node.addEventListener('pointercancel', (e) => endDrag(e, id, node));
    node.addEventListener('click', (e) => {
      if (S.swallow && S.swallow.id === id && Date.now() < S.swallow.until) { S.swallow = null; return; }
      // `B1841`. Shift-, Ctrl- or Cmd-click picks a step with the others
      // instead of opening it.
      if (e && (e.shiftKey || e.ctrlKey || e.metaKey) && canPick()) { togglePick(id); return; }
      if (S.sel.size) clearPicks();
      select(id);
    });
    node.addEventListener('contextmenu', (e) => {
      if (!e || typeof e.preventDefault !== 'function') return;
      e.preventDefault();
      if (e.stopPropagation) e.stopPropagation();
      openMenu(nodeMenu(id), e.clientX, e.clientY, node);
    });
    node.addEventListener('keydown', (e) => onNodeKey(e, id));
    node.addEventListener('focus', () => setCurrent({ kind: 'node', id }));
    node.addEventListener('blur', () => {
      if (S.moving && S.moving.id === id) putDown();
      if (S.pending && S.pending.key === 'node\u0000' + id) clearPending();
    });
    if (S.selected === id) node.classList.add('wb-node-selected');
    return node;
  }

  function drawEdges(graph) {
    const kids = [];
    S.edgeEls = [];
    for (const edge of (graph || S.graph).edges || []) {
      const from = String(edge.from);
      const to = String(edge.to);
      const when = String(edge.when || '');
      if (!S.pos.has(from) || !S.pos.has(to)) continue;
      const fixed = !!edge.fixed;
      const g = _svg('g', 'wb-edge wb-edge-' + (when === 'error' ? 'error' : 'success') + (fixed ? ' wb-edge-fixed' : ''));
      g.setAttribute('data-from', from);
      g.setAttribute('data-to', to);
      g.setAttribute('data-when', when);
      // `P22-04`. An arrow the planned run would not follow is set aside with
      // the steps it joins.
      if (S.plan && !S.plan.partial && !(S.plan.byId.has(from) && S.plan.byId.has(to))) {
        g.setAttribute('data-plan', 'aside');
      }
      // `B1837`. On a run, the arrows its steps took are lit and the rest
      // set aside, so the path the data went reads without a click.
      const fromIt = S.byId.get(from);
      if (fromIt && Array.isArray(fromIt.took)) {
        const lit = fromIt.entry ? fromIt.took.length > 0 : fromIt.took.includes(when);
        g.setAttribute('data-taken', lit ? 'true' : 'false');
      }
      g.setAttribute('tabindex', '-1');
      g.setAttribute('role', 'button');
      const removable = !fixed && !ro();
      g.setAttribute('aria-label', edgeSentence(from, when, to) + (removable ? ' Press Delete to remove this arrow.' : ''));
      const hit = _svg('path', 'wb-edge-hit');
      const line = _svg('path', 'wb-edge-line');
      const head = _svg('path', 'wb-edge-head');
      const label = _svg('text', 'wb-edge-label');
      label.setAttribute('text-anchor', 'middle');
      label.textContent = edge.label ? String(edge.label) : portWord(from, when);
      for (const n of [hit, line, head, label]) g.appendChild(n);
      // `B1842`. A "+" in the middle of the arrow puts a step between its
      // two ends, joined both ways, the arrow it stood on taken away.
      let add = null;
      if (canAddAfter()) {
        add = _svg('g', 'wb-edge-add');
        add.setAttribute('role', 'button');
        add.setAttribute('tabindex', '-1');
        add.setAttribute('aria-label', `Add a step between ${nameOf(from)} and ${nameOf(to)}`);
        const ring = _svg('circle', 'wb-edge-add-ring');
        ring.setAttribute('r', '10');
        const plus = _svg('path', 'wb-edge-add-plus');
        plus.setAttribute('d', 'M-4.5 0h9M0 -4.5v9');
        add.appendChild(ring);
        add.appendChild(plus);
        add.addEventListener('pointerdown', (e) => { if (e && e.stopPropagation) e.stopPropagation(); });
        add.addEventListener('click', (e) => {
          if (e && e.stopPropagation) e.stopPropagation();
          newPressed(add, { from, when, to });
        });
        g.appendChild(add);
      }
      const rec = { edge, from, to, when, fixed, key: `${from}\u0000${when}\u0000${to}`, g, hit, line, head, label, add };
      g.addEventListener('pointerdown', (e) => { if (e && e.stopPropagation) e.stopPropagation(); });
      g.addEventListener('click', () => { if (typeof g.focus === 'function') g.focus(); showEdge(rec); });
      g.addEventListener('focus', () => { setCurrent({ kind: 'edge', id: from, key: rec.key }); showEdge(rec); });
      g.addEventListener('blur', () => { if (S.pending && S.pending.key === rec.key) clearPending(); });
      g.addEventListener('keydown', (e) => onEdgeKey(e, rec));
      S.edgeEls.push(rec);
      kids.push(g);
    }
    edgeLayer.replaceChildren(...kids);
    updateEdges();
  }

  function updateEdges() {
    for (const r of S.edgeEls) {
      // An item with no ports (a workflow's start) has no port to leave from;
      // its arrow leaves where the first port would be, so `graphLayout.js`
      // draws it unchanged.
      const fromItem = S.byId.get(r.from);
      const geom = fromItem && Array.isArray(fromItem.ports) && !fromItem.ports.length ? PORTS[0] : r.when;
      // `B1053`. Routed round both steps when the target is not to the right,
      // so an arrow to a step on the left reads the way it was saved.
      // `P22-10`: from the step's own port, by its own port list.
      const route = edgeRoute(S.pos.get(r.from), S.pos.get(r.to), geom, geomPorts(fromItem));
      r.hit.setAttribute('d', route.d);
      r.line.setAttribute('d', route.d);
      r.head.setAttribute('d', arrowPath(route.end));
      r.label.setAttribute('x', String(route.label.x));
      r.label.setAttribute('y', String(route.label.y - (r.add ? 16 : 0)));
      if (r.add) r.add.setAttribute('transform', `translate(${route.label.x} ${route.label.y})`);
      r.g.setAttribute('data-routed', route.routed ? 'true' : 'false');
    }
    sizeSvg();
  }

  function drawGuides(list) {
    const b = boundsOf(S.pos.values());
    const kids = (list || []).map((gd) => {
      const ln = _svg('line', 'wb-guide');
      if (gd.vertical) {
        ln.setAttribute('x1', String(gd.x)); ln.setAttribute('x2', String(gd.x));
        ln.setAttribute('y1', String(b.y - 40)); ln.setAttribute('y2', String(b.y + b.h + 40));
      } else {
        ln.setAttribute('y1', String(gd.y)); ln.setAttribute('y2', String(gd.y));
        ln.setAttribute('x1', String(b.x - 40)); ln.setAttribute('x2', String(b.x + b.w + 40));
      }
      return ln;
    });
    guides.replaceChildren(...kids);
  }

  // ── what is shown: the built-ins set aside (`B1048`) ─────────────────────
  /** The built-in tasks set aside: every workflow made only of built-ins,
   *  unless the switch shows them or the Workbench was opened on one. A
   *  built-in joined to a step of the person's own is part of their workflow
   *  and is never hidden. */
  function hiddenIds() {
    const out = new Set();
    if (S.showBuiltins) return out;
    const seen = new Set();
    for (const it of S.items) {
      const id = it.id;
      if (!it.builtin || seen.has(id)) continue;
      const ids = componentOf(S.graph, id).ids;
      ids.forEach((x) => seen.add(x));
      const builtinsOnly = [...ids].every((x) => { const o = S.byId.get(x); return !!(o && o.builtin); });
      if (builtinsOnly && ![...ids].some((x) => S.reveal.has(x))) ids.forEach((x) => out.add(x));
    }
    return out;
  }

  function render() {
    S.hidden = hiddenIds();
    const shown = (id) => !S.hidden.has(String(id));
    const graph = {
      ...S.graph,
      nodes: (S.graph.nodes || []).filter((n) => shown(n.id)),
      edges: (S.graph.edges || []).filter((e) => shown(e.from) && shown(e.to)),
    };
    // Everything already on the canvas stays where it is — a person who drew
    // one arrow must not have to find both steps again — and what the person
    // placed in an earlier visit is where it was left. Only steps nobody has
    // placed are laid out (`graphLayout.js`).
    const fixed = new Map(S.pinned);
    for (const [id, p] of S.pos) fixed.set(id, p);
    // `P22-10`. Each step as tall as its ports need, and the steps an If or a
    // Switch leads to ordered the way its ports are.
    const heights = new Map();
    const portLists = new Map();
    for (const it of S.items) {
      heights.set(it.id, heightOf(it));
      if (Array.isArray(it.ports) && it.ports.length) portLists.set(it.id, it.ports.map(String));
    }
    const lay = layoutGraph(graph, fixed, { heights, ports: portLists });
    S.pos = new Map(lay.nodes.map((n) => [n.id, { x: n.x, y: n.y, h: n.h }]));
    S.missing = new Set(lay.nodes.filter((n) => n.missing).map((n) => n.id));
    S.order = lay.nodes.map((n) => n.id);
    S.nodeEls = new Map();
    nodesLayer.replaceChildren(...lay.nodes.map((n) => buildNode(n)));
    drawEdges(graph);
    const real = S.items.filter((i) => !i.missing);
    const builtins = real.filter((i) => i.builtin).length;
    const own = real.length - real.filter((i) => S.hidden.has(i.id)).length;
    builtinsSwitch.hidden = builtins === 0;
    builtinsBox.checked = S.showBuiltins;
    builtinsWord.textContent = `Show built-in tasks (${builtins})`;
    empty.hidden = own > 0;
    emptyTitle.textContent = real.length && word('emptyTitleOwn') ? word('emptyTitleOwn') : word('emptyTitle');
    emptyBuiltins.hidden = !S.hidden.size;
    // A read-only source (a run, a version being looked at) makes nothing.
    newBtn.hidden = ro();
    emptyNew.hidden = ro();
    tidyBtn.hidden = ro();
    root.classList.toggle('wb-room-empty', own === 0);
    root.classList.toggle('wb-read-only', ro());
    if (S.moving && S.nodeEls.has(S.moving.id)) S.nodeEls.get(S.moving.id).classList.add('wb-node-moving');
    applyRoving();
    drawMap();
    syncTools();
    markSelected();
    if (!S.viewed) { S.viewed = true; openView(); } else applyView();
  }

  function moveNode(id, x, y) {
    const was = S.pos.get(id);
    S.pos.set(id, { x, y, h: was && was.h ? was.h : NODE_H });
    const node = S.nodeEls.get(id);
    if (node) place(node, { x, y });
    updateEdges();
    if (!map.hidden) drawMap();
  }

  function pin(id) {
    const p = S.pos.get(id);
    if (p) S.pinned.set(id, { x: p.x, y: p.y });
  }

  // The click a browser fires when a press ends is not a request to open the
  // step: after a drag it lands on the step that moved, and after a drag from
  // a port it lands on the port (which holds the pointer) and bubbles to the
  // step the arrow left — measured in Chromium, where it opened that step's
  // panel over the arrow just drawn. Swallowed by time rather than by a flag,
  // so a browser that fires no click leaves nothing behind to eat a real one.
  function swallowClick(id) { S.swallow = { id, until: Date.now() + SWALLOW_MS }; }

  // ── moving a step: pointer ───────────────────────────────────────────────
  // `windowDrag.js`'s pattern, on pointer events with capture: the press is a
  // click until it travels `MOVE_THRESHOLD`, and the click a browser fires
  // after a real drag is swallowed so it does not open the step that moved.
  function startDrag(e, id, node) {
    if (e.button != null && e.button !== 0) return;
    if (ro()) return;
    const t = e.target;
    if (t && t !== node && typeof t.closest === 'function' && t.closest('button, .wb-port')) return;
    if (e.stopPropagation) e.stopPropagation();
    const p = S.pos.get(id);
    // `B1841`. A picked step drags the others picked with it.
    const group = S.sel.has(id) && S.sel.size > 1
      ? Array.from(S.sel).filter((x) => x !== id && S.pos.has(x)).map((x) => ({ id: x, x0: S.pos.get(x).x, y0: S.pos.get(x).y }))
      : [];
    S.drag = { id, pointerId: e.pointerId, cx: e.clientX, cy: e.clientY, x0: p.x, y0: p.y, moved: false, group };
    try { if (node.setPointerCapture) node.setPointerCapture(e.pointerId); } catch (_) { /* a synthetic pointer */ }
  }

  function moveDrag(e, id, node) {
    const d = S.drag;
    if (!d || d.id !== id) return;
    const dx = e.clientX - d.cx;
    const dy = e.clientY - d.cy;
    if (!d.moved && Math.abs(dx) <= MOVE_THRESHOLD && Math.abs(dy) <= MOVE_THRESHOLD) return;
    d.moved = true;
    node.classList.add('wb-node-dragging');
    const others = [];
    const moving = new Set([id, ...d.group.map((g) => g.id)]);
    for (const [oid, p] of S.pos) {
      if (moving.has(oid) || S.missing.has(oid)) continue;
      others.push({ visible: true, id: oid, canvas: { width: NODE_W, height: p.h || NODE_H }, offset: p });
    }
    // `editor/snap.js`, the image editor's layer snap: a step dragged near
    // another step's edge or centre lines up with it.
    const snap = computeSnap({ id, canvas: { width: NODE_W, height: (S.pos.get(id) || {}).h || NODE_H } },
      d.x0 + dx / S.view.zoom, d.y0 + dy / S.view.zoom,
      { zoom: S.view.zoom, canvasW: 0, canvasH: 0, otherLayers: others });
    drawGuides(snap.guides);
    moveNode(id, snap.x, snap.y);
    for (const g of d.group) moveNode(g.id, g.x0 + (snap.x - d.x0), g.y0 + (snap.y - d.y0));
  }

  function endDrag(e, id, node) {
    const d = S.drag;
    if (!d || d.id !== id) return;
    S.drag = null;
    try { if (node.releasePointerCapture) node.releasePointerCapture(d.pointerId); } catch (_) { /* already released */ }
    node.classList.remove('wb-node-dragging');
    drawGuides([]);
    if (d.moved) {
      swallowClick(id);
      pin(id);
      for (const g of d.group) pin(g.id);
      savePositions();
    }
  }

  // ── the keyboard: one tab stop, the arrows within it (`B1048`) ───────────
  // Every step was a tab stop and so was its Connect…, with the arrows after
  // them: measured on the merged tree, 24 to 28 presses of Tab to reach one
  // step. The canvas is one stop now — the step (or arrow) last visited, the
  // first step to begin with — and the arrow keys go through the steps in
  // reading order (top to bottom, left to right), each followed by the arrows
  // that leave it, "if it works" first; Home and End go to the ends. The
  // stop's own buttons (Connect…, Plan) follow it in the Tab order, so Tab
  // from a step still reaches its Connect…. Moving a step was the arrow keys
  // themselves; they go between steps now, so a step is picked up with M,
  // moved with the arrows exactly as before (Shift for four times the step),
  // and put down with Enter or M — or put back with Escape.
  const BAND = NODE_H / 2;
  const sameItem = (a, b) => !!(a && b && a.kind === b.kind && (a.kind === 'node' ? a.id === b.id : a.key === b.key));

  function rovingItems() {
    const steps = S.order.filter((id) => !S.missing.has(id) && S.nodeEls.has(id))
      .map((id) => ({ id, p: S.pos.get(id) }))
      .sort((a, b) => (Math.round(a.p.y / BAND) - Math.round(b.p.y / BAND)) || (a.p.x - b.p.x));
    const items = [];
    for (const s of steps) {
      items.push({ kind: 'node', id: s.id, el: S.nodeEls.get(s.id) });
      const own = geomPorts(S.byId.get(s.id));
      S.edgeEls.filter((r) => r.from === s.id)
        .sort((a, b) => own.indexOf(a.when) - own.indexOf(b.when))
        .forEach((r) => items.push({ kind: 'edge', id: r.from, key: r.key, el: r.g }));
    }
    return items;
  }

  function applyRoving() {
    const items = rovingItems();
    const cur = items.find((it) => sameItem(it, S.current)) || items[0] || null;
    S.current = cur ? { kind: cur.kind, id: cur.id, key: cur.key } : null;
    for (const it of items) {
      const on = it === cur;
      it.el.setAttribute('tabindex', on ? '0' : '-1');
      if (it.kind === 'node') {
        for (const b of it.el.querySelectorAll('button')) b.setAttribute('tabindex', on ? '0' : '-1');
      }
    }
    return cur;
  }

  function setCurrent(item) {
    if (sameItem(item, S.current)) return;
    S.current = item;
    applyRoving();
  }

  /** Move the stop by `delta` items, or to the first or last, and focus it. */
  function rove(e, delta, end) {
    const items = rovingItems();
    if (!items.length) return;
    const i = items.findIndex((it) => sameItem(it, S.current));
    const j = end === 'first' ? 0 : end === 'last' ? items.length - 1
      : Math.min(items.length - 1, Math.max(0, (i < 0 ? 0 : i) + delta));
    if (e && e.preventDefault) e.preventDefault();
    const next = items[j];
    S.current = { kind: next.kind, id: next.id, key: next.key };
    applyRoving();
    if (typeof next.el.focus === 'function') next.el.focus();
  }

  /** The arrow keys and Home/End, on a step or an arrow. True when used. */
  function roveKeys(e) {
    if (e.altKey || e.ctrlKey || e.metaKey) return false;
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { rove(e, 1); return true; }
    if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { rove(e, -1); return true; }
    if (e.key === 'Home') { rove(e, 0, 'first'); return true; }
    if (e.key === 'End') { rove(e, 0, 'last'); return true; }
    return false;
  }

  // ── moving a step: keyboard ──────────────────────────────────────────────
  function pickUp(id) {
    const p = S.pos.get(id);
    if (!p || ro()) return;
    putDown(true);
    S.moving = {
      id, x: p.x, y: p.y, pinned: S.pinned.has(id) ? { ...S.pinned.get(id) } : null,
      unregister: holdEscape(() => putBack()),
    };
    const node = S.nodeEls.get(id);
    if (node) node.classList.add('wb-node-moving');
    say(`Moving ${nameOf(id)}: the arrow keys move it, with Shift in bigger steps. Enter puts it down; Escape puts it back.`);
  }

  function endMove() {
    const m = S.moving;
    if (!m) return null;
    S.moving = null;
    m.unregister();
    const node = S.nodeEls.get(m.id);
    if (node) node.classList.remove('wb-node-moving');
    return m;
  }

  function putDown(quiet) {
    const m = endMove();
    if (!m) return;
    if (S.saveTimer) savePositions();
    if (!quiet) say(`Put ${nameOf(m.id)} down.`);
  }

  function putBack() {
    const m = endMove();
    if (!m) return;
    moveNode(m.id, m.x, m.y);
    if (m.pinned) S.pinned.set(m.id, m.pinned); else S.pinned.delete(m.id);
    savePositions();
    focusNode(m.id);
    say(`${nameOf(m.id)} is back where it was.`);
  }

  function onNodeKey(e, id) {
    if (e.target && e.target !== S.nodeEls.get(id)) return;   // keys inside Connect…
    const plain = !e.altKey && !e.ctrlKey && !e.metaKey;
    if (S.moving && S.moving.id === id) {
      const dir = KEY_DIRS[e.key];
      if (dir && plain) {
        e.preventDefault();
        const step = KEY_STEP * (e.shiftKey ? 4 : 1);
        const p = S.pos.get(id);
        moveNode(id, p.x + dir[0] * step, p.y + dir[1] * step);
        pin(id);
        scheduleSave();
        return;
      }
      if (plain && (e.key === 'Enter' || e.key === 'm' || e.key === 'M')) {
        e.preventDefault();
        putDown();
      }
      return;
    }
    if (roveKeys(e)) return;
    if (plain && (e.key === 'm' || e.key === 'M') && !ro()) {
      e.preventDefault();
      pickUp(id);
      return;
    }
    if (plain && (e.key === 'Delete' || e.key === 'Backspace') && typeof src.removeItem === 'function' && !ro()) {
      e.preventDefault();
      if (S.sel.size > 1 && S.sel.has(id)) askRemoveMany(Array.from(S.sel));
      else askRemove(id);
      return;
    }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      select(id);
      return;
    }
    zoomKeys(e);
  }

  // ── connecting: drag from a port ─────────────────────────────────────────
  function startLink(e, from, when, port) {
    if (e.button != null && e.button !== 0) return;
    if (e.stopPropagation) e.stopPropagation();
    if (e.preventDefault) e.preventDefault();
    endLink(null);
    S.link = {
      from, when, port, pointerId: e.pointerId, over: null,
      start: portPoint(S.pos.get(from), when, geomPorts(S.byId.get(from))),
      unregister: holdEscape(() => endLink(null)),
    };
    try { if (port.setPointerCapture) port.setPointerCapture(e.pointerId); } catch (_) { /* a synthetic pointer */ }
    ghost.setAttribute('d', edgePath(S.link.start, S.link.start));
    root.classList.add('wb-linking');
    say(isEntry(from)
      ? 'Let go over the step that should run when it starts.'
      : `${_cap(portWord(from, when))}: let go over the step that should run after ${nameOf(from)}.`);
  }

  function moveLink(e) {
    const L = S.link;
    if (!L) return;
    const p = toWorld(e.clientX, e.clientY);
    ghost.setAttribute('d', edgePath(L.start, p));
    const over = nodeAt(hitList(), p, L.from);
    if (over !== L.over) {
      if (L.over && S.nodeEls.get(L.over)) S.nodeEls.get(L.over).classList.remove('wb-node-target');
      if (over && S.nodeEls.get(over)) S.nodeEls.get(over).classList.add('wb-node-target');
      L.over = over;
    }
  }

  function finishLink(e) {
    const L = S.link;
    if (!L) return;
    const at = toWorld(e.clientX, e.clientY);
    const target = nodeAt(hitList(), at, L.from);
    // `B1842`. Let go on empty canvas, away from the port: the step picker
    // opens there, and the step chosen is added joined to that port.
    const far = Math.hypot(at.x - L.start.x, at.y - L.start.y) * S.view.zoom > 36;
    if (!target && far && canAddAfter()) {
      const { from, when, port } = L;
      endLink(null);
      newPressed(port, { from, when }, { at });
      return;
    }
    endLink(target);
  }

  function endLink(target) {
    const L = S.link;
    if (!L) return;
    S.link = null;
    L.unregister();
    try { if (L.port.releasePointerCapture) L.port.releasePointerCapture(L.pointerId); } catch (_) { /* already released */ }
    ghost.setAttribute('d', '');
    root.classList.remove('wb-linking');
    swallowClick(L.from);
    if (L.over && S.nodeEls.get(L.over)) S.nodeEls.get(L.over).classList.remove('wb-node-target');
    if (target) connect(L.from, L.when, target);
    else say('');
  }

  // ── the two writes ───────────────────────────────────────────────────────
  // The source writes; the canvas says what happened and redraws from a fresh
  // `load()`. A refusal is the source's (the server's) sentence, word for word.
  async function connect(from, when, to) {
    const before = (S.graph.edges || []).find((e) => e.from === from && e.when === when);
    let res;
    try { res = await src.connect(from, when, to); } catch (err) { res = { ok: false, sentence: _thrown(err) }; }
    if (!res || !res.ok) {
      const sentence = (res && res.sentence) || 'The change was refused.';
      say('Not connected: ' + sentence, { refusal: true });
      return { ok: false, sentence };
    }
    const sentence = edgeSentence(from, when, to);
    // `P22-11`. On a source with fan-out the arrow that was there stays, so
    // there is nothing it "used to be".
    const was = !fan() && before && before.to !== String(to) ? ` It used to be ${nameOf(before.to)}.` : '';
    await reload();
    say(`Connected. ${sentence}${was}` + (res.sentence ? ' ' + String(res.sentence) : ''));
    return res;
  }

  async function removeEdge(rec) {
    clearPending();
    if (rec.fixed) return { ok: false };
    let res;
    try { res = await src.disconnect(rec.from, rec.when, rec.to); } catch (err) { res = { ok: false, sentence: _thrown(err) }; }
    if (!res || !res.ok) {
      say('Not removed: ' + ((res && res.sentence) || 'The change was refused.'), { refusal: true });
      return res || { ok: false };
    }
    const sentence = isEntry(rec.from)
      ? `${nameOf(rec.to)} no longer runs when it starts.`
      : `${nameOf(rec.to)} no longer runs after ${nameOf(rec.from)} ${portWord(rec.from, rec.when)}.`;
    await reload();
    focusNode(rec.from);
    say('Removed. ' + sentence);
    return res;
  }

  // ── an arrow, focused ────────────────────────────────────────────────────
  function showEdge(rec) {
    if (S.pending && S.pending.key === rec.key) return;
    if (rec.fixed || ro()) { say(edgeSentence(rec.from, rec.when, rec.to)); return; }
    say(edgeSentence(rec.from, rec.when, rec.to), {
      action: { label: 'Remove this arrow', run: () => removeEdge(rec) },
    });
  }

  function clearPending() {
    const p = S.pending;
    if (!p) return;
    S.pending = null;
    p.unregister();
  }

  function onEdgeKey(e, rec) {
    if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault();
      if (ro()) return;
      if (rec.fixed) {
        say(`${edgeSentence(rec.from, rec.when, rec.to)} This arrow always leads to the first step, so it cannot be removed.`);
        return;
      }
      if (S.pending && S.pending.key === rec.key) { removeEdge(rec); return; }
      clearPending();
      // Said first, removed second: the arrow a key would take away is named
      // before anything is written, and a second press is the yes.
      S.pending = {
        key: rec.key,
        unregister: holdEscape(() => { S.pending = null; say('Kept. ' + edgeSentence(rec.from, rec.when, rec.to)); }),
      };
      say(`Remove this arrow? ${edgeSentence(rec.from, rec.when, rec.to)} Press Delete again to remove it, or Escape to keep it.`,
        { action: { label: 'Remove this arrow', run: () => removeEdge(rec) } });
      return;
    }
    if (roveKeys(e)) return;
    zoomKeys(e);
  }

  // ── removing a step: Delete twice, said first (a source with `removeItem`) ─
  function askRemove(id) {
    const it = S.byId.get(id);
    if (!it || it.missing) return;
    if (it.fixed) { say(`${it.name} cannot be removed.`); return; }
    const key = 'node\u0000' + id;
    if (S.pending && S.pending.key === key) { removeItem(id); return; }
    clearPending();
    S.pending = { key, unregister: holdEscape(() => { S.pending = null; say(`Kept ${it.name}.`); }) };
    // `B1851`. The steps that read what this one makes would read nothing.
    let refs = [];
    try { refs = typeof src.referencesTo === 'function' ? (src.referencesTo(id) || []) : []; } catch (_) { refs = []; }
    const using = refs.length
      ? ` ${_listWords(refs.map((r) => `“${r}”`))} ${refs.length === 1 ? 'uses' : 'use'} what it makes and would be left without it.`
      : '';
    say(`Remove ${it.name}?${using} Press Delete again to remove it, or Escape to keep it.`,
      { action: { label: 'Remove this step', run: () => removeItem(id) } });
  }

  async function removeItem(id) {
    clearPending();
    const name = nameOf(id);
    let res;
    try { res = await src.removeItem(id); } catch (err) { res = { ok: false, sentence: _thrown(err) }; }
    if (!res || res.ok === false) {
      say('Not removed: ' + ((res && res.sentence) || 'The change was refused.'), { refusal: true });
      return;
    }
    if (S.panel && S.panel.id === id) closePanel(false);
    S.pinned.delete(id);
    await reload();
    say(`Removed ${name}.` + (res.sentence ? ' ' + res.sentence : ''));
  }

  // ── a box beside a step ──────────────────────────────────────────────────
  /** Put `box` (`width` wide in the sheet) beside step `id`, on the stage. */
  function besideStep(box, id, width) {
    const p = S.pos.get(id) || { x: 0, y: 0 };
    let left = Math.round(S.view.x + (p.x + NODE_W) * S.view.zoom + 12);
    // `B1051`. Beside the step, unless that is past the stage's right edge — at
    // phone width it always is, and the picker opened off-screen.
    const stageW = (() => { try { return stage.getBoundingClientRect().width || 0; } catch (_) { return 0; } })();
    if (stageW) left = Math.min(left, Math.round(stageW - width - 8));
    box.style.left = Math.max(8, left) + 'px';
    box.style.top = Math.max(8, Math.round(S.view.y + p.y * S.view.zoom)) + 'px';
  }

  // ── Connect… — the keyboard's way to the same write ──────────────────────
  function closeConnect(restoreFocus) {
    const c = S.connect;
    if (!c) return;
    S.connect = null;
    c.unregister();
    c.box.remove();
    if (restoreFocus) focusNode(c.from);
  }

  function openConnect(from, opener) {
    closeConnect(false);
    const it = S.byId.get(from);
    if (!it || it.missing) return;
    const name = it.name;
    const box = _el('div', 'wb-connect');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', `Connect ${name}`);
    box.appendChild(_el('p', 'wb-connect-head', it.entry ? 'When it starts…' : `After ${name}…`));

    const ports = portsOf(it);
    const whenLabel = _el('label', 'wb-connect-field');
    whenLabel.appendChild(_el('span', 'wb-connect-label', 'Outcome'));
    const whenSel = _el('select', 'wb-connect-when');
    for (const w of ports) {
      const o = _el('option', null, portWord(from, w));
      o.value = w;
      whenSel.appendChild(o);
    }
    whenLabel.appendChild(whenSel);
    // One way out (a workflow's start, a Set): nothing to choose.
    whenLabel.hidden = ports.length === 1;

    const toLabel = _el('label', 'wb-connect-field');
    toLabel.appendChild(_el('span', 'wb-connect-label', 'Run next'));
    const toSel = _el('select', 'wb-connect-to');
    const others = S.items.filter((o) => o.id !== from && accepts(o.id))
      .sort((a, b) => a.name.localeCompare(b.name));
    for (const t of others) {
      const o = _el('option', null, t.name);
      o.value = t.id;
      toSel.appendChild(o);
    }
    toLabel.appendChild(toSel);

    const now = _el('p', 'wb-connect-now');
    const said = _el('p', 'wb-connect-say');
    said.setAttribute('aria-live', 'assertive');
    const row = _el('div', 'wb-connect-buttons');
    const go = _el('button', 'wb-connect-go', 'Connect');
    go.type = 'button';
    const cancel = _el('button', 'wb-connect-cancel', 'Cancel');
    cancel.type = 'button';
    row.appendChild(go);
    row.appendChild(cancel);
    for (const n of [whenLabel, toLabel, now, said, row]) box.appendChild(n);

    const current = (when) => (S.graph.edges || []).filter((x) => x.from === from && x.when === when).map((x) => x.to);
    const syncNow = () => {
      const cur = current(whenSel.value);
      const words = isEntry(from) ? 'when it starts' : portWord(from, whenSel.value);
      if (!cur.length) { now.textContent = ''; return; }
      const names = cur.map((x) => nameOf(x));
      const list = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0];
      // `P22-11`. With fan-out the arrows there stay and one is added.
      now.textContent = fan()
        ? `Now: ${list} ${names.length > 1 ? 'run' : 'runs'} ${words}. Connecting adds another; ${names.length > 1 ? 'they all run' : 'both run'}.`
        : `Now: ${list} runs ${words}. Connecting replaces it.`;
    };
    // Stated rather than left to the browser's default, so the first choice
    // is the same however the picker is driven.
    whenSel.value = ports[0];
    if (others.length) toSel.value = others[0].id;
    whenSel.addEventListener('change', syncNow);
    if (!others.length) {
      toSel.disabled = true;
      go.disabled = true;
      now.textContent = `There is no other step yet. Make one with ${word('newLabel')}, then connect them.`;
    } else {
      syncNow();
    }

    const submit = async () => {
      if (go.disabled) return;
      go.disabled = true;
      said.textContent = '';
      const res = await connect(from, whenSel.value, toSel.value);
      go.disabled = false;
      if (res.ok) {
        closeConnect(false);
        focusNode(from);
      } else {
        said.textContent = 'Not connected: ' + res.sentence;
      }
    };
    go.addEventListener('click', submit);
    cancel.addEventListener('click', () => closeConnect(true));
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target !== go && e.target !== cancel) { e.preventDefault(); submit(); }
    });

    besideStep(box, from, CONNECT_W);
    stage.appendChild(box);
    S.connect = { box, from, opener, submit, whenSel, toSel, unregister: holdEscape(() => closeConnect(true)) };
    whenSel.focus();
  }

  // ── the side panel: the source's form, mounted ───────────────────────────
  function closePanel(restoreFocus, { swap = false } = {}) {
    const p = S.panel;
    if (!p) return;
    S.panel = null;
    p.unregister();
    try {
      if (p.handle && typeof p.handle.destroy === 'function') p.handle.destroy();
    } catch (err) {
      console.warn('Workbench: the step form did not close cleanly', err);
    }
    panelBody.replaceChildren();
    panel.hidden = true;
    root.classList.remove('wb-panel-open');
    S.selected = null;
    markSelected();
    if (!swap) viewBack();
    if (restoreFocus && p.id) focusNode(p.id);
  }

  /** `B1844`. The view as it was before a panel moved it, put back when the
   *  panel closes — unless the person moved it since. Steps added one after
   *  another each opened a panel that panned the canvas, and nothing panned
   *  it back: after five, the first steps were off the left edge. A view
   *  that was a fit is fitted again, to the steps there are now. */
  function viewBack() {
    const b = S.beside;
    S.beside = null;
    if (!b || !b.set) return;
    const v = S.view;
    if (Math.abs(v.x - b.set.x) > 0.5 || Math.abs(v.y - b.set.y) > 0.5 || Math.abs(v.zoom - b.set.zoom) > 0.001) return;
    if (b.openFit) { openView(); return; }
    if (b.fitted) { fitAll(); return; }
    S.view = { ...b.view };
    applyView();
  }

  async function onSaved(saved) {
    const id = saved && saved.id != null ? String(saved.id) : null;
    // `P22-09`. A source may re-key a step as it is first named (`was`); it
    // stays where it was drawn.
    const was = saved && saved.was != null ? String(saved.was) : null;
    if (id && was && was !== id) {
      for (const map of [S.pos, S.pinned]) {
        if (map.has(was)) { map.set(id, map.get(was)); map.delete(was); }
      }
    }
    closePanel(false);
    await reload();
    if (id) focusNode(id);
    // A source may say what happened in its own words. A source with a save
    // of its own (a workflow, C3's `save()`) keeps a step's change in its
    // draft until that save, so "Saved" would be untrue: it says the change
    // is made and where it is kept.
    const named = saved && (saved.name || saved.label) ? String(saved.name || saved.label) : (id ? nameOf(id) : '');
    if (saved && saved.sentence) say(String(saved.sentence));
    else if (typeof src.save === 'function') say(`Changed ${named || 'the step'}. Save keeps it in the workflow.`);
    else say(saved && saved.name ? `Saved ${saved.name}.` : 'Saved.');
  }

  const panelName = (p) => (p.id ? nameOf(p.id) : 'This new step');

  // `B1052`. Escape on a form with unsaved edits says so before it throws them
  // away, and a second Escape is the yes — the canvas's own rule for removing
  // an arrow (said first, done second). An edit is anything typed or chosen in
  // the form (`input` / `change` reaching the panel's host); the form is the
  // `P22` contract's and says nothing about itself, so the panel listens
  // rather than asking it. Cancel, Close and Save are deliberate and do not ask.
  function panelEscape() {
    const p = S.panel;
    if (!p) return;
    const name = panelName(p);
    if (p.dirty && !p.asked) {
      p.asked = true;
      p.unregister = holdEscape(() => panelEscape());
      say(`${name} has changes that are not saved. Press Escape again to close it without saving them, or Save.`);
      return;
    }
    closePanel(true);
    if (p.asked) say(`Closed ${p.id ? name : 'the new step'} without saving.`);
  }

  // `B1067`. Opening another step — a click, Enter, *New step* — closed the
  // open form with no word, so an edit was lost by a different door than the
  // one `B1052` guarded. The same rule: said first, done second. The first
  // request names what would be lost and is held; the same request again (or
  // the sentence's button) is the yes. Typing in the form in between asks
  // again; the open step itself, asked for again, keeps its form.
  function mayLeavePanel(key, target) {
    const p = S.panel;
    if (!p || !p.dirty || p.pendingOpen === key) return true;
    p.pendingOpen = key;
    say(`${panelName(p)} has changes that are not saved. ${target.again} to close it without saving them, or Save first.`,
      { action: { label: target.label, run: target.retry } });
    return false;
  }

  /**
   * `B1836`. The panel's Close keeps what was typed. It was the one door
   * that dropped an edited form without a word (measured: a step renamed,
   * then Close — the old name stayed and nothing said so), where people
   * expect "close and keep". A form with edits is applied through its own
   * Done; a form that refuses (a field it marks) stays open and says so, and
   * Close again is the "close without them".
   */
  function panelCloseClick() {
    const p = S.panel;
    if (!p) return;
    if (!p.dirty || p.asked) {
      const dropped = p.dirty;
      closePanel(true);
      if (dropped) say(`Closed ${p.id ? nameOf(p.id) : 'the new step'} without keeping its changes.`);
      return;
    }
    const done = applyButtonOf(p);
    if (done) {
      p.applying = false;
      done.click();
      if (S.panel !== p || p.applying) return;   // taken: `onSaved` closes it
    }
    p.asked = true;
    say(done
      ? `${panelName(p)} was not changed: fix what is marked and press Done, or press Close again to close without the changes.`
      : `${panelName(p)} has changes that are not kept. Press Done to keep them, or Close again to close without them.`);
  }

  /** The open form's own Done (a step's; a task step's), the one showing. */
  function applyButtonOf(p) {
    if (!p || !p.host || typeof p.host.querySelectorAll !== 'function') return null;
    const all = Array.from(p.host.querySelectorAll('.wf-step-done, [id$="task-form-save"]'));
    const shown = (b) => {
      for (let n = b; n && n !== p.host; n = n.parentNode) if (n.hidden) return false;
      return !b.disabled;
    };
    // A For-each's inner step, while it is being edited, is the form showing.
    return all.reverse().find(shown) || null;
  }

  /** The sentence for a form closed without saving, if the panel open now is
   *  one the person agreed to drop; `''` otherwise. */
  function droppedSentence() {
    const p = S.panel;
    return p && p.dirty ? `Closed ${p.id ? nameOf(p.id) : 'the new step'} without saving.` : '';
  }

  function openPanel(it, { force = false, fresh = false } = {}) {
    // A step a source opens itself — on the tasks canvas, a workflow's own
    // step opens its document — mounts nothing here.
    if (it && typeof src.openItem === 'function' && src.openItem(it)) return;
    const id = it ? it.id : null;
    const p0 = S.panel;
    // The open step asked for again keeps an edited form as it is.
    if (p0 && p0.dirty && id && p0.id === id) return;
    if (!force) {
      const key = id || NEW_KEY;
      const other = id ? nameOf(id) : '';
      const ok = mayLeavePanel(key, {
        again: id ? `Open ${other} again` : `Press ${word('newLabel')} again`,
        label: id ? `Open ${other} without saving` : `${word('newLabel')} without saving`,
        retry: () => openPanel(it, { force: true }),
      });
      if (!ok) return;
    }
    const dropped = droppedSentence();
    closeConnect(false);
    closePanel(false, { swap: true });
    S.selected = id;
    markSelected();
    panel.hidden = false;
    root.classList.add('wb-panel-open');
    panelTitle.textContent = it ? it.name : word('newLabel');
    // A new step has nothing saved to plan yet.
    panelDry.hidden = !(id && src.dryRunFrom === 'item' && typeof src.dryRun === 'function');
    panelRemove.hidden = !(id && typeof src.removeItem === 'function' && !ro() && !it.fixed);
    const host = _el('div', 'wb-panel-host');
    panelBody.replaceChildren(host);
    // `B1843`. Each step's form opens at its top: the body kept the last
    // form's scroll, so a new step opened on its middle, its Name unseen.
    panelBody.scrollTop = 0;
    S.panel = {
      id, host, handle: null, dirty: false, asked: false, pendingOpen: null,
      unregister: holdEscape(() => panelEscape()),
    };
    const edited = () => {
      const p = S.panel;
      if (p && p.host === host) { p.dirty = true; p.asked = false; p.pendingOpen = null; }
    };
    host.addEventListener('input', edited);
    host.addEventListener('change', edited);
    try {
      S.panel.handle = src.openPanel(host, it, {
        onSaved: (saved) => onSaved(saved),
        onCancel: () => closePanel(true),
        // `B1836`. The form's Done was taken (the source says so before it
        // awaits anything), so a Close that pressed it waits for `onSaved`.
        onApplying: () => { const p = S.panel; if (p && p.host === host) p.applying = true; },
      });
    } catch (err) {
      console.warn('Workbench: the step form did not open', err);
      host.textContent = 'This step’s form did not open. Close the Workbench and open it again to retry.';
    }
    // `P22-06`. What the status bar offers for this step — on the tasks
    // canvas, a chained step can become a workflow.
    const offer = id && typeof src.offer === 'function' ? src.offer(id) : null;
    if (dropped) say(dropped);
    else if (offer) say(chainSentence(id), { action: offer });
    if (id) keepBeside(id);
    // `B1843`. A step just added is named first: its Name has the keyboard
    // (the picker that added it is gone, and the keyboard was left on the
    // page behind the Workbench).
    if (fresh) {
      const name = host.querySelector('[data-field="label"], [id$="task-form-name"]')
        || host.querySelector('input:not([type="hidden"]), textarea, select');
      if (name && typeof name.focus === 'function') {
        try { name.focus({ preventScroll: true }); } catch (_) { name.focus(); }
        if (typeof name.select === 'function') name.select();
      }
      panelBody.scrollTop = 0;
    }
  }

  /**
   * `B1083`. A step a person opens stays in sight beside its panel. The panel
   * takes its width from the canvas (`.wb-panel` is the viewport's flex
   * sibling), and the view was not moved: measured at 1400×860 on a run,
   * clicking *Send me the summary* opened its panel over the very box
   * clicked. While the view is still the fit, it is fitted again now to the
   * same steps in what the panel left — what the resize observer would do a
   * frame later, so it then sees no change — and then, fit or not, the view
   * is panned just enough to bring the step inside the canvas, its zoom
   * kept. A failed run's step is fitted with its neighbours since `P23-06`
   * (`applyFocusChain`); this is every other way a step is opened.
   */
  function keepBeside(id, { remember = true } = {}) {
    const p = S.pos.get(String(id));
    if (!p || S.missing.has(String(id))) return;
    const r = viewSize();
    if (!(r.width > 0 && r.height > 0)) return;
    if (S.fitted && S.fitSize && (Math.abs(r.width - S.fitSize.width) >= 8
      || Math.abs(r.height - S.fitSize.height) >= 8)) fitTo(S.fitted);
    const z = S.view.zoom;
    const w = NODE_W * z;
    const h = (p.h || NODE_H) * z;
    const left = S.view.x + p.x * z;
    const top = S.view.y + p.y * z;
    let dx = 0;
    let dy = 0;
    if (left + w > r.width - KEEP_MARGIN) dx = (r.width - KEEP_MARGIN) - (left + w);
    if (left + dx < KEEP_MARGIN) dx = KEEP_MARGIN - left;
    if (top + h > r.height - KEEP_MARGIN) dy = (r.height - KEEP_MARGIN) - (top + h);
    if (top + dy < KEEP_MARGIN) dy = KEEP_MARGIN - top;
    if (!dx && !dy) return;
    // `B1844`. What it was, so closing the panel puts it back (`viewBack`).
    const v = S.view;
    const b = S.beside;
    const untouched = b && b.set && Math.abs(v.x - b.set.x) <= 0.5 && Math.abs(v.y - b.set.y) <= 0.5 && Math.abs(v.zoom - b.set.zoom) <= 0.001;
    if (remember && !untouched) S.beside = { view: { ...v }, fitted: S.fitted, openFit: S.openFit, set: null };
    S.fitted = null; S.openFit = false;   // the view was moved for this step; a resize leaves it
    S.view = { ...S.view, x: S.view.x + dx, y: S.view.y + dy };
    if (remember && S.beside) S.beside.set = { ...S.view };
    else S.beside = null;
    applyView();
  }

  function select(id, opts2) {
    const it = S.byId.get(String(id));
    if (it && !it.missing) openPanel(it, opts2);
  }

  async function newPressed(anchor, after = null, { at = null } = {}) {
    if (ro()) return;
    if (!mayLeavePanel(NEW_KEY, {
      again: `Press ${word('newLabel')} again`,
      label: `${word('newLabel')} without saving`,
      retry: () => { if (S.panel) S.panel.pendingOpen = NEW_KEY; newPressed(anchor, after, { at }); },
    })) return;
    if (typeof src.newItem !== 'function') { openPanel(null, { force: true }); return; }
    // A source with a palette (a workflow): the new step is added to what is
    // drawn, and opened.
    let id = null;
    try {
      id = after ? await src.newItem(anchor || newBtn, after) : await src.newItem(anchor || newBtn);
    } catch (err) {
      say('Not added: ' + (_thrown(err) || 'the step could not be added.'), { refusal: true });
      return;
    }
    // `B1833`. A step added after a port comes back with what drawing its
    // arrow said when the arrow could not be drawn: the step is kept, alone.
    let refused = '';
    if (id && typeof id === 'object') { refused = String(id.sentence || ''); id = id.id; }
    if (id == null || S.destroyed) return;
    // `B1842`. A step added after a port, on an arrow or where an arrow was
    // let go stands where it was asked for — not in the corner under the
    // start, with its arrow looping back across the canvas.
    const spot = placeFor(after, at);
    if (spot) S.pinned.set(String(id), spot);
    await reload();
    if (spot) savePositions();
    select(String(id), { force: true, fresh: true });
    if (refused) say(`Added, but not joined: ${refused}`, { refusal: true });
  }

  /** Where a step added after `after` (or at `at`) should stand: right of
   *  the step it follows, on the first free row; between an arrow's ends
   *  when there is room; at the point an arrow was let go. */
  function placeFor(after, at) {
    if (at) return { x: Math.round(at.x), y: Math.round(at.y - NODE_H / 2) };
    if (!after || after.from == null) return null;
    const a = S.pos.get(String(after.from));
    if (!a) return null;
    const b = after.to != null ? S.pos.get(String(after.to)) : null;
    const GAP = 90;
    if (b && b.x - (a.x + NODE_W) >= NODE_W + 2 * 40) {
      return { x: Math.round((a.x + NODE_W + b.x) / 2 - NODE_W / 2), y: Math.round((a.y + b.y) / 2) };
    }
    const x = a.x + NODE_W + GAP;
    let y = a.y;
    const clash = (yy) => Array.from(S.pos.entries()).some(([oid, p]) => !S.missing.has(oid)
      && x < p.x + NODE_W && x + NODE_W > p.x && yy < p.y + (p.h || NODE_H) + 16 && yy + NODE_H + 16 > p.y);
    for (let i = 0; i < 12 && clash(y); i += 1) y += NODE_H + 28;
    return { x: Math.round(x), y: Math.round(y) };
  }

  // ── a dry run: every step says what it would do ──────────────────────────
  // `P22-04`. A source plans (`dryRun`), and this half only draws: `plans` is
  // every item the run could reach, once each, in the order the plan reached
  // it — the head first — each with its plan (`steps`, in a run's shape), the
  // arrow that leads to it (`when`) and, when it would not be planned, why
  // (`declined`). On the tasks canvas that is the chain dry run of
  // `/work/notes/P22-WAVE-B.md`; the server half plans and records nothing for
  // the steps after the head. A dry run sends no mail and runs nothing, and
  // that promise is the server's, not this function's.
  //
  // On the canvas: each step the run would reach says, in one short line, what
  // it would do — the plan's own "Would …" line, or for the two actions a dry
  // run cannot describe its sentence saying so — with how it is reached
  // ("After Nightly backup, if it fails"), and *Plan* opens the whole plan
  // drawn by the Tasks card's renderer. A step it would not reach is set aside
  // (dimmed, dotted, "Not reached by this run"); a step the engine would not
  // plan shows the engine's sentence. Escape, *Clear the plan* or any change
  // puts the steps back.

  /** What a step says while a plan is on the canvas, or `null` (no plan, or
   *  the source planned the head only and says nothing of this step). */
  function planFor(id, it) {
    const P = S.plan;
    if (!P) return null;
    // A kind the diagram has no word for (a workflow's start) is given none,
    // rather than the word for another: seen in Chromium, "Starts here · Prompt".
    const kindWord = KIND_WORDS[(it && it.kind) || 'llm'] || '';
    const entry = P.byId.get(id);
    if (!entry) {
      return P.partial ? null : { state: 'aside', sub: kindWord, line: 'Not reached by this run', entry: null };
    }
    // A paused step is planned (`B1036`) and says it is paused, from its own
    // status — the server's half plans it with `declined: null`.
    // `P23-05` (WB-U-7): "Starts here" once. Where the canvas draws a start of
    // its own (a workflow), the step the plan begins at reads "When it starts"
    // beneath it, as an arrow from the start does; measured on the merged tree
    // as "Starts here" over "Starts here · Prompt".
    const isStart = (x) => !!(x && (x.entry || x.kind === 'start'));
    const drawsStart = [...S.byId.values()].some(isStart);
    const first = drawsStart && !isStart(it) ? 'When it starts' : 'Starts here';
    const sub = [entry.depth === 0 ? first : entry.after, kindWord,
      it && it.paused ? 'paused' : ''].filter(Boolean).join(' · ');
    const lines = entry.steps.map((s) => String((s && s.detail) || '').trim()).filter(Boolean);
    if (!lines.length) {
      return { state: 'declined', sub, line: `Would not run: ${entry.declined || 'nothing was planned'}`, entry };
    }
    const cannot = entry.dry === DRY_CANNOT;
    const what = cannot ? CANNOT_SAY : (lines.find((l) => /^Would\b/.test(l)) || lines[0]);
    return { state: cannot ? 'cannot' : 'planned', sub, line: entry.declined ? `${entry.declined} · ${what}` : what, entry };
  }

  function dropPlan() {
    closePlanBox(false);
    const P = S.plan;
    if (!P) return;
    S.plan = null;
    P.unregister();
  }

  function clearPlan() {
    if (!S.plan) return;
    const head = S.plan.head;
    dropPlan();
    render();
    focusNode(head);
    say('');
  }

  function showPlan(headId, result, title) {
    dropPlan();
    const partial = !!result.partial;
    const raw = result.plans instanceof Map ? result.plans : new Map(Object.entries(result.plans || {}));
    const byId = new Map();
    for (const [key, e] of raw) {
      const id = String(key);
      if (!id || byId.has(id) || !e) continue;
      byId.set(id, {
        id, when: e.when ? String(e.when) : null, depth: Number(e.depth) || 0,
        steps: Array.isArray(e.steps) ? e.steps : [], declined: e.declined ? String(e.declined) : null, after: '',
        dry: e.dry ? String(e.dry) : null,
      });
    }
    // How each step is reached: from its first parent in the plan's order,
    // which is where the contract takes `when` from.
    const order = [...byId.keys()];
    order.forEach((id, i) => {
      const e = byId.get(id);
      if (!e.depth || !e.when) return;
      const parent = order.slice(0, i).find((p) => (S.graph.edges || [])
        .some((g) => g.from === p && g.to === id && g.when === e.when));
      const words = parent ? portWord(parent, e.when) : (EDGE_WORDS[e.when] || e.when);
      e.after = parent && isEntry(parent) ? 'When it starts'
        : parent ? `After ${nameOf(parent)}, ${words}` : _cap(words);
    });
    const head = String(result.head || headId || order[0] || '');
    const dirty = !!(S.panel && S.panel.dirty);
    if (S.panel && !dirty) closePanel(false);
    S.plan = { head, byId, partial, unregister: holdEscape(() => clearPlan()) };
    render();
    focusNode(head);
    const name = title || nameOf(head);
    // `P23-05` (COPY-U-24, Doc 2 § 5): what happened, counted once.
    let sentence = `Dry run of ${name} — nothing ran.`;
    if (!partial) {
      const reached = byId.size;
      const aside = S.order.filter((id) => !byId.has(id) && S.nodeEls.has(id)).length;
      sentence += ` ${reached} ${reached === 1 ? 'step' : 'steps'} planned`
        + (aside ? `; ${aside} unreachable, dimmed.` : '.');
    } else {
      sentence += ` Only ${name} was planned: this Pantheon did not plan the steps after it.`;
    }
    if (dirty) sentence += ` Your unsaved changes to ${nameOf(S.panel.id || head)} are not in this plan.`;
    if (result.sentence) sentence += ' ' + String(result.sentence);
    say(sentence, { action: { label: 'Clear the plan', run: () => clearPlan() } });
  }

  /** Plan a run. `id` is the head on a source that plans from a step; a
   *  workflow's source plans the whole document and is asked with none.
   *  `opts.title` names what was planned when the head's name would not (a
   *  workflow's start). */
  async function dryRun(id, { title = '' } = {}) {
    if (S.dryBusy || typeof src.dryRun !== 'function') return null;
    S.dryBusy = true;
    panelDry.disabled = true;
    panelDry.textContent = 'Working it out…';
    const name = title || nameOf(id);
    say(`Working out what a run of ${name} would do. Nothing is running.`);
    let result = null;
    try {
      result = await (id != null ? src.dryRun(id) : src.dryRun());
    } catch (err) {
      result = { ok: false, sentence: _thrown(err) };
    }
    S.dryBusy = false;
    panelDry.disabled = false;
    panelDry.textContent = DRY_LABEL;
    if (S.destroyed) return null;
    if (!result || !result.ok) {
      // The source's own sentence: a loop (`P22-01`'s rule, as a save is
      // answered), "Task is already running", an admin-only action.
      const sentence = (result && result.sentence) || 'nothing was planned';
      say(`Nothing was planned: ${sentence.replace(/\.$/, '')}.`, { refusal: true });
      return null;
    }
    showPlan(id, result, title);
    return result;
  }

  // ── the whole plan, on demand ────────────────────────────────────────────
  function closePlanBox(restoreFocus) {
    const b = S.planBox;
    if (!b) return;
    S.planBox = null;
    b.unregister();
    b.box.remove();
    if (restoreFocus) focusNode(b.id);
  }

  function openPlanBox(id) {
    closePlanBox(false);
    closeConnect(false);
    const entry = S.plan && S.plan.byId.get(id);
    if (!entry) return;
    const name = nameOf(id);
    const box = _el('div', 'wb-plan-box');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', `What ${name} would do`);
    box.appendChild(_el('p', 'wb-plan-head', `What ${name} would do`));
    if (entry.after) box.appendChild(_el('p', 'wb-plan-when', `${entry.after}.`));
    if (entry.declined) box.appendChild(_el('p', 'wb-plan-declined', entry.declined));
    const body = _el('div', 'wb-plan-steps');
    if (entry.steps.length && renderSteps) {
      // The Tasks card's step renderer (`tasks.js:renderRunSteps`), which
      // escapes every value it is given with `ui.js:esc`: the one place this
      // room assigns markup, and the markup is that renderer's, not data's.
      body.innerHTML = renderSteps({ steps: entry.steps }, { open: true, summary: 'What a real run would do' });
    } else if (entry.steps.length) {
      const list = _el('ol', 'wb-plan-lines');
      for (const s of entry.steps) list.appendChild(_el('li', null, String((s && s.detail) || '')));
      body.appendChild(list);
    }
    box.appendChild(body);
    const close = _el('button', 'wb-plan-close', 'Close');
    close.type = 'button';
    close.addEventListener('click', () => closePlanBox(true));
    box.appendChild(close);
    besideStep(box, id, PLAN_W);
    stage.appendChild(box);
    S.planBox = { box, id, unregister: holdEscape(() => closePlanBox(true)) };
    close.focus();
  }

  // ── opening on one workflow ──────────────────────────────────────────────
  function chainSentence(id) {
    const steps = [...componentOf(S.graph, id).ids].filter((x) => S.pos.has(x));
    return steps.length > 1
      ? `${nameOf(id)} is one of ${steps.length} steps in this workflow.`
      : `${nameOf(id)} runs on its own. Drag from “${EDGE_WORDS.success}” or “${EDGE_WORDS.error}” to chain a step to it.`;
  }

  function applyFocusChain() {
    const id = S.focusId;
    if (!id || !S.loaded) return;
    S.focusId = null;
    // `B1048`. Opened on a built-in task (⋮ → Workflow on its card): its
    // workflow is shown, the other built-ins stay aside.
    if (S.hidden.has(id)) {
      componentOf(S.graph, id).ids.forEach((x) => S.reveal.add(x));
      render();
    }
    if (!S.pos.has(id) || S.missing.has(id)) {
      say('That task is not on the canvas any more.');
      return;
    }
    const comp = componentOf(S.graph, id);
    const steps = [...comp.ids].filter((x) => S.pos.has(x));
    // `P23-06` (WB-M-2). With a step's panel open beside the canvas — a failed
    // or waiting run opens on its step — the whole chain was fitted into what
    // the panel left and hit the floor. The step and its neighbours are fitted
    // instead; the rest of the chain is a pan away.
    const near = S.panel ? steps.filter((x) => x === id || S.graph.edges.some((e) =>
      (e.from === id && e.to === x) || (e.to === id && e.from === x))) : steps;
    fitTo(boundsOf((near.length ? near : steps).map((x) => S.pos.get(x))));
    for (const [nid, node] of S.nodeEls) node.classList.toggle('wb-node-chain', comp.ids.has(nid));
    focusNode(id);
    say(chainSentence(id), { action: typeof src.offer === 'function' ? src.offer(id) : null });
  }

  function focusChain(id) {
    S.focusId = id == null ? null : String(id);
    applyFocusChain();
  }

  // ── panning and zooming ──────────────────────────────────────────────────
  // `B1835`. Each pointer on the empty canvas is kept by its id: one pans,
  // two pinch — the zoom follows the fingers' spread around their midpoint
  // and the view follows the midpoint. One `S.pan` for every pointer moved
  // the view in jumps the size of the fingers' gap and never zoomed
  // (measured with two touch points: 50 px at the first move, zoom 71%
  // throughout). A finger lifted hands the pan to the one still down.
  const touches = new Map();
  const panFrom = (id) => {
    const t = touches.get(id);
    S.pan = t ? { pointerId: id, cx: t.x, cy: t.y, x0: S.view.x, y0: S.view.y } : null;
  };
  const pinchNow = () => {
    const [a, b] = Array.from(touches.values());
    const r = viewportRect();
    return { d: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)), mx: (a.x + b.x) / 2 - r.left, my: (a.y + b.y) / 2 - r.top };
  };
  viewport.addEventListener('pointerdown', (e) => {
    if (e.button != null && e.button !== 0) return;
    if (e.target !== viewport && e.target !== world) return;
    try { if (!viewport.contains(document.activeElement)) viewport.focus({ preventScroll: true }); } catch (_) { /* no focus here: a test */ }
    touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    try { if (viewport.setPointerCapture) viewport.setPointerCapture(e.pointerId); } catch (_) { /* a synthetic pointer */ }
    root.classList.add('wb-panning');
    if (touches.size === 2) {
      const p = pinchNow();
      S.pan = null;
      S.pinch = { d0: p.d, z0: S.view.zoom, wx: (p.mx - S.view.x) / S.view.zoom, wy: (p.my - S.view.y) / S.view.zoom };
      return;
    }
    if (touches.size > 2) return;
    // `B1841`. Shift-drag on the empty canvas draws a box: the steps it
    // touches are picked together.
    if (e.shiftKey && canPick()) { startBox(e); return; }
    S.pan = { pointerId: e.pointerId, cx: e.clientX, cy: e.clientY, x0: S.view.x, y0: S.view.y, moved: false };
  });
  viewport.addEventListener('pointermove', (e) => {
    if (touches.has(e.pointerId)) touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (S.pinch && touches.size >= 2) {
      const p = pinchNow();
      const z = clampZoom(S.pinch.z0 * (p.d / S.pinch.d0));
      S.fitted = null; S.openFit = false;
      S.view = { zoom: z, x: p.mx - S.pinch.wx * z, y: p.my - S.pinch.wy * z };
      applyView();
      return;
    }
    if (S.box) { moveBox(e); return; }
    const p = S.pan;
    if (!p || (p.pointerId != null && e.pointerId != null && p.pointerId !== e.pointerId)) return;
    if (!p.moved && Math.abs(e.clientX - p.cx) <= MOVE_THRESHOLD && Math.abs(e.clientY - p.cy) <= MOVE_THRESHOLD) return;
    p.moved = true;
    S.fitted = null; S.openFit = false;
    S.view = { ...S.view, x: p.x0 + (e.clientX - p.cx), y: p.y0 + (e.clientY - p.cy) };
    applyView();
  });
  const endPan = (e) => {
    if (S.box) { endBox(e); touches.clear(); root.classList.remove('wb-panning'); return; }
    // A press on the empty canvas that did not move lets go of the picks.
    if (S.pan && !S.pan.moved && touches.size <= 1 && S.sel.size) clearPicks();
    if (e && e.pointerId != null) touches.delete(e.pointerId); else touches.clear();
    if (S.pinch && touches.size < 2) {
      S.pinch = null;
      const rest = Array.from(touches.keys())[0];
      if (rest != null) { panFrom(rest); return; }
    }
    if (touches.size) return;
    S.pan = null;
    root.classList.remove('wb-panning');
  };
  viewport.addEventListener('pointerup', endPan);
  viewport.addEventListener('pointercancel', endPan);
  viewport.addEventListener('contextmenu', (e) => {
    if (!e || (e.target !== viewport && e.target !== world)) return;
    const items = canvasMenu(toWorld(e.clientX, e.clientY));
    if (!items.length) return;
    e.preventDefault();
    openMenu(items, e.clientX, e.clientY, viewport);
  });
  viewport.addEventListener('wheel', (e) => {
    if (e.preventDefault) e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      const r = viewportRect();
      zoomAt(Math.exp(-(Number(e.deltaY) || 0) * 0.0015), e.clientX - r.left, e.clientY - r.top);
    } else {
      S.fitted = null; S.openFit = false;
      S.view = { ...S.view, x: S.view.x - (Number(e.deltaX) || 0), y: S.view.y - (Number(e.deltaY) || 0) };
      applyView();
    }
  }, { passive: false });
  // `P23-06` (WB-M-3, WB-M-5). The viewport changes size after the first fit —
  // the window settling, a Versions… or Check them now box opening above the
  // canvas (it pushed the steps off the bottom edge), a panel opening beside
  // it. While the view is still the fit (the person has not panned or zoomed),
  // it is fitted again to the same steps.
  if (typeof ResizeObserver === 'function') {
    S.resizeObs = new ResizeObserver(() => {
      if (S.destroyed || !(S.fitted || S.openFit) || !S.fitSize) return;
      const r = viewSize();
      if (Math.abs(r.width - S.fitSize.width) < 8 && Math.abs(r.height - S.fitSize.height) < 8) return;
      if (S.openFit) { openView(); return; }
      fitTo(S.fitted);
    });
    try { S.resizeObs.observe(viewport); } catch (_) { S.resizeObs = null; }
  }
  viewport.addEventListener('keydown', (e) => { if (e.target === viewport) zoomKeys(e); });
  // `B1844`. The viewport is a clipped window onto a transformed drawing; it
  // never scrolls itself (a focus or a find-in-page could scroll it).
  viewport.addEventListener('scroll', () => {
    if (viewport.scrollLeft || viewport.scrollTop) { viewport.scrollLeft = 0; viewport.scrollTop = 0; }
  });

  // ── the toolbar ──────────────────────────────────────────────────────────
  newBtn.addEventListener('click', () => newPressed(newBtn));
  emptyNew.addEventListener('click', () => newPressed(emptyNew));
  panelClose.addEventListener('click', () => panelCloseClick());
  panelDry.addEventListener('click', () => { if (S.panel && S.panel.id) dryRun(S.panel.id); });
  panelRemove.addEventListener('click', () => { if (S.panel && S.panel.id) askRemove(S.panel.id); });
  mapBtn.addEventListener('click', () => {
    mapOn = !mapOn;
    try { localStorage.setItem(MAP_KEY, mapOn ? 'on' : 'off'); } catch (_) { /* this visit only */ }
    drawMap();
  });
  map.addEventListener('pointerdown', (e) => {
    if (e.button != null && e.button !== 0) return;
    if (e.stopPropagation) e.stopPropagation();
    S.mapDrag = { pointerId: e.pointerId };
    try { if (map.setPointerCapture) map.setPointerCapture(e.pointerId); } catch (_) { /* a synthetic pointer */ }
    mapPan(e);
  });
  map.addEventListener('pointermove', (e) => { if (S.mapDrag) mapPan(e); });
  const endMap = () => { S.mapDrag = null; };
  map.addEventListener('pointerup', endMap);
  map.addEventListener('pointercancel', endMap);
  outBtn.addEventListener('click', () => zoomBy(1 / ZOOM_STEP));
  inBtn.addEventListener('click', () => zoomBy(ZOOM_STEP));
  fitBtn.addEventListener('click', () => fitAll());
  builtinsBox.addEventListener('change', () => {
    S.showBuiltins = !!builtinsBox.checked;
    if (!S.showBuiltins) S.reveal = new Set();
    render();
    fitAll();
    const n = S.items.filter((i) => i.builtin).length;
    say(S.showBuiltins ? `Showing the ${n} built-in tasks Pantheon comes with.`
      : 'The built-in tasks are hidden. A built-in task joined to one of yours stays.');
  });
  tidyBtn.addEventListener('click', () => {
    S.pinned = new Map();
    S.pos = new Map();
    render();
    fitAll();
    savePositions();
    if (typeof src.undo === 'function') {
      say('Laid out again. Undo puts every step back where it was.', { action: { label: 'Undo', run: () => undoPressed() } });
    } else {
      say('Laid out again. Drag a step to put it somewhere else.');
    }
  });
  undoBtn.addEventListener('click', () => undoPressed());
  redoBtn.addEventListener('click', () => redoPressed());
  keysBtn.addEventListener('click', () => toggleKeys());

  // ── `B1841`: many steps at once ──────────────────────────────────────────
  // n8n's and Node-RED's basics, on this canvas: Shift/Ctrl/Cmd-click and a
  // Shift-drawn box pick steps together, Ctrl+A picks every one; picked
  // steps move together, Delete removes them (said first, as one step's is),
  // and copy, cut, paste and Ctrl+D duplicate them (`B1840`). Only for a
  // source that edits steps (a workflow's draft); a run and the tasks canvas
  // draw no picks.
  function canPick() { return !ro() && typeof src.removeItem === 'function'; }
  const pickable = (id) => { const it = S.byId.get(String(id)); return !!it && !it.missing && !it.fixed && S.nodeEls.has(String(id)); };
  function syncSelEsc() {
    if (S.sel.size && !S.selEsc) {
      S.selEsc = holdEscape(() => { S.selEsc = null; clearPicks(); say(''); });
    } else if (!S.sel.size && S.selEsc) {
      const release = S.selEsc;
      S.selEsc = null;
      release();
    }
  }
  function pickOnly(ids) {
    S.sel = new Set((ids || []).map(String).filter(pickable));
    markSelected();
    syncSelEsc();
    if (S.sel.size > 1) say(`${S.sel.size} steps picked. Drag one to move them together; Delete, Ctrl+C or Ctrl+D act on all of them.`);
  }
  function togglePick(id) {
    const next = new Set(S.sel);
    if (S.selected && pickable(S.selected) && !next.size) next.add(S.selected);
    if (next.has(String(id))) next.delete(String(id)); else next.add(String(id));
    if (S.panel && !S.panel.dirty) closePanel(false);
    pickOnly(Array.from(next));
    if (S.sel.size === 1) say(`${nameOf(Array.from(S.sel)[0])} picked. Shift-click more steps to pick them too.`);
    focusNode(id);
  }
  function clearPicks() {
    if (!S.sel.size) return;
    S.sel = new Set();
    markSelected();
    syncSelEsc();
  }
  /** What a copy, a cut or a duplicate acts on: the picks, or the step that
   *  has the keyboard or its panel open. */
  function actedOn() {
    if (S.sel.size) return Array.from(S.sel);
    const c = S.current && S.current.kind === 'node' ? S.current.id : S.selected;
    return c && pickable(c) ? [String(c)] : [];
  }

  function startBox(e) {
    const el = _el('div', 'wb-select-box');
    viewport.appendChild(el);
    S.box = { pointerId: e.pointerId, cx: e.clientX, cy: e.clientY, el, add: new Set(S.sel) };
    moveBox(e);
  }
  function boxRect(e, b = S.box) {
    const r = viewportRect();
    const x1 = Math.min(b.cx, e.clientX) - r.left;
    const y1 = Math.min(b.cy, e.clientY) - r.top;
    return { x: x1, y: y1, w: Math.abs(e.clientX - b.cx), h: Math.abs(e.clientY - b.cy) };
  }
  function moveBox(e) {
    const b = S.box;
    if (!b) return;
    const q = boxRect(e);
    b.el.style.left = q.x + 'px';
    b.el.style.top = q.y + 'px';
    b.el.style.width = q.w + 'px';
    b.el.style.height = q.h + 'px';
  }
  function endBox(e) {
    const b = S.box;
    S.box = null;
    if (!b) return;
    const q = boxRect(e, b);
    b.el.remove();
    const z = S.view.zoom;
    const wx = (q.x - S.view.x) / z;
    const wy = (q.y - S.view.y) / z;
    const ww = q.w / z;
    const wh = q.h / z;
    const hit = [];
    for (const [id, p] of S.pos) {
      if (!pickable(id)) continue;
      if (p.x < wx + ww && p.x + NODE_W > wx && p.y < wy + wh && p.y + (p.h || NODE_H) > wy) hit.push(id);
    }
    pickOnly([...b.add, ...hit]);
    if (!S.sel.size) say('Nothing picked: draw the box over the steps you want.');
  }

  function askRemoveMany(ids) {
    const list = ids.map(String).filter(pickable);
    if (!list.length) return;
    if (list.length === 1) { askRemove(list[0]); return; }
    const key = 'many\u0000' + list.slice().sort().join('\u0000');
    if (S.pending && S.pending.key === key) { removeMany(list); return; }
    clearPending();
    S.pending = { key, unregister: holdEscape(() => { S.pending = null; say(`Kept the ${list.length} steps.`); }) };
    say(`Remove these ${list.length} steps? Press Delete again to remove them, or Escape to keep them.`,
      { action: { label: `Remove ${list.length} steps`, run: () => removeMany(list) } });
  }
  async function removeMany(ids) {
    clearPending();
    let res;
    try {
      res = typeof src.removeItems === 'function' ? await src.removeItems(ids) : null;
      if (!res) {
        for (const id of ids) {
          res = await src.removeItem(id);
          if (res && res.ok === false) break;
        }
      }
    } catch (err) { res = { ok: false, sentence: _thrown(err) }; }
    if (!res || res.ok === false) {
      say('Not removed: ' + ((res && res.sentence) || 'The change was refused.'), { refusal: true });
      await reload();
      return;
    }
    if (S.panel && ids.includes(S.panel.id)) closePanel(false);
    for (const id of ids) S.pinned.delete(id);
    clearPicks();
    await reload();
    say(`Removed ${ids.length} steps.` + (res.sentence ? ' ' + res.sentence : '')
      + (typeof src.undo === 'function' ? ' Ctrl+Z puts them back.' : ''));
  }

  // ── `B1840`: copy, cut, paste, duplicate ─────────────────────────────────
  // The clipboard's own events, so a copy reaches another workflow, another
  // window or a text file (the steps as JSON); the last copy is also kept
  // here for the menu's Paste, which has no clipboard event to read.
  const CLIP_PREF = 'pantheon.workbench.clip';
  const canClip = () => typeof src.copyItems === 'function' && typeof src.pasteItems === 'function';
  function keepClip(clip) {
    try { localStorage.setItem(CLIP_PREF, JSON.stringify(clip)); } catch (_) { /* this visit only */ }
    S.clip = clip;
  }
  function lastClip() {
    if (S.clip) return S.clip;
    try { const t = localStorage.getItem(CLIP_PREF); return t ? JSON.parse(t) : null; } catch (_) { return null; }
  }
  const editable = (t) => !!(t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(String(t.tagName || ''))));
  /** A key or a clipboard event the canvas may take: not typed into a
   *  field, not inside the step's panel or the Connect… box. */
  function ours(e) {
    const t = e && e.target;
    if (!t || editable(t)) return false;
    for (let n = t; n && n !== root; n = n.parentNode) {
      if (n === panel || (S.connect && n === S.connect.box) || n.classList?.contains?.('wb-menu')) return false;
    }
    return true;
  }
  function copyNow(ids, verb = 'Copied') {
    const clip = canClip() ? src.copyItems(ids) : null;
    if (!clip) return null;
    keepClip(clip);
    const n = clip.nodes.length;
    say(`${verb} ${n === 1 ? `“${clip.nodes[0].label}”` : `${n} steps`}. Ctrl+V pastes ${n === 1 ? 'it' : 'them'} here or in another workflow.`);
    return clip;
  }
  async function pasteNow(clip, at = null) {
    if (!canClip() || ro()) return;
    const r = viewportRect();
    const centre = at || toWorld(r.left + r.width / 2 - (NODE_W * S.view.zoom) / 2, r.top + r.height / 3);
    let res;
    try { res = await src.pasteItems(clip, { at: centre }); } catch (err) { res = { ok: false, sentence: _thrown(err) }; }
    if (!res || res.ok === false) { say('Not pasted: ' + ((res && res.sentence) || 'there were no steps to paste.'), { refusal: true }); return; }
    // Where the pasted steps stand comes from the clip (the source placed
    // them); read again so they are drawn there.
    await reloadPlaces();
    pickOnly(res.ids || []);
    if ((res.ids || [])[0]) focusNode(res.ids[0]);
    say(res.sentence || 'Pasted.');
  }
  async function duplicateNow() {
    const ids = actedOn();
    if (!ids.length) { say('Pick a step first, then Ctrl+D duplicates it.'); return; }
    const clip = canClip() ? src.copyItems(ids) : null;
    if (!clip) return;
    let res;
    try { res = await src.pasteItems(clip, { offset: { x: 36, y: NODE_H + 36 } }); } catch (err) { res = { ok: false, sentence: _thrown(err) }; }
    if (!res || res.ok === false) { say('Not duplicated: ' + ((res && res.sentence) || 'the step could not be copied.'), { refusal: true }); return; }
    await reloadPlaces();
    pickOnly(res.ids || []);
    if ((res.ids || [])[0]) focusNode(res.ids[0]);
    say(String(res.sentence || 'Duplicated.').replace(/^Pasted/, 'Duplicated'));
  }
  root.addEventListener('copy', (e) => {
    if (!ours(e) || !canClip()) return;
    const ids = actedOn();
    if (!ids.length) return;
    const clip = copyNow(ids);
    if (!clip) return;
    try { e.clipboardData.setData('text/plain', JSON.stringify(clip, null, 2)); e.preventDefault(); } catch (_) { /* kept here */ }
  });
  root.addEventListener('cut', (e) => {
    if (!ours(e) || !canClip() || ro()) return;
    const ids = actedOn();
    if (!ids.length) return;
    const clip = copyNow(ids, 'Cut');
    if (!clip) return;
    try { e.clipboardData.setData('text/plain', JSON.stringify(clip, null, 2)); e.preventDefault(); } catch (_) { /* kept here */ }
    removeMany(ids);
  });
  root.addEventListener('paste', (e) => {
    if (!ours(e) || !canClip() || ro()) return;
    let clip = null;
    try { clip = JSON.parse(e.clipboardData.getData('text/plain') || 'null'); } catch (_) { clip = null; }
    if (!clip || !Array.isArray(clip.nodes)) return;   // not steps: the page's own paste
    e.preventDefault();
    pasteNow(clip);
  });

  // ── `B1851`: what would stop Save, marked on the steps ───────────────────
  /** Marks each step a problem names (a ring and a "!" that says it), from
   *  the source's `problems()`; the rest are unmarked. Cheap: no redraw. */
  function markProblems() {
    const list = !ro() && typeof src.problems === 'function' ? (src.problems() || []) : [];
    const by = new Map();
    for (const p of list) {
      for (const id of (p.nodeIds || [])) {
        const k = String(id);
        if (!by.has(k)) by.set(k, []);
        by.get(k).push(String(p.sentence || ''));
      }
    }
    for (const [id, el] of S.nodeEls) {
      const said = by.get(String(id));
      let badge = el.querySelector('.wb-node-problem');
      if (!said) {
        if (el.dataset.problem) delete el.dataset.problem;
        if (badge) badge.remove();
        continue;
      }
      el.dataset.problem = 'true';
      if (!badge) {
        badge = _el('span', 'wb-node-problem', '!');
        badge.setAttribute('role', 'img');
        el.appendChild(badge);
      }
      const text = said.join(' ');
      badge.title = text;
      badge.setAttribute('aria-label', `Cannot be saved yet: ${text}`);
    }
    return by;
  }

  // ── `B1839`: undo and redo ───────────────────────────────────────────────
  function syncTools() {
    const st = typeof src.state === 'function' ? (src.state() || {}) : {};
    const h = st.history || { undo: 0, redo: 0 };
    undoBtn.disabled = ro() || !h.undo;
    redoBtn.disabled = ro() || !h.redo;
    undoBtn.hidden = typeof src.undo !== 'function' || ro();
    redoBtn.hidden = typeof src.redo !== 'function' || ro();
    markProblems();
  }
  /** Read where the steps stand again, as the source has them (an undo can
   *  move them back): a step the source places is drawn there, one it no
   *  longer places is laid out, and the rest stay where they are. */
  async function reloadPlaces() {
    let pins;
    try { pins = _points(await src.loadPositions()); } catch (_) { pins = S.pinned; }
    const pos = new Map();
    for (const [id, p] of S.pos) {
      if (pins.has(id)) pos.set(id, { ...p, ...pins.get(id) });
      else if (!S.pinned.has(id)) pos.set(id, p);
    }
    S.pinned = pins;
    S.pos = pos;
    return reload();
  }
  async function historyPressed(verb) {
    if (ro() || typeof src[verb] !== 'function') return;
    if (S.panel && S.panel.dirty) {
      say(`${panelName(S.panel)} has changes that are not kept yet. Press Done or Close first, then ${verb === 'undo' ? 'Undo' : 'Redo'}.`);
      return;
    }
    let res;
    try { res = await src[verb](); } catch (err) { res = { ok: false, sentence: _thrown(err) }; }
    if (S.destroyed) return;
    if (!res || res.ok === false) { say((res && res.sentence) || `Nothing to ${verb}.`); syncTools(); return; }
    if (S.panel) closePanel(false);
    clearPicks();
    await reloadPlaces();
    syncTools();
    say(res.sentence || (verb === 'undo' ? 'Undone.' : 'Done again.'));
  }
  const undoPressed = () => historyPressed('undo');
  const redoPressed = () => historyPressed('redo');

  // ── the keys, anywhere on the canvas ─────────────────────────────────────
  root.addEventListener('keydown', (e) => {
    if (!e || !ours(e)) return;
    const mod = (e.ctrlKey || e.metaKey) && !e.altKey;
    const k = String(e.key || '').toLowerCase();
    if (mod && k === 'z' && !e.shiftKey && typeof src.undo === 'function') { e.preventDefault(); undoPressed(); return; }
    if (mod && ((k === 'z' && e.shiftKey) || k === 'y') && typeof src.redo === 'function') { e.preventDefault(); redoPressed(); return; }
    if (mod && k === 'a' && canPick()) {
      e.preventDefault();
      pickOnly(Array.from(S.nodeEls.keys()).filter(pickable));
      return;
    }
    if (mod && k === 'd' && canPick() && canClip()) { e.preventDefault(); duplicateNow(); return; }
    if (!mod && !e.altKey && e.key === '?') { e.preventDefault(); toggleKeys(); return; }
    if (!mod && !e.altKey && (e.key === 'Delete' || e.key === 'Backspace') && S.sel.size > 1 && canPick()) {
      // On a picked step the step's own handler said it already.
      if (e.defaultPrevented) return;
      e.preventDefault();
      askRemoveMany(Array.from(S.sel));
    }
  });

  // ── a right-click menu ───────────────────────────────────────────────────
  function closeMenu(restore) {
    const m = S.menu;
    if (!m) return;
    S.menu = null;
    m.unregister();
    m.box.remove();
    document.removeEventListener('pointerdown', m.outside, true);
    if (restore && m.opener && typeof m.opener.focus === 'function') m.opener.focus();
  }
  function openMenu(items, cx, cy, opener) {
    closeMenu(false);
    const list = (items || []).filter(Boolean);
    if (!list.length) return;
    const box = _el('div', 'wb-menu');
    box.setAttribute('role', 'menu');
    const buttons = [];
    for (const it of list) {
      if (it.sep) { box.appendChild(_el('div', 'wb-menu-sep')); continue; }
      const b = _el('button', 'wb-menu-item');
      b.type = 'button';
      b.setAttribute('role', 'menuitem');
      b.appendChild(_el('span', 'wb-menu-word', it.label));
      if (it.keys) b.appendChild(_el('kbd', 'wb-menu-keys', it.keys));
      if (it.danger) b.dataset.tone = 'danger';
      b.disabled = !!it.disabled;
      b.addEventListener('click', () => { closeMenu(false); it.run(); });
      box.appendChild(b);
      buttons.push(b);
    }
    box.addEventListener('keydown', (e) => {
      const i = buttons.indexOf(e.target);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const live = buttons.filter((b) => !b.disabled);
        const j = live.indexOf(e.target);
        const next = live[(j + (e.key === 'ArrowDown' ? 1 : live.length - 1)) % live.length];
        if (next) next.focus();
      } else if (e.key === 'Tab') { closeMenu(false); } else if (i < 0) { /* nothing */ }
    });
    stage.appendChild(box);
    try {
      const r = stage.getBoundingClientRect();
      const w = 220;
      box.style.left = Math.max(6, Math.min(Math.round(cx - r.left), Math.round(r.width - w - 6))) + 'px';
      box.style.top = Math.max(6, Math.min(Math.round(cy - r.top), Math.round(r.height - 40 * list.length - 6))) + 'px';
    } catch (_) { /* no layout: a test */ }
    const outside = (ev) => { if (S.menu && !box.contains(ev.target)) closeMenu(false); };
    document.addEventListener('pointerdown', outside, true);
    S.menu = { box, opener, outside, unregister: holdEscape(() => closeMenu(true)) };
    const first = buttons.find((b) => !b.disabled);
    if (first) first.focus();
  }
  function nodeMenu(id) {
    const it = S.byId.get(String(id));
    if (!it) return [];
    const edit = !ro() && !it.fixed && !it.missing;
    const many = S.sel.size > 1 && S.sel.has(String(id));
    const ids = many ? Array.from(S.sel) : [String(id)];
    const off = !!it.disabled;
    return [
      { label: it.fixed ? 'Open the start' : 'Open', run: () => { clearPicks(); select(id); } },
      edit && canClip() && { label: many ? `Duplicate ${ids.length} steps` : 'Duplicate', keys: 'Ctrl+D',
        run: () => { if (!many) pickOnly([String(id)]); duplicateNow(); } },
      edit && canClip() && { label: many ? `Copy ${ids.length} steps` : 'Copy', keys: 'Ctrl+C', run: () => copyNow(ids) },
      edit && typeof src.setDisabled === 'function' && !many && {
        label: off ? 'Switch it on' : 'Switch it off (pass its input on)',
        run: async () => {
          const r = await src.setDisabled(id, !off);
          await reload();
          say(r && r.ok === false ? `Not changed: ${r.sentence}` : ((r && r.sentence) || ''), { refusal: !!(r && r.ok === false) });
        },
      },
      edit && { sep: true },
      edit && typeof src.removeItem === 'function' && { label: many ? `Remove ${ids.length} steps` : 'Remove', keys: 'Delete', danger: true,
        run: () => (many ? askRemoveMany(ids) : askRemove(id)) },
    ];
  }
  function canvasMenu(at) {
    if (ro()) return [{ label: 'Fit every step', keys: '0', run: () => fitAll() }];
    const clip = canClip() ? lastClip() : null;
    return [
      canAddAfter() && typeof src.newItem === 'function' && { label: 'Add a step here', run: () => newPressed(newBtn, null, { at }) },
      clip && Array.isArray(clip.nodes) && { label: `Paste ${clip.nodes.length === 1 ? '1 step' : `${clip.nodes.length} steps`}`, keys: 'Ctrl+V',
        run: () => pasteNow(clip, at) },
      canPick() && { label: 'Pick every step', keys: 'Ctrl+A', run: () => pickOnly(Array.from(S.nodeEls.keys()).filter(pickable)) },
      { sep: true },
      { label: 'Tidy up', run: () => tidyBtn.click() },
      { label: 'Fit every step', keys: '0', run: () => fitAll() },
    ];
  }

  // ── the keys sheet ───────────────────────────────────────────────────────
  const KEY_ROWS = [
    ['Click a step', 'Open it'], ['Shift-click, or Shift-drag a box', 'Pick several steps'],
    ['Ctrl+A', 'Pick every step'], ['Drag a port onto a step', 'Join them'],
    ['Drag a port onto empty canvas', 'Add a step joined to it'], ['+ on a port or an arrow', 'Add the next step there'],
    ['Delete (twice)', 'Remove what is picked'], ['Ctrl+C · Ctrl+X · Ctrl+V', 'Copy, cut, paste steps'],
    ['Ctrl+D', 'Duplicate'], ['Ctrl+Z · Ctrl+Shift+Z', 'Undo · Redo'], ['Ctrl+S', 'Save the workflow'],
    ['Arrow keys', 'Go from step to step'], ['M, then arrows', 'Move a step'],
    ['+ · − · 0', 'Zoom in · out · fit'], ['Right-click', 'More for a step or the canvas'], ['Escape', 'Close or let go'],
  ];
  function toggleKeys() {
    if (S.keys) { const k = S.keys; S.keys = null; k.unregister(); k.box.remove(); keysBtn.setAttribute('aria-expanded', 'false'); return; }
    const box = _el('div', 'wb-keys');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Keyboard shortcuts');
    box.appendChild(_el('p', 'wb-keys-head', 'Shortcuts'));
    const dl = _el('dl', 'wb-keys-list');
    for (const [keys, what] of KEY_ROWS) {
      dl.appendChild(_el('dt', null, keys));
      dl.appendChild(_el('dd', null, what));
    }
    box.appendChild(dl);
    const close = _el('button', 'wb-keys-close', 'Close');
    close.type = 'button';
    close.addEventListener('click', () => toggleKeys());
    box.appendChild(close);
    stage.appendChild(box);
    S.keys = { box, unregister: holdEscape(() => { if (S.keys) { S.keys.box.remove(); S.keys = null; keysBtn.setAttribute('aria-expanded', 'false'); keysBtn.focus(); } }) };
    keysBtn.setAttribute('aria-expanded', 'true');
    close.focus();
  }

  // ── start ────────────────────────────────────────────────────────────────
  const ready = Promise.all([
    Promise.resolve().then(() => src.loadPositions()).then(_points, () => new Map()),
    Promise.resolve().then(() => src.load()).then((d) => ({ d }), (err) => ({ err })),
  ]).then(([pins, got]) => {
    if (S.destroyed) return false;
    S.pinned = pins;
    if (got.err) {
      say(word('loadFailed'), { refusal: true });
      return false;
    }
    take(got.d);
    render();
    S.loaded = true;
    applyFocusChain();
    return true;
  });

  function destroy() {
    if (S.destroyed) return;
    if (S.saveTimer) savePositions();
    S.destroyed = true;
    if (S.resizeObs) { try { S.resizeObs.disconnect(); } catch (_) { /* gone with the room */ } S.resizeObs = null; }
    endMove();
    endLink(null);
    closeMenu(false);
    if (S.keys) toggleKeys();
    if (S.selEsc) { const r = S.selEsc; S.selEsc = null; r(); }
    clearPending();
    closeConnect(false);
    dropPlan();
    closePanel(false);
    root.replaceChildren();
    root.classList.remove('wb-room', 'wb-panel-open', 'wb-room-empty', 'wb-linking', 'wb-panning', 'wb-read-only');
    delete root.dataset.escLayer;
  }

  return {
    ready,
    reload,
    refreshOutcomes,
    focusChain,
    select: (id) => select(id),
    destroy,
    flush: () => savePositions(),
    say,
    newStep: () => newPressed(newBtn),
    dryRun: (id, o) => dryRun(id, o),
    /** What is drawn, as the source last loaded it. */
    items: () => S.items.map((i) => ({ ...i })),
    /** The step or arrow that is the canvas's tab stop. */
    current: () => (S.current ? { ...S.current } : null),
    /** Whether the open panel has edits not yet saved (`B1052`'s "edited"). */
    isDirty: () => !!(S.panel && S.panel.dirty),
    /** `B1839`. The source's state moved (its owner says so): Undo/Redo
     *  follow it. */
    syncTools: () => syncTools(),
    /** `B1851`. Marks the steps the source's problems name; → Map id → sentences. */
    markProblems: () => markProblems(),
    undo: () => undoPressed(),
    redo: () => redoPressed(),
    /** `B1841`. The steps picked together now. */
    picked: () => Array.from(S.sel),
  };
}

export default { mountCanvas, outcomeOf, refusalText, POSITIONS_PREF, TASKS_URL };
