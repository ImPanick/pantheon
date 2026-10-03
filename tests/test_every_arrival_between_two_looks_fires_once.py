# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1151` (f-mail) — more than fifty arrivals between two looks at an inbox:
every one fires `email_received` once, or the log says how many did not.

The background inbox check (`B1137`) read the newest fifty messages
(`INBOX_CHECK_WINDOW`) and the producer, `_record_email_received_events`, fired
at most fifty per listing (`new_keys[:50]`), recording the rest as seen.
Measured on the tree before this row with the loopback IMAP server: a baseline,
then sixty messages, then one check — **fifty** events; the ten older arrivals
were never fired, by that check or any later one (newer mail keeps them out of
the newest page, and once seen they are not new).

Everything is the real code (`Law 20`): `_imap_connect` dials the loopback
IMAP server (`tests/helpers/imap_server.py`) with `imaplib`; the check is the
real pass started from the real `setup_email_routes()`; the producer decides
"new" over a real SQLite file (the `B1137` world). Only `fire_event` is
recorded instead of dispatched, and some cases shrink the page and the backlog
so a burst past them is a dozen messages rather than five hundred.
"""

import logging

import pytest

from tests.helpers.imap_server import ImapServer, message
from tests.test_mail_arriving_runs_its_workflow_with_nobody_looking import (  # noqa: F401
    ACCOUNT, OWNER, world,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def fired(monkeypatch):
    import src.event_bus as bus

    got = []
    monkeypatch.setattr(bus, "fire_event",
                        lambda name, owner=None, payload=None: got.append(payload["message_key"]))
    return got


def _deliver(srv, first, last):
    for i in range(first, last + 1):
        srv.box.deliver(message(frm=f"list-{i}@lists.example", subject=f"#{i}", mid=f"m{i}@x"))


def _start(world, monkeypatch):
    """The real routes; the passes are driven one by one here, and every page
    the check reads is counted."""
    pollers = world["pollers"]
    world["email_routes"].setup_email_routes()
    for t in (pollers._inbox_task, pollers._poller_task):
        t.cancel()
    real = pollers._INBOX_HOOKS["list"]
    reads = []

    def counting(folder, limit, offset, *rest):
        reads.append(offset)
        return real(folder, limit, offset, *rest)

    monkeypatch.setitem(pollers._INBOX_HOOKS, "list", counting)
    return pollers, reads


async def test_sixty_arrivals_between_two_checks_fire_sixty_events(world, fired, monkeypatch):
    with ImapServer() as srv:
        world["add_account"](srv.port)
        _deliver(srv, 1, 1)
        pollers, reads = _start(world, monkeypatch)
        assert await pollers._inbox_check_pass() == {ACCOUNT: "checked"}     # the baseline
        assert fired == []
        _deliver(srv, 2, 61)                                                  # sixty land
        assert await pollers._inbox_check_pass() == {ACCOUNT: "checked"}
        assert sorted(fired) == sorted(f"<m{i}@x>" for i in range(2, 62))
        assert len(fired) == 60, "each one once"
        fired.clear()
        assert await pollers._inbox_check_pass() == {ACCOUNT: "checked"}
        assert fired == [], "and never again"
    # The baseline read one page; the sixty, two (the second reached `m1`);
    # the third look, one — its newest page was all seen.
    assert reads == [0, 0, 50, 0]


async def test_reading_back_stops_at_seen_mail_and_older_mail_there_is_not_new(
        world, fired, monkeypatch):
    """The page that holds seen mail ends the reading, and on it an older
    message that was never in the window — under a seen UID — was there all
    along: recorded, not announced (`B1137`'s rule, across pages)."""
    monkeypatch.setattr(world["pollers"], "INBOX_CHECK_WINDOW", 3)
    with ImapServer() as srv:
        world["add_account"](srv.port)
        _deliver(srv, 1, 6)
        pollers, reads = _start(world, monkeypatch)
        await pollers._inbox_check_pass()                 # baseline: 4, 5, 6
        srv.box.expunge(5)                                # deleted in their own client
        _deliver(srv, 7, 11)                              # five arrive
        assert await pollers._inbox_check_pass() == {ACCOUNT: "checked"}
    # Pages: 11 10 9 | 8 7 6 — `m6` was seen, so the reading stops there;
    # 1 to 3 are never read and nothing below `m6` is announced.
    assert reads == [0, 0, 3]
    assert sorted(fired) == sorted(f"<m{i}@x>" for i in range(7, 12))


async def test_the_first_look_reads_one_page_whatever_the_mailbox_holds(world, fired, monkeypatch):
    with ImapServer() as srv:
        world["add_account"](srv.port)
        _deliver(srv, 1, 140)
        pollers, reads = _start(world, monkeypatch)
        await pollers._inbox_check_pass()
        await pollers._inbox_check_pass()
    assert reads == [0, 0] and fired == []


async def test_every_page_is_paced_through_the_outbound_limiter(world, fired, monkeypatch):
    import src.rate_limiter as rl

    acquired = []
    real = rl.outbound.acquire_async

    async def counting(host, *a, **k):
        acquired.append(host)
        return await real(host, *a, **k)

    monkeypatch.setattr(rl.outbound, "acquire_async", counting)
    with ImapServer() as srv:
        world["add_account"](srv.port)
        _deliver(srv, 1, 1)
        pollers, reads = _start(world, monkeypatch)
        await pollers._inbox_check_pass()
        _deliver(srv, 2, 120)
        acquired.clear()
        reads.clear()
        await pollers._inbox_check_pass()
    assert reads == [0, 50, 100]
    assert acquired == ["127.0.0.1"] * 3, "one paced acquire per page read"


async def test_past_the_backlog_what_was_not_announced_is_said(world, fired, monkeypatch, caplog):
    """A burst bigger than the backlog: no seen mail is reached, so nothing
    marks where the arrivals stop. The newest few are announced, the rest
    recorded — and the outcome and the log say how many."""
    pollers = world["pollers"]
    monkeypatch.setattr(pollers, "INBOX_CHECK_WINDOW", 3)
    monkeypatch.setattr(pollers, "INBOX_CHECK_BACKLOG", 6)
    monkeypatch.setattr(world["email_routes"], "EMAIL_RECEIVED_UNSURE_LIMIT", 2)
    caplog.set_level(logging.WARNING)
    with ImapServer() as srv:
        world["add_account"](srv.port)
        _deliver(srv, 1, 1)
        pollers, reads = _start(world, monkeypatch)
        await pollers._inbox_check_pass()
        _deliver(srv, 2, 11)                               # ten land
        outcome = await pollers._inbox_check_pass()
    assert reads == [0, 0, 3]
    assert outcome == {ACCOUNT: "checked; 4 new not announced"}
    assert fired == ["<m11@x>", "<m10@x>"]
    said = [r.getMessage() for r in caplog.records]
    assert any("more than 6 messages arrived since the last look" in m for m in said), said
    assert any("4 more new message(s) in INBOX" in m and "recorded without an event" in m
               for m in said), said


async def test_a_listing_that_shows_seen_mail_announces_every_arrival_above_it(
        world, fired, monkeypatch):
    """The Email window's listing goes through the same producer: with a
    hundred listed and the last seen mail among them, sixty arrivals are sixty
    events — `new_keys[:50]` held this door to fifty as well."""
    with ImapServer() as srv:
        world["add_account"](srv.port)
        _deliver(srv, 1, 5)
        routes = world["email_routes"]
        router = routes.setup_email_routes()
        pollers = world["pollers"]
        for t in (pollers._inbox_task, pollers._poller_task):
            t.cancel()
        listing = next(r.endpoint for r in router.routes
                       if r.path == "/api/email/list" and "GET" in r.methods)

        async def list_100(bust):
            res = await listing(folder="INBOX", limit=100, offset=0, filter="all", from_addr=None,
                                account_id=ACCOUNT, has_attachments=0, cached_only=0,
                                cache_bust=bust, owner=OWNER)
            assert not res.get("error"), res

        await list_100("1")                                  # the baseline
        _deliver(srv, 6, 65)
        await list_100("2")
    assert len(fired) == 60 and len(set(fired)) == 60
    assert set(fired) == {f"<m{i}@x>" for i in range(6, 66)}
