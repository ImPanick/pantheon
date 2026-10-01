# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1046` — the task card's "Part of a N-step workflow" chip opens the Workbench.

Since `P22-02`, ⋮ → *Workflow* opens the Workbench on a task's workflow and
*Read as a diagram* keeps `P8-34`'s Mermaid view. The chip under a chained
card's meta line — the most visible door on it, titled *Draw this workflow* —
still opened the read-only diagram, where nothing can be changed.

Driven: the real `static/js/tasks.js` in the shared `tasks.js` sandbox
(`tests/test_the_palette_moves_to_the_server_js.py`), with `workbench/workbench.js`
recorded as `tests/test_the_workbench_window_js.py` records it: the chip is
pressed and what was opened is read back. The diagram is still one item down
in the kebab (`Law 1`).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_palette_moves_to_the_server_js import _SHIM as _TASKS_SHIM  # noqa: E402
from test_the_workbench_window_js import _TASKS_STUBS_WB, _EXPORT, _SERVED  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TASKS_JS = ROOT / "static" / "js" / "tasks.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    b = _make_sandbox(tmp_path_factory.mktemp("wbchip"), TASKS_JS, _TASKS_SHIM, _TASKS_STUBS_WB)
    copy = b / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + _EXPORT, encoding="utf-8")
    return b


_CARDS = """
import { document, Node, mockFetch, res, tick } from './shim.js';
const { __k } = await import('./tasks.js');
mockFetch(async () => res(200, %s));
await __k._fetchTasks();
const modal = document.body.appendChild(new Node('div'));
modal.setAttribute('id', 'tasks-modal');
const body = modal.appendChild(new Node('div'));
body.className = 'modal-body';
const list = body.appendChild(new Node('div'));
list.setAttribute('id', 'tasks-list');
__k._renderList();
const ev = { stopPropagation() {}, preventDefault() {} };
const card = (id) => list.querySelectorAll('.task-card').find((c) => c.dataset.id === id);
const chip = (id) => card(id).querySelector('.task-workflow-chip');
""" % json.dumps(_SERVED)


def test_the_chip_opens_the_workbench_on_that_chain(box):
    o = _run(box, _CARDS, """
        const c = chip('b');
        const shown = { text: c.textContent, title: c.title };
        c.dispatchEvent({ type: 'click', ...ev });
        await tick();
        console.log(JSON.stringify({ shown, opened: globalThis.__opened, diagram: body.innerHTML.includes('mermaid') }));
    """)
    assert o["shown"] == {"text": "Part of a 2-step workflow", "title": "Open this workflow in the Workbench"}
    # The Workbench, focused on the task whose chip was pressed, with the Tasks
    # window's own schedule words — what ⋮ → Workflow hands it.
    assert o["opened"] == [{"focusId": "b", "words": "Webhook"}]
    assert o["diagram"] is False, "the chip no longer draws the read-only diagram"


def test_the_chip_and_the_kebab_open_it_the_same_way(box):
    o = _run(box, _CARDS, """
        chip('a').dispatchEvent({ type: 'click', ...ev });
        await tick();
        card('a').querySelector('.memory-item-btn').dispatchEvent({ type: 'click', ...ev });
        const menu = document.querySelectorAll('.task-dropdown').slice(-1)[0];
        menu.children.find((b) => b.textContent === 'Workflow').dispatchEvent({ type: 'click', ...ev });
        await tick();
        console.log(JSON.stringify({ opened: globalThis.__opened,
          labels: document.querySelectorAll('.task-dropdown').slice(-1)[0].children.map((b) => b.textContent) }));
    """)
    assert o["opened"] == [{"focusId": "a", "words": "Webhook"}, {"focusId": "a", "words": "Webhook"}]


def test_a_lone_task_has_no_chip(box):
    served = json.loads(json.dumps(_SERVED))
    served["tasks"][0]["then_task_id"] = None
    served["graph"]["edges"] = []
    o = _run(box, _CARDS.replace(json.dumps(_SERVED), json.dumps(served)), """
        console.log(JSON.stringify({ a: !!chip('a'), b: !!chip('b') }));
    """)
    assert o == {"a": False, "b": False}
