# SPDX-License-Identifier: AGPL-3.0-or-later
"""The VM backend: a machine of their own for each person — `P20-07`.

    python3 -m workstation.vm        # what `vm.Dockerfile` runs, under `docker/workstation-vm.yml`

**WHY A MACHINE PER PERSON, NOT ONE VM FOR EVERYONE.** `D-2026-09-30-03` made
"one per person" one Unix account inside one container, and named the VM
backend as *the stronger wall between people when that matters*. One VM with
an account per person would be the same wall as the container — Unix
permissions — around a different kernel: with `sudo` on (the default) one
person's agent is root in it and reads the others' homes, exactly as in the
container. So each person gets a VM of their own, made from one Ubuntu image,
and the wall between two people is a hypervisor. A side effect the container
cannot offer: *Reset to clean* is a fresh machine, not a fresh home, so it also
takes back what a root agent did outside its home.

**ONE PROTOCOL, AND PANTHEON NEVER KNOWS.** This process answers
`workstation/protocol.py` on port 7040 through `agentd`'s own HTTP layer (the
token, the bounds and the error shapes are that file's, once), and forwards
each person's routes to the daemon inside that person's machine — the same
`agentd` with `--system ubuntu --backend vm`. `health`, `config` and `account`
are answered here: `account` looks at the disks without starting anything
(`B959`). A machine starts on its person's first call and the call waits for it
(`protocol.MACHINE_START_S`, which the client honours for a `vm` backend only).

**WHAT EACH MACHINE IS GIVEN, AND WHAT IT IS NOT.** A copy-on-write disk over
the shared image; QEMU's user-mode network (outbound only, through this
container's network; nothing reaches the machine except the one forwarded port,
bound to this container's loopback); and a small read-only app disk made at
each start with the daemon's code and **that machine's own token** — never
Pantheon's. A person who is root in their machine can read their token and
reach the other machines' forwarded ports through QEMU's host alias, and every
one of them refuses it. Pantheon's token is checked here and never leaves.

**THE IMAGE.** Made once, on the first start, from Ubuntu's cloud image (in the
container image, its checksum verified against Ubuntu's signed list at build):
a cloud-init seed writes `provision.sh` and `vm-guest.sh` into it and runs
them — the same list the container image is built from (`Law 14`) — then it
powers off. The serial console's last word says whether it worked. A new
Pantheon whose provisioning changed makes a new image; machines made from the
old one keep it until they are reset (a disk cannot change its base).

**KVM WHEN THE HOST HAS IT, TCG WHEN IT DOES NOT, AND SAID.** `/dev/kvm` is
opened if it is there; if it is not, it is made (`mknod`, a capability Docker
grants by default) and opened, which works exactly when the host has KVM and
the compose overlay's one device-cgroup rule lets this container use it. No
`privileged`, no device list that fails to start on a host without KVM.
`health.machine.accel` says which, and the panel says what TCG costs.

Standard library only, nothing from Pantheon (the package's rule); QEMU,
`qemu-img` and `genisoimage` are in `vm.Dockerfile`.
"""
from __future__ import annotations

import argparse
import base64
import collections
import contextlib
import errno
import hashlib
import http.client
import json
import logging
import os
import queue
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from workstation import protocol as P
from workstation import service
from workstation.agentd import System, Workstation, WorkstationError, load_or_create_token, make_server

logger = logging.getLogger("pantheon.workstation.vm")

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_STATE = Path("/var/lib/pantheon-workstation-vm")
DEFAULT_BASE_IMAGE = Path("/opt/pantheon-workstation/vm/ubuntu-cloud.img")
DEFAULT_PAYLOAD = Path("/opt/pantheon-workstation/payload")

APP_LABEL = "PWSAPP"
APP_MOUNT = "/opt/pantheon-workstation/app"
PROVISION_DIR = "/opt/pantheon-workstation/provision"
IMAGE_READY = "PANTHEON-WORKSTATION-IMAGE-READY"
IMAGE_FAILED = "PANTHEON-WORKSTATION-IMAGE-FAILED"
# What `vm-guest.sh` and `provision.sh` read from the payload directory: the
# two scripts, and every file under these two folders (listed by walking them,
# so a file added to the skeleton is not one more list to remember).
PAYLOAD_SCRIPTS = ("provision.sh", "vm-guest.sh")
PAYLOAD_DIRS = ("firefox", "skel")


def payload_files(payload: Path) -> List[str]:
    """The payload's files, relative, in a stable order."""
    rels = list(PAYLOAD_SCRIPTS)
    for folder in PAYLOAD_DIRS:
        rels += sorted(str(p.relative_to(payload)) for p in (payload / folder).rglob("*")
                       if p.is_file())
    return rels
KVM_MAJOR, KVM_MINOR = 10, 232  # the kernel's fixed misc-device number for /dev/kvm

# Environment the launcher reads, all optional.
ENV = {
    "memory": "PANTHEON_WORKSTATION_VM_MEMORY_MIB",
    "cpus": "PANTHEON_WORKSTATION_VM_CPUS",
    "disk": "PANTHEON_WORKSTATION_VM_DISK_GIB",
    "accel": "PANTHEON_WORKSTATION_VM_ACCEL",
    # `B979`: minutes a machine may sit unused before it is powered off (0:
    # never), and how many may run at once (`auto`: what the memory holds).
    "idle": "PANTHEON_WORKSTATION_VM_IDLE_MIN",
    "max_running": "PANTHEON_WORKSTATION_VM_MAX_RUNNING",
    # Build-time knobs for making the image, like the container image's
    # `APT_MIRROR` and `build-ca` (`provision.sh`). None stays in the image.
    "apt_mirror": "PANTHEON_WORKSTATION_VM_APT_MIRROR",
    "apt_proxy": "PANTHEON_WORKSTATION_VM_APT_PROXY",
    "apt_ca": "PANTHEON_WORKSTATION_VM_APT_CA",
}
DEFAULT_MEMORY_MIB = 2048
DEFAULT_CPUS = 2
DEFAULT_DISK_GIB = 20
# Making the image installs the desktop, the tools and Firefox inside the VM.
# Measured `P20-07`: see the row. Generous, because TCG is that slow.
IMAGE_TIMEOUT_S = 4 * 3600.0
# Room to make it in: Ubuntu's image copied, then grown by the provisioning to
# 2.5 GB measured (`P20-07`), with headroom for apt's downloads.
IMAGE_NEEDS_BYTES = 5 * 10**9
STOP_GRACE_S = 90.0

# ── `B979`: a machine nobody uses is powered off ─────────────────────────────
#
# A running machine keeps its memory: measured `P20-07`, 760 MiB resident for
# a 2048 MiB machine under TCG after five idle minutes — until the host
# restarted, and nothing capped how many ran. So a machine with no request in
# flight and none for `PANTHEON_WORKSTATION_VM_IDLE_MIN` minutes is powered off
# cleanly (`Machine.stop`, ACPI then QMP `quit`), its disk kept: the next call
# boots it, as the first one did. A program left running in it stops with it
# — the protocol has no command running past its answer, and the panel says the
# machine is off. The time is the operator's, in `.env` beside the machine's
# memory and CPUs, because it is the host's capacity that it trades against;
# `health.machines` says what it is.
#
# And at most `PANTHEON_WORKSTATION_VM_MAX_RUNNING` machines run at once. The
# default is what the host's memory holds — its memory (the container's cgroup
# limit when lower) less `MEMORY_RESERVE_MIB` for the host itself and
# Pantheon, over each machine's — and never less than one; a machine past it
# is refused with a sentence naming the limit and when one frees up.
DEFAULT_IDLE_STOP_MIN = 30
MEMORY_RESERVE_MIB = 2048
HOUSEKEEPING_S = 30.0


