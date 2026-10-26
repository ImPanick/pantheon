# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1526` — the routes' SMTP sender waited the whole 30 s to open.

`routes/email_helpers._send_smtp_message` — the send route, the scheduled-mail
poller, the reminder and alert mails — handed one `timeout=30` to
`smtplib.SMTP`/`SMTP_SSL` for connecting and sending alike, so a mail server
that accepts the connection and never greets was reported after half a minute.
`P23-07` split the IMAP opener (five seconds to open, the full timeout for the
reads after) and `B1230` the agent's own SMTP opener; this is the same split
for the routes' sender.

Driven against a real socket on loopback that completes the handshake and
says nothing — the shape of a server that is not answering — through the real
`_send_smtp_message`. A server that does greet keeps the caller's full timeout
for the sign-in and the send.
"""
from __future__ import annotations

import smtplib
import socket
import threading
import time

import pytest

import routes.email_helpers as eh


def _listener():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    return srv


@pytest.fixture()
def silent_server():
    """Accepts the TCP connection, then never sends a greeting."""
    srv = _listener()
    held, stop = [], threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(srv.accept()[0])
            except OSError:
                continue

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    try:
        yield srv.getsockname()[1]
    finally:
        stop.set()
        t.join(timeout=2)
        for c in held:
            c.close()
        srv.close()


@pytest.fixture()
def greeting_server():
    """Just enough SMTP to be opened and closed: a greeting, then 221 to QUIT."""
    srv = _listener()

    def serve():
        conn, _ = srv.accept()
        with conn:
            conn.sendall(b"220 ready\r\n")
            buf = b""
            while True:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                buf += chunk
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    if line.upper().startswith(b"QUIT"):
                        conn.sendall(b"221 bye\r\n")
                        return
                    conn.sendall(b"250 ok\r\n")

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        yield srv.getsockname()[1]
    finally:
        t.join(timeout=3)
        srv.close()


def _cfg(port, security="none"):
    # No user or password: a local relay, so `authenticate_smtp` signs in to
    # nothing and the only thing between connect and send is the greeting.
    return {"smtp_host": "127.0.0.1", "smtp_port": port, "smtp_security": security,
            "smtp_user": "", "smtp_password": ""}


def test_a_send_to_a_server_that_never_greets_fails_in_about_five_seconds(silent_server):
    """The row's `Verify:`, at the real numbers: the default 30 s timeout, and
    the five seconds the opener is given."""
    started = time.monotonic()
    with pytest.raises(OSError):
        eh._send_smtp_message(_cfg(silent_server), "me@example.test", ["you@example.test"], "hi")
    elapsed = time.monotonic() - started
    assert elapsed < 8, f"a send to a server that never greets took {elapsed:.1f}s"
    assert elapsed >= 4, f"gave up after {elapsed:.1f}s — before the five seconds it is owed"


def test_the_sentence_a_person_reads_names_the_server(silent_server):
    """What the send route shows for that failure (`P23-08`): unreachable, and where."""
    try:
        eh._send_smtp_message(_cfg(silent_server), "me@example.test", ["you@example.test"], "hi",
                              timeout=1)
    except OSError as e:
        said = eh._smtp_send_failure("127.0.0.1", silent_server, e)
    else:
        raise AssertionError("a server that never greets accepted a send")
    assert said == (f"Couldn't reach the mail server (127.0.0.1:{silent_server}). "
                    "Check the account's SMTP settings.")


def test_a_server_that_answers_keeps_the_full_timeout_for_the_send(greeting_server, monkeypatch):
    """The split is for opening only: a large attachment's DATA can be slow,
    and the send after the greeting must not inherit the short number."""
    seen = {}

    def sendmail(self, from_addr, to_addrs, msg, *a, **k):
        seen["timeout"] = self.sock.gettimeout()
        return {}

    monkeypatch.setattr(smtplib.SMTP, "sendmail", sendmail)
    eh._send_smtp_message(_cfg(greeting_server), "me@example.test", ["you@example.test"], "hi",
                          timeout=30)
    assert seen == {"timeout": 30}
