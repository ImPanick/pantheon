// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/taskSource.js
//
// `P22-05` (wf-ui). The tasks and chains that run today, as a canvas source.
//
// `canvas.js` drew tasks and nothing else: the `GET /api/tasks` read, the
// `PUT /api/tasks/{id}` that writes an edge, the positions kept through the
// prefs door and the task form in the side panel were all inside it. Slice B
// draws a workflow document on the same canvas (`Law 14`: one canvas, never a
// second), so everything that is about TASKS moved here, behind the canvas
// source contract the design names C3 (`/work/notes/SLICE-B-DESIGN.md` § 6.3,
// § 7):
//
//   { readOnly, words, load() → { items, edges }, connect(from, when, to),
//     disconnect(from, when, to) → { ok, sentence? }, loadPositions(),
//     savePositions(map), openPanel(host, item, { onSaved, onCancel }),
//     newItem?, removeItem?, dryRun? }
//
// The workflow document's source is `workflowSource.js` (`wf-api`). This one
// is the canvas `P22-02` shipped, unchanged in what it asks the server and
// what it says: the moves were made so that every request, body and sentence
// the canvas's tests pin is the one they pinned before (`Law 1`).
//
// Three things here the contract leaves optional, and only this source has:
//
//   * `dryRunFrom: 'item'` — *Show me what this would do* is a step's own
//     (the open step is the head of the plan), where a workflow is planned
//     whole from the room's toolbar;
//   * `openItem(item)` — a step that IS a workflow (`task_type="workflow"`,
//     its trigger task) opens its document rather than the task form, which
//     cannot edit one (§ 6.1);
//   * `offer(id)` — what the status bar offers on a chained step: *Make this
//     chain a workflow* (`P22-06`).

import { EDGE_WORDS, EDGE_COLUMNS, KIND_WORDS, componentOf } from '../tasks/workflowDiagram.js';
import { runStatusTone, runStatusLabel } from '../runStatus.js';
import { PORTS } from './graphLayout.js';
import { refusalText } from './refusal.js';

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

/**
 * What the server said when it refused, as one sentence — `refusal.js`'s, the
 * one reading of a refusal in the Workbench (design § 6.3, `Law 7`). This
 * module reads two refusals with it and re-exports it, so a caller that read
 * it from here (or from `canvas.js`) reads the same function. Closed at the
 * wave C merge (`integrate-c`): wf-ui held the only copy here until wf-api's
 * `refusal.js` was on the same tree; the two bodies were identical.
 */
export { refusalText };

/** A step's last outcome: the tone that styles it and the words it says. */
export function outcomeOf(task) {
  const status = task && task.last_run_status;
  if (!status) {
    return { tone: 'none', word: task && task.last_run ? 'No record of the last run' : 'Not run yet' };
  }
  return { tone: runStatusTone(status) || 'info', word: 'Last run: ' + runStatusLabel(status, 'job') };
}

/** The words the tasks canvas says, exactly as `P22-02` and `B1048` wrote them. */
export const TASK_WORDS = Object.freeze({
  region: 'Your automations',
  emptyTitle: 'No automations yet.',
  // `B1048`: there are tasks, and every one of them is a built-in set aside.
  emptyTitleOwn: 'No automations of your own yet.',
  emptyText: 'A step is a task: a prompt, a research run or an action, started by a schedule, an event or a webhook. Make one, make another, then join them.',
  // `P23-05` (COPY-U-23, Doc 2 § 5): one line, always on; the keys are its
  // tooltip (`hintKeys`), not a third sentence. One noun on this canvas: task.
  hint: 'Drag from “' + EDGE_WORDS.success + '” or “' + EDGE_WORDS.error
    + '” to the next step, or press Connect…. Click a step to edit it.',
  hintKeys: 'Keys: arrows go from step to step, Enter opens one, M moves it.',
  newLabel: 'New task',
  newTitle: 'Make a new task and put it on the canvas',
  unknownName: 'a task you cannot see',
  missingTitle: 'A task you cannot see',
  missingSub: 'Not in your list of tasks',
  loadFailed: 'The list of tasks could not be loaded. Close the Workbench and open it again to retry.',
});

