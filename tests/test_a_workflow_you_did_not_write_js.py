# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-34` — a workflow, drawn, for somebody who did not write it.

**What was on the tree before this, measured 2026-09-19 at `HEAD`.**
`GET /api/tasks` has answered `{"tasks": [...], "graph": {...}}` since `P8-26`;
`build_task_graph` (`src/task_scheduler.py:145`) puts `nodes`, `edges` with a
`when` on each, the `conditions` vocabulary and `max_depth` on the wire, and
`_task_to_dict` (`routes/task/task_routes.py`) puts `then_task_id`,
`else_task_id` and a per-task `edges` list on every row. **Nothing in
`static/` read any of it.** `_fetchTasks` (`static/js/tasks.js:58`) did
`_tasks = data.tasks || []` and dropped the graph; `grep -rn "else_task_id"
static/` returned **nothing at all**, and `then_task_id` appeared in exactly
two places, both inside the edit form (`tasks.js:1853` populating a dropdown
and `:1923` posting it back). So `P8-28`'s branch could be stored and never
seen, and the only way to find out that finishing one task starts another was
to open Edit on the task and read a `<select>`.

**`Law 14` — the renderer already exists and this is not a second one.**
`markdown.js:renderMermaid` (`:1035`) loads the vendored bundle on first use
(`ensureMermaid`, `:90`), finds `pre.mermaid:not([data-processed])` inside a
container and calls `mermaid.run({ nodes })`. `chatRenderer.js:3939`,
`document.js:9831` and `slashCommands.js:476` already call it. `tasks.js` is
the fourth caller. It emits the same `<div class="mermaid-container"><pre
class="mermaid">` markup `markdown.js:690` emits for a fence in a message, and
it does not load, initialise or configure Mermaid.

**How this is tested, and why in three parts.**

  1. `static/js/tasks/workflowDiagram.js` is pure — no DOM, no fetch, no module
     state — so it is imported and called directly under node with no sandbox
     and no stubs at all. That is the strongest form `Law 20` has.
  2. The Mermaid text those functions produce is then handed to **the real
     vendored `static/lib/mermaid.min.js`** through
     `tests/harness/mermaid_diagram_parse.js`, which now takes extra cases as
     an argument. A diagram this product generates and Mermaid cannot parse is
     a blank box in front of a person, and no assertion written in a test can
     tell you whether Mermaid accepts something — only Mermaid can.
  3. The surface half is driven through the shared `tasks.js` sandbox, so
     `_workflowView` really walks the served graph and `_showWorkflowDiagram`
     really writes the card.

**The harness had to be fixed to do (2), and what was wrong with it is worth
recording.** DOMPurify — which the bundle carries and which mermaid runs every
label through once the grammar has accepted it — returns an object with no
`sanitize` at all unless `document.nodeType === 9`. The harness's shim document
had no `nodeType`, so **every diagram with text in a node came back
`ao.sanitize is not a function`**. It passed its own cases only because all
three of them (`graph TD; A-->B;`, `A@{ shape: person }`, `erDiagram`) have no
node labels. One line of shim; `broken` is still rejected, so the harness has
not been loosened into accepting anything.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

DIAGRAM_JS = ROOT / "static" / "js" / "tasks" / "workflowDiagram.js"
TASKS_JS = ROOT / "static" / "js" / "tasks.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── (1) the pure module, called directly ────────────────────────────────────
def _diagram(tmp_path: Path, script: str) -> dict:
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "import * as wd from '%s';\n" % DIAGRAM_JS.as_posix() + textwrap.dedent(script),
        encoding="utf-8",
    )
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# The shape `build_task_graph` serves: two chained tasks plus a branch, an
# unrelated task that must not be drawn, and an edge to a task the caller
# cannot see (`dangling`, which the server keeps on purpose).
_GRAPH = {
    "nodes": [
        {"id": "a", "name": "Morning digest", "task_type": "llm", "status": "active"},
        {"id": "b", "name": "Post the summary", "task_type": "action",
         "action": "tidy_sessions", "status": "active"},
        {"id": "c", "name": "Tell me it broke", "task_type": "llm", "status": "paused"},
        {"id": "z", "name": "Unrelated", "task_type": "research", "status": "active"},
    ],
    "edges": [
        {"from": "a", "to": "b", "when": "success", "dangling": False},
        {"from": "a", "to": "c", "when": "error", "dangling": False},
        {"from": "b", "to": "gone", "when": "success", "dangling": True},
    ],
    "conditions": ["success", "error"],
    "max_depth": 10,
}

