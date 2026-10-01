# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B991`. `B970` let Ollama and OpenRouter say whether a model can see; a
llama-server started with a projector says it on `GET /props`
(`modalities.vision`), and nothing asked it — so a vision model served under a
plain name lost its picture to a caption. `chat_helpers.model_supports_vision`
now asks a local llama-server's `/props`, and believes it only when the answer
carries `modalities.vision` and describes the model asked about.

Driven end to end like `B970`'s file: a fake llama-server answers at the httpx
transport under the real `paced_http` client and the real limiter call, read by
the real `llamacpp` reader and `vision_verdict`, through the real attachment
path (`ChatHandler.preprocess_message`) and the tool-picture path
(`tool_result_images.for_model`). Nothing reads a source file (`Law 20`).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from src import chat_helpers
from src.chat_helpers import is_vision_model, model_supports_vision
from tests.test_a_model_that_says_it_can_see_is_shown_the_picture import (
    _attach, _has_picture, _screen_message)

LLAMA = "http://localhost:8080/v1"          # llama-server's default port
TEXT_NAMED = "house-model-q4"               # the name list says text-only
VISION_NAMED = "gemma3-4b-it"               # the name list says vision


def _props(alias=None, path=None, modalities="absent"):
    """A `/props` answer as llama-server writes it (the fields the reader reads)."""
    out = {"default_generation_settings": {"n_ctx": 8192, "params": {"temperature": 0.8}},
           "total_slots": 1, "chat_template": "", "build_info": "b6000"}
    if alias is not None:
        out["model_alias"] = alias
    if path is not None:
        out["model_path"] = path
    if modalities != "absent":
        out["modalities"] = modalities
    return out


class _Net:
    def __init__(self):
        self.calls = []
        self.paced = []
        self.props = None          # the payload `/props` answers, or None for 404

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.host, request.url.port,
                           request.url.path, request.headers.get("authorization")))
        if request.method == "GET" and request.url.path == "/props" and self.props is not None:
            return httpx.Response(200, json=self.props)
        return httpx.Response(404, json={"error": "not here"})

    def asked(self, path):
        return [c for c in self.calls if c[3] == path]


@pytest.fixture
def net(monkeypatch):
    from src.rate_limiter import outbound

    n = _Net()
    real_init = httpx.Client.__init__

    def _init(self, *a, **k):
        k["transport"] = httpx.MockTransport(n.handle)
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.Client, "__init__", _init)
    monkeypatch.setattr(outbound, "acquire", lambda host, **k: n.paced.append(host) or 0.0)
    monkeypatch.setattr(chat_helpers, "_probe_auth_headers", lambda url: {})
    for cache in ("_ollama_show_cache", "_openrouter_catalogue_cache", "_lmstudio_models_cache",
                  "_llamacpp_props_cache"):
        monkeypatch.setattr(chat_helpers, cache, {}, raising=False)
    return n


def test_a_llamacpp_model_that_reports_vision_is_sent_the_attached_picture(net, tmp_path,
                                                                           monkeypatch):
    """The row's `Verify:`, first half, driven."""
    assert is_vision_model(TEXT_NAMED) is False, "premise: the name list calls it text-only"
    net.props = _props(alias=TEXT_NAMED, modalities={"vision": True, "audio": False})
    content, vl = _attach(tmp_path, monkeypatch, TEXT_NAMED, LLAMA)
    assert _has_picture(content), content
    assert vl == [], "a model that can see is not given a caption in its place"
    assert net.asked("/props") and set(net.paced) == {"localhost"}


def test_a_props_without_modalities_leaves_it_to_the_name_list(net, tmp_path, monkeypatch):
    """The row's `Verify:`, second half: a llama-server older than `modalities`
    takes no picture away from a model the name list calls vision, and gives
    none to one it calls text-only."""
    net.props = _props(alias=VISION_NAMED)
    content, vl = _attach(tmp_path, monkeypatch, VISION_NAMED, LLAMA)
    assert _has_picture(content) and vl == []
    net.props = _props(alias=TEXT_NAMED)
    assert model_supports_vision(TEXT_NAMED, LLAMA) is False
    assert len(net.asked("/props")) == 2


