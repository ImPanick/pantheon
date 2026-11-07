# SPDX-License-Identifier: AGPL-3.0-or-later
"""Email move/flag must never fall back to sequence-number IMAP ops (#1874 sibling).

`imaplib`'s plain `store()` / `copy()` operate on message SEQUENCE NUMBERS, not
UIDs. `_store_email_flag` / `_move_email_message` (used by the archive / delete /
move / mark endpoints) had an `else` fallback that, when `_uid_exists` returned
False, ran `conn.store(uid, …)` / `conn.copy(uid, …)` + `conn.expunge()` — i.e.
it flagged/copied whichever message occupied sequence position == the UID value
and then permanently expunged it. A stale cached UID (or a server whose UID
probe misbehaves) therefore deleted an unrelated email.

The fix fails safe: when the UID isn't present, return False (callers surface
"Email not found") and never touch a message by sequence number.

This is distinct from #1874, which fixes the auto-spam poller's `_imap_move` in
`routes/email_helpers.py`; this covers the user-facing endpoints in
`routes/email_routes.py`.

`B2010`. The probe itself misjudged two kinds of UID. A message that a server
answered the `(UID)` probe for with NO, or without the UID item, was "not
found", so every mark, star, archive, move and delete of it failed; now such a
probe is asked again by UID SEARCH, which must name the exact UID. And a uid
that is not one number passed: `1:*` matched any FETCH row, and the UID MOVE or
STORE after it acted on the whole folder. Now a uid that is not one plain
ASCII number is refused before the probe, so no MOVE or STORE is sent for it.
`strict` lets a delete tell a message that is gone from a lookup that failed.
From upstream Odysseus 84aa9a91 (the SEARCH fallback) and 218d7624 (`strict`,
whose first three lookup cases are reused below).
"""
from unittest.mock import MagicMock

import pytest

from routes import email_routes
from routes.email_routes import _move_email_message, _store_email_flag, _uid_exists


class _FakeConn:
    """Records IMAP calls. `uid_present` controls the FETCH-UID probe result.

    The sequence-number commands (store/copy/expunge) raise if ever called —
    the whole point of the fix is that they must not be reached.
    """
    def __init__(self, uid_present, uid_move_ok=True):
        self.uid_present = uid_present
        self.uid_move_ok = uid_move_ok
        self.uid_calls = []
        self.seqno_calls = []

    def uid(self, command, *args):
        self.uid_calls.append((command.upper(), args))
        cmd = command.upper()
        if cmd == "FETCH":
            return ("OK", [b"1 (UID 5031)"] if self.uid_present else [])
        if cmd == "MOVE":
            return ("OK" if self.uid_move_ok else "NO", [b""])
        if cmd in ("COPY", "STORE"):
            return ("OK", [b""])
        return ("OK", [b""])

    # Sequence-number APIs — must never be used with a UID.
    def store(self, *a):
        self.seqno_calls.append(("store", a)); return ("OK", [b""])

    def copy(self, *a):
        self.seqno_calls.append(("copy", a)); return ("OK", [b""])

    def expunge(self, *a):
        self.seqno_calls.append(("expunge", a)); return ("OK", [b""])


@pytest.fixture(autouse=True)
def _no_folder_resolution(monkeypatch):
    # _move_email_message resolves the destination folder via the connection;
    # short-circuit it so the test focuses on the UID-vs-seqno behaviour.
    monkeypatch.setattr(email_routes, "_resolve_mail_folder", lambda conn, dest, role="": dest)


def test_store_flag_missing_uid_fails_safe():
    conn = _FakeConn(uid_present=False)
    assert _store_email_flag(conn, "5031", "\\Deleted", add=True) is False
    assert conn.seqno_calls == []  # never touched a message by sequence number


def test_move_missing_uid_fails_safe():
    conn = _FakeConn(uid_present=False)
    assert _move_email_message(conn, "5031", "Trash", role="trash") is False
    assert conn.seqno_calls == []  # no copy/store/expunge on a phantom seqno


def test_store_flag_present_uid_uses_uid_store():
    conn = _FakeConn(uid_present=True)
    assert _store_email_flag(conn, "5031", "\\Seen", add=True) is True
    assert any(c[0] == "STORE" for c in conn.uid_calls)
    assert conn.seqno_calls == []


def test_move_present_uid_uses_uid_move():
    conn = _FakeConn(uid_present=True, uid_move_ok=True)
    assert _move_email_message(conn, "5031", "Archive", role="archive") is True
    assert any(c[0] == "MOVE" for c in conn.uid_calls)
    assert conn.seqno_calls == []


# ── `B2010`: what the probe asks, and what it counts as an answer ──────────


