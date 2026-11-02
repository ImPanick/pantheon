# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1717` — Piper, the voice this server speaks with on its own processor,
asks the model-download gate before it fetches a voice, and speaks with the
voice the image carries without asking anything.

A voice chat needs a voice that works where Pantheon runs: Kokoro needs a CUDA
GPU and cannot install on the image's Python at all, so the image carries Piper
and one voice, `en_US-ljspeech-medium`, baked into `PANTHEON_SEED_MODELS/piper`
by `docker/bake_piper_voice.py`. Any other voice is fetched from
`rhasspy/piper-voices` on Hugging Face only through `ensure_piper_voice`, and
only once someone allowed it — one consent (`model_download_allowed`) for
every model Pantheon might fetch (`Law 16`).

Driven (`Law 20`) through the real route (`POST /api/tts/synthesize`), the real
`TTSService` and the real switch read from settings. The stand-ins are the
network (`huggingface_hub.hf_hub_download`, which writes small files where the
real one would and records each fetch) and Piper itself (no voice can be
fetched here to run the real one), whose `PiperVoice` records what it was
loaded from and asked to say.
"""
from __future__ import annotations

import importlib.util
import io
import re
import sys
import types
import wave
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
VOICE = "en_US-ljspeech-medium"


class _Hub:
    """Hugging Face, as far as a voice fetch reaches it."""

    def __init__(self):
        self.fetched: list = []
        self.fail: set = set()

    def hf_hub_download(self, repo_id, filename, local_dir=None, **_kw):
        self.fetched.append((repo_id, filename))
        if any(filename.endswith(f) for f in self.fail):
            raise OSError(f"404 for {filename}")
        path = Path(local_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}" if filename.endswith(".json") else b"onnx-bytes")
        return str(path)


class _Piper:
    """`piper`'s `PiperVoice` and `SynthesisConfig`, keeping what they were asked."""

    def __init__(self):
        self.loaded: list = []
        self.said: list = []
        outer = self

        class Chunk:
            sample_rate, sample_width, sample_channels = 22050, 2, 1
            audio_int16_bytes = b"\x00\x01" * 64

        class PiperVoice:
            def __init__(self, path):
                self.config = types.SimpleNamespace(length_scale=1.0)
                self.path = path

            @classmethod
            def load(cls, path, download_dir=None):
                outer.loaded.append((Path(path).name, download_dir))
                return cls(path)

            def synthesize(self, text, syn_config=None):
                outer.said.append((Path(self.path).name, text, syn_config.length_scale))
                yield Chunk()

        class SynthesisConfig:
            def __init__(self, length_scale=None, **_kw):
                self.length_scale = length_scale

        self.module = types.ModuleType("piper")
        self.module.PiperVoice = PiperVoice
        self.module.SynthesisConfig = SynthesisConfig


@pytest.fixture()
def world(monkeypatch, tmp_path):
    import huggingface_hub
    import src.constants as constants
    import src.settings as S
    from src.rate_limiter import outbound

    hub = _Hub()
    piper = _Piper()
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", hub.hf_hub_download)
    monkeypatch.setitem(sys.modules, "piper", piper.module)
    monkeypatch.setattr(outbound, "acquire", lambda host, **k: 0.0)
    data = tmp_path / "data"
    seed = tmp_path / "seed"
    monkeypatch.setattr(constants, "DATA_DIR", str(data))
    monkeypatch.setenv("PANTHEON_SEED_MODELS", str(seed))
    monkeypatch.delenv("PANTHEON_ALLOW_MODEL_DOWNLOAD", raising=False)
    values = {"tts_enabled": True, "tts_provider": "piper", "tts_voice": "alloy", "tts_speed": "1",
              "allow_model_download": False}
    monkeypatch.setattr(S, "load_settings", lambda *a, **k: dict(S.DEFAULT_SETTINGS, **values))
    return types.SimpleNamespace(hub=hub, piper=piper, data=data, seed=seed, settings=values,
                                 fetched=data / "models" / "piper", tmp=tmp_path)


def _client(tmp):
    from routes.tts_routes import setup_tts_routes
    from services.tts.tts_service import TTSService
    service = TTSService(cache_dir=str(tmp / "tts-cache"))
    app = FastAPI()
    app.include_router(setup_tts_routes(service))
    return TestClient(app), service


def _bake(folder: Path, voice: str = VOICE) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{voice}.onnx").write_bytes(b"onnx-bytes")
    (folder / f"{voice}.onnx.json").write_text("{}")


def _say(client, text="Hello there."):
    return client.post("/api/tts/synthesize", json={"text": text, "format": "audio"})


