# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connect USB said "Permission denied: <folder>" on a VM-backend workstation.

Found on the owner's Windows host (2026-11-21). The host gives each person's
projects folder to Pantheon's group (`vm.project_share`) and shares it into
their machine over 9p, where a chown lands on the host as it is. The daemon in
the machine has no pairing group, so it gave the folder to the account's own
group, and Pantheon (another uid, in Pantheon's group) could no longer open it.
"""
import os
import stat

import pytest

from workstation import protocol as P

from tests.test_each_person_has_their_own_projects import A, ALLOWED

ubuntu = pytest.mark.skipif(os.geteuid() != 0, reason="Unix ownership needs root to set")
PANTHEON_GID = 4242


def _machine(tmp_path, backend):
    from workstation.ubuntu import UbuntuSystem
    system = UbuntuSystem(tmp_path / "homes", skeleton=tmp_path / "skel", prepare=False)
    root = tmp_path / "projects"
    root.mkdir()
    system.shared_roots = [root]
    system.backend = backend
    system.projects_gid = None  # what a VM's machine is started with: no --pairing-group
    folder = root / P.project_folder(ALLOWED)
    folder.mkdir()
    os.chown(folder, 0, PANTHEON_GID)  # as the host leaves it before the machine boots
    os.chmod(folder, 0o2770)
    return system, folder


@ubuntu
def test_a_vm_machine_keeps_the_hosts_group_on_the_shared_folder(tmp_path):
    system, folder = _machine(tmp_path, "vm")
    uid = system.registry.uid_for(A)
    system.make_project_dirs(A)
    st = os.stat(folder)
    assert (st.st_uid, st.st_gid) == (uid, PANTHEON_GID), "Pantheon's group was taken off the folder"
    assert stat.S_IMODE(st.st_mode) == 0o2770


@ubuntu
def test_a_vm_machine_with_a_root_group_folder_gives_it_to_the_account(tmp_path):
    system, folder = _machine(tmp_path, "vm")
    os.chown(folder, 0, 0)  # not the host's share: nothing of Pantheon's to keep
    uid = system.registry.uid_for(A)
    system.make_project_dirs(A)
    assert (os.stat(folder).st_uid, os.stat(folder).st_gid) == (uid, uid)


@ubuntu
def test_a_container_without_a_pairing_group_still_uses_the_accounts_group(tmp_path):
    system, folder = _machine(tmp_path, "container")
    uid = system.registry.uid_for(A)
    system.make_project_dirs(A)
    assert os.stat(folder).st_gid == uid


def test_a_projects_folder_closed_to_pantheon_says_why(tmp_path, monkeypatch):
    from src import phone_usb
    base = tmp_path / "projects"
    (base / "panick-folder").mkdir(parents=True)
    real_open = os.open

    def refused(path, flags, *args, dir_fd=None, **kwargs):
        if path == "panick-folder":
            raise PermissionError(13, "Permission denied", path)
        return real_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(phone_usb.os, "open", refused)
    with pytest.raises(RuntimeError) as caught:
        with phone_usb.Folder(str(base), ["panick-folder", "Android USB", "pixel-google_play"]):
            pass
    message = str(caught.value)
    assert "projects folder" in message and "Pantheon's group" in message
    assert "Errno" not in message
