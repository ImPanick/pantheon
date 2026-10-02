# SPDX-License-Identifier: AGPL-3.0-or-later
"""`C-W` — the four wave D routes, and the two data-layer changes they rest on.

  * `GET /api/workflows/palette` and `/waiting` are LITERAL paths declared
    before `/{workflow_id}`, so neither is read as a workflow's id;
  * the palette's limits are this engine's (`workflow_foreach_max_items`,
    `workflow_wait_max_hours`, `WORKFLOW_PARALLEL_STEPS`);
  * `GET /api/workflows/{id}/nodes/{node_id}/fields` is owner-scoped and knows
    its steps;
  * a refusal names the field it is about;
  * `email_received` carries who sent the mail and its subject (§ 0.12);
  * an install that already has `task_run_nodes` gains its three columns and
    the sweeper's index by ALTER, and nothing it had moves.

Through the real routers over the real scheduler and a real SQLite file.
"""

import json
import sqlite3

import pytest

from tests.helpers.walker_harness import (
    app_for, client_for, make_db, node, recording_scheduler, seed_workflow,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def world(monkeypatch, tmp_path):
    factory = make_db(monkeypatch, tmp_path / "routes.db")
    s = recording_scheduler()
    return factory, s, app_for(factory, s, monkeypatch)


async def test_the_palette_is_a_literal_route_with_this_engines_limits(world, monkeypatch):
    factory, s, app = world
    from src import settings
    monkeypatch.setattr(settings, "role_limit",
                        lambda key, owner=None: 7 if key == "workflow_foreach_max_items" else None)
    async with client_for(app) as client:
        res = await client.get("/api/workflows/palette", headers={"x-test-user": "alice"})
        waiting = await client.get("/api/workflows/waiting", headers={"x-test-user": "alice"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["limits"] == {"foreach_max_items": 7, "wait_max_hours": 168, "parallel_steps": 4}
    assert "kinds" in body, "the rest is wf-effects' palette, passed through"
    assert waiting.status_code == 200 and waiting.json() == {"waiting": []}


async def test_a_steps_fields_are_owner_scoped_and_know_the_step(world):
    factory, s, app = world
    seed_workflow(factory, [node("n1", "Fetch issue", "set", fields=[{"name": "title", "value": "x"}]),
                            node("n2", "Summarise")])
    async with client_for(app) as client:
        ok = await client.get("/api/workflows/w-wf/nodes/n2/fields", headers={"x-test-user": "alice"})
        nope = await client.get("/api/workflows/w-wf/nodes/zz/fields", headers={"x-test-user": "alice"})
        bob = await client.get("/api/workflows/w-wf/nodes/n2/fields", headers={"x-test-user": "bob"})
    assert ok.status_code == 200 and "sources" in ok.json()
    assert nope.status_code == 404 and nope.json()["detail"] == "No such step in this workflow."
    assert bob.status_code == 404


async def test_a_refusal_names_the_field_it_is_about(world):
    """`P22-09`. A save with a reference in a `never` slot is refused with the
    sentence ON that field (`DocumentRefusal.field` → `field`)."""
    factory, s, app = world
    seed_workflow(factory, [node("n1", "Post", "mcp", tool="mcp__chat__send_message",
                                 args={"text": "hi"})], owner="alice")
    graph = {"v": 1, "nodes": [node("n1", "Post", "mcp",
                                    tool="{{ steps.start.data.body }}", args={"text": "hi"})],
             "edges": []}
    async with client_for(app) as client:
        res = await client.put("/api/workflows/w-wf?check=true", headers={"x-test-user": "alice"},
                               json={"graph": graph, "base_version": 3})
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["reason"] == "mapped_never" and body["field"] == "tool"
    assert body["node_ids"] == ["n1"]


async def test_email_received_names_the_sender_and_the_subject(monkeypatch, tmp_path):
    """§ 0.12, driven through the producer (`_record_email_received_events`)
    and the real envelope builder: each new message's event carries
    `from_address` and `subject` beside the three it always carried."""
    import routes.email_routes as email_routes
    import src.event_bus as bus
    monkeypatch.setattr(email_routes, "SCHEDULED_DB", str(tmp_path / "seen.db"))
    fired = []
    monkeypatch.setattr(bus, "fire_event", lambda name, owner, payload: fired.append(
        (name, owner, payload)))
    first = [{"message_id": "<a@x>", "subject": "Old", "from_address": "old@x"}]
    email_routes._record_email_received_events("alice", "home", "INBOX", first)   # baseline
    new = first + [{"message_id": "<b@x>", "subject": "Your statement",
                    "from_address": "alerts@bank.example"}]
    email_routes._record_email_received_events("alice", "home", "INBOX", new)
    assert fired == [("email_received", "alice", {
        "account": "home", "folder": "INBOX", "message_key": "<b@x>",
        "from_address": "alerts@bank.example", "subject": "Your statement"})]
    envelope = bus.build_trigger("event", "email_received", fired[0][2])
    assert envelope["data"]["from_address"] == "alerts@bank.example"
    assert envelope["data"]["subject"] == "Your statement"


def test_an_install_that_has_the_step_table_gains_its_three_columns(monkeypatch, tmp_path):
    """`P22-11`/`P22-12`. Slice B's `task_run_nodes` may already exist, so the
    three columns arrive by ALTER (`_migrate_add_task_run_node_columns`) — read
    back from SQLite itself, twice (idempotent), with the old rows intact and
    the sweeper's `(status, resume_at)` index made."""
    import core.database as cdb
    path = tmp_path / "slice-b.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE task_run_nodes (id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL, "
                "node_id VARCHAR NOT NULL, kind VARCHAR, label VARCHAR, seq INTEGER NOT NULL, "
                "status VARCHAR, attempt INTEGER NOT NULL, dry BOOLEAN NOT NULL, port VARCHAR, "
                "reached_by VARCHAR, depth INTEGER, workflow_version INTEGER, started_at DATETIME, "
                "finished_at DATETIME, input TEXT, output TEXT, error TEXT, steps TEXT, model VARCHAR)")
    con.execute("INSERT INTO task_run_nodes (id, run_id, node_id, seq, status, attempt, dry) "
                "VALUES ('n1', 'r1', 'a', 1, 'success', 1, 0)")
    con.commit()
    before = con.execute("SELECT * FROM task_run_nodes").fetchall()
    con.close()
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_task_run_node_columns()
    cdb._migrate_add_task_run_node_columns()
    con = sqlite3.connect(path)
    try:
        cols = {r[1]: r[2] for r in con.execute("PRAGMA table_info(task_run_nodes)")}
        assert {k: cols[k] for k in ("item", "resume_at", "waiting")} == {
            "item": "INTEGER", "resume_at": "DATETIME", "waiting": "TEXT"}
        row = con.execute("SELECT * FROM task_run_nodes").fetchall()[0]
        assert row[:len(before[0])] == before[0] and row[len(before[0]):] == (None, None, None)
        indexes = {r[1] for r in con.execute("PRAGMA index_list(task_run_nodes)")}
        assert "ix_task_run_nodes_wait" in indexes
        cols_of = [c[2] for c in con.execute("PRAGMA index_info(ix_task_run_nodes_wait)")]
        assert cols_of == ["status", "resume_at"]
    finally:
        con.close()
