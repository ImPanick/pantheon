# SPDX-License-Identifier: AGPL-3.0-or-later
"""A workflow's document, its versions and its trigger, kept together. `P22-05`, `P22-06`.

`D-2026-10-01-05` §1: a workflow is one named, versioned document started by one
`ScheduledTask` (`task_type="workflow"`). The engine (`src/workflow_document.py`,
`src/task_scheduler.py`) decides what a document may be and how it runs; this
module is the half that keeps it — create, save, the version policy, restore,
the On/Off switch, and turning a chain into a document and back (`P22-06`) —
so the HTTP routes (`routes/workflow/workflow_routes.py`), the task routes'
guards and `manage_tasks` all ask one place (`Law 7`).

**The version policy is `P8-10`'s, not a second one** (`services/memory/skills.py`):

  * a version is written only when the content moves — `content_fingerprint`,
    which leaves out where a step sits and any sample pinned on it, so moving a
    step or pinning a sample never makes one;
  * twenty are kept (`MAX_KEPT_VERSIONS`, imported), the oldest pruned, never
    the current one — one row per content version, the current one included, so
    a run can be drawn on the exact graph it ran;
  * a restore writes a NEW version (`source="restored"`); history is linear and
    nothing is lost;
  * "no such workflow" and "no edits yet" are different answers.

**Nothing here is deleted by a conversion or a switch** (`P22-06`, `Law 1`).
Converting a chain copies it into a document and leaves every task where it is;
switching the workflow on pauses the chain's first step so the two do not both
run, and *Put the old chain back* resumes it and switches the workflow off.

The engine's names (`C1` in `/work/notes/SLICE-B-DESIGN.md` § 7) are imported
inside the functions that use them, as the rest of this tree imports the
scheduler, so importing this module costs nothing at app start.

Every refusal is a `WorkflowRefused` carrying the status and the sentence a
person reads; the routes answer it as `{detail: sentence}` (`Law 15`).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Naive UTC, matching every other task column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── what a person is told ────────────────────────────────────────────────────
#
# One sentence per refusal, said once and read by the HTTP routes, the task
# routes' guards and `manage_tasks` alike, so the three doors cannot word the
# same rule three ways (`Law 7`).

WORKFLOW_MADE_IN_WORKBENCH = "A workflow is made in the Workbench (Automations → New workflow)."
NO_SUCH_WORKFLOW = "No such workflow."
LOST_TRIGGER = ("This workflow has lost the task that starts it, so it cannot run. "
                "Delete it and make it again.")

# The words a new workflow is called before it is named, and what a converted
# chain's workflow is called after its first step (design § 6.5).
NEW_WORKFLOW_NAME = "New workflow"
CONVERTED_SUFFIX = " (workflow)"
WORKFLOW_NAME_MAX = 200

# `workflow_versions.source` — stored values, written once, in the engine
# (`workflow_document.VERSION_SOURCE_*` / `WORKFLOW_VERSION_SOURCES`,
# `FORBIDDEN.md` Part 1), and imported where a version is written (`Law 7`;
# closed at the wave C merge — this module had its own three until then).

# What a `PUT /api/workflows/{id}` did, as the reply's `saved` (`Law 10`: an
# enum, never a boolean a reader can take two ways).
SAVED_NEW_VERSION = "new_version"
SAVED_UNCHANGED = "unchanged"
SAVED_POSITIONS = "positions"
SAVED_PINS = "pins"
# `P22-19`. A person said these steps look right: marks cleared, never a version.
SAVED_CHECKED = "checked"

# `P22-19` / `P22-20` (`SLICE-EF-DESIGN` § 1.1, § 2). Said where a door is a
# person's only (`auth_helpers.request_is_a_person`, `B1005`): an API token is
# held by something else and the assistant's loopback is the assistant. The
# `app_api` blocklist cannot see a request body, so these are enforced by the
# routes asking that helper, with these sentences.
ONLY_A_PERSON_CHECKS = ("Only you can say a step looks right, from the Workbench — not an API "
                        "token and not your assistant.")
ONLY_A_PERSON_FIXES = ("Only you can apply a fix, from the Workbench — not an API token and not "
                       "your assistant.")

# `P22-19` (§ 1.2). What a drafted or imported start falls back to, said: the
# trigger is off, so a wrong guess runs nothing.
START_LEFT_AT_DEFAULT = "When it starts was left at daily 09:00 — set it on the start."

# The columns of a chain's first step that say when it runs — what a converted
# workflow's trigger takes from it — are the engine's `TRIGGER_FIELDS`,
# imported in `convert_chain` and used there as an allowlist, so whatever else
# `chain_to_document` hands back can never reach a row unasked (an `id`, an
# `owner`, a `status`). One list (`Law 7`; this module had its own copy of the
# twelve until the wave C merge).


def quoted(name) -> str:
    return f"“{name or 'Untitled'}”"


def trigger_type_is_fixed(task_name, workflow_name) -> str:
    return (f"{quoted(task_name)} starts the workflow {quoted(workflow_name)}, so it stays "
            f"a workflow's start. Change the workflow in the Workbench.")


def trigger_is_renamed_with_its_workflow(task_name, workflow_name) -> str:
    return (f"{quoted(task_name)} starts the workflow {quoted(workflow_name)} and is called "
            f"what the workflow is called. Rename the workflow in the Workbench.")


def trigger_is_deleted_with_its_workflow(task_name, workflow_name) -> str:
    return (f"{quoted(task_name)} starts the workflow {quoted(workflow_name)}. Delete the "
            f"workflow in the Workbench, and this goes with it.")


class WorkflowRefused(Exception):
    """A refusal a person reads.

    `status` is the HTTP status the routes answer with; `sentence` is the whole
    answer. A refusal of a document also carries the engine's `reason` and the
    steps it names (`DocumentRefusal.reason` / `.node_ids`), added beside the
    sentence so the canvas can mark the step and tell a refusal its own edit
    caused from one the draft already had (`workflowSource.js:connect`).
    """

    def __init__(self, status: int, sentence: str, *, reason: str | None = None,
                 node_ids=(), field: str = ""):
        super().__init__(sentence)
        self.status = int(status)
        self.sentence = sentence
        self.reason = reason
        self.node_ids = tuple(node_ids or ())
        # `P22-09` (`C-W`). The setting a refusal is about — `DocumentRefusal.field`,
        # e.g. "path" or "args.channel" — so the panel puts the sentence on
        # that field. Empty when the refusal is about the step or the whole.
        self.field = field or ""

    def body(self) -> dict:
        out = {"detail": self.sentence}
        if self.reason is not None:
            out["reason"] = self.reason
            out["node_ids"] = list(self.node_ids)
            out["field"] = self.field
        return out


# ── reading ──────────────────────────────────────────────────────────────────

def _models():
    from core.database import ScheduledTask, TaskRun, Workflow, WorkflowVersion
    return ScheduledTask, TaskRun, Workflow, WorkflowVersion


def stored_graph(wf) -> dict:
    """The document as stored. It was validated when it was written; a row a
    hand edit broke reads as the empty document (the engine's `empty_graph`)
    rather than taking every list down, and the next save or run says what is
    wrong with it."""
    from src.workflow_document import empty_graph
    try:
        graph = json.loads(wf.graph or "")
    except (TypeError, ValueError):
        logger.warning("Workflow %s has an unreadable document", getattr(wf, "id", "?"))
        return empty_graph()
    return graph if isinstance(graph, dict) else empty_graph()


def stored_chain(wf) -> dict | None:
    """`P22-06`. Where a converted workflow came from, or None."""
    raw = getattr(wf, "source_chain", None)
    if not raw:
        return None
    try:
        chain = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return chain if isinstance(chain, dict) and chain.get("head_task_id") else None


def nodes_of(graph) -> list:
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    return [n for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else []


def owned_workflow(db, workflow_id: str, owner: str | None):
    """The workflow, if `owner` may see it. Another owner's id is a 404, never
    a 403: whether it exists is not theirs to learn either."""
    _, _, Workflow, _ = _models()
    q = db.query(Workflow).filter(Workflow.id == str(workflow_id or ""))
    if owner:
        q = q.filter(Workflow.owner == owner)
    wf = q.first()
    if wf is None:
        raise WorkflowRefused(404, NO_SUCH_WORKFLOW)
    return wf


def trigger_of(db, wf):
    ScheduledTask, _, _, _ = _models()
    if not wf.task_id:
        return None
    return db.query(ScheduledTask).filter(ScheduledTask.id == wf.task_id).first()


def require_trigger(db, wf):
    trigger = trigger_of(db, wf)
    if trigger is None:
        raise WorkflowRefused(400, LOST_TRIGGER)
    return trigger


def workflow_ids_for(db, task_ids) -> dict:
    """`{trigger task id: workflow id}` for these tasks, in one query.

    Asked only for rows whose `task_type` is `workflow`, so a list of tasks with
    no workflow among them costs no query at all.
    """
    ids = [i for i in dict.fromkeys(task_ids or ()) if i]
    if not ids:
        return {}
    _, _, Workflow, _ = _models()
    out = {}
    for start in range(0, len(ids), 500):
        for task_id, wf_id in (db.query(Workflow.task_id, Workflow.id)
                               .filter(Workflow.task_id.in_(ids[start:start + 500])).all()):
            out[task_id] = wf_id
    return out


def workflow_for_task(db, task_id: str):
    _, _, Workflow, _ = _models()
    return db.query(Workflow).filter(Workflow.task_id == task_id).first()


def _iso(value):
    return value.isoformat() + "Z" if value else None


def last_real_runs(db, task_ids) -> dict:
    """`{task id: {id, status, started_at, finished_at, dry}}` — each task's
    newest run that is not a dry run, in one query per 500 tasks.

    `B1054`'s rule, asked through its own SQL condition (`real_run_clause`): a
    dry run is never a last run, so a workflow whose last real run failed does
    not read as "Dry run" after *Show me what this would do*. `dry` is on the
    shape because `C2` puts it there; by that rule it is always false. Its own
    query rather than `latest_real_runs`, which answers `(status, result,
    error)` for the Tasks list and not the run's id and times the shelf needs.
    """
    from sqlalchemy import and_, func
    from src.task_scheduler import real_run_clause
    _, TaskRun, _, _ = _models()
    ids = [i for i in dict.fromkeys(task_ids or ()) if i]
    found = {}
    real = real_run_clause(TaskRun)
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        newest = (db.query(TaskRun.task_id.label("task_id"),
                           func.max(TaskRun.started_at).label("at"))
                  .filter(TaskRun.task_id.in_(chunk), real)
                  .group_by(TaskRun.task_id).subquery())
        rows = (db.query(TaskRun.task_id, TaskRun.id, TaskRun.status,
                         TaskRun.started_at, TaskRun.finished_at)
                .join(newest, and_(TaskRun.task_id == newest.c.task_id,
                                   TaskRun.started_at == newest.c.at))
                .filter(real)
                .order_by(TaskRun.task_id, TaskRun.id.desc()).all())
        for task_id, run_id, status, started, finished in rows:
            found.setdefault(task_id, {"id": run_id, "status": status,
                                       "started_at": _iso(started),
                                       "finished_at": _iso(finished), "dry": False})
    return found


def summaries(db, workflows, *, name_of=None) -> list:
    """The shelf's rows (`C2` *Summary*), for many workflows in a fixed number
    of queries — their triggers, their last real runs and the chains they were
    made from, each read once for the whole list (`B1043`'s lesson: a list
    that asks per row grows a query per row).
    """
    ScheduledTask = _models()[0]
    name_of = name_of or (lambda task: task.name)
    workflows = list(workflows)
    chains = {wf.id: stored_chain(wf) for wf in workflows}
    wanted = {wf.task_id for wf in workflows if wf.task_id}
    wanted |= {c["head_task_id"] for c in chains.values() if c}
    tasks = {}
    ids = [i for i in wanted if i]
    for start in range(0, len(ids), 500):
        for task in db.query(ScheduledTask).filter(ScheduledTask.id.in_(ids[start:start + 500])).all():
            tasks[task.id] = task
    last = last_real_runs(db, [wf.task_id for wf in workflows if wf.task_id])
    return [summary(wf, tasks.get(wf.task_id), last.get(wf.task_id),
                    chains[wf.id], tasks, name_of=name_of)
            for wf in workflows]


def summary_of(db, wf, *, name_of=None) -> dict:
    """One workflow's *Summary* — `summaries` of a list of one."""
    return summaries(db, [wf], name_of=name_of)[0]


def summary(wf, trigger, last_run, chain, tasks, *, name_of) -> dict:
    """One `C2` *Summary*, from rows the caller already holds."""
    converted = None
    if chain:
        head = tasks.get(chain["head_task_id"])
        converted = {
            "head_task_id": chain["head_task_id"],
            "head_name": name_of(head) if head is not None else None,
            # A task status, or "deleted" when the step is gone since.
            "head_status": (head.status or "active") if head is not None else "deleted",
        }
    return {
        "id": wf.id,
        "name": wf.name,
        "task_id": wf.task_id,
        "trigger_status": trigger.status if trigger is not None else None,
        "version": wf.version,
        "step_count": len(nodes_of(stored_graph(wf))),
        "last_run": last_run,
        "converted_from": converted,
        "updated_at": _iso(getattr(wf, "updated_at", None)),
    }


def is_running(db, scheduler, task_id: str) -> bool:
    """Is a run of this trigger in flight: the scheduler's own claim (`B674`),
    or a run row that has not finished — a queued run holds no claim yet, and
    (`P22-11`) a parked one holds none either — `workflow_runs.run_in_flight`,
    the one question."""
    from src.workflow_runs import run_in_flight
    if task_id in (getattr(scheduler, "_executing", None) or ()):
        return True
    return run_in_flight(db, task_id) is not None


def owner_rows(db, owner: str | None) -> tuple:
    """`(tasks_by_id, crew_ids)` — what `validate_document` checks a run-task
    target and a crew member against: this owner's, and nobody else's."""
    from core.database import CrewMember
    ScheduledTask, _, _, _ = _models()
    q = db.query(ScheduledTask)
    c = db.query(CrewMember.id)
    if owner:
        q = q.filter(ScheduledTask.owner == owner)
        c = c.filter(CrewMember.owner == owner)
    return {t.id: t for t in q.all()}, {row[0] for row in c.all()}


# ── checking a document ──────────────────────────────────────────────────────

def refusal_from(refusal, status: int = 400) -> WorkflowRefused:
    """A `DocumentRefusal` as the refusal a person reads."""
    return WorkflowRefused(status, getattr(refusal, "sentence", None) or str(refusal),
                           reason=getattr(refusal, "reason", None),
                           node_ids=getattr(refusal, "node_ids", None) or (),
                           field=getattr(refusal, "field", "") or "")


def _document_error_refusal(err) -> WorkflowRefused:
    refusal = getattr(err, "refusal", None)
    if refusal is None and err.args:
        refusal = err.args[0]
    if refusal is None or isinstance(refusal, str):
        return WorkflowRefused(400, str(refusal or err) or "This workflow could not be read.")
    return refusal_from(refusal)


def first_admin_only_action(graph) -> str | None:
    """The first action step whose action only an admin may schedule.

    `ADMIN_ONLY_TASK_ACTIONS`, asked through the same policy function the task
    routes ask (`is_admin_only_task_action`), so a step is refused exactly
    where a task with that action is. The policy's own walk
    (`task_action_policy.admin_only_action_in`), so the step a For-each repeats
    is asked too — the run's door asks the same (`integrate-d`: this read
    top-level steps only). An HTTP or MCP step is the rule's to refuse at save
    (`admin_only`, said on the step).
    """
    from src.task_action_policy import admin_only_action_in
    return admin_only_action_in(graph)


def check_document(db, graph, *, owner: str | None, own_task_id: str | None,
                   rows=None, resources=None) -> dict:
    """Parse and validate a document exactly as a save does. Returns it parsed.

    The order is the task routes': an action only an admin may schedule is a
    403 with the routes' own sentence (`admin_refusal_message`), then the
    engine's one rule (`validate_document` — the sentence a run would write,
    `Law 10`). Writes nothing.

    `resources` (`P22-24`): what the steps are checked against, when it is not
    what the owner can reach right now — only a file's import passes it, with
    stand-ins for what this install is missing (`workflow_share`), so every
    OTHER rule is asked while a missing Integration does not block it.
    """
    from src.task_action_policy import admin_refusal_message, owner_has_admin_task_privileges
    from src.workflow_document import DocumentError, parse_graph, validate_document

    raw = graph if isinstance(graph, str) else json.dumps(graph)
    try:
        parsed = parse_graph(raw)
    except DocumentError as err:
        raise _document_error_refusal(err) from None
    is_admin = owner_has_admin_task_privileges(owner)
    action = first_admin_only_action(parsed)
    if action and not is_admin:
        raise WorkflowRefused(403, admin_refusal_message(action))
    tasks_by_id, crew_ids = rows if rows is not None else owner_rows(db, owner)
    # `P22-09`…`P22-18`. Checked against what the owner can reach right now —
    # integrations, MCP tools, skills, the workstation (`WorkflowResources`,
    # `wf-effects`' `workflow_resources`) — exactly as the walker checks it at
    # run, so a refusal is the same sentence on the same field at both.
    if resources is None:
        from src.workflow_effects import workflow_resources
        resources = workflow_resources(owner)
    refusal = validate_document(parsed, owner=owner, tasks_by_id=tasks_by_id,
                                crew_ids=crew_ids, owner_is_admin=is_admin,
                                own_task_id=own_task_id, resources=resources)
    if refusal is not None:
        raise refusal_from(refusal)
    return parsed


# ── names ────────────────────────────────────────────────────────────────────

def clean_name(name, *, required: bool = True) -> str | None:
    text = " ".join(str(name or "").split())
    if not text:
        if required:
            raise WorkflowRefused(400, "A workflow needs a name.")
        return None
    if len(text) > WORKFLOW_NAME_MAX:
        raise WorkflowRefused(
            400, f"A workflow's name can be at most {WORKFLOW_NAME_MAX} characters.")
    return text


# ── versions ─────────────────────────────────────────────────────────────────

def _write_version(db, wf, graph: dict, *, source: str) -> None:
    """The row for `wf.version`, then the oldest beyond the twenty pruned.

    `P22-19`: the engine's `version_graph` — no pins and no `unchecked` marks —
    so a kept version never carries a mark and a restore never brings one back.
    """
    from src.workflow_document import content_fingerprint, version_graph
    _, _, _, WorkflowVersion = _models()
    db.add(WorkflowVersion(
        id=str(uuid.uuid4()), workflow_id=wf.id, version=wf.version, name=wf.name,
        graph=json.dumps(version_graph(graph)),
        fingerprint=content_fingerprint(wf.name, graph),
        source=source, created_at=_utcnow()))
    db.flush()
    prune_versions(db, wf)


def prune_versions(db, wf) -> int:
    """Keep the newest `MAX_KEPT_VERSIONS` rows and never the current one out.

    `P8-10`'s number, imported rather than typed again: a workflow's history and
    a skill's are one policy (`Law 7`). The import is a module the running app
    has already loaded (the skills manager), so it costs nothing here.
    """
    from services.memory.skills import MAX_KEPT_VERSIONS
    _, _, _, WorkflowVersion = _models()
    rows = (db.query(WorkflowVersion.id, WorkflowVersion.version)
            .filter(WorkflowVersion.workflow_id == wf.id)
            .order_by(WorkflowVersion.version.desc()).all())
    doomed = [vid for vid, version in rows[MAX_KEPT_VERSIONS:] if version != wf.version]
    if doomed:
        db.query(WorkflowVersion).filter(WorkflowVersion.id.in_(doomed)).delete(
            synchronize_session=False)
    return len(doomed)


def list_versions(db, wf) -> list:
    """Every kept version, newest first; the current one is marked."""
    _, _, _, WorkflowVersion = _models()
    out = []
    for row in (db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == wf.id)
                .order_by(WorkflowVersion.version.desc()).all()):
        out.append(version_summary(row, current=wf.version))
    return out


