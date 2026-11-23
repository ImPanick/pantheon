# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `fleet` tool: how an agent leading an Apollo task talks to its team.

Only a run that leads one of the person's Apollo tasks gets it
(`runs.apollo_plan_parts`), and only while the goal's chain has room
(`fleet.MAX_DEPTH`). The task is found from the run itself — the scheduled
task whose chat this is, its hire, the Apollo task that hire leads — never
from the arguments, so an agent can't reach another task or another person.

  roster    — agents in the roster that fit a need, with their fit badge
  delegate  — hand a sub-task to an agent: {agent, brief, review_by?}
  ask       — ask an agent one question: {agent, question}
  escalate  — a decision or a yes only the person can give: {question}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from src.apollo import fleet as F
from src.apollo.errors import ApolloRefused

logger = logging.getLogger(__name__)

ACTIONS = ("roster", "delegate", "ask", "escalate")
READ_ACTIONS = frozenset({"roster"})
WRITE_ACTIONS = frozenset(ACTIONS) - READ_ACTIONS
NOT_A_LEAD = "The fleet is for an agent leading one of the person's Apollo tasks, and this run isn't one."


def _out(text: str, **extra) -> Dict[str, Any]:
    return {"output": text, "exit_code": 0, **extra}


def task_of_run(db, owner: str, session_id: Optional[str]):
    """The Apollo task this run leads, or None."""
    if not owner or not session_id:
        return None
    from core.database import ScheduledTask
    from src.apollo.runs import apollo_task_for_hire
    from src.agents import hires as H
    st = (db.query(ScheduledTask).filter(ScheduledTask.session_id == str(session_id),
                                         ScheduledTask.owner == owner).first())
    if st is None:
        return None
    hire = H.hire_for_task(db, st.id)
    task = apollo_task_for_hire(db, getattr(hire, "id", None))
    return task if task is not None and task.owner == owner else None


def roster(owner: str, need: Any, *, limit: int = 6) -> List[Dict[str, Any]]:
    from src.apollo.lead import candidates
    return candidates(owner, str(need or ""), limit=limit)


def _do(db, owner: str, task, agent_id: Optional[str], args: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    from src.apollo import runs
    action = str(args.get("action") or "").strip().lower()
    me = task.lead_agent or agent_id or "apollo"
    if action == "roster":
        found = roster(owner, args.get("need") or args.get("brief") or task.title)
        found = [a for a in found if a["id"] != me]
        if not found:
            return _out("No agent in the roster fits that. Do it yourself, or say in your report what "
                        "kind of agent the goal is missing."), []
        return _out("\n".join(f"- {a['id']}: {a['name']} — {a['tagline']} ({a['fit']})" for a in found)), []
    if action in ("delegate", "ask"):
        brief = args.get("brief") if action == "delegate" else args.get("question")
        if action == "ask" and brief:
            brief = f"Answer this one question for {me}, with what your answer rests on:\n{brief}"
        child = F.hand_off(db, owner, task, from_agent=me, to_agent=args.get("agent"), brief=brief,
                           via=action, review_by=args.get("review_by"))
        run, why = runs.prepare(db, owner, child)
        db.commit()
        said = (f"Handed to {child.lead_agent} as “{child.title}”." if action == "delegate"
                else f"Asked {child.lead_agent}.")
        if why:
            said += f" It can't start yet: {why}"
        return _out(said + " You run again with the report when it lands; end this run now, saying "
                           "what you handed off."), ([run] if run else [])
    if action == "escalate":
        F.escalate(db, owner, task, from_agent=me, question=args.get("question"))
        db.commit()
        return _out("The person has the question. End this run; you run again with their answer."), []
    raise ApolloRefused(f"The fleet's actions are {', '.join(ACTIONS)}.")


def run_sync(owner: str, session_id: Any, agent_id: Any, args: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        task = task_of_run(db, owner, session_id)
        if task is None:
            return {"error": NOT_A_LEAD, "exit_code": 1}, []
        return _do(db, owner, task, agent_id, args)
    except ApolloRefused as refused:
        db.rollback()
        return {"error": refused.sentence, "exit_code": 1}, []
    finally:
        db.close()


def parse(content: Any) -> Dict[str, Any]:
    raw = str(content or "").strip()
    if not raw:
        return {}
    try:
        args = json.loads(raw)
    except (TypeError, ValueError):
        return {"action": raw.split()[0].lower()} if raw.split() else {}
    return args if isinstance(args, dict) else {}


async def fleet(content: Any, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = ctx or {}
    owner = ctx.get("owner")
    if not owner:
        return {"error": NOT_A_LEAD, "exit_code": 1}
    result, runs_to_start = await asyncio.to_thread(run_sync, owner, ctx.get("session_id"),
                                                    ctx.get("agent_id"), parse(content))
    from src.apollo.tool import start_run
    for run in runs_to_start:
        if not await start_run(run):
            result["output"] = result.get("output", "") + " (Its run couldn't start just now; it's on the task.)"
    return result


class FleetTool:
    async def execute(self, content, ctx):
        return await fleet(content, ctx)
