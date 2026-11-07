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

`B1921` — and while the Test waited, so did everyone else. The handler is an
`async def` and opened both connections on the event loop itself, so for each
of those seconds no other request was answered, for any person; `B1223` had
moved only the saved account's read off the loop. The two connections are made
in a pool of their own now (`_ACCOUNT_TEST_POOL`, two threads), so a slow or
silent server holds a Test, never the server, and a burst of Tests holds two
threads rather than the default pool the chat send and the document writes
share. From upstream Odysseus 3d91ad82, whose test this is, with its timings.
"""
from __future__ import annotations

import asyncio
import smtplib
import socket
import threading
import time
from unittest import mock

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


# ── `B1921`: the Test waits, and nobody else does ───────────────────────────

_IMAP_ONLY = {"imap_host": "imap.example.test", "imap_port": 993,
              "imap_user": "me@example.test", "imap_password": "pw"}


@pytest.mark.asyncio
async def test_three_tests_against_a_server_that_never_answers_leave_the_server_answering(monkeypatch):
    """Upstream's test: three Tests at once, each against a mail server that
    takes a second to fail. The loop keeps beating every 20 ms throughout, and
    with two threads the three take about two seconds, not three in a row."""
    import routes.email_routes as email_routes

    def _slow_open(host, port, **kwargs):
        time.sleep(1.0)   # a mail server that never answers within the timeout
        raise socket.timeout("timed out")

    monkeypatch.setattr(email_routes, "_open_imap_connection", _slow_open)
    endpoint = _route()
    gaps, done = [], asyncio.Event()

    async def _heartbeat():
        last = time.perf_counter()
        while not done.is_set():
            await asyncio.sleep(0.02)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(_heartbeat())
    started = time.perf_counter()
    results = await asyncio.gather(*(endpoint(req=_Req(dict(_IMAP_ONLY)), owner="alice") for _ in range(3)))
    elapsed = time.perf_counter() - started
    done.set()
    await beat

    assert max(gaps) < 0.5, f"the event loop stalled for {max(gaps):.2f}s"
    assert elapsed < 2.5, f"three Tests took {elapsed:.2f}s: they waited for each other on the loop"
    for result in results:
        assert result["ok"] is False and result["smtp"] is None
        assert result["imap"]["ok"] is False and "timed out" in result["imap"]["error"]


@pytest.mark.asyncio
async def test_both_halves_of_the_test_connect_from_the_test_s_own_pool(monkeypatch):
    """Where each connection is opened: a thread of `_ACCOUNT_TEST_POOL`, never
    the loop's own thread, and not the default pool everything else shares."""
    import routes.email_routes as email_routes

    loop_thread = threading.current_thread()
    seen = {}

    def _open(host, port, **kwargs):
        seen["imap"] = threading.current_thread()
        return mock.MagicMock()

    def _smtp(*args, **kwargs):
        seen["smtp"] = threading.current_thread()
        return mock.MagicMock()

    monkeypatch.setattr(email_routes, "_open_imap_connection", _open)
    monkeypatch.setattr(email_routes.smtplib, "SMTP", _smtp)
    body = dict(_IMAP_ONLY, smtp_host="smtp.example.test", smtp_port=587, smtp_security="starttls")
    result = await _route()(req=_Req(body), owner="alice")

    assert result == {"ok": True, "imap": {"ok": True}, "smtp": {"ok": True}}
    for half in ("imap", "smtp"):
        assert seen[half] is not loop_thread, f"the {half} half connected on the event loop"
        assert seen[half].name.startswith("mail-test"), seen[half].name
