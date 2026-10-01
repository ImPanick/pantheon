# SPDX-License-Identifier: AGPL-3.0-or-later
"""`python3 -m workstation` — start the daemon (`P20-01`).

    python3 -m workstation --system ubuntu --bind 0.0.0.0     # what the image runs
    python3 -m workstation --system single --homes ~/ws       # a remote host, no accounts made

**The token** is `PANTHEON_WORKSTATION_TOKEN` if set, otherwise the one in the
pairing directory, otherwise a new one written there (`agentd.load_or_create_token`)
— and never printed or logged: the pairing volume is how Pantheon gets it, and
an operator running this by hand sets the variable on both sides.

**Who may read it.** The pairing directory is made `root:<group> 0750` and the
token `0640`, where the group is `--pairing-group` — Pantheon's own `PGID`,
which `docker/workstation.yml` passes in — so Pantheon's non-root user can read
it and no workstation account can: account uids and gids are allocated from
`UID_MIN` up and the pairing group is reserved, and a registry that already
gives it to an account stops the daemon with a sentence rather than sharing
the token with that person's agent. Without a group the files are root's
alone.

**It listens on loopback unless told otherwise** (`Law 16`, and `netagent`'s
rule): the image passes `--bind 0.0.0.0` because Pantheon reaches it over the
compose network, where the port is not published to the host.

**On another machine** (`P20-07`): `workstation/install.py` sets it up as a
systemd service with `--backend remote`, the token in a root-only file handed
over as `--token-file`, and — by default — `--tls-cert`/`--tls-key` from a
certificate it makes, whose fingerprint Pantheon pins
(`protocol.TLS_PIN_ENV`). Without TLS it refuses to bind a literal public
address: the client would refuse to send the token there anyway, and a daemon
that starts where nothing can use it is a puzzle rather than an answer.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path
from typing import List, Optional

from workstation import protocol as P
from workstation.agentd import (SingleUserSystem, System, WorkstationError,
                                load_or_create_token, make_server, server_context)

logger = logging.getLogger("pantheon.workstation")

BIND_ENV = "PANTHEON_WORKSTATION_BIND"
PORT_ENV = "PANTHEON_WORKSTATION_PORT"
PAIRING_GID_ENV = "PANTHEON_WORKSTATION_PAIRING_GID"
DEFAULT_BIND = "127.0.0.1"
# `P20-07`. A daemon on another machine: what it says it is, its TLS
# certificate, and its token from a file only root reads (systemd's
# credential, `workstation/service.py`) rather than from the environment.
BACKEND_ENV = "PANTHEON_WORKSTATION_BACKEND"
TLS_CERT_ENV = "PANTHEON_WORKSTATION_TLS_CERT"
TLS_KEY_ENV = "PANTHEON_WORKSTATION_TLS_KEY"


def _gid(value: str) -> Optional[int]:
    v = str(value).strip()
    if v == "":
        return None
    if not v.isdigit() or int(v) == 0:
        raise argparse.ArgumentTypeError("a numeric group id other than 0")
    return int(v)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python3 -m workstation",
        description="The Pantheon workstation daemon: protocol "
                    f"v{P.PROTOCOL_VERSION} on port {P.DEFAULT_PORT}.")
    ap.add_argument("--system", choices=("ubuntu", "single"), default="single",
                    help="ubuntu: a Unix account and an X display per person (the image; needs "
                         "root). single: every person is a folder under --homes and commands run "
                         "as this user — for a machine you do not want accounts made on. "
                         "Default: single.")
    ap.add_argument("--bind", default=os.environ.get(BIND_ENV) or DEFAULT_BIND,
                    help="address to listen on (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=int(os.environ.get(PORT_ENV) or P.DEFAULT_PORT))
    ap.add_argument("--homes", default=None,
                    help="where homes live (default: /home for ubuntu, "
                         "~/pantheon-workstation for single)")
    ap.add_argument("--skeleton", default="/etc/skel",
                    help="what a new or reset home is copied from (default /etc/skel)")
    ap.add_argument("--pairing-dir", default=os.environ.get(P.PAIRING_DIR_ENV)
                    or P.DEFAULT_PAIRING_DIR,
                    help=f"where the token is kept for Pantheon (default {P.DEFAULT_PAIRING_DIR}); "
                         f"ignored when {P.TOKEN_ENV} is set")
    ap.add_argument("--pairing-group", type=_gid, default=os.environ.get(PAIRING_GID_ENV, ""),
                    metavar="GID",
                    help="the group that may read the token: Pantheon's PGID "
                         f"(also ${PAIRING_GID_ENV})")
    # Exactly two words, not a yes/no vocabulary of this package's own
    # (`B97`): the image's command line is the only caller.
    ap.add_argument("--sudo", choices=("on", "off"), default=None,
                    help="whether accounts may sudo until an admin says otherwise. ubuntu: default "
                         "on, and the admin's last choice is kept across restarts. single: only "
                         "lifts the home jail; default off.")
    ap.add_argument("--log-level", default="INFO",
                    choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    # ── `P20-07`, added ──────────────────────────────────────────────────────
    ap.add_argument("--backend", choices=P.BACKENDS, default=os.environ.get(BACKEND_ENV) or None,
                    help="what `health` says this workstation is. Default: looked at — "
                         "`container` for --system ubuntu inside a container, `remote` otherwise. "
                         "`vm` is said only by the VM backend's own machines.")
    ap.add_argument("--tls-cert", default=os.environ.get(TLS_CERT_ENV) or None, metavar="PEM",
                    help="serve HTTPS with this certificate (and --tls-key). Required for a "
                         "daemon Pantheon reaches across a public network: the client refuses to "
                         "send the token there in the clear.")
    ap.add_argument("--tls-key", default=os.environ.get(TLS_KEY_ENV) or None, metavar="PEM")
    ap.add_argument("--token-file", default=None, metavar="PATH",
                    help="read the token from this file (one line) and write nothing: how the "
                         "systemd unit hands it over. Beats the pairing directory; "
                         f"{P.TOKEN_ENV} beats both.")
    return ap


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    # A string default goes through `type` too, so the environment's
    # `PANTHEON_WORKSTATION_PAIRING_GID` is checked exactly like the flag.
    args = parser().parse_args(argv)
    if args.homes is None:
        args.homes = "/home" if args.system == "ubuntu" else str(Path.home() / "pantheon-workstation")
    args.sudo = (args.system == "ubuntu") if args.sudo is None else args.sudo == "on"
    if not 0 <= args.port <= 65535:
        parser().error("--port is 0 to 65535")
    # `P20-07`.
    if bool(args.tls_cert) != bool(args.tls_key):
        parser().error("--tls-cert and --tls-key go together")
    if args.tls_cert is None and _public_literal(args.bind):
        parser().error(f"--bind {args.bind} is a public address: the token would cross it in the "
                       "clear, and Pantheon's client refuses to send it there. Give --tls-cert "
                       "and --tls-key, or bind a private address.")
    if args.backend is None:
        from workstation import machine
        args.backend = machine.default_backend(args.system, machine.virtualization())
    return args


def _public_literal(bind: str) -> bool:
    """A bind address that is a literal, globally routable IP (`P20-07`).
    `0.0.0.0` is not: it is every interface, and which of them is reachable
    from where is the network's to say, not this process's."""
    import ipaddress
    try:
        ip = ipaddress.ip_address(bind.strip("[]"))
    except ValueError:
        return False
    return not ip.is_unspecified and ip.is_global


def make_system(args: argparse.Namespace) -> System:
    if args.system == "ubuntu":
        # Imported here: the module needs Linux's setfsuid, and `single` runs
        # anywhere Python does.
        from workstation.ubuntu import UbuntuSystem
        reserved = [args.pairing_group] if args.pairing_group is not None else []
        system: System = UbuntuSystem(Path(args.homes), skeleton=Path(args.skeleton),
                                      sudo_default=args.sudo, reserved_ids=reserved)
        # `P20-07`: the class says `container`; the command line says what
        # this one is (a VM's machine, or a host it was installed on).
        system.backend = getattr(args, "backend", None) or system.backend
        return system
    system = SingleUserSystem(Path(args.homes), skeleton=Path(args.skeleton),
                              backend=getattr(args, "backend", None) or "remote")
    system.set_sudo(args.sudo)
    return system


def secure_pairing(pairing_dir: Path, gid: Optional[int]) -> None:
    """The directory `root:<gid> 0750`, the token `root:<gid> 0640` — or both
    the running user's alone when there is no group (module docstring)."""
    token = pairing_dir / P.TOKEN_FILENAME
    if not token.exists():
        return
    if os.geteuid() == 0 and gid is not None:
        os.chown(pairing_dir, 0, gid)
        os.chmod(pairing_dir, 0o750)
        os.chown(token, 0, gid)
        os.chmod(token, 0o640)
    else:
        os.chmod(pairing_dir, 0o700)
        os.chmod(token, 0o600)


