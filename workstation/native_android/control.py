# SPDX-License-Identifier: AGPL-3.0-or-later
"""Owned Android pixels and scrcpy input, without an SDK smart server."""
from pathlib import Path
import hashlib
import secrets
import shlex
import struct
import threading
import time

from PIL import Image
from .adb import AdbError

SERVER_VERSION = "3.3.4"
SERVER_SHA256 = "8588238c9a5a00aa542906b6ec7e6d5541d9ffb9b5d0f6e1bc0e365e2303079e"
MAX_PIXELS = 6_200_000


def raw_capture(adb):
    """Parse only Android35's fixed raw frame header, not guest PNG/JPEG."""
    data = adb.execute_bytes(["screencap"], timeout=15)
    if len(data) < 16:
        raise AdbError("Android returned a truncated raw frame.")
    width, height, pixel_format, color_space = struct.unpack("<4I", data[:16])
    if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= MAX_PIXELS):
        raise AdbError("Android returned invalid raw frame dimensions.")
    if pixel_format not in (1, 2) or len(data) != 16 + width * height * 4:
        raise AdbError("Android returned an unsupported raw pixel format or length.")
    return Image.frombytes("RGBA", (width, height), data[16:]).convert("RGB")


class ScrcpyControl:
    """Pinned control-only Android server over one authenticated ADB stream.

    The jar is public software; no private key or proxy credential is pushed.
    Clipboard autosync and sequence acknowledgements are disabled, so control
    sends do not accumulate unsolicited device clipboard contents.
    """
    def __init__(self, adb, jar):
        self.adb, self.jar = adb, Path(jar)
        self.lock = threading.RLock()
        self.channel = self.context = None
        self.pid = None
        self.scid = secrets.randbelow(0x7fffffff)
        self.remote = "/data/local/tmp/pantheon-scrcpy-" + SERVER_SHA256[:12] + ".jar"
        self.log = "/data/local/tmp/pantheon-scrcpy-" + f"{self.scid:08x}" + ".log"

    def start(self):
        if hashlib.sha256(self.jar.read_bytes()).hexdigest() != SERVER_SHA256:
            raise AdbError("The Android control server does not match its pinned digest.")
        self.adb.push(self.jar, self.remote, timeout=20)
        digest = self.adb.shell(["sha256sum", self.remote], timeout=10).split()[0]
        if digest != SERVER_SHA256:
            raise AdbError("The Android control-server readback digest did not match.")
        options = [SERVER_VERSION, f"scid={self.scid:08x}", "tunnel_forward=true", "video=false", "audio=false",
                   "control=true", "send_dummy_byte=true", "send_device_meta=false", "clipboard_autosync=false",
                   "cleanup=false", "power_on=false", "log_level=warn"]
        command = ("CLASSPATH=" + shlex.quote(self.remote) + " app_process / com.genymobile.scrcpy.Server "
                   + " ".join(map(shlex.quote, options)) + " </dev/null >" + shlex.quote(self.log) + " 2>&1 & echo $!")
        pid = self.adb.shell(["sh", "-c", command], timeout=10).strip()
        if not pid.isdigit() or int(pid) < 2:
            raise AdbError("Android did not identify its control-server process.")
        self.pid = int(pid)
        end = time.monotonic() + 15
        while True:
            context = self.adb.channel("localabstract:scrcpy_" + f"{self.scid:08x}", timeout=30)
            try:
                channel = context.__enter__()
                channel.max_pending = 65536
                if channel.read(1) != b"\0":
                    raise AdbError("Android returned an invalid control-server handshake.")
                self.context, self.channel = context, channel
                return self
            except AdbError:
                context.__exit__(None, None, None)
                if time.monotonic() >= end:
                    try:
                        detail = self.adb.execute_bytes(["tail", "-c", "2000", self.log], timeout=5).decode(errors="replace")
                    except AdbError:
                        detail = "Control-server log unavailable."
                    raise AdbError("Android's control server did not become ready: " + detail)
                time.sleep(.2)

    def send(self, data):
        with self.lock:
            if self.channel is None:
                raise AdbError("Android's control server is not connected.")
            self.channel.wire.deadline = time.monotonic() + 5
            self.channel.write(data)
            # Sequence0, no clipboard autosync: unexpected device data is
            # bounded above and discarded rather than exported to the host.
            self.channel.pending.clear()

    def key(self, keycode, *, down=True, meta=0):
        self.send(struct.pack(">BBiii", 0, 0 if down else 1, keycode, 0, meta))

    def press(self, keycode, *, meta=0):
        self.send(struct.pack(">BBiii", 0, 0, keycode, 0, meta) + struct.pack(">BBiii", 0, 1, keycode, 0, meta))

    def touch(self, action, x, y, width, height):
        if not (action in (0, 1, 2) and 0 <= x < width <= 8192 and 0 <= y < height <= 8192):
            raise AdbError("The touch leaves the active Android display.")
        self.send(struct.pack(">BBqiiHHHII", 2, action, -2, x, y, width, height,
                              0 if action == 1 else 0xffff, 0, 0))

    def text(self, value):
        if not isinstance(value, str) or "\0" in value or len(value.encode()) > 16384:
            raise AdbError("Android text is invalid or too large.")
        data = value.encode()
        self.send(struct.pack(">BqBI", 9, 0, 1, len(data)) + data)

    def close(self):
        with self.lock:
            if self.context is not None:
                self.context.__exit__(None, None, None)
            self.context = self.channel = None
            # Closing the control stream makes the pinned server exit. Avoid
            # a PID-only kill; the VM lifecycle owns final guest shutdown.

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
