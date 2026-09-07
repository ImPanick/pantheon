# SPDX-License-Identifier: AGPL-3.0-or-later
"""`edit_image` advertised four actions and posted all four to routes that do
not exist (`H03`).

The path matched `/api/gallery/{image_id}` — GET/PATCH/DELETE only — so every
call 405'd, and the old code read `data.get("error")` off a body that had none
and returned the bare string `"upscale failed"`. The model was told it could do
four things, was given no hint the URL was wrong, and had no way to find out.

That is the product lying to the model, which the discovery audit ranked first
by harm: the model repeats the lie to a person as fact.

The test that matters most is `test_every_advertised_action_posts_to_a_route_that_exists`.
It resolves the paths against the REAL mounted app, so this cannot regress into
a second plausible-looking path map.
"""
import asyncio
import base64
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _schema():
    import src.agent_tools  # noqa: F401  (resolves the circular import cluster)
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    for entry in FUNCTION_TOOL_SCHEMAS:
        fn = entry.get("function") or {}
        if fn.get("name") == "edit_image":
            return fn
    raise AssertionError("edit_image is not in the function schemas")


def _advertised_actions():
    props = _schema()["parameters"]["properties"]
    return set(props["action"]["enum"])


# ── the row itself ──────────────────────────────────────────────────────────

def test_every_advertised_action_posts_to_a_route_that_exists():
    """The whole row, resolved against the real mounted app.

    A map of plausible-looking paths is exactly what was there before — four of
    them, none real — so this asserts against what the application actually
    serves rather than against a second list somebody wrote.
    """
    import logging
    logging.disable(logging.CRITICAL)
    import sys
    sys.path.insert(0, str(ROOT))
    import app as app_module

    mounted = set()

    def walk(node, depth=0):
        if depth > 8:
            return
        for route in getattr(node, "routes", []) or []:
            path = getattr(route, "path", None)
            if path:
                mounted.add((path, frozenset(getattr(route, "methods", set()) or [])))
            for attr in ("original_router", "router", "app"):
                inner = getattr(route, attr, None)
                if inner is not None and inner is not node:
                    walk(inner, depth + 1)

    walk(app_module.app)
    logging.disable(logging.NOTSET)

    from src.tools.image import EDIT_IMAGE_ROUTES
    post_paths = {p for p, methods in mounted if "POST" in methods}
    for action, (path, _style) in EDIT_IMAGE_ROUTES.items():
        assert path in post_paths, \
            f"{action} posts to {path}, which the app does not serve as POST"


def test_the_old_paths_really_did_not_exist():
    """Recorded so the fix is not credited to something else. `/api/gallery/upscale`
    and friends are not routes; `/api/gallery/{image_id}` is, and it does not
    take POST — which is why the failure was a 405 with no error body."""
    gallery = (ROOT / "routes" / "gallery" / "gallery_routes.py").read_text(encoding="utf-8")
    for action in ("upscale", "rembg", "inpaint", "harmonize"):
        assert f'@router.post("/api/gallery/{action}")' not in gallery


def test_the_enum_and_the_route_map_cannot_drift():
    """Two lists that must agree, in different files. Advertising an action with
    no route is the defect; having a route nobody advertises is dead code."""
    from src.tools.image import EDIT_IMAGE_ROUTES
    assert _advertised_actions() == set(EDIT_IMAGE_ROUTES)


def test_inpaint_is_no_longer_advertised_and_says_why():
    """It needs a mask marking the area to replace, and a caller holding only an
    `image_id` cannot produce one. An action that cannot work is worse
    advertised than absent: absent, the model routes around it; advertised, it
    burns a turn and reports a failure the user cannot act on."""
    from src.tools.image import do_edit_image, EDIT_IMAGE_UNSUPPORTED
    assert "inpaint" not in _advertised_actions()
    assert "inpaint" in EDIT_IMAGE_UNSUPPORTED

    out = asyncio.run(do_edit_image(json.dumps({"image_id": "x", "action": "inpaint"})))
    assert out["exit_code"] == 1
    assert "mask" in out["error"].lower()
    assert "editor" in out["error"].lower(), \
        "the refusal does not say where the capability actually lives"


def test_the_description_points_inpainting_somewhere_real():
    assert "inpaint" in _schema()["description"].lower()


# ── the call shapes ─────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Client:
    def __init__(self, response=None, boom=None):
        self.response = response or _Resp(200, {"image": base64.b64encode(b"edited").decode()})
        self.boom = boom
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.boom:
            raise self.boom
        return self.response


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """The gallery I/O replaced; the HTTP call shape is what is under test."""
    import httpx
    import src.tools.image as mod

    saved = {}
    monkeypatch.setattr(mod, "_load_gallery_image",
                        lambda image_id, owner: (b"original-bytes", "src.png", None))

    def _save(data, *, owner, prompt, model, source=None):
        saved.update(data=data, owner=owner, prompt=prompt, model=model)
        return "new-image-id"
    monkeypatch.setattr(mod, "_save_gallery_image", _save)

    # The lookup after saving, for the returned image_url.
    import core.database as core_db
    monkeypatch.setattr(core_db, "SessionLocal", lambda: _NullSession())

    # `P15-06` put these calls behind `paced_http`, so that is the seam to
    # stub. Patching `httpx.AsyncClient` here would stub a client nothing
    # constructs and the tests would exercise a transport they no longer use —
    # the same "a stub that survives the code moving out from under it" failure
    # `P15-06` found in the DuckDuckGo test.
    from src import paced_http
    client = _Client()

    async def _post(url, **kwargs):
        return await client.post(url, **kwargs)
    monkeypatch.setattr(paced_http, "post", _post)
    return client, saved


