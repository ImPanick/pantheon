# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1850` — *Insert a field…* on a step that exists only in the draft.

`GET /api/workflows/{id}/nodes/{node_id}/fields` reads only the stored
document, so the picker refused a step the person had just drawn, and they had
to save a throwaway version first — which Save refused while that step was
still incomplete. `POST /api/workflows/{id}/fields {node_id, graph}` answers
the same shape for the draft on the canvas:

  * the arrows, and what each step promises (an AI step's answer fields, a Set
    step's names), are the draft's;
  * the last run's records and the pinned samples come only from steps the
    saved document also has — a record is kept by step id, and a pin by its
    own door, so a draft can neither borrow a deleted step's record under its
    id nor bring a pin of its own;
  * the draft is never checked as a save is: only "is this a draft at all";
  * owner-scoped (another owner's workflow is a 404), and nothing is written.

Through the real router over the real scheduler, the real `available_fields`,
the real step records and a real SQLite file (`Law 20`).
"""

import pytest

from core.database import TaskRun, Workflow
from src.workflow_runs import record_node_end, record_node_start
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, recording_scheduler, seed_workflow,
)

pytestmark = pytest.mark.asyncio

ALICE = {"x-test-user": "alice"}
PIN = {"source": "task", "event": "Fetch issue", "at": "2026-11-01T07:00:00Z",
       "data": {"task": "Fetch issue", "result": "Pinned text", "data": {"title": "Pinned title"}}}

FETCH = node("n1", "Fetch issue", "set", fields=[{"name": "title", "value": "x"}])
SUM = dict(node("n2", "Summarise"), pinned=PIN)


def _draft(*, wired=True):
    """The saved two steps, and three only the draft has: a judge whose answer
    fields are new, an AI step not written yet (no prompt: Save refuses it), and
    a step drawn under the id of one deleted long ago."""
    judge = node("n3", "Judge", "llm", prompt="Judge it.",
                 answer_fields=[{"name": "verdict", "type": "text"}])
    unfinished = dict(node("n4", "Write it up", "llm", prompt=""),
                      pinned={"data": {"result": "a pin the draft carried", "data": {"x": 1}}})
    reborn = node("gone", "Reborn", "set", fields=[{"name": "fresh", "value": "y"}])
    edges = [arrow("n2", "n3"), arrow("n3", "n4"), arrow("gone", "n4")]
    if wired:
        edges.insert(0, arrow("n1", "n2"))
    return {"v": 1, "nodes": [FETCH, {k: v for k, v in SUM.items() if k != "pinned"},
                              judge, unfinished, reborn], "edges": edges}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    factory = make_db(monkeypatch, tmp_path / "draft-fields.db")
    seed_workflow(factory, [FETCH, SUM], [arrow("n1", "n2")])
    db = factory()
    try:
        db.add(TaskRun(id="run-1", task_id="wf", status="success"))
        db.commit()
        for seq, (step, data) in enumerate(((FETCH, {"title": "From the last run"}),
                                            (node("gone", "Deleted long ago", "set"),
                                             {"secret": "what another step made"})), start=1):
            rec = record_node_start(db, run_id="run-1", node=step, seq=seq, input_envelope=None,
                                    workflow_version=2)
            record_node_end(db, rec, status="success", text="done", data=data, port="success")
    finally:
        db.close()
    return factory, app_for(factory, recording_scheduler(), monkeypatch)


def _by(sources, node_id, origin):
    found = [s for s in sources if s["node_id"] == node_id and s["origin"] == origin]
    return found[0] if found else None


def _refs(source):
    return {f["ref"]: f["example"] for f in (source or {}).get("fields") or ()}


async def test_a_step_only_the_draft_has_is_offered_what_came_before_it(world):
    factory, app = world
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/fields", headers=ALICE,
                                json={"node_id": "n4", "graph": _draft()})
        # The door it replaces: the stored document has no n4.
        stored = await client.get("/api/workflows/w-wf/nodes/n4/fields", headers=ALICE)
        # And the draft is one Save refuses (n4 has no prompt yet).
        check = await client.put("/api/workflows/w-wf?check=true", headers=ALICE,
                                 json={"graph": _draft(), "base_version": 3})
    assert stored.status_code == 404
    assert check.status_code == 400, check.text
    assert res.status_code == 200, res.text
    sources = res.json()["sources"]
    # (`n2` runs before it too, and has nothing to offer yet: no answer fields,
    # no record, no pin on the step after it.)
    assert {s["node_id"] for s in sources} == {"n1", "n3", "gone"}

    # A saved step: its last run's record, and the pin on the step it leads to.
    assert _refs(_by(sources, "n1", "last_run"))["{{ steps.n1.data.title }}"] == "From the last run"
    assert _refs(_by(sources, "n1", "pin"))["{{ steps.n1.data.title }}"] == "Pinned title"
    assert "{{ steps.n1.data.title }}" in _refs(_by(sources, "n1", "declared"))
    # A step only the draft has: what it promises, from the draft's own settings.
    assert list(_refs(_by(sources, "n3", "declared"))) == ["{{ steps.n3.data.verdict }}"]
    # Drawn under a deleted step's id: its own promise, never that step's record.
    assert list(_refs(_by(sources, "gone", "declared"))) == ["{{ steps.gone.data.fresh }}"]
    assert _by(sources, "gone", "last_run") is None
    # Nothing the draft carried as a pin is read: pins have their own door.
    assert not any(s["origin"] == "pin" and s["node_id"] == "n3" for s in sources)


async def test_the_drafts_arrows_decide_what_runs_before_the_step(world):
    factory, app = world
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/fields", headers=ALICE,
                                json={"node_id": "n4", "graph": _draft(wired=False)})
    assert res.status_code == 200, res.text
    # The arrow n1 → n2 is gone in the draft, so n1 no longer runs before n4.
    assert {s["node_id"] for s in res.json()["sources"]} == {"n3", "gone"}


async def test_it_reads_the_saved_steps_records_and_writes_nothing(world):
    factory, app = world
    db = factory()
    before = db.query(Workflow).first().graph, db.query(Workflow).first().version
    db.close()
    async with client_for(app) as client:
        same = await client.post("/api/workflows/w-wf/fields", headers=ALICE,
                                 json={"node_id": "n2", "graph": _draft()})
        old = await client.get("/api/workflows/w-wf/nodes/n2/fields", headers=ALICE)
    # For a step the saved document has, on the saved arrows: the GET's answer.
    assert same.status_code == 200 and same.json() == old.json()
    db = factory()
    assert (db.query(Workflow).first().graph, db.query(Workflow).first().version) == before
    db.close()


async def test_what_is_not_a_draft_is_refused_in_a_sentence(world):
    factory, app = world
    junk = dict(_draft(), nodes=_draft()["nodes"] + [{"kind": "llm"}, "nope", {"id": 7}],
                edges=_draft()["edges"] + [{"from": "n1"}, 3])
    async with client_for(app) as client:
        no_step = await client.post("/api/workflows/w-wf/fields", headers=ALICE,
                                    json={"graph": _draft()})
        not_object = await client.post("/api/workflows/w-wf/fields", headers=ALICE,
                                       json={"node_id": "n4", "graph": ["n1"]})
        not_lists = await client.post("/api/workflows/w-wf/fields", headers=ALICE,
                                      json={"node_id": "n4", "graph": {"nodes": {"n4": {}}}})
        missing = await client.post("/api/workflows/w-wf/fields", headers=ALICE,
                                    json={"node_id": "zz", "graph": _draft()})
        bob = await client.post("/api/workflows/w-wf/fields", headers={"x-test-user": "bob"},
                                json={"node_id": "n4", "graph": _draft()})
        rough = await client.post("/api/workflows/w-wf/fields", headers=ALICE,
                                  json={"node_id": "n4", "graph": junk})
    assert no_step.status_code == 400
    assert no_step.json()["detail"] == "Say which step's fields to list (node_id)."
    for res in (not_object, not_lists):
        assert res.status_code == 400
        assert res.json()["detail"] == ("Send the draft as it stands on the canvas (graph): an "
                                        "object whose steps (nodes) and arrows (edges) are lists.")
    assert missing.status_code == 404 and missing.json()["detail"] == "No such step in this draft."
    assert bob.status_code == 404 and bob.json()["detail"] == "No such workflow."
    # Entries no reference could point at are passed over, not refused.
    assert rough.status_code == 200, rough.text
    assert {s["node_id"] for s in rough.json()["sources"]} == {"n1", "n3", "gone"}
