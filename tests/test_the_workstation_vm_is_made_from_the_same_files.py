# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-07` — the VM backend, without the hypervisor: what each machine is
made from, how it is started, and the wall between two of them.

The parts of `workstation/vm.py` that do not need QEMU to be proven, driven:

  * **the same files, not a fork** (`Law 14`): the cloud-init seed that makes
    the machine image carries `provision.sh`, Firefox's policy, Mozilla's key and
    the skeleton byte for byte from `workstation/`, parsed back with PyYAML (what
    cloud-init reads it with); the container image's `Dockerfile` runs the same
    `provision.sh`; no token is in the image, ever;
  * **what decides an image**: a provisioning change makes a new one, a code
    change does not (code reaches every machine on its app disk at each start);
  * **KVM when it opens, TCG with the reason when not**, the device node made
    when absent; QEMU's command line for each (no display device, no default
    devices, one port forwarded to loopback only);
  * **a token per machine**: none is Pantheon's, each machine refuses another's,
    and the VM host refuses them all — driven against real daemons;
  * **the image's state reaches `health`** and a person's call is refused with a
    sentence while it is being made or after it failed;
  * the console's last word decides whether the image is ready;
  * **the compose overlay**, as compose resolves it: one device-cgroup rule for
    KVM alone, not privileged, no socket, no capability, no published port; the
    same service name, address and pairing as the container's overlay, so
    switching is one `.env` line; and the remote overlay demands the address
    and token with a sentence rather than starting misconfigured.
