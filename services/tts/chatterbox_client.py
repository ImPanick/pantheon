# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1729`. Chatterbox, the voice for a server with an NVIDIA GPU.

The owner chose *"Kokoro, plus Chatterbox for a GPU"* (2026-11-01). Chatterbox
Turbo (Resemble AI, MIT) needs PyTorch on CUDA, gigabytes the image should not
carry for everyone, so it runs beside Pantheon in a container of its own
(`voice/chatterbox/`), which the NVIDIA overlay (`docker/gpu.nvidia.yml`)
starts with `COMPOSE_PROFILES=chatterbox`, and Pantheon speaks to it over the
compose network. This is Pantheon's side:
where it is (`PANTHEON_CHATTERBOX_URL`, set by that overlay and by nothing
else, so an install without it never looks), whether it is up and on a GPU
(`health`, asked at most every half minute), its voices, and a sentence spoken.

Everything it says back is audio this server asked for; nothing of the
person's leaves the machine (`Law 16`): the address is a container on the
same host, or wherever an operator pointed it.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CHATTERBOX_DEFAULT_VOICE = "default"
_HEALTH_TTL = 30.0        # seconds a health answer is kept
_HEALTH_TIMEOUT = 2.0     # an answer slower than this is no answer
_SPEAK_TIMEOUT = 120.0    # a long reply on a busy GPU


def chatterbox_url() -> str:
    """The sidecar's base address, without a trailing slash, or '' when this
    install has none (`PANTHEON_CHATTERBOX_URL`)."""
    return str(os.getenv("PANTHEON_CHATTERBOX_URL") or "").strip().rstrip("/")


class ChatterboxClient:
    """What Pantheon knows of the sidecar. `get`/`post(url, **kw)` answer an
    httpx-like response; `src/paced_http`'s unless given (a test's stand-in)."""

    def __init__(self, get=None, post=None, clock=time.monotonic):
        self._get = get
        self._post = post
        self._clock = clock
        self._lock = threading.Lock()
        self._health: Optional[Dict[str, Any]] = None
        self._asked = -1e9

    def _http(self):
        if self._get is not None:
            return self._get, self._post
        from src import paced_http
        return paced_http.get_sync, paced_http.post_sync

    def health(self, fresh: bool = False) -> Dict[str, Any]:
        """`{"ok": bool, "reason": str|None, "device": str, "voices": [..]}`.
        Kept for `_HEALTH_TTL` seconds, so asking on every page load or
        sentence costs one request a half minute."""
        base = chatterbox_url()
        if not base:
            return {"ok": False, "reason": (
                "Chatterbox is not set up on this install: it runs beside Pantheon on a "
                "server with an NVIDIA GPU (docker/gpu.nvidia.yml)."), "voices": []}
        with self._lock:
            if not fresh and self._health is not None and self._clock() - self._asked < _HEALTH_TTL:
                return self._health
        get, _post = self._http()
        try:
            r = get(base + "/health", timeout=_HEALTH_TIMEOUT)
            body = r.json() if getattr(r, "status_code", 0) == 200 else {}
        except Exception as e:  # not running, or not reachable
            logger.info("Chatterbox not reachable at %s: %s", base, e)
            body = None
        if body is None:
            answer = {"ok": False, "reason": (
                "Chatterbox is not running. On a server with an NVIDIA GPU and its overlay "
                "(docker/gpu.nvidia.yml), add COMPOSE_PROFILES=chatterbox to .env and run "
                "docker compose up -d."),
                "voices": []}
        elif not body.get("ok"):
            answer = {"ok": False, "reason": str(body.get("reason") or "Chatterbox is not ready yet."),
                      "voices": []}
        else:
            voices = [str(v.get("id")) for v in body.get("voices") or [] if isinstance(v, dict) and v.get("id")]
            answer = {"ok": True, "reason": None, "device": str(body.get("device") or ""),
                      "voices": voices or [CHATTERBOX_DEFAULT_VOICE],
                      "labels": {str(v.get("id")): str(v.get("name") or v.get("id"))
                                 for v in body.get("voices") or [] if isinstance(v, dict) and v.get("id")}}
        with self._lock:
            self._health, self._asked = answer, self._clock()
        return answer

    def available(self) -> bool:
        return bool(self.health().get("ok"))

    def voices(self) -> List[str]:
        return list(self.health().get("voices") or [])

    def voice(self, voice: str) -> str:
        """`voice` when the sidecar has it, else its built-in voice."""
        voices = self.voices()
        voice = str(voice or "").strip()
        return voice if voice in voices else CHATTERBOX_DEFAULT_VOICE

    def synthesize(self, text: str, voice: str = CHATTERBOX_DEFAULT_VOICE, speed: float = 1.0) -> bytes:
        """WAV bytes, or an exception saying why there are none."""
        base = chatterbox_url()
        if not base:
            raise RuntimeError(self.health()["reason"])
        _get, post = self._http()
        r = post(base + "/v1/audio/speech", timeout=_SPEAK_TIMEOUT, json={
            "model": "chatterbox-turbo", "input": text, "voice": voice,
            "response_format": "wav", "speed": speed})
        if getattr(r, "status_code", 0) != 200:
            try:
                said = r.json().get("detail")
            except Exception:
                said = None
            # The next health ask is fresh: a sidecar that refused may be down.
            with self._lock:
                self._asked = -1e9
            raise RuntimeError(str(said or f"Chatterbox answered {getattr(r, 'status_code', '?')}."))
        return r.content
