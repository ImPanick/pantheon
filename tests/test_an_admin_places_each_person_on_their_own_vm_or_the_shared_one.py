# SPDX-License-Identifier: AGPL-3.0-or-later
"""The admin decides whether each person's workstation is a VM machine of
their own or an account on the one machine several people share.

The owner, 2026-11-17: *"the admin should be able to decide whether Pantheon
users run their own VM versus their accounts (upon initial creation) also
create a user in a shared VM instance … This keeps the platform lean on
limited hardware, with the ability to really increase the power and strength
across the board to large limits"*, and then *"Yeah let's build 1 and 2"*:
(1) the shared machine, with sudo off so only Unix permissions keep people
apart, and (2) the admin's default for new accounts plus a per-person
override. Android stays one machine per person, untouched.

What is pinned, and why each is a defect if it breaks:

  * **the default** ships as `own`, so nothing changes for an install that
    never touches it; set to `shared`, a new person gets an account on the
    shared machine and no machine of their own;
  * **a person stays where their workstation was made** when the default
    changes: the default is for people who have none yet, so changing it
    never moves anyone's work behind their back;
  * **the admin's word for a person** moves them: off their own machine (it
    powers off cleanly, its disk kept) or off the shared one, and back;
  * **sudo is off on the shared machine** whatever the admin's sudo switch
    says, because root there reads everyone's home;
  * **per-machine controls are per person on the shared machine**: a
    restart is their desktop, a reset is their home, the others' untouched;
    the processors are the pool's, refused with a sentence;
  * **the shared machine is given the projects root**, each person's folder
    made theirs inside it; an own machine is given only its person's;
  * **only the VM host** takes a placement; every other backend refuses it;
  * **Pantheon's side**: two admin settings, validated at the door, refused
    to the agent, pushed by `sync_config`, and shown to the admin with each
    person's machine.
"""
from __future__ import annotations

import asyncio
import os
import json
import time

import pytest

from src import workstation_access as wa
from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers import vm_fleet
from tests.helpers.workstation_daemon import running_workstation
from workstation import protocol as P
from workstation import vm

ANN = account_for("ann")
BOB = account_for("bob")
SHARED = P.SHARED_MACHINE


def run(coro):
    return asyncio.run(coro)


def _host(tmp_path, **kw):
    kw.setdefault("cpus", 2)
    kw.setdefault("host_cpus", 12)
    return vm_fleet.vm_host(tmp_path / "state", **kw)


def _client(url) -> WorkstationClient:
    return WorkstationClient(url, vm_fleet.HOST_TOKEN)


def _place(c, default="own", **people):
    return run(c.config(placement={"default": default, "people": people}))


