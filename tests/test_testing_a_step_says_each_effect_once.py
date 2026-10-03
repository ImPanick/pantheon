# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1112` — *Test this step* says each effect once.

Measured by `integrate-d` (P22-18, `light-390-18-test-plan.png`) and again
here on `7a7f9b2`: the confirmation's plan read "It would: runs your code in
your own workstation account, not on this machine", and the effects list
under it said the same sentence again; an Action step said each of its
effects twice (`dry_run_plan`'s "It would: …" lines, then the list) — the
pattern predates wave D (P22-08). Both are written from one set of sentences
(`EFFECT_SENTENCES`, `CODE_EFFECT_SENTENCE`); the route sent both. The route
now lists only the effects the plan's own "It would: …" lines do not say
(`workflow_routes._effects_not_in`), and the plan stays the dry run's plan
(one planner, `Law 7`).

Driven (`Law 20`): the real `POST /api/workflows/{id}/nodes/{node_id}/test`
over the real rule, palette resources and planners, on a real SQLite file
(`walker_harness`); an Integration and an MCP server are what is listed.
"""
import pytest

from src.builtin_actions import EFFECT_SENTENCES
from src.workflow_document import CODE_EFFECT_SENTENCE
from tests.helpers.walker_harness import app_for, client_for, make_db, node, recording_scheduler, seed_workflow

pytestmark = pytest.mark.asyncio

POST = "mcp__chat__send_message"


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import src.agent_tools as agent_tools
    import src.integrations as integrations
    import src.workflow_effects as we
    from core.database import ScheduledTask

    factory = make_db(monkeypatch, tmp_path / "effects.db")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr(integrations, "load_integrations", lambda: [
        {"id": "int1", "name": "Miniflux", "enabled": True, "base_url": "http://miniflux.lan",
         "api_key": "k", "preset": "miniflux", "description": ""}])

    class Chat:
        def get_all_tools(self, disabled_map=None, overrides=None):
            return [{"qualified_name": POST, "server_name": "Chat", "name": "send_message",
                     "input_schema": {"properties": {"channel": {"type": "string"},
                                                     "text": {"type": "string"}}},
                     "is_disabled": False, "is_readonly": False}]

    monkeypatch.setattr(agent_tools, "get_mcp_manager", lambda: Chat(), raising=False)
    monkeypatch.setattr(we, "workstation_why", lambda owner: None)
    db = factory()
    db.add(ScheduledTask(id="brief", owner="root", name="Brief me", task_type="llm",
                         prompt="Brief me.", trigger_type="webhook", status="active"))
    db.commit()
    db.close()
    return factory, app_for(factory, recording_scheduler(), monkeypatch)


STEPS = {
    "code": node("code", "Total", "code", language="python",
                 source="print(1)", input=[]),
    "http": node("http", "Post it", "http", integration="int1", method="POST", path="/v1/entries",
                 body=[{"name": "text", "value": "hello"}], body_mode="json"),
    "mcp": node("mcp", "Post to #ops", "mcp", tool=POST, args={"channel": "#ops", "text": "hi"}),
    "tidy": node("tidy", "Tidy chats", "action", action="tidy_sessions"),
    "ssh": node("ssh", "Run it", "action", action="ssh_command", prompt="uptime"),
    "consolidate": node("consolidate", "Consolidate", "action", action="consolidate_memory"),
}


async def _confirm(world, step):
    factory, app = world
    seed_workflow(factory, [step], trigger_type="webhook", owner="root")
    async with client_for(app) as client:
        res = await client.post(f"/api/workflows/w-wf/nodes/{step['id']}/test",
                                headers={"x-test-user": "root"}, json={"node": step, "source": "none"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["outcome"] == "needs_confirmation", body
    return body


def _times(body, sentence):
    """How many places in the confirmation say `sentence`: plan lines and
    effect bullets, as the panel draws them one under the other."""
    return sum(sentence in str(x) for x in [*body["plan"], *body["effects"]])


@pytest.mark.parametrize("kind", sorted(STEPS))
async def test_every_effect_is_said_once(world, kind):
    from src.workflow_document import node_effects
    from src.workflow_effects import workflow_resources
    body = await _confirm(world, STEPS[kind])
    effects = node_effects(STEPS[kind], {}, workflow_resources("root"))
    assert effects, "a step that asks has effects to say"
    for effect in effects:
        sentence = CODE_EFFECT_SENTENCE if (kind == "code" and effect == "runs-code") \
            else EFFECT_SENTENCES[effect]
        assert _times(body, sentence) == 1, (kind, sentence, body["plan"], body["effects"])


async def test_the_plan_is_the_dry_runs_plan(world):
    """The fix is in what is listed beside the plan, never in the plan."""
    from src import workflow_document as wd
    from src.workflow_effects import workflow_resources
    body = await _confirm(world, STEPS["code"])
    assert body["plan"] == wd.plan_lines(STEPS["code"], workflow_resources("root"))
    assert f"It would: {CODE_EFFECT_SENTENCE}" in body["plan"] and body["effects"] == []


async def test_an_effect_the_plan_does_not_say_is_still_listed(world):
    """A Run task step's plan is "Would run the task …" and that task's own
    lines ("It would: call a model, and whatever …"); "calls a model" is not
    among them, so it stays in the list."""
    body = await _confirm(world, node("run", "Run the brief", "run_task", task_id="brief"))
    assert EFFECT_SENTENCES["calls-model"] in body["effects"]
    assert _times(body, EFFECT_SENTENCES["calls-model"]) == 1
