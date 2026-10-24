# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1429` — a model that lists something and then answers keeps its answer.

Found by driving `P24`'s *Morning Brief* against a scripted model: the agent
called `manage_calendar` `list_events`, wrote its brief, and the run's answer
came back as the brief **with the calendar tool's own line glued to its end**
(`…on weekdaysNo events between 2026-10-22 and 2026-11-05.`), which then became
the agent's notebook. The cause is the end of `stream_agent_loop`: after any
turn whose last listing was a calendar, notes, tasks or mail list, it replaced
the reply with a deterministic summary of that listing and streamed the summary
as one more delta — so a task's run (which sums deltas) got both, and a chat's
saved reply was the summary alone, the model's answer gone after a reload.
Those summaries were written for Pantheon's own small finetune; they ran for
every model. Measured on `a28041c` (upstream code, unchanged since the import).

Driven through the real loop with a scripted model and the dispatcher stood in
for at `execute_tool_block` (`tests/test_an_ai_step_uses_only_its_tools.py`'s
harness, imported).
"""
import asyncio
import json

import src.agent_loop as al
from tests.test_an_ai_step_uses_only_its_tools import _base

CALENDAR = "No events between 2026-10-22 and 2026-11-05."


def _drive(monkeypatch, rounds, *, tool_output=CALENDAR, model="scripted"):
    script = iter(rounds)

    async def scripted(candidates, messages, **kwargs):
        step = next(script, "")
        if isinstance(step, list):
            calls = [{"name": n, "arguments": json.dumps(a)} for n, a in step]
            yield "data: " + json.dumps({"type": "tool_calls", "calls": calls}) + "\n\n"
        elif step:
            yield "data: " + json.dumps({"delta": step}) + "\n\n"
        yield "data: [DONE]\n\n"

    async def run_tool(block, *a, **k):
        return block.tool_type, {"output": tool_output, "exit_code": 0}

    monkeypatch.setattr(al, "stream_llm_with_fallback", scripted)
    monkeypatch.setattr(al, "execute_tool_block", run_tool)

    async def collect():
        return [c async for c in al.stream_agent_loop(
            "http://local.test/v1", model, [{"role": "user", "content": "What is on today?"}],
            max_rounds=len(rounds) + 1, owner="local")]

    events = [json.loads(c[6:]) for c in asyncio.run(collect())
              if c.startswith("data: ") and not c.startswith("data: [DONE]")]
    text = "".join(e["delta"] for e in events if "delta" in e and not e.get("thinking"))
    return text, events


def test_the_models_answer_after_a_calendar_listing_is_the_answer(monkeypatch):
    _base(monkeypatch)
    answer = "Nothing on the calendar today — a clear run at the release notes."
    text, _ = _drive(monkeypatch, [[("manage_calendar", {"action": "list_events"})], answer])
    assert text == answer, "the listing's summary was glued to (or replaced) the model's answer"


def test_with_no_answer_of_its_own_the_listing_still_speaks(monkeypatch):
    """`Law 1`: what the summaries were for — a turn that listed and then said
    nothing — is unchanged."""
    _base(monkeypatch)
    text, _ = _drive(monkeypatch, [[("manage_calendar", {"action": "list_events"})], ""])
    assert CALENDAR in text


NOTES = "Found 1 notes:\n- [n1] **Renew passport** (due today)"
TASKS = "Found 1 tasks:\n1. Morning Brief (ed93) — active, cron, next 2026-10-24T07:00:00Z"


def test_a_notes_or_tasks_listing_is_not_put_into_the_answer(monkeypatch):
    """`B1435`, found by the agents' evaluation harness: the loop also wrote a
    notes listing ("Here are your notes (1): …") and a tasks listing ("Found 1
    tasks: 1. Morning Brief (<id>) …") into the answer as text, mid-turn, for
    every model — so a hired Morning Brief's report began with them."""
    _base(monkeypatch)
    answer = "**Today**\n- nothing\n\n**Due**\n- Renew passport"
    for tool, out in (("manage_notes", NOTES), ("manage_tasks", TASKS)):
        text, _ = _drive(monkeypatch, [[(tool, {"action": "list"})], answer], tool_output=out)
        assert text == answer, tool


def test_a_notes_listing_with_no_answer_still_speaks(monkeypatch):
    _base(monkeypatch)
    text, _ = _drive(monkeypatch, [[("manage_notes", {"action": "list"})], ""], tool_output=NOTES)
    assert "Renew passport" in text
