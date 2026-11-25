# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's rhythm: briefings at the times each person sets, check-ins between
them that speak only when something changed, and quiet hours that hold.

The outline (*Core behaviours* 1, settled call 4): "Briefings at the times
each person sets, plus check-ins between them that speak only when something
changed ... Quiet hours hold. Everything below the bar lands in the activity
list, not the chat." The first briefing of the day is "First light".

Both run on the `ScheduledTask` engine (zones, retries, run log, one run at a
time), bound to the person's Apollo crew member, so there is no second
scheduler. Which tasks are Apollo's briefings and which its check-in is this
module's record (`ApolloRhythm`), never a task's name.

- A **briefing** hands the model the person's world, as the assistant's
  check-in always has (calendar, notes, integrations), plus Apollo's own
  section from `digest()`: what needs them, what finished since the last time
  Apollo spoke, open loops, and that a locked space needs them (no content).
- A **check-in** is decided here with no model at all: in quiet hours, or
  when nothing in `digest()` is news since Apollo last spoke, it stays silent
  and its run says so. Otherwise it posts the news as one short message.

"News" is what changed since Apollo last spoke: a task that now needs the
person, finished, or waits on an approval. A thing reported once isn't
reported again until it changes, and a talked-through note is never news.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.apollo.errors import ApolloRefused
from src.utc_clock import utcnow_naive  # `B2173`: the one clock

FIRST_LIGHT = "First light"
BRIEFING = "Briefing"
CHECK_IN = "Apollo check-in"
BRIEFINGS_MAX = 6
CHECKIN_HOURS = (0, 1, 2, 3, 4, 6, 8, 12)   # 0 is off
DEFAULT_CHECKIN_HOURS = 3
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

BRIEFING_PROMPT = (
    "This is {name}, one of the briefings the person set. Lead with what needs "
    "them today, then what changed since you last spoke, then what's coming. "
    "Short paragraphs, no filler, nothing they've already settled. If nothing "
    "needs them, say so first.")


def valid_time(value: Any) -> str:
    text = str(value or "").strip()
    if not _HHMM.match(text):
        raise ApolloRefused("A time is HH:MM on a 24-hour clock, like 07:00.")
    return text


def row(db, owner: str, *, make: bool = True):
    from core.database import ApolloRhythm
    r = db.query(ApolloRhythm).filter(ApolloRhythm.owner == owner).first()
    if r is None and make:
        r = ApolloRhythm(owner=owner, checkin_hours=DEFAULT_CHECKIN_HOURS,
                         briefing_ids="[]", reported="{}")
        db.add(r)
        db.flush()
    return r


def _ids(r) -> List[str]:
    try:
        out = json.loads(r.briefing_ids or "[]")
        return [str(x) for x in out] if isinstance(out, list) else []
    except ValueError:
        return []


def kind_of(db, task) -> Optional[str]:
    """'briefing', 'checkin' or None: which of Apollo's rhythms `task` is."""
    r = row(db, task.owner, make=False)
    if r is None:
        return None
    if task.id == r.checkin_task_id:
        return "checkin"
    if task.id in _ids(r):
        return "briefing"
    return None


# -- quiet hours ------------------------------------------------------------

def _local(now_utc: datetime, tz_name: Optional[str]) -> datetime:
    if not tz_name:
        return now_utc
    try:
        from zoneinfo import ZoneInfo
        return now_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:
        return now_utc


def in_quiet(r, now_utc: datetime, tz_name: Optional[str]) -> bool:
    """Whether `now_utc` falls in the person's quiet hours, in their zone.
    A span that crosses midnight (22:00 to 07:00) is read that way."""
    if not r or not r.quiet_start or not r.quiet_end or r.quiet_start == r.quiet_end:
        return False
    t = _local(now_utc, tz_name).time()
    a = dtime(*map(int, r.quiet_start.split(":")))
    b = dtime(*map(int, r.quiet_end.split(":")))
    return (a <= t < b) if a < b else (t >= a or t < b)


# -- what's news ------------------------------------------------------------

def _stamp(task) -> str:
    return f"{task.state}|{task.question or ''}|{task.outcome or ''}"


