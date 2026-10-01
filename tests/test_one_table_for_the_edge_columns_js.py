# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1045` — the edge-to-column pairing and the step-kind words are one table in the browser.

`P22-02` put `EDGE_COLUMNS` (`success → then_task_id`, `error → else_task_id`)
and `KIND_WORDS` (Prompt, Research, Action) in `static/js/tasks/workflowDiagram.js`
for the canvas, while the task form's `CHAIN_FIELDS` (`tasks/taskFields.js`
since `P22-03`) spelled the same column pairing for its two selects and
`tasks.js:_workflowDetail` wrote the same three words on a diagram node. Two
spellings of one fact; one goes stale (`Law 7`).

The row's `Verify:` is a mutation, and this file performs it: each sandbox here
carries `workflowDiagram.js` either as shipped or with **only its tables
changed** — the two columns swapped, the research word reworded — and the real
modules are driven against it. If the form's save, the canvas's write and the
diagram's words all follow the change, the table is the one place that decides.

Driven: the real `mountTaskFields` (the form test's sandbox,
`tests/test_one_task_form_in_two_places_js.py`), the real `canvas.js` (the
canvas test's sandbox and fake server) and the real `tasks.js:_workflowDetail`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_palette_moves_to_the_server_js import _STUBS  # noqa: E402
from test_one_task_form_in_two_places_js import _SHIM_PARSED, _ROUTES_JS  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM, _UP, _TASKS as _CANVAS_TASKS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
TASKS_JS = JS / "tasks.js"
CANVAS_JS = JS / "workbench" / "canvas.js"
DIAGRAM_JS = JS / "tasks" / "workflowDiagram.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_COLUMNS = "  success: 'then_task_id',\n  error: 'else_task_id',\n"
_SWAPPED = "  success: 'else_task_id',\n  error: 'then_task_id',\n"


def _diagram(variant: str) -> str:
    """`workflowDiagram.js` as shipped, or with only its two tables changed."""
    src = DIAGRAM_JS.read_text(encoding="utf-8")
    assert src.count(_COLUMNS) == 1 and src.count("  research: 'Research',\n") == 1, \
        "workflowDiagram.js's tables moved — re-read this test"
    if variant == "changed":
        src = src.replace(_COLUMNS, _SWAPPED).replace("  research: 'Research',\n", "  research: 'Deep research',\n")
    return src


@pytest.fixture(scope="module", params=["shipped", "changed"])
def forms(request, tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("onetable-form"), TASKS_JS, _SHIM_PARSED, _STUBS)
    copy = box / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + "\nexport const __w = { _workflowDetail };\n",
                    encoding="utf-8")
    (box / "tasks" / "workflowDiagram.js").write_text(_diagram(request.param), encoding="utf-8")
    return request.param, box


@pytest.fixture(scope="module", params=["shipped", "changed"])
def canvases(request, tmp_path_factory):
    root = tmp_path_factory.mktemp("onetable-canvas")
    (root / "workbench").mkdir()
    box = _make_sandbox(root / "workbench", CANVAS_JS, _CANVAS_SHIM, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "tasks" / "workflowDiagram.js").write_text(_diagram(request.param), encoding="utf-8")
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    return request.param, box


_ROW = {"id": "t1", "name": "Nightly backup", "task_type": "llm", "prompt": "Back it up",
        "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "02:00", "status": "active",
        "output_target": "session", "then_task_id": None, "else_task_id": None, "run_count": 0}
_OTHERS = [{"id": "t2", "name": "Post the summary"}, {"id": "t3", "name": "Tell me it broke"}]


def test_the_forms_two_selects_save_to_the_columns_the_table_names(forms):
    variant, box = forms
    o = _run(box, (
        "import { document, Node, calls, mockFetch, res, tick, click } from './shim.js';\n"
        "const { mountTaskFields } = await import('./tasks/taskFields.js');\n"
        "const { EDGE_COLUMNS } = await import('./tasks/workflowDiagram.js');\n"
    ), (_ROUTES_JS % json.dumps({"saved": _ROW})) + """
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: %s });
        await tick();
        q(host, 'task-form-chain').value = 't2';        // "If it works"
        q(host, 'task-form-chain-else').value = 't3';   // "If it fails"
        click(q(host, 'task-form-save'));
        await tick();
        const body = writes()[0].body;
        console.log(JSON.stringify({ table: EDGE_COLUMNS, then: body.then_task_id, otherwise: body.else_task_id }));
    """ % (json.dumps(_ROW), json.dumps([_ROW] + _OTHERS)))
    works, fails = o["table"]["success"], o["table"]["error"]
    sent = {"then_task_id": o["then"], "else_task_id": o["otherwise"]}
    assert sent[works] == "t2" and sent[fails] == "t3", (variant, o)
    if variant == "changed":
        assert (o["then"], o["otherwise"]) == ("t3", "t2"), "the save followed the table, not a second copy"


def test_the_form_is_filled_from_the_columns_the_table_names(forms):
    variant, box = forms
    row = dict(_ROW, then_task_id="t2", else_task_id="t3")
    o = _run(box, (
        "import { document, Node, calls, mockFetch, res, tick } from './shim.js';\n"
        "const { mountTaskFields } = await import('./tasks/taskFields.js');\n"
    ), (_ROUTES_JS % json.dumps({})) + """
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: %s });
        await tick();
        console.log(JSON.stringify({ works: q(host, 'task-form-chain').value, fails: q(host, 'task-form-chain-else').value }));
    """ % (json.dumps(row), json.dumps([row] + _OTHERS)))
    expected = {"works": "t2", "fails": "t3"} if variant == "shipped" else {"works": "t3", "fails": "t2"}
    assert o == expected, variant


def test_the_canvas_writes_the_same_column_the_form_saves(canvases):
    variant, box = canvases
    o = _run(box, (
        "import { server, net, mountPanel, fire, settle, host, nodeOf, portOf, at, writes } from './shim.js';\n"
        "const { mountCanvas } = await import('./canvas.js');\n"
        "server.tasks = %s;\nserver.prefs = null;\n" % json.dumps(_CANVAS_TASKS)
    ), """
        const root = host();
        const c = mountCanvas(root, { fetch: net, mountPanel });
        await c.ready; await settle();
        const port = portOf(nodeOf(root, 'b'), 'success'), target = at(nodeOf(root, 'c'));
        fire(port, 'pointerdown', {});
        fire(port, 'pointerup', { clientX: target.x + 5, clientY: target.y + 5 });
        await settle(5);
        console.log(JSON.stringify({ body: writes()[0].body }));
    """)
    column = "then_task_id" if variant == "shipped" else "else_task_id"
    assert o["body"] == {column: "c"}, variant


def test_a_diagram_node_names_its_kind_from_the_table(forms):
    variant, box = forms
    o = _run(box, (
        "import { document, Node, calls, mockFetch, res, tick } from './shim.js';\n"
        "const { __w } = await import('./tasks.js');\n"
    ), """
        console.log(JSON.stringify({
          research: __w._workflowDetail({ task_type: 'research' }),
          prompt: __w._workflowDetail({ task_type: 'llm' }),
          unknown: __w._workflowDetail({ task_type: 'something-new' }),
          action: __w._workflowDetail({ task_type: 'action', action: 'tidy_sessions' }),
        }));
    """)
    assert o["research"] == ("Research" if variant == "shipped" else "Deep research")
    assert o["prompt"] == "Prompt" and o["unknown"] == "Prompt"
    assert o["action"] == "Action · tidy_sessions"
