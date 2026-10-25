# SPDX-License-Identifier: AGPL-3.0-or-later
"""Looking at the network the workstation sits on — `P16-20`, `D-2026-10-25-02`.

The owner, 2026-10-25: *"The user and its agents should be able to task about
their network… subnets and all."* This is the daemon's half: it names this
machine's interfaces, finds which hosts on a range answer, and says which ports
a host has open. It runs as the account, inside the workstation's network mode
(the kernel's nft rules, `workstation/netrules.py`) — so *internet only* or
*none* refuses a LAN target here the same way it refuses the browser, and *full*
(the default) lets it through.

**It maps, it does not evade.** These are the operator's own networks. The pace
below exists so a sweep does not flood a small LAN or a switch, not to stay under
anyone's notice — there is nobody to hide from on a network you own, and a tool
that behaved as if there were would be lying about what it is for.

**Standard library only**, like the rest of this package: liveness is a TCP
connect, not a raw ICMP packet, so it needs no `CAP_NET_RAW` and works whether or
not an admin granted it (`workstation_net_raw`). A connect that is refused is as
good as one that is accepted for *is this host here* — a refusal came from the
host. `ip` is the one external program, and only to read addresses; a machine
without it still scans, it just cannot list its own interfaces.

The scope — which ranges the agent may sweep at all — is Pantheon's, decided on
the server from the person's declared networks (`src/networks.py`) before a call
reaches here. This module enforces only the size bound, because a daemon that
trusted its caller to keep sweeps small is a daemon one bug away from a /8.
"""
from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from workstation import protocol as P


class NetScanError(ValueError):
    """A refusal with a sentence, carried out as `WorkstationError` by agentd."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# The ports a sweep knocks on to decide a host is up, and to say a little about
# it in one pass. A representative spread — remote login, web, file sharing,
# databases, printing, remote desktop — not an exhaustive list; `ports` probes a
# host in full. Ordered most-common first so a host usually answers on the first
# few and the rest time out in parallel.
DISCOVERY_PORTS: Tuple[int, ...] = (
    80, 443, 22, 445, 139, 3389, 8080, 8443, 53, 21, 23, 25, 3306, 5432, 6379,
    27017, 9100, 631, 161, 548, 5900, 111, 2049, 1883, 8006, 32400,
)
#: What each well-known port usually is, for the one-line summary. Not a promise
#: about the host — a service can listen anywhere — just a hint the model reads.
PORT_NAMES: Dict[int, str] = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns", 80: "http",
    110: "pop3", 111: "rpcbind", 139: "netbios", 143: "imap", 161: "snmp",
    389: "ldap", 443: "https", 445: "smb", 465: "smtps", 514: "syslog",
    548: "afp", 587: "smtp", 631: "ipp", 993: "imaps", 995: "pop3s",
    1433: "mssql", 1883: "mqtt", 2049: "nfs", 3000: "http-dev", 3306: "mysql",
    3389: "rdp", 5000: "http-dev", 5432: "postgres", 5900: "vnc", 6379: "redis",
    8006: "proxmox", 8080: "http-alt", 8443: "https-alt", 8123: "home-assistant",
    9000: "http-alt", 9100: "printer", 9200: "elasticsearch", 11211: "memcached",
    27017: "mongodb", 32400: "plex", 51820: "wireguard",
}

_CONNECT_TIMEOUT_S = 0.6
_MAX_WORKERS = 64
# A breather between batches, so a sweep is gentle on a small network rather
# than a burst of a thousand connections at once.
_BATCH = 256
_BATCH_PAUSE_S = 0.05


def _is_ip(text: str) -> Optional[ipaddress._BaseAddress]:
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def interfaces() -> List[Dict[str, Any]]:
    """This machine's network interfaces, each with its addresses and the CIDR
    of the network it is on — what the agent reads to know which subnets exist.
    Empty when `ip` is not installed (said in the answer, not an error)."""
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
            addrs.append({"ip": str(ip_s), "cidr": str(net), "family": f"ipv{net.version}",
                          "hosts": _net_size(net)})
        if addrs:
            out.append({"name": name, "up": link.get("operstate") == "UP",
                        "mac": link.get("address") or "", "addresses": addrs})
    return out


def _net_size(net: ipaddress._BaseNetwork) -> int:
    """How many addresses a sweep of this network would knock on (host count,
    not counting network/broadcast for small v4 nets). Capped at the bound so a
    /8's 16 million never becomes an int the caller has to reason about."""
    n = net.num_addresses
    if net.version == 4 and net.prefixlen <= 30:
        n -= 2
    return min(max(n, 1), P.NET_SCAN_MAX_HOSTS + 1)