def test_with_the_gate_off_a_voice_not_on_disk_is_refused_with_a_sentence(world):
    client, service = _client(world.tmp)
    r = _say(client)
    assert r.status_code == 503
    said = r.json()["detail"]["message"]
    assert f"the Piper voice “{VOICE}”, which is not downloaded" in said
    assert "Download models from the internet" in said, "the sentence names the switch to turn on"
    assert str(world.fetched) in said, "and the folder a voice can be put in by hand"
    assert world.hub.fetched == [], "nothing was fetched"
    assert world.piper.loaded == [], "no voice was loaded"
    stats = service.get_stats()
    assert stats["available"] is False and stats["unavailable_reason"] == said


def test_the_voice_the_image_carries_speaks_without_asking(world):
    _bake(world.seed / "piper")
    client, service = _client(world.tmp)
    r = _say(client)
    assert r.status_code == 200, r.text
    with wave.open(io.BytesIO(r.content)) as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 22050)
    assert world.hub.fetched == []
    assert world.piper.loaded == [(f"{VOICE}.onnx", str(world.seed / "piper"))]
    stats = service.get_stats()
    assert stats["available"] is True and stats["voice"] == VOICE
    assert stats["voices"] == [VOICE]
    assert not (world.data / "models" / "piper" / f"{VOICE}.onnx").exists(), "read where it is, never copied"


def test_with_the_gate_on_a_voice_is_fetched_once_model_then_config(world):
    world.settings["allow_model_download"] = True
    client, _ = _client(world.tmp)
    assert _say(client).status_code == 200
    assert _say(client, "And again.").status_code == 200
    prefix = f"en/en_US/ljspeech/medium/{VOICE}"
    assert world.hub.fetched == [("rhasspy/piper-voices", prefix + ".onnx"),
                                 ("rhasspy/piper-voices", prefix + ".onnx.json")]
    assert sorted(p.name for p in world.fetched.iterdir()) == [f"{VOICE}.onnx", f"{VOICE}.onnx.json"], \
        "the scratch folder is gone and the voice is whole"


def test_turning_the_gate_on_after_a_refusal_is_enough(world):
    client, service = _client(world.tmp)
    assert _say(client).status_code == 503
    world.settings["allow_model_download"] = True
    assert _say(client).status_code == 200
    assert service.unavailable_reason() is None, "a refusal is not remembered"


def test_another_providers_voice_name_speaks_with_the_voice_that_is_there(world):
    """The one voice setting is shared: `alloy` is the endpoint's, `af_heart`
    Kokoro's. Piper then speaks with its default, or with the one voice a
    person put in the folder when the default is not there."""
    from services.tts.tts_service import piper_voice_name
    assert piper_voice_name("alloy") == VOICE
    _bake(world.fetched, "de_DE-thorsten-high")
    assert piper_voice_name("af_heart") == "de_DE-thorsten-high"
    assert piper_voice_name("en_GB-alan-low") == "en_GB-alan-low", "a Piper name is kept as it is"
    client, _ = _client(world.tmp)
    assert _say(client).status_code == 200
    assert world.piper.said[-1][0] == "de_DE-thorsten-high.onnx"


def test_the_speed_chosen_is_piper_s_length_scale_turned_over(world):
    _bake(world.seed / "piper")
    world.settings["tts_speed"] = "1.25"
    client, _ = _client(world.tmp)
    assert _say(client).status_code == 200
    assert world.piper.said[-1][2] == pytest.approx(0.8)


def test_a_voice_that_will_not_speak_says_why(world, monkeypatch):
    """The voice call shows the server's sentence instead of going quiet;
    the route said *Synthesis failed* and nothing else."""
    _bake(world.seed / "piper")
    client, service = _client(world.tmp)

    def broken(self, text, syn_config=None):
        raise RuntimeError("ONNXRuntimeError: invalid input 'input'")
        yield  # noqa: unreachable — a generator, as Piper's is

    monkeypatch.setattr(world.piper.module.PiperVoice, "synthesize", broken)
    r = _say(client)
    assert r.status_code == 500
    assert r.json()["detail"]["message"] == (
        "Piper could not speak it (ONNXRuntimeError: invalid input 'input'). "
        "The server log has the detail.")
    assert service.failure_reason() == r.json()["detail"]["message"]


def test_the_status_loads_the_voice_before_the_first_sentence(world):
    """A voice takes seconds to load and a fifth of a second a sentence after:
    the status read Settings and a starting call make loads it in the
    background, so the first reply is not the one that waits."""
    import time
    _bake(world.seed / "piper")
    client, service = _client(world.tmp)
    assert client.get("/api/tts/stats").json()["voice_loaded"] is False
    deadline = time.monotonic() + 10
    while not service._piper.loaded(VOICE) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert client.get("/api/tts/stats").json()["voice_loaded"] is True
    assert _say(client).status_code == 200
    assert world.piper.loaded == [(f"{VOICE}.onnx", str(world.seed / "piper"))], "loaded once"
    assert service.warm() is False, "nothing left to warm"


