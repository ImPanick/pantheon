# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-02` — the Workbench's Automations canvas, driven.

The real `static/js/workbench/canvas.js` in the shared DOM shim harness
(`tests/test_tool_effect_surfaces_js.py` — `_make_sandbox`, `_run`, `installDom`),
beside the real `graphLayout.js`, `tasks/workflowDiagram.js`, `runStatus.js`,
`editor/snap.js` and `escMenuStack.js`. Two things are stand-ins, and both are
what the module is built to take as dependencies:

  * **the server** — a small fake in the shim that answers the three doors the
    canvas uses, with the shapes the real routes return: `GET /api/tasks`
    (`{ tasks, graph }`, the graph built the way `build_task_graph` builds it,
    from the two successor columns), `PUT /api/tasks/{id}` (an omitted key
    leaves a column alone, `""` clears it — `TaskUpdate`'s rule — and a refusal
    is FastAPI's `400 { detail }`), and `GET`/`PUT /api/prefs/{key}`. Every
    request is recorded, so a case asserts the exact body that went on the wire;
  * **the panel** — `mountPanel`, the `P22` contract `taskFields.js` implements
    on `wb-fields`'s branch. The stub records what it was handed.

`windowDrag.js` is stubbed to its two exported numbers: the real module wires
docking at import time, and these cases are about the canvas.

**The shim's limits, stated rather than glossed (`PREAMBLE`).** Events do not
bubble, so each is fired on the element whose listener a browser would reach
first; `closest()` answers `null`; an element has no layout, so the viewport
measures 0×0 and the canvas falls back to zoom 1 with the drawing's corner at
the padding — which makes a canvas point and a pointer coordinate the same
number, and is why the drop coordinates below are read off the steps' own
`left`/`top` rather than written down. `innerHTML` is stored as a string and
never parsed: `_html` on a node is non-empty only if something assigned markup,
which is exactly what the hostile-name case asserts never happens.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CANVAS_JS = JS / "workbench" / "canvas.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The real modules `canvas.js` reaches with `../`, which the shared builder
# (it follows `./` imports only) does not copy.
_UP = ("tasks/workflowDiagram.js", "runStatus.js", "editor/snap.js", "escMenuStack.js")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};

// ── a server that answers the canvas's three doors ─────────────────────────
export const server = { tasks: [], prefs: null, calls: [], refuse: null };

function graph() {
  const known = new Set(server.tasks.map((t) => t.id));
  const edges = [];
  for (const t of server.tasks) {
    for (const [when, col] of [['success', 'then_task_id'], ['error', 'else_task_id']]) {
      if (t[col]) edges.push({ from: t.id, to: t[col], when, dangling: !known.has(t[col]) });
    }
  }
  return {
    nodes: server.tasks.map((t) => ({ id: t.id, name: t.name, task_type: t.task_type || 'llm', status: t.status })),
    edges, conditions: ['success', 'error'], max_depth: 10,
  };
}
const reply = (status, body) => ({
  ok: status >= 200 && status < 300, status, json: async () => JSON.parse(JSON.stringify(body)),
});
export async function net(url, init = {}) {
  url = String(url);
  const method = init.method || 'GET';
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined;
  server.calls.push({ url, method, body });
  if (url === '/api/tasks?include_last_run=true' && method === 'GET') {
    return reply(200, { tasks: server.tasks.map((t) => ({ ...t })), graph: graph() });
  }
  const m = /^\/api\/tasks\/([^/?]+)$/.exec(url);
  if (m && method === 'PUT') {
    const id = decodeURIComponent(m[1]);
    const t = server.tasks.find((x) => x.id === id);
    if (!t) return reply(404, { detail: 'Task not found' });
    const why = server.refuse && server.refuse(id, body);
    if (why) return reply(400, { detail: why });
    for (const k of ['then_task_id', 'else_task_id', 'name']) {
      if (body[k] !== undefined && body[k] !== null) t[k] = body[k] || null;
    }
    return reply(200, { ...t });
  }
  if (url === '/api/prefs/workbench_positions') {
    if (method === 'GET') return reply(200, { key: 'workbench_positions', value: server.prefs });
    if (method === 'PUT') { server.prefs = body.value; return reply(200, { key: 'workbench_positions', value: body.value }); }
  }
  return reply(404, { detail: 'Not Found' });
}
export const writes = () => server.calls.filter((c) => c.method === 'PUT' && c.url.startsWith('/api/tasks/'));
export const reads = () => server.calls.filter((c) => c.method === 'GET' && c.url.startsWith('/api/tasks')).length;
export const prefWrites = () => server.calls.filter((c) => c.method === 'PUT' && c.url.startsWith('/api/prefs/'));

