# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B163` — the Caption button on an SVG, and what it should do instead.

`GET /api/upload/{id}/vision` gated on ``mime.startswith("image/")``, which
``image/svg+xml`` satisfies, so pressing Caption on a diagram base64'd its XML
and posted it to the vision model — **labelled ``data:image/jpeg``**, because
``analyze_image_with_vl_result``'s ``mime_map`` has no ``.svg`` and falls back to
jpeg. An outbound call that cannot succeed (`Law 16`), on the one upload type
this product had already decided is markup rather than pixels (`B103`).

**The row proposed gating on ``upload_handler.is_image_file``, and measuring
that showed it would cost more than it fixed.** That register is
``{.png .jpg .jpeg .webp .gif}``, while the route accepts every ``image/*`` MIME
and ``static/js/chatRenderer.js`` draws — and offers this button for — `.bmp`
too. So `.bmp`, `.tiff`, `.avif` and `.heic` reach the model today, and swapping
the MIME prefix for that register would have taken a working button away from
four formats to fix one (`Law 1`). The question that separates SVG from those is
not "is it an image" but "is it markup", and ``svg_runtime.is_svg`` is the gate
this product already asks that with.

**The product decision, written down.** The button stays, and the caption comes
out of the file. An SVG carries its words: `<title>` and `<desc>` are the
accessible name and description the format defines for exactly this purpose, and
`<text>` runs are the labels on the drawing. That is the author's own caption,
not a guess about pixels nobody rendered, and it costs no model and no network.
A drawing with no words says so, and says the source is already in the message —
which it is, because `B76`/`B103` route `.svg` to the text arm and this row does
not change that.
"""
import asyncio
import os
from types import SimpleNamespace

import pytest

LABELLED_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="120">'
    b"<title>Payment flow</title>"
    b"<desc>Card, gateway and ledger, left to right</desc>"
    b'<rect width="240" height="120" fill="#fff"/>'
    b'<text x="10" y="40">card</text>'
    b'<text x="90" y="40">gate<tspan>way</tspan></text>'
    b'<text x="170" y="40">ledger &amp; audit</text></svg>'
)
SHAPES_ONLY_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    b'<circle cx="32" cy="32" r="30"/></svg>'
)
HOSTILE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    b"<title>Org chart</title>"
    b'<script>fetch("/api/settings").then(r=>r.text())</script>'
    b'<rect width="64" height="64"/></svg>'
)
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class _Request:
    def __init__(self):
        self.state = SimpleNamespace(current_user=None)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))
        self.client = SimpleNamespace(host="127.0.0.1")


@pytest.fixture
def vision(tmp_path, monkeypatch):
    """Drive the real `GET /api/upload/{id}/vision` over one real file.

    The vision model is replaced by a recorder rather than a stub that answers:
    what this row is about is whether the call happens at all.
    """
    import fastapi.dependencies.utils as dependency_utils
    import routes.upload_routes as upload_routes
    import src.document_processor as document_processor
    from src.upload_handler import UploadHandler

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed", lambda: None)
    calls = []
    monkeypatch.setattr(
        document_processor, "analyze_image_with_vl",
        lambda path, owner=None: calls.append((path, owner)) or "a description of pixels",
    )
    upload_dir = tmp_path / "uploads" / "2026" / "09" / "16"
    upload_dir.mkdir(parents=True, exist_ok=True)
    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))

    def _call(body: bytes, name="diagram.svg", mime="image/svg+xml", force=0):
        file_id = "d" * 32 + os.path.splitext(name)[1]
        path = upload_dir / file_id
        path.write_bytes(body)
        index = {"owner:hash": {"id": file_id, "path": str(path), "mime": mime,
                                "size": len(body), "name": name,
                                "original_name": name, "owner": "owner"}}
        monkeypatch.setattr(handler, "_load_upload_index", lambda: index)
        router, _cleanup = upload_routes.setup_upload_routes(handler)
        endpoint = {r.endpoint.__name__: r.endpoint
                    for r in router.routes}["get_vision_text"]
        result = asyncio.run(endpoint(_Request(), file_id, force=force))
        cache = tmp_path / "uploads" / ".vision" / (file_id + ".txt")
        return result, calls, cache

    return _call


# ── the row's Verify, first clause ──────────────────────────────────────────

def test_an_svg_caption_never_reaches_the_vision_model(vision):
    """Before this row the XML was base64'd and posted as `data:image/jpeg`."""
    result, calls, _cache = vision(LABELLED_SVG)
    assert calls == [], "the SVG was sent to the vision model"
    assert result["source"] == "svg"


def test_the_caption_is_the_words_the_author_put_in_the_drawing(vision):
    result, _calls, _cache = vision(LABELLED_SVG)
    text = result["text"]
    assert "Payment flow" in text                     # <title>
    assert "Card, gateway and ledger" in text         # <desc>
    assert "card" in text and "ledger & audit" in text  # <text> runs, unescaped
    assert "gateway" in text, "a <tspan> split a word in half"
    assert "<" not in text and "svg" not in text.lower(), "markup leaked into the caption"


def test_a_drawing_with_no_words_says_so_and_stores_nothing(vision):
    """An empty answer is an answer. It must not be written to the cache, which
    is also where a hand-edited caption lives (`PUT /{id}/vision`)."""
    result, calls, cache = vision(SHAPES_ONLY_SVG)
    assert calls == []
    assert result["text"].startswith("[")
    assert "no text" in result["text"].lower()
    assert not cache.exists()


def test_captioning_a_hostile_svg_runs_nothing_and_leaks_nothing(vision):
    """`B103`'s file is untrusted markup here too — it is scanned, not parsed,
    and only the character data of three elements is ever returned."""
    result, calls, _cache = vision(HOSTILE_SVG)
    assert calls == []
    assert result["text"] == "Org chart"
    assert "fetch" not in result["text"]


# ── the row's Verify, second clause: the control still works ────────────────

def test_the_caption_is_cached_so_the_button_behaves_like_the_others(vision):
    result, _calls, cache = vision(LABELLED_SVG)
    assert result["cached"] is False
    assert cache.exists() and "Payment flow" in cache.read_text(encoding="utf-8")


def test_a_hand_edited_caption_still_wins(vision, tmp_path):
    """`Law 1` — `PUT /{id}/vision` stores a correction in the same file, and a
    later `GET` must serve the correction rather than recomputing over it.

    This held before this row and has to go on holding, which is why the cache
    check stays ahead of the branch rather than inside it.
    """
    result, _calls, cache = vision(LABELLED_SVG)
    cache.write_text("the diagram the user described", encoding="utf-8")
    result, _calls, _cache = vision(LABELLED_SVG)
    assert result["text"] == "the diagram the user described"
    assert result["cached"] is True


# ── what must not have changed (`Law 1`) ────────────────────────────────────

def test_a_raster_still_goes_to_the_vision_model(vision):
    """The guard, in the form it had before this row so it means the same."""
    result, calls, _cache = vision(PNG_BYTES, name="photo.png", mime="image/png")
    assert len(calls) == 1
    assert result["text"] == "a description of pixels"
    assert result["cached"] is False


def test_the_response_says_which_answer_it_gave(vision):
    """One field, two values, so a client (and this file) can tell a caption
    read out of the file from a description a model produced."""
    svg_result, _calls, _cache = vision(LABELLED_SVG)
    png_result, _calls, _cache = vision(PNG_BYTES, name="photo.png", mime="image/png")
    assert svg_result["source"] == "svg"
    assert png_result["source"] == "vision"


@pytest.mark.parametrize("name,mime", [
    ("scan.bmp", "image/bmp"),
    ("scan.tiff", "image/tiff"),
    ("photo.avif", "image/avif"),
    ("photo.heic", "image/heic"),
])
def test_the_formats_the_rows_proposed_gate_would_have_dropped(vision, name, mime):
    """The measurement behind not using ``is_image_file``.

    None of these four is in that register, all four reach the model today, and
    `chatRenderer.js` offers the button for `.bmp`. Fixing SVG by narrowing to
    the register would have broken them (`Law 1`).
    """
    _result, calls, _cache = vision(PNG_BYTES, name=name, mime=mime)
    assert len(calls) == 1


def test_a_document_upload_is_still_refused(vision):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        vision(b"just some prose", name="notes.txt", mime="text/plain")
    assert excinfo.value.status_code == 400


def test_svg_is_still_markup_to_the_model_and_not_an_image(tmp_path):
    """`B103`'s decision, re-pinned: this row must not have moved `.svg` into
    the image arm on the way past. The source reaching the model is what makes
    "no vision call" the right answer rather than a lost capability."""
    from src.document_processor import build_user_content
    from src.upload_handler import UploadHandler

    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    assert handler.is_image_file("diagram.svg", "image/svg+xml") is False
    path = tmp_path / "uploads" / "diagram.svg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(LABELLED_SVG)
    out = build_user_content(
        "what is this", ["fid"], str(tmp_path / "uploads"), handler, owner="tester",
        resolved_uploads={"fid": {"path": str(path), "name": "diagram.svg",
                                  "mime": "image/svg+xml"}},
    )
    rendered = out if isinstance(out, str) else "".join(
        b.get("text", "") for b in out if isinstance(b, dict))
    assert "Payment flow" in rendered
    assert all(b.get("type") != "image_url" for b in (out if isinstance(out, list) else []))


# ── the extractor itself ────────────────────────────────────────────────────

def test_the_caption_is_bounded():
    """It runs on a file someone else supplied, so it has a size and a length."""
    from src.svg_runtime import SVG_CAPTION_MAX_CHARS, svg_caption_text

    body = (b'<svg xmlns="http://www.w3.org/2000/svg">'
            + b"<text>word</text>" * 5000 + b"</svg>")
    assert len(svg_caption_text(body)) == SVG_CAPTION_MAX_CHARS
    assert svg_caption_text(b"") == ""
    assert svg_caption_text(None) == ""
