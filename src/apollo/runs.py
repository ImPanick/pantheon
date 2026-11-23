# SPDX-License-Identifier: AGPL-3.0-or-later
"""A goal's work, run by its lead agent, and its one line back.

Settled calls 3, 6 and 8: the work runs as a hire of the lead agent from the
roster, so every run is a `ScheduledTask` run (the run log, retries, one run at
a time, the install's agent-run limit) and never a second scheduler. The hire
is a `trial` (its schedule off), made once per task and reused by later runs.

Two hooks in the engine read this module:

  * `src.agents.runtime.plan_for_task` asks `apollo_plan_parts` for a hire that
    belongs to an Apollo task: the lead is told it is doing the goal Apollo
    handed it, the way its runbook works, and gets the brief;
  * `TaskScheduler` calls `report_landed` after a run's report is kept: the
    run's tokens are charged to the goal's budget when the model is API-billed,
    the task moves to Done (or Needs you, with the one question, when the run
    did not deliver), and Apollo's chat gets one line.

A goal over its budget on a paid model does not start; it asks instead.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.apollo import budget as B
from src.apollo import tasks as T
from src.apollo.errors import ApolloRefused

logger = logging.getLogger(__name__)

APOLLO_TASK_PROMPT = "Do the goal Apollo handed you, now, and finish with your report."
NAME_MAX = 60
FILLABLE = ("text", "long_text", "list", "choice", "boolean", "number", "time")


def _first_line(text: str, limit: int = 240) -> str:
    for raw in str(text or "").splitlines():
        line = raw.strip().lstrip("#-*• ").strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return ""


def inputs_for(manifest, task) -> Dict[str, Any]:
    """The lead's hire inputs, filled from the goal. A required input that a
    goal can't answer (an account, a folder, a web address) is refused in a
    sentence, so the person can pick another lead or say what it should be."""
    out: Dict[str, Any] = {}
    goal = task.brief or task.title
    for spec in manifest.inputs:
        if spec.get("optional") or spec.get("default") is not None:
            continue
        kind = spec.get("kind")
        if kind not in FILLABLE:
            raise ApolloRefused(f"{manifest.name} needs “{spec['label']}” to run, which a goal "
                                f"doesn't say. Pick another lead, or hire it in Agents.", 409)
        if kind == "text":
            out[spec["key"]] = goal[:300]
        elif kind == "long_text":
            out[spec["key"]] = goal[:4000]
        elif kind == "list":
            out[spec["key"]] = [task.title[:200]]
        elif kind == "choice":
            out[spec["key"]] = (spec.get("choices") or [""])[0]
        elif kind == "boolean":
            out[spec["key"]] = False
        elif kind == "number":
            out[spec["key"]] = 0
        elif kind == "time":
            out[spec["key"]] = "09:00"
    return out


def apollo_task_for_hire(db, hire_id: Optional[str]):
    if not hire_id:
        return None
    from core.database import ApolloTask
    return db.query(ApolloTask).filter(ApolloTask.hire_id == hire_id).first()


def prepare(db, owner: str, task, *, endpoint_url: Optional[str] = None,
            auth_manager: Any = None) -> Tuple[Optional[str], str]:
    """Make (or reuse) the lead's hire for `task` and say which scheduled task
    to run. `(task_id, "")` to start, or `(None, sentence)` when it can't —
    in which case the task already says why (Needs you, with its question)."""
    from src.agents import hires as H
    from src.agents.catalogue import get_agent
    from core.database import AgentHire, ScheduledTask

    if task.state == "done":
        raise ApolloRefused("That task is done. Start a new one to do more.", 409)
    if not task.lead_agent:
        raise ApolloRefused("No agent leads this yet. Pick a lead from your roster first.", 409)
    if endpoint_url is None:
        try:
            from src.task_endpoint import resolve_task_endpoint
            endpoint_url, _model, _h = resolve_task_endpoint(owner=owner)
        except Exception:
            endpoint_url = None
    if task.space_id:
        from src.apollo import spaces as S
        sc = S.scope(db, owner, task.space_id, "memory")
        if sc.local_only and B.billed(endpoint_url):
            sentence = S.LOCAL_ONLY.format(name=sc.names.get(sc.edge, "This space"))
            T.set_state(task, "needs_you", question=sentence)
            db.flush()
            return None, sentence
    ok, sentence = B.may_spend(task, endpoint_url)
    if ok:
        from src.apollo.fleet import root_of
        root = root_of(db, task)
        if root is not task:
            # A delegate spends the goal's budget too (`report_landed` charges
            # both), so the goal's cap holds across its whole team.
            ok, sentence = B.may_spend(root, endpoint_url)
    if not ok:
        T.set_state(task, "needs_you", question=sentence)
        db.flush()
        return None, sentence
    manifest = get_agent(owner, task.lead_agent)
    if manifest is None:
        raise ApolloRefused("Its lead agent is gone from your roster. Pick another lead.", 409)
    hire = None
    if task.hire_id:
        hire = db.query(AgentHire).filter(AgentHire.id == task.hire_id,
                                          AgentHire.owner == owner).first()
        if hire is not None and hire.agent_id != manifest.id:
            H.fire(db, hire)       # the lead changed: the old hire goes
            hire = None
    if hire is None:
        try:
            hire = H.make_hire(db, owner=owner, manifest=manifest,
                               inputs=inputs_for(manifest, task),
                               name=task.title[:NAME_MAX], status="trial",
                               auth_manager=auth_manager)
        except H.HireRefused as refused:
            raise ApolloRefused(refused.sentence, refused.status)
        task.hire_id = hire.id
    ids = H.task_ids_of(db, hire.id)
    if not ids:
        raise ApolloRefused(f"{manifest.name} has no way to start a run.", 409)
    first = db.query(ScheduledTask).filter(ScheduledTask.id == ids[0]).first()
    if first is not None:
        first.prompt = APOLLO_TASK_PROMPT
    T.set_state(task, "working", next_step=f"{manifest.name} is on it.")
    db.flush()
    return ids[0], ""


def apollo_brief(task, manifest, *, owner: Optional[str]) -> str:
    """The lead's system prompt for an Apollo goal: Apollo's brief over the
    agent's runbook, which says how it works rather than what to do."""
    from src.agents.runtime import CARRY_HEADING, REPORT_HEADING
    who = owner or "the person"
    lines = [
        f"You are {manifest.name}, leading a goal that Apollo, {who}'s partner in Pantheon, "
        f"handed you: {task.title}",
        "",
        "Do that goal. Work the way your runbook below works — its steps, its care, its "
        "limits — on the goal rather than on the runbook's usual job. Use only the tools you "
        "are given. If the goal needs something you can't do or don't have, say so plainly in "
        "your report rather than trying another way. Where an action needs the person's yes, "
        "Pantheon's own approval card does the asking: make the call, never ask in words.",
        "",
        "When you are done, your last message is your answer, and it ends with these sections:",
        "",
        REPORT_HEADING,
        "- the outcome first, in one line, then what you did and left behind, a line each",
    ]
    if manifest.memory != "none":
        lines += ["", CARRY_HEADING,
                  "- only what your next run needs to remember (or the single word: nothing)"]
    lines += ["", "# Runbook", "", manifest.runbook.strip()]
    return "\n".join(lines)


