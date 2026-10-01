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

import { EDGE_WORDS, KIND_WORDS } from '../tasks/workflowDiagram.js';
import { runStatusTone, runStatusLabel } from '../runStatus.js';
import { PORTS } from './graphLayout.js';
import { WorkflowRefusal } from './workflowApi.js';

/** The start's item id on the canvas. Never a step's id: steps are `n<k>`. */
export const START_ID = '__start__';
/** The document's own key for the start (`graph.start`, the positions map) —
 *  `START_KEY` in `src/workflow_document.py`. */
const START_KEY = 'start';

/** What the canvas says while a document is being edited. */
export const EDIT_WORDS = Object.freeze({
  region: 'Steps of this workflow',
  emptyTitle: 'No steps yet.',
  emptyText: 'Add a step, and the start leads to it. A step is a prompt, a research run, an action or another task.',
  hint: 'Drag from a step’s “' + EDGE_WORDS.success + '” or “' + EDGE_WORDS.error
    + '” onto the step that should run next, or use its Connect… button. Click a step to change it. '
    + 'Your changes stay here until you press Save.',
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

const STARTS_LABEL = 'starts';
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
  return { ok: false, status: r.status, sentence: r.sentence, reason: r.reason, nodeIds: r.nodeIds };
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

  /** The newest record of a step in the run being drawn. */
  function recordOf(id) {
    const recs = (S.run && Array.isArray(S.run.nodes) ? S.run.nodes : [])
      .filter((r) => String(r.node_id) === String(id));
    return recs.length ? recs[recs.length - 1] : null;
  }

  /** The step a failed run ended on: the last record, when it failed. */
  function failedStep() {
    if (!isRun || !S.run || !S.run.run || S.run.run.status !== 'error') return null;
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
      loadError: S.loadError ? S.loadError.sentence : null,
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
    } catch (err) {
      S.loadError = refusalOf(err);
    }
    emit();
    return state();
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
    return {
      id: START_ID, name: 'Starts', kind: 'start',
      sub: describe(t) || (t ? '' : 'Its start could not be read'),
      paused: !isRun && !isOn(), outcome, ports: [], marks: [], accepts: false, missing: false,
      fixed: true,
    };
  }

  function nodeItem(n) {
    const id = String(n.id);
    const kind = String(n.kind || 'llm');
    const config = n.config && typeof n.config === 'object' ? n.config : {};
    let detail = '';
    if (kind === 'action' && config.action) detail = String(config.action);
    if (kind === 'run_task') {
      const target = taskById(config.task_id);
      detail = target ? `Runs “${target.name || 'Untitled task'}”`
        : (config.task_id ? 'Runs a task that is not in your list' : 'Choose the task it runs');
    }
    let outcome = { tone: 'none', word: '' };
    if (isRun) {
      const rec = recordOf(id);
      outcome = rec
        ? { tone: runStatusTone(rec.status) || 'info', word: runStatusLabel(rec.status, 'job') }
        : { tone: 'none', word: NOT_REACHED };
    }
    return {
      id, name: String(n.label || KIND_WORDS[kind] || kind), kind,
      sub: [KIND_WORDS[kind] || kind, detail].filter(Boolean).join(' · '),
      paused: false, outcome, ports: PORTS.slice(),
      marks: !isRun && !S.viewing && n.pinned ? [PINNED_MARK] : [],
      accepts: !readOnly(), missing: false,
    };
  }

  async function load() {
    await ready;
    if (S.loadError) throw S.loadError;
    const g = shown();
    const items = [startItem(), ...nodesOf(g).map(nodeItem)];
    const edges = edgesOf(g).map((e) => ({ from: String(e.from), to: String(e.to), when: String(e.port || '') }));
    const first = entryOf(g);
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

  const problemOf = (r) => ({ sentence: r.sentence, reason: r.reason || null, nodeIds: r.nodeIds || [] });

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
    return { ok: false, status: r.status, sentence: r.sentence, reason: r.reason, nodeIds: r.nodeIds };
  }

  async function connect(from, when, to) {
    await ready;
    if (readOnly()) return { ok: false, sentence: READ_ONLY };
    const a = String(from);
    const b = String(to);
    const port = String(when);
    if (a === START_ID || b === START_ID) return { ok: false, sentence: START_FIXED };
    if (!PORTS.includes(port)) return { ok: false, sentence: `A step has no “${port}” outcome.` };
    if (!draftNode(a) || !draftNode(b)) return { ok: false, sentence: 'That step is not in this workflow.' };
    const g = clone(S.draft.graph);
    // One arrow per outcome (design § 1.2): drawing from a port that already
    // has one moves it, as it does on the tasks canvas.
    g.edges = edgesOf(g).filter((e) => !(String(e.from) === a && String(e.port) === port));
    g.edges.push({ from: a, port, to: b });
    return tryEdit(g);
  }

  async function disconnect(from, when, to) {
    await ready;
    if (readOnly()) return { ok: false, sentence: READ_ONLY };
    if (String(from) === START_ID) return { ok: false, sentence: START_FIXED };
    const g = clone(S.draft.graph);
    const kept = edgesOf(g).filter((e) => !(String(e.from) === String(from) && String(e.port) === String(when)
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
      return panels.record(host, { node: clone(shownNode(id)), record: clone(recordOf(id)), run: S.run ? S.run.run : null });
    }
    if (S.viewing) {
      return message(host, `This is how the step was in version ${S.viewing.version}. Restore that version to change it.`);
    }
    const node = draftNode(id);
    if (!node) return message(host, 'That step is not in this workflow.');
    if (typeof panels.node !== 'function') return message(host, 'The step editor did not load.');
    return panels.node(host, {
      node: clone(node),
      tasks: S.tasks,
      workflow: S.doc,
      source: self,
      onApply: async (change) => {
        const n = draftNode(id);
        if (!n || !change) return;
        if (change.label != null) n.label = String(change.label);
        if (change.config && typeof change.config === 'object') n.config = clone(change.config);
        edited();
        await recheck();
        saved({ id, name: n.label, sentence: `Changed “${n.label}”. Save the workflow to keep it.` });
      },
      onCancel,
    });
  }

  async function newItem(anchor) {
    await ready;
    if (readOnly() || !S.draft || typeof panels.palette !== 'function') return null;
    const kind = await panels.palette(anchor);
    if (!kind) return null;
    const nodes = nodesOf(S.draft.graph);
    const taken = new Set(nodes.map((n) => String(n.id)));
    let k = nodes.reduce((m, n) => Math.max(m, Number(/^n(\d+)$/.exec(String(n.id))?.[1] || 0)), 0) + 1;
    while (taken.has(`n${k}`)) k += 1;
    const id = `n${k}`;
    const word = KIND_WORDS[kind] || String(kind);
    const labels = new Set(nodes.map((n) => String(n.label || '')));
    let label = word;
    for (let i = 2; labels.has(label); i += 1) label = `${word} ${i}`;
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

  const self = {
    get readOnly() { return readOnly(); },
    get words() {
      if (!isRun) return EDIT_WORDS;
      return S.run && S.run.cleared ? { ...RUN_WORDS, emptyText: CLEARED } : RUN_WORDS;
    },
    ready,
    load, connect, disconnect, loadPositions, savePositions, openPanel, newItem, removeItem, dryRun,
    state, refresh, rename, save, discard, setPin, test, runNow, switchOn, restoreChain,
    versions, showVersion, restoreVersion,
  };
  if (isRun) {
    // A run cannot be added to or taken from: the optional verbs are absent,
    // so the canvas draws no New and no Delete (`readOnly` says the rest).
    delete self.newItem;
    delete self.removeItem;
  }
  return self;
}

export default { createWorkflowSource, contentOf, START_ID, EDIT_WORDS, RUN_WORDS };
