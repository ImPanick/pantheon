# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1048` — the Workbench opens on your own steps, and the canvas is one tab stop.

Measured by `wb-canvas` (`P22-02`) and again on the merged tree (`verify-a`):
`GET /api/tasks` lists the built-in housekeeping tasks (ten on a fresh install,
eight of them paused), so the Workbench's first view was a grid of *Skills
Audit*, *Email Tags*, … before anything the person wrote; and each step was a
tab stop plus its *Connect…*, with the arrows after them — 24 to 28 presses of
Tab to reach one step.

Now: workflows made only of built-ins are set aside until a switch that says
what they are — *Show built-in tasks (10)* — shows them; a built-in joined to a
step of the person's own is part of their workflow and always shown; opening
the Workbench on a built-in shows that workflow. The canvas is one tab stop,
the arrow keys go through the steps in reading order with each step's arrows
after it, and every keyboard path `P22-02` built still works: Enter opens a
step, Tab from the stop reaches its *Connect…*, Delete twice removes an arrow,
and moving a step is M, then the arrow keys as before, then Enter (Escape puts
it back).

Driven: the real `static/js/workbench/canvas.js` in the shared DOM shim, with
`tests/test_the_workbench_canvas_js.py`'s fake server (rows carry `is_builtin`
as `_task_to_dict` serves it) and recorded panel.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workbench_canvas_js import _SHIM, _UP  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CANVAS_JS = JS / "workbench" / "canvas.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The ten built-ins a fresh install lists (names as `HOUSEKEEPING_DEFAULTS` has them).
_BUILTIN_NAMES = ["Skills Audit", "Email Tags", "Calendar Classify Events", "Email Calendar Events",
                  "Email Auto Translate", "Email AI Auto Reply", "Email (Summary)", "Research Tidy",
                  "Memory Tidy", "Chat Sessions Tidy"]


def _builtin(i, name, **extra):
    return {"id": f"b{i}", "name": name, "task_type": "action", "status": "paused" if i < 8 else "active",
            "is_builtin": True, "then_task_id": None, "else_task_id": None, **extra}


_FRESH = [_builtin(i, n) for i, n in enumerate(_BUILTIN_NAMES)]
# The person's own: Backup → (if it works) Message me → (if it fails) Chat
# Sessions Tidy, a built-in joined to their workflow; and a lone step.
_MINE = [
    {"id": "m1", "name": "Backup", "task_type": "llm", "status": "active", "is_builtin": False,
     "then_task_id": "m2", "else_task_id": None},
    {"id": "m2", "name": "Message me", "task_type": "llm", "status": "active", "is_builtin": False,
     "then_task_id": None, "else_task_id": "b9"},
    {"id": "m3", "name": "Weekly report", "task_type": "research", "status": "active", "is_builtin": False,
     "then_task_id": None, "else_task_id": None},
]
_MIXED = _MINE + _FRESH

