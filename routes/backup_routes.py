# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backup routes — export/import user data (memories, presets, settings, skills, preferences,
and — `P22-24` — tasks and workflows)."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from core.middleware import require_admin
from services.memory import MemoryStoreUnreadable
from src.auth_helpers import get_current_user
from src.settings import (
    WITHHELD_SETTING_KEYS,
    WITHHELD_SETTING_LABELS,
    load_features,
    load_settings,
    save_features,
    save_settings,
    without_withheld_settings,
)
from src.upload_limits import (
    format_byte_limit,
    read_byte_limit_env,
    resolve_byte_cap,
)

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


def _backup_import_max_bytes() -> int:
    """The live cap: role profile -> instance setting -> env -> the constant.

    `P12-01` / `P12-03`. `BACKUP_IMPORT_MAX_BYTES` above is the import-time
    snapshot and stays — `Law 1`, and three tests set it directly — but it is
    read here as the module global rather than closed over, so it remains the
    bottom layer and a test that reassigns it still decides when nothing above
    it is configured.
    """
    return resolve_byte_cap(
        "backup_import_max_bytes",
        "PANTHEON_BACKUP_IMPORT_MAX_BYTES",
        BACKUP_IMPORT_MAX_BYTES,
    )[0]


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


# `P22-24` (`SLICE-EF-DESIGN` § 2). What a backup does not carry, said in the
# file itself (`Law 10`): a restore brings back each workflow's current
# document and every task, not their history.
NOT_CARRIED = "Workflow versions, task runs and their step records are not in a backup."
TASKS_UNREADABLE = "Tasks and workflows could not be read, so they are not in this backup."
# A task's columns a backup never restores as given: when it was written.
_TASK_STAMPS = ("created_at", "updated_at")


def _plain(value):
    return value.isoformat() if isinstance(value, datetime) else value


def backup_tasks(db, user) -> list:
    """`P22-24`. The owner's tasks, every column — webhook tokens included:
    `B958`'s logic is that a restore needs what does not re-pair on its own,
    and a webhook URL is bound to its token (`FORBIDDEN.md` Part 1's shape)."""
    from core.database import ScheduledTask
    q = db.query(ScheduledTask)
    if user:
        q = q.filter(ScheduledTask.owner == user)
    columns = [c.name for c in ScheduledTask.__table__.columns]
    return [{name: _plain(getattr(t, name)) for name in columns}
            for t in q.order_by(ScheduledTask.created_at, ScheduledTask.id).all()]


def backup_workflows(db, user) -> list:
    """`P22-24`. The owner's workflows: `{id, name, graph, version, task_id,
    source_chain}`. The graph is `without_pins` — a sample is real data from a
    run, and runs are not carried — and KEEPS each step's `unchecked` mark, so
    a draft nobody checked is restored still waiting for a person (a backup
    round trip is not a way to clear a mark, `P22-19`)."""
    from core.database import Workflow
    from src import workflow_store as store
    from src.workflow_document import without_pins
    q = db.query(Workflow)
    if user:
        q = q.filter(Workflow.owner == user)
    return [{"id": wf.id, "name": wf.name, "graph": without_pins(store.stored_graph(wf)),
             "version": wf.version, "task_id": wf.task_id, "source_chain": wf.source_chain}
            for wf in q.order_by(Workflow.id).all()]


def _column_value(column, value):
    """A backed-up value as its column takes it, or None when it is not one."""
    from sqlalchemy import Boolean, DateTime, Integer
    if value is None:
        return None
    kind = column.type
    if isinstance(kind, DateTime):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "")).replace(tzinfo=None)
        except ValueError:
            return None
    if isinstance(kind, Boolean):
        return value if isinstance(value, bool) else None
    if isinstance(kind, Integer):
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    return value if isinstance(value, str) else None


