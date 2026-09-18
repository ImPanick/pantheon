# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discovery: the devices that announce themselves, when an operator asks.

`P17-10`, split out of `P17-03` on 2026-09-11 rather than claimed with it. The
neighbour table is *who this machine has already talked to*; this is *who will
answer if you ask the local segment*. A device that has never exchanged a packet
with this host appears here and nowhere else, which is the row's first `Verify:`
clause.

**IT IS OFF UNTIL SOMEBODY TURNS IT ON, AND THAT IS A DECISION, NOT AN
OVERSIGHT.** Everything else in this package observes: it reads a file, a kernel
table, or a socket's own source address, and no packet leaves. This is the first
thing in `P17` that **sends**, and what it sends is multicast — the whole
segment hears it. A self-hosted AI workspace that broadcasts service queries
onto its owner's network because it was installed is not a feature, it is a
surprise, and on a corporate segment it is a surprise somebody's IDS writes down.
So `DiscoveryPolicy.enabled` defaults `False`, the server starts with it off, and
`--discover` is how an operator says yes. `D-2026-09-18-03` records the call.

**LAW 16 — NOTHING HERE CONSULTS AN EXTERNAL SERVICE.** "What the router knows"
means what the router *volunteers on its own segment*: its SSDP announcement,
its mDNS records. It does not mean an IP-geolocation lookup, a MAC-vendor API or
a device-fingerprint service. Vendor names, when we have them, come from
`netagent.oui`, which is a table on disk (`P17-04` made that choice already and
this module inherits it). The only packets this module sends are two multicast
datagrams to two fixed group addresses on the local link.

**THE ADDRESSES ARE CONSTANTS AND THERE IS NO PARAMETER THAT NAMES ONE.**
`discover()` takes a policy and a predicate; it does not take a destination.
That is the same property `src/netagent_client.call()` has and the same reason:
*"enumerate 169.254.169.254"* has nowhere to be put. Belt and braces, every send
goes through `_assert_local_group`, which refuses an address that is not a
multicast group in the link-local or organisation-local scopes — so even a
future edit that makes a group configurable arrives at a refusal rather than at
an SSRF. And every socket sets `IP_MULTICAST_TTL = 1`: a datagram from this
module **cannot leave the local segment**, as a property of the packet rather
than of our intentions.

**SSDP HANDS YOU A URL. WE DO NOT FETCH IT.** Every M-SEARCH response carries a
`LOCATION:` pointing at the device's description XML, and fetching it is the
obvious next step and the actual hole: it is an HTTP request, from the process
that has the LAN, to an address chosen by whatever answered — which on a segment
with one hostile device is an SSRF with a friendly name. The header is
*reported* and never followed. Nothing in this module opens a TCP connection and
a test asserts it.

**DHCP LEASES ARE NOT HERE, DELIBERATELY.** The row says the leases are the
router's rather than this machine's, so reading them means credentials for a
device whose API is per-vendor and undocumented — an integration, not an
observation, and `P17-05` keeps configuration-shaped work out of this package.
What a router volunteers over SSDP *is* local and *is* reported, and that is the
line: we read what is announced on the segment and we do not log in to anything.

Standard library only (package rule 1): `socket` and `struct`. No subprocess —
shelling out to `avahi-browse` or `dns-sd` would be a subprocess in the process
that has the LAN, and it is not installed on two of the three platforms anyway.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import random
import socket
import struct
import time
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("netagent.discovery")

# The two groups, and they are the only destinations in this file.
MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353
SSDP_GROUP = "239.255.255.250"
SSDP_PORT = 1900

# The DNS-SD meta-query: "what service types exist here?". One question, and
# every responder answers with the types it offers. Asking `_services._dns-sd`
# rather than sweeping a list of service names keeps this one packet instead of
# twenty, which matters when the packet is multicast.
MDNS_META_QUERY = "_services._dns-sd._udp.local"

ENV_DISCOVERY = "PANTHEON_NETAGENT_DISCOVERY"

