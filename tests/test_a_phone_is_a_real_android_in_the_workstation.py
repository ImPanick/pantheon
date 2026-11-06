# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1751` / `B1752` — a real Android phone per person, in the workstation.

The owner, 2026-11-02: *"a mobile device emulator... with various real device
emulation (Samsung Galaxy Z Fold, Google Pixel Pro, etc...) with the real OS,
"touch" controls (via mouse)"*, and a rendered phone whose side buttons work.

A test machine has no Android SDK, no KVM and no scrcpy, so what is pinned here
is everything around them, held to what each one is documented to take:

  * **the catalogue** — real devices with their makers' screens, a foldable's
    cover inside its inner screen, and a phone screen that fits the
    protocol's bounds at the device's own shape;
  * **the device** — `config.ini` is the device's own screen and density, no
    skin, software GL, no audio; only a foldable has a hinge;
  * **the processes** — the emulator headless on its own console port with no
    metrics; scrcpy borderless over the whole phone screen, `--no-audio` only
    where scrcpy has audio;
  * **what the phone says** — built without it, no KVM (and how to get it),
    and ready, each in a sentence;
  * **marks** — the device's UI tree moved onto the phone screen's pixels,
    only what can be tapped or typed into, named by its words;
  * **the daemon** — one holder on every screen (the agent's moves are `busy`
    while a person holds them, a look never is), each field checked, touch
    checked against the phone screen's own size, and the VM backend saying
    where the phone is instead;
  * **the agent's tool** — `computer` takes `screen: "phone"`, keeps the
    phone's marks apart from the desktop's, and turns a phone that is off on.
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest

from workstation import phone as PH
from workstation import protocol as P
from workstation.agentd import SingleUserSystem, Workstation
from workstation.agentd import WorkstationError as DaemonError

ACCOUNT = P.account_name("ann")


# ── the catalogue ─────────────────────────────────────────────────────────────

def test_the_devices_the_owner_named_are_there():
    names = {d["name"] for d in P.PHONE_DEVICES.values()}
    assert "Samsung Galaxy Z Fold6" in names
    assert "Google Pixel 9 Pro" in names
    assert P.PHONE_DEFAULT_DEVICE in P.PHONE_DEVICES


@pytest.mark.parametrize("device", sorted(P.PHONE_DEVICES))
def test_each_phone_screen_fits_the_protocols_bounds_at_its_own_shape(device):
    d = P.PHONE_DEVICES[device]
    w, h = P.phone_screen_size(device)
    assert 0 < w <= P.PHONE_SCREEN_MAX[0] <= P.SCREEN_WIDTH
    assert 0 < h <= P.PHONE_SCREEN_MAX[1]
    assert w % 2 == 0 and h % 2 == 0
    assert abs(w / h - d["width"] / d["height"]) < 0.01
    if d["kind"] == "foldable":
        assert 0 < d["cover_width"] < d["width"]


# ── the device ────────────────────────────────────────────────────────────────

def _ini(text):
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def test_a_phones_config_is_its_own_screen_with_no_skin_and_no_hinge():
    cfg = _ini(PH.avd_config("pixel_9_pro", PH.DEFAULT_IMAGE))
    assert (cfg["hw.lcd.width"], cfg["hw.lcd.height"], cfg["hw.lcd.density"]) == ("1280", "2856", "480")
    assert cfg["image.sysdir.1"] == "system-images/android-35/google_apis/x86_64/"
    assert cfg["skin.path"] == "_no_skin" and cfg["showDeviceFrame"] == "no"
    assert cfg["hw.gpu.mode"] == "swiftshader_indirect"
    assert cfg["hw.audioOutput"] == "no"
    assert cfg["hw.device.manufacturer"] == "Google"
    assert "hw.sensor.hinge" not in cfg


def test_a_foldables_config_has_its_hinge_and_its_cover_screen():
    cfg = _ini(PH.avd_config("galaxy_z_fold6", PH.DEFAULT_IMAGE))
    assert cfg["hw.device.manufacturer"] == "Samsung"
    assert cfg["hw.sensor.hinge"] == "yes"
    assert cfg["hw.displayRegion.0.1.width"] == "928"
    assert cfg["hw.displayRegion.0.1.height"] == cfg["hw.lcd.height"] == "2160"


def test_a_tablet_starts_in_landscape():
    assert _ini(PH.avd_config("pixel_tablet", PH.DEFAULT_IMAGE))["hw.initialOrientation"] == "landscape"