# ── `B984`: each machine keeps its host's time ───────────────────────────────
#
# `vm-guest.sh` masks systemd-timesyncd: it calls ntp.ubuntu.com (measured
# `P20-07`), which nobody chose (`Law 16`). The guest kernel takes the time
# from QEMU's RTC at boot and then keeps its own, which under TCG can drift.
# The reference that phones nowhere is this host's own clock, and there are
# three ways to give it to a machine:
#
#   * the RTC — QEMU drives it from the host's clock, but sets it from
#     `time()` in whole seconds when the machine starts (`rtc_set_date_from_
#     host`, hw/rtc/mc146818rtc.c, read 2026-10-01), so it runs up to a second
#     behind the host for the machine's life: "within a second" at best;
#   * QEMU's guest agent (`guest-set-time`) — exact, but not in the machine
#     image, and adding it is a new image that running machines get only when
#     they are reset;
#   * the daemon in the machine, over its forwarded port and its own token —
#     the one channel the host already has to every machine, under every
#     network mode (`restrict=on` keeps forwarded ports). Chosen.
#
# The host reads the machine's clock (`protocol.ROUTES["clock"]`) between two
# readings of its own and takes the middle, as NTP does: the error is at most
# half the round trip, and a round trip over `CLOCK_MAX_RTT_S` measures nothing
# and changes nothing. A machine surely more than `CLOCK_STEP_S` out (beyond
# that half round trip) is stepped — when
# it starts, and every `CLOCK_SYNC_S` after by the housekeeping thread. That is
# not a use: keeping a machine's time never keeps it from being powered off.
CLOCK_SYNC_S = 60.0
CLOCK_STEP_S = 0.25
CLOCK_MAX_RTT_S = 1.0


def idle_stop_from_env(raw: str) -> Optional[float]:
    """Seconds, from the minutes in `PANTHEON_WORKSTATION_VM_IDLE_MIN`; None
    for 0 (never). Empty is the default."""
    raw = (raw or "").strip()
    if not raw:
        return DEFAULT_IDLE_STOP_MIN * 60.0
    if not raw.isdigit() or int(raw) > 7 * 24 * 60:
        raise SystemExit(f"{ENV['idle']} is a whole number of minutes from 0 (never) to "
                         f"{7 * 24 * 60}.")
    return int(raw) * 60.0 or None


def host_memory_mib(meminfo: Path = Path("/proc/meminfo"),
                    cgroup: Path = Path("/sys/fs/cgroup/memory.max")) -> Optional[int]:
    """The memory this host's machines share, in MiB: the machine's, or this
    container's cgroup limit when it is lower. None when neither can be read."""
    total = None
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) // 1024
                break
    except (OSError, ValueError, IndexError):
        total = None
    try:
        limit = cgroup.read_text().strip()
        if limit.isdigit():
            capped = int(limit) // (1024 * 1024)
            total = capped if total is None else min(total, capped)
    except OSError:
        pass  # no cgroup v2 limit to read: the machine's memory is the answer
    return total


