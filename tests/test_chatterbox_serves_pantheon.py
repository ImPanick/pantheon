# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1729` — Chatterbox Turbo speaks for Pantheon from its own container on a
server with an NVIDIA GPU.

The owner chose *"Kokoro, plus Chatterbox for a GPU"* (2026-11-01). Chatterbox
needs PyTorch on CUDA, so it runs beside Pantheon (`voice/chatterbox/`),
started by the NVIDIA overlay's `chatterbox` profile, and Pantheon speaks to
it over the compose network (`services/tts/chatterbox_client.py`).

Driven (`Law 20`) through the sidecar's real routes and Pantheon's real
client over HTTP (`tests/helpers/chatterbox_sidecar.py`). The stand-in is the
model alone: the real one needs a GPU and weights CI has neither of.
"""
from __future__ import annotations

import re
import sys
import time
import types
from pathlib import Path

import pytest

from tests.helpers.chatterbox_sidecar import (
    URL, Clock, FakeTurbo, Sidecar, blocked_loader, recording, server_module, wav_info,
)

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "voice" / "chatterbox"


@pytest.fixture()
def sidecar(tmp_path):
    return Sidecar(tmp_path / "voices").wait_loaded()


def _say(sidecar, text, **kw):
    return sidecar.http.post("/v1/audio/speech", json={"input": text, **kw})


# ── The sidecar ──


def test_it_says_it_is_loading_and_then_that_it_is_ready_on_the_gpu(tmp_path):
    loader, release = blocked_loader(FakeTurbo())
    side = Sidecar(tmp_path / "voices", loader=loader)
    health = side.http.get("/health").json()
    assert health == {"ok": False, "reason": (
        "Chatterbox is loading its model onto the GPU (about half a minute after it starts)."),
        "device": "", "voices": []}
    assert _say(side, "Hello.").status_code == 503
    assert _say(side, "Hello.").json()["detail"] == health["reason"]
    assert side.http.get("/v1/audio/voices").json() == {"voices": []}
    release.set()
    side.wait_loaded()
    assert side.http.get("/health").json() == {
        "ok": True, "reason": None, "device": "cuda (Stand-in GPU)",
        "voices": [{"id": "default", "name": "Chatterbox"}]}


def test_a_model_that_will_not_load_says_why_in_its_health(tmp_path):
    def broken(device):
        raise RuntimeError("CUDA out of memory.\nTried to allocate 2.00 GiB")
    side = Sidecar(tmp_path / "voices", loader=broken).wait_loaded()
    assert side.http.get("/health").json()["reason"] == "Chatterbox would not start: CUDA out of memory."


def test_with_no_gpu_visible_it_says_how_to_check_the_toolkit_or_run_on_the_processor(monkeypatch):
    mod = server_module()
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    monkeypatch.setitem(sys.modules, "torch", torch)
    with pytest.raises(RuntimeError) as refused:
        mod.load_model("cuda")
    said = str(refused.value)
    assert "No NVIDIA GPU is visible to the Chatterbox container" in said
    assert "scripts/check-docker-gpu.sh" in said and "CHATTERBOX_DEVICE=cpu" in said
    assert (ROOT / "scripts" / "check-docker-gpu.sh").is_file(), "the script it names is there"
    monkeypatch.delenv("CHATTERBOX_DEVICE", raising=False)
    assert mod.device_wanted() == "cuda", "the processor must be asked for by name"
    monkeypatch.setenv("CHATTERBOX_DEVICE", " CPU ")
    assert mod.device_wanted() == "cpu"


def test_a_sentence_comes_back_as_a_wav_at_the_models_own_rate(sidecar):
    r = _say(sidecar, "Hello there.")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    wav = wav_info(r.content)
    assert (wav["rate"], wav["channels"], wav["width"]) == (24000, 1, 2)
    assert wav["frames"] == len("Hello there.") * 100
    assert set(wav["samples"].tolist()) == {int(0.25 * 32767)}
    assert sidecar.model.generated == [("Hello there.", "built-in")]


def test_a_long_reply_is_said_in_pieces_cut_between_sentences(sidecar):
    chunks = sidecar.module.chunks
    sentence = "This sentence is about fifty characters long, ok."
    text = "  ".join([sentence] * 12)
    pieces = chunks(text)
    assert all(len(p) <= 280 for p in pieces) and len(pieces) == 3, [len(p) for p in pieces]
    assert all(p.endswith(".") for p in pieces), "cut between sentences"
    assert " ".join(pieces) == re.sub(r"\s+", " ", text).strip(), "nothing lost, nothing doubled"
    one = "word " * 100   # one "sentence" longer than a piece: cut between words
    assert all(len(p) <= 280 and not p.startswith(" ") for p in chunks(one))
    assert " ".join(chunks(one)).split() == one.split()
    assert chunks("   ") == [] and chunks(None) == []

    wav = wav_info(_say(sidecar, text).content)
    said = [t for t, _ in sidecar.model.generated]
    assert said == pieces
    gap = int(24000 * 0.12)
    assert wav["frames"] == sum(len(p) * 100 for p in pieces) + gap * (len(pieces) - 1)


def test_a_voice_in_the_folder_is_learnt_once_and_spoken_in(tmp_path):
    voices = tmp_path / "voices"
    recording(voices / "Grandad.wav")
    recording(voices / "Narrator.flac")          # a FLAC is as good (the name is what is read)
    recording(voices / "default.wav")            # cannot take the built-in voice's name
    recording(voices / ".hidden.wav")            # nor be a hidden file
    (voices / "notes.txt").write_text("not a recording")
    side = Sidecar(voices).wait_loaded()
    assert side.http.get("/v1/audio/voices").json()["voices"] == [
        {"id": "default", "name": "Chatterbox"}, {"id": "Grandad", "name": "Grandad"},
        {"id": "Narrator", "name": "Narrator"}]
    assert _say(side, "One.", voice="Grandad").status_code == 200
    assert _say(side, "Two.", voice="Grandad").status_code == 200
    assert side.model.prepared == ["Grandad.wav"], "a recording is learnt once and kept"
    _say(side, "Three.")
    _say(side, "Four.", voice="nobody")
    assert side.model.generated == [("One.", "conds:Grandad"), ("Two.", "conds:Grandad"),
                                    ("Three.", "built-in"), ("Four.", "built-in")]


def test_a_recording_it_cannot_learn_from_is_refused_with_why(tmp_path):
    voices = tmp_path / "voices"
    recording(voices / "Short.wav", seconds=2)
    side = Sidecar(voices).wait_loaded()

    def too_short(path):
        raise AssertionError("Audio prompt must be longer than 5 seconds!")
    side.model.prepare_conditionals = too_short
    r = _say(side, "Hello.", voice="Short")
    assert r.status_code == 400
    assert "one person speaking for over five seconds" in r.json()["detail"]
    assert "longer than 5 seconds" in r.json()["detail"]


def test_speed_is_a_stretch_that_keeps_the_pitch_and_one_is_none(tmp_path):
    asked = []

    def stretch(audio, rate):
        asked.append(rate)
        return audio[: int(len(audio) / rate)]
    side = Sidecar(tmp_path / "voices", stretch=stretch).wait_loaded()
    whole = wav_info(_say(side, "Hello.").content)["frames"]
    assert asked == [], "at 1x nothing is stretched"
    assert wav_info(_say(side, "Hello.", speed=2).content)["frames"] == whole // 2
    _say(side, "Hello.", speed=5)
    _say(side, "Hello.", speed=0.1)
    assert asked == [2.0, 2.0, 0.5], "held between half and twice"


@pytest.mark.parametrize(("body", "said"), [
    ({"input": "Hello.", "response_format": "mp3"}, "Chatterbox answers in WAV"),
    ({"input": "x" * 5001}, "more than 5000 characters"),
    ({"input": "   "}, "There is nothing in it to say."),
])
def test_what_it_cannot_say_is_refused_with_a_sentence(sidecar, body, said):
    r = sidecar.http.post("/v1/audio/speech", json=body)
    assert r.status_code == 400 and said in r.json()["detail"], r.text
    assert sidecar.model.generated == []


def test_one_sentence_is_spoken_at_a_time(sidecar):
    """The GPU does one well and two slowly: two requests at once are said
    one after the other, never interleaved."""
    import threading
    inside = []
    original = sidecar.model.generate

    def generate(text):
        inside.append(+1)
        assert sum(inside) == 1, "two at once"
        try:
            time.sleep(0.02)
            return original(text)
        finally:
            inside.append(-1)
    sidecar.model.generate = generate
    threads = [threading.Thread(target=_say, args=(sidecar, f"Sentence {i}. And more.")) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(sidecar.model.generated) == 4


# ── Pantheon's client ──


@pytest.fixture()
def client(sidecar, monkeypatch):
    monkeypatch.setenv("PANTHEON_CHATTERBOX_URL", URL + "/")
    return sidecar.client()


def test_pantheon_finds_it_ready_with_its_voices_and_speaks_through_it(tmp_path, monkeypatch):
    recording(tmp_path / "voices" / "Grandad.wav")
    side = Sidecar(tmp_path / "voices").wait_loaded()
    monkeypatch.setenv("PANTHEON_CHATTERBOX_URL", URL)
    client = side.client()
    health = client.health()
    assert health == {"ok": True, "reason": None, "device": "cuda (Stand-in GPU)",
                      "voices": ["default", "Grandad"],
                      "labels": {"default": "Chatterbox", "Grandad": "Grandad"}}
    assert client.available() and client.voices() == ["default", "Grandad"]
    assert client.voice("Grandad") == "Grandad"
    assert client.voice("af_heart") == "default", "another engine's voice is its own"
    audio = client.synthesize("Hello from the GPU.", "Grandad", 1.0)
    assert wav_info(audio)["frames"] == len("Hello from the GPU.") * 100
    assert side.posted[-1] == (URL + "/v1/audio/speech", {
        "model": "chatterbox-turbo", "input": "Hello from the GPU.", "voice": "Grandad",
        "response_format": "wav", "speed": 1.0})
    # A health slower than two seconds is no answer (a page waits on it); a
    # long reply on a busy GPU is given two minutes.
    assert side.timeouts == [("GET", 2.0), ("POST", 120.0)]


def test_its_health_is_asked_at_most_every_half_minute(sidecar, monkeypatch):
    monkeypatch.setenv("PANTHEON_CHATTERBOX_URL", URL)
    clock = Clock()
    client = sidecar.client(clock)
    for _ in range(5):
        client.available()
        client.voice("default")
    assert sidecar.asked == [URL + "/health"]
    clock.now += 29
    client.voices()
    assert len(sidecar.asked) == 1
    clock.now += 2
    client.voices()
    assert len(sidecar.asked) == 2
    client.health(fresh=True)
    assert len(sidecar.asked) == 3


def test_with_no_address_it_is_not_set_up_and_nothing_is_asked(sidecar, monkeypatch):
    monkeypatch.delenv("PANTHEON_CHATTERBOX_URL", raising=False)
    client = sidecar.client()
    health = client.health()
    assert health["ok"] is False and "not set up on this install" in health["reason"]
    assert "docker/gpu.nvidia.yml" in health["reason"]
    with pytest.raises(RuntimeError, match="not set up on this install"):
        client.synthesize("Hello.")
    assert sidecar.asked == [] and sidecar.posted == [], "an install without it never looks"


def test_a_sidecar_that_is_down_says_how_to_start_it(client, sidecar):
    sidecar.up = False
    health = client.health(fresh=True)
    assert health["ok"] is False
    assert health["reason"] == (
        "Chatterbox is not running. On a server with an NVIDIA GPU and its overlay "
        "(docker/gpu.nvidia.yml), add COMPOSE_PROFILES=chatterbox to .env and run docker compose up -d.")
    assert client.voice("Grandad") == "default"


def test_a_refusal_is_said_in_the_sidecars_words_and_the_next_health_is_asked_fresh(tmp_path, monkeypatch):
    recording(tmp_path / "voices" / "Short.wav", seconds=2)
    side = Sidecar(tmp_path / "voices").wait_loaded()

    def too_short(path):
        raise AssertionError("Audio prompt must be longer than 5 seconds!")
    side.model.prepare_conditionals = too_short
    monkeypatch.setenv("PANTHEON_CHATTERBOX_URL", URL)
    client = side.client()
    assert client.available() and client.voice("Short") == "Short"
    asked = len(side.asked)
    with pytest.raises(RuntimeError, match="one person speaking for over five seconds"):
        client.synthesize("Hello.", "Short")
    client.available()
    assert len(side.asked) == asked + 1, "a sidecar that refused may be down: asked again"


# ── Its container ──


def test_the_container_is_pinned_bakes_its_weights_and_runs_offline_as_nobody():
    text = (FOLDER / "Dockerfile").read_text(encoding="utf-8")
    base = re.search(r"^FROM (\S+)", text, re.M).group(1)
    assert re.fullmatch(r"pytorch/pytorch:2\.6\.0-cuda12\.4-cudnn9-runtime@sha256:[0-9a-f]{64}", base), base
    fetch = text.index("snapshot_download")
    offline = text.index("HF_HUB_OFFLINE=1")
    assert fetch < offline, "fetched while built, then offline"
    for name in ("t3_turbo_v1.safetensors", "s3gen_meanflow.safetensors", "ve.safetensors", "conds.pt"):
        assert f'test -f "$CHATTERBOX_MODEL_DIR/{name}"' in text, name
    assert "ARG CHATTERBOX_REPO=ResembleAI/chatterbox-turbo" in text
    user = re.search(r"^USER (\S+)", text, re.M).group(1)
    assert user != "root" and text.index("USER ") > text.index("COPY server.py")
    assert "NUMBA_CACHE_DIR=/tmp/numba" in text, "librosa's cache, where that user may write"
    assert re.search(r"^HEALTHCHECK .*\n.*127\.0\.0\.1:8004/health", text, re.M)
    assert re.search(r'^CMD \["python", "server\.py"\]', text, re.M)


def test_its_requirements_are_pinned_and_keep_the_images_torch():
    lines = [ln.strip() for ln in (FOLDER / "requirements.txt").read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    assert lines and all(re.fullmatch(r"[A-Za-z0-9_.\-\[\]]+==[0-9][0-9A-Za-z.\-]*", ln) for ln in lines), lines
    names = {ln.split("==")[0].lower() for ln in lines}
    assert "chatterbox-tts" in names and "torch" not in names and "torchaudio" not in names
    assert "assert torch.__version__.startswith('2.6.0')" in (FOLDER / "Dockerfile").read_text(encoding="utf-8")
    pins = dict(ln.split("==") for ln in lines)
    core = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for name in ("fastapi", "uvicorn"):
        assert f"{name}=={pins[name]}" in core, f"{name} at the version Pantheon itself pins"
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert dependabot.count('directory: "/voice/chatterbox"') == 2, "pip and docker both watched"