def version_summary(row, *, current: int) -> dict:
    try:
        graph = json.loads(row.graph or "")
    except (TypeError, ValueError):
        graph = {}
    return {
        "version": row.version,
        "name": row.name,
        "saved_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "source": row.source,
        "step_count": len(nodes_of(graph)),
        "current": row.version == current,
    }


def kept_version(db, wf, version):
    """One kept version's row. A version that was pruned and one that never
    existed are told apart, because "it is gone" and "there was no such thing"
    send a person to different places (`Law 10`)."""
    _, _, _, WorkflowVersion = _models()
    try:
        number = int(version)
    except (TypeError, ValueError):
        raise WorkflowRefused(404, "No such version.") from None
    row = (db.query(WorkflowVersion)
           .filter(WorkflowVersion.workflow_id == wf.id, WorkflowVersion.version == number)
           .first())
    if row is None:
        if 1 <= number <= (wf.version or 0):
            from services.memory.skills import MAX_KEPT_VERSIONS
            raise WorkflowRefused(
                404, f"Version {number} is no longer kept: a workflow keeps its last "
                     f"{MAX_KEPT_VERSIONS} versions.")
        raise WorkflowRefused(404, "No such version.")
    return row


def versions_kept(db, wf) -> int:
    _, _, _, WorkflowVersion = _models()
    return db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == wf.id).count()


