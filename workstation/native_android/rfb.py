# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded Kasm-dialect RFB pixels and input for the existing trusted viewer.

There is no public RFB listener. A worker authenticates the HTTP upgrade before
passing its stream here. The pinned viewer uses Kasm pointer11/codec184/alive185
messages; this is explicitly that dialect, never length-based protocol guessing.
"""
import io
import struct
import time


MAX_MESSAGE = 1 << 20
CHUNK = 60 << 10


class StreamEnded(Exception):
    pass


class ProtocolError(Exception):
    pass


class WebSocketBytes:
    def __init__(self, incoming, outgoing):
        self.incoming, self.outgoing = incoming, outgoing
        self.buffer = bytearray()
        self.fragmented = False
        self.message_size = 0

    def _exact(self, count):
        out = bytearray()
        while len(out) < count:
            block = self.incoming.read(count - len(out))
            if not block:
                raise StreamEnded()
            out.extend(block)
        return bytes(out)

    def _send(self, opcode, payload):
        size = len(payload)
        if size > CHUNK:
            raise ProtocolError("Outgoing websocket chunk is too large.")
        header = bytes((0x80 | opcode, size)) if size < 126 else bytes((0x80 | opcode, 126)) + struct.pack(">H", size)
        self.outgoing.write(header + payload)
        self.outgoing.flush()

    def _frame(self):
        flags, length = self._exact(2)
        final, opcode = bool(flags & 0x80), flags & 0x0f
        if flags & 0x70 or not length & 0x80:
            raise ProtocolError("Invalid websocket flags or unmasked client frame.")
        size = length & 0x7f
        if size == 126:
            size = struct.unpack(">H", self._exact(2))[0]
        elif size == 127:
            size = struct.unpack(">Q", self._exact(8))[0]
        if size > MAX_MESSAGE:
            raise ProtocolError("Incoming websocket frame is too large.")
        if opcode >= 8 and (not final or size > 125):
            raise ProtocolError("Invalid websocket control frame.")
        mask = self._exact(4)
        payload = self._exact(size)
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 8:
            if size == 1:
                raise ProtocolError("Invalid websocket close payload.")
            if size > 2:
                try:
                    payload[2:].decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ProtocolError("Invalid websocket close reason.") from error
            self._send(8, payload)
            raise StreamEnded()
        if opcode == 9:
            self._send(10, payload)
            return b""
        if opcode == 10:
            return b""
        if opcode == 2:
            if self.fragmented:
                raise ProtocolError("A websocket message interrupted a fragment.")
            self.message_size = size
            self.fragmented = not final
        elif opcode == 0:
            if not self.fragmented:
                raise ProtocolError("Unexpected websocket continuation.")
            self.message_size += size
            self.fragmented = not final
        else:
            raise ProtocolError("The device stream accepts binary websocket data only.")
        if self.message_size > MAX_MESSAGE:
            raise ProtocolError("Incoming websocket message is too large.")
        return payload

    def read(self, count):
        if not 0 <= count <= MAX_MESSAGE:
            raise ProtocolError("Invalid RFB read length.")
        while len(self.buffer) < count:
            self.buffer.extend(self._frame())
            if len(self.buffer) > MAX_MESSAGE:
                raise ProtocolError("RFB input buffering exceeded its bound.")
        value = bytes(self.buffer[:count])
        del self.buffer[:count]
        return value

    def write(self, data):
        for offset in range(0, len(data), CHUNK):
            self._send(2, data[offset:offset + CHUNK])


DEFAULT_FORMAT = struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 0, 8, 16)


def pixel_bytes(image, pixel_format):
    bpp, depth, big, true_color, red, green, blue, r_shift, g_shift, b_shift = struct.unpack(">BBBBHHHBBB3x", pixel_format)
    if (bpp, depth, true_color, red, green, blue) != (32, 24, 1, 255, 255, 255):
        raise ProtocolError("The phone viewer requires 32-bit RGB true color.")
    if (r_shift, g_shift, b_shift) not in ((0, 8, 16), (16, 8, 0)) or big not in (0, 1):
        raise ProtocolError("Unsupported phone pixel layout.")
    if big:
        mode = "XBGR" if r_shift == 0 else "XRGB"
    else:
        mode = "RGBX" if r_shift == 0 else "BGRX"
    return image.convert("RGB").tobytes("raw", mode)


def serve(stream, frame, event, release, *, frame_interval=.25):
    """`frame` returns (PIL RGB image, immutable geometry token).

    `event` must consult the worker's current holder every time. It receives
    the connection geometry token; this stream closes when it changes.
    `release` clears this viewer's held touches and keys on every exit path.
    """
    try:
        stream.write(b"RFB 003.008\n")
        if stream.read(12) != b"RFB 003.008\n":
            raise ProtocolError("The phone viewer requires RFB3.8.")
        # Authentication is the worker's bearer-protected upgrade, before
        # this function. No separate raw host VNC endpoint exists.
        stream.write(b"\x01\x01")
        if stream.read(1) != b"\x01":
            raise ProtocolError("Unexpected RFB security selection.")
        stream.write(b"\0\0\0\0")
        if stream.read(1) not in (b"\0", b"\x01"):
            raise ProtocolError("Invalid RFB client initialization.")
        image, geometry = frame()
        width, height = image.size
        if not (0 < width <= 1280 and 0 < height <= 1280):
            raise ProtocolError("The logical phone frame is outside its bound.")
        name = b"Pantheon Android"
        pixel_format = DEFAULT_FORMAT
        stream.write(struct.pack(">HH", width, height) + pixel_format + struct.pack(">I", len(name)) + name)
        encodings, last_frame_at = set(), 0.0
        while True:
            kind = stream.read(1)[0]
            if kind == 0:
                packet = stream.read(19)
                pixel_format = packet[3:]
                pixel_bytes(image.crop((0, 0, 1, 1)), pixel_format)
            elif kind == 2:
                padding, count = struct.unpack(">BH", stream.read(3))
                if count > 256:
                    raise ProtocolError("Too many RFB encodings.")
                encodings = set(struct.unpack(">" + "i" * count, stream.read(count * 4)))
            elif kind == 3:
                incremental, x, y, w, h = struct.unpack(">BHHHH", stream.read(9))
                if incremental not in (0, 1) or x + w > width or y + h > height:
                    raise ProtocolError("The framebuffer request leaves the current display.")
                delay = last_frame_at + frame_interval - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                current, current_geometry = frame()
                new_width, new_height = current.size
                if not (0 < new_width <= 1280 and 0 < new_height <= 1280):
                    raise ProtocolError("The updated phone frame is outside its bound.")
                if current_geometry != geometry or current.size != (width, height):
                    raise StreamEnded("The Android display changed; reconnect to its new geometry.")
                if not {7, -224} <= encodings:
                    raise ProtocolError("The bundled phone viewer requires Tight JPEG and LastRect.")
                encoded = io.BytesIO()
                current.convert("RGB").save(encoded, format="JPEG", quality=80)
                data = encoded.getvalue()
                if len(data) > 0x3fffff:
                    raise ProtocolError("The encoded phone frame exceeded its bound.")
                length = bytearray()
                value = len(data)
                length.append((value & 127) | (128 if value > 127 else 0))
                if value > 127:
                    value >>= 7
                    length.append((value & 127) | (128 if value > 127 else 0))
                    if value > 127:
                        length.append(value >> 7)
                stream.write(struct.pack(">BBH", 0, 0, 2))
                stream.write(struct.pack(">HHHHi", 0, 0, width, height, 7))
                stream.write(b"\x90" + length + data)
                stream.write(struct.pack(">HHHHi", 0, 0, 0, 0, -224))
                last_frame_at = time.monotonic()
            elif kind == 4:
                down, padding, keysym = struct.unpack(">BHI", stream.read(7))
                if down not in (0, 1):
                    raise ProtocolError("Invalid RFB key state.")
                event({"kind": "key", "down": bool(down), "keysym": keysym, "geometry": geometry})
            elif kind == 5:
                buttons, x, y, relative_x, relative_y = struct.unpack(">HHHHH", stream.read(10))
                if x >= width or y >= height or buttons & ~0x1ff:
                    raise ProtocolError("The pointer event leaves the current phone display.")
                event({"kind": "pointer", "buttons": buttons, "x": x, "y": y, "geometry": geometry})
            elif kind == 6:
                packet = stream.read(7)
                size = struct.unpack(">I", packet[3:])[0]
                if size > 16384:
                    raise ProtocolError("Phone clipboard text is too large.")
                try:
                    text = stream.read(size).decode("utf-8")
                except UnicodeDecodeError as e:
                    raise ProtocolError("Phone clipboard text is not UTF8.") from e
                event({"kind": "text", "text": text, "geometry": geometry})
            elif kind == 180:
                count = stream.read(1)[0]
                if count != 1:
                    raise ProtocolError("The phone accepts one plain-text clipboard item.")
                mime_size = stream.read(1)[0]
                if mime_size != 10 or stream.read(mime_size) != b"text/plain":
                    raise ProtocolError("The phone clipboard accepts plain text only.")
                size = struct.unpack(">I", stream.read(4))[0]
                if size > 16384:
                    raise ProtocolError("Phone clipboard text is too large.")
                try:
                    text = stream.read(size).decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ProtocolError("Phone clipboard text is not UTF8.") from error
                event({"kind": "text", "text": text, "geometry": geometry})
            elif kind == 182:
                # The bundled Kasm client asks for printer/smartcard relays
                # immediately after initialization, without negotiation.
                # Consume its bounded name and decline; Android exposes none.
                stream.read(stream.read(1)[0])
                reason = b"Android has no relays."
                stream.write(bytes((182, 0, len(reason))) + reason)
            elif kind == 184:
                count = stream.read(1)[0]
                stream.read(count * 4)  # Kasm codec capability list; this server sends Tight JPEG only.
            elif kind == 185:
                pass  # Kasm keepalive
            else:
                raise ProtocolError(f"Unsupported unadvertised phone RFB message {kind}.")
    finally:
        release()
