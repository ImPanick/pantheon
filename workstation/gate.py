# SPDX-License-Identifier: AGPL-3.0-or-later
"""`python3 -m workstation.gate` — the workstation's network gate (`P20-06`).

WHY IT IS A SEPARATE CONTAINER
==============================

The adversary is code an agent was steered into running (`D-2026-09-30-03`),
and with `sudo` on — the default — that code is root in the workstation. A rule
root can change is not a boundary, so the rules that hold the admin's network
mode cannot live anywhere the workstation's root can write. Measured 2026-10-01
in this image, each alternative the row asked about:

* **Rules kept by the daemon inside the workstation** (per account, `meta
  skuid`): an account with `sudo` off was refused the LAN; the same probe as
  root reached it, and `nft delete table` lifted the rule for everyone. Holds
  only while `sudo` is off — and the workstation would need `CAP_NET_ADMIN`
  to write them, which hands it to its root as well.
* **This gate**: it OWNS the network namespace (`docker/workstation.yml` puts
  the workstation in it with `network_mode: service:workstation-net`) and holds
  `CAP_NET_ADMIN`; the workstation holds neither it nor `CAP_NET_RAW`. Root in
  the workstation: `nft flush ruleset` and `ip route add` → *Operation not
  permitted*; an `AF_PACKET` or raw socket → refused at creation; `unshare -n`
  → refused; `/proc/sys` is read-only. The probes gave the mode's answer as an
  account and as root alike. **Dropping `CAP_NET_RAW` is load-bearing**: with
  Docker's default set kept, root wrote its own Ethernet frames and got a
  SYN-ACK from a LAN host the rules refuse — `AF_PACKET` is below the hook.
* **A compose `internal: true` network** held against root too (no route at
  all), but it is fixed when the container is created, cannot say *internet
  only*, and needs Pantheon on two networks. **An egress proxy** holds only
  for programs that use it. Both were left.

A gate restart makes a new namespace and leaves the workstation in the old one
with nothing but loopback (measured): it fails closed, and Pantheon sees the
workstation down until it is recreated with the gate (`docker compose up -d`).

WHAT IT DOES
============

Two routes (`protocol.GATE_ROUTES`) on its own port: `health`, which anyone
may ask (the mode is not a secret), and `mode`, which needs the gate's token —
generated into its own pairing volume, which Pantheon mounts read-only and the
workstation does not mount at all. Its mode is kept in that volume so a restart
puts back the last one; with none kept it starts at `none` and Pantheon sets
the admin's choice on its next call (every tool call syncs, `P20-03`). Every
mode it reports was read back from the kernel after it was written, and a
narrowing mode is then tested (`netrules.self_test`) before it answers.

Standard library only and nothing from Pantheon, like the rest of the package.
"""
from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

from workstation import netrules
from workstation import protocol as P
from workstation.agentd import VERSION, WorkstationError, bearer, load_or_create_token

logger = logging.getLogger("pantheon.workstation.gate")

MODE_FILENAME = "mode"
#: Before Pantheon has said anything, and with nothing kept: the narrowest.
BOOT_MODE = "none"


