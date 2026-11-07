# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1877` — a first answer in words, not JSON, is asked again once.

`draft_workflow` gives a refused draft one repair round. A first answer that
is not a JSON object at all — what a small local model often gives the first
time ("Sure! I would make a workflow that …"), or a fence cut short — was
refused at once: the `why is not None` check ran before the repair.
**Measured on `5e4c8ec`** (the audit's probe, reproduced here): scripted a
prose answer and then a valid draft, the drafter answered 422 "The model's
draft could not be used: its answer was not a JSON object." after ONE model
call; the valid second answer was never asked for.

Now an answer in words is handed back with one sentence — "That was not a
JSON object. Answer again with only the whole draft, as one JSON object." —
and asked once more; that is the one repair round, so words twice is still a
422 and nothing is saved. A reasoning block in the first answer is not handed
back: it is the model's scratch, and it would only spend the window.

Real (`Law 20`): the Workbench's door (`POST /api/workflows {describe}`) and
the assistant's (`manage_tasks draft_workflow`) over a real SQLite file, the
drafter, the store, the rule; the model is `workflow_assist._complete`,
scripted.
"""

import json

import pytest

from core.database import Workflow
from tests.helpers.assist_harness import PERSON, build_world, rows, script_model, stored
from tests.helpers.walker_harness import client_for

pytestmark = pytest.mark.asyncio

GOOD = {
    "name": "Morning brief",
    "trigger": {"type": "schedule", "schedule": "daily", "time": "08:00"},
    "steps": [{"id": "sum", "kind": "llm", "label": "Summarise",
               "config": {"prompt": "Summarise what is on my plate today."}}],
    "arrows": [], "missing": [],
}
IN_WORDS = ("Sure! I would make a workflow that starts every day at 08:00 and then summarises "
            "what is on your plate. Let me know if you want changes.")
THINKING = "<think>The person wants a brief. I should plan the steps first.</think>\n"
AGAIN = ("That was not a JSON object. Answer again with only the whole draft, as one JSON "
         "object.")


@pytest.fixture()
def world(monkeypatch, tmp_path):
    return build_world(monkeypatch, tmp_path, name="again.db")


async def test_the_workbench_door_asks_again_and_the_second_answer_drafts(world, monkeypatch):
    model = script_model(monkeypatch, THINKING + IN_WORDS, GOOD)
    async with client_for(world.app) as client:
        res = await client.post("/api/workflows", headers=PERSON,
                                json={"describe": "Every morning at 8, brief me on my day."})
    assert res.status_code == 200, res.text
    assert len(model.calls) == 2
    first, second = model.calls
    assert second["messages"][:-2] == first["messages"], "the first ask is kept, word for word"
    assert second["messages"][-2:] == [{"role": "assistant", "content": IN_WORDS},
                                       {"role": "user", "content": AGAIN}]
    wf, graph, trigger = stored(world.factory, res.json()["workflow"]["id"])
    assert wf.name == "Morning brief" and trigger.status == "paused"
    assert [n["kind"] for n in graph["nodes"]] == ["llm"]


async def test_the_assistant_door_asks_again_too(world, monkeypatch):
    from src.tools.system import do_manage_tasks
    model = script_model(monkeypatch, "```json\n{\"name\": \"Morning br", GOOD)
    said = await do_manage_tasks(json.dumps({"action": "draft_workflow",
                                             "description": "Every morning at 8, brief me."}),
                                 owner="alice")
    assert said["exit_code"] == 0, said
    assert said["response"].startswith("Drafted “Morning brief” as a workflow of 1 step")
    assert len(model.calls) == 2


async def test_words_twice_is_refused_and_nothing_is_saved(world, monkeypatch):
    model = script_model(monkeypatch, IN_WORDS, IN_WORDS)
    async with client_for(world.app) as client:
        res = await client.post("/api/workflows", headers=PERSON,
                                json={"describe": "Every morning at 8, brief me on my day."})
    assert res.status_code == 422, res.text
    assert res.json()["detail"] == ("The model's draft could not be used: its answer was not a "
                                    "JSON object. Nothing was saved. Say it differently, or "
                                    "build it by hand.")
    assert len(model.calls) == 2, "one repair round, never a third ask"
    assert rows(world.factory, Workflow) == []


async def test_words_then_a_refused_draft_is_still_one_repair_round(world, monkeypatch):
    """The ask in words spent the round: a draft the rule refuses after it is
    a 422, not a third call."""
    theirs = json.loads(json.dumps(GOOD))
    theirs["steps"][0]["kind"] = "nonsense"
    model = script_model(monkeypatch, IN_WORDS, theirs)
    async with client_for(world.app) as client:
        res = await client.post("/api/workflows", headers=PERSON,
                                json={"describe": "Every morning at 8, brief me on my day."})
    assert res.status_code == 422, res.text
    assert res.json()["detail"].startswith("The model's draft could not be used: ")
    assert len(model.calls) == 2
    assert rows(world.factory, Workflow) == []
