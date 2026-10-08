# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1231`: a data directory that cannot hold SQLite's write-ahead log.

`P23-07` turned WAL on by default. WAL keeps its index in a memory-mapped
`-shm` file, and a filesystem that cannot share the mapping cannot run it —
Docker Desktop on Windows and macOS bind-mounts `./data` from a host share.
`PRAGMA journal_mode=wal` does not find that out: it answers `wal`, and the
shared memory is first opened by the next statement.

The failure is forced for real wherever it can be: a directory standing where
`app.db-shm` belongs gives SQLite a `-shm` it can open read-only and never
write (measured before the fix: the pragma answered `wal`, reads worked, every
write failed "attempt to write a readonly database"), and SQLite's own
`unix-dotfile` VFS has no shared memory at all, so it answers the pragma with
the mode it kept. The host share's own signature — "disk I/O error" from the
index — is simulated by a connection class, and said to be.

Every case runs real engines on real files (the listeners are on the `Engine`
class), and the last two boot the real app twice on such a directory.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest
import sqlalchemy as sa

import core.database as database

_REPO = Path(__file__).resolve().parents[1]
_ENV = "PANTHEON_SQLITE_JOURNAL_MODE"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    monkeypatch.setattr(database, "_WAL_REFUSAL_REPORTED", False)


def _engine(path: Path):
    return sa.create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def _header_says_wal(path: Path) -> bool:
    """Bytes 18 and 19 of the file are 2 in WAL and 1 in a rollback journal."""
    head = path.read_bytes()[:20]
    return head[18] == 2 and head[19] == 2


def _seed(path: Path, *, wal: bool = False) -> None:
    conn = sqlite3.connect(str(path))
    if wal:
        assert conn.execute("PRAGMA journal_mode=wal").fetchone()[0] == "wal"
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    conn.execute("INSERT INTO notes (body) VALUES ('kept')")
    conn.commit()
    conn.close()
    for side in ("-wal", "-shm"):
        Path(f"{path}{side}").unlink(missing_ok=True)


def _break_the_shared_memory(path: Path) -> None:
    Path(f"{path}-shm").mkdir()


def _write_and_read(eng) -> list:
    with eng.begin() as c:
        c.exec_driver_sql("INSERT INTO notes (body) VALUES ('written')")
    with eng.connect() as c:
        return [r[0] for r in c.exec_driver_sql("SELECT body FROM notes ORDER BY id")]


def _refusals(caplog) -> list:
    return [r.getMessage() for r in caplog.records
            if r.name == "core.database" and "write-ahead log" in r.getMessage()]


def test_shared_memory_that_cannot_be_written_falls_back_to_the_rollback_journal(tmp_path, caplog):
    db = tmp_path / "app.db"
    _seed(db)
    _break_the_shared_memory(db)
    eng = _engine(db)
    with caplog.at_level(logging.WARNING, logger="core.database"):
        with eng.connect() as c:
            mode = c.exec_driver_sql("PRAGMA journal_mode").scalar()
        rows = _write_and_read(eng)
    eng.dispose()
    assert mode == "delete"
    assert rows == ["kept", "written"]
    assert not _header_says_wal(db)
    [line] = _refusals(caplog)
    assert f"{_ENV}=delete" in line, line
    assert "readonly" in line, "the warning says what SQLite said"


def test_a_database_already_in_wal_on_such_a_directory_is_brought_back(tmp_path, caplog):
    # The upgrade case: an install that ran WAL, then found its data directory
    # on a share (or a `-shm` it can no longer write).
    db = tmp_path / "app.db"
    _seed(db, wal=True)
    assert _header_says_wal(db)
    _break_the_shared_memory(db)
    eng = _engine(db)
    with caplog.at_level(logging.WARNING, logger="core.database"):
        rows = _write_and_read(eng)
        with eng.connect() as c:
            mode = c.exec_driver_sql("PRAGMA journal_mode").scalar()
    eng.dispose()
    assert rows == ["kept", "written"]
    assert mode == "delete"
    assert not _header_says_wal(db), "left in WAL, the next process fails the same way"
    assert len(_refusals(caplog)) == 1


