# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P22-02` — the Workbench is a window like every other, and has two doors.

Four parts, each against the real module it is about:

  1. **Registration** — the real `static/js/modalManager.js` in `P9-11`'s dock
     sandbox (`tests/test_background_work_dock_js.py`): the Workbench is listed
     for the command palette with its label and its rail door, its closed-window
     door presses the rail button, and minimising it puts a chip on the dock
     carrying the shared table's glyph — `_LABELS` and `_AUTO_WIRE`, read by
     calling the functions that read them.
  2. **The markup** — the rail button sits where the rail's order puts it, and
     it and the window's title draw `icons.js:WORKFLOW_GLYPH` exactly. Markup
     cannot import a table (`B292`); this is the second option `B292` named —
     the literal and the table are held equal here, so one cannot drift.
  3. **The glue** — the real `workbench/workbench.js`, `canvas.js` and
     `graphLayout.js`, with `tasks/taskFields.js` replaced by a stub of the
     `P22` panel contract (it lands with `wb-fields`). The window's DOM is
     rebuilt from `static/index.html`'s own `#workbench-modal` block, parsed,
     not transcribed. Proven: the room switcher is drawn from `ROOMS`, the
     window is made draggable and dockable once, opening on a task focuses its
     workflow, and **selecting a step mounts the form through the contract's
     `mountTaskFields`** — the import the glue exists to make.
  4. **⋮ → Workflow** — the real `tasks.js` in the shared `tasks.js` sandbox: the
     kebab offers *Workflow* (the Workbench, on that task, with the Tasks
     window's own schedule words) and *Read as a diagram* (the Mermaid drawing
     `P8-34` built, which stays).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_background_work_dock_js import _SHIM as _DOCK_SHIM, _STUBS as _DOCK_STUBS  # noqa: E402
from test_the_palette_moves_to_the_server_js import _SHIM as _TASKS_SHIM, _STUBS as _TASKS_STUBS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
INDEX = ROOT / "static" / "index.html"
MODALS_JS = JS / "modalManager.js"
WORKBENCH_JS = JS / "workbench" / "workbench.js"
TASKS_JS = JS / "tasks.js"
ICONS_JS = JS / "icons.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _node(script: str) -> dict:
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _table_glyph() -> str:
    return _node("import { WORKFLOW_GLYPH, iconSvg } from '%s';"
                 "console.log(JSON.stringify({ g: WORKFLOW_GLYPH,"
                 " chip: iconSvg(WORKFLOW_GLYPH, { outline: true }) }));" % ICONS_JS.as_posix())


# ── 1. registration, through the real modalManager.js ───────────────────────

@pytest.fixture(scope="module")
def dock(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("wbdock"), MODALS_JS, _DOCK_SHIM, _DOCK_STUBS)


_DOCK_PREAMBLE = (
    "import { document, Node, click, readDock } from './shim.js';\n"
    # `register` watches a window's element; the shim has no observer, and the
    # one `test_settings_comes_back_through_its_own_door_js.py` uses is this.
    "globalThis.MutationObserver = class { observe() {} disconnect() {} };\n"
    "import * as Modals from './modalManager.js';\n"
    "const rail = document.body.appendChild(new Node('button'));\n"
    "rail.setAttribute('id', 'rail-workbench');\n"
    "globalThis.__pressed = [];\n"
    "rail.addEventListener('click', () => globalThis.__pressed.push('rail-workbench'));\n"
)


def test_the_palette_lists_the_workbench_by_its_name_and_its_rail_door(dock):
    o = _run(dock, _DOCK_PREAMBLE, """
        const w = Modals.listWindows().find((x) => x.id === 'workbench-modal');
        const opened = Modals.showWindow('workbench-modal');
        console.log(JSON.stringify({ w, opened, pressed: globalThis.__pressed }));
    """)
    assert o["w"] == {"id": "workbench-modal", "label": "Workbench", "door": True,
                      "doors": ["rail-workbench", "tool-workbench-btn"], "state": "closed"}
    # A closed Workbench is opened by pressing the door a person would press.
    assert o["opened"] == "opened" and o["pressed"] == ["rail-workbench"]


