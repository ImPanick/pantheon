# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1603` — a hired run that adds a note answers in the model's words only.

A sibling of `B1435`. When `manage_notes` makes a note the loop streams a
`[View note: <title>](#note-<id>)` link, so a chat can open the new note with
a click — and a task's run, which sums the stream's text into its answer, put
that link in front of the model's own words. Seen in Gift & Date Keeper's and
Habit Coach's sample reports (and Home Maintenance's): the report, and so the
notebook and the hall's sample, began with a link the model never wrote.

Driven twice: through the agents' harness (the real scheduler, loop and notes
tool), and through the loop alone, to show the chat still gets its link.
"""

from __future__ import annotations

import asyncio
import json

from src.agents import evals as E
from src.agents.catalogue import get_agent


def _final_words(case) -> str:
    return [r["say"] for r in case["script"] if "say" in r][-1]


def test_a_hired_run_that_adds_a_note_answers_in_its_own_words():
    m = get_agent(None, "gift-date-keeper")
    case = next(c for c in E.load_evals(m) if c["id"] == "a-birthday-in-the-window")
    (r,) = asyncio.run(E.run_agent(m, cases=[case]))
    assert "manage_notes" in r.report["wrote"], "the case no longer makes a note — it measures nothing"
    answer = r.report["answer"]
    assert "#note-" not in answer and "View note" not in answer, answer[:200]
    assert answer == _final_words(case).strip(), "the run's answer is not the model's words"


def test_a_chat_still_gets_the_link_to_the_note(monkeypatch):
    """`Law 1`: the link is still streamed — marked as the loop's — and a
    chat's saved reply keeps it."""
    import src.agent_loop as al
    from tests.test_an_ai_step_uses_only_its_tools import _base

    _base(monkeypatch)
    rounds = iter([[("manage_notes", {"action": "add", "title": "Gift for Ana", "content": "pottery"})],
                   "Saved a reminder for Ana's birthday."])

    async def scripted(candidates, messages, **kwargs):
        step = next(rounds, "")
        if isinstance(step, list):
            calls = [{"name": n, "arguments": json.dumps(a)} for n, a in step]
            yield "data: " + json.dumps({"type": "tool_calls", "calls": calls}) + "\n\n"
        elif step:
            yield "data: " + json.dumps({"delta": step}) + "\n\n"
        yield "data: [DONE]\n\n"

    async def run_tool(block, *a, **k):
        return block.tool_type, {"output": "Note added.", "note_id": "n1", "note_title": "Gift for Ana",
                                 "exit_code": 0}

    monkeypatch.setattr(al, "stream_llm_with_fallback", scripted)
    monkeypatch.setattr(al, "execute_tool_block", run_tool)

    async def collect():
        return [c async for c in al.stream_agent_loop(
            "http://local.test/v1", "scripted", [{"role": "user", "content": "Remind me about Ana"}],
            max_rounds=3, owner="local")]

    events = [json.loads(c[6:]) for c in asyncio.run(collect())
              if c.startswith("data: ") and not c.startswith("data: [DONE]")]
    links = [e for e in events if "delta" in e and e.get("link")]
    assert [e["link"] for e in links] == ["note"]
    assert "[View note: Gift for Ana](#note-n1)" in links[0]["delta"]
    words = "".join(e["delta"] for e in events if "delta" in e and not e.get("link") and not e.get("thinking"))
    assert words == "Saved a reminder for Ana's birthday."
