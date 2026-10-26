# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1177` — what a Workbench step form does with a saved choice it no longer
offers, asserted: one case per behaviour, each red with its line mutated.

**Measured before this file** (`w10-docs`, closing `B1153`): over the
Workbench's step-form test files, each of these mutants survived —

  1. `stepFields.js` `_selectField`: the line that puts a select on its first
     choice when the saved value is not offered, removed;
  2. `stepFields.js` `_offer`: `sel.value = has(was) ? String(was) : …` →
     `was || …` (the previous choice kept whether or not it is still offered);
  3. `workflowPanels.js` `syncSources`: `values.includes(keep) ? keep : …` →
     `keep || …` (the test-source picker keeps a source no longer listed).

Under the old shim a select kept any value, so none could be asserted; since
`B1153` the shim's opt-in parser gives `select.value` a browser's rule (a value
no option has reads `''`), and each case below is what a person would see.

Driven (`Law 20`): the real `stepFields.js` and `workflowPanels.js` in node,
the first two over the server's real palette (`workflow_cw_fake.palette_json`)
with the browser's select rule installed, the third in the real Automations
room over the faked workflow layer of `test_the_automations_room_js.py`.
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
import test_the_automations_room_js as room_js  # noqa: E402
from test_the_automations_room_js import box as room_box  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# A select a browser would not let hold a value no option has (`B1153`).
_PARSED_SHIM = _CANVAS_SHIM + "\nimport { installHtmlParsing } from './dom.js';\ninstallHtmlParsing();\n"

_PREAMBLE = (
    "import { document, Node, fire, settle, host } from './shim.js';\n"
    "const SF = await import('./stepFields.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const PAL = %s;\n"
    "const mount = (node, palette = PAL) => {\n"
    "  const h = host();\n"
    "  const got = [];\n"
    "  const view = SF.mountStepFields(h, { node, palette, onApply: (s) => got.push(s), onCancel: () => {} });\n"
    "  return { h, got, view, done: () => fire(h.querySelector('.wf-step-done'), 'click') };\n"
    "};\n"
    "const byField = (h, f) => h.querySelectorAll('[data-field]').find((n) => n.dataset.field === f);\n"
    "const changed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'change', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("notoffered"), _PARSED_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % palette_json(), script)


def test_the_shim_keeps_no_value_an_option_does_not_have(box):
    """The premise every case below stands on."""
    o = _case(box, """
        const sel = document.createElement('select');
        const a = document.createElement('option'); a.value = 'a'; sel.appendChild(a);
        sel.value = 'gone';
        out({ value: sel.value });
    """)
    assert o["value"] == ""


def test_a_step_reopened_after_its_kind_went_away_is_on_the_first_kind_not_blank(box):
    """(1) `_selectField`'s first-choice line. A For-each step saved to run an
    HTTP request, reopened where HTTP is not offered (no integration): the
    select is on the first kind there is, not blank, and Done hands back a kind
    the step can be — the inner step, of a kind no longer chosen, is not kept."""
    o = _case(box, """
        const pal = JSON.parse(JSON.stringify(PAL));
        pal.kinds.find((k) => k.kind === 'http').available = false;
        const m = mount({ id: 'each', kind: 'foreach', label: 'Each', config: { list: '{{ steps.read.data.items }}',
          step: { kind: 'http', label: 'Post it', config: { integration: 'int1', method: 'GET', path: '/x' } } } }, pal);
        const sel = byField(m.h, 'step.kind');
        out({ value: sel.value, first: sel.querySelectorAll('option')[0].value,
              offered: sel.querySelectorAll('option').map((x) => x.value),
              inner: m.h.querySelector('.wf-sf-inner').textContent });
    """)
    assert "http" not in o["offered"]
    assert o["value"] == o["first"] != "", "a blank choice, on a step reopened after its kind went away"
    assert o["inner"] == "Not set up yet."


def test_a_choice_whose_tool_went_away_falls_back_to_the_saved_tool_not_blank(box):
    """(2) `_offer`. An MCP step saved on one tool; the person picks another;
    that other's server goes away and the palette is read again (`B1136`): the
    step is on its saved tool again — not on the gone one (`''` in a browser)."""
    o = _case(box, """
        const saved = PAL.mcp_tools[0];
        const other = { ...saved, qualified_name: 'mcp__other__ping', server_name: 'other', name: 'ping',
                        description: 'Ping.' };
        const both = { ...PAL, mcp_tools: [saved, other] };
        const m = mount({ id: 'post', kind: 'mcp', label: 'Post', config: { tool: saved.qualified_name,
          args: { channel: '#dev', text: 'hi' } } }, both);
        const sel = byField(m.h, 'tool');
        changed(sel, other.qualified_name);
        const picked = sel.value;
        m.view.paletteChanged({ ...PAL, mcp_tools: [saved] });       // the other server went away
        out({ picked, after: sel.value, saved: saved.qualified_name });
    """)
    assert o["picked"] == "mcp__other__ping"
    assert o["after"] == o["saved"], "the gone tool was kept (a blank choice in a browser)"


def test_the_test_source_picker_does_not_keep_a_source_no_longer_listed(room_box):
    """(3) `syncSources`. *The pinned sample* chosen, then unpinned: the picker
    is on the last input, not on a source it no longer lists."""
    o = room_js._case(room_box, """
        const { root } = await room();
        await openW(root);
        fire(itemOf(root, 'n1'), 'click'); await settle(5);
        const sel = by(root, 'wf-test-source');
        sel.value = 'example'; sel.dispatchEvent({ type: 'change', target: sel });
        fire(by(root, 'wf-test-go'), 'click'); await settle(10);
        fire(by(root, 'wf-test-pin'), 'click'); await settle(10);
        sel.value = 'pinned'; sel.dispatchEvent({ type: 'change', target: sel });
        const chosen = sel.value;
        fire(by(root, 'wf-test-unpin'), 'click'); await settle(10);
        out({ chosen, after: sel.value, listed: sel.querySelectorAll('option').map((x) => x.value) });
    """)
    assert o["chosen"] == "pinned"
    assert "pinned" not in o["listed"]
    assert o["after"] == "last", "the picker kept a source it no longer lists"
