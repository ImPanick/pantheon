# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-07` end to end: the VM backend runs a real Ubuntu VM per person under
QEMU, and answers the protocol's conformance cases through Pantheon's client.

It builds the VM host's image (`workstation/vm.Dockerfile`), runs it the way
`docker/workstation-vm.yml` does — one device-cgroup rule for KVM, nothing
privileged — lets it make the machine image from Ubuntu's cloud image with
cloud-init, and drives it: the shared conformance cases
(`tests/helpers/workstation_conformance.py`), then what only a VM can show —
two people are two kernels, root in one machine sees nobody else's home, and
*Reset to clean* takes back what root did outside the home.

**Opt-in, and slow without KVM.** It runs only when Docker answers and
`PANTHEON_WORKSTATION_VM_E2E=1`. Making the image installs the desktop, the
tools and Firefox inside a VM: minutes with KVM, hours under TCG.

    PANTHEON_WORKSTATION_VM_E2E=1 python -m pytest tests/test_the_workstation_vm_is_a_real_machine.py

  PANTHEON_WORKSTATION_VM_E2E_IMAGE   a tag already built, instead of building
  PANTHEON_WORKSTATION_VM_E2E_STATE   a folder kept between runs, so the image is
                                      made once (default: a new temporary one)
  PANTHEON_WORKSTATION_VM_E2E_WAIT    seconds to wait for the image (default 4 h)
  PANTHEON_WORKSTATION_BUILD_CA, PANTHEON_WORKSTATION_APT_MIRROR
                                      as for the container image's end-to-end test;
                                      the CA and mirror also reach the machine image
  PANTHEON_WORKSTATION_VM_APT_PROXY   an apt proxy the machines can reach (from
                                      inside one, the host's loopback is 10.0.2.2)

None of it is written into an image: the knobs reach the machine image only
while it is made, and `vm-guest.sh` removes them before it is closed.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers import workstation_conformance as conf
from workstation import protocol as P
from workstation import vm

ROOT = Path(__file__).resolve().parent.parent
E2E_ENV = "PANTHEON_WORKSTATION_VM_E2E"
IMAGE_ENV = "PANTHEON_WORKSTATION_VM_E2E_IMAGE"
STATE_ENV = "PANTHEON_WORKSTATION_VM_E2E_STATE"
WAIT_ENV = "PANTHEON_WORKSTATION_VM_E2E_WAIT"
BUILD_CA_ENV = "PANTHEON_WORKSTATION_BUILD_CA"
MIRROR_ENV = "PANTHEON_WORKSTATION_APT_MIRROR"
PROXY_ENV = "PANTHEON_WORKSTATION_VM_APT_PROXY"
BUILT_TAG = "pantheon-workstation-vm:e2e-test"


def _docker_answers() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get(E2E_ENV) != "1" or not _docker_answers(),
    reason=f"builds and runs the VM backend: set {E2E_ENV}=1 where Docker answers")


def run(coro):
    return asyncio.run(coro)


def _docker(*argv, timeout=120, check=True) -> subprocess.CompletedProcess:
    done = subprocess.run(["docker", *argv], capture_output=True, text=True, timeout=timeout)
    if check and done.returncode != 0:
        raise AssertionError(f"docker {' '.join(argv[:3])}… failed: {done.stderr.strip()[-2000:]}")
    return done


