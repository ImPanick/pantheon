# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1756` — the phone has a room, a device is picked from a list, Pantheon
installs it, and the agent drives it the way a person does.

The owner (2026-11-07): *"Like workstation, I want it in the workbench as
well. The user should be able to pick from a list of devices and Pantheon
should pull the image/install configure etc. … I also want agentic tooling to
use it exactly as a user would."*

Pinned here, without Android, KVM or a network (none is on a test machine):

  * **the install** — `provision.sh phone`'s steps and sdkmanager's bars read
    as progress; one install at a time; never without the license, which only
    a person accepts; a pick of a device not here installs it and then boots
    it, and a failed install leaves the phone off with the reason, to retry;
  * **availability** — a workstation with KVM that can install is offered the
    phone though nothing is installed yet;
  * **the route** — the install's state shaped for the window;
  * **the agent** — `press`, `rotate`, `fold`, `unfold`, `open_url` and
    `use_device` are the window's own requests, in the tool's schema;
  * **the room** — the device list's words, the license prompt and the
    progress line, from `phoneWindow.js` itself.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from workstation import phone as PH
from workstation import protocol as P

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = P.account_name("ann")
IMAGE = "system-images;android-35;google_apis;x86_64"


class _System:
    backend = "vm"  # isolated guest fixture; this test does not boot a VM
    def __init__(self, root):
        self.root = root

    def home(self, account):
        return self.root / account

    def uid(self, account):
        return 4321

    def ensure(self, account):
        self.home(account).mkdir(parents=True, exist_ok=True)
        return {"home": str(self.home(account))}

    def run_as(self, account, *, with_display=True):
        return [], {"HOME": str(self.home(account))}

    @contextlib.contextmanager
    def files_as(self, account):
        yield


