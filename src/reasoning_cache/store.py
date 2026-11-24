# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reasoning cache entries, per person and per scope (`ReasoningCacheEntry`).

Every read names both the owner and the scope, so no query here can return one
person's entry to another or one space's entry to the next (Apollo's airgaps:
a space's scope is its own, and nothing is shared in or out). Lookup is a
cosine match over the person's entries in that scope, held in the row as
JSON: a person has tens of entries, not millions, so an index would cost more
than it saves.
"""
from __future__ import annotations

import json
import math
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.database import ReasoningCacheEntry, utcnow_naive

SHADOW, LIVE, RETIRED = "shadow", "live", "retired"
#: A disagreement resets the run of agreements; this many retire the entry.
DISAGREEMENTS_TO_RETIRE = 2


def scope_for(*, space_id: Optional[str] = None, task_id: Optional[str] = None,
              agent_id: Optional[str] = None, apollo: bool = False) -> str:
    """The one scope a run's entries live in: its Apollo space, else its hired
    or summoned agent, else its scheduled task, else the person's ordinary
    chats. Apollo's top layer is a scope of its own. The most specific wins, so an entry built in a space is never
    consulted outside it, and nothing from outside is consulted in it."""
    if space_id:
        return f"space:{space_id}"
    if apollo:
        return "apollo"
    if agent_id:
        return f"agent:{agent_id}"
    if task_id:
        return f"task:{task_id}"
    return "chat"


def _vec(text: str) -> List[float]:
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    return [float(x) for x in value] if isinstance(value, list) else []


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def as_dict(row: ReasoningCacheEntry) -> Dict[str, Any]:
    return {
        "id": row.id, "owner": row.owner, "scope": row.scope,
        "applies_when": row.applies_when, "request": row.request,
        "answer": row.answer,
        "parameters": json.loads(row.parameters or "[]"),
        "code": row.code, "root": row.root,
        "tools": json.loads(row.tools or "[]"),
        "status": row.status, "agreements": row.agreements,
        "disagreements": row.disagreements, "served": row.served,
        "tokens_saved": row.tokens_saved, "source_tokens": row.source_tokens,
        "builder_model": row.builder_model, "retired_why": row.retired_why,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


def add_entry(db, owner: str, scope: str, *, applies_when: str, request: str,
              answer: str, embedding: Sequence[float], parameters: List[Dict[str, Any]],
              code: str, root: str, tools: Sequence[str], source_tokens: int = 0,
              builder_model: Optional[str] = None) -> str:
    row = ReasoningCacheEntry(
        id=str(uuid.uuid4()), owner=owner, scope=scope,
        applies_when=applies_when[:2000], request=request[:20000], answer=answer[:20000],
        embedding=json.dumps([float(x) for x in embedding]),
        parameters=json.dumps(parameters), code=code, root=root,
        tools=json.dumps(sorted(set(tools))), status=SHADOW,
        source_tokens=int(source_tokens or 0), builder_model=builder_model)
    db.add(row)
    db.commit()
    return row.id


def _owned(db, owner: str, entry_id: str) -> Optional[ReasoningCacheEntry]:
    return (db.query(ReasoningCacheEntry)
            .filter(ReasoningCacheEntry.id == str(entry_id or ""),
                    ReasoningCacheEntry.owner == owner)
            .first())


def best_match(db, owner: str, scope: str, vector: Sequence[float],
               threshold: float) -> Optional[Tuple[Dict[str, Any], float]]:
    """The closest entry of this person's in this scope at or above
    `threshold`, with its score, or None. Retired entries are never matched."""
    rows = (db.query(ReasoningCacheEntry)
            .filter(ReasoningCacheEntry.owner == owner,
                    ReasoningCacheEntry.scope == scope,
                    ReasoningCacheEntry.status != RETIRED)
            .all())
    best: Optional[Tuple[ReasoningCacheEntry, float]] = None
    for row in rows:
        score = cosine(vector, _vec(row.embedding))
        if score >= threshold and (best is None or score > best[1]):
            best = (row, score)
    return (as_dict(best[0]), best[1]) if best else None


def record_shadow(db, owner: str, entry_id: str, agreed: bool,
                  agreements_to_go_live: int) -> Optional[str]:
    """One shadow comparison. Returns the entry's status after it."""
    row = _owned(db, owner, entry_id)
    if row is None or row.status == RETIRED:
        return None
    if agreed:
        row.agreements = int(row.agreements or 0) + 1
        if row.status == SHADOW and row.agreements >= max(1, int(agreements_to_go_live)):
            row.status = LIVE
    else:
        row.agreements = 0
        row.disagreements = int(row.disagreements or 0) + 1
        if row.status == LIVE:
            row.status = SHADOW
        if row.disagreements >= DISAGREEMENTS_TO_RETIRE:
            row.status = RETIRED
            row.retired_why = "Its answers disagreed with the model's."
    row.last_used_at = utcnow_naive()
    db.commit()
    return row.status


def record_served(db, owner: str, entry_id: str, tokens_saved: int) -> None:
    row = _owned(db, owner, entry_id)
    if row is None:
        return
    row.served = int(row.served or 0) + 1
    row.tokens_saved = int(row.tokens_saved or 0) + max(0, int(tokens_saved or 0))
    row.last_used_at = utcnow_naive()
    db.commit()


def retire(db, owner: str, entry_id: str, why: str) -> bool:
    row = _owned(db, owner, entry_id)
    if row is None:
        return False
    row.status = RETIRED
    row.retired_why = why[:500]
    db.commit()
    return True

