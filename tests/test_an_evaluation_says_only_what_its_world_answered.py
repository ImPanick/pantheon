# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1613` — an evaluation's answer says only what its world answered.

`B1602` gave the evaluation world its own memory and chats: `manage_memory`,
`list_sessions` and `search_chats` answer from what a case seeds (and answer
"nothing" when it seeds nothing). Six agents' cases were written before that,
and their scripted answers still said the tool was missing — Gift & Date
Keeper's first case, *"could not search memory: the memory manager is not
available"*; Weekly Review, Evening Wrap and Decision Log, *"could not read
chats"* in every case; Meal Planner and Out-of-Office Cover the same of
memory. Each sample report therefore told a person that memory or chats were
broken in a run where they had answered — and the case measured nothing of
what the agent does with them.

Driven through the real harness: every case of every agent at the bar whose
kit holds one of those tools runs, and its answer and the documents it wrote
may say memory or chats are "not available" only when one of those tools said
so in that run (a document the agent wrote echoes its own words back, so only
those tools' answers count). And Gift & Date Keeper's
first case seeds the memory its runbook searches, and uses what it found.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from src.agents import evals as E
from src.agents.catalogue import get_agent
import src.tool_execution as tool_execution
from tests.test_an_agent_has_substance import AT_THE_BAR

#: The tools whose answers `B1602` moved into the world.
WORLD_OWNED = {"manage_memory", "list_sessions", "search_chats"}
_MISSING = re.compile(r"not available", re.I)
_ABOUT = re.compile(r"memor|chat|session", re.I)


def _agents():
    out = []
    for aid in sorted(AT_THE_BAR):
        m = get_agent(None, aid)
        if set(m.tools) & WORLD_OWNED:
            out.append(aid)
    return out


def _spy(monkeypatch):
    seen = []
    real = tool_execution._execute_tool_block_impl

    async def spy(block, *a, **kw):
        out = await real(block, *a, **kw)
        seen.append((block.tool_type, json.dumps(out[1] if isinstance(out, tuple) else out, ensure_ascii=False)))
        return out

    monkeypatch.setattr(tool_execution, "_execute_tool_block_impl", spy)
    return seen


@pytest.mark.parametrize("agent", _agents())
def test_no_answer_says_a_source_is_missing_when_it_answered(agent, monkeypatch):
    seen = _spy(monkeypatch)
    m = get_agent(None, agent)
    wrong = {}
    for case in E.load_evals(m):
        seen.clear()
        (r,) = asyncio.run(E.run_agent(m, cases=[case]))
        written = [(r.report or {}).get("answer") or ""] + [d["content"] for d in r.documents]
        said = [ln.strip() for text in written for ln in text.split("\n")
                if _MISSING.search(ln) and _ABOUT.search(ln)]
        told = any(_MISSING.search(out) for t, out in seen if t in WORLD_OWNED)
        if said and not told:
            wrong[case["id"]] = said
    assert not wrong, (f"{agent}'s answers say a source is not available, but every tool in the run "
                       f"answered: {json.dumps(wrong, ensure_ascii=False, indent=1)}")


def test_gift_and_date_keeper_uses_the_memory_its_world_holds(monkeypatch):
    seen = _spy(monkeypatch)
    m = get_agent(None, "gift-date-keeper")
    case = E.load_evals(m)[0]
    memories = (case.get("world") or {}).get("memories") or []
    assert memories, "the first case seeds no memory, so manage_memory answers nothing it can use"
    (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    assert r.passed, [c for c in r.checks if not c["ok"]]
    from_memory = [out for t, out in seen if t == "manage_memory"]
    assert any("found" in out.lower() or "ana" in out.lower() for out in from_memory), from_memory
    # What the memory held reaches the answer: a fact no note has.
    fact = "wheel"
    assert any(fact in json.dumps(x, ensure_ascii=False).lower() for x in memories), memories
    assert fact in r.report["answer"].lower(), r.report["answer"]
