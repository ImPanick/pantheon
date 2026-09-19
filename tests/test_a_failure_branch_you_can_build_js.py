# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B873` — "if this step fails, do that", from the browser.

**What was on the tree before this, measured 2026-09-19 at `HEAD`.**
`grep -rn "else_task_id" static/` returned **nothing at all**. The whole of the
browser's knowledge of chaining was two lines in the edit form:
`tasks.js:1853` filled one `<select>` from `existing.then_task_id` and
`tasks.js:1923` posted `payload.then_task_id` back. Everything under them
already worked:

  * `src/task_scheduler.py:112` — `EDGE_COLUMNS = {success: "then_task_id",
    error: "else_task_id"}`, and `task_edges()` projects both;
  * `routes/task/task_routes.py:175,219` — `else_task_id` is on `TaskCreate`
    **and** `TaskUpdate`, and `:711` / `:929` run it through
    `_validate_then_task_id`, the same validator as the success edge, so the
    two branches cannot end up under different rules;
  * `:270` — `_task_to_dict` puts it on every row it serves;
  * `P8-34` — the diagram **draws** it, as the dotted arrow.

So the failure branch could be stored, validated, served and drawn, and the
only two things that could create one were the API and the agent. That is
`B582`'s shape: a complete backend with no caller, found the moment something
rendered it.

**Re-measured before designing the control** (this row asked for that
explicitly). `PUT /api/tasks/{id}` guards each field with `if req.X is not
None`, so `""` clears an edge and an omitted key leaves it alone — which is why
the form sends both fields every time rather than only the ones that are set. A
self-chain is refused 400 and an unknown target 404, for `else_task_id`
identically to `then_task_id`. Nothing on the write path needed changing, and
nothing on it was changed.

**How this is tested.** The form is driven through the shared `tasks.js`
sandbox — `_showForm` really writes the form, the real populate loop really
fills both `<select>`s, and the real save handler really assembles the payload
and calls `fetch`. The payload that comes off that wire is then handed to the
**server's own** `build_task_graph`, and the graph *that* produces is served
back to `_fetchTasks` and drawn. So the loop this row's `P8-00` clause
describes — a person adds a failure branch on the card and sees the diagram
draw the edge they just made — is closed by the code on both sides of it, with
no fixture standing in for either (`Law 20`).
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

TASKS_JS = ROOT / "static" / "js" / "tasks.js"
DIAGRAM_JS = ROOT / "static" / "js" / "tasks" / "workflowDiagram.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

from src.task_scheduler import EDGE_COLUMNS, build_task_graph  # noqa: E402
from test_the_palette_moves_to_the_server_js import _SHIM, _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

# The one call `tasks.js` makes into `markdown.js`, counted rather than
# no-opped: `Law 14` here means the diagram is handed to the renderer that
# already exists, and watching the handoff is the only way to assert it.
_WF_STUBS = dict(_STUBS)
_WF_STUBS["markdown.js"] = """
const api = {
  processWithThinking: (s) => String(s == null ? '' : s),
  squashOutsideCode: (s) => String(s == null ? '' : s),
  __renderMermaidCalls: 0,
  renderMermaid(container) { api.__renderMermaidCalls += 1; return Promise.resolve(); },
};
export default api;
"""

_EXPORT = (
    "\nexport const __b = { _showForm, _fetchTasks, _showWorkflowDiagram,"
    " _edgeWhenLabel, CHAIN_FIELDS };\n"
)


def _form_ids() -> list:
    """Every `id="task-form-…"` the shipped form writes.

    The DOM shim stores `innerHTML` without parsing it, so the ids the real
    module reaches for have to exist as standalone nodes — the same reason
    `seedForm` exists. Read out of the module rather than listed here, so a
    field added to the form does not silently stop being seeded.
    """
    ids = sorted(set(re.findall(r'id="(task-form-[A-Za-z0-9_-]+)"',
                                TASKS_JS.read_text(encoding="utf-8"))))
    assert "task-form-chain" in ids and "task-form-save" in ids, ids
    return ids


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("branch"), TASKS_JS, _SHIM, _WF_STUBS)
    copy = box / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + _EXPORT, encoding="utf-8")
    return box


_PREAMBLE = (
    "import { document, calls, mockFetch, res, tick, seedForm, byId, fire, Node }"
    " from './shim.js';\n"
    "const { __b } = await import('./tasks.js');\n"
)

