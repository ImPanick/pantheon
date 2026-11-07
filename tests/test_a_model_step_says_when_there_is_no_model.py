# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1891` — with no model, a step a model drives says so before it fails.

The audit (`model-steps-not-gated`, live on a server with no model): the
palette offered Prompt and Research as available while HTTP and Code beside
them were greyed with a reason; the dry run said "Model: the default."; the
switch said "Switched on."; and every run then failed with *No model yet.*
The New-workflow form offered *Draft it* and six example sentences, every one
of which the server refused (503).

Now, with no model:
  * the palette greys Prompt, Research and Skill with the run's own sentence,
    worded as the other greyed kinds are, and says `has_model: false` with
    that sentence as `model_why`; and says the drafter has no model
    (`drafter_model: null`) with the draft route's own refusal as
    `drafter_why`;
  * the dry run of such a step ends "It would not run: No model yet. An admin
    adds one in Settings → Added Models.";
  * switching on goes ahead (a note, not a refusal) and says which steps need
    a model.
With a model, none of that is said.

Driven (`Law 20`): the real palette route, the real scheduler's dry run and
the real switch route over a real SQLite file (`walker_harness`, whose world
registers one endpoint — taken away here to make "no model").
"""

import pytest

from core.database import ModelEndpoint
from src.endpoint_resolver import NO_MODEL_FOR_RUN
from src.workflow_assist import NO_MODEL_TO_DRAFT
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, recording_scheduler, seed_workflow,
)

PERSON = {"x-test-user": "alice"}
WOULD_NOT_RUN = f"It would not run: {NO_MODEL_FOR_RUN}"


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "no-model.db")


def no_model_anywhere(factory):
    """The world's one endpoint taken away: nobody has a model."""
    db = factory()
    try:
        db.query(ModelEndpoint).delete()
        db.commit()
    finally:
        db.close()


async def _palette(factory, monkeypatch):
    app = app_for(factory, recording_scheduler(), monkeypatch)
    async with client_for(app) as client:
        res = await client.get("/api/workflows/palette", headers=PERSON)
    assert res.status_code == 200, res.text
    return res.json()


def _kinds(palette):
    return {k["kind"]: k for k in palette["kinds"]}


async def test_with_no_model_the_steps_a_model_drives_are_greyed_with_the_runs_sentence(
        factory, monkeypatch):
    no_model_anywhere(factory)
    palette = await _palette(factory, monkeypatch)
    kinds = _kinds(palette)
    for kind in ("llm", "research", "skill"):
        assert (kinds[kind]["available"], kinds[kind]["why"]) == (False, NO_MODEL_FOR_RUN), kind
    # The kinds that call no model are offered as before.
    for kind in ("if", "switch", "set", "merge", "wait", "foreach"):
        assert kinds[kind]["available"] is True, kind
    assert (palette["has_model"], palette["model_why"]) == (False, NO_MODEL_FOR_RUN)
    assert NO_MODEL_FOR_RUN == "No model yet. An admin adds one in Settings → Added Models."
    # Drafting: no model, and the sentence the draft route refuses with.
    assert (palette["drafter_model"], palette["drafter_why"]) == (None, NO_MODEL_TO_DRAFT)


async def test_with_a_model_they_are_offered_and_the_drafter_names_its_model(
        factory, monkeypatch):
    from src import workflow_assist
    monkeypatch.setattr(workflow_assist, "_endpoint",
                        lambda owner: ("http://127.0.0.1:9/v1/chat/completions", "scripted", {}))
    palette = await _palette(factory, monkeypatch)
    kinds = _kinds(palette)
    assert kinds["llm"]["available"] is True and kinds["research"]["available"] is True
    assert kinds["llm"]["why"] == ""
    assert (palette["has_model"], palette["model_why"]) == (True, "")
    assert (palette["drafter_model"], palette["drafter_why"]) == ("scripted", "")


async def _dry_plan(factory, scheduler):
    from src import workflow_runs as wr
    run_id = await scheduler.run_task_now("wf", dry=True)
    db = factory()
    try:
        entries = wr.dry_node_entries(db, run_id)
    finally:
        db.close()
    return {e["node_id"]: [st["detail"] for st in e["steps"]] for e in entries}


