# SPDX-License-Identifier: AGPL-3.0-or-later
"""The assistant's words for workflows (`B1875`, `B1878`).

A workflow is built in the Workbench (Automations) and run by the scheduler's
walker; the assistant reaches it through `manage_tasks` (`draft_workflow`,
`run`, `dry_run`) and `manage_workflows` (`B1878`). Everything here SAYS what
the store and the engine already decided — when a start fires, what a draft
changed, where a step sends things — in the sentences the Workbench shows, so
the assistant and the page cannot tell the person two different things
(`Law 7`). Nothing here decides anything.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def start_words(trigger) -> str:
    """When a workflow's start (its trigger task) fires, as a person says it:
    "daily at 09:00 (Europe/Berlin)", "when its webhook is called", "only when
    you run it". A schedule names its zone, or UTC when it has none — the
    scheduler reads a time with no zone as UTC (`compute_next_run`)."""
    if trigger is None:
        return "never: it has no start"
    kind = getattr(trigger, "trigger_type", None) or "schedule"
    if kind == "manual":
        return "only when you run it"
    if kind == "webhook":
        return "when its webhook is called"
    if kind == "event":
        event = getattr(trigger, "trigger_event", None) or "an event"
        count = getattr(trigger, "trigger_count", None) or 1
        return (f"on every {count} “{event}” events" if count > 1
                else f"each time “{event}” happens")
    schedule = getattr(trigger, "schedule", None) or "daily"
    at = getattr(trigger, "scheduled_time", None) or "09:00"
    day = getattr(trigger, "scheduled_day", None)
    zone = getattr(trigger, "tz_name", None) or "UTC"
    if schedule == "cron":
        return f"on the cron schedule “{getattr(trigger, 'cron_expression', None) or '?'}” ({zone})"
    if schedule == "weekly" and isinstance(day, int) and 0 <= day <= 6:
        when = f"every {_WEEKDAYS[day]} at {at}"
    elif schedule == "monthly" and isinstance(day, int):
        when = f"monthly on day {day} at {at}"
    elif schedule == "once":
        date = getattr(trigger, "scheduled_date", None)
        when = f"once, on {date:%Y-%m-%d} at {at}" if date is not None else f"once, at {at}"
    else:
        when = f"daily at {at}"
    return f"{when} ({zone})"


def drafted_reply(drafted) -> str:
    """`B1875`. What `manage_tasks draft_workflow` answers the model with: the
    sentence it always had, then what the Workbench's *Describe it* shows
    beside the draft — when it starts, the drafter's notes, where it sends
    things, and what was not drafted.

    Two of the notes stay out: "Made …" (the first sentence says it), and the
    webhook's address, which carries its secret token — a trigger anybody
    holding it can ring. The person reads it on the start in the Workbench;
    a chat transcript is no place for it."""
    from src.workflow_store import nodes_of, stored_graph, webhook_path
    wf, trigger = drafted.wf, drafted.trigger
    count = len(nodes_of(stored_graph(wf)))
    said = (f"Drafted “{wf.name}” as a workflow of {count} "
            f"step{'s' if count != 1 else ''}, switched off. A person checks each "
            f"step in the Workbench before it can run (Automations → "
            f"“{wf.name}”), and switches it on there.")
    if (getattr(trigger, "trigger_type", None) or "schedule") == "webhook":
        said += (f" It starts {start_words(trigger)}; its address is on the start in the "
                 f"Workbench.")
    else:
        said += f" It starts {start_words(trigger)}."
    address = webhook_path(trigger) if trigger is not None else None
    notes = [str(n) for n in (drafted.notes or ())
             if n and not str(n).startswith("Made ") and not (address and address in str(n))]
    if notes:
        said += " " + " ".join(notes)
    if drafted.destinations:
        said += " Where it sends things: " + " ".join(str(d) for d in drafted.destinations)
    if drafted.missing:
        said += " Not drafted: " + " ".join(str(m) for m in drafted.missing)
    return said


# ── `B1878` · manage_workflows ───────────────────────────────────────────────
#
# The assistant's door to workflows that already exist. Before it, the only
# workflow-aware action was `manage_tasks draft_workflow`; `list` printed a
# workflow's start as an ordinary task ("paused, daily, 09:00") with no steps,
# no marks and no on/off, and nothing read a run's steps, said why one failed,
# named where it sends things or exported it — the loop "build this flow, test
# it, tell me why step 3 failed" stopped after "build". Everything below READS
# what the store, the engine and the explainer already decided, or starts what
# the Workbench's own buttons start (*Show me what this would do*, *Test run*),
# through the same gates.
#
# What it never does is the person's (`B1117`, `B1005`, `B1870`): checking a
# step, applying a fix, answering a step that waits for a yes. Those are
# refused at their routes for anything that is not a person, and this tool has
# no action that reaches them — asked for one, it says whose it is. Changing a
# workflow is the person's in the Workbench, or `manage_tasks draft_workflow`'s
# for a new one, which is saved switched off and marked.
#
# Offered only on a turn that asks for workflows (`tool_index.ON_REQUEST_ONLY`):
# the slim set a first message carries does not grow by its schema.

MANAGE_WORKFLOWS_ACTIONS = ("list", "show", "runs", "explain", "dry_run", "test_run", "export")
RUNS_DEFAULT = 3
RUNS_MAX = 10
#: A run's step lines, and how much of a step's error, a reply carries.
RUN_STEP_LINES_MAX = 20
STEP_ERROR_SHOWN_MAX = 300
LIST_MAX = 50
#: A file longer than this is not put in a reply; the Workbench's Export is.
EXPORT_SHOWN_MAX = 16_000

_RUN_WORDS = {"success": "worked", "error": "failed", "skipped": "did not run",
              "aborted": "was stopped", "running": "is running", "queued": "is queued",
              "waiting": "is waiting"}

NAME_THE_WORKFLOW = "Name the workflow: workflow_id, from list."
EDITS_ARE_THE_PERSONS = ("Changing a workflow is the person's, in the Workbench (Automations). "
                         "A new one: manage_tasks draft_workflow drafts it, switched off.")
SWITCHING_IS_MANAGE_TASKS = ("Switching a workflow on or off is manage_tasks resume or pause, "
                             "with the task_id show names as its start. A workflow with steps "
                             "nobody has checked is not switched on.")


def _person_only(action: str) -> Optional[str]:
    """The sentence for an action that is the person's, or None."""
    from src import workflow_store as store
    if action in ("check", "checked", "looks_right", "check_steps"):
        return store.ONLY_A_PERSON_CHECKS
    if action in ("fix", "apply_fix", "apply"):
        return store.ONLY_A_PERSON_FIXES
    if action in ("answer", "approve", "deny"):
        return store.ONLY_A_PERSON_ANSWERS
    if action in ("edit", "save", "update", "create", "new", "delete", "rename", "import",
                  "restore", "duplicate"):
        return EDITS_ARE_THE_PERSONS
    if action in ("switch", "switch_on", "switch_off", "on", "off", "enable", "disable",
                  "pause", "resume"):
        return SWITCHING_IS_MANAGE_TASKS
    return None


