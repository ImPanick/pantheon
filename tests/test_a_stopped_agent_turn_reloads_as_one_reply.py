# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B-NEW-11` (fx2-chat), the server half: an agent turn the person stopped is
kept the way the screen showed it, so its reload is the same one reply.

**What was wrong** (measured on the showcase at `1049a26` + this lane's
drawing fix, `/work/notes/fx2-chat.md` § drive): the agent branch of
`/api/chat_stream` saved a stopped reply only once it had written words
(`if full_response`), and saved its text and reasoning but none of its rows.
Stopped while a step was thinking, the turn left nothing; stopped in its answer,
the reload drew a plain message — the rows gone, and after an approval a second
reply under the one that paused at the card. And `mark-stopped` marked "the
last assistant message", whichever: with the run's save not yet landed, that was
the reply that had paused at the card (or the previous turn's finished reply).

**What is pinned.** Through the real route (the double
`test_foreground_model_routing.py` builds, as the CHAT-M-16 file drives it): a
reply stopped mid-turn keeps `tool_events` (the rows the browser was shown,
a refused call as a refusal) and `round_texts` beside CHAT-M-21's
`round_thinking`, and one stopped while thinking is kept too; the approved
call's row keeps the approval's fingerprint. And the reply `mark-stopped`
marks: this turn's, never one paused at a card, none when the run saved none.
The drawing of such a record is `test_one_agent_turn_is_one_reply.py`.
"""

import asyncio
import json

import pytest

import routes.chat_routes as chat_routes
from core.models import ChatMessage
from routes.history.history_routes import _stoppable_reply
from test_a_stopped_reply_keeps_its_thinking_and_gets_a_name import _frame, _run


def _stop_mid_turn(monkeypatch, chunks):
    captured = _run(monkeypatch, "agent", chunks + [asyncio.CancelledError()], compare="false")
    saved = [m for m in captured.get("added_messages", [])]
    return saved


ROW_1 = {"type": "tool_output", "tool": "manage_documents", "command": '{"action": "list_folders"}',
         "round": 1, "output": "5 folders", "exit_code": 0, "status": "ok"}
ROW_2 = {"type": "tool_output", "tool": "manage_documents", "command": '{"action": "list"}',
         "round": 2, "output": "3 documents", "exit_code": 0, "status": "ok",
         "document_content": "x" * 50}


def test_a_turn_stopped_in_its_answer_keeps_its_rows_and_rounds(monkeypatch):
    [saved] = _stop_mid_turn(monkeypatch, [
        _frame({"delta": "Folders first.", "thinking": True}),
        _frame({"type": "tool_start", "tool": "manage_documents", "round": 1}),
        _frame(ROW_1),
        _frame({"type": "agent_step", "round": 2}),
        _frame({"delta": "Now the unfiled ones.", "thinking": True}),
        _frame(ROW_2),
        _frame({"type": "agent_step", "round": 3}),
        _frame({"delta": "Counting.", "thinking": True}),
        _frame({"delta": "You have three"}),
    ])
    md = saved.metadata
    assert md["stopped"] is True
    assert md["round_thinking"] == ["Folders first.", "Now the unfiled ones.", "Counting."]
    assert md["round_texts"] == ["", "", "You have three"]
    # The rows the browser drew, as a finished reply keeps them: no frame type,
    # no streamed document body.
    assert [(r["tool"], r["round"], r["output"]) for r in md["tool_events"]] == [
        ("manage_documents", 1, "5 folders"), ("manage_documents", 2, "3 documents")]
    assert all("type" not in r and "document_content" not in r for r in md["tool_events"])


def test_a_turn_stopped_while_a_step_thinks_is_kept(monkeypatch):
    saved = _stop_mid_turn(monkeypatch, [
        _frame({"delta": "Folders first.", "thinking": True}),
        _frame(ROW_1),
        _frame({"type": "agent_step", "round": 2}),
        _frame({"delta": "Now the unf", "thinking": True}),
    ])
    assert len(saved) == 1, "a reply stopped before its first word was not kept"
    md = saved[0].metadata
    assert saved[0].content == "" and md["stopped"] is True
    assert md["round_thinking"] == ["Folders first.", "Now the unf"]
    assert md["round_texts"] == ["", ""] and len(md["tool_events"]) == 1


def test_a_turn_stopped_with_nothing_shown_is_left_to_the_browser(monkeypatch):
    """No words and no reasoning: the browser keeps its own *cancelled* line
    (`_renderCancelledBubble`), so the route adds no second record."""
    assert _stop_mid_turn(monkeypatch, [_frame(ROW_1)]) == []


def test_a_refused_call_is_kept_as_a_refusal_and_an_approved_one_keeps_its_fingerprint():
    blocked = chat_routes._shown_tool_row({
        "type": "tool_blocked", "tool": "bash", "round": 2, "command": "rm -rf /tmp/x",
        "reason": "refused by the current tool policy", "policy": "current_tool_policy"})
    assert blocked == {"tool": "bash", "round": 2, "command": "rm -rf /tmp/x",
                       "policy": "current_tool_policy", "output": "refused by the current tool policy",
                       "exit_code": None, "blocked": True}
    approved = chat_routes._shown_tool_row(dict(ROW_1, approved=True), "5f3c1d2e9a8b7c6d")
    assert approved["approval_digest"] == "5f3c1d2e9a8b7c6d"
    assert "approval_digest" not in chat_routes._shown_tool_row(ROW_1, "5f3c1d2e9a8b7c6d")
    assert chat_routes._shown_tool_row({"type": "agent_step", "round": 2}) is None


def test_the_fingerprint_is_the_one_the_loop_gives_the_approved_call():
    """`src/agent_loop.py` stamps the approved call `exact_approval.pending.digest[:16]`;
    the stopped reply's row must carry the same, or the reload cannot match it
    to the row that asked (measured: the first cut read `exact_approval.digest`,
    which is not there, and the reload drew the turn as two replies again)."""
    from types import SimpleNamespace
    exact = SimpleNamespace(pending=SimpleNamespace(digest="86f97e1f8374f62c" + "0" * 48))
    assert chat_routes._approval_fingerprint(exact) == "86f97e1f8374f62c"
    assert chat_routes._approval_fingerprint(None) == ""


# ── which reply a Stop marks ────────────────────────────────────────────────

def _paused():
    return ChatMessage("assistant", "Allow this task to continue?", metadata={
        "round_texts": [""], "tool_events": [{"round": 1, "tool": "manage_tasks", "ask_user": {
            "kind": "tool_approval", "approval_id": "a1", "resolved": "approve_task"}}]})


def test_a_stop_marks_this_turns_reply():
    reply = ChatMessage("assistant", "You have three", metadata={"round_texts": ["", "You have three"]})
    history = [ChatMessage("user", "Earlier."), ChatMessage("assistant", "Done before."),
               ChatMessage("user", "List my folders."), _paused(), reply]
    assert _stoppable_reply(history) is reply


@pytest.mark.parametrize("tail", ["nothing", "paused"])
def test_a_stop_before_the_run_saved_marks_nothing(tail):
    """The run's save has not landed: the previous turn's finished reply and the
    reply that paused at the card are not what was stopped."""
    history = [ChatMessage("user", "Earlier."), ChatMessage("assistant", "Done before."),
               ChatMessage("user", "List my folders.")]
    if tail == "paused":
        history.append(_paused())
    assert _stoppable_reply(history) is None


def test_a_stop_reads_a_history_of_dicts_too():
    history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hel", "metadata": {}}]
    assert _stoppable_reply(history) is history[1]
