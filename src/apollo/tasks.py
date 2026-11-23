# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's tasks: one goal or errand each, as its own record (settled call 3).

A task has a state the person can read at a glance and the server enforces:

  * `working`   — someone (Apollo or the lead agent) is on it;
  * `needs_you` — it is stuck on exactly one question only the person can answer;
  * `waiting`   — it waits on someone or something else;
  * `done`      — finished, with its outcome in a line.

`needs_you` always carries its question and nothing else does: a task can't be
stuck on nothing, and an answered question doesn't linger. Every function
takes the owner, and another person's task is "not found", never "forbidden",
so its existence isn't told either.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.apollo import budget as B
from src.apollo.errors import ApolloRefused

STATES = ("working", "needs_you", "waiting", "done")
STATE_WORDS = {"working": "Working", "needs_you": "Needs you", "waiting": "Waiting", "done": "Done"}
TITLE_MAX = 120
BRIEF_MAX = 8000
LINE_MAX = 600
KIND_MAX = 60
STARTERS = ("person", "apollo")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _line(value: Any, limit: int, what: str, *, required: bool = False) -> Optional[str]:
    words = " ".join(str(value or "").split())
    if not words:
        if required:
            raise ApolloRefused(f"{what} needs some words.")
        return None
    if len(words) > limit:
        raise ApolloRefused(f"{what} is {limit} characters at most.")
    return words


