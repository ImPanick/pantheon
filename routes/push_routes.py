# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web Push for one person's own devices. `B1830`, `src/web_push.py`.

Every route is the signed-in person's and nobody else's (`require_user`: a
cookie session; a bearer token is refused, because the one thing a push here
carries that matters — a tool approval — may only be answered by a person,
`chat_routes._reject_delegated_tool_approval`). A person sees, adds, removes
and tests only their own devices.

The caller is `static/js/pushSettings.js` (Settings → Reminders → *Push to
your devices*); the approval the notification answers goes through
`POST /api/chat_stream`, the card's own route, from `static/sw.js`.
"""

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from src import web_push
from src.auth_helpers import require_user


def setup_push_routes() -> APIRouter:
    router = APIRouter(tags=["push"])
    web_push.install()

    @router.get("/api/push/key")
    async def push_key(user: str = Depends(require_user)) -> Dict[str, Any]:
        """The server's public key, which the browser's `subscribe` needs."""
        try:
            key = web_push.public_key()
        except Exception as exc:
            raise HTTPException(500, f"Pantheon could not read its push key: {exc}")
        return {"public_key": key}

    @router.get("/api/push/subscriptions")
    async def push_devices(user: str = Depends(require_user)) -> Dict[str, Any]:
        return {"devices": web_push.list_devices(user)}

    @router.post("/api/push/subscriptions")
    async def push_subscribe(request: Request,
                             user: str = Depends(require_user)) -> Dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "Expected a JSON object.")
        try:
            device = web_push.subscribe(user, body.get("subscription"),
                                        label=body.get("label"))
        except web_push.PushError as exc:
            raise HTTPException(400, str(exc))
        return {"device": device}

    @router.delete("/api/push/subscriptions")
    async def push_unsubscribe(request: Request,
                               user: str = Depends(require_user)) -> Dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body if isinstance(body, dict) else {}
        removed = web_push.unsubscribe(user, device_id=body.get("id"),
                                       endpoint=body.get("endpoint"))
        return {"removed": removed}

    @router.post("/api/push/test")
    async def push_test(request: Request,
                        user: str = Depends(require_user)) -> Dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body if isinstance(body, dict) else {}
        results = await web_push.send_to_owner(user, {
            "type": "test",
            "title": "Pantheon can reach this device",
            "body": "Push works. Tool approvals will arrive here with Approve and Deny.",
            "tag": f"push-test-{int(time.time())}",
        }, ttl=300, urgency="high", device_id=body.get("id") or None)
        if not results:
            raise HTTPException(404, "Push is not on for any of your devices yet.")
        return {"results": results}

    return router
