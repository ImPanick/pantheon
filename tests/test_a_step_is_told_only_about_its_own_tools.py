# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1169` — an AI step is sent no sentence naming a tool outside its list.

Measured through the real loop with a step limited to `web_search`: the
request's tool list and its rule blocks were the step's (`B1304` pruned the
rules), but the per-turn date message still said *"When scheduling calendar
events with manage_calendar …"* and *"When scheduling a task with manage_tasks
…"* — on every turn of every model, a step's or a plain chat's. The sentences
are now said only to a turn that has the tool. Driven, not read (`Law 20`): the
real `stream_agent_loop` with a scripted model, and every string the model was
sent searched for a register name outside the step's list.
"""
import re

import pytest

from src.tool_policy import ToolPolicy, known_tool_names
from src.user_time import current_datetime_prompt
from test_an_ai_step_uses_only_its_tools import _base, _drive  # noqa: E402


def _names_outside(text, allowed):
    """Register names outside `allowed` that `text` mentions: any name in
    backticks, and a name with an underscore as a whole word (a bare `git` or
    `computer` is English as often as it is a tool)."""
    found = set()
    for name in set(known_tool_names()) - set(allowed):
        if f"`{name}`" in text or ("_" in name and re.search(rf"\b{re.escape(name)}\b", text)):
            found.add(name)
    return sorted(found)


@pytest.mark.parametrize("native", [True, False], ids=["native", "fenced"])
def test_a_step_limited_to_web_search_is_told_about_no_other_tool(monkeypatch, native):
    _base(monkeypatch, native=native)
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           policy=ToolPolicy(allowed_tools={"web_search"}))

    assert sent, "the model was never asked"
    assert _names_outside(sent[0]["prompt"], {"web_search"}) == []
    # It is still told the date.
    assert "## Current date and time" in sent[0]["prompt"]


def test_a_step_that_has_the_calendar_is_still_told_how_to_schedule(monkeypatch):
    _base(monkeypatch)
    _events, sent = _drive(monkeypatch, ["Nothing to do."],
                           policy=ToolPolicy(allowed_tools={"manage_calendar"}))

    assert "When scheduling calendar events with manage_calendar" in sent[0]["prompt"]
    assert "manage_tasks" not in sent[0]["prompt"]


def test_each_sentence_follows_its_own_tool():
    both = current_datetime_prompt(available={"manage_calendar", "manage_tasks"})
    assert "manage_calendar" in both and "manage_tasks" in both
    tasks = current_datetime_prompt(available={"manage_tasks"})
    assert "manage_calendar" not in tasks and "manage_tasks" in tasks
    assert "manage_" not in current_datetime_prompt(available=())
    # A caller that does not know its tools keeps both, as before.
    assert current_datetime_prompt() == both


@pytest.mark.asyncio
async def test_a_plain_chat_is_told_how_to_call_no_tool(monkeypatch):
    """`routes/chat_helpers.build_chat_context`'s chat-mode turn sends no
    tools, so the date message it builds names none."""
    from test_kv_cache_invalidation_2927 import (  # noqa: E402
        _build_context_harness, _install_chat_helpers_stubs,
    )

    chat_helpers = _install_chat_helpers_stubs(monkeypatch)
    sess, request, chat_handler, chat_processor = _build_context_harness(
        monkeypatch, chat_helpers, history=[])
    context = await chat_helpers.build_chat_context(
        sess=sess, request=request, chat_handler=chat_handler,
        chat_processor=chat_processor, message="Book lunch tomorrow", session_id="s-1",
    )

    sent = "\n".join(m.get("content") or "" for m in context.messages
                     if isinstance(m.get("content"), str))
    assert "## Current date and time" in sent
    assert _names_outside(sent, set()) == []
