# SPDX-License-Identifier: AGPL-3.0-or-later
"""The workstation, as Settings sees it — `P20-02`, `D-2026-09-30-03`.

Three routes, and who may call each is the row:

  GET  /api/workstation/status   anyone signed in. Is it on, may I use it, does
                                 it answer right now and what it said, my
                                 account and whether my home was there. An
                                 admin's answer also carries the settings in
                                 effect and where each came from — never the
                                 token. A person without the privilege is told
                                 so and nothing is probed on their behalf.
  POST /api/workstation/check    admins. *Check now*: the same answer, probed
                                 even while the workstation is switched off, so
                                 an admin can start the overlay, check it, and
                                 then turn it on. Pushes the admin's `sudo`.
  POST /api/workstation/reset    anyone who may use it, for themselves only.
                                 There is no parameter naming whose home: the
                                 account is derived from the caller, so there
                                 is nothing to tamper with. The panel asks
                                 first.

**Gated with `require_user` and `require_admin`, nothing hand-rolled.** Only
`require_admin` honours `auth_disabled()` (`B543`), and a further way of asking
"is this an admin" is what `.pantheon/check-auth-map.py` rule C ratchets. The
status answer needs to know whether to include the admin's view, so it asks
`require_admin` and treats a 403 as "no" (`_caller_is_admin`); both sites are
mapped in `.pantheon/P11-AUTH-MAP.md`. `require_user` refuses a bearer API
token outright — a delegated credential does not inherit its owner's
workstation (`B70`).

The agent's generic `app_api` bridge is refused `POST /api/workstation…`
(`src/tools/system.py`): a reset erases a person's home, and the bridge is the
owner on every route it is not refused.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from core.middleware import require_admin
from src import workstation_access as wa
from src.auth_helpers import require_user
from src.workstation_client import WorkstationError

logger = logging.getLogger(__name__)

# A refusal from the workstation layer, as an HTTP status. The sentence travels
# as the detail unchanged — it was written for a person (`protocol.error_body`).
_STATUS_FOR = {
    "not_permitted": 403,
    "off": 409,
    "unconfigured": 409,
    "busy": 409,
    "unavailable": 503,
    "not_found": 404,
    "bad_request": 400,
}


def _http_error(e: WorkstationError) -> HTTPException:
    # Anything else — Pantheon's token refused, the daemon's own failure — is the
    # workstation's answer passed through, which is a gateway's 502.
    return HTTPException(_STATUS_FOR.get(e.code, 502), e.message)


def setup_workstation_routes() -> APIRouter:
    router = APIRouter(prefix="/api/workstation", tags=["workstation"])

    def _auth_manager(request: Request):
        return getattr(request.app.state, "auth_manager", None)

    def _caller_is_admin(request: Request) -> bool:
        """Whether the status answer includes the admin's view. Asked of
        `require_admin` itself rather than restated, so auth-off and the
        single operator get the same answer here as on every admin route."""
        try:
            require_admin(request)
        except HTTPException:
            return False
        return True

    @router.get("/status")
    async def workstation_status(request: Request):
        """Is the workstation on, may I use it, and does it answer."""
        owner = require_user(request)
        return await wa.status_for(owner, is_admin=_caller_is_admin(request),
                                   auth_manager=_auth_manager(request))

    @router.post("/check")
    async def workstation_check(request: Request):
        """Admin only: ask the workstation now, even while it is switched off."""
        require_admin(request)
        owner = require_user(request)
        return await wa.status_for(owner, is_admin=True, auth_manager=_auth_manager(request),
                                   probe_when_off=True)

    @router.post("/reset")
    async def workstation_reset(request: Request):
        """The caller's own workstation home, back to a clean start."""
        owner = require_user(request)
        try:
            answer = await wa.reset_home(owner, auth_manager=_auth_manager(request))
        except WorkstationError as e:
            raise _http_error(e)
        logger.info("workstation home reset for %s", answer.get("account"))
        return {"ok": True, "account": answer.get("account"),
                "sentence": "Your workstation home is back to a clean start."}

    return router


__all__ = ["setup_workstation_routes"]
