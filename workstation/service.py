# SPDX-License-Identifier: AGPL-3.0-or-later
"""The daemon as a systemd service — `P20-07`.

Two backends run `python3 -m workstation` under systemd rather than as a
container's PID 1: each VM backend machine (`workstation/vm.py`) and any host
`workstation/install.py` sets up. Both get their unit from `unit()` here, so
the restart policy, the environment and the command line are written once
(`Law 14`); what differs between them is a parameter, not a second file.

**The token never goes in the unit or its environment.** It is a root-only file
handed over with `--token-file` — on a VM machine the per-machine file on its
read-only app disk, on a host `/etc/pantheon-workstation/token` (0600) — so
`systemctl show` and the journal never carry it.

Standard library only, nothing from Pantheon (the package's rule).
"""
from __future__ import annotations

import shlex
from typing import List, Optional

from workstation import protocol as P

UNIT_NAME = "pantheon-workstation.service"
UNIT_PATH = f"/etc/systemd/system/{UNIT_NAME}"


def exec_argv(*, backend: str, token_file: str, system: str = "ubuntu", bind: str = "0.0.0.0",
              port: int = P.DEFAULT_PORT, skeleton: Optional[str] = None,
              tls_cert: Optional[str] = None, tls_key: Optional[str] = None,
              python: str = "/usr/bin/python3") -> List[str]:
    """The daemon's command line, as the unit runs it."""
    if backend not in P.BACKENDS:
        raise ValueError(f"backend is one of {', '.join(P.BACKENDS)}")
    if bool(tls_cert) != bool(tls_key):
        raise ValueError("a TLS certificate needs its key, and the other way round")
    argv = [python, "-m", "workstation", "--system", system, "--backend", backend,
            "--bind", bind, "--port", str(int(port)), "--token-file", token_file]
    if skeleton:
        argv += ["--skeleton", skeleton]
    if tls_cert:
        argv += ["--tls-cert", tls_cert, "--tls-key", str(tls_key)]
    return argv


def unit(*, description: str, workdir: str, argv: List[str],
         requires_mounts: Optional[str] = None) -> str:
    """The whole unit file. `workdir` holds the `workstation/` package, which
    `python3 -m` finds there."""
    lines = [
        "# Written by Pantheon (P20-07): the workstation daemon. See workstation/service.py.",
        "[Unit]",
        f"Description={description}",
        "After=network-online.target",
        "Wants=network-online.target",
    ]
    if requires_mounts:
        lines.append(f"RequiresMountsFor={requires_mounts}")
    lines += [
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={workdir}",
        "Environment=LANG=C.UTF-8 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1",
        f"ExecStart={shlex.join(argv)}",
        # Every account's desktop and command is in this unit's cgroup, so a
        # stop takes them with it — what replacing the container does to the
        # container backend.
        "Restart=always",
        "RestartSec=2",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ]
    return "\n".join(lines)


__all__ = ["UNIT_NAME", "UNIT_PATH", "exec_argv", "unit"]
