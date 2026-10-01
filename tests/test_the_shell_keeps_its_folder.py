# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B962` — the agent's shell keeps its folder per chat, on Pantheon's machine and in the workstation.

The owner's call on `B962` (`D-2026-10-01-01`): *keep the working folder per
chat, on both machines; environment resets.* Every case drives the real
dispatcher (`execute_tool_block`) twice or more, so what is asserted is what a
second call in the same chat — and in another chat — actually sees (`Law 20`).
The workstation cases run against the real daemon
(`tests/helpers/workstation_daemon.py`).

  * **the folder is kept**, per chat and per person, by `bash` and read by
    `python`; variables, functions and options are not;
  * **held to the file tools' rule**: a `cd` out of the workspace, out of the
    allowed roots, out of the workstation home or into a sensitive folder is
    not where the next command starts, and the result says so;
  * **a folder that is gone** falls back to the start folder with a sentence;
  * **the command is the command**: exit code, output and the line numbers in
    its own errors are what they were without the folder report.

`B961` (bash is bash) and `B964` (a command stops with what it started) are
`tests/test_bash_is_bash_and_stops_with_what_it_started.py`.

Only harmless commands run here (`echo`, `cd`, `mkdir` under `tmp_path`): a
mutation that breaks a guard must not be able to start anything that matters
(the `P20-03` incident).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import src.agent_tools.subprocess_tools as sp
import src.agent_tools.workstation_tools as wt
import src.tool_execution as te
from src.workstation_client import account_for
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _USERS, _call, _home, _on, people, settings, ws,
)


def _forget_every_folder():
    # Tolerant of a tree without them, so a run against the code before `B962`
    # fails on behaviour rather than on this fixture.
    if hasattr(sp, "CHAT_FOLDERS"):
        sp.CHAT_FOLDERS.clear()
    getattr(wt, "_HOMES", {}).clear()


@pytest.fixture(autouse=True)
def fresh_memory():
    """Each case starts with no chat holding a folder, and leaves none."""
    _forget_every_folder()
    yield
    _forget_every_folder()


@pytest.fixture
def proj(tmp_path):
    """A workspace on this machine with a folder in it."""
    d = Path(os.path.realpath(tmp_path)) / "proj"
    (d / "sub").mkdir(parents=True)
    return d


def here(tool, content, chat, workspace, owner="boss"):
    return _call(tool, content, owner, session_id=chat,
                 workspace=str(workspace) if workspace else None)[1]


def there(tool, content, chat, owner="ann", workspace=None):
    r = _call(tool, content, owner, session_id=chat, workspace=workspace)[1]
    assert r.get("ran_in") == "workstation", r
    return r


# ── on Pantheon's machine ────────────────────────────────────────────────────


def test_a_chat_keeps_its_shell_folder_here(settings, people, proj):
    r = here("bash", "cd sub && pwd", "c1", proj)
    assert r["stdout"] == str(proj / "sub") and r["cwd"] == str(proj / "sub")
    r = here("bash", "pwd", "c1", proj)
    assert r["stdout"] == str(proj / "sub") and r["exit_code"] == 0
    r = here("python", "import os; print(os.getcwd())", "c1", proj)
    assert r["stdout"] == str(proj / "sub") and r["cwd"] == str(proj / "sub")
    # Back to the start folder: nothing is held, and the next call starts there.
    r = here("bash", "cd .. && pwd", "c1", proj)
    assert r["cwd"] == str(proj) and "note" not in r
    assert here("bash", "pwd", "c1", proj)["stdout"] == str(proj)


def test_another_chat_and_a_call_outside_a_chat_start_in_the_workspace(settings, people, proj):
    here("bash", "cd sub", "c1", proj)
    assert here("bash", "pwd", "c2", proj)["stdout"] == str(proj)
    outside = here("bash", "pwd", None, proj)
    assert outside["stdout"] == str(proj) and "cwd" not in outside
    # And a `cd` outside a chat is not kept for anyone.
    here("bash", "cd sub", None, proj)
    assert here("bash", "pwd", None, proj)["stdout"] == str(proj)
    assert here("bash", "pwd", "c1", proj)["stdout"] == str(proj / "sub")


def test_two_people_never_share_a_chats_folder(settings, people, proj, monkeypatch):
    monkeypatch.setitem(_USERS, "dan", {"admin": True, "privs": {}})
    here("bash", "cd sub", "c1", proj, owner="boss")
    assert here("bash", "pwd", "c1", proj, owner="dan")["stdout"] == str(proj)
    assert here("bash", "pwd", "c1", proj, owner="boss")["stdout"] == str(proj / "sub")


