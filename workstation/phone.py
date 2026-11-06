# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone: a real Android device per person, in their workstation. `B1751`.

The owner, 2026-11-02: *"a mobile device emulator... with various real device
emulation (Samsung Galaxy Z Fold, Google Pixel Pro, etc...) with the real OS,
"touch" controls (via mouse)... That way the user can troubleshoot mobile
apps, or even use the mobile device mock up to run their platforms/websites."*

WHAT RUNS
=========

* **Google's Android Emulator**, from the Android SDK the image was built with
  (`provision.sh phone`, only with `WORKSTATION_PHONE=on`), booting a real
  Android system image (`PHONE_IMAGE`, Google APIs, x86_64) — the OS a phone
  runs, not a look-alike. It runs **as the account**, headless (`-no-window`),
  with each device's data in the account's own home
  (`~/.android/avd/pantheon_<device>.avd`), so a person's phone is theirs, is
  kept across restarts, and goes with "Reset to clean" like the rest of the home.
* **On a screen of its own**: an `XDisplay` of role "phone" (`ubuntu.py`), the
  browser's arrangement — KasmVNC with nothing else on it — sized to the
  device's screen scaled to fit (`protocol.phone_screen_size`). **scrcpy** shows
  the emulator's display there, borderless over the whole screen, and is what
  turns the mouse into touch: a click is a tap, a drag a swipe, the wheel a
  fling, a right click Back and a middle click Home. So the person's stream and
  the agent's `computer` calls (with `screen: "phone"`) work this screen the
  way they work the desktop, through the same `xdotool` and the same grab.
* **adb** for everything that is not a touch: the hardware keys
  (`PHONE_BUTTONS`), a foldable's posture, rotation, opening an address, and
  the device's own UI tree for numbered marks (`uiautomator dump`), which is
  what a model clicks by number instead of guessing pixels.

WHAT IT NEEDS, SAID
===================

**KVM.** Android's emulator runs x86_64 Android on the host's CPU through KVM;
without it the emulator either refuses or crawls (minutes a screen), so a phone
on a host without KVM is `unavailable` with the sentence that says how to get
it — on Docker Desktop for Windows, nested virtualization in `.wslconfig`
(`docs/setup.md`). `/dev/kvm` is made in the container as the VM backend makes
it (`vm.choose_accel`; the compose file's device-cgroup rule is what lets it
open) and opened to the accounts, who run the emulator.

**Its own adb, per account.** Each account's adb server listens on a port of
its own (`ANDROID_ADB_SERVER_PORT`, from the uid), and each emulator's console
on an even port from `CONSOLE_PORTS` — above the range adb scans by itself, so
one account's `adb devices` does not list another's phone. The console asks
for the token in the account's own home. That is not a wall between accounts
while `sudo` is on (the default: every account is root here, and the jail is a
fiction the panel already says so beside); with `sudo` off, the emulator's adb
port is still on the loopback every account shares, which `THREAT_MODEL.md`
records as this row's open edge.

WITHOUT KVM: THE MOBILE VIEW (`B1753`)
======================================

The owner chose, 2026-11-02, "Real Android, plus mobile view": on a host
without KVM (Docker Desktop without nested virtualization, most cloud VMs) the
phone is not refused — it opens as a **mobile view**: the workstation's own
Firefox, alone on the phone's screen in kiosk mode, at the device's shape, with
the device's CSS width (`layout.css.devPixelsPerPx`), a mobile user agent, the
page's `<meta name="viewport">` honoured, and touch events on — so a website
lays itself out and behaves as it does on that phone. It is not Android: no
apps, no volume or recents keys, and `info()["mode"]` says which one runs
("android" or "mobile_view"), with `why_not_android` saying what the real one
needs. Back and Home, posture, rotation, opening an address and every
screenshot and input on the screen work the same way.

Standard library only and nothing from Pantheon outside this package, like the
rest of it.
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from workstation import protocol as P
from workstation.browser import AccountBrowser, BrowserError, find_firefox

logger = logging.getLogger(__name__)

# ── what the image put where ─────────────────────────────────────────────────
SDK_ENV = "ANDROID_SDK_ROOT"
DEFAULT_SDK = "/opt/android-sdk"
#: The system image the image installed, as `sdkmanager` names it. Set by the
#: Dockerfile from the same build argument that installed it.
IMAGE_ENV = "PANTHEON_PHONE_IMAGE"
DEFAULT_IMAGE = "system-images;android-35;google_apis;x86_64"
IDLE_ENV = "PANTHEON_PHONE_IDLE_MIN"
MAX_RUNNING_ENV = "PANTHEON_PHONE_MAX_RUNNING"
MEMORY_ENV = "PANTHEON_PHONE_MEMORY_MIB"
DEFAULT_IDLE_MIN = 30
DEFAULT_MAX_RUNNING = 2
DEFAULT_MEMORY_MIB = 2048
#: Where a person's choice of device is kept, in their home.
PREFS_FILE = ".pantheon/phone.json"
#: What the emulator last said, in the person's home (`.android` is the
#: emulator's own folder, made when its device is written).
LOG_FILE = ".android/pantheon-emulator.log"
AVD_PREFIX = "pantheon_"
#: Even ports for the emulator's console (its adb port is the next one up). adb
#: finds emulators by itself on 5554–5585; these start above that, and the
#: emulator allows up to 5682.
CONSOLE_PORTS = range(5586, 5682, 2)
#: Each account's own adb server: this plus the uid's last four digits.
ADB_PORT_BASE = 20000
BOOT_TIMEOUT_S = 420.0
STOP_TIMEOUT_S = 60.0
ADB_TIMEOUT_S = 20.0
REAP_EVERY_S = 60.0
AVAILABILITY_TRUST_S = 30.0

BUILT_WITHOUT = ("This workstation was built without the phone. Rebuild it with the phone in: "
                 "set WORKSTATION_PHONE=on (which accepts the Android SDK License) and run "
                 "docker compose up -d --build.")
