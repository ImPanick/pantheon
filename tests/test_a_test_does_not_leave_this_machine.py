# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1520` — a session-level guard refuses every connect past this machine.

Measured through the agent proxy's refusal log before this row:
`test_foreground_model_routing.py` made 20 HTTPS attempts to `backup`, `paid`
and `selected.example`, `test_a_chosen_temperature_reaches_a_local_model.py`
10, `test_the_meter_warns_before_the_stop.py` 1 and
`test_the_run_limits_are_said_before_it_runs.py` 2 to `api.example.com` — all
of them `src.model_context` asking an endpoint for its context window — and
each passed because the attempt failed.

`tests/conftest.py` now patches `socket.socket.connect`/`connect_ex`: loopback
is allowed, anything else — and the proxy the run was started under, which is
loopback here and the way out — is refused as `ConnectionRefusedError` naming
the test, and listed at the end of the run. The four files stub the lookup
(`tests/helpers/no_endpoint.py`) and make no attempt.
"""
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FOUR = ("tests/test_foreground_model_routing.py",
        "tests/test_a_chosen_temperature_reaches_a_local_model.py",
        "tests/test_the_meter_warns_before_the_stop.py",
        "tests/test_the_run_limits_are_said_before_it_runs.py")


@pytest.fixture
def guard(request):
    conftest = sys.modules["conftest"]
    yield conftest
    # The attempts this file makes on purpose are not the session's news.
    conftest._network["attempts"].pop(request.node.nodeid, None)


def test_a_connect_past_this_machine_is_refused_and_names_the_test(guard, request):
    with pytest.raises(ConnectionRefusedError) as refused:
        socket.create_connection(("192.0.2.10", 443), timeout=2)   # TEST-NET-1
    assert "B1520" in str(refused.value) and request.node.nodeid in str(refused.value)
    s = socket.socket()
    try:
        assert s.connect_ex(("198.51.100.7", 80)) != 0              # TEST-NET-2
    finally:
        s.close()
    assert guard._leaves_the_machine(("2001:db8::1", 443))
    assert guard.network_attempts()[request.node.nodeid] == ["192.0.2.10:443", "198.51.100.7:80"]


def test_a_loopback_server_is_reached(guard, request):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    threading.Thread(target=lambda: srv.accept()[0].close(), daemon=True).start()
    try:
        with socket.create_connection(srv.getsockname(), timeout=5):
            pass
    finally:
        srv.close()
    assert request.node.nodeid not in guard.network_attempts()


def test_the_proxy_the_run_started_under_is_the_way_out_and_is_refused(guard, monkeypatch):
    """Loopback by address, and still not allowed: a request through it reaches
    whoever the proxy dials. A proxy a test stands up later is its own fake."""
    monkeypatch.setattr(guard, "_EXIT_PROXIES", {("127.0.0.1", 46191)})
    assert guard._leaves_the_machine(("127.0.0.1", 46191))
    assert not guard._leaves_the_machine(("127.0.0.1", 46192))
    assert not guard._leaves_the_machine(("::1", 8080))
    assert not guard._leaves_the_machine("/run/a.sock")
    assert guard._leaves_the_machine(("selected.example", 443))
    assert not guard._leaves_the_machine(("localhost", 7000))


def test_the_four_files_make_no_attempt():
    """The row's `Verify:` — the four files, run under the guard, report zero."""
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *FOUR],
        cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-3000:]
    assert "B1520:" not in done.stdout, done.stdout[done.stdout.find("B1520:") - 200:][:3000]
