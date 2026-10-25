# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-04` / `P26-05` · The Design window's design systems, over HTTP.

    GET    /api/design/systems?project=   mine: personal ones, and the project's
    POST   /api/design/systems/extract    {text?, file?: {name, data_b64}} → {tokens, warnings, css}
                                          — read by the model, kept nowhere
    POST   /api/design/systems            {name, scope, project?, tokens, accept_low_contrast?}
    PUT    /api/design/systems/{id}       the same fields, any of them
    DELETE /api/design/systems/{id}

`P26-06` / `P26-07` · designs, as files in the project (`src/design_files.py`):

    GET    /api/design/designs?project=                     the project's designs
    POST   /api/design/designs                              {project, name, kind, brief?, system?} → its folder
    GET    /api/design/designs/{slug}?project=&version=&variant=
                                                            facts, versions, variants, a page to preview
    GET    /api/design/designs/{slug}/preview?project=&version=&variant=
                                                            that page as its own sandboxed document, for the frame
    POST   /api/design/designs/{slug}/versions              {project, note?} keep the present as a version
    POST   /api/design/designs/{slug}/restore               {project, version}
    POST   /api/design/designs/{slug}/keep                  {project, variant}
    POST   /api/design/designs/{slug}/adjust                {project, selector, props} — the canvas
    POST   /api/design/designs/{slug}/tweaks                {project} → sliders for this design

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
from fastapi.responses import HTMLResponse, JSONResponse

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

    # ── designs, as files (`P26-06` / `P26-07`) ─────────────────────────────

    async def _design(request: Request, fn, *, person: bool = True):
        from src import design_files as F
        if person and not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request) if request.method != "GET" else {}
        except ValueError as e:
            return _refused(str(e))
        try:
            return await fn(F, get_current_user(request), body)
        except F.DesignFileRefused as r:
            return _refused(r.sentence, r.status)

    @router.get("/designs")
    async def my_designs(request: Request, project: str = ""):
        async def go(F, user, _b):
            return {"designs": await F.listing(user, project)}
        return await _design(request, go, person=False)

    @router.post("/designs")
    async def new_design(request: Request):
        async def go(F, user, b):
            return await F.create(user, str(b.get("project") or ""), b)
        return await _design(request, go)

    @router.get("/designs/{slug}")
    async def one_design(slug: str, request: Request, project: str = "", version: int = 0, variant: str = ""):
        async def go(F, user, _b):
            return await F.opened(user, project, slug, version=version or None, variant=variant or None)
        return await _design(request, go, person=False)

    @router.get("/designs/{slug}/preview")
    async def preview(slug: str, request: Request, project: str = "", version: int = 0, variant: str = ""):
        # Its policy — `sandbox allow-scripts`, nothing fetched — is set by
        # `core/middleware.py` (`is_design_preview`); see `design_files.preview`.
        async def go(F, user, _b):
            html = await F.preview(user, project, slug, version=version or None, variant=variant or None)
            return HTMLResponse(html, headers={"Cache-Control": "no-store"})
        return await _design(request, go, person=False)

    @router.post("/designs/{slug}/versions")
    async def keep_version(slug: str, request: Request):
        async def go(F, user, b):
            return await F.save_version(user, str(b.get("project") or ""), slug, str(b.get("note") or ""))
        return await _design(request, go)

    @router.post("/designs/{slug}/restore")
    async def restore_version(slug: str, request: Request):
        async def go(F, user, b):
            v = b.get("version")
            if isinstance(v, bool) or not isinstance(v, int):
                raise F.DesignFileRefused("“version” is a version's number.")
            return await F.restore(user, str(b.get("project") or ""), slug, v)
        return await _design(request, go)

    @router.post("/designs/{slug}/keep")
    async def keep_variant(slug: str, request: Request):
        async def go(F, user, b):
            return await F.keep_variant(user, str(b.get("project") or ""), slug, str(b.get("variant") or ""))
        return await _design(request, go)

    @router.post("/designs/{slug}/adjust")
    async def adjust(slug: str, request: Request):
        async def go(F, user, b):
            return await F.adjust(user, str(b.get("project") or ""), slug, b.get("selector"), b.get("props"),
                                  tokens_css=_tokens_css(user, b.get("system")))
        return await _design(request, go)

    @router.post("/designs/{slug}/tweaks")
    async def tweaks(slug: str, request: Request):
        async def go(F, user, b):
            return await F.suggest_tweaks(user, str(b.get("project") or ""), slug)
        return await _design(request, go)

    return router


def _tokens_css(user, system_id) -> str:
    """The design system's tokens as `:root` properties, so an adjustment to
    `var(--color-ink)` resolves inside the page itself."""
    if not system_id:
        return ""
    from core.database import DesignSystem
    from src import design_systems as D
    db = SessionLocal()
    try:
        row = (db.query(DesignSystem)
               .filter(DesignSystem.account == D.account(user), DesignSystem.id == str(system_id)).first())
        return D.as_css(json.loads(row.tokens)) if row else ""
    finally:
        db.close()


__all__ = ["setup_design_routes"]
