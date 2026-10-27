# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-05` / `P24-06` / `P24-07` — a hire's run is assembled from its file, it
leaves a report, and its effects table is enforced before anything runs.

Driven through the real `TaskScheduler._execute_llm_task` on a real SQLite
file, with a hire made by the real routes' store (`src.agents.hires`) from the
real shipped manifests. The agent loop is the one thing stood in for at the
`_run_agent_loop` seam: what is asserted is exactly what that seam is handed —
the system prompt, the tools, the slot — and what the run then keeps. The
effects gate is the real `ToolRunSecurityContext`, and the policy the loop is
handed is captured from the real `_run_agent_loop` at `stream_agent_loop`.

**Measured before this file, on `a28041c`:** none of this existed; a task's
tools were whatever retrieval picked for its prompt (`B1414`/`B1416`).
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from tests.test_a_workflow_is_kept_as_one_document import wf_db  # noqa: F401  (fixture)
from core.database import AgentHire, AgentRunReport, ScheduledTask, TaskRun
from src.agents import hires as H
from src.agents.catalogue import get_agent
from src.agents.runtime import AgentRunRefused, carried_forward


@pytest.fixture()
def world(wf_db, monkeypatch, tmp_path):
    import src.constants as constants
    import src.tool_security as ts
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ts, "owner_is_admin", lambda owner: owner == "alice")
    from src.task_scheduler import TaskScheduler
    monkeypatch.setattr(TaskScheduler, "_usable_route", lambda self, db, task, url, model: (url, model))
    sched = TaskScheduler(session_manager=None)
    seen = {}

    async def loop(endpoint_url, model, task, session_id, **kw):
        seen.update(kw, slot=dict(sched._runs().get(kw.get("run_id")) or {}))
        return seen.pop("answer", "Done.\n\n## Report\n- read the calendar\n\n## Carry forward\n- nothing")

    sched._run_agent_loop = loop
    return wf_db, sched, seen


def _hire(db, agent, owner="alice", **kw):
    m = get_agent(owner, agent)
    h = H.make_hire(db, owner=owner, manifest=m, **kw)
    db.commit()
    return h, m


def _run(sched, db, task, run_id=None):
    run_id = run_id or str(uuid.uuid4())
    if db.query(TaskRun).filter(TaskRun.id == run_id).first() is None:
        db.add(TaskRun(id=run_id, task_id=task.id, status="running"))
        db.commit()
    task.endpoint_url, task.model = "http://endpoint", "m-1"
    return run_id, asyncio.run(sched._execute_llm_task(task, db, run_id=run_id))


def _task(db, hire_id, n=0):
    return db.query(ScheduledTask).get(H.task_ids_of(db, hire_id)[n])


def test_a_run_is_told_its_runbook_and_offered_exactly_its_tools(world):
    factory, sched, seen = world
    db = factory()
    h, m = _hire(db, "morning-brief", inputs={"at": "06:00"})
    seen["answer"] = "Today: done."
    run_id, answer = _run(sched, db, _task(db, h.id))
    assert answer.startswith("Today: done.")
    prompt = seen["system_prompt"]
    assert prompt.startswith("You are Morning Brief, an agent alice summoned in Pantheon")
    assert m.runbook in prompt and "## Report" in prompt and "## Carry forward" in prompt
    assert seen["relevant_tools"] == set(m.tools)
    slot = seen["slot"]
    assert sorted(slot["allowed_tools"]) == sorted(m.tools)
    assert slot["suppress_skills"] is True
    assert slot["agent"]["hire_id"] == h.id
    hired_with = [c for c in seen["context_msgs"] if "what you were hired with" in c["content"]]
    assert hired_with and "When it arrives: 06:00" in hired_with[0]["content"]


def test_effects_the_file_is_silent_on_ask_and_a_never_takes_the_tool_away(world):
    factory, sched, seen = world
    db = factory()
    h, m = _hire(db, "notes-gardener")
    seen["answer"] = "Changed: nothing."
    _run(sched, db, _task(db, h.id))
    assert seen["slot"]["agent"]["ask_effects"] == ["destructive"]
    assert seen["slot"]["agent"]["never_effects"] == []
    h2, _ = _hire(db, "topic-watcher", inputs={"topics": ["solar"]},
                  grants={"network_egress": "never"})
    _run(sched, db, _task(db, h2.id))
    assert seen["slot"]["allowed_tools"] == ["web_search"], "web_fetch reaches out; the hire said never"
    assert seen["slot"]["agent"]["never_effects"] == ["network_egress"]


