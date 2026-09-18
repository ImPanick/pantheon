# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background scheduler for ScheduledTask execution."""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Tuple

from core.auth import RESERVED_USERNAMES
from src.event_bus import (
    EVENT_DOCUMENT_CREATED,
    EVENT_MEMORY_ADDED,
    EVENT_RESEARCH_COMPLETED,
    EVENT_SESSION_CREATED,
    EVENT_SKILL_ADDED,
    trigger_context_message as _trigger_context_message,
    trigger_summary as _trigger_summary,
)
from src.owner_identity import REQUEST_SENTINEL_OWNERS
from src.task_action_policy import (
    is_admin_only_task_action,
    owner_has_admin_task_privileges,
    record_admin_refusal,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return naive UTC for task DB fields without using deprecated APIs."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Run-slot concurrency (P6-08) ────────────────────────────────────────────
# How many *model-backed* task runs may hold the run slot at once. Was a bare
# `Semaphore(1)` with `_concurrency_cap = 1` beside it, commented "a hard
# guarantee, not configurable".
#
# What the semaphore actually guarantees, measured against this file: it bounds
# how many runs share the inference backend. It is NOT what stops a task from
# running twice — two paths already skip it entirely (`_task_needs_model_slot`
# lets pure housekeeping actions through, and `run_task_now(force=True)` passes
# `bypass_model_slot=True`), so "exactly one task runs at a time" was already
# untrue before this knob existed.
#
# THE INVARIANT THAT IS PRESERVED, and it is a different one: **a single task
# never runs twice concurrently.** That is held by `_executing` under
# `_executing_lock` — claimed in `_check_due_tasks` and `_run_chained`,
# released in `_execute_task`'s `finally` — and is completely independent of
# this cap. Raising the cap lets *different* tasks overlap; it cannot make one
# task overlap itself.
#
# ONE EXCEPTION, and it predates this knob: `run_task_now(force=True)` neither
# checks nor adds to `_executing` and passes `release_executing=False`, so a
# forced manual trigger CAN overlap the same task with itself. That is what
# `force` means, and the button that reaches it is deliberate. Recorded here
# because an earlier version of this comment listed `run_task_now` among the
# claimants, which made the invariant read as absolute when it is not.
#
# Resolution order is the one P12-01 sets out in .pantheon/ROADMAP.md:
#   role profile → instance setting → env → built-in default
# It is implemented once, in `settings.resolve_limit`, and this module names its
# key, its variable, its default and its clamp. The role-profile layer does not
# exist yet (it is P11-02's to build) — `settings.role_limit` is the single
# place it plugs in, for every limit at once.
TASK_CONCURRENCY_CAP_SETTING = "task_concurrency_cap"
TASK_CONCURRENCY_CAP_ENV = "PANTHEON_TASK_CONCURRENCY_CAP"
TASK_CONCURRENCY_CAP_DEFAULT = 1
# Upper bound. Each concurrent run holds a model slot on the inference backend,
# so an unbounded value is a self-inflicted outage on a single-GPU host.
TASK_CONCURRENCY_CAP_MAX = 16

# ── `P8-26` · the graph document ────────────────────────────────────────────
#
# A workflow in this engine is one nullable column: `ScheduledTask.then_task_id`,
# "run this next if the last one succeeded". That is a graph — a path — and
# nothing in the product ever said so, so nothing could draw it, validate it or
# extend it. `P8-34` wants to render one, `P8-27` wants runs on one and `P8-28`
# wants a second edge out of a node.
#
# So this projects what already exists rather than storing a second copy of it
# (`Law 14`): the successor IS the edge, read at request time, and there is no
# new column, no migration and no way for a stored graph to disagree with the
# stored chain. Everything that works today keeps working because nothing about
# how a chain runs has moved.
#
# **The depth cap is the part nobody could see.** `_has_chain_cycle` walked ten
# steps and returned "cycle" when it ran out, so an eleven-step chain was
# refused under a name that describes a different thing entirely. It is a real
# limit of this engine; it now has a name, a reason and a place on the wire.
CHAIN_MAX_DEPTH = 10
EDGE_WHEN_SUCCESS = "success"
# `P8-28`. The second condition, and the first conditional this engine has ever
# had that is not "did it work". `then_task_id` runs on success and
# `else_task_id` runs on anything else, which is the whole branch: a workflow
# could say what comes next and never what to do when the step failed, so a
# failure ended the chain and the person found out from an Activity row.
#
# These are the RUN's own statuses and not a new set of words (`Law 14`):
# `success` is `TaskRun.status == "success"` and `error` is the other terminal
# outcome a finished run can carry here. `skipped`, `aborted` and a deferred
# run do not reach the branch at all — they return before it, unchanged.
EDGE_WHEN_ERROR = "error"
EDGE_CONDITIONS = (EDGE_WHEN_SUCCESS, EDGE_WHEN_ERROR)
# Which column carries which condition. One table, so the projection, the
# engine and the validator cannot disagree about what `else` means.
EDGE_COLUMNS = {
    EDGE_WHEN_SUCCESS: "then_task_id",
    EDGE_WHEN_ERROR: "else_task_id",
}

CHAIN_CYCLE = "cycle"
CHAIN_TOO_DEEP = "too_deep"
CHAIN_CROSS_OWNER = "cross_owner"
# `Law 10`: the reason is an enum and the sentence is derived from it, so the
# log line and the wire cannot describe the same refusal differently.
CHAIN_REFUSAL_REASONS = {
    CHAIN_CYCLE: "the chain loops back on itself",
    CHAIN_TOO_DEEP: f"the chain is longer than {CHAIN_MAX_DEPTH} steps",
    CHAIN_CROSS_OWNER: "the chain reaches another owner's task",
}


def task_edges(task) -> list:
    """The edges leaving one task, in `EDGE_CONDITIONS` order.

    Derived entirely from the two successor columns — there is no second place
    an edge can be stored, which is the whole point of projecting rather than
    storing a graph. Zero, one or two entries.
    """
    edges = []
    for when in EDGE_CONDITIONS:
        successor = getattr(task, EDGE_COLUMNS[when], None)
        if successor:
            edges.append({"from": task.id, "to": successor, "when": when})
    return edges


def build_task_graph(tasks) -> dict:
    """Nodes, edges and the limits, for a set of tasks the caller already has.

    Takes the rows rather than a session, so the one place that lists tasks can
    hand its own query in and there is no second query returning a different
    set (`Law 7`). An edge pointing outside the set is kept and marked
    `dangling` — a chain to a task the caller cannot see is a real fact about
    the workflow, and dropping it would draw a graph that ends for no reason.
    """
    nodes = []
    edges = []
    known = set()
    for task in tasks:
        known.add(task.id)
        nodes.append({
            "id": task.id,
            "name": getattr(task, "name", None),
            "task_type": getattr(task, "task_type", None) or "llm",
            "action": getattr(task, "action", None),
            "status": getattr(task, "status", None),
        })
    for task in tasks:
        for edge in task_edges(task):
            edge = dict(edge)
            edge["dangling"] = edge["to"] not in known
            edges.append(edge)
    return {
        "nodes": nodes,
        "edges": edges,
        "conditions": list(EDGE_CONDITIONS),
        "max_depth": CHAIN_MAX_DEPTH,
    }


# `P12-01` removed two private helpers from this module and nothing else moved:
# `_coerce_concurrency_cap` (parse, clamp, warn) is `settings._coerce_limit`, and
# `_role_concurrency_cap` (the empty role hook) is `settings.role_limit`. Both
# were private to this file, both had zero references anywhere else in the tree,
# and both now exist once for every limit in the product rather than once for
# this one (`Law 14`). The public names, the four `source` strings and the
# clamp bounds are unchanged.


def resolve_task_concurrency_cap(owner: str | None = None) -> Tuple[int, str]:
    """Return (cap, source) for the scheduler's model-run slot.

    Order: role profile → instance setting → env → built-in default.
    Always returns a value in [1, TASK_CONCURRENCY_CAP_MAX].

    `H06`. The instance-setting layer here read `get_setting(KEY, None)` and
    treated a non-None answer as an operator's choice. `get_setting` calls
    `load_settings`, which merges `DEFAULT_SETTINGS` on **every** read — so it
    could not return None, returned the shipped 1, and every layer below it was
    unreachable code from first boot on a machine with no settings file at all.
    The env var had therefore never worked on any install. `setting_is_explicit`
    is the question that line was trying to ask, and `settings.resolve_limit`
    now asks it for every limit in the product.
    """
    from src.settings import resolve_limit
    return resolve_limit(
        TASK_CONCURRENCY_CAP_SETTING, TASK_CONCURRENCY_CAP_DEFAULT,
        env_name=TASK_CONCURRENCY_CAP_ENV, owner=owner,
        minimum=1, maximum=TASK_CONCURRENCY_CAP_MAX,
        label="Task concurrency cap",
    )


# Shell/file tools a scheduled task's agent should be offered by default,
# mirroring the chat agent (where these are on unless a privilege or global
# setting turns them off). The RAG tool selector + ASSISTANT_ALWAYS_AVAILABLE
# never include bash/python, so on a host with an empty/degraded tool-embedding
# index a task could not run shell or Python even for an admin owner. Offering
# them here is safe: stream_agent_loop's blocked_tools_for_owner() still strips
# this whole group for non-admin multi-user owners, and only admits it for
# admins and single-user (AUTH_ENABLED=false) deployments.
TASK_DEFAULT_SHELL_TOOLS = frozenset({
    "bash", "python", "read_file", "write_file", "edit_file",
    "grep", "glob", "ls", "get_workspace",
})


def compose_task_relevant_tools(rag_tools, assistant_always, disabled_tools):
    """Compose the relevant-tools set offered to a scheduled task's agent.

    Unions the RAG-retrieved tools, the assistant's always-available set, and
    the default shell/file group, then removes anything the task's crew
    explicitly disabled via its `enabled_tools` allowlist. Per-owner admin
    gating is applied later by stream_agent_loop (blocked_tools_for_owner).
    """
    tools = set(rag_tools) | set(assistant_always) | set(TASK_DEFAULT_SHELL_TOOLS)
    if disabled_tools:
        tools -= set(disabled_tools)
    return tools


# ── Shared TTL cache (singleflight) ────────────────────────────────────────
# Multiple scheduled tasks firing in the same minute often need the same
# external data (Miniflux unreads, MCP tool snapshots, etc.). This cache
# deduplicates those fetches — in-flight requests for the same key await the
# same underlying coroutine, and completed results are reused until TTL expiry.
_shared_cache: Dict[Tuple, Tuple[float, Any]] = {}
_shared_cache_pending: Dict[Tuple, asyncio.Future] = {}
_shared_cache_lock = asyncio.Lock()


async def _cached(key: Tuple, ttl: float, fetch: Callable[[], Awaitable[Any]]) -> Any:
    """Return a cached result for `key` if fresh, else call `fetch()` and store.

    Concurrent callers for the same missing key share one `fetch()` call.
    Exceptions propagate to every waiter and do not poison the cache.
    """
    now = time.monotonic()
    async with _shared_cache_lock:
        entry = _shared_cache.get(key)
        if entry and entry[0] > now:
            return entry[1]
        fut = _shared_cache_pending.get(key)
        if fut is not None:
            pending = fut
            owner = False
        else:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            _shared_cache_pending[key] = fut
            pending = fut
            owner = True
    if not owner:
        # A cancelled waiter must not cancel the shared Future for the owner
        # and every other waiter.
        return await asyncio.shield(pending)
    try:
        val = await fetch()
        async with _shared_cache_lock:
            _shared_cache[key] = (time.monotonic() + ttl, val)
        pending.set_result(val)
        return val
    except asyncio.CancelledError:
        # Cancellation is a BaseException on supported Python versions, so it
        # bypasses the Exception handler below. Wake all current waiters while
        # allowing a later caller to retry the fetch.
        pending.cancel()
        raise
    except Exception as e:
        pending.set_exception(e)
        raise
    finally:
        # Keep this cleanup synchronous so a second cancellation cannot
        # interrupt it and leave a permanently pending Future behind. All
        # access runs on the scheduler's event-loop thread.
        if _shared_cache_pending.get(key) is pending:
            _shared_cache_pending.pop(key, None)


# ── P15-08 · the floor under a schedule, and the brake under a failure ──────
#
# `routes/task/task_routes.py` validated cron SYNTAX and nothing else, against a
# free-text field. `* * * * *` was accepted: 1,440 runs a day, each one able to
# open IMAP, walk the whole search-provider chain and call a model API. `P15`
# exists because the owner's IP was soft-banned by this product in an afternoon;
# a minute-by-minute task is that, scheduled.
#
# Five minutes, and the number is a floor rather than a recommendation. At one a
# minute a task is a scraper; at five it is 288 runs a day, which is still more
# than any of this product's own seeded jobs and enough for anything local. The
# precedent is on the row: `check_email_urgency` shipped at `*/15` and was walked
# back to hourly with a migration, so this exact failure has already cost this
# product once.
#
# A setting, with `0` meaning no floor, because an operator running entirely
# against their own LAN is entitled to a one-minute task and `Law 1` says the
# capability stays — what changes is what you get by not thinking about it.
MIN_TASK_INTERVAL_SECONDS = 300
# How far a failing task is pushed out, doubling per consecutive failure. The
# ladder is `rate_limiter.penalise`'s, deliberately: same shape, same cap, so
# there is one idea of "back off" in this product and not two (`Law 14`).
FAILURE_BACKOFF_BASE_SECONDS = 300
FAILURE_BACKOFF_CAP_SECONDS = 6 * 60 * 60


def min_task_interval_seconds() -> int:
    """The floor, in seconds. `0` means an operator turned it off."""
    try:
        from src.settings import get_setting
        minutes = int(get_setting("min_task_interval_minutes",
                                  MIN_TASK_INTERVAL_SECONDS // 60))
    except Exception:
        return MIN_TASK_INTERVAL_SECONDS
    return max(0, minutes) * 60


def cron_interval_seconds(cron_expression: str, *, samples: int = 24) -> float | None:
    """The SHORTEST gap between two consecutive firings of this expression.

    Not "the interval" — a cron expression need not have one. `0,1,30 * * * *`
    fires three times an hour with a one-minute gap in it, and reading only the
    first two firings, or dividing an hour by three, both miss that. The
    expression is stepped and the smallest gap wins, which is the only number a
    floor can honestly be compared against.

    `None` when croniter cannot parse it — that is the syntax check's answer to
    give, not this one's.
    """
    try:
        from croniter import croniter
        # A fixed base, so the answer does not depend on when it is asked.
        base = datetime(2026, 1, 5, 0, 0, 0)
        it = croniter(cron_expression, base)
        prev = it.get_next(datetime)
        smallest = None
        for _ in range(max(2, samples)):
            nxt = it.get_next(datetime)
            gap = (nxt - prev).total_seconds()
            if gap > 0 and (smallest is None or gap < smallest):
                smallest = gap
            prev = nxt
        return smallest
    except Exception:
        return None


def cron_floor_problem(cron_expression: str) -> str | None:
    """The sentence a user reads when their schedule is too fast, or `None`.

    A refusal that only says *"too frequent"* sends someone back to the same
    field to guess. This names what they asked for, what the floor is, and the
    setting that moves it — because a limit whose remedy is unstated reads as a
    bug in the product rather than a decision it made.
    """
    floor = min_task_interval_seconds()
    if not floor or not cron_expression:
        return None
    gap = cron_interval_seconds(cron_expression)
    if gap is None or gap >= floor:
        return None
    return (
        f"That schedule runs every {_human_gap(gap)}, and the minimum is "
        f"{_human_gap(floor)}. A task can open a mailbox, search the web and "
        f"call a model on every run, and at that rate providers rate-limit or "
        f"block the account — Pantheon has done it to its own owner once. "
        f"Use a slower schedule, or change min_task_interval_minutes in "
        f"Settings if this task only touches your own machines."
    )


def consecutive_failures(db, task_id: str, *, before_run_id: str = None,
                         limit: int = 16) -> int:
    """How many times in a row this task has just failed.

    Read from `task_runs` rather than from a new column: the history is already
    written, already indexed by `(task_id, started_at)`, and a counter on the
    task would be a second copy of it that can disagree (`Law 14`).

    `before_run_id` excludes the run being processed right now, because its row
    is updated in an unflushed session and would otherwise be counted or not
    depending on autoflush. The caller adds the current failure itself, which
    is the arithmetic being explicit instead of implicit.

    `queued`/`running` rows are skipped rather than treated as a success: an
    in-flight or stuck row says nothing about whether the last finished attempt
    worked. `skipped` and `aborted` are not failures and are not successes
    either — they end the streak only in the sense that they are not part of it,
    so they stop the count rather than resetting it to zero.
    """
    from core.database import TaskRun

    q = (db.query(TaskRun.id, TaskRun.status)
           .filter(TaskRun.task_id == task_id)
           .order_by(TaskRun.started_at.desc(), TaskRun.id.desc())
           .limit(limit))
    n = 0
    for run_id, status in q.all():
        if before_run_id and run_id == before_run_id:
            continue
        if status in ("queued", "running"):
            continue
        if status == "error":
            n += 1
            continue
        break
    return n


def failure_backoff_seconds(failures: int) -> float:
    """Escalating, jittered, capped. The ladder `rate_limiter` already uses.

    Jittered through `src/jitter.py` for `P15-10`'s reason and not a new one: a
    provider that rate-limits everyone at once is the synchronising event, and a
    fleet of Pantheons all retrying a failed task at exactly 5, 10 and 20
    minutes past the outage is the herd arriving three times.
    """
    from src.jitter import jittered

    failures = max(1, int(failures))
    delay = min(FAILURE_BACKOFF_BASE_SECONDS * (2 ** (failures - 1)),
                FAILURE_BACKOFF_CAP_SECONDS)
    return jittered(delay, fraction=0.2)


def _human_gap(seconds: float) -> str:
    seconds = int(seconds)
    if seconds % 3600 == 0 and seconds >= 3600:
        n = seconds // 3600
        return "hour" if n == 1 else f"{n} hours"
    if seconds % 60 == 0:
        n = seconds // 60
        return "minute" if n == 1 else f"{n} minutes"
    return f"{seconds} seconds"


def apply_interval_floor(next_run: datetime | None,
                         after: datetime | None = None) -> datetime | None:
    """Push a next run out to the floor. The half that covers rows already here.

    Refusing `* * * * *` at the API stops NEW ones; it does nothing about a task
    created before this shipped, seeded by a migration, or written straight into
    the database. Those are paced rather than broken (`Law 1`): the schedule the
    user set still runs, just not more often than the floor.
    """
    floor = min_task_interval_seconds()
    if next_run is None or not floor:
        return next_run
    earliest = (after or _utcnow()) + timedelta(seconds=floor)
    return max(next_run, earliest)


def compute_next_run(schedule: str, scheduled_time: str,
                     scheduled_day: int = None,
                     scheduled_date: datetime = None,
                     after: datetime = None,
                     cron_expression: str = None,
                     tz_name: str = None) -> datetime | None:
    """Compute the next run datetime (stored as naive UTC) based on schedule type.

    If `tz_name` is provided (IANA zone, e.g. "America/New_York"), `scheduled_time` /
    `scheduled_day` are interpreted as local wall-clock time in that zone and
    the result is converted to naive UTC for DB storage. If `tz_name` is None,
    the legacy behavior (`scheduled_time` interpreted as naive-UTC wall clock)
    is preserved so existing tasks don't shift.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None

    tz = None
    if tz_name and ZoneInfo is not None:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = None

    # "now" used for comparisons. When tz is set we work entirely in local tz
    # and convert to UTC at the end. Otherwise we use naive UTC (legacy).
    if tz is not None:
        now_utc = after or _utcnow()
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        now = now_utc.astimezone(tz)
    else:
        now = after or _utcnow()

    def _to_utc_naive(dt: datetime) -> datetime:
        """Convert a tz-aware datetime to naive UTC for DB storage."""
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    if schedule == "cron" and cron_expression:
        try:
            from croniter import croniter
            cron = croniter(cron_expression, now)
            nxt = cron.get_next(datetime)
            if tz is not None and nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=tz)
            out = _to_utc_naive(nxt) if tz is not None else nxt
            # `P15-08`. The floor applies to what is ALREADY in the database as
            # well as to what the API will accept from here on — a `* * * * *`
            # row created before this shipped is paced, not broken.
            return apply_interval_floor(out, after=(after or _utcnow()))
        except Exception as e:
            logger.warning(f"Invalid cron expression '{cron_expression}': {e}")
            return None

    if schedule == "once":
        if scheduled_date and scheduled_date > (_to_utc_naive(now) if tz is not None else now):
            return scheduled_date
        return None

    if not scheduled_time:
        return None

    # Parse HH:MM — fail closed on malformed input (no colon, non-numeric,
    # out-of-range) the same way an invalid cron expression does above, so a
    # bad value like "9" or "9am" returns None instead of raising IndexError/
    # ValueError out of the create route (a 500) or the scheduler loop.
    parts = scheduled_time.split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("hour/minute out of range")
    except (ValueError, IndexError):
        logger.warning(f"Invalid scheduled_time '{scheduled_time}'")
        return None

    if schedule == "daily":
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return _to_utc_naive(candidate) if tz is not None else candidate

    if schedule == "weekly":
        day = scheduled_day if scheduled_day is not None else 0  # 0=Monday
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = day - candidate.weekday()
        if days_ahead < 0 or (days_ahead == 0 and candidate <= now):
            days_ahead += 7
        candidate += timedelta(days=days_ahead)
        return _to_utc_naive(candidate) if tz is not None else candidate

    if schedule == "monthly":
        day = scheduled_day if scheduled_day is not None else 1
        try:
            candidate = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            # Short month: clamp to its last day (mirrors the next-month
            # clamp below) instead of silently skipping the whole month.
            if now.month == 12:
                last = now.replace(year=now.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                last = now.replace(month=now.month + 1, day=1) - timedelta(days=1)
            candidate = last.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)
            try:
                candidate = next_month.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError:
                if next_month.month == 12:
                    last = next_month.replace(year=next_month.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    last = next_month.replace(month=next_month.month + 1, day=1) - timedelta(days=1)
                candidate = last.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return _to_utc_naive(candidate) if tz is not None else candidate

    return None


def _resolve_task_timezone(db, task) -> str | None:
    """Look up the IANA timezone name for a task via its linked CrewMember, if any."""
    if not getattr(task, "crew_member_id", None):
        return None
    try:
        from core.database import CrewMember
        cm = db.query(CrewMember).filter(CrewMember.id == task.crew_member_id).first()
        if cm and cm.timezone:
            return cm.timezone
    except Exception:
        pass
    return None


# `P8-30`. The event names below are `src.event_bus` constants, not strings
# spelled again here. These five were the loose spellings a merge of "the two
# catalogues" would have walked straight past — they are stored in
# `ScheduledTask.trigger_event` and join against it, so the VALUES are
# unchanged and `FORBIDDEN.md` Part 1 still holds; only the spelling moved.
# Built-in "housekeeping" tasks seeded for every owner, keyed by action.
# These are the canonical defaults — used both to seed and to revert a
# built-in task the user has altered. schedule "daily" uses scheduled_time;
# "cron" uses cron_expression.
HOUSEKEEPING_DEFAULTS = {
    "tidy_sessions":        {"name": "Chat Sessions Tidy",       "trigger_type": "event", "trigger_event": EVENT_SESSION_CREATED, "trigger_count": 5, "schedule": None, "scheduled_time": None, "cron_expression": None, "legacy_names": ["Tidy Chat Sessions"]},
    "tidy_documents":       {"name": "Documents Tidy",           "trigger_type": "event", "trigger_event": EVENT_DOCUMENT_CREATED, "trigger_count": 5, "schedule": None, "scheduled_time": None, "cron_expression": None, "legacy_names": ["Tidy Documents"]},
    "consolidate_memory":   {"name": "Memory Tidy",              "trigger_type": "event", "trigger_event": EVENT_MEMORY_ADDED, "trigger_count": 5, "schedule": None, "scheduled_time": None, "cron_expression": None, "legacy_names": ["Tidy Memory"]},
    "tidy_research":        {"name": "Research Tidy",            "trigger_type": "event", "trigger_event": EVENT_RESEARCH_COMPLETED, "trigger_count": 5, "schedule": None, "scheduled_time": None, "cron_expression": None, "legacy_names": ["Tidy Research"]},
    "summarize_emails":     {"name": "Email (Summary)",          "schedule": "cron",  "scheduled_time": None,    "cron_expression": "0 */2 * * *", "ship_paused": True, "legacy_names": ["Tidy Email (Summary)"]},
    "draft_email_replies":  {"name": "Email AI Auto Reply",      "schedule": "cron",  "scheduled_time": None,    "cron_expression": "0 */2 * * *", "ship_paused": True, "legacy_names": ["Tidy Email (Replies)", "AI Auto Reply"]},
    "email_auto_translate": {"name": "Email Auto Translate",     "schedule": "cron",  "scheduled_time": None,    "cron_expression": "0 */2 * * *", "ship_paused": True, "legacy_names": ["Auto-translate Emails", "Auto Translate Email"]},
    "extract_email_events": {"name": "Email Calendar Events",    "schedule": "cron",  "scheduled_time": None,    "cron_expression": "0 */1 * * *", "ship_paused": True, "legacy_names": ["Email → Calendar Events"]},
    "classify_events":      {"name": "Calendar Classify Events", "schedule": "cron",  "scheduled_time": None,    "cron_expression": "0 6,18 * * *", "ship_paused": True, "legacy_names": ["Classify Calendar Events"]},
    "check_email_urgency":   {"name": "Email Tags",               "schedule": "cron",  "scheduled_time": None,    "cron_expression": "0 * * * *", "ship_paused": True, "old_cron_expressions": ["*/15 * * * *"], "legacy_names": ["Email Triage", "Urgent Email"]},
    "audit_skills":          {"name": "Skills Audit",             "trigger_type": "event", "trigger_event": EVENT_SKILL_ADDED, "trigger_count": 5, "schedule": None, "scheduled_time": None, "cron_expression": None, "legacy_names": ["Audit Skills"]},
}

RETIRED_HOUSEKEEPING_ACTIONS = frozenset({
    "tidy_calendar",
    "tidy_email_inbox",
    "mark_email_boundaries",
})


# `P15-10`. How long a due task waits before it actually starts.
#
# Scaled to the task's OWN period rather than being a flat number, because the
# herd this exists to break is hourly-and-slower — the seeded email jobs on
# minute `0` — while a `* * * * *` task delayed by half a minute would start
# skipping periods once its own runtime is added. Five percent of the period,
# capped, gives a minute-cadence task a couple of seconds and an hourly one a
# useful spread.
DISPATCH_JITTER_FRACTION = 0.05
DISPATCH_JITTER_CAP_SECONDS = 45.0
# When the period cannot be worked out — a malformed cron, a one-shot, an event
# task deferred onto `next_run` — a few seconds is still better than none, and
# is short enough to be safe against any cadence.
DISPATCH_JITTER_FALLBACK_SECONDS = 5.0


def _task_period_seconds(task, *, now=None):
    """Seconds between this task's runs, or None when it cannot be derived."""
    now = now or _utcnow()
    try:
        nxt = compute_next_run(
            schedule=task.schedule,
            scheduled_time=task.scheduled_time,
            scheduled_day=task.scheduled_day,
            scheduled_date=task.scheduled_date,
            after=now,
            cron_expression=task.cron_expression,
            tz_name=getattr(task, "tz_name", None),
        )
    except Exception:
        return None
    if not nxt:
        return None
    seconds = (nxt - now).total_seconds()
    return seconds if seconds > 0 else None


def dispatch_hold(task, *, now=None) -> float:
    """The spread for one due task. Zero is a legitimate answer."""
    from src.jitter import spread
    period = _task_period_seconds(task, now=now)
    if period is None:
        return spread(DISPATCH_JITTER_FALLBACK_SECONDS)
    return spread(min(DISPATCH_JITTER_CAP_SECONDS, period * DISPATCH_JITTER_FRACTION))


def _digest_windows(now):
    """(label, start, end) buckets for the calendar check-in digest.

    The windows are contiguous so no event is dropped between buckets — an
    earlier version started the 30-day window at now+8d while the week window
    ended at now+7d, so events ~7-8 days out fell into no bucket.
    """
    return [
        ("today_tomorrow", now, now + timedelta(days=2)),
        ("this_week", now + timedelta(days=2), now + timedelta(days=7)),
        ("next_30_days", now + timedelta(days=7), now + timedelta(days=30)),
    ]


def _checkin_calendar_events(db, owner, start, end):
    """Calendar events in [start, end] for ONE owner, for the check-in digest.

    Ownership lives on CalendarCal.owner; events inherit it via calendar_id.
    The digest query had no owner scope, so it pulled EVERY user's events into
    one user's check-in (a cross-tenant leak of summaries/locations). Scope it
    by joining CalendarCal, mirroring routes/calendar_routes.list_events.
    """
    from core.database import CalendarEvent as _CE, CalendarCal as _CC
    return (
        db.query(_CE)
        .join(_CC, _CE.calendar_id == _CC.id)
        .filter(
            _CC.owner == owner,
            _CE.dtstart >= start,
            _CE.dtstart <= end,
            _CE.status != "cancelled",
        )
        .order_by(_CE.dtstart)
        .all()
    )


def _normalize_chat_endpoint(url: str) -> str:
    """Repair a resolved task endpoint to a full chat-completions URL.

    Unlike the chat path — which stores ``build_chat_url(normalize_base(base))``
    on the session — the task executor passes ``task.endpoint_url`` verbatim to
    the model HTTP call. A bare OpenAI-compatible base such as
    ``http://host:11434/v1`` therefore POSTs to a 404 ("page not found") and the
    model silently appears to "return an empty response".

    Repair only bare OpenAI-compatible bases. Native-Ollama URLs (``/api...``)
    and URLs that already point at a concrete endpoint are returned untouched, so
    their own downstream normalizers keep working. Idempotent: a URL already
    ending in ``/chat/completions`` is left as-is.
    """
    if not url:
        return url
    # Imports kept function-local (endpoint_resolver pulls in heavy deps) but
    # OUTSIDE the try: an import failure is a real bug that should surface, not
    # be silently swallowed into the un-normalized URL this function exists to
    # repair.
    from urllib.parse import urlparse
    from src.endpoint_resolver import normalize_base, build_chat_url
    path = (urlparse(url).path or "").rstrip("/")
    if path == "/api" or path.startswith("/api/"):
        return url  # native Ollama — handled by the native path downstream
    if path.endswith(("/chat/completions", "/messages", "/responses", "/completions")):
        return url  # already a concrete endpoint
    try:
        return build_chat_url(normalize_base(url))
    except Exception:
        # Guard only the actual normalization. Returning the URL un-normalized
        # reverts to the 404 this fixes, so make the silent revert visible.
        logger.debug("task endpoint normalization failed for %r; using as-is", url, exc_info=True)
        return url


class TaskScheduler:
    def __init__(self, session_manager):
        self._session_manager = session_manager
        self._running = False
        self._task = None
        self._executing = set()  # task IDs currently running OR queued behind the semaphore
        # Guards mutations of _executing. _check_due_tasks runs in the loop
        # coroutine; trigger_task() can be called from request handlers; the
        # event bus fires from background tasks. Without this lock long-running
        # tasks could be double-dispatched.
        self._executing_lock = asyncio.Lock()
        self._pending_notifications = []  # completed task notifications
        self._task_defer_counts = {}
        # Model-run slot. At the default cap of 1 this is the historical
        # behaviour: one model-backed run at a time, everything else (manual
        # trigger, scheduled dispatch, task chain) waits behind it as "queued"
        # and starts when the current run finishes. Configurable since P6-08 —
        # see the resolver above for the order, and for which invariant this
        # does and does not hold. Re-read in start() so an operator does not
        # need a process restart to change it.
        self._concurrency_cap, self._concurrency_cap_source = resolve_task_concurrency_cap()
        self._run_semaphore = asyncio.Semaphore(self._concurrency_cap)
        # Permits currently in circulation on `_run_semaphore`. Tracked
        # separately because `asyncio.Semaphore` does not expose its own count
        # and because a permit a run is holding is still in circulation.
        self._slot_permits = self._concurrency_cap
        self._slot_drain = None
        self._task_handles = {}
        # `P8-27` / `B603`. Per-run state, keyed by run.
        #
        # `_last_run_model` and `_last_run_steps` were single instance
        # attributes, so which model a run resolved and what it did were
        # recorded in one slot shared by every run on this scheduler. That is
        # sound at `TASK_CONCURRENCY_CAP_DEFAULT`, which is 1. It is an operator
        # setting with a ceiling of 16, and at any value above one two runs
        # write the same slot between the executor returning and the row being
        # committed: run A gets stamped with run B's model and B's step log.
        # Nothing in the tree measured it, so the only symptom was a run history
        # that occasionally described the wrong run.
        #
        # A dict and not a lock, because the state is not contended — it is
        # simply mis-addressed. `run_id` is the address. `None` is a legitimate
        # key for a call made outside `_execute_task_locked` (the agent loop
        # driven directly by a test, a future node runner with no row yet), so
        # that case records somewhere real instead of into the previous run.
        self._run_state = {}

    def _refresh_concurrency_cap(self) -> int:
        """Re-resolve the cap and make the new number the one that governs.

        `P6-08`. This used to say "safe only while no run holds the semaphore"
        and to REBUILD the semaphore, and both halves were the row: rebuilding
        under load drops the waiters parked on the old object, so the only
        caller it could have was `start()`, so the resolver's answer was fixed
        at boot and "configurable without a restart" was not true. The cap is
        now moved by adding and retiring permits on the SAME object, which the
        waiters are parked on, so this is safe to call from the running loop —
        and it is, once per tick.
        """
        cap, source = resolve_task_concurrency_cap()
        changed = cap != self._concurrency_cap
        self._concurrency_cap, self._concurrency_cap_source = cap, source
        if changed:
            logger.info(
                "Task concurrency cap is now %d (from %s)", cap, source)
            self._sync_run_slot()
        return cap

    def _sync_run_slot(self) -> None:
        """Move the live slot to `self._concurrency_cap`.

        Raising is immediate: `release()` on an `asyncio.Semaphore` adds a
        permit above its initial value and wakes a waiter, so a run queued
        behind the old cap starts at once rather than after the run ahead of
        it finishes.

        LOWERING CANNOT BE IMMEDIATE and pretending otherwise is what the old
        rebuild did. A permit held by a run in flight is not ours to take, so
        the surplus is retired by *acquiring* it — which parks behind the runs
        already using it and hands nothing back. The effect is a drain: no run
        is killed, and the slot narrows as work finishes.
        """
        while self._slot_permits < self._concurrency_cap:
            self._run_semaphore.release()
            self._slot_permits += 1
        if self._slot_permits <= self._concurrency_cap:
            return
        if self._slot_drain is not None and not self._slot_drain.done():
            return                      # a drain is already converging on it
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop: construction, or a synchronous caller. Nothing can be
            # holding the slot, so the exact object is safe to rebuild and the
            # drain would have nothing to wait for anyway.
            self._run_semaphore = asyncio.Semaphore(self._concurrency_cap)
            self._slot_permits = self._concurrency_cap
            return
        self._slot_drain = loop.create_task(self._drain_run_slot())

    async def _drain_run_slot(self) -> None:
        """Retire surplus permits one at a time, then re-apply any raise that
        landed while we were waiting."""
        try:
            while self._slot_permits > self._concurrency_cap:
                await self._run_semaphore.acquire()   # retired, never released
                self._slot_permits -= 1
        finally:
            # A raise during the drain released permits this loop then took
            # back; converge rather than leave the slot one short.
            while self._slot_permits < self._concurrency_cap:
                self._run_semaphore.release()
                self._slot_permits += 1

    def _set_run_progress(self, run_id: str, message: str):
        """Persist short live progress text for Activity while a run is active."""
        if not run_id:
            return
        try:
            from core.database import SessionLocal, TaskRun, TASK_RUN_ACTIVE_STATUSES
            db = SessionLocal()
            try:
                run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if run and run.status in TASK_RUN_ACTIVE_STATUSES:
                    run.result = (message or "")[:4000]
                    db.commit()
            finally:
                db.close()
        except Exception:
            logger.debug("Task progress update failed", exc_info=True)

    # `P8-25`. A run's step log. `TaskRun.steps` was declared on the model and
    # never written, so a run recorded one result string for the whole task and
    # the Activity view could say a task succeeded without ever saying what it
    # touched. Both executors feed this: an action through the progress
    # callback it is already handed, an LLM task through the agent loop's own
    # tool events.
    #
    # Capped, because this is JSON in a row somebody loads to read a summary. A
    # forty-round agent run with a chatty tool would otherwise put a megabyte
    # of tool output behind every click in Activity.
    _MAX_RUN_STEPS = 200
    _MAX_STEP_DETAIL = 400

    # `P8-27`. Every accessor below takes the run's id. There is no
    # "the current run" on a scheduler that can hold sixteen of them.

    def _runs(self) -> dict:
        """The slot table, created on demand.

        `__init__` makes it; this exists because a scheduler built with
        `__new__` and hand-set attributes is how several tests drive one
        executor without a whole engine, and the two attributes this replaces
        were read through `getattr(..., None)` for exactly that reason.
        """
        state = getattr(self, "_run_state", None)
        if state is None:
            state = {}
            self._run_state = state
        return state

    def _state_for(self, run_id):
        """This run's slot, created on first write."""
        runs = self._runs()
        state = runs.get(run_id)
        if state is None:
            state = {"model": None, "steps": [], "trigger": None}
            runs[run_id] = state
        return state

    def _clear_run_state(self, run_id) -> None:
        """Drop a finished run's slot. Called on every exit from a run."""
        self._runs().pop(run_id, None)

    def run_steps(self, run_id) -> list:
        """This run's step log so far. Empty for a run that recorded none."""
        state = self._runs().get(run_id)
        return list(state["steps"]) if state else []

    def run_model(self, run_id):
        """The model this run actually resolved on, once an executor says."""
        state = self._runs().get(run_id)
        return state["model"] if state else None

    def run_trigger(self, run_id):
        """What fired this run — the `P8-23` envelope, or `None` for a schedule.

        On the run's slot rather than threaded through four signatures, because
        a trigger payload is a fact about the run and `P8-27` just gave a run
        somewhere to keep its facts.
        """
        state = self._runs().get(run_id)
        return state["trigger"] if state else None

    def set_run_model(self, run_id, model) -> None:
        self._state_for(run_id)["model"] = model

    def _record_run_step(self, run_id, **fields):
        """Append one step to a run's log.

        `P8-25` put this on the instance beside `_last_run_model`, in the same
        shape and for the same reason — one place the executors write and
        `_execute_task_locked` reads (`Law 14`). `B603` recorded what that shape
        cost above a concurrency cap of one. `P8-27` keys it by run, which is
        the same one place, correctly addressed.
        """
        steps = self._state_for(run_id)["steps"]
        if len(steps) >= self._MAX_RUN_STEPS:
            return None
        for key in ("detail", "output"):
            value = fields.get(key)
            if isinstance(value, str) and len(value) > self._MAX_STEP_DETAIL:
                fields[key] = value[: self._MAX_STEP_DETAIL].rstrip() + "\u2026"
        fields.setdefault("at", _utcnow().isoformat() + "Z")
        steps.append(fields)
        return fields

    def _close_run_step(self, run_id, *, tool, round_, status, output):
        """Finish the most recent open step for this tool and round.

        A `tool_output` with no matching `tool_start` still records: the point
        of the log is what happened, and a tool whose start event was missed is
        exactly the case somebody opens it to understand.
        """
        state = self._runs().get(run_id)
        for step in reversed(state["steps"] if state else []):
            if (step.get("kind") == "tool" and step.get("status") == "running"
                    and step.get("tool") == tool and step.get("round") == round_):
                step["status"] = status
                if output:
                    step["output"] = output[: self._MAX_STEP_DETAIL]
                return
        self._record_run_step(run_id, kind="tool", tool=tool or "?", round=round_,
                              status=status, output=output or "")

    def _advance_chain(self, db, task, run_status: str, run_id: str) -> None:
        """Follow the edge this run's outcome matches, if there is one.

        `P8-28`. The engine's only conditional was `status == "success"` and it
        was written inline, so a workflow could say what comes next and never
        what to do when the step failed: the failure ended the chain, and the
        only trace was an Activity row. The branch is `EDGE_COLUMNS` — one
        table naming which column carries which condition — so the projection
        (`task_edges`), the engine and the route validator cannot disagree
        about what `else` means.

        Success behaves exactly as it did. What is new is that `error` now has
        an edge it can take, and that the decision is one function called from
        both the ordinary path and the exception path — an LLM task that RAISED
        used to leave the chain untouched while an action that RETURNED a
        failure would at least have been considered, which is the same workflow
        behaving two ways depending on how the failure was expressed.
        """
        from core.database import ScheduledTask

        when = run_status if run_status in EDGE_CONDITIONS else None
        chain_id = getattr(task, EDGE_COLUMNS[when], None) if when else None
        if not chain_id:
            return
        chain_task = db.query(ScheduledTask).filter(
            ScheduledTask.id == chain_id).first()
        if not chain_task or chain_task.owner != task.owner:
            logger.warning(
                "Skipping chain from %r: target task %s is missing or not owned by %r",
                task.name, chain_id, task.owner,
            )
            self._record_chain_outcome(
                db, run_id,
                f"Did not continue to the next task: {chain_id} is missing "
                f"or belongs to somebody else")
            return
        refusal = self._chain_refusal(db, chain_id, owner=task.owner)
        label = chain_task.name or chain_id
        lead = "Continued to" if when == EDGE_WHEN_SUCCESS else "Failed, so continued to"
        if refusal is None:
            logger.info("Chaining on %s: %r → task %s", when, task.name, chain_id)
            self._record_chain_outcome(db, run_id, f"{lead} {label}")
            asyncio.create_task(self._run_chained(chain_id))
            return
        # `P8-26`. This said "cycle detected" for all three reasons, including
        # a chain that is simply longer than `CHAIN_MAX_DEPTH` and has no cycle
        # in it.
        logger.warning("Skipping chain from %r: %s",
                       task.name, CHAIN_REFUSAL_REASONS[refusal])
        # `P8-26` / `Law 15`. The depth cap is a real limit of this engine and
        # the ONLY trace of it was a server log line naming the wrong cause.
        # Whoever built the workflow is not reading the log; they are looking at
        # a chain that stopped at step ten for no stated reason. It is in the
        # run's own step log now, in the words the enum resolves to, so the two
        # cannot drift apart.
        self._record_chain_outcome(
            db, run_id,
            f"Did not continue to {label}: {CHAIN_REFUSAL_REASONS[refusal]}")

    def _record_chain_outcome(self, db, run_id, detail: str) -> None:
        """Append one step about what happened AFTER this run finished.

        `P8-26`. The chain decision is taken after the run row has already been
        written and committed, so a step recorded there would never reach the
        row without this. It re-reads the run, re-attaches the log and commits
        again — three cheap statements on a path that runs once per chained
        task, against a line somebody needs in order to understand why their
        workflow stopped.
        """
        from core.database import TaskRun

        self._record_run_step(run_id, kind="progress", detail=detail)
        try:
            run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
            if run is not None:
                self._attach_run_steps(run_id, run)
                db.commit()
        except Exception:
            # The run itself is finished and committed; losing the last line of
            # its log must not turn a successful run into an error.
            logger.debug("Could not record the chain outcome for run %s",
                         run_id, exc_info=True)

    def _attach_run_steps(self, run_id, run) -> None:
        """Persist this run's step log onto its row, if anything recorded one."""
        state = self._runs().get(run_id)
        steps = state["steps"] if state else None
        if run is None or not steps:
            return
        try:
            run.steps = json.dumps(steps)
        except (TypeError, ValueError):
            # A step carried something json cannot represent. The run's own
            # status and result are unaffected and still have to be committed,
            # so the log is dropped rather than the run — but it is said out
            # loud, because an empty step log reads exactly like a run that did
            # nothing at all.
            logger.warning("Could not serialise the step log for run %s",
                           getattr(run, "id", "?"))

    def _mark_run_aborted(self, task_id: str, run_id: str | None = None, message: str = "Stopped by user") -> bool:
        """Mark an active run as aborted. Used by stop/cancel paths."""
        try:
            from core.database import SessionLocal, TaskRun, TASK_RUN_ACTIVE_STATUSES
            db = SessionLocal()
            try:
                q = db.query(TaskRun)
                if run_id:
                    q = q.filter(TaskRun.id == run_id)
                else:
                    q = q.filter(
                        TaskRun.task_id == task_id,
                        TaskRun.status.in_(TASK_RUN_ACTIVE_STATUSES),
                    ).order_by(TaskRun.started_at.desc())
                run = q.first()
                if not run or run.status not in TASK_RUN_ACTIVE_STATUSES:
                    return False
                run.status = "aborted"
                run.error = message
                run.result = run.result or message
                run.finished_at = _utcnow()
                db.commit()
                return True
            finally:
                db.close()
        except Exception:
            logger.debug("Task abort marker failed for %s", task_id, exc_info=True)
            return False

    def add_notification(self, task_name: str, status: str, task_id: str = None, owner: str = None, body: str = None):
        """Store a notification about a completed task run. Tagged with the
        task's owner so `pop_notifications` can return only that user's
        notifications and prevent cross-tenant drain. `body` is the result
        text — populated when output_target='notification' so the client can
        show a rich browser Notification, not just a toast."""
        self._pending_notifications.append({
            "task_name": task_name,
            "status": status,
            "task_id": task_id,
            "owner": owner,
            "body": (body[:500] + "…") if body and len(body) > 500 else body,
            "timestamp": _utcnow().isoformat() + "Z",
        })
        # Cap at 50 to avoid unbounded growth
        if len(self._pending_notifications) > 50:
            self._pending_notifications = self._pending_notifications[-50:]

    def _notify_run_outcome(self, task, status: str, *, body: str = None,
                            task_id: str = None,
                            quiet_for_actions: bool = False) -> bool:
        """Queue a notification for a terminal run — if the vocabulary says so.

        `B112`. Which outcomes are worth telling the owner about is stated once,
        in `core.database.TASK_RUN_NOTIFY`, with a reason per status. Before
        this, the answer was three `return`s: `except TaskNoop` and `except
        asyncio.CancelledError` both left `_execute_task_locked` before the
        notify block, so no `skipped` and no `aborted` notification had ever
        been emitted and nothing on the tree said whether that was deliberate.

        Every terminal branch calls this now, including the aborted one that
        stays quiet. The silence is the policy's answer rather than an
        omission's, which is what makes flipping an entry in that table change
        what a person sees.

        The two gates after the policy are about NOISE, not about the outcome.
        `notifications_enabled` is the owner's per-task opt-out.
        `quiet_for_actions` is the rule that already shipped for `success`:
        housekeeping actions do not toast. Neither is honoured for `error` —
        that branch predates this and shouts regardless, and taking that away
        would be a subtraction (`Law 1`).
        """
        from core.database import TASK_RUN_NOTIFY

        allowed, _why = TASK_RUN_NOTIFY.get(status, (False, ""))
        if not allowed or task is None:
            return False
        if not getattr(task, "notifications_enabled", True):
            return False
        if quiet_for_actions and \
                (getattr(task, "task_type", None) or "llm") not in {"llm", "research"}:
            return False
        self.add_notification(
            task.name, status, task_id or getattr(task, "id", None),
            owner=task.owner, body=body,
        )
        return True

    def pop_notifications(self, owner: str = None) -> list:
        """Return and clear pending notifications.

        When `owner` is set, only matching notifications are returned (and
        cleared). Notifications stored before owner-tagging existed (or
        from owner-less tasks) are included when the caller is anonymous
        or when no owner filter is given — preserves backward behaviour
        for the legacy single-user deploy.
        """
        if owner is None:
            notes = self._pending_notifications[:]
            self._pending_notifications.clear()
            return notes
        # Strict owner scope — used to OR-in null-owner notifications for
        # "legacy single-user" compat but that leaked notification bodies to
        # any authenticated user once a second account existed.
        keep, take = [], []
        for n in self._pending_notifications:
            if n.get("owner") == owner:
                take.append(n)
            else:
                keep.append(n)
        self._pending_notifications = keep
        return take

    async def start(self):
        # Re-read the concurrency cap here, not just in __init__: the scheduler
        # is constructed at import/wiring time, so a settings change made after
        # boot would otherwise need a full process restart to take effect.
        # Nothing holds the semaphore yet at this point. `_check_due_tasks`
        # re-reads it every tick as well (`P6-08`); this call is what makes the
        # start-up log line report the cap the first dispatch will actually use.
        self._refresh_concurrency_cap()
        # On startup, mark any leftover "running" task_runs as aborted. Without
        # this, a server crash leaves rows stuck running indefinitely and the
        # _executing in-memory set forgets them, so the UI shows phantoms.
        try:
            from core.database import SessionLocal, TaskRun, TASK_RUN_ACTIVE_STATUSES
            db = SessionLocal()
            try:
                # Zombies from a prior server crash. Tagged "aborted" (not
                # "error") so the Activity view + error-rate stats don't
                # falsely blame the task for what was an infrastructure event.
                stale = db.query(TaskRun).filter(
                    TaskRun.status.in_(TASK_RUN_ACTIVE_STATUSES)
                ).all()
                if stale:
                    now = _utcnow()
                    for r in stale:
                        old_status = r.status or "running"
                        r.status = "aborted"
                        r.error = "Server restarted while task was " + old_status
                        r.finished_at = now
                    db.commit()
                    logger.info(f"Cleared {len(stale)} stale task_runs from previous run")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Could not clear stale task_runs on startup: {e}")

        # Advance next_run for active tasks whose next_run is already in the
        # past. Without this, a restart hits _check_due_tasks() with an empty
        # in-process _executing set, and the same overdue task fires once per
        # poll until it completes.
        try:
            from core.database import SessionLocal as _SL, ScheduledTask as _ST
            db = _SL()
            try:
                now = _utcnow()
                overdue = db.query(_ST).filter(
                    _ST.status == "active",
                    _ST.next_run.isnot(None),
                    _ST.next_run < now,
                ).all()
                if overdue:
                    for t in overdue:
                        t.next_run = now + timedelta(seconds=60)
                    db.commit()
                    logger.info(
                        "Pushed next_run forward by 60s for %d overdue active tasks on startup",
                        len(overdue),
                    )
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Could not advance overdue next_run on startup: {e}")

        # Defense-in-depth dedupe sweep: for any owner with >1 rows where
        # is_default_assistant=True, keep the oldest and demote the rest +
        # delete their orphaned check-in tasks. This is the safety net for
        # the synthetic-owner seeding bug (we cleaned a manual instance of
        # it, but a stale code path or DB import could recreate it).
        try:
            from core.database import SessionLocal, CrewMember, ScheduledTask
            db = SessionLocal()
            try:
                from sqlalchemy import func
                groups = db.query(CrewMember.owner, func.count(CrewMember.id).label("n")).filter(
                    CrewMember.is_default_assistant == True,  # noqa: E712
                ).group_by(CrewMember.owner).having(func.count(CrewMember.id) > 1).all()
                for owner, n in groups:
                    rows = db.query(CrewMember).filter(
                        CrewMember.owner == owner,
                        CrewMember.is_default_assistant == True,  # noqa: E712
                    ).order_by(CrewMember.created_at.asc()).all()
                    keep = rows[0]
                    losers = rows[1:]
                    loser_ids = [r.id for r in losers]
                    # Delete the orphaned tasks tied to the loser crews — they
                    # are duplicates of the keeper's check-ins.
                    n_tasks = db.query(ScheduledTask).filter(
                        ScheduledTask.crew_member_id.in_(loser_ids)
                    ).delete(synchronize_session=False)
                    for r in losers:
                        db.delete(r)
                    db.commit()
                    logger.warning(
                        "Default-assistant dedupe: owner=%r had %d rows, kept %s, "
                        "dropped %d crew + %d orphan tasks",
                        owner, n, keep.id, len(losers), n_tasks,
                    )
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Could not dedupe default-assistant rows on startup: {e}")

        self._running = True
        self._task = asyncio.create_task(self._loop())
        # Internal background scanner that isn't a user-facing "task" — pure
        # infra (no LLM), shouldn't clutter the Tasks UI, fires on its own
        # cadence inside the scheduler process.
        #
        # Calendar event reminders are represented as Notes by the calendar UI,
        # so the Notes scanner is the single reminder dispatch path. Running the
        # old event scanner too caused duplicate emails/notifications for the
        # same calendar event.
        self._note_pings_task = asyncio.create_task(self._note_pings_loop())
        logger.info(
            "Task scheduler started (concurrency cap: %d, from %s)",
            self._concurrency_cap, self._concurrency_cap_source,
        )
        # Audit clusters: show any minute-of-day where >1 active scheduled
        # tasks land. Helps spot "all my tasks fire at 9am" patterns the user
        # may want to spread out.
        try:
            from core.database import SessionLocal, ScheduledTask
            db = SessionLocal()
            try:
                rows = db.query(ScheduledTask).filter(
                    ScheduledTask.status == "active",
                    ScheduledTask.trigger_type == "schedule",
                    ScheduledTask.next_run.isnot(None),
                ).all()
                buckets: Dict[str, list] = {}
                for r in rows:
                    if not r.next_run:
                        continue
                    key = r.next_run.strftime("%H:%M")
                    buckets.setdefault(key, []).append(r.name or r.id)
                clusters = {k: v for k, v in buckets.items() if len(v) > 1}
                if clusters:
                    summary = ", ".join(f"{k} ({len(v)})" for k, v in sorted(clusters.items()))
                    logger.info(f"Task scheduling clusters (>1 task/minute): {summary}")
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"Cluster audit skipped: {e}")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for attr in ("_note_pings_task", "_event_pings_task"):
            t = getattr(self, attr, None)
            if t:
                t.cancel()
                try: await t
                except asyncio.CancelledError: pass
        logger.info("Task scheduler stopped")

    async def _note_pings_loop(self):
        """Built-in note-due scanner — ticks every 60s inside the scheduler.
        Pure infra (no LLM), doesn't surface in the Tasks UI. Iterates
        per-owner so cache pruning in `action_ping_notes` (which removes
        cache entries for notes not in the current scan's seen_ids) doesn't
        cross-delete other users' entries (review C4).
        """
        # `P15-10` — the startup offset is jittered too, or every install that
        # restarts after the same provider outage lines back up on the way in.
        from src.jitter import sleep_jittered
        await sleep_jittered(30)
        from src.builtin_actions import action_ping_notes, TaskNoop
        while self._running:
            owners = self._known_task_owners()
            for ow in (owners or [""]):
                try:
                    await action_ping_notes(owner=ow)
                except TaskNoop:
                    pass
                except Exception as e:
                    logger.warning(f"ping_notes background scanner errored for owner={ow!r}: {e}")
            await sleep_jittered(60)  # 1 min, spread

    async def _event_pings_loop(self):
        """Built-in calendar-event scanner — same recipe as note pings. Runs
        every 10 min, fires reminders via dispatch_reminder. Not a user task.
        Iterates per-owner so each user only gets their own calendar pings
        (passing owner="" globally would email User B's events to User A's
        configured SMTP "from" address — see review C3).
        """
        from src.jitter import sleep_jittered
        await sleep_jittered(90)
        from src.builtin_actions import action_ping_events, TaskNoop
        while self._running:
            owners = self._known_task_owners()
            for ow in (owners or [""]):
                try:
                    await action_ping_events(owner=ow)
                except TaskNoop:
                    pass
                except Exception as e:
                    logger.warning(f"ping_events background scanner errored for owner={ow!r}: {e}")
            await sleep_jittered(600)  # 10 min, spread

    def _known_task_owners(self) -> list:
        """Distinct non-empty owners that background scanners should visit.

        Scheduled tasks used to be the only owner source. Calendar reminders
        are stored as Notes, though, so an account with due notes but no task
        rows could get the browser reminder while the backend email/ntfy
        scanner never ran for that owner.
        """
        from core.database import SessionLocal, ScheduledTask, Note
        db = SessionLocal()
        try:
            owners = set()
            for r in db.query(ScheduledTask.owner).distinct().all():
                if r[0]:
                    owners.add(r[0])
            note_q = db.query(Note.owner).filter(
                Note.due_date.isnot(None),
                Note.due_date != "",
                Note.archived == False,  # noqa: E712
            ).distinct()
            for r in note_q.all():
                if r[0]:
                    owners.add(r[0])
            return sorted(owners)
        except Exception:
            return []
        finally:
            db.close()

    async def _loop(self):
        await asyncio.sleep(10)
        while self._running:
            try:
                await self._check_due_tasks()
            except Exception:
                logger.exception("Error in task scheduler loop")
            # Sleep until the next scheduled run, capped at 60s. A `* * * * *`
            # cron task previously fired up to ~60s late because we always
            # slept the full minute; now the loop wakes near the boundary.
            sleep_for = 60.0
            try:
                from core.database import SessionLocal as _SL, ScheduledTask as _ST
                _db = _SL()
                try:
                    next_run = _db.query(_ST.next_run).filter(
                        _ST.status == "active",
                        _ST.next_run.isnot(None),
                    ).order_by(_ST.next_run.asc()).first()
                    if next_run and next_run[0]:
                        delta = (next_run[0] - _utcnow()).total_seconds()
                        sleep_for = max(1.0, min(60.0, delta))
                finally:
                    _db.close()
            except Exception:
                pass
            await asyncio.sleep(sleep_for)

    async def _check_due_tasks(self):
        # `P6-08`. The settings-change path for this cap is every tick, not a
        # hook on one writer. `save_settings` has ~20 call sites (the admin
        # endpoint, the agent's own `manage_settings`, a backup restore) and
        # `data/settings.json` is also hand-edited — a listener on any one of
        # them is `Law 13`'s defect class. Re-resolving here costs one cached
        # settings read per tick and cannot miss a writer, including one that
        # does not exist yet.
        self._refresh_concurrency_cap()
        from core.database import SessionLocal, ScheduledTask
        db = SessionLocal()
        try:
            now = _utcnow()
            foreground_active = False
            try:
                from src.interactive_gate import has_foreground_activity
                foreground_active = has_foreground_activity()
            except Exception:
                foreground_active = False
            async with self._executing_lock:
                # Snapshot under the lock so we don't race with mid-iteration adds.
                executing_snapshot = set(self._executing)
                # Scheduled tasks and deferred event tasks both use next_run.
                due = db.query(ScheduledTask).filter(
                    ScheduledTask.status == "active",
                    ScheduledTask.next_run <= now,
                    ScheduledTask.id.notin_(executing_snapshot) if executing_snapshot else True,
                ).all()
                to_dispatch = []
                for task in due:
                    if task.id in self._executing:
                        continue
                    if foreground_active:
                        task.next_run = now + timedelta(minutes=15)
                        continue
                    self._executing.add(task.id)
                    to_dispatch.append((task.id, dispatch_hold(task, now=now)))
                if foreground_active and due:
                    db.commit()
            for task_id, hold in to_dispatch:
                asyncio.create_task(self._dispatch_after(task_id, hold))
        finally:
            db.close()

    async def _dispatch_after(self, task_id: str, hold: float) -> None:
        """Hold a scheduled task briefly, then run it (`P15-10`).

        The seeded housekeeping tasks all sit on minute `0` of the hour, and
        they are email and calendar jobs — so every install with the same
        provider knocks at the same instant. Jittering here rather than in the
        shipped cron expressions covers user-created tasks too, and needs no
        migration of a schedule somebody may have edited.

        It is NOT in `_execute_task`, deliberately: that is also the manual
        "Run now" path, where a person is watching and a spread-out start reads
        as a button that did not work.

        The id is already in `self._executing`, so the hold cannot cause a
        second dispatch of the same task.
        """
        if hold > 0:
            try:
                await asyncio.sleep(hold)
            except asyncio.CancelledError:
                self._executing.discard(task_id)
                raise
        await self._execute_task(task_id)

    async def _execute_task(self, task_id: str, *, bypass_model_slot: bool = False,
                            release_executing: bool = True, trigger: dict | None = None):
        # Create the run record with status="queued" BEFORE waiting on the
        # semaphore so the UI can show that a manually-triggered task is in
        # line behind another. Once we acquire the slot, flip to "running"
        # and hand off to _execute_task_locked.
        from core.database import SessionLocal, TaskRun
        current = asyncio.current_task()
        if current:
            self._task_handles[task_id] = current
        run_id = str(uuid.uuid4())
        _q_db = SessionLocal()
        try:
            run = TaskRun(
                id=run_id,
                task_id=task_id,
                started_at=_utcnow(),
                status="queued",
                result="Queued — waiting for a free slot…",
            )
            _q_db.add(run)
            _q_db.commit()
        except Exception:
            logger.exception(f"Failed to create queued run row for task {task_id}")
        finally:
            _q_db.close()

        try:
            if bypass_model_slot or not self._task_needs_model_slot(task_id):
                await self._execute_task_locked(
                    task_id,
                    run_id,
                    release_executing=release_executing,
                    gate_foreground=not bypass_model_slot,
                    trigger=trigger,
                )
                return

            async with self._run_semaphore:
                await self._execute_task_locked(
                    task_id,
                    run_id,
                    release_executing=release_executing,
                    gate_foreground=True,
                    trigger=trigger,
                )
        except asyncio.CancelledError:
            # If cancellation happens while queued behind the semaphore,
            # _execute_task_locked never runs and cannot update the Activity row.
            self._mark_run_aborted(task_id, run_id)
            self._defer_immediately_due_task(task_id, delay=timedelta(minutes=15))
            raise
        finally:
            handle = self._task_handles.get(task_id)
            if handle is current:
                self._task_handles.pop(task_id, None)
            if release_executing:
                async with self._executing_lock:
                    self._executing.discard(task_id)

    def _defer_immediately_due_task(self, task_id: str, *, delay: timedelta):
        """A queued task can be cancelled before _execute_task_locked gets a DB
        handle. If its next_run stays in the past, the scheduler dispatches it
        again on the next tick and spams aborted Activity rows."""
        try:
            from core.database import SessionLocal, ScheduledTask
            db = SessionLocal()
            try:
                task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
                if (
                    task
                    and task.status == "active"
                    and task.next_run is not None
                    and task.next_run <= _utcnow()
                ):
                    task.next_run = _utcnow() + delay
                    db.commit()
            finally:
                db.close()
        except Exception:
            logger.debug("Failed to defer cancelled queued task %s", task_id, exc_info=True)

    async def _execute_task_locked(
        self,
        task_id: str,
        run_id: str,
        *,
        release_executing: bool = True,
        gate_foreground: bool = True,
        trigger: dict | None = None,
    ):
        from core.database import SessionLocal, ScheduledTask, TaskRun

        db = SessionLocal()
        try:
            task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            if not task or task.status != "active":
                # Task was paused/deleted while queued — record that outcome
                # so the run row doesn't sit as "queued" forever.
                stale = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if stale and stale.status == "queued":
                    stale.status = "skipped"
                    stale.finished_at = _utcnow()
                    stale.error = f"Task no longer active (status={task.status if task else 'deleted'})"
                    db.commit()
                    # `B112`. The task is paused or gone, so this run is the last
                    # thing that will happen on it and nothing else will say so.
                    # A deleted task has no name and no owner to notify.
                    self._notify_run_outcome(task, "skipped", body=stale.error,
                                             task_id=task_id)
                return

            if (
                is_admin_only_task_action(task.task_type, task.action)
                and not owner_has_admin_task_privileges(task.owner)
            ):
                # `skipped`, not `error` — the action never ran, so by the
                # vocabulary in core/database.py this is not a failure. Recorded
                # through the shared helper because the webhook path in
                # routes/task/task_routes.py enforces the same rule and used to
                # record nothing at all.
                _refusal = record_admin_refusal(db, task, run_id=run_id)
                logger.warning(
                    "Paused admin-only task %s for non-admin owner %r",
                    task_id,
                    task.owner,
                )
                # `B112`. `record_admin_refusal` PAUSES the task: it will not run
                # again until somebody re-enables it. `B07` had to leave this
                # silent because the client called every non-`success` status a
                # failure; `B78` fixed the client, so the owner gets told what
                # actually happened instead of finding a stopped task later.
                self._notify_run_outcome(task, "skipped", body=_refusal,
                                         task_id=task_id)
                return

            if gate_foreground:
                waiting = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if waiting and waiting.status == "queued":
                    waiting.result = "Queued — waiting for Pantheon to be idle…"
                    db.commit()
                from src.interactive_gate import wait_for_interactive_quiet
                await wait_for_interactive_quiet(f"scheduled task {task.name}")

            # Flip the run from queued → running. Reset started_at to the
            # actual execution start so queue wait time is visible from
            # created_at vs started_at if we ever surface that.
            run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
            if run:
                run.status = "running"
                run.started_at = _utcnow()
                run.result = "Starting…"
                db.commit()
            else:
                # Defensive: row may have been wiped; recreate so the rest of
                # the code can look it up by run_id without crashing.
                run = TaskRun(
                    id=run_id,
                    task_id=task.id,
                    started_at=_utcnow(),
                    status="running",
                    result="Starting…",
                )
                db.add(run)
                db.commit()

            task_type = task.task_type or "llm"

            from src.builtin_actions import TaskDeferred, TaskNoop

            # `P8-23`. What fired this run, recorded before anything it does —
            # so the first line of the step log is the cause and the rest is the
            # effect. The run's slot carries the envelope for the executors.
            if trigger:
                self._state_for(run_id)["trigger"] = trigger
                self._record_run_step(
                    run_id, kind="trigger",
                    detail=_trigger_summary(trigger),
                )
            # `P8-27`. Nothing to clear: this run's slot is keyed by `run_id`
            # and is created empty on first write. The two lines that used to be
            # here reset a shared attribute so an action task would not inherit
            # the previous llm/research run's model — which worked only because
            # one run existed at a time. A run's slot is dropped in the `finally`
            # below, so a scheduler that has been up for a week holds state for
            # the runs in flight and no others.
            foreground_cancel = {"hit": False}
            foreground_monitor = None
            if gate_foreground:
                current_task = asyncio.current_task()

                async def _cancel_if_foreground_active():
                    # Give the just-finished quiet gate a tiny grace window,
                    # then keep enforcing "background means background" while
                    # a long email/LLM action is already running.
                    await asyncio.sleep(0.1)
                    from src.interactive_gate import has_foreground_activity
                    while True:
                        await asyncio.sleep(0.25)
                        if has_foreground_activity():
                            foreground_cancel["hit"] = True
                            logger.info("Task '%s' interrupted because Pantheon became active", task.name)
                            if current_task:
                                current_task.cancel()
                            return

                foreground_monitor = asyncio.create_task(_cancel_if_foreground_active())
            try:
                if task_type == "action":
                    node = await self._execute_action(task, run_id=run_id)
                    # `P8-24`. `skipped` and `deferred` are raised here rather
                    # than branched on, so the two handlers below stay the only
                    # code that writes a no-op row or pushes `next_run` — one
                    # vocabulary at the node boundary, one set of handlers
                    # inside the scheduler (`Law 14`).
                    signal = node.as_signal()
                    if signal is not None:
                        raise signal
                    result = node.text
                    run.status = "success" if node.ok else "error"
                    run.result = result
                    if node.failed:
                        run.error = result
                elif task_type == "research":
                    result = await self._execute_research_task(task, db, run_id=run_id)
                    run.status = "success"
                    run.result = result
                else:
                    # LLM task — use agent loop for tool access
                    result = await self._execute_llm_task(task, db, run_id=run_id)
                    run.status = "success"
                    run.result = result
                # Record which model actually ran (resolved inside the executor).
                if self.run_model(run_id):
                    run.model = self.run_model(run_id)
                self._attach_run_steps(run_id, run)
                if run.status == "success":
                    await self._deliver_task_result(task, result, db, model=self.run_model(run_id))
            except TaskDeferred as defer:
                count = self._task_defer_counts.get(task_id, 0) + 1
                self._task_defer_counts[task_id] = count
                delay_seconds = int(getattr(defer, "delay_seconds", 20 * 60) or (20 * 60))
                if count > 2:
                    delay_seconds = max(delay_seconds, 40 * 60)
                when = _utcnow() + timedelta(seconds=delay_seconds)
                logger.info(
                    "Task '%s' deferred for %ss after %s quiet-window hit(s): %s",
                    task.name, delay_seconds, count, defer,
                )
                run_obj = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if run_obj:
                    db.delete(run_obj)
                task.next_run = when
                db.commit()
                return
            except asyncio.CancelledError:
                msg = (
                    "Paused because Pantheon became active"
                    if foreground_cancel.get("hit")
                    else "Stopped by user"
                )
                logger.info("Task '%s' %s", task.name, msg)
                run_obj = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if run_obj:
                    run_obj.status = "aborted"
                    run_obj.error = msg
                    run_obj.result = run_obj.result or msg
                    run_obj.finished_at = _utcnow()
                    # An interrupted run is one of the two people most want the
                    # steps for; the other is the one that errored, below.
                    self._attach_run_steps(run_id, run_obj)
                task.last_run = _utcnow()
                if foreground_cancel.get("hit"):
                    task.next_run = _utcnow() + timedelta(minutes=15)
                elif (task.trigger_type or "schedule") == "schedule":
                    task.next_run = compute_next_run(
                        task.schedule, task.scheduled_time,
                        task.scheduled_day, task.scheduled_date,
                        after=_utcnow(),
                        cron_expression=task.cron_expression,
                        tz_name=_resolve_task_timezone(db, task),
                    )
                else:
                    task.next_run = None
                db.commit()
                # `B112`. Declared silent in `TASK_RUN_NOTIFY`, with the reason:
                # the restart sweep aborts every in-flight run on every boot and
                # a foreground takeover re-queues this one in 15 minutes. The
                # call is here anyway so the silence is the policy's answer and
                # not this branch forgetting the notify block, which is how it
                # read before.
                self._notify_run_outcome(task, "aborted", body=msg, task_id=task_id)
                return
            except TaskNoop as noop:
                # Action reported "nothing to do". Mark the run as `skipped`
                # with the reason in `result` so it surfaces in Activity as a
                # slim "skipped — <reason>" row instead of vanishing silently.
                # (Previous behavior was `db.delete(run)`, which made the user
                # think queued tasks had been dropped on the floor.)
                logger.info(f"Task '{task.name}' no-op: {noop}")
                run.status = "skipped"
                run.result = str(noop)
                run.finished_at = _utcnow()
                self._attach_run_steps(run_id, run)
                task.last_run = _utcnow()
                if (task.trigger_type or "schedule") == "schedule":
                    task.next_run = compute_next_run(
                        task.schedule, task.scheduled_time,
                        task.scheduled_day, task.scheduled_date,
                        after=_utcnow(),
                        cron_expression=task.cron_expression,
                        tz_name=_resolve_task_timezone(db, task),
                    )
                else:
                    task.next_run = None
                db.commit()
                # `B112`. A no-op that leaves the task on its schedule is a
                # housekeeping action saying "nothing to do" — it recurs on every
                # tick and toasting it would be the noise this row exists to
                # avoid. A no-op on a task that will not come round again is the
                # last thing that will happen on it, so it is told.
                _will_run_again = (
                    task.status == "active"
                    and ((task.trigger_type or "schedule") != "schedule"
                         or task.next_run is not None)
                )
                if not _will_run_again:
                    self._notify_run_outcome(task, "skipped", body=str(noop),
                                             task_id=task_id)
                return
            finally:
                if foreground_monitor and not foreground_monitor.done():
                    foreground_monitor.cancel()
                    try:
                        await foreground_monitor
                    except asyncio.CancelledError:
                        pass

            run.finished_at = _utcnow()

            # Update task
            task.last_run = _utcnow()
            task.run_count = (task.run_count or 0) + 1
            self._task_defer_counts.pop(task_id, None)

            # Compute next run only for schedule-triggered tasks
            if (task.trigger_type or "schedule") == "schedule":
                task.next_run = compute_next_run(
                    task.schedule, task.scheduled_time,
                    task.scheduled_day, task.scheduled_date,
                    after=_utcnow(),
                    cron_expression=task.cron_expression,
                    tz_name=_resolve_task_timezone(db, task),
                )
                if task.next_run is None and task.schedule == "once":
                    task.status = "completed"
            else:
                task.next_run = None

            db.commit()
            logger.info(f"Task '{task.name}' completed (run {run_id})")
            output = task.output_target or "session"
            # Per-task notification gate. Default True (notifications_enabled
            # defaults to True at column level), but skip when the user has
            # explicitly turned them off for this task — quiets chatty
            # housekeeping cron tasks without disabling them entirely.
            # `B112`. One reader of the policy, not two. This used to spell its
            # own gate — `task_type in {llm, research} and notifications_enabled`
            # — beside three other terminal branches that emitted nothing at all
            # and said nothing about why. Every branch goes through
            # `_notify_run_outcome` now, so `core.database.TASK_RUN_NOTIFY` is
            # the only place that decides which outcomes are worth a
            # notification, and the two quiet gates stay exactly what they were.
            notified = self._notify_run_outcome(
                task,
                run.status,
                body=run.result if output == "notification" else None,
                task_id=task_id,
                quiet_for_actions=True,
            )
            if not notified and run.status == "error":
                self.add_notification(
                    task.name,
                    "error",
                    task_id,
                    owner=task.owner,
                    body=run.error or run.result,
                )

            # Log result to the assistant chat so all task activity is visible.
            # Skip skipped/error rows — user shouldn't see "skipped: …" noise
            # for cron tasks that no-op'd, or duplicate error spam for tasks
            # that already fired an error notification above.
            if run.status == "success":
                self._log_to_assistant(db, task, run.result or "[success]")

            # `P8-28`. Take the edge whose condition this run's outcome met.
            self._advance_chain(db, task, run.status, run_id)

        except Exception as exec_exc:
            logger.exception(f"Task {task_id} execution error")
            # Fetch the task's owner so the error notification reaches
            # the same user the success notification would have.
            _owner = None
            try:
                _t = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
                _owner = _t.owner if _t else None
            except Exception:
                pass
            _should_notify_error = False
            try:
                _t_for_notify = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
                _should_notify_error = (
                    bool(_t_for_notify)
                    and (_t_for_notify.task_type or "llm") in {"llm", "research"}
                    and getattr(_t_for_notify, "notifications_enabled", True)
                )
            except Exception:
                _should_notify_error = False
            if _should_notify_error:
                self.add_notification(f"Task {task_id}", "error", task_id, owner=_owner)
            try:
                # Persist the actual exception message so the UI can show it
                err_text = f"{type(exec_exc).__name__}: {exec_exc}"
                run_obj = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if run_obj and run_obj.status in ("running", "success"):
                    run_obj.status = "error"
                    run_obj.error = err_text[:2000]
                    run_obj.finished_at = _utcnow()
                    self._attach_run_steps(run_id, run_obj)
                # Advance next_run even on failure so a broken task doesn't
                # busy-loop the scheduler every tick with a stale past date.
                task_obj = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
                if task_obj and (task_obj.trigger_type or "schedule") == "schedule":
                    task_obj.last_run = _utcnow()
                    try:
                        task_obj.next_run = compute_next_run(
                            task_obj.schedule, task_obj.scheduled_time,
                            task_obj.scheduled_day, task_obj.scheduled_date,
                            after=_utcnow(),
                            cron_expression=task_obj.cron_expression,
                            tz_name=_resolve_task_timezone(db, task_obj),
                        )
                        # `P15-08`. Advancing to the next slot is what this line
                        # did and all it did: a task failing against a
                        # rate-limiting provider retried at full cadence, for
                        # ever, and every retry is another request to the thing
                        # that is already refusing us. The schedule is kept —
                        # this only ever pushes the next run LATER — and the
                        # first success clears the ladder, because the count is
                        # read from the run history rather than carried.
                        if task_obj.next_run is not None:
                            failures = consecutive_failures(
                                db, task_id, before_run_id=run_id) + 1
                            delay = failure_backoff_seconds(failures)
                            backed_off = _utcnow() + timedelta(seconds=delay)
                            if backed_off > task_obj.next_run:
                                logger.warning(
                                    "Task %s has failed %d time(s) in a row; next run "
                                    "held back to %s (+%.0fs) instead of its schedule",
                                    task_id, failures, backed_off, delay)
                                task_obj.next_run = backed_off
                    except Exception as exc:
                        # `P3-17`. `last_run` was set on the line above, so
                        # swallowing this leaves `next_run` at a time that has
                        # already passed — the task either re-fires on every
                        # tick or never fires again, depending on which way the
                        # comparison falls, and the schedule the user set is
                        # not what runs. A malformed cron expression is the
                        # likely cause and it is worth a line in the log.
                        logger.warning(
                            "Could not compute the next run for task %s (%s); its schedule is "
                            "left at %s: %s",
                            getattr(task_obj, "id", "?"), getattr(task_obj, "schedule", "?"),
                            getattr(task_obj, "next_run", None), exc,
                        )
                try:
                    db.commit()
                    # `P8-28`. The same branch the ordinary path takes. A task
                    # that RAISED and a task that RETURNED a failure are the
                    # same failure to whoever built the workflow, and before
                    # this the first one silently skipped the branch.
                    if (task_obj is not None and run_obj is not None
                            and run_obj.status == "error"):
                        self._advance_chain(db, task_obj, "error", run_id)
                except Exception as commit_err:
                    # Commit failed — without a fallback the run row stays
                    # "running" forever AND next_run stays in the past, so the
                    # scheduler busy-loops dispatching the same task every tick
                    # until restart. Force the recovery in a fresh session.
                    logger.warning("Task %s error-path commit failed: %s — falling back", task_id, commit_err)
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    from datetime import timedelta as _td
                    _recover_db = SessionLocal()
                    try:
                        from core.database import TASK_RUN_ACTIVE_STATUSES
                        _r = _recover_db.query(TaskRun).filter(TaskRun.id == run_id).first()
                        if _r and _r.status in TASK_RUN_ACTIVE_STATUSES:
                            _r.status = "aborted"
                            _r.error = f"commit_failed: {type(commit_err).__name__}: {commit_err}"[:2000]
                            _r.finished_at = _utcnow()
                        _t = _recover_db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
                        if _t and (_t.trigger_type or "schedule") == "schedule":
                            # Push next_run forward 5min as a safe stall so the
                            # scheduler doesn't immediately re-dispatch.
                            _t.next_run = _utcnow() + _td(minutes=5)
                            _t.last_run = _utcnow()
                        _recover_db.commit()
                    except Exception as recover_err:
                        logger.error("Task %s recovery commit ALSO failed: %s", task_id, recover_err)
                    finally:
                        _recover_db.close()
            except Exception:
                logger.exception("Task %s error-path failed unexpectedly", task_id)
        finally:
            db.close()
            # `P8-27`. The run is over on every path out of this function —
            # success, no-op, defer, abort, error, and the early returns above
            # that never reached an executor. Dropping the slot here and nowhere
            # else is what keeps `_run_state` the size of what is in flight.
            self._clear_run_state(run_id)
            handle = self._task_handles.get(task_id)
            if handle is asyncio.current_task():
                self._task_handles.pop(task_id, None)
            if release_executing:
                async with self._executing_lock:
                    self._executing.discard(task_id)



    # Built-in housekeeping actions whose output is pure infra (no user-facing
    # content) — don't pollute the assistant chat session with their summaries.
    # Activity log + reminder email already carry everything the user needs.
    _SILENT_ACTIONS = frozenset({
        "check_email_urgency",
        "learn_sender_signatures",
        "summarize_emails",
        "draft_email_replies",
        "email_auto_translate",
        "extract_email_events",
        "classify_events",
        "tidy_sessions",
        "tidy_documents",
        "consolidate_memory",
        "tidy_research",
        "test_skills",
        "audit_skills",
    })

    def _action_needs_model(self, action: str | None) -> bool:
        """Does this built-in action call a model?

        `P8-22`. This was a frozenset spelled out here, to gate the model
        semaphore, and spelled out again in `static/js/tasks.js`, to draw the
        "uses model" badge — two lists of the same fact, either of which could
        be edited without the other. It is stated once now, as `model_backed`
        in `src.builtin_actions.BUILTIN_ACTION_META`, and
        `GET /api/tasks/meta/actions` carries the flag to the client so the
        badge and the semaphore cannot describe the same action differently
        (`Law 7`). Imported lazily, matching every other reach from this module
        into `builtin_actions`.
        """
        from src.builtin_actions import MODEL_BACKED_ACTIONS
        return (action or "") in MODEL_BACKED_ACTIONS

    def _task_needs_model_slot(self, task_id: str) -> bool:
        """Only LLM/research/model-backed actions should wait in the model
        queue. Pure housekeeping actions can run immediately."""
        from core.database import SessionLocal, ScheduledTask

        db = SessionLocal()
        try:
            task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            if not task:
                return True
            task_type = getattr(task, "task_type", "") or "llm"
            if task_type != "action":
                return True
            return self._action_needs_model(getattr(task, "action", ""))
        finally:
            db.close()

    def _log_to_assistant(self, db, task, result_text: str):
        """Log a task result to the assistant's chat session."""
        # Don't double-log check-ins (they already save directly)
        if "check-in" in (task.name or "").lower():
            return
        # Built-in housekeeping noise stays out of the chat.
        if (getattr(task, "action", "") or "") in self._SILENT_ACTIONS:
            return
        from src.assistant_log import log_to_assistant
        log_to_assistant(
            task.owner,
            result_text[:1000],
            category=(task.name or "Task"),
        )

    async def _execute_action(self, task, run_id: str | None = None):
        """Execute a built-in action (no LLM needed).

        `P8-24`. Returns a `NodeResult`, not `(text, success)`. The eighteen
        shipped actions still return the pair and are read through
        `coerce_node_result` — the adapter is here, at the one boundary, and
        not eighteen edits to working code.

        `TaskNoop` and `TaskDeferred` come back as `skipped` and `deferred`
        rather than propagating from here, so the four statuses are all things
        this function actually produces. `_execute_task_locked` raises them
        again through `as_signal()`, because the branches that know how to
        write a `skipped` row and how to push `next_run` are already written and
        a second copy of them is the `Law 14` mistake this row is warned about.
        """
        from src.builtin_actions import (
            BUILTIN_ACTIONS, NODE_STATUS_ERROR, NodeResult, coerce_node_result,
        )

        action_fn = BUILTIN_ACTIONS.get(task.action)
        if not action_fn:
            return NodeResult(NODE_STATUS_ERROR,
                              payload=f"Unknown action: {task.action}")

        from src.builtin_actions import TaskNoop, TaskDeferred
        try:
            # Pass task prompt as script/command for ssh_command/run_script actions.
            def _progress(message: str):
                # `P8-25`. Every action already reports its progress here and
                # each line overwrote the last one into `result`, so only the
                # final line survived and the rest existed nowhere. They are
                # the run's steps; they are kept now as well as shown.
                self._record_run_step(run_id, kind="progress", detail=message)
                self._set_run_progress(run_id, message)

            kwargs = {"owner": task.owner, "task_name": task.name, "progress_cb": _progress}
            if task.prompt:
                kwargs["prompt"] = task.prompt
            if task.action in ("run_script", "run_local", "ssh_command") and task.prompt:
                kwargs["script" if task.action in ("run_script", "run_local") else "command"] = task.prompt
            # cookbook_serve carries its JSON config in task.prompt — feed it
            # through as `command` so action_cookbook_serve can json.loads it.
            elif task.action == "cookbook_serve" and task.prompt:
                kwargs["command"] = task.prompt
            return coerce_node_result(await action_fn(**kwargs))
        except (TaskNoop, TaskDeferred) as signal:
            # `P8-24`. The two signals the engine has always had, spoken in the
            # same vocabulary as everything else a node can say — so all four
            # statuses are things this function returns rather than two of them
            # being a separate control-flow channel nobody can branch on.
            return NodeResult.from_signal(signal)
        except Exception as e:
            logger.error(f"Action '{task.action}' failed: {e}")
            return NodeResult(NODE_STATUS_ERROR, payload=str(e))

    # ── Check-in source discovery ──
    # Pattern-based: if an MCP server has a tool matching a pattern, it becomes
    # a check-in source. Add new patterns here to support new integrations —
    # no code changes needed elsewhere.
    CHECKIN_MCP_PATTERNS = [
        {"detect": "list_emails",   "section": "Email",    "tool": "list_emails",
         "args": {"mailbox": "INBOX", "limit": 10, "unread_only": True},
         "label_from_identity": True,
         "formatter": "_format_email_output"},
        {"detect": "search_emails", "section": "Email",    "tool": "search_emails",
         "args": {"query": "is:unread", "limit": 10},
         "label_from_identity": True,
         "formatter": "_format_email_output"},
        {"detect": "get_feed",      "section": "RSS",      "tool": "get_feed",
         "args": {},
         "label_from_identity": False},
        {"detect": "list_feeds",    "section": "RSS",      "tool": "list_feeds",
         "args": {},
         "label_from_identity": False},
        {"detect": "list_messages", "section": "Messages", "tool": "list_messages",
         "args": {"limit": 10},
         "label_from_identity": True},
    ]

    @staticmethod
    def _format_email_output(raw: str) -> str:
        """Clean up raw MCP email list output into readable format."""
        import re as _re
        lines = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Skip header lines like "📬 [INBOX] 856 emails..."
            if line.startswith(("\U0001f4ec", "📬", "No emails", "---", "Page ")):
                continue
            # Skip "more pages available" etc
            if "page" in line.lower() and "/" in line:
                continue
            # Parse: [1778] Re: Subject From: Name | Date
            m = _re.match(r'\[?\d+\]?\s*(?:↩️\s*|📎\s*|🔵\s*|⭐\s*)?(.+?)(?:\s*From:\s*(.+?))?(?:\s*\|\s*(\S+))?$', line)
            if m:
                subject = m.group(1).strip().rstrip('|').strip()
                sender = (m.group(2) or "").strip().rstrip('|').strip()
                if sender:
                    lines.append(f"- {sender} — {subject}")
                else:
                    lines.append(f"- {subject}")
            elif line.startswith("[") or line.startswith("-"):
                # Generic cleanup
                cleaned = _re.sub(r'^\[?\d+\]?\s*(?:↩️\s*|📎\s*)?', '', line.lstrip('- '))
                if cleaned.strip():
                    lines.append(f"- {cleaned.strip()}")
        if not lines:
            return "No unread emails"
        return "\n".join(lines[:10])

    async def _execute_checkin(self, task, crew, db, session_id: str,
                               endpoint_url: str, model: str,
                               run_id: str | None = None) -> str:
        """Gather raw data from all integrations, hand it to the LLM to write the check-in."""
        from src.tool_implementations import do_manage_notes
        from src.tool_utils import get_mcp_manager

        tz_name = _resolve_task_timezone(db, task)
        try:
            if tz_name:
                from zoneinfo import ZoneInfo
                from datetime import timezone, timedelta
                now = _utcnow().replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))
            else:
                from datetime import timedelta
                now = _utcnow()
            time_str = now.strftime("%A, %B %d %Y, %H:%M")
        except Exception:
            from datetime import timedelta
            now = _utcnow()
            time_str = now.strftime("%H:%M UTC")

        raw = {}

        # Calendar: today+tomorrow, this week, month ahead
        # Pull directly from DB so we can include event_type and importance.
        try:
            from core.database import SessionLocal as _SL, CalendarEvent as _CE
            _db = _SL()
            try:
                for label, start, end in _digest_windows(now):
                    # Strip timezone for naive DB comparison
                    _s = start.replace(tzinfo=None) if start.tzinfo else start
                    _e = end.replace(tzinfo=None) if end.tzinfo else end
                    evs = _checkin_calendar_events(_db, task.owner, _s, _e)
                    if not evs:
                        continue
                    # Group by importance for richer output
                    by_imp = {"critical": [], "high": [], "normal": [], "low": []}
                    for ev in evs:
                        imp = (ev.importance or "normal").lower()
                        by_imp.setdefault(imp, []).append(ev)
                    lines = []
                    for tier in ("critical", "high", "normal", "low"):
                        items = by_imp.get(tier, [])
                        if not items:
                            continue
                        marker = {"critical": "[!!]", "high": "[!]", "normal": "  ", "low": " ·"}[tier]
                        for ev in items:
                            t = ev.dtstart.strftime("%a %b %d %H:%M")
                            tag = f" ({ev.event_type})" if ev.event_type else ""
                            loc = f" @ {ev.location}" if ev.location else ""
                            lines.append(f"{marker} {t} — {ev.summary}{tag}{loc}")
                    if lines:
                        raw[f"calendar_{label}"] = "\n".join(lines)
            finally:
                _db.close()
        except Exception as e:
            raw["calendar"] = f"Error: {e}"

        # Notes/Tasks
        try:
            r = await do_manage_notes(json.dumps({"action": "list"}), owner=task.owner)
            raw["notes_tasks"] = r.get("results") or r.get("response") or "No notes"
        except Exception as e:
            raw["notes_tasks"] = f"Error: {e}"

        # Auto-discover API integrations (Miniflux RSS, etc.).
        try:
            import httpx
            from src.integrations import load_integrations
            for integ in load_integrations():
                if not integ.get("enabled"):
                    continue
                preset = integ.get("preset", "")
                base_url = integ.get("base_url", "").rstrip("/")
                api_key = integ.get("api_key", "")
                if not base_url:
                    continue

                # Build auth headers
                headers = {}
                if integ.get("auth_type") == "header" and api_key:
                    headers[integ.get("auth_header", "X-Auth-Token")] = api_key
                elif integ.get("auth_type") == "bearer" and api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                # Miniflux: fetch unread entries (cached 3 min across tasks)
                if preset == "miniflux":
                    async def _fetch_miniflux(_base=base_url, _headers=dict(headers)):
                        async with httpx.AsyncClient(timeout=10) as client:
                            resp = await client.get(
                                f"{_base}/v1/entries",
                                params={"status": "unread", "limit": 15, "order": "published_at", "direction": "desc"},
                                headers=_headers,
                            )
                            if resp.status_code != 200:
                                return None
                            entries = resp.json().get("entries", []) or []
                            if not entries:
                                return None
                            lines = []
                            for e in entries[:15]:
                                title = e.get("title", "?")
                                feed = (e.get("feed") or {}).get("title", "?")
                                url = e.get("url", "")
                                lines.append(f"- [{feed}] {title} — {url}")
                            return "\n".join(lines)
                    try:
                        val = await _cached(("miniflux_unread", base_url), 180, _fetch_miniflux)
                        if val:
                            raw["rss_miniflux_unread"] = val
                    except Exception as e:
                        logger.warning(f"Miniflux fetch failed: {e}")
        except Exception as e:
            logger.warning(f"Integrations discovery failed: {e}")

        # Auto-discover MCP sources
        mcp = get_mcp_manager()
        if mcp:
            discovered = set()
            for server_id, tools in mcp._tools.items():
                if mcp.is_builtin(server_id):
                    continue
                conn = mcp._connections.get(server_id, {})
                if conn.get("status") != "connected":
                    continue
                identity = conn.get("identity", "")
                tool_names = {t["name"] for t in tools}
                for pattern in self.CHECKIN_MCP_PATTERNS:
                    if pattern["detect"] not in tool_names:
                        continue
                    key = f"{pattern['section']}_{server_id}"
                    if key in discovered:
                        continue
                    discovered.add(key)
                    label = f"{pattern['section']} ({identity})" if identity else pattern["section"]
                    qualified = f"mcp__{server_id}__{pattern['tool']}"
                    args = dict(pattern.get("args", {}))
                    args["account"] = "default"
                    try:
                        # Cache 3 min: different scheduled tasks firing at the
                        # same minute share the same MCP snapshot.
                        async def _call_mcp(_q=qualified, _args=args):
                            return await mcp.call_tool(_q, _args)
                        cache_key = ("mcp_snapshot", qualified, json.dumps(args, sort_keys=True))
                        result = await _cached(cache_key, 180, _call_mcp)
                        if result.get("exit_code", 0) != 0:
                            continue
                        content = result.get("stdout") or result.get("output") or ""
                        if content.strip():
                            raw[label] = content[:3000]
                    except Exception:
                        pass

        # Build the data dump and hand it to the LLM
        data_dump = f"Current time: {time_str}\n\n"
        for key, val in raw.items():
            data_dump += f"--- {key} ---\n{val}\n\n"

        context = (
            data_dump +
            f"---\n\n{task.prompt}\n\n"
            "Write the check-in. YOU decide what matters, what to skip, how to format. "
            "Only show future events. Calendar events are pre-tagged with importance: "
            "[!!] critical, [!] high, plain = normal, ' ·' = low. "
            "GROUP your output by importance — lead with critical/high, then normal, "
            "skip low entirely unless explicitly relevant. Mention event type (work/health/travel/etc) "
            "where it adds context (e.g. 'leave 1h early for travel'). "
            "Flag anything coming up that needs prep (birthdays, deadlines, holidays). "
            "Use tools to take action if needed. Keep it concise — no raw data dumps."
        )

        return await self._run_agent_loop(
            endpoint_url, model, task, session_id,
            system_prompt=(crew.personality or "").strip() if crew else None,
            disabled_tools=None, relevant_tools=None,
            override_user_message=context,
            trigger_context_msg=_trigger_context_message(self.run_trigger(run_id)),
            run_id=run_id,
        )

    async def _execute_llm_task(self, task, db, run_id: str | None = None) -> str:
        """Execute an LLM task with full tool access via the agent loop.

        `P8-27`. `run_id` addresses this run's slot — the resolved model and the
        step log. It defaults to `None` so a caller that has not been updated
        still runs; what it loses is the row those two facts land on, not the
        run.
        """
        from core.database import Session as DbSession, ChatMessage, CrewMember

        # If this task is wired to a CrewMember (personal assistant, custom
        # crew), prefer the crew member's persona/model/endpoint as overrides.
        crew = None
        if getattr(task, "crew_member_id", None):
            try:
                crew = db.query(CrewMember).filter(CrewMember.id == task.crew_member_id).first()
            except Exception:
                crew = None

        # Determine endpoint + model
        endpoint_url = task.endpoint_url
        model = task.model
        if (not endpoint_url or not model) and crew:
            endpoint_url = endpoint_url or crew.endpoint_url
            model = model or crew.model
        if not endpoint_url or not model:
            endpoint_url, model = self._resolve_defaults(db, task.owner)
        if not endpoint_url or not model:
            raise RuntimeError("No model/endpoint configured")
        endpoint_url = _normalize_chat_endpoint(endpoint_url)
        # Record the resolved model so _execute_task_locked can persist it on
        # the run (tasks rarely pin a model, so this is the only record of
        # which model actually produced the output). `P8-27`: against this run,
        # not against the scheduler.
        self.set_run_model(run_id, model)

        # Ensure a session exists for output
        session_id = task.session_id
        if not session_id:
            session_id = str(uuid.uuid4())
            sess = DbSession(
                id=session_id,
                name=f"[Task] {task.name}",
                endpoint_url=endpoint_url,
                model=model,
                owner=task.owner,
                folder="Tasks",
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.add(sess)
            task.session_id = session_id
            db.commit()
            if self._session_manager:
                try:
                    self._session_manager.ensure_task_session(
                        session_id, f"[Task] {task.name}", endpoint_url, model,
                        owner=task.owner, task=task
                    )
                except Exception:
                    pass

        # For assistant check-ins: call each tool directly and post results
        # as separate messages. More reliable than hoping the model calls tools.
        is_checkin = crew and crew.is_default_assistant and "check-in" in (task.name or "").lower()
        if is_checkin:
            return await self._execute_checkin(task, crew, db, session_id, endpoint_url, model,
                                               run_id=run_id)

        # Build system prompt: crew member persona overrides the default.
        # Built-in character_id (Socrates, Razor, etc.) further biases the
        # voice — it prepends to whichever base prompt we landed on so the
        # task still knows it's executing a scheduled task but in that
        # character's tone.
        system_prompt = (
            (crew.personality or "").strip()
            if crew and crew.personality
            else "You are a helpful assistant executing a scheduled task. Use available tools to complete the task thoroughly."
        )
        char_id = (getattr(task, "character_id", None) or "").strip()
        if char_id:
            try:
                from src.reminder_personas import PERSONAS as _PERSONAS
                char_prompt = _PERSONAS.get(char_id.lower())
                if char_prompt:
                    system_prompt = f"{char_prompt}\n\n{system_prompt}"
            except Exception:
                pass
        # Provide current date/time as a user-role message so the system prompt
        # stays byte-identical across runs and doesn't bust the Anthropic prompt
        # cache on every scheduled tick (see issue #2927 and the identical fix on
        # the interactive-chat path in src/agent_loop.py).  The message is built
        # once here and shared by both execution paths below (agent loop and the
        # direct fallback) so time grounding is never lost on either path.
        tz_name = _resolve_task_timezone(db, task)
        try:
            from src.user_time import current_datetime_context_message_for_tz
            _dt_msg: dict | None = current_datetime_context_message_for_tz(tz_name)
        except Exception:
            _dt_msg = None

        # Compute the disabled-tools set: the crew's enabled_tools allowlist
        # (inverted) plus the operator's global disabled_tools setting. The
        # global list must be merged here — chat does the same merge before
        # entering the agent loop (routes/chat_routes.py) — otherwise an admin
        # or AUTH_ENABLED=false scheduled task would still see and call shell/
        # file tools after the operator disabled them globally, because the
        # prompt/schema/execution gates only enforce what is passed in.
        disabled_tools: set[str] = set()
        if crew and crew.enabled_tools:
            try:
                enabled = json.loads(crew.enabled_tools)
                if isinstance(enabled, list) and enabled:
                    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
                    all_tools = set(BUILTIN_TOOL_DESCRIPTIONS.keys())
                    disabled_tools |= all_tools - set(enabled)
            except Exception:
                pass
        try:
            from src.settings import get_setting
            _global_disabled = get_setting("disabled_tools", [])
            if isinstance(_global_disabled, list):
                disabled_tools.update(_global_disabled)
        except Exception as exc:
            # `P3-17`: fails open — a scheduled task would run with tools the
            # operator disabled globally.
            logger.warning("Could not read the global disabled-tool list: %s", exc)

        # RAG-select relevant tools for this prompt + always-available assistant tools.
        # Without this, all 40+ tools get sent and models hit their tool limit.
        relevant_tools = None
        try:
            from src.tool_index import get_tool_index, ASSISTANT_ALWAYS_AVAILABLE
            tool_idx = get_tool_index()
            if tool_idx:
                rag_tools = tool_idx.get_tools_for_query(task.prompt or "", k=8)
                relevant_tools = compose_task_relevant_tools(
                    rag_tools, ASSISTANT_ALWAYS_AVAILABLE, disabled_tools
                )
                logger.info(f"[assistant] RAG selected {len(rag_tools)} tools + {len(ASSISTANT_ALWAYS_AVAILABLE)} always-available + shell/file defaults = {len(relevant_tools)} total for '{task.name}'")
        except Exception as e:
            logger.warning(f"[assistant] RAG tool selection failed, using all: {e}")

        # `P8-23`. What fired this run, as a message the model can read and must
        # not obey. `None` when nothing triggered it, which is every scheduled
        # run — so those build exactly the message list they built before.
        _trigger_msg = _trigger_context_message(self.run_trigger(run_id))

        # Try using the agent loop for full tool access
        try:
            result = await self._run_agent_loop(
                endpoint_url, model, task, session_id,
                system_prompt=system_prompt, disabled_tools=disabled_tools or None,
                relevant_tools=relevant_tools,
                datetime_context_msg=_dt_msg,
                trigger_context_msg=_trigger_msg,
                run_id=run_id,
            )
        except Exception as e:
            logger.warning(f"Agent loop failed for task '{task.name}', falling back to simple call: {e}")
            from src.task_endpoint import task_llm_call_async
            messages: list = [{"role": "system", "content": system_prompt}]
            if _dt_msg:
                messages.append(_dt_msg)
            # `P8-23`. The fallback path builds its own message list, so a
            # trigger payload has to be added here too or a task that ran
            # because the agent loop was down would be the one run that could
            # not say what fired it.
            if _trigger_msg:
                messages.append(_trigger_msg)
            messages.append({"role": "user", "content": task.prompt})
            result = await task_llm_call_async(
                messages,
                fallback_url=endpoint_url,
                fallback_model=model,
                owner=task.owner,
                timeout=120,
            )

        # Strip the model's chain-of-thought before saving/delivering. Task
        # output is LLM-only, so prose=True (which also removes untagged
        # "The user wants me to…" reasoning) is safe here — without this the
        # thinking leaked into the saved result.
        try:
            from src.text_helpers import strip_think
            result = strip_think(result or "", prose=True, prompt_echo=True).strip() or result
        except Exception:
            pass

        return result

    async def _deliver_task_result(self, task, result: str, db, model: str = None):
        """Deliver a completed task result according to output_target.

        This is intentionally shared by LLM/research/action tasks so built-in
        actions cannot drift into hidden delivery paths that disagree with the
        task's visible output target.
        """
        from core.database import Session as DbSession, ChatMessage, CrewMember
        from core.models import ChatMessage as MemChatMessage

        output = task.output_target or "session"
        if (
            output == "session"
            and (getattr(task, "task_type", "") or "") == "action"
            and (getattr(task, "action", "") or "") in self._SILENT_ACTIONS
        ):
            return
        if output.startswith("mcp__"):
            await self._deliver_via_mcp(output, task, result)
            return

        if self._is_email_output_target(output):
            await self._deliver_via_email(output, task, result)
            return

        if output != "session":
            return

        endpoint_url = task.endpoint_url
        model_name = model or task.model
        crew = None
        if getattr(task, "crew_member_id", None):
            try:
                crew = db.query(CrewMember).filter(CrewMember.id == task.crew_member_id).first()
            except Exception:
                crew = None
        if (not endpoint_url or not model_name) and crew:
            endpoint_url = endpoint_url or crew.endpoint_url
            model_name = model_name or crew.model
        if not endpoint_url or not model_name:
            try:
                resolved_url, resolved_model = self._resolve_defaults(db, task.owner)
                endpoint_url = endpoint_url or resolved_url
                model_name = model_name or resolved_model
            except Exception:
                pass

        endpoint_url = _normalize_chat_endpoint(endpoint_url)

        session_id = task.session_id
        if not session_id:
            session_id = str(uuid.uuid4())
            sess = DbSession(
                id=session_id,
                name=f"[Task] {task.name}",
                endpoint_url=endpoint_url or "",
                model=model_name or "",
                owner=task.owner,
                folder="Tasks",
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.add(sess)
            task.session_id = session_id
            db.commit()
            if self._session_manager:
                try:
                    self._session_manager.ensure_task_session(
                        session_id, f"[Task] {task.name}", endpoint_url, model_name,
                        owner=task.owner, task=task
                    )
                except Exception:
                    pass

        meta = {}
        if model_name:
            meta["model"] = model_name
        if crew and crew.is_default_assistant:
            meta.update({"source": "cron", "task_id": task.id, "task_name": task.name})

        # Use SessionManager for persistence so in-memory cache stays in sync
        if self._session_manager and session_id:
            try:
                self._session_manager.add_message(
                    session_id,
                    MemChatMessage(
                        "user",
                        task.prompt or f"[Task] {task.name}",
                        metadata=dict(meta),
                    ),
                )
                self._session_manager.add_message(
                    session_id,
                    MemChatMessage(
                        "assistant",
                        result or "",
                        metadata=dict(meta),
                    ),
                )
            except Exception:
                logger.exception("Failed to deliver task %s through SessionManager", task.id)
        else:
            # Fallback: raw DB write (no session manager available)
            msg_meta = json.dumps(meta)
            user_msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="user",
                content=task.prompt or f"[Task] {task.name}",
                timestamp=_utcnow(),
                meta_data=msg_meta,
            )
            assistant_msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=result or "",
                timestamp=_utcnow(),
                meta_data=msg_meta,
            )
            db.add(user_msg)
            db.add(assistant_msg)
            db.commit()

    @staticmethod
    def _is_email_output_target(output: str) -> bool:
        target = (output or "").strip()
        if target in {"email", "email:self"}:
            return True
        if target.startswith("email:"):
            return True
        return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", target))

    async def _deliver_via_email(self, output: str, task, result: str):
        """Send task output through the app's configured SMTP account.

        Supported output_target values:
        - email / email:self: send to the account's From address
        - email:name@example.com or raw name@example.com: send there
        """
        from email.message import EmailMessage

        target = (output or "").strip()
        explicit = ""
        account_id = ""
        if target.startswith("email:"):
            explicit = target.split(":", 1)[1].strip()
            if "|account=" in explicit:
                explicit, account_id = explicit.split("|account=", 1)
                explicit = explicit.strip()
                account_id = account_id.strip()
            if explicit == "self":
                explicit = ""
        elif "@" in target:
            explicit = target

        try:
            from routes.email_routes import _resolve_send_config
            from routes.email_helpers import _send_smtp_message

            cfg = _resolve_send_config(account_id=account_id or None, owner=task.owner or "")
            to_addr = explicit or cfg.get("from_address") or cfg.get("smtp_user") or ""
            if not to_addr:
                raise RuntimeError("No email recipient resolved for task output")

            from_addr = cfg.get("from_address") or cfg.get("smtp_user") or to_addr
            msg = EmailMessage()
            msg["From"] = from_addr
            msg["To"] = to_addr
            msg["Subject"] = f"[Task] {task.name}"
            msg["X-Pantheon-Origin"] = "pantheon-ui"
            msg["X-Pantheon-Kind"] = "task"
            msg["X-Pantheon-Ref"] = str(task.id)
            msg.set_content(result or "")
            _send_smtp_message(cfg, from_addr, [to_addr], msg.as_string(), timeout=30)
            logger.info("Task %s emailed result (recipient_set=%s, %sb)", task.id, bool(to_addr), len(result or ""))
        except Exception as e:
            logger.error("Task %s email delivery failed: %s", task.id, e, exc_info=True)
            raise

    async def _run_agent_loop(self, endpoint_url: str, model: str, task, session_id: str,
                              system_prompt: str | None = None,
                              disabled_tools: set | None = None,
                              relevant_tools: set | None = None,
                              override_user_message: str | None = None,
                              datetime_context_msg: dict | None = None,
                              trigger_context_msg: dict | None = None,
                              run_id: str | None = None) -> str:
        """Run the full agent loop with tool access, collecting the final text."""
        from src.agent_loop import stream_agent_loop

        system_content = system_prompt or "You are a helpful assistant executing a scheduled task. Use available tools to complete the task thoroughly."
        user_content = override_user_message or task.prompt
        # Build the message list. The datetime context message (user-role) is
        # inserted immediately before the task prompt so the system prefix stays
        # byte-identical and cacheable across runs (see issue #2927).
        messages: list = [{"role": "system", "content": system_content}]
        if datetime_context_msg:
            messages.append(datetime_context_msg)
        # `P8-23`. The trigger payload goes after the time context and before
        # the prompt, in the same slot and for the same reason: the system
        # prefix stays byte-identical and cacheable, and the model reads what
        # fired the task immediately before being told what to do about it.
        if trigger_context_msg:
            messages.append(trigger_context_msg)
        messages.append({"role": "user", "content": user_content})

        # Resolve headers from the endpoint's API key
        headers = {}
        try:
            from core.database import SessionLocal, ModelEndpoint
            from src.endpoint_resolver import normalize_base, build_headers
            from src.auth_helpers import owner_filter
            db2 = SessionLocal()
            try:
                ep_q = db2.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
                ep_q = owner_filter(ep_q, ModelEndpoint, task.owner or None)
                eps = ep_q.all()
                for ep in eps:
                    if normalize_base(ep.base_url) in endpoint_url or endpoint_url in normalize_base(ep.base_url):
                        headers = build_headers(ep.api_key, normalize_base(ep.base_url))
                        break
            finally:
                db2.close()
        except Exception:
            pass
        full_text = ""
        tool_results = []
        approval_pause = None

        # Honor per-task max_steps (defense against runaway agent loops).
        # Falls back to 20 if not set — the historical default.
        _task_max_rounds = task.max_steps if task.max_steps and task.max_steps > 0 else 20
        # Tasks are background workloads: use the shared task fallback chain
        # behind the primary endpoint so a downed primary won't silently yield
        # `(no output)`.
        try:
            from src.interactive_gate import wait_for_interactive_quiet
            await wait_for_interactive_quiet(f"agent task {task.name}")
            from src.task_endpoint import resolve_task_candidates
            _task_fallbacks = resolve_task_candidates(
                fallback_url=endpoint_url,
                fallback_model=model,
                fallback_headers=headers,
                owner=task.owner or None,
            )[1:]
        except Exception:
            _task_fallbacks = []
        async for event_str in stream_agent_loop(
            endpoint_url=endpoint_url,
            model=model,
            messages=messages,
            max_rounds=_task_max_rounds,
            session_id=session_id,
            owner=task.owner,
            headers=headers,
            disabled_tools=disabled_tools,
            relevant_tools=relevant_tools,
            fallbacks=_task_fallbacks,
            workload="background",
        ):
            if event_str.startswith("data: ") and not event_str.startswith("data: [DONE]"):
                try:
                    data = json.loads(event_str[6:])
                    # Capture text from all event types, not just delta
                    if "delta" in data:
                        if data.get("thinking"):
                            continue
                        full_text += data["delta"]
                    elif data.get("type") == "tool_start":
                        # `P8-25`. The run's step log. These events already
                        # carried everything an Activity row needs to say what
                        # a task did, and nothing read them.
                        self._record_run_step(
                            run_id,
                            kind="tool",
                            tool=data.get("tool") or "?",
                            round=data.get("round"),
                            detail=data.get("command") or "",
                            status="running",
                        )
                    elif data.get("type") == "tool_blocked":
                        # Refused by policy — it never ran, and that is the most
                        # useful line in the log when a task did less than asked.
                        self._record_run_step(
                            run_id,
                            kind="tool",
                            tool=data.get("tool") or "?",
                            round=data.get("round"),
                            detail=data.get("command") or "",
                            status="blocked",
                            output=data.get("reason") or "",
                        )
                    elif data.get("type") == "tool_output":
                        # Tool results — capture summary so we have SOMETHING even
                        # if the model never produces a final text response
                        tool_summary = data.get("stdout") or data.get("output") or data.get("result") or ""
                        # `B600`. This read `"error" if data.get("exit_code")
                        # else "ok"`, and only the shell and python branches ever
                        # set `exit_code` — so ~70 tools reported `ok` whatever
                        # happened, including a `web_fetch` that 404'd. The event
                        # states its own outcome now (`agent_loop.tool_outcome`);
                        # the fallback keeps an older event readable rather than
                        # calling it an error for lacking a field it predates.
                        _status = data.get("status")
                        if _status not in ("ok", "error"):
                            _status = "error" if data.get("exit_code") else "ok"
                        self._close_run_step(
                            run_id,
                            tool=data.get("tool") or "?",
                            round_=data.get("round"),
                            status=_status,
                            output=tool_summary if isinstance(tool_summary, str) else "",
                        )
                        if isinstance(tool_summary, str) and tool_summary.strip():
                            tool_results.append(f"[{data.get('tool', '?')}] {tool_summary[:500]}")
                        approval = data.get("ask_user")
                        if (
                            isinstance(approval, dict)
                            and approval.get("kind") == "tool_approval"
                        ):
                            approval_pause = {
                                "tool": data.get("tool") or "tool",
                                "approval_id": approval.get("approval_id"),
                            }
                            # Scheduled tasks have no interactive surface that
                            # can safely resume a one-use grant. Retire the
                            # record immediately instead of leaving it pending
                            # and report an explicit manual-action boundary.
                            try:
                                from src.tool_approvals import tool_approval_store
                                tool_approval_store.consume(
                                    approval_pause["approval_id"],
                                    decision="deny",
                                    owner=task.owner,
                                    session_id=session_id,
                                )
                            except Exception:
                                logger.debug(
                                    "Could not retire scheduled-task approval",
                                    exc_info=True,
                                )
                            break
                except (json.JSONDecodeError, KeyError):
                    pass

        if approval_pause is not None:
            return (
                "Scheduled task paused safely: "
                f"{approval_pause['tool']} requested an exact action after "
                "untrusted context. That action was not executed. Run this task "
                "interactively to inspect and approve the action."
            )

        # Grace summarization — if the model exhausted rounds on tool calls
        # without producing a final text response, do one last LLM call
        # asking it to summarize what it did. Guarantees output.
        if not full_text.strip():
            try:
                from src.task_endpoint import task_llm_call_async
                grace_context = "You ran out of steps. "
                if tool_results:
                    grace_context += "Here's what your tools returned:\n" + "\n".join(tool_results[-5:])
                else:
                    grace_context += "No tool results were captured."
                grace_context += "\n\nSummarize what you accomplished and what's still pending. Be concise."
                full_text = await task_llm_call_async(
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": grace_context},
                    ],
                    fallback_url=endpoint_url,
                    fallback_model=model,
                    fallback_headers=headers,
                    owner=task.owner or None,
                    timeout=30,
                )
                full_text = (full_text or "").strip()
            except Exception as e:
                logger.warning(f"Grace summarization failed: {e}")
                if tool_results:
                    full_text = "\n".join(tool_results[-5:])

        return full_text or "(no output)"

    async def _execute_research_task(self, task, db, run_id: str | None = None) -> str:
        """Execute a deep research task using DeepResearcher."""
        from core.database import Session as DbSession, ChatMessage
        from src.deep_research import DeepResearcher
        from src.research_handler import RESEARCH_DATA_DIR, ResearchHandler
        from src.research_utils import strip_thinking
        from src.settings import get_setting

        # Resolve endpoint/model: research settings > task settings > session defaults
        endpoint_url = task.endpoint_url
        model = task.model
        headers = {}
        headers_from_resolver = False

        if not endpoint_url or not model:
            try:
                from src.endpoint_resolver import resolve_endpoint
                ep_url, ep_model, ep_headers = resolve_endpoint(
                    "research",
                    endpoint_url or None,
                    model or None,
                    None,
                    owner=task.owner or None,
                )
                endpoint_url = ep_url or endpoint_url
                model = ep_model or model
                if ep_headers is not None:
                    headers = ep_headers
                    headers_from_resolver = True
            except Exception:
                pass

        if not endpoint_url or not model:
            endpoint_url, model = self._resolve_defaults(db, task.owner)
        if not endpoint_url or not model:
            raise RuntimeError("No model/endpoint configured for research")
        endpoint_url = _normalize_chat_endpoint(endpoint_url)
        # Record the resolved model for the run record (see _execute_task_locked).
        self.set_run_model(run_id, model)

        # Resolve headers
        try:
            from core.database import ModelEndpoint
            from src.endpoint_resolver import normalize_base, build_headers
            from src.auth_helpers import owner_filter
            db2 = db
            if not headers_from_resolver:
                ep_q = db2.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
                ep_q = owner_filter(ep_q, ModelEndpoint, task.owner or None)
                eps = ep_q.all()
                for ep in eps:
                    if normalize_base(ep.base_url) in endpoint_url or endpoint_url in normalize_base(ep.base_url):
                        headers = build_headers(ep.api_key, normalize_base(ep.base_url))
                        break
        except Exception:
            pass

        max_tokens = int(get_setting("research_max_tokens", 8192))
        extraction_timeout = int(get_setting("research_extraction_timeout_seconds", 90) or 90)
        extraction_concurrency = int(get_setting("research_extraction_concurrency", 3) or 3)

        researcher = DeepResearcher(
            llm_endpoint=endpoint_url,
            llm_model=model,
            llm_headers=headers,
            max_rounds=8,
            max_time=600,  # 10 min for scheduled research
            max_report_tokens=max_tokens,
            extraction_timeout=extraction_timeout,
            extraction_concurrency=extraction_concurrency,
        )

        started_ts = time.time()
        report = await researcher.research(task.prompt)
        completed_ts = time.time()
        try:
            stats = researcher.get_stats() or {}
        except Exception:
            stats = {}

        # Ensure a session exists for output
        session_id = task.session_id
        if not session_id:
            session_id = str(uuid.uuid4())
            sess = DbSession(
                id=session_id,
                name=f"[Research] {task.name}",
                endpoint_url=endpoint_url,
                model=model,
                owner=task.owner,
                folder="Tasks",
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.add(sess)
            task.session_id = session_id
            db.commit()
            if self._session_manager:
                try:
                    self._session_manager.sessions[session_id] = self._session_manager._db_to_session(sess)
                except Exception:
                    pass

        # Persist scheduled research in the same on-disk shape used by the
        # Research panel. Without this, task research had Markdown output but
        # no Library entry and no visual report route to open.
        try:
            RESEARCH_DATA_DIR.mkdir(parents=True, exist_ok=True)
            findings = getattr(researcher, "findings", []) or []
            payload = {
                "query": task.prompt or task.name or "Scheduled research",
                "status": "done",
                "result": report,
                "raw_report": strip_thinking(report or ""),
                "sources": ResearchHandler._extract_sources(findings),
                "raw_findings": ResearchHandler._extract_raw_findings(findings),
                "stats": stats,
                "category": "scheduled",
                "started_at": started_ts,
                "completed_at": completed_ts,
                "owner": task.owner or "",
                "task_id": task.id,
                "task_name": task.name,
            }
            (RESEARCH_DATA_DIR / f"{session_id}.json").write_text(json.dumps(payload), encoding="utf-8")
            try:
                from src.event_bus import fire_event
                fire_event("research_completed", task.owner or None,
                           {"session_id": session_id,
                            "topic": payload.get("query")})
            except Exception:
                logger.debug("research_completed event dispatch failed", exc_info=True)
        except Exception as e:
            logger.warning("Failed to persist task research report %s: %s", session_id, e)

        return report

    async def _run_chained(self, task_id: str):
        """Run a chained task. Acquires _executing membership the same way
        run_task_now does so an overlapping scheduler tick can't double-dispatch
        the same task while the chain run is in flight."""
        async with self._executing_lock:
            if task_id in self._executing:
                return  # already in flight (manual trigger, scheduler tick, or another chain)
            self._executing.add(task_id)
        await self._execute_task(task_id)

    def _chain_refusal(self, db, start_id: str, max_depth: int = CHAIN_MAX_DEPTH,
                       owner: str | None = None) -> str | None:
        """Why this chain may not run, or `None` if it may.

        `P8-26`. This function used to answer one boolean for three different
        situations, and the row is about the second of them: a chain longer
        than ten steps returned `True` from something called
        `_has_chain_cycle`, so the log said *"cycle detected"* about a workflow
        that has no cycle in it and is simply eleven steps long. **The depth cap
        is a real limit of this engine and it had no name, no message and no
        way for anyone to find out it existed** — the only symptom was a chain
        that stopped at step ten and a log line that named the wrong cause.

        Nothing is permitted that was refused before (`Law 1` runs both ways
        here: the cap stays, and the cycle check stays). What changes is that
        the caller can say which one happened, and `build_task_graph` can put
        the same answer on the wire.
        """
        from core.database import ScheduledTask
        visited = set()
        current = start_id
        for _ in range(max_depth):
            if current in visited:
                return CHAIN_CYCLE
            visited.add(current)
            task = db.query(ScheduledTask).filter(ScheduledTask.id == current).first()
            if owner is not None and task and task.owner != owner:
                return CHAIN_CROSS_OWNER
            if not task or not task.then_task_id:
                return None
            current = task.then_task_id
        return CHAIN_TOO_DEEP

    def _has_chain_cycle(self, db, start_id: str, max_depth: int = CHAIN_MAX_DEPTH,
                         owner: str | None = None) -> bool:
        """Kept, with its old name and its old answer.

        Three callers and two tests ask this question as a boolean and the
        answer they get is unchanged. `_chain_refusal` is the same walk with
        the reason kept instead of thrown away.
        """
        return self._chain_refusal(db, start_id, max_depth, owner) is not None

    def _resolve_defaults(self, db, owner):
        """Find the first available endpoint + model from an existing session."""
        from core.database import Session as DbSession
        try:
            recent = db.query(DbSession).filter(
                DbSession.endpoint_url.isnot(None),
                DbSession.model.isnot(None),
                *([DbSession.owner == owner] if owner else []),
            ).order_by(DbSession.created_at.desc()).first()
            if recent:
                return recent.endpoint_url, recent.model
        except Exception:
            pass
        return None, None

    async def _deliver_via_mcp(self, tool_name: str, task, result: str):
        """Send the task result via an MCP tool (e.g. Gmail send).

        Resolves a recipient (so email-style tools have a 'to') by trying the
        configured From address first (the `daily_brief` pattern — email
        yourself) then falling back to the task owner. Common recipient field
        names (to / recipient / email / address) are all populated so we don't
        have to special-case each tool's schema; the MCP tool ignores keys it
        doesn't recognise.
        """
        from src.tool_utils import get_mcp_manager
        mcp = get_mcp_manager()
        if not mcp:
            logger.warning(f"Task {task.id}: MCP manager not available for delivery")
            return

        # Resolve recipient — prefer the configured email From (the established
        # "email yourself" pattern from daily_brief), fall back to task.owner.
        # `_get_email_config()` is the single source of truth that handles both
        # the legacy `email_from` setting and the per-account DB rows.
        recipient = None
        try:
            from routes.email_helpers import _get_email_config
            cfg = _get_email_config() or {}
            recipient = cfg.get("from_address") or None
        except Exception as _e:
            logger.debug(f"_deliver_via_mcp: email config lookup failed: {_e}")
        if not recipient and task.owner and "@" in str(task.owner):
            recipient = task.owner

        args = {
            "subject": f"[Task] {task.name}",
            "body": result,
            "headers": {
                "X-Pantheon-Origin": "pantheon-ui",
                "X-Pantheon-Kind": "task",
                "X-Pantheon-Ref": str(task.id),
            },
        }
        if recipient:
            # Cover the common field names so we work across MCP servers (Gmail,
            # generic SMTP, Slack DMs, etc.) without having to hard-code each.
            args["to"] = recipient
            args["recipient"] = recipient
            args["email"] = recipient
            args["address"] = recipient
        else:
            logger.warning(
                f"Task {task.id}: no recipient resolved for MCP delivery via {tool_name} — "
                "set an email From address in Settings or give the task an owner email."
            )
        try:
            mcp_result = await mcp.call_tool(tool_name, args)
            stderr = mcp_result.get("stderr", "")
            stdout = mcp_result.get("stdout", "")
            body_len = len(result or "")
            exit_code = mcp_result.get("exit_code", 0)
            if exit_code != 0:
                logger.warning(
                    f"Task {task.id} MCP delivery FAILED via {tool_name}: "
                    f"exit={exit_code} stderr={stderr[:400]!r} stdout={stdout[:400]!r}"
                )
            else:
                # Include the MCP tool's own stdout (e.g. email_server returns
                # "Sent email to ... with subject ...") + the body size so a
                # silent SMTP failure is easier to spot in the logs.
                logger.info(
                    f"Task {task.id} delivered via MCP tool {tool_name} "
                    f"(recipient_set={bool(recipient)}, body={body_len}b, reply={stdout[:200]!r})"
                )
        except Exception as e:
            logger.error(f"Task {task.id} MCP delivery failed: {e}")

    async def run_task_now(self, task_id: str, *, force: bool = False,
                           trigger: dict | None = None):
        """Manually trigger a task execution.

        `P8-23`. `trigger` is what fired it — the event bus's envelope or the
        webhook's. `None` is a run nobody can name a cause for, which is every
        scheduled run and every button press, and those behave exactly as
        before.
        """
        if force:
            asyncio.create_task(self._execute_task(
                task_id, bypass_model_slot=True, release_executing=False,
                trigger=trigger))
            return True
        async with self._executing_lock:
            if task_id in self._executing:
                return False
            self._executing.add(task_id)
        asyncio.create_task(self._execute_task(task_id, trigger=trigger))
        return True

    async def stop_task(self, task_id: str) -> bool:
        """Request cancellation of a running/queued task and mark its run aborted."""
        handle = self._task_handles.get(task_id)
        stopped = False
        if handle and not handle.done():
            handle.cancel()
            stopped = True
        async with self._executing_lock:
            if task_id in self._executing:
                self._executing.discard(task_id)
                stopped = True

        stopped = self._mark_run_aborted(task_id) or stopped
        return stopped

    async def stop_background_tasks_for_foreground(self, *, reason: str = "Pantheon became active") -> int:
        """Cancel all in-process scheduler tasks because the user is active.

        This is intentionally blunt for scheduled/background work: when the
        user opens or uses Pantheon, foreground interaction wins immediately.
        Manual force-runs can be restarted by the user; automatic jobs will be
        deferred by their cancellation path instead of stealing the app.
        """
        async with self._executing_lock:
            task_ids = list(self._executing)
        stopped = 0
        for task_id in task_ids:
            handle = self._task_handles.get(task_id)
            if handle and not handle.done():
                handle.cancel()
                stopped += 1
            if self._mark_run_aborted(task_id):
                stopped += 1
        if stopped:
            logger.info("Stopped %d background scheduler task(s): %s", stopped, reason)
        return stopped

    async def ensure_defaults(self, owner: str):
        """Create default housekeeping tasks for this owner (idempotent per action)."""
        from core.database import SessionLocal, ScheduledTask
        try:
            from routes.prefs_routes import _load_for_user
            _prefs = _load_for_user(owner) or {}
        except Exception:
            _prefs = {}
        tasks_enabled = bool(_prefs.get("tasks_enabled"))
        tasks_opened = bool(_prefs.get("tasks_opened"))

        db = SessionLocal()
        try:
            # Normalize old built-ins that were created before `task_type` /
            # `action` were reliable. Match by current or legacy name so stale
            # rows cannot keep running as scheduled LLM tasks forever.
            name_to_action = {}
            for action, defs in HOUSEKEEPING_DEFAULTS.items():
                name_to_action[defs["name"]] = action
                for legacy in defs.get("legacy_names") or []:
                    name_to_action[legacy] = action
            possible_names = list(name_to_action.keys())
            legacy_named = db.query(ScheduledTask).filter(
                ScheduledTask.owner == owner,
                ScheduledTask.name.in_(possible_names),
            ).all()
            for task in legacy_named:
                action = name_to_action.get(task.name)
                if not action:
                    continue
                task.task_type = "action"
                task.action = action

            from core.database import TaskRun
            retired_ids = [
                row[0] for row in db.query(ScheduledTask.id).filter(
                    ScheduledTask.owner == owner,
                    ScheduledTask.task_type == "action",
                    ScheduledTask.action.in_(list(RETIRED_HOUSEKEEPING_ACTIONS)),
                ).all()
            ]
            if retired_ids:
                db.query(TaskRun).filter(TaskRun.task_id.in_(retired_ids)).delete(synchronize_session=False)
            retired_count = db.query(ScheduledTask).filter(
                ScheduledTask.owner == owner,
                ScheduledTask.task_type == "action",
                ScheduledTask.action.in_(list(RETIRED_HOUSEKEEPING_ACTIONS)),
            ).delete(synchronize_session=False)
            # Sweep orphan TaskRun rows (parent task deleted previously) so
            # retired actions stop showing in Activity. Only runs when at least
            # one live task exists — avoids wiping run history on a fresh DB.
            try:
                live_ids = {row[0] for row in db.query(ScheduledTask.id).all()}
                if live_ids:
                    db.query(TaskRun).filter(~TaskRun.task_id.in_(list(live_ids))).delete(synchronize_session=False)
            except Exception:
                # `P3-17`: housekeeping. These rows belong to tasks that no
                # longer exist; leaving them costs a little disk and nothing
                # else, and the next sweep tries again.
                pass
            existing_actions = {
                row[0] for row in db.query(ScheduledTask.action).filter(
                    ScheduledTask.owner == owner,
                    ScheduledTask.task_type == "action",
                ).all() if row[0]
            }
            renamed = []
            builtin_tasks = db.query(ScheduledTask).filter(
                ScheduledTask.owner == owner,
                ScheduledTask.task_type == "action",
                ScheduledTask.action.in_(list(HOUSEKEEPING_DEFAULTS.keys())),
            ).all()
            by_action = {}
            for task in builtin_tasks:
                by_action.setdefault(task.action, []).append(task)
            removed_dupes = []
            kept_ids = set()
            for action, tasks in by_action.items():
                defs = HOUSEKEEPING_DEFAULTS.get(action)
                if not defs:
                    continue
                desired_trigger = defs.get("trigger_type", "schedule")

                def _score(candidate):
                    matches_default = (
                        (candidate.trigger_type or "schedule") == desired_trigger
                        and (candidate.trigger_event or None) == defs.get("trigger_event")
                        and (candidate.trigger_count or 1) == (defs.get("trigger_count") or 1)
                        and (candidate.schedule or None) == defs.get("schedule")
                        and (candidate.scheduled_time or None) == defs.get("scheduled_time")
                        and (candidate.cron_expression or None) == defs.get("cron_expression")
                    )
                    created = candidate.created_at or datetime.min
                    created_key = (created.toordinal(), created.hour, created.minute, created.second, created.microsecond)
                    return (1 if matches_default else 0, 1 if candidate.status == "active" else 0, created_key)

                keep = sorted(tasks, key=_score, reverse=True)[0]
                kept_ids.add(keep.id)
                for dupe in tasks:
                    if dupe.id == keep.id:
                        continue
                    db.delete(dupe)
                    removed_dupes.append(action)

            for task in [t for t in builtin_tasks if t.id in kept_ids]:
                defs = HOUSEKEEPING_DEFAULTS.get(task.action)
                if not defs:
                    continue
                legacy_names = set(defs.get("legacy_names") or [])
                if (task.name or "") in legacy_names:
                    task.name = defs["name"]
                    renamed.append(task.action)
                normalized = False
                desired_trigger = defs.get("trigger_type", "schedule")
                if task.action == "check_email_urgency":
                    old_crons = set(defs.get("old_cron_expressions") or [])
                    if task.schedule == "cron" and (task.cron_expression or "") in old_crons:
                        task.cron_expression = defs["cron_expression"]
                        task.next_run = compute_next_run(
                            defs["schedule"], defs["scheduled_time"], None, None,
                            after=_utcnow(), cron_expression=defs["cron_expression"],
                            tz_name=_resolve_task_timezone(db, task),
                        )
                        normalized = True
                if desired_trigger == "event" and (
                    (task.trigger_type or "schedule") != "event"
                    or task.trigger_event != defs.get("trigger_event")
                    or (task.trigger_count or 1) != (defs.get("trigger_count") or 1)
                    or task.schedule is not None
                    or task.scheduled_time is not None
                    or task.scheduled_date is not None
                    or task.cron_expression is not None
                ):
                    task.trigger_type = "event"
                    task.trigger_event = defs.get("trigger_event")
                    task.trigger_count = defs.get("trigger_count") or 1
                    task.trigger_counter = 0
                    task.schedule = defs.get("schedule")
                    task.scheduled_time = defs.get("scheduled_time")
                    task.scheduled_day = None
                    task.scheduled_date = None
                    task.cron_expression = defs.get("cron_expression")
                    normalized = True
                if normalized:
                    renamed.append(task.action)
                ships_paused = bool(defs.get("ship_paused"))
                if not tasks_enabled and not tasks_opened:
                    if ships_paused and task.status == "active":
                        task.status = "paused"
                    elif not ships_paused and task.status == "paused":
                        task.status = "active"
                        if (task.trigger_type or "schedule") == "schedule":
                            task.next_run = compute_next_run(
                                task.schedule, task.scheduled_time,
                                task.scheduled_day, task.scheduled_date,
                                after=_utcnow(), cron_expression=task.cron_expression,
                                tz_name=_resolve_task_timezone(db, task),
                            )
                # Built-in housekeeping/action jobs should not create browser
                # task notifications; user AI/research tasks still can.
                task.notifications_enabled = False
                if (task.output_target or "session") == "session":
                    task.output_target = defs.get("output_target", "none")
            seeded = []
            for action, defs in HOUSEKEEPING_DEFAULTS.items():
                if action in existing_actions:
                    continue
                trigger_type = defs.get("trigger_type", "schedule")
                next_run = None
                if trigger_type == "schedule":
                    next_run = compute_next_run(
                        defs["schedule"], defs["scheduled_time"], None, None,
                        after=_utcnow(), cron_expression=defs["cron_expression"],
                    )
                ships_paused = bool(defs.get("ship_paused"))
                task = ScheduledTask(
                    id=str(uuid.uuid4())[:8],
                    owner=owner,
                    name=defs["name"],
                    task_type="action",
                    action=action,
                    trigger_type=trigger_type,
                    trigger_event=defs.get("trigger_event"),
                    trigger_count=defs.get("trigger_count"),
                    trigger_counter=0,
                    schedule=defs["schedule"],
                    scheduled_time=defs["scheduled_time"],
                    cron_expression=defs["cron_expression"],
                    next_run=next_run,
                    # Most built-ins are active by default. The invasive
                    # AI/email/calendar tasks opt into a paused starting state
                    # via ship_paused so users can enable them deliberately.
                    status="paused" if ships_paused else "active",
                    output_target=defs.get("output_target", "none"),
                    notifications_enabled=False,
                )
                db.add(task)
                seeded.append(action)
            if seeded or renamed or removed_dupes or retired_count:
                logger.info(
                    "Housekeeping defaults for %s: seeded=%s renamed=%s deduped=%s retired=%s",
                    owner, seeded, sorted(set(renamed)), sorted(set(removed_dupes)), retired_count,
                )
            # Always commit — the orphan-run sweep above may have produced
            # pending deletes even when no defaults changed.
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to create default tasks: {e}")
        finally:
            db.close()
        # Always ensure the personal assistant exists (independent of other tasks).
        try:
            await self.ensure_assistant_defaults(owner)
        except Exception as e:
            logger.warning(f"Failed to seed assistant for {owner}: {e}")

    async def ensure_assistant_defaults(self, owner: str):
        """Create the personal-assistant CrewMember, its pinned session, and three
        daily check-in ScheduledTasks for this owner — idempotent on is_default_assistant."""
        # Hard-reject synthetic owners. Without this, AuthMiddleware-stamped
        # values like 'internal-tool' (loopback agent-tool callbacks) or 'api'
        # (bearer-token integrations) would get a real assistant + 3 daily
        # check-ins seeded, which then double-fire alongside the human user's
        # check-ins. This was the root cause of the duplicate 'Morning check-in'
        # rows we had to manually clean up.
        if not owner or owner in REQUEST_SENTINEL_OWNERS:
            logger.info(f"ensure_assistant_defaults: skip synthetic owner {owner!r}")
            return
        from core.database import SessionLocal, CrewMember, ScheduledTask
        from core.database import Session as DbSession

        db = SessionLocal()
        try:
            existing = db.query(CrewMember).filter(
                CrewMember.owner == owner,
                CrewMember.is_default_assistant == True,  # noqa: E712
            ).first()
            if existing:
                return  # already seeded

            # Resolve a default model/endpoint from any existing session so the
            # assistant has something to call. The user can change this later.
            endpoint_url, model = self._resolve_defaults(db, owner)

            default_personality = (
                "You are the user's personal assistant. Concise, warm, a little dry. "
                "Never waste time with fluff. Default to English. Only match the other language when replying to a non-English email.\n\n"

                "CORE RULE: You MUST use your tools to take action — do not describe what you would do. "
                "Never say 'I would check your calendar' — actually call manage_calendar. "
                "Never say 'I can look that up' — actually call web_search or search_chats. "
                "If you have a tool for it, use it. No hypotheticals, no promises, only actions and results.\n\n"

                "DECISION FRAMEWORK — follow these rules, not just tool descriptions:\n\n"

                "CONTEXT GATHERING (before any response involving a specific person):\n"
                "1. resolve_contact if you only have a name and need their email\n"
                "2. search_chats for recent conversations mentioning them or their topic\n"
                "3. manage_memory to check stored facts about them\n"
                "Skip steps you already have answers for. Don't search for the user themselves.\n\n"

                "EMAIL HANDLING:\n"
                "- If a document is open in the editor, that IS the email. Use update_document to write the reply.\n"
                "- BEFORE drafting any reply: gather context (steps above) about the sender and topic.\n"
                "- When an email mentions a date/meeting: check calendar for conflicts, add if clear.\n"
                "- When an email asks a question you can't answer from context: say so honestly. Never fabricate.\n"
                "- Skip automated/marketing emails in check-ins. Only surface human-sent, actionable ones.\n"
                "- Never duplicate information the user already saw in a previous check-in.\n\n"

                "ESCALATION LADDER (when you need info you don't have):\n"
                "1. search_chats (fast, free)\n"
                "2. manage_memory (fast, free)\n"
                "3. web_search (medium cost)\n"
                "4. trigger_research (expensive, async — only for complex multi-source questions)\n"
                "Stop as soon as you have a sufficient answer.\n\n"

                "'SEND TO [NAME]' FLOW:\n"
                "1. resolve_contact to find their email\n"
                "2. If a document is open, use its content as the body\n"
                "3. Draft the email in a document (create_document with language='email')\n"
                "4. Tell the user to review — NEVER auto-send\n\n"

                "SELF-IMPROVEMENT — use manage_memory constantly:\n"
                "- When the user corrects you, IMMEDIATELY store the correction as a memory.\n"
                "- After every check-in or task, store new facts you learned (contacts, preferences, patterns).\n"
                "- Before responding about a person or topic, search_chats and manage_memory FIRST.\n"
                "- Build knowledge over time: who people are, what projects are active, how the user likes things done.\n"
                "- If something failed or you got corrected, store WHY so you never repeat it.\n"
                "- When you figure out a multi-step workflow that works, save it as a SKILL using manage_skills.\n"
                "  A skill is a reusable procedure. Next time, recall the skill instead of figuring it out again.\n"
                "- Before starting a complex task, check manage_skills for an existing procedure.\n\n"

                "AUTONOMY RULES:\n"
                "- Auto-add calendar events from clear meeting invitations (mention what you added)\n"
                "- Auto-draft email replies (cached for when user clicks Reply)\n"
                "- NEVER send emails without explicit user instruction\n"
                "- NEVER delete anything without explicit instruction\n"
                "- If uncertain, ask rather than guess"
            )

            # Create the singleton session first (CrewMember.session_id links to it).
            session_id = str(uuid.uuid4())
            sess = DbSession(
                id=session_id,
                name="Assistant",
                endpoint_url=endpoint_url or "",
                model=model or "",
                owner=owner,
                is_important=True,
                mode="agent",
                folder="Assistant",
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.add(sess)
            db.flush()

            # Create the assistant CrewMember.
            crew_id = str(uuid.uuid4())
            assistant = CrewMember(
                id=crew_id,
                owner=owner,
                name="Assistant",
                avatar=None,
                user_name=None,
                personality=default_personality,
                model=model,
                endpoint_url=endpoint_url,
                greeting=None,
                enabled_tools=json.dumps([
                    "manage_calendar", "manage_notes", "manage_tasks", "manage_memory",
                    "list_email_accounts", "list_emails", "read_email", "send_email", "reply_to_email", "archive_email",
                    "mark_email_read", "delete_email", "resolve_contact",
                    "search_chats", "web_search", "web_fetch", "read_file",
                    "create_document", "update_document", "edit_document",
                    "generate_image", "trigger_research",
                    "download_model", "serve_model", "list_served_models", "stop_served_model",
                    "edit_image",
                ]),
                session_id=session_id,
                is_active=True,
                sort_order=0,
                is_default_assistant=True,
                timezone=None,  # user picks in settings; None = legacy UTC behavior
            )
            db.add(assistant)

            # Link the session back to the crew member so UI can resolve either way.
            sess.crew_member_id = crew_id

            # No auto-seeded check-in tasks. The old behaviour created three
            # daily ScheduledTasks (Morning/Midday/Evening) under every new
            # owner, which was intrusive and ran under whatever account was
            # marked is_default globally. Users now create their own
            # recurring tasks from the Tasks UI.

            db.commit()
            logger.info(f"Seeded personal assistant (crew {crew_id}) for owner={owner}")
        except Exception as e:
            logger.exception(f"ensure_assistant_defaults({owner}) failed: {e}")
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()