def test_minimising_the_workbench_leaves_a_chip_with_its_name_and_the_tables_glyph(dock):
    table = _table_glyph()
    o = _run(dock, _DOCK_PREAMBLE, """
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'workbench-modal');
        modal.className = 'modal';
        const content = modal.appendChild(new Node('div'));
        content.className = 'modal-content';
        const header = content.appendChild(new Node('div'));
        header.className = 'modal-header';
        Modals.minimize('workbench-modal');
        const chip = document.getElementById('minimized-dock').querySelectorAll('.minimized-dock-chip')[0];
        console.log(JSON.stringify({ dock: readDock(), html: chip._writtenHtml,
          badge: rail._classes().includes('rail-minimized'), state: Modals.windowState('workbench-modal') }));
    """)
    assert o["dock"][0]["id"] == "workbench-modal"
    assert o["dock"][0]["title"] == "Restore Workbench"
    assert table["chip"] in o["html"], "the chip draws the shared table's glyph"
    assert '<span class="minimized-dock-label">Workbench</span>' in o["html"]
    assert o["badge"] is True and o["state"] == "minimized"


# ── 2. the markup ───────────────────────────────────────────────────────────

def _rail_buttons() -> list:
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<div class="icon-rail" id="icon-rail"')
    end = html.index("</div>\n\n  <nav class=\"sidebar\"", start)
    rail = html[start:end]
    out = []
    for m in re.finditer(r'<button class="icon-rail-btn[^"]*" id="([^"]+)"[^>]*>(.*?)</button>'
                         r'|<div style="flex:1"></div>', rail, re.S):
        out.append(m.group(1) or "<spacer>")
    return out, rail


def _svg_children(fragment: str):
    m = re.search(r"<svg([^>]*)>(.*?)</svg>", fragment, re.S)
    assert m, fragment[:200]
    return m.group(1), m.group(2)


def test_the_rail_button_is_the_last_launcher_before_the_spacer(tmp_path):
    """The launchers are alphabetical by the names they were added under —
    Library, Memory (now Brain), Notes, Tasks, Theme — so W goes last, and the
    spacer keeps Settings at the bottom."""
    order, _ = _rail_buttons()
    i = order.index("rail-workbench")
    assert order[i - 1] == "rail-theme"
    assert order[i + 1] == "<spacer>"
    assert order[-1] == "rail-settings"


def test_the_sidebar_door_is_the_last_of_the_tools_and_customize_ui_can_hide_both():
    """Measured in Chromium at 1400px before this was added: with the sidebar
    open — the default on a desktop — the icon rail is `display: none`, so a
    rail-only door is one the person in this row's `Verify` never sees. Every
    tool has its row in the sidebar's Tools and its rail twin presses it
    (`app.js:_railToolMap`); Customize UI hides the pair together."""
    html = INDEX.read_text(encoding="utf-8")
    tools = html[html.index('id="tools-section"'):html.index('id="sidebar-user-bar"')]
    ids = re.findall(r'<(?:button|div) type="button" class="list-item" id="([^"]+)"', tools) or \
        re.findall(r'class="list-item"[^>]*id="([^"]+)"', tools)
    assert ids[-2:] == ["tool-theme-btn", "tool-workbench-btn"], ids
    row = re.search(r'<input type="checkbox" checked data-ui-key="tool-workbench">', html)
    assert row, "Customize UI has no switch for the Workbench"
    vis = _node("import { UI_VIS_MAP } from '%s';"
                "console.log(JSON.stringify(UI_VIS_MAP['tool-workbench'] || null));"
                % (JS / "ui_visibility.js").as_posix())
    assert vis == "#tool-workbench-btn, #rail-workbench"


