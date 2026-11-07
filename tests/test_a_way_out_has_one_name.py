# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1893` — a way out of a step has one name, on the canvas and in a run.

The audit (`port-words`): the canvas labels an If's arrows "if so" and
"otherwise", a Switch case's "if <its label>", and the one arrow out of a Set,
Merge or Wait step "then" (`workflowDiagram.js:PORT_WORDS`, `ONLY_WAY_WORD`,
`workflowSource.js:portWordsOf`). The run said "Went the “then” way." and
"Went the “From the bank” way, to …"; a loop refusal said "goes the “Urgent”
way" and, out of a Set step, "works". Three names for one arrow.

Now the server words a way out from one table (`workflow_document.
PORT_PHRASES`, `ONLY_WAY_PHRASE`, `port_words`), and these tests run the
browser's own table and rule under node and hold the two equal — a word
changed on one side and not the other fails here.

Driven (`Law 20`): the real browser modules under node; the real scheduler
running real workflows over a real SQLite file (`walker_harness`); the real
document rule at save.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src import workflow_document as wd
from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow,
)

ROOT = Path(__file__).resolve().parent.parent
DIAGRAM = ROOT / "static" / "js" / "tasks" / "workflowDiagram.js"
SOURCE = ROOT / "static" / "js" / "workbench" / "workflowSource.js"

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

URGENT = [{"left": "{{ steps.start.data.subject }}", "op": "contains", "right": "urgent"}]

# One of every kind of step, and the Switch cases a person writes: labelled,
# labelled with spaces around, and not labelled at all.
SAMPLES = [
    {"id": "a", "kind": kind, "label": kind, "config": {}}
    for kind in ("llm", "research", "action", "run_task", "http", "mcp", "skill", "code",
                 "foreach", "set", "merge", "wait")
] + [
    {"id": "i", "kind": "if", "label": "Is it urgent?", "config": {"conditions": URGENT}},
    {"id": "s", "kind": "switch", "label": "Route", "config": {"cases": [
        {"id": "bank", "label": "From the bank", "conditions": URGENT},
        {"id": "pad", "label": "  Padded  ", "conditions": URGENT},
        {"id": "bare", "conditions": URGENT},
    ]}},
]


