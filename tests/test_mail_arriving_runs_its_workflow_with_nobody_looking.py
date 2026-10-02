# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1137` — "when mail arrives" runs with nobody looking at the inbox.

Measured by `integrate-e` (P22-00, three drives): the bank's mail sat in IMAP
with the workflow on, and `email_received` fired only on an uncached
`GET /api/email/list` — the Email window's Refresh. There was no poller; a
person who never opened Pantheon's inbox never got the workflow the gate
sentence describes.

Everything here is the real code (`Law 20`): the inbox is a loopback IMAP
server (`tests/helpers/imap_server.py`) that `_imap_connect` dials with
`imaplib`; the background check is the real loop, started by the real
`setup_email_routes()` → `_start_poller()`; what is new is decided by the real
producer, `_record_email_received_events`, over a real SQLite file; the event
goes through the real bus to the real scheduler and walker on a real SQLite
file (the walker harness: only the action steps' far ends record instead of
acting). The one seam is the length of a minute (`_SECONDS_PER_MINUTE`), so
the loop's five-minute interval passes in a second.
"""

import asyncio
import logging
import sqlite3
import time

import pytest

from tests.helpers.imap_server import ImapServer, message
from tests.helpers.walker_harness import (
    arrow, make_db, node, records_of, recording_scheduler, runs_of, seed_workflow, settle,
)

pytestmark = pytest.mark.asyncio

OWNER = "rowan"
ACCOUNT = "home-acct"
MINUTE = 0.2          # what "a minute" is to the loop in these tests


@pytest.fixture()
def world(monkeypatch, tmp_path):
    from core.database import EmailAccount
    import routes.email_helpers as email_helpers
    import routes.email_pollers as pollers
    import routes.email_routes as email_routes
    import src.constants as constants
    import src.rate_limiter as rl
    import src.settings as settings

    factory = make_db(monkeypatch, tmp_path / "pantheon.db")
    seen_db = tmp_path / "scheduled_emails.db"
    monkeypatch.setattr(email_helpers, "SCHEDULED_DB", seen_db)
    monkeypatch.setattr(email_routes, "SCHEDULED_DB", seen_db)
    email_helpers._init_scheduled_db()
    monkeypatch.setattr(settings, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    settings._invalidate_caches()
    monkeypatch.setattr(constants, "OUTBOUND_STATE_FILE", str(tmp_path / "outbound.json"))
    monkeypatch.setattr(rl, "outbound", rl.OutboundHostLimiter({}))
    monkeypatch.setattr(pollers, "_SECONDS_PER_MINUTE", MINUTE)
    monkeypatch.setattr(pollers, "_poller_task", None)
    monkeypatch.setattr(pollers, "_inbox_task", None)
    monkeypatch.setitem(pollers._INBOX_HOOKS, "list", None)
    monkeypatch.delenv("IMAP_HOST", raising=False)
    monkeypatch.delenv("PANTHEON_INPROCESS_POLLERS", raising=False)

    def add_account(port, *, account_id=ACCOUNT, owner=OWNER, default=True):
        db = factory()
        db.add(EmailAccount(id=account_id, owner=owner, name="Home", is_default=default, enabled=True,
                            imap_host="127.0.0.1", imap_port=port, imap_starttls=False,
                            imap_user=f"{owner}@example.test", imap_password="pw",
                            from_address=f"{owner}@example.test"))
        db.commit()
        db.close()

    def set_minutes(value):
        settings.save_settings({**settings.DEFAULT_SETTINGS, "email_inbox_check_minutes": value})
        settings._invalidate_caches()

    yield {"factory": factory, "seen_db": seen_db, "add_account": add_account,
           "set_minutes": set_minutes, "pollers": pollers, "email_routes": email_routes}
    for name in ("_inbox_task", "_poller_task"):
        task = getattr(pollers, name)
        if task is not None:
            task.cancel()
    settings._invalidate_caches()


def _bank_workflow(factory):
    seed_workflow(factory, [
        node("from-bank", "Is it from the bank?", "if", join="all", conditions=[
            {"left": "{{ steps.start.data.from_address }}", "op": "contains", "right": "bank"}]),
        node("post", "Post to #bank", "action", action="tidy_sessions"),
        node("ignore", "Leave it", "action", action="tidy_documents"),
    ], [arrow("start", "from-bank"), arrow("from-bank", "post", "then"),
        arrow("from-bank", "ignore", "otherwise")],
        name="Bank mail to chat", owner=OWNER, trigger_type="event", trigger_event="email_received",
        schedule=None, scheduled_time=None)


async def _until(predicate, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return time.monotonic()
        await asyncio.sleep(0.05)
    raise AssertionError(f"{what}: not within {timeout:.1f}s")


def _seen_count(seen_db):
    try:
        con = sqlite3.connect(seen_db)
        try:
            return con.execute("SELECT COUNT(*) FROM email_event_seen").fetchone()[0]
        finally:
            con.close()
    except sqlite3.OperationalError:
        return 0


async def test_mail_from_the_bank_runs_its_workflow_with_nobody_looking(world):
    """P22-00's promise, unattended: the workflow is on, nobody lists the
    inbox, the bank's mail lands — and the workflow runs, the `then` way,
    within the interval."""
    from src.event_bus import set_task_scheduler

    _bank_workflow(world["factory"])
    s = recording_scheduler()
    set_task_scheduler(s)
    try:
        with ImapServer() as srv:
            world["add_account"](srv.port)
            srv.box.deliver(message(frm="Old friend <friend@example.test>", subject="Hi", mid="old@x"))
            # The real start: the routes are set up inside a running loop, so
            # `_start_poller` launches the pollers there and then.
            world["email_routes"].setup_email_routes()
            assert world["pollers"]._inbox_task is not None
            interval = 5 * MINUTE                       # the default, five "minutes"
            await _until(lambda: _seen_count(world["seen_db"]) == 1, interval * 3,
                         "the first background look (the baseline)")
            assert runs_of(world["factory"], "wf") == [], "the baseline fires nothing"

            delivered = time.monotonic()
            srv.box.deliver(message(frm="Northwind Bank <statements@northwindbank.example.com>",
                                    subject="Your September statement is ready", mid="stmt-9@northwind"))
            ran = await _until(lambda: any(r["status"] == "success" for r in runs_of(world["factory"], "wf")),
                               interval * 3 + 5, "the workflow's run")
            await settle(s)
    finally:
        set_task_scheduler(None)
    # Within the interval (plus its jitter and the run itself), not "whenever
    # someone opens the Email window" — nobody did.
    assert ran - delivered <= interval * 1.1 + 3.0, f"{ran - delivered:.2f}s"
    [run] = runs_of(world["factory"], "wf")
    by = {r["node_id"]: r for r in records_of(world["factory"], run["id"])}
    assert by["from-bank"]["port"] == "then"
    assert set(by) == {"from-bank", "post"}, "the bank's mail went the bank's way, once"
    assert [c["name"] for c in s.calls] == ["Bank mail to chat · Post to #bank"]
    cause = run["steps"][0]["detail"]
    assert "email_received" in cause and "statements@northwindbank.example.com" in cause
    assert f"account={ACCOUNT}" in cause


async def test_a_restart_and_a_listing_fire_nothing_the_check_already_fired(world):
    """The seen keys are rows, not memory: a second process (a restart) and the
    Email window's listing both find the mail already seen."""
    fired = []
    import src.event_bus as bus
    pollers = world["pollers"]
    original = bus.fire_event
    bus.fire_event = lambda name, owner=None, payload=None: fired.append(payload["message_key"])
    try:
        with ImapServer() as srv:
            world["add_account"](srv.port)
            srv.box.deliver(message(frm="a@example.test", subject="Old", mid="old@x"))
            routes = world["email_routes"]
            router = routes.setup_email_routes()
            for t in (pollers._inbox_task, pollers._poller_task):
                t.cancel()                    # driven pass by pass here
            assert await pollers._inbox_check_pass() == {ACCOUNT: "checked"}
            srv.box.deliver(message(frm="b@bank.example", subject="New", mid="new@x"))
            assert await pollers._inbox_check_pass() == {ACCOUNT: "checked"}
            assert fired == ["<new@x>"]

            # "Restart": a new routes closure (a new pool, a new hook), the
            # same SQLite file.
            router = routes.setup_email_routes()
            assert await pollers._inbox_check_pass() == {ACCOUNT: "checked"}
            listing = next(r.endpoint for r in router.routes
                           if r.path == "/api/email/list" and "GET" in r.methods)
            res = await listing(folder="INBOX", limit=50, offset=0, filter="all", from_addr=None,
                                account_id=ACCOUNT, has_attachments=0, cached_only=0, cache_bust="1",
                                owner=OWNER)
            assert not res.get("error"), res
    finally:
        bus.fire_event = original
    assert fired == ["<new@x>"], "fired once, not again after the restart or by the listing"


