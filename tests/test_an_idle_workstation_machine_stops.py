# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B979`. A VM backend machine never stopped once started — measured 760 MiB
resident for a 2048 MiB machine under TCG, idle, until the VM host restarted —
and nothing capped how many ran. Now the host powers off a machine nobody has
called and nothing is running in for `PANTHEON_WORKSTATION_VM_IDLE_MIN`
minutes (30 by default; its disk kept, the next call boots it), refuses the
machine after `PANTHEON_WORKSTATION_VM_MAX_RUNNING` (by default what the
host's memory holds) with a sentence naming the limit, and says both in
`health` and in the panel.

Driven through the VM host's real HTTP layer and Pantheon's real client, with
machines that are the real daemon in this process (`tests/helpers/vm_fleet.py`)
and a clock the test moves; the housekeeping thread is driven for real on a
short idle time; the panel's words under node. Nothing reads a source file.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers import vm_fleet
from workstation import protocol as P
from workstation import vm
from workstation.agentd import WorkstationError as DaemonError

ANN, BOB = account_for("ann"), account_for("bob")


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _client(url) -> WorkstationClient:
    c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
    run(c.health())
    return c


def test_a_machine_nobody_calls_powers_off_and_boots_again_with_its_files(tmp_path):
    """The row's `Verify:`, first half: the idle time at a minute."""
    clock = Clock()
    with vm_fleet.vm_host(tmp_path / "state", idle_stop_s=60.0, clock=clock) as (fleet, url):
        c = _client(url)
        run(c.write(ANN, "notes.txt", "kept"))
        m = fleet.machine_for(ANN)
        assert m.running() and m.starts == 1
        clock.t += 59
        assert fleet.reap_idle() == [] and m.running()
        clock.t += 2
        assert fleet.reap_idle() == [ANN]
        assert not m.running() and m.stops == [True], "powered off cleanly, not killed"
        assert run(c.health())["machines"]["running"] == 0
        seen = run(c.account(ANN))
        assert (seen["exists"], seen["machine"]) == (True, "stopped"), "looked at, not booted"
        assert not m.running()
        assert run(c.read(ANN, "notes.txt"))["data"] == b"kept"
        assert m.starts == 2 and run(c.account(ANN))["machine"] == "running"


def test_a_call_or_a_running_command_keeps_it_up(tmp_path):
    clock = Clock()
    with vm_fleet.vm_host(tmp_path / "state", idle_stop_s=60.0, clock=clock) as (fleet, url):
        c = _client(url)
        run(c.ensure(ANN))
        clock.t += 50
        run(c.list(ANN))                       # used again: the minute starts over
        clock.t += 50
        assert fleet.reap_idle() == []
        started = threading.Event()

        def long_command():
            run(c.exec(ANN, "echo go; sleep 1.5", on_output=lambda k, d: started.set()))

        t = threading.Thread(target=long_command)
        t.start()
        assert started.wait(10)
        clock.t += 600                         # nobody has called for ten minutes…
        assert fleet.reap_idle() == [], "a machine was stopped under a running command"
        t.join(10)
        assert fleet.reap_idle() == [], "the command's end is a use"
        clock.t += 61
        assert fleet.reap_idle() == [ANN]


def test_an_idle_time_of_never_never_stops_one(tmp_path):
    clock = Clock()
    with vm_fleet.vm_host(tmp_path / "state", idle_stop_s=None, clock=clock) as (fleet, url):
        c = _client(url)
        run(c.ensure(ANN))
        clock.t += 10 ** 7
        assert fleet.reap_idle() == [] and fleet.machine_for(ANN).running()
        assert run(c.health())["machines"]["idle_stop_s"] is None


def test_the_host_does_it_on_its_own(tmp_path):
    """The housekeeping thread, for real: nobody calls `reap_idle`."""
    with vm_fleet.vm_host(tmp_path / "state", idle_stop_s=0.3) as (fleet, url):
        c = _client(url)
        run(c.ensure(ANN))
        stop = threading.Event()
        threading.Thread(target=fleet.housekeeping, args=(stop,), kwargs={"interval": 0.05},
                         daemon=True).start()
        try:
            deadline = time.monotonic() + 10
            while fleet.machine_for(ANN).running() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not fleet.machine_for(ANN).running()
        finally:
            stop.set()


def test_the_cap_refuses_the_next_machine_in_words_and_frees_up(tmp_path):
    """The row's `Verify:`, second half."""
    clock = Clock()
    with vm_fleet.vm_host(tmp_path / "state", idle_stop_s=60.0, max_running=1,
                          clock=clock) as (fleet, url):
        c = _client(url)
        run(c.ensure(ANN))
        with pytest.raises(WorkstationError) as e:
            run(c.ensure(BOB))
        assert e.value.code == "unavailable"
        assert "already runs 1 machine" in e.value.message
        assert vm.ENV["max_running"] in e.value.message and "1 minute" in e.value.message
        assert not fleet.machine_for(BOB).running()
        assert run(c.health())["machines"] == {"running": 1, "max_running": 1,
                                               "idle_stop_s": 60.0}
        run(c.ensure(ANN))                     # its own machine is not refused
        clock.t += 61
        fleet.reap_idle()
        run(c.ensure(BOB))
        assert fleet.machine_for(BOB).running()


# ── the knobs ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [("", 1800.0), ("30", 1800.0), ("1", 60.0),
                                          ("0", None), (" 5 ", 300.0)])