def test_a_system_images_name_is_read_whole_or_refused():
    assert PH.image_parts("system-images;android-36;google_apis_playstore;x86_64")["target"] == "android-36"
    assert _ini(PH.avd_config("pixel_8", "system-images;android-36;google_apis_playstore;x86_64"))[
        "PlayStore.enabled"] == "true"
    with pytest.raises(PH.PhoneError):
        PH.image_parts("platforms;android-35")


def test_the_avd_ini_points_at_the_devices_folder(tmp_path):
    text = PH.avd_ini("pixel_8", tmp_path, PH.DEFAULT_IMAGE)
    assert f"path={tmp_path / 'pantheon_pixel_8.avd'}" in text


# ── the processes ─────────────────────────────────────────────────────────────

def test_the_emulator_runs_headless_on_its_own_port_and_tells_nobody():
    argv = PH.emulator_argv("/sdk/emulator/emulator", "pixel_8", port=5590, memory_mib=2048)
    assert argv[:3] == ["/sdk/emulator/emulator", "-avd", "pantheon_pixel_8"]
    for flag in ("-no-window", "-no-audio", "-no-metrics"):
        assert flag in argv
    assert argv[argv.index("-port") + 1] == "5590"


def test_the_consoles_are_above_the_range_adb_finds_by_itself():
    assert min(PH.CONSOLE_PORTS) > 5585 and max(PH.CONSOLE_PORTS) + 1 <= 5682
    assert all(p % 2 == 0 for p in PH.CONSOLE_PORTS)


def test_scrcpy_covers_the_phone_screen_borderless_and_asks_no_audio_only_where_it_has_audio():
    old = PH.scrcpy_argv("scrcpy", "emulator-5586", (492, 1100), version=(1, 25))
    new = PH.scrcpy_argv("scrcpy", "emulator-5586", (492, 1100), version=(3, 1))
    for argv in (old, new):
        assert "--window-borderless" in argv
        assert argv[argv.index("--window-width") + 1] == "492"
        assert argv[argv.index("--window-height") + 1] == "1100"
        assert argv[argv.index("--serial") + 1] == "emulator-5586"
    assert "--no-audio" not in old and "--no-audio" in new


@pytest.mark.parametrize("url,ok", [("https://example.com/a?b=1&c=2", True), ("http://10.0.0.5:3000", True),
                                    ("javascript:alert(1)", False), ("file:///etc/passwd", False),
                                    ("https://a b", False), ("", False)])
def test_only_web_addresses_are_opened(url, ok):
    if ok:
        assert PH.check_url(url) == url
    else:
        with pytest.raises(PH.PhoneError):
            PH.check_url(url)


# ── what the phone says ───────────────────────────────────────────────────────

class _System:
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


def _sdk(tmp_path, monkeypatch, *, image=True):
    sdk = tmp_path / "sdk"
    for rel in ("emulator/emulator", "platform-tools/adb"):
        f = sdk / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("#!/bin/sh\n")
        f.chmod(0o755)
    if image:
        (sdk / "system-images/android-35/google_apis/x86_64").mkdir(parents=True)
    monkeypatch.setenv(PH.SDK_ENV, str(sdk))
    monkeypatch.setattr(PH.shutil, "which", lambda name: "/usr/bin/scrcpy" if name == "scrcpy" else None)
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    return sdk


def _phone(tmp_path, kvm=(True, "KVM: /dev/kvm opened.")):
    system = _System(tmp_path)
    system.ensure(ACCOUNT)
    return PH.AccountPhone(system, ACCOUNT, None, kvm=lambda: kvm)


def test_a_workstation_built_without_the_phone_says_how_to_build_it_in(tmp_path, monkeypatch):
    monkeypatch.setenv(PH.SDK_ENV, str(tmp_path / "nothing"))
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    info = _phone(tmp_path).info()
    assert info["available"] is False and info["state"] == "unavailable"
    assert "WORKSTATION_PHONE=on" in info["why"] and "Android SDK License" in info["why"]


def test_a_host_without_kvm_is_told_how_to_get_it(tmp_path, monkeypatch):
    _sdk(tmp_path, monkeypatch)
    info = _phone(tmp_path, kvm=(False, "the host has no KVM")).info()
    assert info["available"] is False
    assert "KVM" in info["why"] and ".wslconfig" in info["why"] and "the host has no KVM" in info["why"]


def test_an_arm_machine_is_told_the_phone_is_x86(tmp_path, monkeypatch):
    _sdk(tmp_path, monkeypatch)
    monkeypatch.setattr("platform.machine", lambda: "aarch64")
    assert "x86_64" in _phone(tmp_path).info()["why"]


