# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-04`. An ARP table is a snapshot; the question never is.

*Organising* a network means knowing that `a4:83:e7:…` is the printer, that it
has been on `192.168.1.40` for three months, and that something new appeared last
Tuesday. A neighbour table answers none of those.

**MAC is identity, IP is an attribute, and that ordering is the whole module.** A
DHCP reshuffle changes every address and no device. Key the record by address and
a lease renewal reads as the old device vanishing and a new one arriving — the
exact opposite of the one question this exists to answer. The test below does a
full reshuffle and requires the answer to be "one new device", not three.
"""
import json
import os
import tempfile

import pytest

import src.device_inventory as inv
from netagent.oui import (
    PROVENANCE_IMPORTED,
    PROVENANCE_SEED,
    PROVENANCE_UNKNOWN,
    VendorTable,
    import_table,
    is_locally_administered,
    normalise,
    prefix_of,
)

T0 = 1_700_000_000.0
PRINTER = "a4:83:e7:11:22:33"
ROUTER = "6c:2b:59:8e:91:36"
PI = "b8:27:eb:aa:bb:cc"


@pytest.fixture(autouse=True)
def store(monkeypatch):
    tmp = tempfile.mkdtemp()
    import src.constants as C
    monkeypatch.setattr(C, "DATA_DIR", tmp, raising=False)
    monkeypatch.setattr(inv, "_store_path", lambda: os.path.join(tmp, "devices.json"))
    yield tmp


def _snapshot(pairs):
    return [{"address": a, "mac": m, "kind": "device"} for a, m in pairs]


# ── identity ────────────────────────────────────────────────────────────────

def test_a_dhcp_reshuffle_does_not_invent_devices():
    """The row in one test. Every address changes; one device is actually new."""
    inv.observe(_snapshot([("192.168.1.40", PRINTER), ("192.168.1.1", ROUTER)]), now=T0)
    result = inv.observe(_snapshot([
        ("192.168.1.77", PRINTER),
        ("192.168.1.2", ROUTER),
        ("192.168.1.90", PI),
    ]), now=T0 + 3600)

    assert result["new"] == [normalise(PI)], (
        "a lease renewal was reported as devices appearing and disappearing")
    assert {m["mac"] for m in result["moved"]} == {normalise(PRINTER), normalise(ROUTER)}
    assert result["known"] == 3


def test_a_name_survives_the_address_it_was_given_under():
    inv.observe(_snapshot([("192.168.1.40", PRINTER)]), now=T0)
    assert inv.rename(PRINTER, "the printer") is True
    inv.observe(_snapshot([("192.168.1.77", PRINTER)]), now=T0 + 3600)

    device = inv.inventory(now=T0 + 3600)["devices"][0]
    assert device["name"] == "the printer"
    assert device["address"] == "192.168.1.77"
    assert device["previous_addresses"] == ["192.168.1.40"]


@pytest.mark.parametrize("spelling", [
    "a4:83:e7:11:22:33", "A4-83-E7-11-22-33", "a483.e711.2233", "A483E7112233",
])
def test_the_same_device_written_differently_is_the_same_device(spelling):
    """A normaliser exists so the caller does not have to know which separator
    their source chose — and an inventory that thinks `AA:BB` and `aa-bb` are two
    machines is worse than no inventory."""
    inv.observe(_snapshot([("192.168.1.40", PRINTER)]), now=T0)
    result = inv.observe(_snapshot([("192.168.1.40", spelling)]), now=T0 + 60)
    assert result["new"] == []
    assert result["known"] == 1


def test_the_current_address_is_first_so_nobody_has_to_sort():
    inv.observe(_snapshot([("192.168.1.10", PRINTER)]), now=T0)
    inv.observe(_snapshot([("192.168.1.20", PRINTER)]), now=T0 + 10)
    inv.observe(_snapshot([("192.168.1.10", PRINTER)]), now=T0 + 20)
    device = inv.inventory(now=T0 + 20)["devices"][0]
    assert device["address"] == "192.168.1.10"
    assert device["previous_addresses"] == ["192.168.1.20"]


def test_address_history_is_bounded():
    """A machine that has been on a network for a year through a dozen leases
    does not need all twelve to answer "where is it and where was it"."""
    for i in range(inv.MAX_ADDRESS_HISTORY + 8):
        inv.observe(_snapshot([(f"192.168.1.{i + 1}", PRINTER)]), now=T0 + i)
    device = inv.inventory(now=T0 + 99)["devices"][0]
    assert len(device["addresses"]) == inv.MAX_ADDRESS_HISTORY


# ── "something appeared last Tuesday" ───────────────────────────────────────

def test_a_new_device_is_reported_as_new_and_stops_being_new():
    inv.observe(_snapshot([("192.168.1.90", PI)]), now=T0)
    assert inv.inventory(now=T0 + 60)["new"] == [normalise(PI)]
    assert inv.inventory(now=T0 + inv.NEW_FOR_SECONDS + 1)["new"] == []


def test_a_device_named_before_it_is_seen_is_neither_new_nor_old():
    """Somebody labelling a printer from its sticker. Reporting it as new would
    be inventing an observation; reporting an age would be inventing a date."""
    assert inv.rename(PRINTER, "the printer") is True
    device = inv.inventory(now=T0)["devices"][0]
    assert device["is_new"] is False
    assert device["age_seconds"] is None
    assert device["name"] == "the printer"


def test_a_mac_that_is_not_a_mac_is_not_a_device():
    result = inv.observe([{"address": "192.168.1.5", "mac": "not-a-mac"}], now=T0)
    assert result["known"] == 0


# ── the store ───────────────────────────────────────────────────────────────

def test_a_corrupt_store_refuses_rather_than_reading_as_empty(store):
    """Treating an unreadable file as empty and then saving over it turns a
    recoverable problem into a permanent one — the same rule as
    `MemoryStoreUnreadable`."""
    with open(os.path.join(store, "devices.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    with pytest.raises(inv.DeviceStoreUnreadable):
        inv.inventory(now=T0)
    with pytest.raises(inv.DeviceStoreUnreadable):
        inv.observe(_snapshot([("192.168.1.1", ROUTER)]), now=T0)


def test_a_missing_store_is_simply_empty():
    assert inv.inventory(now=T0)["count"] == 0


def test_what_is_written_is_json_a_person_could_read(store):
    inv.observe(_snapshot([("192.168.1.40", PRINTER)]), now=T0)
    raw = json.loads(open(os.path.join(store, "devices.json"), encoding="utf-8").read())
    assert normalise(PRINTER) in raw["devices"]
    assert raw["devices"][normalise(PRINTER)]["addresses"][0]["address"] == "192.168.1.40"


# ── vendors, and where the answer came from ─────────────────────────────────

def test_a_vendor_answer_always_says_where_it_came_from():
    """A table that is wrong for a device the operator owns is worse than one
    that says "I don't know", because a wrong vendor is acted upon and an absent
    one is looked up."""
    table = VendorTable()
    assert table.lookup("00:0c:29:11:22:33")["provenance"] == PROVENANCE_SEED
    assert table.lookup(ROUTER)["provenance"] == PROVENANCE_UNKNOWN
    assert table.lookup(ROUTER)["vendor"] is None
    assert "import" in table.lookup(ROUTER)["detail"]


def test_a_randomised_or_virtual_address_says_there_is_no_vendor():
    """Reporting "unknown vendor" for a locally administered address is true and
    misleading. The useful answer is that no manufacturer assigned it, so the
    operator stops looking."""
    assert is_locally_administered("02:42:ac:11:00:02") is True
    assert is_locally_administered(PRINTER) is False
    answer = VendorTable().lookup("02:42:ac:11:00:02")
    assert answer["locally_administered"] is True
    assert "no manufacturer" in answer["detail"]


def test_an_imported_table_answers_and_says_it_was_imported(tmp_path):
    csv_path = tmp_path / "oui.csv"
    csv_path.write_text(
        "Registry,Assignment,Organization Name,Organization Address\n"
        "MA-L,6C2B59,Acme Networks,1 Nowhere Road\n"
        "MA-L,BAD,Too Short,x\n"
        "MA-L,AABBCC,,no name\n", encoding="utf-8")
    out = tmp_path / "oui.json"
    report = import_table(csv_path, out)
    assert report["imported"] == 1 and report["skipped"] == 2

    table = VendorTable.load(out)
    answer = table.lookup(ROUTER)
    assert answer["vendor"] == "Acme Networks"
    assert answer["provenance"] == PROVENANCE_IMPORTED


def test_the_import_drops_the_postal_address(tmp_path):
    """IEEE publishes an organisation address. A postal address is not a thing
    this product should be storing about anybody."""
    csv_path = tmp_path / "oui.csv"
    csv_path.write_text(
        "Registry,Assignment,Organization Name,Organization Address\n"
        "MA-L,6C2B59,Acme Networks,17 Identifiable Lane Springfield\n", encoding="utf-8")
    out = tmp_path / "oui.json"
    import_table(csv_path, out)
    assert "Identifiable Lane" not in out.read_text(encoding="utf-8")


def test_a_corrupt_vendor_table_falls_back_to_the_seed(tmp_path):
    bad = tmp_path / "oui.json"
    bad.write_text("{not json", encoding="utf-8")
    table = VendorTable.load(bad)
    assert table.lookup("00:0c:29:11:22:33")["provenance"] == PROVENANCE_SEED


def test_every_seed_entry_can_actually_be_returned():
    """A table entry that cannot be reached is not documentation, it is a line
    the next reader has to work out is dead. The Docker bridge prefix was one:
    it is locally administered, so `lookup` answers before the seed is consulted.
    Found by running the lookup rather than by reading it."""
    from netagent.oui import _SEED
    table = VendorTable()
    unreachable = []
    for prefix, name in _SEED.items():
        answer = table.lookup(prefix + "000000")
        if answer["vendor"] != name:
            unreachable.append((prefix, name, answer))
    assert unreachable == [], f"seed entries that can never be returned: {unreachable}"


def test_nothing_in_the_lookup_path_can_open_a_socket():
    """`Law 16`, asserted against the import graph rather than the intent. "We do
    not call a lookup service" is a promise; "this module cannot" is a property."""
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "netagent" / "oui.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    networky = imported & {"socket", "http", "urllib", "httpx", "requests",
                           "ssl", "ftplib", "telnetlib", "asyncio"}
    assert networky == set(), f"the vendor lookup can reach a network: {networky}"


