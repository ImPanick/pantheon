# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-05`…`P22-08` (wf-ui) — the workflow data layer, faked in the contract's shapes.

The Workbench's room and canvas (`wf-ui`) consume contract C3 of
`/work/notes/SLICE-B-DESIGN.md` § 7 — `workflowApi.js`, `workflowSource.js`
and the canvas source contract — which `wf-api` builds on its own branch at
the same time. Until the branches merge, the browser half is driven against
these fakes, written to exactly those shapes, so every place the fakes had to
choose a shape the contract leaves open is a seam listed in `wf-ui`'s handoff
note rather than a guess hidden in a test:

  * ``CANVAS_SOURCE_JS`` — a canvas source (`load`, `connect`, `disconnect`,
    `loadPositions`, `savePositions`, `openPanel`, `newItem`, `removeItem`,
    `dryRun`, `readOnly`, `words`) over an in-memory document: a start item
    with no ports and a fixed arrow, steps with ports and marks. Every call is
    recorded on ``S.calls``.
  * ``WORKFLOW_API_JS`` / ``WORKFLOW_SOURCE_JS`` — the two modules the room
    loads (`import('./workflowApi.js')`, `import('./workflowSource.js')`),
    written into a sandbox as files so the room's own loader is what reads
    them. The API answers the C2 shapes (Summary, Doc, NodeRecord) from an
    in-memory store and records every call on ``globalThis.__wf.calls``; the
    source keeps a draft, saves with ``base_version``, and hands the room's
    panels exactly the arguments C3 names.

Where C3 names a verb and not its answer, the fakes answer the way wf-api's
module was being written when this was (read on its branch, 2026-10-01, not
copied): a source's verbs answer `{ ok: false, sentence }` rather than throw,
`ready` settles with `state().loadError`, `state().viewing` is an object and
`state().failed` names a failed run's step. The room reads either way.

Nothing here is the product; nothing here is copied from wf-api's branch.
"""

CANVAS_SOURCE_JS = r"""
export function fakeSource(spec = {}) {
  const S = {
    calls: [],
    items: JSON.parse(JSON.stringify(spec.items || [])),
    edges: JSON.parse(JSON.stringify(spec.edges || [])),
    readOnly: !!spec.readOnly,
    positions: spec.positions || {},
    refuse: spec.refuse || null,
    throwOnConnect: spec.throwOnConnect || null,
    panel: null,
  };
  const src = {
    get readOnly() { return S.readOnly; },
    words: spec.words || {
      region: 'Steps of Morning brief', emptyTitle: 'No steps yet.',
      emptyText: 'Add a step with Add a step.', hint: 'Drag from a step to the next one.',
      newLabel: 'Add a step',
    },
    async load() {
      S.calls.push(['load']);
      return { items: JSON.parse(JSON.stringify(S.items)), edges: JSON.parse(JSON.stringify(S.edges)) };
    },
    async connect(from, when, to) {
      S.calls.push(['connect', from, when, to]);
      if (S.throwOnConnect) { const e = new Error(S.throwOnConnect); e.sentence = S.throwOnConnect; throw e; }
      if (S.refuse) return { ok: false, sentence: S.refuse };
      S.edges = S.edges.filter((e) => !(e.from === from && e.when === when));
      S.edges.push({ from, when, to });
      return { ok: true };
    },
    async disconnect(from, when, to) {
      S.calls.push(['disconnect', from, when, to]);
      S.edges = S.edges.filter((e) => !(e.from === from && e.when === when && e.to === to));
      return { ok: true };
    },
    async loadPositions() { S.calls.push(['loadPositions']); return S.positions; },
    async savePositions(map) {
      S.calls.push(['savePositions', map instanceof Map ? [...map.entries()] : map]);
      return { ok: true };
    },
    openPanel(host, item, cb) {
      S.calls.push(['openPanel', item ? item.id : null]);
      S.panel = { host, item, cb, destroyed: false };
      const rec = S.panel;
      const field = host.appendChild(document.createElement('input'));
      field.className = 'fake-field';
      return { destroy() { rec.destroyed = true; } };
    },
  };
  if (spec.newItem !== false) {
    src.newItem = async (anchor) => {
      S.calls.push(['newItem', anchor ? anchor.className : null]);
      const id = 'n9';
      S.items.push({ id, name: 'Research', kind: 'research', sub: 'Research', ports: ['success', 'error'],
        marks: [], outcome: { tone: 'none', word: 'Not run yet' } });
      return id;
    };
  }
  if (spec.removeItem !== false) {
    src.removeItem = async (id) => {
      S.calls.push(['removeItem', id]);
      S.items = S.items.filter((i) => i.id !== id);
      S.edges = S.edges.filter((e) => e.from !== id && e.to !== id);
      return { ok: true };
    };
  }
  if (spec.dryRun !== false) {
    src.dryRun = async (...args) => {
      S.calls.push(['dryRun', ...args]);
      return { ok: true, plans: new Map(spec.plans || []) };
    };
  }
  if (spec.save) src.save = async () => { S.calls.push(['save']); return { ok: true }; };
  return { src, S };
}

