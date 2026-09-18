# SPDX-License-Identifier: AGPL-3.0-or-later
# routes/compare_routes.py
"""Model A/B comparison routes."""
import json
import uuid
import random
from datetime import datetime
from fastapi import APIRouter, Form, HTTPException, Request
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
import logging

from core.database import Comparison, SessionLocal
from core.session_manager import SessionManager
from src.auth_helpers import get_current_user
from routes.session_routes import _reject_raw_endpoint_url_for_non_admin
from src.env_flags import request_flag

logger = logging.getLogger(__name__)



def _owned_endpoint_by_url(db, base_url, owner):
    """ModelEndpoint whose base_url == `base_url` and is VISIBLE to `owner`
    (their own rows + legacy null-owner "shared" rows); None otherwise.

    Owner-scoped on purpose. ModelEndpoint is per-user (core/database.py: non-null
    owner = private, "the model picker only shows the endpoint to that user") and
    holds a decrypted `api_key`. start_comparison copies the matched row's api_key
    into the caller-owned [CMP] session's headers, which then drives that session's
    /api/chat_stream calls — so an UNSCOPED base_url match would let a user mint a
    comparison bound to ANOTHER user's private endpoint and spend that owner's
    api_key / reach whatever base_url they configured. Mirrors
    session_routes._owned_endpoint. A null/empty owner is a no-op (single-user /
    legacy mode).
    """
    from core.database import ModelEndpoint
    from src.auth_helpers import owner_filter
    q = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == base_url)
    return owner_filter(q, ModelEndpoint, owner).first()


def _owned_endpoint_by_id(db, endpoint_id, owner):
    """ModelEndpoint whose id == `endpoint_id` and is VISIBLE to `owner` (their
    own rows + legacy null-owner "shared" rows); None otherwise.

    Preferred over _owned_endpoint_by_url for credential resolution: two visible
    endpoints can share the same base_url but hold DIFFERENT api_keys (e.g. two
    accounts on the same provider). A base_url-only match returns whichever row
    sorts first, so it can copy the WRONG owner-scoped key into the [CMP] session.
    An id pins the exact registered endpoint, so /api/compare/start prefers it and
    only falls back to URL matching for legacy / admin raw-URL callers. Owner
    scoping is identical to _owned_endpoint_by_url (a null/empty owner is a no-op).
    """
    from core.database import ModelEndpoint
    from src.auth_helpers import owner_filter
    q = db.query(ModelEndpoint).filter(ModelEndpoint.id == endpoint_id)
    return owner_filter(q, ModelEndpoint, owner).first()


class RecordVoteRequest(BaseModel):
    prompt: str
    models: List[str]
    winner: str           # model name or "tie"
    is_blind: bool = True
    # `H12`. Both optional, both things only the voting browser knows: the
    # per-model cost estimate it computed from the token counts it saw, and
    # which compare mode produced the vote. Without them the server record
    # cannot reconstruct the Scoreboard and the browser copy stays the only
    # complete one — which is the whole defect.
    costs: Optional[List[Optional[float]]] = None
    mode: Optional[str] = None


def _vote_meta(body) -> Dict[str, Any]:
    """What a vote stores beyond the two model columns. `H12`.

    A function rather than five lines inline because `_history_row` reads what
    this writes, and a pair like that is only trustworthy if the round trip can
    be tested. A mutation restoring the old `if len(models) > 2` condition —
    which silently dropped costs and mode for every two-model vote — survived a
    test file that exercised only the reader.

    Written unconditionally, which also removes the N==2 special case that made
    a two-model vote read back in a different shape from a three-model one.
    """
    meta: Dict[str, Any] = {"models": list(body.models)}
    if body.costs is not None:
        meta["costs"] = body.costs
    if body.mode:
        meta["mode"] = body.mode
    return meta


