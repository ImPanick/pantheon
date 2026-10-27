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

**Gated with `require_user` and `require_admin`, nothing hand-rolled.** A
further way of asking "is this an admin" is what `.pantheon/check-auth-map.py`
rule C ratchets. (`require_admin` also once honoured an auth-off install,
`B543`; there is none now, `D-2026-10-07-02` §2.) The
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

  GET  /api/workstation/screen   the person's own screen, as one JPEG frame
                                 (an admin may add `?person=<name>` to watch
                                 someone else's, `B1424`; GET /control too —
                                 watching only, never their input):
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

`P25-06` — the agent browser's window. Two more, the caller's own browser only,
through `_mine` like the input route:

  GET  /api/workstation/browser  one frame of the page (not the desktop) with
                                 its address, title and tabs; `?if_none_match`
                                 and an unchanged page is `304`.
  POST /api/workstation/browser  the person's own action — open an address, a
                                 click or a wheel at a point on the frame, typed
                                 text, a key, back, forward, reload, a tab —
                                 sent with `holder: "person"`. Taking the
                                 browser over is the screen's own `control`: it
                                 is on that screen, so there is one holder.

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

from core.middleware import require_admin, require_operator
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

    def _caller_runs_instance(request: Request) -> bool:
        """Whether the status answer includes the admin's view. Asked of
        the operator gate itself rather than restated, so this view and the
        routes beside it that act on it (`/check`, `/machines`, `/backend`)
        answer the same people: an admin, or a person an admin let run the
        instance (`require_operator`, `B683`)."""
        try:
            require_operator(request)
        except HTTPException:
            return False
        return True

    @router.get("/status")
    async def workstation_status(request: Request):
        """Is the workstation on, may I use it, and does it answer."""
        owner = require_user(request)
        return await wa.status_for(owner, is_admin=_caller_runs_instance(request),
                                   auth_manager=_auth_manager(request))

    @router.post("/check")
    async def workstation_check(request: Request):
        """Whoever runs the instance (`B683`): ask the workstation now, even while it is switched off."""
        require_operator(request)
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

    # ── `B1478`: the admin controls the workstation's containers ──────────────
    #
    # `D-2026-10-25-04` §3. Only where the operator gave Pantheon the host's
    # Docker (`docker/host-docker.yml`); otherwise each answer says how to give
    # it. Admin only: these start and stop containers on the host. Only the
    # workstation's own services in Pantheon's own compose project are named,
    # and only start, stop and restart (`src/workstation_control.py`).

    def _docker():
        from src import workstation_control as wctl
        if not wctl.available():
            raise HTTPException(409, wctl.ENABLE_SENTENCE)
        api = wctl.DockerAPI()
        try:
            project = wctl.own_project(api)
        except wctl.DockerControlError as e:
            raise HTTPException(503, str(e))
        if not project:
            raise HTTPException(409, "Pantheon can't tell which compose project it runs in, "
                                     "so it won't touch any container.")
        return wctl, api, project

    @router.get("/machines")
    async def workstation_machines(request: Request):
        """Whoever runs the instance (`B683`): the workstation's containers and what Pantheon may do."""
        require_operator(request)
        from src import workstation_control as wctl
        out: Dict[str, Any] = {"available": wctl.available(), "choice": wa.wc.backend_choice(),
                               "backend": wa.backend_setting(), "vm_configured": wa.wc.vm_configured(),
                               "containers": [], "sentence": ""}
        if not out["available"]:
            out["sentence"] = wctl.ENABLE_SENTENCE
            return out
        try:
            wctl_, api, project = _docker()
            out["project"] = project
            out["containers"] = wctl_.workstation_containers(api, project)
        except HTTPException as e:
            out["sentence"] = e.detail
        except wctl.DockerControlError as e:
            out["sentence"] = str(e)
        return out

    @router.post("/machines/{service}/{action}")
    async def workstation_machine_act(request: Request, service: str, action: str):
        """Whoever runs the instance (`B683`): start, stop or restart one workstation service."""
        require_operator(request)
        wctl, api, project = _docker()
        try:
            done = wctl.act(api, project, service, action)
        except wctl.DockerControlError as e:
            raise HTTPException(400, str(e))
        logger.info("workstation %s: %s by %s", service, action,
                    getattr(request.state, "current_user", None) or "Pantheon")
        return {"ok": True, **done}

    @router.get("/machines/{service}/logs")
    async def workstation_machine_logs(request: Request, service: str, tail: int = 200):
        """Whoever runs the instance (`B683`): the last lines a workstation service wrote."""
        require_operator(request)
        wctl, api, project = _docker()
        try:
            return {"service": service, "text": wctl.logs(api, project, service, tail)}
        except wctl.DockerControlError as e:
            raise HTTPException(400, str(e))

    @router.post("/backend")
    async def workstation_backend(request: Request):
        """Whoever runs the instance (`B683`): choose the backend — stored, and with the host's Docker,
        that backend started and the other stopped."""
        require_operator(request)
        body = await _body(request)
        try:
            choice = wa.validate_setting("workstation_backend", body.get("backend"))
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))
        from src.settings import load_settings, save_settings
        settings = dict(load_settings())
        settings["workstation_backend"] = choice
        save_settings(settings)
        wa.wc.forget_vm_accel()
        backend = wa.backend_setting()
        out: Dict[str, Any] = {"ok": True, "choice": choice, "backend": backend, "steps": [],
                               "sentence": ""}
        from src import workstation_control as wctl
        if not wctl.available():
            out["sentence"] = ("Saved. " + ("Pantheon now talks to that workstation. "
                               if wa.wc.vm_configured() else "") + wctl.ENABLE_SENTENCE)
            return out
        try:
            wctl_, api, project = _docker()
            out.update(wctl_.switch(api, project, backend))
            out["sentence"] = f"Switched to the {backend} workstation: " + ", ".join(out["steps"]) + "."
        except HTTPException as e:
            out["sentence"] = f"Saved, but nothing was switched: {e.detail}"
        except wctl.DockerControlError as e:
            out["sentence"] = f"Saved, but nothing was switched: {e}"
        logger.info("workstation backend set to %s (%s) by %s", choice, backend,
                    getattr(request.state, "current_user", None) or "Pantheon")
        return out

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

    def _watched(request: Request, person: str):
        """`B1424`. `(client, account)` for the screen being watched: the
        caller's own, or — for an admin, and only to watch — another person's.
        Nobody else may name a person here; an admin may not type, take over or
        reset for them (those routes take no `person`)."""
        person = (person or "").strip()
        if not person:
            return _mine(request)
        require_admin(request)
        manager = _auth_manager(request)
        if manager is None:
            from src.auth_manager_access import shared_auth_manager
            manager = shared_auth_manager()
        users = getattr(manager, "users", {}) or {}
        name = person.lower()
        if name not in users:
            raise HTTPException(404, f"There is no person called {person}.")
        try:
            return wa.workstation_for(name, auth_manager=manager)
        except WorkstationError as e:
            raise _http_error(e)

    @router.get("/screen")
    async def workstation_screen(request: Request, if_none_match: str = "", person: str = ""):
        """The caller's own screen, one frame; `304` when it has not changed.
        An admin may pass `person` to watch someone else's (`B1424`)."""
        client, account = _watched(request, person)
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
    async def workstation_holder(request: Request, person: str = ""):
        """Who has the mouse and keyboard right now — on the caller's screen,
        or on the one an admin is watching (`B1424`)."""
        client, account = _watched(request, person)
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

    # ── `P25-06`: the agent browser's window ───────────────────────────────────

    @router.get("/browser")
    async def workstation_browser(request: Request, if_none_match: str = "", since: int = 0):
        """The caller's own browser: one frame of the page, its address, title
        and tabs, and what it did after `since` (`P25-07`); `304` when none
        of that changed."""
        client, account = _mine(request)
        try:
            shot = await client.browser(account, "frame", if_none_match=if_none_match or None,
                                        since=max(0, int(since or 0)))
            if shot is None:
                return Response(status_code=304, headers=_NO_STORE)
            frame = _frame(shot)
        except WorkstationError as e:
            raise _http_error(e)
        tabs = [{"tab": n, "url": str(t.get("url") or "")[:2000], "current": bool(t.get("current"))}
                for n, t in enumerate(shot.get("tabs") or [], start=1) if isinstance(t, dict)]
        activity = [_activity(a) for a in (shot.get("activity") or []) if isinstance(a, dict)]
        seq = shot.get("seq") if isinstance(shot.get("seq"), int) and not isinstance(shot.get("seq"), bool) else 0
        return JSONResponse({**frame, "url": str(shot.get("url") or "")[:4000],
                             "title": str(shot.get("title") or "")[:300], "tabs": tabs,
                             "activity": activity, "seq": seq},
                            headers=_NO_STORE)

    @router.post("/browser")
    async def workstation_browser_act(request: Request):
        """The person's own hand on their browser."""
        client, account = _mine(request)
        body = await _body(request)
        action = body.get("action")
        if action not in _BROWSER_PERSON_ACTIONS:
            raise HTTPException(400, f"“action” is one of {', '.join(_BROWSER_PERSON_ACTIONS)}.")
        fields = {k: body[k] for k in _BROWSER_FIELDS if k in body}
        if action in ("open", "reload", "tab_new"):
            from src.agent_tools.browser_tools import sync_names
            await sync_names(client, account, require_user(request))   # `P27-04`
        try:
            answer = await client.browser(account, action, holder="person", **fields) or {}
        except WorkstationError as e:
            raise _http_error(e)
        out = {"ok": bool(answer.get("ok")), "action": action,
               "url": str(answer.get("url") or "")[:4000], "title": str(answer.get("title") or "")[:300]}
        if isinstance(answer.get("notes"), list):
            out["notes"] = [_note(n) for n in answer["notes"] if isinstance(n, dict)]
        if isinstance(answer.get("pointed"), dict):
            out["pointed"] = _pointed(answer["pointed"])
        return out

    return router


