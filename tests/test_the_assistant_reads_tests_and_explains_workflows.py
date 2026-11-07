# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1878` — the assistant reads, tests and explains the workflows that exist.

**Measured on `5e4c8ec`** (the audit's probe): the assistant had one way into
a workflow, `manage_tasks draft_workflow`, which makes a new one. Asked "why
did step 3 of my bank-mail workflow fail?", it had no tool that lists the
workflows, says their steps, reads a run step by step, asks the explainer the
Workbench's *Why did this fail?* asks, tries a switched-off workflow once, or
exports one — `find_tools "workflow runs"` found nothing that did, and
`ui_control open_panel` had no Workbench to open. The loop "build this flow,
test it, tell me why step 3 failed" stopped after "build".

Now `manage_workflows` does those seven things, each through the door the
Workbench's own button goes through (`Law 14`):

  * `list`, `show`, `runs` read what the store and the runs already hold;
  * `explain` is the explain route's read and ask, moved into
    `workflow_assist.step_to_explain` / `explain_answer` so both doors read one
    step the same way — the run's bytes reach the model only inside the
    untrusted guard, and a change it proposes is only ever proposed;
  * `dry_run` is `manage_tasks dry_run` on the workflow's start;
  * `test_run` is `run_task_now(test=True)` (`B1852`) — once, even switched
    off, and the switch is not touched; a workflow with steps nobody has
    checked is not tested;
  * `export` is the Workbench's file, which carries no key and no address.

**The adversary (`Law 17`)** is whoever wrote what a run recorded — here an
Integration's server whose 404 body orders the model about. What holds is
what held at the route; and nothing this tool has reaches what is the
person's alone (`B1117`, `B1005`, `B1870`): checking a step, applying a fix,
answering a waiting step. Asked for one, it says whose it is and writes
nothing.

**The token budget (the owner's rule):** the tool is offered on a workflow
turn only (`tool_index.ON_REQUEST_ONLY`) — a plain or a schedule turn is
offered exactly what it was, and `find_tools` can still load it. Its schema
costs under 800 tokens.

`ui_control open_panel workbench <id>` opens the Workbench on one workflow,
and a tool card whose result names a workflow carries a door to it.

Real (`Law 20`): the real scheduler and walker over a real SQLite file; the
HTTP step reaches a loopback server that answers 404 through the real SSRF
guard; the model is `workflow_assist._complete`, scripted.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from core.database import ScheduledTask, TaskRun, Workflow, WorkflowVersion
from src import workflow_assist as wa
from src import workflow_store as store
from src.prompt_security import GUARD_CLOSE, GUARD_OPEN
from tests.helpers.assist_harness import (
    KEY, Feeds, build_world, miniflux, resolve_to_loopback, rows, script_model, stored,
)
from tests.helpers.walker_harness import arrow, node, row, runs_of, seed_workflow, settle
from tests.test_a_first_message_is_not_a_lesser_message import (
    ORDINARY_TURN, _base, _drive, _mcp_manager,
)
from tests.test_why_did_this_step_fail import (
    COMPLIES, EDGES, FETCH, HOSTILE_HINT, POST_STEP, TALLY, _call, _failed_run,
)

SCHEDULE_TURN = "Every weekday at 8:00, give me my daily brief."
STEPS = ([node("s", "Make it", "set", fields=[{"name": "n", "value": 3}]),
          node("a", "Tidy", "action", action="tidy_sessions")],
         [arrow("start", "s"), arrow("s", "a")])


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import src.event_bus as event_bus
    feeds = Feeds()
    feeds.not_found = {"error": "not found", "hint": HOSTILE_HINT}
    resolve_to_loopback(monkeypatch)
    w = build_world(monkeypatch, tmp_path, integrations=[miniflux(feeds.base_url)],
                    workstation=True)
    monkeypatch.setattr(event_bus, "_task_scheduler", w.s)
    w.feeds = feeds
    yield w
    feeds.close()


async def _tool(owner="alice", **args):
    from src.tools.workflows import do_manage_workflows
    return await do_manage_workflows(json.dumps(args), owner=owner)


def _marked(nodes):
    return [dict(n, unchecked={"origin": "drafted", "needs": []}) for n in nodes]


def _graphs(factory):
    db = factory()
    try:
        return {wf.id: (wf.graph, wf.version) for wf in db.query(Workflow).all()}
    finally:
        db.close()


# ── list, show, runs ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_names_each_workflow_its_switch_its_start_and_its_last_run(world):
    w = world
    wf_id, task_id, run_id = await _failed_run(w)
    seed_workflow(w.factory, _marked(STEPS[0]), STEPS[1], status="paused")
    said = await _tool(action="list")
    assert said["exit_code"] == 0, said
    lines = said["response"].split("\n")
    assert lines[0] == "2 workflows:"
    [feeds] = [ln for ln in lines if "“Feeds”" in ln]
    [digest] = [ln for ln in lines if "“Morning digest”" in ln]
    assert re.fullmatch(rf"\d\. “Feeds” \(id {wf_id}\) — switched on; 3 steps; starts daily "
                        rf"at 09:00 \(UTC\); last run failed \(\d{{4}}-\d\d-\d\dT[^)]+\)",
                        feeds), feeds
    assert re.fullmatch(r"\d\. “Morning digest” \(id w-wf\) — switched off; 2 steps; starts "
                        r"daily at 08:00 \(UTC\); 2 not checked yet", digest), digest
    # bob has none of them
    theirs = await _tool(owner="bob", action="list")
    assert theirs["response"] == ("No workflows yet. manage_tasks draft_workflow drafts one "
                                  "from the person's words.")


@pytest.mark.asyncio
async def test_show_says_the_steps_in_order_where_each_goes_and_where_it_sends(world):
    w = world
    wf_id, task_id, _run_id = await _failed_run(w)
    said = await _tool(action="show", workflow_id="Feeds")
    assert said["exit_code"] == 0 and said["workflow_id"] == wf_id, said
    assert said["response"].split("\n") == [
        f"“Feeds” (id {wf_id}, its start is task {task_id}) — switched on, version 2. It starts "
        f"daily at 09:00 (UTC).",
        "Steps (3), as listed:",
        "1. “Fetch unread” (step fetch) — HTTP request; then “Post to #dev” if it works",
        "2. “Post to #dev” (step post) — MCP tool; then “Tally” if it works",
        "3. “Tally” (step tally) — Code",
        "Where it sends things: “Fetch unread” sends GET /v1/entriess to Miniflux. “Post to "
        "#dev” sends to Chat: send_message — channel: #dev. “Tally” runs your code in your own "
        "workstation account, not on this machine, and the code reaches whatever that account "
        "can.",
    ]
    assert KEY not in said["response"] and w.feeds.base_url not in said["response"]


@pytest.mark.asyncio
async def test_show_says_which_steps_nobody_has_checked_and_who_checks_them(world):
    w = world
    seed_workflow(w.factory, _marked(STEPS[0]), STEPS[1], status="paused")
    said = await _tool(action="show", workflow_id="w-wf")
    assert said["response"].split("\n")[-1] == (
        "The model drafted 2 steps nobody has checked yet: “Make it”, “Tidy”. Check them first. "
        "A person checks each step in the Workbench (Automations → “Morning digest”).")
    assert "switched off" in said["response"].split("\n")[0]


@pytest.mark.asyncio
async def test_runs_says_what_each_step_did_with_its_error(world):
    w = world
    wf_id, _task_id, run_id = await _failed_run(w)
    said = await _tool(action="runs", workflow_id=wf_id)
    assert said["exit_code"] == 0 and said["workflow_id"] == wf_id, said
    lines = said["response"].split("\n")
    assert lines[0] == "The last run of “Feeds”:"
    assert re.fullmatch(rf"- run {run_id}: failed, \d{{4}}-\d\d-\d\d \d\d:\d\d UTC\. It "
                        rf"failed at “Fetch unread” \(step fetch\)\.", lines[1]), lines[1]
    assert lines[2].startswith("  · “Fetch unread” (step fetch) — error: HTTP 404 "), lines[2]
    assert len(lines[2]) <= len("  · “Fetch unread” (step fetch) — error: ") + 300, \
        "a step's error is cut to a few lines"
    assert len(lines) == 3, "the steps after it never ran, so they have no record"
    assert KEY not in said["response"] and w.feeds.base_url not in said["response"]


@pytest.mark.asyncio
async def test_a_workflow_that_has_not_run_says_so(world):
    seed_workflow(world.factory, *STEPS)
    said = await _tool(action="runs", workflow_id="Morning digest")
    assert said == {"response": "“Morning digest” has not run yet.", "workflow_id": "w-wf",
                    "exit_code": 0}


# ── explain ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explain_reads_the_last_failed_run_and_only_proposes(world, monkeypatch):
    """No run or step named: the newest failed real run, and the step it failed
    on — the Runs view's own `failed`. The model complies with the 404 body;
    what reaches it is guarded, what survives is the path, and nothing is
    written."""
    w = world
    wf_id, _task_id, run_id = await _failed_run(w)
    before = _graphs(w.factory)
    versions_before = len(rows(w.factory, WorkflowVersion, workflow_id=wf_id))
    model = script_model(monkeypatch, COMPLIES)
    said = await _tool(action="explain", workflow_id="Feeds")
    assert said["exit_code"] == 0, said
    assert said["workflow_id"] == wf_id and said["run_id"] == run_id
    assert said["response"].startswith(
        f"Why “Fetch unread” failed in run {run_id}: The server says /v1/entriess does not "
        f"exist. The path should be /v1/entries. Fix the path. What it would change: Path from "
        f"\"/v1/entriess\" to \"/v1/entries\". A person applies it in the Workbench (Automations "
        f"→ “Feeds”, the step's Why did this fail? → Apply). Not in the change: It also "
        f"suggested sending to a different Integration. That is yours to decide, in the step's "
        f"panel. "), said["response"]
    assert said["response"].endswith(
        " A suggestion — the run's record may hold text someone else wrote.")
    for words in ("sending to a different Integration", "changing a header",
                  "changing the step's code", "sending the result somewhere else"):
        assert words in said["response"], words
    messages = model.calls[0]["messages"]
    guarded = [m for m in messages if GUARD_OPEN in m["content"]]
    assert len(guarded) == 1 and guarded[0]["metadata"]["trusted"] is False
    assert all("evil.example" not in m["content"] for m in messages if m is not guarded[0])
    assert KEY not in json.dumps(messages) and w.feeds.base_url not in json.dumps(messages)
    assert _graphs(w.factory) == before, "nothing is applied"
    assert len(rows(w.factory, WorkflowVersion, workflow_id=wf_id)) == versions_before


@pytest.mark.asyncio
async def test_explain_names_a_run_and_a_step_and_says_when_there_is_none(world, monkeypatch):
    w = world
    wf_id, _task_id, run_id = await _failed_run(w)
    model = script_model(monkeypatch)
    no_record = await _tool(action="explain", workflow_id=wf_id, run_id=run_id, node_id="post")
    assert no_record == {"error": "That step has no record in this run.", "exit_code": 1}
    no_run = await _tool(action="explain", workflow_id=wf_id, run_id="nope")
    assert no_run == {"error": "No such run of this workflow.", "exit_code": 1}
    seed_workflow(w.factory, *STEPS)
    never = await _tool(action="explain", workflow_id="w-wf")
    assert never == {"error": "“Morning digest” has no failed run to explain.", "exit_code": 1}
    assert model.calls == []


@pytest.mark.asyncio
async def test_explain_with_no_model_says_the_steps_own_error(world, monkeypatch):
    w = world
    wf_id, _task_id, _run_id = await _failed_run(w)
    import src.endpoint_resolver as er
    monkeypatch.setattr(er, "resolve_endpoint", lambda *a, **k: (None, None, None))
    said = await _tool(action="explain", workflow_id=wf_id)
    assert said["exit_code"] == 1 and said["workflow_id"] == wf_id, said
    assert said["error"].startswith(
        "No model is set up to explain this (the utility or the default model). The step's own "
        "error: "), said["error"]
    assert KEY not in said["error"]


# ── dry_run, test_run, export ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_says_what_it_would_do_and_nothing_runs(world):
    w = world
    seed_workflow(w.factory, *STEPS, status="paused")
    said = await _tool(action="dry_run", workflow_id="Morning digest")
    assert said["exit_code"] == 0 and said["workflow_id"] == "w-wf", said
    assert said["response"].split("\n") == [
        "“Morning digest”: Dry run — nothing ran.",
        "Step 1, “Make it”: Would make these fields:",
        "Step 2, “Tidy” (if the step before works): Would run: tidy_sessions — Clean up empty "
        "chats and sort the rest into folders",
        "It is paused, so a real run would not start it."], said["response"]
    await settle(w.s)
    assert w.s.calls == [], "nothing ran"
    assert row(w.factory, "wf").status == "paused"
    read_back = await _tool(action="runs", workflow_id="w-wf")
    assert re.search(r"- run \S+: a dry run, .* — nothing ran\.", read_back["response"]), \
        read_back["response"]


@pytest.mark.asyncio
async def test_test_run_runs_the_saved_version_once_and_it_stays_off(world):
    w = world
    seed_workflow(w.factory, *STEPS, status="paused")
    said = await _tool(action="test_run", workflow_id="w-wf")
    assert said["exit_code"] == 0, said
    assert said["response"] == ("Test run of “Morning digest” started: the saved version, once. "
                                "The workflow stays switched off. runs says what each step did.")
    assert said["workflow_id"] == "w-wf"
    await settle(w.s)
    [run] = runs_of(w.factory, "wf")
    assert run["id"] == said["run_id"] and run["status"] == "success", run
    assert run["steps"][0]["detail"] == "Test run"
    assert [c["name"] for c in w.s.calls] == ["Morning digest · Tidy"]
    assert row(w.factory, "wf").status == "paused", "the switch is not touched"
    read_back = await _tool(action="runs", workflow_id="w-wf")
    assert f"- run {run['id']}: worked, " in read_back["response"]
    assert "(test run)" in read_back["response"]


@pytest.mark.asyncio
async def test_a_workflow_nobody_has_checked_is_not_tested(world):
    w = world
    seed_workflow(w.factory, _marked(STEPS[0]), STEPS[1], status="paused")
    said = await _tool(action="test_run", workflow_id="w-wf")
    assert said == {
        "error": ("“Morning digest” was not tested. The model drafted 2 steps nobody has checked "
                  "yet: “Make it”, “Tidy”. Check them first. A person checks each step in the "
                  "Workbench (Automations → “Morning digest”); dry_run says what it would do "
                  "meanwhile."),
        "workflow_id": "w-wf", "exit_code": 1}
    await settle(w.s)
    assert runs_of(w.factory, "wf") == [] and w.s.calls == []


@pytest.mark.asyncio
async def test_export_is_the_workbench_file_without_the_key_or_the_address(world):
    w = world
    wf_id, _task_id, _run_id = await _failed_run(w)
    said = await _tool(action="export", workflow_id=wf_id)
    assert said["exit_code"] == 0 and said["workflow_id"] == wf_id, said
    head, body = said["response"].split("\n", 1)
    assert head == ("“Feeds” as a file, feeds.workflow.json. No webhook token, key, base URL, "
                    "header value or endpoint address is in it."), head
    assert said["file_name"] == "feeds.workflow.json"
    data = json.loads(body)
    assert data["name"] == "Feeds"
    assert [n["id"] for n in data["graph"]["nodes"]] == ["fetch", "post", "tally"]
    assert data["requires"]["integrations"][0]["name"] == "Miniflux"
    assert KEY not in body and w.feeds.base_url not in body and str(w.feeds.port) not in body


# ── what is the person's ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("action, sentence", [
    ("check", store.ONLY_A_PERSON_CHECKS),
    ("fix", store.ONLY_A_PERSON_FIXES),
    ("apply_fix", store.ONLY_A_PERSON_FIXES),
    ("answer", store.ONLY_A_PERSON_ANSWERS),
    ("approve", store.ONLY_A_PERSON_ANSWERS),
])
async def test_what_is_the_persons_alone_is_refused_in_its_own_words(world, action, sentence):
    w = world
    seed_workflow(w.factory, _marked(STEPS[0]), STEPS[1], status="paused")
    before = _graphs(w.factory)
    said = await _tool(action=action, workflow_id="w-wf", node_id="s")
    assert said == {"error": sentence, "exit_code": 1}
    assert _graphs(w.factory) == before


