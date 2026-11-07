# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1993`. A command the agent ran on this machine could read the server's terminal.

`bash` and `python`, and the host commands of `git` and `shell_with_login`,
were started with stdout and stderr piped and stdin left alone, so each
inherited the server's own. On a native install started in a terminal
(`start-macos.sh` runs the server in the foreground, *"press Ctrl+C here to
stop"*) that is the person's terminal. `start_new_session` takes away the
controlling terminal and not the descriptor, so a command that reads (`read x`,
`input()`, a program that asks a question) waited for the person's keystrokes
and took them, for as long as a command may run: an hour. Docker and the
systemd unit give the server `/dev/null`, which is why it was seldom seen.

Now each starts with stdin closed (`/dev/null`), as the background jobs
(`src/bg_jobs.py`) and the workstation's daemon already start theirs, so a
read gets end-of-file at once. It is passed where each command is started:
`_create_bash_subprocess` forwards what it is given, and
`tests/test_agent_bash_windows.py` holds that. Upstream Odysseus closed the
same stdin in `84aa9a91`; its check of the spawn's arguments is the one here,
without its tmux cases, since Pantheon has no tmux shell (`B962`).

The spawns are captured rather than run: under pytest the server's own stdin
is already `/dev/null`, so a real process cannot show the difference.
"""
import asyncio

import pytest

from src.agent_tools import git_tools, subprocess_tools


class _Proc:
    returncode = 0

    async def communicate(self):
        return b"", b""


@pytest.fixture
def spawned(monkeypatch, tmp_path):
    """Every spawn's keyword arguments, in order; nothing is started."""
    seen = []

    async def create_bash(command, **kwargs):
        seen.append(kwargs)
        return _Proc()

    async def create_exec(*argv, **kwargs):
        seen.append(kwargs)
        return _Proc()

    async def stream(_proc, **_kwargs):
        return "", "", 0, False

    monkeypatch.setattr("src.tool_execution.agent_cwd", lambda: str(tmp_path))
    monkeypatch.setattr(subprocess_tools, "_create_bash_subprocess", create_bash)
    monkeypatch.setattr(subprocess_tools.asyncio, "create_subprocess_exec", create_exec)
    monkeypatch.setattr(subprocess_tools, "_run_subprocess_streaming", stream)
    return seen


def test_bash_starts_with_stdin_closed(spawned):
    result = asyncio.run(subprocess_tools.BashTool().execute(
        "read answer; echo $answer", {"subproc_env": {}, "session_id": None}))
    assert result["exit_code"] == 0
    assert [kw.get("stdin") for kw in spawned] == [asyncio.subprocess.DEVNULL]


def test_python_starts_with_stdin_closed(spawned):
    result = asyncio.run(subprocess_tools.PythonTool().execute(
        "print(input())", {"subproc_env": {}, "session_id": None}))
    assert result["exit_code"] == 0
    assert [kw.get("stdin") for kw in spawned] == [asyncio.subprocess.DEVNULL]


def test_a_git_or_login_shell_command_on_this_machine_starts_with_stdin_closed(
        spawned, tmp_path):
    place = git_tools._Place(None, None)
    assert not place.in_workstation
    out = asyncio.run(place.run("git status", cwd=str(tmp_path), env={}, timeout=5))
    assert out["exit_code"] == 0
    assert [kw.get("stdin") for kw in spawned] == [asyncio.subprocess.DEVNULL]
