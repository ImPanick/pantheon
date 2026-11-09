# SPDX-License-Identifier: AGPL-3.0-or-later
"""A new app must not expose an old, shared-account Android daemon.

Most cases record the HTTP/socket boundary before anything can be sent. The
legacy integration case runs the real agentd HTTP/auth layer and substitutes
only its old phone producer. No case runs Android or proves VM isolation.
"""
from __future__ import annotations

import asyncio
import copy

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from src import workstation_client as WC
from tests.helpers.workstation_daemon import running_workstation
from workstation import protocol as P


ACCOUNT = account_for("client-isolation")
LEGACY_ANDROID = {"available": True, "state": "on", "mode": "android", "installed": True,
                  "stream_ready": True, "accel": "kvm"}
LEGACY_PREVIEW = {**LEGACY_ANDROID, "mode": "mobile_view"}
SHARED_OFF = {"available": False, "state": "off", "mode": None, "isolation": "shared",
              "preview_available": True}
SHARED_PREVIEW = {**SHARED_OFF, "available": True, "state": "on", "mode": "mobile_view"}
VM_ANDROID = {**LEGACY_ANDROID, "isolation": "per_user_vm"}
VM_STOPPED = {"available": False, "state": "off", "mode": None, "isolation": "per_user_vm",
              "can_start": True, "capability": "unknown"}
UNSAFE_ACTIONS = [
    ("start", {}), ("install", {"accept_license": True}), ("edition", {"edition": "google_play"}),
    ("transfer", {"name": "private.txt", "data_b64": "eA=="}),
    ("screenshot", {}), ("input", {"input": "click", "x": 1, "y": 1}), ("marks", {}),
]


def run(coro):
    return asyncio.run(coro)


class RecordingClient(WorkstationClient):
    def __init__(self, status, *, android_vm_endpoint=False):
        super().__init__("http://127.0.0.1:7040", "pws_client-fixture", timeout=1,
                         android_vm_endpoint=android_vm_endpoint)
        self.status = copy.deepcopy(status)
        self.calls = []

    async def _call(self, name, account=None, body=None, **kwargs):
        self.calls.append((name, account, copy.deepcopy(body)))
        if name == "phone_screen":
            return {"kind": "kasmvnc", "holder": "person"}
        if name != "phone":
            pytest.fail("The phone client called an unrelated HTTP route")
        answer = copy.deepcopy(self.status)
        if body["action"] == "preview":
            answer.update(mode="mobile_view", state="on", available=True)
        elif body["action"] == "stop":
            answer.update(state="off", mode=None)
        return answer

    def mutations(self):
        return [body for name, _, body in self.calls
                if name == "phone" and body and body.get("action") != "status"]


@pytest.mark.parametrize("isolation", [None, "shared", "vm", True, ["per_user_vm"], "per_user_vm"])
def test_unsafe_android_status_is_unavailable_even_when_old_runtime_claims_kvm(isolation):
    old = {**LEGACY_ANDROID, "isolation": isolation}
    client = RecordingClient(old)
    answer = run(client.phone(ACCOUNT, "status"))
    assert answer["available"] is False and answer["state"] == "unavailable"
    assert answer.get("mode") is None and answer.get("stream_ready") is not True
    assert answer.get("can_start") is not True and answer.get("why")
    assert not client.mutations()


@pytest.mark.parametrize("holder", ["agent", "person"])
@pytest.mark.parametrize("action,fields", UNSAFE_ACTIONS)
def test_no_unsafe_action_reaches_an_old_android_daemon(action, fields, holder):
    client = RecordingClient(LEGACY_ANDROID)
    with pytest.raises(WorkstationError) as error:
        run(client.phone(ACCOUNT, action, holder=holder, **fields))
    assert error.value.code == "unavailable"
    assert not client.mutations()
    assert client.calls and all(name == "phone" and body["action"] == "status"
                                for name, _, body in client.calls)


