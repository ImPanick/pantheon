# SPDX-License-Identifier: AGPL-3.0-or-later
"""`D-2026-11-01-01` — the agent's browser, live, on a screen of its own.

The owner, 2026-10-31: *"It's supposed to be a literal web-browser that the
agent (llm) can see the inside content inside of as well as navigate
themselves."* The window showed still frames of the workstation's Firefox under
Pantheon's own address bar and tabs. Now the browser runs alone on a second
display of the person's — KasmVNC's X server with nothing else on it
(`workstation/ubuntu.py`, role "browser") — which streams through the same
client and relays as the desktop does (`D-2026-10-31-01`), from the workstation
or from Pantheon's own image where there is no workstation
(`src/local_browser.py`). The agent still drives it through BiDi and still sees
its screenshots; the person sees Firefox itself, its tabs and address bar, and
uses it while they hold it.

A test machine has no KasmVNC and no Firefox, so `FakeKasm`
(`test_the_workstation_desktop_is_live.py`, held to what KasmVNC does) stands
where the screen streams, and a stand-in browser answers what the daemon asks
of one. Everything else is the shipped code.

What is pinned, and why each is a defect if it breaks:

  * **the screen** — the browser's display is KasmVNC alone, with no desktop
    session, its own X cookie and its own logins; without KasmVNC it does not
    start at all (`unavailable`, with why) — never an Xvfb nobody can watch;
  * **Firefox on it** — not headless, its `DISPLAY` the screen's and never the
    desktop's, its window over the whole screen, its tabs and new windows in
    one window; headless, as before, where the screen will not start;
  * **what the agent and the window measure** — a click is checked against the
    page's own size on the screen; a frame is the picture's real size and says
    where the page sits on the screen; the agent's tab is the one shown;
  * **the daemon** — `browser_screen` answers whether it streams and starts the
    browser; its stream is the screen's, with the daemon's login; one person at
    the wheel of both screens; a route is matched whole, so `/screen` is not
    `browser/screen`;
  * **the VM host and Pantheon's own** — the same answer and stream one hop
    further, and from Pantheon's own KasmVNC with the `Origin` KasmVNC wants;
  * **Pantheon's relay** — the caller's own browser only, from Pantheon's own
    pages, and `?live=1` is a frame's answer without the picture;
  * **the window** — live, it frames Pantheon's own client and nothing else,
    hides its own address bar and tabs for Firefox's, asks for no pictures,
    lays the page's stand-in over the page, and a click takes the browser
    without sending a click.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import shutil
import socket
import struct
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers.vm_fleet import HOST_TOKEN, InProcessMachine, vm_host
from tests.helpers.workstation_daemon import running_workstation
from workstation import browser as WB
from workstation import protocol as P
from workstation import ubuntu
from workstation.agentd import WorkstationError as DaemonError
from workstation.ubuntu import DesktopLogins, XDisplay

from test_the_workstation_desktop_is_live import (  # noqa: E402,F401
    ORIGIN, FakeKasm, _connect, _display, _StartableSystem, client_dir, kasm, no_chown)
from test_the_workstation_is_admin_controlled import (  # noqa: E402,F401
    ADMIN, ALLOWED, PLAIN, app, as_user, auth, datadir, switch_on)

ROOT = Path(__file__).resolve().parents[1]
ANN = account_for("ann")
STREAM = "/api/workstation/browser/websockify"


def run(coro):
    return asyncio.run(coro)


def _png(width, height):
    """The header of a PNG of that size: all `png_size` reads."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IEND", b""))


# ── stand-ins: a screen that streams on FakeKasm, a browser on it ────────────

class BrowserScreen:
    """The browser's screen, as the daemon sees one: `desktop` hands back
    FakeKasm's port and this screen's own login; `set_driver` rewrites who may
    drive, as `XDisplay` does."""

    desktop_kind = "kasmvnc"
    desktop_why = ""

    def __init__(self, kasm, root, account):
        self.kasm = kasm
        self.logins = DesktopLogins(root / account / "browser-kasmpasswd", os.getgid())
        self.logins.write(False)
        kasm.files[f"{account}:browser"] = self.logins.path
        self.drivers = []
        self.starts = 0

    def desktop(self, viewer):
        return self.kasm.port, self.logins.authorization(viewer)

    def set_driver(self, person):
        self.drivers.append(person)
        self.logins.write(person)


class FakeBrowser:
    """What the daemon asks of a browser for the screen: that it runs, and what
    it is doing."""

    def __init__(self, fail=None):
        self.ensured = 0
        self.fail = fail
        self.asked = []

    def ensure_running(self):
        self.ensured += 1
        if self.fail:
            raise WB.BrowserError("unavailable", self.fail)

    def live(self, since=0):
        self.asked.append(since)
        return {"ok": True, "action": "activity", "url": "https://shop.example/", "title": "Shop",
                "tabs": [{"tab": "ctx-1", "url": "https://shop.example/", "current": True}],
                "activity": [{"id": 1, "seq": 3, "at": 1.0, "who": "agent", "action": "click",
                              "label": "Clicking “Buy”", "x": 40, "y": 50, "phase": "doing"}],
                "seq": 3, "view": {"x": 0, "y": 85, "w": 1280, "h": 715}}


@pytest.fixture
def screens(tmp_path, kasm, no_chown):
    made = {}

    def screen_for(account):
        if account not in made:
            made[account] = BrowserScreen(kasm, tmp_path / "browser-logins", account)
        return made[account]

    screen_for.made = made
    return screen_for


@pytest.fixture
def station(tmp_path, screens, monkeypatch):
    """The real daemon, whose desktop is pictures (so the only display that
    streams is the browser's) and whose browser stands in for Firefox."""
    browser = FakeBrowser()
    with running_workstation(tmp_path) as ws:
        monkeypatch.setattr(ws.system, "browser_display", screens)
        monkeypatch.setattr(ws.station.browsers, "get", lambda account: browser)
        ws.browser = browser
        yield ws


# ── the screen ───────────────────────────────────────────────────────────────