def _when(value) -> str:
    return f"{value:%Y-%m-%d %H:%M} UTC" if value is not None else "at an unknown time"


def _on_off(trigger) -> str:
    if trigger is None:
        return "it has lost its start"
    return "switched on" if (trigger.status or "active") == "active" else "switched off"


def _find(db, owner, ref):
    """The caller's workflow by id or, failing that, by its exact name."""
    from core.database import Workflow
    from src import workflow_store as store
    from src.workflow_store import WorkflowRefused
    ref = str(ref or "").strip()
    if not ref:
        raise WorkflowRefused(400, NAME_THE_WORKFLOW)
    try:
        return store.owned_workflow(db, ref, owner)
    except WorkflowRefused:
        # Not an id of theirs: the same words are tried as a name below, and
        # a name that matches nothing is refused there, in words that say both.
        pass
    q = db.query(Workflow)
    if owner:
        q = q.filter(Workflow.owner == owner)
    named = [wf for wf in q.all() if (wf.name or "").strip().casefold() == ref.casefold()]
    if len(named) == 1:
        return named[0]
    if named:
        raise WorkflowRefused(409, f"{len(named)} of your workflows are called “{ref}”; name "
                                   f"one by its id: " + ", ".join(wf.id for wf in named) + ".")
    raise WorkflowRefused(404, f"No workflow of yours has the id or the name “{ref}”. list "
                               f"names them.")


