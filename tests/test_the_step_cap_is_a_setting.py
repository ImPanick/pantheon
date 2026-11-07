# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1857` — how many steps one workflow may hold is a setting,
`workflow_max_steps` (100 as shipped, from 20 to 500). It was a constant,
`WORKFLOW_MAX_NODES = 20`, met by anyone building something n8n-shaped within
an afternoon, with nothing to move it.

  * one home for the number and its bounds (`workflow_runs`), read by the
    settings' defaults and both doors' ranges, the rule's `WorkflowResources`
    and the palette — the For-each cap's and the longest Wait's shape;
  * the save, the draft's door, a chain made a workflow and the run all refuse
    over the cap IN FORCE, naming it and the setting;
  * the rule's walks stay fast at the top of the range — the merge rule's pair
    check was a pass over every walker state per pair of arrows, which at 500
    steps did not finish in ten minutes.

Driven through the real routes, the real scheduler, the real settings
resolver (its store stood in, as `test_the_halves_are_one_product.py` does)
and a real SQLite file (`Law 20`).
"""

import time

import pytest

from core.database import ScheduledTask, TaskRun
import src.settings as S
from src import workflow_document as wd
from src import workflow_effects as we
from src import workflow_runs as wr
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, recording_scheduler, seed_workflow,
)

pytestmark = pytest.mark.asyncio

ALICE = {"x-test-user": "alice"}


def _cap_at(monkeypatch, value):
    real, real_explicit = S.get_setting, S.setting_is_explicit
    monkeypatch.setattr(S, "get_setting", lambda key, default=None:
                        value if key == "workflow_max_steps" else real(key, default))
    monkeypatch.setattr(S, "setting_is_explicit", lambda key:
                        key == "workflow_max_steps" or real_explicit(key))


def _chain(n, prefix="n"):
    nodes = [node(f"{prefix}{i}", f"Step {i}", "set", fields=[{"name": "a", "value": "1"}])
             for i in range(n)]
    return nodes, [arrow(f"{prefix}{i}", f"{prefix}{i + 1}") for i in range(n - 1)]


def _seed_chain(factory, n):
    """`n` tasks, each run after the one before (`then_task_id`), written last
    first so each arrow names a row that is already there."""
    db = factory()
    try:
        for i in reversed(range(n)):
            db.add(ScheduledTask(id=f"t{i}", owner="alice", name=f"Task {i}", task_type="llm",
                                 prompt="Say hi.", trigger_type="webhook", status="active",
                                 then_task_id=f"t{i + 1}" if i < n - 1 else None))
            db.flush()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def world(monkeypatch, tmp_path):
    factory = make_db(monkeypatch, tmp_path / "cap.db")
    s = recording_scheduler()
    return factory, s, app_for(factory, s, monkeypatch)


def test_the_number_and_its_bounds_have_one_home():
    assert (wr.MAX_STEPS_SETTING, wr.MAX_STEPS_DEFAULT, wr.MAX_STEPS_RANGE) == (
        "workflow_max_steps", 100, (20, 500))
    assert S.DEFAULT_SETTINGS["workflow_max_steps"] == wr.MAX_STEPS_DEFAULT
    assert S.int_setting_ranges()["workflow_max_steps"] == wr.MAX_STEPS_RANGE
    # The name contract C1 holds stays, and means the cap as shipped.
    assert wd.WORKFLOW_MAX_NODES == wr.MAX_STEPS_DEFAULT == wd.WorkflowResources().max_steps


def test_both_settings_doors_hold_it_to_its_bounds():
    assert S.clamp_int_setting("workflow_max_steps", 5) == 20
    assert S.clamp_int_setting("workflow_max_steps", 10_000) == 500
    assert S.clamp_int_setting("workflow_max_steps", "250") == 250


def test_a_cap_outside_the_bounds_cannot_reach_the_rule(monkeypatch):
    """However a `WorkflowResources` was built, the walks are never asked past
    what they were measured at, and never held under the old twenty."""
    assert wd.step_cap(wd.WorkflowResources(max_steps=5)) == 20
    assert wd.step_cap(wd.WorkflowResources(max_steps=10_000)) == 500
    assert wd.step_cap(wd.WorkflowResources(max_steps=True)) == 100
    _cap_at(monkeypatch, 3)
    assert wr.max_steps() == 20


async def test_the_setting_moves_the_save_the_palette_and_the_run(world, monkeypatch):
    factory, s, app = world
    nodes, edges = _chain(25)
    seed_workflow(factory, nodes[:1])
    graph = {"v": 1, "nodes": nodes, "edges": edges}
    async with client_for(app) as client:
        # As shipped, 25 steps save: twenty was the constant.
        res = await client.put("/api/workflows/w-wf", headers=ALICE,
                               json={"graph": graph, "base_version": 3})
        assert res.status_code == 200, res.text
        _cap_at(monkeypatch, 21)
        palette = await client.get("/api/workflows/palette", headers=ALICE)
        refused = await client.put("/api/workflows/w-wf?check=true", headers=ALICE,
                                   json={"graph": graph, "base_version": 4})
    assert palette.json()["limits"]["max_steps"] == 21
    assert refused.status_code == 400, refused.text
    body = refused.json()
    assert body["reason"] == "too_many_steps"
    assert body["detail"] == ("The workflow has more than 21 steps (the “workflow_max_steps” "
                              "setting): it has 25. Split it, or run part of it as its own task.")
    # The run reads the same setting, and says the same sentence.
    await s._execute_task("wf")
    db = factory()
    try:
        run = db.query(TaskRun).filter(TaskRun.task_id == "wf").first()
        assert run.status == "error" and body["detail"] in (run.result or "") + (run.error or "")
    finally:
        db.close()
    assert s.calls == []


async def test_a_chain_longer_than_twenty_becomes_a_workflow(world):
    factory, s, app = world
    _seed_chain(factory, 25)
    async with client_for(app) as client:
        res = await client.post("/api/workflows", headers=ALICE, json={"from_task_id": "t0"})
    assert res.status_code == 200, res.text
    assert len(res.json()["workflow"]["graph"]["nodes"]) == 25


async def test_a_chain_over_the_cap_in_force_is_refused_with_that_cap(world, monkeypatch):
    factory, s, app = world
    _seed_chain(factory, 25)
    _cap_at(monkeypatch, 20)
    async with client_for(app) as client:
        res = await client.post("/api/workflows", headers=ALICE, json={"from_task_id": "t0"})
    assert res.status_code == 400, res.text
    assert "more than 20 steps" in res.json()["detail"] and "it has 25" in res.json()["detail"]


def test_the_rule_answers_quickly_at_the_top_of_the_range():
    """498 branches from the start, every one into one Merge, then a last step:
    500 steps. The merge rule asked its pair check 124,000 times, each a pass
    over 250,000 walker states, and had not answered after ten minutes."""
    n = 500
    nodes = [node(f"n{i}", f"Branch {i}", "set", fields=[{"name": "a", "value": "1"}])
             for i in range(n - 2)]
    nodes += [node("m", "Meet", "merge", mode="all"), node("z", "Last", "set",
                                                             fields=[{"name": "a", "value": "1"}])]
    edges = [arrow("start", f"n{i}") for i in range(n - 2)]
    edges += [arrow(f"n{i}", "m") for i in range(n - 2)] + [arrow("m", "z")]
    graph = wd.parse_graph({"v": 1, "nodes": nodes, "edges": edges})
    started = time.monotonic()
    refusal = wd.validate_document(graph, owner=None, tasks_by_id={}, crew_ids=set(),
                                   owner_is_admin=True, own_task_id=None,
                                   resources=wd.WorkflowResources(max_steps=500))
    took = time.monotonic() - started
    assert refusal is None
    assert took < 30, f"{took:.1f}s"
    # And without the Merge, the same 498 meetings are found and refused.
    nodes[-2] = node("m", "Meet", "set", fields=[{"name": "a", "value": "1"}])
    graph = wd.parse_graph({"v": 1, "nodes": nodes, "edges": edges})
    refusal = wd.validate_document(graph, owner=None, tasks_by_id={}, crew_ids=set(),
                                   owner_is_admin=True, own_task_id=None,
                                   resources=wd.WorkflowResources(max_steps=500))
    assert refusal is not None and refusal.reason == wd.REFUSE_NEEDS_MERGE
    assert len(wd.concurrent_arrivals(graph)) == 498 * 497 // 2


def test_the_resources_the_save_and_the_run_read_carry_the_setting(monkeypatch):
    _cap_at(monkeypatch, 42)
    assert we.workflow_resources(None).max_steps == 42