def test_the_browsers_screen_is_kasmvnc_alone_with_its_own_cookie_and_logins(
        tmp_path, monkeypatch, no_chown):
    display, spawned, _ = _display(tmp_path, monkeypatch)
    display = XDisplay(_StartableSystem(tmp_path), ANN, role="browser")
    display._spawn = lambda prefix, env, label, argv: (
        spawned.append((label, argv(9))) or ((_Proc(), 11), ""))
    sessions = []
    monkeypatch.setattr(ubuntu, "fs_identity", lambda uid, gid: contextlib.nullcontext())
    monkeypatch.setattr(ubuntu, "desktop_session", lambda: sessions.append(1) or (["true"], {}))
    monkeypatch.setattr(ubuntu.subprocess, "Popen", lambda *a, **k: sessions.append(a) or _Proc())
    monkeypatch.setattr(display, "_open_watch", lambda: sessions.append("watch"))
    assert display.start() == ":11"
    assert [label for label, _ in spawned] == ["Xkasmvnc"]
    assert sessions == [], "a desktop session, a program or a damage watch was started on it"
    assert display.auth_path() == tmp_path / ".Xauthority-browser"
    argv = spawned[0][1]
    assert argv[argv.index("-auth") + 1] == str(tmp_path / ".Xauthority-browser")
    logins = argv[argv.index("-KasmPasswordFile") + 1]
    assert logins == str(tmp_path / "2001" / "browser-kasmpasswd")
    assert display.desktop_kind == "kasmvnc"


def test_without_kasmvnc_the_browsers_screen_does_not_start_and_says_why(tmp_path, monkeypatch):
    display, spawned, _ = _display(tmp_path, monkeypatch, kasm_here=False)
    display.role = "browser"
    with pytest.raises(DaemonError) as e:
        display._start_server([], {}, tmp_path / ".Xauthority-browser", 2001)
    assert e.value.code == "unavailable"
    assert spawned == [], "an Xvfb nobody can watch was started for the browser"
    assert "no KasmVNC, so its browser is shown as pictures" in e.value.message
    assert "docker compose up -d --build" in e.value.message


def test_a_system_may_say_why_in_its_own_words_and_keep_its_own_logins(tmp_path, monkeypatch, no_chown):
    display, spawned, _ = _display(tmp_path, monkeypatch, kasm_here=False)

    class Pantheons(_StartableSystem):
        no_kasmvnc_why = "Pantheon has no KasmVNC."

    display.system = Pantheons(tmp_path)
    display.role = "browser"
    with pytest.raises(DaemonError) as e:
        display._start_server([], {}, tmp_path / ".Xauthority-browser", 2001)
    assert e.value.message == "Pantheon has no KasmVNC."

    display, spawned, _ = _display(tmp_path, monkeypatch)

    class Own(_StartableSystem):
        logins_owner, logins_gid = 4242, 4343

        def logins_path(self, account, role):
            return tmp_path / "own" / account / role

    owners = []
    monkeypatch.setattr(os, "fchown", lambda fd, u, g: owners.append((u, g)))
    display.system = Own(tmp_path)
    display.role = "browser"
    _, _, (port, logins) = display._start_server([], {}, tmp_path / ".Xauthority-browser", 2001)
    assert logins.path == tmp_path / "own" / ANN / "browser" and logins.path.is_file()
    assert owners == [(4242, 4343)]


def test_the_workstation_makes_one_browser_screen_per_account_and_a_reset_stops_it():
    source = (ROOT / "workstation" / "ubuntu.py").read_text(encoding="utf-8")
    body = source[source.index("    def browser_display(self, account: str) -> XDisplay:"):]
    body = body[:body.index("\n    # --")]
    assert 'XDisplay(self, account, role="browser")' in body and "setdefault" in body
    reset = source[source.index("    def reset(self, account: str) -> None:"):]
    reset = reset[:reset.index("kill_processes")]
    assert "self._browser_displays.get(account)" in reset and "screen.stop()" in reset
    assert ubuntu.DISPLAY_ROLES == ("desktop", "browser")


class _Proc:
    def poll(self):
        return None


# ── Firefox on it ────────────────────────────────────────────────────────────

class _Screen:
    def __init__(self, tmp_path, fails=False):
        self.tmp_path = tmp_path
        self.fails = fails
        self.started = 0

    def start(self):
        self.started += 1
        if self.fails:
            raise DaemonError("unavailable", "no KasmVNC here")
        return ":11"

    def auth_path(self):
        return self.tmp_path / ".Xauthority-browser"


class _Launched(Exception):
    pass


def _launch(monkeypatch, browser):
    """Start `browser` up to the moment Firefox would run: `(argv, env)`."""
    seen = {}

    def popen(argv, env=None, **kw):
        seen["argv"], seen["env"] = list(argv), dict(env or {})
        raise _Launched()

    monkeypatch.setattr(WB, "find_firefox", lambda: "/usr/bin/firefox")
    monkeypatch.setattr(WB.subprocess, "Popen", popen)
    with pytest.raises(_Launched):
        browser.start()
    return seen["argv"], seen["env"]


def test_on_its_screen_firefox_is_seen_its_window_covers_the_screen_and_its_tabs_stay_in_it(
        tmp_path, monkeypatch):
    profile = tmp_path / "home" / WB.PROFILE_DIR
    profile.mkdir(parents=True)
    (profile / WB.XULSTORE).write_text(json.dumps({
        "chrome://browser/content/browser.xhtml": {"main-window": {"width": "640"},
                                                   "sidebar-box": {"width": "200"}},
        "chrome://other/": {"x": {"y": "1"}}}))
    screen = _Screen(tmp_path)
    b = WB.AccountBrowser([], {"PATH": "/usr/bin", "DISPLAY": ":0"}, profile, True, screen=screen)
    argv, env = _launch(monkeypatch, b)
    assert "--headless" not in argv and b.on_screen is True and screen.started == 1
    assert env["DISPLAY"] == ":11" and env["XAUTHORITY"] == str(tmp_path / ".Xauthority-browser")
    prefs = (profile / "user.js").read_text()
    assert prefs.startswith(WB.USER_JS) and WB.SCREEN_JS in prefs
    for pref in ('"browser.link.open_newwindow", 3', '"browser.tabs.inTitlebar", 0',
                 '"browser.tabs.closeWindowWithLastTab", false'):
        assert pref in prefs, pref
    store = json.loads((profile / WB.XULSTORE).read_text())
    main = store["chrome://browser/content/browser.xhtml"]
    assert main["main-window"] == {"screenX": "0", "screenY": "0", "width": str(P.SCREEN_WIDTH),
                                   "height": str(P.SCREEN_HEIGHT), "sizemode": "normal"}
    assert main["sidebar-box"] == {"width": "200"} and store["chrome://other/"] == {"x": {"y": "1"}}


