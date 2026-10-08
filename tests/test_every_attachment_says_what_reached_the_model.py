# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx5-vision `B-NEW-7` — every kind of attachment reaches the model, or the person is told.

The owner, 2026-10-08, widening the image row: *"Ensure not just images reach
model -- that ALL attachments and any 'attachable' context reaches the model."*

**Measured on the tree before this row** (`/tmp/scratch-fx5-vision/measure_kinds.py`:
this checkout's `app.py`, one file of each of 25 kinds uploaded and sent through
`/api/chat_stream` in Chat and in Agent mode, a recording model keeping every
request): text, Markdown, code, CSV, TSV, JSON, TOML, PDF, DOCX, XLSX, ODT, DOC,
RTF and SVG reached the model as their text, and a picture as an `image_url`.
The rest did not, and the person was told nothing:

* a recording (`.wav`, `.mp3`, and a video `.webm` taken for one) went out as
  `{"type": "audio", "audio": {"url": "data:…"}}` — a part no chat API takes —
  with no words, so the model was not told a recording was attached and the
  saved message showed none;
* `.pptx`, `.xls`, `.epub` (markitdown not installed), video, `.zip` and other
  binaries reached the model as a bracket saying it was not read, and the person
  as a card that looked sent;
* a file too long for the message was cut, and only the model was told;
* a picture to a model whose server says it cannot see, with no vision model
  set, was swapped for *"[No vision model configured …]"*, and with pictures
  switched off it was dropped with no word to either.

Now each attachment carries `reach` / `reach_note` in the message's attachment
metadata — the one sentence the person reads under it, live and after a reload
— and a recording is its transcript when the server's speech-to-text answers.