def test_the_environment_does_not_carry_over_here(settings, people, proj):
    here("bash", "export PAN_X=1; PAN_Y=2; pan_f() { :; }; set -o noclobber; cd sub", "c1", proj)
    r = here("bash", 'echo "${PAN_X:-unset} ${PAN_Y:-unset} $(type -t pan_f || echo none) '
                     '$([[ -o noclobber ]] && echo on || echo off)"; pwd', "c1", proj)
    assert r["stdout"].splitlines() == ["unset unset none off", str(proj / "sub")]


def test_a_cd_out_of_the_workspace_is_not_where_the_next_command_starts(settings, people, proj):
    r = here("bash", "cd / && pwd", "c1", proj)
    assert r["stdout"] == "/" and r["cwd"] == str(proj)
    assert r["note"] == (f"The shell ended in /, outside the workspace ({proj}), so the next "
                         f"command starts in {proj}.")
    r = here("bash", "pwd", "c1", proj)
    assert r["stdout"] == str(proj) and "note" not in r


def test_a_cd_into_a_sensitive_folder_is_not_kept(settings, people, proj):
    (proj / ".ssh").mkdir()
    r = here("bash", "cd .ssh", "c1", proj)
    assert r["cwd"] == str(proj)
    assert r["note"] == (f"The shell ended in {proj / '.ssh'}, a sensitive folder (such as .ssh) "
                         f"the file tools refuse, so the next command starts in {proj}.")
    assert here("bash", "pwd", "c1", proj)["stdout"] == str(proj)


def test_without_a_workspace_the_allowed_roots_hold_it(settings, people, tmp_path, monkeypatch):
    base = Path(os.path.realpath(tmp_path))
    (base / "start").mkdir()
    (base / "elsewhere").mkdir()
    monkeypatch.setattr(te, "_AGENT_WORKDIR", str(base / "start"))
    # Inside the allowed roots (the system temp folder is one): kept.
    r = here("bash", f"cd {base / 'elsewhere'}", "c1", None)
    assert r["cwd"] == str(base / "elsewhere") and "note" not in r
    assert here("bash", "pwd", "c1", None)["stdout"] == str(base / "elsewhere")
    # Outside them: not kept, and said.
    r = here("bash", "cd /usr", "c1", None)
    assert r["cwd"] == str(base / "start")
    assert r["note"] == ("The shell ended in /usr, outside the folders Pantheon's file tools may "
                         f"use, so the next command starts in {base / 'start'}.")


def test_a_folder_that_is_gone_falls_back_with_a_sentence_here(settings, people, proj):
    here("bash", "cd sub", "c1", proj)
    (proj / "sub").rmdir()
    r = here("bash", "pwd", "c1", proj)
    assert r["stdout"] == str(proj) and r["cwd"] == str(proj)
    assert r["note"] == (f"This chat's shell was in {proj / 'sub'}, which is no longer there, "
                         f"so this command started in {proj}.")
    assert "note" not in here("bash", "pwd", "c1", proj)


def test_picking_another_workspace_moves_the_shell(settings, people, proj, tmp_path):
    other = Path(os.path.realpath(tmp_path)) / "other"
    other.mkdir()
    here("bash", "cd sub", "c1", proj)
    r = here("bash", "pwd", "c1", other)
    assert r["stdout"] == str(other)
    assert r["note"] == (f"The workspace changed, so this chat's shell starts in {other} "
                         f"(it was in {proj / 'sub'}).")


def test_the_command_keeps_its_exit_code_output_and_line_numbers(settings, people, proj):
    r = here("bash", "cd sub; echo hi; exit 3", "c1", proj)
    assert (r["stdout"], r["exit_code"], r["cwd"]) == ("hi", 3, str(proj / "sub"))
    r = here("bash", "cd ..; set -e; false; echo never", "c1", proj)
    assert (r["stdout"], r["exit_code"], r["cwd"]) == ("", 1, str(proj))
    # The folder report sits on the command's own first line, so the line
    # numbers bash prints are the ones it printed without it, and a line it
    # quotes back never carries the report.
    for command in ("pan_not_a_command", "echo one\npan_not_a_command", "echo ( oops",
                    "set -x; cd sub"):
        in_chat = here("bash", command, "c2", proj)
        alone = here("bash", command, None, proj)
        assert in_chat["stderr"] == alone["stderr"], command
        assert in_chat["exit_code"] == alone["exit_code"], command
        assert sp._CwdReport.VAR not in in_chat["output"], command
    assert "line 2" in here("bash", "echo one\npan_not_a_command", "c3", proj)["stderr"]


def test_a_command_that_replaces_the_shell_keeps_the_folder_it_had(settings, people, proj):
    here("bash", "cd sub", "c1", proj)
    r = here("bash", "cd /; exec true", "c1", proj)
    assert r["exit_code"] == 0 and r["cwd"] == str(proj / "sub")
    assert here("bash", "pwd", "c1", proj)["stdout"] == str(proj / "sub")