def test_a_screen_that_will_not_start_leaves_firefox_headless_as_before(tmp_path, monkeypatch):
    profile = tmp_path / "home" / WB.PROFILE_DIR
    b = WB.AccountBrowser([], {"PATH": "/usr/bin"}, profile, False, screen=_Screen(tmp_path, fails=True))
    argv, env = _launch(monkeypatch, b)
    assert "--headless" in argv and b.on_screen is False
    assert "DISPLAY" not in env and WB.SCREEN_JS not in (profile / "user.js").read_text()
    assert not (profile / WB.XULSTORE).exists()


def test_the_profile_files_are_never_written_through_a_link(tmp_path, monkeypatch):
    profile = tmp_path / "home" / WB.PROFILE_DIR
    profile.mkdir(parents=True)
    os.symlink(tmp_path / "elsewhere", profile / WB.XULSTORE)
    b = WB.AccountBrowser([], {}, profile, True, screen=_Screen(tmp_path))
    monkeypatch.setattr(WB, "find_firefox", lambda: "/usr/bin/firefox")
    with pytest.raises(OSError):
        b.start()
    assert not (tmp_path / "elsewhere").exists()


def test_a_browser_with_a_screen_of_its_own_never_takes_the_desktops(tmp_path):
    woken = []

    class System:
        def ensure(self, account):
            return {}

        def browser_display(self, account):
            return _Screen(tmp_path)

        def wake(self, account):
            woken.append(account)
            return ":5"

        def run_as(self, account):
            return [], {"DISPLAY": ":5", "XAUTHORITY": "/home/a/.Xauthority", "PATH": "/usr/bin"}

        def home(self, account):
            return tmp_path

        def own(self, account, paths):
            pass

    b = WB.Browsers(System()).get(ANN)
    assert woken == [], "the desktop was started for a browser that has its own screen"
    assert "DISPLAY" not in b.env and "XAUTHORITY" not in b.env
    assert isinstance(b.screen, _Screen)


# ── what the agent and the window measure ────────────────────────────────────

def _on_screen(tmp_path, answers):
    """A browser on its screen whose page answers `answers[fn]`."""
    b = WB.AccountBrowser([], {}, tmp_path, True, screen=_Screen(tmp_path))
    b.on_screen = True
    asked = []

    def ev(ctx, fn, *args, timeout=30.0):
        asked.append((ctx, fn, timeout))
        got = answers.get(fn)
        if isinstance(got, Exception):
            raise got
        return got(ctx) if callable(got) else got

    b._eval = ev
    b.asked = asked
    return b


def test_a_point_is_checked_against_the_page_on_the_screen(tmp_path):
    b = _on_screen(tmp_path, {"() => JSON.stringify([innerWidth, innerHeight])": "[1280, 715]"})
    assert b._page_size("c") == (1280, 715)
    assert WB._xy({"x": 1279, "y": 714}, b._page_size("c")) == (1279, 714)
    with pytest.raises(WB.BrowserError) as e:
        WB._xy({"x": 10, "y": 715}, b._page_size("c"))
    assert "The page is 1280×715" in e.value.message
    # Headless, the page is the protocol's size, whatever it says.
    b.on_screen = False
    assert b._page_size("c") == (P.BROWSER_WIDTH, P.BROWSER_HEIGHT)


@pytest.mark.parametrize("said", ["[0, 715]", "[true, 5]", "not json", "[99999, 5]",
                                  WB.BrowserError("refused", "x")])
def test_a_page_that_will_not_say_its_size_is_the_protocols(tmp_path, said):
    b = _on_screen(tmp_path, {"() => JSON.stringify([innerWidth, innerHeight])": said})
    assert b._page_size("c") == (P.BROWSER_WIDTH, P.BROWSER_HEIGHT)


@pytest.mark.parametrize("said,view", [
    ('{"x": 0, "y": 85, "w": 1280, "h": 715}', {"x": 0, "y": 85, "w": 1280, "h": 715}),
    ('{"x": -40, "y": 900, "w": 5000, "h": 9}', {"x": 0, "y": 799, "w": 1280, "h": 1}),
    ('{"x": 100, "y": 100, "w": 2000, "h": 2000}', {"x": 100, "y": 100, "w": 1180, "h": 700}),
    ('{"x": "a"}', None), ("[]", None), ("", None),
])
def test_where_the_page_sits_is_kept_on_the_screen(tmp_path, said, view):
    b = _on_screen(tmp_path, {WB.VIEW_FN: said})
    assert b._view("c") == view
    b.on_screen = False
    assert b._view("c") is None, "a headless browser's picture is the page"


def test_the_agents_tab_is_the_one_on_the_screen(tmp_path):
    shown = {"c1": "hidden", "c2": "visible", "c3": "hidden"}
    b = _on_screen(tmp_path, {"() => document.visibilityState": lambda ctx: shown[ctx]})
    b._contexts = lambda: [{"context": c} for c in ("c1", "c2", "c3")]
    b.current = "c1"
    assert b._ctx() == "c2"
    assert all(timeout == WB._VISIBLE_ASK_S for _, _, timeout in b.asked)
    shown.update(c2="hidden", c3="visible")
    assert b._ctx() == "c3"
    # A tab that will not say keeps the agent where it was.
    b._eval = lambda *a, **k: (_ for _ in ()).throw(WB.BrowserError("refused", "x"))
    assert b._ctx() == "c3"


def test_a_frame_is_the_pictures_own_size_and_says_where_the_page_sits(tmp_path, monkeypatch):
    b = _on_screen(tmp_path, {WB.VIEW_FN: '{"x": 0, "y": 85, "w": 1280, "h": 715}',
                              "() => document.title": "Shop"})
    data = _png(1280, 715)
    b.running = lambda: True
    b._contexts = lambda: [{"context": "c1", "url": "https://shop.example/"}]
    b._call = lambda method, params=None, timeout=30.0: (
        {"data": base64.b64encode(data).decode()} if method == "browsingContext.captureScreenshot" else {})
    f = b.frame()
    assert (f["width"], f["height"]) == (1280, 715)
    assert f["view"] == {"x": 0, "y": 85, "w": 1280, "h": 715}
    assert f["url"] == "https://shop.example/" and f["title"] == "Shop"
    assert WB.png_size(data) == (1280, 715) and WB.png_size(b"GIF89a" + b"\0" * 30) is None


