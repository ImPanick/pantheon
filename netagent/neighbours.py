# SPDX-License-Identifier: AGPL-3.0-or-later
"""The neighbour table: who this machine has actually talked to.

`P17-03`, and the owner's original ask — *"I wanted to make an agent perform and
organize an ARP table on my network but it's stuck inside the docker sandbox."*
The container's neighbour table is the **bridge's**: `172.18.0.1`, `.3`, `.5`.
No flag makes the host's real entries appear in it, because they are not the
container's neighbours. That is topology, not permissions, and it is why this
module runs where it does.

**NO SUBPROCESS, AND THAT IS WHY THIS FILE IS LONGER THAN `arp -a`.**
`netagent/__init__.py` rule 1 is standard library only, and the server has no
shell — shelling out to `arp` is one argument-quoting bug away from being one,
and on Windows it would also mean parsing a localised, format-unstable human
table. `ctypes` is standard library, `GetIpNetTable` is the API `arp.exe` itself
calls, and it returns a struct rather than prose. The Linux path reads
`/proc/net/arp`, which is a file.

**WHAT THIS IS AND IS NOT.** It is the machine's own cache — devices it has
exchanged traffic with recently. It is **not a scan**: nothing is probed, no
packet is sent, and a quiet device that has not spoken will not appear. That is a
feature. Turning a declaration into a sweep is how a *"look at my network"*
feature becomes a port scanner somebody's IDS reports, which is the same reason
`networks.hosts_in_scope` refuses to expand a CIDR.

Entries are filtered against the allowlist by the caller, not here. The table is
the machine's and this function reports it; deciding what may be *answered for*
belongs at the door (`P17-02`), where there is one of it.
"""
from __future__ import annotations

import ipaddress
import platform
import re
import socket
import struct
from typing import Dict, List, Optional

# `dwType` in MIB_IPNETROW, and the same vocabulary Linux's flags map onto, so
# one reader learns one set of words.
_TYPES = {1: "other", 2: "invalid", 3: "dynamic", 4: "static"}

_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")

BROADCAST_MAC = "ff:ff:ff:ff:ff:ff"


def _kind(address: str, mac: str) -> str:
    """Device, broadcast, or multicast.

    Found on the owner's real table 2026-09-11: a first run returned
    `192.168.1.255 / ff:ff:ff:ff:ff:ff` alongside nine actual machines. It is a
    genuine ARP entry and dropping it would be this module editing the kernel's
    table — but it is not a device, and an operator counting rows to answer
    *"what is on my network"* counts it as one. The row is kept and **labelled**,
    because the ask was to *organise* the table, and organising means the reader
    can tell a machine from a protocol artifact without knowing that
    `01:00:5e` is the IPv4 multicast prefix.
    """
    if mac == BROADCAST_MAC:
        return "broadcast"
    if mac.startswith("01:00:5e") or mac.startswith("33:33"):
        return "multicast"
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return "device"
    if ip.is_multicast:
        return "multicast"
    if ip.version == 4 and str(ip).endswith(".255"):
        # A /24 broadcast. The real prefix length is not visible from here, so
        # this is a heuristic and is named one rather than asserted: a host
        # legitimately numbered .255 inside a /23 would be mislabelled, which is
        # why the row is labelled rather than removed.
        return "broadcast"
    return "device"


def _format_mac(raw: bytes, length: int) -> str:
    return ":".join(f"{b:02x}" for b in raw[:length])


