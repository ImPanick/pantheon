# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-11` / `P22-10` — branches run side by side inside ONE run, a Merge
waits for its inputs, and If / Switch / Set route and reshape without a model.

Driven through the real `TaskScheduler._execute_task` on a real SQLite file
(`tests/helpers/walker_harness.py`). The executors are recorders that can hold a
step open, so "side by side" is measured — every feed is inside its executor
at the same moment — rather than inferred from the order of records.
"""

import asyncio

import pytest

from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "side.db")


def _held(started: list, release: asyncio.Event, name: str, text: str):
    async def run(task, run_id):
        started.append(name)
        await asyncio.wait_for(release.wait(), timeout=5)
        return text
    return run


async def test_three_feeds_at_once_then_merge_all_then_brief_me(factory):
    """`P22-11`'s `Verify:` shape — "check three feeds at once, merge, brief
    me" — as ONE run: the three feed steps are all inside their executors at
    the same time (the third releases the barrier only when it sees the other
    two waiting), the Merge waits for all three, and the brief is handed all
    three, in the order they arrived."""
    started, release = [], asyncio.Event()

    async def third(task, run_id):
        started.append("C")
        for _ in range(200):
            if {"A", "B"} <= set(started):
                break
            await asyncio.sleep(0.01)
        assert {"A", "B"} <= set(started), "the three feeds did not run side by side"
        release.set()
        return "feed C: 1 item"

    seed_workflow(factory, [
        node("a", "Feed A", "action", action="tidy_sessions"),
        node("b", "Feed B", "action", action="tidy_documents"),
        node("c", "Feed C", "action", action="consolidate_memory"),
        node("m", "Merge", "merge", mode="all"),
        node("brief", "Brief me"),
    ], [arrow("start", "a"), arrow("start", "b"), arrow("start", "c"),
        arrow("a", "m"), arrow("b", "m"), arrow("c", "m"), arrow("m", "brief")])
    s = recording_scheduler({
        "Morning digest · Feed A": _held(started, release, "A", "feed A: 3 items"),
        "Morning digest · Feed B": _held(started, release, "B", "feed B: 2 items"),
        "Morning digest · Feed C": third,
    })
    await s._execute_task("wf")

    runs = runs_of(factory, "wf")
    assert len(runs) == 1 and runs[0]["status"] == "success", runs
    records = records_of(factory, runs[0]["id"])
    by = {r["node_id"]: r for r in records}
    assert set(by) == {"a", "b", "c", "m", "brief"}, "one record per step, in one run"
    merged = by["m"]["output"]["data"]
    # In arrival order: C finished first (it released the other two).
    assert merged["inputs"][0]["from"] == "c"
    assert sorted(i["from"] for i in merged["inputs"]) == ["a", "b", "c"]
    assert merged["missing"] == []
    assert by["m"]["port"] == "success" and by["brief"]["status"] == "success"
    handed = [c for c in s.calls if c["name"] == "Morning digest · Brief me"][0]["trigger"]
    texts = [i["text"] for i in handed["data"]["data"]["inputs"]]
    assert sorted(texts) == ["feed A: 3 items", "feed B: 2 items", "feed C: 1 item"]
    assert runs[0]["result"] == "Morning digest · Brief me: done"


async def test_steps_that_drive_a_model_take_turns(factory):
    """Inside one run, model-driven steps take a per-run lock one at a time
    (`SLICE-CD-DESIGN` § 1.4) — the run holds one model-slot permit."""
    inside, most = [0], [0]

    async def model(task, run_id):
        inside[0] += 1
        most[0] = max(most[0], inside[0])
        await asyncio.sleep(0.05)
        inside[0] -= 1
        return f"{task.name} said"

    seed_workflow(factory, [node("p", "Ask one"), node("q", "Ask two"), node("r", "Ask three")],
                  [arrow("start", "p"), arrow("start", "q"), arrow("start", "r")])
    s = recording_scheduler({"Morning digest · Ask one": model,
                             "Morning digest · Ask two": model,
                             "Morning digest · Ask three": model})
    await s._execute_task("wf")
    assert runs_of(factory, "wf")[0]["status"] == "success"
    assert most[0] == 1, "two model steps of one run were inside the model at once"
    assert len([c for c in s.calls if c["kind"] == "llm"]) == 3


async def test_no_more_than_four_deterministic_steps_at_once(factory):
    """`WORKFLOW_PARALLEL_STEPS` — mistake prevention, not a control."""
    from src.task_scheduler import WORKFLOW_PARALLEL_STEPS

    inside, most = [0], [0]

    async def work(task, run_id):
        inside[0] += 1
        most[0] = max(most[0], inside[0])
        await asyncio.sleep(0.05)
        inside[0] -= 1
        return "ok"

    steps = [node(f"s{i}", f"Step {i}", "action", action="tidy_sessions") for i in range(6)]
    seed_workflow(factory, steps, [arrow("start", f"s{i}") for i in range(6)])
    s = recording_scheduler({f"Morning digest · Step {i}": work for i in range(6)})
    await s._execute_task("wf")
    assert WORKFLOW_PARALLEL_STEPS == 4
    assert most[0] == 4, most
    assert len(s.calls) == 6
    assert runs_of(factory, "wf")[0]["status"] == "success"


async def test_merge_first_goes_on_with_the_first_and_runs_once(factory):
    release = asyncio.Event()

    async def slow(task, run_id):
        await asyncio.wait_for(release.wait(), timeout=5)
        return "slow arrived"

    async def fast(task, run_id):
        return "fast arrived"

    async def after(task, run_id):
        release.set()
        return "went on"

    seed_workflow(factory, [
        node("fast", "Fast", "action", action="tidy_sessions"),
        node("slow", "Slow", "action", action="tidy_documents"),
        node("m", "First in", "merge", mode="first"),
        node("go", "Go on", "action", action="consolidate_memory"),
    ], [arrow("start", "fast"), arrow("start", "slow"), arrow("fast", "m"),
        arrow("slow", "m"), arrow("m", "go")])
    s = recording_scheduler({"Morning digest · Slow": slow, "Morning digest · Fast": fast,
                             "Morning digest · Go on": after})
    await s._execute_task("wf")
    run = runs_of(factory, "wf")[0]
    records = records_of(factory, run["id"])
    merges = [r for r in records if r["node_id"] == "m"]
    assert len(merges) == 1, "a Merge runs once"
    data = merges[0]["output"]["data"]
    assert [i["from"] for i in data["inputs"]] == ["fast"]
    assert data["missing"] == [{"from": "slow", "why": "it had not finished"}]
    # It went on before the slow branch finished — the slow one finished after.
    names = [c["name"] for c in s.calls]
    assert names.index("Morning digest · Go on") < len(names)
    assert {r["node_id"]: r["status"] for r in records} == {
        "fast": "success", "slow": "success", "m": "success", "go": "success"}
    assert run["status"] == "success"


async def test_a_merge_names_a_branch_that_failed_and_the_run_fails_naming_it(factory):
    from src.builtin_actions import NodeResult

    seed_workflow(factory, [
        node("a", "Feed A", "action", action="tidy_sessions"),
        node("b", "Feed B", "action", action="tidy_documents"),
        node("m", "Merge", "merge", mode="all"),
        node("brief", "Brief", "action", action="consolidate_memory"),
    ], [arrow("start", "a"), arrow("start", "b"), arrow("a", "m"), arrow("b", "m"),
        arrow("m", "brief")])
    s = recording_scheduler({"Morning digest · Feed B": NodeResult("error", payload="503 from the feed")})
    await s._execute_task("wf")
    run = runs_of(factory, "wf")[0]
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["m"]["output"]["data"]["missing"] == [{"from": "b", "why": "it failed"}]
    assert by["brief"]["status"] == "success", "the merge went on with what arrived"
    # Feed B's failure had no arrow out of its failure port: the run failed,
    # and its error names the step.
    assert run["status"] == "error"
    assert run["error"] == "“Feed B” failed: 503 from the feed"
    assert by["b"]["port"] == "error"


async def test_if_routes_urgent_mail_one_way_and_the_rest_the_other(factory):
    """`P22-10`'s `Verify:` shape, two webhook bodies: one says URGENT and goes
    the `then` way, the other `otherwise`; the branch not taken never runs."""
    from src.event_bus import TRIGGER_SOURCE_WEBHOOK, WEBHOOK_PAYLOAD_FIELDS, build_trigger

    seed_workflow(factory, [
        node("is-urgent", "Is it urgent?", "if", join="all", conditions=[
            {"left": "{{ steps.start.data.body }}", "op": "contains", "right": "urgent"}]),
        node("page", "Page me", "action", action="tidy_sessions"),
        node("file", "File it", "action", action="tidy_documents"),
    ], [arrow("start", "is-urgent"), arrow("is-urgent", "page", "then"),
        arrow("is-urgent", "file", "otherwise")], trigger_type="webhook")
    s = recording_scheduler()
    await s._execute_task("wf", trigger=build_trigger(
        TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": "URGENT: the server is down"},
        fields=WEBHOOK_PAYLOAD_FIELDS))
    await s._execute_task("wf", trigger=build_trigger(
        TRIGGER_SOURCE_WEBHOOK, "webhook", {"body": "a newsletter"},
        fields=WEBHOOK_PAYLOAD_FIELDS))
    first, second = runs_of(factory, "wf")
    assert [c["name"] for c in s.calls] == ["Morning digest · Page me", "Morning digest · File it"]
    r1 = {r["node_id"]: r for r in records_of(factory, first["id"])}
    r2 = {r["node_id"]: r for r in records_of(factory, second["id"])}
    assert r1["is-urgent"]["port"] == "then" and set(r1) == {"is-urgent", "page"}
    assert r2["is-urgent"]["port"] == "otherwise" and set(r2) == {"is-urgent", "file"}
    assert any("Went the “then” way" in (st.get("detail") or "") for st in first["steps"])


async def test_a_switch_takes_its_first_matching_case_and_set_renames_a_field(factory):
    seed_workflow(factory, [
        node("route", "Route", "switch", cases=[
            {"id": "bank", "label": "From the bank", "join": "all", "conditions": [
                {"left": "{{ steps.start.data.from_address }}", "op": "contains", "right": "bank"}]},
            {"id": "any", "label": "Anything", "join": "all", "conditions": [
                {"left": "{{ steps.start.data.subject }}", "op": "is_empty"}]},
        ]),
        node("rename", "Rename", "set", fields=[
            {"name": "headline", "value": "{{ steps.start.data.subject }}"}]),
        node("note", "Note it", "action", action="tidy_sessions"),
        node("else", "Ignore", "action", action="tidy_documents"),
    ], [arrow("start", "route"), arrow("route", "rename", "case:bank"),
        arrow("route", "else", "otherwise"), arrow("rename", "note")],
        trigger_type="event", trigger_event="email_received")
    from src.event_bus import build_trigger
    s = recording_scheduler()
    await s._execute_task("wf", trigger=build_trigger("event", "email_received", {
        "account": "home", "folder": "INBOX", "message_key": "1",
        "from_address": "alerts@bank.example", "subject": "Statement ready"}))
    run = runs_of(factory, "wf")[0]
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["route"]["port"] == "case:bank"
    assert by["rename"]["output"]["data"] == {"headline": "Statement ready"}
    handed = [c for c in s.calls if c["name"] == "Morning digest · Note it"][0]["trigger"]
    assert handed["data"]["data"] == {"headline": "Statement ready"}
    assert "else" not in by
    assert any("“From the bank”" in (st.get("detail") or "") for st in run["steps"])
