# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1858` — a run parked on a Wait keeps the version it started on, however
many times its workflow is saved while it waits.

A parked run resumes on the document it started with, read back from its kept
version (`workflow_store.graph_of_version`). The version policy keeps twenty
(`MAX_KEPT_VERSIONS`) and pruned the oldest with no regard for runs: measured
on the merged tree (the engine-triggers audit's t10), twenty-one ordinary
saves while a run waited, and the run woke to "version N is no longer kept"
and ended in error. A person's edits killed a run they had not touched.

Driven through the real save route (`PUT /api/workflows/{id}`), the real
scheduler's park and resume, and a real SQLite file (`Law 20`).
"""

import json

import pytest

from core.database import WorkflowVersion
from src import workflow_store as store
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, recording_scheduler, runs_of, seed_workflow,
    settle, skip_ahead,
)

pytestmark = pytest.mark.asyncio

WAIT = node("w", "Wait", "wait", mode="for", minutes=1)


def _graph(label):
    return {"v": 1, "start": {"position": None},
            "nodes": [WAIT, node("x", label, "action", action="tidy_sessions")],
            "edges": [arrow("w", "x")]}


def _kept(factory):
    db = factory()
    try:
        return sorted(v for (v,) in db.query(WorkflowVersion.version)
                      .filter(WorkflowVersion.workflow_id == "w-wf").all())
    finally:
        db.close()


@pytest.fixture()
def world(monkeypatch, tmp_path):
    factory = make_db(monkeypatch, tmp_path / "parked.db")
    first = _graph("Old step")
    seed_workflow(factory, first["nodes"], first["edges"], version=3)
    db = factory()
    db.add(WorkflowVersion(id="v3", workflow_id="w-wf", version=3, name="Morning digest",
                           graph=json.dumps(first), fingerprint="f3", source="user"))
    db.commit()
    db.close()
    s = recording_scheduler()
    return factory, s, app_for(factory, s, monkeypatch)


async def _save(client, label, base):
    res = await client.put("/api/workflows/w-wf", headers={"x-test-user": "alice"},
                           json={"graph": _graph(label), "base_version": base})
    assert res.status_code == 200, res.text
    return res.json()["workflow"]["version"]


async def test_twenty_one_saves_while_a_run_waits_do_not_take_its_version(world, monkeypatch):
    factory, s, app = world
    await s._execute_task("wf")
    assert runs_of(factory, "wf")[0]["status"] == "waiting"

    version = 3
    async with client_for(app) as client:
        for i in range(21):
            version = await _save(client, f"Edit {i}", version)
    assert version == 24
    kept = _kept(factory)
    # The twenty newest, and the one the parked run stands on beside them.
    assert kept == [3] + list(range(5, 25)), kept

    skip_ahead(monkeypatch, 61)
    await s._resume_due_waits()
    await settle(s)
    run = runs_of(factory, "wf")[0]
    assert run["status"] == "success", run
    assert [c["name"] for c in s.calls] == ["Morning digest · Old step"]

    # The run has ended: the next save prunes its version as the policy always has.
    async with client_for(app) as client:
        version = await _save(client, "Edit after", version)
    assert _kept(factory) == list(range(6, 26))


async def test_only_a_run_still_in_flight_holds_a_version(world):
    """`versions_held_by_runs`: queued, running or parked — never a run that has
    ended, never a dry plan, never another workflow's run."""
    factory, s, _app = world
    db = factory()
    try:
        wf = db.query(store._models()[2]).filter_by(id="w-wf").first()
        assert store.versions_held_by_runs(db, wf) == frozenset()
    finally:
        db.close()
    await s._execute_task("wf")
    db = factory()
    try:
        wf = db.query(store._models()[2]).filter_by(id="w-wf").first()
        assert store.versions_held_by_runs(db, wf) == frozenset({3})
        from core.database import TaskRun
        run = db.query(TaskRun).filter(TaskRun.task_id == "wf").first()
        run.status = "aborted"
        db.commit()
        assert store.versions_held_by_runs(db, wf) == frozenset()
    finally:
        db.close()
