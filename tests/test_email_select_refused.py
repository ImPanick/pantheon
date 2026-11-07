# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2011`. A folder the mail server refused to open was reported as a broken
message.

Opening a message, Move to Trash and Delete Permanently each SELECT the folder
first and never read what the server answered. imaplib raises only when a
read-write SELECT is answered `OK [READ-ONLY]`; a plain NO (a folder renamed or
deleted in another client, one the account may not open) comes back as a
status and leaves the connection in no mailbox at all. The next command then
fails, so the reader said "Mail operation failed" and both deletes said "Email
not found" for a folder nobody had opened. And a read-write SELECT refused with
NO never reached the read-only retry that the raise does, so a folder that
opens read-only stayed unreadable.

Now the reader retries read-only on a NO as it does on the raise, and says
"Could not open email folder: <name>" when the folder opens neither way; both
deletes say "Could not open email folder" and send nothing. From upstream
Odysseus 84aa9a91; its role-resolved retry is not taken, because a UID belongs
to one folder and the same number in another names a different message.

Driven (`Law 20`): the real route handlers over a connection that answers as
imaplib does, state included.
"""
import imaplib
from contextlib import contextmanager

import pytest

from tests.test_email_read_mark_seen import RAW_EMAIL, _route_endpoint


class RefusingImap:
    """Answers SELECT and EXAMINE as a case scripts them, and keeps imaplib's
    state: after a NO the connection is in AUTH, where a UID command or EXPUNGE
    raises imaplib's own error, and nothing is selected."""

    def __init__(self, select_status="NO", examine_status="OK"):
        self.select_status = select_status
        self.examine_status = examine_status
        self.state = "AUTH"
        self.selects = []
        self.commands = []

    def select(self, mailbox, readonly=False):
        self.selects.append((mailbox, readonly))
        status = self.examine_status if readonly else self.select_status
        self.state = "SELECTED" if status == "OK" else "AUTH"
        return status, [b"1" if status == "OK" else b"[NONEXISTENT] Unknown Mailbox"]

    def _in_a_mailbox(self, command):
        if self.state != "SELECTED":
            raise imaplib.IMAP4.error(
                f"command {command} illegal in state AUTH, only allowed in states SELECTED")

    def list(self, *_args):
        return "OK", []

    def uid(self, command, *args):
        self.commands.append((command, *args))
        self._in_a_mailbox(command)
        if command == "FETCH" and "(UID)" in args:
            return "OK", [b"1 (UID 42)"]
        if command == "FETCH":
            header, body = RAW_EMAIL.split(b"\r\n\r\n", 1)
            return "OK", [
                (b"1 (UID 42 BODY[HEADER])", header + b"\r\n\r\n"),
                (b"1 (UID 42 BODY[TEXT]<0>)", body),
            ]
        return "OK", []

    def expunge(self):
        self.commands.append(("EXPUNGE",))
        self._in_a_mailbox("EXPUNGE")
        return "OK", []


@pytest.fixture
def mail(monkeypatch, tmp_path):
    import routes.email_helpers as email_helpers
    import routes.email_routes as email_routes

    db_path = tmp_path / "email.db"
    monkeypatch.setattr(email_helpers, "SCHEDULED_DB", db_path)
    monkeypatch.setattr(email_routes, "SCHEDULED_DB", db_path)
    email_helpers._init_scheduled_db()

    box = {"select": "NO", "examine": "OK", "connections": [], "index_deletes": []}

    @contextmanager
    def fake_imap(account_id=None, owner=""):
        conn = RefusingImap(box["select"], box["examine"])
        box["connections"].append(conn)
        yield conn

    monkeypatch.setattr(email_routes, "_start_poller", lambda: None)
    monkeypatch.setattr(email_routes, "_imap", fake_imap)
    for name in ("_email_preview_cache_get", "_email_attachment_meta_cache_get"):
        monkeypatch.setattr(email_routes, name, lambda *_a, **_k: None)
    for name in ("_email_preview_cache_put", "_email_attachment_meta_cache_put",
                 "_email_index_update_flags"):
        monkeypatch.setattr(email_routes, name, lambda *_a, **_k: None)
    monkeypatch.setattr(email_routes, "_email_index_delete",
                        lambda *args, **_k: box["index_deletes"].append(args))
    box["router"] = email_routes.setup_email_routes()
    return box


async def _read(mail, *, mark_seen, folder="Archive"):
    read_email = _route_endpoint(mail["router"], "/api/email/read/{uid}", "GET")
    return await read_email("42", folder=folder, account_id="acct-a",
                            mark_seen=mark_seen, full=False, owner="alice")


async def test_a_folder_that_refuses_a_read_write_select_is_read_read_only(mail):
    mail["select"], mail["examine"] = "NO", "OK"
    result = await _read(mail, mark_seen=True)

    assert "error" not in result
    assert result["uid"] == "42"
    assert result["mark_seen_failed"] is True
    conn = mail["connections"][0]
    assert [readonly for _box, readonly in conn.selects] == [False, True]
    # Read-only now: the message is fetched and no \Seen is attempted.
    assert [c[0] for c in conn.commands] == ["FETCH"]


async def test_a_folder_that_opens_neither_way_is_named(mail):
    mail["select"], mail["examine"] = "NO", "NO"
    result = await _read(mail, mark_seen=True)

    assert result == {"error": "Could not open email folder: Archive"}
    conn = mail["connections"][0]
    assert [readonly for _box, readonly in conn.selects] == [False, True]
    assert conn.commands == []


async def test_a_read_only_open_of_a_refused_folder_is_named(mail):
    mail["select"], mail["examine"] = "OK", "NO"
    result = await _read(mail, mark_seen=False)

    assert result == {"error": "Could not open email folder: Archive"}
    conn = mail["connections"][0]
    assert [readonly for _box, readonly in conn.selects] == [True]
    assert conn.commands == []


@pytest.mark.parametrize("path", ["/api/email/delete/{uid}", "/api/email/delete-permanent/{uid}"])
def test_a_delete_in_a_folder_that_will_not_open_says_so_and_sends_nothing(mail, path):
    mail["select"] = "NO"
    delete = _route_endpoint(mail["router"], path, "DELETE")

    result = delete("42", folder="Archive", account_id=None, owner="alice")

    assert result == {"success": False, "error": "Could not open email folder"}
    conn = mail["connections"][0]
    assert conn.selects == [('"Archive"', False)]
    assert not [c for c in conn.commands if c[0] in ("MOVE", "COPY", "STORE", "EXPUNGE")]
    assert mail["index_deletes"] == []


async def test_a_folder_that_opens_is_read_as_before(mail):
    mail["select"], mail["examine"] = "OK", "OK"
    result = await _read(mail, mark_seen=False, folder="INBOX")

    assert result["uid"] == "42"
    assert result.get("mark_seen_failed") is False
    assert mail["connections"][0].selects == [('"INBOX"', True)]
