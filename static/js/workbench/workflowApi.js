// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/workflowApi.js
//
// `P22-05`…`P22-08`. The browser's one door to a workflow document: every
// route of `routes/workflow/workflow_routes.py`, plus the trigger task's own
// run, dry run and run list, which a workflow reuses rather than duplicates
// (`Law 14`). Nothing here draws; `workflowSource.js` and the Workbench's room
// are its callers.
//
// **Every path is spelled out, in full, at its call.** `check-unreachable.py`
// counts a route as reached when a string in `static/` normalises to its
// pattern, and it is held at a ceiling (`--max-routes 90`). Nine new paths,
// each written literally below, keep that count where it was; a helper that
// assembled them from pieces would hide them from the checker and push it
// over. `tests/test_every_workflow_route_has_its_caller.py` runs the checker
// without this file and watches the nine come back.
//
// **A refusal is a `WorkflowRefusal`**, carrying the status and the server's
// own sentence (`{detail}`, read by `refusal.js`), and — for a document the
// engine refused — its `reason` and the steps it names. Nothing here words a
// refusal of its own except when Pantheon could not be reached at all.

import { readRefusal } from './refusal.js';

/** Thrown for any answer that is not a 2xx, and when nothing answered. */
export class WorkflowRefusal extends Error {
  constructor(status, sentence, { reason = null, nodeIds = [] } = {}) {
    super(sentence);
    this.name = 'WorkflowRefusal';
    /** The HTTP status; 0 when Pantheon could not be reached. */
    this.status = status;
    /** What the server said, to show as it is. */
    this.sentence = sentence;
    /** The engine's reason for refusing a document, or null. */
    this.reason = reason;
    /** The steps that refusal names. */
    this.nodeIds = nodeIds;
  }
}

const UNREACHABLE = 'Pantheon could not be reached, so nothing changed.';

/**
 * The data layer. `fetch` is injected so a test can answer every request and
 * see its body; by default it is the page's own.
 *
 * Every function answers the route's JSON, or throws a `WorkflowRefusal`.
 * Arguments are the browser's names; bodies are the server's (`base_version`,
 * `from_task_id`), so the wire is exactly the route's (`C2`).
 */
