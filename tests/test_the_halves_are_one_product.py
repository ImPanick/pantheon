# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wave D's four halves, driven across their seams (`integrate-d`).

`wf-rules` (the document rule, references, slots, logic), `wf-effects` (the
executors, the palette), `wf-walker` (the walker, the routes) and `wf-canvas`
(the panels) were each built against the others' contracts with stand-ins
where the other half was missing (`P22-WAVE-D.md`). The stand-ins are gone;
each case here drives the REAL code on both sides of one seam the merge had
to reconcile, and says which (`Law 20`: nothing here reads a file to decide).

  * the palette route answers the walker's limits (it raised `AttributeError`:
    `WORKFLOW_PARALLEL_STEPS` was read where it did not live);
  * the For-each / Wait defaults have one home and the save, the run and the
    settings read it;
  * a start that fans out is read one way by the walker, the fields route and
    the dry run;
  * which workflows wait for the model slot is the rule's `node_needs_model`;
  * a non-admin's workflow holding an admin-only step — a For-each's
    `ssh_command`, an HTTP step, an MCP step — is paused before anything runs,
    and the save door asks the For-each's step too;
  * *Test this step* on an HTTP step shows the document's own plan;
  * an AI step in a real run is offered only its tools and answers in its
    shape (the walker → `_run_agent_loop` → `stream_agent_loop` seam);
  * the palette says the words the boxes say;
  * every step form writes a config the rule accepts and `render_call` renders;
  * every field a panel offers a picker on is one the renderer fills.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger  # noqa: E402
from src.tool_approvals import tool_approval_store  # noqa: E402
from tests.helpers.walker_harness import (  # noqa: E402
    app_for, arrow, client_for, make_db, node, records_of, recording_scheduler, row, runs_of,
    seed_workflow,
)

ENDPOINT = dict(model="scripted", endpoint_url="http://127.0.0.1:9/v1")
SEND = "mcp__chat__send_message"


def _webhook(body):
    return build_trigger(TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": body},
                         fields=WEBHOOK_PAYLOAD_FIELDS)


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "halves.db")


# ── the palette route and the walker's limits ─────────────────────────────────

@pytest.mark.asyncio
async def test_the_palette_route_answers_with_the_walkers_limits(factory, monkeypatch):
    """Red on the merge: `workflow_effects._limits` read
    `workflow_runs.WORKFLOW_PARALLEL_STEPS`, which lived in `task_scheduler` —
    every palette (and every document check) raised `AttributeError`."""
    import src.task_scheduler as ts
    from src import workflow_runs as wr
    app = app_for(factory, recording_scheduler(), monkeypatch)
    async with client_for(app) as client:
        res = await client.get("/api/workflows/palette", headers={"x-test-user": "alice"})
    assert res.status_code == 200, res.text
    limits = res.json()["limits"]
    assert limits == {"foreach_max_items": wr.foreach_max_items("alice"),
                      "wait_max_hours": wr.wait_max_hours(),
                      "parallel_steps": ts.WORKFLOW_PARALLEL_STEPS}
    assert len(res.json()["kinds"]) == 14


