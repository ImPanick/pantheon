# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1753` — on a host without KVM, the phone is a mobile view.

The owner chose, 2026-11-02, "Real Android, plus mobile view": where the real
Android phone cannot run (no KVM — Docker Desktop without nested
virtualization, most cloud machines), the phone window does not just refuse.
It opens the workstation's own Firefox alone on the phone's screen, in kiosk
mode, at the device's shape and CSS width, with a mobile user agent, the
page's viewport tag honoured and touch on — and says plainly that it is a
phone-shaped browser, not Android, and what Android would need.

Pinned here, without Firefox or a display (neither is on a test machine):

  * **the shape** — the device's screen, its cover when a foldable is closed,
    on its side when turned, inside the protocol's bounds;
  * **what a site sees** — Firefox for Android's user agent (Tablet for the
    tablet), the device's CSS width on this screen, meta viewport, touch;
  * **which one runs** — Android where it can, the mobile view where only it
    can, and neither without a screen; the state says which and why;
  * **the keys** — Back, Home and Power work; volume and recents say why not;
    turning and folding reopen the page at the new shape; no numbered marks;
  * **the window and the tool** — the mode reaches the window, which greys
    the keys the mobile view has not, and the agent is told what it is.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from workstation import browser as B
from workstation import phone as PH
from workstation import protocol as P

ACCOUNT = P.account_name("ann")


# ── the shape and what a site sees ────────────────────────────────────────────

@pytest.mark.parametrize("device", list(P.PHONE_DEVICES))
def test_the_mobile_view_is_the_devices_shape_inside_the_bounds(device):
    for posture in (None, "open", "closed"):
        for rotation in range(4):
            w, h = PH.mobile_view_size(device, posture, rotation)
            assert 0 < w <= P.PHONE_SCREEN_MAX[0] and 0 < h <= P.PHONE_SCREEN_MAX[1]
            assert w % 2 == 0 and h % 2 == 0
    assert PH.mobile_view_size(device) == P.phone_screen_size(device)


def test_turning_puts_it_on_its_side_and_closing_a_foldable_shows_its_cover():
    w, h = PH.mobile_view_size("pixel_9_pro")
    assert h > w
    tw, th = PH.mobile_view_size("pixel_9_pro", rotation=1)
    assert tw > th
    open_w, _ = PH.mobile_view_size("galaxy_z_fold6", "open")
    closed_w, closed_h = PH.mobile_view_size("galaxy_z_fold6", "closed")
    assert closed_w < open_w and closed_h > closed_w


def test_a_site_sees_the_devices_own_css_width_and_a_mobile_firefox():
    assert PH.mobile_css_width("pixel_9_pro") == pytest.approx(1280 / 3)
    prefs = PH.mobile_view_prefs("pixel_9_pro")
    assert '"general.useragent.override", "Mozilla/5.0 (Android 15; Mobile;' in prefs
    scale = PH.mobile_view_size("pixel_9_pro")[0] / (1280 / 3)
    assert f'"layout.css.devPixelsPerPx", "{scale:.3f}"' in prefs
    for line in ('"dom.meta-viewport.enabled", true', '"dom.w3c_touch_events.enabled", 1',
                 '"ui.primaryPointerCapabilities", 2'):
        assert line in prefs
    assert "Tablet" in PH.mobile_user_agent("pixel_tablet")
    assert "Mobile" in PH.mobile_user_agent("galaxy_s25_ultra")


def test_every_pref_line_is_one_firefox_reads():
    for line in PH.mobile_view_prefs("galaxy_z_fold6", "closed", 1).splitlines():
        if line.startswith("//"):
            continue
        assert line.startswith("user_pref(\"") and line.endswith(");")


def test_the_browser_window_takes_a_size_and_arguments_of_its_own(tmp_path):
    b = B.AccountBrowser([], {}, tmp_path / "p", False)
    store = json.loads(b._xulstore_text())
    win = next(iter(store.values()))["main-window"]
    assert (win["width"], win["height"]) == (str(P.SCREEN_WIDTH), str(P.SCREEN_HEIGHT))
    b.window_size = (492, 1100)
    win = next(iter(json.loads(b._xulstore_text()).values()))["main-window"]
    assert (win["width"], win["height"]) == ("492", "1100")
    assert PH.MobileView.extra_args == ("--kiosk",)


