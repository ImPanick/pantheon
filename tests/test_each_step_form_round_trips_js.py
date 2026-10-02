# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-10`…`P22-18` (wf-canvas) — every new kind of step has a panel, and what it holds comes back out of it unchanged.

Slices C and D add ten kinds (`/work/notes/SLICE-CD-DESIGN.md` § 1.3, § 2's
`NODE_SLOTS` table): If, Switch, Set fields, Merge, Wait, For each item, HTTP
request, MCP tool, Skill, Code — and an AI step's tools and answer shape
(`P22-16`). Each is a form a person fills in without writing a condition in
any language (`D-2026-10-01-05` §2): a field picked from a list, one of six
words, a typed value. These cases drive `static/js/workbench/stepFields.js`
(`mountStepFields`, `mountAiOptions`) the way a person does: open a step with
its settings, press Done, and the step handed to the workflow's draft
(`onApply({ label, kind, config })`, no request) holds exactly those settings —
a key the form does not draw is kept as it came. A form refuses in words, on
the field the refusal is about. A For-each step's inner step is edited in
place, and its picker offers the item (`{{ item }}`, `{{ item.subject }}`).

The config shapes the panels write are this package's reading of § 1.4 and § 2
(For-each and Wait are spelled there; If/Switch/Set/HTTP/Code by their slot
paths); they are a merge point with `wf-rules`' `validate_document`, listed in
`wf-canvas`'s note.
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
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "const SF = await import('./stepFields.js');\n"
    "const { SKILL_GATE_NOTE } = await import('../skillGateNote.js');\n"
    "const { portsOfNode, portWordsOf } = await import('./workflowSource.js');\n"
    "const { createWorkflowPanels } = await import('./workflowPanels.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const PAL = %s;\n"
    "const mount = (node, more = {}) => {\n"
    "  const h = host();\n"
    "  const got = [];\n"
    "  const view = SF.mountStepFields(h, { node, palette: PAL, onApply: (s) => got.push(s), onCancel: () => got.push('cancel'), ...more });\n"
    "  return { h, got, view, done: () => fire(h.querySelector('.wf-step-done'), 'click') };\n"
    "};\n"
    "// The line goes right after its field in a browser (`insertBefore(nextSibling)`); the shim\n"
    "// has no `nextSibling`, so here it is read as: in the field's own group, naming the field.\n"
    "const problemOf = (h) => { const p = h.querySelector('.wf-sf-problem');\n"
    "  if (!p) return null;\n"
    "  const f = p.dataset.field || null;\n"
    "  const el = f ? h.querySelectorAll('[data-field]').find((n) => n.dataset.field === f && n !== p) : null;\n"
    "  return [p.textContent, el && el.parentNode === p.parentNode ? f : null]; };\n"
    "const typed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'input', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const changed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'change', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const byField = (h, f) => h.querySelectorAll('[data-field]').find((n) => n.dataset.field === f);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("stepforms"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % palette_json(), script)


_CONFIGS = {
    "if": {"join": "any", "conditions": [
        {"left": "{{ steps.read.text }}", "op": "contains", "right": "URGENT"},
        {"left": "{{ steps.read.data.n }}", "op": "is_empty"}]},
    "switch": {"cases": [
        {"id": "c1", "label": "Urgent", "join": "all", "conditions": [{"left": "{{ steps.read.text }}", "op": "contains", "right": "URGENT"}]},
        {"id": "c7", "label": "Billing", "join": "any", "conditions": [{"left": "{{ steps.read.data.amount }}", "op": "greater_than", "right": "100"}]}]},
    "set": {"fields": [{"name": "headline", "value": "{{ steps.read.data.subject }}"}, {"name": "n", "value": "3"}]},
    "merge": {"mode": "first"},
    "wait": {"mode": "until", "time": "08:00", "tz": "Europe/London"},
    "foreach": {"list": "{{ steps.read.data.emails }}", "on_error": "stop",
                "step": {"kind": "llm", "label": "Summarise", "config": {"prompt": "Summarise {{ item.subject }}"}}},
    "http": {"integration": "int1", "method": "POST", "path": "/v1/entries", "query": [{"name": "status", "value": "unread"}],
             "body": [{"name": "text", "value": "{{ steps.read.text }}"}], "body_mode": "json"},
    "mcp": {"tool": "mcp__chat__send_message", "args": {"channel": "#general", "text": "{{ steps.sum.text }}",
                                                         "silent": True, "priority": 2, "mood": "calm", "meta": {"a": 1}}},
    "skill": {"skill": "print-queue", "prompt": "Print today’s queue"},
    "code": {"language": "python", "source": "import json, sys\nprint(json.dumps({'total': 3}))\n", "timeout_seconds": 30,
             "input": [{"name": "prices", "value": "{{ steps.read.data.prices }}"}]},
}


