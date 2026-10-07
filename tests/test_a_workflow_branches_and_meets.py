# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-10` / `P22-11` / `P22-12` … `P22-18` — the document rule for Slices C
and D (`src/workflow_document.py`, `SLICE-CD-DESIGN` § 1.3, contract C-R).

Pure functions, called (`Law 20`, option 1):

  * **ports** — `ports_of` per kind; an arrow on a port its step does not have
    is refused;
  * **fan-out** — several arrows on one port are allowed; only the exact same
    arrow twice is refused;
  * **the merge rule** — two branches that can run at the same time must meet
    at a Merge (`needs_merge`); Slice B's exclusive converging (`success` /
    `error` into one step) stays valid (`Law 1`); `concurrent_arrivals` is held
    equal to the path-by-path rule the design states, on generated graphs;
  * **loops over every arrow** — through a Switch case, through a second arrow
    on one port (which `document_rows`' one-arrow-per-port reading could not
    see), told in `describe_graph_refusal`'s words; on a document with one
    arrow per port the loop found is exactly `validate_graph`'s;
  * **start arrows** — the start may lead to several steps; a document with
    none keeps its single implied entry;
  * **resources** — what a step may name, failing closed when none are given;
  * **what a step needs to run**, `node_needs_model`, `node_effects`,
    `needs_test_confirmation` and `plan_lines` per kind.
