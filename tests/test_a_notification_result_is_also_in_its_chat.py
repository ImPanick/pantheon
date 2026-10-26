# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1078` — the Output picker says *Notification* is "Push a browser
notification with the result (also saved to a chat)"; now the result is in the
chat.

**Measured before this file:** `_deliver_task_result` returned for any target
that was not `session`, `email` or an MCP tool, so a task with output
*Notification* left its result in the run's notification body and nowhere
else — its chat held nothing, while the picker (`task_routes._output_targets`)
and a dry run's plan (`_RESULT_PLACES`: "a notification, and a chat") both
said it was saved there. A workflow step set to *Notification*
(`_deliver_node_result`) sent its own notification and returned the same way.

Driven (`Law 20`): the real scheduler from `_execute_task` down — the real
Prompt executor, the real delivery, the real walker for the step — and a real
`SessionManager` on one SQLite file. The model's answer is the one stand-in
(`_run_agent_loop`).
"""
from __future__ import annotations

import pytest

from tests.helpers.walker_harness import arrow, make_db, node, runs_of, seed_workflow

pytestmark = pytest.mark.asyncio

ENDPOINT = dict(model="m", endpoint_url="http://127.0.0.1:9/v1")


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.session_manager as sm_mod
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "notify.db")
    monkeypatch.setattr(sm_mod, "SessionLocal", factory)
    manager = sm_mod.SessionManager()
    s = TaskScheduler(manager)
    s._log_to_assistant = lambda *a, **k: None

    async def agent_loop(endpoint_url, model, task, session_id, **kw):
        return f"The answer for {task.name}."
    s._run_agent_loop = agent_loop
    return factory, s


def _chat(factory, session_id):
    from core.database import ChatMessage
    db = factory()
    try:
        return [(m.role, m.content) for m in db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id).order_by(ChatMessage.timestamp).all()]
    finally:
        db.close()


def _task_row(factory, task_id):
    from core.database import ScheduledTask
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    finally:
        db.close()


async def test_a_prompt_task_with_output_notification_keeps_its_result_in_its_chat(world):
    from core.database import ScheduledTask
    factory, s = world
    db = factory()
    try:
        db.add(ScheduledTask(id="nt", owner="alice", name="Bills due", task_type="llm",
                             prompt="Which bills are due this week?", trigger_type="schedule",
                             schedule="daily", scheduled_time="08:00", status="active",
                             output_target="notification", notifications_enabled=True,
                             **ENDPOINT))
        db.commit()
    finally:
        db.close()

    await s._execute_task("nt")

    (run,) = runs_of(factory, "nt")
    assert run["status"] == "success" and run["result"] == "The answer for Bills due."
    notes = s.pop_notifications()
    assert [(n["task_name"], n["status"], n.get("body")) for n in notes] == [
        ("Bills due", "success", "The answer for Bills due.")], "the notification, as before"
    chat = _task_row(factory, "nt").session_id
    assert chat, "the run has a chat"
    assert _chat(factory, chat) == [("user", "Which bills are due this week?"),
                                    ("assistant", "The answer for Bills due.")], \
        "…and the result is saved to it, as the picker says"


async def test_a_workflow_step_with_output_notification_keeps_its_result_in_the_chat(world):
    factory, s = world
    seed_workflow(factory, [
        node("n1", "Send me the summary", prompt="Write me the summary.",
             output_target="notification", **ENDPOINT),
    ], [], notifications_enabled=True)

    await s._execute_task("wf")

    (run,) = runs_of(factory, "wf")
    assert run["status"] == "success", run
    notes = s.pop_notifications()
    assert ("Morning digest · Send me the summary", "success",
            "The answer for Morning digest · Send me the summary.") in [
        (n["task_name"], n["status"], n.get("body")) for n in notes], "its notification, as before"
    chat = _task_row(factory, "wf").session_id
    assert chat, "the workflow keeps its chat"
    assert ("assistant", "The answer for Morning digest · Send me the summary.") in _chat(factory, chat)


async def test_a_session_task_and_a_silent_action_are_as_they_were(world):
    """`Law 1`: `session` saves as it always did; a target that is neither
    (an unknown key) still writes nowhere."""
    from core.database import ScheduledTask
    factory, s = world
    db = factory()
    try:
        db.add(ScheduledTask(id="st", owner="alice", name="To chat", task_type="llm",
                             prompt="Say hi.", trigger_type="webhook", status="active",
                             output_target="session", **ENDPOINT))
        db.add(ScheduledTask(id="xx", owner="alice", name="Elsewhere", task_type="llm",
                             prompt="Say hi.", trigger_type="webhook", status="active",
                             output_target="document", **ENDPOINT))
        db.commit()
    finally:
        db.close()
    await s._execute_task("st")
    await s._execute_task("xx")
    assert ("assistant", "The answer for To chat.") in _chat(factory, _task_row(factory, "st").session_id)
    assert _chat(factory, _task_row(factory, "xx").session_id) == []