def test_every_door_and_the_window_title_draw_the_tables_glyph_exactly():
    """The rail button, the Tools row, the Customize UI switch and the window's
    title: four spellings in markup, each equal to `WORKFLOW_GLYPH`."""
    table = _table_glyph()["g"]
    html = INDEX.read_text(encoding="utf-8")
    sites = {
        "rail": re.search(r'<button class="icon-rail-btn" id="rail-workbench"[^>]*>(.*?)</button>', html, re.S),
        "tools": re.search(r'<button type="button" class="list-item" id="tool-workbench-btn">(.*?)</button>', html, re.S),
        "customize": re.search(r'(<svg.*?</svg>)', html[html.rindex(
            '<span class="vis-icon">', 0, html.index('<span class="vis-label">Workbench</span>')):], re.S),
        "title": re.search(r'<div id="workbench-modal".*?<h4>(.*?)</h4>', html, re.S),
    }
    for where, m in sites.items():
        assert m, f"the Workbench's {where} glyph moved — re-read this test"
        attrs, inner = _svg_children(m.group(1))
        assert inner == table, where
        assert 'aria-hidden="true"' in attrs, where


# ── 3. the glue, with the panel contract stubbed ────────────────────────────

class _Tree(HTMLParser):
    """`#workbench-modal` and everything in it, as `[tag, attrs, children]`.
    SVG is skipped: it is drawing, not structure the glue reaches for."""

    VOID = {"input", "br", "img", "meta", "link", "hr"}

    def __init__(self):
        super().__init__()
        self.root = None
        self.stack = []
        self.svg = 0

    def handle_starttag(self, tag, attrs):
        if tag == "svg" or self.svg:
            self.svg += 0 if tag in self.VOID else 1
            return
        node = [tag, dict(attrs), []]
        if self.stack:
            self.stack[-1][2].append(node)
        elif dict(attrs).get("id") == "workbench-modal":
            self.root = node
        else:
            return
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if self.svg:
            self.svg -= 1
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()


def _window_tree():
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<div id="workbench-modal"')
    p = _Tree()
    p.feed(html[start:])
    assert p.root, "the Workbench window is not in static/index.html"
    return p.root


_GLUE_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};

function build(spec, parent) {
  const [tag, attrs, kids] = spec;
  const n = parent.appendChild(new Node(tag));
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v; else n.setAttribute(k, v);
  }
  for (const k of kids) build(k, n);
  return n;
}
export const modal = build(__TREE__, document.body);

