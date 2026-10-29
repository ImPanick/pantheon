# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1645` — no evaluation world is left in the temp folder.

Measured on 2026-10-28: 459 `pantheon-eval-*` folders (~900 KB each) in
`/tmp`. Read by birth time and by the hire in each world's own database, 457
came in batches of 23 (46 when two suites ran at once), each batch exactly the
worlds `tests/test_an_agent_is_measured.py` made before `P24-27` (`0b47b4d4`)
made a world remove itself — the five starred agents' four cases each, the two
of `test_a_model_that_says_done_and_did_nothing_fails` and one empty world —
the last born 2026-10-27 17:12. Since then two more: a Topic Watcher world
whose run was still `queued` and a Spec Writer world whose run had finished,
each the one world of a process stopped mid-case (`timeout`'s SIGTERM, the
OOM killer, a machine restart) — which runs no `finally`, so `isolated()`
never removed it. And one way in-process: everything `isolated()` did after
making the folder and before its `try` — the database, the swaps, the world's
memory manager — left the folder behind when it raised, and, past the swaps,
the install's session and data folder swapped for the world's.

Now a world's setup is inside the `try`, a world names the process that made
it, a later process's first world removes the worlds of processes that are
gone, and the suite fails a test whose world outlives it
(`conftest._no_eval_world_outlives_its_test`).

Driven (`Law 20`): the real `isolated()`; a real process that makes a world
and is killed; a real pytest session over a test that leaves one.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.agents import evals as E

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def temp(tmp_path, monkeypatch):
    """A temp folder of the test's own, as `tempfile` reads it, swept afresh."""
    import tempfile
    folder = tmp_path / "tmp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    monkeypatch.setattr(E, "_SWEPT", set(), raising=False)
    return folder


def _worlds(folder: Path):
    return sorted(p.name for p in folder.iterdir() if p.name.startswith("pantheon-eval-"))


def _env(folder: Path) -> dict:
    return dict(os.environ, TMPDIR=str(folder), DATABASE_URL="sqlite:///:memory:", PYTHONPATH=str(ROOT))


def test_a_world_whose_setup_breaks_is_removed_and_the_install_put_back(temp, monkeypatch):
    import core.database as cdb
    import src.constants as constants
    import src.memory as memory

    class Full:
        def __init__(self, *a, **k):
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(memory, "MemoryManager", Full)
    before = (cdb.SessionLocal, constants.DATA_DIR, os.environ.get("BACKGROUND_TASK_FOREGROUND_GATE"))
    with pytest.raises(OSError, match="No space left"):
        with E.isolated():
            pass
    after = (cdb.SessionLocal, constants.DATA_DIR, os.environ.get("BACKGROUND_TASK_FOREGROUND_GATE"))
    assert after == before, "the install's session and data folder stayed the dead world's"
    assert _worlds(temp) == [], "the world whose setup broke stayed in the temp folder"


def test_a_world_left_by_a_killed_process_is_removed_by_the_next_process(temp):
    # A process makes a world and is killed in it, as `timeout` or the OOM
    # killer ends a suite: no `finally` runs.
    proc = subprocess.run(
        [sys.executable, "-c",
         "import os, signal\n"
         "from src.agents import evals as E\n"
         "with E.isolated() as (_f, data):\n"
         "    print(os.path.dirname(data), flush=True)\n"
         "    os.kill(os.getpid(), signal.SIGKILL)\n"],
        cwd=str(ROOT), env=_env(temp), capture_output=True, text=True, timeout=120)
    assert proc.returncode == -signal.SIGKILL, proc.stderr[-2000:]
    killed = Path(proc.stdout.strip())
    assert killed.parent == temp and killed.is_dir(), "control: a killed process leaves its world"

    host = socket.gethostname()
    keep = {
        # As the 459 were: no owner file, so not this harness's to judge.
        "pantheon-eval-unnamed": None,
        # A world whose process is still running (this test's own parent).
        "pantheon-eval-running": f"{os.getppid()} {host}",
        # A pid on another machine says nothing about this one.
        "pantheon-eval-elsewhere": f"{_a_pid_that_is_gone()} another-host",
    }
    for name, owner in keep.items():
        (temp / name / "data").mkdir(parents=True)
        if owner:
            (temp / name / E.WORLD_OWNER_FILE).write_text(owner, encoding="utf-8")

    with E.isolated() as (_factory, data):
        here = Path(data).parent
        assert not killed.exists(), "the killed process's world was not removed by the next one"
        assert sorted([*keep, here.name]) == _worlds(temp)
    assert _worlds(temp) == sorted(keep)


def test_a_world_still_open_when_its_process_exits_is_removed(temp):
    """A world nobody ended, held by a module, is closed only as the
    interpreter takes itself apart: putting the install back raised there
    (`logging` half gone) and its removal imported `shutil` (`sys.meta_path is
    None`), so the folder stayed — as it did in the probe session below."""
    proc = subprocess.run(
        [sys.executable, "-c",
         "import json, os\n"
         "from src.agents import evals as E\n"
         "world = E.isolated()\n"
         "_f, data = world.__enter__()\n"
         "json._held_world = world\n"
         "print(os.path.dirname(data), flush=True)\n"],
        cwd=str(ROOT), env=_env(temp), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert Path(proc.stdout.strip()).parent == temp
    assert _worlds(temp) == [], proc.stderr[-2000:]


def _a_pid_that_is_gone() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_the_suite_fails_a_test_whose_world_outlives_it(tmp_path):
    """A real pytest session, in its own process and temp folder: one test
    leaves its world open, one ends it."""
    temp = tmp_path / "tmp"
    temp.mkdir()
    probe = ROOT / "tests" / "_b1645_probe_test.py"
    probe.write_text(
        "from src.agents import evals as E\n"
        "_OPEN = []\n"
        "def test_leaves_its_world():\n"
        "    world = E.isolated()\n"
        "    world.__enter__()\n"
        "    _OPEN.append(world)\n"
        "def test_ends_its_world():\n"
        "    with E.isolated():\n"
        "        pass\n",
        encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             f"--basetemp={tmp_path / 'bt'}", str(probe)],
            cwd=str(ROOT), env=_env(temp), capture_output=True, text=True, timeout=300)
    finally:
        probe.unlink()
    out = proc.stdout
    assert proc.returncode != 0, out[-3000:]
    assert "ERROR at teardown of test_leaves_its_world" in out, out[-3000:]
    assert "B1645: this test left 1 evaluation world(s)" in out, out[-3000:]
    assert "2 passed" in out and "1 error" in out, out[-3000:]   # the test itself passed; its teardown did not
    assert _worlds(temp) == [], "the guard named the world and left it"
