# SPDX-License-Identifier: AGPL-3.0-or-later
"""A program installed with a capability this machine never grants is made to
start — `B976`.

THE PROBLEM, MEASURED
=====================

The workstation container runs without `CAP_NET_RAW` (`docker/workstation.yml`'s
`cap_drop`, `P20-06`): it is load-bearing, because with it root wrote its own
Ethernet frames past the network gate's rules. And the kernel refuses to `exec` a
binary whose file capability names a capability the bounding set does not hold
(`bprm_caps_from_vfs_caps`: *insufficient to execute correctly*) — for an account
and for root alike. Ubuntu's `iputils-ping` is installed with `cap_net_raw=ep`
(`setcap` in its maintainer script), so measured 2026-10-01 in this image with
`NET_RAW` dropped: `sudo apt-get install iputils-ping`, then `ping` → *Operation
not permitted* at `exec`, which names no reason. `ping` is not in the image; an
agent debugging a network installs it, and then cannot run it.

`setcap -r /usr/bin/ping` was the fix measured by `P20-06`: without its file
capability `ping` opens an unprivileged ICMP socket instead
(`net.ipv4.ping_group_range` is `0 2147483647` in the container's namespace —
Docker sets it) and a LAN host answered.

WHAT THIS DOES
==============

apt runs it after every dpkg run (`DPkg::Post-Invoke`, `apt-net-raw.conf`, which
the container image installs). For each program in the directories on `PATH`
whose file capability asks for a capability **outside this process's bounding
set**, it takes those — and only those — out of the file capability; when
nothing is left, the attribute goes, as `setcap -r` would. The program then
starts as an ordinary one: `ping` falls back to an ICMP socket and works; a
program that truly needs raw packets (`arping`) fails at its socket with
*Operation not permitted* — the truth about this machine — rather than at
`exec`. It says each change in one line, which apt prints to whoever ran it.

**It removes, never adds, and only what could never be granted here.** A
capability in the bounding set is kept. Where `CAP_NET_RAW` is in the bounding
set — an image being built, a VM backend machine, another machine running the
daemon — nothing is outside it that a package asks for, and it changes nothing.
The container image is the only place that installs the hook, because the
container is the only backend that drops a capability (`P20-06`).

Standard library only, like the rest of the package: the `security.capability`
attribute is read and written directly (`os.getxattr`), so it needs no `setcap`,
which the image does not have.
"""
from __future__ import annotations

import os
import struct
import sys
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from workstation import netrules

XATTR = "security.capability"
CAP_NET_RAW = 13
#: Where an agent runs programs from — the image's `PATH`, with `/bin` and
#: `/sbin` (links into `/usr` on Ubuntu 24.04) folded by their real path.
PATH_DIRS = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")

# `struct vfs_cap_data` (linux/capability.h): a little-endian `magic_etc`, then
# (permitted, inheritable) pairs of 32-bit words — one pair for revision 1, two
# for revisions 2 and 3 — and, for revision 3, the namespace's root uid.
_REVISION_MASK = 0xFF000000
_WORDS = {0x01000000: 1, 0x02000000: 2, 0x03000000: 2}

#: Linux's capability names, by bit, for the line said about a change.
NAMES = (
    "chown", "dac_override", "dac_read_search", "fowner", "fsetid", "kill", "setgid", "setuid",
    "setpcap", "linux_immutable", "net_bind_service", "net_broadcast", "net_admin", "net_raw",
    "ipc_lock", "ipc_owner", "sys_module", "sys_rawio", "sys_chroot", "sys_ptrace", "sys_pacct",
    "sys_admin", "sys_boot", "sys_nice", "sys_resource", "sys_time", "sys_tty_config", "mknod",
    "lease", "audit_write", "audit_control", "setfcap", "mac_override", "mac_admin", "syslog",
    "wake_alarm", "block_suspend", "audit_read", "perfmon", "bpf", "checkpoint_restore",
)


def name(bit: int) -> str:
    return "cap_" + NAMES[bit] if 0 <= bit < len(NAMES) else f"capability {bit}"