@pytest.fixture(scope="module")
def image() -> str:
    tag = os.environ.get(IMAGE_ENV, "").strip()
    if tag:
        _docker("image", "inspect", tag)
        return tag
    argv = ["build", "--network", "host", "-f", str(ROOT / "workstation" / "vm.Dockerfile"),
            "-t", BUILT_TAG]
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        argv += ["--build-arg", f"HTTPS_PROXY={proxy}", "--build-arg", f"https_proxy={proxy}"]
    if os.environ.get(MIRROR_ENV):
        argv += ["--build-arg", f"APT_MIRROR={os.environ[MIRROR_ENV]}"]
    if os.environ.get(BUILD_CA_ENV):
        argv += ["--secret", f"id=build-ca,src={os.environ[BUILD_CA_ENV]}"]
    _docker(*argv, str(ROOT / "workstation"), timeout=3600)
    return BUILT_TAG


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def host(image):
    """The VM host as the overlay runs it, on the host network on a free port.
    `(url, token, name, state, timings)`."""
    state = os.environ.get(STATE_ENV, "").strip()
    kept = bool(state)
    state = Path(state or tempfile.mkdtemp(prefix="pantheon-vm-e2e-"))
    state.mkdir(parents=True, exist_ok=True)
    pairing = Path(tempfile.mkdtemp(prefix="pantheon-vm-pairing-"))
    name = f"pantheon-vm-e2e-{secrets.token_hex(4)}"
    port = _free_port()
    argv = ["run", "-d", "--name", name, "--network", "host",
            "--device-cgroup-rule", f"c {vm.KVM_MAJOR}:{vm.KVM_MINOR} rwm",
            "-v", f"{state}:{vm.DEFAULT_STATE}", "-v", f"{pairing}:{P.DEFAULT_PAIRING_DIR}",
            "-e", f"{vm.ENV['memory']}=1536", "-e", "PANTHEON_WORKSTATION_PAIRING_GID=4242"]
    if os.environ.get(MIRROR_ENV):
        argv += ["-e", f"{vm.ENV['apt_mirror']}={os.environ[MIRROR_ENV]}"]
    if os.environ.get(PROXY_ENV):
        argv += ["-e", f"{vm.ENV['apt_proxy']}={os.environ[PROXY_ENV]}"]
    if os.environ.get(BUILD_CA_ENV):
        argv += ["-v", f"{os.environ[BUILD_CA_ENV]}:/run/provision-ca.crt:ro",
                 "-e", f"{vm.ENV['apt_ca']}=/run/provision-ca.crt"]
    _docker(*argv, image, "--bind", "127.0.0.1", "--port", str(port))
    url = f"http://127.0.0.1:{port}"
    timings = {}
    try:
        started = time.monotonic()
        token = ""
        while time.monotonic() - started < 60 and not token:
            try:
                token = (pairing / P.TOKEN_FILENAME).read_text().strip()
            except OSError:
                time.sleep(0.5)
        assert token, "the VM host minted no token"
        limit = float(os.environ.get(WAIT_ENV) or 4 * 3600)
        state_now = None
        while time.monotonic() - started < limit:
            try:
                state_now = run(WorkstationClient(url, token).health())["machine"]["image"]
            except WorkstationError:
                state_now = None
            if state_now in ("ready", "failed"):
                break
            time.sleep(10)
        timings["image_s"] = round(time.monotonic() - started, 1)
        logs = _docker("logs", name, check=False)
        assert state_now == "ready", f"image {state_now}: {(logs.stdout + logs.stderr)[-3000:]}"
        yield url, token, name, state, timings
    finally:
        _docker("stop", "-t", "150", name, timeout=200, check=False)
        _docker("rm", "-f", name, check=False)
        shutil.rmtree(pairing, ignore_errors=True)
        if not kept:
            shutil.rmtree(state, ignore_errors=True)


@pytest.fixture(scope="module")
def shared(host):
    """One person, used by every case that does not need a person nobody has
    used yet — each new person is a VM boot."""
    url, token, *_ = host
    account = account_for(f"vm-e2e-{secrets.token_hex(3)}")
    started = time.monotonic()
    run(_client(host).ensure(account))
    host[4]["first_ensure_s"] = round(time.monotonic() - started, 1)
    backend = conf.Backend("vm-qemu", url, token, kind="vm", has_display=True,
                           port=int(url.rsplit(":", 1)[1]))
    backend.fresh = lambda: account  # type: ignore[method-assign]
    return backend


SHARED_CASES = [c for c in conf.CASES if c not in (conf.looking_makes_nothing,
                                                    conf.ensure_makes_the_home_once,
                                                    conf.reset_puts_the_home_back)]


@pytest.mark.parametrize("case", SHARED_CASES, ids=[c.__name__ for c in SHARED_CASES])
def test_a_real_vm_answers_the_protocol_like_every_backend(shared, case):
    case(shared)


def test_a_person_nobody_has_used_is_looked_at_without_a_machine_starting(host):
    url, token, name, state, timings = host
    b = conf.Backend("vm-qemu", url, token, kind="vm", has_display=True)
    conf.looking_makes_nothing(b)  # ends with this person's machine made and answering
    assert (state / "machines").is_dir()


def _client(host) -> WorkstationClient:
    url, token, *_ = host
    c = WorkstationClient(url, token, timeout=60)
    run(c.health())  # so the client knows machines start, and waits for one
    return c


def _boot_id(c, account) -> str:
    return run(c.exec(account, "cat /proc/sys/kernel/random/boot_id"))["stdout"].strip()