@pytest.mark.asyncio
async def test_an_edit_or_a_switch_is_pointed_where_it_is_made(world):
    w = world
    seed_workflow(w.factory, *STEPS, status="paused")
    edit = await _tool(action="edit", workflow_id="w-wf")
    assert edit["error"] == ("Changing a workflow is the person's, in the Workbench "
                             "(Automations). A new one: manage_tasks draft_workflow drafts it, "
                             "switched off.")
    on = await _tool(action="switch_on", workflow_id="w-wf")
    assert on["error"] == ("Switching a workflow on or off is manage_tasks resume or pause, with "
                           "the task_id show names as its start. A workflow with steps nobody "
                           "has checked is not switched on.")
    assert row(w.factory, "wf").status == "paused"


@pytest.mark.asyncio
async def test_another_persons_workflow_is_not_found_by_id_or_by_name(world):
    w = world
    seed_workflow(w.factory, *STEPS)
    for ref in ("w-wf", "Morning digest"):
        for action in ("show", "runs", "export", "test_run", "dry_run", "explain"):
            said = await _tool(owner="bob", action=action, workflow_id=ref)
            assert said["error"] == (f"No workflow of yours has the id or the name “{ref}”. "
                                     f"list names them."), (action, said)
    await settle(w.s)
    assert runs_of(w.factory, "wf") == []


