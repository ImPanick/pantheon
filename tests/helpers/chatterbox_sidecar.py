# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1729`. The Chatterbox sidecar (`voice/chatterbox/server.py`), served in
this process with a stand-in for its model, and Pantheon's client
(`services/tts/chatterbox_client.py`) wired to it.

The real model needs PyTorch on an NVIDIA GPU and weights fetched from Hugging
Face; neither is in CI. So the stand-in is the model alone — Chatterbox
Turbo's `generate`, `prepare_conditionals`, `conds` and `sr`, as `server.py`
reaches them — and everything around it, the sidecar's routes, its voices
folder, its pieces and its WAV, and Pantheon's client over HTTP, is the
shipped code.
"""
from __future__ import annotations

import importlib.util
import io
import threading
import time
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
URL = "http://chatterbox:8004"
SERVER = ROOT / "voice" / "chatterbox" / "server.py"


def server_module():
    """`voice/chatterbox/server.py`, which is no package: loaded from its file."""
    spec = importlib.util.spec_from_file_location("chatterbox_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeTurbo:
    """`ChatterboxTurboTTS`, as far as the server reaches it. Each piece it
    says is 100 samples a character, valued 0.25, and it keeps what it was
    asked and in which voice's conditionals."""

    sr = 24000

    def __init__(self):
        self.conds = "built-in"
        self.generated: list = []
        self.prepared: list = []

    def generate(self, text):
        self.generated.append((text, self.conds))
        return np.full((1, max(1, len(text)) * 100), 0.25, dtype=np.float32)

    def prepare_conditionals(self, wav_path):
        self.prepared.append(Path(wav_path).name)
        self.conds = f"conds:{Path(wav_path).stem}"


def recording(path: Path, seconds: float = 6.0, rate: int = 24000) -> Path:
    """A WAV of one "person" speaking (a tone), for the voices folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(seconds * rate)) / rate
    pcm = (0.3 * np.sin(2 * np.pi * 180 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return path


def wav_info(data: bytes) -> dict:
    with wave.open(io.BytesIO(data)) as wf:
        return {"rate": wf.getframerate(), "channels": wf.getnchannels(),
                "width": wf.getsampwidth(), "frames": wf.getnframes(),
                "samples": np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")}


class Clock:
    """`time.monotonic`, moved by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Sidecar:
    """The sidecar's app over a `TestClient`, reachable at `URL` the way the
    compose network reaches it, and switched off by `up = False` (nothing
    answers: a connection error, as a stopped container gives)."""

    def __init__(self, voices_dir: Path, loader=None, stretch=None, start: bool = True):
        self.module = server_module()
        self.model = FakeTurbo()
        voices_dir = Path(voices_dir)
        voices_dir.mkdir(parents=True, exist_ok=True)
        self.voice = self.module.Voice(
            loader=loader or (lambda device: (self.model, f"{device} (Stand-in GPU)")),
            voices_dir=str(voices_dir), stretch=stretch)
        self.app = self.module.create_app(self.voice, start=start)
        self.http = TestClient(self.app, base_url=URL)
        self.up = True
        self.asked: list = []
        self.posted: list = []
        self.timeouts: list = []   # what the client waits at most, asked and kept here

    def wait_loaded(self, seconds: float = 5.0) -> "Sidecar":
        deadline = time.monotonic() + seconds
        while self.voice.loading and time.monotonic() < deadline:
            time.sleep(0.01)
        return self

    def get(self, url, **kw):
        self.asked.append(url)
        self.timeouts.append(("GET", kw.get("timeout")))
        if not self.up:
            raise ConnectionError("[Errno 111] Connection refused")
        return self.http.get(url)

    def post(self, url, **kw):
        self.posted.append((url, kw.get("json")))
        self.timeouts.append(("POST", kw.get("timeout")))
        if not self.up:
            raise ConnectionError("[Errno 111] Connection refused")
        return self.http.post(url, json=kw.get("json"))

    def client(self, clock=None):
        """Pantheon's `ChatterboxClient`, speaking to this sidecar."""
        from services.tts.chatterbox_client import ChatterboxClient
        return ChatterboxClient(get=self.get, post=self.post, clock=clock or Clock())


def blocked_loader(model):
    """A loader that waits for `release.set()`, as the real one takes half a
    minute to put the model on the GPU."""
    release = threading.Event()

    def loader(device):
        release.wait(10)
        return model, f"{device} (Stand-in GPU)"

    return loader, release