async def test_older_mail_that_scrolls_into_view_is_not_new(world, monkeypatch):
    """Deleting the newest mail in your own client brings older mail up into
    the window the check reads. It was there all along: no event."""
    pollers = world["pollers"]
    monkeypatch.setattr(pollers, "INBOX_CHECK_WINDOW", 3)
    fired = []
    import src.event_bus as bus
    monkeypatch.setattr(bus, "fire_event",
                        lambda name, owner=None, payload=None: fired.append(payload["message_key"]))
    with ImapServer() as srv:
        world["add_account"](srv.port)
        for i in range(1, 6):
            srv.box.deliver(message(frm=f"p{i}@example.test", subject=f"#{i}", mid=f"m{i}@x"))
        world["email_routes"].setup_email_routes()
        for t in (pollers._inbox_task, pollers._poller_task):
            t.cancel()
        await pollers._inbox_check_pass()                    # baseline: 3, 4, 5
        srv.box.expunge(5)
        srv.box.expunge(4)                                   # the person deleted two
        await pollers._inbox_check_pass()                    # the window is 1, 2, 3 now
        assert fired == [], "1 and 2 were in the mailbox before; they did not arrive"
        srv.box.deliver(message(frm="statements@bank.example", subject="New", mid="m6@x"))
        await pollers._inbox_check_pass()
    assert fired == ["<m6@x>"]


