# SPDX-License-Identifier: AGPL-3.0-or-later
"""A phone that fails says so in the android-vm log.

The owner, 2026-11-18: *"The logs are squeaky clean"*, while one phone never
finished booting and another showed its picture and took no input. For those
three hours the service's log held, beside its request lines and the two it
starts with, four lines of its own: three times "did not finish booting", and
one viewer stream ended by a pointer at the edge. Thirteen button presses were
answered 503 with no reason beside them, and nothing said that the phone had
stopped being reachable, or when. What is pinned:

  * a phone whose control listener stops being provably this VM's says why,
    once, and says when it is back; the refusal itself carries the reason;
  * a port that is not open yet while Android boots is not that;
  * a start, Android's first answer, "on" and a stop are in the log;
  * a boot that times out says whether the emulator saw Android finish
    booting, and the emulator's last line;
  * an emulator that dies under a running phone is in the log;
  * a picture that stays frozen is named once, and so is its return;
  * a tap or key that does not reach Android is named, once per reason;
  * a broken control connection is this phone's error, not a silent end;
  * a pointer at or past the edge is the edge, not the end of the stream;
  * a request refused for a fault on this host, and a stream that ends, are
    in the log with their reason;
  * a request that dies on an OS error is answered, and in the log;
  * a fold whose console fails is this phone's error, with its reason;
  * an image install, and a start after it that fails, are in the log.
"""
from __future__ import annotations

import base64
import http.client
import json
import logging
import os
import re
import socket
import struct
import threading
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest
from PIL import Image

from tests.test_a_google_play_phone_starts_on_a_user_build import _phone as timed_phone
from tests.test_a_phone_stays_its_vms_own_when_the_clock_steps import PORT, start_phone
from tests.test_a_phone_stream_survives_boot import Stream, greeting, jpeg_sizes, request
from tests.test_android_shows_its_own_boot_screen import Guest, _phone as booting_phone
from workstation import phone as PH
from workstation.native_android import host as H
from workstation.native_android import rfb
from workstation.native_android.adb import AdbError

ACCOUNT = "pw-ada-12345678"
needs_nofollow = pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"),
                                    reason="the emulator's log is read without following a link, or not at all")


def said(caplog, words):
    return [record for record in caplog.records if words in record.getMessage()]


# -- the control listener ------------------------------------------------------

def test_a_phone_that_stops_being_its_vms_own_says_why_once_and_when_it_is_back(tmp_path, monkeypatch, caplog):
    phone, kernel = start_phone(tmp_path, monkeypatch)
    assert phone._owned()
    with caplog.at_level(logging.INFO, logger=H.__name__):
        kernel.rows[4242]["listening"] = ()
        for _ in range(3):  # every frame and every button asks
            assert not phone._owned()
        with pytest.raises(AdbError) as refused:
            phone.direct._owned()
        kernel.rows[4242]["listening"] = (PORT, PORT + 1)
        assert phone._owned()
    reason = f"its emulator is not listening on port {PORT + 1}"
    assert str(refused.value) == f"The Android control listener no longer belongs to this VM: {reason}."
    lost = said(caplog, "no longer provably this VM's")
    assert len(lost) == 1 and lost[0].levelno == logging.WARNING
    assert reason in lost[0].getMessage() and "owned" in lost[0].getMessage()
    assert len(said(caplog, "this VM's own again")) == 1


def test_a_port_that_is_not_open_yet_is_the_wait_for_android_not_a_loss(tmp_path, monkeypatch, caplog):
    phone, kernel = start_phone(tmp_path, monkeypatch)
    kernel.rows[4242]["listening"] = ()  # the emulator has not opened its ADB port yet
    with caplog.at_level(logging.INFO, logger=H.__name__):
        assert not phone._owned() and not phone._owned()
        assert phone.unowned == f"its emulator is not listening on port {PORT + 1}"
        kernel.rows[4242]["listening"] = (PORT, PORT + 1)
        assert phone._owned() and phone.unowned is None
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert not said(caplog, "own again")


