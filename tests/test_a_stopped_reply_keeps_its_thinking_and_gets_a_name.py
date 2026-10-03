# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-04` — CHAT-M-16 and CHAT-M-21, the server half: what a reply keeps of
its reasoning, and a stopped chat still gets a name.

**What was wrong** (measured on `9560d50`, `routes/chat_routes.py`):

  * **CHAT-M-16.** The Stop button cancels the detached run, and the
    disconnect branch saved the reply's text only — the reasoning the person
    watched was gone after a reload — and naming ran only on `[DONE]`, so a
    chat stopped on its first turn was called "scripted-demo 3:29:34 AM" for
    ever, in the header, the sidebar and the Library.
  * **CHAT-M-21.** An agent turn's reasoning was saved as the rounds glued
    together with no separator ("…Reading the rows.Reminders: 41 agree…"),
    and nothing kept which round said what.

**What is pinned.** Through the real `/api/chat_stream` route (the double
`test_foreground_model_routing.py` builds) and the real
`save_assistant_response`: a finished agent turn keeps `round_thinking` and a
joined `thinking`; a stopped one — Chat mode or Agent — keeps its reasoning and
starts the naming a finished one starts. The client half (drawing it) is
`test_a_denied_call_says_denied.py::test_the_reasoning_is_drawn_after_a_reload`.
"""

import asyncio
import json

import pytest

import routes.chat_routes as chat_routes
from routes.chat_helpers import needs_auto_name
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402


def _frame(obj) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def test_the_reasoning_record_keeps_each_round_and_joins_them():
    rec = chat_routes._thinking_record("ab", ["First look. ", "", " Second look."])
    assert rec == {"thinking": "First look.\n\nSecond look.",
                   "round_thinking": ["First look.", "", "Second look."]}
    assert chat_routes._thinking_record("  only one  ") == {"thinking": "only one"}
    assert chat_routes._thinking_record("", []) == {}


def test_a_new_chat_is_one_that_still_needs_a_name():
    assert needs_auto_name("New chat")
    assert needs_auto_name("scripted-demo 3:29:34 AM")   # a chat made before this row
    assert not needs_auto_name("Plan the launch week")


def _run(monkeypatch, mode, chunks, *, compare="true", name="New chat"):
    """One request through the route; returns what it saved and what it named."""
    import core.database as database
    from routes.chat_helpers import save_assistant_response

    captured = {"named": []}
    kwargs = {"agent_chunks": chunks} if mode == "agent" else {"chat_chunks": chunks}
    endpoint = _chat_stream_endpoint(monkeypatch, mode, captured, **kwargs)
    monkeypatch.setattr(chat_routes, "save_assistant_response", save_assistant_response)
    monkeypatch.setattr(database, "update_session_last_accessed", lambda sid: None, raising=False)

    async def fake_name(_manager, sess):
        captured["named"].append(sess.name)

    monkeypatch.setattr(chat_routes, "auto_name_session", fake_name)
    # The double's session is called "test", which is a name; a fresh chat has
    # the default one. It is reached through the manager the route closed over.
    for cell in (endpoint.__closure__ or ()):
        manager = cell.cell_contents
        if hasattr(manager, "get_session") and hasattr(manager, "save_sessions"):
            manager.get_session("session-1").name = name
    request = _RouteRequest(mode)
    request._form["compare_mode"] = compare

    async def go():
        response = await endpoint(request)
        try:
            async for _ in response.body_iterator:
                pass
        except (asyncio.CancelledError, GeneratorExit):
            pass
        for _ in range(5):
            await asyncio.sleep(0)   # let a detached run and a naming task finish

    asyncio.run(go())
    return captured


def test_a_finished_agent_turn_keeps_its_reasoning_per_round(monkeypatch):
    chunks = [
        _frame({"delta": "First look.", "thinking": True}),
        _frame({"type": "agent_step", "round": 2}),
        _frame({"delta": "Second look.", "thinking": True}),
        _frame({"delta": "The answer."}),
        _frame({"type": "metrics", "data": {"round_texts": ["", "The answer."]}}),
        "data: [DONE]\n\n",
    ]
    captured = _run(monkeypatch, "agent", chunks)
    [saved] = [m.metadata for m in captured.get("added_messages", [])]
    assert saved["round_thinking"] == ["First look.", "Second look."]
    assert saved["thinking"] == "First look.\n\nSecond look."


@pytest.mark.parametrize("mode", ["chat", "agent"])
def test_a_stopped_reply_keeps_its_reasoning_and_the_chat_gets_a_name(monkeypatch, mode):
    chunks = [
        _frame({"delta": "Thinking it through.", "thinking": True}),
        _frame({"delta": "Here is the start"}),
        asyncio.CancelledError(),
    ]
    captured = _run(monkeypatch, mode, chunks, compare="false")
    [saved] = [m.metadata for m in captured.get("added_messages", [])]
    assert saved.get("stopped") is True
    assert saved.get("thinking") == "Thinking it through."
    assert captured["named"] == ["New chat"], "a stopped chat was never named"


def test_a_stopped_compare_pane_is_not_named(monkeypatch):
    chunks = [_frame({"delta": "Here is the start"}), asyncio.CancelledError()]
    captured = _run(monkeypatch, "agent", chunks, compare="true")
    assert captured["named"] == []
