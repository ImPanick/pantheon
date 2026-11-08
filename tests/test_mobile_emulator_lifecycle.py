# SPDX-License-Identifier: AGPL-3.0-or-later
"""The device uplift's lifecycle, tested without pretending to run Android.

Processes and adb answers are explicit fakes. Browser coverage lives in
test_mobile_emulator_in_a_browser.py; a KVM acceptance run is still required.
"""
from types import SimpleNamespace

import pytest

from workstation import phone as PH
from workstation import protocol as P
from workstation.agentd import Workstation, WorkstationError


class Process:
    returncode = 0
    alive = True

    def poll(self):
        return None if self.alive else self.returncode

    def wait(self, **kwargs):
        self.alive = False


def phone(tmp_path):
    system = SimpleNamespace(home=lambda account: tmp_path, uid=lambda account: 1234)
    p = PH.AccountPhone(system, "test", None)
    p.emulator = Process()
    p.state = "starting"
    return p


def test_power_on_cold_boots_with_android_animation_and_keeps_userdata():
    argv = PH.emulator_argv("emulator", "pixel_8", port=5586, memory_mib=2048)
    assert "-no-snapshot-load" in argv
    assert "-no-boot-anim" not in argv
    assert "-wipe-data" not in argv


def test_physical_power_can_start_an_off_device(tmp_path, monkeypatch):
    p = phone(tmp_path)
    p.emulator, p.state = None, "off"
    monkeypatch.setattr(p, "start", lambda: {"state": "starting"})
    assert p.button("power")["state"] == "starting"
    with pytest.raises(PH.PhoneError, match="off"):
        p.button("home")


def test_display_is_shown_before_android_reports_boot_complete(tmp_path, monkeypatch):
    p = phone(tmp_path)
    events, answers = [], iter(["", "1"])

    def adb(args, **kwargs):
        value = "running" if args[-1] == "init.svc.surfaceflinger" else next(answers)
        events.append(f"{args[-1]}:{value}")
        return value

    def show():
        events.append("display")
        p.scrcpy = Process()

    monkeypatch.setattr(p, "adb", adb)
    monkeypatch.setattr(p, "_show", show)
    monkeypatch.setattr(PH.time, "sleep", lambda seconds: None)
    p._boot(p.emulator)
    assert events.index("display") < events.index("sys.boot_completed:1")
    assert events.count("display") == 1
    assert p.state == "on" and p.boot_phase == "ready" and p.stream_ready()


def test_scrcpy_is_retried_if_android_cannot_show_it_yet(tmp_path, monkeypatch):
    p = phone(tmp_path)
    answers, attempts = iter(["", "1"]), []
    monkeypatch.setattr(p, "adb", lambda args, **kw: "running" if args[-1] == "init.svc.surfaceflinger" else next(answers))

    def show():
        attempts.append(True)
        if len(attempts) == 1:
            raise PH.PhoneError("unavailable", "Framework not ready")
        p.scrcpy = Process()

    monkeypatch.setattr(p, "_show", show)
    monkeypatch.setattr(PH.time, "sleep", lambda seconds: None)
    p._boot(p.emulator)
    assert len(attempts) == 2 and p.state == "on"


def test_a_cancelled_boot_worker_never_attaches_to_a_replacement(tmp_path, monkeypatch):
    p = phone(tmp_path)
    old = p.emulator
    p.emulator = Process()
    monkeypatch.setattr(p, "adb", lambda *args, **kw: pytest.fail("stale worker queried the new phone"))
    p._boot(old)
    assert p.scrcpy is None


def test_a_boot_timeout_releases_processes_display_and_port(tmp_path, monkeypatch):
    p = phone(tmp_path)
    events = []
    p.port = 5586
    p.scrcpy = Process()
    p.screen = SimpleNamespace(stop=lambda: events.append("screen"))
    p._release_port = lambda account: events.append("port")
    monkeypatch.setattr(PH, "BOOT_TIMEOUT_S", 0)
    monkeypatch.setattr(PH, "_kill", lambda proc: events.append("scrcpy"))
    monkeypatch.setattr(p, "adb", lambda *args, **kw: "")
    p._boot(p.emulator)
    assert events == ["scrcpy", "port", "screen"]
    assert p.emulator is None and p.scrcpy is None and p.port is None
    assert p.state == "unavailable" and "retry" in p.why