def _list(db, owner) -> Dict:
    from core.database import ScheduledTask, Workflow
    from src import workflow_store as store
    from src.workflow_document import marked_nodes
    q = db.query(Workflow)
    if owner:
        q = q.filter(Workflow.owner == owner)
    rows = q.order_by(Workflow.updated_at.desc(), Workflow.id).all()
    if not rows:
        return {"response": "No workflows yet. manage_tasks draft_workflow drafts one from "
                            "the person's words.", "exit_code": 0}
    shown = rows[:LIST_MAX]
    ids = [wf.task_id for wf in shown if wf.task_id]
    triggers = {t.id: t for t in db.query(ScheduledTask).filter(ScheduledTask.id.in_(ids)).all()} \
        if ids else {}
    last = store.last_real_runs(db, ids)
    lines = [f"{len(rows)} workflow{'s' if len(rows) != 1 else ''}:"]
    for idx, wf in enumerate(shown, 1):
        graph = store.stored_graph(wf)
        steps = len(store.nodes_of(graph))
        trigger = triggers.get(wf.task_id)
        bits = [_on_off(trigger), f"{steps} step{'s' if steps != 1 else ''}"]
        if trigger is not None:
            bits.append(f"starts {start_words(trigger)}")
        marked = len(marked_nodes(graph))
        if marked:
            bits.append(f"{marked} not checked yet")
        run = last.get(wf.task_id)
        if run:
            bits.append(f"last run {_RUN_WORDS.get(run['status'], run['status'])} "
                        f"({run['started_at']})")
        lines.append(f"{idx}. “{wf.name}” (id {wf.id}) — " + "; ".join(bits))
    if len(rows) > LIST_MAX:
        lines.append(f"… and {len(rows) - LIST_MAX} more; the Workbench lists them all.")
    return {"response": "\n".join(lines), "exit_code": 0}


def _show(db, owner, wf) -> Dict:
    from src import workflow_store as store
    from src.workflow_document import (DISABLED_KEY, destination_lines, port_words,
                                       unchecked_refusal)
    from src.workflow_effects import KIND_WORDS, workflow_resources
    graph = store.stored_graph(wf)
    trigger = store.trigger_of(db, wf)
    nodes = store.nodes_of(graph)
    by_id = {str(n.get("id")): n for n in nodes}
    head = f"“{wf.name}” (id {wf.id}"
    if trigger is not None:
        head += f", its start is task {trigger.id}"
    head += f") — {_on_off(trigger)}, version {wf.version}."
    if trigger is not None:
        head += f" It starts {start_words(trigger)}."
    else:
        head += " " + store.LOST_TRIGGER
    lines = [head]
    if not nodes:
        lines.append("It has no steps yet.")
    else:
        lines.append(f"Steps ({len(nodes)}), as listed:")
    edges = [e for e in graph.get("edges") or () if isinstance(e, dict)]
    for idx, node in enumerate(nodes, 1):
        node_id = str(node.get("id"))
        kind = node.get("kind")
        line = f"{idx}. “{node.get('label') or node_id}” (step {node_id}) — {KIND_WORDS.get(kind, kind)}"
        if node.get(DISABLED_KEY) is True:
            line += "; switched off in this workflow"
        after = []
        for edge in edges:
            if str(edge.get("from")) != node_id:
                continue
            target = by_id.get(str(edge.get("to")))
            name = (target.get("label") or target.get("id")) if target else edge.get("to")
            after.append(f"“{name}” {port_words(node, str(edge.get('port') or ''))}")
        if after:
            line += "; then " + ", ".join(after)
        lines.append(line)
    marks = unchecked_refusal(graph)
    if marks is not None:
        lines.append(marks.sentence + " A person checks each step in the Workbench "
                     f"(Automations → “{wf.name}”).")
    sends = destination_lines(graph, workflow_resources(wf.owner))
    if sends:
        lines.append("Where it sends things: " + " ".join(sends))
    return {"response": "\n".join(lines), "workflow_id": wf.id, "exit_code": 0}