_PREAMBLE = (
    "import { document, Node, server, net, writes, prefWrites, panel, mountPanel, fire, settle, host, nodeOf,"
    " at, edgeEls, said } from './shim.js';\n"
    "import { dismissTopMenu } from '../escMenuStack.js';\n"
    "const { mountCanvas } = await import('./canvas.js');\n"
    "const mount = async (opts = {}) => {\n"
    "  const root = host();\n"
    "  const c = mountCanvas(root, { fetch: net, mountPanel, ...opts });\n"
    "  await c.ready; await settle();\n"
    "  return { root, c };\n"
    "};\n"
    "const drawn = (root) => root.querySelectorAll('.wb-node').map((n) => n.dataset.taskId);\n"
    "const stops = (root) => [...root.querySelectorAll('.wb-node'), ...edgeEls(root)]\n"
    "  .filter((n) => n.getAttribute('tabindex') === '0')\n"
    "  .map((n) => n.dataset.taskId || (n.getAttribute('data-from') + '>' + n.getAttribute('data-to')));\n"
    "const sw = (root) => { const s = root.querySelector('.wb-tool-switch');\n"
    "  return { hidden: s.hidden, word: s.querySelector('.wb-tool-switch-word').textContent,\n"
    "           checked: !!s.querySelector('input').checked }; };\n"
    "const toggle = (root, on) => { const b = root.querySelector('.wb-tool-switch-box'); b.checked = on; fire(b, 'change'); };\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbown")
    (root / "workbench").mkdir()
    sandbox = _make_sandbox(root / "workbench", CANVAS_JS, _SHIM, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    (root / "windowDrag.js").write_text(
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable() {}\n", encoding="utf-8")
    return sandbox


def _case(box, script, tasks=None):
    setup = "server.tasks = %s;\nserver.prefs = null;\n" % json.dumps(tasks if tasks is not None else _MIXED)
    return _run(box, _PREAMBLE + setup, script)


# ── the built-ins, set aside ───────────────────────────────────────────────

def test_a_fresh_install_opens_on_an_empty_canvas_that_says_why(box):
    o = _case(box, """
        const { root } = await mount();
        const empty = root.querySelector('.wb-empty');
        const first = { drawn: drawn(root), empty: empty.hidden, text: empty.readable, sw: sw(root),
                        note: !root.querySelector('.wb-empty-builtins').hidden };
        toggle(root, true);
        const shown = { drawn: drawn(root).length, empty: empty.hidden, said: said(root), sw: sw(root) };
        toggle(root, false);
        out({ first, shown, again: drawn(root).length, said: said(root) });
    """, tasks=_FRESH)
    f = o["first"]
    assert f["drawn"] == [] and f["empty"] is False
    assert f["text"].startswith("No automations of your own yet.")
    assert "Pantheon’s built-in tasks are hidden here." in f["text"] and f["note"] is True
    assert f["sw"] == {"hidden": False, "word": "Show built-in tasks (10)", "checked": False}
    assert o["shown"] == {"drawn": 10, "empty": True, "said": "Showing the 10 built-in tasks Pantheon comes with.",
                          "sw": {"hidden": False, "word": "Show built-in tasks (10)", "checked": True}}
    assert o["again"] == 0


def test_your_own_steps_come_first_and_a_built_in_joined_to_them_stays(box):
    o = _case(box, """
        const { root } = await mount();
        const first = drawn(root).sort();
        toggle(root, true);
        out({ first, all: drawn(root).length, empty: root.querySelector('.wb-empty').hidden });
    """)
    assert o["first"] == ["b9", "m1", "m2", "m3"], "Chat Sessions Tidy is joined to Message me"
    assert o["all"] == 13 and o["empty"] is True


def test_with_no_built_ins_there_is_no_switch(box):
    o = _case(box, """
        const { root } = await mount();
        out({ sw: sw(root).hidden, drawn: drawn(root).length });
    """, tasks=[dict(t, else_task_id=None) for t in _MINE])
    assert o == {"sw": True, "drawn": 3}


def test_opened_on_a_built_in_its_workflow_is_shown_and_focused(box):
    o = _case(box, """
        const { root } = await mount({ focusId: 'b3' });
        out({ drawn: drawn(root).sort(), focused: !!nodeOf(root, 'b3').focused, stops: stops(root) });
    """)
    assert o["drawn"] == ["b3", "b9", "m1", "m2", "m3"]
    assert o["focused"] is True and o["stops"] == ["b3"]


def test_connect_still_offers_a_built_in_and_joining_one_shows_it(box):
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'm3').querySelector('.wb-node-connect'), 'click');
        const options = root.querySelector('.wb-connect-to').querySelectorAll('option').map((x) => x.textContent);
        root.querySelector('.wb-connect-to').value = 'b0';
        fire(root.querySelector('.wb-connect-go'), 'click');
        await settle(5);
        out({ options: options.length, memory: options.includes('Memory Tidy'), writes: writes(),
              drawn: drawn(root).includes('b0') });
    """)
    assert o["options"] == 12 and o["memory"] is True
    assert o["writes"] == [{"url": "/api/tasks/m3", "method": "PUT", "body": {"then_task_id": "b0"}}]
    assert o["drawn"] is True


def test_the_step_form_is_still_handed_the_whole_list(box):
    """The `P22` panel contract: `tasks` is the full list the response carried
    — the chain pickers offer a built-in whether or not it is drawn."""
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'm1'), 'click');
        out({ n: panel.mounts[0].args.tasks.length });
    """)
    assert o["n"] == 13