def test_the_run_keeps_a_report_and_its_carry_forward_is_the_next_runs_notebook(world):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "topic-watcher", inputs={"topics": ["solar", "wind"]})
    task = _task(db, h.id)
    sched._record_run_step = lambda run_id, **step: sched._state_for(run_id)["steps"].append(step)
    seen["answer"] = ("Solar: a new panel record.\n\n## Report\n- searched two topics\n\n"
                      "## Carry forward\n- https://example.org/panel")

    async def loop_with_steps(endpoint_url, model, task, session_id, **kw):
        sched._state_for(kw["run_id"])["steps"].extend([
            {"kind": "tool", "tool": "web_search", "status": "ok"},
            {"kind": "tool", "tool": "web_fetch", "status": "ok"},
            {"kind": "tool", "tool": "send_email", "status": "blocked", "output": "not one of its tools"},
        ])
        seen.update(kw)
        return seen.pop("answer")

    sched._run_agent_loop = loop_with_steps
    run_id, _ = _run(sched, db, task)
    db.expire_all()
    report = json.loads(db.query(AgentRunReport).get(run_id).report)
    assert report["summary"] == "- searched two topics"
    assert report["read"] == ["web_search", "web_fetch"] and report["wrote"] == []
    assert report["refused"] == [{"tool": "send_email", "reason": "not one of its tools"}]
    assert db.query(AgentHire).get(h.id).notebook == "- https://example.org/panel"
    seen["answer"] = "Nothing new.\n\n## Carry forward\nnothing"
    _run(sched, db, task)
    notebook = [c for c in seen["context_msgs"] if "your notebook" in c["content"]]
    assert notebook and "https://example.org/panel" in notebook[0]["content"]
    assert notebook[0]["metadata"]["tool_gate_untrusted"] is False
    db.expire_all()
    assert db.query(AgentHire).get(h.id).notebook == "- https://example.org/panel", \
        "“nothing” keeps the notebook rather than wiping it"


def test_a_hire_whose_file_moved_on_stops_and_says_why(world, monkeypatch):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "morning-brief")
    from dataclasses import replace
    import src.agents.catalogue as C
    real = C.get_agent
    monkeypatch.setattr(C, "get_agent", lambda owner, aid, **kw: replace(real(owner, aid), version="2.0.0"))
    task = _task(db, h.id)
    with pytest.raises(AgentRunRefused, match="was updated to 2.0.0"):
        _run(sched, db, task)
    db.expire_all()
    hire = db.query(AgentHire).get(h.id)
    assert hire.status == "attention" and "choose Update" in hire.attention
    assert _task(db, h.id).status == "paused" and "system_prompt" not in seen


def test_a_hire_stops_at_its_runs_per_day(world):
    factory, sched, seen = world
    db = factory()
    h, m = _hire(db, "model-steward")          # runs_per_day: 1
    task = _task(db, h.id)
    _run(sched, db, task)
    db.query(TaskRun).update({"status": "success"})
    db.commit()
    with pytest.raises(AgentRunRefused, match="already run 1 times in the last 24 hours"):
        _run(sched, db, task)


def test_a_task_that_is_no_agents_runs_as_it_always_did(world):
    factory, sched, seen = world
    db = factory()
    task = ScheduledTask(id="plain", owner="alice", name="Plain", prompt="say hi", task_type="llm")
    db.add(task)
    db.commit()
    _run(sched, db, task)
    assert "agent" not in seen["slot"] and "allowed_tools" not in seen["slot"]
    assert seen["system_prompt"].startswith("You are a helpful assistant executing a scheduled task.")


