# SPDX-License-Identifier: AGPL-3.0-or-later
"""A phone that does not boot in time says how far Android got.

Found on the owner's Windows host (2026-11-16): the phone sat on "Waiting for
the Android display" and then gave up with "did not finish booting", while adb
showed the device `offline` the whole time and the emulator's log ended at its
own setup lines. Nothing said that Android had never come up far enough to
answer adb, and the log held no kernel output to show where the guest stopped.
"""
from types import SimpleNamespace

import pytest

from workstation import phone as PH


class Process:
    returncode = 0
    alive = True

    def poll(self):
        return None if self.alive else self.returncode

    def wait(self, **kwargs):
        self.alive = False


def phone(tmp_path):
    system = SimpleNamespace(home=lambda account: tmp_path, uid=lambda account: 1234, backend="vm")
    p = PH.AccountPhone(system, "test", None)
    p.emulator = Process()
    p.state = "starting"
    p.port = 5586
    p.screen = SimpleNamespace(stop=lambda: None)
    p._release_port = lambda account: None
    return p


def clock(monkeypatch, step=3.0):
    now = [0.0]

    def monotonic():
        now[0] += step
        return now[0]

    monkeypatch.setattr(PH, "time", SimpleNamespace(monotonic=monotonic, sleep=lambda s: None))


def answers(state="", display="", completed=""):
    def adb(args, **kw):
        if args == ["get-state"]:
            return state
        if args[-1] == "init.svc.surfaceflinger":
            return display
        if args[-1] == "sys.boot_completed":
            return completed
        return ""
    return adb


def stall(tmp_path, monkeypatch, adb):
    p = phone(tmp_path)
    clock(monkeypatch)
    monkeypatch.setattr(PH, "BOOT_TIMEOUT_S", 12.0)
    monkeypatch.setattr(PH, "_kill", lambda proc: None)
    monkeypatch.setattr(p, "adb", adb)
    monkeypatch.setattr(p, "stream_ready", lambda: False)

    def no_screen():
        raise PH.PhoneError("unavailable", "not yet")

    monkeypatch.setattr(p, "_show", no_screen)
    p._boot(p.emulator)
    assert p.state == "unavailable" and p.emulator is None
    return p.why


def test_a_phone_adb_never_reached_says_android_never_answered(tmp_path, monkeypatch):
    why = stall(tmp_path, monkeypatch, answers(state="offline"))
    assert "never answered adb" in why
    assert PH.LOG_FILE in why and "retry" in why


def test_a_phone_that_answered_without_a_display_says_so(tmp_path, monkeypatch):
    why = stall(tmp_path, monkeypatch, answers(state="device"))
    assert "never answered adb" not in why
    assert "display service never started" in why


def test_a_phone_whose_display_started_says_it_did_not_finish(tmp_path, monkeypatch):
    why = stall(tmp_path, monkeypatch, answers(state="device", display="running"))
    assert "display started" in why and "never" not in why


def test_the_stall_quotes_the_emulators_last_line(tmp_path, monkeypatch):
    (tmp_path / ".android").mkdir()
    (tmp_path / PH.LOG_FILE).write_text("INFO | setup\n[   41.2] init: starting service 'zygote'\n")
    monkeypatch.setattr(PH.AccountPhone, "_as_account", lambda self: _noop())
    why = stall(tmp_path, monkeypatch, answers(state="offline"))
    assert "starting service 'zygote'" in why


def test_the_emulator_log_carries_the_guest_kernel():
    """Without it the log ends at the emulator's own setup and a stalled guest
    leaves nothing to read."""
    argv = PH.emulator_argv("emulator", "pixel_9", port=5586, memory_mib=8192)
    assert "-show-kernel" in argv


class _noop:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
