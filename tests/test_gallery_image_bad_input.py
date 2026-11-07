# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2008`. A missing or unreadable picture sent to an image tool was a 500.

`POST /api/image/sharpen`, `/denoise`, `/upscale-local`, `/remove-bg` and
`/enhance-face` read the posted `image` with a bare `base64.b64decode` and
`Image.open`. Text that is not base64, base64 that is not a picture (a video
from the Gallery, say, which the agent's `edit_image` sends to remove-bg), a
value that is not text, or no `image` at all on the two routes that never
checked (sharpen and remove-bg) raised inside the route: the caller got a
bare 500, the log a traceback, and `edit_image` told the model *Internal
Server Error*. The editor never meets this, because it always posts its
canvas as a PNG.

Now each route reads the picture with `_b64_to_pil_image`, the helper
`/api/image/mask` already used: no picture is a 400 *Missing image*, one that
cannot be read is a 400 *Invalid image*, both before any model is loaded,
and a `data:` URL is read as the picture it carries. A readable picture
decodes to the same pixels as before. Sharpen's `amount` is read as denoise
reads its `strength`: a value that is not a number takes the default.

Ported from upstream Odysseus 00ecf1c7 (#6818), on top of `B1815`, which
moved the model work of these routes into worker threads.
"""
import asyncio
import base64
import io
import sys
import tempfile
import types

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

import routes.gallery_routes as gallery_routes

ROUTES = ("sharpen", "denoise", "upscale-local", "remove-bg", "enhance-face")


def _png(mode="RGB"):
    buf = io.BytesIO()
    colour = (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)
    Image.new(mode, (4, 4), colour).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _picture(b64):
    return Image.open(io.BytesIO(base64.b64decode(b64)))


class _Request:
    """All these routes read of a request: its JSON body."""

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture
def post(monkeypatch, tmp_path):
    """Each route, called as the app calls it, with every model a stand-in
    that hands the picture back unchanged and notes that it ran."""
    ran = []

    def module(name, **attrs):
        fake = types.ModuleType(name)
        fake.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, fake)

    class RealESRGANer:
        def __init__(self, **kwargs):
            ran.append("Real-ESRGAN")

        def enhance(self, arr, outscale=1):
            return arr, None

    class GFPGANer:
        def __init__(self, **kwargs):
            ran.append("GFPGAN")

        def enhance(self, img, **kwargs):
            return None, None, img

    module("rembg", remove=lambda img: ran.append("rembg") or img)
    module("realesrgan", RealESRGANer=RealESRGANer)
    module("realesrgan.archs")
    module("realesrgan.archs.srvgg_arch", SRVGGNetCompact=lambda **kwargs: None)
    module("basicsr")
    module("basicsr.archs")
    module("basicsr.archs.rrdbnet_arch", RRDBNet=lambda **kwargs: None)
    module("gfpgan", GFPGANer=GFPGANer)
    module("cv2", COLOR_RGB2BGR=4, COLOR_BGR2RGB=4, cvtColor=lambda arr, code: np.asarray(arr))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))   # GFPGAN's model folder
    monkeypatch.setattr(gallery_routes, "require_privilege", lambda *args: "alice")
    routes = {r.path: r for r in gallery_routes.setup_gallery_routes().routes}

    def call(name, body):
        return asyncio.run(routes[f"/api/image/{name}"].endpoint(_Request(body)))

    call.ran = ran
    return call


def _refused(post, name, body):
    with pytest.raises(HTTPException) as refused:
        post(name, body)
    assert refused.value.status_code == 400
    return refused.value.detail


@pytest.mark.parametrize("name", ROUTES)
@pytest.mark.parametrize("image", [
    "!!notb64",
    base64.b64encode(b"hello").decode(),
    base64.b64encode(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32).decode(),
    5,
], ids=["not-base64", "not-a-picture", "a-video", "not-text"])
def test_a_picture_that_cannot_be_read_is_a_400_before_any_model_runs(post, name, image):
    assert _refused(post, name, {"image": image}) == "Invalid image"
    assert post.ran == []


@pytest.mark.parametrize("name", ["sharpen", "remove-bg"])
def test_no_picture_is_a_400_on_the_two_routes_that_never_checked(post, name):
    assert _refused(post, name, {}) == "Missing image"
    assert post.ran == []


@pytest.mark.parametrize("name", ["denoise", "upscale-local", "enhance-face"])
def test_no_picture_is_still_the_400_it_was(post, name):
    assert _refused(post, name, {}) == "No image provided"


@pytest.mark.parametrize("name", ROUTES)
def test_a_readable_picture_comes_back_as_it_did(post, name):
    mode = "RGBA" if name == "remove-bg" else "RGB"
    sent = _png(mode)
    answer = post(name, {"image": sent})
    back = _picture(answer["image"])
    assert back.size == (4, 4)
    if name != "sharpen":
        # Every stand-in hands the picture back, so only the decode shows.
        assert back.convert(mode).tobytes() == _picture(sent).convert(mode).tobytes()


def test_a_data_url_is_read_as_the_picture_it_carries(post):
    answer = post("sharpen", {"image": "data:image/png;base64," + _png()})
    assert _picture(answer["image"]).size == (4, 4)


@pytest.mark.parametrize("amount", ["strong", None, [1]])
def test_a_sharpen_amount_that_is_not_a_number_takes_the_default(post, amount):
    answer = post("sharpen", {"image": _png(), "amount": amount})
    default = post("sharpen", {"image": _png()})
    assert answer["image"] == default["image"]
