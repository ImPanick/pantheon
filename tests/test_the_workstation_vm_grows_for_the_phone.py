# SPDX-License-Identifier: AGPL-3.0-or-later
"""A person's VM grows by the phone's memory while Android runs, and gives it
back when Android stops (virtio-mem).

The owner, 2026-11-14: *"the platform must be allowed "ballooning" memory to
allocate itself more as needed, and release it when it's not. Shitty thing
about RAM and VM's is - whether or not the VM is using it, it's allocated and
"reserved" to the system while the VM is online"*. Free page reporting (the
memory setting's change) hands back what the guest frees; this hands back the
memory itself: a desktop VM is 2 GB, and the 9.5 GB Android needs is plugged
in only while the phone is on.

What is pinned:

  * under KVM every machine starts with a virtio-mem device sized for the
    phone, plugged at zero; under TCG (no Android there) nothing changes;
  * *Automatic* is then the plain 2 GB desktop, where the host has room to
    plug the phone in; a host that has not keeps the setting's earlier sizing;
  * the VM host plugs the room in before a phone `start`/`install` reaches the
    machine, takes it out after `stop`, takes it out again when a start fails,
    and when a status says the phone is off while it is still plugged in;
  * a look (`status`, `screenshot`, `marks`) never plugs anything in;
  * QEMU is asked over QMP (`qom-set requested-size`), and the host waits for
    the guest to take the memory before the phone's own check runs;
  * the guest daemon onlines what is plugged in as movable memory, so it can
    be unplugged again.
"""
from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from src.workstation_client import account_for
from workstation.agentd import WorkstationError
from tests.helpers import vm_fleet
from workstation import __main__ as daemon_main
from workstation import vm

ANN = account_for("ann")
ROOM = vm.PHONE_ROOM_HOTPLUG_MIB