def test_the_loop_is_handed_the_hires_policy(world, monkeypatch):
    """The real `_run_agent_loop`, captured where it hands `stream_agent_loop` its policy."""
    factory, sched, _ = world
    from src.task_scheduler import TaskScheduler
    real_loop = TaskScheduler._run_agent_loop
    captured = {}

    async def stream(**kw):
        captured.update(kw)
        if False:
            yield ""

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", stream)
    sched._run_agent_loop = lambda *a, **kw: real_loop(sched, *a, **kw)
    db = factory()
    h, _ = _hire(db, "notes-gardener")
    from src.agents.runtime import AgentDidNotDeliver
    with pytest.raises(AgentDidNotDeliver):         # it said nothing, so it delivered nothing
        _run(sched, db, _task(db, h.id))
    policy = captured["tool_policy"]
    assert policy.allowed_tools == frozenset({"manage_notes", "manage_documents"})
    assert policy.ask_effects == frozenset({"destructive"}) and policy.never_effects == frozenset()
    assert policy.sealed is True, "notes and documents only: no way out (`D-2026-10-24-01`)"
    import os
    from src.tool_execution import projects_root
    assert captured["workspace"] == os.path.realpath(projects_root("alice")), "`B1434`: it works in the projects folder"
    assert policy.reason_for("send_email") == "“send_email” is not one of this agent's tools."


# ── the gate ────────────────────────────────────────────────────────────────

def _ctx(**kw):
    from src.tool_capabilities import ToolRunSecurityContext
    return ToolRunSecurityContext(**kw)


def test_an_ask_effect_waits_for_a_yes_before_the_ladder_and_before_auto():
    send = json.dumps({"to": "a@b.c", "subject": "hi", "body": "x"})
    d = _ctx(hire_ask_effects=frozenset({"external_side_effect"}), auto_approved=True
             ).decision_for("send_email", send)
    assert d.allowed is False
    assert d.reason == ("This agent's hire asks before external_side_effect: 'send_email' waits "
                        "for your yes.")
    assert _ctx(hire_ask_effects=frozenset({"external_side_effect"})).decision_for(
        "web_search", '{"query": "x"}').allowed is True


def test_a_never_effect_is_refused_and_no_card_can_lift_it():
    from src.tool_capabilities import TOOL_CLASSIFICATION_UNAVAILABLE
    d = _ctx(hire_never_effects=frozenset({"write_private"})).decision_for(
        "manage_notes", '{"action": "create", "title": "x"}')
    assert d.allowed is False and d.classification == TOOL_CLASSIFICATION_UNAVAILABLE
    assert d.reason.startswith("This agent's hire never allows write_private")


@pytest.mark.parametrize("tool,content", [
    ("send_email", '{"to": "a@b.c"}'), ("web_fetch", '{"url": "https://x"}'),
    ("bash", '{"command": "ls"}'), ("manage_notes", '{"action": "list"}'),
])
def test_with_no_hire_the_gate_answers_exactly_as_before(tool, content):
    for tainted in (False, True):
        before = _ctx(external_untrusted_context_seen=tainted)._ladder_decision_for(tool, content)
        after = _ctx(external_untrusted_context_seen=tainted).decision_for(tool, content)
        assert (after.allowed, after.reason) == (before.allowed, before.reason)


def test_a_hire_that_allows_never_lifts_the_untrusted_floor():
    d = _ctx(external_untrusted_context_seen=True, hire_ask_effects=frozenset()).decision_for(
        "send_email", '{"to": "a@b.c"}')
    assert d.allowed is False, "the floor after untrusted content is the ladder's, and a hire cannot lift it"


def test_the_carry_forward_reads_only_its_own_section():
    text = "x\n## Carry forward\n- a\n- b\n## Something else\n- c"
    assert carried_forward(text) == "- a\n- b"
    assert carried_forward("## carry forward\n\n- nothing") == ""
    assert carried_forward("no sections at all") == ""


def test_a_call_that_only_lists_is_reported_as_a_read():
    from src.agents.runtime import build_report
    r = build_report("ok", [
        {"kind": "tool", "tool": "manage_calendar", "status": "ok", "detail": '{"action": "list_events"}'},
        {"kind": "tool", "tool": "manage_notes", "status": "ok", "detail": '{"action": "add", "title": "x"}'},
        {"kind": "tool", "tool": "manage_tasks", "status": "ok", "detail": "list my tasks"},
    ])
    assert r["read"] == ["manage_calendar"]
    assert r["wrote"] == ["manage_notes", "manage_tasks"], "no arguments on the step: the tool's whole reach"


