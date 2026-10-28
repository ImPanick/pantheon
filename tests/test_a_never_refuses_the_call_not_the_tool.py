# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1619` — a hire's *never* refuses the calls that carry the effect, and
keeps the tool.

Measured before the fix: `runtime.plan_for_task` and `summon.summon` dropped a
tool from the kit when its widest reach held a `never` — `capabilities_for_tool`,
the tool as a whole — so Memory Auditor hired with `write_private: never` ran
with **no tools at all**: `manage_memory` writes, so its list and search went
with its add, edit and delete, and an agent whose whole job is reading memory
could not read any.

Now a tool goes only when every call of it carries a `never`
(`tool_capabilities.least_reach`); one some of whose calls do stays in the kit,
and the gate refuses just those calls, one at a time, in the hire's words.

Driven through the real scheduler (`TaskScheduler._execute_llm_task`), the
real hire store and the real shipped manifest — the slot the agent loop is
handed is what is asserted, as `test_a_hired_agent_runs_as_its_file_says.py`
does — and the real gate for the calls.
"""

from __future__ import annotations

import json

from tests.test_a_workflow_is_kept_as_one_document import wf_db  # noqa: F401  (fixture)
from tests.test_a_hired_agent_runs_as_its_file_says import _hire, _run, _task, world  # noqa: F401
from src.agents import hires as H
from src.agents.catalogue import get_agent
from src.tool_capabilities import (
    TOOL_CLASSIFICATION_UNAVAILABLE,
    ToolEffect,
    ToolRunSecurityContext,
    least_reach,
)

AUDIT = ("**Conflicts**\n- nothing\n\n**Out of date**\n- nothing\n\n**Duplicates**\n- nothing\n\n"
         "**Unsure**\n- nothing\n\n## Report\n- read 0 memories\n\n## Carry forward\n- nothing")


def test_a_hire_that_never_writes_keeps_its_memory_tool(world):
    factory, sched, seen = world
    db = factory()
    h, m = _hire(db, "memory-auditor", grants={"write_private": "never"})
    assert m.tools == ("manage_memory",)
    seen["answer"] = AUDIT
    _run(sched, db, _task(db, h.id))
    agent = seen["slot"]["agent"]
    assert "write_private" in agent["never_effects"]
    assert seen["slot"]["allowed_tools"] == ["manage_memory"], (
        "it reads memories; a never on writing takes the writes, not the tool")


def test_the_gate_refuses_only_the_writing_actions():
    never = frozenset(e for e, r in H.effective_effects(
        get_agent(None, "memory-auditor"), {"write_private": "never"}).items() if r == "never")
    run = ToolRunSecurityContext(hire_never_effects=never)
    for read in ({"action": "list"}, {"action": "search", "query": "pottery"}):
        assert run.decision_for("manage_memory", json.dumps(read)).allowed is True, read
    for write in ({"action": "add", "text": "x"}, {"action": "edit", "id": "1", "text": "y"},
                  {"action": "delete", "id": "1"}):
        refused = run.decision_for("manage_memory", json.dumps(write))
        assert refused.allowed is False, write
        assert refused.classification == TOOL_CLASSIFICATION_UNAVAILABLE
        assert refused.reason.startswith("This agent's hire never allows")
        assert "write_private" in refused.reason


def test_a_summoned_agent_keeps_the_same_kit(world):
    """A summoned agent uses the person's own hire's table and the same rule
    for its kit — the two cannot differ (`Law 7`)."""
    from src.agents.summon import summon
    factory, _sched, _seen = world
    db = factory()
    _hire(db, "memory-auditor", grants={"write_private": "never"})
    s = summon("alice", "memory-auditor", db=db)
    assert s.tools == ["manage_memory"]
    assert "write_private" in s.never_effects


def test_a_tool_every_call_of_which_is_never_still_goes(world):
    """`web_fetch` reaches the network on every call: `network_egress: never`
    still takes it away, as before."""
    factory, sched, seen = world
    db = factory()
    h, _ = _hire(db, "topic-watcher", inputs={"topics": ["solar"]}, grants={"network_egress": "never"})
    seen["answer"] = "New since last run: nothing. Checked: x."
    _run(sched, db, _task(db, h.id))
    assert seen["slot"]["allowed_tools"] == ["web_search"]


def test_least_reach_is_what_every_call_shares():
    assert least_reach("manage_memory") == frozenset()          # a read and a write share nothing
    assert least_reach("web_fetch") == {ToolEffect.BROKERED_NETWORK_READ, ToolEffect.NETWORK_EGRESS}
    assert least_reach("bash") == {ToolEffect.EXECUTE_CODE}      # its deletions are some calls'
    assert least_reach("delete_email") == {ToolEffect.EXTERNAL_SIDE_EFFECT, ToolEffect.DESTRUCTIVE}
    assert ToolEffect.READ_WORKSPACE not in least_reach("git")   # a push reads nothing
