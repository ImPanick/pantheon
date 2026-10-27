# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1566` — a recording rescued by a model that does not hear says so.

`B1290` sends a recording to the selected model as sound when its endpoint says
it hears, and the card under the attachment reads *The model was given the
recording itself*. Under a non-strict foreground policy a fallback may answer
instead, and one that does not hear is sent the turn without the sound part
(`_chat_candidate_request_factory`, `without_sounds`) — but the words it was
sent still said *given to the model as sound*, with no transcript (none is
asked for a recording the selected model hears), and the card went on saying
the model was given the recording when the model that answered had nothing
from it at all.

Now the candidate that does not hear is sent each such recording as its
transcript — asked for then, and only then — or as the not-heard sentence
(`document_processor.unheard_turn`), and when that candidate is the one that
answers the card says which: live (a second `attachments` event) and on the
saved message (`_persist_message_metadata`).

Driven (`Law 20`) through the real `/api/chat_stream` handler on
`tests/test_foreground_model_routing.py`'s harness — the route, its candidate
factory and its fallback handling are the real ones; the two models are a
stand-in stream that asks the factory for each candidate's request, as
`stream_llm_with_fallback` does, and then reports which one answered.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import routes.chat_routes as chat_routes
import src.chat_helpers as src_chat_helpers
import src.foreground_model_routing as foreground_model_routing
from tests.test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

BRACKET = "\n\n[Recording attached: voice.wav — given to the model as sound]"
SOUND = {"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "wav"}}
HEARD = "The model was given the recording itself."


def _turn():
    return [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "earlier answer"},
        # The harness's message is "hello"; the route keeps the turn that holds it.
        {"role": "user", "content": [{"type": "text", "text": "hello" + BRACKET}, SOUND]},
    ]


async def _drive(monkeypatch, *, transcripts, answered_by):
    captured, persisted, asked = {}, [], []
    meta = [{"id": "rec1", "name": "voice.wav", "mime": "audio/wav",
             "reach": "heard", "reach_note": HEARD}]
    user_row = SimpleNamespace(metadata={"attachments": meta, "_db_id": "row-1"})
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", captured, context_overrides={
        "messages": _turn(), "route_messages": _turn(),
        "preprocessed": SimpleNamespace(attachment_meta=meta),
        "user_message": user_row,
    })
    monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences", lambda owner=None: {
        "foreground_fallback_enabled": True,
        "foreground_model_fallbacks": [{"endpoint_id": "backup", "model": "backup-model"}],
    })
    monkeypatch.setattr(foreground_model_routing, "resolve_fallback_entries",
                        lambda *a, **k: [("https://backup.example/v1", "backup-model", {})])

    async def passthrough(session, url, model, messages, headers=None, owner=None, **kwargs):
        return list(messages), 8192, False

    monkeypatch.setattr(chat_routes, "maybe_compact", passthrough)
    monkeypatch.setattr(chat_routes, "trim_for_context", lambda messages, budget: list(messages))
    # The selected model's endpoint says it hears; the backup's says nothing.
    monkeypatch.setattr(src_chat_helpers, "audio_answer",
                        lambda model, url="": True if model == "selected-model" else None)

    def transcriber(chat_handler, owner):
        async def transcribe(ids):
            asked.append(list(ids))
            return dict(transcripts)
        return transcribe

    monkeypatch.setattr(chat_routes, "_fallback_transcriber", transcriber)
    monkeypatch.setattr(chat_routes, "_persist_message_metadata",
                        lambda sid, mid, md: persisted.append((sid, mid, json.loads(json.dumps(md)))) or True)

    async def fake_stream(candidates, messages, **kwargs):
        factory = kwargs["candidate_request_factory"]
        captured["requests"] = []
        # Lazily, as the real loop does: the backup is asked for only when the
        # selected model failed.
        for index, candidate in enumerate(candidates):
            if index > answered_by:
                break
            captured["requests"].append((await factory(index, *candidate))["messages"])
        if answered_by:
            yield ('data: {"type": "fallback", "candidate_index": 1, '
                   '"selected_model": "selected-model", "answered_by": "backup-model"}\n\n')
        yield 'data: {"delta": "the word"}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_llm_with_fallback", fake_stream)
    response = await endpoint(_RouteRequest("chat"))
    events = []
    async for chunk in response.body_iterator:
        for line in str(chunk).splitlines():
            if line.startswith("data: {"):
                events.append(json.loads(line[6:]))
    cards = [e["data"] for e in events if e.get("type") == "attachments"]
    return captured, cards, persisted, asked


def _text(message):
    content = message["content"]
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content if p.get("type") == "text")


def _sounds(messages):
    return [p for m in messages if isinstance(m.get("content"), list)
            for p in m["content"] if p.get("type") == "input_audio"]


@pytest.mark.asyncio
async def test_a_turn_rescued_by_a_model_that_does_not_hear_is_given_the_transcript(monkeypatch):
    """The row's `Verify:` — the transcript, to the model and on the card."""
    captured, cards, persisted, asked = await _drive(
        monkeypatch, transcripts={"rec1": "the code word is SPOKENQ7"}, answered_by=1)
    selected, backup = captured["requests"]
    assert _sounds(selected), "the model that hears is still sent the recording"
    assert not _sounds(backup)
    said = _text(backup[-1])
    assert "[Recording attached: voice.wav — transcript]:\nthe code word is SPOKENQ7" in said
    assert "given to the model as sound" not in said, "the model was told it had the sound"
    assert asked == [["rec1"]]
    # The card: live, and on the saved message.
    assert cards[-1][0]["reach"] == "transcribed"
    assert cards[-1][0]["reach_note"] == "The model was given a transcript of it."
    assert persisted and persisted[-1][1] == "row-1"
    assert persisted[-1][2]["attachments"][0]["reach_note"] == "The model was given a transcript of it."


@pytest.mark.asyncio
async def test_with_no_speech_to_text_the_card_says_not_heard(monkeypatch):
    captured, cards, persisted, _asked = await _drive(monkeypatch, transcripts={}, answered_by=1)
    backup = captured["requests"][1]
    assert "voice.wav — not heard" in _text(backup[-1])
    assert cards[-1][0]["reach"] == "not_heard"
    assert cards[-1][0]["reach_note"].startswith("Not heard: the model can't be given a recording")
    assert persisted[-1][2]["attachments"][0]["reach"] == "not_heard"


@pytest.mark.asyncio
async def test_a_turn_the_hearing_model_answers_is_unchanged_and_transcribes_nothing(monkeypatch):
    captured, cards, persisted, asked = await _drive(
        monkeypatch, transcripts={"rec1": "unused"}, answered_by=0)
    assert len(captured["requests"]) == 1 and _sounds(captured["requests"][0])
    assert asked == [], "speech-to-text was asked for a recording the model heard"
    assert [c[0]["reach_note"] for c in cards] == [HEARD]
    assert persisted == []


def test_the_words_are_the_ones_the_builder_writes():
    """One sentence each, `Law 7`: what a fallback is sent for an unheard
    recording is what `build_user_content` sends a model that never heard."""
    from src.document_processor import HEARD_RECORDING, recording_in_words, unheard_turn

    assert HEARD_RECORDING.format(name="voice.wav") == BRACKET
    out, reach = unheard_turn(_turn(), [{"id": "rec1", "name": "voice.wav"}], {})
    words, note = recording_in_words("voice.wav")
    assert _text(out[-1]) == "hello" + words
    assert reach == {"rec1": note}
    assert out[0] == _turn()[0] and not _sounds(out)
