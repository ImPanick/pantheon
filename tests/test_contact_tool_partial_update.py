# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1911`. Updating a contact through the agent wiped every field it did not name.

`manage_contact` with `action=update` built the whole contact from the
arguments it was given, an empty name, no emails and no phones for every field
left out, and handed that to `contacts_routes._update_contact`, which rewrites
the contact. So "add a phone for Casey" left Casey with no name and no email,
"change Casey's email" renamed them to the address's local part and dropped their
phones, on the local address book and on the CardDAV server alike. An update
naming a uid that was not there added a new contact instead.

Now the update reads the stored contact first and changes only the fields the
call names. A uid that is not there is refused, and so is an update while the
address book cannot be read, because merging into an old copy writes old
values back.

Ported from upstream Odysseus 84aa9a91, whose cases these are; Pantheon's
address book is one per install, so upstream's owner fixtures are gone.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

import routes.contacts_routes as cc
from src import paced_http
from src.tools.contacts import do_manage_contact

CASEY = {"action": "add", "name": "Casey Example", "email": "casey@example.test",
         "phones": ["+1-202-555-0142"], "address": "42 Fixture Street"}

WREN = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:w1\r\nFN:Wren Ashby\r\n"
        "EMAIL:wren@example.test\r\nTEL:+1-202-555-0100\r\n"
        "ADR:;;9 Lark Lane;;;;\r\nEND:VCARD\r\n")


def _tool(args):
    return asyncio.run(do_manage_contact(json.dumps(args)))


@pytest.fixture
def local_book(monkeypatch, tmp_path):
    """The address book in the install's own contacts file, no CardDAV."""
    monkeypatch.setattr(cc, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cc, "LOCAL_CONTACTS_FILE", tmp_path / "contacts.json")
    monkeypatch.setattr(cc, "_get_carddav_config", lambda: {"url": "", "username": "", "password": ""})
    monkeypatch.setattr(cc, "_contact_cache", {"contacts": [], "fetched_at": None})
    assert _tool(CASEY)["exit_code"] == 0
    return cc._load_local_contacts


@pytest.fixture
def carddav(monkeypatch):
    """A configured CardDAV book holding Wren; every PUT is recorded."""
    monkeypatch.setattr(cc, "_get_carddav_config", lambda: {
        "url": "http://192.168.1.20:5232/joseph/contacts/", "username": "joseph",
        "password": "pw"})
    monkeypatch.setattr(cc, "_fetch_via_report", lambda cfg, auth: None)
    monkeypatch.setattr(cc, "_contact_cache", {"contacts": [], "fetched_at": None})
    server = {"status": 200, "puts": []}

    def get_sync(url, **kwargs):
        return SimpleNamespace(status_code=server["status"], text=WREN)

    def request_sync(method, url, **kwargs):
        server["puts"].append((method, url, kwargs.get("data", b"").decode("utf-8")))
        return SimpleNamespace(status_code=201, text="")

    monkeypatch.setattr(paced_http, "get_sync", get_sync)
    monkeypatch.setattr(paced_http, "request_sync", request_sync)
    return server


@pytest.mark.parametrize("patch,expected", [
    ({"name": "Casey Revised"}, {"name": "Casey Revised"}),
    ({"email": "revised@example.test"}, {"emails": ["revised@example.test"]}),
    ({"phones": ["+1-202-555-0168"]}, {"phones": ["+1-202-555-0168"]}),
    ({"address": "7 New Road"}, {"address": "7 New Road"}),
    ({"emails": []}, {"emails": []}),
    ({"phones": []}, {"phones": []}),
    # A call that fills every argument names only what it filled in.
    ({"phones": ["+1-202-555-0168"], "name": "", "email": "", "address": ""},
     {"phones": ["+1-202-555-0168"]}),
], ids=["name", "email", "phones", "address", "clear-emails", "clear-phones", "blanks"])
def test_an_update_changes_only_the_fields_it_names(local_book, patch, expected):
    [original] = local_book()

    result = _tool({"action": "update", "uid": original["uid"], **patch})

    assert result["exit_code"] == 0, result
    assert local_book() == [{**original, **expected}]


def test_an_update_of_a_contact_that_is_not_there_adds_nobody(local_book):
    before = local_book()

    result = _tool({"action": "update", "uid": "missing", "name": "Changed"})

    assert result == {"error": "Contact not found", "exit_code": 1}
    assert local_book() == before


def test_the_carddav_server_keeps_what_the_update_did_not_name(carddav):
    result = _tool({"action": "update", "uid": "w1", "phones": ["+1-202-555-0199"]})

    assert result["exit_code"] == 0, result
    [(method, url, vcard)] = carddav["puts"]
    assert method == "PUT" and url.endswith("/w1.vcf")
    assert "FN:Wren Ashby" in vcard
    assert "EMAIL;PREF=1:wren@example.test" in vcard
    assert "TEL:+1-202-555-0199" in vcard and "+1-202-555-0100" not in vcard
    assert "ADR:;;9 Lark Lane;;;;" in vcard


def test_an_update_while_the_address_book_cannot_be_read_changes_nothing(carddav):
    cc._fetch_contacts(True)                     # an earlier read, now stale
    carddav["status"] = 503
    cc._contact_cache["fetched_at"] = None

    result = _tool({"action": "update", "uid": "w1", "phones": ["+1-202-555-0199"]})

    assert result["exit_code"] == 1
    assert result["error"].startswith("The address book was not read: the CardDAV server "
                                      "answered HTTP 503")
    assert carddav["puts"] == []
