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

These cases ran, on `wf-canvas`' branch, against a stand-in of all of C-W.
**Since the merge (`integrate-d`) only the network is stood in:**

  * ``CW_FAKE_JS`` — a module written into the sandbox as `workbench/cwfake.js`:
    a fake **server** (`net`) answering the C2 and C-W routes the real
    `workflowSource.js` and `workflowApi.js` call, from one in-memory workflow,
    recording every request; and ``cwApi(net)`` — the REAL `createWorkflowApi`
    over that server, C-W's four functions included (`getPalette`,
    `listFields`, `listWaiting`, `answerStep`). It used to lay a second copy of
    those four over the real ones (`cwFunctions`), so the room's tests drove
    the copy; it now fails if the real module lacks one.
  * ``PALETTE`` — the REAL palette: `workflow_effects.build_palette`'s answer
    (`real_palette()`), so every kind's word, group, hint, ports, slots and
    their reasons, the MCP arguments' mappings and the operators are the
    server's. Only the person's environment is supplied — one Integration, two
    MCP tools, a skill, three AI tools, the workstation switched off — because
    the real readers of those reach a data directory, an MCP manager and a
    skills store. It used to be hand-written, and said HTTP query and body
    values were `value` where the server says `never` (`classify_argument` is
    per entry name), and "Set" was "Set fields".

The route answers the fake server gives (a fields list, a waiting list, an
answer's sentence) are each test's own data; the real routes are driven by
the Python route tests and the merged drive.

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
    "approvalBox.js", "skillGateNote.js", "settings/mcpFields.js", "toolWindowZOrder.js",
)

# The person's environment — what the real readers would find in a data
# directory, an MCP manager and a skills store. Everything else in the palette
# is `build_palette`'s own answer.
ENV_INTEGRATIONS = [{"id": "int1", "name": "Miniflux", "preset": "miniflux",
                     "description": "My feed reader.", "enabled": True}]
ENV_MCP_TOOLS = [
    {"qualified_name": "mcp__chat__send_message", "server_name": "chat", "name": "send_message",
     "description": "Post a message to a channel.",
     "input_schema": {"type": "object", "required": ["channel", "text"], "properties": {
         "channel": {"type": "string", "description": "Where it goes, like #general."},
         "text": {"type": "string", "description": "What it says."},
         "silent": {"type": "boolean", "description": "Post without a ping."},
         "priority": {"type": "integer", "description": "1 to 5."},
         "mood": {"type": "string", "enum": ["calm", "loud"]},
         "meta": {"type": "object", "description": "Extra fields."}}},
     "annotations": {"readOnlyHint": False}, "is_readonly": False, "readonly_source": "annotation",
     "override": None, "is_disabled": False},
    {"qualified_name": "mcp__chat__list_channels", "server_name": "chat", "name": "list_channels",
     "description": "List channels.", "input_schema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True}, "is_readonly": True, "readonly_source": "annotation",
     "override": None, "is_disabled": False},
]
ENV_SKILLS = [{"name": "print-queue", "description": "Print what is in the queue."}]
ENV_AI_TOOLS = [{"name": "web_search", "label": "Search the web", "kind": "builtin"},
                {"name": "web_fetch", "label": "Read a page", "kind": "builtin"},
                {"name": "bash", "label": "Run a shell command", "kind": "builtin"}]


def real_palette(*, admin: bool = True, workstation_why=None) -> dict:
    """`workflow_effects.build_palette` — the server's palette — for a person
    whose agent reaches what an admin's does (`admin=False`: the non-admin
    policy, so HTTP and MCP are greyed with the server's sentence), in the
    environment above. The workstation is switched off unless
    `workstation_why` says otherwise (`""` for on)."""
    from unittest import mock

    from src import workflow_effects as we
    from src.workstation_access import OFF_SENTENCE

    why = OFF_SENTENCE if workstation_why is None else (workstation_why or None)
    with mock.patch.object(we, "_reaches", lambda owner, tool: admin), \
            mock.patch.object(we, "_integrations",
                              lambda owner: [dict(i) for i in ENV_INTEGRATIONS] if admin else []), \
            mock.patch.object(we, "_mcp_tools", lambda: [dict(t) for t in ENV_MCP_TOOLS]), \
            mock.patch.object(we, "global_disabled_tools", lambda: set()), \
            mock.patch.object(we, "_own_skills", lambda owner: [dict(x) for x in ENV_SKILLS]), \
            mock.patch.object(we, "workstation_why", lambda owner: why), \
            mock.patch.object(we, "ai_tool_choices", lambda owner: [dict(t) for t in ENV_AI_TOOLS]):
        return json.loads(json.dumps(we.build_palette("rowan")))


PALETTE = real_palette()

CW_FAKE_JS = r"""
// A server answering the C2 routes `workflowSource.js` uses and C-W's, from
// one in-memory workflow, recording every request; and the real data layer
// over it with C-W's four functions beside (see the Python module's doc).
import { createWorkflowApi } from './workflowApi.js';

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

/** The real data layer over the fake server — C-W's four functions are the
 *  real module's (`integrate-d`: this laid its own copies over them). */
export function cwApi(fetchFn = net) {
  const api = createWorkflowApi({ fetch: fetchFn });
  for (const name of ['getPalette', 'listFields', 'listWaiting', 'answerStep']) {
    if (typeof api[name] !== 'function') throw new Error(`workflowApi.js has no ${name}: a C-W half is missing`);
  }
  return api;
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


def palette_json(**kw) -> str:
    """The real palette as JSON (`real_palette`)."""
    return json.dumps(real_palette(**kw) if kw else PALETTE)
