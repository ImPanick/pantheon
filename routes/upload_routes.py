# SPDX-License-Identifier: AGPL-3.0-or-later
# routes/upload_routes.py
import os
import time
import json
import asyncio
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Request, File, UploadFile, HTTPException, Form
from typing import List, Optional
import logging
from core.middleware import require_admin
from core.database import (
    SessionLocal,
    ChatMessage as DbChatMessage,
    CalendarCal,
    CalendarEvent,
    Document,
    DocumentVersion,
    GalleryImage,
    Note,
    Session as DbSession,
)
from src.auth_helpers import effective_user
from src.attachment_refs import attachment_refs_from_metadata
from src.constants import GENERATED_IMAGES_DIR
from src.upload_handler import (
    MAX_FILES_PER_REQUEST,
    UploadCleanupSafetyError,
    count_recent_uploads,
    extract_upload_ids,
)
# `B103`: the SVG gate lives in one module so this route and the emoji route ask
# it the same question. Imported as the module as well, so the gate is resolved
# at call time and cannot be a second copy.
from src import svg_runtime
from src.svg_runtime import (
    MAX_PREVIEW_SVG_BYTES,
    SVG_REFUSAL_HEADER,
    SVG_SECURITY_HEADERS,
    is_svg,
    svg_caption_text,
)

logger = logging.getLogger(__name__)

UPLOAD_RESPONSE_HEADERS = {"X-Content-Type-Options": "nosniff"}

def _upload_ids_from_persisted_text(value: object) -> set[str]:
    """Return canonical upload IDs embedded in persisted text.

    This covers attachment reference lines/URIs and the PDF source markers
    stored by the document editor. False positives are intentionally
    conservative: retaining an extra upload is safer than deleting referenced
    bytes.
    """
    return extract_upload_ids(value)


def _upload_ids_from_message_metadata(raw_metadata: object) -> set[str]:
    """Extract attachment IDs from a persisted chat metadata JSON value.

    Malformed metadata raises instead of being treated as an empty reference
    set. The admin cleanup route catches that failure and aborts cleanup.
    """
    if raw_metadata in (None, ""):
        return set()
    if isinstance(raw_metadata, str):
        metadata = json.loads(raw_metadata)
    else:
        metadata = raw_metadata
    if not isinstance(metadata, dict):
        raise ValueError("chat message metadata must be a JSON object")

    attachments = metadata.get("attachments")
    if attachments is not None:
        if not isinstance(attachments, list) or any(
            not isinstance(item, dict) for item in attachments
        ):
            raise ValueError("chat message attachments metadata is malformed")

    ids = {
        str(ref["attachment_id"])
        for ref in attachment_refs_from_metadata(metadata)
        if ref.get("attachment_id")
    }
    # Preserve canonical IDs even in older metadata shapes not normalized by
    # attachment_refs_from_metadata().
    ids.update(_upload_ids_from_persisted_text(json.dumps(metadata)))
    return ids


def _collect_persisted_upload_references() -> tuple[set[str], set[str]]:
    """Collect upload IDs/hashes still referenced by durable application data.

    The caller must treat any exception as an incomplete scan and fail closed.
    There is no distinct artifact table in the current schema; artifact-like
    attachment references persisted in chat/document text are covered by the
    canonical-ID scan.
    """
    referenced_ids: set[str] = set()
    referenced_hashes: set[str] = set()
    db = SessionLocal()
    try:
        for content, raw_metadata in db.query(
            DbChatMessage.content,
            DbChatMessage.meta_data,
        ).yield_per(500):
            referenced_ids.update(_upload_ids_from_persisted_text(content))
            referenced_ids.update(_upload_ids_from_message_metadata(raw_metadata))

        for (content,) in db.query(Document.current_content).yield_per(500):
            referenced_ids.update(_upload_ids_from_persisted_text(content))

        for (content,) in db.query(DocumentVersion.content).yield_per(500):
            referenced_ids.update(_upload_ids_from_persisted_text(content))

        for filename, file_hash in db.query(
            GalleryImage.filename,
            GalleryImage.file_hash,
        ).yield_per(500):
            referenced_ids.update(_upload_ids_from_persisted_text(filename))
            if file_hash:
                referenced_hashes.add(str(file_hash))

        for image_url, color, content, items in db.query(
            Note.image_url,
            Note.color,
            Note.content,
            Note.items,
        ).yield_per(500):
            for value in (image_url, color, content, items):
                referenced_ids.update(_upload_ids_from_persisted_text(value))

        for (color,) in db.query(CalendarCal.color).yield_per(500):
            referenced_ids.update(_upload_ids_from_persisted_text(color))

        for color, description, location in db.query(
            CalendarEvent.color,
            CalendarEvent.description,
            CalendarEvent.location,
        ).yield_per(500):
            for value in (color, description, location):
                referenced_ids.update(_upload_ids_from_persisted_text(value))

        return referenced_ids, referenced_hashes
    finally:
        db.close()


