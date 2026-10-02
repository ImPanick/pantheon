# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1114` and `B1140` — the chat a workflow writes into is named for the
workflow, and a task's chat is made once.

`B1114`, measured on the merged tree by `integrate-d` (P22-05's drive): the
chat "[Task] Morning inbox brief · Summarise my inbox" held only step 2's
write-up. Step 1 (no delivery) made the chat in `_execute_llm_task` under its
own stand-in name ("workflow · step"), and `_keep_workflow_chat` kept that
chat on the trigger for every later step. The stand-in now carries the
workflow's name for the chat it makes (`WorkflowNodeTask.chat_name`,
`task_scheduler.task_chat_name`).

`B1140`, measured by `integrate-e` (11 times in one server log): the first run
of a Prompt step logged "core.session_manager - ERROR - Error creating
session: (sqlite3.IntegrityError) UNIQUE constraint failed: sessions.id". The
scheduler writes the chat row itself (in the Tasks folder) and then calls
`SessionManager.ensure_task_session`, whose "if it doesn't exist" asked only
its cache — so it inserted the row a second time, raised into a bare
`except`, and left the cache empty. A stored row is now loaded, not made again.

Driven (`Law 20`): the real scheduler and walker from `_execute_task`, the real
agent loop with the model's words scripted at `stream_llm_with_fallback`, a
real `SessionManager`, all on one SQLite FILE.
"""
import json
import logging

import pytest

from tests.helpers.walker_harness import make_db, node, arrow, runs_of, seed_workflow

pytestmark = pytest.mark.asyncio

ENDPOINT = dict(model="scripted", endpoint_url="http://127.0.0.1:9/v1")


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import core.session_manager as sm_mod
    import src.agent_loop as agent_loop
    import src.task_endpoint as task_endpoint
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "chat.db")
    monkeypatch.setattr(sm_mod, "SessionLocal", factory)
    said = []

    async def model(candidates, messages, **kwargs):
        text = f"Answer {len(said) + 1}."
        said.append(text)
        yield f"data: {json.dumps({'delta': text})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", model)
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)
    monkeypatch.setattr(task_endpoint, "resolve_task_candidates", lambda **kw: [])
    manager = sm_mod.SessionManager()
    s = TaskScheduler(manager)
    s._log_to_assistant = lambda *a, **k: None

    class World:
        pass
    w = World()
    w.factory, w.s, w.manager, w.said = factory, s, manager, said
    return w


def _chats(factory):
    from core.database import ChatMessage, Session as DbSession
    db = factory()
    try:
        out = []
        for row in db.query(DbSession).order_by(DbSession.created_at).all():
            msgs = (db.query(ChatMessage).filter(ChatMessage.session_id == row.id)
                    .order_by(ChatMessage.id).all())
            out.append({"id": row.id, "name": row.name, "folder": row.folder,
                        "said": [(m.role, m.content) for m in msgs]})
        return out
    finally:
        db.close()


def _trigger_chat(factory, task_id):
    from core.database import ScheduledTask
    db = factory()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first().session_id
    finally:
        db.close()


def _session_errors(caplog):
    return [r.getMessage() for r in caplog.records
            if r.name == "core.session_manager" and r.levelno >= logging.ERROR]


async def test_a_workflows_chat_is_named_for_the_workflow_and_holds_its_write_up(world, caplog):
    """P22-05's drive, again: step 1 makes the chat with no delivery of its
    own, step 2 writes its summary up into it."""
    w = world
    caplog.set_level(logging.INFO)
    seed_workflow(w.factory, [
        node("n1", "Summarise my inbox", "llm", prompt="Summarise my unread mail.", **ENDPOINT),
        node("n2", "Write it up", "llm", prompt="Write the summary up as a short message to me.",
             output_target="session", **ENDPOINT),
    ], [arrow("n1", "n2")], name="Morning inbox brief")
    await w.s._execute_task("wf")
    [run] = runs_of(w.factory, "wf")
    assert run["status"] == "success", run
    chats = _chats(w.factory)
    assert [(c["name"], c["folder"]) for c in chats] == [("[Task] Morning inbox brief", "Tasks")], \
        "one chat, named for the workflow — not for the step that made it"
    assert chats[0]["id"] == _trigger_chat(w.factory, "wf"), "…and kept on the trigger"
    assert ("user", "Write the summary up as a short message to me.") in chats[0]["said"]
    assert _session_errors(caplog) == [], "the chat row is written once"
    assert chats[0]["id"] in w.manager.sessions, "and the session manager holds it"


async def test_a_second_run_writes_into_the_same_chat(world, caplog):
    w = world
    caplog.set_level(logging.INFO)
    seed_workflow(w.factory, [
        node("n1", "Write it up", "llm", prompt="Write a line.", output_target="session", **ENDPOINT),
    ], name="Daily line")
    await w.s._execute_task("wf")
    await w.s._execute_task("wf")
    chats = _chats(w.factory)
    assert [c["name"] for c in chats] == ["[Task] Daily line"]
    assert [m for m in chats[0]["said"] if m[0] == "user"] == [("user", "Write a line.")] * 2
    assert _session_errors(caplog) == []


async def test_a_prompt_tasks_chat_keeps_its_own_name_and_is_made_once(world, caplog):
    """`Law 1`: a task that is not a workflow names its chat as it always did;
    `B1140` held for it too."""
    from core.database import ScheduledTask
    w = world
    caplog.set_level(logging.INFO)
    db = w.factory()
    db.add(ScheduledTask(id="t1", owner="alice", name="Weekly report", task_type="llm",
                         prompt="Write my weekly report.", output_target="session",
                         trigger_type="schedule", schedule="daily", scheduled_time="08:00",
                         status="active", **ENDPOINT))
    db.commit()
    db.close()
    await w.s._execute_task("t1")
    chats = _chats(w.factory)
    assert [(c["name"], c["folder"]) for c in chats] == [("[Task] Weekly report", "Tasks")]
    assert _session_errors(caplog) == []
    assert chats[0]["id"] in w.manager.sessions


async def test_ensure_task_session_loads_a_stored_row_and_makes_a_missing_one(world, caplog):
    """The function itself, both ways: a row the scheduler already wrote is
    loaded (no second insert); an id with no row is made, as before."""
    from core.database import Session as DbSession
    w = world
    caplog.set_level(logging.INFO)
    db = w.factory()
    db.add(DbSession(id="s-stored", name="[Task] Stored", endpoint_url="u", model="m",
                     owner="alice", folder="Tasks"))
    db.commit()
    db.close()

    class Holder:
        session_id = None
    held = Holder()
    got = w.manager.ensure_task_session("s-stored", "[Task] Stored", "u", "m", owner="alice", task=held)
    assert got.id == "s-stored" and held.session_id == "s-stored"
    made = w.manager.ensure_task_session("s-new", "[Task] New", "u", "m", owner="alice")
    assert made.id == "s-new"
    assert sorted((c["id"], c["name"], c["folder"]) for c in _chats(w.factory)) == [
        ("s-new", "[Task] New", None), ("s-stored", "[Task] Stored", "Tasks")]
    assert _session_errors(caplog) == []
