# SPDX-License-Identifier: AGPL-3.0-or-later
"""A phone stays this VM's own when the host steps its clock.

Found in the owner's android-vm log (2026-11-18, Windows, Docker Desktop on
WSL2): the Linux VM's wall clock went back about 1.5 s every 30 s (348 times
in 192 minutes; the log's own timestamps run backwards 28 times). The phone
told its emulator from a later process on the same pid by comparing
`psutil.Process(pid).create_time()` with the value read at launch. On Linux
psutil derives that from the wall clock: the kernel's start tick plus the boot
time *as the clock reads now*. So the first clock step after every launch
changed it, the emulator stopped counting as this VM's own for good, and every
control connection said "The Android control listener no longer belongs to
this VM":

  * a step before Android first answered (2 to 9 s after launch in three of
    the owner's runs): the phone sat at "Starting virtual hardware" for ten
    minutes, then "Android did not finish booting";
  * a step after it turned on (1 s after, in the run that showed): the
    picture froze and the buttons answered 503, which read as "zero control".

Pinned here: the emulator is known by the psutil handle kept from its launch,
which psutil compares by pid and the start tick itself. A stepped clock changes
nothing; a process that reuses the pid is still never taken for the phone.
"""
from __future__ import annotations

import subprocess
import sys
import time as real_time
from types import SimpleNamespace

import pytest

from workstation.native_android import host as H
from workstation.native_android.adb import AdbError

PORT = 5586


class Gone(Exception):
    """psutil.NoSuchProcess, without needing psutil installed (CI's lean leg has none)."""


class Denied(Gone):
    """psutil.AccessDenied."""


class Kernel:
    """What psutil reads: who holds each pid and the tick it started on, and
    the boot time the wall clock implies, which moves whenever the clock is set."""

    def __init__(self, sdk):
        self.sdk, self.rows, self.tick, self.btime, self.signalled = sdk, {}, 100_000, 1_795_000_000.0, []

    def spawn(self, pid, *, parent=None, exe=None, listening=()):
        self.tick += 250
        self.rows[pid] = dict(tick=self.tick, parent=parent, listening=tuple(listening),
                              exe=exe or str(self.sdk / "emulator/qemu/linux-x86_64/qemu-system-x86_64-headless"))

    def exit(self, pid):
        self.rows.pop(pid, None)

    def step_clock(self, seconds):
        self.btime += seconds

    def handle(self, pid):
        return Handle(self, pid)

    def wait_procs(self, procs, timeout=None):
        alive = [p for p in procs if p.is_running()]
        return [p for p in procs if p not in alive], alive


class Handle:
    """psutil.Process, as psutil 7.2.2 behaves on Linux."""

    def __init__(self, kernel, pid):
        if pid not in kernel.rows:
            raise Gone(pid)
        self.kernel, self.pid, self.started, self._created = kernel, pid, kernel.rows[pid]["tick"], None

    def _row(self):
        row = self.kernel.rows.get(self.pid)
        if row is None or row["tick"] != self.started:
            raise Gone(self.pid)
        return row

    def create_time(self):
        # "Based on the system clock, which means it may be affected by
        # changes such as manual adjustments or time synchronization."
        if self._created is None:
            self._row()
            self._created = self.started / 100 + self.kernel.btime
        return self._created

    def __eq__(self, other):  # psutil: pid and the start tick, never the wall clock
        return isinstance(other, Handle) and (self.pid, self.started) == (other.pid, other.started)

    def __hash__(self):
        return hash((self.pid, self.started))

    def is_running(self):
        row = self.kernel.rows.get(self.pid)
        return row is not None and row["tick"] == self.started

    def children(self, recursive=True):
        self._row()
        found, frontier = [], [self.pid]
        while frontier:
            parent = frontier.pop()
            for pid, row in self.kernel.rows.items():
                if row["parent"] == parent:
                    found.append(Handle(self.kernel, pid))
                    frontier.append(pid)
        return found

    def exe(self):
        return self._row()["exe"]

    def net_connections(self, kind):
        return [SimpleNamespace(status="LISTEN", laddr=SimpleNamespace(port=port)) for port in self._row()["listening"]]

    def terminate(self):
        self._row()
        self.kernel.signalled.append(("terminate", self.pid, self.started))
        self.kernel.exit(self.pid)

    def kill(self):
        self._row()
        self.kernel.signalled.append(("kill", self.pid, self.started))
        self.kernel.exit(self.pid)


