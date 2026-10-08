# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx5-vision — a person's picture goes to the model, labelled as what it is.

The owner, 2026-10-08: *"attaching an image to the chat, doesnt actually feed
said image to the LLM."* The cause of the report was in the page
(`B-NEW-1`, `tests/test_a_new_chats_first_message_takes_its_pictures_js.py`);
checking the rest of the way to the model (Law 3) found two more ways a
picture did not arrive as a picture, both measured on `0345288`:

* **`B-NEW-2`, the name list decided a model could not see.** With nothing from
  the endpoint, `model_supports_vision` fell back to a list of model names, and a
  name the list did not know was text-only: the picture was taken out of the
  message and replaced with *"[No vision model configured — set one in Settings →
  Vision]"*. Driven in Chromium against a fake OpenAI-compatible server listing
  `text-box-7b`: the model was sent no picture. `D-2026-10-07-02` §1 rules out a
  list written in the code standing in for what a model is; a model nothing
  knows about is now sent the picture, and one that refuses it says so in the
  chat (`chatStreamErrors.replyErrorSentence`). An endpoint that says the model
  cannot see still gets the description, as before.
* **Every `.jpg` was labelled `data:image/jpg`.** The label was `image/<file
  extension>`. `image/jpg` is not a registered type, and Anthropic's image block
  takes `image/jpeg`, `image/png`, `image/gif` or `image/webp` only, so a phone
  photo to Claude was a refused request. The label is now what the bytes are.

