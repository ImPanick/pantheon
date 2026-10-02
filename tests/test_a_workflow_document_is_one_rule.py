# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-05` — a workflow is one document, and one set of functions says what it
may be (`src/workflow_document.py`, contract C1).

Pure functions, called (`Law 20`, option 1). The save route and the engine at
run ask `validate_document` the same question, so its every refusal is driven
here and the test at the bottom holds that no reason in
`WORKFLOW_REFUSAL_REASONS` goes undriven — a reason nobody can reach is a
sentence nobody has read (`Law 13`).
"""

import json
from types import SimpleNamespace

import pytest

from tests.helpers.import_state import clear_fake_database_modules

clear_fake_database_modules()

from src import workflow_document as wd  # noqa: E402
from src.event_bus import EVENT_PAYLOAD_FIELDS, TASK_HANDOFF_FIELDS  # noqa: E402
from src.task_scheduler import EDGE_CONDITIONS  # noqa: E402

OWNER = "alice"


def step(node_id, kind="llm", label=None, **config):
    if kind == "llm" and "prompt" not in config:
        config["prompt"] = "Summarise my inbox."
    return {"id": node_id, "kind": kind, "label": label or node_id.upper(),
            "config": config, "position": None, "pinned": None}


def arrow(a, b, port="success"):
    return {"from": a, "port": port, "to": b}


def doc(nodes, edges=()):
    return wd.parse_graph({"v": 1, "nodes": list(nodes), "edges": list(edges)})


def task(task_id, *, owner=OWNER, task_type="llm", action=None, name=None, **kw):
    return SimpleNamespace(id=task_id, owner=owner, task_type=task_type, action=action,
                           name=name or task_id, then_task_id=kw.get("then"),
                           else_task_id=kw.get("other"), prompt=kw.get("prompt", "p"),
                           model=None, endpoint_url=None, character_id=None,
                           crew_member_id=None, max_steps=None,
                           output_target=kw.get("output_target", "session"),
                           trigger_type=kw.get("trigger_type", "schedule"),
                           trigger_event=kw.get("trigger_event"),
                           schedule="daily", scheduled_time="08:00", scheduled_day=None,
                           scheduled_date=None, cron_expression=None, trigger_count=None,
                           tz_name="Europe/London", max_retries=2, timeout_seconds=None,
                           notifications_enabled=True, session_id=kw.get("session_id"))


def check(graph, *, tasks=(), crew=(), admin=False, own="trigger"):
    return wd.validate_document(graph, owner=OWNER, tasks_by_id={t.id: t for t in tasks},
                                crew_ids=set(crew), owner_is_admin=admin, own_task_id=own)


def parse_refusal(raw):
    with pytest.raises(wd.DocumentError) as err:
        wd.parse_graph(raw)
    return err.value.refusal


# Every refusal, driven. (name, thunk → DocumentRefusal, reason, words in it)
CASES = [
    ("not JSON", lambda: parse_refusal("{nope"), wd.REFUSE_UNREADABLE, "not JSON"),
    ("steps not a list", lambda: parse_refusal({"v": 1, "nodes": "x"}), wd.REFUSE_UNREADABLE, "lists"),
    ("a step with no id", lambda: parse_refusal({"v": 1, "nodes": [{"kind": "llm", "label": "A"}]}),
     wd.REFUSE_UNREADABLE, "step 1 has no id"),
    ("a position that is not two numbers",
     lambda: parse_refusal({"v": 1, "nodes": [dict(step("n1"), position=[1, "x"])]}),
     wd.REFUSE_UNREADABLE, "position"),
    ("an arrow with no end", lambda: parse_refusal({"v": 1, "nodes": [], "edges": [{"from": "a"}]}),
     wd.REFUSE_UNREADABLE, "arrow 1"),
    ("too big", lambda: parse_refusal(json.dumps({"v": 1, "nodes": [], "pad": "x" * (257 * 1024)})),
     wd.REFUSE_TOO_BIG, "256 KiB"),
    ("a newer version", lambda: parse_refusal({"v": 2, "nodes": []}), wd.REFUSE_VERSION, "version 2"),
    ("no steps", lambda: check(doc([])), wd.REFUSE_NO_STEPS, "add a step"),
    ("21 steps", lambda: check(doc([step(f"n{i}") for i in range(21)],
                                   [arrow(f"n{i}", f"n{i + 1}") for i in range(20)])),
     wd.REFUSE_TOO_MANY_STEPS, "it has 21"),
    ("an id called start", lambda: check(doc([step("start")])), wd.REFUSE_BAD_ID, "'start'"),
    ("an id with a colon", lambda: check(doc([step("a:b")])), wd.REFUSE_BAD_ID, "'a:b'"),
    ("two steps one id", lambda: check(doc([step("n1"), step("n1")])), wd.REFUSE_DUPLICATE_ID, "'n1'"),
    ("a kind nobody runs", lambda: check(doc([step("n1", kind="code")])), wd.REFUSE_BAD_KIND, "'code'"),
    ("no name", lambda: check(doc([dict(step("n1"), label="  ")])), wd.REFUSE_BAD_LABEL, "needs a name"),
    ("a long name", lambda: check(doc([step("n1", label="x" * 121)])), wd.REFUSE_BAD_LABEL, "120"),
    ("a setting it does not take",
     lambda: check(doc([step("n1", kind="research", prompt="q", character_id="socrates")])),
     wd.REFUSE_BAD_SETTING, "character_id"),
    ("a setting of the wrong type", lambda: check(doc([step("n1", prompt=["x"])])),
     wd.REFUSE_BAD_SETTING, "must be text"),
    ("max_steps out of range", lambda: check(doc([step("n1", max_steps=500)])),
     wd.REFUSE_BAD_SETTING, "1 to 200"),
    ("a prompt step with no prompt", lambda: check(doc([step("n1", prompt="  ")])),
     wd.REFUSE_MISSING_SETTING, "what to ask"),
    ("a research step with no question", lambda: check(doc([step("n1", kind="research")])),
     wd.REFUSE_MISSING_SETTING, "the question"),
    ("an action step with no action", lambda: check(doc([step("n1", kind="action")])),
     wd.REFUSE_MISSING_SETTING, "needs an action"),
    ("a command step with no command",
     lambda: check(doc([step("n1", kind="action", action="ssh_command")]), admin=True),
     wd.REFUSE_MISSING_SETTING, "needs its command"),
    ("a run-task step with no task", lambda: check(doc([step("n1", kind="run_task")])),
     wd.REFUSE_MISSING_SETTING, "a task to run"),
    ("an action this build lacks", lambda: check(doc([step("n1", kind="action", action="nope")])),
     wd.REFUSE_UNKNOWN_ACTION, "'nope'"),
    ("an admin-only action, not an admin",
     lambda: check(doc([step("n1", kind="action", action="run_local", prompt="ls")])),
     wd.REFUSE_ADMIN_ONLY, "requires admin privileges"),
    ("a run-task step into an admin-only task",
     lambda: check(doc([step("n1", kind="run_task", task_id="t9")]),
                   tasks=[task("t9", task_type="action", action="ssh_command")]),
     wd.REFUSE_ADMIN_ONLY, "requires admin privileges"),
    ("a task that does not exist", lambda: check(doc([step("n1", kind="run_task", task_id="gone")])),
     wd.REFUSE_UNKNOWN_TASK, "not one of yours"),
    ("another owner's task",
     lambda: check(doc([step("n1", kind="run_task", task_id="bobs")]), tasks=[task("bobs", owner="bob")]),
     wd.REFUSE_UNKNOWN_TASK, "not one of yours"),
    ("a workflow as a step",
     lambda: check(doc([step("n1", kind="run_task", task_id="w2")]),
                   tasks=[task("w2", task_type="workflow", name="Other flow")]),
     wd.REFUSE_WORKFLOW_TARGET, "Other flow"),
    ("this workflow itself", lambda: check(doc([step("n1", kind="run_task", task_id="trigger")])),
     wd.REFUSE_OWN_TRIGGER, "this workflow itself"),
    ("a stranger's crew member", lambda: check(doc([step("n1", crew_member_id="c9")]), crew=["c1"]),
     wd.REFUSE_UNKNOWN_CREW, "crew member"),
    ("an arrow to nowhere", lambda: check(doc([step("n1")], [arrow("n1", "n7")])),
     wd.REFUSE_BAD_EDGE, "not in the workflow"),
    ("an arrow on no port", lambda: check(doc([step("n1"), step("n2")], [arrow("n1", "n2", "maybe")])),
     wd.REFUSE_BAD_EDGE, "neither"),
    ("two arrows one outcome",
     lambda: check(doc([step("n1"), step("n2"), step("n3")], [arrow("n1", "n2"), arrow("n1", "n3")])),
     wd.REFUSE_TWO_ARROWS, "two “if it works” arrows"),
    ("a loop through the failure arrow",
     lambda: check(doc([step("n1", label="Backup"), step("n2", label="Cleanup")],
                       [arrow("n1", "n2", "error"), arrow("n2", "n1", "success")])),
     wd.REFUSE_CYCLE, "if “Backup” fails it runs “Cleanup”"),
    ("two first steps", lambda: check(doc([step("n1"), step("n2")])),
     wd.REFUSE_SEVERAL_STARTS, "“N1”, “N2”"),
    ("a sample for a step handed nothing",
     lambda: _pin_refusal(doc([step("n1")]), "n1", task("trigger"), {"x": 1}),
     wd.REFUSE_PIN_UNUSED, "first step"),
    ("a sample that is not fields",
     lambda: _pin_refusal(doc([step("n1")]), "n1",
                          task("trigger", trigger_type="event", trigger_event="email_received"), "mail"),
     wd.REFUSE_BAD_PIN, "account"),
    ("a chain with a workflow in it",
     lambda: _convert_refusal([task("h", then="w"), task("w", task_type="workflow", name="Flow")], "h"),
     wd.REFUSE_WORKFLOW_MEMBER, "“Flow” is a workflow"),
    ("a chain into another owner's task",
     lambda: _convert_refusal([task("h", then="x"), task("x", owner="bob", name="Secret")], "h"),
     wd.REFUSE_CROSS_OWNER, "another owner"),
]


def _pin_refusal(graph, node_id, trigger, data):
    with pytest.raises(wd.DocumentError) as err:
        wd.build_pin(graph, node_id, trigger, data)
    return err.value.refusal


def _convert_refusal(rows, head):
    with pytest.raises(wd.DocumentError) as err:
        wd.chain_to_document(rows, head)
    return err.value.refusal


@pytest.mark.parametrize("name,thunk,reason,words", CASES, ids=[c[0] for c in CASES])
def test_every_refusal_says_why_in_words(name, thunk, reason, words):
    refusal = thunk()
    assert isinstance(refusal, wd.DocumentRefusal), refusal
    assert refusal.reason == reason, refusal
    assert words in refusal.sentence, refusal.sentence
    assert refusal.sentence[:1].isupper() and refusal.sentence.endswith("."), refusal.sentence


def test_no_refusal_reason_goes_undriven():
    """`Law 13`. Every reason in the table is reached by a case above."""
    assert {c[2] for c in CASES} == set(wd.WORKFLOW_REFUSAL_REASONS)


def test_a_loop_is_named_by_its_steps_and_never_another_owners_task():
    refusal = CASES[[c[0] for c in CASES].index("a chain into another owner's task")][1]()
    assert "Secret" not in refusal.sentence
    loop = check(doc([step("n1", label="Backup"), step("n2", label="Cleanup")],
                     [arrow("n1", "n2", "error"), arrow("n2", "n1", "success")]))
    assert loop.sentence.startswith("The workflow loops back on itself:"), loop.sentence
    assert set(loop.node_ids) == {"n1", "n2"}


def test_a_good_document_of_every_kind_passes():
    graph = doc([step("n1", label="Summarise"),
                 step("n2", kind="research", label="Look it up", prompt="What changed?"),
                 step("n3", kind="action", label="Tidy", action="tidy_sessions"),
                 step("n4", kind="run_task", label="Report", task_id="t2"),
                 step("n5", label="Say it failed", crew_member_id="c1", max_steps=5)],
                [arrow("n1", "n2"), arrow("n1", "n5", "error"), arrow("n2", "n3"),
                 arrow("n3", "n4"), arrow("n5", "n4")])
    assert check(graph, tasks=[task("t2")], crew=["c1"]) is None
    # Converging branches are allowed: each step leaves by one port, so the
    # path a run takes is one line and no step runs twice.
    assert [e["node"]["id"] for e in wd.reachable_bfs(graph)] == ["n1", "n2", "n5", "n3", "n4"]
    assert [e["when"] for e in wd.reachable_bfs(graph)] == [None, "success", "error", "success", "success"]


def test_the_ports_are_the_chain_conditions_not_a_second_vocabulary():
    assert wd.PORTS is EDGE_CONDITIONS
    assert wd.NODE_KINDS == ("llm", "research", "action", "run_task")
    assert set(wd.NODE_CONFIG_FIELDS) == set(wd.NODE_KINDS)


def test_the_fingerprint_moves_on_an_edit_and_not_on_bookkeeping():
    base = doc([step("n1", label="Summarise"), step("n2", label="Send")], [arrow("n1", "n2")])
    fp = wd.content_fingerprint("Morning", base)
    moved = wd.merge_positions(base, {"n1": [10, 20], "n2": [30.5, 1], "start": [0, 0]})
    pinned = json.loads(json.dumps(base))
    pinned["nodes"][0]["pinned"] = {"source": "event", "event": "x", "data": {"a": 1}}
    reordered = json.loads(json.dumps(base))
    reordered["nodes"].reverse()
    assert wd.content_fingerprint("Morning", moved) == fp
    assert wd.content_fingerprint("Morning", pinned) == fp
    assert wd.content_fingerprint("Morning", reordered) == fp
    assert wd.content_fingerprint(" Morning ", base) == fp
    renamed = json.loads(json.dumps(base))
    renamed["nodes"][1]["label"] = "Send it"
    rewired = json.loads(json.dumps(base))
    rewired["edges"][0]["port"] = "error"
    reconfigured = json.loads(json.dumps(base))
    reconfigured["nodes"][0]["config"]["prompt"] = "Summarise my calendar."
    for edited in (renamed, rewired, reconfigured):
        assert wd.content_fingerprint("Morning", edited) != fp
    assert wd.content_fingerprint("Evening", base) != fp


def test_positions_merge_and_a_version_holds_no_pins():
    base = doc([step("n1")])
    merged = wd.merge_positions(base, {"n1": [1, 2], "start": [3, 4], "deleted": [5, 6]})
    assert merged["nodes"][0]["position"] == [1, 2]
    assert merged["start"]["position"] == [3, 4]
    assert base["nodes"][0]["position"] is None, "merge_positions copies"
    with pytest.raises(wd.DocumentError):
        wd.merge_positions(base, {"n1": [1]})
    pinned = json.loads(json.dumps(base))
    pinned["nodes"][0]["pinned"] = {"data": {}}
    assert wd.without_pins(pinned)["nodes"][0]["pinned"] is None
    assert pinned["nodes"][0]["pinned"] == {"data": {}}


def test_what_each_step_is_handed():
    graph = doc([step("n1", label="Classify"), step("n2", label="Reply"), step("n3")],
                [arrow("n1", "n2")])
    mail = task("trigger", trigger_type="event", trigger_event="email_received")
    hook = task("trigger", trigger_type="webhook")
    timer = task("trigger")
    assert wd.node_input_shape(graph, "n1", mail) == ("event", "email_received",
                                                      EVENT_PAYLOAD_FIELDS["email_received"])
    assert wd.node_input_shape(graph, "n1", hook) == ("webhook", "webhook",
                                                      ("body", "json", "query", "headers"))
    assert wd.node_input_shape(graph, "n1", timer) == (None, None, ())
    assert wd.node_input_shape(graph, "n2", timer) == ("task", "Classify", TASK_HANDOFF_FIELDS)
    # A draft step not connected yet would be handed a step's hand-off.
    assert wd.node_input_shape(graph, "n3", timer).source == "task"


def test_a_pin_is_built_by_the_one_envelope_builder_and_names_what_it_dropped():
    graph = doc([step("n1", label="Classify")])
    mail = task("trigger", trigger_type="event", trigger_event="email_received")
    envelope, dropped = wd.build_pin(graph, "n1", mail,
                                     {"account": "work", "folder": "INBOX",
                                      "message_key": "42", "subject": "Hi"})
    assert envelope["source"] == "event" and envelope["event"] == "email_received"
    assert envelope["data"] == {"account": "work", "folder": "INBOX", "message_key": "42"}
    assert dropped == ("subject",)


@pytest.mark.parametrize("node,asks", [
    (step("n", kind="action", action="tidy_sessions"), True),          # deletes
    (step("n", kind="action", action="check_email_urgency"), True),    # notifies, remote
    (step("n", kind="action", action="audit_skills"), True),           # rewrites
    (step("n", kind="action", action="run_local", prompt="ls"), True),  # runs code
    (step("n", kind="action", action="summarize_emails"), False),      # reads, writes, model
    (step("n", kind="action", action="daily_brief"), False),           # reads the mailbox
    (step("n"), False),
    (step("n", kind="research", prompt="q"), False),
    (step("n", kind="run_task", task_id="t2"), True),                  # really runs a task
])
def test_which_steps_ask_before_a_real_test(node, asks):
    assert wd.needs_test_confirmation(node, {"t2": task("t2")}) is asks


def test_a_run_task_steps_effects_are_its_tasks():
    tasks = {"t2": task("t2", task_type="action", action="tidy_research")}
    assert wd.node_effects(step("n", kind="run_task", task_id="t2"), tasks) == ("deletes",)
    assert wd.node_effects(step("n", kind="run_task", task_id="gone"), tasks) == ()


def test_a_chain_becomes_a_document_with_both_edges_and_its_head_s_trigger():
    rows = [task("h", name="Nightly backup", then="ok", other="bad", trigger_type="webhook",
                 prompt="Back it up", output_target="session"),
            task("ok", task_type="action", action="tidy_sessions", name="Tidy", prompt=None),
            task("bad", name="Tell me", prompt="Say the backup failed.", output_target="notification"),
            task("side", name="Weekly report", then="ok"),
            task("elsewhere", owner="bob", then="ok")]
    graph, trigger, notes = wd.chain_to_document(rows, "h", positions={"ok": [100, 40]})
    assert [n["label"] for n in graph["nodes"]] == ["Nightly backup", "Tidy", "Tell me"]
    assert [n["kind"] for n in graph["nodes"]] == ["llm", "action", "llm"]
    assert graph["nodes"][0]["config"]["prompt"] == "Back it up"
    assert graph["nodes"][1]["config"] == {"action": "tidy_sessions", "output_target": "session"}
    assert graph["nodes"][1]["position"] == [100, 40]
    assert graph["nodes"][2]["config"]["output_target"] == "notification"
    assert graph["edges"] == [{"from": "n1", "port": "success", "to": "n2"},
                              {"from": "n1", "port": "error", "to": "n3"}]
    assert trigger["trigger_type"] == "webhook" and trigger["tz_name"] == "Europe/London"
    assert trigger["max_retries"] == 2
    assert check(graph) is None, "a converted chain is a document the engine runs"
    joined = " ".join(notes)
    assert "3 steps" in joined and "“Weekly report” also leads into this chain" in joined
    assert "webhook address" in joined
    assert "bob" not in joined, "another owner's task is never named"


def test_a_looping_chain_is_refused_in_the_chain_rule_s_words():
    refusal = _convert_refusal([task("a", name="Backup", other="b"),
                                task("b", name="Cleanup", then="a")], "a")
    assert refusal.reason == wd.REFUSE_CYCLE
    assert "if “Backup” fails it runs “Cleanup”" in refusal.sentence


def test_the_stand_in_carries_exactly_its_fields():
    trig = task("trigger", session_id="chat-1")
    prompt = wd.node_stand_in(trig, "Morning", step("n1", label="Summarise",
                                                    output_target="notification"))
    assert (prompt.id, prompt.owner, prompt.name) == ("trigger", OWNER, "Morning · Summarise")
    assert (prompt.task_type, prompt.session_id, prompt.tz_name) == ("llm", "chat-1", "Europe/London")
    assert prompt.output_target == "notification"
    research = wd.node_stand_in(trig, "Morning", step("n2", kind="research", prompt="q"))
    assert research.session_id is None, "a report is keyed by its session; each gets its own"
    with pytest.raises(AttributeError):
        prompt.notifications_enabled  # noqa: B018 - the read is the assertion
    with pytest.raises(ValueError):
        wd.node_stand_in(trig, "Morning", step("n3", kind="run_task", task_id="t2"))


def test_contract_c1_is_exactly_what_the_routes_import():
    """`SLICE-B-DESIGN` § 7, contract C1 — the names and signatures `wf-api`
    imports, held here so a rename on this side fails on this side."""
    import inspect

    from src import task_action_policy, workflow_runs
    from src.task_scheduler import TaskScheduler

    for name in ("GRAPH_VERSION", "NODE_KINDS", "PORTS", "NODE_CONFIG_FIELDS",
                 "STAND_IN_FIELDS", "WORKFLOW_MAX_NODES", "WORKFLOW_GRAPH_MAX_BYTES",
                 "START_KEY", "WORKFLOW_REFUSAL_REASONS", "DocumentRefusal", "DocumentError",
                 "parse_graph", "validate_document", "content_fingerprint", "without_pins",
                 "merge_positions", "build_pin", "node_input_shape", "entry_node",
                 "next_node", "reachable_bfs", "node_effects", "needs_test_confirmation",
                 "chain_to_document", "WorkflowNodeTask", "node_stand_in"):
        assert hasattr(wd, name), name
    assert (wd.GRAPH_VERSION, wd.START_KEY) == (1, "start")
    assert wd.DocumentRefusal._fields == ("reason", "node_ids", "sentence")

    def sig(fn):
        return [(p.name, p.kind.name, p.default is inspect.Parameter.empty)
                for p in inspect.signature(fn).parameters.values()]

    kw = "KEYWORD_ONLY"
    pos = "POSITIONAL_OR_KEYWORD"
    assert sig(wd.validate_document) == [
        ("graph", pos, True), ("owner", kw, True), ("tasks_by_id", kw, True),
        ("crew_ids", kw, True), ("owner_is_admin", kw, True), ("own_task_id", kw, True)]
    assert sig(wd.chain_to_document) == [("rows", pos, True), ("head_id", pos, True),
                                         ("positions", kw, False)]
    assert [p[0] for p in sig(wd.build_pin)] == ["graph", "node_id", "trigger_task", "data"]
    assert [p[0] for p in sig(wd.node_input_shape)] == ["graph", "node_id", "trigger_task"]
    assert [p[0] for p in sig(wd.node_stand_in)] == ["trigger", "workflow_name", "node"]
    assert [p[0] for p in sig(workflow_runs.node_record_to_dict)] == ["rec"]
    assert [p[0] for p in sig(workflow_runs.last_node_record)] == ["db", "task_id", "node_id"]
    assert [p[0] for p in sig(workflow_runs.maybe_prune_node_records)] == ["db"]
    assert sig(TaskScheduler.test_workflow_node)[:4] == [
        ("self", pos, True), ("task", pos, True), ("workflow_name", pos, True), ("node", pos, True)]
    assert [p[:2] for p in sig(TaskScheduler.test_workflow_node)[4:]] == [
        ("input_envelope", kw), ("timeout", kw)]
    register = inspect.signature(TaskScheduler._execute_task).parameters["register_handle"]
    assert (register.kind.name, register.default) == (kw, True)
    assert [p[0] for p in sig(task_action_policy.admin_only_action_of)] == ["db", "task"]
    assert sig(task_action_policy.record_admin_refusal) == [
        ("db", pos, True), ("task", pos, True), ("run_id", kw, False), ("action", kw, False)]
