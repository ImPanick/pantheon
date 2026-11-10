# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone: a real Android device per person, in their workstation. `B1751`.

The owner, 2026-11-02: *"a mobile device emulator... with various real device
emulation (Samsung Galaxy Z Fold, Google Pixel Pro, etc...) with the real OS,
"touch" controls (via mouse)... That way the user can troubleshoot mobile
apps, or even use the mobile device mock up to run their platforms/websites."*

WHAT RUNS
=========

* **Google's Android Emulator**, from the Android SDK the image was built with
  (`provision.sh phone`, after an explicit licensed install), booting a real
  Android system image (`PHONE_IMAGE`, Google APIs, x86_64) — the OS a phone
  runs, not a look-alike. It runs **as the account inside their own VM**,
  headless (`-no-window`),
  with each device's data in the account's own home
  (`~/.android/avd/pantheon_<device>_<image-hash>.avd`, or a matching legacy AVD), so a person's phone is theirs, is
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

**KVM and isolation.** The outer VM host must use actual KVM, and this guest
must also have usable KVM. A TCG guest can expose an emulated KVM node; that
does not make Android hardware-accelerated. Shared container/remote accounts
are refused for Android even when their ports differ or sudo is off. The VM
backend forwards only its authenticated daemon, not the phone's ports. Nested
Android is experimental; Google's supported configurations exclude running an
accelerated emulator inside another VM. See `docs/setup.md` for prerequisites.

**Its own adb.** The account's adb server and emulator console/device ports
stay on that user's guest loopback. Each VM has separate disks and its own
daemon token. The user's own agents share this device; host administrators
remain trusted. Separate ports on a shared loopback were never an isolation
boundary (`THREAT_MODEL.md`).

EXPLICIT WEB PREVIEW (`B1753`)
======================================

The web preview survives as an explicit `preview` action. Android `start` and
`install` never launch it. The workstation's own Firefox runs alone on the
phone's screen in kiosk mode, at the device's shape, with
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

import base64
import hashlib
import logging
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from functools import lru_cache
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
PLAY_IMAGE = "system-images;android-35;google_apis_playstore;x86_64"
TRANSFER_DEST = "/sdcard/Download/Pantheon"
TRANSFER_TIMEOUT_S = 90.0
ISOLATION_REQUIRED = P.PHONE_ISOLATION_REQUIRED
IDLE_ENV = "PANTHEON_PHONE_IDLE_MIN"
MAX_RUNNING_ENV = "PANTHEON_PHONE_MAX_RUNNING"
MEMORY_ENV = "PANTHEON_PHONE_MEMORY_MIB"
DEFAULT_IDLE_MIN = 30
DEFAULT_MAX_RUNNING = 2
DEFAULT_MEMORY_MIB = 2048
MIN_SCRCPY_VERSION = (2, 4)  # Android 15 display API support, upstream scrcpy v2.4
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

BUILT_WITHOUT = ("This VM has no working Android runtime or installer. Rebuild the workstation-vm "
                 "host from the current checkout and restart your VM, preserving its disk. "
                 "Install Android only after a person accepts the Android SDK License (docs/setup.md).")
NO_KVM = ("Android needs usable KVM inside your own VM, and the check failed ({why}). "
          "Windows virtualization toggles alone do not prove this path works. Ask an admin "
          "to verify nested KVM and the emulator's -accel-check inside the user's VM "
          "(docs/setup.md, Mobile Emulator). Browser preview is a separate web-only option.")
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


# `B1756`. Installing a device when it is picked. The owner, 2026-11-07: *"The
# user should be able to pick from a list of devices and Pantheon should pull
# the image/install configure etc."* The daemon runs the same `provision.sh
# phone` step the image build runs — the same pinned, checked tools — for the
# device's system image, as root, one install at a time for the workstation.
PROVISION = "/opt/pantheon-workstation/provision/provision.sh"
PROVISION_ENV = "PANTHEON_PHONE_PROVISION"
LICENSE_URL = "https://developer.android.com/studio/terms"
INSTALL_FREE_BYTES = 8 * 1024 ** 3     # the SDK, the emulator and one image, with room
INSTALL_TIMEOUT_S = 3 * 3600.0
INSTALL_STEPS = {
    "libraries": "Installing the phone's libraries",
    "tools": "Fetching Google's Android SDK tools",
    "android": "Downloading Android and the emulator",
    "done": "Installed",
}
ANDROID_NAMES = {33: "Android 13", 34: "Android 14", 35: "Android 15", 36: "Android 16"}
NEEDS_LICENSE = ("Installing the phone accepts the Android SDK License ({url}). A person accepts "
                 "it once, in the Workbench's Devices room; then any device can be installed.")
CANNOT_INSTALL = ("This VM cannot install Android ({why}). Check its disk space and update the "
                  "workstation-vm host from the current checkout, then restart your VM without "
                  "resetting its data (docs/setup.md, Mobile Emulator).")


class PhoneError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def device_image(device: str) -> str:
    """`B1756`. The system image a device runs: its own (`"image"` in the
    catalogue) or the workstation's default (`image_package`)."""
    d = P.PHONE_DEVICES.get(device) or {}
    return str(d.get("image") or image_package())


def android_name(package: str) -> str:
    """"Android 15" for `system-images;android-35;…`, the API level otherwise."""
    try:
        api = int(image_parts(package)["api"].split("-")[-1])
    except (PhoneError, ValueError, KeyError):
        return package
    return ANDROID_NAMES.get(api, f"Android API {api}")


def image_kind(package: str) -> str:
    tag = image_parts(package)["tag"]
    if tag == "google_apis_playstore":
        return "google_play"
    return {"google_apis": "google_apis", "default": "aosp"}.get(tag, "custom")


def image_installed(package: str) -> bool:
    try:
        return (sdk_root() / image_parts(package)["sysdir"]).is_dir()
    except PhoneError:
        return False


def tools_installed() -> bool:
    found = tools()
    return bool(found["emulator"] and found["adb"] and found["scrcpy"]
                and scrcpy_version(found["scrcpy"]) >= MIN_SCRCPY_VERSION)


