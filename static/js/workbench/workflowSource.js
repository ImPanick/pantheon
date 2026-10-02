// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/workflowSource.js
//
// `P22-05`…`P22-08`. A workflow document as a canvas source: the object the
// Workbench's one canvas (`canvas.js`) draws and edits through, so a document
// is drawn on the same canvas as the tasks and chains are (`Law 14`) — the
// tasks' own source is `taskSource.js`. The contract is `C3` in
// `/work/notes/SLICE-B-DESIGN.md` § 7:
//
//   { readOnly, words, load() → { items, edges }, connect(from, when, to),
//     disconnect(from, when, to) → { ok, sentence? }, loadPositions(),
//     savePositions(map), openPanel(host, item, { onSaved, onCancel }),
//     newItem(anchor), removeItem(id), dryRun() }
//
// **A document is edited as a draft and saved on purpose** (design § 6.2).
// Every edit — an arrow drawn or taken away, a step added, changed or removed,
// a rename — changes the person's working copy only; `save()` writes it, with
// the version it started from (`base_version`), and the server answers 409 if
// somebody saved in between (nothing is overwritten). `discard()` throws the
// draft away. Two things are not content and save themselves at once, never
// making a version: where a step sits (`savePositions`) and a sample pinned on
// a step (`setPin`) — the server's fingerprint leaves both out as well.
//
// **The server decides what a workflow may be** (`P22-01`'s one rule, in the
// engine's `validate_document`). Drawing an arrow asks it — `PUT ?check=true`
// with the draft as it would be, which writes nothing — and a refusal is the
// server's sentence, word for word. A draft that is still being built (a new
// step not joined to anything yet, a prompt not written yet) is refused for
// that too; an arrow is refused only when IT is the problem — when the draft
// without it did not have the same one — and the draft's own unfinished state
// is kept as `state().problem`, which Save will say again.
//
// **The start is drawn as a step**: `__start__`, "Starts · Every day at 08:00"
// (the trigger's words from `describeTrigger`, the Tasks window's), with a
// fixed arrow into the step that goes first. It is not in `graph.nodes`; its
// place is `graph.start.position`, and its settings are the trigger task's,
// edited through the injected start panel (`PUT /api/tasks/{id}`).
//
// **A run is drawn read-only** (`mode: 'run'`, `P22-07`): the graph of the
// version that run used, each step's outcome from its node record
// (`runStatus.js`, the one vocabulary), a step it never reached saying so, and
// the step that failed named in `state().failed` so the room can open on it.
//
// Nothing here draws or words a panel: the palette, the step form, the start
// form and the record panel are injected (`panels`), and every word a person
// wrote reaches the canvas as data the canvas sets as text.
//
// **Slices C and D (`P22-09`…`P22-18`, wf-canvas; `SLICE-CD-DESIGN.md` § 3,
// contract C-W).** The palette (C-W's palette route, `api.getPalette`) is read once
// when a document opens: the kinds a person may add — each with its ports,
// whether it is available and, when it is not, why — and the integrations, MCP
// tools, skills and AI tools the step panels offer. A step's ports are its
// kind's (an If's *if so* / *otherwise*; a Switch's one per case, `case:<id>`,
// then *otherwise*), drawn with their words. Several arrows may leave one port
// (`fanOut`), and the start has one port of its own whose arrows are real
// (`{from: "start", port: "success", to}`): a document with none keeps Slice
// B's one implied entry, and the first arrow drawn from the start writes that
// entry out beside the new one, so nothing that ran stops running. A new step's
// id is a slug of its label (`fetch-issue`), taken when it is first named and
// kept through every later rename, so a reference reads like words. A run that
// is waiting (`P22-11`, `P22-17`) names its waiting step in `state().waiting`,
// and its question is answered through `answer()` (`POST …/answer`,
// `approve_task` or `deny`).
//
// **Slice E (`P22-19`, `P22-20`, `P22-24`, wb-canvas-e; `SLICE-EF-DESIGN.md`
// § 1.1, § 2, contract C-A).** A step the model drafted or a file brought in
// carries the server's mark (`node.unchecked = { origin, at, needs }`) until a
// person says it looks right. The mark is the SAVED document's — the server
// keeps it, a save can neither set nor clear it, and a step the person changed
// loses it on Save (`_marks_kept`) — so it is drawn from the saved node, and
// only while the draft's step still reads as that node does: a step changed
// here is the person's, as it will be once saved. Drawn as words on the step
// ("Drafted — check me"), the step's `unchecked` origin for its dashed border,
// and handed to its panel (`check`) with its `needs`, what it would do and
// *Looks right* (`checkSteps`, C-A's `PUT {checked}`, which writes no version).
// What a step would do is the dry run's plan of the saved version — the one
// planner (`plan_lines`), the existing door, which plans a marked step
// (design § 1.1) — asked once per saved version (`planLines`). A run's failed
// step can be explained (`explain`, C-A's explain route) and a proposed change
// applied as a new version (`fix`, source `fixed`) and undone with
// `restoreVersion`. The saved workflow is a file (`exportFile`).

import { EDGE_WORDS, KIND_WORDS, PORT_WORDS, ONLY_WAY_WORD, waitingWords } from '../tasks/workflowDiagram.js';
import { runStatusTone, runStatusLabel } from '../runStatus.js';
import { PORTS } from './graphLayout.js';
import { WorkflowRefusal } from './workflowApi.js';

/** The start's item id on the canvas. Never a step's id: a step's id is
 *  `[A-Za-z0-9_-]`, so it can never hold the start's underscores-only shape
 *  as a slug of a label (`slugOf` keeps letters and digits). */
export const START_ID = '__start__';
/** The document's own key for the start (`graph.start`, the positions map,
 *  and the `from` of a start arrow) — `START_KEY` in `src/workflow_document.py`. */
const START_KEY = 'start';

/** `P22-09`. The id rule a step's id must keep (`src/workflow_document.py`). */
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

/**
 * `P22-09`. A step's id from its label: "Fetch issue" → `fetch-issue`, so a
 * reference written into another step reads like words
 * (`{{ steps.fetch-issue.data.title }}`). Letters and digits, joined by
 * hyphens, at most 40 characters; a label with none becomes `step`.
 */
export function slugOf(label) {
  const base = String(label == null ? '' : label).normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/g, '');
  return base || 'step';
}

/** `slugOf(label)`, made unique among `taken` (and never the start's key). */
function freeId(label, taken) {
  const base = slugOf(label);
  let id = base;
  for (let i = 2; taken.has(id) || id === START_KEY || !ID_RE.test(id); i += 1) id = `${base}-${i}`;
  return id;
}

/** `P22-10`. The ports a kind leaves by when no palette says (`ports_of`,
 *  `src/workflow_document.py` § 1.3's table) — the palette's own `ports` win
 *  when it is loaded; a Switch's are always its cases'. */
export const KIND_PORTS = Object.freeze({
  llm: ['success', 'error'], research: ['success', 'error'], action: ['success', 'error'],
  run_task: ['success', 'error'], http: ['success', 'error'], mcp: ['success', 'error'],
  skill: ['success', 'error'], code: ['success', 'error'], foreach: ['success', 'error'],
  if: ['then', 'otherwise'], set: ['success'], merge: ['success'], wait: ['success'],
});
/** The prefix of a Switch case's port (`case:<id>`), a stored word. */
export const CASE_PREFIX = 'case:';

/** The ports step `node` leaves by: a Switch's one per case and then
 *  *otherwise*; any other kind's from the palette's entry for it, else
 *  `KIND_PORTS`, else the two every task has. */
export function portsOfNode(node, palette) {
  const kind = String((node && node.kind) || 'llm');
  if (kind === 'switch') {
    const cases = Array.isArray(node && node.config && node.config.cases) ? node.config.cases : [];
    return [...cases.filter((c) => c && c.id != null && String(c.id) !== '').map((c) => CASE_PREFIX + String(c.id)), 'otherwise'];
  }
  const entry = palette && Array.isArray(palette.kinds) ? palette.kinds.find((k) => k && k.kind === kind) : null;
  if (entry && Array.isArray(entry.ports) && entry.ports.length) return entry.ports.map(String);
  return (KIND_PORTS[kind] || PORTS).slice();
}

