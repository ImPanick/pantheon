# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P25-02` / `P25-04` · Git, per account, over HTTP.

    GET  /api/git         my identity and my hosts (never a token), and the forges to pick from
    PUT  /api/git         change them: {identity: {name, email} | null,
                                        hosts: {host: {username?, token} | null}}
    GET  /api/git/repos   the repositories where my shell starts, each with its branch and
                          how many changes it holds — *+ → Git ›* (`P25-04`)

Everything here is the caller's own: there is no route to another person's
identity or hosts, an admin's included. **Only a person** changes them
(`request_is_a_person`): a token stored here is used by every git call the
agent makes as that person, so an API token or the assistant's own loopback
writing one would be a credential choosing its own reach.

Every refusal is `{detail: "<sentence>"}` (`Law 15`). The route ceiling
(`check-unreachable.py`): each path is spelled in `static/js/gitSettings.js`
or `static/js/composerMenu.js`, its callers.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import SessionLocal
from src.auth_helpers import get_current_user, request_is_a_person

logger = logging.getLogger(__name__)

BODY_MAX_BYTES = 16 * 1024
ONLY_A_PERSON = ("Only a person signed in to Pantheon can change their git identity or tokens — "
                 "not an API token or the assistant.")


def _refused(sentence: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": sentence}, status_code=status)


async def _body(request: Request) -> Dict[str, Any]:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > BODY_MAX_BYTES:
            raise ValueError("The request is larger than 16 KiB, so it was not read.")
    if not bytes(raw).strip():
        return {}
    try:
        body = json.loads(bytes(raw))
    except (TypeError, ValueError):
        raise ValueError("The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise ValueError("The request body must be a JSON object.")
    return body


def setup_git_routes() -> APIRouter:
    router = APIRouter(prefix="/api/git", tags=["git"])

    @router.get("")
    def my_git(request: Request):
        from src import git_accounts as G
        db = SessionLocal()
        try:
            return G.public(db, get_current_user(request))
        finally:
            db.close()

    @router.put("")
    async def change_my_git(request: Request):
        from src import git_accounts as G
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e), 413 if "16 KiB" in str(e) else 400)
        db = SessionLocal()
        try:
            return G.change(db, get_current_user(request), body)
        except G.GitRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.get("/repos")
    async def my_repos(request: Request):
        from src.agent_tools.git_tools import list_repos
        from src.tool_execution import _works_in_workstation
        user = get_current_user(request)
        workspace = (request.query_params.get("workspace") or "").strip() or None
        station = host = None
        if workspace and _works_in_workstation(user):
            from src.agent_tools.workstation_tools import vet_workspace
            from src.workstation_client import WorkstationError
            try:
                station = await vet_workspace(user, workspace)
            except WorkstationError as e:
                return _refused(e.message, 503)
        elif workspace:
            from src.tool_execution import vet_workspace as vet_host
            host = vet_host(workspace)
        got = await list_repos(user, station_workspace=station, host_workspace=host)
        if got.get("error"):
            return _refused(got["error"], 409)
        return got

    return router