def test_a_mobile_view_whose_screen_will_not_start_says_so_and_never_goes_headless(tmp_path):
    class Dead:
        def start(self):
            raise RuntimeError("no KasmVNC")

    b = PH.MobileView([], {}, tmp_path / "p", False, screen=Dead())
    with pytest.raises(PH.PhoneError, match="no KasmVNC"):
        b._on_screen_env()
    with pytest.raises(PH.PhoneError):
        PH.MobileView([], {}, tmp_path / "q", False, screen=None)._on_screen_env()


# ── which one runs ────────────────────────────────────────────────────────────

class _System:
    backend = "vm"  # guest fixture with KVM explicitly unavailable
    def __init__(self, root):
        self.root = root
        self.owned = []

    def home(self, account):
        return self.root / account

    def uid(self, account):
        return 4321

    def ensure(self, account):
        self.home(account).mkdir(parents=True, exist_ok=True)

    def run_as(self, account, *, with_display=True):
        return [], {"HOME": str(self.home(account))}

    def own(self, account, paths):
        self.owned.extend(paths)

    @contextlib.contextmanager
    def files_as(self, account):
        yield


class _Screen:
    width, height = 0, 0
    desktop_kind = "kasmvnc"

    def __init__(self):
        self.sizes = []
        self.stopped = 0

    def set_size(self, size):
        self.sizes.append(tuple(size))
        self.width, self.height = size

    def start(self):
        return ":7"

    def auth_path(self):
        return Path("/nonexistent/.Xauthority-phone")

    def stop(self):
        self.stopped += 1


class _Proc:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 0


@pytest.fixture
def no_kvm(tmp_path, monkeypatch):
    """A workstation with Firefox and a screen for the phone, and no Android."""
    monkeypatch.setenv(PH.SDK_ENV, str(tmp_path / "no-sdk"))
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    monkeypatch.setattr(PH, "find_firefox", lambda: "/usr/bin/firefox")
    calls = []

    def start(self, *, cancel=None):
        calls.append(("start", self.window_size, self.extra_args, self.extra_prefs))
        self.proc = _Proc()

    def stop(self):
        if self.proc is not None:
            self.proc.alive = False
        self.proc = None
        calls.append(("stop",))

    monkeypatch.setattr(PH.MobileView, "start", start)
    monkeypatch.setattr(PH.MobileView, "stop", stop)
    monkeypatch.setattr(PH.MobileView, "cancel_start", lambda self: None)  # no OS process in this fixture
    monkeypatch.setattr(PH.MobileView, "_ctx", lambda self: "ctx-1")
    monkeypatch.setattr(PH.MobileView, "_act",
                        lambda self, action, body, at=None: calls.append(("act", action, body)) or {})
    monkeypatch.setattr(PH.MobileView, "_call",
                        lambda self, method, params, timeout=30.0: calls.append(("call", method, params)) or {})
    monkeypatch.setattr(PH.MobileView, "state",
                        lambda self, ctx=None: {"url": "https://example.org/shop", "title": "", "tabs": []})
    system = _System(tmp_path)
    system.ensure(ACCOUNT)
    screen = _Screen()
    phone = PH.AccountPhone(system, ACCOUNT, screen, kvm=lambda: (False, "the host has no KVM"))
    phone.calls = calls
    yield phone
    phone.stop()
    if phone._booting:
        phone._booting.join(5)


def _started(phone, device=None):
    phone.preview(device)
    return _ready(phone)


def _ready(phone):
    end = time.monotonic() + 5
    while phone.state == "starting" and time.monotonic() < end:
        time.sleep(0.01)
    assert phone.state == "on", phone.why
    return phone


