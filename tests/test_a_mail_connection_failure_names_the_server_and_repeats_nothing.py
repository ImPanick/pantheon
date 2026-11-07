# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2032` — a mail connection that failed read back what the server sent.

The account form's Test (`POST /api/email/accounts/test`) connects to whatever
IMAP and SMTP host and port it is given and, when that failed, answered with
`str(e)` through `_friendly_email_auth_error`, which passed on anything it did
not recognise, cut to 200 characters. imaplib's greeting error quotes the
first line the server sent (`unexpected response: b'SSH-2.0-OpenSSH_9.6'`), and
so does smtplib's `SMTPConnectError` (`(-1, b'2.0-OpenSSH_9.6')`), so pointing
the form at any port on loopback or the LAN read back the banner of whatever
listened there. `GET /api/email/list` showed a saved account's the same way:
`Mail operation failed: unexpected response: b'SSH-2.0-…'`.

Now `_open_imap_connection` says a greeting that is not an IMAP server's in
its own words, once for every route that opens one; an SMTP server that does
not greet gets `P23-08`'s sentence (`_smtp_send_failure`); and a connection
that was refused, timed out or failed its TLS handshake gets one fixed
sentence each, naming the host and port that were typed. A timeout still says
"timed out", which the list's 504 reads. From upstream Odysseus 3d91ad82 and
4d0610a1 (#6355).

Driven through the real route handlers, imaplib and smtplib against loopback
sockets: one that answers as an SSH server does, one that answers with an
IMAP `BYE`, one that says nothing, and a port nobody listens on.
"""
from __future__ import annotations

import json
import smtplib
import socket
import threading

import pytest

import routes.email_helpers as eh
from tests.test_a_send_to_a_mail_server_that_is_not_there_fails_in_seconds import (  # noqa: F401
    _listener, silent_server,
)

#: What each server sends first, and a word of it that must not come back.
_BANNERS = {
    "ssh": (b"SSH-2.0-OpenSSH_9.6\r\n", "OpenSSH"),
    # A well-formed IMAP refusal: imaplib raises `IMAP4.error`, not `abort`.
    "bye": (b"* BYE internal-db 9.6 ready\r\n", "internal-db"),
}


@pytest.fixture(params=sorted(_BANNERS))
def banner_server(request):
    """Sends its banner to every connection, then waits, as SSH waits for the client's."""
    banner, quoted = _BANNERS[request.param]
    srv = _listener()
    held, stop = [], threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn = srv.accept()[0]
            except OSError:
                continue
            held.append(conn)
            conn.sendall(banner)

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    try:
        yield srv.getsockname()[1], quoted
    finally:
        stop.set()
        t.join(timeout=2)
        for c in held:
            c.close()
        srv.close()


@pytest.fixture()
def nobody_listens():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def endpoint(monkeypatch):
    import routes.email_routes as email_routes

    monkeypatch.setattr(email_routes, "_start_poller", lambda: None)
    # A server that never greets is given up on after a second, not five.
    monkeypatch.setattr(eh, "_IMAP_CONNECT_SECONDS", 1)
    monkeypatch.setattr(email_routes, "_MAIL_CONNECT_SECONDS", 1)
    router = email_routes.setup_email_routes()

    def find(method, path):
        for route in router.routes:
            if route.path == path and method in getattr(route, "methods", set()):
                return route.endpoint
        raise AssertionError(f"{method} {path} is not registered")

    return find


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _both_halves_at(port):
    return {"imap_host": "127.0.0.1", "imap_port": port, "imap_user": "me@example.test",
            "imap_password": "pw", "smtp_host": "127.0.0.1", "smtp_port": port,
            "smtp_security": "none"}


@pytest.mark.asyncio
async def test_the_account_test_names_a_server_that_is_not_a_mail_server_and_repeats_nothing(endpoint, banner_server):
    port, quoted = banner_server
    result = await endpoint("POST", "/api/email/accounts/test")(req=_Req(_both_halves_at(port)), owner="alice")

    assert result["ok"] is False
    for half in ("imap", "smtp"):
        assert result[half]["ok"] is False
        assert quoted not in result[half]["error"], (half, result[half]["error"])
    assert result["imap"]["error"] == f"The server at 127.0.0.1:{port} did not answer like an IMAP server."
    # `P23-08`'s sentence for an SMTP server that did not greet, said in one place.
    assert result["smtp"]["error"] == eh._smtp_send_failure("127.0.0.1", port, smtplib.SMTPConnectError(-1, b""))


@pytest.mark.asyncio
async def test_the_account_test_says_refused_or_timed_out_and_names_the_host_and_port(
        endpoint, silent_server, nobody_listens):
    test = endpoint("POST", "/api/email/accounts/test")
    silent = await test(req=_Req(_both_halves_at(silent_server)), owner="alice")
    refused = await test(req=_Req(_both_halves_at(nobody_listens)), owner="alice")

    for half in ("imap", "smtp"):
        assert silent[half]["error"] == (f"The server at 127.0.0.1:{silent_server} did not answer in time "
                                         "(timed out). Check the host and the port."), (half, silent)
        assert refused[half]["error"] == (f"The server at 127.0.0.1:{nobody_listens} refused the connection. "
                                          "Check the host and the port."), (half, refused)


@pytest.mark.asyncio
async def test_the_list_names_a_saved_server_that_is_not_a_mail_server_and_a_silent_one_is_still_a_timeout(
        endpoint, banner_server, silent_server, monkeypatch):
    port, quoted = banner_server
    saved = {"imap_host": "127.0.0.1", "imap_port": port, "imap_starttls": False,
             "imap_user": "me@example.test", "imap_password": "pw"}
    monkeypatch.setattr(eh, "_get_email_config", lambda *a, **k: dict(saved))
    listing = endpoint("GET", "/api/email/list")

    async def _list():
        r = await listing(folder="INBOX", limit=5, offset=0, filter="all", from_addr=None, account_id=None,
                          has_attachments=0, cached_only=0, cache_bust="b2032", owner="alice")
        return r.status_code, json.loads(r.body)

    status, body = await _list()
    assert status == 502, body
    assert quoted not in body["error"], body
    assert body["error"] == f"Mail operation failed: The server at 127.0.0.1:{port} did not answer like an IMAP server."

    saved["imap_port"] = silent_server
    status, body = await _list()
    assert status == 504, body
    assert body["error"] == "Mail operation failed: timed out", body