def test_activity_is_a_frame_without_the_picture_and_asking_is_watching(tmp_path):
    b = _on_screen(tmp_path, {WB.VIEW_FN: '{"x": 0, "y": 85, "w": 1280, "h": 715}',
                              "() => document.title": "Shop"})
    b.running = lambda: True
    b._contexts = lambda: [{"context": "c1", "url": "https://shop.example/"}]
    b._call = lambda *a, **k: pytest.fail("a picture was taken for the live window")
    b._log("agent", "click", "Clicking “Buy”", 40, 50)
    b.watched_at = 0.0
    out = b.live(0)
    assert out["ok"] is True and out["action"] == "activity" and "data_b64" not in out
    assert out["view"] == {"x": 0, "y": 85, "w": 1280, "h": 715} and out["seq"] == 1
    assert [a["label"] for a in out["activity"]] == ["Clicking “Buy”"]
    assert out["tabs"] == [{"tab": "c1", "url": "https://shop.example/", "current": True}]
    assert b.watched(), "the agent's hand is not paced while a person watches it live"
    assert b.live(1)["activity"] == []


def test_watching_live_is_never_busy_and_never_the_agents_to_ask():
    from src.agent_tools import browser_tools
    assert P.WATCH_ACTIONS == ("frame", "activity")
    assert "activity" in P.BROWSER_ACTIONS and "activity" in browser_tools.PERSON_ONLY
    assert "activity" not in browser_tools.ACTIONS


# ── the daemon ───────────────────────────────────────────────────────────────

def test_the_daemon_says_the_browser_streams_and_starts_it(station):
    client = WorkstationClient(station.url, station.token)
    assert run(client.browser_screen(ANN)) == {"kind": "kasmvnc", "holder": "agent"}
    assert station.browser.ensured == 1, "a person opening the window would see an empty screen"


def test_the_stream_is_the_browsers_screen_and_one_person_holds_both_screens(station, screens):
    client = WorkstationClient(station.url, station.token)

    async def go():
        async with client.browser_screen_stream(ANN, "person") as ws:
            await ws.send(b"who")
            watching = await ws.recv()
            await client.control(ANN, "person")
            await ws.send(b"who")
            holding = await ws.recv()
            await client.control(ANN, "agent")
            await ws.send(b"who")
            return watching, holding, await ws.recv()

    assert run(go()) == (b"person:r", b"person:rw", b"person:r")
    assert screens.made[ANN].drivers == [True, False]
    assert station.browser.ensured >= 1


def test_the_browsers_screen_hears_the_daemons_login_and_nothing_of_the_callers(station, kasm):
    client = WorkstationClient(station.url, station.token)

    async def go():
        async with client.browser_screen_stream(ANN, "person") as ws:
            await ws.send(b"who")
            return await ws.recv()

    assert run(go()) == b"person:r"
    seen = kasm.seen[-1]
    assert seen["Origin"] == f"http://127.0.0.1:{kasm.port}" and seen["Sec-WebSocket-Protocol"] == "binary"
    assert all(station.token not in v for v in seen.values()), "Pantheon's token reached the screen"


def test_a_browser_without_a_screen_of_its_own_says_why(tmp_path, monkeypatch):
    with running_workstation(tmp_path) as ws:
        monkeypatch.setattr(ws.station.browsers, "get", lambda account: FakeBrowser())
        client = WorkstationClient(ws.url, ws.token)
        answer = run(client.browser_screen(ANN))
        assert answer == {"kind": None, "holder": "agent",
                          "why": "This workstation's browser has no screen of its own; it is "
                                 "shown as pictures."}

        async def go():
            async with client.browser_screen_stream(ANN, "person"):
                pass

        with pytest.raises(WorkstationError) as e:
            run(go())
    assert e.value.code == "unavailable"


def test_a_browser_that_will_not_start_says_why_and_is_not_offered_live(station, monkeypatch):
    monkeypatch.setattr(station.station.browsers, "get",
                        lambda account: FakeBrowser(fail="This workstation has no Firefox."))
    answer = run(WorkstationClient(station.url, station.token).browser_screen(ANN))
    assert answer["kind"] is None and answer["why"] == "This workstation has no Firefox."


def test_a_workstation_older_than_the_live_browser_is_frames_not_a_failure(monkeypatch):
    client = WorkstationClient("http://127.0.0.1:9", "pws_x")

    async def older(*a, **k):
        raise WorkstationError("not_found", "No such workstation route.", status=404)

    monkeypatch.setattr(client, "_call", older)
    answer = run(client.browser_screen(ANN))
    assert answer["kind"] is None and "older than the live browser" in answer["why"]


def test_a_route_is_matched_whole(station):
    """`/screen` is the screenshot route's name, not a route: before this, the
    tail match took `GET /v1/users/{account}/screen` for whichever route's
    template ended in it — and `browser/screen` does."""
    status, body = _get(station, f"/v1/users/{ANN}/screen")
    assert status == 404 and body["error"] == "not_found"
    status, body = _get(station, f"/v1/users/{ANN}/browser/screen")
    assert status == 200 and body["kind"] == "kasmvnc"


def _get(station, path):
    parts = urlsplit(station.url)
    with socket.create_connection((parts.hostname, parts.port), timeout=10) as s:
        s.sendall((f"GET {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {station.token}\r\n"
                   "Connection: close\r\n\r\n").encode())
        raw = b""
        while chunk := s.recv(65536):
            raw += chunk
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split()[1]), json.loads(body)


def test_the_protocol_states_the_route_and_the_watching_actions():
    assert P.ROUTES["browser_screen"] == ("GET", "/v1/users/{account}/browser/screen")
    assert P.route_path("browser_screen", ANN) == ("GET", f"/v1/users/{ANN}/browser/screen")


# ── the VM host ──────────────────────────────────────────────────────────────

