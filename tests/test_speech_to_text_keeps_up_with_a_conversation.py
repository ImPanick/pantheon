# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1716` — speech-to-text keeps up with a conversation.

A voice chat sends a recording every turn, and the speech-to-text it reaches
was built for a voice note now and then. Each recording went to an endpoint
named `audio.webm` whatever it was, so a WAV, a Safari recording or an MP3 was
refused by a server that reads all three. Whisper heard words in silence. A GPU
was looked for through torch, which the image does not install, and a GPU
CTranslate2 counts but cannot run on brought the process down. Two asks at once
built two models, a size changed in Settings was used only after a restart, and
the status read loaded the model.

Driven (`Law 20`) through the real routes (`POST /api/stt/transcribe`,
`GET /api/stt/stats`) and the real `STTService` reading the real settings
reader. The stand-ins: faster-whisper itself (a `WhisperModel` that keeps the
device it was built on and what it was asked, and can be held or refused), the
GPU probe's child process (`subprocess.run`), and the endpoint's server
(`paced_http.post_sync`, which keeps what was uploaded).
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_local_whisper_asks_before_it_downloads import settings  # noqa: F401  (fixture)

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32


class _Whisper:
    """faster-whisper, as far as speech-to-text reaches it."""

    def __init__(self, tmp_path):
        self.built: list = []        # (model folder, device, compute type)
        self.attempts = 0
        self.asked: list = []        # (temp file suffix, transcribe kwargs)
        self.refuse: set = set()     # devices whose build raises
        self.hold = None             # an Event every build waits on, when set
        self.entered = threading.Event()
        self.words = [" hello "]
        self.reader = None           # faster-whisper's own decoder, when it is asked
        self.heard: list = []        # seconds of audio the decoder read, at 16 kHz
        outer = self

        class WhisperModel:
            def __init__(self, source, device="cpu", compute_type="int8", **_kw):
                outer.attempts += 1
                outer.entered.set()
                if outer.hold is not None:
                    assert outer.hold.wait(15), "the test let the build go"
                if device in outer.refuse:
                    raise RuntimeError(f"{device} would not take the model")
                outer.built.append((Path(source).name, device, compute_type))

            def transcribe(self, path, **kw):
                outer.asked.append((Path(path).suffix, kw))
                if outer.reader is not None:          # what `WhisperModel.transcribe` does first
                    outer.heard.append(len(outer.reader(path, sampling_rate=16000)) / 16000)
                segments = [types.SimpleNamespace(text=t) for t in outer.words]
                return segments, types.SimpleNamespace(language="en", language_probability=0.99)

        def download_model(name, local_files_only=False, **_kw):
            folder = tmp_path / f"whisper-{name}"   # every size is in the cache
            folder.mkdir(exist_ok=True)
            return str(folder)

        self.module = types.ModuleType("faster_whisper")
        self.module.WhisperModel = WhisperModel
        self.utils = types.ModuleType("faster_whisper.utils")
        self.utils.download_model = download_model
        self.module.utils = self.utils


@pytest.fixture()
def whisper(monkeypatch, tmp_path, settings):  # noqa: F811
    from services.stt import stt_service
    w = _Whisper(tmp_path)
    monkeypatch.setitem(sys.modules, "faster_whisper", w.module)
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", w.utils)
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.delenv("PANTHEON_SEED_MODELS", raising=False)
    monkeypatch.setattr(stt_service, "_cuda_devices", lambda: 0)
    monkeypatch.setattr(stt_service, "_cuda_verdict", None)
    return w


@pytest.fixture()
def probe(monkeypatch):
    """The GPU probe's child process: what it was run with, and how it ends."""
    runs: list = []
    real = subprocess.run
    state = types.SimpleNamespace(runs=runs, returncode=0, stderr=b"")

    def run(args, *a, **kw):
        if isinstance(args, list) and len(args) >= 3 and args[1] == "-c" and "WhisperModel" in args[2]:
            runs.append(args)
            return subprocess.CompletedProcess(args, state.returncode, b"", state.stderr)
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", run)
    return state


def _client():
    from routes.stt_routes import setup_stt_routes
    from services.stt.stt_service import STTService
    service = STTService()
    app = FastAPI()
    app.include_router(setup_stt_routes(service))
    return TestClient(app), service


def _send(client, data=WAV, name="turn.wav", mime="audio/wav"):
    return client.post("/api/stt/transcribe", files={"file": (name, data, mime)})


