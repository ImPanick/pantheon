# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-2`): a held SQLite lock no longer freezes the server.

Measured on `32df791` against the seeded showcase install: with a second
connection holding a write lock for 6 s, `POST /api/email/accounts` (an
`async def` handler) answered a bare **500 after 5,074 ms**, and
`GET /api/auth/status` — no database at all — took **4,773 ms**, because the
event loop sat inside SQLite's 5 s busy wait. After: WAL, a half-second wait on
the loop and a 503 with a sentence (824 ms on the same probe, side requests
≤ 522 ms).

Every case drives the code: real engines on real files (the listeners are on
the `Engine` and `Pool` classes, so any engine gets them), the real app in a
subprocess, the real backup script.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

import core.database as database
from tests.helpers.cli_loader import load_script

_REPO = Path(__file__).resolve().parents[1]


def _engine(path: Path):
    return sa.create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def _seeded(tmp_path: Path) -> Path:
    db = tmp_path / "app.db"
    eng = _engine(db)
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
        c.exec_driver_sql("INSERT INTO notes (body) VALUES ('committed')")
    eng.dispose()
    return db


class _HeldLock:
    """A second connection holding the write lock — `BEGIN EXCLUSIVE` plus an
    uncommitted write, the strongest lock a writer takes."""

    def __init__(self, db: Path):
        self.conn = sqlite3.connect(str(db), timeout=1, check_same_thread=False)

    def __enter__(self):
        self.conn.execute("BEGIN EXCLUSIVE")
        self.conn.execute("UPDATE notes SET body = 'uncommitted'")
        return self

    def __exit__(self, *exc):
        self.conn.rollback()
        self.conn.close()
        return False


def test_a_file_database_is_written_ahead(tmp_path):
    eng = _engine(_seeded(tmp_path))
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        # NORMAL (1) is WAL's safe setting; FULL (2) is the rollback default.
        assert c.exec_driver_sql("PRAGMA synchronous").scalar() == 1
    eng.dispose()


def test_a_reader_reads_the_last_commit_while_a_writer_holds_the_lock(tmp_path):
    db = _seeded(tmp_path)
    eng = _engine(db)
    with _HeldLock(db):
        start = time.monotonic()
        with eng.connect() as c:
            body = c.exec_driver_sql("SELECT body FROM notes").scalar()
        elapsed = time.monotonic() - start
    eng.dispose()
    assert body == "committed"
    assert elapsed < 0.4, f"a reader waited {elapsed:.2f}s on a writer"


def _busy_timeout(eng) -> int:
    with eng.connect() as c:
        return int(c.exec_driver_sql("PRAGMA busy_timeout").scalar())


def test_the_wait_is_short_on_the_event_loop_and_unchanged_off_it(tmp_path):
    eng = _engine(_seeded(tmp_path))
    off_loop = {}
    t = threading.Thread(target=lambda: off_loop.setdefault("ms", _busy_timeout(eng)))
    t.start(); t.join()

    async def on_loop():
        here = _busy_timeout(eng)
        with database.patient_database_waits():
            patient = _busy_timeout(eng)
        return here, patient

    here, patient = asyncio.run(on_loop())
    eng.dispose()
    assert off_loop["ms"] == database.DEFAULT_BUSY_WAIT_MS == 5000
    assert here == database.EVENT_LOOP_BUSY_WAIT_MS == 500
    assert patient == 5000, "startup on the loop (`uvicorn app:app`) keeps the patient wait"


def test_on_the_event_loop_a_held_lock_is_refused_in_half_a_second(tmp_path):
    db = _seeded(tmp_path)
    eng = _engine(db)

    async def write():
        start = time.monotonic()
        try:
            with eng.begin() as c:
                c.exec_driver_sql("INSERT INTO notes (body) VALUES ('mine')")
        except sa.exc.OperationalError as exc:
            return time.monotonic() - start, exc
        return time.monotonic() - start, None

    with _HeldLock(db):
        elapsed, exc = asyncio.run(write())
    eng.dispose()
    assert exc is not None and database.is_database_locked(exc)
    assert 0.3 < elapsed < 1.5, f"the loop waited {elapsed:.2f}s"


def test_the_journal_mode_is_the_operators_to_choose(tmp_path, monkeypatch):
    monkeypatch.setenv("PANTHEON_SQLITE_JOURNAL_MODE", "delete")
    eng = _engine(tmp_path / "share.db")
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "delete"
    eng.dispose()
    # A word SQLite would lose the database with is not offered.
    monkeypatch.setenv("PANTHEON_SQLITE_JOURNAL_MODE", "off")
    assert database.chosen_journal_mode() == "wal"


def test_only_a_lock_refusal_becomes_a_503():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    database.install_database_busy_answer(app)

    @app.get("/locked")
    async def locked():
        raise sa.exc.OperationalError("INSERT", {}, sqlite3.OperationalError("database is locked"))

    @app.get("/other")
    async def other():
        raise sa.exc.OperationalError("SELECT", {}, sqlite3.OperationalError("no such table: x"))

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/locked")
    assert r.status_code == 503
    assert r.json() == {"detail": database.DATABASE_BUSY_DETAIL}
    assert r.headers["retry-after"] == "1"
    assert client.get("/other").status_code == 500


