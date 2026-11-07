# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1815`. A picture worked on by a local model froze the whole server.

The editor's Remove background (rembg), Denoise and AI Upscale (Real-ESRGAN),
Enhance face (GFPGAN) and smart mask (SAM, with OWL-ViT for a mask asked for
by name) each ran its model inside its `async def` route, on the event loop.
While one person's picture was worked on, seconds on a GPU and minutes on a
CPU, every other request on the install waited, chat streams included. The
agent's `edit_image` rembg action reaches the same route over the loopback.

Now each model runs in a worker thread (`asyncio.to_thread`, the file's own
convention). SAM and OWL-ViT are loaded once and shared by every request, so
masks are still made one at a time: the lock is taken on the loop before the
work moves to its thread. Upstream Odysseus moved rembg off the loop in
e5e23e64; the other four are the same defect in the same file.

Driven: the real routes over ASGI, two requests at once, each model a
stand-in that notes whether it is running on the event loop's thread.
"""
import asyncio
import base64
import contextlib
import io
import sys
import tempfile
import threading
import time
import types

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from PIL import Image

import routes.gallery_routes as gallery_routes


def _png() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class _Tensor:
    """As much of a torch tensor as the mask route reads."""

    def __init__(self, values):
        self.array = np.asarray(values)
        self.ndim = self.array.ndim

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.array


@pytest.fixture
def models(monkeypatch, tmp_path):
    """Every model the image routes run, faked. Each notes where it ran."""
    runs = []                       # (model, whether it ran on the event loop's thread)
    masks = {"now": 0, "most": 0}   # SAM runs under way at once
    counting = threading.Lock()

    def ran(model):
        try:
            asyncio.get_running_loop()
            runs.append((model, True))
        except RuntimeError:
            runs.append((model, False))

    def module(name, **attrs):
        fake = types.ModuleType(name)
        fake.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, fake)

    def remove(img):
        ran("rembg")
        return img

    class RealESRGANer:
        def __init__(self, **kwargs):
            ran("Real-ESRGAN")

        def enhance(self, arr, outscale=1):
            return arr, None

    class GFPGANer:
        def __init__(self, **kwargs):
            ran("GFPGAN")

        def enhance(self, img, **kwargs):
            return None, None, img

    module("rembg", remove=remove)
    module("realesrgan", RealESRGANer=RealESRGANer)
    module("realesrgan.archs")
    module("realesrgan.archs.srvgg_arch", SRVGGNetCompact=lambda **kwargs: None)
    module("basicsr")
    module("basicsr.archs")
    module("basicsr.archs.rrdbnet_arch", RRDBNet=lambda **kwargs: None)
    module("gfpgan", GFPGANer=GFPGANer)
    module("cv2", COLOR_RGB2BGR=4, COLOR_BGR2RGB=4, cvtColor=lambda arr, code: arr)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))   # GFPGAN's model folder

    class SamProcessor:
        def __init__(self):
            self.image_processor = self

        def __call__(self, image, **kwargs):
            return {"original_sizes": _Tensor([[4, 4]]), "reshaped_input_sizes": _Tensor([[4, 4]])}

        def post_process_masks(self, masks, original_sizes, reshaped_sizes):
            return [_Tensor(np.ones((4, 4)))]

    def sam(**inputs):
        ran("SAM")
        with counting:
            masks["now"] += 1
            masks["most"] = max(masks["most"], masks["now"])
        time.sleep(0.1)
        with counting:
            masks["now"] -= 1
        return types.SimpleNamespace(pred_masks=_Tensor(np.ones((1, 1, 4, 4))), iou_scores=_Tensor([[1.0]]))

    sam_backend = {"torch": types.SimpleNamespace(no_grad=contextlib.nullcontext),
                   "processor": SamProcessor(), "model": sam, "device": "cpu", "model_id": "sam"}

    def ground(image, text):
        ran("OWL-ViT")
        return {"box": [0.0, 0.0, 4.0, 4.0], "label": text}

    monkeypatch.setattr(gallery_routes, "_load_sam_backend", lambda: sam_backend)
    monkeypatch.setattr(gallery_routes, "_ground_text_to_box", ground)
    monkeypatch.setattr(gallery_routes, "require_privilege", lambda request, privilege: None)
    app = FastAPI()
    app.include_router(gallery_routes.setup_gallery_routes())
    return app, runs, masks


@pytest.mark.asyncio
@pytest.mark.parametrize("path, extra, answer, models_run", [
    pytest.param("/api/image/remove-bg", {}, "image", {"rembg"}, id="remove-background"),
    pytest.param("/api/image/denoise", {}, "image", {"Real-ESRGAN"}, id="denoise"),
    pytest.param("/api/image/upscale-local", {"scale": 2}, "image", {"Real-ESRGAN"}, id="upscale"),
    pytest.param("/api/image/enhance-face", {}, "image", {"GFPGAN"}, id="enhance-face"),
    pytest.param("/api/image/mask", {"points": [{"x": 1, "y": 1}]}, "mask", {"SAM"}, id="mask"),
    pytest.param("/api/image/mask", {"text": "the cat"}, "mask", {"OWL-ViT", "SAM"}, id="mask-by-name"),
])
async def test_an_image_model_runs_in_a_worker_thread_and_masks_one_at_a_time(
        models, path, extra, answer, models_run):
    app, runs, masks = models

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gallery.test") as client:
        answers = await asyncio.gather(*[client.post(path, json={"image": _png(), **extra})
                                         for _ in range(2)])

    assert [(a.status_code, answer in a.json()) for a in answers] == [(200, True)] * 2
    assert {model for model, _ in runs} == models_run
    assert [model for model, on_the_loop in runs if on_the_loop] == [], "a model ran on the event loop"
    assert masks["most"] <= 1, "two masks ran at once on the shared models"
