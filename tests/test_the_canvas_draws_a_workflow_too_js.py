# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-05` (wf-ui) — one canvas draws a workflow document too (`Law 14`).

Until Slice B, `static/js/workbench/canvas.js` knew one thing: tasks. It read
`GET /api/tasks`, wrote `PUT /api/tasks/{id}`, kept positions in a preference
and mounted the task form. A workflow document is drawn on the same canvas, so
the canvas now draws whatever a *source* hands it — the canvas source contract
(C3, `/work/notes/SLICE-B-DESIGN.md` § 6.3, § 7) — and today's tasks are one
source (`taskSource.js`). `test_the_workbench_canvas_js.py` (27 cases) proves
the tasks canvas did not move; these cases prove what a document needs and the
tasks never had:

  * an item with no ports — a workflow's start — and an arrow that is `fixed`
    (the start's, which cannot be removed) and carries its own `label`;
  * an item no arrow may land on (`accepts: false`);
  * `marks` drawn as words on the step ("Sample pinned"), never markup;
  * a `readOnly` source (a run): no ports, no Connect…, no New, no Tidy, no
    moving, no removing — and a click still opens the step;
  * a step removed by Delete pressed twice, said first (`removeItem`);
  * *New step* asking the source (`newItem`, the palette) and opening what it
    added;
  * a whole document planned with no head (`dryRun()`);
  * a step's Done on a source that saves later says the change is in the
    draft, not that it was saved.

The source is a fake in the contract's exact shape (`tests/helpers/
workflow_fakes.py`); the canvas, the layout and every module they import are
the real ones, in the canvas test's own sandbox and shim (`Law 14`).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM, _UP  # noqa: E402
from helpers.workflow_fakes import CANVAS_SOURCE_JS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CANVAS_JS = JS / "workbench" / "canvas.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = _CANVAS_SHIM + CANVAS_SOURCE_JS + r"""
export const itemOf = (root, id) => root.querySelectorAll('.wb-node').find((n) => n.dataset.itemId === id) || null;
"""

_PREAMBLE = (
    "import { document, Node, fire, settle, host, portOf, at, edgeEls, edges, said, refused, markup,"
    " fakeSource, DOC_ITEMS, DOC_EDGES, itemOf } from './shim.js';\n"
    "import { dismissTopMenu } from '../escMenuStack.js';\n"
    "const { mountCanvas } = await import('./canvas.js');\n"
    "const mount = async (spec = {}, opts = {}) => {\n"
    "  const { src, S } = fakeSource({ items: DOC_ITEMS, edges: DOC_EDGES, ...spec });\n"
    "  const root = host();\n"
    "  const c = mountCanvas(root, { source: src, ...opts });\n"
    "  await c.ready; await settle();\n"
    "  return { root, c, src, S };\n"
    "};\n"
    "const edgeTo = (root, from, to) => edgeEls(root).find((g) => g.getAttribute('data-from') === from"
    " && g.getAttribute('data-to') === to);\n"
    "const calls = (S, name) => S.calls.filter((c) => c[0] === name);\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbsource")
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
    return _run(box, _PREAMBLE, script)


def test_a_documents_start_has_no_ports_and_its_arrow_has_its_own_word(box):
    o = _case(box, """
        const { root, S } = await mount();
        const start = itemOf(root, '__start__'), n1 = itemOf(root, 'n1');
        out({
          startPorts: start.querySelectorAll('.wb-port').length,
          startConnect: !!start.querySelector('.wb-node-connect'),
          n1Ports: n1.querySelectorAll('.wb-port').map((p) => p.dataset.when),
          n1Connect: !!n1.querySelector('.wb-node-connect'),
          taskId: n1.dataset.taskId || null,
          edges: edges(root),
          region: root.querySelector('.wb-viewport').getAttribute('aria-label'),
          hint: root.querySelector('.wb-hint').textContent,
          newWord: root.querySelector('.wb-tool-new').textContent,
          first: S.calls.slice(0, 2).map((c) => c[0]).sort(),
        });
    """)
    assert o["startPorts"] == 0 and o["startConnect"] is False, "the start has no ports and no Connect…"
    assert o["n1Ports"] == ["success", "error"] and o["n1Connect"] is True
    assert o["taskId"] is None, "a document's step is not a task: no `data-task-id`"
    assert o["edges"][0] == {"from": "__start__", "to": "n1", "when": "success", "words": "starts",
                             "label": "Summarise my inbox runs first."}, \
        "the start's arrow carries the source's own word and is not offered for removal"
    assert o["edges"][1]["label"] == ("After Summarise my inbox, if it works, Send me the summary runs. "
                                      "Press Delete to remove this arrow.")
    assert o["region"] == "Steps of Morning brief"
    assert o["hint"] == "Drag from a step to the next one."
    assert o["newWord"] == "Add a step"
    assert o["first"] == ["load", "loadPositions"], "everything is read through the source"


def test_the_start_arrow_cannot_be_removed_and_a_step_arrow_can(box):
    o = _case(box, """
        const { root, S } = await mount();
        const fixed = edgeTo(root, '__start__', 'n1');
        fire(fixed, 'focus'); fire(fixed, 'keydown', { key: 'Delete' }); fire(fixed, 'keydown', { key: 'Delete' });
        await settle(5);
        const fixedSaid = said(root);
        const plain = edgeTo(root, 'n1', 'n2');
        fire(plain, 'focus'); fire(plain, 'keydown', { key: 'Delete' });
        const asked = said(root), before = calls(S, 'disconnect').length;
        fire(plain, 'keydown', { key: 'Delete' });
        await settle(5);
        out({ fixedSaid, asked, before, disconnects: calls(S, 'disconnect'), after: said(root),
              left: edges(root).map((e) => [e.from, e.to]) });
    """)
    assert o["fixedSaid"] == ("Summarise my inbox runs first. This arrow always leads to the first step, "
                              "so it cannot be removed.")
    assert o["asked"].startswith("Remove this arrow? ") and o["before"] == 0, "said first"
    assert o["disconnects"] == [["disconnect", "n1", "success", "n2"]], "removed second, through the source"
    assert o["after"] == "Removed. Send me the summary no longer runs after Summarise my inbox if it works."
    assert o["left"] == [["__start__", "n1"]]


def test_no_arrow_can_land_on_the_start(box):
    o = _case(box, """
        const { root, S } = await mount();
        fire(itemOf(root, 'n2').querySelector('.wb-node-connect'), 'click');
        const to = root.querySelector('.wb-connect-to');
        const options = to.querySelectorAll('option').map((x) => x.value);
        // A drag from n2's port let go over the start connects nothing.
        dismissTopMenu();
        const port = portOf(itemOf(root, 'n2'), 'success'), s = at(itemOf(root, '__start__'));
        fire(port, 'pointerdown', {}); fire(port, 'pointerup', { clientX: s.x + 5, clientY: s.y + 5 });
        await settle(5);
        out({ options, connects: calls(S, 'connect') });
    """)
    assert o["options"] == ["n1"], "the start accepts no arrow, and a step does not lead to itself"
    assert o["connects"] == []


def test_a_mark_is_a_word_on_the_step_and_nothing_a_person_wrote_is_markup(box):
    hostile = '<img src=x onerror="alert(1)">'
    o = _case(box, """
        const items = JSON.parse(JSON.stringify(DOC_ITEMS));
        items[1].name = %s; items[1].marks = ['Sample pinned', '<b>bold</b>'];
        const edges0 = JSON.parse(JSON.stringify(DOC_EDGES)); edges0[0].label = '<i>starts</i>';
        const { root } = await mount({ items, edges: edges0 });
        const n1 = itemOf(root, 'n1');
        const n2 = itemOf(root, 'n2');
        out({ title: n1.querySelector('.wb-node-title').textContent,
              badges: n1.querySelectorAll('.wb-node-badge').map((b) => b.textContent),
              label: edges(root)[0].words, markup: markup(root),
              marks: ['__start__', 'n1'].map((id) => itemOf(root, id).querySelector('.wb-node-mark').textContent) });
    """ % json.dumps(hostile))
    assert o["title"] == hostile
    # An outcome is a mark AND a word: a step with no word to say (the start
    # here, a draft's step) has no lone mark either.
    assert o["marks"] == ["", "○"]
    assert o["badges"] == ["Sample pinned", "<b>bold</b>"]
    assert o["label"] == "<i>starts</i>"
    assert o["markup"] == [], "no innerHTML with data anywhere in the room"


def test_a_read_only_source_draws_a_run_that_can_be_read_and_not_changed(box):
    o = _case(box, """
        const { root, c, S } = await mount({ readOnly: true });
        const n1 = itemOf(root, 'n1'), p0 = at(n1);
        fire(n1, 'keydown', { key: 'm' });
        const moving = n1._classes().includes('wb-node-moving');
        fire(n1, 'pointerdown', { clientX: p0.x + 10, clientY: p0.y + 10 });
        fire(n1, 'pointermove', { clientX: p0.x + 200, clientY: p0.y + 200 });
        fire(n1, 'pointerup', { clientX: p0.x + 200, clientY: p0.y + 200 });
        await settle(5);
        const e = edgeTo(root, 'n1', 'n2');
        fire(e, 'focus'); fire(e, 'keydown', { key: 'Delete' }); fire(e, 'keydown', { key: 'Delete' });
        fire(n1, 'keydown', { key: 'Delete' }); fire(n1, 'keydown', { key: 'Delete' });
        await settle(5);
        fire(itemOf(root, 'n1'), 'click');
        out({ ports: root.querySelectorAll('.wb-port').length, connect: root.querySelectorAll('.wb-node-connect').length,
              newHidden: root.querySelector('.wb-tool-new').hidden, tidyHidden: root.querySelectorAll('.wb-tool')
                .find((b) => b.textContent === 'Tidy up').hidden,
              readOnly: root._classes().includes('wb-read-only'), moving, moved: at(itemOf(root, 'n1')), p0,
              label: e.getAttribute('aria-label'),
              writes: S.calls.filter((x) => ['savePositions', 'disconnect', 'removeItem', 'connect'].includes(x[0])),
              opened: calls(S, 'openPanel') });
    """)
    assert o["ports"] == 0 and o["connect"] == 0
    assert o["newHidden"] is True and o["tidyHidden"] is True and o["readOnly"] is True
    assert o["moving"] is False and o["moved"] == o["p0"], "a run's steps do not move"
    assert "Press Delete" not in o["label"]
    assert o["writes"] == [], "a read-only source is never written to"
    assert o["opened"] == [["openPanel", "n1"]], "a step of a run still opens (its record)"


def test_a_step_is_removed_by_delete_pressed_twice_said_first(box):
    o = _case(box, """
        const { root, S } = await mount();
        const n2 = itemOf(root, 'n2');
        fire(n2, 'focus'); fire(n2, 'keydown', { key: 'Delete' });
        const asked = said(root), early = calls(S, 'removeItem').length;
        const escaped = dismissTopMenu();
        const kept = said(root);
        fire(itemOf(root, 'n2'), 'keydown', { key: 'Delete' }); fire(itemOf(root, 'n2'), 'keydown', { key: 'Delete' });
        await settle(5);
        const start = itemOf(root, '__start__');
        fire(start, 'keydown', { key: 'Delete' });
        out({ asked, early, escaped, kept, removed: calls(S, 'removeItem'), gone: !itemOf(root, 'n2'),
              startSaid: said(root), startStill: !!itemOf(root, '__start__') });
    """)
    assert o["asked"] == "Remove Send me the summary? Press Delete again to remove it, or Escape to keep it."
    assert o["early"] == 0
    assert o["escaped"] is True and o["kept"] == "Kept Send me the summary."
    assert o["removed"] == [["removeItem", "n2"]] and o["gone"] is True
    assert o["startSaid"] == "Starts · Every day at 08:00 cannot be removed." and o["startStill"] is True


def test_new_step_asks_the_source_and_opens_what_it_added(box):
    o = _case(box, """
        const { root, S } = await mount();
        fire(root.querySelector('.wb-tool-new'), 'click');
        await settle(10);
        out({ asked: calls(S, 'newItem'), drawn: !!itemOf(root, 'n9'), opened: calls(S, 'openPanel'),
              panel: !root.querySelector('.wb-panel').hidden });
    """)
    assert o["asked"] == [["newItem", "wb-tool wb-tool-new"]], "the palette is anchored on the button pressed"
    assert o["drawn"] is True
    assert o["opened"] == [["openPanel", "n9"]] and o["panel"] is True


def test_a_document_is_planned_whole_from_no_head(box):
    o = _case(box, """
        const plans = [['__start__', { steps: [{ kind: 'dry-run', detail: 'Would start: Every day at 08:00.' }],
                                       declined: null, when: null, depth: 0 }],
                       ['n1', { steps: [{ kind: 'dry-run', detail: 'Would send this task’s prompt to a model, with tools.' }],
                                declined: null, when: 'success', depth: 1 }]];
        const { root, c, S } = await mount({ plans });
        await c.dryRun(null, { title: 'Morning brief' });
        await settle(5);
        out({ asked: calls(S, 'dryRun'), said: said(root),
              n1: itemOf(root, 'n1').dataset.plan, n2: itemOf(root, 'n2').dataset.plan,
              line: itemOf(root, 'n1').querySelector('.wb-node-plan-line').textContent,
              startSub: itemOf(root, '__start__').querySelector('.wb-node-sub').textContent });
    """)
    assert o["asked"] == [["dryRun"]], "a workflow's source is asked with no head"
    assert o["said"].startswith("Dry run of Morning brief — nothing ran. 2 steps planned;")  # P23-05 (COPY-U-24)
    assert o["n1"] == "planned" and o["n2"] == "aside"
    assert o["line"] == "Would send this task’s prompt to a model, with tools."
    # The start is not a Prompt: a kind the diagram has no word for is not
    # given the word for another (found in Chromium: "Starts here · Prompt").
    assert o["startSub"] == "Starts here"


def test_a_steps_done_on_a_source_that_saves_later_says_it_is_in_the_draft(box):
    o = _case(box, """
        const { root, S } = await mount({ save: true });
        fire(itemOf(root, 'n1'), 'click');
        await S.panel.cb.onSaved({ id: 'n1', label: 'Summarise my inbox' });
        await settle(5);
        const draft = said(root);
        const plain = await mount({});
        fire(itemOf(plain.root, 'n1'), 'click');
        await plain.S.panel.cb.onSaved({ id: 'n1', name: 'Summarise my inbox' });
        await settle(5);
        out({ draft, plain: said(plain.root), closed: root.querySelector('.wb-panel').hidden,
              loads: calls(S, 'load').length });
    """)
    assert o["draft"] == "Changed Summarise my inbox. Save keeps it in the workflow."
    assert o["plain"] == "Saved Summarise my inbox."
    assert o["closed"] is True and o["loads"] == 2, "the panel closes and the canvas redraws from the source"


def test_a_refusal_from_the_source_is_said_word_for_word(box):
    o = _case(box, """
        const answered = await mount({ refuse: 'Each outcome of a step can lead to one step.' });
        fire(itemOf(answered.root, 'n2').querySelector('.wb-node-connect'), 'click');
        fire(answered.root.querySelector('.wb-connect-go'), 'click');
        await settle(5);
        const thrown = await mount({ throwOnConnect: 'This workflow is at most 20 steps.' });
        fire(itemOf(thrown.root, 'n2').querySelector('.wb-node-connect'), 'click');
        fire(thrown.root.querySelector('.wb-connect-go'), 'click');
        await settle(5);
        out({ a: said(answered.root), aRef: refused(answered.root),
              aBox: answered.root.querySelector('.wb-connect-say').textContent,
              b: said(thrown.root), bRef: refused(thrown.root) });
    """)
    assert o["a"] == "Not connected: Each outcome of a step can lead to one step." and o["aRef"] is True
    assert o["aBox"] == "Not connected: Each outcome of a step can lead to one step."
    assert o["b"] == "Not connected: This workflow is at most 20 steps." and o["bRef"] is True


def test_a_moved_step_is_kept_through_the_source(box):
    o = _case(box, """
        const { root, S } = await mount();
        const n1 = itemOf(root, 'n1'), p0 = at(n1);
        fire(n1, 'pointerdown', { clientX: p0.x + 10, clientY: p0.y + 10 });
        fire(n1, 'pointermove', { clientX: p0.x + 160, clientY: p0.y + 10 });
        fire(n1, 'pointerup', { clientX: p0.x + 160, clientY: p0.y + 10 });
        await settle(5);
        out({ p1: at(itemOf(root, 'n1')), saved: calls(S, 'savePositions') });
    """)
    assert o["saved"] == [["savePositions", [["n1", {"x": o["p1"]["x"], "y": o["p1"]["y"]}]]]], \
        "a Map of the moved steps' {x, y}"