// ── the panel contract, recorded ───────────────────────────────────────────
export const panel = { mounts: [] };
export function mountPanel(host, args) {
  const rec = { host, args, destroyed: false };
  panel.mounts.push(rec);
  return { destroy() { rec.destroyed = true; } };
}

// ── driving it ─────────────────────────────────────────────────────────────
export function fire(node, type, extra = {}) {
  const ev = Object.assign({
    type, target: node, currentTarget: node, button: 0, pointerId: 7, clientX: 0, clientY: 0,
    shiftKey: false, altKey: false, ctrlKey: false, metaKey: false, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() {},
  }, extra);
  node.dispatchEvent(ev);
  return ev;
}
export const settle = (ms = 0) => new Promise((r) => setTimeout(r, ms));
export function host() {
  const r = document.body.appendChild(new Node('div'));
  r.className = 'workbench-room';
  return r;
}
export const nodeOf = (root, id) => root.querySelectorAll('.wb-node').find((n) => n.dataset.taskId === id) || null;
export const portOf = (node, when) => node.querySelectorAll('.wb-port').find((p) => p.dataset.when === when);
export const at = (node) => ({ x: parseFloat(node.style.left), y: parseFloat(node.style.top) });
export function edgeEls(root) {
  return root.querySelectorAll('g').filter((g) => g.getAttribute('data-from') != null);
}
export function edges(root) {
  return edgeEls(root).map((g) => ({
    from: g.getAttribute('data-from'), to: g.getAttribute('data-to'), when: g.getAttribute('data-when'),
    words: g.querySelectorAll('text').map((t) => t.textContent).join(''),
    label: g.getAttribute('aria-label'),
  }));
}
export const said = (root) => root.querySelector('.wb-say-text').textContent;
export const refused = (root) => root.querySelector('.wb-say')._classes().includes('wb-say-refusal');
export function read(root, id) {
  const n = nodeOf(root, id);
  if (!n) return null;
  return {
    title: n.querySelector('.wb-node-title').textContent,
    sub: n.querySelector('.wb-node-sub').textContent,
    word: n.querySelector('.wb-node-last') ? n.querySelector('.wb-node-last').readable : null,
    mark: n.querySelector('.wb-node-mark') ? n.querySelector('.wb-node-mark').textContent : null,
    outcome: n.dataset.outcome || null,
    ports: n.querySelectorAll('.wb-port').map((p) => [p.dataset.when, p.querySelector('.wb-port-label').textContent]),
    connect: !!n.querySelector('.wb-node-connect'),
    focusable: n.getAttribute('tabindex') === '0',
    focused: !!n.focused,
    chain: n._classes().includes('wb-node-chain'),
    hidden: n.getAttribute('aria-hidden'),
    ...at(n),
  };
}
/** Every string any node in the tree was given as markup. */
export const markup = (root) => root._walk([]).filter((n) => n._html).map((n) => n._html);
"""

_PREAMBLE = (
    "import { document, Node, server, net, writes, reads, prefWrites, panel, mountPanel, fire,"
    " settle, host, nodeOf, portOf, at, edgeEls, edges, said, refused, read, markup } from './shim.js';\n"
    "import { dismissTopMenu } from '../escMenuStack.js';\n"
    "const { mountCanvas, POSITIONS_PREF } = await import('./canvas.js');\n"
    "const describeTrigger = (t) => t.trigger_words || '';\n"
    "const mount = async (opts = {}) => {\n"
    "  const root = host();\n"
    "  const c = mountCanvas(root, { fetch: net, mountPanel, describeTrigger, ...opts });\n"
    "  await c.ready; await settle();\n"
    "  return { root, c };\n"
    "};\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbcanvas")
    (root / "workbench").mkdir()
    sandbox = _make_sandbox(root / "workbench", CANVAS_JS, _SHIM, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    return sandbox


def _case(box, script, tasks=None, prefs=None):
    setup = "server.tasks = %s;\nserver.prefs = %s;\n" % (
        json.dumps(tasks if tasks is not None else _TASKS), json.dumps(prefs))
    return _run(box, _PREAMBLE + setup, script)


# Three tasks: a backup that failed last night and is chained to a summary if
# it works, a message step that worked, and a summary that has never run.
_TASKS = [
    {"id": "a", "name": "Nightly backup", "task_type": "action", "status": "active",
     "trigger_words": "Daily at 02:00", "last_run_status": "error", "last_run": "2026-10-01T02:00:00Z",
     "then_task_id": "c", "else_task_id": None},
    {"id": "b", "name": "Message me", "task_type": "llm", "status": "active",
     "trigger_words": "Webhook", "last_run_status": "success", "then_task_id": None, "else_task_id": None},
    {"id": "c", "name": "Post summary", "task_type": "research", "status": "paused",
     "trigger_words": "Daily at 09:00", "then_task_id": None, "else_task_id": None},
]


# ── what is drawn ───────────────────────────────────────────────────────────

def test_every_task_is_a_step_and_every_edge_an_arrow_in_the_diagrams_words(box):
    o = _case(box, """
        const { root } = await mount();
        out({ a: read(root, 'a'), b: read(root, 'b'), c: read(root, 'c'), edges: edges(root),
              said: said(root), get: server.calls[0] });
    """)
    assert o["a"]["title"] == "Nightly backup"
    # What starts it is on the step nothing points at, and not on the one the
    # arrow starts (`P8-34`'s rule).
    assert o["a"]["sub"] == "Action · Daily at 02:00"
    assert o["b"]["sub"] == "Prompt · Webhook"
    assert o["c"]["sub"] == "Research · paused"
    for k in "abc":
        assert o[k]["ports"] == [["success", "if it works"], ["error", "if it fails"]], o[k]
        assert o[k]["connect"] is True and o[k]["focusable"] is True
    assert o["edges"] == [{
        "from": "a", "to": "c", "when": "success", "words": "if it works",
        "label": "After Nightly backup, if it works, Post summary runs. Press Delete to remove this arrow.",
    }]


def test_a_steps_last_outcome_is_a_mark_and_a_word_not_a_hue(box):
    """`runStatus.js`'s words and tone, on the step: `data-outcome` carries the
    border's shape and weight in the sheet, and the mark and the word say it
    in text — so the three states differ with every colour taken away."""
    o = _case(box, """
        const { root } = await mount();
        out({ a: read(root, 'a'), b: read(root, 'b'), c: read(root, 'c') });
    """)
    assert (o["a"]["outcome"], o["a"]["mark"], o["a"]["word"]) == ("error", "✗", "✗ Last run: Failed")
    assert (o["b"]["outcome"], o["b"]["mark"], o["b"]["word"]) == ("ok", "✓", "✓ Last run: Success")
    assert (o["c"]["outcome"], o["c"]["mark"], o["c"]["word"]) == ("none", "○", "○ Not run yet")


def test_the_list_is_asked_for_with_its_last_runs_and_nothing_else_is_fetched(box):
    o = _case(box, """
        await mount();
        out(server.calls.map((c) => c.method + ' ' + c.url));
    """)
    assert sorted(o) == ["GET /api/prefs/workbench_positions", "GET /api/tasks?include_last_run=true"]


# ── connecting by dragging from a port ─────────────────────────────────────

def test_dragging_if_it_fails_onto_a_step_writes_else_task_id_and_nothing_else(box):
    o = _case(box, """
        const { root } = await mount();
        const a = nodeOf(root, 'a'), b = at(nodeOf(root, 'b'));
        const port = portOf(a, 'error');
        fire(port, 'pointerdown', { clientX: 0, clientY: 0 });
        fire(port, 'pointermove', { clientX: b.x + 30, clientY: b.y + 30 });
        const target = nodeOf(root, 'b')._classes().includes('wb-node-target');
        const before = reads();
        fire(port, 'pointerup', { clientX: b.x + 30, clientY: b.y + 30 });
        await settle(5);
        out({ writes: writes(), target, refetched: reads() - before, edges: edges(root),
              said: said(root), refused: refused(root) });
    """)
    assert o["target"] is True, "the step under the pointer says it would take the arrow"
    assert o["writes"] == [{"url": "/api/tasks/a", "method": "PUT", "body": {"else_task_id": "b"}}]
    assert o["refetched"] == 1, "the canvas redraws from a fresh fetch, not from its own guess"
    assert {"from": "a", "to": "b", "when": "error"} in [
        {k: e[k] for k in ("from", "to", "when")} for e in o["edges"]]
    assert o["said"] == "Connected. After Nightly backup, if it fails, Message me runs."
    assert o["refused"] is False


def test_dragging_if_it_works_writes_then_task_id_and_says_what_it_replaced(box):
    o = _case(box, """
        const { root } = await mount();
        const port = portOf(nodeOf(root, 'a'), 'success'), b = at(nodeOf(root, 'b'));
        fire(port, 'pointerdown', {});
        fire(port, 'pointerup', { clientX: b.x + 5, clientY: b.y + 5 });
        await settle(5);
        out({ writes: writes(), said: said(root), edges: edges(root).map((e) => e.from + e.when + e.to) });
    """)
    assert o["writes"] == [{"url": "/api/tasks/a", "method": "PUT", "body": {"then_task_id": "b"}}]
    assert o["said"].endswith("It used to be Post summary."), o["said"]
    assert o["edges"] == ["asuccessb"]


def test_the_click_that_ends_a_drag_from_a_port_does_not_open_the_step(box):
    """Found in Chromium, not here: the port holds the pointer, so the click a
    browser fires when the button comes up lands on the port and bubbles to
    the step the arrow left — which opened that step's panel over the arrow
    just drawn. The shim does not bubble, so the click is fired on the step
    directly, as the browser delivers it. A click after the moment has passed
    is a real one and opens the step."""
    o = _case(box, """
        const { root } = await mount();
        const port = portOf(nodeOf(root, 'a'), 'error'), b = at(nodeOf(root, 'b'));
        fire(port, 'pointerdown', {});
        fire(port, 'pointerup', { clientX: b.x + 5, clientY: b.y + 5 });
        fire(nodeOf(root, 'a'), 'click');
        await settle(5);
        const swallowed = panel.mounts.length;
        await settle(450);
        fire(nodeOf(root, 'a'), 'click');
        out({ swallowed, later: panel.mounts.length, writes: writes().length });
    """)
    assert o == {"swallowed": 0, "later": 1, "writes": 1}


def test_letting_go_over_nothing_or_over_the_same_step_writes_nothing(box):
    o = _case(box, """
        const { root } = await mount();
        const a = nodeOf(root, 'a'), pa = at(a);
        const port = portOf(a, 'error');
        fire(port, 'pointerdown', {}); fire(port, 'pointerup', { clientX: -500, clientY: -500 });
        fire(port, 'pointerdown', {}); fire(port, 'pointerup', { clientX: pa.x + 20, clientY: pa.y + 20 });
        // The far end of nothing: a cancelled drag, and Escape mid-drag.
        fire(port, 'pointerdown', {}); const escaped = dismissTopMenu();
        fire(port, 'pointerup', { clientX: at(nodeOf(root, 'b')).x + 5, clientY: at(nodeOf(root, 'b')).y + 5 });
        await settle(5);
        out({ writes: writes(), escaped });
    """)
    assert o["writes"] == []
    assert o["escaped"] is True, "Escape ends a drag before the window's own Escape runs"


def test_a_refusal_shows_the_servers_own_sentence_and_changes_nothing(box):
    """`P22-01` puts the loop rule on the server and answers `400` with a
    sentence naming the tasks. The canvas does not rule on it; it shows it."""
    sentence = "That would loop: Message me runs Nightly backup, which runs Message me."
    o = _case(box, """
        server.refuse = (id, body) => (id === 'a' && body.else_task_id === 'b') ? %s : null;
        const { root } = await mount();
        const before = reads(), drawn = edges(root);
        const port = portOf(nodeOf(root, 'a'), 'error'), b = at(nodeOf(root, 'b'));
        fire(port, 'pointerdown', {});
        fire(port, 'pointerup', { clientX: b.x + 5, clientY: b.y + 5 });
        await settle(5);
        out({ said: said(root), refused: refused(root), refetched: reads() - before,
              same: JSON.stringify(drawn) === JSON.stringify(edges(root)), writes: writes().length });
    """ % json.dumps(sentence))
    assert o["writes"] == 1
    assert o["said"] == "Not connected: " + sentence
    assert o["refused"] is True
    assert o["refetched"] == 0 and o["same"] is True


def test_a_refusal_with_a_parse_error_shape_still_says_words(box):
    o = _case(box, """
        server.refuse = () => [{ loc: ['body', 'else_task_id'], msg: 'Input should be a valid string' }];
        const { root } = await mount();
        const port = portOf(nodeOf(root, 'a'), 'error'), b = at(nodeOf(root, 'b'));
        fire(port, 'pointerdown', {}); fire(port, 'pointerup', { clientX: b.x + 5, clientY: b.y + 5 });
        await settle(5);
        out({ said: said(root) });
    """)
    assert o["said"] == "Not connected: Input should be a valid string"


# ── the keyboard path: Connect… ─────────────────────────────────────────────

def test_connect_picks_the_outcome_and_the_step_by_name_and_writes_the_same_body(box):
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'a').querySelector('.wb-node-connect'), 'click');
        const box = root.querySelector('.wb-connect');
        const when = box.querySelector('.wb-connect-when'), to = box.querySelector('.wb-connect-to');
        const options = { when: when.querySelectorAll('option').map((x) => [x.value, x.textContent]),
                          to: to.querySelectorAll('option').map((x) => [x.value, x.textContent]) };
        const opened = { focused: when.focused, label: box.getAttribute('aria-label'),
                         head: box.querySelector('.wb-connect-head').textContent,
                         now: box.querySelector('.wb-connect-now').textContent };
        when.value = 'error'; fire(when, 'change');
        to.value = 'b';
        fire(box.querySelector('.wb-connect-go'), 'click');
        await settle(5);
        out({ options, opened, writes: writes(), open: !!root.querySelector('.wb-connect'),
              said: said(root), focusedA: read(root, 'a').focused });
    """)
    assert o["options"]["when"] == [["success", "if it works"], ["error", "if it fails"]]
    # Every other step, by name, alphabetically; never the step itself.
    assert o["options"]["to"] == [["b", "Message me"], ["c", "Post summary"]]
    assert o["opened"]["focused"] is True
    assert o["opened"]["label"] == "Connect Nightly backup"
    assert o["opened"]["head"] == "After Nightly backup…"
    assert o["opened"]["now"] == "Now: Post summary runs if it works. Connecting replaces it."
    assert o["writes"] == [{"url": "/api/tasks/a", "method": "PUT", "body": {"else_task_id": "b"}}]
    assert o["open"] is False
    assert o["said"] == "Connected. After Nightly backup, if it fails, Message me runs."
    assert o["focusedA"] is True, "the focus goes back to the step, redrawn"