def test_rotation_and_folding_reshape_the_shared_live_screen(tmp_path, monkeypatch):
    p = phone(tmp_path)
    p.device, p.state, p.posture = "galaxy_z_fold6", "on", "open"
    calls, sizes = [], []
    monkeypatch.setattr(p, "adb", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(p, "_show", lambda: sizes.append(p.screen_size()))
    monkeypatch.setattr(p, "info", lambda action: {"action": action})
    p.rotate()
    p.set_posture("closed")
    assert calls == [["emu", "rotate"], ["emu", "fold"]]
    assert sizes == [PH.mobile_view_size(p.device, "open", 1), PH.mobile_view_size(p.device, "closed", 1)]
    assert sizes[0][0] > sizes[0][1] and sizes[1][0] > sizes[1][1]


def test_a_refused_rotation_does_not_advance_the_device_pose(tmp_path, monkeypatch):
    p = phone(tmp_path)
    p.state = "on"

    def refused(*args, **kwargs):
        raise PH.PhoneError("unavailable", "Command refused")

    monkeypatch.setattr(p, "adb", refused)
    with pytest.raises(PH.PhoneError, match="refused"):
        p.rotate()
    assert p.rotation == 0


def test_the_daemon_exposes_a_live_boot_stream_but_never_an_off_screen(tmp_path, monkeypatch):
    p = phone(tmp_path)
    p.scrcpy = Process()
    p.screen = SimpleNamespace(desktop_kind="kasmvnc")
    p.ensure_shown = lambda: None
    station = Workstation.__new__(Workstation)
    station.system = SimpleNamespace(ensure=lambda account: None)
    station.phones = SimpleNamespace(get=lambda account: p)
    station.holder = lambda account: {"holder": "agent"}
    assert station.phone_screen("test")["kind"] == "kasmvnc"
    p.state = "off"
    p.info = lambda: {"state": "off"}
    assert station.phone_screen("test")["kind"] is None
    with pytest.raises(WorkstationError):
        with station.phone_screen_upstream("test", "watch"):
            pytest.fail("off screen opened")


def test_the_route_keeps_active_shape_and_safe_boot_fields():
    from routes.workstation_routes import _phone_state
    state = _phone_state({"state": "starting", "device": "pixel_8", "mode": "android",
                          "screen": [1100, 494], "screen_is_active": True,
                          "stream_ready": True, "boot_phase": "android",
                          "devices": [{"id": "pixel_8", "width": -1, "height": "bad"}]})
    assert state["stream_ready"] and state["screen_is_active"]
    assert state["screen"] == [1100, 494] and state["boot_phase"] == "android"
    assert state["devices"][0]["width"] == P.PHONE_DEVICES["pixel_8"]["width"]
    assert _phone_state({"stream_ready": "yes", "boot_phase": "anything"})["stream_ready"] is False


def test_runtime_identity_follows_the_running_producer(tmp_path, monkeypatch):
    p = phone(tmp_path)
    p.mobile = SimpleNamespace(proc=Process())
    monkeypatch.setattr(p, "android_why", lambda: None)
    assert p.mode() == "mobile_view"  # capability changed; Firefox is still Firefox
    p.mobile = None
    monkeypatch.setattr(p, "android_why", lambda: "KVM capability changed")
    assert p.mode() == "android"  # the running Android remains Android


def test_final_display_failure_cleans_up_before_reporting_it(tmp_path, monkeypatch):
    p = phone(tmp_path)
    released = []
    p.port = 5586
    p._release_port = lambda account: released.append(account)
    monkeypatch.setattr(p, "adb", lambda *args, **kw: "1")

    def fail():
        raise PH.PhoneError("unavailable", "Display refused")

    monkeypatch.setattr(p, "_show", fail)
    p._boot(p.emulator)
    assert p.state == "unavailable" and p.why == "Display refused"
    assert p.emulator is None and p.port is None and released == ["test"]


def test_a_socket_request_recovers_a_dead_display_before_refusing(tmp_path, monkeypatch):
    p = phone(tmp_path)
    p.state = "on"
    p.screen = SimpleNamespace(desktop=lambda viewer: (9000, "authorization"))
    restored = []

    def recover():
        p.scrcpy = Process()
        restored.append(True)

    p.ensure_shown = recover
    sock = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr("workstation.agentd.socket.create_connection", lambda *args, **kw: sock)
    station = Workstation.__new__(Workstation)
    station.system = SimpleNamespace(ensure=lambda account: None)
    station.phones = SimpleNamespace(get=lambda account: p)
    with station.phone_screen_upstream("test", "watch") as (upstream, route, auth):
        assert upstream is sock and p.watchers == 1
    assert restored == [True] and p.watchers == 0


def test_an_obsolete_scrcpy_is_not_offered_as_an_installed_android(monkeypatch):
    monkeypatch.setattr(PH, "tools", lambda: {"adb": "adb", "emulator": "emulator", "scrcpy": "scrcpy"})
    monkeypatch.setattr(PH, "scrcpy_version", lambda path: (1, 25))
    assert not PH.tools_installed()
    monkeypatch.setattr(PH, "scrcpy_version", lambda path: (3, 3))
    assert PH.tools_installed()


def test_version_probes_are_cached_until_the_binary_changes(tmp_path, monkeypatch):
    import os
    binary = tmp_path / "scrcpy"
    binary.write_text("test binary")
    calls = []

    def run(*args, **kw):
        calls.append(True)
        return SimpleNamespace(stdout=b"scrcpy 3.3.4 <https://github.com/Genymobile/scrcpy>\n")

    monkeypatch.setattr(PH.subprocess, "run", run)
    assert PH.scrcpy_version(str(binary)) == (3, 3)
    assert PH.scrcpy_version(str(binary)) == (3, 3)
    assert calls == [True]
    stamp = binary.stat().st_mtime_ns + 1_000_000_000
    os.utime(binary, ns=(stamp, stamp))
    assert PH.scrcpy_version(str(binary)) == (3, 3)
    assert calls == [True, True]


@pytest.mark.parametrize("state", ["starting", "on"])
def test_live_screenshots_refresh_activity_while_booting_touch_waits(tmp_path, state):
    p = phone(tmp_path)
    p.state = state
    p.used_at = 0
    p.scrcpy = Process()
    p.screen = SimpleNamespace(width=494, height=1100, grab=lambda fmt: (b"png", "image/png"))
    station = Workstation.__new__(Workstation)
    station.system = SimpleNamespace(ensure=lambda account: None)
    station.phones = SimpleNamespace(get=lambda account: p)
    station.holder = lambda account: {"holder": "agent"}
    shot = station.phone("test", {"action": "screenshot"})
    assert shot["state"] == state and shot["mode"] == "android"
    assert p.used_at > 0
    assert shot["width"] == 494 and shot["data_b64"]
    if state == "starting":
        with pytest.raises(WorkstationError, match="booting"):
            station.phone("test", {"action": "input", "input": "click", "x": 1, "y": 1})


def test_an_agent_can_look_at_boot_without_treating_it_as_ready(monkeypatch):
    import asyncio
    import json
    from src.agent_tools.computer_tools import ComputerTool

    calls = []

    class Client:
        async def phone(self, account, action, **fields):
            calls.append(action)
            if action == "status":
                return {"state": "starting", "stream_ready": True, "mode": "android"}
            if action == "screenshot":
                return {"state": "starting", "mode": "android", "width": 494, "height": 1100,
                        "data_b64": "aGk=", "mime": "image/png"}
            pytest.fail("No marks or input should be requested while Android is booting")

    async def ready(owner):
        return SimpleNamespace(client=Client(), account="test")

    monkeypatch.setattr("src.workstation_access.ensure_ready", ready)
    tool = ComputerTool()
    result = asyncio.run(tool.execute(json.dumps({"action": "screenshot", "screen": "phone"}),
                                      {"owner": "mobile-test"}))
    assert calls == ["status", "screenshot"]
    assert result["images"] and result["screenshot_caption"] == "Phone booting"
    calls.clear()
    result = asyncio.run(tool.execute(json.dumps({"action": "click", "screen": "phone", "x": 1, "y": 1}),
                                      {"owner": "mobile-test"}))
    assert calls == ["status"] and "booting" in result["output"]
