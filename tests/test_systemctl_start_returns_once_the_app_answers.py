# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B444`: the systemd unit calls Pantheon started when it answers, not when it forks.

`pantheon-ui.service` was `Type=simple` with nothing after `ExecStart`, so
`systemctl start` returned and `systemctl status` read `active (running)` for
the 35-60 s port 7000 refused every connection, and forever for a wedged boot.
Its `ExecStartPost=` now runs `scripts/pantheon-deploy wait-ready`, and the unit
stays `activating` until that returns.

There is no systemd here, so what is driven is everything around it: the wait
itself, as the unit runs it (a subprocess against a loopback server), the
unit's lines read as systemd reads them, and `install-service.sh` with a fake
`sudo` that records what it was asked. Unrun and only reasoned: that systemd
holds a `Type=simple` unit in `activating` until `ExecStartPost` exits (it does,
per `systemd.service(5)`), on a real host.
"""
import http.server
import os
import pathlib
import shlex
import stat
import subprocess
import sys
import threading

import pytest

from tests.helpers.cli_loader import load_script

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def pd():
    return load_script("pantheon-deploy")


# ── the wait ────────────────────────────────────────────────────────────────

def test_the_wait_polls_through_refusal_and_503_until_ready(pd):
    answers = iter([(0, "ConnectionRefusedError"), (503, ""),
                    (200, "<html>login</html>"), (200, '{"ready": true}')])
    slept = []
    clock = iter(range(100))
    waited = pd.wait_for_ready("http://x/api/ready", timeout=60, poll=2,
                               fetch=lambda url: next(answers), sleeper=slept.append,
                               clock=lambda: next(clock))
    assert slept == [2, 2, 2], "it polls; a login page is a 200 that is not ready"
    assert waited == 4


def test_a_start_that_never_gets_ready_fails_with_a_sentence(pd):
    clock = iter(range(0, 1000, 10))
    with pytest.raises(pd.DeployError) as e:
        pd.wait_for_ready("http://x/api/ready", timeout=30, poll=1,
                          fetch=lambda url: (503, ""), sleeper=lambda s: None,
                          clock=lambda: next(clock))
    assert "answered 503" in str(e.value) and "journalctl -u pantheon-ui" in str(e.value)


class _Ready(http.server.BaseHTTPRequestHandler):
    body = b'{"ready": true}'

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *a):
        pass


def _run_wait(url, timeout):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pantheon-deploy"), "wait-ready",
         "--url", url, "--timeout", str(timeout)],
        cwd=ROOT, capture_output=True, text=True, timeout=60)


def test_the_command_the_unit_runs_exits_0_on_ready_and_1_when_nothing_answers():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Ready)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        ok = _run_wait(f"http://127.0.0.1:{srv.server_port}/api/ready", 10)
    finally:
        srv.shutdown()
        srv.server_close()
    assert ok.returncode == 0, ok.stderr
    assert "ready after" in ok.stderr

    closed = _run_wait(f"http://127.0.0.1:{srv.server_port}/api/ready", 1)
    assert closed.returncode == 1
    assert "did not answer" in closed.stderr


# ── the unit, read as systemd reads it ──────────────────────────────────────

def _service_section():
    lines = (ROOT / "pantheon-ui.service").read_text(encoding="utf-8").splitlines()
    out, section = {}, None
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            section = line
            continue
        if section == "[Service]":
            key, _, value = line.partition("=")
            out.setdefault(key, []).append(value)
    return out


def test_the_unit_waits_for_ready_inside_its_start_timeout():
    svc = _service_section()
    assert svc["Type"] == ["simple"]
    post = shlex.split(svc["ExecStartPost"][0])
    assert post[0].startswith("/") and post[0].endswith("/python"), \
        "systemd needs an absolute executable; the venv's python runs the wait"
    assert post[1:3] == ["scripts/pantheon-deploy", "wait-ready"], post
    url = post[post.index("--url") + 1]
    wait = float(post[post.index("--timeout") + 1])
    start = shlex.split(svc["ExecStart"][0])
    port = start[start.index("--port") + 1]
    assert url == f"http://127.0.0.1:{port}/api/ready", "the wait asks the port ExecStart serves"
    assert wait < float(svc["TimeoutStartSec"][0]), \
        "the wait gives up (with its sentence) before systemd kills it"
    assert (ROOT / post[1]).exists(), "relative to WorkingDirectory, the checkout's root"


# ── install-service.sh ──────────────────────────────────────────────────────

def _install(tmp_path, start_rc):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "sudo.log"
    fake = bindir / "sudo"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> {shlex.quote(str(log))}\n'
        f'if [ "$1 $2" = "systemctl start" ]; then exit {start_rc}; fi\n'
        "exit 0\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin")
    proc = subprocess.run(["bash", str(ROOT / "install-service.sh")], env=env,
                          capture_output=True, text=True, timeout=30)
    return proc, log.read_text(encoding="utf-8").splitlines()


def test_the_installer_says_serving_only_when_start_returned(tmp_path):
    proc, calls = _install(tmp_path, start_rc=0)
    assert proc.returncode == 0, proc.stderr
    assert "Pantheon UI is serving" in proc.stdout
    assert calls.index("systemctl start pantheon-ui") < calls.index(
        "systemctl status pantheon-ui --no-pager")


def test_the_installer_fails_and_points_at_the_log_when_the_start_failed(tmp_path):
    proc, calls = _install(tmp_path, start_rc=1)
    assert proc.returncode == 1
    assert "did not come up" in proc.stdout and "journalctl -u pantheon-ui" in proc.stdout
    assert "Pantheon UI is serving" not in proc.stdout
