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

# `P22-12`. How many items one For-each step may run. Over it the step is
# refused with this setting's name — nothing is cut silently. Resolves with
# the owner (a role may carry it), like the record cap above.
FOREACH_MAX_ITEMS_SETTING = "workflow_foreach_max_items"
FOREACH_MAX_ITEMS_DEFAULT = 50
FOREACH_MAX_ITEMS_RANGE = (1, 1000)

# `P22-11`. The longest a Wait step may wait, in hours. Mistake prevention,
# not a control (`Law 17`): a Wait of a year is a typo.
WAIT_MAX_HOURS_SETTING = "workflow_wait_max_hours"
WAIT_MAX_HOURS_DEFAULT = 168
WAIT_MAX_HOURS_RANGE = (1, 720)

# `B1857`. How many steps one workflow may hold. It was a constant, twenty
# (`workflow_document.WORKFLOW_MAX_NODES`), which a person building anything
# n8n-shaped met within an afternoon, with nothing to move it. Mistake
# prevention, not a control (`Law 17`): the floor is the old cap, so no
# document that was ever saved is refused by a lower one, and the top is what
# the document rule's walks were measured at (`find_loop` is one depth-first
# pass, `concurrent_arrivals` a reachability over pairs of steps — 501² states
# at most) and what a 256 KiB document can hold of steps worth drawing.
# Settings-only, like the longest Wait: one number for the whole install.
MAX_STEPS_SETTING = "workflow_max_steps"
MAX_STEPS_DEFAULT = 100
MAX_STEPS_RANGE = (20, 500)

# `B1883`. How much of the values an AI step reads (its prompt's references)
# the model is shown, in characters, all of them together. They were shown at
# a trigger payload's numbers — each cut to 2,000 and the block to 6,000 — so
# "Summarise {{ steps.fetch.data.body }}" summarised the first 2,000
# characters of a page with nothing said. Within this every value is shown
# whole; past it the longest are cut first and the step's log names them and
# this setting (`workflow_refs.fit_values`). Mistake prevention, not a control
# (`Law 17`): a model's context is finite. The floor is the old per-value cut,
# the top the sanity ceiling the record cap uses. Settings-only, like the
# longest Wait: one number for the install.
PROMPT_VALUES_MAX_CHARS_SETTING = "workflow_prompt_values_max_chars"
PROMPT_VALUES_MAX_CHARS_DEFAULT = 20_000
PROMPT_VALUES_MAX_CHARS_RANGE = (2_000, 1_000_000)
# These defaults and ranges are stated HERE and nowhere else (`Law 7`,
# `integrate-d`): `workflow_document` (the save-time check, `WorkflowResources`)
# and `src/settings.py` (`DEFAULT_SETTINGS`) import them. This module imports
# nothing of the product at load, so both can.

# `P22-11`. How many deterministic and logic steps of one run run side by side.
# A constant for mistake prevention, not a control (`Law 17`): the run still
# holds ONE model-slot permit, and its model-driven steps take a per-run lock
# one at a time, so the concurrency cap still applies. The walker
# (`task_scheduler`) and the palette's `limits` (`workflow_effects`) read it.
WORKFLOW_PARALLEL_STEPS = 4

# `P22-17` (`D-2026-10-02-01` §1). How long a parked workflow step's card waits
# for an answer. Its own deadline, so an overnight question does not lapse at
# the chat card's ten minutes and a chat card does not linger twelve hours.
# The same four layers as `approval_timeout_seconds` (role → setting → env →
# default) and the store's own bounds, imported (`FORBIDDEN.md` Part 2: the
# TTL is kept — this moves it, never lifts it).
WORKFLOW_APPROVAL_TIMEOUT_SETTING = "workflow_approval_timeout_seconds"
WORKFLOW_APPROVAL_TIMEOUT_ENV = "PANTHEON_WORKFLOW_APPROVAL_TIMEOUT_SECONDS"
WORKFLOW_APPROVAL_TIMEOUT_DEFAULT = 12 * 60 * 60

# `P22-11` / `P22-17`. What a `waiting` record waits for (`TaskRunNode.waiting`
# JSON `kind`). Stored values (`FORBIDDEN.md` Part 1 at the merge).
WAITING_TIME = "time"            # a Wait step, until `resume_at`
WAITING_APPROVAL = "approval"    # a step's card, until it is answered or lapses
WAITING_IDLE = "idle"            # a step a foreground takeover stopped
WAITING_KINDS = (WAITING_TIME, WAITING_APPROVAL, WAITING_IDLE)

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


