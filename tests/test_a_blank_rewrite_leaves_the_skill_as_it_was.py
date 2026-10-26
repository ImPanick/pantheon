# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B791` — a model that answers nothing usable leaves the skill as it was.

`Skill.from_markdown("   ")` does not raise: it returns a nameless skill with no
description, no when-to-use and no procedure, and `_apply_skill_md` persisted it
through `update_skill`, pinning only the name. The audit's call sites each guard
with `fixed and fixed.strip() != md.strip()`, which a whitespace answer passes
(truthy, unequal), so a local model that answered a 16k-token rewrite request
with a newline blanked the skill it was asked to improve. The guard is in
`_apply_skill_md` itself now, so every caller has it (`Law 14`).

Driven twice: `_apply_skill_md` directly, over every flavour of nothing, and the
real `_audit_one_skill` with the rewriter answering whitespace — the path the
row measured — asserting the stored SKILL.md is byte-identical afterwards.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import routes.skills_routes as skills_routes
from routes.skills_routes import _apply_skill_md
from services.memory.skills import SkillsManager

OWNER = "alice"
NAME = "rotate-logs"


@pytest.fixture()
def store(tmp_path):
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name=NAME, description="Rotate and prune application logs",
                 category="ops", tags=["logs"], when_to_use="the disk is full of logs",
                 procedure=["stop the writer", "rotate", "prune older than 7 days"],
                 pitfalls=["an open file frees nothing"], verification=["df shows space"],
                 owner=OWNER, source="user", status="published")
    return sm


def _bytes(sm) -> str:
    return sm.read_skill_md(NAME, owner=OWNER)


@pytest.mark.parametrize("nothing", [None, "", "   ", "\n", "\n\t \n"])
def test_applying_nothing_writes_nothing(store, nothing):
    before = _bytes(store)
    assert _apply_skill_md(store, NAME, nothing, OWNER) is False
    assert _bytes(store) == before


@pytest.mark.parametrize("nothing", ["   ", "\n"])
def test_the_audits_self_edit_answering_whitespace_leaves_the_skill_alone(store, monkeypatch, nothing):
    """The row's measurement: the self-edit path, the rewriter answering a
    truthy blank. The test then fails, so the skill is flagged — and its text
    is exactly what it was."""
    before = _bytes(store)
    verdicts = [{"verdict": "needs_work", "confidence": 0.4, "summary": "vague", "issues": ["x"]}]

    async def judge(url, model, messages, **kw):
        system = messages[0]["content"]
        if system.startswith("You assess whether a reusable AI 'skill'"):
            return json.dumps({"necessary": True, "redundant_with": [], "reason": "specific"})
        if system.startswith("You are a strict QA reviewer"):
            return json.dumps(verdicts[0])
        raise AssertionError(f"unexpected model call: {system[:60]!r}")

    async def blank_rewrite(*a, **k):
        return nothing

    async def loop(url, model, messages, **kw):
        yield "data: " + json.dumps({"delta": "tried it"}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("src.llm_core.llm_call_async", judge)
    monkeypatch.setattr("src.agent_loop.stream_agent_loop", loop)
    monkeypatch.setattr(skills_routes, "_improve_skill_md", blank_rewrite)
    monkeypatch.setattr(skills_routes, "_audit_auto_publish_policy", lambda owner: (True, 0.85))

    skill = next(s for s in store.load(owner=OWNER) if s["name"] == NAME)
    result = asyncio.run(skills_routes._audit_one_skill(
        store, skill, "http://model.test", "scripted", {}, None, OWNER, lambda m: None))
    assert result["result"] == "flagged"
    after = _bytes(store)
    # The audit's own decisions (status, confidence) are frontmatter it writes
    # on purpose; the body the rewriter was asked to improve is untouched.
    assert after.split("\n---", 1)[1].split("## When to Use", 1)[1] == \
        before.split("\n---", 1)[1].split("## When to Use", 1)[1]
    assert "stop the writer" in after and "Rotate and prune application logs" in after