def _addresses_of(target: str) -> Tuple[List[ipaddress._BaseAddress], Optional[str]]:
    """The addresses a `scan` target expands to: a CIDR's hosts, a single IP, or
    the addresses a name resolves to. Returns `(addresses, cidr_or_None)`."""
    target = (target or "").strip()
    if not target:
        raise NetScanError("bad_request", "Give a range to scan, like 192.168.1.0/24 or a host.")
    if "/" in target:
        try:
            net = ipaddress.ip_network(target, strict=False)
        except ValueError as e:
            raise NetScanError("bad_request", f"{target!r} is not a network: {e}.")
        size = net.num_addresses - (2 if net.version == 4 and net.prefixlen <= 30 else 0)
        if size > P.NET_SCAN_MAX_HOSTS:
            raise NetScanError(
                "bad_request",
                f"{target} is {size} addresses; a sweep is at most {P.NET_SCAN_MAX_HOSTS} "
                f"(a /{32 - (P.NET_SCAN_MAX_HOSTS.bit_length() - 1)} for IPv4). Scan a smaller "
                "range, or use the shell for a bigger one.")
        hosts = list(net.hosts()) if (net.version == 4 and net.prefixlen <= 30) else [
            a for a in net][:P.NET_SCAN_MAX_HOSTS]
        return hosts, str(net)
    ip = _is_ip(target)
    if ip is not None:
        return [ip], None
    # A name: resolve it here, on the account's own resolver.
    try:
        infos = socket.getaddrinfo(target, None)
    except OSError as e:
        raise NetScanError("refused", f"{target} did not resolve: {e.strerror or e}.")
    seen: List[ipaddress._BaseAddress] = []
    for info in infos:
        a = _is_ip(info[4][0].split("%")[0])
        if a is not None and a not in seen:
            seen.append(a)
    if not seen:
        raise NetScanError("refused", f"{target} did not resolve to an address.")
    return seen[:P.NET_SCAN_MAX_HOSTS], None


def _probe(addr: str, port: int, timeout: float) -> str:
    """One TCP connect: 'open', 'refused' (host is there, port shut), or
    'filtered' (no answer — host down, or the port dropped)."""
    family = socket.AF_INET6 if ":" in addr else socket.AF_INET
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((addr, port))
        return "open"
    except socket.timeout:
        return "filtered"
    except ConnectionRefusedError:
        return "refused"
    except OSError:
        return "filtered"
    finally:
        try:
            s.close()
        except OSError:
            pass


def _clean_ports(raw: Any, default: Sequence[int]) -> List[int]:
    if raw is None:
        return list(default)
    if not isinstance(raw, (list, tuple)):
        raise NetScanError("bad_request", "“ports” is a list of port numbers.")
    out: List[int] = []
    for p in raw:
        if isinstance(p, bool) or not isinstance(p, int) or not 1 <= p <= 65535:
            raise NetScanError("bad_request", f"{p!r} is not a port (1–65535).")
        if p not in out:
            out.append(p)
    if len(out) > P.NET_SCAN_MAX_PORTS:
        raise NetScanError("bad_request",
                           f"At most {P.NET_SCAN_MAX_PORTS} ports at a time; you gave {len(out)}.")
    return out


