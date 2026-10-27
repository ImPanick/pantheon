# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-04` / `P26-05` · The Design window's design systems, over HTTP.

    GET    /api/design/systems?project=   mine: personal ones, and the project's;
                                          and those shared with me (`shared`)
    POST   /api/design/systems/extract    {text?, file?: {name, data_b64}} → {tokens, warnings, css}
                                          — read by the model, kept nowhere
    POST   /api/design/systems            {name, scope, project?, tokens, accept_low_contrast?}
    PUT    /api/design/systems/{id}       the same fields, any of them (an editor it is
                                          shared with: its name and tokens)
    DELETE /api/design/systems/{id}       its owner's

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

`P26-08` · *Build it* (`src/design_build.py`), the owner's:

    POST   /api/design/designs/{slug}/build                 {project, base?, acceptance?} → the branch
                                                            design/<slug>, its folder, BUILD.md committed
    GET    /api/design/designs/{slug}/build?project=        its commits, changes, whether the base moved
    POST   /api/design/designs/{slug}/build/preview         {project, address} where the person previews it
    POST   /api/design/designs/{slug}/build/merge           {project, yes: true} — a person's yes, or nothing
    POST   /api/design/designs/{slug}/build/close           {project} remove the build folder (the branch stays)

`P26-09` · collaborators (`src/design_access.py`, the one check):

    GET    /api/design/shared                               shared with me: designs and systems
    GET    /api/design/shares?kind=&project=&ref=           whom I shared one of mine with
    POST   /api/design/shares                               {kind, project?, ref, invitee, role} invite by name,
                                                            or change a role — the owner's
    DELETE /api/design/shares/{id}                          revoke — the owner's
    GET    /api/design/notes?kind=&project=&ref=&share=     a design's or a system's notes, with authors
    POST   /api/design/notes                                {kind, project?|share?, ref, text, selector?}
                                                            — a commenter, an editor or the owner
    DELETE /api/design/notes/{id}?kind=&project=&ref=&share=
                                                            its author's, or the owner's
    POST   /api/design/presence                             {kind, project?|share?, ref} → who has it open

A design is named as the caller's own (`project` and the slug) or by `share`,
the id of a share whose invitee is the caller; every route that reads or
changes one asks `design_access` with the role it needs — a viewer reads, an
editor writes, the owner shares. A stranger's request is 404 — the same as a
design that is not there — and a commenter's write is refused here, by the
server, whatever the window shows. Every refusal is `{detail: "<sentence>"}`
(`Law 15`); a contrast pair below AA is `422` with the sentence, until the
person saves knowing it. The route ceiling (`check-unreachable.py`): each path
is spelled in `static/js/design/designWindow.js` or `designView.js`.
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


def _access_for(user, kind: Any, project: Any, ref: Any, share: Any):
    """`P26-09`. The one door: a design or a design system the caller may
    reach, with their role — or `AccessRefused` (404 for a stranger)."""
    from src import design_access as A
    if kind not in A.KINDS:
        raise A.AccessRefused("“kind” is design or system.")
    db = SessionLocal()
    try:
        if kind == "system":
            return A.system_access(db, user, ref)
        if not share:
            from src.design_files import _clean_slug, DesignFileRefused
            try:
                _clean_slug(ref)
            except DesignFileRefused:
                raise A.AccessRefused(A.NOT_FOUND["design"], 404) from None
        acc = A.design_access(db, user, project=project, slug=ref, share=share)
        if share and ref and str(ref).strip().lower() != acc.ref:
            # A share names one design; it is never a key to the rest of the project.
            raise A.AccessRefused(A.NOT_FOUND["design"], 404)
        return acc
    finally:
        db.close()


