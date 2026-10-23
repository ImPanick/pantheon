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
    monkeypatch.setattr(ts, "owner_is_admin_or_single_user", lambda owner: owner == "alice")
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
    run_id, answer = _run(sched, db, _task(db, h.id))
    assert answer.startswith("Done.")
    prompt = seen["system_prompt"]
    assert prompt.startswith("You are Morning Brief, an agent alice hired in Pantheon")
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
    _run(sched, db, _task(db, h.id))
    policy = captured["tool_policy"]
    assert policy.allowed_tools == frozenset({"manage_notes", "manage_documents"})
    assert policy.ask_effects == frozenset({"destructive"}) and policy.never_effects == frozenset()
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
