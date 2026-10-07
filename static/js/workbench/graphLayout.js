// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/graphLayout.js
//
// `P22-02`. Where each step of a chain sits on the Workbench's canvas, and the
// geometry the canvas needs to draw an arrow and to tell which step a pointer
// is over.
//
// **Pure, on purpose** — no DOM, no fetch, no module state — so the test calls
// it directly under node with no sandbox and no stubs, the way
// `tasks/workflowDiagram.js` is tested. The canvas (`canvas.js`) is the half
// that touches the page.
//
// **Not a second graph library (`Law 14`).** The walk that finds a workflow is
// `workflowDiagram.js:componentOf`, the depth is its `longestChain`, and the
// two ports are its `EDGE_WORDS` — imported, never copied, so a third condition
// added on the server is a third port here without an edit to this file.
//
// **The layout is layered, left to right.** A step's column is the longest
// path to it from where its workflow starts, so everything a step waits for is
// to its left; within a column the step reached *if it works* sits above the
// one reached *if it fails*. Edges that point back (a loop, which the engine
// refuses and a hand-edited database can still hold) are set aside before the
// columns are counted, so a cycle is drawn rather than hanging the window —
// the same promise `longestChain` makes. Workflows are stacked longest first,
// and tasks chained to nothing sit in a grid underneath, ready to be connected.
//
// **A position a person chose is kept exactly.** The layout only places steps
// nobody has placed: one in a workflow that already has a placed step goes
// where the layout would put it relative to that step, and a workflow with
// nothing placed keeps its own place unless a placed step is in the way, when
// it moves down as a whole. Measured in Chromium, not guessed: the first
// version sent every unplaced workflow below the lowest placed step, so
// nudging one step 32px reshuffled the whole canvas on the next visit.

import { componentOf, longestChain, EDGE_WORDS } from '../tasks/workflowDiagram.js';

/** One step on the canvas, in canvas pixels at zoom 1. The canvas sizes its
 *  node elements from these, so the box drawn and the box hit-tested are the
 *  same box. */
export const NODE_W = 232;
export const NODE_H = 96;
/** Between columns (room for an arrow and its words) and between rows. */
export const GAP_X = 96;
export const GAP_Y = 32;
/** Space around everything the layout places. */
export const MARGIN = 40;
/** Tasks chained to nothing, laid out this many to a row. */
export const LONE_COLUMNS = 4;
/** How far the canvas zooms either way. */
export const ZOOM_MIN = 0.35;
export const ZOOM_MAX = 2;
/** `P23-06` (WB-M-2, WB-M-6). A fit into a canvas narrower than this — a
 *  phone, or a desktop canvas a run list and a step's panel have squeezed —
 *  stops at `FIT_FLOOR_NARROW` instead of `ZOOM_MIN`: at 35 % a step is an
 *  80 px box with 5 px words (measured at 390 px and beside a failed run's
 *  panel at 1440). The person pans to the rest; `B1113` keeps the start in
 *  view. The `−` button still goes down to `ZOOM_MIN`. */
export const NARROW_FIT_WIDTH = 600;
export const FIT_FLOOR_NARROW = 0.6;

/** The ports a step has, in the order `EDGE_WORDS` names the conditions. */
export const PORTS = Object.freeze(Object.keys(EDGE_WORDS));

/** Where a port sits down the right-hand edge of a step, and where an arrow
 *  arrives on the left. The first port shares the title's row and the second
 *  the last-run row, which is what lets each carry its own words. */
const PORT_TOP = 20;
const PORT_STEP = 42;
/** `P22-10`/`P22-11` (wf-canvas). Below a step's last port: the same room the
 *  two-port step has under its second (96 − 62), so a step with more ports is
 *  taller by exactly one port's step for each port past the second. */
const PORT_FOOT = NODE_H - (PORT_TOP + PORT_STEP);

/**
 * `P22-10`/`P22-11` (wf-canvas). How tall a step with `ports` is drawn.
 *
 * A step of a workflow document may have named ports — an If's *if so* and
 * *otherwise*, a Switch's one per case and *otherwise* (`ports_of` in
 * `src/workflow_document.py`) — and each port carries its own words on the
 * step's right edge, one per row. Two ports or fewer is the step every
 * canvas has drawn since `P22-02` (`NODE_H`), so a task and every existing
 * step are the same size they were; each port past the second adds one row.
 * `ports` is an array (its length is what counts) or a count.
 */