/** The words on each of `node`'s ports: a Switch case's own label, "then"
 *  for a step with one way out, the shared words for the rest. */
export function portWordsOf(node, ports) {
  const out = {};
  const cases = Array.isArray(node && node.config && node.config.cases) ? node.config.cases : [];
  for (const p of ports) {
    if (p.startsWith(CASE_PREFIX)) {
      const c = cases.find((x) => x && CASE_PREFIX + String(x.id) === p);
      out[p] = c && String(c.label || '').trim() ? `if ${String(c.label).trim()}` : 'if this case';
    } else if (ports.length === 1 && p === 'success') {
      out[p] = ONLY_WAY_WORD;
    } else {
      out[p] = PORT_WORDS[p] || p;
    }
  }
  return out;
}

/** What the canvas says while a document is being edited. */
export const EDIT_WORDS = Object.freeze({
  region: 'Steps of this workflow',
  emptyTitle: 'No steps yet.',
  // `P22-10`…`P22-18` (wf-canvas): the kinds a step can be now, and its ways
  // out beyond the two every task has.
  emptyText: 'Add a step, and the start leads to it. A step asks a model, decides which way to go, '
    + 'calls a service, waits, or runs your code.',
  hint: 'Drag from a step’s way out — “' + EDGE_WORDS.success + '”, “' + EDGE_WORDS.error + '”, “'
    + PORT_WORDS.then + '”, a case — onto the step that should run next, or use its Connect… button. '
    + 'Click a step to change it. Your changes stay here until you press Save.',
  newLabel: 'New step',
  newTitle: 'Add a step to this workflow',
  unknownName: 'a step that is not in this workflow',
  missingTitle: 'A step that is not in this workflow',
  missingSub: '',
  loadFailed: 'This workflow could not be loaded. Close the Workbench and open it again to retry.',
});

/** What the canvas says over a run (`P22-07`). */
export const RUN_WORDS = Object.freeze({
  region: 'This run, step by step',
  emptyTitle: 'This run left no steps.',
  emptyText: '',
  hint: 'Each step says how it went in this run. Click one to read what it was handed and what it made.',
  newLabel: 'New step',
  newTitle: '',
  unknownName: 'a step that is not in this run',
  missingTitle: 'A step that is not in this version',
  missingSub: '',
  loadFailed: 'This run could not be loaded. Close the Workbench and open it again to retry.',
});

/** `P22-19`, `P22-24`. The words on a step nobody has checked yet, by the
 *  mark's `origin` (stored words, C-A: `drafted` | `imported`). */
export const MARK_WORDS = Object.freeze({
  drafted: 'Drafted — check me',
  imported: 'Imported — check me',
});
/** The origin of a mark, read safely: a known word, else `drafted` (a mark the
 *  server set is a mark whatever its origin says — fails closed). */
export function markOrigin(unchecked) {
  const o = unchecked && typeof unchecked === 'object' ? String(unchecked.origin || '') : '';
  return Object.prototype.hasOwnProperty.call(MARK_WORDS, o) ? o : 'drafted';
}
/** A mark's `needs`, as the server wrote them (`[{ field, name, preset?,
 *  server?, tool? }]`), keeping only entries that are objects. */
export function needsOf(unchecked) {
  const n = unchecked && typeof unchecked === 'object' && Array.isArray(unchecked.needs) ? unchecked.needs : [];
  return n.filter((x) => x && typeof x === 'object').map((x) => ({ ...x }));
}

const STARTS_LABEL = 'starts';
/** `P22-13`…`P22-18`. What the canvas says under a step, by kind: one short
 *  line of what it does, from its own settings. */
const WAIT_UNIT = (m) => (m % 60 === 0 && m >= 60 ? `${m / 60} h` : `${m} min`);
const NOT_REACHED = 'Not reached in this run';
const PINNED_MARK = 'Sample pinned';
const READ_ONLY = 'This is a record, so it cannot be changed here.';
const START_FIXED = 'The start always leads to the step that goes first; draw arrows between steps.';
const CLEARED = 'Its step details were cleared after the time Pantheon keeps them '
  + '(workflow_node_records_days). The run’s own summary is still in the list.';

// ── pure helpers ───────────────────────────────────────────────────────────

const clone = (value) => (value == null ? value : JSON.parse(JSON.stringify(value)));

/** JSON with every object's keys in order, so two equal documents read equal
 *  however their settings were typed in. */
function stable(value) {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map((k) => JSON.stringify(k) + ':' + stable(value[k])).join(',') + '}';
  }
  return JSON.stringify(value === undefined ? null : value);
}

const nodesOf = (g) => (Array.isArray(g && g.nodes) ? g.nodes.filter((n) => n && n.id != null) : []);
const edgesOf = (g) => (Array.isArray(g && g.edges)
  ? g.edges.filter((e) => e && e.from != null && e.to != null) : []);

/** What a Save would write that makes it a change: the name, each step's id,
 *  kind, label and settings, and the arrows. Not where a step sits and not a
 *  pinned sample — the server's `content_fingerprint` leaves both out too, so
 *  "Unsaved changes" and "a new version" mean the same thing. */
export function contentOf(name, graph) {
  return stable({
    name: String(name || ''),
    nodes: nodesOf(graph).map((n) => ({
      id: String(n.id), kind: String(n.kind || ''), label: String(n.label || ''), config: n.config || {},
    })).sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
    edges: edgesOf(graph).map((e) => [String(e.from), String(e.port || ''), String(e.to)]).sort(),
  });
}

/** The step that goes first: the one nothing leads to. While a draft has
 *  several, the first in the document (the oldest) is drawn as first. */
function entryOf(graph) {
  const led = new Set(edgesOf(graph).map((e) => String(e.to)));
  return nodesOf(graph).find((n) => !led.has(String(n.id))) || null;
}

/** `[x, y]` from `[x, y]` or `{ x, y }`, or null — and null for a missing
 *  place, which `Number(null)` would otherwise read as the origin. */
function point(value) {
  if (value == null || typeof value !== 'object') return null;
  const [rx, ry] = Array.isArray(value) ? value : [value.x, value.y];
  if (rx == null || ry == null || rx === '' || ry === '') return null;
  const x = Number(rx);
  const y = Number(ry);
  return Number.isFinite(x) && Number.isFinite(y) ? [Math.round(x), Math.round(y)] : null;
}

const samePoint = (a, b) => stable(point(a)) === stable(point(b));

function refusalOf(err) {
  if (err instanceof WorkflowRefusal) return err;
  return new WorkflowRefusal(0, String((err && err.message) || 'Something went wrong.'));
}

const answer = (err) => {
  const r = refusalOf(err);
  return { ok: false, status: r.status, sentence: r.sentence, reason: r.reason, nodeIds: r.nodeIds,
    field: r.field || null };
};

/**
 * A workflow document, or one of its runs, as a canvas source.
 *
 * `api`            — `createWorkflowApi(...)`.
 * `workflowId`     — the document.
 * `mode`           — `'edit'` (the default) or `'run'`.
 * `runId`          — the run to draw, in `'run'` mode.
 * `describeTrigger(task)` — the Tasks window's words for what starts a task.
 * `panels`         — `{ palette(anchor) → Promise<kind|null>,
 *                       node(host, { node, tasks, workflow, source, onApply, onCancel }) → { destroy },
 *                       start(host, { triggerTask, tasks, onSaved, onCancel }) → { destroy },
 *                       record(host, { node, record, run }) → { destroy } }`.
 * `onState(state)` — called after every change to what `state()` answers.
 */
