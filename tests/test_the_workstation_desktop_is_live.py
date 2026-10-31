# SPDX-License-Identifier: AGPL-3.0-or-later
"""`D-2026-10-31-01` — the workstation's desktop, live, through Pantheon.

KasmVNC's X server is each person's display (`workstation/ubuntu.py`); the
daemon joins a viewer's websocket to it with a login only the daemon holds
(`workstation/agentd.py`), the VM backend's host joins it to the person's
machine (`workstation/vm.py`), Pantheon relays the person's browser to that
(`routes/workstation_routes.py`), and serves the web client from its own image
(`src/desktop_client.py`). A test machine has no KasmVNC, so `FakeKasm` stands
where it listens, and is held to what KasmVNC does at 1.5.2 (websocket.c, read
when this was written): a Basic login checked as `crypt(secret, "$5$kasm$")`
against the `user:hash:perms` file it re-reads on every change, the
subprotocol `binary`, and nothing served to a viewer who is not in the file.
Everything else is the shipped code.

What is pinned, and why each is a defect if it breaks:

  * **the logins** — the hash is glibc's SHA-256 crypt (the specification's own
    vector, and `openssl passwd -5` where it is installed), so KasmVNC accepts
    the secret the daemon sends; `person` writes only while the person holds
    the screen and `watch` never does; the file is written in place, 0640 in a
    0750 folder, and never through a link;
  * **the display** — KasmVNC is started on loopback only, behind the file,
    with no web server, no TLS-off switch and no public STUN lookup; Xvfb is
    the display wherever KasmVNC is missing or will not start, and why is said;
  * **the daemon's stream** — a viewer reaches the display only through the
    daemon, with the daemon's login and none of the caller's headers; *Take
    over* and *Hand back* change what the open stream may do, at once, and a
    reset gives the screen back to the agent; a malformed upgrade is a plain
    refusal before anything is joined;
  * **the VM host** — the same stream, one hop further, and the machine counts
    as in use for as long as it is open;
  * **Pantheon's relay** — only a signed-in person, from Pantheon's own pages,
    reaches it; only an admin watches another person, and never drives; the
    page the window frames is Pantheon's own copy, under its own policy.
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src.workstation_client import WorkstationClient, WorkstationError, account_for
from tests.helpers.vm_fleet import HOST_TOKEN, CountingScreen, InProcessMachine, vm_host
from tests.helpers.workstation_daemon import PictureScreen, running_workstation
from workstation import agentd
from workstation import protocol as P
from workstation.agentd import WorkstationError as DaemonError
from workstation import ubuntu
from workstation.ubuntu import DesktopLogins, XDisplay, kasmvnc_argv, sha256_crypt

ROOT = Path(__file__).resolve().parents[1]
ANN = account_for("ann")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def no_chown(monkeypatch):
    """The logins file is root's in a workstation; a test runs as whoever runs it."""
    monkeypatch.setattr(os, "chown", lambda *a, **k: None)
    monkeypatch.setattr(os, "fchown", lambda *a, **k: None)


# ── a stand-in for KasmVNC, held to what KasmVNC does ────────────────────────

class FakeKasm:
    """Listens where KasmVNC would; checks a login the way KasmVNC does — the
    secret, crypted with the fixed salt, against the line for that user in
    the logins file, read again for every check — and answers `who` with the
    viewer's name and rights as the file says them now."""

    def __init__(self) -> None:
        from websockets.datastructures import Headers
        from websockets.http11 import Response
        from websockets.sync.server import serve

        self.seen = []        # each handshake's headers, as KasmVNC received them
        self.files = {}       # account → its logins file

        def check(conn, request):
            self.seen.append(dict(request.headers.raw_items()))
            viewer = self._login(request.headers.get("Authorization", ""))
            if viewer is None:
                return Response(401, "Unauthorized", Headers(), b"")
            conn.viewer = viewer
            return None

        def handler(conn):
            for message in conn:
                if message == b"who":
                    who = self._rights(conn.viewer)
                    conn.send(f"{conn.viewer[1]}:{who}".encode())
                else:
                    conn.send(b"echo:" + (message if isinstance(message, bytes) else message.encode()))

        self.server = serve(handler, "127.0.0.1", 0, subprotocols=[P.DESKTOP_SUBPROTOCOL],
                            process_request=check, compression=None)
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _lines(self, account):
        path = self.files.get(account)
        if path is None or not path.exists():
            return {}
        out = {}
        for line in path.read_text().splitlines():
            user, hashed, perms = line.split(":")
            out[user] = (hashed, perms)
        return out

    def _login(self, header):
        if not header.startswith("Basic "):
            return None
        user, _, secret = base64.b64decode(header[6:]).decode().partition(":")
        for account in self.files:
            line = self._lines(account).get(user)
            if line and sha256_crypt(secret, "kasm") == line[0]:
                return (account, user)
        return None

    def _rights(self, viewer):
        account, user = viewer
        return self._lines(account).get(user, ("", "-"))[1]

    def close(self):
        self.server.shutdown()


