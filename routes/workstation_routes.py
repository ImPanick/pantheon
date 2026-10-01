# SPDX-License-Identifier: AGPL-3.0-or-later
"""The workstation, as Settings sees it — `P20-02`, `D-2026-09-30-03` — and as
the person watching it sees it — `P20-05`.

Settings has three routes, and who may call each is the row:

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

`P20-05` — a window onto the workstation. Four more, all for the caller's own
display and nobody else's, and all through `workstation_for` — so the admin's
switch, the address and `can_use_workstation` are asked exactly as the agent's
tools ask them, with the same sentence when one says no:

  GET  /api/workstation/screen   the person's own screen, as one JPEG frame:
                                 `{mime, data_b64, width, height, digest}`.
                                 `?if_none_match=<digest>` and an unchanged
                                 screen is `304` with no body — the protocol's
                                 own conditional, passed through, so a frame
                                 nobody changed is not sent twice.
  POST /api/workstation/input    the person's mouse and keyboard: one of the
                                 protocol's actions, sent with `holder:
                                 "person"`. Only the protocol's input fields are
                                 passed on; the daemon validates every one.
  GET  /api/workstation/control  who has the screen now (`ensure`'s answer —
                                 the protocol reads it there on purpose).
  POST /api/workstation/control  take over (`person`) or hand back (`agent`).
                                 While a person holds it, the agent's input is
                                 `busy` with the daemon's sentence (`P20-04`).

**Why a person's input carries `holder: "person"` and nothing else can.** The
body's own `holder` is dropped: this route speaks for the person at the
keyboard, which is the one thing the daemon cannot tell from the wire. The
bridge is refused every `POST` here by the prefix above, so an agent cannot
reach this route to type as the person past its own `busy`.

**The token never reaches the browser**: a frame is the daemon's picture
re-sent, and nothing else of its answer passes through. JPEG because it is
real in the image and about 20 ms a grab there against 65–70 ms for PNG
(measured in `P20-01`).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from core.middleware import require_admin
from src import workstation_access as wa
from src.auth_helpers import require_user
from src.workstation_client import WorkstationError
from workstation import protocol as P

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


# ── `P20-05`: the screen ──────────────────────────────────────────────────────

#: The format the window asks for. Real JPEG in the image (`P20-01`: 20–24 ms a
#: grab, against 65–70 ms for PNG), and a viewer polling a few times a second is
#: what JPEG is for.
FRAME_FORMAT = "jpeg"
# What a frame may be drawn as. The daemon names its picture's type; the window
# builds a `data:` URL from it, so only these two pass — anything else is a
# workstation answering with something that is not a screen.
_FRAME_MIMES = frozenset({"image/jpeg", "image/png"})
# `digest` is the daemon's 16 hex characters (`agentd.screenshot`), checked on
# the way out. The conditional on the way in is passed on as it came: the
# client URL-encodes it and the daemon only ever compares it with the frame's
# digest, so any other string gets the frame (a check here was measured
# unobservable — the one mutation of this route that survived).
_DIGEST_RE = re.compile(r"^[0-9a-f]{16}$")
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")
# The fields a person's input may carry: the protocol's own, minus `holder`
# (this route sets it) and `screenshot_after` (the window is already watching).
_INPUT_FIELDS = ("x", "y", "to_x", "to_y", "text", "keys", "dx", "dy", "ms")
_NO_STORE = {"Cache-Control": "no-store"}

# What the window says about who has the screen. Said here, beside the routes
# that answer the question, so the window has no sentences of its own to drift.
TAKEN_OVER_SENTENCE = ("You have the mouse and keyboard. The agent waits until you hand "
                       "them back.")
HANDED_BACK_SENTENCE = "The agent has the mouse and keyboard again."
WATCHING_SENTENCE = "The agent has the mouse and keyboard. You are watching."


def _holder_answer(holder: Any, *, changed: bool = False) -> Dict[str, Any]:
    holder = holder if holder in P.HOLDERS else "agent"
    if holder == "person":
        sentence = TAKEN_OVER_SENTENCE
    else:
        sentence = HANDED_BACK_SENTENCE if changed else WATCHING_SENTENCE
    return {"holder": holder, "sentence": sentence}


def _frame(shot: Dict[str, Any]) -> Dict[str, Any]:
    """The daemon's screenshot answer, as the window is given it — the picture
    and its size and digest, and nothing else of what the daemon said."""
    mime = shot.get("mime")
    data = shot.get("data_b64")
    digest = shot.get("digest")
    width, height = shot.get("width"), shot.get("height")
    if (mime not in _FRAME_MIMES or not isinstance(data, str) or not _BASE64_RE.match(data)
            or not isinstance(digest, str) or not _DIGEST_RE.match(digest)
            or not isinstance(width, int) or not isinstance(height, int)
            or isinstance(width, bool) or isinstance(height, bool)):
        raise WorkstationError("internal", "The workstation sent a screen Pantheon cannot show.")
    return {"mime": mime, "data_b64": data, "width": width, "height": height,
            "digest": digest}


async def _body(request: Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — an empty or broken body is "nothing was sent"
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, "The request body is a JSON object.")
    return body


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

    # ── `P20-05`: watch it, take it over, hand it back ────────────────────────

    def _mine(request: Request):
        """`(client, account)` for the caller's own display. The account is the
        caller's — there is no parameter naming whose, here or in any route
        below — and every refusal is `workstation_for`'s own sentence."""
        owner = require_user(request)
        try:
            return wa.workstation_for(owner, auth_manager=_auth_manager(request))
        except WorkstationError as e:
            raise _http_error(e)

    @router.get("/screen")
    async def workstation_screen(request: Request, if_none_match: str = ""):
        """The caller's own screen, one frame; `304` when it has not changed."""
        client, account = _mine(request)
        try:
            shot = await client.screenshot(account, fmt=FRAME_FORMAT,
                                           if_none_match=if_none_match or None)
            if shot is None:
                return Response(status_code=304, headers=_NO_STORE)
            frame = _frame(shot)
        except WorkstationError as e:
            raise _http_error(e)
        return JSONResponse(frame, headers=_NO_STORE)

    @router.post("/input")
    async def workstation_input(request: Request):
        """The person's own mouse and keyboard, on their own display."""
        client, account = _mine(request)
        body = await _body(request)
        action = body.get("action")
        if action not in P.INPUT_ACTIONS:
            raise HTTPException(400, f"“action” is one of {', '.join(P.INPUT_ACTIONS)}.")
        fields = {k: body[k] for k in _INPUT_FIELDS if k in body}
        try:
            answer = await client.input(account, action, holder="person", **fields)
        except WorkstationError as e:
            raise _http_error(e)
        return {"ok": bool(answer.get("ok")), "action": answer.get("action")}

    @router.get("/control")
    async def workstation_holder(request: Request):
        """Who has the mouse and keyboard right now."""
        client, account = _mine(request)
        try:
            made = await client.ensure(account)
        except WorkstationError as e:
            raise _http_error(e)
        return _holder_answer(made.get("holder"))

    @router.post("/control")
    async def workstation_control(request: Request):
        """Take over (`person`) or hand back (`agent`) the caller's own screen."""
        client, account = _mine(request)
        holder = (await _body(request)).get("holder")
        if holder not in P.HOLDERS:
            raise HTTPException(400, "“holder” is “person” (take over) or “agent” (hand back).")
        try:
            answer = await client.control(account, holder)
        except WorkstationError as e:
            raise _http_error(e)
        logger.info("workstation screen of %s: %s holds it", account, holder)
        return {**_holder_answer(answer.get("holder"), changed=True),
                "since": answer.get("since")}

    return router


__all__ = ["setup_workstation_routes"]