def _stale(wf, base_version) -> None:
    if base_version is None or isinstance(base_version, bool):
        raise WorkflowRefused(
            400, "Say which version this change started from (base_version), so a "
                 "change made somewhere else since is not overwritten.")
    try:
        base = int(base_version)
    except (TypeError, ValueError):
        raise WorkflowRefused(400, "base_version must be a version number.") from None
    if base != wf.version:
        raise WorkflowRefused(
            409, f"This workflow was saved somewhere else since you opened it: it is at "
                 f"version {wf.version} and your change started from version {base}. "
                 f"Nothing was saved. Open it again to see the other change.")


def _commit_version(db, wf, graph, *, source, base) -> None:
    """Write and commit a new version, or answer the stale 409 if another save
    took the same number first.

    `_stale` reads the version before this save writes, so two saves from one
    `base_version` can both pass it; the second then breaks the version row's
    `(workflow_id, version)` key. That is the same fact `_stale` reports — the
    workflow moved on since this change started — and it is told the same way,
    not as a 500.
    """
    from sqlalchemy.exc import IntegrityError
    try:
        _write_version(db, wf, graph, source=source)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise WorkflowRefused(
            409, f"This workflow was saved somewhere else at the same moment, from the "
                 f"same version ({base}). Nothing was saved. Open it again to see the "
                 f"other change.") from None


def _pins_kept(graph: dict, before: dict) -> dict:
    """A content save keeps the samples pinned on the stored steps.

    Pins have their own door (`save_pins`) and never make a version, so the
    document a save sends cannot set or clear one: a step that still exists
    keeps its stored pin, a step that was removed takes it with it, and a new
    step starts without one.
    """
    pinned = {str(n.get("id")): n.get("pinned") for n in nodes_of(before)}
    out = dict(graph)
    out["nodes"] = [dict(n, pinned=pinned.get(str(n.get("id")))) for n in nodes_of(graph)]
    return out


def _step_content(node: dict) -> str:
    """What a person changes when they change a step: its kind, its name and
    its settings — `content_fingerprint`'s reading of one step, as text."""
    return json.dumps([node.get("kind"), node.get("label"), node.get("config") or {}],
                      sort_keys=True, default=str, ensure_ascii=False)