def _runs(db, owner, wf, limit) -> Dict:
    from core.database import TaskRun
    from routes.workflow.workflow_routes import _failed_step
    from src import workflow_store as store
    from src.task_scheduler import is_dry_run, is_test_run
    from src.workflow_runs import records_cleared_sentence, run_node_records
    try:
        limit = int(limit) if limit is not None else RUNS_DEFAULT
    except (TypeError, ValueError):
        limit = RUNS_DEFAULT
    limit = max(1, min(RUNS_MAX, limit))
    runs = (db.query(TaskRun).filter(TaskRun.task_id == wf.task_id)
            .order_by(TaskRun.started_at.desc(), TaskRun.id.desc()).limit(limit).all()
            if wf.task_id else [])
    if not runs:
        return {"response": f"“{wf.name}” has not run yet.", "workflow_id": wf.id,
                "exit_code": 0}
    lines = [f"The last {len(runs)} runs of “{wf.name}”, newest first:" if len(runs) > 1
             else f"The last run of “{wf.name}”:"]
    for run in runs:
        if is_dry_run(run):
            lines.append(f"- run {run.id}: a dry run, {_when(run.started_at)} — nothing ran.")
            continue
        head = (f"- run {run.id}: {_RUN_WORDS.get(run.status, run.status or 'unknown')}, "
                f"{_when(run.started_at)}")
        if is_test_run(run):
            head += " (test run)"
        recs = [r for r in run_node_records(db, run.id) if not r.dry]
        version = next((r.workflow_version for r in recs if r.workflow_version is not None), None)
        graph, kept = store.graph_of_version(db, wf, version)
        failed = _failed_step(run, graph, kept, recs)
        if failed:
            head += f". It failed at “{failed['label']}” (step {failed['node_id']})"
        elif run.status == "error" and run.error:
            head += f". {str(run.error)[:STEP_ERROR_SHOWN_MAX]}"
        lines.append(head + ".")
        if not recs and store.records_were_cleared(run):
            lines.append(f"  {records_cleared_sentence()}")
        for rec in recs[:RUN_STEP_LINES_MAX]:
            step = f"  · “{rec.label or rec.node_id}” (step {rec.node_id})"
            if rec.item is not None:
                step += f", item {rec.item}"
            if (rec.attempt or 1) > 1:
                step += f", try {rec.attempt}"
            step += f" — {rec.status}"
            if rec.error:
                step += f": {' '.join(str(rec.error).split())[:STEP_ERROR_SHOWN_MAX]}"
            lines.append(step)
        if len(recs) > RUN_STEP_LINES_MAX:
            lines.append(f"  … and {len(recs) - RUN_STEP_LINES_MAX} more step records.")
    return {"response": "\n".join(lines), "workflow_id": wf.id, "exit_code": 0}


def _what_to_explain(db, wf, run_id, node_id) -> tuple:
    """The run and step `explain` reads: the ones named, or the newest failed
    real run and the step it failed on (the Runs view's own `failed`)."""
    from core.database import TaskRun
    from routes.workflow.workflow_routes import _failed_step
    from src import workflow_store as store
    from src.task_scheduler import real_run_clause
    from src.workflow_runs import run_node_records
    from src.workflow_store import WorkflowRefused
    if not wf.task_id:
        raise WorkflowRefused(400, store.LOST_TRIGGER)
    q = db.query(TaskRun).filter(TaskRun.task_id == wf.task_id)
    if run_id:
        run = q.filter(TaskRun.id == str(run_id)).first()
        if run is None:
            raise WorkflowRefused(404, "No such run of this workflow.")
    else:
        run = (q.filter(TaskRun.status == "error", real_run_clause(TaskRun))
               .order_by(TaskRun.started_at.desc(), TaskRun.id.desc()).first())
        if run is None:
            raise WorkflowRefused(404, f"“{wf.name}” has no failed run to explain.")
    if node_id:
        return run.id, str(node_id)
    recs = [r for r in run_node_records(db, run.id) if not r.dry]
    version = next((r.workflow_version for r in recs if r.workflow_version is not None), None)
    graph, kept = store.graph_of_version(db, wf, version)
    failed = _failed_step(run, graph, kept, recs)
    if failed is None:
        raise WorkflowRefused(404, f"Run {run.id} of “{wf.name}” has no failed step to explain; "
                                   f"name one with node_id.")
    return run.id, failed["node_id"]