def _launch(tmp_path, monkeypatch, popen):
    """`NativePhone._launch_android`, up to a started emulator; no boot thread."""
    home = tmp_path / "owner"
    (home / ".android").mkdir(parents=True)
    system = SimpleNamespace(config={"radio_binary": "radio", "scrcpy_server": "control"}, abi="x86_64", why=None,
                             sdk=tmp_path.resolve() / "sdk", emulator=tmp_path / "sdk/emulator/emulator",
                             home=lambda _: home)
    phone = H.NativePhone(system, "owned", None, claim_port=lambda _: PORT)
    phone.avd = "pantheon_pixel_9_0123456789ab"
    monkeypatch.setattr(phone, "_write_avd", lambda: None)
    monkeypatch.setattr(phone, "_boot", lambda proc: None)
    monkeypatch.setattr(phone, "info", lambda action="status": {"state": phone.state})
    radio = SimpleNamespace(env={}, TARGET="pantheon-radio.invalid:7443",
                            __enter__=lambda: None, __exit__=lambda *a: None)
    monkeypatch.setattr(H, "PrivateRadio", lambda *a, **k: radio)
    monkeypatch.setattr(H.subprocess, "Popen", popen)
    phone._launch_android()
    return phone


def start_phone(tmp_path, monkeypatch):
    """A launched phone whose emulator (pid 4242) listens on its ADB port, and the kernel under it."""
    kernel = Kernel(tmp_path.resolve() / "sdk")
    monkeypatch.setattr(H, "psutil", SimpleNamespace(
        Process=kernel.handle, Error=Gone, NoSuchProcess=Gone, AccessDenied=Denied,
        CONN_LISTEN="LISTEN", wait_procs=kernel.wait_procs))

    def popen(args, **kwargs):
        kernel.spawn(4242, listening=(PORT, PORT + 1))
        tick = kernel.rows[4242]["tick"]  # the launcher itself, not a later process on its pid
        return SimpleNamespace(pid=4242, poll=lambda: None if kernel.rows.get(4242, {}).get("tick") == tick else 0,
                               terminate=lambda: kernel.exit(4242), wait=lambda timeout=None: 0, kill=lambda: None)
    return _launch(tmp_path, monkeypatch, popen), kernel


@pytest.fixture
def started(tmp_path, monkeypatch):
    return start_phone(tmp_path, monkeypatch)


def test_a_stepped_clock_does_not_disown_a_running_phone(started):
    phone, kernel = started
    assert phone._owned()
    for _ in range(4):  # the owner's host: about every 30 s
        kernel.step_clock(-1.46)
        assert phone._owned(), "a clock step must not make the phone's own emulator a stranger"
    kernel.step_clock(+9.0)
    assert phone._owned()
    phone.direct._owned()  # the control connection's own gate: raises "no longer belongs to this VM"


def test_a_phone_still_boots_when_the_clock_steps_before_android_answers(started, monkeypatch):
    phone, kernel = started
    kernel.step_clock(-1.46)  # the owner's runs 1, 2 and 4: 2 to 9 s after launch
    answers = {"init.svc.surfaceflinger": "running", "ro.adb.secure": "1", "sys.boot_completed": "1"}

    def shell(args, timeout=20.0):
        if not phone._owned():  # as DirectAdb does before every connection
            raise AdbError("The Android control listener no longer belongs to this VM.")
        return answers.get(args[1], "") if args[0] == "getprop" else ""
    phone.direct = SimpleNamespace(shell=shell)
    monkeypatch.setattr(phone, "_show", lambda: None)
    monkeypatch.setattr(phone, "_stop_locked", lambda: setattr(phone, "emulator", None))
    now = [0.0]

    def monotonic():
        now[0] += 0.01
        return now[0]
    monkeypatch.setattr(H, "time", SimpleNamespace(monotonic=monotonic, time=real_time.time,
                                                   sleep=lambda seconds: now.__setitem__(0, now[0] + seconds)))
    H.NativePhone._boot(phone, phone.emulator)
    assert phone.state == "on", phone.why