/** A workflow's start, two steps, and the arrows between them, as a source
 *  draws them. */
export const DOC_ITEMS = [
  { id: '__start__', name: 'Starts · Every day at 08:00', kind: 'start', sub: 'Every day at 08:00',
    ports: [], accepts: false, fixed: true, marks: [], outcome: { tone: 'none', word: '' } },
  { id: 'n1', name: 'Summarise my inbox', kind: 'llm', sub: 'Prompt', ports: ['success', 'error'],
    marks: ['Sample pinned'], outcome: { tone: 'none', word: 'Not run yet' } },
  { id: 'n2', name: 'Send me the summary', kind: 'action', sub: 'Action', ports: ['success', 'error'],
    marks: [], outcome: { tone: 'none', word: 'Not run yet' } },
];
export const DOC_EDGES = [
  { from: '__start__', to: 'n1', when: 'success', label: 'starts', fixed: true },
  { from: 'n1', to: 'n2', when: 'success' },
];
"""


WORKFLOW_API_JS = r"""
// A fake of `workflowApi.js` (C3), answering C2's shapes from memory.
export class WorkflowRefusal extends Error {
  constructor(status, sentence, { reason = null, nodeIds = [] } = {}) {
    super(sentence);
    this.name = 'WorkflowRefusal';
    this.status = status; this.sentence = sentence; this.reason = reason; this.nodeIds = nodeIds;
  }
}
const W = globalThis.__wf;
const copy = (o) => JSON.parse(JSON.stringify(o));
function summary(w) {
  const t = W.tasks.find((x) => x.id === w.task_id) || {};
  return { id: w.id, name: w.name, task_id: w.task_id, trigger_status: t.status || 'paused',
    version: w.version, step_count: w.graph.nodes.length, last_run: w.last_run || null,
    converted_from: w.converted_from || null, updated_at: '2026-10-01T08:00:00Z' };
}
function doc(w) {
  return { ...summary(w), graph: copy(w.graph), trigger_task: copy(W.tasks.find((x) => x.id === w.task_id) || null),
    versions_kept: (w.versions || []).length };
}
function find(id) {
  const w = W.workflows.find((x) => x.id === String(id));
  if (!w) throw new WorkflowRefusal(404, 'Workflow not found');
  return w;
}
async function call(name, args, fn) {
  W.calls.push([name, ...copy(args)]);
  const refuse = W.refuse && W.refuse[name];
  if (refuse) throw new WorkflowRefusal(refuse.status || 400, refuse.sentence, refuse);
  return copy(await fn());
}
export function createWorkflowApi() {
  return {
    listWorkflows: () => call('listWorkflows', [], () => ({ workflows: W.workflows.map(summary) })),
    createWorkflow: (b = {}) => call('createWorkflow', [b], () => {
      const id = 'w' + (W.workflows.length + 1);
      const task = { id: 't' + id, name: b.name || 'Untitled workflow', task_type: 'workflow', status: 'paused',
        trigger_type: 'schedule', schedule: 'daily', scheduled_time: '08:00', workflow_id: id };
      W.tasks.push(task);
      const w = { id, name: task.name, task_id: task.id, version: 1, graph: { v: 1, start: { position: null }, nodes: [], edges: [] } };
      if (b.fromTaskId) {
        w.name = 'Nightly backup (workflow)'; task.name = w.name;
        w.converted_from = { head_task_id: b.fromTaskId, head_name: 'Nightly backup', head_status: 'active' };
        w.graph.nodes = [{ id: 'n1', kind: 'action', label: 'Nightly backup', config: { action: 'tidy_sessions' } }];
      }
      W.workflows.push(w);
      const notes = b.fromTaskId
        ? ['Made “Nightly backup (workflow)” from 3 steps. It is switched off, and the chain still runs as before.']
        : [`Made “${w.name}”. It is switched off: it will not run until you switch it on.`];
      return { workflow: doc(w), notes };
    }),
    getWorkflow: (id) => call('getWorkflow', [id], () => ({ workflow: doc(find(id)) })),
    saveWorkflow: (id, b) => call('saveWorkflow', [id, b], () => {
      const w = find(id);
      if (b.baseVersion !== w.version) {
        throw new WorkflowRefusal(409, `This workflow was saved somewhere else since you opened it: it is at version ${w.version} and your change started from version ${b.baseVersion}. Nothing was saved. Open it again to see the other change.`);
      }
      const same = JSON.stringify(b.graph) === JSON.stringify(w.graph) && b.name === w.name;
      if (!same) { w.graph = copy(b.graph); w.name = b.name; w.version += 1; }
      return { workflow: doc(w), saved: same ? 'unchanged' : 'new_version' };
    }),
    checkWorkflow: (id, b) => call('checkWorkflow', [id, b], () => ({ ok: true, check: true })),
    savePositions: (id, p) => call('savePositions', [id, p], () => ({ workflow: doc(find(id)), saved: 'positions' })),
    savePins: (id, pins) => call('savePins', [id, pins], () => {
      const w = find(id);
      for (const [nid, v] of Object.entries(pins)) { const n = w.graph.nodes.find((x) => x.id === nid); if (n) n.pinned = v; }
      return { workflow: doc(w), saved: 'pins', dropped: W.pinDropped || [] };
    }),
    deleteWorkflow: (id) => call('deleteWorkflow', [id], () => ({ ok: true, notes: [] })),
    listVersions: (id) => call('listVersions', [id], () => ({ versions: (find(id).versions || []) })),
    getVersion: (id, v) => call('getVersion', [id, v], () => ({ version: v, name: find(id).name, graph: copy(find(id).graph) })),
    restoreVersion: (id, v, base) => call('restoreVersion', [id, v, base], () => {
      const w = find(id); w.version += 1; return { workflow: doc(w), saved: 'new_version' };
    }),
    switchWorkflow: (id, on) => call('switchWorkflow', [id, on], () => {
      const w = find(id); const t = W.tasks.find((x) => x.id === w.task_id); t.status = on ? 'active' : 'paused';
      let paused = null;
      const notes = [];
      if (on && w.converted_from) {
        w.converted_from.head_status = 'paused';
        paused = { task_id: w.converted_from.head_task_id, name: w.converted_from.head_name };
        notes.push('Switched on. The chain’s first step, “Nightly backup”, is paused so the two do not both run.');
      } else notes.push(on ? 'Switched on.' : 'Switched off — it will not run until you switch it on.');
      return { workflow: doc(w), chain_paused: paused, notes };
    }),
    restoreChain: (id) => call('restoreChain', [id], () => {
      const w = find(id); const t = W.tasks.find((x) => x.id === w.task_id); t.status = 'paused';
      w.converted_from.head_status = 'active';
      return { workflow: doc(w), chain_resumed: { task_id: w.converted_from.head_task_id, name: 'Nightly backup', next_run: null },
        notes: ['The chain runs again and this workflow is switched off. Nothing was deleted.'] };
    }),
    getExecution: (id, runId) => call('getExecution', [id, runId], () => {
      const w = find(id); const ex = (W.executions || {})[runId];
      return { run: ex.run, version: w.version, version_kept: true, graph: copy(w.graph), nodes: copy(ex.nodes), cleared: !!ex.cleared };
    }),
    listExecutions: (taskId, o = {}) => call('listExecutions', [taskId, o], () => ({ runs: copy(W.runs || []), total: (W.runs || []).length })),
    runWorkflow: (taskId, o = {}) => call('runWorkflow', [taskId, o], () => ({ ok: true, dry: !!o.dry, message: 'Started' })),
    testNode: (id, nodeId, b) => call('testNode', [id, nodeId, b], () => W.testReply(b)),
  };
}
export default { createWorkflowApi, WorkflowRefusal };
"""


WORKFLOW_SOURCE_JS = r"""
// A fake of `workflowSource.js` (C3): a canvas source over one workflow, with
// a draft, built on the (fake) API and the panels the room hands it. Its
// verbs ANSWER a refusal (`{ ok: false, status, sentence, nodeIds }`) rather
// than throw it, `ready` settles even when the document could not be read
// (`state().loadError` says why), `state().viewing` is `{ version, … }` and
// `state().failed` names the step a failed run ended on — the shapes the
// room must read whichever way C3's open points are settled.
import { KIND_WORDS } from '../tasks/workflowDiagram.js';
const copy = (o) => JSON.parse(JSON.stringify(o));
const no = (err) => ({ ok: false, status: err.status || 0, sentence: err.sentence || err.message,
  reason: err.reason || null, nodeIds: err.nodeIds || [] });
