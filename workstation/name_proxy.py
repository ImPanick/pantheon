# SPDX-License-Identifier: AGPL-3.0-or-later
"""`python3 -m workstation.name_proxy` — a person's names, as a forwarding proxy.
`P27-04`, `D-2026-10-24-03`.

A login may be for a name only the person's network knows (`grafana.lan`), or
one it does not know at all. Firefox has no setting that sends one name to one
address, and the workstation's `/etc/hosts` is every account's. So each person
who maps a name gets this: a small HTTP forwarding proxy **run as their own
account** (the daemon starts it with the account's `run_as` prefix, as it starts
their Firefox), so every connection it makes is theirs — to the kernel, to the
network gate in the container and to the account-uid rules on an Ubuntu
install alike. It cannot reach anything the person could not.

It answers two forms, enough for a browser and for curl, git and Python:

  * `CONNECT host:port` — a tunnel, to the mapped address when `host` is
    mapped, else to `host` as the network resolves it;
  * `GET http://host:port/path` (the absolute form) — the request is sent on to
    the same place in origin form, `Host` kept, `Connection: close`.

The map is a JSON file `{name: address}` the daemon writes; it is read again
whenever it changes. The listening port is written to `--port-file`.

Standard library only, like the rest of the package.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import select
import socket
import socketserver
import sys
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

BUFFER = 65536
CONNECT_TIMEOUT_S = 10.0
IDLE_S = 300.0
HEAD_MAX = 64 * 1024


class _Map:
    def __init__(self, path: Path):
        self.path = path
        self._mtime = None
        self._map: Dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self) -> Dict[str, str]:
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime_ns
            except OSError:
                return self._map
            if mtime != self._mtime:
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    self._map = {str(k).lower(): str(ipaddress.ip_address(v))
                                 for k, v in (data.get("map") or {}).items()}
                except (OSError, ValueError, AttributeError):
                    pass   # a half-written file: keep the last good map; the next request reads again
                self._mtime = mtime
            return self._map


def _split_host(hostport: str, default_port: int) -> Tuple[str, int]:
    if hostport.startswith("["):
        host, _, rest = hostport[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") else default_port
        return host, port
    host, sep, port = hostport.rpartition(":")
    if sep and port.isdigit():
        return host, int(port)
    return hostport, default_port


def _pipe(a: socket.socket, b: socket.socket) -> None:
    socks = [a, b]
    try:
        while True:
            r, _, x = select.select(socks, [], socks, IDLE_S)
            if x or not r:
                return
            for s in r:
                data = s.recv(BUFFER)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return   # either side closed: the tunnel is over


class _Handler(socketserver.BaseRequestHandler):
    names: _Map

    def _target(self, host: str, port: int) -> Tuple[str, int]:
        return self.names.get().get(host.lower(), host), port

    def _fail(self, code: int, why: str) -> None:
        body = (why + "\n").encode()
        try:
            self.request.sendall(f"HTTP/1.1 {code} {why}\r\nContent-Length: {len(body)}\r\n"
                                 "Connection: close\r\n\r\n".encode() + body)
        except OSError:
            pass   # the client went away first; nothing to tell it

    def handle(self) -> None:
        conn: socket.socket = self.request
        conn.settimeout(30)
        head = b""
        try:
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
                if len(head) > HEAD_MAX:
                    return self._fail(431, "Request Header Fields Too Large")
        except OSError:
            return
        head, _, rest = head.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            return self._fail(400, "Bad Request")
        if method.upper() == "CONNECT":
            host, port = _split_host(target, 443)
            addr = self._target(host, port)
            try:
                up = socket.create_connection(addr, timeout=CONNECT_TIMEOUT_S)
            except OSError as e:
                return self._fail(502, f"Bad Gateway ({e.__class__.__name__})")
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if rest:
                up.sendall(rest)
            conn.settimeout(None)
            up.settimeout(None)
            _pipe(conn, up)
            up.close()
            return
        if not target.lower().startswith("http://"):
            return self._fail(400, "Bad Request")
        hostport, slash, path = target[7:].partition("/")
        host, port = _split_host(hostport, 80)
        addr = self._target(host, port)
        out = [f"{method} {slash + path or '/'} {version}"]
        for line in lines[1:]:
            name = line.split(":", 1)[0].strip().lower()
            if name in ("proxy-connection", "proxy-authorization", "connection", "keep-alive"):
                continue
            out.append(line)
        out.append("Connection: close")
        try:
            up = socket.create_connection(addr, timeout=CONNECT_TIMEOUT_S)
        except OSError as e:
            return self._fail(502, f"Bad Gateway ({e.__class__.__name__})")
        up.sendall(("\r\n".join(out) + "\r\n\r\n").encode("latin-1") + rest)
        conn.settimeout(None)
        up.settimeout(None)
        _pipe(conn, up)
        up.close()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(map_path: Path, port_file: Optional[Path] = None, port: int = 0) -> _Server:
    handler = type("Handler", (_Handler,), {"names": _Map(map_path)})
    srv = _Server(("127.0.0.1", port), handler)
    if port_file is not None:
        tmp = port_file.with_suffix(".tmp")
        tmp.write_text(str(srv.server_address[1]), encoding="utf-8")
        os.replace(tmp, port_file)
    return srv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", required=True, type=Path)
    ap.add_argument("--port-file", required=True, type=Path)
    args = ap.parse_args(argv)
    srv = serve(args.map, args.port_file)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass   # stopped by the daemon
    return 0


if __name__ == "__main__":
    sys.exit(main())