export function createWorkflowSource({
  api, workflowId, mode = 'edit', runId = null, describeTrigger, panels = {}, onState,
} = {}) {
  const S = {
    doc: null, draft: null, base: null, gen: 0,
    tasks: [], run: null, viewing: null,
    checks: [], problem: null, stale: false, busy: false, loadError: null,
    // `P22-09`…`P22-18`. The palette (C-W), or null when this Pantheon has
    // none to serve (the panels then offer Slice B's four kinds); and the
    // steps added in this draft whose id still follows their first label.
    palette: null, paletteError: null, fresh: new Set(),
    // `P22-19`. What each step of the saved version would do, from its dry
    // run: `{ version, promise }`, asked once per saved version.
    plans: null,
  };
  const isRun = mode === 'run';
  const describe = (task) => {
    if (typeof describeTrigger !== 'function' || !task) return '';
    try { return String(describeTrigger(task) || ''); } catch (_) { return ''; }
  };

  // ── state ────────────────────────────────────────────────────────────────

  const readOnly = () => isRun || !!S.viewing;
  const dirty = () => !isRun && !!S.doc && !!S.draft
    && contentOf(S.draft.name, S.draft.graph) !== contentOf(S.doc.name, S.doc.graph);
  const trigger = () => (S.doc && S.doc.trigger_task) || null;
  const isOn = () => !!S.doc && S.doc.trigger_status === 'active';
  const shown = () => (isRun ? (S.run && S.run.graph) : S.viewing ? S.viewing.graph : S.draft && S.draft.graph) || {};
  const draftNode = (id) => nodesOf(S.draft && S.draft.graph).find((n) => String(n.id) === String(id)) || null;
  const savedNode = (id) => nodesOf(S.doc && S.doc.graph).find((n) => String(n.id) === String(id)) || null;
  const shownNode = (id) => nodesOf(shown()).find((n) => String(n.id) === String(id)) || null;
  const taskById = (id) => S.tasks.find((t) => String(t.id) === String(id)) || null;

  /** `P22-19`, `P22-24`. Step `id`'s mark, as `{ origin, needs, at }`, or
   *  null: the saved node's, while the draft's step still reads as it (its
   *  kind, label and settings — the server's `_marks_kept` rule). Never on a
   *  run or a kept version: their graphs carry no marks (`version_graph`). */
  function markOf(id) {
    if (isRun || S.viewing) return null;
    const saved = savedNode(id);
    if (!saved || !saved.unchecked || typeof saved.unchecked !== 'object') return null;
    const now = draftNode(id);
    const same = (a, b) => stable({ k: a.kind || '', l: a.label || '', c: a.config || {} })
      === stable({ k: b.kind || '', l: b.label || '', c: b.config || {} });
    if (!now || !same(now, saved)) return null;
    return { origin: markOrigin(saved.unchecked), needs: needsOf(saved.unchecked), at: saved.unchecked.at || null };
  }

  /** Every step of the saved document still marked — `{ id, label, kind,
   *  origin, needs, changed }`, in the document's order; `changed` is a step
   *  the draft has changed (it is the person's once saved). */
  function marked() {
    if (isRun || !S.doc) return [];
    return nodesOf(S.doc.graph)
      .filter((n) => n.unchecked && typeof n.unchecked === 'object')
      .map((n) => ({
        id: String(n.id), label: String(n.label || KIND_WORDS[n.kind] || n.id), kind: String(n.kind || 'llm'),
        origin: markOrigin(n.unchecked), needs: needsOf(n.unchecked), changed: !markOf(n.id),
      }));
  }

  /** The newest record of a step in the run being drawn — the step's own,
   *  not one of a For-each's items (`P22-12`: those carry `item`). */
  function recordOf(id) {
    const recs = (S.run && Array.isArray(S.run.nodes) ? S.run.nodes : [])
      .filter((r) => String(r.node_id) === String(id) && (r.item == null));
    return recs.length ? recs[recs.length - 1] : null;
  }

  /** `P22-12`. A For-each step's item records, in item order. */
  function itemRecordsOf(id) {
    return (S.run && Array.isArray(S.run.nodes) ? S.run.nodes : [])
      .filter((r) => String(r.node_id) === String(id) && r.item != null)
      .sort((a, b) => (Number(a.item) - Number(b.item)) || ((Number(a.seq) || 0) - (Number(b.seq) || 0)));
  }

  /** `P22-11`, `P22-17`. The step a waiting run waits on: its record whose
   *  status is `waiting` (an item's, if the step is a For-each's). */
  function waitingStep() {
    if (!isRun || !S.run) return null;
    const recs = (Array.isArray(S.run.nodes) ? S.run.nodes : []).filter((r) => r && r.status === 'waiting');
    const rec = recs[recs.length - 1];
    if (!rec) return null;
    const w = rec.waiting && typeof rec.waiting === 'object' ? rec.waiting : {};
    return {
      nodeId: String(rec.node_id), item: rec.item == null ? null : Number(rec.item),
      label: String(rec.label || rec.node_id), kind: w.kind || null, since: w.since || null,
      until: w.until || null, approval: w.approval || null, words: waitingWords(w),
    };
  }

  /** `P22-09`. The steps that run before `id` — the ones a reference in it
   *  may name — and the start, in the order a walk back from it meets them. */
  function upstreamOf(id) {
    const g = S.draft ? S.draft.graph : shown();
    const into = new Map();
    for (const e of edgesOf(g)) {
      const to = String(e.to);
      if (!into.has(to)) into.set(to, []);
      into.get(to).push(String(e.from));
    }
    // Slice B's implied entry: a document with no start arrows starts at the
    // step nothing leads to.
    if (!edgesOf(g).some((e) => String(e.from) === START_KEY)) {
      const first = entryOf(g);
      if (first) {
        if (!into.has(String(first.id))) into.set(String(first.id), []);
        into.get(String(first.id)).push(START_KEY);
      }
    }
    const seen = new Set();
    const out = [];
    const queue = [String(id)];
    while (queue.length) {
      for (const from of into.get(queue.shift()) || []) {
        if (seen.has(from) || from === String(id)) continue;
        seen.add(from);
        queue.push(from);
        if (from === START_KEY) out.push({ id: START_KEY, label: 'The start', kind: 'start' });
        else {
          const n = nodesOf(g).find((x) => String(x.id) === from);
          if (n) out.push({ id: from, label: String(n.label || KIND_WORDS[n.kind] || from), kind: String(n.kind || 'llm') });
        }
      }
    }
    return out;
  }

  /** The step a failed run failed on: the one the server names (`failed`,
   *  the walker's own rule — the last step that failed with no arrow out of
   *  its failure port), else the last record when it failed (a reply with no
   *  `failed`: a run drawn on a version no longer kept). `integrate-d`: the
   *  last record is not the failed one once branches run side by side or a
   *  For-each's items are recorded after it. */
  function failedStep() {
    if (!isRun || !S.run || !S.run.run || S.run.run.status !== 'error') return null;
    const named = S.run.failed;
    if (named && named.node_id != null) {
      return {
        nodeId: String(named.node_id),
        label: String(named.label || named.node_id),
        firstLine: String(named.error || '').split('\n')[0].trim(),
      };
    }
    const recs = (Array.isArray(S.run.nodes) ? S.run.nodes : []).filter((r) => !r.dry);
    const last = recs[recs.length - 1];
    if (!last || last.status !== 'error') return null;
    return {
      nodeId: String(last.node_id),
      label: String(last.label || last.node_id),
      firstLine: String(last.error || '').split('\n')[0].trim(),
    };
  }

  function state() {
    const doc = S.doc;
    return {
      mode: isRun ? 'run' : 'edit',
      readOnly: readOnly(),
      workflowId: String(workflowId),
      runId: runId != null ? String(runId) : null,
      name: S.draft ? S.draft.name : (doc ? doc.name : ''),
      savedName: doc ? doc.name : '',
      version: doc ? doc.version : null,
      base: S.base,
      on: isOn(),
      dirty: dirty(),
      stale: S.stale,
      busy: S.busy,
      problem: S.problem,
      viewing: S.viewing ? {
        version: S.viewing.version, name: S.viewing.name, saved_at: S.viewing.saved_at,
        source: S.viewing.source, current: !!S.viewing.current,
      } : null,
      workflow: doc,
      run: isRun && S.run ? S.run.run : null,
      versionKept: isRun && S.run ? !!S.run.version_kept : null,
      cleared: isRun && S.run ? !!S.run.cleared : null,
      failed: failedStep(),
      waiting: waitingStep(),
      loadError: S.loadError ? S.loadError.sentence : null,
      palette: S.palette,
      paletteError: S.paletteError,
    };
  }

  function emit() {
    if (typeof onState !== 'function') return;
    try { onState(state()); } catch (_) { /* the room's listener is its own */ }
  }

  /** A served document becomes the one held. The draft follows it only when
   *  it has no edits of its own, so a save elsewhere never overwrites the
   *  person's work — their next Save is answered 409 instead. */
  function takeDoc(doc, { force = false } = {}) {
    if (!doc) return;
    const follow = force || !S.draft || !dirty();
    S.doc = clone(doc);
    if (follow) {
      S.draft = { name: String(doc.name || ''), graph: clone(doc.graph) || { nodes: [], edges: [] } };
      S.base = doc.version;
    }
  }

  function edited() {
    S.gen += 1;
    emit();
  }

  // ── loading ──────────────────────────────────────────────────────────────

  async function init() {
    try {
      if (isRun) {
        const [run, wf] = await Promise.all([
          api.getExecution(workflowId, runId),
          api.getWorkflow(workflowId).catch(() => null),
        ]);
        S.run = run || { graph: {}, nodes: [] };
        if (wf && wf.workflow) S.doc = clone(wf.workflow);
      } else {
        const wf = await api.getWorkflow(workflowId);
        takeDoc(wf && wf.workflow, { force: true });
        try {
          const listed = await api.listTasks();
          S.tasks = Array.isArray(listed && listed.tasks) ? listed.tasks : [];
        } catch (_) {
          // A run-task step's picker is then empty; the document still opens.
          S.tasks = [];
        }
      }
      await loadPalette();
    } catch (err) {
      S.loadError = refusalOf(err);
    }
    emit();
    return state();
  }

  /** `P22-10`…`P22-18`. The palette, once (C-W's `getPalette`). A Pantheon
   *  without the route, or a refusal, leaves it null and says why; the
   *  document opens either way and the panels offer Slice B's four kinds. */
  async function loadPalette() {
    if (!api || typeof api.getPalette !== 'function') return;
    try {
      const p = await api.getPalette();
      S.palette = p && typeof p === 'object' ? p : null;
      S.paletteError = null;
    } catch (err) {
      S.palette = null;
      S.paletteError = refusalOf(err).sentence;
    }
  }

  const ready = init();

  /** Read the document (or the run) again from the server — for a run still
   *  in progress, or after a change made somewhere else. Edits in the draft
   *  are kept (see `takeDoc`). */
  async function refresh() {
    await ready;
    try {
      if (isRun) {
        S.run = await api.getExecution(workflowId, runId);
      } else {
        const wf = await api.getWorkflow(workflowId);
        takeDoc(wf && wf.workflow);
        if (S.doc && S.base != null && S.doc.version !== S.base) S.stale = true;
      }
      S.loadError = null;
      emit();
      return { ok: true };
    } catch (err) {
      return answer(err);
    }
  }

  // ── the canvas source ────────────────────────────────────────────────────

  function startItem() {
    const t = trigger();
    let outcome = { tone: 'none', word: isOn() ? 'Switched on' : 'Switched off' };
    if (isRun) {
      const steps = S.run && S.run.run && Array.isArray(S.run.run.steps) ? S.run.run.steps : [];
      const cause = steps.find((s) => s && s.kind === 'trigger');
      outcome = { tone: 'info', word: String((cause && cause.detail) || 'Started') };
    }
    // `P22-11`. The start has one port, *starts*: an arrow drawn from it is
    // a real arrow of the document, and several may leave it.
    return {
      id: START_ID, name: 'Starts', kind: 'start',
      sub: describe(t) || (t ? '' : 'Its start could not be read'),
      paused: !isRun && !isOn(), outcome, ports: ['success'], portWords: { success: STARTS_LABEL },
      entry: true, marks: [], accepts: false, missing: false, fixed: true,
    };
  }

  /** `P22-13`…`P22-18`. One short line of what a step does, from its own
   *  settings: what a person needs to tell two steps of one kind apart. */
  function detailOf(kind, config) {
    const c = config || {};
    const pal = S.palette || {};
    const named = (list, key, value) => (Array.isArray(list) ? list.find((x) => x && String(x[key]) === String(value)) : null);
    switch (kind) {
      case 'action': return c.action ? String(c.action) : '';
      case 'run_task': {
        const target = taskById(c.task_id);
        return target ? `Runs “${target.name || 'Untitled task'}”`
          : (c.task_id ? 'Runs a task that is not in your list' : 'Choose the task it runs');
      }
      case 'http': {
        const integ = named(pal.integrations, 'id', c.integration);
        const where = [String(c.method || 'GET').toUpperCase(), c.path ? String(c.path) : ''].filter(Boolean).join(' ');
        return [integ ? integ.name : (c.integration ? '' : 'Choose an integration'), c.integration ? where : ''].filter(Boolean).join(' · ');
      }
      case 'mcp': {
        const tool = named(pal.mcp_tools, 'qualified_name', c.tool);
        return tool ? `${tool.server_name || ''}${tool.server_name ? ': ' : ''}${tool.name}` : (c.tool ? String(c.tool) : 'Choose a tool');
      }
      case 'skill': return c.skill ? `Follows “${c.skill}”` : 'Choose a skill';
      case 'code': return c.language === 'bash' ? 'Bash' : 'Python';
      case 'wait': {
        if (c.mode === 'until' && c.time) return `Until ${c.time}`;
        const m = Number(c.minutes);
        return Number.isFinite(m) && m > 0 ? `For ${WAIT_UNIT(m)}` : 'Choose how long';
      }
      case 'merge': return c.mode === 'first' ? 'Goes on with the first to arrive' : 'Waits for every branch';
      case 'set': {
        const n = Array.isArray(c.fields) ? c.fields.length : 0;
        return n ? `${n} field${n === 1 ? '' : 's'}` : 'Choose the fields';
      }
      case 'switch': {
        const n = Array.isArray(c.cases) ? c.cases.length : 0;
        return n ? `${n} case${n === 1 ? '' : 's'}` : 'Add a case';
      }
      case 'if': {
        const n = Array.isArray(c.conditions) ? c.conditions.length : 0;
        return n ? `${n} condition${n === 1 ? '' : 's'}` : 'Add a condition';
      }
      case 'foreach': {
        const inner = c.step && typeof c.step === 'object' ? c.step : null;
        return inner ? `Each item: ${inner.label || KIND_WORDS[inner.kind] || inner.kind || 'a step'}` : 'Choose what it does for each item';
      }
      case 'llm': {
        const parts = [];
        if (Array.isArray(c.tools)) parts.push(c.tools.length ? `${c.tools.length} tool${c.tools.length === 1 ? '' : 's'}` : 'No tools');
        if (Array.isArray(c.answer_fields) && c.answer_fields.length) parts.push(`Answers ${c.answer_fields.map((f) => f && f.name).filter(Boolean).join(', ')}`);
        return parts.join(' · ');
      }
      default: return '';
    }
  }

  function nodeItem(n) {
    const id = String(n.id);
    const kind = String(n.kind || 'llm');
    const config = n.config && typeof n.config === 'object' ? n.config : {};
    const detail = detailOf(kind, config);
    let outcome = { tone: 'none', word: '' };
    if (isRun) {
      const rec = recordOf(id);
      const items = itemRecordsOf(id);
      const waitingItem = items.find((r) => r.status === 'waiting');
      if (rec && rec.status === 'waiting') {
        // `P22-11`, `P22-17`. A step that is waiting says what for.
        outcome = { tone: runStatusTone('waiting') || 'pending', word: waitingWords(rec.waiting) };
      } else if (waitingItem) {
        outcome = { tone: runStatusTone('waiting') || 'pending',
          word: `Item ${Number(waitingItem.item) + 1}: ${waitingWords(waitingItem.waiting).toLowerCase()}` };
      } else if (rec) {
        outcome = { tone: runStatusTone(rec.status) || 'info', word: runStatusLabel(rec.status, 'job') };
      } else if (items.length) {
        const last = items[items.length - 1];
        outcome = { tone: runStatusTone(last.status) || 'info', word: `Item ${Number(last.item) + 1}: ${runStatusLabel(last.status, 'job')}` };
      } else {
        outcome = { tone: 'none', word: NOT_REACHED };
      }
    }
    const ports = portsOfNode(n, S.palette);
    // `P22-19`, `P22-24`. Not checked yet: its words first, then any pin.
    const mark = markOf(id);
    const marks = [];
    if (mark) marks.push(MARK_WORDS[mark.origin]);
    if (!isRun && !S.viewing && n.pinned) marks.push(PINNED_MARK);
    const item = {
      id, name: String(n.label || KIND_WORDS[kind] || kind), kind,
      sub: [KIND_WORDS[kind] || kind, detail].filter(Boolean).join(' · '),
      paused: false, outcome, ports, portWords: portWordsOf(n, ports),
      marks,
      accepts: !readOnly(), missing: false,
    };
    if (mark) item.unchecked = mark.origin;
    return item;
  }

  /** `P22-11`. The document's own start arrows (`from: "start"`). */
  const startEdgesOf = (g) => edgesOf(g).filter((e) => String(e.from) === START_KEY);

  async function load() {
    await ready;
    if (S.loadError) throw S.loadError;
    const g = shown();
    const items = [startItem(), ...nodesOf(g).map(nodeItem)];
    const edges = edgesOf(g).map((e) => ({
      from: String(e.from) === START_KEY ? START_ID : String(e.from), to: String(e.to), when: String(e.port || ''),
    }));
    // A document with no start arrows of its own starts at the one step
    // nothing leads to (Slice B, `Law 1`): drawn as a fixed arrow, the way it
    // always was.
    const first = startEdgesOf(g).length ? null : entryOf(g);
    if (first) {
      edges.unshift({ from: START_ID, to: String(first.id), when: PORTS[0], label: STARTS_LABEL, fixed: true });
    }
    return { items, edges };
  }

  // ── asking the server about a draft ─────────────────────────────────────

  /** `PUT ?check=true`: what a Save of this draft would answer. Nothing is
   *  written. The last few answers are kept by content, because a refused
   *  arrow asks about the draft without it as well. */
  async function check(graph) {
    const name = S.draft ? S.draft.name : '';
    const key = contentOf(name, graph) + '@' + S.base;
    const known = S.checks.find((c) => c.key === key);
    if (known) return known.result;
    let result;
    try {
      await api.checkWorkflow(workflowId, { name, graph, baseVersion: S.base });
      result = { ok: true };
    } catch (err) {
      result = { ok: false, refusal: refusalOf(err) };
    }
    if (result.ok || result.refusal.status) {
      S.checks = [{ key, result }, ...S.checks].slice(0, 4);
    }
    return result;
  }

  // `P22-09`: a refusal may name the field it is about (`field`, C-W), so the
  // step's panel can put the sentence on that field.
  const problemOf = (r) => ({ sentence: r.sentence, reason: r.reason || null, nodeIds: r.nodeIds || [],
    field: r.field || null });

  /** After an edit nothing can refuse (a step added or removed, an arrow
   *  taken away, a step changed): say what the draft still lacks, if
   *  anything. The edit stands either way. */
  async function recheck() {
    if (readOnly() || !S.draft) return;
    const gen = S.gen;
    const res = await check(S.draft.graph);
    if (gen !== S.gen) return;
    if (res.ok) S.problem = null;
    else if (res.refusal.status === 409) S.stale = true;
    else if (res.refusal.status) S.problem = problemOf(res.refusal);
    emit();
  }

  /** An edit that the server may refuse because of itself: an arrow. */
  async function tryEdit(after) {
    const before = S.draft.graph;
    const res = await check(after);
    if (res.ok) {
      S.draft.graph = after;
      S.problem = null;
      edited();
      return { ok: true };
    }
    const r = res.refusal;
    if (r.status === 409) {
      S.stale = true;
      emit();
      return { ok: false, status: 409, sentence: r.sentence };
    }
    if (r.status === 400 || r.status === 403) {
      // Is it this arrow, or the draft it was drawn on? The same refusal
      // without it means the draft is not finished yet, and the arrow is fine.
      const prior = await check(before);
      const same = !prior.ok && prior.refusal.status === r.status
        && ((r.reason && prior.refusal.reason === r.reason) || prior.refusal.sentence === r.sentence);
      if (same) {
        S.draft.graph = after;
        S.problem = problemOf(r);
        edited();
        return { ok: true, sentence: r.sentence };
      }
    }
    return { ok: false, status: r.status, sentence: r.sentence, reason: r.reason, nodeIds: r.nodeIds, field: r.field || null };
  }

  async function connect(from, when, to) {
    await ready;
    if (readOnly()) return { ok: false, sentence: READ_ONLY };
    const a = String(from);
    const b = String(to);
    const port = String(when);
    if (b === START_ID) return { ok: false, sentence: START_FIXED };
    if (!draftNode(b)) return { ok: false, sentence: 'That step is not in this workflow.' };
    const g = clone(S.draft.graph);
    if (a === START_ID) {
      // `P22-11`. An arrow from the start is real. A document that had none
      // started at its one entry; that arrow is written out beside the new
      // one, so the step that ran first still runs.
      if (port !== 'success') return { ok: false, sentence: 'The start has one way out: it starts.' };
      const own = startEdgesOf(g);
      if (own.some((e) => String(e.to) === b)) return { ok: false, sentence: `“${draftNode(b).label || b}” already runs when it starts.` };
      if (!own.length) {
        const first = entryOf(g);
        if (first && String(first.id) !== b) g.edges = [...edgesOf(g), { from: START_KEY, port: 'success', to: String(first.id) }];
      }
      g.edges = [...edgesOf(g), { from: START_KEY, port: 'success', to: b }];
      return tryEdit(g);
    }
    const n = draftNode(a);
    if (!n) return { ok: false, sentence: 'That step is not in this workflow.' };
    const ports = portsOfNode(n, S.palette);
    if (!ports.includes(port)) {
      return { ok: false, sentence: `“${n.label || a}” has no “${PORT_WORDS[port] || port}” way out.` };
    }
    // `P22-11`. Fan-out: several arrows may leave one port, and drawing one
    // adds it; only the very same arrow twice is refused.
    if (edgesOf(g).some((e) => String(e.from) === a && String(e.port) === port && String(e.to) === b)) {
      return { ok: false, sentence: 'That arrow is already there.' };
    }
    g.edges = [...edgesOf(g), { from: a, port, to: b }];
    return tryEdit(g);
  }

  async function disconnect(from, when, to) {
    await ready;
    if (readOnly()) return { ok: false, sentence: READ_ONLY };
    const g = clone(S.draft.graph);
    // `P22-11`. A start arrow of the document's own can be taken away; the
    // implied one (a document with none) cannot.
    const a = String(from) === START_ID ? START_KEY : String(from);
    if (a === START_KEY && !startEdgesOf(g).length) return { ok: false, sentence: START_FIXED };
    const kept = edgesOf(g).filter((e) => !(String(e.from) === a && String(e.port) === String(when)
      && (to == null || String(e.to) === String(to))));
    if (kept.length === edgesOf(g).length) return { ok: false, sentence: 'There is no such arrow.' };
    g.edges = kept;
    S.draft.graph = g;
    edited();
    await recheck();
    return { ok: true };
  }

  async function loadPositions() {
    await ready;
    const out = new Map();
    if (S.loadError) return out;
    const g = shown();
    for (const n of nodesOf(g)) {
      const p = point(n.position);
      if (p) out.set(String(n.id), { x: p[0], y: p[1] });
    }
    const s = point(g[START_KEY] && g[START_KEY].position);
    if (s) out.set(START_ID, { x: s[0], y: s[1] });
    return out;
  }

  /** Where every step sits, as the canvas has them now: a step it has no
   *  place for is laid out again (that is *Tidy up*). Kept in the draft for
   *  steps only it has, and written at once for the steps the saved document
   *  has — never a version. A record or an old version is drawn where it was
   *  and nothing is written. */
  async function savePositions(map) {
    await ready;
    if (readOnly() || !S.doc || !S.draft) return { ok: true };
    const points = new Map();
    const entries = map instanceof Map ? map.entries() : Object.entries(map || {});
    for (const [id, p] of entries) {
      const xy = point(p);
      if (xy) points.set(String(id), xy);
    }
    const placeIn = (g) => {
      for (const n of nodesOf(g)) n.position = points.get(String(n.id)) || null;
      if (g && typeof g === 'object') g[START_KEY] = { ...(g[START_KEY] || {}), position: points.get(START_ID) || null };
    };
    placeIn(S.draft.graph);
    const body = {};
    for (const n of nodesOf(S.doc.graph)) {
      const p = points.get(String(n.id)) || null;
      if (!samePoint(n.position, p)) body[String(n.id)] = p;
    }
    const startNow = points.get(START_ID) || null;
    if (!samePoint(S.doc.graph && S.doc.graph[START_KEY] && S.doc.graph[START_KEY].position, startNow)) {
      body[START_KEY] = startNow;
    }
    if (!Object.keys(body).length) return { ok: true };
    try {
      await api.savePositions(workflowId, body);
      placeIn(S.doc.graph);
      return { ok: true };
    } catch (err) {
      return answer(err);
    }
  }

  function message(host, words) {
    host.textContent = words;
    return { destroy() { host.textContent = ''; } };
  }

  function openPanel(host, item, { onSaved, onCancel } = {}) {
    const id = item && item.id != null ? String(item.id) : null;
    const saved = (out) => { if (typeof onSaved === 'function') onSaved(out); };
    if (id === START_ID) {
      if (isRun) {
        return message(host, `Started: ${startItem().outcome.word}. What starts it is changed in the workflow, not in a run.`);
      }
      if (typeof panels.start !== 'function') return message(host, 'The start’s settings did not load.');
      return panels.start(host, {
        triggerTask: trigger(),
        tasks: S.tasks,
        onSaved: (task) => {
          if (task && S.doc) {
            S.doc.trigger_task = task;
            if (task.status) S.doc.trigger_status = task.status;
          }
          emit();
          saved({ id: START_ID, name: 'Starts', sentence: 'Saved when it starts. That is the start’s own setting, so it is saved already.' });
        },
        onCancel,
      });
    }
    if (isRun) {
      if (typeof panels.record !== 'function') return message(host, 'The step’s record did not load.');
      // The panel reads `run.cleared` (wf-ui's `record`): whether a run with
      // no record for this step had its records cleared, or never reached it.
      // That is the run reply's, not the run row's, so it is handed on with
      // the server's sentence (wave C merge: the row was handed alone, so a
      // cleared run's every step said "not reached" — `Law 10`).
      const run = S.run ? { ...(S.run.run || {}), cleared: S.run.cleared === true,
        cleared_sentence: S.run.cleared_sentence || null } : null;
      // `P22-12`: a For-each's items; `P22-17`: a waiting step's question,
      // answered from here as from the notification.
      // `P22-20`. A failed step can be explained (C-A's explain route) — of
      // the step as the CURRENT document has it (`current`), which is what a
      // proposed change would change; `palette` names its Integration.
      const canExplain = !!api && typeof api.explainStep === 'function';
      return panels.record(host, {
        node: clone(shownNode(id)), record: clone(recordOf(id)), run,
        items: clone(itemRecordsOf(id)), answer: (args) => answerStep(args),
        explain: canExplain ? (args) => explainStep(args) : null,
        current: clone(savedNode(id)), palette: S.palette,
      });
    }
    if (S.viewing) {
      return message(host, `This is how the step was in version ${S.viewing.version}. Restore that version to change it.`);
    }
    const node = draftNode(id);
    if (!node) return message(host, 'That step is not in this workflow.');
    if (typeof panels.node !== 'function') return message(host, 'The step editor did not load.');
    const problem = S.problem && (S.problem.nodeIds || []).map(String).includes(id) ? { ...S.problem } : null;
    // `P22-19`, `P22-24`. A step nobody has checked yet: its panel opens on
    // what it is, what it needs, what it would do, and *Looks right*.
    const mark = markOf(id);
    const check = mark ? {
      origin: mark.origin, needs: mark.needs,
      plan: () => planLines().then((p) => (p.ok ? { ok: true, lines: p.plans.get(id) || null } : p)),
      looksRight: () => checkSteps([id]),
    } : null;
    return panels.node(host, {
      node: clone(node),
      tasks: S.tasks,
      workflow: S.doc,
      source: self,
      // `P22-09`…`P22-18`, C-W. What the step panels offer and may refer to.
      palette: S.palette,
      upstream: upstreamOf(id),
      saved: !!savedNode(id),
      fields: () => listFields(id),
      problem,
      check,
      onApply: async (change) => {
        let n = draftNode(id);
        if (!n || !change) return;
        if (change.label != null) n.label = String(change.label);
        if (change.config && typeof change.config === 'object') n.config = clone(change.config);
        // `P22-09`. A step added in this draft takes its id from the label it
        // is first given, and keeps it after (`fresh` is spent here).
        let nowId = id;
        if (S.fresh.has(id)) {
          S.fresh.delete(id);
          nowId = renameFresh(id, n.label);
          n = draftNode(nowId) || n;
        }
        edited();
        await recheck();
        // `P22-09`. When the server says this step cannot be saved as it is
        // (a field from another step in a command, say), it is said now —
        // and again on the field when the step is opened or Save is pressed.
        const p = S.problem && (S.problem.nodeIds || []).map(String).includes(nowId) ? S.problem : null;
        saved({ id: nowId, was: nowId !== id ? id : null, name: n.label,
          sentence: p ? `Changed “${n.label}”, but it cannot be saved like this: ${p.sentence}`
            : `Changed “${n.label}”. Save the workflow to keep it.` });
      },
      onCancel,
    });
  }

  /** `P22-09`. Step `id`, added in this draft, re-keyed by its first label —
   *  unless nothing would change, the label's slug is taken, or another step
   *  already names it in a reference. Answers the id it has now. */
  function renameFresh(id, label) {
    const g = S.draft.graph;
    const taken = new Set(nodesOf(g).map((n) => String(n.id)).filter((x) => x !== String(id)));
    const next = freeId(label, taken);
    if (next === String(id)) return id;
    const named = new RegExp('steps\\.' + String(id).replace(/[-]/g, '\\-') + '\\.');
    if (nodesOf(g).some((n) => String(n.id) !== String(id) && named.test(JSON.stringify(n.config || {})))) return id;
    for (const n of nodesOf(g)) if (String(n.id) === String(id)) n.id = next;
    for (const e of edgesOf(g)) {
      if (String(e.from) === String(id)) e.from = next;
      if (String(e.to) === String(id)) e.to = next;
    }
    return next;
  }

  /** `P22-09`. The fields a reference in step `id` may name (C-W's
   *  fields route, `api.listFields`), as the panel's
   *  picker lists them. A step the server has not seen yet (added in this
   *  draft) has none to list until the workflow is saved. */
  async function listFields(id) {
    await ready;
    if (!api || typeof api.listFields !== 'function') {
      return { ok: false, sentence: 'This Pantheon cannot list the fields other steps made.' };
    }
    if (!savedNode(id)) {
      return { ok: false, sentence: 'Save the workflow first: the fields other steps made are listed for a saved step.' };
    }
    try {
      const out = await api.listFields(workflowId, String(id));
      return { ok: true, sources: Array.isArray(out && out.sources) ? out.sources : [] };
    } catch (err) {
      return answer(err);
    }
  }

  async function newItem(anchor) {
    await ready;
    if (readOnly() || !S.draft || typeof panels.palette !== 'function') return null;
    const kind = await panels.palette(anchor, { palette: S.palette, paletteError: S.paletteError });
    if (!kind) return null;
    const nodes = nodesOf(S.draft.graph);
    const word = KIND_WORDS[kind] || String(kind);
    const labels = new Set(nodes.map((n) => String(n.label || '')));
    let label = word;
    for (let i = 2; labels.has(label); i += 1) label = `${word} ${i}`;
    // `P22-09`. The id is the label's slug — `http-request` until the step
    // is first named, then that name's (`renameFresh`), and kept after.
    const id = freeId(label, new Set(nodes.map((n) => String(n.id))));
    S.fresh.add(id);
    S.draft.graph = { ...S.draft.graph, nodes: [...nodes, { id, kind: String(kind), label, config: {}, position: null, pinned: null }] };
    edited();
    await recheck();
    return id;
  }

  async function removeItem(id) {
    await ready;
    if (readOnly()) return { ok: false, sentence: READ_ONLY };
    if (String(id) === START_ID) return { ok: false, sentence: 'The start cannot be removed: it is what runs the workflow.' };
    if (!draftNode(id)) return { ok: false, sentence: 'That step is not in this workflow.' };
    const g = clone(S.draft.graph);
    g.nodes = nodesOf(g).filter((n) => String(n.id) !== String(id));
    g.edges = edgesOf(g).filter((e) => String(e.from) !== String(id) && String(e.to) !== String(id));
    S.draft.graph = g;
    edited();
    await recheck();
    return { ok: true, sentence: 'Save the workflow to keep the change.' };
  }

  /** *Show me what this would do*, for the whole document: the server's dry
   *  run of the SAVED workflow (`POST /api/tasks/{start}/run?dry=true`), one
   *  plan per step in the reply's `nodes`. */
  async function dryRun() {
    await ready;
    if (isRun) return { ok: false, sentence: 'A record of a run cannot be planned again.' };
    if (!S.doc) return { ok: false, sentence: S.loadError ? S.loadError.sentence : 'This workflow has not loaded.' };
    let reply;
    try {
      reply = await api.runWorkflow(S.doc.task_id, { dry: true });
    } catch (err) {
      return answer(err);
    }
    const plans = new Map();
    const t = trigger();
    plans.set(START_ID, {
      steps: [{ kind: 'dry-run', detail: `Would start: ${describe(t) || 'when its start says'}.` }],
      declined: null, when: null, depth: 0,
    });
    const listed = Array.isArray(reply && reply.nodes) ? reply.nodes : null;
    for (const e of listed || []) {
      if (!e || e.node_id == null) continue;
      plans.set(String(e.node_id), {
        steps: Array.isArray(e.steps) ? e.steps : [], declined: e.declined || null,
        when: e.when || null, depth: Number(e.depth) || 0,
      });
    }
    return {
      ok: true, plans, head: START_ID, partial: !listed, run: reply ? reply.run : null,
      sentence: dirty() ? 'This is the plan for the workflow as saved: your unsaved changes are not in it.' : '',
    };
  }

  // ── the rest of the room's verbs ─────────────────────────────────────────

  function rename(name) {
    if (readOnly() || !S.draft) return { ok: false, sentence: READ_ONLY };
    S.draft.name = String(name == null ? '' : name);
    edited();
    return { ok: true };
  }

  async function save() {
    await ready;
    if (readOnly() || !S.draft) return { ok: false, sentence: READ_ONLY };
    const gen = S.gen;
    const sent = clone(S.draft);
    S.busy = true;
    emit();
    try {
      const out = await api.saveWorkflow(workflowId, { name: sent.name, graph: sent.graph, baseVersion: S.base });
      // An edit made while the save was on its way stays in the draft.
      takeDoc(out.workflow, { force: gen === S.gen });
      if (gen !== S.gen) S.base = out.workflow.version;
      S.problem = null;
      S.stale = false;
      S.checks = [];
      return {
        ok: true, saved: out.saved,
        sentence: out.saved === 'new_version'
          ? `Saved as version ${out.workflow.version}.`
          : 'Nothing to save: it is the same as the saved version.',
      };
    } catch (err) {
      const r = refusalOf(err);
      if (r.status === 409) S.stale = true;
      else if (r.status === 400 || r.status === 403) S.problem = problemOf(r);
      return { ...answer(r), stale: r.status === 409 };
    } finally {
      S.busy = false;
      emit();
    }
  }

  /** Throw the draft away and read the saved workflow again (it may have
   *  moved on, if this draft was stale). */
  async function discard() {
    await ready;
    if (isRun) return { ok: false, sentence: READ_ONLY };
    try {
      const wf = await api.getWorkflow(workflowId);
      takeDoc(wf && wf.workflow, { force: true });
    } catch (_) {
      takeDoc(S.doc, { force: true });
    }
    S.problem = null;
    S.stale = false;
    S.checks = [];
    edited();
    return { ok: true };
  }

  /** Pin a sample on a saved step, or with `null` unpin it (`P22-08`). It is
   *  never a version and never a change to the draft's content. */
  async function setPin(id, data) {
    await ready;
    if (readOnly()) return { ok: false, sentence: READ_ONLY };
    if (!savedNode(id)) return { ok: false, sentence: 'Save the workflow first, then pin a sample on this step.' };
    try {
      const out = await api.savePins(workflowId, { [String(id)]: data == null ? null : data });
      const pinned = (nodesOf(out.workflow && out.workflow.graph).find((n) => String(n.id) === String(id)) || {}).pinned || null;
      const keepDraft = dirty();
      takeDoc(out.workflow);
      if (keepDraft) {
        const n = draftNode(id);
        if (n) n.pinned = clone(pinned);
      }
      emit();
      return { ok: true, pinned, dropped: (out.dropped && out.dropped[String(id)]) || [] };
    } catch (err) {
      return answer(err);
    }
  }

  /** *Test this step* (`P22-08`), on the step as it stands in the draft —
   *  its unsaved settings are what is tested. */
  async function test(id, { source = 'none', input, confirm = false } = {}) {
    await ready;
    if (isRun || S.viewing) return { ok: false, sentence: READ_ONLY };
    const node = draftNode(id);
    if (!node) return { ok: false, sentence: 'That step is not in this workflow.' };
    try {
      const out = await api.testNode(workflowId, String(id), { node: clone(node), source, input, confirm });
      return { ok: true, ...out };
    } catch (err) {
      return answer(err);
    }
  }

  async function runNow() {
    await ready;
    if (!S.doc) return { ok: false, sentence: 'This workflow has not loaded.' };
    try {
      await api.runWorkflow(S.doc.task_id);
    } catch (err) {
      return answer(err);
    }
    return {
      ok: true,
      sentence: dirty() ? 'Started the workflow as saved. Your unsaved changes are not in this run.'
        : 'Started. It is under Runs.',
    };
  }

  async function switchOn(on) {
    await ready;
    if (isRun || !S.doc) return { ok: false, sentence: READ_ONLY };
    try {
      const out = await api.switchWorkflow(workflowId, !!on);
      takeDoc(out.workflow);
      emit();
      return { ok: true, notes: out.notes || [], chainPaused: out.chain_paused || null, sentence: (out.notes || []).join(' ') };
    } catch (err) {
      return answer(err);
    }
  }

  async function restoreChain() {
    await ready;
    if (isRun || !S.doc) return { ok: false, sentence: READ_ONLY };
    try {
      const out = await api.restoreChain(workflowId);
      takeDoc(out.workflow);
      emit();
      return { ok: true, notes: out.notes || [], chainResumed: out.chain_resumed || null, sentence: (out.notes || []).join(' ') };
    } catch (err) {
      return answer(err);
    }
  }

  async function versions() {
    await ready;
    try {
      const out = await api.listVersions(workflowId);
      return { ok: true, versions: Array.isArray(out && out.versions) ? out.versions : [] };
    } catch (err) {
      return answer(err);
    }
  }

  /** Look at a kept version on the canvas, read-only; `null` goes back to
   *  the draft. */
  async function showVersion(version) {
    await ready;
    if (isRun) return { ok: false, sentence: READ_ONLY };
    if (version == null) {
      S.viewing = null;
      emit();
      return { ok: true };
    }
    try {
      const out = await api.getVersion(workflowId, version);
      S.viewing = { version: out.version, name: out.name, graph: out.graph || {}, saved_at: out.saved_at,
        source: out.source, current: !!out.current };
      emit();
      return { ok: true, version: state().viewing };
    } catch (err) {
      return answer(err);
    }
  }

  /** Put a kept version back, as a new version; nothing is lost. Refused
   *  while the draft has changes, which the restore would replace. */
  async function restoreVersion(version) {
    await ready;
    if (isRun) return { ok: false, sentence: READ_ONLY };
    if (dirty()) {
      return { ok: false, sentence: 'You have changes that are not saved. Save them or throw them away first, then restore.' };
    }
    try {
      const out = await api.restoreVersion(workflowId, version, S.base);
      takeDoc(out.workflow, { force: true });
      S.viewing = null;
      S.checks = [];
      emit();
      return {
        ok: true, saved: out.saved,
        sentence: out.saved === 'unchanged'
          ? `Version ${version} is what is saved already.`
          : `Restored version ${version} as version ${out.workflow.version}. Every earlier version is still kept.`,
      };
    } catch (err) {
      const r = refusalOf(err);
      if (r.status === 409) { S.stale = true; emit(); }
      return answer(r);
    }
  }

  /** `P22-17`. Answer the question a waiting step asks (C-W's
   *  answer route, `api.answerStep`): `approve_task` — Allow
   *  once, the only yes a workflow has (no chat to remember it in) — or
   *  `deny`. The run is read again after, so the canvas says what happened. */
  async function answerStep({ nodeId, item = null, approvalId, decision } = {}) {
    await ready;
    if (!isRun) return { ok: false, sentence: 'Only a run that is waiting can be answered.' };
    if (decision !== 'approve_task' && decision !== 'deny') {
      return { ok: false, sentence: 'A step is answered with Allow once or Deny.' };
    }
    if (!api || typeof api.answerStep !== 'function') {
      return { ok: false, sentence: 'This Pantheon cannot answer a waiting step.' };
    }
    let out;
    try {
      out = await api.answerStep(workflowId, runId, { nodeId, item, approvalId, decision });
    } catch (err) {
      return answer(err);
    }
    try { S.run = await api.getExecution(workflowId, runId); } catch (_) { /* drawn from what was */ }
    emit();
    return { ok: !!(out && out.ok !== false), outcome: out ? out.outcome : null,
      sentence: out && out.sentence ? String(out.sentence) : '' };
  }

  // ── Slice E (`P22-19`, `P22-20`, `P22-24`; C-A) ─────────────────────────

  /** `P22-19`. *Looks right* on steps `ids` (C-A: `PUT {checked}`, a person
   *  only — the server answers 403 to a token or the assistant). It writes
   *  no version, so the draft and its base stay as they are; the saved
   *  document comes back without those marks. */
  async function checkSteps(ids) {
    await ready;
    if (isRun || !S.doc) return { ok: false, sentence: READ_ONLY };
    if (!api || typeof api.checkSteps !== 'function') {
      return { ok: false, sentence: 'This Pantheon cannot take a step’s check yet.' };
    }
    const list = (Array.isArray(ids) ? ids : []).map(String).filter(Boolean);
    if (!list.length) return { ok: false, sentence: 'There is no step to check.' };
    try {
      const out = await api.checkSteps(workflowId, list);
      if (out && out.workflow) takeDoc(out.workflow);
      emit();
      return { ok: true, checked: list, saved: out ? out.saved || null : null };
    } catch (err) {
      return answer(err);
    }
  }

  /** `P22-19`. What each step of the SAVED version would do: the dry run's
   *  plan (`POST /api/tasks/{start}/run?dry=true`, `nodes[].steps`), one
   *  planner (`plan_lines`) and the existing door — nothing runs, and the
   *  dry run plans a step nobody has checked (design § 1.1). Asked once per
   *  saved version; a refusal is not kept. → `{ ok, plans: Map<id, [line]> }` */
  function planLines() {
    if (isRun || !S.doc) return Promise.resolve({ ok: false, sentence: READ_ONLY });
    const version = S.doc.version;
    if (S.plans && S.plans.version === version) return S.plans.promise;
    const promise = (async () => {
      try {
        const reply = await api.runWorkflow(S.doc.task_id, { dry: true });
        const plans = new Map();
        for (const e of (Array.isArray(reply && reply.nodes) ? reply.nodes : [])) {
          if (!e || e.node_id == null) continue;
          const lines = (Array.isArray(e.steps) ? e.steps : [])
            .map((s) => String((s && typeof s === 'object' ? s.detail : s) || '').trim()).filter(Boolean);
          plans.set(String(e.node_id), e.declined ? [`Would not run: ${e.declined}`, ...lines] : lines);
        }
        return { ok: true, plans };
      } catch (err) {
        return answer(err);
      }
    })();
    S.plans = { version, promise };
    promise.then((r) => { if (!r.ok && S.plans && S.plans.promise === promise) S.plans = null; });
    return promise;
  }

  /** `P22-20`. Apply a proposed change to step `nodeId` (C-A's fix route, a
   *  person only): the server asks the fix rule again against the stored
   *  step and writes a new version (source `fixed`); `undoVersion` is the one
   *  it was made on, which `restoreVersion` puts back. Refused here while the
   *  draft has changes the new version would leave stale. */
  async function fix(nodeId, { config, baseVersion } = {}) {
    await ready;
    if (isRun || !S.doc) return { ok: false, sentence: READ_ONLY };
    if (!api || typeof api.fixStep !== 'function') {
      return { ok: false, sentence: 'This Pantheon cannot apply a fix yet.' };
    }
    if (dirty()) {
      return { ok: false, sentence: 'This workflow has changes that are not saved. Save them or throw them away '
        + 'first (in Edit), then apply the fix.' };
    }
    try {
      const out = await api.fixStep(workflowId, String(nodeId), { config, baseVersion });
      takeDoc(out && out.workflow, { force: true });
      S.viewing = null;
      S.checks = [];
      S.problem = null;
      S.stale = false;
      emit();
      return { ok: true, saved: out ? out.saved || null : null,
        version: out && out.workflow ? out.workflow.version : null,
        undoVersion: out && out.undo_version != null ? out.undo_version : null };
    } catch (err) {
      const r = refusalOf(err);
      if (r.status === 409) { S.stale = true; emit(); }
      return answer(r);
    }
  }

  /** `P22-24`. The saved workflow as a file (C-A's export route, an
   *  attachment): `{ ok, blob, filename, unsaved }`. */
  async function exportFile() {
    await ready;
    if (!S.doc) return { ok: false, sentence: S.loadError ? S.loadError.sentence : 'This workflow has not loaded.' };
    if (!api || typeof api.exportWorkflow !== 'function') {
      return { ok: false, sentence: 'This Pantheon cannot export a workflow yet.' };
    }
    try {
      const out = await api.exportWorkflow(workflowId);
      const blob = out && typeof out === 'object' && 'blob' in out ? out.blob : out;
      const filename = (out && typeof out === 'object' && typeof out.filename === 'string' && out.filename)
        || `${slugOf(S.doc.name || 'workflow')}.workflow.json`;
      return { ok: true, blob, filename, unsaved: dirty() };
    } catch (err) {
      return answer(err);
    }
  }

  /** `P22-20`. Ask a model why step `nodeId` (item `item`) failed in this
   *  run (C-A's explain route). Nothing is written. → `{ ok, why, model,
   *  changed_since_run, proposal, left_out }` */
  async function explainStep({ nodeId, item = null } = {}) {
    await ready;
    if (!isRun) return { ok: false, sentence: 'Only a step of a run can be explained.' };
    if (!api || typeof api.explainStep !== 'function') {
      return { ok: false, sentence: 'This Pantheon cannot explain a step yet.' };
    }
    try {
      const out = await api.explainStep(workflowId, runId,
        { nodeId: String(nodeId), item: item == null ? null : Number(item) });
      return { ok: true, ...(out && typeof out === 'object' ? out : {}) };
    } catch (err) {
      return answer(err);
    }
  }

  const self = {
    get readOnly() { return readOnly(); },
    /** `P22-11`. Several arrows may leave one port of a document's step. */
    get fanOut() { return !isRun; },
    get words() {
      if (!isRun) return EDIT_WORDS;
      if (!(S.run && S.run.cleared)) return RUN_WORDS;
      // The server's sentence names the window as it is set (`cleared_sentence`,
      // the engine's `records_cleared_sentence`); CLEARED only if it said none.
      const said = typeof S.run.cleared_sentence === 'string' && S.run.cleared_sentence
        ? `${S.run.cleared_sentence} The run’s own summary is still in the list.` : CLEARED;
      return { ...RUN_WORDS, emptyText: said };
    },
    ready,
    load, connect, disconnect, loadPositions, savePositions, openPanel, newItem, removeItem, dryRun,
    state, refresh, rename, save, discard, setPin, test, runNow, switchOn, restoreChain,
    versions, showVersion, restoreVersion, answer: answerStep, listFields, upstreamOf,
    // Slice E (C-A).
    marked, checkSteps, planLines, fix, exportFile, explain: explainStep,
  };
  if (isRun) {
    // A run cannot be added to or taken from: the optional verbs are absent,
    // so the canvas draws no New and no Delete (`readOnly` says the rest).
    delete self.newItem;
    delete self.removeItem;
  }
  return self;
}

export default {
  createWorkflowSource, contentOf, START_ID, EDIT_WORDS, RUN_WORDS, slugOf, portsOfNode, portWordsOf,
  KIND_PORTS, CASE_PREFIX, MARK_WORDS, markOrigin, needsOf,
};
