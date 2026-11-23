# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's notebook: its working state (settled call 7).

Three kinds of line, each owner-scoped:

  * `open_loop`      — something owed or promised, open until settled or dropped;
  * `talked_through` — a thing the person already discussed, so a briefing
                       never brings it back as news;
  * `working`        — a note Apollo keeps for itself.

Facts and rules about the person are not here; they are in Brain (`knows`).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from src.apollo.errors import ApolloRefused

KINDS = ("open_loop", "talked_through", "working")
STATES = ("open", "settled", "dropped")
TEXT_MAX = 600


def add(db, owner: str, text: Any, *, kind: str = "working", task_id: Optional[str] = None):
    from core.database import ApolloNote
    words = " ".join(str(text or "").split())
    if not words:
        raise ApolloRefused("A note needs some words.")
    if len(words) > TEXT_MAX:
        raise ApolloRefused(f"A note is a line, {TEXT_MAX} characters at most.")
    if kind not in KINDS:
        raise ApolloRefused("A note is an open loop, a thing talked through, or a working note.")
    note = ApolloNote(id=str(uuid.uuid4()), owner=owner, kind=kind, text=words,
                      state="open", task_id=task_id)
    db.add(note)
    db.flush()
    return note


def get(db, owner: str, note_id: str):
    from core.database import ApolloNote
    note = db.query(ApolloNote).filter(ApolloNote.id == str(note_id or ""),
                                       ApolloNote.owner == owner).first()
    if note is None:
        raise ApolloRefused("That note isn't in your notebook.", 404)
    return note


def set_state(db, owner: str, note_id: str, state: str):
    if state not in STATES:
        raise ApolloRefused("A note is open, settled or dropped.")
    note = get(db, owner, note_id)
    note.state = state
    db.flush()
    return note


def list_for(db, owner: str, *, kind: Optional[str] = None, state: Optional[str] = None,
             limit: int = 60) -> List[Any]:
    from core.database import ApolloNote
    q = db.query(ApolloNote).filter(ApolloNote.owner == owner)
    if kind:
        q = q.filter(ApolloNote.kind == kind)
    if state:
        q = q.filter(ApolloNote.state == state)
    return q.order_by(ApolloNote.updated_at.desc()).limit(max(1, min(int(limit), 500))).all()


def to_dict(note) -> Dict[str, Any]:
    return {"id": note.id, "kind": note.kind, "text": note.text, "state": note.state,
            "task_id": note.task_id,
            "updated_at": note.updated_at.isoformat() + "Z" if note.updated_at else None}