@pytest.fixture
def kasm():
    k = FakeKasm()
    yield k
    k.close()


def streaming(kasm, root):
    """A screen factory: each account's display streams on `kasm`, with real
    `DesktopLogins` written where `kasm` reads them."""

    class StreamingScreen(PictureScreen):
        desktop_kind = "kasmvnc"

        def __init__(self, account):
            super().__init__(account)
            self.logins = DesktopLogins(root / account / "kasmpasswd", os.getgid())
            self.logins.write(False)
            kasm.files[account] = self.logins.path
            self.drivers = []

        def desktop(self, viewer):
            return kasm.port, self.logins.authorization(viewer)

        def set_driver(self, person):
            self.drivers.append(person)
            self.logins.write(person)

    return StreamingScreen


@pytest.fixture
def station(tmp_path, kasm, no_chown):
    with running_workstation(tmp_path, screen_factory=streaming(kasm, tmp_path / "logins")) as ws:
        yield ws


# ── the logins ───────────────────────────────────────────────────────────────

def test_the_hash_is_glibcs_sha256_crypt():
    # The specification's own example (Drepper, "Unix crypt using SHA-256").
    assert sha256_crypt("Hello world!", "saltstring") == (
        "$5$saltstring$5B8vYYiY.CVt1RlTTf8KbXBH3hsxY/GNooZaBBGWEc5")
    assert sha256_crypt("x").startswith("$5$kasm$")