# ── one tab stop, the arrow keys within ────────────────────────────────────

_ORDER = ["m1", "m1>m2", "m2", "m2>b9", "b9", "m3"]


def test_the_canvas_is_one_tab_stop_and_its_buttons_follow_it(box):
    o = _case(box, """
        const { root } = await mount();
        const connect = (id) => nodeOf(root, id).querySelector('.wb-node-connect').getAttribute('tabindex');
        out({ stops: stops(root), connects: ['m1', 'm2', 'm3', 'b9'].map(connect) });
    """)
    assert o["stops"] == ["m1"]
    assert o["connects"] == ["0", "-1", "-1", "-1"], "Tab from the stop reaches its own Connect…, no other"


def test_the_arrow_keys_go_through_every_step_and_arrow_in_reading_order(box):
    o = _case(box, """
        const { root } = await mount();
        const where = () => stops(root)[0];
        const el = (k) => k.includes('>') ? edgeEls(root).find((g) => g.getAttribute('data-from') + '>' + g.getAttribute('data-to') === k)
                                          : nodeOf(root, k);
        const down = [where()];
        for (let i = 0; i < 6; i++) { fire(el(where()), 'keydown', { key: i % 2 ? 'ArrowRight' : 'ArrowDown' }); down.push(where()); }
        const up = [];
        for (let i = 0; i < 2; i++) { fire(el(where()), 'keydown', { key: i ? 'ArrowLeft' : 'ArrowUp' }); up.push(where()); }
        fire(el(where()), 'keydown', { key: 'End' }); const end = where();
        const endFocused = !!el(end).focused;
        fire(el(where()), 'keydown', { key: 'Home' }); const home = where();
        out({ down, up, end, endFocused, home, moved: prefWrites().length });
    """)
    assert o["down"] == _ORDER + ["m3"], "the last press stays on the last item"
    assert o["up"] == ["b9", "m2>b9"]
    assert o["end"] == "m3" and o["endFocused"] is True and o["home"] == "m1"
    assert o["moved"] == 0, "going between steps moves none of them"


def test_any_step_or_arrow_is_a_handful_of_presses_away(box):
    """The row's `Verify:`. Counted by pressing, not by arithmetic: from the
    canvas's stop, the presses each item takes — the arrow keys, or End and
    back. With the built-ins aside the person's canvas is six items and none is
    more than three presses away; Tab no longer walks every step and button."""
    o = _case(box, """
        const { root } = await mount();
        const el = (k) => k.includes('>') ? edgeEls(root).find((g) => g.getAttribute('data-from') + '>' + g.getAttribute('data-to') === k)
                                          : nodeOf(root, k);
        const reach = (target) => {
          // The fewer of: ArrowDown from the start, or End then ArrowUp.
          fire(el(stops(root)[0]), 'keydown', { key: 'Home' });
          let down = 0; while (stops(root)[0] !== target && down < 40) { fire(el(stops(root)[0]), 'keydown', { key: 'ArrowDown' }); down++; }
          fire(el(stops(root)[0]), 'keydown', { key: 'Home' });
          fire(el(stops(root)[0]), 'keydown', { key: 'End' });
          let up = 1; while (stops(root)[0] !== target && up < 40) { fire(el(stops(root)[0]), 'keydown', { key: 'ArrowUp' }); up++; }
          return Math.min(down, up);
        };
        const items = %s;
        const aside = Object.fromEntries(items.map((k) => [k, reach(k)]));
        toggle(root, true);
        const shown = root.querySelectorAll('.wb-node').length + edgeEls(root).length;
        out({ aside, shown });
    """ % json.dumps(_ORDER))
    assert max(o["aside"].values()) <= 3, o["aside"]
    # Nine more when shown: the tenth built-in is joined to Message me and was
    # on the canvas already.
    assert o["shown"] == len(_ORDER) + 9


