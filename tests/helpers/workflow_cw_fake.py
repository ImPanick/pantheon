# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-09`…`P22-18` (wf-canvas) — contract C-W, faked in its exact shapes, for the browser half.

The Workbench's step panels, picker, palette, waiting runs and the workflow
question's notice (`wf-canvas`, package P4 of `/work/notes/SLICE-CD-DESIGN.md`)
consume contract **C-W** — the workflow routes `wf-walker` (P3) builds on its
own branch at the same time, and the four functions it adds to
`workflowApi.js`:

    GET  /api/workflows/palette → {kinds:[{kind,word,group,hint,ports,available,why,slots:{field:{mapping,why}}}],
           integrations:[{id,name,preset,description}], mcp_tools:[{qualified_name,server_name,name,description,
           input_schema,annotations,is_readonly,readonly_source,override,args:{name:{mapping,why}}}],
           skills:[{name,description}], ai_tools:[{name,label,kind}], workstation:{available,why},
           limits:{foreach_max_items,wait_max_hours,parallel_steps}, operators:[{op,word}]}
    GET  /api/workflows/{id}/nodes/{node_id}/fields → {sources:[{node_id,label,kind,origin,at,fields:[{ref,path,type,example}]}]}
    GET  /api/workflows/waiting → {waiting:[{workflow_id,workflow,run_id,node_id,item,label,kind,since,until,approval}]}
    POST /api/workflows/{id}/runs/{run_id}/answer {node_id,item,approval_id,decision} → {ok,outcome,sentence}
    GET  /api/workflows/{id}/runs/{run_id}: records gain item, waiting{kind,since,until,approval}; status may be "waiting"
    refusal bodies gain field

Until the branches merge, these cases run against:

  * ``CW_FAKE_JS`` — a module written into the sandbox as `workbench/cwfake.js`:
    a fake **server** (`net`) answering the C2 routes the real
    `workflowSource.js` and `workflowApi.js` use and the C-W routes above, from
    one in-memory workflow, recording every request; and ``cwApi(net)`` — the
    REAL `createWorkflowApi` over that server, plus the four C-W functions
    written to C-W's paths and bodies (`getPalette`, `listFields(id, nodeId)`,
    `listWaiting`, `answerStep(id, runId, { nodeId, item, approvalId,
    decision })` — the browser's names, the server's body keys, as every
    function of `workflowApi.js` does). Where C-W names a function and not its
    arguments, the names chosen here are listed in `wf-canvas`'s handoff note
    as a merge point.
  * ``PALETTE`` — a palette in C-W's shape, with every kind of § 1.3, two kinds
    greyed with a reason, slots per § 2's table, one integration, two MCP tools
    (one whose `channel` is `never` and `text` is `value`), skills, AI tools.