def test_no_report_file_is_left_behind_here(settings, people, proj):
    import tempfile
    before = set(Path(tempfile.gettempdir()).glob("pantheon-shell-cwd-*"))
    for _ in range(3):
        here("bash", "cd sub; cd ..", "c1", proj)
    assert set(Path(tempfile.gettempdir()).glob("pantheon-shell-cwd-*")) == before


# ── in `sh`, and in the background ───────────────────────────────────────


def test_the_folder_report_is_posix_sh(settings, people, proj, monkeypatch):
    """Where there is no bash (`B961` runs `sh` and says so), the folder is
    still kept: the report is POSIX — `trap`, `command`, `>|` — and dash runs it."""
    monkeypatch.setattr(sp, "find_bash", lambda: None)
    here("bash", "cd sub", "c1", proj)
    r = here("bash", "pwd", "c1", proj)
    assert r["stdout"] == str(proj / "sub") and r["note"] == sp.NO_BASH_NOTE


def test_a_background_job_starts_where_the_chats_shell_is(settings, people, proj, monkeypatch):
    """`#!bg` is a `bash` call too: it starts in the chat's folder, and being
    detached, where it ends moves nothing. The launcher is a spy, so nothing
    is started."""
    from src import bg_jobs
    launched = []
    monkeypatch.setattr(bg_jobs, "launch", lambda command, session_id, cwd=None, **kw:
                        launched.append((command, cwd)) or {"id": "job1"})
    here("bash", "cd sub", "c1", proj)
    r = here("bash", "#!bg\necho later", "c1", proj)
    assert launched == [("echo later", str(proj / "sub"))]
    assert r["bg_job_id"] == "job1" and r["cwd"] == str(proj / "sub")
    here("bash", "#!bg\necho later", "c2", proj)
    assert launched[-1] == ("echo later", str(proj))
    (proj / "sub").rmdir()
    r = here("bash", "#!bg\necho later", "c1", proj)
    assert launched[-1] == ("echo later", str(proj))
    assert r["note"] == (f"This chat's shell was in {proj / 'sub'}, which is no longer there, "
                         f"so this command started in {proj}.")


# ── in the workstation ───────────────────────────────────────────────────────


def test_a_chat_keeps_its_shell_folder_in_the_workstation(ws, settings, people):
    _on(settings, ws)
    home = _home(ws, "ann")
    r = there("bash", "mkdir -p proj/sub && cd proj/sub && pwd", "c1")
    assert r["stdout"] == str(home / "proj" / "sub") and r["cwd"] == str(home / "proj" / "sub")
    assert r["ran_as"] == account_for("ann")
    assert there("bash", "pwd", "c1")["stdout"] == str(home / "proj" / "sub")
    r = there("python", "import os; print(os.getcwd())", "c1")
    assert r["stdout"] == str(home / "proj" / "sub") and r["cwd"] == str(home / "proj" / "sub")
    # Another chat, and a call outside any chat, start in the home.
    assert there("bash", "pwd", "c2")["stdout"] == str(home)
    assert there("bash", "pwd", None)["stdout"] == str(home)
    # Back home: nothing held.
    assert there("bash", "cd ~", "c1")["cwd"] == str(home)
    assert there("bash", "pwd", "c1")["stdout"] == str(home)


def test_two_people_in_the_workstation_never_share_a_chats_folder(ws, settings, people):
    _on(settings, ws)
    there("bash", "mkdir -p proj && cd proj", "c1", owner="ann")
    assert there("bash", "pwd", "c1", owner="cat")["stdout"] == str(_home(ws, "cat"))
    assert there("bash", "pwd", "c1", owner="ann")["stdout"] == str(_home(ws, "ann") / "proj")


def test_the_environment_does_not_carry_over_in_the_workstation(ws, settings, people):
    _on(settings, ws)
    there("bash", "export PAN_X=1; pan_f() { :; }; mkdir -p proj && cd proj", "c1")
    r = there("bash", 'echo "${PAN_X:-unset} $(type -t pan_f || echo none)"; pwd', "c1")
    assert r["stdout"].splitlines() == ["unset none", str(_home(ws, "ann") / "proj")]


def test_a_folder_that_is_gone_falls_back_with_a_sentence_in_the_workstation(ws, settings, people):
    _on(settings, ws)
    home = _home(ws, "ann")
    there("bash", "mkdir -p proj/sub && cd proj/sub", "c1")
    shutil.rmtree(home / "proj")
    r = there("bash", "pwd", "c1")
    assert r["stdout"] == str(home) and r["cwd"] == str(home)
    assert r["note"] == (f"This chat's shell was in {home / 'proj' / 'sub'}, which is no longer "
                         f"there, so this command started in {home}.")
    assert "note" not in there("bash", "pwd", "c1")


