# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1595` — a server told to stop stops, whatever a client is holding open.

Found driving `tests/test_the_service_worker_controls_the_app.py` with the
server held to a tenth of a CPU: after SIGTERM the server logged *Shutting
down* and then answered `GET /login` 300 times in 84 s on one keep-alive
connection — the drive's probe — until the drive gave up and called the server
still up. uvicorn stops accepting at once and asks every open connection to
close, then waits for them with no bound; a connection it accepted at the
moment it was told to stop was not in that sweep, and a client that kept it
busy kept the server alive. `app.py` now gives the connections
`GRACEFUL_SHUTDOWN_SECONDS` and then closes them.

Driven out of process (`app_url`'s server, `Law 20`): a request whose body
never finishes is the deterministic form of "a client holding a connection",
and the server is stopped with it in flight. Without the bound it waited for
the 45 s request ceiling.
"""

import os
import signal
import socket
import time
from urllib.parse import urlparse

from test_the_command_palette_in_a_browser import SERVED, app_url  # noqa: F401,E402


def _alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            return "zombie" not in fh.read().lower()
    except OSError:
        return False


def test_a_sigterm_stops_the_server_while_a_request_is_held_open(app_url):  # noqa: F811
    import app as app_module   # the bound the server runs with, read from the module

    grace = app_module.GRACEFUL_SHUTDOWN_SECONDS
    assert 0 < grace < 45, "the bound has to come before the request ceiling, or it bounds nothing"
    u = urlparse(app_url)
    held = socket.create_connection((u.hostname, u.port), timeout=10)
    try:
        # Headers that promise a body, and the body's first byte only.
        held.sendall(b"POST /api/auth/login HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                     b"Content-Length: 4096\r\n\r\n{")
        time.sleep(1.0)
        pid = SERVED[app_url].pgid
        os.killpg(pid, signal.SIGTERM)
        started = time.monotonic()
        while _alive(pid) and time.monotonic() - started < grace + 20:
            time.sleep(0.25)
        took = time.monotonic() - started
    finally:
        held.close()
    assert not _alive(pid), f"the server was still running {took:.0f} s after SIGTERM"
    assert took < grace + 20, took
    log = (SERVED[app_url].data / "app.log").read_text(encoding="utf-8", errors="replace")
    assert "Shutting down" in log and "Finished server process" in log