_PROBE = textwrap.dedent(
    """
    import json, sqlite3, threading, time
    import app as app_module
    from tests.helpers.signed_in import sign_in
    from fastapi.testclient import TestClient
    DB = __DB__
    ACCOUNT = {"name": "probe", "imap_host": "x", "imap_user": "x", "imap_password": "x", "smtp_host": "x"}
    out = {}
    with TestClient(app_module.app) as client:
        sign_in(app_module, client)  # the install's admin: there is always authentication (`D-2026-10-07-02` §2)
        out["journal_mode"] = sqlite3.connect(DB).execute("PRAGMA journal_mode").fetchone()[0]
        held = threading.Event()
        def hold():
            c = sqlite3.connect(DB, timeout=1)
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE notes SET updated_at = updated_at WHERE 0")
            held.set(); time.sleep(3); c.rollback(); c.close()
        holder = threading.Thread(target=hold); holder.start(); held.wait()
        res = {}
        def write():
            t0 = time.perf_counter()
            r = client.post("/api/email/accounts", json=ACCOUNT)
            res.update(status=r.status_code, body=r.json(), ms=(time.perf_counter() - t0) * 1000)
        writer = threading.Thread(target=write); writer.start(); time.sleep(0.05)
        side = []
        for _ in range(6):
            t0 = time.perf_counter(); client.get("/api/auth/status")
            side.append((time.perf_counter() - t0) * 1000); time.sleep(0.1)
        writer.join(); holder.join()
        out["write"] = res; out["side_ms"] = side
        r = client.post("/api/email/accounts", json=ACCOUNT)
        out["after"] = r.status_code
    print("RESULT " + json.dumps(out))
    """
)


@pytest.fixture(scope="module")
def held_lock_on_the_real_app(tmp_path_factory) -> dict:
    """The row's `Verify:` on the real app: a write through an `async def`
    handler while another connection holds the lock, and a request that
    touches no database timed beside it. Out of process because importing
    `app` brings the whole application up (`test_offline_shell_manifest.py`'s
    shape)."""
    tmp = tmp_path_factory.mktemp("held_lock")
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
    probe = _PROBE.replace("__DB__", repr(str(db)))
    done = subprocess.run([sys.executable, "-c", probe], cwd=_REPO, env=env,
                          capture_output=True, text=True, timeout=240)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"probe printed no result:\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
    return json.loads(line[len("RESULT "):])


def test_the_app_database_is_written_ahead(held_lock_on_the_real_app):
    assert held_lock_on_the_real_app["journal_mode"] == "wal"


def test_a_write_under_a_held_lock_is_a_503_with_a_sentence_in_under_a_second(held_lock_on_the_real_app):
    write = held_lock_on_the_real_app["write"]
    assert write["status"] == 503, write
    assert write["body"] == {"detail": database.DATABASE_BUSY_DETAIL}
    assert write["ms"] < 1000, f"refused after {write['ms']:.0f} ms"


def test_other_requests_answer_while_the_lock_is_held(held_lock_on_the_real_app):
    side = held_lock_on_the_real_app["side_ms"]
    # One side request may land inside the half-second wait; none waits 5 s.
    assert max(side) < 1000, side
    assert sorted(side)[len(side) // 2] < 100, side


def test_the_same_write_succeeds_once_the_lock_is_gone(held_lock_on_the_real_app):
    assert held_lock_on_the_real_app["after"] == 200


def test_a_snapshot_leaves_out_the_live_sidecars_of_a_database_it_copied(tmp_path, monkeypatch):
    backup = load_script("pantheon-backup")
    root = tmp_path / "repo"
    data = root / "data"
    data.mkdir(parents=True)
    monkeypatch.setattr(backup, "_REPO_ROOT", root)
    monkeypatch.setattr(backup, "_DATA_DIR", data)
    monkeypatch.setattr(backup, "_BACKUP_DIR", root / "backups")
    db = data / "app.db"
    live = sqlite3.connect(str(db))
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("CREATE TABLE notes (body TEXT)")
    live.execute("INSERT INTO notes VALUES ('in the wal')")
    live.commit()                     # committed, not checkpointed: it lives in app.db-wal
    assert (data / "app.db-wal").exists()
    (data / "notes.txt").write_text("kept")
    out = tmp_path / "snap.tar.gz"
    backup.cmd_snapshot(SimpleNamespace(out=str(out), include_research=False,
                                        include_attachments=False, pretty=False))
    live.close()
    with tarfile.open(out) as tar:
        names = set(tar.getnames())
        assert "data/app.db" in names and "data/notes.txt" in names
        assert not {"data/app.db-wal", "data/app.db-shm"} & names, names
        tar.extractall(tmp_path / "restored", filter="data")
    restored = sqlite3.connect(str(tmp_path / "restored" / "data" / "app.db"))
    assert restored.execute("SELECT body FROM notes").fetchone() == ("in the wal",)
    restored.close()
