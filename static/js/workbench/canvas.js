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
// **The keyboard path is a peer, not an afterthought.** A step is focusable;
// its *Connect…* button picks the outcome and the next step by name from two
// `<select>`s; arrow keys move a focused step by the window system's own step
// (`windowDrag.js:KEY_STEP`); an arrow is focusable too, and Delete removes it
// only after saying which arrow it is. Escape goes through `escMenuStack.js`,
// so it closes the innermost thing — the picker, the pending removal, the side
// panel — before `ui.js`'s arbiter closes the window; while one is open the
// room carries `data-esc-layer`, which is what makes the arbiter ask the stack
// first when the pointer is on the window (`B1052`, `holdEscape`).
//
// **Every word a person wrote is set as text.** Task names reach the page
// through `textContent` and attribute values only — never `innerHTML` — which
// is the property `P22`'s preamble weighed Drawflow on and found it lacked.
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
// **Where a step sits is the person's, and kept per person** through the
// preferences door that exists (`PUT /api/prefs/{key}`, `routes/prefs_routes.py`)
// under `workbench_positions` — see `POSITIONS_PREF` for why that name.

import {
  layoutGraph, boundsOf, portPoint, portOffset, inputPoint, edgePath, edgeMid,
  arrowPath, nodeAt, clampZoom, fitView, NODE_W, NODE_H, PORTS,
} from './graphLayout.js';
import { EDGE_WORDS, EDGE_COLUMNS, KIND_WORDS, componentOf } from '../tasks/workflowDiagram.js';
import { runStatusTone, runStatusLabel } from '../runStatus.js';
import { computeSnap } from '../editor/snap.js';
import { registerMenuDismiss } from '../escMenuStack.js';
import { KEY_STEP, MOVE_THRESHOLD } from '../windowDrag.js';

/**
 * The preference key positions are kept under.
 *
 * Snake case beside the two task preferences the server already keeps in the
 * same per-person record (`tasks_opened`, `tasks_enabled`), and prefixed with
 * the window's name rather than the room's: `P22-05`'s workflow documents
 * carry their own node positions inside the document, so what lives here is
 * only where a *task* sits on this canvas. The value is
 * `{ v: 1, tasks: { "<task id>": [x, y] } }` — keyed by id, which survives a
 * rename, pruned to the tasks that still exist on every save so it cannot grow
 * without bound, and versioned so a later shape can be read beside this one.
 */
export const POSITIONS_PREF = 'workbench_positions';
/** The list the Tasks window reads, with each task's last run on it. */
export const TASKS_URL = '/api/tasks?include_last_run=true';

const SVG_NS = 'http://www.w3.org/2000/svg';
const SAVE_DELAY_MS = 400;
/** How long after a drag ends the click a browser fires for it is ignored. */
const SWALLOW_MS = 400;
const ZOOM_STEP = 1.2;
/** `.wb-connect`'s width in the sheet, so the picker can be kept on the stage. */
const CONNECT_W = 260;
const KEY_DIRS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
/** The mark beside a step's last-run word, by `runStatusTone`. `none` is a
 *  step that has not run. */
const OUTCOME_MARKS = { ok: '✓', error: '✗', pending: '…', info: '·', none: '○' };

function _cap(s) {
  const t = String(s || '');
  return t.charAt(0).toUpperCase() + t.slice(1);
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

/** What the server said when it refused, as one sentence. FastAPI answers
 *  `{ detail: "…" }` for an `HTTPException` and `{ detail: [{ msg }] }` for a
 *  body it could not parse; an object detail is read for its words. */
export function refusalText(detail) {
  if (typeof detail === 'string') return detail.trim();
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && (d.msg || d.message)) || '').filter(Boolean).join(' ').trim();
  }
  if (detail && typeof detail === 'object') {
    return String(detail.message || detail.sentence || detail.reason || detail.detail || '').trim();
  }
  return '';
}

/** A step's last outcome: the tone that styles it and the words it says. */
export function outcomeOf(task) {
  const status = task && task.last_run_status;
  if (!status) {
    return { tone: 'none', word: task && task.last_run ? 'No record of the last run' : 'Not run yet' };
  }
  return { tone: runStatusTone(status) || 'info', word: 'Last run: ' + runStatusLabel(status, 'job') };
}