def test_the_idle_time_is_minutes_and_zero_is_never(raw, expected):
    assert vm.idle_stop_from_env(raw) == expected


@pytest.mark.parametrize("raw", ["-1", "half", "1.5", "100000"])
def test_a_bad_idle_time_is_said(raw):
    with pytest.raises(SystemExit) as e:
        vm.idle_stop_from_env(raw)
    assert vm.ENV["idle"] in str(e.value)


def test_the_cap_is_what_the_hosts_memory_holds_unless_set(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       16384000 kB\nMemFree:        1000 kB\n")
    limit = tmp_path / "memory.max"
    limit.write_text("max\n")
    total = vm.host_memory_mib(meminfo=meminfo, cgroup=limit)
    assert total == 16000
    assert vm.max_running_from_env("", 2048, total) == (16000 - vm.MEMORY_RESERVE_MIB) // 2048
    assert vm.max_running_from_env("auto", 4096, total) == 3
    limit.write_text(str(6 * 1024 ** 3) + "\n")           # a cgroup limit below the host's
    assert vm.host_memory_mib(meminfo=meminfo, cgroup=limit) == 6144
    assert vm.max_running_from_env("", 2048, 6144) == 2
    assert vm.max_running_from_env("", 2048, 1024) == 1, "always room for one"
    assert vm.max_running_from_env("", 2048, None) is None, "cannot tell: no cap made up"
    assert vm.max_running_from_env("7", 2048, total) == 7
    assert vm.max_running_from_env("0", 2048, total) is None
    with pytest.raises(SystemExit) as e:
        vm.max_running_from_env("lots", 2048, total)
    assert vm.ENV["max_running"] in str(e.value)


# ── the panel ────────────────────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    from test_tool_effect_surfaces_js import _make_sandbox
    from tests.test_the_workstation_panel_js import MODULE, _SHIM, _STUBS, _panel_nodes
    shim = _SHIM.replace("__NODES__", json.dumps(_panel_nodes()))
    return _make_sandbox(tmp_path_factory.mktemp("workstation-panel-b979"), MODULE, shim, _STUBS)


def _read(sandbox, status):
    from test_tool_effect_surfaces_js import _run
    from tests.test_the_workstation_panel_js import _PREAMBLE
    return _run(sandbox, _PREAMBLE + f"const st = {json.dumps(status)};\n", """
        respond(() => ({ status: 200, body: st }));
        await mod.open();
        console.log(JSON.stringify(read()));
    """)


DAEMON = {"agent": "pantheon-workstation", "protocol": 1, "backend": "vm", "version": 1,
          "sudo": True, "network": "full", "screen": [1280, 800], "accounts": 3,
          "machine": {"virtualization": "qemu", "accel": "tcg", "image": "ready"}}
UP = {"enabled": True, "is_admin": False, "may_use": True, "state": "up",
      "sentence": "The workstation is answering.", "probe": "ok", "daemon": DAEMON,
      "error": None, "you": {"account": "pw-cy-1a2b3c4d", "home": "/home/pw-cy-1a2b3c4d",
                             "home_state": "kept", "machine": "stopped"}}


@pytestmark_node
@pytest.mark.parametrize("machines,words", [
    ({"running": 2, "max_running": 3, "idle_stop_s": 1800},
     "2 of 3 machines running · a machine stops after 30 minutes unused"),
    ({"running": 1, "max_running": None, "idle_stop_s": 60},
     "1 machine running · a machine stops after 1 minute unused"),
    ({"running": 0, "max_running": 4, "idle_stop_s": None}, "0 of 4 machines running"),
])
def test_the_panel_says_how_many_run_and_when_one_stops(sandbox, machines, words):
    out = _read(sandbox, {**UP, "daemon": {**DAEMON, "machines": machines}})
    assert out["facts"].endswith(words), out["facts"]


@pytestmark_node
def test_the_panel_tells_a_person_their_machine_is_off_and_what_starts_it(sandbox):
    out = _read(sandbox, UP)
    assert out["you"].endswith("home /home/pw-cy-1a2b3c4d (kept from before) · your machine "
                               "is off — it starts when you or your agent next work there")
    on = _read(sandbox, {**UP, "you": {**UP["you"], "machine": "running"}})
    assert "machine is off" not in on["you"]


def test_the_status_passes_the_persons_machine_through(tmp_path, monkeypatch):
    from src import workstation_access as wa
    from src import workstation_client as wc
    clock = Clock()
    with vm_fleet.vm_host(tmp_path / "state", idle_stop_s=60.0, clock=clock) as (fleet, url):
        monkeypatch.setattr(wc, "enabled", lambda: True)
        monkeypatch.setattr(wc, "resolve_base", lambda: (url, wc.SOURCE_SETTING))
        monkeypatch.setattr(wc, "configured_token", lambda: vm_fleet.HOST_TOKEN)
        monkeypatch.setattr(wa, "may_use", lambda owner, auth_manager=None: True)
        monkeypatch.setattr(wa, "account_of", lambda owner: ANN)
        run(_client(url).ensure(ANN))
        clock.t += 61
        fleet.reap_idle()
        status = run(wa.status_for("ann", is_admin=True))
        assert status["you"]["machine"] == "stopped"
        assert status["daemon"]["machines"]["running"] == 0
        assert not fleet.machine_for(ANN).running(), "the panel's look booted it"