def test_the_inventory_does_not_reach_a_network_either():
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "src" / "device_inventory.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    networky = imported & {"socket", "http", "urllib", "httpx", "requests"}
    assert networky == set(), f"the inventory can reach a network: {networky}"


def test_the_inventory_carries_the_vendor_and_its_provenance():
    inv.observe(_snapshot([("192.168.1.90", PI)]), now=T0)
    device = inv.inventory(now=T0)["devices"][0]
    assert device["vendor"]["vendor"] == "Raspberry Pi Foundation"
    assert device["vendor"]["provenance"] == PROVENANCE_SEED


def test_the_list_is_newest_seen_first():
    inv.observe(_snapshot([("192.168.1.40", PRINTER)]), now=T0)
    inv.observe(_snapshot([("192.168.1.90", PI)]), now=T0 + 500)
    macs = [d["mac"] for d in inv.inventory(now=T0 + 500)["devices"]]
    assert macs[0] == normalise(PI)


def test_a_prefix_is_the_first_three_octets():
    assert prefix_of(PRINTER) == "a483e7"
    assert prefix_of("nonsense") is None


def test_an_operator_name_is_bounded():
    """Not a security boundary — a name goes in a JSON file and a table cell —
    but an unbounded string written from a form is how a small file becomes a
    large one and a table cell becomes a scrolling page."""
    inv.rename(PRINTER, "x" * 5000)
    device = inv.inventory(now=T0)["devices"][0]
    assert len(device["name"]) == 120