/**
 * Draw the Automations room into `root`.
 *
 * `opts.mountPanel` — the `P22` panel contract (`mountTaskFields`).
 * `opts.fetch` — defaults to the page's `fetch`; injected so the test can see
 *   every request this makes and answer it.
 * `opts.describeTrigger(task)` — the words for what starts a task
 *   (`tasks.js:_scheduleLabel`, handed in by whoever opened the window so the
 *   schedule wording exists once).
 * `opts.focusId` — open on the workflow this task is part of.
 *
 * Returns `{ ready, reload, focusChain, select, destroy, flush }`; `ready`
 * settles once the first drawing is on the page.
 */
export function mountCanvas(root, opts = {}) {
  const mountPanel = typeof opts.mountPanel === 'function' ? opts.mountPanel : null;
  const net = typeof opts.fetch === 'function' ? opts.fetch : (url, init) => globalThis.fetch(url, init);
  const describe = (task) => {
    if (typeof opts.describeTrigger !== 'function') return '';
    try { return String(opts.describeTrigger(task) || ''); } catch (_) { return ''; }
  };

  const S = {
    tasks: [], byId: new Map(), graph: { nodes: [], edges: [] },
    pos: new Map(), pinned: new Map(), missing: new Set(), order: [],
    nodeEls: new Map(), edgeEls: [],
    view: { x: 0, y: 0, zoom: 1 }, viewed: false, loaded: false, destroyed: false,
    focusId: opts.focusId != null ? String(opts.focusId) : null,
    selected: null, panel: null, connect: null,
    drag: null, link: null, pan: null, swallow: null,
    pending: null, sayRun: null, saveTimer: null,
  };

  // ── the skeleton ─────────────────────────────────────────────────────────
  root.classList.add('wb-room');
  const toolbar = _el('div', 'wb-toolbar');
  const newBtn = _el('button', 'wb-tool wb-tool-new', 'New step');
  newBtn.type = 'button';
  newBtn.title = 'Make a new task and put it on the canvas';
  const tidyBtn = _el('button', 'wb-tool', 'Tidy up');
  tidyBtn.type = 'button';
  tidyBtn.title = 'Forget where steps were moved and lay everything out again';
  const spacer = _el('span', 'wb-toolbar-spacer');
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
  for (const n of [newBtn, tidyBtn, spacer, outBtn, zoomWord, inBtn, fitBtn]) toolbar.appendChild(n);

  const hint = _el('p', 'wb-hint',
    'Drag from a step’s “' + EDGE_WORDS.success + '” or “' + EDGE_WORDS.error
    + '” onto the step that should run next, or use its Connect… button. Click a step to edit it.');

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
  viewport.setAttribute('aria-label', 'Your automations');
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
  empty.appendChild(_el('p', 'wb-empty-title', 'No automations yet.'));
  empty.appendChild(_el('p', 'wb-empty-text',
    'A step is a task: a prompt, a research run or an action, started by a schedule, an event or a webhook. Make one, make another, then join them.'));
  const emptyNew = _el('button', 'wb-tool wb-tool-new', 'New step');
  emptyNew.type = 'button';
  empty.appendChild(emptyNew);
  empty.hidden = true;
  viewport.appendChild(empty);

  const panel = _el('aside', 'wb-panel');
  panel.setAttribute('aria-label', 'Step');
  panel.hidden = true;
  const panelHead = _el('div', 'wb-panel-head');
  const panelTitle = _el('h3', 'wb-panel-title');
  const panelClose = _el('button', 'wb-panel-close', 'Close');
  panelClose.type = 'button';
  panelHead.appendChild(panelTitle);
  panelHead.appendChild(panelClose);
  const panelBody = _el('div', 'wb-panel-body');
  panel.appendChild(panelHead);
  panel.appendChild(panelBody);

  stage.appendChild(viewport);
  stage.appendChild(panel);
  for (const n of [toolbar, hint, sayBox, stage]) root.appendChild(n);

  // ── words ────────────────────────────────────────────────────────────────
  const taskName = (t) => String((t && t.name) || 'Untitled task');
  const nameOf = (id) => {
    const t = S.byId.get(String(id));
    return t ? taskName(t) : 'a task you cannot see';
  };
  const edgeSentence = (from, when, to) =>
    `After ${nameOf(from)}, ${EDGE_WORDS[when] || when}, ${nameOf(to)} runs.`;

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

  // ── the wire ─────────────────────────────────────────────────────────────
  async function put(path, body) {
    let res;
    try {
      res = await net(path, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (_) {
      return { ok: false, status: 0, sentence: 'Pantheon could not be reached, so nothing changed.' };
    }
    if (res.ok) {
      let data = null;
      try { data = await res.json(); } catch (_) { data = null; }
      return { ok: true, status: res.status, data };
    }
    let detail = '';
    try { detail = refusalText((await res.json()).detail); } catch (_) { detail = ''; }
    return { ok: false, status: res.status, sentence: detail || `The change was refused (${res.status}).` };
  }

  async function fetchTasks() {
    const res = await net(TASKS_URL, { credentials: 'same-origin' });
    if (!res.ok) throw new Error('GET /api/tasks answered ' + res.status);
    return res.json();
  }

  function readPositions(value) {
    const out = new Map();
    const tasks = value && typeof value === 'object' ? value.tasks : null;
    if (!tasks || typeof tasks !== 'object') return out;
    for (const [id, xy] of Object.entries(tasks)) {
      const x = Number(Array.isArray(xy) ? xy[0] : NaN);
      const y = Number(Array.isArray(xy) ? xy[1] : NaN);
      if (Number.isFinite(x) && Number.isFinite(y)) out.set(String(id), { x, y });
    }
    return out;
  }

  async function loadPositions() {
    try {
      const res = await net('/api/prefs/' + POSITIONS_PREF, { credentials: 'same-origin' });
      if (!res.ok) return new Map();
      return readPositions((await res.json()).value);
    } catch (_) {
      // No saved positions is the first-run state, and the layout covers it.
      return new Map();
    }
  }

  async function savePositions() {
    if (S.saveTimer) { clearTimeout(S.saveTimer); S.saveTimer = null; }
    const tasks = {};
    for (const [id, p] of S.pinned) {
      if (S.byId.has(id)) tasks[id] = [Math.round(p.x), Math.round(p.y)];
    }
    try {
      const res = await net('/api/prefs/' + POSITIONS_PREF, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: { v: 1, tasks } }),
      });
      if (!res.ok) say('Where the steps sit could not be saved; they will be laid out again next time.', { refusal: true });
    } catch (_) {
      say('Where the steps sit could not be saved; they will be laid out again next time.', { refusal: true });
    }
  }

  function scheduleSave() {
    if (S.saveTimer) clearTimeout(S.saveTimer);
    S.saveTimer = setTimeout(() => { S.saveTimer = null; savePositions(); }, SAVE_DELAY_MS);
  }

  function take(data) {
    S.tasks = Array.isArray(data && data.tasks) ? data.tasks : [];
    S.byId = new Map(S.tasks.map((t) => [String(t.id), t]));
    const g = data && data.graph;
    S.graph = g && Array.isArray(g.nodes)
      ? { nodes: g.nodes, edges: Array.isArray(g.edges) ? g.edges : [] }
      : { nodes: S.tasks.map((t) => ({ id: t.id, name: t.name })), edges: [] };
  }

  async function reload() {
    let data;
    try {
      data = await fetchTasks();
    } catch (_) {
      say('The list of tasks could not be loaded. Close the Workbench and open it again to retry.', { refusal: true });
      return false;
    }
    if (S.destroyed) return false;
    take(data);
    render();
    applyFocusChain();
    return true;
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
  }

  function fitTo(bounds) {
    const r = viewportRect();
    S.view = fitView(bounds, r.width, r.height);
    applyView();
  }

  function fitAll() { fitTo(boundsOf(S.pos.values())); }

  function zoomAt(factor, px, py) {
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

  function hitList() {
    return S.order.filter((id) => !S.missing.has(id)).map((id) => ({ id, ...S.pos.get(id) }));
  }

  function markSelected() {
    for (const [id, node] of S.nodeEls) node.classList.toggle('wb-node-selected', id === S.selected);
  }

  function focusNode(id) {
    const node = S.nodeEls.get(String(id));
    if (node && typeof node.focus === 'function') node.focus();
    return node || null;
  }

  function buildNode(item, targeted) {
    const id = item.id;
    const task = S.byId.get(id) || null;
    const node = _el('div', 'wb-node');
    node.dataset.taskId = id;
    node.style.width = NODE_W + 'px';
    node.style.height = NODE_H + 'px';
    place(node, item);
    S.nodeEls.set(id, node);

    if (item.missing || !task) {
      // The far end of an edge the server kept on purpose (`dangling`): a
      // chain to a task this person cannot see is a real fact about the
      // workflow, so it is drawn — and it is not something to drag or open.
      node.classList.add('wb-node-missing');
      node.setAttribute('aria-hidden', 'true');
      node.appendChild(_el('div', 'wb-node-title', 'A task you cannot see'));
      node.appendChild(_el('div', 'wb-node-sub', 'Not in your list of tasks'));
      return node;
    }

    const name = taskName(task);
    const kind = task.task_type || 'llm';
    // What starts it goes on the step nothing points at — `P8-34`'s rule: a
    // step downstream is started by the arrow into it, and repeating its own
    // schedule there would say something untrue about when it runs next.
    const trigger = targeted.has(id) ? '' : describe(task);
    const paused = task.status === 'paused';
    const out = outcomeOf(task);
    const subText = [KIND_WORDS[kind] || KIND_WORDS.llm, trigger, paused ? 'paused' : '']
      .filter(Boolean).join(' · ');

    node.setAttribute('tabindex', '0');
    node.setAttribute('role', 'group');
    node.setAttribute('aria-label', `${name}. ${subText}. ${out.word}.`);
    node.dataset.kind = kind;
    node.dataset.outcome = out.tone;
    if (paused) node.dataset.paused = 'true';

    const title = _el('div', 'wb-node-title', name);
    title.title = name;
    const sub = _el('div', 'wb-node-sub', subText);
    const last = _el('div', 'wb-node-last');
    const mark = _el('span', 'wb-node-mark', OUTCOME_MARKS[out.tone] || OUTCOME_MARKS.info);
    mark.setAttribute('aria-hidden', 'true');
    last.appendChild(mark);
    last.appendChild(_el('span', 'wb-node-word', out.word));
    const connectBtn = _el('button', 'wb-node-connect', 'Connect…');
    connectBtn.type = 'button';
    connectBtn.title = `Choose what runs after ${name}`;
    connectBtn.addEventListener('click', (e) => {
      if (e && e.stopPropagation) e.stopPropagation();
      openConnect(id, connectBtn);
    });
    for (const n of [title, sub, last, connectBtn]) node.appendChild(n);

    for (const when of PORTS) {
      const port = _el('span', 'wb-port');
      port.dataset.when = when;
      port.style.top = (portOffset(when) - 7) + 'px';
      port.title = `${_cap(EDGE_WORDS[when] || when)}: drag to the step that should run`;
      // The keyboard's way to the same thing is Connect…; a port is a pointer
      // handle and is not announced twice.
      port.setAttribute('aria-hidden', 'true');
      port.appendChild(_el('span', 'wb-port-label', EDGE_WORDS[when] || when));
      port.addEventListener('pointerdown', (e) => startLink(e, id, when, port));
      port.addEventListener('pointermove', (e) => moveLink(e));
      port.addEventListener('pointerup', (e) => finishLink(e));
      port.addEventListener('pointercancel', () => endLink(null));
      node.appendChild(port);
    }

    node.addEventListener('pointerdown', (e) => startDrag(e, id, node));
    node.addEventListener('pointermove', (e) => moveDrag(e, id, node));
    node.addEventListener('pointerup', (e) => endDrag(e, id, node));
    node.addEventListener('pointercancel', (e) => endDrag(e, id, node));
    node.addEventListener('click', () => {
      if (S.swallow && S.swallow.id === id && Date.now() < S.swallow.until) { S.swallow = null; return; }
      select(id);
    });
    node.addEventListener('keydown', (e) => onNodeKey(e, id));
    if (S.selected === id) node.classList.add('wb-node-selected');
    return node;
  }

  function drawEdges() {
    const kids = [];
    S.edgeEls = [];
    for (const edge of S.graph.edges || []) {
      const from = String(edge.from);
      const to = String(edge.to);
      const when = String(edge.when || '');
      if (!S.pos.has(from) || !S.pos.has(to)) continue;
      const g = _svg('g', 'wb-edge wb-edge-' + (when === 'error' ? 'error' : 'success'));
      g.setAttribute('data-from', from);
      g.setAttribute('data-to', to);
      g.setAttribute('data-when', when);
      g.setAttribute('tabindex', '0');
      g.setAttribute('role', 'button');
      g.setAttribute('aria-label', edgeSentence(from, when, to) + ' Press Delete to remove this arrow.');
      const hit = _svg('path', 'wb-edge-hit');
      const line = _svg('path', 'wb-edge-line');
      const head = _svg('path', 'wb-edge-head');
      const label = _svg('text', 'wb-edge-label');
      label.setAttribute('text-anchor', 'middle');
      label.textContent = EDGE_WORDS[when] || when;
      for (const n of [hit, line, head, label]) g.appendChild(n);
      const rec = { edge, from, to, when, key: `${from}\u0000${when}\u0000${to}`, g, hit, line, head, label };
      g.addEventListener('pointerdown', (e) => { if (e && e.stopPropagation) e.stopPropagation(); });
      g.addEventListener('click', () => { if (typeof g.focus === 'function') g.focus(); showEdge(rec); });
      g.addEventListener('focus', () => showEdge(rec));
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
      const a = portPoint(S.pos.get(r.from), r.when);
      const b = inputPoint(S.pos.get(r.to));
      const d = edgePath(a, b);
      r.hit.setAttribute('d', d);
      r.line.setAttribute('d', d);
      r.head.setAttribute('d', arrowPath(b));
      const m = edgeMid(a, b);
      r.label.setAttribute('x', String(m.x));
      r.label.setAttribute('y', String(m.y - 6));
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

  function render() {
    // Everything already on the canvas stays where it is — a person who drew
    // one arrow must not have to find both steps again — and what the person
    // placed in an earlier visit is where it was left. Only steps nobody has
    // placed are laid out (`graphLayout.js`).
    const fixed = new Map(S.pinned);
    for (const [id, p] of S.pos) fixed.set(id, p);
    const lay = layoutGraph(S.graph, fixed);
    S.pos = new Map(lay.nodes.map((n) => [n.id, { x: n.x, y: n.y }]));
    S.missing = new Set(lay.nodes.filter((n) => n.missing).map((n) => n.id));
    S.order = lay.nodes.map((n) => n.id);
    const targeted = new Set((S.graph.edges || []).map((e) => String(e.to)));
    S.nodeEls = new Map();
    nodesLayer.replaceChildren(...lay.nodes.map((n) => buildNode(n, targeted)));
    drawEdges();
    empty.hidden = S.tasks.length > 0;
    root.classList.toggle('wb-room-empty', S.tasks.length === 0);
    if (!S.viewed) { S.viewed = true; fitAll(); } else applyView();
  }

  function moveNode(id, x, y) {
    S.pos.set(id, { x, y });
    const node = S.nodeEls.get(id);
    if (node) place(node, { x, y });
    updateEdges();
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
    const t = e.target;
    if (t && t !== node && typeof t.closest === 'function' && t.closest('button, .wb-port')) return;
    if (e.stopPropagation) e.stopPropagation();
    const p = S.pos.get(id);
    S.drag = { id, pointerId: e.pointerId, cx: e.clientX, cy: e.clientY, x0: p.x, y0: p.y, moved: false };
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
    for (const [oid, p] of S.pos) {
      if (oid === id || S.missing.has(oid)) continue;
      others.push({ visible: true, id: oid, canvas: { width: NODE_W, height: NODE_H }, offset: p });
    }
    // `editor/snap.js`, the image editor's layer snap: a step dragged near
    // another step's edge or centre lines up with it.
    const snap = computeSnap({ id, canvas: { width: NODE_W, height: NODE_H } },
      d.x0 + dx / S.view.zoom, d.y0 + dy / S.view.zoom,
      { zoom: S.view.zoom, canvasW: 0, canvasH: 0, otherLayers: others });
    drawGuides(snap.guides);
    moveNode(id, snap.x, snap.y);
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
      savePositions();
    }
  }

  // ── moving a step: keyboard ──────────────────────────────────────────────
  function onNodeKey(e, id) {
    if (e.target && e.target !== S.nodeEls.get(id)) return;   // keys inside Connect…
    const dir = KEY_DIRS[e.key];
    if (dir && !e.altKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      const step = KEY_STEP * (e.shiftKey ? 4 : 1);
      const p = S.pos.get(id);
      moveNode(id, p.x + dir[0] * step, p.y + dir[1] * step);
      pin(id);
      scheduleSave();
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
      start: portPoint(S.pos.get(from), when),
      unregister: holdEscape(() => endLink(null)),
    };
    try { if (port.setPointerCapture) port.setPointerCapture(e.pointerId); } catch (_) { /* a synthetic pointer */ }
    ghost.setAttribute('d', edgePath(S.link.start, S.link.start));
    root.classList.add('wb-linking');
    say(`${_cap(EDGE_WORDS[when] || when)}: let go over the step that should run after ${nameOf(from)}.`);
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
    endLink(nodeAt(hitList(), toWorld(e.clientX, e.clientY), L.from));
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
  async function connect(from, when, to) {
    const column = EDGE_COLUMNS[when];
    if (!column) {
      const sentence = `This canvas cannot write “${when}” yet.`;
      say('Not connected: ' + sentence, { refusal: true });
      return { ok: false, sentence };
    }
    const before = (S.graph.edges || []).find((e) => String(e.from) === from && String(e.when) === when);
    const res = await put('/api/tasks/' + encodeURIComponent(from), { [column]: String(to) });
    if (!res.ok) {
      // The server's own sentence (`P22-01`), word for word.
      say('Not connected: ' + res.sentence, { refusal: true });
      return res;
    }
    const sentence = edgeSentence(from, when, to);
    const was = before && String(before.to) !== String(to) ? ` It used to be ${nameOf(before.to)}.` : '';
    await reload();
    say(`Connected. ${sentence}${was}`);
    return res;
  }

  async function removeEdge(rec) {
    clearPending();
    const column = EDGE_COLUMNS[rec.when];
    if (!column) return { ok: false };
    const res = await put('/api/tasks/' + encodeURIComponent(rec.from), { [column]: '' });
    if (!res.ok) {
      say('Not removed: ' + res.sentence, { refusal: true });
      return res;
    }
    const sentence = `${nameOf(rec.to)} no longer runs after ${nameOf(rec.from)} ${EDGE_WORDS[rec.when] || rec.when}.`;
    await reload();
    focusNode(rec.from);
    say('Removed. ' + sentence);
    return res;
  }

  // ── an arrow, focused ────────────────────────────────────────────────────
  function showEdge(rec) {
    if (S.pending && S.pending.key === rec.key) return;
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
    zoomKeys(e);
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
    const task = S.byId.get(from);
    if (!task) return;
    const name = taskName(task);
    const box = _el('div', 'wb-connect');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', `Connect ${name}`);
    box.appendChild(_el('p', 'wb-connect-head', `After ${name}…`));

    const whenLabel = _el('label', 'wb-connect-field');
    whenLabel.appendChild(_el('span', 'wb-connect-label', 'Outcome'));
    const whenSel = _el('select', 'wb-connect-when');
    for (const w of PORTS) {
      const o = _el('option', null, EDGE_WORDS[w] || w);
      o.value = w;
      whenSel.appendChild(o);
    }
    whenLabel.appendChild(whenSel);

    const toLabel = _el('label', 'wb-connect-field');
    toLabel.appendChild(_el('span', 'wb-connect-label', 'Run next'));
    const toSel = _el('select', 'wb-connect-to');
    const others = S.tasks.filter((t) => String(t.id) !== from)
      .sort((a, b) => taskName(a).localeCompare(taskName(b)));
    for (const t of others) {
      const o = _el('option', null, taskName(t));
      o.value = String(t.id);
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

    const current = (when) => {
      const e = (S.graph.edges || []).find((x) => String(x.from) === from && String(x.when) === when);
      return e ? String(e.to) : null;
    };
    const syncNow = () => {
      const cur = current(whenSel.value);
      now.textContent = cur
        ? `Now: ${nameOf(cur)} runs ${EDGE_WORDS[whenSel.value] || whenSel.value}. Connecting replaces it.`
        : '';
    };
    // Stated rather than left to the browser's default, so the first choice
    // is the same however the picker is driven.
    whenSel.value = PORTS[0];
    if (others.length) toSel.value = String(others[0].id);
    whenSel.addEventListener('change', syncNow);
    if (!others.length) {
      toSel.disabled = true;
      go.disabled = true;
      now.textContent = 'There is no other step yet. Make one with New step, then connect them.';
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

    const p = S.pos.get(from) || { x: 0, y: 0 };
    let left = Math.round(S.view.x + (p.x + NODE_W) * S.view.zoom + 12);
    // `B1051`. Beside the step, unless that is past the stage's right edge — at
    // phone width it always is, and the picker opened off-screen. `CONNECT_W`
    // is the sheet's `.wb-connect` width.
    const stageW = (() => { try { return stage.getBoundingClientRect().width || 0; } catch (_) { return 0; } })();
    if (stageW) left = Math.min(left, Math.round(stageW - CONNECT_W - 8));
    box.style.left = Math.max(8, left) + 'px';
    box.style.top = Math.max(8, Math.round(S.view.y + p.y * S.view.zoom)) + 'px';
    stage.appendChild(box);
    S.connect = { box, from, opener, submit, whenSel, toSel, unregister: holdEscape(() => closeConnect(true)) };
    whenSel.focus();
  }

  // ── the side panel: the task form, mounted ───────────────────────────────
  function closePanel(restoreFocus) {
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
    if (restoreFocus && p.id) focusNode(p.id);
  }

  async function onSaved(saved) {
    const id = saved && saved.id != null ? String(saved.id) : null;
    closePanel(false);
    await reload();
    if (id) focusNode(id);
    say(saved && saved.name ? `Saved ${saved.name}.` : 'Saved.');
  }

  // `B1052`. Escape on a form with unsaved edits says so before it throws them
  // away, and a second Escape is the yes — the canvas's own rule for removing
  // an arrow (said first, done second). An edit is anything typed or chosen in
  // the form (`input` / `change` reaching the panel's host); the form is the
  // `P22` contract's and says nothing about itself, so the panel listens
  // rather than asking it. Cancel, Close and Save are deliberate and do not ask.
  function panelEscape() {
    const p = S.panel;
    if (!p) return;
    const name = p.id ? nameOf(p.id) : 'This new step';
    if (p.dirty && !p.asked) {
      p.asked = true;
      p.unregister = holdEscape(() => panelEscape());
      say(`${name} has changes that are not saved. Press Escape again to close it without saving them, or Save.`);
      return;
    }
    closePanel(true);
    if (p.asked) say(`Closed ${p.id ? name : 'the new step'} without saving.`);
  }

  function openPanel(task) {
    closeConnect(false);
    closePanel(false);
    const id = task ? String(task.id) : null;
    S.selected = id;
    markSelected();
    panel.hidden = false;
    root.classList.add('wb-panel-open');
    panelTitle.textContent = task ? taskName(task) : 'New step';
    const host = _el('div', 'wb-panel-host');
    panelBody.replaceChildren(host);
    S.panel = { id, host, handle: null, dirty: false, asked: false, unregister: holdEscape(() => panelEscape()) };
    const edited = () => {
      const p = S.panel;
      if (p && p.host === host) { p.dirty = true; p.asked = false; }
    };
    host.addEventListener('input', edited);
    host.addEventListener('change', edited);
    if (!mountPanel) {
      host.textContent = 'The step editor did not load. Edit this task from the Tasks window.';
      return;
    }
    S.panel.handle = mountPanel(host, {
      task,
      tasks: S.tasks,
      onSaved: (saved) => onSaved(saved),
      onCancel: () => closePanel(true),
    });
  }

  function select(id) {
    const task = S.byId.get(String(id));
    if (task) openPanel(task);
  }

  // ── opening on one workflow ──────────────────────────────────────────────
  function applyFocusChain() {
    const id = S.focusId;
    if (!id || !S.loaded) return;
    S.focusId = null;
    if (!S.pos.has(id) || S.missing.has(id)) {
      say('That task is not on the canvas any more.');
      return;
    }
    const comp = componentOf(S.graph, id);
    const steps = [...comp.ids].filter((x) => S.pos.has(x));
    fitTo(boundsOf(steps.map((x) => S.pos.get(x))));
    for (const [nid, node] of S.nodeEls) node.classList.toggle('wb-node-chain', comp.ids.has(nid));
    focusNode(id);
    say(steps.length > 1
      ? `${nameOf(id)} is one of ${steps.length} steps in this workflow.`
      : `${nameOf(id)} runs on its own. Drag from “${EDGE_WORDS.success}” or “${EDGE_WORDS.error}” to chain a step to it.`);
  }

  function focusChain(id) {
    S.focusId = id == null ? null : String(id);
    applyFocusChain();
  }

  // ── panning and zooming ──────────────────────────────────────────────────
  viewport.addEventListener('pointerdown', (e) => {
    if (e.button != null && e.button !== 0) return;
    if (e.target !== viewport && e.target !== world) return;
    S.pan = { pointerId: e.pointerId, cx: e.clientX, cy: e.clientY, x0: S.view.x, y0: S.view.y };
    try { if (viewport.setPointerCapture) viewport.setPointerCapture(e.pointerId); } catch (_) { /* a synthetic pointer */ }
    root.classList.add('wb-panning');
  });
  viewport.addEventListener('pointermove', (e) => {
    const p = S.pan;
    if (!p) return;
    S.view = { ...S.view, x: p.x0 + (e.clientX - p.cx), y: p.y0 + (e.clientY - p.cy) };
    applyView();
  });
  const endPan = () => { S.pan = null; root.classList.remove('wb-panning'); };
  viewport.addEventListener('pointerup', endPan);
  viewport.addEventListener('pointercancel', endPan);
  viewport.addEventListener('wheel', (e) => {
    if (e.preventDefault) e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      const r = viewportRect();
      zoomAt(Math.exp(-(Number(e.deltaY) || 0) * 0.0015), e.clientX - r.left, e.clientY - r.top);
    } else {
      S.view = { ...S.view, x: S.view.x - (Number(e.deltaX) || 0), y: S.view.y - (Number(e.deltaY) || 0) };
      applyView();
    }
  }, { passive: false });
  viewport.addEventListener('keydown', (e) => { if (e.target === viewport) zoomKeys(e); });

  // ── the toolbar ──────────────────────────────────────────────────────────
  newBtn.addEventListener('click', () => openPanel(null));
  emptyNew.addEventListener('click', () => openPanel(null));
  panelClose.addEventListener('click', () => closePanel(true));
  outBtn.addEventListener('click', () => zoomBy(1 / ZOOM_STEP));
  inBtn.addEventListener('click', () => zoomBy(ZOOM_STEP));
  fitBtn.addEventListener('click', () => fitAll());
  tidyBtn.addEventListener('click', () => {
    S.pinned = new Map();
    S.pos = new Map();
    render();
    fitAll();
    savePositions();
    say('Laid out again. Drag a step to put it somewhere else.');
  });

  // ── start ────────────────────────────────────────────────────────────────
  const ready = Promise.all([loadPositions(), fetchTasks().then((d) => ({ d }), (err) => ({ err }))])
    .then(([pins, got]) => {
      if (S.destroyed) return false;
      S.pinned = pins;
      if (got.err) {
        say('The list of tasks could not be loaded. Close the Workbench and open it again to retry.', { refusal: true });
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
    endLink(null);
    clearPending();
    closeConnect(false);
    closePanel(false);
    root.replaceChildren();
    root.classList.remove('wb-room', 'wb-panel-open', 'wb-room-empty', 'wb-linking', 'wb-panning');
    delete root.dataset.escLayer;
  }

  return {
    ready,
    reload,
    focusChain,
    select,
    destroy,
    flush: () => savePositions(),
    say,
    newStep: () => openPanel(null),
  };
}

export default { mountCanvas, outcomeOf, refusalText, POSITIONS_PREF, TASKS_URL };
