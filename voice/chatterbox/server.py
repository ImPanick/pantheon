# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1729`. Chatterbox Turbo, served beside Pantheon on a server with an NVIDIA GPU.

The owner chose *"Kokoro, plus Chatterbox for a GPU"* (2026-11-01): Kokoro on
every server's processor, and Chatterbox Turbo (Resemble AI, MIT, weights and
code) where a GPU can run it. It needs PyTorch on CUDA, gigabytes Pantheon's
image does not carry for everyone, so it runs here, in a container of its own
(`voice/chatterbox/Dockerfile`), started by the NVIDIA overlay
(`docker/gpu.nvidia.yml`). Pantheon asks it (`services/tts/chatterbox_client.py`):

- `GET /health`: `{"ok", "reason", "device", "voices": [{"id", "name"}]}`;
  `ok` only once the model is loaded on the GPU, and `reason` says otherwise;
- `GET /v1/audio/voices`: the voices alone;
- `POST /v1/audio/speech`: `{"input", "voice", "speed", "response_format":
  "wav"}`, the OpenAI shape, answered with a 24 kHz WAV.

Voices: Chatterbox's own (`default`, the `conds.pt` its weights carry) and one
for each recording in `CHATTERBOX_VOICES_DIR` (`/voices`): a WAV or FLAC of one
person speaking, longer than five seconds, named for the voice
(`Grandad.wav` is "Grandad"). Chatterbox speaks in the voice it hears there,
so only a voice you may use belongs there. Every word it says carries
Resemble AI's inaudible Perth watermark, which marks it as made by a model.

The weights are baked into the image (`HF_HUB_OFFLINE`): the container reaches
nothing at run time (`Law 16`). One sentence is spoken at a time, because the
GPU does one well and two slowly.
"""
from __future__ import annotations

import io
import logging
import os
import re
import threading
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

logger = logging.getLogger("chatterbox")

MODEL_DIR = os.getenv("CHATTERBOX_MODEL_DIR", "/opt/chatterbox/model")
VOICES_DIR = os.getenv("CHATTERBOX_VOICES_DIR", "/voices")
DEFAULT_VOICE = "default"
MAX_INPUT = 5000          # what Pantheon sends at most (`TTSService.synthesize`)
_CHUNK = 280              # characters Chatterbox speaks well in one go
_VOICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class Speech(BaseModel):
    model: str = "chatterbox-turbo"
    input: str
    voice: str = DEFAULT_VOICE
    response_format: str = "wav"
    speed: float = 1.0


def device_wanted() -> str:
    """`cuda` unless the operator asked for something else. On a processor it
    is many times slower than speech, and Pantheon's "Automatic" would pick it
    over Kokoro, so `cpu` must be asked for by name."""
    return (os.getenv("CHATTERBOX_DEVICE") or "cuda").strip().lower()


def load_model(device: str):
    """Chatterbox Turbo from the baked weights, on `device`, or an exception
    that says why not."""
    import torch
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(
            "No NVIDIA GPU is visible to the Chatterbox container. Check the NVIDIA "
            "Container Toolkit (scripts/check-docker-gpu.sh), or set CHATTERBOX_DEVICE=cpu "
            "to run it slowly on the processor.")
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    model = ChatterboxTurboTTS.from_local(MODEL_DIR, device)
    name = device
    if device.startswith("cuda"):
        try:
            name = f"{device} ({torch.cuda.get_device_name(0)})"
        except Exception:
            pass
    return model, name


def voice_files(folder: str = VOICES_DIR) -> Dict[str, Path]:
    """`{voice id: recording}` for every usable recording in `folder`."""
    found: Dict[str, Path] = {}
    try:
        entries = sorted(Path(folder).iterdir())
    except OSError:
        return found
    for path in entries:
        if path.suffix.lower() not in (".wav", ".flac") or not path.is_file():
            continue
        vid = path.stem.strip()
        if vid.lower() == DEFAULT_VOICE or not _VOICE_NAME.match(vid):
            continue
        found.setdefault(vid, path)
    return found


def chunks(text: str, limit: int = _CHUNK) -> List[str]:
    """`text` as pieces of at most `limit` characters, cut between sentences
    where it can and between words where it must."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    pieces: List[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > limit // 3 else limit
            head, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if current:
                pieces.append(current)
                current = ""
            pieces.append(head)
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _samples(audio) -> "Any":
    import numpy as np
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    return np.asarray(audio, dtype=np.float32).reshape(-1)


