# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B970`. The model-capability readers had no production caller: "can this
model see" was LM Studio's answer, then a name list, so an Ollama model that
reports `vision` or an OpenRouter model whose catalogue lists image input
decided nothing. `chat_helpers.model_supports_vision` — the one question a
person's attachment and a tool's picture both ask — now reads Ollama's
`/api/show` and OpenRouter's catalogue through those readers.

Driven end to end: a fake Ollama and a fake OpenRouter answer at the httpx
transport, under the real `paced_http` client, the real limiter call, the real
readers and the real attachment path (`ChatHandler.preprocess_message`) and
tool-picture path (`tool_result_images.for_model`). Nothing reads a source
file (`Law 20`).
"""
from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from src import chat_helpers
from src.chat_helpers import is_vision_model, model_supports_vision

OLLAMA = "http://localhost:11434/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
TEXT_NAMED = "mistral-nemo-custom:12b"     # the name list says text-only
VISION_NAMED = "gemma3:1b"                 # the name list says vision; it is text-only
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

CATALOGUE = {"data": [
    {"id": "acme/plain-chat", "name": "Acme Plain",
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
    {"id": "openai/gpt-4o-textonly", "name": "Named like vision",
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
    {"id": "meta/llama-x", "name": "Llama X",
     "architecture": {"modality": "text+image->text"}},
]}


class _Net:
    """What reached the network, and what answered."""

    def __init__(self):
        self.calls = []
        self.paced = []
        self.show = {}            # model -> /api/show payload (or None for 404)
        self.catalogue = CATALOGUE
        self.catalogue_status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.host, request.url.path,
                           request.headers.get("authorization")))
        if request.method == "POST" and request.url.path == "/api/show":
            model = json.loads(request.content or b"{}").get("model")
            payload = self.show.get(model)
            return httpx.Response(200, json=payload) if payload is not None else httpx.Response(404)
        if request.url.host == "openrouter.ai" and request.url.path == "/api/v1/models":
            return httpx.Response(self.catalogue_status, json=self.catalogue)
        return httpx.Response(404, json={"error": "not here"})

    def asked(self, path):
        return [c for c in self.calls if c[2] == path]


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
    monkeypatch.setattr(chat_helpers, "_ollama_show_cache", {}, raising=False)
    monkeypatch.setattr(chat_helpers, "_openrouter_catalogue_cache", {}, raising=False)
    monkeypatch.setattr(chat_helpers, "_lmstudio_models_cache", {})
    return n


def _show(*caps):
    return {"modelfile": "", "details": {"family": "x"}, "capabilities": list(caps)}


# ── the attachment: a person's picture ──────────────────────────────────────

class _Uploads:
    def __init__(self, path):
        self.path = path

    def resolve_upload(self, att_id, owner=None):
        return {"id": att_id, "name": "shot.png", "path": str(self.path), "mime": "image/png", "size": 68}

    def _inside_upload_dir(self, path):
        return True

    def is_image_file(self, name, mime=""):
        return True

    def is_audio_file(self, name, mime=""):
        return False

    def is_document_file(self, name, mime=""):
        return False


def _attach(tmp_path, monkeypatch, model, url):
    """`preprocess_message` with one PNG attached; returns `(user_content, vl_calls)`."""
    from src.chat_handler import ChatHandler
    import src.chat_handler as ch
    import src.settings as S

    sp = tmp_path / "settings.json"
    sp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    S._invalidate_caches()
    monkeypatch.setattr(ch, "UPLOAD_DIR", str(tmp_path / "uploads"))   # the caption cache
    vl = []
    monkeypatch.setattr(ch, "analyze_image_with_vl_result",
                        lambda path, owner=None: vl.append(path) or {"text": "a grey square", "model": "vl"})
    img = tmp_path / "shot.png"
    img.write_bytes(PNG)
    handler = ChatHandler(session_manager=None, memory_manager=None, chat_processor=None,
                          research_handler=None, preset_manager=None, upload_handler=_Uploads(img))
    sess = SimpleNamespace(model=model, endpoint_url=url, owner="", id="s1")
    _e, user_content, _t, _y, _m = asyncio.run(handler.preprocess_message(
        "what is this?", ["att-1"], sess, auto_opened_docs=[], allow_tool_preprocessing=True))
    S._invalidate_caches()
    return user_content, vl


def _has_picture(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(p, dict) and p.get("type") == "image_url" for p in content)


def test_an_ollama_model_that_reports_vision_is_sent_the_attached_picture(net, tmp_path, monkeypatch):
    """The row's `Verify:`, driven."""
    assert is_vision_model(TEXT_NAMED) is False, "premise: the name list calls it text-only"
    net.show[TEXT_NAMED] = _show("completion", "vision")
    content, vl = _attach(tmp_path, monkeypatch, TEXT_NAMED, OLLAMA)
    assert _has_picture(content), content
    assert vl == [], "a model that can see is not given a caption in its place"
    assert net.asked("/api/show") and net.paced and set(net.paced) == {"localhost"}


def test_an_ollama_model_that_reports_no_vision_is_given_words(net, tmp_path, monkeypatch):
    assert is_vision_model(VISION_NAMED) is True, "premise: the name list calls it vision"
    net.show[VISION_NAMED] = _show("completion", "tools")
    content, vl = _attach(tmp_path, monkeypatch, VISION_NAMED, OLLAMA)
    assert not _has_picture(content)
    assert "a grey square" in content and len(vl) == 1