@pytest.fixture
def bare(tmp_path, monkeypatch):
    """A workstation with KVM that has nothing of the phone yet, and can
    install it (a provisioning script, root, room on the disk)."""
    sdk = tmp_path / "sdk"
    script = tmp_path / "provision.sh"
    script.write_text("#!/bin/sh\n")
    monkeypatch.setenv(PH.SDK_ENV, str(sdk))
    monkeypatch.setattr(PH, "scrcpy_version", lambda path: (3, 3))
    monkeypatch.setenv(PH.PROVISION_ENV, str(script))
    monkeypatch.setattr(PH.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(PH.shutil, "which", lambda name: "/usr/bin/scrcpy" if name == "scrcpy" else None)
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    return sdk


def _lay_down(sdk, package=IMAGE):
    """What `provision.sh phone` leaves behind."""
    for rel in ("emulator/emulator", "platform-tools/adb"):
        f = sdk / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("#!/bin/sh\n")
        f.chmod(0o755)
    (sdk / PH.image_parts(package)["sysdir"]).mkdir(parents=True, exist_ok=True)
    (sdk / "licenses").mkdir(exist_ok=True)
    (sdk / "licenses" / "android-sdk-license").write_text("hash\n")


def _phone(tmp_path, installer):
    system = _System(tmp_path)
    system.ensure(ACCOUNT)
    return PH.AccountPhone(system, ACCOUNT, None, kvm=lambda: (True, "KVM opened."), installer=installer)


# ── the install ───────────────────────────────────────────────────────────────

def test_the_scripts_steps_and_sdkmanagers_bar_are_read_as_progress():
    state = {}
    for line in ("provision: step: libraries", "Get:1 http://archive.ubuntu.com noble InRelease",
                 "provision: step: android", "[=====                ] 25% Downloading x86_64-35_r09.zip"):
        PH.read_progress(line, state)
    assert state["step"] == "android" and state["percent"] == 25
    assert state["said"] == "Downloading x86_64-35_r09.zip"
    PH.read_progress("provision: step: done", state)
    assert state["percent"] == 100
    PH.read_progress("provision: step: nonsense", state)
    assert state["step"] == "done", "an unknown step is not taken"


def test_the_android_name_is_read_from_the_package():
    assert PH.android_name(IMAGE) == "Android 15"
    assert PH.android_name("system-images;android-36;google_apis;x86_64") == "Android 16"
    assert PH.android_name("not a package") == "not a package"


def test_nothing_is_installed_without_the_license(bare):
    inst = PH.Installer(run=lambda pkg, on_line: 0)
    with pytest.raises(PH.PhoneError) as e:
        inst.start(IMAGE, accept=False)
    assert e.value.code == "license" and "Android SDK License" in e.value.message
    assert "Devices room" in e.value.message


def test_a_workstation_that_cannot_install_says_how_to_build_the_phone_in(bare, monkeypatch):
    monkeypatch.setattr(PH.os, "geteuid", lambda: 1000, raising=False)
    with pytest.raises(PH.PhoneError) as e:
        PH.Installer(run=lambda pkg, on_line: 0).start(IMAGE, accept=True)
    assert e.value.code == "unavailable" and "root" in e.value.message
    assert "workstation-vm" in e.value.message


def test_one_install_at_a_time(bare):
    import threading
    gate = threading.Event()

    def run(pkg, on_line):
        gate.wait(5)
        return 1

    inst = PH.Installer(run=run)
    inst.start(IMAGE, accept=True)
    assert inst.start(IMAGE, accept=True)["state"] == "running", "the same one again is the same install"
    with pytest.raises(PH.PhoneError) as e:
        inst.start("system-images;android-36;google_apis;x86_64", accept=True)
    assert e.value.code == "busy"
    gate.set()
    inst._thread.join(5)
    assert inst.info()["state"] == "failed" and "exit 1" in inst.info()["why"]


def test_a_workstation_with_kvm_is_offered_the_phone_before_anything_is_installed(bare, tmp_path):
    info = _phone(tmp_path, PH.Installer(run=lambda p, f: 0)).info()
    assert info["available"] is True and info["mode"] == "android" and info["state"] == "off"
    assert info["installed"] is False and info["can_install"] is True
    assert info["license"] == {"accepted": False, "url": PH.LICENSE_URL}
    assert all(d["installed"] is False and d["android"] == "Android 15" for d in info["devices"])


def test_picking_a_device_not_here_installs_it_then_boots_it(bare, tmp_path):
    def run(pkg, on_line):
        on_line("provision: step: tools")
        on_line("[==========] 60% Unzipping")
        _lay_down(bare, pkg)
        return 0

    phone = _phone(tmp_path, PH.Installer(run=run))
    booted = []
    real_start = phone.start

    def start(device=None):
        if phone.installed():
            booted.append(phone.device)
            return phone.info("start")
        return real_start(device)

    phone.start = start
    with pytest.raises(PH.PhoneError) as e:
        phone.install("galaxy_z_fold6")
    assert e.value.code == "license"
    answer = phone.install("galaxy_z_fold6", accept=True)
    assert answer["state"] == "installing" and answer["device"] == "galaxy_z_fold6"
    phone.installer._thread.join(5)
    assert phone.installer.info()["state"] == "done"
    assert booted == ["galaxy_z_fold6"], "once installed, the device it was picked for is turned on"
    info = phone.info()
    assert info["installed"] is True and info["license"]["accepted"] is True


def test_a_failed_install_leaves_the_phone_off_with_the_reason(bare, tmp_path):
    def run(pkg, on_line):
        on_line("provision: dl.google.com could not be reached")
        return 7

    phone = _phone(tmp_path, PH.Installer(run=run))
    phone.install("pixel_8", accept=True)
    phone.installer._thread.join(5)
    assert phone.state == "off", "off, so the person can pick it again"
    assert "exit 7" in phone.why and "could not be reached" in phone.why


def test_a_pick_of_an_installed_device_just_starts_it(bare, tmp_path):
    _lay_down(bare)
    phone = _phone(tmp_path, PH.Installer(run=lambda p, f: pytest.fail("nothing to install")))
    calls = []
    phone.start = lambda device=None: calls.append(phone.device) or {"state": "starting"}
    assert phone.install("pixel_9_pro")["state"] == "starting" and calls == ["pixel_9_pro"]


def test_provisioning_is_idempotent_and_asks_for_the_license():
    script = (ROOT / "workstation" / "provision.sh").read_text()
    body = script[script.index("phone()"):]
    assert "PHONE_ACCEPT_LICENSE" in body and "exit 3" in body
    assert 'say "step: tools"' in body and 'say "step: android"' in body and 'say "step: done"' in body
    assert subprocess.run(["sh", "-n", str(ROOT / "workstation" / "provision.sh")]).returncode == 0


# ── the route ─────────────────────────────────────────────────────────────────

def test_the_route_shapes_the_install_for_the_window():
    from routes.workstation_routes import _PHONE_FIELDS, _PHONE_PERSON_ACTIONS, _phone_state
    assert "install" in _PHONE_PERSON_ACTIONS and "accept_license" in _PHONE_FIELDS
    out = _phone_state({
        "available": True, "state": "installing", "device": "pixel_8", "installed": False,
        "license": {"accepted": True, "url": "https://evil.example/terms"},
        "install": {"state": "running", "step": "android", "step_label": "Downloading Android",
                    "percent": 140, "android": "Android 15", "secret": "x"},
        "devices": [{"id": "pixel_8", "name": "Google Pixel 8", "maker": "Google", "kind": "phone",
                     "installed": False, "android": "Android 15"}],
    })
    assert out["state"] == "installing" and out["installed"] is False
    assert out["license"] == {"accepted": True, "url": "https://developer.android.com/studio/terms"}
    assert out["install"] == {"state": "running", "step": "android", "step_label": "Downloading Android",
                              "android": "Android 15", "percent": 100}
    assert out["devices"][0]["installed"] is False and out["devices"][0]["android"] == "Android 15"
    assert "installing" in P.PHONE_STATES and "install" in P.PHONE_ACTIONS


def test_only_a_person_accepts_the_license():
    src = (ROOT / "workstation" / "agentd.py").read_text()
    branch = src[src.index('if action == "install":'):][:400]
    assert 'who != "person"' in branch and "accept_license" in branch


# ── the agent ─────────────────────────────────────────────────────────────────

def test_the_agents_controls_are_the_windows_own_requests():
    from src.agent_tools import computer_tools as CT
    req = CT._control_request
    assert req({"action": "press", "button": "Volume up"}) == (("button", {"button": "volume_up"}), None)
    assert req({"action": "rotate"}) == (("rotate", {}), None)
    assert req({"action": "fold"}) == (("posture", {"posture": "closed"}), None)
    assert req({"action": "unfold"}) == (("posture", {"posture": "open"}), None)
    assert req({"action": "open_url", "url": "https://example.org"}) == (
        ("open_url", {"url": "https://example.org"}), None)
    assert req({"action": "use_device", "device": "galaxy_z_fold6"}) == (
        ("install", {"device": "galaxy_z_fold6"}), None)
    assert "button" in req({"action": "press"})[1]
    assert "Galaxy" in req({"action": "use_device", "device": "iphone"})[1]
    assert set(CT.PHONE_CONTROLS) <= set(CT.ACTIONS)


def test_the_schema_offers_the_controls_and_their_fields():
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    fn = next(s["function"] for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "computer")
    props = fn["parameters"]["properties"]
    for action in ("press", "rotate", "fold", "unfold", "open_url", "use_device"):
        assert action in props["action"]["enum"]
    assert props["button"]["enum"] == list(P.PHONE_BUTTONS)
    assert props["device"]["enum"] == list(P.PHONE_DEVICES)
    assert "use_device" in fn["description"]


class _Client:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def phone(self, account, action, **fields):
        self.calls.append((action, fields))
        return self.answers.pop(0)


def test_the_agents_pick_waits_on_the_install_like_the_person_does():
    from src.agent_tools import computer_tools as CT
    installing = {"state": "installing", "device": "pixel_8",
                  "install": {"state": "running", "step_label": "Downloading Android", "percent": 40},
                  "devices": [{"id": "pixel_8", "name": "Google Pixel 8"}]}
    client = _Client([installing, installing])
    tool = CT.ComputerTool.__new__(CT.ComputerTool)
    got = asyncio.run(tool._control(client, ACCOUNT, {"action": "use_device", "device": "pixel_8"},
                                    "ann", "use Google Pixel 8"))
    assert client.calls[0] == ("install", {"device": "pixel_8"})
    assert got["output"].startswith("Did: use Google Pixel 8.")
    assert "Downloading Android" in got["output"]


# ── the room ──────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_room_lists_the_devices_and_asks_for_the_license_once(tmp_path):
    src = (ROOT / "static" / "js" / "phoneWindow.js").read_text()
    src = re.sub(r"^import \* as Modals from .*$", "const Modals = {};", src, flags=re.M)
    src = re.sub(r"^import \{ prefersReducedMotion \} from .*$",
                 "const prefersReducedMotion = () => false;", src, flags=re.M)
    src = re.sub(r"^import \{ makeWindowDraggable \} from .*$", "const makeWindowDraggable = () => {};",
                 src, flags=re.M)
    mod = tmp_path / "phoneWindow.mjs"
    mod.write_text(src)
    script = f"""
import {{ catalogueOf, installLine, needsLicense }} from {json.dumps(mod.as_uri())};
const devices = [
  {{ id: 'pixel_9_pro', name: 'Google Pixel 9 Pro', maker: 'Google', kind: 'phone', installed: true, android: 'Android 15' }},
  {{ id: 'galaxy_z_fold6', name: 'Samsung Galaxy Z Fold6', maker: 'Samsung', kind: 'foldable', foldable: true, installed: false }},
];
const s = {{ state: 'on', mode: 'android', device: 'pixel_9_pro', devices, license: {{ accepted: false }} }};
const installing = {{ ...s, state: 'installing', device: 'galaxy_z_fold6',
  install: {{ state: 'running', step_label: 'Downloading Android', percent: 55, android: 'Android 15' }} }};
console.log(JSON.stringify({{
  groups: catalogueOf(s),
  mobile: catalogueOf({{ ...s, mode: 'mobile_view' }})[1].devices[0],
  installing: catalogueOf(installing)[1].devices[0],
  line: installLine(installing),
  failed: installLine({{ ...s, state: 'off', install: {{ state: 'failed', why: 'The install did not finish (exit 7).' }} }}),
  idle: installLine(s),
  license: [needsLicense(s, 'galaxy_z_fold6'), needsLicense(s, 'pixel_9_pro'),
            needsLicense({{ ...s, license: {{ accepted: true }} }}, 'galaxy_z_fold6'),
            needsLicense({{ ...s, mode: 'mobile_view' }}, 'galaxy_z_fold6')],
}}));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert [g["maker"] for g in got["groups"]] == ["Google", "Samsung"]
    pixel, fold = got["groups"][0]["devices"][0], got["groups"][1]["devices"][0]
    assert pixel["current"] is True and pixel["verb"] == "In use" and pixel["installed"] is True
    assert fold["verb"] == "Install and use" and fold["installed"] is False and fold["foldable"] is True
    assert got["mobile"]["verb"] == "Preview this profile", "preview is an explicit web-only action"
    assert got["installing"]["verb"] == "Installing…" and got["installing"]["busy"] is True
    assert got["line"] == {"text": "Downloading Android (Android 15)", "percent": 55, "failed": False}
    assert got["failed"]["failed"] is True and "exit 7" in got["failed"]["text"]
    assert got["idle"] is None
    assert got["license"] == [True, False, False, False]


def test_the_workbench_has_the_devices_room():
    js = (ROOT / "static" / "js" / "workbench" / "workbench.js").read_text()
    html = (ROOT / "static" / "index.html").read_text()
    assert "id: 'devices', label: ROOM_NAMES.devices, panel: 'workbench-room-devices'" in js
    assert "import('../phoneWindow.js')" in js
    assert 'id="workbench-room-devices"' in html and 'id="devices-room"' in html
    from src import workbench_rooms
    assert workbench_rooms.DEVICES_ROOM == "Devices"
    assert "devices: 'Devices'" in (ROOT / "static" / "js" / "workbench" / "rooms.js").read_text()


# ── `B1757`: more devices, each drawn as it looks ───────────────────────────────

def test_the_catalogue_has_phones_foldables_and_tablets_from_several_makers():
    kinds = {}
    for d in P.PHONE_DEVICES.values():
        kinds.setdefault(d["kind"], []).append(d["name"])
    assert len(P.PHONE_DEVICES) >= 15
    assert len(kinds["tablet"]) >= 4 and len(kinds["foldable"]) >= 3 and len(kinds["phone"]) >= 8
    assert {d["maker"] for d in P.PHONE_DEVICES.values()} >= {"Google", "Samsung", "OnePlus", "Nothing"}
    for id_, d in P.PHONE_DEVICES.items():
        if d["kind"] == "foldable":
            assert 0 < d["cover_width"] < d["width"], id_


@pytest.mark.parametrize("device", sorted(P.PHONE_DEVICES))
def test_every_device_says_how_it_looks(device):
    look = P.PHONE_LOOKS[device]
    assert re.fullmatch(r"#[0-9a-f]{6}", look["finish"]) and look["finish_name"]
    assert 0 < look["corner"] <= 0.2 and 0 < look["bezel"] <= 0.1
    assert look["cutout"] in P.PHONE_CUTOUTS
    keys = [k for side, ids in look["keys"].items() for k in ids]
    assert set(look["keys"]) <= set(P.PHONE_KEY_SIDES)
    assert sorted(keys) == ["power", "volume_down", "volume_up"], "every device has power and a rocker"
    if P.PHONE_DEVICES[device]["kind"] == "tablet":
        assert "top" in look["keys"] and look["cutout"] == "bezel-top"


def test_the_look_reaches_the_window_shaped():
    from routes.workstation_routes import _phone_look, _phone_state
    good = _phone_look(P.PHONE_LOOKS["oneplus_12"])
    assert good["finish"] == "#2e5a4a" and good["keys"] == {"left": ["volume_up", "volume_down"], "right": ["power"]}
    bad = _phone_look({"finish": "red;background:url(x)", "corner": 9, "bezel": True, "cutout": "notch",
                       "keys": {"bottom": ["power"], "right": ["power", "reboot"]}})
    assert bad == {"finish": "", "finish_name": "", "corner": 0.2, "bezel": 0.03, "cutout": "punch-center",
                   "keys": {"right": ["power"]}}
    out = _phone_state({"state": "off", "devices": []})
    assert all(d["look"]["finish"] for d in out["devices"]), "the catalogue's own looks when the daemon sent none"


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_body_is_drawn_at_the_devices_shape_with_its_keys_on_their_edges(tmp_path):
    src = (ROOT / "static" / "js" / "phoneWindow.js").read_text()
    src = re.sub(r"^import \* as Modals from .*$", "const Modals = {};", src, flags=re.M)
    src = re.sub(r"^import \{ prefersReducedMotion \} from .*$",
                 "const prefersReducedMotion = () => false;", src, flags=re.M)
    src = re.sub(r"^import \{ makeWindowDraggable \} from .*$", "const makeWindowDraggable = () => {};",
                 src, flags=re.M)
    mod = tmp_path / "phoneWindow.mjs"
    mod.write_text(src)
    looks = json.dumps({k: P.PHONE_LOOKS[k] for k in ("oneplus_12", "galaxy_tab_s9", "pixel_9_pro")})
    script = f"""
import {{ keysOf, lookOf, bodyGeometry }} from {json.dumps(mod.as_uri())};
const looks = {looks};
const dev = (id, maker) => ({{ id, maker, look: looks[id] }});
const ids = (side) => side.map((k) => k.id);
const one = keysOf(dev('oneplus_12', 'OnePlus')), tab = keysOf(dev('galaxy_tab_s9', 'Samsung'));
const phone = bodyGeometry(lookOf(dev('pixel_9_pro')), {{ w: 492, h: 1100 }}, 600, 800);
const slab = bodyGeometry(lookOf(dev('galaxy_tab_s9')), {{ w: 1280, h: 800 }}, 900, 800);
console.log(JSON.stringify({{
  one: [ids(one.left), ids(one.right), ids(one.top)], tab: [ids(tab.left), ids(tab.right), ids(tab.top)],
  old: ids(keysOf({{ maker: 'Samsung' }}).right),
  phone, slab, plain: lookOf({{}}),
}}));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["one"] == [["volume_up", "volume_down"], ["power"], []]
    assert got["tab"] == [[], [], ["power", "volume_up", "volume_down"]]
    assert got["old"] == ["volume_up", "volume_down", "power"], "a device with no look keeps its maker's keys"
    for g, (W, H) in ((got["phone"], (600, 800)), (got["slab"], (900, 800))):
        assert g["screenW"] + 2 * g["rim"] <= W + 1 and g["screenH"] + 2 * g["rim"] <= H + 1
        assert g["rim"] >= 4 and g["radius"] > g["rim"] and g["inner"] >= 2
    p = got["phone"]
    assert abs(p["screenW"] / p["screenH"] - 492 / 1100) < 0.01 and p["screenH"] > p["screenW"]
    s = got["slab"]
    assert s["screenW"] > s["screenH"] and s["radius"] < p["radius"] * 1.5
    assert got["plain"]["cutout"] == "punch-center" and got["plain"]["finish"] == ""
