# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1856` — a step can be switched off in its workflow.

Measured before this row, on `ea80706`: to leave a step out of a run you had
to delete it (and its arrows) or rewire around it; `parse_graph` dropped any
`disabled` key, so a document that carried one ran the step anyway. Now
`"disabled": true` on a step means a run does not run it: its record is
`skipped` — "Switched off in this workflow — passed its input on" — its output
is what it was handed, and the run goes on along its first way out. A step
switched off need not be complete, and it is part of the document's
fingerprint only while it is off.

Pure functions called, and the walker driven over the real scheduler
(`walker_harness`); only an Action step's far end is a recorder.
"""

import json

import pytest

from tests.helpers.walker_harness import (
    arrow, make_db, node, recording_scheduler, records_of, runs_of, seed_workflow,
)

SWITCHED_OFF = "Switched off in this workflow — passed its input on"


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "off.db")


def _doc(nodes, edges):
    return {"v": 1, "nodes": nodes, "edges": edges}


def _check(graph, *, admin=True):
    from src import workflow_document as wd
    return wd.validate_document(wd.parse_graph(json.dumps(graph)), owner="alice",
                                tasks_by_id={}, crew_ids=set(), owner_is_admin=admin,
                                own_task_id="wf")


def test_switched_off_is_kept_only_when_it_is_off_and_only_as_true_or_false():
    from src import workflow_document as wd
    off = dict(node("a", "Tidy", "action", action="tidy_sessions"), disabled=True)
    on = dict(node("b", "Tidy too", "action", action="tidy_sessions"), disabled=False)
    plain = node("c", "Tidy three", "action", action="tidy_sessions")
    parsed = wd.parse_graph(json.dumps(_doc([off, on, plain], [])))
    assert [n.get("disabled") for n in parsed["nodes"]] == [True, None, None]
    assert "disabled" not in parsed["nodes"][1], "false is the default and is not stored"
    with pytest.raises(wd.DocumentError) as refused:
        wd.parse_graph(json.dumps(_doc([dict(plain, disabled="yes")], [])))
    assert refused.value.refusal.sentence == (
        "The workflow could not be read: “Tidy three” is switched on or off by something "
        "that is neither true nor false.")


def test_switching_a_step_off_is_an_edit_and_switching_it_back_is_none():
    from src import workflow_document as wd
    plain = [node("a", "Tidy", "action", action="tidy_sessions")]
    before = wd.content_fingerprint("W", wd.parse_graph(json.dumps(_doc(plain, []))))
    off = wd.content_fingerprint("W", wd.parse_graph(json.dumps(
        _doc([dict(plain[0], disabled=True)], []))))
    back = wd.content_fingerprint("W", wd.parse_graph(json.dumps(
        _doc([dict(plain[0], disabled=False)], []))))
    assert off != before and back == before


def test_a_step_switched_off_need_not_be_complete_but_an_admin_only_one_is_still_refused():
    half = node("a", "Not finished", "action")              # no action chosen yet
    unread = node("p", "Ask", "llm", prompt="Say {{ steps.nowhere.text }}")
    assert _check(_doc([half], [arrow("start", "a")])).reason == "missing_setting"
    assert _check(_doc([dict(half, disabled=True)], [arrow("start", "a")])) is None
    assert _check(_doc([unread], [arrow("start", "p")])) is not None
    assert _check(_doc([dict(unread, disabled=True)], [arrow("start", "p")])) is None
    from src.task_action_policy import ADMIN_ONLY_TASK_ACTIONS
    admin_only = sorted(ADMIN_ONLY_TASK_ACTIONS)[0]
    shell = dict(node("x", "Shell", "action", action=admin_only), disabled=True)
    refused = _check(_doc([shell], [arrow("start", "x")]), admin=False)
    assert refused is not None and refused.reason == "admin_only"


@pytest.mark.asyncio
async def test_a_switched_off_step_is_skipped_and_hands_on_what_it_was_handed(factory):
    seed_workflow(factory, [
        node("s", "Make it", "set", fields=[{"name": "n", "value": 3}]),
        dict(node("a", "Tidy", "action", action="tidy_sessions"), disabled=True),
        node("t", "Read it", "set", fields=[{"name": "m", "value": "{{ steps.a.data.n }}"}]),
        node("b", "Tidy documents", "action", action="tidy_documents"),
    ], [arrow("start", "s"), arrow("s", "a"), arrow("a", "t"), arrow("t", "b")])
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy documents"], "it did not run"
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    off = by["a"]
    assert off["status"] == "skipped" and off["port"] == "success"
    assert off["output"] == {"text": SWITCHED_OFF, "data": {"n": 3}}
    assert by["t"]["output"]["data"] == {"m": 3}, "a reference to it reads its input"
    line = next(st for st in run["steps"] if st.get("node") == "a")
    assert line["status"] == "skipped" and line["detail"] == SWITCHED_OFF
    assert any(st.get("detail") == "Continued to Read it" for st in run["steps"])


@pytest.mark.asyncio
async def test_a_switched_off_switch_goes_its_first_way(factory):
    seed_workflow(factory, [
        dict(node("route", "Route", "switch", cases=[
            {"id": "bank", "label": "From the bank", "join": "all", "conditions": [
                {"left": "{{ steps.start.data.from_address }}", "op": "contains",
                 "right": "bank"}]}]), disabled=True),
        node("note", "Note it", "action", action="tidy_sessions"),
        node("else", "Ignore", "action", action="tidy_documents"),
    ], [arrow("start", "route"), arrow("route", "note", "case:bank"),
        arrow("route", "else", "otherwise")],
        trigger_type="event", trigger_event="email_received", schedule=None)
    from src.event_bus import build_trigger
    s = recording_scheduler()
    await s._execute_task("wf", trigger=build_trigger("event", "email_received", {
        "account": "home", "folder": "INBOX", "message_key": "1",
        "from_address": "someone@else.example", "subject": "Hi"}))
    [run] = runs_of(factory, "wf")
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["route"]["status"] == "skipped" and by["route"]["port"] == "case:bank"
    assert by["route"]["output"]["data"]["from_address"] == "someone@else.example"
    assert [c["name"] for c in s.calls] == ["Morning digest · Note it"]
    assert "else" not in by


@pytest.mark.asyncio
async def test_a_workflow_of_steps_switched_off_runs_nothing_and_says_skipped(factory):
    seed_workflow(factory, [
        dict(node("p", "Ask", "llm", prompt="Hello"), disabled=True),
        dict(node("a", "Tidy", "action", action="tidy_sessions"), disabled=True),
    ], [arrow("start", "p"), arrow("p", "a")])
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "skipped" and s.calls == []
    from core.database import ScheduledTask
    db = factory()
    try:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == "wf").first()
        assert s._workflow_needs_model_slot(db, task) is False
    finally:
        db.close()


def test_a_switched_off_model_step_takes_no_model_and_its_plan_says_it_is_off(factory):
    from src import workflow_document as wd
    from src.task_scheduler import TaskScheduler
    prompt = node("p", "Ask", "llm", prompt="Hello")
    assert wd.node_needs_model(prompt) is True
    assert wd.node_needs_model(dict(prompt, disabled=True)) is False
    s = TaskScheduler(None)
    steps, declined = s._plan_workflow_node(None, None, dict(prompt, disabled=True))
    assert declined is None
    assert [st["detail"] for st in steps] == [
        "Switched off in this workflow — it would pass its input on and do nothing else."]


@pytest.mark.asyncio
async def test_a_save_keeps_a_step_switched_off_and_is_a_new_version(factory, monkeypatch):
    from tests.helpers.walker_harness import app_for, client_for
    seed_workflow(factory, [node("a", "Tidy", "action", action="tidy_sessions")],
                  [arrow("start", "a")])
    s = recording_scheduler()
    alice = {"x-test-user": "alice"}
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        got = (await client.get("/api/workflows/w-wf", headers=alice)).json()["workflow"]
        graph = got["graph"]
        graph["nodes"][0]["disabled"] = True
        saved = await client.put("/api/workflows/w-wf", headers=alice,
                                 json={"graph": graph, "base_version": got["version"]})
        assert saved.status_code == 200, saved.text
        after = (await client.get("/api/workflows/w-wf", headers=alice)).json()["workflow"]
        assert after["graph"]["nodes"][0]["disabled"] is True
        assert after["version"] == got["version"] + 1, "switching a step off is an edit"
        graph["nodes"][0]["disabled"] = False
        back = await client.put("/api/workflows/w-wf", headers=alice,
                                json={"graph": graph, "base_version": after["version"]})
        assert back.status_code == 200, back.text
        last = (await client.get("/api/workflows/w-wf", headers=alice)).json()["workflow"]
        assert "disabled" not in last["graph"]["nodes"][0]
