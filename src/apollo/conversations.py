# SPDX-License-Identifier: AGPL-3.0-or-later
"""A new conversation with Apollo, and the earlier ones.

The owner's test on a fresh deploy (2026-11-24): Apollo was "another generic
Chat page that can't be cleared". Apollo's chat was one pinned session for
life, and the generic delete refuses a chat with messages in it, so there was
no way to start over.

A new conversation starts a fresh chat and keeps everything that isn't the
transcript: tasks, the notebook, what Apollo knows, Spaces, budgets and the
rhythm all key on the person (and the crew member), not on the chat. The old
chat is kept, renamed by its date and filed as an earlier conversation, so
nothing said is lost. Briefings and check-ins that spoke into the old chat now
speak into the new one.

A space has its own Apollo chat (`spaces.chat_for`); a new conversation there
does the same for that space's chat and nothing else.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from src.apollo import APOLLO_NAME
from src.apollo.errors import ApolloRefused

EARLIER_FOLDER = "Apollo · earlier"


def _crew(db, owner: str):
    from core.database import CrewMember
    crew = (db.query(CrewMember)
            .filter(CrewMember.owner == owner, CrewMember.is_default_assistant == True)  # noqa: E712
            .first())
    if crew is None or not crew.session_id:
        raise ApolloRefused("Your Apollo chat isn't set up yet. Open Apollo once first.", 409)
    return crew


def _messages_in(db, session_id: str) -> int:
    from core.database import ChatMessage
    return db.query(ChatMessage.id).filter(ChatMessage.session_id == session_id).count()


def _file_as_earlier(sess, crew_name: str, space_name: Optional[str]) -> None:
    when = sess.last_message_at or sess.updated_at or sess.created_at
    stamp = f"{when:%b} {when.day}, {when:%Y}" if when else "earlier"
    label = f"{crew_name} · {space_name}" if space_name else crew_name
    sess.name = f"{label}, {stamp}"
    sess.folder = EARLIER_FOLDER
    sess.is_important = False


def start_new(db, owner: str, space_id: Optional[str] = None) -> Dict[str, Any]:
    """Start a new Apollo conversation (in `space_id`'s chat when given).

    Returns `{"session_id", "earlier_id", "unchanged"}`. A chat with nothing in
    it is kept as it is (`unchanged`), so pressing the button twice doesn't
    leave an empty earlier conversation behind.
    """
    from core.database import ScheduledTask, Session as DbSession, utcnow_naive
    from src import agent_runs
    from src.apollo import spaces

    crew = _crew(db, owner)
    crew_name = crew.name or APOLLO_NAME
    row = spaces.get(db, owner, space_id) if space_id else None
    old_id = spaces.chat_for(db, owner, row.id if row is not None else None)
    old = db.query(DbSession).filter(DbSession.id == old_id, DbSession.owner == owner).first()
    if old is None:
        raise ApolloRefused("Your Apollo chat isn't set up yet. Open Apollo once first.", 409)
    if agent_runs.is_active(old_id):
        raise ApolloRefused("Apollo is still working in this chat. Stop it or let it finish, "
                            "then start a new one.", 409)
    if _messages_in(db, old_id) == 0:
        return {"session_id": old_id, "earlier_id": None, "unchanged": True}

    if row is not None:
        # The space's chat is made by `chat_for`, the same way as the first time.
        _file_as_earlier(old, crew_name, row.name)
        row.session_id = None
        db.flush()
        new_id = spaces.chat_for(db, owner, row.id)
    else:
        now = utcnow_naive()
        new_id = str(uuid.uuid4())
        db.add(DbSession(
            id=new_id, name=crew_name,
            endpoint_url=old.endpoint_url or "", model=old.model or "", owner=owner,
            is_important=True, mode=old.mode or "agent", folder=old.folder,
            headers=dict(old.headers or {}), approval_mode=old.approval_mode,
            crew_member_id=crew.id, created_at=now, updated_at=now))
        _file_as_earlier(old, crew_name, None)
        crew.session_id = new_id
        db.flush()

    # Briefings, check-ins and the rhythm speak into the chat that's open now.
    (db.query(ScheduledTask)
     .filter(ScheduledTask.owner == owner, ScheduledTask.crew_member_id == crew.id,
             ScheduledTask.session_id == old_id)
     .update({ScheduledTask.session_id: new_id}, synchronize_session=False))
    return {"session_id": new_id, "earlier_id": old_id, "unchanged": False}


def earlier(db, owner: str, limit: int = 30) -> List[Dict[str, Any]]:
    """The person's earlier Apollo conversations, newest first."""
    from core.database import Session as DbSession
    crew = _crew(db, owner)
    rows = (db.query(DbSession)
            .filter(DbSession.owner == owner, DbSession.crew_member_id == crew.id,
                    DbSession.folder == EARLIER_FOLDER)
            .order_by(DbSession.last_message_at.desc(), DbSession.updated_at.desc())
            .limit(max(1, min(int(limit or 30), 100))).all())
    def iso(d):
        return d.isoformat() + "Z" if d else None
    return [{"session_id": s.id, "name": s.name, "messages": int(s.message_count or 0),
             "last_message_at": iso(s.last_message_at)} for s in rows]
