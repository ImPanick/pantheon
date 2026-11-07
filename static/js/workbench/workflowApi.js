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
// without this file and watches the nine come back. Wave D (`C-W`) adds four —
// the palette, the waiting list, a step's fields and a parked step's answer —
// each spelled out the same way, so the count still does not move. Wave E
// (`C-A`, `P22-19`/`20`/`24`) adds three — a workflow's file, a step's "why did
// this fail?" and its fix — and two bodies on routes already here (a draft or a
// file on `POST /api/workflows`, the steps a person checked on `PUT`). The
// builder's elevation adds a draft step's fields (`B1850`) and every problem
// a save of the draft would name (`B1851`), each spelled out the same way.
//
// **A refusal is a `WorkflowRefusal`**, carrying the status and the server's
// own sentence (`{detail}`, read by `refusal.js`), and — for a document the
// engine refused — its `reason` and the steps it names. Nothing here words a
// refusal of its own except when Pantheon could not be reached at all.

import { readRefusal } from './refusal.js';

/** Thrown for any answer that is not a 2xx, and when nothing answered. */
export class WorkflowRefusal extends Error {
  constructor(status, sentence, { reason = null, nodeIds = [], field = null } = {}) {
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
    /** `P22-09` (wf-canvas; C-W "refusal bodies gain field"): the field of the
     *  step it is about, or null. */
    this.field = field;
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
      throw new WorkflowRefusal(r.status, r.sentence, { reason: r.reason, nodeIds: r.nodeIds, field: r.field });
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
    /** A new, empty workflow; or (`fromTaskId`, `P22-06`) the chain that task
     *  is a step of; or (`describe`, `P22-19`) a draft the model makes from
     *  the person's words; or (`file`, `P22-24`) a workflow file's parsed
     *  JSON. Created switched off. → `{ workflow, notes }`, and for a draft
     *  or a file also `{ missing: [sentence], destinations: [line] }`, with
     *  every step of `workflow.graph` marked `unchecked` (C-A).
     *  `tz` (optional, `Intl…resolvedOptions().timeZone`) is the person's time
     *  zone, so "at 8" and a Wait "until 08:00" mean their 8: the new start's
     *  own zone for an empty workflow and a draft (`B1867`), and for a file
     *  that names none. A chain keeps its first step's zone; a zone this
     *  machine does not know is left out, never refused. Omitted, the start
     *  is on the server's clock, as before. */
    createWorkflow({ name, fromTaskId, describe, tz, file } = {}) {
      return call('POST', `/api/workflows`,
        given({ name, from_task_id: fromTaskId, describe, tz, file }));
    },
    /** `P22-19`. A person looked at these steps and says they look right: their
     *  `unchecked` marks go. Never a version; a 403 `WorkflowRefusal` unless a
     *  person sent it. → `{ workflow, saved: "checked" }` */
    checkSteps(id, nodeIds) {
      return call('PUT', `/api/workflows/${enc(id)}`, { checked: Array.from(nodeIds || []) });
    },
    /** `P22-24`. The workflow as a file to hand someone (`pantheon_workflow: 1`)
     *  — never a key, a token, an address, a header value or a sample. Answers
     *  a `Blob`, with the server's own file name as `blob.filename`. */
    async exportWorkflow(id) {
      let res;
      try {
        res = await net(`/api/workflows/${enc(id)}/export`, { method: 'GET', credentials: 'same-origin' });
      } catch (_) {
        throw new WorkflowRefusal(0, UNREACHABLE);
      }
      if (!res || !res.ok) {
        const r = await readRefusal(res);
        throw new WorkflowRefusal(r.status, r.sentence, { reason: r.reason, nodeIds: r.nodeIds, field: r.field });
      }
      const blob = await res.blob();
      const said = (res.headers && res.headers.get && res.headers.get('Content-Disposition')) || '';
      const m = /filename="?([^";]+)"?/i.exec(said);
      blob.filename = m ? m[1] : 'workflow.json';
      return blob;
    },
    /** `P22-20`. "Why did this fail?" — the model reads what the step was
     *  handed and what came back (as untrusted data) and answers. Writes
     *  nothing. `item` is the For-each item's index, or null.
     *  → `{ why, model, changed_since_run, proposal: { base_version, node_id,
     *  item, config, changes: [{ field, words, before, after, where, from_run }] }
     *  | null, left_out: [sentence] }` */
    explainStep(id, runId, { nodeId, item = null } = {}) {
      return call('POST', `/api/workflows/${enc(id)}/runs/${enc(runId)}/explain`,
        { node_id: nodeId, item: item == null ? null : item });
    },
    /** `P22-20`. Apply a proposed fix to one step: a new version (source
     *  `fixed`), refused (400) if the change is one a fix may not make, 409 if
     *  the workflow moved since `baseVersion`, 403 unless a person sent it.
     *  Undo is `restoreVersion(id, undo_version, newVersion)`.
     *  → `{ workflow, saved, undo_version }` */
    fixStep(id, nodeId, { config, baseVersion } = {}) {
      return call('POST', `/api/workflows/${enc(id)}/nodes/${enc(nodeId)}/fix`,
        { config, base_version: baseVersion });
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
    /** `B1851`. Every refusal a save of this draft would give, at once —
     *  `checkWorkflow` answers with the first only. Each step checked where
     *  it stands, then the whole (loops, steps nothing leads to, unknown
     *  arrows…), in the order a save names them, at most fifty; nothing is
     *  written. An empty list is "Save would pass".
     *  → `{ problems: [{ node_ids, field, reason, sentence }], count, more }` */
    listProblems(id, { name, graph } = {}) {
      return call('POST', `/api/workflows/${enc(id)}/problems`, given({ name, graph }));
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
    /** `B1845`. A copy of the saved workflow, as a new workflow of the same
     *  person: named "<name> (copy)", switched off, its steps as they are
     *  (no marks: the person made them). → `{ workflow }` */
    duplicateWorkflow(id) {
      return call('POST', `/api/workflows/${enc(id)}/duplicate`);
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
     *  → `{ run, version, version_kept, graph, nodes: [NodeRecord], cleared, cleared_sentence }` */
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
    /** `B1869`. Stop a workflow run: one that is running is cancelled, one
     *  that waits (a Wait, a yes, an answer) is ended where it waits. Its
     *  record says who stopped it. → `{ ok, sentence }`; a 409 when the run
     *  has already ended. */
    stopRun(workflowId, runId) {
      return call('POST', `/api/workflows/${enc(workflowId)}/runs/${enc(runId)}/stop`);
    },
    runWorkflow(taskId, { dry = false } = {}) {
      return dry
        ? call('POST', `/api/tasks/${enc(taskId)}/run?dry=true`)
        : call('POST', `/api/tasks/${enc(taskId)}/run`);
    },
    /** `B1852`. Run the SAVED current version once, as your run, even while
     *  the workflow is switched off — nothing about when it runs moves (not
     *  the switch, not its next run). The run is in the Runs list with
     *  `run.test === true` and its cause line reads "Test run"; its Waits and
     *  questions go on while it is off. A 409 `WorkflowRefusal` (with Run
     *  now's sentence) while a run is going or waiting. → `{ ok, run_id }` */
    testRun(id) {
      return call('POST', `/api/workflows/${enc(id)}/test-run`);
    },
    /** `B1854`. Retry a FAILED run from one of its steps — `nodeId`, or
     *  (left out) the step it failed on: a new run of the version that run
     *  ran, in which the steps it finished before and beside that step are
     *  kept (their records carry `kept_from: <failed run id>` and a first
     *  log line "Kept from the run at 10:42") and that step and those after
     *  it run again. The new run's `retry_of` is the failed run's id. A 400
     *  `WorkflowRefusal` says why it cannot (it did not fail; its version is
     *  not kept; the step did not run); a 409 while a run is going or
     *  waiting, or for a real run of a workflow switched off.
     *  → `{ ok, run_id }` */
    retryRun(id, runId, nodeId) {
      return call('POST', `/api/workflows/${enc(id)}/runs/${enc(runId)}/retry`,
        nodeId ? { node_id: nodeId } : undefined);
    },
    /** Test one step as it stands on the canvas (`P22-08`). `source` is
     *  `last | pinned | custom | example | none`. → `{ outcome:
     *  "needs_confirmation", plan, effects }` or `{ outcome: "ran", status,
     *  text, data, steps, model, took_ms, input_used, dropped }` */
    testNode(id, nodeId, { node, source = 'none', input, confirm = false } = {}) {
      return call('POST', `/api/workflows/${enc(id)}/nodes/${enc(nodeId)}/test`,
        given({ node, source, input, confirm: !!confirm }));
    },
    /** `B1209`. A workflow's start, written to its trigger task through the
     *  door every task is edited by (`PUT /api/tasks/{id}`) — the fields the
     *  start's form hands over and nothing else. → `{ ok, task }` */
    updateTrigger(taskId, patch) {
      return call('PUT', `/api/tasks/${enc(taskId)}`, patch);
    },
    /** The person's tasks — what a run-task step can be pointed at. The
     *  route every task surface reads; an addition beside `C3`'s list. */
    listTasks() {
      return call('GET', `/api/tasks`);
    },
    /** `C-W`. What a step can be, for this person: every kind (available or
     *  not, and why), each field's mapping (`value` / `never`, with the
     *  reason), integrations, MCP tools, skills, the AI step's tools, the
     *  workstation, the limits and the operators. The browser derives none of
     *  it. → `{ kinds, integrations, mcp_tools, skills, ai_tools, workstation,
     *  limits, operators, examples, has_model, model_why, drafter_model,
     *  drafter_why }`
     *
     *  `B1891`. `has_model` is false when this person has no model at all;
     *  `model_why` is then the sentence Prompt, Research and Skill are greyed
     *  with in `kinds` ("No model yet. An admin adds one in Settings → Added
     *  Models."), else "". `drafter_model` is the model *Draft it* would use,
     *  or null; `drafter_why` is then the sentence the draft would be refused
     *  with ("No model is set up to draft a workflow. Make it by hand."), else
     *  "" — read it to hold *Draft it* and the examples back. */
    getPalette() {
      return call('GET', `/api/workflows/palette`);
    },
    /** `B1099`. What one field of a step, as it stands, may be filled with —
     *  the rule's answer (`slot_for`), for a field the palette decides per
     *  entry (an HTTP query or body value, by its name). → `{ mapping, why }` */
    fieldSlot(node, field) {
      return call('POST', `/api/workflows/slot`, { node, field });
    },
    /** `C-W`. The fields a step can pick from the steps before it, each with
     *  an example and where it came from. → `{ sources: [{ node_id, label,
     *  kind, origin, at, fields: [{ ref, path, type, example }] }] }` */
    listFields(id, nodeId) {
      return call('GET', `/api/workflows/${enc(id)}/nodes/${enc(nodeId)}/fields`);
    },
    /** `B1850`. `listFields`' answer for a step as it stands in the DRAFT —
     *  one not saved yet, or in a draft Save would still refuse: `graph` is
     *  the document on the canvas. The arrows and what each step promises are
     *  the draft's; the last run's records and the pinned samples come only
     *  from steps the saved document also has. Writes nothing. A 404
     *  `WorkflowRefusal` when `nodeId` is not in `graph`, a 400 when `graph`
     *  is not a draft at all. → `{ sources: [...] }`, as `listFields`. */
    listDraftFields(id, nodeId, graph) {
      return call('POST', `/api/workflows/${enc(id)}/fields`, { node_id: nodeId, graph });
    },
    /** `C-W`. Every step of this person's workflows that waits now — for a
     *  yes (`approval` is the card while it can still be answered), a time,
     *  or Pantheon to be idle. → `{ waiting: [{ workflow_id, workflow, run_id,
     *  node_id, item, label, kind, since, until, approval }] }` */
    listWaiting() {
      return call('GET', `/api/workflows/waiting`);
    },
    /** `C-W`. A parked step's answer: `decision` is `approve_task` (Allow
     *  once) or `deny`; `item` is the For-each item, or null.
     *  → `{ ok, outcome: "resumed" | "denied" | "lapsed", sentence, step }` */
    answerStep(id, runId, { nodeId, item = null, approvalId, decision } = {}) {
      return call('POST', `/api/workflows/${enc(id)}/runs/${enc(runId)}/answer`,
        { node_id: nodeId, item: item == null ? null : item, approval_id: approvalId, decision });
    },
  };
}

export default { createWorkflowApi, WorkflowRefusal };