def test_every_kind_hands_back_what_it_was_opened_with(box):
    o = _case(box, """
        const CONFIGS = %s;
        const back = {};
        for (const [kind, config] of Object.entries(CONFIGS)) {
          const m = mount({ id: 's-' + kind, kind, label: 'Step ' + kind, config: { ...config, kept_as_it_came: 7 } });
          m.done();
          back[kind] = m.got[0];
        }
        out({ back, markup: markup(document.body) });
    """ % json.dumps(_CONFIGS))
    for kind, config in _CONFIGS.items():
        got = o["back"][kind]
        assert got["kind"] == kind and got["label"] == "Step " + kind, kind
        assert got["config"] == {**config, "kept_as_it_came": 7}, (kind, got["config"])
    assert o["markup"] == [], "every form is built from nodes and text"


def test_a_form_refuses_in_words_on_the_field_it_is_about(box):
    o = _case(box, """
        const r = {};
        let m = mount({ kind: 'if', label: 'Check', config: { conditions: [{ left: '', op: 'equals', right: 'x' }] } });
        m.done(); r.if = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'wait', label: 'Hold', config: { mode: 'until', time: '8am' } });
        m.done(); r.wait = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'wait', label: 'Hold', config: { mode: 'for', minutes: 60 * 200 } });
        m.done(); r.long = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'set', label: 'Name', config: { fields: [{ name: 'a', value: '1' }, { name: 'a', value: '2' }] } });
        m.done(); r.set = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'http', label: 'Fetch', config: {} });
        m.done(); r.http = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'mcp', label: 'Post', config: { tool: 'mcp__chat__send_message', args: { text: 'hi' } } });
        m.done(); r.mcp = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'code', label: 'Total', config: { source: '   ' } });
        m.done(); r.code = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'switch', label: 'Sort', config: { cases: [{ id: 'c1', label: '', conditions: [{ left: 'x', op: 'equals', right: 'y' }] }] } });
        m.done(); r.switch = [problemOf(m.h), m.got.length];
        out(r);
    """)
    assert o["if"] == [["Pick the field this condition looks at.", "conditions[0].left"], 0]
    assert o["wait"] == [["Write the time as HH:MM, such as 08:00.", "time"], 0]
    assert o["long"] == [["A wait is at most 168 hours (workflow_wait_max_hours).", "minutes"], 0]
    assert o["set"] == [["“a” is set twice. Each name once.", "fields[1].name"], 0]
    assert o["http"] == [["Choose the integration it calls.", "integration"], 0]
    assert o["mcp"] == [["Fill in channel: the tool needs it.", "args.channel"], 0]
    assert o["code"] == [["Write the code it runs.", "source"], 0]
    assert o["switch"] == [["Name this case: its name is the words on its arrow.", "cases[0].label"], 0]


def test_a_wait_says_when_it_goes_on_and_every_wait_field_says_why_it_is_typed(box):
    o = _case(box, """
        const seen = [];
        const pickField = (input, { field, slot }) => { seen.push([field, slot ? slot.mapping : null]); return null; };
        const m = mount({ kind: 'wait', label: 'Until breakfast', config: { mode: 'until', time: '07:30' } }, { pickField });
        const said = m.h.querySelector('.wf-sf-wait-said').textContent;
        changed(byField(m.h, 'mode'), 'for');
        const forSaid = m.h.querySelector('.wf-sf-wait-said').textContent;
        out({ said, forSaid, seen });
    """)
    assert o["said"] == "It runs at 07:30, or as soon after as Pantheon is idle."
    assert o["forSaid"] == "Then it runs on as soon as Pantheon is idle."
    assert o["seen"] == [["minutes", "never"], ["time", "never"], ["tz", "never"]], "every Wait field is never (§ 2)"