export function createWorkflowApi({ fetch } = {}) {
  const net = typeof fetch === 'function' ? fetch : (url, init) => globalThis.fetch(url, init);
  const enc = (value) => encodeURIComponent(String(value == null ? '' : value));

  async function call(method, url, body) {
    const init = { method, credentials: 'same-origin' };
    if (body !== undefined) {
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await net(url, init);
    } catch (_) {
      throw new WorkflowRefusal(0, UNREACHABLE);
    }
    if (!res || !res.ok) {
      const r = await readRefusal(res);
      throw new WorkflowRefusal(r.status, r.sentence, { reason: r.reason, nodeIds: r.nodeIds });
    }
    try {
      return await res.json();
    } catch (_) {
      return null;
    }
  }

  // Only the keys that were given, so an omitted one is not sent as null.
  const given = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined));

  return {
    /** → `{ workflows: [Summary] }` */
    listWorkflows() {
      return call('GET', `/api/workflows`);
    },
    /** A new, empty workflow, or (`fromTaskId`, `P22-06`) the chain that task
     *  is a step of. Created switched off. → `{ workflow, notes }` */
    createWorkflow({ name, fromTaskId } = {}) {
      return call('POST', `/api/workflows`, given({ name, from_task_id: fromTaskId }));
    },
    /** → `{ workflow: Doc }` */
    getWorkflow(id) {
      return call('GET', `/api/workflows/${enc(id)}`);
    },
    /** A content save. A new version only if the content moved; a 409
     *  `WorkflowRefusal` if `baseVersion` is stale. → `{ workflow, saved }` */
    saveWorkflow(id, { name, graph, baseVersion } = {}) {
      return call('PUT', `/api/workflows/${enc(id)}`, given({ name, graph, base_version: baseVersion }));
    },
    /** The same body, checked and not written. → `{ ok: true, check: true }` */
    checkWorkflow(id, { name, graph, baseVersion } = {}) {
      return call('PUT', `/api/workflows/${enc(id)}?check=true`, given({ name, graph, base_version: baseVersion }));
    },
    /** `{ "<step id>" | "start": [x, y] }` — never a version. */
    savePositions(id, positions) {
      return call('PUT', `/api/workflows/${enc(id)}`, { positions });
    },
    /** `{ "<step id>": sample | null }` — never a version.
     *  → `{ workflow, saved: "pins", dropped }` */
    savePins(id, pins) {
      return call('PUT', `/api/workflows/${enc(id)}`, { pins });
    },
    /** → `{ ok, notes }`; 409 while it runs. */
    deleteWorkflow(id) {
      return call('DELETE', `/api/workflows/${enc(id)}`);
    },
    /** → `{ versions: [{ version, name, saved_at, source, step_count, current }] }` */
    listVersions(id) {
      return call('GET', `/api/workflows/${enc(id)}/versions`);
    },
    /** → `{ version, name, saved_at, source, graph, … }` */
    getVersion(id, version) {
      return call('GET', `/api/workflows/${enc(id)}/versions/${enc(version)}`);
    },
    /** Put a kept version back, as a new version. → `{ workflow, saved }` */
    restoreVersion(id, version, baseVersion) {
      return call('POST', `/api/workflows/${enc(id)}/versions/${enc(version)}/restore`,
        given({ base_version: baseVersion }));
    },
    /** On or Off. → `{ workflow, chain_paused, notes }` */
    switchWorkflow(id, on) {
      return call('POST', `/api/workflows/${enc(id)}/switch`, { on: !!on });
    },
    /** *Put the old chain back* (`P22-06`). → `{ workflow, chain_resumed, notes }` */
    restoreChain(id) {
      return call('POST', `/api/workflows/${enc(id)}/restore-chain`);
    },
    /** One run, every step (`P22-07`).
     *  → `{ run, version, version_kept, graph, nodes: [NodeRecord], cleared }` */
    getExecution(id, runId) {
      return call('GET', `/api/workflows/${enc(id)}/runs/${enc(runId)}`);
    },
    /** The trigger task's runs, newest first — a workflow's Runs list.
     *  → `{ runs, total }` */
    listExecutions(taskId, { limit, offset } = {}) {
      const q = new URLSearchParams();
      if (limit != null) q.set('limit', String(limit));
      if (offset != null) q.set('offset', String(offset));
      const url = `/api/tasks/${enc(taskId)}/runs`;
      return call('GET', q.toString() ? url + '?' + q.toString() : url);
    },
    /** Run the workflow now, through its trigger task — or (`dry`) plan it:
     *  the reply then carries `nodes`, one plan per step. */
    runWorkflow(taskId, { dry = false } = {}) {
      return dry
        ? call('POST', `/api/tasks/${enc(taskId)}/run?dry=true`)
        : call('POST', `/api/tasks/${enc(taskId)}/run`);
    },
    /** Test one step as it stands on the canvas (`P22-08`). `source` is
     *  `last | pinned | custom | example | none`. → `{ outcome:
     *  "needs_confirmation", plan, effects }` or `{ outcome: "ran", status,
     *  text, data, steps, model, took_ms, input_used, dropped }` */
    testNode(id, nodeId, { node, source = 'none', input, confirm = false } = {}) {
      return call('POST', `/api/workflows/${enc(id)}/nodes/${enc(nodeId)}/test`,
        given({ node, source, input, confirm: !!confirm }));
    },
    /** The person's tasks — what a run-task step can be pointed at. The
     *  route every task surface reads; an addition beside `C3`'s list. */
    listTasks() {
      return call('GET', `/api/tasks`);
    },
  };
}

export default { createWorkflowApi, WorkflowRefusal };
