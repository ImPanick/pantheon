# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-11`, `P22-12`, `P22-17` (wf-canvas) — a waiting run opens on the step it waits on, and is answered there; a For-each step's items are each a line.

A run that reaches a step needing a yes, a Wait, or a foreground takeover parks
as `waiting` (design § 1.4, § 1.5; C-W: "`GET /api/workflows/{id}/runs/{run_id}`:
records gain `item`, `waiting{kind,since,until,approval}`; status may be
`waiting`"). The row: "the card reaches notifications **and the executions
view**". So in the Workbench's Runs, a waiting run opens on its waiting step —
"without being told where to look", as a failed run opens on its failed step
(`P22-07`) — the step says what it waits for on the canvas, its record panel
holds the card, and *Allow once* posts `approve_task` (C-W's answer route),
after which the run is drawn again in the server's words. A For-each step's
item records (`item = i`) are listed one line each: "Item 3 of 5: Failed — …"
(`P22-12`'s `Verify:`, the Runs half). The notice's *Open the run* reaches the
same view through the room's `openRun(workflowId, runId)`.

Driven: the real room (`workflowRoom.js`), canvas, panels and source over the
real `workflowApi.js` with C-W's four functions, answered by the C-W fake
server (`tests/helpers/workflow_cw_fake.py`).
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

_APPROVAL = {"approval_id": "ap1", "question": "Allow this exact action once?",
             "action": {"tool": "send_reply", "content": "Thanks, Ann — Thursday works.", "effects": ["sends_external"],
                        "digest": "ab12cd34"}}

_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "import { server as cw, net as cwnet, seed, cwApi } from './cwfake.js';\n"
    "const { mountAutomations } = await import('./workflowRoom.js');\n"
    "const { createWorkflowSource } = await import('./workflowSource.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "cw.palette = %s;\n"
    "const APPROVAL = %s;\n"
    "const node = (id, kind, label, config = {}) => ({ id, kind, label, config, position: null, pinned: null });\n"
    "const GRAPH = { v: 1, start: { position: null }, nodes: [\n"
    "  node('post', 'mcp', 'Post the summary', { tool: 'mcp__chat__send_message', args: { channel: '#ops', text: '{{ steps.start.data.body }}' } }),\n"
    "  node('reply', 'llm', 'Send reply', { prompt: 'Reply to it' }),\n"
    "  node('each', 'foreach', 'Each mail', { list: '{{ steps.start.data.mails }}', step: { kind: 'llm', label: 'Summarise', config: { prompt: 'x' } } })],\n"
    "  edges: [{ from: 'start', port: 'success', to: 'post' }, { from: 'start', port: 'success', to: 'reply' },\n"
    "          { from: 'reply', port: 'success', to: 'each' }] };\n"
    "seed({ id: 'wf1', name: 'Overnight replies', task_id: 't1', trigger_status: 'active', version: 4,\n"
    "  trigger_task: { id: 't1', status: 'active' }, graph: GRAPH });\n"
    "const rec = (node_id, status, more = {}) => ({ id: node_id + ':' + (more.item == null ? '' : more.item), node_id,\n"
    "  kind: 'llm', label: more.label || node_id, seq: 1, status, attempt: 1, dry: false, port: status === 'error' ? 'error' : 'success',\n"
    "  started_at: '2026-10-02T03:10:00Z', finished_at: status === 'waiting' ? null : '2026-10-02T03:11:00Z',\n"
    "  input: null, output: { text: more.text || '', data: null }, error: more.error || null, steps: [], item: null, ...more });\n"
    "cw.runs = [{ id: 'r1', task_id: 't1', status: 'waiting', started_at: '2026-10-02T03:10:00Z', steps: [] }];\n"
    "cw.executions.r1 = { run: { id: 'r1', status: 'waiting' }, graph: GRAPH, version_kept: true, cleared: false, nodes: [\n"
    "  rec('post', 'success', { label: 'Post the summary', text: 'Posted to #ops.' }),\n"
    "  rec('reply', 'waiting', { label: 'Send reply', waiting: { kind: 'approval', since: '2026-10-02T03:12:00Z',\n"
    "    until: '2026-10-02T15:12:00Z', approval: APPROVAL } })] };\n"
    "cw.onAnswer = (runId, body) => {\n"
    "  const ex = cw.executions[runId];\n"
    "  const r = ex.nodes.find((n) => n.node_id === body.node_id);\n"
    "  r.status = body.decision === 'deny' ? 'error' : 'success'; r.waiting = null;\n"
    "  ex.run.status = body.decision === 'deny' ? 'error' : 'running';\n"
    "  cw.runs[0].status = ex.run.status;\n"
    "};\n"
    "const mountTaskFields = () => ({ destroy() {} });\n"
    "const room = async (o = {}) => {\n"
    "  const r = host();\n"
    "  const handle = mountAutomations(r, { fetch: cwnet, mountTaskFields, describeTrigger: () => 'On a webhook',\n"
    "    loadWorkflowModules: async () => ({ createWorkflowApi: () => cwApi(cwnet), createWorkflowSource }), ...o });\n"
    "  await handle.ready; await settle(10);\n"
    "  return { r, handle };\n"
    "};\n"
    "const runPanel = (root) => root.querySelector('.wf-run-canvas');\n"
    "const said = (root) => runPanel(root).querySelector('.wb-say-text').textContent;\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("waiting"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % (palette_json(), json.dumps(_APPROVAL)), script)


def test_a_waiting_run_opens_on_its_waiting_step_with_its_card_and_allow_once_goes_on(box):
    o = _case(box, """
        const { r } = await room({ workflowId: 'wf1' });
        fire(r.querySelectorAll('.wf-tab').find((t) => t.dataset.tab === 'runs'), 'click');
        await settle(20);
        const rp = runPanel(r);
        const reply = rp.querySelectorAll('.wb-node').find((n) => n.dataset.itemId === 'reply');
        const before = {
          said: said(r), title: rp.querySelector('.wb-panel-title').textContent, open: !rp.querySelector('.wb-panel').hidden,
          node: [reply.dataset.outcome, reply.querySelector('.wb-node-word').textContent],
          head: rp.querySelector('.wf-record-waiting-head').textContent.split(' · ')[0],
          card: rp.querySelector('.wf-record-waiting').querySelectorAll('button').map((b) => [b.textContent, b.dataset.decision]),
          action: rp.querySelector('.skill-test-out').textContent.split('\\n')[0],
          runWord: r.querySelector('.wf-run-word').textContent,
        };
        fire(rp.querySelectorAll('button').find((b) => b.dataset.decision === 'approve_task'), 'click');
        await settle(30);
        const reply2 = runPanel(r).querySelectorAll('.wb-node').find((n) => n.dataset.itemId === 'reply');
        out({ before,
              answers: cw.calls.filter((c) => c.url.endsWith('/answer')).map((c) => [c.url, c.body]),
              after: { said: said(r), node: [reply2.dataset.outcome, reply2.querySelector('.wb-node-word').textContent],
                       cardSaid: (runPanel(r).querySelector('.wf-record-waiting-said') || { textContent: '' }).textContent },
              markup: markup(r).filter((m) => !m.includes('task-run-step')) });
    """)
    b = o["before"]
    assert b["title"] == "Send reply" and b["open"] is True, "opened on the step it waits on, without being told where"
    assert b["said"] == "“Send reply” is waiting for your yes. Its question is open beside it: Allow once, or Deny."
    assert b["node"] == ["pending", "Waiting for your yes"], "the step says what it waits for, a shape before a hue"
    assert b["head"] == "Waiting for your yes"
    assert b["card"] == [["Deny", "deny"], ["Allow once", "approve_task"]]
    assert b["action"] == "send_reply"
    assert b["runWord"] in ("waiting", "Waiting"), "runStatus.js's word for the run (wf-walker teaches it 'Waiting')"
    assert o["answers"] == [["/api/workflows/wf1/runs/r1/answer",
                             {"node_id": "reply", "item": None, "approval_id": "ap1", "decision": "approve_task"}]]
    assert o["after"]["said"] == "Allowed once by joseph at 07:42: send_reply. The run goes on.", "the server's words"
    assert o["after"]["node"] == ["ok", "Success"], "the run is drawn again"
    assert o["after"]["cardSaid"] == "Allowed once by joseph at 07:42: send_reply. The run goes on."
    assert o["markup"] == []


def test_a_wait_says_until_when_and_a_takeover_says_it_runs_again_from_that_step(box):
    o = _case(box, """
        cw.executions.r1.nodes[1].waiting = { kind: 'time', since: '2026-10-02T03:12:00Z', until: '2026-10-02T08:00:00Z' };
        const { r } = await room({ workflowId: 'wf1' });
        fire(r.querySelectorAll('.wf-tab').find((t) => t.dataset.tab === 'runs'), 'click');
        await settle(20);
        const rp = runPanel(r);
        const time = { said: said(r), buttons: rp.querySelector('.wf-record-waiting').querySelectorAll('button').length,
          note: rp.querySelector('.wf-record-waiting').querySelectorAll('.wf-record-note').map((n) => n.textContent)[0].slice(0, 14) };
        cw.executions.r1.nodes[1].waiting = { kind: 'idle', since: '2026-10-02T03:12:00Z' };
        fire(r.querySelector('.wf-run-item'), 'click');
        await settle(20);
        out({ time, idle: said(r), idleNote: runPanel(r).querySelector('.wf-record-waiting').querySelectorAll('.wf-record-note')[0].textContent });
    """)
    assert o["time"]["said"].startswith("“Send reply” is waiting until ") and o["time"]["said"].endswith(". The run goes on by itself.")
    assert o["time"]["buttons"] == 0 and o["time"]["note"] == "It goes on at "
    assert o["idle"] == "“Send reply” is waiting for Pantheon to be idle; the run goes on from that step."
    assert o["idleNote"].endswith("the steps before it are not run again.")


def test_a_for_each_steps_items_are_each_a_line_and_the_failed_one_is_named(box):
    o = _case(box, """
        cw.runs[0].status = 'error';
        const items = [0, 1, 2, 3, 4].map((i) => rec('each', i === 2 ? 'error' : 'success',
          { item: i, label: 'Summarise · item ' + (i + 1) + ' of 5', text: 'Summary ' + (i + 1),
            error: i === 2 ? 'The model refused: too long.' : null }));
        cw.executions.r1 = { run: { id: 'r1', status: 'error' }, graph: GRAPH, nodes: [
          rec('post', 'success'), rec('reply', 'success'), ...items,
          rec('each', 'error', { label: 'Each mail', error: 'Item 3 of 5 failed: The model refused: too long.' })] };
        const { r } = await room({ workflowId: 'wf1' });
        fire(r.querySelectorAll('.wf-tab').find((t) => t.dataset.tab === 'runs'), 'click');
        await settle(20);
        const rp = runPanel(r);
        out({ said: said(r), title: rp.querySelector('.wb-panel-title').textContent,
              summary: rp.querySelector('.wf-record-items').querySelector('summary').textContent,
              open: !!rp.querySelector('.wf-record-items').open,
              lines: rp.querySelectorAll('.wf-record-item').map((li) => [li.dataset.tone, li.querySelector('.wf-record-item-word').textContent]) });
    """)
    assert o["title"] == "Each mail"
    assert o["said"] == "“Each mail” failed: Item 3 of 5 failed: The model refused: too long. Its panel is open at What it was handed."
    assert o["summary"] == "Items (5)" and o["open"] is True
    assert o["lines"] == [
        ["ok", "Item 1 of 5: Success — Summary 1"], ["ok", "Item 2 of 5: Success — Summary 2"],
        ["error", "Item 3 of 5: Failed — The model refused: too long."],
        ["ok", "Item 4 of 5: Success — Summary 4"], ["ok", "Item 5 of 5: Success — Summary 5"]]


def test_open_the_run_from_the_notice_opens_the_room_on_it(box):
    o = _case(box, """
        const { r, handle } = await room();
        const fromTasks = !r.querySelector('.wf-view') || r.querySelector('.wf-view').hidden;
        await handle.openRun('wf1', 'r1');
        await settle(30);
        const rp = runPanel(r);
        out({ fromTasks, tab: r.querySelectorAll('.wf-tab').find((t) => t.getAttribute('aria-selected') === 'true').textContent,
              title: rp.querySelector('.wb-panel-title').textContent, said: said(r) });
    """)
    assert o["fromTasks"] is True
    assert o["tab"] == "Runs" and o["title"] == "Send reply"
    assert o["said"].startswith("“Send reply” is waiting for your yes.")