Driven, not read (`Law 20`): the real `ChatHandler.preprocess_message` over the
real `build_user_content` and the real `UploadHandler` classification, on real
files (the Office ones LibreOffice made, `tests/helpers/office_fixtures.py`).
"""
from __future__ import annotations

import asyncio
import io
import struct
import wave
import zipfile
from types import SimpleNamespace

import pytest

from helpers.office_fixtures import OFFICE_SENTINEL, office_fixture
from test_attachment_extension_registers import _minimal_pdf


def _wav() -> bytes:
    b = io.BytesIO()
    w = wave.open(b, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
    w.writeframes(struct.pack("<80h", *([0] * 80)))
    w.close()
    return b.getvalue()


def _zip() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("inside.txt", "hidden words")
    return b.getvalue()


def _jpeg() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 80, 30)).save(b, "JPEG")
    return b.getvalue()


def _markitdown_installed() -> bool:
    try:
        import markitdown  # noqa: F401
        return True
    except Exception:
        return False


@pytest.fixture
def send(tmp_path, monkeypatch):
    """`send(files, model=…, vision=…, stt=…)` → (user_content, attachment_meta)."""
    from src.chat_handler import ChatHandler
    from src.upload_handler import UploadHandler
    import src.chat_handler as ch
    import src.settings as S

    sp = tmp_path / "settings.json"
    sp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    S._invalidate_caches()
    monkeypatch.setattr(ch, "UPLOAD_DIR", str(tmp_path / "uploads"))

    class _Uploads(UploadHandler):
        def __init__(self, files):
            super().__init__(str(tmp_path), str(tmp_path / "uploads"))
            self.files = files

        def resolve_upload(self, att_id, owner=None):
            return dict(self.files[att_id]) if att_id in self.files else None

        def _inside_upload_dir(self, path):
            return True

    real_get = S.get_setting

    def _send(files, model="gemma-4-26b-a4b", vision=True, stt=None, describer=None):
        # Settings → Vision's switch, as `preprocess_message` reads it.
        monkeypatch.setattr(S, "get_setting",
                            lambda key, default=None: vision if key == "vision_enabled" else real_get(key, default))
        monkeypatch.setattr(ch, "analyze_image_with_vl_result",
                            describer or (lambda path, owner=None: {"text": "[No vision model configured — set one in Settings → Vision]", "model": ""}))
        import services.stt as stt_mod
        monkeypatch.setattr(stt_mod, "get_stt_service",
                            lambda: SimpleNamespace(transcribe=lambda audio: stt))
        infos = {}
        for n, (name, raw, mime) in enumerate(files):
            p = tmp_path / f"f{n}-{name}"
            p.write_bytes(raw)
            infos[f"a{n}"] = {"id": f"a{n}", "name": name, "path": str(p), "mime": mime, "size": len(raw)}
        handler = ChatHandler(session_manager=None, memory_manager=None, chat_processor=None,
                              research_handler=None, preset_manager=None, upload_handler=_Uploads(infos))
        sess = SimpleNamespace(model=model, endpoint_url="", owner="", id=None)
        _e, content, _t, _y, meta = asyncio.run(handler.preprocess_message(
            "What does it say?", list(infos), sess, auto_opened_docs=[], allow_tool_preprocessing=True))
        S._invalidate_caches()
        return content, {m["name"]: m for m in meta}
    return _send


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content)


# ── what is read reaches the model whole, and says nothing more ──────────────

@pytest.mark.parametrize("name, raw, mime, marker", [
    ("notes.txt", b"plain MARKTXT words", "text/plain", "MARKTXT"),
    ("table.tsv", b"a\tb\n1\tMARKTSV\n", "text/tab-separated-values", "MARKTSV"),
    ("data.json", b'{"k": "MARKJSON"}', "application/json", "MARKJSON"),
    ("report.pdf", _minimal_pdf("MARKPDF"), "application/pdf", "MARKPDF"),
    ("brief.docx", office_fixture(".docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", OFFICE_SENTINEL),
    ("letter.odt", office_fixture(".odt"), "application/vnd.oasis.opendocument.text", OFFICE_SENTINEL),
], ids=["txt", "tsv", "json", "pdf", "docx", "odt"])
def test_a_file_that_is_read_reaches_the_model_and_needs_no_note(send, name, raw, mime, marker):
    content, meta = send([(name, raw, mime)])
    assert marker in _text(content)
    assert not meta[name].get("reach_note"), meta[name]


# ── what is not read is said, to the person and to the model ────────────────

@pytest.mark.parametrize("name, raw, mime, says", [
    ("bundle.zip", _zip(), "application/zip", "Not read: there is no reader for .zip files"),
    ("blob.bin", bytes(range(256)) * 4, "application/octet-stream", "Not read: there is no reader for .bin files"),
    ("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64, "video/mp4", "Not read: the model can't be given a video."),
    ("clip.webm", b"\x1aE\xdf\xa3" + b"\x00" * 64, "video/webm", "Not read: the model can't be given a video."),
], ids=["zip", "bin", "mp4", "video-webm"])
def test_a_file_nothing_reads_is_said_under_it(send, name, raw, mime, says):
    content, meta = send([(name, raw, mime)])
    assert (meta[name].get("reach_note") or "").startswith(says), meta[name]
    assert meta[name]["reach"] == "not_read"
    assert f"[Attached file: {name} — contents not read." in _text(content)
    assert not isinstance(content, list), "no part the model's API would refuse"


@pytest.mark.skipif(_markitdown_installed(), reason="markitdown reads these where it is installed")
@pytest.mark.parametrize("ext", [".pptx", ".xls", ".epub"])
def test_an_office_file_needing_the_optional_reader_says_so(send, ext):
    _content, meta = send([(f"deck{ext}", office_fixture(ext), "application/octet-stream")])
    assert meta[f"deck{ext}"]["reach_note"] == (
        f"Not read: {ext} files need markitdown, an optional install on this server.")


# ── a recording ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, mime", [("voice.wav", "audio/wav"), ("song.mp3", "audio/mpeg"),
                                         ("memo.webm", "audio/webm")], ids=["wav", "mp3", "voice-webm"])
def test_a_recording_with_no_speech_to_text_is_said_not_heard(send, name, mime):
    """Measured on the base: the model got a part no API takes and no words."""
    content, meta = send([(name, _wav(), mime)])
    assert not isinstance(content, list), "the old `audio` part is gone"
    assert f"[Recording attached: {name} — not heard." in _text(content)
    assert meta[name]["reach"] == "not_heard"
    assert meta[name]["reach_note"].startswith("Not heard:")


def test_a_recording_reaches_the_model_as_its_transcript(send):
    content, meta = send([("voice.wav", _wav(), "audio/wav")], stt="the code word is MARKSPOKEN")
    assert "MARKSPOKEN" in _text(content)
    assert "[Recording attached: voice.wav — transcript]:" in _text(content)
    assert meta["voice.wav"]["reach_note"] == "The model was given a transcript of it."


# ── a file too long for the message ─────────────────────────────────────────

def test_a_cut_file_is_said_with_how_much_went(send):
    big = ("MARKSTART " + "lorem ipsum dolor " * 4000 + " MARKEND").encode()
    content, meta = send([("big.txt", big, "text/plain")])
    assert "MARKSTART" in _text(content) and "MARKEND" not in _text(content)
    note = meta["big.txt"]["reach_note"]
    assert note.startswith("Too long to send whole: the model was given the start of it (")
    assert meta["big.txt"]["reach"] == "cut"


def test_a_file_with_no_room_left_is_said_not_sent(send):
    big = ("lorem ipsum dolor " * 4000).encode()
    _content, meta = send([("one.txt", big, "text/plain"), ("two.txt", b"MARKTWO", "text/plain")])
    assert meta["two.txt"]["reach"] == "omitted"
    assert meta["two.txt"]["reach_note"].startswith("Not sent: earlier attachments filled")


# ── a picture the model is not given ────────────────────────────────────────

def test_a_picture_with_pictures_switched_off_is_said_to_both(send):
    content, meta = send([("cat.jpg", _jpeg(), "image/jpeg")], vision=False)
    assert "[Image attached: cat.jpg — not sent: pictures are switched off" in _text(content)
    assert meta["cat.jpg"]["reach_note"] == "Not sent: pictures are switched off (Settings → Vision)."


def test_a_picture_to_a_blind_model_with_no_describer_is_said_not_seen(send, monkeypatch):
    import src.chat_handler as ch
    monkeypatch.setattr(ch, "vision_answer", lambda model, url="": False)
    content, meta = send([("cat.jpg", _jpeg(), "image/jpeg")], model="local/text-box-7b")
    assert meta["cat.jpg"]["reach"] == "not_seen"
    assert meta["cat.jpg"]["reach_note"].startswith("Not seen: text-box-7b can't see pictures")


def test_a_picture_to_a_blind_model_that_was_described_says_so(send, monkeypatch):
    import src.chat_handler as ch
    monkeypatch.setattr(ch, "vision_answer", lambda model, url="": False)
    content, meta = send([("cat.jpg", _jpeg(), "image/jpeg")], model="text-box-7b",
                         describer=lambda path, owner=None: {"text": "an orange circle", "model": "vl"})
    assert "an orange circle" in _text(content)
    assert meta["cat.jpg"]["reach_note"] == "text-box-7b can't see pictures; it was given a description."


def test_a_picture_the_model_sees_needs_no_note(send):
    content, meta = send([("cat.jpg", _jpeg(), "image/jpeg")])
    assert isinstance(content, list) and any(p.get("type") == "image_url" for p in content)
    assert not meta["cat.jpg"].get("reach_note")