def restore_tasks(db, user, tasks) -> int:
    """Tasks, by their own ids; an id this install already has is skipped.
    Each becomes the importing person's. A chain's arrows are joined after
    every task is in (the foreign keys want their targets first), and only to
    a task that is there; a chat or a crew member this install does not have
    is let go rather than pointed at."""
    from core.database import CrewMember, ScheduledTask, Session as ChatSession
    from src.task_scheduler import _resolve_task_timezone, compute_next_run
    columns = {c.name: c for c in ScheduledTask.__table__.columns}
    existing = {row[0] for row in db.query(ScheduledTask.id).all()}
    made, edges = [], []
    for item in tasks:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        if item["id"] in existing:
            continue
        values = {name: _column_value(columns[name], item.get(name)) for name in columns
                  if name in item and name not in _TASK_STAMPS}
        values["owner"] = user if user else values.get("owner")
        edges.append((item["id"], values.pop("then_task_id", None), values.pop("else_task_id", None)))
        session_id = values.get("session_id")
        if session_id and db.query(ChatSession.id).filter(ChatSession.id == session_id).first() is None:
            values["session_id"] = None
        crew = values.get("crew_member_id")
        if crew and db.query(CrewMember.id).filter(CrewMember.id == crew,
                                                  CrewMember.owner == values["owner"]).first() is None:
            values["crew_member_id"] = None
        task = ScheduledTask(**values)
        if not task.name:
            task.name = "Untitled Task"
        db.add(task)
        existing.add(item["id"])
        made.append(task)
    db.flush()
    for task_id, then_id, else_id in edges:
        task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        for column, target in (("then_task_id", then_id), ("else_task_id", else_id)):
            if target and db.query(ScheduledTask.id).filter(ScheduledTask.id == target).first():
                setattr(task, column, target)
    for task in made:
        # A restored schedule runs from now on, not to catch up the time the
        # backup sat in a drawer.
        if (task.status or "active") == "active" and (task.trigger_type or "schedule") == "schedule":
            task.next_run = compute_next_run(task.schedule, task.scheduled_time, task.scheduled_day,
                                             task.scheduled_date, cron_expression=task.cron_expression,
                                             tz_name=_resolve_task_timezone(db, task))
    db.commit()
    return len(made)