# ── the name a recording goes up under ───────────────────────────────────────

@pytest.mark.parametrize("data, name, sent", [
    (WAV, "turn.wav", ("audio.wav", "audio/wav")),
    (b"OggS\x00\x02" + b"\x00" * 20, "a.webm", ("audio.ogg", "audio/ogg")),
    (b"fLaC\x00\x00\x00\x22" + b"\x00" * 20, "", ("audio.flac", "audio/flac")),
    (b"\x1aE\xdf\xa3\x9fB\x86\x81" + b"\x00" * 20, "", ("audio.webm", "audio/webm")),
    (b"\x00\x00\x00\x1cftypM4A " + b"\x00" * 20, "audio.webm", ("audio.m4a", "audio/mp4")),
    (b"ID3\x04\x00\x00" + b"\x00" * 20, "", ("audio.mp3", "audio/mpeg")),
    (b"\xff\xfb\x90\x64" + b"\x00" * 20, "", ("audio.mp3", "audio/mpeg")),
    (b"\xff\xf1\x50\x80" + b"\x00" * 20, "note.opus", ("audio.ogg", "audio/ogg")),
    (b"\x00" * 24, "", ("audio.webm", "audio/webm")),
], ids=["wav", "ogg-misnamed", "flac", "webm", "safari-mp4", "mp3-id3", "mp3-frame",
        "aac-adts-by-its-name", "nothing-said"])
