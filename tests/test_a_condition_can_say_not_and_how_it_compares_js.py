# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1880` (`condition-operators-and-coercion`) — the If and Switch forms offer the new words, choices one on each line, and what a condition compares as.

The server's closed list grew by eleven (`workflow_logic.OPERATORS`: "is
not", "does not contain", "is not empty", "is not one of", "starts with",
"ends with", "matches the pattern", "is at least", "is at most", "is
before", "is after"), and a condition may say what it compares its sides as
(`as`). The form (`stepFields.js`, `_conditions`, shared by If and each
Switch case) draws them: the operator select from the palette (its fallback
held equal to the server's), "Compared as" with "as it looks" writing no
`as` (so every document saved before this row comes back unchanged), the
choices of "is one of" in a box one on each line kept as a list (so
"Smith, John" is one choice), and the pattern's and the dates' words under
their value. Driven: the real `stepFields.js` in node over the DOM shim
(events do not bubble: each is fired on the element listening).
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
from helpers.workflow_cw_fake import PALETTE, build_sandbox, palette_json  # noqa: E402

from src import workflow_logic as wl  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "const SF = await import('./stepFields.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const PAL = %s;\n"
    "const mount = (node, more = {}) => {\n"
    "  const h = host();\n"
    "  const got = [];\n"
    "  SF.mountStepFields(h, { node, palette: PAL, onApply: (s) => got.push(s), onCancel: () => got.push('cancel'), ...more });\n"
    "  return { h, got, done: () => fire(h.querySelector('.wf-step-done'), 'click') };\n"
    "};\n"
    "const problemOf = (h) => { const p = h.querySelector('.wf-sf-problem');\n"
    "  return p ? [p.textContent, p.dataset.field || null] : null; };\n"
    "const typed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'input', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const changed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'change', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const byField = (h, f) => h.querySelectorAll('[data-field]').find((n) => n.dataset.field === f);\n"
    "// Whether `el` is shown: none of the boxes it sits in is hidden.\n"
    "const shown = (el) => { for (let n = el; n; n = n.parentNode) if (n.hidden) return false; return true; };\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("conditions"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % palette_json(), script)


F = "{{ steps.read.data.status }}"


def test_the_forms_words_are_the_servers(box):
    o = _case(box, "out({ ops: SF.DEFAULT_OPERATORS, unary: SF.UNARY_OPERATORS, list: SF.LIST_OPERATORS,"
                   " dates: SF.DATE_OPERATORS, as: SF.COMPARE_AS });")
    assert o["ops"] == [{"op": op, "word": wl.OPERATOR_WORDS[op]} for op in wl.OPERATORS]
    assert o["ops"] == PALETTE["operators"], "the fallback is the palette's own list"
    assert o["unary"] == list(wl.UNARY_OPERATORS)
    assert o["list"] == list(wl.LIST_OPERATORS)
    assert o["dates"] == list(wl.DATE_OPERATORS)
    assert o["as"][0] == ["", "as it looks"]
    assert [k for k, _ in o["as"][1:]] == list(wl.COMPARE_AS)
    assert {k: w for k, w in o["as"][1:]} == wl.COMPARE_AS_WORDS


_CONFIG = {"join": "all", "conditions": [
    {"left": F, "op": "not_equals", "right": "closed", "as": "text"},
    {"left": F, "op": "is_not_empty"},
    {"left": F, "op": "not_one_of", "right": ["Smith, John", "Doe"]},
    {"left": F, "op": "one_of", "right": "dev, ops ,qa"},
    {"left": F, "op": "matches", "right": "^(re|fwd):"},
    {"left": F, "op": "is_before", "right": "2 days ago"},
    {"left": F, "op": "at_least", "right": "3", "as": "length"},
    {"left": F, "op": "equals", "right": "007", "as": "exact"},
]}


def test_every_new_word_comes_back_out_of_the_if_form_unchanged(box):
    o = _case(box, """
        const m = mount({ id: 'i', kind: 'if', label: 'Check', config: %s });
        const opsOffered = byField(m.h, 'conditions[0].op').querySelectorAll('option').map((x) => x.value);
        m.done();
        out({ config: m.got[0] && m.got[0].config, problem: problemOf(m.h), opsOffered });
    """ % json.dumps(_CONFIG))
    assert o["problem"] is None
    assert o["config"] == _CONFIG
    assert o["opsOffered"] == list(wl.OPERATORS)


def test_a_switch_case_takes_the_new_words_too(box):
    cases = [{"id": "c1", "label": "Old", "join": "any", "conditions": [
        {"left": F, "op": "is_after", "right": "yesterday"},
        {"left": F, "op": "starts_with", "right": "Re:", "as": "exact"}]}]
    o = _case(box, """
        const m = mount({ id: 's', kind: 'switch', label: 'Sort', config: { cases: %s } });
        m.done();
        out(m.got[0].config);
    """ % json.dumps(cases))
    assert o == {"cases": cases}


def test_what_each_word_shows_and_hides(box):
    o = _case(box, """
        const m = mount({ id: 'i', kind: 'if', label: 'Check', config: { conditions: [{ left: '%s', op: 'equals', right: 'x' }] } });
        const op = byField(m.h, 'conditions[0].op');
        const at = (o) => {
          changed(op, o);
          const hints = m.h.querySelectorAll('.wf-sf-hint').filter(shown).map((p) => p.textContent);
          return { value: shown(byField(m.h, 'conditions[0].right')),
                   choices: shown(byField(m.h, 'conditions[0].choices')),
                   as: shown(byField(m.h, 'conditions[0].as')),
                   pattern: hints.some((t) => t.startsWith('A pattern:')),
                   dates: hints.some((t) => t.startsWith('A date or a time')),
                   oneEach: hints.includes('One choice on each line.') };
        };
        out({ equals: at('equals'), notEmpty: at('is_not_empty'), oneOf: at('not_one_of'),
              matches: at('matches'), before: at('is_before'), atLeast: at('at_least') });
    """ % F)
    assert o["equals"] == {"value": True, "choices": False, "as": True, "pattern": False, "dates": False, "oneEach": False}
    assert o["notEmpty"] == {"value": False, "choices": False, "as": False, "pattern": False, "dates": False, "oneEach": False}
    assert o["oneOf"] == {"value": False, "choices": True, "as": True, "pattern": False, "dates": False, "oneEach": True}
    assert o["matches"] == {"value": True, "choices": False, "as": True, "pattern": True, "dates": False, "oneEach": False}
    assert o["before"] == {"value": True, "choices": False, "as": False, "pattern": False, "dates": True, "oneEach": False}
    assert o["atLeast"] == {"value": True, "choices": False, "as": True, "pattern": False, "dates": False, "oneEach": False}


def test_choices_are_one_on_each_line_and_kept_as_a_list(box):
    o = _case(box, """
        const r = {};
        let m = mount({ id: 'i', kind: 'if', label: 'Check', config: { conditions: [{ left: '%s', op: 'equals', right: 'Smith, John' }] } });
        changed(byField(m.h, 'conditions[0].op'), 'one_of');
        r.carried = byField(m.h, 'conditions[0].choices').value;
        typed(byField(m.h, 'conditions[0].choices'), 'Smith, John\\n  Doe, Jane \\n\\n');
        changed(byField(m.h, 'conditions[0].as'), 'text');
        m.done();
        r.list = m.got[0].config.conditions[0];
        m = mount({ id: 'i', kind: 'if', label: 'Check', config: { conditions: [{ left: '%s', op: 'one_of', right: 'a' }] } });
        typed(byField(m.h, 'conditions[0].choices'), '{{ steps.read.data.allowed }}');
        m.done();
        r.picked = m.got[0].config.conditions[0].right;
        m = mount({ id: 'i', kind: 'if', label: 'Check', config: { conditions: [{ left: '%s', op: 'one_of', right: 'a' }] } });
        typed(byField(m.h, 'conditions[0].choices'), '  \\n ');
        m.done();
        r.none = [problemOf(m.h), m.got.length];
        m = mount({ id: 'i', kind: 'if', label: 'Check', config: { conditions: [{ left: '%s', op: 'not_equals', right: '' }] } });
        m.done();
        r.blankNot = m.got[0] && m.got[0].config.conditions[0];
        out(r);
    """ % (F, F, F, F))
    assert o["carried"] == "Smith, John", "what was typed moves to the choices"
    assert o["list"] == {"left": F, "op": "one_of", "right": ["Smith, John", "Doe, Jane"], "as": "text"}
    assert o["picked"] == "{{ steps.read.data.allowed }}", "a picked list stays the field"
    assert o["none"] == [["Give the choices, one on each line.", "conditions[0].choices"], 0]
    assert o["blankNot"] == {"left": F, "op": "not_equals", "right": ""}, "“is not” nothing, as “is” nothing"


def test_as_it_looks_writes_no_as_and_dates_write_none(box):
    o = _case(box, """
        const m = mount({ id: 'i', kind: 'if', label: 'Check', config: { conditions: [
          { left: '%s', op: 'equals', right: '7', as: 'number' }, { left: '%s', op: 'equals', right: '7' }] } });
        changed(byField(m.h, 'conditions[0].as'), '');
        changed(byField(m.h, 'conditions[1].as'), 'exact');
        changed(byField(m.h, 'conditions[1].op'), 'is_after');
        typed(byField(m.h, 'conditions[1].right'), 'in 2 hours');
        m.done();
        out(m.got[0].config.conditions);
    """ % (F, F))
    assert o == [{"left": F, "op": "equals", "right": "7"},
                 {"left": F, "op": "is_after", "right": "in 2 hours"}]
