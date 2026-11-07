# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1965`. A signed reply is addressed to the sender of the mail it answers.

A PDF form opened from a mail attachment keeps the message's IMAP UID
(`attachment_as_doc` stores the UID the mailbox read it by). Send signed reply
then read that message's headers back with a plain FETCH, which takes the
number as a sequence number. In a folder where anything older was ever
expunged, which is nearly every real inbox, that number is another message, so
the draft's To, Subject and In-Reply-To were a stranger's, and the person
reading the draft before Send was the only check. The mailbox was also opened
without the person's name, so a document opened from the reader's preview (no
account id) read the install's default mailbox, which on a shared install can
be someone else's.

The headers are fetched by UID now, from the signed-in person's mailbox; a
message that is gone, or a UID that now names a message with another
Message-ID, leaves the reply unaddressed. From upstream Odysseus #7069
(1801b54e, issue #5456), with its expunged-mailbox fake.

Driven through the real document router over `B1007`'s harness.
"""
from contextlib import contextmanager

import pytest

import core.database as cdb
from tests.test_a_signed_form_keeps_its_name import _filler, _form, compose  # noqa: F401
from tests.test_an_uploaded_document_keeps_its_name import OWNER, env  # noqa: F401


def _header(sender: str, subject: str, message_id: str, refs: str = "") -> bytes:
    lines = [f"From: {sender}", f"Subject: {subject}", f"Message-ID: {message_id}"]
    if refs:
        lines.append(f"References: {refs}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


ALICE = _header("Alice <alice@example.com>", "Contract", "<contract@example.com>",
                "<thread-start@example.com>")
MALLORY = _header("Mallory <mallory@example.com>", "Unrelated", "<other@example.com>")


class _ExpungedMailbox:
    """A folder where UID 7 is the third message: sequence number 7 is Mallory's."""

    def __init__(self, by_uid):
        self.by_uid = by_uid
        self.by_seq = {b"7": MALLORY}
        self.selected = None
        self.uid_calls = []

    def select(self, mailbox, readonly=False):
        self.selected = (mailbox, readonly)
        return "OK", [b"3"]

    def uid(self, command, *args):
        self.uid_calls.append((command,) + args)
        msg_set, _query = args
        raw = self.by_uid.get(msg_set)
        if raw is None:
            return "OK", [None]
        return "OK", [(b"1 (UID " + msg_set + b" RFC822.HEADER {%d}" % len(raw), raw), b")"]

    def fetch(self, msg_set, query):
        raw = self.by_seq.get(msg_set)
        if raw is None:
            return "OK", [None]
        return "OK", [(msg_set + b" (RFC822.HEADER {%d}" % len(raw), raw), b")"]


@pytest.fixture
def mailbox(env, monkeypatch):
    opened = []

    def install(by_uid):
        box = _ExpungedMailbox(by_uid)

        @contextmanager
        def _fake_imap(account_id=None, owner=""):
            opened.append((account_id, owner))
            yield box

        monkeypatch.setattr(env.email_routes, "_imap", _fake_imap)
        box.opened = opened
        return box

    return install


def _reply(env, doc_id, message_id=None):
    if message_id is not None:
        db = env.Session()
        try:
            db.query(cdb.Document).filter(cdb.Document.id == doc_id).one() \
                .source_email_message_id = message_id
            db.commit()
        finally:
            db.close()
    r = env.client.post(f"/api/document/{doc_id}/prepare-signed-reply")
    assert r.status_code == 200, r.text
    return r.json()["reply"]


def test_the_reply_is_addressed_to_the_sender_of_the_message_by_its_uid(env, compose, mailbox):
    box = mailbox({b"7": ALICE})
    reply = _reply(env, _form(env, "Contract form"), "<contract@example.com>")

    assert box.uid_calls == [("FETCH", b"7", "(RFC822.HEADER)")]
    assert box.selected == ('"INBOX"', True)
    assert (reply["to"], reply["to_name"], reply["subject"]) == ("alice@example.com", "Alice", "Re: Contract")
    assert reply["in_reply_to"] == "<contract@example.com>"
    assert reply["references"] == "<thread-start@example.com> <contract@example.com>"


def test_the_reply_reads_the_signed_in_persons_mailbox(env, compose, mailbox):
    box = mailbox({b"7": ALICE})
    _reply(env, _form(env, "Contract form"))

    assert box.opened == [(None, OWNER)]


def test_a_message_gone_from_the_server_leaves_the_reply_unaddressed(env, compose, mailbox):
    mailbox({})
    reply = _reply(env, _form(env, "Contract form"), "<contract@example.com>")

    assert (reply["to"], reply["to_name"], reply["subject"]) == ("", "", "")
    assert reply["in_reply_to"] == reply["references"] == "<contract@example.com>"


def test_a_uid_that_now_names_another_message_leaves_the_reply_unaddressed(env, compose, mailbox):
    # The folder's UIDVALIDITY changed: UID 7 is a different message now.
    mailbox({b"7": _header("Eve <eve@example.com>", "Hello", "<new@example.com>")})
    reply = _reply(env, _form(env, "Contract form"), "<contract@example.com>")

    assert (reply["to"], reply["to_name"], reply["subject"]) == ("", "", "")
    assert reply["in_reply_to"] == reply["references"] == "<contract@example.com>"
