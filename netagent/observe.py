# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the agent can see, and nothing it can change.

`P17-01` ships the two answers that prove the premise: which host am I, and what
networks am I actually on. `P17-03` adds neighbours, reachability, names and
services on top of this module; `P17-05` decided that *changing* anything is a
separate risk class and does not ride in on these.

Standard library only (package rule 1). `socket` and `ipaddress` are enough for
both answers, which is the point — the container's problem was never that
listing interfaces is hard.
"""
from __future__ import annotations

import ipaddress
import platform
import socket
from typing import Dict, List


def _addresses() -> List[str]:
    """Every address this host answers on, best effort.

    Two sources because neither is complete on its own: `getaddrinfo` on the
    hostname misses interfaces the resolver does not know about, and the
    UDP-connect trick finds only the one the default route would use. Merged and
    de-duplicated, they cover the case that matters — a host with a LAN address
    and a Docker bridge address, which is exactly the machine this runs on.

    Borrowed in shape from `companion/pairing.py:lan_ip_candidates`, which does
    the same thing for the same reason, one direction over.
    """
    found: List[str] = []

    def add(value: str) -> None:
        value = (value or "").strip()
        if value and value not in found:
            found.append(value)

    # The default-route address. No packets are sent; connect() on a UDP socket
    # only picks a source address.
    for probe, family in (("8.8.8.8", socket.AF_INET), ("2001:4860:4860::8888", socket.AF_INET6)):
        # `socket()` itself raises when the family is unavailable — an IPv6-less
        # container is `EAFNOSUPPORT` at construction, before any connect — so
        # the guard has to be around the whole block rather than the call that
        # looks like the risky one. Found by running this in the container it
        # exists to be different from.
        sock = None
        try:
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.settimeout(0.2)
            sock.connect((probe, 80))
            add(sock.getsockname()[0])
        except OSError:
            # No route, or no such family. Normal on an IPv4-only or IPv6-only
            # host, and not worth reporting as a failure.
            pass
        finally:
            if sock is not None:
                sock.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            add(info[4][0])
    except (OSError, socket.gaierror):
        # A host whose own name does not resolve still has the address above.
        pass
    return found


def _classify(addr: str) -> Dict[str, object]:
    """What kind of address this is, so a reader can tell a LAN from a bridge."""
    out: Dict[str, object] = {"address": addr}
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        out["kind"] = "unparseable"
        return out
    out["version"] = ip.version
    if ip.is_loopback:
        out["kind"] = "loopback"
    elif ip.is_link_local:
        out["kind"] = "link-local"
    elif ip.is_private:
        out["kind"] = "private"
    elif ip.is_global:
        out["kind"] = "global"
    else:
        out["kind"] = "other"
    # The /24 an operator would recognise as "their network". Stated rather than
    # guessed at: this is a display convenience and not a claim about the real
    # prefix length, which this process cannot see without a netlink call.
    if ip.version == 4 and out["kind"] == "private":
        out["assumed_network"] = str(ipaddress.ip_network(f"{ip}/24", strict=False))
    return out


def whoami() -> Dict[str, object]:
    """Identity and reach. The answer the container cannot give correctly.

    From inside the container this returns the bridge — `172.18.x` — and from
    the host it returns the real segments. That difference IS the row: the same
    call, two answers, and the one that is useful is only available where this
    process runs.
    """
    return {
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "addresses": [_classify(a) for a in _addresses()],
    }


def networks_seen() -> List[str]:
    """The private /24s this host sits on, deduplicated.

    What an operator would paste into the Networks panel. Offering it is the
    difference between "declare your networks" and "here is what I can see;
    which of these do you mean" — `Law 15`.
    """
    out: List[str] = []
    for entry in whoami()["addresses"]:
        net = entry.get("assumed_network")
        if net and net not in out:
            out.append(str(net))
    return out
