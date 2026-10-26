# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1031` — a teacher whose own model fails is saved once, with its notes.

When the teacher's request fails, its loop sends `agent_terminal` and returns;
the route's terminal arm saves the reply. `run_teacher_inline` then goes on —
it may send `escalation_failed` — and the student's loop sends `[DONE]`, whose
arm saved the turn **again**: two failed replies after a reload, the second
with the note the first lacked, and `run_post_response_tasks` run for a turn
that failed. Now the `[DONE]` arm saves nothing for a turn its terminal saved,
and a note that arrived after that save is written onto the saved reply.

Driven (`Law 20`): the frames `B939` measured — the student's, a takeover, a
teacher delta, the teacher's `agent_terminal`, `escalation_failed`, `[DONE]` —
through `/api/chat_stream` and the real `save_assistant_response`.
"""
from __future__ import annotations

import asyncio

import routes.chat_routes as chat_routes
from test_a_reload_keeps_the_turns_notes import _STUDENT, _frame  # noqa: E402
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402

TEACHER_FAILS = _STUDENT + [
    _frame({"type": "teacher_takeover", "teacher_model": "big", "model": "big"}),
    _frame({"delta": "Checking", "teacher": True}),
    _frame({"type": "agent_terminal", "teacher": True, "data": {
        "failed": True, "failure": {"status": 502}, "model": "big",
        "round_texts": ["Checking\n\n[Agent stopped: Model request failed (HTTP 502)]"]}}),
    _frame({"type": "escalation_failed", "reason": "teacher request failed (HTTP 502)"}),
    "data: [DONE]\n\n",
]


def _through_route(monkeypatch, chunks):
    """The route and the real save, over a session whose `add_message` keeps
    the reply in its history and gives it a row id, as `Session.add_message`
    and `_persist_message` do. Returns (the replies saved, the post-response
    calls, the metadata writes to a saved row, the frames sent)."""
    import core.database as database
    from routes.chat_helpers import save_assistant_response

    captured = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured, agent_chunks=chunks,
                                     capture_completion=True)
    writes = []

    def save(sess, *args, **kwargs):
        before = len(captured.get("added_messages", []))
        out = save_assistant_response(sess, *args, **kwargs)
        added = captured.get("added_messages", [])[before:]
        for i, msg in enumerate(added):
            msg.metadata["_db_id"] = f"row-{before + i}"
            sess.history.append(msg)
        return added[-1].metadata["_db_id"] if added else out

    monkeypatch.setattr(chat_routes, "save_assistant_response", save)
    monkeypatch.setattr(chat_routes, "_persist_message_metadata",
                        lambda sid, mid, meta: writes.append((mid, dict(meta))) or True)
    monkeypatch.setattr(database, "update_session_last_accessed", lambda sid: None, raising=False)

    async def go():
        response = await endpoint(_RouteRequest("agent"))
        return [c async for c in response.body_iterator]

    sent = asyncio.run(go())
    replies = [m for m in captured.get("added_messages", []) if m.role == "assistant"]
    return replies, captured.get("post_processed", []), writes, sent


def test_a_teacher_that_failed_leaves_one_reply_with_its_notes(monkeypatch):
    replies, post, writes, sent = _through_route(monkeypatch, TEACHER_FAILS)
    assert len(replies) == 1, [r.content for r in replies]
    [reply] = replies
    assert reply.metadata["failed"] is True
    assert [n["type"] for n in reply.metadata["agent_notes"]] == [
        "skill_saved", "teacher_takeover", "escalation_failed"]
    # The note that came after the save reached the saved row.
    assert [(mid, [n["type"] for n in meta["agent_notes"]]) for mid, meta in writes] == [
        ("row-0", ["skill_saved", "teacher_takeover", "escalation_failed"])]
    assert post == [], "a failed turn ran the post-response tasks"
    assert sum(1 for c in sent if '"message_saved"' in c) == 1


def test_a_turn_that_did_not_fail_is_still_saved_at_its_done(monkeypatch):
    replies, post, writes, _ = _through_route(monkeypatch, _STUDENT + [
        _frame({"type": "escalation_failed", "reason": "teacher endpoint not resolvable: x"}),
        "data: [DONE]\n\n"])
    assert len(replies) == 1 and "failed" not in replies[0].metadata
    assert [n["type"] for n in replies[0].metadata["agent_notes"]] == ["skill_saved", "escalation_failed"]
    assert writes == [] and len(post) == 1


def test_a_terminal_with_nothing_after_it_writes_nothing_more(monkeypatch):
    replies, _, writes, _ = _through_route(monkeypatch, TEACHER_FAILS[:-2] + ["data: [DONE]\n\n"])
    assert len(replies) == 1 and writes == []