export const server = { calls: [], tasks: [
  { id: 'a', name: 'Nightly backup', task_type: 'action', status: 'active', schedule: 'daily',
    then_task_id: 'b', else_task_id: null },
  { id: 'b', name: 'Message me', task_type: 'llm', status: 'active', then_task_id: null, else_task_id: null },
] };
globalThis.fetch = async (url, init = {}) => {
  server.calls.push({ url: String(url), method: init.method || 'GET' });
  const ok = (body) => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(body)) });
  // `P22-04`: a chain dry run, in the contract's shape (P22-WAVE-B.md).
  const dry = /^\/api\/tasks\/([^/]+)\/run\?dry=true&chain=true$/.exec(String(url));
  if (dry && init.method === 'POST') {
    const steps = [{ kind: 'dry-run', detail: 'Would run: tidy_sessions — Tidy sessions' }];
    return ok({ ok: true, dry: true, message: 'Dry run — planned, nothing executed', run_id: 'r1',
      run: { id: 'r1', status: 'skipped', steps },
      chain: [{ task_id: 'a', name: 'Nightly backup', when: null, depth: 0, steps, declined: null },
              { task_id: 'b', name: 'Message me', when: 'success', depth: 1,
                steps: [{ kind: 'dry-run', detail: 'Would send this task’s prompt to a model, with tools.' }],
                declined: null }] });
  }
  if (String(url).startsWith('/api/tasks')) {
    const edges = server.tasks.filter((t) => t.then_task_id)
      .map((t) => ({ from: t.id, to: t.then_task_id, when: 'success', dangling: false }));
    return ok({ tasks: server.tasks, graph: { nodes: server.tasks.map((t) => ({ id: t.id, name: t.name })), edges } });
  }
  return ok({ key: 'workbench_positions', value: null });
};
export function fire(node, type, extra = {}) {
  node.dispatchEvent(Object.assign({ type, target: node, currentTarget: node, button: 0,
    preventDefault() {}, stopPropagation() {} }, extra));
}
export const settle = (ms = 0) => new Promise((r) => setTimeout(r, ms));
export const $ = (id) => document.getElementById(id);
"""

_GLUE_STUBS = {
    "tasks/taskFields.js": (
        "globalThis.__fields = [];\n"
        "export function mountTaskFields(host, args) {\n"
        "  const rec = { host, args, destroyed: false };\n"
        "  globalThis.__fields.push(rec);\n"
        "  return { destroy() { rec.destroyed = true; } };\n"
        "}\n"
    ),
    "windowDrag.js": (
        "globalThis.__drag = [];\n"
        "export const KEY_STEP = 16;\nexport const MOVE_THRESHOLD = 4;\n"
        "export function makeWindowDraggable(modal, o) { globalThis.__drag.push({ id: modal.id,\n"
        "  content: !!o.content, header: !!o.header, dock: o.enableDock, left: o.enableLeftDock }); }\n"
    ),
    "modalManager.js": (
        "globalThis.__minimized = false; globalThis.__restored = [];\n"
        "export function isMinimized() { return globalThis.__minimized; }\n"
        "export function restore(id) { globalThis.__restored.push(id); globalThis.__minimized = false;"
        " document.getElementById(id).classList.remove('hidden'); return true; }\n"
    ),
    # `P22-04`. The glue imports the Tasks card's step renderer from the
    # `tasks.js` instance already on the page (`?v=` and all); recorded here.
    "tasks.js": (
        "globalThis.__rendered = [];\n"
        "export function renderRunSteps(run, opts) { globalThis.__rendered.push({ run, opts });\n"
        "  return '<ol class=\"task-run-step-list\"><li>rendered by tasks.js</li></ol>'; }\n"
    ),
}

_UP = ("tasks/workflowDiagram.js", "runStatus.js", "editor/snap.js", "escMenuStack.js",
       # `P22-09`…`P22-18` (wf-canvas): the room's step forms reach these with `../`.
       "approvalBox.js", "skillGateNote.js", "settings/mcpFields.js")


@pytest.fixture(scope="module")
def glue(tmp_path_factory):
    root = tmp_path_factory.mktemp("wbglue")
    (root / "workbench").mkdir()
    shim = _GLUE_SHIM.replace("__TREE__", json.dumps(_window_tree()))
    sandbox = _make_sandbox(root / "workbench", WORKBENCH_JS, shim, {})
    for rel in _UP:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JS / rel, root / rel)
    for rel, src in _GLUE_STUBS.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(src, encoding="utf-8")
    return sandbox


_GLUE_PREAMBLE = (
    "import { document, modal, server, fire, settle, $ } from './shim.js';\n"
    "const wb = await import('./workbench.js');\n"
    "const words = (t) => t.schedule === 'daily' ? 'Daily at 02:00' : '';\n"
    "const nodeOf = (id) => $('workbench-room').querySelectorAll('.wb-node').find((n) => n.dataset.taskId === id);\n"
    "const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };\n"
)


def test_the_window_markup_has_what_the_glue_reaches_for():
    tree = _window_tree()

    def walk(n):
        yield n
        for k in n[2]:
            yield from walk(k)
    ids = {n[1].get("id"): n for n in walk(tree) if n[1].get("id")}
    assert {"workbench-modal", "workbench-close", "workbench-rooms", "workbench-room"} <= set(ids)
    assert "modal hidden" == tree[1]["class"]
    content = tree[2][0]
    assert "modal-content" in content[1]["class"].split() and content[1]["role"] == "dialog"
    assert "aria-modal" not in content[1], "tool windows do not trap the reader (`B949`)"
    assert ids["workbench-close"][1]["class"] == "close-btn", "Escape's arbiter presses `.close-btn`"
    assert ids["workbench-rooms"][1]["role"] == "tablist"


def test_opening_draws_the_rooms_wires_the_window_once_and_focuses_the_workflow(glue):
    o = _run(glue, _GLUE_PREAMBLE, """
        wb.openWorkbench({ focusId: 'b', describeTrigger: words });
        await settle(5);
        const tabs = $('workbench-rooms').children.map((t) => ({ text: t.textContent, role: t.getAttribute('role'),
          selected: t.getAttribute('aria-selected'), controls: t.getAttribute('aria-controls'), id: t.id }));
        const first = { hidden: modal._classes().includes('hidden'), tabs, drag: globalThis.__drag.slice(),
          room: $('workbench-room')._classes().includes('wb-room'),
          labelled: $('workbench-room').getAttribute('aria-labelledby'),
          focusedB: !!nodeOf('b').focused, sub: nodeOf('a').querySelector('.wb-node-sub').textContent,
          open: wb.isWorkbenchOpen() };
        const reads = server.calls.filter((c) => c.url.startsWith('/api/tasks')).length;
        wb.openWorkbench({ focusId: 'a' });
        await settle(5);
        out({ first, again: { focusedA: !!nodeOf('a').focused, drag: globalThis.__drag.length,
          reads: server.calls.filter((c) => c.url.startsWith('/api/tasks')).length - reads } });
    """)
    f = o["first"]
    assert f["hidden"] is False and f["open"] is True
    assert f["tabs"] == [{"text": "Automations", "role": "tab", "selected": "true",
                          "controls": "workbench-room", "id": "workbench-room-tab-automations"}]
    assert f["labelled"] == "workbench-room-tab-automations"
    assert f["drag"] == [{"id": "workbench-modal", "content": True, "header": True, "dock": True, "left": True}]
    assert f["room"] is True
    assert f["focusedB"] is True
    assert f["sub"] == "Action · Daily at 02:00", "the opener's schedule words reach the step"
    # A second door press while open moves to that workflow — it does not wire
    # the window twice or mount a second canvas.
    assert o["again"] == {"focusedA": True, "drag": 1, "reads": 0}


def test_selecting_a_step_mounts_the_task_form_through_the_contract(glue):
    o = _run(glue, _GLUE_PREAMBLE, """
        wb.openWorkbench({});
        await settle(5);
        fire(nodeOf('a'), 'click');
        const rec = globalThis.__fields[0];
        out({ n: globalThis.__fields.length, task: rec && rec.args.task.id,
              tasks: rec && rec.args.tasks.map((t) => t.id), host: rec && rec.host.className,
              fns: rec && [typeof rec.args.onSaved, typeof rec.args.onCancel] });
    """)
    assert o == {"n": 1, "task": "a", "tasks": ["a", "b"], "host": "wb-panel-host",
                 "fns": ["function", "function"]}


def test_a_steps_full_plan_is_drawn_by_the_tasks_cards_renderer(glue):
    """`P22-04`: the glue hands `tasks.js:renderRunSteps` to the canvas, so the
    Workbench draws a plan with the renderer the Tasks card draws one with
    (`Law 7`) — exported, not copied."""
    o = _run(glue, _GLUE_PREAMBLE, """
        wb.openWorkbench({});
        await settle(5);
        fire(nodeOf('a'), 'click');
        fire($('workbench-room').querySelector('.wb-panel-dry'), 'click');
        await settle(5);
        fire(nodeOf('b').querySelector('.wb-node-plan-btn'), 'click');
        const box = $('workbench-room').querySelector('.wb-plan-box');
        out({ posts: server.calls.filter((c) => c.method === 'POST').map((c) => c.url),
              rendered: globalThis.__rendered.map((r) => ({ steps: r.run.steps.map((s) => s.detail), opts: r.opts })),
              html: box && box.querySelector('.wb-plan-steps').innerHTML });
    """)
    assert o["posts"] == ["/api/tasks/a/run?dry=true&chain=true"]
    assert o["rendered"] == [{"steps": ["Would send this task’s prompt to a model, with tools."],
                              "opts": {"open": True, "summary": "What a real run would do"}}]
    assert o["html"] == '<ol class="task-run-step-list"><li>rendered by tasks.js</li></ol>'


def test_closing_takes_the_room_down_and_the_close_button_is_wired(glue):
    o = _run(glue, _GLUE_PREAMBLE, """
        wb.openWorkbench({});
        await settle(5);
        fire(nodeOf('a'), 'click');
        fire($('workbench-close'), 'click');
        const closing = modal.querySelector('.modal-content')._classes().includes('modal-closing');
        await settle(300);
        out({ closing, hidden: modal._classes().includes('hidden'), open: wb.isWorkbenchOpen(),
              emptied: $('workbench-room').childNodes.length === 0,
              formDestroyed: globalThis.__fields[0].destroyed });
    """)
    assert o == {"closing": True, "hidden": True, "open": False, "emptied": True, "formDestroyed": True}


def test_a_minimised_workbench_is_restored_rather_than_rebuilt(glue):
    o = _run(glue, _GLUE_PREAMBLE, """
        wb.openWorkbench({});
        await settle(5);
        modal.classList.add('hidden');
        globalThis.__minimized = true;
        const reads = server.calls.length;
        wb.openWorkbench({ focusId: 'b' });
        await settle(5);
        out({ restored: globalThis.__restored, hidden: modal._classes().includes('hidden'),
              refetched: server.calls.length - reads, focusedB: !!nodeOf('b').focused });
    """)
    assert o == {"restored": ["workbench-modal"], "hidden": False, "refetched": 0, "focusedB": True}


# ── 4. ⋮ → Workflow, and Read as a diagram ──────────────────────────────────

_TASKS_STUBS_WB = dict(_TASKS_STUBS)
_TASKS_STUBS_WB["markdown.js"] = """
const api = { processWithThinking: (s) => String(s == null ? '' : s),
  squashOutsideCode: (s) => String(s == null ? '' : s),
  renderMermaid() { return Promise.resolve(); } };
