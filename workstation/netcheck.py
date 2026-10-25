# SPDX-License-Identifier: AGPL-3.0-or-later
"""What network this machine is on, and whether it can reach one host.

`P16-20`, trimmed by `D-2026-10-25-03`. The owner, 2026-10-25: *"literally just
a 'what's around me' thing"* — connectivity across their own networks, nothing
more. So the daemon answers two questions:

  * **interfaces** — this machine's network interfaces, each with its address
    and the CIDR of the network it is on;
  * **reach** — can this workstation open a TCP connection to *one* host on
    *one* port? Connected, refused (the host answered and nothing is listening,
    or a firewall rejected it), or no answer — plus whether the route leaves
    this machine's own subnets, i.e. goes through the gateway/firewall, which is
    the first place to look when two segments can't talk.

One connection per call. No ranges, no port lists: that is the shell's business
if a person wants it, not a tool the model drives.

It runs as the account, inside the workstation's network mode (the kernel's nft
rules, `workstation/netrules.py`), so *internet only* or *none* refuses a LAN
target here the same way it refuses the browser. Standard library only; `ip` is
the one external program, and only to read addresses.
"""
from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Sequence

#: How long `reach` waits for an answer by default, and the bounds a caller may
#: set. Long enough for a slow link across a gateway; short enough that a
#: dropped packet doesn't hang a turn.
REACH_TIMEOUT_MS = 3000
REACH_TIMEOUT_RANGE_MS = (50, 10000)


class NetCheckError(ValueError):
    """A refusal with a sentence, carried out as `WorkstationError` by agentd."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def interfaces() -> List[Dict[str, Any]]:
    """This machine's network interfaces, each with its addresses and the CIDR
    of the network it is on. Empty when `ip` is not installed (said in the
    answer, not an error)."""
    ip = shutil.which("ip")
    if not ip:
        return []
    try:
        done = subprocess.run([ip, "-j", "addr", "show"], capture_output=True,
                              text=True, timeout=10)
        raw = json.loads(done.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    out: List[Dict[str, Any]] = []
    for link in raw if isinstance(raw, list) else []:
        name = str(link.get("ifname") or "")
        if not name or name == "lo":
            continue
        addrs = []
        for a in link.get("addr_info") or []:
            ip_s = a.get("local")
            plen = a.get("prefixlen")
            if not ip_s or plen is None:
                continue
            try:
                net = ipaddress.ip_network(f"{ip_s}/{plen}", strict=False)
            except ValueError:
                continue
            if net.is_loopback or (net.version == 6 and net.is_link_local):
                continue
            addrs.append({"ip": str(ip_s), "cidr": str(net), "family": f"ipv{net.version}"})
        if addrs:
            out.append({"name": name, "up": link.get("operstate") == "UP",
                        "addresses": addrs})
    return out


def _own_subnets() -> List[ipaddress._BaseNetwork]:
    nets: List[ipaddress._BaseNetwork] = []
    for iface in interfaces():
        for a in iface.get("addresses") or []:
            try:
                nets.append(ipaddress.ip_network(a["cidr"], strict=False))
            except (ValueError, KeyError):
                continue
    return nets


def _via_gateway(addr: ipaddress._BaseAddress,
                 own: Optional[Sequence[ipaddress._BaseNetwork]] = None) -> Optional[bool]:
    """True when `addr` is not on one of this machine's own subnets (the route
    goes through the gateway); None when that can't be told (no `ip`)."""
    own = _own_subnets() if own is None else own
    if not own:
        return None
    return not any(addr.version == n.version and addr in n for n in own)


def _resolve(host: str) -> ipaddress._BaseAddress:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise NetCheckError("bad_request", f"“{host}” doesn't resolve to an address from here.")
    for info in infos:
        try:
            return ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
    raise NetCheckError("bad_request", f"“{host}” doesn't resolve to an address from here.")


def _connect(addr: str, port: int, timeout: float) -> str:
    """One TCP connection: 'connected', 'refused', or 'no answer'."""
    family = socket.AF_INET6 if ":" in addr else socket.AF_INET
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((addr, port))
        return "connected"
    except ConnectionRefusedError:
        return "refused"
    except (socket.timeout, OSError):
        return "no answer"
    finally:
        try:
            s.close()
        except OSError:
            pass


def _port(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 65535:
        raise NetCheckError("bad_request", "“port” is one port number, 1 to 65535.")
    return raw


def _timeout(raw: Any) -> float:
    if raw is None:
        return REACH_TIMEOUT_MS / 1000.0
    lo, hi = REACH_TIMEOUT_RANGE_MS
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not lo <= raw <= hi:
        raise NetCheckError("bad_request", f"“timeout_ms” is between {lo} and {hi}.")
    return raw / 1000.0


def _deny_list(raw: Any) -> List[tuple]:
    """`[{"name": str, "cidrs": [str]}]` -> `[(name, [network])]`; malformed
    entries are a bad request, not silently skipped (a deny list that drops
    what it can't parse is an allow list)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise NetCheckError("bad_request", "“deny” is a list of {name, cidrs}.")
    out = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("cidrs"), list):
            raise NetCheckError("bad_request", "“deny” is a list of {name, cidrs}.")
        nets = []
        for c in item["cidrs"]:
            try:
                nets.append(ipaddress.ip_network(str(c), strict=False))
            except ValueError:
                raise NetCheckError("bad_request", f"“deny” has an unreadable range {c!r}.")
        out.append((str(item.get("name") or "untrusted"), nets))
    return out


def reach(body: Dict[str, Any]) -> Dict[str, Any]:
    """Can this workstation connect to `host` on `port`? One connection."""
    host = str(body.get("host") or "").strip()
    if not host:
        raise NetCheckError("bad_request", "Give a host, like 192.168.1.10 or nas.lan.")
    if "/" in host:
        raise NetCheckError("bad_request", "`reach` checks one host, not a range.")
    port = _port(body.get("port"))
    timeout = _timeout(body.get("timeout_ms"))
    addr = _resolve(host)
    # Pantheon decides which networks the agent may not connect to and sends
    # them as `deny`; checked here, after the name resolved in THIS machine and
    # before any packet leaves, so a name that lands in a denied range is
    # refused rather than reached and then reported.
    for name, cidrs in _deny_list(body.get("deny")):
        if any(addr.version == c.version and addr in c for c in cidrs):
            raise NetCheckError("forbidden",
                                f"{host} resolves to {addr}, which is in network “{name}”, marked "
                                "untrusted — Pantheon doesn't open connections there for the agent.")
    started = time.monotonic()
    result = _connect(str(addr), port, timeout)
    return {"ok": True, "action": "reach", "host": host, "address": str(addr), "port": port,
            "result": result, "via_gateway": _via_gateway(addr),
            "took_ms": int((time.monotonic() - started) * 1000),
            "timeout_ms": int(timeout * 1000)}


def act(action: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """One `network` action (`protocol.NETWORK_ACTIONS`)."""
    if action == "interfaces":
        return {"ok": True, "action": "interfaces", "interfaces": interfaces(),
                "ip_available": shutil.which("ip") is not None}
    if action == "reach":
        return reach(body)
    raise NetCheckError("bad_request", f"“{action}” is not a network action.")
