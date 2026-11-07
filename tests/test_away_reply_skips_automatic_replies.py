# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2013`. The away reply answered automatic replies that said so only in their subject.

With the away reply on, each new message in the inbox gets one, unless
`_sender_is_automated` (`routes/email_pollers.py`) says a machine sent it. It
read `Auto-Submitted`, `Precedence: bulk/junk/list`, the mailing-list headers
and a handful of no-reply addresses, and nothing else. So an auto-responder
that marks its reply only in the subject ("Automatic reply: …", "Réponse
automatique : …", "Out of Office: …"), only with Microsoft's
`X-Auto-Response-Suppress`, with `X-Autoreply` or `X-Autorespond`, or with
`Precedence: auto_reply` got an away reply back, once per sender per cooldown.

Now each of those counts as automated, under the same "Skip automated and
no-reply senders" switch, so a person can still turn the check off. The
subject is read decoded and has to *start* with an automatic-reply marker and
its colon, in English, French, German, Spanish, Italian, Portuguese, Dutch,
Swedish or Danish and Norwegian. A person who writes "Are you out of office on
Friday?", "OOO next week" or "Re: Automatic reply: …" still gets the away reply.

From upstream Odysseus 84aa9a91, which matched "out of office" or "ooo"
anywhere in the raw header: that held the away reply back from people asking
about leave, and missed an encoded French subject. The anchored match on the
decoded subject and the header checks are Pantheon's; upstream's urgent-tag
cleanup in the same change is a feature and is not taken.
"""
from __future__ import annotations

import email

import pytest

import routes.email_pollers as pollers

ME = "me@example.test"


def _message(subject: str | None, headers: dict | None = None):
    lines = ["From: Dana Reyes <dana@example.test>", f"To: {ME}",
             "Message-ID: <reply-1@example.test>"]
    if subject is not None:
        lines.append(f"Subject: {subject}")
    lines += [f"{name}: {value}" for name, value in (headers or {}).items()]
    return email.message_from_string("\r\n".join(lines) + "\r\n\r\nI am away until Monday.\r\n")


AUTOMATIC_SUBJECTS = [
    "Automatic reply: Invoice 4411",
    "=?iso-8859-1?Q?R=E9ponse_automatique=A0:_Invoice_4411?=",   # French Outlook, encoded
    "Réponse automatique : Invoice 4411",
    "Automatische Antwort: Invoice 4411",
    "Abwesenheitsnotiz: Invoice 4411",
    "Out of Office: back Monday",
    "Out of Office AutoReply: Invoice 4411",
    "Auto-Reply: Invoice 4411",
    "Respuesta automática: Invoice 4411",
    "Risposta automatica: Invoice 4411",
    "Resposta automática: Invoice 4411",
    "Automatisch antwoord: Invoice 4411",
    "Automatiskt svar: Invoice 4411",
    "Autosvar: Invoice 4411",
]

AUTOMATIC_HEADERS = [
    {"X-Auto-Response-Suppress": "OOF, AutoReply"},
    {"X-Auto-Response-Suppress": "All"},
    {"X-Autoreply": "yes"},
    {"X-Autorespond": "Invoice 4411"},
    {"Precedence": "auto_reply"},
]

PERSONAL_SUBJECTS = [
    "Are you out of office on Friday?",
    "OOO next week - please contact Dana",
    "Out of office tomorrow, call me",
    "Re: Automatic reply: Invoice 4411",
    "Re: auto-reply settings for the shared inbox",
    "Invoice 4411",
]


@pytest.mark.parametrize("subject", AUTOMATIC_SUBJECTS)
def test_a_subject_that_starts_as_an_automatic_reply_is_automated(subject):
    assert pollers._sender_is_automated(_message(subject), "dana@example.test") is True


@pytest.mark.parametrize("headers", AUTOMATIC_HEADERS, ids=lambda h: ", ".join(f"{k}: {v}" for k, v in h.items()))
def test_a_header_that_marks_an_automatic_reply_is_automated(headers):
    assert pollers._sender_is_automated(_message("Invoice 4411", headers), "dana@example.test") is True


@pytest.mark.parametrize("subject", PERSONAL_SUBJECTS)
def test_a_person_asking_about_leave_is_not_automated(subject):
    assert pollers._sender_is_automated(_message(subject), "dana@example.test") is False


def test_a_suppress_header_for_receipts_only_is_not_automated():
    msg = _message("Quarterly numbers", {"X-Auto-Response-Suppress": "RN, NRN"})
    assert pollers._sender_is_automated(msg, "dana@example.test") is False


def test_the_headers_already_honoured_still_are():
    for headers in ({"Auto-Submitted": "auto-replied"}, {"Precedence": "bulk"},
                    {"List-Id": "<team.example.test>"}):
        assert pollers._sender_is_automated(_message("Invoice 4411", headers), "dana@example.test") is True
    assert pollers._sender_is_automated(_message("Invoice 4411"), "no-reply@example.test") is True
    assert pollers._sender_is_automated(_message("Invoice 4411", {"Auto-Submitted": "no"}),
                                        "dana@example.test") is False


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(pollers, "_get_email_config", lambda account_id=None, owner=None: {"from_address": ME})
    monkeypatch.setattr(pollers, "_send_smtp_message",
                        lambda cfg, from_addr, to, raw: sent.append((from_addr, list(to), raw)))
    monkeypatch.setattr(pollers, "_away_reply_already_sent", lambda *a, **k: False)
    monkeypatch.setattr(pollers, "_record_away_reply", lambda *a, **k: None)
    return sent


def _away_reply(msg, settings=None):
    """What the poller does for a new message: the subject arrives decoded."""
    return pollers._send_away_reply(
        settings if settings is not None else {"email_auto_reply_enabled": True},
        "rowan", "home-acct", msg, msg["Message-ID"], msg["From"],
        pollers._decode_header(msg.get("Subject", "")),
    )


@pytest.mark.parametrize("subject", ["Automatic reply: Invoice 4411",
                                     "=?iso-8859-1?Q?R=E9ponse_automatique=A0:_Invoice_4411?="])
def test_an_automatic_reply_gets_no_away_reply(outbox, subject):
    assert _away_reply(_message(subject)) == (False, "automated sender")
    assert outbox == []


def test_a_person_asking_about_leave_still_gets_the_away_reply(outbox):
    assert _away_reply(_message("Are you out of office on Friday?")) == (True, "dana@example.test")
    assert [to for _, to, _ in outbox] == [["dana@example.test"]]


def test_the_exclude_automated_switch_still_turns_the_check_off(outbox):
    settings = {"email_auto_reply_enabled": True, "email_auto_reply_exclude_automated": False}
    assert _away_reply(_message("Automatic reply: Invoice 4411"), settings) == (True, "dana@example.test")
    assert len(outbox) == 1
