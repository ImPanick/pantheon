# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P23-06` — the Workbench is readable at any width and draws each thing once.

Driven under node with the canvas's and the Automations room's own harnesses
(`tests/test_the_workbench_canvas_js.py`, `tests/test_the_automations_room_js.py`
— imported, not copied): the real `canvas.js`, `graphLayout.js`,
`workflowRoom.js`, `taskSource.js` and `tasks/taskFields.js`.

  * **WB-M-6 / WB-M-2.** A fit into a canvas under 600 px wide (a phone, or a
    desktop canvas a run list and a step's panel squeezed) stops at 60 %, not
    the 35 % floor where a step was an 80 px smudge; with a step's panel open
    the chain is fitted around that step and its neighbours.
  * **WB-M-3.** A fit reads the viewport's layout size: the window's entrance
    scales it (0.95 → 1), and a fit made mid-entrance opened one graph at 87 %
    one time and 91 % the next.
  * **WB-M-5.** When the viewport changes size and the view is still the fit
    (nobody panned or zoomed), it is fitted again — a Versions… box no longer
    pushes the steps off the bottom; after a pan, a resize leaves the view be.
  * **WB-M-4.** "No runs yet" sits in the empty run list, not above the
    workflow's toolbar, and a tab switch takes the room's line away.
  * **WB-M-8.** *Make it* with no name asks for one and makes nothing.
  * **WB-M-10.** A workflow's start has no ports on the chains canvas.
  * **WB-M-14.** The task form takes `chain: false`: no Chain selects, and a
    save leaves the canvas's arrows alone.
  * **WB-U-4.** A run's time reads "Sep 30, 8:00 AM" — no seconds.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_the_automations_room_js as room_t  # noqa: E402
import test_the_workbench_canvas_js as canvas_t  # noqa: E402
import test_one_task_form_in_two_places_js as form_t  # noqa: E402
from helpers.workflow_fakes import WORKFLOW_API_JS, WORKFLOW_SOURCE_JS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
LAYOUT = JS / "workbench" / "graphLayout.js"

pytestmark = pytest.mark.skipif(
    subprocess.run(["node", "--version"], capture_output=True).returncode != 0, reason="node not on PATH")


# ── WB-M-6 / WB-M-2: a readable floor in a narrow canvas ────────────────────

def test_a_fit_in_a_narrow_canvas_stops_at_sixty_percent(tmp_path):
    entry = tmp_path / "case.mjs"
    entry.write_text(
        f"import * as gl from '{LAYOUT.as_posix()}';\n"
        "const wide = { x: 40, y: 40, w: 232 * 7 + 96 * 6, h: 96 };\n"
        "console.log(JSON.stringify({ phone: gl.fitView(wide, 390, 640), squeezed: gl.fitView(wide, 560, 600),\n"
        "  desk: gl.fitView(wide, 1100, 700), floor: gl.FIT_FLOOR_NARROW, under: gl.NARROW_FIT_WIDTH }));\n",
        encoding="utf-8")
    o = json.loads(subprocess.run(["node", str(entry)], capture_output=True, text=True, check=True).stdout)
    assert o["phone"]["zoom"] == 0.6 and o["squeezed"]["zoom"] == 0.6, o   # was 0.35, the floor
    assert o["phone"]["x"] + 40 * 0.6 == 40, "the start at the padding (`B1113`)"
    assert o["desk"]["zoom"] < 0.6, "a wide canvas still fits the whole graph"
    assert (o["floor"], o["under"]) == (0.6, 600)


# ── the canvas: layout size, refit on resize, a panel's neighbours ──────────

@pytest.fixture(scope="module")
def cbox(tmp_path_factory):
    """The canvas test's sandbox, built the way its `box` fixture builds it."""
    root = tmp_path_factory.mktemp("wbwidth")
    (root / "workbench").mkdir()
    sandbox = _make_sandbox(root / "workbench", canvas_t.CANVAS_JS, canvas_t._SHIM, {})
    for rel in canvas_t._UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    return sandbox


# A viewport the harness can size: its layout box (`clientWidth/Height`) and
# its drawn box (`getBoundingClientRect`, which a transform scales) apart.
_SIZED = r"""
let observed = null;
globalThis.ResizeObserver = class { constructor(fn) { this.fn = fn; } observe(el) { observed = this; } disconnect() {} };
const size = (vp, w, h, scale = 1) => {
  Object.defineProperty(vp, 'clientWidth', { configurable: true, get: () => w });
  Object.defineProperty(vp, 'clientHeight', { configurable: true, get: () => h });
  vp.getBoundingClientRect = () => ({ left: 0, top: 0, x: 0, y: 0, width: w * scale, height: h * scale,
    right: w * scale, bottom: h * scale });
};
const zoomOf = (root) => root.querySelector('.wb-zoom').textContent;
const fitBtn = (root) => root.querySelectorAll('button').find((b) => b.textContent === 'Fit');
"""

# A chain long enough that its whole and its middle fit differently.
_CHAIN = [
    {"id": "a", "name": "Fetch", "task_type": "action", "status": "active", "then_task_id": "b", "else_task_id": None},
    {"id": "b", "name": "Read", "task_type": "llm", "status": "active", "then_task_id": "c", "else_task_id": None},
    {"id": "c", "name": "Write", "task_type": "llm", "status": "active", "then_task_id": "d", "else_task_id": None},
    {"id": "d", "name": "Send", "task_type": "llm", "status": "active", "then_task_id": "e", "else_task_id": None},
    {"id": "e", "name": "Log", "task_type": "llm", "status": "active", "then_task_id": None, "else_task_id": None},
]


def _canvas(box, script, tasks=None):
    setup = "server.tasks = %s;\nserver.prefs = null;\n" % json.dumps(tasks or _CHAIN)
    return _run(box, canvas_t._PREAMBLE + setup + _SIZED, script)


def test_a_fit_reads_the_layout_size_not_the_box_the_entrance_is_scaling(cbox):
    o = _canvas(cbox, """
        const { root } = await mount();
        const vp = root.querySelector('.wb-viewport');
        size(vp, 1000, 600, 0.95); fire(fitBtn(root), 'click'); const mid = zoomOf(root);
        size(vp, 1000, 600, 1); fire(fitBtn(root), 'click'); const end = zoomOf(root);
        out({ mid, end });
    """)
    assert o["mid"] == o["end"], o     # the same graph, the same fit, whatever the entrance is doing


def test_a_resized_canvas_is_fitted_again_until_the_person_moves_the_view(cbox):
    o = _canvas(cbox, """
        const { root } = await mount();
        const vp = root.querySelector('.wb-viewport');
        size(vp, 1400, 600); fire(fitBtn(root), 'click'); const wide = zoomOf(root);
        size(vp, 800, 600); observed.fn([]); const narrower = zoomOf(root);
        // The person pans: the view is theirs now.
        fire(vp, 'pointerdown', { target: vp, clientX: 10, clientY: 10 });
        fire(vp, 'pointermove', { clientX: 60, clientY: 30 }); fire(vp, 'pointerup');
        size(vp, 1400, 600); observed.fn([]); const kept = zoomOf(root);
        out({ wide, narrower, kept });
    """)
    assert o["narrower"] != o["wide"], o    # re-fitted to the smaller viewport (a Versions… box opened)
    assert o["kept"] == o["narrower"], o    # after a pan, a resize changes nothing


def test_with_a_panel_open_the_focused_step_and_its_neighbours_are_fitted(cbox):
    o = _canvas(cbox, """
        const { root, c } = await mount();
        const vp = root.querySelector('.wb-viewport');
        size(vp, 1400, 300);
        c.focusChain('c'); const whole = zoomOf(root);
        c.select('c'); await settle();
        c.focusChain('c'); const near = zoomOf(root);
        out({ whole, near });
    """)
    assert int(o["near"].rstrip("%")) > int(o["whole"].rstrip("%")), o   # b, c, d — not a…e


# ── the room ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rbox(tmp_path_factory):
    """The Automations room test's sandbox, built the way its `box` builds it."""
    root = tmp_path_factory.mktemp("wbwidthroom")
    (root / "workbench").mkdir()
    sandbox = _make_sandbox(root / "workbench", room_t.ROOM_JS, room_t._SHIM, {})
    for rel in canvas_t._UP + ("approvalBox.js", "skillGateNote.js", "settings/mcpFields.js"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    (sandbox / "workflowApi.js").write_text(WORKFLOW_API_JS, encoding="utf-8")
    (sandbox / "workflowSource.js").write_text(WORKFLOW_SOURCE_JS, encoding="utf-8")
    return sandbox


def _room(box, script, world=None, tasks=None):
    return _run(box, room_t._PREAMBLE % (json.dumps(tasks or canvas_t._TASKS), json.dumps(world or room_t._WORLD)),
                script)


def test_make_it_with_no_name_asks_for_one_and_makes_nothing(rbox):
    o = _room(rbox, """
        const { root } = await room();
        fire(by(root, 'wf-shelf-new') || named(root, 'New workflow'), 'click'); await settle(5);
        by(root, 'wf-new-name').value = '   ';
        fire(by(root, 'wf-new-go'), 'click'); await settle(10);
        out({ made: called('createWorkflow').length, note: by(root, 'wf-shelf-note').textContent,
              formOpen: !by(root, 'wf-new').hidden });
    """)
    assert o["made"] == 0, o
    assert o["note"] == "Give it a name first.", o
    assert o["formOpen"] is True, o


def test_no_runs_yet_is_said_in_the_run_list_and_leaves_with_the_tab(rbox):
    world = json.loads(json.dumps(room_t._WORLD))
    world["runs"] = []
    world["workflows"][0]["last_run"] = None
    o = _room(rbox, """
        const { root } = await room();
        await openW(root);
        fire(root.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs'), 'click'); await settle(10);
        const inList = root.querySelectorAll('.wf-run-empty').map((li) => li.textContent);
        const said = sayOf(root);
        const roomLine = !by(root, 'wf-say').hidden;
        fire(root.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Edit'), 'click'); await settle(10);
        out({ inList, said, roomLine, roomLineAfterEdit: !by(root, 'wf-say').hidden });
    """, world)
    assert o["inList"] and o["inList"][0].startswith("No runs yet"), o
    assert o["roomLine"] is False, o           # was drawn above the toolbar, pushing it down
    assert o["roomLineAfterEdit"] is False, o


def test_a_run_says_its_day_and_time_without_seconds(rbox):
    o = _room(rbox, """
        const { root } = await room();
        await openW(root);
        fire(root.querySelectorAll('.wf-tab').find((t) => t.textContent === 'Runs'), 'click'); await settle(15);
        out({ when: root.querySelectorAll('.wf-run-when').map((s) => s.textContent),
              title: root.querySelector('.wf-run-item').title });
    """)
    import re
    assert o["when"], o
    for w in o["when"]:
        # A day in another month this year: "Sep 30, 8:00 AM" — never the full date with seconds.
        assert re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2}\s?[AP]M", w), w
    assert o["title"].startswith("Failed, "), o   # folded to its mark beside a panel, a run still says itself


def test_a_workflows_start_has_no_ports_on_the_chains_canvas(rbox):
    o = _room(rbox, """
        const { root } = await room();
        const wf = itemOf(root, 'tw1'); const task = itemOf(root, 'a');
        out({ wf: wf ? wf.querySelectorAll('.wb-port').length : null,
              task: task ? task.querySelectorAll('.wb-port').length : null });
    """, tasks=canvas_t._TASKS + [{"id": "tw1", "name": "Morning brief", "task_type": "workflow",
                                  "status": "paused", "then_task_id": None, "else_task_id": None}])
    assert o["wf"] == 0, o     # its "after" is the steps inside it
    assert o["task"] == 2, o   # a task keeps "if it works" and "if it fails"


# ── WB-M-14: the task form without its Chain selects ────────────────────────

@pytest.fixture(scope="module")
def fbox(tmp_path_factory):
    """The task form test's sandbox, built the way its `sandbox` builds it."""
    box = _make_sandbox(tmp_path_factory.mktemp("taskfieldsnochain"), form_t.TASKS_JS, form_t._SHIM_PARSED,
                        form_t._STUBS)
    copy = box / form_t.TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + form_t._TASKS_EXPORT, encoding="utf-8")
    fields = box / "tasks" / form_t.TASK_FIELDS_JS.name
    fields.write_text(fields.read_text(encoding="utf-8") + form_t._FIELDS_EXPORT, encoding="utf-8")
    return box


