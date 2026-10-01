# SPDX-License-Identifier: AGPL-3.0-or-later
"""Has the screen changed since the last picture? — `B974`.

`agentd` answers `screenshot?if_none_match=<digest>` with `304` when the screen
is the frame the caller already holds. Until `B974` it found that out by taking
the frame (`scrot`) and hashing it, so a 304 saved the transfer and not the
grab: a person watching a still screen (`P20-05`, a frame every ~300 ms) cost
the workstation a grab every time.

**The X server already knows what was drawn, and where.** Its DAMAGE extension
reports changes to a drawable's contents. This module is one small X client per
display, speaking the X11 wire protocol over the display's Unix socket
(standard library only, the package's rule — no Xlib): a damage object on the
root window at the `BoundingBox` level, so the server sends an event whenever
the box around everything drawn since the last clear grows — a handful of
events, not one per drawing.

**Drawn is not changed — measured.** On the shipped desktop the tray's clock
(`skel/.jwmrc`, `%H:%M`) is redrawn about three times a second with the same
pixels (2026-10-01, the workstation image, Xvfb: 16 damage reports in 5 s of an
idle desktop, every one the clock's 45x30 box). Damage alone would call that
screen changed every time. So a mark also keeps the screen's own pixels
(`GetImage`, 4 MB raw, 4.5 ms measured, against 50 ms for the `scrot` JPEG
on the same host at load 2.3), and a question about a screen that was drawn on
compares only the drawn box with them (0.06 ms for the clock's box).

    mark = watch.mark()       before a grab: damage cleared, the pixels kept
    mark = watch.settle(mark) after it: None if anything moved meanwhile
    watch.unchanged(mark)     is the screen still that frame?

**Exact, not hopeful.** `unchanged` ends with a round trip to the server
(`GetInputFocus`): on one connection the X protocol delivers every event the
server generated before it handled a request ahead of that request's reply, so
every drawing finished before the question has been reported when the answer
is read. `mark` clears the damage before it reads the pixels, so anything drawn
after it is either in them or reported — usually both. `settle` keeps the mark
only if nothing at all was drawn from the clear to the end of the grab, so the
frame the caller holds is exactly the pixels the mark describes; a question
that then finds the drawn box mid-redraw says "changed", and the caller grabs. Anything that
goes wrong — no DAMAGE extension, a refused connection, the server gone — makes
the watch broken, a broken watch's marks are never unchanged, and the caller
grabs exactly as before this module.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from typing import NamedTuple, Optional, Tuple

#: DamageReportBoundingBox: an event whenever the damage's bounding box grows.
REPORT_BOUNDING_BOX = 2
_OP_GET_IMAGE = 73
_OP_GET_INPUT_FOCUS = 43
_OP_QUERY_EXTENSION = 98
_Z_PIXMAP = 2
_DAMAGE_QUERY_VERSION, _DAMAGE_CREATE, _DAMAGE_SUBTRACT = 0, 1, 3
_TIMEOUT_S = 5.0
# A box this small (a sixteenth of the screen) is worth one more look before
# "changed": the clock's is 1,350 pixels.
_SMALL_BOX_PX = 64_000
_REDRAW_PAUSE_S = 0.015


class XError(Exception):
    """The display refused, or stopped answering."""


class Mark(NamedTuple):
    """The screen as one frame saw it: which watch, which clear of its damage
    (a later clear forgets what was drawn before it), and its pixels."""
    watch: "DamageWatch"
    clear: int
    pixels: bytes


def _pad(n: int) -> int:
    return (4 - n % 4) % 4


def _union(a: Optional[Tuple[int, int, int, int]], b: Tuple[int, int, int, int]
           ) -> Tuple[int, int, int, int]:
    if a is None:
        return tuple(b)  # type: ignore[return-value]
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0)


class DamageWatch:
    """One display's damage, watched through its own X connection."""

    def __init__(self, socket_path: str, cookie: bytes, *, timeout: float = _TIMEOUT_S) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._clears = 0
        # The box around everything drawn since the last clear, or None when
        # nothing has been. Every report after a clear grows it from nothing,
        # so a drawing after a clear is never without one.
        self._box: Optional[Tuple[int, int, int, int]] = None
        self._first_event: Optional[int] = None
        self._broken = False
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        try:
            self._sock.connect(socket_path)
            self._setup(cookie)
            self._extension()
        except (OSError, struct.error, XError) as e:
            self.close()
            raise XError(f"the display's damage cannot be watched: {e}") from e

    # -- the wire -----------------------------------------------------------

    def _read(self, n: int) -> bytes:
        buf = bytearray(n)
        view = memoryview(buf)
        got = 0
        while got < n:
            k = self._sock.recv_into(view[got:], n - got)
            if not k:
                raise XError("the display closed the connection")
            got += k
        return buf  # type: ignore[return-value] — compared and sliced, never changed

    def _setup(self, cookie: bytes) -> None:
        name = b"MIT-MAGIC-COOKIE-1"
        head = struct.pack("<BxHHHHxx", 0x6C, 11, 0, len(name), len(cookie))
        self._sock.sendall(head + name + b"\0" * _pad(len(name)) + cookie
                           + b"\0" * _pad(len(cookie)))
        status, reason_len, _maj, _min, extra = struct.unpack("<BBHHH", self._read(8))
        data = self._read(extra * 4)
        if status != 1:
            raise XError(data[:reason_len].decode("latin-1", "replace") or "refused")
        (_release, self._id_base, self._id_mask, _motion, vendor_len, _max_req, _screens,
         formats) = struct.unpack_from("<IIIIHHBB", data, 0)
        screen = 32 + vendor_len + _pad(vendor_len) + 8 * formats
        (self.root,) = struct.unpack_from("<I", data, screen)
        self.width, self.height = struct.unpack_from("<HH", data, screen + 20)

    def _request(self, data: bytes) -> int:
        self._sock.sendall(data)
        self._seq = (self._seq + 1) & 0xFFFF
        return self._seq

    def _await_reply(self, seq: int) -> Tuple[bytes, bytes]:
        """Read until the reply to `seq`, taking in every damage report on the
        way. An error for any request of ours raises: each one is expected to
        succeed, and a damage object that was never made reports nothing —
        which would read as "unchanged" for ever."""
        while True:
            packet = self._read(32)
            kind = packet[0] & 0x7F
            if kind == 1:
                (got, extra) = struct.unpack_from("<HI", packet, 2)
                # The body apart from the header, never joined to it: a whole
                # screen is 4 MB, and every copy of it is time on a grab.
                body = self._read(extra * 4) if extra else b""
                if got == seq:
                    return packet, body
            elif kind == 0:
                (got,) = struct.unpack_from("<H", packet, 2)
                raise XError(f"the display refused request {got} (X error {packet[1]})")
            elif self._first_event is not None and kind == self._first_event:
                # DamageNotify: its `area` is the damage's bounding box now.
                # Joined to the box held, never put in its place: a report
                # from before a clear can arrive after it, and keeping a larger
                # box only means comparing more pixels.
                self._box = _union(self._box, struct.unpack_from("<hhHH", packet, 16))

    def _extension(self) -> None:
        name = b"DAMAGE"
        reply, _ = self._await_reply(self._request(
            struct.pack("<BxHHxx", _OP_QUERY_EXTENSION, 2 + (len(name) + _pad(len(name))) // 4,
                        len(name)) + name + b"\0" * _pad(len(name))))
        present, self._major, first_event = reply[8], reply[9], reply[10]
        if not present:
            raise XError("the display has no DAMAGE extension")
        # The version is asked before anything else, as the extension requires.
        self._await_reply(self._request(struct.pack("<BBHII", self._major, _DAMAGE_QUERY_VERSION,
                                                    3, 1, 1)))
        self._first_event = first_event
        self._damage = self._id_base | (self._id_mask & -self._id_mask)
        self._request(struct.pack("<BBHIIBxxx", self._major, _DAMAGE_CREATE, 4, self._damage,
                                  self.root, REPORT_BOUNDING_BOX))
        self._sync()

    def _sync(self) -> None:
        self._await_reply(self._request(struct.pack("<BxH", _OP_GET_INPUT_FOCUS, 1)))

    def _clear(self) -> None:
        # What was reported before this point is read and forgotten FIRST, then
        # the server's damage is emptied: a report read after this line is
        # either from just before the subtract (a box too many, harmless) or
        # from after it (needed) — so none is dropped (`_await_reply`).
        self._sync()
        self._box = None
        self._clears += 1
        self._request(struct.pack("<BBHIII", self._major, _DAMAGE_SUBTRACT, 4,
                                  self._damage, 0, 0))
        self._sync()

    def _pixels(self, x: int = 0, y: int = 0, w: Optional[int] = None,
                h: Optional[int] = None) -> bytes:
        w = self.width if w is None else w
        h = self.height if h is None else h
        _, pixels = self._await_reply(self._request(struct.pack(
            "<BBHIhhHHI", _OP_GET_IMAGE, _Z_PIXMAP, 5, self.root, x, y, w, h, 0xFFFFFFFF)))
        return pixels

    def _box_unchanged(self, mark: Mark) -> bool:
        """Whether the drawn box holds the pixels the mark kept."""
        x, y, w, h = self._box  # type: ignore[misc]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return True  # drawn entirely off the screen
        now = self._pixels(x0, y0, x1 - x0, y1 - y0)
        row = (x1 - x0) * 4
        if len(now) < row * (y1 - y0) or len(mark.pixels) < self.width * 4 * self.height:
            return False  # not 32 bits a pixel: nothing here can compare it
        stride = self.width * 4
        for r in range(y1 - y0):
            start = (y0 + r) * stride + x0 * 4
            if mark.pixels[start:start + row] != now[r * row:(r + 1) * row]:
                return False
        return True

    # -- what `agentd` asks -------------------------------------------------

    def _guarded(self, fn, fallback):
        with self._lock:
            if self._broken:
                return fallback
            try:
                return fn()
            except (OSError, struct.error, XError):
                self._broken = True
                return fallback

    def mark(self) -> Optional[Mark]:
        """Clear the damage and keep the pixels, just before a grab; None when
        the watch is broken (the caller then grabs every time)."""
        def go():
            self._clear()
            return Mark(self, self._clears, self._pixels())
        return self._guarded(go, None)

    def settle(self, mark: Optional[Mark]) -> Optional[Mark]:
        """After the grab: the mark, if NOTHING was drawn between the clear
        and now — so the frame taken in between is exactly the pixels the
        mark kept. Drawn-but-equal is not enough here: a redraw is several
        requests (measured: the tray clock, read mid-redraw by one question in
        thirty), and a grab that landed between two of them holds a picture
        the screen never settled on. None then: that frame is not trusted, and
        the next question grabs again."""
        if mark is None or mark.watch is not self:
            return None

        def go():
            self._sync()
            return mark if mark.clear == self._clears and self._box is None else None
        return self._guarded(go, None)

    def unchanged(self, mark: Optional[Mark]) -> bool:
        """Whether the screen is still what `mark` saw: nothing drawn since,
        or only drawing that left the drawn box's pixels as they were. Asked of
        the server now (module docstring), never answered from memory alone."""
        if mark is None or mark.watch is not self:
            return False

        def go():
            self._sync()
            if mark.clear != self._clears:
                return False  # what was drawn between then and that clear is forgotten
            if self._box is None:
                return True
            if self._box_unchanged(mark):
                return True
            # A small box read mid-redraw is asked once more, a moment later
            # (module docstring: the tray clock's redraw, caught one question
            # in fifteen to thirty). Still an answer about the screen as it is.
            x, y, w, h = self._box
            if w * h > _SMALL_BOX_PX:
                return False
            time.sleep(_REDRAW_PAUSE_S)
            self._sync()
            return self._box_unchanged(mark)
        return self._guarded(go, False)

    @property
    def broken(self) -> bool:
        return self._broken

    def close(self) -> None:
        self._broken = True
        try:
            self._sock.close()
        except OSError:
            pass  # already closed: nothing left to release


__all__ = ["DamageWatch", "Mark", "REPORT_BOUNDING_BOX", "XError"]
