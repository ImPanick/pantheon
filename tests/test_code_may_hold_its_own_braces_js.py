# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1882` (`picker-clipped-and-never-false-alarm`, the browser's half) — a typed-only field warns exactly when the save would refuse it.

A field only a person types (`never`) says "Not here: …" the moment what is
typed in it would be refused at save. The browser decided that with a
pattern of its own — any `{{` at all — so `docker ps --format '{{.Names}}'`
was marked "Not here" in red and then saved without a word, and the
opposite: `\{{ steps.a.data.x }}` looked fine and was refused at save. It
now reads a field as the server does (`referencesInText`, the port of
`workflow_refs.references_in_text`, held equal by a differential case), and
on the one slot the palette marks `escape` (a Code step's source) a
reference after `\` is the code's own text, as the server reads it.

Driven: the real `fieldPicker.js` and `stepFields.js` in node over the DOM
shim (whose events do not bubble: each is fired on the element listening),
with the real palette.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM  # noqa: E402
from test_a_reference_can_change_what_it_reads_js import _generated  # noqa: E402
from helpers.workflow_cw_fake import build_sandbox, palette_json  # noqa: E402

from src import workflow_refs as wr  # noqa: E402
from src import workflow_slots as ws  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "const FP = await import('./fieldPicker.js');\n"
    "const SF = await import('./stepFields.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const PAL = %s;\n"
    "const typed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'input', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const field = (slot) => { const h = host(); const input = document.createElement('textarea');\n"
    "  h.appendChild(input); const d = FP.decorateField(input, { slot, field: 'x' });\n"
    "  return { input, d, said: () => [d.box.classList.contains('wf-slot-refused'), d.box.querySelector('.wf-slot-never').textContent] }; };\n"
)

DOCKER = "docker ps --format '{{.Names}}'"
F_STRING = 'print(f"\\{{item}} is {item}")'


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("braces"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % palette_json(), script)


# ── One reading on both sides ────────────────────────────────────────────────

_AROUND = ["", "x ", "\\", "\\\\", 'print(f"', "echo '", "{{", "{", "a\\b ", "}} "]


def _texts(seed=1882):
    """Texts with references, near-references and backslashes anywhere: the
    B1879 corpus, each put after and before other text, and pairs of them."""
    rng = random.Random(seed)
    base = _generated(n=400, seed=seed)
    out = [DOCKER, F_STRING, "\\{{ steps.a.data.x }}", "{{ {{ item }} }}", "\\{{ \\{{ item }} }}"]
    for t in base:
        out.append(rng.choice(_AROUND) + t + rng.choice(_AROUND))
    for _ in range(300):
        out.append(rng.choice(_AROUND).join(rng.sample(base, 2)))
    return out


def test_the_browser_finds_the_references_in_a_typed_only_field_as_the_server_does(box):
    """Differential (`Law 20`): `referencesInText` against
    `references_in_text`, with and without the escape, on the same texts."""
    texts = _texts()
    o = _case(box, """
        const texts = %s;
        out([false, true].map((escapes) => texts.map((t) => FP.referencesInText(t, { escapes }).map((r) => r.ref))));
    """ % json.dumps(texts))
    for escapes, got in zip((False, True), o):
        want = [[r.text for r in wr.references_in_text(t, escapes=escapes)] for t in texts]
        assert sum(1 for w in want if w) > 200 and sum(1 for w in want if not w) > 100, "both, often"
        bad = [(t, w, g) for t, w, g in zip(texts, want, got) if w != g]
        assert not bad, (escapes, bad[:5])
    # The escape changes the answer somewhere, or the case proves nothing.
    assert o[0] != o[1]


# ── What a typed-only field says as it is typed ──────────────────────────────

def test_a_go_template_is_not_called_a_reference(box):
    o = _case(box, """
        const f = field(%s);
        typed(f.input, %s);
        out(f.said());
    """ % (json.dumps({"mapping": "never", "why": ws.WHY_NOT_TEXT}), json.dumps(DOCKER)))
    assert o == [False, ws.WHY_NOT_TEXT]


def test_an_escaped_reference_is_still_one_where_there_is_no_escape(box):
    o = _case(box, """
        const f = field(%s);
        typed(f.input, '\\\\{{ steps.a.data.x }}');
        const escaped = f.said();
        typed(f.input, 'https://x/{{ steps.a.data.x }}');
        out([escaped, f.said()]);
    """ % json.dumps({"mapping": "never", "why": ws.WHY_NOT_TEXT}))
    assert o == [[True, "Not here: " + ws.WHY_NOT_TEXT], [True, "Not here: " + ws.WHY_NOT_TEXT]]


def test_a_code_steps_source_takes_the_escape_as_the_save_does(box):
    slot = {"mapping": "never", "why": ws.WHY_CODE, "escape": True}
    o = _case(box, """
        const f = field(%s);
        typed(f.input, %s);
        const escaped = f.said();
        typed(f.input, %s);
        out([escaped, f.said()]);
    """ % (json.dumps(slot), json.dumps(F_STRING), json.dumps(F_STRING.replace("\\{{", "{{"))))
    assert o == [[False, ws.WHY_CODE], [True, "Not here: " + ws.WHY_CODE]]


def test_the_code_form_says_how_to_write_braces_and_takes_them(box):
    """The real Code form over the real palette: the source says the
    sentence, and an escaped f-string is not marked."""
    o = _case(box, """
        const h = host();
        SF.mountStepFields(h, { node: { id: 'c', kind: 'code', label: 'Say', config: { language: 'python', source: 'print(1)' } },
          palette: PAL, pickField: (input, { field, slot }) => FP.decorateField(input, { slot, field }) });
        const src = h.querySelectorAll('textarea').find((t) => t.dataset.field === 'source');
        const slotBox = h.querySelectorAll('.wf-slot').find((b) => b.dataset.slotFor === 'source');
        const said = () => [slotBox.classList.contains('wf-slot-refused'), slotBox.querySelector('.wf-slot-never').textContent];
        typed(src, %s);
        const escaped = said();
        typed(src, 'print("{{ item }}")');
        out([escaped, said()]);
    """ % json.dumps(F_STRING))
    assert o == [[False, ws.WHY_CODE], [True, "Not here: " + ws.WHY_CODE]]
