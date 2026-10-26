# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1076` — a `task_type` no task can be is refused, in words, at every door
that writes one.

**Measured before this file:** `POST /api/tasks {"task_type": "banana", …}`
answered 200 and stored "banana"; so did `PUT`; so did the agent's
`manage_tasks` create and edit (only the tool schema's enum stood in front of
the model). A stored unknown word ran as a Prompt task with no prompt —
`_execute_task_locked`'s `else`. `wf-api` had closed the doors to `workflow`
only (`P22-05`).

Now one allowlist (`PERSON_TASK_TYPES`, `task_type_problem`) is asked by the
route's create and edit and by the tool's create and edit, and the refusal
names the kinds a task can be. A row already stored is not refused for keeping
its kind (`Law 1`). Driven (`Law 20`): the real routes and the real tool over a
real SQLite file (`B1063`'s world).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_your_own_housekeeping_task_is_kept import OWNER, _rows, world  # noqa: E402,F401

KINDS = ("Prompt (llm)", "Research (research)", "Action (action)")


def _says_the_kinds(sentence):
    return all(kind in sentence for kind in KINDS) and "Workbench" in sentence


def test_the_route_refuses_an_unknown_kind_on_create_and_edit(world):
    factory, _s, client, _ran = world
    r = client.post("/api/tasks", json={"name": "Fruit", "task_type": "banana",
                                         "prompt": "Peel it.", "schedule": "daily"})
    assert r.status_code == 400, r.text
    assert "“banana” is not a kind of task" in r.json()["detail"]
    assert _says_the_kinds(r.json()["detail"]), r.json()["detail"]
    assert not [t for t in _rows(factory).values() if t.name == "Fruit"], "it was stored"

    r = client.post("/api/tasks", json={"name": "Brief", "task_type": "llm",
                                         "prompt": "Summarise.", "schedule": "daily"})
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    r = client.put(f"/api/tasks/{task_id}", json={"task_type": "foo"})
    assert r.status_code == 400 and _says_the_kinds(r.json()["detail"]), r.text
    assert _rows(factory)[task_id].task_type == "llm"


def test_every_kind_a_person_makes_still_saves(world):
    _factory, _s, client, _ran = world
    for body in ({"task_type": "llm", "prompt": "Summarise."},
                 {"task_type": "research", "prompt": "What changed in SQLite?"},
                 {"task_type": "action", "action": "tidy_documents"}):
        r = client.post("/api/tasks", json={"name": body["task_type"], "schedule": "daily", **body})
        assert r.status_code == 200, (body, r.text)


def test_a_row_stored_with_another_word_is_not_refused_for_keeping_it(world):
    """`Law 1`: an install's existing row loads and saves as it is."""
    from core.database import ScheduledTask
    factory, _s, client, _ran = world
    db = factory()
    db.add(ScheduledTask(id="old", owner=OWNER, name="Old one", task_type="download",
                         trigger_type="webhook", status="active"))
    db.commit()
    db.close()
    assert client.get("/api/tasks/old").json()["task_type"] == "download"
    r = client.put("/api/tasks/old", json={"name": "Old one, renamed", "task_type": "download"})
    assert r.status_code == 200, r.text


def test_the_agents_tool_refuses_it_too(world):
    from src.tools.system import do_manage_tasks
    factory, _s, _client, _ran = world
    out = asyncio.run(do_manage_tasks(json.dumps({
        "action": "create", "name": "Fruit", "task_type": "banana", "prompt": "Peel it."}),
        owner=OWNER))
    assert out.get("exit_code") == 1 and _says_the_kinds(out["error"]), out
    assert not [t for t in _rows(factory).values() if t.name == "Fruit"]

    out = asyncio.run(do_manage_tasks(json.dumps({
        "action": "create", "name": "Brief", "task_type": "llm", "prompt": "Summarise."}),
        owner=OWNER))
    assert out.get("exit_code") == 0, out
    out = asyncio.run(do_manage_tasks(json.dumps({
        "action": "edit", "task_id": out["task_id"], "task_type": "banana"}), owner=OWNER))
    assert out.get("exit_code") == 1 and _says_the_kinds(out["error"]), out
