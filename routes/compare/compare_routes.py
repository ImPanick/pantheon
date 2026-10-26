# SPDX-License-Identifier: AGPL-3.0-or-later
# routes/compare_routes.py
"""Model A/B comparison routes."""
import json
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
import logging

from core.database import Comparison, SessionLocal
from core.session_manager import SessionManager
from src.auth_helpers import get_current_user

logger = logging.getLogger(__name__)



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
    # `B1191` (`D-2026-10-26-01` §5): refused, in the door's words, to a person this
    # Tools entry is switched off for (`src/tool_privileges.py`).
    from fastapi import Depends as _Depends
    from src.tool_privileges import everyone_switch as _everyone_switch, tool_privilege as _tool_privilege
    router = APIRouter(prefix="/api/compare", tags=["compare"],
                       # `B1488`: the switch for everyone first (it refuses everyone, in
                       # the door's *everyone* words), then the person's.
                       dependencies=[_Depends(_everyone_switch("can_use_compare")),
                                     _Depends(_tool_privilege("can_use_compare"))])


    # (`B1453`: `POST /start` and `POST /{comp_id}/vote` were here — a
    # server-side blind comparison: two sessions minted here, a vote that
    # revealed which side was which. The Compare window runs its panes from the
    # browser over ordinary sessions and records the result through `/record`,
    # so neither had a caller; the agent's `app_api` list named `/start`, which
    # it could not use, since it cannot stream two replies. Rows they wrote
    # still read back through `/history`.)

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