def test_the_two_limits_and_the_waiting_words_have_one_home(monkeypatch):
    """The For-each cap and the longest Wait are the walker's (`workflow_runs`):
    the settings' defaults, the rule's `WorkflowResources` and the palette read
    them; a setting moves all three. The waiting kinds are the record's, and
    `TaskWaiting` takes exactly those."""
    import src.settings as S
    from src import builtin_actions as ba
    from src import workflow_document as wd
    from src import workflow_effects as we
    from src import workflow_runs as wr

    assert S.DEFAULT_SETTINGS["workflow_foreach_max_items"] == wr.FOREACH_MAX_ITEMS_DEFAULT
    assert S.DEFAULT_SETTINGS["workflow_wait_max_hours"] == wr.WAIT_MAX_HOURS_DEFAULT
    assert wd.WorkflowResources().foreach_max_items == wr.FOREACH_MAX_ITEMS_DEFAULT
    assert wd.WorkflowResources().wait_max_hours == wr.WAIT_MAX_HOURS_DEFAULT
    # One setting, read through the resolver, reaches the save's check and
    # the palette alike.
    values = {"workflow_foreach_max_items": 7, "workflow_wait_max_hours": 3}
    real, real_explicit = S.get_setting, S.setting_is_explicit
    monkeypatch.setattr(S, "get_setting", lambda key, default=None: values.get(key, real(key, default)))
    monkeypatch.setattr(S, "setting_is_explicit", lambda key: key in values or real_explicit(key))
    res = we.workflow_resources(None)
    assert (res.foreach_max_items, res.wait_max_hours) == (7, 3)
    graph = wd.parse_graph({"v": 1, "nodes": [node("w", "Long", "wait", mode="for", minutes=4 * 60)],
                            "edges": []})
    refusal = wd.validate_document(graph, owner=None, tasks_by_id={}, crew_ids=set(),
                                   owner_is_admin=True, own_task_id=None, resources=res)
    assert refusal is not None and refusal.field == "minutes" and "3 hours" in refusal.sentence
    for kind in wr.WAITING_KINDS:
        assert ba.TaskWaiting("x", kind=kind).kind == kind
    with pytest.raises(ValueError):
        ba.TaskWaiting("x", kind="later")
    assert ba.WAIT_KINDS == wr.WAITING_KINDS


# ── a start that fans out ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_start_that_fans_out_is_read_one_way(factory):
    """The walker, the fields a step can pick and the dry run all ask
    `workflow_document.start_nodes` (three readings of it were merged)."""
    from core.database import ScheduledTask, Workflow
    from src import workflow_document as wd
    from src import workflow_effects as we
    from src import workflow_runs as wr
    nodes = [node("a", "Feed A", "action", action="tidy_sessions"),
             node("b", "Feed B", "action", action="tidy_documents"),
             node("m", "Merge", "merge", mode="all"),
             node("say", "Say it", "set", fields=[{"name": "said", "value": "{{ steps.start.data.body }}"}])]
    edges = [arrow("start", "a"), arrow("start", "b"), arrow("a", "m"), arrow("b", "m"),
             arrow("m", "say")]
    seed_workflow(factory, nodes, edges, trigger_type="webhook")
    s = recording_scheduler()
    await s._execute_task("wf", trigger=_webhook("deploy done"))
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    handed = {c["name"]: c["trigger"] for c in s.calls}
    assert handed["Morning digest · Feed A"]["data"]["body"] == "deploy done"
    assert handed["Morning digest · Feed B"]["data"]["body"] == "deploy done"
    said = {r["node_id"]: r for r in records_of(factory, run["id"])}["say"]
    assert said["output"]["data"] == {"said": "deploy done"}, "steps.start.data is the trigger's data"

    db = factory()
    try:
        wf = db.query(Workflow).first()
        trigger = db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first()
        graph = wd.parse_graph(wf.graph)
        assert wr.start_targets(graph) == [n["id"] for n in wd.start_nodes(graph)] == ["a", "b"]
        fields = we.available_fields(db, wf, trigger, graph, "say")
    finally:
        db.close()
    start_last_run = [src for src in fields["sources"]
                      if src["node_id"] == "start" and src["origin"] == "last_run"]
    assert start_last_run, fields
    assert "{{ steps.start.data.body }}" in [f["ref"] for f in start_last_run[0]["fields"]]
    planned = [(e["node"]["id"], e["depth"]) for e in wd.reachable_bfs(graph)]
    assert planned[:2] == [("a", 0), ("b", 0)], "the dry run starts where the run does"