def setup_design_routes() -> APIRouter:
    router = APIRouter(prefix="/api/design", tags=["design"])

    @router.get("/systems")
    def my_systems(request: Request, project: str = ""):
        from src import design_access as A
        from src import design_systems as D
        user = get_current_user(request)
        db = SessionLocal()
        try:
            shared = []
            for s in A.shared_with(db, user)["systems"]:
                try:
                    acc = A.system_access(db, user, s["system"])
                except A.AccessRefused:
                    continue   # its owner removed it since
                from core.database import DesignSystem
                row = db.query(DesignSystem).filter(DesignSystem.id == acc.ref).first()
                shared.append({**D.public(row), "shared": {"share": acc.share_id, "owner": acc.owner,
                                                           "role": acc.role}})
            return {"systems": D.listing(db, user, project.strip() or None) + shared,
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
        from src import design_access as A
        from src import design_systems as D
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        user = get_current_user(request)
        owner = user
        if system_id:
            # `P26-09`. An editor it is shared with changes its name and
            # tokens, in its owner's store; where it lives stays the owner's.
            try:
                acc = A.need(_access_for(user, "system", "", system_id, None), "editor")
            except A.AccessRefused as r:
                return _refused(r.sentence, r.status)
            if not acc.mine:
                owner = acc.owner
                body = {k: v for k, v in body.items() if k in ("name", "tokens", "accept_low_contrast")}
        db = SessionLocal()
        try:
            return await D.save(db, owner, body, system_id)
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
        from src import design_access as A
        from src import design_systems as D
        if not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        user = get_current_user(request)
        try:
            A.need(_access_for(user, "system", "", system_id, None), "owner")
        except A.AccessRefused as r:
            return _refused(r.sentence, r.status)
        db = SessionLocal()
        try:
            D.remove(db, user, system_id)
            A.forget_system(db, system_id)
            db.commit()
            return {"ok": True}
        except D.DesignRefused as r:
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    # ── designs, as files (`P26-06` / `P26-07`) ─────────────────────────────

    async def _design(request: Request, fn, *, person: bool = True, slug: str = "", at_least: str = "editor"):
        """One design, as the caller may reach it (`P26-09`): their own by
        `project`, or one shared with them by `share` — with at least the role
        the route needs. `fn(F, access, body)`; `access.owner` opens the
        owner's project."""
        from src import design_access as A
        from src import design_files as F
        if person and not request_is_a_person(request):
            return _refused(ONLY_A_PERSON, 403)
        try:
            body = await _body(request) if request.method != "GET" else {}
        except ValueError as e:
            return _refused(str(e))
        user = get_current_user(request)
        share = body.get("share") or request.query_params.get("share")
        project = body.get("project") if "project" in body else request.query_params.get("project", "")
        try:
            if share:
                acc = A.need(_access_for(user, "design", "", slug, share), at_least)
            else:
                acc = A.Access("design", user, str(project or "").strip(), str(slug or "").strip().lower(), "owner")
        except A.AccessRefused as r:
            return _refused(r.sentence, r.status)
        try:
            return await fn(F, acc, body)
        except (F.DesignFileRefused, A.AccessRefused) as r:
            return _refused(r.sentence, r.status)

    @router.get("/designs")
    async def my_designs(request: Request, project: str = ""):
        async def go(F, acc, _b):
            return {"designs": await F.listing(acc.owner, acc.project)}
        return await _design(request, go, person=False, at_least="owner")

    @router.post("/designs")
    async def new_design(request: Request):
        async def go(F, acc, b):
            return await F.create(acc.owner, acc.project, b)
        return await _design(request, go, at_least="owner")

    @router.get("/designs/{slug}")
    async def one_design(slug: str, request: Request, version: int = 0, variant: str = ""):
        from src import design_access as A

        async def go(F, acc, _b):
            got = await F.opened(acc.owner, acc.project, slug if acc.mine else acc.ref,
                                 version=version or None, variant=variant or None)
            # `P26-09`: whose it is, what the caller may do, and who has it open.
            return {**got, "access": {"role": acc.role, "owner": acc.owner, "share": acc.share_id,
                                      "present": A.seen(acc, get_current_user(request))}}
        return await _design(request, go, person=False, slug=slug, at_least="viewer")

    @router.get("/designs/{slug}/preview")
    async def preview(slug: str, request: Request, version: int = 0, variant: str = ""):
        # Its policy — `sandbox allow-scripts`, nothing fetched — is set by
        # `core/middleware.py` (`is_design_preview`); see `design_files.preview`.
        async def go(F, acc, _b):
            html = await F.preview(acc.owner, acc.project, acc.ref or slug,
                                   version=version or None, variant=variant or None)
            return HTMLResponse(html, headers={"Cache-Control": "no-store"})
        return await _design(request, go, person=False, slug=slug, at_least="viewer")

    @router.post("/designs/{slug}/versions")
    async def keep_version(slug: str, request: Request):
        async def go(F, acc, b):
            return await F.save_version(acc.owner, acc.project, acc.ref or slug, str(b.get("note") or ""))
        return await _design(request, go, slug=slug)

    @router.post("/designs/{slug}/restore")
    async def restore_version(slug: str, request: Request):
        async def go(F, acc, b):
            v = b.get("version")
            if isinstance(v, bool) or not isinstance(v, int):
                raise F.DesignFileRefused("“version” is a version's number.")
            return await F.restore(acc.owner, acc.project, acc.ref or slug, v)
        return await _design(request, go, slug=slug)

    @router.post("/designs/{slug}/keep")
    async def keep_variant(slug: str, request: Request):
        async def go(F, acc, b):
            return await F.keep_variant(acc.owner, acc.project, acc.ref or slug, str(b.get("variant") or ""))
        return await _design(request, go, slug=slug)

    @router.post("/designs/{slug}/adjust")
    async def adjust(slug: str, request: Request):
        async def go(F, acc, b):
            return await F.adjust(acc.owner, acc.project, acc.ref or slug, b.get("selector"), b.get("props"),
                                  tokens_css=_tokens_css(get_current_user(request), b.get("system")))
        return await _design(request, go, slug=slug)

    @router.post("/designs/{slug}/tweaks")
    async def tweaks(slug: str, request: Request):
        async def go(F, acc, b):
            return await F.suggest_tweaks(acc.owner, acc.project, acc.ref or slug)
        return await _design(request, go, slug=slug)

    # ── *Build it* (`P26-08`) — the owner's, and the merge a person's yes ────

    @router.post("/designs/{slug}/build")
    async def build(slug: str, request: Request):
        """Make `design/<slug>` and its folder, and commit the brief there.
        Nothing on the base branch moves."""
        from src import design_build as B

        async def go(F, acc, b):
            facts = await F.describe(acc.owner, acc.project, acc.ref)
            css, sys_name = _system_for_brief(acc.owner, facts.get("system"))
            return await B.start(acc.owner, acc.project, acc.ref, base=b.get("base"), acceptance=b.get("acceptance"),
                                 system_css=css, system_name=sys_name, notes=_notes_for_brief(acc))
        return await _design(request, go, slug=slug, at_least="owner")

    @router.get("/designs/{slug}/build")
    async def build_status(slug: str, request: Request):
        from src import design_build as B

        async def go(F, acc, _b):
            return await B.status(acc.owner, acc.project, acc.ref)
        return await _design(request, go, slug=slug, at_least="owner")

    @router.post("/designs/{slug}/build/preview")
    async def build_preview(slug: str, request: Request):
        from src import design_build as B

        async def go(F, acc, b):
            return await B.set_preview(acc.owner, acc.project, acc.ref, b.get("address"))
        return await _design(request, go, slug=slug, at_least="owner")

    @router.post("/designs/{slug}/build/merge")
    async def build_merge(slug: str, request: Request):
        """The person's yes, and only theirs: `_design` refuses a token or the
        assistant before this runs, and `yes` must be a literal true."""
        from src import design_build as B

        async def go(F, acc, b):
            return await B.merge(acc.owner, acc.project, acc.ref, yes=b.get("yes"))
        return await _design(request, go, slug=slug, at_least="owner")

    @router.post("/designs/{slug}/build/close")
    async def build_close(slug: str, request: Request):
        from src import design_build as B

        async def go(F, acc, _b):
            return await B.close(acc.owner, acc.project, acc.ref)
        return await _design(request, go, slug=slug, at_least="owner")

    # ── collaborators (`P26-09`) ────────────────────────────────────────────

    @router.get("/shared")
    def shared_with_me(request: Request):
        from src import design_access as A
        db = SessionLocal()
        try:
            return A.shared_with(db, get_current_user(request))
        finally:
            db.close()

    @router.get("/shares")
    def my_shares(request: Request, kind: str = "design", project: str = "", ref: str = ""):
        from src import design_access as A
        user = get_current_user(request)
        try:
            acc = _access_for(user, kind, project, ref, None)
            db = SessionLocal()
            try:
                return {"shares": A.shares_of(db, user, acc), "roles": list(A.ROLES)}
            finally:
                db.close()
        except A.AccessRefused as r:
            return _refused(r.sentence, r.status)

    @router.post("/shares")
    async def invite(request: Request):
        """Only the owner shares, and only a person: a token or the assistant
        choosing who may read someone's designs is a credential widening its
        own owner's reach."""
        from src import design_access as A
        from src import design_files as F
        if not request_is_a_person(request):
            return _refused("Only a person signed in to Pantheon shares their designs.", 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        user = get_current_user(request)
        try:
            acc = A.need(_access_for(user, body.get("kind"), body.get("project"), body.get("ref"), None), "owner")
            if acc.kind == "design":
                facts = await F.describe(user, acc.project, acc.ref)   # 404 for a design that is not there
                acc = A.Access("design", user, acc.project, acc.ref, "owner", None, facts["name"])
            db = SessionLocal()
            try:
                return A.share(db, user, acc, body.get("invitee"), body.get("role"))
            finally:
                db.close()
        except (A.AccessRefused, F.DesignFileRefused) as r:
            return _refused(r.sentence, r.status)

    @router.delete("/shares/{share_id}")
    def revoke(share_id: str, request: Request):
        from src import design_access as A
        if not request_is_a_person(request):
            return _refused("Only a person signed in to Pantheon changes whom their designs are shared with.", 403)
        db = SessionLocal()
        try:
            A.revoke(db, get_current_user(request), share_id)
            return {"ok": True}
        except A.AccessRefused as r:
            return _refused(r.sentence, r.status)
        finally:
            db.close()

    def _note_access(request: Request, params: Dict[str, Any]):
        return _access_for(get_current_user(request), params.get("kind") or "design", params.get("project"),
                           params.get("ref"), params.get("share"))

    @router.get("/notes")
    def design_notes(request: Request):
        from src import design_access as A
        try:
            acc = _note_access(request, dict(request.query_params))
            db = SessionLocal()
            try:
                return {"notes": A.notes(db, acc), "role": acc.role}
            finally:
                db.close()
        except A.AccessRefused as r:
            return _refused(r.sentence, r.status)

    @router.post("/notes")
    async def add_note(request: Request):
        from src import design_access as A
        if not request_is_a_person(request):
            return _refused("Only a person signed in to Pantheon writes notes on a design.", 403)
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        try:
            acc = _note_access(request, body)
            db = SessionLocal()
            try:
                return A.add_note(db, get_current_user(request), acc, body.get("text"), body.get("selector"))
            finally:
                db.close()
        except A.AccessRefused as r:
            return _refused(r.sentence, r.status)

    @router.delete("/notes/{note_id}")
    def remove_note(note_id: str, request: Request):
        from src import design_access as A
        if not request_is_a_person(request):
            return _refused("Only a person signed in to Pantheon removes notes on a design.", 403)
        try:
            acc = _note_access(request, dict(request.query_params))
            db = SessionLocal()
            try:
                A.remove_note(db, get_current_user(request), note_id, acc)
                return {"ok": True}
            finally:
                db.close()
        except A.AccessRefused as r:
            return _refused(r.sentence, r.status)

    @router.post("/presence")
    async def presence(request: Request):
        from src import design_access as A
        try:
            body = await _body(request)
        except ValueError as e:
            return _refused(str(e))
        try:
            acc = A.need(_note_access(request, body), "viewer")
        except A.AccessRefused as r:
            return _refused(r.sentence, r.status)
        return {"present": A.seen(acc, get_current_user(request))}

    return router


def _system_for_brief(user, system_id):
    """`(css, name)` of the design's system, for `BUILD.md` (`P26-08`)."""
    if not system_id:
        return "", ""
    from core.database import DesignSystem
    from src import design_access as A
    db = SessionLocal()
    try:
        try:
            acc = A.system_access(db, user, system_id)
        except A.AccessRefused:
            return "", ""
        row = db.query(DesignSystem).filter(DesignSystem.id == acc.ref).first()
        name = row.name if row else ""
    finally:
        db.close()
    return _tokens_css(user, system_id), name


def _notes_for_brief(acc):
    """Every note on the design, with its author (`P26-09`), for `BUILD.md`."""
    from src import design_access as A
    db = SessionLocal()
    try:
        return A.notes_for_brief(db, acc)
    finally:
        db.close()


def _tokens_css(user, system_id) -> str:
    """The design system's tokens as `:root` properties, so an adjustment to
    `var(--color-ink)` resolves inside the page itself. A system shared with
    the caller counts as theirs here (`P26-09`)."""
    if not system_id:
        return ""
    from core.database import DesignSystem
    from src import design_access as A
    from src import design_systems as D
    db = SessionLocal()
    try:
        try:
            acc = A.system_access(db, user, system_id)
        except A.AccessRefused:
            return ""
        row = db.query(DesignSystem).filter(DesignSystem.id == acc.ref).first()
        return D.as_css(json.loads(row.tokens)) if row else ""
    finally:
        db.close()


__all__ = ["setup_design_routes"]
