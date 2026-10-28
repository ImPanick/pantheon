# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1608` — repeated window lookups to one local endpoint reuse one client.

`src.model_context` asks a local endpoint for its context window (llama.cpp's
`/slots`, then `/v1/models`) on every agent round, and never caches a local
answer — the server can restart with another `--max-model-len`. Each request
went through `paced_http.request_sync`, which built an `httpx.Client` and
closed it, and a client loads the CA store when it is made, once more for
each proxy the environment names: 78 requests, 156 TLS contexts in one profile.

Driven against a real HTTP server on `127.0.0.1`, through the real lookup and
the real `paced_http`; only the endpoint table is stood in for.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

import src.model_context as model_context
from src import paced_http


class _Server(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen: list = []
    delay = 0.0

    def do_GET(self):
        type(self).seen.append(self.path)
        if type(self).delay:
            time.sleep(type(self).delay)
        if self.path.endswith("/slots"):
            body = [{"id": 0, "n_ctx": 16384}]
        else:
            body = {"data": [{"id": "local-model", "context_length": 16384}]}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def _close_reused():
    getattr(paced_http, "close_reused", lambda: None)()


@pytest.fixture
def local_server(monkeypatch):
    _Server.seen = []
    _Server.delay = 0.0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(model_context, "_configured_endpoint_kind", lambda url: None)
    monkeypatch.setattr(model_context, "_endpoint_auth_headers", lambda url: {})
    monkeypatch.setattr(model_context, "_context_cache", {})
    _close_reused()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        _close_reused()


@pytest.fixture
def clients_built(monkeypatch):
    built = []
    real_init = httpx.Client.__init__

    def counting(self, *a, **k):
        built.append(k.get("mounts"))
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.Client, "__init__", counting)
    return built


def test_repeated_window_lookups_to_one_local_endpoint_reuse_one_client(local_server, clients_built):
    endpoint = f"{local_server}/v1/chat/completions"
    assert model_context.is_local_endpoint(endpoint), "premise: a local endpoint, never cached"
    for _ in range(5):
        assert model_context.get_context_length(endpoint, "local-model") == 16384
    assert _Server.seen.count("/slots") == 5, f"each lookup asks the server again: {_Server.seen}"
    assert len(clients_built) == 1, f"{len(clients_built)} clients for 5 lookups"


def test_a_reused_client_still_keeps_each_requests_timeout(local_server):
    _Server.delay = 0.5
    with pytest.raises(httpx.TimeoutException):
        paced_http.get_sync(f"{local_server}/slots", timeout=0.1, reuse=True)
    _Server.delay = 0.0
    assert paced_http.get_sync(f"{local_server}/slots", timeout=5, reuse=True).json()[0]["n_ctx"] == 16384


def test_a_caller_that_does_not_ask_to_reuse_gets_its_own_client(local_server, clients_built):
    """`Law 1`: every other caller of `request_sync` is answered as before."""
    for _ in range(2):
        paced_http.get_sync(f"{local_server}/slots", timeout=5)
    assert len(clients_built) == 2
    assert not getattr(paced_http, "_REUSED", None)
