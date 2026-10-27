# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1290` — a recording is sent to a model that can hear it, and only to one.

`B1284` stopped sending a part no API takes and gave the model a transcript
when the server has speech-to-text. A model that takes OpenAI's `input_audio`
was still never offered the recording itself, because nothing asked which
models hear — and most local servers refuse an audio part outright, failing the
whole turn, so the answer cannot be a guess.

Now the capability readers answer it (`model_capabilities.audio_verdict`, read
from llama-server's `/props` `modalities.audio` and OpenRouter's catalogue —
the two endpoints that say), `chat_helpers.audio_answer` asks them and nothing
else, and a WAV or MP3 recording goes as an `input_audio` part to a model whose
endpoint says it hears. Everywhere else the transcript or the not-heard
sentence stands. The card says which happened.

`Law 20`: the unit cases call the real functions on real files; the end-to-end
cases boot `app.py` (`capture.Server`) with two scripted models — one whose
`/props` says it hears, one that refuses any audio part as a local server
does — and read what each was sent through `/api/chat_stream`.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import struct
import sys
import wave
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402


def _wav() -> bytes:
    b = io.BytesIO()
    w = wave.open(b, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
    w.writeframes(struct.pack("<80h", *range(80)))
    w.close()
    return b.getvalue()


_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 64
_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 60
_AAC = b"\xff\xf1\x50\x80" + b"\x00" * 60     # ADTS: the sync bits, layer 00


# ── the answer, from what a provider says ───────────────────────────────────

def test_the_reader_answer_is_yes_no_or_nothing():
    from src import model_capabilities as mc
    from src.model_capability_readers import llamacpp

    def props(modalities):
        record = llamacpp.record_from_props_payload({"model_alias": "m", "modalities": modalities})
        return mc.audio_verdict(record.capability)

    assert props({"vision": False, "audio": True}) is True
    assert props({"vision": True, "audio": False}) is False
    assert mc.audio_verdict(mc.unknown_capability()) is None


class _Net:
    """Every outbound request a probe makes, answered from the test's table."""

    def __init__(self):
        self.props = None
        self.catalogue = None
        self.seen = []

    def handle(self, request):
        self.seen.append(request.url.path)
        if request.url.path == "/props" and self.props is not None:
            return httpx.Response(200, json=self.props)
        if request.url.path.endswith("/models") and self.catalogue is not None:
            return httpx.Response(200, json=self.catalogue)
        return httpx.Response(404, json={})


@pytest.fixture
def net(monkeypatch):
    from src import chat_helpers
    from src.rate_limiter import outbound

    n = _Net()
    real_init = httpx.Client.__init__

    def _init(self, *a, **k):
        k["transport"] = httpx.MockTransport(n.handle)
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.Client, "__init__", _init)
    monkeypatch.setattr(outbound, "acquire", lambda host, **k: 0.0)
    monkeypatch.setattr(chat_helpers, "_probe_auth_headers", lambda url: {})
    for cache in ("_ollama_show_cache", "_openrouter_catalogue_cache", "_lmstudio_models_cache",
                  "_llamacpp_props_cache"):
        monkeypatch.setattr(chat_helpers, cache, {}, raising=False)
    return n


LLAMA = "http://127.0.0.1:8080/v1"


def test_llama_server_says_whether_its_model_hears(net):
    from src.chat_helpers import audio_answer, vision_answer

    net.props = {"model_alias": "omni-7b", "modalities": {"vision": False, "audio": True}}
    assert audio_answer("omni-7b", LLAMA) is True
    assert vision_answer("omni-7b", LLAMA) is False, "one /props read answers both"
    assert net.seen.count("/props") == 1
    net.props = {"model_alias": "text-7b", "modalities": {"vision": False, "audio": False}}
    assert audio_answer("text-7b", LLAMA) is False


@pytest.mark.parametrize("props", [
    None,                                                              # not llama-server
    {"model_alias": "omni-7b"},                                        # older: no modalities
    {"model_alias": "omni-7b", "modalities": {"vision": True}},        # says nothing of audio
    {"model_alias": "other", "modalities": {"audio": True}},           # about another model
], ids=["no-props", "no-modalities", "no-audio-field", "another-model"])
def test_nothing_said_is_never_a_yes(net, props):
    """No name list, no guess: an unknown keeps the recording out."""
    from src.chat_helpers import audio_answer

    net.props = props
    assert audio_answer("omni-7b", LLAMA) is None
    assert audio_answer("gpt-4o-audio-preview", "https://api.example.com/v1") is None


