# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1475`, `D-2026-10-25-04` §5 · Each person's own networks, over HTTP.

    GET  /api/networks/mine          my networks (each linked login's label: mine to
                                     read), the install's names, what a task may pick
    PUT  /api/networks/mine          {networks: [...]} replace my list — refused whole,
                                     with every problem, or while an admin has it off
    POST /api/networks/mine/check    {networks, probe?} the problems with what is on
                                     screen, and which network claims `probe`
    GET  /api/networks/people        admin: every person's networks; of a linked login
                                     only `login_linked` — never which, nor anything in it

**Only a person** changes their list (`request_is_a_person`): linking a vault
login to a network decides what the agent signs in with, and a token or the
assistant's own loopback choosing that would be a credential choosing its own
reach — the vault's rule (`routes/vault_mine_routes.py`).

Every refusal is `{detail: "<sentence>"}` (`Law 15`). Each path is spelled in
`static/js/personNetworks.js` (`check-unreachable.py`).
"""

from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import SessionLocal
from core.middleware import require_admin
from src.auth_helpers import get_current_user, request_is_a_person

BODY_MAX_BYTES = 64 * 1024
ONLY_A_PERSON = ("Only a person signed in to Pantheon can change their networks — "
                 "not an API token or the assistant.")


def _refused(sentence: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": sentence}, status_code=status)


async def _body(request: Request) -> Dict[str, Any]:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > BODY_MAX_BYTES:
            raise ValueError("The request is larger than 64 KiB, so it was not read.")
    if not bytes(raw).strip():
        return {}
    try:
        body = json.loads(bytes(raw))
    except (TypeError, ValueError):
        raise ValueError("The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise ValueError("The request body must be a JSON object.")
    return body


def _choices(owner) -> list:
    """What a task's *Networks* may name: every network this person's runs see,
    and *the internet*."""
    from src import networks as N
    names = [n.name for n in N.declared_networks(owner=owner)]
    return names + [N.OUTSIDE] if names else []


def setup_person_network_routes() -> APIRouter:
    router = APIRouter(prefix="/api/networks", tags=["networks"])

    @router.get("/mine")
    def my_networks(request: Request):
        from src import person_networks as PN
        user = get_current_user(request)
        db = SessionLocal()
        try:
            return {**PN.mine(db, user), "choices": _choices(user)}
        finally:
            db.close()

    @router.put("/mine")
    async def save_my_networks(request: Request):
        from src import person_networks as PN
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e), 413 if "64 KiB" in str(e) else 400)
        user = get_current_user(request)
        db = SessionLocal()
        try:
            return {**PN.save(db, user, body.get("networks", [])), "choices": _choices(user)}
        except PN.NetworksRefused as r:
            db.rollback()
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    @router.post("/mine/check")
    async def check_my_networks(request: Request):
        """Nothing is saved: the panel asks about what is on screen."""
        from src import person_networks as PN
        from src.networks import matches_for
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        value = body.get("networks", [])
        probe = str(body.get("probe") or "").strip()
        user = get_current_user(request)
        db = SessionLocal()
        try:
            problems = PN.validate(db, user, value)
        finally:
            db.close()
        return {"problems": problems, "probe": probe,
                "matched": matches_for(value, probe) if probe else None}

    @router.get("/people")
    def everyones_networks(request: Request):
        """Admin only. `D-2026-10-25-04` §5: the admin sees every endpoint a
        person declared, and of a login only that one is linked."""
        require_admin(request)
        from src import person_networks as PN
        mgr = getattr(request.app.state, "auth_manager", None)
        people = list((getattr(mgr, "users", None) or {}).keys())
        db = SessionLocal()
        try:
            return {"enabled": PN.enabled(), "people": PN.everyone(db, people)}
        finally:
            db.close()

    return router


__all__ = ["setup_person_network_routes"]
