"""Image-domain tool implementations.

Extracted from tool_implementations.py as part of slice 1 (#4082/#4071).
Holds the edit_image (gallery) tool.
``src.tool_implementations`` re-exports these for backward compatibility.
``_INTERNAL_BASE`` still lives in tool_implementations.py and is pulled back
function-locally here.

── `H03`: four advertised actions, four URLs that do not exist ──────────────

`edit_image` offered `upscale · rembg · inpaint · harmonize` and posted every
one of them to `{base}/api/gallery/{action}`. **None of the four routes
existed.** The path matched `/api/gallery/{image_id}` — GET/PATCH/DELETE only —
so every call 405'd, and the old code read `data.get("error")`, found none, and
returned the bare string `"upscale failed"`. The model was told it could do four
things, was given no hint that the URL was wrong, and had no way to find out.

That is the product lying to the model, which the discovery audit ranked first
by harm precisely because the model then repeats the lie to a person as fact.

All the capabilities were real the whole time, under other names, and **the
bodies differ — which is why this is a rewrite and not a path map**:

    upscale    POST /api/gallery/ai-upscale   multipart: image file + scale
    rembg      POST /api/image/remove-bg      json: {image: <base64>}
    harmonize  POST /api/image/harmonize      json: {image: <base64>, prompt?}

All three answer `{"image": "<base64>"}` — raw bytes, not a saved gallery
row — so this reads the source image off disk, calls the route, and writes the
result back into the gallery itself.

**`inpaint` is removed from the enum rather than left advertised.** It needs a
mask, and there is no way for a model holding an `image_id` to produce one. An
action that cannot work is worse advertised than absent: absent, the model
routes around it; advertised, it burns a turn and reports a failure the user
cannot act on.

**And a second defect in the same function:** it posted without
`_internal_headers()`, so even with the right URL every call would have been
refused by `require_privilege(request, "can_generate_images")`. Fixing the paths
alone would have moved the failure from 405 to 403 and changed nothing the model
could see.
"""
import base64
import logging
import uuid
from typing import Dict, Optional, Tuple

from src.tools._common import _parse_tool_args

logger = logging.getLogger(__name__)

# action -> (path, body style). The body style is the reason this table exists:
# `ai-upscale` takes a multipart upload and the other two take JSON, so a
# single path map would have produced three 422s instead of three 405s.
EDIT_IMAGE_ROUTES = {
    "upscale":   ("/api/gallery/ai-upscale", "multipart"),
    "rembg":     ("/api/image/remove-bg", "json"),
    "harmonize": ("/api/image/harmonize", "json"),
}

# Advertised and impossible. Named here rather than silently dropped so the
# refusal can say what is missing instead of "unknown action".
EDIT_IMAGE_UNSUPPORTED = {
    "inpaint": ("inpaint needs a mask marking the area to replace, and a tool "
                "call carrying only an image_id has no way to produce one. Use "
                "the gallery's inpaint editor, which draws the mask."),
}


def _load_gallery_image(image_id: str, owner: Optional[str]) -> Tuple[bytes, str, object]:
    """`(bytes, filename, row)` for an image this owner may edit."""
    from pathlib import Path
    from src.constants import GENERATED_IMAGES_DIR
    from core.database import GalleryImage, SessionLocal

    db = SessionLocal()
    try:
        q = db.query(GalleryImage).filter(GalleryImage.id == image_id)
        if owner:
            q = q.filter(GalleryImage.owner == owner)
        row = q.first()
        if not row or not row.filename:
            return b"", "", None
        path = Path(GENERATED_IMAGES_DIR) / row.filename
        if not path.is_file():
            return b"", row.filename, row
        return path.read_bytes(), row.filename, row
    finally:
        db.close()


def _save_gallery_image(data: bytes, *, owner: Optional[str], prompt: str,
                        model: str, source=None) -> str:
    """Write edited bytes into the gallery and return the new id."""
    from pathlib import Path
    from src.constants import GENERATED_IMAGES_DIR
    from core.database import GalleryImage, SessionLocal

    img_dir = Path(GENERATED_IMAGES_DIR)
    img_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:12]}.png"
    (img_dir / filename).write_bytes(data)

    new_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(GalleryImage(
            id=new_id,
            filename=filename,
            prompt=prompt,
            model=model,
            owner=owner,
            file_size=len(data),
            # Keep the edit beside its original rather than at the top of an
            # unrelated album — an edit that lands somewhere else is an edit
            # the person has to go and find.
            album_id=getattr(source, "album_id", None),
        ))
        db.commit()
    finally:
        db.close()
    return new_id


