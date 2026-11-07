# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for cross-platform helper behavior."""

import importlib.util
import io
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace


_MODULE_PATH = Path(__file__).resolve().parents[1] / "core" / "platform_compat.py"
_SPEC = importlib.util.spec_from_file_location("platform_compat_under_test", _MODULE_PATH)
platform_compat = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(platform_compat)


def _reset_bash_cache(monkeypatch):
    monkeypatch.setattr(platform_compat, "_BASH_CACHE", None)
    monkeypatch.setattr(platform_compat, "_BASH_PROBED", False)


def test_find_bash_tries_windows_exe_suffix(monkeypatch):
    _reset_bash_cache(monkeypatch)
    monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)

    expected = r"C:\Program Files\Git\bin\bash.exe"

    def fake_which(name):
        return expected if name == "bash.exe" else None

    monkeypatch.setattr(platform_compat.shutil, "which", fake_which)
    monkeypatch.setattr(platform_compat.os.path, "exists", lambda _path: False)

    assert platform_compat.find_bash() == expected


def test_find_bash_checks_local_app_data_git_install(monkeypatch):
    _reset_bash_cache(monkeypatch)
    monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)
    monkeypatch.setattr(platform_compat.shutil, "which", lambda _name: None)
    for env_name in platform_compat._WINDOWS_BASH_ROOT_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("LocalAppData", r"C:\Users\alice\AppData\Local")

    expected = r"C:\Users\alice\AppData\Local\Git\bin\bash.exe"
    monkeypatch.setattr(platform_compat.os.path, "exists", lambda path: path == expected)

    assert platform_compat.find_bash() == expected


def test_find_bash_checks_local_app_data_programs_git_install(monkeypatch):
    _reset_bash_cache(monkeypatch)
    monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)
    monkeypatch.setattr(platform_compat.shutil, "which", lambda _name: None)
    for env_name in platform_compat._WINDOWS_BASH_ROOT_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("LocalAppData", r"C:\Users\alice\AppData\Local")

    expected = r"C:\Users\alice\AppData\Local\Programs\Git\bin\bash.exe"
    monkeypatch.setattr(platform_compat.os.path, "exists", lambda path: path == expected)

    assert platform_compat.find_bash() == expected


def test_find_bash_skips_windows_wsl_stub(monkeypatch):
    _reset_bash_cache(monkeypatch)
    monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)

    stub = r"C:\WINDOWS\system32\bash.exe"
    expected = r"C:\Program Files\Git\bin\bash.exe"
    monkeypatch.setattr(
        platform_compat.shutil,
        "which",
        lambda name: stub if name == "bash" else None,
    )
    monkeypatch.setattr(platform_compat.os.path, "exists", lambda path: path == expected)

    assert platform_compat.find_bash() == expected