async def test_the_check_waits_while_someone_is_using_pantheon(world, monkeypatch):
    """Background work waits for the foreground gate's quiet: while a visible
    tab's heartbeat is fresh, the mailbox is not even logged in to."""
    from src import interactive_gate as gate

    pollers = world["pollers"]
    monkeypatch.setenv("BACKGROUND_TASK_FOREGROUND_GATE", "1")
    monkeypatch.setenv("BACKGROUND_TASK_BROWSER_ACTIVE_SECONDS", "0.8")
    monkeypatch.setattr(gate, "_ACTIVE_REQUESTS", 0)
    monkeypatch.setattr(gate, "_LAST_ACTIVITY", 0.0)
    monkeypatch.setattr(gate, "_LAST_BROWSER_ACTIVITY", 0.0)
    monkeypatch.setattr(gate, "_has_active_chat_stream", lambda: False)   # no chat in this test
    with ImapServer() as srv:
        world["add_account"](srv.port)
        world["email_routes"].setup_email_routes()
        for t in (pollers._inbox_task, pollers._poller_task):
            t.cancel()
        await gate.mark_browser_activity()                   # someone is looking at Pantheon
        started = time.monotonic()
        check = asyncio.create_task(pollers._inbox_check_pass())
        await asyncio.sleep(0.4)
        assert not check.done() and srv.box.logins() == 0, "it went ahead while Pantheon was in use"
        assert await asyncio.wait_for(check, 5) == {ACCOUNT: "checked"}
        assert time.monotonic() - started >= 0.7
        assert srv.box.logins() == 1


async def test_nothing_is_checked_while_no_account_is_configured(world, caplog):
    """A fresh install: no account, no IMAP in the environment — the check
    connects to nothing and says nothing, pass after pass."""
    pollers = world["pollers"]
    world["email_routes"].setup_email_routes()
    assert pollers._inbox_task is not None
    caplog.set_level(logging.DEBUG, logger="routes.email_helpers")
    assert pollers._inbox_accounts() == []
    assert await pollers._inbox_check_pass() == {}
    await asyncio.sleep(5 * MINUTE * 2.5)                    # two passes of the real loop
    assert not [r for r in caplog.records if "not configured" in r.getMessage()]


async def test_an_admin_turns_it_off_with_zero(world):
    """`email_inbox_check_minutes` = 0: the loop runs, and looks at nothing —
    and the setting is read each time round, so 0 needs no restart."""
    pollers = world["pollers"]
    world["set_minutes"](0)
    assert pollers.inbox_check_minutes() == 0
    with ImapServer() as srv:
        world["add_account"](srv.port)
        world["email_routes"].setup_email_routes()
        await asyncio.sleep(MINUTE * 4)                       # four of the loop's off-minutes
        assert srv.box.logins() == 0
        world["set_minutes"](1)                               # an admin turns it on
        await _until(lambda: srv.box.logins() >= 1, MINUTE * 6, "the first check once turned on")


async def test_the_setting_is_held_to_its_range_on_both_doors(world):
    """Both doors that write a setting clamp through `int_setting_ranges`
    (`B931`), and the loop reads the same bounds."""
    from src.settings import DEFAULT_SETTINGS, clamp_int_setting, int_setting_ranges

    assert DEFAULT_SETTINGS["email_inbox_check_minutes"] == 5
    assert int_setting_ranges()["email_inbox_check_minutes"] == (0, 1440)
    assert clamp_int_setting("email_inbox_check_minutes", -3) == 0
    assert clamp_int_setting("email_inbox_check_minutes", 99999) == 1440
    world["set_minutes"](99999)
    assert world["pollers"].inbox_check_minutes() == 1440
    world["set_minutes"](-1)
    assert world["pollers"].inbox_check_minutes() == 0