# ── the model slot ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("nodes, wants", [
    ([node("h", "Fetch", "http", integration="int1", path="/v1"), node("i", "If", "if")], False),
    ([node("a", "Tidy", "action", action="tidy_sessions")], False),
    ([node("a", "Consolidate", "action", action="consolidate_memory")], True),
    ([node("f", "Each", "foreach", list="{{ steps.start.data.body }}",
           step={"kind": "llm", "label": "Sum", "config": {"prompt": "Sum {{ item }}"}})], True),
    ([node("f", "Each", "foreach", list="{{ steps.start.data.body }}",
           step={"kind": "action", "label": "Tidy", "config": {"action": "tidy_sessions"}})], False),
    ([node("r", "Run", "run_task", task_id="t2")], True),
])
def test_which_workflows_wait_for_the_model_slot(factory, nodes, wants):
    """`_workflow_needs_model_slot` and the walker's lock ask the rule's
    `node_needs_model` (they restated its action and For-each halves)."""
    from core.database import ScheduledTask
    seed_workflow(factory, nodes)
    s = recording_scheduler()
    db = factory()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first()
        assert s._workflow_needs_model_slot(db, task) is wants
    finally:
        db.close()
    assert any(s._node_needs_model(n) for n in nodes) is wants


# ── an admin's step, in a non-admin's workflow ───────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("step, named", [
    (node("each", "Each host", "foreach", list="{{ steps.start.data.body }}",
          step={"kind": "action", "label": "Run it", "config": {"action": "ssh_command",
                                                                "prompt": "uptime"}}),
     "ssh_command"),
    (node("fetch", "Fetch", "http", integration="int1", method="GET", path="/v1/entries"), "api_call"),
    (node("post", "Post", "mcp", tool=SEND, args={"channel": "#ops", "text": "hi"}), SEND),
])
async def test_a_non_admins_workflow_with_an_admin_step_is_paused_before_any_step_runs(factory, step, named):
    """`wf-rules`' B-NEW: `admin_only_action_of` read top-level Action steps
    only, so these ran into the rule at run and were recorded `error`; every
    other admin-only step pauses its task with a `skipped` run that says so."""
    seed_workflow(factory, [node("first", "First", "action", action="tidy_sessions"),
                            step], [arrow("first", step["id"])], owner="bob")
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "skipped", run
    assert run["error"] == f"Action '{named}' requires admin privileges"
    assert row(factory, "wf").status == "paused"
    assert s.calls == [], "nothing ran — not even the step before it"


def test_the_save_door_asks_the_step_a_for_each_repeats(factory, monkeypatch):
    """`workflow_store.check_document` asks the policy's own walk: a For-each
    of `ssh_command` is the same 403, in the same words, as an `ssh_command`
    step (it read top-level steps only)."""
    import src.task_action_policy as policy
    from src import workflow_store as store
    monkeypatch.setattr(policy, "owner_has_admin_task_privileges", lambda owner: owner == "root")
    graph = {"v": 1, "nodes": [node("each", "Each host", "foreach", list="{{ steps.start.data.body }}",
                                    step={"kind": "action", "label": "Run it",
                                          "config": {"action": "ssh_command", "prompt": "uptime"}})],
             "edges": []}
    db = factory()
    try:
        with pytest.raises(store.WorkflowRefused) as refused:
            store.check_document(db, graph, owner="bob", own_task_id=None)
    finally:
        db.close()
    assert refused.value.status == 403
    assert refused.value.sentence == "Action 'ssh_command' requires admin privileges"


# ── Test this step: the plan of an HTTP step ──────────────────────────────────

