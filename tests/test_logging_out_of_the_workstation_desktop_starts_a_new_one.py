# SPDX-License-Identifier: AGPL-3.0-or-later
"""Logging out of the workstation desktop, and getting it back — reported by
the owner, 2026-11-16: *"I logged out of the VM... And now I'm in a blank
(black) screen with no ability to do anything. I also can't restart/reboot the
VM from the controls."*

Two defects, each pinned here:

  * **Log Out left the screen black for good.** A desktop display is two
    processes: the X server (KasmVNC's, which the person's viewer is joined
    to) and the XFCE session on it. Log Out ends the session and leaves the X
    server, and `XDisplay.running()` asked only the server — so the display
    counted as up, nothing started a session again, and the viewer showed the
    bare root window until the machine was gone. Now an ended session is
    started again on the same server: at once by a watch on the session, and
    on the display's next use besides. The viewer stays joined (same server,
    same port, same logins). A session that keeps ending as soon as it starts
    is not started forever; the display says why, and Restart starts it.
  * **A person had no way to restart their workstation.** The ⋯ menu offered
    Save and Reset (which erases); the panel's Restart is the admin's, and
    restarts the container every person's machine is in. Now
    `ROUTES["restart"]` restarts the caller's own: on the VM backend their
    machine powers off cleanly and starts again with its disk as it was —
    nobody else's machine is touched; where the workstation is one system
    shared by accounts, their desktop starts again. Pantheon serves it to
    the person, for themselves only, behind `POST /api/workstation/restart`.
"""
from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest

from src.workstation_client import WorkstationClient, account_for
from tests.helpers.vm_fleet import HOST_TOKEN, InProcessMachine, vm_host
from tests.helpers.workstation_daemon import running_workstation
from workstation import protocol as P
from workstation import ubuntu
from workstation.ubuntu import XDisplay

ROOT = Path(__file__).resolve().parents[1]
ANN = account_for("ann")
BOB = account_for("bob")


@pytest.fixture
def no_chown(monkeypatch):
    monkeypatch.setattr(ubuntu.os, "chown", lambda *a, **k: None)
    monkeypatch.setattr(ubuntu.os, "fchown", lambda *a, **k: None)


class _Server:
    """An X server that is up until a test stops it."""
    def __init__(self):
        self.returncode = None
        self.pid = 0

    def poll(self):
        return self.returncode


class _Session:
    """A desktop session: runs until it is logged out of (`end`)."""
    def __init__(self):
        self.returncode = None
        self.pid = 0
        self._ended = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self._ended.wait(timeout):
            raise TimeoutError
        return self.returncode

    def end(self, code=0):
        self.returncode = code
        self._ended.set()


class _System:
    def __init__(self, root: Path):
        self.desktop_root = root

    def home(self, account):
        return self.desktop_root

    def run_as(self, account, *, with_display=True):
        return [], {"HOME": str(self.desktop_root)}

    def uid(self, account):
        return 2001

    def add_desktop_settings(self, account):
        return 0

    def retire_shipped_files(self, account):
        return 0


@pytest.fixture
def desktop(tmp_path, monkeypatch, no_chown):
    """A desktop display on KasmVNC with everything below the processes real:
    `servers` and `sessions` are what it started, in order."""
    monkeypatch.setattr(ubuntu.shutil, "which",
                        lambda name, *a, **k: "/usr/bin/" + name
                        if name in (ubuntu.KASMVNC_SERVER, "dbus-run-session") else None)
    monkeypatch.setattr(ubuntu, "_answers", lambda port, timeout: True)
    monkeypatch.setattr(ubuntu, "_stop", lambda proc, **k: setattr(proc, "returncode", -15) or "")
    monkeypatch.setattr(ubuntu, "fs_identity", lambda uid, gid: contextlib.nullcontext())
    monkeypatch.setattr(ubuntu, "desktop_session", lambda: ([ubuntu.XFCE_SESSION], {}))
    monkeypatch.setattr(ubuntu, "_SESSION_AGAIN_AFTER_S", 0.0, raising=False)
    display = XDisplay(_System(tmp_path), ANN)
    servers, sessions = [], []

    def spawn(prefix, env, label, argv):
        servers.append(_Server())
        return (servers[-1], 7 + len(servers)), ""

    def popen(argv, **kw):
        sessions.append(_Session())
        return sessions[-1]

    display._spawn = spawn
    monkeypatch.setattr(ubuntu.subprocess, "Popen", popen)
    monkeypatch.setattr(display, "_wait_for_wm", lambda *a, **k: 0.0)
    monkeypatch.setattr(display, "_open_watch", lambda: None)
    yield display, servers, sessions
    display.stop()


def _until(check, limit=3.0):
    started = time.monotonic()
    while time.monotonic() - started < limit:
        if check():
            return True
        time.sleep(0.01)
    return check()


