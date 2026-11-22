# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone's screen as video: the pinned scrcpy server's H.264, decoded here.

`screencap` copies a whole raw frame out of Android for every picture (about
10 MB at 1080 x 2400), and on an emulator each one takes the better part of a
second, so the live phone ran at about one frame a second (the owner,
2026-11-22). The scrcpy server that already takes the phone's taps encodes the
screen as it changes, at the size it is shown, and is read here over its own
authenticated ADB stream. `screencap` stays the fallback: before the first
frame, while the display turns, on a folded cover screen, and on a host
without PyAV.

The stream starts when a picture is wanted and stops after `IDLE_S` without
one, so a phone nobody watches encodes nothing.
"""
from __future__ import annotations

import logging
import secrets
import shlex
import socket
import struct
import threading
import time

from .adb import AdbError
from .control import SERVER_VERSION, install

logger = logging.getLogger(__name__)

CODEC_H264 = 0x68323634  # "h264", scrcpy's codec id
FLAG_CONFIG = 1 << 63
MAX_PACKET = 8 << 20  # one encoded frame; 8 Mbit/s never makes one near this
# The viewer's frame is at most 1280 x 1100 (`Screen.refresh`): no larger
# picture is ever shown, so none larger is encoded.
MAX_SIZE = 1280
MAX_FPS = 30
BIT_RATE = 8_000_000
IDLE_S = 30  # no picture wanted this long: the stream stops
RETRY_S = 60  # a stream that would not start is tried again after this
READY_S = 15  # the server's socket appears within this


def _decoder():
    try:
        import av  # noqa: PLC0415 — optional on a host; screencap is the fallback
    except ImportError:
        return None
    return av.CodecContext.create("h264", "r")


def _packet(data):
    import av  # noqa: PLC0415 — present whenever a decoder was made
    return av.Packet(data)


class ScrcpyVideo:
    """Started on demand by `want()`; `picture()` is the newest decoded frame."""

    def __init__(self, adb, jar, *, who=None, decoder=_decoder, packet=_packet):
        self.adb, self.jar, self.who = adb, jar, who
        self.decoder, self.packet = decoder, packet
        self.lock = threading.Lock()
        self.thread = None
        self.channel = None
        self.frame = None  # the newest decoded frame, converted only when shown
        self.image = None
        self.serial = self.shown = 0
        self.wanted_at = 0.0
        self.failed_at = None
        self.unavailable = None  # why this host never streams video (said once)
        self.closed = False

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def want(self):
        """A picture is wanted now: the stream runs, or starts in the background."""
        now = time.monotonic()
        with self.lock:
            self.wanted_at = now
            if self.closed or self.unavailable or self.running:
                return
            if self.failed_at is not None and now - self.failed_at < RETRY_S:
                return
            self.frame = self.image = None
            self.thread = threading.Thread(target=self._run, daemon=True, name="android-video")
            self.thread.start()

    def picture(self):
        """(PIL RGB image, serial) of the newest frame, or None without one."""
        with self.lock:
            if not self.running or self.frame is None:
                return None
            if self.shown != self.serial:
                self.image, self.shown = self.frame.to_image(), self.serial
            return self.image, self.shown

    def close(self):
        with self.lock:
            self.closed = True
            channel, thread = self.channel, self.thread
        self._hang_up(channel)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    @staticmethod
    def _hang_up(channel):
        if channel is None:
            return
        try:
            channel.wire.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # already closed: the reader is ending anyway

    def _run(self):
        decoder = self.decoder()
        if decoder is None:
            with self.lock:
                self.unavailable = "PyAV is not installed on this host"
            logger.warning("Android phone for %s: the screen streams by screenshot (about one frame a second) "
                           "because %s.", self.who, self.unavailable)
            return
        try:
            context, channel = self._start()
        except Exception as error:  # noqa: BLE001 — any start failure leaves the screenshot, never the phone
            with self.lock:
                self.failed_at = time.monotonic()
            said = str(error) if isinstance(error, AdbError) else type(error).__name__
            logger.warning("Android phone for %s: its screen's video did not start, so it streams by screenshot "
                           "for now: %s", self.who, " ".join(said.split())[:300])
            return
        try:
            with self.lock:
                if self.closed:
                    return
                self.channel = channel
            self._read(channel, decoder)
        except (AdbError, OSError) as error:
            with self.lock:
                ended = self.closed
                self.failed_at = None if ended else time.monotonic()
            if not ended:
                logger.warning("Android phone for %s: its screen's video stopped, so it streams by screenshot "
                               "for now: %s", self.who, " ".join(str(error).split())[:300])
        except Exception as error:  # a decoder error: the stream is dropped, never the phone
            with self.lock:
                self.failed_at = time.monotonic()
            logger.warning("Android phone for %s: its screen's video could not be decoded (%s), so it streams "
                           "by screenshot for now.", self.who, type(error).__name__)
        finally:
            with self.lock:
                self.channel = None
                self.frame = self.image = None
            try:
                context.__exit__(None, None, None)
            except (AdbError, OSError):
                pass  # the stream is already gone, which is the goal

    def _start(self):
        remote = install(self.adb, self.jar)
        scid = secrets.randbelow(0x7fffffff)
        options = [SERVER_VERSION, f"scid={scid:08x}", "tunnel_forward=true", "video=true", "audio=false",
                   "control=false", "video_codec=h264", f"max_size={MAX_SIZE}", f"max_fps={MAX_FPS}",
                   f"video_bit_rate={BIT_RATE}", "send_dummy_byte=true", "send_device_meta=false",
                   "send_codec_meta=true", "send_frame_meta=true", "cleanup=false", "power_on=false",
                   "log_level=warn"]
        log = f"/data/local/tmp/pantheon-scrcpy-{scid:08x}.log"
        command = ("CLASSPATH=" + shlex.quote(remote) + " app_process / com.genymobile.scrcpy.Server "
                   + " ".join(map(shlex.quote, options)) + " </dev/null >" + shlex.quote(log) + " 2>&1 & echo $!")
        pid = self.adb.shell(["sh", "-c", command], timeout=10).strip()
        if not pid.isdigit() or int(pid) < 2:
            raise AdbError("Android did not identify its screen-video server.")
        end = time.monotonic() + READY_S
        while True:
            context = self.adb.channel("localabstract:scrcpy_" + f"{scid:08x}", timeout=30)
            try:
                channel = context.__enter__()
                channel.max_pending = MAX_PACKET + 64
                if channel.read(1) != b"\0":
                    raise AdbError("Android's screen-video server sent an invalid handshake.")
                codec, width, height = struct.unpack(">III", channel.read(12))
                if codec != CODEC_H264:
                    raise AdbError("Android's screen-video server could not encode the screen"
                                   + (f" (codec {codec:#x})." if codec > 1 else "."))
                if not (0 < width <= 8192 and 0 < height <= 8192):
                    raise AdbError("Android's screen video has an invalid size.")
                return context, channel
            except AdbError:
                context.__exit__(None, None, None)
                if time.monotonic() >= end:
                    try:
                        detail = self.adb.execute_bytes(["tail", "-c", "2000", log], timeout=5).decode(errors="replace")
                    except AdbError:
                        detail = "its log is unavailable."
                    raise AdbError("Android's screen-video server did not become ready: " + detail)
                time.sleep(.2)

    def _read(self, channel, decoder):
        config = b""
        while True:
            with self.lock:
                if self.closed or time.monotonic() - self.wanted_at > IDLE_S:
                    return
            # A still screen sends nothing for as long as it stays still.
            channel.wire.deadline = time.monotonic() + IDLE_S + 5
            try:
                header = channel.read(12)
            except AdbError as error:
                if "timed out" in str(error):
                    continue  # nothing changed on screen; the idle check above decides
                raise
            flags, size = struct.unpack(">QI", header)
            if size > MAX_PACKET:
                raise AdbError("Android's screen video sent an oversized frame.")
            channel.wire.deadline = time.monotonic() + 10
            data = channel.read(size)
            if flags & FLAG_CONFIG:
                config = data  # the codec's parameters, decoded with the next frame as scrcpy's own client does
                continue
            if config:
                data, config = config + data, b""
            for frame in decoder.decode(self.packet(data)):
                with self.lock:
                    self.frame = frame
                    self.serial += 1