export function nodeHeight(ports) {
  const n = Array.isArray(ports) ? ports.length : Math.max(0, Number(ports) || 0);
  if (n <= 2) return NODE_H;
  return PORT_TOP + (n - 1) * PORT_STEP + PORT_FOOT;
}

/** A position's drawn height: its own `h` when the layout gave it one. */
const _h = (p) => (p && Number(p.h) > 0 ? Number(p.h) : NODE_H);

const _r = (n) => Math.round(n * 10) / 10;

function _toMap(saved) {
  const out = new Map();
  if (!saved) return out;
  const entries = saved instanceof Map ? saved.entries() : Object.entries(saved);
  for (const [id, p] of entries) {
    const x = Number(p && p.x);
    const y = Number(p && p.y);
    if (Number.isFinite(x) && Number.isFinite(y)) out.set(String(id), { x, y });
  }
  return out;
}

/** The order a condition's port takes, unknown conditions after the known.
 *  `ports` is the step's own list when it has one (`P22-10`); without it, the
 *  two every task has. */
function _portIndex(when, ports) {
  const list = Array.isArray(ports) && ports.length ? ports.map(String) : PORTS;
  const i = list.indexOf(String(when));
  return i < 0 ? list.length : i;
}

/** Every id the graph names — its nodes in the order served, then the far end
 *  of any edge whose target is not one of them (`dangling`, kept on purpose by
 *  `build_task_graph`). */
function _ids(graph) {
  const out = [];
  const seen = new Set();
  const add = (id) => {
    const key = String(id);
    if (!seen.has(key)) { seen.add(key); out.push(key); }
  };
  for (const n of (graph && graph.nodes) || []) if (n && n.id != null) add(n.id);
  for (const e of (graph && graph.edges) || []) {
    if (e && e.from != null && e.to != null) { add(e.from); add(e.to); }
  }
  return out;
}

/**
 * Column and row for every step of one workflow.
 *
 * `members` is in served order and that order breaks every tie, so the same
 * graph always lands the same way. Back edges are found with an iterative
 * depth-first walk (a long chain must not run out of stack), set aside, and
 * the columns are then the longest path over what is left — a DAG, so it
 * terminates whatever the database holds.
 */
function _columns(members, edges, index, portsOf = () => null) {
  const out = new Map(members.map((id) => [id, []]));
  const incoming = new Map(members.map((id) => [id, 0]));
  for (const e of edges) {
    const from = String(e.from);
    const to = String(e.to);
    if (!out.has(from) || !out.has(to)) continue;
    out.get(from).push({ to, when: String(e.when || '') });
    incoming.set(to, incoming.get(to) + 1);
  }

  const state = new Map();     // 1 on the walk's path, 2 finished
  const back = new Set();
  const starts = members.filter((id) => incoming.get(id) === 0).concat(members);
  for (const start of starts) {
    if (state.has(start)) continue;
    state.set(start, 1);
    const stack = [[start, 0]];
    while (stack.length) {
      const top = stack[stack.length - 1];
      const outs = out.get(top[0]);
      if (top[1] < outs.length) {
        const edge = outs[top[1]];
        top[1] += 1;
        if (!state.has(edge.to)) {
          state.set(edge.to, 1);
          stack.push([edge.to, 0]);
        } else if (state.get(edge.to) === 1) {
          back.add(edge);
        }
      } else {
        state.set(top[0], 2);
        stack.pop();
      }
    }
  }

  const waiting = new Map(members.map((id) => [id, 0]));
  for (const outs of out.values()) {
    for (const edge of outs) if (!back.has(edge)) waiting.set(edge.to, waiting.get(edge.to) + 1);
  }
  const column = new Map(members.map((id) => [id, 0]));
  const byIndex = (a, b) => index.get(a) - index.get(b);
  const ready = members.filter((id) => waiting.get(id) === 0);
  while (ready.length) {
    const id = ready.shift();
    for (const edge of out.get(id)) {
      if (back.has(edge)) continue;
      column.set(edge.to, Math.max(column.get(edge.to), column.get(id) + 1));
      waiting.set(edge.to, waiting.get(edge.to) - 1);
      if (waiting.get(edge.to) === 0) { ready.push(edge.to); ready.sort(byIndex); }
    }
  }

  // Rows, column by column: under the average row of what leads to a step,
  // then the step reached `if it works` before the one reached `if it fails`,
  // then served order.
  const preds = new Map(members.map((id) => [id, []]));
  for (const [from, outs] of out) {
    for (const edge of outs) if (!back.has(edge)) preds.get(edge.to).push({ from, when: edge.when });
  }
  const columns = new Map();
  for (const id of members) {
    const c = column.get(id);
    if (!columns.has(c)) columns.set(c, []);
    columns.get(c).push(id);
  }
  const row = new Map();
  for (const c of [...columns.keys()].sort((a, b) => a - b)) {
    const key = (id) => {
      const from = preds.get(id).filter((p) => row.has(p.from));
      const bary = from.length
        ? from.reduce((sum, p) => sum + row.get(p.from), 0) / from.length
        : index.get(id);
      const when = from.length ? Math.min(...from.map((p) => _portIndex(p.when, portsOf(p.from)))) : 0;
      return [bary, when, index.get(id)];
    };
    const keyed = columns.get(c).map((id) => [id, key(id)]);
    keyed.sort((a, b) => (a[1][0] - b[1][0]) || (a[1][1] - b[1][1]) || (a[1][2] - b[1][2]));
    keyed.forEach(([id], i) => row.set(id, i));
  }
  return { column, row };
}