@pytest.mark.asyncio
async def test_testing_an_http_step_shows_the_documents_own_plan(factory, monkeypatch):
    """It said "Would send this task's prompt to a model, with tools." for an
    HTTP, MCP or Code step: the route asked `dry_run_plan(task_type=kind)`."""
    import src.integrations as integrations
    from src import workflow_document as wd
    from src import workflow_effects as we
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr(integrations, "load_integrations", lambda: [
        {"id": "int1", "name": "Miniflux", "enabled": True, "base_url": "http://miniflux.lan",
         "api_key": "k", "preset": "miniflux", "description": ""}])
    post = node("post", "Post it", "http", integration="int1", method="POST", path="/v1/entries",
                body=[{"name": "text", "value": "{{ steps.start.data.body }}"}], body_mode="json")
    seed_workflow(factory, [post], trigger_type="webhook", owner="root")
    app = app_for(factory, recording_scheduler(), monkeypatch)
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/nodes/post/test", headers={"x-test-user": "root"},
                                json={"node": post, "source": "none"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["outcome"] == "needs_confirmation"
    assert body["plan"] == wd.plan_lines(post, we.workflow_resources("root"))
    assert body["plan"][0] == "Would call Miniflux — POST /v1/entries"
    assert not any("prompt to a model" in line for line in body["plan"])


# ── an AI step in a real run: the walker → the agent loop ─────────────────────

@pytest.fixture()
def loop_world(monkeypatch, tmp_path):
    """The real walker and agent loop; only the model's words are scripted
    and a tool's far end records (as `test_a_step_that_needs_a_yes_waits_for_it`)."""
    import src.agent_loop as agent_loop
    import src.task_endpoint as task_endpoint
    import src.tool_execution as tool_execution
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "ai.db")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    tool_approval_store._pending.clear()
    script, seen, executed = [], [], []

    async def model(candidates, messages, **kwargs):
        seen.append([dict(m) for m in messages])
        said = script.pop(0) if script else "All done."
        yield f"data: {json.dumps({'delta': said})}\n\n"
        yield "data: [DONE]\n\n"

    async def far_end(block, **kwargs):
        executed.append((block.tool_type, block.content))
        return f"{block.tool_type}: ran", {"output": "ran", "exit_code": 0}

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", model)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(tool_execution, "_execute_tool_block_impl", far_end)
    monkeypatch.setattr(task_endpoint, "resolve_task_candidates", lambda **kw: [])
    s = TaskScheduler(None)
    s._log_to_assistant = lambda *a, **k: None
    return type("W", (), {"factory": factory, "script": script, "seen": seen,
                          "executed": executed, "s": s})


@pytest.mark.asyncio
async def test_an_ai_step_in_a_run_is_offered_only_its_tools_and_answers_in_its_shape(loop_world):
    """`P22-16`'s `Verify:` through the walker: the step's `tools` reach the
    loop as its `ToolPolicy` (the walker's slot → `_run_agent_loop` →
    `stream_agent_loop`), so the scripted model's `bash` is refused as "not
    one of this step's tools" and never reaches the far end; its answer is
    parsed into the fields asked for, which the next step reads."""
    w = loop_world
    seed_workflow(w.factory, [
        node("look", "Look it up", "llm", prompt="Find the release notes.", tools=["web_search"],
             answer_fields=[{"name": "title", "type": "text"}, {"name": "url", "type": "text"}],
             **ENDPOINT),
        node("say", "Say it", "set", fields=[{"name": "headline", "value": "{{ steps.look.data.title }}"}]),
    ], [arrow("look", "say")])
    w.script.append("```bash\nprintf pwned\n```")
    w.script.append('```json\n{"title": "Pantheon 2.0", "url": "https://example.org/notes"}\n```')
    await w.s._execute_task("wf")
    [run] = runs_of(w.factory, "wf")
    assert w.executed == [], "bash never reached the far end"
    assert any("“bash” is not one of this step's tools." in str(m.get("content"))
               for m in w.seen[1]), "the loop told the model why"
    by = {r["node_id"]: r for r in records_of(w.factory, run["id"])}
    assert by["look"]["status"] == "success", by["look"]
    assert by["look"]["output"]["data"] == {"title": "Pantheon 2.0", "url": "https://example.org/notes"}
    assert by["say"]["output"]["data"] == {"headline": "Pantheon 2.0"}
    assert run["status"] == "success", run


# ── the browser half against the server half ──────────────────────────────────

