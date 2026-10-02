# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-12` — For each item: one step, run for each item of a referenced list,
in order, each item with its own record, in ONE run.

Through the real scheduler on a real SQLite file; the inner step's executor is
a recorder that can fail an item or stop one for a yes, so "a failure on the
third names it" and "a resumed run does not run a finished item again" are
measured on the records the walker wrote.
"""

import pytest

from src.builtin_actions import TaskWaiting
from src.tool_approvals import tool_approval_store
from tests.helpers.walker_harness import (
    app_for, arrow, client_for, make_db, node, records_of, recording_scheduler, runs_of,
    seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio

EMAILS = [{"subject": f"Mail {i}", "from": f"p{i}@example.org"} for i in range(1, 6)]


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "each.db")


def _each(on_error="continue", inner=None, items=EMAILS):
    return ([node("fetch", "Fetch unread", "set", fields=[{"name": "emails", "value": items}]),
             node("each", "For each email", "foreach", list="{{ steps.fetch.data.emails }}",
                  on_error=on_error,
                  step=inner or {"kind": "llm", "label": "Summarise",
                                 "config": {"prompt": "Summarise this email."}})],
            [arrow("fetch", "each")])


def _item(i, n=5):
    return f"Morning digest · Summarise · item {i} of {n}"


async def test_five_emails_five_records_one_run_and_the_third_failure_is_named(factory):
    """`P22-12`'s `Verify:` — five summaries in one run; a failure on the
    third names it, in the step's record and in the run's error."""
    seed_workflow(factory, *_each())
    s = recording_scheduler({_item(3): RuntimeError("the model refused")})
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert [c["name"] for c in s.calls] == [_item(i) for i in range(1, 6)], "in order"
    records = records_of(factory, run["id"])
    items = [r for r in records if r["item"] is not None]
    assert [(r["item"], r["status"]) for r in items] == [
        (0, "success"), (1, "success"), (2, "error"), (3, "success"), (4, "success")]
    assert [r["label"] for r in items][2] == "Summarise · item 3 of 5"
    own = [r for r in records if r["node_id"] == "each" and r["item"] is None][0]
    assert own["status"] == "error" and own["port"] == "error"
    assert own["error"] == "Item 3 of 5 failed: RuntimeError: the model refused"
    assert own["output"]["data"]["worked"] == 4 and own["output"]["data"]["failed"] == 1
    assert [x["index"] for x in own["output"]["data"]["items"]] == [0, 1, 2, 3, 4]
    assert run["status"] == "error"
    assert run["error"] == "“For each email” failed: Item 3 of 5 failed: RuntimeError: the model refused"
    # Each item was handed its own email, wrapped as the step before's hand-off.
    handed = s.calls[1]["trigger"]["data"]
    assert handed["data"] == EMAILS[1]


async def test_stop_on_the_first_failure_runs_no_more_items(factory):
    seed_workflow(factory, *_each(on_error="stop"))
    s = recording_scheduler({_item(2): RuntimeError("down")})
    await s._execute_task("wf")
    assert [c["name"] for c in s.calls] == [_item(1), _item(2)]
    [run] = runs_of(factory, "wf")
    items = [r for r in records_of(factory, run["id"]) if r["item"] is not None]
    assert [(r["item"], r["status"]) for r in items] == [(0, "success"), (1, "error")]


async def test_over_the_cap_is_refused_by_name_and_nothing_runs(factory, monkeypatch):
    """Over `workflow_foreach_max_items` the step is refused with the
    setting's name; nothing is cut silently. The cap resolves with the owner
    through the role layer (`P12-01`), as the record cap does."""
    from src import settings
    from src import workflow_runs as wr
    monkeypatch.setattr(settings, "role_limit",
                        lambda key, owner=None: 3 if key == wr.FOREACH_MAX_ITEMS_SETTING else None)
    assert wr.foreach_max_items("alice") == 3
    seed_workflow(factory, *_each())
    s = recording_scheduler()
    await s._execute_task("wf")
    assert s.calls == []
    [run] = runs_of(factory, "wf")
    own = [r for r in records_of(factory, run["id"]) if r["node_id"] == "each"][0]
    assert own["error"] == ("“For each email” was handed 5 items; workflow_foreach_max_items "
                            "allows 3. Nothing was run.")


async def test_an_item_is_read_by_reference(factory):
    seed_workflow(factory, *_each(inner={"kind": "set", "label": "Pick", "config": {
        "fields": [{"name": "headline", "value": "{{ item.subject }}"}]}}))
    s = recording_scheduler()
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    items = [r for r in records_of(factory, run["id"]) if r["item"] is not None]
    assert [r["output"]["data"] for r in items] == [{"headline": f"Mail {i}"} for i in range(1, 6)]
    assert run["status"] == "success"


async def test_a_resumed_run_does_not_run_a_finished_item_again(factory, monkeypatch):
    """Item 2 stops for a yes; the run parks; Allow resumes it — item 1 is
    not run again, item 2 runs again with the consumed approval, and items 3
    to 5 run once each."""
    from src.tool_capabilities import capabilities_for_action
    asked = {"done": False}

    async def needs_a_yes(task, run_id):
        if asked["done"]:
            return "item 2 summarised after the yes"
        asked["done"] = True
        pending = tool_approval_store.create(
            owner="alice", session_id="", origin_run_id=run_id, tool_name="bash",
            content="printf two", workspace=None, external_untrusted_context_seen=True,
            capabilities=capabilities_for_action("bash", "printf two"))
        raise TaskWaiting("Waiting for your yes on bash", kind="approval",
                          approval_id=pending.approval_id, session_id="", tool="bash",
                          until=pending.expires_at, card=pending.public_payload())

    seed_workflow(factory, *_each())
    s = recording_scheduler({_item(2): needs_a_yes})
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "waiting" and run["result"] == "Waiting for your yes on “For each email”"
    own = [r for r in records_of(factory, run["id"])
           if r["node_id"] == "each" and r["item"] is None][0]
    card = own["waiting"]["approval"]
    async with client_for(app_for(factory, s, monkeypatch)) as client:
        listed = (await client.get("/api/workflows/waiting",
                                   headers={"x-test-user": "alice"})).json()["waiting"]
        assert [(x["node_id"], x["item"]) for x in listed] == [("each", 1)]
        res = await client.post(f"/api/workflows/w-wf/runs/{run['id']}/answer",
                                headers={"x-test-user": "alice"},
                                json={"node_id": "each", "item": 1,
                                      "approval_id": card["approval_id"],
                                      "decision": "approve_task"})
    assert res.status_code == 200, res.text
    await settle(s)
    names = [c["name"] for c in s.calls]
    assert names == [_item(1), _item(2), _item(2), _item(3), _item(4), _item(5)]
    again = [c for c in s.calls if c["name"] == _item(2)][1]
    assert again["slot_state"].get("exact_approval") is not None
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success"
    items = [r for r in records_of(factory, run["id"]) if r["item"] is not None]
    assert [(r["item"], r["status"]) for r in items] == [(i, "success") for i in range(5)]
    assert len(items) == 5, "one record per item, the parked one reused"
