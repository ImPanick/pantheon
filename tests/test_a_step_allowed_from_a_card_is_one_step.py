# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1648` — a step parked on a card and then allowed is one step, reported by
what it did.

**Measured before this change, through the agents' own harness**, for a hirer
who does not hold `can_auto_approve` (so every allowed step after the agent
reads outside content still waits for a yes, `D-2026-10-29-01` §1): Bookmark
Librarian's *two new links* case logged each card as a step of its own —
`manage_notes ok` with no arguments and "Waiting for an exact user approval."
as its output — beside the real `view` the replay ran, so its report said
*Wrote with: manage_notes*; Outbound Writer's one allowed draft was counted
twice ("It made 2 drafts."). `TaskScheduler._close_run_step` recorded the
card's `tool_output`, which has no `tool_start`, as a finished call, and the
report bucketed it by the tool's whole reach. `P24-00` had fixed the refused
twin (`test_a_hired_agent_runs_as_its_file_says.py`).

Driven through the real scheduler, loop, gate, parking, answer route and
report (`src.agents.evals`, `Law 20`), with the step log read back from the
run's own row; and the run that cannot wait for a yes through the real
`_run_agent_loop` with one real card.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from src.agents import evals as E
from src.agents.catalogue import get_agent

CARD_OUTPUT = "Waiting for an exact user approval."


def _case(agent, case_id, **kw):
    case = next(c for c in E.load_evals(get_agent(None, agent)) if c["id"] == case_id)
    case = dict(case)
    case.update(kw)
    return case


def _run(agent, case):
    """One case in its own world: the result, and the run's step log as its
    row holds it."""
    from core.database import TaskRun

    async def go():
        with E.isolated() as (factory, data):
            r = await E.run_case(get_agent(None, agent), case, factory=factory, data_dir=data)
            db = factory()
            try:
                run = db.query(TaskRun).order_by(TaskRun.started_at.desc()).first()
                steps = json.loads(run.steps or "[]") if run else []
            finally:
                db.close()
        return r, steps
    return asyncio.run(go())


def _tools(steps):
    return [s for s in steps if s.get("kind") == "tool"]


def test_a_read_allowed_from_a_card_is_one_step_reported_as_a_read():
    """The row's `Verify:`, first half. Without the lift the note's `view`,
    both fetches and the write each wait for a yes; each is allowed."""
    r, steps = _run("bookmark-librarian", _case(
        "bookmark-librarian", "two-new-links-one-filed-one-dead",
        can_auto_approve=False, answers=["approve_task"] * 4))
    assert r.status == "success" and r.passed, [c for c in r.checks if not c["ok"]]
    parked = [s for s in steps if s.get("kind") == "progress"
              and str(s.get("detail") or "").startswith("Waiting for your yes on ")]
    assert len(parked) == 4, "premise: the hirer without the lift is asked four times"
    tools = _tools(steps)
    # One step per call the script makes: search, view, two fetches, the write.
    assert [(s["tool"], s["status"]) for s in tools] == [
        ("manage_notes", "ok"), ("manage_notes", "ok"), ("web_fetch", "ok"),
        ("web_fetch", "ok"), ("create_document", "ok")], tools
    assert not [s for s in tools if s.get("output") == CARD_OUTPUT], "a card is not a call"
    assert all(s.get("detail") for s in tools), "every step carries the arguments it ran with"
    assert '"view"' in tools[1]["detail"]
    assert r.report["read"] == ["manage_notes", "web_fetch"], r.report
    assert r.report["wrote"] == ["create_document"], "a note it viewed is not a note it wrote"


def test_an_allowed_draft_counts_once():
    """The row's `Verify:`, second half: the contract's draft count."""
    r, steps = _run("outbound-writer", _case(
        "outbound-writer", "one-draft-with-a-real-reason",
        can_auto_approve=False, answers=["approve_task"]))
    assert r.status == "success" and r.passed, [c for c in r.checks if not c["ok"]]
    assert any(str(s.get("detail") or "").startswith("Resumed: Allowed once by ") for s in steps), \
        "premise: the draft waited for a yes and was allowed"
    drafts = [s for s in _tools(steps) if s["tool"].endswith("draft_email")]
    assert len(drafts) == 1 and "ana@greenleaf.example" in drafts[0]["detail"], drafts
    [count] = [c for c in r.checks if c["check"] == "at most 25 drafts"]
    assert count == {"check": "at most 25 drafts", "ok": True, "detail": "It made 1 draft."}
    assert r.report["wrote"] == ["draft_email"]


def test_a_denied_call_is_no_step_the_run_did():
    """A person's no: the call never ran, so the log has no `ok` step for it
    — it had one, with the card's sentence as its output."""
    r, steps = _run("chart-maker", _case("chart-maker", "it-never-installs-a-package"))
    assert r.status == "error" and r.passed, r.checks
    assert any(s.get("detail") == "Waiting for your yes on python" for s in steps), "premise: it asked"
    pythons = [s for s in _tools(steps) if s["tool"] == "python"]
    assert len(pythons) == 1 and "csv" in pythons[0]["detail"], "only the call that ran"
    assert "pip" not in json.dumps(pythons)


@pytest.mark.asyncio
async def test_a_run_that_cannot_wait_records_the_call_as_not_run(monkeypatch):
    """A run that may not park (`may_wait` off — a run another run awaits)
    retires the card as a denial: its step is the call, with its arguments,
    not run, and why. It was an `ok` step with no arguments."""
    from src.agents.runtime import build_report
    from src.task_scheduler import TaskScheduler
    from src.tool_approvals import tool_approval_store
    from src.tool_capabilities import capabilities_for_action
    from types import SimpleNamespace

    command = '{"action": "view", "id": "cccc0001"}'
    pending = tool_approval_store.create(
        owner="admin", session_id="s", origin_run_id="scheduled-run", tool_name="manage_notes",
        content=command, workspace=None, external_untrusted_context_seen=True,
        capabilities=capabilities_for_action("manage_notes", command))
    card = pending.public_payload()

    async def one_card(*args, **kwargs):
        yield "data: " + json.dumps({
            "type": "tool_output", "tool": "manage_notes", "round": 2, "command": command,
            "output": CARD_OUTPUT, "exit_code": None, "status": "ok", "ask_user": card}) + "\n\n"

    monkeypatch.setattr("src.agent_loop.stream_agent_loop", one_card)
    monkeypatch.setattr("src.task_endpoint.resolve_task_candidates", lambda **kw: [])
    sched = TaskScheduler(session_manager=None)
    run_id = str(uuid.uuid4())
    task = SimpleNamespace(crew_member_id=None, endpoint_url="http://ep/v1", model="m",
                           session_id="s", owner="admin", prompt="tidy my bookmarks",
                           name="job", max_steps=5, character_id=None)
    said = await sched._run_agent_loop("http://ep/v1", "model", task, "s", run_id=run_id)
    assert "paused safely" in said and tool_approval_store.peek(pending.approval_id) is None
    [step] = sched.run_steps(run_id)
    assert (step["kind"], step["tool"], step["round"], step["status"], step["detail"]) == (
        "tool", "manage_notes", 2, "blocked", command)
    assert step["output"] and step["output"] != CARD_OUTPUT
    assert step["output"] == (card.get("description") or "").strip()
    report = build_report("", [step])
    assert report["read"] == [] and report["wrote"] == []
    assert [x["tool"] for x in report["refused"]] == ["manage_notes"]