def _marks_kept(graph: dict, before: dict, *, by_person: bool) -> dict:
    """`P22-19` (`SLICE-EF-DESIGN` § 1.1). A content save, a restore or a fix
    keeps the `unchecked` marks on the stored steps — beside `_pins_kept`, and
    by the same rule that a save's body cannot set or clear one:

      * whatever mark the client sent is dropped — a save cannot set a mark,
        and cannot clear one by sending none;
      * a stored mark stays on a step whose kind, name and settings are
        unchanged (moving it, or pinning a sample, is not a change);
      * a step that was changed — or added — is decided by WHO changed it
        (`by_person`, the route's `request_is_a_person`):
          - a person's change makes the step theirs, and its mark goes;
          - anything else's change (the assistant through `app_api`, an API
            token) marks it `assistant`, even a step a person had checked.

    `integrate-e`, the integrator's call on wb-assist's `B-NEW-2`: a mark
    clears only by a person. Before, any change cleared it, so the assistant
    could touch each drafted step through `PUT /api/workflows/{id}` and then
    `manage_tasks resume` — the draft ran with nobody pressing *Looks right*.
    Saying "a person looked at this" without changing it is `check_steps`',
    which is a person's only too.
    """
    from src.workflow_document import ORIGIN_ASSISTANT, UNCHECKED_KEY
    stored = {}
    for node in nodes_of(before):
        stored[str(node.get("id"))] = (_step_content(node), node.get(UNCHECKED_KEY))
    at = None
    out = dict(graph)
    nodes = []
    for node in nodes_of(graph):
        node = {k: v for k, v in node.items() if k != UNCHECKED_KEY}
        kept = stored.get(str(node.get("id")))
        if kept is not None and kept[0] == _step_content(node):
            if isinstance(kept[1], dict):
                node[UNCHECKED_KEY] = kept[1]
        elif not by_person:
            at = at or _utcnow().isoformat() + "Z"
            node[UNCHECKED_KEY] = {"origin": ORIGIN_ASSISTANT, "at": at, "needs": []}
        nodes.append(node)
    out["nodes"] = nodes
    return out


def save_document(db, wf, trigger, *, name, graph, base_version, by_person: bool,
                  check: bool = False) -> str:
    """Save a content edit. A new version only if the content moved.

    `check=True` answers exactly what the save would — stale, refused or fine —
    and writes nothing (`PUT ?check=true`, which the canvas asks on each
    connect). `by_person` — whether a person is saving (`request_is_a_person`),
    which decides what a changed step's mark becomes (`_marks_kept`); required,
    so no door can leave it unsaid. Returns `SAVED_NEW_VERSION`,
    `SAVED_UNCHANGED` or `"check"`.
    """
    from src.workflow_document import content_fingerprint
    _stale(wf, base_version)
    new_name = clean_name(name) if name is not None else wf.name
    parsed = check_document(db, graph, owner=wf.owner, own_task_id=trigger.id if trigger else None)
    if check:
        return "check"
    before = stored_graph(wf)
    parsed = _marks_kept(_pins_kept(parsed, before), before, by_person=by_person)
    moved = content_fingerprint(new_name, parsed) != content_fingerprint(wf.name, before)
    # Where steps sit is saved either way: the draft knows where they are.
    wf.graph = json.dumps(parsed)
    if not moved:
        db.commit()
        return SAVED_UNCHANGED
    base = wf.version
    wf.version = (wf.version or 0) + 1
    wf.name = new_name
    if trigger is not None:
        # Kept equal on every save, so the Tasks window and Activity read the
        # workflow's name on its start (design § 1.1).
        trigger.name = new_name
    from src.workflow_document import VERSION_SOURCE_USER
    _commit_version(db, wf, parsed, source=VERSION_SOURCE_USER, base=base)
    return SAVED_NEW_VERSION


def restore_version(db, wf, trigger, version, *, base_version, by_person: bool) -> str:
    """Put a kept version back, as a NEW version (`source="restored"`).
    `by_person` as `save_document`'s: a step the restore changes is marked
    `assistant` unless a person restored it.

    Restoring the content that is already current writes nothing. The restored
    document is checked as a save is — a run-task step's target may have been
    deleted since, or the owner may no longer be an admin — so a restore cannot
    put back a document the engine would refuse to run.
    """
    from src.workflow_document import content_fingerprint
    _stale(wf, base_version)
    row = kept_version(db, wf, version)
    graph = json.loads(row.graph)
    parsed = check_document(db, graph, owner=wf.owner, own_task_id=trigger.id if trigger else None)
    before = stored_graph(wf)
    parsed = _marks_kept(_pins_kept(parsed, before), before, by_person=by_person)
    if content_fingerprint(row.name, parsed) == content_fingerprint(wf.name, before):
        return SAVED_UNCHANGED
    wf.graph = json.dumps(parsed)
    base = wf.version
    wf.version = (wf.version or 0) + 1
    wf.name = row.name
    if trigger is not None:
        trigger.name = row.name
    from src.workflow_document import VERSION_SOURCE_RESTORED
    _commit_version(db, wf, parsed, source=VERSION_SOURCE_RESTORED, base=base)
    return SAVED_NEW_VERSION


def save_fix(db, wf, trigger, *, node_id, config, base_version) -> str:
    """`P22-20`. *Apply*: one step's settings replaced by a fix, as a NEW
    version (`source="fixed"`). Undo is the restore door with the version this
    started from (`restore_version`, source `restored`) — nothing new.

    The fix rule is asked HERE, against the STORED step, whatever the client
    sends (`workflow_assist.fix_problem`: `FIX_FIELDS`, effects that do not
    grow, the whole document's rule) — so the browser is not trusted to send
    only what was proposed (`SLICE-EF-DESIGN` § 5.1). Then the save's own
    check, pins and marks kept (the step a person fixed is theirs now, so its
    mark goes, `_marks_kept`), and `_stale`'s 409. Who may apply it is the
    route's question (`ONLY_A_PERSON_FIXES`). Returns `SAVED_NEW_VERSION` or
    `SAVED_UNCHANGED`."""
    from src import workflow_assist
    from src.task_action_policy import owner_has_admin_task_privileges
    from src.workflow_document import (
        VERSION_SOURCE_FIXED, DocumentError, content_fingerprint, parse_graph,
    )
    from src.workflow_effects import workflow_resources
    _stale(wf, base_version)
    if not isinstance(config, dict):
        raise WorkflowRefused(400, "Send the step's settings (config), as the fix proposed them.")
    try:
        current = parse_graph(stored_graph(wf))
    except DocumentError as err:
        raise _document_error_refusal(err) from None
    node = next((n for n in nodes_of(current) if str(n.get("id")) == str(node_id)), None)
    if node is None:
        raise WorkflowRefused(404, "No such step in this workflow.")
    own = trigger.id if trigger is not None else None
    rows = owner_rows(db, wf.owner)
    resources = workflow_resources(wf.owner)
    after = dict(node, config=config)
    refused = workflow_assist.fix_problem(
        node, after, current, resources=resources, tasks_by_id=rows[0], crew_ids=rows[1],
        owner=wf.owner, owner_is_admin=owner_has_admin_task_privileges(wf.owner), own_task_id=own)
    if refused is not None:
        raise WorkflowRefused(400, refused.sentence, reason=refused.reason,
                              node_ids=(str(node_id),), field=refused.field)
    patched = dict(current)
    patched["nodes"] = [after if n is node else n for n in nodes_of(current)]
    parsed = check_document(db, patched, owner=wf.owner, own_task_id=own, rows=rows,
                            resources=resources)
    before = stored_graph(wf)
    # *Apply* is a person's only (the route's `ONLY_A_PERSON_FIXES`), so the
    # step they fixed is theirs.
    parsed = _marks_kept(_pins_kept(parsed, before), before, by_person=True)
    if content_fingerprint(wf.name, parsed) == content_fingerprint(wf.name, before):
        return SAVED_UNCHANGED
    wf.graph = json.dumps(parsed)
    base = wf.version
    wf.version = (wf.version or 0) + 1
    _commit_version(db, wf, parsed, source=VERSION_SOURCE_FIXED, base=base)
    return SAVED_NEW_VERSION


# ── positions and pins: saved by themselves, never a version ─────────────────

def _xy(value):
    if isinstance(value, dict):
        value = [value.get("x"), value.get("y")]
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    out = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        if v != v or v in (float("inf"), float("-inf")):
            return None
        out.append(round(float(v), 1))
    return out


