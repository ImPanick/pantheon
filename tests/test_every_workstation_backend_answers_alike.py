# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-07` — one protocol, every backend: the same cases against each one
that can start here.

`tests/helpers/workstation_conformance.py` holds the cases; this file starts
the backends and runs every case against every one of them, through Pantheon's
real client over a real socket:

  * **in-process** — `workstation/agentd.py` in this process
    (`tests/helpers/workstation_daemon.py`), the daemon every earlier test drives;
  * **remote-http** — `python3 -m workstation` as another process on **another
    address** (127.0.0.2), its token set through `PANTHEON_WORKSTATION_TOKEN`
    because a remote daemon has no pairing volume, `--backend` left to the
    daemon to work out;
  * **remote-https** — the same with `--tls-cert`/`--tls-key` from the
    certificate `workstation/install.py` makes, trusted by Pantheon by its
    pinned fingerprint (`PANTHEON_WORKSTATION_CERT_SHA256`);
  * **vm-host** — the VM backend's host (`workstation/vm.py`) on 127.0.0.3,
    forwarding every person's routes to a machine of their own. The machines
    here are `python3 -m workstation --backend vm` processes instead of QEMU
    guests (`LocalMachine`): everything between Pantheon and a machine's daemon
    — the token check, the forwarding, the per-machine tokens, streaming,
    hang-ups, reset as a new machine — is the shipped code; the hypervisor is
    what the opt-in `tests/test_the_workstation_vm_is_a_real_machine.py` adds.

Opt-in, because they need an image: **container-image** — the workstation
image itself, `--system ubuntu` as the overlay runs it (real Unix accounts, a
real display), when `PANTHEON_WORKSTATION_E2E=1` and
`PANTHEON_WORKSTATION_E2E_IMAGE` names a built image (see
`tests/test_the_workstation_image_is_a_real_ubuntu_machine.py`); a real VM runs
the same cases in `tests/test_the_workstation_vm_is_a_real_machine.py`.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.workstation_client import WorkstationClient
from tests.helpers.workstation_conformance import CASES, Backend, run
from tests.helpers.workstation_daemon import running_workstation
from workstation import install, vm
from workstation import protocol as P
from workstation.agentd import make_server

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "pws_conformance-token-for-every-backend"


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in (P.TOKEN_ENV, P.URL_ENV, P.PAIRING_DIR_ENV)}
    env.update(extra)
    return env


def start_cli(argv, *, token: str, address: str):
    """`python3 -m workstation …` as its own process; `(proc, port)` once it
    says where it listens."""
    proc = subprocess.Popen([sys.executable, "-m", "workstation", *argv, "--bind", address,
                             "--port", "0"], cwd=ROOT, env=_env(**{P.TOKEN_ENV: token}),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    line = proc.stdout.readline()
    m = re.search(rf"listening on {re.escape(address)}:(\d+)", line)
    if not m:
        proc.kill()
        raise AssertionError(f"the daemon did not start: {line}{proc.stdout.read()}")
    # Keep reading so a chatty log never fills the pipe.
    threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
    return proc, int(m.group(1))


def stop(proc) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


class LocalMachine(vm.Machine):
    """A person's "machine" for the VM host to forward to: the real daemon as
    its own process, with its own token and its own homes — the same five
    methods `QemuMachine` has, without the hypervisor."""

    def __init__(self, fleet: vm.Fleet, account: str) -> None:
        self.fleet, self.account = fleet, account
        self.dir = fleet.state / "machines" / account
        self.proc = None
        self.port = None
        self.token = ""

    def exists(self) -> bool:
        return (self.dir / "homes").is_dir()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.running():
            return
        (self.dir / "homes").mkdir(parents=True, exist_ok=True)
        self.token = vm.mint_machine_token(self.dir / "token")
        # An empty environment token, so `--token-file` is what it reads.
        self.proc, self.port = start_cli(
            ["--system", "single", "--backend", "vm", "--homes", str(self.dir / "homes"),
             "--token-file", str(self.dir / "token")], token="", address="127.0.0.1")

    def stop(self, *, graceful: bool = True) -> None:
        if self.proc is not None:
            stop(self.proc)
        self.proc = None

    def destroy(self) -> None:
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory):
    """The certificate `workstation/install.py` makes, for 127.0.0.2."""
    root = tmp_path_factory.mktemp("install-root")
    plan = install.Plan(dry_run=False, root=root)
    pin = install.make_certificate(plan, ["127.0.0.2", "workstation.test"])
    return plan.path(install.TLS_DIR / "cert.pem"), plan.path(install.TLS_DIR / "key.pem"), pin


