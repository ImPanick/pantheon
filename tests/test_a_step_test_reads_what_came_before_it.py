# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1887` (`test-input-replaces-start`) and `B1888` (`test-custom-input-ignored`)
— *Test this step* reads what the steps before it made, the start stays the
trigger, and what you type can be what they made.

Measured before the fix, on the real route:

  * a pin on a step after another resolved to nothing in its test: Set b,
    reading `{{ steps.a.data.title }}` (the reference the picker offers "from
    the pinned sample"), tested with the pin answered "Not found, so left
    empty: {{ steps.a.data.title }}" — the pin was readable only as
    `{{ steps.start.data.data.title }}`, which is wrong in a real run;
  * a later step reading the trigger (`{{ steps.start.data.json.issues[0].
    title }}`) was left empty in every test — with *What it was handed in the
    last run* and with *Nothing* — although the real run read "First";
  * an If after "Make greeting" tested on the typed `{"greeting": "goodbye"}`
    went the "then" way whatever was typed, with "Left out, because this step
    is not handed them: greeting." — the sample was cut to the hand-off's own
    fields and the reference still read the last run;
  * a For-each could not be tested before a full run.

Driven through the real route (`POST /api/workflows/{id}/nodes/{node_id}/test`)
on the real `TaskScheduler`, a real SQLite file and real runs
(`tests/helpers/walker_harness.py`).
"""

import json

import pytest

from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, recording_scheduler, runs_of, seed_workflow,
)

ALICE = {"x-test-user": "alice"}
WF = "w-wf"


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "step-test.db")


async def _test(client, step, **body):
    res = await client.post(f"/api/workflows/{WF}/nodes/{step['id']}/test",
                            json=dict({"node": step}, **body), headers=ALICE)
    return res


def _pin(factory, node_id, pinned):
    from core.database import Workflow

    db = factory()
    try:
        wf = db.query(Workflow).filter(Workflow.id == WF).first()
        graph = json.loads(wf.graph)
        for n in graph["nodes"]:
            if n["id"] == node_id:
                n["pinned"] = pinned
        wf.graph = json.dumps(graph)
        db.commit()
    finally:
        db.close()


# ── B1887 · a pin on a later step reads as what the step before it made ─────

@pytest.mark.asyncio
async def test_a_pinned_sample_on_a_later_step_is_what_its_parent_made(factory, monkeypatch):
    a = node("a", "Make it", "set", fields=[{"name": "title", "value": "Real title"}])
    b = node("b", "Use it", "set", fields=[{"name": "t", "value": "{{ steps.a.data.title }}"},
                                         {"name": "s", "value": "{{ steps.a.text }}"}])
    seed_workflow(factory, [a, b], [arrow("start", "a"), arrow("a", "b")])
    _pin(factory, "b", {"source": "task", "event": "Make it", "at": "2026-11-07T08:00:00Z",
                        "data": {"task": "Make it", "result": "Pinned text",
                                 "data": {"title": "Pinned title"}}})
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        res = await _test(client, b, source="pinned")
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["outcome"] == "ran" and out["status"] == "success", out
    assert out["data"] == {"t": "Pinned title", "s": "Pinned text"}, out["text"]
    [read] = out["reads"]
    assert read["node_id"] == "a" and read["origin"] == "handed"
    assert read["data"] == {"title": "Pinned title"} and read["label"] == "Make it"


# ── B1887 · the start stays the trigger for a later step ────────────────────

@pytest.mark.asyncio
async def test_a_later_step_reads_the_trigger_its_last_run_had(factory, monkeypatch):
    nodes = [
        node("a", "Read", "set", fields=[{"name": "n", "value": "{{ steps.start.data.json.n }}"}]),
        node("c", "First title", "set", fields=[
            {"name": "first", "value": "{{ steps.start.data.json.issues[0].title }}"},
            {"name": "n", "value": "{{ steps.a.data.n }}"}]),
    ]
    seed_workflow(factory, nodes, [arrow("start", "a"), arrow("a", "c")], trigger_type="webhook")
    s = recording_scheduler()
    await s._execute_task("wf", trigger=build_trigger(
        TRIGGER_SOURCE_WEBHOOK, "webhook",
        {"json": {"n": 7, "issues": [{"title": "First"}, {"title": "Second"}]}},
        fields=WEBHOOK_PAYLOAD_FIELDS))
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        last = (await _test(client, nodes[1], source="last")).json()
        none = (await _test(client, nodes[1], source="none")).json()
    assert last["data"] == {"first": "First", "n": 7}, last
    assert none["data"] == {"first": "First", "n": 7}, "the newest run's trigger, with nothing chosen"
    origins = {r["node_id"]: r["origin"] for r in last["reads"]}
    assert origins == {"start": "last_run", "a": "handed"}
    assert {r["node_id"]: r["origin"] for r in none["reads"]} == {"start": "last_run", "a": "last_run"}


@pytest.mark.asyncio
async def test_the_first_step_is_still_handed_the_chosen_input_as_the_start(factory, monkeypatch):
    first = node("a", "Read", "set", fields=[{"name": "n", "value": "{{ steps.start.data.json.n }}"}])
    seed_workflow(factory, [first], [arrow("start", "a")], trigger_type="webhook")
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        out = (await _test(client, first, source="custom", input={"json": {"n": 3}})).json()
    assert out["data"] == {"n": 3} and out["reads"][0]["origin"] == "handed"


# ── B1888 · what you type is what the step before it made ──────────────────

def _greeting_then_if():
    make = node("make-greeting", "Make greeting", "set", fields=[
        {"name": "greeting", "value": "hello world"}])
    says = node("says-hello", "Says hello?", "if", join="all", conditions=[
        {"left": "{{ steps.make-greeting.data.greeting }}", "op": "equals", "right": "hello world"}])
    return make, says


@pytest.mark.asyncio
async def test_testing_an_if_on_a_typed_value_goes_the_way_that_value_goes(factory, monkeypatch):
    make, says = _greeting_then_if()
    seed_workflow(factory, [make, says], [arrow("start", "make-greeting"),
                                          arrow("make-greeting", "says-hello")])
    s = recording_scheduler()
    await s._execute_task("wf")        # a real run: the last run said "hello world"
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        typed = (await _test(client, says, source="custom", input='{"greeting": "goodbye"}')).json()
        same = (await _test(client, says, source="custom", input={"greeting": "hello world"})).json()
        last = (await _test(client, says, source="last")).json()
    assert typed["port"] == "otherwise" and typed["dropped"] == [], typed
    assert typed["data"] == {"greeting": "goodbye", "port": "otherwise"}, "it hands on what it was handed"
    assert typed["input_used"]["data"]["data"] == {"greeting": "goodbye"}
    assert typed["reads"] == [{"node_id": "make-greeting", "label": "Make greeting", "origin": "handed",
                               "data": {"greeting": "goodbye"}, "text": ""}]
    assert same["port"] == "then" and last["port"] == "then"


@pytest.mark.asyncio
async def test_a_hand_off_typed_in_its_own_fields_is_read_as_it_always_was(factory, monkeypatch):
    make, says = _greeting_then_if()
    seed_workflow(factory, [make, says], [arrow("start", "make-greeting"),
                                          arrow("make-greeting", "says-hello")])
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        out = (await _test(client, says, source="custom",
                           input={"result": "Set.", "data": {"greeting": "hello world"}})).json()
    assert out["port"] == "then" and out["dropped"] == []
    assert out["input_used"]["data"]["result"] == "Set."


@pytest.mark.asyncio
async def test_outputs_typed_for_a_step_two_back_are_what_its_references_read(factory, monkeypatch):
    nodes = [
        node("a", "Score", "set", fields=[{"name": "score", "value": 1}]),
        node("b", "Note", "set", fields=[{"name": "note", "value": "seen"}]),
        node("c", "High?", "if", join="all", conditions=[
            {"left": "{{ steps.a.data.score }}", "op": "greater_than", "right": "5"},
            {"left": "{{ steps.b.data.note }}", "op": "equals", "right": "seen"}]),
    ]
    seed_workflow(factory, nodes, [arrow("start", "a"), arrow("a", "b"), arrow("b", "c")])
    s = recording_scheduler()
    await s._execute_task("wf")
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        before = (await _test(client, nodes[2], source="last")).json()
        typed = (await _test(client, nodes[2], source="last",
                             outputs={"a": {"data": {"score": 9}}})).json()
        context = (await _test(client, nodes[2], source="last", context_only=True,
                               outputs={"a": {"data": {"score": 9}}})).json()
        stranger = await _test(client, nodes[2], outputs={"c": {"data": {}}})
        bare = await _test(client, nodes[2], outputs={"a": {"score": 9}})
    assert before["port"] == "otherwise" and typed["port"] == "then"
    assert {r["node_id"]: r["origin"] for r in typed["reads"]} == {"a": "typed", "b": "handed"}
    assert context["outcome"] == "context" and "status" not in context, "nothing ran"
    assert context["reads"][0] == {"node_id": "a", "label": "Score", "origin": "typed",
                                   "data": {"score": 9}, "text": ""}
    assert stranger.status_code == 400
    assert "is not the start or a step before" in stranger.json()["detail"]
    assert bare.status_code == 400 and '{"data": …, "text": "…"}' in bare.json()["detail"]


@pytest.mark.asyncio
async def test_outputs_for_the_step_before_are_what_it_is_handed_too(factory, monkeypatch):
    make, says = _greeting_then_if()
    seed_workflow(factory, [make, says], [arrow("start", "make-greeting"),
                                          arrow("make-greeting", "says-hello")])
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        out = (await _test(client, says, source="none",
                           outputs={"make-greeting": {"data": {"greeting": "yo"}, "text": "Made."}})).json()
    assert out["port"] == "otherwise"
    assert out["input_used"]["data"]["data"] == {"greeting": "yo"}
    assert out["input_used"]["data"]["result"] == "Made."
    assert out["data"] == {"greeting": "yo", "port": "otherwise"}


@pytest.mark.asyncio
async def test_a_for_each_is_tested_on_a_typed_list_before_any_run(factory, monkeypatch):
    nodes = [
        node("a", "Issues", "set", fields=[{"name": "issues", "value": "{{ steps.start.data.json }}"}]),
        node("fe", "Each", "foreach", list="{{ steps.a.data.issues }}", on_error="continue",
             step={"kind": "set", "label": "Title", "config": {
                 "fields": [{"name": "t", "value": "{{ item.title }}"}]}}),
    ]
    seed_workflow(factory, nodes, [arrow("start", "a"), arrow("a", "fe")], trigger_type="webhook")
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        out = (await _test(client, nodes[1], source="custom",
                           input={"issues": [{"title": "One"}, {"title": "Two"}]})).json()
    assert out["status"] == "success", out
    assert out["data"]["worked"] == 2
    assert [i["data"] for i in out["data"]["items"]] == [{"t": "One"}, {"t": "Two"}]
