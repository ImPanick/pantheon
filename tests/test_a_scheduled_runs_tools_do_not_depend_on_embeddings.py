# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1372` — a scheduled Prompt task gets the same tools whether or not the
embedding lane answered.

**Measured before this file:** `_execute_llm_task` built a scheduled run's tool
set from `get_tool_index().get_tools_for_query(task.prompt, k=8)` unioned with
`ASSISTANT_ALWAYS_AVAILABLE` and the shell/file defaults. With the embedding
lane up the run got that top-8 retrieval; with it down (`get_tool_index()`
answers `None`) it passed nothing and the agent loop planned the suite itself,
without the assistant's tools pinned — two different tool sets for one task,
which is the intermittency `B1368` removed from the chat turn. Now the run's
tools are planned by the agent loop as a chat turn's are
(`plan_turn_tool_suite`), with the assistant's always-available tools and the
shell defaults pinned, and recorded on the run's receipt the same way.

Driven (`Law 20`): the real scheduler (`_execute_task` down), the real agent
loop and its real suite planner, on a real SQLite file; the model is scripted
at `stream_llm_with_fallback` and records the request it was handed.
"""
from __future__ import annotations

import json

import pytest

from tests.helpers.walker_harness import make_db

pytestmark = pytest.mark.asyncio

ENDPOINT = dict(model="scripted", endpoint_url="http://127.0.0.1:9/v1")


class _UpIndex:
    """The embedding lane answering: a top-8 that names tools the prompt
    never asked for, as a vector neighbourhood does."""

    def get_tools_for_query(self, query, k=8, always_include=None):
        return {"web_fetch", "generate_image", "manage_skills", "trigger_research"}

    def retrieve(self, query, k=8):
        return list(self.get_tools_for_query(query, k))


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.session_manager as sm_mod
    import src.agent_loop as agent_loop
    import src.events as events
    import src.task_endpoint as task_endpoint
    from core.database import ScheduledTask
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "suite.db")
    monkeypatch.setattr(sm_mod, "SessionLocal", factory)
    seen = {"requests": [], "plans": [], "receipts": []}

    async def model(candidates, messages, **kwargs):
        seen["requests"].append({
            "tools": sorted((t.get("function") or {}).get("name") for t in (kwargs.get("tools") or [])),
            "system": next((m.get("content") for m in messages if m.get("role") == "system"), ""),
        })
        yield f"data: {json.dumps({'delta': 'Checked.'})}\n\n"
        yield "data: [DONE]\n\n"

    real_plan = agent_loop.plan_turn_tool_suite

    def plan(*a, **k):
        out = real_plan(*a, **k)
        seen["plans"].append(out)
        return out

    real_record = events.record_run_config

    def record(**k):
        if k.get("suite") is not None:
            seen["receipts"].append(json.loads(json.dumps(k["suite"])))
        return real_record(**k)

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", model)
    monkeypatch.setattr(agent_loop, "plan_turn_tool_suite", plan)
    monkeypatch.setattr(events, "record_run_config", record)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(task_endpoint, "resolve_task_candidates", lambda **kw: [])
    db = factory()
    db.add(ScheduledTask(id="am", owner="alice", name="Morning check", task_type="llm",
                         prompt="Look over my inbox and my calendar for today.",
                         trigger_type="webhook", status="active", **ENDPOINT))
    db.commit()
    db.close()
    s = TaskScheduler(sm_mod.SessionManager())
    s._log_to_assistant = lambda *a, **k: None
    return s, seen


async def _fire(s, monkeypatch, lane):
    import src.tool_index as tool_index
    monkeypatch.setattr(tool_index, "get_tool_index",
                        (lambda: _UpIndex()) if lane == "up" else (lambda: None))
    await s._execute_task("am")


async def test_the_same_task_gets_the_same_tools_with_the_embedding_lane_up_or_down(world, monkeypatch):
    from src.tool_index import ASSISTANT_ALWAYS_AVAILABLE

    s, seen = world
    await _fire(s, monkeypatch, "up")
    await _fire(s, monkeypatch, "down")

    assert len(seen["requests"]) == 2, seen["requests"]
    assert len(seen["plans"]) == 2, "a run's tools were not planned by the suite planner"
    up, down = seen["plans"]
    assert set(up.offered) == set(down.offered), sorted(set(up.offered) ^ set(down.offered))
    assert seen["requests"][0] == seen["requests"][1], "the model was handed two different offers"
    # The vector neighbourhood decided nothing: what it alone named is offered
    # only if the plan offers it without it.
    assert up.reason == down.reason
    # The assistant's tools are pinned: whatever the plan held back, not them.
    assert (set(ASSISTANT_ALWAYS_AVAILABLE) & set(up.candidates)) <= set(up.offered)
    # …and the plan is on the run's receipt, as a chat turn's is.
    assert len(seen["receipts"]) == 2 and seen["receipts"][0] == seen["receipts"][1]