def max_running_from_env(raw: str, memory_mib: int, total_mib: Optional[int]) -> Optional[int]:
    """`PANTHEON_WORKSTATION_VM_MAX_RUNNING`: a number (0: no limit), or `auto`
    / empty for what the memory holds — None when the memory cannot be read,
    rather than a number made up."""
    raw = (raw or "").strip().lower()
    if raw in ("", "auto"):
        if total_mib is None:
            return None
        return max(1, (total_mib - MEMORY_RESERVE_MIB) // max(1, int(memory_mib)))
    if not raw.isdigit() or int(raw) > 1024:
        raise SystemExit(f"{ENV['max_running']} is auto, or a whole number of machines from 0 "
                         "(no limit) to 1024.")
    return int(raw) or None


# `B992`: how much of the network each mode leaves (narrowest last), who holds
# each on this backend, and what a machine that cannot hold *internet* is told.
_NETWORK_WIDTH = {"full": 0, "internet": 1, "none": 2}
_HOLDER = {"none": "hypervisor", "internet": "accounts", "full": "none"}
INTERNET_UNHELD_SENTENCE = (
    "Your workstation machine cannot hold the network an admin chose (internet only): it was "
    "made from an older image without the rules for it, so it was not started. Reset your "
    "workstation to make it from the current image.")


def _minutes(seconds: float) -> str:
    n = max(1, round(seconds / 60))
    return "1 minute" if n == 1 else f"{n} minutes"


# ── what the host can do ─────────────────────────────────────────────────────

def choose_accel(dev: Path = Path("/dev/kvm"), *, want: str = "auto",
                 mknod: Callable = os.mknod, opener: Callable = os.open) -> Tuple[str, str]:
    """`(accel, why)`: `kvm` when /dev/kvm opens, `tcg` with the reason when not.

    A missing node is made first: inside a container the node is absent
    unless passed in, but the kernel's device is not, and the compose
    overlay's device-cgroup rule (`c 10:232 rwm`) is what permits opening
    it. On a host without KVM the open fails and the answer is TCG, said."""
    if want == "tcg":
        return "tcg", "TCG was asked for."
    if not os.path.exists(dev):
        try:
            mknod(str(dev), stat.S_IFCHR | 0o660, os.makedev(KVM_MAJOR, KVM_MINOR))
        except OSError as e:
            if e.errno != errno.EEXIST:
                why = f"there is no {dev} and it could not be made ({e.strerror or e})"
                if want == "kvm":
                    raise WorkstationError("unavailable", f"KVM was asked for, but {why}.")
                return "tcg", f"No KVM: {why}."
    try:
        fd = opener(str(dev), os.O_RDWR | os.O_CLOEXEC)
    except OSError as e:
        why = {errno.ENXIO: "the host kernel has no KVM device",
               errno.ENODEV: "the host kernel has no KVM device",
               errno.ENOENT: "the host has no KVM",
               errno.EPERM: "this container may not use it",
               errno.EACCES: "this container may not use it"}.get(e.errno, e.strerror or str(e))
        if want == "kvm":
            raise WorkstationError("unavailable", f"KVM was asked for, but {dev} did not open: {why}.")
        return "tcg", f"No KVM: {dev} did not open ({why}). Machines run emulated, which is slow."
    os.close(fd)
    return "kvm", f"KVM: {dev} opened."


def qemu_argv(*, name: str, accel: str, cpus: int, memory_mib: int, disk: Path,
              iso: Optional[Path], console: Path, qmp: Path,
              forward: Optional[Tuple[str, int]] = None,
              dump: Optional[Path] = None, qemu: str = "qemu-system-x86_64",
              restrict: bool = False) -> List[str]:
    """One machine's command line. No display device (the desktop is Xvfb
    inside), no default devices, the serial console to a file, one virtio
    disk, the read-only seed or app disk (`iso`), user-mode network with at most one
    port forwarded to this container's loopback, and a QMP socket to power it
    off cleanly."""
    if accel not in P.ACCELS:
        raise ValueError(f"accel is one of {P.ACCELS}")
    argv = [qemu, "-name", name, "-nodefaults", "-no-user-config",
            "-machine", "q35", "-accel", "kvm" if accel == "kvm" else "tcg,thread=multi,tb-size=256",
            "-cpu", "host" if accel == "kvm" else "max",
            "-smp", str(int(cpus)), "-m", str(int(memory_mib)),
            "-display", "none", "-serial", f"file:{console}",
            "-rtc", "base=utc,driftfix=slew",
            "-drive", f"if=virtio,file={disk},format=qcow2,discard=unmap",
            "-device", "virtio-rng-pci",
            "-qmp", f"unix:{qmp},server=on,wait=off"]
    if iso is not None:
        # A read-only virtio disk, not a CD-ROM: udev labels a virtio disk as
        # soon as it is probed, where a CD-ROM's label waits on `cdrom_id`
        # finding media — and under TCG that missed the mount's deadline
        # (measured `P20-07`: "Dependency failed for /opt/pantheon-workstation/app").
        argv += ["-drive", f"if=virtio,file={iso},format=raw,readonly=on"]
    netdev = "user,id=net0"
    if restrict:
        # `B992`: the admin's *none*, held by QEMU itself (`Fleet.network_report`).
        netdev += ",restrict=on"
    if forward is not None:
        host, port = forward
        netdev += f",hostfwd=tcp:{host}:{int(port)}-:{P.DEFAULT_PORT}"
    argv += ["-netdev", netdev, "-device", "virtio-net-pci,netdev=net0"]
    if dump is not None:
        # Every packet the machine sends or receives, for measuring what it
        # talks to (`Law 16`). Never on by default.
        argv += ["-object", f"filter-dump,id=dump0,netdev=net0,file={dump}"]
    return argv


def make_iso(out: Path, label: str, root: Path, *, keep_modes: bool,
             tool: str = "genisoimage") -> None:
    """An ISO 9660 disk of `root`. `keep_modes` records each file's real mode
    and owner (Rock Ridge `-R`), so a 0600 token stays root's inside the
    machine; otherwise everything is readable (`-r`), which is what a
    cloud-init seed wants."""
    argv = [tool, "-quiet", "-output", str(out), "-volid", label, "-joliet",
            "-R" if keep_modes else "-r", str(root)]
    done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode != 0:
        raise WorkstationError("unavailable", f"{tool} failed: "
                               f"{done.stderr.decode('utf-8', 'replace').strip()[-300:]}")


# ── the image every machine starts from ───────────────────────────────────────

def guest_unit() -> str:
    """The daemon's unit inside each machine (`workstation/service.py`): its
    code and its token from the app disk, `--backend vm`."""
    argv = service.exec_argv(backend="vm", token_file=f"{APP_MOUNT}/token")
    return service.unit(description="Pantheon workstation daemon (VM backend, P20-07)",
                        workdir=APP_MOUNT, argv=argv, requires_mounts=APP_MOUNT)


def payload_digest(payload: Path, base_digest: str) -> str:
    """What decides an image: Ubuntu's image, the provisioning files and the
    unit. The daemon's code is not in it — it comes on the app disk at every
    start — so a code change needs no new image."""
    h = hashlib.sha256()
    h.update(base_digest.encode())
    for rel in payload_files(payload):
        h.update(rel.encode() + b"\0" + (payload / rel).read_bytes() + b"\0")
    h.update(guest_unit().encode())
    return h.hexdigest()


def image_user_data(payload: Path, *, apt_mirror: str = "", apt_proxy: str = "",
                    apt_ca: Optional[bytes] = None) -> str:
    """The cloud-init seed that makes the image. JSON after the `#cloud-config`
    header — JSON is YAML, and the standard library writes it.

    Nothing secret is in it: no token is in the image, ever."""
    files = []

    def put(rel: str, data: bytes, mode: str) -> None:
        files.append({"path": f"{PROVISION_DIR}/{rel}", "encoding": "b64",
                      "content": base64.b64encode(data).decode("ascii"),
                      "owner": "root:root", "permissions": mode})

    for rel in payload_files(payload):
        put(rel, (payload / rel).read_bytes(), "0755" if rel.endswith(".sh") else "0644")
    put("pantheon-workstation.service", guest_unit().encode(), "0644")
    env = []
    if apt_mirror:
        env.append(f"APT_MIRROR={apt_mirror}")
    if apt_proxy:
        env.append(f"APT_PROXY={apt_proxy}")
    if apt_ca:
        put("provision-ca.crt", apt_ca, "0644")
        env.append(f"PROVISION_CA={PROVISION_DIR}/provision-ca.crt")
    if env:
        put("provision.env", ("\n".join(env) + "\n").encode(), "0600")
    config = {
        # Nobody logs in: no default user, no password, no root login.
        "users": [],
        "disable_root": True,
        "ssh_pwauth": False,
        "package_update": False,
        "package_upgrade": False,
        "apt": {"preserve_sources_list": True},
        "write_files": files,
        "runcmd": [["sh", f"{PROVISION_DIR}/vm-guest.sh", "bake"]],
        "power_state": {"mode": "poweroff", "condition": True, "timeout": 120,
                        "message": "Pantheon workstation image made; powering off."},
    }
    return "#cloud-config\n" + json.dumps(config, indent=1) + "\n"


def image_meta_data(digest: str) -> str:
    return f"instance-id: pantheon-image-{digest[:16]}\nlocal-hostname: pantheon-workstation\n"


def read_verdict(console: Path) -> Optional[bool]:
    """True / False from the console's last word on the image, None if it
    said neither."""
    try:
        text = console.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    ok, failed = text.rfind(IMAGE_READY), text.rfind(IMAGE_FAILED)
    if ok < 0 and failed < 0:
        return None
    return ok > failed


def tail(path: Path, lines: int = 8) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    keep = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " | ".join(keep[-lines:])


def qmp_command(sock_path: Path, command: str, timeout: float = 5.0) -> bool:
    """Send one QMP command (`system_powerdown`, `quit`). False if the socket
    was not there to take it."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(sock_path))
            f = s.makefile("rwb")
            f.readline()  # the greeting
            for cmd in ("qmp_capabilities", command):
                f.write(json.dumps({"execute": cmd}).encode() + b"\n")
                f.flush()
                while True:
                    line = f.readline()
                    if not line:
                        return False
                    msg = json.loads(line)
                    if "return" in msg or "error" in msg:
                        break
            return True
    except (OSError, ValueError):
        return False


# ── one person's machine ──────────────────────────────────────────────────────

class Machine:
    """What the fleet needs of a person's machine. `QemuMachine` is the real
    one; a test gives the fleet another, with the same five methods, so the
    forwarding is driven for real without a hypervisor."""

    account: str
    port: Optional[int]
    token: str

    def exists(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def running(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def start(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def stop(self, *, graceful: bool = True) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def destroy(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


def mint_machine_token(path: Path) -> str:
    """This machine's own token: made once, kept 0600 beside its disk."""
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        return existing
    token = P.TOKEN_PREFIX + secrets.token_urlsafe(P.TOKEN_ENTROPY_BYTES)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    return token


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class QemuMachine(Machine):
    """A person's VM: `<state>/machines/<account>/` holds its disk (over the
    image it was made from), its token, its console and its QMP socket."""

    def __init__(self, fleet: "Fleet", account: str) -> None:
        self.fleet = fleet
        self.account = account
        self.dir = fleet.state / "machines" / account
        self.disk = self.dir / "disk.qcow2"
        self.console = self.dir / "console.log"
        self.qmp = self.dir / "qmp.sock"
        self.port: Optional[int] = None
        self.proc: Optional[subprocess.Popen] = None
        self.token = ""

    def exists(self) -> bool:
        return self.disk.exists()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _create(self) -> None:
        image = self.fleet.current_image()
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)
        tmp = self.dir / "disk.qcow2.tmp"
        self.fleet.run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2",
                        "-b", str(image), str(tmp)])
        os.replace(tmp, self.disk)

    def _app_disk(self) -> Path:
        """The daemon's code and this machine's token, as a read-only disk."""
        root = self.dir / "app"
        shutil.rmtree(root, ignore_errors=True)
        (root / "workstation").mkdir(parents=True)
        for src in sorted(PACKAGE_DIR.glob("*.py")):
            shutil.copy2(src, root / "workstation" / src.name)
            os.chmod(root / "workstation" / src.name, 0o644)
        fd = os.open(root / "token", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self.token + "\n")
        iso = self.dir / "app.iso"
        make_iso(iso, APP_LABEL, root, keep_modes=True)
        shutil.rmtree(root, ignore_errors=True)
        return iso

    def start(self) -> None:
        if self.running():
            return
        if not self.exists():
            self._create()
        self.token = mint_machine_token(self.dir / "token")
        self._app_disk()  # at the path `Fleet.machine_argv` names
        self.port = free_port()
        try:
            self.qmp.unlink()
        except FileNotFoundError:
            pass  # no socket left from a previous run: nothing to clear
        self.console.write_bytes(b"")
        argv = self.fleet.machine_argv(self)
        logger.info("starting the machine for %s (%s)", self.account, self.fleet.accel)
        # QEMU's own messages to a file, not a pipe: nothing reads a pipe
        # while the machine runs, and a full one would stall it.
        with open(self.dir / "qemu.log", "wb") as log:
            self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=log, start_new_session=True)

    def stop(self, *, graceful: bool = True) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            self.proc = None
            return
        if graceful and qmp_command(self.qmp, "system_powerdown"):
            try:
                proc.wait(timeout=STOP_GRACE_S)
            except subprocess.TimeoutExpired:
                logger.warning("the machine for %s did not power off in %.0f s; stopping it",
                               self.account, STOP_GRACE_S)
        if proc.poll() is None:
            qmp_command(self.qmp, "quit")
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        self.proc = None

    def destroy(self) -> None:
        self.stop(graceful=False)
        shutil.rmtree(self.dir, ignore_errors=True)

    def why_not(self) -> str:
        """What the machine said before it stopped answering, for a sentence."""
        return tail(self.dir / "qemu.log", 2) or tail(self.console, 3)