def _brief(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > BRIEF_MAX:
        raise ApolloRefused(f"A brief is {BRIEF_MAX} characters at most.")
    return text


def get(db, owner: str, task_id: Any):
    from core.database import ApolloTask
    task = db.query(ApolloTask).filter(ApolloTask.id == str(task_id or ""),
                                       ApolloTask.owner == owner).first()
    if task is None:
        raise ApolloRefused("That task isn't one of yours.", 404)
    return task


def create(db, owner: str, *, title: Any, brief: Any = None, kind: Any = None,
           parent_id: Any = None, lead_agent: Any = None, budget_tokens: Any = None,
           started_by: str = "person", pick=None):
    """A new task for `owner`. Its lead is the agent named, if it exists for
    this person, or else the roster's best fit (`lead.pick_lead`); with no fit
    the task still starts, led by Apollo, and says the roster has a gap."""
    from core.database import ApolloTask
    if not owner:
        raise ApolloRefused("Tasks belong to a signed-in person.", 403)
    if started_by not in STARTERS:
        raise ApolloRefused("A task is started by the person or by Apollo.")
    title = _line(title, TITLE_MAX, "A task's title", required=True)
    brief = _brief(brief)
    kind = _line(kind, KIND_MAX, "A kind of work")
    parent = get(db, owner, parent_id) if parent_id else None
    tokens = B.check_person_budget(budget_tokens)
    lead = None
    note = None
    if lead_agent:
        from src.agents.catalogue import get_agent
        manifest = get_agent(owner, str(lead_agent).strip())
        if manifest is None:
            raise ApolloRefused("There's no agent by that name in your roster.", 404)
        lead = manifest.id
    else:
        if pick is None:
            from src.apollo.lead import pick_lead as pick
        found = pick(owner, " ".join(x for x in (title, kind or "", brief or "") if x))
        if found:
            lead = found["id"]
        else:
            note = "No agent in the roster fits this yet, so Apollo leads it."
    task = ApolloTask(id=str(uuid.uuid4()), owner=owner, title=title, brief=brief, kind=kind,
                      parent_id=parent.id if parent else None, state="working",
                      lead_agent=lead, budget_tokens=tokens, spent_tokens=0,
                      started_by=started_by, next_step=note)
    db.add(task)
    db.flush()
    return task


def list_for(db, owner: str, *, state: Optional[str] = None, include_done: bool = True,
             parent_id: Optional[str] = None, limit: int = 50) -> List[Any]:
    from core.database import ApolloTask
    q = db.query(ApolloTask).filter(ApolloTask.owner == owner)
    if state:
        if state not in STATES:
            raise ApolloRefused("A task is working, needs you, waiting or done.")
        q = q.filter(ApolloTask.state == state)
    elif not include_done:
        q = q.filter(ApolloTask.state != "done")
    if parent_id:
        q = q.filter(ApolloTask.parent_id == parent_id)
    return q.order_by(ApolloTask.updated_at.desc()).limit(max(1, min(int(limit), 500))).all()


def set_state(task, state: str, *, question: Any = None, next_step: Any = ...,
              outcome: Any = ...):
    """Move `task` to `state`. `needs_you` takes the one question; any other
    state clears it. `done` keeps an outcome line."""
    if state not in STATES:
        raise ApolloRefused("A task is working, needs you, waiting or done.")
    if state == "needs_you":
        task.question = _line(question, LINE_MAX, "The question", required=True)
    else:
        task.question = None
    if next_step is not ...:
        task.next_step = _line(next_step, LINE_MAX, "A next step")
    if outcome is not ...:
        task.outcome = _line(outcome, LINE_MAX, "An outcome")
    task.state = state
    task.done_at = _now() if state == "done" else None
    task.updated_at = _now()
    return task


def update(db, owner: str, task_id: Any, fields: Dict[str, Any]):
    """The person's edits: title, brief, kind, lead, budget, next step, state."""
    task = get(db, owner, task_id)
    fields = fields if isinstance(fields, dict) else {}
    unknown = set(fields) - {"title", "brief", "kind", "lead_agent", "budget_tokens",
                             "next_step", "state", "question", "outcome"}
    if unknown:
        raise ApolloRefused(f"A task has no {sorted(unknown)[0]} to change.")
    if "title" in fields:
        task.title = _line(fields["title"], TITLE_MAX, "A task's title", required=True)
    if "brief" in fields:
        task.brief = _brief(fields["brief"])
    if "kind" in fields:
        task.kind = _line(fields["kind"], KIND_MAX, "A kind of work")
    if "lead_agent" in fields:
        if fields["lead_agent"]:
            from src.agents.catalogue import get_agent
            manifest = get_agent(owner, str(fields["lead_agent"]).strip())
            if manifest is None:
                raise ApolloRefused("There's no agent by that name in your roster.", 404)
            task.lead_agent = manifest.id
        else:
            task.lead_agent = None
    if "budget_tokens" in fields:
        task.budget_tokens = B.check_person_budget(fields["budget_tokens"])
    if "state" in fields:
        set_state(task, fields["state"], question=fields.get("question"),
                  next_step=fields.get("next_step", ...), outcome=fields.get("outcome", ...))
    else:
        if "next_step" in fields:
            task.next_step = _line(fields["next_step"], LINE_MAX, "A next step")
        if "outcome" in fields:
            task.outcome = _line(fields["outcome"], LINE_MAX, "An outcome")
    task.updated_at = _now()
    db.flush()
    return task


def answer(db, owner: str, task_id: Any, words: Any):
    """The person answers the task's question. It goes back to working, and the
    answer is kept as its next step until the lead picks it up."""
    task = get(db, owner, task_id)
    if task.state != "needs_you":
        raise ApolloRefused("That task isn't waiting on an answer from you.", 409)
    said = _line(words, LINE_MAX, "Your answer", required=True)
    asked = task.question
    set_state(task, "working", next_step=f"You answered “{asked}”: {said}")
    db.flush()
    return task


def status(db, owner: str) -> Dict[str, Any]:
    """What Apollo is doing now, for the pane header: Needs you, Working on N, Idle."""
    from sqlalchemy import func

    from core.database import ApolloTask
    counts = dict(db.query(ApolloTask.state, func.count(ApolloTask.id))
                  .filter(ApolloTask.owner == owner).group_by(ApolloTask.state).all())
    needs = int(counts.get("needs_you", 0))
    working = int(counts.get("working", 0))
    waiting = int(counts.get("waiting", 0))
    if needs:
        state, words = "needs_you", "Needs you" if needs == 1 else f"Needs you on {needs}"
    elif working:
        state, words = "working", f"Working on {working}"
    else:
        state, words = "idle", "Idle"
    return {"state": state, "words": words,
            "counts": {s: int(counts.get(s, 0)) for s in STATES}, "waiting": waiting}


def to_dict(task, *, budget_cap: Optional[int] = None) -> Dict[str, Any]:
    def iso(d):
        return d.isoformat() + "Z" if d else None
    return {
        "id": task.id, "title": task.title, "brief": task.brief, "kind": task.kind,
        "state": task.state, "state_words": STATE_WORDS.get(task.state, task.state),
        "next_step": task.next_step, "question": task.question, "outcome": task.outcome,
        "lead_agent": task.lead_agent, "parent_id": task.parent_id,
        "hire_id": task.hire_id, "session_id": task.session_id,
        "budget_tokens": task.budget_tokens, "spent_tokens": int(task.spent_tokens or 0),
        "budget_limit": B.limit_for(task, cap=budget_cap),
        "started_by": task.started_by,
        "created_at": iso(task.created_at), "updated_at": iso(task.updated_at),
        "done_at": iso(task.done_at),
    }