def test_a_skill_step_says_p8_18s_sentence_and_code_starts_from_a_three_line_template(box):
    o = _case(box, """
        const s = mount({ kind: 'skill', label: 'Print', config: {} });
        const gate = s.h.querySelector('.wf-sf-gate').textContent;
        const c = mount({ kind: 'code', label: 'Total', config: {} });
        const src = byField(c.h, 'source');
        const py = src.value;
        changed(byField(c.h, 'language'), 'bash');
        const sh = src.value;
        src.value = 'echo mine';
        changed(byField(c.h, 'language'), 'python');
        const kept = src.value;
        const warn = c.h.querySelector('.wf-sf-warn').textContent;
        out({ gate, same: gate === SKILL_GATE_NOTE, py, pyLines: py.trim().split('\\n').length, sh, kept, warn });
    """)
    assert o["same"] is True and "stop halfway and wait" in o["gate"]
    assert o["pyLines"] == 3 and "json.load(sys.stdin)" in o["py"] and "print(json.dumps(" in o["py"]
    assert o["sh"].startswith("input=$(cat)")
    assert o["kept"] == "echo mine", "written code is never replaced by a template"
    from src.workstation_access import OFF_SENTENCE
    assert o["warn"] == OFF_SENTENCE, "the server's sentence (`workflow_effects.workstation_why`)"


def test_a_new_case_is_a_new_way_out_with_its_own_words(box):
    o = _case(box, """
        const m = mount({ kind: 'switch', label: 'Sort', config: { cases: [{ id: 'c1', label: 'Urgent',
          conditions: [{ left: '{{ steps.read.text }}', op: 'contains', right: 'URGENT' }] }] } });
        fire(m.h.querySelectorAll('.wf-sf-add').find((b) => b.textContent === 'Add a case'), 'click');
        const rows = m.h.querySelectorAll('.wf-sf-row').filter((r) => r.dataset.caseId);
        typed(byField(m.h, 'cases[1].label'), 'Billing');
        typed(byField(m.h, 'cases[1].conditions[0].left'), '{{ steps.read.data.amount }}');
        changed(byField(m.h, 'cases[1].conditions[0].op'), 'greater_than');
        typed(byField(m.h, 'cases[1].conditions[0].right'), '100');
        m.done();
        const node = { kind: 'switch', config: m.got[0].config };
        const ports = portsOfNode(node, PAL);
        out({ ids: rows.map((r) => r.dataset.caseId), cases: m.got[0].config.cases, ports, words: portWordsOf(node, ports) });
    """)
    assert o["ids"] == ["c1", "c2"], "a new case gets an id nothing else has, kept from then on"
    assert o["cases"][1] == {"id": "c2", "label": "Billing", "join": "all",
                             "conditions": [{"left": "{{ steps.read.data.amount }}", "op": "greater_than", "right": "100"}]}
    assert o["ports"] == ["case:c1", "case:c2", "otherwise"]
    assert o["words"] == {"case:c1": "if Urgent", "case:c2": "if Billing", "otherwise": "otherwise"}


def test_for_each_edits_its_inner_step_in_place_and_its_picker_offers_the_item(box):
    o = _case(box, """
        const mounts = [];
        const mountTaskFields = (h, args) => { mounts.push(args); const i = h.appendChild(new Node('textarea'));
          i.className = 'stub-prompt'; i.value = 'Summarise '; args.pickField(i, { field: 'prompt', slot: { mapping: 'value', why: '' } });
          return { destroy() {} }; };
        const root = host();
        const panels = createWorkflowPanels({ mountTaskFields, layer: () => root });
        const applied = [];
        const fields = async () => ({ ok: true, sources: [{ node_id: 'read', label: 'Read the mail', origin: 'last_run',
          fields: [{ ref: '{{ steps.read.data.emails }}', path: 'emails', type: 'list',
                     example: [{ subject: 'Hello', from: 'a@b.example' }] }] }] });
        const h = root.appendChild(new Node('div'));
        panels.node(h, { node: { id: 'each', kind: 'foreach', label: 'Each mail',
          config: { list: '{{ steps.read.data.emails }}', on_error: 'continue' } },
          palette: PAL, upstream: [{ id: 'read', label: 'Read the mail', kind: 'llm' }], fields, onApply: (s) => applied.push(s) });
        const form = h.querySelector('.wf-sf');
        changed(byField(h, 'step.kind'), 'llm');
        fire(h.querySelector('.wf-sf-inner-edit'), 'click');
        await settle(2);
        const inner = { hidden: form.parentNode.hidden, head: h.querySelector('.wf-step-inner-head').textContent,
          mode: mounts[0].mode, kind: mounts[0].task.task_type };
        const prompt = h.querySelector('.stub-prompt');
        fire(prompt.parentNode.querySelector('.wf-slot-pick'), 'click');
        await settle(5);
        const pick = root.querySelector('.wf-picker');
        const listed = pick.querySelectorAll('.wf-picker-source').map((s) => [s.querySelector('.wf-picker-step-name').textContent,
          s.querySelectorAll('.wf-picker-field').map((b) => b.dataset.ref)]);
        fire(pick.querySelectorAll('.wf-picker-field').find((b) => b.dataset.ref === '{{ item.subject }}'), 'click');
        await settle(5);
        mounts[0].onSaved({ label: 'Summarise', kind: 'llm', config: { prompt: prompt.value } });
        await settle(2);
        const back = { hidden: form.parentNode.hidden, line: h.querySelector('.wf-sf-inner').textContent, inner: !!h.querySelector('.wf-step-inner') };
        fire(h.querySelector('.wf-step-done'), 'click');
        out({ inner, listed, back, applied });
    """)
    assert o["inner"] == {"hidden": True, "head": "For each item: Prompt", "mode": "node", "kind": "llm"}
    assert o["listed"] == [["Each item", ["{{ item }}", "{{ item.subject }}", "{{ item.from }}"]],
                           ["Read the mail", ["{{ steps.read.data.emails }}"]]]
    assert o["back"] == {"hidden": False, "line": "Each item: Summarise.", "inner": False}
    assert o["applied"][0]["config"] == {"list": "{{ steps.read.data.emails }}", "on_error": "continue",
                                         "step": {"kind": "llm", "label": "Summarise",
                                                  "config": {"prompt": "Summarise {{ item.subject }}"}}}