@pytest.mark.asyncio
async def test_an_unknown_action_names_the_seven_and_a_missing_workflow_is_asked_for(world):
    said = await _tool(action="frobnicate")
    assert said == {"error": ("Unknown action: frobnicate. manage_workflows reads, tests and "
                              "explains workflows: list, show, runs, explain, dry_run, test_run, "
                              "export."), "exit_code": 1}
    assert await _tool(action="show") == {"error": "Name the workflow: workflow_id, from list.",
                                          "exit_code": 1}


@pytest.mark.asyncio
async def test_two_workflows_of_one_name_are_named_by_id(world):
    w = world
    seed_workflow(w.factory, *STEPS, task_id="one")
    seed_workflow(w.factory, *STEPS, task_id="two")
    said = await _tool(action="show", workflow_id="morning digest")
    assert said["exit_code"] == 1
    assert said["error"] in ("2 of your workflows are called “morning digest”; name one by its "
                             f"id: {ids}." for ids in ("w-one, w-two", "w-two, w-one")), said


# ── offered on a workflow turn only (the token budget) ──────────────────────


def test_the_schema_costs_less_than_800_tokens():
    from src.context_budget import tool_schema_tokens
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    [schema] = [s for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "manage_workflows"]
    assert tool_schema_tokens([schema]) <= 800
    assert schema["function"]["parameters"]["properties"]["action"]["enum"] == [
        "list", "show", "runs", "explain", "dry_run", "test_run", "export"]


