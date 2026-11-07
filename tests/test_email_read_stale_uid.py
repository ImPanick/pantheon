# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1966`. A message gone from the server reads as gone, not as a blank one.

A UID FETCH for a UID the server no longer has (moved, deleted or expunged
from another client since the list was read) answers OK with no message data:
`('OK', [None])`. The reader's default path skipped every item that was not a
message part and built an ordinary answer out of nothing, with no sender,
subject or body. That blank went into the 30-minute read cache and into the
preview cache, which keeps an entry until its version changes, so every reopen
showed it again, and a foreground open marked the stale UID seen on the way.
The full read and the attachment list indexed `[None][0][1]` and answered
"Mail operation failed".

All three now say the message was moved or deleted, before anything is parsed,
marked or cached, as the agent's own reader (`mcp_servers/email_server.py`)
already did. From upstream Odysseus #6425 (245769e7).
"""
from contextlib import contextmanager

import pytest


def _route_endpoint(router, path: str, method: str):
    method = method.upper()
    for route in router.routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class _GoneFromTheServer:
    """What imaplib hands back for a UID FETCH that matches no message."""

    def __init__(self):
        self.commands = []

    def select(self, mailbox, readonly=False):
        return "OK", [b"1"]

    def uid(self, command, uid, *args):
        self.commands.append((command, uid, *args))
        if command == "FETCH":
            return "OK", [None]
        return "OK", []


@pytest.fixture
def mailbox(monkeypatch, tmp_path):
    import routes.email_helpers as email_helpers
    import routes.email_routes as email_routes

    db_path = tmp_path / "email.db"
    monkeypatch.setattr(email_helpers, "SCHEDULED_DB", db_path)
    monkeypatch.setattr(email_routes, "SCHEDULED_DB", db_path)
    email_helpers._init_scheduled_db()

    connections, preview_puts = [], []

    @contextmanager
    def fake_imap(account_id=None, owner=""):
        conn = _GoneFromTheServer()
        connections.append(conn)
        yield conn

    monkeypatch.setattr(email_routes, "_start_poller", lambda: None)
    monkeypatch.setattr(email_routes, "_imap", fake_imap)
    monkeypatch.setattr(email_routes, "_email_preview_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(email_routes, "_email_preview_cache_put",
                        lambda *args, **_k: preview_puts.append(args))
    monkeypatch.setattr(email_routes, "_email_attachment_meta_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(email_routes, "_email_attachment_meta_cache_put", lambda *_a, **_k: None)
    monkeypatch.setattr(email_routes, "_email_index_update_flags", lambda *_a, **_k: None)

    router = email_routes.setup_email_routes()

    class Box:
        pass

    box = Box()
    box.read = _route_endpoint(router, "/api/email/read/{uid}", "GET")
    box.attachments = _route_endpoint(router, "/api/email/attachments/{uid}", "GET")
    box.connections = connections
    box.preview_puts = preview_puts
    return box


def _commands(box):
    return [c[0] for conn in box.connections for c in conn.commands]


@pytest.mark.asyncio
async def test_opening_a_message_gone_from_the_server_says_so_and_marks_nothing_seen(mailbox):
    result = await mailbox.read("4242", folder="INBOX", account_id="acct-a",
                                mark_seen=True, full=False, owner="alice")

    assert result.get("not_found") is True
    assert "moved or deleted" in result["error"]
    assert "subject" not in result and "body" not in result
    assert _commands(mailbox) == ["FETCH"], "no \\Seen STORE for a message that is not there"


@pytest.mark.asyncio
async def test_a_message_gone_from_the_server_is_not_cached_as_a_blank_one(mailbox):
    for _ in range(2):
        result = await mailbox.read("4242", folder="INBOX", account_id="acct-a",
                                    mark_seen=False, full=False, owner="alice")
        assert result.get("not_found") is True

    assert _commands(mailbox) == ["FETCH", "FETCH"], "the second open asks the server again"
    assert mailbox.preview_puts == []


@pytest.mark.asyncio
async def test_the_full_read_of_a_message_gone_from_the_server_says_so(mailbox):
    result = await mailbox.read("4242", folder="INBOX", account_id="acct-a",
                                mark_seen=False, full=True, owner="alice")

    assert result.get("not_found") is True
    assert "moved or deleted" in result["error"]


def test_the_attachment_list_of_a_message_gone_from_the_server_says_so(mailbox):
    result = mailbox.attachments("4242", folder="INBOX", account_id="acct-a", owner="alice")

    assert result == {"attachments": [], "error": "Email not found"}