def test_openrouter_says_it_in_its_catalogue(net):
    from src.chat_helpers import audio_answer, vision_answer

    net.catalogue = {"data": [
        {"id": "acme/omni", "architecture": {"input_modalities": ["text", "audio"],
                                             "output_modalities": ["text"]}},
        {"id": "acme/eyes", "architecture": {"input_modalities": ["text", "image"],
                                             "output_modalities": ["text"]}},
    ]}
    url = "https://openrouter.ai/api/v1"
    assert audio_answer("acme/omni", url) is True
    assert audio_answer("acme/omni:free", url) is True, "a variant reads its base model"
    assert audio_answer("acme/eyes", url) is False
    assert vision_answer("acme/eyes", url) is True, "the picture answer is unchanged"


# ── the message, from a real file ───────────────────────────────────────────

class _Uploads:
    """The upload handler's three questions, answered as the real one does."""

    def __init__(self, base):
        self.base = base

    def is_image_file(self, name, mime):
        return False

    def is_audio_file(self, name, mime):
        return True

    def inside_base_dir(self, path):
        return str(path).startswith(str(self.base))


def _content(tmp_path, data: bytes, name: str, *, hears: bool, transcript: str = ""):
    from src.document_processor import build_user_content

    path = tmp_path / name
    path.write_bytes(data)
    reach: dict = {}
    content = build_user_content(
        "Listen.", ["rec1"], str(tmp_path), _Uploads(tmp_path),
        resolved_uploads={"rec1": {"id": "rec1", "path": str(path), "name": name,
                                   "mime": "audio/x-test"}},
        reach=reach, transcripts={"rec1": transcript} if transcript else None, hears=hears)
    return content, reach.get("rec1")


@pytest.mark.parametrize("name,data,fmt", [("voice.wav", _wav(), "wav"), ("voice.mp3", _MP3, "mp3")],
                         ids=["wav", "mp3"])
def test_a_model_that_hears_is_given_the_recording_itself(tmp_path, name, data, fmt):
    content, said = _content(tmp_path, data, name, hears=True, transcript="ignored")
    sounds = [p for p in content if p.get("type") == "input_audio"]
    assert len(sounds) == 1 and sounds[0]["input_audio"]["format"] == fmt
    assert base64.b64decode(sounds[0]["input_audio"]["data"]) == data
    assert f"[Recording attached: {name} — given to the model as sound]" in content[0]["text"]
    assert said == {"state": "heard", "note": "The model was given the recording itself."}


def test_a_model_nothing_said_hears_keeps_the_transcript(tmp_path):
    content, said = _content(tmp_path, _wav(), "voice.wav", hears=False, transcript="the word is Q7")
    assert isinstance(content, str) and "the word is Q7" in content
    assert said["state"] == "transcribed"


@pytest.mark.parametrize("name,data", [("voice.webm", _WEBM), ("voice.aac", _AAC)], ids=["webm", "aac"])
def test_a_format_no_audio_part_takes_is_said_and_not_sent(tmp_path, name, data):
    content, said = _content(tmp_path, data, name, hears=True)
    assert isinstance(content, str), "nothing but words"
    assert said["state"] == "not_heard"
    assert "WAV or MP3" in said["note"] and Path(name).suffix in said["note"]


def test_an_earlier_turns_recording_is_not_sent_again():
    from src.attachment_refs import without_sounds

    sound = {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}}
    history = [
        {"role": "user", "content": [{"type": "text", "text": "first"}, sound]},
        {"role": "assistant", "content": "heard it"},
        {"role": "user", "content": [{"type": "text", "text": "second"}, sound]},
    ]
    kept = without_sounds(history, keep_last_user=True)
    assert kept[0]["content"] == "first" and kept[2] is history[2]
    assert history[0]["content"][1] is sound, "the session's own message is not changed"
    assert without_sounds(history)[2]["content"] == "second"


# ── end to end: the real route, two scripted models ─────────────────────────

