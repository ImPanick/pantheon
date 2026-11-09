# SPDX-License-Identifier: AGPL-3.0-or-later
"""A cached phone display outlives a manager's individual phone handles.

Real manager/phone methods and threads drive the ownership races. Firefox,
Android, BiDi and the display are fixtures: these tests establish lifecycle
ordering, not Android boot, KVM or isolation between real virtual machines.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest

from workstation import phone as PH

ACCOUNT = "fixture-phone"


class Task:
    def __init__(self, call):
        self.error = None
        self.value = None
        self.done = threading.Event()

        def work():
            try:
                self.value = call()
            except BaseException as error:
                self.error = error
            finally:
                self.done.set()

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()


class Process:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def wait(self, **kwargs):
        self.alive = False


def settled(phone, state="on"):
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        if phone.state == state:
            return
        time.sleep(.005)
    pytest.fail(f"Phone remained {phone.state}, expected {state}: {phone.why}")


def lease_is_free(phone):
    acquired = phone._mobile_lifecycle.acquire(blocking=False)
    if acquired:
        phone._mobile_lifecycle.release()
    return acquired


@pytest.fixture
def manager(tmp_path, monkeypatch):
    plans, instances, events, handles = deque(), [], [], []

    class Screen:
        desktop_kind = "kasmvnc"
        width, height = 400, 800
        active = None

        def set_size(self, size):
            self.width, self.height = size

        def stop(self):
            events.append(("screen-stop", self.active))
            self.active = None

    screen = Screen()  # the system caches the same screen across stop/get

    class Mobile:
        def __init__(self, *args, **kwargs):
            self.blocked = plans.popleft() if plans else False
            self.entered, self.release, self.cancelled = (
                threading.Event(), threading.Event(), threading.Event())
            self.proc = None
            self.stops = 0
            self.screen = kwargs["screen"]
            instances.append(self)

        def start(self, *, cancel=None):
            events.append(("start", self))
            self.entered.set()
            if self.blocked:
                # Deliberately noncooperative: the old call returns after a
                # replacement handle already exists, exercising stale cleanup.
                assert self.release.wait(4), "fixture old producer was never released"
            self.proc = Process()
            self.screen.active = self

        def cancel_start(self):
            self.cancelled.set()

        def stop(self):
            events.append(("stop", self))
            self.stops += 1
            if self.proc:
                self.proc.alive = False
            self.proc = None

        def _ctx(self):
            return "fixture-context"

        def _call(self, *args, **kwargs):
            return {}

    def ensure(account):
        home = tmp_path / account
        home.mkdir(exist_ok=True)
        return {"home": str(home)}

    system = SimpleNamespace(backend="vm", ensure=ensure, home=lambda a: tmp_path / a,
                             uid=lambda a: 12000, phone_display=lambda a: screen,
                             files_as=lambda a: contextlib.nullcontext(),
                             run_as=lambda a, **kw: ([], dict(os.environ)))
    monkeypatch.setenv(PH.IDLE_ENV, "0")
    monkeypatch.setattr(PH, "MobileView", Mobile)
    monkeypatch.setattr(PH, "tools_installed", lambda: False)
    monkeypatch.setattr(PH, "license_accepted", lambda: False)
    monkeypatch.setattr(PH, "_listening", lambda port: False)
    monkeypatch.setattr(PH.AccountPhone, "android_why", lambda self: None)
    monkeypatch.setattr(PH.AccountPhone, "mobile_why", lambda self: None)
    monkeypatch.setattr(PH.AccountPhone, "installed", lambda self, device=None: True)
    monkeypatch.setattr(PH.AccountPhone, "_edition_accepted", lambda self: True)
    phones = PH.Phones(system)

    def get():
        phone = phones.get(ACCOUNT)
        handles.append(phone)
        return phone

    def preview(phone, blocked=False):
        plans.append(blocked)
        before = len(instances)
        phone.preview()
        assert len(instances) == before + 1
        return instances[-1], phone._booting

    yield SimpleNamespace(phones=phones, get=get, preview=preview,
                          screen=screen, events=events, instances=instances)
    for instance in instances:
        instance.release.set()
    for phone in handles:
        phone.stop()
    for phone in handles:
        if phone._booting:
            phone._booting.join(2)


@pytest.mark.parametrize("all_accounts", [False, True], ids=["stop", "stop-all"])
def test_evicted_phone_cleanup_finishes_before_replacement_uses_the_same_display(manager, all_accounts):
    old = manager.get()
    first, first_worker = manager.preview(old, blocked=True)
    assert first.entered.wait(1)
    stop = Task(manager.phones.stop_all if all_accounts else lambda: manager.phones.stop(ACCOUNT))
    assert stop.done.wait(.5), "Manager stop waited for the old browser's startup"
    assert stop.error is None
    new = manager.get()
    assert new is not old and new.screen is old.screen
    second, second_worker = manager.preview(new)
    assert not second.entered.wait(.05), "New handle bypassed the old display owner's teardown"
    first.release.set()
    first_worker.join(1)
    assert not first_worker.is_alive() and second.entered.wait(1)
    settled(new)
    assert manager.screen.active is second and second.stops == 0
    assert manager.events.index(("stop", first)) < manager.events.index(("start", second))
    assert ("screen-stop", first) in manager.events[
        manager.events.index(("stop", first)):manager.events.index(("start", second))]
    # A previously captured handle cannot start orphan sessions or close the
    # replacement's cached display after its own teardown has finished.
    for call in (old.preview, old.start, old.install, lambda: old.select_edition("standard"),
                 lambda: old.button("power")):
        with pytest.raises(PH.PhoneError, match="replaced"):
            call()
    before = list(manager.events)
    old.stop()
    assert manager.events == before and manager.screen.active is second
    assert new.running() and second_worker.is_alive()


def test_android_start_is_refused_until_old_preview_releases_the_manager_display(manager, monkeypatch):
    old = manager.get()
    browser, worker = manager.preview(old, blocked=True)
    assert browser.entered.wait(1)
    manager.phones.stop(ACCOUNT)
    new = manager.get()
    launched = []

    def launch():
        launched.append(True)
        new.emulator, new.state = Process(), "on"
        return new.info("start")

    monkeypatch.setattr(new, "_launch_android", launch)
    monkeypatch.setattr(new, "adb", lambda *a, **kw: "")
    with pytest.raises(PH.PhoneError) as error:
        new.start()
    assert error.value.code == "busy" and launched == []
    browser.release.set()
    worker.join(1)
    assert not worker.is_alive()
    assert new.start()["state"] == "on" and launched == [True]
    assert not lease_is_free(new), "Android did not retain its display ownership"
    new.stop()
    assert lease_is_free(new)


def test_concurrent_get_and_android_release_do_not_wait_on_the_manager_lock(manager, monkeypatch):
    old = manager.get()
    waiting, release = threading.Event(), threading.Event()

    class SlowProcess(Process):
        def wait(self, **kwargs):
            waiting.set()
            assert release.wait(2), "fixture Android stop was never released"
            self.alive = False

    def launch():
        old.port = old._claim_port(ACCOUNT)
        old.emulator, old.state = SlowProcess(), "on"
        return old.info("start")

    monkeypatch.setattr(old, "_launch_android", launch)
    monkeypatch.setattr(old, "adb", lambda *a, **kw: "")
    old.start()
    stopped = Task(lambda: manager.phones.stop(ACCOUNT))
    assert waiting.wait(1)
    try:
        getting = Task(manager.get)
        assert getting.done.wait(.3), "Slow Android stop held the manager's global lock"
        assert getting.error is None and getting.value is not old
        with pytest.raises(PH.PhoneError) as error:
            getting.value.start()
        assert error.value.code == "busy"
    finally:
        release.set()
    assert stopped.done.wait(1), "The release callback deadlocked acquiring the manager lock"
    assert stopped.error is None and manager.phones._ports == {}
    assert lease_is_free(getting.value)


@pytest.mark.parametrize("phase", ["configuration", "boot"])
def test_failed_android_start_or_boot_releases_the_shared_display_and_port(manager, monkeypatch, phase):
    phone = manager.get()
    monkeypatch.setattr(phone, "adb", lambda *a, **kw: "")
    if phase == "configuration":
        def bad_config():
            raise OSError("fixture disk configuration failed")
        monkeypatch.setattr(phone, "_write_avd", bad_config)
        with pytest.raises(PH.PhoneError, match="preserved"):
            phone.start()
    else:
        def launch():
            phone.port = phone._claim_port(ACCOUNT)
            phone.emulator, phone.state = Process(), "starting"
            return phone.info("start")
        monkeypatch.setattr(phone, "_launch_android", launch)
        monkeypatch.setattr(PH, "BOOT_TIMEOUT_S", 0)
        phone.start()
        phone._boot(phone.emulator)
        assert phone.state == "unavailable"
    assert phone.port is None and phone.emulator is None
    assert manager.phones._ports == {} and lease_is_free(phone)


def test_failed_graceful_adb_stop_kills_its_captured_emulator_before_releasing_the_lease(
        manager, monkeypatch, caplog):
    phone = manager.get()
    order = []
    proc = Process()

    def launch():
        phone.port = phone._claim_port(ACCOUNT)
        phone.emulator, phone.state = proc, "on"
        return phone.info("start")

    def no_adb(*args, **kwargs):
        raise PH.PhoneError("unavailable", "fixture SDK was removed")

    def kill(captured):
        assert captured is proc and not lease_is_free(phone)
        order.append("kill")
        captured.alive = False

    real_release = phone._release_port

    def released(account):
        assert proc.poll() is not None and not lease_is_free(phone)
        order.append("release")
        real_release(account)

    monkeypatch.setattr(phone, "_launch_android", launch)
    monkeypatch.setattr(phone, "adb", no_adb)
    monkeypatch.setattr(PH, "_kill", kill)
    monkeypatch.setattr(phone, "_release_port", released)
    phone.start()
    manager.phones.stop(ACCOUNT)
    assert order == ["kill", "release"]
    assert "graceful ADB stop failed" in caplog.text
    assert phone.emulator is None and manager.phones._ports == {} and lease_is_free(phone)
    replacement = manager.get()
    browser, _ = manager.preview(replacement)
    assert browser.entered.wait(1)
    settled(replacement)


def test_unreaped_android_keeps_its_display_and_port_reserved(manager, monkeypatch):
    phone = manager.get()

    class StuckProcess(Process):
        def wait(self, **kwargs):
            if self.alive:
                raise subprocess.TimeoutExpired("fixture emulator", kwargs.get("timeout", 0))

    proc = StuckProcess()

    def launch():
        phone.port = phone._claim_port(ACCOUNT)
        phone.emulator, phone.state = proc, "on"
        return phone.info("start")

    monkeypatch.setattr(phone, "_launch_android", launch)
    monkeypatch.setattr(phone, "adb", lambda *a, **kw: "")
    monkeypatch.setattr(PH, "_kill", lambda captured: None)  # explicit failed process-kill fixture
    phone.start()
    try:
        with pytest.raises(PH.PhoneError, match="remains reserved"):
            manager.phones.stop(ACCOUNT)
        assert phone.emulator is proc and phone.port is not None
        assert manager.phones._ports and not lease_is_free(phone)
        replacement = manager.get()
        with pytest.raises(PH.PhoneError) as error:
            replacement.start()
        assert error.value.code == "busy"
    finally:
        proc.alive = False  # release the fixture for deterministic teardown
        phone.stop()