def _unverified() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    return ctx


@pytest.fixture(scope="module", autouse=True)
def direct_to_the_other_addresses():
    """The other loopback addresses are reached directly, never through a
    proxy the shell running this may name in `HTTPS_PROXY` (httpx honours it,
    and its `NO_PROXY` does not read a `127.0.0.0/8` range)."""
    mp = pytest.MonkeyPatch()
    for var in ("NO_PROXY", "no_proxy"):
        mp.setenv(var, ",".join(filter(None, [os.environ.get(var, ""),
                                               "127.0.0.2", "127.0.0.3"])))
    yield
    mp.undo()


def _container_image(tmp):
    """The workstation image as the overlay runs it, on the host network."""
    tag = os.environ.get("PANTHEON_WORKSTATION_E2E_IMAGE", "").strip()
    if os.environ.get("PANTHEON_WORKSTATION_E2E") != "1" or not tag or not shutil.which("docker"):
        pytest.skip("the container image: set PANTHEON_WORKSTATION_E2E=1 and "
                    "PANTHEON_WORKSTATION_E2E_IMAGE to a built image")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    name = f"pantheon-conformance-{secrets.token_hex(4)}"
    pairing = tmp / "pairing"
    pairing.mkdir()
    subprocess.run(["docker", "run", "-d", "--name", name, "--network", "host", "--shm-size", "1g",
                    "-v", f"{pairing}:{P.DEFAULT_PAIRING_DIR}", tag, "--system", "ubuntu",
                    "--bind", "127.0.0.1", "--port", str(port)], check=True, capture_output=True)
    token = ""
    for _ in range(120):
        try:
            token = (pairing / P.TOKEN_FILENAME).read_text().strip()
            if token:
                break
        except OSError:
            pass
        time.sleep(0.5)
    return name, port, token


@pytest.fixture(scope="module", params=["in-process", "remote-http", "remote-https", "vm-host",
                                        "container-image"])
def backend(request, tmp_path_factory):
    name = request.param
    tmp = tmp_path_factory.mktemp(name)
    if name == "container-image":
        container, port, token = _container_image(tmp)
        try:
            for _ in range(120):
                try:
                    run(WorkstationClient(f"http://127.0.0.1:{port}", "").health())
                    break
                except Exception:  # noqa: BLE001 — not answering yet
                    time.sleep(0.5)
            yield Backend(name, f"http://127.0.0.1:{port}", token, kind="container",
                          has_display=True, port=port)
        finally:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        return
    if name == "in-process":
        with running_workstation(tmp, token=TOKEN) as ws:
            port = int(ws.url.rsplit(":", 1)[1])
            yield Backend(name, ws.url, TOKEN, kind="container", has_display=True, port=port)
        return
    if name.startswith("remote"):
        argv = ["--system", "single", "--homes", str(tmp / "homes")]
        tls = name == "remote-https"
        mp = pytest.MonkeyPatch()
        if tls:
            cert, key, pin = request.getfixturevalue("tls_files")
            argv += ["--tls-cert", str(cert), "--tls-key", str(key)]
            mp.setenv(P.TLS_PIN_ENV, pin)
        proc, port = start_cli(argv, token=TOKEN, address="127.0.0.2")
        scheme = "https" if tls else "http"
        try:
            yield Backend(name, f"{scheme}://127.0.0.2:{port}", TOKEN, kind="remote",
                          has_display=False, host="127.0.0.2", port=port,
                          tls=_unverified() if tls else None)
        finally:
            stop(proc)
            mp.undo()
        return
    fleet = vm.Fleet(tmp / "state", accel="tcg", need_image=False, machine_factory=LocalMachine,
                     start_timeout=60.0)
    server = make_server(fleet, TOKEN, bind="127.0.0.3", port=0,
                         station=vm.VmStation(fleet, TOKEN))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield Backend(name, f"http://127.0.0.3:{port}", TOKEN, kind="vm", has_display=False,
                      host="127.0.0.3", port=port)
    finally:
        server.shutdown()
        server.server_close()
        fleet.stop_all()
        for m in list(fleet._machines.values()):
            m.stop()


@pytest.mark.parametrize("case", CASES, ids=[c.__name__ for c in CASES])
def test_every_backend_answers_the_protocol_alike(backend, case):
    case(backend)