def save_positions(db, wf, positions) -> str:
    """Where steps sit. `merge_positions` — the engine's — places them.

    A value of `null` forgets where that step was put, so the canvas lays it
    out again — the document's half of the canvas's *Tidy up*, which on the
    tasks canvas is a smaller preference (`workbench_positions`). Ids the saved
    document does not have (a step only in the person's unsaved draft) are
    left out: the draft keeps them, and its Save writes them.
    """
    from src.workflow_document import START_KEY, merge_positions
    if not isinstance(positions, dict):
        raise WorkflowRefused(
            400, f"positions must map a step's id (or “{START_KEY}”) to [x, y], or to null.")
    graph = stored_graph(wf)
    known = {str(n.get("id")) for n in nodes_of(graph)} | {START_KEY}
    placed, forgotten = {}, set()
    for key, value in positions.items():
        if value is None:
            forgotten.add(str(key))
            continue
        xy = _xy(value)
        if xy is None:
            raise WorkflowRefused(400, f"The position of “{key}” must be two numbers, [x, y], or null.")
        if str(key) in known:
            placed[str(key)] = xy
    for node in nodes_of(graph):
        if str(node.get("id")) in forgotten:
            node["position"] = None
    if START_KEY in forgotten and isinstance(graph.get(START_KEY), dict):
        graph[START_KEY]["position"] = None
    wf.graph = json.dumps(merge_positions(graph, placed))
    db.commit()
    return SAVED_POSITIONS


def save_pins(db, wf, trigger, pins) -> dict:
    """Pin (or, with `null`, unpin) a sample on steps. Returns what each pin
    dropped — the keys that step is never handed — so the person is told."""
    from src.workflow_document import DocumentError, build_pin
    if not isinstance(pins, dict) or not pins:
        raise WorkflowRefused(400, "pins must map a step's id to a sample, or to null to unpin it.")
    graph = stored_graph(wf)
    by_id = {str(n.get("id")): n for n in nodes_of(graph)}
    dropped = {}
    for node_id, data in pins.items():
        node = by_id.get(str(node_id))
        if node is None:
            raise WorkflowRefused(
                400, f"There is no step “{node_id}” in this workflow as saved. Save it first, then pin a sample.")
        if data is None:
            node["pinned"] = None
            continue
        try:
            # The engine refuses a sample for a step that is handed nothing (a
            # first step on a schedule) and one that is not an object, in its
            # own words — a 400 the person reads, never a 500.
            envelope, lost = build_pin(graph, str(node_id), trigger, data)
        except DocumentError as err:
            raise _document_error_refusal(err) from None
        node["pinned"] = envelope
        dropped[str(node_id)] = list(lost or ())
    wf.graph = json.dumps(graph)
    db.commit()
    return dropped


def check_steps(db, wf, node_ids) -> str:
    """`P22-19`. A person looked at these steps and says they look right: their
    `unchecked` marks are cleared. Never a version — a mark is not content, so
    the document a run would walk is the same before and after.

    Who may say it is the route's question (`request_is_a_person`,
    `ONLY_A_PERSON_CHECKS`); this is what it does. A step that has no mark is
    already checked, and naming it again changes nothing. Returns
    `SAVED_CHECKED`."""
    from src.workflow_document import UNCHECKED_KEY
    if (not isinstance(node_ids, list) or not node_ids
            or not all(isinstance(i, str) and i for i in node_ids)):
        raise WorkflowRefused(400, "checked must list the steps you looked at, by their ids.")
    graph = stored_graph(wf)
    by_id = {str(n.get("id")): n for n in nodes_of(graph)}
    for node_id in node_ids:
        if node_id not in by_id:
            raise WorkflowRefused(
                400, f"There is no step “{node_id}” in this workflow as saved. Nothing was checked.")
    for node_id in node_ids:
        by_id[node_id].pop(UNCHECKED_KEY, None)
    wf.graph = json.dumps(graph)
    db.commit()
    return SAVED_CHECKED


# ── create, convert, delete ──────────────────────────────────────────────────

def _new_trigger(*, owner, name, fields: dict):
    """The task that starts a workflow: created switched off (design § 8)."""
    import secrets
    ScheduledTask, _, _, _ = _models()
    task = ScheduledTask(
        id=str(uuid.uuid4()), owner=owner, name=name, task_type="workflow",
        trigger_type="schedule", schedule="daily", scheduled_time="09:00",
        trigger_counter=0, status="paused", next_run=None, run_count=0)
    for key, value in fields.items():
        setattr(task, key, value)
    if (task.trigger_type or "schedule") == "webhook":
        # A new address: a webhook URL is bound to its task's id, and this is a
        # new task — the cost `D-2026-10-01-05` §1 accepted, said out loud.
        task.webhook_token = secrets.token_urlsafe(32)
    return task


def create_workflow(db, *, owner, name=None):
    """A new, empty workflow, switched off. Returns `(wf, trigger, notes)`.
    Created from the engine's `empty_graph` WITHOUT validating it (an empty
    document is refused at save — `no_steps` — and this one is off)."""
    from src.workflow_document import VERSION_SOURCE_USER, empty_graph
    _, _, Workflow, _ = _models()
    name = clean_name(name, required=False) or NEW_WORKFLOW_NAME
    trigger = _new_trigger(owner=owner, name=name, fields={})
    db.add(trigger)
    db.flush()
    wf = Workflow(id=str(uuid.uuid4()), owner=owner, name=name, task_id=trigger.id,
                  graph=json.dumps(empty_graph()), version=1)
    db.add(wf)
    db.flush()
    _write_version(db, wf, empty_graph(), source=VERSION_SOURCE_USER)
    db.commit()
    return wf, trigger, [
        f"Made {quoted(name)}. It is switched off: it will not run until you switch it on."]


# `P22-19` / `P22-24`. The words a start may store, closed (`TRIGGER_FIELDS`'
# enums, as the task form offers them).
START_TRIGGER_TYPES = ("schedule", "event", "webhook")
START_SCHEDULES = ("once", "daily", "weekly", "monthly", "cron")
START_TRIGGER_COUNT_MAX = 1000


