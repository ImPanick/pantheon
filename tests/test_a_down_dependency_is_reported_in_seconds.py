# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-10`, `PERF-U-7`, `PERF-U-8`): a dependency that is down is
reported in seconds, and a list that could not be read is not a 200.

Measured on `32df791` against the seeded install, the workstation on an address
that drops packets (10.255.255.1): `check` 10.0 s, `screen` 34.8 s, `status`
14.9 s; a mail server there: `unread-state` 30.0 s, `email/list` 30.0 s
answering **200** `{"emails": [], "error": "Mail operation failed: timed out"}`.
One timeout covered the connection and the answer.

Here an address that drops packets is a loopback listener whose accept queue is
full — Linux drops the SYN, so the connect waits exactly as it would for a host
that is not there — and every case drives the real code: the workstation client,
the IMAP opener, the real app's `/api/email/list`.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


class _Blackhole:
    """A port on 127.0.0.1 that accepts no new connection: its backlog is full."""

    def __enter__(self):
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(0)
        self.port = self.server.getsockname()[1]
        self.fill = []
        for _ in range(4):
            s = socket.socket()
            s.setblocking(False)
            try:
                s.connect(("127.0.0.1", self.port))
            except BlockingIOError:
                pass
            self.fill.append(s)
        time.sleep(0.2)
        return self

    def __exit__(self, *exc):
        for s in self.fill:
            s.close()
        self.server.close()
        return False


def test_a_workstation_that_is_not_there_is_reported_in_seconds():
    from src.workstation_client import WorkstationClient, WorkstationUnreachable

    async def ask(base):
        start = time.monotonic()
        with pytest.raises(WorkstationUnreachable) as caught:
            await asyncio.wait_for(WorkstationClient(base, "token").health(), 12)
        return time.monotonic() - start, caught.value.message

    with _Blackhole() as hole:
        base = f"http://127.0.0.1:{hole.port}"
        elapsed, sentence = asyncio.run(ask(base))
    assert elapsed < 5, f"reported after {elapsed:.1f}s"
    # `PERF-U-7`: the sentence a person reads, without the exception's class.
    assert sentence == f"The workstation at {base} did not answer. Is it running?"


def test_a_slow_answer_still_gets_the_calls_own_timeout():
    """The cap is on the connection only: an exec or a VM starting keeps its wait."""
    from src.workstation_client import _CONNECT_S, _timeouts

    t = _timeouts(120.0)
    assert (t.connect, t.read, t.write, t.pool) == (_CONNECT_S, 120.0, 120.0, 120.0)
    assert _timeouts(1.0).connect == 1.0


def test_a_mail_server_that_is_not_there_is_reported_in_seconds():
    from routes.email_helpers import _IMAP_CONNECT_SECONDS, _open_imap_connection

    with _Blackhole() as hole:
        start = time.monotonic()
        with pytest.raises(OSError):
            _open_imap_connection("127.0.0.1", hole.port, starttls=False, timeout=30)
        elapsed = time.monotonic() - start
    assert elapsed < _IMAP_CONNECT_SECONDS + 2, f"reported after {elapsed:.1f}s"


def test_once_connected_the_reads_keep_the_full_timeout():
    """A server that greets: the session's socket waits the configured timeout."""
    from routes.email_helpers import _open_imap_connection

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    import threading

    def greet():
        conn, _ = server.accept()
        conn.sendall(b"* OK IMAP4rev1 ready\r\n")
        # imaplib asks CAPABILITY on connect; answer its tag.
        tag = conn.recv(1024).split(b" ", 1)[0]
        conn.sendall(b"* CAPABILITY IMAP4rev1\r\n" + tag + b" OK done\r\n")
        time.sleep(1)
        conn.close()

    t = threading.Thread(target=greet)
    t.start()
    try:
        conn = _open_imap_connection("127.0.0.1", port, starttls=False, timeout=30)
        assert conn.sock.gettimeout() == 30
        conn.sock.close()
    finally:
        t.join()
        server.close()


_LIST_PROBE = textwrap.dedent(
    """
    import json, time
    import app as app_module
    from fastapi.testclient import TestClient
    PORT = __PORT__
    out = {}
    with TestClient(app_module.app) as client:
        r = client.post("/api/email/accounts", json={
            "name": "Not there", "imap_host": "127.0.0.1", "imap_port": PORT,
            "imap_user": "x@example.com", "imap_password": "pw", "smtp_host": "127.0.0.1",
            "smtp_port": PORT, "from_address": "x@example.com"})
        out["account"] = r.status_code
        t0 = time.perf_counter()
        r = client.get("/api/email/list", params={"folder": "INBOX", "limit": 5})
        out["list"] = [r.status_code, r.json(), round(time.perf_counter() - t0, 2)]
    print("RESULT " + json.dumps(out))
    """
)


def test_a_list_that_could_not_be_read_is_not_a_200(tmp_path):
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": "false", "CHROMADB_CONNECT_TIMEOUT": "0.01", "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9", "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path), "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(_REPO), "PYTHON_DOTENV_DISABLED": "1",
    })
    with _Blackhole() as hole:
        done = subprocess.run([sys.executable, "-c", _LIST_PROBE.replace("__PORT__", str(hole.port))],
                              cwd=_REPO, env=env, capture_output=True, text=True, timeout=240)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, done.stderr[-4000:]
    out = json.loads(line[len("RESULT "):])
    assert out["account"] == 200
    status, body, seconds = out["list"]
    assert status == 504, out
    assert body["emails"] == [] and body["error"], body
    assert seconds < 10, f"the list answered after {seconds}s"