def check_pairing_group(system: System, gid: Optional[int]) -> None:
    """Refuse to share the token with an account that owns the pairing group."""
    if gid is None:
        return
    registry = getattr(system, "registry", None)
    if registry is None:
        return
    for account in registry.accounts():
        if registry.get(account) == gid:
            raise WorkstationError(
                "unavailable",
                f"The pairing group {gid} is also the group of workstation account {account}, "
                "so that person's agent could read Pantheon's token. Give Pantheon a different "
                "PGID, or move that account's home aside.")


def build(args: argparse.Namespace):
    """`(server, system)`, listening, not yet serving."""
    system = make_system(args)
    check_pairing_group(system, args.pairing_group)
    from_env = bool((os.environ.get(P.TOKEN_ENV) or "").strip())
    token_file = getattr(args, "token_file", None)
    if token_file and not from_env:
        token = read_token_file(Path(token_file))  # `P20-07`
    else:
        pairing = Path(args.pairing_dir) if args.pairing_dir else None
        token = load_or_create_token(pairing)
        if not from_env and pairing is not None:
            secure_pairing(pairing, args.pairing_group)
    tls = None
    if getattr(args, "tls_cert", None):
        tls = server_context(Path(args.tls_cert), Path(args.tls_key))
    server = make_server(system, token, bind=args.bind, port=args.port, tls=tls)
    return server, system


def read_token_file(path: Path) -> str:
    """`--token-file` (`P20-07`): one line, read and never written."""
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise WorkstationError("unavailable", f"The token file {path} could not be read: "
                                              f"{e.strerror or e}.")
    if not token:
        raise WorkstationError("unavailable", f"The token file {path} is empty.")
    return token


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(stream=sys.stdout, level=getattr(logging, args.log_level),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        server, system = build(args)
    except WorkstationError as e:
        logger.error("%s", e.message)
        return 2
    host, port = server.server_address[:2]
    logger.info("workstation listening on %s:%s — system %s, backend %s, sudo %s, protocol v%s%s",
                host, port, args.system, system.backend, "on" if system.sudo else "off",
                P.PROTOCOL_VERSION, ", TLS" if getattr(args, "tls_cert", None) else "")

    def stop(signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logger.info("workstation stopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
