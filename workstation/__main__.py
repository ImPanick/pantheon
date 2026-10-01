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
                                load_or_create_token, make_server)

logger = logging.getLogger("pantheon.workstation")

BIND_ENV = "PANTHEON_WORKSTATION_BIND"
PORT_ENV = "PANTHEON_WORKSTATION_PORT"
PAIRING_GID_ENV = "PANTHEON_WORKSTATION_PAIRING_GID"
DEFAULT_BIND = "127.0.0.1"


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
    return args


def make_system(args: argparse.Namespace) -> System:
    if args.system == "ubuntu":
        # Imported here: the module needs Linux's setfsuid, and `single` runs
        # anywhere Python does.
        from workstation.ubuntu import UbuntuSystem
        reserved = [args.pairing_group] if args.pairing_group is not None else []
        system: System = UbuntuSystem(Path(args.homes), skeleton=Path(args.skeleton),
                                      sudo_default=args.sudo, reserved_ids=reserved)
        return system
    system = SingleUserSystem(Path(args.homes), skeleton=Path(args.skeleton), backend="remote")
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
    pairing = Path(args.pairing_dir) if args.pairing_dir else None
    token = load_or_create_token(pairing)
    if not from_env and pairing is not None:
        secure_pairing(pairing, args.pairing_group)
    server = make_server(system, token, bind=args.bind, port=args.port)
    return server, system


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
    logger.info("workstation listening on %s:%s — system %s, backend %s, sudo %s, protocol v%s",
                host, port, args.system, system.backend, "on" if system.sudo else "off",
                P.PROTOCOL_VERSION)

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
