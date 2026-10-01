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

# `workflow_versions.source` — stored values, so an enum written once.
VERSION_SOURCE_USER = "user"
VERSION_SOURCE_CONVERTED = "converted"
VERSION_SOURCE_RESTORED = "restored"
VERSION_SOURCES = (VERSION_SOURCE_USER, VERSION_SOURCE_CONVERTED, VERSION_SOURCE_RESTORED)

# What a `PUT /api/workflows/{id}` did, as the reply's `saved` (`Law 10`: an
# enum, never a boolean a reader can take two ways).
SAVED_NEW_VERSION = "new_version"
SAVED_UNCHANGED = "unchanged"
SAVED_POSITIONS = "positions"
SAVED_PINS = "pins"

# The columns of a chain's first step that say when it runs — what a converted
# workflow's trigger takes from it. An allowlist, so whatever else the engine's
# `chain_to_document` hands back can never reach a row unasked.
TRIGGER_COLUMNS = (
    "schedule", "scheduled_time", "scheduled_day", "scheduled_date",
    "cron_expression", "trigger_type", "trigger_event", "trigger_count",
    "tz_name", "max_retries", "timeout_seconds", "notifications_enabled",
    "crew_member_id",
)


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
                 node_ids=()):
        super().__init__(sentence)
        self.status = int(status)
        self.sentence = sentence
        self.reason = reason
        self.node_ids = tuple(node_ids or ())

    def body(self) -> dict:
        out = {"detail": self.sentence}
        if self.reason is not None:
            out["reason"] = self.reason
            out["node_ids"] = list(self.node_ids)
        return out


# ── reading ──────────────────────────────────────────────────────────────────

def _models():
    from core.database import ScheduledTask, TaskRun, Workflow, WorkflowVersion
    return ScheduledTask, TaskRun, Workflow, WorkflowVersion


def empty_graph() -> dict:
    """A document with nothing in it yet: a start and no steps."""
    from src.workflow_document import GRAPH_VERSION, START_KEY
    return {"v": GRAPH_VERSION, START_KEY: {"position": None}, "nodes": [], "edges": []}


def stored_graph(wf) -> dict:
    """The document as stored. It was validated when it was written; a row a
    hand edit broke reads as the empty document rather than taking every list
    down, and the next save or run says what is wrong with it."""
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
    or a run row that has not finished — a queued run holds no claim yet."""
    from core.database import TASK_RUN_ACTIVE_STATUSES
    _, TaskRun, _, _ = _models()
    if task_id in (getattr(scheduler, "_executing", None) or ()):
        return True
    return db.query(TaskRun.id).filter(
        TaskRun.task_id == task_id,
        TaskRun.status.in_(TASK_RUN_ACTIVE_STATUSES)).first() is not None


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
                           node_ids=getattr(refusal, "node_ids", None) or ())


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
    where a task with that action is.
    """
    from src.task_action_policy import is_admin_only_task_action
    for node in nodes_of(graph):
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if node.get("kind") == "action" and is_admin_only_task_action("action", config.get("action")):
            return config.get("action")
    return None


def check_document(db, graph, *, owner: str | None, own_task_id: str | None,
                   rows=None) -> dict:
    """Parse and validate a document exactly as a save does. Returns it parsed.

    The order is the task routes': an action only an admin may schedule is a
    403 with the routes' own sentence (`admin_refusal_message`), then the
    engine's one rule (`validate_document` — the sentence a run would write,
    `Law 10`). Writes nothing.
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
    refusal = validate_document(parsed, owner=owner, tasks_by_id=tasks_by_id,
                                crew_ids=crew_ids, owner_is_admin=is_admin,
                                own_task_id=own_task_id)
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
    """The row for `wf.version`, then the oldest beyond the twenty pruned."""
    from src.workflow_document import content_fingerprint, without_pins
    _, _, _, WorkflowVersion = _models()
    db.add(WorkflowVersion(
        id=str(uuid.uuid4()), workflow_id=wf.id, version=wf.version, name=wf.name,
        graph=json.dumps(without_pins(graph)),
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


def save_document(db, wf, trigger, *, name, graph, base_version, check: bool = False) -> str:
    """Save a content edit. A new version only if the content moved.

    `check=True` answers exactly what the save would — stale, refused or fine —
    and writes nothing (`PUT ?check=true`, which the canvas asks on each
    connect). Returns `SAVED_NEW_VERSION`, `SAVED_UNCHANGED` or `"check"`.
    """
    from src.workflow_document import content_fingerprint
    _stale(wf, base_version)
    new_name = clean_name(name) if name is not None else wf.name
    parsed = check_document(db, graph, owner=wf.owner, own_task_id=trigger.id if trigger else None)
    if check:
        return "check"
    before = stored_graph(wf)
    parsed = _pins_kept(parsed, before)
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
    _commit_version(db, wf, parsed, source=VERSION_SOURCE_USER, base=base)
    return SAVED_NEW_VERSION


def restore_version(db, wf, trigger, version, *, base_version) -> str:
    """Put a kept version back, as a NEW version (`source="restored"`).

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
    parsed = _pins_kept(parsed, before)
    if content_fingerprint(row.name, parsed) == content_fingerprint(wf.name, before):
        return SAVED_UNCHANGED
    wf.graph = json.dumps(parsed)
    base = wf.version
    wf.version = (wf.version or 0) + 1
    wf.name = row.name
    if trigger is not None:
        trigger.name = row.name
    _commit_version(db, wf, parsed, source=VERSION_SOURCE_RESTORED, base=base)
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
    from src.workflow_document import build_pin
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
        envelope, lost = build_pin(graph, str(node_id), trigger, data)
        node["pinned"] = envelope
        dropped[str(node_id)] = list(lost or ())
    wf.graph = json.dumps(graph)
    db.commit()
    return dropped


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
    """A new, empty workflow, switched off. Returns `(wf, trigger, notes)`."""
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