def _sweep(pairs: Sequence[Tuple[str, int]], timeout: float) -> Dict[Tuple[str, int], str]:
    """Probe every (address, port), a batch at a time with a breather between,
    so the burst stays small on a little network."""
    result: Dict[Tuple[str, int], str] = {}
    workers = min(_MAX_WORKERS, max(1, len(pairs)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(pairs), _BATCH):
            batch = pairs[start:start + _BATCH]
            futures = {pool.submit(_probe, a, p, timeout): (a, p) for a, p in batch}
            for fut in concurrent.futures.as_completed(futures):
                result[futures[fut]] = fut.result()
            if start + _BATCH < len(pairs):
                time.sleep(_BATCH_PAUSE_S)
    return result


def scan(body: Dict[str, Any]) -> Dict[str, Any]:
    """Find which hosts on a range answer, and a little of what each runs. A
    host is up if any discovery port is open or refused — both came from it."""
    addrs, cidr = _addresses_of(str(body.get("target") or body.get("range") or body.get("host") or ""))
    ports = _clean_ports(body.get("ports"), DISCOVERY_PORTS)
    timeout = _timeout(body)
    pairs = [(str(a), p) for a in addrs for p in ports]
    started = time.monotonic()
    probed = _sweep(pairs, timeout)
    hosts = []
    for a in addrs:
        s = str(a)
        states = {p: probed[(s, p)] for p in ports}
        openp = [p for p in ports if states[p] == "open"]
        up = bool(openp) or any(v == "refused" for v in states.values())
        if up:
            hosts.append({"ip": s, "open": [{"port": p, "name": PORT_NAMES.get(p, "")} for p in openp]})
    return {"ok": True, "action": "scan", "cidr": cidr, "scanned": len(addrs),
            "ports_each": ports, "up": len(hosts), "hosts": hosts,
            "took_ms": int((time.monotonic() - started) * 1000)}


def ports(body: Dict[str, Any]) -> Dict[str, Any]:
    """Which ports a single host answers on: the given list, or a wide common
    set. Says open, refused and filtered apart, because the difference is what a
    person debugging a firewall is asking about."""
    target = str(body.get("host") or body.get("target") or "").strip()
    if not target:
        raise NetScanError("bad_request", "Give a host to probe, like 192.168.1.10.")
    addrs, _ = _addresses_of(target)
    addr = str(addrs[0])
    wide = tuple(sorted(set(DISCOVERY_PORTS) | set(PORT_NAMES)))
    want = _clean_ports(body.get("ports"), wide)
    timeout = _timeout(body)
    started = time.monotonic()
    states = _sweep([(addr, p) for p in want], timeout)
    openp, refused, filtered = [], 0, 0
    for p in want:
        st = states[(addr, p)]
        if st == "open":
            openp.append({"port": p, "name": PORT_NAMES.get(p, "")})
        elif st == "refused":
            refused += 1
        else:
            filtered += 1
    return {"ok": True, "action": "ports", "host": addr, "resolved_from": target if target != addr else None,
            "probed": len(want), "open": openp, "refused": refused, "filtered": filtered,
            "reachable": bool(openp) or refused > 0,
            "took_ms": int((time.monotonic() - started) * 1000)}


def _timeout(body: Dict[str, Any]) -> float:
    raw = body.get("timeout_ms")
    if raw is None:
        return _CONNECT_TIMEOUT_S
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 50 <= raw <= 5000:
        raise NetScanError("bad_request", "“timeout_ms” is between 50 and 5000.")
    return raw / 1000.0


def act(action: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """One `network` action (`protocol.NETWORK_ACTIONS`)."""
    if action == "interfaces":
        ifs = interfaces()
        return {"ok": True, "action": "interfaces", "interfaces": ifs,
                "ip_available": shutil.which("ip") is not None}
    if action == "scan":
        return scan(body)
    if action == "ports":
        return ports(body)
    raise NetScanError("bad_request", f"“{action}” is not a network action.")
