# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2119`–`B2122`: the agents follow the same lean path as a chat turn.

The owner, 2026-11-15: *"look at the agents as well.. we have to ensure the
agents are also going to be following the most efficient token use pathway
too."* Traced on `fix/agent-lean-turn` (hired, summoned, workflow, scheduled,
teacher, background follow-up, skill tests, side calls). A hired or summoned
agent's kit is already what its author picked (1 to 6 tools across the
shipped library), so the kit is left as it is; these are the gaps that were
not:

  * `B2119`: the step-budget note on the last two steps of every run was a
    `system` message, which `llm_core` folds into the first one, so the
    system prompt changed and a local server re-read its whole prefix.
  * `B2120`: a summoned agent and a skill test carried the person's skills
    catalogue beside skills that are already in the request whole.
  * `B2121`: the teacher's takeover read Pantheon's own turn note as the
    person's request, and dropped the turn's skills switch, plan mode and caps.
  * `B2122`: one-word and few-token side calls left thinking on.
"""
from __future__ import annotations

import asyncio
import inspect

from src import teacher_escalation
from src.prompt_security import turn_note_message


def test_the_step_budget_note_is_a_turn_note_not_a_system_message():
    from src.agent_loop import _step_budget_note
    for n, limit in ((19, 20), (20, 20)):
        note = _step_budget_note(n, limit)
        assert note["role"] == "user", note
        assert note["content"].startswith(turn_note_message("x")["content"].split("x")[0][:20])


def test_the_summoned_agent_and_skill_tests_ship_no_catalogue():
    import routes.chat_routes as chat_routes
    import routes.skills_routes as skills_routes
    assert "suppress_skills=(not ctx.skills_enabled) or bool(_summoned)" in inspect.getsource(chat_routes)
    assert inspect.getsource(skills_routes).count("suppress_skills=True") >= 2


def _teacher_run(monkeypatch, messages, **kwargs):
    seen = {}

    async def fake_loop(**kw):
        seen.update(kw)
        if False:
            yield ""

    import src.agent_loop as agent_loop
    import src.settings as settings
    import src.ai_interaction as ai_interaction
    monkeypatch.setattr(agent_loop, "stream_agent_loop", fake_loop)
    values = {"teacher_enabled": True, "teacher_model": "teacher"}
    monkeypatch.setattr(settings, "get_setting", lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(ai_interaction, "_resolve_model",
                        lambda spec, owner=None: ("http://127.0.0.1:9/v1", "teacher", {}))
    monkeypatch.setattr(teacher_escalation, "note_turn_outcome", lambda **k: None, raising=False)

    async def no_skill(*a, **k):
        return None
    monkeypatch.setattr(teacher_escalation, "_call_teacher", no_skill)

    async def drain():
        async for _ in teacher_escalation.run_teacher_inline(
            student_endpoint_url="http://127.0.0.1:9/v1",
            student_messages=messages,
            student_tool_events=[{"error": "boom"}],
            student_reply="",
            **kwargs,
        ):
            pass
    asyncio.run(drain())
    return seen


def test_the_teacher_reads_the_persons_words_not_the_loops_note(monkeypatch):
    messages = [
        {"role": "user", "content": "rename the report to Q3 final"},
        {"role": "assistant", "content": "Want me to do it?"},
        turn_note_message("Do the work instead of offering it."),
    ]
    seen = _teacher_run(monkeypatch, messages)
    last = seen["messages"][-1]["content"]
    assert last.startswith("rename the report to Q3 final"), last


def test_the_teacher_keeps_the_turns_switches_and_caps(monkeypatch):
    seen = _teacher_run(
        monkeypatch, [{"role": "user", "content": "fix it"}],
        suppress_skills=True, max_rounds=6, max_tool_calls=9,
        plan_mode=True, approved_plan="the plan")
    assert seen["suppress_skills"] is True
    assert seen["max_rounds"] == 6 and seen["max_tool_calls"] == 9
    assert seen["plan_mode"] is True and seen["approved_plan"] == "the plan"


def test_one_word_and_few_token_side_calls_turn_thinking_off():
    import src.agent_loop as agent_loop
    import src.research_handler as research_handler
    verifier = inspect.getsource(agent_loop).split("VERIFICATION: SUCCESS", 1)[1][:2500]
    assert "thinking=False" in verifier
    assert "thinking=False" in inspect.getsource(teacher_escalation.evaluate_turn_llm)
    src = inspect.getsource(research_handler)
    assert src.count("thinking=False") >= 2
