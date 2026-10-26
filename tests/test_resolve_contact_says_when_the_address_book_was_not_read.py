# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1534` — `resolve_contact` said nothing when the CardDAV server could not be read.

`contacts_routes._fetch_contacts` answered a non-200, or no answer at all, with
the last copy it had read (often `[]`) and a log line, so the tool could not
tell *not read* from *empty*: with the address book's server down and nobody
called Wren in the mail history, the assistant was told *"No contacts found
matching 'Wren'"* — `B1528`'s shape on the address book. Now the fetch says
why it did not read the server (an out-parameter, so every caller that takes
the list is unchanged) and the tool says it with the answer.

Driven through the real `_fetch_contacts` and `do_resolve_contact`; only the
CardDAV server (an HTTP status, or a refused connection) and the mail-history
route (answering, with nobody by that name) are replaced.
"""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import routes.contacts_routes as cc
from src import paced_http
from src.tools.contacts import do_manage_contact, do_resolve_contact

WREN = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:w1\r\nFN:Wren Ashby\r\n"
        "EMAIL:wren@example.test\r\nEND:VCARD\r\n")


@pytest.fixture
def carddav(monkeypatch):
    """A configured address book whose server answers what the test says."""
    monkeypatch.setattr(cc, "_get_carddav_config", lambda: {
        "url": "http://192.168.1.20:5232/joseph/contacts/", "username": "joseph",
        "password": "pw"})
    monkeypatch.setattr(cc, "_carddav_configured", lambda cfg=None: True)
    monkeypatch.setattr(cc, "_fetch_via_report", lambda cfg, auth: None)
    monkeypatch.setattr(cc, "_contact_cache", {"contacts": [], "fetched_at": None})
    answer = {}

    def get_sync(url, **kwargs):
        if answer.get("refuse"):
            raise httpx.ConnectError("Connection refused")
        return SimpleNamespace(status_code=answer.get("status", 200), text=answer.get("text", ""))

    monkeypatch.setattr(paced_http, "get_sync", get_sync)
    return answer


@pytest.fixture
def mail_history(monkeypatch):
    """The mail-history route answers, and knows nobody by the name."""
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"contacts": []})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def _resolve(name="Wren"):
    return asyncio.run(do_resolve_contact(json.dumps({"name": name}), owner="joseph"))


@pytest.mark.parametrize("answer,why", [
    ({"status": 503}, "the CardDAV server answered HTTP 503"),
    ({"refuse": True}, "the CardDAV server could not be reached (ConnectError)"),
], ids=["http-503", "refused"])
def test_the_fetch_says_why_it_did_not_read_the_server(carddav, answer, why):
    carddav.update(answer)
    report = {}

    assert cc._fetch_contacts(True, report) == []
    assert report == {"unread": why, "stale": False}


def test_a_read_says_it_read(carddav):
    carddav.update(text=WREN)
    report = {}

    rows = cc._fetch_contacts(True, report)

    assert [r["name"] for r in rows] == ["Wren Ashby"]
    assert report == {"unread": None, "stale": False}
    # A cache hit is a read less than a minute old.
    cc._fetch_contacts(False, report)
    assert report["unread"] is None


@pytest.mark.parametrize("answer", [{"status": 503}, {"refuse": True}], ids=["http-503", "refused"])
def test_with_carddav_down_the_reply_says_the_address_book_was_not_read(
        carddav, mail_history, answer):
    carddav.update(answer)

    out = _resolve()["output"]

    assert "The address book was not read: the CardDAV server" in out
    assert "So this is not an answer that nobody by that name exists" in out


def test_a_stale_copy_is_searched_and_said_to_be_stale(carddav, mail_history):
    carddav.update(text=WREN)
    cc._fetch_contacts(True)
    carddav.update(status=503)
    cc._contact_cache["fetched_at"] = None     # past the minute

    out = _resolve()["output"]

    assert "Wren Ashby <wren@example.test> (contacts)" in out
    assert ("The address book was not read: the CardDAV server answered HTTP 503; "
            "only the copy from its last read was searched.") in out


def test_a_read_address_book_with_nobody_by_that_name_is_still_a_plain_no(carddav, mail_history):
    carddav.update(text=WREN)

    assert _resolve("Ozymandias")["output"] == "No contacts found matching 'Ozymandias'."


def test_listing_an_unread_address_book_is_not_no_contacts(carddav):
    carddav.update(status=503)

    result = asyncio.run(do_manage_contact(json.dumps({"action": "list"}), owner="joseph"))

    assert result == {"error": "The address book was not read: the CardDAV server "
                               "answered HTTP 503.", "exit_code": 1}
