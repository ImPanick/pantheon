# SPDX-License-Identifier: AGPL-3.0-or-later
"""A task's own chat, and Apollo's one line about it.

The outline's fourth layer ("Task chat"): *Chat with this agent* opens a second
chat bound to the task's lead, so the person talks to the agent doing the work
and not to Apollo about it. That chat is the chat the lead's runs write into
(the hire's `ScheduledTask.session_id`), so it outlives a run and reopening the
task reopens it.

Two rules from the outline live here:

  * what the person types there goes to that lead only, and Apollo's chat gets
    one line about it (`said_line`), so the main chat never fills with task
    chatter;
  * only the owner reaches it: a task's chat is found from the owner's own
    task, and a chat that belongs to someone else is refused even if a task
    row points at it.

`post_line` is the one way a line lands in a person's Apollo chat, shared by
the scheduler (a run landed) and the routes (the person spoke in a task chat).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.apollo import tasks as T
from src.apollo.errors import ApolloRefused

logger = logging.getLogger(__name__)

NO_CHAT_YET = ("This task's chat opens once its lead has started on it. "
               "Start the task, and the chat is here when the first run begins.")
SAID_MAX = 160


def _hire_session(db, hire_id: Optional[str]) -> Optional[str]:
    """The chat the lead's runs write into, before a run has landed."""
    if not hire_id:
        return None
    from core.database import ScheduledTask
    from src.agents import hires as H
    for tid in H.task_ids_of(db, hire_id) or []:
        row = db.query(ScheduledTask).filter(ScheduledTask.id == tid).first()
        if row is not None and row.session_id:
            return row.session_id
    return None


def _owned(db, owner: str, session_id: str) -> bool:
    from core.database import Session as DbSession
    row = db.query(DbSession).filter(DbSession.id == session_id).first()
    return row is not None and row.owner == owner


def lead_name(owner: str, lead_agent: Optional[str]) -> str:
    if not lead_agent:
        return "the lead"
    try:
        from src.agents.catalogue import get_agent
        manifest = get_agent(owner, lead_agent)
    except Exception:
        manifest = None
    return getattr(manifest, "name", None) or lead_agent


def task_chat(db, owner: str, task_id: Any) -> Dict[str, Any]:
    """The task's chat for its owner: `{task_id, session_id, title, lead,
    lead_agent, state}`.
    Refused in a sentence when the lead hasn't started, or when the chat it
    points at isn't the owner's."""
    task = T.get(db, owner, task_id)
    sid = task.session_id or _hire_session(db, task.hire_id)
    if not sid:
        raise ApolloRefused(NO_CHAT_YET, 409)
    if not _owned(db, owner, sid):
        logger.warning("Apollo task %s points at a chat its owner doesn't own", task.id)
        raise ApolloRefused("That task's chat isn't yours, so it stays closed.", 403)
    if task.session_id != sid:
        task.session_id = sid
        db.flush()
    return {"task_id": task.id, "session_id": sid, "title": task.title,
            "lead": lead_name(owner, task.lead_agent), "lead_agent": task.lead_agent,
            "state": task.state}


def said_line(task, words: Any, *, lead: str = "the lead") -> str:
    """Apollo's one line about what the person told a task's lead."""
    text = " ".join(str(words or "").split())
    if not text:
        raise ApolloRefused("Say something to the lead first.")
    if len(text) > SAID_MAX:
        text = text[: SAID_MAX - 1].rstrip() + "…"
    return f"You told {lead} on “{task.title}”: {text}"


def apollo_session_id(db, owner: str) -> Optional[str]:
    from core.database import CrewMember
    crew = (db.query(CrewMember)
            .filter(CrewMember.owner == owner,
                    CrewMember.is_default_assistant == True)  # noqa: E712
            .first())
    return getattr(crew, "session_id", None)


def post_line(session_manager: Any, owner: str, line: str, meta: Optional[Dict[str, Any]] = None) -> bool:
    """One line from Apollo into `owner`'s Apollo chat. `False`, and silent,
    when they have no Apollo chat yet — the task's own record still says it."""
    if session_manager is None or not owner or not line:
        return False
    from core.database import SessionLocal
    from core.models import ChatMessage as MemChatMessage
    db = SessionLocal()
    try:
        session_id = apollo_session_id(db, owner)
    finally:
        db.close()
    if not session_id:
        return False
    session_manager.add_message(
        session_id, MemChatMessage("assistant", line, metadata=dict(meta or {})))
    return True


def waiting_approvals(db, owner: str, space: Any = "all") -> list:
    """The approvals the owner's Apollo leads are waiting on right now, one per
    parked run: `{task_id, title, run_task_id, run_id, approval_id, tool,
    question, why}`. Answered through the run's own door (`POST /api/tasks/{id}/
    runs/{run_id}/answer`), so the store's seal, single use and owner binding
    are the ones every other answer goes through."""
    from core.database import ApolloTask
    from src.agents import hires as H
    from src.task_scheduler import plain_waiting_list

    from src.apollo import tasks as Tk
    by_run_task: Dict[str, Any] = {}
    rows = (Tk._in_spaces(db.query(ApolloTask), db, owner, space)
            .filter(ApolloTask.owner == owner, ApolloTask.hire_id.isnot(None),
                    ApolloTask.state != "done")
            .all())
    for t in rows:
        for tid in H.task_ids_of(db, t.hire_id) or []:
            by_run_task[tid] = t
    if not by_run_task:
        return []
    out = []
    for w in plain_waiting_list(db, owner):
        task = by_run_task.get(w.get("task_id"))
        card = w.get("approval") or None
        if task is None or not card or not card.get("approval_id"):
            continue
        tool = w.get("tool_label") or "an action"
        out.append({"task_id": task.id, "title": task.title, "run_task_id": w["task_id"],
                    "run_id": w["run_id"], "approval_id": card["approval_id"], "tool": tool,
                    "question": f"{task.title}: allow {tool}?",
                    "why": str(card.get("description") or "")})
    return out
