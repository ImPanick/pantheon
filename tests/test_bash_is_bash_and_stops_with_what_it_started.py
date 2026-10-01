# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B961`, `B964` — the agent's `bash` on Pantheon's machine is bash, and stops whole.

Both rows were found by `P20-03`, comparing the workstation's shell with this
machine's, and both are about the same few lines of
`src/agent_tools/subprocess_tools.py`:

  * **`B961`**: the tool named `bash` ran `/bin/sh -c` — dash on the Debian
    image, so `[[ ]]` was "not found" and `{a,b}` was literal. It runs
    `bash -c` wherever there is a bash, as Windows already did, and where
    there is none it runs `sh` and the result says so.
  * **`B964`**: a timed-out (or cancelled) command killed the shell and left
    what the shell had started — a `sleep`, a build, a server — running and
    holding the pipes. The command now starts as the leader of its own process
    group, and the group is killed (the tree, on Windows).

Driven through the real dispatcher (`execute_tool_block`), and for `B964`
checked against the process table itself (`/proc`), so what is asserted is
what is still running (`Law 20`). Only harmless commands (`sleep`, `echo`).
"""
from __future__ import annotations

import asyncio
import os
import secrets
import time
from pathlib import Path

import pytest

import src.agent_tools.subprocess_tools as sp
import src.tool_execution as te
from src.agent_tools import ToolBlock
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, people, settings,
)


@pytest.fixture
def proj(tmp_path):
    d = Path(os.path.realpath(tmp_path)) / "proj"
    (d / "sub").mkdir(parents=True)
    return d


def here(tool, content, chat, workspace, owner="boss"):
    return _call(tool, content, owner, session_id=chat,
                 workspace=str(workspace) if workspace else None)[1]


# ── bash is bash (`B961`) ────────────────────────────────────────────────────


@pytest.mark.parametrize("chat", ["c1", None])
def test_bash_is_bash_here(settings, people, proj, chat):
    r = here("bash", "[[ 1 == 1 ]] && echo ok", chat, proj)
    assert (r["stdout"], r["exit_code"]) == ("ok", 0) and "note" not in r
    r = here("bash", 'echo {a,b}; arr=(x y); echo "${arr[1]}"; [ -n "$BASH_VERSION" ] && echo bash',
             chat, proj)
    assert r["stdout"].splitlines() == ["a b", "y", "bash"]


def test_where_there_is_no_bash_it_runs_in_sh_and_says_so(settings, people, proj, monkeypatch):
    monkeypatch.setattr(sp, "find_bash", lambda: None)
    r = here("bash", "echo hi", "c1", proj)
    assert r["stdout"] == "hi" and r["note"] == sp.NO_BASH_NOTE


# ── a command and everything it started stop together (`B964`) ──────────────


def _running(tag: str) -> list:
    """Processes whose command line holds `tag`, read from /proc."""
    found = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if tag.encode() in argv:
            found.append(int(pid))
    return found


def _gone(tag: str, within_s: float = 3.0) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        if not _running(tag):
            return True
        time.sleep(0.05)
    return False


def _tag() -> str:
    """A `sleep` length nothing else on the machine is using."""
    return f"{40 + secrets.randbelow(10)}.{secrets.randbelow(10**6):06d}"


skip_no_proc = pytest.mark.skipif(not os.path.isdir("/proc") or os.name == "nt",
                                  reason="reads /proc to find what is still running")


@skip_no_proc
@pytest.mark.parametrize("chat", ["c1", None])
def test_a_timed_out_command_leaves_nothing_behind(settings, people, proj, monkeypatch, chat):
    monkeypatch.setattr(sp, "DEFAULT_BASH_TIMEOUT", 1)
    tag = _tag()
    r = here("bash", f"echo before; sleep {tag} & wait", chat, proj)
    assert r["exit_code"] == 124 and r["output"] == "before"
    assert _gone(tag), f"sleep {tag} outlived its timed-out command: {_running(tag)}"


@skip_no_proc
def test_a_timed_out_python_leaves_nothing_behind(settings, people, proj, monkeypatch):
    monkeypatch.setattr(sp, "DEFAULT_PYTHON_TIMEOUT", 1)
    tag = _tag()
    r = here("python", f"import subprocess, time\nsubprocess.Popen(['sleep', '{tag}'])\n"
                       "time.sleep(30)", "c1", proj)
    assert r["exit_code"] == 124
    assert _gone(tag), f"sleep {tag} outlived its timed-out python: {_running(tag)}"


@skip_no_proc
def test_a_cancelled_command_leaves_nothing_behind(settings, people, proj):
    tag = _tag()

    async def run_then_cancel():
        task = asyncio.create_task(te.execute_tool_block(
            ToolBlock("bash", f"sleep {tag} & wait"), session_id="c1", owner="boss",
            workspace=str(proj), security_context=te.NO_TOOL_SECURITY_CONTEXT))
        deadline = time.monotonic() + 10
        while not _running(tag) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert _running(tag), "the command never started"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_then_cancel())
    assert _gone(tag), f"sleep {tag} outlived its cancelled command: {_running(tag)}"


@skip_no_proc
def test_a_command_without_a_group_of_its_own_is_still_killed(monkeypatch):
    """`kill_tree` on a process that is not a group leader: `killpg` finds no
    group of that number (it never reaches Pantheon's own), and the plain
    kill still happens."""
    import subprocess
    proc = subprocess.Popen(["sleep", _tag()])
    try:
        sp.kill_tree(proc)
        assert proc.wait(timeout=5) == -9
    finally:
        if proc.poll() is None:
            proc.kill()