def _whole(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def clean_trigger_fields(fields) -> tuple:
    """`(fields, notes)` — a start the model drafted or a file carried, made
    into one this Pantheon can store (`SLICE-EF-DESIGN` § 1.2, step 1).

    Only `TRIGGER_FIELDS` (the engine's list, `Law 7`), and each one checked:
    the closed words for the kind of start and the schedule, an event this
    Pantheon fires (`EVENT_NAMES`), `HH:MM`, a day in range, a date, a cron
    expression `croniter` reads and the floor allows (`cron_floor_problem`), a
    time zone this machine knows (`valid_timezone`), and the task form's own
    bounds for retries and the time limit. When WHEN IT STARTS cannot be used,
    the whole start drops to the default (daily, 09:00) and that is said once;
    anything else that cannot be used is dropped and said. Nothing here is a
    control — the trigger is created switched off, so a wrong guess runs
    nothing — and nothing restates the task routes' refusals.
    """
    from datetime import datetime as _dt
    from src.event_bus import DEFAULT_TRIGGER_COUNT, EVENT_NAMES
    from src.task_scheduler import (
        MAX_TASK_TIMEOUT_SECONDS, MIN_TASK_TIMEOUT_SECONDS, cron_floor_problem, valid_timezone,
    )
    from src.workflow_document import TRIGGER_FIELDS, _TIME_RE

    raw = {k: v for k, v in fields.items() if k in TRIGGER_FIELDS} if isinstance(fields, dict) else {}
    out, notes = {}, []
    usable = True
    kind = raw.get("trigger_type") or "schedule"
    if kind not in START_TRIGGER_TYPES:
        usable = False
    elif kind == "schedule":
        schedule = raw.get("schedule") or "daily"
        at = raw.get("scheduled_time") or "09:00"
        start = {"trigger_type": "schedule", "schedule": schedule, "scheduled_time": at}
        if schedule not in START_SCHEDULES or not isinstance(at, str) or not _TIME_RE.fullmatch(at):
            usable = False
        elif schedule in ("weekly", "monthly"):
            day = _whole(raw.get("scheduled_day"))
            lo, hi = (0, 6) if schedule == "weekly" else (1, 31)
            if day is None or not lo <= day <= hi:
                usable = False
            start["scheduled_day"] = day
        elif schedule == "once":
            try:
                when = _dt.fromisoformat(str(raw.get("scheduled_date") or "").replace("Z", ""))
            except ValueError:
                when = None
            if when is None:
                usable = False
            else:
                start["scheduled_date"] = when.replace(tzinfo=None)
        elif schedule == "cron":
            cron = raw.get("cron_expression")
            try:
                from croniter import croniter
                croniter(cron)
                usable = isinstance(cron, str) and cron_floor_problem(cron) is None
            except Exception:  # noqa: BLE001 - any failure is "not a schedule this runs"
                usable = False
            start["cron_expression"] = cron
        if usable:
            out.update(start)
    elif kind == "event":
        event = raw.get("trigger_event")
        if event not in EVENT_NAMES:
            usable = False
        else:
            count = _whole(raw.get("trigger_count"))
            if count is None or not 1 <= count <= START_TRIGGER_COUNT_MAX:
                count = DEFAULT_TRIGGER_COUNT
            out.update({"trigger_type": "event", "trigger_event": event, "trigger_count": count,
                        "schedule": None, "scheduled_time": None})
    else:
        out.update({"trigger_type": "webhook", "schedule": None, "scheduled_time": None})
    if not usable:
        out = {}
        notes.append(START_LEFT_AT_DEFAULT)
    zone = raw.get("tz_name")
    if isinstance(zone, str) and zone.strip():
        if valid_timezone(zone.strip()):
            out["tz_name"] = zone.strip()
        else:
            notes.append(f"The time zone {quoted(zone.strip()[:60])} is not one this machine "
                         f"knows, so the start uses the server's. Set it on the start.")
    retries = raw.get("max_retries")
    if retries is not None:
        if _whole(retries) is not None and 0 <= retries <= 10:
            out["max_retries"] = retries or None
        else:
            notes.append("How many times it tries again was left unset — set it on the start.")
    limit = raw.get("timeout_seconds")
    if limit is not None:
        if _whole(limit) is not None and (limit == 0 or MIN_TASK_TIMEOUT_SECONDS <= limit
                                          <= MAX_TASK_TIMEOUT_SECONDS):
            out["timeout_seconds"] = limit or None
        else:
            notes.append("Its time limit was left unset — set it on the start.")
    if isinstance(raw.get("notifications_enabled"), bool):
        out["notifications_enabled"] = raw["notifications_enabled"]
    return out, notes


def create_from_document(db, *, owner, name, graph, trigger_fields, origin, needs=None,
                         resources=None, rows=None) -> tuple:
    """`P22-19` / `P22-24` (`SLICE-EF-DESIGN` § 1.2). The one door for a
    document that arrives from outside — the model's draft, a file. Returns
    `(wf, trigger, notes)`. In order:

      1. `clean_trigger_fields` — the start, made storable, with what it left out said;
      2. `_new_trigger` — created switched OFF, and a webhook's token MINTED
         there: a token, a status or an id the model or the file carried is
         never read (only `TRIGGER_FIELDS` reach the row);
      3. `check_document` — the real one: the admin gate, `validate_document`
         and what the owner can reach (`resources` only for a file's import,
         with stand-ins for what is missing);
      4. every step marked `unchecked` with its `origin`, and the `needs` the
         import found for it — whatever pin or mark the document carried is
         dropped first, so neither door depends on its caller to strip them;
      5. version 1, source `drafted` or `imported` (`version_graph`: no marks).

    Nothing else marks a whole document; a step changed by anything that is
    not a person is marked `assistant` by `_marks_kept`. Raises
    `WorkflowRefused`, writing nothing, when the document is refused.
    """
    from src.workflow_document import (
        DOOR_ORIGINS, ORIGIN_DRAFTED, UNCHECKED_KEY, VERSION_SOURCE_DRAFTED,
        VERSION_SOURCE_IMPORTED,
    )
    if origin not in DOOR_ORIGINS:
        raise ValueError(f"not an origin a mark can have: {origin!r}")
    _, _, Workflow, _ = _models()
    name = clean_name(name, required=False) or NEW_WORKFLOW_NAME
    fields, notes = clean_trigger_fields(trigger_fields)
    trigger = _new_trigger(owner=owner, name=name, fields=fields)
    if isinstance(graph, dict):
        graph = dict(graph)
        graph["nodes"] = [{k: v for k, v in n.items() if k not in (UNCHECKED_KEY, "pinned")}
                          if isinstance(n, dict) else n for n in (graph.get("nodes") or [])]
    parsed = check_document(db, graph, owner=owner, own_task_id=trigger.id, rows=rows,
                            resources=resources)
    at = _utcnow().isoformat() + "Z"
    needs = needs if isinstance(needs, dict) else {}
    marked = dict(parsed)
    marked["nodes"] = [dict(n, pinned=None, **{UNCHECKED_KEY: {
        "origin": origin, "at": at, "needs": [dict(x) for x in needs.get(n["id"]) or ()]}})
        for n in nodes_of(parsed)]
    db.add(trigger)
    db.flush()
    wf = Workflow(id=str(uuid.uuid4()), owner=owner, name=name, task_id=trigger.id,
                  graph=json.dumps(marked), version=1)
    db.add(wf)
    db.flush()
    _write_version(db, wf, marked, source=(VERSION_SOURCE_DRAFTED if origin == ORIGIN_DRAFTED
                                           else VERSION_SOURCE_IMPORTED))
    db.commit()
    count = len(marked["nodes"])
    said = [f"Made {quoted(name)}, {count} step{'s' if count != 1 else ''}. It is switched off, "
            f"and each step waits for you to check it before it can run."]
    address = webhook_path(trigger)
    if address:
        said.append(f"Its webhook address is {address}. It answers once you switch the "
                    f"workflow on.")
    return wf, trigger, said + notes


def webhook_path(task) -> str | None:
    """A webhook task's address, as `FORBIDDEN.md` Part 1 pins its shape."""
    if (getattr(task, "trigger_type", None) or "schedule") != "webhook" or not task.webhook_token:
        return None
    return f"/api/tasks/{task.id}/webhook/{task.webhook_token}"


def heads_reaching(tasks_by_id: dict, task_id: str) -> tuple:
    """`(heads, upstream)` for one step of a chain.

    `upstream` is every task an arrow path leads from into `task_id`, itself
    included; `heads` are those no task of the owner's leads to — the first
    steps of every chain that reaches it, in the owner's own task order. A
    task that only leads INTO the chain further down (a second chain sharing a
    step) does not reach `task_id` and is not a head of it: the engine converts
    the chain from its head and names such a task as one that keeps running
    as it does now (`chain_to_document`).
    """
    from src.task_scheduler import task_edges
    parents = {}
    for task in tasks_by_id.values():
        for edge in task_edges(task):
            if edge["to"] in tasks_by_id:
                parents.setdefault(edge["to"], []).append(task.id)
    upstream, frontier = {task_id}, [task_id]
    while frontier:
        following = []
        for node in frontier:
            for parent in parents.get(node, ()):
                if parent not in upstream:
                    upstream.add(parent)
                    following.append(parent)
        frontier = following
    heads = [tasks_by_id[i] for i in tasks_by_id if i in upstream and i not in parents]
    return heads, upstream


def _chain_from(tasks_by_id: dict, head_id: str) -> list:
    """The task ids the chain from `head_id` runs, each once, breadth first —
    the walk `chain_to_document` turns into steps."""
    from src.task_scheduler import task_edges
    order, seen, frontier = [head_id], {head_id}, [head_id]
    while frontier:
        following = []
        for node in frontier:
            for edge in task_edges(tasks_by_id[node]):
                if edge["to"] in tasks_by_id and edge["to"] not in seen:
                    seen.add(edge["to"])
                    order.append(edge["to"])
                    following.append(edge["to"])
        frontier = following
    return order


def convert_chain(db, *, owner, from_task_id, name=None, positions=None, name_of=None):
    """`P22-06`. A chain, copied into a new workflow that is switched off.

    `from_task_id` may be any step of the chain; the workflow starts where the
    chain does — the one first step that leads to it. Refused, in words: a
    step that is itself a workflow; a step two chains reach (which one it
    starts from is the person's choice, so they are named); a chain that goes
    round in a circle. What the chain from its head may be — a loop, another
    owner's task, a member that is a workflow, too many steps — is the
    engine's rule, asked once, in `chain_to_document` (`Law 7`). Nothing is
    written to any task of the chain. Returns `(wf, trigger, notes)`.
    """
    from src.task_scheduler import describe_graph_refusal, load_chain_rows, validate_graph
    from src.workflow_document import (
        TRIGGER_FIELDS, VERSION_SOURCE_CONVERTED, WORKFLOW_MAX_NODES, DocumentError,
        chain_to_document,
    )
    _, _, Workflow, _ = _models()
    name_of = name_of or (lambda task: task.name)
    depth = WORKFLOW_MAX_NODES + 1

    tasks_by_id, crew_ids = owner_rows(db, owner)
    picked = tasks_by_id.get(str(from_task_id or ""))
    if picked is None:
        raise WorkflowRefused(404, "No such task.")
    if (picked.task_type or "") == "workflow":
        raise WorkflowRefused(400, f"{quoted(name_of(picked))} is already a workflow.")
    heads, upstream = heads_reaching(tasks_by_id, picked.id)
    if not heads:
        # Every way back from this step comes round again, so the chain has
        # no first step: a loop, said in the engine's own words (`P22-01`).
        rows = load_chain_rows(db, list(upstream), known=tasks_by_id, max_depth=depth)
        refusal = validate_graph(rows, starts=sorted(upstream), owner=owner, max_depth=depth)
        names = {row.id: name_of(row) for row in rows if row.id in tasks_by_id}
        raise WorkflowRefused(400, describe_graph_refusal(refusal, names, first=picked.id)
                              if refusal is not None else
                              "This chain goes round in a circle, so it has no first step to start from.")
    if len(heads) > 1:
        said = " and ".join(quoted(name_of(t)) for t in sorted(heads, key=name_of))
        raise WorkflowRefused(
            400, f"{quoted(name_of(picked))} is reached from {len(heads)} first steps, {said}, "
                 f"and a workflow starts in one place. Make it from the one it should start at.")
    head = heads[0]
    # Every task of the owner's (what leads into the chain from outside it is
    # named in the engine's notes), and any other owner's task an arrow
    # reaches — a refusal, never a missing row (`load_chain_rows`).
    rows = load_chain_rows(db, [head.id], known=tasks_by_id, max_depth=depth)
    try:
        graph, trigger_fields, engine_notes = chain_to_document(rows, head.id, positions=positions)
    except DocumentError as err:
        raise _document_error_refusal(err) from None
    name = clean_name(name, required=False) or clean_name(f"{name_of(head)}{CONVERTED_SUFFIX}")
    fields = {k: v for k, v in dict(trigger_fields or {}).items() if k in TRIGGER_FIELDS}
    trigger = _new_trigger(owner=owner, name=name, fields=fields)
    parsed = check_document(db, graph, owner=owner, own_task_id=trigger.id,
                            rows=(tasks_by_id, crew_ids))
    db.add(trigger)
    db.flush()
    wf = Workflow(id=str(uuid.uuid4()), owner=owner, name=name, task_id=trigger.id,
                  graph=json.dumps(parsed), version=1,
                  source_chain=json.dumps({
                      "head_task_id": head.id,
                      "task_ids": _chain_from(tasks_by_id, head.id),
                      "head_was": head.status or "active",
                      "converted_at": _utcnow().isoformat() + "Z",
                      "paused_by_switch": False,
                  }))
    db.add(wf)
    db.flush()
    _write_version(db, wf, parsed, source=VERSION_SOURCE_CONVERTED)
    db.commit()
    # The engine says what was made from what (how many steps, the first one,
    # a task that also leads in); the store says what only it knows — the new
    # workflow's name, that it is off, and the two webhook addresses. The
    # engine's own webhook line is left out where the store names both
    # addresses, so the fact is said once (`Law 7`).
    addresses = _address_notes(trigger, head)
    notes = [str(n) for n in (engine_notes or ()) if n
             and not (addresses and "webhook" in str(n).lower())]
    notes.append(f"{quoted(name)} is switched off, and the chain still runs as before.")
    notes.extend(addresses)
    return wf, trigger, notes


def _address_notes(trigger, head) -> list:
    """`P22-06`, the integrator's call 3: a converted webhook chain gets a new
    address, and the person is told both, at conversion and at switch-on."""
    new = webhook_path(trigger)
    if not new:
        return []
    old = webhook_path(head) if head is not None else None
    said = f"This workflow has its own webhook address: {new}."
    if old:
        said += f" The chain's address, {old}, only answers while the chain is on."
    return [said]


def delete_workflow(db, wf, trigger, *, running: bool) -> list:
    """The document, its versions and its trigger (whose runs, and their node
    records, go with it). Refused while it runs. A chain it was made from is
    left exactly as it is, and the person is told if it is still paused."""
    _, _, _, WorkflowVersion = _models()
    ScheduledTask = _models()[0]
    if running:
        raise WorkflowRefused(409, f"{quoted(wf.name)} is running. Stop it first, then delete it.")
    notes = []
    chain = stored_chain(wf)
    if chain:
        head = db.query(ScheduledTask).filter(ScheduledTask.id == chain["head_task_id"]).first()
        if head is not None and (head.status or "active") == "paused" and chain.get("paused_by_switch"):
            notes.append(f"The chain it was made from is still paused. Resume "
                         f"{quoted(head.name)} to run it again.")
    db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == wf.id).delete(
        synchronize_session=False)
    db.delete(wf)
    db.flush()
    if trigger is not None:
        db.delete(trigger)
    db.commit()
    return notes


