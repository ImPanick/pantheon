# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1223` — the writes a person makes first wait for a held lock off the loop.

`P23-07` bounded what a held SQLite lock costs while route handlers did their
database work on the event loop: half a second, shared by every request, and
then the write was refused with a 503. **Measured on `a16e7d75`** (`B1223`'s
count, `/tmp/…/count_async_db.py`: an `async def` route whose own body calls
`SessionLocal()` or `get_db_session()`): 143 such handlers — a document save,
a task edit, a mail account, the gallery, the calendar … — so a person saving a
document while a run finished was told *"busy, try again"*, and everyone else's
requests waited out that half second with them.

They are plain `def` now (Starlette runs them in its thread pool), or their
database work goes through `asyncio.to_thread`: off the loop a writer waits its
turn the 5 s it always could, and nothing else waits with it. What is left is
held to a ceiling (`tests/test_route_handlers_keep_the_database_off_the_loop.py`).

Driven on the real app, out of process (importing `app` brings the whole
application up — `test_a_held_database_lock_is_answered_in_a_second.py`'s
shape): another connection holds the write lock for two seconds while a
document is saved, a task edited, a mail account added and a calendar event
made, and a request that touches no database is timed beside them.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
HOLD_S = 2.0

_PROBE = textwrap.dedent(
    """
    import json, sqlite3, threading, time, uuid
    import app as app_module
    from tests.helpers.signed_in import ADMIN, sign_in
    from fastapi.testclient import TestClient
    from core.database import SessionLocal, ScheduledTask
    DB = __DB__
    HOLD = __HOLD__
    out = {}
    with TestClient(app_module.app) as client:
        sign_in(app_module, client)
        doc = client.post("/api/document", json={"title": "Draft", "content": "one"}).json()
        # FastAPI builds a router's routes the first time a request walks into
        # it — on the loop, a few hundred milliseconds on a busy machine, once
        # a process, no database. A path no route answers walks them all, so
        # that cost is paid here, before the lock, and what is timed under it
        # is the database wait alone.
        client.get("/api/no-route-answers-this")
        db = SessionLocal()
        task_id = uuid.uuid4().hex
        db.add(ScheduledTask(id=task_id, owner=ADMIN, name="Probe", prompt="hi", task_type="llm"))
        db.commit(); db.close()
        held = threading.Event()
        def hold():
            c = sqlite3.connect(DB, timeout=1)
            c.execute("BEGIN IMMEDIATE")
            held.set(); time.sleep(HOLD); c.rollback(); c.close()
        writes = {
            "document_save": lambda: client.put(f"/api/document/{doc['id']}", json={"content": "two"}),
            "task_edit": lambda: client.put(f"/api/tasks/{task_id}", json={"name": "Probe, renamed"}),
            "mail_account": lambda: client.post("/api/email/accounts", json={
                "name": "probe", "imap_host": "x", "imap_user": "x", "imap_password": "x", "smtp_host": "x"}),
            # `B1223`, second pass (54 → 0): one of the handlers whose database
            # work moved to `asyncio.to_thread` rather than to a plain `def`.
            "calendar_event": lambda: client.post("/api/calendar/events", json={
                "summary": "Probe", "dtstart": "2026-11-02T10:00:00"}),
        }
        res = {}
        def write(name, fn):
            t0 = time.perf_counter(); r = fn()
            res[name] = {"status": r.status_code, "ms": (time.perf_counter() - t0) * 1000}
        holder = threading.Thread(target=hold); holder.start(); held.wait()
        t_lock = time.perf_counter()
        workers = [threading.Thread(target=write, args=kv) for kv in writes.items()]
        for w in workers: w.start()
        time.sleep(0.05)
        side = []
        while time.perf_counter() - t_lock < HOLD - 0.2:
            t0 = time.perf_counter(); client.get("/api/auth/status")
            side.append((time.perf_counter() - t0) * 1000); time.sleep(0.1)
        for w in workers: w.join()
        holder.join()
        out["writes"] = res; out["side_ms"] = side
        out["saved"] = client.get(f"/api/document/{doc['id']}").json().get("current_content")
        out["renamed"] = client.get(f"/api/tasks/{task_id}").json().get("name")
        out["events"] = [e["summary"] for e in client.get(
            "/api/calendar/events", params={"start": "2026-11-01", "end": "2026-11-03"}).json()["events"]]
    print("RESULT " + json.dumps(out))
    """
)


@pytest.fixture(scope="module")
def under_a_held_lock(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("held_lock_off_the_loop")
    db = tmp / "app.db"
    env = os.environ.copy()
    env.update({
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{db}",
        "PANTHEON_DATA_DIR": str(tmp),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(_REPO),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    env.pop("PANTHEON_SQLITE_JOURNAL_MODE", None)
    probe = _PROBE.replace("__DB__", repr(str(db))).replace("__HOLD__", repr(HOLD_S))
    done = subprocess.run([sys.executable, "-c", probe], cwd=_REPO, env=env,
                          capture_output=True, text=True, timeout=240)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"probe printed no result:\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
    return json.loads(line[len("RESULT "):])


@pytest.mark.parametrize("write", ["document_save", "task_edit", "mail_account", "calendar_event"])
def test_a_write_waits_its_turn_and_lands_instead_of_a_503(under_a_held_lock, write):
    got = under_a_held_lock["writes"][write]
    assert got["status"] == 200, got
    # It waited for the lock to go (off the loop, the patient wait), not half
    # a second and a refusal.
    assert got["ms"] > 1000, got


def test_what_was_written_is_there(under_a_held_lock):
    assert under_a_held_lock["saved"] == "two"
    assert under_a_held_lock["renamed"] == "Probe, renamed"
    assert under_a_held_lock["events"] == ["Probe"]


def test_nobody_else_waits_while_they_do(under_a_held_lock):
    side = under_a_held_lock["side_ms"]
    assert len(side) >= 5, side
    assert sorted(side)[len(side) // 2] < 100, side
    assert max(side) < 400, f"a request that touches no database waited behind a write: {side}"
