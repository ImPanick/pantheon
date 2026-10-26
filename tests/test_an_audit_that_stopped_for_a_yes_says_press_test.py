# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B886` — an audit that stopped for a person's yes says so, and says a thing
they can do.

`_audit_one_skill` returned `result: "approval_required"` under a comment saying
it routed the action to the manual test UI, recorded `inconclusive`, and told
the person to *"review the sealed action"*. No browser file read the result, so
the card looked like any other inconclusive one; and the sealed action had
already been consumed with `decision="deny"` (`_retire_skill_approval`), so
there was nothing left to review.

Now the sidecar records the fact beside the verdict (`audit_needs_approval`,
which `load()` surfaces and every later audit rewrites), and the sentence names
the button that works: Test, which reaches the same action and asks on a card
that can be answered. The card half is
`tests/test_the_skills_window_says_what_the_server_says_js.py`.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import routes.skills_routes as skills_routes
from routes.skills_routes import AUDIT_NEEDS_APPROVAL_SENTENCE
from services.memory.skills import SkillsManager

OWNER = "alice"
NAME = "send-weekly-report"


async def _model(url, model, messages, **kw):
    system = messages[0]["content"]
    if system.startswith("You assess whether a reusable AI 'skill'"):
        return json.dumps({"necessary": True, "redundant_with": [], "reason": "specific"})
    raise AssertionError(f"unscripted model call: {system[:80]!r}")


async def _stops_for_a_yes(url, model, messages, **kw):
    yield "data: " + json.dumps({"type": "tool_output", "output": "waiting for a yes",
                                 "ask_user": {"kind": "tool_approval",
                                              "approval_id": "ap-b886"}}) + "\n\n"


@pytest.fixture()
def audited(tmp_path, monkeypatch):
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name=NAME, description="Email the weekly report to the team",
                 category="email", tags=["report"], when_to_use="every friday",
                 procedure=["draft the report", "send it to the team list"],
                 owner=OWNER, source="user", status="published", confidence=0.9)
    denied = []
    monkeypatch.setattr(skills_routes, "_retire_skill_approval",
                        lambda approval_id, owner, why: denied.append(approval_id))
    monkeypatch.setattr("src.llm_core.llm_call_async", _model)
    monkeypatch.setattr("src.agent_loop.stream_agent_loop", _stops_for_a_yes)
    monkeypatch.setattr(skills_routes, "_audit_auto_publish_policy", lambda owner: (True, 0.85))
    skill = next(s for s in sm.load(owner=OWNER) if s["name"] == NAME)
    result = asyncio.run(skills_routes._audit_one_skill(
        sm, skill, "http://model.test", "scripted", {}, None, OWNER, lambda m: None))
    return sm, result, denied


def _live(sm):
    return next(s for s in sm.load(owner=OWNER) if s["name"] == NAME)


def test_the_audit_records_that_it_stopped_for_a_yes(audited):
    sm, result, denied = audited
    assert result["result"] == "approval_required"
    assert denied == ["ap-b886"], "the premise: the audit denied its own copy"
    live = _live(sm)
    assert live["audit_verdict"] == "inconclusive"
    assert live["audit_needs_approval"] is True
    assert (live["status"], live["confidence"]) == ("published", 0.9)


def test_what_it_tells_the_person_to_do_is_a_thing_they_can_do(audited):
    _sm, result, _denied = audited
    assert result["verdict"]["issues"] == [AUDIT_NEEDS_APPROVAL_SENTENCE]
    assert "Press Test" in AUDIT_NEEDS_APPROVAL_SENTENCE
    assert "review the sealed action" not in AUDIT_NEEDS_APPROVAL_SENTENCE


def test_the_next_audit_result_clears_it(audited):
    sm, _result, _denied = audited
    sm.set_audit(NAME, "pass", worker_model="scripted", owner=OWNER)
    assert _live(sm)["audit_needs_approval"] is False