def _a_stranger_on_its_pid(phone, kernel):
    """Its pid went to another process while Popen still calls its child running."""
    kernel.exit(4242)
    kernel.spawn(4242, listening=(PORT, PORT + 1))
    phone.emulator.poll = lambda: None


@pytest.mark.parametrize("breaks, reason", [
    pytest.param(lambda phone, kernel: kernel.exit(4242), "its emulator process has exited", id="exited"),
    pytest.param(_a_stranger_on_its_pid, "its emulator (pid 4242) is not among the processes this VM started",
                 id="pid-reused"),
    pytest.param(lambda phone, kernel: kernel.rows[4242].update(exe="/usr/bin/something-else"),
                 "none of its processes runs this host's SDK emulator", id="another-binary"),
    pytest.param(lambda phone, kernel: kernel.rows[4242].update(listening=()),
                 f"its emulator is not listening on port {PORT + 1}", id="not-listening"),
])
def test_the_refusal_names_which_proof_failed(tmp_path, monkeypatch, breaks, reason):
    phone, kernel = start_phone(tmp_path, monkeypatch)
    assert phone._owned()
    breaks(phone, kernel)
    with pytest.raises(AdbError) as refused:
        phone.direct._owned()
    assert str(refused.value) == f"The Android control listener no longer belongs to this VM: {reason}."
    with pytest.raises(AdbError, match=re.escape(f"console no longer belongs to this VM: {reason}.")):
        phone.console(["rotate"], 5)


# -- a phone's life --------------------------------------------------------------

def test_a_start_and_a_stop_are_in_the_log(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger=H.__name__):
        phone, _ = start_phone(tmp_path, monkeypatch)
        started = said(caplog, "emulator started")
        assert phone._owned()
        monkeypatch.setattr(phone, "_release", lambda: None)
        phone.direct = None
        phone._stop_locked()
        assert not phone._owned()  # as the boot thread may still ask while the phone is stopped
    assert len(started) == 1
    assert not said(caplog, "no longer provably"), "a listener that goes with a stop is not a lost one"
    assert f"for owned: emulator started (pid 4242, console port {PORT}, ADB port {PORT + 1}," in started[0].getMessage()
    assert len(said(caplog, "Android phone for owned: emulator stopped.")) == 1


def test_a_boot_says_when_android_first_answered_and_when_it_was_on(tmp_path, monkeypatch, caplog):
    phone, proc, _ = booting_phone(tmp_path, monkeypatch, Guest(["kernel", "display", "done"]))
    with caplog.at_level(logging.INFO, logger=H.__name__):
        phone._boot(proc)
    assert phone.state == "on"
    lines = [record.getMessage() for record in caplog.records]
    answered = next(i for i, line in enumerate(lines) if "Android answered after" in line and "display is streaming" in line)
    on = next(i for i, line in enumerate(lines) if "for owned is on after" in line and "controls attached" in line)
    assert answered < on


class Unreachable:
    """`DirectAdb.shell` when nothing this VM may talk to answers on the phone's port."""

    def shell(self, args, **kw):
        raise AdbError("Android control connection failed (ConnectionRefusedError).")


@needs_nofollow
@pytest.mark.parametrize("guest, emulator_log, why", [
    pytest.param(Unreachable(), "INFO | Boot completed in 23456 ms\nINFO | Increasing screen off timeout\n",
                 "Android finished booting (its emulator says so), but Pantheon never reached Android: "
                 "Android control connection failed (ConnectionRefusedError). Start it again to retry.",
                 id="android-booted-unreached"),
    pytest.param(Unreachable(),
                 "INFO | Storing crashdata in: /tmp/android-unknown\nWARNING | Waiting for the\x1b[0m guest\n",
                 "Pantheon never reached Android: Android control connection failed (ConnectionRefusedError) "
                 "(its emulator last said: WARNING | Waiting for the [0m guest). Start it again to retry.",
                 id="android-not-booted-unreached"),
    pytest.param(Guest(["kernel"]),
                 "INFO | Storing crashdata in: /tmp/android-unknown\nERROR | No bootable device\n",
                 "Android did not finish booting (its emulator last said: ERROR | No bootable device). "
                 "Start it again to retry.", id="android-answers-never-boots"),
])
def test_a_boot_that_times_out_says_what_the_emulator_itself_saw(tmp_path, monkeypatch, caplog, guest, emulator_log, why):
    phone, proc, _ = timed_phone(monkeypatch, tmp_path, guest)
    (tmp_path / ".android").mkdir()
    (tmp_path / PH.LOG_FILE).write_text(emulator_log)
    with caplog.at_level(logging.WARNING, logger=H.__name__):
        phone._boot(proc)
    assert phone.state == "unavailable"
    assert phone.why == why
    assert len(said(caplog, "did not start: " + why)) == 1