function _overlaps(a, b) {
  return a.x < b.x + NODE_W + GAP_Y / 2 && b.x < a.x + NODE_W + GAP_Y / 2
    && a.y < b.y + _h(b) + GAP_Y / 2 && b.y < a.y + _h(a) + GAP_Y / 2;
}

/** `{ heights, ports }` from `layoutGraph`'s third argument: each a `Map` or
 *  a plain object keyed by id. */
function _lookup(value) {
  if (!value) return () => null;
  if (value instanceof Map) return (id) => (value.has(String(id)) ? value.get(String(id)) : null);
  return (id) => (Object.prototype.hasOwnProperty.call(value, String(id)) ? value[String(id)] : null);
}

/**
 * Lay a graph out.
 *
 * `graph` is `build_task_graph`'s shape (`{ nodes, edges }`); `saved` maps a
 * task id to `{ x, y }` (a `Map` or a plain object) for every step a person has
 * placed. Returns `{ nodes: [{ id, x, y, h, saved, missing }], bounds,
 * components }` — an array, so the order is the drawing order and a caller
 * never meets JavaScript's integer-key ordering of plain objects.
 *
 * `opts` (`P22-10`, wf-canvas): `heights` — a step's drawn height by id
 * (`nodeHeight` of its ports; `NODE_H` for any step not named), and `ports` —
 * a step's own port list by id, which orders the steps an If or a Switch leads
 * to the way its ports are ordered. A row of a workflow is as tall as its
 * tallest step, so the rows of every column still line up; with every step
 * `NODE_H` tall this is the layout `P22-02` drew, to the pixel.
 */
