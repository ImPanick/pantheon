# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx5-vision `B-NEW-7`/`B-NEW-8` — through the real route, what the model and the page are sent.

The owner, 2026-10-08: *"Ensure not just images reach model -- that ALL
attachments and any 'attachable' context reaches the model."*

**`B-NEW-8`, measured on the tree before this wave** (this checkout's `app.py`,
`/api/chat_stream`, a recording model): an email open in the reader
(`active_email_uid`) and a document open in the editor (`active_doc_id`) reached
the model in Agent mode — the reader's header and preview, the document's text —
and in Chat mode as nothing at all: Chat mode's call has no tools and no
document access. The page promotes a turn with a document open (`chat.js`), but
not with an email open, and not in incognito; the route promotes both now and
says why in the turn's `auto_escalated` event.

**`B-NEW-7` end to end**: a recording reaches the model as its transcript when
the server's speech-to-text is an endpoint that answers (the scripted model plays
an OpenAI-compatible `/audio/transcriptions`), and the page is sent each
attachment's `reach_note` in the `attachments` event, the sentence it draws under
the attachment.

`Law 20`: `capture.Server` boots `app.py` on a throwaway data directory; every
turn goes through `/api/chat_stream`; the model is `demo_model.DemoModel`
keeping every request.
"""
from __future__ import annotations

import io
import json
import secrets
import struct
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "showcase"))

import demo_model  # noqa: E402
import seed  # noqa: E402

MODEL = "gemma-4-26b-a4b"
WORDS = "Use what I gave you and tell me the code word."
SCRIPT = [{"key": "c", "title": "Ctx", "turns": [{"user": WORDS, "steps": [{"say": "OK."}]}]}]


def _wav() -> bytes:
    b = io.BytesIO()
    w = wave.open(b, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
    w.writeframes(struct.pack("<80h", *([0] * 80)))
    w.close()
    return b.getvalue()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import capture
    import httpx

    work = tmp_path_factory.mktemp("fx5ctx")
    data = work / "data"
    data.mkdir()
    server = capture.Server(sys.executable, data, capture._free_port(),
                            extra_env={"PANTHEON_DISABLE_MCP": "1", "PANTHEON_UPLOAD_BURST_LIMIT": "100"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        pytest.fail(f"{e}\n{server.log_path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    log: list = []
    try:
        client = httpx.Client(base_url=server.base, timeout=180)
        seed.setup_admin(client, secrets.token_urlsafe(18))
        with demo_model.DemoModel(log=log, conversations=SCRIPT, model_id=MODEL,
                                  transcript="the code word is MARKSPOKENQ7") as m:
            ep = seed._ok(client.post("/api/model-endpoints", data={
                "name": "Box", "base_url": m.base_url, "supports_tools": "true",
                "require_models": "true"}), "endpoint")["id"]
            yield client, ep, log
    finally:
        server.stop()


def _turn(world, mode, extra=None, sid=None, attach=None):
    client, ep, log = world
    if sid is None:
        sess = seed._ok(client.post("/api/session", data={"endpoint_id": ep, "model": MODEL}), "chat")
        sid = sess.get("session_id") or sess.get("id")
    form = {"message": WORDS, "session": sid, "mode": mode, "plan_mode": "false",
            "selected_model": MODEL, "selected_endpoint_id": ep,
            "allow_bash": "false", "allow_web_search": "false", **(extra or {})}
    if attach:
        up = seed._ok(client.post("/api/upload", files={"files": attach}, data={"session_id": sid}), "upload")
        form["attachments"] = json.dumps([f["id"] for f in up["files"]])
    start = len(log)
    resp = client.post("/api/chat_stream", data=form)
    assert resp.status_code == 200, resp.text[:300]
    events = list(seed._sse_events(resp.text))
    asked = [e for e in log[start:] if e.get("stream")]
    assert asked, "the model was never asked"
    sent = "\n".join(demo_model._text(m.get("content")) for m in asked[0]["messages"])
    return events, sent


def _promoted(events):
    return [r for e in events if e.get("type") == "auto_escalated" for r in e.get("reasons", [])]


# ── `B-NEW-8`: what is open beside the chat ────────────────────────────────

def test_a_document_open_beside_a_chat_mode_turn_reaches_the_model(world):
    client, _ep, _log = world
    d = seed._ok(client.post("/api/document", json={"title": "Plan", "language": "markdown",
                                                     "content": "The code word is MARKDOCQ7."}), "doc")
    events, sent = _turn(world, "chat", {"active_doc_id": d.get("id") or d["document"]["id"]})
    assert "MARKDOCQ7" in sent, "Chat mode was given no document"
    assert "a document is open beside the chat" in _promoted(events)


def test_an_email_open_beside_a_chat_mode_turn_reaches_the_model(world):
    events, sent = _turn(world, "chat", {"active_email_uid": "42", "active_email_folder": "INBOX"})
    assert "ACTIVE EMAIL OPEN" in sent and "UID: 42" in sent, "Chat mode was given no email"
    assert "an email is open beside the chat" in _promoted(events)


def test_incognito_is_promoted_too(world):
    client, _ep, _log = world
    d = seed._ok(client.post("/api/document", json={"title": "Nobody", "language": "markdown",
                                                     "content": "The code word is MARKINCQ7."}), "doc")
    events, sent = _turn(world, "chat", {"active_doc_id": d.get("id") or d["document"]["id"],
                                         "incognito": "true"})
    assert "MARKINCQ7" in sent


def test_a_chat_mode_turn_with_nothing_open_is_not_promoted(world):
    events, _sent = _turn(world, "chat")
    assert _promoted(events) == []


def test_agent_mode_was_already_given_both(world):
    """The ordinary path, unchanged."""
    _events, sent = _turn(world, "agent", {"active_email_uid": "7"})
    assert "UID: 7" in sent


# ── `B-NEW-7`: a recording, and what the page is told ─────────────────────

def test_a_recording_reaches_the_model_as_its_transcript(world):
    client, ep, log = world
    seed._ok(client.post("/api/auth/settings", json={
        "stt_enabled": True, "stt_provider": f"endpoint:{ep}", "stt_model": "whisper-1"}), "stt")
    try:
        before = len([e for e in log if e.get("transcription")])
        events, sent = _turn(world, "chat", attach=("voice.wav", _wav(), "audio/wav"))
        assert len([e for e in log if e.get("transcription")]) == before + 1, "speech-to-text was not asked"
        assert "MARKSPOKENQ7" in sent
        att = [e for e in events if e.get("type") == "attachments"][0]["data"][0]
        assert att["reach_note"] == "The model was given a transcript of it."
    finally:
        seed._ok(client.post("/api/auth/settings", json={"stt_enabled": False, "stt_provider": "disabled"}), "stt off")


def test_a_recording_with_speech_to_text_off_is_said_not_heard_to_the_page(world):
    events, sent = _turn(world, "agent", attach=("voice.wav", _wav(), "audio/wav"))
    assert "[Recording attached: voice.wav — not heard." in sent
    att = [e for e in events if e.get("type") == "attachments"][0]["data"][0]
    assert att["reach"] == "not_heard" and att["reach_note"].startswith("Not heard:")


def test_the_page_is_told_a_zip_was_not_read(world):
    events, sent = _turn(world, "chat", attach=("bundle.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip"))
    assert "[Attached file: bundle.zip — contents not read." in sent
    att = [e for e in events if e.get("type") == "attachments"][0]["data"][0]
    assert att["reach_note"].startswith("Not read: there is no reader for .zip files")


def test_a_reload_keeps_the_sentence(world):
    client, ep, _log = world
    sess = seed._ok(client.post("/api/session", data={"endpoint_id": ep, "model": MODEL}), "chat")
    sid = sess.get("session_id") or sess.get("id")
    _turn(world, "chat", sid=sid, attach=("bundle.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip"))
    hist = client.get(f"/api/history/{sid}").json()
    rows = hist.get("history") if isinstance(hist, dict) else hist
    user = [m for m in rows if m.get("role") == "user"][-1]
    atts = (user.get("metadata") or {}).get("attachments") or []
    assert atts and atts[0].get("reach_note", "").startswith("Not read:")