@needs_nofollow
def test_an_emulator_that_dies_under_a_running_phone_is_in_the_log(tmp_path, monkeypatch, caplog):
    system = SimpleNamespace(config={}, sdk=tmp_path / "sdk", abi="x86_64", why=None, home=lambda _: tmp_path)
    phone = H.NativePhone(system, "owned", None)
    (tmp_path / ".android").mkdir()
    (tmp_path / PH.LOG_FILE).write_text("INFO | boot completed\nERROR | qemu-system-x86_64-headless: hardware error\n")
    phone.state, phone.emulator = "on", SimpleNamespace(pid=4242, poll=lambda: 134)
    monkeypatch.setattr(phone, "_stop_locked", lambda: setattr(phone, "emulator", None))
    with caplog.at_level(logging.WARNING, logger=H.__name__):
        phone.ensure_shown()
    assert phone.state == "unavailable" and "Turn it on again" in phone.why
    assert len(said(caplog, "for owned: its emulator exited (status 134) while Android was on (its emulator last "
                            "said: ERROR | qemu-system-x86_64-headless: hardware error).")) == 1


# -- the picture and the input ---------------------------------------------------

def test_a_picture_that_stays_frozen_is_named_once_and_so_is_its_return(monkeypatch, caplog):
    from workstation.native_android import screen as S
    phone = SimpleNamespace(lock=threading.RLock(), generation="g", control=None, state="on", account="owned",
                            device="pixel_9", posture=None, rotation=0, direct=object(),
                            _active=lambda: None, touch=lambda: None, stream_ready=lambda: True)
    screen, now, works = S.Screen(phone), [100.0], [True]
    monkeypatch.setattr(S, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=lambda seconds: None))

    def capture(_):
        if works[0]:
            return Image.new("RGB", (360, 780), (9, 9, 9))
        raise AdbError("The Android control listener no longer belongs to this VM: "
                       "its emulator is not listening on port 5587.")
    monkeypatch.setattr(S, "raw_capture", capture)

    def frames(seconds):
        for _ in range(seconds):
            now[0] += 1
            assert screen.frame()[0].size == (360, 780)
    with caplog.at_level(logging.INFO, logger=S.__name__):
        frames(1)
        works[0] = False
        frames(3)  # as while SurfaceFlinger hands over during boot: the last picture, and no word
        works[0] = True
        frames(1)
        assert not caplog.records
        works[0] = False
        frames(12)
        frozen = said(caplog, "the picture shown is frozen")
        assert len(frozen) == 1 and frozen[0].levelno == logging.WARNING
        assert "for owned" in frozen[0].getMessage() and "not listening on port 5587" in frozen[0].getMessage()
        works[0] = True
        frames(2)
    assert len(said(caplog, "its screen is captured again after 12 s")) == 1


