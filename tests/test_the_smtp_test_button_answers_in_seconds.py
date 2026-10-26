# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1535` — the account form's SMTP test waited its whole timeout on a silent server.

`POST /api/email/accounts/test` opened `smtplib.SMTP`/`SMTP_SSL` with one
`timeout=10` for connecting and signing in alike, so a mail server that
accepted the connection and never greeted held the Test button for ten
seconds — `B1526`'s shape on the form. It opens with the mail openers' five
seconds now (`_MAIL_CONNECT_SECONDS`) and keeps ten for the sign-in.

Driven through the real route handler against a real loopback socket that
completes the handshake and says nothing (`B1526`'s listener), and against one
that greets, to show the sign-in still has its ten seconds.
"""
from __future__ import annotations

import smtplib
import time

import pytest

from routes.email_helpers import _MAIL_CONNECT_SECONDS
from tests.test_a_send_to_a_mail_server_that_is_not_there_fails_in_seconds import (  # noqa: F401
    greeting_server, silent_server,
)


def _route():
    from routes.email_routes import setup_email_routes

    for route in setup_email_routes().routes:
        if route.path == "/api/email/accounts/test" and "POST" in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError("POST /api/email/accounts/test is not registered")


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _body(port):
    # No IMAP host: that half answers "Need IMAP host…" at once, so the time
    # measured is the SMTP half's.
    return {"smtp_host": "127.0.0.1", "smtp_port": port, "smtp_security": "none",
            "smtp_user": "me@example.test", "smtp_password": "pw"}


@pytest.mark.asyncio
async def test_a_server_that_never_greets_is_reported_in_about_five_seconds(silent_server):
    started = time.monotonic()
    result = await _route()(req=_Req(_body(silent_server)), owner="alice")
    elapsed = time.monotonic() - started

    assert result["smtp"]["ok"] is False
    assert result["smtp"]["error"]
    assert elapsed < _MAIL_CONNECT_SECONDS + 3, f"the Test button waited {elapsed:.1f}s"
    assert elapsed >= _MAIL_CONNECT_SECONDS - 1, f"gave up after {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_a_server_that_greets_gives_the_sign_in_its_ten_seconds(greeting_server, monkeypatch):
    seen = {}

    def login(self, user, password, *a, **k):
        seen["timeout"] = self.sock.gettimeout()
        return (235, b"ok")

    monkeypatch.setattr(smtplib.SMTP, "login", login)
    result = await _route()(req=_Req(_body(greeting_server)), owner="alice")

    assert result["smtp"] == {"ok": True}
    assert seen == {"timeout": 10}
