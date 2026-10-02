# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-07` — one workflow run, every step: what it was handed, what it made.

`TaskRun` is one row per run with one `result` string and one step log, which is
the record `B806` says it cannot be for a workflow: a run of four steps has four
inputs and four outputs, and the person who opens yesterday's failed run wants
the failed step's, not a summary. `task_run_nodes` (`core.database.TaskRunNode`)
is that record, one row per step per run, and this module is everything that
writes, reads, caps and prunes it — the scheduler's walker writes through it, and
the workflow routes read through it, so there is one shape (`Law 7`).

**Capped.** What a step is handed and what it makes can be a whole mailbox
summary or a research report. Each of the two is kept up to
`workflow_node_record_max_chars` characters of JSON (`resolve_limit`, so a role
may carry it — `P12-01`'s order); past it the record keeps a preview and says it
was cut, as valid JSON, so a reader never has to guess whether a value is whole.

**Pruned.** On a finite window, `workflow_node_records_days`, at most once an
hour, at the end of a workflow run — `src/events.py`'s shape. The run's own row
in Activity is never touched: a run older than the window keeps its summary, and
its step details say they were cleared.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ── The two settings (`src/settings.py` carries the keys and these bounds) ──
#
# The cap resolves with the step's owner (a role may carry it) and ships a real
# default, so `role_limit_ranges` imports this range rather than restating it.
NODE_RECORD_MAX_CHARS_SETTING = "workflow_node_record_max_chars"
NODE_RECORD_MAX_CHARS_DEFAULT = 16000
# The floor keeps a record worth opening; the top is a sanity ceiling — a
# megabyte of one step's input in a row is a typo, not a decision.
NODE_RECORD_MAX_CHARS_RANGE = (1000, 1_000_000)

NODE_RECORDS_DAYS_SETTING = "workflow_node_records_days"
NODE_RECORDS_DAYS_DEFAULT = 30
NODE_RECORDS_DAYS_RANGE = (1, 3650)

# The same ceiling `TaskRun.error` is written under (`_execute_task_locked`).
NODE_ERROR_MAX_CHARS = 2000
# How much of an over-long value the record keeps to show, as a share of the
# cap: the marker around it has to fit too.
_PREVIEW_SHARE = 0.9
# A cut input's one-line summary rides inside the marker; it is a line, not a
# second copy of the input.
_SUMMARY_MAX = 300

_PRUNE_INTERVAL_SECONDS = 60 * 60
# None means "never pruned in this process", not "pruned at time zero" — the
# reason is at `src/events.py`'s `_last_prune` (monotonic time counts from boot).
_last_prune: float | None = None
_prune_lock = threading.Lock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value) -> str | None:
    return value.isoformat() + "Z" if value else None


def node_record_max_chars(owner: str | None = None) -> int:
    """The cap on one step's input, and separately on its output, in characters."""
    from src.settings import resolve_limit

    lo, hi = NODE_RECORD_MAX_CHARS_RANGE
    value, _source = resolve_limit(
        NODE_RECORD_MAX_CHARS_SETTING, NODE_RECORD_MAX_CHARS_DEFAULT,
        owner=owner, minimum=lo, maximum=hi)
    return value


def node_records_days() -> int:
    """How many days a step's record is kept."""
    from src.settings import resolve_limit

    lo, hi = NODE_RECORDS_DAYS_RANGE
    value, _source = resolve_limit(
        NODE_RECORDS_DAYS_SETTING, NODE_RECORDS_DAYS_DEFAULT,
        minimum=lo, maximum=hi)
    return value


def cap_json(value, *, limit: int, summary: str | None = None) -> str | None:
    """`value` as JSON text no longer than about `limit`, or `None` for `None`.

    Over the cap it becomes `{"truncated": true, "chars": N, "preview": "…"}` —
    still valid JSON, and it says what was lost. `summary` (the one-line
    description of an input, `trigger_summary`'s) rides inside the marker, so
    a cut input still says what it was.
    """
    if value is None:
        return None
    try:
        text = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = json.dumps(str(value), ensure_ascii=False)
    if len(text) <= limit:
        return text
    # The preview is JSON inside JSON, so every quote in it is escaped again
    # and the stored text is longer than the slice; it shrinks until what is
    # STORED fits, which is the number the setting promises.
    keep = max(0, int(limit * _PREVIEW_SHARE))
    while True:
        marker = {"truncated": True, "chars": len(text), "preview": text[:keep]}
        if summary:
            marker["summary"] = summary[:_SUMMARY_MAX]
        stored = json.dumps(marker, ensure_ascii=False)
        if len(stored) <= limit or keep == 0:
            return stored
        keep = max(0, keep - (len(stored) - limit) - 8)


