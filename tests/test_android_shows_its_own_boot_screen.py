# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone shows Android's own boot screen, live, from the first frame
Android draws — not a sentence until boot has finished.

The owner, 2026-11-15: *"instead of "booting up your phone" we put an actual
"Android Boot" splash-gif to show the android device *actually* starting"*.
No copy of Google's animation is shipped: the device draws its own, and the
viewer streams it. The VM backend's phone already attaches its screen once
SurfaceFlinger runs (`AccountPhone._boot`); the native host (macOS and
Windows launchers) waited for `sys.boot_completed`. What is pinned:

  * the native host's display is live once SurfaceFlinger runs, while the
    phone is still `starting`, and only after Android said its ADB is private;
  * the control channel still attaches at boot completion, and input is
    ignored until it has, rather than ending the stream;
  * until the display is up, Android is asked twice a second, not every 2 s;
  * a stop forgets the boot display;
  * no emulator argv hides the boot animation.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from workstation import phone as PH
from workstation.native_android import host as H


class Guest:
    """`DirectAdb.shell`, answering from a script of boot moments."""

    def __init__(self, moments, secure="1"):
        self.moments, self.secure, self.at = list(moments), secure, 0
        self.asked = []

    def now(self):
        return self.moments[min(self.at, len(self.moments) - 1)]

    def shell(self, args, **kw):
        self.asked.append(tuple(args))
        if args[:2] == ["getprop", "init.svc.surfaceflinger"]:
            return "running\n" if self.now() in ("display", "done") else "\n"
        if args[:2] == ["getprop", "sys.boot_completed"]:
            return "1\n" if self.now() == "done" else "\n"
        if args[:2] == ["getprop", "ro.adb.secure"]:
            return self.secure + "\n"
        return ""


def _phone(tmp_path, monkeypatch, guest):
    system = SimpleNamespace(config={}, sdk=tmp_path / "sdk", abi="x86_64", why=None,
                             home=lambda _: tmp_path)
    phone = H.NativePhone(system, "owned", None)
    phone.state, phone.boot_phase = "starting", "emulator"
    phone.emulator = proc = SimpleNamespace(poll=lambda: None)
    phone.direct = guest
    monkeypatch.setattr(phone, "running", lambda: phone.emulator is not None)
    seen = []

    def sleep(s):
        seen.append((guest.now(), s, phone.stream_ready(), phone.state, phone.boot_phase))
        guest.at += 1
    monkeypatch.setattr(H.time, "sleep", sleep)

    def show():
        phone.control = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(phone, "_show", show)
    return phone, proc, seen


def test_the_display_is_live_while_android_boots(tmp_path, monkeypatch):
    guest = Guest(["kernel", "kernel", "display", "display", "done"])
    phone, proc, seen = _phone(tmp_path, monkeypatch, guest)
    phone._boot(proc)
    assert [s[2] for s in seen] == [False, False, True, True]
    assert seen[2][3:] == ("starting", "android"), "still booting, and showing it"
    assert phone.control is not None and phone.state == "on" and phone.boot_phase == "ready"


def test_android_is_asked_often_until_its_display_is_up(tmp_path, monkeypatch):
    guest = Guest(["kernel", "kernel", "display", "display", "done"])
    phone, proc, seen = _phone(tmp_path, monkeypatch, guest)
    phone._boot(proc)
    assert [s[1] for s in seen[:2]] == [0.5, 0.5]
    assert all(s[1] <= 2 for s in seen)


def test_an_android_without_private_adb_shows_nothing(tmp_path, monkeypatch):
    guest = Guest(["display", "done"], secure="0")
    phone, proc, seen = _phone(tmp_path, monkeypatch, guest)
    stopped = []
    monkeypatch.setattr(phone, "_stop_locked", lambda: stopped.append(True))
    phone._boot(proc)
    assert stopped == [True] and phone.state == "unavailable"
    assert "private ADB" in phone.why
    assert not any(s[2] for s in seen)


def test_the_private_adb_check_comes_before_the_first_frame(tmp_path, monkeypatch):
    guest = Guest(["display", "done"])
    phone, proc, _ = _phone(tmp_path, monkeypatch, guest)
    phone._boot(proc)
    asked = [a[1] for a in guest.asked if a[0] == "getprop"]
    assert asked.index("ro.adb.secure") < asked.index("sys.boot_completed")


def test_a_touch_during_boot_is_ignored_not_fatal(tmp_path, monkeypatch):
    from workstation.native_android.screen import Screen
    guest = Guest(["display"])
    phone, _, _ = _phone(tmp_path, monkeypatch, guest)
    phone.boot_display = True
    screen = Screen(phone)
    screen.size = screen.physical = (100, 200)
    event = {"kind": "pointer", "buttons": 1, "x": 3, "y": 4, "scroll_x": 0, "scroll_y": 0,
             "geometry": (phone.generation, screen.size, screen.physical)}
    assert screen.rfb_event(event, "s", lambda: "person") is None


def test_a_stopped_phone_forgets_its_boot_display(tmp_path, monkeypatch):
    guest = Guest(["display"])
    phone, _, _ = _phone(tmp_path, monkeypatch, guest)
    phone.boot_display = True
    monkeypatch.setattr(phone, "_process_family", lambda: [])
    monkeypatch.setattr(phone, "_release", lambda: None)
    phone.emulator = None
    phone._stop_locked()
    assert phone.boot_display is False


@pytest.mark.parametrize("hides", ["-no-boot-anim", "-no-window-boot-anim"])
def test_no_emulator_hides_the_boot_animation(hides):
    argv = PH.emulator_argv("emulator", "pixel_9", port=5554, memory_mib=8192)
    assert hides not in argv
