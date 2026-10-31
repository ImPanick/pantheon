# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1427`, `D-2026-10-25-04` §4 — on the VM backend, a person's machine has
their projects folder, and only theirs.

`docker/workstation-vm.yml` mounted nothing into the machines, so what an agent
built in its VM stayed there. The VM host is given `data/projects` now; each
machine is started with its own person's folder shared in (virtio-9p, one
folder, never the root — the hypervisor wall holds), and the machine mounts it
at the same path before its daemon serves. A host given no projects folder
starts machines as it always did.

Not booted here (no KVM in CI): the command line, the folder, and the guest's
mount are each driven with the real functions.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from workstation import protocol as P
from workstation import vm
import workstation.__main__ as daemon_main

ACCOUNT = P.account_name("ada")
FOLDER = P.project_folder("ada")


def _argv(share):
    return vm.qemu_argv(name="pantheon-x", accel="tcg", cpus=1, memory_mib=512,
                        disk=Path("/s/disk.qcow2"), iso=None, console=Path("/s/console"),
                        qmp=Path("/s/qmp"), share=share)


def test_a_machine_is_started_with_its_own_folder_and_nothing_else():
    argv = _argv(Path("/projects") / FOLDER)
    i = argv.index("-virtfs")
    assert argv[i + 1] == (f"local,path=/projects/{FOLDER},mount_tag={vm.PROJECTS_TAG},"
                           "security_model=none,id=projects")
    assert "-virtfs" not in _argv(None), "no folder: the machine starts as it always did"
    with pytest.raises(ValueError):
        _argv(Path("/pro,jects/x"))


def test_the_host_makes_the_folder_theirs_in_pantheons_group(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv(P.PROJECTS_DIR_ENV, str(root))
    fleet = SimpleNamespace()
    share = vm.Fleet.project_share(fleet, ACCOUNT)
    assert share == root / FOLDER and share.is_dir()
    assert stat.S_IMODE(share.stat().st_mode) == 0o2770
    monkeypatch.setenv(P.PROJECTS_DIR_ENV, str(tmp_path / "absent"))
    assert vm.Fleet.project_share(fleet, ACCOUNT) is None


def _guest(tmp_path, *, tag="pantheon-projects", folder=FOLDER, mounted=""):
    app = tmp_path / "app"
    app.mkdir()
    (app / "projects-folder").write_text(folder + "\n")
    sysroot = tmp_path / "sys"
    (sysroot / "virtio0").mkdir(parents=True)
    (sysroot / "virtio0" / "mount_tag").write_text(tag + "\x00")
    mounts = tmp_path / "mounts"
    mounts.write_text(mounted)
    return app, sysroot, mounts


def test_the_machine_mounts_it_at_the_same_path(tmp_path, monkeypatch):
    monkeypatch.setenv(P.PROJECTS_DIR_ENV, str(tmp_path / "projects"))
    app, sysroot, mounts = _guest(tmp_path)
    ran = []
    got = daemon_main.mount_project_share(app, sys_root=sysroot, mounts=mounts,
                                          run=lambda argv, **kw: ran.append(argv) or SimpleNamespace(returncode=0))
    assert got == tmp_path / "projects" / FOLDER and got.is_dir()
    assert ran == [["mount", "-t", "9p", "-o", "trans=virtio,version=9p2000.L,msize=262144",
                    "pantheon-projects", str(got)]]


@pytest.mark.parametrize("case", ["no-tag", "bad-folder", "already"])
def test_nothing_to_mount_or_nothing_safe_mounts_nothing(tmp_path, monkeypatch, case):
    monkeypatch.setenv(P.PROJECTS_DIR_ENV, str(tmp_path / "projects"))
    target = tmp_path / "projects" / FOLDER
    kw = {"no-tag": dict(tag="something-else"), "bad-folder": dict(folder="../etc"),
          "already": dict(mounted=f"pantheon-projects {target} 9p rw 0 0\n")}[case]
    app, sysroot, mounts = _guest(tmp_path, **kw)
    ran = []
    got = daemon_main.mount_project_share(app, sys_root=sysroot, mounts=mounts,
                                          run=lambda argv, **k: ran.append(argv))
    assert ran == []
    assert got == (target if case == "already" else None)


def test_the_vm_overlays_give_the_host_the_projects_folder():
    import yaml
    root = Path(__file__).resolve().parents[1]
    # The VM host is the stack's own `workstation-vm` (2026-10-31).
    svc = yaml.safe_load((root / "docker-compose.yml").read_text())["services"]["workstation-vm"]
    assert "${APP_DATA_DIR:-./data}/projects:/projects:z" in svc["volumes"]
