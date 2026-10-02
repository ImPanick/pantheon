# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-19`, `P22-20`, `P22-24` (wb-canvas-e) — contract C-A, faked in its exact shapes, for the browser half.

The Workbench's Slice E surfaces (package B of `/work/notes/SLICE-EF-DESIGN.md`
§ 3) consume contract **C-A** — the workflow routes `wb-assist` (package A)
builds on its own branch at the same time, and the five functions it adds to
`workflowApi.js`:

    POST /api/workflows {describe, tz?} | {file}   → {workflow: Doc, notes:[str], missing:[str], destinations:[str]}
    PUT  /api/workflows/{id} {checked:[node_id]}   → {workflow, saved:"checked"}            (403 unless a person)
    POST /api/workflows/{id}/switch {on:true}      → 409 {detail, reason:"unchecked", node_ids} while marks remain
    GET  /api/workflows/{id}/export                → attachment, pantheon_workflow:1
    POST /api/workflows/{id}/runs/{run_id}/explain {node_id, item} → {why, model, changed_since_run,
            proposal:{base_version, node_id, item, config, changes:[{field, words, before, after, where, from_run}]}|null,
            left_out:[str]}
    POST /api/workflows/{id}/nodes/{node_id}/fix {base_version, config} → {workflow, saved, undo_version}  (403 unless a person)
    Doc.graph.nodes[].unchecked: null | {origin:"drafted"|"imported", at, needs:[{field, name, preset?, server?, tool?}]}
    version.source ∈ user|converted|restored|drafted|imported|fixed

    JS: createWorkflow({name, fromTaskId, describe, tz, file}), checkSteps(id, nodeIds), exportWorkflow(id) (a blob),
        explainStep(id, runId, {nodeId, item}), fixStep(id, nodeId, {config, baseVersion})

**Measured when these cases were written:** `wb-assist`'s branch had no commit
past the wave's base (`4cfb297`) and nothing in its worktree, so its routes
could not be called to record their replies — the move Slice D's `real_palette`
made. The replies here are therefore C-A's LITERAL shapes (the design's own
sentences where it gives one), and every value the server would compute that a
real function here can compute is that function's: the palette is
`workflow_effects.build_palette`'s (`helpers.workflow_cw_fake.real_palette`),
and a step's dry-run plan is `workflow_document.plan_lines`' answer.

Two keys C-A does not name, said so where they are used: the palette's
`examples` (`D-2026-10-02-02` §1's example sentences, "served by wb-assist";
read from the palette — merge point) and `exportWorkflow`'s answer (a `Blob`,
or `{ blob, filename }`; both are read).

  * ``CA_FAKE_JS`` — `workbench/cafake.js`: a fake **server** (`net`) answering
    C-A's routes from the C-W fake's one in-memory workflow (`cwfake.js`'s
    `server`, so the C2 and C-W routes still answer as they do there), every
    request recorded; and ``caApi(net)`` — the REAL `createWorkflowApi` with
    C-A's five functions. **While the real module lacks them** (this branch,
    before `wb-assist` merges) the five are laid beside it, written to C-A's
    literal paths and bodies — `createWorkflow` included, because the real one
    drops `describe`, `tz` and `file`. **Once the real module has
    `checkSteps`, every one of the five must be real** (it throws otherwise),
    and these cases drive A's code with no copy in between — integrate-d's
    lesson about `cwFunctions`. At the merge, delete the stand-ins.

Nothing here is the product; nothing here is copied from wb-assist's branch.
"""

from __future__ import annotations

import json
from pathlib import Path

from helpers.workflow_cw_fake import build_sandbox as _cw_sandbox, real_palette

CA_FUNCTIONS = ("createWorkflow", "checkSteps", "exportWorkflow", "explainStep", "fixStep")

# `D-2026-10-02-02` §1: at most six example sentences. Seven here, so the
# browser's cap is what is measured. (The palette key is a merge point.)
EXAMPLES = [
    "When a GitHub webhook says an issue opened, summarise it and post it to my chat server",
    "When mail arrives from my bank, summarise it and post it to my chat server",
    "Every morning at 8, summarise my unread mail and send it to me",
    "Every Friday at 5, list what my tasks did this week",
    "When a document is saved, check its spelling and tell me what changed",
    "Every hour, fetch my unread feed entries and post the titles to #news",
    "A seventh sentence the browser never offers",
]


def palette(**kw) -> dict:
    """The real palette (`build_palette`), with C-A's example sentences."""
    p = real_palette(**kw)
    p["examples"] = list(EXAMPLES)
    return p


