# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1624` — an evaluation world's answers reach the model in its own
characters.

Measured before the fix: `World.answer` serialised every structured answer
with `json.dumps(…, indent=1)`, which escapes everything outside ASCII, so a
mail subject's *—* reached the model as `\\u2014` and a sender's *ë* as
`\\u00eb` — text no real tool hands a model, in a harness whose whole purpose
is to measure a model on what a real run reads.

Driven through the real harness (`evals.run_agent`: the scheduler, the agent
loop, the gate, the world) with the scripted model recording every request it
is sent, for a mail tool the world answers and for a tool that leaves the
install, which the world answers from its research.
"""

from __future__ import annotations

import asyncio

from src.agents import evals as E
from src.agents.catalogue import get_agent

SUBJECT = "Q3 — numbers for Zoë"


def _asked(monkeypatch, agent: str, case: dict):
    """Every request the scripted model was sent during `case`."""
    sent = []
    make = E.scripted_model

    def recording(script):
        model = make(script)

        async def ask(candidates, messages, **kwargs):
            sent.append(messages)
            async for chunk in model(candidates, messages, **kwargs):
                yield chunk
        return ask

    monkeypatch.setattr(E, "scripted_model", recording)
    asyncio.run(E.run_agent(get_agent(None, agent), cases=[case]))
    return sent


def _tool_text(sent) -> str:
    return "\n".join(str(m.get("content") or "") for request in sent for m in request
                     if m.get("role") in ("tool", "user"))


def test_a_mail_tools_answer_keeps_its_dash_and_its_accent(monkeypatch):
    case = {
        "id": "own-characters", "about": "The world's mail, as the model reads it.",
        "inputs": {"vip": ["ana@example.com"]},
        "world": {"emails": [{"id": "m1", "from": "zoe@example.com", "subject": SUBJECT,
                              "body": "Café figures attached — see row 4.", "date": "2026-10-27"}]},
        "script": [{"call": [["list_emails", {"unread_only": True}]]}, {"say": "Done."}],
        "checks": [{"called": "list_emails"}],
    }
    text = _tool_text(_asked(monkeypatch, "inbox-triage", case))
    assert SUBJECT in text, text[-800:]
    assert "\\u2014" not in text and "\\u00eb" not in text


def test_an_outside_tools_answer_keeps_them_too(monkeypatch):
    """`trigger_research` leaves the install, so the world answers it in its
    own branch — the other `json.dumps` the row names."""
    case = {
        "id": "own-characters-outside", "about": "Research started, as the model reads it.",
        "inputs": {"question": "Is a roof in Leeds worth panels?"},
        "world": {"research": []},
        "script": [{"call": [["trigger_research", {"topic": "solar — Zoë's roof"}]]}, {"say": "Done."}],
        "checks": [{"called": "trigger_research"}],
    }
    text = _tool_text(_asked(monkeypatch, "deep-researcher", case))
    assert "solar — Zoë's roof" in text, text[-800:]
    assert "\\u2014" not in text