# Bounds. A discovery that can be asked to listen for a minute, or to buffer
# whatever a chatty segment sends, is a way to make a small process hold a large
# string — the same reasoning `server._body` already applies to request bodies.
MAX_WAIT_SECONDS = 6.0
DEFAULT_WAIT_SECONDS = 2.5
MAX_RESPONSES = 256
MAX_DATAGRAM = 4096


class DiscoveryRefused(RuntimeError):
    """A destination that is not a local multicast group. Never caught here."""


class DiscoveryPolicy:
    """Whether this agent may ask the segment anything, and for how long.

    Mirrors `execute.ExecPolicy`: a small object the operator's flags build, so
    the decision lives in one place and the routes read it rather than each
    deciding for themselves.
    """

    __slots__ = ("enabled", "wait")

    def __init__(self, enabled: bool = False, wait: float = DEFAULT_WAIT_SECONDS) -> None:
        self.enabled = bool(enabled)
        try:
            wait = float(wait)
        except (TypeError, ValueError):
            wait = DEFAULT_WAIT_SECONDS
        # Clamped rather than validated-and-refused: an operator who typed 30
        # wants a longer listen, and the honest answer is the longest we will
        # do rather than an error about a number.
        self.wait = min(max(wait, 0.2), MAX_WAIT_SECONDS)

    @classmethod
    def from_env_and_args(cls, enabled: Optional[bool] = None,
                          wait: Optional[float] = None) -> "DiscoveryPolicy":
        if enabled is None:
            # env-spelling: `netagent` imports nothing from the app
            # (package rule 1), so `src/env_flags.py` cannot be called here.
            # These are the three words `--allow-exec` already takes, matched
            # rather than widened — `B91`'s rule is that a strict list is the
            # point, because a host carrying `...=on` should not start
            # broadcasting because somebody guessed a truthy-looking word.
            enabled = os.environ.get(ENV_DISCOVERY, "").strip().lower() in (
                "1", "true", "yes")
        return cls(enabled=enabled, wait=wait if wait is not None else DEFAULT_WAIT_SECONDS)

    def refusal(self) -> str:
        return ("discovery is off. It sends multicast onto this segment, so it "
                "is a thing you turn on rather than a thing that happens: start "
                f"the agent with --discover, or set ${ENV_DISCOVERY}=1.")

    def as_dict(self) -> dict:
        return {"enabled": self.enabled, "wait_seconds": round(self.wait, 2)}


def _assert_local_group(address: str) -> ipaddress.IPv4Address:
    """Refuse any destination that is not a local-scope multicast group.

    The two constants above already satisfy this, so today it can only fire on
    a mistake. That is the point: the check is on the *send*, so a later change
    that threads an address in from anywhere — a setting, a query parameter, a
    response field — meets a refusal instead of reaching a host. `224.0.0.0/24`
    is the link-local control block (mDNS lives there) and `239.0.0.0/8` is the
    organisation-local scope (SSDP lives there). `169.254.169.254` is not
    multicast at all and is refused by the first clause, which is the address
    this check exists to be pointed at.
    """
    try:
        ip = ipaddress.ip_address(str(address).strip())
    except ValueError as exc:
        raise DiscoveryRefused(f"{address!r} is not an address") from exc
    # ONE DECISION, NOT TWO. This was written as a multicast check followed by a
    # scope check, and mutation testing showed the first could not change an
    # answer: both scopes are entirely multicast, so anything that fails
    # `is_multicast` already fails the scope test. A branch that cannot change an
    # answer is deleted rather than tested around — the same call `allowlist.py`
    # records for its own dead `is_empty()` guard, and for the same reason:
    # keeping it suggests the non-multicast case needs special handling, which is
    # an invitation to "fix" it in the permissive direction.
    link_local = ipaddress.ip_network("224.0.0.0/24")   # mDNS lives here
    org_local = ipaddress.ip_network("239.0.0.0/8")     # SSDP lives here
    if ip.version != 4 or not (ip in link_local or ip in org_local):
        raise DiscoveryRefused(
            f"{address} is not a local multicast group ({link_local} or "
            f"{org_local}); discovery sends to this segment and nowhere else")
    return ip