def plan_of(node: dict) -> list:
    """What the dry run says of `node`: the real planner (`plan_lines`)."""
    from src import workflow_document as wd

    return list(wd.plan_lines(node))


CA_FAKE_JS = r"""
// C-A's routes over the C-W fake's one workflow, recording every request; and
// the real data layer with C-A's five functions (see the Python module's doc).
import { server, net as cwNet, seed } from './cwfake.js';
import { createWorkflowApi, WorkflowRefusal } from './workflowApi.js';
import { readRefusal } from './refusal.js';

const clone = (v) => (v === undefined ? v : JSON.parse(JSON.stringify(v)));
export const ca = {
  calls: [],                           // every request, in order
  draft: null, importFile: null,      // (body) → { status, body }
  checkRefusal: null,                  // { status, detail }
  switchRefusal: null,                 // the 409 body while marks remain (recorded or literal)
  exportRefusal: null, exportBody: null,
  explain: null, fix: null,            // (body, nodeId) → { status, body } | null for the default
  dryNodes: {},                        // node_id → [plan line]
  versions: [], graphs: {},            // the Versions list; a version's graph, for a restore
};
const reply = (status, body, blob) => ({
  ok: status >= 200 && status < 300, status,
  json: async () => (body === undefined ? Promise.reject(new Error('no body')) : clone(body)),
  blob: async () => blob,
});
const marked = () => (server.doc ? server.doc.graph.nodes.filter((n) => n.unchecked).map((n) => n.id) : []);
function pushVersion(source) {
  const d = server.doc;
  for (const v of ca.versions) v.current = false;
  ca.versions.unshift({ version: d.version, name: d.name, saved_at: '2026-10-02T09:00:00Z', source,
    step_count: d.graph.nodes.length, current: true });
  ca.graphs[d.version] = clone(d.graph);
}

export async function net(url, init = {}) {
  url = String(url);
  const method = init.method || 'GET';
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined;
  const path = url.split('?')[0];
  // Every request is in `ca.calls`; one answered here is in the C-W fake's
  // `server.calls` too (one it hands on is put there by `cwNet`).
  ca.calls.push({ method, url, body });
  const note = () => { server.calls.push({ method, url, body }); };
  if (method === 'POST' && path === '/api/workflows' && body && (body.describe !== undefined || body.file !== undefined)) {
    note();
    const fn = body.file !== undefined ? ca.importFile : ca.draft;
    const r = typeof fn === 'function' ? fn(body) : { status: 404, body: { detail: 'No answer in the fake.' } };
    if (r.status >= 200 && r.status < 300 && r.body && r.body.workflow) {
      seed(r.body.workflow);
      ca.versions = [];
      pushVersion(body.file !== undefined ? 'imported' : 'drafted');
    }
    return reply(r.status, r.body);
  }
  const doc = server.doc;
  if (!doc) return cwNet(url, init);
  const base = `/api/workflows/${doc.id}`;
  if (method === 'PUT' && path === base && body && Array.isArray(body.checked)) {
    note();
    if (ca.checkRefusal) return reply(ca.checkRefusal.status, { detail: ca.checkRefusal.detail });
    for (const n of doc.graph.nodes) if (body.checked.includes(n.id)) n.unchecked = null;
    return reply(200, { workflow: doc, saved: 'checked' });
  }
  if (method === 'POST' && path === `${base}/switch` && body && body.on && marked().length) {
    note();
    // The recorded (or literal) refusal, while any mark remains.
    if (ca.switchRefusal) return reply(409, ca.switchRefusal);
    const ids = marked();
    const names = doc.graph.nodes.filter((n) => ids.includes(n.id)).map((n) => `“${n.label}”`).join(', ');
    return reply(409, { detail: `${ids.length} steps were drafted by the model and nobody has checked them yet: `
      + `${names}. Open each one and press Looks right (or change it), then switch it on.`,
      reason: 'unchecked', node_ids: ids });
  }
  if (method === 'GET' && path === `${base}/export`) {
    note();
    if (ca.exportRefusal) return reply(ca.exportRefusal.status, { detail: ca.exportRefusal.detail });
    const file = ca.exportBody || { pantheon_workflow: 1, name: doc.name, graph: { nodes: [], edges: [] } };
    return reply(200, undefined, new Blob([JSON.stringify(file)], { type: 'application/json' }));
  }
  const explain = new RegExp(`^${base}/runs/([^/]+)/explain$`).exec(path);
  if (method === 'POST' && explain) {
    note();
    const r = typeof ca.explain === 'function' ? ca.explain(body, decodeURIComponent(explain[1])) : null;
    return r ? reply(r.status, r.body) : reply(404, { detail: 'No answer in the fake.' });
  }
  const fix = new RegExp(`^${base}/nodes/([^/]+)/fix$`).exec(path);
  if (method === 'POST' && fix) {
    note();
    const nodeId = decodeURIComponent(fix[1]);
    const r = typeof ca.fix === 'function' ? ca.fix(body, nodeId) : null;
    if (r) return reply(r.status, r.body);
    if (body.base_version !== doc.version) return reply(409, { detail: 'This workflow was saved somewhere else since. Nothing was applied.' });
    const n = doc.graph.nodes.find((x) => x.id === nodeId);
    n.config = clone(body.config);
    doc.version += 1;
    pushVersion('fixed');
    return reply(200, { workflow: doc, saved: 'new_version', undo_version: body.base_version });
  }
  if (method === 'GET' && path === `${base}/versions`) { note(); return reply(200, { versions: ca.versions }); }
  const restore = new RegExp(`^${base}/versions/([^/]+)/restore$`).exec(path);
  if (method === 'POST' && restore) {
    note();
    const v = Number(decodeURIComponent(restore[1]));
    if (body.base_version !== doc.version) return reply(409, { detail: 'Saved somewhere else since.' });
    if (ca.graphs[v]) doc.graph = clone(ca.graphs[v]);
    doc.version += 1;
    pushVersion('restored');
    return reply(200, { workflow: doc, saved: 'new_version' });
  }
  if (method === 'POST' && url === `/api/tasks/${doc.task_id}/run?dry=true`) {
    note();
    return reply(200, { ok: true, dry: true, run: { id: 'dry' + ca.calls.length },
      nodes: Object.entries(ca.dryNodes).map(([node_id, lines], i) => ({ node_id, kind: '', name: node_id,
        when: null, depth: i, declined: null, steps: lines.map((detail) => ({ kind: 'dry-run', detail })) })) });
  }
  return cwNet(url, init);
}

export const CA_FUNCTIONS = ['createWorkflow', 'checkSteps', 'exportWorkflow', 'explainStep', 'fixStep'];

/** The real data layer over the fake server, with C-A's five functions: the
 *  real module's once it has them, a stand-in written to C-A's literal paths
 *  and bodies until then (see the Python module's doc). */
export function caApi(fetchFn = net) {
  const api = createWorkflowApi({ fetch: fetchFn });
  if (typeof api.checkSteps === 'function') {
    for (const name of CA_FUNCTIONS) {
      if (typeof api[name] !== 'function') throw new Error(`workflowApi.js has no ${name}: a C-A half is missing`);
    }
    api.__caReal = true;
    return api;
  }
  const enc = (value) => encodeURIComponent(String(value == null ? '' : value));
  const given = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined));
  async function call(method, url, body, { raw = false } = {}) {
    const init = { method, credentials: 'same-origin' };
    if (body !== undefined) { init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(body); }
    let res;
    try { res = await fetchFn(url, init); } catch (_) { throw new WorkflowRefusal(0, 'Pantheon could not be reached, so nothing changed.'); }
    if (!res || !res.ok) {
      const r = await readRefusal(res);
      throw new WorkflowRefusal(r.status, r.sentence, { reason: r.reason, nodeIds: r.nodeIds, field: r.field });
    }
    if (raw) return res.blob();
    try { return await res.json(); } catch (_) { return null; }
  }
  api.createWorkflow = ({ name, fromTaskId, describe, tz, file } = {}) =>
    call('POST', `/api/workflows`, given({ name, from_task_id: fromTaskId, describe, tz, file }));
  api.checkSteps = (id, nodeIds) => call('PUT', `/api/workflows/${enc(id)}`, { checked: nodeIds });
  api.exportWorkflow = (id) => call('GET', `/api/workflows/${enc(id)}/export`, undefined, { raw: true });
  api.explainStep = (id, runId, { nodeId, item = null } = {}) =>
    call('POST', `/api/workflows/${enc(id)}/runs/${enc(runId)}/explain`, { node_id: nodeId, item: item == null ? null : item });
  api.fixStep = (id, nodeId, { config, baseVersion } = {}) =>
    call('POST', `/api/workflows/${enc(id)}/nodes/${enc(nodeId)}/fix`, { base_version: baseVersion, config });
  api.__caReal = false;
  return api;
}
"""