# ── what a run left ──────────────────────────────────────────────────────────

def _node_model():
    from core.database import TaskRunNode
    return TaskRunNode


def _json_list(raw) -> list:
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def graph_of_version(db, wf, version) -> tuple:
    """`(graph, kept)`: the graph of the version a run used, or — when that
    version was pruned or is unknown — the current one, with `kept` False so
    nobody draws a run on a graph it did not run and calls it that one."""
    _, _, _, WorkflowVersion = _models()
    if version is not None:
        row = (db.query(WorkflowVersion)
               .filter(WorkflowVersion.workflow_id == wf.id, WorkflowVersion.version == version)
               .first())
        if row is not None:
            try:
                return json.loads(row.graph), True
            except (TypeError, ValueError):
                # A kept version a hand edit broke is drawn as not kept — the
                # current graph, `kept` False, which the Runs view says — and
                # logged, rather than taking the run's detail down with it.
                logger.warning("Workflow %s version %s has an unreadable graph", wf.id, version)
    return stored_graph(wf), False


def dry_plan_nodes(db, run_id: str) -> list:
    """`P22-05`. A workflow's dry run, one entry per step — the engine's
    `workflow_runs.dry_node_entries` (`{node_id, kind, name, when, depth,
    steps, declined, task_id?}`, beside wave B's `chain` entries, design § 5),
    read from that run's dry step records, which carry how the plan reached
    each step (`reached_by`, `depth`) from the walk that planned it. This
    door only finds the document the plan was made from, so a Run task step's
    entry names its target (`task_id`). One reading of a plan (`Law 7`;
    closed at the wave C merge — this module walked the graph a second time
    for records without a place until then, and the engine writes one on
    every dry record)."""
    from src.workflow_runs import dry_node_entries
    _, TaskRun, _, _ = _models()
    TaskRunNode = _node_model()
    first = (db.query(TaskRunNode)
             .filter(TaskRunNode.run_id == run_id, TaskRunNode.dry.is_(True))
             .order_by(TaskRunNode.seq).first())
    if first is None:
        return []
    run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
    wf = workflow_for_task(db, run.task_id) if run is not None else None
    graph = graph_of_version(db, wf, first.workflow_version)[0] if wf is not None else None
    return dry_node_entries(db, run_id, graph)


# `P22-07`. How long a run's step records are kept is the pruner's own rule,
# `workflow_runs.node_records_days` (the setting `workflow_node_records_days`,
# its default and its bounds, `src/settings.py`), so "they were cleared" is
# said on exactly the runs the pruner can have reached — one function, asked
# by both (`Law 7`; this module resolved the setting itself until the wave C
# merge).


def records_were_cleared(run, *, now=None) -> bool:
    """A run with no step records: were they cleared after their window, or
    never written? (`Law 10` — "cleared" is a claim, made only when true.)

    Both have to hold: the run's own log says steps ran — a `node` line per
    step the walker ran (design § 2.3), or a dry run's headline and a line per
    step it planned — and the run ended longer ago than records are kept. A
    recent run with no records was never given any (a refusal before its
    first step, a plan the engine wrote no records for), and is not told its
    details were cleared.
    """
    from datetime import timedelta
    steps = _json_list(getattr(run, "steps", None))
    ran = any(isinstance(s, dict) and s.get("kind") == "node" for s in steps)
    if not ran:
        from src.task_scheduler import is_dry_run
        ran = is_dry_run(run) and sum(
            1 for s in steps if isinstance(s, dict) and s.get("kind") == "dry-run") > 1
    if not ran:
        return False
    ended = getattr(run, "finished_at", None) or getattr(run, "started_at", None)
    if ended is None:
        return False
    from src.workflow_runs import node_records_days
    return ended < (now or _utcnow()) - timedelta(days=node_records_days())