_VIEW = {
    "nodes": [
        {"id": "a", "title": "Morning digest", "kind": "llm",
         "trigger": "Daily at 09:00", "detail": "Prompt", "focus": True},
        {"id": "b", "title": "Post the summary", "kind": "action",
         "trigger": "", "detail": "Action · Clean up empty chat sessions"},
        {"id": "c", "title": "Tell me it broke", "kind": "llm",
         "trigger": "", "detail": "Prompt · paused"},
    ],
    "edges": _GRAPH["edges"][:2],
}


def test_the_component_walk_goes_both_ways_and_stops_at_the_workflow(tmp_path):
    """Opening the *last* step of a chain has to show what runs before it.

    A downstream-only walk would draw half a workflow from `b` and give no
    sign the other half exists. `z` is in the same payload and in no chain, so
    it must not appear from any of them.
    """
    out = _diagram(tmp_path, """
        const g = %s;
        console.log(JSON.stringify({
          fromStart: [...wd.componentOf(g, 'a').ids].sort(),
          fromMiddle: [...wd.componentOf(g, 'b').ids].sort(),
          fromBranch: [...wd.componentOf(g, 'c').ids].sort(),
          fromLoner: [...wd.componentOf(g, 'z').ids].sort(),
          missing: wd.componentOf(g, 'b').nodes.filter(n => n.missing).map(n => n.id),
        }));
    """ % json.dumps(_GRAPH))
    assert out["fromStart"] == ["a", "b", "c", "gone"]
    assert out["fromMiddle"] == ["a", "b", "c", "gone"]
    assert out["fromBranch"] == ["a", "b", "c", "gone"]
    assert out["fromLoner"] == ["z"]
    # The server keeps a dangling edge rather than dropping it, so the diagram
    # has to draw the far end as something, and say what it is.
    assert out["missing"] == ["gone"]


def test_the_two_branches_are_different_arrows_and_are_named_in_words(tmp_path):
    """`P8-28`'s conditions are stored as `success` and `error`. Those stay
    stored; on the arrow they are a sentence, because the person reading the
    diagram has not read `EDGE_CONDITIONS`."""
    out = _diagram(tmp_path, """
        console.log(JSON.stringify({ src: wd.workflowMermaid(%s) }));
    """ % json.dumps(_VIEW))
    src = out["src"]
    lines = [ln.strip() for ln in src.splitlines()]
    assert "flowchart TD" in lines
    assert any(ln.startswith("n0 -->") and '"if it works"' in ln for ln in lines), src
    assert any(ln.startswith("n0 -.->") and '"if it fails"' in ln for ln in lines), src
    assert "success" not in src and "error" not in src, src


def test_the_shape_says_what_kind_of_step_it_is_and_no_colour_is_emitted(tmp_path):
    """Sixteen palettes ship and four are light, so a `fill:#…` would be right
    in one of them. Every distinction is a shape or a word."""
    out = _diagram(tmp_path, """
        console.log(JSON.stringify({ src: wd.workflowMermaid(%s), words: wd.SHAPE_WORDS }));
    """ % json.dumps(_VIEW))
    src = out["src"]
    assert 'n0["Morning digest<br/>Daily at 09:00<br/>Prompt"]' in src, src
    assert 'n1{{"Post the summary' in src, src          # hexagon = action
    assert "paused" in src, src
    assert "#" not in src.replace("#quot;", "").replace("#35;", "")  \
        .replace("#lt;", "").replace("#gt;", "").replace("#amp;", ""), src
    assert "fill" not in src and "color" not in src, src
    assert len(out["words"]) == 3


def test_the_trigger_is_only_on_the_step_that_starts_the_workflow(tmp_path):
    """The second step is started by the arrow into it. Repeating its own
    schedule there would say something untrue about when it runs."""
    out = _diagram(tmp_path, """
        console.log(JSON.stringify({ src: wd.workflowMermaid(%s) }));
    """ % json.dumps(_VIEW))
    assert out["src"].count("Daily at 09:00") == 1, out["src"]