# What every Slice E case adds to the canvas shim: a click a download can make,
# the object URLs it makes and takes back, and a stand-in for `workbench.js`'s
# door (C-R's `openWorkbench({ room })`, wb-rooms' — stubbed until it merges).
SHIM_EXTRA = r"""
export const downloads = { made: [], revoked: [], clicked: [] };
Node.prototype.click = function click() {
  downloads.clicked.push({ tag: this.tagName, download: this.download, href: this.href });
  if (typeof this.onclick === 'function') this.onclick();
};
const realCreate = URL.createObjectURL.bind(URL);
URL.createObjectURL = (blob) => { const u = realCreate(blob); downloads.made.push({ url: u, blob }); return u; };
URL.revokeObjectURL = (u) => { downloads.revoked.push(u); };
export const doors = { opened: [] };
export const loadWorkbench = async () => ({ openWorkbench: (o) => { doors.opened.push(o); return true; } });
"""


def build_sandbox(root: Path, shim: str) -> Path:
    """The C-W sandbox (every real Workbench module, the `../` modules they
    reach, `cwfake.js`) plus `cafake.js`."""
    sandbox = _cw_sandbox(root, shim + SHIM_EXTRA)
    (sandbox / "cafake.js").write_text(CA_FAKE_JS, encoding="utf-8")
    return sandbox