def test_the_vm_host_carries_the_browsers_screen_from_the_persons_machine(tmp_path, screens):
    browser = FakeBrowser()

    class Machine(InProcessMachine):
        def start(self):
            super().start()
            self.system.browser_display = screens
            self.server.station.browsers.get = lambda account: browser

    with vm_host(tmp_path / "vm", factory=Machine) as (fleet, url):
        client = WorkstationClient(url, HOST_TOKEN)
        assert run(client.browser_screen(ANN)) == {"kind": "kasmvnc", "holder": "agent"}

        async def go():
            async with client.browser_screen_stream(ANN, "person") as ws:
                await ws.send(b"who")
                first = await ws.recv()
                busy = fleet._use[ANN][0]
                await client.control(ANN, "person")
                await ws.send(b"who")
                return first, busy, await ws.recv()

        first, busy, holding = run(go())
    assert (first, holding) == (b"person:r", b"person:rw")
    assert busy >= 1, "a machine someone is watching could be powered off as idle"


# ── Pantheon's own ───────────────────────────────────────────────────────────

def test_pantheons_own_browser_has_a_screen_where_kasmvnc_is_here(tmp_path, monkeypatch):
    from src import local_browser as LB
    system = LB._LocalSystem(tmp_path)
    monkeypatch.setattr(LB, "live_screens_here", lambda: False)
    assert system.browser_display("pw-a") is None
    monkeypatch.setattr(LB, "live_screens_here", lambda: True)
    screen = system.browser_display("pw-a")
    assert isinstance(screen, XDisplay) and screen.role == "browser"
    assert system.browser_display("pw-a") is screen and system.screen_of("pw-b") is None
    assert system.logins_path("pw-a", "browser") == system.home("pw-a") / LB.SCREEN_DIR / "kasmpasswd"
    assert system.logins_path("pw-a", "browser") != system.logins_path("pw-b", "browser")
    assert system.no_kasmvnc_why == LB.NO_LIVE_SCREEN_SENTENCE
    assert system.uid("pw-a") == system.logins_owner


def test_live_screens_need_linux_and_kasmvnc(monkeypatch):
    import sys
    from src import local_browser as LB
    here = {ubuntu.KASMVNC_SERVER: "/usr/bin/Xkasmvnc"}
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: here.get(name))
    monkeypatch.setattr(sys, "platform", "linux")
    assert LB.live_screens_here() is True
    here.clear()
    assert LB.live_screens_here() is False
    here[ubuntu.KASMVNC_SERVER] = "/usr/bin/Xkasmvnc"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert LB.live_screens_here() is False


def _local(tmp_path, monkeypatch, screen):
    from src import local_browser as LB
    browsers = LB.LocalBrowsers(tmp_path)
    monkeypatch.setattr(browsers.browsers.system, "browser_display", lambda account: screen)
    fake = FakeBrowser()
    monkeypatch.setattr(browsers, "_browser", lambda account: fake)
    return browsers, fake


def test_pantheons_own_screen_answers_and_its_holder_drives_it(tmp_path, monkeypatch, kasm, no_chown):
    screen = BrowserScreen(kasm, tmp_path / "logins", "pw-a")
    browsers, fake = _local(tmp_path, monkeypatch, screen)
    assert browsers.screen("pw-a", "cy") == {"kind": "kasmvnc", "holder": "agent"}
    assert fake.ensured == 1
    browsers.control("pw-a", "person")
    browsers.control("pw-a", "agent")
    assert screen.drivers == [True, False]
    port, authorization = browsers.screen_login("pw-a", "person")
    assert port == kasm.port and authorization.startswith("Basic ")
    with pytest.raises(WorkstationError):
        browsers.screen_login("pw-a", "root")


def test_pantheon_without_kasmvnc_says_how_to_get_the_live_browser(tmp_path, monkeypatch):
    from src import local_browser as LB
    browsers, _ = _local(tmp_path, monkeypatch, None)
    answer = browsers.screen("pw-a", "cy")
    assert answer == {"kind": None, "holder": "agent", "why": LB.NO_LIVE_SCREEN_SENTENCE}
    with pytest.raises(WorkstationError) as e:
        browsers.screen_login("pw-a", "person")
    assert e.value.code == "unavailable" and e.value.message == LB.NO_LIVE_SCREEN_SENTENCE


def test_pantheons_own_stream_reaches_its_kasmvnc_with_the_origin_it_wants(
        tmp_path, monkeypatch, kasm, no_chown):
    from src import local_browser as LB
    screen = BrowserScreen(kasm, tmp_path / "logins", "pw-a")
    browsers, _ = _local(tmp_path, monkeypatch, screen)
    client = LB.LocalBrowserClient(browsers, owner="cy")

    async def go():
        async with client.browser_screen_stream("pw-a", "person") as ws:
            await ws.send(b"who")
            first = await ws.recv()
            await client.control("pw-a", "person")
            await ws.send(b"who")
            return first, await ws.recv()

    assert run(go()) == (b"person:r", b"person:rw")
    seen = kasm.seen[-1]
    assert seen["Origin"] == f"http://127.0.0.1:{kasm.port}"
    assert seen["Authorization"].startswith("Basic ") and seen["Sec-WebSocket-Protocol"] == "binary"


def test_the_workstations_screen_falls_back_to_pantheons_own_before_the_stream_starts():
    from src import local_browser as LB

    class Primary:
        @contextlib.asynccontextmanager
        async def browser_screen_stream(self, account, viewer):
            raise WorkstationError("unavailable", "The workstation is starting.")
            yield  # pragma: no cover

    class Refusing:
        @contextlib.asynccontextmanager
        async def browser_screen_stream(self, account, viewer):
            raise WorkstationError("not_permitted", "No.")
            yield  # pragma: no cover

    class Local:
        @contextlib.asynccontextmanager
        async def browser_screen_stream(self, account, viewer):
            yield "pantheon's own"

    async def through(primary):
        both = LB.FallbackBrowser(primary, Local())
        async with both.browser_screen_stream("pw-a", "person") as upstream:
            return upstream, both.last_runs_in

    assert run(through(Primary())) == ("pantheon's own", None)
    with pytest.raises(WorkstationError) as e:
        run(through(Refusing()))
    assert e.value.code == "not_permitted", "a refusal is not a reason to use another browser"


# ── Pantheon's relay ─────────────────────────────────────────────────────────

@pytest.fixture
def live(app, station, client_dir):
    switch_on(app, station)
    return app