Nothing here is the product; nothing here is copied from wf-walker's branch.
"""

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "static" / "js"

# The modules the room, the panels and the canvas reach with `../`.
UP = (
    "tasks/workflowDiagram.js", "runStatus.js", "editor/snap.js", "escMenuStack.js",
    "approvalBox.js", "skillGateNote.js", "settings/mcpFields.js",
)

_V = {"mapping": "value", "why": ""}
_WHERE = {"mapping": "never", "why": "Typed here only: it says where the result goes, so a field from another step can never fill it."}
_WHAT = {"mapping": "never", "why": "Typed here only: it says what runs, so a field from another step can never fill it."}
_WHEN = {"mapping": "never", "why": "Typed here only: it says when, so a field from another step can never fill it."}

PALETTE = {
    "kinds": [
        {"kind": "llm", "word": "Prompt", "group": "Ask a model", "hint": "Ask a model to read, write or decide something.",
         "ports": ["success", "error"], "available": True, "why": "",
         "slots": {"prompt": _V, "model": _WHAT, "output_target": _WHERE, "tools": _WHAT, "answer_fields": _WHAT}},
        {"kind": "research", "word": "Research", "group": "Ask a model", "hint": "Look something up and write a report.",
         "ports": ["success", "error"], "available": True, "why": "", "slots": {"prompt": _V, "output_target": _WHERE}},
        {"kind": "skill", "word": "Skill", "group": "Ask a model", "hint": "Follow one of your skills.",
         "ports": ["success", "error"], "available": True, "why": "", "slots": {"skill": _WHAT, "prompt": _V}},
        {"kind": "if", "word": "If", "group": "Decide and reshape", "hint": "Go one of two ways.",
         "ports": ["then", "otherwise"], "available": True, "why": "",
         "slots": {"conditions[].left": _V, "conditions[].right": _V, "conditions[].op": _WHAT, "join": _WHAT}},
        {"kind": "switch", "word": "Switch", "group": "Decide and reshape", "hint": "Go the way of the first case that holds.",
         "ports": ["otherwise"], "available": True, "why": "",
         "slots": {"cases[].conditions[].left": _V, "cases[].conditions[].right": _V, "cases[].label": _WHAT}},
        {"kind": "set", "word": "Set fields", "group": "Decide and reshape", "hint": "Name the fields the next step gets.",
         "ports": ["success"], "available": True, "why": "", "slots": {"fields[].name": _WHAT, "fields[].value": _V}},
        {"kind": "merge", "word": "Merge", "group": "Decide and reshape", "hint": "Bring branches back together.",
         "ports": ["success"], "available": True, "why": "", "slots": {"mode": _WHAT}},
        {"kind": "wait", "word": "Wait", "group": "Decide and reshape", "hint": "Hold the run, then go on.",
         "ports": ["success"], "available": True, "why": "",
         "slots": {"mode": _WHEN, "minutes": _WHEN, "time": _WHEN, "tz": _WHEN}},
        {"kind": "foreach", "word": "For each item", "group": "Decide and reshape", "hint": "Run a step for each item of a list.",
         "ports": ["success", "error"], "available": True, "why": "", "slots": {"list": _V, "on_error": _WHAT}},
        {"kind": "action", "word": "Action", "group": "Do something", "hint": "Run one of Pantheon’s built-in actions.",
         "ports": ["success", "error"], "available": True, "why": "",
         "slots": {"action": _WHAT, "prompt": _WHAT, "output_target": _WHERE}},
        {"kind": "run_task", "word": "Run task", "group": "Do something", "hint": "Run one of your tasks.",
         "ports": ["success", "error"], "available": True, "why": "", "slots": {"task_id": _WHAT}},
        {"kind": "http", "word": "HTTP request", "group": "Reach out", "hint": "Call a service you set up.",
         "ports": ["success", "error"], "available": False,
         "why": "Only an admin can add this step: it calls a service outside Pantheon, which your agent cannot do either.",
         "slots": {"integration": _WHERE, "method": _WHAT, "path": _WHERE, "query[].value": _V, "body[].value": _V}},
        {"kind": "mcp", "word": "MCP tool", "group": "Reach out", "hint": "Call a tool of an MCP server.",
         "ports": ["success", "error"], "available": True, "why": "", "slots": {"tool": _WHAT}},
        {"kind": "code", "word": "Code", "group": "Reach out", "hint": "Run your own code in your workstation.",
         "ports": ["success", "error"], "available": False,
         "why": "Your workstation is switched off. Switch it on in Settings → Workstation to run code.",
         "slots": {"language": _WHAT, "source": _WHAT, "timeout_seconds": _WHAT, "input[].name": _WHAT, "input[].value": _V}},
    ],
    "integrations": [{"id": "int1", "name": "Miniflux", "preset": "miniflux", "description": "My feed reader."}],
    "mcp_tools": [
        {"qualified_name": "mcp__chat__send_message", "server_name": "chat", "name": "send_message",
         "description": "Post a message to a channel.",
         "input_schema": {"type": "object", "required": ["channel", "text"], "properties": {
             "channel": {"type": "string", "description": "Where it goes, like #general."},
             "text": {"type": "string", "description": "What it says."},
             "silent": {"type": "boolean", "description": "Post without a ping."},
             "priority": {"type": "integer", "description": "1 to 5."},
             "mood": {"type": "string", "enum": ["calm", "loud"]},
             "meta": {"type": "object", "description": "Extra fields."}}},
         "annotations": {"readOnlyHint": False}, "is_readonly": False, "readonly_source": "annotation", "override": None,
         "args": {"channel": _WHERE, "text": _V, "priority": _WHAT, "meta": _WHAT, "silent": _WHAT, "mood": _WHAT}},
        {"qualified_name": "mcp__chat__list_channels", "server_name": "chat", "name": "list_channels",
         "description": "List channels.", "input_schema": {"type": "object", "properties": {}},
         "annotations": {"readOnlyHint": True}, "is_readonly": True, "readonly_source": "annotation", "override": None,
         "args": {}},
    ],
    "skills": [{"name": "print-queue", "description": "Print what is in the queue."}],
    "ai_tools": [{"name": "web_search", "label": "Search the web", "kind": "built-in"},
                 {"name": "web_fetch", "label": "Read a page", "kind": "built-in"},
                 {"name": "bash", "label": "Run a shell command", "kind": "built-in"}],
    "workstation": {"available": False, "why": "Your workstation is switched off. Switch it on in Settings → Workstation to run code."},
    "limits": {"foreach_max_items": 50, "wait_max_hours": 168, "parallel_steps": 4},
    "operators": [{"op": "equals", "word": "is"}, {"op": "contains", "word": "contains"},
                  {"op": "is_empty", "word": "is empty"}, {"op": "greater_than", "word": "is more than"},
                  {"op": "less_than", "word": "is less than"}, {"op": "one_of", "word": "is one of"}],
}

CW_FAKE_JS = r"""
// A server answering the C2 routes `workflowSource.js` uses and C-W's, from
// one in-memory workflow, recording every request; and the real data layer
// over it with C-W's four functions beside (see the Python module's doc).
import { createWorkflowApi, WorkflowRefusal } from './workflowApi.js';
import { readRefusal } from './refusal.js';