class _ScriptedConn:
    """Answers UID FETCH and UID SEARCH as a case scripts them (an exception is
    raised) and records every command, so a case can say what was never sent."""

    def __init__(self, fetch=("OK", [None]), search=("OK", [b""])):
        self.answers = {"FETCH": fetch, "SEARCH": search}
        self.calls = []

    def uid(self, command, *args):
        cmd = command.upper()
        self.calls.append((cmd, args))
        answer = self.answers.get(cmd, ("OK", [b""]))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def expunge(self):
        self.calls.append(("EXPUNGE", ()))
        return ("OK", [b""])


@pytest.mark.parametrize("fetch", [
    ("OK", [b"1 (FLAGS (\\Seen))"]),   # the probe's row carries no UID item
    ("NO", [b"probe refused"]),
], ids=["no-uid-item", "fetch-no"])
def test_a_probe_without_its_uid_is_asked_again_by_uid_search(fetch):
    conn = _ScriptedConn(fetch=fetch, search=("OK", [b"5031"]))
    assert _uid_exists(conn, "5031") is True
    assert conn.calls[-1] == ("SEARCH", (None, "UID 5031"))


def test_a_message_found_by_uid_search_is_moved():
    conn = _ScriptedConn(fetch=("OK", [b"1 (FLAGS (\\Seen))"]), search=("OK", [b"5031"]))
    assert _move_email_message(conn, "5031", "Trash", role="trash") is True
    assert ("MOVE", (b"5031", '"Trash"')) in conn.calls


@pytest.mark.parametrize("search", [
    ("OK", [b"5030 5032"]),   # only its neighbours
    ("OK", [b""]),
    ("OK", [None]),
], ids=["neighbours", "empty", "none"])
def test_uid_search_counts_only_the_exact_uid(search):
    conn = _ScriptedConn(fetch=("OK", [None]), search=search)
    assert _uid_exists(conn, "5031") is False


def test_a_fetch_row_for_another_message_is_not_this_one():
    """A row the server pushes for another message (a flag change elsewhere)
    named some UID, and any UID used to count."""
    conn = _ScriptedConn(fetch=("OK", [b"7 (UID 4000 FLAGS (\\Seen))"]), search=("OK", [b""]))
    assert _uid_exists(conn, "5031") is False


@pytest.mark.parametrize("uid", ["1:*", "5,7", "*", "\uff15", "", None, "5031 "],
                         ids=["range", "list", "star", "fullwidth", "empty", "none", "space"])
def test_a_uid_that_is_not_one_number_sends_no_command(uid):
    rows = ("OK", [b"1 (UID 5031)", b"2 (UID 5032)"])
    conn = _ScriptedConn(fetch=rows, search=("OK", [b"5031 5032"]))
    assert _uid_exists(conn, uid) is False
    assert _move_email_message(conn, uid, "Trash", role="trash") is False
    assert _store_email_flag(conn, uid, "\\Deleted", add=True) is False
    assert conn.calls == []


def test_a_uid_sent_as_bytes_is_still_one_number():
    conn = _ScriptedConn(fetch=("OK", [b"1 (UID 5031)"]))
    assert _uid_exists(conn, b"5031") is True
    assert conn.calls == [("FETCH", (b"5031", "(UID)"))]


def test_strict_refuses_a_uid_that_is_not_one_number_before_any_command():
    conn = _ScriptedConn(fetch=("OK", [b"1 (UID 5031)"]))
    with pytest.raises(ValueError):
        _uid_exists(conn, "1:*", strict=True)
    assert conn.calls == []


def test_strict_raises_when_uid_search_is_refused():
    conn = _ScriptedConn(fetch=("OK", [b"1 (FLAGS (\\Seen))"]), search=("NO", [b"search refused"]))
    with pytest.raises(RuntimeError):
        _uid_exists(conn, "5031", strict=True)
    # Without strict a refused lookup still reads as "not found", as before.
    assert _uid_exists(conn, "5031") is False


def test_strict_reraises_a_probe_that_fails():
    conn = _ScriptedConn(fetch=OSError("connection reset"))
    with pytest.raises(OSError):
        _uid_exists(conn, "5031", strict=True)
    assert _uid_exists(conn, "5031") is False


# Upstream 218d7624's tests/test_review_email_delete_lookup.py, its first three
# cases, asked of `_uid_exists(strict=True)` (Pantheon has no
# `_resolve_current_email_uid`).

def test_disconnect_is_not_confirmed_absence():
    conn = MagicMock()
    conn.uid.side_effect = OSError("IMAP disconnected")
    with pytest.raises(OSError):
        _uid_exists(conn, "123", strict=True)


def test_rejected_search_is_not_confirmed_absence():
    conn = MagicMock()
    conn.uid.side_effect = [("OK", [None]), ("NO", [b"search failed"])]
    with pytest.raises(RuntimeError):
        _uid_exists(conn, "123", strict=True)


def test_confirmed_absence_can_be_idempotent():
    conn = MagicMock()
    conn.uid.side_effect = [("OK", [None]), ("OK", [b""])]
    assert _uid_exists(conn, "123", strict=True) is False
