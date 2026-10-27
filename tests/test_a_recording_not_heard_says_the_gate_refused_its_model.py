# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1571` — a recording's *not heard* note says the download gate refused, when it did.

`document_processor.recording_in_words` wrote one note for every recording the
model was not given in words: *"…, and this server has no speech-to-text set
up."* With `stt_provider=local` set up and `B1565`'s gate off, local Whisper
was set up and refused its model — so the note sent a person looking for a
setting they had already made, while the sentence naming the switch that would
fix it (`ensure_whisper_download_permitted`) was in the server's hand.

Now the note carries the speech-to-text service's own sentence when it has one
(`STTService.unheard_reason`), and the old one otherwise.

Driven (`Law 20`): the real `ChatHandler.preprocess_message` over the real
`build_user_content`, `UploadHandler` and `STTService`, with the real
`allow_model_download` switch; the one stand-in is `faster_whisper` itself
(`tests/test_local_whisper_asks_before_it_downloads.py`'s fake hub, which
records any fetch). The `B1566` path — a fallback model that does not hear —
writes the same note through `unheard_turn`, and is driven too.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from test_every_attachment_says_what_reached_the_model import _wav
from test_local_whisper_asks_before_it_downloads import hub, settings  # noqa: F401

GATE_WORDS = "Whisper “base” model, which is not downloaded"


@pytest.fixture
def service(monkeypatch, hub, settings):  # noqa: F811
    """One real `STTService`, the one both the transcriber and the note ask."""
    import services.stt as stt_mod
    from services.stt.stt_service import STTService

    svc = STTService()
    monkeypatch.setattr(stt_mod, "get_stt_service", lambda: svc)
    return svc


def _preprocess(tmp_path, monkeypatch):
    from src.chat_handler import ChatHandler
    from src.upload_handler import UploadHandler
    import src.chat_handler as ch

    monkeypatch.setattr(ch, "UPLOAD_DIR", str(tmp_path / "uploads"))
    p = tmp_path / "voice.wav"
    p.write_bytes(_wav())
    infos = {"a0": {"id": "a0", "name": "voice.wav", "path": str(p), "mime": "audio/wav",
                    "size": p.stat().st_size}}

    class _Uploads(UploadHandler):
        def resolve_upload(self, att_id, owner=None):
            return dict(infos[att_id]) if att_id in infos else None

        def _inside_upload_dir(self, path):
            return True

    handler = ChatHandler(session_manager=None, memory_manager=None, chat_processor=None,
                          research_handler=None, preset_manager=None,
                          upload_handler=_Uploads(str(tmp_path), str(tmp_path / "uploads")))
    sess = SimpleNamespace(model="gemma-4-26b-a4b", endpoint_url="", owner="", id=None)
    _e, content, _t, _y, meta = asyncio.run(handler.preprocess_message(
        "What does it say?", list(infos), sess, auto_opened_docs=[], allow_tool_preprocessing=True))
    return content, meta[0]


def test_with_local_whisper_and_the_gate_off_the_note_gives_the_gates_sentence(
        tmp_path, monkeypatch, hub, service):  # noqa: F811
    """The row's `Verify:`."""
    _content, att = _preprocess(tmp_path, monkeypatch)
    assert att["reach"] == "not_heard", att
    note = att["reach_note"]
    assert note.startswith("Not heard: the model can't be given a recording."), note
    assert GATE_WORDS in note and "Download models from the internet" in note, note
    assert "no speech-to-text set up" not in note, note
    assert hub.fetched == [] and hub.built == [], "nothing was fetched to find out"


def test_once_the_gate_is_on_the_recording_is_heard_as_its_transcript(
        tmp_path, monkeypatch, hub, settings, service):  # noqa: F811
    settings["allow_model_download"] = True
    content, att = _preprocess(tmp_path, monkeypatch)
    assert att["reach"] == "transcribed", att
    assert hub.fetched == ["base"]


def test_with_speech_to_text_off_the_note_is_what_it_was(
        tmp_path, monkeypatch, hub, settings, service):  # noqa: F811
    settings["stt_provider"] = "disabled"
    _content, att = _preprocess(tmp_path, monkeypatch)
    assert att["reach_note"] == ("Not heard: the model can't be given a recording, "
                                 "and this server has no speech-to-text set up."), att


def test_a_refusal_from_before_the_provider_changed_is_not_said(
        tmp_path, monkeypatch, hub, settings, service):  # noqa: F811
    """The refusal is remembered on the service; it is about local Whisper,
    and is never said about a provider that is not."""
    _preprocess(tmp_path, monkeypatch)
    assert service.unavailable_reason(), "the premise: a refusal was recorded"
    settings["stt_provider"] = "browser"
    assert service.unheard_reason() is None
    _content, att = _preprocess(tmp_path, monkeypatch)
    assert "no speech-to-text set up" in att["reach_note"], att


def test_a_fallback_that_does_not_hear_is_given_the_same_note(service):
    """`B1566`'s path writes the note through `unheard_turn` — the same
    sentence (`Law 7`)."""
    from src.document_processor import HEARD_RECORDING, unheard_turn

    service.transcribe(b"RIFF....")    # what the route's transcriber asked first
    turn = [{"role": "user", "content": "hello" + HEARD_RECORDING.format(name="voice.wav")}]
    _out, reach = unheard_turn(turn, [{"id": "rec1", "name": "voice.wav"}], {})
    assert GATE_WORDS in reach["rec1"]["note"], reach