export function layoutGraph(graph, saved, opts = {}) {
  const heightOf = _lookup(opts && opts.heights);
  const hOf = (id) => { const v = Number(heightOf(id)); return v > 0 ? v : NODE_H; };
  const portsLookup = _lookup(opts && opts.ports);
  const ids = _ids(graph);
  const index = new Map(ids.map((id, i) => [id, i]));
  const known = new Set(((graph && graph.nodes) || []).map((n) => String(n.id)));
  const fixed = _toMap(saved);
  const edges = ((graph && graph.edges) || []).filter((e) => e && e.from != null && e.to != null);

  // The workflows, each found the way the diagram finds one.
  const seen = new Set();
  const comps = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    const component = componentOf(graph, id);
    const members = ids.filter((x) => component.ids.has(x));
    members.forEach((x) => seen.add(x));
    comps.push({ members, component, depth: longestChain(component), first: index.get(id) });
  }
  // Longest chain first, then the bigger workflow, then served order; tasks
  // chained to nothing come last, in served order.
  const chains = comps.filter((c) => c.members.length > 1)
    .sort((a, b) => (b.depth - a.depth) || (b.members.length - a.members.length) || (a.first - b.first));
  const lone = comps.filter((c) => c.members.length === 1);

  // Where everything would go with nothing placed.
  const base = new Map();
  let top = MARGIN;
  for (const c of chains) {
    const memberSet = new Set(c.members);
    const own = edges.filter((e) => memberSet.has(String(e.from)) && memberSet.has(String(e.to)));
    const { column, row } = _columns(c.members, own, index, portsLookup);
    // Each row as tall as its tallest step, so a Switch with five ports does
    // not run into the step under it and every column's rows still line up.
    const rowH = [];
    for (const id of c.members) {
      const r = row.get(id);
      rowH[r] = Math.max(rowH[r] || 0, hOf(id));
    }
    const rowTop = [];
    let y = top;
    for (let r = 0; r < rowH.length; r++) { rowTop[r] = y; y += (rowH[r] || NODE_H) + GAP_Y; }
    for (const id of c.members) {
      base.set(id, {
        x: MARGIN + column.get(id) * (NODE_W + GAP_X),
        y: rowTop[row.get(id)],
      });
    }
    top = y + GAP_Y;
  }
  // Tasks chained to nothing, a grid of rows each as tall as its tallest.
  const loneRows = [];
  lone.forEach((c, k) => {
    const r = Math.floor(k / LONE_COLUMNS);
    loneRows[r] = Math.max(loneRows[r] || 0, hOf(c.members[0]));
  });
  const loneTop = [];
  { let y = top; for (let r = 0; r < loneRows.length; r++) { loneTop[r] = y; y += loneRows[r] + GAP_Y; } }
  lone.forEach((c, k) => {
    base.set(c.members[0], {
      x: MARGIN + (k % LONE_COLUMNS) * (NODE_W + GAP_X),
      y: loneTop[Math.floor(k / LONE_COLUMNS)],
    });
  });

  // What a person placed stays exactly where it is.
  const placed = new Map();
  for (const id of ids) if (fixed.has(id)) placed.set(id, { ...fixed.get(id), h: hOf(id) });

  // Everything else keeps the place the layout gives it unless something is
  // in the way. A step in a workflow that has a placed step goes where the
  // layout would put it relative to that step, and moves down a row at a time
  // off anything it would land on. A workflow with nothing placed moves down
  // AS A WHOLE, a row at a time, until none of it lands on anything — so
  // nudging one step does not rearrange every other workflow on the next
  // visit. Both loops are bounded by the number of steps: there is always a
  // free row below.
  const taken = [...placed.values()];
  const row = NODE_H + GAP_Y;
  for (const c of chains.concat(lone)) {
    const anchor = c.members.find((id) => placed.has(id));
    const free = c.members.filter((id) => !placed.has(id));
    if (anchor) {
      const dx = placed.get(anchor).x - base.get(anchor).x;
      const dy = placed.get(anchor).y - base.get(anchor).y;
      for (const id of free) {
        const a = { x: base.get(id).x + dx, y: base.get(id).y + dy, h: hOf(id) };
        for (let guard = 0; guard <= ids.length && taken.some((b) => _overlaps(a, b)); guard++) a.y += row;
        taken.push(a);
        placed.set(id, a);
      }
    } else {
      let dy = 0;
      const clash = () => free.some((id) => taken.some((b) => _overlaps({ x: base.get(id).x, y: base.get(id).y + dy, h: hOf(id) }, b)));
      for (let guard = 0; guard <= ids.length && clash(); guard++) dy += row;
      for (const id of free) {
        const a = { x: base.get(id).x, y: base.get(id).y + dy, h: hOf(id) };
        taken.push(a);
        placed.set(id, a);
      }
    }
  }

  const nodes = ids.map((id) => ({
    id,
    x: _r(placed.get(id).x),
    y: _r(placed.get(id).y),
    h: hOf(id),
    saved: fixed.has(id),
    missing: !known.has(id),
  }));
  return {
    nodes,
    bounds: boundsOf(nodes),
    components: chains.concat(lone).map((c) => c.members.slice()),
  };
}

/** The box around a set of steps, node size included (a point's own `h`
 *  when it has one). Empty → a zero box. */
export function boundsOf(points) {
  const list = [...(points || [])];
  if (!list.length) return { x: 0, y: 0, w: 0, h: 0 };
  const xs = list.map((p) => p.x);
  const x = Math.min(...xs);
  const y = Math.min(...list.map((p) => p.y));
  return { x, y, w: Math.max(...xs) + NODE_W - x, h: Math.max(...list.map((p) => p.y + _h(p))) - y };
}