"""

import itertools
import json
import random
from types import SimpleNamespace

import pytest

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

from src import workflow_document as wd  # noqa: E402
from src.task_scheduler import describe_graph_refusal, validate_graph  # noqa: E402

RES = wd.WorkflowResources(
    integrations={"miniflux": {"name": "Miniflux", "enabled": True},
                  "gone": {"name": "Gone", "enabled": False}},
    mcp_tools={"mcp__chat__send_message": {"input_schema": {"type": "object", "properties": {
        "channel": {"type": "string"}, "text": {"type": "string"}}},
        "disabled": False, "is_readonly": False},
        "mcp__chat__list": {"input_schema": {}, "disabled": False, "is_readonly": True},
        "mcp__chat__off": {"input_schema": {}, "disabled": True}},
    skills=frozenset({"print-queue"}), ai_tools=frozenset({"web_search", "web_fetch"}),
    workstation_why=None, foreach_max_items=50, wait_max_hours=2)


def step(node_id, kind="llm", label=None, **config):
    if kind == "llm" and "prompt" not in config:
        config["prompt"] = "Summarise."
    return {"id": node_id, "kind": kind, "label": label or node_id.upper(),
            "config": config, "position": None, "pinned": None}


def arrow(a, b, port="success"):
    return {"from": a, "port": port, "to": b}


def doc(nodes, edges=()):
    return wd.parse_graph({"v": 1, "nodes": list(nodes), "edges": list(edges)})


def check(graph, *, admin=True, resources=RES):
    return wd.validate_document(graph, owner="alice", tasks_by_id={}, crew_ids=set(),
                                owner_is_admin=admin, own_task_id="trigger",
                                resources=resources)


IF = dict(conditions=[{"left": "{{ steps.start.data.subject }}", "op": "contains",
                       "right": "urgent"}])
CASES = [{"id": "urgent", "label": "Urgent", "conditions": IF["conditions"]},
         {"id": "boss", "label": "From the boss",
          "conditions": [{"left": "{{ steps.start.data.from }}", "op": "contains",
                          "right": "boss"}]}]


# ── Ports ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("node,ports", [
    (step("a"), ("success", "error")),
    (step("a", "research", prompt="q"), ("success", "error")),
    (step("a", "action", action="tidy_sessions"), ("success", "error")),
    (step("a", "run_task", task_id="t"), ("success", "error")),
    (step("a", "http"), ("success", "error")), (step("a", "mcp"), ("success", "error")),
    (step("a", "skill"), ("success", "error")), (step("a", "code"), ("success", "error")),
    (step("a", "foreach"), ("success", "error")),
    (step("a", "if", **IF), ("then", "otherwise")),
    (step("a", "switch", cases=CASES), ("case:urgent", "case:boss", "otherwise")),
    (step("a", "switch", cases=[{"id": "x"}, {"id": "x"}, {"id": "bad id"}, "junk"]),
     ("case:x", "otherwise")),
    (step("a", "set"), ("success",)), (step("a", "merge"), ("success",)),
    (step("a", "wait"), ("success",)), (step("a", "teleport"), ()),
    ("start", ("success",)),
])
def test_each_kind_leaves_by_its_own_ports(node, ports):
    assert wd.ports_of(node) == ports


def test_the_new_words_are_added_and_none_renamed():
    assert wd.NODE_KINDS[:4] == ("llm", "research", "action", "run_task")
    assert set(wd.NODE_KINDS[4:]) == {"if", "switch", "set", "merge", "wait", "foreach",
                                      "http", "mcp", "skill", "code"}
    assert wd.PORT_WORDS == ("success", "error", "then", "otherwise")
    assert wd.CASE_PORT_PREFIX == "case:" and wd.START_KEY == "start"
    assert wd.port_words(step("a", "switch", cases=CASES), "case:boss") == "From the boss"
    assert wd.port_words(step("a"), "error") == "if it fails"


@pytest.mark.parametrize("node,port,words", [
    (step("a"), "then", "neither “if it works” nor “if it fails”"),
    (step("a", "if", **IF), "success", "leaves by 'success', and it leaves by “then”, “otherwise”"),
    (step("a", "switch", cases=CASES), "case:other", "“Urgent”, “From the boss”, “otherwise”"),
    (step("a", "set", fields=[{"name": "x", "value": "1"}]), "error", "leaves by 'error'"),
])
def test_an_arrow_on_a_port_its_step_does_not_have_is_refused(node, port, words):
    refusal = check(doc([node, step("b")], [arrow("a", "b", port)]))
    assert refusal.reason == wd.REFUSE_BAD_EDGE and words in refusal.sentence, refusal


# ── Fan-out, and the same arrow twice ────────────────────────────────────────

def test_one_port_may_lead_to_several_steps():
    graph = doc([step("a"), step("b"), step("c")], [arrow("a", "b"), arrow("a", "c")])
    assert check(graph) is None
    assert [n["id"] for n in wd.next_nodes(graph, "a", "success")] == ["b", "c"]
    assert wd.next_node(graph, "a", "success")["id"] == "b"
    assert wd.next_nodes(graph, "a", "error") == []


def test_only_the_exact_same_arrow_twice_is_refused():
    refusal = check(doc([step("a", label="Fetch"), step("b", label="Send")],
                        [arrow("a", "b"), arrow("a", "b")]))
    assert refusal.reason == wd.REFUSE_TWO_ARROWS
    assert refusal.sentence == ("A step has the same arrow twice: “Fetch” → “Send”, if it works, "
                                "is drawn twice. Remove one.")
    twice = wd.parse_graph({"v": 1, "nodes": [step("a")],
                            "edges": [arrow("start", "a"), arrow("start", "a")]})
    assert check(twice).reason == wd.REFUSE_TWO_ARROWS


# ── The merge rule ───────────────────────────────────────────────────────────

def test_two_branches_that_run_together_must_meet_at_a_merge():
    nodes = [step("a"), step("b"), step("c"), step("d", label="Brief me")]
    edges = [arrow("a", "b"), arrow("a", "c"), arrow("b", "d"), arrow("c", "d")]
    refusal = check(doc(nodes, edges))
    assert refusal.reason == wd.REFUSE_NEEDS_MERGE
    assert refusal.sentence == ("Two branches that run at the same time both reach “Brief me”. "
                                "Put a Merge step before it.")
    assert refusal.node_ids == ("d", "b", "c")
    nodes[3] = step("d", "merge", label="Brief me", mode="all")
    assert check(doc(nodes, edges)) is None


@pytest.mark.parametrize("nodes,edges", [
    # Slice B: success and error into one step — a step leaves by one port.
    ([step("a"), step("b"), step("c")], [arrow("a", "c"), arrow("a", "b", "error"), arrow("b", "c")]),
    ([step("a", "if", **IF), step("b"), step("c"), step("d")],
     [arrow("a", "b", "then"), arrow("a", "c", "otherwise"), arrow("b", "d"), arrow("c", "d")]),
    ([step("a", "switch", cases=CASES), step("b"), step("c"), step("d"), step("e")],
     [arrow("a", "b", "case:urgent"), arrow("a", "c", "case:boss"), arrow("a", "d", "otherwise"),
      arrow("b", "e"), arrow("c", "e"), arrow("d", "e")]),
    # exclusive further up: the two branches part at `a` by different ports
    ([step("a", "if", **IF), step("b"), step("c"), step("x"), step("d")],
     [arrow("a", "b", "then"), arrow("a", "c", "otherwise"), arrow("b", "x"), arrow("x", "d"),
      arrow("c", "d")]),
])
def test_branches_that_cannot_both_run_may_meet_anywhere(nodes, edges):
    assert check(doc(nodes, edges)) is None
    assert wd.concurrent_arrivals(doc(nodes, edges)) == []


@pytest.mark.parametrize("edges", [
    [arrow("start", "a"), arrow("start", "b"), arrow("a", "d"), arrow("b", "d")],
    [arrow("start", "a"), arrow("start", "d"), arrow("a", "d")],
    [arrow("start", "a"), arrow("a", "b"), arrow("a", "c"), arrow("b", "d"), arrow("c", "x"),
     arrow("x", "d")],
    # the branches part at `a` by the SAME port, then each meets an If: still together
    [arrow("start", "a"), arrow("a", "b"), arrow("a", "c"), arrow("b", "d", "then"),
     arrow("c", "d", "otherwise")],
])
def test_branches_that_part_by_one_port_run_together(edges):
    ids = {i for e in edges for i in (e["from"], e["to"])} - {"start"}
    kinds = {"b": "if", "c": "if"} if any(e["port"] == "then" for e in edges) else {}
    nodes = [step(i, kinds.get(i, "llm"), **(IF if kinds.get(i) == "if" else {})) for i in sorted(ids)]
    graph = wd.parse_graph({"v": 1, "nodes": nodes, "edges": edges})
    assert check(graph).reason == wd.REFUSE_NEEDS_MERGE


def _brute_force_arrivals(graph):
    """The design's rule, path by path: two arrivals at one step are
    exclusive iff their paths leave some shared step by different ports."""
    out = {}
    for e in graph["edges"]:
        out.setdefault(e["from"], []).append(e)
    starts = wd.start_edges(graph) or [arrow("start", n["id"]) for n in wd._entries(graph)]
    arrivals = {}

    def walk(edge, choices):
        arrivals.setdefault(edge["to"], []).append(((edge["from"], edge["port"]), choices))
        for nxt in out.get(edge["to"], ()):
            walk(nxt, {**choices, edge["to"]: nxt["port"]})

    for edge in starts:
        walk(edge, {"start": "success"})
    found = set()
    for node, items in arrivals.items():
        for (k1, c1), (k2, c2) in itertools.combinations(items, 2):
            if k1 == k2 or k1[0] == k2[0]:
                continue
            c1, c2 = {**c1, k1[0]: k1[1]}, {**c2, k2[0]: k2[1]}
            if all(c1[s] == c2[s] for s in set(c1) & set(c2)):
                found.add((node, frozenset((k1, k2))))
    return found


def test_the_merge_rule_is_the_path_by_path_rule_on_generated_graphs():
    rng = random.Random(2211)
    kinds = [("llm", ("success", "error")), ("if", ("then", "otherwise")), ("set", ("success",)),
             ("switch", ("case:a", "case:b", "otherwise"))]
    tried = with_pairs = 0
    for _ in range(1500):
        n = rng.randint(2, 7)
        chosen = [rng.choice(kinds) for _ in range(n)]
        nodes = [step(f"n{i}", k, **({"cases": [{"id": "a"}, {"id": "b"}]} if k == "switch" else {}))
                 for i, (k, _p) in enumerate(chosen)]
        edges, drawn = [], set()
        for i in range(n):
            for j in range(i + 1, n):
                if rng.random() < 0.45:
                    e = arrow(f"n{i}", f"n{j}", rng.choice(chosen[i][1]))
                    if (e["from"], e["port"], e["to"]) not in drawn:
                        drawn.add((e["from"], e["port"], e["to"]))
                        edges.append(e)
        if rng.random() < 0.5:
            edges += [arrow("start", f"n{j}") for j in range(n) if rng.random() < 0.35]
        graph = wd.parse_graph({"v": 1, "nodes": nodes, "edges": edges})
        fast = {(a.node_id, frozenset(((a.first["from"], a.first["port"]),
                                       (a.second["from"], a.second["port"]))))
                for a in wd.concurrent_arrivals(graph)}
        assert fast == _brute_force_arrivals(graph), edges
        tried += 1
        with_pairs += bool(fast)
    assert tried == 1500 and with_pairs > 300, with_pairs


def test_the_merge_rule_stays_cheap_on_the_widest_document():
    """Twenty steps, every one leading to every later one on one port: 2^18
    paths into the last. A path-by-path rule could not answer at save; this
    one answers at once."""
    nodes = [step(f"n{i}") for i in range(20)]
    edges = [arrow(f"n{i}", f"n{j}") for i in range(20) for j in range(i + 1, 20)]
    nodes[-1] = step("n19", "merge")
    graph = doc(nodes, edges)
    found = wd.concurrent_arrivals(graph)
    assert {a.node_id for a in found} == {f"n{i}" for i in range(2, 20)}
    refusal = check(graph)
    assert refusal.reason == wd.REFUSE_NEEDS_MERGE and refusal.node_ids[0] == "n2"


# ── Loops over every arrow ───────────────────────────────────────────────────

def test_a_loop_through_a_second_arrow_on_one_port_is_found():
    """`document_rows` read one arrow per port, so the loop below — through
    the second `success` arrow out of “Fetch” — was invisible to it."""
    graph = doc([step("a", label="Fetch"), step("b", label="Log"), step("c", label="Retry")],
                [arrow("a", "b"), arrow("a", "c"), arrow("c", "a")])
    refusal = check(graph)
    assert refusal.reason == wd.REFUSE_CYCLE
    assert refusal.sentence == ("The workflow loops back on itself: if “Fetch” works it runs "
                                "“Retry”, and if “Retry” works it runs “Fetch” again. Remove one "
                                "of those links to save it.")
    assert set(refusal.node_ids) == {"a", "c"}


def test_a_loop_through_a_case_port_is_told_in_its_words_at_save_and_at_run():
    graph = doc([step("t", "switch", label="Triage", cases=CASES), step("e", label="Escalate")],
                [arrow("t", "e", "case:urgent"), arrow("e", "t", "error")])
    refusal = check(graph)
    assert refusal.reason == wd.REFUSE_CYCLE
    assert refusal.sentence == ("The workflow loops back on itself: if “Triage” goes the “Urgent” "
                                "way it runs “Escalate”, and if “Escalate” fails it runs “Triage” "
                                "again. Remove one of those links to save it.")
    loop = wd.find_loop(graph)
    assert describe_graph_refusal(loop, names={"t": "Triage", "e": "Escalate"},
                                  lead="the workflow loops back on itself") == refusal.sentence
    otherwise = doc([step("i", "if", label="Check", **IF), step("x", label="X")],
                    [arrow("i", "x", "otherwise"), arrow("x", "i")])
    assert "if “Check” goes the “otherwise” way it runs “X”" in check(otherwise).sentence


def test_a_step_that_leads_to_itself_is_a_loop():
    refusal = check(doc([step("a", label="Again")], [arrow("a", "a", "error")]))
    assert refusal.reason == wd.REFUSE_CYCLE and "if “Again” fails it runs “Again” again" \
        in refusal.sentence


def test_on_one_arrow_per_port_the_loop_found_is_the_chain_rule_s_loop():
    """`Law 1`: where Slice B's reading saw every arrow, the loop and its
    sentence are exactly what `validate_graph` over the projected rows said."""
    rng = random.Random(2205)
    compared = loops = 0
    for _ in range(1500):
        n = rng.randint(1, 8)
        ids = [f"n{i}" for i in range(n)]
        edges = []
        for i in ids:
            for port in ("success", "error"):
                if rng.random() < 0.55:
                    edges.append(arrow(i, rng.choice(ids), port))
        graph = doc([step(i, label=i.upper()) for i in ids], edges)
        rows = [SimpleNamespace(id=i, owner=None,
                                then_task_id=next((e["to"] for e in edges
                                                   if e["from"] == i and e["port"] == "success"), None),
                                else_task_id=next((e["to"] for e in edges
                                                   if e["from"] == i and e["port"] == "error"), None))
                for i in ids]
        old = validate_graph(rows, starts=ids, owner=None, max_depth=n + 1)
        new = wd.find_loop(graph)
        assert (old is None) == (new is None), edges
        if old is not None:
            names = {i: i.upper() for i in ids}
            assert describe_graph_refusal(new, names) == describe_graph_refusal(old, names), edges
            loops += 1
        compared += 1
    assert compared == 1500 and loops > 300


# ── Start arrows ─────────────────────────────────────────────────────────────

def test_the_start_may_lead_to_several_steps():
    graph = wd.parse_graph({"v": 1, "nodes": [step("a"), step("b"), step("m", "merge"),
                                              step("z")],
                            "edges": [arrow("start", "a"), arrow("start", "b"), arrow("a", "m"),
                                      arrow("b", "m"), arrow("m", "z")]})
    assert check(graph) is None
    assert [n["id"] for n in wd.start_nodes(graph)] == ["a", "b"]
    assert wd.entry_node(graph)["id"] == "a"
    assert [(e["node"]["id"], e["when"], e["depth"], e["parent"]) for e in wd.reachable_bfs(graph)] \
        == [("a", None, 0, None), ("b", None, 0, None), ("m", "success", 1, "a"),
            ("z", "success", 2, "m")]
    hook = SimpleNamespace(trigger_type="webhook", trigger_event=None)
    for node_id in ("a", "b"):
        assert wd.node_input_shape(graph, node_id, hook).source == "webhook"
    assert wd.node_input_shape(graph, "m", hook).source == "task"


def test_a_document_with_no_start_arrows_keeps_its_one_implied_entry():
    graph = doc([step("a"), step("b")], [arrow("a", "b")])
    assert wd.start_edges(graph) == [] and [n["id"] for n in wd.start_nodes(graph)] == ["a"]
    assert check(graph) is None
    assert check(doc([step("a"), step("b")])).reason == wd.REFUSE_SEVERAL_STARTS


@pytest.mark.parametrize("edges,reason,words", [
    ([arrow("start", "a", "error")], wd.REFUSE_BAD_EDGE, "the start has one way out"),
    ([arrow("start", "ghost")], wd.REFUSE_BAD_EDGE, "not in the workflow"),
    ([arrow("start", "a"), arrow("a", "start")], wd.REFUSE_BAD_EDGE, "not in the workflow"),
    ([arrow("start", "a")], wd.REFUSE_SEVERAL_STARTS,
     "“B”. Connect each to the start or to the step before it, or remove it"),
])
def test_a_start_arrow_is_checked_like_any_other(edges, reason, words):
    graph = wd.parse_graph({"v": 1, "nodes": [step("a"), step("b")], "edges": edges})
    refusal = check(graph)
    assert refusal.reason == reason and words in refusal.sentence, refusal


def test_upstream_is_every_step_with_a_path_here_and_not_the_start():
    graph = wd.parse_graph({"v": 1, "nodes": [step(i) for i in "abcdm"],
                            "edges": [arrow("start", "a"), arrow("start", "b"), arrow("a", "c"),
                                      arrow("b", "m"), arrow("c", "m"), arrow("m", "d")]})
    assert wd.upstream_of(graph, "d") == {"a", "b", "c", "m"}
    assert wd.upstream_of(graph, "c") == {"a"} and wd.upstream_of(graph, "a") == frozenset()


# ── What a step may reach ────────────────────────────────────────────────────

@pytest.mark.parametrize("node,reason,field", [
    (step("h", "http", integration="miniflux", method="GET", path="/"), wd.REFUSE_UNKNOWN_INTEGRATION,
     "integration"),
    (step("m", "mcp", tool="mcp__chat__send_message"), wd.REFUSE_UNKNOWN_TOOL, "tool"),
    (step("s", "skill", skill="print-queue"), wd.REFUSE_UNKNOWN_SKILL, "skill"),
    (step("c", "code", language="bash", source="echo hi"), wd.REFUSE_WORKSTATION, ""),
    (step("p", tools=["web_search"]), wd.REFUSE_UNKNOWN_TOOL, "tools"),
])
def test_with_no_resources_every_effect_step_is_refused(node, reason, field):
    """Fail closed: a caller that passes nothing gets no Integration, no tool,
    no skill and no workstation — never everything."""
    for resources in (None, wd.EMPTY_RESOURCES, "not resources"):
        refusal = check(doc([node]), resources=resources)
        assert (refusal.reason, refusal.field) == (reason, field), refusal
    assert check(doc([node])) is None


@pytest.mark.parametrize("node,reason,words", [
    (step("h", "http", integration="gone", method="GET", path="/"), wd.REFUSE_UNKNOWN_INTEGRATION,
     "switched off"),
    (step("m", "mcp", tool="mcp__chat__off"), wd.REFUSE_UNKNOWN_TOOL, "'mcp__chat__off'"),
    (step("m", "mcp", tool="mcp__nobody__x"), wd.REFUSE_UNKNOWN_TOOL, "'mcp__nobody__x'"),
    (step("s", "skill", skill="someone-elses"), wd.REFUSE_UNKNOWN_SKILL, "'someone-elses'"),
    (step("p", tools=["web_search", "bash"]), wd.REFUSE_UNKNOWN_TOOL, "'bash'"),
])
def test_a_step_names_only_what_the_person_can_reach(node, reason, words):
    refusal = check(doc([node]))
    assert refusal.reason == reason and words in refusal.sentence, refusal


def test_http_and_mcp_steps_are_an_admin_s_inside_a_for_each_too():
    for node in (step("h", "http", integration="miniflux", method="GET", path="/"),
                 step("m", "mcp", tool="mcp__chat__send_message")):
        refusal = check(doc([node]), admin=False)
        assert refusal.reason == wd.REFUSE_ADMIN_ONLY and "only an admin's agent can" \
            in refusal.sentence
        wrapped = step("f", "foreach", list="{{ steps.start.data.items }}",
                       step={"kind": node["kind"], "config": node["config"]})
        refusal = check(doc([wrapped]), admin=False)
        assert refusal.reason == wd.REFUSE_ADMIN_ONLY and refusal.field == "step"
    inner_ssh = step("f", "foreach", list="{{ steps.start.data.items }}",
                     step={"kind": "action", "config": {"action": "ssh_command", "prompt": "uptime"}})
    assert check(doc([inner_ssh]), admin=False).reason == wd.REFUSE_ADMIN_ONLY
    assert check(doc([inner_ssh]), admin=True) is None


def test_a_code_step_is_greyed_with_the_workstation_s_own_sentence():
    node = step("c", "code", language="python", source="print(1)")
    off = RES._replace(workstation_why="Your workstation is switched off.")
    refusal = check(doc([node]), resources=off)
    assert refusal.reason == wd.REFUSE_WORKSTATION
    assert refusal.sentence.endswith("“C”. Your workstation is switched off.")
    assert check(doc([node])) is None


@pytest.mark.parametrize("kind", wd.FOREACH_REFUSED_KINDS)
def test_a_for_each_repeats_one_step_of_any_kind_but_the_flow_ones(kind):
    refusal = check(doc([step("f", "foreach", list="{{ steps.start.data.items }}",
                              step={"kind": kind, "config": {}})]))
    assert refusal.reason == wd.REFUSE_FOREACH_INNER and refusal.field == "step.kind", refusal


def test_a_for_each_reads_one_picked_list_and_its_step_reads_the_item():
    good = step("f", "foreach", list="{{ steps.start.data.emails }}", on_error="continue",
                step={"kind": "llm", "label": "Summarise",
                      "config": {"prompt": "Summarise {{ item.subject }} from {{ item.from }}"}})
    assert check(doc([good])) is None
    for listed in ("emails", "{{ steps.start.data.a }} and {{ steps.start.data.b }}", None):
        bad = json.loads(json.dumps(good))
        bad["config"]["list"] = listed
        refusal = check(doc([bad]))
        assert refusal.reason == wd.REFUSE_MISSING_SETTING and refusal.field == "list", refusal
    inner_bad = json.loads(json.dumps(good))
    inner_bad["config"]["step"]["kind"] = "teleport"
    assert check(doc([inner_bad])).reason == wd.REFUSE_BAD_KIND
    outside = check(doc([step("p", prompt="Summarise {{ item.subject }}")]))
    assert outside.reason == wd.REFUSE_BAD_REFERENCE and "only the step inside a For-each" \
        in outside.sentence
    own_list = json.loads(json.dumps(good))
    own_list["config"]["list"] = "{{ item.list }}"
    assert check(doc([own_list])).reason == wd.REFUSE_BAD_REFERENCE


# ── What each kind needs ─────────────────────────────────────────────────────

@pytest.mark.parametrize("node,reason,words", [
    (step("i", "if"), wd.REFUSE_MISSING_SETTING, "needs a condition"),
    (step("i", "if", conditions="x"), wd.REFUSE_BAD_SETTING, "list of up to 20 conditions"),
    (step("i", "if", conditions=[{"left": "a", "op": "regex", "right": "b"}]),
     wd.REFUSE_BAD_SETTING, "'regex' is not a test"),
    (step("i", "if", conditions=[{"left": "a", "op": "equals", "right": {"o": 1}}]),
     wd.REFUSE_BAD_SETTING, "a condition's value must be"),
    (step("i", "if", conditions=[{"left": "a", "op": "equals", "code": "x"}]),
     wd.REFUSE_BAD_SETTING, "a field, a test and a value"),
    (step("i", "if", join="some", **IF), wd.REFUSE_BAD_SETTING, "all or any"),
    (step("s", "switch"), wd.REFUSE_MISSING_SETTING, "at least one way"),
    (step("s", "switch", cases=[CASES[0], CASES[0]]), wd.REFUSE_BAD_SETTING, "share the id"),
    (step("s", "switch", cases=[{**CASES[0], "label": "x" * 61}]), wd.REFUSE_BAD_SETTING,
     "up to 60 characters"),
    (step("s", "switch", cases=[{**CASES[0], "conditions": []}]), wd.REFUSE_MISSING_SETTING,
     "needs a condition for “Urgent”"),
    (step("s", "set"), wd.REFUSE_MISSING_SETTING, "a field to make"),
    (step("s", "set", fields=[{"name": "a b", "value": 1}]), wd.REFUSE_BAD_SETTING, "letters"),
    (step("s", "set", fields=[{"name": "a", "value": 1}, {"name": "a", "value": 2}]),
     wd.REFUSE_BAD_SETTING, "twice"),
    (step("m", "merge", mode="most"), wd.REFUSE_BAD_SETTING, "all of its branches or the first"),
    (step("w", "wait"), wd.REFUSE_MISSING_SETTING, "how long to wait"),
    (step("w", "wait", mode="for", minutes=121), wd.REFUSE_BAD_SETTING,
     "workflow_wait_max_hours"),
    (step("w", "wait", mode="for", minutes=0), wd.REFUSE_BAD_SETTING, "whole number"),
    (step("w", "wait", mode="until", time="8am"), wd.REFUSE_BAD_SETTING, "like 08:00"),
    (step("w", "wait", mode="until", time="24:00"), wd.REFUSE_BAD_SETTING, "like 08:00"),
    (step("w", "wait", mode="until", time="08:00", tz="Mars/Olympus"), wd.REFUSE_BAD_SETTING,
     "not a time zone"),
    (step("h", "http", integration="miniflux", method="TRACE", path="/"), wd.REFUSE_BAD_SETTING,
     "GET, POST, PUT, PATCH, DELETE"),
    (step("h", "http", integration="miniflux", path="v1"), wd.REFUSE_BAD_SETTING, "starts with /"),
    (step("h", "http", integration="miniflux", path="/x#y"), wd.REFUSE_BAD_SETTING, "starts with /"),
    (step("h", "http", integration="miniflux", path="//evil.example/x?u=http://a"),
     wd.REFUSE_BAD_SETTING, "no address"),
    (step("h", "http", integration="miniflux", path="/", body_mode="form"), wd.REFUSE_BAD_SETTING,
     "as JSON"),
    (step("h", "http", integration="miniflux", path="/", headers=[{"name": "Bad Header",
                                                                   "value": "v"}]),
     wd.REFUSE_BAD_SETTING, "Header names"),
    (step("h", "http", integration="miniflux", path="/", query=[{"name": "a", "value": "1"},
                                                               {"name": "a", "value": "2"}]),
     wd.REFUSE_BAD_SETTING, "Query names"),
    (step("h", "http"), wd.REFUSE_MISSING_SETTING, "an Integration"),
    (step("m", "mcp"), wd.REFUSE_MISSING_SETTING, "needs a tool"),
    (step("m", "mcp", tool="mcp__chat__send_message", args=["x"]), wd.REFUSE_BAD_SETTING,
     "named arguments"),
    (step("s", "skill"), wd.REFUSE_MISSING_SETTING, "a skill to follow"),
    (step("c", "code", source="x"), wd.REFUSE_MISSING_SETTING, "Python or bash"),
    (step("c", "code", language="python", source="  "), wd.REFUSE_MISSING_SETTING, "code to run"),
    (step("c", "code", language="python", source="x" * 20_001), wd.REFUSE_BAD_SETTING, "20,000"),
    (step("c", "code", language="python", source="x", timeout_seconds=601), wd.REFUSE_BAD_SETTING,
     "1 to 600"),
    (step("c", "code", language="python", source="x",
          input=[{"name": "a", "value": 1}, {"name": "a", "value": 2}]),
     wd.REFUSE_BAD_SETTING, "its own name"),
    (step("p", tools="web_search"), wd.REFUSE_BAD_SETTING, "a list of up to 64 tool names"),
    (step("p", tools=["web_search", "web_search"]), wd.REFUSE_BAD_SETTING, "names a tool twice"),
    (step("p", answer_fields=[{"name": "t", "type": "date"}]), wd.REFUSE_BAD_SETTING,
     "text, number, yes/no, list"),
    (step("p", answer_fields=[{"name": "t", "type": "text"}, {"name": "t", "type": "list"}]),
     wd.REFUSE_BAD_SETTING, "two answer fields"),
    (step("p", answer_fields=[{"name": "t", "type": "text"}] * 21), wd.REFUSE_BAD_SETTING,
     "up to 20 fields"),
    (step("f", "foreach", list="{{ steps.start.data.x }}",
          step={"kind": "llm", "config": {"prompt": 5}}), wd.REFUSE_BAD_SETTING,
     "the step it repeats"),
    (step("f", "foreach", list="{{ steps.start.data.x }}", on_error="retry",
          step={"kind": "llm", "config": {"prompt": "p"}}), wd.REFUSE_BAD_SETTING, "stops or goes on"),
    (step("f", "foreach", list="{{ steps.start.data.x }}"), wd.REFUSE_MISSING_SETTING,
     "a step to repeat"),
])
def test_each_new_kind_says_what_it_is_missing_in_words(node, reason, words):
    refusal = check(doc([node]))
    assert refusal is not None and refusal.reason == reason, refusal
    assert words in refusal.sentence, refusal.sentence
    assert refusal.sentence[:1].isupper() and refusal.sentence.endswith("."), refusal.sentence


@pytest.mark.parametrize("node", [
    step("i", "if", join="any", **IF),
    step("s", "switch", cases=CASES),
    step("s", "set", fields=[{"name": "headline", "value": "{{ steps.start.data.subject }}"},
                             {"name": "n", "value": 3}, {"name": "tags", "value": ["a"]}]),
    step("m", "merge"), step("m", "merge", mode="first"),
    step("w", "wait", mode="for", minutes=120),
    step("w", "wait", mode="until", time="23:59", tz="Europe/London"),
    step("h", "http", integration="miniflux", method="GET", path="/v1/entries",
         headers=[{"name": "Accept", "value": "application/json"}],
         query=[{"name": "status", "value": "unread"}]),
    step("m", "mcp", tool="mcp__chat__send_message", args={"channel": "#ops", "text": "hi"}),
    step("s", "skill", skill="print-queue", prompt="Print the queue"),
    step("c", "code", language="bash", source="cat", timeout_seconds=30,
         input=[{"name": "x", "value": 1}]),
    step("p", tools=[], answer_fields=[{"name": "title", "type": "text", "description": "d"},
                                       {"name": "why", "type": "list"}]),
])
def test_a_good_step_of_each_new_kind_passes(node):
    assert check(doc([node])) is None


# ── What a step does ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("node,needs", [
    (step("a"), True), (step("a", "research"), True), (step("a", "skill"), True),
    (step("a", "run_task"), True),
    (step("a", "action", action="summarize_emails"), True),
    (step("a", "action", action="tidy_sessions"), False),
    (step("a", "http"), False), (step("a", "mcp"), False), (step("a", "code"), False),
    (step("a", "if"), False), (step("a", "switch"), False), (step("a", "set"), False),
    (step("a", "merge"), False), (step("a", "wait"), False),
    (step("a", "foreach", step={"kind": "llm", "config": {}}), True),
    (step("a", "foreach", step={"kind": "http", "config": {}}), False),
    (step("a", "foreach", step={"kind": "foreach", "config": {}}), False),
    (step("a", "foreach"), False), (step("a", "teleport"), True),
])
def test_only_a_step_a_model_drives_needs_the_model(node, needs):
    assert wd.node_needs_model(node) is needs


@pytest.mark.parametrize("node,effects,asks", [
    (step("h", "http", method="GET"), (), False),
    (step("h", "http", method="POST"), ("touches-remote",), True),
    (step("h", "http"), (), False),
    (step("m", "mcp", tool="mcp__chat__list"), (), False),
    (step("m", "mcp", tool="mcp__chat__send_message"), ("touches-remote",), True),
    (step("m", "mcp", tool="mcp__unknown__x"), ("touches-remote",), True),
    (step("c", "code"), ("runs-code",), True),
    (step("s", "skill"), ("calls-model",), False),
    (step("i", "if"), (), False), (step("s", "switch"), (), False), (step("s", "set"), (), False),
    (step("m", "merge"), (), False), (step("w", "wait"), (), False),
    (step("p", tools=["web_search"]), ("calls-model",), False),
    (step("f", "foreach", step={"kind": "code", "config": {}}), ("runs-code",), True),
    (step("f", "foreach", step={"kind": "llm", "config": {}}), ("calls-model",), False),
    (step("f", "foreach", step={"kind": "run_task", "config": {}}), (), True),
])
def test_testing_a_step_asks_first_only_where_it_reaches_out(node, effects, asks):
    assert wd.node_effects(node, {}, RES) == effects
    assert wd.needs_test_confirmation(node, {}, RES) is asks


def test_an_mcp_tool_not_known_to_be_read_only_asks_without_resources():
    node = step("m", "mcp", tool="mcp__chat__list")
    assert wd.needs_test_confirmation(node) is True and wd.needs_test_confirmation(node, {}, RES) \
        is False


def test_plan_lines_show_what_you_typed_and_where_a_value_comes_from_never_a_value():
    http = step("h", "http", integration="miniflux", method="POST", path="/v1/entries",
                headers=[{"name": "Authorization", "value": "Bearer sk-PASTED"}],
                query=[{"name": "status", "value": "unread"}],
                body=[{"name": "title", "value": "{{ steps.fetch.data.title }}"}])
    lines = wd.plan_lines(http, RES)
    assert lines[0] == "Would call Miniflux — POST /v1/entries"
    assert "Header Authorization: as you typed it" in lines
    assert "Query status: unread" in lines and "Body title: {{ steps.fetch.data.title }}" in lines
    assert not any("sk-PASTED" in line for line in lines), "a typed header value is not shown"
    assert any(line.startswith("It would: changes something") for line in lines)

    mcp = wd.plan_lines(step("m", "mcp", tool="mcp__chat__send_message",
                             args={"channel": "#ops", "text": "{{ steps.sum.text }}"}), RES)
    assert mcp[:3] == ["Would call the tool mcp__chat__send_message", "channel: #ops",
                       "text: {{ steps.sum.text }}"]
    code = wd.plan_lines(step("c", "code", language="python", source="a\nb\nc\nd",
                              input=[{"name": "prices", "value": "{{ steps.a.data.prices }}"}]))
    assert code[:2] == ["Would run 4 lines of Python in your workstation, as you.",
                        "Hands it prices: {{ steps.a.data.prices }}"]
    if_lines = wd.plan_lines(step("i", "if", join="any", **IF))
    # P23-05 (WB-U-7): the plan says the port's own words.
    assert if_lines == ["Would go “if so” if any of these hold: {{ steps.start.data.subject }} "
                        "contains “urgent”; otherwise “otherwise”."]
    switch = wd.plan_lines(step("s", "switch", cases=CASES))
    assert switch[1].startswith("“Urgent” if all of these hold:") and \
        switch[-1] == "and the “otherwise” way if none does."
    assert wd.plan_lines(step("s", "set", fields=[{"name": "headline",
                                                   "value": "{{ steps.a.data.subject }}"}])) == \
        ["Would make these fields:", "headline ← {{ steps.a.data.subject }}"]
    assert wd.plan_lines(step("w", "wait", mode="until", time="08:00")) == \
        ["Would wait until 08:00 (the trigger's time zone), or as soon after as Pantheon is idle."]
    assert wd.plan_lines(step("m", "merge", mode="first")) == \
        ["Would go on as soon as the first branch arrives."]
    each = wd.plan_lines(step("f", "foreach", list="{{ steps.a.data.emails }}",
                              step={"kind": "llm", "label": "Summarise",
                                    "config": {"prompt": "Sum {{ item.subject }}"}}), RES)
    assert each[0] == ("Would repeat “Summarise” for each item of {{ steps.a.data.emails }}, in "
                       "order, at most 50 items.")
    assert each[1] == "If an item fails it stops there."
    assert "  Its prompt, as written: Sum {{ item.subject }}" in each
    ssh = wd.plan_lines(step("a", "action", action="ssh_command", prompt="rm -rf /tmp/x"))
    assert any("rm -rf /tmp/x" in line for line in ssh), "a command is shown verbatim (P8-33)"
    ai = wd.plan_lines(step("p", prompt="Look up {{ steps.start.data.q }}", tools=["web_search"],
                            answer_fields=[{"name": "title", "type": "text"}]))
    assert "Its prompt, as written: Look up {{ steps.start.data.q }}" in ai
    assert "Tools it may use: web_search" in ai and "It answers with the fields: title" in ai


# ── Contract C-R (`SLICE-CD-DESIGN` § 3) ─────────────────────────────────────

def test_contract_c_r_is_what_the_other_three_packages_import():
    import inspect

    from src import workflow_logic, workflow_refs, workflow_slots

    for module, names in (
        (workflow_refs, ("parse_template", "RefError", "refs_in", "single_ref", "resolve",
                         "render_text", "render_value", "render_named_slots", "format_ref",
                         "flatten_fields", "MISSING", "build_context", "Ref", "Template")),
        (workflow_slots, ("MAPPING_VALUE", "MAPPING_NEVER", "MAPPINGS", "CARRY_INLINE",
                          "CARRY_CONTEXT", "Slot", "NODE_SLOTS", "action_param_slots",
                          "classify_argument", "CONTENT_WORDS", "FORMAT_WORDS", "slot_for",
                          "RenderedCall", "render_call", "SlotError")),
        (workflow_logic, ("OPERATORS", "JOINS", "OPERATOR_WORDS", "evaluate_condition",
                          "choose_port", "build_set")),
        (wd, ("WorkflowResources", "ports_of", "upstream_of", "concurrent_arrivals",
              "node_needs_model", "plan_lines", "NODE_KINDS", "PORT_WORDS", "PORT_THEN",
              "PORT_OTHERWISE", "CASE_PORT_PREFIX", "START_KEY", "DocumentRefusal",
              "validate_document", "find_loop", "start_nodes", "next_nodes", "node_effects",
              "needs_test_confirmation")),
    ):
        for name in names:
            assert hasattr(module, name), f"{module.__name__}.{name}"
    assert wd.DocumentRefusal._fields == ("reason", "node_ids", "sentence", "field")
    assert wd.DocumentRefusal("r", (), "s").field == ""
    assert workflow_slots.RenderedCall._fields == ("kind", "tool", "content", "value_paths",
                                                    "missing")
    assert workflow_slots.Slot._fields == ("mapping", "carry", "why")
    assert wd.WorkflowResources._fields == ("integrations", "mcp_tools", "skills", "ai_tools",
                                            "workstation_why", "foreach_max_items",
                                            "wait_max_hours")

    def params(fn):
        return [(p.name, p.kind.name) for p in inspect.signature(fn).parameters.values()]

    assert params(workflow_slots.render_call) == [("node", "POSITIONAL_OR_KEYWORD"),
                                                   ("ctx", "POSITIONAL_OR_KEYWORD"),
                                                   ("mcp_schema", "KEYWORD_ONLY")]
    assert params(wd.plan_lines)[:2] == [("node", "POSITIONAL_OR_KEYWORD"),
                                         ("resources", "POSITIONAL_OR_KEYWORD")]
    assert [p[0] for p in params(workflow_refs.render_named_slots)] == ["t", "ctx"]
    assert [p[0] for p in params(workflow_refs.format_ref)] == ["node_id", "field", "path"]
    assert [p[0] for p in params(workflow_refs.flatten_fields)] == ["value", "max_depth",
                                                                     "max_fields"]
