"""Backup routes — export/import user data (memories, presets, settings, skills, preferences)."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from core.middleware import require_admin
from services.memory import MemoryStoreUnreadable
from src.auth_helpers import get_current_user
from src.settings import load_settings, save_settings, load_features, save_features
from src.upload_limits import format_byte_limit, read_byte_limit_env

logger = logging.getLogger(__name__)

# Hard ceiling on the /api/import request body. Read through the house helper
# (src/upload_limits.py) so it is validated and env-overridable —
# PANTHEON_BACKUP_IMPORT_MAX_BYTES, an integer byte count; a non-integer or a
# value below 1 fails fast at import rather than mid-request. Deliberately not
# a raw int(os.getenv(...)) literal.
#
# 25 MB: a backup is a strict superset of a memory import
# (MEMORY_IMPORT_MAX_BYTES, 10 MB) since it also carries presets, skills,
# settings and preferences, and it is well under the ~100 MB point where the
# whole-payload-in-memory read would have to become streaming-to-disk.
BACKUP_IMPORT_MAX_BYTES = read_byte_limit_env(
    "PANTHEON_BACKUP_IMPORT_MAX_BYTES", 25 * 1024 * 1024
)


def _declared_body_length(request: Request):
    """The client-declared Content-Length as an int, or None if absent or junk."""
    try:
        raw = request.headers.get("content-length")
    except Exception:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _load_import_body(request: Request, limit: int):
    """Parse the /api/import JSON body under a hard byte ceiling.

    ``Request.json()`` goes through ``Request.body()``, which concatenates the
    entire stream into memory with no ceiling, and this app installs no
    request-body-size middleware, so the only bound on an /api/import POST is
    available RAM. Stream instead and stop one byte past ``limit``.

    Content-Length is a cheap early reject only: it is client-supplied and
    absent on chunked bodies, so the streamed byte count is the real control.

    This bounds an *already authorized* request — ``require_admin`` runs before
    it and is not replaced by it. The ceiling matters most where
    ``require_admin`` short-circuits (AUTH_ENABLED=false), because there it is
    the only thing between /api/import and an unbounded read.
    """
    stream = getattr(request, "stream", None)
    if stream is None:
        # A Request-like object with no ASGI stream (in-process callers that
        # pass the handler a double). There is nothing to meter, so defer to
        # whatever parser it offers.
        return await request.json()

    declared = _declared_body_length(request)
    too_large = f"Import body exceeds {format_byte_limit(limit)} limit"
    if declared is not None and declared > limit:
        raise HTTPException(413, too_large)

    raw = bytearray()
    async for chunk in stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise HTTPException(413, too_large)
    return json.loads(bytes(raw))


def setup_backup_routes(memory_manager, preset_manager, skills_manager) -> APIRouter:
    router = APIRouter(tags=["backup"])

    @router.get("/api/export")
    async def export_data(request: Request):
        """Export all user data as a downloadable JSON file."""
        require_admin(request)
        user = get_current_user(request)

        # Memories (filtered by owner when auth is enabled)
        memories = memory_manager.load(owner=user)

        # Presets (shared across users — export all)
        presets = preset_manager.get_all()

        # Skills (filtered by owner when auth is enabled)
        skills = skills_manager.load(owner=user)

        # Settings
        settings = load_settings()

        # Feature flags
        features = load_features()

        # User preferences
        from routes.prefs_routes import _load_for_user
        preferences = _load_for_user(user)

        export_data = {
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "exported_by": user,
            "memories": memories,
            "presets": presets,
            "skills": skills,
            "settings": settings,
            "features": features,
            "preferences": preferences,
        }

        filename = f"pantheon_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        return Response(
            content=json.dumps(export_data, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @router.post("/api/import")
    async def import_data(request: Request):
        """Import user data from a previously exported JSON file. Merges with existing data."""
        require_admin(request)
        user = get_current_user(request)
        # Size ceiling goes AFTER the admin gate, never in place of it.
        try:
            body = await _load_import_body(request, BACKUP_IMPORT_MAX_BYTES)
        except HTTPException:
            raise  # 413 must not be laundered into "Invalid JSON" below
        except Exception:
            raise HTTPException(400, "Invalid JSON")

        if not isinstance(body, dict):
            raise HTTPException(400, "Expected a JSON object")

        imported = []

        # ── Memories ──
        if "memories" in body and isinstance(body["memories"], list):
            # Strict load: importing on top of an unreadable store would write
            # only the incoming rows back and drop everything already saved.
            try:
                existing = memory_manager.load_all_for_update()
            except MemoryStoreUnreadable as e:
                logger.error("Refusing to import memories: %s", e)
                raise HTTPException(
                    503, "Memory store is temporarily unreadable — nothing was imported."
                )
            # Dedup against THIS user's own memories only. Using every tenant's
            # rows (load_all) meant a memory whose text matched any other
            # user's was silently skipped, so the importing user lost their own
            # data. The full store is still saved back below.
            existing_texts = {e.get("text", "").strip().lower()
                              for e in existing if e.get("owner") == user}
            added = 0
            for mem in body["memories"]:
                if not isinstance(mem, dict) or not mem.get("text"):
                    continue
                if mem["text"].strip().lower() in existing_texts:
                    continue  # skip duplicates
                # Assign owner when auth is enabled
                if user and not mem.get("owner"):
                    mem["owner"] = user
                existing.append(mem)
                existing_texts.add(mem["text"].strip().lower())
                added += 1
            memory_manager.save(existing)
            imported.append(f"{added} memories")

        # ── Skills ──
        if "skills" in body and isinstance(body["skills"], list):
            existing = skills_manager.load_all()
            # Dedup against THIS user's own skills only. Using every tenant's
            # rows (load_all) meant a skill whose id/name/title matched any
            # other user's was silently skipped, so the importing user lost
            # their own data — same cross-tenant bug fixed for memories above.
            # The full store is still saved back below.
            own = [s for s in existing if s.get("owner") == user]
            existing_names = {s.get("name") for s in own if s.get("name")}
            existing_ids = {s.get("id") for s in own if s.get("id")}
            existing_titles = {
                (s.get("title") or s.get("description") or "").strip().lower()
                for s in own
            }
            added = 0
            for skill in body["skills"]:
                if not isinstance(skill, dict):
                    continue
                title = (
                    skill.get("title") or skill.get("description")
                    or skill.get("name") or ""
                ).strip()
                if not title:
                    continue
                sid = skill.get("id") or skill.get("name")
                if sid and sid in existing_ids:
                    continue
                nm = skill.get("name")
                if nm and nm in existing_names:
                    continue
                if title.lower() in existing_titles:
                    continue
                owner = skill.get("owner")
                if user and not owner:
                    owner = user
                # Skills live on disk as SKILL.md files; the old JSON-era
                # skills_manager.save() no longer exists. Write each new skill
                # via add_skill (source="user" skips auto-dedup — this is an
                # explicit backup restore).
                result = skills_manager.add_skill(
                    title=title,
                    name=skill.get("name"),
                    description=skill.get("description"),
                    problem=skill.get("problem", ""),
                    solution=skill.get("solution", ""),
                    steps=skill.get("steps"),
                    tags=skill.get("tags"),
                    source="user",
                    teacher_model=skill.get("teacher_model"),
                    confidence=skill.get("confidence", 0.8),
                    owner=owner,
                    category=skill.get("category", "general"),
                    when_to_use=skill.get("when_to_use"),
                    procedure=skill.get("procedure"),
                    pitfalls=skill.get("pitfalls"),
                    verification=skill.get("verification"),
                    platforms=skill.get("platforms"),
                    requires_toolsets=skill.get("requires_toolsets"),
                    fallback_for_toolsets=skill.get("fallback_for_toolsets"),
                    status=skill.get("status", "draft"),
                    version=skill.get("version", "1.0.0"),
                )
                if result.get("_deduped"):
                    continue
                if result.get("name"):
                    existing_names.add(result["name"])
                if result.get("id"):
                    existing_ids.add(result["id"])
                existing_titles.add(title.lower())
                added += 1
            imported.append(f"{added} skills")

        # ── Presets ──
        if "presets" in body and isinstance(body["presets"], dict):
            current = preset_manager.get_all()
            for key, value in body["presets"].items():
                if isinstance(value, dict):
                    current[key] = value
                elif isinstance(value, list):
                    current[key] = value
            preset_manager.save(current)
            imported.append("presets")

        # ── Settings ──
        if "settings" in body and isinstance(body["settings"], dict):
            current = load_settings()
            current.update(body["settings"])
            save_settings(current)
            imported.append("settings")

        # ── Features ──
        if "features" in body and isinstance(body["features"], dict):
            current = load_features()
            current.update(body["features"])
            save_features(current)
            imported.append("features")

        # ── Preferences ──
        if "preferences" in body and isinstance(body["preferences"], dict):
            from routes.prefs_routes import _load_for_user, _save_for_user
            current = _load_for_user(user)
            current.update(body["preferences"])
            _save_for_user(user, current)
            imported.append("preferences")

        if not imported:
            return {"ok": False, "message": "No recognized data found in the file"}

        return {"ok": True, "imported": imported, "message": f"Imported: {', '.join(imported)}"}

    return router
