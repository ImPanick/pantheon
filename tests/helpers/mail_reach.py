# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2102`. For a test whose mail server is a loopback stand-in.

A mail account reaches this machine or a private network only for a person
who holds `can_reach_private_mail` (`src/mail_reach.py`). A test that stands a
fake IMAP or SMTP server up on `127.0.0.1` is testing something else — a
sentence, a timeout, a certificate — for a person allowed to reach it, and says
so with this. What the guard refuses is `tests/test_the_mail_test_is_not_a_port_scanner.py`'s.
"""
from __future__ import annotations


def allow_this_network(monkeypatch) -> None:
    """Every person named in this test holds `can_reach_private_mail` and may
    reach this machine, which takes an admin (`src/mail_reach.py`)."""
    import src.mail_reach as mail_reach
    monkeypatch.setattr(mail_reach, "_holds", lambda owner: True)
    monkeypatch.setattr(mail_reach, "_is_admin", lambda owner: True)