NO_KVM = ("The phone needs KVM, and this workstation has none ({why}). Android's emulator runs "
          "the phone's own CPU through KVM and is unusable without it. On Docker Desktop for "
          "Windows, turn on nested virtualization in .wslconfig (docs/setup.md, \"A real VM on "
          "Windows\") and restart Docker; on Linux, the host needs /dev/kvm.")
NOT_X86 = "The phone runs x86_64 Android, and this workstation is {arch}."
NO_SCREEN = ("The phone has no screen to show on: this workstation has no KasmVNC. Rebuild it: "
             "docker compose up -d --build.")

# `B1753`. The mobile view: where its profile lives, what Home opens, and the
# Firefox for Android its user agent names (a version sites recognise).
MOBILE_PROFILE_DIR = ".pantheon/mobile-view"
MOBILE_HOME = "about:home"
MOBILE_UA_VERSION = "140.0"
MOBILE_NO_KEY = ("The mobile view has no {key} key: it is a phone-shaped browser, not Android. "
                 "The real Android phone needs KVM ({why})")
MOBILE_NO_MARKS = ("The mobile view has no numbered marks of its own; click by where things are "
                   "on its screenshot.")


class PhoneError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ── the pieces, as pure functions (the tests read these) ─────────────────────

def sdk_root() -> Path:
    return Path(os.environ.get(SDK_ENV) or DEFAULT_SDK)


def image_package() -> str:
    return os.environ.get(IMAGE_ENV) or DEFAULT_IMAGE


def image_parts(package: str) -> Dict[str, str]:
    """`system-images;android-35;google_apis;x86_64` read as its four parts:
    the folder under the SDK, the platform, the tag and the ABI."""
    parts = package.split(";")
    if len(parts) != 4 or parts[0] != "system-images" or not all(parts):
        raise PhoneError("unavailable", f"“{package}” is not a system image's name.")
    _, target, tag, abi = parts
    return {"sysdir": f"system-images/{target}/{tag}/{abi}/", "target": target, "tag": tag,
            "abi": abi, "api": target.split("-")[-1]}


def tools(root: Optional[Path] = None) -> Dict[str, Optional[str]]:
    """Where the emulator, adb and scrcpy are, or None for each one missing."""
    root = root or sdk_root()

    def there(path: Path) -> Optional[str]:
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None

    return {"emulator": there(root / "emulator" / "emulator"),
            "adb": there(root / "platform-tools" / "adb"),
            "scrcpy": shutil.which("scrcpy")}


def avd_name(device: str) -> str:
    return AVD_PREFIX + device


def avd_config(device: str, package: str, *, memory_mib: int = DEFAULT_MEMORY_MIB) -> str:
    """The device's `config.ini`: its screen exactly as the maker ships it,
    the system image, no skin (scrcpy draws the screen; Pantheon draws the
    bezel), no audio, software GL (no GPU is assumed), and for a foldable the
    hinge and the cover screen as the SDK's own foldables declare them."""
    d = P.PHONE_DEVICES[device]
    img = image_parts(package)
    w, h = d["width"], d["height"]
    lines = {
        "AvdId": avd_name(device),
        "avd.ini.displayname": d["name"],
        "avd.ini.encoding": "UTF-8",
        "abi.type": img["abi"],
        "hw.cpu.arch": "x86_64" if img["abi"] == "x86_64" else img["abi"],
        "hw.cpu.ncore": "2",
        "hw.ramSize": str(memory_mib),
        "vm.heapSize": "256",
        "image.sysdir.1": img["sysdir"],
        "tag.id": img["tag"],
        "target": img["target"],
        "hw.device.name": device,
        "hw.device.manufacturer": d["maker"],
        "hw.lcd.width": str(w),
        "hw.lcd.height": str(h),
        "hw.lcd.density": str(d["density"]),
        "hw.initialOrientation": "landscape" if w > h else "portrait",
        "hw.keyboard": "yes",
        "hw.mainKeys": "no",
        "hw.gpu.enabled": "yes",
        "hw.gpu.mode": "swiftshader_indirect",
        "hw.audioInput": "no",
        "hw.audioOutput": "no",
        "hw.camera.back": "none",
        "hw.camera.front": "none",
        "disk.dataPartition.size": "6G",
        "showDeviceFrame": "no",
        "skin.dynamic": "yes",
        "skin.name": f"{w}x{h}",
        "skin.path": "_no_skin",
        "PlayStore.enabled": "true" if "playstore" in img["tag"] else "false",
        "fastboot.forceColdBoot": "no",
    }
    if d["kind"] == "foldable":
        cover = d["cover_width"]
        lines.update({
            "hw.sensor.hinge": "yes",
            "hw.sensor.hinge.count": "1",
            "hw.sensor.hinge.type": "1",
            "hw.sensor.hinge.sub_type": "1",
            "hw.sensor.hinge.ranges": "0-180",
            "hw.sensor.hinge.defaults": "180",
            "hw.sensor.hinge.areas": f"{cover}-0-1-{h}",
            "hw.sensor.posture_list": "1, 2, 3",
            "hw.sensor.hinge_angles_posture_definitions": "0-30, 30-150, 150-180",
            "hw.sensor.hinge.fold_to_displayRegion.0.1_at_posture": "1",
            "hw.displayRegion.0.1.xOffset": "0",
            "hw.displayRegion.0.1.yOffset": "0",
            "hw.displayRegion.0.1.width": str(cover),
            "hw.displayRegion.0.1.height": str(h),
        })
    return "".join(f"{k}={v}\n" for k, v in lines.items())


def avd_ini(device: str, avd_home: Path, package: str) -> str:
    """The `<name>.ini` beside the device's folder, which is how the emulator
    finds it."""
    return (f"avd.ini.encoding=UTF-8\npath={avd_home / (avd_name(device) + '.avd')}\n"
            f"path.rel=avd/{avd_name(device)}.avd\ntarget={image_parts(package)['target']}\n")