def test_an_ai_step_chooses_its_tools_and_the_shape_of_its_answer(box):
    o = _case(box, """
        const read = (config, act) => { const h = host(); const v = SF.mountAiOptions(h, { node: { config }, palette: PAL });
          if (act) act(h); return v.read(); };
        out({
          auto: read({}),
          none: read({ tools: [] }),
          only: read({ tools: ['web_fetch'] }),
          empty: read({}, (h) => changed(h.querySelectorAll('select')[0], 'only')),
          twice: read({ answer_fields: [{ name: 'url', type: 'text' }, { name: 'url', type: 'list' }] }),
          bad: read({ answer_fields: [{ name: '1st', type: 'text' }] }),
          shape: read({ answer_fields: [{ name: 'title', type: 'text', description: 'Its title' }, { name: 'n', type: 'number' }] }),
        });
    """)
    assert o["auto"] == {"config": {}}, "no tools key: Pantheon picks tools by the prompt, as a Prompt task does"
    assert o["none"] == {"config": {"tools": []}}
    assert o["only"] == {"config": {"tools": ["web_fetch"]}}
    assert o["empty"] == {"refusal": "Choose at least one tool, or choose no tools.", "field": "tools"}
    assert o["twice"] == {"refusal": "“url” is asked for twice.", "field": "answer_fields[1].name"}
    assert o["bad"] == {"refusal": "A field’s name is letters, digits and _, such as title.", "field": "answer_fields[0].name"}
    assert o["shape"] == {"config": {"answer_fields": [{"name": "title", "type": "text", "description": "Its title"},
                                                       {"name": "n", "type": "number", "description": ""}]}}


def test_a_fields_name_finds_the_field_and_nothing_else(box):
    """Found by the Chromium drive: the slot box beside a field carried the
    field's own `data-field`, so `[data-field="path"]` answered two elements and a
    refusal's sentence could land beside the wrong one. The box names it as
    `data-slot-for`."""
    o = _case(box, """
        const { decorateField } = await import('./fieldPicker.js');
        const pickField = (input, { field, slot }) => decorateField(input, { slot, field, pick: async () => null });
        const m = mount({ kind: 'http', label: 'Fetch', config: { integration: 'int1', method: 'POST', path: '/v1',
          query: [{ name: 'status', value: 'unread' }], body: [{ name: 'text', value: 'x' }] } }, { pickField });
        const names = m.h.querySelectorAll('[data-field]').map((n) => n.dataset.field);
        out({ dup: names.filter((n, i) => names.indexOf(n) !== i),
              slots: m.h.querySelectorAll('.wf-slot').map((b) => [b.dataset.slotFor, b.dataset.mapping]) });
    """)
    assert o["dup"] == [], "one element per field name"
    # The server's palette (`integrate-d`): an entry's name says where the value
    # goes, and whether its value may come from another step depends on that
    # name (`classify_argument`), which a palette cannot answer once per kind —
    # so both are `never` here, fail-closed, and the box says why (filed: an
    # HTTP body value named `text` does not offer the picker).
    assert o["slots"] == [["path", "never"], ["query[0].name", "never"], ["query[0].value", "never"],
                          ["body[0].name", "never"], ["body[0].value", "never"]]