def _a_workflow_with_a_model_step(factory, **task_kw):
    seed_workflow(factory, [node("sum", "Summarise"),
                            node("tag", "Tag it", "set", fields=[{"name": "x", "value": "1"}]),
                            node("look", "Look it up", "research", prompt="What changed?")],
                  [arrow("start", "sum"), arrow("sum", "tag"), arrow("tag", "look")], **task_kw)


async def test_the_dry_run_says_a_model_step_would_not_run_without_a_model(factory):
    _a_workflow_with_a_model_step(factory)
    no_model_anywhere(factory)
    plan = await _dry_plan(factory, recording_scheduler())
    assert plan["sum"][-1] == WOULD_NOT_RUN, plan["sum"]
    assert plan["look"][-1] == WOULD_NOT_RUN, plan["look"]
    assert not any(line.startswith("It would not run") for line in plan["tag"]), plan["tag"]


async def test_the_dry_run_says_nothing_more_when_a_model_is_there(factory, monkeypatch):
    _a_workflow_with_a_model_step(factory)
    s = recording_scheduler()
    # The configured chain answers the world's endpoint and a model it lists.
    monkeypatch.setattr(s, "_resolve_defaults",
                        lambda db, owner: ("http://127.0.0.1:9/v1", "scripted"))
    plan = await _dry_plan(factory, s)
    for step in ("sum", "tag", "look"):
        assert not any(line.startswith("It would not run") for line in plan[step]), plan[step]


async def test_the_dry_run_names_a_model_its_endpoint_no_longer_lists(factory):
    seed_workflow(factory, [node("sum", "Summarise", model="gone-model",
                                 endpoint_url="http://127.0.0.1:9/v1")],
                  [arrow("start", "sum")])
    plan = await _dry_plan(factory, recording_scheduler())
    last = plan["sum"][-1]
    assert last.startswith("It would not run: ") and "gone-model" in last, plan["sum"]


async def _switch_on(factory, monkeypatch):
    app = app_for(factory, recording_scheduler(), monkeypatch)
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/switch", headers=PERSON, json={"on": True})
    assert res.status_code == 200, res.text
    return res.json()


async def test_switching_on_with_no_model_goes_ahead_and_says_which_steps_need_one(
        factory, monkeypatch):
    _a_workflow_with_a_model_step(factory, status="paused")
    no_model_anywhere(factory)
    body = await _switch_on(factory, monkeypatch)
    assert body["workflow"]["trigger_status"] == "active", "a note, never a refusal"
    assert (f"“Summarise” and “Look it up” need a model. {NO_MODEL_FOR_RUN}"
            in body["notes"]), body["notes"]


async def test_switching_on_with_a_model_says_nothing_about_one(factory, monkeypatch):
    _a_workflow_with_a_model_step(factory, status="paused")
    body = await _switch_on(factory, monkeypatch)
    assert not any("need" in n and "model" in n for n in body["notes"]), body["notes"]


async def test_a_workflow_with_no_model_step_is_switched_on_without_a_word_about_models(
        factory, monkeypatch):
    seed_workflow(factory, [node("tag", "Tag it", "set", fields=[{"name": "x", "value": "1"}]),
                            node("off", "Not today", "llm", prompt="Hi")],
                  [arrow("start", "tag"), arrow("tag", "off")], status="paused")
    db = factory()
    try:
        # `B1856`: a step switched off runs nothing, so it needs no model.
        import json
        from core.database import Workflow
        wf = db.query(Workflow).filter(Workflow.task_id == "wf").first()
        graph = json.loads(wf.graph)
        graph["nodes"][1]["disabled"] = True
        wf.graph = json.dumps(graph)
        db.commit()
    finally:
        db.close()
    no_model_anywhere(factory)
    body = await _switch_on(factory, monkeypatch)
    assert not any("model" in n for n in body["notes"]), body["notes"]


def test_the_note_names_one_two_or_three_steps():
    from src.workflow_store import needs_a_model
    a, b, c = ({"label": n} for n in ("A", "B", "C"))
    assert needs_a_model([a]) == "“A” needs a model."
    assert needs_a_model([a, b]) == "“A” and “B” need a model."
    assert needs_a_model([a, b, c]) == "“A”, “B” and “C” need a model."