def _devices(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-device"]


def _objects(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-object"]


# ── the command line ─────────────────────────────────────────────────────────

def test_room_for_the_phone_passes_the_phones_own_check():
    from workstation import phone
    # Plugged into the smallest desktop, the guest reports at least what the
    # phone's pre-check asks for (its memory plus 1536 MiB).
    assert ROOM >= phone.DEFAULT_MEMORY_MIB + 1536
    assert ROOM % 2 == 0, "virtio-mem plugs whole 2 MiB blocks"


def test_a_machine_with_room_starts_with_it_unplugged(tmp_path):
    argv = vm.qemu_argv(name="x", accel="kvm", cpus=2, memory_mib=2048,
                        disk=tmp_path / "d", iso=None, console=tmp_path / "c",
                        qmp=tmp_path / "q", hotplug_mib=ROOM)
    assert argv[argv.index("-m") + 1] == f"2048,maxmem={2048 + ROOM}M"
    assert f"memory-backend-ram,id={vm.PHONE_ROOM_MEMDEV},size={ROOM}M" in _objects(argv)
    assert (f"virtio-mem-pci,id={vm.PHONE_ROOM_DEVICE},memdev={vm.PHONE_ROOM_MEMDEV},"
            "requested-size=0") in _devices(argv)


def test_a_machine_without_room_is_as_it_was(tmp_path):
    argv = vm.qemu_argv(name="x", accel="tcg", cpus=2, memory_mib=2048,
                        disk=tmp_path / "d", iso=None, console=tmp_path / "c",
                        qmp=tmp_path / "q")
    assert argv[argv.index("-m") + 1] == "2048"
    assert not [d for d in _devices(argv) if d.startswith("virtio-mem")]


@pytest.mark.parametrize("accel,room", [("kvm", ROOM), ("tcg", 0)])
def test_the_fleet_gives_room_only_where_android_can_run(tmp_path, accel, room):
    fleet = vm.Fleet(tmp_path / "state", accel=accel, need_image=False,
                     machine_factory=vm_fleet.InProcessMachine)
    assert fleet.phone_room_mib == room
    assert fleet.memory_report()["phone_room_mib"] == room
    m = fleet.machine_for(ANN)
    fleet._started_memory[ANN] = fleet.memory_mib
    argv = fleet.machine_argv(m)
    assert bool([d for d in _devices(argv) if d.startswith("virtio-mem")]) is bool(room)


def test_a_host_without_room_for_the_phone_plugs_nothing(tmp_path):
    fleet = vm.Fleet(tmp_path / "state", accel="kvm", need_image=False, host_mib=8192,
                     machine_factory=vm_fleet.InProcessMachine)
    assert fleet.phone_room_mib == 0


# ── automatic ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host_mib", [None, 16384, 32768, 65536])
def test_automatic_is_the_plain_desktop_where_the_phone_is_plugged_in(host_mib):
    assert vm.auto_memory_mib(host_mib, phone_room=True) == vm.DEFAULT_MEMORY_MIB


def test_automatic_without_room_still_sizes_for_the_phone():
    assert vm.auto_memory_mib(65536) == vm.PHONE_ROOM_MEMORY_MIB


@pytest.mark.parametrize("host_mib,fits", [(None, True), (8192, False), (16384, True),
                                           (65536, True)])
def test_room_is_given_where_the_host_has_it(host_mib, fits):
    assert vm.phone_room_fits(host_mib, vm.DEFAULT_MEMORY_MIB) is fits


# ── QMP ───────────────────────────────────────────────────────────────────────

class FakeQmp:
    """A QMP socket: answers `qom-set` by plugging the asked size at once (as
    a guest that onlines it does), and `qom-get size` with what is plugged."""

    def __init__(self, path: Path, *, guest_takes: bool = True):
        self.path, self.guest_takes = path, guest_takes
        self.seen = []
        self.size = 0
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        self.sock.listen(8)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                f = conn.makefile("rwb")
                f.write(b'{"QMP": {"version": {}, "capabilities": []}}\n')
                f.flush()
                for line in f:
                    msg = json.loads(line)
                    self.seen.append(msg)
                    cmd, args = msg.get("execute"), msg.get("arguments") or {}
                    if cmd == "qom-set" and args.get("property") == "requested-size":
                        if self.guest_takes:
                            self.size = args["value"]
                        out = {"return": {}}
                    elif cmd == "qom-get" and args.get("property") == "size":
                        out = {"return": self.size}
                    elif cmd == "qom-get":
                        out = {"error": {"class": "GenericError", "desc": "no such property"}}
                    else:
                        out = {"return": {}}
                    f.write(json.dumps(out).encode() + b"\n")
                    f.flush()

    def close(self):
        self.sock.close()


def test_qmp_execute_returns_what_qemu_answers(tmp_path):
    q = FakeQmp(tmp_path / "q.sock")
    try:
        assert vm.qmp_execute(tmp_path / "q.sock", "qom-get",
                              {"path": "/machine/peripheral/x", "property": "size"}) == 0
        with pytest.raises(vm.QmpError, match="no such property"):
            vm.qmp_execute(tmp_path / "q.sock", "qom-get",
                           {"path": "/machine/peripheral/x", "property": "nope"})
    finally:
        q.close()


def test_qmp_execute_on_no_socket_is_an_error(tmp_path):
    with pytest.raises(vm.QmpError):
        vm.qmp_execute(tmp_path / "absent.sock", "qom-get", {})


def _qemu_machine(tmp_path):
    fleet = vm.Fleet(tmp_path / "state", accel="kvm", need_image=False)
    m = vm.QemuMachine(fleet, ANN)
    m.dir.mkdir(parents=True)
    return m


def test_a_qemu_machine_is_grown_and_waits_for_its_guest(tmp_path):
    m = _qemu_machine(tmp_path)
    q = FakeQmp(m.qmp)
    try:
        assert m.set_phone_room(ROOM, wait_s=2.0) == ROOM
        assert m.set_phone_room(0, wait_s=2.0) == 0
        sets = [s["arguments"] for s in q.seen if s.get("execute") == "qom-set"]
        assert sets == [
            {"path": f"/machine/peripheral/{vm.PHONE_ROOM_DEVICE}",
             "property": "requested-size", "value": ROOM * 1024 * 1024},
            {"path": f"/machine/peripheral/{vm.PHONE_ROOM_DEVICE}",
             "property": "requested-size", "value": 0}]
    finally:
        q.close()


def test_a_guest_that_does_not_take_the_memory_is_said_plainly(tmp_path):
    m = _qemu_machine(tmp_path)
    q = FakeQmp(m.qmp, guest_takes=False)
    try:
        assert m.set_phone_room(ROOM, wait_s=0.3) == 0
    finally:
        q.close()


# ── the VM host, around the phone ────────────────────────────────────────────

class Recorded:
    def __init__(self, fleet, monkeypatch, answers=None, fail=None):
        self.log = []
        self.answers = answers or {}
        self.fail = fail or set()

        def forward(account, name, body=None, **kw):
            self.log.append(("forward", (body or {}).get("action")))
            action = (body or {}).get("action")
            if action in self.fail:
                raise WorkstationError("unavailable", "Android did not start.")
            return dict(self.answers.get(action, {"ok": True, "state": "on"}))

        def room(account, mib):
            self.log.append(("room", mib))
            return mib

        monkeypatch.setattr(fleet, "forward", forward)
        monkeypatch.setattr(fleet, "set_phone_room", room)


def _station(tmp_path, accel="kvm"):
    fleet = vm.Fleet(tmp_path / "state", accel=accel, need_image=False,
                     machine_factory=vm_fleet.InProcessMachine)
    fleet.machine_for(ANN).start()
    return fleet, vm.VmStation(fleet, vm_fleet.HOST_TOKEN)


@pytest.mark.parametrize("action", ["start", "install"])
def test_the_room_is_plugged_in_before_android_starts(tmp_path, monkeypatch, action):
    fleet, station = _station(tmp_path)
    r = Recorded(fleet, monkeypatch)
    station.phone(ANN, {"action": action, "holder": "person"})
    assert r.log == [("room", ROOM), ("forward", action)]


def test_the_room_comes_out_after_android_stops(tmp_path, monkeypatch):
    fleet, station = _station(tmp_path)
    r = Recorded(fleet, monkeypatch, answers={"stop": {"ok": True, "state": "off"}})
    station.phone(ANN, {"action": "stop", "holder": "person"})
    assert r.log == [("forward", "stop"), ("room", 0)]


def test_a_start_that_fails_gives_the_room_back(tmp_path, monkeypatch):
    fleet, station = _station(tmp_path)
    r = Recorded(fleet, monkeypatch, fail={"start"})
    with pytest.raises(WorkstationError):
        station.phone(ANN, {"action": "start", "holder": "person"})
    assert r.log == [("room", ROOM), ("forward", "start"), ("room", 0)]


def test_a_phone_found_off_gives_the_room_back(tmp_path, monkeypatch):
    fleet, station = _station(tmp_path)
    fleet._phone_room[ANN] = ROOM
    r = Recorded(fleet, monkeypatch, answers={"status": {"ok": True, "state": "off"}})
    station.phone(ANN, {"action": "status", "holder": "person"})
    assert r.log == [("forward", "status"), ("room", 0)]


@pytest.mark.parametrize("action", ["status", "screenshot", "marks"])
def test_a_look_plugs_nothing_in(tmp_path, monkeypatch, action):
    fleet, station = _station(tmp_path)
    r = Recorded(fleet, monkeypatch, answers={a: {"ok": True, "state": "on"}
                                              for a in ("status", "screenshot", "marks")})
    station.phone(ANN, {"action": action, "holder": "agent"})
    assert ("room", ROOM) not in r.log


def test_a_machine_that_starts_again_has_nothing_plugged_in(tmp_path):
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        fleet.ready(ANN)
        fleet._phone_room[ANN] = ROOM
        fleet.machine_for(ANN).stop()
        fleet.ready(ANN)
        assert fleet.plugged_room(ANN) == 0


def test_a_guest_that_takes_too_little_is_refused_plainly(tmp_path, monkeypatch):
    fleet, station = _station(tmp_path)
    log = []
    monkeypatch.setattr(fleet, "forward", lambda *a, **k: log.append("forward") or {"ok": True})
    monkeypatch.setattr(fleet, "set_phone_room",
                        lambda account, mib: log.append(("room", mib)) or (0 if mib else 0))
    with pytest.raises(WorkstationError, match="memory") as e:
        station.phone(ANN, {"action": "start", "holder": "person"})
    assert e.value.code == "unavailable"
    assert log == [("room", ROOM), ("room", 0)], "nothing reaches the phone"


def test_tcg_plugs_nothing(tmp_path, monkeypatch):
    fleet, station = _station(tmp_path, accel="tcg")
    calls = []
    monkeypatch.setattr(fleet, "set_phone_room", lambda *a: calls.append(a) or 0)
    with pytest.raises(WorkstationError):
        station.phone(ANN, {"action": "start", "holder": "person"})
    assert calls == []


# ── inside the machine ────────────────────────────────────────────────────────

@pytest.mark.parametrize("before,after", [("offline", "online_movable"),
                                          ("online", "online"),
                                          ("online_movable", "online_movable")])
def test_the_guest_onlines_plugged_memory_as_movable(tmp_path, before, after):
    knob = tmp_path / "auto_online_blocks"
    knob.write_text(before + "\n")
    assert daemon_main.online_hotplugged_memory(knob) == after
    assert knob.read_text().strip() == after


def test_a_guest_without_hotplug_is_left_alone(tmp_path):
    assert daemon_main.online_hotplugged_memory(tmp_path / "absent") is None


def test_the_guest_reads_the_room_its_host_promised(tmp_path):
    assert daemon_main.phone_room_promised(tmp_path) == 0
    (tmp_path / vm.PHONE_ROOM_FILE).write_text(f"{ROOM}\n")
    assert daemon_main.phone_room_promised(tmp_path) == ROOM
    (tmp_path / vm.PHONE_ROOM_FILE).write_text("lots\n")
    assert daemon_main.phone_room_promised(tmp_path) == 0


def test_the_phones_check_counts_the_room_still_to_be_plugged_in(monkeypatch, tmp_path):
    import platform

    from workstation import phone
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:        1990000 kB\n")   # a 2 GB desktop
    monkeypatch.setattr(phone, "MEMINFO", meminfo)
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(phone, "tools_installed", lambda: True)
    monkeypatch.setattr(phone, "image_installed", lambda pkg: True)

    class Sys:
        backend = "vm"

    def why(room):
        system = Sys()
        system.phone_room_mib = room
        p = phone.AccountPhone.__new__(phone.AccountPhone)
        p.system, p.memory_mib, p._avail = system, phone.DEFAULT_MEMORY_MIB, None
        p._kvm = lambda: (True, "")
        p.package = lambda device=None: "x"
        return p._availability()

    assert "Android needs" in (why(0) or "")
    assert why(ROOM) is None