# ── every person's machine ────────────────────────────────────────────────────

class Fleet(System):
    """The VM backend's `System`: what `health`, `config` and `account` ask
    of a system, answered from the machines' disks — and the machines
    themselves, started on demand."""

    backend = "vm"

    def __init__(self, state: Path, *, accel: str, accel_why: str = "",
                 base_image: Path = DEFAULT_BASE_IMAGE, payload: Path = DEFAULT_PAYLOAD,
                 memory_mib: int = DEFAULT_MEMORY_MIB, cpus: int = DEFAULT_CPUS,
                 disk_gib: int = DEFAULT_DISK_GIB,
                 machine_factory: Optional[Callable[["Fleet", str], Machine]] = None,
                 image_options: Optional[Dict] = None, need_image: bool = True,
                 start_timeout: float = P.MACHINE_START_S - 30.0,
                 idle_stop_s: Optional[float] = DEFAULT_IDLE_STOP_MIN * 60.0,
                 max_running: Optional[int] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self.state = Path(state)
        (self.state / "machines").mkdir(parents=True, exist_ok=True)
        (self.state / "images").mkdir(parents=True, exist_ok=True)
        self.accel, self.accel_why = accel, accel_why
        self.base_image, self.payload = Path(base_image), Path(payload)
        self.memory_mib, self.cpus, self.disk_gib = memory_mib, cpus, disk_gib
        self.factory = machine_factory or QemuMachine
        self.image_options = dict(image_options or {})
        self.start_timeout = start_timeout
        self.network = self._persisted_network()  # `B992`
        # Per machine: whether it was started with `restrict=on`, and what its
        # own daemon last said it holds (`network_report`).
        self._restricted: Dict[str, bool] = {}
        self._guest_net: Dict[str, Dict] = {}
        self._retiring: List[threading.Thread] = []
        self.image_state = "preparing" if need_image else "ready"
        self.image_why = ""
        self._image: Optional[Path] = None
        self._machines: Dict[str, Machine] = {}
        self._locks: Dict[str, threading.Lock] = collections.defaultdict(threading.Lock)
        self._registry = threading.Lock()
        self.sudo = self._persisted_sudo()
        # `B979`: when each machine was last used and how many requests are in
        # it now; the idle time and the cap (module comment above).
        self.idle_stop_s = idle_stop_s
        self.max_running = max_running
        self._clock = clock
        self._use: Dict[str, List] = {}          # account -> [requests in flight, last use]
        self._use_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._last_clock_sync = 0.0  # `B984`

    # -- the System interface ---------------------------------------------------

    def home(self, account: str) -> Path:
        # Where the home is inside that person's machine.
        return Path("/home") / account

    def accounts(self) -> List[str]:
        root = self.state / "machines"
        return sorted(p.name for p in root.iterdir()
                      if P.ACCOUNT_RE.match(p.name) and self.machine_for(p.name).exists())

    def has_home(self, account: str) -> bool:
        """`B959`: a person's machine exists — looked at, nothing started."""
        return self.machine_for(account).exists()

    def machine(self) -> Dict:
        return {"virtualization": "kvm" if self.accel == "kvm" else "qemu",
                "accel": self.accel, "image": self.image_state}

    def machines(self) -> Dict:
        """`B979`: `health.machines` — how many run, the most that may, and
        how long one may sit unused (None: no limit / never)."""
        return {"running": len(self.running_accounts()), "max_running": self.max_running,
                "idle_stop_s": self.idle_stop_s}

    def running_accounts(self) -> List[str]:
        with self._registry:
            return sorted(a for a, m in self._machines.items() if m.running())

    def set_sudo(self, on: bool) -> None:
        on = bool(on)
        path = self.state / "settings.json"
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"sudo": on}, f)
        os.replace(tmp, path)
        self.sudo = on
        for account, m in list(self._machines.items()):
            if m.running():
                try:
                    self.forward(account, "config", {"sudo": on}, start=False)
                except WorkstationError as e:
                    logger.warning("could not tell %s's machine sudo is %s: %s",
                                   account, "on" if on else "off", e.message)

    # -- `B992`: the admin's network mode, held as far as this backend can ------
    #
    # *none* is held OUTSIDE each machine: its user-mode network is started with
    # `restrict=on`, and libslirp — QEMU's network stack, in QEMU's own process —
    # then drops every packet the machine sends out or to the host, except DHCP
    # and the one forwarded port the daemon answers on (read in libslirp's
    # `udp.c`, `udp6.c`, `tcp_input.c`, `ip_icmp.c`, `ip6_icmp.c`, 2026-10-01: a
    # new TCP connection is answered with a reset, UDP and ICMP dropped). Root in
    # the machine cannot change a netdev it has no handle on. A netdev cannot be
    # changed on a running machine, so a running machine whose network is not
    # the admin's is powered off (cleanly, its disk kept) and boots with it on
    # its next use; until then the report says the mode is still pending.
    #
    # *internet* cannot be said to user mode — it does not filter by
    # destination — so it is held INSIDE each machine: pushed to the machine's
    # daemon like `sudo`, which holds it for workstation accounts with `nft`
    # (`P20-06`'s accounts layer; the machine image has `nftables` since then).
    # That holds while `sudo` is off: an agent with `sudo` is root in its
    # machine and can delete the table — and the panel says exactly that. A
    # machine that answers without holding it (made from an older image) is
    # powered off and refused with a sentence, never run under a wider network.
    #
    # Not done: a gate in front of the VM host (`P20-06`'s, as the container
    # has). Its rules hold for the whole namespace QEMU's sockets live in, which
    # is also where this host makes the machine image on its first start, from
    # Ubuntu's and Mozilla's repositories: under *none* or *internet* the image
    # could not be made. Holding *internet* against root here needs rules
    # scoped to the machines' QEMU processes alone — filed, not built.

    def _network_path(self) -> Path:
        return self.state / "network.json"

    def _persisted_network(self) -> str:
        try:
            value = json.loads(self._network_path().read_text(encoding="utf-8")).get("network")
        except (OSError, ValueError, AttributeError):
            return "full"  # the product's default (`D-2026-09-30-03`)
        return value if value in P.NETWORK_MODES else "full"

    def set_network(self, mode: str) -> None:
        path = self._network_path()
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"network": mode}, f)
        os.replace(tmp, path)
        self.network = mode
        for account in self.running_accounts():
            if self._restricted.get(account, False) != (mode == "none"):
                self._retire(account)
                continue
            try:
                self._hold(account, self.machine_for(account))
            except WorkstationError as e:
                logger.warning("%s's machine did not take network %s: %s", account, mode,
                               e.message)
                self._retire(account)

    def _hold(self, account: str, m: Machine) -> None:
        """Tell the machine's daemon the mode and keep what it says it holds;
        a machine that cannot hold *internet* is a `WorkstationError`."""
        answer = self._call(m, "config", body={"network": self.network}) or {}
        self._guest_net[account] = {k: answer.get(k) for k in
                                    ("network_in_force", "network_enforcement")}
        if self.network == "internet" and not self._holds_internet(account):
            raise WorkstationError("unavailable", INTERNET_UNHELD_SENTENCE)

    def _holds_internet(self, account: str) -> bool:
        said = self._guest_net.get(account) or {}
        return (said.get("network_enforcement") == "accounts"
                and said.get("network_in_force") == "internet")

    def _wrong_network(self, account: str) -> bool:
        return (self._restricted.get(account, False) != (self.network == "none")
                or (self.network == "internet" and not self._holds_internet(account)))

    def _retire(self, account: str) -> None:
        """Power the machine off in the background (a clean power-off takes up
        to `STOP_GRACE_S`), holding its lock so a call waits and then boots it
        with the network it should have."""
        def go() -> None:
            with self._locks[account]:
                m = self.machine_for(account)
                if m.running() and self._wrong_network(account):
                    logger.info("powering off %s's machine: its network is not %s yet",
                                account, self.network)
                    m.stop(graceful=True)
        t = threading.Thread(target=go, name=f"retire-{account}", daemon=True)
        self._retiring.append(t)
        t.start()

    def wait_retired(self, timeout: float = STOP_GRACE_S + 20) -> None:
        for t in list(self._retiring):
            t.join(timeout)
        self._retiring = [t for t in self._retiring if t.is_alive()]

    def _held(self, account: str) -> str:
        if self._restricted.get(account, False):
            return "none"
        said = self._guest_net.get(account) or {}
        if said.get("network_enforcement") == "accounts" and \
                said.get("network_in_force") in P.NETWORK_MODES:
            return said["network_in_force"]
        return "full"

    def network_report(self) -> Dict:
        """What is in force on every machine that can reach anything: the
        widest mode any running machine holds — never more than is kept — or,
        with none running, the mode a machine starts with (it is not let run
        otherwise). `network_enforcement` names who holds the chosen mode
        (`hypervisor` for *none*, `accounts` for *internet*), or, under *full*,
        whoever still holds a narrower one. Root in a machine cannot reach
        this host's namespace, so `root_can_change_network` is false here; how
        far `accounts` holds is the panel's to say (`network_view`)."""
        held = [self._held(a) for a in self.running_accounts()] or [self.network]
        in_force = min(held, key=_NETWORK_WIDTH.__getitem__)
        by = _HOLDER[self.network if self.network != "full" else in_force]
        return {"network_in_force": in_force, "network_enforcement": by,
                "root_can_change_network": False}

    def _persisted_sudo(self) -> bool:
        try:
            value = json.loads((self.state / "settings.json").read_text(encoding="utf-8")).get("sudo")
        except (OSError, ValueError, AttributeError):
            return True  # the product's default (`D-2026-09-30-03`)
        return value if isinstance(value, bool) else True

    # -- the image --------------------------------------------------------------

    def run(self, argv: List[str]) -> None:
        done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if done.returncode != 0:
            raise WorkstationError("unavailable", f"{argv[0]} failed: "
                                   f"{done.stderr.decode('utf-8', 'replace').strip()[-300:]}")

    def current_image(self) -> Path:
        if self.image_state != "ready" or self._image is None:
            raise WorkstationError("unavailable", self.image_sentence())
        return self._image

    def image_sentence(self) -> str:
        if self.image_state == "failed":
            return ("The workstation's machine image could not be made, so no machine can start: "
                    f"{self.image_why or 'see the workstation container log'}. Restart the "
                    "workstation container to try again.")
        return ("The workstation is still making the machine image every person's machine starts "
                "from — Ubuntu, the desktop, the tools and Firefox, once, on its first start. With "
                "KVM that takes minutes; without it, much longer. Try again shortly.")

    def _base_digest(self) -> str:
        """The base image's SHA-256, kept beside it so a restart need not hash
        600 MB again — keyed on size and modification time."""
        st = self.base_image.stat()
        key = f"{st.st_size}:{int(st.st_mtime)}"
        cache = self.state / "images" / "base.sha256"
        try:
            k, digest = cache.read_text().split()
            if k == key:
                return digest
        except (OSError, ValueError):
            pass  # no usable cache: the image is hashed again below
        h = hashlib.sha256()
        with open(self.base_image, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        cache.write_text(f"{key} {h.hexdigest()}\n")
        return h.hexdigest()

    def prepare_image(self) -> None:
        """The image for this payload: found, or made (module docstring). Sets
        `image_state`; never raises."""
        try:
            digest = payload_digest(self.payload, self._base_digest())
            image = self.state / "images" / f"image-{digest[:16]}.qcow2"
            if image.exists():
                self._image, self.image_state = image, "ready"
                logger.info("machine image %s is ready", image.name)
                return
            self.image_state = "preparing"
            started = time.monotonic()
            self._make_image(image, digest)
            self._image, self.image_state = image, "ready"
            logger.info("machine image %s made in %.0f s (%s)", image.name,
                        time.monotonic() - started, self.accel)
            self._forget_unused_images(keep=image)
        except WorkstationError as e:
            self.image_state, self.image_why = "failed", e.message
            logger.error("the machine image could not be made: %s", e.message)
        except Exception as e:  # noqa: BLE001 — the reason goes to the panel, the trace to the log
            self.image_state, self.image_why = "failed", f"{type(e).__name__}: {e}"
            logger.exception("the machine image could not be made")

    def _make_image(self, image: Path, digest: str) -> None:
        work = self.state / "images" / "making"
        shutil.rmtree(work, ignore_errors=True)
        free = shutil.disk_usage(self.state).free
        if free < IMAGE_NEEDS_BYTES:
            raise WorkstationError(
                "unavailable", f"making it needs about {IMAGE_NEEDS_BYTES // 10**9} GB free where "
                               f"the workstation keeps its machines, and {free / 10**9:.1f} GB is")
        (work / "seed").mkdir(parents=True)
        disk = work / "disk.qcow2"
        self.run(["qemu-img", "convert", "-O", "qcow2", str(self.base_image), str(disk)])
        self.run(["qemu-img", "resize", "-q", str(disk), f"{int(self.disk_gib)}G"])
        opts = self.image_options
        ca = Path(opts["apt_ca"]).read_bytes() if opts.get("apt_ca") else None
        (work / "seed" / "user-data").write_text(image_user_data(
            self.payload, apt_mirror=opts.get("apt_mirror", ""),
            apt_proxy=opts.get("apt_proxy", ""), apt_ca=ca), encoding="utf-8")
        (work / "seed" / "meta-data").write_text(image_meta_data(digest), encoding="utf-8")
        seed = work / "seed.iso"
        make_iso(seed, "cidata", work / "seed", keep_modes=False)
        console = work / "console.log"
        argv = qemu_argv(name="pantheon-image", accel=self.accel, cpus=self.cpus,
                         memory_mib=max(self.memory_mib, 2048), disk=disk, iso=seed,
                         console=console, qmp=work / "qmp.sock")
        logger.info("making the machine image (%s); its console is %s", self.accel, console)
        with open(work / "qemu.log", "wb") as log:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=log, start_new_session=True)
        try:
            proc.wait(timeout=IMAGE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise WorkstationError("unavailable", f"making it took longer than "
                                                  f"{IMAGE_TIMEOUT_S / 3600:.0f} h")
        verdict = read_verdict(console)
        if verdict is not True:
            disk.unlink(missing_ok=True)  # gigabytes of a failed attempt; its console is kept
            said = tail(work / "qemu.log", 2)
            raise WorkstationError("unavailable", ("its provisioning failed" if verdict is False
                                                   else "it stopped before it said it was done")
                                   + f": {said or tail(console)}")
        shutil.copy2(console, image.with_suffix(".log"))
        # Moved, not copied: a compacting copy needs the image's size free a
        # second time, and measured `P20-07` it failed for exactly that on a
        # full disk after the 33 minutes of making it — for a copy that came
        # out no smaller (2.67 GB compacted, 2.5 GB in place).
        os.replace(disk, image)
        shutil.rmtree(work, ignore_errors=True)

    def _forget_unused_images(self, keep: Path) -> None:
        """Images no machine is made from any more. Asked of `qemu-img` rather
        than remembered, because a disk's base is written in the disk."""
        used = {keep.resolve()}
        for disk in (self.state / "machines").glob("*/disk.qcow2"):
            try:
                info = json.loads(subprocess.run(
                    ["qemu-img", "info", "--output=json", str(disk)], capture_output=True,
                    text=True, check=True).stdout)
            except (subprocess.CalledProcessError, ValueError, OSError):
                return  # unsure which images are used: keep them all
            backing = info.get("full-backing-filename") or info.get("backing-filename")
            if backing:
                used.add(Path(backing).resolve())
        for old in (self.state / "images").glob("image-*.qcow2"):
            if old.resolve() not in used:
                logger.info("removing machine image %s: nothing is made from it", old.name)
                old.unlink(missing_ok=True)

    # -- machines ---------------------------------------------------------------

    def machine_argv(self, m: Machine) -> List[str]:
        """The QEMU command line for a person's machine: its files under its
        own folder, its forwarded port, and `restrict=on` when the network it
        is started with is *none* (`B992`)."""
        folder = self.state / "machines" / m.account
        return qemu_argv(name=f"pantheon-{m.account}", accel=self.accel, cpus=self.cpus,
                         memory_mib=self.memory_mib, disk=folder / "disk.qcow2",
                         iso=folder / "app.iso", console=folder / "console.log",
                         qmp=folder / "qmp.sock", forward=("127.0.0.1", int(m.port or 0)),
                         restrict=self._restricted.get(m.account, False))

    def machine_for(self, account: str) -> Machine:
        with self._registry:
            m = self._machines.get(account)
            if m is None:
                m = self._machines[account] = self.factory(self, account)
            return m

    def ready(self, account: str) -> Machine:
        """This person's machine, started and answering — or a sentence."""
        m = self.machine_for(account)
        self._touch(account)  # `B979`
        with self._locks[account]:
            if m.running() and m.port is not None:
                if not self._wrong_network(account):
                    return m
                # Started under another network mode (`B992`): it boots again
                # with this one.
                m.stop(graceful=True)
            if not m.exists() and self.image_state != "ready":
                raise WorkstationError("unavailable", self.image_sentence())
            started = time.monotonic()
            with self._start_lock:  # `B979`: counted and started as one step
                others = [a for a in self.running_accounts() if a != account]
                if self.max_running is not None and len(others) >= self.max_running:
                    raise WorkstationError("unavailable", self.cap_sentence(len(others)))
                self._restricted[account] = self.network == "none"  # `B992`
                self._guest_net.pop(account, None)
                m.start()
            self._wait_answering(m, started)
            logger.info("the machine for %s answered after %.1f s", account,
                        time.monotonic() - started)
            # A machine that just booted knows only what its disk remembers.
            try:
                self._call(m, "config", body={"sudo": self.sudo})
            except WorkstationError as e:
                m.stop(graceful=False)
                raise WorkstationError("unavailable", f"Your workstation machine started but "
                                                      f"refused its settings: {e.message}")
            # …and the network mode (`B992`): held, or the machine does not run.
            try:
                self._hold(account, m)
            except WorkstationError as e:
                m.stop(graceful=True)
                raise e
            # …and only the time its RTC gave it (`B984`). Not fatal: a daemon
            # older than the route answers `not_found`, and runs as it did.
            try:
                self._sync_clock(account, m)
            except WorkstationError as e:
                logger.info("the clock of %s's machine was not set: %s", account, e.message)
            return m

    def _wait_answering(self, m: Machine, started: float) -> None:
        while time.monotonic() - started < self.start_timeout:
            if not m.running():
                raise WorkstationError("unavailable", "Your workstation machine stopped while it "
                                       f"was starting: {getattr(m, 'why_not', lambda: '')()}")
            try:
                answer = self._call(m, "health", timeout=5.0)
                if answer.get("agent") == P.AGENT_NAME and "sudo" in answer:
                    return
            except WorkstationError:
                pass  # still booting: not answering yet is the normal answer here
            time.sleep(1.0)
        m.stop(graceful=False)
        raise WorkstationError("unavailable", f"Your workstation machine did not answer within "
                                              f"{self.start_timeout:.0f} s of starting.")

    def reset(self, account: str) -> None:
        """A fresh machine from the newest image (module docstring)."""
        m = self.machine_for(account)
        with self._locks[account]:
            if self.image_state != "ready":
                raise WorkstationError("unavailable", self.image_sentence())
            m.destroy()
            with self._registry:
                self._machines.pop(account, None)
            self._restricted.pop(account, None)  # `B992`
            self._guest_net.pop(account, None)

    # -- `B979`: use, idleness and the cap --------------------------------------

    def _touch(self, account: str) -> None:
        with self._use_lock:
            self._use.setdefault(account, [0, self._clock()])[1] = self._clock()

    @contextlib.contextmanager
    def _using(self, account: str):
        """A request in this person's machine: it is not idle while one is in
        flight, and its end is a use."""
        with self._use_lock:
            use = self._use.setdefault(account, [0, self._clock()])
            use[0] += 1
            use[1] = self._clock()
        try:
            yield
        finally:
            with self._use_lock:
                use[0] -= 1
                use[1] = self._clock()

    def _idle(self, account: str) -> bool:
        with self._use_lock:
            busy, last = self._use.get(account, [0, self._clock()])
            return (self.idle_stop_s is not None and busy == 0
                    and self._clock() - last >= self.idle_stop_s)

    def reap_idle(self) -> List[str]:
        """Power off every machine idle for `idle_stop_s`, cleanly, its disk
        kept; the accounts whose machines were stopped. One that is starting
        or being reset (its lock held) is left for the next round."""
        stopped: List[str] = []
        for account in self.running_accounts():
            if not self._idle(account):
                continue
            lock = self._locks[account]
            if not lock.acquire(blocking=False):
                continue
            try:
                m = self.machine_for(account)
                if m.running() and self._idle(account):
                    logger.info("powering off the machine for %s: unused for %s", account,
                                _minutes(self.idle_stop_s or 0))
                    m.stop(graceful=True)
                    stopped.append(account)
            finally:
                lock.release()
        return stopped

    def housekeeping(self, stop: threading.Event, *, interval: float = HOUSEKEEPING_S) -> None:
        """What the host does on its own, every `interval` until `stop`: power
        off what nobody uses (`B979`), and keep the rest on time (`B984`)."""
        while not stop.wait(interval):
            try:
                self.reap_idle()
                if time.monotonic() - self._last_clock_sync >= CLOCK_SYNC_S:
                    self._last_clock_sync = time.monotonic()
                    self.sync_clocks()
            except Exception:  # noqa: BLE001 — one bad round must not end the next ones
                logger.exception("workstation housekeeping failed")

    # -- `B984`: the time ---------------------------------------------------------

    def step_clock(self, seconds: float) -> None:
        raise WorkstationError("unavailable", "The VM host keeps the clock of the machine it "
                                              "runs on. It sets its machines' clocks, never "
                                              "its own.")

    def _sync_clock(self, account: str, m: Machine) -> Optional[float]:
        """The machine's offset from this host's clock in seconds, after
        stepping it if it was more than `CLOCK_STEP_S` out; None when the
        round trip was too slow to measure (module comment above)."""
        before = time.time()
        answer = self._call(m, "clock", body={}, timeout=10.0) or {}
        after = time.time()
        seen = answer.get("time")
        if after - before > CLOCK_MAX_RTT_S or isinstance(seen, bool) \
                or not isinstance(seen, (int, float)):
            return None
        offset = float(seen) - (before + after) / 2
        # Stepped only when it is out by more than `CLOCK_STEP_S` beyond what
        # the round trip leaves unknown: a machine on time is never stepped
        # on noise.
        if abs(offset) - (after - before) / 2 > CLOCK_STEP_S:
            self._call(m, "clock", body={"step_s": -offset}, timeout=10.0)
            logger.info("set the clock of %s's machine to this host's (it was %+.3f s out)",
                        account, offset)
        return offset

    def sync_clocks(self) -> Dict[str, Optional[float]]:
        """Every running machine to this host's time: `{account: offset}`."""
        out: Dict[str, Optional[float]] = {}
        for account in self.running_accounts():
            m = self.machine_for(account)
            try:
                out[account] = self._sync_clock(account, m) if m.running() else None
            except WorkstationError as e:
                out[account] = None
                logger.info("the clock of %s's machine was not read: %s", account, e.message)
        return out

    def cap_sentence(self, running: int) -> str:
        machines = "1 machine" if running == 1 else f"{running} machines"
        then = (f"A machine nobody has used for {_minutes(self.idle_stop_s)} stops on its own; "
                "try again then, or ask" if self.idle_stop_s else "Ask")
        return (f"The workstation already runs {machines}, the most this host is set to hold "
                f"({ENV['max_running']}). {then} an admin to raise the limit.")

    def stop_all(self) -> None:
        threads = [threading.Thread(target=m.stop, daemon=True)
                   for m in list(self._machines.values()) if m.running()]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=STOP_GRACE_S + 20)

    # -- the wire to a machine --------------------------------------------------

    def _connection(self, m: Machine, timeout: float) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", int(m.port or 0), timeout=timeout)

    def _call(self, m: Machine, name: str, account: Optional[str] = None,
              body: Optional[Dict] = None, query: Optional[Dict] = None,
              timeout: float = 60.0, allow_304: bool = False) -> Optional[Dict]:
        method, path = P.route_path(name, account)
        if query:
            path += "?" + urlencode({k: v for k, v in query.items() if v is not None})
        conn = self._connection(m, timeout)
        try:
            payload = json.dumps(body or {}).encode() if method == "POST" else None
            headers = {"Authorization": f"Bearer {m.token}"}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except (OSError, http.client.HTTPException) as e:
            raise WorkstationError("unavailable", f"Your workstation machine stopped answering "
                                                  f"({type(e).__name__}).")
        finally:
            conn.close()
        if allow_304 and resp.status == 304:  # `B974`: the frame the caller holds
            return None
        return _answer(resp.status, data)

    def forward(self, account: str, name: str, body: Optional[Dict] = None, *,
                query: Optional[Dict] = None, timeout: float = 120.0, start: bool = True,
                allow_304: bool = False) -> Optional[Dict]:
        if not start:
            m = self.machine_for(account)
            if not m.running():
                raise WorkstationError("unavailable", "Your workstation machine is not running.")
            return self._call(m, name, account, body, query, timeout, allow_304=allow_304)
        with self._using(account):  # `B979`
            m = self.ready(account)
            return self._call(m, name, account, body, query, timeout, allow_304=allow_304)

    def stream_exec(self, account: str, body: Dict, on_chunk: Callable[[str, str], None],
                    caller_gone: Optional[Callable[[], bool]], timeout: float) -> Dict:
        """`exec` with `stream: true`, relayed line by line. If the caller
        hangs up, the connection to the machine is closed, and the daemon
        there kills the command (`B965`) — the hang-up travels through."""
        with self._using(account):  # `B979`: not idle while the command runs
            return self._stream_exec(account, body, on_chunk, caller_gone, timeout)

    def _stream_exec(self, account: str, body: Dict, on_chunk: Callable[[str, str], None],
                     caller_gone: Optional[Callable[[], bool]], timeout: float) -> Dict:
        m = self.ready(account)
        method, path = P.route_path("exec", account)
        conn = self._connection(m, timeout)
        lines: "queue.Queue[Optional[bytes]]" = queue.Queue()
        sock: Optional[socket.socket] = None
        try:
            conn.request(method, path, body=json.dumps(dict(body, stream=True)).encode(),
                         headers={"Authorization": f"Bearer {m.token}",
                                  "Content-Type": "application/json"})
            # Held here: `getresponse` hands a `Connection: close` stream to the
            # response and forgets the socket, and closing the connection
            # object then closes nothing.
            sock = conn.sock
            resp = conn.getresponse()
            if resp.status != 200:
                return _answer(resp.status, resp.read())

            def pump() -> None:
                try:
                    for raw in iter(resp.readline, b""):
                        lines.put(raw)
                except (OSError, ValueError, http.client.HTTPException):
                    # The stream ended badly; the `None` below is how the
                    # waiting side learns, and it says so in a sentence.
                    pass
                lines.put(None)

            threading.Thread(target=pump, daemon=True).start()
            while True:
                try:
                    raw = lines.get(timeout=0.5)
                except queue.Empty:
                    if caller_gone is not None and caller_gone():
                        raise ConnectionResetError("the caller went away")
                    continue
                if raw is None:
                    raise WorkstationError("unavailable", "Your workstation machine stopped "
                                                          "answering while the command ran.")
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if event.get("type") == "exit":
                    result = {k: v for k, v in event.items() if k != "type"}
                    if result.get("error") in P.ERRORS and "stdout" not in result:
                        raise WorkstationError(result["error"], str(result.get("message") or ""))
                    return result
                on_chunk(str(event.get("type")), str(event.get("data") or ""))
        except (OSError, http.client.HTTPException) as e:
            if isinstance(e, ConnectionError):
                raise
            raise WorkstationError("unavailable", f"Your workstation machine stopped answering "
                                                  f"({type(e).__name__}).")
        finally:
            # Closing is the hang-up the machine's daemon listens for.
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # already closed by the other end
                sock.close()
            conn.close()