def _windows_neighbours() -> List[Dict[str, object]]:
    """`GetIpNetTable` from `iphlpapi.dll` — the API `arp.exe` calls.

    Two calls by design: the first returns `ERROR_INSUFFICIENT_BUFFER` (122) and
    writes the size it needs, the second fills the buffer. Asking for the size
    first is the documented contract, not a retry loop.
    """
    import ctypes
    from ctypes import wintypes

    class MIB_IPNETROW(ctypes.Structure):
        _fields_ = [
            ("dwIndex", wintypes.DWORD),
            ("dwPhysAddrLen", wintypes.DWORD),
            ("bPhysAddr", ctypes.c_ubyte * 8),
            ("dwAddr", wintypes.DWORD),
            ("dwType", wintypes.DWORD),
        ]

    iphlpapi = ctypes.WinDLL("iphlpapi.dll")
    size = wintypes.ULONG(0)
    # First call: size only. 122 is ERROR_INSUFFICIENT_BUFFER and is the
    # expected answer, not a failure.
    iphlpapi.GetIpNetTable(None, ctypes.byref(size), False)
    if size.value == 0:
        return []
    buf = ctypes.create_string_buffer(size.value)
    rc = iphlpapi.GetIpNetTable(buf, ctypes.byref(size), False)
    if rc != 0:
        raise OSError(rc, f"GetIpNetTable returned {rc}")

    count = struct.unpack_from("<I", buf, 0)[0]
    row_size = ctypes.sizeof(MIB_IPNETROW)
    out: List[Dict[str, object]] = []
    for i in range(count):
        row = MIB_IPNETROW.from_buffer_copy(buf, 4 + i * row_size)
        if row.dwPhysAddrLen == 0:
            # An entry with no hardware address is an incomplete lookup, not a
            # device. Reporting it would put phantom machines on the list.
            continue
        # `dwAddr` is network byte order already; `inet_ntoa` expects exactly
        # that, so no swap.
        address = socket.inet_ntoa(struct.pack("<I", row.dwAddr))
        mac = _format_mac(bytes(row.bPhysAddr), row.dwPhysAddrLen)
        out.append({
            "address": address,
            "mac": mac,
            "kind": _kind(address, mac),
            "type": _TYPES.get(row.dwType, f"type{row.dwType}"),
            "interface_index": int(row.dwIndex),
        })
    return out


def _linux_neighbours(path: str = "/proc/net/arp") -> List[Dict[str, object]]:
    """`/proc/net/arp`, which is a file rather than a command.

    Columns: IP address, HW type, Flags, HW address, Mask, Device. Flags `0x0`
    means the entry is incomplete — an address the kernel asked about and got no
    answer for — so those are dropped for the same reason Windows drops a
    zero-length hardware address.
    """
    out: List[Dict[str, object]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        address, _hwtype, flags, mac, _mask, device = parts[:6]
        if flags == "0x0":
            continue
        mac = mac.lower()
        if not _MAC_RE.match(mac):
            continue
        out.append({
            "address": address,
            "mac": mac,
            "kind": _kind(address, mac),
            # `0x4` is NUD_PERMANENT in the ARP flags; everything else the table
            # reports here is a learned entry.
            "type": "static" if flags == "0x4" else "dynamic",
            "interface": device,
        })
    return out


def neighbours() -> Dict[str, object]:
    """Every device this machine has exchanged traffic with recently.

    Never raises. A platform with no supported reader says so in `supported`
    rather than returning an empty list, because *"no neighbours"* and *"I cannot
    see neighbours here"* are completely different answers and an operator
    reading a bare `[]` would take the first for the second.
    """
    system = platform.system()
    try:
        if system == "Windows":
            rows = _windows_neighbours()
        elif system == "Linux":
            rows = _linux_neighbours()
        else:
            return {"supported": False, "platform": system, "neighbours": [],
                    "detail": f"no neighbour-table reader for {system} that does "
                              f"not need a subprocess"}
    except Exception as e:  # noqa: BLE001
        return {"supported": True, "platform": system, "neighbours": [],
                "detail": f"could not read the neighbour table ({type(e).__name__})"}

    rows.sort(key=_sort_key)
    return {"supported": True, "platform": system,
            "count": len(rows), "neighbours": rows,
            # Counted here so a caller does not have to know which MAC prefixes
            # mean "not a machine" to answer "how many devices".
            "devices": sum(1 for r in rows if r.get("kind") == "device")}


def _sort_key(row: Dict[str, object]):
    """Numeric address order, so `.9` comes before `.10`.

    Lexicographic order on dotted quads is the classic way a device list becomes
    hard to read at exactly the moment it gets long enough to matter.
    """
    try:
        return (0, int(ipaddress.ip_address(str(row.get("address", "")))))
    except ValueError:
        return (1, 0)


def filter_to(rows: List[Dict[str, object]], allows) -> List[Dict[str, object]]:
    """Keep only the neighbours the caller may be answered about.

    The table is the machine's; what may be *reported* is the allowlist's. Kept
    as a separate function taking the predicate, rather than reaching for the
    allowlist here, so the gate stays in one place (`P17-02`) and this module
    stays testable without one.
    """
    return [r for r in rows if allows(str(r.get("address", "")))]
