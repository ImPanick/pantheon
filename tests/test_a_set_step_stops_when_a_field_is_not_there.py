# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1881` (`set-missing-silent-and-type-words`) — a Set step whose field reads
nothing stops the run and says which field, unless it says to leave it empty;
and a For-each handed something that is not a list says what, in words.

The audit found that an HTTP, MCP, Code or AI step fails when a reference
finds nothing, but a Set step stored `null`, mentioned it only in its text,
and the run ended "success" — how a webhook clipped short, or data lost past
a Wait, showed as a green run. And a For-each handed text said "was handed
str, not a list"; handed an object, "was handed dict".

Now a Set step stops: "“Shape” stopped: “title” read nothing from
{{ steps.read.data.title }}. Pick a field that is there, end the reference in
| default:"…" for when it is not, or set “If a field is not there” to leave it
empty and go on." Its `on_missing` — "stop" (what a step that says nothing
does) or "empty" (what every Set step did before this row) — is the person's
choice, refused at save when it is neither. A For-each says "was handed text"
/ "an object" / "a number" / "yes or no" / "nothing".

The real `TaskScheduler` over a real SQLite file (`Law 20`); the rule and the
words called.
"""

import pytest

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

from src import workflow_document as wd  # noqa: E402
from src import workflow_logic as wl  # noqa: E402
from src import workflow_refs as wr  # noqa: E402
from src import workflow_slots as ws  # noqa: E402
from tests.helpers.walker_harness import (  # noqa: E402
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
)

HELP = ("Pick a field that is there, end the reference in | default:\"…\" for when it is not, "
        "or set “If a field is not there” to leave it empty and go on.")


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "set.db")


def _read_then_shape(shape_fields, **shape_config):
    return ([
        node("read", "Read", "set", fields=[{"name": "subject", "value": "Hello"},
                                            {"name": "amount", "value": "about ten"}]),
        node("shape", "Shape", "set", fields=shape_fields, **shape_config),
        node("after", "After", "set", fields=[{"name": "x", "value": "{{ steps.shape.data }}"}],
             on_missing="empty"),
    ], [arrow("start", "read"), arrow("read", "shape"), arrow("shape", "after")])


async def _run(factory, nodes, edges):
    seed_workflow(factory, nodes, edges)
    await recording_scheduler()._execute_task("wf")
    [run] = runs_of(factory, "wf")
    return run, {r["node_id"]: r for r in records_of(factory, run["id"])}


@pytest.mark.asyncio
async def test_a_field_that_reads_nothing_stops_the_run_and_says_which(factory):
    run, by = await _run(factory, *_read_then_shape([
        {"name": "subject", "value": "{{ steps.read.data.subject }}"},
        {"name": "title", "value": "Re: {{ steps.read.data.title }}"},
        {"name": "who.name", "value": "{{ steps.read.data.from }}"}]))
    assert run["status"] != "success", run
    assert by["shape"]["status"] == "error"
    said = by["shape"]["error"] or str(by["shape"]["output"])
    assert said == (
        "“Shape” stopped: “title” read nothing from {{ steps.read.data.title }}; “who.name” "
        "read nothing from {{ steps.read.data.from }}. " + HELP), said
    assert "after" not in by, "the step after it does not run on a hole"


@pytest.mark.asyncio
async def test_a_change_that_cannot_use_its_value_stops_it_too_and_says_why(factory):
    run, by = await _run(factory, *_read_then_shape([
        {"name": "n", "value": "{{ steps.read.data.amount | number }}"}]))
    assert by["shape"]["status"] == "error"
    assert (by["shape"]["error"] or "").startswith(
        "“Shape” stopped: “n” read nothing from {{ steps.read.data.amount | number }} "
        "(what “number” was handed is not a number). ")


@pytest.mark.asyncio
async def test_leave_it_empty_goes_on_as_a_set_step_always_did(factory):
    run, by = await _run(factory, *_read_then_shape([
        {"name": "subject", "value": "{{ steps.read.data.subject }}"},
        {"name": "title", "value": "{{ steps.read.data.title }}"}], on_missing="empty"))
    assert run["status"] == "success", run
    assert by["shape"]["output"]["data"] == {"subject": "Hello", "title": None}
    assert by["shape"]["output"]["text"] == (
        "Set “subject”, “title”. Not found, so left empty: {{ steps.read.data.title }}.")
    assert by["after"]["status"] == "success"


@pytest.mark.asyncio
async def test_a_default_is_not_missing(factory):
    run, by = await _run(factory, *_read_then_shape([
        {"name": "title", "value": '{{ steps.read.data.title | default:"(none)" }}'}]))
    assert run["status"] == "success", run
    assert by["shape"]["output"]["data"] == {"title": "(none)"}


@pytest.mark.parametrize("value,words", [
    ("hello", "text"), ({"a": 1}, "an object"), (7, "a number"), (True, "yes or no"),
    (None, "nothing"),
])
@pytest.mark.asyncio
async def test_a_for_each_handed_something_else_says_what_in_words(factory, value, words):
    seed_workflow(factory, [
        node("read", "Read", "set", fields=[{"name": "items", "value": value}]),
        node("each", "Each mail", "foreach", list="{{ steps.read.data.items }}",
             step={"kind": "set", "label": "One", "config": {"fields": [{"name": "x", "value": "1"}]}}),
    ], [arrow("start", "read"), arrow("read", "each")])
    await recording_scheduler()._execute_task("wf")
    [run] = runs_of(factory, "wf")
    by = {r["node_id"]: r for r in records_of(factory, run["id"]) if r["item"] is None}
    assert by["each"]["error"] == (
        f"“Each mail” was handed {words}, not a list, so there was nothing to go through.")


# ── The words, and the rule at save ──────────────────────────────────────────

@pytest.mark.parametrize("value,words", [
    ("x", "text"), ("", "text"), (3, "a number"), (2.5, "a number"), (False, "yes or no"),
    ([], "a list"), ({}, "an object"), (None, "nothing"), (wr.MISSING, "nothing"),
])
def test_what_a_value_is_in_words(value, words):
    assert wl.type_words(value) == words


def test_stop_is_what_a_step_that_says_nothing_does():
    assert wl.SET_ON_MISSING == ("stop", "empty")
    assert wl.set_stops_on_missing({}) is True
    assert wl.set_stops_on_missing({"on_missing": "stop"}) is True
    assert wl.set_stops_on_missing({"on_missing": "empty"}) is False
    assert wl.set_stops_on_missing(None) is True


RES = wd.WorkflowResources(integrations={}, mcp_tools={}, skills=frozenset(),
                           ai_tools=frozenset(), workstation_why=None,
                           foreach_max_items=50, wait_max_hours=2)


def _check(**config):
    step = node("s", "Shape", "set", fields=[{"name": "a", "value": "1"}], **config)
    graph = wd.parse_graph({"v": 1, "nodes": [step], "edges": [arrow("start", "s")]})
    return wd.validate_document(graph, owner="alice", tasks_by_id={}, crew_ids=set(),
                                owner_is_admin=True, own_task_id="t", resources=RES)


def test_on_missing_is_stop_or_empty_and_nothing_else():
    assert _check() is None
    assert _check(on_missing="stop") is None
    assert _check(on_missing="empty") is None
    refusal = _check(on_missing="maybe")
    assert refusal.reason == wd.REFUSE_BAD_SETTING and refusal.field == "on_missing"
    assert "when a field is not there it stops or leaves it empty" in refusal.sentence
    refusal = _check(on_missing="{{ steps.start.text }}")
    assert refusal is not None and refusal.reason == wd.REFUSE_MAPPED_NEVER, refusal


def test_on_missing_is_declared_never_and_a_set_setting():
    assert "on_missing" in wd.NODE_CONFIG_FIELDS["set"]
    slot = ws.slot_for({"kind": "set", "config": {}}, ("on_missing",))
    assert slot.mapping == ws.MAPPING_NEVER


def test_the_plan_says_when_a_field_would_be_left_empty():
    base = {"id": "s", "kind": "set", "config": {"fields": [{"name": "a", "value": "1"}]}}
    assert wd.plan_lines(base) == ["Would make these fields:", "a ← 1"]
    base["config"]["on_missing"] = "empty"
    assert wd.plan_lines(base)[-1] == "A field that is not there would be left empty, and it would go on."
