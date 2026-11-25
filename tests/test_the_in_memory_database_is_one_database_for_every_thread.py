# SPDX-License-Identifier: AGPL-3.0-or-later
"""The suite's database is one database, whichever thread asks and however many.

`B1410`/`B1491`. `tests/conftest.py` runs the in-process suite on
`DATABASE_URL=sqlite:///:memory:`, and an in-memory SQLite database belongs to
the one connection that opened it. SQLAlchemy's default pool for that URL was
`SingletonThreadPool` — a connection per thread, at most five kept — so:

  * a TestClient's worker thread opened its own, empty database;
  * past five threads the pool closed a connection picked by `set.pop()`, and
    when it picked the one `init_db()` built the schema on, every later file
    met `no such table: mcp_servers`. Which one it picked follows object
    addresses, so the answer depended on the file set — the row's 33 errors
    after 177 particular files and none after 180 others;
  * the close runs on whichever thread connected last, against a connection
    another thread may be inside: concurrent connects segfaulted the process.

Measured on `9cb99344`: six worker threads, and main had 0 of its 40 tables;
`test_the_turns_suite_is_counted_after_every_clamp.py` then errored 34 times
with the row's exact trace. These cases drive `core.database.engine` itself —
the object every file shares — rather than a copy built here.
"""
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parent.parent


def _tables_on(engine):
    with engine.connect() as conn:
        return set(inspect(conn).get_table_names())


def _from_a_worker(engine):
    seen = {}

    def ask():
        seen["tables"] = _tables_on(engine)

    worker = threading.Thread(target=ask)
    worker.start()
    worker.join()
    return seen["tables"]


def test_a_worker_thread_sees_the_tables_the_session_built():
    """A TestClient's worker thread is where a route runs. Red on `9cb99344`:
    the worker saw 0 tables while the main thread saw 40."""
    import core.database as cdb

    here = _tables_on(cdb.engine)
    assert "mcp_servers" in here, "init_db() built the schema on this engine"
    assert _from_a_worker(cdb.engine) == here, (
        "a worker thread opened a different database than the one init_db() built")


def test_the_session_keeps_its_schema_however_many_threads_have_asked():
    """Past five threads the old pool closed connections at random; this is
    the shape that made the row's file set lose `mcp_servers`."""
    import core.database as cdb

    before = _tables_on(cdb.engine)
    for n in range(1, 41):
        _from_a_worker(cdb.engine)
        assert _tables_on(cdb.engine) == before, (
            f"after {n} worker threads the main thread's database lost its tables")


def test_threads_connecting_at_once_do_not_crash_the_process():
    """In a child, so a segfault is a failed case rather than a dead session.

    Only the crash is asked about here — what the workers see is the first
    case's. On `9cb99344` this child died with SIGSEGV (exit -11) in nine
    runs of ten: `SingletonThreadPool._cleanup` closing a connection mid-query."""
    script = textwrap.dedent("""
        from concurrent.futures import ThreadPoolExecutor
        import core.database as d
        from sqlalchemy import inspect

        def ask(_):
            with d.engine.connect() as c:
                return inspect(c).get_table_names()

        for _ in range(20):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(ask, range(16)))
        print("ok")
    """)
    env = dict(os.environ, DATABASE_URL="sqlite:///:memory:")
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    done = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "ok" in done.stdout, (
        f"exit {done.returncode}: {done.stderr[-2000:]}")


def test_only_a_database_in_memory_shares_one_connection():
    """A file, and anything that is not SQLite, keeps the pool it had."""
    from sqlalchemy.pool import StaticPool
    import core.database as cdb

    for url in ("sqlite:///:memory:", "sqlite://",
                "sqlite:///file:scratch?mode=memory&uri=true"):
        assert cdb._pool_for(url) == {"poolclass": StaticPool}, url
    for url in ("sqlite:////var/lib/pantheon/app.db",
                "postgresql://u:p@db.local/pantheon"):
        assert cdb._pool_for(url) == {}, url


# ── `B2195`: a connection per thread, onto one named database ────────────────
#
# One shared connection was still one connection: on Python 3.13 and 3.14 the
# crash case above died with `IndexError: tuple index out of range` inside
# SQLAlchemy's row, eight threads interleaving on its cursor (3.11 passed). An
# in-memory database nobody named is now SQLite's `memdb` one under a name of
# the process's own, which every connection opening that name shares.


def test_a_private_in_memory_url_becomes_one_named_memdb_database():
    import core.database as cdb

    for url in ("sqlite:///:memory:", "sqlite://", "sqlite:///file::memory:?uri=true"):
        target, pool = cdb._engine_target(url, sqlite_version=(3, 45, 1))
        assert target.startswith("sqlite:///file:/pantheon-memory-"), target
        assert target.endswith("?vfs=memdb&uri=true") and pool == {}, (target, pool)
        assert cdb._sqlite_db_path(cdb.make_url(target)) is None, (
            "a memdb database is not a file, so nothing may chmod or journal it")
        assert cdb._in_memory_sqlite(target), "a child process cannot share it either"


def test_older_sqlite_and_named_or_file_urls_keep_what_they_had():
    from sqlalchemy.pool import StaticPool
    import core.database as cdb

    assert cdb._engine_target("sqlite:///:memory:", sqlite_version=(3, 35, 5)) == (
        "sqlite:///:memory:", {"poolclass": StaticPool})
    named = "sqlite:///file:scratch?mode=memory&uri=true"
    assert cdb._engine_target(named, sqlite_version=(3, 45, 1)) == (
        named, {"poolclass": StaticPool})
    for url in ("sqlite:////var/lib/pantheon/app.db", "postgresql://u:p@db.local/pantheon"):
        assert cdb._engine_target(url, sqlite_version=(3, 45, 1)) == (url, {}), url


def test_the_suites_engine_gives_each_thread_its_own_connection():
    import sqlite3
    import core.database as cdb

    if sqlite3.sqlite_version_info < cdb._MEMDB_SINCE:  # pragma: no cover
        return
    assert "vfs=memdb" in str(cdb.engine.url), cdb.engine.url
    assert cdb._MEMORY_ANCHOR is not None, "nothing keeps the database alive"
    seen = {}

    def ask():
        with cdb.engine.connect() as conn:
            seen["worker"] = id(conn.connection.dbapi_connection)

    with cdb.engine.connect() as conn:
        mine = id(conn.connection.dbapi_connection)
        worker = threading.Thread(target=ask)
        worker.start()
        worker.join()
    assert seen["worker"] != mine


def test_threads_writing_at_once_all_land_in_one_database():
    """Readers were the reported crash; writers share the same connection, and
    on the named database they queue on SQLite's lock instead."""
    script = textwrap.dedent("""
        from concurrent.futures import ThreadPoolExecutor
        import core.database as d
        from sqlalchemy import text

        with d.engine.begin() as c:
            c.execute(text("CREATE TABLE b2195 (n INTEGER)"))

        def write(n):
            with d.engine.begin() as c:
                c.execute(text("INSERT INTO b2195 (n) VALUES (:n)"), {"n": n})

        for _ in range(10):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(write, range(16)))
        with d.engine.connect() as c:
            print("rows", c.execute(text("SELECT COUNT(*) FROM b2195")).scalar())
    """)
    env = dict(os.environ, DATABASE_URL="sqlite:///:memory:")
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    done = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "rows 160" in done.stdout, (
        f"exit {done.returncode}: {done.stdout[-500:]} {done.stderr[-2000:]}")
