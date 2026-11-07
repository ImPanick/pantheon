# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1889` (`foreach-last-record-is-an-item`) — "the last run" of a For-each is
its own record, never its last item's.

A For-each keeps each item's record under the For-each's own step id, with
`item` set to the index, and every item starts after the For-each's own
record. `workflow_runs.last_node_record` took the newest record of the step,
so it answered the LAST ITEM. Measured before the fix (the audit's workflow,
webhook → Set → For-each of Set → Set): the field picker for the step after
the For-each listed `{{ steps.fe.data.t }}` with the last item's value
"Third" and never `items`, `worked` or `failed`; *Test this step* on that
step read `t` and said "Not found, so left empty: {{ steps.fe.data.worked }}"
although the real run had made `worked: 3`; and *What it was handed in the
last run* on the For-each was the last item's input.

Driven through the real `TaskScheduler._execute_task` on a real SQLite file,
the real field picker (`workflow_effects.available_fields`), the real *Test
this step* (`test_workflow_node`) and the test route's own reader of the last
input (`workflow_routes._last_input`).
"""

from types import SimpleNamespace

import pytest

from src import workflow_effects as fx
from src import workflow_runs as wr
from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger
from tests.helpers.walker_harness import (
    arrow, make_db, node, recording_scheduler, row, runs_of, seed_workflow,
)

ISSUES = [{"title": "First"}, {"title": "Second"}, {"title": "Third"}]
NODES = [
    node("a", "Read the issues", "set", fields=[
        {"name": "issues", "value": "{{ steps.start.data.json.issues }}"}]),
    node("fe", "Each issue", "foreach", list="{{ steps.a.data.issues }}", on_error="continue",
         step={"kind": "set", "label": "Title", "config": {
             "fields": [{"name": "t", "value": "{{ item.title }}"}]}}),
    node("c", "Count", "set", fields=[{"name": "worked", "value": "{{ steps.fe.data.worked }}"}]),
]
EDGES = [arrow("start", "a"), arrow("a", "fe"), arrow("fe", "c")]


@pytest.fixture()
def ran(monkeypatch, tmp_path):
    import asyncio

    factory = make_db(monkeypatch, tmp_path / "foreach.db")
    seed_workflow(factory, NODES, EDGES, trigger_type="webhook")
    s = recording_scheduler()
    asyncio.run(s._execute_task("wf", trigger=build_trigger(
        TRIGGER_SOURCE_WEBHOOK, "webhook", {"json": {"issues": ISSUES}},
        fields=WEBHOOK_PAYLOAD_FIELDS)))
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    return factory, s


def test_the_last_record_of_a_for_each_is_its_own(ran):
    factory, _s = ran
    db = factory()
    try:
        rec = wr.last_node_record(db, "wf", "fe")
        assert rec.item is None, "the For-each's own record, not an item's"
        out = wr._loads(rec.output)
        assert out["data"]["worked"] == 3 and out["data"]["failed"] == 0
        assert [i["data"] for i in out["data"]["items"]] == [{"t": "First"}, {"t": "Second"},
                                                             {"t": "Third"}]
    finally:
        db.close()


def test_the_picker_offers_what_the_for_each_made(ran):
    factory, _s = ran
    db = factory()
    try:
        graph = {"v": 1, "nodes": NODES, "edges": EDGES}
        trigger = SimpleNamespace(id="wf", trigger_type="webhook", trigger_event=None)
        sources = fx.available_fields(db, SimpleNamespace(id="w-wf"), trigger, graph, "c")["sources"]
    finally:
        db.close()
    [last] = [s for s in sources if s["node_id"] == "fe" and s["origin"] == "last_run"]
    refs = {f["ref"]: f.get("example") for f in last["fields"]}
    assert "{{ steps.fe.data.worked }}" in refs and refs["{{ steps.fe.data.worked }}"] == "3"
    assert "{{ steps.fe.data.failed }}" in refs and "{{ steps.fe.data.items }}" in refs
    assert "{{ steps.fe.data.t }}" not in refs, "the last item's field is not the For-each's"


@pytest.mark.asyncio
async def test_testing_the_step_after_reads_the_for_each_as_the_run_did(ran):
    factory, s = ran
    out = await s.test_workflow_node(
        row(factory, "wf"), "Morning digest", NODES[2],
        graph={"v": 1, "nodes": NODES, "edges": EDGES})
    assert out["status"] == "success", out
    assert out["data"] == {"worked": 3}, "the run made worked: 3, and the test reads the same"


def test_the_for_eachs_last_input_is_what_it_was_handed(ran):
    from routes.workflow.workflow_routes import _last_input

    factory, _s = ran
    db = factory()
    try:
        value, found = _last_input(db, SimpleNamespace(id="wf"), "fe")
    finally:
        db.close()
    assert found
    assert value["source"] == "task" and value["data"]["task"] == "Read the issues", \
        "what the step before it handed it, not one item"
    assert value["data"]["data"] == {"issues": ISSUES}
