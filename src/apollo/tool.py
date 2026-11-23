# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `apollo` tool: how Apollo's chat acts on its own records.

Structured actions are tool calls with a schema, never parsed out of prose
(the outline's model-agnostic rule). One tool with an `action`, the way
`manage_memory` and `manage_session` are, so the registry gains one name:

  status        — what is open, what needs the person
  create_task   — a goal or errand as a task, staffed with a lead agent
  start_task    — run a task's lead now
  update_task   — move a task on: state, next step, outcome
  ask           — mark a task Needs you with its one question
  note          — a notebook line (open_loop, talked_through, working)
  settle_note   — close a notebook line (settled or dropped)
  remember      — a line in Brain, stated or inferred (inferred needs evidence)
  confirm       — an inferred line the person said is right becomes stated
  forget        — delete a line from Brain
  knows         — every line Apollo keeps about the person

Every action is the caller's own: the owner comes from the run, never from the
arguments, so one person's Apollo can't reach another's records.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Tuple

from src.apollo import knows, notebook, tasks
from src.apollo.errors import ApolloRefused

logger = logging.getLogger(__name__)

ACTIONS = ("status", "create_task", "start_task", "update_task", "ask", "note", "settle_note",
           "remember", "confirm", "forget", "knows")
READ_ACTIONS = frozenset({"status", "knows"})
WRITE_ACTIONS = frozenset(ACTIONS) - READ_ACTIONS
DESTRUCTIVE_ACTIONS = frozenset({"forget"})
NO_OWNER = "Apollo acts for a signed-in person only."


def parse(content: Any) -> Dict[str, Any]:
    raw = str(content or "").strip()
    if not raw:
        return {}
    try:
        args = json.loads(raw)
    except (TypeError, ValueError):
        # A bare action word: `status`, `knows`.
        return {"action": raw.split()[0].lower()} if raw.split() else {}
    return args if isinstance(args, dict) else {}


def _out(text: str, **extra) -> Dict[str, Any]:
    return {"output": text, "exit_code": 0, **extra}


def _do(db, owner: str, args: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    """The action, done in `db`. Returns the result and, for start_task, the
    scheduled task to run once the write is committed."""
    action = str(args.get("action") or "").strip().lower()
    if action not in ACTIONS:
        raise ApolloRefused(f"apollo needs an action: {', '.join(ACTIONS)}.")
    if action == "status":
        st = tasks.status(db, owner)
        open_ = [tasks.to_dict(t) for t in tasks.list_for(db, owner, include_done=False, limit=20)]
        lines = [st["words"]] + [f"- [{t['state_words']}] {t['title']} (id {t['id']})" for t in open_]
        return _out("\n".join(lines), status=st, tasks=open_), None
    if action == "create_task":
        t = tasks.create(db, owner, title=args.get("title"), brief=args.get("brief"),
                         kind=args.get("kind"), parent_id=args.get("parent_id"),
                         lead_agent=args.get("lead_agent"),
                         budget_tokens=args.get("budget_tokens"), started_by="apollo")
        lead = f"led by {t.lead_agent}" if t.lead_agent else "with no roster agent to lead it yet"
        run = None
        if args.get("start", True) and t.lead_agent:
            from src.apollo import runs
            run, why = runs.prepare(db, owner, t)
            if run is None:
                return _out(f"Task “{t.title}” made ({lead}), not started: {why}",
                            task=tasks.to_dict(t)), None
        return _out(f"Task “{t.title}” made, {lead}{', and started' if run else ''}. Id {t.id}.",
                    task=tasks.to_dict(t)), run
    if action == "start_task":
        from src.apollo import runs
        t = tasks.get(db, owner, args.get("id"))
        run, why = runs.prepare(db, owner, t)
        if run is None:
            return _out(f"Not started: {why}", task=tasks.to_dict(t)), None
        return _out(f"Started “{t.title}”.", task=tasks.to_dict(t)), run
    if action == "update_task":
        fields = {k: args[k] for k in ("title", "brief", "kind", "lead_agent", "budget_tokens",
                                        "next_step", "state", "question", "outcome") if k in args}
        t = tasks.update(db, owner, args.get("id"), fields)
        return _out(f"“{t.title}” is {tasks.STATE_WORDS[t.state]}.", task=tasks.to_dict(t)), None
    if action == "ask":
        t = tasks.get(db, owner, args.get("id"))
        tasks.set_state(t, "needs_you", question=args.get("question"))
        return _out(f"“{t.title}” now waits on: {t.question}", task=tasks.to_dict(t)), None
    if action == "note":
        n = notebook.add(db, owner, args.get("text"), kind=args.get("kind") or "working",
                         task_id=args.get("task_id"))
        return _out(f"Noted ({n.kind}).", note=notebook.to_dict(n)), None
    if action == "settle_note":
        n = notebook.set_state(db, owner, args.get("id"), args.get("state") or "settled")
        return _out(f"Note {n.state}.", note=notebook.to_dict(n)), None
    if action == "remember":
        line = knows.remember(owner, args.get("text"), basis=args.get("basis") or "stated",
                              category=args.get("category") or "fact",
                              evidence=args.get("evidence"))
        return _out(f"Kept ({line['basis']}): {line['text']}", line=line), None
    if action == "confirm":
        line = knows.confirm(owner, args.get("id"))
        return _out(f"Confirmed: {line['text']}", line=line), None
    if action == "forget":
        knows.forget(owner, args.get("id"))
        return _out("Forgotten."), None
    lines = knows.what_apollo_knows(owner)
    shown = "\n".join(f"- ({line['basis']}) {line['text']}" for line in lines[:40]) or "Nothing yet."
    return _out(shown, lines=lines), None


def run_sync(owner: str, args: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        result, run = _do(db, owner, args)
        db.commit()
        return result, run
    except ApolloRefused as refused:
        db.rollback()
        return {"error": refused.sentence, "exit_code": 1}, None
    finally:
        db.close()


async def apollo(content: Any, session_id: Any = None, owner: Any = None) -> Dict[str, Any]:
    if not owner:
        return {"error": NO_OWNER, "exit_code": 1}
    from src.nobody_mode import keeps_nothing
    if keeps_nothing():
        return {"error": "Nobody mode keeps nothing, so Apollo keeps nothing from it.", "exit_code": 1}
    args = parse(content)
    result, run = await asyncio.to_thread(run_sync, owner, args)
    if run and not await start_run(run):
        result["output"] = result.get("output", "") + " (The run couldn't start just now; it's on the task.)"
    return result


async def start_run(run_id: Any) -> bool:
    """Start the lead's scheduled run now. False when it could not start; the
    task keeps saying what it is waiting on either way."""
    try:
        from src.event_bus import get_task_scheduler
        from src.interactive_gate import STARTED_BY_PERSON
        scheduler = get_task_scheduler()
        if scheduler is None:
            return False
        return bool(await scheduler.run_task_now(run_id, force=True, started_by=STARTED_BY_PERSON))
    except Exception:
        logger.warning("Apollo could not start the run for %s", run_id, exc_info=True)
        return False


class ApolloTool:
    async def execute(self, content, ctx):
        ctx = ctx or {}
        return await apollo(content, ctx.get("session_id"), owner=ctx.get("owner"))