def is_truncated(value) -> bool:
    """Is this stored (parsed) value the marker `cap_json` writes?"""
    return isinstance(value, dict) and value.get("truncated") is True \
        and "preview" in value and "chars" in value


def _loads(text):
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def record_node_start(db, *, run_id: str, node: dict, seq: int,
                      input_envelope, workflow_version: int | None,
                      owner: str | None = None, dry: bool = False,
                      reached_by: str | None = None, depth: int | None = None):
    """Write one step's record as `running` (a real run) and commit it.

    Written at the start, so a view polling a run in progress shows which step
    it is on. A dry run's plan is written `skipped` in one go by
    `record_dry_node` instead.
    """
    from core.database import TaskRunNode
    from src.event_bus import trigger_summary

    rec = TaskRunNode(
        id=str(uuid.uuid4()),
        run_id=run_id,
        node_id=str(node.get("id")),
        kind=node.get("kind"),
        label=node.get("label"),
        seq=seq,
        status="running",
        attempt=1,
        dry=bool(dry),
        workflow_version=workflow_version,
        started_at=_utcnow(),
        input=cap_json(input_envelope, limit=node_record_max_chars(owner),
                       summary=trigger_summary(input_envelope) or None),
        reached_by=reached_by,
        depth=depth,
    )
    db.add(rec)
    db.commit()
    return rec


def record_node_end(db, rec, *, status: str, text: str | None = None,
                    data=None, error: str | None = None, steps=None,
                    model: str | None = None, port: str | None = None,
                    owner: str | None = None) -> None:
    """Finish one step's record and commit it.

    `status` is `TASK_RUN_STATUSES`' word for how the step ended — never
    `queued`, never `deferred` (the walker maps that to `skipped`, with why).
    `port` is the outcome edge it left by, or `None` where its branch ended.
    """
    rec.status = status
    rec.finished_at = _utcnow()
    rec.port = port
    rec.model = model
    if text is not None or data is not None:
        out = {"text": text or "", "data": data}
        rec.output = cap_json(out, limit=node_record_max_chars(owner))
    if error:
        rec.error = str(error)[:NODE_ERROR_MAX_CHARS]
    if steps:
        try:
            rec.steps = json.dumps(list(steps), default=str)
        except (TypeError, ValueError):
            logger.warning("Could not serialise the step log of step record %s", rec.id)
    db.commit()


def record_dry_node(db, *, run_id: str, node: dict, seq: int, steps: list,
                    declined: str | None, reached_by: str | None,
                    depth: int, workflow_version: int | None):
    """One step of a dry run's plan: `skipped`, `dry`, its plan lines as its
    steps, and — where the engine would not plan it — why, as its `error`.
    Not committed here: the dry run commits its records with its run row."""
    from core.database import TaskRunNode

    now = _utcnow()
    rec = TaskRunNode(
        id=str(uuid.uuid4()),
        run_id=run_id,
        node_id=str(node.get("id")),
        kind=node.get("kind"),
        label=node.get("label"),
        seq=seq,
        status="skipped",
        attempt=1,
        dry=True,
        reached_by=reached_by,
        depth=depth,
        workflow_version=workflow_version,
        started_at=now,
        finished_at=now,
        error=declined,
        steps=json.dumps(list(steps or []), default=str),
    )
    db.add(rec)
    return rec


def input_summary(stored_input) -> str:
    """One line saying what a step was handed — `trigger_summary`'s words, so
    the Runs view and a run's step log say it the same way (`Law 7`)."""
    from src.event_bus import trigger_summary

    if stored_input is None:
        return "Nothing — it was not handed anything."
    if is_truncated(stored_input):
        return stored_input.get("summary") or (
            f"Too long to keep in full ({stored_input.get('chars')} characters).")
    return trigger_summary(stored_input) or "Nothing it could name."