@pytest.mark.parametrize("text", [ORDINARY_TURN, SCHEDULE_TURN,
                                  "Remind me every Friday at 5pm to water the plants."])
def test_a_turn_that_does_not_ask_for_workflows_is_not_offered_it(monkeypatch, text):
    from src.tool_index import ToolIndex
    assert "manage_workflows" not in ToolIndex.select_without_embeddings(text, set())
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message=text, prompt_type="agent")
    assert "manage_workflows" not in sent[0]["tools"], sent[0]["tools"]
    assert "manage_workflows" not in sent[0]["prompt"]


@pytest.mark.parametrize("text", ["Why did step 3 of my bank-mail workflow fail?",
                                  "Test run my morning automation.",
                                  "Show me my workflows."])
def test_a_workflow_turn_is_offered_it(monkeypatch, text):
    from src.tool_index import ToolIndex
    assert "manage_workflows" in ToolIndex.select_without_embeddings(text, set())
    _base(monkeypatch, _mcp_manager())
    sent = _drive(monkeypatch, message=text, prompt_type="agent")
    assert {"manage_tasks", "manage_workflows"} <= set(sent[0]["tools"]), sent[0]["tools"]


def test_the_plan_holds_it_back_unless_the_turn_asks():
    """Whole or partial, a turn that did not ask is planned as if the tool did
    not exist — `on_request` names it for `find_tools`; asked by a keyword,
    a domain or last turn's set, it is in."""
    from src.tool_index import plan_tool_suite
    pool = ["ask_user", "find_tools", "manage_tasks", "manage_workflows", "web_search"]
    whole = plan_tool_suite(pool, cost=lambda n: 100, room=100_000)
    assert "manage_workflows" not in whole.candidates
    assert whole.on_request == ("manage_workflows",)
    partial = plan_tool_suite(pool, cost=lambda n: 100, room=250, pinned=["ask_user"])
    assert "manage_workflows" not in partial.candidates
    assert partial.on_request == ("manage_workflows",)
    for asked in ({"keyword_picks": ["manage_workflows"]}, {"keep": ["manage_workflows"]},
                  {"domains": ["workflows"], "domain_map": {"workflows": {"manage_workflows"}}}):
        planned = plan_tool_suite(pool, cost=lambda n: 100, room=100_000, **asked)
        assert "manage_workflows" in planned.candidates, asked
        assert planned.on_request == ()