export function createWorkflowSource({ api, workflowId, mode = 'edit', runId = null, describeTrigger, panels, onState }) {
  const W = globalThis.__wf;
  W.sources = W.sources || [];
  let doc = null, draft = null, dirty = false, name = '', viewing = null, exec = null, loadError = null;
  const emit = () => { if (onState) onState(); };
  const touch = () => { dirty = true; emit(); };
  const nodeOf = (id) => (draft ? draft.nodes.find((n) => n.id === id) : null);
  const recOf = (id) => (exec ? exec.nodes.find((r) => r.node_id === id) : null);
  const ready = (async () => {
    try {
      const r = await api.getWorkflow(workflowId);
      doc = r.workflow; draft = copy(doc.graph); name = doc.name;
      if (mode === 'run') exec = await api.getExecution(workflowId, runId);
    } catch (err) { loadError = err.sentence || err.message; }
    emit();
  })();
  function failed() {
    if (mode !== 'run' || !exec || !exec.run || exec.run.status !== 'error') return null;
    const last = exec.nodes[exec.nodes.length - 1];
    return last && last.status === 'error' ? { nodeId: last.node_id, label: last.label, firstLine: String(last.error || '').split('\n')[0] } : null;
  }
  const src = {
    ready,
    get readOnly() { return mode === 'run' || viewing != null; },
    words: { region: 'Steps of this workflow', emptyTitle: 'No steps yet.', emptyText: 'Add a step.',
      hint: 'Click a step to change it.', newLabel: 'Add a step' },
    async load() {
      if (loadError) throw new Error(loadError);
      const g = mode === 'run' ? exec.graph : viewing ? viewing.graph : draft;
      const trig = doc.trigger_task || {};
      const items = [{ id: '__start__', name: 'Starts · ' + (describeTrigger ? describeTrigger(trig) : ''), kind: 'start',
        sub: '', ports: [], accepts: false, fixed: true, marks: [], outcome: { tone: 'none', word: '' } }];
      for (const n of g.nodes) {
        const r = mode === 'run' ? recOf(n.id) : null;
        const tone = r ? ({ success: 'ok', error: 'error' }[r.status] || 'info') : 'none';
        items.push({ id: n.id, name: n.label, kind: n.kind, sub: KIND_WORDS[n.kind] || n.kind,
          ports: ['success', 'error'], marks: n.pinned ? ['Sample pinned'] : [],
          outcome: { tone, word: r ? r.status : (mode === 'run' ? 'Not reached in this run' : 'Not run yet') } });
      }
      const targeted = new Set(g.edges.map((e) => e.to));
      const entry = g.nodes.find((n) => !targeted.has(n.id));
      const edges = g.edges.map((e) => ({ from: e.from, to: e.to, when: e.port }));
      if (entry) edges.unshift({ from: '__start__', to: entry.id, when: 'success', label: 'starts', fixed: true });
      return { items, edges };
    },
    async connect(from, when, to) { draft.edges = draft.edges.filter((e) => !(e.from === from && e.port === when)); draft.edges.push({ from, port: when, to }); touch(); return { ok: true }; },
    async disconnect(from, when, to) { draft.edges = draft.edges.filter((e) => !(e.from === from && e.port === when && e.to === to)); touch(); return { ok: true }; },
    async loadPositions() { return {}; },
    async savePositions(map) { return api.savePositions(workflowId, Object.fromEntries([...map].map(([k, p]) => [k, [p.x, p.y]]))).then(() => ({ ok: true })); },
    openPanel(host, item, { onSaved, onCancel }) {
      W.opened = (W.opened || []).concat([[mode, item ? item.id : null]]);
      if (item && item.id === '__start__') {
        return panels.start(host, { triggerTask: doc.trigger_task, tasks: W.tasks,
          onSaved: (task) => { if (task) doc.trigger_task = task; emit(); onSaved({ id: '__start__', name: 'Starts', sentence: 'Saved when it starts.' }); },
          onCancel });
      }
      if (mode === 'run') return panels.record(host, { node: copy(exec.graph.nodes.find((n) => n.id === item.id) || null), record: copy(recOf(item.id) || null), run: copy(exec.run) });
      const n = nodeOf(item.id);
      return panels.node(host, { node: copy(n), tasks: W.tasks, workflow: doc, source: src,
        onApply: (change) => { Object.assign(n, { label: change.label, kind: change.kind, config: change.config }); touch(); onSaved({ id: n.id, name: change.label, sentence: `Changed “${change.label}”. Save the workflow to keep it.` }); },
        onCancel });
    },
    async newItem(anchor) {
      const kind = await panels.palette(anchor);
      if (!kind) return null;
      const id = 'n' + (draft.nodes.length + 1) + 'x';
      draft.nodes.push({ id, kind, label: KIND_WORDS[kind] || kind, config: {}, position: null, pinned: null });
      touch();
      return id;
    },
    async removeItem(id) { draft.nodes = draft.nodes.filter((n) => n.id !== id); draft.edges = draft.edges.filter((e) => e.from !== id && e.to !== id); touch(); return { ok: true, sentence: 'Save the workflow to keep the change.' }; },
    async dryRun() {
      try { await api.runWorkflow(doc.task_id, { dry: true }); } catch (err) { return no(err); }
      return { ok: true, plans: new Map(W.plans || []), head: '__start__', partial: !W.plans };
    },
    state() {
      return { mode, workflow: doc, name, dirty, loadError,
        viewing: viewing ? { version: viewing.version, name: viewing.name } : null,
        run: exec ? exec.run : null, failed: failed() };
    },
    rename(n) { name = n; touch(); return { ok: true }; },
    async save() {
      try {
        const r = await api.saveWorkflow(workflowId, { name, graph: draft, baseVersion: doc.version });
        doc = r.workflow; draft = copy(doc.graph); name = doc.name; dirty = false; emit();
        return { ok: true, saved: r.saved, sentence: r.saved === 'new_version' ? `Saved as version ${doc.version}.` : 'Nothing to save.' };
      } catch (err) { return { ...no(err), stale: err.status === 409 }; }
    },
    async discard() { W.discarded = (W.discarded || 0) + 1; draft = copy(doc.graph); name = doc.name; dirty = false; emit(); return { ok: true }; },
    async setPin(id, data) {
      try {
        const r = await api.savePins(workflowId, { [id]: data });
        const n = nodeOf(id); if (n) n.pinned = data; emit();
        return { ok: true, pinned: data, dropped: r.dropped || [] };
      } catch (err) { return no(err); }
    },
    async test(id, b) {
      try { return { ok: true, ...(await api.testNode(workflowId, id, { node: copy(nodeOf(id)), ...b })) }; } catch (err) { return no(err); }
    },
    async runNow() { try { await api.runWorkflow(doc.task_id); return { ok: true, sentence: 'Started.' }; } catch (err) { return no(err); } },
    async switchOn(on) {
      try {
        const r = await api.switchWorkflow(workflowId, on); doc = r.workflow; emit();
        return { ok: true, notes: r.notes || [], chainPaused: r.chain_paused || null, sentence: (r.notes || []).join(' ') };
      } catch (err) { return no(err); }
    },
    async restoreChain() {
      try {
        const r = await api.restoreChain(workflowId); doc = r.workflow; emit();
        return { ok: true, notes: r.notes || [], chainResumed: r.chain_resumed || null, sentence: (r.notes || []).join(' ') };
      } catch (err) { return no(err); }
    },
    async versions() { try { const r = await api.listVersions(workflowId); return { ok: true, versions: r.versions || [] }; } catch (err) { return no(err); } },
    async showVersion(v) {
      if (v == null) { viewing = null; emit(); return { ok: true }; }
      try { const r = await api.getVersion(workflowId, v); viewing = { version: r.version, name: r.name, graph: r.graph }; emit(); return { ok: true }; } catch (err) { return no(err); }
    },
    async restoreVersion(v) {
      if (dirty) return { ok: false, sentence: 'You have changes that are not saved. Save them or throw them away first, then restore.' };
      try {
        const r = await api.restoreVersion(workflowId, v, doc.version); doc = r.workflow; draft = copy(doc.graph); viewing = null; emit();
        return { ok: true, saved: r.saved, sentence: `Restored version ${v} as version ${doc.version}.` };
      } catch (err) { return no(err); }
    },
    destroy() {},
  };
  if (mode === 'run') { delete src.newItem; delete src.removeItem; }
  W.sources.push({ mode, runId, src });
  return src;
}
export default { createWorkflowSource };
"""