def node_record_to_dict(rec) -> dict:
    """`NodeRecord`, contract C2 — exactly these keys."""
    stored_input = _loads(rec.input)
    steps = _loads(rec.steps)
    return {
        "id": rec.id,
        "node_id": rec.node_id,
        "kind": rec.kind,
        "label": rec.label,
        "seq": rec.seq,
        "status": rec.status,
        "attempt": rec.attempt,
        "dry": bool(rec.dry),
        "port": rec.port,
        "workflow_version": rec.workflow_version,
        "started_at": _iso(rec.started_at),
        "finished_at": _iso(rec.finished_at),
        "input": stored_input,
        "input_summary": input_summary(stored_input),
        "output": _loads(rec.output),
        "error": rec.error,
        "steps": steps if isinstance(steps, list) else [],
        "model": rec.model,
    }


def run_node_records(db, run_id: str) -> list:
    """A run's step records in the order they ran (or were planned)."""
    from core.database import TaskRunNode

    return (db.query(TaskRunNode).filter(TaskRunNode.run_id == run_id)
            .order_by(TaskRunNode.seq, TaskRunNode.started_at).all())


def dry_node_entries(db, run_id: str) -> list:
    """A workflow dry run's plan, one entry per step, breadth first — the
    shape wave B's chain dry run answers in (`chain` entries), for the
    `nodes` key of `POST /api/tasks/{id}/run?dry=true` on a workflow task:
    `{node_id, kind, name, when, depth, steps, declined}`."""
    out = []
    for rec in run_node_records(db, run_id):
        if not rec.dry:
            continue
        steps = _loads(rec.steps)
        out.append({
            "node_id": rec.node_id,
            "kind": rec.kind,
            "name": rec.label,
            "when": rec.reached_by,
            "depth": rec.depth if rec.depth is not None else 0,
            "steps": steps if isinstance(steps, list) else [],
            "declined": rec.error,
        })
    return out


def last_node_record(db, task_id: str, node_id: str):
    """The newest REAL record of this step in this workflow's runs, or `None`.

    `P22-08`'s *from the last run*. A dry run's plan is never "the last run"
    (`B1054`'s defect, closed here by the `dry` flag rather than by a sentence).
    Node ids are per document, so the trigger task's id scopes the search.
    """
    from core.database import TaskRun, TaskRunNode

    return (db.query(TaskRunNode)
            .join(TaskRun, TaskRun.id == TaskRunNode.run_id)
            .filter(TaskRun.task_id == task_id,
                    TaskRunNode.node_id == str(node_id),
                    TaskRunNode.dry.is_(False))
            .order_by(TaskRunNode.started_at.desc(), TaskRunNode.seq.desc())
            .first())


def prune_node_records(db, *, days: int | None = None, now: datetime | None = None) -> int:
    """Delete step records that finished more than `days` ago. Answers how many.

    Through the ORM, never raw SQL (`.pantheon/check-run-statuses.py` reads raw
    SQL against `task_runs`). Records still `running` have no `finished_at` and
    are never touched; the run rows are never touched.
    """
    from core.database import TaskRunNode

    days = node_records_days() if days is None else days
    cutoff = (now or _utcnow()) - timedelta(days=days)
    removed = (db.query(TaskRunNode)
               .filter(TaskRunNode.finished_at.isnot(None),
                       TaskRunNode.finished_at < cutoff)
               .delete(synchronize_session=False))
    db.commit()
    return int(removed or 0)


def maybe_prune_node_records(db) -> int:
    """`prune_node_records`, at most once an hour per process. Never raises:
    a prune that fails must not turn a finished run into an error."""
    global _last_prune
    now = time.monotonic()
    with _prune_lock:
        if _last_prune is not None and now - _last_prune < _PRUNE_INTERVAL_SECONDS:
            return 0
        _last_prune = now
    try:
        removed = prune_node_records(db)
        if removed:
            logger.info("Pruned %d workflow step record(s) past %d day(s)",
                        removed, node_records_days())
        return removed
    except Exception:
        logger.warning("Could not prune workflow step records", exc_info=True)
        try:
            db.rollback()
        except Exception:
            # The failure was logged on the line above; a rollback that fails
            # too leaves the session to its owner, who closes it next.
            pass
        return 0


def records_cleared_sentence(days: int | None = None) -> str:
    """What the Runs view says about a run older than the window."""
    days = node_records_days() if days is None else days
    return (f"Its step details were cleared after {days} days "
            f"({NODE_RECORDS_DAYS_SETTING}).")