pytestmark_js = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_JS_PREAMBLE = (
    "import { document, Node, fire, settle, host, markup } from './shim.js';\n"
    "const SF = await import('./stepFields.js');\n"
    "const { KIND_WORDS } = await import('../tasks/workflowDiagram.js');\n"
    "const { PALETTE_KINDS } = await import('./workflowPanels.js');\n"
    "const out = (o) => console.log(JSON.stringify(o));\n"
    "const PAL = %s;\n"
    "const typed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'input', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const changed = (el, v) => { el.value = v; el.dispatchEvent({ type: 'change', target: el, stopPropagation() {}, preventDefault() {} }); };\n"
    "const byField = (h, f) => h.querySelectorAll('[data-field]').find((n) => n.dataset.field === f);\n"
    "const addRow = (h, words) => fire(h.querySelectorAll('.wf-sf-add').find((b) => b.textContent === words), 'click');\n"
    "const seenSlots = [];\n"
    "const pickField = (input, { field, slot }) => { seenSlots.push([field, slot ? slot.mapping : null]); return null; };\n"
    "const fill = (kind, how, more = {}) => {\n"
    "  const h = host();\n"
    "  const got = [];\n"
    "  SF.mountStepFields(h, { node: { id: `x-${kind}`, kind, label: '', config: {} }, palette: PAL,\n"
    "    pickField, onApply: (s) => got.push(s), ...more });\n"
    "  how(h);\n"
    "  fire(h.querySelector('.wf-step-done'), 'click');\n"
    "  const p = h.querySelector('.wf-sf-problem');\n"
    "  return got[0] || { refused: p ? [p.textContent, p.dataset.field] : 'nothing' };\n"
    "};\n"
)


@pytest.fixture(scope="module")
def js_box(tmp_path_factory):
    from helpers.workflow_cw_fake import build_sandbox
    from test_the_workbench_canvas_js import _SHIM as _CANVAS_SHIM
    return build_sandbox(tmp_path_factory.mktemp("halves"), _CANVAS_SHIM)


def _js(js_box, script):
    from helpers.workflow_cw_fake import palette_json
    from test_tool_effect_surfaces_js import _run
    return _run(js_box, _JS_PREAMBLE % palette_json(workstation_why=""), script)


@pytestmark_js
def test_the_palette_says_the_words_the_boxes_say(js_box):
    """The palette's words (`workflow_effects.KIND_WORDS`) are the words every
    box, panel and record draws (`workflowDiagram.js:KIND_WORDS`), and Slice
    B's four hints are the room's fallback's (`PALETTE_KINDS`) — the merge said
    "Set" / "For each" in the palette and "Set fields" / "For each item" on
    the step it made."""
    from src import workflow_document as wd
    from src import workflow_effects as fx
    o = _js(js_box, "out({ words: KIND_WORDS, four: PALETTE_KINDS });")
    assert {k: o["words"][k] for k in wd.NODE_KINDS} == {k: fx.KIND_WORDS[k] for k in wd.NODE_KINDS}
    assert {k["kind"]: k["hint"] for k in o["four"]} == {k: fx.KIND_HINTS[k] for k in wd.TASK_KINDS}


