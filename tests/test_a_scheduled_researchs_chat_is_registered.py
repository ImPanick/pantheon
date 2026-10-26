# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1171` — a scheduled research's chat is registered with the session
manager it was made for.

**Measured before this file:** `_execute_research_task` wrote the chat row and
then called `self._session_manager._db_to_session(sess)` — one argument to a
method that takes two (`db_session, db`) — so it raised `TypeError` into a bare
`except: pass` on every run and the session manager never held the chat. It
was harmless only because `get_session` loads a missing session from the
database; the line read as though it worked. It now asks
`SessionManager.ensure_task_session`, as the other two task sites do.

Driven (`Law 20`): the real `TaskScheduler._execute_research_task` and a real
`SessionManager` on one SQLite file; the researcher is the one stand-in (a
research run's model rounds are not what is under test).
"""
from __future__ import annotations

import pytest

from tests.helpers.walker_harness import make_db

pytestmark = pytest.mark.asyncio


class _Researcher:
    """`DeepResearcher`, answering at once."""

    findings = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def research(self, prompt):
        return f"# Report\n\nWhat I found about {prompt}."

    def get_stats(self):
        return {"rounds": 1}


async def test_the_research_chat_is_in_the_session_manager(monkeypatch, tmp_path):
    import core.session_manager as sm_mod
    import src.deep_research as deep_research
    import src.research_handler as research_handler
    from core.database import ScheduledTask, Session as DbSession
    from src.task_scheduler import TaskScheduler

    factory = make_db(monkeypatch, tmp_path / "research.db")
    monkeypatch.setattr(sm_mod, "SessionLocal", factory)
    monkeypatch.setattr(deep_research, "DeepResearcher", _Researcher)
    monkeypatch.setattr(research_handler, "RESEARCH_DATA_DIR", tmp_path / "research")
    manager = sm_mod.SessionManager()
    s = TaskScheduler(manager)

    db = factory()
    try:
        task = ScheduledTask(id="rs", owner="alice", name="Weekly look", task_type="research",
                             prompt="local inference servers", status="active",
                             model="scripted", endpoint_url="http://127.0.0.1:9/v1")
        db.add(task)
        db.commit()
        report = await s._execute_research_task(task, db, run_id="r1")
        session_id = task.session_id
    finally:
        db.close()

    assert report.startswith("# Report")
    assert session_id, "the run made a chat for its report"
    db = factory()
    try:
        row = db.query(DbSession).filter(DbSession.id == session_id).first()
        assert (row.name, row.folder) == ("[Research] Weekly look", "Tasks")
        assert db.query(ScheduledTask).filter(ScheduledTask.id == "rs").first().session_id == session_id
    finally:
        db.close()
    assert session_id in manager.sessions, "the chat it made is registered"
    assert manager.sessions[session_id].name == "[Research] Weekly look"
    assert (tmp_path / "research" / f"{session_id}.json").exists(), "and its report kept"