def test_a_task_name_cannot_add_a_node_to_the_diagram(tmp_path):
    """The `B866` question in Mermaid's grammar rather than HTML's.

    A task name is what a person typed. `A"] --> evil["own the graph` is a
    complete node declaration in Mermaid if it reaches the source unescaped.
    Measured as a differential against a benign name of the same length: same
    number of node lines, same number of edge lines.
    """
    hostile = 'A"] --> evil["own the graph'
    benign = "A" * len(hostile)

    def render(name):
        view = json.loads(json.dumps(_VIEW))
        view["nodes"][0]["title"] = name
        return view

    out = _diagram(tmp_path, """
        const a = wd.workflowMermaid(%s), b = wd.workflowMermaid(%s);
        const count = (s, re) => s.split('\\n').filter(l => re.test(l)).length;
        console.log(JSON.stringify({
          hostile: a, benign: b,
          hostileNodes: count(a, /^  n\\d+[[({]/), benignNodes: count(b, /^  n\\d+[[({]/),
          hostileEdges: count(a, /^  n\\d+ -/), benignEdges: count(b, /^  n\\d+ -/),
        }));
    """ % (json.dumps(render(hostile)), json.dumps(render(benign))))

    assert out["hostileNodes"] == out["benignNodes"] == 3, out["hostile"]
    assert out["hostileEdges"] == out["benignEdges"] == 2, out["hostile"]
    assert "evil" in out["hostile"], "the name must still be readable, just inert"
    assert '"] -->' not in out["hostile"], out["hostile"]


def test_the_escaper_is_for_mermaid_and_not_for_html(tmp_path):
    """`B866` had just finished merging this tree's HTML escapers into one, so
    the one thing this must not be is an eighteenth of those. Mermaid's escape
    is a `#`-introduced entity; `&quot;` is drawn literally by it."""
    out = _diagram(tmp_path, """
        console.log(JSON.stringify({ out: ['a"b', 'x<y>z', 'p&q', '#quot;', 'tab\\there']
          .map(wd.mermaidText) }));
    """)
    assert out["out"] == ['a#quot;b', 'x#lt;y#gt;z', 'p#amp;q', '#35;quot;', 'tab here']


def test_the_sentence_and_the_diagram_are_built_from_the_same_component(tmp_path):
    """`P8-00`. The boxes give the order; the sentence gives it in words for
    anyone the boxes did not reach."""
    out = _diagram(tmp_path, """
        console.log(JSON.stringify({
          chained: wd.workflowSentence(%s),
          alone: wd.workflowSentence({ nodes: [{ id: 'a', title: 'Nightly tidy',
                                                 trigger: 'Daily at 03:00' }], edges: [] }),
        }));
    """ % json.dumps(_VIEW))
    assert out["chained"] == (
        "Morning digest runs first — Daily at 09:00."
        " If it works, Post the summary runs next."
        " If it fails, Tell me it broke runs instead."
    ), out["chained"]
    assert out["alone"] == (
        "Nightly tidy runs on its own — Daily at 03:00."
        " Nothing follows it, and nothing leads to it."
    ), out["alone"]


def test_the_depth_cap_the_server_serves_can_be_reached(tmp_path):
    """`build_task_graph` serves `max_depth` and nothing had ever shown it, so
    a workflow one step from being refused looked like one that was not. A
    cycle — which the engine refuses and a hand-edited database can still hold
    — must terminate rather than hang the modal."""
    chain = {"nodes": [{"id": str(i)} for i in range(5)],
             "edges": [{"from": str(i), "to": str(i + 1), "when": "success"} for i in range(4)]}
    loop = {"nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b", "when": "success"},
                      {"from": "b", "to": "a", "when": "success"}]}
    out = _diagram(tmp_path, """
        console.log(JSON.stringify({
          chain: wd.longestChain(wd.componentOf(%s, '0')),
          loop: wd.longestChain(wd.componentOf(%s, 'a')),
          one: wd.longestChain(wd.componentOf({ nodes: [{ id: 'a' }], edges: [] }, 'a')),
        }));
    """ % (json.dumps(chain), json.dumps(loop)))
    assert out["chain"] == 5
    assert out["loop"] == 2
    assert out["one"] == 1


def test_the_theme_directive_follows_the_palette_the_app_already_computed(tmp_path):
    """`markdown.js:94` initialises Mermaid with `theme: 'dark'` written in, and
    four of the sixteen shipped palettes are light. `theme.js:292` already
    computes `_isLightBackground(colors.bg)` and writes `color-scheme` onto
    `<html>`, so this reads that answer instead of deriving a second one."""
    out = _diagram(tmp_path, """
        console.log(JSON.stringify({
          light: wd.themeDirective('light'),
          dark: wd.themeDirective('dark'),
          unset: wd.themeDirective(''),
          inSource: wd.workflowMermaid(Object.assign({ scheme: 'light' }, %s)).split('\\n')[0],
          noScheme: wd.workflowMermaid(%s).split('\\n')[0],
        }));
    """ % (json.dumps(_VIEW), json.dumps(_VIEW)))
    assert out["light"] == '%%{init: {"theme": "neutral"}}%%'
    assert out["dark"] == '%%{init: {"theme": "dark"}}%%'
    assert out["unset"] == '%%{init: {"theme": "dark"}}%%'
    assert out["inSource"] == out["light"]
    assert out["noScheme"] == "flowchart TD"