def as_js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


# The room as a person meets it: the real room, canvas, panels, source and
# data layer over the C-A fake server; the task form is the `P22` panel
# contract recorded (its modes are driven in their own tests); C-R's door is
# `loadWorkbench`'s stand-in (wb-rooms').
ROOM_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup, downloads, doors, loadWorkbench } from './shim.js';\n"
    "import { server as cw, seed } from './cwfake.js';\n"
    "import { ca, net as canet, caApi } from './cafake.js';\n"
    "const { mountAutomations } = await import('./workflowRoom.js');\n"
    "const { createWorkflowSource } = await import('./workflowSource.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const by = (root, cls) => root.querySelector('.' + cls);\n"
    "const all = (root, cls) => root.querySelectorAll('.' + cls);\n"
    "const shown = (n) => { for (let x = n; x; x = x.parentNode) if (x.hidden) return false; return true; };\n"
    "const sayOf = (root) => { const s = root.querySelectorAll('.wb-say-text').filter(shown);\n"
    "  return s.length ? s[s.length - 1].textContent : root.querySelector('.wf-say-text').textContent; };\n"
    "const sayButton = (root) => { const b = root.querySelectorAll('.wb-say-action').filter((x) => !x.hidden && shown(x));\n"
    "  return b.length ? b[b.length - 1] : null; };\n"
    "const nodeEl = (root, id) => root.querySelectorAll('.wb-node').find((n) => n.dataset.itemId === id) || null;\n"
    "const steps = (root) => root.querySelector('.wf-edit').querySelectorAll('.wb-node')\n"
    "  .filter((n) => n.dataset.itemId && n.dataset.itemId !== '__start__');\n"
    "const typed = (el, value) => { el.value = value;\n"
    "  el.dispatchEvent({ type: 'input', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const mountTaskFields = () => ({ destroy() {} });\n"
    "const room = async (o = {}) => {\n"
    "  const r = host();\n"
    "  const handle = mountAutomations(r, { fetch: canet, mountTaskFields, describeTrigger: () => 'On a webhook',\n"
    "    loadWorkbench,\n"
    "    loadWorkflowModules: async () => ({ createWorkflowApi: () => caApi(canet), createWorkflowSource }), ...o });\n"
    "  await handle.ready; await settle(10);\n"
    "  return { r, handle };\n"
    "};\n"
    "const calls = (method, pred = () => true) => ca.calls.filter((c) => c.method === method && pred(c.url))\n"
    "  .map((c) => [c.url, c.body]);\n"
)