# ── the tool picture: the same question ─────────────────────────────────────

def _screen_message():
    from src.tool_result_images import images_message
    data = base64.b64encode(PNG).decode()
    return images_message([{"tool_name": "computer", "content": "{}",
                            "result": {"images": [{"mimeType": "image/png", "data": data}],
                                       "screenshot_caption": "Screen after click"}}])


def test_a_tool_picture_follows_the_same_answer(net):
    from src.tool_result_images import NO_VISION_SENTENCE, for_model
    net.show[TEXT_NAMED] = _show("completion", "vision")
    net.show[VISION_NAMED] = _show("completion")
    msg = _screen_message()
    kept = asyncio.run(for_model([msg], TEXT_NAMED, OLLAMA))
    assert kept == [msg]
    worded = asyncio.run(for_model([msg], VISION_NAMED, OLLAMA))
    assert isinstance(worded[0]["content"], str) and NO_VISION_SENTENCE in worded[0]["content"]


# ── what Ollama says, and when it says nothing ──────────────────────────────

def test_an_ollama_that_lists_no_capabilities_leaves_it_to_the_name(net):
    net.show[TEXT_NAMED] = {"modelfile": "", "details": {}}          # Ollama before `capabilities`
    net.show[VISION_NAMED] = {"modelfile": "", "details": {}}
    assert model_supports_vision(TEXT_NAMED, OLLAMA) is False
    assert model_supports_vision(VISION_NAMED, OLLAMA) is True


def test_a_model_ollama_does_not_know_leaves_it_to_the_name(net):
    assert model_supports_vision("llava:7b", OLLAMA) is True
    assert model_supports_vision(TEXT_NAMED, OLLAMA) is False
    assert len(net.asked("/api/show")) == 2


def test_ollama_is_asked_once_a_minute_per_model(net):
    net.show[TEXT_NAMED] = _show("completion", "vision")
    for _ in range(3):
        assert model_supports_vision(TEXT_NAMED, OLLAMA) is True
    assert len(net.asked("/api/show")) == 1


# ── OpenRouter's catalogue ──────────────────────────────────────────────────

def test_openrouter_modalities_decide(net):
    assert is_vision_model("acme/plain-chat") is False
    assert is_vision_model("openai/gpt-4o-textonly") is True
    assert model_supports_vision("acme/plain-chat", OPENROUTER) is True
    assert model_supports_vision("openai/gpt-4o-textonly", OPENROUTER) is False
    assert model_supports_vision("meta/llama-x", OPENROUTER) is True          # `modality` arrow form
    assert model_supports_vision("acme/plain-chat:free", OPENROUTER) is True  # variant → base entry
    assert model_supports_vision("acme/unlisted", OPENROUTER) is False        # not listed → the name
    fetched = net.asked("/api/v1/models")
    assert len(fetched) == 1, "one catalogue answers every question for an hour"
    assert fetched[0][3] is None, "the public catalogue is fetched without the person's key"
    assert net.paced == ["openrouter.ai"]


def test_an_unreachable_catalogue_falls_back_and_is_not_asked_per_picture(net):
    net.catalogue_status = 503
    assert model_supports_vision("acme/plain-chat", OPENROUTER) is False      # the name list
    assert model_supports_vision("openai/gpt-4o-textonly", OPENROUTER) is True
    assert len(net.asked("/api/v1/models")) == 1


def test_no_other_endpoint_is_asked_anything_new(net):
    """Only an endpoint the readers call Ollama or OpenRouter is asked; a cloud
    endpoint is asked nothing at all, as before."""
    assert model_supports_vision("gpt-4o", "https://api.openai.com/v1") is True
    assert model_supports_vision(TEXT_NAMED, "https://api.example.com/v1") is False
    assert net.calls == []
    model_supports_vision(TEXT_NAMED, "http://gpu-box:8000/v1")        # local: LM Studio's probe only
    assert net.calls and all(c[:3] == ("GET", "gpu-box", "/api/v1/models") for c in net.calls)


# ── the one reading ─────────────────────────────────────────────────────────

def test_vision_verdict_is_yes_no_or_nothing_said():
    from src import model_capabilities as mc
    from src.model_capability_readers import ollama, openrouter

    yes = ollama.record_from_show_payload("m", _show("completion", "vision")).capability
    no = ollama.record_from_show_payload("m", _show("completion")).capability
    silent = ollama.record_from_show_payload("m", {"capabilities": []}).capability
    assert mc.vision_verdict(yes) is True
    assert mc.vision_verdict(no) is False
    assert mc.vision_verdict(silent) is None
    rec = openrouter.records_from_payload(CATALOGUE)[0]
    assert mc.vision_verdict(rec.capability) is True
    # Image input decides on its own, whatever a reader named the capability.
    takes_pictures = mc.ModelCapability.build(
        family=mc.FAMILY_CHAT, input_modalities=("text", "image"), output_modalities=("text",),
        capabilities=(), source=mc.SOURCE_PROVIDER_READER, confidence=mc.CONFIDENCE_PROVIDER_REPORTED)
    assert mc.vision_verdict(takes_pictures) is True
