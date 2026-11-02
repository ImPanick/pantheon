# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1732` — the window of a model LM Studio or Ollama serves is the one it
LOADED the model with, read from the server's own API.

Measured from the owner's context wheel, 2026-11-01: gpt-oss-20b on LM Studio
read "The model's window is unknown, so the agent keeps 6K." LM Studio's
OpenAI-compatible `/v1/models` names no window, `gpt-oss` was in no table, and
nothing asked LM Studio's own list — which says what each loaded instance was
loaded with. Ollama's OpenAI door is the same, and `/api/ps` says it.

Driven against real HTTP servers on `127.0.0.1` through the real lookup and the
real `paced_http`; only the endpoint table is stood in for.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import src.model_context as model_context


def _serve(routes):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            body = routes.get(self.path)
            raw = json.dumps(body if body is not None else {"error": "not found"}).encode()
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture(autouse=True)
def _no_table(monkeypatch):
    monkeypatch.setattr(model_context, "_configured_endpoint_kind", lambda url: None)
    monkeypatch.setattr(model_context, "_endpoint_auth_headers", lambda url: {})
    monkeypatch.setattr(model_context, "_context_cache", {})
    monkeypatch.setattr(model_context, "_served_window_cache", {})
    import src.model_capability_readers as readers
    # The servers listen on a random port; say which kind each one is.
    yield readers


@pytest.fixture
def server():
    made = []

    def make(routes, vendor):
        srv = _serve(routes)
        made.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}/v1", vendor

    yield make
    for srv in made:
        srv.shutdown()
        srv.server_close()


def _as(monkeypatch, vendor):
    import src.model_capability_readers as readers
    monkeypatch.setattr(readers, "detect_vendor", lambda url, kind="": vendor)


_NATIVE = {"models": [{
    "type": "llm", "key": "openai/gpt-oss-20b", "display_name": "gpt-oss-20b",
    "architecture": "gpt-oss", "max_context_length": 131072,
    "loaded_instances": [{"id": "openai/gpt-oss-20b", "config": {"context_length": 16384}}]}]}
_OPENAI_LIST = {"object": "list", "data": [{"id": "openai/gpt-oss-20b", "object": "model"}]}


def test_lm_studio_says_what_it_loaded_gpt_oss_with(server, monkeypatch):
    url, vendor = server({"/api/v1/models": _NATIVE, "/v1/models": _OPENAI_LIST}, "lmstudio")
    _as(monkeypatch, vendor)
    assert model_context.get_context_length_basis(url, "openai/gpt-oss-20b") == (
        16384, True, model_context.BASIS_REPORTED)


def test_lm_studio_loaded_with_less_than_the_model_can_take_wins_over_the_table(server, monkeypatch):
    small = json.loads(json.dumps(_NATIVE))
    small["models"][0]["loaded_instances"][0]["config"]["context_length"] = 4096
    url, vendor = server({"/api/v1/models": small, "/v1/models": _OPENAI_LIST}, "lmstudio")
    _as(monkeypatch, vendor)
    assert model_context.get_context_length_known(url, "openai/gpt-oss-20b") == (4096, True)


def test_a_model_lm_studio_has_not_loaded_is_unknown_not_its_trained_window(server, monkeypatch):
    """LM Studio loads it on the next request with its own default (often
    4,096): the table's 131,072 is not what will be served."""
    idle = json.loads(json.dumps(_NATIVE))
    idle["models"][0]["loaded_instances"] = []
    url, vendor = server({"/api/v1/models": idle, "/v1/models": _OPENAI_LIST}, "lmstudio")
    _as(monkeypatch, vendor)
    assert model_context.get_context_length_known(url, "openai/gpt-oss-20b") == (
        model_context.DEFAULT_CONTEXT, False)


def test_an_older_lm_studio_says_it_on_api_v0(server, monkeypatch):
    v0 = {"object": "list", "data": [{"id": "openai/gpt-oss-20b", "type": "llm", "state": "loaded",
                                      "max_context_length": 131072, "loaded_context_length": 8192}]}
    url, vendor = server({"/api/v0/models": v0, "/v1/models": _OPENAI_LIST}, "lmstudio")
    _as(monkeypatch, vendor)
    assert model_context.get_context_length_known(url, "gpt-oss-20b") == (8192, True)


def test_ollamas_openai_door_is_answered_by_api_ps(server, monkeypatch):
    ps = {"models": [{"name": "gpt-oss:20b", "model": "gpt-oss:20b", "context_length": 32768}]}
    url, vendor = server({"/api/ps": ps, "/v1/models": {"data": [{"id": "gpt-oss:20b"}]}}, "ollama")
    _as(monkeypatch, vendor)
    assert model_context.get_context_length_known(url, "gpt-oss:20b") == (32768, True)


def test_lm_studio_on_a_port_of_its_own_is_asked_once_its_list_says_nothing(server, monkeypatch):
    url, vendor = server({"/api/v1/models": _NATIVE, "/v1/models": _OPENAI_LIST}, "generic_openai")
    _as(monkeypatch, vendor)
    assert model_context.get_context_length_known(url, "openai/gpt-oss-20b") == (16384, True)


def test_another_servers_api_paths_are_not_read_as_lm_studio(server, monkeypatch):
    """A generic server that answers every GET with an OpenAI list is not LM
    Studio; its own `/v1/models` decides, as before."""
    listing = {"data": [{"id": "local-model", "context_length": 12000}]}
    url, vendor = server({"/api/v1/models": listing, "/api/v0/models": listing,
                          "/v1/models": listing}, "generic_openai")
    _as(monkeypatch, vendor)
    assert model_context.get_context_length_known(url, "local-model") == (12000, True)
