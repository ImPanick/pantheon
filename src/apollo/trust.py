# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trust that widens one kind of task at a time: "just do it", earned by
record and granted by the person.

The outline (*Personality, adaptation and brand*): "It starts by drafting
everything. Approvals and rejections per kind of work (mail replies,
calendar moves, cert renewals) build a record, and 'just do it' is earned per
kind, never globally ... The admin's autonomy ceiling still caps it." Settled
call 2 is B: "After a run of approvals with no edits, Apollo offers the step
up and the person confirms."

- **The record** is per person, kind of work (the Apollo task's `kind`) and
  action (the approval card's tool). Each Allow the person gives a lead's
  card adds one to a clean run; a Deny ends the run.
- **The offer.** After `OFFER_AFTER` clean Allows in a row, the row is
  offered: the pane's Needs you shows it, and the next check-in says so once.
  "Not now" keeps it quiet for a month.
- **The grant** needs the person's yes, and the admin's ceiling: only someone
  who holds `can_auto_approve` (the privilege Auto mode is held to,
  `approval_mode.may_use_auto`) can say yes, and it is asked again at every
  run, so an admin taking it away takes "just do it" away at the next card.
- **Just doing it** is answering the card through the run's own door
  (`TaskScheduler.answer_question`): the same seal, single use and owner
  binding, the action allowed once, and the run log saying Apollo allowed it
  and why. Only the action the record was earned on, for that kind; another
  action of the same kind still asks.
- **Taking it back** is one tap; the record starts again from nothing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.apollo.errors import ApolloRefused

OFFER_AFTER = 5
QUIET_AFTER_NO = timedelta(days=30)
STATES = ("drafting", "offered", "granted")
NO_CEILING = ("Your admin hasn't let Apollo act without asking, so it keeps asking. "
              "That's the autonomy ceiling, which only an admin can raise.")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def kind_key(kind: Any) -> str:
    return " ".join(str(kind or "").lower().split())


def apollo_task_of(db, owner: str, scheduled_task_id: Optional[str]):
    """The Apollo task whose lead ran `scheduled_task_id`, or None."""
    if not scheduled_task_id:
        return None
    from core.database import ApolloTask
    from src.agents import hires as H
    hire = H.hire_for_task(db, scheduled_task_id)
    if hire is None:
        return None
    return (db.query(ApolloTask).filter(ApolloTask.owner == owner, ApolloTask.hire_id == hire.id)
            .order_by(ApolloTask.updated_at.desc()).first())


def _row(db, owner: str, kind: str, tool: str, *, make: bool = True):
    from core.database import ApolloTrust
    r = (db.query(ApolloTrust).filter(ApolloTrust.owner == owner, ApolloTrust.kind == kind,
                                      ApolloTrust.tool == tool).first())
    if r is None and make:
        r = ApolloTrust(id=str(uuid.uuid4()), owner=owner, kind=kind, tool=tool, state="drafting",
                        streak=0, allowed=0, denied=0)
        db.add(r)
        db.flush()
    return r


def record(db, owner: str, scheduled_task_id: Optional[str], decision: str, tool: Any) -> Optional[Dict[str, Any]]:
    """The person answered a lead's card. Returns the offer when this answer
    earned one; None otherwise (and for any card that isn't an Apollo lead's,
    or whose task has no kind)."""
    task = apollo_task_of(db, owner, scheduled_task_id)
    kind = kind_key(getattr(task, "kind", None))
    tool = str(tool or "").strip()
    if task is None or not kind or not tool:
        return None
    r = _row(db, owner, kind, tool)
    r.space_id = task.space_id
    r.updated_at = _now()
    if decision == "deny":
        r.denied = (r.denied or 0) + 1
        r.streak = 0
        if r.state == "offered":
            r.state = "drafting"
        db.flush()
        return None
    r.allowed = (r.allowed or 0) + 1
    r.streak = (r.streak or 0) + 1
    quiet = r.declined_at is not None and _now() - r.declined_at < QUIET_AFTER_NO
    if r.state == "drafting" and r.streak >= OFFER_AFTER and not quiet:
        r.state = "offered"
        r.offered_at = _now()
        db.flush()
        return to_dict(r)
    db.flush()
    return None


def offer_line(r) -> str:
    return (f"You've allowed {r.tool} for {r.kind} {r.streak} times in a row without a change. "
            f"Should Apollo just do it for {r.kind} from now on?")


def to_dict(r, names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    out = {"id": r.id, "kind": r.kind, "tool": r.tool, "state": r.state, "streak": int(r.streak or 0),
           "allowed": int(r.allowed or 0), "denied": int(r.denied or 0),
           "space_id": r.space_id}
    if r.state == "offered":
        out["words"] = offer_line(r)
    elif r.state == "granted":
        out["words"] = f"Apollo just does {r.tool} for {r.kind}."
    else:
        left = max(0, OFFER_AFTER - int(r.streak or 0))
        out["words"] = (f"Apollo asks before {r.tool} for {r.kind}. "
                        f"{left} more clean {'yes' if left == 1 else 'yeses'} and it'll offer to just do it.")
    if names is not None and r.space_id in names:
        out["space"] = names[r.space_id]
    return out


def _visible(db, owner: str, rows, space: Any):
    from src.apollo import spaces as S
    if space == S.ALL:
        sealed = set(S.sealed_ids(db, owner))
        return [r for r in rows if r.space_id not in sealed]
    return [r for r in rows if (r.space_id or None) == space]


def list_for(db, owner: str, *, space: Any = "all", state: Optional[str] = None) -> List[Dict[str, Any]]:
    from core.database import ApolloTrust
    from src.apollo import spaces as S
    q = db.query(ApolloTrust).filter(ApolloTrust.owner == owner)
    if state:
        q = q.filter(ApolloTrust.state == state)
    names = {k: v.name for k, v in S._all(db, owner).items()}
    rows = _visible(db, owner, q.order_by(ApolloTrust.kind, ApolloTrust.tool).all(), space)
    return [to_dict(r, names) for r in rows]


def _get(db, owner: str, trust_id: Any):
    from core.database import ApolloTrust
    r = db.query(ApolloTrust).filter(ApolloTrust.id == str(trust_id or ""), ApolloTrust.owner == owner).first()
    if r is None:
        raise ApolloRefused("There's no such offer.", 404)
    return r


def answer(db, owner: str, trust_id: Any, yes: bool, *, may_auto: bool) -> Dict[str, Any]:
    """The person's answer to an offer. Yes needs the admin's ceiling."""
    r = _get(db, owner, trust_id)
    if r.state != "offered":
        raise ApolloRefused("That offer isn't open any more.", 409)
    if yes:
        if not may_auto:
            raise ApolloRefused(NO_CEILING, 403)
        r.state = "granted"
        r.granted_at = _now()
    else:
        r.state = "drafting"
        r.streak = 0
        r.declined_at = _now()
    r.updated_at = _now()
    db.flush()
    return to_dict(r)


def take_back(db, owner: str, trust_id: Any) -> Dict[str, Any]:
    """Apollo asks again for this kind and action, and the record starts over."""
    r = _get(db, owner, trust_id)
    r.state = "drafting"
    r.streak = 0
    r.granted_at = None
    r.updated_at = _now()
    db.flush()
    return to_dict(r)


def granted_kind(db, owner: str, scheduled_task_id: Optional[str], tool: Any) -> Optional[str]:
    """The kind whose "just do it" covers this card, or None. The admin's
    ceiling is the caller's to ask, per run."""
    task = apollo_task_of(db, owner, scheduled_task_id)
    kind = kind_key(getattr(task, "kind", None))
    if task is None or not kind:
        return None
    r = _row(db, owner, kind, str(tool or "").strip(), make=False)
    return kind if r is not None and r.state == "granted" else None