class _RealFindTools:
    """`_drive`'s monkeypatch, except that `find_tools` runs for real: the
    harness answers every tool "ok", and this asks what the loop does with
    what `find_tools` found."""

    def __init__(self, mp):
        self._mp = mp

    def __getattr__(self, name):
        return getattr(self._mp, name)

    def setattr(self, target, name, value, raising=True):
        if name == "execute_tool_block":
            stub = value

            async def run(block, *a, **k):
                if block.tool_type == "find_tools":
                    from src.tools.system import do_find_tools
                    return "find_tools", await do_find_tools(block.content)
                return await stub(block, *a, **k)
            value = run
        return self._mp.setattr(target, name, value, raising=raising)


def test_find_tools_finds_it_and_the_loop_loads_it(monkeypatch):
    from src.tools.system import find_tool_matches
    found = [r["name"] for r in find_tool_matches("why did my workflow run fail", mcp_tools={})]
    assert "manage_workflows" in found[:3], found
    _base(monkeypatch, _mcp_manager())
    sent = _drive(_RealFindTools(monkeypatch), message=ORDINARY_TURN, prompt_type="agent",
                  rounds=('```find_tools\n{"names": ["manage_workflows"]}\n```', "Done."))
    assert "manage_workflows" not in sent[0]["tools"]
    assert len(sent) >= 2 and "manage_workflows" in sent[1]["tools"], \
        [s["tools"] for s in sent]