_FILL_ALL = r"""
const forms = {};
forms.if = fill('if', (h) => { typed(byField(h, 'conditions[0].left'), '{{ steps.read.text }}');
  changed(byField(h, 'conditions[0].op'), 'contains'); typed(byField(h, 'conditions[0].right'), 'URGENT'); });
forms.switch = fill('switch', (h) => { typed(byField(h, 'cases[0].label'), 'Urgent');
  typed(byField(h, 'cases[0].conditions[0].left'), '{{ steps.read.text }}');
  changed(byField(h, 'cases[0].conditions[0].op'), 'contains');
  typed(byField(h, 'cases[0].conditions[0].right'), 'URGENT'); });
forms.set = fill('set', (h) => { typed(byField(h, 'fields[0].name'), 'headline');
  typed(byField(h, 'fields[0].value'), '{{ steps.read.text }}'); });
forms.merge = fill('merge', () => {});
forms.wait = fill('wait', (h) => { typed(byField(h, 'minutes'), '45'); });
forms.foreach = fill('foreach', (h) => { typed(byField(h, 'list'), '{{ steps.read.data.items }}');
  fire(h.querySelector('.wf-sf-inner-edit'), 'click'); },
  { editInner: (base, done) => done({ kind: 'llm', label: 'Summarise', config: { prompt: 'Summarise {{ item.subject }}' } }) });
forms.http = fill('http', (h) => { changed(byField(h, 'integration'), 'int1'); changed(byField(h, 'method'), 'POST');
  typed(byField(h, 'path'), '/v1/entries');
  addRow(h, 'Add a query value'); typed(byField(h, 'query[0].name'), 'status'); typed(byField(h, 'query[0].value'), 'unread');
  addRow(h, 'Add a body field'); typed(byField(h, 'body[0].name'), 'text'); typed(byField(h, 'body[0].value'), '{{ steps.read.text }}'); });
forms.mcp = fill('mcp', (h) => { changed(byField(h, 'tool'), 'mcp__chat__send_message');
  typed(byField(h, 'args.channel'), '#ops'); typed(byField(h, 'args.text'), '{{ steps.read.text }}'); });
forms.skill = fill('skill', (h) => { changed(byField(h, 'skill'), 'print-queue'); typed(byField(h, 'prompt'), 'Print it.'); });
forms.code = fill('code', (h) => { addRow(h, 'Add an input'); typed(byField(h, 'input[0].name'), 'prices');
  typed(byField(h, 'input[0].value'), '{{ steps.read.data.prices }}'); });
out({ forms, seenSlots });
"""


def _resources():
    from src import workflow_document as wd
    from tests.helpers.workflow_cw_fake import ENV_MCP_TOOLS
    return wd.WorkflowResources(
        integrations={"int1": {"name": "Miniflux", "enabled": True}},
        mcp_tools={t["qualified_name"]: {"input_schema": t["input_schema"], "disabled": False,
                                         "is_readonly": t["is_readonly"]} for t in ENV_MCP_TOOLS},
        skills=frozenset({"print-queue"}), ai_tools=frozenset({"web_search"}), workstation_why=None)


def _path(field: str) -> tuple:
    """`cases[0].conditions[1].left` → `("cases", 0, "conditions", 1, "left")`."""
    out = []
    for name, index in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]", field):
        out.append(int(index) if index else name)
    return tuple(out)


@pytestmark_js
def test_every_step_form_writes_what_the_rule_and_the_renderer_read(js_box):
    """Each of the ten forms, filled as a person fills it (typed, picked,
    rows added), hands over a config the real rule accepts at save and the
    real `render_call` turns into the call the walker dispatches. The HTTP
    form wrote its query and body as `{key, value}`; the rule and the
    renderer read `{name, value}` — every save was refused ("each of “query”
    is a name and a value")."""
    from src import workflow_document as wd
    from src import workflow_slots as ws
    from tests.helpers.workflow_cw_fake import ENV_MCP_TOOLS
    o = _js(js_box, _FILL_ALL)
    forms = o["forms"]
    refused = {k: v for k, v in forms.items() if "refused" in v}
    assert not refused, refused
    read = {"id": "read", "kind": "llm", "label": "Read the mail", "config": {"prompt": "Read it."}}
    nodes = [read] + [{"id": f"x-{kind}", **step} for kind, step in forms.items()]
    edges = [{"from": "read", "port": "success", "to": f"x-{kind}"} for kind in forms]
    graph = wd.parse_graph({"v": 1, "nodes": nodes, "edges": edges})
    refusal = wd.validate_document(graph, owner="root", tasks_by_id={}, crew_ids=set(),
                                   owner_is_admin=True, own_task_id=None, resources=_resources())
    assert refusal is None, refusal
    ctx = {"steps": {"read": {"text": "URGENT: the build is red",
                              "data": {"items": [{"subject": "a"}], "prices": [4.5, 3.25]},
                              "status": "success"}}}
    by = {n["id"]: n for n in graph["nodes"]}
    http = json.loads(ws.render_call(by["x-http"], ctx).content)
    assert http["params"] == {"status": "unread"}
    assert http["body"] == {"text": "URGENT: the build is red"}
    schema = ENV_MCP_TOOLS[0]["input_schema"]
    mcp = ws.render_call(by["x-mcp"], ctx, mcp_schema=schema)
    assert (mcp.tool, json.loads(mcp.content)) == (SEND, {"channel": "#ops", "text": "URGENT: the build is red"})
    code = ws.render_call(by["x-code"], ctx)
    assert json.loads(code.content) == {"prices": [4.5, 3.25]}