# What a comparison with no recorded mapping means: left is A, right is B.
# `POST /api/compare/start` is the only writer of a real one, and it always
# writes one, so this is the shape for every row that path did not create.
_IDENTITY_MAPPING = {"left": "a", "right": "b"}


def _blind_mapping(c) -> Dict[str, str]:
    """Which side is which, for one comparison. `P13-12`.

    Always returns both keys. `vote_comparison` indexes `mapping["left"]` and
    `mapping["right"]` unconditionally — including in the reveal block, which
    runs even for a tie — so anything that can hand it a dict without them is a
    500 rather than a bad request. Before this row that was reachable: a vote
    recorded through `POST /api/compare/record` stored `{"models": [...]}` in
    this column, and a `winner` of `""` slips past the "Already voted" guard
    that otherwise hides the shape mismatch.

    The payload has moved to `vote_meta` and the migration moved the existing
    rows, so the wrong shape should no longer exist. This still refuses to
    index a blob it has not checked: a store can be older than its migration,
    and the last thing `/vote` should do with a row it does not recognise is
    crash on it.
    """
    if not getattr(c, "blind_mapping", None):
        return dict(_IDENTITY_MAPPING)
    try:
        blob = json.loads(c.blind_mapping)
    except (ValueError, TypeError):
        return dict(_IDENTITY_MAPPING)
    if not isinstance(blob, dict):
        return dict(_IDENTITY_MAPPING)
    left, right = blob.get("left"), blob.get("right")
    if left not in ("a", "b") or right not in ("a", "b"):
        logger.warning(
            "Comparison %s has a blind_mapping that is not a left/right mapping; "
            "reading it as the identity mapping", getattr(c, "id", "?"))
        return dict(_IDENTITY_MAPPING)
    return {"left": left, "right": right}