def apollo_plan_parts(db, hire, manifest) -> Optional[Dict[str, Any]]:
    """For a hire that belongs to an Apollo task: its system prompt and the
    brief as context. `None` for every other hire, which runs as before."""
    task = apollo_task_for_hire(db, getattr(hire, "id", None))
    if task is None:
        return None
    from src.prompt_security import own_context_message
    from src.apollo import fleet as F
    body = task.brief or task.title
    if task.next_step and task.next_step.startswith(("You answered", "You asked for changes")):
        body = f"{body}\n\n{task.next_step}"
    team = F.plan_parts(db, task)
    prompt = apollo_brief(task, manifest, owner=hire.owner)
    if team["lines"]:
        prompt = prompt.replace("\n# Runbook", "\n" + "\n\n".join(team["lines"]) + "\n\n# Runbook", 1)
    return {"system_prompt": prompt,
            "context_messages": [own_context_message("the goal Apollo handed you", body)]
            + team["context_messages"],
            "ceiling": team["ceiling"], "fleet": team["fleet"]}


def run_tokens(db, run_id: Optional[str]) -> int:
    if not run_id:
        return 0
    from sqlalchemy import func
    from core.database import Event
    total = db.query(func.coalesce(func.sum(Event.input_tokens), 0)
                     + func.coalesce(func.sum(Event.output_tokens), 0)).filter(
        Event.run_id == run_id).scalar()
    return int(total or 0)