def test_a_refused_call_is_one_step_and_the_report_does_not_say_it_read_or_wrote():
    """`P24-00`, found by driving a member's Morning Brief: the loop sends a
    refused call as a `tool_blocked` and then its refusal as a `tool_output`,
    and the step log kept both — the second an `error` with no arguments, which
    the report counted by the tool's whole reach (*Wrote with: manage_calendar*
    for a call that listed events and was refused). Driven through the real
    scheduler's step log, in the order the events arrive."""
    from src.agents.runtime import build_report
    from src.task_scheduler import TaskScheduler

    sched = TaskScheduler(session_manager=None)
    run = str(uuid.uuid4())
    reason = "Tool 'manage_calendar' is restricted to admin users on this deployment."
    sched._record_run_step(run, kind="tool", tool="manage_calendar", round=1,
                           detail='{"action": "list_events"}', status="blocked", output=reason)
    sched._close_run_step(run, tool="manage_calendar", round_=1, status="error", output=reason)
    sched._record_run_step(run, kind="tool", tool="manage_notes", round=2,
                           detail='{"action": "list"}', status="running")
    sched._close_run_step(run, tool="manage_notes", round_=2, status="ok", output="No notes found.")
    # A result whose start was missed still records (`_close_run_step`'s rule).
    sched._close_run_step(run, tool="manage_tasks", round_=3, status="ok", output="2 tasks")
    steps = sched._runs()[run]["steps"]
    assert [(s["tool"], s["status"]) for s in steps] == [
        ("manage_calendar", "blocked"), ("manage_notes", "ok"), ("manage_tasks", "ok")]
    r = build_report("**Today** nothing.", steps)
    assert r["read"] == ["manage_notes"] and r["wrote"] == ["manage_tasks"]
    assert [x["tool"] for x in r["refused"]] == ["manage_calendar"]


def test_the_loop_carries_the_hires_effects_into_its_gate(monkeypatch):
    """The real `stream_agent_loop`, handed a hire's policy: a call with an
    `ask` effect waits for a yes — it is not run — and says why."""
    from src.tool_policy import ToolPolicy
    from tests.test_an_ai_step_uses_only_its_tools import _base, _drive
    _base(monkeypatch)
    executed = []
    policy = ToolPolicy(allowed_tools=["send_email"], allowed_owner="this agent's",
                        ask_effects=frozenset({"external_side_effect"}))
    events, _ = _drive(monkeypatch, [[("send_email", {"to": "a@example.com", "subject": "hi",
                                                       "body": "x"})], "Sent."],
                       policy=policy, executed=executed, message="Email them")
    assert executed == [], "the hire said ask, and the call ran"
    said = json.dumps(events)
    assert "This agent's hire asks before external_side_effect" in said


def test_an_ask_can_be_answered_in_a_clean_run_and_a_never_cannot():
    """`B1431`. The dispatcher replays an approval only into a run whose gate
    asks for that action (`asks_for`); a hire's `ask` asks in a clean run."""
    bash = '{"command": "printf hi"}'
    assert _ctx().asks_for("bash", bash) is False, "premise: a clean run at the default rung asks nothing"
    assert _ctx(hire_ask_effects=frozenset({"execute_code"})).asks_for("bash", bash) is True
    assert _ctx(hire_never_effects=frozenset({"execute_code"})).asks_for("bash", bash) is False
    assert _ctx(hire_ask_effects=frozenset({"execute_code"})).asks_for(
        "web_search", '{"query": "x"}') is False, "an effect the hire is silent on is not its question"


# ── `D-2026-10-24-01`: a sealed hire reads after outside content ───────────

def _tainted(**kw):
    return _ctx(external_untrusted_context_seen=True, **kw)


def test_a_sealed_hire_reads_and_writes_its_own_data_after_outside_content():
    """The owner's ruling: a kit with no way out of the install does not ask
    to read more of the person's own data — the brief that read the calendar
    then reads the mail."""
    for tool, content in [("list_emails", '{"unread_only": true}'), ("mcp__email__read_email", '{"id": "m1"}'),
                          ("manage_notes", '{"action": "list"}'), ("manage_tasks", '{"action": "list"}'),
                          ("create_document", "Inbox triage\nUrgent")]:
        assert _tainted()._ladder_decision_for(tool, content).allowed is False, f"premise: the floor asks for {tool}"
        assert _tainted(hire_sealed=True).decision_for(tool, content).allowed is True, tool


