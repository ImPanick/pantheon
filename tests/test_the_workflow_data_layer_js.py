# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05`…`P22-08`, the browser's data layer — `workflowApi.js`,
`refusal.js` and `workflowSource.js` (contract `C3`,
`/work/notes/SLICE-B-DESIGN.md` § 7), driven under node.

**Measured before this file, on `5654cd4`:** none of the three modules existed;
the Workbench could draw only tasks (`canvas.js` held its task I/O inline) and
had no way to reach a workflow document.

What is driven:

  * `workflowApi.js` — every function's method, URL and body, as the server
    reads them (`C2`); a refusal arrives as a `WorkflowRefusal` carrying the
    server's own sentence, word for word, and for a document the engine
    refused its `reason` and the steps it names.
  * `refusal.js` — the one reading of a refusal, the same as `canvas.js`'s
    (which moves to it, design § 6.3).
  * `workflowSource.js` — the canvas source over a document: what `load()`
    draws (the start as a fixed step, its arrow into the first step, marks,
    ports), and its **draft semantics**: an arrow, a new step, a change or a
    removal edits the draft only; the server is asked whether an arrow is
    allowed (`?check=true`, writes nothing) and an arrow is refused only when
    it is the problem; Save writes the draft with the version it started
    from, and a 409 keeps the draft; positions and pins save themselves and
    never mark the draft changed; a run is drawn read-only with each step's
    outcome and the step it failed on; an old version is looked at
    read-only. The fake server answers in `C2`'s shapes and records every
    request, so each case says what went over the wire.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

SOURCE_JS = JS / "workbench" / "workflowSource.js"
_UP = ("tasks/workflowDiagram.js", "runStatus.js")
_CANVAS_UP = ("editor/snap.js", "escMenuStack.js",
              # `P22-09`…`P22-18` (wf-canvas): the panels' step forms reach these with `../`.
              "approvalBox.js", "skillGateNote.js", "settings/mcpFields.js")

_SHIM = r"""
// A server answering the workflow routes in `C2`'s shapes, recording every
// request. `server.check(body)` decides a `?check=true` (null = fine).
const clone = (v) => JSON.parse(JSON.stringify(v));
export const server = {
  calls: [], check: () => null, tasks: [], plan: [], execution: null, versions: [],
  doc: null, testReply: { outcome: 'ran', status: 'success', text: 'ok' },
};
const reply = (status, body) => ({
  ok: status >= 200 && status < 300, status,
  json: async () => (body === undefined ? Promise.reject(new Error('no body')) : clone(body)),
});
export function seed(doc) { server.doc = clone(doc); }
export async function net(url, init = {}) {
  url = String(url);
  const method = init.method || 'GET';
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined;
  server.calls.push({ method, url, body });
  const doc = server.doc;
  if (method === 'GET' && url === '/api/tasks') return reply(200, { tasks: server.tasks });
  if (method === 'GET' && url === `/api/workflows/${doc.id}`) return reply(200, { workflow: doc });
  if (method === 'PUT' && url === `/api/workflows/${doc.id}?check=true`) {
    if (body.base_version !== doc.version) return reply(409, { detail: 'Saved somewhere else.' });
    const r = server.check(body);
    return r ? reply(r.status || 400, r.body) : reply(200, { ok: true, check: true });
  }
  if (method === 'PUT' && url === `/api/workflows/${doc.id}`) {
    if (body.positions) {
      for (const n of doc.graph.nodes) if (n.id in body.positions) n.position = body.positions[n.id];
      if ('start' in body.positions) doc.graph.start.position = body.positions.start;
      return reply(200, { saved: 'positions', version: doc.version });
    }
    if (body.pins) {
      const dropped = {};
      for (const [id, data] of Object.entries(body.pins)) {
        const n = doc.graph.nodes.find((x) => x.id === id);
        n.pinned = data ? { source: 'task', data } : null;
        dropped[id] = data && data.colour ? ['colour'] : [];
      }
      return reply(200, { workflow: doc, saved: 'pins', dropped });
    }
    if (body.base_version !== doc.version) return reply(409, { detail: 'Saved somewhere else since.' });
    const r = server.check(body);
    if (r) return reply(r.status || 400, r.body);
    doc.version += 1;
    doc.graph = clone(body.graph);
    if (body.name) doc.name = body.name;
    return reply(200, { workflow: doc, saved: 'new_version' });
  }
  if (method === 'POST' && url === `/api/tasks/${doc.task_id}/run?dry=true`) {
    return reply(200, { ok: true, dry: true, run_id: 'dry1', run: { id: 'dry1' }, nodes: server.plan });
  }
  if (method === 'POST' && url === `/api/tasks/${doc.task_id}/run`) return reply(200, { ok: true });
  if (method === 'POST' && url === `/api/workflows/${doc.id}/switch`) {
    doc.trigger_status = body.on ? 'active' : 'paused';
    return reply(200, { workflow: doc, chain_paused: null, notes: [body.on ? 'Switched on.' : 'Switched off.'] });
  }
  if (method === 'GET' && url === `/api/workflows/${doc.id}/versions`) return reply(200, { versions: server.versions });
  const v = /^\/api\/workflows\/[^/]+\/versions\/(\d+)$/.exec(url);
  if (method === 'GET' && v) {
    const found = server.versions.find((x) => x.version === Number(v[1]));
    return found ? reply(200, found) : reply(404, { detail: 'No such version.' });
  }
  const r = /^\/api\/workflows\/[^/]+\/versions\/(\d+)\/restore$/.exec(url);
  if (method === 'POST' && r) {
    doc.version += 1;
    return reply(200, { workflow: doc, saved: 'new_version' });
  }
  if (method === 'GET' && url.startsWith(`/api/workflows/${doc.id}/runs/`)) return reply(200, server.execution);
  if (method === 'POST' && /\/nodes\/[^/]+\/test$/.test(url)) return reply(200, server.testReply);
  return reply(404, { detail: 'No such route in the fake: ' + method + ' ' + url });
}
"""

