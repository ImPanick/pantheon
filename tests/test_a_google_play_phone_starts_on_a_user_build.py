# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Google Play phone turns on, though its shell is not root.

Found on the owner's Windows host (2026-11-17): the Google APIs phone started,
but the Google Play phone "just hangs" and then says it failed to start. The
emulator log showed Android fully booted (boot completed, Play services
running), and the android-vm log showed nothing at all.

Google Play images are user builds. Their shell is uid 2000, never root, and
Android refuses some commands to it, among them `cmd wifi connect-network`.
After boot the native host joined the private Wi-Fi with that command; the
refusal was swallowed as "still booting" and the whole setup was retried
silently until the ten-minute deadline, which then said only "did not finish
booting". What is pinned:

  * a refused Wi-Fi connect is not retried; Android's own join is waited for;
  * a phone whose Wi-Fi never gets an address still turns on, without internet;
  * a refused finishing touch (screen size, stay awake) does not block the phone;
  * a step that keeps failing after boot is named in the failure, and logged.
"""
from __future__ import annotations

import logging
import time as real_time
from types import SimpleNamespace

from workstation.native_android import host as H
from workstation.native_android.adb import AdbError

REFUSED = AdbError("Android command did not complete: Exception occurred while executing "
                   "'connect-network': java.lang.SecurityException: Uid 2000 does not have access "
                   "to connect-network wifi command (or such command doesn't exist)")


class UserBuild:
    """`DirectAdb.shell` for a booted Google Play image."""

    def __init__(self, joins_by_itself_after=None, refuse=()):
        self.joins_after = joins_by_itself_after  # status asks before Android joins; None: never
        self.refuse = set(refuse)
        self.asked = []
        self.status_asks = 0

    def shell(self, args, **kw):
        args = list(args)
        self.asked.append(tuple(args))
        if args[:2] == ["getprop", "init.svc.surfaceflinger"]:
            return "running\n"
        if args[:2] == ["getprop", "sys.boot_completed"]:
            return "1\n"
        if args[:2] == ["getprop", "ro.adb.secure"]:
            return "1\n"
        if args[:3] == ["cmd", "wifi", "connect-network"]:
            raise REFUSED
        if tuple(args[:2]) in self.refuse:
            raise AdbError("Android command did not complete: Security exception: permission denied.")
        if args == ["cmd", "wifi", "status"]:
            self.status_asks += 1
            joined = self.joins_after is not None and self.status_asks > self.joins_after
            return "Wifi is enabled\n" + ("Wifi is connected to \"AndroidWifi\"\nIP: /10.0.2.16\n" if joined else "")
        return ""


def _phone(monkeypatch, tmp_path, guest, *, show=None):
    system = SimpleNamespace(config={"internet": True}, sdk=tmp_path / "sdk", abi="x86_64", why=None,
                             home=lambda _: tmp_path)
    phone = H.NativePhone(system, "owned", None)
    phone.state, phone.boot_phase = "starting", "emulator"
    phone.emulator = proc = SimpleNamespace(poll=lambda: None)
    phone.direct = guest
    monkeypatch.setattr(phone, "running", lambda: phone.emulator is not None)
    monkeypatch.setattr(phone, "_stop_locked", lambda: setattr(phone, "emulator", None))
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    def monotonic():
        now[0] += 0.01
        return now[0]
    monkeypatch.setattr(H, "time", SimpleNamespace(monotonic=monotonic, sleep=sleep, time=real_time.time))

    def shown():
        if show is not None:
            show()
        phone.control = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(phone, "_show", shown)
    return phone, proc, now


def test_a_refused_wifi_connect_waits_for_android_to_join_by_itself(tmp_path, monkeypatch):
    guest = UserBuild(joins_by_itself_after=15)
    phone, proc, now = _phone(monkeypatch, tmp_path, guest)
    phone._boot(proc)
    assert phone.state == "on" and phone.boot_phase == "ready"
    assert sum(a[:3] == ("cmd", "wifi", "connect-network") for a in guest.asked) == 1, "asked once, never retried"
    assert now[0] < 120, "no ten-minute silent retry"


def test_android_that_joins_quickly_is_not_asked_to_connect(tmp_path, monkeypatch):
    guest = UserBuild(joins_by_itself_after=2)
    phone, proc, _ = _phone(monkeypatch, tmp_path, guest)
    phone._boot(proc)
    assert phone.state == "on"
    assert not any(a[:3] == ("cmd", "wifi", "connect-network") for a in guest.asked)


def test_a_phone_without_a_wifi_address_still_turns_on(tmp_path, monkeypatch, caplog):
    guest = UserBuild(joins_by_itself_after=None)
    phone, proc, now = _phone(monkeypatch, tmp_path, guest)
    with caplog.at_level(logging.WARNING, logger=H.__name__):
        phone._boot(proc)
    assert phone.state == "on"
    assert now[0] < 120
    assert "starts without internet" in caplog.text


def test_a_refused_finishing_touch_does_not_block_the_phone(tmp_path, monkeypatch, caplog):
    guest = UserBuild(joins_by_itself_after=0, refuse=[("svc", "power"), ("wm", "scaling")])
    phone, proc, _ = _phone(monkeypatch, tmp_path, guest)
    with caplog.at_level(logging.WARNING, logger=H.__name__):
        phone._boot(proc)
    assert phone.state == "on"
    assert "svc power" in caplog.text and "wm scaling" in caplog.text


def test_a_step_that_keeps_failing_after_boot_is_named_and_logged(tmp_path, monkeypatch, caplog):
    def no_screen():
        raise H.PH.PhoneError("unavailable", "The phone's screen tool did not start.")
    guest = UserBuild(joins_by_itself_after=0)
    phone, proc, _ = _phone(monkeypatch, tmp_path, guest, show=no_screen)
    with caplog.at_level(logging.WARNING, logger=H.__name__):
        phone._boot(proc)
    assert phone.state == "unavailable"
    assert "screen tool did not start" in phone.why and "Start it again" in phone.why
    assert caplog.text.count("screen tool did not start") >= 2, "logged when it first failed, and at the end"
    assert caplog.text.count("startup step failed") == 1, "a repeated failure is logged once"