def webhook_path(task) -> str | None:
    """A webhook task's address, as `FORBIDDEN.md` Part 1 pins its shape."""
    if (getattr(task, "trigger_type", None) or "schedule") != "webhook" or not task.webhook_token:
        return None
    return f"/api/tasks/{task.id}/webhook/{task.webhook_token}"


def chain_component(tasks_by_id: dict, task_id: str) -> list:
    """Every task joined to `task_id` by an edge either way, in the owner's rows."""
    from src.task_scheduler import task_edges
    links = {}
    for task in tasks_by_id.values():
        for edge in task_edges(task):
            links.setdefault(edge["from"], set()).add(edge["to"])
            links.setdefault(edge["to"], set()).add(edge["from"])
    seen, frontier = {task_id}, [task_id]
    while frontier:
        nxt = []
        for node in frontier:
            for other in links.get(node, ()):
                if other not in seen and other in tasks_by_id:
                    seen.add(other)
                    nxt.append(other)
        frontier = nxt
    return [tid for tid in tasks_by_id if tid in seen]


def convert_chain(db, *, owner, from_task_id, name=None, positions=None, name_of=None):
    """`P22-06`. A chain, copied into a new workflow that is switched off.

    `from_task_id` may be any step of the chain; the workflow starts where the
    chain does. Refused, in words: a step that is itself a workflow, a chain
    that starts in more than one place (a document has one start), and a chain
    the engine refuses (`validate_graph` — a loop, or a step that is not the
    owner's). Nothing is written to any task of the chain. Returns
    `(wf, trigger, notes)`.
    """
    from src.task_scheduler import (
        describe_graph_refusal, load_chain_rows, task_edges, validate_graph,
    )
    from src.workflow_document import DocumentError, WORKFLOW_MAX_NODES, chain_to_document
    _, _, Workflow, _ = _models()
    name_of = name_of or (lambda task: task.name)

    tasks_by_id, crew_ids = owner_rows(db, owner)
    picked = tasks_by_id.get(str(from_task_id or ""))
    if picked is None:
        raise WorkflowRefused(404, "No such task.")
    if (picked.task_type or "") == "workflow":
        raise WorkflowRefused(400, f"{quoted(name_of(picked))} is already a workflow.")
    members = chain_component(tasks_by_id, picked.id)
    inner = [tasks_by_id[m] for m in members if (tasks_by_id[m].task_type or "") == "workflow"]
    if inner:
        said = ", ".join(quoted(name_of(t)) for t in inner)
        raise WorkflowRefused(
            400, f"{said} {'is a workflow' if len(inner) == 1 else 'are workflows'}, and a "
                 f"workflow cannot be a step of another one. Take "
                 f"{'it' if len(inner) == 1 else 'them'} out of the chain first.")
    # The engine's rule for the chain as it is, walked from every member so a
    # loop anywhere in it is found — and to `WORKFLOW_MAX_NODES` deep, because
    # the document's own cap (not the chain's ten) is what the workflow will run
    # under. No owner filter on the rows: a chain into another owner's task is
    # a refusal, not a missing row (`load_chain_rows`).
    rows = load_chain_rows(db, members, known={m: tasks_by_id[m] for m in members},
                           max_depth=WORKFLOW_MAX_NODES + 1)
    refusal = validate_graph(rows, starts=members, owner=owner,
                             max_depth=WORKFLOW_MAX_NODES + 1)
    if refusal is not None:
        names = {row.id: name_of(row) for row in rows}
        raise WorkflowRefused(400, describe_graph_refusal(refusal, names, first=picked.id))
    led_to = {edge["to"] for m in members for edge in task_edges(tasks_by_id[m])}
    heads = [tasks_by_id[m] for m in members if m not in led_to]
    if len(heads) != 1:
        said = " and ".join(quoted(name_of(t)) for t in heads)
        raise WorkflowRefused(
            400, f"This chain starts in {len(heads)} places, {said}, and a workflow starts "
                 f"in one. Join them under one first step, or make each its own workflow.")
    head = heads[0]
    component_rows = [tasks_by_id[m] for m in members]
    try:
        graph, trigger_fields, engine_notes = chain_to_document(
            component_rows, head.id, positions=positions)
    except DocumentError as err:
        raise _document_error_refusal(err) from None
    name = clean_name(name, required=False) or clean_name(f"{name_of(head)}{CONVERTED_SUFFIX}")
    fields = {k: v for k, v in dict(trigger_fields or {}).items() if k in TRIGGER_COLUMNS}
    trigger = _new_trigger(owner=owner, name=name, fields=fields)
    parsed = check_document(db, graph, owner=owner, own_task_id=trigger.id,
                            rows=(tasks_by_id, crew_ids))
    db.add(trigger)
    db.flush()
    wf = Workflow(id=str(uuid.uuid4()), owner=owner, name=name, task_id=trigger.id,
                  graph=json.dumps(parsed), version=1,
                  source_chain=json.dumps({
                      "head_task_id": head.id,
                      "task_ids": [t.id for t in component_rows],
                      "head_was": head.status or "active",
                      "converted_at": _utcnow().isoformat() + "Z",
                      "paused_by_switch": False,
                  }))
    db.add(wf)
    db.flush()
    _write_version(db, wf, parsed, source=VERSION_SOURCE_CONVERTED)
    db.commit()
    steps = len(nodes_of(parsed))
    notes = [f"Made {quoted(name)} from {steps} step{'s' if steps != 1 else ''}. It is "
             f"switched off, and the chain still runs as before."]
    if head.id != picked.id:
        notes.append(f"The chain starts at {quoted(name_of(head))}, so the workflow starts there too.")
    notes.extend(str(n) for n in (engine_notes or ()) if n)
    notes.extend(_address_notes(trigger, head))
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


