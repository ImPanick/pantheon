# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B103` — an attached `.svg` can be seen, and the bytes that draw it are inert.

`B76` made an SVG's *source* reach the model, which is the right half of the
answer: most vision models reject `image/svg+xml`, and a model that sees the XML
can edit it. This file pins the other half — what the person sees — and the
security property that comes with it, because SVG is the one upload type
`.pantheon/DECISIONS.md` D-2026-08-26-01 names as a real stored-XSS vector.

Measured before this row, by driving the route below:

* `?thumb=1` on an SVG **already served the original bytes**. `image/svg+xml`
  passes `mime.startswith("image/")`, PIL then raises `UnidentifiedImageError`
  because it cannot parse SVG at all, and the except-branch fell through to
  `FileResponse(path, media_type="image/svg+xml")`. So the row's premise ("a
  person who attaches a diagram sees a generic chip") was wrong — the chat
  renderer treats `.svg` as an image by name (`static/js/chatRenderer.js`) and
  the preview did appear. What was missing was any decision behind it: an SVG
  carrying `<script>` was served exactly like a clean one, with none of the
  headers this product already applies to every SVG it serves on purpose
  (`routes/emoji_routes.py`).
* The safety gate for those headers existed, in a route module, where the upload
  path could not call it. `B103` lifted it to `src/svg_runtime.py`; both callers
  use it now (`Law 13`, `Law 14`).

