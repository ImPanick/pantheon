# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B992`. On the VM backend the admin's network mode was not enforced: each
person's machine is on QEMU's user-mode network, `P20-06`'s gate sits in front
of the container workstation only, and the VM host reported `full`.

Now, held as far as each mechanism can hold it, and said exactly that far:

  * **none** — from OUTSIDE the machine: its user-mode network is started
    with `restrict=on` (`vm.qemu_argv`), which libslirp enforces in QEMU's own
    process: no packet from the machine is routed out or to the host, DHCP and
    the one forwarded port excepted (read in libslirp's `udp.c`, `udp6.c`,
    `tcp_input.c`, `ip_icmp.c`, `ip6_icmp.c`, 2026-10-01). Root in the machine
    cannot change it. A running machine started without it is powered off and
    boots with it on its next use; `health` says `enforcement: hypervisor`.
  * **internet only** — user mode cannot filter by destination, so it is held
    INSIDE each machine: pushed to the machine's daemon the way `sudo` is, and
    held there for workstation accounts with `nft` (`P20-06`'s accounts
    layer). It holds while `sudo` is off and an agent with `sudo` can lift it —
    `enforcement: accounts`, and the panel says *"Enforced only while sudo is
    off"*. A machine that cannot hold it (made from an image without `nft`) is
    refused with a sentence, not run under a wider network.
  * a gate in front of the VM host was not used: its rules hold the whole
    namespace, and the host makes the machine image there on its first start,
    from Ubuntu's and Mozilla's repositories (argued in `workstation/vm.py`).

Driven through the VM host's real HTTP layer, the machines' real daemons in
this process (`tests/helpers/vm_fleet.py`, which records the QEMU command line
the host built for each), Pantheon's real `sync_config` and `network_view`.
"""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

from src import workstation_access as wa
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers import vm_fleet
from workstation import protocol as P
from workstation import vm

ANN, BOB = account_for("ann"), account_for("bob")


def run(coro):
    return asyncio.run(coro)


def _netdev(machine) -> str:
    argv = machine.argv
    return argv[argv.index("-netdev") + 1]


def _view(c, chosen):
    return wa.network_view(chosen, run(c.health()))


def test_none_is_held_from_outside_every_machine(tmp_path):
    """The row's `Verify:`, as far as it can be driven without a hypervisor:
    the machine is started with the network QEMU will not route."""
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        assert run(c.config(network="none"))["network"] == "none"
        run(c.ensure(ANN))
        m = fleet.machine_for(ANN)
        assert _netdev(m) == (f"user,id=net0,restrict=on,hostfwd=tcp:127.0.0.1:{m.port}"
                              f"-:{P.DEFAULT_PORT}")
        health = run(c.health())
        assert (health["network_in_force"], health["network_enforcement"],
                health["root_can_change_network"]) == ("none", "hypervisor", False)
        assert _view(c, "none")["state"] == wa.NETWORK_ENFORCED


def test_a_running_machine_restarts_into_none_and_out_of_it(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.write(ANN, "notes.txt", "kept"))
        m = fleet.machine_for(ANN)
        assert "restrict=on" not in _netdev(m)
        run(c.config(network="none"))
        fleet.wait_retired()
        assert not m.running() and m.stops == [True], "powered off cleanly"
        assert run(c.read(ANN, "notes.txt"))["data"] == b"kept"
        assert "restrict=on" in _netdev(m) and m.starts == 2
        run(c.config(network="full"))
        fleet.wait_retired()
        run(c.ensure(ANN))
        assert "restrict=on" not in _netdev(m) and m.starts == 3
        assert _view(c, "full")["state"] == wa.NETWORK_UNRESTRICTED


def test_while_a_machine_still_runs_the_old_network_the_panel_says_pending(tmp_path):
    release = threading.Event()

    class SlowToStop(vm_fleet.InProcessMachine):
        def stop(self, *, graceful=True):
            release.wait(10)
            super().stop(graceful=graceful)

    with vm_fleet.vm_host(tmp_path / "state", factory=SlowToStop) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.ensure(ANN))
        run(c.config(network="none"))
        view = _view(c, "none")
        assert (view["state"], view["in_force"]) == (wa.NETWORK_PENDING, "full")
        release.set()
        fleet.wait_retired()
        assert _view(c, "none")["state"] == wa.NETWORK_ENFORCED


@pytest.mark.parametrize("sudo,state", [(False, wa.NETWORK_ENFORCED_SUDO_OFF),
                                        (True, wa.NETWORK_LIFTABLE)])
def test_internet_is_held_inside_each_machine_and_said_that_far(tmp_path, sudo, state):
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.config(sudo=sudo, network="internet"))
        run(c.ensure(ANN))
        m = fleet.machine_for(ANN)
        assert "restrict=on" not in _netdev(m), "user mode cannot say internet only"
        guest = run(WorkstationClient(f"http://127.0.0.1:{m.port}", m.token).health())
        assert (guest["network"], guest["network_in_force"],
                guest["network_enforcement"]) == ("internet", "internet", "accounts")
        health = run(c.health())
        assert (health["network_in_force"], health["network_enforcement"]) == (
            "internet", "accounts")
        assert _view(c, "internet")["state"] == state


def test_a_machine_that_cannot_hold_internet_is_refused_not_run_wider(tmp_path):
    class OldImage(vm_fleet.InProcessMachine):
        holds_network = False   # made before `nft` was in the image

    with vm_fleet.vm_host(tmp_path / "state", factory=OldImage) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.config(network="internet"))
        with pytest.raises(WorkstationError) as e:
            run(c.exec(ANN, "echo should-not-run"))
        assert e.value.code == "unavailable"
        assert "internet only" in e.value.message and "Reset" in e.value.message
        assert not fleet.machine_for(ANN).running()


def test_the_running_machines_are_told_and_a_new_one_is_told_at_start(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.ensure(ANN))
        run(c.config(network="internet"))
        for account in (ANN, BOB):
            run(c.ensure(account))
            m = fleet.machine_for(account)
            assert m.system.network == "internet", account
        assert fleet.machine_for(ANN).starts == 1, "internet needs no restart"


def test_the_mode_is_kept_by_the_host_across_its_restart(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        run(WorkstationClient(url, vm_fleet.HOST_TOKEN).config(sudo=False, network="none"))
        state = fleet.state
    assert json.loads((state / "settings.json").read_text()) == {"sudo": False}
    assert json.loads((state / "network.json").read_text()) == {"network": "none"}
    again = vm.Fleet(state, accel="tcg", need_image=False,
                     machine_factory=vm_fleet.InProcessMachine)
    assert (again.sudo, again.network) == (False, "none")


def test_sync_config_pushes_the_mode_to_the_vm_host(tmp_path, monkeypatch):
    """Pantheon's own path: the admin's setting reaches the host, which then
    starts the next machine with it."""
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        monkeypatch.setattr(wa, "network_setting", lambda: "none")
        monkeypatch.setattr(wa, "sudo_wanted", lambda: False)
        daemon = run(wa.sync_config(WorkstationClient(url, vm_fleet.HOST_TOKEN)))
        assert daemon["network"] == "none" and fleet.network == "none"
        assert wa.network_view("none", daemon)["state"] == wa.NETWORK_ENFORCED


def test_the_image_is_made_with_the_network_it_needs(tmp_path):
    """The machine image is the operator's build, from Ubuntu's and Mozilla's
    repositories: never restricted, whatever the people's mode."""
    argv = vm.qemu_argv(name="pantheon-image", accel="tcg", cpus=1, memory_mib=2048,
                        disk=tmp_path / "d.qcow2", iso=None, console=tmp_path / "c",
                        qmp=tmp_path / "q")
    assert "restrict=on" not in argv[argv.index("-netdev") + 1]
    restricted = vm.qemu_argv(name="m", accel="tcg", cpus=1, memory_mib=2048,
                              disk=tmp_path / "d.qcow2", iso=None, console=tmp_path / "c",
                              qmp=tmp_path / "q", forward=("127.0.0.1", 4242), restrict=True)
    assert restricted[restricted.index("-netdev") + 1] == (
        f"user,id=net0,restrict=on,hostfwd=tcp:127.0.0.1:4242-:{P.DEFAULT_PORT}")