def test_a_llamacpp_model_that_reports_no_vision_is_given_words(net, tmp_path, monkeypatch):
    assert is_vision_model(VISION_NAMED) is True, "premise: the name list calls it vision"
    net.props = _props(path=f"/models/{VISION_NAMED}.gguf",
                       modalities={"vision": False, "audio": False})
    content, vl = _attach(tmp_path, monkeypatch, VISION_NAMED, LLAMA)
    assert not _has_picture(content)
    assert "a grey square" in content and len(vl) == 1


def test_a_tool_picture_follows_the_same_answer(net):
    from src.tool_result_images import NO_VISION_SENTENCE, for_model
    msg = _screen_message()
    net.props = _props(alias=TEXT_NAMED, modalities={"vision": True})
    assert asyncio.run(for_model([msg], TEXT_NAMED, LLAMA)) == [msg]
    net.props = _props(alias=VISION_NAMED, modalities={"vision": False})
    worded = asyncio.run(for_model([msg], VISION_NAMED, LLAMA))
    assert isinstance(worded[0]["content"], str) and NO_VISION_SENTENCE in worded[0]["content"]


@pytest.mark.parametrize("payload", [
    _props(alias="some-other-model", modalities={"vision": True}),     # a router's other model
    _props(path="/models/other.gguf", modalities={"vision": True}),
    _props(modalities={"vision": True}),                                # says not which model
    _props(alias=TEXT_NAMED, modalities={"vision": "yes"}),             # not a boolean
    _props(alias=TEXT_NAMED, modalities=["vision"]),
], ids=["other-alias", "other-path", "no-name", "vision-not-bool", "modalities-not-object"])
def test_an_answer_about_something_else_leaves_it_to_the_name(net, payload):
    net.props = payload
    assert model_supports_vision(TEXT_NAMED, LLAMA) is False
    assert chat_helpers.llamacpp_supports_vision(LLAMA, TEXT_NAMED) is None


@pytest.mark.parametrize("asked", [
    "/models/house-model-q4.gguf",          # the path, as /v1/models lists it
    "house-model-q4.gguf",                  # the file name
    "House-Model-Q4",                       # the file name without .gguf, any case
])
def test_the_model_path_names_the_model_however_it_is_written(net, asked):
    net.props = _props(path="/models/house-model-q4.gguf", modalities={"vision": True})
    assert model_supports_vision(asked, LLAMA) is True


def test_a_server_that_is_not_llamacpp_is_asked_once_a_minute(net):
    for _ in range(3):
        assert model_supports_vision(TEXT_NAMED, LLAMA) is False
        assert model_supports_vision(VISION_NAMED, LLAMA) is True
    assert len(net.asked("/props")) == 2, "one /props per model per minute, a 404 included"


def test_a_transport_failure_is_not_remembered(net, monkeypatch):
    from src import paced_http

    def down(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(paced_http, "get_sync", down)
    assert chat_helpers.llamacpp_supports_vision(LLAMA, TEXT_NAMED) is None
    assert chat_helpers._llamacpp_props_cache == {}


def test_only_a_local_server_of_the_right_kind_is_asked(net):
    """A cloud endpoint is asked nothing new (`Law 16`); a local endpoint the
    readers call Ollama, LM Studio, vLLM or SGLang has no `/props` to ask."""
    net.props = _props(alias=TEXT_NAMED, modalities={"vision": True})
    for url in ("https://api.example.com/v1", "https://openrouter.ai/api/v1",
                "http://localhost:11434/v1", "http://localhost:1234/v1",
                "http://gpu-box:8000/v1", "http://gpu-box:30000/v1"):
        model_supports_vision(TEXT_NAMED, url)
    assert net.asked("/props") == []
    assert model_supports_vision(TEXT_NAMED, "http://192.168.1.40:8080/v1") is True
    assert model_supports_vision(TEXT_NAMED, "http://gpu-box.local:9000/v1") is True
    assert [c[1] for c in net.asked("/props")] == ["192.168.1.40", "gpu-box.local"]


def test_the_endpoints_own_key_goes_with_the_probe(net, monkeypatch):
    monkeypatch.setattr(chat_helpers, "_probe_auth_headers",
                        lambda url: {"Authorization": "Bearer sk-llama"})
    net.props = _props(alias=TEXT_NAMED, modalities={"vision": True})
    assert model_supports_vision(TEXT_NAMED, LLAMA) is True
    assert net.asked("/props")[0][4] == "Bearer sk-llama"
