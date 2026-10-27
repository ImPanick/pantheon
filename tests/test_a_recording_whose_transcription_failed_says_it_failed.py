# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1579` — a recording whose transcription failed says it failed.

`STTService.unheard_reason` (`B1571`) covered the download gate only. With
local Whisper loaded and `_transcribe_local` raising — a recording ffmpeg
cannot decode, a CUDA fault — it returned `None`, and the recording's note fell
back to *"…, and this server has no speech-to-text set up"*: a person who had
set it up, and whose Whisper had just run, was sent looking for the setting.

Driven (`Law 20`) through `B1571`'s harness: the real
`ChatHandler.preprocess_message` over the real `build_user_content`,
`UploadHandler` and `STTService`; the one stand-in is `faster_whisper` itself
(`tests/test_local_whisper_asks_before_it_downloads.py`'s fake hub), here with
its model on disk and its `transcribe` made to raise.
"""
from __future__ import annotations

import sys

import pytest

from test_a_recording_not_heard_says_the_gate_refused_its_model import _preprocess
from test_a_recording_not_heard_says_the_gate_refused_its_model import service  # noqa: F401
from test_local_whisper_asks_before_it_downloads import hub, settings  # noqa: F401

OLD = "no speech-to-text set up"


@pytest.fixture
def loaded(hub, settings):  # noqa: F811
    """Whisper `base` on disk, so the model loads with the gate shut."""
    hub.cached.add("base")
    return sys.modules["faster_whisper"].WhisperModel


def test_a_transcription_that_raised_gives_a_note_saying_it_failed(
        tmp_path, monkeypatch, loaded, service):  # noqa: F811
    """The row's `Verify:`."""
    def broken(self, path, **kw):
        raise RuntimeError("Invalid data found when processing input")

    monkeypatch.setattr(loaded, "transcribe", broken)
    _content, att = _preprocess(tmp_path, monkeypatch)
    assert att["reach"] == "not_heard", att
    note = att["reach_note"]
    assert service._whisper_model is not None, "the premise: Whisper was loaded"
    assert "Local speech-to-text (Whisper) failed on it" in note, note
    assert "Invalid data found when processing input" in note, note
    assert OLD not in note, note


def test_a_transcription_that_heard_no_words_says_so(
        tmp_path, monkeypatch, loaded, service):  # noqa: F811
    def silent(self, path, **kw):
        import types
        return [], types.SimpleNamespace(language="en", language_probability=0.5)

    monkeypatch.setattr(loaded, "transcribe", silent)
    _content, att = _preprocess(tmp_path, monkeypatch)
    assert att["reach"] == "not_heard", att
    assert "Whisper) gave no words for it" in att["reach_note"], att
    assert OLD not in att["reach_note"], att


def test_a_whisper_that_would_not_load_says_so(tmp_path, monkeypatch, loaded, service):  # noqa: F811
    def refuses(self, *a, **kw):
        raise RuntimeError("CUDA driver version is insufficient")

    monkeypatch.setattr(loaded, "__init__", refuses)
    _content, att = _preprocess(tmp_path, monkeypatch)
    note = att["reach_note"]
    assert "could not load the Whisper “base” model" in note, note
    assert "CUDA driver version is insufficient" in note, note
    assert OLD not in note, note


def test_the_next_recording_that_is_heard_carries_no_stale_failure(
        tmp_path, monkeypatch, loaded, service):  # noqa: F811
    def broken(self, path, **kw):
        raise RuntimeError("boom")

    hears = loaded.transcribe            # the hub's own, which hears "hello"
    monkeypatch.setattr(loaded, "transcribe", broken)
    _preprocess(tmp_path, monkeypatch)
    assert service._transcribe_failure, "the premise: a failure was recorded"
    monkeypatch.setattr(loaded, "transcribe", hears)
    _content, att = _preprocess(tmp_path, monkeypatch)
    assert att["reach"] == "transcribed", att
    assert service._transcribe_failure is None


def test_an_endpoint_that_failed_says_so_without_its_address(monkeypatch, settings):  # noqa: F811
    """The same defect on the other server-side provider: an endpoint that
    answered 401 was called *no speech-to-text set up*."""
    import httpx
    from services.stt.stt_service import STTService
    import src.database as db

    settings["stt_provider"] = "endpoint:ep1"

    class _Q:
        def filter(self, *_a):
            return self

        def first(self):
            from types import SimpleNamespace
            return SimpleNamespace(base_url="http://user:secret@stt.lan/v1", api_key="k")

    class _S:
        def query(self, *_a):
            return _Q()

        def close(self):
            pass

    monkeypatch.setattr(db, "SessionLocal", lambda: _S())

    def post_sync(url, **kw):
        req = httpx.Request("POST", url)
        resp = httpx.Response(401, request=req)
        raise httpx.HTTPStatusError("401", request=req, response=resp)

    import src.paced_http as ph
    monkeypatch.setattr(ph, "post_sync", post_sync)
    svc = STTService()
    assert svc.transcribe(b"RIFF....") is None
    said = svc.unheard_reason()
    assert said and "endpoint failed on it (it answered 401)" in said, said
    assert "secret" not in said and "stt.lan" not in said, said