def test_the_age_and_the_newness_come_from_one_reading():
    """Written as two expressions they disagreed in a way no test could see: with
    a real epoch, `now - 0` is fifty years and never inside the newness window,
    so `is_new`'s guard was doing nothing while `age_seconds`' guard was doing
    all the work. One value, both answers."""
    assert inv.rename(PRINTER, "the printer") is True
    inv.observe(_snapshot([("192.168.1.90", PI)]), now=T0)
    by_mac = {d["mac"]: d for d in inv.inventory(now=T0 + 60)["devices"]}

    never_seen = by_mac[normalise(PRINTER)]
    assert never_seen["age_seconds"] is None
    assert never_seen["is_new"] is False, "an unobserved device cannot be new"

    seen = by_mac[normalise(PI)]
    assert seen["age_seconds"] == 60
    assert seen["is_new"] is True


def test_an_unobserved_device_is_never_new_whatever_the_clock_says():
    """**Why there is a 1970 timestamp in this test.**

    `inventory(now=...)` is a pure function of its argument, so any `now` is a
    legal input to it. With a present-day epoch, `now - 0` is fifty-odd years and
    lands outside the newness window by arithmetic — so the guard that *means*
    "an unobserved device is never new" and the arithmetic that *accidentally*
    agrees are indistinguishable, and a mutation removing the guard survived
    every test above.

    A `now` inside the first week of 1970 is the only input that separates them.
    It pins the intent rather than the coincidence: the answer must come from
    "we never saw this", not from "the epoch is large".
    """
    assert inv.rename(PRINTER, "the printer") is True
    early = inv.NEW_FOR_SECONDS / 2
    device = inv.inventory(now=early)["devices"][0]
    assert device["age_seconds"] is None
    assert device["is_new"] is False, (
        "newness is being decided by the size of the epoch rather than by "
        "whether the device was ever observed")