class Gate:
    """The mode, written to the kernel and read back. HTTP-free, so the tests
    call it directly with a fake `nft`."""

    def __init__(self, state_dir: Path, *, run: netrules.Runner = netrules._run,
                 nft: Optional[str] = None,
                 self_test: Callable[[], str] = netrules.self_test,
                 resolvers: Callable[[], List[str]] = netrules.lan_resolvers) -> None:
        self.state_dir = Path(state_dir)
        self._run = run
        self._nft = nft
        self._self_test = self_test
        self._resolvers = resolvers
        self._lock = threading.Lock()
        self._state: Dict = {"mode": None, "self_test": None, "applied_at": None}

    def kept_mode(self) -> str:
        try:
            mode = (self.state_dir / MODE_FILENAME).read_text(encoding="utf-8").strip()
        except OSError:
            return BOOT_MODE
        return mode if mode in P.NETWORK_MODES else BOOT_MODE

    def _keep(self, mode: str) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_dir / MODE_FILENAME
        tmp = path.with_name("." + path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(mode + "\n")
        os.replace(tmp, path)

    def set_mode(self, mode: str) -> Dict:
        if mode not in P.NETWORK_MODES:
            raise WorkstationError("bad_request", f"“mode” is one of {', '.join(P.NETWORK_MODES)}.")
        with self._lock:
            try:
                netrules.apply(netrules.ruleset(mode, table=netrules.GATE_TABLE,
                                                resolvers=self._resolvers()),
                               run=self._run, nft=self._nft)
                loaded = netrules.in_force(netrules.GATE_TABLE, run=self._run, nft=self._nft)
                if loaded != mode:
                    raise netrules.RulesError(
                        f"the kernel has {loaded or 'nothing readable'} loaded, not {mode}")
                tested = "not_needed" if mode == "full" else self._self_test()
            except netrules.RulesError as e:
                # What is loaded now is reported, not what was asked for.
                self._state.update(mode=netrules.in_force(netrules.GATE_TABLE, run=self._run,
                                                          nft=self._nft), self_test=None)
                logger.error("network mode %s was not put in force: %s", mode, e)
                raise WorkstationError("unavailable", f"The workstation's network gate could not "
                                                      f"put “{mode}” in force: {e}.")
            self._keep(mode)
            self._state.update(mode=mode, self_test=tested, applied_at=time.time())
            logger.info("network mode %s in force (self-test: %s)", mode, tested)
            return self.health()

    def start(self) -> Dict:
        return self.set_mode(self.kept_mode())

    def health(self) -> Dict:
        return {"ok": True, "agent": P.GATE_AGENT_NAME, "protocol": P.PROTOCOL_VERSION,
                "version": VERSION, "enforcement": "gate", **self._state}


class GateHandler(BaseHTTPRequestHandler):
    server_version = f"{P.GATE_AGENT_NAME}/{VERSION}"
    sys_version = ""
    gate: Gate
    token: str

    def log_message(self, fmt, *args):  # noqa: A003
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, payload: Dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _route(self, method: str) -> None:
        path = urlsplit(self.path).path.rstrip("/")
        try:
            if (method, path) == P.GATE_ROUTES["health"]:
                self._send(200, self.gate.health())
                return
            raw = bearer(self.headers.get("Authorization", ""))
            if not (raw and hmac.compare_digest(raw.encode(), self.token.encode())):
                # Before the route lookup, as the daemon does.
                raise WorkstationError("unauthorized", "The network gate's token is missing or wrong.")
            if (method, path) != P.GATE_ROUTES["mode"]:
                raise WorkstationError("not_found", "No such network gate route.")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise WorkstationError("bad_request", "Content-Length is not a number.")
            if not 0 < length <= 4096:
                raise WorkstationError("bad_request", "The request is a small JSON object.")
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise WorkstationError("bad_request", "The request body is not JSON.")
            if not isinstance(body, dict):
                raise WorkstationError("bad_request", "The request body is a JSON object.")
            self._send(200, self.gate.set_mode(body.get("mode")))
        except WorkstationError as e:
            self._send(P.ERRORS[e.code], P.error_body(e.code, e.message))
        except Exception as e:  # noqa: BLE001 — the caller gets a sentence, the log the trace
            logger.exception("network gate route %s failed", path)
            self._send(500, P.error_body("internal", f"The network gate failed: {type(e).__name__}."))

    def do_GET(self) -> None:  # noqa: N802
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._route("POST")


def make_server(gate: Gate, token: str, *, bind: str = "0.0.0.0",
                port: int = P.GATE_PORT) -> ThreadingHTTPServer:
    handler = type("BoundGateHandler", (GateHandler,), {"gate": gate, "token": token})
    httpd = ThreadingHTTPServer((bind, port), handler)
    httpd.daemon_threads = True
    return httpd


def parser() -> argparse.ArgumentParser:
    from workstation.__main__ import PAIRING_GID_ENV, _gid
    ap = argparse.ArgumentParser(prog="python3 -m workstation.gate",
                                 description="The Pantheon workstation's network gate "
                                             f"(protocol v{P.PROTOCOL_VERSION}, port {P.GATE_PORT}).")
    ap.add_argument("--bind", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=P.GATE_PORT)
    ap.add_argument("--pairing-dir", default=os.environ.get(P.GATE_PAIRING_DIR_ENV)
                    or P.DEFAULT_GATE_PAIRING_DIR,
                    help="where the gate's token and its mode are kept "
                         f"(default {P.DEFAULT_GATE_PAIRING_DIR})")
    ap.add_argument("--pairing-group", type=_gid, metavar="GID",
                    default=os.environ.get(PAIRING_GID_ENV, ""),
                    help="the group that may read the token: Pantheon's PGID")
    ap.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    import signal

    from workstation.__main__ import secure_pairing
    args = parser().parse_args(argv)
    logging.basicConfig(stream=sys.stdout, level=getattr(logging, args.log_level),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    pairing = Path(args.pairing_dir)
    try:
        # Its own token, never the workstation's variable: a value the
        # workstation knows would let its root open the gate (module docstring).
        token = load_or_create_token(pairing, env=None)
        secure_pairing(pairing, args.pairing_group)
        gate = Gate(pairing)
        gate.start()
    except WorkstationError as e:
        logger.error("%s", e.message)
        return 2
    server = make_server(gate, token, bind=args.bind, port=args.port)
    host, port = server.server_address[:2]
    logger.info("network gate listening on %s:%s — mode %s", host, port, gate.health()["mode"])

    def stop(signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logger.info("network gate stopping")
    finally:
        server.server_close()
    return 0



__all__ = ["BOOT_MODE", "Gate", "GateHandler", "MODE_FILENAME", "main", "make_server"]


if __name__ == "__main__":
    raise SystemExit(main())