class _NullSession:
    def query(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def first(self):
        return None

    def close(self):
        pass


def _run(action, **extra):
    from src.tools.image import do_edit_image
    args = {"image_id": "img-1", "action": action}
    args.update(extra)
    return asyncio.run(do_edit_image(json.dumps(args), owner="alice"))


def test_upscale_sends_a_multipart_upload_not_json(stubbed):
    """`ai-upscale` reads `form.get("image")`. A JSON `image_id` would have been
    a 422 rather than a 405 — a different error, equally useless. This is why
    the route map carries a body style."""
    client, _ = stubbed
    out = _run("upscale", scale=4)
    assert out["exit_code"] == 0
    call = client.calls[0]
    assert call["url"].endswith("/api/gallery/ai-upscale")
    assert "files" in call and "image" in call["files"]
    assert call["data"]["scale"] == "4"
    assert "json" not in call


@pytest.mark.parametrize("action,path", [
    ("rembg", "/api/image/remove-bg"),
    ("harmonize", "/api/image/harmonize"),
])
def test_the_json_actions_send_the_image_as_base64(stubbed, action, path):
    client, _ = stubbed
    out = _run(action)
    assert out["exit_code"] == 0
    call = client.calls[0]
    assert call["url"].endswith(path)
    assert base64.b64decode(call["json"]["image"]) == b"original-bytes"
    assert "files" not in call


def test_every_call_carries_the_internal_headers(stubbed):
    """The second defect in the same function: it posted without
    `_internal_headers()`, so even with the right URL every one of these would
    have been refused by `require_privilege(..., "can_generate_images")`.
    Fixing the paths alone would have moved the failure from 405 to 403 and
    changed nothing the model could see."""
    from core.middleware import INTERNAL_TOOL_HEADER
    client, _ = stubbed
    for action in ("upscale", "rembg", "harmonize"):
        client.calls.clear()
        _run(action)
        assert INTERNAL_TOOL_HEADER in client.calls[0]["headers"]
        assert client.calls[0]["headers"].get("X-Pantheon-Owner") == "alice"


def test_the_edited_bytes_are_saved_and_the_new_id_returned(stubbed):
    """All three routes answer `{"image": "<base64>"}` — raw bytes, not a saved
    gallery row — so the tool has to write the result back itself. Returning the
    source id, or no id, would leave the edit nowhere the user can find."""
    _, saved = stubbed
    out = _run("rembg")
    assert saved["data"] == b"edited"
    assert saved["owner"] == "alice"
    assert saved["model"] == "edit_image:rembg"
    assert out["image_id"] == "new-image-id"
    assert "new-image-id" in out["output"]


# ── a wrong URL has to be loud ──────────────────────────────────────────────

def test_a_405_names_the_status_and_the_path(monkeypatch, stubbed):
    """The original defect in one assertion. The old code turned this into the
    bare string "upscale failed", so a routing mistake was indistinguishable
    from a model that could not upscale — which is how it survived long enough
    to become a roadmap row."""
    from src import paced_http
    client = _Client(_Resp(405, None, text="Method Not Allowed"))
    monkeypatch.setattr(paced_http, "post", client.post)
    out = _run("upscale")
    assert out["exit_code"] == 1
    assert "405" in out["error"]
    assert "/api/gallery/ai-upscale" in out["error"]
    assert out["error"] != "upscale failed"


def test_an_error_body_is_passed_through(monkeypatch, stubbed):
    from src import paced_http
    client = _Client(_Resp(503, {"error": "no image endpoint configured"}))
    monkeypatch.setattr(paced_http, "post", client.post)
    out = _run("harmonize")
    assert "no image endpoint configured" in out["error"]
    assert "503" in out["error"]


def test_a_200_with_no_image_is_a_failure_not_a_success(monkeypatch, stubbed):
    """A success path that accepts an empty response reports an edit that did
    not happen, and the model tells the user it worked."""
    from src import paced_http
    monkeypatch.setattr(paced_http, "post", _Client(_Resp(200, {"ok": True})).post)
    out = _run("rembg")
    assert out["exit_code"] == 1
    assert "no image" in out["error"].lower()


def test_a_transport_failure_names_the_path(monkeypatch, stubbed):
    from src import paced_http
    monkeypatch.setattr(paced_http, "post", _Client(boom=OSError("connection refused")).post)
    out = _run("rembg")
    assert out["exit_code"] == 1
    assert "/api/image/remove-bg" in out["error"]


def test_an_unknown_action_lists_the_ones_that_work():
    from src.tools.image import do_edit_image
    out = asyncio.run(do_edit_image(json.dumps({"image_id": "x", "action": "sharpen"})))
    assert out["exit_code"] == 1
    for action in ("upscale", "rembg", "harmonize"):
        assert action in out["error"]


def test_a_missing_image_is_reported_before_any_request(monkeypatch):
    """An unreadable id must not become an HTTP error about something else."""
    from src import paced_http
    import src.tools.image as mod
    monkeypatch.setattr(mod, "_load_gallery_image", lambda image_id, owner: (b"", "", None))
    client = _Client()
    monkeypatch.setattr(paced_http, "post", client.post)
    out = _run("rembg")
    assert out["exit_code"] == 1
    assert "gallery image" in out["error"].lower()
    assert client.calls == [], "it made a request for an image it could not read"
