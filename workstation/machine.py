# SPDX-License-Identifier: AGPL-3.0-or-later
"""What machine the daemon is running on — `P20-07`.

`health` says which backend a workstation is (`container`, `vm`, `remote`) and,
for a caller with the token, what the machine under it is
(`protocol.ACCELS`, the comment above it). Both are answered here, by looking,
so neither is a label somebody typed and forgot to change (`Law 10`).

**Virtualization** is `systemd-detect-virt`'s answer — the same word systemd
itself acts on, from CPUID, DMI and `/proc`, which Python's standard library
cannot read for itself (CPUID needs the instruction). Where systemd is absent —
the container image runs no init — the container runtime's own marker files
answer instead, and anything else is "unknown", never a guess.

**For a QEMU guest the word is also the speed.** systemd-detect-virt(1):
`kvm` is "Linux KVM kernel virtual machine, in combination with QEMU"; `qemu`
is "QEMU software virtualization, without KVM" — TCG, measured `P20-07` at
roughly an order of magnitude slower. `accel` restates that pair as the
protocol's `kvm` / `tcg` and is None for everything else.

Standard library only, nothing from Pantheon (the package's rule).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, Optional

# systemd-detect-virt's container words (systemd 255), and the files a
# runtime leaves when there is no systemd to ask.
_CONTAINER_WORDS = {"docker", "podman", "lxc", "lxc-libvirt", "systemd-nspawn", "openvz",
                    "rkt", "wsl", "proot", "pouch", "container-other"}
_MARKERS = (("/.dockerenv", "docker"), ("/run/.containerenv", "podman"))


def _systemd_detect_virt(run: Callable = subprocess.run) -> Optional[str]:
    tool = shutil.which("systemd-detect-virt")
    if not tool:
        return None
    try:
        # Exit status 1 means "none": it still prints the word.
        done = run([tool], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                   text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    word = (done.stdout or "").strip().splitlines()
    return word[0].strip() if word and word[0].strip() else None


def virtualization(*, detect: Callable[[], Optional[str]] = _systemd_detect_virt,
                   root: Path = Path("/")) -> str:
    """systemd's word for what this runs on, a container runtime's marker
    when there is no systemd, or "unknown"."""
    word = detect()
    if word:
        return word
    for marker, name in _MARKERS:
        if (root / marker.lstrip("/")).exists():
            return name
    return "unknown"


def in_container(word: str) -> bool:
    return word in _CONTAINER_WORDS


def accel(word: str) -> Optional[str]:
    """`kvm` or `tcg` for a QEMU guest (module docstring), None otherwise."""
    return {"kvm": "kvm", "qemu": "tcg"}.get(word)


def facts(word: Optional[str] = None) -> Dict[str, Optional[str]]:
    """The `machine` object `health` carries."""
    word = word if word is not None else virtualization()
    return {"virtualization": word, "accel": accel(word)}


def default_backend(system: str, word: str) -> str:
    """What a daemon is when nobody said: a `single` daemon is somebody's
    machine Pantheon was pointed at; an `ubuntu` one is the container image
    when it runs in a container, and another machine when it does not. `vm`
    is never guessed — only the VM backend's own machines are that, and they
    say so on their command line (`workstation/vm.py`)."""
    if system == "ubuntu" and in_container(word):
        return "container"
    return "remote"


__all__ = ["accel", "default_backend", "facts", "in_container", "virtualization"]