def test_focusing_a_step_with_the_mouse_makes_it_the_stop(box):
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'm3'), 'focus');
        const a = stops(root);
        fire(edgeEls(root)[0], 'focus');
        out({ a, b: stops(root) });
    """)
    assert o["a"] == ["m3"] and o["b"] == ["m1>m2"]


# ── moving a step from the keyboard ────────────────────────────────────────

def test_m_picks_a_step_up_the_arrows_move_it_and_enter_puts_it_down(box):
    o = _case(box, """
        const { root } = await mount();
        const n = nodeOf(root, 'm1'), p0 = at(n);
        fire(n, 'keydown', { key: 'm' });
        const picked = { said: said(root), moving: n._classes().includes('wb-node-moving'),
                         marked: root.dataset.escLayer != null };
        fire(n, 'keydown', { key: 'ArrowRight' });
        fire(n, 'keydown', { key: 'ArrowRight' });
        fire(n, 'keydown', { key: 'ArrowDown', shiftKey: true });
        const p1 = at(nodeOf(root, 'm1'));
        fire(n, 'keydown', { key: 'Enter' });
        await settle(5);
        const down = { said: said(root), moving: nodeOf(root, 'm1')._classes().includes('wb-node-moving'),
                       saved: server.prefs, panel: panel.mounts.length };
        fire(nodeOf(root, 'm1'), 'keydown', { key: 'ArrowRight' });
        out({ p0, p1, picked, down, after: at(nodeOf(root, 'm1')), stop: stops(root) });
    """)
    assert o["picked"] == {
        "said": "Moving Backup: the arrow keys move it, with Shift in bigger steps. Enter puts it down; "
                "Escape puts it back.", "moving": True, "marked": True}
    assert (o["p1"]["x"] - o["p0"]["x"], o["p1"]["y"] - o["p0"]["y"]) == (32, 64)
    assert o["down"]["said"] == "Put Backup down." and o["down"]["moving"] is False
    assert o["down"]["saved"] == {"v": 1, "tasks": {"m1": [o["p1"]["x"], o["p1"]["y"]]}}
    assert o["down"]["panel"] == 0, "Enter put the step down; it did not open it"
    assert o["after"] == o["p1"] and o["stop"] == ["m1>m2"], "put down, the arrows go between steps again"


def test_escape_puts_a_picked_up_step_back(box):
    o = _case(box, """
        const { root } = await mount();
        const n = nodeOf(root, 'm3'), p0 = at(n);
        fire(n, 'keydown', { key: 'M' });
        fire(n, 'keydown', { key: 'ArrowLeft' });
        fire(n, 'keydown', { key: 'ArrowUp', shiftKey: true });
        const moved = at(nodeOf(root, 'm3'));
        const escaped = dismissTopMenu();
        await settle(5);
        out({ p0, moved, escaped, back: at(nodeOf(root, 'm3')), said: said(root), saved: server.prefs,
              focused: !!nodeOf(root, 'm3').focused, marked: root.dataset.escLayer != null });
    """)
    assert o["moved"] != o["p0"] and o["escaped"] is True
    assert o["back"] == o["p0"]
    assert o["said"] == "Weekly report is back where it was."
    assert o["saved"] == {"v": 1, "tasks": {}}, "a step nobody had placed is not kept anywhere"
    assert o["focused"] is True and o["marked"] is False


def test_the_paths_p22_02_built_still_work(box):
    """Enter opens a step; Connect… is there; Delete twice removes an arrow;
    the zoom keys still answer on a step."""
    o = _case(box, """
        const { root } = await mount();
        fire(nodeOf(root, 'm2'), 'keydown', { key: 'Enter' });
        const opened = panel.mounts.length;
        dismissTopMenu();
        const g = edgeEls(root).find((x) => x.getAttribute('data-from') === 'm1');
        fire(g, 'focus'); fire(g, 'keydown', { key: 'Delete' }); fire(g, 'keydown', { key: 'Delete' });
        await settle(5);
        const zoom = root.querySelector('.wb-zoom').textContent;
        fire(nodeOf(root, 'm3'), 'keydown', { key: '+' });
        out({ opened, writes: writes(), zoomed: root.querySelector('.wb-zoom').textContent !== zoom });
    """)
    assert o["opened"] == 1
    assert o["writes"] == [{"url": "/api/tasks/m1", "method": "PUT", "body": {"then_task_id": ""}}]
    assert o["zoomed"] is True