@pytest.mark.parametrize("action,fields", UNSAFE_ACTIONS)
def test_legacy_preview_metadata_cannot_race_into_an_unisolated_android(action, fields):
    # Old preview mode is not a capability guarantee: another old client or
    # shared-root account could switch it to Android after the status read.
    client = RecordingClient(LEGACY_PREVIEW)
    with pytest.raises(WorkstationError) as error:
        run(client.phone(ACCOUNT, action, **fields))
    assert error.value.code == "unavailable" and not client.mutations()


@pytest.mark.parametrize("status", [LEGACY_ANDROID, LEGACY_PREVIEW, VM_ANDROID])
def test_unsafe_screen_lookup_never_asks_for_a_display(status):
    client = RecordingClient(status)
    answer = run(client.phone_screen(ACCOUNT))
    assert answer.get("kind") is None and not answer.get("client")
    assert all(name != "phone_screen" for name, _, _ in client.calls)


@pytest.mark.parametrize("status", [LEGACY_ANDROID, LEGACY_PREVIEW, VM_ANDROID])
@pytest.mark.parametrize("entry", ["phone", "direct"])
def test_neither_stream_entrypoint_reaches_socket_setup_for_an_unsafe_runtime(monkeypatch, status, entry):
    client = RecordingClient(status)
    wire = []

    async def forbidden_wire():
        wire.append("token/TLS setup")
        pytest.fail("Unsafe phone stream reached socket/token setup")

    monkeypatch.setattr(client, "_wire", forbidden_wire)

    async def enter():
        context = client.phone_screen_stream(ACCOUNT, "person") if entry == "phone" else \
            client.desktop_stream(ACCOUNT, "person", route="phone_screen")
        async with context:
            pytest.fail("Unsafe phone stream was exposed")

    with pytest.raises(WorkstationError) as error:
        run(enter())
    assert error.value.code == "unavailable" and not wire


@pytest.mark.parametrize("status", [LEGACY_ANDROID, LEGACY_PREVIEW, SHARED_OFF])
def test_stop_remains_available_for_cleaning_up_an_old_device(status):
    client = RecordingClient(status)
    run(client.phone(ACCOUNT, "stop", holder="person"))
    assert client.mutations() == [{"action": "stop", "holder": "person"}]


def test_web_preview_is_requested_explicitly_and_never_via_legacy_start():
    client = RecordingClient(SHARED_OFF)
    answer = run(client.phone(ACCOUNT, "preview", holder="person", device="pixel_8"))
    assert answer["mode"] == "mobile_view"
    assert client.mutations() == [{"action": "preview", "holder": "person", "device": "pixel_8"}]


@pytest.mark.parametrize("action,fields", [("start", {}), ("install", {}),
                                         ("transfer", {"name": "x", "data_b64": "eA=="})])
def test_shared_workstation_cannot_turn_preview_availability_into_android(action, fields):
    client = RecordingClient(SHARED_OFF)
    with pytest.raises(WorkstationError) as error:
        run(client.phone(ACCOUNT, action, **fields))
    assert error.value.code == "unavailable" and not client.mutations()


def test_power_and_device_in_a_modern_preview_cannot_trigger_a_legacy_android_start():
    client = RecordingClient(SHARED_PREVIEW)
    run(client.phone(ACCOUNT, "button", holder="person", button="power"))
    run(client.phone(ACCOUNT, "device", holder="person", device="pixel_tablet"))
    assert client.mutations() == [{"action": "stop", "holder": "person"},
                                  {"action": "preview", "holder": "person", "device": "pixel_tablet"}]


@pytest.mark.parametrize("action,fields", [("button", {"button": "home"}), ("button", {"button": "back"}),
                                         ("rotate", {}), ("posture", {"posture": "closed"}),
                                         ("open_url", {"url": "https://example.test"}),
                                         ("input", {"input": "click", "x": 1, "y": 1}),
                                         ("screenshot", {}), ("marks", {})])
