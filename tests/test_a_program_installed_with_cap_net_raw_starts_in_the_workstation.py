# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B976` — `ping`, installed by an agent, starts in the workstation.

The container runs without `CAP_NET_RAW` (`P20-06`, load-bearing), and the
kernel refuses to `exec` a program whose file capability names a capability the
bounding set never grants — Ubuntu's `ping` is installed `cap_net_raw=ep`.
`workstation/netraw.py`, run by apt after every dpkg run, takes out of each
program on `PATH` what the machine cannot grant.

Driven, not read (`Law 20`): a real file with a real `security.capability`
attribute, started by the real kernel from a process whose bounding set lacks
`CAP_NET_RAW` — refused before, started after — through the module's own entry
point, the one apt's hook runs. The capability decoding is checked against
`getcap` where it is installed. Root only for the kernel cases (setting a file
capability needs `CAP_SETFCAP`); they skip elsewhere.

The image half — `sudo apt-get install iputils-ping`, then `ping` — was measured
2026-10-01 in the image and is in the row's closing text; the apt hook as apt
reads it is checked here with apt's own parser when `apt-config` is present.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from workstation import netraw as NR
from workstation import netrules as N

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "workstation" / "apt-net-raw.conf"

NET_RAW = 1 << 13
NET_BIND_SERVICE = 1 << 10
# Docker's default bounding set, with and without NET_RAW (read off
# `/proc/self/status` in the image: `a80425fb`, and `a80405fb` with
# `--cap-drop NET_RAW`).
DOCKER_DEFAULT = 0xA80425FB
WORKSTATION = 0xA80405FB


def _cap(permitted: int, inheritable: int = 0, *, rev: int = 2, effective: bool = True) -> bytes:
    """A `security.capability` value as `setcap` writes it."""
    magic = (rev << 24) | (1 if effective else 0)
    words = 1 if rev == 1 else 2
    pairs = []
    for i in range(words):
        pairs += [(permitted >> (32 * i)) & 0xFFFFFFFF, (inheritable >> (32 * i)) & 0xFFFFFFFF]
    raw = struct.pack(f"<I{2 * words}I", magic, *pairs)
    return raw + (struct.pack("<I", 0) if rev == 3 else b"")


# ── the decoding ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rev", [1, 2, 3])
def test_what_the_machine_never_grants_is_found_in_every_revision(rev):
    assert NR.ungrantable(_cap(NET_RAW, rev=rev), WORKSTATION) == NET_RAW
    assert NR.ungrantable(_cap(NET_RAW, rev=rev), DOCKER_DEFAULT) == 0
    assert NR.ungrantable(_cap(NET_BIND_SERVICE, rev=rev), WORKSTATION) == 0


@pytest.mark.parametrize("raw", [b"", b"\x00\x00\x00\x09" + b"\x00" * 16, b"\x01\x00\x00\x02"])
def test_an_attribute_it_cannot_read_is_left_alone(raw):
    assert NR.ungrantable(raw, 0) == 0


def test_the_bounding_set_is_read_whole_and_unknown_is_not_empty(tmp_path):
    status = tmp_path / "status"
    status.write_text("Name:\tx\nCapBnd:\t00000000a80405fb\n")
    assert N.capabilities("CapBnd", status) == WORKSTATION
    assert N.capability(13, "CapBnd", status) is False and N.capability(12, "CapBnd", status) is False
    assert N.capability(10, "CapBnd", status) is True
    assert N.capabilities("CapBnd", tmp_path / "missing") is None
    assert N.capability(10, "CapBnd", tmp_path / "missing") is False


def test_a_bounding_set_that_cannot_be_read_changes_nothing(monkeypatch):
    monkeypatch.setattr(N, "capabilities", lambda *a, **k: None)
    touched = []
    assert NR.mend_all(["/usr/bin"], get=lambda *a, **k: touched.append(a) or b"") == []
    assert touched == []


# ── on real files, with the real kernel ──────────────────────────────────────

_root_only = pytest.mark.skipif(os.geteuid() != 0, reason="setting a file capability needs root")
_libc = ctypes.CDLL(None, use_errno=True)
PR_CAPBSET_DROP = 24


def _without_net_raw():
    """In the child, before exec: drop CAP_NET_RAW from the bounding set — the
    workstation container's `cap_drop: [NET_RAW]`."""
    if _libc.prctl(PR_CAPBSET_DROP, 13, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_CAPBSET_DROP)")