def test_a_ready_workstation_offers_every_device_and_starts_none(tmp_path, monkeypatch):
    _sdk(tmp_path, monkeypatch)
    info = _phone(tmp_path).info()
    assert info["available"] is True and info["state"] == "off" and "why" not in info
    assert {d["id"] for d in info["devices"]} == set(P.PHONE_DEVICES)
    assert info["device"] == P.PHONE_DEFAULT_DEVICE
    assert info["screen"] == list(P.phone_screen_size(P.PHONE_DEFAULT_DEVICE))


def test_the_chosen_device_is_kept_in_the_persons_home(tmp_path, monkeypatch):
    _sdk(tmp_path, monkeypatch)
    p = _phone(tmp_path)
    p.device = "galaxy_z_fold6"
    p._save_device()
    assert (tmp_path / ACCOUNT / PH.PREFS_FILE).is_file()
    assert _phone(tmp_path).device == "galaxy_z_fold6"


def test_the_device_and_its_avd_are_written_into_the_home(tmp_path, monkeypatch):
    _sdk(tmp_path, monkeypatch)
    p = _phone(tmp_path)
    p.device = "pixel_9_pro_fold"
    p._write_avd()
    avd = tmp_path / ACCOUNT / ".android" / "avd"
    assert (avd / "pantheon_pixel_9_pro_fold.ini").is_file()
    assert "hw.sensor.hinge=yes" in (avd / "pantheon_pixel_9_pro_fold.avd" / "config.ini").read_text()


def test_the_accounts_adb_is_its_own(tmp_path, monkeypatch):
    _sdk(tmp_path, monkeypatch)
    env = _phone(tmp_path).env()
    assert env["ANDROID_ADB_SERVER_PORT"] == str(PH.adb_port(4321))
    assert env["ANDROID_AVD_HOME"].startswith(str(tmp_path / ACCOUNT))
    assert "ANDROID_SERIAL" not in env  # not running: no phone to name


def test_kvm_is_opened_to_the_accounts_only_when_it_opens(tmp_path):
    dev = tmp_path / "kvm"
    dev.write_text("")
    calls = []
    ok, why = PH.kvm_for_accounts(dev, chooser=lambda d, want: ("tcg", "No KVM: the host has no KVM."),
                                  chmod=lambda *a: calls.append(a))
    assert (ok, calls) == (False, []) and why == "the host has no KVM"


# ── marks ─────────────────────────────────────────────────────────────────────

DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node index="0" text="" class="android.widget.FrameLayout" package="com.android.chrome" clickable="false" enabled="true" bounds="[0,0][1080,2400]">
  <node index="0" text="" content-desc="" class="android.widget.EditText" package="com.android.chrome" clickable="true" enabled="true" bounds="[40,100][1040,220]"/>
  <node index="1" text="" content-desc="" class="android.widget.Button" package="com.android.chrome" clickable="true" enabled="true" bounds="[40,300][540,420]">
    <node index="0" text="Sign in" class="android.widget.TextView" package="com.android.chrome" clickable="false" enabled="true" bounds="[60,320][520,400]"/>
  </node>
  <node index="2" text="Off" class="android.widget.Button" package="com.android.chrome" clickable="true" enabled="false" bounds="[40,500][540,600]"/>
  <node index="3" text="Static" class="android.widget.TextView" package="com.android.chrome" clickable="false" enabled="true" bounds="[40,700][540,800]"/>
