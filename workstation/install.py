#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Make this Ubuntu machine a Pantheon workstation — `P20-07`.

    sudo python3 workstation/install.py            # on the machine that will be the workstation
    sudo python3 workstation/install.py --dry-run  # every step it would take, and none taken

For a machine an admin points Pantheon at — a Proxmox or libvirt VM, a spare
box — without Pantheon becoming a hypervisor manager (`DEFERRED.md` D-03: point
at a machine). Copy the repository's `workstation/` folder there (or clone the
repository) and run this. It is a script, not an agent: deterministic, it
prints every step before it takes it, and `--dry-run` takes none
(`netagent/install.py`'s rule).

**What it does, in order.**

  1. The workstation's packages and files: `provision.sh`, the same list the
     container image is built from (`Law 14`) — the desktop, the tools and
     Mozilla's Firefox with its no-phone-home policy. It adds Mozilla's apt
     repository, pinned. A machine set aside for this is the intended home.
  2. The daemon's code in `/opt/pantheon-workstation/`, and a skeleton of its
     own there, so this machine's `/etc/skel` is left as it was.
  3. A token in `/etc/pantheon-workstation/token` (root, 0600) — kept across
     re-runs, so Pantheon's copy stays right.
  4. TLS, unless `--no-tls`: a certificate for this machine's names and
     addresses in `/etc/pantheon-workstation/tls/`, also kept across re-runs.
     Pantheon trusts exactly that certificate by its SHA-256 fingerprint
     (`protocol.TLS_PIN_ENV`). **Why TLS by default:** the token is a bearer
     secret that drives every person's account, and root with `sudo` on;
     Pantheon will not send it in the clear to a public address at all, and on
     a network this script cannot see, encrypted is the answer that is right
     either way. `--no-tls` is for a LAN or a VPN, where the owner's ruling is
     that traffic between his own machines is normal (`D-2026-09-01-03`).
  5. A systemd service (`workstation/service.py`), `--system ubuntu
     --backend remote`, listening on 0.0.0.0:7040, started now and at boot.
  6. A health check of what it started, and the lines to add to Pantheon's
     `.env` — the one-line backend switch and the three values that go with it.

`--uninstall` stops and removes the service and the two folders above. Homes
and their Unix accounts stay: they are people's work.

Standard library only, nothing from Pantheon (the package's rule): this runs on
a machine where Pantheon is not installed.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workstation import protocol as P  # noqa: E402
from workstation import service  # noqa: E402
from workstation.agentd import mint_token  # noqa: E402

HERE = Path(__file__).resolve().parent
OPT = Path("/opt/pantheon-workstation")
ETC = Path("/etc/pantheon-workstation")
TOKEN_FILE = ETC / "token"
TLS_DIR = ETC / "tls"
REMOTE_OVERLAY = "docker/workstation-remote.yml"


def say(message: str = "") -> None:
    print(message, flush=True)


class Plan:
    """Every step said before it is taken; with `dry_run`, only said. `root`
    puts every path under another directory — how the tests run it."""

    def __init__(self, *, dry_run: bool, root: Path = Path("/"),
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.dry_run = dry_run
        self.root = Path(root)
        self._run = run

    def path(self, p: Path) -> Path:
        return self.root / Path(p).relative_to("/")

    def do(self, what: str, argv: List[str], **env: str) -> None:
        say(f"  · {what}")
        if self.dry_run:
            say(f"      would run: {' '.join(argv)}")
            return
        done = self._run(argv, env={**os.environ, **env} if env else None)
        if done.returncode != 0:
            raise SystemExit(f"  ! {argv[0]} failed (exit {done.returncode}). Nothing after this "
                             "step was done; fix what it said and run this again.")

    def write(self, what: str, path: Path, data: bytes, mode: int) -> None:
        target = self.path(path)
        say(f"  · {what}: {path}")
        if self.dry_run:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name("." + target.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, target)


# ── this machine's names ──────────────────────────────────────────────────────

def primary_address() -> str:
    """The address this machine reaches other machines from. A UDP connect
    picks the route and sends nothing."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # TEST-NET-1: routed like anything else, never reached
        return str(sock.getsockname()[0])
    except OSError:
        return ""
    finally:
        sock.close()


def machine_names(extra: List[str]) -> List[str]:
    """What the certificate names: the host name, its fully qualified name,
    the primary address, and anything `--name` adds. Loopback is left out —
    Pantheon is not on this machine."""
    names: List[str] = []
    for name in [socket.gethostname(), socket.getfqdn(), primary_address(), *extra]:
        name = (name or "").strip()
        if not name or name in names:
            continue
        try:
            if ipaddress.ip_address(name).is_loopback:
                continue
        except ValueError:
            if name in ("localhost", "localhost.localdomain"):
                continue
        names.append(name)
    return names


def san(names: List[str]) -> str:
    parts = []
    for name in names:
        try:
            ipaddress.ip_address(name)
            parts.append(f"IP:{name}")
        except ValueError:
            parts.append(f"DNS:{name}")
    return ",".join(parts)


def fingerprint(pem: str) -> str:
    """`AB:CD:…` — the form `openssl x509 -fingerprint -sha256` prints, and the
    one Pantheon's client reads (`src/workstation_client.normalise_pin`)."""
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def make_certificate(plan: Plan, names: List[str]) -> Optional[str]:
    cert, key = TLS_DIR / "cert.pem", TLS_DIR / "key.pem"
    if plan.path(cert).exists() and plan.path(key).exists():
        say(f"  · keeping the certificate already in {TLS_DIR} (Pantheon's pin stays right)")
        return fingerprint(plan.path(cert).read_text())
    say(f"  · a TLS certificate for {', '.join(names) or 'this machine'}, valid ten years "
        "(Pantheon pins it, so its expiry is not what it trusts)")
    if plan.dry_run:
        return None
    plan.path(TLS_DIR).mkdir(parents=True, exist_ok=True)
    os.chmod(plan.path(TLS_DIR), 0o700)
    argv = ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes", "-days", "3650", "-subj", f"/CN={names[0] if names else 'pantheon-workstation'}",
            "-keyout", str(plan.path(key)), "-out", str(plan.path(cert)),
            "-addext", "extendedKeyUsage=serverAuth"]
    if names:
        argv += ["-addext", f"subjectAltName={san(names)}"]
    done = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if done.returncode != 0:
        raise SystemExit(f"  ! openssl could not make the certificate: "
                         f"{done.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    os.chmod(plan.path(key), 0o600)
    return fingerprint(plan.path(cert).read_text())


# ── the unit, the token, the check ────────────────────────────────────────────

def remote_unit(*, port: int, bind: str, tls: bool) -> str:
    argv = service.exec_argv(
        backend="remote", token_file=str(TOKEN_FILE), bind=bind, port=port,
        skeleton=str(OPT / "skel"),
        tls_cert=str(TLS_DIR / "cert.pem") if tls else None,
        tls_key=str(TLS_DIR / "key.pem") if tls else None)
    return service.unit(description="Pantheon workstation daemon (P20-07)", workdir=str(OPT),
                        argv=argv)


def existing_token(plan: Plan) -> str:
    try:
        return plan.path(TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def check(port: int, *, tls: bool, pin: Optional[str], token: str, wait: float = 30.0,
          host: str = "127.0.0.1") -> Dict:
    """`health` from the service just started — over TLS with exactly the
    pinned certificate, as Pantheon will see it."""
    deadline = time.monotonic() + wait
    last = ""
    while time.monotonic() < deadline:
        try:
            if tls:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
                conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                    host, port, timeout=5, context=ctx)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", P.ROUTES["health"][1], headers={"Authorization": f"Bearer {token}"})
            if tls and pin:
                der = conn.sock.getpeercert(binary_form=True)  # type: ignore[union-attr]
                got = hashlib.sha256(der).hexdigest()
                if got != pin.replace(":", "").lower():
                    raise SystemExit("  ! the service answered with a certificate other than the "
                                     "one just made; something else is on that port.")
            answer = json.loads(conn.getresponse().read())
            conn.close()
            if answer.get("agent") == P.AGENT_NAME:
                return answer
            last = f"something answered that is not a workstation: {answer!r:.200}"
        except (OSError, ValueError, http.client.HTTPException) as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.0)
    raise SystemExit(f"  ! the service did not answer on port {port} within {wait:.0f} s ({last}). "
                     "`journalctl -u pantheon-workstation` says why.")


def env_lines(*, url: str, token: str, pin: Optional[str]) -> List[str]:
    lines = [f"COMPOSE_FILE=docker-compose.yml:{REMOTE_OVERLAY}",
             f"{P.URL_ENV}={url}", f"{P.TOKEN_ENV}={token}"]
    if pin:
        lines.append(f"{P.TLS_PIN_ENV}={pin}")
    return lines


# ── install, uninstall ────────────────────────────────────────────────────────

def install(args: argparse.Namespace, plan: Plan) -> int:
    tls = not args.no_tls
    names = machine_names(args.name)
    address = args.address or primary_address() or socket.gethostname()
    url = f"{'https' if tls else 'http'}://{address}:{args.port}"
    say("Pantheon workstation — installer (P20-07)")
    say("=" * 66)
    say(f"  this machine   {', '.join(names) or '?'}")
    say(f"  listens on     {args.bind}:{args.port} ({'HTTPS' if tls else 'plain HTTP'})")
    say(f"  Pantheon uses  {url}")
    if not tls:
        say("")
        say("  NOTE: plain HTTP. Pantheon sends the token only to a private address")
        say("  (a LAN, a VPN); anything public it refuses. Drop --no-tls for HTTPS.")
    say("")
    if not args.dry_run and plan.root == Path("/") and os.geteuid() != 0:
        raise SystemExit("  ! run it as root (sudo): it installs packages, makes an account per "
                         "person and starts a service.")
    if args.packages:
        plan.do("the workstation's packages (provision.sh: the desktop, the tools, Mozilla's "
                "Firefox) — several minutes", ["sh", str(HERE / "provision.sh"), "packages"])
    else:
        say("  · skipping packages (--no-packages)")
    plan.do(f"the daemon, its skeleton ({OPT}) and Firefox's policy",
            ["sh", str(HERE / "provision.sh"), "files", "--skel", str(plan.path(OPT / "skel")),
             "--code", str(plan.path(OPT)),
             "--policies", str(plan.path(Path("/etc/firefox/policies")))])
    token = existing_token(plan)
    if token:
        say(f"  · keeping the token already in {TOKEN_FILE}")
    else:
        token = mint_token()
        plan.write("a new token, root only", TOKEN_FILE, (token + "\n").encode(), 0o600)
    pin = make_certificate(plan, names) if tls else None
    plan.write("the service", Path(service.UNIT_PATH),
               remote_unit(port=args.port, bind=args.bind, tls=tls).encode(), 0o644)
    if args.start:
        plan.do("systemd told about it", ["systemctl", "daemon-reload"])
        plan.do("started now and at every boot", ["systemctl", "enable", service.UNIT_NAME])
        plan.do("(re)started", ["systemctl", "restart", service.UNIT_NAME])
        if not args.dry_run:
            answer = check(args.port, tls=tls, pin=pin, token=token)
            say(f"  · it answers: backend {answer.get('backend')}, "
                f"{(answer.get('machine') or {}).get('virtualization', '?')}, "
                f"sudo {'on' if answer.get('sudo') else 'off'}")
    else:
        say("  · not starting it (--no-start)")
    say("")
    say("=" * 66)
    if args.dry_run:
        say("  DRY RUN — nothing was installed, written or started.")
        return 0
    say("  Add these lines to Pantheon's .env (the folder with docker-compose.yml),")
    say("  then run `docker compose up -d` there and turn it on in")
    say("  Settings → Workstation:")
    say("")
    for line in env_lines(url=url, token=token, pin=pin):
        say(f"      {line}")
    say("")
    say("  (Windows: separate COMPOSE_FILE with ; instead of :)")
    say("  The token is in the second line: keep it like a password. It is also")
    say(f"  in {TOKEN_FILE} here, readable by root only.")
    if shutil.which("ufw"):
        status = subprocess.run(["ufw", "status"], capture_output=True, text=True)
        if "Status: active" in (status.stdout or ""):
            say("")
            say(f"  ufw is on here. Let Pantheon's machine in:  sudo ufw allow from "
                f"<pantheon-host> to any port {args.port} proto tcp")
    return 0


def uninstall(args: argparse.Namespace, plan: Plan) -> int:
    say("Pantheon workstation — removing the service (P20-07)")
    plan.do("stopped and disabled", ["systemctl", "disable", "--now", service.UNIT_NAME])
    for path in (Path(service.UNIT_PATH), OPT, ETC):
        say(f"  · removing {path}")
        if not args.dry_run:
            target = plan.path(path)
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
    plan.do("systemd told", ["systemctl", "daemon-reload"])
    say("  Homes in /home/pw-* and their Unix accounts are kept: they are people's work.")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sudo python3 workstation/install.py",
                                 description="Make this Ubuntu machine a Pantheon workstation.")
    ap.add_argument("--dry-run", action="store_true", help="say every step and take none")
    ap.add_argument("--port", type=int, default=P.DEFAULT_PORT)
    ap.add_argument("--bind", default="0.0.0.0",
                    help="address to listen on (default every interface: Pantheon is elsewhere)")
    ap.add_argument("--address", default="",
                    help="the address Pantheon reaches this machine at, if not its primary one")
    ap.add_argument("--name", action="append", default=[],
                    help="another name or address for the certificate (repeatable)")
    ap.add_argument("--no-tls", action="store_true",
                    help="plain HTTP: only for a LAN or a VPN (Pantheon refuses it otherwise)")
    ap.add_argument("--no-packages", dest="packages", action="store_false",
                    help="skip apt (the packages are already there)")
    ap.add_argument("--no-start", dest="start", action="store_false",
                    help="write the service but do not start it")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--root", default="/", help=argparse.SUPPRESS)  # tests: a directory, not /
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser().error("--port is 1 to 65535")
    plan = Plan(dry_run=args.dry_run, root=Path(args.root))
    return uninstall(args, plan) if args.uninstall else install(args, plan)


if __name__ == "__main__":
    raise SystemExit(main())