/** Where an arrow for condition `when` leaves a step at `pos`. `ports` is the
 *  step's own list (`P22-10`: an If's, a Switch's); without it, the two every
 *  task has, so `P22-02`'s geometry is unchanged. */
export function portPoint(pos, when, ports) {
  return { x: _r(pos.x + NODE_W), y: _r(pos.y + PORT_TOP + _portIndex(when, ports) * PORT_STEP) };
}

/** The port's offset from the step's top edge, for the canvas to place it. */
export function portOffset(when, ports) {
  return PORT_TOP + _portIndex(when, ports) * PORT_STEP;
}

/** Where every arrow arrives on a step at `pos`: halfway down its left edge
 *  (`pos.h` for a taller step; `NODE_H` otherwise, as it always was). */
export function inputPoint(pos) {
  return { x: _r(pos.x), y: _r(pos.y + _h(pos) / 2) };
}

/** A curve from a port to a step's input — horizontal at both ends, so it
 *  leaves the port and arrives at the step the way the arrowhead points. */
export function edgePath(a, b) {
  const dx = Math.max(48, Math.abs(b.x - a.x) / 2);
  return `M ${_r(a.x)} ${_r(a.y)} C ${_r(a.x + dx)} ${_r(a.y)}, ${_r(b.x - dx)} ${_r(b.y)}, ${_r(b.x)} ${_r(b.y)}`;
}

/** The curve's midpoint, where its words go. For this curve it is the plain
 *  midpoint of the two ends — the two control offsets cancel at t = ½. */
export function edgeMid(a, b) {
  return { x: _r((a.x + b.x) / 2), y: _r((a.y + b.y) / 2) };
}

/** `B1053`. How far a routed arrow runs straight out of its port and straight
 *  into its step before it turns, how far it keeps from the steps it goes
 *  round, and the radius of its corners. */
const ROUTE_STUB = 24;
const ROUTE_CLEAR = 20;
const ROUTE_CORNER = 10;
/** The narrowest gap the plain curve crosses without dipping under either
 *  step. Measured on `edgePath`'s own control points: at a gap of 16 its
 *  lowest x is the source's right edge, and below that it goes under it. */
const CURVE_MIN_GAP = 16;

/** A polyline of axis-aligned points as a path with rounded corners. */
function _rounded(points) {
  let d = `M ${_r(points[0].x)} ${_r(points[0].y)}`;
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1];
    const p = points[i];
    const next = points[i + 1];
    const k = Math.min(ROUTE_CORNER,
      (Math.abs(p.x - prev.x) + Math.abs(p.y - prev.y)) / 2,
      (Math.abs(next.x - p.x) + Math.abs(next.y - p.y)) / 2);
    const toward = (q) => ({ x: p.x + Math.sign(q.x - p.x) * k, y: p.y + Math.sign(q.y - p.y) * k });
    const a = toward(prev);
    const b = toward(next);
    d += ` L ${_r(a.x)} ${_r(a.y)} Q ${_r(p.x)} ${_r(p.y)} ${_r(b.x)} ${_r(b.y)}`;
  }
  const last = points[points.length - 1];
  return d + ` L ${_r(last.x)} ${_r(last.y)}`;
}

/**
 * `B1053`. The arrow for condition `when` from the step at `from` to the step
 * at `to`: `{ d, label: { x, y }, end, routed }`.
 *
 * An arrow leaves a step's right edge and arrives at another's left edge.
 * When the target is to the right that is `edgePath`'s curve, unchanged. When
 * it is not — a step on the left, or stacked under — that same curve ran back
 * UNDER both steps, and its one visible piece, with its words, sat between
 * them leaving the TARGET's port: measured on the merged tree, an *if it
 * fails* from Ann target to Zed source read as "if Zed source fails, run Ann
 * target", 12 of 21 sampled points under the two boxes. So it is routed round:
 * out of the port, along a lane that clears both steps — between their rows
 * when there is room, otherwise above them for the first port and below for
 * the second, so the two arrows of one step take different lanes — and into
 * the target from its left, where the arrowhead points in. The words sit on
 * the lane, clear of both boxes.
 */