WORDS = "Listen to this and tell me the code word."
SCRIPT = [{"key": "a", "title": "Audio", "turns": [{"user": WORDS, "steps": [{"say": "OK."}]}]}]
HEARS, SILENT = "omni-hears-7b", "text-only-7b"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import capture

    work = tmp_path_factory.mktemp("b1290")
    data = work / "data"
    data.mkdir()
    server = capture.Server(sys.executable, data, capture._free_port(),
                            extra_env={"PANTHEON_DISABLE_MCP": "1",
                                       "PANTHEON_UPLOAD_BURST_LIMIT": "100"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    log: list = []
    try:
        client = httpx.Client(base_url=server.base, timeout=180)
        seed.setup_admin(client, secrets.token_urlsafe(18))
        refusal = (400, "audio input is not supported by this model")
        with demo_model.DemoModel(log=log, conversations=SCRIPT, model_id=HEARS,
                                  modalities={"vision": False, "audio": True}) as hears, \
                demo_model.DemoModel(log=log, conversations=SCRIPT, model_id=SILENT,
                                     refuse_audio=refusal,
                                     transcript="the code word is SPOKENQ7") as silent:
            eps = {}
            for model, m in ((HEARS, hears), (SILENT, silent)):
                eps[model] = seed._ok(client.post("/api/model-endpoints", data={
                    "name": model, "base_url": m.base_url, "require_models": "true"}),
                    "endpoint")["id"]
            yield client, eps, log
    finally:
        server.stop()


def _turn(world, model, *, sid=None, attach=None):
    client, eps, log = world
    if sid is None:
        sess = seed._ok(client.post("/api/session", data={"endpoint_id": eps[model],
                                                          "model": model}), "chat")
        sid = sess.get("session_id") or sess.get("id")
    form = {"message": WORDS, "session": sid, "mode": "chat", "plan_mode": "false",
            "selected_model": model, "selected_endpoint_id": eps[model],
            "allow_bash": "false", "allow_web_search": "false"}
    if attach:
        up = seed._ok(client.post("/api/upload", files={"files": attach},
                                  data={"session_id": sid}), "upload")
        form["attachments"] = json.dumps([f["id"] for f in up["files"]])
    start = len(log)
    resp = client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:300]
    events = list(seed._sse_events(resp.text))
    asked = [e for e in log[start:] if e.get("stream")]
    assert asked, "the model was never asked"
    reach = [e for e in events if e.get("type") == "attachments"]
    return sid, asked[0], reach[0]["data"][0] if reach else None, log[start:]


def test_the_model_that_hears_is_sent_the_recording_and_the_card_says_so(world):
    """The row's `Wants:`, driven: the bytes attached are the bytes it got."""
    wav = _wav()
    sid, asked, att, during = _turn(world, HEARS, attach=("voice.wav", wav, "audio/wav"))
    assert asked["sounds"] == [{"message": len(asked["messages"]) - 1, "format": "wav",
                                "bytes": len(wav), "sha256": hashlib.sha256(wav).hexdigest()}]
    assert att["reach"] == "heard"
    assert att["reach_note"] == "The model was given the recording itself."
    assert not [e for e in during if e.get("transcription")], "no speech-to-text for it"
    # The next turn is not sent the last turn's recording again.
    _sid, again, _att, _ = _turn(world, HEARS, sid=sid)
    assert again["sounds"] == [] and "refused" not in again


def test_a_model_that_says_nothing_is_never_sent_one(world):
    """A server that refuses any audio part, as most local servers do, is not
    sent one — the turn answers and the card says it was not heard."""
    _sid, asked, att, _ = _turn(world, SILENT, attach=("voice.wav", _wav(), "audio/wav"))
    assert asked["sounds"] == [] and "refused" not in asked
    assert att["reach"] == "not_heard" and att["reach_note"].startswith("Not heard:")


def test_a_chat_that_moves_to_a_model_that_does_not_hear_is_not_sent_the_old_recording(world):
    sid, first, _att, _ = _turn(world, HEARS, attach=("voice.wav", _wav(), "audio/wav"))
    assert first["sounds"]
    _sid, moved, _att2, _ = _turn(world, SILENT, sid=sid)
    assert moved["sounds"] == [] and "refused" not in moved
