# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1890` (`big-outputs-dropped`) — what a step made is read whole, even when
its record had to be cut.

A step's record is held to `workflow_node_record_max_chars` (16,000 by
default) and past it becomes a preview marker. Every reader of the record
skipped a cut one, so — measured before the fix, on the audit's workflow
(webhook → Set a of ten ~1.9 KB fields → Wait 1 minute → Set c reading
`{{ steps.a.data.f0[0].title }}`):

  * after the Wait the run ended "success" with c's log saying "Not found, so
    left empty: {{ steps.a.data.f0[0].title }}" — the walker reads records
    after a pause, and a.'s was a preview;
  * the field picker offered `a` only as "declared", with no examples and no
    nested paths;
  * *Test this step* on c read nothing from `a`.

Now a cut record keeps what it made whole, apart (`task_run_node_outputs`,
ON DELETE CASCADE from the record, so the record's retention), with the
picker's view of it taken before the cut. The preview stays capped.

Driven through the real `TaskScheduler` (a Wait and its sweeper) on a real
SQLite file, the real picker and the real *Test this step*.
"""

import json
from types import SimpleNamespace

import pytest

from src import workflow_effects as fx
from src import workflow_runs as wr
from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger
from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, row, runs_of, seed_workflow,
    settle, skip_ahead,
)

pytestmark = pytest.mark.asyncio

BIG = {f"f{i}": [{"title": f"Title {i}", "body": "x" * 1900}] for i in range(10)}
NODES = [
    node("a", "Big", "set", fields=[{"name": k, "value": f"{{{{ steps.start.data.json.{k} }}}}"}
                                    for k in BIG]),
    node("w", "Later", "wait", mode="for", minutes=1),
    node("c", "Read it", "set", fields=[{"name": "t", "value": "{{ steps.a.data.f0[0].title }}"},
                                        {"name": "last", "value": "{{ steps.a.data.f9[0].title }}"}]),
]
EDGES = [arrow("start", "a"), arrow("a", "w"), arrow("w", "c")]


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "big.db")


async def _run_past_the_wait(factory, monkeypatch):
    seed_workflow(factory, NODES, EDGES, trigger_type="webhook")
    s = recording_scheduler()
    await s._execute_task("wf", trigger=build_trigger(
        TRIGGER_SOURCE_WEBHOOK, "webhook", {"json": BIG}, fields=WEBHOOK_PAYLOAD_FIELDS))
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting", run
    skip_ahead(monkeypatch, 61)
    assert await s._resume_due_waits() == 1
    await settle(s)
    [run] = runs_of(factory, "wf")
    return s, run


async def test_a_reference_into_a_cut_record_reads_it_whole_after_a_wait(factory, monkeypatch):
    _s, run = await _run_past_the_wait(factory, monkeypatch)
    assert run["status"] == "success", run
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert wr.is_truncated(by["a"]["output"]), "the record itself is still a capped preview"
    assert len(json.dumps(by["a"]["output"])) <= wr.NODE_RECORD_MAX_CHARS_DEFAULT
    assert by["c"]["output"]["data"] == {"t": "Title 0", "last": "Title 9"}, by["c"]


async def test_the_picker_offers_every_field_of_a_cut_record_with_its_example(factory, monkeypatch):
    await _run_past_the_wait(factory, monkeypatch)
    db = factory()
    try:
        trigger = SimpleNamespace(id="wf", trigger_type="webhook", trigger_event=None)
        sources = fx.available_fields(db, SimpleNamespace(id="w-wf"), trigger,
                                      {"v": 1, "nodes": NODES, "edges": EDGES}, "c")["sources"]
    finally:
        db.close()
    [last] = [s for s in sources if s["node_id"] == "a" and s["origin"] == "last_run"]
    refs = {f["ref"]: f["example"] for f in last["fields"]}
    assert refs["{{ steps.a.data.f0[0].title }}"] == "Title 0"
    assert refs["{{ steps.a.data.f9 }}"] == "1 item"
    start = [s for s in sources if s["node_id"] == "start" and s["origin"] == "last_run"]
    assert start and "{{ steps.start.data.json.f3[0].title }}" in {f["ref"] for f in start[0]["fields"]}, \
        "the start's large trigger is offered from the run's own row"


async def test_testing_the_step_after_reads_the_cut_record_whole(factory, monkeypatch):
    s, _run = await _run_past_the_wait(factory, monkeypatch)
    out = await s.test_workflow_node(row(factory, "wf"), "Morning digest", NODES[2],
                                     graph={"v": 1, "nodes": NODES, "edges": EDGES})
    assert out["data"] == {"t": "Title 0", "last": "Title 9"}, out


async def test_the_whole_copy_goes_with_its_record(factory, monkeypatch):
    from datetime import timedelta

    from core.database import TaskRunNodeOutput

    _s, run = await _run_past_the_wait(factory, monkeypatch)
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    db = factory()
    try:
        # The Wait hands on what it was handed (a's data), so its record is
        # cut too; c's is small and keeps no copy.
        kept = {r.record_id for r in db.query(TaskRunNodeOutput).all()}
        assert kept == {by["a"]["id"], by["w"]["id"]}, "only a cut record keeps a copy"
        removed = wr.prune_node_records(db, days=1, now=wr._utcnow() + timedelta(days=2))
        assert removed == 3
        assert db.query(TaskRunNodeOutput).count() == 0, "the record's retention"
    finally:
        db.close()


async def test_a_step_that_makes_more_than_the_whole_copy_holds_says_so(factory, monkeypatch):
    monkeypatch.setattr(wr, "WHOLE_OUTPUT_MAX_CHARS", 10_000)
    _s, run = await _run_past_the_wait(factory, monkeypatch)
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    said = [line.get("detail") for line in by["a"]["steps"]]
    assert any("more than the 10,000 kept whole" in (d or "") for d in said), said
    # `B1881`: a Set field that reads nothing stops the step, naming the
    # reference and that the step it reads was kept only in part.
    said_c = by["c"]["output"]["text"]
    assert "read nothing from {{ steps.a.data.f0[0].title }}" in said_c, \
        "a reference that reads nothing after a pause still says so"
    assert "kept only in part" in said_c, said_c