def test_a_tap_that_does_not_reach_android_is_named_once_per_reason(caplog):
    from workstation.native_android import screen as S
    sent, failure = [], [AdbError("Android's control connection failed (BrokenPipeError).")]

    def touch(action, x, y, width, height):
        if failure[0] is not None:
            raise failure[0]
        sent.append((action, x, y))
    phone = SimpleNamespace(lock=threading.RLock(), generation="g", state="on", account="owned",
                            control=SimpleNamespace(touch=touch), _on=lambda: None, touch=lambda: None)
    screen = S.Screen(phone)
    screen.size = screen.physical = (100, 200)
    down = {"kind": "pointer", "buttons": 1, "x": 3, "y": 4, "scroll_x": 0, "scroll_y": 0,
            "geometry": ("g", (100, 200), (100, 200))}
    with caplog.at_level(logging.WARNING, logger=S.__name__):
        for _ in range(3):
            with pytest.raises(PH.PhoneError, match="BrokenPipeError"):
                screen.rfb_event(down, "viewer", lambda: "person")
        named = said(caplog, "a tap or key did not reach Android")
        assert len(named) == 1 and "for owned" in named[0].getMessage() and "BrokenPipeError" in named[0].getMessage()
        failure[0] = None
        screen.rfb_event(down, "viewer", lambda: "person")
        failure[0] = AdbError("Android's control connection failed (BrokenPipeError).")
        with pytest.raises(PH.PhoneError):
            screen.rfb_event(down, "viewer", lambda: "person")
    assert sent == [(0, 3, 4)]
    assert len(said(caplog, "a tap or key did not reach Android")) == 2, "said again once it had worked in between"


def test_a_broken_control_connection_is_this_phones_error_not_a_silent_end():
    from workstation.native_android.control import ScrcpyControl
    control = ScrcpyControl(None, "unused.jar")

    def broken(data):
        raise BrokenPipeError(32, "Broken pipe")
    control.channel = SimpleNamespace(wire=SimpleNamespace(deadline=0), write=broken, pending=bytearray(), closed=False)
    # An OSError here ended the viewer's stream with nothing in the log, and
    # an agent's tap with no answer at all.
    with pytest.raises(AdbError, match=r"control connection failed \(BrokenPipeError\)"):
        control.touch(0, 1, 1, 10, 10)

    def closed(data):
        control.channel.closed = True
        raise AdbError("Android closed its file-transfer stream.")
    control.channel.write = closed
    with pytest.raises(AdbError, match="control server closed its connection"):
        control.key(4)


def test_a_pointer_at_or_past_the_edge_is_the_edge_not_the_end_of_the_stream():
    image = Image.new("RGB", (320, 640))

    def pointer(buttons, x, y):
        return b"\5" + struct.pack(">HHHhh", buttons, x, y, 0, 0)
    stream = Stream(greeting(7, -224, -308) + request(320, 640) + pointer(1, 320, 640) + pointer(0, 65535, 3)
                    + request(320, 640))
    events = []
    with pytest.raises(rfb.StreamEnded):  # the script runs out; no pointer ended it
        rfb.serve(stream, lambda: (image, "one"), events.append, lambda: None, frame_interval=0)
    assert [(event["buttons"], event["x"], event["y"]) for event in events] == [(1, 319, 639), (0, 319, 3)]
    assert len(jpeg_sizes(bytes(stream.output))) == 2, "the stream went on after them"
    with pytest.raises(rfb.ProtocolError, match="buttons"):
        rfb.serve(Stream(greeting(7, -224, -308) + pointer(0x200, 1, 1)), lambda: (image, "one"),
                  events.append, lambda: None, frame_interval=0)


# -- the worker ------------------------------------------------------------------