# ── (2) the real vendored Mermaid parses what this product emits ────────────
from test_vendored_bumps_still_render import run_harness  # noqa: E402


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    """Every diagram the pure module can produce, through the shipped bundle."""
    box = tmp_path_factory.mktemp("wfmermaid")
    entry = box / "gen.mjs"
    cases = {
        "wfPlain": _VIEW,
        "wfLight": dict(_VIEW, scheme="light"),
        "wfDark": dict(_VIEW, scheme="dark"),
        "wfHostile": json.loads(json.dumps(_VIEW)),
        "wfLone": {"nodes": [{"id": "a", "title": "Nightly tidy", "kind": "action",
                              "trigger": "Daily at 03:00", "detail": "Action · Tidy"}],
                   "edges": []},
        "wfUnseen": {"nodes": [{"id": "a", "title": "Step one", "kind": "llm"},
                               {"id": "g", "title": "Task g", "missing": True,
                                "detail": "not in your list of tasks"}],
                     "edges": [{"from": "a", "to": "g", "when": "success"}]},
    }
    cases["wfHostile"]["nodes"][0]["title"] = 'A"] --> evil["own the graph'
    entry.write_text(
        "import * as wd from '%s';\n" % DIAGRAM_JS.as_posix()
        + "import fs from 'node:fs';\n"
        + "const cases = %s;\n" % json.dumps(cases)
        + "const out = {};\n"
        + "for (const [k, v] of Object.entries(cases)) out[k] = wd.workflowMermaid(v);\n"
        + "fs.writeFileSync(process.argv[2], JSON.stringify(out));\n",
        encoding="utf-8",
    )
    extra = box / "extra.json"
    proc = subprocess.run(["node", str(entry), str(extra)], capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return run_harness("mermaid_diagram_parse.js", str(extra)), json.loads(extra.read_text())


def test_mermaid_itself_accepts_every_diagram_this_surface_can_draw(parsed):
    report, sources = parsed
    assert report["ok"], report
    for name in sources:
        got = report["parse"][name]
        assert got["ok"], (name, got, sources[name])
        assert got["diagramType"] == "flowchart-v2", (name, got)


def test_the_harness_still_rejects_something(parsed):
    """A shim change that made `parse` accept anything would make the case
    above worthless. The harness's own broken case is the control."""
    report, _ = parsed
    assert report["parse"]["broken"]["ok"] is False, report["parse"]["broken"]


# ── (3) the surface, driven through the shared `tasks.js` sandbox ───────────
from test_the_palette_moves_to_the_server_js import _SHIM, _STUBS  # noqa: E402

# The shared stubs plus the one call this row makes into `markdown.js`. A
# counter rather than a no-op: `Law 14` here means the diagram is handed to the
# renderer that already exists, and the only way to assert that is to watch the
# handoff happen.
_WF_STUBS = dict(_STUBS)
_WF_STUBS["markdown.js"] = """
const api = {
  processWithThinking: (s) => String(s == null ? '' : s),
  squashOutsideCode: (s) => String(s == null ? '' : s),
  __renderMermaidCalls: 0,
  renderMermaid(container) { api.__renderMermaidCalls += 1; api.__lastContainer = container; return Promise.resolve(); },
};
export default api;
"""
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

_WF_EXPORT = "\nexport const __w = { _workflowView, _showWorkflowDiagram, _fetchTasks };\n"


@pytest.fixture(scope="module")
def wf_sandbox(tmp_path_factory):
    box = _make_sandbox(tmp_path_factory.mktemp("wfsurface"), TASKS_JS, _SHIM, _WF_STUBS)
    copy = box / TASKS_JS.name
    copy.write_text(copy.read_text(encoding="utf-8") + _WF_EXPORT, encoding="utf-8")
    return box


_WF_PREAMBLE = (
    "import { document, Node, mockFetch, res, tick } from './shim.js';\n"
    "import markdown from './markdown.js';\n"
    "const { __w } = await import('./tasks.js');\n"
)

_SERVED = {
    "tasks": [
        {"id": "a", "name": "Morning digest", "task_type": "llm", "status": "active",
         "trigger_type": "schedule", "schedule": "daily", "scheduled_time": "09:00"},
        {"id": "b", "name": "Post the summary", "task_type": "action",
         "action": "tidy_sessions", "status": "paused", "trigger_type": "schedule",
         "schedule": "daily", "scheduled_time": "10:00"},
    ],
    "graph": {
        "nodes": [
            {"id": "a", "name": "Morning digest", "task_type": "llm", "status": "active"},
            {"id": "b", "name": "Post the summary", "task_type": "action",
             "action": "tidy_sessions", "status": "paused"},
        ],
        "edges": [{"from": "a", "to": "b", "when": "success", "dangling": False}],
        "conditions": ["success", "error"],
        "max_depth": 10,
    },
}


def test_the_graph_the_endpoint_serves_is_kept_and_walked(wf_sandbox):
    """`_fetchTasks` read `data.tasks` and dropped `data.graph` on the floor.
    The whole row is downstream of that one line."""
    out = _run(wf_sandbox, _WF_PREAMBLE, """
        mockFetch(async () => res(200, %s));
        await __w._fetchTasks();
        const view = __w._workflowView('b');
        console.log(JSON.stringify({
          ids: view.nodes.map(n => n.id),
          titles: view.nodes.map(n => n.title),
          focus: view.nodes.filter(n => n.focus).map(n => n.id),
          triggers: view.nodes.map(n => n.trigger),
          details: view.nodes.map(n => n.detail),
          edges: view.edges.length,
          maxDepth: view.maxDepth,
        }));
    """ % json.dumps(_SERVED))
    assert sorted(out["ids"]) == ["a", "b"]
    assert out["focus"] == ["b"]
    assert out["edges"] == 1
    assert out["maxDepth"] == 10
    # The trigger goes on the entry node only, and it is `_scheduleLabel`'s own
    # sentence rather than a second wording of `schedule: "daily"`.
    triggers = dict(zip(out["ids"], out["triggers"]))
    assert triggers["a"].startswith("Daily at "), triggers
    assert triggers["b"] == "", triggers
    details = dict(zip(out["ids"], out["details"]))
    assert details["a"] == "Prompt", details
    assert "paused" in details["b"], details


def test_the_card_is_written_and_handed_to_the_renderer_that_already_exists(wf_sandbox):
    """`Law 14`. The markup is `markdown.js`'s own (`div.mermaid-container` +
    `pre.mermaid`) and the render call is `markdownModule.renderMermaid`, the
    same pair a mermaid fence in a chat message goes through."""
    out = _run(wf_sandbox, _WF_PREAMBLE, """
        mockFetch(async () => res(200, %s));
        await __w._fetchTasks();
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const body = modal.appendChild(new Node('div'));
        body.className = 'modal-body';
        __w._showWorkflowDiagram('a', 'Morning digest');
        await tick();
        console.log(JSON.stringify({
          html: body.innerHTML,
          rendered: markdown.__renderMermaidCalls,
        }));
    """ % json.dumps(_SERVED))
    html = out["html"]
    assert '<div class="mermaid-container"><pre class="mermaid"' in html, html
    assert "flowchart TD" in html, html
    assert "Morning digest" in html and "Post the summary" in html, html
    # The sentence, the legend and the word for the dotted arrow.
    assert "runs first" in html, html
    assert "runs next when a step works" in html, html
    assert out["rendered"] == 1, out["rendered"]


def test_a_lone_task_is_still_a_diagram_and_says_how_to_chain_one(wf_sandbox):
    """`P8-00` again: the empty state is where a person finds out the feature
    exists. An unchained task draws one box and a sentence naming the control
    that would add a second."""
    lone = {"tasks": [_SERVED["tasks"][0]],
            "graph": {"nodes": [_SERVED["graph"]["nodes"][0]], "edges": [],
                      "conditions": ["success", "error"], "max_depth": 10}}
    out = _run(wf_sandbox, _WF_PREAMBLE, """
        mockFetch(async () => res(200, %s));
        await __w._fetchTasks();
        const modal = document.body.appendChild(new Node('div'));
        modal.setAttribute('id', 'tasks-modal');
        const body = modal.appendChild(new Node('div'));
        body.className = 'modal-body';
        __w._showWorkflowDiagram('a', 'Morning digest');
        await tick();
        console.log(JSON.stringify({ html: body.innerHTML }));
    """ % json.dumps(lone))
    assert "Nothing is chained to this task yet" in out["html"], out["html"]
    assert "runs on its own" in out["html"], out["html"]