def license_accepted() -> bool:
    """Whether Google's SDK License was accepted here: sdkmanager writes its
    hash under `licenses/` once it is."""
    return (sdk_root() / "licenses" / "android-sdk-license").is_file()


def provision_script() -> Optional[str]:
    override = os.environ.get(PROVISION_ENV)
    if override:
        return override if os.path.isfile(override) else None
    # The VM's read-only app disk carries this daemon's current installer;
    # its original base image's baked script may predate the display bridge.
    current = Path(__file__).with_name("provision.sh")
    if current.is_file():
        return str(current)
    return PROVISION if os.path.isfile(PROVISION) else None


def can_install() -> Optional[str]:
    """Why this daemon cannot install the phone, or None when it can."""
    if not provision_script():
        return "it has no provisioning script"
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return "its daemon does not run as root"
    root = sdk_root()
    probe = root if root.exists() else root.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        free = None
    if free is not None and free < INSTALL_FREE_BYTES and not tools_installed():
        return f"it has {free // 1024 ** 3} GB free and needs about {INSTALL_FREE_BYTES // 1024 ** 3}"
    return None


_STEP_RE = re.compile(r"^provision: step: ([a-z]+)\s*$")
_PERCENT_RE = re.compile(r"(\d{1,3})%")


def read_progress(line: str, state: Dict) -> None:
    """One line of `provision.sh phone`'s output into the install's state:
    its step, sdkmanager's percent, and what it last said."""
    line = line.strip()
    if not line:
        return
    m = _STEP_RE.match(line)
    if m:
        if m.group(1) in INSTALL_STEPS:
            state["step"] = m.group(1)
            state["percent"] = 100 if m.group(1) == "done" else 0
        return
    m = _PERCENT_RE.search(line)
    if m and "[" in line:
        state["percent"] = min(100, int(m.group(1)))
        said = line.split("%", 1)[-1].strip()
        if said:
            state["said"] = said[:160]
        return
    if line.startswith("provision: "):
        state["said"] = line[len("provision: "):][:160]


