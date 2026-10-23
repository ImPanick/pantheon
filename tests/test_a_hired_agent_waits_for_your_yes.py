# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-08` — a hired agent whose effects table says *ask* waits for its
person's yes, the plain task's way (`B1102`), and Allow runs the action once.

Everything that decides is real (`Law 20`): the real scheduler and agent loop
(only the model's words are scripted), the hire's run plan, the real gate with
the hire's effects in it, the real approval store, and the real task routes —
the world is `test_a_plain_task_waits_for_your_yes.py`'s, imported (`Law 14`).
The agent's file is a test's own, so the table under test is the one written
here: `bash`, `execute_code: ask`.

**Measured before this file, on `6f51844`:** the gate refused the call with
"waits for your yes" (`P24-07`) — whether the run then parked was untested.
"""

import pytest

from src.tool_approvals import tool_approval_store
from tests.helpers.walker_harness import client_for, records_of, runs_of, settle
from tests.test_a_plain_task_waits_for_your_yes import ALICE, ENDPOINT, world  # noqa: F401

pytestmark = pytest.mark.asyncio

AGENT = """---
id: shell-hand
name: Shell Hand
tagline: Runs one command, after asking.
section: development
icon: terminal
version: 1.0.0
wave: 1
inputs: []
triggers:
  - {on: hand}
tools: [bash]
needs: {connectors: [], min_context: 8000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: ask}
budget: {runs_per_day: 5, max_steps: 5, max_minutes: 5}
memory: none
---
Run `printf hello` and say what it printed.
"""


@pytest.fixture()
def hired(world, monkeypatch):
    from core.database import ScheduledTask
    from src.agents import hires as H
    import src.agents.catalogue as C
    from src.agents.manifest import parse_manifest
    m = parse_manifest(AGENT, source="own")
    monkeypatch.setattr(C, "get_agent", lambda owner, aid, **kw: m if aid == m.id else None)
    db = world.factory()
    h = H.make_hire(db, owner="alice", manifest=m)
    task = db.query(ScheduledTask).get(H.task_ids_of(db, h.id)[0])
    task.model, task.endpoint_url = ENDPOINT["model"], ENDPOINT["endpoint_url"]
    db.commit()
    tid = task.id
    db.close()
    return world, tid


async def test_an_ask_effect_parks_the_run_and_allow_runs_it_once(hired):
    w, tid = hired
    w.script.append("```bash\nprintf hello\n```")
    await w.s._execute_task(tid)
    run = runs_of(w.factory, tid)[-1]
    assert run["status"] == "waiting", run
    assert w.executed == [], "nothing ran before the yes"
    [rec] = records_of(w.factory, run["id"])
    card = rec["waiting"]["approval"]
    assert card["action"]["tool"] == "bash" and card["action"]["content"] == "printf hello"
    assert card["gate"]["tainted"] is False, "nothing untrusted was read: the hire asked, not the floor"
    assert tool_approval_store.peek(card["approval_id"]) is not None
    async with client_for(w.app) as client:
        listed = (await client.get("/api/tasks/waiting", headers=ALICE)).json()["waiting"]
        assert [(x["task_id"], x["run_id"]) for x in listed] == [(tid, run["id"])]
        w.script.append("It printed hello.")
        res = await client.post(f"/api/tasks/{tid}/runs/{run['id']}/answer", headers=ALICE,
                                json={"approval_id": card["approval_id"], "decision": "approve_task"})
        assert res.status_code == 200, res.text
        await settle(w.s)
    assert w.executed == [("bash", "printf hello")], "the sealed action ran exactly once"
    [run] = runs_of(w.factory, tid)
    assert run["status"] == "success", run


async def test_deny_runs_nothing(hired):
    w, tid = hired
    w.script.append("```bash\nprintf hello\n```")
    await w.s._execute_task(tid)
    run = runs_of(w.factory, tid)[-1]
    [rec] = records_of(w.factory, run["id"])
    async with client_for(w.app) as client:
        res = await client.post(f"/api/tasks/{tid}/runs/{run['id']}/answer", headers=ALICE,
                                json={"approval_id": rec["waiting"]["approval"]["approval_id"],
                                      "decision": "deny"})
        assert res.status_code == 200 and res.json()["outcome"] == "denied"
        await settle(w.s)
    assert w.executed == []
    assert runs_of(w.factory, tid)[-1]["status"] == "error"