Driven, not read (`Law 20`): the real `build_user_content`, the real
`ChatHandler.preprocess_message` (with `B970`'s fake Ollama at the httpx
transport for the endpoint's answer), and the real Anthropic payload builder.
"""
from __future__ import annotations

import base64
import io

from test_a_model_that_says_it_can_see_is_shown_the_picture import (  # noqa: F401  (`net` is a fixture)
    OLLAMA, TEXT_NAMED, _attach, _has_picture, _show, net,
)


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), (200, 80, 30)).save(buf, "JPEG")
    return buf.getvalue()


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


class _Uploads:
    """The upload handler's surface `build_user_content` reads, over one real file."""

    def __init__(self, path, name, mime):
        self.info = {"id": "att-1", "name": name, "path": str(path), "mime": mime, "size": path.stat().st_size}

    def resolve_upload(self, att_id, owner=None):
        return dict(self.info)

    def _inside_upload_dir(self, path):
        return True

    def is_image_file(self, name, mime=""):
        return True

    def is_audio_file(self, name, mime=""):
        return False

    def is_document_file(self, name, mime=""):
        return False


def _sent(tmp_path, raw: bytes, stored_as: str, name: str, mime: str):
    """The `image_url` part `build_user_content` makes for one stored picture."""
    from src.document_processor import build_user_content
    path = tmp_path / stored_as
    path.write_bytes(raw)
    content = build_user_content("what is this?", ["att-1"], str(tmp_path), _Uploads(path, name, mime))
    parts = [p for p in content if isinstance(p, dict) and p.get("type") == "image_url"]
    assert len(parts) == 1, content
    head, _, data = parts[0]["image_url"]["url"].partition(",")
    return content, head, base64.b64decode(data)


# ── the label ────────────────────────────────────────────────────────────────

def test_a_phone_photo_is_labelled_image_jpeg_with_its_own_bytes(tmp_path):
    raw = _jpeg()
    _c, head, got = _sent(tmp_path, raw, "IMG_2041.jpg", "IMG_2041.jpg", "image/jpeg")
    assert got == raw, "the model was not sent the bytes the person attached"
    assert head == "data:image/jpeg;base64", (
        f"{head!r}: `image/jpg` names no type, and Anthropic refuses it"
    )


def test_the_label_is_what_the_bytes_are_not_what_the_name_says(tmp_path):
    """A screenshot saved as `.jpg` is a PNG; Anthropic checks the bytes against
    the label it is given."""
    raw = _png()
    _c, head, got = _sent(tmp_path, raw, "screenshot.jpg", "screenshot.jpg", "image/jpeg")
    assert got == raw
    assert head == "data:image/png;base64"


def test_a_pasted_picture_with_no_extension_keeps_its_type(tmp_path):
    raw = _png()
    _c, head, _got = _sent(tmp_path, raw, "paste", "paste", "image/png")
    assert head == "data:image/png;base64"


def test_the_label_reader_names_the_four_types_and_reads_jpg_as_jpeg():
    from src.document_processor import image_media_type
    assert image_media_type(_jpeg()) == "image/jpeg"
    assert image_media_type(_png()) == "image/png"
    assert image_media_type(b"GIF89a....") == "image/gif"
    assert image_media_type(b"RIFF\x10\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert image_media_type(b"", ".jpg") == "image/jpeg"
    assert image_media_type(b"", "", "image/jpg") == "image/jpeg"
    assert image_media_type(b"", "", "image/webp") == "image/webp"


# ── the Anthropic path ───────────────────────────────────────────────────────

def test_the_anthropic_request_carries_an_image_block_of_the_photo(tmp_path):
    from src.llm_core import _build_anthropic_payload
    raw = _jpeg()
    content, _head, _got = _sent(tmp_path, raw, "IMG_2041.jpg", "IMG_2041.jpg", "image/jpeg")
    payload = _build_anthropic_payload("claude-sonnet-4-5", [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": content},
    ], 0.7, 1024)
    blocks = payload["messages"][0]["content"]
    images = [b for b in blocks if b.get("type") == "image"]
    assert images == [{"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(raw).decode()}}], images
    assert [b["type"] for b in blocks] == ["text", "image"]


def test_a_picture_labelled_image_jpg_elsewhere_is_sent_to_anthropic_as_jpeg():
    """A label made before this fix, or by a tool, still reaches Claude."""
    from src.llm_core import _build_anthropic_payload
    data = base64.b64encode(_jpeg()).decode()
    payload = _build_anthropic_payload("claude-sonnet-4-5", [{"role": "user", "content": [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpg;base64,{data}"}}]}], 0.7, 1024)
    source = payload["messages"][0]["content"][1]["source"]
    assert source == {"type": "base64", "media_type": "image/jpeg", "data": data}


# ── who decides whether the model sees it (`B-NEW-2`) ───────────────────────

def test_a_model_nothing_knows_about_is_sent_the_picture(net, tmp_path, monkeypatch):
    """Measured on the base: a name the list does not know, on an endpoint
    that says nothing, had its picture swapped for a line of words."""
    from src.chat_helpers import is_vision_model
    assert is_vision_model(TEXT_NAMED) is False, "premise: the name list does not know it"
    content, vl = _attach(tmp_path, monkeypatch, TEXT_NAMED, OLLAMA)   # /api/show: 404
    assert _has_picture(content), (
        "the picture was taken out of the message on a guess from the model's name"
    )
    assert vl == [], "a describer was asked to stand in for a model nobody said was blind"


def test_an_endpoint_too_old_to_say_leaves_the_picture_in(net, tmp_path, monkeypatch):
    net.show[TEXT_NAMED] = {"modelfile": "", "details": {}}       # Ollama before `capabilities`
    content, vl = _attach(tmp_path, monkeypatch, TEXT_NAMED, OLLAMA)
    assert _has_picture(content) and vl == []


def test_a_model_with_no_endpoint_named_is_sent_the_picture(tmp_path, monkeypatch):
    content, vl = _attach(tmp_path, monkeypatch, "text-box-7b", "")
    assert _has_picture(content) and vl == []


def test_an_endpoint_that_says_it_cannot_see_still_gets_words(net, tmp_path, monkeypatch):
    """The change is narrow: only *unknown* changed. A model whose endpoint
    says it takes no images is still given the description, as before."""
    net.show[TEXT_NAMED] = _show("completion", "tools")
    content, vl = _attach(tmp_path, monkeypatch, TEXT_NAMED, OLLAMA)
    assert not _has_picture(content)
    assert "a grey square" in content and len(vl) == 1


def test_the_answer_is_three_way(net):
    from src.chat_helpers import model_supports_vision, vision_answer
    net.show[TEXT_NAMED] = _show("completion", "vision")
    assert vision_answer(TEXT_NAMED, OLLAMA) is True
    assert vision_answer("llava:7b", "") is True              # the list names a family that sees
    assert vision_answer("text-box-7b", "") is None           # nothing knows: unknown, not no
    # A tool's picture still asks the yes/no question it always asked.
    assert model_supports_vision("text-box-7b", "") is False

