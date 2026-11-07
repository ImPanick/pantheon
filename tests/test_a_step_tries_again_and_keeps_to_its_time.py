# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1855` — a step's own retries and time limit.

Measured before this row, on `ea80706`: a workflow had one retry setting, the
start's `max_retries`, which ran the WHOLE workflow again; a step that failed
because a provider blinked failed the run, and a step that hung held it until
the run's own time limit. `parse_graph` dropped a step's `settings`. Now a
step may carry `settings: {retries, retry_wait_seconds, timeout_seconds}`: a
failed attempt is tried again after the wait, up to `retries` times, then its
failure port is taken as before; one attempt may take at most the time limit
("Stopped after 30 s: the step's time limit."). A step with no settings runs
exactly as it did.

Pure functions called, and the walker driven over the real scheduler
(`walker_harness`); only a step's far end is a recorder. The waits and limits
the walker reads are scaled down (`_quick`), never the rule's own ranges.
"""

import asyncio
import json

import pytest

from tests.helpers.walker_harness import (
    arrow, make_db, node, recording_scheduler, records_of, runs_of, seed_workflow, settle,
)


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "attempts.db")


def _quick(monkeypatch, scale=0.01):
    """The walker reads a step's settings through `step_settings`; this hands
    it the same settings with the wait and the limit scaled to test speed."""
    from src import workflow_document as wd
    real = wd.step_settings

    def scaled(node):
        out = real(node)
        if out is None:
            return None
        return dict(out, retry_wait_seconds=out["retry_wait_seconds"] * scale,
                    timeout_seconds=out["timeout_seconds"] * scale)
    monkeypatch.setattr(wd, "step_settings", scaled)


def _doc(nodes, edges=()):
    return {"v": 1, "nodes": nodes, "edges": list(edges)}


def _check(graph):
    from src import workflow_document as wd
    return wd.validate_document(wd.parse_graph(json.dumps(graph)), owner="alice",
                                tasks_by_id={}, crew_ids=set(), owner_is_admin=True,
                                own_task_id="wf")


def _tidy(**settings):
    step = node("a", "Tidy", "action", action="tidy_sessions")
    return dict(step, settings=settings) if settings else step


def test_settings_are_kept_and_each_one_is_held_to_its_range():
    from src import workflow_document as wd
    parsed = wd.parse_graph(json.dumps(_doc([_tidy(retries=2), dict(_tidy(), id="b", settings={})])))
    assert parsed["nodes"][0]["settings"] == {"retries": 2}
    assert "settings" not in parsed["nodes"][1], "no settings, no key"
    assert wd.step_settings(parsed["nodes"][0]) == {
        "retries": 2, "retry_wait_seconds": 30, "timeout_seconds": 0}
    assert wd.step_settings(parsed["nodes"][1]) is None
    assert _check(_doc([_tidy(retries=5, retry_wait_seconds=3600, timeout_seconds=86400)],
                       [arrow("start", "a")])) is None
    assert _check(_doc([_tidy(timeout_seconds=0)], [arrow("start", "a")])) is None
    cases = [
        ({"retries": 9}, "settings.retries",
         "A step has a setting it does not take: “Tidy” tries again 9 times; a step tries "
         "again from 0 to 5 times."),
        ({"retry_wait_seconds": 0}, "settings.retry_wait_seconds",
         "A step has a setting it does not take: “Tidy” waits 0 seconds before it tries "
         "again; that is from 1 to 3600 seconds."),
        ({"timeout_seconds": 3}, "settings.timeout_seconds",
         "A step has a setting it does not take: “Tidy” has a time limit of 3 seconds; that "
         "is 0 (none) or from 5 to 86400 seconds."),
        ({"retries": True}, "settings.retries", None),
        ({"tries": 2}, "settings.tries", None),
    ]
    for settings, field, sentence in cases:
        refused = _check(_doc([_tidy(**settings)], [arrow("start", "a")]))
        assert refused is not None and refused.reason == "bad_setting", settings
        assert refused.field == field and refused.node_ids == ("a",)
        if sentence:
            assert refused.sentence == sentence
    wait = dict(node("w", "Wait a minute", "wait", mode="for", minutes=1),
                settings={"retries": 1})
    refused = _check(_doc([wait], [arrow("start", "w")]))
    assert refused.sentence == ("A step has a setting it does not take: “Wait a minute” is a "
                                "Wait, which is not tried again and has no time limit of its own.")
    with pytest.raises(wd.DocumentError):
        wd.parse_graph(json.dumps(_doc([dict(_tidy(), settings=[1])])))


def test_a_for_eachs_repeated_step_may_carry_its_own_and_they_are_checked():
    each = node("each", "For each", "foreach", list="{{ steps.start.data.items }}",
                step={"kind": "action", "label": "Tidy",
                      "config": {"action": "tidy_sessions"}, "settings": {"retries": 1}})
    assert _check(_doc([each], [arrow("start", "each")])) is None
    each["config"]["step"]["settings"] = {"retries": 7}
    refused = _check(_doc([each], [arrow("start", "each")]))
    assert refused is not None and "the step it repeats tries again 7 times" in refused.sentence


def test_settings_are_an_edit_and_a_step_without_them_keeps_its_fingerprint():
    from src import workflow_document as wd

    def fp(nodes):
        return wd.content_fingerprint("W", wd.parse_graph(json.dumps(_doc(nodes))))
    assert fp([_tidy()]) == fp([dict(_tidy(), settings={})])
    assert fp([_tidy(retries=1)]) != fp([_tidy()])
    assert fp([_tidy(retries=1)]) != fp([_tidy(retries=2)])


def test_the_time_limit_is_said_in_words():
    from src.task_scheduler import step_time_limit_words
    assert step_time_limit_words(30) == "Stopped after 30 s: the step's time limit."
    assert step_time_limit_words(600) == "Stopped after 10 min: the step's time limit."


@pytest.mark.asyncio
async def test_a_failed_attempt_is_tried_again_and_the_record_counts_it(factory, monkeypatch):
    from src.builtin_actions import NodeResult
    _quick(monkeypatch)
    answers = iter([NodeResult("error", payload="The provider answered 503."),
                    NodeResult("error", payload="The provider answered 503."),
                    NodeResult("success", payload="Tidied.")])

    async def far_end(task, run_id):
        return next(answers)
    seed_workflow(factory, [_tidy(retries=2, retry_wait_seconds=30)], [arrow("start", "a")])
    s = recording_scheduler({"Morning digest · Tidy": far_end})
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    assert len(s.calls) == 3
    [rec] = records_of(factory, run["id"])
    assert rec["status"] == "success" and rec["attempt"] == 3
    lines = [st.get("detail") for st in rec["steps"]]
    assert "Attempt 1 of 3 failed: The provider answered 503. Trying again in under a second." \
        in lines
    assert "Attempt 2 of 3." in lines and "Attempt 3 of 3." in lines
    assert any(st.get("detail") == "“Tidy” failed (attempt 1 of 3). Trying again in under "
               "a second." for st in run["steps"])


@pytest.mark.asyncio
async def test_the_last_failure_takes_the_failure_port_as_before(factory, monkeypatch):
    from src.builtin_actions import NodeResult
    _quick(monkeypatch)
    seed_workflow(factory, [_tidy(retries=1),
                            node("e", "Tell me", "action", action="tidy_documents")],
                  [arrow("start", "a"), arrow("a", "e", "error")])
    s = recording_scheduler({"Morning digest · Tidy": NodeResult("error", payload="Down.")})
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["a"]["status"] == "error" and by["a"]["port"] == "error" and by["a"]["attempt"] == 2
    assert by["e"]["status"] == "success"
    assert [c["name"] for c in s.calls] == ["Morning digest · Tidy"] * 2 + [
        "Morning digest · Tell me"]


@pytest.mark.asyncio
async def test_a_step_without_settings_is_tried_once(factory):
    from src.builtin_actions import NodeResult
    seed_workflow(factory, [_tidy()], [arrow("start", "a")])
    s = recording_scheduler({"Morning digest · Tidy": NodeResult("error", payload="Down.")})
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    [rec] = records_of(factory, run["id"])
    assert rec["attempt"] == 1 and len(s.calls) == 1 and run["status"] == "error"


@pytest.mark.asyncio
async def test_an_attempt_past_the_time_limit_is_stopped_and_tried_again(factory, monkeypatch):
    _quick(monkeypatch)
    slow = {"first": True}

    async def far_end(task, run_id):
        if slow.pop("first", False):
            await asyncio.sleep(30)
        return "Tidied."
    seed_workflow(factory, [_tidy(retries=1, timeout_seconds=10)], [arrow("start", "a")])
    s = recording_scheduler({"Morning digest · Tidy": far_end})
    await asyncio.wait_for(s._execute_task("wf"), 10)
    [run] = runs_of(factory, "wf")
    [rec] = records_of(factory, run["id"])
    assert rec["status"] == "success" and rec["attempt"] == 2, rec
    assert any((st.get("detail") or "").startswith(
        "Attempt 1 of 2 failed: Stopped after under a second: the step's time limit")
        for st in rec["steps"])


@pytest.mark.asyncio
async def test_stop_ends_the_wait_between_attempts_at_once(factory, monkeypatch):
    from src.builtin_actions import NodeResult
    seed_workflow(factory, [_tidy(retries=3, retry_wait_seconds=3600)], [arrow("start", "a")])
    s = recording_scheduler({"Morning digest · Tidy": NodeResult("error", payload="Down.")})
    assert await s.run_task_now("wf") is True
    for _ in range(300):
        await asyncio.sleep(0.01)
        if len(s.calls) == 1:
            break
    await asyncio.sleep(0.05)                # into the hour's wait
    assert await s.stop_task("wf") is True
    await settle(s)
    [run] = runs_of(factory, "wf")
    assert run["status"] == "aborted", run
    assert len(s.calls) == 1, "it did not try again"
    [rec] = records_of(factory, run["id"])
    assert rec["status"] == "aborted"


@pytest.mark.asyncio
async def test_a_for_each_tried_again_runs_only_the_items_that_failed(factory, monkeypatch):
    _quick(monkeypatch)
    failed_once = set()

    async def far_end(task, run_id):
        if "item 2 of 3" in task.name and "2" not in failed_once:
            failed_once.add("2")
            raise RuntimeError("the model refused")
        return f"{task.name}: done"
    seed_workflow(factory, [
        node("fetch", "Fetch", "set", fields=[{"name": "items", "value": [1, 2, 3]}]),
        dict(node("each", "For each", "foreach", list="{{ steps.fetch.data.items }}",
                  step={"kind": "llm", "label": "Summarise", "config": {"prompt": "Sum."}}),
             settings={"retries": 1}),
    ], [arrow("start", "fetch"), arrow("fetch", "each")])
    s = recording_scheduler({f"Morning digest · Summarise · item {i} of 3": far_end
                             for i in (1, 2, 3)})
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    assert [c["name"].rsplit("· ", 1)[1] for c in s.calls] == [
        "item 1 of 3", "item 2 of 3", "item 3 of 3", "item 2 of 3"], "only the failed item again"
    records = records_of(factory, run["id"])
    items = {r["item"]: r for r in records if r["item"] is not None}
    assert len(items) == 3 and len([r for r in records if r["item"] is not None]) == 3
    assert [(items[i]["status"], items[i]["attempt"]) for i in (0, 1, 2)] == [
        ("success", 1), ("success", 2), ("success", 1)]
    own = next(r for r in records if r["node_id"] == "each" and r["item"] is None)
    assert own["attempt"] == 2 and own["output"]["data"]["worked"] == 3


@pytest.mark.asyncio
async def test_a_repeated_steps_own_settings_are_each_items(factory, monkeypatch):
    _quick(monkeypatch)
    tries = {}

    async def far_end(task, run_id):
        tries[task.name] = tries.get(task.name, 0) + 1
        if tries[task.name] == 1:
            raise RuntimeError("blinked")
        return "done"
    seed_workflow(factory, [
        node("fetch", "Fetch", "set", fields=[{"name": "items", "value": [1, 2]}]),
        node("each", "For each", "foreach", list="{{ steps.fetch.data.items }}",
             step={"kind": "llm", "label": "Summarise", "config": {"prompt": "Sum."},
                   "settings": {"retries": 1}}),
    ], [arrow("start", "fetch"), arrow("fetch", "each")])
    s = recording_scheduler({f"Morning digest · Summarise · item {i} of 2": far_end
                             for i in (1, 2)})
    await s._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    items = [r for r in records_of(factory, run["id"]) if r["item"] is not None]
    assert [(r["status"], r["attempt"]) for r in items] == [("success", 2), ("success", 2)]
    assert any(st.get("detail") == "Attempt 2 of 2." for st in items[0]["steps"])