def _explained_words(wf, run_id, step, answer) -> str:
    """The Workbench's *Why did this fail?* panel, in a sentence or few."""
    label = step.node.get("label") or step.node.get("id") or "the step"
    said = f"Why “{label}” failed in run {run_id}"
    if answer.get("model"):
        said += f" (asked: {answer['model']})"
    said += f": {answer.get('why') or 'It gave no reason.'}"
    if answer.get("changed_since_run"):
        said += " This step has changed since this run; a change below is to the step as it is now."
    changes = (answer.get("proposal") or {}).get("changes") or []
    if changes:
        rows = [f"{c.get('words') or c.get('field') or 'a setting'} from "
                f"{json.dumps(c.get('before'), ensure_ascii=False)} to "
                f"{json.dumps(c.get('after'), ensure_ascii=False)}" for c in changes]
        said += (" What it would change: " + "; ".join(rows) + ". A person applies it in the "
                 f"Workbench (Automations → “{wf.name}”, the step's Why did this fail? → Apply).")
    else:
        said += " It proposes no change that can be applied."
    if answer.get("left_out"):
        # Each `left_out` sentence is the person's already ("That is yours to
        # decide"), written for the panel; said here as it is, after a lead.
        said += " Not in the change: " + " ".join(str(x) for x in answer["left_out"])
    return said + " A suggestion — the run's record may hold text someone else wrote."


def _export(db, owner, wf) -> Dict:
    from src import workflow_share
    from src import workflow_store as store
    data = workflow_share.export_file(db, wf, store.trigger_of(db, wf))
    name = workflow_share.file_name(wf.name)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if len(text) > EXPORT_SHOWN_MAX:
        said = (f"“{wf.name}” as a file ({name}) is {len(text):,} characters, more than a reply "
                f"carries. Export in the Workbench (Automations → “{wf.name}”) downloads it.")
    else:
        said = (f"“{wf.name}” as a file, {name}. No webhook token, key, base URL, header value "
                f"or endpoint address is in it.\n{text}")
    return {"response": said, "file_name": name, "workflow_id": wf.id, "exit_code": 0}


def _test_run_check(db, owner, ref) -> Dict:
    """`B1852`'s gates, asked before the scheduler is: the owner, the marks
    (a test run of a marked workflow would end before its first step — the
    walker asks them), the admin rule. Answers the run's facts or a refusal."""
    from src import workflow_store as store
    from src.task_action_policy import (admin_only_action_of, admin_refusal_message,
                                        owner_has_admin_task_privileges)
    from src.workflow_document import unchecked_refusal
    wf = _find(db, owner, ref)
    trigger = store.require_trigger(db, wf)
    marks = unchecked_refusal(store.stored_graph(wf))
    if marks is not None:
        return {"error": (f"“{wf.name}” was not tested. {marks.sentence} A person checks each "
                          f"step in the Workbench (Automations → “{wf.name}”); dry_run says "
                          f"what it would do meanwhile."), "workflow_id": wf.id, "exit_code": 1}
    found = admin_only_action_of(db, trigger)
    if found and not owner_has_admin_task_privileges(owner):
        return {"error": admin_refusal_message(found), "workflow_id": wf.id, "exit_code": 1}
    return {"wf_id": wf.id, "name": wf.name, "task_id": trigger.id,
            "on": (trigger.status or "active") == "active"}


async def do_manage_workflows(content: str, owner: Optional[str] = None) -> Dict:
    """`B1878`. list | show | runs | explain | dry_run | test_run | export."""
    from core.database import SessionLocal
    from src.tool_utils import _parse_tool_args
    from src.workflow_store import WorkflowRefused

    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}
    action = str(args.get("action") or "list").strip().lower().replace("-", "_")
    ref = args.get("workflow_id") or args.get("id") or args.get("name") or args.get("workflow")
    person = _person_only(action)
    if person is not None:
        return {"error": person, "exit_code": 1}
    if action not in MANAGE_WORKFLOWS_ACTIONS:
        return {"error": (f"Unknown action: {action}. manage_workflows reads, tests and explains "
                          f"workflows: " + ", ".join(MANAGE_WORKFLOWS_ACTIONS) + "."),
                "exit_code": 1}

    def read(fn, *extra):
        db = SessionLocal()
        try:
            if fn is _list:
                return _list(db, owner)
            return fn(db, owner, _find(db, owner, ref), *extra)
        finally:
            db.close()

    try:
        if action == "list":
            return await asyncio.to_thread(read, _list)
        if action == "show":
            return await asyncio.to_thread(read, _show)
        if action == "runs":
            return await asyncio.to_thread(read, _runs, args.get("limit"))
        if action == "export":
            return await asyncio.to_thread(read, _export)
        if action == "explain":
            return await _explain(owner, ref, args)
        if action == "dry_run":
            return await _dry_run(owner, ref)
        return await _test_run(owner, ref)
    except WorkflowRefused as refused:
        return {"error": refused.sentence, "exit_code": 1}


