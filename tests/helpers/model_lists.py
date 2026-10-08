# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local stand-ins for the model-list calls a provider answers (`Law 16`).

fx4-models (`D-2026-10-07-02` §1). Pantheon offers a model only when an
enumeration that succeeded named it — a local server's `/v1/models`, or a
provider's own list call on a key that answered (OpenAI `GET /v1/models` with
a bearer key, Anthropic `GET /v1/models` with `x-api-key` and
`anthropic-version`). These servers answer those calls on 127.0.0.1 so the
real listing code is driven without reaching anyone.

`ListServer(models)` is OpenAI-shaped: `GET /v1/models` → `{"object": "list",
"data": [{"id": …}]}`, and `POST /v1/chat/completions` answers one word so a
chat can be sent. `ListServer(models, anthropic_key="k")` is Anthropic-shaped:
the list is refused (401, Anthropic's error body) unless `x-api-key` is the key
and `anthropic-version` is sent, and the page carries Anthropic's paging
fields. `stop()` closes the port; `start()` opens the same port again, so an
endpoint that stopped answering can come back.

`point_hosts_at(monkeypatch, {"api.anthropic.com": port})` makes a provider's
own host resolve to 127.0.0.1 inside this process, so the provider-specific
branch (`_detect_provider` reads the host) is the one driven — still nothing
leaves the machine.
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional


class ListServer:
    def __init__(self, models: List[str], *, anthropic_key: Optional[str] = None,
                 port: int = 0, reply: str = "Hello from the fixture.", loading: bool = False):
        self.models = list(models)
        self.anthropic_key = anthropic_key
        # llama.cpp's answer while it loads a model: 503, "Loading model".
        self.loading = loading
        self.reply = reply
        self.asked: List[Dict[str, str]] = []
        self.port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self.start()

    # ── the far end ──────────────────────────────────────────────────────
    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                return

            def _send(self, code: int, body: dict) -> None:
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                server.asked.append({"path": self.path,
                                     "x-api-key": self.headers.get("x-api-key", ""),
                                     "authorization": self.headers.get("authorization", "")})
                if not self.path.rstrip("/").endswith("/models"):
                    return self._send(404, {"error": "not found"})
                if server.loading:
                    return self._send(503, {"error": {"message": "Loading model", "code": 503}})
                if server.anthropic_key is not None:
                    if (self.headers.get("x-api-key") != server.anthropic_key
                            or not self.headers.get("anthropic-version")):
                        return self._send(401, {"type": "error", "error": {
                            "type": "authentication_error", "message": "invalid x-api-key"}})
                    data = [{"type": "model", "id": m, "display_name": m,
                             "created_at": "2026-01-01T00:00:00Z"} for m in server.models]
                    return self._send(200, {"data": data, "has_more": False,
                                            "first_id": data[0]["id"] if data else None,
                                            "last_id": data[-1]["id"] if data else None})
                return self._send(200, {"object": "list", "data": [
                    {"id": m, "object": "model", "owned_by": "fixture"} for m in server.models]})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                server.asked.append({"path": self.path, "model": str(body.get("model", ""))})
                if body.get("stream"):
                    chunk = {"choices": [{"index": 0, "delta": {"content": server.reply},
                                          "finish_reason": None}], "model": body.get("model")}
                    raw = (f"data: {json.dumps(chunk)}\n\n"
                           "data: " + json.dumps({"choices": [{"index": 0, "delta": {},
                                                               "finish_reason": "stop"}]})
                           + "\n\ndata: [DONE]\n\n").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                return self._send(200, {"choices": [{"index": 0, "message": {
                    "role": "assistant", "content": server.reply}, "finish_reason": "stop"}],
                    "model": body.get("model")})

        return Handler

    def start(self) -> "ListServer":
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), self._handler())
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"


def closed_port() -> int:
    """A port nothing listens on (bound, then released)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def point_hosts_at(monkeypatch, hosts: Dict[str, int]) -> None:
    """Resolve each named host to 127.0.0.1 in this process. The port stays
    the URL's own, so a base like `http://api.anthropic.com:<port>` reaches the
    fixture listening there."""
    real = socket.getaddrinfo

    def getaddrinfo(host, port, *a, **k):
        if isinstance(host, str) and host.lower() in hosts:
            return real("127.0.0.1", port, *a, **k)
        return real(host, port, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
              "NO_PROXY", "no_proxy")


def no_proxy(monkeypatch) -> None:
    """A request goes straight to the fixture (this sandbox sets a proxy)."""
    for var in PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