# ── `P22-19`: the drafter's replies, recorded from wb-assist's routes ───────
# Where `wb-assist`'s drafter is in the tree (`src.workflow_assist.draft_workflow`
# and its harness, `tests/helpers/assist_harness.py`), the replies the browser
# is handed are RECORDED from its real routes — the create door with
# `{describe}` (a scripted model answering the draft below), the switch's 409
# while marks remain, and the palette's example sentences — on a real SQLite
# file, as a person's browser asks (`assist_harness.PERSON`). Where it is not
# (this branch alone), they are C-A's literal shapes. A tree that HAS the
# drafter records or fails: a recording that breaks is not papered over with
# the literal shape. Slice D's `real_palette` move (`integrate-d`).

def drafter_present() -> bool:
    try:
        from src import workflow_assist  # noqa: F401
        from tests.helpers import assist_harness  # noqa: F401
    except Exception:
        return False
    return hasattr(workflow_assist, "draft_workflow") and hasattr(workflow_assist, "EXAMPLE_SENTENCES")


def literal_switch_refusal(doc: dict) -> dict:
    """C-A's 409 while marks remain, with the design's sentence (§ 1.1)."""
    marked = [n for n in doc["graph"]["nodes"] if n.get("unchecked")]
    names = ", ".join(f"“{n['label']}”" for n in marked)
    return {"detail": f"{len(marked)} steps were drafted by the model and nobody has checked them yet: {names}. "
                      f"Open each one and press Looks right (or change it), then switch it on.",
            "reason": "unchecked", "node_ids": [n["id"] for n in marked]}


def recorded_draft(tmp_path: Path, doc: dict, *, describe: str, notes, missing, destinations) -> dict:
    """`{source, examples, reply, switch_refusal}` — recorded from the real
    routes when the drafter is in the tree, else C-A's literal shapes built
    from `doc`. The scripted model answers `doc`'s steps and arrows (the
    start's implied entry is the one step nothing leads to)."""
    if not drafter_present():
        return {"source": "literal", "examples": list(EXAMPLES),
                "reply": {"workflow": doc, "notes": list(notes), "missing": list(missing),
                          "destinations": list(destinations)},
                "switch_refusal": literal_switch_refusal(doc)}
    import asyncio

    import pytest

    from src import workflow_assist as wa
    from tests.helpers.assist_harness import PERSON, build_world, miniflux, script_model
    from tests.helpers.walker_harness import client_for

    answer = {
        "name": doc["name"],
        "trigger": {"type": (doc.get("trigger_task") or {}).get("trigger_type") or "webhook"},
        "steps": [{"id": n["id"], "kind": n["kind"], "label": n["label"], "config": n["config"]}
                  for n in doc["graph"]["nodes"]],
        "arrows": [{"from": e["from"], "port": e["port"], "to": e["to"]}
                   for e in doc["graph"]["edges"] if e["from"] != "start"],
        "missing": list(missing),
    }

    async def record(w):
        async with client_for(w.app) as client:
            made = await client.post("/api/workflows", headers=PERSON, json={"describe": describe, "tz": "UTC"})
            assert made.status_code == 200, made.text
            reply = made.json()
            wid = reply["workflow"]["id"]
            refused = await client.post(f"/api/workflows/{wid}/switch", headers=PERSON, json={"on": True})
            assert refused.status_code == 409, refused.text
            palette_reply = await client.get("/api/workflows/palette", headers=PERSON)
            assert palette_reply.status_code == 200, palette_reply.text
            return reply, refused.json(), palette_reply.json().get("examples")

    with pytest.MonkeyPatch.context() as mp:
        w = build_world(mp, tmp_path, integrations=[miniflux()])
        script_model(mp, answer)
        reply, refusal, examples = asyncio.run(record(w))
    assert list(examples) == list(wa.EXAMPLE_SENTENCES)
    return {"source": "recorded", "examples": list(examples), "reply": reply, "switch_refusal": refusal}