async def do_edit_image(content: str, owner: Optional[str] = None) -> Dict:
    """Edit a gallery image (upscale, remove background, harmonize) — `H03`."""
    from src.tool_implementations import _INTERNAL_BASE, _internal_headers

    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}

    image_id = args.get("image_id", "")
    action = (args.get("action") or "").strip().lower()
    if not image_id or not action:
        return {"error": "image_id and action are required", "exit_code": 1}

    if action in EDIT_IMAGE_UNSUPPORTED:
        return {"error": EDIT_IMAGE_UNSUPPORTED[action], "exit_code": 1}
    if action not in EDIT_IMAGE_ROUTES:
        return {"error": f"Unknown action {action!r}. Available: "
                         f"{', '.join(sorted(EDIT_IMAGE_ROUTES))}.",
                "exit_code": 1}

    source_bytes, filename, row = _load_gallery_image(image_id, owner)
    if not source_bytes:
        return {"error": f"No gallery image {image_id!r} readable by this owner.",
                "exit_code": 1}

    path, style = EDIT_IMAGE_ROUTES[action]
    url = f"{_INTERNAL_BASE}{path}"
    headers = _internal_headers(owner=owner)

    # `P15-06` — through the limiter like every other deliberate outbound call.
    # This one is loopback, so `LOCAL_POLICY` paces it at zero and the wrapper
    # costs nothing; routing it anyway is what keeps `check-outbound.py`'s count
    # monotonic, and this rewrite would otherwise have added a call to it.
    from src import paced_http
    try:
        if style == "multipart":
            resp = await paced_http.post(
                url,
                files={"image": (filename or "image.png", source_bytes, "image/png")},
                data={"scale": str(args.get("scale") or 2)},
                headers=headers,
                timeout=180,
            )
        else:
            body = {"image": base64.b64encode(source_bytes).decode()}
            if args.get("prompt"):
                body["prompt"] = args["prompt"]
            resp = await paced_http.post(url, json=body, headers=headers, timeout=180)
    except Exception as e:
        return {"error": f"{action} could not reach {path}: {type(e).__name__}: {e}",
                "exit_code": 1}

    # A wrong URL must be LOUD. The old code read `data.get("error")` off a 405
    # body that had none and returned "upscale failed", so a routing mistake was
    # indistinguishable from a model that could not upscale — which is how this
    # survived long enough to become a roadmap row.
    if resp.status_code >= 400:
        detail = ""
        try:
            payload = resp.json()
            detail = payload.get("error") or payload.get("detail") or ""
        except Exception:
            detail = (resp.text or "")[:200]
        return {"error": f"{action} failed: HTTP {resp.status_code} from {path}"
                         + (f" — {detail}" if detail else ""),
                "exit_code": 1}

    try:
        data = resp.json()
    except Exception:
        return {"error": f"{action} failed: {path} did not return JSON", "exit_code": 1}

    if data.get("error"):
        return {"error": f"{action} failed: {data['error']}", "exit_code": 1}

    edited_b64 = data.get("image")
    if not edited_b64:
        return {"error": f"{action} failed: {path} returned no image", "exit_code": 1}
    try:
        edited = base64.b64decode(edited_b64)
    except Exception:
        return {"error": f"{action} failed: {path} returned unreadable image data",
                "exit_code": 1}

    new_id = _save_gallery_image(
        edited, owner=owner,
        prompt=(args.get("prompt") or getattr(row, "prompt", "") or action),
        model=f"edit_image:{action}",
        source=row,
    )

    from core.database import GalleryImage, SessionLocal
    db = SessionLocal()
    try:
        img = db.query(GalleryImage).filter(GalleryImage.id == new_id).first()
        new_filename = img.filename if img else ""
    finally:
        db.close()

    result = {
        "output": f"Image edited ({action}). New image ID: {new_id}",
        "exit_code": 0,
        "image_id": new_id,
    }
    if new_filename:
        result.update({
            "image_url": f"/api/generated-image/{new_filename}",
            "image_prompt": args.get("prompt") or getattr(row, "prompt", "") or action,
            "image_model": f"edit_image:{action}",
        })
    return result