_PREAMBLE = (
    "import { server, net, seed } from './shim.js';\n"
    "const { createWorkflowApi, WorkflowRefusal } = await import('./workbench/workflowApi.js');\n"
    "const { createWorkflowSource, START_ID, contentOf } = await import('./workbench/workflowSource.js');\n"
    "const { refusalText, readRefusal } = await import('./workbench/refusal.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const api = createWorkflowApi({ fetch: net });\n"
    "const sent = () => server.calls.map((c) => [c.method, c.url, c.body === undefined ? null : c.body]);\n"
    "const node = (id, kind = 'llm', label = id.toUpperCase(), config = { prompt: 'Do ' + id }) =>\n"
    "  ({ id, kind, label, config, position: null, pinned: null });\n"
    "const DOC = { id: 'wf1', name: 'Morning digest', task_id: 't1', trigger_status: 'paused', version: 2,\n"
    "  trigger_task: { id: 't1', task_type: 'workflow', schedule: 'daily', scheduled_time: '08:00', status: 'paused' },\n"
    "  graph: { v: 1, start: { position: null },\n"
    "    nodes: [node('n1', 'llm', 'Summarise my inbox'), node('n2', 'llm', 'Send me the summary')],\n"
    "    edges: [{ from: 'n1', port: 'success', to: 'n2' }] } };\n"
    "const source = (extra = {}) => createWorkflowSource({ api, workflowId: 'wf1',\n"
    "  describeTrigger: (t) => 'Every day at ' + t.scheduled_time, ...extra });\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("wfdata")
    (root / "workbench").mkdir()
    _make_sandbox(root / "workbench", SOURCE_JS, _SHIM, {})
    shutil.move(str(root / "workbench" / "shim.js"), str(root / "shim.js"))
    shutil.move(str(root / "workbench" / "dom.js"), str(root / "dom.js"))
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    # The canvas too, whole, so its `refusalText` can be read beside this one
    # (the canvas tests' own set of climbing imports, and their windowDrag stub).
    for f in (JS / "workbench").glob("*.js"):
        shutil.copy(f, root / "workbench" / f.name)
    for rel in _CANVAS_UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    return root


def _case(box, script, doc=True):
    return _run(box, _PREAMBLE + ("seed(DOC);\n" if doc else ""), script)


# ── workflowApi.js: every route, its method, URL and body ───────────────────

def test_every_function_sends_its_routes_method_url_and_body(box):
    # The fake answers only a seeded document; seed one whose id is the odd one.
    o = _run(box, _PREAMBLE + "seed({ ...DOC, id: 'w 1/x' });\n", """
        const id = 'w 1/x';
        const calls = [
          () => api.listWorkflows(),
          () => api.createWorkflow({ name: 'A' }),
          () => api.createWorkflow({ fromTaskId: 't9' }),
          () => api.getWorkflow(id),
          () => api.saveWorkflow(id, { name: 'B', graph: { nodes: [] }, baseVersion: 3 }),
          () => api.checkWorkflow(id, { graph: { nodes: [] }, baseVersion: 3 }),
          () => api.savePositions(id, { n1: [1, 2], start: null }),
          () => api.savePins(id, { n1: { a: 1 } }),
          () => api.deleteWorkflow(id),
          () => api.listVersions(id),
          () => api.getVersion(id, 4),
          () => api.restoreVersion(id, 4, 7),
          () => api.switchWorkflow(id, 1),
          () => api.restoreChain(id),
          () => api.getExecution(id, 'r/1'),
          () => api.listExecutions('t1', { limit: 5 }),
          () => api.runWorkflow('t1'),
          () => api.runWorkflow('t1', { dry: true }),
          () => api.testNode(id, 'n1', { node: { id: 'n1' }, source: 'pinned' }),
          () => api.listTasks(),
        ];
        for (const c of calls) { try { await c(); } catch (_) {} }
        out(sent());
    """)
    w = "/api/workflows/w%201%2Fx"
    assert o == [
        ["GET", "/api/workflows", None],
        ["POST", "/api/workflows", {"name": "A"}],
        ["POST", "/api/workflows", {"from_task_id": "t9"}],
        ["GET", w, None],
        ["PUT", w, {"name": "B", "graph": {"nodes": []}, "base_version": 3}],
        ["PUT", w + "?check=true", {"graph": {"nodes": []}, "base_version": 3}],
        ["PUT", w, {"positions": {"n1": [1, 2], "start": None}}],
        ["PUT", w, {"pins": {"n1": {"a": 1}}}],
        ["DELETE", w, None],
        ["GET", w + "/versions", None],
        ["GET", w + "/versions/4", None],
        ["POST", w + "/versions/4/restore", {"base_version": 7}],
        ["POST", w + "/switch", {"on": True}],
        ["POST", w + "/restore-chain", None],
        ["GET", w + "/runs/r%2F1", None],
        ["GET", "/api/tasks/t1/runs?limit=5", None],
        ["POST", "/api/tasks/t1/run", None],
        ["POST", "/api/tasks/t1/run?dry=true", None],
        ["POST", w + "/nodes/n1/test", {"node": {"id": "n1"}, "source": "pinned", "confirm": False}],
        ["GET", "/api/tasks", None],
    ]


def test_a_refusal_is_the_servers_sentence_with_its_reason_and_steps(box):
    o = _case(box, """
        const answers = [
          [400, { detail: 'These steps would run in a circle.', reason: 'cycle', node_ids: ['n1', 'n2'] }],
          [409, { detail: 'Saved somewhere else.' }],
          [422, { detail: [{ msg: 'field required' }, { msg: 'too long' }] }],
          [502, undefined],
        ];
        const seen = [];
        for (const [status, body] of answers) {
          const a = createWorkflowApi({ fetch: async () => ({ ok: false, status,
            json: async () => (body === undefined ? Promise.reject(new Error('html')) : body) }) });
          try { await a.getWorkflow('x'); seen.push('no throw'); }
          catch (e) { seen.push([e instanceof WorkflowRefusal, e.status, e.sentence, e.reason, e.nodeIds]); }
        }
        const down = createWorkflowApi({ fetch: async () => { throw new TypeError('Failed to fetch'); } });
        try { await down.listWorkflows(); } catch (e) { seen.push([e.status, e.sentence]); }
        out(seen);
    """)
    assert o == [
        [True, 400, "These steps would run in a circle.", "cycle", ["n1", "n2"]],
        [True, 409, "Saved somewhere else.", None, []],
        [True, 422, "field required too long", None, []],
        [True, 502, "The server refused (502).", None, []],
        [0, "Pantheon could not be reached, so nothing changed."],
    ]


def test_refusal_reads_a_refusal_exactly_as_the_canvas_did(box):
    """`refusalText` moves out of `canvas.js` (design § 6.3). Since the wave C
    merge the canvas and the tasks source import it from here, so the canvas's
    (and `taskSource.js`'s) export IS this function — one copy (`Law 7`) —
    and it reads every shape as the canvas did."""
    o = _case(box, """
        const canvas = await import('./workbench/canvas.js').catch((e) => ({ err: String(e) }));
        const tasks = await import('./workbench/taskSource.js').catch((e) => ({ err: String(e) }));
        const inputs = [' A sentence. ', [{ msg: 'a' }, { message: 'b' }, {}], { message: 'm' },
                        { sentence: 's' }, { reason: 'r' }, { detail: 'd' }, null, 42, ''];
        out({ mine: inputs.map(refusalText),
              theirs: canvas.refusalText ? inputs.map(canvas.refusalText) : canvas.err,
              one: [canvas.refusalText === refusalText, tasks.refusalText === refusalText] });
    """)
    assert o["mine"] == ["A sentence.", "a b", "m", "s", "r", "d", "", "", ""]
    assert isinstance(o["theirs"], list), f"the canvas did not load: {o['theirs']}"
    assert o["theirs"] == o["mine"]
    assert o["one"] == [True, True], "a second copy of refusalText"


# ── workflowSource.js: what is drawn ─────────────────────────────────────────

def test_the_start_is_drawn_as_a_fixed_step_with_a_fixed_arrow_into_the_first(box):
    o = _case(box, """
        server.doc.graph.nodes.push(node('n3', 'run_task', 'Run the backup', { task_id: 'bk' }));
        server.doc.graph.nodes[1].pinned = { data: { result: 'x' } };
        server.tasks = [{ id: 'bk', name: 'Backup' }];
        const s = source();
        await s.ready;
        const d = await s.load();
        out({ items: d.items.map((i) => [i.id, i.name, i.kind, i.sub, i.ports, i.marks, i.accepts, !!i.fixed, i.paused]),
              edges: d.edges, readOnly: s.readOnly, words: s.words.region,
              start: { words: d.items[0].portWords, entry: d.items[0].entry },
              optional: [typeof s.newItem, typeof s.removeItem, typeof s.dryRun] });
    """)
    # `P22-11` (wf-canvas, design § 2): the start has one port of its own,
    # *starts*, and an arrow drawn from it is a real arrow of the document. A
    # document with none still draws its implied entry as the fixed arrow.
    assert o["start"] == {"words": {"success": "starts"}, "entry": True}
    assert o["items"] == [
        ["__start__", "Starts", "start", "Every day at 08:00", ["success"], [], False, True, True],
        ["n1", "Summarise my inbox", "llm", "Prompt", ["success", "error"], [], True, False, False],
        ["n2", "Send me the summary", "llm", "Prompt", ["success", "error"], ["Sample pinned"], True, False, False],
        # The person-facing word (`KIND_WORDS.run_task`, wf-ui, design § 6.6).
        # wf-api's branch had no word for the kind yet and pinned the raw
        # fallback `run_task · …`; a person never reads `run_task` (§ 6.6),
        # so at the wave C merge the data layer's test agrees with the word.
        ["n3", "Run the backup", "run_task", "Run task · Runs “Backup”", ["success", "error"], [], True, False, False],
    ]
    assert o["edges"] == [
        {"from": "__start__", "to": "n1", "when": "success", "label": "starts", "fixed": True},
        {"from": "n1", "to": "n2", "when": "success"},
    ]
    assert o["readOnly"] is False and o["words"] == "Steps of this workflow"
    assert o["optional"] == ["function", "function", "function"]


# ── draft semantics ─────────────────────────────────────────────────────────

def test_an_arrow_is_a_draft_edit_checked_by_the_server_and_written_by_nothing(box):
    o = _case(box, """
        server.doc.graph.nodes.push(node('n3'));
        const states = [];
        const s = source({ onState: (st) => states.push(st.dirty) });
        await s.ready;
        server.calls.length = 0;
        const r = await s.connect('n1', 'error', 'n3');
        const moved = await s.connect('n1', 'success', 'n3');
        const d = await s.load();
        out({ r, moved, calls: sent(), edges: d.edges.filter((e) => !e.fixed),
              dirty: s.state().dirty, saved: server.doc.graph.edges, lastState: states[states.length - 1] });
    """)
    assert o["r"] == {"ok": True} and o["moved"] == {"ok": True}
    assert [c[0:2] for c in o["calls"]] == [["PUT", "/api/workflows/wf1?check=true"]] * 2
    assert o["calls"][0][2]["base_version"] == 2
    assert {"from": "n1", "port": "error", "to": "n3"} in o["calls"][0][2]["graph"]["edges"]
    # `P22-11` (wf-canvas): fan-out. Drawing from a port that already has an
    # arrow ADDS one there (it was one per outcome, moved, in Slice B).
    assert sorted((e["from"], e["when"], e["to"]) for e in o["edges"]) == [
        ("n1", "error", "n3"), ("n1", "success", "n2"), ("n1", "success", "n3")]
    assert o["dirty"] is True and o["lastState"] is True
    assert o["saved"] == [{"from": "n1", "port": "success", "to": "n2"}], "nothing written"


def test_an_arrow_that_makes_a_loop_is_refused_in_the_servers_words(box):
    o = _case(box, """
        server.check = (body) => body.graph.edges.some((e) => e.from === 'n2' && e.to === 'n1')
          ? { status: 400, body: { detail: 'These steps would run in a circle: n1, n2.', reason: 'cycle', node_ids: ['n1', 'n2'] } }
          : null;
        const s = source();
        await s.ready;
        const r = await s.connect('n2', 'success', 'n1');
        out({ r, dirty: s.state().dirty, edges: (await s.load()).edges.length });
    """)
    assert o["r"]["ok"] is False
    assert o["r"]["sentence"] == "These steps would run in a circle: n1, n2."
    assert o["r"]["nodeIds"] == ["n1", "n2"]
    assert o["dirty"] is False and o["edges"] == 2


def test_an_unfinished_draft_does_not_block_an_arrow_and_says_what_it_lacks(box):
    o = _case(box, """
        // n3 and n4 are new and joined to nothing yet: the draft starts in three places.
        server.doc.graph.nodes.push(node('n3'), node('n4'));
        server.check = (body) => {
          const led = new Set(body.graph.edges.map((e) => e.to));
          const roots = body.graph.nodes.filter((n) => !led.has(n.id)).map((n) => n.id);
          return roots.length > 1 ? { status: 400, body: { detail: 'A workflow starts in one place.', reason: 'starts', node_ids: roots } } : null;
        };
        const s = source();
        await s.ready;
        const r = await s.connect('n2', 'success', 'n3');
        const problem = s.state().problem;
        const r2 = await s.connect('n3', 'success', 'n4');
        out({ r, problem, r2, after: s.state().problem });
    """)
    assert o["r"] == {"ok": True, "sentence": "A workflow starts in one place."}
    assert o["problem"] == {"sentence": "A workflow starts in one place.", "reason": "starts", "nodeIds": ["n1", "n4"],
                            "field": None}
    assert o["r2"] == {"ok": True} and o["after"] is None


def test_save_writes_the_draft_from_its_base_and_a_409_keeps_the_draft(box):
    o = _case(box, """
        const s = source();
        await s.ready;
        s.rename('Inbox digest');
        await s.connect('n2', 'error', 'n1').catch(() => null);
        const first = await s.save();
        const afterFirst = { dirty: s.state().dirty, version: s.state().version, name: s.state().name };
        // Somebody else saves (version 3 → 4) while this draft is open.
        server.doc.version += 1;
        s.rename('Mine');
        const second = await s.save();
        out({ first, afterFirst, second, kept: s.state().name, dirty: s.state().dirty, stale: s.state().stale,
              saves: sent().filter((c) => c[0] === 'PUT' && !c[1].includes('check')).map((c) => [c[2].base_version, c[2].name]) });
    """)
    assert o["first"] == {"ok": True, "saved": "new_version", "sentence": "Saved as version 3."}
    assert o["afterFirst"] == {"dirty": False, "version": 3, "name": "Inbox digest"}
    assert o["second"]["ok"] is False and o["second"]["stale"] is True
    assert o["second"]["sentence"] == "Saved somewhere else since."
    assert (o["kept"], o["dirty"], o["stale"]) == ("Mine", True, True)
    assert o["saves"] == [[2, "Inbox digest"], [3, "Mine"]]


def test_a_refused_save_names_the_steps_and_the_draft_stays(box):
    o = _case(box, """
        server.check = (body) => body.graph.nodes.some((n) => !n.config.prompt)
          ? { status: 400, body: { detail: '“Prompt” needs a prompt.', reason: 'needs', node_ids: ['prompt'],
              field: 'config.prompt' } } : null;
        const s = source({ panels: { palette: async () => 'llm' } });
        await s.ready;
        const id = await s.newItem(null);
        const res = await s.save();
        out({ id, res, problem: s.state().problem, dirty: s.state().dirty });
    """)
    # `P22-09` (wf-canvas): a new step's id is its label's slug, and a refusal
    # names the field it is about (C-W).
    assert o["id"] == "prompt"
    assert o["res"]["ok"] is False and o["res"]["nodeIds"] == ["prompt"] and o["res"]["field"] == "config.prompt"
    assert o["problem"]["nodeIds"] == ["prompt"] and o["problem"]["field"] == "config.prompt" and o["dirty"] is True


def test_positions_save_themselves_never_mark_the_draft_and_tidy_up_forgets_them(box):
    o = _case(box, """
        const s = source({ panels: { palette: async () => 'research' } });
        await s.ready;
        const fresh = await s.newItem(null);
        server.calls.length = 0;
        const a = await s.savePositions(new Map([['n1', { x: 10.4, y: 20 }], [START_ID, { x: 0, y: 0 }], [fresh, { x: 300, y: 5 }]]));
        const b = await s.savePositions(new Map([['n1', { x: 10, y: 20 }], [START_ID, { x: 0, y: 0 }], [fresh, { x: 300, y: 5 }]]));
        const back = await s.loadPositions();
        const c = await s.savePositions(new Map());
        out({ a, b, c, calls: sent(), back: [...back.entries()], dirty: s.state().dirty,
              stored: server.doc.graph.nodes.map((n) => n.position), start: server.doc.graph.start.position });
    """)
    assert o["a"] == {"ok": True} and o["b"] == {"ok": True} and o["c"] == {"ok": True}
    assert o["calls"] == [
        ["PUT", "/api/workflows/wf1", {"positions": {"n1": [10, 20], "start": [0, 0]}}],
        ["PUT", "/api/workflows/wf1", {"positions": {"n1": None, "start": None}}],
    ], "only what moved, only saved steps; nothing when nothing moved"
    assert o["back"] == [["n1", {"x": 10, "y": 20}], ["research", {"x": 300, "y": 5}], ["__start__", {"x": 0, "y": 0}]]
    assert o["stored"] == [None, None] and o["start"] is None
    assert o["dirty"] is True, "dirty from the new step, not from where steps sit"


def test_a_pin_saves_itself_says_what_it_dropped_and_is_not_a_change(box):
    o = _case(box, """
        const s = source({ panels: { palette: async () => 'llm' } });
        await s.ready;
        const unsaved = await s.newItem(null);
        const refused = await s.setPin(unsaved, { a: 1 });
        await s.removeItem(unsaved);
        const pinned = await s.setPin('n2', { result: 'Three mails.', colour: 'blue' });
        const marks = (await s.load()).items.find((i) => i.id === 'n2').marks;
        const unpinned = await s.setPin('n2', null);
        out({ refused, pinned, marks, unpinned: unpinned.pinned, dirty: s.state().dirty,
              pins: sent().filter((c) => c[2] && c[2].pins).map((c) => c[2].pins) });
    """)
    assert o["refused"] == {"ok": False, "sentence": "Save the workflow first, then pin a sample on this step."}
    assert o["pinned"]["ok"] is True and o["pinned"]["dropped"] == ["colour"]
    assert o["marks"] == ["Sample pinned"]
    assert o["unpinned"] is None and o["dirty"] is False
    assert o["pins"] == [{"n2": {"result": "Three mails.", "colour": "blue"}}, {"n2": None}]


def test_new_change_and_remove_are_draft_edits_and_discard_takes_them_back(box):
    o = _case(box, """
        const opened = [];
        const panels = {
          palette: async () => 'action',
          node: (host, args) => { opened.push(args); return { destroy() {} }; },
        };
        const s = source({ panels });
        await s.ready;
        const a = await s.newItem(null);
        const b = await s.newItem(null);
        const saidOnSaved = [];
        s.openPanel({ textContent: '' }, { id: a }, { onSaved: (x) => saidOnSaved.push(x) });
        await opened[0].onApply({ label: 'Tidy chats', config: { action: 'tidy_sessions' } });
        const items = (await s.load()).items.map((i) => [i.id, i.name, i.sub]);
        const start = await s.removeItem(START_ID);
        const gone = await s.removeItem('n1');
        const edgesAfter = (await s.load()).edges;
        const dirty = s.state().dirty;
        await s.discard();
        out({ a, b, items, start, gone, edgesAfter, dirty, saidOnSaved,
              panelArgs: Object.keys(opened[0]).sort(), panelNodeIsACopy: opened[0].node !== null,
              after: (await s.load()).items.map((i) => i.id), clean: s.state().dirty,
              writes: sent().filter((c) => c[0] !== 'GET' && !c[1].includes('check')) });
    """)
    # `P22-09` (wf-canvas): a new step's id is the slug of its label, and the
    # label it is first given re-keys it once ("Tidy chats" → `tidy-chats`).
    assert (o["a"], o["b"]) == ("action", "action-2")
    assert o["items"][3:] == [["tidy-chats", "Tidy chats", "Action · tidy_sessions"], ["action-2", "Action 2", "Action"]]
    assert o["start"] == {"ok": False, "sentence": "The start cannot be removed: it is what runs the workflow."}
    assert o["gone"] == {"ok": True, "sentence": "Save the workflow to keep the change."}
    assert all(e["from"] != "n1" and e["to"] != "n1" for e in o["edgesAfter"] if not e.get("fixed"))
    assert o["edgesAfter"][0]["to"] == "n2", "the start now leads to the step that goes first"
    assert o["dirty"] is True and o["clean"] is False
    assert o["saidOnSaved"] == [{"id": "tidy-chats", "was": "action", "name": "Tidy chats",
                                 "sentence": "Changed “Tidy chats”. Save the workflow to keep it."}]
    # `P22-09`…`P22-18` (wf-canvas, C-W): the panel is also handed the
    # palette, the steps before it, whether it is saved, a field lister and
    # the draft's problem when it names this step. `P22-19` (wb-canvas-e, C-A):
    # and `check` — a step nobody has checked yet opens on it (null here).
    assert o["panelArgs"] == ["check", "fields", "node", "onApply", "onCancel", "palette", "problem", "saved",
                              "source", "tasks", "upstream", "workflow"]
    assert o["after"] == ["__start__", "n1", "n2"]
    assert o["writes"] == [], "a draft edit writes nothing; Discard writes nothing"


def test_a_step_is_tested_as_it_stands_in_the_draft(box):
    o = _case(box, """
        const opened = [];
        const s = source({ panels: { node: (h, args) => { opened.push(args); return { destroy() {} }; } } });
        await s.ready;
        s.openPanel({}, { id: 'n1' }, {});
        await opened[0].onApply({ label: 'Shorter', config: { prompt: 'Two lines.' } });
        const r = await opened[0].source.test('n1', { source: 'custom', input: { a: 1 } });
        const t = sent().find((c) => c[1].endsWith('/test'));
        out({ r, t });
    """)
    assert o["r"]["ok"] is True and o["r"]["outcome"] == "ran"
    assert o["t"][1] == "/api/workflows/wf1/nodes/n1/test"
    assert o["t"][2]["node"]["config"] == {"prompt": "Two lines."}
    assert o["t"][2]["source"] == "custom" and o["t"][2]["input"] == {"a": 1}


def test_the_dry_run_is_of_the_saved_document_one_plan_per_step(box):
    o = _case(box, """
        server.plan = [
          { node_id: 'n1', kind: 'llm', name: 'Summarise my inbox', when: null, depth: 0, steps: [{ kind: 'dry-run', detail: 'Would ask the model.' }], declined: null },
          { node_id: 'n2', kind: 'llm', name: 'Send me the summary', when: 'success', depth: 1, steps: [], declined: 'It is paused.' },
        ];
        const s = source();
        await s.ready;
        const clean = await s.dryRun();
        s.rename('Changed');
        const dirty = await s.dryRun();
        out({ head: clean.head, partial: clean.partial, plans: [...clean.plans.entries()],
              cleanSays: clean.sentence, dirtySays: dirty.sentence,
              asked: sent().filter((c) => c[0] === 'POST').map((c) => c[1]) });
    """)
    assert o["head"] == "__start__" and o["partial"] is False
    assert [k for k, _ in o["plans"]] == ["__start__", "n1", "n2"]
    assert o["plans"][0][1]["steps"][0]["detail"] == "Would start: Every day at 08:00."
    assert o["plans"][2][1] == {"steps": [], "declined": "It is paused.", "when": "success", "depth": 1}
    assert o["cleanSays"] == ""
    assert o["dirtySays"] == "This is the plan for the workflow as saved: your unsaved changes are not in it."
    assert o["asked"] == ["/api/tasks/t1/run?dry=true"] * 2


def test_switch_and_versions_and_a_restore_that_would_lose_edits_is_refused(box):
    o = _case(box, """
        server.versions = [
          { version: 2, name: 'Morning digest', saved_at: 'x', source: 'user', step_count: 2, current: true },
          { version: 1, name: 'Morning digest', saved_at: 'y', source: 'user', step_count: 0, current: false,
            graph: { v: 1, start: { position: null }, nodes: [], edges: [] } },
        ];
        const s = source();
        await s.ready;
        const on = await s.switchOn(true);
        const listed = await s.versions();
        const look = await s.showVersion(1);
        const viewing = { ro: s.readOnly, items: (await s.load()).items.map((i) => i.id),
                          connect: await s.connect('n1', 'error', 'n2') };
        await s.showVersion(null);
        s.rename('Edited');
        const refused = await s.restoreVersion(1);
        await s.discard();
        const restored = await s.restoreVersion(1);
        out({ on, onState: s.state().on, listed: listed.versions.map((v) => v.version), look: look.version,
              viewing, back: s.readOnly, refused, restored });
    """)
    assert o["on"]["ok"] is True and o["on"]["sentence"] == "Switched on." and o["onState"] is True
    assert o["listed"] == [2, 1]
    assert o["look"]["version"] == 1
    assert o["viewing"]["ro"] is True and o["viewing"]["items"] == ["__start__"]
    assert o["viewing"]["connect"]["ok"] is False
    assert o["back"] is False
    assert o["refused"] == {"ok": False, "sentence": "You have changes that are not saved. Save them or throw them away first, then restore."}
    assert o["restored"]["ok"] is True and o["restored"]["sentence"].startswith("Restored version 1 as version 3.")


# ── a run, read-only (`P22-07`) ─────────────────────────────────────────────

def test_a_run_is_drawn_read_only_with_each_steps_outcome_and_the_step_it_failed_on(box):
    o = _case(box, """
        server.execution = {
          run: { id: 'r1', status: 'error', steps: [{ kind: 'trigger', detail: 'Triggered by email_received — account=work' }] },
          version: 2, version_kept: true, cleared: false,
          graph: { v: 1, start: { position: [5, 5] }, nodes: [node('n1', 'llm', 'Summarise my inbox'),
                   node('n2', 'llm', 'Write it up'), node('n3', 'llm', 'Tell me')],
                   edges: [{ from: 'n1', port: 'success', to: 'n2' }, { from: 'n2', port: 'success', to: 'n3' }] },
          nodes: [
            { node_id: 'n1', label: 'Summarise my inbox', status: 'success', seq: 1, dry: false },
            { node_id: 'n2', label: 'Write it up', status: 'error', seq: 2, dry: false, error: 'The model did not answer.\\nTrace…' },
          ],
        };
        const records = [];
        const s = source({ mode: 'run', runId: 'r1',
          panels: { record: (host, args) => { records.push(args); return { destroy() {} }; } } });
        await s.ready;
        const d = await s.load();
        s.openPanel({}, { id: 'n2' }, {});
        out({ ro: s.readOnly, optional: [typeof s.newItem, typeof s.removeItem],
              items: d.items.map((i) => [i.id, i.outcome.tone, i.outcome.word]),
              failed: s.state().failed, record: records[0].record.status,
              connect: await s.connect('n1', 'error', 'n3'), saved: await s.savePositions(new Map()),
              words: s.words.region, positions: [...(await s.loadPositions()).entries()],
              writes: sent().filter((c) => c[0] !== 'GET') });
    """)
    assert o["ro"] is True and o["optional"] == ["undefined", "undefined"]
    assert o["items"] == [
        ["__start__", "info", "Triggered by email_received — account=work"],
        ["n1", "ok", o["items"][1][2]],
        ["n2", "error", o["items"][2][2]],
        ["n3", "none", "Not reached in this run"],
    ]
    assert o["items"][1][2] and o["items"][2][2], "the shared run words (`runStatus.js`)"
    assert o["failed"] == {"nodeId": "n2", "label": "Write it up", "firstLine": "The model did not answer."}
    assert o["record"] == "error"
    assert o["connect"]["ok"] is False and o["saved"] == {"ok": True}
    assert o["words"] == "This run, step by step"
    assert o["positions"] == [["__start__", {"x": 5, "y": 5}]]
    assert o["writes"] == []


def test_a_cleared_runs_step_says_it_was_cleared_in_the_servers_words(box):
    """The wave C seam between wf-api's source and wf-ui's record panel: the
    panel tells a cleared run's step from one the run never reached by
    `run.cleared`, which is the run REPLY's (`GET /runs/{id}` → `cleared`,
    `cleared_sentence`), not the run row's. The source handed the row alone,
    so every step of a cleared run said "not reached" (`Law 10`), and the
    panel's own sentence typed "30 days" whatever the window was set to. The
    real source drives the real panel here."""
    o = _case(box, """
        const { installDom } = await import('./dom.js');
        installDom();
        const { createWorkflowPanels } = await import('./workbench/workflowPanels.js');
        const said = 'Its step details were cleared after 7 days (workflow_node_records_days).';
        const run = (cleared) => ({
          run: { id: 'r1', status: 'success', steps: [{ kind: 'node', node: 'n1' }] },
          version: 2, version_kept: true, cleared, cleared_sentence: cleared ? said : null,
          graph: { v: 1, start: { position: null }, nodes: [node('n1', 'llm', 'Summarise my inbox')], edges: [] },
          nodes: [],
        });
        const texts = (host) => host._walk([]).filter((n) => n.className === 'wf-record-note').map((n) => n.textContent);
        const panels = createWorkflowPanels({ mountTaskFields: () => ({ destroy() {} }) });
        const shown = {};
        for (const cleared of [true, false]) {
          server.execution = run(cleared);
          const s = source({ mode: 'run', runId: 'r1', panels });
          await s.ready;
          await s.load();
          const host = document.createElement('div');
          s.openPanel(host, { id: 'n1' }, {});
          shown[cleared] = { note: texts(host), empty: s.words.emptyText || null };
        }
        out(shown);
    """)
    assert o["true"]["note"] == ["Its step details were cleared after 7 days (workflow_node_records_days)."]
    assert o["true"]["empty"].startswith("Its step details were cleared after 7 days")
    assert o["false"]["note"] == [
        "This step was not reached in this run, so it was handed nothing and made nothing."]
    assert not o["false"]["empty"]