def test_sqlite_answering_a_mode_other_than_wal_is_believed(tmp_path, monkeypatch, caplog):
    # SQLite's `unix-dotfile` VFS has no shared memory: it answers the switch
    # with the mode it kept, as a filesystem without the mapping would.
    def no_shared_memory(path):
        return sqlite3.connect(f"file:{path}?vfs=unix-dotfile", uri=True, timeout=0.25,
                               isolation_level=None, check_same_thread=False)

    monkeypatch.setattr(database, "_open_for_journal_check", no_shared_memory)
    db = tmp_path / "app.db"
    _seed(db)
    eng = _engine(db)
    with caplog.at_level(logging.WARNING, logger="core.database"):
        with eng.connect() as c:
            mode = c.exec_driver_sql("PRAGMA journal_mode").scalar()
        rows = _write_and_read(eng)
    eng.dispose()
    assert mode == "delete"
    assert rows == ["kept", "written"]
    [line] = _refusals(caplog)
    assert "answered journal_mode=delete" in line and _ENV in line, line


class _HostShare(sqlite3.Connection):
    """SIMULATED: the index fails to map, as a host share answers it."""

    def execute(self, sql, *args):
        if sql.strip().upper().startswith("BEGIN IMMEDIATE"):
            raise sqlite3.OperationalError("disk I/O error")
        return super().execute(sql, *args)


def test_a_disk_io_error_from_the_index_falls_back(tmp_path, monkeypatch, caplog):
    def host_share(path):
        return sqlite3.connect(path, timeout=0.25, isolation_level=None,
                               check_same_thread=False, factory=_HostShare)

    monkeypatch.setattr(database, "_open_for_journal_check", host_share)
    db = tmp_path / "app.db"
    _seed(db)
    eng = _engine(db)
    with caplog.at_level(logging.WARNING, logger="core.database"):
        rows = _write_and_read(eng)
        with eng.connect() as c:
            mode = c.exec_driver_sql("PRAGMA journal_mode").scalar()
    eng.dispose()
    assert mode == "delete" and rows == ["kept", "written"]
    assert not _header_says_wal(db), "the probe switched it; the fallback switched it back"
    [line] = _refusals(caplog)
    assert "disk I/O error" in line and f"{_ENV}=delete" in line


def test_it_is_said_once_and_asked_once_per_file(tmp_path, monkeypatch, caplog):
    asked = []
    real = database._open_for_journal_check

    def counting(path):
        asked.append(path)
        return real(path)

    monkeypatch.setattr(database, "_open_for_journal_check", counting)
    dbs = []
    for name in ("a.db", "b.db"):
        db = tmp_path / name
        _seed(db)
        _break_the_shared_memory(db)
        dbs.append(db)
    with caplog.at_level(logging.WARNING, logger="core.database"):
        for db in dbs:
            eng = _engine(db)
            for _ in range(3):
                with eng.connect() as c:
                    c.exec_driver_sql("SELECT 1")
                eng.dispose()  # a new pooled connection each time
    assert len(_refusals(caplog)) == 1
    # Per file: one probe and one connection to leave WAL, never again.
    assert sorted(asked) == sorted([str(d) for d in dbs for _ in range(2)])


def test_a_directory_that_can_hold_one_is_written_ahead_and_asked_once(tmp_path, monkeypatch, caplog):
    asked = []
    real = database._open_for_journal_check
    monkeypatch.setattr(database, "_open_for_journal_check",
                        lambda path: (asked.append(path), real(path))[1])
    db = tmp_path / "app.db"
    _seed(db)
    eng = _engine(db)
    with caplog.at_level(logging.WARNING, logger="core.database"):
        for _ in range(3):
            with eng.connect() as c:
                assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
                assert c.exec_driver_sql("PRAGMA synchronous").scalar() == 1
            eng.dispose()
        assert _write_and_read(eng) == ["kept", "written"]
    eng.dispose()
    assert asked == [str(db)]
    assert _refusals(caplog) == []


