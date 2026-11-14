# SPDX-License-Identifier: AGPL-3.0-or-later
"""Android routes use each person's VM, not the shared workstation host.

Both daemon HTTP hops, bearer-token checks, account routing and websocket
relays below are real. ``vm_fleet`` substitutes for QEMU/kernels; the phone
and display fixtures substitute for Android/KasmVNC. These tests do not prove
hypervisor isolation, nested KVM, Android boot or Google sign-in readiness.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers import vm_fleet
from workstation import protocol as P
from workstation import vm
from workstation.agentd import WorkstationError as DaemonError
ANN, BOB = account_for("android-ann"), account_for("android-bob")


def run(coro):
    return asyncio.run(coro)


def test_a_host_without_linux_device_apis_reports_the_kvm_blocker(tmp_path, monkeypatch):
    monkeypatch.delattr(vm.os, "mknod", raising=False)
    monkeypatch.delattr(vm.os, "makedev", raising=False)
    dev = tmp_path / "missing-kvm"
    accel, why = vm.choose_accel(dev)
    assert accel == "tcg" and "cannot make a Linux KVM device" in why
    assert not dev.exists()
    with pytest.raises(DaemonError) as error:
        vm.choose_accel(dev, want="kvm")
    assert error.value.code == "unavailable" and "Linux KVM device" in error.value.message


def test_existing_vm_gets_current_phone_installer_on_its_app_disk_without_touching_userdata(
        tmp_path, monkeypatch):
    payload = tmp_path / "payload"
    payload.mkdir()
    provision = payload / "provision.sh"
    provision.write_bytes(b"#!/bin/sh\nprintf 'old installer'\n")
    fleet = vm.Fleet(tmp_path / "host", accel="tcg", need_image=False, payload=payload)
    machine = vm.QemuMachine(fleet, ANN)
    machine.dir.mkdir(parents=True, exist_ok=True)
    machine.disk.write_bytes(b"persistent Android and desktop data")
    machine.token = "pws_this-guests-fixture-token"
    copied = []

    def inspect_disk(out, label, root, **kwargs):
        assert label == vm.APP_LABEL and kwargs["keep_modes"] is True
        assert (root / "token").read_text().strip() == machine.token
        assert (root / "workstation" / "phone.py").is_file()
        copied.append((root / "workstation" / "provision.sh").read_bytes())
        out.write_bytes(b"test ISO boundary")

    monkeypatch.setattr(vm, "make_iso", inspect_disk)
    machine._app_disk()
    provision.write_bytes(b"#!/bin/sh\nprintf 'updated checked installer'\n")
    machine._app_disk()
    assert copied == [b"#!/bin/sh\nprintf 'old installer'\n",
                      b"#!/bin/sh\nprintf 'updated checked installer'\n"]
    assert machine.disk.read_bytes() == b"persistent Android and desktop data"


@pytest.mark.skipif(sys.platform != "linux", reason="host filesystem descriptor checks are Linux")
@pytest.mark.parametrize("replace_while_chmod", [False, True])
def test_a_linked_or_replaced_project_export_never_changes_or_shares_its_target(
        tmp_path, monkeypatch, replace_while_chmod):
    root, foreign = tmp_path / "projects", tmp_path / "foreign"
    root.mkdir()
    foreign.mkdir(mode=0o700)
    (foreign / "secret").write_text("another user's fixture")
    folder = root / P.project_folder_of(ANN)
    monkeypatch.setenv(P.PROJECTS_DIR_ENV, str(root))
    if replace_while_chmod:
        folder.mkdir()
        real_chmod = os.fchmod

        def replace(fd, mode):
            folder.rename(root / "old-own-export")
            folder.symlink_to(foreign, target_is_directory=True)
            real_chmod(fd, mode)

        monkeypatch.setattr(vm.os, "fchmod", replace)
    else:
        folder.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(DaemonError) as error:
        vm.Fleet.project_share(object(), ANN)
    assert error.value.code == "unavailable" and "exported safely" in error.value.message
    assert foreign.stat().st_mode & 0o7777 == 0o700
    assert (foreign / "secret").read_text() == "another user's fixture"


class FixturePhone:
    """Only the boundary the real guest daemon talks to, no simulated OS."""

    def __init__(self, account, screen=None):
        self.account = account
        self.screen = screen
        self.calls = []
        self.state = "off"
        self._mode = "android"
        self.lock = threading.RLock()
        self.watchers = 0

    def info(self, action="status"):
        return {"ok": True, "action": action, "state": self.state, "mode": self._mode,
                "isolation": "per_user_vm",
                "fixture_owner": self.account}

    def start(self, device=None, **kwargs):
        self.calls.append(("start", device))
        self._mode = "android"
        self.state = "on"
        return self.info("start")

    def stop(self):
        self.calls.append(("stop",))
        self.state = "off"
        return self.info("stop")

    def preview(self, device=None):
        self.calls.append(("preview", device))
        self._mode = "mobile_view"
        self.state = "on"
        return self.info("preview")

    def mode(self):
        return self._mode

    def running(self):
        return self.state == "on"

    def ensure_shown(self):
        pass

    def stream_ready(self):
        return self.running() and self.screen is not None

    def touch(self):
        pass


class PhoneMachine(vm_fleet.InProcessMachine):
    """Separate real guest daemons, fixtures only at the Android boundary."""

    def start(self):
        if self.running():
            return
        super().start()
        self.phone = FixturePhone(self.account)
        # A forged account field in a body never chooses the guest or phone.
        self.server.station.phones.get = lambda account: self._phone_for(account)

    def _phone_for(self, account):
        assert account == self.account, "the host sent a request into the wrong machine"
        return self.phone


def _request(url, path, token=None, body=None):
    parts = urlsplit(url)
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    try:
        connection.request("POST" if body is not None else "GET", path,
                           body=json.dumps(body).encode() if body is not None else None,
                           headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_phone_mutations_and_screen_status_reach_only_the_owners_guest(tmp_path):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
        run(client.ensure(ANN))
        run(client.ensure(BOB))
        assert run(client.phone(ANN, "status"))["fixture_owner"] == ANN
        assert run(client.phone(BOB, "status"))["fixture_owner"] == BOB
        assert run(client.phone(ANN, "start", device=P.PHONE_DEFAULT_DEVICE))["state"] == "on"
        ann, bob = fleet.machine_for(ANN), fleet.machine_for(BOB)
        assert ann.phone.calls == [("start", P.PHONE_DEFAULT_DEVICE)]
        assert bob.phone.calls == [] and bob.phone.state == "off"
        assert run(client.phone_screen(ANN))["kind"] is None
        assert run(client.phone(ANN, "stop"))["state"] == "off"
        assert ann.phone.calls[-1] == ("stop",) and bob.phone.calls == []
        assert ann.token != bob.token != vm_fleet.HOST_TOKEN


def test_looking_at_a_stopped_phone_never_starts_or_provisions_its_vm(tmp_path):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
        status = run(client.phone(ANN, "status"))
        machine = fleet.machine_for(ANN)
        assert status["state"] == "off" and status["capability"] == "unknown"
        assert status["isolation"] == "per_user_vm" and status["can_start"] is True
        assert not ({"installed", "device", "edition"} & status.keys())
        assert run(client.phone_screen(ANN))["kind"] is None
        assert not machine.running() and not machine.exists() and machine.starts == 0

        async def unavailable_stream():
            async with client.phone_screen_stream(ANN, "person"):
                pytest.fail("a stopped VM acquired a stream")

        with pytest.raises(WorkstationError) as error:
            run(unavailable_stream())
        assert error.value.code == "unavailable" and "VM is off" in error.value.message
        assert not machine.running() and machine.starts == 0


def test_outer_tcg_is_a_definite_android_blocker_without_booting_a_guest(tmp_path):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        fleet.accel = "tcg"
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
        status = run(client.phone(ANN, "status"))
        assert status["state"] == "unavailable" and status["can_start"] is False
        assert status["mode"] is None and status["stream_ready"] is False
        assert "TCG" in status["why"] and "/dev/kvm" in status["why"]
        machine = fleet.machine_for(ANN)
        for action, fields in [("start", {}), ("install", {}), ("transfer", {}),
                               ("edition", {"edition": "google_play"}),
                               ("button", {"button": "power"}), ("rotate", {})]:
            with pytest.raises(WorkstationError) as error:
                run(client.phone(ANN, action, **fields))
            assert error.value.code == "unavailable" and "TCG" in error.value.message
        assert run(client.phone(ANN, "stop"))["state"] == "off"
        assert not machine.running() and not machine.exists() and machine.starts == 0


def test_existing_android_on_tcg_cannot_claim_ready_stream_or_accept_mutations(tmp_path):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
        run(client.phone(ANN, "start"))
        run(client.write(ANN, ".android/avd/kept.txt", "existing device data"))
        machine = fleet.machine_for(ANN)
        fleet.accel = "tcg"
        status = run(client.phone(ANN, "status"))
        assert status["state"] == "unavailable" and status["mode"] is None
        assert status["available"] is False and status["stream_ready"] is False
        screen = run(client.phone_screen(ANN))
        assert screen["kind"] is None and "TCG" in screen["why"]

        async def no_stream():
            async with client.phone_screen_stream(ANN, "person"):
                pytest.fail("outer TCG was offered as an accelerated Android producer")

        with pytest.raises(WorkstationError) as error:
            run(no_stream())
        assert "TCG" in error.value.message
        for action in ("start", "install", "rotate", "posture", "button", "device",
                       "input", "transfer", "marks", "screenshot", "open_url", "edition"):
            with pytest.raises(WorkstationError):
                run(client.phone(ANN, action))
        assert machine.phone.calls == [("start", None)]
        assert run(client.phone(ANN, "stop"))["state"] == "off"
        assert run(client.read(ANN, ".android/avd/kept.txt"))["data"] == b"existing device data"


def test_explicit_preview_remains_a_preview_on_outer_tcg(tmp_path):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        fleet.accel = "tcg"
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
        assert run(client.phone(ANN, "preview"))["mode"] == "mobile_view"
        assert run(client.phone(ANN, "status"))["mode"] == "mobile_view"
        machine = fleet.machine_for(ANN)
        # These are rewritten to preview/stop, so a concurrent preview closure
        # cannot turn either into an Android start in the guest.
        assert run(client.phone(ANN, "device", device=P.PHONE_DEFAULT_DEVICE))["mode"] == "mobile_view"
        assert machine.phone.calls[-1] == ("preview", P.PHONE_DEFAULT_DEVICE)
        assert run(client.phone(ANN, "button", button="power"))["state"] == "off"
        assert machine.phone.calls[-1] == ("stop",)
        assert not any(call[0] == "start" for call in machine.phone.calls)


def test_an_account_in_the_body_cannot_reroute_a_phone_to_someone_else(tmp_path):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        _, path = P.route_path("phone", ANN)
        status, answer = _request(url, path, vm_fleet.HOST_TOKEN,
                                  {"action": "start", "account": BOB, "owner": BOB,
                                   "device": P.PHONE_DEFAULT_DEVICE})
        assert (status, answer["fixture_owner"]) == (200, ANN)
        assert ANN in fleet._machines and BOB not in fleet._machines
        assert fleet.machine_for(ANN).phone.calls == [("start", P.PHONE_DEFAULT_DEVICE)]


@pytest.mark.parametrize("route", ["phone", "phone_screen", "read"])
@pytest.mark.parametrize("credential", ["other-guest", "host", "missing"])
def test_a_stolen_guest_token_cannot_access_another_guests_phone_or_files(
        tmp_path, route, credential):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
        run(client.ensure(ANN))
        run(client.ensure(BOB))
        ann, bob = fleet.machine_for(ANN), fleet.machine_for(BOB)
        token = {"other-guest": ann.token, "host": vm_fleet.HOST_TOKEN,
                 "missing": None}[credential]
        guest_url = f"http://127.0.0.1:{bob.port}"
        _, path = P.route_path(route, BOB)
        body = ({"action": "start"} if route == "phone" else
                {"path": ".android/private.txt"} if route == "read" else None)
        status, answer = _request(guest_url, path, token, body)
        assert (status, answer["error"]) == (401, "unauthorized")
        assert bob.phone.calls == [], "a rejected caller changed the phone"


def test_a_guest_token_cannot_reach_the_host_router_or_other_guests_files(tmp_path):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
        run(client.ensure(ANN))
        run(client.write(BOB, ".android/private.txt", "bob-device-data"))
        ann, bob = fleet.machine_for(ANN), fleet.machine_for(BOB)
        _, phone_path = P.route_path("phone", BOB)
        status, answer = _request(url, phone_path, ann.token, {"action": "start"})
        assert (status, answer["error"]) == (401, "unauthorized")
        _, read_path = P.route_path("read", BOB)
        # Even a guessed Bob account path on Alice's daemon addresses only a
        # shadow account in Alice's filesystem, never Bob's actual machine.
        status, answer = _request(f"http://127.0.0.1:{ann.port}", read_path, ann.token,
                                  {"path": ".android/private.txt"})
        assert (status, answer["error"]) == (404, "not_found")
        assert run(client.read(BOB, ".android/private.txt"))["data"] == b"bob-device-data"
        assert bob.phone.calls == []


def test_qemu_exposes_only_the_authenticated_guest_daemon_not_android_ports(tmp_path):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
        for account in (ANN, BOB):
            run(client.ensure(account))
            machine = fleet.machine_for(account)
            netdev = machine.argv[machine.argv.index("-netdev") + 1]
            assert netdev == (f"user,id=net0,hostfwd=tcp:127.0.0.1:{machine.port}"
                              f"-:{P.DEFAULT_PORT}")
            assert netdev.count("hostfwd=") == 1


@pytest.mark.parametrize("job", ["installing", "starting"])
def test_watching_a_phone_job_keeps_its_vm_alive_until_the_job_finishes(tmp_path, job):
    with vm_fleet.vm_host(tmp_path / "host", factory=PhoneMachine) as (fleet, url):
        seconds = [0.0]
        fleet._clock = lambda: seconds[0]
        fleet.idle_stop_s = 10.0
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
        run(client.ensure(ANN))
        machine = fleet.machine_for(ANN)
        machine.phone.state = job
        seconds[0] = 12.0
        assert fleet._idle(ANN)
        assert run(client.phone(ANN, "status"))["state"] == job
        assert fleet.reap_idle() == [] and machine.running()
        machine.phone.state = "off"
        seconds[0] = 24.0
        run(client.phone(ANN, "status"))
        assert fleet.reap_idle() == [ANN]
        assert machine.exists(), "Idle shutdown must retain this user's disk/home"


class FixturePhoneScreen:
    """Kasm login behavior; intentionally no X server or filesystem identity."""

    desktop_kind = "kasmvnc"

    def __init__(self, kasm, root: Path, account):
        from workstation.ubuntu import DesktopLogins

        self.kasm = kasm
        self.logins = DesktopLogins(root / account / "phone-kasmpasswd", 0)
        self.logins.path.parent.mkdir(parents=True)
        self.set_driver(False)
        kasm.files[account] = self.logins.path

    def set_driver(self, driving):
        # The real Linux mode/owner checks have their own tests; this fixture
        # writes only disposable login text, so it also runs on Windows.
        self.logins.path.write_text(self.logins.text(driving), encoding="ascii")

    def desktop(self, viewer):
        return self.kasm.port, self.logins.authorization(viewer)


@pytest.mark.skipif(sys.platform != "linux", reason="the Kasm login fixture imports the Linux display")
@pytest.mark.parametrize("host_accel", ["kvm", "tcg"])
def test_phone_stream_uses_guest_token_and_stays_in_use_until_viewer_leaves(tmp_path, host_accel):
    from test_the_workstation_desktop_is_live import FakeKasm

    kasm = FakeKasm()

    class StreamingPhoneMachine(PhoneMachine):
        def start(self):
            super().start()
            self.phone.screen = FixturePhoneScreen(kasm, self.dir, self.account)
            self.phone.state = "on"
            self.system.phone_display = lambda account: self._phone_for(account).screen

    try:
        with vm_fleet.vm_host(tmp_path / "host", factory=StreamingPhoneMachine) as (fleet, url):
            fleet.accel = host_accel
            client = WorkstationClient(url, vm_fleet.HOST_TOKEN, android_vm_endpoint=True)
            run(client.ensure(ANN))
            if host_accel == "tcg":
                run(client.phone(ANN, "preview"))
            assert run(client.phone_screen(ANN)) == {"kind": "kasmvnc", "holder": "agent"}

            async def stream():
                async with client.phone_screen_stream(ANN, "person") as socket:
                    await socket.send(b"who")
                    watching = await socket.recv()
                    busy = fleet._use[ANN][0]
                    await client.control(ANN, "person")
                    await socket.send(b"who")
                    driving = await socket.recv()
                    await client.control(ANN, "agent")
                    await socket.send(b"who")
                    return watching, busy, driving, await socket.recv()

            watching, busy, driving, handed_back = run(stream())
            assert (watching, driving, handed_back) == (b"person:r", b"person:rw", b"person:r")
            assert busy >= 1
            # The display receives only its Basic login, neither daemon token.
            token = fleet.machine_for(ANN).token
            assert all(vm_fleet.HOST_TOKEN not in value and token not in value
                       for headers in kasm.seen for value in headers.values())
    finally:
        kasm.close()