def test_connect_keeps_the_picker_open_with_the_refusal_in_it(box):
    sentence = "the chain loops back on itself"
    o = _case(box, """
        server.refuse = () => %s;
        const { root } = await mount();
        fire(nodeOf(root, 'c').querySelector('.wb-node-connect'), 'click');
        const box = root.querySelector('.wb-connect');
        fire(box.querySelector('.wb-connect-go'), 'click');
        await settle(5);
        const still = root.querySelector('.wb-connect');
        const inside = still ? still.querySelector('.wb-connect-say').textContent : null;
        const escaped = dismissTopMenu();
        out({ writes: writes(), inside, said: said(root), closed: !root.querySelector('.wb-connect'),
              escaped, focusedC: read(root, 'c').focused });
    """ % json.dumps(sentence))
    # Defaults: the first outcome and the first other step by name.
    assert o["writes"] == [{"url": "/api/tasks/c", "method": "PUT", "body": {"then_task_id": "b"}}]
    assert o["inside"] == "Not connected: " + sentence
    assert o["said"] == "Not connected: " + sentence
    assert o["escaped"] is True and o["closed"] is True
    assert o["focusedC"] is True, "Escape hands the focus back to the step it was opened from"


def test_connect_on_the_only_task_says_there_is_nothing_to_connect_to(box):
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'b').querySelector('.wb-node-connect'), 'click');
        const box = root.querySelector('.wb-connect');
        out({ now: box.querySelector('.wb-connect-now').textContent,
              disabled: box.querySelector('.wb-connect-go').disabled });
    """, tasks=[_TASKS[1]])
    assert o["disabled"] is True
    assert "There is no other step yet" in o["now"]


# ── moving a step ───────────────────────────────────────────────────────────

def test_arrow_keys_move_a_focused_step_by_the_window_step_and_keep_it(box):
    o = _case(box, """
        const { root, c } = await mount();
        const a = nodeOf(root, 'a'), p0 = at(a);
        fire(a, 'keydown', { key: 'ArrowRight' });
        fire(a, 'keydown', { key: 'ArrowDown', shiftKey: true });
        const p1 = at(nodeOf(root, 'a'));
        const beforeSave = prefWrites().length;
        await c.flush();
        out({ p0, p1, beforeSave, saved: server.prefs, edgeFollowed: edgeEls(root)[0]
                .querySelectorAll('path')[1].getAttribute('d') });
    """)
    p0, p1 = o["p0"], o["p1"]
    assert (p1["x"] - p0["x"], p1["y"] - p0["y"]) == (16, 64)
    assert o["saved"] == {"v": 1, "tasks": {"a": [p1["x"], p1["y"]]}}
    # The arrow leaving `a` starts at `a`'s new right edge.
    assert o["edgeFollowed"].startswith("M %g " % (p1["x"] + 232)), o["edgeFollowed"]


def test_dragging_a_step_moves_it_saves_it_and_does_not_open_it(box):
    o = _case(box, """
        const { root } = await mount();
        const a = nodeOf(root, 'a'), p0 = at(a);
        fire(a, 'pointerdown', { clientX: p0.x + 10, clientY: p0.y + 10 });
        fire(a, 'pointermove', { clientX: p0.x + 12, clientY: p0.y + 11 });
        const afterNudge = at(nodeOf(root, 'a'));
        fire(a, 'pointermove', { clientX: p0.x + 10 + 150, clientY: p0.y + 10 + 333 });
        fire(a, 'pointerup', { clientX: p0.x + 10 + 150, clientY: p0.y + 10 + 333 });
        fire(a, 'click');
        await settle(5);
        out({ p0, afterNudge, p1: at(nodeOf(root, 'a')), saved: server.prefs, mounts: panel.mounts.length });
    """)
    assert o["afterNudge"] == o["p0"], "under MOVE_THRESHOLD a press is still a click"
    assert o["p1"] == {"x": o["p0"]["x"] + 150, "y": o["p0"]["y"] + 333}
    assert o["saved"] == {"v": 1, "tasks": {"a": [o["p1"]["x"], o["p1"]["y"]]}}
    assert o["mounts"] == 0, "the click a browser fires after a drag does not open the step"


def test_a_saved_position_is_where_the_step_is_drawn(box):
    o = _case(box, """
        const { root } = await mount();
        out({ b: at(nodeOf(root, 'b')) });
    """, prefs={"v": 1, "tasks": {"b": [700, 520], "deleted": [1, 1]}})
    assert o["b"] == {"x": 700, "y": 520}


def test_drawing_an_arrow_does_not_move_the_steps_already_on_the_canvas(box):
    o = _case(box, """
        const { root } = await mount();
        const before = Object.fromEntries(['a', 'b', 'c'].map((id) => [id, at(nodeOf(root, id))]));
        const port = portOf(nodeOf(root, 'b'), 'success'), c = before.c;
        fire(port, 'pointerdown', {}); fire(port, 'pointerup', { clientX: c.x + 5, clientY: c.y + 5 });
        await settle(5);
        const after = Object.fromEntries(['a', 'b', 'c'].map((id) => [id, at(nodeOf(root, id))]));
        out({ before, after, writes: writes().length });
    """)
    assert o["writes"] == 1
    assert o["after"] == o["before"]


# ── removing an arrow ───────────────────────────────────────────────────────

def test_delete_on_a_focused_arrow_says_which_first_and_removes_it_second(box):
    o = _case(box, """
        const { root } = await mount();
        const g = edgeEls(root)[0];
        fire(g, 'focus');
        const onFocus = said(root);
        fire(g, 'keydown', { key: 'Delete' });
        const first = { said: said(root), writes: writes().length };
        fire(g, 'keydown', { key: 'Delete' });
        await settle(5);
        out({ onFocus, first, writes: writes(), said: said(root), edges: edges(root), focusedA: read(root, 'a').focused });
    """)
    assert o["onFocus"] == "After Nightly backup, if it works, Post summary runs."
    assert o["first"]["writes"] == 0
    assert o["first"]["said"] == ("Remove this arrow? After Nightly backup, if it works, Post summary runs."
                                  " Press Delete again to remove it, or Escape to keep it.")
    assert o["writes"] == [{"url": "/api/tasks/a", "method": "PUT", "body": {"then_task_id": ""}}]
    assert o["edges"] == []
    assert o["said"] == "Removed. Post summary no longer runs after Nightly backup if it works."
    assert o["focusedA"] is True


def test_escape_between_the_two_presses_keeps_the_arrow(box):
    o = _case(box, """
        const { root } = await mount();
        const g = edgeEls(root)[0];
        fire(g, 'focus'); fire(g, 'keydown', { key: 'Delete' });
        const escaped = dismissTopMenu();
        fire(g, 'keydown', { key: 'Delete' });
        await settle(5);
        out({ escaped, writes: writes().length, said: said(root), edges: edges(root).length });
    """)
    assert o["escaped"] is True
    assert o["writes"] == 0, "the press after Escape asks again rather than removing"
    assert o["said"].startswith("Remove this arrow?")
    assert o["edges"] == 1


def test_the_mouse_removes_an_arrow_through_the_button_its_sentence_carries(box):
    o = _case(box, """
        const { root } = await mount();
        fire(edgeEls(root)[0], 'click');
        const action = root.querySelector('.wb-say-action');
        const shown = { hidden: action.hidden, text: action.textContent };
        fire(action, 'click');
        await settle(5);
        out({ shown, writes: writes() });
    """)
    assert o["shown"] == {"hidden": False, "text": "Remove this arrow"}
    assert o["writes"] == [{"url": "/api/tasks/a", "method": "PUT", "body": {"then_task_id": ""}}]


# ── a hostile name stays a name ─────────────────────────────────────────────

_EVIL = '<img src=x onerror="globalThis.__pwned=1">'


def test_a_hostile_task_name_is_set_as_text_everywhere_it_appears(box):
    """The step, its title tooltip, the arrow's words, the Connect… picker, the
    side panel's heading and every sentence the canvas says: each reaches the
    page as text. `_html` is non-empty only where markup was assigned."""
    tasks = json.loads(json.dumps(_TASKS))
    tasks[0]["name"] = _EVIL
    tasks[0]["trigger_words"] = "<b>bold</b>"
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'b').querySelector('.wb-node-connect'), 'click');
        const option = root.querySelector('.wb-connect-to').querySelectorAll('option')
          .find((x) => x.value === 'a').textContent;
        dismissTopMenu();
        fire(edgeEls(root)[0], 'focus');
        const sentence = said(root);
        fire(nodeOf(root, 'a'), 'click');
        out({ title: read(root, 'a').title, sub: read(root, 'a').sub, option, sentence,
              heading: root.querySelector('.wb-panel-title').textContent,
              markup: markup(root), pwned: globalThis.__pwned || 0 });
    """, tasks=tasks)
    assert o["title"] == _EVIL
    assert o["sub"] == "Action · <b>bold</b>"
    assert o["option"] == _EVIL
    assert o["heading"] == _EVIL
    assert _EVIL in o["sentence"]
    assert o["markup"] == [], o["markup"]
    assert o["pwned"] == 0