def test_each_recording_goes_up_named_for_what_it_is(monkeypatch, settings, data, name, sent):  # noqa: F811
    """An OpenAI-compatible `/audio/transcriptions` reads the format from the
    file's name. The bytes say what it is; the name it came with is asked
    only when they do not (an AAC stream is not an MP3, whatever its frame
    sync looks like)."""
    import src.database as db
    import src.paced_http as ph

    settings["stt_provider"] = "endpoint:ep1"

    class _Query:
        def filter(self, *_a):
            return self

        def first(self):
            return types.SimpleNamespace(base_url="http://stt.lan/v1", api_key="k")

    class _Session:
        def query(self, *_a):
            return _Query()

        def close(self):
            pass

    uploads: list = []

    def post_sync(url, files=None, **_kw):
        filename, body, mime = files["file"]
        uploads.append((filename, mime, body.read()))
        return httpx.Response(200, json={"text": "hello"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(db, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(ph, "post_sync", post_sync)
    client, _ = _client()
    r = _send(client, data, name or "blob", "application/octet-stream")
    assert r.status_code == 200 and r.json() == {"text": "hello"}, r.text
    assert [(f, m) for f, m, _ in uploads] == [sent]
    assert uploads[0][2] == data, "the recording itself went up, unchanged"


# ── what Whisper is asked ────────────────────────────────────────────────────

def test_silence_is_cut_out_before_whisper_hears_it(whisper, settings):  # noqa: F811
    """A voice call's pause came back as *"Thank you."*: faster-whisper's own
    voice-activity filter cuts the silence first, and a recording, being one
    turn, is not conditioned on text before it. An empty segment adds no
    space."""
    whisper.words = [" Hello ", "  ", " there. "]
    settings["stt_language"] = "en"
    client, _ = _client()
    r = _send(client)
    assert r.status_code == 200 and r.json() == {"text": "Hello there."}, r.text
    suffix, asked = whisper.asked[-1]
    assert asked == {"vad_filter": True, "condition_on_previous_text": False, "language": "en"}
    assert suffix == ".wav", "the file Whisper reads is named for what it is"


# ── what Whisper can open ────────────────────────────────────────────────────

def _pins(name):
    pins = {}
    for line in (Path(__file__).resolve().parent.parent / name).read_text(encoding="utf-8").splitlines():
        m = re.match(r"([A-Za-z0-9_.-]+)==([0-9][^;\s]*)", line.strip())
        if m:
            pins[m.group(1).lower()] = m.group(2)
    return pins


@pytest.mark.parametrize("name", ["requirements-voice.txt", "requirements-optional.txt"])
def test_pyav_stays_below_the_release_faster_whisper_cannot_open_audio_with(name):
    """faster-whisper 1.2.1 opens every recording with `av.open(...,
    metadata_errors="ignore")`, an argument PyAV 19 removed: with the newest
    PyAV each recording raised TypeError and local speech-to-text heard
    nothing (found running the image's own Python). Its main branch passes the
    argument only to an older PyAV; until a release carries that, PyAV is held
    below 19 wherever faster-whisper is installed from. Read from the files,
    so it holds in CI, which installs neither."""
    from packaging.version import Version
    pins = _pins(name)
    if Version(pins["faster-whisper"]) > Version("1.2.1"):
        pytest.skip("a faster-whisper after 1.2.1: the driven case below says whether it opens audio")
    assert "av" in pins, f"{name} installs faster-whisper with whatever PyAV is newest"
    assert Version(pins["av"]) < Version("19"), f"{name}: PyAV {pins['av']} has no metadata_errors"


@pytest.fixture()
def decoder():
    """faster-whisper's own decoder, the first thing `WhisperModel.transcribe`
    does with the file it is handed. Taken before `whisper` stands in for the
    package, and only where faster-whisper is installed (`requirements-voice.txt`;
    CI's `requirements.txt` does not carry it)."""
    return pytest.importorskip("faster_whisper.audio", reason="faster-whisper is not installed").decode_audio


def _recording(container):
    """A second of a tone, as the call sends it (`encodeWav`'s 16 kHz WAV) or
    a browser records it (WebM or Ogg Opus, Safari's MP4 with AAC)."""
    import io
    import wave

    import numpy as np
    pcm = (0.3 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000) * 32767).astype(np.int16)
    if container == "wav":
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm.tobytes())
        return buf.getvalue()
    import av
    codec, rate = {"webm": ("libopus", 48000), "ogg": ("libopus", 48000), "mp4": ("aac", 44100)}[container]
    if codec not in av.codecs_available:
        pytest.skip(f"this PyAV cannot write {codec}")
    buf = io.BytesIO()
    with av.open(buf, mode="w", format=container) as out:
        stream = out.add_stream(codec, rate=rate)
        stream.layout = "mono"
        resampler = av.AudioResampler(format=stream.format.name, layout="mono", rate=rate)
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = 16000
        for piece in resampler.resample(frame) + resampler.resample(None):
            for packet in stream.encode(piece):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


@pytest.mark.parametrize("container, name, mime", [
    ("wav", "turn.wav", "audio/wav"),
    ("webm", "dictation.webm", "audio/webm"),
    ("ogg", "dictation.ogg", "audio/ogg"),
    ("mp4", "dictation.mp4", "audio/mp4"),
], ids=["the-calls-wav", "webm-opus", "ogg-opus", "safari-mp4-aac"])
def test_whisper_opens_each_recording_it_is_sent(decoder, whisper, container, name, mime):
    """The real decoder, on the file `_transcribe_local` writes: a decoder
    that cannot open it is a recording heard as nothing."""
    whisper.reader = decoder
    client, _ = _client()
    r = _send(client, _recording(container), name, mime)
    assert r.status_code == 200 and r.json() == {"text": "hello"}, r.text
    assert 0.9 < whisper.heard[-1] < 1.2, f"a second of audio was read as {whisper.heard[-1]:.2f} s"


# ── the GPU ──────────────────────────────────────────────────────────────────

def test_the_gpu_is_asked_of_ctranslate2_not_torch(monkeypatch):
    """faster-whisper's engine answers for itself; torch, which the image
    does not install, was asked, so a GPU passed into the container was never
    used for speech."""
    from services.stt import stt_service
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(get_cuda_device_count=lambda: 2))
    assert stt_service._cuda_devices() == 2

    def broken():
        raise RuntimeError("CUDA driver version is insufficient for CUDA runtime version")

    monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(get_cuda_device_count=broken))
    assert stt_service._cuda_devices() == 0
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    assert stt_service._cuda_devices() == 0, "not installed is no GPU"


def test_a_gpu_that_would_bring_the_server_down_is_found_out_first(whisper, probe, monkeypatch):
    """CTranslate2 counts a device whenever the driver is passed in, and with
    no cuDNN in the image the first recording aborts the process it runs in.
    The probe runs that first recording in a child; the child's abort is a
    *no*, asked once, and the CPU hears."""
    from services.stt import stt_service
    monkeypatch.setattr(stt_service, "_cuda_devices", lambda: 1)
    probe.returncode = -6
    probe.stderr = b"Could not load library libcudnn_ops.so.9\nAborted (core dumped)"
    client, service = _client()
    assert _send(client).status_code == 200
    assert whisper.built == [("whisper-base", "cpu", "int8")]
    assert len(probe.runs) == 1
    args = probe.runs[0]
    assert args[0] == sys.executable and args[-1].endswith("whisper-base"), args
    assert "device='cuda'" in args[2] and "transcribe" in args[2], "the probe hears, not only loads"
    service._whisper_model = None                      # a later load in the same process
    assert _send(client).status_code == 200
    assert len(probe.runs) == 1, "the verdict is kept for the process"
    assert service.get_stats()["device"] == "cpu"


