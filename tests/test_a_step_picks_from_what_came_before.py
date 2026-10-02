# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-09` / `P22-16` — the fields a step can pick from, and where each came from.

`workflow_effects.available_fields(db, wf, trigger, graph, node_id)` is
`GET /api/workflows/{id}/nodes/{node_id}/fields`'s body (contract C-W; the
route is wf-walker's). For the start and every step upstream of `node_id` it
lists the fields a reference can name, from up to three places, saying which:
the newest real run's record (`last_node_record`; a dry run is never "the last
run"), the sample pinned on the step it leads to, and what the step promises
before any run — an AI step's answer fields (so `P22-16`'s picker shows
`title`, `url`, `why` before the step has ever run), a Set step's names, the
start's webhook or event fields. Every `ref` is what the picker inserts.

Real SQLite, real `record_node_start`/`record_node_end` (`Law 20`). C-R
(`upstream_of`, `flatten_fields`, `format_ref`) is faked where absent.
"""
from types import SimpleNamespace

import pytest

from src import workflow_effects as fx
from tests.helpers import workflow_cr_fake as cr

GRAPH = {
    "v": 1,
    "nodes": [
        {"id": "fetch", "kind": "http", "label": "Fetch issue", "config": {}},
        {"id": "sum", "kind": "llm", "label": "Summarise", "config": {
            "prompt": "Summarise", "answer_fields": [
                {"name": "title", "type": "text"}, {"name": "url", "type": "text"},
                {"name": "why", "type": "text"}]}},
        {"id": "side", "kind": "set", "label": "Side branch", "config": {
            "fields": [{"name": "headline", "value": "x"}]}},
        {"id": "post", "kind": "mcp", "label": "Post it", "config": {},
         "pinned": {"source": "task", "event": "Summarise", "at": "2026-10-02T07:00:00Z",
                    "data": {"task": "Summarise", "result": "Pinned summary text",
                             "data": {"title": "Pinned title", "url": "u", "why": "w"}}}},
    ],
    "edges": [
        {"from": "fetch", "to": "sum", "when": "success"},
        {"from": "sum", "to": "post", "when": "success"},
        {"from": "fetch", "to": "side", "when": "error"},
    ],
}


@pytest.fixture
def db(monkeypatch):
    from core.database import Base, ScheduledTask, TaskRun
    from tests.helpers.sqlite_db import make_temp_sqlite

    cr.install(monkeypatch)
    SessionLocal, engine, _tmp = make_temp_sqlite(Base.metadata)
    session = SessionLocal()
    session.add(ScheduledTask(id="trig", name="Issue brief", task_type="workflow",
                              trigger_type="webhook"))
    session.add(TaskRun(id="run-1", task_id="trig", status="success"))
    session.add(TaskRun(id="run-dry", task_id="trig", status="skipped"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _record(db, run_id, node_id, *, seq, input_env=None, text=None, data=None, dry=False):
    from src.workflow_runs import record_node_end, record_node_start
    node = next(n for n in GRAPH["nodes"] if n["id"] == node_id)
    rec = record_node_start(db, run_id=run_id, node=node, seq=seq, input_envelope=input_env,
                            workflow_version=1, dry=dry)
    record_node_end(db, rec, status="success", text=text, data=data, port="success")
    return rec


def _fields(db, node_id, trigger=None):
    trigger = trigger or SimpleNamespace(id="trig", trigger_type="webhook", trigger_event=None)
    return fx.available_fields(db, SimpleNamespace(id="wf-1"), trigger, GRAPH, node_id)["sources"]


def _by(sources, node_id, origin):
    found = [s for s in sources if s["node_id"] == node_id and s["origin"] == origin]
    return found[0] if found else None


def test_the_last_runs_fields_are_offered_with_the_reference_the_picker_inserts(db):
    webhook = {"source": "webhook", "event": "webhook", "at": "2026-10-02T07:00:00Z",
               "data": {"json": {"issue": {"number": 7}}, "body": "{...}"}}
    _record(db, "run-1", "fetch", seq=1, input_env=webhook, text="HTTP 200",
            data={"title": "Printer jams on tray 2", "labels": [{"name": "bug"}]})
    fields = _by(_fields(db, "sum"), "fetch", "last_run")
    assert fields["label"] == "Fetch issue" and fields["kind"] == "http" and fields["at"]
    refs = {f["ref"]: f for f in fields["fields"]}
    assert refs["{{ steps.fetch.data.title }}"]["example"] == "Printer jams on tray 2"
    assert refs["{{ steps.fetch.data.title }}"]["type"] == "text"
    assert "{{ steps.fetch.text }}" in refs
    assert "{{ steps.fetch.data.labels[0].name }}" in refs

    start = _by(_fields(db, "sum"), "start", "last_run")
    assert "{{ steps.start.data.json.issue.number }}" in {f["ref"] for f in start["fields"]}


def test_an_ai_steps_answer_fields_are_offered_before_it_ever_ran(db):
    declared = _by(_fields(db, "post"), "sum", "declared")
    assert [f["ref"] for f in declared["fields"]] == [
        "{{ steps.sum.data.title }}", "{{ steps.sum.data.url }}", "{{ steps.sum.data.why }}"]
    assert [f["type"] for f in declared["fields"]] == ["text", "text", "text"]


def test_a_pin_on_the_next_step_is_what_this_step_hands_on(db):
    pinned = _by(_fields(db, "post"), "sum", "pin")
    refs = {f["ref"]: f["example"] for f in pinned["fields"]}
    assert refs["{{ steps.sum.text }}"] == "Pinned summary text"
    assert refs["{{ steps.sum.data.title }}"] == "Pinned title"


def test_only_the_start_and_steps_upstream_are_offered(db):
    _record(db, "run-1", "side", seq=2, text="x", data={"headline": "h"})
    sources = _fields(db, "post")
    assert {s["node_id"] for s in sources} <= {"start", "fetch", "sum"}
    assert not any(s["node_id"] in ("post", "side") for s in sources)
    assert {s["node_id"] for s in _fields(db, "fetch")} == {"start"}


def test_the_start_says_what_a_webhook_hands_over(db):
    declared = _by(_fields(db, "fetch"), "start", "declared")
    assert [f["ref"] for f in declared["fields"]] == [
        "{{ steps.start.data.body }}", "{{ steps.start.data.json }}",
        "{{ steps.start.data.query }}", "{{ steps.start.data.headers }}"]
    on_event = _fields(db, "fetch", SimpleNamespace(id="trig", trigger_type="event",
                                                    trigger_event="email_received"))
    event_refs = [f["ref"] for f in _by(on_event, "start", "declared")["fields"]]
    assert "{{ steps.start.data.message_key }}" in event_refs
    on_schedule = _fields(db, "fetch", SimpleNamespace(id="trig", trigger_type="schedule",
                                                       trigger_event=None))
    assert _by(on_schedule, "start", "declared") is None


def test_a_dry_run_is_never_the_last_run(db):
    _record(db, "run-dry", "fetch", seq=1, text="planned", data={"planned": True}, dry=True)
    assert _by(_fields(db, "sum"), "fetch", "last_run") is None


def test_a_record_cut_to_fit_offers_no_fields(db, monkeypatch):
    monkeypatch.setattr("src.workflow_runs.node_record_max_chars", lambda owner=None: 60)
    _record(db, "run-1", "fetch", seq=1, text="HTTP 200", data={"body": "x" * 500})
    assert _by(_fields(db, "sum"), "fetch", "last_run") is None


def test_a_set_steps_names_are_offered_downstream(db):
    graph = dict(GRAPH, edges=GRAPH["edges"] + [{"from": "side", "to": "post", "when": "success"}])
    sources = fx.available_fields(db, SimpleNamespace(id="wf-1"),
                                  SimpleNamespace(id="trig", trigger_type="webhook"),
                                  graph, "post")["sources"]
    assert [f["ref"] for f in _by(sources, "side", "declared")["fields"]] == [
        "{{ steps.side.data.headline }}"]
