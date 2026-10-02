# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-09` (wf-canvas) — a field is picked from a list of what earlier steps made, and a field that may never take one says why.

`D-2026-10-01-05` §2: data moves between steps by picking a field, never by
writing an expression. The design's picker (§ 2's P22-09, `fieldPicker.js`)
"lists upstream steps and their fields with an example value and where each
came from (*from the last run, 2 Oct 07:00* / *from the pinned sample* /
*what the step promises to answer*). It inserts `{{ steps.<id>.data.<path> }}`
at the caret. Under each field the panel says, in words, *Uses: title, from
“Fetch issue”*. … `never` fields show no picker and show the reason." Which
field is which is the server's answer (C-W's palette `slots`, from
`src/workflow_slots.py`) — the browser derives nothing, and a field with no
slot is offered nothing (fails closed). `P22-09`'s `Verify:` second half:
"mapping a field into a shell command is refused with the reason on the
field" — the server's refusal carries `field` (C-W), and the room opens that
step with the sentence on that field.

Driven: the real `fieldPicker.js` over the real `workflowSource.js:listFields`
(C-W's fields route on the fake server); the real task form
(`tasks/taskFields.js`, `'node'` mode) with its new hooks and the real
`decorateField`; and the real room (`workflowRoom.js`) with the real source,
whose refused save opens the step the refusal names.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from test_one_task_form_in_two_places_js import (  # noqa: E402
    _SHIM_PARSED, _STUBS as _FORM_STUBS, _PREAMBLE as _FORM_PREAMBLE, _ROUTES_JS, TASKS_JS)
from helpers.workflow_cw_fake import build_sandbox, palette_json, PALETTE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The three origins are the server's own words (`integrate-d`: this list once
# said "pinned", which the server never sends — it sends `ORIGIN_PIN`).
from src.workflow_effects import ORIGIN_DECLARED, ORIGIN_LAST_RUN, ORIGIN_PIN  # noqa: E402

_SOURCES = {"sources": [
    {"node_id": "fetch-issue", "label": "Fetch issue", "kind": "http", "origin": ORIGIN_LAST_RUN, "at": "2026-10-02T07:00:00Z",
     "fields": [
         {"ref": "{{ steps.fetch-issue.data.title }}", "path": "title", "type": "text",
          "example": "Login fails <img src=x onerror=alert(1)>"},
         {"ref": "{{ steps.fetch-issue.data.labels }}", "path": "labels", "type": "list", "example": ["bug", "p1"]}]},
    {"node_id": "classify", "label": "Classify", "kind": "llm", "origin": ORIGIN_DECLARED,
     "fields": [{"ref": "{{ steps.classify.data.urgent }}", "path": "urgent", "type": "yes/no"}]},
    {"node_id": "start", "label": "The start", "kind": "start", "origin": ORIGIN_PIN,
     "fields": [{"ref": "{{ steps.start.data.body }}", "path": "body", "type": "text", "example": "Hello"}]},
]}

_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "import { server as cw, net as cwnet, seed, cwApi } from './cwfake.js';\n"
    "const { decorateField, openFieldPicker, usesLine, refsIn } = await import('./fieldPicker.js');\n"
    "const { createWorkflowSource } = await import('./workflowSource.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "cw.palette = %s;\n"
    "cw.fields = { sum: %s };\n"
    "const node = (id, kind, label, config = {}) => ({ id, kind, label, config, position: null, pinned: null });\n"
    "seed({ id: 'wf1', name: 'Issues', task_id: 't1', trigger_status: 'paused', version: 2,\n"
    "  trigger_task: { id: 't1', status: 'paused' }, graph: { v: 1, start: { position: null },\n"
    "  nodes: [node('fetch-issue', 'http', 'Fetch issue', { integration: 'int1', method: 'GET', path: '/issue' }),\n"
    "          node('classify', 'llm', 'Classify', { prompt: 'x' }), node('sum', 'llm', 'Summarise', { prompt: 'x' })],\n"
    "  edges: [{ from: 'fetch-issue', port: 'success', to: 'classify' }, { from: 'classify', port: 'success', to: 'sum' }] } });\n"
    "const root = host();\n"
    "const field = (tag = 'textarea') => { const wrap = root.appendChild(new Node('div')); const i = wrap.appendChild(new Node(tag)); return i; };\n"
    "const typed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'input', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const slotBox = (i) => i.parentNode.querySelector('.wf-slot');\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("picker"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % (palette_json(), json.dumps(_SOURCES)), script)


def test_insert_a_field_lists_what_earlier_steps_made_and_puts_the_pick_at_the_caret(box):
    o = _case(box, """
        const src = createWorkflowSource({ api: cwApi(cwnet), workflowId: 'wf1' });
        await src.ready;
        const up = src.upstreamOf('sum');
        const labelOf = (id) => (up.find((u) => u.id === id) || {}).label;
        const ta = field();
        ta.value = 'Summarise the issue  for me.';
        ta.selectionStart = 20; ta.selectionEnd = 20;
        const h = decorateField(ta, { slot: { mapping: 'value', why: '' }, field: 'prompt', labelOf,
          pick: (anchor) => openFieldPicker(anchor, { load: () => src.listFields('sum'), layer: () => root }) });
        const btn = slotBox(ta).querySelector('.wf-slot-pick');
        fire(btn, 'click');
        await settle(5);
        const picker = root.querySelector('.wf-picker');
        const listed = picker.querySelectorAll('.wf-picker-source').map((s) => ({
          step: s.querySelector('.wf-picker-step-name').textContent,
          from: (s.querySelector('.wf-picker-origin') || { textContent: '' }).textContent,
          fields: s.querySelectorAll('.wf-picker-field').map((b) => [b.querySelector('.wf-picker-path').textContent,
            (b.querySelector('.wf-picker-example') || { textContent: '' }).textContent]) }));
        const req = cw.calls.filter((c) => c.url.includes('/fields')).map((c) => [c.method, c.url]);
        const title = picker.querySelectorAll('.wf-picker-field').find((b) => b.dataset.ref === '{{ steps.fetch-issue.data.title }}');
        fire(title, 'click');
        await settle(5);
        out({ up, listed, req, value: ta.value, uses: slotBox(ta).querySelector('.wf-slot-uses').textContent,
              gone: !root.querySelector('.wf-picker'), markup: markup(root),
              unsaved: await src.listFields('nope') });
    """)
    assert o["up"] == [{"id": "classify", "label": "Classify", "kind": "llm"},
                       {"id": "fetch-issue", "label": "Fetch issue", "kind": "http"},
                       {"id": "start", "label": "The start", "kind": "start"}], "the steps before it, and the start"
    assert o["req"] == [["GET", "/api/workflows/wf1/nodes/sum/fields"]], "C-W's route, spelled whole"
    assert [s["step"] for s in o["listed"]] == ["Fetch issue", "Classify", "The start"]
    assert o["listed"][0]["from"].startswith("from the last run, ")
    assert o["listed"][1]["from"] == "what the step promises to answer"
    assert o["listed"][2]["from"] == "from the pinned sample"
    assert o["listed"][0]["fields"] == [["title", "Login fails <img src=x onerror=alert(1)>"], ["labels", '["bug","p1"]']]
    assert o["value"] == "Summarise the issue {{ steps.fetch-issue.data.title }} for me.", "at the caret"
    assert o["uses"] == "Uses: title, from “Fetch issue”."
    assert o["gone"] is True and o["markup"] == [], "an example from outside is text"
    assert o["unsaved"] == {"ok": False, "sentence": "Save the workflow first: the fields other steps made are listed for a saved step."}


def test_a_never_field_offers_no_picker_and_says_why_and_says_no_to_a_typed_reference(box):
    o = _case(box, """
        const why = 'Typed here only: it says what runs, so a field from another step can never fill it.';
        const inp = field('input');
        const h = decorateField(inp, { slot: { mapping: 'never', why }, field: 'prompt', pick: async () => 'X' });
        const first = { pick: !!slotBox(inp).querySelector('.wf-slot-pick'), never: slotBox(inp).querySelector('.wf-slot-never').textContent };
        typed(inp, 'curl {{ steps.fetch-issue.data.title }}');
        const refused = { text: slotBox(inp).querySelector('.wf-slot-never').textContent,
          cls: slotBox(inp)._classes().includes('wf-slot-refused') };
        const picked = await h.pick();
        const p = slotBox(inp).querySelector('.wf-slot-problem');
        const problem = { hidden: p.hidden, textContent: p.textContent };
        typed(inp, 'curl \\\\{{ literal');
        const escaped = slotBox(inp)._classes().includes('wf-slot-refused');
        // A field the palette gave no slot is offered nothing at all.
        const bare = field('input');
        decorateField(bare, { slot: null, field: 'x', pick: async () => 'X' });
        out({ first, refused, picked, problem: [problem.hidden, problem.textContent], value: inp.value, escaped,
              bare: { pick: !!slotBox(bare).querySelector('.wf-slot-pick'), never: !!slotBox(bare).querySelector('.wf-slot-never') } });
    """)
    why = "Typed here only: it says what runs, so a field from another step can never fill it."
    assert o["first"] == {"pick": False, "never": why}
    assert o["refused"] == {"text": "Not here: " + why, "cls": True}
    assert o["picked"] is None and o["problem"] == [False, why], "a never field is never handed a reference"
    assert o["escaped"] is False, "\\{{ is literal text, not a reference"
    assert o["bare"] == {"pick": False, "never": False}, "no slot from the server: nothing offered (fails closed)"


def test_the_words_under_a_field_name_what_it_uses(box):
    o = _case(box, """
        const labelOf = (id) => ({ 'fetch-issue': 'Fetch issue', sum: 'Summarise' })[id];
        out({
          uses: usesLine('{{ steps.fetch-issue.data.title }} / {{steps.sum.text}} / {{ steps.start.data.body[0] }} / {{ item.subject }}', labelOf),
          none: usesLine('nothing here, \\\\{{ steps.x.data.y }} is literal, {{ STEPS.x.data }} is not one', labelOf),
          refs: refsIn('{{ steps.a.data }} {{steps.b-2.text}}').map((r) => [r.node, r.field, r.path]),
        });
    """)
    assert o["uses"] == ("Uses: title, from “Fetch issue”; its text, from “Summarise”; body[0], from the start; "
                         "subject, from each item.")
    assert o["none"] == ""
    assert o["refs"] == [["a", "data", ""], ["b-2", "text", ""]]


# ── the task form's step mode, with the hooks ───────────────────────────────

_FORM_EXTRA = r"""
const out = (o) => console.log(JSON.stringify(o));
const { decorateField } = await import('./workbench/fieldPicker.js');
const { mountAiOptions } = await import('./workbench/stepFields.js');
const PAL = %s;
const slotsOf = (k) => PAL.kinds.find((x) => x.kind === k).slots;
const decorated = [];
const pickField = (input, { field, slot }) => { decorated.push([field, slot ? slot.mapping : null]);
  return decorateField(input, { slot, field, pick: async () => '{{ steps.fetch-issue.data.title }}' }); };
const slotOf = (el) => el && el.parentNode ? el.parentNode.querySelector('.wf-slot') : null;
"""

_FORM_ROUTES = {
    "actions": {"actions": [
        {"name": "ssh_command", "description": "Run a command on a host", "category": "Hosts", "icon": "x",
         "model_backed": False, "admin_only": True,
         "params": [{"name": "command", "label": "Command", "type": "text", "required": True, "source": "prompt",
                     "description": "The command to run."}]}]},
    "targets": [{"value": "session", "label": "Session"}],
}


@pytest.fixture(scope="module")
def form(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("pickform"), TASKS_JS, _SHIM_PARSED, _FORM_STUBS)
    (box / "workbench").mkdir(exist_ok=True)
    for rel in ("workbench/fieldPicker.js", "workbench/stepFields.js", "workbench/argsForm.js",
                "skillGateNote.js", "settings/mcpFields.js", "tasks/workflowDiagram.js"):
        (box / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, box / rel)
    return box


def _form_case(form, script):
    return _run(form, _FORM_PREAMBLE, (_ROUTES_JS % json.dumps(_FORM_ROUTES))
                + (_FORM_EXTRA % json.dumps(PALETTE)) + script)


def _real_command_refusal() -> dict:
    """What the server says, and on which field, when a reference is put in
    `ssh_command`'s Command: the real rule's `DocumentRefusal` for that
    document — its `sentence`, and its `field` as the save route sends it
    (`WorkflowRefused.body`) — so the panel is tested against the server's
    words (`integrate-d`; this case handed the panel a hand-made refusal)."""
    from src import workflow_document as wd
    from src.workflow_store import refusal_from
    graph = wd.parse_graph({"v": 1, "nodes": [
        {"id": "fetch-issue", "kind": "llm", "label": "Fetch issue", "config": {"prompt": "Read it."}},
        {"id": "run-it", "kind": "action", "label": "Run it",
         "config": {"action": "ssh_command", "prompt": "ls {{ steps.fetch-issue.data.title }}"}}],
        "edges": [{"from": "fetch-issue", "port": "success", "to": "run-it"}]})
    refusal = wd.validate_document(graph, owner="root", tasks_by_id={}, crew_ids=set(),
                                   owner_is_admin=True, own_task_id=None,
                                   resources=wd.EMPTY_RESOURCES)
    assert refusal is not None and refusal.reason == wd.REFUSE_MAPPED_NEVER, refusal
    body = refusal_from(refusal).body()
    return {"sentence": body["detail"], "field": body["field"]}


def test_a_prompt_steps_prompt_takes_a_field_and_an_action_steps_command_says_why_not(form):
    problem = _real_command_refusal()
    assert problem["field"] == "prompt", "the Command field of an action is its `prompt`"
    o = _form_case(form, "const PROBLEM = %s;\n" % json.dumps(problem) + """
        const got = [];
        const a = hostIn();
        mountTaskFields(a, { mode: 'node', task: { name: 'Summarise', task_type: 'llm', prompt: 'Summarise ' },
          tasks: [], slots: slotsOf('llm'), pickField, onSaved: (r) => got.push(r) });
        await tick();
        const prompt = q(a, 'task-form-prompt');
        const box = slotOf(prompt);
        click(box.querySelector('.wf-slot-pick'));
        await tick();
        const b = hostIn();
        mountTaskFields(b, { mode: 'node', task: { name: 'Run it', task_type: 'action', action: 'ssh_command',
          prompt: 'ls {{ steps.fetch-issue.data.title }}' }, tasks: [], slots: slotsOf('action'), pickField,
          problem: PROBLEM });
        await tick();
        const cmd = q(b, 'task-form-action-param');
        const cbox = slotOf(cmd);
        out({ decorated, value: prompt.value, uses: box.querySelector('.wf-slot-uses').textContent,
              cmd: { pick: !!cbox.querySelector('.wf-slot-pick'), never: cbox.querySelector('.wf-slot-never').textContent,
                     refused: cbox._classes().includes('wf-slot-refused'),
                     problem: cbox.querySelector('.wf-slot-problem').textContent },
              topProblem: !!b.querySelector('.task-form-problem') });
    """)
    assert o["decorated"] == [["prompt", "value"], ["prompt", "never"]], "each step's stored text box, with the palette's slot"
    assert o["value"] == "Summarise {{ steps.fetch-issue.data.title }}"
    assert o["uses"] == "Uses: title, from “fetch-issue”."
    from src.workflow_slots import WHY_WHAT
    assert o["cmd"] == {"pick": False,
                        "never": f"Not here: {WHY_WHAT}",
                        "refused": True,
                        "problem": problem["sentence"]}, \
        "the server's refusal is said on the Command field"
    assert o["topProblem"] is False, "said on its field, not above the form"


def test_a_prompt_steps_ai_options_join_its_config_and_are_kept_when_not_drawn(form):
    o = _form_case(form, """
        const got = [];
        const a = hostIn();
        mountTaskFields(a, { mode: 'node', task: { name: 'Find it', task_type: 'llm', prompt: 'Find the page' },
          tasks: [], extra: (el) => mountAiOptions(el, { node: { config: {} }, palette: PAL }),
          onSaved: (r) => got.push(r) });
        await tick();
        const sel = a.querySelector('.wf-ai').querySelectorAll('select')[0];
        sel.value = 'only';
        sel.dispatchEvent({ type: 'change', target: sel, stopPropagation() {}, preventDefault() {} });
        for (const b of a.querySelectorAll('.wf-ai-tool-box')) b.checked = b.value === 'web_search' || b.value === 'web_fetch';
        const shaped = a.querySelector('.wf-ai-shaped-box');
        shaped.checked = true;
        shaped.dispatchEvent({ type: 'change', target: shaped, stopPropagation() {}, preventDefault() {} });
        const rows = a.querySelectorAll('.wf-ai')[0].querySelectorAll('.wf-sf-row');
        rows[0].querySelectorAll('input')[0].value = 'title';
        click(q(a, 'task-form-save'));
        await tick();
        // No section drawn (a Pantheon with no palette): what the step had is kept.
        const b = hostIn();
        mountTaskFields(b, { mode: 'node', task: { name: 'Kept', task_type: 'llm', prompt: 'p', tools: [],
          answer_fields: [{ name: 'url', type: 'text', description: '' }] }, tasks: [], onSaved: (r) => got.push(r) });
        await tick();
        click(q(b, 'task-form-save'));
        await tick();
        out({ got: got.map((g) => g.config), errors: ui.errors });
    """)
    assert o["errors"] == []
    assert o["got"][0]["tools"] == ["web_search", "web_fetch"]
    assert o["got"][0]["answer_fields"] == [{"name": "title", "type": "text", "description": ""}]
    assert o["got"][1]["tools"] == [] and o["got"][1]["answer_fields"] == [{"name": "url", "type": "text", "description": ""}]


def test_the_task_form_with_no_mode_draws_no_slot_and_no_extra(form):
    o = _form_case(form, """
        const a = hostIn();
        mountTaskFields(a, { task: { name: 'Plain', task_type: 'llm', prompt: 'x' }, tasks: [],
          slots: slotsOf('llm'), pickField, extra: () => { throw new Error('drawn'); } });
        await tick();
        out({ decorated, slot: !!a.querySelector('.wf-slot'), extra: !!q(a, 'task-form-step-extra') });
    """)
    assert o == {"decorated": [], "slot": False, "extra": False}, "the hooks are a step's only (Law 1)"


# ── the room: a refusal about a field opens that step on it ─────────────────

_ROOM = r"""
const { mountAutomations } = await import('./workflowRoom.js');
const { createWorkflowSource: realSource } = await import('./workflowSource.js');
const mounts = [];
const mountTaskFields = (h, args) => { mounts.push(args); return { destroy() {} }; };
const room = async () => {
  const r = host();
  const handle = mountAutomations(r, { fetch: cwnet, mountTaskFields, describeTrigger: () => 'Every day at 08:00',
    workflowId: 'wf1', loadWorkflowModules: async () => ({ createWorkflowApi: () => cwApi(cwnet), createWorkflowSource: realSource }) });
  await handle.ready; await settle(10);
  return { r, handle };
};
"""


def test_a_refused_save_about_a_field_opens_that_step_with_the_sentence_for_its_field(box):
    o = _case(box, _ROOM + """
        cw.doc.graph.nodes.push(node('run-it', 'action', 'Run it', { action: 'ssh_command', prompt: 'ls {{ steps.sum.text }}' }));
        cw.doc.graph.edges.push({ from: 'sum', port: 'success', to: 'run-it' });
        const SENTENCE = 'A field from another step cannot go into “Command”: it says what runs.';
        cw.check = (b) => (b.graph.nodes.some((n) => n.kind === 'action' && /\\{\\{/.test(n.config.prompt || ''))
          ? { status: 400, body: { detail: SENTENCE, reason: 'mapped_never', node_ids: ['run-it'], field: 'config.prompt' } } : null);
        const { r } = await room();
        const name = r.querySelector('.wf-name');
        name.value = 'Issues, summarised';
        name.dispatchEvent({ type: 'input', target: name, stopPropagation() {}, preventDefault() {} });
        fire(r.querySelector('.wf-save'), 'click');
        await settle(20);
        const opened = mounts[mounts.length - 1];
        out({ said: r.querySelectorAll('.wb-say-text').map((s) => s.textContent).filter(Boolean),
              title: r.querySelector('.wb-panel-title').textContent, panelHidden: r.querySelector('.wb-panel').hidden,
              problem: opened && opened.problem, mode: opened && opened.mode, kind: opened && opened.task.task_type });
    """)
    assert o["title"] == "Run it" and o["panelHidden"] is False, "the step the refusal names is opened"
    assert o["mode"] == "node" and o["kind"] == "action"
    assert o["problem"]["field"] == "config.prompt"
    assert o["problem"]["sentence"] == "A field from another step cannot go into “Command”: it says what runs."
    assert o["said"][-1] == "Not saved: A field from another step cannot go into “Command”: it says what runs."
