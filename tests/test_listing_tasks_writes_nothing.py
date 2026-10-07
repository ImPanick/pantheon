# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-18`): listing tasks is a read; the built-ins are seeded by
the scheduler.

Measured by the perf audit on `9560d50`: the first `GET /api/tasks` after the
showcase made its account inserted 10 built-in tasks and a crew member
(320 ms), and every later list re-ran the reconcile and committed — a read that
writes, and so a read that can wait on the database lock (`PERF-M-2`). On a
fresh install that is every first open: the admin is created after boot, so
startup's seeding had nobody to seed.

Now the scheduler's loop seeds anyone in `auth.json` it has not seeded
(`TaskScheduler._seed_defaults_for_new_owners`, re-reading the file only when it
changes) and the list only reads. Driven: the real app (a fresh install, its
first admin, `GET /api/tasks`, then one scheduler pass) and the real scheduler.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_PROBE = textwrap.dedent(
    """
    import json, sqlite3
    import app as app_module
    from fastapi.testclient import TestClient
    DB = __DB__
    def rows():
        return sqlite3.connect(DB).execute("SELECT COUNT(*) FROM scheduled_tasks").fetchone()[0]
    out = {}
    with TestClient(app_module.app) as client:
        creds = {"username": "first", "password": "first-pass-123"}
        out["setup"] = client.post("/api/auth/setup", json=creds).status_code
        client.post("/api/auth/login", json={**creds, "remember": True})
        before = rows()
        r = client.get("/api/tasks")
        out["list"] = [r.status_code, len(r.json().get("tasks") or []), rows() - before]
        out["seeded"] = client.portal.call(app_module.task_scheduler._seed_defaults_for_new_owners)
        r = client.get("/api/tasks")
        out["after"] = len(r.json().get("tasks") or [])
        out["again"] = client.portal.call(app_module.task_scheduler._seed_defaults_for_new_owners)
    print("RESULT " + json.dumps(out))
    """
)


def test_a_fresh_installs_first_list_writes_nothing_and_the_scheduler_seeds(tmp_path):
    db = tmp_path / "app.db"
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": "true", "CHROMADB_CONNECT_TIMEOUT": "0.01", "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9", "DATABASE_URL": f"sqlite:///{db}", "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1", "PYTHONPATH": str(_REPO), "PYTHON_DOTENV_DISABLED": "1",
        "LOCALHOST_BYPASS": "false",
    })
    done = subprocess.run([sys.executable, "-c", _PROBE.replace("__DB__", repr(str(db)))], cwd=_REPO,
                          env=env, capture_output=True, text=True, timeout=240)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, done.stderr[-4000:]
    out = json.loads(line[len("RESULT "):])
    assert out["setup"] == 200
    status, listed, written = out["list"]
    assert status == 200 and listed == 0 and written == 0, out
    assert out["seeded"] == ["first"]
    assert out["after"] >= 5, out
    assert out["again"] == []


def test_the_scheduler_seeds_each_new_person_once(monkeypatch, tmp_path):
    import src.constants as constants
    from src.task_scheduler import TaskScheduler

    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"users": {"alice": {}}}), encoding="utf-8")
    monkeypatch.setattr(constants, "AUTH_FILE", str(auth))
    s = TaskScheduler(None)
    seeded = []

    async def ensure(owner):
        seeded.append(owner)

    monkeypatch.setattr(s, "ensure_defaults", ensure)

    async def passes():
        first = await s._seed_defaults_for_new_owners()
        second = await s._seed_defaults_for_new_owners()
        time.sleep(0.01)
        auth.write_text(json.dumps({"users": {"alice": {}, "bob": {}}}), encoding="utf-8")
        os.utime(auth, ns=(time.time_ns(), time.time_ns()))
        third = await s._seed_defaults_for_new_owners()
        return first, second, third

    assert asyncio.run(passes()) == (["alice"], [], ["bob"])
    assert seeded == ["alice", "bob"]


def test_someone_seeded_at_startup_is_not_seeded_again(monkeypatch, tmp_path):
    import src.constants as constants
    from src.task_scheduler import TaskScheduler

    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"users": {"alice": {}}}), encoding="utf-8")
    monkeypatch.setattr(constants, "AUTH_FILE", str(auth))
    s = TaskScheduler(None)
    calls = []

    async def fake_assistant(owner):
        calls.append(owner)

    # The real `ensure_defaults` — what startup calls — records who it saw.
    monkeypatch.setattr(s, "ensure_assistant_defaults", fake_assistant)
    asyncio.run(s.ensure_defaults("alice"))
    assert asyncio.run(s._seed_defaults_for_new_owners()) == []


def test_the_loop_seeds_before_it_looks_for_due_work(monkeypatch):
    """One turn of the scheduler's own loop: a new person's built-ins are
    seeded there, and before the due work is looked for."""
    from src.task_scheduler import TaskScheduler

    s = TaskScheduler(None)
    order = []

    async def seed():
        order.append("seed")
        return []

    async def check():
        order.append("check")
        s._running = False

    real_sleep = asyncio.sleep

    async def no_wait(_seconds, *a, **k):
        await real_sleep(0)

    monkeypatch.setattr(s, "_seed_defaults_for_new_owners", seed)
    monkeypatch.setattr(s, "_check_due_tasks", check)
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    s._running = True
    asyncio.run(s._loop())
    assert order == ["seed", "check"]