def test_without_kvm_android_is_blocked_and_preview_requires_an_explicit_choice(no_kvm):
    info = no_kvm.info()
    assert info["available"] is False and info["state"] == "unavailable"
    assert info["mode"] is None and "KVM" in info["why"]
    assert info["preview_available"] and not info["installed"]
    assert no_kvm.start()["state"] == "unavailable"
    assert no_kvm.mobile is None and no_kvm.calls == []
    _started(no_kvm)
    info = no_kvm.info()
    assert info["mode"] == "mobile_view" and "KVM" in info["why_not_android"]
    assert "Mozilla/5.0 (Android" in info["user_agent"]
    assert info["accel"] is None


def test_without_a_screen_there_is_neither_and_the_android_reason_is_given(tmp_path, monkeypatch):
    monkeypatch.setenv(PH.SDK_ENV, str(tmp_path / "no-sdk"))
    monkeypatch.setattr(PH, "find_firefox", lambda: "/usr/bin/firefox")
    system = _System(tmp_path)
    system.ensure(ACCOUNT)
    info = PH.AccountPhone(system, ACCOUNT, None).info()
    assert info["available"] is False and info["mode"] is None
    assert "KVM" in info["why"]   # `B1756`: asked before what is installed


def test_the_mobile_view_starts_in_kiosk_at_the_devices_shape_on_its_home(no_kvm):
    _started(no_kvm, "galaxy_s25_ultra")
    start = next(c for c in no_kvm.calls if c[0] == "start")
    size = PH.mobile_view_size("galaxy_s25_ultra")
    assert start[1] == size and start[2] == ("--kiosk",)
    assert start[3] == PH.mobile_view_prefs("galaxy_s25_ultra")
    assert no_kvm.screen.sizes[-1] == size
    assert ("call", "browsingContext.navigate",
            {"context": "ctx-1", "url": PH.MOBILE_HOME, "wait": "none"}) in no_kvm.calls
    assert no_kvm.info()["screen"] == list(size)
    # A mobile view has no adb, so the account's shell is given none.
    phones = PH.Phones(no_kvm.system, kvm=lambda: (False, "no KVM"))
    phones._by_account[ACCOUNT] = no_kvm
    assert phones.env_of(ACCOUNT) == {}


def test_back_and_home_work_and_the_keys_android_has_say_why_not(no_kvm):
    _started(no_kvm)
    no_kvm.button("back")
    assert any(c[:2] == ("call", "browsingContext.traverseHistory") for c in no_kvm.calls)
    for key in ("volume_up", "volume_down", "recents"):
        with pytest.raises(PH.PhoneError) as e:
            no_kvm.button(key)
        assert e.value.code == "bad_request" and "not Android" in e.value.message
        assert "KVM" in e.value.message
    with pytest.raises(PH.PhoneError, match="no numbered marks"):
        no_kvm.marks()


def test_power_turns_the_mobile_view_off(no_kvm):
    _started(no_kvm)
    assert no_kvm.button("power")["mode"] is None
    assert no_kvm.state == "off"
    assert no_kvm.mobile is None and not no_kvm.running()


def test_turning_and_folding_reopen_the_page_at_the_new_shape(no_kvm):
    _started(no_kvm, "galaxy_z_fold6")
    assert no_kvm.posture == "open"
    no_kvm.rotate()
    _ready(no_kvm)
    assert no_kvm.state == "on" and no_kvm.rotation == 1
    assert no_kvm.screen.sizes[-1] == PH.mobile_view_size("galaxy_z_fold6", "open", 1)
    assert ("act", "open", {"url": "https://example.org/shop"}) in no_kvm.calls
    no_kvm.set_posture("closed")
    _ready(no_kvm)
    assert no_kvm.screen.sizes[-1] == PH.mobile_view_size("galaxy_z_fold6", "closed", 1)
    assert no_kvm.info()["posture"] == "closed"


def test_an_address_opens_in_the_mobile_view(no_kvm):
    _started(no_kvm)
    no_kvm.open_url("https://example.org")
    assert ("act", "open", {"url": "https://example.org"}) in no_kvm.calls