def test_is_wsl_true_when_proc_version_mentions_microsoft(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux", raising=False)

    def fake_open(path, mode="r", *args, **kwargs):
        assert path == "/proc/version"
        assert mode == "r"
        assert kwargs == {"encoding": "utf-8", "errors": "ignore"}
        return io.StringIO("Linux version 6.6.0 microsoft standard")

    monkeypatch.setattr("builtins.open", fake_open)

    assert platform_compat.is_wsl() is True


def test_is_wsl_false_when_proc_version_is_not_microsoft(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: io.StringIO("Linux version 6.6.0 generic"))

    assert platform_compat.is_wsl() is False


def test_is_wsl_false_on_non_posix_without_proc_probe(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr(platform_compat.os, "name", "nt", raising=False)

    def fail_open(*_args, **_kwargs):
        raise AssertionError("open should not be called when platform is not Linux/POSIX")

    monkeypatch.setattr("builtins.open", fail_open)

    assert platform_compat.is_wsl() is False


def test_translate_path_converts_windows_drive_path_on_wsl(monkeypatch):
    monkeypatch.setattr(platform_compat, "is_wsl", lambda: True)

    out = platform_compat.translate_path(r"C:\Users\alice\models\qwen.gguf")

    assert out == "/mnt/c/Users/alice/models/qwen.gguf"


def test_translate_path_resolves_paths_when_not_wsl(monkeypatch):
    monkeypatch.setattr(platform_compat, "is_wsl", lambda: False)

    assert platform_compat.translate_path(".") == str(Path(".").resolve())


def test_translate_path_returns_input_when_resolve_fails(monkeypatch):
    monkeypatch.setattr(platform_compat, "is_wsl", lambda: False)

    class _BrokenPath:
        def __init__(self, _value):
            pass

        def resolve(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(platform_compat, "Path", _BrokenPath)

    assert platform_compat.translate_path("weird::path") == "weird::path"


def test_nvidia_path_override_is_correct_string(monkeypatch):
    monkeypatch.setattr(platform_compat, "_SSH_PATH_MEMBERS", ["path1", "path2"])
    assert platform_compat._ssh_path_override() == "export PATH=\"$PATH:path1:path2\"; "


def test_windows_powershell_argv_defaults_include_no_profile_and_noninteractive():
    argv = platform_compat._windows_powershell_argv("Write-Output Hello")
    assert argv == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Write-Output Hello",
    ]


def test_windows_powershell_argv_respects_disabled_flags():
    argv = platform_compat._windows_powershell_argv(
        "Write-Output Hello",
        no_profile=False,
        non_interactive=False,
    )
    assert argv == ["powershell.exe", "-Command", "Write-Output Hello"]


def test_run_wsl_windows_powershell_raises_outside_wsl(monkeypatch):
    monkeypatch.setattr(platform_compat, "is_wsl", lambda: False)
    try:
        platform_compat.run_wsl_windows_powershell("Write-Output Hello", timeout=2)
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "only supported in WSL" in str(exc)


def test_run_wsl_windows_powershell_calls_subprocess_with_expected_argv(monkeypatch):
    monkeypatch.setattr(platform_compat, "is_wsl", lambda: True)
    captured = {}

    class _Result:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def _fake_run(args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(platform_compat.subprocess, "run", _fake_run)

    result = platform_compat.run_wsl_windows_powershell("Write-Output Hello", timeout=9)

    assert result.returncode == 0
    assert captured["args"] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Write-Output Hello",
    ]
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["timeout"] == 9


def test_ssh_exec_argv_builds_default_command():
    argv = platform_compat._ssh_exec_argv("alice@gpu-box", None, remote_cmd="echo ok")
    assert argv == ["ssh", "alice@gpu-box", "echo ok"]


def test_ssh_exec_argv_includes_port_and_options():
    argv = platform_compat._ssh_exec_argv(
        "alice@gpu-box",
        "2222",
        remote_cmd="tmux ls",
        connect_timeout=6,
        strict_host_key_checking=False,
    )
    assert argv == [
        "ssh",
        "-o",
        "ConnectTimeout=6",
        "-o",
        "StrictHostKeyChecking=no",
        "-p",
        "2222",
        "alice@gpu-box",
        "tmux ls",
    ]


def test_run_ssh_command_uses_built_argv(monkeypatch):
    captured = {}

    class _Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(platform_compat.subprocess, "run", _fake_run)

    result = platform_compat.run_ssh_command(
        "alice@gpu-box",
        "2200",
        "tmux ls",
        timeout=7,
        connect_timeout=3,
        strict_host_key_checking=True,
        text=False,
    )

    assert result.returncode == 0
    assert captured["args"] == [
        "ssh",
        "-o",
        "ConnectTimeout=3",
        "-o",
        "StrictHostKeyChecking=yes",
        "-p",
        "2200",
        "alice@gpu-box",
        "tmux ls",
    ]
    assert captured["kwargs"]["timeout"] == 7
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is False


# ── `B1927`: a stored pid never reaches Pantheon itself ─────────────────────


def test_a_pid_that_is_not_a_positive_whole_number_is_never_probed_or_signalled(monkeypatch):
    """`B1927`. ``0`` and a negative number name process groups (``-1`` is
    every process Pantheon may signal) and ``True`` is pid 1. ``pid_alive(-1)``
    probed them all and ``kill_process_tree(-1)`` sent SIGTERM to them all; a
    hand-edited job record was enough. Now neither reaches a signal."""
    calls = []
    monkeypatch.setattr(platform_compat, "IS_WINDOWS", False)
    for name in ("kill", "killpg", "getpgid"):
        monkeypatch.setattr(platform_compat.os, name,
                            lambda *args, _name=name: calls.append((_name, *args)) or 0)
    for pid in (-1, 0, -4321, True, None, "4321", 4321.0):
        assert platform_compat.pid_alive(pid) is False, pid
        assert platform_compat.kill_process_tree(pid) is None
    assert calls == []


def _process_table(monkeypatch, groups):
    """`os.getpgid`, `os.killpg` and `os.kill` as a process table of
    ``{pid: its group}`` answers them, each signal recorded and none sent. A
    group exists while a pid in the table is in it."""
    sent = []

    def getpgid(pid):
        if pid not in groups:
            raise ProcessLookupError(pid)
        return groups[pid]

    def killpg(pgid, sig):
        if pgid not in set(groups.values()):
            raise ProcessLookupError(pgid)
        sent.append(("killpg", pgid, sig))

    def kill(pid, sig):
        if pid not in groups:
            raise ProcessLookupError(pid)
        sent.append(("kill", pid, sig))

    monkeypatch.setattr(platform_compat, "IS_WINDOWS", False)
    monkeypatch.setattr(platform_compat.os, "getpgid", getpgid)
    monkeypatch.setattr(platform_compat.os, "killpg", killpg)
    monkeypatch.setattr(platform_compat.os, "kill", kill)
    return sent


def test_kill_process_tree_never_signals_pantheons_own_group(monkeypatch):
    """`B1927`. It sent SIGTERM to the whole of ``getpgid(pid)``'s group. A
    stored job pid that the system handed out again to one of Pantheon's own
    threads, or to a child started without a session of its own, is in
    Pantheon's group, so that ended Pantheon (`B964` kept its shell tools off
    this branch for the same reason). Now the group signalled is one ``pid``
    leads, a plain ``kill`` never reaches a process in Pantheon's group, and a
    detached job, which leads its own group, still stops with its children."""
    ours, me = os.getpgrp(), os.getpid()
    member, stranger, leader = 434343, 444444, 424242
    sent = _process_table(monkeypatch, {me: ours, ours: ours, member: ours,
                                        stranger: 454545, leader: leader})
    for pid in (me, ours, member):
        platform_compat.kill_process_tree(pid)
    assert sent == [], "nothing reached Pantheon's own group"
    platform_compat.kill_process_tree(stranger)
    assert sent == [("kill", stranger, signal.SIGTERM)], "one process, not its group"
    sent.clear()
    platform_compat.kill_process_tree(leader)
    assert sent == [("killpg", leader, signal.SIGTERM)], "a detached job stops with its children"


def test_on_windows_a_process_start_time_names_the_process(monkeypatch):
    """`B1927`. Windows hands a pid out again quickly, so `bg_jobs` keeps when
    its job's process started (``GetProcessTimes``) beside the pid and asks
    again before a signal. Against a stand-in kernel32: the token is the
    creation time as one number and the handle is closed; a pid nobody holds
    has none, and on POSIX there is none (the command line proves the job)."""
    import ctypes

    class Kernel32:
        def __init__(self):
            self.closed = []

        def OpenProcess(self, access, inherit, pid):
            assert access == 0x1000, "PROCESS_QUERY_LIMITED_INFORMATION, as pid_alive asks"
            return 77 if pid == 4321 else 0

        def GetProcessTimes(self, handle, created, exited, kernel, user):
            created._obj.dwHighDateTime, created._obj.dwLowDateTime = 3, 5
            return 1

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    kernel32 = Kernel32()
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False)
    monkeypatch.setattr(platform_compat, "IS_WINDOWS", True)
    assert platform_compat.process_start_token(4321) == str((3 << 32) | 5)
    assert kernel32.closed == [77]
    assert platform_compat.process_start_token(999) is None
    assert platform_compat.process_start_token(-1) is None
    monkeypatch.setattr(platform_compat, "IS_WINDOWS", False)
    assert platform_compat.process_start_token(4321) is None
