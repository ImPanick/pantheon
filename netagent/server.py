# SPDX-License-Identifier: AGPL-3.0-or-later
"""The agent's HTTP surface. Read it in one sitting; that is the security model.

`P17-01`. Four routes, all authenticated, none of which changes anything —
`P17-05` decided that configuration is a separate risk class and does not ride
in on observation.

**Why `http.server` and not FastAPI.** Package rule 1: this runs on the
operator's host, and a host is not a place to install a web framework so a laptop
can describe its own interfaces. The stdlib server is enough for four read-only
routes on a LAN, and it is small enough that the reader can see there is no
fifth route hiding in it.

**Binding to loopback is the default and it is not the whole answer.** On Docker
Desktop the container reaches the host through `host.docker.internal`, which does
not arrive on `127.0.0.1`. So the bind address is a parameter with a loopback
default: the safe value ships, and the operator who needs the container to reach
it makes that choice deliberately and knows they made it. `Law 16` — nothing
listens beyond this machine unless a person said so.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Optional
from urllib.parse import parse_qs, urlsplit

if __package__ in (None, ""):  # running the file directly on the host
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from netagent import neighbours as neighbour_table
from netagent import observe
from netagent.allowlist import ENV_CIDRS, ENV_HOSTS, Allowlist
from netagent.tokens import bearer_credential, load_or_create, token_matches

logger = logging.getLogger("netagent")

DEFAULT_PORT = 7010
DEFAULT_BIND = "127.0.0.1"

# The name this build answers to, so a caller can tell it reached the agent and
# not something else that happens to be on the port.
AGENT = "pantheon-netagent"
VERSION = 1


# Routes that need no target. Every one is a read; there is deliberately no
# writer (`P17-05`).
def _routes(allowlist: Allowlist) -> Dict[str, Callable[[], object]]:
    return {
        "/health": lambda: {
            "agent": AGENT, "version": VERSION, "ok": True,
            # What this agent will answer for, so an operator can see the
            # boundary without guessing at it. Readable, never writable — there
            # is no route that sets it, which is the point of `P17-02`.
            "allowlist": allowlist.as_dict(),
        },
        "/whoami": observe.whoami,
        "/networks": lambda: {"networks": observe.networks_seen()},
        # `P17-03`, and the owner's original ask. Not a scan: nothing is probed
        # and a quiet device does not appear. The table is the machine's; what
        # may be *reported* from it is the allowlist's, so the rows are filtered
        # here rather than inside the reader — one gate, at the door.
        "/neighbours": lambda: _neighbours_for(allowlist),
    }


def _neighbours_for(allowlist: Allowlist) -> Dict[str, object]:
    result = neighbour_table.neighbours()
    rows = result.get("neighbours") or []
    kept = neighbour_table.filter_to(rows, allowlist.allows)
    result["neighbours"] = kept
    result["count"] = len(kept)
    # Said out loud, because a filtered list that looks complete is worse than a
    # short one: an operator who allowed the wrong CIDR would otherwise conclude
    # their network is empty rather than that their allowlist is wrong.
    result["seen_total"] = len(rows)
    result["devices"] = sum(1 for r in kept if r.get("kind") == "device")
    result["withheld"] = len(rows) - len(kept)
    result["allowlist"] = allowlist.as_dict()
    return result


# Routes that take a `target`, and therefore go through the allowlist. Kept in
# their own table so that adding one cannot accidentally skip the gate: the
# dispatcher checks membership in THIS dict to decide whether a target is
# required, so a target route that forgot to check is not a shape this file has.
TARGET_ROUTES: Dict[str, Callable[[str], object]] = {
    "/reach": observe.reach,
    # A forward lookup is an outbound channel — resolving
    # `<secret>.attacker.example.com` puts the secret in somebody's DNS logs
    # without a packet reaching the "target" — so names go through the same gate
    # as addresses, which means a forward lookup works only for a name the
    # operator listed with `--allow-host`.
    "/dns": observe.resolve,
}


class Handler(BaseHTTPRequestHandler):
    server_version = f"{AGENT}/{VERSION}"
    sys_version = ""          # do not advertise the Python version
    token_hash = ""           # set by `serve()`
    allowlist: Allowlist = Allowlist()

    def log_message(self, fmt, *args):  # noqa: A003
        # The default writes to stderr with no level and no logger. Route it so
        # an operator can silence it, and never log the Authorization header —
        # `BaseHTTPRequestHandler` does not, but the next person adding a log
        # line here should see the rule stated.
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Nothing here is for a browser, and a browser reaching it should not be
        # able to keep the answer or be talked into sending one.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        raw = bearer_credential(self.headers.get("Authorization", ""))
        return bool(raw) and token_matches(raw, self.token_hash)

    def _target(self) -> Optional[str]:
        query = parse_qs(urlsplit(self.path).query)
        values = query.get("target") or []
        return values[0].strip() if values and values[0].strip() else None

    def do_GET(self) -> None:  # noqa: N802  (stdlib naming)
        path = urlsplit(self.path).path.rstrip("/") or "/health"
        if not self._authorised():
            # 401 before the route lookup, so an unauthenticated caller cannot
            # learn which paths exist by comparing 401 against 404.
            self._send(401, {"error": "unauthorized"})
            return

        plain = _routes(self.allowlist)
        if path in TARGET_ROUTES:
            target = self._target()
            if not target:
                self._send(400, {"error": f"{path} needs a ?target="})
                return
            # `P17-02`. The gate, and it is the only door: the dispatcher decides
            # a route needs a target by its membership in `TARGET_ROUTES`, so a
            # new target route cannot be added without arriving here. Refused
            # because the address was never named — not because anything
            # declined, which is not a security control.
            if not self.allowlist.allows(target):
                self._send(403, {"error": self.allowlist.refusal(target),
                                 "allowlist": self.allowlist.as_dict()})
                return
            try:
                self._send(200, TARGET_ROUTES[path](target))
            except Exception as e:  # noqa: BLE001
                logger.exception("route %s failed", path)
                self._send(500, {"error": f"{type(e).__name__}"})
            return

        handler = plain.get(path)
        if handler is None:
            self._send(404, {"error": "no such route",
                             "routes": sorted(list(plain) + list(TARGET_ROUTES))})
            return
        try:
            self._send(200, handler())
        except Exception as e:  # noqa: BLE001
            logger.exception("route %s failed", path)
            self._send(500, {"error": f"{type(e).__name__}"})

    def do_POST(self) -> None:  # noqa: N802
        # `P17-05`: changing firewall rules, router settings or DHCP is a
        # different risk class from reading them, and bundling it into the first
        # version would mean the thing that describes your network can also break
        # it. There is no writer here, and this says so rather than 501-ing by
        # accident.
        self._send(405, {"error": "this agent is read-only; see P17-05"})


def serve(*, bind: str = DEFAULT_BIND, port: int = DEFAULT_PORT,
          state_dir: Path | None = None, serve_forever: bool = True,
          allowlist: Allowlist | None = None):
    allowlist = allowlist if allowlist is not None else Allowlist.from_env_and_args()
    state = Path(state_dir) if state_dir else Path.home() / ".pantheon-netagent"
    token_hash, minted = load_or_create(state)
    if minted:
        # Once, on stdout, and never again — the file holds only the hash.
        print("\n" + "=" * 68)
        print("  A token was minted for this agent. Paste it into Pantheon:")
        print(f"\n      {minted}\n")
        print("  Settings -> Networks -> Agent. It is not recoverable from")
        print(f"  {state / 'token.json'}, which holds only its hash.")
        print("=" * 68 + "\n", flush=True)

    if allowlist.rejected:
        # Loud, because a typo in a security boundary that silently narrows it is
        # the kindest possible failure and still the wrong one.
        logger.warning("ignoring unparseable allowlist entries: %s",
                       ", ".join(allowlist.rejected))
    if allowlist.is_empty():
        logger.warning("no allowlist: this agent will refuse every target. "
                       "Start it with --allow <cidr> to answer for a network.")
    else:
        logger.info("allowlist: %s", allowlist.describe())

    handler = type("BoundHandler", (Handler,),
                   {"token_hash": token_hash, "allowlist": allowlist})
    httpd = ThreadingHTTPServer((bind, port), handler)
    logger.info("netagent listening on %s:%s", bind, port)
    if not serve_forever:
        return httpd
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        # Ctrl-C is how an operator stops a foreground process. Letting the
        # traceback print would suggest something went wrong when the person
        # asked for exactly this; `finally` still closes the socket.
        pass
    finally:
        httpd.server_close()
    return httpd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="netagent",
        description="The Pantheon network agent. Read-only; runs on the host.")
    ap.add_argument("--bind", default=os.environ.get("PANTHEON_NETAGENT_BIND", DEFAULT_BIND),
                    help="address to listen on (default 127.0.0.1; use the host's "
                         "LAN or bridge address if a container must reach it)")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("PANTHEON_NETAGENT_PORT", DEFAULT_PORT)))
    ap.add_argument("--state-dir", default=os.environ.get("PANTHEON_NETAGENT_STATE", ""))
    ap.add_argument("--allow", action="append", default=[], metavar="CIDR",
                    help="a network this agent may be asked about, e.g. "
                         "192.168.1.0/24. Repeatable. With none given the agent "
                         f"refuses every target. Also read from ${ENV_CIDRS}.")
    ap.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                    help="a single name this agent may be asked about. Names are "
                         "never resolved to decide membership, so a name matches "
                         f"only by exact listing. Also read from ${ENV_HOSTS}.")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    serve(bind=args.bind, port=args.port,
          state_dir=Path(args.state_dir) if args.state_dir else None,
          allowlist=Allowlist.from_env_and_args(args.allow, args.allow_host))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