def _wait(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _home_in(fleet, machine, account):
    return fleet.machine_for(machine).dir / "homes" / account


# ── the shared name, and the shipped default ─────────────────────────────────

def test_the_shared_machines_name_is_never_a_persons():
    assert not P.ACCOUNT_RE.match(SHARED)
    assert P.PLACEMENTS == ("own", "shared") and P.DEFAULT_PLACEMENT == "own"


def test_by_default_each_person_gets_a_machine_of_their_own(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        run(c.ensure(ANN))
        run(c.ensure(BOB))
        assert fleet.machine_for(ANN).running() and fleet.machine_for(BOB).running()
        assert not fleet.machine_for(SHARED).exists()
        placement = run(c.health())["placement"]
        assert placement["default"] == "own" and placement["people"] == {}
        assert placement["where"] == {ANN: "own", BOB: "own"}
        assert placement["shared_sudo"] is False


# ── the default is for people who have no workstation yet ───────────────────

def test_a_shared_default_puts_new_people_on_one_machine(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        _place(c, "shared")
        run(c.ensure(ANN))
        run(c.ensure(BOB))
        assert not fleet.machine_for(ANN).exists() and not fleet.machine_for(BOB).exists()
        shared = fleet.machine_for(SHARED)
        assert shared.running() and shared.starts == 1, "one machine, started once"
        assert _home_in(fleet, SHARED, ANN).is_dir() and _home_in(fleet, SHARED, BOB).is_dir()
        assert run(c.account(ANN))["placement"] == "shared"
        report = run(c.health())["placement"]
        assert report["shared"] == {"running": True, "accounts": [ANN, BOB]}
        assert report["where"] == {ANN: "shared", BOB: "shared"}
        assert sorted(run(c.health())["accounts"] if isinstance(run(c.health())["accounts"], list)
                      else fleet.accounts()) == [ANN, BOB]


def test_changing_the_default_moves_nobody_who_already_has_a_workstation(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        run(c.ensure(ANN))                       # made on a machine of her own
        _place(c, "shared")
        run(c.ensure(ANN))
        run(c.ensure(BOB))                       # made after: shared
        assert fleet.placement_of(ANN) == "own" and fleet.placement_of(BOB) == "shared"
        assert not _home_in(fleet, SHARED, ANN).exists()
        _place(c, "own")
        assert fleet.placement_of(BOB) == "shared", "and back: still where it was made"


def test_a_person_with_a_machine_from_before_placement_stays_on_it(tmp_path):
    """An install upgraded with machines already made: no `made` record for
    them, a disk that exists — theirs, whatever the default says."""
    with _host(tmp_path) as (fleet, url):
        run(_client(url).ensure(ANN))
    (tmp_path / "state" / "placement.json").unlink()
    with _host(tmp_path) as (fleet, url):
        _place(_client(url), "shared")
        assert fleet.placement_of(ANN) == "own"


# ── the admin's word for one person ─────────────────────────────────────────

def test_moving_a_person_to_the_shared_machine_powers_theirs_off_and_keeps_it(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        run(c.ensure(ANN))
        own = fleet.machine_for(ANN)
        run(c.write(ANN, "notes.txt", "mine"))
        _place(c, "own", **{ANN: "shared"})
        assert _wait(lambda: own.stops), "her own machine powers off"
        assert own.stops == [True] and not own.running(), "cleanly"
        assert own.exists(), "its disk kept"
        run(c.ensure(ANN))
        assert fleet.machine_for(SHARED).running()
        assert _home_in(fleet, SHARED, ANN).is_dir()
        assert run(c.account(ANN))["placement"] == "shared"
        # Back, by the admin's word: her own machine, her file still in it.
        _place(c, "own", **{ANN: "own"})
        run(c.ensure(ANN))
        assert own.running()
        assert (own.dir / "homes" / ANN / "notes.txt").read_text() == "mine"


def test_moving_one_person_leaves_everyone_else_where_they_are(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        run(c.ensure(ANN))
        run(c.ensure(BOB))
        _place(c, "own", **{ANN: "shared"})
        assert _wait(lambda: not fleet.machine_for(ANN).running())
        assert fleet.machine_for(BOB).running() and fleet.placement_of(BOB) == "own"


def test_placement_is_kept_across_a_restart_of_the_host(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        _place(c, "shared", **{BOB: "own"})
        run(c.ensure(ANN))
    saved = json.loads((tmp_path / "state" / "placement.json").read_text())
    assert saved["default"] == "shared" and saved["people"] == {BOB: "own"}
    assert saved["made"] == {ANN: "shared"}
    with _host(tmp_path) as (fleet, url):
        report = run(_client(url).health())["placement"]
        assert report["default"] == "shared" and report["people"] == {BOB: "own"}
        assert fleet.placement_of(ANN) == "shared" and fleet.placement_of(BOB) == "own"


@pytest.mark.parametrize("bad", [
    "shared",                                            # not the object
    {"default": "pool"},                                 # not a placement
    {"default": "own", "people": {"ann": "shared"}},     # not an account
    {"default": "own", "people": {ANN: "theirs"}},       # not a placement
    {"default": "own", "people": [ANN]},                 # not a map
    {"default": "own", "extra": 1},                      # not a field
])
def test_a_placement_that_is_not_one_is_refused(tmp_path, bad):
    with _host(tmp_path) as (fleet, url):
        with pytest.raises(WorkstationError) as e:
            run(_client(url).config(placement=bad))
        assert e.value.code == "bad_request"
        assert run(_client(url).health())["placement"]["default"] == "own"


def test_only_the_vm_host_takes_a_placement(tmp_path):
    with running_workstation(tmp_path) as ws:
        c = WorkstationClient(ws.url, ws.token)
        assert "placement" not in run(c.health())
        with pytest.raises(WorkstationError) as e:
            run(c.config(placement={"default": "shared", "people": {}}))
        assert e.value.code == "bad_request" and "VM" in e.value.message


# ── the shared machine: sudo off, one person at a time ──────────────────────

def test_sudo_is_off_on_the_shared_machine_whatever_the_switch_says(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        run(c.config(sudo=True))
        _place(c, "own", **{BOB: "shared"})
        run(c.ensure(ANN))
        run(c.ensure(BOB))
        assert fleet.machine_for(ANN).system.sudo is True, "her own machine: the switch"
        assert fleet.machine_for(SHARED).system.sudo is False, "the shared one: off"
        run(c.config(sudo=True))                 # pushed again: still off there
        assert fleet.machine_for(SHARED).system.sudo is False


def test_the_shared_machine_is_told_who_the_admins_are(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        _place(c, "shared")
        run(c.ensure(ANN))
        run(c.config(admins=[ANN]))
        assert fleet.machine_for(SHARED).system.admin_accounts == {ANN}


def test_a_restart_on_the_shared_machine_is_that_persons_desktop(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        _place(c, "shared")
        run(c.ensure(ANN))
        run(c.ensure(BOB))
        shared = fleet.machine_for(SHARED)
        answer = run(c.restart(ANN))
        assert answer["restarted"] == "desktop"
        assert shared.running() and shared.starts == 1 and shared.stops == [], \
            "nobody else's session was ended"


def test_a_reset_on_the_shared_machine_is_that_persons_home_only(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        _place(c, "shared")
        for who in (ANN, BOB):
            run(c.ensure(who))
            run(c.write(who, "keep.txt", who))
        run(c.reset(ANN))
        assert not (_home_in(fleet, SHARED, ANN) / "keep.txt").exists()
        assert (_home_in(fleet, SHARED, BOB) / "keep.txt").read_text() == BOB
        assert fleet.machine_for(SHARED).running()


def test_the_shared_machines_processors_are_the_pools(tmp_path):
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        _place(c, "shared")
        run(c.ensure(ANN))
        answer = run(c.cpus(ANN))
        assert answer["placement"] == "shared" and answer["cpus"] == 12
        with pytest.raises(WorkstationError) as e:
            run(c.cpus(ANN, 4))
        assert e.value.code == "bad_request" and "machine of your own" in e.value.message
        view = wa.cpus_view(answer)
        assert view["placement"] == "shared" and view["sentence"] == wa.SHARED_CPUS_SENTENCE


def test_the_shared_machine_is_given_the_projects_root(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv(P.PROJECTS_DIR_ENV, str(root))
    with _host(tmp_path) as (fleet, url):
        c = _client(url)
        _place(c, "own", **{BOB: "shared"})
        run(c.ensure(ANN))
        run(c.ensure(BOB))
        own = " ".join(fleet.machine_for(ANN).argv)
        shared = " ".join(fleet.machine_for(SHARED).argv)
        assert str(root / P.project_folder("ann")) in own
        assert f"path={root.resolve()}," in shared
        assert str(root / P.project_folder("bob")) not in shared


def test_the_shared_machines_app_disk_says_so(tmp_path, monkeypatch):
    """What each guest reads at boot: the shared machine, that it is shared
    and the group Pantheon's folders are in; an own machine, its person's
    folder and no word of sharing."""
    seen = {}

    def _iso(path, label, root, **kw):
        seen[path.parent.name] = {p.name: p.read_text() for p in root.iterdir() if p.is_file()}
        path.write_bytes(b"iso")

    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "provision.sh").write_text("#!/bin/sh\n")
    monkeypatch.setattr(vm, "make_iso", _iso)
    monkeypatch.setenv("PANTHEON_WORKSTATION_PAIRING_GID", "4242")
    fleet = vm.Fleet(tmp_path / "state", accel="kvm", need_image=False, payload=payload)
    for name in (SHARED, ANN):
        machine = vm.QemuMachine(fleet, name)
        machine.dir.mkdir(parents=True)
        machine._app_disk()
    assert seen[SHARED][vm.SHARED_MACHINE_FILE].strip() == "1"
    assert seen[SHARED][vm.PROJECTS_GID_FILE].strip() == "4242"
    assert vm.PROJECTS_FOLDER_FILE not in seen[SHARED]
    assert vm.SHARED_MACHINE_FILE not in seen[ANN]
    assert seen[ANN][vm.PROJECTS_FOLDER_FILE].strip() == P.project_folder_of(ANN)


# ── the guest's side, at boot ────────────────────────────────────────────────

def test_the_guest_knows_it_is_the_shared_machine(tmp_path):
    from workstation import __main__ as main
    assert main.shared_machine(tmp_path) is False
    (tmp_path / main.SHARED_MACHINE_FILE).write_text("1\n")
    assert main.shared_machine(tmp_path) is True
    assert main.shared_projects_gid(tmp_path) is None
    (tmp_path / main.PROJECTS_GID_FILE).write_text("4242\n")
    assert main.shared_projects_gid(tmp_path) == 4242
    (tmp_path / main.PROJECTS_GID_FILE).write_text("0\n")
    assert main.shared_projects_gid(tmp_path) is None, "never root's group"


def test_the_shared_machine_hides_other_peoples_processes(tmp_path):
    from workstation import __main__ as main
    mounts = tmp_path / "mounts"
    mounts.write_text("proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0\n")
    calls = []

    def _run(argv, **kw):
        calls.append(argv)
        mounts.write_text("proc /proc proc rw,relatime,hidepid=invisible 0 0\n")
        return type("R", (), {"returncode": 0})()

    assert main.hide_other_peoples_processes(run=_run, mounts=mounts) is True
    assert calls and calls[0][:2] == ["mount", "-o"] and "hidepid=invisible" in calls[0][2]
    calls.clear()
    assert main.hide_other_peoples_processes(run=_run, mounts=mounts) is True
    assert calls == [], "already hidden: nothing to do"


def test_ubuntu_with_sudo_locked_off_never_turns_it_on(tmp_path, monkeypatch):
    import workstation.ubuntu as ub
    written = []
    monkeypatch.setattr(ub, "write_sudoers", lambda *a, **k: written.append(a), raising=False)
    system = ub.UbuntuSystem(tmp_path / "homes", skeleton=tmp_path / "skel", prepare=False)
    system.sudo_locked_off = True
    system.set_sudo(True)
    assert system.sudo is False


# ── Pantheon's side ──────────────────────────────────────────────────────────

def test_the_settings_ship_as_own_and_nobody_named():
    from src.settings import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["workstation_vm_placement"] == "own"
    assert DEFAULT_SETTINGS["workstation_vm_placement_people"] == {}
    assert {"workstation_vm_placement", "workstation_vm_placement_people"} <= set(wa.SETTING_KEYS)


def test_an_admin_may_store_a_default_and_each_persons_word():
    assert wa.validate_setting("workstation_vm_placement", "Shared") == "shared"
    stored = wa.validate_setting("workstation_vm_placement_people",
                                 {"Bob": "OWN", "ann": "shared", "cy": None, "di": ""})
    assert stored == {"Bob": "own", "ann": "shared"}, "named people, the word lowercased; empty is none"
    assert wa.validate_setting("workstation_vm_placement_people", None) == {}


@pytest.mark.parametrize("key,bad", [
    ("workstation_vm_placement", "pool"),
    ("workstation_vm_placement", 1),
    ("workstation_vm_placement_people", ["ann"]),
    ("workstation_vm_placement_people", {"ann": "theirs"}),
    ("workstation_vm_placement_people", {"": "own"}),
])
def test_a_placement_setting_that_is_not_one_is_refused_at_the_door(key, bad):
    with pytest.raises(ValueError):
        wa.validate_setting(key, bad)


def test_the_agent_may_not_place_anyone():
    from src.agent_tools.admin_tools import _SELF_RESTRAINT_KEYS
    assert {"workstation_vm_placement", "workstation_vm_placement_people"} <= _SELF_RESTRAINT_KEYS


def test_sync_config_pushes_placement_by_account_to_a_vm_host(tmp_path, monkeypatch):
    with _host(tmp_path) as (fleet, url):
        client = _client(url)
        monkeypatch.setattr(wa, "vm_placement_default", lambda: "shared")
        monkeypatch.setattr(wa, "vm_placement_people", lambda: {"bob": "own"})
        monkeypatch.setattr(wa, "account_of", lambda owner: account_for(owner))
        daemon = run(wa.sync_config(client))
        assert daemon["placement"]["default"] == "shared"
        assert daemon["placement"]["people"] == {BOB: "own"}
        assert fleet.placement_default == "shared"


def test_sync_config_sends_no_placement_to_a_backend_without_one(tmp_path, monkeypatch):
    with running_workstation(tmp_path) as ws:
        monkeypatch.setattr(wa, "vm_placement_default", lambda: "shared")
        daemon = run(wa.sync_config(WorkstationClient(ws.url, ws.token)))
        assert "placement" not in daemon


def _serve(monkeypatch, url):
    from src import workstation_client as wc
    monkeypatch.setattr(wc, "enabled", lambda: True)
    monkeypatch.setattr(wc, "resolve_base", lambda *system: (url, wc.SOURCE_SETTING))
    monkeypatch.setattr(wc, "configured_token", lambda *a: vm_fleet.HOST_TOKEN)
    monkeypatch.setattr(wa, "may_use", lambda owner, auth_manager=None: True)
    monkeypatch.setattr(wa, "account_of", lambda owner: account_for(owner))
    monkeypatch.setattr(wa, "system_for", lambda owner: P.DEFAULT_SYSTEM)


class _Users:
    users = {"ann": {"is_admin": True}, "bob": {}}


def test_the_admin_is_shown_each_persons_machine(tmp_path, monkeypatch):
    with _host(tmp_path) as (fleet, url):
        _serve(monkeypatch, url)
        monkeypatch.setattr(wa, "vm_placement_people", lambda: {"bob": "shared"})
        run(_client(url).ensure(ANN))
        status = run(wa.status_for("ann", is_admin=True, auth_manager=_Users()))
        assert status["daemon"]["placement"]["default"] == "own"
        people = {p["name"]: p for p in status["settings"]["vm_people"]}
        assert people["ann"] == {"name": "ann", "account": ANN, "choice": None, "where": "own"}
        assert people["bob"] == {"name": "bob", "account": BOB, "choice": "shared",
                                 "where": None}
        assert status["you"]["placement"] == "own"


def test_a_person_on_the_shared_machine_is_told_so(tmp_path, monkeypatch):
    with _host(tmp_path) as (fleet, url):
        _serve(monkeypatch, url)
        monkeypatch.setattr(wa, "vm_placement_default", lambda: "shared")
        run(wa.sync_config(_client(url)))
        run(_client(url).ensure(BOB))
        status = run(wa.status_for("bob", is_admin=False, auth_manager=_Users()))
        assert status["you"]["placement"] == "shared"
        assert "settings" not in status


# ── the shared machine's wall: Unix permissions, with sudo locked off ───────

ubuntu = pytest.mark.skipif(os.geteuid() != 0, reason="Unix ownership needs root to set")


@ubuntu
def test_on_the_shared_machine_one_person_cannot_reach_anothers_work(tmp_path, monkeypatch):
    """The whole of the shared machine's isolation, as its daemon enforces it:
    sudo cannot be turned on there (so file tools never act as root), and
    acting as one person, another's home and projects folder are closed —
    read and write. Real ownership and real modes, no account made on this
    machine (`Law 20`): uids from the daemon's own registry."""
    import shutil
    import tempfile
    from pathlib import Path

    import workstation.ubuntu as ub
    monkeypatch.setattr(ub, "write_sudoers", lambda *a, **k: None, raising=False)
    system = ub.UbuntuSystem(tmp_path / "homes", skeleton=tmp_path / "skel", prepare=False)
    system.sudo_locked_off = True
    system.set_sudo(True)                         # the admin's switch, pushed
    assert system.sudo is False
    # Under /tmp itself: pytest's own folders are root's 0700.
    top = Path(tempfile.mkdtemp(prefix="shared-vm-"))
    os.chmod(top, 0o755)
    projects = top / "projects"
    projects.mkdir()
    system.shared_roots = [projects]
    system.projects_gid = 4242
    try:
        homes = {}
        for acct in (ANN, BOB):
            uid = system.registry.uid_for(acct)
            home = top / acct
            home.mkdir(mode=0o700)
            os.chown(home, uid, uid)
            os.chmod(home, 0o700)
            homes[acct] = home
        [ann_projects] = system.make_project_dirs(ANN)
        with system.acting_as(ANN):
            (homes[ANN] / "secret.txt").write_text("ann's")
            (Path(ann_projects) / "app.py").write_text("print('ann')")
        with system.acting_as(BOB):
            for denied in (lambda: (homes[ANN] / "secret.txt").read_text(),
                           lambda: os.listdir(homes[ANN]),
                           lambda: (homes[ANN] / "planted").write_text("x"),
                           lambda: (Path(ann_projects) / "app.py").read_text(),
                           lambda: (Path(ann_projects) / "planted").write_text("x"),
                           lambda: os.listdir(projects)):
                with pytest.raises(PermissionError):
                    denied()
            (homes[BOB] / "mine.txt").write_text("bob's")   # his own, fine
        assert not (homes[ANN] / "planted").exists()
    finally:
        shutil.rmtree(top, ignore_errors=True)