def _answer(status: int, data: bytes) -> Dict:
    try:
        payload = json.loads(data.decode("utf-8")) if data else {}
    except (ValueError, UnicodeDecodeError):
        payload = {}
    if status == 200 and isinstance(payload, dict):
        return payload
    code = payload.get("error") if isinstance(payload, dict) else None
    message = payload.get("message") if isinstance(payload, dict) else None
    if status == 401:
        # Pantheon's token was right (it reached here); the machine's was not.
        raise WorkstationError("unavailable", "Your workstation machine refused the token the "
                                              "workstation gave it. Reset it to make it again.")
    if code in P.ERRORS and message:
        raise WorkstationError(code, str(message))
    raise WorkstationError("internal", f"Your workstation machine answered {status}.")


# ── the protocol, answered by forwarding ──────────────────────────────────────

class VmStation(Workstation):
    """`agentd.Workstation` with each person's routes forwarded to their
    machine. `health`, `config`, `account`, the token and every byte bound are
    the base class's (module docstring)."""

    system: Fleet

    def health(self, authorised: bool) -> Dict:
        out = super().health(authorised)
        if authorised:
            out["machines"] = self.system.machines()  # `B979`
        return out

    def account(self, account: str) -> Dict:
        """`B959`: from the machine itself when it is already running (the
        exact home it has), else from its disk — and never by starting it.
        `B979`: and whether that machine is running or powered off."""
        m = self.system.machine_for(account)
        if m.running() and m.port is not None:
            try:
                answer = dict(self.system._call(m, "account", account, timeout=10.0) or {})
                answer["machine"] = "running"
                return answer
            except WorkstationError:
                pass  # what the disk says is still true
        answer = super().account(account)
        if answer.get("exists"):
            answer["machine"] = "running" if m.running() else "stopped"
        return answer

    def ensure(self, account: str) -> Dict:
        return self.system.forward(account, "ensure", {}, timeout=120.0)

    def reset(self, account: str) -> Dict:
        self.system.reset(account)
        # The protocol says a reset ends on a fresh desktop (`ROUTES["reset"]`).
        self.system.forward(account, "ensure", {}, timeout=120.0)
        return {"account": account, "reset": True}

    def control(self, account: str, body: Dict) -> Dict:
        return self.system.forward(account, "control", body)

    def _exec_prepare(self, account: str, body: Dict):
        # Started (and its errors said) before `200` goes out on a stream.
        self.system.ready(account)
        return ("vm", dict(body))

    def exec(self, account: str, body: Dict, on_chunk=None, prepared=None,
             caller_gone=None) -> Dict:
        try:
            timeout = float(body.get("timeout_s") or P.DEFAULT_EXEC_TIMEOUT_S)
        except (TypeError, ValueError):
            timeout = P.DEFAULT_EXEC_TIMEOUT_S
        wait = min(max(timeout, 1.0), P.MAX_EXEC_TIMEOUT_S) + 60.0
        if on_chunk is None:
            return self.system.forward(account, "exec", {k: v for k, v in body.items()
                                                         if k != "stream"}, timeout=wait)
        return self.system.stream_exec(account, body, on_chunk, caller_gone, wait)

    def read(self, account: str, body: Dict) -> Dict:
        return self.system.forward(account, "read", body)

    def write(self, account: str, body: Dict) -> Dict:
        return self.system.forward(account, "write", body)

    def list(self, account: str, body: Dict) -> Dict:
        return self.system.forward(account, "list", body)

    def screenshot(self, account: str, fmt: str = "png") -> Dict:
        return self.system.forward(account, "screenshot", query={"format": fmt})

    def screenshot_unless(self, account: str, fmt: str, if_none_match: str = "") -> Optional[Dict]:
        """`B974`: the conditional travels to the machine, whose display can
        tell whether it moved without a grab; its `304` comes back as None."""
        return self.system.forward(account, "screenshot", allow_304=True,
                                   query={"format": fmt, "if_none_match": if_none_match or None})

    def input(self, account: str, body: Dict) -> Dict:
        return self.system.forward(account, "input", body,
                                   timeout=P.MAX_WAIT_MS / 1000 + 120.0)


