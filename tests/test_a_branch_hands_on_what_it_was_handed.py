# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1863` — an If and a Switch hand on the data they were handed.

A logic step made `{"port": <port>}` and nothing else, so the step after a
branch was handed "Went the “then” way." with the port as its only data: a
Prompt step after "Is it urgent?" never saw the mail it was deciding about,
and `{{ steps.<if>.data.title }}` read nothing. Now If and Switch hand on what
they were handed, as a Wait does (`workflow_logic.passes_on`, the rule): an
object gets the way it went added as `port` — so `{{ steps.<if>.data.port }}`
in an existing document still reads it — an object with its own `port` is
left as it is, and the way it went stays in the record's `port` column, which
is what the walker and the Runs view read. The field picker offers what an If
or a Switch hands on before it has ever run.

Driven through the real `TaskScheduler._execute_task` on a real SQLite file,
the real *Test this step*, and the real `available_fields`.
"""

from types import SimpleNamespace

import pytest

from src import workflow_effects as fx
from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger
from src.workflow_logic import passes_on
from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, row, runs_of, seed_workflow,
)

MAIL = {"title": "Server down", "from": "ops@example.com", "urgent": True}


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "branch.db")


def _mail_then_if(after):
    return ([
        node("mail", "Read the mail", "set", fields=[
            {"name": k, "value": v} for k, v in MAIL.items()]),
        node("urgent", "Is it urgent?", "if", join="all", conditions=[
            {"left": "{{ steps.mail.data.urgent }}", "op": "equals", "right": "yes"}]),
        after,
    ], [arrow("start", "mail"), arrow("mail", "urgent"), arrow("urgent", after["id"], "then")])


@pytest.mark.asyncio
async def test_the_step_after_an_if_is_handed_the_data_the_if_was_handed(factory):
    seed_workflow(factory, *_mail_then_if(node("page", "Page me", "action", action="tidy_sessions")))
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["urgent"]["port"] == "then", "the way it went is still the record's port"
    assert by["urgent"]["output"]["data"] == {**MAIL, "port": "then"}
    assert by["urgent"]["output"]["text"] == "Went the “then” way."
    [page] = [c for c in s.calls if c["name"] == "Morning digest · Page me"]
    assert page["trigger"]["data"]["data"] == {**MAIL, "port": "then"}, page["trigger"]["data"]


@pytest.mark.asyncio
async def test_a_reference_through_the_if_reads_both_the_data_and_the_port(factory):
    """`{{ steps.<if>.data.port }}` — what an existing document reads — still
    resolves; a field of what the If was handed now resolves too."""
    after = node("note", "Note it", "set", fields=[
        {"name": "way", "value": "{{ steps.urgent.data.port }}"},
        {"name": "title", "value": "{{ steps.urgent.data.title }}"}])
    seed_workflow(factory, *_mail_then_if(after))
    await recording_scheduler()._execute_task("wf")
    [run] = runs_of(factory, "wf")
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["note"]["output"]["data"] == {"way": "then", "title": "Server down"}


@pytest.mark.asyncio
async def test_a_switch_hands_on_the_webhooks_data_with_its_case(factory):
    seed_workflow(factory, [
        node("route", "Route", "switch", cases=[
            {"id": "bank", "label": "From the bank", "join": "all", "conditions": [
                {"left": "{{ steps.start.data.json.from }}", "op": "contains", "right": "bank"}]}]),
        node("file", "File it", "action", action="tidy_documents"),
    ], [arrow("start", "route"), arrow("route", "file", "case:bank")], trigger_type="webhook")
    s = recording_scheduler()
    await s._execute_task("wf", trigger=build_trigger(
        TRIGGER_SOURCE_WEBHOOK, "webhook", {"json": {"from": "alerts@bank.example"}},
        fields=WEBHOOK_PAYLOAD_FIELDS))
    [run] = runs_of(factory, "wf")
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["route"]["port"] == "case:bank"
    [filed] = [c for c in s.calls if c["name"] == "Morning digest · File it"]
    assert filed["trigger"]["data"]["data"] == {
        "json": {"from": "alerts@bank.example"}, "port": "case:bank"}


@pytest.mark.asyncio
async def test_data_with_its_own_port_is_handed_on_untouched(factory):
    after = node("page", "Page me", "action", action="tidy_sessions")
    nodes, edges = _mail_then_if(after)
    nodes[0]["config"]["fields"].append({"name": "port", "value": 8080})
    seed_workflow(factory, nodes, edges)
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["urgent"]["output"]["data"] == {**MAIL, "port": 8080}
    assert by["urgent"]["port"] == "then"


@pytest.mark.asyncio
async def test_an_if_handed_only_text_still_makes_its_port(factory):
    """An action that made only text hands no data; the If makes what it
    always made, `{"port": …}`."""
    seed_workflow(factory, [
        node("tidy", "Tidy", "action", action="tidy_sessions"),
        node("ok", "Did it?", "if", join="all", conditions=[
            {"left": "{{ steps.tidy.text }}", "op": "contains", "right": "done"}]),
    ], [arrow("start", "tidy"), arrow("tidy", "ok")])
    await recording_scheduler()._execute_task("wf")
    [run] = runs_of(factory, "wf")
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["ok"]["output"]["data"] == {"port": "then"}


def test_the_rule_for_what_is_not_an_object():
    assert passes_on([1, 2], "then") == [1, 2]
    assert passes_on(7, "otherwise") == 7
    assert passes_on(None, "then") == {"port": "then"}
    assert passes_on("only text", "case:a") == {"port": "case:a"}


@pytest.mark.asyncio
async def test_testing_an_if_shows_what_it_would_hand_on(factory):
    """*Test this step*: the input the person chose is what it was handed."""
    seed_workflow(factory, *_mail_then_if(node("page", "Page me", "action", action="tidy_sessions")))
    s = recording_scheduler()
    sample = {"source": "task", "event": "Read the mail", "at": "2026-11-07T08:00:00Z",
              "data": {"task": "Read the mail", "result": "Set.", "data": MAIL}}
    step = node("urgent", "Is it urgent?", "if", join="all", conditions=[
        {"left": "{{ steps.mail.data.urgent }}", "op": "equals", "right": "yes"}])
    out = await s.test_workflow_node(row(factory, "wf"), "Morning digest", step,
                                     input_envelope=sample)
    assert out["data"]["title"] == "Server down" and out["data"]["port"] == out["port"]


# ── the field picker ───────────────────────────────────────────────────────

GRAPH = {
    "v": 1,
    "nodes": [
        {"id": "mail", "kind": "set", "label": "Read the mail", "config": {
            "fields": [{"name": "title", "value": "x"}, {"name": "from", "value": "y"}]}},
        {"id": "urgent", "kind": "if", "label": "Is it urgent?", "config": {"conditions": []}},
        {"id": "route", "kind": "switch", "label": "Route", "config": {"cases": []}},
        {"id": "page", "kind": "action", "label": "Page me", "config": {}},
    ],
    "edges": [
        {"from": "start", "to": "mail", "port": "success"},
        {"from": "mail", "to": "urgent", "port": "success"},
        {"from": "start", "to": "route", "port": "success"},
        {"from": "urgent", "to": "page", "port": "then"},
        {"from": "route", "to": "page", "port": "otherwise"},
    ],
}


def _declared(sources, node_id):
    found = [s for s in sources if s["node_id"] == node_id and s["origin"] == "declared"]
    return [f["ref"] for f in found[0]["fields"]] if found else None


def test_the_picker_offers_what_an_if_and_a_switch_hand_on_before_any_run():
    trigger = SimpleNamespace(id=None, trigger_type="webhook", trigger_event=None)
    sources = fx.available_fields(None, SimpleNamespace(id="wf-1"), trigger, GRAPH, "page")["sources"]
    assert _declared(sources, "urgent") == [
        "{{ steps.urgent.data.title }}", "{{ steps.urgent.data.from }}",
        "{{ steps.urgent.data.port }}"]
    # A Switch the start leads to hands on the webhook's own fields.
    assert _declared(sources, "route") == [
        *(f"{{{{ steps.route.data.{f} }}}}" for f in WEBHOOK_PAYLOAD_FIELDS),
        "{{ steps.route.data.port }}"]
    # The Set step's own promise is offered as before.
    assert _declared(sources, "mail") == ["{{ steps.mail.data.title }}", "{{ steps.mail.data.from }}"]