def test_a_gpu_that_runs_whisper_is_used(whisper, probe, monkeypatch):
    from services.stt import stt_service
    monkeypatch.setattr(stt_service, "_cuda_devices", lambda: 1)
    client, service = _client()
    assert _send(client).status_code == 200
    assert whisper.built == [("whisper-base", "cuda", "float16")]
    assert service.get_stats()["device"] == "cuda"


def test_a_gpu_that_refuses_the_model_leaves_it_on_the_cpu(whisper, probe, monkeypatch):
    """Too little memory on the card: the CPU takes the model, and nothing
    says speech-to-text failed."""
    from services.stt import stt_service
    monkeypatch.setattr(stt_service, "_cuda_devices", lambda: 1)
    whisper.refuse.add("cuda")
    client, service = _client()
    r = _send(client)
    assert r.status_code == 200 and r.json() == {"text": "hello"}, r.text
    assert whisper.attempts == 2 and whisper.built == [("whisper-base", "cpu", "int8")]
    assert service.unavailable_reason() is None


# ── one model, the one chosen ────────────────────────────────────────────────

def test_the_status_never_loads_the_model_it_starts_it_and_says_so(whisper):
    """The first status read built Whisper on the request — seconds, or a
    download's minutes — and Settings and a starting call waited. It answers
    at once with `loading`, and the next read finds the model."""
    whisper.hold = threading.Event()
    client, _ = _client()
    t0 = time.monotonic()
    first = client.get("/api/stt/stats").json()
    assert time.monotonic() - t0 < 5
    assert first["loading"] is True and first["model_loaded"] is False and first["available"] is True
    assert whisper.entered.wait(5), "the load started in the background"
    assert client.get("/api/stt/stats").json()["loading"] is True, "a second read waits on the same load"
    whisper.hold.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        stats = client.get("/api/stt/stats").json()
        if stats["model_loaded"]:
            break
        time.sleep(0.02)
    assert stats["model_loaded"] is True and stats["loading"] is False and stats["device"] == "cpu", stats
    assert whisper.built == [("whisper-base", "cpu", "int8")], "built once"


def test_two_asks_at_once_build_one_model(whisper):
    """A call's warm-up and its first recording both asked for the model, and
    two were built side by side, each holding the memory of one."""
    whisper.hold = threading.Event()
    client, service = _client()
    assert service.warm() is True
    assert whisper.entered.wait(5)
    heard: list = []
    second = threading.Thread(target=lambda: heard.append(_send(client).json()))
    second.start()
    time.sleep(0.2)                                     # the recording is waiting on the load
    whisper.hold.set()
    second.join(10)
    assert heard == [{"text": "hello"}]
    assert whisper.built == [("whisper-base", "cpu", "int8")]
    assert service.warm() is False, "loaded: nothing to warm"


def test_a_size_changed_in_settings_is_the_one_heard_with_next(whisper, settings):  # noqa: F811
    client, service = _client()
    assert _send(client).status_code == 200
    settings["stt_model"] = "small"
    assert service.get_stats()["model_loaded"] is False, "the loaded model is not the size chosen"
    assert _send(client).status_code == 200
    assert [b[0] for b in whisper.built] == ["whisper-base", "whisper-small"]
    assert service.get_stats()["model_loaded"] is True


def test_a_load_that_failed_is_not_tried_again_by_every_status_read(whisper):
    """Settings polls the status; a model that would not load was built
    again on each poll. The failure is said, and the next recording tries."""
    whisper.refuse.add("cpu")
    client, service = _client()
    r = _send(client)
    assert r.status_code == 503, r.text
    said = r.json()["detail"]["message"]
    assert "could not load the Whisper “base” model (cpu would not take the model)" in said
    tried = whisper.attempts
    for _ in range(3):
        stats = client.get("/api/stt/stats").json()
        assert stats["available"] is False and stats["unavailable_reason"] == said
        assert stats["loading"] is False
    assert whisper.attempts == tried
    whisper.refuse.clear()
    assert _send(client).json() == {"text": "hello"}, "a recording asks again"