@pytestmark_js
def test_every_field_a_panel_offers_a_picker_on_is_one_the_renderer_fills(js_box):
    """The slot each panel field looks up in the palette (`slotFor`: the path
    with `[]` for each index, then its last name) is the slot the rule and the
    renderer decide for that path (`workflow_slots.slot_for`): no field offers
    *Insert a field…* where a reference would be refused, and every `never`
    the panel says is the rule's. One gap, fail-closed and filed: an HTTP
    query or body value is `value` only by its entry's name, which the palette
    cannot answer once per kind, so the panel says `never` for all of them."""
    from src import workflow_slots as ws
    from tests.helpers.workflow_cw_fake import ENV_MCP_TOOLS
    o = _js(js_box, _FILL_ALL)
    forms = o["forms"]
    schema = ENV_MCP_TOOLS[0]["input_schema"]
    nodes = {kind: {"id": f"x-{kind}", **step} for kind, step in forms.items()}
    seen = o["seenSlots"]
    assert seen, "the panels decorated their fields"
    unknown = [field for field, mapping in seen if mapping is None]
    assert unknown == [], f"a field the palette gave no slot: {unknown}"
    # Which form each decorated field belongs to: the forms were filled in this
    # order, and each field path is unique to its kind's shape.
    mismatched, gap = [], []
    owners = {"conditions": "if", "cases": "switch", "fields": "set", "minutes": "wait", "time": "wait",
              "tz": "wait", "list": "foreach", "path": "http", "query": "http", "body": "http",
              "args": "mcp", "skill": "skill", "source": "code", "timeout_seconds": "code",
              "input": "code", "join": "if"}
    for field, mapping in seen:
        path = _path(field)
        kind = owners.get(path[0])
        if kind is None and path[0] == "prompt":
            kind = "skill"
        assert kind, field
        rule = ws.slot_for(nodes[kind], path, mcp_schema=schema if kind == "mcp" else None).mapping
        if mapping == ws.MAPPING_VALUE:
            assert rule == ws.MAPPING_VALUE, f"{kind} {field}: a picker where the renderer refuses one"
        elif rule != mapping:
            (gap if kind == "http" and path[-1] == "value" else mismatched).append((kind, field, rule))
    assert mismatched == [], mismatched
    assert gap == [("http", "body[0].value", "value")], "the one filed gap, and only it"


