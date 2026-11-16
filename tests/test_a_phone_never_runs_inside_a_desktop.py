# SPDX-License-Identifier: AGPL-3.0-or-later
"""A phone is its own VM beside the desktop, never a VM inside it.

Found on the owner's Windows host (2026-11-16): started with plain
`docker compose up`, Pantheon had no Android host, so it ran the phone's
emulator inside the person's desktop VM. Under Docker Desktop that put Android
three hypervisors deep, and it stalled before its display. The owner's design is
one layer: the host runs the desktop VM and the Android VM side by side, so the
phone works whatever system (or image) the desktop runs.

The desktop's endpoint therefore never counts as an Android endpoint, whatever
backend it uses. Only the Android host (`PANTHEON_ANDROID_URL`) does.
"""
from __future__ import annotations

import asyncio

import pytest

from src import workstation_client as WC
from src.workstation_client import WorkstationError
from tests.test_android_client_isolation import ACCOUNT, VM_ANDROID, RecordingClient
from workstation import protocol as P


def run(coro):
    return asyncio.run(coro)


def desktop(monkeypatch, backend):
    settings = {"workstation_enabled": True, "workstation_backend": backend,
                "workstation_url": "", "workstation_token": "pws_operator-configured"}
    monkeypatch.setattr(WC, "_setting", lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(WC, "vm_accel", lambda: "kvm")
    for name in (P.URL_ENV, P.VM_URL_ENV, *(P.system_url_env(s) for s in P.SYSTEMS if s != P.DEFAULT_SYSTEM)):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(P.VM_URL_ENV, "http://127.0.0.1:7140")
    monkeypatch.setenv(P.URL_ENV, "http://127.0.0.1:7040")
    client = WC.from_settings()
    # The desktop answers as an old in-desktop phone would: running, per-user VM.
    recorder = RecordingClient(VM_ANDROID)
    monkeypatch.setattr(client, "_call", recorder._call)
    return client, recorder


@pytest.mark.parametrize("backend", ["vm", "auto", "container"])
def test_the_desktop_is_never_an_android_endpoint(monkeypatch, backend):
    client, _ = desktop(monkeypatch, backend)
    assert client.android_vm_endpoint is False


@pytest.mark.parametrize("backend", ["vm", "auto"])
def test_the_desktop_vm_is_never_asked_to_start_android(monkeypatch, backend):
    client, recorder = desktop(monkeypatch, backend)
    with pytest.raises(WorkstationError) as caught:
        run(client.phone(ACCOUNT, "start"))
    assert caught.value.code == "unavailable"
    assert not recorder.mutations()


def test_the_phone_says_it_needs_the_android_host_beside_the_desktop(monkeypatch):
    client, _ = desktop(monkeypatch, "vm")
    answer = run(client.phone(ACCOUNT, "status"))
    assert answer["available"] is False and answer["state"] == "unavailable"
    why = answer["why"]
    assert "beside your desktop" in why and "Android VM service" in why
    assert "android-vm" in why


def test_the_android_host_is_the_one_android_endpoint(monkeypatch, tmp_path):
    from src import phone_runtime as PR
    token = tmp_path / "token"
    token.write_text("pws_android-host\n")
    monkeypatch.setenv(PR.URL_ENV, "http://127.0.0.1:7993")
    monkeypatch.setenv(PR.TOKEN_ENV, str(token))
    monkeypatch.setattr("src.workstation_access.may_use", lambda owner, auth_manager=None: True)
    monkeypatch.setattr("src.workstation_access.account_of", lambda owner: ACCOUNT)
    phone, account = PR.phone_for("someone")
    assert account == ACCOUNT
    assert phone.native_android is True and phone.client.android_vm_endpoint is True