# ── what each action does, said to the gate ─────────────────────────────────


def test_each_action_says_what_it_does():
    from src.tool_capabilities import ToolEffect, capabilities_for_action
    for action in ("list", "show", "runs", "explain", "export"):
        caps = capabilities_for_action("manage_workflows", json.dumps({"action": action}))
        assert set(caps.effects) == {ToolEffect.READ_PRIVATE}, (action, caps.effects)
    test_run = capabilities_for_action("manage_workflows", json.dumps({"action": "test_run"}))
    assert ToolEffect.EXTERNAL_SIDE_EFFECT in test_run.effects, "a test run sends what it sends"
    dry = capabilities_for_action("manage_workflows", json.dumps({"action": "dry_run"}))
    assert ToolEffect.EXTERNAL_SIDE_EFFECT not in dry.effects
    assert capabilities_for_action("manage_workflows", "{}").effects == \
        capabilities_for_action("manage_workflows", json.dumps({"action": "list"})).effects


# ── the Workbench's door ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ui_control_opens_the_workbench_on_a_workflow():
    from src.ai_interaction import do_ui_control
    from src.tool_schemas import function_call_to_tool_block
    on_one = await do_ui_control("open_panel workbench w-wf")
    assert on_one == {"ui_event": "open_panel", "panel": "workbench", "workflow_id": "w-wf",
                      "results": "Opening the Workbench on workflow w-wf"}
    plain = await do_ui_control("open_panel automations")
    assert plain == {"ui_event": "open_panel", "panel": "workbench",
                     "results": "Opening the Workbench"}
    block = function_call_to_tool_block("ui_control", json.dumps(
        {"action": "open_panel", "name": "workbench", "value": "w-wf"}))
    assert block.content == "open_panel workbench w-wf"
    other = function_call_to_tool_block("ui_control", json.dumps(
        {"action": "open_panel", "name": "notes", "value": "x"}))
    assert other.content == "open_panel notes", "only the Workbench takes a second word"