@pytestmark_js
def test_the_picker_lists_a_nested_field_as_its_reference_spells_it(js_box):
    """The fields route answers each field's `path` as a list of segments
    (`flatten_fields`, the form `format_ref` takes); the picker printed it as
    it came, so a nested field read `json,subject` (found by the drive). It now
    lists the path as the server's own reference spells it, and a field a step
    only promises shows no example (it showed the word "null")."""
    from src import workflow_effects as we
    data = {"json": {"subject": "URGENT: the build is red"}, "headers": {"content-type": "application/json"},
            "items": [{"title": "first"}]}
    sources = [we._source("start", "What started it", "start", we.ORIGIN_LAST_RUN, None,
                          we._fields_of("start", None, data)),
               we._source("rename", "Rename", "set", we.ORIGIN_DECLARED, None,
                          we._declared_fields("rename", [("headline", None)]))]
    o = _js(js_box, "const SOURCES = %s;\n" % json.dumps(sources) + r"""
        const { openFieldPicker } = await import('./fieldPicker.js');
        const root = host();
        const anchor = root.appendChild(new Node('button'));
        openFieldPicker(anchor, { load: async () => ({ ok: true, sources: SOURCES }), layer: () => root });
        await settle(); await settle();
        out({ groups: root.querySelectorAll('.wf-picker-source').map((g) => [
          g.querySelector('.wf-picker-step-name').textContent,
          g.querySelectorAll('.wf-picker-field').map((b) => [b.querySelector('.wf-picker-path').textContent,
            (b.querySelector('.wf-picker-example') || { textContent: null }).textContent, b.dataset.ref])]) });
    """)
    start = {path: (example, ref) for path, example, ref in o["groups"][0][1]}
    assert start["json.subject"] == ("URGENT: the build is red", "{{ steps.start.data.json.subject }}")
    assert start['headers["content-type"]'][1] == '{{ steps.start.data.headers["content-type"] }}'
    assert start["items[0].title"] == ("first", "{{ steps.start.data.items[0].title }}")
    assert not [p for p in start if "," in p], "no field is listed by a comma-joined list"
    assert o["groups"][1] == ["Rename", [["headline", None, "{{ steps.rename.data.headline }}"]]]


@pytest.mark.asyncio
async def test_a_failed_run_names_the_step_it_failed_on_and_the_room_opens_there(factory, monkeypatch, js_box):
    """Found by the merged drive (P22-12): a run whose For-each failed on an
    item did not open on its failed step — the room took "the last record, when
    it failed" (Slice B's single path), and here the last record is the next
    item, which worked. The run's detail now names the step by the walker's own
    rule (`RunState.unhandled_error`), and the source opens on it."""
    from core.database import WorkflowVersion
    from src.builtin_actions import NodeResult
    nodes = [node("make", "Make the list", "set", fields=[{"name": "hosts", "value": ["a", "b", "c"]}]),
             node("each", "Each host", "foreach", list="{{ steps.make.data.hosts }}", on_error="continue",
                  step={"kind": "action", "label": "Tidy", "config": {"action": "tidy_sessions"}})]
    seed_workflow(factory, nodes, [arrow("make", "each")])
    db = factory()     # the version the run ran is kept, as a save keeps it
    db.add(WorkflowVersion(id="v3", workflow_id="w-wf", version=3, name="Morning digest",
                           graph=json.dumps({"v": 1, "nodes": nodes, "edges": [arrow("make", "each")]}),
                           fingerprint="f3", source="user"))
    db.commit()
    db.close()
    s = recording_scheduler({"Morning digest · Tidy · item 2 of 3": NodeResult("error", payload="It broke on b.")})
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "error", run
    records = records_of(factory, run["id"])
    assert records[-1]["status"] == "success" and records[-1]["item"] == 2, "the last record is item 3, which worked"
    app = app_for(factory, s, monkeypatch)
    async with client_for(app) as client:
        detail = (await client.get(f"/api/workflows/w-wf/runs/{run['id']}",
                                   headers={"x-test-user": "alice"})).json()
    assert detail["failed"] == {"node_id": "each", "label": "Each host",
                                "error": "Item 2 of 3 failed: It broke on b."}
    o = _js(js_box, "const DETAIL = %s;\n" % json.dumps(detail, default=str) + r"""
        const { server: cw, net: cwnet, seed, cwApi } = await import('./cwfake.js');
        const { createWorkflowSource } = await import('./workflowSource.js');
        seed({ id: 'w-wf', name: 'Morning digest', task_id: 'wf', trigger_status: 'active', version: 3,
               trigger_task: { id: 'wf', status: 'active' }, graph: DETAIL.graph });
        cw.executions[DETAIL.run.id] = DETAIL;
        const src = createWorkflowSource({ api: cwApi(cwnet), workflowId: 'w-wf', mode: 'run', runId: DETAIL.run.id });
        await src.ready;
        out({ failed: src.state().failed });
    """)
    assert o["failed"]["nodeId"] == "each" and o["failed"]["firstLine"] == "Item 2 of 3 failed: It broke on b."