def _starts(path: Path) -> str:
    try:
        done = subprocess.run([str(path)], preexec_fn=_without_net_raw, capture_output=True,
                              timeout=10)
    except PermissionError:
        return "refused at exec"
    return f"ran, exit {done.returncode}"


@pytest.fixture
def bin_dir(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("setting a file capability needs root")
    d = tmp_path / "bin"
    d.mkdir()
    for name in ("ping", "arping", "plain", "binder", "both"):
        shutil.copy2(shutil.which("true"), d / name)
    os.setxattr(d / "ping", NR.XATTR, _cap(NET_RAW))
    os.setxattr(d / "arping", NR.XATTR, _cap(NET_RAW, rev=3))
    os.setxattr(d / "binder", NR.XATTR, _cap(NET_BIND_SERVICE))
    os.setxattr(d / "both", NR.XATTR, _cap(NET_RAW | NET_BIND_SERVICE))
    (d / "link").symlink_to(d / "ping")
    return d


def _caps(path: Path):
    try:
        return os.getxattr(path, NR.XATTR, follow_symlinks=False)
    except OSError:
        return None


@_root_only
def test_the_premise_a_program_asking_for_net_raw_is_refused_at_exec(bin_dir):
    assert _starts(bin_dir / "ping") == "refused at exec"
    assert _starts(bin_dir / "plain") == "ran, exit 0"


@_root_only
def test_without_net_raw_it_is_taken_out_and_the_program_starts(bin_dir):
    said = NR.mend_all([str(bin_dir)], bounding=WORKSTATION)
    assert said == [
        f"workstation: {bin_dir}/arping asked for cap_net_raw, which this machine never grants, "
        "so it could not start; it now starts without it (B976).",
        f"workstation: {bin_dir}/both asked for cap_net_raw, which this machine never grants, "
        "so it could not start; it now starts without it (B976).",
        f"workstation: {bin_dir}/ping asked for cap_net_raw, which this machine never grants, "
        "so it could not start; it now starts without it (B976).",
    ]
    # `setcap -r`, as measured: nothing left, so the attribute is gone.
    assert _caps(bin_dir / "ping") is None and _caps(bin_dir / "arping") is None
    # Only what cannot be granted: the grantable half stays.
    assert _caps(bin_dir / "both") == _cap(NET_BIND_SERVICE)
    assert _caps(bin_dir / "binder") == _cap(NET_BIND_SERVICE)
    for name in ("ping", "arping", "both", "binder", "plain"):
        assert _starts(bin_dir / name) == "ran, exit 0", name
    getcap = shutil.which("getcap")
    if getcap:
        shown = subprocess.run([getcap, str(bin_dir / "both")], capture_output=True, text=True)
        assert shown.stdout.split()[-1] == "cap_net_bind_service=ep"
    # Once is enough: a second run finds nothing to say.
    assert NR.mend_all([str(bin_dir)], bounding=WORKSTATION) == []


@_root_only
def test_where_net_raw_is_granted_nothing_changes(bin_dir):
    before = {p.name: _caps(p) for p in bin_dir.iterdir()}
    assert NR.mend_all([str(bin_dir)], bounding=DOCKER_DEFAULT) == []
    assert {p.name: _caps(p) for p in bin_dir.iterdir()} == before


@_root_only
def test_the_entry_point_apt_runs_mends_from_a_process_without_net_raw(bin_dir):
    """`python3 -m workstation.netraw` — apt's hook — in a process whose
    bounding set lacks CAP_NET_RAW, as the container's root's does; then the
    program starts from a process like it."""
    done = subprocess.run([sys.executable, "-B", "-m", "workstation.netraw", str(bin_dir)],
                          cwd=ROOT, preexec_fn=_without_net_raw, capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.count("never grants") == 3 and "/ping asked for cap_net_raw" in done.stdout
    assert _starts(bin_dir / "ping") == "ran, exit 0"
    assert _caps(bin_dir / "link") is None and (bin_dir / "link").is_symlink()


@_root_only
def test_a_file_it_may_not_change_is_said_not_hidden(bin_dir):
    def refuse(*a, **k):
        raise PermissionError(1, "Operation not permitted")
    said = NR.mend(str(bin_dir / "ping"), WORKSTATION, drop=refuse)
    assert said.endswith("so it cannot start, and it could not be changed (Operation not permitted).")
    assert _caps(bin_dir / "ping") == _cap(NET_RAW)


# ── in the image (opt-in: `PANTHEON_WORKSTATION_E2E=1`) ──────────────────────

from test_the_workstation_image_is_a_real_ubuntu_machine import (  # noqa: E402,F401 — fixture
    E2E_ENV, _docker, _docker_answers, image)

_PROBE = r"""
set -e
# A package whose maintainer script gives its program cap_net_raw=ep — what
# iputils-ping's does with setcap — built here, so this needs no network.
mkdir -p /tmp/pkg/DEBIAN /tmp/pkg/usr/bin
cp /usr/bin/true /tmp/pkg/usr/bin/pantheon-probe
printf 'Package: pantheon-probe\nVersion: 1\nArchitecture: all\nMaintainer: t <t@example.invalid>\nDescription: probe\n' > /tmp/pkg/DEBIAN/control
cat > /tmp/pkg/DEBIAN/postinst <<'EOF'
#!/bin/sh
python3 -c "import os, struct; os.setxattr('/usr/bin/pantheon-probe', 'security.capability', struct.pack('<IIIII', 0x02000001, 1 << 13, 0, 0, 0))"
EOF
chmod 755 /tmp/pkg/DEBIAN/postinst
dpkg-deb --build /tmp/pkg /tmp/pantheon-probe.deb > /dev/null
dpkg -i /tmp/pantheon-probe.deb > /dev/null          # dpkg alone: apt's hook does not run
echo "BOUNDING $(grep CapBnd /proc/self/status | cut -f2)"
if /usr/bin/pantheon-probe 2>/dev/null; then echo "DPKG started"; else echo "DPKG refused"; fi
apt-get install -y --reinstall /tmp/pantheon-probe.deb 2>&1 | grep '^workstation:' || true
if /usr/bin/pantheon-probe; then echo "APT started"; else echo "APT refused"; fi
"""


@pytest.mark.skipif(os.environ.get(E2E_ENV) != "1" or not _docker_answers(),
                    reason=f"runs the workstation image: set {E2E_ENV}=1 where Docker answers")
def test_in_the_image_apt_mends_what_it_installs_without_net_raw(image):
    """The overlay's `cap_drop: [NET_RAW]`, the image's own apt and hook."""
    done = _docker("run", "--rm", "--cap-drop", "NET_RAW", "--network", "none",
                   "--entrypoint", "bash", image, "-c", _PROBE, timeout=300)
    lines = done.stdout.splitlines()
    assert "BOUNDING 00000000a80405fb" in lines, done.stdout
    assert "DPKG refused" in lines, "the premise: refused at exec without NET_RAW"
    assert ("workstation: /usr/bin/pantheon-probe asked for cap_net_raw, which this machine "
            "never grants, so it could not start; it now starts without it (B976).") in lines
    assert lines[-1] == "APT started", done.stdout
    # With NET_RAW granted, apt's hook leaves the program as it was.
    kept = _docker("run", "--rm", "--network", "none", "--entrypoint", "bash", image, "-c",
                   _PROBE + "python3 -c \"import os; print('CAPS', os.getxattr("
                   "'/usr/bin/pantheon-probe', 'security.capability').hex())\"\n", timeout=300)
    assert "DPKG started" in kept.stdout and "APT started" in kept.stdout
    assert "never grants" not in kept.stdout
    assert "CAPS " + _cap(NET_RAW).hex() in kept.stdout.splitlines()


# ── the hook, as apt reads it ────────────────────────────────────────────────


def test_apt_runs_the_module_after_every_dpkg_run():
    apt_config = shutil.which("apt-config")
    if not apt_config:
        pytest.skip("apt-config is not installed here")
    done = subprocess.run([apt_config, "-c", str(CONF), "dump", "DPkg::Post-Invoke"],
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    hooks = [line.split(" ", 1)[1].strip().rstrip(";").strip('"')
             for line in done.stdout.splitlines() if line.startswith("DPkg::Post-Invoke::")]
    ours = [h for h in hooks if "workstation.netraw" in h]
    assert ours == ["cd /opt/pantheon-workstation && python3 -B -m workstation.netraw || true"]