class Installer:
    """`B1756`. The workstation's one phone install at a time: `provision.sh
    phone` for a system image, as root, its progress read as it goes."""

    def __init__(self, *, run: Optional[Callable] = None) -> None:
        self.lock = threading.Lock()
        self.state: Dict = {"state": "idle"}
        self._run = run or self._provision
        self._thread: Optional[threading.Thread] = None

    def info(self) -> Dict:
        with self.lock:
            out = dict(self.state)
        if out.get("step"):
            out["step_label"] = INSTALL_STEPS.get(out["step"], out["step"])
        return out

    def running(self) -> bool:
        with self.lock:
            return self.state.get("state") == "running"

    def start(self, package: str, *, accept: bool, then: Optional[Callable[[bool], None]] = None) -> Dict:
        """Begin installing `package` (and the tools, the first time); `then`
        is called with whether it worked. One install at a time."""
        with self.lock:
            if self.state.get("state") == "running":
                if self.state.get("package") == package:
                    return dict(self.state)
                raise PhoneError("busy", "Another device is being installed on this workstation; "
                                         "wait for it to finish.")
            why = can_install()
            if why:
                raise PhoneError("unavailable", CANNOT_INSTALL.format(why=why))
            if not (accept or license_accepted()):
                raise PhoneError("license", NEEDS_LICENSE.format(url=LICENSE_URL))
            self.state = {"state": "running", "package": package, "android": android_name(package),
                          "step": "", "percent": 0, "said": "", "started": time.time()}
            self._thread = threading.Thread(target=self._work, args=(package, then), daemon=True)
            self._thread.start()
            return dict(self.state)

    def _work(self, package: str, then: Optional[Callable[[bool], None]]) -> None:
        try:
            code = self._run(package, self._line)
        except Exception as e:  # noqa: BLE001 — said on the phone, never a silent "running"
            code, why = -1, str(e)
        else:
            why = ""
        ok = code == 0 and image_installed(package) and tools_installed()
        with self.lock:
            last = self.state.get("said") or ""
            self.state.update(state="done" if ok else "failed", percent=100 if ok else
                              self.state.get("percent", 0), finished=time.time())
            if not ok:
                self.state["why"] = (f"The install did not finish (exit {code}"
                                     + (f": {why or last}" if (why or last) else "") + ").")[:400]
        logger.info("phone install of %s: %s", package, "done" if ok else self.state.get("why"))
        if then is not None:
            try:
                then(ok)
            except Exception as e:  # noqa: BLE001 — the install's own state already says how it went
                logger.warning("phone install of %s: what follows it failed: %s", package, e)

    def _line(self, line: str) -> None:
        with self.lock:
            read_progress(line, self.state)

    @staticmethod
    def _provision(package: str, on_line: Callable[[str], None]) -> int:
        env = {**os.environ, "PHONE_IMAGE": package, "PHONE_RUNTIME": "yes",
               "PHONE_ACCEPT_LICENSE": "yes"}
        proc = subprocess.Popen(["sh", provision_script() or PROVISION, "phone", str(sdk_root())],
                                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
        assert proc.stdout is not None
        buf = b""
        deadline = time.monotonic() + INSTALL_TIMEOUT_S
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            # sdkmanager redraws its bar with carriage returns
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for raw in parts:
                on_line(raw.decode("utf-8", "replace"))
            if time.monotonic() > deadline:
                _kill(proc)
                return -1
        if buf:
            on_line(buf.decode("utf-8", "replace"))
        return proc.wait()


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

    bundled = there(root / "scrcpy" / "scrcpy") if (root / "scrcpy" / "scrcpy-server").is_file() else None
    return {"emulator": there(root / "emulator" / "emulator"),
            "adb": there(root / "platform-tools" / "adb"),
            "scrcpy": bundled or shutil.which("scrcpy")}


def avd_name(device: str) -> str:
    return AVD_PREFIX + device


def avd_config(device: str, package: str, *, memory_mib: int = DEFAULT_MEMORY_MIB,
               name: Optional[str] = None) -> str:
    """The device's `config.ini`: its screen exactly as the maker ships it,
    the system image, no skin (scrcpy draws the screen; Pantheon draws the
    bezel), no audio, software GL (no GPU is assumed), and for a foldable the
    hinge and the cover screen as the SDK's own foldables declare them."""
    d = P.PHONE_DEVICES[device]
    img = image_parts(package)
    w, h = d["width"], d["height"]
    lines = {
        "AvdId": name or avd_name(device),
        "avd.ini.displayname": d["name"],
        "avd.ini.encoding": "UTF-8",
        "abi.type": img["abi"],
        "hw.cpu.arch": "arm64" if img["abi"] == "arm64-v8a" else img["abi"],
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
        "PlayStore.enabled": "true" if image_kind(package) == "google_play" else "false",
        "fastboot.forceColdBoot": "yes",
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


def avd_ini(device: str, avd_home: Path, package: str, *, name: Optional[str] = None) -> str:
    """The `<name>.ini` beside the device's folder, which is how the emulator
    finds it."""
    name = name or avd_name(device)
    return (f"avd.ini.encoding=UTF-8\npath={avd_home / (name + '.avd')}\n"
            f"path.rel=avd/{name}.avd\ntarget={image_parts(package)['target']}\n")


def emulator_argv(emulator: str, device: str, *, port: int, memory_mib: int,
                  name: Optional[str] = None) -> List[str]:
    """The emulator, headless — scrcpy is the window — on KVM, with software
    GL, a visible Android boot animation, and no metrics. Cold boot preserves
    userdata, but deliberately does not resume a snapshot past the boot screen."""
    return [emulator, "-avd", name or avd_name(device), "-port", str(port), "-no-window", "-no-audio",
            "-no-snapshot-load", "-gpu", "swiftshader_indirect", "-accel", "on",
            "-memory", str(memory_mib), "-no-metrics"]


def scrcpy_version(scrcpy: str) -> Tuple[int, int]:
    """scrcpy's `(major, minor)`, or `(1, 0)` when it does not say: its options
    differ between the release Ubuntu ships and later ones."""
    try:
        stamp = os.stat(scrcpy).st_mtime_ns
    except OSError:
        stamp = None
    return _scrcpy_version(scrcpy, stamp)


@lru_cache(maxsize=16)
def _scrcpy_version(scrcpy: str, stamp: Optional[int]) -> Tuple[int, int]:
    """Cache probes by binary modification time; status polling must not
    spawn subprocesses repeatedly, and provisioning must invalidate a probe."""
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
            "--window-borderless", "--fullscreen", "--window-x", "0", "--window-y", "0",
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
                 kvm: Optional[Callable[[], Tuple[bool, str]]] = None,
                 installer: Optional["Installer"] = None, lifecycle=None) -> None:
        self.system = system
        self.account = account
        self.installer = installer or Installer()   # `B1756`: the workstation's one
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
        self.edition = self._saved_edition()
        self.posture: Optional[str] = None
        self.rotation = 0
        self.port: Optional[int] = None
        self.emulator: Optional[subprocess.Popen] = None
        self.scrcpy: Optional[subprocess.Popen] = None
        self.boot_phase = "off"
        self.used_at = time.monotonic()
        self.watchers = 0
        self._booting: Optional[threading.Thread] = None
        self._avail: Optional[Tuple[float, Optional[str]]] = None
        self.mobile: Optional[MobileView] = None   # `B1753`: the mobile view's Firefox
        self._mobile_cancel: Optional[threading.Event] = None
        # The manager keeps this lease across handle eviction: the display is
        # cached by the system and can outlive any one AccountPhone instance.
        self._mobile_lifecycle = lifecycle if lifecycle is not None else threading.Lock()
        self._android_lifecycle = False
        self._retired = threading.Event()

    # -- what it is -------------------------------------------------------------

    def retire(self) -> None:
        """Invalidate captured handles without waiting for I/O or the phone lock."""
        self._retired.set()

    def _active(self) -> None:
        if self._retired.is_set():
            raise PhoneError("unavailable", "This phone session was replaced. Open the current device again.")

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
        """Android's prerequisite, independently of the optional web preview."""
        return self.android_why()

    def mobile_why(self) -> Optional[str]:
        """`B1753`. Why the mobile view cannot run here, or None."""
        if self.screen is None:
            return NO_SCREEN
        if not find_firefox():
            return "This workstation has no Firefox, so it has no mobile view either."
        return None

    def mode(self) -> Optional[str]:
        """Android capability/producer, or an explicitly started web preview.
        An available Firefox never makes Android available."""
        if self.mobile is not None:
            return "mobile_view"
        if self.emulator is not None and self.running():
            return "android"
        if self.android_why() is None:
            return "android"
        return None

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
        if getattr(self.system, "backend", None) != "vm":
            return ISOLATION_REQUIRED
        arch = platform.machine().lower()
        if arch not in ("x86_64", "amd64"):
            return NOT_X86.format(arch=arch or "another architecture")
        ok, why = self._kvm()
        if not ok:
            return NO_KVM.format(why=why)
        try:
            total_mib = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                                 if line.startswith("MemTotal:"))) // 1024
        except (OSError, ValueError, StopIteration, IndexError):
            total_mib = None
        if total_mib is not None and total_mib < self.memory_mib + 1536:
            return (f"This user's VM has {total_mib} MiB of memory; Android alone needs "
                    f"{self.memory_mib} MiB plus 1536 MiB for the workstation. Ask an admin "
                    "to increase PANTHEON_WORKSTATION_VM_MEMORY_MIB (8192 recommended), then restart your VM.")
        # `B1756`: a phone that is not installed yet is one picking a device
        # installs — where this daemon can install it.
        if tools_installed() and image_installed(self.package()):
            return None
        if can_install() is None:
            return None
        return BUILT_WITHOUT

    def package(self, device: Optional[str] = None) -> str:
        return PLAY_IMAGE if self.edition == "google_play" else device_image(device or self.device)

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
        """The active display at its current posture and orientation, for
        streaming, screenshots, touch and the agent's marks alike."""
        return mobile_view_size(self.device, self.posture, self.rotation)

    def info(self, action: str = "status") -> Dict:
        mode = self.mode()
        why = self.why if self.state == "unavailable" else ""
        if self.state == "off" or (mode != "mobile_view" and self.android_why()):
            why = self.availability() or ""
        d = P.PHONE_DEVICES.get(self.device) or {}
        out = {"ok": True, "action": action, "available": not why,
               "state": "unavailable" if why else self.state, "device": self.device,
               "devices": [{"id": k, "name": v["name"], "maker": v["maker"], "kind": v["kind"],
                            "foldable": v["kind"] == "foldable", "width": v["width"],
                            "height": v["height"], "density": v["density"],
                            "look": P.PHONE_LOOKS.get(k) or {}}   # `B1757`
                           for k, v in P.PHONE_DEVICES.items()],
               "posture": self.posture if d.get("kind") == "foldable" else None,
               "rotation": self.rotation,
               "screen": list(self.screen_size()),
               "screen_is_active": True,
               "accel": "kvm" if self.state in ("starting", "on") and mode == "android" else None,
               "android": self.package(),
               "edition": self.edition,
               "image_kind": image_kind(self.package()),
               "standard_image_kind": image_kind(device_image(self.device)),
               "editions": list(P.PHONE_EDITIONS),
               "isolation": "per_user_vm" if getattr(self.system, "backend", None) == "vm" else "shared",
               "preview_available": self.mobile_why() is None,
               "mode": mode,
               "boot_phase": self.boot_phase,
               "stream_ready": self.stream_ready()}
        # `B1756`: what each device needs, and the install under way.
        ready_tools = tools_installed()
        for entry in out["devices"]:
            pkg = self.package(entry["id"])
            entry["android"] = android_name(pkg)
            entry["installed"] = ready_tools and image_installed(pkg)
        out["installed"] = ready_tools and image_installed(self.package())
        out["license"] = {"accepted": license_accepted() and self._edition_accepted(), "url": LICENSE_URL}
        out["install"] = self.installer.info()
        if mode == "android" and not out["installed"]:
            out["can_install"] = can_install() is None
        if mode == "mobile_view":
            out["why_not_android"] = (self.android_why() or "")[:500]
            out["user_agent"] = mobile_user_agent(self.device)
        if why:
            out["why"] = why[:500]
        out["google_play"] = image_kind(self.package()) == "google_play"
        out["transfer_max_bytes"] = P.MAX_FILE_BYTES
        return out

    # -- the person's choice, kept in their home -------------------------------

    def _saved_device(self) -> str:
        import json
        try:
            raw = json.loads((self.home() / PREFS_FILE).read_text(encoding="utf-8"))
            device = raw.get("device") if isinstance(raw, dict) else None
        except (OSError, ValueError, TypeError):
            device = None
        return device if isinstance(device, str) and device in P.PHONE_DEVICES else P.PHONE_DEFAULT_DEVICE

    def _saved_edition(self) -> str:
        import json
        try:
            raw = json.loads((self.home() / PREFS_FILE).read_text(encoding="utf-8"))
            edition = raw.get("edition") if isinstance(raw, dict) else None
            accepted = raw.get("accepted_editions") if isinstance(raw, dict) else None
            self._accepted_editions = {x for x in accepted if isinstance(x, str) and x in P.PHONE_EDITIONS} \
                if isinstance(accepted, list) else set()
        except (OSError, ValueError, TypeError):
            edition, self._accepted_editions = None, set()
        return edition if edition in P.PHONE_EDITIONS else "standard"

    def _edition_accepted(self) -> bool:
        # Selecting proprietary Google apps is a fresh, explicit choice, even
        # on a VM whose SDK was installed for a different image previously.
        return image_kind(self.package()) != "google_play" or "google_play" in self._accepted_editions

    def select_edition(self, edition) -> Dict:
        if edition not in P.PHONE_EDITIONS:
            raise PhoneError("bad_request", f"edition is one of {', '.join(P.PHONE_EDITIONS)}.")
        with self.lock:
            self._active()
            if self.installer.running():
                raise PhoneError("busy", "Wait for the current Android install to finish.")
            if edition != self.edition:
                self._stop_locked()
                self.state, self.why = "off", ""
                self.edition = edition
                self._avail = None
                self._save_device()
            return self.info("edition")

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
            self._write_as_account(self.home() / PREFS_FILE, json.dumps({"device": self.device,
                "edition": self.edition, "accepted_editions": sorted(self._accepted_editions)}))
        except OSError as e:
            logger.info("phone for %s: the choice of device was not kept: %s", self.account, e)

    def _write_avd(self) -> None:
        """The device's folder and its `.ini` in the account's home, rewritten
        every start so a change to the catalogue reaches a device made before
        it; the device's data (its disk, its snapshot) is never touched."""
        package = self.package()
        avd_home = self.home() / ".android" / "avd"
        self.avd = self._avd_slot(package)
        folder = avd_home / (self.avd + ".avd")
        self._write_as_account(folder / "config.ini", avd_config(self.device, package,
                                                   memory_mib=self.memory_mib, name=self.avd))
        self._write_as_account(avd_home / (self.avd + ".ini"),
                               avd_ini(self.device, avd_home, package, name=self.avd))
        # `Law 16`: the emulator looks for its own updates unless it checked lately.
        self._write_as_account(self.home() / ".android" / "emu-update-last-check.ini",
                               "Android.Emulator.LastCheck=4102444800000\n")

    def _avd_slot(self, package: str) -> str:
        """Reuse legacy userdata only for its original image; never migrate it.

        Different API/tag/ABI gets a separate persistent disk. Unknown legacy
        data is left in place; ambiguous data in a named slot is refused.
        """
        root = self.home() / ".android" / "avd"
        expected = image_parts(package)["sysdir"]
        legacy = avd_name(self.device)
        slot = legacy + "_" + hashlib.sha256(package.encode()).hexdigest()[:12]
        for name in (legacy, slot):
            folder = root / (name + ".avd")
            try:
                with self._as_account():
                    config = (folder / "config.ini").read_text(encoding="utf-8")
                image = next((line.split("=", 1)[1].strip() for line in config.splitlines()
                              if "=" in line and line.split("=", 1)[0].strip() == "image.sysdir.1"), None)
                if image == expected:
                    return name
            except (FileNotFoundError, UnicodeError):
                if name == slot and not folder.exists():
                    return name
            if name == slot:
                raise PhoneError("unavailable", "This device's saved image is incompatible or unknown. "
                                 "Its data was preserved. Ask an admin to inspect the AVD; do not wipe it.")
        return slot

    # -- life -------------------------------------------------------------------

    def running(self) -> bool:
        if self.mobile is not None:
            return self.mobile.proc is not None and self.mobile.proc.poll() is None
        return self.emulator is not None and self.emulator.poll() is None

    def touch(self) -> None:
        self.used_at = time.monotonic()

    def installed(self, device: Optional[str] = None) -> bool:
        """`B1756`. Whether a device is ready to boot here: the tools and its
        system image installed."""
        return tools_installed() and image_installed(self.package(device))

    def install(self, device: Optional[str] = None, *, accept: bool = False,
                then_start: bool = True) -> Dict:
        """`B1756`. Install what `device` needs (the person's pick), then boot
        it. `accept` is the person's acceptance of the Android SDK License,
        asked once; a device already installed just starts."""
        with self.lock:
            self._active()
            if device is not None:
                if not isinstance(device, str) or device not in P.PHONE_DEVICES:
                    raise PhoneError("bad_request",
                                     f"“device” is one of {', '.join(P.PHONE_DEVICES)}.")
                if device != self.device:
                    if self.running():
                        self._stop_locked()
                    self.device = device
                    self._save_device()
            why = self.android_why()
            if why:
                raise PhoneError("unavailable", why)
            if not (accept or (license_accepted() and self._edition_accepted())):
                raise PhoneError("license", NEEDS_LICENSE.format(url=LICENSE_URL))
            if accept:
                self._accepted_editions.add("google_play" if image_kind(self.package()) == "google_play" else "standard")
                self._save_device()
            if self.mobile is not None:
                self._stop_locked()
            if self.installed():
                return self.start() if then_start else self.info("install")
            wanted, edition = self.device, self.edition

            def then(ok: bool) -> None:
                with self.lock:
                    if self.state == "installing":
                        self.state = "off"
                        self.why = ""
                    if not ok:
                        # Off, not unavailable: the person can pick it again
                        # once whatever stopped it is fixed (`B1756`).
                        self.state = "off"
                        self.why = self.installer.info().get("why") or "The install did not finish."
                        return
                if then_start and self.device == wanted and self.edition == edition:
                    try:
                        self.start()
                    except PhoneError as e:
                        logger.info("phone for %s: after the install: %s", self.account, e.message)

            self.installer.start(self.package(wanted), accept=accept, then=then)
            self.state, self.why = "installing", ""
            logger.info("phone for %s: installing %s", self.account, wanted)
            return self.info("install")

    def start(self, device: Optional[str] = None) -> Dict:
        with self.lock:
            self._active()
            self.touch()
            if device is not None:
                if not isinstance(device, str) or device not in P.PHONE_DEVICES:
                    raise PhoneError("bad_request",
                                     f"“device” is one of {', '.join(P.PHONE_DEVICES)}.")
                if device != self.device and self.running():
                    self._stop_locked()
                if device != self.device:
                    self.device = device
                    self._save_device()
            why = self.availability()
            if why:
                self.state, self.why = "unavailable", why
                return self.info("start")
            if self.mobile is None and self.running() and self.state in ("starting", "on"):
                return self.info("start")
            if not self._edition_accepted():
                raise PhoneError("license", NEEDS_LICENSE.format(url=LICENSE_URL))
            if self.state == "installing" and self.installer.running():
                return self.info("start")
            if not self.installed():
                # `B1756`: picked, and not here yet — installed, then booted.
                return self.install(then_start=True)
            refused = self._can_start(self.account)
            if refused:
                raise PhoneError("unavailable", refused)
            if self.screen is None:
                self.state, self.why = "unavailable", NO_SCREEN
                return self.info("start")
            self._stop_locked()
            if not self._mobile_lifecycle.acquire(blocking=False):
                raise PhoneError("busy", "The previous device is stopping. Try Android again shortly.")
            self._android_lifecycle = True
            try:
                answer = self._launch_android()
                if self.emulator is None:
                    self._stop_locked()
                return answer
            except Exception:
                self._stop_locked()
                raise

    def _launch_android(self) -> Dict:
        """Launch while the caller holds both the phone lock and display lease."""
        port = self._claim_port(self.account)
        if port is None:
            raise PhoneError("unavailable", "Every phone this workstation can run is running.")
        self.port = port
        try:
            self._write_avd()
        except PhoneError:
            self._release()
            raise
        except (OSError, UnicodeError) as e:
            self._release()
            raise PhoneError("unavailable", "The device configuration could not be read or written. "
                             "Its data was preserved; ask an admin to inspect the AVD.") from e
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
                                             memory_mib=self.memory_mib, name=self.avd)],
                    env=env, cwd=str(self.home()), stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                log.close()
        except OSError as e:
            self._release()
            self.state, self.why = "unavailable", f"The emulator did not start: {e}."
            return self.info("start")
        self.state, self.why = "starting", ""
        self.boot_phase = "emulator"
        self.posture = "open" if P.PHONE_DEVICES[self.device]["kind"] == "foldable" else None
        self.rotation = 0
        self._booting = threading.Thread(target=self._boot, args=(self.emulator,), daemon=True)
        self._booting.start()
        logger.info("phone for %s: %s starting on console port %s", self.account,
                    self.device, port)
        return self.info("start")

    def preview(self, device: Optional[str] = None) -> Dict:
        """An explicitly requested Firefox preview, never an Android fallback."""
        with self.lock:
            self._active()
            if self.installer.running():
                raise PhoneError("busy", "Wait for the current Android install to finish.")
            if device is not None and (not isinstance(device, str) or device not in P.PHONE_DEVICES):
                raise PhoneError("bad_request", "Choose a device from the catalogue.")
            why = self.mobile_why()
            if why:
                raise PhoneError("unavailable", why)
            if self.mobile is not None and self.running() and (device is None or device == self.device):
                return self.info("preview")
            self._stop_locked()
            if device is not None:
                self.device = device
                self._save_device()
            self.touch()
            return self._start_mobile()

    def _boot(self, proc: subprocess.Popen) -> None:
        """Show the actual display as soon as Android's display service is
        running, including boot animation where scrcpy can attach that early.
        Early scrcpy failures are retried while Android continues booting."""
        deadline = time.monotonic() + BOOT_TIMEOUT_S
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                with self.lock:
                    if self.emulator is proc:
                        why = (f"The emulator stopped while the phone was booting (exit "
                                    f"{proc.returncode}). ~/{LOG_FILE} in the workstation says "
                                    f"why{self._last_words()}.")
                        self._stop_locked()
                        self.state, self.why = "unavailable", why
                return
            if self.emulator is not proc:
                return
            # ADB may wait for the guest. Keep that wait outside the lifecycle
            # lock so Stop can cancel a device whose guest never answers.
            display = self.adb(["shell", "getprop", "init.svc.surfaceflinger"],
                               timeout=5.0, quiet=True).strip() == "running"
            completed = self.adb(["shell", "getprop", "sys.boot_completed"],
                                 timeout=5.0, quiet=True).strip() == "1"
            with self.lock:
                if self.emulator is not proc:
                    return  # stopped or replaced while this worker was waiting
                if not self.stream_ready() and display:
                    try:
                        self._show()
                        self.boot_phase = "android"
                    except PhoneError:
                        pass  # the framework may not accept scrcpy yet
            if completed:
                break
            time.sleep(2.0)
        else:
            with self.lock:
                if self.emulator is proc:
                    self._stop_locked()
                    self.state, self.why = "unavailable", (
                        f"The phone did not finish booting in {int(BOOT_TIMEOUT_S)} s. "
                        "Start it again to retry.")
            return
        with self.lock:
            if self.emulator is not proc:
                return
            try:
                if not self.stream_ready():
                    self._show()
            except PhoneError as e:
                self._stop_locked()
                self.state, self.why = "unavailable", e.message
                return
            self.state = "on"
            self.boot_phase = "ready"
            logger.info("phone for %s: %s is on", self.account, self.device)

    # -- `B1753`: the mobile view -------------------------------------------

    def _start_mobile(self, url: Optional[str] = None, *, keep_pose: bool = False) -> Dict:
        self._active()
        self._stop_locked()
        if not keep_pose:
            self.posture = "open" if P.PHONE_DEVICES[self.device]["kind"] == "foldable" else None
            self.rotation = 0
        b = self._make_mobile()
        cancelled = threading.Event()
        self.mobile, self._mobile_cancel = b, cancelled
        self.state, self.why = "starting", ""
        self.boot_phase = "browser"
        self._booting = threading.Thread(target=self._boot_mobile, args=(b, cancelled, url),
                                        name="phone-preview", daemon=True)
        self._booting.start()
        logger.info("phone for %s: %s starting as a mobile view", self.account, self.device)
        return self.info("start")

    def _boot_mobile(self, b, cancelled, url: Optional[str] = None) -> None:
        # One owner for this display through startup, use and teardown. Requests
        # only cancel/detach it; they never wait on this resource lock or BiDi.
        with self._mobile_lifecycle:
            if cancelled.is_set() or self._retired.is_set():
                return
            try:
                self._open_mobile(url, b, cancelled)
                with self.lock:
                    if self.mobile is not b or cancelled.is_set() or self._retired.is_set():
                        return
                    self.state, self.boot_phase = "on", "ready"
                cancelled.wait()
            except Exception as e:  # noqa: BLE001 — said on the phone, never a silent "starting"
                with self.lock:
                    if self.mobile is b and not cancelled.is_set():
                        self.mobile, self._mobile_cancel = None, None
                        said = str(getattr(e, "message", None) or e)
                        self.state, self.why = "unavailable", f"The mobile view did not start: {said}"
                        self.boot_phase = "off"
                        logger.info("phone for %s: %s", self.account, self.why)
            finally:
                try:
                    b.stop()
                except Exception:
                    logger.warning("phone for %s: preview cleanup failed", self.account, exc_info=True)
                stop_screen = getattr(self.screen, "stop", None)
                if callable(stop_screen):
                    stop_screen()

    def _make_mobile(self):
        """Prepare a producer without starting the display or doing pipe/socket I/O."""
        size = mobile_view_size(self.device, self.posture, self.rotation)
        prefix, env = self._run_as()
        env.setdefault("HOME", str(self.home()))
        env["MOZ_CRASHREPORTER_DISABLE"] = "1"
        own = getattr(self.system, "own", None)
        b = MobileView(prefix, env, self.home() / MOBILE_PROFILE_DIR, False,
                       own=(lambda paths: own(self.account, paths)) if callable(own) else None,
                       screen=self.screen)
        b.window_size = size
        b.extra_prefs = mobile_view_prefs(self.device, self.posture, self.rotation)
        return b

    def _open_mobile(self, url: Optional[str], b, cancelled) -> None:
        if cancelled.is_set():
            return
        set_size = getattr(self.screen, "set_size", None)
        if callable(set_size):
            set_size(b.window_size)
        b.start(cancel=cancelled)
        if cancelled.is_set():
            return
        if url:
            b._act("open", {"url": url})
        else:
            self._go_home(b)

    def _reshape(self) -> None:
        """The mobile view again at its new shape, on the page it was on."""
        url = None
        try:
            url = self.mobile.state().get("url") if self.mobile is not None else None
        except BrowserError:
            url = None
        self._start_mobile(url if url and url.startswith(("http://", "https://")) else None, keep_pose=True)

    def _go_home(self, browser=None) -> None:
        """Firefox's own Home page — not an address `check_url` lets through,
        so opened directly; a Firefox that will not open it shows a blank page."""
        b = browser if browser is not None else self.mobile
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
        size = self.screen_size()
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
        if scrcpy == str(sdk_root() / "scrcpy" / "scrcpy"):
            env["SCRCPY_SERVER_PATH"] = str(sdk_root() / "scrcpy" / "scrcpy-server")
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
        if self._retired.is_set() or (self.mobile is None and getattr(self.system, "backend", None) != "vm"):
            return
        with self.lock:
            if self.mobile is not None:
                if self.state == "on" and not self.running():
                    self._stop_locked()
                    self.state = "off"
                    self.boot_phase = "off"
                return
            if self.state == "on" and not self.running():
                why = "The Android emulator stopped. Turn it on again to retry."
                self._stop_locked()
                self.state, self.why = "unavailable", why
                return
            if self.state == "on" and (self.scrcpy is None or self.scrcpy.poll() is not None):
                try:
                    self._show()
                except PhoneError as e:
                    logger.info("phone for %s: %s", self.account, e.message)

    def stream_ready(self) -> bool:
        """Whether there is a live display producer, including during boot.
        Readiness here is transport readiness, never a claim that Android booted."""
        if self._retired.is_set() or self.state not in ("starting", "on"):
            return False
        if self.mobile is not None:
            return self.state == "on" and self.running()
        if getattr(self.system, "backend", None) != "vm":
            return False
        return self.scrcpy is not None and self.scrcpy.poll() is None and self.running()

    def stop(self) -> Dict:
        b = self.mobile
        cancel = getattr(b, "cancel_start", None)
        if callable(cancel):
            cancel()  # may be called while another request holds the phone lock
        with self.lock:
            self._stop_locked()
            self.state, self.why = "off", ""
            return self.info("stop")

    def _stop_locked(self) -> None:
        had_producer = (self.mobile is not None or self.emulator is not None
                        or self.scrcpy is not None or self.port is not None)
        deferred = (self._mobile_cancel is not None
                    or (self._mobile_lifecycle.locked() and not self._android_lifecycle))
        if self._mobile_cancel is not None:
            self._mobile_cancel.set()
            self._mobile_cancel = None
        if self.mobile is not None:
            if deferred:
                self.mobile.cancel_start()
            else:
                self.mobile.stop()
            self.mobile = None
        if self.scrcpy is not None:
            _kill(self.scrcpy)
            self.scrcpy = None
        if self.emulator is not None:
            proc = self.emulator
            if proc.poll() is None:
                # Android's persistent disk survives; the next power-on cold boots.
                try:
                    self.adb(["emu", "kill"], timeout=10.0, quiet=True)
                except Exception:  # cleanup still owns this captured process when ADB is unavailable
                    logger.warning("phone for %s: graceful ADB stop failed; terminating the emulator",
                                   self.account, exc_info=True)
                    _kill(proc)
                try:
                    proc.wait(timeout=STOP_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    _kill(proc)
                    try:
                        proc.wait(timeout=5.0)
                    except subprocess.TimeoutExpired as e:
                        self.state, self.why = "unavailable", (
                            "The previous Android emulator could not be stopped. Its device data "
                            "was preserved and its display remains reserved. Ask an admin to inspect it.")
                        logger.error("phone for %s: %s", self.account, self.why)
                        raise PhoneError("unavailable", self.why) from e
            self.emulator = None
        self._release()
        self.boot_phase = "off"
        if self.state != "unavailable":
            self.state = "off"
        stop_screen = getattr(self.screen, "stop", None)
        owns_display = self._android_lifecycle
        if not owns_display and had_producer and not deferred:
            # Compatibility for an already attached producer: claim its free
            # display before teardown, never stop a replacement's leased screen.
            owns_display = self._mobile_lifecycle.acquire(blocking=False)
        if owns_display:
            try:
                if callable(stop_screen):
                    stop_screen()
            finally:
                self._android_lifecycle = False
                self._mobile_lifecycle.release()

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
        self._active()
        if self.mobile is None and getattr(self.system, "backend", None) != "vm":
            raise PhoneError("unavailable", ISOLATION_REQUIRED)
        if not self.running() or self.state != "on":
            raise PhoneError("unavailable", {
                "starting": "The phone is still booting; try again in a moment.",
                "unavailable": self.why or "The phone is not running.",
            }.get(self.state, "The phone is off. Start it first."))
        self.touch()

    @contextmanager
    def _transfer_slot(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self.lock.acquire(timeout=min(5.0, remaining)):
            raise PhoneError("busy", "Another operation is using your phone. Wait for it to finish before sending a file.")
        try:
            yield
        finally:
            self.lock.release()

    def transfer(self, name, data_b64) -> Dict:
        """Push only caller-supplied bytes into this user's Android Downloads.

        No host path, Android destination, owner or shell command is accepted.
        The private temporary file is created as the account, not root, and
        removed on success and failure. A digest read back from Android proves
        completion; returning from adb push alone does not. Readiness is
        checked afresh, without waiting for or retrying a data write.
        """
        import secrets
        if (not isinstance(name, str) or not name.strip() or name.strip() in (".", "..")
                or name.startswith("-") or any(c in name for c in ("/", "\\"))
                or any(unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in name)
                or len(name.encode("utf-8")) > 180):
            raise PhoneError("bad_request", "Use a filename of at most 180 UTF-8 bytes, without paths or control characters.")
        if not isinstance(data_b64, str) or len(data_b64) > (P.MAX_FILE_BYTES * 4 + 2) // 3 + 4:
            raise PhoneError("bad_request", f"Each transfer is at most {P.MAX_FILE_BYTES} bytes.")
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError):
            raise PhoneError("bad_request", "The transfer must contain valid base64 file bytes.")
        if len(data) > P.MAX_FILE_BYTES:
            raise PhoneError("bad_request", f"Each transfer is at most {P.MAX_FILE_BYTES} bytes.")
        deadline = time.monotonic() + TRANSFER_TIMEOUT_S
        with self._transfer_slot(deadline):
            self._on()
            if self.mobile is not None:
                raise PhoneError("unavailable", "File transfer needs a running Android device. Browser preview has no Android storage.")
            serial = self.serial()
            if serial is None:
                raise PhoneError("unavailable", "The Android device connection is missing. Restart your phone before sending a file.")
            self.touch()
            digest = hashlib.sha256(data).hexdigest()
            destination_dir = f"{TRANSFER_DEST}/{secrets.token_hex(8)}"
            destination = f"{destination_dir}/{name}"
            # Lock admission and ADB work share one budget. Local filesystem
            # operations are synchronous; check again before staging or sending.
            stage, phase, verified, timed_out = None, "readiness", False, False

            def budget():
                nonlocal timed_out
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    raise PhoneError("unavailable", "Android did not confirm the file before the transfer timed out.")
                return remaining

            def command(args, *, maximum=5.0, cleanup=False):
                nonlocal timed_out
                # A retired/malformed handle must never fall back to adb's
                # default device, including on the failure cleanup path.
                if self.serial() != serial:
                    raise PhoneError("unavailable", "The Android device connection changed. Start a new file transfer.")
                remaining = 5.0 if cleanup else budget()
                try:
                    return self.adb(args, timeout=min(maximum, remaining))
                except PhoneError as error:
                    if not cleanup and isinstance(error.__context__, subprocess.TimeoutExpired):
                        timed_out = True
                    if phase == "readiness":
                        raise PhoneError("unavailable", "Android's connection could not be checked. Wait for the phone to reconnect, then try again.") from error
                    raise

            try:
                if command(["get-state"]).strip() != "device":
                    raise PhoneError("unavailable", "Android's debugging connection is not ready. Wait for the phone to reconnect, then try again.")
                if command(["shell", "getprop", "sys.boot_completed"]).strip() != "1":
                    raise PhoneError("unavailable", "Android is still booting. Wait for its home screen, then send the file again.")
                # Missing on some configured images: unknown is not an unlock
                # attestation. An explicit locked system-user CE state refuses
                # the transfer; push/checksum remain the completion checks.
                ce = command(["shell", "getprop", "sys.user.0.ce_available"]).strip().lower()
                if ce in ("false", "0"):  # flag-spelling: Android CE wire values; absent is unknown, not a Pantheon flag.
                    raise PhoneError("unavailable", "Android's storage is locked. Unlock the phone before sending a file.")
                budget()
                phase = "staging"
                with self._as_account():
                    stage = tempfile.TemporaryDirectory(prefix="pantheon-phone-")
                source = Path(stage.name) / "payload"
                with self._as_account():
                    fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(data)
                phase = "prepare"
                command(["shell", "mkdir", "-p", destination_dir], maximum=20)
                phase = "send"
                command(["push", str(source), destination], maximum=120)
                phase = "verify"
                checked = command(["shell", "sha256sum", shlex.quote(destination)], maximum=60)
                record = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", checked.rstrip("\r\n"))
                if not record or record[1].lower() != digest or record[2] != destination:
                    raise PhoneError("unavailable", "Android did not confirm the transferred file's checksum. Try the transfer again.")
                verified = True
            except Exception as error:
                cleanup_failed = False
                if phase in ("prepare", "send", "verify"):
                    try:
                        command(["shell", "rm", "-f", shlex.quote(destination)], cleanup=True)
                    except Exception as cleanup_error:
                        cleanup_failed = True
                        logger.warning("Unconfirmed Android transfer cleanup (%s).", type(cleanup_error).__name__)
                if isinstance(error, (PhoneError, OSError)):
                    message = ("Android did not finish the file transfer before the timeout. Try again after the phone is ready."
                               if timed_out else error.message if phase == "readiness" and isinstance(error, PhoneError) else {
                        "readiness": "Android's connection could not be checked. Wait for the phone to reconnect, then try again.",
                        "staging": "The selected file could not be staged in your private workspace. Check free space and try again.",
                        "prepare": "Android could not prepare Downloads for this file. Unlock the phone and try again.",
                        "send": "Android's file-transfer service did not confirm the upload. Try sending the file again.",
                        "verify": "Android did not confirm the transferred file's checksum. Try sending the file again.",
                    }[phase])
                    if cleanup_failed:
                        message += " An unconfirmed file may remain in Android Downloads."
                    raise PhoneError("unavailable", message) from error
                raise
            finally:
                if stage is not None:
                    try:
                        with self._as_account():
                            stage.cleanup()
                    except Exception as cleanup_error:
                        if verified:
                            raise PhoneError("unavailable", "Android verified the file, but cleanup of its private staging copy was not confirmed. Ask an admin to check temporary storage.") from cleanup_error
                        logger.warning("Private Android transfer staging cleanup failed (%s).", type(cleanup_error).__name__)
            return {"ok": True, "name": name, "bytes": len(data), "sha256": digest,
                    "destination": destination}

    def button(self, name) -> Dict:
        if not isinstance(name, str) or name not in P.PHONE_BUTTONS:
            raise PhoneError("bad_request", f"“button” is one of {', '.join(P.PHONE_BUTTONS)}.")
        with self.lock:
            if name == "power" and not self.running():
                return self.start()
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
            self._show()
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
            self._show()
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
        return marks_from_dump(xml, self.screen_size())


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
        self._lifecycles = {}  # screen leases survive stop/get handle replacement
        self._lock = threading.Lock()
        self._reaper: Optional[threading.Thread] = None
        self.installer = Installer()   # `B1756`: one install at a time, for every account

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
                                 can_start=self._room_for, kvm=self.kvm,
                                 installer=self.installer,
                                 lifecycle=self._lifecycles.setdefault(account, threading.Lock()))
                self._by_account[account] = p
            if self._reaper is None and self.idle_s:
                self._reaper = threading.Thread(target=self._reap, daemon=True)
                self._reaper.start()
            return p

    def env_of(self, account: str) -> Dict[str, str]:
        """What the account's shell gets so its `adb` reaches its own phone;
        nothing for an account whose phone was never asked for."""
        p = self._by_account.get(account)
        return (p.env() if p is not None and p.android_why() is None and tools_installed()
                else {})

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
                p.retire()
        if p is not None:
            p.stop()

    def stop_all(self) -> None:
        with self._lock:
            items = list(self._by_account.values())
            for p in items:
                p.retire()
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
