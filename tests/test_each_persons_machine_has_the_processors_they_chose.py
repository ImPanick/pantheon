# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each person chooses how many processors their own VM machine gets, within
the pool an admin makes available to Pantheon.

The owner, 2026-11-16, after a phone run on his Windows desktop needed
`PANTHEON_WORKSTATION_VM_CPUS=6` and there was no `.env` to put it in: *"The
CPU setting should be user configurable with whatever is available for
pantheon to use (admin set)"*.

What is pinned, and why each is a defect if it breaks:

  * **the pool** is the admin's: by default every processor the VM host has,
    or fewer when an admin says so. It reaches the host through `config`, is
    kept on its volume, and a pool set above what the host has is held at the
    host's (Pantheon cannot know the host's count when it stores the setting,
    and a value refused at every sync would stop the workstation);
  * **the default** is `PANTHEON_WORKSTATION_VM_CPUS`, as before, held inside
    the pool;
  * **a person's choice** is theirs alone: it starts their machine with that
    many and nobody else's; it is kept across a restart, refused above the
    pool with a sentence, goes back to the default on `null`, and a running
    machine powers off cleanly and boots with it on its next use, its disk
    kept. Lowering the pool does the same to a machine running above it;
  * **a backend with no machines of its own** refuses both with a sentence;
  * **Pantheon's side**: the pool ships as *the host's*, is admin-validated,
    and `sync_config` pushes it; a person reads and sets only their own; and
    the panel is given what the VM host says about its memory and processors
    (it was given neither, so #76's memory control never showed).
"""
from __future__ import annotations

import asyncio

import pytest

from src import workstation_access as wa
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers import vm_fleet
from tests.helpers.workstation_daemon import running_workstation
from workstation import protocol as P
from workstation import vm

ANN = account_for("ann")
BOB = account_for("bob")


def run(coro):
    return asyncio.run(coro)


def _smp(machine) -> int:
    argv = machine.argv
    return int(argv[argv.index("-smp") + 1])


def _host(tmp_path, **kw):
    kw.setdefault("cpus", 2)
    kw.setdefault("host_cpus", 12)
    return vm_fleet.vm_host(tmp_path / "state", **kw)


# ── the pool and the default, at the VM host ─────────────────────────────────

def test_the_host_reports_its_pool_and_its_default(tmp_path):
    with _host(tmp_path) as (fleet, url):
        health = run(WorkstationClient(url, vm_fleet.HOST_TOKEN).health())
        assert health["cpus_max"] == 12 and health["cpus_max_choice"] is None
        assert health["cpus_default"] == 2 and health["host_cpus"] == 12


def test_an_admins_pool_is_kept_across_a_restart(tmp_path):
    with _host(tmp_path) as (fleet, url):
        answer = run(WorkstationClient(url, vm_fleet.HOST_TOKEN).config(cpus_max=8))
        assert (answer["cpus_max"], answer["cpus_max_choice"]) == (8, 8)
    with _host(tmp_path) as (fleet, url):
        health = run(WorkstationClient(url, vm_fleet.HOST_TOKEN).health())
        assert (health["cpus_max"], health["cpus_max_choice"]) == (8, 8)


def test_a_pool_above_the_host_is_held_at_the_hosts(tmp_path):
    with _host(tmp_path, host_cpus=6) as (fleet, url):
        answer = run(WorkstationClient(url, vm_fleet.HOST_TOKEN).config(cpus_max=32))
        assert (answer["cpus_max"], answer["cpus_max_choice"]) == (6, 32)


def test_null_gives_the_pool_back_to_the_host(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.config(cpus_max=4))
        answer = run(c.config(cpus_max=None))
        assert (answer["cpus_max"], answer["cpus_max_choice"]) == (12, None)


@pytest.mark.parametrize("bad", [0, 65, "8", True, 4.5])
def test_a_pool_out_of_range_is_refused_with_a_sentence(tmp_path, bad):
    with _host(tmp_path) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        with pytest.raises(WorkstationError) as e:
            run(c.config(cpus_max=bad))
        assert e.value.code == "bad_request" and "cpus_max" in e.value.message
        assert run(c.health())["cpus_max_choice"] is None


def test_the_default_is_held_inside_the_pool(tmp_path):
    with _host(tmp_path, cpus=6) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.config(cpus_max=4))
        assert run(c.cpus(ANN))["cpus"] == 4
        run(c.ensure(ANN))
        assert _smp(fleet.machine_for(ANN)) == 4


# ── a person's own choice ────────────────────────────────────────────────────

def test_nothing_chosen_is_the_default(tmp_path):
    with _host(tmp_path) as (fleet, url):
        answer = run(WorkstationClient(url, vm_fleet.HOST_TOKEN).cpus(ANN))
        assert answer == {"account": ANN, "cpus": 2, "cpus_choice": None, "cpus_default": 2,
                          "cpus_max": 12, "running_cpus": None}


def test_a_persons_choice_is_their_machine_and_nobody_elses(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        answer = run(c.cpus(ANN, 6))
        assert (answer["cpus"], answer["cpus_choice"]) == (6, 6)
        run(c.ensure(ANN))
        run(c.ensure(BOB))
        assert _smp(fleet.machine_for(ANN)) == 6
        assert _smp(fleet.machine_for(BOB)) == 2
        assert run(c.cpus(BOB))["cpus_choice"] is None
        assert run(c.cpus(ANN))["running_cpus"] == 6


def test_a_choice_survives_a_restart(tmp_path):
    with _host(tmp_path) as (fleet, url):
        run(WorkstationClient(url, vm_fleet.HOST_TOKEN).cpus(ANN, 6))
    with _host(tmp_path) as (fleet, url):
        assert run(WorkstationClient(url, vm_fleet.HOST_TOKEN).cpus(ANN))["cpus_choice"] == 6


def test_null_goes_back_to_the_default(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.cpus(ANN, 6))
        answer = run(c.cpus(ANN, None))
        assert (answer["cpus"], answer["cpus_choice"]) == (2, None)


def test_more_than_the_pool_is_refused_with_a_sentence(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.config(cpus_max=4))
        with pytest.raises(WorkstationError) as e:
            run(c.cpus(ANN, 6))
        assert e.value.code == "bad_request" and "4" in e.value.message
        assert run(c.cpus(ANN))["cpus_choice"] is None


@pytest.mark.parametrize("bad", [0, "6", True, 2.5])
def test_a_count_that_is_not_one_is_refused(tmp_path, bad):
    with _host(tmp_path) as (fleet, url):
        with pytest.raises(WorkstationError) as e:
            run(WorkstationClient(url, vm_fleet.HOST_TOKEN).cpus(ANN, bad))
        assert e.value.code == "bad_request" and "cpus" in e.value.message


def test_a_running_machine_boots_again_with_its_new_count_and_keeps_its_disk(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.write(ANN, "notes.txt", "kept"))
        run(c.ensure(BOB))
        m, other = fleet.machine_for(ANN), fleet.machine_for(BOB)
        assert _smp(m) == 2
        run(c.cpus(ANN, 6))
        fleet.wait_retired()
        assert not m.running() and m.stops == [True], "powered off cleanly"
        assert other.running() and other.stops == [], "nobody else's machine is touched"
        assert run(c.read(ANN, "notes.txt"))["data"] == b"kept"
        assert _smp(m) == 6 and m.starts == 2


def test_the_same_count_again_restarts_nothing(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.ensure(ANN))
        run(c.cpus(ANN, 2))
        fleet.wait_retired()
        m = fleet.machine_for(ANN)
        assert m.running() and m.starts == 1 and m.stops == []


def test_a_smaller_pool_brings_a_machine_above_it_down_to_it(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.cpus(ANN, 8))
        run(c.ensure(ANN))
        run(c.ensure(BOB))
        run(c.config(cpus_max=4))
        fleet.wait_retired()
        assert not fleet.machine_for(ANN).running()
        assert fleet.machine_for(BOB).running(), "two processors fit inside four"
        answer = run(c.cpus(ANN))
        assert (answer["cpus"], answer["cpus_choice"]) == (4, 8), "her choice is kept"
        run(c.ensure(ANN))
        assert _smp(fleet.machine_for(ANN)) == 4


def test_a_reset_keeps_the_persons_choice(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        run(c.cpus(ANN, 6))
        run(c.reset(ANN))
        assert _smp(fleet.machine_for(ANN)) == 6


def test_the_shared_container_has_no_processors_to_set(tmp_path):
    with running_workstation(tmp_path) as ws:
        c = WorkstationClient(ws.url, ws.token)
        assert "cpus_max_choice" not in run(c.health())
        for call in (lambda: c.config(cpus_max=4), lambda: c.cpus(ANN, 4)):
            with pytest.raises(WorkstationError) as e:
                run(call())
            assert e.value.code == "bad_request" and "VM" in e.value.message


def test_the_host_counts_the_processors_it_may_run_on(tmp_path, monkeypatch):
    """A server's cpuset, and a container's quota, are what the machines share."""
    quota = tmp_path / "cpu.max"
    monkeypatch.setattr(vm.os, "sched_getaffinity", lambda pid: set(range(96)), raising=False)
    assert vm.host_cpus(quota) == 96               # no quota file: every one it may run on
    quota.write_text("max 100000\n")
    assert vm.host_cpus(quota) == 96               # no quota
    quota.write_text("1600000 100000\n")
    assert vm.host_cpus(quota) == 16               # `--cpus 16`
    quota.write_text("150000 100000\n")
    assert vm.host_cpus(quota) == 2                # a part of one counts as one
    monkeypatch.setattr(vm.os, "sched_getaffinity", lambda pid: set(range(8)), raising=False)
    assert vm.host_cpus(quota) == 2
    quota.write_text("max 100000\n")
    assert vm.host_cpus(quota) == 8                # `--cpuset-cpus 0-7`


# ── Pantheon's side ───────────────────────────────────────────────────────────

def test_the_pool_ships_as_the_hosts():
    from src.settings import DEFAULT_SETTINGS
    assert "workstation_vm_cpus_max" in wa.SETTING_KEYS
    assert DEFAULT_SETTINGS["workstation_vm_cpus_max"] is None
    assert wa._DEFAULTS["workstation_vm_cpus_max"] is None
    assert wa.settings_view()["vm_cpus_max_choice"] is None


@pytest.mark.parametrize("value,stored", [(None, None), (1, 1), (8, 8), (64, 64), ("6", 6)])
def test_an_admin_may_store_a_pool_or_the_hosts(value, stored):
    assert wa.validate_setting("workstation_vm_cpus_max", value) == stored


@pytest.mark.parametrize("value", [0, 65, True, "lots", 4.5, ""])
def test_a_pool_the_host_would_refuse_is_refused_here(value):
    with pytest.raises(ValueError, match="processors"):
        wa.validate_setting("workstation_vm_cpus_max", value)


def test_sync_config_pushes_the_pool_to_a_vm_host(tmp_path, monkeypatch):
    with _host(tmp_path) as (fleet, url):
        client = WorkstationClient(url, vm_fleet.HOST_TOKEN)
        monkeypatch.setattr(wa, "vm_cpus_max_choice", lambda: 4)
        daemon = run(wa.sync_config(client))
        assert (daemon["cpus_max"], daemon["cpus_max_choice"]) == (4, 4)
        monkeypatch.setattr(wa, "vm_cpus_max_choice", lambda: None)
        assert run(wa.sync_config(client))["cpus_max"] == 12


def test_sync_config_sends_no_pool_to_a_backend_without_one(tmp_path, monkeypatch):
    with running_workstation(tmp_path) as ws:
        monkeypatch.setattr(wa, "vm_cpus_max_choice", lambda: 4)
        daemon = run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
        assert "cpus_max_choice" not in daemon


def _serve(monkeypatch, url):
    from src import workstation_client as wc
    monkeypatch.setattr(wc, "enabled", lambda: True)
    monkeypatch.setattr(wc, "resolve_base", lambda *system: (url, wc.SOURCE_SETTING))
    monkeypatch.setattr(wc, "configured_token", lambda *a: vm_fleet.HOST_TOKEN)
    monkeypatch.setattr(wa, "may_use", lambda owner, auth_manager=None: True)
    monkeypatch.setattr(wa, "account_of", lambda owner: account_for(owner))
    monkeypatch.setattr(wa, "system_for", lambda owner: P.DEFAULT_SYSTEM)


def test_a_person_reads_and_sets_only_their_own(tmp_path, monkeypatch):
    with _host(tmp_path) as (fleet, url):
        _serve(monkeypatch, url)
        view = run(wa.machine_cpus("ann", 6))
        assert (view["cpus"], view["cpus_choice"], view["cpus_max"]) == (6, 6, 12)
        assert view["sentence"]
        assert run(wa.machine_cpus("bob"))["cpus_choice"] is None
        assert fleet.account_cpus(ANN) == 6 and fleet.account_cpus(BOB) == 2


def test_a_person_is_told_the_pool_in_words_when_they_ask_for_more(tmp_path, monkeypatch):
    with _host(tmp_path) as (fleet, url):
        _serve(monkeypatch, url)
        monkeypatch.setattr(wa, "vm_cpus_max_choice", lambda: 4)   # the admin's, pushed first
        with pytest.raises(WorkstationError) as e:
            run(wa.machine_cpus("ann", 6))
        assert "4" in e.value.message


def test_the_panel_is_told_what_the_vm_host_says_of_memory_and_processors(tmp_path,
                                                                         monkeypatch):
    """`_daemon_view` passed neither on, so #76's memory control never showed."""
    with _host(tmp_path, memory_mib=4096) as (fleet, url):
        _serve(monkeypatch, url)
        daemon = run(wa.status_for("ann", is_admin=True))["daemon"]
        assert daemon["memory_choice"] is None and daemon["memory_default_mib"] == 4096
        assert daemon["cpus_max"] == 12 and daemon["cpus_max_choice"] is None
        assert daemon["host_cpus"] == 12 and daemon["cpus_default"] == 2


def test_the_route_and_its_bounds_are_in_the_protocol():
    assert P.ROUTES["cpus"] == ("POST", "/v1/users/{account}/cpus")
    assert (P.VM_CPUS_MIN, P.VM_CPUS_MAX) == (1, 64)


def test_the_agents_own_bridge_cannot_set_a_persons_processors():
    from src.tools.system import _APP_API_BLOCKLIST_METHOD_PATH, _effective_app_api_path
    path = _effective_app_api_path("/api/workstation/cpus")
    assert any(m == "POST" and path.startswith(p) for m, p in _APP_API_BLOCKLIST_METHOD_PATH)