def _viewer(port, token, viewer="person"):
    """Ask for the phone's screen as the pinned viewer does: the socket, and the status it got."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f"GET /v1/users/{ACCOUNT}/phone/screen?viewer={viewer} HTTP/1.1\r\nHost: android-vm\r\n"
                  f"Authorization: Bearer {token}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: binary\r\n"
                  f"Sec-WebSocket-Key: {key}\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        block = sock.recv(4096)
        if not block:
            break
        head += block
    return sock, int(head.split()[1])


def _masked(payload):
    mask = os.urandom(4)
    return bytes((0x82, 0x80 | len(payload))) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def _until_closed(sock):
    try:
        while sock.recv(4096):
            pass
    except OSError:
        pass  # reset instead of closed: ended either way
    sock.close()


@contextmanager
def _worker(tmp_path, monkeypatch, phone):
    """The real worker on a loopback port, serving one phone: its module, port and token."""
    from workstation.native_android import server as NS

    class Host:
        accel, why = "kvm", None

        def __init__(self, config):
            pass

        def ensure(self, account):
            pass

        def get(self, account):
            return phone
    monkeypatch.setattr(NS, "Host", Host)
    worker = NS.make_server(dict(state=str(tmp_path), sdk=str(tmp_path), token_file=str(tmp_path / "token"), port=0))
    thread = threading.Thread(target=worker.serve_forever, daemon=True)
    thread.start()
    try:
        yield NS, worker.server_port, (tmp_path / "token").read_text().strip()
    finally:
        worker.shutdown()
        worker.server_close()
        thread.join()


def test_a_refused_request_and_an_ended_stream_are_in_the_log_with_their_reason(tmp_path, monkeypatch, caplog):
    ready = [False]

    def frame():
        raise PH.PhoneError("unavailable", "Wait for Android to finish booting, or turn it on first.")
    phone = SimpleNamespace(lock=threading.RLock(), watchers=0, stream_ready=lambda: ready[0], touch=lambda: None,
                            screen=SimpleNamespace(frame=frame, rfb_event=lambda *a: None, release=lambda session: None))
    with _worker(tmp_path, monkeypatch, phone) as (NS, port, token), caplog.at_level(logging.INFO, logger=NS.__name__):
        sock, status = _viewer(port, token, viewer="nobody")
        _until_closed(sock)
        assert status == 400 and not said(caplog, "refused"), "the caller's own mistake is answered, not logged as a fault"

        sock, status = _viewer(port, token)
        _until_closed(sock)
        assert status == 503
        refused = said(caplog, "Android request refused (unavailable): Android has no live display.")
        assert len(refused) == 1 and refused[0].levelno == logging.WARNING

        ready[0] = True
        sock, status = _viewer(port, token)
        assert status == 101
        sock.sendall(_masked(b"RFB 003.008\n") + _masked(b"\x01") + _masked(b"\x01"))
        _until_closed(sock)  # the handler says why before it lets go of the connection
        ended = said(caplog, "Android viewer stream ended: Wait for Android to finish booting, or turn it on first.")
        assert len(ended) == 1
    assert phone.watchers == 0


def test_a_request_that_dies_on_an_os_error_is_answered_and_in_the_log(tmp_path, monkeypatch, caplog):
    def release_all():  # as a console or a file of this host's own can fail under any request
        raise ConnectionRefusedError(111, "Connection refused")
    phone = SimpleNamespace(lock=threading.RLock(), screen=SimpleNamespace(release_all=release_all))
    with _worker(tmp_path, monkeypatch, phone) as (NS, port, token), caplog.at_level(logging.WARNING, logger=NS.__name__):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request("POST", f"/v1/users/{ACCOUNT}/control", body=json.dumps({"holder": "person"}),
                           headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        answer = connection.getresponse()  # it used to be a dropped connection: no answer, no access line
        body = json.loads(answer.read())
        connection.close()
    assert answer.status == 500 and "ConnectionRefusedError" in body["message"]
    ended = said(caplog, "Android request ended on an OS error")
    assert len(ended) == 1 and ended[0].exc_info is not None


def test_a_start_this_host_cannot_make_is_in_the_log_not_only_on_the_phone(tmp_path, monkeypatch, caplog):
    why = "Android acceleration is unavailable: /dev/kvm is not usable by this user."
    asked = []

    def start(device):
        asked.append(device)
        return {"state": "unavailable", "why": why}
    phone = SimpleNamespace(lock=threading.RLock(), start=start, info=lambda: {"state": "unavailable", "why": why})
    with _worker(tmp_path, monkeypatch, phone) as (NS, port, token), caplog.at_level(logging.WARNING, logger=NS.__name__):
        for action in ("status", "start"):  # the panel's poll says nothing; the person's "Turn on" does
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("POST", f"/v1/users/{ACCOUNT}/phone", body=json.dumps({"action": action, "holder": "person"}),
                               headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            answer = connection.getresponse()
            assert answer.status == 200 and json.loads(answer.read())["why"] == why
            connection.close()
    assert asked == [None]
    assert len(said(caplog, f"Android phone for {ACCOUNT} did not start: {why}")) == 1


def test_a_fold_whose_console_fails_is_this_phones_error_with_its_reason(tmp_path, monkeypatch):
    system = SimpleNamespace(config={}, sdk=tmp_path / "sdk", abi="x86_64", why=None, home=lambda _: tmp_path)
    phone = H.NativePhone(system, "owned", None)
    phone.device = next(name for name, device in PH.P.PHONE_DEVICES.items() if device["kind"] == "foldable")
    phone.state, phone.emulator = "on", SimpleNamespace(pid=4242, poll=lambda: None)
    phone.screen = SimpleNamespace(release_all=lambda: None)
    monkeypatch.setattr(phone, "_active", lambda: None)

    def fails_with(error):
        def console(args, timeout):
            raise error
        monkeypatch.setattr(phone, "console", console)
    fails_with(ConnectionRefusedError(111, "Connection refused"))  # ended the request with no answer and no log
    with pytest.raises(PH.PhoneError, match=r"emulator console did not answer \(ConnectionRefusedError\)"):
        phone.set_posture("closed")
    fails_with(AdbError("The Android console no longer belongs to this VM: its emulator process has exited."))
    with pytest.raises(PH.PhoneError, match="its emulator process has exited"):  # answered "the host failed"
        phone.set_posture("closed")


# -- installing ------------------------------------------------------------------

def test_an_image_install_is_in_the_log(monkeypatch, caplog):
    from workstation.native_android import images as I
    installer = I.ImageInstaller(SimpleNamespace(lock=threading.RLock(), claims={}, closing=False))
    outcome, done = [RuntimeError("The Android image archive did not match its pinned digest.")], []

    def install_image(package):
        if outcome[0] is not None:
            raise outcome[0]
    monkeypatch.setattr(installer, "install_image", install_image)
    with caplog.at_level(logging.INFO, logger=I.__name__):
        installer.start(PH.PLAY_IMAGE, accept=True, then=done.append)
        installer._thread.join(10)
        assert len(said(caplog, f"Installing the Android image {PH.PLAY_IMAGE}.")) == 1
        failed = said(caplog, f"The Android image {PH.PLAY_IMAGE} was not installed after")
        assert len(failed) == 1 and failed[0].levelno == logging.WARNING
        assert "RuntimeError: The Android image archive did not match its pinned digest." in failed[0].getMessage()
        outcome[0] = None
        installer.start(PH.PLAY_IMAGE, accept=True, then=done.append)
        installer._thread.join(10)
    assert done == [False, True]
    assert len(said(caplog, f"The Android image {PH.PLAY_IMAGE} is installed (")) == 1


def test_a_start_that_fails_after_an_image_install_is_in_the_log(tmp_path, monkeypatch, caplog):
    class Installer:
        callback = None

        def running(self):
            return False

        def info(self):
            return {"state": "running"}

        def start(self, package, *, accept, then):
            self.callback = then
    home = tmp_path / "owner"
    home.mkdir()
    consent = tmp_path / "consent.json"
    consent.write_text(json.dumps({"license_ids": ["android-sdk-license", "android-sdk-arm-dbt-license"]}))
    system = SimpleNamespace(config={"consent": str(consent)}, sdk=tmp_path / "sdk", abi="arm64-v8a", why=None,
                             accel="hvf", home=lambda _: home, files_as=lambda _: nullcontext())
    installer = Installer()
    phone = H.NativePhone(system, "owned", None, installer=installer)
    phone.screen = SimpleNamespace(release_all=lambda: None, size=None, lock=threading.RLock())
    monkeypatch.setattr(phone, "installed", lambda device=None: False)

    def start(*args, **kwargs):
        raise RuntimeError("the emulator binary is missing")
    monkeypatch.setattr(phone, "start", start)
    assert phone.install()["state"] == "installing"
    with caplog.at_level(logging.WARNING, logger=H.__name__):
        installer.callback(True)
    assert phone.state == "unavailable" and "Check the host log" in phone.why
    failed = said(caplog, "Android phone for owned could not start after its image was installed")
    assert len(failed) == 1 and failed[0].exc_info is not None
    assert "RuntimeError: the emulator binary is missing" in caplog.text
