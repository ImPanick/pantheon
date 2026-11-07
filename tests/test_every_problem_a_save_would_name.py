# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1851` — every problem at once.

Save's check (`PUT /api/workflows/{id}?check=true`) answers with the FIRST
refusal only — a save stops there — so the canvas could mark one broken step
and no other. `POST /api/workflows/{id}/problems {graph, name?}` answers
`{problems: [{node_ids, field, reason, sentence}], count, more}`: every refusal
a save of the draft would give, writing nothing.

What "every refusal a save would give" means, held here by asking the save
itself rather than by restating the rule:

  * the list's first problem IS `?check=true`'s refusal — same sentence, same
    reason, same steps, same field;
  * mend that one and `?check=true` names the list's second, and so on to
    the end, where `?check=true` passes — so the list is the save's own
    answers, in the save's own order, each step checked where it stands;
  * the whole is asked too: a loop, a step nothing leads to, an arrow to a
    step that is not there, two branches meeting outside a Merge, a reference
    to a step that does not run before;
  * empty when Save would pass; de-duplicated; at most fifty, the walk
    stopping there; owner-scoped (another owner's workflow is a 404).

Through the real router, the real store, the real engine and a real SQLite
file (`Law 20`).
"""

import copy
import json

import pytest

from core.database import Workflow, WorkflowVersion
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, recording_scheduler, seed_workflow,
)

pytestmark = pytest.mark.asyncio

ALICE = {"x-test-user": "alice"}
SAVED = [node("n1", "Fetch issue", "set", fields=[{"name": "title", "value": "x"}]),
         node("n2", "Summarise")]
SAVED_ARROWS = [arrow("n1", "n2")]


@pytest.fixture()
def world(monkeypatch, tmp_path):
    factory = make_db(monkeypatch, tmp_path / "problems.db")
    seed_workflow(factory, SAVED, SAVED_ARROWS)
    return factory, app_for(factory, recording_scheduler(), monkeypatch)


def _broken():
    """A draft with six things wrong, and how to mend each, in the order a
    save names them: three steps broken in place (an AI step with no prompt,
    an action this Pantheon does not have, a step reading from one that runs
    after it), an arrow to a step that is not there, an arrow drawn twice, a
    step nothing leads to, and two branches meeting outside a Merge."""
    nodes = [
        node("n1", "Fetch issue", "set", fields=[{"name": "title", "value": "x"}]),
        node("n2", "Summarise", "llm", prompt=""),
        node("n3", "Post it", "action", action="no_such_action"),
        node("n4", "Judge", "llm", prompt="Judge {{ steps.n5.data.result }}"),
        node("n5", "Report", "llm", prompt="Report."),
        node("n6", "Stray", "llm", prompt="Stray."),
    ]
    edges = [arrow("n1", "n2"), arrow("n2", "n3"), arrow("n3", "n4"), arrow("n4", "n5"),
             arrow("n5", "ghost"), arrow("n1", "n4"), arrow("n4", "n5")]
    return {"v": 1, "nodes": nodes, "edges": edges}


def _step(g, node_id):
    return next(n for n in g["nodes"] if n["id"] == node_id)


def _mend_prompt(g):
    _step(g, "n2")["config"]["prompt"] = "Do Summarise."


def _mend_action(g):
    step = _step(g, "n3")
    step["kind"], step["config"] = "llm", {"prompt": "Post it."}


def _mend_ghost(g):
    g["edges"] = [e for e in g["edges"] if e["to"] != "ghost"]


def _mend_twice(g):
    g["edges"] = g["edges"][:-1]


def _mend_stray(g):
    g["edges"].append(arrow("n5", "n6"))


def _mend_merge(g):
    g["edges"] = [e for e in g["edges"] if (e["from"], e["to"]) != ("n1", "n4")]


def _mend_reference(g):
    _step(g, "n4")["config"]["prompt"] = "Judge it."


# (reason, steps, field) of each problem, in the save's order, and its mend.
EXPECTED = [
    ("missing_setting", ["n2"], _mend_prompt),
    ("unknown_action", ["n3"], _mend_action),
    ("bad_edge", ["n5"], _mend_ghost),
    ("two_arrows", ["n4"], _mend_twice),
    ("several_starts", ["n1", "n6"], _mend_stray),
    ("needs_merge", ["n4", "n3", "n1"], _mend_merge),
    ("not_upstream", ["n4"], _mend_reference),
]


def _as_problem(refused):
    """`?check=true`'s refusal, in a problem's shape."""
    body = refused.json()
    return {"node_ids": body.get("node_ids") or [], "field": body.get("field") or None,
            "reason": body.get("reason"), "sentence": body["detail"]}


async def test_every_broken_step_and_the_whole_are_named_at_once(world):
    factory, app = world
    draft = _broken()
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                json={"graph": draft})
        assert res.status_code == 200, res.text
        answer = res.json()
        problems = answer["problems"]
        assert [(p["reason"], p["node_ids"]) for p in problems] == [
            (reason, ids) for reason, ids, _ in EXPECTED]
        assert answer["count"] == len(EXPECTED) and answer["more"] is False
        # Each sentence names its step, and a reference is put on its field.
        assert "“Summarise”" in problems[0]["sentence"]
        assert "“Post it”" in problems[1]["sentence"]
        assert problems[-1]["field"] == "prompt" and "“Report”" in problems[-1]["sentence"]
        assert all(set(p) == {"node_ids", "field", "reason", "sentence"} for p in problems)

        # The list is the save's own answers in the save's own order: mend the
        # one `?check=true` names, and it names the next one on the list.
        for i, (_, _, mend) in enumerate(EXPECTED):
            check = await client.put("/api/workflows/w-wf?check=true", headers=ALICE,
                                     json={"graph": draft, "base_version": 3})
            assert check.status_code == 400, (i, check.text)
            assert _as_problem(check) == problems[i], i
            mend(draft)
        check = await client.put("/api/workflows/w-wf?check=true", headers=ALICE,
                                 json={"graph": draft, "base_version": 3})
        mended = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                   json={"graph": draft})
    assert check.status_code == 200 and check.json() == {"ok": True, "check": True}
    assert mended.json() == {"problems": [], "count": 0, "more": False}


async def test_a_loop_is_named_beside_the_steps_broken_in_it(world):
    factory, app = world
    draft = {"v": 1, "nodes": [node("a", "Ask"), node("b", "Blank", "llm", prompt=""),
                               node("c", "Check")],
             "edges": [arrow("a", "b"), arrow("b", "c"), arrow("c", "b")]}
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                json={"graph": draft})
        mended = copy.deepcopy(draft)
        _step(mended, "b")["config"]["prompt"] = "Do Blank."
        loop = await client.put("/api/workflows/w-wf?check=true", headers=ALICE,
                                json={"graph": mended, "base_version": 3})
    problems = res.json()["problems"]
    assert [p["reason"] for p in problems] == ["missing_setting", "cycle"]
    assert problems[0]["node_ids"] == ["b"]
    assert loop.status_code == 400 and _as_problem(loop) == problems[1]
    assert set(problems[1]["node_ids"]) == {"b", "c"}


async def test_a_draft_save_would_pass_has_no_problems(world):
    factory, app = world
    stored = {"v": 1, "nodes": SAVED, "edges": SAVED_ARROWS}
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                json={"graph": stored, "name": "Morning digest"})
        as_text = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                    json={"graph": json.dumps(stored)})
        check = await client.put("/api/workflows/w-wf?check=true", headers=ALICE,
                                 json={"graph": stored, "name": "Morning digest",
                                       "base_version": 3})
    assert check.status_code == 200
    assert res.status_code == 200 and res.json() == {"problems": [], "count": 0, "more": False}
    assert as_text.json() == res.json()


async def test_the_same_problem_twice_is_named_once(world):
    factory, app = world
    draft = {"v": 1, "nodes": SAVED,
             "edges": SAVED_ARROWS + [arrow("n2", "ghost"), arrow("n2", "ghost")]}
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                json={"graph": draft})
    problems = res.json()["problems"]
    assert [(p["reason"], p["node_ids"]) for p in problems] == [("bad_edge", ["n2"])]
    assert res.json()["count"] == 1


async def test_the_name_and_the_start_are_problems_too(world):
    factory, app = world
    draft = {"v": 1, "nodes": SAVED, "edges": SAVED_ARROWS}
    async with client_for(app) as client:
        blank = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                  json={"graph": _broken(), "name": "   "})
        named_check = await client.put("/api/workflows/w-wf?check=true", headers=ALICE,
                                       json={"graph": draft, "name": "   ", "base_version": 3})
        db = factory()
        db.query(Workflow).filter(Workflow.id == "w-wf").update({"task_id": None})
        db.commit()
        db.close()
        lost = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                 json={"graph": draft})
        lost_check = await client.put("/api/workflows/w-wf?check=true", headers=ALICE,
                                      json={"graph": draft, "base_version": 3})
    first, *rest = blank.json()["problems"]
    # The name, as a save says it — about no step, on the name's own box — and
    # every problem of the document after it, still listed.
    assert first == {"node_ids": [], "field": "name", "reason": None,
                     "sentence": named_check.json()["detail"]}
    assert first["sentence"] == "A workflow needs a name."
    assert [p["reason"] for p in rest] == [reason for reason, _, _ in EXPECTED]
    # A workflow that has lost the task that starts it: the save's first answer.
    assert lost_check.status_code == 400
    assert lost.json()["problems"] == [{"node_ids": [], "field": None, "reason": None,
                                        "sentence": lost_check.json()["detail"]}]


async def test_what_is_not_a_document_is_its_one_problem(world):
    factory, app = world
    unreadable = {"v": 1, "nodes": [{"id": "n1", "kind": "llm", "label": "A",
                                     "config": "not settings"}], "edges": []}
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                json={"graph": unreadable})
        check = await client.put("/api/workflows/w-wf?check=true", headers=ALICE,
                                 json={"graph": unreadable, "base_version": 3})
        nothing = await client.post("/api/workflows/w-wf/problems", headers=ALICE, json={})
        listed = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                   json={"graph": ["n1"]})
        bob = await client.post("/api/workflows/w-wf/problems", headers={"x-test-user": "bob"},
                                json={"graph": _broken()})
        missing = await client.post("/api/workflows/w-nope/problems", headers=ALICE,
                                    json={"graph": _broken()})
    assert check.status_code == 400
    assert res.status_code == 200 and res.json()["problems"] == [_as_problem(check)]
    for refused in (nothing, listed):
        assert refused.status_code == 400
        assert refused.json()["detail"] == "Send the draft as it stands on the canvas (graph)."
    for refused in (bob, missing):
        assert refused.status_code == 404 and refused.json()["detail"] == "No such workflow."


async def test_it_stops_after_fifty_and_writes_nothing(world, monkeypatch):
    factory, app = world
    import src.workflow_document as wd
    asked = []
    real_loop = wd.find_loop
    monkeypatch.setattr(wd, "find_loop", lambda g: asked.append(g) or real_loop(g))
    many = [node(f"s{i}", f"Step {i}", "llm", prompt="") for i in range(1, 61)]
    draft = {"v": 1, "nodes": many,
             "edges": [arrow(f"s{i}", f"s{i + 1}") for i in range(1, 60)]}
    db = factory()
    before = (db.query(Workflow).first().graph, db.query(Workflow).first().version,
              db.query(WorkflowVersion).count())
    db.close()
    async with client_for(app) as client:
        res = await client.post("/api/workflows/w-wf/problems", headers=ALICE,
                                json={"graph": draft, "name": "Sixty steps"})
    answer = res.json()
    assert res.status_code == 200 and answer["count"] == 50 and answer["more"] is True
    assert [p["node_ids"] for p in answer["problems"]] == [[f"s{i}"] for i in range(1, 51)]
    # The walk stopped there: the whole document was never walked.
    assert asked == []
    db = factory()
    assert (db.query(Workflow).first().graph, db.query(Workflow).first().version,
            db.query(WorkflowVersion).count()) == before
    db.close()
