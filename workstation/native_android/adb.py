# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded, authenticated ADB wire operations for an owned native Android VM.

There is no SDK smart server and no public-key enrollment request. The caller
attests the listening process before connecting and before signing a challenge.
This establishes a device-control transport, not a tenant network boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shlex
import socket
import struct
import time
from typing import Callable


MAX_PACKET = 1 << 20
MAX_OUTPUT = 24 << 20
VERSION = 0x01000001
CNXN, AUTH, OPEN, OKAY, WRTE, CLSE = (
    int.from_bytes(name, "little") for name in (b"CNXN", b"AUTH", b"OPEN", b"OKAY", b"WRTE", b"CLSE")
)


class AdbError(Exception):
    pass


class AdbAuthenticationError(AdbError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


class Wire:
    def __init__(self, sock: socket.socket, deadline: float):
        self.sock, self.deadline = sock, deadline

    def _timeout(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise AdbError("Android control timed out.")
        self.sock.settimeout(left)

    def exact(self, count: int) -> bytes:
        out = bytearray()
        while len(out) < count:
            self._timeout()
            block = self.sock.recv(count - len(out))
            if not block:
                raise AdbError("Android closed its control connection.")
            out.extend(block)
        return bytes(out)

    def send(self, command: int, arg0=0, arg1=0, data=b""):
        if len(data) > MAX_PACKET:
            raise AdbError("Android control packet is too large.")
        packet = struct.pack("<6I", command, arg0, arg1, len(data), sum(data) & 0xFFFFFFFF,
                             command ^ 0xFFFFFFFF) + data
        self._timeout()
        self.sock.sendall(packet)

    def receive(self):
        command, a, b, size, check, magic = struct.unpack("<6I", self.exact(24))
        if command not in (CNXN, AUTH, OPEN, OKAY, WRTE, CLSE) or magic != command ^ 0xFFFFFFFF:
            raise AdbError("Android returned an invalid control packet.")
        if size > MAX_PACKET:
            raise AdbError("Android returned an oversized control packet.")
        data = self.exact(size)
        # Modern ADB negotiates omitted checksums with protocol 0x01000001.
        if check and check != sum(data) & 0xFFFFFFFF:
            raise AdbError("Android control packet checksum failed.")
        return command, a, b, data


class Channel:
    def __init__(self, wire: Wire, remote: int):
        self.wire, self.remote = wire, remote
        self.pending = bytearray()
        self.closed = False
        self.max_pending = MAX_OUTPUT

    def _packet(self):
        command, a, b, data = self.wire.receive()
        if a != self.remote or b != 1:
            raise AdbError("Android answered on a different control stream.")
        if command == WRTE:
            if len(self.pending) + len(data) > self.max_pending:
                raise AdbError("Android stream output exceeded its bound.")
            self.wire.send(OKAY, 1, self.remote)
            self.pending.extend(data)
        elif command == CLSE:
            self.wire.send(CLSE, 1, self.remote)
            self.closed = True
        elif command != OKAY:
            raise AdbError("Android returned an unexpected stream packet.")
        return command

    def write(self, data: bytes):
        for offset in range(0, len(data), 64 << 10):
            self.wire.send(WRTE, 1, self.remote, data[offset:offset + (64 << 10)])
            while True:
                command = self._packet()
                if command == OKAY:
                    break
                if self.closed:
                    raise AdbError("Android closed its file-transfer stream.")
                if len(self.pending) > MAX_PACKET:
                    raise AdbError("Android returned excessive file-transfer output.")

    def read(self, count: int) -> bytes:
        if count < 0 or count > MAX_OUTPUT:
            raise AdbError("Invalid Android stream length.")
        while len(self.pending) < count and not self.closed:
            self._packet()
        if len(self.pending) < count:
            raise AdbError("Android returned an incomplete stream.")
        out = bytes(self.pending[:count])
        del self.pending[:count]
        return out

    def all(self, limit=MAX_OUTPUT) -> bytes:
        while not self.closed:
            self._packet()
            if len(self.pending) > limit:
                raise AdbError("Android output exceeded its limit.")
        return bytes(self.pending)


class DirectAdb:
    """A single immutable target; callers cannot supply arbitrary host addresses."""

    def __init__(self, port: int, key: Path, attest: Callable[[], bool]):
        self.port, self.key, self.attest = port, Path(key), attest

    def _owned(self):
        if not self.attest():
            raise AdbError("The Android control listener no longer belongs to this VM.")

    @contextmanager
    def channel(self, service: str, timeout=20.0):
        self._owned()
        if not isinstance(service, str) or "\0" in service or len(service.encode()) > 65536:
            raise AdbError("Invalid Android control service.")
        deadline = time.monotonic() + timeout
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as sock:
                wire = Wire(sock, deadline)
                wire.send(CNXN, VERSION, MAX_PACKET, b"host::features=shell_v2,cmd;\0")
                command, kind, _, challenge = wire.receive()
                if command != AUTH or kind != 1 or len(challenge) != 20:
                    raise AdbAuthenticationError("missing_auth_challenge", "Android did not require private device authentication.")
                self._owned()
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import padding, utils
                key = serialization.load_pem_private_key(self.key.read_bytes(), password=None)
                signature = key.sign(challenge, padding.PKCS1v15(), utils.Prehashed(hashes.SHA1()))
                wire.send(AUTH, 2, 0, signature)
                command, kind, _, answer = wire.receive()
                if command != CNXN:
                    if command == AUTH and kind == 1 and len(answer) == 20:
                        raise AdbAuthenticationError("key_rejected", "Android rejected this VM's private device key.")
                    raise AdbError("Android did not authenticate this VM's private device key.")
                self._owned()
                wire.send(OPEN, 1, 0, service.encode() + b"\0")
                command, remote, local, data = wire.receive()
                if command != OKAY or local != 1 or remote == 0 or data:
                    raise AdbError("Android refused its requested control stream.")
                yield Channel(wire, remote)
        except (OSError, ValueError) as e:
            raise AdbError(f"Android control connection failed ({type(e).__name__}).") from e

    def shell(self, args: list[str], timeout=20.0) -> str:
        command = " ".join(shlex.quote(str(arg)) for arg in args)
        with self.channel("shell,v2,raw:" + command, timeout) as channel:
            data = channel.all()
        stdout, stderr, exit_code = bytearray(), bytearray(), None
        offset = 0
        while offset < len(data):
            if len(data) - offset < 5:
                raise AdbError("Android returned an incomplete shell packet.")
            stream, size = data[offset], struct.unpack_from("<I", data, offset + 1)[0]
            offset += 5
            if size > len(data) - offset:
                raise AdbError("Android returned an invalid shell packet length.")
            part = data[offset:offset + size]
            offset += size
            if stream == 1:
                stdout.extend(part)
            elif stream == 2:
                stderr.extend(part)
            elif stream == 3 and len(part) == 1:
                exit_code = part[0]
            else:
                raise AdbError("Android returned an unknown shell stream.")
        if exit_code != 0:
            detail = stderr.decode("utf-8", "replace").strip()[:300]
            raise AdbError("Android command did not complete" + (": " + detail if detail else "."))
        return stdout.decode("utf-8", "replace")

    def execute_bytes(self, args: list[str], timeout=20.0) -> bytes:
        command = " ".join(shlex.quote(str(arg)) for arg in args)
        with self.channel("exec:" + command, timeout) as channel:
            return channel.all()

    def push(self, source: Path, destination: str, timeout=45.0):
        path = (destination + ",33152").encode()  # S_IFREG | 0600, SDK sync protocol's decimal mode
        if len(path) > 1024:
            raise AdbError("Android transfer destination is too long.")
        with self.channel("sync:", timeout) as channel:
            channel.write(b"SEND" + struct.pack("<I", len(path)) + path)
            with Path(source).open("rb") as f:
                for block in iter(lambda: f.read(64 << 10), b""):
                    channel.write(b"DATA" + struct.pack("<I", len(block)) + block)
            channel.write(b"DONE" + struct.pack("<I", int(time.time())))
            status, size = struct.unpack("<4sI", channel.read(8))
            if status != b"OKAY" or size:
                detail = channel.read(min(size, 4096)).decode("utf-8", "replace") if size else ""
                raise AdbError("Android did not accept the transferred file" + (": " + detail[:300] if detail else "."))
            channel.wire.send(CLSE, 1, channel.remote)
