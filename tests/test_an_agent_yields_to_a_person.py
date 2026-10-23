# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-11` — a hired agent's run yields to a person using Pantheon.

An agent's run is its hire's task's run, so it passes the task engine's own
gate (`B1060`): a background run waits for Pantheon to be idle *before* it
takes the model slot, a person's own run goes ahead of it, and it then runs
with what started it. Nothing here is the hall's: this file proves the hire's
compiled task is an ordinary background task to that gate, with the gate's
own harness (imported — `Law 14`) and a hire made by the real
`src.agents.hires` from a real shipped manifest.

**Measured before this file, on `f26ee3d`:** inherited and untested for an
agent's task.
"""

import pytest

from tests.test_a_background_run_waits_for_idle_with_its_trigger import (  # noqa: F401
    _heartbeat, _runs, _scheduler, _tab_closes, _turns, _until, gate, task_db,
)
import src.task_scheduler as ts
from core.database import ScheduledTask


def _hire(factory, monkeypatch, tmp_path):
    import src.constants as constants
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path))
    from src.agents import hires as H
    from src.agents.catalogue import get_agent
    db = factory()
    try:
        h = H.make_hire(db, owner="alice", manifest=get_agent("alice", "deep-researcher"),
                        inputs={"question": "What changed in solid-state batteries?"})
        db.commit()
        return H.task_ids_of(db, h.id)[0]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_an_agents_run_waits_for_idle_and_a_persons_run_goes_first(task_db, gate, monkeypatch, tmp_path):
    agent_task = _hire(task_db, monkeypatch, tmp_path)
    db = task_db()
    db.add(ScheduledTask(id="mine", owner="alice", name="My own task", prompt="Do it.",
                         task_type="llm", trigger_type="webhook", status="active"))
    db.commit()
    db.close()
    ran = []
    s = _scheduler(ran)
    await _heartbeat(s)                                     # a person has Pantheon open

    assert await s.run_task_now(agent_task) is True         # the agent's trigger fires
    await _until(lambda: _runs(task_db, agent_task)
                 and _runs(task_db, agent_task)[0]["result"] == ts.WAITING_FOR_IDLE,
                 "the agent's run waits for idle")
    await _turns(10)
    assert await s.run_task_now("mine", started_by=ts.STARTED_BY_PERSON) is True
    await _until(lambda: [r["status"] for r in _runs(task_db, "mine")] == ["success"],
                 "the person's run goes ahead of the waiting agent")
    assert [t for t, _ in ran] == ["mine"]
    assert _runs(task_db, agent_task)[0]["status"] == "queued"

    await _tab_closes()
    await _until(lambda: [t for t, _ in ran] == ["mine", agent_task], "then the agent runs")
    await _until(lambda: [r["status"] for r in _runs(task_db, agent_task)] == ["success"],
                 "and its run ends")