def test_a_new_child_of_the_emulator_joins_the_family_after_a_clock_step(started):
    phone, kernel = started
    kernel.step_clock(-1.46)
    kernel.spawn(4300, parent=4242, exe="/usr/bin/helper")
    assert {process.pid for process in phone._process_family()} == {4242, 4300}


def test_a_process_that_reuses_the_emulators_pid_is_not_the_phone(started):
    phone, kernel = started
    assert phone._owned()
    kernel.exit(4242)
    # Another process gets the pid, runs the same binary and listens on the phone's ports.
    kernel.spawn(4242, listening=(PORT, PORT + 1))
    assert phone._process_family() == []
    assert not phone._owned()
    with pytest.raises(AdbError, match="no longer belongs"):
        phone.direct._owned()


def test_stopping_never_signals_a_stranger_on_a_reused_pid(started, monkeypatch):
    phone, kernel = started
    kernel.spawn(4300, parent=4242, exe="/usr/bin/helper")
    assert {process.pid for process in phone._process_family()} == {4242, 4300}
    kernel.exit(4300)
    kernel.spawn(4300, exe="/usr/bin/someone-elses")  # reused by a process that is not ours
    stranger = kernel.rows[4300]["tick"]
    kernel.step_clock(-1.46)
    monkeypatch.setattr(phone, "_release", lambda: None)
    phone.direct = None
    phone._stop_locked()
    assert kernel.rows.get(4300, {}).get("tick") == stranger, "the stranger still runs"
    assert all(pid != 4300 for _, pid, _ in kernel.signalled)
    assert 4242 not in kernel.rows, "the phone's own emulator was stopped"


def test_a_stepped_clock_does_not_cost_the_phone_its_clean_shutdown(started, monkeypatch):
    """Turning the phone off asks Android to flush and shut down first, over
    the same attested connection. Disowned, it was refused that too: the
    emulator was ended under a running Android after a wasted 30 s wait."""
    phone, kernel = started
    assert phone._owned()
    kernel.step_clock(-1.46)
    asked = []

    def shell(args, timeout=20.0):
        if not phone._owned():  # as DirectAdb does before every connection
            raise AdbError("The Android control listener no longer belongs to this VM.")
        asked.append(list(args))
        return ""
    phone.direct = SimpleNamespace(shell=shell)
    monkeypatch.setattr(phone, "_release", lambda: None)
    phone._stop_locked()
    assert asked == [["sync"], ["svc", "power", "shutdown"]]
    assert 4242 not in kernel.rows and phone.state == "off"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="psutil derives create_time from the boot time on Linux")
def test_with_the_real_psutil_a_clock_step_keeps_the_family(tmp_path, monkeypatch):
    psutil = pytest.importorskip("psutil")
    from psutil import _pslinux
    monkeypatch.setattr(H, "psutil", psutil)
    children, spawn = [], subprocess.Popen  # the launch's Popen is replaced below; this is the real one

    def popen(args, **kwargs):
        children.append(spawn([sys.executable, "-c", "import time; time.sleep(120)"]))
        return children[-1]
    try:
        phone = _launch(tmp_path, monkeypatch, popen)
        pid = children[0].pid
        assert [process.pid for process in phone._process_family()] == [pid]
        boot_time = _pslinux.boot_time
        for step in (-1.0, -2.0, +5.0):  # /proc/stat's btime after the clock was set
            monkeypatch.setattr(_pslinux, "boot_time", lambda step=step: boot_time() + step)
            assert [process.pid for process in phone._process_family()] == [pid], f"after a {step:+} s clock step"
    finally:
        for child in children:
            child.kill()
            child.wait()
    assert phone._process_family() == []