# ── On / Off, and the chain ──────────────────────────────────────────────────

def _next_run_of(db, task):
    from src.task_scheduler import _resolve_task_timezone, compute_next_run
    if (task.trigger_type or "schedule") != "schedule":
        return None
    return compute_next_run(task.schedule, task.scheduled_time, task.scheduled_day,
                            task.scheduled_date, cron_expression=task.cron_expression,
                            tz_name=_resolve_task_timezone(db, task))


def switch_workflow(db, wf, trigger, *, on: bool, name_of=None) -> tuple:
    """On or Off. Returns `(chain_paused, notes)`.

    The trigger task's `status` IS the switch (design § 0.9 — no second column,
    `Law 7`). Switching on checks the saved document first, as a save does, so
    a workflow the engine would refuse is refused here in the same words rather
    than failing at its first run; and if the workflow was made from a chain
    whose first step is on, that step is paused so the two do not both run.
    """
    ScheduledTask = _models()[0]
    name_of = name_of or (lambda task: task.name)
    if trigger is None:
        raise WorkflowRefused(400, LOST_TRIGGER)
    chain = stored_chain(wf)
    head = (db.query(ScheduledTask).filter(ScheduledTask.id == chain["head_task_id"]).first()
            if chain else None)
    if not on:
        trigger.status = "paused"
        db.commit()
        return None, ["Switched off — it will not run until you switch it on."]
    # `P22-19` (`SLICE-EF-DESIGN` § 1.1). Not while a step the model drafted,
    # or one a file carried, waits for a person to check it — a 409 naming the
    # steps (`reason: "unchecked"`, `node_ids`), so the Workbench can open them.
    # The task route's resume and `manage_tasks resume` come through here.
    from src.workflow_document import unchecked_refusal
    marks = unchecked_refusal(stored_graph(wf))
    if marks is not None:
        raise refusal_from(marks, status=409)
    check_document(db, stored_graph(wf), owner=wf.owner, own_task_id=trigger.id)
    trigger.status = "active"
    trigger.next_run = _next_run_of(db, trigger)
    notes = ["Switched on."]
    if (trigger.trigger_type or "schedule") == "schedule" and trigger.next_run is None:
        # A one-off whose time has passed: on, and never coming round. Said,
        # because "Switched on" alone would be a promise it cannot keep.
        notes.append("Its schedule has no time left to run at, so it will not run until "
                     "you change when it starts.")
    chain_paused = None
    if head is not None and (head.status or "active") == "active":
        head.status = "paused"
        chain = dict(chain, paused_by_switch=True)
        wf.source_chain = json.dumps(chain)
        chain_paused = {"task_id": head.id, "name": name_of(head)}
        notes[0] = (f"Switched on. The chain's first step, {quoted(name_of(head))}, is paused so "
                    f"the two do not both run.")
    notes.extend(_address_notes(trigger, head))
    db.commit()
    return chain_paused, notes


def restore_chain(db, wf, trigger, *, owner, name_of=None) -> tuple:
    """`P22-06`, *Put the old chain back*: the chain's first step runs again
    and this workflow is switched off. Nothing is deleted. Returns
    `(chain_resumed, notes)`."""
    from src.task_action_policy import (
        admin_refusal_message, is_admin_only_task_action, owner_has_admin_task_privileges,
    )
    ScheduledTask = _models()[0]
    name_of = name_of or (lambda task: task.name)
    chain = stored_chain(wf)
    if not chain:
        raise WorkflowRefused(400, "This workflow was not made from a chain, so there is no chain to put back.")
    head = db.query(ScheduledTask).filter(ScheduledTask.id == chain["head_task_id"]).first()
    if head is None:
        raise WorkflowRefused(
            400, "The chain's first step has been deleted since, so there is no chain to put back.")
    if is_admin_only_task_action(head.task_type, head.action) and not owner_has_admin_task_privileges(owner):
        # The resume door's rule (`task_routes.resume_task`).
        raise WorkflowRefused(403, admin_refusal_message(head.action))
    if trigger is not None:
        trigger.status = "paused"
    head.status = "active"
    head.next_run = _next_run_of(db, head)
    wf.source_chain = json.dumps(dict(chain, paused_by_switch=False))
    db.commit()
    resumed = {"task_id": head.id, "name": name_of(head),
               "next_run": head.next_run.isoformat() + "Z" if head.next_run else None}
    return resumed, ["The chain runs again and this workflow is switched off. Nothing was deleted."]


# ── `P22-17` · the question a parked step asks, and its answer ──────────────

# `C-W`. The two answers the Workbench sends. `approve_task` is the row's own
# scope word; `approve` (chat-session scope) has no chat to be remembered in.
ANSWER_DECISIONS = ("approve_task", "deny")
NO_CHAT_TO_REMEMBER = "There is no chat to remember this in; choose Allow once."


def waiting_list(db, owner: str | None) -> list:
    """`GET /api/workflows/waiting` (`C-W`): every step of the owner's
    workflows that waits right now, oldest first —
    `{workflow_id, workflow, run_id, node_id, item, label, kind, since, until,
    approval}`. `approval` is the card while the store still holds it (so the
    page re-offers only a question that can still be answered), else null."""
    from core.database import TaskRunNode
    from src.tool_approvals import tool_approval_store
    from src.workflow_runs import WAITING_APPROVAL, waiting_of
    ScheduledTask, TaskRun, Workflow, _ = _models()
    q = (db.query(TaskRunNode, TaskRun, Workflow)
         .join(TaskRun, TaskRun.id == TaskRunNode.run_id)
         .join(Workflow, Workflow.task_id == TaskRun.task_id)
         .filter(TaskRunNode.status == "waiting", TaskRun.status == "waiting",
                 TaskRunNode.item.is_(None)))
    if owner:
        q = q.filter(Workflow.owner == owner)
    out = []
    for rec, run, wf in q.order_by(TaskRunNode.started_at, TaskRunNode.seq).all():
        waiting = waiting_of(rec) or {}
        kind = waiting.get("kind")
        approval = None
        if kind == WAITING_APPROVAL and tool_approval_store.peek(waiting.get("approval_id")):
            approval = waiting.get("card")
        out.append({
            "workflow_id": wf.id, "workflow": wf.name, "run_id": run.id,
            "node_id": rec.node_id,
            "item": waiting.get("item") if isinstance(waiting.get("item"), int) else None,
            "label": rec.label, "kind": kind, "since": waiting.get("since"),
            "until": waiting.get("until"), "approval": approval,
        })
    return out


def find_waiting_step(db, wf, run_id: str, node_id: str, item, approval_id: str):
    """`(run, record, waiting)` for the question this answer is about, or a
    refusal: the run must be this workflow's and `waiting`, and the step's
    own record must wait on exactly this card."""
    from core.database import TaskRunNode
    from src.workflow_runs import WAITING_APPROVAL, waiting_of
    _, TaskRun, _, _ = _models()
    run = (db.query(TaskRun).filter(TaskRun.id == str(run_id or ""),
                                    TaskRun.task_id == wf.task_id).first()
           if wf.task_id else None)
    if run is None:
        raise WorkflowRefused(404, "No such run of this workflow.")
    if run.status != "waiting":
        raise WorkflowRefused(409, "This run is not waiting for an answer any more.")
    rec = (db.query(TaskRunNode)
           .filter(TaskRunNode.run_id == run.id, TaskRunNode.node_id == str(node_id or ""),
                   TaskRunNode.item.is_(None), TaskRunNode.status == "waiting").first())
    waiting = waiting_of(rec) if rec is not None else None
    asked_item = waiting.get("item") if isinstance((waiting or {}).get("item"), int) else None
    if (rec is None or not waiting or waiting.get("kind") != WAITING_APPROVAL
            or waiting.get("approval_id") != approval_id or asked_item != item):
        raise WorkflowRefused(409, "That step is not waiting on this question any more.")
    return run, rec, waiting
