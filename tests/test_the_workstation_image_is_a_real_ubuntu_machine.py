# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-01` end to end: the image builds, and the daemon inside it answers for
a real Ubuntu machine — driven through Pantheon's own client, over HTTP, with
nothing faked: Unix accounts, a 0700 home, `sudo` switched on and off, a real
X display that a click and typed text change, Firefox opening from the tray,
*Reset to clean*, and accounts that outlive the container being replaced.

It builds and runs a Docker image, so it is **opt-in**: it runs only when
Docker answers and `PANTHEON_WORKSTATION_E2E=1`. The normal suite never builds
an image.

    PANTHEON_WORKSTATION_E2E=1 python -m pytest tests/test_the_workstation_image_is_a_real_ubuntu_machine.py

`PANTHEON_WORKSTATION_E2E_IMAGE=<tag>` uses an image already built instead of
building `workstation/`. A builder behind a TLS-inspecting proxy passes its CA
file as `PANTHEON_WORKSTATION_BUILD_CA` (the Dockerfile's `build-ca` secret)
and, if Ubuntu's plain-HTTP mirrors are not reachable, an HTTPS mirror as
`PANTHEON_WORKSTATION_APT_MIRROR`; `HTTPS_PROXY` is passed through as a build
argument when it is set. None of it is written into the image.

The container runs on the host network on a free port, so nothing needs NAT;
its volumes are its own and are removed afterwards.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from workstation import protocol as P
from workstation.ubuntu import UID_MAX, UID_MIN

ROOT = Path(__file__).resolve().parent.parent
E2E_ENV = "PANTHEON_WORKSTATION_E2E"
IMAGE_ENV = "PANTHEON_WORKSTATION_E2E_IMAGE"
BUILD_CA_ENV = "PANTHEON_WORKSTATION_BUILD_CA"
MIRROR_ENV = "PANTHEON_WORKSTATION_APT_MIRROR"
PAIRING_GID = 4242
BUILT_TAG = "pantheon-workstation:e2e-test"
# The panel's buttons (`skel/.config/xfce4`, `D-2026-10-31-02`), in screenshot
# pixels: the panel is 40 px high along the bottom and each button is 40 px
# square from the left — the menu, Terminal, Firefox, Files. Measured on a
# desktop built from these same files (2026-10-31, Xvfb): a click at each
# opened what it names. A change to the panel moves them, and this test and the
# `workstation-desktop` skill are where it shows.
TRAY_MENU = (20, 780)
TRAY_TERMINAL = (60, 780)
TRAY_FIREFOX = (100, 780)
TRAY_FILES = (140, 780)
TERMINAL_CLASS = "xfce4-terminal"


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
    reason=f"builds and runs the workstation image: set {E2E_ENV}=1 where Docker answers")


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
    argv = ["build", "--network", "host", "-t", BUILT_TAG]
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        argv += ["--build-arg", f"HTTPS_PROXY={proxy}", "--build-arg", f"https_proxy={proxy}"]
    if os.environ.get(MIRROR_ENV):
        argv += ["--build-arg", f"APT_MIRROR={os.environ[MIRROR_ENV]}"]
    if os.environ.get(BUILD_CA_ENV):
        argv += ["--secret", f"id=build-ca,src={os.environ[BUILD_CA_ENV]}"]
    _docker(*argv, str(ROOT / "workstation"), timeout=1800)
    return BUILT_TAG


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Station:
    name: str
    image: str
    port: int
    homes: str
    pairing: str

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        _docker("run", "-d", "--name", self.name, "--network", "host", "--shm-size", "1g",
                "-e", f"PANTHEON_WORKSTATION_PAIRING_GID={PAIRING_GID}",
                "-v", f"{self.homes}:/home", "-v", f"{self.pairing}:{P.DEFAULT_PAIRING_DIR}",
                self.image, "--system", "ubuntu", "--bind", "127.0.0.1", "--port", str(self.port))
        self.wait_healthy()

    def token(self) -> str:
        return _docker("exec", self.name, "cat", f"{P.DEFAULT_PAIRING_DIR}/{P.TOKEN_FILENAME}"
                       ).stdout.strip()

    def client(self) -> WorkstationClient:
        return WorkstationClient(self.url, self.token())

    def wait_healthy(self, limit: float = 90.0) -> float:
        started = time.monotonic()
        while time.monotonic() - started < limit:
            try:
                run(WorkstationClient(self.url, "").health())
                return time.monotonic() - started
            except WorkstationError:
                time.sleep(0.1)
        logs = _docker("logs", self.name, check=False)
        raise AssertionError(f"the workstation never answered:\n{logs.stdout[-3000:]}"
                             f"{logs.stderr[-3000:]}")

    def recreate(self) -> None:
        """A new container on the same volumes — what an image update or
        `docker compose up --force-recreate` does. Unlike `docker restart`,
        this throws away `/etc/passwd`, `/etc/group` and the sudoers file."""
        _docker("rm", "-f", self.name, timeout=120)
        self.start()


