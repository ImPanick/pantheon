# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-04` / `P26-05` · The Design window's design systems, over HTTP.

    GET    /api/design/systems?project=   mine: personal ones, and the project's
    POST   /api/design/systems/extract    {text?, file?: {name, data_b64}} → {tokens, warnings, css}
                                          — read by the model, kept nowhere
    POST   /api/design/systems            {name, scope, project?, tokens, accept_low_contrast?}
    PUT    /api/design/systems/{id}       the same fields, any of them
    DELETE /api/design/systems/{id}

Everything is the caller's own (`src/design_systems.py`): there is no route to
another person's systems — collaborators are `P26-09`'s. Every refusal is
`{detail: "<sentence>"}` (`Law 15`); a contrast pair below AA is `422` with
the sentence, until the person saves knowing it. The route ceiling
(`check-unreachable.py`): each path is spelled in `static/js/design/designWindow.js`.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import SessionLocal
from src.auth_helpers import get_current_user, request_is_a_person

BODY_MAX_BYTES = 12 * 1024 * 1024
ONLY_A_PERSON = "Only a person signed in to Pantheon changes their design systems — not an API token or the assistant."


def _refused(sentence: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": sentence}, status_code=status)


async def _body(request: Request) -> Dict[str, Any]:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > BODY_MAX_BYTES:
            raise ValueError("The request is larger than 12 MB, so it was not read.")
    if not bytes(raw).strip():
        return {}
    try:
        body = json.loads(bytes(raw))
    except (TypeError, ValueError):
        raise ValueError("The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise ValueError("The request body must be a JSON object.")
    return body


def setup_design_routes() -> APIRouter:
    router = APIRouter(prefix="/api/design", tags=["design"])

    @router.get("/systems")
    def my_systems(request: Request, project: str = ""):
        from src import design_systems as D
        db = SessionLocal()
        try:
            return {"systems": D.listing(db, get_current_user(request), project.strip() or None),
                    "roles": list(D.ROLES)}
        finally:
            db.close()

    @router.post("/systems/extract")
    async def extract(request: Request):
        from src import design_systems as D
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e), 413 if "12 MB" in str(e) else 400)
        try:
            return await D.extract(get_current_user(request), body.get("text"), body.get("file"))
        except D.DesignRefused as r:
            return _refused(r.sentence, r.status)

    async def _save(request: Request, system_id=None):
        from src import design_systems as D
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        db = SessionLocal()
        try:
            return await D.save(db, get_current_user(request), body, system_id)
        except D.DesignRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.post("/systems")
    async def add_system(request: Request):
        return await _save(request)

    @router.put("/systems/{system_id}")
    async def change_system(system_id: str, request: Request):
        return await _save(request, system_id)

    @router.delete("/systems/{system_id}")
    def remove_system(system_id: str, request: Request):
        from src import design_systems as D
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        db = SessionLocal()
        try:
            D.remove(db, get_current_user(request), system_id)
            return {"ok": True}
        except D.DesignRefused as r:
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    return router


__all__ = ["setup_design_routes"]