The product decision, stated so the next row does not have to re-derive it: SVG
is **markup to the model and a picture to the viewer**. It is deliberately not
added to `upload_handler.is_image_file`, which would base64 it into an
`image_url` the model cannot read and take the source away again.
"""
import asyncio
import os
from types import SimpleNamespace

import pytest

SAFE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    b'<rect width="64" height="64" fill="#204080"/>'
    b'<text x="8" y="36" fill="white">arch</text></svg>'
)
HOSTILE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    b'<script>fetch("/api/settings").then(r=>r.text())</script>'
    b'<rect width="64" height="64"/></svg>'
)
BEACON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    b'<image href="https://tracker.example/pixel.png" width="64" height="64"/></svg>'
)
# The same beacon through an element the blocked-element list does not name, so
# the external-reference check is the only thing standing between this file and
# a request to someone else's server.
LINKED_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    b'<use xlink:href="https://tracker.example/sprite.svg#icon"/>'
    b'<rect width="64" height="64"/></svg>'
)


class _Request:
    def __init__(self):
        self.state = SimpleNamespace(current_user=None)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=None))
        self.client = SimpleNamespace(host="127.0.0.1")


def _serve(tmp_path, monkeypatch, body: bytes, *, thumb: int, name="diagram.svg",
           mime="image/svg+xml"):
    """Drive the real `GET /api/upload/{file_id}` over one real file on disk."""
    import fastapi.dependencies.utils as dependency_utils
    import routes.upload_routes as upload_routes
    from src.upload_handler import UploadHandler

    monkeypatch.setattr(
        dependency_utils, "ensure_multipart_is_installed", lambda: None
    )
    upload_dir = tmp_path / "uploads" / "2026" / "09" / "15"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = "d" * 32 + os.path.splitext(name)[1]
    path = upload_dir / file_id
    path.write_bytes(body)

    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    index = {
        "owner:hash": {
            "id": file_id, "path": str(path), "mime": mime, "size": len(body),
            "name": name, "original_name": name, "owner": "owner",
        }
    }
    monkeypatch.setattr(handler, "_load_upload_index", lambda: index)
    router, _cleanup = upload_routes.setup_upload_routes(handler)
    endpoint = {r.endpoint.__name__: r.endpoint for r in router.routes}["download_file"]
    return asyncio.run(endpoint(_Request(), file_id, thumb=thumb)), path


def _body_of(response, path):
    body = getattr(response, "body", None)
    if body is not None:
        return body
    # FileResponse streams from disk rather than holding bytes.
    return path.read_bytes()


# --------------------------------------------------------------------------
# What the viewer gets
# --------------------------------------------------------------------------

def test_a_clean_svg_is_previewed(tmp_path, monkeypatch):
    """The row's `Verify`, first clause: the attachment shows a picture.

    `static/js/chatRenderer.js` requests `?thumb=1` for anything named `.svg`,
    so this response is what the `<img>` in the message renders.
    """
    response, path = _serve(tmp_path, monkeypatch, SAFE_SVG, thumb=1)
    assert response.media_type == "image/svg+xml"
    assert _body_of(response, path) == SAFE_SVG


def test_a_previewed_svg_cannot_run_anything(tmp_path, monkeypatch):
    """Every header the product already puts on an SVG, now on this one too.

    `sandbox` is what makes the bytes inert in the contexts `<img>` does not
    already make inert — a direct navigation, an `<iframe>`, an `<object>` — and
    before this row the preview response carried only `nosniff`.
    """
    response, _ = _serve(tmp_path, monkeypatch, SAFE_SVG, thumb=1)
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["content-security-policy"] == "sandbox"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    assert headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize("body", [HOSTILE_SVG, BEACON_SVG, LINKED_SVG])
def test_an_active_svg_is_never_drawn(tmp_path, monkeypatch, body):
    """The sanitisation question, answered by not rendering the file at all.

    Two shapes: one that runs script, and one that fetches a third-party URL when
    rendered — a beacon telling someone else that this person opened this file
    (`Law 16`). Both get an empty image, not their own markup. The upload is
    untouched; only the preview is refused.
    """
    response, _ = _serve(tmp_path, monkeypatch, body, thumb=1)
    served = response.body
    assert b"<script" not in served
    assert b"tracker.example" not in served
    assert served != body
    assert served.startswith(b"<svg")
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert headers["content-security-policy"] == "sandbox"
    assert headers["cache-control"] == "no-store"


def test_the_file_itself_is_still_downloadable(tmp_path, monkeypatch):
    """`Law 1`. The banner in `build_user_content` promises in writing that "the
    upload itself is intact and can be downloaded", and a refused *preview* must
    not quietly become a refused *file* — including for the hostile one, which
    someone may well want to inspect.
    """
    for body in (SAFE_SVG, HOSTILE_SVG):
        response, path = _serve(tmp_path, monkeypatch, body, thumb=0)
        assert _body_of(response, path) == body


@pytest.mark.parametrize("thumb", [0, 1])
def test_no_route_serves_svg_bytes_that_a_browser_would_render(tmp_path, monkeypatch, thumb):
    """The row's `Verify`, second clause, driven over both ways in.

    "Renderable content type and no attachment disposition" is the combination
    that makes a stored SVG a stored XSS: a link to it renders as a document in
    the user's origin. Either half missing is enough, and both are present here.
    """
    response, _ = _serve(tmp_path, monkeypatch, SAFE_SVG, thumb=thumb)
    headers = {k.lower(): v for k, v in response.headers.items()}
    assert response.media_type == "image/svg+xml"
    assert headers.get("content-disposition", "").startswith("attachment")
    assert headers.get("content-security-policy") == "sandbox"


def test_an_svg_named_anything_is_still_handled_by_content_type(tmp_path, monkeypatch):
    """A sniffed `image/svg+xml` with no suffix takes the same path.

    `upload_handler.detect_content_type` is libmagic where python-magic is
    installed (the Docker image) and `mimetypes` otherwise, so both halves of the
    classifier have to agree or the hardening depends on how the file was named.
    """
    response, _ = _serve(
        tmp_path, monkeypatch, HOSTILE_SVG, thumb=1, name="drawing", mime="image/svg+xml",
    )
    assert b"<script" not in response.body
    assert {k.lower() for k in response.headers}.issuperset(
        {"content-security-policy", "x-content-type-options"}
    )


# --------------------------------------------------------------------------
# What the model gets — `B76`, pinned so this row cannot undo it
# --------------------------------------------------------------------------

def test_the_model_still_receives_the_svg_source(tmp_path):
    """The decision behind this row, in the form of a test.

    Making `.svg` an image for the *viewer* must not make it an image for the
    *model*: `is_image_file` is the switch that base64s a file into an
    `image_url`, and most vision models reject `image/svg+xml` outright. So the
    picture and the prose come from two different questions about the same file.
    """
    from src.document_processor import build_user_content
    from src.upload_handler import UploadHandler

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / "diagram.svg"
    path.write_bytes(SAFE_SVG)
    handler = UploadHandler(str(tmp_path), str(upload_dir))

    assert not handler.is_image_file("diagram.svg", "image/svg+xml")
    out = build_user_content(
        "what does this show", ["fid"], str(upload_dir), handler, owner="tester",
        resolved_uploads={"fid": {
            "path": str(path), "name": "diagram.svg", "mime": "image/svg+xml",
        }},
    )
    text = out if isinstance(out, str) else "".join(
        b.get("text", "") for b in out if isinstance(b, dict))
    assert "<rect" in text and "arch" in text
    assert "[Type: svg," in text
    assert "base64" not in text


def test_the_two_svg_callers_share_one_gate(tmp_path, monkeypatch):
    """`Law 13`, proved by moving the gate and watching both callers move.

    The emoji route and the upload preview ask the same question about the same
    kind of bytes. A copy of the check in either file passes every other test
    here and cannot pass this one.
    """
    import routes.emoji_routes as emoji_routes
    import src.svg_runtime as svg_runtime

    import routes.upload_routes as upload_routes

    # The constants are the same objects, not equal copies.
    assert emoji_routes._BLOCKED_SVG_RE is svg_runtime.BLOCKED_SVG_RE
    assert emoji_routes._SVG_SECURITY_HEADERS is svg_runtime.SVG_SECURITY_HEADERS
    assert upload_routes.SVG_SECURITY_HEADERS is svg_runtime.SVG_SECURITY_HEADERS

    # And one function answers for both routes: break it, and both refuse.
    monkeypatch.setattr(svg_runtime, "is_safe_svg", lambda content, *a, **k: False)
    monkeypatch.setattr(emoji_routes, "_GLYPHS", {"1f600": '<path d="M0 0"/>'})
    assert asyncio.run(_emoji_endpoint()("1f600")).body == svg_runtime.BLANK_SVG
    response, _ = _serve(tmp_path, monkeypatch, SAFE_SVG, thumb=1)
    assert response.body == svg_runtime.BLANK_SVG


def _emoji_endpoint():
    import routes.emoji_routes as emoji_routes

    router = emoji_routes.setup_emoji_routes()
    for route in router.routes:
        if route.path == "/api/emoji/{code}.svg" and "GET" in route.methods:
            return route.endpoint
    raise AssertionError("emoji route not found")
