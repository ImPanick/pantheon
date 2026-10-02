# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-10`, `P22-11` (wf-canvas) — a step has its own ways out, several arrows may leave one, and the start's arrows are real.

Slice B's canvas drew every step with the two ports every task has (*if it
works*, *if it fails*) at two fixed heights (`graphLayout.js` `PORT_TOP` /
`PORT_STEP`), one arrow per port (drawing another moved it), and a workflow's
start as a step with no port and one fixed arrow into the step nothing leads
to. Slices C and D add steps with ports of their own (`ports_of`,
`/work/notes/SLICE-CD-DESIGN.md` § 1.3: an If's `then` / `otherwise`, a
Switch's `case:<id>` per case and `otherwise`, one `success` for Set, Merge
and Wait), fan-out ("Several arrows on one `(from, port)` are allowed"), and
explicit start arrows (`{from: "start", port: "success", to}`; a document with
none keeps its implied entry, `Law 1`). The JS contract (§ 3): `item.portWords`,
`source.fanOut` (Connect… *adds* an arrow), `portPoint(pos, when, ports)`,
`nodeHeight(ports)`.

Driven: the real `canvas.js`, `graphLayout.js` and `workflowSource.js` over the
real `workflowApi.js`, answered by a fake server in C2's and C-W's shapes
(`tests/helpers/workflow_cw_fake.py`), every request recorded.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from helpers.workflow_cw_fake import build_sandbox, palette_json  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_PREAMBLE = (
    "import { document, Node, fire, settle, host, edges, edgeEls, markup } from './shim.js';\n"
    "import { server as cw, net as cwnet, seed, cwApi } from './cwfake.js';\n"
    "const { mountCanvas } = await import('./canvas.js');\n"
    "const { createWorkflowSource, START_ID } = await import('./workflowSource.js');\n"
    "const L = await import('./graphLayout.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "cw.palette = %s;\n"
    "const itemOf = (root, id) => root.querySelectorAll('.wb-node').find((n) => n.dataset.itemId === id) || null;\n"
    "const node = (id, kind, label, config = {}) => ({ id, kind, label, config, position: null, pinned: null });\n"
    "const doc = (nodes, edgesList) => ({ id: 'wf1', name: 'Mail triage', task_id: 't1', trigger_status: 'paused',\n"
    "  version: 3, trigger_task: { id: 't1', task_type: 'workflow', status: 'paused' },\n"
    "  graph: { v: 1, start: { position: null }, nodes, edges: edgesList } });\n"
    "const open = async (d) => {\n"
    "  seed(d);\n"
    "  const src = createWorkflowSource({ api: cwApi(cwnet), workflowId: 'wf1', describeTrigger: () => 'Every day at 08:00' });\n"
    "  await src.ready;\n"
    "  const root = host();\n"
    "  const c = mountCanvas(root, { source: src });\n"
    "  await c.ready; await settle();\n"
    "  return { root, c, src };\n"
    "};\n"
    "const ports = (root, id) => itemOf(root, id).querySelectorAll('.wb-port').map((p) =>\n"
    "  [p.dataset.when, p.querySelector('.wb-port-label').textContent, p.style.top]);\n"
    "const said = (root) => root.querySelector('.wb-say-text').textContent;\n"
    "const checks = () => cw.calls.filter((c) => c.method === 'PUT' && c.url.endsWith('?check=true'));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("waysout"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % palette_json(), script)


_SORT = """
const SORT = doc([
  node('read', 'llm', 'Read the mail', { prompt: 'Read it' }),
  node('sort', 'switch', 'Sort it', { cases: [
    { id: 'c1', label: 'Urgent', join: 'all', conditions: [{ left: '{{ steps.read.text }}', op: 'contains', right: 'URGENT' }] },
    { id: 'c2', label: 'Billing', join: 'all', conditions: [{ left: '{{ steps.read.text }}', op: 'contains', right: 'invoice' }] }] }),
  node('urgent', 'llm', 'Tell me now', { prompt: 'x' }),
  node('bill', 'action', 'File the bill', { action: 'tidy_sessions' }),
  node('rest', 'llm', 'Leave it', { prompt: 'x' }),
  node('isit', 'if', 'Is it long?', { join: 'all', conditions: [{ left: '{{ steps.read.text }}', op: 'is_empty' }] }),
  node('tidy', 'set', 'Tidy', { fields: [{ name: 'headline', value: '{{ steps.read.text }}' }] }),
], [
  { from: 'read', port: 'success', to: 'sort' },
  { from: 'sort', port: 'case:c1', to: 'urgent' },
  { from: 'sort', port: 'case:c2', to: 'bill' },
  { from: 'sort', port: 'otherwise', to: 'rest' },
  { from: 'rest', port: 'success', to: 'isit' },
  { from: 'isit', port: 'then', to: 'tidy' },
]);
"""


def test_a_step_with_more_ways_out_is_taller_and_each_port_has_its_own_place(box):
    o = _case(box, """
        const G = { nodes: [{ id: 'a' }, { id: 's' }, { id: 'x' }, { id: 'y' }],
          edges: [{ from: 'a', to: 's', when: 'success' }, { from: 'a', to: 'x', when: 'error' }, { from: 's', to: 'y', when: 'case:c1' }] };
        const plain = L.layoutGraph(G, null).nodes.map((n) => [n.id, n.x, n.y, n.h]);
        const evenly = L.layoutGraph(G, null, { heights: {} }).nodes.map((n) => [n.id, n.x, n.y, n.h]);
        const tall = L.layoutGraph(G, null, { heights: { s: L.nodeHeight(['case:c1', 'case:c2', 'case:c3', 'case:c4', 'otherwise']) } })
          .nodes.map((n) => [n.id, n.x, n.y, n.h]);
        out({
          h: [L.nodeHeight([]), L.nodeHeight(['success', 'error']), L.nodeHeight(['then', 'otherwise']),
              L.nodeHeight(['case:c1', 'case:c2', 'otherwise']), L.nodeHeight(5)],
          p: [L.portPoint({ x: 0, y: 0 }, 'otherwise', ['then', 'otherwise']),
              L.portPoint({ x: 0, y: 0 }, 'case:c3', ['case:c1', 'case:c2', 'case:c3', 'otherwise']),
              L.portPoint({ x: 0, y: 0 }, 'error'), L.portPoint({ x: 0, y: 0 }, 'success', ['success'])],
          input: [L.inputPoint({ x: 10, y: 0 }), L.inputPoint({ x: 10, y: 0, h: 222 })],
          hit: [L.nodeAt([{ id: 's', x: 0, y: 0, h: 222 }], { x: 5, y: 200 }), L.nodeAt([{ id: 's', x: 0, y: 0 }], { x: 5, y: 200 })],
          bounds: L.boundsOf([{ x: 0, y: 0, h: 222 }, { x: 300, y: 0 }]),
          plain, evenly, tall,
        });
    """)
    assert o["h"] == [96, 96, 96, 138, 222], "two ports or fewer is Slice B's step; each port past the second adds a row"
    assert o["p"] == [{"x": 232, "y": 62}, {"x": 232, "y": 104}, {"x": 232, "y": 62}, {"x": 232, "y": 20}]
    assert o["input"] == [{"x": 10, "y": 48}, {"x": 10, "y": 111}], "an arrow arrives halfway down the step it reaches"
    assert o["hit"] == ["s", None], "a tall step is hit where it is drawn"
    assert o["bounds"] == {"x": 0, "y": 0, "w": 532, "h": 222}
    assert o["plain"] == o["evenly"], "with no heights the layout is Slice B's, to the pixel"
    by = {n[0]: n for n in o["tall"]}
    assert by["s"][3] == 222 and by["x"][2] == by["s"][2] + 222 + 32, \
        "the row under a tall step starts under it, not into it"


def test_a_switchs_cases_are_its_ways_out_each_with_its_words(box):
    o = _case(box, _SORT + """
        const { root } = await open(SORT);
        const g = edgeEls(root).find((x) => x.getAttribute('data-from') === 'sort' && x.getAttribute('data-when') === 'case:c2');
        // SVG children carry their class as an attribute (the shim matches className).
        const line = g.childNodes.find((n) => n.getAttribute('class') === 'wb-edge-line');
        const startY = Number(String(line.getAttribute('d')).split(' ')[2]);
        out({
          sort: { h: itemOf(root, 'sort').style.height, ports: ports(root, 'sort'), top: parseFloat(itemOf(root, 'sort').style.top) },
          isit: { h: itemOf(root, 'isit').style.height, ports: ports(root, 'isit') },
          tidy: ports(root, 'tidy'),
          read: ports(root, 'read'),
          edges: edges(root).filter((e) => e.from === 'sort' || e.from === 'isit').map((e) => [e.when, e.words, e.label]),
          startY,
          markup: markup(root),
        });
    """)
    assert o["sort"]["h"] == "138px"
    assert o["sort"]["ports"] == [["case:c1", "if Urgent", "13px"], ["case:c2", "if Billing", "55px"],
                                  ["otherwise", "otherwise", "97px"]]
    assert o["isit"] == {"h": "96px", "ports": [["then", "if so", "13px"], ["otherwise", "otherwise", "55px"]]}
    assert o["tidy"] == [["success", "then", "13px"]], "a step with one way out says 'then', not 'if it works'"
    assert o["read"] == [["success", "if it works", "13px"], ["error", "if it fails", "55px"]], "a task kind is as it was"
    assert o["edges"] == [
        ["case:c1", "if Urgent", "After Sort it, if Urgent, Tell me now runs. Press Delete to remove this arrow."],
        ["case:c2", "if Billing", "After Sort it, if Billing, File the bill runs. Press Delete to remove this arrow."],
        ["otherwise", "otherwise", "After Sort it, otherwise, Leave it runs. Press Delete to remove this arrow."],
        ["then", "if so", "After Is it long?, if so, Tidy runs. Press Delete to remove this arrow."],
    ]
    assert o["startY"] == o["sort"]["top"] + 62, "the Billing arrow leaves from the Billing port"
    assert o["markup"] == [], "a case label a person typed is text"


def test_connect_adds_an_arrow_on_a_source_that_fans_out(box):
    o = _case(box, """
        const D = doc([node('sum', 'llm', 'Summarise', { prompt: 'x' }), node('mail', 'llm', 'Mail it', { prompt: 'x' }),
          node('file', 'action', 'File it', { action: 'tidy_sessions' })],
          [{ from: 'sum', port: 'success', to: 'mail' }, { from: 'sum', port: 'success', to: 'file' }].slice(0, 1));
        const { root, src } = await open(D);
        fire(itemOf(root, 'sum').querySelector('.wb-node-connect'), 'click');
        const box = root.querySelector('.wb-connect');
        const now = box.querySelector('.wb-connect-now').textContent;
        box.querySelector('.wb-connect-to').value = 'file';
        fire(box.querySelector('.wb-connect-go'), 'click');
        await settle(5);
        const sent = checks().map((c) => c.body.graph.edges);
        const after = edges(root).filter((e) => e.from === 'sum').map((e) => [e.when, e.to]);
        const sayAfter = said(root);
        const again = await src.connect('sum', 'success', 'file');
        fire(itemOf(root, 'sum').querySelector('.wb-node-connect'), 'click');
        const now2 = root.querySelector('.wb-connect-now').textContent;
        out({ fan: src.fanOut, now, sent, after, sayAfter, again, now2 });
    """)
    assert o["fan"] is True
    assert o["now"] == "Now: Mail it runs if it works. Connecting adds another; both run."
    assert o["sent"][-1] == [{"from": "sum", "port": "success", "to": "mail"}, {"from": "sum", "port": "success", "to": "file"}], \
        "the arrow that was there stays, and the new one is added"
    assert sorted(o["after"]) == [["success", "file"], ["success", "mail"]]
    assert o["sayAfter"] == "Connected. After Summarise, if it works, File it runs.", "nothing it 'used to be'"
    assert o["again"] == {"ok": False, "sentence": "That arrow is already there."}
    assert o["now2"] == "Now: Mail it and File it run if it works. Connecting adds another; they all run."


def test_the_start_has_one_port_and_its_arrows_are_real(box):
    o = _case(box, """
        const D = doc([node('first', 'llm', 'Check feed A', { prompt: 'x' }), node('second', 'llm', 'Check feed B', { prompt: 'x' })], []);
        const { root, src } = await open(D);
        const before = edges(root).map((e) => [e.from, e.to, e.words]);
        const implied = edgeEls(root).find((g) => g.getAttribute('data-from') === START_ID);
        fire(implied, 'keydown', { key: 'Delete' });
        const kept = said(root);
        const startPorts = ports(root, START_ID);
        fire(itemOf(root, START_ID).querySelector('.wb-node-connect'), 'click');
        const box = root.querySelector('.wb-connect');
        const head = box.querySelector('.wb-connect-head').textContent;
        const outcomeHidden = box.querySelector('.wb-connect-field').hidden;
        box.querySelector('.wb-connect-to').value = 'second';
        fire(box.querySelector('.wb-connect-go'), 'click');
        await settle(5);
        const sent = checks().map((c) => c.body.graph.edges);
        const after = edgeEls(root).filter((g) => g.getAttribute('data-from') === START_ID)
          .map((g) => [g.getAttribute('data-to'), g.querySelector('text').textContent, g.getAttribute('class').includes('wb-edge-fixed')]);
        const sayAfter = said(root);
        const toStart = await src.connect('first', 'success', START_ID);
        const off = await src.disconnect(START_ID, 'success', 'second');
        const left = (await src.load()).edges.filter((e) => e.from === START_ID);
        out({ before, kept, startPorts, head, outcomeHidden, sent, after, sayAfter, toStart, off, left });
    """)
    assert o["before"] == [["__start__", "first", "starts"]], "a document with no start arrows keeps its implied entry"
    assert o["kept"] == ("When it starts, Check feed A runs. This arrow always leads to the first step, "
                         "so it cannot be removed.")
    assert o["startPorts"] == [["success", "starts", "13px"]], "the start has one port, starts"
    assert o["head"] == "When it starts…" and o["outcomeHidden"] is True, "one way out: nothing to choose"
    assert o["sent"][-1] == [{"from": "start", "port": "success", "to": "first"},
                             {"from": "start", "port": "success", "to": "second"}], \
        "the implied entry is written out beside the new arrow, so the step that ran first still runs"
    assert sorted(o["after"]) == [["first", "starts", False], ["second", "starts", False]], "both real, both removable"
    assert o["sayAfter"] == "Connected. When it starts, Check feed B runs."
    assert o["toStart"] == {"ok": False, "sentence": "The start always leads to the step that goes first; draw arrows between steps."}
    assert o["off"] == {"ok": True}
    assert o["left"] == [{"from": "__start__", "to": "first", "when": "success"}]


def test_a_way_out_a_step_does_not_have_is_refused_in_words(box):
    o = _case(box, _SORT + """
        const { src } = await open(SORT);
        out({
          set: await src.connect('tidy', 'error', 'urgent'),
          sw: await src.connect('sort', 'success', 'urgent'),
          case: await src.connect('sort', 'case:c9', 'urgent'),
          sent: checks().length,
        });
    """)
    assert o["set"] == {"ok": False, "sentence": "“Tidy” has no “if it fails” way out."}
    assert o["sw"] == {"ok": False, "sentence": "“Sort it” has no “if it works” way out."}
    assert o["case"] == {"ok": False, "sentence": "“Sort it” has no “case:c9” way out."}
    assert o["sent"] == 0, "refused before asking the server"
