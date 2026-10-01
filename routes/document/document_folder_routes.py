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
from src.auth_helpers import _auth_disabled, get_current_user, require_privilege


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


def _scope(user: Optional[str]):
    """The owner every query is scoped to — `_owner_session_filter`'s rule."""
    if user:
        return user
    if user == "" or _auth_disabled():
        return folders.EVERY_OWNER
    raise HTTPException(403, "Authentication required")


def _reader(request: Request):
    return _scope(get_current_user(request))


def _writer(request: Request):
    return _scope(require_privilege(request, "can_use_documents"))


def _write(request: Request, op, *args, **kwargs) -> Dict[str, Any]:
    owner = _writer(request)
    db = SessionLocal()
    try:
        out = op(db, owner, *args, **kwargs)
        db.commit()
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