_TASKS = [
    {"id": "a", "name": "Morning digest", "task_type": "llm", "status": "active",
     "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "09:00",
     "prompt": "summarise the inbox"},
    {"id": "b", "name": "Post the summary", "task_type": "llm", "status": "active",
     "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "10:00"},
    {"id": "c", "name": "Tell me it broke", "task_type": "llm", "status": "active",
     "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "11:00"},
]


def _served(rows, graph=None):
    return {"tasks": rows,
            "graph": graph or {"nodes": [], "edges": [], "conditions": ["success", "error"],
                               "max_depth": 10}}


def _open_form(existing: dict, body: str) -> str:
    """The sandbox preamble that gets the edit form onto the page."""
    return """
        mockFetch(async () => res(200, %s));
        await __b._fetchTasks();
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const mbody = modal.appendChild(new Node('div'));
        mbody.className = 'modal-body';
        seedForm(%s);
        byId('task-form-prompt').value = 'summarise the inbox';
        __b._showForm(%s);
        await tick();
    """ % (json.dumps(_served(_TASKS)), json.dumps(_form_ids()), json.dumps(existing)) + body


def test_the_form_offers_both_branches_and_fills_each_from_its_own_column(sandbox):
    """`tasks.js:1853` filled one dropdown. A task stored with both edges could
    only ever show one of them, so opening Edit on a task with a failure branch
    showed a form that, if saved, would have been a lie about it."""
    out = _run(sandbox, _PREAMBLE, _open_form(
        {"id": "a", "name": "Morning digest", "task_type": "llm",
         "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "09:00",
         "prompt": "summarise the inbox", "then_task_id": "b", "else_task_id": "c"},
        """
        const read = (id) => byId(id).childNodes.map(
          (o) => ({ value: o.value, selected: o.selected === true, text: o.textContent }));
        console.log(JSON.stringify({
          then: read('task-form-chain'),
          otherwise: read('task-form-chain-else'),
          labels: [__b._edgeWhenLabel('success'), __b._edgeWhenLabel('error')],
          fields: __b.CHAIN_FIELDS,
        }));
        """))
    # Both dropdowns offer every other task, and neither offers the task itself
    # (the API refuses a self-chain 400; offering it would be a form that can
    # only produce an error).
    for key in ("then", "otherwise"):
        assert [o["value"] for o in out[key]] == ["b", "c"], (key, out[key])
    assert [o["value"] for o in out["then"] if o["selected"]] == ["b"], out["then"]
    assert [o["value"] for o in out["otherwise"] if o["selected"]] == ["c"], out["otherwise"]
    # The pairing the form works from is the server's own table.
    assert {when: field for _, field, when in out["fields"]} == EDGE_COLUMNS, out["fields"]


def test_the_two_controls_are_named_in_the_diagram_s_own_words(sandbox):
    """`Law 14`. `workflowDiagram.js:EDGE_WORDS` already maps the wire's
    `success`/`error` onto what a person reads, and `P8-34` draws those words
    on the arrows. The form says the same two things, so the control that makes
    an edge and the arrow it draws are one vocabulary rather than two."""
    words = json.loads(_run_node_words())
    out = _run(sandbox, _PREAMBLE, _open_form(
        {"id": "a", "task_type": "llm", "trigger_type": "schedule",
         "schedule": "daily", "scheduled_time": "09:00", "prompt": "x"},
        """
        console.log(JSON.stringify({
          success: __b._edgeWhenLabel('success'),
          error: __b._edgeWhenLabel('error'),
          html: byId('tasks-modal').querySelector('.modal-body').innerHTML,
        }));
        """))
    assert out["success"].lower() == words["success"], (out["success"], words)
    assert out["error"].lower() == words["error"], (out["error"], words)
    # Capitalised for a label and printed in the markup, next to its select.
    assert out["success"] == "If it works" and out["error"] == "If it fails", out
    assert f'>{out["success"]}<' in out["html"], out["html"]
    assert f'>{out["error"]}<' in out["html"], out["html"]
    assert 'id="task-form-chain-else"' in out["html"], out["html"]


def _run_node_words() -> str:
    """`EDGE_WORDS` out of the pure module, called rather than parsed."""
    import subprocess
    import tempfile
    entry = Path(tempfile.mkdtemp()) / "words.mjs"
    entry.write_text(
        "import { EDGE_WORDS } from '%s';\n" % DIAGRAM_JS.as_posix()
        + "console.log(JSON.stringify(EDGE_WORDS));\n", encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip().splitlines()[-1]


def _save_with(sandbox, then_value: str, else_value: str) -> dict:
    """Drive the real save handler and return the request body it sent."""
    out = _run(sandbox, _PREAMBLE, _open_form(
        {"id": "a", "name": "Morning digest", "task_type": "llm",
         "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "09:00",
         "prompt": "summarise the inbox", "then_task_id": "b", "else_task_id": "c"},
        """
        byId('task-form-chain').value = %s;
        byId('task-form-chain-else').value = %s;
        fire(byId('task-form-save'), 'click');
        await tick();
        const writes = calls.fetch.filter((c) => c.method === 'PUT' || c.method === 'POST');
        console.log(JSON.stringify({ writes }));
        """ % (json.dumps(then_value), json.dumps(else_value))))
    writes = [w for w in out["writes"] if w["url"].endswith("/api/tasks/a")]
    assert len(writes) == 1, out["writes"]
    return writes[0]["body"]


def test_saving_puts_the_failure_branch_on_the_wire(sandbox):
    """The line this row is about. `tasks.js:1923` was
    `payload.then_task_id = chainVal || ''` and there was no second line."""
    body = _save_with(sandbox, "b", "c")
    assert body["then_task_id"] == "b", body
    assert body["else_task_id"] == "c", body


def test_clearing_a_branch_sends_the_empty_string_that_clears_it(sandbox):
    """`PUT /api/tasks/{id}` guards with `if req.else_task_id is not None`
    (`task_routes.py:928`), so an omitted key leaves the stored edge in place
    and `""` is the only thing that removes it. A person who sets a failure
    branch and changes their mind has to be able to take it off."""
    body = _save_with(sandbox, "", "")
    assert body["then_task_id"] == "", body
    assert body["else_task_id"] == "", body
    assert "else_task_id" in body, body


def test_the_branch_a_person_just_made_is_the_branch_the_diagram_draws(sandbox):
    """The `P8-00` loop, closed end to end.

    The payload the form really sent is fed to the **server's own**
    `build_task_graph`, and the graph that produces is served back to
    `_fetchTasks` and drawn. Nothing between the two halves is hand-written, so
    a front end that sent the right field into the wrong column, or a diagram
    that drew the failure edge like a success edge, fails here rather than
    passing on a fixture that agrees with itself.
    """
    body = _save_with(sandbox, "", "c")
    assert body["else_task_id"] == "c" and body["then_task_id"] == ""

    rows = [SimpleNamespace(id=t["id"], name=t["name"], task_type=t["task_type"],
                            action=None, status=t["status"],
                            then_task_id=None, else_task_id=None) for t in _TASKS]
    saved = next(r for r in rows if r.id == "a")
    for when, column in EDGE_COLUMNS.items():
        setattr(saved, column, body[column] or None)
    graph = build_task_graph(rows)
    assert graph["edges"] == [{"from": "a", "to": "c", "when": "error", "dangling": False}], graph

    out = _run(sandbox, _PREAMBLE, """
        mockFetch(async () => res(200, %s));
        await __b._fetchTasks();
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const mbody = modal.appendChild(new Node('div'));
        mbody.className = 'modal-body';
        __b._showWorkflowDiagram('a', 'Morning digest');
        await tick();
        console.log(JSON.stringify({ html: mbody.innerHTML }));
    """ % json.dumps(_served(_TASKS, graph)))
    html = out["html"]
    # The `<pre>` holds escaped diagram source, so the dotted arrow is spelt
    # `-.-&gt;` here and a solid one would be `--&gt;`.
    assert "-.-&gt;" in html, html
    assert "--&gt;" not in html.replace("-.-&gt;", ""), html
    assert "Tell me it broke" in html, html
    assert "if it fails" in html, html
    # And the sentence above the boxes says the same thing in words.
    assert "If it fails, Tell me it broke runs instead." in html, html


def test_a_chain_with_no_failure_branch_says_so_and_names_the_control(sandbox):
    """`P8-00`. A chain that only says what happens when a step works looks
    finished; the branch worth having is the one that fires when it breaks. The
    note appears exactly where a person is looking at the arrow that is missing
    — and it goes away once the branch exists, or it is noise."""
    rows = [SimpleNamespace(id=t["id"], name=t["name"], task_type=t["task_type"],
                            action=None, status=t["status"],
                            then_task_id=None, else_task_id=None) for t in _TASKS]
    rows[0].then_task_id = "b"
    success_only = build_task_graph(rows)
    rows[0].else_task_id = "c"
    both = build_task_graph(rows)

    def render(graph):
        return _run(sandbox, _PREAMBLE, """
            mockFetch(async () => res(200, %s));
            await __b._fetchTasks();
            const modal = document.body.appendChild(new Node('div'));
            modal.setAttribute('id', 'tasks-modal');
            const mbody = modal.appendChild(new Node('div'));
            mbody.className = 'modal-body';
            __b._showWorkflowDiagram('a', 'Morning digest');
            await tick();
            console.log(JSON.stringify({ html: mbody.innerHTML }));
        """ % json.dumps(_served(_TASKS, graph)))["html"]

    missing = render(success_only)
    assert "Nothing runs if this step fails" in missing, missing
    assert "If it fails" in missing, missing
    assert "under Chain" in missing, missing
    assert "Nothing runs if this step fails" not in render(both)


def test_the_lone_task_empty_state_names_both_branches(sandbox):
    """The other end of `P8-00`: an unchained task is where a person finds out
    chaining exists at all, and the sentence used to name a control ("Then
    run") that has never been a label in this form."""
    html = _run(sandbox, _PREAMBLE, """
        mockFetch(async () => res(200, %s));
        await __b._fetchTasks();
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const mbody = modal.appendChild(new Node('div'));
        mbody.className = 'modal-body';
        __b._showWorkflowDiagram('a', 'Morning digest');
        await tick();
        console.log(JSON.stringify({ html: mbody.innerHTML }));
    """ % json.dumps(_served([_TASKS[0]])))["html"]
    assert "Nothing is chained to this task yet" in html, html
    # The two controls it names are the two the form really draws — asserted
    # against the rendered form in
    # `test_the_two_controls_are_named_in_the_diagram_s_own_words`, so the
    # sentence and the labels cannot drift apart the way "Then run" did.
    assert "If it works" in html and "If it fails" in html, html
    assert "under Chain" in html, html