export default api;
"""
_TASKS_STUBS_WB["workbench/workbench.js"] = (
    "globalThis.__opened = [];\n"
    "export function openWorkbench(o) { globalThis.__opened.push({ focusId: o.focusId,\n"
    "  words: typeof o.describeTrigger === 'function' ? o.describeTrigger({ trigger_type: 'webhook' }) : null }); return true; }\n"
)
_EXPORT = "\nexport const __k = { _fetchTasks, _renderList };\n"


@pytest.fixture(scope="module")
def tasks_box(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("wbkebab"), TASKS_JS, _TASKS_SHIM, _TASKS_STUBS_WB)
    copy = box / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + _EXPORT, encoding="utf-8")
    return box


_SERVED = {
    "tasks": [{"id": "a", "name": "Nightly backup", "task_type": "llm", "status": "active",
               "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "02:00",
               "then_task_id": "b", "else_task_id": None, "run_count": 0},
              {"id": "b", "name": "Message me", "task_type": "llm", "status": "active",
               "trigger_type": "webhook", "then_task_id": None, "else_task_id": None, "run_count": 0}],
    "graph": {"nodes": [{"id": "a", "name": "Nightly backup"}, {"id": "b", "name": "Message me"}],
              "edges": [{"from": "a", "to": "b", "when": "success", "dangling": False}],
              "conditions": ["success", "error"], "max_depth": 10},
}

_KEBAB = """
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
const kebab = (id) => list.querySelectorAll('.task-card').find((c) => c.dataset.id === id)
  .querySelector('.memory-item-btn');
