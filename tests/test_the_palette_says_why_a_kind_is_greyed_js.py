# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-10`…`P22-18` (wf-canvas) — the palette offers every kind, grouped, and a kind the person may not use is greyed with its reason in words.

`D-2026-10-01-05` ("the node palette offers a person only what their agent can
already reach") and design § 0.6: HTTP and MCP steps are for admins (and
single-user installs), Code needs the workstation (`OFF_SENTENCE`,
`UNCONFIGURED_SENTENCE`, `NOT_PERMITTED_SENTENCE`). The server answers which
(`GET /api/workflows/palette`, C-W: `kinds: [{ kind, word, group, hint, ports,
available, why, slots }]`) and the browser derives nothing: a kind with
`available: false` is drawn, disabled, with the server's `why` as text beside
its words — never a colour or a lock alone — and cannot be picked. A Pantheon
with no palette offers Slice B's four (`Law 1`).

Driven: the real `workflowPanels.js:palette` and the real `workflowSource.js`
(`newItem` hands the palette over, and the new step's id is its label's slug),
over the C-W fake (`tests/helpers/workflow_cw_fake.py`).
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
    "import { server as cw, net as cwnet, seed, cwApi } from './cwfake.js';\n"
    "import { registerMenuDismiss, dismissTopMenu } from '../escMenuStack.js';\n"
    "const { createWorkflowPanels, PALETTE_KINDS } = await import('./workflowPanels.js');\n"
    "const { createWorkflowSource } = await import('./workflowSource.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "cw.palette = %s;\n"
    "const root = host();\n"
    "const anchor = root.appendChild(new Node('button'));\n"
    "const panels = createWorkflowPanels({ layer: () => root, holdEscape: (fn) => registerMenuDismiss(fn) });\n"
    "const pal = () => root.querySelector('.wf-palette');\n"
    "const kindBtn = (k) => pal().querySelectorAll('.wf-palette-kind').find((b) => b.dataset.kind === k);\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return build_sandbox(tmp_path_factory.mktemp("palette"), _CANVAS_SHIM)


def _case(box, script):
    return _run(box, _PREAMBLE % palette_json(), script)


def test_every_kind_is_offered_grouped_and_a_kind_you_may_not_use_says_why(box):
    o = _case(box, """
        const picked = panels.palette(anchor, { palette: cw.palette });
        const groups = pal().querySelectorAll('.wf-palette-group').map((g) => [
          (g.querySelector('.wf-palette-group-head') || { textContent: '' }).textContent,
          g.querySelectorAll('.wf-palette-kind').map((b) => b.dataset.kind)]);
        const read = (k) => { const b = kindBtn(k); return {
          disabled: !!b.disabled, aria: b.getAttribute('aria-disabled'), available: b.dataset.available || null,
          words: b.querySelectorAll('span').map((s) => [s.className, s.textContent]), label: b.getAttribute('aria-label') }; };
        const http = read('http');
        const code = read('code');
        const iff = read('if');
        fire(kindBtn('http'), 'click');
        await settle();
        const stillOpen = !!pal();
        const focused = kindBtn('llm').focused;
        fire(kindBtn('if'), 'click');
        out({ groups, http, code, iff, stillOpen, focused, picked: await picked, gone: !pal(), markup: markup(root) });
    """)
    assert o["groups"] == [
        ["Ask a model", ["llm", "research", "skill"]],
        ["Decide and reshape", ["if", "switch", "set", "merge", "wait", "foreach"]],
        ["Do something", ["action", "run_task"]],
        ["Reach out", ["http", "mcp", "code"]],
    ]
    assert o["http"]["disabled"] is True and o["http"]["aria"] == "true" and o["http"]["available"] == "false"
    assert o["http"]["words"] == [
        ["wf-palette-word", "HTTP request"], ["wf-palette-hint", "Call a service you set up."],
        ["wf-palette-why", "Only an admin can add this step: it calls a service outside Pantheon, which your agent cannot do either."]]
    assert o["http"]["label"].startswith("HTTP request: not available. Only an admin can add this step")
    assert o["code"]["words"][-1] == ["wf-palette-why", "Your workstation is switched off. Switch it on in Settings → Workstation to run code."]
    assert o["iff"] == {"disabled": False, "aria": None, "available": None,
                        "words": [["wf-palette-word", "If"], ["wf-palette-hint", "Go one of two ways."]],
                        "label": "If: Go one of two ways."}
    assert o["stillOpen"] is True, "a greyed kind cannot be picked"
    assert o["focused"] is True, "the first kind that can be picked has the focus"
    assert o["picked"] == "if" and o["gone"] is True
    assert o["markup"] == []


def test_escape_adds_nothing(box):
    o = _case(box, """
        const picked = panels.palette(anchor, { palette: cw.palette });
        dismissTopMenu();
        out({ picked: await picked, gone: !pal(), back: !!anchor.focused });
    """)
    assert o == {"picked": None, "gone": True, "back": True}


def test_a_pantheon_with_no_palette_offers_slice_bs_four(box):
    o = _case(box, """
        const picked = panels.palette(anchor);
        const kinds = pal().querySelectorAll('.wf-palette-kind').map((b) => [b.dataset.kind, !!b.disabled,
          b.querySelector('.wf-palette-word').textContent]);
        const heads = pal().querySelectorAll('.wf-palette-group-head').length;
        fire(kindBtn('run_task'), 'click');
        out({ kinds, heads, picked: await picked, four: PALETTE_KINDS.map((k) => k.kind) });
    """)
    assert o["kinds"] == [["llm", False, "Prompt"], ["research", False, "Research"], ["action", False, "Action"],
                          ["run_task", False, "Run task"]]
    assert o["heads"] == 0 and o["picked"] == "run_task" and o["four"] == ["llm", "research", "action", "run_task"]


def test_new_step_hands_the_palette_over_and_names_the_step_after_its_kind(box):
    o = _case(box, """
        seed({ id: 'wf1', name: 'Triage', task_id: 't1', trigger_status: 'paused', version: 1,
          trigger_task: { id: 't1', status: 'paused' }, graph: { v: 1, start: { position: null }, nodes: [], edges: [] } });
        let handed = null;
        const src = createWorkflowSource({ api: cwApi(cwnet), workflowId: 'wf1',
          panels: { palette: async (a, args) => { handed = args; return 'set'; } } });
        await src.ready;
        const a = await src.newItem(anchor);
        const b = await src.newItem(anchor);
        const items = (await src.load()).items.filter((i) => i.kind === 'set').map((i) => [i.id, i.name, i.ports, i.portWords]);
        cw.refusePalette = { status: 500, detail: 'The palette could not be built.' };
        const s2 = createWorkflowSource({ api: cwApi(cwnet), workflowId: 'wf1' });
        await s2.ready;
        const st = s2.state();
        out({ kinds: handed.palette.kinds.length, a, b, items, err: st.paletteError, pal: st.palette });
    """)
    assert o["kinds"] == 14, "the palette the server answered is the one the panel is handed"
    assert (o["a"], o["b"]) == ("set-fields", "set-fields-2"), "a step's id is its label's slug"
    assert o["items"] == [["set-fields", "Set fields", ["success"], {"success": "then"}],
                          ["set-fields-2", "Set fields 2", ["success"], {"success": "then"}]]
    assert o["err"] == "The palette could not be built." and o["pal"] is None, \
        "a palette the server refused leaves the document open and says why"