def _activity(a: Dict[str, Any]) -> Dict[str, Any]:
    """`P25-07`. One thing the browser did, as the window is given it: only the
    fields it draws, each its own type."""
    def _int(v):
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    out = {"id": _int(a.get("id")) or 0, "seq": _int(a.get("seq")) or 0,
           "who": "person" if a.get("who") == "person" else "agent",
           "action": str(a.get("action") or "")[:20], "label": str(a.get("label") or "")[:160],
           "phase": a.get("phase") if a.get("phase") in ("doing", "done", "failed") else "done"}
    x, y = _int(a.get("x")), _int(a.get("y"))
    if x is not None and y is not None:
        out["x"], out["y"] = x, y
    # `P25-12`: the agent's sentence for why. `P25-11`: what it looked at.
    if isinstance(a.get("why"), str) and a["why"].strip():
        out["why"] = a["why"][:200]
    box = a.get("box")
    if isinstance(box, list) and len(box) == 4 and all(_int(v) is not None for v in box):
        out["box"] = list(box)
    return out


def _pointed(p: Dict[str, Any]) -> Dict[str, Any]:
    """`P25-10`. What the person pointed at, as their window is given it: enough
    to say it in the message and crop the picture — the facts stay with the
    daemon for the agent's `inspect`."""
    a = p.get("anchor") if isinstance(p.get("anchor"), dict) else None
    facts = p.get("facts") if isinstance(p.get("facts"), dict) else {}
    out = {"url": str(p.get("url") or "")[:2000], "title": str(p.get("title") or "")[:300],
           "page": a is None}
    if a is not None:
        out["tag"] = str(a.get("tag") or "")[:40]
        out["text"] = str(a.get("text") or "")[:80]
        box = facts.get("box")
        if isinstance(box, list) and len(box) == 4 and all(isinstance(v, int) and not isinstance(v, bool) for v in box):
            out["box"] = box
    return out