def test_two_people_are_two_kernels_and_root_in_one_sees_only_its_own_home(host, shared):
    c = _client(host)
    ann = shared.fresh()
    bob = account_for(f"vm-e2e-bob-{secrets.token_hex(3)}")
    started = time.monotonic()
    run(c.ensure(bob))
    host[4]["second_machine_s"] = round(time.monotonic() - started, 1)
    run(c.write(bob, "secret.txt", "bob's"))
    assert _boot_id(c, ann) != _boot_id(c, bob)
    was = run(c.health())["sudo"]
    try:
        run(c.config(sudo=True))
        seen = run(c.exec(ann, "sudo -n ls /home; sudo -n find / -name secret.txt "
                               "-path '*/home/*' 2>/dev/null"))
        assert seen["exit_code"] == 0, seen
        assert ann in seen["stdout"] and bob not in seen["stdout"]
        assert "secret.txt" not in seen["stdout"]
    finally:
        run(c.config(sudo=was))
    facts = run(c.health())["machine"]
    assert facts["accel"] in P.ACCELS and facts["image"] == "ready"
    inside = run(c.exec(ann, "systemd-detect-virt || true"))["stdout"].strip()
    assert inside == ("kvm" if facts["accel"] == "kvm" else "qemu")


def test_reset_is_a_fresh_machine_not_only_a_fresh_home(host, shared):
    c = _client(host)
    account = shared.fresh()
    was = run(c.health())["sudo"]
    try:
        run(c.config(sudo=True))
        run(c.exec(account, "sudo -n touch /etc/root-was-here && echo junk > ~/junk.txt"))
        before = _boot_id(c, account)
        started = time.monotonic()
        assert run(c.reset(account)) == {"account": account, "reset": True}
        host[4]["reset_s"] = round(time.monotonic() - started, 1)
        assert _boot_id(c, account) != before
        r = run(c.exec(account, "test -e /etc/root-was-here; echo $?; ls ~"))
        assert r["stdout"].split()[0] == "1", "what root did outside the home survived the reset"
        with pytest.raises(WorkstationError) as e:
            run(c.read(account, "junk.txt"))
        assert e.value.code == "not_found"
    finally:
        run(c.config(sudo=was))
    print(json.dumps({"timings_s": host[4]}))


