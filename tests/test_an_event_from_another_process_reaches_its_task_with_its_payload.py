# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1075` — an event fired where no scheduler runs reaches its task with its
payload.

**Measured before this file** (`SLICE-B-DESIGN` § 0.6, confirmed by
`wf-engine`, and here): `mcp_servers/email_server.py` fires `document_updated`
(a reply draft merged into a document) and `document_created` (a new draft) in
the email MCP server's SUBPROCESS, where `event_bus._task_scheduler` is None.
`_handle_event`'s no-scheduler branch wrote `next_run = now` and nothing else,
so the main process's loop ran the task as a plain due task: the envelope
`build_trigger` made — which document, its title — was dropped on the floor,
and `B602`/`P8-23`'s promise did not hold for the one producer of
`document_updated` in the product.

Now the envelope is kept on the row with the `next_run` it explains
(`ScheduledTask.pending_trigger`) and the run that starts takes it.

Driven (`Law 20`): the email server's real `_create_email_draft_document`
merges a reply into a real document on a real SQLite file with no scheduler
set (the subprocess), and the real `TaskScheduler`'s loop (`_check_due_tasks`)
runs the task on the same file (the main process); only the model is a
recorder (`walker_harness.recording_scheduler`).
"""
from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from tests.helpers.walker_harness import OWNER, make_db, recording_scheduler

import core.database as cdb  # noqa: E402
import src.event_bus as bus  # noqa: E402


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import src.task_scheduler as ts
    monkeypatch.setattr(ts, "dispatch_hold", lambda *a, **k: 0.0)   # no `P15-10` jitter here
    factory = make_db(monkeypatch, tmp_path / "events.db")
    db = factory()
    db.add(cdb.ScheduledTask(id="t1", owner=OWNER, name="Read the edited draft", task_type="llm",
                             prompt="Say which document changed.", trigger_type="event",
                             trigger_event="document_updated", trigger_count=1, status="active"))
    db.add(cdb.Document(id="doc-7", title="Re: Thursday", language="email", owner=OWNER,
                        current_content="To: ann@example.com\nSubject: Re: Thursday\n---\nOld reply",
                        version_count=1, is_active=True, source_email_uid="42",
                        source_email_folder="INBOX"))
    db.commit()
    db.close()
    return factory


def _merge_a_reply_in_the_email_server(monkeypatch):
    """What the email MCP server does in its own process: no scheduler."""
    import mcp_servers.email_server as srv
    monkeypatch.setattr(bus, "_task_scheduler", None)
    monkeypatch.setattr(srv, "_load_config", lambda account=None: {"account_name": "work", "account_id": "a1"})
    monkeypatch.setattr(srv, "_current_owner", lambda: OWNER)
    out = srv._create_email_draft_document(to="ann@example.com", subject="Re: Thursday",
                                           body="Thursday works.", source_uid="42",
                                           source_folder="INBOX")
    assert out["updated"] is True and out["doc_id"] == "doc-7", "the draft was merged (the premise)"


def _row(factory, task_id="t1"):
    db = factory()
    try:
        return db.query(cdb.ScheduledTask).filter(cdb.ScheduledTask.id == task_id).first()
    finally:
        db.close()


async def _loop_once(s):
    await s._check_due_tasks()
    for _ in range(300):
        await asyncio.sleep(0.01)
        if not s._executing:
            return


def test_a_task_on_document_updated_fired_by_a_merged_email_draft_is_handed_the_document(
        world, monkeypatch):
    _merge_a_reply_in_the_email_server(monkeypatch)
    row = _row(world)
    assert row.next_run is not None, "queued for the main process's loop"
    assert json.loads(row.pending_trigger)["data"] == {"document_id": "doc-7", "title": "Re: Thursday"}

    s = recording_scheduler()                      # the main process
    asyncio.run(_loop_once(s))
    assert [c["name"] for c in s.calls] == ["Read the edited draft"]
    handed = s.calls[0]["trigger"]
    assert handed is not None, "the task ran with no payload"
    assert (handed["source"], handed["event"]) == ("event", "document_updated")
    assert handed["data"] == {"document_id": "doc-7", "title": "Re: Thursday"}
    assert _row(world).pending_trigger is None, "taken by the run it was for"


def test_a_queued_event_is_handed_to_one_run_only(world, monkeypatch):
    _merge_a_reply_in_the_email_server(monkeypatch)
    s = recording_scheduler()
    asyncio.run(_loop_once(s))
    asyncio.run(s._execute_task("t1"))             # a later Run now
    assert s.calls[0]["trigger"] is not None and s.calls[1]["trigger"] is None


def test_an_event_in_this_process_is_not_handed_again_by_its_queued_copy(world, monkeypatch):
    """With a scheduler, the bus runs the task at once with the envelope; the
    copy it kept for a restart is taken by that run, so the next run (say, Run
    now) is not handed the same document again."""
    s = recording_scheduler()
    monkeypatch.setattr(bus, "_task_scheduler", s)

    async def go():
        await bus._handle_event("document_updated", OWNER, {"document_id": "doc-7", "title": "Re: Thursday"})
        for _ in range(300):
            await asyncio.sleep(0.01)
            if not s._executing and s.calls:
                break
        await s._execute_task("t1")
    asyncio.run(go())
    assert [c["trigger"]["data"] if c["trigger"] else None for c in s.calls] == [
        {"document_id": "doc-7", "title": "Re: Thursday"}, None]
    assert _row(world).pending_trigger is None


def test_a_dry_run_leaves_a_queued_event_for_the_real_run(world, monkeypatch):
    _merge_a_reply_in_the_email_server(monkeypatch)
    s = recording_scheduler()
    asyncio.run(s._execute_task("t1", dry=True))
    assert _row(world).pending_trigger is not None


def test_an_install_from_before_gains_the_column(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE scheduled_tasks (id TEXT PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{path}")
    cdb._migrate_add_scheduled_task_execution_columns()
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(scheduled_tasks)")]
    conn.close()
    assert "pending_trigger" in cols


def test_a_backup_does_not_carry_a_queued_event(world, monkeypatch):
    from routes.backup_routes import backup_tasks
    _merge_a_reply_in_the_email_server(monkeypatch)
    db = world()
    try:
        (task,) = [t for t in backup_tasks(db, OWNER) if t["id"] == "t1"]
    finally:
        db.close()
    assert "pending_trigger" not in task