def test_a_sealed_run_lifts_nothing_that_reaches_outside():
    for tool, content in [("send_email", '{"to": "a@b.c"}'), ("web_fetch", '{"url": "https://x"}'),
                          ("bash", '{"command": "ls"}')]:
        assert _tainted(hire_sealed=True).decision_for(tool, content).allowed is False, tool


def test_what_a_later_run_would_trust_keeps_the_floor():
    for tool, content in [("manage_memory", '{"action": "add", "content": "x"}'),
                          ("manage_skills", '{"action": "create", "name": "x"}'),
                          ("manage_tasks", '{"action": "create", "name": "x", "prompt": "y"}')]:
        d = _tainted(hire_sealed=True).decision_for(tool, content)
        assert d.allowed is False, tool


def test_the_hires_own_table_still_asks_in_a_sealed_run():
    d = _tainted(hire_sealed=True, hire_ask_effects=frozenset({"write_private"})).decision_for(
        "create_document", "x\ny")
    assert d.allowed is False and d.reason.startswith("This agent's hire asks before write_private")


@pytest.mark.parametrize("tool,content", [
    ("list_emails", '{"unread_only": true}'), ("send_email", '{"to": "a@b.c"}'),
    ("manage_memory", '{"action": "add"}'), ("web_fetch", '{"url": "https://x"}')])
def test_sealed_changes_nothing_before_outside_content_or_for_an_unsealed_run(tool, content):
    clean_before = _ctx()._ladder_decision_for(tool, content)
    clean_after = _ctx(hire_sealed=True).decision_for(tool, content)
    assert (clean_after.allowed, clean_after.reason) == (clean_before.allowed, clean_before.reason)
    tainted_before = _tainted()._ladder_decision_for(tool, content)
    tainted_unsealed = _tainted().decision_for(tool, content)
    assert (tainted_unsealed.allowed, tainted_unsealed.reason) == (tainted_before.allowed, tainted_before.reason)


def test_a_kit_is_sealed_only_with_no_way_out():
    from src.agents.runtime import is_sealed
    assert is_sealed(get_agent("alice", "morning-brief").tools)
    assert is_sealed(get_agent("alice", "inbox-triage").tools)
    assert not is_sealed(get_agent("alice", "topic-watcher").tools), "web_search carries a query out"
    assert not is_sealed(get_agent("alice", "server-health").tools), "a shell can reach anything"
    assert not is_sealed(["send_email", "list_emails"])


def test_the_run_carries_sealed_into_its_gate(world):
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "morning-brief", inputs={"at": "06:00"})
    seen["answer"] = "Today: nothing."
    _run(sched, db, _task(db, h.id))
    assert seen["slot"]["agent"]["sealed"] is True
    h2, _ = _hire(db, "topic-watcher", inputs={"topics": ["x"]})
    _run(sched, db, _task(db, h2.id))
    assert seen["slot"]["agent"]["sealed"] is False


# ── `D-2026-10-24-02`: a blind hire reads the web after outside content ────

def test_a_blind_hire_fetches_after_outside_content_and_its_writes_still_ask():
    fetch = ("web_fetch", '{"url": "https://news.example/x"}')
    assert _tainted()._ladder_decision_for(*fetch).allowed is False, "premise: the floor asks"
    assert _tainted(hire_blind=True).decision_for(*fetch).allowed is True
    assert _tainted(hire_blind=True).decision_for("web_search", '{"query": "x"}').allowed is True
    assert _tainted(hire_blind=True).decision_for("create_document", "x\ny").allowed is False
    assert _tainted(hire_blind=True).decision_for("send_email", '{"to": "a@b.c"}').allowed is False
    assert _ctx(hire_blind=True).decision_for(*fetch).allowed == _ctx()._ladder_decision_for(*fetch).allowed


def test_a_kit_is_blind_only_when_it_can_read_nothing_private():
    from src.agents.runtime import is_blind
    assert is_blind(get_agent("alice", "topic-watcher").tools)
    assert is_blind(["web_search", "web_fetch", "create_document"]), "a tool that only creates reads nothing"
    assert not is_blind(["web_fetch", "manage_documents"]), "a tool that writes documents can read them"
    assert not is_blind(["web_fetch", "bash"])
    assert not is_blind(get_agent("alice", "morning-brief").tools)