def test_the_installer_sets_up_a_remote_workstation_on_real_ubuntu(host, shared):
    """`workstation/install.py` where it is meant to run — Ubuntu 24.04 with
    systemd and its own `openssl` — inside a person's machine: the files, the
    token and certificate, a unit `systemd-analyze verify` accepts, and the
    daemon that unit describes started by systemd (as a transient unit on
    another port, so the machine's own daemon is untouched), answering the
    installer's own pinned health check as `remote`. Under a root of its own
    (`--root`), so nothing of the machine's real `/etc` is changed."""
    c = _client(host)
    account = shared.fresh()
    src = ROOT / "workstation"
    for path in sorted(src.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith(".pyc"):
            run(c.write(account, f"src/workstation/{path.relative_to(src)}", path.read_bytes()))
    was = run(c.health())["sudo"]
    try:
        run(c.config(sudo=True))
        out = run(c.exec(account, "sudo -n python3 ~/src/workstation/install.py --root /tmp/inst "
                                  "--no-packages --no-start --address 127.0.0.1 --name 127.0.0.1",
                         timeout_s=300))
        assert out["exit_code"] == 0, out
        lines = dict(ln.strip().split("=", 1) for ln in out["stdout"].splitlines()
                     if ln.startswith("      ") and "=" in ln)
        assert lines[P.URL_ENV] == "https://127.0.0.1:7040" and lines[P.TLS_PIN_ENV]
        unit = "/tmp/inst/etc/systemd/system/pantheon-workstation.service"
        verify = run(c.exec(account, f"sudo -n systemd-analyze verify {unit}"))
        assert verify["exit_code"] == 0, verify
        # What systemd would run, rooted under /tmp/inst, on 7041, as `single`
        # so it makes no Unix accounts beside the machine's own daemon.
        script = (
            "import shlex, subprocess; "
            f"line = [l for l in open('{unit}') if l.startswith('ExecStart=')][0]; "
            "argv = shlex.split(line.split('=', 1)[1]); "
            "argv = ['/tmp/inst' + a if a.startswith(('/etc/', '/opt/')) else a for a in argv]; "
            "argv[argv.index('--port') + 1] = '7041'; argv[argv.index('--bind') + 1] = '127.0.0.1'; "
            "argv[argv.index('--system') + 1] = 'single'; argv += ['--homes', '/tmp/inst/home']; "
            "subprocess.run(['systemd-run', '--unit', 'pws-remote-e2e', "
            "'--property=WorkingDirectory=/tmp/inst/opt/pantheon-workstation', *argv], check=True)")
        started = run(c.exec(account, f"sudo -n python3 -c {shlex.quote(script)}"))
        assert started["exit_code"] == 0, started
        probe = ("import sys, json; sys.path.insert(0, '/tmp/inst/opt/pantheon-workstation'); "
                 "from workstation import install; "
                 f"a = install.check(7041, tls=True, pin={lines[P.TLS_PIN_ENV]!r}, "
                 f"token={lines[P.TOKEN_ENV]!r}, wait=120); print(json.dumps(a))")
        answer = run(c.exec(account, f"sudo -n python3 -c {shlex.quote(probe)}", timeout_s=200))
        assert answer["exit_code"] == 0, answer
        health = json.loads(answer["stdout"].strip().splitlines()[-1])
        assert health["backend"] == "remote"
        assert health["machine"]["virtualization"] in ("kvm", "qemu")
        status = run(c.exec(account, "systemctl show -p ActiveState pws-remote-e2e"))
        assert "ActiveState=active" in status["stdout"]
    finally:
        run(c.exec(account, "sudo -n systemctl stop pws-remote-e2e 2>/dev/null; "
                            "sudo -n rm -rf /tmp/inst; true"))
        run(c.config(sudo=was))


# ── `B992`, `B984`: written for a real VM, not run where they were written ───
# (no machine image there: making one is 33-67 min of TCG; see `ws-vm2`'s
# handoff). Each restores what it changed.

_PROBE = """
import errno, socket
for host, port in (("1.1.1.1", 443), ("10.0.2.2", {port}), ("192.168.1.1", 80)):
    s = socket.socket(); s.settimeout(8)
    print(host, s.connect_ex((host, port)))
"""


def _probe(c, account, port) -> dict:
    out = run(c.exec(account, _PROBE.format(port=port), shell="python", timeout_s=120))
    assert out["exit_code"] == 0, out
    return {ln.split()[0]: int(ln.split()[1]) for ln in out["stdout"].splitlines() if ln.strip()}


def test_none_refuses_a_public_and_a_private_probe_from_inside_a_machine(host, shared):
    """`B992`'s `Verify:`. `10.0.2.2` is QEMU's alias for the VM host's own
    loopback, where its port answers: reached under *full*, so its refusal
    under *none* is the rule's and not a closed port. Under `restrict=on` a
    connection is answered with a reset by QEMU itself (libslirp)."""
    c = _client(host)
    account = shared.fresh()
    port = int(host[0].rsplit(":", 1)[1])
    before = run(c.health())
    was, was_sudo = before["network"], before["sudo"]
    try:
        run(c.config(network="full"))
        assert _probe(c, account, port)["10.0.2.2"] == 0, "premise: the private probe answers"
        run(c.config(network="none"))
        codes = _probe(c, account, port)        # the machine restarts with restrict=on first
        assert all(code != 0 for code in codes.values()), codes
        health = run(c.health())
        assert (health["network_in_force"], health["network_enforcement"]) == ("none",
                                                                                "hypervisor")
        # As root, too: the rule is outside the machine.
        run(c.config(sudo=True))
        root = run(c.exec(account, "sudo -n nft flush ruleset; sudo -n python3 -c "
                                   + shlex.quote(_PROBE.format(port=port)), timeout_s=120))
        codes = [int(ln.split()[1]) for ln in root["stdout"].splitlines() if len(ln.split()) == 2]
        assert len(codes) == 3 and all(code != 0 for code in codes), root
    finally:
        run(c.config(network=was, sudo=was_sudo))


def test_a_machine_clock_pushed_off_is_brought_back_to_the_hosts(host, shared):
    """`B984`: root in the machine moves its clock 30 s ahead; within a sync
    period the host has stepped it back to its own, within a second."""
    c = _client(host)
    account = shared.fresh()
    was = run(c.health())["sudo"]
    try:
        run(c.config(sudo=True))
        run(c.exec(account, "sudo -n date -s @$(( $(date +%s) + 30 )) >/dev/null"))
        deadline = time.monotonic() + vm.CLOCK_SYNC_S + vm.HOUSEKEEPING_S + 60
        offset = None
        while time.monotonic() < deadline:
            t0 = time.time()
            got = float(run(c.exec(account, "date +%s.%N"))["stdout"])
            t1 = time.time()
            offset = got - (t0 + t1) / 2
            if abs(offset) < 1.0:
                break
            time.sleep(10)
        assert offset is not None and abs(offset) < 1.0, offset
    finally:
        run(c.config(sudo=was))
