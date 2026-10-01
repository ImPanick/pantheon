# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B984`. A VM backend machine had no clock source but the one it booted
with: `vm-guest.sh` masks `systemd-timesyncd` (it calls `ntp.ubuntu.com`,
measured `P20-07` — `Law 16`), so a long-running machine under TCG could drift,
and TLS in Firefox and `apt` notice a wrong clock.

The VM host now keeps each machine to its own time, over the one channel it
already has to each machine and nothing else: the machine's daemon, on its
forwarded port, with that machine's token. `POST /v1/clock` (`protocol.ROUTES`,
added) reads the machine's clock; with `step_s` it steps it — on a `vm`
machine's daemon only. The host measures the offset the way NTP does (its time
before and after, the machine's between; refused when the round trip is too
slow to say) and steps a machine more than `vm.CLOCK_STEP_S` out, when it
starts and every `vm.CLOCK_SYNC_S` after. No NTP server, no pool: the
reference is the VM host's clock, which is the Docker host's.

Why not the alternatives (argued in `workstation/vm.py`): QEMU's RTC follows
the host but starts up to a second behind it (`rtc_set_date_from_host` keeps
whole seconds — read in QEMU's source, 2026-10-01), so a guest reading it is
"within a second" at best; QEMU's guest agent would set it exactly but is not
in the machine image, and adding it means a new image every machine keeps
only after a reset.

Driven through the VM host's real HTTP layer and the machines' real daemons
in this process, with a machine clock the test can move
(`tests/helpers/vm_fleet.GuestSystem`). Nothing reads a source file.
"""
from __future__ import annotations

import asyncio
import math
import time

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers import vm_fleet
from tests.helpers.workstation_daemon import running_workstation
from workstation import agentd
from workstation import protocol as P
from workstation import vm
from workstation.agentd import SingleUserSystem, Workstation
from workstation.agentd import WorkstationError as DaemonError

ANN = account_for("ann")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def never_the_real_clock(monkeypatch):
    """Whatever the code under test does — or a mutant of it — this machine's
    own clock is never stepped here: the machines' clocks are the test's
    (`GuestSystem.drift`), and a test that wants a step records it instead."""
    monkeypatch.setattr(agentd.time, "clock_settime",
                        lambda *a: pytest.fail("something stepped the real clock"))


class Drifting(vm_fleet.InProcessMachine):
    """A machine whose clock is 30 s ahead of the host's when it boots."""
    boot_drift = 30.0

    def start(self) -> None:
        super().start()
        self.system.drift = self.boot_drift


def test_a_machine_that_boots_with_a_wrong_clock_is_given_the_hosts(tmp_path):
    """The row's `Verify:`, for what can be driven here: a machine off by 30 s
    is within `CLOCK_STEP_S` of the host once it answers. (Six hours of TCG is
    measured by the opt-in end-to-end file, not here.)"""
    with vm_fleet.vm_host(tmp_path / "state", factory=Drifting) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.health())
        run(c.ensure(ANN))
        guest = fleet.machine_for(ANN).system
        assert len(guest.steps) == 1 and guest.steps[0] == pytest.approx(-30.0, abs=0.25)
        assert abs(guest.drift) < vm.CLOCK_STEP_S


def test_a_clock_that_drifts_later_is_brought_back_and_that_is_not_a_use(tmp_path):
    clock = [1000.0]
    with vm_fleet.vm_host(tmp_path / "state", idle_stop_s=60.0,
                          clock=lambda: clock[0]) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.ensure(ANN))
        guest = fleet.machine_for(ANN).system
        assert guest.steps == [], "a machine already on time is not stepped"
        guest.drift = -4.0
        offsets = fleet.sync_clocks()
        assert offsets[ANN] == pytest.approx(-4.0, abs=0.25)
        assert guest.steps[-1] == pytest.approx(4.0, abs=0.25) and abs(guest.drift) < 0.25
        guest.drift += vm.CLOCK_STEP_S / 2              # inside the bound: left alone
        fleet.sync_clocks()
        assert len(guest.steps) == 1
        clock[0] += 61
        assert fleet.reap_idle() == [ANN], "keeping a machine's time kept it awake"


def test_a_round_trip_too_slow_to_measure_by_steps_nothing(tmp_path, monkeypatch):
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        run(WorkstationClient(url, vm_fleet.HOST_TOKEN).ensure(ANN))
        guest = fleet.machine_for(ANN).system
        guest.drift = 5.0
        slow = guest.clock_now

        def clock_now():
            time.sleep(vm.CLOCK_MAX_RTT_S + 0.1)
            return slow()

        monkeypatch.setattr(guest, "clock_now", clock_now)
        assert fleet.sync_clocks() == {ANN: None}
        assert guest.steps == []


# ── the daemon's side of it ──────────────────────────────────────────────────

def test_the_clock_route_reads_anywhere_and_steps_only_a_vm_machine(tmp_path, monkeypatch):
    # Never this machine's real clock, whatever the code under test does.
    monkeypatch.setattr(agentd.time, "clock_settime",
                        lambda *a: pytest.fail("a container's daemon stepped the clock"))
    with running_workstation(tmp_path) as ws:          # the container backend
        c = WorkstationClient(ws.url, ws.token)
        before = time.time()
        answer = run(c._call("clock", body={}))
        assert before - 1 < answer["time"] < time.time() + 1
        with pytest.raises(WorkstationError) as e:
            run(c._call("clock", body={"step_s": 1.0}))
        assert e.value.code == "unavailable" and "keeps its own clock" in e.value.message
        with pytest.raises(WorkstationError) as e:
            run(WorkstationClient(ws.url, "pws_wrong")._call("clock", body={}))
        assert e.value.code == "unauthorized"
    stepped = []
    monkeypatch.setattr(agentd.time, "clock_settime", lambda clk, t: stepped.append((clk, t)))
    machine = Workstation(SingleUserSystem(tmp_path / "m", backend="vm"), "pws_x")
    now = time.clock_gettime(time.CLOCK_REALTIME)
    machine.clock({"step_s": -2.5})
    assert stepped and stepped[0][0] == time.CLOCK_REALTIME
    assert stepped[0][1] == pytest.approx(now - 2.5, abs=0.5)


@pytest.mark.parametrize("bad", [True, "1", None, math.nan, math.inf, -math.inf,
                                 P.MAX_CLOCK_STEP_S + 1])
def test_a_step_that_is_not_a_finite_number_of_seconds_is_refused(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(agentd.time, "clock_settime",
                        lambda *a: pytest.fail("a refused step reached the clock"))
    machine = Workstation(SingleUserSystem(tmp_path / "m", backend="vm"), "pws_x")
    with pytest.raises(DaemonError) as e:
        machine.clock({"step_s": bad})
    assert e.value.code == "bad_request"


def test_the_vm_host_never_steps_its_own_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(agentd.time, "clock_settime",
                        lambda *a: pytest.fail("the VM host stepped the Docker host's clock"))
    with vm_fleet.vm_host(tmp_path / "state") as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        with pytest.raises(WorkstationError) as e:
            run(c._call("clock", body={"step_s": 3.0}))
        assert e.value.code == "unavailable"
