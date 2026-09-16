# SPDX-License-Identifier: AGPL-3.0-or-later
"""B80 — a note-level agent run that outlives the page that started it.

The two agent-solve paths in ``static/js/notes.js`` share a queue, a job runner
and a stop path, and diverged on one thing: bookkeeping. The item path wrote
``agent_session_id`` / ``agent_session_title`` / ``agent_status`` /
``agent_stream_completed_at`` onto ``n.items[idx]`` and patched them, which is
what ``B08`` made actionable. The note path wrote ``n.agent_session_id`` and
nothing else, so after a reload ``_openNoteCornerMenu`` asked
``_agentSolveState(id, null)`` — memory only — got ``''``, and rendered
*Re-run agent* with no Stop and no sign a run was ever in flight. The run is
detached server-side, so it kept working and kept costing tokens with no control
anywhere in the UI.

Measured before the fix, through ``tests/harness/note_agent_run_bookkeeping.js``:
a completed note-level solve left the note carrying ``agent_session_id`` alone
(``agent_status`` undefined), and the corner menu for a reloaded note built
``copy`` + ``agent`` and nothing else.

These drive the real functions (`Law 20`) — the job runner, the corner menu and
the stop path out of the module itself. What is pinned, and why each is a defect
if it breaks:

  * a note-level run records the same four fields an item-level one does, at the
    same two moments (start, end). One writer, two carriers — a second field set
    is how the two came apart in the first place (`Law 13`, `Law 14`);
  * a reloaded note whose stored status says ``running`` offers a Stop, and that
    Stop is `B08`'s recovery verbatim: ``/api/chat/resume`` for the run id, then
    ``/api/chat/stop`` carrying it as ``X-Pantheon-Run-Id``;
  * what the server says decides what the note then claims — a live run becomes
    ``aborted``, a 404 becomes ``stream_complete``, and a request that never
    completed writes nothing, because "your run finished" must not be what a
    person is told when their network dropped;
  * a note with ``running`` and no session id offers nothing, exactly as the
    checklist item does: there is nothing to ask and nothing to stop;
  * the item path is unchanged — same fields, same patch bodies (``items`` plus
    the parent note's latest-wins ``agent_session_id``).

The last test is the server half: the three new fields survive a PUT and come
back on the GET, because a field the API drops is a field that is not there
after the reload this row is about.
"""

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import Note
import routes.note_routes as nr

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "harness" / "note_agent_run_bookkeeping.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

FIELDS = ("agent_session_id", "agent_session_title", "agent_status",
          "agent_stream_completed_at")