def test_the_protocol_names_the_hypervisor_as_a_holder():
    assert "hypervisor" in P.NETWORK_ENFORCEMENT
    assert wa.network_view("none", {"backend": "vm", "network_in_force": "none",
                                    "network_enforcement": "hypervisor",
                                    "root_can_change_network": False})["state"] == \
        wa.NETWORK_ENFORCED


@pytest.mark.skipif(not __import__("shutil").which("genisoimage"),
                    reason="genisoimage is in vm.Dockerfile; this machine has none")
@pytest.mark.parametrize("mode,restricted", [("none", True), ("internet", False), ("full", False)])
def test_a_qemu_machine_is_started_with_the_network_its_mode_needs(tmp_path, monkeypatch, mode,
                                                                  restricted):
    """`QemuMachine.start` itself, with QEMU's process stood in for: the
    command line it hands to QEMU, built by the one place that builds it."""
    started = []
    real_popen = vm.subprocess.Popen

    class Proc:
        def poll(self):
            return None

    def popen(argv, **kw):
        if str(argv[0]).startswith("qemu-system"):
            started.append(argv)
            return Proc()
        return real_popen(argv, **kw)  # genisoimage, for the app disk

    fleet = vm.Fleet(tmp_path / "state", accel="tcg", need_image=False)
    fleet._image = tmp_path / "image.qcow2"
    monkeypatch.setattr(fleet, "run", lambda argv: open(argv[-1], "wb").close())
    monkeypatch.setattr(vm.subprocess, "Popen", popen)
    fleet.network = mode
    fleet._restricted[ANN] = mode == "none"
    m = vm.QemuMachine(fleet, ANN)
    m.start()
    argv = started[0]
    netdev = argv[argv.index("-netdev") + 1]
    assert ("restrict=on" in netdev) is restricted
    assert f"hostfwd=tcp:127.0.0.1:{m.port}-:{P.DEFAULT_PORT}" in netdev
    drives = [argv[i + 1] for i, a in enumerate(argv) if a == "-drive"]
    assert drives[0].startswith(f"if=virtio,file={m.disk},")
    assert drives[1] == f"if=virtio,file={m.dir / 'app.iso'},format=raw,readonly=on"
    assert (m.dir / "app.iso").is_file()
