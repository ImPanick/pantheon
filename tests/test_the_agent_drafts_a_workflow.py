# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-19`'s agent half — `manage_tasks draft_workflow` (folds `B673`) and the
full list of actions the model may schedule (folds `B800`).

**Measured before this file, on `4cfb297`:** `manage_tasks` had no way to make
one task run after another — `then_task_id` was never in its schema, and a
`workflow` start is refused at `create` (`WORKFLOW_MADE_IN_WORKBENCH`) — so
*"run my backup and then email me the result"* was two tasks the agent could
make and could not join; `draft_workflow` answered "Unknown action". The
`action_name` enum listed 12 of the 14 actions a person may schedule:
`daily_brief` and `email_auto_translate` were missing for no stated reason.

`B673`'s `Verify:` is reworded on its row (`SLICE-EF-DESIGN` § 2): the agent,
asked to make one task run after another, drafts a workflow of two Run task
steps and says where to switch it on. Chains stay `D-2026-10-01-05` §1's
legacy path, so `then_task_id` is not added to the schema.

Real (`Law 20`): `do_manage_tasks` over a real SQLite file, the drafter, the
store, the rule; the model is `workflow_assist._complete`, scripted.
"""

import ast
import json
from pathlib import Path

import pytest

from core.database import ScheduledTask, Workflow
from src import workflow_store as store
from tests.helpers.assist_harness import build_world, marks_of, rows, script_model, stored

pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def world(monkeypatch, tmp_path):
    w = build_world(monkeypatch, tmp_path)
    db = w.factory()
    try:
        for task_id, name in (("t-backup", "Nightly backup"), ("t-report", "Email me the result")):
            db.add(ScheduledTask(id=task_id, owner="alice", name=name, task_type="llm",
                                 prompt=f"Do: {name}", trigger_type="schedule", schedule="daily",
                                 scheduled_time="02:00", status="active"))
        db.add(ScheduledTask(id="t-bob", owner="bob", name="Bob's secret", task_type="llm",
                             prompt="x", status="active"))
        db.commit()
    finally:
        db.close()
    return w


TWO_RUN_TASKS = {
    "name": "Backup, then report",
    "trigger": {"type": "schedule", "schedule": "daily", "time": "02:00"},
    "steps": [{"id": "backup", "kind": "run_task", "label": "Nightly backup",
               "config": {"task_id": "t-backup"}},
              {"id": "report", "kind": "run_task", "label": "Email me the result",
               "config": {"task_id": "t-report"}}],
    "arrows": [{"from": "backup", "port": "success", "to": "report"}],
    "missing": [],
}


async def _ask(args, owner="alice"):
    from src.tools.system import do_manage_tasks
    return await do_manage_tasks(json.dumps(args), owner=owner)


async def test_asked_to_run_one_task_after_another_the_agent_drafts_a_workflow(world, monkeypatch):
    w = world
    model = script_model(monkeypatch, TWO_RUN_TASKS)
    said = await _ask({"action": "draft_workflow",
                       "description": "Run my nightly backup and then email me the result"})
    assert said["exit_code"] == 0, said
    assert said["response"] == (
        "Drafted “Backup, then report” as a workflow of 2 steps, switched off. A person checks "
        "each step in the Workbench before it can run (Automations → “Backup, then report”), "
        "and switches it on there.")
    wf, graph, trigger = stored(w.factory, said["workflow_id"])
    assert trigger.id == said["task_id"] and trigger.status == "paused"
    assert [(n["kind"], n["config"]["task_id"]) for n in graph["nodes"]] == [
        ("run_task", "t-backup"), ("run_task", "t-report")]
    assert all(m["origin"] == "drafted" for m in marks_of(graph).values())
    palette = json.loads(next(m["content"] for m in model.calls[0]["messages"]
                              if "The palette" in m["content"]).split("as JSON:\n", 1)[1])
    assert sorted(t["name"] for t in palette["tasks"]) == ["Email me the result", "Nightly backup"]
    resumed = await _ask({"action": "resume", "task_id": trigger.id})
    assert resumed["exit_code"] == 1 and "nobody has checked yet" in resumed["error"]


async def test_a_draft_the_rule_refuses_is_told_to_the_agent_and_nothing_is_saved(world, monkeypatch):
    w = world
    theirs = json.loads(json.dumps(TWO_RUN_TASKS))
    theirs["steps"][1]["config"]["task_id"] = "t-bob"          # another owner's task
    script_model(monkeypatch, theirs, theirs)
    said = await _ask({"action": "draft_workflow", "description": "Back up, then run Bob's"})
    assert said["exit_code"] == 1
    assert said["error"].startswith("The model's draft could not be used: A step runs a task that "
                                    "is not one of yours")
    assert rows(w.factory, Workflow) == []


async def test_the_model_may_name_every_action_a_person_may_schedule(world):
    """`B800`. The enum is derived — `BUILTIN_ACTION_INFO` minus the four
    admin-only command actions — so it is the 14, `daily_brief` and
    `email_auto_translate` among them; and its `Verify:` — a daily brief every
    morning is a task the assistant can make."""
    import src.agent_tools  # noqa: F401 - tool_schemas is imported through it, as the app does
    from src.builtin_actions import BUILTIN_ACTION_INFO
    from src.task_action_policy import ADMIN_ONLY_TASK_ACTIONS
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    schema = next(s for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "manage_tasks")
    props = schema["function"]["parameters"]["properties"]
    enum = props["action_name"]["enum"]
    assert enum == [n for n in BUILTIN_ACTION_INFO if n not in ADMIN_ONLY_TASK_ACTIONS]
    assert len(enum) == 14 and {"daily_brief", "email_auto_translate"} <= set(enum)
    assert not set(enum) & set(ADMIN_ONLY_TASK_ACTIONS)
    assert "draft_workflow" in props["action"]["enum"] and "description" in props
    made = await _ask({"action": "create", "task_type": "action", "action_name": "daily_brief",
                       "name": "Morning brief", "schedule": "daily", "scheduled_time": "07:00"})
    assert made["exit_code"] == 0, made
    assert rows(world.factory, ScheduledTask, id=made["task_id"])[0].action == "daily_brief"


def test_the_schema_literal_still_reads_with_literal_eval():
    """`B21`: the parity test reads `FUNCTION_TOOL_SCHEMAS` with
    `ast.literal_eval`, so the enum is spliced in after the literal — which
    must still parse, with the enum left empty there."""
    source = (ROOT / "src" / "tool_schemas.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "FUNCTION_TOOL_SCHEMAS" for t in n.targets))
    schemas = ast.literal_eval(node.value)
    tasks = next(s for s in schemas if s["function"]["name"] == "manage_tasks")
    assert tasks["function"]["parameters"]["properties"]["action_name"]["enum"] == []


def test_drafting_a_workflow_is_a_private_write():
    import src.agent_tools  # noqa: F401
    from src.tool_capabilities import ToolEffect, capabilities_for_action
    caps = capabilities_for_action("manage_tasks", "draft_workflow")
    assert caps.known and ToolEffect.WRITE_PRIVATE in caps.effects