async def _explain(owner, ref, args) -> Dict:
    from core.database import SessionLocal
    from src import workflow_assist
    from src.workflow_store import WorkflowRefused
    item = args.get("item")
    if item is not None and (isinstance(item, bool) or not isinstance(item, int)):
        return {"error": "item must be a whole number.", "exit_code": 1}

    def read():
        db = SessionLocal()
        try:
            wf = _find(db, owner, ref)
            run_id, node_id = _what_to_explain(db, wf, args.get("run_id"), args.get("node_id"))
            return wf, run_id, workflow_assist.step_to_explain(db, wf, run_id, node_id, item)
        finally:
            db.close()
    wf, run_id, step = await asyncio.to_thread(read)
    try:
        answer = await workflow_assist.explain_answer(step)
    except WorkflowRefused as refused:
        if refused.status != 503:
            raise
        # The Workbench's sentence points at the error shown above it; here
        # there is no "above", so the step's own error is said instead.
        own = " ".join(str(step.record.get("error") or "").split())[:STEP_ERROR_SHOWN_MAX]
        return {"error": ("No model is set up to explain this (the utility or the default "
                          "model). " + (f"The step's own error: {own}" if own else
                                        "The step recorded no error.")),
                "workflow_id": wf.id, "exit_code": 1}
    return {"response": _explained_words(wf, run_id, step, answer), "workflow_id": wf.id,
            "run_id": run_id, "exit_code": 0}


async def _dry_run(owner, ref) -> Dict:
    """`manage_tasks dry_run` on the workflow's start — the one dry run
    (`P8-33`, `P22-04`), not a second (`Law 14`)."""
    from core.database import SessionLocal
    from src import workflow_store as store
    from src.tools.system import do_manage_tasks

    def read():
        db = SessionLocal()
        try:
            wf = _find(db, owner, ref)
            trigger = store.require_trigger(db, wf)
            return wf.id, wf.name, trigger.id, trigger.name
        finally:
            db.close()
    wf_id, wf_name, task_id, task_name = await asyncio.to_thread(read)
    said = await do_manage_tasks(json.dumps({"action": "dry_run", "task_id": task_id}),
                                 owner=owner)
    lead = f"Task '{task_name}': "
    if str(said.get("response") or "").startswith(lead):
        said["response"] = f"“{wf_name}”: " + said["response"][len(lead):]
    said["workflow_id"] = wf_id
    return said


async def _test_run(owner, ref) -> Dict:
    """The Workbench's *Test run* (`POST /api/workflows/{id}/test-run`,
    `B1852`): the saved version, once, even while it is switched off, through
    `run_task_now(test=True)` — it moves nothing about when it runs."""
    import uuid
    from core.database import SessionLocal
    from src.event_bus import get_task_scheduler
    from src.interactive_gate import tool_call_started_by

    def check():
        db = SessionLocal()
        try:
            return _test_run_check(db, owner, ref)
        finally:
            db.close()
    found = await asyncio.to_thread(check)
    if "error" in found:
        return found
    scheduler = get_task_scheduler()
    if not scheduler:
        return {"error": "Task scheduler not available", "exit_code": 1}
    run_id = str(uuid.uuid4())
    started = await scheduler.run_task_now(found["task_id"], started_by=tool_call_started_by(),
                                           test=True, run_id=run_id)
    if not started:
        return {"error": scheduler.in_flight_sentence(found["task_id"]) or "Task is already running",
                "workflow_id": found["wf_id"], "exit_code": 1}
    said = f"Test run of “{found['name']}” started: the saved version, once."
    if not found["on"]:
        said += " The workflow stays switched off."
    said += " runs says what each step did."
    return {"response": said, "run_id": run_id, "workflow_id": found["wf_id"], "exit_code": 0}