def test_modern_preview_keeps_its_web_controls(action, fields):
    client = RecordingClient(SHARED_PREVIEW)
    run(client.phone(ACCOUNT, action, **fields))
    assert client.mutations() == [{"action": action, "holder": "agent", **fields}]


def test_modern_shared_offline_device_choice_only_saves_a_profile():
    client = RecordingClient(SHARED_OFF)
    run(client.phone(ACCOUNT, "device", holder="person", device="pixel_8"))
    assert client.mutations() == [{"action": "device", "holder": "person", "device": "pixel_8"}]


def test_a_stopped_per_user_vm_can_be_started_without_inventing_an_installed_os():
    client = RecordingClient(VM_STOPPED, android_vm_endpoint=True)
    looked = run(client.phone(ACCOUNT, "status"))
    assert looked["can_start"] and looked["mode"] is None and not looked.get("installed")
    assert not client.mutations()
    run(client.phone(ACCOUNT, "start", holder="person"))
    assert client.mutations() == [{"action": "start", "holder": "person"}]


@pytest.mark.parametrize("action,fields", UNSAFE_ACTIONS)
def test_a_verified_per_user_vm_keeps_the_android_actions(action, fields):
    client = RecordingClient(VM_ANDROID, android_vm_endpoint=True)
    run(client.phone(ACCOUNT, action, **fields))
    assert client.mutations() == [{"action": action, "holder": "agent", **fields}]


@pytest.mark.parametrize("status,trusted_vm", [(VM_ANDROID, True), (SHARED_PREVIEW, False)])
def test_valid_android_and_modern_preview_screens_can_reach_their_own_stream(monkeypatch, status, trusted_vm):
    client = RecordingClient(status, android_vm_endpoint=trusted_vm)
    connections, closed = [], []

    async def wire():
        return True

    class Stream:
        async def close(self):
            closed.append(True)

    async def connect(url, **kwargs):
        connections.append((url, kwargs))
        return Stream()

    monkeypatch.setattr(client, "_wire", wire)
    monkeypatch.setattr("websockets.asyncio.client.connect", connect)
    assert run(client.phone_screen(ACCOUNT))["kind"] == "kasmvnc"

    async def enter():
        async with client.phone_screen_stream(ACCOUNT, "person") as stream:
            assert isinstance(stream, Stream)

    run(enter())
    assert len(connections) == 1 and "/phone/screen?viewer=person" in connections[0][0]
    assert closed == [True]


@pytest.mark.parametrize("action,fields", UNSAFE_ACTIONS)
def test_a_shared_endpoint_cannot_grant_itself_a_vm_role_in_its_status_json(action, fields):
    client = RecordingClient(VM_ANDROID)  # No trusted VM role was granted by the application.
    with pytest.raises(WorkstationError) as error:
        run(client.phone(ACCOUNT, action, **fields))
    assert error.value.code == "unavailable" and not client.mutations()