def foreach_max_items(owner: str | None = None) -> int:
    """`P22-12`. How many items one For-each step may run, for this owner."""
    from src.settings import resolve_limit

    lo, hi = FOREACH_MAX_ITEMS_RANGE
    value, _source = resolve_limit(
        FOREACH_MAX_ITEMS_SETTING, FOREACH_MAX_ITEMS_DEFAULT,
        owner=owner, minimum=lo, maximum=hi)
    return value


def wait_max_hours() -> int:
    """`P22-11`. The longest a Wait step may wait, in hours."""
    from src.settings import resolve_limit

    lo, hi = WAIT_MAX_HOURS_RANGE
    value, _source = resolve_limit(
        WAIT_MAX_HOURS_SETTING, WAIT_MAX_HOURS_DEFAULT, minimum=lo, maximum=hi)
    return value


def prompt_values_max_chars() -> int:
    """`B1883`. How much of the values an AI step reads its model is shown, in
    characters, together (`workflow_prompt_values_max_chars`)."""
    from src.settings import resolve_limit

    lo, hi = PROMPT_VALUES_MAX_CHARS_RANGE
    value, _source = resolve_limit(
        PROMPT_VALUES_MAX_CHARS_SETTING, PROMPT_VALUES_MAX_CHARS_DEFAULT,
        minimum=lo, maximum=hi)
    return value


def max_steps() -> int:
    """`B1857`. How many steps one workflow may hold (`workflow_max_steps`)."""
    from src.settings import resolve_limit

    lo, hi = MAX_STEPS_RANGE
    value, _source = resolve_limit(
        MAX_STEPS_SETTING, MAX_STEPS_DEFAULT, minimum=lo, maximum=hi)
    return value