# ── Log Out ───────────────────────────────────────────────────────────────────

def test_logging_out_starts_a_new_session_on_the_same_screen_without_anyone_asking(desktop):
    display, servers, sessions = desktop
    name = display.start()
    port = display._desktop[0]
    assert len(servers) == 1 and len(sessions) == 1

    sessions[0].end(0)                       # the person pressed Log Out

    assert _until(lambda: len(sessions) == 2), "the screen stayed black: no new session"
    assert len(servers) == 1, "the X server the viewer is joined to was replaced"
    assert display.start() == name and display._desktop[0] == port
    assert sessions[1].poll() is None


def test_the_next_use_starts_a_session_that_ended_even_before_the_watch_does(
        desktop, monkeypatch):
    display, servers, sessions = desktop
    monkeypatch.setattr(display, "_watch_session", lambda proc, generation: None)
    display.start()
    sessions[0].end(0)
    display.start()                          # a screenshot, the viewer joining
    assert len(sessions) == 2 and len(servers) == 1


def test_a_session_that_keeps_ending_at_once_is_not_started_forever(desktop, monkeypatch):
    display, servers, sessions = desktop
    monkeypatch.setattr(display, "_watch_session", lambda proc, generation: None)
    display.start()
    for _ in range(ubuntu._SESSION_QUICK_MAX):
        sessions[-1].end(1)
        display.start()
    count = len(sessions)
    sessions[-1].end(1)
    display.start()
    display.start()
    assert len(sessions) == count, "a session that dies at once was started in a loop"
    assert "desktop session ended" in display.desktop_why.lower()
    assert "restart" in display.desktop_why.lower()
    # Restart is the way out, and it starts the desktop from nothing.
    display.restart()
    assert len(sessions) == count + 1 and len(servers) == 2
    assert "session ended" not in display.desktop_why


def test_a_display_that_was_stopped_does_not_start_its_old_session_again(desktop):
    display, servers, sessions = desktop
    display.start()
    display.stop()
    sessions[0].end(-15)                     # what stopping the display does to it
    time.sleep(0.1)
    assert len(sessions) == 1


def test_restart_keeps_who_drives(desktop):
    display, servers, sessions = desktop
    display.start()
    display.set_driver(True)
    display.restart()
    assert len(servers) == 2 and display._driving is True
    assert ":rw\n" in display._desktop[1].path.read_text()


# ── Restart: the protocol, the container's daemon, the VM host ───────────────

def test_restart_is_a_route_of_the_protocol():
    assert P.ROUTES["restart"] == ("POST", "/v1/users/{account}/restart")
    assert set(P.RESTART_KINDS) == {"desktop", "machine"}


def test_where_accounts_share_a_system_restart_starts_only_the_callers_desktop(tmp_path):
    from tests.helpers.workstation_daemon import PictureScreen

    class Counting(PictureScreen):
        def __init__(self, account):
            super().__init__(account)
            self.restarts = 0

        def restart(self):
            self.restarts += 1

    with running_workstation(tmp_path, screen_factory=Counting) as ws:
        client = WorkstationClient(ws.url, ws.token)
        import asyncio
        asyncio.run(client.ensure(ANN))
        asyncio.run(client.ensure(BOB))
        answer = asyncio.run(client.restart(ANN))
        assert answer == {"account": ANN, "restarted": "desktop"}
        assert ws.screen(ANN).restarts == 1 and ws.screen(BOB).restarts == 0
        assert (ws.root / ANN).is_dir(), "a restart erased the home"


def test_on_the_vm_backend_restart_powers_the_persons_machine_off_cleanly_and_back_on(tmp_path):
    import asyncio
    with vm_host(tmp_path / "vm") as (fleet, url):
        client = WorkstationClient(url, HOST_TOKEN)
        asyncio.run(client.ensure(ANN))
        asyncio.run(client.ensure(BOB))
        ann, bob = fleet.machine_for(ANN), fleet.machine_for(BOB)
        marker = ann.dir / "homes" / "kept.txt"
        marker.write_text("still here")
        answer = asyncio.run(client.restart(ANN))
        assert answer == {"account": ANN, "restarted": "machine"}
        assert ann.stops == [True], "the machine was not powered off cleanly"
        assert ann.starts == 2 and ann.running(), "the machine did not start again"
        assert marker.read_text() == "still here", "a restart lost the disk"
        assert bob.stops == [] and bob.starts == 1, "someone else's machine was touched"


def test_restarting_a_machine_that_is_off_starts_it(tmp_path):
    import asyncio
    with vm_host(tmp_path / "vm") as (fleet, url):
        client = WorkstationClient(url, HOST_TOKEN)
        asyncio.run(client.ensure(ANN))
        fleet.machine_for(ANN).stop()
        answer = asyncio.run(client.restart(ANN))
        assert answer["restarted"] == "machine" and fleet.machine_for(ANN).running()
