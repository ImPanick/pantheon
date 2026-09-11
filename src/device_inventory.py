# SPDX-License-Identifier: AGPL-3.0-or-later
"""Devices, remembered — because an ARP table is a snapshot and the question is not.

`P17-04`. *Organising* a network means knowing that `a4:83:e7:…` is the printer,
that it has been on `192.168.1.40` for three months, and that something new
appeared last Tuesday. A neighbour table answers none of those: it says what is
cached right now, and five minutes later it says something slightly different.

**MAC IS IDENTITY, IP IS AN ATTRIBUTE, AND THAT ORDERING IS THE WHOLE MODULE.**
A DHCP reshuffle changes every address on the network and changes no device. Key
the record by address and a lease renewal looks like the old device vanishing and
a new one arriving — which is the *opposite* of the one question this exists to
answer. So the address is history hung on the record, not the name of it.

**IT LIVES HERE AND NOT IN `netagent/`, deliberately.** The agent observes; this
remembers. Keeping it here holds the agent to its own first rule — small enough
to read in one sitting, standard library only, no state to corrupt — and puts
permanence where this product already keeps permanence. The agent stays a thing
you can restart without losing anything.

**NOTHING HERE REACHES A NETWORK.** Vendor names come from `netagent.oui`, which
reads a table that ships with us, and every answer carries where it came from.
`Law 16`, and a test asserts the import graph rather than the intent.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# How many addresses to remember per device. A machine that has been on a
# network for a year through a dozen leases does not need all twelve to answer
# "where is it and where was it"; keeping them unbounded turns a small file into
# a growing one for no extra answer.
MAX_ADDRESS_HISTORY = 12

# Below this, a device is "new" — the answer to *something appeared last
# Tuesday*. Seven days because that is the window in which a person still
# remembers plugging something in.
NEW_FOR_SECONDS = 7 * 24 * 60 * 60


def _store_path() -> str:
    from src.constants import DATA_DIR
    return os.path.join(DATA_DIR, "devices.json")


def _now() -> float:
    return time.time()


def _load() -> Dict[str, Any]:
    path = _store_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"devices": {}}
    except (OSError, ValueError) as e:
        # Refusing to answer is better than answering from nothing and then
        # OVERWRITING: a corrupt file that this module treats as empty would be
        # replaced by an empty one on the next observation, turning a recoverable
        # problem into a permanent one. Same rule as `MemoryStoreUnreadable`.
        raise DeviceStoreUnreadable(f"{path} could not be read: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("devices"), dict):
        raise DeviceStoreUnreadable(f"{path} is not a device store")
    return data


class DeviceStoreUnreadable(RuntimeError):
    """The store exists and cannot be read. Never silently treated as empty."""


def _save(data: Dict[str, Any]) -> None:
    from core.atomic_io import atomic_write_json
    atomic_write_json(_store_path(), data, indent=2, preserve_unreadable=True)


def _normalise(mac: str) -> Optional[str]:
    from netagent.oui import normalise
    return normalise(mac)


def _blank(mac: str, now: float) -> Dict[str, Any]:
    return {"mac": mac, "first_seen": now, "last_seen": now,
            "addresses": [], "name": "", "notes": "", "kind": "device"}


def _touch_address(record: Dict[str, Any], address: str, now: float) -> bool:
    """Record where a device is now. Returns True if this is a move."""
    history: List[Dict[str, Any]] = record.setdefault("addresses", [])
    for entry in history:
        if entry.get("address") == address:
            entry["last_seen"] = now
            moved = history[0].get("address") != address
            # Most recent first, so `current` is always `addresses[0]` and no
            # caller has to sort to answer "where is it".
            history.remove(entry)
            history.insert(0, entry)
            return moved
    history.insert(0, {"address": address, "first_seen": now, "last_seen": now})
    del history[MAX_ADDRESS_HISTORY:]
    return len(history) > 1


def observe(rows: List[Dict[str, Any]], *, now: Optional[float] = None) -> Dict[str, Any]:
    """Merge a neighbour snapshot into the inventory.

    Returns what *changed*, because that is the useful half: a caller wanting the
    whole list can ask for it, and a caller wanting to tell the operator
    something needs to know which three of forty devices are worth mentioning.
    """
    now = now if now is not None else _now()
    data = _load()
    devices: Dict[str, Any] = data["devices"]
    new: List[str] = []
    moved: List[Dict[str, str]] = []
    seen: List[str] = []

    for row in rows or []:
        mac = _normalise(str(row.get("mac", "")))
        if not mac:
            continue
        address = str(row.get("address", "")).strip()
        record = devices.get(mac)
        if record is None:
            record = _blank(mac, now)
            devices[mac] = record
            new.append(mac)
        record["last_seen"] = now
        if row.get("kind"):
            record["kind"] = str(row["kind"])
        if address:
            was = (record.get("addresses") or [{}])[0].get("address")
            if _touch_address(record, address, now) and was and was != address:
                moved.append({"mac": mac, "from": was, "to": address})
        seen.append(mac)

    data["last_observed"] = now
    _save(data)
    return {"seen": len(seen), "new": new, "moved": moved,
            "known": len(devices)}


def rename(mac: str, name: str) -> bool:
    """The operator's own name for a device. Survives a DHCP reshuffle by
    construction — it is hung on the MAC, and the MAC is the identity."""
    normalised = _normalise(mac)
    if not normalised:
        return False
    data = _load()
    record = data["devices"].get(normalised)
    if record is None:
        record = _blank(normalised, _now())
        # A device can be named before it is ever seen — somebody labelling a
        # printer from its sticker. The record exists from that moment and gets
        # its addresses when it first speaks.
        record["first_seen"] = 0.0
        record["last_seen"] = 0.0
        data["devices"][normalised] = record
    record["name"] = str(name or "").strip()[:120]
    _save(data)
    return True


def inventory(*, now: Optional[float] = None,
              vendor_table_path: Optional[str] = None) -> Dict[str, Any]:
    """Everything known, newest-seen first, with vendor and age filled in."""
    now = now if now is not None else _now()
    from netagent.oui import VendorTable
    table = VendorTable.load(vendor_table_path) if vendor_table_path else VendorTable()

    data = _load()
    out: List[Dict[str, Any]] = []
    for mac, record in data["devices"].items():
        addresses = record.get("addresses") or []
        first_seen = float(record.get("first_seen") or 0.0)
        entry = dict(record)
        entry["address"] = addresses[0]["address"] if addresses else None
        entry["previous_addresses"] = [a["address"] for a in addresses[1:]]
        entry["vendor"] = table.lookup(mac)
        # `first_seen == 0` means named-before-seen, which is not new and is also
        # not old — reporting it as either would be inventing an observation.
        #
        # The age is computed ONCE and both answers read it. Written as two
        # expressions, `is_new`'s own `bool(first_seen)` guard was provably
        # unable to change an answer — with a real epoch, `now - 0` is fifty
        # years and never inside the window — so a mutation deleting it survived
        # while `age_seconds` stayed correct. Sharing the value makes the guard
        # load-bearing through the half that is tested, which is `P13-14`'s
        # `cutoff` move rather than a deletion: here the guard says what the code
        # *means* and the arithmetic only agreed by accident.
        age = (now - first_seen) if first_seen else None
        entry["age_seconds"] = age
        entry["is_new"] = age is not None and age < NEW_FOR_SECONDS
        out.append(entry)

    out.sort(key=lambda e: float(e.get("last_seen") or 0.0), reverse=True)
    return {"devices": out, "count": len(out),
            "new": [e["mac"] for e in out if e["is_new"]],
            "last_observed": data.get("last_observed"),
            "vendor_table": table.stats()}