const clone = (v) => (v === undefined ? v : JSON.parse(JSON.stringify(v)));
export const server = {
  calls: [], doc: null, tasks: [], palette: null, fields: {}, waiting: [], runs: [], executions: {},
  check: () => null, answerReply: null, onAnswer: null, refusePalette: null,
};
const reply = (status, body) => ({
  ok: status >= 200 && status < 300, status,
  json: async () => (body === undefined ? Promise.reject(new Error('no body')) : clone(body)),
});
const routeOf = (url) => url.split('?')[0];
export async function net(url, init = {}) {
  url = String(url);
  const method = init.method || 'GET';
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined;
  server.calls.push({ method, url, body });
  const doc = server.doc;
  const path = routeOf(url);
  if (method === 'GET' && path === '/api/tasks') return reply(200, { tasks: server.tasks });
  if (method === 'GET' && path === '/api/workflows/palette') {
    if (server.refusePalette) return reply(server.refusePalette.status, { detail: server.refusePalette.detail });
    return reply(200, server.palette);
  }
  if (method === 'GET' && path === '/api/workflows/waiting') return reply(200, { waiting: server.waiting });
  if (method === 'GET' && path === '/api/workflows') return reply(200, { workflows: doc ? [summary()] : [] });
  if (!doc) return reply(404, { detail: 'No workflow in the fake.' });
  const base = `/api/workflows/${doc.id}`;
  if (method === 'GET' && path === base) return reply(200, { workflow: doc });
  if (method === 'PUT' && url === `${base}?check=true`) {
    if (body.base_version !== doc.version) return reply(409, { detail: 'Saved somewhere else.' });
    const r = server.check(body);
    return r ? reply(r.status || 400, r.body) : reply(200, { ok: true, check: true });
  }
  if (method === 'PUT' && path === base) {
    if (body.positions) return reply(200, { saved: 'positions', version: doc.version });
    if (body.pins) return reply(200, { workflow: doc, saved: 'pins', dropped: {} });
    if (body.base_version !== doc.version) return reply(409, { detail: 'Saved somewhere else since.' });
    const r = server.check(body);
    if (r) return reply(r.status || 400, r.body);
    doc.version += 1;
    doc.graph = clone(body.graph);
    if (body.name) doc.name = body.name;
    return reply(200, { workflow: doc, saved: 'new_version' });
  }
  const fields = new RegExp(`^${base}/nodes/([^/]+)/fields$`).exec(path);
  if (method === 'GET' && fields) {
    const id = decodeURIComponent(fields[1]);
    const got = server.fields[id];
    return got ? reply(200, got) : reply(404, { detail: 'That step is not in the saved workflow.' });
  }
  const answer = new RegExp(`^${base}/runs/([^/]+)/answer$`).exec(path);
  if (method === 'POST' && answer) {
    const runId = decodeURIComponent(answer[1]);
    if (typeof server.onAnswer === 'function') server.onAnswer(runId, body);
    const r = typeof server.answerReply === 'function' ? server.answerReply(runId, body) : null;
    if (r && r.status) return reply(r.status, r.body);
    return reply(200, r || { ok: true, outcome: body.decision === 'deny' ? 'denied' : 'resumed',
      sentence: body.decision === 'deny' ? 'Denied by joseph at 07:42. The step took its “if it fails” way.'
        : 'Allowed once by joseph at 07:42: send_reply. The run goes on.' });
  }
  const run = new RegExp(`^${base}/runs/([^/]+)$`).exec(path);
  if (method === 'GET' && run) {
    const got = server.executions[decodeURIComponent(run[1])];
    return got ? reply(200, got) : reply(404, { detail: 'No such run.' });
  }
  if (method === 'GET' && path === `/api/tasks/${doc.task_id}/runs`) return reply(200, { runs: server.runs, total: server.runs.length });
  if (method === 'POST' && path === `/api/tasks/${doc.task_id}/run`) return reply(200, { ok: true });
  if (method === 'POST' && path === `${base}/switch`) {
    doc.trigger_status = body.on ? 'active' : 'paused';
    return reply(200, { workflow: doc, chain_paused: null, notes: [body.on ? 'Switched on.' : 'Switched off.'] });
  }
  return reply(404, { detail: 'No such route in the fake: ' + method + ' ' + url });
}
function summary() {
  const d = server.doc;
  return { id: d.id, name: d.name, task_id: d.task_id, trigger_status: d.trigger_status, version: d.version,
    step_count: d.graph.nodes.length, last_run: null, converted_from: null };
}
export function seed(doc) { server.doc = clone(doc); }