def test_a_mobile_view_that_will_not_start_says_why_and_is_not_left_starting(no_kvm, monkeypatch):
    def boom(self, **kwargs):
        raise B.BrowserError("unavailable", "Firefox crashed")

    monkeypatch.setattr(PH.MobileView, "start", boom)
    no_kvm.preview()
    end = time.monotonic() + 5
    while no_kvm.state == "starting" and time.monotonic() < end:
        time.sleep(0.01)
    assert no_kvm.state == "unavailable" and "Firefox crashed" in no_kvm.why


def test_a_mobile_view_whose_firefox_was_closed_is_off(no_kvm):
    _started(no_kvm)
    no_kvm.mobile.proc.alive = False
    no_kvm.ensure_shown()
    assert no_kvm.state == "off" and no_kvm.mobile is None


# ── the window and the tool ───────────────────────────────────────────────────

def test_the_route_passes_the_mode_and_why_to_the_window():
    from routes.workstation_routes import _phone_state
    out = _phone_state({"state": "on", "mode": "mobile_view", "why_not_android": "no KVM",
                        "user_agent": "Mozilla/5.0 (Android 15; Mobile)"})
    assert out["mode"] == "mobile_view" and out["why_not_android"] == "no KVM"
    assert _phone_state({"state": "on", "mode": "nonsense"})["mode"] is None
    assert "PHONE_MODES" in P.__all__ and PH.MOBILE_HOME


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_window_greys_the_keys_a_mobile_view_has_not(tmp_path):
    import re
    src = (Path(__file__).resolve().parents[1] / "static" / "js" / "phoneWindow.js").read_text()
    src = re.sub(r"^import \* as Modals from .*$", "const Modals = {};", src, flags=re.M)
    src = re.sub(r"^import \{ prefersReducedMotion \} from .*$",
                 "const prefersReducedMotion = () => false;", src, flags=re.M)
    src = re.sub(r"^import \{ makeWindowDraggable \} from .*$", "const makeWindowDraggable = () => {};",
                 src, flags=re.M)
    mod = tmp_path / "phoneWindow.mjs"
    mod.write_text(src)
    script = f"""
import {{ keyWorks, isMobileView, bezelShape }} from {json.dumps(mod.as_uri())};
const mv = {{ mode: 'mobile_view', device: 'galaxy_z_fold6', screen: [500, 1100], posture: 'closed',
  devices: [{{ id: 'galaxy_z_fold6', maker: 'Samsung', kind: 'foldable', foldable: true }}] }};
const ids = ['power', 'volume_up', 'volume_down', 'back', 'home', 'recents'];
console.log(JSON.stringify({{
  mobile: isMobileView(mv), android: isMobileView({{ ...mv, mode: 'android' }}),
  works: ids.filter((k) => keyWorks(mv, k)),
  all: ids.filter((k) => keyWorks({{ ...mv, mode: 'android' }}, k)),
  shape: bezelShape(mv),
}}));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["mobile"] is True and got["android"] is False
    assert got["works"] == ["power", "back", "home"] and len(got["all"]) == 6
    assert got["shape"] == {"w": 500, "h": 1100}   # already the cover's shape


class _Client:
    def __init__(self, states):
        self.states = list(states)

    async def phone(self, account, action, **fields):
        return self.states.pop(0)


def test_the_agent_is_told_the_phone_is_a_mobile_view():
    from src.agent_tools import computer_tools as CT
    got = asyncio.run(CT._phone_on(_Client([{"state": "off"}, {
        "state": "starting", "mode": "mobile_view", "device": "pixel_8",
        "devices": [{"id": "pixel_8", "name": "Google Pixel 8"}]}]), ACCOUNT))
    assert "browser preview" in got["output"] and "Google Pixel 8" in got["output"]
    assert "web pages only, not Android apps" in got["output"]
    line = CT._shot_line({"width": 450, "height": 1000, "mode": "mobile_view"}, "phone")
    assert "not Android" in line and "450×1000" in line
