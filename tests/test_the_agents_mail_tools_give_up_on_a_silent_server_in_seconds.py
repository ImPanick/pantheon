# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1230` — the agent's mail tools waited the whole read timeout to open.

`mcp_servers/email_server.py` handed `EMAIL_SOCKET_TIMEOUT` (20 s) to imaplib
and smtplib as the one timeout for everything, so a mail server that does not
answer was reported only after the full read timeout. `P23-07` split the
routes' opener (five seconds to open, the full timeout for the reads after);
this is the same split for the agent's own process.

Driven against a real socket on loopback that accepts the connection and never
greets — the shape of a server that is not answering — through the real
`_imap_connect` and `_smtp_connect`. The two timeouts are shortened so the
test is quick and the difference between them is still unmistakable: the old
code waits the read timeout (6 s here), the new one gives up at the connect
timeout. A server that does greet keeps the full timeout for its reads.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest

pytest.importorskip("mcp")

import mcp_servers.email_server as es  # noqa: E402

CONNECT = 0.5
READ = 6.0


@pytest.fixture()
def silent_server():
    """A listener that completes the TCP handshake and then says nothing."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    held = []
    stop = threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                held.append(conn)
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
def greeting_imap_server():
    """Just enough IMAP to open a session: a greeting and a CAPABILITY answer."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        with conn:
            conn.sendall(b"* OK ready\r\n")
            buf = b""
            while b"\r\n" not in buf:
                chunk = conn.recv(1024)
                if not chunk:
                    return
                buf += chunk
            tag = buf.split(b" ", 1)[0]
            conn.sendall(b"* CAPABILITY IMAP4rev1\r\n" + tag + b" OK done\r\n")
            time.sleep(1)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        yield srv.getsockname()[1]
    finally:
        t.join(timeout=3)
        srv.close()


@pytest.fixture()
def short_timeouts(monkeypatch):
    # `raising=False`: on the tree before `B1230` there is no connect timeout
    # to set, and the test must still run there and fail on the elapsed time.
    monkeypatch.setattr(es, "EMAIL_CONNECT_TIMEOUT", CONNECT, raising=False)
    monkeypatch.setattr(es, "EMAIL_SOCKET_TIMEOUT", READ)
    monkeypatch.setattr(es._mail_auth, "authenticate_imap", lambda conn, cfg: None)
    monkeypatch.setattr(es._mail_auth, "authenticate_smtp", lambda conn, cfg: None)


def _imap_cfg(port):
    return {"imap_ssl": False, "imap_host": "127.0.0.1", "imap_port": port,
            "imap_starttls": False}


def test_reading_mail_from_a_silent_server_fails_at_the_connect_timeout(
        silent_server, short_timeouts, monkeypatch):
    monkeypatch.setattr(es, "_load_config", lambda account=None: _imap_cfg(silent_server))
    started = time.monotonic()
    with pytest.raises((TimeoutError, OSError)):
        es._imap_connect()
    elapsed = time.monotonic() - started
    assert elapsed < CONNECT + 2.0, (
        f"opening IMAP on a server that never greets took {elapsed:.1f}s — "
        f"the read timeout ({READ}s), not the connect timeout ({CONNECT}s)")


def test_sending_mail_through_a_silent_server_fails_at_the_connect_timeout(
        silent_server, short_timeouts):
    cfg = {"smtp_host": "127.0.0.1", "smtp_port": silent_server,
           "smtp_security": "none", "smtp_user": "a@example.test",
           "smtp_password": "x", "account_name": "Test"}
    started = time.monotonic()
    with pytest.raises((TimeoutError, OSError)):
        es._smtp_connect(cfg=cfg)
    elapsed = time.monotonic() - started
    assert elapsed < CONNECT + 2.0, (
        f"opening SMTP on a server that never greets took {elapsed:.1f}s")


def test_a_server_that_answers_keeps_the_full_timeout_for_its_reads(
        greeting_imap_server, short_timeouts, monkeypatch):
    """The split is for opening only: a large mailbox's UID SEARCH can be slow,
    and the reads after the greeting must not inherit the short number."""
    monkeypatch.setattr(es, "_load_config",
                        lambda account=None: _imap_cfg(greeting_imap_server))
    conn = es._imap_connect()
    try:
        assert conn.sock.gettimeout() == READ
    finally:
        conn.shutdown()