</node>
</hierarchy>UI hierchary dumped to: /dev/tty"""


def test_the_phones_ui_tree_is_marked_on_the_phone_screens_pixels():
    got = PH.marks_from_dump(DUMP, (494, 1100))
    marks = got["marks"]
    assert [m["name"] for m in marks] == ["", "Sign in"]
    field, button = marks
    assert field["role"] == "text field" and field.get("editable") is True
    # 1080×2400 fits 494×1100 at 0.4574 (by width), centred: 494 wide, 1097.8 tall.
    scale = min(494 / 1080, 1100 / 2400)
    oy = (1100 - 2400 * scale) / 2
    assert button["box"] == [round(40 * scale), round(oy + 300 * scale), round(500 * scale), round(120 * scale)]
    for m in marks:
        x, y, w, h = m["box"]
        assert x >= 0 and y >= 0 and x + w <= 494 and y + h <= 1100


def test_a_tree_that_is_not_one_is_said():
    with pytest.raises(PH.PhoneError):
        PH.marks_from_dump("ERROR: could not get idle state.", (494, 1100))


# ── the daemon ────────────────────────────────────────────────────────────────

class _Screen:
    width, height = 494, 1100
    desktop_kind = "kasmvnc"

    def __init__(self):
        self.sent = []

    def send(self, action):
        self.sent.append(action)

    def grab(self, fmt):
        return b"\x89PNG-phone", "image/png"


class _FakePhone:
    def __init__(self):
        self.screen = _Screen()
        self.device = "pixel_8"
        self.lock = contextlib.nullcontext()
        self.pressed = []
        self.state = "on"

    def info(self, action="status"):
        return {"ok": True, "action": action, "state": self.state, "device": self.device}

    def running(self):
        return True

    def mode(self):
        return "android"

    def _on(self):
        pass

    def button(self, name):
        if name not in P.PHONE_BUTTONS:
            raise PH.PhoneError("bad_request", "no such button")
        self.pressed.append(name)
        return self.info("button")


@pytest.fixture
def station(tmp_path):
    st = Workstation(SingleUserSystem(tmp_path / "homes"), "pws_test")
    fake = _FakePhone()
    st.phones.get = lambda account: fake
    st.fake = fake
    return st


def test_a_person_at_the_wheel_makes_the_agents_moves_on_the_phone_busy_but_not_its_looks(station):
    station.control(ACCOUNT, {"holder": "person"})
    with pytest.raises(DaemonError) as e:
        station.phone(ACCOUNT, {"action": "button", "button": "power"})
    assert e.value.code == "busy"
    with pytest.raises(DaemonError):
        station.phone(ACCOUNT, {"action": "input", "input": "click", "x": 10, "y": 10})
    assert station.phone(ACCOUNT, {"action": "status"})["state"] == "on"
    assert station.phone(ACCOUNT, {"action": "screenshot"})["width"] == 494
    # The person's own press goes through.
    station.phone(ACCOUNT, {"action": "button", "button": "power", "holder": "person"})
    assert station.fake.pressed == ["power"]


def test_touch_is_checked_against_the_phone_screens_own_size(station):
    out = station.phone(ACCOUNT, {"action": "input", "input": "click", "x": 400, "y": 1050})
    assert out == {"ok": True, "action": "click"}
    assert station.fake.screen.sent == [{"action": "click", "x": 400, "y": 1050}]
    with pytest.raises(DaemonError) as e:
        station.phone(ACCOUNT, {"action": "input", "input": "click", "x": 494, "y": 10})
    assert e.value.code == "bad_request"


def test_every_field_is_checked(station):
    for body in ({"action": "reboot"}, {"action": "device", "device": "iphone_16"},
                 {"action": "button", "button": "bixby"}, {"action": "status", "holder": "root"}):
        with pytest.raises(DaemonError) as e:
            station.phone(ACCOUNT, body)
        assert e.value.code == "bad_request", body


def test_the_phone_routes_are_the_protocols():
    assert P.ROUTES["phone"] == ("POST", "/v1/users/{account}/phone")
    assert P.ROUTES["phone_screen"] == ("GET", "/v1/users/{account}/phone/screen")
    assert set(P.PHONE_LOOK_ACTIONS) <= set(P.PHONE_ACTIONS)
    assert P.PHONE_BUTTONS["power"] == 26 and P.PHONE_BUTTONS["volume_up"] == 24


def test_the_vm_backend_says_where_the_phone_is():
    from workstation.vm import VmStation
    assert "container" in VmStation.PHONE_ELSEWHERE.lower()


def test_a_phone_screen_is_its_devices_shape_on_kasmvnc():
    from workstation.ubuntu import DISPLAY_ROLES, kasmvnc_argv
    assert "phone" in DISPLAY_ROLES
    argv = kasmvnc_argv("Xkasmvnc", displayfd=3, auth=Path("/a"), port=1, logins=Path("/l"),
                        size=(494, 1100))
    assert argv[argv.index("-geometry") + 1] == "494x1100"
    argv = kasmvnc_argv("Xkasmvnc", displayfd=3, auth=Path("/a"), port=1, logins=Path("/l"))
    assert argv[argv.index("-geometry") + 1] == f"{P.SCREEN_WIDTH}x{P.SCREEN_HEIGHT}"


# ── the agent's tool ──────────────────────────────────────────────────────────

def test_computer_takes_the_phone_as_a_screen():
    from src.agent_tools.computer_tools import describe_action, parse_args
    args, problem = parse_args({"action": "click", "x": 10, "y": 20, "screen": "Phone"})
    assert problem is None and args["screen"] == "phone"
    assert describe_action(args) == "phone: click at (10, 20)"
    args, problem = parse_args({"action": "screenshot"})
    assert args["screen"] == "desktop"
    _, problem = parse_args({"action": "screenshot", "screen": "tv"})
    assert problem and "phone" in problem


def test_the_computer_schema_offers_the_phone():
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    fn = next(s["function"] for s in FUNCTION_TOOL_SCHEMAS if s["function"]["name"] == "computer")
    assert fn["parameters"]["properties"]["screen"]["enum"] == ["desktop", "phone"]


class _Client:
    def __init__(self, states):
        self.states = list(states)
        self.calls = []

    async def phone(self, account, action, **fields):
        self.calls.append((action, fields))
        if action in ("status", "start"):
            return self.states.pop(0)
        if action == "screenshot":
            return {"mime": "image/png", "data_b64": "aGk=", "width": 494, "height": 1100}
        return {}


def test_a_phone_that_is_off_is_turned_on_and_the_agent_told_to_wait():
    from src.agent_tools.computer_tools import _phone_on
    client = _Client([{"state": "off"}, {"state": "starting", "device": "pixel_8",
                                         "devices": [{"id": "pixel_8", "name": "Google Pixel 8"}]}])
    out = asyncio.run(_phone_on(client, ACCOUNT))
    assert [c[0] for c in client.calls] == ["status", "start"]
    assert "Google Pixel 8" in out["output"] and "booting" in out["output"]


def test_a_phone_that_is_on_lets_the_action_through_and_one_that_cannot_says_why():
    from src.agent_tools.computer_tools import _phone_on
    assert asyncio.run(_phone_on(_Client([{"state": "on"}]), ACCOUNT)) is None
    out = asyncio.run(_phone_on(_Client([{"state": "unavailable", "why": "No KVM here."}]), ACCOUNT))
    assert out["error"] == "No KVM here." and out["exit_code"] == 1


# ── the window (`B1752`) ──────────────────────────────────────────────────────

def _window_module(tmp_path):
    """`phoneWindow.js` with its two imports stood in for, so its pure parts
    run under node without a page."""
    import re
    src = (Path(__file__).resolve().parents[1] / "static" / "js" / "phoneWindow.js").read_text()
    src = re.sub(r"^import \* as Modals from .*$", "const Modals = {};", src, flags=re.M)
    src = re.sub(r"^import \{ makeWindowDraggable \} from .*$", "const makeWindowDraggable = () => {};",
                 src, flags=re.M)
    path = tmp_path / "phoneWindow.mjs"
    path.write_text(src)
    return path


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="node binary not on PATH")
def test_the_bezel_is_the_devices_shape_and_its_keys_are_where_its_maker_puts_them(tmp_path):
    import json
    import subprocess
    mod = _window_module(tmp_path)
    script = f"""
