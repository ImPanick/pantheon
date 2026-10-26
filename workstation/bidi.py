# SPDX-License-Identifier: AGPL-3.0-or-later
"""A WebDriver BiDi client, standard library only. `P25-05`.

The daemon drives each person's Firefox over WebDriver BiDi — the W3C protocol
Firefox speaks natively since 129, over one WebSocket. The daemon has no
third-party dependencies (`workstation/Dockerfile` installs none for it), so
this module is the WebSocket client too: RFC 6455's client half, enough for
one connection to a browser on this machine — masked frames out, text frames
in (fragmented or not), pings answered, a close honoured.

`Session.call(method, params)` sends a command and waits for the answer with
its `id`; events (`browsingContext.load`, …) are kept, newest last, for a
caller that wants them. One reader thread per connection; every call takes
the lock only to register its waiter, so two calls from two threads (the
agent's and the person's window) interleave rather than serialise behind a
slow page load.
"""

from __future__ import annotations

import base64
import collections
import hashlib
import json
import os
import socket
import struct
import threading
from typing import Any, Deque, Dict, Optional

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class BidiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _Socket:
    """The WebSocket: a handshake, then frames."""

    def __init__(self, host: str, port: int, path: str, timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise BidiError("unavailable", "The browser closed the connection during its handshake.")
            head += chunk
            if len(head) > 65536:
                raise BidiError("unavailable", "The browser's handshake was too long.")
        head, _, self._rest = head.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        if not lines[0].startswith("HTTP/1.1 101"):
            raise BidiError("unavailable", f"The browser refused the connection: {lines[0][:80]}.")
        accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
        if headers.get("sec-websocket-accept") != accept:
            raise BidiError("unavailable", "The browser's handshake did not match.")
        self.sock.settimeout(None)
        self._send_lock = threading.Lock()

    def _read(self, n: int) -> bytes:
        out = b""
        if self._rest:
            out, self._rest = self._rest[:n], self._rest[n:]
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("closed")
            out += chunk
        return out

    def send(self, opcode: int, payload: bytes) -> None:
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack("!H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", n)
        mask = os.urandom(4)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            self.sock.sendall(head + mask + body)

    def recv_message(self) -> Optional[str]:
        """The next text message, or None when the connection closed."""
        parts = []
        while True:
            b1, b2 = self._read(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            data = self._read(n) if n else b""
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                try:
                    self.send(0x8, data[:2])
                except OSError:
                    pass  # the peer is closing anyway; our echo of its close is a courtesy
                return None
            if opcode == 0x9:
                self.send(0xA, data)
                continue
            if opcode == 0xA:
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.send(0x8, struct.pack("!H", 1000))
        except OSError:
            pass  # closing: a socket the browser already dropped needs no close frame
        try:
            self.sock.close()
        except OSError:
            pass  # closing: the socket is gone either way


class Session:
    """One BiDi session: `call` and the events the browser sent."""

    EVENTS_KEPT = 200

    def __init__(self, host: str, port: int, *, path: str = "/session", timeout: float = 10.0):
        self._ws = _Socket(host, port, path, timeout)
        self._next = 0
        self._lock = threading.Lock()
        self._waiting: Dict[int, Dict[str, Any]] = {}
        self.events: Deque[Dict[str, Any]] = collections.deque(maxlen=self.EVENTS_KEPT)
        self.closed = False
        self._reader = threading.Thread(target=self._read_loop, name="bidi-reader", daemon=True)
        self._reader.start()
        self.session_id: Optional[str] = None

    def _read_loop(self) -> None:
        try:
            while True:
                text = self._ws.recv_message()
                if text is None:
                    break
                try:
                    msg = json.loads(text)
                except ValueError:
                    continue
                if "id" in msg and msg.get("type") in ("success", "error"):
                    with self._lock:
                        waiter = self._waiting.get(msg["id"])
                    if waiter is not None:
                        waiter["answer"] = msg
                        waiter["done"].set()
                elif msg.get("type") == "event":
                    self.events.append(msg)
        except (OSError, ConnectionError, ValueError):
            pass  # the connection ended; `finally` marks the session closed and wakes every waiter, which is how callers learn it
        finally:
            self.closed = True
            with self._lock:
                for waiter in self._waiting.values():
                    waiter["done"].set()

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, *, timeout: float = 30.0) -> Dict:
        if self.closed:
            raise BidiError("unavailable", "The browser has closed.")
        with self._lock:
            self._next += 1
            cid = self._next
            waiter = {"done": threading.Event(), "answer": None}
            self._waiting[cid] = waiter
        try:
            self._ws.send(0x1, json.dumps({"id": cid, "method": method, "params": params or {}}).encode())
            if not waiter["done"].wait(timeout):
                raise BidiError("timeout", f"The browser did not answer {method} within {int(timeout)} s.")
        finally:
            with self._lock:
                self._waiting.pop(cid, None)
        answer = waiter["answer"]
        if answer is None:
            raise BidiError("unavailable", "The browser closed while answering.")
        if answer.get("type") == "error":
            raise BidiError(str(answer.get("error") or "error"), str(answer.get("message") or "")[:300])
        return answer.get("result") or {}

    def start(self, capabilities: Optional[Dict[str, Any]] = None) -> str:
        got = self.call("session.new", {"capabilities": capabilities or {}})
        self.session_id = got.get("sessionId")
        return self.session_id or ""

    def close(self) -> None:
        self.closed = True
        self._ws.close()


