# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2012`. The agent's bulk move said what it asked for, not what moved.

`bulk_email` (archive, junk, delete to Trash) told the model, and through it
the person, "Done — 3 email(s) archived" from a count `_bulk_move` fixed
before it sent the MOVE: how many of the UIDs the folder held, whatever the
server then did. A server that answers OK to UID MOVE without applying it, or
whose COPY and STORE fallback ends in an EXPUNGE that removes nothing, left
the mail where it was under a "Done". And after a MOVE answered NO having
moved part of the set (RFC 6851 allows that), a COPY refused for the rest
made the count 0 for mail that had moved.

Now `_bulk_move` asks the folder again, on the same connection, which of the
UIDs are still there and counts the ones that left. Only when that read fails
does it fall back to the server's own answer, as before. `bulk_email`'s zero
line says the server may not have applied the change.

From upstream Odysseus 84aa9a91. Its re-SELECT, its one-by-one retry and its
second mailbox-wide EXPUNGE are not taken.

Driven (`Law 20`): `_bulk_move` and the MCP server's own `call_tool` over a
folder that keeps its messages and applies each command as a case scripts it.
"""
import pytest

pytest.importorskip("mcp")

import mcp_servers.email_server as es


class Folder:
    """One IMAP folder and the UIDs in it. `moves` names the UIDs a MOVE
    really takes ("all" for every one asked), `move` how it answers; `copy`
    and `store` are those answers, and `expunge_removes` whether EXPUNGE takes
    what STORE flagged."""

    def __init__(self, *uids, move="OK", moves="all", copy="OK", store="OK",
                 expunge_removes=True, read_back=None):
        self.present = {str(u) for u in uids}
        self.flagged = set()
        self.move, self.moves = move, moves
        self.copy, self.store = copy, store
        self.expunge_removes = expunge_removes
        self.read_back = read_back
        self.fetches = 0
        self.commands = []

    def select(self, mailbox, readonly=False):
        self.commands.append(("SELECT", mailbox))
        return "OK", [str(len(self.present)).encode()]

    def list(self, *_args):
        return "OK", []

    def uid(self, command, *args):
        self.commands.append((command, *args))
        asked = args[0].decode().split(",")
        if command == "FETCH":
            self.fetches += 1
            if self.fetches > 1 and self.read_back is not None:
                raise self.read_back
            rows = [f"{i} (UID {u})".encode() for i, u in enumerate(asked, 1) if u in self.present]
            return "OK", rows or [None]
        if command == "MOVE":
            self.present -= set(asked if self.moves == "all" else self.moves)
            return self.move, [b""]
        if command == "COPY":
            return self.copy, [b""]
        if command == "STORE":
            if self.store == "OK":
                self.flagged |= set(asked) & self.present
            return self.store, [b""]
        raise AssertionError(f"unexpected IMAP command {command}")

    def expunge(self):
        self.commands.append(("EXPUNGE",))
        if self.expunge_removes:
            self.present -= self.flagged
        self.flagged = set()
        return "OK", [b""]

    def logout(self):
        pass


@pytest.fixture
def folder(monkeypatch):
    box = {}

    def connect(account=None):
        return box["folder"]

    monkeypatch.setattr(es, "_imap_connect", connect)
    return box


def _move(box, folder, uids=("5", "6", "7")):
    box["folder"] = folder
    return es._bulk_move(list(uids), "INBOX", "Archive", role="archive")


def test_a_compliant_move_counts_every_message(folder):
    mailbox = Folder("5", "6", "7")
    assert _move(folder, mailbox) == 3
    assert mailbox.present == set()


def test_a_uid_the_folder_does_not_hold_is_not_counted(folder):
    assert _move(folder, Folder("5", "6")) == 2


def test_a_move_answered_ok_that_moved_nothing_counts_nothing(folder):
    mailbox = Folder("5", "6", "7", moves=[])
    assert _move(folder, mailbox) == 0
    assert mailbox.present == {"5", "6", "7"}


def test_a_fallback_whose_expunge_removed_nothing_counts_nothing(folder):
    mailbox = Folder("5", "6", "7", move="NO", moves=[], expunge_removes=False)
    assert _move(folder, mailbox) == 0
    assert [c[0] for c in mailbox.commands][-3:] == ["STORE", "EXPUNGE", "FETCH"]


def test_a_partial_move_refused_for_the_rest_counts_what_moved(folder):
    """RFC 6851: a MOVE answered NO may have moved part of the set."""
    mailbox = Folder("5", "6", "7", move="NO", moves=["5"], copy="NO")
    assert _move(folder, mailbox) == 1
    assert "STORE" not in [c[0] for c in mailbox.commands]


def test_a_read_back_that_fails_falls_back_to_the_servers_answer(folder):
    mailbox = Folder("5", "6", "7", read_back=OSError("connection reset"))
    assert _move(folder, mailbox) == 3


def test_the_read_back_asks_the_same_folder_without_selecting_again(folder):
    mailbox = Folder("5", "6", "7")
    _move(folder, mailbox)
    assert [c[0] for c in mailbox.commands] == ["SELECT", "FETCH", "MOVE", "FETCH"]
    assert mailbox.commands[-1] == ("FETCH", b"5,6,7", "(UID)")


@pytest.fixture
def agent(folder, tmp_path, monkeypatch):
    for key in es._OWNER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(es, "APP_DB", str(tmp_path / "no-app.db"))
    monkeypatch.setattr(es, "_load_config", lambda account=None: {
        "trash_folder": "Trash", "archive_folder": "Archive", "junk_folder": "Junk"})
    return folder


async def test_bulk_email_says_nothing_moved_when_nothing_did(agent):
    agent["folder"] = Folder("5", "6", "7", moves=[])
    out = await es.call_tool("bulk_email", {"action": "archive", "uids": ["5", "6", "7"]})
    assert out[0].text == ("0 of 3 email(s) archived in INBOX: none of those UIDs is there, "
                           "or the server did not apply the change.")


async def test_bulk_email_counts_a_part_against_what_was_asked(agent):
    agent["folder"] = Folder("5", "6", "7", move="NO", moves=["5"], copy="NO")
    out = await es.call_tool("bulk_email", {"action": "delete", "uids": ["5", "6", "7"]})
    assert out[0].text == "Done — 1 email(s) moved to Trash (1 of 3 requested)."