def _run(*args) -> dict:
    proc = subprocess.run(
        ["node", str(HARNESS), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "node produced no stdout"
    return json.loads(lines[-1])


# ── the run is written down ─────────────────────────────────────────────────

def test_a_note_level_run_records_the_same_four_fields_an_item_does():
    """The row's core claim. Before B80 the note carried a session id alone."""
    noted = _run("job", "note")
    itemed = _run("job", "item")
    assert sorted(noted["note"]) == sorted(FIELDS)
    assert noted["note"]["agent_status"] == "stream_complete"
    assert noted["note"]["agent_session_id"] == "sess-9"
    assert noted["note"]["agent_stream_completed_at"] == "SET"
    # Same field set on the other carrier — that is the whole point.
    assert sorted(itemed["item"]) == sorted(FIELDS)
    assert set(noted["note"]) == set(itemed["item"])


def test_a_note_level_run_is_persisted_at_both_ends_of_the_job():
    """Start and finish, not just the link. The start patch is what a reload
    reads; the finish patch is what stops it claiming to still be running."""
    noted = _run("job", "note")
    assert noted["patchedKeys"] == [sorted(FIELDS), sorted(FIELDS)]
    assert [p["body"]["agent_status"] for p in noted["patched"]] == ["running", "stream_complete"]


def test_a_stopped_note_level_run_records_aborted():
    """`isItem` gated the terminal statuses too, so an aborted note-level run
    left `running` standing with nobody able to clear it."""
    noted = _run("abort", "note")
    assert noted["note"]["agent_status"] == "aborted"
    assert noted["patched"][-1]["body"] == {"agent_status": "aborted"}


def test_the_item_path_still_patches_items_and_the_parent_session_id():
    """Regression guard: the item path's patch bodies are unchanged."""
    itemed = _run("job", "item")
    assert itemed["patchedKeys"] == [["agent_session_id", "items"], ["agent_session_id", "items"]]
    # The parent note still carries the latest session id and NOTHING else —
    # an item run must not start claiming the note itself is running.
    assert itemed["note"] == {"agent_session_id": "sess-9"}
    aborted = _run("abort", "item")
    assert aborted["item"]["agent_status"] == "aborted"
    assert aborted["patchedKeys"][-1] == ["items"]


def test_the_carrier_is_the_note_for_a_note_run_and_the_item_for_an_item_run():
    got = _run("carrier", "x")
    assert got["noteIsCarrier"] is True
    assert got["itemIsCarrier"] is True
    assert got["missingItem"] is None and got["missingNote"] is None


# ── the reloaded note's ⋯ menu ──────────────────────────────────────────────

def test_a_reloaded_note_with_a_run_in_flight_offers_a_stop():
    """The row's Verify clause. Nothing live in this page's queue; the note's
    stored status and session id are all there is, and they are enough."""
    menu = _run("menu", "stale")
    assert menu["liveState"] == "", "the live queue is empty — this is the reload case"
    assert menu["stopKind"] == "detached"
    assert "agent-cancel" in menu["acts"], (
        "before B80 the note menu gated its Stop on the memory-only queue state "
        "and built copy + agent only"
    )
    assert "Stop this run" in menu["labels"]


def test_a_note_running_with_no_session_offers_no_stop():
    """Same rule the checklist item follows: nothing to ask, nothing to claim."""
    menu = _run("menu", "orphan")
    assert menu["stopKind"] == "orphan"
    assert "agent-cancel" not in menu["acts"]


@pytest.mark.parametrize("fixture,label", [("ran", "Re-run agent"), ("idle", "Agent: solve this")])
def test_a_finished_note_run_offers_no_stop(fixture, label):
    menu = _run("menu", fixture)
    assert "agent-cancel" not in menu["acts"]
    assert label in menu["labels"]


def test_a_live_note_run_still_cancels_in_memory():
    """`Law 1`: the queue-owned cases keep the behaviour they had."""
    live = _run("menu", "live")
    assert live["acts"] == ["copy", "agent", "agent-cancel"]
    assert "Stop this run" in live["labels"]
    queued = _run("menu", "queued")
    assert "Remove from queue" in queued["labels"]


# ── pressing it ─────────────────────────────────────────────────────────────

def test_stopping_a_detached_note_run_recovers_the_run_id_and_stops_it():
    got = _run("stop", "detached")
    assert got["noStopEntry"] is False
    assert [f["url"] for f in got["fetched"]] == [
        "/api/chat/resume/sess-9", "/api/chat/stop/sess-9",
    ]
    assert got["fetched"][1]["method"] == "POST"
    assert got["fetched"][1]["runId"] == "run-77", "the stop fails closed without the run id"
    assert got["note"]["agent_status"] == "aborted"
    assert got["patched"] == [{"id": "note-1", "body": {"agent_status": "aborted"}}]


def test_a_run_the_server_says_is_over_is_recorded_as_finished_not_aborted():
    got = _run("stop", "gone")
    assert [f["url"] for f in got["fetched"]] == ["/api/chat/resume/sess-9"]
    assert got["note"]["agent_status"] == "stream_complete"
    assert any("already finished" in t for t in got["toasts"])


def test_a_stop_that_never_reached_the_server_writes_nothing():
    """A dropped network is not evidence a run ended."""
    got = _run("stop", "throws")
    assert got["note"]["agent_status"] == "running"
    assert got["patched"] == []
    assert any(t.startswith("ERR:") for t in got["toasts"])


def test_a_live_note_run_stops_without_a_server_round_trip():
    got = _run("stop", "live")
    assert [f["url"] for f in got["fetched"]] == ["/api/chat/stop/sess-9"]
    assert got["fetched"][0]["runId"] == "run-1"


# ── the server half: the fields have to survive the round trip ──────────────

_PEER = ("203.0.113.7", 54321)


class _Identity:
    """Pure-ASGI identity shim — same reason as test_notes_fail_closed_auth."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            state = scope.setdefault("state", {})
            user = headers.get(b"x-test-user")
            if user:
                state["current_user"] = user.decode()
        await self.app(scope, receive, send)


@pytest.fixture
def note_api(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'notes.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(nr, "SessionLocal", factory)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("LOCALHOST_BYPASS", raising=False)
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(is_configured=True)
    app.include_router(nr.setup_note_routes())
    db = factory()
    db.add(Note(id="note-1", owner="alice", title="ship it"))
    db.commit()
    db.close()
    transport = httpx.ASGITransport(app=_Identity(app), client=_PEER)
    return httpx.AsyncClient(transport=transport, base_url="http://notes.test")


async def test_the_note_agent_fields_survive_a_put_and_come_back_on_the_get(note_api):
    """A field the API drops is a field that is not there after the reload."""
    alice = {"x-test-user": "alice"}
    body = {
        "agent_session_id": "sess-9",
        "agent_session_title": "Agent: ship it",
        "agent_status": "running",
        "agent_stream_completed_at": "",
    }
    async with note_api as c:
        put = await c.put("/api/notes/note-1", json=body, headers=alice)
        assert put.status_code == 200
        assert {k: put.json()[k] for k in FIELDS} == body
        got = (await c.get("/api/notes/note-1", headers=alice)).json()
        assert {k: got[k] for k in FIELDS} == body
        # And the terminal patch the job runner sends at the end.
        done = await c.put("/api/notes/note-1",
                           json={"agent_status": "stream_complete"}, headers=alice)
        assert done.json()["agent_status"] == "stream_complete"
        assert done.json()["agent_session_id"] == "sess-9"


def test_an_existing_database_gains_the_new_columns(tmp_path, monkeypatch):
    """A fix that only works on a fresh database is not shipped.

    `notes` is migrated in place by `_migrate_add_notes_sort_order`, beside the
    `agent_session_id` column added the same way. Driven against a table built
    with the OLD shape, because that is every existing install.
    """
    import sqlite3

    db_path = tmp_path / "pantheon.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE notes (id TEXT PRIMARY KEY, owner TEXT, title TEXT, "
        "content TEXT, items TEXT, note_type TEXT, agent_session_id TEXT)"
    )
    conn.execute("INSERT INTO notes (id, owner, agent_session_id) VALUES ('n1','alice','sess-9')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(cdb, "DATABASE_URL", f"sqlite:///{db_path}")
    cdb._migrate_add_notes_sort_order()

    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
    row = conn.execute("SELECT agent_session_id, agent_status FROM notes").fetchone()
    conn.close()
    assert {"agent_status", "agent_session_title", "agent_stream_completed_at"} <= cols
    # And the row that was already there is intact.
    assert row == ("sess-9", None)
    # Idempotent: startup runs it on every boot.
    cdb._migrate_add_notes_sort_order()


async def test_the_listing_carries_the_agent_fields_too(note_api):
    """The notes panel renders from the list, not from per-note GETs."""
    alice = {"x-test-user": "alice"}
    async with note_api as c:
        await c.put("/api/notes/note-1", json={"agent_status": "running",
                                               "agent_session_id": "sess-9"}, headers=alice)
        listed = (await c.get("/api/notes", headers=alice)).json()["notes"]
    assert listed[0]["agent_status"] == "running"
    assert listed[0]["agent_session_id"] == "sess-9"