_ROW = {"id": "t1", "name": "Morning brief", "task_type": "llm", "prompt": "Summarise my inbox",
        "status": "active", "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "09:00",
        "then_task_id": "t2", "else_task_id": "t3", "notifications_enabled": True}
_OTHERS = [{"id": "t2", "name": "Post it", "task_type": "llm"}, {"id": "t3", "name": "Tell me", "task_type": "llm"}]


@pytest.mark.parametrize("chain", ["false", "undefined"])
def test_the_workbench_task_form_has_no_chain_selects_and_keeps_the_arrows(fbox, chain):
    out = form_t._case(fbox, {"saved": _ROW}, """
        const host = hostIn();
        mountTaskFields(host, { task: %s, tasks: %s, chain: %s });
        await tick();
        const selects = [!!q(host, 'task-form-chain'), !!q(host, 'task-form-chain-else')];
        click(q(host, 'task-form-save'));
        await tick();
        console.log(JSON.stringify({ selects, writes: writes(), errors: ui.errors }));
    """ % (json.dumps(_ROW), json.dumps([_ROW] + _OTHERS), chain))
    assert out["errors"] == [], out
    (write,) = out["writes"]
    if chain == "false":
        assert out["selects"] == [False, False], out          # the canvas draws the chain
        assert "then_task_id" not in write["body"] and "else_task_id" not in write["body"], write
    else:                                                     # the Tasks window, unchanged (`Law 1`)
        assert out["selects"] == [True, True], out
        assert (write["body"]["then_task_id"], write["body"]["else_task_id"]) == ("t2", "t3"), write
