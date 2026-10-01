# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-06` end to end: in each mode, a probe from inside the real workstation
to a public host and to a private address gives the answer the mode promises —
as an account with `sudo` off, and as root with `sudo` on.

Nothing is faked. The shipped overlay (`docker/workstation.yml`) is started by
`docker compose` itself, so the gate's capabilities, the workstation's place in
the gate's network namespace and its missing CAP_NET_RAW are the file's, not a
copy of them. A LAN stands beside it: a network on 192.168.x with a web server
on it, joined to the namespace the way a host's LAN is reachable from a
container. This test is Pantheon: it pushes the admin's mode with the real
`sync_config`, and runs every probe through the daemon's own `exec`.

**What the probes say.** `reached`: a server answered. `blocked_here`: the
connection was refused inside the workstation at once (*No route to host*, the
rules' ICMP admin-prohibited, or *Operation not permitted*). The public host is
`PANTHEON_WORKSTATION_E2E_PUBLIC` (default `1.1.1.1:80`); where the machine
running this has no route to it even in *full*, the public half is skipped and
says so, rather than counted as a refusal the rules made.

Two more machines show the other two states the panel can report:
the daemon holding the mode for accounts itself (a container given
CAP_NET_ADMIN and no gate — what a VM is), which an agent with `sudo` lifts in
one command; and a workstation started without the gate (the overlay before
this row), which holds nothing.

Opt-in, like `test_the_workstation_image_is_a_real_ubuntu_machine.py`:

    PANTHEON_WORKSTATION_E2E=1 python -m pytest tests/test_the_workstation_network_holds_in_the_image.py

`PANTHEON_WORKSTATION_E2E_IMAGE=<tag>` uses an image already built.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pytest

from src import workstation_access as wa
from src import workstation_client as wc
from src.workstation_client import NetGateClient, WorkstationClient, account_for
from test_the_workstation_image_is_a_real_ubuntu_machine import (  # noqa: F401 — the fixture
    E2E_ENV, _docker, _docker_answers, image)
from workstation import protocol as P

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ENV = "PANTHEON_WORKSTATION_E2E_PUBLIC"
PUBLIC = os.environ.get(PUBLIC_ENV, "1.1.1.1:80")
LAN_DEVICE_HOST = 10
METADATA = "169.254.169.254:80"

pytestmark = pytest.mark.skipif(
    os.environ.get(E2E_ENV) != "1" or not _docker_answers(),
    reason=f"starts the workstation overlay: set {E2E_ENV}=1 where Docker answers")


def run(coro):
    return asyncio.run(coro)


PROBE = r'''
import errno, json, socket, sys, time
for arg in sys.argv[1:]:
    host, port = arg.rsplit(":", 1)
    s = socket.socket(); s.settimeout(4); t = time.monotonic()
    try:
        s.connect((host, int(port)))
        s.sendall(f"HEAD / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        line = s.recv(200).split(b"\r\n")[0].decode("latin-1")
        out = {"verdict": "reached", "answer": line}
    except OSError as e:
        n = getattr(e, "errno", None)
        out = {"verdict": "blocked_here" if n in (errno.EHOSTUNREACH, errno.EPERM, errno.EACCES)
               and time.monotonic() - t < 1 else "other", "why": f"{type(e).__name__}: {e}"}
    finally:
        s.close()
    out.update(target=arg, ms=int((time.monotonic() - t) * 1000))
    print(json.dumps(out), flush=True)
'''


def _compose(project: str, *argv: str, timeout: int = 300) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("COMPOSE_FILE",)}
    env["PGID"] = "4242"
    done = subprocess.run(["docker", "compose", "-p", project, "-f", "docker-compose.yml",
                           "-f", "docker/workstation.yml", *argv],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise AssertionError(f"docker compose {' '.join(argv)} failed: {done.stderr[-3000:]}")
    return done


def _ip(container: str, network: str) -> str:
    return _docker("inspect", container, "-f",
                   f"{{{{(index .NetworkSettings.Networks \"{network}\").IPAddress}}}}").stdout.strip()


def _lan_network(name: str) -> str:
    """A 192.168.x/24 nobody here uses yet: the owner's LAN, standing in."""
    for third in range(201, 251):
        subnet = f"192.168.{third}.0/24"
        done = _docker("network", "create", "--subnet", subnet, name, check=False)
        if done.returncode == 0:
            return f"192.168.{third}"
    raise AssertionError("no free 192.168.x/24 for the stand-in LAN")


@dataclass
class Stack:
    project: str
    gate: str            # container names
    workstation: str
    lan: str             # network name
    lan_prefix: str
    gate_ip: str
    tokens_dir: Path

    @property
    def lan_device(self) -> str:
        return f"{self.lan_prefix}.{LAN_DEVICE_HOST}:80"

    def client(self) -> WorkstationClient:
        token = _docker("exec", self.workstation, "cat",
                        f"{P.DEFAULT_PAIRING_DIR}/{P.TOKEN_FILENAME}").stdout.strip()
        return WorkstationClient(f"http://{self.gate_ip}:{P.DEFAULT_PORT}", token)


@pytest.fixture(scope="module")
def stack(image, tmp_path_factory):
    tag = secrets.token_hex(4)
    project = f"pantheon-ws-net-{tag}"
    for service in ("workstation", "workstation-net"):
        _docker("tag", image, f"{project}-{service}:latest")
    lan = f"{project}-lan"
    device = f"{project}-lan-device"
    try:
        _compose(project, "up", "-d", "--no-build", "--wait", "workstation")
        gate, ws = f"{project}-workstation-net-1", f"{project}-workstation-1"
        prefix = _lan_network(lan)
        _docker("run", "-d", "--name", device, "--network", lan, "--ip",
                f"{prefix}.{LAN_DEVICE_HOST}", "--entrypoint", "python3", image,
                "-m", "http.server", "80")
        _docker("network", "connect", lan, gate)
        tokens = tmp_path_factory.mktemp("gate-pairing")
        (tokens / P.TOKEN_FILENAME).write_text(_docker(
            "exec", gate, "cat", f"{P.DEFAULT_GATE_PAIRING_DIR}/{P.TOKEN_FILENAME}").stdout)
        yield Stack(project, gate, ws, lan, prefix, _ip(gate, f"{project}_default"), tokens)
    finally:
        _docker("rm", "-f", device, check=False)
        try:
            _compose(project, "down", "-v", "--remove-orphans", timeout=180)
        except AssertionError:
            pass
        _docker("network", "rm", lan, check=False)
        for service in ("workstation", "workstation-net"):
            _docker("image", "rm", f"{project}-{service}:latest", check=False)


@pytest.fixture
def admin(stack, monkeypatch):
    """The admin's settings, and Pantheon pointed at this stack's gate the way
    the overlay points it (`PANTHEON_WORKSTATION_NET_URL`, the pairing volume)."""
    values = {"workstation_sudo": False, "workstation_network": "full"}
    read = lambda key, default=None: values.get(key, default)  # noqa: E731
    monkeypatch.setattr(wa, "_setting", read)
    monkeypatch.setattr(wc, "_setting", read)
    monkeypatch.setenv(P.GATE_URL_ENV, f"http://{stack.gate_ip}:{P.GATE_PORT}")
    monkeypatch.setenv(P.GATE_PAIRING_DIR_ENV, str(stack.tokens_dir))
    return values


def _probe(client: WorkstationClient, account: str, targets: List[str], *, root: bool) -> Dict:
    run(client.write(account, "probe.py", PROBE))
    prefix = "sudo -n " if root else ""
    r = run(client.exec(account, f"{prefix}python3 ~/probe.py {' '.join(targets)}", timeout_s=60))
    assert r["exit_code"] == 0, r
    return {json.loads(line)["target"]: json.loads(line) for line in r["stdout"].splitlines()}


def _sync(admin, client, *, mode: str, sudo: bool) -> Dict:
    admin.update(workstation_network=mode, workstation_sudo=sudo)
    return run(wa.sync_config(client))


@pytest.fixture(scope="module")
def public_reachable(stack):
    """Whether this machine reaches the public host at all, asked in *full*
    from the gate itself: the half of the promise this place can measure."""
    run(NetGateClient(f"http://{stack.gate_ip}:{P.GATE_PORT}",
                      (stack.tokens_dir / P.TOKEN_FILENAME).read_text().strip()).set_mode("full"))
    done = _docker("exec", stack.gate, "python3", "-c", PROBE, PUBLIC, check=False)
    return '"reached"' in done.stdout


EXPECTED = {
    # mode: (public, private)
    "full": ("reached", "reached"),
    "internet": ("reached", "blocked_here"),
    "none": ("blocked_here", "blocked_here"),
}


@pytest.mark.parametrize("mode", P.NETWORK_MODES)
@pytest.mark.parametrize("as_root", [False, True], ids=["account-sudo-off", "root-sudo-on"])
def test_each_mode_gives_the_answer_it_promises(stack, admin, public_reachable, mode, as_root):
    client, ann = stack.client(), account_for("net-ann")
    daemon = _sync(admin, client, mode=mode, sudo=as_root)
    assert daemon["network_gate"]["mode"] == mode and daemon["sudo"] is as_root
    want_public, want_private = EXPECTED[mode]
    targets = [stack.lan_device, METADATA] + ([PUBLIC] if public_reachable else [])
    seen = _probe(client, ann, targets, root=as_root)
    assert seen[stack.lan_device]["verdict"] == want_private, seen
    if mode == "full":
        # Whether anything answers there depends on the machine; that the
        # workstation did not refuse it is what *full* promises.
        assert seen[METADATA]["verdict"] != "blocked_here", seen
    else:
        assert seen[METADATA]["verdict"] == "blocked_here", seen
    if want_private == "reached":
        assert seen[stack.lan_device]["answer"].startswith("HTTP/1.0 200"), seen
    if public_reachable:
        assert seen[PUBLIC]["verdict"] == want_public, seen
    elif mode == "none":
        assert _probe(client, ann, [PUBLIC], root=as_root)[PUBLIC]["verdict"] == "blocked_here"
    view = wa.network_view(mode, daemon)
    assert view["state"] == ("unrestricted" if mode == "full" else "enforced"), view


def test_the_public_half_was_measured_here(public_reachable):
    if not public_reachable:
        pytest.skip(f"{PUBLIC} is not reachable from here even in full; the public half of each "
                    "mode was not measured (set PANTHEON_WORKSTATION_E2E_PUBLIC)")


def test_root_in_the_workstation_cannot_open_the_gate(stack, admin):
    client, ann = stack.client(), account_for("net-ann")
    _sync(admin, client, mode="none", sudo=True)
    r = run(client.exec(ann, "sudo -n nft flush ruleset; echo rc=$?; "
                             "sudo -n nft delete table inet pantheon_workstation; echo rc=$?; "
                             "sudo -n python3 -c 'import socket; socket.socket(socket.AF_PACKET, "
                             "socket.SOCK_RAW, 768)'; echo rc=$?; "
                             "sudo -n unshare -n true; echo rc=$?"))
    assert [ln for ln in r["stdout"].split() if ln.startswith("rc=")] == ["rc=1"] * 4, r
    assert "Operation not permitted" in r["stderr"]
    seen = _probe(client, ann, [stack.lan_device], root=True)
    assert seen[stack.lan_device]["verdict"] == "blocked_here", seen
    gate = run(NetGateClient(f"http://{stack.gate_ip}:{P.GATE_PORT}", "").health())
    assert gate["mode"] == "none" and gate["self_test"] == "refused"


def test_the_workstation_holds_neither_capability_and_the_gate_only_its_own(stack):
    def caps(container: str) -> Dict[str, int]:
        status = _docker("exec", container, "cat", "/proc/1/status").stdout
        return {ln.split(":")[0]: int(ln.split()[1], 16) for ln in status.splitlines()
                if ln.startswith(("CapEff", "CapBnd"))}
    net_admin, net_raw, chown = 1 << 12, 1 << 13, 1 << 0
    ws, gate = caps(stack.workstation), caps(stack.gate)
    assert not ws["CapBnd"] & (net_admin | net_raw)
    assert gate["CapEff"] == gate["CapBnd"] == net_admin | chown
    ip = lambda c: _docker("exec", c, "python3", "-c",  # noqa: E731
                           "import socket; print(sorted(socket.if_nameindex()))").stdout
    assert ip(stack.workstation) == ip(stack.gate), "the workstation is not in the gate's namespace"


def test_the_gates_token_is_not_in_the_workstation(stack):
    client, ann = stack.client(), account_for("net-ann")
    r = run(client.exec(ann, f"sudo -n ls {P.DEFAULT_GATE_PAIRING_DIR}; echo rc=$?"))
    assert "rc=2" in r["stdout"] or "No such file" in r["stderr"], r


# ── the other two states: accounts only, and nothing ─────────────────────────

@dataclass
class Lone:
    name: str
    volume: str
    client: WorkstationClient


def _lone(stack, image, *, net_admin: bool) -> Lone:
    """A workstation on the stack's network and LAN with no gate in front of
    it: with CAP_NET_ADMIN (what a VM's root daemon has) or without (the
    overlay before `P20-06`)."""
    tag = secrets.token_hex(4)
    name, volume = f"{stack.project}-lone-{tag}", f"{stack.project}-lone-pairing-{tag}"
    argv = ["run", "-d", "--name", name, "--network", f"{stack.project}_default",
            "-v", f"{volume}:{P.DEFAULT_PAIRING_DIR}"]
    if net_admin:
        argv += ["--cap-add", "NET_ADMIN"]
    _docker(*argv, image, "--system", "ubuntu", "--bind", "0.0.0.0")
    _docker("network", "connect", stack.lan, name)
    ip = _ip(name, f"{stack.project}_default")
    for _ in range(100):
        done = _docker("exec", name, "cat", f"{P.DEFAULT_PAIRING_DIR}/{P.TOKEN_FILENAME}",
                       check=False)
        if done.returncode == 0 and done.stdout.strip():
            client = WorkstationClient(f"http://{ip}:{P.DEFAULT_PORT}", done.stdout.strip())
            try:
                run(client.health())
                return Lone(name, volume, client)
            except Exception:  # noqa: BLE001 — not answering yet
                pass
        time.sleep(0.2)
    raise AssertionError(_docker("logs", name, check=False).stdout[-2000:])


@pytest.fixture
def lone_with_net_admin(stack, image):
    lone = _lone(stack, image, net_admin=True)
    yield lone
    _docker("rm", "-f", lone.name, check=False)
    _docker("volume", "rm", "-f", lone.volume, check=False)


@pytest.fixture
def lone_without(stack, image):
    lone = _lone(stack, image, net_admin=False)
    yield lone
    _docker("rm", "-f", lone.name, check=False)
    _docker("volume", "rm", "-f", lone.volume, check=False)


def test_the_daemon_holds_it_for_accounts_and_sudo_lifts_it(stack, admin, lone_with_net_admin):
    """What a VM can do: an account is held, and root deletes the rule."""
    client, ann = lone_with_net_admin.client, account_for("net-bob")
    admin.update(workstation_network="internet", workstation_sudo=False)
    daemon = run(wa.sync_config(client))   # no gate in front of this one
    assert "network_gate" not in daemon
    assert (daemon["network_enforcement"], daemon["network_in_force"]) == ("accounts", "internet")
    assert wa.network_view("internet", daemon)["state"] == "enforced_sudo_off"
    assert _probe(client, ann, [stack.lan_device], root=False)[stack.lan_device]["verdict"] \
        == "blocked_here"
    admin.update(workstation_sudo=True)
    daemon = run(wa.sync_config(client))
    assert wa.network_view("internet", daemon)["state"] == "liftable"
    r = run(client.exec(ann, "sudo -n nft delete table inet pantheon_accounts; echo rc=$?"))
    assert "rc=0" in r["stdout"], r
    seen = _probe(client, ann, [stack.lan_device], root=False)
    assert seen[stack.lan_device]["verdict"] == "reached", "sudo did not lift it — say so"


def test_a_workstation_started_without_the_gate_holds_nothing_and_is_told_so(
        stack, admin, lone_without):
    client, ann = lone_without.client, account_for("net-cy")
    admin.update(workstation_network="internet", workstation_sudo=False)
    daemon = run(wa.sync_config(client))
    assert daemon["network"] == "internet" and daemon["network_enforcement"] == "none"
    assert wa.network_view("internet", daemon)["state"] == "needs_recreate"
    seen = _probe(client, ann, [stack.lan_device], root=False)
    assert seen[stack.lan_device]["verdict"] == "reached", \
        "the panel says not enforced, and it is not — the two agree"


def test_a_restarted_gate_fails_closed_and_the_workstation_comes_back_inside_it(stack, admin):
    """Last, because it restarts the gate. The gate's new namespace keeps the
    mode it had (kept in its volume); the workstation, left with loopback
    alone, exits and is restarted into it (`watch_namespace`) — and nothing in
    between reaches the LAN, because nothing in between has a way out."""
    client = stack.client()
    _sync(admin, client, mode="internet", sudo=False)
    _docker("restart", stack.gate, timeout=120)
    # A restart rejoins the networks it had; its address may move.
    stack.gate_ip = _ip(stack.gate, f"{stack.project}_default")
    gate = NetGateClient(f"http://{stack.gate_ip}:{P.GATE_PORT}", "")
    for _ in range(50):
        try:
            held = run(gate.health())
            break
        except Exception:  # noqa: BLE001 — still starting
            time.sleep(0.2)
    assert held["mode"] == "internet", "the restarted gate lost the admin's mode"

    def answers():
        try:
            return run(stack.client().health())
        except Exception:  # noqa: BLE001 — not back yet
            return None
    started = time.monotonic()
    while time.monotonic() - started < 90 and not answers():
        time.sleep(1)
    assert answers(), _docker("logs", "--tail", "20", stack.workstation, check=False).stdout
    log = _docker("logs", stack.workstation, check=False).stdout
    assert "nothing but loopback left" in log
    seen = _probe(stack.client(), account_for("net-ann"), [stack.lan_device], root=False)
    assert seen[stack.lan_device]["verdict"] == "blocked_here", seen