# ── the command line ──────────────────────────────────────────────────────────

def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    if not raw.isdigit() or not lo <= int(raw) <= hi:
        raise SystemExit(f"{name} is a whole number from {lo} to {hi}.")
    return int(raw)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python3 -m workstation.vm",
                                 description="The workstation's VM backend: a machine per "
                                             f"person, protocol v{P.PROTOCOL_VERSION}.")
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=P.DEFAULT_PORT)
    ap.add_argument("--state", default=str(DEFAULT_STATE),
                    help="where the image and every machine's disk are kept (a volume)")
    ap.add_argument("--base-image", default=str(DEFAULT_BASE_IMAGE))
    ap.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    ap.add_argument("--pairing-dir", default=os.environ.get(P.PAIRING_DIR_ENV)
                    or P.DEFAULT_PAIRING_DIR)
    ap.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    from workstation.__main__ import PAIRING_GID_ENV, _gid, secure_pairing

    args = parser().parse_args(argv)
    logging.basicConfig(stream=sys.stdout, level=getattr(logging, args.log_level),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    memory = _int_env(ENV["memory"], DEFAULT_MEMORY_MIB, 1024, 262_144)
    cpus = _int_env(ENV["cpus"], DEFAULT_CPUS, 1, 64)
    disk = _int_env(ENV["disk"], DEFAULT_DISK_GIB, 8, 4096)
    idle = idle_stop_from_env(os.environ.get(ENV["idle"], ""))  # `B979`
    cap = max_running_from_env(os.environ.get(ENV["max_running"], ""), memory, host_memory_mib())
    want = (os.environ.get(ENV["accel"]) or "auto").strip().lower()
    if want not in ("auto", "kvm", "tcg"):
        logger.error("%s is auto, kvm or tcg.", ENV["accel"])
        return 2
    try:
        gid = _gid(os.environ.get(PAIRING_GID_ENV, ""))
        accel, why = choose_accel(want=want)
        pairing = Path(args.pairing_dir)
        token = load_or_create_token(pairing)
        if not (os.environ.get(P.TOKEN_ENV) or "").strip():
            secure_pairing(pairing, gid)
        options = {k: (os.environ.get(ENV[k]) or "").strip()
                   for k in ("apt_mirror", "apt_proxy", "apt_ca")}
        fleet = Fleet(Path(args.state), accel=accel, accel_why=why,
                      base_image=Path(args.base_image), payload=Path(args.payload),
                      memory_mib=memory, cpus=cpus, disk_gib=disk, image_options=options,
                      idle_stop_s=idle, max_running=cap)
    except (WorkstationError, argparse.ArgumentTypeError) as e:
        logger.error("%s", getattr(e, "message", None) or e)
        return 2
    logger.info("%s", why)
    station = VmStation(fleet, token)
    server = make_server(fleet, token, bind=args.bind, port=args.port, station=station)
    threading.Thread(target=fleet.prepare_image, name="image", daemon=True).start()
    done = threading.Event()
    threading.Thread(target=fleet.housekeeping, args=(done,), name="housekeeping",
                     daemon=True).start()  # `B979`
    host, port = server.server_address[:2]
    logger.info("workstation VM backend listening on %s:%s — %s, %d MiB and %d CPUs a machine, "
                "protocol v%s", host, port, accel, memory, cpus, P.PROTOCOL_VERSION)
    logger.info("%s; %s", f"a machine unused for {_minutes(idle)} is powered off" if idle
                else "machines are never powered off for being unused",
                f"at most {cap} run at once" if cap is not None else "any number may run")

    def stop(signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logger.info("stopping: powering off every machine")
    finally:
        done.set()
        server.server_close()
        fleet.stop_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CLOCK_MAX_RTT_S", "CLOCK_STEP_S", "CLOCK_SYNC_S",  # `B984`
           "DEFAULT_IDLE_STOP_MIN", "MEMORY_RESERVE_MIB", "host_memory_mib",  # `B979`
           "idle_stop_from_env", "max_running_from_env",
           "Fleet", "Machine", "QemuMachine", "VmStation", "choose_accel", "guest_unit",
           "image_meta_data", "image_user_data", "make_iso", "payload_digest", "payload_files",
           "qemu_argv", "read_verdict"]