export function edgeRoute(from, to, when, ports) {
  const a = portPoint(from, when, ports);
  const b = inputPoint(to);
  if (b.x - a.x >= CURVE_MIN_GAP) {
    const m = edgeMid(a, b);
    return { d: edgePath(a, b), label: { x: m.x, y: _r(m.y - 6) }, end: b, routed: false };
  }
  const fromTop = from.y;
  const fromBottom = from.y + _h(from);
  const toTop = to.y;
  const toBottom = to.y + _h(to);
  let lane;
  if (toBottom + ROUTE_CLEAR * 2 <= fromTop) lane = (toBottom + fromTop) / 2;
  else if (fromBottom + ROUTE_CLEAR * 2 <= toTop) lane = (fromBottom + toTop) / 2;
  else if (_portIndex(when, ports) === 0) lane = Math.min(fromTop, toTop) - ROUTE_CLEAR;
  else lane = Math.max(fromBottom, toBottom) + ROUTE_CLEAR;
  const out = a.x + ROUTE_STUB;
  const into = b.x - ROUTE_STUB;
  const d = _rounded([a, { x: out, y: a.y }, { x: out, y: lane }, { x: into, y: lane },
    { x: into, y: b.y }, b]);
  return { d, label: { x: _r((out + into) / 2), y: _r(lane - 6) }, end: b, routed: true };
}

/** The arrowhead at `b`, pointing the way the curve arrives (rightwards). */
export function arrowPath(b) {
  return `M ${_r(b.x)} ${_r(b.y)} L ${_r(b.x - 9)} ${_r(b.y - 5)} L ${_r(b.x - 9)} ${_r(b.y + 5)} Z`;
}

/** The step under a canvas point, or null. The last one drawn wins, as it
 *  would on screen; `exclude` is the step an arrow is being dragged from. */
export function nodeAt(nodes, point, exclude) {
  const list = [...(nodes || [])];
  for (let i = list.length - 1; i >= 0; i--) {
    const n = list[i];
    if (exclude != null && String(n.id) === String(exclude)) continue;
    if (point.x >= n.x && point.x <= n.x + NODE_W && point.y >= n.y && point.y <= n.y + _h(n)) {
      return String(n.id);
    }
  }
  return null;
}

export function clampZoom(z) {
  const n = Number(z);
  if (!Number.isFinite(n)) return 1;
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, n));
}

/**
 * The zoom and offset that show `bounds` in a `width` × `height` viewport.
 *
 * Never zooms in past 1 — fitting two steps should not make them enormous.
 * A viewport with no size yet (a window still opening) gets zoom 1 with the
 * box's corner at the padding, rather than a division by zero.
 */
export function fitView(bounds, width, height, pad = MARGIN) {
  const w = Number(width) || 0;
  const h = Number(height) || 0;
  if (!bounds || w <= 0 || h <= 0 || bounds.w <= 0 || bounds.h <= 0) {
    return { zoom: 1, x: _r(pad - ((bounds && bounds.x) || 0)), y: _r(pad - ((bounds && bounds.y) || 0)) };
  }
  const floor = w < NARROW_FIT_WIDTH ? FIT_FLOOR_NARROW : ZOOM_MIN;
  const zoom = clampZoom(Math.max(floor, Math.min(1, (w - pad * 2) / bounds.w, (h - pad * 2) / bounds.h)));
  // `B1113`. Centred when it fits. When it does not — the zoom is at its floor
  // and the graph is still wider (or taller) than the viewport — its first
  // column (row) sits at the padding: centring put the start off the left
  // edge (measured at 390 px: a six-step run's "Starts" at x −75…6), and the
  // start is where a person begins reading. Panning reaches the rest.
  const lay = (room, size, from) => (size * zoom > room - pad * 2
    ? pad - from * zoom
    : (room - size * zoom) / 2 - from * zoom);
  return {
    zoom: Math.round(zoom * 1000) / 1000,
    x: _r(lay(w, bounds.w, bounds.x)),
    y: _r(lay(h, bounds.h, bounds.y)),
  };
}

export default {
  layoutGraph, boundsOf, portPoint, portOffset, inputPoint, edgePath, edgeMid, edgeRoute,
  arrowPath, nodeAt, clampZoom, fitView, nodeHeight,
  NODE_W, NODE_H, GAP_X, GAP_Y, MARGIN, LONE_COLUMNS, ZOOM_MIN, ZOOM_MAX, PORTS,
  NARROW_FIT_WIDTH, FIT_FLOOR_NARROW,
};