@pytest.mark.skipif(not shutil.which("openssl"), reason="no openssl here to compare with")
@pytest.mark.parametrize("length", [1, 7, 16, 31, 32, 33, 47, 64, 65, 100])
def test_the_hash_is_what_openssl_computes_for_kasmvncs_salt(length):
    secret = ("Pantheon-desktop-" * 8)[:length]
    done = subprocess.run(["openssl", "passwd", "-5", "-salt", "kasm", secret],
                          capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        pytest.skip(f"this openssl has no -5: {done.stderr.strip()}")
    assert sha256_crypt(secret) == done.stdout.strip()


def test_person_drives_only_while_they_hold_the_screen_and_watch_never_does(tmp_path):
    logins = DesktopLogins(tmp_path / "kasmpasswd", 1234)
    lines = lambda text: {l.split(":")[0]: l.split(":", 1)[1] for l in text.splitlines()}  # noqa: E731
    agent, person = lines(logins.text(False)), lines(logins.text(True))
    assert set(agent) == set(person) == {"person", "watch"}
    assert agent["person"].endswith(":r") and person["person"].endswith(":rw")
    assert agent["watch"].endswith(":r") and person["watch"].endswith(":r")
    # The secret in each viewer's header is the one its line was made from —
    # KasmVNC's own check — and no two displays share one.
    for viewer in P.DESKTOP_VIEWERS:
        user, _, secret = base64.b64decode(logins.authorization(viewer)[6:]).decode().partition(":")
        assert user == viewer and len(secret) >= 32
        assert sha256_crypt(secret) == person[viewer].rsplit(":", 1)[0]
    assert DesktopLogins(tmp_path / "other", 1234).authorization("person") != \
        logins.authorization("person")


def test_an_unknown_viewer_has_no_login(tmp_path):
    with pytest.raises(DaemonError) as e:
        DesktopLogins(tmp_path / "kasmpasswd", 1234).authorization("root")
    assert e.value.code == "bad_request"


def test_the_file_is_written_in_place_privately_and_never_through_a_link(tmp_path, monkeypatch):
    owners = []
    monkeypatch.setattr(os, "chown", lambda p, u, g, **k: owners.append((str(p), u, g)))
    monkeypatch.setattr(os, "fchown", lambda fd, u, g: owners.append(("fd", u, g)))
    path = tmp_path / "desktop" / "2001" / "kasmpasswd"
    logins = DesktopLogins(path, 2001)
    logins.write(False)
    inode = path.stat().st_ino
    logins.write(True)
    assert path.stat().st_ino == inode, "replaced, not rewritten: KasmVNC watches the file it opened"
    assert path.read_text() == logins.text(True)
    assert oct(path.stat().st_mode & 0o777) == "0o640"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o750"
    assert (str(path.parent), 0, 2001) in owners and ("fd", 0, 2001) in owners
    path.unlink()
    os.symlink(tmp_path / "elsewhere", path)
    with pytest.raises(OSError):
        logins.write(True)
    assert not (tmp_path / "elsewhere").exists()


# ── the display ──────────────────────────────────────────────────────────────

def test_kasmvnc_streams_on_loopback_behind_the_logins_and_nothing_else():
    argv = kasmvnc_argv("/usr/bin/Xkasmvnc", displayfd=9, auth=Path("/home/a/.Xauthority"),
                        port=41234, logins=Path("/run/pantheon-desktop/2001/kasmpasswd"))
    assert argv[0] == "/usr/bin/Xkasmvnc"
    assert argv[argv.index("-interface") + 1] == "127.0.0.1"
    assert argv[argv.index("-websocketPort") + 1] == "41234"
    assert argv[argv.index("-KasmPasswordFile") + 1] == "/run/pantheon-desktop/2001/kasmpasswd"
    assert argv[argv.index("-geometry") + 1] == f"{P.SCREEN_WIDTH}x{P.SCREEN_HEIGHT}"
    assert argv[argv.index("-nolisten") + 1] == "tcp"
    assert argv[argv.index("-displayfd") + 1] == "9"
    assert argv[argv.index("-publicIP") + 1] == "127.0.0.1", "it would ask Google's STUN servers"
    assert "-AcceptSetDesktopSize=0" in argv, "a viewer could resize the agent's screen"
    assert "-AlwaysShared" in argv
    lowered = [a.lower() for a in argv]
    for never in ("-httpd", "-disablebasicauth", "-sslonly", "-localhost", "-cert", "-key"):
        assert never not in lowered, never


class _Proc:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return None


class _System:
    def __init__(self, root):
        self.desktop_root = root

    def home(self, account):
        return self.desktop_root


def _display(tmp_path, monkeypatch, *, kasm_here=True, answers=(True,)):
    real = shutil.which
    monkeypatch.setattr(ubuntu.shutil, "which",
                        lambda name, *a, **k: ("/usr/bin/Xkasmvnc" if kasm_here else None)
                        if name == ubuntu.KASMVNC_SERVER else real(name, *a, **k))
    replies = list(answers)
    monkeypatch.setattr(ubuntu, "_answers", lambda port, timeout: replies.pop(0) if replies else False)
    stopped = []
    monkeypatch.setattr(ubuntu, "_stop", lambda proc, **k: stopped.append(proc) or "")
    display = XDisplay(_System(tmp_path), ANN)
    spawned = []

    def spawn(prefix, env, label, argv):
        spawned.append((label, argv(9)))
        return (_Proc(), 7 + len(spawned)), ""

    display._spawn = spawn
    return display, spawned, stopped


def test_the_display_is_kasmvnc_where_the_machine_has_it(tmp_path, monkeypatch, no_chown):
    display, spawned, _ = _display(tmp_path, monkeypatch)
    proc, number, desktop = display._start_server(["setpriv"], {}, tmp_path / ".Xauthority", 2001)
    assert [label for label, _ in spawned] == ["Xkasmvnc"] and number == 8
    port, logins = desktop
    argv = spawned[0][1]
    assert argv[argv.index("-websocketPort") + 1] == str(port)
    assert logins.path == tmp_path / "2001" / "kasmpasswd" and logins.path.is_file()
    assert "person:" in logins.path.read_text() and ":rw" not in logins.path.read_text()


def test_kasmvnc_that_will_not_answer_is_tried_twice_then_the_screen_is_pictures(
        tmp_path, monkeypatch, no_chown):
    display, spawned, stopped = _display(tmp_path, monkeypatch, answers=(False, False))
    proc, number, desktop = display._start_server([], {}, tmp_path / ".Xauthority", 2001)
    assert [label for label, _ in spawned] == ["Xkasmvnc", "Xkasmvnc", "Xvfb"]
    assert desktop is None and len(stopped) == 2
    ports = {argv[argv.index("-websocketPort") + 1] for _, argv in spawned[:2]}
    assert len(ports) == 2, "the second try used the port the first could not have"
    assert display.desktop_why.startswith("The live desktop did not start (nothing answered")
    assert spawned[2][1][0] == "Xvfb"


def test_a_machine_without_kasmvnc_shows_pictures_and_says_how_to_get_the_stream(
        tmp_path, monkeypatch):
    display, spawned, _ = _display(tmp_path, monkeypatch, kasm_here=False)
    _, _, desktop = display._start_server([], {}, tmp_path / ".Xauthority", 2001)
    assert [label for label, _ in spawned] == ["Xvfb"] and desktop is None
    assert "no KasmVNC" in display.desktop_why and "docker compose up -d --build" in display.desktop_why
    assert not (tmp_path / "2001").exists()


def test_who_drives_is_written_live_and_kept_for_the_next_start(tmp_path, monkeypatch, no_chown):
    display, spawned, _ = _display(tmp_path, monkeypatch, answers=(True, True))
    _, _, desktop = display._start_server([], {}, tmp_path / ".Xauthority", 2001)
    display._desktop = desktop
    display.set_driver(True)
    assert "person:" in desktop[1].path.read_text() and ":rw\n" in desktop[1].path.read_text()
    # A restart of the display (it died, or a reset) keeps the person driving.
    _, _, again = display._start_server([], {}, tmp_path / ".Xauthority", 2001)
    assert ":rw\n" in again[1].path.read_text()
    display._desktop = again
    display.set_driver(False)
    assert ":rw" not in again[1].path.read_text()


class _DyingProc:
    """An X server that has stopped, the way a crashing one is found."""
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


class _StartableSystem(_System):
    def run_as(self, account, *, with_display=True):
        return [], {"HOME": str(self.desktop_root)}

    def uid(self, account):
        return 2001

    def add_desktop_settings(self, account):
        return 0

    def retire_shipped_files(self, account):
        return 0


def test_a_live_desktop_that_keeps_stopping_is_given_up_for_pictures(tmp_path, monkeypatch, no_chown):
    """`B1721`. The owner, 2026-10-31: the desktop *"constantly opens and
    reopens firefox and the terminal"*. Every start of a display is a new
    session, so a server that dies a moment after starting is a desktop that
    keeps opening itself. Twice within a minute and KasmVNC is not started a
    third time: the display is Xvfb, says why, and the log says what the server
    said before it stopped."""
    display, spawned, _ = _display(tmp_path, monkeypatch, answers=(True, True, True))
    display.system = _StartableSystem(tmp_path)
    procs = []

    def spawn(prefix, env, label, argv):
        spawned.append((label, argv(9)))
        procs.append(_DyingProc())
        return (procs[-1], 7), ""

    display._spawn = spawn
    monkeypatch.setattr(ubuntu, "fs_identity", lambda uid, gid: __import__("contextlib").nullcontext())
    monkeypatch.setattr(ubuntu, "desktop_session", lambda: (["true"], {}))
    monkeypatch.setattr(ubuntu.subprocess, "Popen", lambda *a, **k: _DyingProc())
    monkeypatch.setattr(display, "_wait_for_wm", lambda *a, **k: 0.0)
    monkeypatch.setattr(display, "_open_watch", lambda: None)
    warnings = []
    monkeypatch.setattr(ubuntu.logger, "warning", lambda msg, *a: warnings.append(msg % a))

    display.start()
    for _ in range(2):
        display._server_tail.append("Fatal server error: something KasmVNC said")
        procs[-1].returncode = 1          # it stopped a moment after starting
        display.start()
    assert [label for label, _ in spawned] == ["Xkasmvnc", "Xkasmvnc", "Xvfb"]
    assert display.desktop_kind is None
    assert display.desktop_why.startswith("The live desktop stopped 2 times within a minute")
    assert "something KasmVNC said" in display.desktop_why
    assert any("had stopped (exit 1)" in w and "It last said: Fatal server error" in w
               for w in warnings), warnings


def test_a_live_desktop_that_ran_a_while_is_simply_started_again(tmp_path, monkeypatch, no_chown):
    display, spawned, _ = _display(tmp_path, monkeypatch, answers=(True,) * 4)
    display.system = _StartableSystem(tmp_path)
    procs = []

    def spawn(prefix, env, label, argv):
        spawned.append((label, argv(9)))
        procs.append(_DyingProc())
        return (procs[-1], 7), ""

    display._spawn = spawn
    monkeypatch.setattr(ubuntu, "fs_identity", lambda uid, gid: __import__("contextlib").nullcontext())
    monkeypatch.setattr(ubuntu, "desktop_session", lambda: (["true"], {}))
    monkeypatch.setattr(ubuntu.subprocess, "Popen", lambda *a, **k: _DyingProc())
    monkeypatch.setattr(display, "_wait_for_wm", lambda *a, **k: 0.0)
    monkeypatch.setattr(display, "_open_watch", lambda: None)
    display.start()
    for _ in range(3):
        display._started_at -= ubuntu._QUICK_DEATH_S + 1   # it ran for over a minute
        procs[-1].returncode = -9
        display.start()
    assert [label for label, _ in spawned] == ["Xkasmvnc"] * 4


def test_a_display_without_a_stream_says_why_when_asked_for_it(tmp_path, monkeypatch):
    display, _, _ = _display(tmp_path, monkeypatch, kasm_here=False)
    monkeypatch.setattr(display, "start", lambda: ":8")
    monkeypatch.setattr(display, "running", lambda: True)
    display._desktop_why = "This workstation has no KasmVNC, so its screen is shown as pictures."
    with pytest.raises(DaemonError) as e:
        display.desktop("person")
    assert e.value.code == "unavailable" and "no KasmVNC" in e.value.message
    assert display.desktop_kind is None


# ── the daemon's stream ──────────────────────────────────────────────────────

def test_the_daemon_says_whether_a_screen_streams(station):
    client = WorkstationClient(station.url, station.token)
    assert run(client.desktop(ANN)) == {"kind": "kasmvnc", "holder": "agent"}


def test_a_screen_without_a_stream_says_why(tmp_path):
    with running_workstation(tmp_path) as ws:
        answer = run(WorkstationClient(ws.url, ws.token).desktop(ANN))
    assert answer["kind"] is None and answer["holder"] == "agent"
    assert answer["why"] == "This screen has no live desktop; it is shown as pictures."


def test_take_over_and_hand_back_change_what_the_open_stream_may_do(station, kasm):
    client = WorkstationClient(station.url, station.token)

    async def go():
        async with client.desktop_stream(ANN, "person") as ws:
            await ws.send(b"hello")
            echo = await ws.recv()
            await ws.send(b"who")
            watching = await ws.recv()
            await client.control(ANN, "person")
            await ws.send(b"who")
            holding = await ws.recv()
            async with client.desktop_stream(ANN, "watch") as watcher:
                await watcher.send(b"who")
                watched = await watcher.recv()
            await client.control(ANN, "agent")
            await ws.send(b"who")
            return echo, watching, holding, watched, await ws.recv()

    assert run(go()) == (b"echo:hello", b"person:r", b"person:rw", b"watch:r", b"person:r")


def test_the_display_hears_the_daemons_login_and_nothing_of_the_callers(station, kasm):
    client = WorkstationClient(station.url, station.token)

    async def go():
        async with client.desktop_stream(ANN, "person") as ws:
            await ws.send(b"who")
            return await ws.recv()

    assert run(go()) == b"person:r"
    seen = kasm.seen[-1]
    assert seen["Host"] == f"127.0.0.1:{kasm.port}"
    assert seen["Origin"] == f"http://127.0.0.1:{kasm.port}"
    assert seen["Sec-WebSocket-Protocol"] == "binary" and seen["Sec-WebSocket-Version"] == "13"
    assert seen["Authorization"].startswith("Basic ")
    assert set(seen) == {"Host", "Origin", "Upgrade", "Connection", "Sec-WebSocket-Version",
                         "Sec-WebSocket-Key", "Sec-WebSocket-Protocol", "Authorization"}
    assert all(station.token not in v for v in seen.values()), "Pantheon's token reached the display"


def test_a_reset_gives_the_live_screen_back_to_the_agent(station):
    client = WorkstationClient(station.url, station.token)
    run(client.control(ANN, "person"))
    screen = station.screen(ANN)
    assert screen.drivers[-1] is True
    run(client.reset(ANN))
    assert screen.drivers[-1] is False, "the display was reset still driven by the person"
    assert ":rw" not in screen.logins.path.read_text()


def _upgrade(url, path, headers):
    """A raw upgrade request to the daemon: `(status, json body or None)`."""
    parts = urlsplit(url)
    with socket.create_connection((parts.hostname, parts.port), timeout=10) as s:
        lines = [f"GET {path} HTTP/1.1", f"Host: {parts.hostname}:{parts.port}",
                 "Upgrade: websocket", "Connection: Upgrade",
                 *(f"{k}: {v}" for k, v in headers.items())]
        s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        status, head, rest = agentd.read_head(s)
        length = int(re.search(rb"Content-Length: (\d+)", head).group(1))
        while len(rest) < length:
            rest += s.recv(4096)
    assert head.startswith(b"HTTP/1.1 "), "a websocket client reads only an HTTP/1.1 answer"
    import json
    return status, json.loads(rest) if rest else None


_KEY = base64.b64encode(b"0123456789abcdef").decode()
_GOOD = {"Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": _KEY,
         "Sec-WebSocket-Protocol": "binary"}


@pytest.mark.parametrize("change,status,code", [
    ({"Sec-WebSocket-Protocol": "chat"}, 400, "bad_request"),
    ({"Sec-WebSocket-Version": "8"}, 400, "bad_request"),
    ({"Sec-WebSocket-Key": "not-a-key"}, 400, "bad_request"),
    ({"Authorization": "Bearer pws_wrong"}, 401, "unauthorized"),
])
def test_a_malformed_or_unauthorised_upgrade_is_refused_before_anything_is_joined(
        station, kasm, change, status, code):
    _, path = P.route_path("desktop", ANN)
    headers = {"Authorization": f"Bearer {station.token}", **_GOOD, **change}
    before = len(kasm.seen)
    got, body = _upgrade(station.url, path + "?viewer=person", headers)
    assert (got, body["error"]) == (status, code)
    assert len(kasm.seen) == before, "the display was asked before the request was checked"


def test_an_unknown_viewer_is_refused(station):
    _, path = P.route_path("desktop", ANN)
    got, body = _upgrade(station.url, path + "?viewer=root",
                         {"Authorization": f"Bearer {station.token}", **_GOOD})
    assert got == 400 and "viewer" in body["message"]


def test_the_upgrade_the_daemon_writes_is_exactly_what_kasmvnc_parses():
    request = agentd.desktop_request("/websockify", 41234, _KEY, "Basic eDp5").decode()
    head, _, tail = request.partition("\r\n")
    assert head == "GET /websockify HTTP/1.1" and request.endswith("\r\n\r\n")
    fields = dict(line.split(": ", 1) for line in tail.strip().split("\r\n"))
    assert fields == {"Host": "127.0.0.1:41234", "Origin": "http://127.0.0.1:41234",
                      "Upgrade": "websocket", "Connection": "Upgrade",
                      "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": _KEY,
                      "Sec-WebSocket-Protocol": "binary", "Authorization": "Basic eDp5"}
    assert len(request) >= 92, "KasmVNC refuses a handshake shorter than this"
    with pytest.raises(DaemonError):
        agentd.desktop_request("/websockify", 41234, "x\r\nInjected: yes", "Basic eDp5")


def test_an_answer_is_read_to_its_blank_line_and_the_rest_is_the_stream():
    a, b = socket.socketpair()
    with a, b:
        b.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\nRFB 003.008\n")
        status, head, rest = agentd.read_head(a)
    assert status == 101 and head.endswith(b"\r\n\r\n") and rest == b"RFB 003.008\n"
    for wire, words in [(b"x" * 20000, "too much"), (b"", "closed"),
                        (b"NOT HTTP\r\n\r\n", "not HTTP")]:
        a, b = socket.socketpair()
        with a, b:
            b.sendall(wire)
            b.shutdown(socket.SHUT_WR)
            with pytest.raises(DaemonError) as e:
                agentd.read_head(a, limit=16_384)
        assert words in e.value.message


def test_the_splice_carries_bytes_both_ways_until_one_side_ends():
    a1, a2 = socket.socketpair()
    b1, b2 = socket.socketpair()
    worker = threading.Thread(target=agentd.splice, args=(a2, b1), daemon=True)
    worker.start()
    a1.sendall(b"to the display")
    assert b2.recv(100) == b"to the display"
    b2.sendall(b"to the viewer" * 1000)
    got = b""
    while len(got) < 13000:
        got += a1.recv(65536)
    assert got == b"to the viewer" * 1000
    a1.close()
    worker.join(timeout=5)
    assert not worker.is_alive()
    for s in (a2, b1, b2):
        s.close()


# ── the VM host ──────────────────────────────────────────────────────────────

def test_the_vm_host_carries_the_stream_from_the_persons_machine(tmp_path, kasm, no_chown):
    factory = streaming(kasm, tmp_path / "logins")

    class StreamingMachine(InProcessMachine):
        def start(self):
            super().start()
            self.system._screen_factory = factory

    with vm_host(tmp_path / "vm", factory=StreamingMachine) as (fleet, url):
        client = WorkstationClient(url, HOST_TOKEN)
        assert run(client.desktop(ANN)) == {"kind": "kasmvnc", "holder": "agent"}

        async def go():
            async with client.desktop_stream(ANN, "person") as ws:
                await ws.send(b"who")
                first = await ws.recv()
                busy = fleet._use[ANN][0]
                await client.control(ANN, "person")
                await ws.send(b"who")
                return first, busy, await ws.recv()

        first, busy, holding = run(go())
        assert (first, holding) == (b"person:r", b"person:rw")
        assert busy >= 1, "a machine someone is watching could be powered off as idle"
        assert fleet._use[ANN][0] == 0
        # The machine's daemon wrote the upgrade KasmVNC saw: the machine's own
        # login, never the host's token.
        assert all(HOST_TOKEN not in v for v in kasm.seen[-1].values())


# ── Pantheon's relay ─────────────────────────────────────────────────────────

from test_the_workstation_is_admin_controlled import (  # noqa: E402,F401
    ADMIN, ALLOWED, PLAIN, app, as_user, auth, datadir, switch_on)


@pytest.fixture
def client_dir(tmp_path, monkeypatch):
    """An unpacked client, as the image has one: a page with one inline block
    (KasmVNC's own has one) and an asset."""
    from src import desktop_client
    www = tmp_path / "kasmvnc" / "www"
    (www / "assets").mkdir(parents=True)
    (www / "vnc.html").write_text("<!doctype html><script>window.x = 1;</script>"
                                  "<script type=module src=assets/ui-AbC.js></script>")
    (www / "assets" / "ui-AbC.js").write_text("export const ui = 1;\n")
    monkeypatch.setenv(desktop_client.DIR_ENV, str(www))
    return www


@pytest.fixture
def live(app, station, client_dir):
    switch_on(app, station)
    return app


ORIGIN = {"origin": "http://testserver"}
STREAM = "/api/workstation/desktop/websockify"


def _connect(client, path, headers=ORIGIN, **kw):
    """A copy of `headers` each time: Starlette's test client writes the
    upgrade's own headers into the dict it is handed."""
    return client.websocket_connect(path, headers=dict(headers), **kw)


def test_pantheon_offers_its_own_client_for_a_screen_that_streams(live):
    r = as_user(live, ALLOWED).get("/api/workstation/desktop")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "kasmvnc" and body["holder"] == "agent" and body["watching"] is False
    assert body["client"].startswith("/api/workstation/desktop/client/vnc.html?")
    q = parse_qs(urlsplit(body["client"]).query)
    assert q["path"] == ["api/workstation/desktop/websockify"]
    assert q["view_only"] == ["false"] and q["autoconnect"] == ["true"]
    assert q["clipboard_up"] == q["clipboard_down"] == ["true"]
    assert q["enable_webrtc"] == ["false"] and q["resize"] == ["scale"]
    assert "why" not in body and r.headers["cache-control"].startswith("no-store")


def test_an_admin_watching_is_offered_a_view_only_client_with_no_clipboard(live):
    r = as_user(live, ADMIN).get(f"/api/workstation/desktop?person={ALLOWED}")
    q = parse_qs(urlsplit(r.json()["client"]).query)
    assert r.json()["watching"] is True
    assert q["path"] == [f"api/workstation/desktop/websockify?person={ALLOWED}"]
    assert q["view_only"] == ["true"]
    assert q["clipboard_up"] == q["clipboard_down"] == ["false"]


def test_without_the_client_the_screen_is_pictures_and_says_so(app, station, monkeypatch, tmp_path):
    from src import desktop_client
    monkeypatch.setenv(desktop_client.DIR_ENV, str(tmp_path / "nothing-here"))
    switch_on(app, station)
    body = as_user(app, ALLOWED).get("/api/workstation/desktop").json()
    assert body["kind"] is None and "client" not in body
    assert body["why"] == desktop_client.UNAVAILABLE_SENTENCE


def test_nobody_else_may_ask_about_another_persons_desktop(live):
    assert as_user(live, PLAIN).get("/api/workstation/desktop").status_code == 403
    assert as_user(live, ALLOWED).get(f"/api/workstation/desktop?person={ADMIN}").status_code == 403


def test_the_stream_relays_the_persons_own_desktop_and_take_over_changes_it(live):
    c = as_user(live, ALLOWED)
    with _connect(c, STREAM, subprotocols=["binary"]) as ws:
        assert ws.accepted_subprotocol == "binary"
        ws.send_bytes(b"hello")
        assert ws.receive_bytes() == b"echo:hello"
        ws.send_bytes(b"who")
        assert ws.receive_bytes() == b"person:r"
        assert c.post("/api/workstation/control", json={"holder": "person"}).status_code == 200
        ws.send_bytes(b"who")
        assert ws.receive_bytes() == b"person:rw"
        assert c.post("/api/workstation/control", json={"holder": "agent"}).status_code == 200
        ws.send_bytes(b"who")
        assert ws.receive_bytes() == b"person:r"


def test_an_admin_watches_another_persons_desktop_and_never_drives_it(live):
    owner = as_user(live, ALLOWED)
    assert owner.post("/api/workstation/control", json={"holder": "person"}).status_code == 200
    try:
        with _connect(as_user(live, ADMIN), f"{STREAM}?person={ALLOWED}",
                      subprotocols=["binary"]) as ws:
            ws.send_bytes(b"who")
            assert ws.receive_bytes() == b"watch:r"
    finally:
        owner.post("/api/workstation/control", json={"holder": "agent"})


@pytest.mark.parametrize("who,path,headers,code", [
    (None, STREAM, ORIGIN, 4401),                                      # nobody signed in
    (ALLOWED, STREAM, {"origin": "https://elsewhere.example"}, 4401),  # another site's page
    (ALLOWED, STREAM, {}, 4401),                                        # no page at all
    (ALLOWED, STREAM, {**ORIGIN, "authorization": "Bearer pnth_x"}, 4401),  # a token is not a person
    (PLAIN, STREAM, ORIGIN, 4403),                                      # no workstation privilege
    (ALLOWED, f"{STREAM}?person={ADMIN}", ORIGIN, 4403),                # only an admin watches
])
def test_the_stream_is_refused_to_anyone_but_the_person_from_pantheons_pages(
        live, who, path, headers, code):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with _connect(as_user(live, who), path, headers, subprotocols=["binary"]):
            pass
    assert e.value.code == code


def test_a_stream_that_does_not_speak_the_clients_subprotocol_is_refused(live):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with _connect(as_user(live, ALLOWED), STREAM):
            pass
    assert e.value.code == 1002


def test_a_workstation_that_cannot_stream_closes_the_stream_with_its_sentence(
        app, tmp_path, client_dir):
    from starlette.websockets import WebSocketDisconnect
    with running_workstation(tmp_path) as ws_plain:   # pictures only
        switch_on(app, ws_plain)
        with pytest.raises(WebSocketDisconnect) as e:
            with _connect(as_user(app, ALLOWED), STREAM, subprotocols=["binary"]) as ws:
                ws.receive_bytes()
    assert e.value.code == 1011
    assert "no live desktop" in (e.value.reason or "")


# ── the client Pantheon serves ───────────────────────────────────────────────

def _client_app():
    from fastapi import FastAPI
    from core.middleware import SecurityHeadersMiddleware
    from src.desktop_client import PREFIX, DesktopClientFiles
    application = FastAPI()
    application.add_middleware(SecurityHeadersMiddleware)
    application.mount(PREFIX, DesktopClientFiles(), name="desktop-client")
    return application


def test_the_client_is_served_from_pantheons_copy_under_its_own_policy(client_dir):
    import hashlib
    from fastapi.testclient import TestClient
    c = TestClient(_client_app())
    page = c.get("/api/workstation/desktop/client/vnc.html")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
    csp = page.headers["content-security-policy"]
    digest = base64.b64encode(hashlib.sha256(b"window.x = 1;").digest()).decode()
    script_src = next(d for d in csp.split("; ") if d.startswith("script-src "))
    assert f"'sha256-{digest}'" in script_src and "'wasm-unsafe-eval'" in script_src
    assert "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src
    assert "frame-ancestors 'self'" in csp and "connect-src 'self'" in csp
    assert "frame-src 'none'" in csp and "base-uri 'none'" in csp
    assert page.headers["x-frame-options"] == "SAMEORIGIN"
    asset = c.get("/api/workstation/desktop/client/assets/ui-AbC.js")
    assert asset.status_code == 200 and asset.headers["cache-control"] == "private, max-age=86400"
    assert c.get("/api/workstation/desktop/client/../../../etc/passwd").status_code == 404
    assert c.post("/api/workstation/desktop/client/vnc.html").status_code == 405


def test_an_install_without_the_client_answers_with_a_sentence(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from src import desktop_client
    monkeypatch.setenv(desktop_client.DIR_ENV, str(tmp_path / "none"))
    r = TestClient(_client_app()).get("/api/workstation/desktop/client/vnc.html")
    assert r.status_code == 404 and r.text == desktop_client.UNAVAILABLE_SENTENCE
    assert desktop_client.available() is False


def test_the_app_serves_the_client_behind_the_session():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'app.mount(_DESKTOP_CLIENT_PREFIX, DesktopClientFiles(), name="desktop-client")' in source
    from src.desktop_client import PREFIX
    assert PREFIX.startswith("/api/"), "outside /api/ the session would not gate it"


# ── where it comes from ──────────────────────────────────────────────────────

def test_kasmvnc_is_pinned_by_version_and_checksum_and_unpacked_without_running():
    script = (ROOT / "workstation" / "provision.sh").read_text(encoding="utf-8")
    assert re.search(r"^KASMVNC_VERSION=\d+\.\d+\.\d+$", script, re.M)
    for arch in ("AMD64", "ARM64"):
        assert re.search(rf"^KASMVNC_SHA256_{arch}=[0-9a-f]{{64}}$", script, re.M), arch
    assert "KASMVNC_URL=https://github.com/kasmtech/KasmVNC/releases/download" in script
    assert "sha256sum -c" in script and "refusing it" in script
    client = script[script.index("client() {"):]
    client = client[:client.index("\n}\n")]
    assert "dpkg-deb -x" in client and "dpkg -i" not in client and "apt-get" not in client
    assert "LICENSES" in client


def test_pantheons_image_unpacks_the_client_in_a_stage_of_its_own():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    stage = dockerfile[dockerfile.index("AS desktop-client"):]
    stage = stage[:stage.index("\nFROM ")]
    assert "provision.sh client /out" in stage
    assert "COPY docker/kasmvnc-client/ /out/LICENSES/" in stage
    final = dockerfile[dockerfile.rindex("\nFROM "):]
    assert "COPY --from=desktop-client /out/ /opt/pantheon/kasmvnc/" in final
    assert "ENV PANTHEON_DESKTOP_CLIENT_DIR=/opt/pantheon/kasmvnc/www" in final
    for name in ("noVNC-LICENSE.txt", "LICENSE.MPL-2.0.txt", "LICENSE.OFL-1.1.txt"):
        assert (ROOT / "docker" / "kasmvnc-client" / name).is_file(), name


def test_uvicorn_has_a_websocket_library_to_serve_the_stream_with():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^websockets==\d+\.\d+(\.\d+)?$", requirements, re.M)


def test_the_decision_is_on_the_record_and_the_old_one_says_it_was_replaced():
    decisions = (ROOT / ".pantheon" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "D-2026-10-31-01" in decisions
    old = decisions[decisions.index("D-2026-09-30-03"):]
    old = old[:old.index("\n## ", 10) if "\n## " in old[10:] else len(old)]
    assert "D-2026-10-31-01" in old, "the screenshot-stream decision does not say what replaced it"