def restore_workflows(db, user, workflows) -> tuple:
    """`(restored, switched_off)` — workflows, by their own ids, after the
    tasks; an id this install already has is skipped. Each is asked the
    rule as a save is (`check_document`) and whether a step still waits to be
    checked (`unchecked_refusal`); one this install refuses — a missing MCP
    server, say — is restored with its trigger switched OFF, and named with
    the refusal's sentence. A trigger that is not the importing person's own
    workflow start is not linked."""
    from core.database import ScheduledTask, Workflow
    from src import workflow_store as store
    from src.workflow_document import (
        VERSION_SOURCE_RESTORED, DocumentError, parse_graph, unchecked_refusal,
    )
    restored, off = 0, []
    for item in workflows:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        if db.query(Workflow.id).filter(Workflow.id == item["id"]).first() is not None:
            continue
        name = store.clean_name(item.get("name"), required=False) or store.NEW_WORKFLOW_NAME
        graph_in = item.get("graph") if isinstance(item.get("graph"), dict) else {}
        try:
            graph, why = parse_graph(graph_in), None
        except DocumentError as err:
            graph, why = graph_in, err.refusal.sentence
        task_id = item.get("task_id") if isinstance(item.get("task_id"), str) else None
        trigger = (db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
                   if task_id else None)
        if (trigger is None or (user and trigger.owner != user)
                or (trigger.task_type or "") != "workflow"
                or db.query(Workflow.id).filter(Workflow.task_id == task_id).first() is not None):
            trigger, task_id = None, None
        version = item.get("version")
        version = version if isinstance(version, int) and not isinstance(version, bool) \
            and version >= 1 else 1
        chain = item.get("source_chain") if isinstance(item.get("source_chain"), str) else None
        wf = Workflow(id=item["id"], owner=user if user else item.get("owner"), name=name,
                      task_id=task_id, graph=json.dumps(graph), version=version, source_chain=chain)
        db.add(wf)
        db.flush()
        store._write_version(db, wf, graph, source=VERSION_SOURCE_RESTORED)
        if why is None:
            marks = unchecked_refusal(graph)
            why = marks.sentence if marks is not None else None
        if why is None:
            try:
                store.check_document(db, graph, owner=wf.owner, own_task_id=task_id)
            except store.WorkflowRefused as refused:
                why = refused.sentence
        if trigger is None:
            why = why or store.LOST_TRIGGER
        if why and trigger is not None:
            trigger.status = "paused"
        if why:
            off.append({"id": wf.id, "name": name, "why": why})
        db.commit()
        restored += 1
    return restored, off


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

        # Settings. `B958`: less the keys that never leave the server — they
        # re-pair on their own (`WITHHELD_SETTING_KEYS`). Every provider API key
        # stays: a restore needs them, and the panel says the file holds them.
        settings = without_withheld_settings(load_settings())

        # Feature flags
        features = load_features()

        # User preferences
        from routes.prefs_routes import _load_for_user
        preferences = _load_for_user(user)

        # `P22-24`. Tasks and workflows — the backup carried neither. A task
        # table that cannot be read leaves them out and says so in the file,
        # rather than taking the memories and settings down with it (`Law 10`:
        # never an empty list that reads as "there were none").
        from sqlalchemy.exc import SQLAlchemyError
        from core.database import SessionLocal
        tasks = workflows = None
        not_carried = NOT_CARRIED
        db = SessionLocal()
        try:
            tasks = backup_tasks(db, user)
            workflows = backup_workflows(db, user)
        except SQLAlchemyError as err:
            logger.warning("Backup: tasks and workflows could not be read: %s", err)
            tasks = workflows = None
            not_carried = f"{TASKS_UNREADABLE} {NOT_CARRIED}"
        finally:
            db.close()

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
        if tasks is not None:
            export_data["tasks"] = tasks
            export_data["workflows"] = workflows
        export_data["not_carried"] = not_carried

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
            body = await _load_import_body(request, _backup_import_max_bytes())
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
        # `B958`. A key that re-pairs on its own is never restored: a file from
        # before the export left it out still carries it (as `""`, or as a
        # token from an older pairing), and the setting outranks the pairing
        # volume, so writing it would blank or replace the token in use.
        left_alone = []
        if "settings" in body and isinstance(body["settings"], dict):
            incoming = body["settings"]
            left_alone = sorted(k for k in incoming if k in WITHHELD_SETTING_KEYS)
            current = load_settings()
            current.update(without_withheld_settings(incoming))
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

        # ── Tasks, then workflows (`P22-24`) ──
        switched_off = []
        if isinstance(body.get("tasks"), list) or isinstance(body.get("workflows"), list):
            from core.database import SessionLocal
            db = SessionLocal()
            try:
                if isinstance(body.get("tasks"), list):
                    count = restore_tasks(db, user, body["tasks"])
                    imported.append(f"{count} task{'s' if count != 1 else ''}")
                if isinstance(body.get("workflows"), list):
                    count, switched_off = restore_workflows(db, user, body["workflows"])
                    imported.append(f"{count} workflow{'s' if count != 1 else ''}")
            finally:
                db.close()

        if not imported:
            return {"ok": False, "message": "No recognized data found in the file"}

        message = f"Imported: {', '.join(imported)}"
        for wf in switched_off:
            message += f". “{wf['name']}” was restored switched off: {wf['why'].rstrip('.')}"
        if left_alone:
            names = ", ".join(WITHHELD_SETTING_LABELS[k] for k in left_alone)
            message += f". Left as it was: {names} — it pairs again on its own."
        return {"ok": True, "imported": imported, "left_alone": left_alone,
                "switched_off": switched_off, "message": message}

    return router
