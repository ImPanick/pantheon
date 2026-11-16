# SPDX-License-Identifier: AGPL-3.0-or-later
"""The workstation VM's memory is an admin's setting, sized automatically
until one is chosen, and memory a machine is not using goes back to the host.

The owner, 2026-11-14, after Android was refused inside a 2 GB machine on a
64 GB desktop: *"this needs to be a setting in the platform's overall setting
to allocate RAM … OR the platform must be allowed "ballooning" memory to
allocate itself more as needed, and release it when it's not."* And, offered
the three ways to get there: *"All three"*. This file is the first.

What is pinned, and why each is a defect if it breaks:

  * **every machine reports free pages to the host** — QEMU's
    `virtio-balloon-pci,free-page-reporting=on`, so a machine given 10 GB
    holds on the host about what its guest is using, not 10 GB;
  * **automatic** (nothing chosen, nothing in `.env`) gives a machine room for
    the phone on a host that can spare it and the old 2 GB on one that cannot;
    `PANTHEON_WORKSTATION_VM_MEMORY_MIB` still wins over automatic;
  * **an admin's choice** reaches the VM host through `config`, is kept on its
    volume across a restart, is refused out of range with a sentence, goes
    back to automatic on `null`, and a running machine powers off cleanly and
    boots with it on its next use — its disk kept;
  * **a backend with no machines of its own** (the shared container) refuses
    the setting with a sentence rather than storing a number it cannot use;
  * **Pantheon's side**: the key ships automatic, is admin-validated, and
    `sync_config` pushes it to a VM host whose answer differs — and never to a
    backend that has no such setting;
  * **the stack** no longer pins 2048 in compose, and the phone's refusal
    points an admin at the setting.

Driven through the VM host's real HTTP layer and the machines' real daemons
in this process (`tests/helpers/vm_fleet.py`), with Pantheon's real client and
`sync_config`.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from src import workstation_access as wa
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers import vm_fleet
from tests.helpers.workstation_daemon import running_workstation
from workstation import phone
from workstation import protocol as P
from workstation import vm

ROOT = Path(__file__).resolve().parents[1]
ANN = account_for("ann")


def run(coro):
    return asyncio.run(coro)


def _memory(machine) -> int:
    argv = machine.argv
    return int(argv[argv.index("-m") + 1].split(",")[0])  # the desktop, before any phone room


# ── free page reporting ───────────────────────────────────────────────────────

def test_every_machine_hands_its_free_memory_back_to_the_host(tmp_path):
    argv = vm.qemu_argv(name="x", accel="kvm", cpus=2, memory_mib=10240,
                        disk=tmp_path / "d.qcow2", iso=None, console=tmp_path / "c",
                        qmp=tmp_path / "q")
    devices = [argv[i + 1] for i, a in enumerate(argv) if a == "-device"]
    assert "virtio-balloon-pci,free-page-reporting=on" in devices


# ── automatic ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host_mib,expected", [
    (None, vm.DEFAULT_MEMORY_MIB),     # unknown: the old size, nothing made up
    (8192, vm.DEFAULT_MEMORY_MIB),     # a small host keeps its memory
    (16384, vm.DEFAULT_MEMORY_MIB),    # 10 GB would leave it too little
    (32768, vm.PHONE_ROOM_MEMORY_MIB),
    (65536, vm.PHONE_ROOM_MEMORY_MIB),  # Cybertooth
])
def test_automatic_leaves_room_for_the_phone_where_the_host_can_spare_it(host_mib, expected):
    assert vm.auto_memory_mib(host_mib) == expected


def test_room_for_the_phone_is_what_the_phone_asks_of_its_machine():
    # The phone's own pre-check: its memory plus 1536 MiB for the desktop, out
    # of what the guest kernel reports (a little under `-m`).
    assert vm.PHONE_ROOM_MEMORY_MIB >= phone.DEFAULT_MEMORY_MIB + 1536 + 256


# ── the admin's choice, at the VM host ───────────────────────────────────────

def test_the_host_reports_its_memory_and_where_the_number_came_from(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state", memory_mib=4096, memory_source="auto",
                          host_mib=24576) as (fleet, url):
        health = run(WorkstationClient(url, vm_fleet.HOST_TOKEN).health())
        assert health["memory_mib"] == 4096
        assert health["memory_choice"] is None
        assert health["memory_default_mib"] == 4096
        assert health["memory_default_source"] == "auto"
        assert health["host_memory_mib"] == 24576
        assert health["memory_returns_to_host"] is True


def test_a_chosen_size_starts_the_next_machine_and_survives_a_restart(tmp_path):
    state = tmp_path / "state"
    with vm_fleet.vm_host(state) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        answer = run(c.config(memory_mib=12288))
        assert (answer["memory_mib"], answer["memory_choice"]) == (12288, 12288)
        run(c.ensure(ANN))
        assert _memory(fleet.machine_for(ANN)) == 12288
    with vm_fleet.vm_host(state) as (fleet, url):
        health = run(WorkstationClient(url, vm_fleet.HOST_TOKEN).health())
        assert (health["memory_mib"], health["memory_choice"]) == (12288, 12288)


def test_the_choice_does_not_disturb_sudo_or_the_network(tmp_path):
    state = tmp_path / "state"
    with vm_fleet.vm_host(state) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.config(sudo=False, network="internet"))
        run(c.config(memory_mib=8192))
    with vm_fleet.vm_host(state) as (fleet, url):
        health = run(WorkstationClient(url, vm_fleet.HOST_TOKEN).health())
        assert (health["sudo"], health["network"], health["memory_choice"]) == \
            (False, "internet", 8192)


def test_null_goes_back_to_automatic(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state", memory_mib=2048) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.config(memory_mib=6144))
        answer = run(c.config(memory_mib=None))
        assert (answer["memory_mib"], answer["memory_choice"]) == (2048, None)


@pytest.mark.parametrize("bad", [512, 300_000, "8192", True, 8192.5])
def test_a_size_out_of_range_is_refused_with_a_sentence(tmp_path, bad):
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        with pytest.raises(WorkstationError) as e:
            run(c.config(memory_mib=bad))
        assert e.value.code == "bad_request"
        assert "memory_mib" in e.value.message and "MiB" in e.value.message
        assert run(c.health())["memory_choice"] is None


def test_a_running_machine_boots_again_with_the_new_size_and_keeps_its_disk(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state", memory_mib=2048) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.write(ANN, "notes.txt", "kept"))
        m = fleet.machine_for(ANN)
        assert _memory(m) == 2048
        run(c.config(memory_mib=10240))
        fleet.wait_retired()
        assert not m.running() and m.stops == [True], "powered off cleanly"
        assert run(c.read(ANN, "notes.txt"))["data"] == b"kept"
        assert _memory(m) == 10240 and m.starts == 2


def test_the_same_size_again_restarts_nothing(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state", memory_mib=4096) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.ensure(ANN))
        run(c.config(memory_mib=4096))
        fleet.wait_retired()
        m = fleet.machine_for(ANN)
        assert m.running() and m.starts == 1 and m.stops == []


def test_an_automatic_limit_on_running_machines_follows_the_size(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state", memory_mib=2048, host_mib=32768,
                          max_running=vm.max_running_from_env("", 2048, 32768),
                          max_running_auto=True) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        assert run(c.health())["machines"]["max_running"] == 15
        run(c.config(memory_mib=10240))
        assert run(c.health())["machines"]["max_running"] == 3


def test_an_operators_limit_on_running_machines_stays_theirs(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state", max_running=4, host_mib=32768) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.config(memory_mib=10240))
        assert run(c.health())["machines"]["max_running"] == 4


def test_the_shared_container_refuses_a_memory_size(tmp_path):
    with running_workstation(tmp_path) as ws:
        c = WorkstationClient(ws.url, ws.token)
        assert "memory_choice" not in run(c.health())
        with pytest.raises(WorkstationError) as e:
            run(c.config(memory_mib=8192))
        assert e.value.code == "bad_request"
        assert "VM" in e.value.message


# ── Pantheon's side ───────────────────────────────────────────────────────────

def test_the_setting_ships_automatic():
    from src.settings import DEFAULT_SETTINGS
    assert "workstation_vm_memory_mib" in wa.SETTING_KEYS
    assert DEFAULT_SETTINGS["workstation_vm_memory_mib"] is None
    assert wa._DEFAULTS["workstation_vm_memory_mib"] is None


@pytest.mark.parametrize("value,stored", [(None, None), (8192, 8192), (1024, 1024),
                                          (262_144, 262_144), ("12288", 12288)])
def test_an_admin_may_store_a_size_or_automatic(value, stored):
    assert wa.validate_setting("workstation_vm_memory_mib", value) == stored


@pytest.mark.parametrize("value", [512, 300_000, True, "lots", 8192.5, ""])
def test_a_size_pantheon_would_send_and_the_host_refuse_is_refused_here(value):
    with pytest.raises(ValueError, match="MiB"):
        wa.validate_setting("workstation_vm_memory_mib", value)


def test_the_panel_is_told_the_choice():
    view = wa.settings_view()
    assert view["vm_memory_choice"] is None
    assert view["vm_memory_sizes"] == list(wa.VM_MEMORY_SIZES)
    assert all(P.VM_MEMORY_MIN_MIB <= s <= P.VM_MEMORY_MAX_MIB for s in wa.VM_MEMORY_SIZES)


def test_sync_config_pushes_the_choice_to_a_vm_host_and_back(tmp_path, monkeypatch):
    with vm_fleet.vm_host(tmp_path / "state", memory_mib=2048) as (fleet, url):
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        monkeypatch.setattr(wa, "vm_memory_choice", lambda: 10240)
        daemon = run(wa.sync_config(client))
        assert (daemon["memory_mib"], daemon["memory_choice"]) == (10240, 10240)
        assert fleet.memory_mib == 10240
        monkeypatch.setattr(wa, "vm_memory_choice", lambda: None)
        daemon = run(wa.sync_config(client))
        assert (daemon["memory_mib"], daemon["memory_choice"]) == (2048, None)


def test_sync_config_sends_no_size_to_a_backend_without_one(tmp_path, monkeypatch):
    with running_workstation(tmp_path) as ws:
        monkeypatch.setattr(wa, "vm_memory_choice", lambda: 10240)
        daemon = run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
        assert "memory_choice" not in daemon


# ── the stack ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.gpu-amd.yml",
                                  "docker-compose.gpu-nvidia.yml"])
def test_compose_no_longer_pins_two_gigabytes(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines()
             if ln.strip().startswith("- PANTHEON_WORKSTATION_VM_MEMORY_MIB")]
    assert lines, f"{name} still passes the variable through"
    for ln in lines:
        assert re.search(r"PANTHEON_WORKSTATION_VM_MEMORY_MIB=\$\{PANTHEON_WORKSTATION_VM_MEMORY_MIB:-\}",
                         ln), ln


def test_the_phones_refusal_points_an_admin_at_the_setting():
    assert "Settings" in phone.TOO_LITTLE_MEMORY
    assert "{need}" in phone.TOO_LITTLE_MEMORY and "{have}" in phone.TOO_LITTLE_MEMORY