const taskName = (t) => String((t && t.name) || 'Untitled task');

/**
 * The tasks canvas's source.
 *
 * `opts.fetch` — the page's `fetch` by default; injected so a test sees and
 *   answers every request.
 * `opts.mountPanel` — the `P22` panel contract (`taskFields.js:mountTaskFields`).
 * `opts.describeTrigger(task)` — the Tasks window's schedule words.
 * `opts.openWorkflow(workflowId, task)` — a workflow's step was opened.
 * `opts.onMakeWorkflow(headId, id)` — *Make this chain a workflow* was pressed.
 */
export function createTaskSource(opts = {}) {
  const net = typeof opts.fetch === 'function' ? opts.fetch : (url, init) => globalThis.fetch(url, init);
  const mountPanel = typeof opts.mountPanel === 'function' ? opts.mountPanel : null;
  const describe = (task) => {
    if (typeof opts.describeTrigger !== 'function') return '';
    try { return String(opts.describeTrigger(task) || ''); } catch (_) { return ''; }
  };

  let rows = [];
  let byId = new Map();
  let graph = { nodes: [], edges: [] };

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

  function take(data) {
    rows = Array.isArray(data && data.tasks) ? data.tasks : [];
    byId = new Map(rows.map((t) => [String(t.id), t]));
    const g = data && data.graph;
    graph = g && Array.isArray(g.nodes)
      ? { nodes: g.nodes, edges: Array.isArray(g.edges) ? g.edges : [] }
      : { nodes: rows.map((t) => ({ id: t.id, name: t.name })), edges: [] };
  }

  function itemOf(task, targeted) {
    const id = String(task.id);
    const kind = task.task_type || 'llm';
    // What starts it goes on the step nothing points at — `P8-34`'s rule: a
    // step downstream is started by the arrow into it, and repeating its own
    // schedule there would say something untrue about when it runs next.
    const trigger = targeted.has(id) ? '' : describe(task);
    const paused = task.status === 'paused';
    return {
      id, taskId: id, name: taskName(task), kind,
      sub: [KIND_WORDS[kind] || KIND_WORDS.llm, trigger, paused ? 'paused' : ''].filter(Boolean).join(' · '),
      paused, outcome: outcomeOf(task), ports: PORTS.slice(), marks: [], accepts: true, missing: false,
      builtin: !!task.is_builtin,
    };
  }

  async function load() {
    const res = await net(TASKS_URL, { credentials: 'same-origin' });
    if (!res.ok) throw new Error('GET /api/tasks answered ' + res.status);
    take(await res.json());
    const targeted = new Set(graph.edges.map((e) => String(e.to)));
    // In the served graph's order, which is the order the layout breaks ties
    // by — the order the canvas drew in before the move.
    const seen = new Set();
    const items = [];
    for (const n of graph.nodes) {
      const t = byId.get(String(n && n.id));
      if (t && !seen.has(String(t.id))) { seen.add(String(t.id)); items.push(itemOf(t, targeted)); }
    }
    for (const t of rows) if (!seen.has(String(t.id))) items.push(itemOf(t, targeted));
    return {
      items,
      edges: graph.edges.map((e) => ({ from: String(e.from), to: String(e.to), when: String(e.when || '') })),
    };
  }

  async function connect(from, when, to) {
    const column = EDGE_COLUMNS[when];
    if (!column) return { ok: false, sentence: `This canvas cannot write “${when}” yet.` };
    const res = await put('/api/tasks/' + encodeURIComponent(from), { [column]: String(to) });
    return res.ok ? { ok: true } : { ok: false, sentence: res.sentence };
  }

  async function disconnect(from, when) {
    const column = EDGE_COLUMNS[when];
    if (!column) return { ok: false, sentence: `This canvas cannot write “${when}” yet.` };
    const res = await put('/api/tasks/' + encodeURIComponent(from), { [column]: '' });
    return res.ok ? { ok: true } : { ok: false, sentence: res.sentence };
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

  async function savePositions(map) {
    const tasks = {};
    for (const [id, p] of map) {
      if (byId.has(id)) tasks[id] = [Math.round(p.x), Math.round(p.y)];
    }
    try {
      const res = await net('/api/prefs/' + POSITIONS_PREF, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: { v: 1, tasks } }),
      });
      return { ok: !!res.ok };
    } catch (_) {
      return { ok: false };
    }
  }

  function openPanel(host, item, { onSaved, onCancel }) {
    if (!mountPanel) {
      host.textContent = 'The step editor did not load. Edit this task from the Tasks window.';
      return null;
    }
    // The `P22` panel contract: the row exactly as `GET /api/tasks` served
    // it, and the whole list — the chain pickers offer every task, drawn or
    // set aside.
    return mountPanel(host, {
      task: item ? (byId.get(String(item.id)) || null) : null,
      tasks: rows,
      onSaved,
      onCancel,
    });
  }

  /** § 6.1: a step whose task is a workflow's trigger opens its document. */
  function openItem(item) {
    const t = item && byId.get(String(item.id));
    if (!t || t.task_type !== 'workflow' || typeof opts.openWorkflow !== 'function') return false;
    opts.openWorkflow(t.workflow_id || null, t);
    return true;
  }

  /** `P22-06`. A chained step's status bar offers to make the chain a
   *  workflow; the head goes to the server, which is where a chain with two
   *  heads or a workflow in it is refused in words. */
  function offer(id) {
    if (typeof opts.onMakeWorkflow !== 'function') return null;
    const t = byId.get(String(id));
    if (!t || t.task_type === 'workflow') return null;
    const comp = componentOf(graph, String(id));
    if (comp.ids.size < 2) return null;
    const targeted = new Set(comp.edges.map((e) => String(e.to)));
    const heads = [...comp.ids].filter((x) => !targeted.has(x) && byId.has(x));
    const head = heads.length === 1 ? heads[0] : String(id);
    return { label: 'Make this chain a workflow', run: () => opts.onMakeWorkflow(head, String(id)) };
  }

  /** `P22-04`. A dry run of the chain from `id`, in the reply's order
   *  (breadth first, the head first — `P22-WAVE-B.md`'s contract). */
  async function dryRun(id) {
    let res = null;
    let reply = null;
    let sentence = '';
    try {
      res = await net(`/api/tasks/${encodeURIComponent(id)}/run?dry=true&chain=true`,
        { method: 'POST', credentials: 'same-origin' });
      if (res.ok) reply = await res.json();
      else {
        try { sentence = refusalText((await res.json()).detail); } catch (_) { sentence = ''; }
      }
    } catch (_) {
      sentence = 'Pantheon could not be reached';
    }
    if (!reply) {
      // The route's own sentence: a loop (`P22-01`'s rule, as a save is
      // answered), "Task is already running", an admin-only action.
      if (!sentence && res && res.status === 409) sentence = 'Task is already running';
      return { ok: false, sentence: sentence || `the server answered ${res ? res.status : 'nothing'}` };
    }
    const chain = Array.isArray(reply.chain) ? reply.chain : null;
    // A reply with no `chain` is the head's plan alone (`run`): drawn, and
    // nothing said of the rest — not "would not reach", which is not known.
    const run = reply.run || {};
    const entries = chain || [{
      task_id: id, when: null, depth: 0, steps: run.steps,
      declined: Array.isArray(run.steps) && run.steps.length ? null : (run.error || run.result || null),
    }];
    const plans = new Map();
    for (const e of entries) {
      const key = e && e.task_id != null ? String(e.task_id) : '';
      if (!key || plans.has(key)) continue;
      plans.set(key, { steps: e.steps, declined: e.declined, when: e.when, depth: e.depth });
    }
    return { ok: true, plans, partial: !chain, head: String(id) };
  }

  return {
    readOnly: false,
    words: TASK_WORDS,
    // The canvas writes this data attribute beside its own `data-item-id`, so
    // what read a task's step by `data-task-id` before the move still does.
    idKey: 'taskId',
    dryRunFrom: 'item',
    load, connect, disconnect, loadPositions, savePositions, openPanel, openItem, offer, dryRun,
    /** Every row as served, for the room's chain door. */
    rows: () => rows,
  };
}

export default { createTaskSource, refusalText, outcomeOf, POSITIONS_PREF, TASKS_URL, TASK_WORDS };