# `P25-06`. What a person's window may ask of their browser, and the fields it
# may carry; the daemon validates every one (`workstation/browser.py`).
_BROWSER_PERSON_ACTIONS = ("open", "click", "type", "press", "scroll", "back", "forward",
                           "reload", "tab_new", "tab_switch", "tab_close",
                           # `P26-01` … `P26-03`: the person's notes on the page.
                           "note_add", "note_edit", "note_remove", "notes", "note_done", "notes_sent",
                           # `P25-10`: "this is the page I mean".
                           "point")
_BROWSER_FIELDS = ("url", "x", "y", "text", "submit", "keys", "dx", "dy", "tab", "double",
                   "note", "notes", "shapes", "said", "status", "all", "page")


def _note(n: Dict[str, Any]) -> Dict[str, Any]:
    """`P26-01`. One note, as the window is given it: only what it draws."""
    def _ints(v, k):
        return [int(x) for x in v][:k] if isinstance(v, list) and all(
            isinstance(x, int) and not isinstance(x, bool) for x in v) else None
    a = n.get("anchor") if isinstance(n.get("anchor"), dict) else {}
    out = {"id": str(n.get("id") or "")[:80], "n": n.get("n") if isinstance(n.get("n"), int) else 0,
           "page": str(n.get("page") or "")[:2000], "text": str(n.get("text") or "")[:2000],
           "status": n.get("status") if n.get("status") in ("open", "sent", "done", "declined") else "open",
           "said": str(n.get("said") or "")[:600], "lost": bool(n.get("lost")),
           "anchor": {"tag": str(a.get("tag") or "")[:40], "role": str(a.get("role") or "")[:40],
                      "text": str(a.get("text") or "")[:80]},
           "at": _ints(n.get("at"), 2) or [0, 0],
           "shapes": [{"kind": s.get("kind"), "points": [p for p in (s.get("points") or []) if _ints(p, 2)][:200]}
                      for s in (n.get("shapes") or []) if isinstance(s, dict)
                      and s.get("kind") in ("arrow", "circle", "box", "line")][:12]}
    box = _ints(n.get("box"), 4)
    if box and len(box) == 4:
        out["box"] = box
        out["where"] = n.get("where") if n.get("where") in ("here", "above", "below") else "here"
    return out


__all__ = ["setup_workstation_routes"]
