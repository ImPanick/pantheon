# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-14` (wf-canvas) — an MCP tool's arguments are a form built from its schema, and only content may come from another step.

Design § 2's P22-14: "The form is `argsForm.js`, built from `input_schema`
(top-level properties; objects and arrays as literal JSON, which is `never`).
Each argument shows the registry's mapping. `describeReadonly` from
`static/js/settings/mcpFields.js:517` is reused, not rewritten." The mapping is
the server's (`workflow_slots.classify_argument`, an allowlist that fails
closed): C-W's palette hands each tool's `args: { name: { mapping, why } }`.
`P22-14`'s `Verify:` — "The person types `#general` (the picker is not offered
there, with its reason), maps the Summarise step's text into `text`" — is this
form: `channel` says why it is typed, `text` offers *Insert a field…*.

Driven: the real `argsForm.js` with the real `fieldPicker.js:decorateField`
and the real `settings/mcpFields.js`, on C-W's palette entries.
"""

from __future__ import annotations

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
    "const { mountArgsForm, typeWord } = await import('./argsForm.js');\n"
    "const { decorateField } = await import('./fieldPicker.js');\n"
    "const { describeReadonly } = await import('../settings/mcpFields.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const PAL = %s;\n"
    "const SEND = PAL.mcp_tools[0];\n"
    "const pickField = (input, { field, slot }) => decorateField(input, { slot, field, pick: async () => '{{ steps.sum.text }}' });\n"
    "const rowOf = (h, name) => h.querySelectorAll('.wf-arg').find((r) => r.dataset.arg === name);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("argsform"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % palette_json(), script)


def test_each_argument_is_a_row_from_the_schema_with_what_it_may_take(box):
    o = _case(box, """
        const h = host();
        const tool = { ...SEND, input_schema: { ...SEND.input_schema, properties: { ...SEND.input_schema.properties,
          channel: { type: 'string', description: 'Where it goes <b>like #general</b>.' } } } };
        const f = mountArgsForm(h, { tool, values: { channel: '#general' }, pickField });
        const rows = h.querySelectorAll('.wf-arg').map((r) => {
          const input = r.querySelector('.wf-arg-input');
          const slot = r.querySelector('.wf-slot');
          return [r.dataset.arg, r.querySelector('.wf-arg-label').textContent, input.tagName, input.value,
            slot ? (slot.querySelector('.wf-slot-pick') ? 'pick' : slot.querySelector('.wf-slot-never').textContent) : null];
        });
        out({ rows, desc: rowOf(h, 'channel').querySelector('.wf-arg-desc').textContent, markup: markup(h),
              words: ['string', 'number', 'integer', 'boolean', 'object', 'array'].map((t) => typeWord({ type: t })) });
    """)
    # The server's reason (`integrate-d`: the palette is `build_palette`'s now) —
    # `classify_argument` says one sentence for every argument that is not a
    # word for text a person reads: a destination, a number, an object.
    from src.workflow_slots import WHY_NOT_TEXT
    assert o["rows"] == [
        ["channel", "channel needed · text", "INPUT", "#general", WHY_NOT_TEXT],
        ["text", "text needed · text", "INPUT", "", "pick"],
        ["silent", "silent optional · yes or no", "SELECT", "", None],
        ["priority", "priority optional · a whole number", "INPUT", "", WHY_NOT_TEXT],
        ["mood", "mood optional · one of a list", "SELECT", "", None],
        ["meta", "meta optional · JSON (an object)", "TEXTAREA", "", WHY_NOT_TEXT],
    ], "a destination is typed and says why; content may come from another step; a choice cannot hold a reference"
    assert o["desc"] == "Where it goes <b>like #general</b>." and o["markup"] == [], "the server's words are text"
    assert o["words"] == ["text", "a number", "a whole number", "yes or no", "JSON (an object)", "JSON (a list)"]


def test_whether_it_writes_is_said_as_settings_says_it(box):
    o = _case(box, """
        const said = (tool) => { const h = host(); mountArgsForm(h, { tool });
          return [h.querySelector('.wf-args-writes').textContent, h.querySelector('.wf-args-writes').dataset.writes,
            h.querySelector('.wf-args-writes-sentence').textContent, (h.querySelector('.wf-args-none') || {}).textContent || null]; };
        const destroys = { ...SEND, annotations: { destructiveHint: true } };
        out({ send: said(SEND), list: said(PAL.mcp_tools[1]), destroys: said(destroys),
              same: describeReadonly({ ...SEND, name: SEND.name }).sentence });
    """)
    assert o["send"][:2] == ["Writes (the server says so)", "yes"]
    assert o["send"][2] == o["same"], "describeReadonly's own sentence (P8-48), not a second wording"
    assert o["list"] == ["Read-only (the server says so)", "no", o["list"][2], "This tool takes no arguments."]
    assert o["destroys"][:2] == ["Destructive (the server says so)", "destroys"]


def test_what_it_reads_is_typed_as_the_schema_says(box):
    o = _case(box, """
        const read = (values, edit) => { const h = host(); const f = mountArgsForm(h, { tool: SEND, values });
          if (edit) edit(h); return f.read(); };
        const set = (h, name, v) => { rowOf(h, name).querySelector('.wf-arg-input').value = v; };
        out({
          full: read({ channel: '#general', text: '{{ steps.sum.text }}', silent: true, priority: 3, mood: 'loud', meta: { a: [1] } }),
          typedNumber: read({ channel: '#x', text: 'hi' }, (h) => set(h, 'priority', ' 4 ')),
          refNumber: read({ channel: '#x', text: 'hi' }, (h) => set(h, 'priority', '{{ steps.n.data.p }}')),
          notWhole: read({ channel: '#x', text: 'hi' }, (h) => set(h, 'priority', '2.5')),
          badJson: read({ channel: '#x', text: 'hi' }, (h) => set(h, 'meta', '{ nope')),
          needed: read({ text: 'hi' }),
          blanks: read({ channel: '#x', text: 'hi' }),
        });
    """)
    assert o["full"] == {"args": {"channel": "#general", "text": "{{ steps.sum.text }}", "silent": True, "priority": 3,
                                  "mood": "loud", "meta": {"a": [1]}}}
    assert o["typedNumber"] == {"args": {"channel": "#x", "text": "hi", "priority": 4}}
    assert o["refNumber"] == {"args": {"channel": "#x", "text": "hi", "priority": "{{ steps.n.data.p }}"}}, \
        "a reference stays its text; the server reads it as the type at run"
    assert o["notWhole"] == {"refusal": "priority must be a whole number.", "field": "args.priority"}
    assert o["badJson"] == {"refusal": "meta must be JSON (an object): it could not be read.", "field": "args.meta"}
    assert o["needed"] == {"refusal": "Fill in channel: the tool needs it.", "field": "args.channel"}
    assert o["blanks"] == {"args": {"channel": "#x", "text": "hi"}}, "an optional argument left blank is not sent"
