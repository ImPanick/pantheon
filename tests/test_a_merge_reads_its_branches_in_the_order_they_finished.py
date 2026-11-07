# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1860` — branches that finish in the same tick are read in the order they
finished: the Merge's `inputs[]`, the run's log, and the run's result ("what
the step that finished last made").

The walker's loop read `for finished in done:` over the SET `asyncio.wait`
answers, so when several branches finished inside one tick of the loop they
were handled in the set's hash order — the Merge's arrival order, which output
was "last", and the order of the run's lines changed from one run of the same
document to the next (`test_steps_run_side_by_side_and_merge.py::
test_three_feeds_at_once_then_merge_all_then_brief_me` failed most runs). Each
step's coroutine is now stamped by a done callback, which asyncio runs in the
order the tasks finish.

Driven through the real `TaskScheduler._execute_task` on a real SQLite file.
Four held branches (the parallel cap) are released by the test in one go, in
an order that is not the document's, so all four finish inside one tick; the
order each executor RETURNED in is recorded by the executor itself and is what
every assertion compares against. Three release orders are run, so a set order
that happened to match one by chance cannot pass the test.
"""

import asyncio

import pytest

from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
)

pytestmark = pytest.mark.asyncio

FEEDS = ("a", "b", "c", "d")
RELEASE_ORDERS = (("d", "b", "a", "c"), ("c", "d", "b", "a"), ("b", "c", "d", "a"))


@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "finish_order.db")


def _feeds(started: list, returned: list, gates: dict):
    def held(feed: str):
        async def run(task, run_id):
            started.append(feed)
            await asyncio.wait_for(gates[feed].wait(), timeout=5)
            returned.append(feed)
            return f"feed {feed.upper()}"
        return run
    return {f"Morning digest · Feed {f.upper()}": held(f) for f in FEEDS}


async def _run_released(factory, task_id: str, order, *, merge: bool):
    started, returned = [], []
    gates = {f: asyncio.Event() for f in FEEDS}
    actions = ("tidy_sessions", "tidy_documents", "consolidate_memory", "tidy_sessions")
    nodes = [node(f, f"Feed {f.upper()}", "action", action=a) for f, a in zip(FEEDS, actions)]
    edges = [arrow("start", f) for f in FEEDS]
    if merge:
        nodes.append(node("m", "Merge", "merge", mode="all"))
        edges += [arrow(f, "m") for f in FEEDS]
    seed_workflow(factory, nodes, edges, task_id=task_id)
    s = recording_scheduler(_feeds(started, returned, gates))
    job = asyncio.create_task(s._execute_task(task_id))
    for _ in range(500):
        if set(started) == set(FEEDS):
            break
        await asyncio.sleep(0.01)
    assert set(started) == set(FEEDS), "the four feeds did not all start side by side"
    for feed in order:                       # one go: all four finish in one tick
        gates[feed].set()
    await asyncio.wait_for(job, timeout=10)
    assert returned == list(order), returned
    [run] = runs_of(factory, task_id)
    assert run["status"] == "success", run
    return run, returned


async def test_a_merge_lists_its_inputs_in_the_order_the_branches_finished(factory):
    for n, order in enumerate(RELEASE_ORDERS):
        run, returned = await _run_released(factory, f"wf{n}", order, merge=True)
        by = {r["node_id"]: r for r in records_of(factory, run["id"])}
        merged = by["m"]["output"]["data"]
        assert [i["from"] for i in merged["inputs"]] == returned, (
            f"released {order}: the Merge read {[i['from'] for i in merged['inputs']]}")
        assert merged["missing"] == []


async def test_the_run_log_and_result_follow_the_order_the_branches_finished(factory):
    for n, order in enumerate(RELEASE_ORDERS):
        run, returned = await _run_released(factory, f"wf{n}", order, merge=False)
        logged = [st["node"] for st in run["steps"]
                  if st.get("kind") == "node" and st.get("node") in FEEDS]
        assert logged == returned, f"released {order}: the log reads {logged}"
        # "What the step that finished last made."
        assert run["result"] == f"feed {returned[-1].upper()}", (order, run["result"])
