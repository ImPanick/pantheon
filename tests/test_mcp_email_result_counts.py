# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1981`. The agent's mail search and listing took the model's count as it came.

`search_emails` and `list_emails` (`mcp_servers/email_server.py`) cut the IMAP
answer with the `max_results` the model chose, exactly as it arrived. The MCP
wrapper checks each call against the tool's schema first
(`src/mcp_tool_server.py`), so a count sent as a string never gets in, but JSON
Schema counts `20.0` as an integer: the search then failed in every folder on
"slice indices must be integers" and answered *Search failed*, and a listing
answered the same error. `0` found nothing, `-1` fetched every match but one,
and `5000` asked for every match's headers, one round trip each, in each of the
three folders a search walks, against the 120-second ceiling on an MCP call.

Now the count is read once as a whole number. Anything that is not a number,
and anything below one, is the default of 20. A search takes at most 100 per
folder, the ceiling upstream chose and the bound Pantheon's own unsubscribe
scan already keeps. A listing has no ceiling: a larger listing works today,
and whether to cap it is the owner's call (`Law 1`).

From upstream Odysseus 84aa9a91, whose bounds these are, except that a count
below one is the default rather than one. The mailbox is a fake that holds
2,000 matches in every folder and records each header it is asked for; one
call goes through the real MCP wrapper and its schema check.
"""
from __future__ import annotations

import asyncio
from collections import Counter

import pytest

pytest.importorskip("mcp")

import mcp_servers.email_server as es  # noqa: E402

MATCHES = 2000
SEARCHED = ("INBOX", "Sent", "Archive")   # what a search walks by default


class FakeMailbox:
    """Every folder holds `MATCHES` messages and every search matches them all."""

    def __init__(self):
        self.folder = None
        self.fetched: list[tuple[str, bytes]] = []

    def select(self, folder, readonly=False):
        self.folder = folder.strip('"')
        return "OK", [str(MATCHES).encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b" ".join(str(n).encode() for n in range(1, MATCHES + 1))]
        if command == "FETCH":
            uid = args[0]
            self.fetched.append((self.folder, uid))
            header = (b"Subject: Invoice " + uid + b"\r\n"
                      b"From: Ana <ana@example.test>\r\n"
                      b"Date: Mon, 2 Nov 2026 09:00:00 +0000\r\n"
                      b"Message-ID: <" + uid + b"@example.test>\r\n\r\n")
            return "OK", [(b"1 (UID " + uid + b" RFC822.HEADER {%d}" % len(header), header), b")"]
        return "NO", []

    def logout(self):
        pass

    def per_folder(self) -> Counter:
        return Counter(folder for folder, _ in self.fetched)


@pytest.fixture()
def mailbox(monkeypatch, tmp_path):
    box = FakeMailbox()
    monkeypatch.setattr(es, "_imap_connect", lambda account=None: box)
    monkeypatch.setattr(es, "_fixture_list_emails", lambda *a, **k: None)
    monkeypatch.setattr(es, "_fixture_search_emails", lambda *a, **k: None)
    monkeypatch.setattr(es, "_get_cached_summaries", lambda: {})
    monkeypatch.setattr(es, "APP_DB", str(tmp_path / "no-accounts.db"))
    for key in es._OWNER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    es._ACCOUNT_CACHE.clear()
    yield box
    es._ACCOUNT_CACHE.clear()


def test_a_search_for_twenty_point_zero_finds_the_mail(mailbox):
    rows = es._search_emails("invoice", max_results=20.0)

    assert len(rows) == 20 * len(SEARCHED)
    assert mailbox.per_folder() == {folder: 20 for folder in SEARCHED}


@pytest.mark.parametrize("asked", [0, -1])
def test_a_search_for_fewer_than_one_takes_the_default(mailbox, asked):
    rows = es._search_emails("invoice", max_results=asked)

    assert mailbox.per_folder() == {folder: 20 for folder in SEARCHED}
    assert len(rows) == 20 * len(SEARCHED)


def test_a_search_for_thousands_reads_a_hundred_a_folder(mailbox):
    rows = es._search_emails("invoice", max_results=5000)

    assert mailbox.per_folder() == {folder: 100 for folder in SEARCHED}
    assert len(rows) == 100 * len(SEARCHED)


def test_a_search_with_no_count_still_reads_twenty_a_folder(mailbox):
    rows = es._search_emails("invoice")

    assert mailbox.per_folder() == {folder: 20 for folder in SEARCHED}
    assert [row["uid"] for row in rows[:2]] == [str(MATCHES), str(MATCHES - 1)]


def test_a_listing_of_zero_takes_the_default(mailbox):
    rows = es._list_emails(max_results=0)

    assert len(mailbox.fetched) == 20
    assert len(rows) == 20


def test_a_listing_for_twenty_point_zero_lists_the_mail(mailbox):
    rows = es._list_emails(max_results=20.0)

    assert len(rows) == 20


def test_a_listing_keeps_a_count_above_the_search_ceiling(mailbox):
    """No ceiling on a listing: 150 asked is 150 read (`Law 1`)."""
    rows = es._list_emails(max_results=150)

    assert len(mailbox.fetched) == 150
    assert len(rows) == 150


@pytest.mark.parametrize("asked", [0, 20.0])
def test_a_listing_across_two_mailboxes_takes_the_default(mailbox, monkeypatch, asked):
    monkeypatch.setattr(es, "_list_accounts_raw", lambda: [
        {"id": "home", "name": "Home", "imap_user": "me@home.test"},
        {"id": "work", "name": "Work", "imap_user": "me@work.test"},
    ])

    rows, errors = es._list_emails_across_accounts(max_results=asked)

    assert errors == []
    assert len(mailbox.fetched) == 40          # twenty from each mailbox
    assert len(rows) == 20


def test_twenty_point_zero_passes_the_schema_check_and_now_finds_mail(mailbox):
    """The whole way in: the real wrapper (`es.server`) checks the call against
    the tool's schema, lets `20.0` through as an integer, and the search runs."""
    from mcp import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams

    async def call():
        async with create_client_server_memory_streams() as (client, srv):
            serving = asyncio.ensure_future(
                es.server.run(srv[0], srv[1], es.server.create_initialization_options()))
            try:
                async with ClientSession(client[0], client[1]) as session:
                    await session.initialize()
                    return await session.call_tool(
                        "search_emails", {"query": "invoice", "max_results": 20.0})
            finally:
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)

    result = asyncio.run(call())
    text = result.content[0].text

    assert not result.is_error, text
    assert text.startswith('Found 60 email(s) matching "invoice"'), text
    assert mailbox.per_folder() == {folder: 20 for folder in SEARCHED}
