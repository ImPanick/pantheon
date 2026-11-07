# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1881` (`set-missing-silent-and-type-words`) — the Set form asks what to do when a field is not there.

A Set step whose field reads nothing now stops the run (`workflow_logic.
set_stops_on_missing`), as every other step does; its `on_missing` "empty"
keeps what a Set step did before. The form (`stepFields.js`, `buildSet`)
draws "If a field is not there": "stop the run and say which" or "leave it
empty and go on" — the server's words, held equal here — and writes
`on_missing` only when it says "leave it empty" or the step already said,
so every Set step saved before this row comes back exactly as it was.
Driven: the real `stepFields.js` in node over the DOM shim.
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

from src import workflow_logic as wl  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "const SF = await import('./stepFields.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const PAL = %s;\n"
    "const mount = (node) => {\n"
    "  const h = host();\n"
    "  const got = [];\n"
    "  SF.mountStepFields(h, { node, palette: PAL, onApply: (s) => got.push(s), onCancel: () => got.push('cancel') });\n"
    "  return { h, got, done: () => fire(h.querySelector('.wf-step-done'), 'click') };\n"
    "};\n"
    "const changed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'change', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const byField = (h, f) => h.querySelectorAll('[data-field]').find((n) => n.dataset.field === f);\n"
)

FIELDS = [{"name": "title", "value": "{{ steps.read.data.title }}"}]


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("setmissing"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % palette_json(), script)


def test_the_forms_words_are_the_servers(box):
    o = _case(box, "out(SF.SET_ON_MISSING);")
    assert [k for k, _ in o] == list(wl.SET_ON_MISSING)
    assert {k: w for k, w in o} == wl.SET_ON_MISSING_WORDS


def test_the_set_form_asks_and_writes_only_what_was_said(box):
    o = _case(box, """
        const fields = %s;
        const r = {};
        let m = mount({ id: 's', kind: 'set', label: 'Shape', config: { fields } });
        const sel = byField(m.h, 'on_missing');
        r.shown = { value: sel.value, words: sel.querySelectorAll('option').map((x) => x.textContent),
          label: m.h.querySelectorAll('.wf-sf-label').map((l) => l.textContent).includes('If a field is not there') };
        m.done();
        r.untouched = m.got[0].config;
        m = mount({ id: 's', kind: 'set', label: 'Shape', config: { fields } });
        changed(byField(m.h, 'on_missing'), 'empty');
        m.done();
        r.empty = m.got[0].config;
        m = mount({ id: 's', kind: 'set', label: 'Shape', config: { fields, on_missing: 'empty' } });
        r.reopened = byField(m.h, 'on_missing').value;
        changed(byField(m.h, 'on_missing'), 'stop');
        m.done();
        r.backToStop = m.got[0].config;
        m = mount({ id: 's', kind: 'set', label: 'Shape', config: { fields, on_missing: 'stop' } });
        m.done();
        r.keptStop = m.got[0].config;
        out(r);
    """ % json.dumps(FIELDS))
    assert o["shown"] == {"value": "stop", "label": True,
                          "words": ["stop the run and say which", "leave it empty and go on"]}
    assert o["untouched"] == {"fields": FIELDS}, "a step saved before this row comes back as it was"
    assert o["empty"] == {"fields": FIELDS, "on_missing": "empty"}
    assert o["reopened"] == "empty"
    assert o["backToStop"] == {"fields": FIELDS, "on_missing": "stop"}
    assert o["keptStop"] == {"fields": FIELDS, "on_missing": "stop"}
