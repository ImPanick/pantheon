# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1945`. Email Tags marked every receipt and statement as needing action.

The Email Tags task (`check_email_urgency`; it ships paused and runs hourly
once a person turns it on) scores received mail with a keyword rule, and that
rule is the whole classifier: its verdict is cached and no model is asked. One
pattern mixed real asks with bare billing words (invoice, bill, payment,
balance, subscription, renewal ...), so any of those words added
`action-needed`, which scores 2. Score 2 is the reply-soon tag and the
threshold of the "Urgent email" reminder, so every unread receipt, renewal
confirmation, paid invoice or bank statement could raise one.

Now `action-needed` takes an explicit ask (please reply, submit, sign, a
deadline ...) or a consequence (payment due, pay by, overdue, a declined card,
a failed payment, an unpaid invoice ...). The receipt and bills type tags and
the urgent words are unchanged. `TRIAGE_VERSION` moves to 11, so the cached
verdicts are scored again once, by this rule and with no model call.

Adapted from upstream Odysseus 84aa9a91
(`test_company_receipt_is_not_marked_urgent_or_reply_soon`,
`test_payment_due_with_deadline_is_reply_soon_bill`). Upstream's list lets a
declined card and an unpaid invoice fall to 0; this one keeps them.

Driven (`Law 20`) for the version: the real `action_check_email_urgency` over
the fake mailbox of `tests/test_email_urgency_checkpoint.py`.
"""
import json
import sqlite3

from src.builtin_actions import _heuristic_email_verdict

#: The tags the action passes in (`CATEGORY_TAGS` in `action_check_email_urgency`).
TAGS = {"bills", "receipt", "travel", "calendar", "action-needed"}


def _verdict(sender, subject, body):
    return _heuristic_email_verdict(
        {"from": sender, "subject": subject, "body": body, "headers": "",
         "message_id": "<m-1@example.test>", "unread": True},
        triage_version=11, category_tags=TAGS)


def _needs_action(verdict):
    return verdict["score"] == 2 and "action-needed" in verdict["tags"]


def test_a_receipt_is_not_action_needed_but_a_bill_that_is_due_still_is():
    due = _verdict("City Power <billing@power.example>", "Payment due for your electricity bill",
                   "Amount due: $84.20. Please pay by 18 August to avoid a late fee.")
    assert _needs_action(due) and "bills" in due["tags"]

    receipt = _verdict("Acme Store <receipts@acme.example>", "Your receipt from Acme Store",
                       "Thanks for your order. Payment received: $42.00. Receipt #1234.")
    assert receipt["score"] < 2, receipt
    assert "action-needed" not in receipt["tags"]
    assert "receipt" in receipt["tags"], "still filed as a receipt"


def test_confirmations_and_statements_are_not_action_needed_but_a_failed_payment_still_is():
    for still_needs_action in (
        _verdict("Bank <alerts@bank.example>", "Your card was declined",
                 "We could not take your payment. Please update your payment method."),
        _verdict("Hosting <billing@host.example>", "Payment failed",
                 "Your payment has failed for the server plan."),
        _verdict("Studio <accounts@studio.example>", "Invoice #88 is unpaid",
                 "Invoice #88 for $310 is still unpaid."),
        _verdict("Sam <sam@example.test>", "Friday", "Can you please reply about Friday?"),
    ):
        assert _needs_action(still_needs_action), still_needs_action

    for confirmation in (
        _verdict("Music <no-reply@music.example>", "Your subscription has been renewed",
                 "Your annual plan renewed on 3 September. Nothing else is needed."),
        _verdict("Studio <accounts@studio.example>", "Invoice #2041 paid",
                 "Thank you, invoice #2041 has been paid in full. Your balance is $0.00."),
        _verdict("Bank <statements@bank.example>", "Your March statement is ready",
                 "Your account statement for March is now available. Balance: $1,204.10."),
    ):
        assert confirmation["score"] < 2, confirmation
        assert "action-needed" not in confirmation["tags"], confirmation


RECEIPT = (
    b"From: Acme Store <receipts@acme.example>\r\n"
    b"Subject: Your receipt from Acme Store\r\n"
    b"Message-ID: <receipt-1@acme.example>\r\n"
    b"\r\n"
    b"Thanks for your order. Payment received: $42.00. Receipt #1234."
)


async def test_a_receipt_the_old_rule_put_in_reply_soon_is_scored_again(monkeypatch, tmp_path):
    """A cached verdict is trusted only at its own `TRIAGE_VERSION`. At 10 the
    receipt the old rule scored 2 stayed reply-soon, and as unread mail it
    raised an "Urgent email" reminder; at 11 it is scored again, with no model
    call, and keeps only its receipt tag."""
    import routes.note_routes as note_routes
    from routes import email_helpers
    from tests.test_email_urgency_checkpoint import _FakeImap, _configure_action

    builtin_actions, runtime = _configure_action(monkeypatch, tmp_path, ["acct-a"])

    class _ReceiptMailbox(_FakeImap):
        def uid(self, command, *args):
            status, data = super().uid(command, *args)
            if command == "FETCH" and str(args[-1]) != "(UID FLAGS)":
                data = [(data[0][0], RECEIPT)]
            return status, data

    monkeypatch.setattr(email_helpers, "_imap_connect", lambda account_id=None, **_kwargs: _ReceiptMailbox(
        str(account_id), runtime["failures"], runtime["seen_accounts"], runtime["search_uids"]))
    reminders = []

    async def delivered(**kwargs):
        reminders.append(kwargs["note_body"])
        return {"browser_sent": True, "email_sent": False, "ntfy_sent": False, "webhook_sent": False}

    monkeypatch.setattr(note_routes, "dispatch_reminder", delivered)
    cache_file = tmp_path / "urgency-cache" / "acct-a.json"
    cache_file.parent.mkdir()
    cache_file.write_text(json.dumps({"uids": {"1": {
        "score": 2, "tags": ["action-needed", "receipt"], "spam": False,
        "reason": "action likely needed", "subject": "Your receipt from Acme Store",
        "from": "Acme Store", "triage_version": 10,
        "message_id": "<receipt-1@acme.example>", "unread": True, "ts": 0}}}), encoding="utf-8")

    message, ok = await builtin_actions.action_check_email_urgency("alice")

    assert ok is True
    assert "reply-soon 0" in message and "1 saved classifications" in message, message
    assert reminders == [], "a receipt raises no Urgent email reminder"
    verdict = json.loads(cache_file.read_text(encoding="utf-8"))["uids"]["1"]
    assert verdict["triage_version"] == 11 and verdict["score"] == 0, verdict
    conn = sqlite3.connect(tmp_path / "scheduled-emails.db")
    try:
        rows = conn.execute("SELECT tags FROM email_tags WHERE message_id = ?",
                            ("<receipt-1@acme.example>",)).fetchall()
    finally:
        conn.close()
    assert [json.loads(tags) for (tags,) in rows] == [["receipt"]]