def _socket(ttl: int = 1) -> socket.socket:
    """A UDP socket that cannot leave this segment.

    `IP_MULTICAST_TTL = 1` is the control, not a default worth inheriting: a
    router decrements it to zero, so the datagram is undeliverable off-link as a
    property of the packet. Nothing about this module's reach then depends on
    our own bookkeeping being right.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(ttl))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
    sock.bind(("", 0))
    return sock


def _collect(sock: socket.socket, deadline: float) -> List[Tuple[bytes, str]]:
    """Every datagram that arrives before the deadline, bounded both ways."""
    out: List[Tuple[bytes, str]] = []
    while len(out) < MAX_RESPONSES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            sock.settimeout(remaining)
            payload, addr = sock.recvfrom(MAX_DATAGRAM)
        except socket.timeout:
            break
        except OSError:
            # A closed or unusable socket ends the listen. Discovery is best
            # effort by nature — a quiet answer and a broken socket look the
            # same to the caller, and `supported` distinguishes the cases that
            # matter.
            break
        if payload:
            out.append((payload, addr[0]))
    return out


# ── mDNS ─────────────────────────────────────────────────────────────────────


def _encode_name(name: str) -> bytes:
    out = bytearray()
    for label in name.strip(".").split("."):
        raw = label.encode("utf-8")[:63]
        out.append(len(raw))
        out += raw
    out.append(0)
    return bytes(out)


def _decode_name(data: bytes, offset: int) -> Tuple[str, int]:
    """A DNS name, following compression pointers, bounded against a loop.

    A malformed or hostile packet can point a label back at itself; the hop
    budget is what makes that a truncated name rather than a hang in a process
    that has the LAN.
    """
    labels: List[str] = []
    hops = 0
    cursor = offset
    after: Optional[int] = None
    while cursor < len(data) and hops < 64:
        length = data[cursor]
        if length == 0:
            cursor += 1
            break
        if length & 0xC0 == 0xC0:
            if cursor + 1 >= len(data):
                break
            pointer = ((length & 0x3F) << 8) | data[cursor + 1]
            if after is None:
                after = cursor + 2
            if pointer >= len(data) or pointer == cursor:
                break
            cursor = pointer
            hops += 1
            continue
        cursor += 1
        labels.append(data[cursor:cursor + length].decode("utf-8", "replace"))
        cursor += length
    return ".".join(labels), (after if after is not None else cursor)


def _mdns_query(query: str = MDNS_META_QUERY) -> bytes:
    """One PTR question, with the unicast-response bit set.

    QU (`0x8000` on the question class) asks responders to answer this socket
    directly instead of re-multicasting to the whole segment. It is the polite
    form: one query, and the answers do not become traffic every other device
    has to read.
    """
    header = struct.pack("!HHHHHH", random.getrandbits(16), 0, 1, 0, 0, 0)
    question = _encode_name(query) + struct.pack("!HH", 12, 0x8001)  # PTR, IN|QU
    return header + question


def _parse_mdns(payload: bytes) -> Dict[str, object]:
    """Names and service types out of one response. Never raises."""
    names: List[str] = []
    addresses: List[str] = []
    try:
        _ident, _flags, qd, an, ns, ar = struct.unpack_from("!HHHHHH", payload, 0)
        cursor = 12
        for _ in range(min(qd, 32)):
            _name, cursor = _decode_name(payload, cursor)
            cursor += 4
        for _ in range(min(an + ns + ar, 128)):
            if cursor >= len(payload):
                break
            _name, cursor = _decode_name(payload, cursor)
            if cursor + 10 > len(payload):
                break
            rtype, _rclass, _ttl, rdlen = struct.unpack_from("!HHIH", payload, cursor)
            cursor += 10
            rdata = payload[cursor:cursor + rdlen]
            if rtype in (12, 33):  # PTR, SRV — both carry a name we want
                value, _ = _decode_name(payload, cursor if rtype == 12 else cursor + 6)
                if value:
                    names.append(value)
            elif rtype == 1 and rdlen == 4:  # A
                addresses.append(socket.inet_ntoa(rdata))
            cursor += rdlen
    except (struct.error, IndexError, UnicodeDecodeError):
        # A partial parse of a real response is more useful than nothing, and a
        # malformed packet from a device on the segment is normal rather than
        # exceptional. Whatever was read before the break is returned.
        pass
    return {"names": sorted(set(n for n in names if n))[:16],
            "addresses": sorted(set(addresses))[:8]}


def mdns(wait: float = DEFAULT_WAIT_SECONDS) -> Dict[str, object]:
    """Ask the segment what services it offers. Never raises."""
    group = _assert_local_group(MDNS_GROUP)
    rows: Dict[str, Dict[str, object]] = {}
    sock = None
    try:
        sock = _socket()
        sock.sendto(_mdns_query(), (str(group), MDNS_PORT))
        for payload, source in _collect(sock, time.monotonic() + wait):
            parsed = _parse_mdns(payload)
            row = rows.setdefault(source, {"address": source, "source": "mdns",
                                           "names": [], "addresses": []})
            row["names"] = sorted(set(row["names"]) | set(parsed["names"]))[:16]
            row["addresses"] = sorted(set(row["addresses"]) | set(parsed["addresses"]))[:8]
    except DiscoveryRefused:
        raise
    except OSError as exc:
        return {"supported": False, "responders": [],
                "detail": f"mDNS query failed ({type(exc).__name__})"}
    finally:
        if sock is not None:
            sock.close()
    return {"supported": True, "responders": list(rows.values())}


# ── SSDP ─────────────────────────────────────────────────────────────────────


def _ssdp_query(mx: int = 1) -> bytes:
    """`M-SEARCH * HTTP/1.1` for everything, with the shortest legal spread.

    `MX` is how long responders may wait before answering, so it is the floor on
    how long we listen. 1 keeps the listen short; `ST: ssdp:all` is the whole
    point — asking for one device type would be asking the question we already
    know the answer to.
    """
    return ("M-SEARCH * HTTP/1.1\r\n"
            f"HOST: {SSDP_GROUP}:{SSDP_PORT}\r\n"
            'MAN: "ssdp:discover"\r\n'
            f"MX: {int(mx)}\r\n"
            "ST: ssdp:all\r\n"
            "USER-AGENT: pantheon-netagent/1 UPnP/1.0\r\n"
            "\r\n").encode("ascii")


def _parse_ssdp(payload: bytes) -> Dict[str, str]:
    """The headers worth reporting. `LOCATION` is reported and never fetched."""
    fields: Dict[str, str] = {}
    try:
        text = payload.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return fields
    for line in text.splitlines()[1:]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in ("server", "st", "usn", "location"):
            fields[key] = value.strip()[:300]
    return fields


def ssdp(wait: float = DEFAULT_WAIT_SECONDS) -> Dict[str, object]:
    """Ask the segment what UPnP devices are on it. Never raises, never fetches."""
    group = _assert_local_group(SSDP_GROUP)
    rows: Dict[str, Dict[str, object]] = {}
    sock = None
    try:
        sock = _socket()
        sock.sendto(_ssdp_query(), (str(group), SSDP_PORT))
        for payload, source in _collect(sock, time.monotonic() + max(wait, 1.2)):
            fields = _parse_ssdp(payload)
            row = rows.setdefault(source, {"address": source, "source": "ssdp",
                                           "services": []})
            if fields.get("server"):
                row["server"] = fields["server"]
            if fields.get("location"):
                # Verbatim, and unfetched. Reporting it is data; following it
                # would be an HTTP request to an address chosen by whatever
                # answered, made from the one process on this machine that has
                # the LAN.
                row["location"] = fields["location"]
                row["location_fetched"] = False
            st = fields.get("st") or fields.get("usn")
            if st and st not in row["services"]:
                row["services"] = (row["services"] + [st])[:16]
    except DiscoveryRefused:
        raise
    except OSError as exc:
        return {"supported": False, "responders": [],
                "detail": f"SSDP search failed ({type(exc).__name__})"}
    finally:
        if sock is not None:
            sock.close()
    return {"supported": True, "responders": list(rows.values())}


# ── the one entry point ──────────────────────────────────────────────────────


def _sort_key(row: Dict[str, object]):
    try:
        return (0, int(ipaddress.ip_address(str(row.get("address", "")))))
    except ValueError:
        return (1, 0)


def filter_to(rows: List[Dict[str, object]], allows: Callable[[str], bool]
              ) -> List[Dict[str, object]]:
    """Keep only the responders the caller may be answered about.

    Same shape and same reasoning as `neighbours.filter_to`: the segment is the
    segment's, what may be *reported* is the allowlist's, and the predicate is
    passed in so the gate stays in one place (`P17-02`) and this module stays
    testable without one. The row's third `Verify:` clause is this function plus
    the `withheld` count `discover` puts beside it — **a broadcast cannot be
    gated the way a target can, so the answers are filtered and the filtering is
    said out loud.**
    """
    return [r for r in rows if allows(str(r.get("address", "")))]


def discover(policy: Optional[DiscoveryPolicy] = None,
             allows: Optional[Callable[[str], bool]] = None) -> Dict[str, object]:
    """Both protocols, filtered, with what was withheld counted.

    **There is no destination parameter and there will not be one.** The groups
    are module constants checked on every send; the only inputs are the
    operator's policy and the allowlist predicate. A caller cannot name a host
    and neither can anything that talks to a caller.
    """
    policy = policy if policy is not None else DiscoveryPolicy()
    if not policy.enabled:
        return {"enabled": False, "responders": [], "count": 0,
                "detail": policy.refusal()}
    allows = allows if allows is not None else (lambda _address: False)

    merged: Dict[str, Dict[str, object]] = {}
    protocols: Dict[str, object] = {}
    for name, fn in (("mdns", mdns), ("ssdp", ssdp)):
        result = fn(policy.wait)
        protocols[name] = {"supported": result.get("supported", False),
                           "responders": len(result.get("responders") or []),
                           "detail": result.get("detail", "")}
        for row in result.get("responders") or []:
            address = str(row.get("address", ""))
            if not address:
                continue
            existing = merged.get(address)
            if existing is None:
                merged[address] = dict(row)
                merged[address]["sources"] = [name]
            else:
                # A device answering both protocols is one device. Merging on
                # the address rather than reporting it twice is the same call
                # `P17-04` made for the inventory, for the same reason: an
                # operator counting rows to answer "what is on my network"
                # should not count a machine once per protocol it speaks.
                for key, value in row.items():
                    if key in ("address", "source"):
                        continue
                    if isinstance(value, list):
                        existing[key] = sorted(set(existing.get(key) or []) | set(value))[:16]
                    else:
                        existing.setdefault(key, value)
                existing["sources"] = sorted(set(existing["sources"]) | {name})
        # `source` was per-protocol; `sources` is the merged answer.
    seen = sorted(merged.values(), key=_sort_key)
    for row in seen:
        row.pop("source", None)
    kept = filter_to(seen, allows)
    return {
        "enabled": True,
        "protocols": protocols,
        "responders": kept,
        "count": len(kept),
        # Said out loud for the same reason `/neighbours` says it: a filtered
        # list that looks complete is worse than a short one, because an
        # operator who allowed the wrong CIDR concludes their network is empty
        # rather than that their allowlist is wrong.
        "seen_total": len(seen),
        "withheld": len(seen) - len(kept),
        "policy": policy.as_dict(),
    }