def prepare_all(db, owner: str, task_ids: List[str], endpoint_url: Optional[str] = None) -> List[str]:
    """The scheduled runs to start for the fleet's next tasks. A task that
    can't start (its budget, a local-only space) already says why."""
    out: List[str] = []
    for tid in dict.fromkeys(task_ids or ()):
        try:
            t = T.get(db, owner, tid)
        except ApolloRefused:
            continue
        if t.state == "done":
            continue
        try:
            run, _why = prepare(db, owner, t, endpoint_url=endpoint_url)
        except ApolloRefused as refused:
            T.set_state(t, "needs_you", question=refused.sentence)
            run = None
        if run:
            out.append(run)
    db.commit()
    return out


def report_landed(db, scheduled_task, run_id: Optional[str], answer: str,
                  checks: Optional[List[Dict[str, Any]]] = None, *,
                  endpoint_url: Optional[str] = None,
                  post: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
                  start: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """A lead's run finished. Charge its tokens, move the task on, and say one
    line in Apollo's chat. Returns that line, or `None` for a run that is not
    an Apollo task's."""
    from src.agents import hires as H
    from src.agents.runtime import failed
    hire = H.hire_for_task(db, getattr(scheduled_task, "id", None))
    task = apollo_task_for_hire(db, getattr(hire, "id", None))
    if task is None:
        return None
    if endpoint_url is None:
        endpoint_url = getattr(scheduled_task, "endpoint_url", None)
        if not endpoint_url:
            try:
                from src.task_endpoint import resolve_task_endpoint
                endpoint_url, _m, _h = resolve_task_endpoint(owner=task.owner)
            except Exception:
                endpoint_url = None
    from src.apollo import fleet as F
    spent = run_tokens(db, run_id)
    B.charge(task, spent, endpoint_url)
    root = F.root_of(db, task)
    if root is not task:
        B.charge(root, spent, endpoint_url)      # a fleet spends the goal's budget
    if getattr(scheduled_task, "session_id", None):
        task.session_id = scheduled_task.session_id
    misses = failed(checks or [])
    starts: List[str] = []
    if misses:
        T.set_state(task, "needs_you",
                    question="The run didn't deliver everything it should have. Run it again?",
                    next_step=_first_line(answer) or None)
        line = f"“{task.title}” needs you: the run came back short. It's in the task."
    else:
        outcome = _first_line(_report_section(answer)) or _first_line(answer) or "Finished."
        report = _report_section(answer).strip() or str(answer or "")
        if task.state == "needs_you":
            # The lead asked its one question (or escalated) during the run:
            # the task waits on the person, whatever the run's last words were.
            moved = {"state": "needs_you", "start": [],
                     "line": f"“{task.title}” needs you: {task.question}" if task.question
                     else f"“{task.title}” needs you."}
        else:
            moved = F.landed(db, task, report, outcome)
        starts = list(moved["start"])
        if moved["state"] is None:
            T.set_state(task, "done", outcome=outcome, next_step=None)
            line = f"Done: {task.title}. {outcome}"
        elif task.parent_id:
            # A child's progress is the goal's log; the person hears about the
            # goal, unless the fleet says something needs them.
            line = moved["line"]
        elif moved["state"] == "done":
            line = f"Done: {task.title}. {task.outcome or outcome}"
        else:
            line = moved["line"]
    db.commit()
    for run in prepare_all(db, task.owner, starts, endpoint_url):
        if start is None:
            break
        try:
            start(run)
        except Exception:
            logger.warning("Could not start the fleet's next run %s", run, exc_info=True)
    if post is not None and line:
        try:
            post(task.owner, line, {"source": "apollo", "apollo_task_id": task.id,
                                    "state": task.state})
        except Exception:
            logger.warning("Could not post Apollo's line for task %s", task.id, exc_info=True)
    return line


def _report_section(answer: str) -> str:
    from src.agents.runtime import REPORT_HEADING
    text = str(answer or "")
    at = text.find(REPORT_HEADING)
    return text[at + len(REPORT_HEADING):] if at >= 0 else ""