def _history_row(c) -> Dict[str, Any]:
    """One comparison as the Scoreboard needs it. `H12`.

    `model_a`/`model_b`/`prompt` keep the exact shape and truncation they had,
    because this endpoint is public API and something may already read it.
    What is added is `models`, `costs` and `mode`, decoded from the JSON the
    vote endpoint writes — without which a browser cannot rebuild a vote it did
    not cast, and the Scoreboard has to keep reading its own local copy.

    A row whose blob is missing or unreadable still returns a usable `models`
    from the two columns. That matters: every vote recorded before this change
    has either no blob at all (N==2) or one carrying models only, and they must
    not vanish from a history that is about to become the source of truth.

    `P13-12`. **It reads one column now, and it no longer guesses.** It used to
    read `blind_mapping`, which by then meant three different things depending
    on which endpoint had written the row, and told them apart by which keys
    were present. The guess was correct; the column having two meanings was the
    defect, and `POST /api/compare/{id}/vote` is where it cost something — that
    handler indexes `mapping["left"]` and raised `KeyError` on any row this
    path had written. The payload moved to `vote_meta`, and
    `_migrate_add_comparison_vote_meta_column` moved the existing rows with it,
    so a history recorded before the migration reads back exactly as before.
    """
    models: List[str] = []
    costs = None
    mode = None
    meta = getattr(c, "vote_meta", None)
    if meta:
        try:
            blob = json.loads(meta)
            if isinstance(blob, dict):
                if isinstance(blob.get("models"), list):
                    models = [str(m) for m in blob["models"]]
                if isinstance(blob.get("costs"), list):
                    costs = blob["costs"]
                if isinstance(blob.get("mode"), str):
                    mode = blob["mode"]
        except (ValueError, TypeError):
            pass
    if not models:
        models = [m for m in (c.model_a, c.model_b) if m]
    return {
        "id": c.id,
        "prompt": c.prompt[:100],
        "model_a": c.model_a,
        "model_b": c.model_b,
        "models": models,
        "costs": costs,
        "mode": mode,
        "winner": c.winner,
        "is_blind": c.is_blind,
        "voted_at": c.voted_at.isoformat() if c.voted_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def setup_compare_routes(session_manager: SessionManager):
    """Setup comparison routes."""
    # B53. This `APIRouter` used to be a module global, decorated by this
    # function and returned. Calling the function twice therefore registered
    # every route twice on one router, and FastAPI dispatches to the first
    # match — so the second call's handlers, and the manager they close over,
    # were silently ignored while the call appeared to succeed. Production
    # calls it once, so nothing was broken; two test files that each build a
    # router were not, and the suite's green depended on which ran first.
    router = APIRouter(prefix="/api/compare", tags=["compare"])


    @router.post("/start")
    def start_comparison(
        request: Request,
        prompt: str = Form(...),
        model_a: str = Form(...),
        model_b: str = Form(...),
        endpoint_a: str = Form(""),
        endpoint_b: str = Form(""),
        endpoint_a_id: str = Form(""),
        endpoint_b_id: str = Form(""),
        is_blind: str = Form("true"),
    ):
        """Create two ephemeral sessions and a comparison record.

        Returns the comparison ID and the two session IDs so the client
        can fire two independent SSE streams to /api/chat_stream.
        """
        user = getattr(request.state, 'current_user', None)
        comp_id = str(uuid.uuid4())
        sid_a = str(uuid.uuid4())
        sid_b = str(uuid.uuid4())

        # Blind mapping: randomly assign left/right
        blind = request_flag(is_blind)  # `B97`
        if blind:
            mapping = {"left": "a", "right": "b"}
            if random.random() > 0.5:
                mapping = {"left": "b", "right": "a"}
        else:
            mapping = {"left": "a", "right": "b"}

        # Map session IDs to left/right based on blind mapping
        session_left = sid_a if mapping["left"] == "a" else sid_b
        session_right = sid_a if mapping["right"] == "a" else sid_b

        # In blind mode, name the helper sessions by their neutral slot
        # ("Model A" / "Model B") instead of the real model. Otherwise the
        # session name leaks the model in the sidebar and GET /api/sessions,
        # de-anonymizing the comparison before the user votes (issue #1285).
        slot_name = {session_left: "Model A", session_right: "Model B"}

        # SECURITY: resolve and validate BOTH endpoints before creating any
        # session. Compare copies a registered endpoint's Authorization header
        # into the [CMP] session, so validating one endpoint while creating its
        # session, then rejecting the other, would leave a partial compare
        # session behind with that header attached. Doing all the owner-scope
        # resolution + raw-URL rejection up front means a 403 on either endpoint
        # aborts the whole request with nothing created and no header copied.
        from src.endpoint_resolver import build_chat_url, build_headers, normalize_base
        resolved = []
        db = SessionLocal()
        try:
            for sid, model, endpoint, endpoint_id in [
                (sid_a, model_a, endpoint_a, endpoint_a_id),
                (sid_b, model_b, endpoint_b, endpoint_b_id),
            ]:
                # Prefer an explicit endpoint id: it pins the EXACT registered
                # endpoint (and its api_key), even when two endpoints visible to
                # the caller share a base_url with different keys — a URL-only
                # match would copy whichever row sorts first, i.e. possibly the
                # wrong key. Fall back to URL resolution only for legacy / admin
                # raw-URL callers that don't send an id.
                eid = endpoint_id.strip() if isinstance(endpoint_id, str) else ""
                if eid:
                    ep = _owned_endpoint_by_id(db, eid, user)
                    if ep is None:
                        # An id the caller can't see (wrong owner / deleted) must
                        # NOT silently fall back to a same-URL row with a different
                        # key — that's exactly the mix-up ids exist to prevent.
                        raise HTTPException(404, "Model endpoint not found")
                    # The id already resolved the endpoint; ignore any raw URL the
                    # caller also sent and dial the stored config instead.
                    endpoint = ep.base_url
                elif not endpoint:
                    raise HTTPException(
                        422, "endpoint_a/endpoint_b or endpoint_a_id/endpoint_b_id is required"
                    )
                else:
                    # Resolve the supplied URL to a ModelEndpoint the caller owns
                    # (their own rows + legacy null-owner shared rows), scoped so a
                    # comparison can't borrow another user's private endpoint key.
                    base = normalize_base(endpoint)
                    ep = _owned_endpoint_by_url(db, base, user)
                # Reject *unregistered* raw URLs for signed-in non-admins; a
                # matched registered endpoint supplies an id so the caller can
                # still compare endpoints they own. Blanket-rejecting here (the
                # earlier `endpoint_id=None` call) locked non-admins out of
                # compare entirely, since compare resolves endpoints by URL with
                # no endpoint_id. Mirrors the gallery inpaint/harmonize checks.
                # Raised here (phase 1), before any session exists.
                _reject_raw_endpoint_url_for_non_admin(
                    request, user, str(ep.id) if ep is not None else None, endpoint
                )
                # Bind the [CMP] session to the RESOLVED endpoint, not the raw
                # caller-supplied string. When the URL matches a registered
                # endpoint visible to the caller, use that row's own normalized
                # base URL (the same value owner scoping + endpoint validation
                # already vetted) so the session dials exactly where the stored
                # config points. The raw `endpoint` only survives for callers
                # allowed to pass one — admins / single-user mode, where
                # `_reject_raw_endpoint_url_for_non_admin` is a no-op and `ep`
                # is None. Mirrors the registered-endpoint path in session_routes.
                session_endpoint_url = (
                    build_chat_url(normalize_base(ep.base_url)) if ep is not None else endpoint
                )
                # Headers come only from a matched endpoint's key; None when
                # `ep` is None (raw admin URL or no match), so a comparison can
                # never inherit another user's key/headers.
                headers = build_headers(ep.api_key, ep.base_url) if (ep and ep.api_key) else None
                resolved.append((sid, model, session_endpoint_url, headers))
        finally:
            db.close()

        # Both endpoints validated — only now create the ephemeral [CMP]
        # sessions and copy any resolved headers.
        for sid, model, session_endpoint_url, headers in resolved:
            name = f"[CMP] {slot_name[sid]}" if blind else f"[CMP] {model.split('/')[-1]}"
            session_manager.create_session(
                session_id=sid,
                name=name,
                endpoint_url=session_endpoint_url,
                model=model,
                rag=False,
                owner=user,
            )
            if headers:
                s = session_manager.sessions.get(sid)
                if s:
                    s.headers = headers

        # Store comparison record
        db = SessionLocal()
        try:
            comp = Comparison(
                id=comp_id,
                prompt=prompt,
                model_a=model_a,
                model_b=model_b,
                # Record the URL the session actually dials. For URL callers this
                # is their raw input; for id-only callers (empty endpoint_a/_b)
                # fall back to the resolved endpoint URL so the column stays
                # meaningful and non-null. resolved is in [a, b] order.
                endpoint_a=endpoint_a or resolved[0][2],
                endpoint_b=endpoint_b or resolved[1][2],
                is_blind=blind,
                blind_mapping=json.dumps(mapping),
                owner=user,
            )
            db.add(comp)
            db.commit()
        finally:
            db.close()

        # In blind mode, withhold the model identities AND the left/right
        # mapping from the response. The client already knows model_a/model_b
        # (it sent them), so returning either would defeat blind mode. They are
        # revealed by POST /api/compare/{id}/vote once the user has voted (#1285).
        return {
            "id": comp_id,
            "session_left": session_left,
            "session_right": session_right,
            "model_left": None if blind else (model_a if mapping["left"] == "a" else model_b),
            "model_right": None if blind else (model_a if mapping["right"] == "a" else model_b),
            "is_blind": blind,
            "mapping": None if blind else mapping,
        }

    @router.post("/{comp_id}/vote")
    def vote_comparison(
        request: Request,
        comp_id: str,
        winner: str = Form(...),  # "left", "right", or "tie"
    ):
        """Record the user's vote and reveal model names if blind."""
        user = get_current_user(request)
        db = SessionLocal()
        try:
            comp = db.query(Comparison).filter(Comparison.id == comp_id).first()
            if not comp:
                raise HTTPException(404, "Comparison not found")
            # SECURITY: strict ownership — null-owner Comparisons were
            # accessible to every user.
            if user and comp.owner != user:
                raise HTTPException(404, "Comparison not found")
            if comp.winner:
                raise HTTPException(400, "Already voted")

            mapping = _blind_mapping(comp)

            if winner == "tie":
                comp.winner = "tie"
            elif winner == "left":
                comp.winner = mapping["left"]
            elif winner == "right":
                comp.winner = mapping["right"]
            else:
                raise HTTPException(400, "winner must be 'left', 'right', or 'tie'")

            comp.voted_at = datetime.utcnow()
            db.commit()

            return {
                "winner": comp.winner,
                "model_a": comp.model_a,
                "model_b": comp.model_b,
                "revealed": {
                    "left": comp.model_a if mapping["left"] == "a" else comp.model_b,
                    "right": comp.model_a if mapping["right"] == "a" else comp.model_b,
                },
            }
        finally:
            db.close()

    @router.post("/record")
    def record_comparison(request: Request, body: RecordVoteRequest):
        """Lightweight endpoint to record a comparison vote from the frontend."""
        user = get_current_user(request)
        comp_id = str(uuid.uuid4())

        model_a = body.models[0] if len(body.models) > 0 else ""
        model_b = body.models[1] if len(body.models) > 1 else ""

        # `H12`. The full model list (which is why `model_a`/`model_b` were
        # never enough), plus the two fields the browser is the only holder of,
        # so `/history` can rebuild a vote without the browser that cast it.
        # Written unconditionally, which removes the N==2 special case that made
        # a two-model vote read back in a different shape from a three-model one.
        #
        # `P13-12`. This went into `blind_mapping` until now, because
        # `model_a`/`model_b` cannot hold three models and there was nowhere
        # else without a migration. There is a column for it now, and this path
        # leaves `blind_mapping` NULL: a vote recorded here was never blind in
        # the left/right sense — nothing was hidden behind a side — so there is
        # no mapping to record, and writing one would be inventing a fact to
        # fill a field.
        vote_meta = json.dumps(_vote_meta(body))

        db = SessionLocal()
        try:
            comp = Comparison(
                id=comp_id,
                prompt=body.prompt[:500],
                model_a=model_a,
                model_b=model_b,
                endpoint_a="",
                endpoint_b="",
                winner=body.winner,
                is_blind=body.is_blind,
                vote_meta=vote_meta,
                voted_at=datetime.utcnow(),
                owner=user,
            )
            db.add(comp)
            db.commit()
        finally:
            db.close()

        return {"status": "ok", "id": comp_id}

    @router.get("/history")
    def list_comparisons(request: Request):
        """List past comparisons."""
        user = get_current_user(request)
        db = SessionLocal()
        try:
            q = db.query(Comparison)
            if user:
                q = q.filter(Comparison.owner == user)
            comps = q.order_by(Comparison.created_at.desc()).limit(50).all()
            return [_history_row(c) for c in comps]
        finally:
            db.close()

    @router.delete("/{comp_id}")
    def delete_comparison(request: Request, comp_id: str):
        """Delete a comparison and its ephemeral sessions."""
        user = get_current_user(request)
        db = SessionLocal()
        try:
            comp = db.query(Comparison).filter(Comparison.id == comp_id).first()
            if not comp:
                raise HTTPException(404, "Comparison not found")
            # SECURITY: strict ownership — null-owner Comparisons were
            # accessible to every user.
            if user and comp.owner != user:
                raise HTTPException(404, "Comparison not found")
            db.delete(comp)
            db.commit()
            return {"status": "deleted"}
        finally:
            db.close()

    return router
