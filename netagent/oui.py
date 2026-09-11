# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which manufacturer a MAC address belongs to, from a table that ships with us.

`P17-04`. The row is explicit: *"OUI vendor lookup from a vendored prefix table
and not a web service (`Law 16`)"*. So there is no lookup service, no API key and
no runtime fetch — a test asserts this module imports nothing that can open a
socket, which is a stronger statement than *"we do not call one"*.

**THE SEED IS SMALL AND SAYS SO, WHICH IS THE WHOLE DESIGN.**

The IEEE registry is about 35,000 assignments. Shipping a guessed subset and
answering confidently from it would be the failure this project has a law about:
a table that is wrong for a device the operator owns is worse than one that says
*"I don't know"*, because a wrong vendor is acted upon and an absent one is
looked up. So:

  * every answer carries `provenance` — `seed` for what ships here, `imported`
    for a table the operator loaded from IEEE themselves, and `unknown` when the
    prefix is in neither;
  * `unknown` is a normal answer and the caller renders it as one;
  * the seed holds only assignments stable enough to state plainly, and each
    line carries the name as IEEE registers it rather than a marketing name.

`import_table()` is how an operator gets the other 34,900: they download
`oui.csv` from IEEE, point this at it, and the answers become `imported`. That
is a deliberate act by a person, which is precisely the shape `Law 16` asks for —
*"unless the user (or sysadmin) explicitly links it"*.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, Optional

_MAC_SEP = re.compile(r"[^0-9a-f]")

PROVENANCE_SEED = "seed"
PROVENANCE_IMPORTED = "imported"
PROVENANCE_UNKNOWN = "unknown"

# Locally administered addresses have a set second-least-significant bit in the
# first octet. They are not registered to anybody and never will be — a
# randomised phone MAC, a VM, a container. Reporting "unknown vendor" for one is
# technically true and actively misleading: the honest answer is that this
# address was not assigned by a manufacturer at all.
_LOCALLY_ADMINISTERED_BIT = 0b10

# The seed. Deliberately short. Each of these is an IEEE MA-L assignment stable
# enough to state without a citation; everything else waits for `import_table`.
_SEED: Dict[str, str] = {
    "000c29": "VMware, Inc.",
    "005056": "VMware, Inc.",
    "080027": "PCS Systemtechnik GmbH (VirtualBox)",
    "00155d": "Microsoft Corporation (Hyper-V)",
    # TWO ENTRIES WERE REMOVED FROM HERE and the reason is worth keeping.
    # `0242ac` (the Docker bridge) and `525400` (QEMU/KVM) are both **locally
    # administered** — bit 1 of the first octet is set — so `lookup` answers
    # before it ever consults the seed, and neither line could ever have been
    # returned. A table entry that cannot be reached is not documentation, it is
    # a line the next reader has to work out is dead.
    #
    # The first was found by running the lookup; the second by the test that was
    # written after the first, which is the argument for having written it.
    # `test_every_seed_entry_can_actually_be_returned` keeps the third from
    # landing.
    "b827eb": "Raspberry Pi Foundation",
    "dca632": "Raspberry Pi Trading Ltd",
    "e45f01": "Raspberry Pi Trading Ltd",
}


def normalise(mac: str) -> Optional[str]:
    """Twelve lowercase hex characters, or None.

    Accepts every separator a table might use — colons, hyphens, dots, none —
    because the point of a normaliser is that the caller does not have to know
    which one their source chose.
    """
    cleaned = _MAC_SEP.sub("", str(mac or "").lower())
    return cleaned if len(cleaned) == 12 else None


def prefix_of(mac: str) -> Optional[str]:
    normalised = normalise(mac)
    return normalised[:6] if normalised else None


def is_locally_administered(mac: str) -> bool:
    """Was this address assigned by a manufacturer at all?

    A randomised phone MAC, a VM, a container bridge. Reporting "unknown vendor"
    for one is true and misleading; the useful answer is that there is no vendor
    to find, so an operator stops looking.
    """
    normalised = normalise(mac)
    if not normalised:
        return False
    return bool(int(normalised[:2], 16) & _LOCALLY_ADMINISTERED_BIT)


class VendorTable:
    """Prefix -> manufacturer, with where the answer came from."""

    __slots__ = ("_imported", "_source")

    def __init__(self, imported: Optional[Dict[str, str]] = None,
                 source: str = "") -> None:
        self._imported = dict(imported or {})
        self._source = source

    @classmethod
    def load(cls, path: Optional[Path]) -> "VendorTable":
        """An imported table if one is there, otherwise just the seed."""
        if not path:
            return cls()
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt table is not a reason to refuse to answer at all: the
            # seed still works and the caller still gets `provenance`, which is
            # how they can tell the difference.
            return cls()
        entries = data.get("prefixes") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return cls()
        return cls(entries, source=str(path))

    def lookup(self, mac: str) -> Dict[str, object]:
        prefix = prefix_of(mac)
        if not prefix:
            return {"vendor": None, "provenance": PROVENANCE_UNKNOWN,
                    "detail": "not a MAC address"}
        if is_locally_administered(mac):
            return {"vendor": None, "prefix": prefix,
                    "provenance": PROVENANCE_UNKNOWN,
                    "locally_administered": True,
                    "detail": "locally administered — no manufacturer assigned this"}
        if prefix in self._imported:
            return {"vendor": self._imported[prefix], "prefix": prefix,
                    "provenance": PROVENANCE_IMPORTED}
        if prefix in _SEED:
            return {"vendor": _SEED[prefix], "prefix": prefix,
                    "provenance": PROVENANCE_SEED}
        return {"vendor": None, "prefix": prefix, "provenance": PROVENANCE_UNKNOWN,
                "detail": "not in the shipped table; import IEEE's oui.csv to widen it"}

    def stats(self) -> Dict[str, object]:
        return {"seed": len(_SEED), "imported": len(self._imported),
                "source": self._source}


def import_table(csv_path: Path, out_path: Path) -> Dict[str, object]:
    """Turn IEEE's `oui.csv` into the table this module reads.

    Run by the operator, once, on a file they downloaded. The columns IEEE
    publishes are `Registry, Assignment, Organization Name, Organization
    Address`; only the first three matter and the address is dropped, because a
    postal address is not a thing this product should be storing about anybody.
    """
    csv_path, out_path = Path(csv_path), Path(out_path)
    prefixes: Dict[str, str] = {}
    skipped = 0
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            assignment = _MAC_SEP.sub("", str(row.get("Assignment", "")).lower())
            name = str(row.get("Organization Name", "")).strip()
            if len(assignment) != 6 or not name:
                skipped += 1
                continue
            prefixes[assignment] = name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "provenance": PROVENANCE_IMPORTED,
        "source": csv_path.name,
        "prefixes": prefixes,
    }, indent=0, sort_keys=True), encoding="utf-8")
    return {"imported": len(prefixes), "skipped": skipped, "path": str(out_path)}
