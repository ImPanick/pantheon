# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1565` — local Whisper asks the model-download gate before it fetches.

`services/stt/stt_service.py`'s `_get_whisper` called `WhisperModel(size)`,
which resolves a bare name like `base` through Hugging Face — fetching the
model the first time — with no question asked, while FastEmbed's construction
asks `ensure_fastembed_download_permitted` (`Law 16`, the owner's words: *"i
dont want things that'll may route to external services unless the user (or
sysadmin) explicitly links it"*).

Driven through the real route (`POST /api/stt/transcribe`) and the real
`STTService`, with the real `allow_model_download` switch read from settings.
The one stand-in is `faster_whisper` itself (not installed here, and it must
never download in a test): a fake whose `WhisperModel` does what the real one
does with a name that is not a folder — calls `download_model`, which fetches
unless `local_files_only` — and records every fetch.
"""

from __future__ import annotations

import os
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Hub:
    """What the fake Hugging Face cache holds, and every fetch asked of it."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.cached: set = set()
        self.fetched: list = []
        self.built: list = []

    def download_model(self, name, local_files_only=False, **_kw):
        if name in self.cached:
            path = self.tmp / f"whisper-{name}"
            path.mkdir(exist_ok=True)
            return str(path)
        if local_files_only:
            raise RuntimeError(f"{name} is not in the local cache")
        self.fetched.append(name)          # the network, in the real one
        self.cached.add(name)
        return self.download_model(name, local_files_only=True)


@pytest.fixture()
def hub(monkeypatch, tmp_path):
    h = _Hub(tmp_path)

    class WhisperModel:
        def __init__(self, model_size_or_path, device="cpu", compute_type="int8", **kw):
            # The real constructor: a folder is loaded as it is; anything else
            # is a name, resolved through `download_model`.
            if not os.path.isdir(model_size_or_path):
                model_size_or_path = h.download_model(
                    model_size_or_path, local_files_only=kw.get("local_files_only", False))
            h.built.append(model_size_or_path)

        def transcribe(self, path, **kw):
            seg = types.SimpleNamespace(text=" hello ")
            info = types.SimpleNamespace(language="en", language_probability=0.99)
            return [seg], info

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = WhisperModel
    utils = types.ModuleType("faster_whisper.utils")
    utils.download_model = h.download_model
    fw.utils = utils
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    # torch is only asked about CUDA; keep it out of the way.
    monkeypatch.setitem(sys.modules, "torch", None)
    return h


@pytest.fixture()
def settings(monkeypatch):
    """The real settings reader, answering a local-Whisper install."""
    import src.settings as S
    values = {"stt_enabled": True, "stt_provider": "local", "stt_model": "base",
              "stt_language": "", "allow_model_download": False}
    monkeypatch.setattr(S, "load_settings", lambda *a, **k: dict(S.DEFAULT_SETTINGS, **values))
    monkeypatch.delenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", raising=False)
    return values


def _client():
    from routes.stt_routes import setup_stt_routes
    from services.stt.stt_service import STTService
    service = STTService()
    app = FastAPI()
    app.include_router(setup_stt_routes(service))
    return TestClient(app), service


def _send(client):
    return client.post("/api/stt/transcribe", files={"file": ("a.webm", b"RIFF....", "audio/webm")})


def test_with_the_gate_off_and_no_model_transcription_refuses_with_a_sentence(hub, settings):
    client, _ = _client()
    r = _send(client)
    assert r.status_code == 503
    said = r.json()["detail"]["message"]
    assert "Whisper “base” model, which is not downloaded" in said
    assert "Download models from the internet" in said, "the sentence names the switch to turn on"
    assert hub.fetched == [], "nothing was fetched"
    assert hub.built == [], "no model was built"


def test_the_stats_say_why_local_speech_to_text_is_not_running(hub, settings):
    _, service = _client()
    stats = service.get_stats()
    assert stats["model_loaded"] is False
    assert "not downloaded" in stats["unavailable_reason"]
    assert hub.fetched == []


def test_a_model_already_on_disk_is_used_without_asking_the_network(hub, settings):
    hub.cached.add("base")
    client, _ = _client()
    r = _send(client)
    assert r.status_code == 200 and r.json() == {"text": "hello"}
    assert hub.fetched == []
    assert hub.built and os.path.isdir(hub.built[0]), "built from the cached folder, not the name"


def test_with_the_gate_on_the_model_is_fetched_once(hub, settings):
    settings["allow_model_download"] = True
    client, _ = _client()
    assert _send(client).status_code == 200
    assert hub.fetched == ["base"]


def test_turning_the_gate_on_after_a_refusal_is_enough(hub, settings):
    client, service = _client()
    assert _send(client).status_code == 503
    settings["allow_model_download"] = True
    r = _send(client)
    assert r.status_code == 200, r.text
    assert service.unavailable_reason() is None, "a refusal is not remembered"
    assert hub.fetched == ["base"]


def test_the_environment_variable_is_the_same_consent(hub, settings, monkeypatch):
    settings["allow_model_download"] = None          # nothing stored: the env decides
    monkeypatch.setenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", "1")
    client, _ = _client()
    assert _send(client).status_code == 200
    assert hub.fetched == ["base"]
