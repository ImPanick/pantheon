# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1067` — opening another step no longer drops the open step's unsaved edits.

**Measured on `5654cd4`.** `B1052` made Escape ask before it closes a step
form with edits. Every other door to another step — a click on a step, Enter
on it, *New step* — went `canvas.js:openPanel` → `closePanel(false)` and
destroyed the open form with no word: the edit was gone, the loss `B1052`
closed, by a different door.

**Now the same rule as Escape and as removing an arrow: said first, done
second.** The first request names the form that would be lost and keeps it;
the same request again — or the sentence's own button — closes it and opens
the next, and says so. Typing in the form in between asks again. Asking for the
open step again keeps its form as it is. A form with no edits is replaced as
before (`Law 1`). The rule is the canvas's, so it holds for a workflow's steps
(a document source) as it does for the tasks.

The real canvas and the real task source, in the canvas test's sandbox and
fake server; the panel is the recorded stand-in, and an edit is what a browser
delivers when a person types in the form — an `input` event reaching the
panel's host.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM, _UP, _TASKS  # noqa: E402
from helpers.workflow_fakes import CANVAS_SOURCE_JS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CANVAS_JS = JS / "workbench" / "canvas.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = _CANVAS_SHIM + CANVAS_SOURCE_JS + r"""
export const itemOf = (root, id) => root.querySelectorAll('.wb-node').find((n) => n.dataset.itemId === id) || null;
/** A person typing in the open form: `input` reaching the panel's host. */
export function type(root) {
  const h = root.querySelector('.wb-panel-host');
  h.dispatchEvent({ type: 'input', target: h, stopPropagation() {}, preventDefault() {} });
}
"""

_PREAMBLE = (
    "import { document, Node, server, net, panel, mountPanel, fire, settle, host, nodeOf, said,"
    " fakeSource, DOC_ITEMS, DOC_EDGES, itemOf, type } from './shim.js';\n"
    "import { dismissTopMenu } from '../escMenuStack.js';\n"
    "const { mountCanvas } = await import('./canvas.js');\n"
    "server.tasks = %s;\n"
    "const tasksCanvas = async () => {\n"
    "  const root = host();\n"
    "  const c = mountCanvas(root, { fetch: net, mountPanel, describeTrigger: (t) => t.trigger_words || '' });\n"
    "  await c.ready; await settle();\n"
    "  return { root, c };\n"
    "};\n"
    "const open = (root) => panel.mounts.filter((m) => !m.destroyed).map((m) => m.args.task ? m.args.task.id : null);\n"
    "const title = (root) => root.querySelector('.wb-panel-title').textContent;\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbkeep")
    (root / "workbench").mkdir()
    sandbox = _make_sandbox(root / "workbench", CANVAS_JS, _SHIM, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    return sandbox


def _case(box, script):
    return _run(box, _PREAMBLE % json.dumps(_TASKS), script)


def test_clicking_another_step_asks_before_it_drops_the_edit(box):
    o = _case(box, """
        const { root } = await tasksCanvas();
        fire(nodeOf(root, 'a'), 'click');
        type(root);
        fire(nodeOf(root, 'b'), 'click');
        const first = { open: open(root), title: title(root), said: said(root),
                        action: root.querySelector('.wb-say-action').textContent };
        fire(nodeOf(root, 'b'), 'click');
        out({ first, second: { open: open(root), title: title(root), said: said(root) } });
    """)
    assert o["first"]["open"] == ["a"] and o["first"]["title"] == "Nightly backup", "the edited form is kept"
    assert o["first"]["said"] == ("Nightly backup has changes that are not saved. Open Message me again to "
                                  "close it without saving them, or Save first.")
    assert o["first"]["action"] == "Open Message me without saving"
    assert o["second"]["open"] == ["b"] and o["second"]["title"] == "Message me"
    assert o["second"]["said"] == "Closed Nightly backup without saving."


def test_enter_and_the_sentences_button_are_the_same_door(box):
    o = _case(box, """
        const { root } = await tasksCanvas();
        fire(nodeOf(root, 'a'), 'click');
        type(root);
        fire(nodeOf(root, 'c'), 'keydown', { key: 'Enter' });
        const kept = open(root);
        fire(root.querySelector('.wb-say-action'), 'click');
        out({ kept, now: open(root), said: said(root) });
    """)
    assert o["kept"] == ["a"]
    assert o["now"] == ["c"] and o["said"] == "Closed Nightly backup without saving."


def test_new_step_asks_too_and_typing_again_asks_again(box):
    o = _case(box, """
        const { root } = await tasksCanvas();
        fire(nodeOf(root, 'a'), 'click');
        type(root);
        const newBtn = root.querySelector('.wb-tool-new');
        fire(newBtn, 'click'); await settle(5);
        const asked = { open: open(root), said: said(root) };
        type(root);                                   // more typing: the yes is withdrawn
        fire(newBtn, 'click'); await settle(5);
        const again = open(root);
        fire(newBtn, 'click'); await settle(5);
        out({ asked, again, now: open(root), title: title(root) });
    """)
    assert o["asked"]["open"] == ["a"]
    assert o["asked"]["said"] == ("Nightly backup has changes that are not saved. Press New step again to "
                                  "close it without saving them, or Save first.")
    assert o["again"] == ["a"], "typing after the question asks again rather than taking the old yes"
    assert o["now"] == [None] and o["title"] == "New step"


def test_the_open_step_asked_for_again_keeps_its_form_and_an_unedited_form_just_moves(box):
    o = _case(box, """
        const { root } = await tasksCanvas();
        fire(nodeOf(root, 'a'), 'click');
        type(root);
        const mountsBefore = panel.mounts.length;
        // Asked for again — twice, so a question held for the second press
        // would show: the open step is not "another" step.
        fire(nodeOf(root, 'a'), 'click');
        fire(nodeOf(root, 'a'), 'click');
        const same = { open: open(root), mounts: panel.mounts.length - mountsBefore,
                       asked: said(root).includes('not saved') };
        // Escape's own question (`B1052`) still works beside this one.
        dismissTopMenu();
        const escAsked = said(root);
        dismissTopMenu();
        fire(nodeOf(root, 'b'), 'click');
        fire(nodeOf(root, 'c'), 'click');
        out({ same, escAsked, plain: open(root) });
    """)
    assert o["same"] == {"open": ["a"], "mounts": 0, "asked": False}, \
        "the open step, asked for again, is left as it is, and nothing is asked"
    assert o["escAsked"].startswith("Nightly backup has changes that are not saved. Press Escape again")
    assert o["plain"] == ["c"], "a form with no edits is replaced at once, as before"


def test_a_workflow_steps_edit_is_kept_the_same_way(box):
    o = _case(box, """
        const { src, S } = fakeSource({ items: DOC_ITEMS, edges: DOC_EDGES });
        const root = host();
        const c = mountCanvas(root, { source: src });
        await c.ready; await settle();
        fire(itemOf(root, 'n1'), 'click');
        type(root);
        fire(itemOf(root, 'n2'), 'click');
        const kept = { opened: S.calls.filter((x) => x[0] === 'openPanel'), destroyed: S.panel.destroyed,
                       dirty: c.isDirty(), said: said(root) };
        fire(itemOf(root, 'n2'), 'click');
        out({ kept, opened: S.calls.filter((x) => x[0] === 'openPanel'), said: said(root) });
    """)
    assert o["kept"]["opened"] == [["openPanel", "n1"]] and o["kept"]["destroyed"] is False
    assert o["kept"]["dirty"] is True
    assert o["kept"]["said"].startswith("Summarise my inbox has changes that are not saved.")
    assert o["opened"] == [["openPanel", "n1"], ["openPanel", "n2"]]
    assert o["said"] == "Closed Summarise my inbox without saving."
