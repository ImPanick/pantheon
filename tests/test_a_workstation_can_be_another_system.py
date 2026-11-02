# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1744` — the workstation can be Ubuntu, Debian, Fedora or Rocky Linux,
each person's own pick.

The owner, 2026-11-02, on a choice of golden images: *"I think that would be a
worthwhile addition.. Considering I have custom fine-tune LLM's built around
full-suite security ops.. (Purple Teaming, aka Red and Blue team experts)."*
Later the same day he kept Kali and Parrot to a private security branch
(*"I don't feel like releasing llm automated hack-tools is the move to the
public"*) and asked for other systems of great value in their place:
Fedora (current, developer-first) and Rocky Linux (the RHEL 9 family).

What is pinned:

  * one `Dockerfile` makes all four: a pinned base stage per system, the final
    stage chosen by `WORKSTATION_OS`;
  * `provision.sh` knows which system it is on from /etc/os-release, refuses
    any other, picks KasmVNC's build for it, and installs the same desktop
    with apt or dnf, every download checked against a pinned sum;
  * each non-Ubuntu system is a compose service in its own profile, on the
    port `protocol.SYSTEM_PORTS` names, behind the same network gate, with its
    own homes and pairing volume — and Pantheon is told where, in all three
    compose files;
  * Pantheon routes a person to the system they picked only when the stack
    runs it (its daemon has paired), with that daemon's own token, and to
    Ubuntu otherwise; an address an admin typed still wins for everyone;
  * the daemon says which system it is; the pick is validated on the way in;
  * the panel's System picker shows every system and says what to do about
    one that is not running.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from src import workstation_access as wa
from src import workstation_client as wc
from workstation import machine
from workstation import protocol as P

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "workstation" / "Dockerfile"
PROVISION = ROOT / "workstation" / "provision.sh"
COMPOSE = [ROOT / "docker-compose.yml", ROOT / "docker-compose.gpu-nvidia.yml",
           ROOT / "docker-compose.gpu-amd.yml"]
OTHERS = [s for s in P.SYSTEMS if s != P.DEFAULT_SYSTEM]


# ── the protocol ──────────────────────────────────────────────────────────────

def test_every_system_has_a_name_and_a_port_of_its_own():
    assert P.SYSTEMS[0] == P.DEFAULT_SYSTEM == "ubuntu"
    assert set(P.SYSTEM_NAMES) == set(P.SYSTEMS) == set(P.SYSTEM_PORTS)
    ports = list(P.SYSTEM_PORTS.values())
    assert len(set(ports)) == len(ports), "two systems in one namespace cannot share a port"
    assert P.GATE_PORT not in ports, "the gate's port is in the same namespace"
    assert P.SYSTEM_PORTS["ubuntu"] == P.DEFAULT_PORT
    assert P.system_url_env("ubuntu") == P.URL_ENV
    assert P.system_pairing_dir("ubuntu") == P.DEFAULT_PAIRING_DIR
    assert P.system_url_env("fedora") == "PANTHEON_WORKSTATION_FEDORA_URL"
    assert P.system_pairing_dir("rocky") == "/workstation-rocky-pairing"
    assert not {"kali", "parrot"} & set(P.SYSTEMS), "kept off the public branch"


# ── the image ─────────────────────────────────────────────────────────────────

def test_one_dockerfile_makes_every_system_from_a_pinned_base():
    text = DOCKERFILE.read_text(encoding="utf-8")
    for system in P.SYSTEMS:
        m = re.search(rf"^FROM (\S+) AS base-{system}$", text, re.M)
        assert m, f"no base stage for {system}"
        assert re.search(r"@sha256:[0-9a-f]{64}$", m.group(1)), \
            f"{system}'s base is a tag a rebuild can move ({m.group(1)})"
    assert re.search(r"^ARG WORKSTATION_OS=ubuntu$", text, re.M)
    assert re.search(r"^FROM base-\$\{WORKSTATION_OS\}$", text, re.M)
    assert "TOOLSET" not in text


def _os_release(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "os-release"
    path.write_text(text, encoding="utf-8")
    return path


RELEASES = {
    "ubuntu": 'PRETTY_NAME="Ubuntu 24.04.3 LTS"\nID=ubuntu\nID_LIKE=debian\n',
    "debian": 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\n',
    "fedora": 'NAME="Fedora Linux"\nPRETTY_NAME="Fedora Linux 44 (Container Image)"\nID=fedora\n',
    "rocky": 'NAME="Rocky Linux"\nPRETTY_NAME="Rocky Linux 9.8 (Blue Onyx)"\nID="rocky"\n'
             'ID_LIKE="rhel centos fedora"\n',
}


def _provision(tmp_path: Path, release: str, *args: str) -> subprocess.CompletedProcess:
    """`provision.sh` with apt-get and dnf replaced by a recorder: what it
    would install is in `apt.log`, and nothing is installed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "apt.log"
    (bin_dir / "apt-get").write_text(f'#!/bin/sh\necho "$@" >> {log}\n', encoding="utf-8")
    (bin_dir / "apt-get").chmod(0o755)
    shutil.copy(bin_dir / "apt-get", bin_dir / "dnf")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "OS_RELEASE": str(_os_release(tmp_path, release)),
           "PROVISION_CA": str(tmp_path / "no-ca")}
    return subprocess.run(["sh", str(PROVISION), *args], env=env, capture_output=True,
                          text=True, timeout=60)


def _install_lists(name: str) -> set[str]:
    text = PROVISION.read_text(encoding="utf-8")
    m = re.search(rf'^{name}="([^"]*)"', text, re.M | re.S)
    assert m, f"no {name} in provision.sh"
    return set(m.group(1).replace("\\\n", " ").split())


def test_fedora_and_rocky_install_the_same_desktop_with_dnf():
    """The dnf list names what the apt list's desktop is made of: the X
    server, the input and picture tools, XFCE, a terminal, D-Bus and Python
    for the daemon. `curl` is left to the image (Rocky's curl-minimal
    conflicts with it), and tini and Firefox are installed on their own."""
    dnf = _install_lists("DNF_PACKAGES")
    for need in ("xorg-x11-server-Xvfb", "xdotool", "scrot", "xfce4-session", "xfwm4",
                 "xfce4-panel", "xfdesktop", "xfce4-terminal", "dbus-daemon", "python3",
                 "sudo", "git", "nftables", "shadow-utils"):
        assert need in dnf, f"{need} is missing from the dnf list"
    assert "curl" not in dnf
    text = PROVISION.read_text(encoding="utf-8")
    body = text[text.index("packages_dnf() {"):]
    body = body[:body.index("\n}\n")]
    assert "$dnf install firefox" in body
    assert "dnf config-manager --set-enabled crb" in body, "Rocky needs CRB for EPEL's XFCE"
    assert '/usr/bin/tini "$tsum"' in body
    assert "kasmvncserver_oracle_9_" in body
    assert '[ "$os" = fedora ] || exit 1' in body, "only Fedora may fall back to pictures"


def test_every_download_is_checked_against_a_pinned_sum():
    text = PROVISION.read_text(encoding="utf-8")
    for name in ("KASMVNC_SHA256_EL9_X86_64", "KASMVNC_SHA256_EL9_AARCH64",
                 "TINI_SHA256_AMD64", "TINI_SHA256_ARM64"):
        assert re.search(rf"^{name}=[0-9a-f]{{64}}$", text, re.M), name
    assert "sha256sum -c" in text[text.index("fetch_checked() {"):]


@pytest.mark.skipif(not shutil.which("sh"), reason="no sh")
@pytest.mark.parametrize("release", [
    'ID=arch\n', 'ID=kali\nID_LIKE=debian\n', 'ID=parrot\nID_LIKE=debian\n',
    'ID="opensuse-leap"\n', '',
])
def test_a_system_the_workstation_is_not_made_from_is_refused(tmp_path, release):
    """Kali and Parrot are kept off this branch (`D-2026-11-02-01`); a build
    on any system the lists are not for stops before installing anything."""
    done = _provision(tmp_path, release, "packages")
    assert done.returncode == 1
    assert "not a system the workstation is made from" in done.stderr
    assert not (tmp_path / "apt.log").exists()


def test_kasmvnc_is_the_build_for_the_system():
    """Ubuntu's own build on Ubuntu, Debian 13's on Debian (pinned already
    for Pantheon's own image), and the EL9 build on Rocky and Fedora."""
    text = PROVISION.read_text(encoding="utf-8")
    body = text[text.index("kasmvnc_dist() {"):]
    body = body[:body.index("\n}\n")]
    assert "ubuntu) printf 'ubuntu_noble'" in body
    assert "debian) printf 'debian_trixie'" in body
    assert "*) printf 'oracle_9'" in body
    assert 'kasmvnc_deb "$arch" /tmp/kasmvncserver.deb "$(kasmvnc_dist)"' in text


# ── the stack ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", COMPOSE, ids=lambda p: p.name)
def test_each_system_is_an_opt_in_service_behind_the_same_gate(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    services = data["services"]
    ubuntu = services["workstation"]
    assert "profiles" not in ubuntu, "Ubuntu's workstation is every install's"
    env = services["pantheon"]["environment"]
    mounts = services["pantheon"]["volumes"]
    for system in OTHERS:
        svc = services[f"workstation-{system}"]
        port = P.SYSTEM_PORTS[system]
        assert svc["profiles"] == [system]
        assert svc["build"]["context"] == "./workstation"
        assert svc["build"]["args"]["WORKSTATION_OS"] == system
        assert svc["network_mode"] == "service:workstation-net"
        assert svc["cap_drop"] == ubuntu["cap_drop"] == ["NET_RAW"]
        assert svc["command"][-2:] == ["--port", str(port)]
        assert f"127.0.0.1:{port}/v1/health" in svc["healthcheck"]["test"][-1]
        assert f"workstation-{system}-pairing:/workstation-pairing" in svc["volumes"]
        assert f"workstation-{system}-homes:/home" in svc["volumes"]
        assert f"{P.system_url_env(system)}=http://workstation:{port}" in env
        assert f"workstation-{system}-pairing:{P.system_pairing_dir(system)}:ro" in mounts
        assert {f"workstation-{system}-homes", f"workstation-{system}-pairing"} <= set(data["volumes"])
        assert "TOOLSET" not in svc["build"]["args"]
    assert not {"workstation-kali", "workstation-parrot"} & set(services)


# ── which one a person is routed to ───────────────────────────────────────────

@pytest.fixture()
def stack(tmp_path, monkeypatch):
    """A stack whose compose file names every system, with pairing folders
    in `tmp_path`; a system "runs" once its token file is written."""
    settings: dict = {}
    monkeypatch.setattr(wc, "_setting", lambda key, default="": settings.get(key, default))
    monkeypatch.setenv(P.URL_ENV, "http://workstation:7040")
    monkeypatch.delenv(P.VM_URL_ENV, raising=False)
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    dirs = {}
    for system in P.SYSTEMS:
        d = tmp_path / f"pair-{system}"
        d.mkdir()
        dirs[system] = d
        monkeypatch.setenv(P.system_pairing_dir_env(system), str(d))
        if system != P.DEFAULT_SYSTEM:
            monkeypatch.setenv(P.system_url_env(system),
                               f"http://workstation:{P.SYSTEM_PORTS[system]}")
    (dirs["ubuntu"] / P.TOKEN_FILENAME).write_text("pws_ubuntu\n")

    def pair(system):
        (dirs[system] / P.TOKEN_FILENAME).write_text(f"pws_{system}\n")
    return settings, pair


def test_a_system_is_offered_once_its_daemon_has_paired(stack):
    _settings, pair = stack
    assert wc.systems_offered() == ["ubuntu"]
    pair("fedora")
    assert wc.systems_offered() == ["ubuntu", "fedora"]
    assert wc.system_in_use("fedora") == "fedora"
    assert wc.system_in_use("rocky") == "ubuntu", "never an address nothing answers at"
    assert wc.system_in_use("kali") == "ubuntu"
    assert wc.system_in_use("windows") == "ubuntu"


def test_the_picked_system_is_its_own_address_and_token(stack):
    _settings, pair = stack
    pair("rocky")
    assert wc.resolve_base("rocky") == ("http://workstation:7044", wc.SOURCE_ENVIRONMENT)
    assert wc.resolve_token("rocky") == ("pws_rocky", wc.SOURCE_PAIRING)
    assert wc.resolve_base() == ("http://workstation:7040", wc.SOURCE_ENVIRONMENT)
    assert wc.resolve_token() == ("pws_ubuntu", wc.SOURCE_PAIRING)
    client = wc.from_settings("rocky")
    assert client.base == "http://workstation:7044"


def test_an_ubuntu_token_set_by_hand_is_not_sent_to_another_system(stack, monkeypatch):
    settings, pair = stack
    pair("fedora")
    settings["workstation_token"] = "pws_typed"
    monkeypatch.setenv(P.TOKEN_ENV, "pws_env")
    assert wc.resolve_token() == ("pws_typed", wc.SOURCE_SETTING)
    assert wc.resolve_token("fedora") == ("pws_fedora", wc.SOURCE_PAIRING)


def test_an_address_an_admin_typed_is_everyones(stack):
    settings, pair = stack
    pair("fedora")
    settings["workstation_url"] = "http://10.0.0.5:7040"
    assert wc.systems_offered() == ["ubuntu"]
    assert wc.system_in_use("fedora") == "ubuntu"
    assert wc.resolve_base("fedora") == ("http://10.0.0.5:7040", wc.SOURCE_SETTING)


def test_workstation_for_routes_a_person_to_their_pick(stack, monkeypatch):
    settings, pair = stack
    settings["workstation_enabled"] = True
    prefs = {"ann": {wa.SYSTEM_PREF: "fedora"}, "bo": {}}
    import routes.prefs_routes as pr
    monkeypatch.setattr(pr, "_load_for_user", lambda user=None: prefs.get(user, {}))
    monkeypatch.setattr(wa, "may_use", lambda owner, auth_manager=None: True)
    client, _account = wa.workstation_for("ann")
    assert client.base == "http://workstation:7040", "Fedora is not running yet: Ubuntu"
    pair("fedora")
    client, _account = wa.workstation_for("ann")
    assert client.base == "http://workstation:7043"
    assert wa.workstation_for("bo")[0].base == "http://workstation:7040"
    view = wa.systems_view("ann")
    assert (view["chosen"], view["in_use"]) == ("fedora", "fedora")
    rows = {r["id"]: r for r in view["systems"]}
    assert rows["fedora"]["runs"] and rows["fedora"]["how"] is None
    assert not rows["rocky"]["runs"] and "COMPOSE_PROFILES=rocky" in rows["rocky"]["how"]


def test_a_pick_is_checked_on_the_way_in():
    assert wa.checked_system("rocky") == "rocky"
    assert wa.checked_system(None) == wa.checked_system("") == "ubuntu"
    for bad in ("windows", "kali", "Fedora", 3, ["rocky"]):
        with pytest.raises(ValueError):
            wa.checked_system(bad)


# ── the daemon says which it is ───────────────────────────────────────────────

@pytest.mark.parametrize("system", P.SYSTEMS)
def test_the_daemon_reads_which_system_it_is(tmp_path, system):
    seen = machine.os_release(_os_release(tmp_path, RELEASES[system]))
    assert seen["id"] == system
    assert seen["name"] and system.split()[0] in seen["name"].lower()


def test_no_os_release_is_said_as_nothing(tmp_path):
    assert machine.os_release(tmp_path / "missing") == {"id": None, "name": None}


def test_health_carries_the_system_for_a_caller_with_the_token(tmp_path):
    from workstation.agentd import SingleUserSystem, Workstation
    system = SingleUserSystem(tmp_path / "homes")
    system._os_release = {"id": "rocky", "name": "Rocky Linux 9.8 (Blue Onyx)"}
    ws = Workstation(system, "pws_test")
    assert ws.health(True)["system"] == {"id": "rocky", "name": "Rocky Linux 9.8 (Blue Onyx)"}
    assert "system" not in ws.health(False)
    assert "system" in wa._daemon_view(ws.health(True))


# ── the panel ─────────────────────────────────────────────────────────────────

node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@node
def test_the_picker_shows_every_system_and_what_to_do_about_one_not_running(tmp_path_factory):
    import json

    import test_the_workstation_panel_js as panel
    from test_tool_effect_surfaces_js import _make_sandbox
    sandbox = _make_sandbox(tmp_path_factory.mktemp("workstation-system"), panel.MODULE,
                            panel._SHIM.replace("__NODES__", json.dumps(panel._panel_nodes())),
                            panel._STUBS)
    systems = [{"id": s, "name": P.SYSTEM_NAMES[s], "runs": s in ("ubuntu", "fedora"),
                "how": None if s in ("ubuntu", "fedora") else
                wa.SYSTEM_PROFILE_HINT.format(system=s)} for s in P.SYSTEMS]
    out = panel._panel(sandbox, """
      mod._test.renderSystem(view);
      const sel = byId('ws-system');
      console.log(JSON.stringify({
        shown: !byId('ws-system-row').hidden, value: sel.value,
        labels: sel.children.map((o) => o.textContent),
        why: byId('ws-system-why').hidden ? null : byId('ws-system-why').textContent,
      }));
    """, view={"chosen": "rocky", "in_use": "ubuntu", "systems": systems})
    assert out["shown"] and out["value"] == "rocky"
    assert out["labels"] == ["Ubuntu 24.04", "Debian 13 (not running)", "Fedora 44",
                             "Rocky Linux 9 (not running)"]
    assert "Rocky Linux 9 is not running on this server, so you are on Ubuntu 24.04." in out["why"]
    assert "COMPOSE_PROFILES=rocky" in out["why"]