def test_pantheon_offers_its_own_client_pointed_at_the_browsers_stream(live):
    r = as_user(live, ALLOWED).get("/api/workstation/browser/screen")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "kasmvnc" and body["holder"] == "agent"
    assert body["client"].startswith("/api/workstation/desktop/client/vnc.html?")
    q = parse_qs(urlsplit(body["client"]).query)
    assert q["path"] == ["api/workstation/browser/websockify"]
    assert q["view_only"] == ["false"] and q["resize"] == ["scale"]
    assert "why" not in body and r.headers["cache-control"].startswith("no-store")


def test_without_the_client_the_browser_is_frames_and_says_so(app, station, monkeypatch, tmp_path):
    from src import desktop_client
    monkeypatch.setenv(desktop_client.DIR_ENV, str(tmp_path / "nothing-here"))
    switch_on(app, station)
    body = as_user(app, ALLOWED).get("/api/workstation/browser/screen").json()
    assert body["kind"] is None and "client" not in body
    assert body["why"] == desktop_client.UNAVAILABLE_SENTENCE


def test_live_the_window_is_told_what_the_agent_did_and_where_the_page_sits(live, station):
    r = as_user(live, ALLOWED).get("/api/workstation/browser?live=1&since=2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["live"] is True and "data_b64" not in body and body["runs_in"] == "workstation"
    assert body["view"] == {"x": 0, "y": 85, "w": 1280, "h": 715}
    assert body["url"] == "https://shop.example/" and body["seq"] == 3
    assert [a["label"] for a in body["activity"]] == ["Clicking “Buy”"]
    assert body["tabs"] == [{"tab": 1, "url": "https://shop.example/", "current": True}]
    assert station.browser.asked == [2]


@pytest.mark.parametrize("v,kept", [
    ({"x": 0, "y": 85, "w": 1280, "h": 715}, True), ({"x": -1, "y": 0, "w": 5, "h": 5}, False),
    ({"x": 0, "y": 0, "w": 0, "h": 5}, False), ({"x": 0, "y": 0, "w": 1281, "h": 5}, False),
    ({"x": True, "y": 0, "w": 5, "h": 5}, False), ("0,0,5,5", False), (None, False),
])
def test_where_the_page_sits_reaches_the_window_only_as_four_numbers_on_the_screen(v, kept):
    from routes.workstation_routes import _view
    assert (_view(v) is not None) is kept


def test_the_stream_relays_the_callers_own_browser_and_take_over_changes_it(live):
    c = as_user(live, ALLOWED)
    with _connect(c, STREAM, subprotocols=["binary"]) as ws:
        assert ws.accepted_subprotocol == "binary"
        ws.send_bytes(b"who")
        assert ws.receive_bytes() == b"person:r"
        assert c.post("/api/workstation/control", json={"holder": "person"}).status_code == 200
        ws.send_bytes(b"who")
        assert ws.receive_bytes() == b"person:rw"
        assert c.post("/api/workstation/control", json={"holder": "agent"}).status_code == 200
        ws.send_bytes(b"who")
        assert ws.receive_bytes() == b"person:r"


@pytest.mark.parametrize("who,path,headers,code", [
    (None, STREAM, ORIGIN, 4401),                                      # nobody signed in
    (ALLOWED, STREAM, {"origin": "https://elsewhere.example"}, 4401),  # another site's page
    (ALLOWED, STREAM, {}, 4401),                                        # no page at all
    (PLAIN, STREAM, ORIGIN, 4403),                                      # no browser of their own
])
def test_the_stream_is_refused_to_anyone_but_the_person_from_pantheons_pages(
        live, who, path, headers, code, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    # "No browser of their own" holds only where Pantheon carries no Firefox:
    # with one (its image, a CI runner), PLAIN has Pantheon's own browser —
    # the case below. Pinned so this reads the same on every machine.
    monkeypatch.setattr("src.local_browser.firefox_here", lambda: False)
    with pytest.raises(WebSocketDisconnect) as e:
        with _connect(as_user(live, who), path, headers, subprotocols=["binary"]):
            pass
    assert e.value.code == code


def test_pantheons_own_browser_without_a_screen_closes_the_stream_saying_why(live, monkeypatch):
    """A person with no workstation whose browser is Pantheon's own, where
    Pantheon has no KasmVNC: `/browser/screen` sends the window to frames, so
    the stream is never asked for; asked anyway, it closes with the reason
    rather than a refusal of who they are."""
    from starlette.websockets import WebSocketDisconnect
    from routes.workstation_routes import _close_reason
    from src import local_browser

    def no_screen(self, account, viewer):   # what a Pantheon with no KasmVNC answers
        raise WorkstationError("unavailable", local_browser.NO_LIVE_SCREEN_SENTENCE)

    monkeypatch.setattr(local_browser, "firefox_here", lambda: True)
    monkeypatch.setattr(local_browser.LocalBrowsers, "screen_login", no_screen)
    with pytest.raises(WebSocketDisconnect) as e:
        with _connect(as_user(live, PLAIN), STREAM, ORIGIN, subprotocols=["binary"]):
            pass
    assert e.value.code == 1011
    assert e.value.reason == _close_reason(local_browser.NO_LIVE_SCREEN_SENTENCE)


def test_a_stream_that_does_not_speak_the_clients_subprotocol_is_refused(live):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with _connect(as_user(live, ALLOWED), STREAM):
            pass
    assert e.value.code == 1002


def test_only_the_two_streams_pantheon_relays_are_ever_offered():
    from src import desktop_client
    assert "path=api%2Fworkstation%2Fbrowser%2Fwebsockify" in desktop_client.page_url(
        stream=desktop_client.BROWSER_STREAM_PATH)
    with pytest.raises(ValueError):
        desktop_client.page_url(stream="api/elsewhere")


# ── where it comes from ──────────────────────────────────────────────────────

def test_pantheons_image_carries_kasmvncs_server_pinned_for_its_own_debian():
    script = (ROOT / "workstation" / "provision.sh").read_text(encoding="utf-8")
    for arch in ("AMD64", "ARM64"):
        assert re.search(rf"^KASMVNC_SHA256_TRIXIE_{arch}=[0-9a-f]{{64}}$", script, re.M), arch
    server = script[script.index("server() {"):]
    server = server[:server.index("\n}\n")]
    assert "debian_trixie" in server and "dpkg --print-architecture" in server
    assert "dpkg -i" not in server, "the server is installed by the image's apt, not here"
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    stage = dockerfile[dockerfile.index("AS desktop-client"):]
    stage = stage[:stage.index("\nFROM ")]
    assert "provision.sh server /server" in stage
    final = dockerfile[dockerfile.rindex("\nFROM "):]
    assert "COPY --from=desktop-client /server/kasmvncserver.deb /tmp/kasmvncserver.deb" in final
    assert "/tmp/kasmvncserver.deb" in final[final.index("apt-get install"):]
    assert "xdotool" in final[final.index("apt-get install"):]


def test_the_stream_route_is_a_known_unreachable_from_the_page():
    checker = (ROOT / ".pantheon" / "check-unreachable.py").read_text(encoding="utf-8")
    assert '"/api/workstation/browser/websockify"' in checker


def test_the_decision_is_on_the_record():
    decisions = (ROOT / ".pantheon" / "DECISIONS.md").read_text(encoding="utf-8")
    entry = decisions[decisions.index("## D-2026-11-01-01"):]
    entry = entry[:entry.index("\n## ", 5)] if "\n## " in entry[5:] else entry
    assert "D-2026-10-31-01" in entry, "it does not say what it amends"
    old = decisions[decisions.index("## D-2026-10-31-01"):]
    old = old[:old.index("\n## ", 5)]
    assert "Amended 2026-11-01 by `D-2026-11-01-01`" in old, \
        "the decision that kept KasmVNC's server out of Pantheon's image does not say it changed"


# ── the window ───────────────────────────────────────────────────────────────

_CLIENT = ("/api/workstation/desktop/client/vnc.html?autoconnect=true"
           "&path=api%2Fworkstation%2Fbrowser%2Fwebsockify&resize=scale")

_LIVE_SHIM_TAIL = r"""
// ── `D-2026-11-01-01`: the browser's own screen ───────────────────────────
export const screen = { answer: null, view: { x: 0, y: 85, w: 1280, h: 715 }, activity: [] };
const _framesFetch = globalThis.fetch;
globalThis.fetch = async (url, opts = {}) => {
  const path = String(url).split('?')[0];
  const reply = (status, payload) => ({ ok: status >= 200 && status < 300, status, json: async () => payload });
  if (path === '/api/workstation/browser/screen') {
    server.calls.push({ url, method: 'GET', body: null });
    return screen.answer ? reply(200, screen.answer) : reply(404, { detail: 'no such route' });
  }
  if (path === '/api/workstation/browser' && String(url).includes('live=1')) {
    server.calls.push({ url, method: 'GET', body: null });
    return reply(200, { url: browser.url, title: browser.title, tabs: browser.tabs,
                        activity: screen.activity.splice(0), seq: 0, view: screen.view, live: true,
                        runs_in: 'workstation' });
  }
  return _framesFetch(url, opts);
};
"""


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    from test_the_agent_browser_window_js import MODULE, _SHIM, _STUBS
    from test_tool_effect_surfaces_js import _make_sandbox
    d = _make_sandbox(tmp_path_factory.mktemp("live-browser"), MODULE, _SHIM + _LIVE_SHIM_TAIL, _STUBS)
    shutil.copy(ROOT / "static" / "js" / "workstationScreen.js", d / "workstationScreen.js")
    return d


def _live_window(window, script):
    from test_the_agent_browser_window_js import _PREAMBLE
    from test_tool_effect_surfaces_js import _run
    preamble = _PREAMBLE.replace("fireWindow, fireWin } from './shim.js';",
                                 "fireWindow, fireWin, screen } from './shim.js';")
    preamble += (
        f"const CLIENT = {json.dumps(_CLIENT)};\n"
        "const streams = (o) => { screen.answer = Object.assign({ kind: 'kasmvnc', holder: 'agent',\n"
        "  client: CLIENT }, o || {}); };\n"
        "const live = () => mod._test.live();\n"
        "const gets = () => server.calls.filter((c) => c.method === 'GET'\n"
        "  && String(c.url).startsWith('/api/workstation/browser?')).map((c) => c.url);\n"
    )
    return _run(window, preamble, script)


@pytest.mark.parametrize("frame,view,expect", [
    # The stage is the screen's shape: half size, the page below Firefox's own bar.
    ({"left": 100, "top": 50, "width": 640, "height": 400}, {"x": 0, "y": 85, "w": 1280, "h": 715},
     {"left": 0, "top": 42.5, "width": 640, "height": 357.5}),
    # Wider than the screen's shape: scaled to its height and centred.
    ({"left": 100, "top": 50, "width": 800, "height": 400}, {"x": 0, "y": 85, "w": 1280, "h": 715},
     {"left": 80, "top": 42.5, "width": 640, "height": 357.5}),
    ({"left": 100, "top": 50, "width": 0, "height": 400}, {"x": 0, "y": 0, "w": 5, "h": 5}, None),
    ({"left": 100, "top": 50, "width": 640, "height": 400}, None, None),
])
def test_the_page_is_found_on_the_screen_as_the_client_draws_it(window, frame, view, expect):
    out = _live_window(window, f"""
        out({{ r: mod.viewRegion({json.dumps(frame)}, {{ left: 100, top: 50 }},
                                 {{ w: 1280, h: 800 }}, {json.dumps(view)}) }});
    """)
    assert out["r"] == expect


def test_a_browser_that_streams_is_shown_live_and_no_picture_is_asked_for(window):
    out = _live_window(window, """
        streams();
        await open();
        await settle(120);
        const w = win();
        const f = live().frame;
        out({ framed: !!f && f.parentNode === w.page, tag: f && f.tagName, src: f && f.src,
              isLive: w.page.classList.contains('abw-live'), tabs: w.tabs.hidden, bar: w.bar.hidden,
              gets: gets(), status: w.statusText.textContent, title: w.title.textContent,
              size: live().size, view: live().view });
    """)
    assert out["framed"] and out["tag"].lower() == "iframe" and out["src"] == _CLIENT
    assert out["isLive"] is True
    assert out["tabs"] is True and out["bar"] is True, "Pantheon's address bar sat over Firefox's own"
    assert out["gets"] and all("live=1" in g and "if_none_match" not in g for g in out["gets"]), \
        "a picture was asked for while live"
    assert out["status"] == "Your browser, live in your workstation." and out["title"] == "Shop"
    assert out["view"] == {"x": 0, "y": 85, "w": 1280, "h": 715}
    assert out["size"] == {"w": 1280, "h": 715}, "the hand and the notes measure the page, not the screen"


def test_the_pages_stand_in_is_laid_over_the_page_on_the_screen(window):
    out = _live_window(window, """
        streams();
        await open();
        await settle(60);
        const w = win();
        w.page.getBoundingClientRect = () => ({ left: 100, top: 50, width: 640, height: 400 });
        live().frame.getBoundingClientRect = () => ({ left: 100, top: 50, width: 640, height: 400 });
        await settle(80);
        const st = w.img.style;
        out({ left: st.left, top: st.top, width: st.width, height: st.height });
    """)
    assert out == {"left": "0px", "top": "42.5px", "width": "640px", "height": "357.5px"}


@pytest.mark.parametrize("answer", [
    {"client": "https://elsewhere.example/vnc.html"},
    {"client": "/api/workstation/desktop/websockify"},
    {"kind": None, "why": "This workstation has no KasmVNC, so its browser is shown as pictures."},
])
def test_no_page_but_pantheons_own_client_is_ever_framed_and_frames_say_why(window, answer):
    out = _live_window(window, f"""
        streams({json.dumps(answer)});
        await open();
        await settle(80);
        const w = win();
        out({{ frame: !!live().frame, client: live().client, src: w.img.src, tabs: w.tabs.hidden,
               status: w.statusText.textContent, gets: gets() }});
    """)
    assert out["frame"] is False and out["client"] == ""
    assert out["src"].startswith("data:image/png;base64,UE5H") and out["tabs"] is False
    assert not any("live=1" in g for g in out["gets"])
    if answer.get("why"):
        assert out["status"] == "Your browser, in your workstation. " + answer["why"]


def test_an_older_workstation_is_frames_as_before(window):
    out = _live_window(window, """
        await open();
        await settle(60);
        out({ frame: !!live().frame, src: win().img.src, status: win().statusText.textContent,
              asked: server.calls.filter((c) => c.url === '/api/workstation/browser/screen').length });
    """)
    assert out["frame"] is False and out["src"].startswith("data:image/png;base64,UE5H")
    assert out["status"] == "Your browser, in your workstation." and out["asked"] == 1


def test_live_a_click_takes_the_browser_and_is_not_sent_as_a_click(window):
    out = _live_window(window, """
        streams();
        await open();
        await settle(60);
        const w = win();
        const f = live().frame;
        let focused = 0;
        f.focus = () => { focused += 1; };
        fire(w.page, 'click', { clientX: 420, clientY: 250 }); await done(); await settle(30);
        const held = mod._test.state().holder;
        fire(w.page, 'click', { clientX: 420, clientY: 250 });
        fire(w.page, 'keydown', { key: 'a' }); await done();
        out({ held, focused, clicks: acts().filter((a) => a.action === 'click').length,
              typed: acts().filter((a) => a.action === 'type' || a.action === 'press').length,
              controls: server.calls.filter((c) => c.url === '/api/workstation/control'
                && c.method === 'POST').map((c) => c.body.holder),
              hint: w.hint.textContent });
    """)
    assert out["held"] == "person" and out["controls"] == ["person"]
    assert out["clicks"] == 0 and out["typed"] == 0, "the live browser got a second, synthetic click"
    assert out["focused"] >= 1, "the browser did not get the keyboard"
    assert out["hint"].startswith("You have the browser: use it as your own")


def test_the_live_browser_is_taken_down_while_hidden_and_when_the_window_closes(window):
    out = _live_window(window, """
        streams();
        await open();
        await settle(40);
        const shown = !!live().frame;
        document.hidden = true;
        fire(document, 'visibilitychange');
        const hidden = !!live().frame;
        document.hidden = false;
        fire(document, 'visibilitychange');
        await settle(80);
        const back = !!live().frame;
        mod.closeAgentBrowser();
        await settle(20);
        out({ shown, hidden, back, closed: live() });
    """)
    assert out["shown"] is True and out["hidden"] is False and out["back"] is True
    assert out["closed"]["frame"] is None and out["closed"]["client"] is None


def test_what_the_browser_copies_reaches_the_person_and_their_clipboard_reaches_it(window):
    out = _live_window(window, """
        Object.defineProperty(globalThis, 'location',
          { value: { origin: 'http://pantheon.test' }, configurable: true, writable: true });
        globalThis.isSecureContext = false;   // no quiet write: the Copy button is the way
        const clip = { text: 'from the person' };
        Object.defineProperty(globalThis, 'navigator', { configurable: true, writable: true, value: {
          clipboard: { readText: async () => clip.text } } });
        streams();
        await open();
        await settle(60);
        const w = win();
        const posted = [];
        live().frame.contentWindow = { postMessage: (m, o) => posted.push({ m, o }), focus() {} };
        const say = (data, origin) => mod._test.onMessage({ source: live().frame.contentWindow,
          origin: origin || 'http://pantheon.test', data });
        say({ action: 'clipboardrx', value: 'elsewhere' }, 'https://evil.example');
        const strangerKept = live().clip;
        say({ action: 'clipboardrx', value: 'copied in firefox' });
        await settle(10);
        const offered = !w.copy.hidden;
        await mod.copyFromBrowser();
        const pasteBefore = await mod.pasteToBrowser();
        await mod.takeOver(); await settle(20);
        const pasteShown = !w.paste.hidden;
        const pasted = await mod.pasteToBrowser();
        out({ strangerKept, offered, copied: globalThis.__copiedText || [], clipAfter: live().clip,
              pasteBefore, pasteShown, pasted, posted });
    """)
    assert out["strangerKept"] == "", "another origin's message was taken as the browser's"
    assert out["offered"] is True and out["copied"] == ["copied in firefox"] and out["clipAfter"] == ""
    assert out["pasteBefore"] is False, "the clipboard went in while the agent held the browser"
    assert out["pasteShown"] is True and out["pasted"] is True
    assert out["posted"] == [{"m": {"action": "clipboardsnd", "value": "from the person"},
                              "o": "http://pantheon.test"}]