async def test_a_mailbox_that_refuses_logins_is_backed_off(world):
    """A stale password is a failing login every pass — what providers lock
    accounts for. The first failure starts `penalise`'s ladder under the
    account's own key, and the next pass does not knock."""
    import src.rate_limiter as rl

    pollers = world["pollers"]
    with ImapServer() as srv:
        world["add_account"](srv.port)
        world["email_routes"].setup_email_routes()
        for t in (pollers._inbox_task, pollers._poller_task):
            t.cancel()
        srv.box.refuse_logins = True
        first = await pollers._inbox_check_pass()
        assert first[ACCOUNT].startswith("failed; backing off for "), first
        tried = srv.box.logins()
        assert tried >= 1
        second = await pollers._inbox_check_pass()
        assert second[ACCOUNT].startswith("backing off for "), second
        assert srv.box.logins() == tried, "it knocked again while backing off"
        assert rl.outbound.blocked_for(f"imap-inbox:{ACCOUNT}") >= 120.0
        assert rl.outbound.blocked_for("imap-inbox:another-account") == 0


async def test_each_account_is_checked_as_its_owner(world):
    """Two people, two mailboxes: each one's mail is that person's event and
    wakes only their tasks; an account nobody owns yet is not guessed at."""
    import src.event_bus as bus
    from core.database import EmailAccount

    pollers = world["pollers"]
    fired = []
    original = bus.fire_event
    bus.fire_event = lambda name, owner=None, payload=None: fired.append((owner, payload["account"],
                                                                          payload["message_key"]))
    try:
        with ImapServer() as rowan_srv, ImapServer() as sam_srv, ImapServer() as orphan_srv:
            world["add_account"](rowan_srv.port)
            world["add_account"](sam_srv.port, account_id="sam-acct", owner="sam")
            db = world["factory"]()
            db.add(EmailAccount(id="orphan-acct", owner=None, name="Old", is_default=False, enabled=True,
                                imap_host="127.0.0.1", imap_port=orphan_srv.port, imap_starttls=False,
                                imap_user="x", imap_password="pw"))
            db.commit()
            db.close()
            world["email_routes"].setup_email_routes()
            for t in (pollers._inbox_task, pollers._poller_task):
                t.cancel()
            for srv, who in ((rowan_srv, "rowan"), (sam_srv, "sam"), (orphan_srv, "nobody")):
                srv.box.deliver(message(frm="x@example.test", subject="Old", mid=f"old-{who}@x"))
            await pollers._inbox_check_pass()
            for srv, who in ((rowan_srv, "rowan"), (sam_srv, "sam"), (orphan_srv, "nobody")):
                srv.box.deliver(message(frm="x@example.test", subject="New", mid=f"new-{who}@x"))
            outcome = await pollers._inbox_check_pass()
            assert orphan_srv.box.logins() == 0
    finally:
        bus.fire_event = original
    assert outcome == {ACCOUNT: "checked", "sam-acct": "checked"}
    assert sorted(fired) == [("rowan", ACCOUNT, "<new-rowan@x>"), ("sam", "sam-acct", "<new-sam@x>")]


async def test_starting_the_pollers_twice_starts_one_check(world):
    """`_start_poller` is called at import and again from the app's startup:
    with a loop running, the first call starts the check and the second
    leaves it as it is."""
    pollers = world["pollers"]
    pollers._start_poller()
    first = pollers._inbox_task
    assert first is not None and not first.done()
    pollers._start_poller()
    assert pollers._inbox_task is first


def test_the_app_starts_the_email_pollers_where_a_loop_is_running():
    """`launcher.py` imports the app before uvicorn's loop exists, so the
    import-time start is deferred to the first inbox listing — the app's own
    startup starts them. Scoped to `_startup_event` (`Law 20` § 2): entering
    the whole lifespan here would start every other service with it."""
    import ast
    import inspect

    import app as app_module

    tree = ast.parse(inspect.getsource(app_module._startup_event))
    imported = {(n.module, a.name, a.asname) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                for a in n.names}
    assert ("routes.email_pollers", "_start_poller", "_start_email_pollers") in imported
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_start_email_pollers"]
    assert len(calls) == 1