@pytest.fixture(scope="module")
def station(image):
    tag = secrets.token_hex(4)
    st = Station(name=f"pantheon-ws-e2e-{tag}", image=image, port=_free_port(),
                 homes=f"pantheon-ws-e2e-homes-{tag}", pairing=f"pantheon-ws-e2e-pairing-{tag}")
    try:
        st.start()
        yield st
    finally:
        _docker("rm", "-f", st.name, check=False)
        _docker("volume", "rm", "-f", st.homes, st.pairing, check=False)


def sh(client, account, command, **kw):
    return run(client.exec(account, command, **kw))


def _png_size(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def _wait_for(predicate, limit=30.0, step=0.25):
    started = time.monotonic()
    while time.monotonic() - started < limit:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return None


# ── accounts and homes ───────────────────────────────────────────────────────

def test_a_person_gets_a_real_unix_account_with_a_private_home(station):
    client, ann = station.client(), account_for("e2e-ann")
    made = run(client.ensure(ann))
    assert made["created"] is True and made["home"] == f"/home/{ann}"
    assert made["display"] and made["display"].startswith(":")
    r = sh(client, ann, "id -un; id -u; stat -c '%a %U' ~; id -Gn")
    name, uid, home_mode, groups = r["stdout"].splitlines()
    assert name == ann and UID_MIN <= int(uid) <= UID_MAX
    assert home_mode == f"700 {ann}"
    assert "pantheon-agents" in groups.split()
    assert run(client.ensure(ann))["created"] is False


def test_one_persons_agent_cannot_read_anothers_home_or_the_pairing_token(station):
    client = station.client()
    run(client.config(sudo=False))
    ann, bob = account_for("e2e-ann"), account_for("e2e-bob")
    run(client.write(ann, "private.txt", "ann's"))
    run(client.ensure(bob))
    r = sh(client, bob, f"cat /home/{ann}/private.txt; echo rc=$?; "
                        f"cat {P.DEFAULT_PAIRING_DIR}/{P.TOKEN_FILENAME}; echo rc=$?")
    assert r["stdout"].split() == ["rc=1", "rc=1"]
    assert "Permission denied" in r["stderr"]
    owner = _docker("exec", station.name, "stat", "-c", "%U %g %a",
                    f"{P.DEFAULT_PAIRING_DIR}/{P.TOKEN_FILENAME}").stdout.split()
    assert owner == ["root", str(PAIRING_GID), "640"]


def test_files_the_daemon_writes_belong_to_the_account(station):
    client, ann = station.client(), account_for("e2e-ann")
    run(client.config(sudo=False))
    run(client.write(ann, "proj/src/hello.txt", "hello from the client"))
    assert run(client.read(ann, "~/proj/src/hello.txt"))["data"] == b"hello from the client"
    r = sh(client, ann, "stat -c '%U %a' proj proj/src proj/src/hello.txt")
    assert [line.split()[0] for line in r["stdout"].splitlines()] == [ann] * 3
    listing = run(client.list(ann, "proj", recursive=True))
    assert {e["path"] for e in listing["entries"]} == {"src", "src/hello.txt"}
    with pytest.raises(WorkstationError) as e:
        run(client.read(ann, "/etc/shadow"))
    assert e.value.code == "outside_home"


def test_an_oversized_request_is_refused_before_it_is_read(station):
    """The daemon checks Content-Length first: a body larger than it reads is
    413 with nothing read, and the client refuses a file too large to send."""
    client, ann = station.client(), account_for("e2e-ann")
    with pytest.raises(WorkstationError) as e:
        run(client.write(ann, "big.bin", b"\0" * (P.MAX_FILE_BYTES + 1)))
    assert e.value.code == "too_large"
    _, path = P.route_path("write", ann)
    host, port = station.url.rsplit("//", 1)[1].split(":")
    with socket.create_connection((host, int(port)), timeout=10) as s:
        s.sendall((f"POST {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {client.token}\r\n"
                   f"Content-Type: application/json\r\nContent-Length: {P.MAX_BODY_BYTES + 1}\r\n"
                   "\r\n").encode())
        answer = b""
        while chunk := s.recv(4096):  # the daemon answers and closes
            answer += chunk
    status, _, body = answer.decode("latin1").partition("\r\n\r\n")
    assert status.split()[1] == "413"
    assert json.loads(body)["error"] == "too_large"


def test_commands_stream_and_time_out_as_the_account(station):
    client, ann = station.client(), account_for("e2e-ann")
    seen = []
    r = run(client.exec(ann, "echo one; sleep 0.3; id -un >&2",
                        on_output=lambda kind, text: seen.append((kind, text))))
    assert ("stdout", "one\n") in seen and ("stderr", f"{ann}\n") in seen and r["exit_code"] == 0
    slow = sh(client, ann, "sleep 30", timeout_s=1)
    assert slow["timed_out"] is True and slow["exit_code"] == 124


# ── sudo ─────────────────────────────────────────────────────────────────────

def test_sudo_is_a_switch_the_daemon_enforces(station):
    client, ann = station.client(), account_for("e2e-ann")
    run(client.ensure(ann))
    try:
        assert run(client.config(sudo=True))["sudo"] is True
        on = sh(client, ann, "sudo -n id -u")
        assert (on["exit_code"], on["stdout"].strip()) == (0, "0")
        assert run(client.config(sudo=False))["sudo"] is False
        off = sh(client, ann, "sudo -n true")
        assert off["exit_code"] != 0 and "password is required" in off["stderr"]
        assert run(client.health())["sudo"] is False
    finally:
        run(client.config(sudo=False))


# ── the display ──────────────────────────────────────────────────────────────

def _terminal_centre(client, account):
    r = sh(client, account, f"xdotool search --onlyvisible --class {TERMINAL_CLASS} "
                            "getwindowgeometry --shell")
    geo = dict(line.split("=", 1) for line in r["stdout"].split() if "=" in line)
    return int(geo["X"]) + int(geo["WIDTH"]) // 2, int(geo["Y"]) + int(geo["HEIGHT"]) // 2


def test_a_real_display_is_seen_typed_into_and_the_picture_changes(station):
    client, ann = station.client(), account_for("e2e-typist")
    run(client.ensure(ann))
    shot = run(client.screenshot(ann))
    png = base64.b64decode(shot["data_b64"])
    assert shot["mime"] == "image/png" and _png_size(png) == (P.SCREEN_WIDTH, P.SCREEN_HEIGHT)
    jpeg = run(client.screenshot(ann, fmt="jpeg"))
    assert jpeg["mime"] == "image/jpeg" and base64.b64decode(jpeg["data_b64"])[:2] == b"\xff\xd8"
    assert run(client.screenshot(ann, if_none_match=shot["digest"])) is None  # nothing moved

    x, y = _wait_for(lambda: _terminal_centre(client, ann) if sh(
        client, ann, f"xdotool search --onlyvisible --class {TERMINAL_CLASS}")["stdout"].strip()
        else None)
    run(client.input(ann, "click", x=x, y=y))
    run(client.input(ann, "type", text="echo typed-through-the-screen > ~/typed.txt"))
    after = run(client.input(ann, "key", keys="Return", screenshot_after=True))
    assert after["screenshot"]["digest"] != shot["digest"]
    typed = _wait_for(lambda: sh(client, ann, "cat ~/typed.txt 2>/dev/null")["stdout"].strip())
    assert typed == "typed-through-the-screen"


def test_every_input_action_reaches_the_display(station):
    client, ann = station.client(), account_for("e2e-typist")
    run(client.ensure(ann))
    # On the bare desktop, right of the terminal (centred, about 918 px wide, so
    # it ends near x 1100): nothing here types into a shell.
    for action, fields in [
        ("move", {"x": 1200, "y": 300}), ("click", {"x": 1200, "y": 300}),
        ("double_click", {"x": 1200, "y": 300}), ("triple_click", {"x": 1200, "y": 300}),
        ("middle_click", {"x": 1200, "y": 300}), ("right_click", {"x": 1200, "y": 300}),
        ("key", {"keys": "Escape"}), ("drag", {"x": 1200, "y": 300, "to_x": 1240, "to_y": 350}),
        ("mouse_down", {"x": 1200, "y": 400}), ("mouse_up", {"x": 1220, "y": 420}),
        ("scroll", {"x": 1200, "y": 300, "dy": 2}), ("scroll", {"x": 1200, "y": 300, "dx": -1}),
        ("wait", {"ms": 50}),
    ]:
        assert run(client.input(ann, action, **fields))["ok"] is True, action
    where = sh(client, ann, "xdotool getmouselocation --shell")["stdout"]
    assert "X=1200" in where and "Y=300" in where  # the last pointer move landed


def test_another_account_cannot_see_or_drive_my_display(station):
    client = station.client()
    ann, bob = account_for("e2e-typist"), account_for("e2e-bob")
    display = run(client.ensure(ann))["display"]
    run(client.ensure(bob))
    r = sh(client, bob, f"DISPLAY={display} XAUTHORITY=/nonexistent xdotool getmouselocation")
    assert r["exit_code"] != 0 and "Authorization required" in r["stderr"]
    r = sh(client, bob, f"DISPLAY={display} xdotool getmouselocation")  # bob's own cookie
    assert r["exit_code"] != 0


def test_a_person_holding_the_screen_keeps_the_agent_off_it(station):
    client, ann = station.client(), account_for("e2e-typist")
    run(client.control(ann, "person"))
    try:
        with pytest.raises(WorkstationError) as e:
            run(client.input(ann, "move", x=10, y=10))
        assert e.value.code == "busy"
        run(client.input(ann, "move", x=11, y=11, holder="person"))
    finally:
        run(client.control(ann, "agent"))


# ── `D-2026-10-31-01`: the live desktop ────────────────────────────────────────

async def _rfb_session(client, account, viewer, then):
    """A real RFB session with the person's display, through the daemon's
    `desktop` route — the websocket Pantheon relays — as far as the server's
    hello, then `then(ws)`. Security type None: the websocket's login, which
    the daemon adds and nobody else holds, was the authentication."""
    async with client.desktop_stream(account, viewer) as ws:
        buf = bytearray()

        async def need(n):
            while len(buf) < n:
                buf.extend(await asyncio.wait_for(ws.recv(), 20))
            out = bytes(buf[:n])
            del buf[:n]
            return out

        version = await need(12)
        await ws.send(b"RFB 003.008\n")
        types = list(await need((await need(1))[0]))
        await ws.send(bytes([1]))
        result = struct.unpack(">I", await need(4))[0]
        await ws.send(bytes([1]))                           # shared: others stay
        size = struct.unpack(">HH", await need(4))
        return version, types, result, size, await then(ws)


def _pointer_to(x, y):
    return struct.pack(">BBHH", 5, 0, x, y)                 # PointerEvent, no button


def test_the_desktop_streams_and_only_the_person_holding_it_drives_it(station):
    client, ann = station.client(), account_for("e2e-live")
    answer = run(client.desktop(ann))
    assert answer["kind"] == "kasmvnc" and "why" not in answer, answer
    assert answer["holder"] == "agent"

    async def where():
        r = await client.exec(ann, "xdotool getmouselocation --shell")
        return r["stdout"]

    async def drive(ws):
        await client.input(ann, "move", x=10, y=10)
        await ws.send(_pointer_to(500, 400))
        await asyncio.sleep(1.0)
        watching = await where()                              # the agent holds it: read-only
        await client.control(ann, "person")
        try:
            await asyncio.sleep(1.5)                          # the logins file, re-read live
            await ws.send(_pointer_to(600, 450))
            await asyncio.sleep(1.0)
            holding = await where()
        finally:
            await client.control(ann, "agent")
        await asyncio.sleep(1.5)
        await ws.send(_pointer_to(700, 500))
        await asyncio.sleep(1.0)
        return watching, holding, await where()

    version, types, result, size, (watching, holding, back) = run(
        _rfb_session(client, ann, "person", drive))
    assert version == b"RFB 003.008\n" and 1 in types and result == 0
    assert size == (P.SCREEN_WIDTH, P.SCREEN_HEIGHT)
    assert "X=10" in watching and "Y=10" in watching, "the stream drove while the agent held it"
    assert "X=600" in holding and "Y=450" in holding, "Take over did not let the stream drive"
    assert "X=600" in back and "Y=450" in back, "Hand back left the stream driving"


def test_a_watcher_sees_the_desktop_and_never_drives_it(station):
    client, ann = station.client(), account_for("e2e-live")
    run(client.control(ann, "person"))
    try:
        async def poke(ws):
            await client.input(ann, "move", x=20, y=20, holder="person")
            await ws.send(_pointer_to(800, 600))
            await asyncio.sleep(1.0)
            return (await client.exec(ann, "xdotool getmouselocation --shell"))["stdout"]

        version, _types, result, size, where = run(_rfb_session(client, ann, "watch", poke))
    finally:
        run(client.control(ann, "agent"))
    assert version == b"RFB 003.008\n" and result == 0 and size == (P.SCREEN_WIDTH, P.SCREEN_HEIGHT)
    assert "X=20" in where and "Y=20" in where, "a watcher drove the desktop"


def test_the_desktops_logins_are_not_the_accounts_to_read(station):
    """The file the display reads its two logins from is root's, readable by
    the display (the account's group) — so the agent, which runs as that
    account, can read it but never rewrite who may drive; another account
    cannot read it at all."""
    client = station.client()
    ann, bob = account_for("e2e-live"), account_for("e2e-bob")
    run(client.desktop(ann))
    uid = sh(client, ann, "id -u")["stdout"].strip()
    path = f"/run/pantheon-desktop/{uid}/kasmpasswd"
    assert sh(client, ann, f"stat -c '%U %a' {path}")["stdout"].split() == ["root", "640"]
    assert sh(client, ann, f"echo x:y:rw >> {path}")["exit_code"] != 0
    run(client.ensure(bob))
    assert sh(client, bob, f"cat {path}")["exit_code"] != 0


def test_the_tray_opens_a_terminal_and_firefox(station):
    client, ann = station.client(), account_for("e2e-browser")
    run(client.ensure(ann))
    # The desktop is XFCE with Pantheon's frames (`D-2026-10-31-02`), not the fallback.
    assert sh(client, ann, "pgrep -u $(id -u) -xc xfwm4")["stdout"].strip() == "1"
    assert sh(client, ann, "pgrep -u $(id -u) -xc jwm")["stdout"].strip() == "0"
    assert sh(client, ann, "test -f /usr/share/themes/Pantheon/xfwm4/themerc && echo theme"
              )["stdout"].strip() == "theme"
    # Windows, not processes: the panel's terminals share one process.
    count = lambda: sh(client, ann, f"xdotool search --onlyvisible --class {TERMINAL_CLASS} "  # noqa: E731
                                    "| wc -l")["stdout"].strip()
    before = int(count() or 0)
    run(client.input(ann, "click", x=TRAY_TERMINAL[0], y=TRAY_TERMINAL[1]))
    assert _wait_for(lambda: int(count() or 0) > before, limit=15)
    run(client.input(ann, "click", x=TRAY_FILES[0], y=TRAY_FILES[1]))
    assert _wait_for(lambda: sh(client, ann, "xdotool search --onlyvisible --class thunar "
                                             "2>/dev/null | head -1")["stdout"].strip(), limit=30)
    run(client.input(ann, "click", x=TRAY_MENU[0], y=TRAY_MENU[1]))
    assert _wait_for(lambda: sh(client, ann, "xdotool search --onlyvisible --name "
                                             "'^Whisker Menu$' 2>/dev/null | head -1")
                     ["stdout"].strip(), limit=15), "the panel's menu did not open"
    run(client.input(ann, "key", keys="Escape"))
    run(client.input(ann, "click", x=TRAY_FIREFOX[0], y=TRAY_FIREFOX[1]))
    window = _wait_for(lambda: sh(client, ann, "xdotool search --onlyvisible --class firefox "
                                               "2>/dev/null | head -1")["stdout"].strip(), limit=90)
    assert window, "Firefox did not open a window from the tray"
    title = _wait_for(lambda: "Mozilla Firefox" in sh(
        client, ann, f"xdotool getwindowname {window}")["stdout"], limit=30)
    assert title
    # Mozilla's build from Mozilla's repository, not the snap wrapper, with
    # our policy in force.
    r = sh(client, ann, "readlink -f $(command -v firefox); firefox --version; "
                        "test -f /etc/firefox/policies/policies.json && echo policy")
    assert r["stdout"].splitlines()[0] == "/usr/lib/firefox/firefox"
    assert r["stdout"].splitlines()[1].startswith("Mozilla Firefox ")
    assert r["stdout"].splitlines()[2] == "policy"


# ── reset, and a new container on the same volumes ───────────────────────────

def test_reset_puts_the_home_and_the_display_back(station):
    client, carol = station.client(), account_for("e2e-carol")
    run(client.ensure(carol))
    run(client.write(carol, "junk/a.txt", "x"))
    sh(client, carol, "rm -f ~/.bashrc; (setsid sleep 1000 >/dev/null 2>&1 &)")
    assert sh(client, carol, "pgrep -u $(id -u) -xc sleep")["stdout"].strip() == "1"
    assert run(client.reset(carol)) == {"account": carol, "reset": True}
    r = sh(client, carol, "ls -A ~; echo ---; pgrep -u $(id -u) -x sleep; stat -c %a ~")
    listing, rest = r["stdout"].split("---\n")
    names = set(listing.split())
    assert "junk" not in names and {".bashrc", ".jwmrc", ".Xdefaults", ".profile",
                                     ".config"} <= names
    assert rest.strip() == "700"  # and no sleep survived
    # The desktop is back without being asked for: the display restarted.
    assert sh(client, carol, "pgrep -u $(id -u) -xc Xkasmvnc")["stdout"].strip() == "1"
    shot = run(client.screenshot(carol))
    assert _png_size(base64.b64decode(shot["data_b64"])) == (P.SCREEN_WIDTH, P.SCREEN_HEIGHT)


def test_a_reset_brings_the_desktop_back_even_for_a_shell_only_person(station):
    client, frank = station.client(), account_for("e2e-frank")
    sh(client, frank, "true")  # exec makes the account and no display
    assert sh(client, frank, "pgrep -u $(id -u) -xc Xkasmvnc")["stdout"].strip() == "0"
    run(client.reset(frank))
    assert sh(client, frank, "pgrep -u $(id -u) -xc Xkasmvnc")["stdout"].strip() == "1"


def test_accounts_their_files_and_the_sudo_choice_survive_the_container_being_replaced(station):
    client, dave, erin = station.client(), account_for("e2e-dave"), account_for("e2e-erin")
    run(client.config(sudo=False))
    run(client.ensure(erin))  # a second person, so the numbers are not simply "the first"
    run(client.ensure(dave))
    uid = sh(client, dave, "id -u")["stdout"].strip()
    run(client.write(dave, "keep.txt", "kept"))
    station.recreate()  # /etc/passwd is the image's again; /home is the volume
    gone = _docker("exec", station.name, "getent", "passwd", dave, check=False)
    assert gone.returncode != 0  # the account really was lost with the container
    client = station.client()
    assert run(client.health())["sudo"] is False
    rule = _docker("exec", station.name, "cat", "/etc/sudoers.d/pantheon-workstation").stdout
    assert "NOPASSWD" not in rule
    again = run(client.ensure(dave))  # made again, before erin is, with its own number
    assert again["created"] is False
    r = sh(client, dave, "id -un; id -u; cat keep.txt; echo; stat -c %U keep.txt")
    assert r["stdout"].splitlines() == [dave, uid, "kept", dave]
    shot = run(client.screenshot(dave))
    assert _png_size(base64.b64decode(shot["data_b64"])) == (P.SCREEN_WIDTH, P.SCREEN_HEIGHT)


def test_the_daemon_says_what_it_is_and_holds_no_secret_of_pantheons(station):
    health = run(WorkstationClient(station.url, "").health())
    assert (health["agent"], health["protocol"], health["backend"]) == (
        P.AGENT_NAME, P.PROTOCOL_VERSION, "container")
    env = json.loads(_docker("inspect", station.name).stdout)[0]["Config"]["Env"]
    assert not [e for e in env if e.split("=")[0] in (P.TOKEN_ENV, "OPENAI_API_KEY", "HF_TOKEN")]
    mounts = json.loads(_docker("inspect", station.name).stdout)[0]["Mounts"]
    assert sorted(m["Destination"] for m in mounts) == ["/home", P.DEFAULT_PAIRING_DIR]
