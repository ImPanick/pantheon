# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P21-01` — the library's folder routes.

Registered onto the document router by `setup_document_routes`, so they sit
behind the same `document_editor` gate as every other document route (`H05`)
and nothing about mounting them can drift from the routes they belong with.
Every decision is in `src/document_folders.py`; these handlers resolve who is
asking, call it, and commit once.

Paths travel in JSON bodies, not in the URL: a folder path holds "/", and
`/api/documents/{session_id}` already owns every single-segment GET under
`/api/documents/`, which is why these live under `/api/document-folders`.

Writes take `can_use_documents`, the privilege `POST /api/document` already
checks — making a folder is making something in the library.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from core.database import SessionLocal
from src import document_folders as folders
from src.auth_helpers import (
    get_current_user, request_is_a_person, require_privilege,
)


class FolderCreate(BaseModel):
    folder: str


class FolderRename(BaseModel):
    folder: str
    name: str


class FolderMove(BaseModel):
    folder: str
    # Required, nullable: `null` or "" is the top level. A missing key is a
    # client bug, and reading it as "the top level" would move the folder.
    to: Optional[str]


class FolderRemove(BaseModel):
    folder: str
    contents: Optional[str] = None
    dry_run: bool = False


class DocumentsFile(BaseModel):
    document_ids: List[str]
    # Required, nullable: `null` or "" is Unfiled, for the reason `FolderMove` gives.
    to: Optional[str]


class PlanAnswer(BaseModel):
    answer: str


def _scope(user: Optional[str]):
    """The owner every query is scoped to — `_owner_session_filter`'s rule."""
    if user:
        return user
    if user == "":
        return folders.EVERY_OWNER
    raise HTTPException(403, "Authentication required")


def _reader(request: Request):
    return _scope(get_current_user(request))


def _writer(request: Request):
    return _scope(require_privilege(request, "can_use_documents"))


def _person(request: Request):
    """`B1006`. A plan's answer is the person's, so a request acting in their
    name — a bearer token (`B70`), the assistant's own loopback through
    `app_api` — is refused here before anything is read (`B1005`)."""
    if not request_is_a_person(request):
        raise HTTPException(403, "Only you can answer this, from Pantheon itself — "
                                 "not an API token and not your assistant.")
    return _writer(request)


def _write(request: Request, op, *args, **kwargs) -> Dict[str, Any]:
    owner = _writer(request)
    db = SessionLocal()
    try:
        out = op(db, owner, *args, **kwargs)
        db.commit()
        # `B994`: the open-document pointer is cleared once a delete is real,
        # not inside the step — a plan runs its steps and rolls them back.
        folders.forget_deleted(out.get("changes"))
        if "changes" in out:
            out = {**out, "changes": folders.shown_changes(out["changes"])}
        return out
    except folders.FolderError as e:
        db.rollback()
        raise HTTPException(e.status, e.message)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Folder change failed: {e}")
    finally:
        db.close()


def register_document_folder_routes(router: APIRouter) -> None:
    @router.get("/api/document-folders")
    async def list_document_folders(request: Request,
                                    archived: bool = Query(False)) -> Dict[str, Any]:
        owner = _reader(request)
        db = SessionLocal()
        try:
            return folders.list_folders(db, owner, archived=archived)
        finally:
            db.close()

    @router.post("/api/document-folders")
    async def create_document_folder(request: Request, req: FolderCreate) -> Dict[str, Any]:
        return _write(request, folders.create_folder, req.folder)

    @router.post("/api/document-folders/rename")
    async def rename_document_folder(request: Request, req: FolderRename) -> Dict[str, Any]:
        return _write(request, folders.rename_folder, req.folder, req.name)

    @router.post("/api/document-folders/move")
    async def move_document_folder(request: Request, req: FolderMove) -> Dict[str, Any]:
        return _write(request, folders.move_folder, req.folder, req.to)

    @router.post("/api/document-folders/remove")
    async def remove_document_folder(request: Request, req: FolderRemove) -> Dict[str, Any]:
        return _write(request, folders.remove_folder, req.folder, req.contents,
                      dry_run=req.dry_run)

    @router.post("/api/document-folders/file")
    async def file_documents_into_folder(request: Request, req: DocumentsFile) -> Dict[str, Any]:
        return _write(request, folders.file_documents, req.document_ids, req.to)

    # ── `B1006` · the scheduled tidy's proposal, answered by the person ─────
    #
    # `GET` lists the proposals still waiting for the caller, so the browser
    # can offer one again after a reload (a notification is said once). `POST`
    # is the answer: "Apply the plan" or "Don't change anything", recorded in
    # the plan's chat as the person's (`document_actions.answer_review`) and
    # applied by `document_folders.apply_plan` against the documents as they
    # are now. Only a person may answer; an agent's plan is not answered here.

    @router.get("/api/document-folders/plans")
    async def waiting_document_plans(request: Request) -> Dict[str, Any]:
        owner = _reader(request)
        return {"plans": [dict(p.review, plan_id=p.plan_id)
                          for p in folders.waiting_reviews(owner)]}

    @router.post("/api/document-folders/plans/{plan_id}/answer")
    async def answer_document_plan(request: Request, plan_id: str,
                                   req: PlanAnswer) -> Dict[str, Any]:
        from src.document_actions import answer_review

        owner = _person(request)
        plan = folders.waiting_review(plan_id, owner)
        if plan is None:
            raise HTTPException(404, "That tidy is no longer waiting — it was answered, a "
                                     "newer one replaced it, or it lapsed.")
        answer = (req.answer or "").strip()
        if answer not in (folders.PLAN_APPROVE_LABEL, folders.PLAN_DECLINE_LABEL):
            raise HTTPException(400, f"Answer \"{folders.PLAN_APPROVE_LABEL}\" or "
                                     f"\"{folders.PLAN_DECLINE_LABEL}\".")
        return answer_review(plan, answer)