def _run_reference_safe_cleanup(upload_handler) -> int:
    referenced_ids, referenced_hashes = _collect_persisted_upload_references()
    return upload_handler.cleanup_old_uploads(
        referenced_upload_ids=referenced_ids,
        referenced_upload_hashes=referenced_hashes,
    )

def setup_upload_routes(upload_handler):
    """Setup upload routes with the provided handler"""
    # B53. This `APIRouter` used to be a module global, decorated by this
    # function and returned. Calling the function twice therefore registered
    # every route twice on one router, and FastAPI dispatches to the first
    # match — so the second call's handlers, and the manager they close over,
    # were silently ignored while the call appeared to succeed. Production
    # calls it once, so nothing was broken; two test files that each build a
    # router were not, and the suite's green depended on which ran first.
    router = APIRouter(prefix="/api/upload", tags=["upload"])


    def _upload_root() -> str:
        from src.constants import UPLOAD_DIR
        return os.path.realpath(getattr(upload_handler, "upload_dir", UPLOAD_DIR))

    def _path_inside_upload_dir(path: str) -> bool:
        try:
            return os.path.commonpath([_upload_root(), os.path.realpath(path)]) == _upload_root()
        except Exception:
            return False

    def _resolve_upload_path(file_id: str) -> str:
        from src.constants import UPLOAD_DIR
        upload_root = getattr(upload_handler, "upload_dir", UPLOAD_DIR)
        direct = os.path.join(upload_root, file_id)
        if os.path.lexists(direct):
            if not _path_inside_upload_dir(direct):
                raise HTTPException(403, "Access denied")
            if os.path.isfile(direct):
                return direct
            raise HTTPException(404, "File not found")

        for root, _dirs, files in os.walk(upload_root, followlinks=False):
            if file_id not in files:
                continue
            path = os.path.join(root, file_id)
            if not _path_inside_upload_dir(path):
                raise HTTPException(403, "Access denied")
            if os.path.isfile(path):
                return path
            raise HTTPException(404, "File not found")

        raise HTTPException(404, "File not found")

    def _valid_session_id_for_owner(db, session_id: str | None, owner: str | None) -> str | None:
        if not session_id:
            return None
        sess = db.query(DbSession).filter(DbSession.id == session_id).first()
        if not sess:
            return None
        if owner and sess.owner and sess.owner != owner:
            return None
        return session_id

    def _promote_chat_image_to_gallery(meta: dict, owner: str | None, session_id: str | None = None) -> str | None:
        """Make chat-uploaded images visible in Gallery without changing chat storage."""
        is_image_file = getattr(upload_handler, "is_image_file", None)
        if not callable(is_image_file):
            return None
        if not is_image_file(meta.get("name", ""), meta.get("mime", "")):
            return None

        source_path = meta.get("path")
        if not source_path or not os.path.isfile(source_path):
            return None

        db = SessionLocal()
        try:
            file_hash = meta.get("hash")
            if file_hash:
                q = db.query(GalleryImage).filter(
                    GalleryImage.file_hash == file_hash,
                    GalleryImage.is_active == True,  # noqa: E712
                )
                if owner:
                    q = q.filter(GalleryImage.owner == owner)
                existing = q.first()
                if existing:
                    return existing.id

            image_dir = Path(GENERATED_IMAGES_DIR)
            image_dir.mkdir(parents=True, exist_ok=True)
            ext = Path(meta.get("name") or source_path).suffix.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                mime_ext = {
                    "image/png": ".png",
                    "image/jpeg": ".jpg",
                    "image/jpg": ".jpg",
                    "image/webp": ".webp",
                    "image/gif": ".gif",
                }.get(meta.get("mime", ""))
                ext = mime_ext or ".png"
            filename = f"{uuid.uuid4().hex[:12]}{ext}"
            dest_path = image_dir / filename
            shutil.copy2(source_path, dest_path)

            image_id = str(uuid.uuid4())
            db.add(GalleryImage(
                id=image_id,
                filename=filename,
                prompt=meta.get("name") or "Chat upload",
                model="chat-upload",
                owner=owner,
                session_id=_valid_session_id_for_owner(db, session_id, owner),
                file_hash=file_hash,
                width=meta.get("width"),
                height=meta.get("height"),
                file_size=meta.get("size"),
            ))
            db.commit()
            return image_id
        except Exception as e:
            db.rollback()
            logger.warning("Failed to add chat image upload to gallery: %s", e)
            return None
        finally:
            db.close()
    
    @router.post("")
    async def api_upload(
        request: Request,
        files: List[UploadFile] = File(...),
        session_id: Optional[str] = Form(None),
    ):
        """Upload files with enhanced security and organization."""
        if not isinstance(session_id, str):
            session_id = None
        if not files:
            raise HTTPException(400, "No files uploaded")

        # Batch-size cap. The browser's MAX_FILES (static/js/fileHandler.js) is
        # advisory — it bounds the composer, not the endpoint — so bound the
        # request here too, before any bytes are written. Cheapest check first:
        # an oversized batch is rejected whole, with nothing left on disk.
        if len(files) > MAX_FILES_PER_REQUEST:
            raise HTTPException(
                400,
                f"Too many files in one request (max {MAX_FILES_PER_REQUEST})",
            )

        client_ip = request.client.host if request.client else "unknown"
        out = []
        rejected = []
        first_rejection: Optional[HTTPException] = None

        # Limit concurrent uploads per IP. Count genuine recent upload events —
        # NOT the number of files in this batch. The previous check summed over
        # `files`, so a single multi-file request counted itself as N concurrent
        # uploads and tripped the limit (issue #1346: "attach more than one file
        # → the model doesn't even see them"). save_upload still enforces the
        # per-minute sliding-window rate limit per file.
        recent_uploads = count_recent_uploads(
            upload_handler.upload_rate_log.get(client_ip, []), time.time()
        )

        if recent_uploads >= upload_handler.max_concurrent_uploads:
            raise HTTPException(
                status_code=429,
                detail=f"Maximum concurrent uploads ({upload_handler.max_concurrent_uploads}) exceeded"
            )
        
        for u in files:
            try:
                owner = effective_user(request)
                meta = upload_handler.save_upload(u, client_ip, owner=owner)
                gallery_id = _promote_chat_image_to_gallery(meta, owner, session_id)
                item = {
                    "id": meta["id"],
                    "name": meta["name"],
                    "mime": meta["mime"],
                    "size": meta["size"],
                    "hash": meta["hash"],
                    "checksum_sha256": meta.get("checksum_sha256") or meta["hash"],
                    "uploaded_at": meta["uploaded_at"],
                    "created_at": meta.get("created_at") or meta["uploaded_at"],
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                    "is_duplicate": meta.get("is_duplicate", False)
                }
                if gallery_id:
                    item["gallery_id"] = gallery_id
                out.append(item)
            except HTTPException as e:
                # A per-file rejection must not abort the batch. save_upload()
                # charges upload_rate_limit once per file, so file N can 429
                # after files 1..N-1 are already written to disk and indexed —
                # re-raising here returned an error body while leaving those
                # bytes committed, and the browser (which reads `files`) threw
                # the successful ones away. Report the failures next to the
                # successes instead of discarding both.
                if first_rejection is None:
                    first_rejection = e
                logger.warning("Upload rejected for %s: %s", u.filename, e.detail)
                rejected.append({
                    "name": u.filename,
                    "status": e.status_code,
                    "error": str(e.detail),
                })
                continue
            except Exception as e:
                logger.error(f"Failed to process upload {u.filename}: {str(e)}")
                # Keep the response free of internal detail; the log has it.
                rejected.append({
                    "name": u.filename,
                    "status": 500,
                    "error": "Upload failed",
                })
                continue

        if not out:
            # Nothing was written, so there is no partial state to preserve:
            # surface the first per-file rejection verbatim (429/400/…) so a
            # single-file caller still gets the precise reason and status.
            if first_rejection is not None:
                raise first_rejection
            raise HTTPException(500, "All file uploads failed")

        response = {"files": out}
        if rejected:
            response["rejected"] = rejected
        return response
    
    @router.post("/cleanup")
    async def manual_cleanup(request: Request):
        """Manually trigger cleanup of old uploads."""
        require_admin(request)
        try:
            cleaned_count = await asyncio.to_thread(
                _run_reference_safe_cleanup,
                upload_handler,
            )
        except UploadCleanupSafetyError:
            logger.exception("Upload cleanup aborted because index safety checks failed")
            raise HTTPException(
                503,
                "Upload cleanup aborted because upload index integrity could not be verified",
            )
        except Exception:
            logger.exception("Upload cleanup skipped because reference discovery failed")
            raise HTTPException(
                503,
                "Upload cleanup skipped because persisted references could not be verified",
            )
        return {"status": "success", "files_cleaned": cleaned_count}

    @router.get("/stats")
    async def upload_stats(request: Request):
        """Get statistics about uploaded files."""
        require_admin(request)
        try:
            return upload_handler.get_upload_stats()
        except Exception as e:
            logger.error(f"Failed to get upload stats: {e}")
            raise HTTPException(500, "Failed to get upload statistics")

    def _svg_response(path: str, thumb: bool):
        """Serve an uploaded SVG: sanitised for a preview, intact for a download.

        `B103`, and the split is the whole point. A **preview** is the product
        choosing to render someone's markup, so it only ever carries bytes the
        shared gate passed and otherwise sends an empty image — the chip
        collapses instead of spinning, and the refused file is still on disk. A
        **download** is the person asking for their own file back, which
        `build_user_content`'s banner promises them in writing, so it is served
        whole. Both carry `src/svg_runtime.SVG_SECURITY_HEADERS` and an
        attachment disposition, which is what makes the intact one inert: a
        sandbox CSP allows no script in any context, and `attachment` means a
        direct navigation downloads rather than renders. An `<img>`, which is how
        both the chip and the lightbox load it, ignores the disposition and
        draws the picture.

        `B160` changed two things about the refusal arm and neither about the
        pass arm. **The preview allows an embedded `data:image` raster**, which
        is the majority of what `B103` was refusing: an Inkscape or Figma export
        with one bitmap in it carries `<image href="data:image/png;base64,…">`
        and lost its preview to the element name alone. **And a refusal is now
        drawn rather than blank** — the 1x1 told the person nothing, so a
        harmless diagram and a file carrying `<script>` produced the identical
        empty box. The reason is a slug from a fixed vocabulary; it is put on
        the response as `X-Preview-Refused` for anything that can read a header
        and drawn into the placeholder for the `<img>` that cannot.
        """
        from fastapi.responses import FileResponse, Response

        headers = {**UPLOAD_RESPONSE_HEADERS, **SVG_SECURITY_HEADERS,
                   "Content-Disposition": "attachment"}
        if not thumb:
            return FileResponse(path, media_type="image/svg+xml", headers=headers)
        try:
            with open(path, "rb") as fh:
                content = fh.read(MAX_PREVIEW_SVG_BYTES + 1)
        except OSError as e:
            logger.warning(f"SVG preview read failed for {path}: {e}")
            content = b""
        # Through the module, not a name bound at import time, so there is
        # demonstrably one gate in the process and this route reaches it.
        reason = svg_runtime.svg_refusal_reason(
            content, MAX_PREVIEW_SVG_BYTES, allow_data_images=True
        )
        if reason is not None:
            logger.info("SVG preview refused (%s): %s", reason, path)
            return Response(
                svg_runtime.refused_preview_svg(reason),
                media_type="image/svg+xml",
                headers={**headers, "Cache-Control": "no-store",
                         SVG_REFUSAL_HEADER: reason},
            )
        return Response(content, media_type="image/svg+xml", headers=headers)

    @router.get("/{file_id}")
    async def download_file(request: Request, file_id: str, thumb: int = 0):
        """Serve an uploaded file by its ID. `?thumb=1` returns a small cached
        JPEG thumbnail for images (used by chat attachment previews) so the
        client isn't downloading the full-resolution photo just to show it tiny."""
        if not upload_handler.validate_upload_id(file_id):
            raise HTTPException(400, "Invalid file ID")
        import mimetypes as _mt
        # Look up original filename and owner from uploads.json
        original_name = file_id
        # _load_upload_index() tolerates a missing/corrupt uploads.json (it falls
        # back to the .bak sibling, then to {}), so a truncated DB degrades to
        # "no metadata" instead of a 500 from an unhandled JSONDecodeError.
        db = upload_handler._load_upload_index()
        info = next((fi for fi in db.values() if fi.get("id") == file_id), None)
        if info:
            original_name = info.get("name", file_id)
        auth_mgr = getattr(request.app.state, "auth_manager", None)
        auth_configured = bool(auth_mgr and auth_mgr.is_configured)
        current_user = effective_user(request)
        file_owner = info.get("owner") if info else None
        if auth_configured:
            if not current_user:
                raise HTTPException(403, "Access denied")
            if file_owner != current_user and not auth_mgr.is_admin(current_user):
                raise HTTPException(404, "File not found")
        path = _resolve_upload_path(file_id)
        mime = (info or {}).get("mime") or _mt.guess_type(path)[0] or "application/octet-stream"
        from fastapi.responses import FileResponse
        # `B103`. SVG before PIL, because PIL cannot parse SVG: `image/svg+xml`
        # satisfies the `startswith("image/")` test below, `Image.open` raises
        # `UnidentifiedImageError`, and the except-branch then fell through and
        # served the original file. So the preview a person sees today is the raw
        # SVG, arrived at by an exception handler rather than by a decision, and
        # carrying none of the headers this product already applies to every
        # other SVG it serves (`routes/emoji_routes.py`). Same bytes either way
        # for a file that passes the check — the difference is that refusing is
        # now possible.
        if is_svg(original_name, mime):
            return _svg_response(path, bool(thumb))
        # Downscaled thumbnail for image previews — generated once and cached.
        if thumb and mime.startswith("image/"):
            try:
                from PIL import Image, ImageOps
                thumb_dir = os.path.join(_upload_root(), ".thumbs")
                os.makedirs(thumb_dir, exist_ok=True)
                thumb_path = os.path.join(thumb_dir, file_id + ".jpg")
                if (not os.path.exists(thumb_path)
                        or os.path.getmtime(thumb_path) < os.path.getmtime(path)):
                    im = Image.open(path)
                    # iPhone / camera JPEGs encode rotation in EXIF rather than
                    # the pixel data. Browsers honour that on the original via
                    # image-orientation:from-image, but PIL strips EXIF when it
                    # saves the JPEG thumb, leaving the pixels sideways. Bake
                    # the rotation into the pixels before thumbnailing.
                    im = ImageOps.exif_transpose(im)
                    im.thumbnail((320, 320))
                    if im.mode not in ("RGB", "L"):
                        im = im.convert("RGB")
                    im.save(thumb_path, "JPEG", quality=80)
                return FileResponse(thumb_path, media_type="image/jpeg", headers=UPLOAD_RESPONSE_HEADERS)
            except Exception as e:
                logger.warning(f"Thumbnail generation failed for {file_id}: {e}")
                # Fall through to the full image.
        return FileResponse(
            path,
            media_type=mime,
            filename=original_name,
            headers=UPLOAD_RESPONSE_HEADERS,
        )

    def _load_upload_info(file_id: str):
        """Look up the uploads.json record for a file_id, with owner/auth checks."""
        # Corruption-tolerant load (see download_file): a bad uploads.json yields
        # {} rather than raising JSONDecodeError out of the vision path.
        db = upload_handler._load_upload_index()
        return next((fi for fi in db.values() if fi.get("id") == file_id), None)

    def _vision_cache_path(file_id: str) -> str:
        cache_dir = os.path.join(_upload_root(), ".vision")
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, file_id + ".txt")

    # The empty answer, worded for the person who pressed the button. It is
    # bracketed because that is this product's marker for "not a caption" —
    # `src/chat_handler.py` already declines to fold a cached line starting with
    # `[` into the prompt, so a diagram with no words cannot arrive at the model
    # dressed as a description of itself.
    SVG_NO_TEXT_CAPTION = (
        "[This SVG contains no text. Its source is sent to the model with the "
        "message, so you can ask about the drawing directly.]"
    )

    def _svg_caption_response(path: str, file_id: str, info: dict | None,
                              owner: str | None, cache_path: str):
        """Caption an SVG from the SVG (`B163`), with no model and no network.

        `Law 16` is the first reason and accuracy is the second: `<title>` and
        `<desc>` are the accessible name and description the SVG format defines
        for exactly this, and `<text>` runs are the labels on the drawing, so
        this is the caption the author wrote rather than a guess about pixels
        that were never rendered.

        A file with no text is not cached: the cache doubles as the store for a
        hand-edited caption (`PUT /{id}/vision`), and writing a placeholder into
        it would make the next `GET` serve the placeholder as though a person
        had typed it.
        """
        try:
            with open(path, "rb") as fh:
                content = fh.read(MAX_PREVIEW_SVG_BYTES)
        except OSError as e:
            logger.warning(f"SVG caption read failed for {file_id}: {e}")
            content = b""
        text = svg_caption_text(content)
        if not text:
            return {"text": SVG_NO_TEXT_CAPTION, "cached": False, "source": "svg"}
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            logger.warning(f"Vision cache write failed for {file_id}: {e}")
        _sync_gallery_caption_for_upload(info, owner, text)
        return {"text": text, "cached": False, "source": "svg"}

    def _sync_gallery_caption_for_upload(info: dict | None, owner: str | None, text: str) -> None:
        """Copy upload OCR/vision text onto the promoted gallery image row."""
        if not info:
            return
        file_hash = info.get("hash")
        if not file_hash:
            return
        db = SessionLocal()
        try:
            q = db.query(GalleryImage).filter(
                GalleryImage.file_hash == file_hash,
                GalleryImage.is_active == True,  # noqa: E712
            )
            if owner:
                q = q.filter(GalleryImage.owner == owner)
            img = q.first()
            if not img:
                return
            img.caption = (text or "").strip()
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("Failed to sync OCR caption to gallery image: %s", e)
        finally:
            db.close()

    @router.get("/{file_id}/vision")
    async def get_vision_text(request: Request, file_id: str, force: int = 0):
        """Return the OCR/description for an uploaded image.

        Cached under UPLOAD_DIR/.vision/{file_id}.txt — first call computes,
        subsequent loads are instant. Pass force=1 to recompute.

        `B163`: an SVG is answered from its own markup and never reaches the
        vision model. The gate was `mime.startswith("image/")`, which
        `image/svg+xml` satisfies, so pressing Caption on a diagram base64'd its
        XML and posted it to a VL endpoint **labelled `data:image/jpeg`** —
        `analyze_image_with_vl_result`'s `mime_map` has no `.svg` and falls back
        to jpeg. An outbound call that cannot succeed (`Law 16`), on the one
        upload type this product has already decided is markup rather than
        pixels (`B103`, `src/svg_runtime.py`).

        **Not `upload_handler.is_image_file`, which is what the row proposed.**
        Measured: that register is `{.png .jpg .jpeg .webp .gif}`, while
        `static/js/chatRenderer.js` draws — and offers this button for —
        `.bmp` as well, and the route accepts every `image/*` MIME, so `.bmp`,
        `.tiff`, `.avif` and `.heic` reach the model today. Swapping the MIME
        prefix for that register would have taken the Caption button away from
        four working formats to fix one broken one (`Law 1`). The question that
        actually separates them is not "is it an image" but "is it markup", and
        `svg_runtime.is_svg` is the gate this product already asks that with.
        """
        if not upload_handler.validate_upload_id(file_id):
            raise HTTPException(400, "Invalid file ID")
        info = _load_upload_info(file_id)
        auth_mgr = getattr(request.app.state, "auth_manager", None)
        auth_configured = bool(auth_mgr and auth_mgr.is_configured)
        current_user = effective_user(request)
        file_owner = info.get("owner") if info else None
        if auth_configured:
            if not current_user:
                raise HTTPException(403, "Access denied")
            if file_owner != current_user and not auth_mgr.is_admin(current_user):
                raise HTTPException(404, "File not found")
        path = _resolve_upload_path(file_id)
        import mimetypes as _mt
        display_name = (info or {}).get("name") or os.path.basename(path)
        mime = (info or {}).get("mime") or _mt.guess_type(path)[0] or ""
        markup = is_svg(display_name, mime)
        if not markup and not mime.startswith("image/"):
            raise HTTPException(400, "Not an image")
        cache_path = _vision_cache_path(file_id)
        if not force and os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    cached_text = f.read()
                _sync_gallery_caption_for_upload(info, file_owner or current_user, cached_text)
                return {"text": cached_text, "cached": True,
                        "source": "svg" if markup else "vision"}
            except Exception as e:
                logger.warning(f"Vision cache read failed for {file_id}: {e}")
        if markup:
            return _svg_caption_response(path, file_id, info,
                                         file_owner or current_user, cache_path)
        from src.document_processor import analyze_image_with_vl
        try:
            text = analyze_image_with_vl(path, owner=current_user) or ""
        except Exception as e:
            logger.error(f"Vision analysis failed for {file_id}: {e}")
            raise HTTPException(500, f"Vision analysis failed: {e}")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            logger.warning(f"Vision cache write failed for {file_id}: {e}")
        _sync_gallery_caption_for_upload(info, file_owner or current_user, text)
        return {"text": text, "cached": False, "source": "vision"}

    @router.put("/{file_id}/vision")
    async def put_vision_text(request: Request, file_id: str):
        """Persist a user-edited vision/OCR text for an attachment. Stored in
        the same cache file so the chat send picks it up as the override."""
        if not upload_handler.validate_upload_id(file_id):
            raise HTTPException(400, "Invalid file ID")
        info = _load_upload_info(file_id)
        if not info:
            raise HTTPException(404, "File not found")
        auth_mgr = getattr(request.app.state, "auth_manager", None)
        auth_configured = bool(auth_mgr and auth_mgr.is_configured)
        current_user = effective_user(request)
        file_owner = info.get("owner")
        if auth_configured:
            if not current_user:
                raise HTTPException(403, "Access denied")
            if file_owner != current_user and not auth_mgr.is_admin(current_user):
                raise HTTPException(404, "File not found")
        _resolve_upload_path(file_id)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(400, "Request body must be valid JSON")
        text = (body or {}).get("text", "")
        if not isinstance(text, str):
            raise HTTPException(400, "text must be a string")
        with open(_vision_cache_path(file_id), "w", encoding="utf-8") as f:
            f.write(text)
        _sync_gallery_caption_for_upload(info, file_owner or current_user, text)
        return {"ok": True}

    async def periodic_rate_limit_cleanup():
        """Background task to run cleanup every hour.

        Local-only, so it is not part of the cross-install herd — spread anyway
        (`P15-10`), because "every recurring job" is a rule worth being able to
        check mechanically and an exception that has to be argued each time is
        an exception nobody checks.
        """
        from src.jitter import sleep_jittered
        while True:
            await sleep_jittered(3600)
            upload_handler.cleanup_rate_limits()
    
    return router, periodic_rate_limit_cleanup