def test_trying_voices_keeps_two_in_memory(world):
    """Someone listening through voices in Settings: each is loaded once, and
    the oldest is let go when a third is asked for."""
    voices = (VOICE, "en_GB-alan-low", "de_DE-thorsten-high")
    for v in voices:
        _bake(world.seed / "piper", v)
    client, service = _client(world.tmp)
    for v in voices + (voices[2],):
        world.settings["tts_voice"] = v
        assert _say(client, f"This is {v}.").status_code == 200
    assert sorted(service._piper._voices) == sorted(voices[1:])
    assert [name for name, _ in world.piper.loaded] == [f"{v}.onnx" for v in voices]


@pytest.mark.parametrize("torch, said", [
    (None, "Kokoro is not installed on this server; it needs PyTorch with CUDA and Python "
           "below 3.13 (requirements-optional.txt). Piper speaks on the CPU."),
    (types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False)),
     "Kokoro needs a CUDA GPU, and this server has none it can use. Piper speaks on the CPU."),
])
def test_kokoro_that_cannot_start_says_why_and_names_the_voice_that_can(world, monkeypatch, torch, said):
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "kokoro", types.SimpleNamespace(KPipeline=object))
    world.settings["tts_provider"] = "local"
    client, service = _client(world.tmp)
    assert client.get("/api/tts/stats").json()["unavailable_reason"] == said
    r = _say(client)
    assert r.status_code == 503 and r.json()["detail"]["message"] == said


def test_a_voice_name_that_is_not_one_is_never_a_path(world):
    """A stored voice reaches the file system only as a Piper name: nothing
    with a separator or a dot in it is looked for or fetched."""
    from services.tts.tts_service import ensure_piper_voice, find_piper_voice
    for bad in ("../../etc/passwd", "en_US-ljspeech-medium/../x", "a.onnx", ""):
        assert find_piper_voice(bad) is None
        with pytest.raises(ValueError):
            ensure_piper_voice(bad)
    assert world.hub.fetched == []


# ── the bake ─────────────────────────────────────────────────────────────────

def _bake_script():
    spec = importlib.util.spec_from_file_location("_bake_piper_voice", ROOT / "docker" / "bake_piper_voice.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_image_bakes_the_voice_with_its_config_and_card(tmp_path):
    hub = _Hub()
    written = _bake_script().bake(VOICE, str(tmp_path / "piper"),
                                  fetch=lambda r, f, d: hub.hf_hub_download(r, f, local_dir=d))
    assert written == [f"{VOICE}.onnx", f"{VOICE}.onnx.json", f"{VOICE}.MODEL_CARD"]
    assert sorted(p.name for p in (tmp_path / "piper").iterdir()) == sorted(written)
    assert [f for _, f in hub.fetched] == [f"en/en_US/ljspeech/medium/{VOICE}.onnx",
                                           f"en/en_US/ljspeech/medium/{VOICE}.onnx.json",
                                           "en/en_US/ljspeech/medium/MODEL_CARD"]


def test_a_voice_without_a_card_is_still_baked_and_a_bad_name_is_not(tmp_path):
    hub = _Hub()
    hub.fail.add("MODEL_CARD")
    bake = _bake_script().bake
    fetch = lambda r, f, d: hub.hf_hub_download(r, f, local_dir=d)  # noqa: E731
    assert bake(VOICE, str(tmp_path / "a"), fetch=fetch) == [f"{VOICE}.onnx", f"{VOICE}.onnx.json"]
    with pytest.raises(ValueError):
        bake("../voice", str(tmp_path / "b"), fetch=fetch)


def test_the_bake_and_the_runtime_agree_on_where_a_voice_lives():
    """The two read one layout: the bake's name pattern is the service's."""
    from services.tts import tts_service
    assert _bake_script().VOICE.pattern == tts_service._PIPER_VOICE.pattern
    assert _bake_script().REPO == tts_service.PIPER_VOICE_REPO


def test_only_the_gate_fetches_a_voice():
    """`Law 16`'s one door: Piper's voice repository is reached from
    `ensure_piper_voice` at runtime and from the image's bake, nowhere else."""
    hits = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "node_modules/", ".git/", "venv/", ".venv/")) or "/site-packages/" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"piper-voices|PIPER_VOICE_REPO|piper\.download_voices|download_voice\(", text):
            hits.append(rel)
    assert sorted(hits) == ["docker/bake_piper_voice.py", "services/tts/tts_service.py"], hits
    service = (ROOT / "services" / "tts" / "tts_service.py").read_text(encoding="utf-8")
    assert service.count("hf_hub_download") == 2, "imported and called once, inside ensure_piper_voice"