def _decode(raw: bytes) -> Optional[Tuple[int, int, int, List[int]]]:
    """`(magic_etc, permitted, inheritable, words)` of a file capability, or None
    for one this code does not read (it is then left as it is)."""
    if len(raw) < 4:
        return None
    magic = struct.unpack_from("<I", raw)[0]
    words = _WORDS.get(magic & _REVISION_MASK)
    if words is None or len(raw) < 4 + 8 * words:
        return None
    pairs = list(struct.unpack_from(f"<{2 * words}I", raw, 4))
    permitted = sum(pairs[2 * i] << (32 * i) for i in range(words))
    inheritable = sum(pairs[2 * i + 1] << (32 * i) for i in range(words))
    return magic, permitted, inheritable, pairs


def _encode(raw: bytes, permitted: int) -> bytes:
    """`raw` with its permitted set replaced, everything else as it was."""
    magic, _old, _inh, pairs = _decode(raw)  # type: ignore[misc]
    words = len(pairs) // 2
    for i in range(words):
        pairs[2 * i] = (permitted >> (32 * i)) & 0xFFFFFFFF
    head = struct.pack(f"<I{2 * words}I", magic, *pairs)
    return head + raw[len(head):]


def ungrantable(raw: bytes, bounding: int) -> int:
    """The capabilities `raw` asks to be permitted that `bounding` never grants
    — what makes the kernel refuse the program at `exec`. 0 for none, and for
    an attribute this code cannot read."""
    decoded = _decode(raw)
    return decoded[1] & ~bounding if decoded else 0


def mend(path: str, bounding: int, *, get: Callable = os.getxattr, put: Callable = os.setxattr,
         drop: Callable = os.removexattr) -> Optional[str]:
    """Take out of `path`'s file capability what `bounding` never grants. The
    line to say about it, or None when there was nothing to take out."""
    try:
        raw = get(path, XATTR, follow_symlinks=False)
    except OSError:
        return None   # no file capability (ENODATA), or not a file that has one
    refused = ungrantable(raw, bounding)
    if not refused:
        return None
    _magic, permitted, inheritable, _pairs = _decode(raw)  # type: ignore[misc]
    kept = permitted & ~refused
    names = ", ".join(name(b) for b in range(64) if refused >> b & 1)
    try:
        if kept == 0 and inheritable == 0:
            drop(path, XATTR, follow_symlinks=False)
        else:
            put(path, XATTR, _encode(raw, kept), follow_symlinks=False)
    except OSError as e:
        return (f"workstation: {path} asks for {names}, which this machine never grants, so it "
                f"cannot start, and it could not be changed ({e.strerror or e}).")
    return (f"workstation: {path} asked for {names}, which this machine never grants, so it "
            "could not start; it now starts without it (B976).")


def mend_all(dirs: Sequence[str] = PATH_DIRS, *, bounding: Optional[int] = None,
             **xattr: Callable) -> List[str]:
    """`mend` every regular file in `dirs` (each directory once, by its real
    path). The lines said, in order. A bounding set that cannot be read
    changes nothing: "unknown" is not "empty"."""
    if bounding is None:
        bounding = netrules.capabilities("CapBnd")
        if bounding is None:
            return []
    seen: Dict[str, None] = {}
    said: List[str] = []
    for d in dirs:
        real = os.path.realpath(d)
        if real in seen or not os.path.isdir(real):
            continue
        seen[real] = None
        for entry in sorted(os.scandir(real), key=lambda e: e.name):
            if entry.is_file(follow_symlinks=False):
                line = mend(entry.path, bounding, **xattr)
                if line:
                    said.append(line)
    return said


def main(argv: Optional[Sequence[str]] = None) -> int:
    """apt runs it with no arguments: the directories on `PATH`. Directories
    given as arguments are mended instead (how a test drives this entry point
    without touching the machine running it)."""
    for line in mend_all(list(argv) if argv else PATH_DIRS):
        print(line)
    return 0


__all__ = ["CAP_NET_RAW", "PATH_DIRS", "XATTR", "main", "mend", "mend_all", "name",
           "ungrantable"]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