def test_a_cd_out_of_the_home_or_into_a_sensitive_folder_is_not_kept(ws, settings, people):
    _on(settings, ws)       # `sudo` off: the daemon holds commands to the home
    home = _home(ws, "ann")
    r = there("bash", "cd / && pwd", "c1")
    assert r["stdout"] == "/" and r["cwd"] == str(home)
    assert r["note"] == (f"The shell ended in /, outside your workstation home, so the next "
                         f"command starts in {home}.")
    assert there("bash", "pwd", "c1")["stdout"] == str(home)
    r = there("bash", "mkdir -p .ssh && cd .ssh", "c1")
    assert r["cwd"] == str(home)
    assert r["note"] == (f"The shell ended in {home / '.ssh'}, a sensitive folder (such as .ssh) "
                         f"the file tools refuse, so the next command starts in {home}.")
    assert there("bash", "pwd", "c1")["stdout"] == str(home)


def test_a_report_left_by_an_earlier_call_is_not_read_as_this_ones(ws, settings, people):
    """The workstation's report file is one per chat. A command that replaces
    the shell writes none, so the file still holds the last call's folder —
    here `/`, already refused once. Read as this call's, it would be refused
    and said again; it carries the earlier call's nonce, so it is not."""
    _on(settings, ws)
    home = _home(ws, "ann")
    assert "outside your workstation home" in there("bash", "cd /", "c1")["note"]
    r = there("bash", "exec true", "c1")
    assert r["cwd"] == str(home) and "note" not in r, r


def test_with_sudo_on_the_folder_follows_the_jail_and_a_later_jail_is_kept(ws, settings, people,
                                                                          tmp_path):
    outside = Path(os.path.realpath(tmp_path)) / "outside-the-home"
    outside.mkdir()
    _on(settings, ws, workstation_sudo=True)
    home = _home(ws, "ann")
    # With the jail lifted, the file tools reach outside the home, and so may
    # the folder the shell starts in.
    r = there("bash", f"cd {outside}", "c1")
    assert r["cwd"] == str(outside) and "note" not in r
    assert there("bash", "pwd", "c1")["stdout"] == str(outside)
    # Then the admin switches `sudo` off: the daemon refuses the folder, and
    # the command starts in the home, saying why.
    settings["workstation_sudo"] = False
    r = there("bash", "pwd", "c1")
    assert r["stdout"] == str(home)
    assert r["note"] == (f"This chat's shell was in {outside}, which the workstation does not let "
                         f"it use now, so this command started in {home}.")


def test_the_workstation_command_keeps_its_output_and_errors(ws, settings, people):
    _on(settings, ws)
    r = there("bash", "mkdir -p proj; cd proj; echo hi; exit 3", "c1")
    assert (r["stdout"], r["exit_code"]) == ("hi", 3)
    assert r["cwd"] == str(_home(ws, "ann") / "proj")
    for command in ("echo ( oops", "echo one\npan_not_a_command"):
        r = there("bash", command, "c2")
        assert sp._CwdReport.VAR not in r["output"], command
    assert "line 1: syntax error" in there("bash", "echo ( oops", "c2")["stderr"]
    assert "line 2: pan_not_a_command" in there("bash", "echo one\npan_not_a_command",
                                               "c2")["stderr"]


def test_output_and_progress_never_show_the_report(ws, settings, people, monkeypatch, proj):
    """The one place the report could surface: a command that prints its own
    source. Here that is the `bash -c` argument (`/proc/$$/cmdline`); in the
    workstation, the script the daemon runs (`$0`). The result and every
    progress beat show the command as it was written."""
    monkeypatch.setattr(sp, "PROGRESS_INTERVAL_S", 0.2)
    tails = []

    async def cb(payload):
        tails.append(payload.get("tail", ""))

    command = "tr '\\0' '\\n' < /proc/$$/cmdline; sleep 0.7"
    r = _call("bash", command, "boss", session_id="c1", workspace=str(proj), progress_cb=cb)[1]
    assert r["stdout"].splitlines()[-1] == command and sp._CwdReport.VAR not in r["output"]
    _on(settings, ws)
    command = 'cat "$0"; echo; sleep 0.7'
    r = _call("bash", command, "ann", session_id="c1", progress_cb=cb)[1]
    assert r["stdout"] == command and sp._CwdReport.VAR not in r["output"]
    assert len(tails) >= 2 and all(sp._CwdReport.VAR not in t for t in tails), tails