# ── the side panel is the task form, mounted ────────────────────────────────

def test_selecting_a_step_mounts_the_form_with_that_task_and_the_whole_list(box):
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'b'), 'click');
        const m = panel.mounts[0];
        let up = m.host, inside = false;
        while (up) { if (up === root) { inside = true; break; } up = up.parentNode; }
        out({ count: panel.mounts.length, task: m.args.task, ids: m.args.tasks.map((t) => t.id),
              fns: [typeof m.args.onSaved, typeof m.args.onCancel], inside,
              hostClass: m.host.className, open: !root.querySelector('.wb-panel').hidden,
              heading: root.querySelector('.wb-panel-title').textContent,
              selected: nodeOf(root, 'b')._classes().includes('wb-node-selected') });
    """)
    assert o["count"] == 1
    # The row exactly as `GET /api/tasks` served it — not a summary of it.
    assert o["task"] == {**_TASKS[1]}
    assert o["ids"] == ["a", "b", "c"]
    assert o["fns"] == ["function", "function"]
    assert o["inside"] is True and o["hostClass"] == "wb-panel-host"
    assert o["open"] is True and o["heading"] == "Message me" and o["selected"] is True


def test_after_a_save_the_canvas_redraws_from_a_fresh_fetch(box):
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'b'), 'click');
        const m = panel.mounts[0];
        server.tasks[1].name = 'Message me on Matrix';
        const before = reads();
        await m.args.onSaved({ ...server.tasks[1] });
        await settle(5);
        out({ refetched: reads() - before, title: read(root, 'b').title, destroyed: m.destroyed,
              open: !root.querySelector('.wb-panel').hidden, said: said(root), focused: read(root, 'b').focused });
    """)
    assert o["refetched"] == 1
    assert o["title"] == "Message me on Matrix"
    assert o["destroyed"] is True
    assert o["open"] is False
    assert o["said"] == "Saved Message me on Matrix."
    assert o["focused"] is True