def emulator_argv(emulator: str, device: str, *, port: int, memory_mib: int) -> List[str]:
    """The emulator, headless — scrcpy is the window — on KVM, with software
    GL, no audio, no boot animation, and nothing sent anywhere about it."""
    return [emulator, "-avd", avd_name(device), "-port", str(port), "-no-window", "-no-audio",
            "-no-boot-anim", "-gpu", "swiftshader_indirect", "-accel", "on",
            "-memory", str(memory_mib), "-no-metrics"]


def scrcpy_version(scrcpy: str) -> Tuple[int, int]:
    """scrcpy's `(major, minor)`, or `(1, 0)` when it does not say: its options
    differ between the release Ubuntu ships and later ones."""
    try:
        out = subprocess.run([scrcpy, "--version"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=10).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return (1, 0)
    m = re.search(r"scrcpy\s+v?(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (1, 0)


def scrcpy_argv(scrcpy: str, serial: str, size: Tuple[int, int], *,
                version: Tuple[int, int] = (1, 0)) -> List[str]:
    """scrcpy over the whole phone screen, borderless at its corner — the
    screen has no window manager to place it — drawn in software, the device
    kept awake while it shows. Audio is a later scrcpy's and is not wanted."""
    w, h = size
    argv = [scrcpy, "--serial", serial, "--window-title", "Pantheon phone",
            "--window-borderless", "--window-x", "0", "--window-y", "0",
            "--window-width", str(w), "--window-height", str(h),
            "--render-driver", "software", "--max-size", str(max(w, h) * 2),
            "--stay-awake", "--disable-screensaver"]
    if version >= (2, 0):
        argv.append("--no-audio")
    return argv


def mobile_view_size(device: str, posture: Optional[str] = None,
                     rotation: int = 0) -> Tuple[int, int]:
    """`B1753`. The mobile view's screen: the device's screen — its cover
    screen when a foldable is closed, turned on its side at an odd rotation —
    scaled to fit `P.PHONE_SCREEN_MAX`, both sides even."""
    d = P.PHONE_DEVICES.get(device) or P.PHONE_DEVICES[P.PHONE_DEFAULT_DEVICE]
    w, h = _shape(d, posture, rotation)
    scale = min(P.PHONE_SCREEN_MAX[0] / w, P.PHONE_SCREEN_MAX[1] / h, 1.0)
    return max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)


def _shape(d: Dict, posture: Optional[str], rotation: int) -> Tuple[int, int]:
    w, h = d["width"], d["height"]
    if posture == "closed" and d.get("cover_width"):
        w = d["cover_width"]
    if rotation % 2:
        w, h = h, w
    return w, h


def mobile_user_agent(device: str) -> str:
    """Firefox for Android's own user agent, phone or tablet: what a site
    reads to send its mobile pages."""
    d = P.PHONE_DEVICES.get(device) or P.PHONE_DEVICES[P.PHONE_DEFAULT_DEVICE]
    kind = "Tablet" if d["kind"] == "tablet" else "Mobile"
    v = MOBILE_UA_VERSION
    return f"Mozilla/5.0 (Android 15; {kind}; rv:{v}) Gecko/{v} Firefox/{v}"


def mobile_css_width(device: str, posture: Optional[str] = None, rotation: int = 0) -> float:
    """The page's width in CSS pixels on the real device: its pixels over
    its density (160 dpi is one CSS pixel a device pixel)."""
    d = P.PHONE_DEVICES.get(device) or P.PHONE_DEVICES[P.PHONE_DEFAULT_DEVICE]
    return _shape(d, posture, rotation)[0] / (d["density"] / 160.0)


def mobile_view_prefs(device: str, posture: Optional[str] = None, rotation: int = 0) -> str:
    """The mobile view's `user.js` lines, after the browser's own: the
    device's CSS width on this screen, its user agent, the page's viewport
    tag honoured, touch on and the pointer coarse — what responsive pages ask."""
    import json
    size = mobile_view_size(device, posture, rotation)
    scale = size[0] / mobile_css_width(device, posture, rotation)
    lines = {
        "general.useragent.override": mobile_user_agent(device),
        "layout.css.devPixelsPerPx": f"{scale:.3f}",
        "dom.meta-viewport.enabled": True,
        "dom.w3c_touch_events.enabled": 1,
        "ui.primaryPointerCapabilities": 2,   # coarse, no hover: `(pointer: coarse)`
        "ui.allPointerCapabilities": 2,
        "browser.startup.homepage": MOBILE_HOME,
        "browser.sessionstore.resume_from_crash": False,
        "browser.fullscreen.autohide": True,
    }
    return ("// `B1753`: the phone's mobile view (`workstation/phone.py`).\n"
            + "".join(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in lines.items()))


class MobileView(AccountBrowser):
    """`B1753`. The workstation's Firefox as a phone: on the phone's screen,
    in kiosk mode, at its size. Never headless: a mobile view nobody can see
    is no view, so a screen that will not start is said, not worked around."""

    extra_args = ("--kiosk",)

    def _on_screen_env(self) -> Optional[Dict[str, str]]:
        if self.screen is None:
            raise PhoneError("unavailable", NO_SCREEN)
        try:
            display = self.screen.start()
        except Exception as e:  # noqa: BLE001 — said, as the phone's own
            raise PhoneError("unavailable", "The phone's screen did not start: "
                             + str(getattr(e, "message", None) or e))
        return {**self.env, "DISPLAY": display, "XAUTHORITY": str(self.screen.auth_path())}


def adb_port(uid: int) -> int:
    return ADB_PORT_BASE + uid % 10000


def check_url(raw) -> str:
    url = str(raw or "").strip()
    if not re.match(r"^https?://[^\s]+$", url, re.I) or len(url) > 4000:
        raise PhoneError("bad_request", "“url” is an http:// or https:// address.")
    return url


_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_EDITABLE = ("EditText", "AutoCompleteTextView", "SearchView")


def marks_from_dump(xml: str, screen: Tuple[int, int]) -> Dict:
    """`ROUTES["marks"]`'s answer from a `uiautomator dump`: each control a
    person could tap or type into, its box moved from the device's pixels to
    the phone screen's — scrcpy fits the device's display into the screen,
    centred, keeping its shape — named by its text or its description."""
    end = xml.rfind("</hierarchy>")
    if end < 0:
        raise PhoneError("unavailable", "The phone's UI tree could not be read.")
    try:
        root = ET.fromstring(xml[xml.find("<?xml") if "<?xml" in xml else xml.find("<hierarchy"):
                                 end + len("</hierarchy>")])
    except ET.ParseError:
        raise PhoneError("unavailable", "The phone's UI tree could not be read.")
    nodes = list(root.iter("node"))
    if not nodes:
        return {"marks": [], "windows": [], "why": "The phone's screen has nothing on it to tap."}
    dev_w = dev_h = 0
    for n in nodes:
        m = _BOUNDS_RE.match(n.get("bounds", ""))
        if m:
            dev_w, dev_h = max(dev_w, int(m.group(3))), max(dev_h, int(m.group(4)))
    sw, sh = screen
    if dev_w <= 0 or dev_h <= 0:
        raise PhoneError("unavailable", "The phone's UI tree has no sizes in it.")
    scale = min(sw / dev_w, sh / dev_h)
    ox, oy = (sw - dev_w * scale) / 2, (sh - dev_h * scale) / 2
    marks: List[Dict] = []
    seen = set()
    for n in nodes:
        cls = n.get("class", "")
        editable = any(cls.endswith(e) for e in _EDITABLE)
        if not (n.get("clickable") == "true" or n.get("long-clickable") == "true"
                or n.get("checkable") == "true" or editable):
            continue
        if n.get("enabled") == "false":
            continue
        m = _BOUNDS_RE.match(n.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        box = [int(round(ox + x1 * scale)), int(round(oy + y1 * scale)),
               int(round((x2 - x1) * scale)), int(round((y2 - y1) * scale))]
        if box[2] < 4 or box[3] < 4 or box[0] < 0 or box[1] < 0 \
                or box[0] + box[2] > sw or box[1] + box[3] > sh:
            continue
        name = (n.get("text") or n.get("content-desc") or "").strip()
        if not name:
            # A control with no words of its own is named by the first child that has some.
            for c in n.iter("node"):
                name = (c.get("text") or c.get("content-desc") or "").strip()
                if name:
                    break
        key = tuple(box)
        if key in seen:
            continue
        seen.add(key)
        mark = {"role": "text field" if editable else
                ("check box" if n.get("checkable") == "true" else "button"),
                "name": name[:P.MARK_NAME_MAX], "box": box, "app": n.get("package", "")}
        if editable:
            mark["editable"] = True
        marks.append(mark)
        if len(marks) >= P.MAX_MARKS:
            break
    marks.sort(key=lambda mk: (mk["box"][1], mk["box"][0]))
    return {"marks": marks, "windows": [{"app": "phone", "name": "Android", "box": [0, 0, sw, sh],
                                          "role": "frame", "active": True, "id": 1,
                                          "marks": len(marks)}]}


def kvm_for_accounts(dev: Path = Path("/dev/kvm"), *, chooser: Optional[Callable] = None,
                     chmod: Callable = os.chmod) -> Tuple[bool, str]:
    """Whether KVM opens here — made first if the node is missing, as the VM
    backend makes it — and, when it does, opened to the accounts that run the
    emulator: `(ok, why)`."""
    if chooser is None:
        from workstation.vm import choose_accel as chooser
    accel, why = chooser(dev, want="auto")
    if accel != "kvm":
        return False, why.rstrip(".").replace("No KVM: ", "")
    try:
        st = os.stat(dev)
        if stat.S_ISCHR(st.st_mode) and st.st_mode & 0o006 != 0o006:
            chmod(str(dev), 0o666)
    except OSError as e:
        return False, f"{dev} could not be opened to the workstation's accounts ({e.strerror or e})"
    return True, why


# ── one person's phone ───────────────────────────────────────────────────────

class AccountPhone:
    """The account's emulator and the scrcpy that shows it, started and
    stopped together; the state the `phone` route answers."""

    def __init__(self, system, account: str, screen, *, memory_mib: int = DEFAULT_MEMORY_MIB,
                 claim_port: Optional[Callable[[str], Optional[int]]] = None,
                 release_port: Optional[Callable[[str], None]] = None,
                 can_start: Optional[Callable[[str], Optional[str]]] = None,
                 kvm: Optional[Callable[[], Tuple[bool, str]]] = None) -> None:
        self.system = system
        self.account = account
        self.screen = screen
        self.memory_mib = memory_mib
        self._claim_port = claim_port or (lambda a: CONSOLE_PORTS[0])
        self._release_port = release_port or (lambda a: None)
        self._can_start = can_start or (lambda a: None)
        self._kvm = kvm or kvm_for_accounts
        self.lock = threading.RLock()
        self.state = "off"
        self.why = ""
        self.device = self._saved_device()
        self.posture: Optional[str] = None
        self.rotation = 0
        self.port: Optional[int] = None
        self.emulator: Optional[subprocess.Popen] = None
        self.scrcpy: Optional[subprocess.Popen] = None
        self.used_at = time.monotonic()
        self.watchers = 0
        self._booting: Optional[threading.Thread] = None
        self._avail: Optional[Tuple[float, Optional[str]]] = None
        self.mobile: Optional[MobileView] = None   # `B1753`: the mobile view's Firefox

    # -- what it is -------------------------------------------------------------

    def home(self) -> Path:
        return Path(self.system.home(self.account))

    def uid(self) -> int:
        return self.system.uid(self.account)

    def _run_as(self) -> Tuple[List[str], Dict[str, str]]:
        """`(prefix, env)` to run as the account, without the desktop's display
        (the phone has its own): the Ubuntu system's keyword, where it has one."""
        try:
            prefix, env = self.system.run_as(self.account, with_display=False)
        except TypeError:
            prefix, env = self.system.run_as(self.account)
        env = dict(env)
        env.pop("DISPLAY", None)
        env.pop("XAUTHORITY", None)
        return prefix, env

    def serial(self) -> Optional[str]:
        return f"emulator-{self.port}" if self.port else None

    def availability(self) -> Optional[str]:
        """Why this workstation can run no phone at all — not Android and not
        the mobile view (`B1753`) — or None when it can run one."""
        why = self.android_why()
        if why is None or self.mobile_why() is None:
            return None
        return why

    def mobile_why(self) -> Optional[str]:
        """`B1753`. Why the mobile view cannot run here, or None."""
        if self.screen is None:
            return NO_SCREEN
        if not find_firefox():
            return "This workstation has no Firefox, so it has no mobile view either."
        return None

    def mode(self) -> Optional[str]:
        """`B1753`. "android" where the real phone runs, "mobile_view" where
        only the mobile view does, None where neither."""
        if self.android_why() is None:
            return "android"
        return "mobile_view" if self.mobile_why() is None else None

    def android_why(self) -> Optional[str]:
        """Why this workstation cannot run Android, or None when it can —
        asked again at most every `AVAILABILITY_TRUST_S`, since every command
        the account runs asks it (`Phones.env_of`)."""
        now = time.monotonic()
        if self._avail is not None and now - self._avail[0] < AVAILABILITY_TRUST_S:
            return self._avail[1]
        why = self._availability()
        self._avail = (now, why)
        return why

    def _availability(self) -> Optional[str]:
        import platform
        arch = platform.machine().lower()
        if arch not in ("x86_64", "amd64"):
            return NOT_X86.format(arch=arch or "another architecture")
        found = tools()
        if not found["emulator"] or not found["adb"]:
            return BUILT_WITHOUT
        if not (sdk_root() / image_parts(image_package())["sysdir"]).is_dir():
            return BUILT_WITHOUT
        if not found["scrcpy"]:
            return BUILT_WITHOUT
        ok, why = self._kvm()
        if not ok:
            return NO_KVM.format(why=why)
        return None

    def env(self) -> Dict[str, str]:
        """What the emulator, adb and scrcpy run with, as the account — and
        what the account's own shell gets, so `adb` there reaches this phone."""
        home = self.home()
        root = sdk_root()
        out = {"ANDROID_SDK_ROOT": str(root), "ANDROID_HOME": str(root),
               "ANDROID_AVD_HOME": str(home / ".android" / "avd"),
               "ANDROID_EMULATOR_HOME": str(home / ".android"),
               "ANDROID_ADB_SERVER_PORT": str(adb_port(self.uid())),
               "ADB": str(root / "platform-tools" / "adb")}
        if self.serial():
            out["ANDROID_SERIAL"] = self.serial()
        return out

    def screen_size(self) -> Tuple[int, int]:
        """The phone's screen now: the device's, or (`B1753`) the mobile
        view's, which turns and folds with it."""
        if self.mode() == "mobile_view":
            return mobile_view_size(self.device, self.posture, self.rotation)
        return P.phone_screen_size(self.device)

    def info(self, action: str = "status") -> Dict:
        mode = self.mode()
        why = self.why if self.state == "unavailable" else ""
        if self.state == "off":
            why = self.availability() or ""
        d = P.PHONE_DEVICES.get(self.device) or {}
        out = {"ok": True, "action": action, "available": not why,
               "state": "unavailable" if why else self.state, "device": self.device,
               "devices": [{"id": k, "name": v["name"], "maker": v["maker"], "kind": v["kind"],
                            "foldable": v["kind"] == "foldable", "width": v["width"],
                            "height": v["height"], "density": v["density"]}
                           for k, v in P.PHONE_DEVICES.items()],
               "posture": self.posture if d.get("kind") == "foldable" else None,
               "rotation": self.rotation,
               "screen": list(self.screen_size()),
               "accel": "kvm" if self.state in ("starting", "on") and mode == "android" else None,
               "android": image_package(),
               "mode": mode}
        if mode == "mobile_view":
            out["why_not_android"] = (self.android_why() or "")[:500]
            out["user_agent"] = mobile_user_agent(self.device)
        if why:
            out["why"] = why[:500]
        return out

    # -- the person's choice, kept in their home -------------------------------

    def _saved_device(self) -> str:
        import json
        try:
            raw = json.loads((self.home() / PREFS_FILE).read_text(encoding="utf-8"))
            device = raw.get("device") if isinstance(raw, dict) else None
        except (OSError, ValueError, TypeError):
            device = None
        return device if device in P.PHONE_DEVICES else P.PHONE_DEFAULT_DEVICE

    def _as_account(self):
        """Files in the home are written as the account (`fs_identity`), never
        as root through a link the account could have put there; a system
        that is one user already (a test's) says so with `files_as`."""
        hook = getattr(self.system, "files_as", None)
        if callable(hook):
            return hook(self.account)
        from workstation.ubuntu import fs_identity
        uid = self.uid()
        return fs_identity(uid, uid)

    def _write_as_account(self, path: Path, text: str) -> None:
        with self._as_account():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)

    def _save_device(self) -> None:
        import json
        try:
            self._write_as_account(self.home() / PREFS_FILE, json.dumps({"device": self.device}))
        except OSError as e:
            logger.info("phone for %s: the choice of device was not kept: %s", self.account, e)

    def _write_avd(self) -> None:
        """The device's folder and its `.ini` in the account's home, rewritten
        every start so a change to the catalogue reaches a device made before
        it; the device's data (its disk, its snapshot) is never touched."""
        package = image_package()
        avd_home = self.home() / ".android" / "avd"
        folder = avd_home / (avd_name(self.device) + ".avd")
        self._write_as_account(folder / "config.ini", avd_config(self.device, package,
                                                                 memory_mib=self.memory_mib))
        self._write_as_account(avd_home / (avd_name(self.device) + ".ini"),
                               avd_ini(self.device, avd_home, package))
        # `Law 16`: the emulator looks for its own updates unless it checked lately.
        self._write_as_account(self.home() / ".android" / "emu-update-last-check.ini",
                               "Android.Emulator.LastCheck=4102444800000\n")

    # -- life -------------------------------------------------------------------

    def running(self) -> bool:
        if self.mobile is not None:
            return self.mobile.proc is not None and self.mobile.proc.poll() is None
        return self.emulator is not None and self.emulator.poll() is None

    def touch(self) -> None:
        self.used_at = time.monotonic()

    def start(self, device: Optional[str] = None) -> Dict:
        with self.lock:
            self.touch()
            if device is not None:
                if device not in P.PHONE_DEVICES:
                    raise PhoneError("bad_request",
                                     f"“device” is one of {', '.join(P.PHONE_DEVICES)}.")
                if device != self.device and self.running():
                    self._stop_locked()
                if device != self.device:
                    self.device = device
                    self._save_device()
            if self.running() and self.state in ("starting", "on"):
                return self.info("start")
            why = self.availability()
            if why:
                self.state, self.why = "unavailable", why
                return self.info("start")
            if self.mode() == "mobile_view":
                return self._start_mobile()
            refused = self._can_start(self.account)
            if refused:
                raise PhoneError("unavailable", refused)
            if self.screen is None:
                self.state, self.why = "unavailable", NO_SCREEN
                return self.info("start")
            self._stop_locked()
            port = self._claim_port(self.account)
            if port is None:
                raise PhoneError("unavailable", "Every phone this workstation can run is running.")
            self.port = port
            self._write_avd()
            prefix, env = self._run_as()
            env = {**env, **self.env()}
            self._adb_quiet(["start-server"])
            try:
                # What the emulator says goes to a file in the person's home,
                # which is where a phone that will not boot says why.
                with self._as_account():
                    fd = os.open(self.home() / LOG_FILE,
                                 os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                log = os.fdopen(fd, "wb")
                try:
                    self.emulator = subprocess.Popen(
                        [*prefix, *emulator_argv(tools()["emulator"], self.device, port=port,
                                                 memory_mib=self.memory_mib)],
                        env=env, cwd=str(self.home()), stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                finally:
                    log.close()
            except OSError as e:
                self._release()
                self.state, self.why = "unavailable", f"The emulator did not start: {e}."
                return self.info("start")
            self.state, self.why = "starting", ""
            self.posture = "open" if P.PHONE_DEVICES[self.device]["kind"] == "foldable" else None
            self.rotation = 0
            self._booting = threading.Thread(target=self._boot, args=(self.emulator,), daemon=True)
            self._booting.start()
            logger.info("phone for %s: %s starting on console port %s", self.account,
                        self.device, port)
            return self.info("start")

    def _boot(self, proc: subprocess.Popen) -> None:
        """Wait for Android to say it has booted, then put scrcpy on the
        phone's screen. A phone that stops or never boots says why."""
        deadline = time.monotonic() + BOOT_TIMEOUT_S
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                with self.lock:
                    if self.emulator is proc:
                        self.state = "unavailable"
                        self.why = (f"The emulator stopped while the phone was booting (exit "
                                    f"{proc.returncode}). ~/{LOG_FILE} in the workstation says "
                                    f"why{self._last_words()}.")
                        self._release()
                return
            if self.adb(["shell", "getprop", "sys.boot_completed"], timeout=10.0,
                        quiet=True).strip() == "1":
                break
            time.sleep(2.0)
        else:
            with self.lock:
                if self.emulator is proc:
                    self.state = "unavailable"
                    self.why = (f"The phone did not finish booting in {int(BOOT_TIMEOUT_S)} s. "
                                "Stop it and start it again.")
            return
        with self.lock:
            if self.emulator is not proc:
                return
            try:
                self._show()
            except PhoneError as e:
                self.state, self.why = "unavailable", e.message
                return
            self.state = "on"
            logger.info("phone for %s: %s is on", self.account, self.device)

    # -- `B1753`: the mobile view -------------------------------------------

    def _start_mobile(self) -> Dict:
        self._stop_locked()
        self.posture = "open" if P.PHONE_DEVICES[self.device]["kind"] == "foldable" else None
        self.rotation = 0
        self.state, self.why = "starting", ""
        self._booting = threading.Thread(target=self._boot_mobile, daemon=True)
        self._booting.start()
        logger.info("phone for %s: %s starting as a mobile view", self.account, self.device)
        return self.info("start")

    def _boot_mobile(self, url: Optional[str] = None) -> None:
        with self.lock:
            if self.state != "starting":
                return
            try:
                self._open_mobile(url)
            except Exception as e:  # noqa: BLE001 — said on the phone, never a silent "starting"
                if self.mobile is not None:
                    self.mobile.stop()
                    self.mobile = None
                said = str(getattr(e, "message", None) or e)
                self.state, self.why = "unavailable", f"The mobile view did not start: {said}"
                logger.info("phone for %s: %s", self.account, self.why)
                return
            self.state = "on"

    def _open_mobile(self, url: Optional[str]) -> None:
        """Firefox on the phone's screen as this device, at `url` or Home."""
        size = mobile_view_size(self.device, self.posture, self.rotation)
        set_size = getattr(self.screen, "set_size", None)
        if callable(set_size):
            set_size(size)
        prefix, env = self._run_as()
        env.setdefault("HOME", str(self.home()))
        env["MOZ_CRASHREPORTER_DISABLE"] = "1"
        own = getattr(self.system, "own", None)
        b = MobileView(prefix, env, self.home() / MOBILE_PROFILE_DIR, False,
                       own=(lambda paths: own(self.account, paths)) if callable(own) else None,
                       screen=self.screen)
        b.window_size = size
        b.extra_prefs = mobile_view_prefs(self.device, self.posture, self.rotation)
        self.mobile = b
        b.start()
        if url:
            b._act("open", {"url": url})
        else:
            self._go_home()

    def _reshape(self) -> None:
        """The mobile view again at its new shape, on the page it was on."""
        url = None
        try:
            url = self.mobile.state().get("url") if self.mobile is not None else None
        except BrowserError:
            url = None
        if self.mobile is not None:
            self.mobile.stop()
            self.mobile = None
        self.state = "starting"
        self._boot_mobile(url if url and url.startswith(("http://", "https://")) else None)
        if self.state != "on":
            raise PhoneError("unavailable", self.why or "The mobile view did not come back.")

    def _go_home(self) -> None:
        """Firefox's own Home page — not an address `check_url` lets through,
        so opened directly; a Firefox that will not open it shows a blank page."""
        b = self.mobile
        ctx = b._ctx()
        for url in (MOBILE_HOME, "about:blank"):
            try:
                b._call("browsingContext.navigate", {"context": ctx, "url": url, "wait": "none"})
                return
            except BrowserError:
                continue

    def _mobile_key(self, name: str) -> None:
        b = self.mobile
        ctx = b._ctx()
        if name == "back":
            try:
                b._call("browsingContext.traverseHistory", {"context": ctx, "delta": -1})
            except BrowserError:
                pass  # nothing to go back to: a phone's Back does nothing there either
        elif name == "home":
            self._go_home()
        else:
            key = name.replace("_", " ")
            raise PhoneError("bad_request", MOBILE_NO_KEY.format(key=key, why=self.android_why()))

    def _show(self) -> None:
        """scrcpy on the phone's screen, the screen sized to this device."""
        size = P.phone_screen_size(self.device)
        set_size = getattr(self.screen, "set_size", None)
        if callable(set_size):
            set_size(size)
        try:
            display = self.screen.start()
        except Exception as e:  # noqa: BLE001 — said, and the phone is still on for adb
            raise PhoneError("unavailable", getattr(e, "message", None) or str(e))
        prefix, env = self._run_as()
        env = {**env, **self.env(), "DISPLAY": display,
               "XAUTHORITY": str(self.screen.auth_path())}
        scrcpy = tools()["scrcpy"]
        if self.scrcpy is not None and self.scrcpy.poll() is None:
            _kill(self.scrcpy)
        try:
            self.scrcpy = subprocess.Popen(
                [*prefix, *scrcpy_argv(scrcpy, self.serial(), size,
                                       version=scrcpy_version(scrcpy))],
                env=env, cwd=str(self.home()), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            raise PhoneError("unavailable", f"The phone's screen could not be shown: {e}.")

    def ensure_shown(self) -> None:
        """scrcpy again if it stopped while the phone stayed on — and a
        mobile view whose Firefox was closed is off (`B1753`)."""
        with self.lock:
            if self.mobile is not None:
                if self.state == "on" and not self.running():
                    self.mobile = None
                    self.state = "off"
                return
            if self.state == "on" and (self.scrcpy is None or self.scrcpy.poll() is not None):
                try:
                    self._show()
                except PhoneError as e:
                    logger.info("phone for %s: %s", self.account, e.message)

    def stop(self) -> Dict:
        with self.lock:
            self._stop_locked()
            return self.info("stop")

    def _stop_locked(self) -> None:
        if self.mobile is not None:
            self.mobile.stop()
            self.mobile = None
        if self.scrcpy is not None:
            _kill(self.scrcpy)
            self.scrcpy = None
        if self.emulator is not None:
            if self.emulator.poll() is None:
                # Asked to stop, so it saves where it was and boots back there.
                self.adb(["emu", "kill"], timeout=10.0, quiet=True)
                try:
                    self.emulator.wait(timeout=STOP_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    _kill(self.emulator)
            self.emulator = None
        self._release()
        if self.state != "unavailable":
            self.state = "off"
        stop_screen = getattr(self.screen, "stop", None)
        if callable(stop_screen):
            stop_screen()

    def _release(self) -> None:
        if self.port is not None:
            self._release_port(self.account)
        self.port = None

    # -- adb ----------------------------------------------------------------

    def adb(self, args: List[str], *, timeout: float = ADB_TIMEOUT_S, quiet: bool = False,
            data: Optional[bytes] = None, binary: bool = False):
        """One adb command as the account, against this phone."""
        adb = tools()["adb"]
        if not adb:
            raise PhoneError("unavailable", BUILT_WITHOUT)
        prefix, env = self._run_as()
        env = {**env, **self.env()}
        argv = [*prefix, adb] + (["-s", self.serial()] if self.serial() else []) + args
        try:
            done = subprocess.run(argv, env=env, input=data, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=timeout,
                                  cwd=str(self.home()))
        except (OSError, subprocess.TimeoutExpired) as e:
            if quiet:
                return b"" if binary else ""
            raise PhoneError("unavailable", f"The phone did not answer ({type(e).__name__}).")
        if done.returncode != 0 and not quiet:
            said = done.stderr.decode("utf-8", "replace").strip().splitlines()
            raise PhoneError("unavailable", "The phone refused that"
                             + (f": {said[-1][:200]}" if said else "."))
        return done.stdout if binary else done.stdout.decode("utf-8", "replace")

    def _adb_quiet(self, args: List[str]) -> None:
        saved, self.port = self.port, None
        try:
            self.adb(args, quiet=True)
        finally:
            self.port = saved

    def _last_words(self) -> str:
        """The emulator's last line, for the sentence: `: <line>` or nothing."""
        try:
            with self._as_account():
                fd = os.open(self.home() / LOG_FILE, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 2000))
                lines = [ln for ln in f.read().decode("utf-8", "replace").splitlines() if ln.strip()]
        except OSError:
            return ""
        return f" (it last said: {lines[-1].strip()[:200]})" if lines else ""

    def _on(self) -> None:
        if not self.running() or self.state != "on":
            raise PhoneError("unavailable", {
                "starting": "The phone is still booting; try again in a moment.",
                "unavailable": self.why or "The phone is not running.",
            }.get(self.state, "The phone is off. Start it first."))
        self.touch()

    def button(self, name) -> Dict:
        if name not in P.PHONE_BUTTONS:
            raise PhoneError("bad_request", f"“button” is one of {', '.join(P.PHONE_BUTTONS)}.")
        with self.lock:
            if name == "power" and self.mobile is not None:
                self._stop_locked()       # `B1753`: the mobile view's Power is off
                return self.info("button")
            self._on()
            if self.mobile is not None:
                self._mobile_key(name)
                return self.info("button")
            self.adb(["shell", "input", "keyevent", str(P.PHONE_BUTTONS[name])])
            return self.info("button")

    def set_posture(self, posture) -> Dict:
        if posture not in P.PHONE_POSTURES:
            raise PhoneError("bad_request", f"“posture” is one of {', '.join(P.PHONE_POSTURES)}.")
        with self.lock:
            self._on()
            if P.PHONE_DEVICES[self.device]["kind"] != "foldable":
                raise PhoneError("bad_request", f"The {P.PHONE_DEVICES[self.device]['name']} "
                                                "does not fold.")
            if self.mobile is not None:
                if posture != self.posture:
                    self.posture = posture
                    self._reshape()
                return self.info("posture")
            self.adb(["emu", "fold" if posture == "closed" else "unfold"])
            self.posture = posture
            return self.info("posture")

    def rotate(self) -> Dict:
        with self.lock:
            self._on()
            if self.mobile is not None:
                self.rotation = (self.rotation + 1) % 4
                self._reshape()
                return self.info("rotate")
            self.adb(["emu", "rotate"])
            self.rotation = (self.rotation + 1) % 4
            return self.info("rotate")

    def open_url(self, raw) -> Dict:
        url = check_url(raw)
        with self.lock:
            self._on()
            if self.mobile is not None:
                self.mobile._act("open", {"url": url})
                return self.info("open_url")
            # adb joins its arguments into one line for the phone's shell, so
            # the address is quoted for that shell, whole.
            self.adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d",
                      shlex.quote(url)])
            return self.info("open_url")

    def marks(self) -> Dict:
        with self.lock:
            self._on()
            if self.mobile is not None:
                raise PhoneError("unavailable", MOBILE_NO_MARKS)
        xml = self.adb(["exec-out", "uiautomator", "dump", "/dev/tty"], timeout=30.0)
        return marks_from_dump(xml, P.phone_screen_size(self.device))


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, 15)
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass  # already gone between the wait and the kill


# ── everyone's phones ────────────────────────────────────────────────────────

def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return min(max(v, lo), hi)


class Phones:
    """Every account's phone, made on first ask; a phone nobody used or
    watched for `idle_s` is stopped, and at most `max_running` run at once —
    each one is a whole Android, about two gigabytes of memory."""

    def __init__(self, system, *, kvm: Optional[Callable[[], Tuple[bool, str]]] = None) -> None:
        self.system = system
        self.kvm = kvm
        self.idle_s = _env_int(IDLE_ENV, DEFAULT_IDLE_MIN, 0, 24 * 60) * 60.0
        self.max_running = _env_int(MAX_RUNNING_ENV, DEFAULT_MAX_RUNNING, 1, len(CONSOLE_PORTS))
        self.memory_mib = _env_int(MEMORY_ENV, DEFAULT_MEMORY_MIB, 1024, 16384)
        self._by_account: Dict[str, AccountPhone] = {}
        self._ports: Dict[str, int] = {}
        self._lock = threading.Lock()
        self._reaper: Optional[threading.Thread] = None

    def get(self, account: str) -> AccountPhone:
        with self._lock:
            p = self._by_account.get(account)
            if p is None:
                self.system.ensure(account)
                display_of = getattr(self.system, "phone_display", None)
                screen = None
                if callable(display_of):
                    try:
                        screen = display_of(account)
                    except Exception:  # noqa: BLE001 — no screen of its own: said at start
                        screen = None
                p = AccountPhone(self.system, account, screen, memory_mib=self.memory_mib,
                                 claim_port=self._claim, release_port=self._free,
                                 can_start=self._room_for, kvm=self.kvm)
                self._by_account[account] = p
            if self._reaper is None and self.idle_s:
                self._reaper = threading.Thread(target=self._reap, daemon=True)
                self._reaper.start()
            return p

    def env_of(self, account: str) -> Dict[str, str]:
        """What the account's shell gets so its `adb` reaches its own phone;
        nothing for an account whose phone was never asked for."""
        p = self._by_account.get(account)
        return p.env() if p is not None and p.android_why() is None else {}

    def _room_for(self, account: str) -> Optional[str]:
        running = [a for a, p in self._by_account.items() if a != account and p.running()]
        if len(running) >= self.max_running:
            return (f"This workstation already runs {len(running)} phones, its most at once "
                    f"({MAX_RUNNING_ENV}). One stops after {int(self.idle_s // 60)} minutes "
                    "unused, or an admin can raise the limit.")
        return None

    def _claim(self, account: str) -> Optional[int]:
        with self._lock:
            if account in self._ports:
                return self._ports[account]
            taken = set(self._ports.values())
            for port in CONSOLE_PORTS:
                if port in taken or _listening(port) or _listening(port + 1):
                    continue
                self._ports[account] = port
                return port
        return None

    def _free(self, account: str) -> None:
        with self._lock:
            self._ports.pop(account, None)

    def _reap(self) -> None:
        while True:
            time.sleep(REAP_EVERY_S)
            now = time.monotonic()
            for account, p in list(self._by_account.items()):
                if p.running() and not p.watchers and now - p.used_at > self.idle_s:
                    logger.info("phone for %s: unused for %d minutes, stopped", account,
                                int(self.idle_s // 60))
                    try:
                        p.stop()
                    except Exception as e:  # noqa: BLE001
                        logger.warning("phone for %s did not stop: %s", account, e)

    def stop(self, account: str) -> None:
        with self._lock:
            p = self._by_account.pop(account, None)
        if p is not None:
            p.stop()

    def stop_all(self) -> None:
        with self._lock:
            items = list(self._by_account.values())
            self._by_account.clear()
        for p in items:
            try:
                p.stop()
            except Exception:  # noqa: BLE001
                pass


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


__all__ = ["AccountPhone", "PhoneError", "Phones", "adb_port", "avd_config", "avd_ini",
           "avd_name", "check_url", "emulator_argv", "image_parts", "kvm_for_accounts",
           "marks_from_dump", "scrcpy_argv", "tools"]