"""
from __future__ import annotations

import asyncio
import base64
import errno
import json
import os
import shutil
import stat
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.test_every_workstation_backend_answers_alike import LocalMachine
from workstation import protocol as P
from workstation import service, vm
from workstation.agentd import WorkstationError as DaemonError
from workstation.agentd import make_server

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "workstation"
TOKEN = "pws_the-vm-hosts-own-token-for-pantheon"


def run(coro):
    return asyncio.run(coro)


def _seed(**kw) -> dict:
    text = vm.image_user_data(PKG, **kw)
    assert text.startswith("#cloud-config\n")
    as_yaml = yaml.safe_load(text)
    assert as_yaml == json.loads(text.split("\n", 1)[1])  # JSON is YAML: one document
    return as_yaml


def _files(seed: dict) -> dict:
    return {f["path"]: (base64.b64decode(f["content"]), f["permissions"], f["owner"])
            for f in seed["write_files"]}


# ── the same files ───────────────────────────────────────────────────────────

def test_the_image_is_provisioned_with_the_container_images_own_files():
    files = _files(_seed())
    for rel in ("provision.sh", "vm-guest.sh", "firefox/policies.json",
                "firefox/packages.mozilla.org.asc", "skel/.jwmrc", "skel/.Xdefaults"):
        data, mode, owner = files[f"{vm.PROVISION_DIR}/{rel}"]
        assert data == (PKG / rel).read_bytes(), rel
        assert owner == "root:root" and mode == ("0755" if rel.endswith(".sh") else "0644")
    # Every file under the two folders, not a list someone keeps.
    for path in (PKG / "skel").rglob("*"):
        assert f"{vm.PROVISION_DIR}/skel/{path.name}" in files


def test_the_container_image_runs_the_same_provisioning_script():
    """One list of what a workstation has (`Law 14`): the Dockerfile's apt step
    is `provision.sh packages`, not a list of its own."""
    lines = [ln.strip() for ln in (PKG / "Dockerfile").read_text().splitlines()]
    runs = [ln for ln in lines if ln.startswith("RUN ") or ln.startswith("sh ")]
    assert any("provision.sh packages --image" in ln for ln in runs)
    assert any("provision.sh files --skel /etc/skel" in ln for ln in runs)
    assert not any("apt-get install" in ln for ln in lines), "a second package list"
    assert "xvfb jwm xterm xdotool scrot" in (PKG / "provision.sh").read_text()


def test_the_seed_runs_the_guest_script_then_powers_off_and_lets_nobody_in():
    seed = _seed()
    assert seed["runcmd"] == [["sh", f"{vm.PROVISION_DIR}/vm-guest.sh", "bake"]]
    assert seed["power_state"]["mode"] == "poweroff"
    assert seed["users"] == [] and seed["disable_root"] is True and seed["ssh_pwauth"] is False
    assert seed["package_update"] is False and seed["apt"] == {"preserve_sources_list": True}
    unit = _files(seed)[f"{vm.PROVISION_DIR}/pantheon-workstation.service"][0].decode()
    assert unit == vm.guest_unit()


def test_no_token_is_ever_in_the_image(tmp_path):
    text = vm.image_user_data(PKG, apt_mirror="https://mirror.test/ubuntu",
                              apt_proxy="http://10.0.2.2:3142", apt_ca=b"-----CA-----")
    assert P.TOKEN_PREFIX not in text and "token" not in json.dumps(
        [f["path"] for f in _seed()["write_files"]])
    files = _files(yaml.safe_load(text))
    env, mode, _ = files[f"{vm.PROVISION_DIR}/provision.env"]
    assert mode == "0600"
    assert env.decode().splitlines() == [
        "APT_MIRROR=https://mirror.test/ubuntu", "APT_PROXY=http://10.0.2.2:3142",
        f"PROVISION_CA={vm.PROVISION_DIR}/provision-ca.crt"]
    assert files[f"{vm.PROVISION_DIR}/provision-ca.crt"][0] == b"-----CA-----"
    # …and without the knobs, no environment file at all.
    assert f"{vm.PROVISION_DIR}/provision.env" not in _files(_seed())


def test_each_machine_runs_the_daemon_from_its_app_disk_with_its_own_token():
    unit = vm.guest_unit()
    exec_line = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    from workstation import __main__ as cli
    import shlex
    argv = shlex.split(exec_line.split("=", 1)[1])
    args = cli.parse_args(argv[3:])
    assert (args.system, args.backend, args.bind, args.port) == ("ubuntu", "vm", "0.0.0.0",
                                                                 P.DEFAULT_PORT)
    assert args.token_file == f"{vm.APP_MOUNT}/token" and args.tls_cert is None
    assert f"WorkingDirectory={vm.APP_MOUNT}" in unit.splitlines()
    assert f"RequiresMountsFor={vm.APP_MOUNT}" in unit.splitlines()
    # The guest script mounts the app disk by the label the host gives it, there.
    guest = (PKG / "vm-guest.sh").read_text()
    assert f"LABEL={vm.APP_LABEL}" in guest and f"APP={vm.APP_MOUNT}" in guest
    assert vm.IMAGE_READY in guest and vm.IMAGE_FAILED in guest


def test_the_remote_and_vm_units_are_one_unit_with_different_parameters():
    from workstation import install
    remote = install.remote_unit(port=7040, bind="0.0.0.0", tls=True).splitlines()
    guest = vm.guest_unit().splitlines()
    shared = {ln for ln in remote if not ln.startswith(("ExecStart=", "Description=",
                                                         "WorkingDirectory=", "#"))}
    assert shared <= set(guest)
    with pytest.raises(ValueError):
        service.exec_argv(backend="cloud", token_file="/t")
    with pytest.raises(ValueError):
        service.exec_argv(backend="remote", token_file="/t", tls_cert="/c")


# ── what decides an image ────────────────────────────────────────────────────

def _payload_copy(tmp_path) -> Path:
    dest = tmp_path / "payload"
    shutil.copytree(PKG, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def test_a_provisioning_change_makes_a_new_image_and_a_code_change_does_not(tmp_path):
    payload = _payload_copy(tmp_path)
    first = vm.payload_digest(payload, "base-digest")
    (payload / "agentd.py").write_text("# changed\n")
    assert vm.payload_digest(payload, "base-digest") == first
    assert vm.payload_digest(payload, "another-base") != first
    for rel in ("provision.sh", "skel/.jwmrc", "firefox/policies.json"):
        before = vm.payload_digest(payload, "base-digest")
        with open(payload / rel, "a") as f:
            f.write("\n")
        assert vm.payload_digest(payload, "base-digest") != before, rel


def test_an_image_already_made_for_this_payload_is_used(tmp_path):
    base = tmp_path / "base.img"
    base.write_bytes(b"not really an image")
    fleet = vm.Fleet(tmp_path / "state", accel="tcg", base_image=base, payload=PKG)
    assert fleet.image_state == "preparing"
    digest = vm.payload_digest(PKG, fleet._base_digest())
    image = fleet.state / "images" / f"image-{digest[:16]}.qcow2"
    image.write_bytes(b"made earlier")
    fleet.prepare_image()
    assert (fleet.image_state, fleet.current_image()) == ("ready", image)
    # The base image is hashed once, then remembered by size and time.
    cache = (fleet.state / "images" / "base.sha256").read_text().split()
    assert cache[1] == fleet._base_digest()


def test_a_failure_to_make_the_image_is_said_not_raised(tmp_path, monkeypatch):
    base = tmp_path / "base.img"
    base.write_bytes(b"x")
    fleet = vm.Fleet(tmp_path / "state", accel="tcg", base_image=base, payload=PKG)

    def broken(argv):
        raise DaemonError("unavailable", "qemu-img failed: no space left on device")

    monkeypatch.setattr(vm.shutil, "disk_usage",
                        lambda p: shutil._ntuple_diskusage(100 * 10**9, 10 * 10**9, 90 * 10**9))
    monkeypatch.setattr(fleet, "run", broken)
    fleet.prepare_image()
    # The tool's own sentence, as it said it — not a type name and a repr.
    assert fleet.image_state == "failed"
    assert fleet.image_why == "qemu-img failed: no space left on device"
    with pytest.raises(DaemonError) as e:
        fleet.ready(account_for("ann"))
    assert "could not be made" in e.value.message and "no space left" in e.value.message


@pytest.mark.parametrize("console,verdict", [
    ("boot…\nvm-guest: PANTHEON-WORKSTATION-IMAGE-READY\n", True),
    ("vm-guest: PANTHEON-WORKSTATION-IMAGE-FAILED\n", False),
    ("PANTHEON-WORKSTATION-IMAGE-FAILED\n…\nPANTHEON-WORKSTATION-IMAGE-READY\n", True),
    ("PANTHEON-WORKSTATION-IMAGE-READY\n…\nPANTHEON-WORKSTATION-IMAGE-FAILED\n", False),
    ("[  12.0] reached target Power-Off\n", None),
])
def test_the_consoles_last_word_decides_the_image(tmp_path, console, verdict):
    path = tmp_path / "console.log"
    path.write_text(console)
    assert vm.read_verdict(path) is verdict
    assert vm.read_verdict(tmp_path / "missing.log") is None


# ── KVM or TCG ───────────────────────────────────────────────────────────────

def test_kvm_when_the_device_opens(tmp_path):
    dev = tmp_path / "kvm"
    dev.write_bytes(b"")
    assert vm.choose_accel(dev) == ("kvm", f"KVM: {dev} opened.")


def test_a_missing_node_is_made_then_opened(tmp_path):
    dev = tmp_path / "kvm"
    made = []

    def mknod(path, mode, device):
        made.append((path, stat.S_ISCHR(mode), os.major(device), os.minor(device)))
        Path(path).write_bytes(b"")  # what the node would be, for the open

    assert vm.choose_accel(dev, mknod=mknod)[0] == "kvm"
    assert made == [(str(dev), True, 10, 232)]


@pytest.mark.parametrize("err,words", [
    (errno.ENXIO, "the host kernel has no KVM device"),
    (errno.ENODEV, "the host kernel has no KVM device"),
    (errno.EPERM, "this container may not use it"),
])
def test_tcg_with_the_reason_when_kvm_does_not_open(tmp_path, err, words):
    dev = tmp_path / "kvm"
    dev.write_bytes(b"")

    def opener(path, flags):
        raise OSError(err, os.strerror(err))

    accel, why = vm.choose_accel(dev, opener=opener)
    assert accel == "tcg" and words in why and "slow" in why
    with pytest.raises(DaemonError):
        vm.choose_accel(dev, want="kvm", opener=opener)


def test_tcg_when_the_node_cannot_be_made(tmp_path):
    def mknod(*a):
        raise PermissionError(errno.EPERM, "Operation not permitted")
    accel, why = vm.choose_accel(tmp_path / "kvm", mknod=mknod)
    assert accel == "tcg" and "could not be made" in why
    assert vm.choose_accel(tmp_path / "kvm", want="tcg")[0] == "tcg"


def test_each_accelerator_gets_its_own_command_line(tmp_path):
    common = dict(name="pantheon-pw-ann", cpus=2, memory_mib=2048, disk=tmp_path / "d.qcow2",
                  iso=tmp_path / "app.iso", console=tmp_path / "c.log", qmp=tmp_path / "q",
                  forward=("127.0.0.1", 41234))
    kvm, tcg = vm.qemu_argv(accel="kvm", **common), vm.qemu_argv(accel="tcg", **common)

    def opt(argv, flag):
        return [argv[i + 1] for i, a in enumerate(argv) if a == flag]

    assert (opt(kvm, "-accel"), opt(kvm, "-cpu")) == (["kvm"], ["host"])
    assert opt(tcg, "-accel")[0].startswith("tcg,thread=multi") and opt(tcg, "-cpu") == ["max"]
    for argv in (kvm, tcg):
        assert "-nodefaults" in argv and opt(argv, "-display") == ["none"]
        assert not any(a in ("-vnc", "-spice", "-monitor", "-vga") for a in argv)
        assert opt(argv, "-netdev") == ["user,id=net0,hostfwd=tcp:127.0.0.1:41234-:7040"]
        assert f"if=virtio,file={tmp_path / 'app.iso'},format=raw,readonly=on" in opt(argv, "-drive")
        assert opt(argv, "-serial") == [f"file:{tmp_path / 'c.log'}"]
    with pytest.raises(ValueError):
        vm.qemu_argv(accel="hvf", **common)


@pytest.mark.skipif(not shutil.which("genisoimage") or not shutil.which("isoinfo"),
                    reason="genisoimage is in vm.Dockerfile; this machine has none")
def test_the_app_disk_keeps_the_token_roots_alone(tmp_path):
    root = tmp_path / "app"
    (root / "workstation").mkdir(parents=True)
    (root / "workstation" / "agentd.py").write_text("# code\n")
    (root / "token").write_text("pws_machine\n")
    os.chmod(root / "token", 0o600)
    iso = tmp_path / "app.iso"
    vm.make_iso(iso, vm.APP_LABEL, root, keep_modes=True)
    listing = subprocess.run(["isoinfo", "-R", "-l", "-i", str(iso)], capture_output=True,
                             text=True, check=True).stdout
    token_line = next(ln for ln in listing.splitlines() if ln.rstrip().endswith(" token"))
    assert token_line.lstrip().startswith("-rw-------")
    assert "agentd.py" in listing
    label = subprocess.run(["isoinfo", "-d", "-i", str(iso)], capture_output=True, text=True,
                           check=True).stdout
    assert f"Volume id: {vm.APP_LABEL}" in label


# ── a token per machine, and the wall between them ───────────────────────────

@pytest.fixture
def host(tmp_path):
    fleet = vm.Fleet(tmp_path / "state", accel="kvm", need_image=False,
                     machine_factory=LocalMachine, start_timeout=60.0)
    server = make_server(fleet, TOKEN, bind="127.0.0.1", port=0,
                         station=vm.VmStation(fleet, TOKEN))
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield fleet, url
    finally:
        server.shutdown()
        server.server_close()
        for m in list(fleet._machines.values()):
            m.stop()


def test_each_person_gets_a_machine_of_their_own_and_its_token_opens_nothing_else(host):
    fleet, url = host
    c = WorkstationClient(url, TOKEN)
    ann, bob = account_for("ann"), account_for("bob")
    run(c.write(ann, "secret.txt", "ann's"))
    run(c.write(bob, "secret.txt", "bob's"))
    m_ann, m_bob = fleet.machine_for(ann), fleet.machine_for(bob)
    assert m_ann.port != m_bob.port and len({m_ann.token, m_bob.token, TOKEN}) == 3
    for path in (fleet.state / "machines" / ann / "token", fleet.state / "machines" / bob / "token"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # What a person who is root in their machine could read — that machine's
    # own token — opens neither the other machine nor the host.
    for target, token in ((f"http://127.0.0.1:{m_bob.port}", m_ann.token), (url, m_ann.token),
                          (url, m_bob.token)):
        with pytest.raises(WorkstationError) as e:
            run(WorkstationClient(target, token).read(bob, "secret.txt"))
        assert e.value.code == "unauthorized"
    assert run(c.read(bob, "secret.txt"))["data"] == b"bob's"
    assert run(c.health())["accounts"] == 2


def test_the_image_state_is_in_health_and_a_call_waits_for_nothing_while_it_is_made(tmp_path):
    fleet = vm.Fleet(tmp_path / "state", accel="tcg", machine_factory=LocalMachine)
    station = vm.VmStation(fleet, TOKEN)
    health = station.health(True)
    assert (health["backend"], health["machine"]) == (
        "vm", {"virtualization": "qemu", "accel": "tcg", "image": "preparing"})
    assert "machine" not in station.health(False)
    with pytest.raises(DaemonError) as e:
        station.ensure(account_for("ann"))
    assert e.value.code == "unavailable" and "making the machine image" in e.value.message
    assert station.account(account_for("ann"))["exists"] is False
    assert fleet._machines[account_for("ann")].running() is False


def test_sudo_is_kept_by_the_host_and_given_to_every_machine(host, tmp_path):
    fleet, url = host
    c = WorkstationClient(url, TOKEN)
    ann = account_for("ann")
    run(c.ensure(ann))
    assert run(c.config(sudo=False))["sudo"] is False
    machine_health = run(WorkstationClient(f"http://127.0.0.1:{fleet.machine_for(ann).port}",
                                           fleet.machine_for(ann).token).health())
    assert machine_health["sudo"] is False
    assert json.loads((fleet.state / "settings.json").read_text()) == {"sudo": False}
    again = vm.Fleet(fleet.state, accel="kvm", need_image=False, machine_factory=LocalMachine)
    assert again.sudo is False
    # Back on: the running machine is told at once — and a machine started
    # after the change is told when it starts (these machines boot with sudo
    # off, so on is what only the host's push can give them).
    assert run(c.config(sudo=True))["sudo"] is True
    assert run(WorkstationClient(f"http://127.0.0.1:{fleet.machine_for(ann).port}",
                                 fleet.machine_for(ann).token).health())["sudo"] is True
    bob = account_for("bob")
    run(c.ensure(bob))
    assert run(WorkstationClient(f"http://127.0.0.1:{fleet.machine_for(bob).port}",
                                 fleet.machine_for(bob).token).health())["sudo"] is True


def test_reset_is_a_new_machine_with_a_new_token(host):
    fleet, url = host
    c = WorkstationClient(url, TOKEN)
    ann = account_for("ann")
    run(c.write(ann, "notes.txt", "x"))
    old_token = fleet.machine_for(ann).token
    assert run(c.reset(ann)) == {"account": ann, "reset": True}
    assert fleet.machine_for(ann).token != old_token
    with pytest.raises(WorkstationError) as e:
        run(c.read(ann, "notes.txt"))
    assert e.value.code == "not_found"


def test_a_machine_that_dies_while_starting_is_said(tmp_path):
    class Dies(LocalMachine):
        def start(self):
            super().start()
            self.proc.kill()
            self.proc.wait()

        def why_not(self):
            return "kernel panic - not syncing"

    fleet = vm.Fleet(tmp_path / "state", accel="tcg", need_image=False, machine_factory=Dies,
                     start_timeout=30.0)
    with pytest.raises(DaemonError) as e:
        fleet.ready(account_for("ann"))
    assert "stopped while it was starting" in e.value.message and "kernel panic" in e.value.message


# ── the compose overlays, as compose resolves them ───────────────────────────

def _compose(*overlays, env=None):
    if not shutil.which("docker"):
        pytest.skip("the docker CLI is not installed here")
    base = {k: v for k, v in os.environ.items()
            if k not in ("COMPOSE_FILE", "PGID") and not k.startswith("PANTHEON_WORKSTATION")}
    base.update(env or {})
    argv = ["docker", "compose", "-f", "docker-compose.yml"]
    for o in overlays:
        argv += ["-f", o]
    done = subprocess.run(argv + ["config", "--format", "json"], cwd=ROOT, env=base,
                          capture_output=True, text=True, timeout=60)
    if done.returncode != 0 and "is not a docker command" in done.stderr:
        pytest.skip("docker compose is not installed here")
    return done


def test_the_vm_overlay_asks_for_one_device_and_nothing_else_of_the_host():
    done = _compose("docker/workstation-vm.yml", env={"PGID": "1234"})
    assert done.returncode == 0, done.stderr
    cfg = json.loads(done.stdout)
    ws = cfg["services"]["workstation"]
    assert ws["build"] == {"context": str(PKG), "dockerfile": "vm.Dockerfile"}
    assert ws["device_cgroup_rules"] == [f"c {vm.KVM_MAJOR}:{vm.KVM_MINOR} rwm"]
    assert not ws.get("privileged") and not ws.get("cap_add") and not ws.get("ports")
    assert not ws.get("devices") and ws.get("network_mode") in (None, "")
    mounts = [(m["type"], m["source"], m["target"], bool(m.get("read_only")))
              for m in ws["volumes"]]
    assert mounts == [("volume", "workstation-vm", str(vm.DEFAULT_STATE), False),
                      ("volume", "workstation-pairing", P.DEFAULT_PAIRING_DIR, False)]
    assert not any("docker.sock" in str(m) for m in ws["volumes"])
    assert ws["environment"]["PANTHEON_WORKSTATION_PAIRING_GID"] == "1234"
    assert ws["environment"][vm.ENV["accel"]] == "auto"
    # Long enough for every machine to power off cleanly.
    assert ws["stop_grace_period"] in ("2m0s", "120s") and vm.STOP_GRACE_S < 120
    assert ws["healthcheck"]["test"]


def test_switching_backends_is_one_line_because_pantheon_sees_no_difference():
    vm_cfg = json.loads(_compose("docker/workstation-vm.yml").stdout)
    ct_cfg = json.loads(_compose("docker/workstation.yml").stdout)
    for cfg in (vm_cfg, ct_cfg):
        p = cfg["services"]["pantheon"]
        assert p["environment"][P.URL_ENV] == f"http://{P.DEFAULT_HOST}:{P.DEFAULT_PORT}"
        assert ("workstation-pairing", P.DEFAULT_PAIRING_DIR, True) in [
            (m["source"], m["target"], bool(m.get("read_only"))) for m in p["volumes"]]
        assert "workstation" in cfg["services"]


def test_the_remote_overlay_starts_nothing_and_demands_what_it_needs():
    done = _compose("docker/workstation-remote.yml")
    assert done.returncode != 0 and "workstation/install.py printed" in done.stderr
    done = _compose("docker/workstation-remote.yml", env={
        P.URL_ENV: "https://192.168.1.50:7040", P.TOKEN_ENV: "pws_x"})
    assert done.returncode == 0, done.stderr
    cfg = json.loads(done.stdout)
    assert "workstation" not in cfg["services"]
    env = cfg["services"]["pantheon"]["environment"]
    assert (env[P.URL_ENV], env[P.TOKEN_ENV], env[P.TLS_PIN_ENV]) == (
        "https://192.168.1.50:7040", "pws_x", "")


def test_too_little_room_to_make_the_image_is_said_before_anything_is_written(tmp_path,
                                                                              monkeypatch):
    base = tmp_path / "base.img"
    base.write_bytes(b"x")
    fleet = vm.Fleet(tmp_path / "state", accel="tcg", base_image=base, payload=PKG)
    monkeypatch.setattr(vm.shutil, "disk_usage",
                        lambda p: shutil._ntuple_diskusage(100 * 10**9, 99 * 10**9, 10**9))
    monkeypatch.setattr(fleet, "run", lambda argv: pytest.fail(f"ran {argv}"))
    fleet.prepare_image()
    assert fleet.image_state == "failed"
    assert "needs about 5 GB free" in fleet.image_why and "1.0 GB is" in fleet.image_why
    assert not (fleet.state / "images" / "making").exists()