def bfs_places(graph) -> dict:
    """`{node id: (when, depth)}` from the engine's breadth-first walk.

    `reachable_bfs` (`C1`) is the one walk — every node once, `when` from its
    first parent, as wave B's chain contract has it. Read as an ordered
    iterable of `(node, when, depth)`, or of dicts carrying `node`/`node_id`,
    `when` and `depth`, which is all `C1` fixes about its shape.
    """
    from src.workflow_document import reachable_bfs
    out = {}
    for entry in reachable_bfs(graph) or ():
        if isinstance(entry, dict):
            node = entry.get("node")
            node_id = entry.get("node_id") or entry.get("id") or node
            when, depth = entry.get("when"), entry.get("depth")
        else:
            node_id, when, depth = (tuple(entry) + (None, None, None))[:3]
        if isinstance(node_id, dict):
            node_id = node_id.get("id")
        if node_id is not None:
            out.setdefault(str(node_id), (when, depth))
    return out


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
                pass
    return stored_graph(wf), False


def dry_plan_nodes(db, run_id: str) -> list:
    """`P22-05`. A workflow's dry run, one entry per step, read from that run's
    dry node records — `{node_id, kind, name, when, depth, steps, declined,
    task_id?}`, beside wave B's `chain` entries (design § 5) — so the canvas
    draws a document's plan as it draws a chain's. `task_id` is only a run-task
    step's target; it is not overloaded with the step's own id."""
    _, TaskRun, _, _ = _models()
    TaskRunNode = _node_model()
    recs = (db.query(TaskRunNode)
            .filter(TaskRunNode.run_id == run_id, TaskRunNode.dry.is_(True))
            .order_by(TaskRunNode.seq).all())
    if not recs:
        return []
    run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
    wf = workflow_for_task(db, run.task_id) if run is not None else None
    graph = graph_of_version(db, wf, recs[0].workflow_version)[0] if wf is not None else {}
    places = bfs_places(graph) if wf is not None else {}
    by_id = {str(n.get("id")): n for n in nodes_of(graph)}
    out = []
    for rec in recs:
        when, depth = places.get(str(rec.node_id), (None, None))
        if getattr(rec, "depth", None) is not None:
            # The engine's dry record says how the plan reached the step
            # (`reached_by`, `depth`), written by the same walk that planned
            # it — so it is the one answer (`Law 7`), and the graph's walk
            # above is only for records that do not carry it.
            when, depth = getattr(rec, "reached_by", None), rec.depth
        entry = {
            "node_id": rec.node_id, "kind": rec.kind, "name": rec.label,
            "when": when, "depth": depth,
            "steps": _json_list(rec.steps),
            "declined": rec.error or None,
        }
        if rec.kind == "run_task":
            config = (by_id.get(str(rec.node_id)) or {}).get("config") or {}
            entry["task_id"] = config.get("task_id")
        out.append(entry)
    return out


# `P22-07`. How long a run's step records are kept — the key, default and
# bounds `maybe_prune_node_records` resolves (design § 3.2: settings-only, no
# owner), so "they were cleared" is said on exactly the runs the pruner can
# have reached. A merge point with wf-engine: the two must stay one rule.
NODE_RECORDS_DAYS_KEY = "workflow_node_records_days"
NODE_RECORDS_DAYS_DEFAULT = 30


def node_records_days() -> int:
    from src.settings import resolve_limit
    return resolve_limit(NODE_RECORDS_DAYS_KEY, NODE_RECORDS_DAYS_DEFAULT,
                         minimum=1, maximum=3650)[0]


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