const menu = () => document.querySelectorAll('.task-dropdown').slice(-1)[0];
const item = (label) => menu().children.find((b) => b.textContent === label);
""" % json.dumps(_SERVED)


def test_the_kebab_offers_the_workbench_and_keeps_the_diagram(tasks_box):
    o = _run(tasks_box, _KEBAB, """
        kebab('a').dispatchEvent({ type: 'click', ...ev });
        const labels = menu().children.map((b) => b.textContent);
        item('Workflow').dispatchEvent({ type: 'click', ...ev });
        await tick();
        const opened = globalThis.__opened.slice();
        kebab('a').dispatchEvent({ type: 'click', ...ev });
        item('Read as a diagram').dispatchEvent({ type: 'click', ...ev });
        await tick();
        console.log(JSON.stringify({ labels, opened, diagram: body.innerHTML }));
    """)
    i = o["labels"].index("Workflow")
    assert o["labels"][i - 1] == "History" and o["labels"][i + 1] == "Read as a diagram"
    # The Workbench, on that task, with the Tasks window's own schedule words.
    assert o["opened"] == [{"focusId": "a", "words": "Webhook"}]
    assert '<div class="mermaid-container"><pre class="mermaid"' in o["diagram"]
    assert "Nightly backup" in o["diagram"]
