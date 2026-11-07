# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1886` (`anyof-optional-args-never`) — the MCP step's form draws an
optional argument as the type it is optional of.

pydantic v2 and FastMCP write `count: int | None` as
`{"anyOf": [{"type": "integer"}, {"type": "null"}]}`, with no `type` of its
own. `argsForm.js` read only `type`, so it labelled the argument "text", drew
a text box, and `read()` sent `"3"` as a string; an optional choice
(`Literal["calm", "loud"] | None`) was a free text box instead of its list.
The server answered `never` for an optional text argument too
(`classify_argument`), so the palette's mapping for it was `never`.

Now `effectiveSchema` (the browser's twin of `workflow_slots.
effective_schema`, the same rule) unwraps an `anyOf`/`oneOf` of one schema and
`null`, and nothing else: the word, the box, the choices and what `read()`
sends are the type's. The palette entry here is the REAL server's
(`workflow_effects._mcp_tool_entry`), so the picker on `message` is what the
server would allow.

Driven: the real `argsForm.js` with the real `fieldPicker.js:decorateField`.
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
from helpers.workflow_cw_fake import build_sandbox  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

SCHEMA = {"type": "object", "required": ["channel"], "properties": {
    "channel": {"type": "string"},
    "message": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None,
                "description": "What it says."},
    "count": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None},
    "loud": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
    "mood": {"anyOf": [{"type": "string", "enum": ["calm", "loud"]}, {"type": "null"}]},
    "either": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
}}


def _tool():
    from src.workflow_effects import _mcp_tool_entry
    return _mcp_tool_entry({"qualified_name": "mcp__chat__send", "server_name": "chat",
                            "name": "send", "input_schema": SCHEMA,
                            "annotations": {"readOnlyHint": False}, "is_readonly": False,
                            "readonly_source": "annotation"})


_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "const AF = await import('./argsForm.js');\n"
    "const { mountArgsForm, typeWord } = AF;\n"
    "const effectiveSchema = AF.effectiveSchema || ((p) => p);\n"
    "const { decorateField } = await import('./fieldPicker.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const TOOL = %s;\n"
    "const pickField = (input, { field, slot }) => decorateField(input, { slot, field, pick: async () => '{{ steps.sum.text }}' });\n"
    "const rowOf = (h, name) => h.querySelectorAll('.wf-arg').find((r) => r.dataset.arg === name);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("optional-args"), _CANVAS_SHIM)


def test_an_optional_argument_is_drawn_and_read_as_its_type(box):
    o = _run(box, _PREAMBLE % json.dumps(_tool()), """
        const h = host();
        const f = mountArgsForm(h, { tool: TOOL, values: { channel: '#ops' }, pickField });
        const rows = h.querySelectorAll('.wf-arg').map((r) => {
          const input = r.querySelector('.wf-arg-input');
          const slot = r.querySelector('.wf-slot');
          return [r.dataset.arg, r.querySelector('.wf-arg-type').textContent, input.tagName,
            slot ? (slot.querySelector('.wf-slot-pick') ? 'pick' : 'typed') : null];
        });
        const moods = [...rowOf(h, 'mood').querySelectorAll('option')].map((x) => x.textContent);
        rowOf(h, 'count').querySelector('.wf-arg-input').value = '3';
        rowOf(h, 'message').querySelector('.wf-arg-input').value = '{{ steps.sum.text }}';
        rowOf(h, 'loud').querySelector('.wf-arg-input').value = 'true';
        rowOf(h, 'mood').querySelector('.wf-arg-input').value = JSON.stringify('calm');
        out({ rows, moods, read: f.read(), desc: rowOf(h, 'message').querySelector('.wf-arg-desc').textContent,
              plain: effectiveSchema({ type: 'string' }), two: typeWord({ anyOf: [{ type: 'string' }, { type: 'integer' }] }) });
    """)
    assert o["rows"] == [
        ["channel", " · text", "INPUT", "typed"],
        ["message", " · text", "INPUT", "pick"],
        ["count", " · a whole number", "INPUT", "typed"],
        ["loud", " · yes or no", "SELECT", None],
        ["mood", " · one of a list", "SELECT", None],
        ["either", " · text", "INPUT", "typed"],
    ], "an optional argument is its type; the server's mapping lets `message` take a field"
    assert o["moods"] == ["—", "calm", "loud"], "an optional choice keeps its list"
    assert o["read"] == {"args": {"channel": "#ops", "message": "{{ steps.sum.text }}", "count": 3,
                                  "loud": True, "mood": "calm"}}, "a whole number is sent as a number"
    assert o["desc"] == "What it says.", "the argument's own description stays on top"
    assert o["plain"] == {"type": "string"}, "a schema with a type is left as it is"
    assert o["two"] == "text", "a choice of two real types is not unwrapped"