def wav_bytes(samples, rate: int) -> bytes:
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(rate))
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class Voice:
    """The model, loaded once in the background, and each voice's
    conditionals, prepared once from its recording and kept."""

    def __init__(self, loader: Callable[[str], Any] = load_model,
                 voices_dir: str = VOICES_DIR, stretch: Optional[Callable] = None):
        self._loader = loader
        self._voices_dir = voices_dir
        self._stretch = stretch
        self.model = None
        self.device = ""
        self.error: Optional[str] = None
        self.loading = False
        self._conds: Dict[str, Any] = {}
        self._speak = threading.Lock()

    def start(self) -> None:
        self.loading = True
        threading.Thread(target=self._load, name="chatterbox-load", daemon=True).start()

    def _load(self) -> None:
        try:
            self.model, self.device = self._loader(device_wanted())
            self._conds[DEFAULT_VOICE] = getattr(self.model, "conds", None)
            logger.info("Chatterbox Turbo loaded on %s", self.device)
        except Exception as e:  # said by /health, in the words below
            logger.exception("Chatterbox would not load")
            self.error = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        finally:
            self.loading = False

    def voices(self) -> List[Dict[str, str]]:
        listed = [{"id": DEFAULT_VOICE, "name": "Chatterbox"}]
        listed += [{"id": vid, "name": vid} for vid in voice_files(self._voices_dir)]
        return listed

    def health(self) -> Dict[str, Any]:
        if self.model is not None:
            return {"ok": True, "reason": None, "device": self.device, "voices": self.voices()}
        if self.error:
            return {"ok": False, "reason": f"Chatterbox would not start: {self.error}",
                    "device": "", "voices": []}
        return {"ok": False, "reason": (
            "Chatterbox is loading its model onto the GPU (about half a minute after it starts)."),
            "device": "", "voices": []}

    def speak(self, text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> bytes:
        if self.model is None:
            raise HTTPException(503, self.health()["reason"])
        pieces = chunks(text)
        if not pieces:
            raise HTTPException(400, "There is nothing in it to say.")
        import numpy as np
        with self._speak:
            self._use(voice)
            rate = int(getattr(self.model, "sr", 24000))
            gap = np.zeros(int(rate * 0.12), dtype=np.float32)
            parts = []
            for piece in pieces:
                if parts:
                    parts.append(gap)
                parts.append(_samples(self.model.generate(piece)))
        audio = np.concatenate(parts)
        if speed and abs(float(speed) - 1.0) > 0.01:
            audio = self._stretched(audio, float(speed))
        return wav_bytes(audio, rate)

    def _use(self, voice: str) -> None:
        """Set the model's conditionals to `voice`'s, preparing them from its
        recording the first time (Chatterbox's own when it is unknown)."""
        recordings = voice_files(self._voices_dir)
        if voice not in self._conds and voice in recordings:
            try:
                self.model.prepare_conditionals(str(recordings[voice]))
                self._conds[voice] = self.model.conds
            except Exception as e:
                raise HTTPException(400, f"The recording for “{voice}” could not be used "
                                         f"(it must be one person speaking for over five seconds): {e}")
        chosen = self._conds.get(voice)
        if chosen is None:
            chosen = self._conds.get(DEFAULT_VOICE)
        if chosen is not None:
            self.model.conds = chosen

    def _stretched(self, audio, speed: float):
        """Faster or slower without the pitch moving: Chatterbox has no speed
        of its own."""
        speed = min(2.0, max(0.5, speed))
        stretch = self._stretch
        if stretch is None:
            import librosa
            stretch = lambda a, rate: librosa.effects.time_stretch(a, rate=rate)
        return stretch(audio, speed)


def create_app(voice: Optional[Voice] = None, start: bool = True) -> FastAPI:
    app = FastAPI(title="Pantheon's Chatterbox", docs_url=None, redoc_url=None)
    app.state.voice = voice or Voice()
    if start:
        app.state.voice.start()

    @app.get("/health")
    def health():
        return app.state.voice.health()

    @app.get("/v1/audio/voices")
    def voices():
        return {"voices": app.state.voice.voices() if app.state.voice.model is not None else []}

    @app.post("/v1/audio/speech")
    def speech(body: Speech):
        if body.response_format not in ("wav", ""):
            raise HTTPException(400, "Chatterbox answers in WAV (response_format \"wav\").")
        if len(body.input) > MAX_INPUT:
            raise HTTPException(400, f"That is more than {MAX_INPUT} characters to say at once.")
        audio = app.state.voice.speak(body.input, body.voice or DEFAULT_VOICE, body.speed)
        return Response(content=audio, media_type="audio/wav",
                        headers={"Content-Disposition": "inline; filename=speech.wav"})

    return app


if __name__ == "__main__":  # the container's command
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.getenv("CHATTERBOX_PORT", "8004")))