def _configured_client(monkeypatch, *, backend="container", system=None, manual="http://127.0.0.1:7040",
                       vm_env=True, container_env=True, accel="kvm"):
    settings = {"workstation_enabled": True, "workstation_backend": backend,
                "workstation_url": manual, "workstation_token": "pws_operator-configured"}
    monkeypatch.setattr(WC, "_setting", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(WC, "vm_accel", lambda: accel)
    for name in (P.URL_ENV, P.VM_URL_ENV, *(P.system_url_env(s) for s in P.SYSTEMS if s != P.DEFAULT_SYSTEM)):
        monkeypatch.delenv(name, raising=False)
    if vm_env:
        monkeypatch.setenv(P.VM_URL_ENV, "http://127.0.0.1:7140")
    if container_env:
        monkeypatch.setenv(P.URL_ENV, "http://127.0.0.1:7040")
    if system and system != P.DEFAULT_SYSTEM:
        monkeypatch.setenv(P.system_url_env(system), "http://127.0.0.1:7240")
    client = WC.from_settings(system)
    assert client is not None
    boundary = RecordingClient(VM_ANDROID)
    monkeypatch.setattr(client, "_call", boundary._call)
    return client, boundary


@pytest.mark.parametrize("backend", ["vm", "container", "remote", "auto"])
@pytest.mark.parametrize("system", [None, "ubuntu", "debian"])
def test_a_manual_endpoint_needs_an_explicit_vm_role_on_the_default_system(monkeypatch, backend, system):
    client, boundary = _configured_client(monkeypatch, backend=backend, system=system)
    trusted = backend == "vm" and system in (None, P.DEFAULT_SYSTEM)
    answer = run(client.phone(ACCOUNT, "status"))
    assert client.android_vm_endpoint is trusted
    assert (answer["state"] == "on") is trusted
    if trusted:
        run(client.phone(ACCOUNT, "start"))
        assert boundary.mutations() == [{"action": "start", "holder": "agent"}]
    else:
        with pytest.raises(WorkstationError):
            run(client.phone(ACCOUNT, "start"))
        assert not boundary.mutations()


@pytest.mark.parametrize("backend,vm_env,container_env,accel,trusted,port", [
    ("vm", True, True, "kvm", True, 7140),
    ("container", True, True, "kvm", False, 7040),
    ("auto", True, True, "kvm", True, 7140),
    ("auto", True, True, "tcg", False, 7040),
    ("auto", True, True, None, False, 7040),
    ("auto", True, False, "tcg", True, 7140),
    ("vm", False, True, None, False, 7040),
])
def test_vm_role_tracks_the_endpoint_actually_selected_from_the_environment(
        monkeypatch, backend, vm_env, container_env, accel, trusted, port):
    client, boundary = _configured_client(monkeypatch, backend=backend, manual="", vm_env=vm_env,
                                          container_env=container_env, accel=accel)
    assert client.base == f"http://127.0.0.1:{port}"
    assert client.android_vm_endpoint is trusted
    answer = run(client.phone(ACCOUNT, "status"))
    assert (answer["state"] == "on") is trusted
    if not trusted:
        with pytest.raises(WorkstationError):
            run(client.phone(ACCOUNT, "start"))
        assert not boundary.mutations()


def test_a_non_default_system_container_never_inherits_the_ubuntu_vm_role(monkeypatch):
    client, boundary = _configured_client(monkeypatch, backend="vm", system="debian", manual="")
    assert client.base == "http://127.0.0.1:7240" and client.android_vm_endpoint is False
    with pytest.raises(WorkstationError):
        run(client.phone(ACCOUNT, "screenshot"))
    assert not boundary.mutations()


def test_real_legacy_http_daemon_never_receives_unsafe_actions_or_screen_requests(tmp_path):
    events = []

    class OldPhone:
        def info(self, action="status"):
            events.append(action)
            return {**LEGACY_ANDROID, "ok": True, "action": action}

        def start(self, device=None):
            pytest.fail("New client booted an old shared Android phone")

        def stop(self):
            return self.info("stop")

    with running_workstation(tmp_path) as station:
        old = OldPhone()
        station.station.phones.get = lambda account: old

        def forbidden_screen(account):
            pytest.fail("Unsafe legacy screen endpoint was reached")

        station.station.phone_screen = forbidden_screen
        client = WorkstationClient(station.url, station.token)
        assert run(client.phone(ACCOUNT, "status"))["state"] == "unavailable"
        for action, fields in UNSAFE_ACTIONS:
            with pytest.raises(WorkstationError) as error:
                run(client.phone(ACCOUNT, action, **fields))
            assert error.value.code == "unavailable"
        assert run(client.phone_screen(ACCOUNT))["kind"] is None
        assert all(event == "status" for event in events)
        run(client.phone(ACCOUNT, "stop", holder="person"))
        assert events[-1] == "stop" and "start" not in events
