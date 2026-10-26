# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1066` — the canvas knows a step's action cannot be described by a dry run
from a verdict on the wire, not from one sentence of the plan.

**Measured before this file:** `canvas.js` (`planFor`) found the step a dry
run cannot describe by looking for the line that starts *"A dry run cannot
tell you what this would change"* in its plan (`CANNOT_SAY`). Nothing on the
wire said which actions those are: a plan entry was `{task_id, name, when,
depth, steps, declined}` and `/meta/actions` served no verdict. So rewording
the sentence in `dry_run_plan` left both steps saying "Would run:
consolidate_memory — …" with a `→`, as if the plan described them.

Now every plan entry — a chain's (`plan_dry_chain`) and a workflow's
(`dry_node_entries`) — carries `dry`, `action_dry_verdict`'s word, and the
canvas reads that.

Driven (`Law 20`): the real task route over a real SQLite file answers the
chain dry run with `dry_run_plan`'s sentence reworded (the planner is wrapped,
nothing else); the real workflow route answers a workflow's; and the real
`canvas.js`, in the shared DOM shim, is handed a chain whose sentence is
reworded.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import src.builtin_actions as ba  # noqa: E402
from test_a_dry_run_plans_the_whole_chain import (  # noqa: E402,F401
    _dry, _write, calls, client, scheduler, task_db,
)
import test_the_workbench_shows_what_a_chain_would_do_js as chain_js  # noqa: E402
from test_the_workbench_shows_what_a_chain_would_do_js import box  # noqa: E402,F401

SENTENCE = "A dry run cannot tell you what this would change."
REWORDED = "Only a real run can show you what this one changes."


@pytest.fixture()
def reworded(monkeypatch):
    """`dry_run_plan`, with the sentence the canvas used to look for said
    another way — what an edit to its words would do."""
    real = ba.dry_run_plan

    def plan(**kw):
        return [line.replace(SENTENCE, REWORDED) for line in real(**kw)]
    monkeypatch.setattr(ba, "dry_run_plan", plan)


def test_each_entry_of_a_chain_s_plan_carries_the_step_s_verdict(client, task_db, reworded):
    _write(task_db,
           [("h", {"name": "Backup"}),                                   # tidy_sessions
            ("m", {"name": "Tidy memories", "action": "consolidate_memory"}),
            ("s", {"name": "Audit skills", "action": "audit_skills"}),
            ("x", {"name": "Restart", "action": "ssh_command", "prompt": "systemctl restart web"}),
            ("p", {"name": "Summarise", "task_type": "llm", "action": None, "prompt": "Sum it up"})],
           [("h", "then_task_id", "m"), ("m", "then_task_id", "s"),
            ("h", "else_task_id", "x"), ("x", "then_task_id", "p")])
    r = _dry(client, "h")
    assert r.status_code == 200, r.text
    chain = {e["task_id"]: e for e in r.json()["chain"]}
    assert {k: e["dry"] for k, e in chain.items()} == {
        "h": "describes", "m": "cannot", "s": "cannot", "x": "shows-input", "p": None}
    # The words changed and the verdict did not.
    lines = [st["detail"] for st in chain["m"]["steps"]]
    assert any(REWORDED in line for line in lines) and not any(SENTENCE in line for line in lines)


@pytest.mark.asyncio
async def test_each_step_of_a_workflow_s_plan_carries_its_verdict(monkeypatch, tmp_path, reworded):
    from tests.helpers.walker_harness import (
        app_for, arrow, client_for, make_db, node, recording_scheduler, seed_workflow,
    )
    factory = make_db(monkeypatch, tmp_path / "wf-dry.db")
    seed_workflow(factory, [
        node("n1", "Summarise my inbox"),
        node("n2", "Tidy my memories", "action", action="consolidate_memory"),
        node("n3", "Tidy my chats", "action", action="tidy_sessions"),
    ], [arrow("n1", "n2"), arrow("n2", "n3")])
    s = recording_scheduler()
    async with client_for(app_for(factory, s, monkeypatch)) as http:
        res = await http.post("/api/tasks/wf/run?dry=true", headers={"x-test-user": "alice"})
    assert res.status_code == 200, res.text
    nodes = {e["node_id"]: e for e in res.json()["nodes"]}
    assert {k: e["dry"] for k, e in nodes.items()} == {
        "n1": None, "n2": "cannot", "n3": "describes"}
    assert s.calls == [], "a dry run runs nothing"


# ── the canvas reads the verdict ────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_rewording_the_sentence_leaves_the_canvas_saying_so(box):
    reply = chain_js._reply()
    for entry in reply["chain"]:
        for step in entry["steps"]:
            step["detail"] = step["detail"].replace(SENTENCE, REWORDED)
    assert not any(SENTENCE in json.dumps(e) for e in reply["chain"])
    o = chain_js._case(box, """
        const { root } = await mount();
        await press(root, 'A');
        out({ A: plan(root, 'A'), C: plan(root, 'C'), D: plan(root, 'D') });
    """, reply=reply)
    for k in ("C", "D"):
        assert o[k]["state"] == "cannot", o[k]
        assert o[k]["line"] == SENTENCE
        assert o[k]["mark"] == "?"
    assert o["A"]["state"] == "planned" and o["A"]["line"].startswith("Would run: daily_brief")


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_a_plan_that_says_the_sentence_without_the_verdict_is_not_marked(box):
    """The other half of reading the verdict: the words alone mark nothing."""
    reply = chain_js._reply()
    for entry in reply["chain"]:
        entry["dry"] = None
    o = chain_js._case(box, """
        const { root } = await mount();
        await press(root, 'A');
        out({ C: plan(root, 'C') });
    """, reply=reply)
    assert o["C"]["state"] == "planned", o["C"]