/** C-W's four `workflowApi.js` functions, to C-W's paths and bodies. */
export function cwFunctions(fetchFn = net) {
  const enc = (v) => encodeURIComponent(String(v == null ? '' : v));
  async function call(method, url, body) {
    const init = { method, credentials: 'same-origin' };
    if (body !== undefined) { init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(body); }
    let res;
    try { res = await fetchFn(url, init); } catch (_) { throw new WorkflowRefusal(0, 'Pantheon could not be reached, so nothing changed.'); }
    if (!res || !res.ok) {
      const r = await readRefusal(res);
      throw new WorkflowRefusal(r.status, r.sentence, { reason: r.reason, nodeIds: r.nodeIds, field: r.field });
    }
    try { return await res.json(); } catch (_) { return null; }
  }
  return {
    getPalette() { return call('GET', `/api/workflows/palette`); },
    listFields(id, nodeId) { return call('GET', `/api/workflows/${enc(id)}/nodes/${enc(nodeId)}/fields`); },
    listWaiting() { return call('GET', `/api/workflows/waiting`); },
    answerStep(id, runId, { nodeId, item = null, approvalId, decision } = {}) {
      return call('POST', `/api/workflows/${enc(id)}/runs/${enc(runId)}/answer`,
        { node_id: nodeId, item, approval_id: approvalId, decision });
    },
  };
}

/** The real data layer over the fake server, with C-W's four beside it. */
export function cwApi(fetchFn = net) {
  return { ...createWorkflowApi({ fetch: fetchFn }), ...cwFunctions(fetchFn) };
}
"""


def build_sandbox(root: Path, shim: str, *, stubs: dict = None) -> Path:
    """`root/workbench` with every real Workbench module, the `../` modules
    they reach, `cwfake.js`, and `shim.js` / `dom.js`; plus a `windowDrag.js`
    stub (its two numbers) and any `stubs` (path → text, from `root`)."""
    from test_tool_effect_surfaces_js import _make_sandbox  # noqa: E402

    wb = root / "workbench"
    wb.mkdir(parents=True, exist_ok=True)
    sandbox = _make_sandbox(wb, JS / "workbench" / "canvas.js", shim, {})
    for f in (JS / "workbench").glob("*.js"):
        shutil.copy(f, wb / f.name)
    for rel in UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    (wb / "cwfake.js").write_text(CW_FAKE_JS, encoding="utf-8")
    for rel, text in (stubs or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return sandbox


def palette_json() -> str:
    return json.dumps(PALETTE)