def _browser(script: str):
    """Run `script` with the canvas's own modules imported, and read back the
    one JSON line it prints."""
    lead = (f"const D = await import({json.dumps(DIAGRAM.as_uri())});\n"
            f"const S = await import({json.dumps(SOURCE.as_uri())});\n")
    done = subprocess.run(["node", "--input-type=module", "-e", lead + script],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_node
def test_the_servers_table_is_the_canvass_table():
    said = _browser("console.log(JSON.stringify({ports: D.PORT_WORDS, only: D.ONLY_WAY_WORD}));")
    assert said["ports"] == wd.PORT_PHRASES
    assert said["only"] == wd.ONLY_WAY_PHRASE


@needs_node
def test_every_steps_ways_out_read_as_the_canvas_draws_them():
    said = _browser(
        f"const nodes = {json.dumps(SAMPLES)};\n"
        "console.log(JSON.stringify(nodes.map((n) => S.portWordsOf(n, S.portsOfNode(n)))));")
    server = [{port: wd.port_words(n, port) for port in wd.ports_of(n)} for n in SAMPLES]
    assert said == server
    # And what they are, in a person's words.
    by_id = dict(zip((n["id"] for n in SAMPLES), server))
    assert by_id["i"] == {"then": "if so", "otherwise": "otherwise"}
    assert by_id["s"] == {"case:bank": "if From the bank", "case:pad": "if Padded",
                          "case:bare": "if this case", "otherwise": "otherwise"}


# ── In a run ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def factory(monkeypatch, tmp_path):
    return make_db(monkeypatch, tmp_path / "ways.db")


def _said(run):
    return [st.get("detail") or "" for st in run["steps"]]


async def test_an_if_says_the_way_it_went_as_its_arrow_is_labelled(factory):
    seed_workflow(factory, [
        node("mail", "Read the mail", "set", fields=[{"name": "subject", "value": "urgent!"}]),
        node("check", "Is it urgent?", "if", join="all", conditions=[
            {"left": "{{ steps.mail.data.subject }}", "op": "contains", "right": "urgent"}]),
        node("page", "Page me", "action", action="tidy_sessions"),
    ], [arrow("start", "mail"), arrow("mail", "check"), arrow("check", "page", "then")])
    await recording_scheduler()._execute_task("wf")
    [run] = runs_of(factory, "wf")
    assert run["status"] == "success", run
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["check"]["port"] == "then", "the stored word is unchanged"
    assert by["check"]["output"]["text"] == "Went the “if so” way."
    assert "Went the “if so” way, to Page me" in _said(run), _said(run)
    assert not any("“then”" in line for line in _said(run)), _said(run)


async def test_a_switch_says_if_and_its_cases_label(factory):
    seed_workflow(factory, [
        node("mail", "Read the mail", "set", fields=[{"name": "from", "value": "bank"}]),
        node("route", "Route", "switch", cases=[
            {"id": "bank", "label": "From the bank", "join": "all", "conditions": [
                {"left": "{{ steps.mail.data.from }}", "op": "contains", "right": "bank"}]}]),
        node("file", "File it", "action", action="tidy_documents"),
    ], [arrow("start", "mail"), arrow("mail", "route"), arrow("route", "file", "case:bank")])
    await recording_scheduler()._execute_task("wf")
    [run] = runs_of(factory, "wf")
    by = {r["node_id"]: r for r in records_of(factory, run["id"])}
    assert by["route"]["port"] == "case:bank"
    assert by["route"]["output"]["text"] == "Went the “if From the bank” way."
    assert "Went the “if From the bank” way, to File it" in _said(run), _said(run)


# ── At save ──────────────────────────────────────────────────────────────────

def _check(nodes, edges):
    graph = wd.parse_graph({"v": 1, "nodes": nodes, "edges": edges})
    return wd.validate_document(graph, owner="alice", tasks_by_id={}, crew_ids=set(),
                                owner_is_admin=True, own_task_id="trigger",
                                resources=wd.WorkflowResources())


def _step(node_id, kind, label, **config):
    if kind == "llm":
        config.setdefault("prompt", "Summarise.")
    return {"id": node_id, "kind": kind, "label": label, "config": config,
            "position": None, "pinned": None}


def test_a_loop_out_of_a_step_with_one_way_out_says_then():
    refusal = _check([_step("t", "set", "Tidy", fields=[{"name": "x", "value": "1"}]),
                      _step("w", "llm", "Write")],
                     [{"from": "t", "port": "success", "to": "w"},
                      {"from": "w", "port": "success", "to": "t"}])
    assert refusal.reason == wd.REFUSE_CYCLE
    assert "if “Tidy” goes the “then” way it runs “Write”" in refusal.sentence, refusal.sentence
    assert "if “Write” works it runs “Tidy”" in refusal.sentence, "a task's two words are kept"


def test_a_loop_through_an_ifs_arrow_says_if_so():
    refusal = _check([_step("i", "if", "Check", conditions=URGENT), _step("x", "llm", "X")],
                     [{"from": "i", "port": "then", "to": "x"},
                      {"from": "x", "port": "success", "to": "i"}])
    assert "if “Check” goes the “if so” way it runs “X”" in refusal.sentence, refusal.sentence


def test_an_arrow_an_if_does_not_have_is_told_its_two_by_the_canvass_words():
    refusal = _check([_step("i", "if", "Check", conditions=URGENT), _step("x", "llm", "X")],
                     [{"from": "i", "port": "success", "to": "x"}])
    assert refusal.reason == wd.REFUSE_BAD_EDGE
    assert "it leaves by “if so”, “otherwise”" in refusal.sentence, refusal.sentence