def workflow_approval_ttl_seconds(owner: str | None = None) -> int:
    """`P22-17`. A parked workflow step's card deadline, through `P12`'s four
    layers exactly as `tool_approvals.resolve_approval_ttl_seconds` resolves
    the chat card's — the same resolver, the same bounds, its own key."""
    from src.limit_policy import resolve_int_limit
    from src.tool_approvals import MAX_APPROVAL_TTL_SECONDS, MIN_APPROVAL_TTL_SECONDS

    return resolve_int_limit(
        WORKFLOW_APPROVAL_TIMEOUT_SETTING,
        default=WORKFLOW_APPROVAL_TIMEOUT_DEFAULT,
        env_name=WORKFLOW_APPROVAL_TIMEOUT_ENV,
        owner=owner,
        minimum=MIN_APPROVAL_TTL_SECONDS,
        maximum=MAX_APPROVAL_TTL_SECONDS,
    ).value


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
                      reached_by: str | None = None, depth: int | None = None,
                      item: int | None = None, label: str | None = None):
    """Write one step's record as `running` (a real run) and commit it.

    Written at the start, so a view polling a run in progress shows which step
    it is on. A dry run's plan is written `skipped` in one go by
    `record_dry_node` instead. `item` (`P22-12`) is a For-each item's index;
    `label` overrides the step's ("Summarise · item 3 of 5").
    """
    from core.database import TaskRunNode
    from src.event_bus import trigger_summary

    rec = TaskRunNode(
        id=str(uuid.uuid4()),
        run_id=run_id,
        node_id=str(node.get("id")),
        kind=node.get("kind"),
        label=label or node.get("label"),
        item=item,
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
    # `P22-11`. A record that waited and is now over waits for nothing.
    rec.waiting = None
    rec.resume_at = None
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
        return "Nothing."
    if is_truncated(stored_input):
        return stored_input.get("summary") or (
            f"Too long to keep in full ({stored_input.get('chars')} characters).")
    return trigger_summary(stored_input) or "Nothing it could name."


def node_record_to_dict(rec) -> dict:
    """`NodeRecord`, contract C2 — and `P22-11`/`P22-12`'s two (C-W): `item`,
    the For-each index (null for a step's own record), and `waiting`
    (`{kind, since, until, approval}` while the step waits, else null).
    `B1854` adds `kept_from`: the id of the failed run a retry kept this
    record from, or null for a step that ran in this run."""
    stored_input = _loads(rec.input)
    steps = _loads(rec.steps)
    return {
        "kept_from": kept_from(rec),
        "item": getattr(rec, "item", None),
        "waiting": waiting_public(rec),
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


def dry_node_entries(db, run_id: str, graph: dict | None = None) -> list:
    """A workflow dry run's plan, one entry per step, breadth first — the
    shape wave B's chain dry run answers in (`chain` entries), for the
    `nodes` key of `POST /api/tasks/{id}/run?dry=true` on a workflow task:
    `{node_id, kind, name, when, depth, steps, declined}`, and `task_id` on a
    Run task step when `graph` (the document the plan was made from) is given
    — a step record keeps the plan, not the step's settings.

    `B1066`: `dry` on every entry — `action_dry_verdict`'s word for an Action
    step, read off `graph`, and `None` for any other step (or with no
    document) — as wave B's `chain` entries carry it."""
    from src.builtin_actions import action_dry_verdict

    targets = {}
    verdicts = {}
    for node in (graph or {}).get("nodes") or ():
        config = node.get("config") or {}
        if node.get("kind") == "run_task":
            targets[str(node.get("id"))] = config.get("task_id")
        verdicts[str(node.get("id"))] = action_dry_verdict(node.get("kind"), config.get("action"))
    out = []
    for rec in run_node_records(db, run_id):
        if not rec.dry:
            continue
        steps = _loads(rec.steps)
        entry = {
            "node_id": rec.node_id,
            "kind": rec.kind,
            "name": rec.label,
            "when": rec.reached_by,
            "depth": rec.depth if rec.depth is not None else 0,
            "steps": steps if isinstance(steps, list) else [],
            "declined": rec.error,
            "dry": verdicts.get(rec.node_id),
        }
        if rec.node_id in targets:
            entry["task_id"] = targets[rec.node_id]
        out.append(entry)
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
    from core.database import TaskRun, TaskRunNode, TASK_RUN_IN_FLIGHT_STATUSES

    days = node_records_days() if days is None else days
    cutoff = (now or _utcnow()) - timedelta(days=days)
    # `P22-11`. A parked run's finished records ARE its state (`run_state`): a
    # Wait of seven days under a one-day window would otherwise resume with
    # nothing to read. Records of a run still in flight are never pruned.
    in_flight = db.query(TaskRun.id).filter(TaskRun.status.in_(TASK_RUN_IN_FLIGHT_STATUSES))
    removed = (db.query(TaskRunNode)
               .filter(TaskRunNode.finished_at.isnot(None),
                       TaskRunNode.finished_at < cutoff,
                       ~TaskRunNode.run_id.in_(in_flight))
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


# ── `P22-11` / `P22-17` · a step that waits ─────────────────────────────────

def _waiting_of(rec) -> dict | None:
    raw = getattr(rec, "waiting", None)
    if not raw:
        return None
    value = _loads(raw)
    return value if isinstance(value, dict) else None


def waiting_public(rec) -> dict | None:
    """What a person may see of a waiting record (`C-W`): `{kind, since,
    until, approval, tool_label}` — `approval` the card's public payload (the
    sealed content shown verbatim, as every card shows it), never the session
    the card is bound to; `tool_label` (`B1111`) the card's tool as the step's
    panel names it."""
    waiting = _waiting_of(rec)
    if waiting is None or getattr(rec, "status", None) != "waiting":
        return None
    question = waiting.get("kind") == WAITING_APPROVAL
    return {
        "kind": waiting.get("kind"),
        "since": waiting.get("since"),
        "until": waiting.get("until"),
        "approval": waiting.get("card") if question else None,
        "tool_label": (waiting.get("tool_label") or None) if question else None,
    }


def record_node_waiting(db, rec, *, waiting: dict, resume_at: datetime | None = None,
                        steps=None, model: str | None = None) -> None:
    """Park one step's record: `waiting`, what it waits for as JSON, and — for
    a time — when the sweeper should wake it. Committed. `waiting["kind"]` is
    one of `WAITING_KINDS`; `since` is stamped here."""
    if waiting.get("kind") not in WAITING_KINDS:
        raise ValueError(f"not a waiting kind: {waiting.get('kind')!r}")
    body = dict(waiting)
    body.setdefault("since", _iso(_utcnow()))
    rec.status = "waiting"
    rec.waiting = json.dumps(body, default=str)
    rec.resume_at = resume_at
    rec.finished_at = None
    if model:
        rec.model = model
    if steps:
        try:
            rec.steps = json.dumps(list(steps), default=str)
        except (TypeError, ValueError):
            logger.warning("Could not serialise the step log of step record %s", rec.id)
    db.commit()


def record_node_resumed(db, rec) -> dict | None:
    """A waiting record runs again: `running`, one attempt more. Answers what
    it was waiting for (the JSON), so the walker can say so."""
    waiting = _waiting_of(rec)
    rec.status = "running"
    rec.attempt = (rec.attempt or 1) + 1
    rec.waiting = None
    rec.resume_at = None
    db.commit()
    return waiting


def record_node_attempt(db, rec) -> int:
    """`B1855`. A step (or an item) is tried again — its own retries: the
    record is `running` once more, what its last attempt ended with is
    cleared, and `attempt` counts one more (`record_node_resumed` counts a
    resume the same way). Committed. Answers the attempt it is on."""
    rec.status = "running"
    rec.attempt = (rec.attempt or 1) + 1
    rec.finished_at = None
    rec.port = None
    rec.error = None
    rec.output = None
    rec.waiting = None
    rec.resume_at = None
    db.commit()
    return rec.attempt


def end_running_items(db, run_id: str, node_id: str, *, error: str) -> int:
    """`B1855`. Every For-each item of this step still `running` — the one
    the step's time limit cut — ended `error`, with why. Committed. Answers
    how many."""
    from core.database import TaskRunNode

    rows = (db.query(TaskRunNode)
            .filter(TaskRunNode.run_id == run_id, TaskRunNode.node_id == node_id,
                    TaskRunNode.item.isnot(None), TaskRunNode.status == "running")
            .all())
    for rec in rows:
        rec.status = "error"
        rec.port = "error"
        rec.error = str(error)[:NODE_ERROR_MAX_CHARS]
        rec.finished_at = _utcnow()
    if rows:
        db.commit()
    return len(rows)


# ── `B1854` · a failed run, retried from one of its steps ───────────────────

#: The key on a copied record's first step-log line naming the run it was kept
#: from ("Kept from the run at 10:42"), read back as the record's `kept_from`.
KEPT_FROM_KEY = "kept_from"


def downstream_of(graph: dict, node_id: str) -> frozenset:
    """The ids of every step a path of arrows leads to from `node_id` — along
    any port — not `node_id` itself. `upstream_of`'s other direction."""
    leads = {}
    for edge in graph.get("edges") or ():
        leads.setdefault(edge.get("from"), set()).add(edge.get("to"))
    found, frontier = set(), [node_id]
    while frontier:
        following = []
        for current in frontier:
            for target in leads.get(current, ()):
                if target != node_id and target not in found:
                    found.add(target)
                    following.append(target)
        frontier = following
    return frozenset(found)


def retry_kept(records, graph: dict, node_id: str) -> list:
    """`B1854`. The failed run's records a retry from `node_id` keeps: every
    finished record of a step that is neither `node_id` nor after it — the
    steps before it and those beside it on other branches, whatever they
    did, so a step that worked (and sent its mail) is not run again — and,
    when `node_id` is a For-each, the items of it that worked. `node_id` and
    every step after it run again."""
    again = {node_id} | downstream_of(graph, node_id)
    kept = []
    for rec in records:
        if getattr(rec, "dry", False) or rec.status not in STEP_FINISHED:
            continue
        if rec.node_id in again:
            if rec.node_id == node_id and rec.item is not None and rec.status == "success":
                kept.append(rec)
            continue
        kept.append(rec)
    return kept


def copy_kept_records(db, *, run_id: str, records, from_run_id: str, words: str) -> int:
    """`B1854`. The kept records, copied into the retry as they ended — the
    same step, item, order, input, output and ending — each with `words`
    ("Kept from the run at 10:42") as the first line of its own log, under
    `KEPT_FROM_KEY`. The records ARE the run's state (`RunState`), so the
    walker treats them as finished and starts what is ready after them.
    Committed. Answers how many."""
    from core.database import TaskRunNode

    at = _iso(_utcnow())
    for rec in records:
        steps = _loads(rec.steps)
        line = {"kind": "progress", "detail": words, KEPT_FROM_KEY: from_run_id, "at": at}
        db.add(TaskRunNode(
            id=str(uuid.uuid4()), run_id=run_id, node_id=rec.node_id, kind=rec.kind,
            label=rec.label, item=rec.item, seq=rec.seq, status=rec.status,
            attempt=rec.attempt or 1, dry=False, port=rec.port, reached_by=rec.reached_by,
            depth=rec.depth, workflow_version=rec.workflow_version,
            started_at=rec.started_at, finished_at=rec.finished_at, input=rec.input,
            output=rec.output, error=rec.error, model=rec.model,
            steps=json.dumps([line, *(steps if isinstance(steps, list) else [])],
                             default=str)))
    db.commit()
    return len(records)


def kept_from(rec) -> str | None:
    """`B1854`. The run this record was kept from, for a record a retry
    copied; `None` for one that ran in its own run."""
    steps = _loads(rec.steps)
    for line in steps if isinstance(steps, list) else ():
        if isinstance(line, dict) and line.get(KEPT_FROM_KEY):
            return str(line[KEPT_FROM_KEY])
    return None


def end_waiting_records(db, run_id: str, *, status: str, error: str) -> int:
    """Every `waiting` record of this run ended `status` with `error` — the run
    was stopped, switched off, or aborted by a restart, so what its steps
    waited for will not come. Answers how many. Committed."""
    from core.database import TaskRunNode

    found = (db.query(TaskRunNode)
             .filter(TaskRunNode.run_id == run_id, TaskRunNode.status == "waiting").all())
    now = _utcnow()
    for rec in found:
        rec.status = status
        rec.error = str(error)[:NODE_ERROR_MAX_CHARS]
        rec.finished_at = now
        rec.waiting = None
        rec.resume_at = None
    if found:
        db.commit()
    return len(found)


def waiting_records(db, run_id: str) -> list:
    from core.database import TaskRunNode

    return (db.query(TaskRunNode)
            .filter(TaskRunNode.run_id == run_id, TaskRunNode.status == "waiting")
            .order_by(TaskRunNode.seq).all())


def waiting_of(rec) -> dict | None:
    """The waiting JSON of a record (server side: it includes the session)."""
    return _waiting_of(rec)


# ── `B1861` · what started a run, kept once, whole ──────────────────────────

def keep_run_trigger(run, trigger) -> None:
    """`B1861`. Write what started this run onto its row
    (`TaskRun.trigger_envelope`), once, when it starts. The caller commits.

    A parked run goes on in a new slot, so the walker read its trigger back
    from the input of a step the start leads to (`RunState.
    _trigger_from_records`) — a record held to `workflow_node_record_max_chars`
    and marked cut past it, so a resumed run of a large webhook read no trigger
    at all: `{{ steps.start.data… }}` after a Wait or a yes was null. The
    envelope is already held to `trigger_payload_max_chars` by `build_trigger`,
    so the row keeps it as it was handed."""
    if run is None or not isinstance(trigger, dict):
        return
    try:
        run.trigger_envelope = json.dumps(trigger, default=str)
    except (TypeError, ValueError):
        logger.warning("Could not keep the trigger of run %s", getattr(run, "id", "?"))


def stored_run_trigger(db, run_id: str) -> dict | None:
    """`B1861`. The trigger `keep_run_trigger` kept for this run, or `None` —
    a run that had none, or one from before the column."""
    from core.database import TaskRun

    try:
        row = (db.query(TaskRun.trigger_envelope)
               .filter(TaskRun.id == run_id).first())
    except Exception:
        logger.warning("Could not read the kept trigger of run %s", run_id, exc_info=True)
        return None
    value = _loads(row[0]) if row is not None and row[0] else None
    return value if isinstance(value, dict) else None


# ── `B674` · one workflow runs once at a time, written once ──────────────────

def run_in_flight(db, task_id: str, *, exclude: str | None = None):
    """The run of this task that is still going — queued, running or parked
    (`TASK_RUN_IN_FLIGHT_STATUSES`) — or `None`. `B674`'s one question: the
    scheduler asks it before a run starts, `run_task_now` and the webhook
    answer from it, and the email subprocess's guard asks it too
    (`event_bus._workflow_run_in_flight`). `exclude` is the asking run."""
    from core.database import TaskRun, TASK_RUN_IN_FLIGHT_STATUSES

    q = db.query(TaskRun).filter(TaskRun.task_id == task_id,
                                 TaskRun.status.in_(TASK_RUN_IN_FLIGHT_STATUSES))
    if exclude:
        q = q.filter(TaskRun.id != exclude)
    return q.order_by(TaskRun.started_at.desc()).first()


def parked_run(db, task_id: str, *, exclude: str | None = None):
    """The run of this task that is parked (`waiting`), or `None`."""
    from core.database import TaskRun, TASK_RUN_PARKED_STATUSES

    q = db.query(TaskRun).filter(TaskRun.task_id == task_id,
                                 TaskRun.status.in_(TASK_RUN_PARKED_STATUSES))
    if exclude:
        q = q.filter(TaskRun.id != exclude)
    return q.order_by(TaskRun.started_at.desc()).first()


def _clock(value: datetime | None, tz_name: str | None) -> str:
    """`07:00` on the task's clock (UTC when it has none)."""
    if value is None:
        return "?"
    try:
        from zoneinfo import ZoneInfo
        aware = value.replace(tzinfo=timezone.utc)
        if tz_name:
            aware = aware.astimezone(ZoneInfo(tz_name))
        return aware.strftime("%H:%M")
    except Exception:
        return value.strftime("%H:%M")


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def what_it_waits_for(db, run, *, tz_name: str | None = None) -> str:
    """"waiting for your yes on “Send reply”" / "waiting until 08:00" /
    "waiting for Pantheon to be idle" — the first waiting step's, in words."""
    for rec in waiting_records(db, run.id):
        waiting = _waiting_of(rec) or {}
        kind = waiting.get("kind")
        if kind == WAITING_APPROVAL:
            return f"waiting for your yes on “{rec.label or rec.node_id}”"
        if kind == WAITING_TIME:
            return f"waiting until {_clock(rec.resume_at, tz_name)}"
        if kind == WAITING_IDLE:
            return "waiting for Pantheon to be idle"
    return "waiting"


def parked_sentence(db, run, *, tz_name: str | None = None) -> str:
    """`B674`. Why a new trigger did not start a run: "Did not start: the 07:00
    run is still waiting for your yes on “Send reply”." One sentence for the
    `skipped` row, the webhook's 409 and Run now's (`Law 7`)."""
    return (f"Did not start: the {_clock(run.started_at, tz_name)} run is still "
            f"{what_it_waits_for(db, run, tz_name=tz_name)}.")


# ── `P22-11` · the records are the run state (`Law 7`) ──────────────────────

STEP_IN_PROGRESS = ("running", "waiting")
STEP_FINISHED = ("success", "error", "skipped", "aborted")
# The reserved start key, and the port its arrows leave by. Read from the
# document module (`START_KEY`) — the port is the success word every arrow
# out of the start has (`SLICE-CD-DESIGN` § 1.3).
_START_PORT = "success"


def _start_key() -> str:
    from src.workflow_document import START_KEY
    return START_KEY


def start_targets(graph: dict) -> list:
    """The ids of the steps the start leads to — `workflow_document.start_nodes`,
    the document rule's one answer (`Law 7`, `integrate-d`: the merge held
    three readings of it — here, `workflow_effects` and the rule): its explicit
    arrows (`P22-11` — the start can fan out), or, in a document with none,
    Slice B's implied entry (`Law 1`; the rule refuses more than one)."""
    from src.workflow_document import start_nodes
    return [n["id"] for n in start_nodes(graph)]


class RunState:
    """One run of one document, read from its records (`SLICE-CD-DESIGN`
    § 1.4). Pure over what it is handed: the graph, the run's real records,
    the trigger; the walker adds what finishes in this segment
    (`note_live`), so a step's full output is read while the run is in
    memory and its capped record after a resume.

      * an arrow has fired when a finished record of its source left by its
        port (an arrow from the start has always fired);
      * a step is ready when it has no record and at least one arrow into it
        has fired — or it is one the start leads to;
      * a Merge is ready when (`mode: first`) one input has arrived, or
        (`mode: all`) every input has arrived or can no longer arrive, and at
        least one has.
    """

    def __init__(self, graph: dict, records, *, trigger=None):
        self.graph = graph
        self.nodes = list(graph.get("nodes") or ())
        self.by_id = {n["id"]: n for n in self.nodes}
        self.edges = [e for e in graph.get("edges") or ()]
        self.start = _start_key()
        self.starts = start_targets(graph)
        self.own = {}
        self.items = {}
        for rec in records:
            if getattr(rec, "dry", False):
                continue
            if getattr(rec, "item", None) is None:
                prev = self.own.get(rec.node_id)
                if prev is None or (rec.seq or 0) >= (prev.seq or 0):
                    self.own[rec.node_id] = rec
            else:
                self.items.setdefault(rec.node_id, {})[rec.item] = rec
        self.trigger = trigger if trigger is not None else self._trigger_from_records()
        self.live = {}           # node id → {"text", "data"}, this segment
        self.finish_order = []   # node ids in the order they finished
        for rec in sorted((r for r in self.own.values() if r.status in STEP_FINISHED),
                          key=lambda r: (r.finished_at or datetime.min, r.seq or 0)):
            self.finish_order.append(rec.node_id)
        self._seq = max([r.seq or 0 for r in records] or [0])

    # ── reading ──────────────────────────────────────────────────────────────

    def _trigger_from_records(self):
        """After a restart the run's slot is gone; what fired it is the input
        of a step the start leads to (the records are the state)."""
        for node_id in self.starts:
            rec = self.own.get(node_id)
            if rec is None:
                continue
            value = _loads(rec.input)
            if isinstance(value, dict) and not is_truncated(value):
                return value
        return None

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def record(self, node_id: str):
        return self.own.get(node_id)

    def status(self, node_id: str):
        rec = self.own.get(node_id)
        return rec.status if rec is not None else None

    def note_live(self, node_id: str, *, text, data) -> None:
        self.live[node_id] = {"text": text or "", "data": data}
        if node_id not in self.finish_order:
            self.finish_order.append(node_id)

    def note_record(self, rec) -> None:
        """A record written or changed in this segment."""
        if getattr(rec, "item", None) is None:
            self.own[rec.node_id] = rec
        else:
            self.items.setdefault(rec.node_id, {})[rec.item] = rec

    def fired(self, edge: dict) -> bool:
        if edge.get("from") == self.start:
            return True
        rec = self.own.get(edge["from"])
        return (rec is not None and rec.status in STEP_FINISHED
                and rec.port == edge["port"])

    def _can_still_run(self, node_id: str, visiting=None) -> bool:
        """Might this step still finish and fire an arrow? Memoised per call."""
        rec = self.own.get(node_id)
        if rec is not None:
            return rec.status in STEP_IN_PROGRESS
        if node_id in self.starts:
            return True
        visiting = set() if visiting is None else visiting
        if node_id in visiting:
            return False
        visiting.add(node_id)
        try:
            return any(not self.dead(e, visiting) for e in self.incoming(node_id))
        finally:
            visiting.discard(node_id)

    def dead(self, edge: dict, visiting=None) -> bool:
        """Can this arrow no longer fire?"""
        if edge.get("from") == self.start:
            return False
        rec = self.own.get(edge["from"])
        if rec is not None:
            if rec.status in STEP_FINISHED:
                return rec.port != edge["port"]
            return False
        return not self._can_still_run(edge["from"], visiting)

    def incoming(self, node_id: str) -> list:
        return [e for e in self.edges if e.get("to") == node_id]

    def outgoing(self, node_id: str, port: str | None = None) -> list:
        return [e for e in self.edges if e.get("from") == node_id
                and (port is None or e.get("port") == port)]

    def is_merge(self, node: dict) -> bool:
        return node.get("kind") == "merge"

    def merge_mode(self, node: dict) -> str:
        mode = (node.get("config") or {}).get("mode")
        return "first" if mode == "first" else "all"

    def ready(self) -> list:
        """Steps that may start now, in the document's order."""
        out = []
        for node in self.nodes:
            node_id = node["id"]
            if node_id in self.own:
                continue
            incoming = self.incoming(node_id)
            arrived = [e for e in incoming if self.fired(e)]
            if self.is_merge(node):
                if not arrived:
                    continue
                if self.merge_mode(node) == "all" and not all(
                        self.fired(e) or self.dead(e) for e in incoming):
                    continue
                out.append(node)
            elif arrived or (node_id in self.starts and not incoming):
                out.append(node)
        return out

    def waiting(self) -> list:
        """Every record of this run that waits, its own and items'."""
        found = [r for r in self.own.values() if r.status == "waiting"]
        for by_item in self.items.values():
            found.extend(r for r in by_item.values() if r.status == "waiting")
        return found

    def in_progress(self) -> list:
        return [r for r in self.own.values() if r.status in STEP_IN_PROGRESS]

    # ── what a step is handed ────────────────────────────────────────────────

    def output_of(self, node_id: str) -> dict | None:
        """`{"text", "data"}` a finished step made: this segment's, whole; or
        its record's, capped — `None` for a record cut past the cap."""
        if node_id in self.live:
            return self.live[node_id]
        rec = self.own.get(node_id)
        if rec is None or rec.status not in STEP_FINISHED:
            return None
        out = _loads(rec.output)
        if out is None:
            return {"text": "", "data": None}
        if is_truncated(out) or not isinstance(out, dict):
            return None
        return {"text": out.get("text") or "", "data": out.get("data")}

    def truncated(self, node_id: str) -> bool:
        if node_id in self.live:
            return False
        rec = self.own.get(node_id)
        return rec is not None and is_truncated(_loads(rec.output))

    def context(self, *, item=None, has_item: bool = False, run_id=None,
                workflow=None) -> dict:
        """The pure-JSON context a reference reads (`workflow_refs`): every
        finished step's `{data, text, status}` and the start's. A step whose
        record was cut past `workflow_node_record_max_chars` after a resume
        has no `data` or `text`, so a reference into it is `MISSING`.
        `B1879`: and `{{ now }}` (read now, as the step starts) and
        `{{ run.id }}` / `{{ run.workflow }}` (`workflow_refs.run_roots`)."""
        from src.event_bus import trigger_summary
        from src.workflow_refs import run_roots

        steps = {}
        trigger = self.trigger if isinstance(self.trigger, dict) else None
        steps[self.start] = {
            "data": (trigger or {}).get("data") if trigger else None,
            "text": trigger_summary(trigger) if trigger else "",
            "status": "success",
        }
        for node_id, rec in self.own.items():
            if rec.status not in STEP_FINISHED and node_id not in self.live:
                continue
            out = self.output_of(node_id)
            entry = {"status": rec.status}
            if out is not None:
                entry["text"] = out.get("text") or ""
                entry["data"] = out.get("data")
            steps[node_id] = entry
        ctx = {"steps": json.loads(json.dumps(steps, default=str))}
        ctx.update(run_roots(run_id, workflow))
        if has_item:
            ctx["item"] = json.loads(json.dumps(item, default=str))
        return ctx

    def arrived_from(self, node_id: str) -> list:
        """The steps whose arrows into this one fired, in the order they
        finished (`finish_order`)."""
        sources = {e["from"] for e in self.incoming(node_id) if self.fired(e)}
        ordered = [n for n in self.finish_order if n in sources]
        ordered += [s for s in sources if s not in ordered]
        return ordered

    def merge_output(self, node_id: str) -> dict:
        """`{inputs: [{from, label, text, data}], missing: [{from, why}]}` in
        arrival order; a branch that failed or went another way is named under
        `missing`, with why."""
        inputs, missing = [], []
        for source in self.arrived_from(node_id):
            if source == self.start:
                continue
            out = self.output_of(source) or {}
            node = self.by_id.get(source) or {}
            inputs.append({"from": source, "label": node.get("label") or source,
                           "text": out.get("text") or "", "data": out.get("data")})
        for edge in self.incoming(node_id):
            if self.fired(edge):
                continue
            source = edge["from"]
            rec = self.own.get(source)
            if rec is None:
                why = "it was not reached"
            elif rec.status == "error":
                why = "it failed"
            elif rec.status == "skipped":
                why = "it was skipped"
            elif rec.status in STEP_IN_PROGRESS:
                why = "it had not finished"
            else:
                why = "it went another way"
            missing.append({"from": source, "why": why})
        return {"inputs": inputs, "missing": missing}

    # ── how the run ends (`Law 10`: one rule, written once) ──────────────────

    def unhandled_error(self):
        """The record of the last step that failed with no arrow out of its
        failure port, or `None`."""
        found = None
        for node_id in self.finish_order:
            rec = self.own.get(node_id)
            if rec is None or rec.status != "error":
                continue
            if not self.outgoing(node_id, "error"):
                found = rec
        return found

    def outcome(self):
        """`(status, text, failed_record)` for the whole run:
          * a branch that ended on an unhandled `error` → `error`;
          * every step `skipped` → `skipped`;
          * anything else → `success`.
        `text` is what the step that finished last made."""
        finished = [self.own[n] for n in self.finish_order if n in self.own]
        if not finished:
            return None, "", None
        last = finished[-1]
        out = self.output_of(last.node_id) or {}
        text = out.get("text") or (last.error or "")
        failed = self.unhandled_error()
        if failed is not None:
            return "error", text, failed
        if all(r.status == "skipped" for r in finished):
            return "skipped", text, None
        return "success", text, None
