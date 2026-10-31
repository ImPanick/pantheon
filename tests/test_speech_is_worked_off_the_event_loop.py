# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1716`, `B1717` — turning speech into words and words into speech never
stops the server.

Both ran on the server's event loop: `POST /api/stt/transcribe` called
Whisper and `POST /api/tts/synthesize` called the voice inline, so while a
recording was heard or a sentence was said — seconds on a processor, and the
first one also waiting for the model to load — every other request from
every person waited, the chat's stream among them. A voice chat sends one of
each a turn. Now each runs in a worker thread, and so do the status reads
that look at model files on disk.

Driven (`Law 20`) through the real routes in one running app (one event loop,
as the server has): a speech service that holds its work until the test lets
it go, and a second request that must be answered meanwhile.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Held:
    """A speech service whose work waits until `release` is set."""

    available = True

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.threads: list = []

    def _work(self, answer):
        self.threads.append(threading.current_thread().name)
        self.entered.set()
        self.release.wait(15)
        return answer

    def transcribe(self, audio, filename=""):
        return self._work("heard you")

    def synthesize(self, text):
        return self._work(b"RIFF" + b"\x00" * 40)

    def get_stats(self):
        return {"provider": "local", "available": True}

    def unavailable_reason(self):
        return None


def _served_meanwhile(app, slow_request, quick_path):
    service = app.state.service
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(slow_request, client)
        assert service.entered.wait(15), "the slow request reached the service"
        t0 = time.monotonic()
        quick = client.get(quick_path)
        waited = time.monotonic() - t0
        service.release.set()
        return first.result(15), quick, waited


def test_a_recording_being_heard_does_not_hold_up_other_requests():
    from routes.stt_routes import setup_stt_routes
    app = FastAPI()
    app.state.service = _Held()
    app.include_router(setup_stt_routes(app.state.service))
    heard, quick, waited = _served_meanwhile(
        app, lambda c: c.post("/api/stt/transcribe", files={"file": ("turn.wav", b"RIFF" + b"\x00" * 64, "audio/wav")}),
        "/api/stt/stats")
    assert quick.status_code == 200 and waited < 5, f"the status waited {waited:.1f} s behind Whisper"
    assert heard.status_code == 200 and heard.json() == {"text": "heard you"}
    assert app.state.service.threads and app.state.service.threads[0] != threading.main_thread().name


def test_a_sentence_being_said_does_not_hold_up_other_requests():
    from routes.tts_routes import setup_tts_routes
    app = FastAPI()
    app.state.service = _Held()
    app.include_router(setup_tts_routes(app.state.service))
    said, quick, waited = _served_meanwhile(
        app, lambda c: c.post("/api/tts/synthesize", json={"text": "Hello there.", "format": "audio"}),
        "/api/tts/stats")
    assert quick.status_code == 200 and waited < 5, f"the status waited {waited:.1f} s behind the voice"
    assert said.status_code == 200 and said.content.startswith(b"RIFF")