_REPO = Path(__file__).resolve().parent.parent
_JS = _REPO / "static" / "js"
_HOOKS = """
export async function resolve(specifier, context, next) {
  if (specifier === '/static/js/workbench/workbench.js') {
    return { url: new URL('./workbench_stub.mjs', import.meta.url).href, shortCircuit: true };
  }
  return next(specifier, context);
}
"""
_STUB = "export function openWorkbench(o) { globalThis.__opened.push(o); return true; }\n"


def _node(directory: Path, script: str) -> dict:
    """`script` under node, `/static/js/workbench/workbench.js` answered by a
    stub that records what the Workbench was asked to open."""
    (directory / "hooks.mjs").write_text(_HOOKS, encoding="utf-8")
    (directory / "register.mjs").write_text(
        "import { register } from 'node:module';\nregister('./hooks.mjs', import.meta.url);\n",
        encoding="utf-8")
    (directory / "workbench_stub.mjs").write_text(_STUB, encoding="utf-8")
    entry = directory / "case.mjs"
    entry.write_text("globalThis.__opened = [];\n" + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", "--import", "./register.mjs", str(entry)], cwd=directory,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_a_card_whose_result_names_a_workflow_opens_it(tmp_path):
    from test_tool_effect_surfaces_js import _copy_unstubbed_imports
    from tests.helpers.esc_stub import ui_default_stub
    (tmp_path / "ui.js").write_text(ui_default_stub(), encoding="utf-8")
    shutil.copy(_JS / "agentThread.js", tmp_path / "agentThread.js")
    _copy_unstubbed_imports(tmp_path, _JS / "agentThread.js", {"ui.js"})
    out = _node(tmp_path, """
        const listeners = [];
        globalThis.document = { addEventListener: (type, fn, capture) =>
          listeners.push({ type, fn, capture }) };
        const m = await import('./agentThread.js');
        const card = (o) => m.agentThreadNodeHtml(Object.assign(
          { tool: 'manage_workflows', state: 'done', ok: true }, o));
        const door = { getAttribute: (k) => (k === 'data-open-workflow' ? 'w-wf' : null) };
        const ev = { target: { closest: (sel) => (sel === '[data-open-workflow]' ? door : null) },
                     prevented: false, stopped: false,
                     preventDefault() { this.prevented = true; },
                     stopPropagation() { this.stopped = true; } };
        for (const l of listeners) if (l.type === 'click' && l.capture === true) l.fn(ev);
        await new Promise((r) => setTimeout(r, 50));
        console.log(JSON.stringify({
          named: card({ workflowId: 'w-wf' }), hostile: card({ workflowId: 'w"><img src=x>' }),
          none: card({}), notString: card({ workflowId: 7 }),
          prevented: ev.prevented, stopped: ev.stopped, opened: globalThis.__opened }));
    """)
    assert ('<button type="button" class="agent-thread-ws-door" data-open-workflow="w-wf" '
            'title="Open this workflow in the Workbench">Open in the Workbench</button>') \
        in out["named"]
    assert "<img" not in out["hostile"] and 'data-open-workflow="w&quot;&gt;&lt;img' in out["hostile"]
    assert "data-open-workflow" not in out["none"] and "data-open-workflow" not in out["notString"]
    assert out["opened"] == [{"workflowId": "w-wf"}]
    assert out["prevented"] and out["stopped"], "the press does not also fold the card"


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_ui_control_open_panel_workbench_opens_it_in_the_browser(tmp_path):
    from tests.helpers.esc_stub import esc_source
    from tests.helpers.js_source import js_function
    body = js_function((_JS / "chatStream.js").read_text(encoding="utf-8"),
                       "export function handleUIControl")
    out = _node(tmp_path, esc_source() + f"""
        const uiModule = {{ esc }};
        function handleUIControl(uiData) {body}
        handleUIControl({{ ui_event: 'open_panel', panel: 'workbench', workflow_id: 'w-wf' }});
        handleUIControl({{ ui_event: 'open_panel', panel: 'workbench' }});
        await new Promise((r) => setTimeout(r, 50));
        console.log(JSON.stringify({{ opened: globalThis.__opened }}));
    """)
    assert out["opened"] == [{"workflowId": "w-wf"}, {"workflowId": None}]