def test_cancel_and_escape_close_the_panel_and_hand_the_focus_back(box):
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'c'), 'keydown', { key: 'Enter' });
        const first = panel.mounts[0];
        first.args.onCancel();
        const afterCancel = { open: !root.querySelector('.wb-panel').hidden, destroyed: first.destroyed,
                              focused: read(root, 'c').focused };
        nodeOf(root, 'c').focused = false;
        fire(nodeOf(root, 'c'), 'click');
        const escaped = dismissTopMenu();
        out({ afterCancel, escaped, second: panel.mounts[1].destroyed, focused: read(root, 'c').focused,
              open: !root.querySelector('.wb-panel').hidden });
    """)
    assert o["afterCancel"] == {"open": False, "destroyed": True, "focused": True}
    assert o["escaped"] is True and o["second"] is True
    assert o["open"] is False and o["focused"] is True


def test_new_step_mounts_the_form_for_a_new_task(box):
    o = _case(box, """
        const { root } = await mount();
        fire(root.querySelector('.wb-tool-new'), 'click');
        out({ task: panel.mounts[0].args.task, n: panel.mounts[0].args.tasks.length,
              heading: root.querySelector('.wb-panel-title').textContent });
    """)
    assert o["task"] is None and o["n"] == 3 and o["heading"] == "New step"


def test_an_empty_list_says_what_a_step_is_and_offers_the_first_one(box):
    o = _case(box, """
        const { root } = await mount();
        const empty = root.querySelector('.wb-empty');
        fire(empty.querySelector('.wb-tool-new'), 'click');
        out({ hidden: empty.hidden, text: empty.readable, task: panel.mounts[0].args.task });
    """, tasks=[])
    assert o["hidden"] is False
    assert o["text"].startswith("No automations yet.")
    assert o["task"] is None


# ── opening on one workflow ─────────────────────────────────────────────────

def test_opening_on_a_task_shows_its_workflow_and_focuses_it(box):
    o = _case(box, """
        const { root } = await mount({ focusId: 'c' });
        out({ a: read(root, 'a'), b: read(root, 'b'), c: read(root, 'c'), said: said(root) })
    """)
    assert o["c"]["focused"] is True
    assert o["a"]["chain"] is True and o["c"]["chain"] is True and o["b"]["chain"] is False
    assert o["said"] == "Post summary is one of 2 steps in this workflow."


def test_a_chain_to_a_task_nobody_here_can_see_is_drawn_and_not_offered(box):
    tasks = json.loads(json.dumps(_TASKS))
    tasks[1]["then_task_id"] = "someone-elses"
    o = _case(box, """
        const { root } = await mount();
        const ghost = nodeOf(root, 'someone-elses');
        out({ ghost: ghost && { hidden: ghost.getAttribute('aria-hidden'), text: ghost.readable,
                                ports: ghost.querySelectorAll('.wb-port').length,
                                connect: !!ghost.querySelector('.wb-node-connect'),
                                tab: ghost.getAttribute('tabindex') },
              edge: edges(root).find((e) => e.from === 'b') });
    """, tasks=tasks)
    assert o["ghost"] == {"hidden": "true", "text": "A task you cannot see Not in your list of tasks",
                          "ports": 0, "connect": False, "tab": None}
    assert o["edge"]["label"].startswith("After Message me, if it works, a task you cannot see runs.")