def digest(db, owner: str, *, since: Optional[datetime] = None,
           reported: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Apollo's own section of a briefing, and what of it is news.

    Reads every space the All view reads; a locked space shows only that
    something there needs the person, by its name. `news` holds only lines
    whose task changed since it was last reported; `reported` is the record
    to keep after speaking."""
    from core.database import ApolloTask
    from src.apollo import chat as C, notebook as N, spaces as S, tasks as Tk

    reported = dict(reported or {})
    names = {k: v.name for k, v in S._all(db, owner).items()}
    sealed = set(S.sealed_ids(db, owner))
    rows = (Tk._in_spaces(db.query(ApolloTask).filter(ApolloTask.owner == owner), db, owner, S.ALL)
            .order_by(ApolloTask.updated_at).all())

    def where(t) -> str:
        return f" (in {names[t.space_id]})" if t.space_id in names else ""

    needs, done, working = [], [], []
    news: List[str] = []
    keep: Dict[str, str] = {}
    for t in rows:
        if t.state == "needs_you":
            line = f"“{t.title}”{where(t)} needs you: {t.question or 'it is waiting on your answer.'}"
            needs.append(line)
        elif t.state == "done":
            if since is None or (t.done_at and t.done_at >= since):
                done.append(f"“{t.title}”{where(t)} is done: {t.outcome or 'finished.'}")
            else:
                continue
        elif t.state == "working":
            working.append(f"“{t.title}”{where(t)}")
            continue
        else:
            continue
        keep[t.id] = _stamp(t)
        if reported.get(t.id) != keep[t.id]:
            news.append(needs[-1] if t.state == "needs_you" else done[-1])

    locked = []
    if sealed:
        every = S._all(db, owner)
        # One line per outermost locked space, for anything anywhere inside it.
        outer = [sid for sid in sealed if every[sid].parent_id not in sealed]
        for sid in sorted(outer, key=lambda s: names.get(s, "")):
            if db.query(ApolloTask.id).filter(ApolloTask.owner == owner,
                                              ApolloTask.space_id.in_(S.subtree(every, sid)),
                                              ApolloTask.state == "needs_you").first():
                line = f"Something in “{names.get(sid, 'a locked space')}” needs you."
                locked.append(line)
                keep[f"space:{sid}"] = "needs"
                if reported.get(f"space:{sid}") != "needs":
                    news.append(line)

    approvals = []
    for a in C.waiting_approvals(db, owner, space=S.ALL):
        line = f"“{a.get('title') or 'A task'}” is waiting for your yes on {a.get('tool') or 'an action'}."
        approvals.append(line)
        key = f"approval:{a.get('run_id')}"
        keep[key] = "waiting"
        if reported.get(key) != "waiting":
            news.append(line)

    from src.apollo import trust as Tr
    offers = []
    for o in Tr.list_for(db, owner, space=S.ALL, state="offered"):
        offers.append(o["words"])
        key = f"offer:{o['id']}"
        keep[key] = "offered"
        if reported.get(key) != "offered":
            news.append(o["words"])

    loops = [n.text for n in N.list_for(db, owner, kind="open_loop", state="open", limit=10, space=S.ALL)]
    return {"needs": needs, "approvals": approvals, "locked": locked, "done": done,
            "working": working, "offers": offers, "loops": loops, "news": news, "reported": keep}


def section(d: Dict[str, Any]) -> str:
    """The digest as the briefing's Apollo section, for the model to fold in."""
    parts = []
    for title, key in (("Needs them", "needs"), ("Waiting for their yes", "approvals"),
                       ("Locked spaces (say only this, never guess what)", "locked"),
                       ("Finished since you last spoke", "done"), ("Working on", "working"),
                       ("Apollo offers to just do (they decide)", "offers"),
                       ("Open loops they owe or were promised", "loops")):
        if d.get(key):
            parts.append(f"{title}:\n" + "\n".join(f"- {x}" for x in d[key]))
    return "\n\n".join(parts) if parts else "Nothing of Apollo's needs them, and nothing finished."


def checkin_words(news: List[str]) -> str:
    """A check-in's message: the news, one line each, the count first."""
    if len(news) == 1:
        return news[0]
    return f"{len(news)} things since I last spoke:\n" + "\n".join(f"- {x}" for x in news)


def remember_spoke(db, owner: str, reported: Dict[str, str], *, now: Optional[datetime] = None) -> None:
    r = row(db, owner)
    r.reported = json.dumps(reported, sort_keys=True)
    r.last_spoke_at = now or utcnow_naive()
    db.flush()


def reported_of(r) -> Dict[str, str]:
    try:
        out = json.loads(r.reported or "{}") if r is not None else {}
        return out if isinstance(out, dict) else {}
    except ValueError:
        return {}


def checkin(db, owner: str, tz_name: Optional[str], *, now: Optional[datetime] = None) -> Tuple[Optional[str], str]:
    """(message or None, what the run says). None means Apollo stays quiet."""
    now = now or utcnow_naive()
    r = row(db, owner)
    if in_quiet(r, now, tz_name):
        return None, "Quiet hours: Apollo stayed quiet."
    d = digest(db, owner, since=r.last_spoke_at, reported=reported_of(r))
    if not d["news"]:
        return None, "Nothing changed since Apollo last spoke, so it stayed quiet."
    remember_spoke(db, owner, d["reported"], now=now)
    return checkin_words(d["news"]), f"Spoke: {len(d['news'])} new."


# -- settings ---------------------------------------------------------------

def to_dict(db, owner: str) -> Dict[str, Any]:
    from core.database import ScheduledTask
    r = row(db, owner)
    ids = _ids(r)
    tasks = {t.id: t for t in db.query(ScheduledTask).filter(ScheduledTask.id.in_(ids + [r.checkin_task_id or ""])).all()}

    def iso(d):
        return d.isoformat() + "Z" if d else None
    briefings = [{"id": i, "name": tasks[i].name, "time": tasks[i].scheduled_time,
                  "enabled": (tasks[i].status or "active") == "active",
                  "next_run": iso(tasks[i].next_run)} for i in ids if i in tasks]
    from core.database import CrewMember
    crew = (db.query(CrewMember).filter(CrewMember.owner == owner,
                                        CrewMember.is_default_assistant == True)  # noqa: E712
            .first())
    return {"briefings": briefings, "checkin_hours": int(r.checkin_hours or 0) if r.checkin_task_id else 0,
            "timezone": getattr(crew, "timezone", None), "has_chat": bool(crew and crew.session_id),
            "quiet": {"start": r.quiet_start, "end": r.quiet_end},
            "last_spoke_at": iso(r.last_spoke_at)}


def _crew(db, owner: str):
    from core.database import CrewMember
    crew = (db.query(CrewMember).filter(CrewMember.owner == owner,
                                        CrewMember.is_default_assistant == True)  # noqa: E712
            .first())
    if crew is None or not crew.session_id:
        raise ApolloRefused("Open your Apollo chat once first, so Apollo has somewhere to speak.", 409)
    return crew


def _task(db, owner: str, crew, *, name: str, prompt: str, **when):
    import uuid
    from core.database import ScheduledTask
    from src.task_scheduler import compute_next_run
    t = ScheduledTask(id=str(uuid.uuid4()), owner=owner, name=name, prompt=prompt, task_type="llm",
                      status="active", crew_member_id=crew.id, session_id=crew.session_id,
                      notifications_enabled=False, **when)
    t.next_run = compute_next_run(t.schedule, t.scheduled_time, cron_expression=t.cron_expression,
                                  tz_name=crew.timezone)
    db.add(t)
    db.flush()
    return t


def save(db, owner: str, *, briefings: Optional[List[Dict[str, Any]]] = None,
         checkin_hours: Optional[int] = None, quiet: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Set the person's briefings (a list of `{time, enabled}`, in order; the
    first is First light), how often check-ins look, and quiet hours. Each
    briefing is a daily task on the engine in the person's zone; removing one
    deletes its task."""
    from core.database import ScheduledTask
    from src.task_scheduler import compute_next_run
    crew = _crew(db, owner)
    r = row(db, owner)
    if quiet is not None:
        start, end = (quiet or {}).get("start"), (quiet or {}).get("end")
        if start or end:
            r.quiet_start, r.quiet_end = valid_time(start), valid_time(end)
        else:
            r.quiet_start = r.quiet_end = None
    if checkin_hours is not None:
        hours = int(checkin_hours)
        if hours not in CHECKIN_HOURS:
            raise ApolloRefused("Check-ins look every 1, 2, 3, 4, 6, 8 or 12 hours, or not at all.")
        r.checkin_hours = hours
        old = db.query(ScheduledTask).filter(ScheduledTask.id == (r.checkin_task_id or "")).first()
        if hours == 0:
            if old is not None:
                db.delete(old)
            r.checkin_task_id = None
        else:
            cron = f"0 */{hours} * * *" if hours < 24 else "0 9 * * *"
            if old is None:
                old = _task(db, owner, crew, name=CHECK_IN, prompt="Apollo's check-in.",
                            schedule="cron", cron_expression=cron)
                r.checkin_task_id = old.id
            else:
                old.cron_expression = cron
                old.next_run = compute_next_run("cron", None, cron_expression=cron, tz_name=crew.timezone)
    if briefings is not None:
        if len(briefings) > BRIEFINGS_MAX:
            raise ApolloRefused(f"Up to {BRIEFINGS_MAX} briefings a day.")
        wanted = []
        for b in briefings:
            wanted.append({"id": (b or {}).get("id"), "time": valid_time((b or {}).get("time")),
                           "enabled": bool((b or {}).get("enabled", True))})
        times = [w["time"] for w in wanted]
        if len(set(times)) != len(times):
            raise ApolloRefused("Two briefings at the same time would say the same thing twice.")
        wanted.sort(key=lambda w: w["time"])
        have = {t.id: t for t in db.query(ScheduledTask).filter(ScheduledTask.id.in_(_ids(r))).all()}
        keep: List[str] = []
        for i, w in enumerate(wanted):
            name = FIRST_LIGHT if i == 0 else BRIEFING
            prompt = BRIEFING_PROMPT.format(name=name)
            t = have.pop(w["id"], None) if w["id"] else None
            if t is None:
                t = _task(db, owner, crew, name=name, prompt=prompt, schedule="daily",
                          scheduled_time=w["time"])
            else:
                t.name, t.prompt, t.scheduled_time = name, prompt, w["time"]
                t.next_run = compute_next_run("daily", w["time"], tz_name=crew.timezone)
            t.status = "active" if w["enabled"] else "paused"
            keep.append(t.id)
        for gone in have.values():
            db.delete(gone)
        r.briefing_ids = json.dumps(keep)
    db.flush()
    return to_dict(db, owner)