import {{ sideKeys, bezelShape, deviceOf }} from {json.dumps(str(mod))};
const fold = {{ device: 'galaxy_z_fold6', screen: [944, 1100], posture: 'closed',
  devices: [{{ id: 'galaxy_z_fold6', name: 'Samsung Galaxy Z Fold6', maker: 'Samsung', kind: 'foldable', foldable: true }}] }};
console.log(JSON.stringify({{
  google: sideKeys('Google').map((k) => k.id),
  samsung: sideKeys('Samsung').map((k) => k.id),
  closed: bezelShape(fold),
  open: bezelShape({{ ...fold, posture: 'open' }}),
  name: deviceOf(fold).name,
}}));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["google"] == ["power", "volume_up", "volume_down"]
    assert got["samsung"] == ["volume_up", "volume_down", "power"]
    assert got["open"] == {"w": 944, "h": 1100}
    assert got["closed"] == {"w": 472, "h": 1100}
    assert got["name"] == "Samsung Galaxy Z Fold6"


def test_the_window_has_a_door_and_names_no_server_string_as_html():
    root = Path(__file__).resolve().parents[1]
    src = (root / "static" / "js" / "phoneWindow.js").read_text()
    assert "data-open-phone" in (root / "static" / "index.html").read_text()
    assert "import './js/phoneWindow.js'" in (root / "static" / "app.js").read_text()
    # The one innerHTML is the constant icon.
    assert src.count("innerHTML") == 1 and "icon.innerHTML = PHONE_ICON" in src
