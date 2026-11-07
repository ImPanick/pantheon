# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1964`. A display name with a comma in it stays one recipient on every send.

Exchange and Outlook write a name as `"Smith, John" <john@corp.com>`. The
person's own send (`/send`) already read the address grammar
(`_envelope_recipients`), but the scheduled-send poller, which also sends every
agent draft a person approves, and the agent's own `send_email` with
confirmation off split each field on its commas. The envelope then said RCPT TO
`"Smith` and `John" <john@corp.com>`: a refused recipient, which the send still
reported as sent, or no delivery at all.

`src/mail_headers.envelope_recipients` is now the one parser, and all three
paths use it. It keeps `/send`'s trailing-comma clean-up first, because the
strict `getaddresses` reads a pasted `a@x.com,` as no address at all. Adapted
from upstream Odysseus #6910 (35c87498), which put the parser in a module of
its own.
"""
import email
import sqlite3

import pytest


def test_one_parser_reads_a_name_with_a_comma_a_pasted_trailing_comma_and_a_list():
    from src.mail_headers import envelope_recipients

    assert envelope_recipients('"Smith, John" <john@corp.com>') == ["john@corp.com"]
    assert envelope_recipients("a@x.com,", None, ["b@y.com"]) == ["a@x.com", "b@y.com"]
    assert envelope_recipients(" , a@x.com, , b@y.com, ") == ["a@x.com", "b@y.com"]
    assert envelope_recipients("", None, []) == []


def test_a_scheduled_mail_reaches_a_name_with_a_comma_and_keeps_its_bcc_private(tmp_path, monkeypatch):
    import routes.email_helpers as helpers
    import routes.email_pollers as pollers

    db_path = tmp_path / "scheduled.db"
    monkeypatch.setattr(helpers, "SCHEDULED_DB", db_path)
    monkeypatch.setattr(pollers, "SCHEDULED_DB", db_path)
    helpers._init_scheduled_db()
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO scheduled_emails
            (id, to_addr, cc, bcc, subject, body, attachments, send_at, created_at,
             status, account_id, owner)
            VALUES ('quoted', ?, ?, ?, 'Test', 'Body', '[]', '2000-01-01T00:00:00',
                    '1999-12-31T00:00:00', 'pending', 'acct-ada', 'ada')
        """, ('"Smith, John" <john@corp.com>', "a@x.com,", '"Private, Pat" <pat@example.test>'))
    captured = {}

    def send(cfg, sender, recipients, message):
        captured.update(recipients=recipients, message=email.message_from_string(message))

    class _Imap:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def append(self, *args):
            pass

    monkeypatch.setattr(pollers, "_get_email_config",
                        lambda account=None, owner="": {"from_address": "ada@example.test"})
    monkeypatch.setattr(pollers, "_send_smtp_message", send)
    monkeypatch.setattr(pollers, "_imap", _Imap)
    monkeypatch.setattr(pollers, "_detect_sent_folder", lambda imap: "Sent")
    monkeypatch.setattr(pollers, "_cleanup_compose_uploads", lambda attachments: None)

    assert pollers._scheduled_poll_once() == {"sent": ["quoted"], "failed": []}
    assert captured["recipients"] == ["john@corp.com", "a@x.com", "pat@example.test"]
    assert captured["message"]["Bcc"] is None
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT status FROM scheduled_emails").fetchone() == ("sent",)


@pytest.mark.parametrize("as_lists", [False, True])
def test_the_agents_direct_send_reaches_a_name_with_a_comma(monkeypatch, as_lists):
    import mcp_servers.email_server as es

    captured = {}

    class _Smtp:
        def send_message(self, message, from_addr, to_addrs):
            captured.update(message=message, recipients=to_addrs)

        def quit(self):
            captured["closed"] = True

    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: False)
    monkeypatch.setattr(es, "_resolve_send_config", lambda account: (
        "acct-ada", {"from_address": "ada@example.test", "account_id": "acct-ada"},
    ))
    monkeypatch.setattr(es, "_smtp_connect", lambda *args, **kwargs: _Smtp())
    monkeypatch.setattr(es, "_imap_connect", lambda *args: (_ for _ in ()).throw(OSError("no inbox")))
    to = ['"Doe, Jane" <jane@example.test>', "bob@example.test"]
    cc = ['"Smith, Sam" <sam@example.test>']
    bcc = ['"Private, Pat" <pat@example.test>']

    result = es._send_email(
        to if as_lists else ", ".join(to), "Test", "Body",
        cc=cc if as_lists else ", ".join(cc),
        bcc=bcc if as_lists else ", ".join(bcc),
    )

    expected = ["jane@example.test", "bob@example.test", "sam@example.test", "pat@example.test"]
    assert captured["recipients"] == expected
    assert result["sent"] is True and result["to"] == expected
    assert captured["closed"] is True
    assert captured["message"]["Bcc"] is None
    assert email.utils.getaddresses([str(captured["message"]["To"])]) == [
        ("Doe, Jane", "jane@example.test"), ("", "bob@example.test"),
    ]