def test_a_file_busy_at_the_first_connection_is_asked_again_by_the_next(tmp_path):
    db = tmp_path / "app.db"
    _seed(db)
    holder = sqlite3.connect(str(db), timeout=1, check_same_thread=False)
    holder.execute("BEGIN EXCLUSIVE")
    release = threading.Timer(1.0, lambda: (holder.rollback(), holder.close()))
    release.start()
    eng = _engine(db)
    with eng.connect() as c:   # the probe met the lock; this connection waited it out
        first = c.exec_driver_sql("PRAGMA journal_mode").scalar()
    release.join()
    assert first == "delete"
    assert str(db) not in database._JOURNAL_SETTLED, "a busy file was taken as an answer"
    eng.dispose()
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    eng.dispose()
    assert database._JOURNAL_SETTLED[str(db)] == "wal"


def test_the_operator_choosing_a_mode_is_not_second_guessed(tmp_path, monkeypatch):
    monkeypatch.setenv(_ENV, "delete")
    monkeypatch.setattr(database, "_open_for_journal_check",
                        lambda path: pytest.fail("probed although the operator chose"))
    db = tmp_path / "app.db"
    _seed(db)
    eng = _engine(db)
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "delete"
    eng.dispose()


# ── The row's `Verify:` on the real app: it boots, writes, and survives a restart ──

_BOOT = textwrap.dedent(
    """
    import json, sqlite3
    import app as app_module
    from tests.helpers.signed_in import sign_in
    from fastapi.testclient import TestClient
    DB = __DB__
    out = {}
    with TestClient(app_module.app) as client:
        sign_in(app_module, client)  # the install's admin: there is always authentication (`D-2026-10-07-02` §2)
        out["journal_mode"] = sqlite3.connect(DB).execute("PRAGMA journal_mode").fetchone()[0]
        if __WRITE__:
            r = client.post("/api/email/accounts", json={
                "name": "kept-across-restart", "imap_host": "x", "imap_user": "x",
                "imap_password": "x", "smtp_host": "x"})
            out["write"] = r.status_code
        r = client.get("/api/email/accounts")
        out["names"] = [a.get("name") for a in (r.json().get("accounts") or [])]
    print("RESULT " + json.dumps(out))
    """
)


@pytest.fixture(scope="module")
def two_boots_on_a_share(tmp_path_factory) -> list:
    tmp = tmp_path_factory.mktemp("share")
    db = tmp / "app.db"
    Path(f"{db}-shm").mkdir()      # the forced failure, before the first boot
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
    env.pop(_ENV, None)
    boots = []
    for write in (True, False):
        script = _BOOT.replace("__DB__", repr(str(db))).replace("__WRITE__", repr(write))
        done = subprocess.run([sys.executable, "-c", script], cwd=_REPO, env=env,
                              capture_output=True, text=True, timeout=240)
        line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
        assert line, f"boot printed no result:\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
        boots.append({**json.loads(line[len("RESULT "):]), "log": done.stdout + done.stderr})
    return boots


def test_the_app_boots_and_writes_on_a_directory_without_wal(two_boots_on_a_share):
    first = two_boots_on_a_share[0]
    assert first["journal_mode"] == "delete"
    assert first["write"] == 200
    assert "kept-across-restart" in first["names"]
    assert f"{_ENV}=delete" in first["log"], "the log names the way to stop asking"


def test_what_it_wrote_survives_a_restart(two_boots_on_a_share):
    second = two_boots_on_a_share[1]
    assert second["journal_mode"] == "delete"
    assert "kept-across-restart" in second["names"]
