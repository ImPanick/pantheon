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
from typing import Any, Awaitable, Callable, Dict, NamedTuple, Tuple

from core.auth import RESERVED_USERNAMES
from src.event_bus import (
    EVENT_DOCUMENT_CREATED,
    EVENT_MEMORY_ADDED,
    EVENT_RESEARCH_COMPLETED,
    EVENT_SESSION_CREATED,
    EVENT_SKILL_ADDED,
    build_task_handoff as _build_task_handoff,
    trigger_context_message as _trigger_context_message,
    trigger_summary as _trigger_summary,
)
from src.interactive_gate import STARTED_BY, STARTED_BY_BACKGROUND, STARTED_BY_PERSON
from src.owner_identity import REQUEST_SENTINEL_OWNERS
from src import paced_http  # `B1014`: NO_PROXY ranges, read for every client
from src.task_action_policy import (
    admin_only_action_of,
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
# `_executing_lock` — claimed in `_check_due_tasks`, in `run_task_now` and,
# for a chain, in `_advance_chain` through `_claim_chained` (`P22-01` moved it
# there from `_run_chained`, so the run's "Continued to" line and the claim are
# one decision), released in `_execute_task`'s `finally` — and is completely independent of
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


# ── `P22-01` · one rule for what a workflow may be ──────────────────────────
#
# `_chain_refusal` walked `then_task_id` and nothing else, while `_advance_chain`
# takes both `EDGE_COLUMNS` edges. So a failure edge went round the loop check
# AND the depth cap: *"if the backup fails run cleanup; when cleanup works run
# the backup"* was saved without a word, and the two could run each other for
# ever. Measured on the tree before this block by driving it: `PUT` accepted
# that edit, `_chain_refusal` answered `None` from both ends of the loop, and
# `None` again from step two of a thirteen-step chain wired on failure alone.
# Nothing checked at save — `_validate_then_task_id` checks one edge's target
# (not itself, same owner) and nothing about where the edges lead.
#
# `validate_graph` is the rule, once. It takes rows, as `build_task_graph` does,
# so the route at save and the engine at run hand it what they already hold and
# it cannot be asked two different questions (`Law 7`). It answers in
# `CHAIN_REFUSAL_REASONS`' three words and no fourth (`Law 10`).
#
# **Nothing that was refused is now permitted.** The walk follows
# `EDGE_CONDITIONS` in order, success first, so the first path it walks from any
# task is exactly the success-only path the old loop walked — with the same
# checks in the same order (the cap once its budget is spent, then loop, then
# owner) — and it reaches whatever the old
# loop refused, for the same reason, before it looks at a failure edge at all.
# `tests/test_one_rule_for_what_a_workflow_may_be.py` holds that against the old
# walk itself, on graphs it generates.

# The words a person reads for each condition. Keyed by `EDGE_CONDITIONS`, so a
# third condition cannot ship without a sentence for it (a test asserts that).
EDGE_WORDS = {
    EDGE_WHEN_SUCCESS: "works",
    EDGE_WHEN_ERROR: "fails",
}

# `P22-01`. Not a refusal of the graph, which is why it is not in
# `CHAIN_REFUSAL_REASONS`: the chain is fine, and its next task is busy.
CHAIN_ALREADY_RUNNING = "it was already running"


class GraphRefusal(NamedTuple):
    """Why a workflow may not run as drawn. `P22-01`.

    `reason` is a `CHAIN_REFUSAL_REASONS` key — an enum, never a sentence.
    `start` is the task the refused walk began at: a task some edge leads to,
    which is where `_advance_chain` asks. `path` is the edges, shaped as
    `task_edges` shapes them, from `start` to the defect — for `cycle`, exactly
    the loop and nothing before it, so the sentence names the tasks in it.
    """
    reason: str
    start: str
    path: tuple


def chain_entry_points(tasks) -> list:
    """Every task an edge leads to, in row order. Each is a place
    `_advance_chain` can be asked to continue to, and so a place the engine
    walks from; a task nothing leads to is a head, and is never walked from."""
    seen = set()
    out = []
    for task in tasks:
        for edge in task_edges(task):
            if edge["to"] not in seen:
                seen.add(edge["to"])
                out.append(edge["to"])
    return out


def chain_starts_through(tasks, task_id: str) -> list:
    """The walks a change to `task_id`'s edges can alter.

    From each entry point whose chain reaches `task_id` (so a mid-chain edit
    that makes an EARLIER step's chain too long is caught where it is made),
    and from `task_id`'s own successors. A defect elsewhere in the person's
    tasks is not this save's to refuse — the engine still refuses it at run,
    in that run's step log.
    """
    feeds = {}
    by_id = {}
    for task in tasks:
        by_id[task.id] = task
        for edge in task_edges(task):
            feeds.setdefault(edge["to"], []).append(edge["from"])
    upstream = {task_id}
    frontier = [task_id]
    while frontier:
        nxt = []
        for node in frontier:
            for pred in feeds.get(node, ()):
                if pred not in upstream:
                    upstream.add(pred)
                    nxt.append(pred)
        frontier = nxt
    own = by_id.get(task_id)
    successors = {e["to"] for e in task_edges(own)} if own is not None else set()
    return [s for s in chain_entry_points(tasks) if s in upstream or s in successors]


def validate_graph(tasks, *, starts=None, owner: str | None = None,
                   max_depth: int = CHAIN_MAX_DEPTH) -> "GraphRefusal | None":
    """The first reason this workflow may not run, or `None`. Pure.

    `tasks` is rows — anything with `id`, `owner` and the `EDGE_COLUMNS`
    columns — the ones the caller already holds (`Law 7`). `starts` is where
    to walk from; by default every `chain_entry_points` task. Every path from
    each start, along every edge, is walked:

      * **`too_deep`** — a path of more than `max_depth` tasks from its start;
      * **`cycle`** — a path that comes back to a task already on it;
      * **`cross_owner`** — a task on it that `owner` does not own (skipped when
        `owner` is `None`, as the old walk skipped it).

    A successor that is not among `tasks` ends that path and is not a refusal,
    as a missing row was not before. Out of a task the edges are taken in
    `EDGE_CONDITIONS` order, which is what makes the success-only path the first
    one walked (see the block comment above).
    """
    by_id = {task.id: task for task in tasks}
    if starts is None:
        starts = chain_entry_points(tasks)

    def visit(start, node_id, on_path, taken):
        if len(on_path) >= max_depth:
            return GraphRefusal(CHAIN_TOO_DEEP, start, tuple(taken))
        if node_id in on_path:
            return GraphRefusal(CHAIN_CYCLE, start,
                                tuple(taken[on_path.index(node_id):]))
        row = by_id.get(node_id)
        if row is None:
            return None
        if owner is not None and getattr(row, "owner", None) != owner:
            return GraphRefusal(CHAIN_CROSS_OWNER, start, tuple(taken))
        on_path.append(node_id)
        try:
            for edge in task_edges(row):
                found = visit(start, edge["to"], on_path, taken + [edge])
                if found is not None:
                    return found
        finally:
            on_path.pop()
        return None

    for start in starts:
        found = visit(start, start, [], [])
        if found is not None:
            return found
    return None


def load_chain_rows(db, start_ids, *, known=None,
                    max_depth: int = CHAIN_MAX_DEPTH) -> list:
    """The rows a walk from `start_ids` reads, fetched by id a level at a time.

    `P22-01`. The session half of `validate_graph`, kept apart so the rule
    itself takes rows. `known` is rows the caller already holds — and the one
    the route is about to save, whose edges are not in the database yet — and
    those win over the database. No owner filter: a chain that reaches someone
    else's task is a refusal, and a query scoped to the caller would make that
    task look missing, which is not.

    `max_depth` levels are enough: a task at depth `d` on some path is at most
    `d` levels from a start, and the walk refuses at depth `max_depth` before
    it reads that row.
    """
    from core.database import ScheduledTask

    rows = dict(known or {})
    frontier = [i for i in dict.fromkeys(start_ids) if i]
    seen = set(frontier)
    for _ in range(max_depth):
        missing = [i for i in frontier if i not in rows]
        if missing:
            for row in db.query(ScheduledTask).filter(
                    ScheduledTask.id.in_(missing)).all():
                rows[row.id] = row
        nxt = []
        for node_id in frontier:
            row = rows.get(node_id)
            for edge in (task_edges(row) if row is not None else ()):
                if edge["to"] not in seen:
                    seen.add(edge["to"])
                    nxt.append(edge["to"])
        if not nxt:
            break
        frontier = nxt
    return list(rows.values())


def describe_graph_refusal(refusal: GraphRefusal, names=None, *,
                           first: str | None = None,
                           lead: str | None = None) -> str:
    """The sentence a person is told on Save, naming the tasks. `P22-01`.

    Led by `CHAIN_REFUSAL_REASONS[reason]`, the same words the run's step log
    uses, so a refusal reads the same at save and at run (`Law 10`). `names`
    maps task id to the name a person knows it by; an id stands in for a name
    nobody passed. Another owner's task is never named — only the person's own
    task that leads to it. `first` is the task the person is saving: a loop
    through it is told starting from it, because that is the link they just
    drew.

    `P22-05`. `lead` replaces the reason's words for a caller whose thing is
    not a chain — a workflow document's loop is told "The workflow loops back
    on itself: …", the rest of the sentence built here exactly as for a chain.
    """
    names = names or {}

    def called(task_id):
        return f"“{names.get(task_id) or task_id}”"

    lead = lead or CHAIN_REFUSAL_REASONS[refusal.reason]
    lead = lead[:1].upper() + lead[1:]
    path = list(refusal.path)
    if refusal.reason == CHAIN_CYCLE and path:
        turn = next((i for i, e in enumerate(path) if e["from"] == first), 0)
        path = path[turn:] + path[:turn]
        hops = [f"if {called(e['from'])} {EDGE_WORDS.get(e['when'], e['when'])} "
                f"it runs {called(e['to'])}" for e in path]
        hops[-1] += " again"
        said = hops[0] if len(hops) == 1 else ", ".join(hops[:-1]) + ", and " + hops[-1]
        return f"{lead}: {said}. Remove one of those links to save it."
    if refusal.reason == CHAIN_TOO_DEEP and path:
        return (f"{lead}: from {called(refusal.start)} to {called(path[-1]['to'])} "
                f"is {len(path) + 1} tasks in a row. Shorten it, or give part of "
                f"it its own trigger.")
    if refusal.reason == CHAIN_CROSS_OWNER and path:
        return (f"{lead}, after {called(path[-1]['from'])}. A chain can only "
                f"run your own tasks.")
    return f"{lead}."


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

    `B1059`. A DRY run is not part of the history this reads: it is recorded
    `skipped` (`P8-33`), so one *Show me what this would do* between two
    failures stopped the count at zero and handed out a fresh retry budget and
    the first rung of `P15-08`'s ladder — a side effect of the one button that
    promises none. `real_run_clause` is `is_dry_run`, negated, in SQL (`B1054`).
    """
    from core.database import TaskRun

    q = (db.query(TaskRun.id, TaskRun.status)
           .filter(TaskRun.task_id == task_id, real_run_clause(TaskRun))
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


# `P8-32`. A ceiling nobody can set is not a ceiling, and one that can be set
# to three seconds is a task that can never finish. The floor is the smallest
# number that leaves room for a model call to connect and answer; `0` and NULL
# both mean "no ceiling", which is what every run has had until this row.
MIN_TASK_TIMEOUT_SECONDS = 30
MAX_TASK_TIMEOUT_SECONDS = 24 * 60 * 60


def task_timeout_seconds(task) -> int:
    """This task's wall-clock ceiling in seconds, or `0` for none."""
    raw = getattr(task, "timeout_seconds", None)
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    return max(MIN_TASK_TIMEOUT_SECONDS, min(MAX_TASK_TIMEOUT_SECONDS, value))


class FailureSchedule(NamedTuple):
    """Where a failed run puts `next_run`, and what to tell the person."""
    next_run: datetime | None
    is_retry: bool
    attempt: int
    delay_seconds: float
    note: str


def failure_next_run(db, task, *, run_id: str, now=None) -> FailureSchedule:
    """When a task that just failed goes again. One decision, both failures.

    `P8-32`. Three things meet here and none of them is new machinery.

    **`P15-08`'s ladder is the only ladder.** `failure_backoff_seconds` is
    `rate_limiter.penalise`'s shape and it is jittered, so this adds no second
    idea of backing off and nothing new for `.pantheon/check-jitter.py` to
    police. `apply_interval_floor` still holds the minimum gap on top, because
    a retry is one more request to the provider that has just refused us and
    `FORBIDDEN.md` Part 2 is about exactly that standing.

    **`P8-24`'s vocabulary supplies the unit.** `delay_seconds` is the
    `retry_after` a `NODE_STATUS_DEFERRED` result carries — the same number,
    meaning the same thing. What is deliberately NOT reused is `deferred`
    itself: `TaskDeferred` deletes the run row (`B675`), and a failure with
    retries left is the one case where the row is the whole point. A retry is a
    failure that is coming back, not a run that never happened.

    **The attempt count is read, not stored.** `consecutive_failures` already
    derives it from `task_runs`, and `P15-08` chose that over a column for the
    reason this row would otherwise repeat: a counter beside a history that
    already answers the question is a second copy that can disagree (`Law 14`).

    With `max_retries` unset — every task in every existing install — the
    result is byte-for-byte what this code computed before: the schedule,
    pushed out if the backoff is later.
    """
    now = now or _utcnow()
    scheduled = None
    if (getattr(task, "trigger_type", None) or "schedule") == "schedule":
        scheduled = compute_next_run(
            task.schedule, task.scheduled_time,
            task.scheduled_day, task.scheduled_date,
            after=now,
            cron_expression=task.cron_expression,
            tz_name=_resolve_task_timezone(db, task),
        )
    attempt = consecutive_failures(db, task.id, before_run_id=run_id) + 1
    delay = failure_backoff_seconds(attempt)
    backed_off = apply_interval_floor(now + timedelta(seconds=delay), now)
    budget = max(0, int(getattr(task, "max_retries", None) or 0))

    if scheduled is None:
        # An event- or webhook-triggered task waits for its trigger, and always
        # has. Re-firing it on a clock would make it a different kind of task.
        return FailureSchedule(None, False, attempt, delay, "")
    if attempt <= budget:
        return FailureSchedule(
            backed_off, True, attempt, delay,
            f"Failed — retrying (attempt {attempt} of {budget}) in "
            f"{_human_gap(delay)}, at {backed_off.isoformat()}Z")
    if backed_off > scheduled:
        note = (f"Failed {attempt} time(s) in a row — next run held back to "
                f"{backed_off.isoformat()}Z instead of its schedule")
        if budget:
            note = (f"Failed — {budget} retry attempt(s) used up. " + note)
        return FailureSchedule(backed_off, False, attempt, delay, note)
    return FailureSchedule(scheduled, False, attempt, delay, "")


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


def valid_timezone(name: str | None) -> str | None:
    """`name` if `zoneinfo` knows it, else `None`.

    `P8-32`. A typo here is the worst possible failure mode, because it is
    silent and it is wrong by hours: `compute_next_run` catches the lookup
    error and falls back to naive UTC, so "Ameria/New_York" produces a task
    that runs, every day, at the wrong time, with nothing anywhere saying so.
    The API refuses the value instead, and this is the one function that
    decides — so the route's validation and the executor's resolution cannot
    disagree about which zones exist (`Law 7`).
    """
    name = (name or "").strip()
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(name)
    except Exception:
        return None
    return name


def _resolve_task_timezone(db, task) -> str | None:
    """The IANA zone this task's wall-clock time is in, or `None` for UTC.

    `P8-32`. Order: the task's own `tz_name`, then its linked crew member's,
    then none. The second is what this function used to be and is preserved
    exactly (`Law 1`) — a task linked to a crew member and carrying no zone of
    its own still fires in that crew member's local time.

    The task's own value wins because it is the more specific statement: a
    crew member is a persona that several tasks share, and "this report runs at
    09:00 Sydney time" is a fact about the report. A stored value that
    `zoneinfo` no longer knows falls through to the crew member rather than
    silently meaning UTC, which is what an un-validated read would do.
    """
    own = valid_timezone(getattr(task, "tz_name", None))
    if own:
        return own
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


def _task_period_seconds(task, *, now=None, tz_name: str | None = None):
    """Seconds between this task's runs, or None when it cannot be derived.

    `P8-32` corrected the zone this reads. It was `getattr(task, "tz_name", None)`
    — a column that did not exist, so it was `None` on every task ever, while
    `_execute_task_locked` computed the same task's next run through
    `_resolve_task_timezone` and got the crew member's zone. **Two answers to
    one question**, and the one used to size the dispatch spread was the wrong
    one. It is passed in now, resolved once by the caller that holds the
    session, so there is one resolver (`Law 7`).
    """
    now = now or _utcnow()
    try:
        nxt = compute_next_run(
            schedule=task.schedule,
            scheduled_time=task.scheduled_time,
            scheduled_day=task.scheduled_day,
            scheduled_date=task.scheduled_date,
            after=now,
            cron_expression=task.cron_expression,
            tz_name=tz_name,
        )
    except Exception:
        return None
    if not nxt:
        return None
    seconds = (nxt - now).total_seconds()
    return seconds if seconds > 0 else None


def dispatch_hold(task, *, now=None, tz_name: str | None = None) -> float:
    """The spread for one due task. Zero is a legitimate answer."""
    from src.jitter import spread
    period = _task_period_seconds(task, now=now, tz_name=tz_name)
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


# `P8-33`'s first line of every plan, named once. `P22-04`: the agent's
# `manage_tasks` `dry_run` reads a run back and has to tell a plan from a run
# the engine declined to plan (a paused task, an admin refusal), and it does so
# by this line rather than by a second copy of it (`Law 7`).
#
# `B1054`. `DRY_RUN_MARK` is what every dry run's `result` starts with — a plan
# (the headline) and a dry run the engine declined (`_record_dry_run`) alike —
# so "is this row a dry run" has one answer, in Python (`is_dry_run`) and in
# SQL (`real_run_clause`), and a dry run is never a task's last run.
DRY_RUN_MARK = "Dry run — "
# `P23-05` (COPY-U-27): said once — "nothing changed" restated "nothing ran". The
# MARK is the stored prefix every reader keys on and does not move; rows already
# written keep the longer sentence and still start with it.
DRY_RUN_HEADLINE = f"{DRY_RUN_MARK}nothing ran."


def is_dry_run(run) -> bool:
    """`B1054`. Is this run row a dry run (a plan, or a declined plan)?"""
    return (getattr(run, "status", None) == "skipped"
            and (getattr(run, "result", None) or "").startswith(DRY_RUN_MARK))


def real_run_clause(run_model):
    """`B1054`. `is_dry_run` negated, as a SQL condition on `TaskRun`."""
    from sqlalchemy import func, or_
    return or_(
        run_model.status.is_(None),
        run_model.status != "skipped",
        ~func.coalesce(run_model.result, "").startswith(DRY_RUN_MARK, autoescape=True),
    )


class LastRun(NamedTuple):
    """A task's newest real run, as much of it as a list shows. `B1043`."""
    status: str | None
    result: str | None
    error: str | None


def plain_waiting_list(db, owner: str | None) -> list:
    """`B1102`. `GET /api/tasks/waiting`: every plain Prompt task of `owner`'s
    whose run waits for a yes right now, oldest first — `{task_id, task, run_id,
    node_id, item, label, kind, since, until, tool_label, approval}`, the workflow waiting
    list's shape with the task in the workflow's place. `approval` is the card
    while the store still holds it (so the page re-offers only a question that
    can still be answered), else null. Never the session the card is bound to."""
    from core.database import ScheduledTask, TaskRun, TaskRunNode
    from src import workflow_runs as wr
    from src.tool_approvals import tool_approval_store

    q = (db.query(TaskRunNode, TaskRun, ScheduledTask)
         .join(TaskRun, TaskRun.id == TaskRunNode.run_id)
         .join(ScheduledTask, ScheduledTask.id == TaskRun.task_id)
         .filter(TaskRunNode.node_id == PLAIN_TASK_NODE, TaskRunNode.status == "waiting",
                 TaskRun.status == "waiting", ScheduledTask.task_type == "llm"))
    if owner:
        q = q.filter(ScheduledTask.owner == owner)
    out = []
    for rec, run, task in q.order_by(TaskRunNode.started_at).all():
        waiting = wr.waiting_of(rec) or {}
        kind = waiting.get("kind")
        approval = None
        if kind == wr.WAITING_APPROVAL and tool_approval_store.peek(waiting.get("approval_id")):
            approval = waiting.get("card")
        out.append({"task_id": task.id, "task": task.name, "run_id": run.id,
                    "node_id": rec.node_id, "item": None, "label": rec.label, "kind": kind,
                    "since": waiting.get("since"), "until": waiting.get("until"),
                    "tool_label": waiting.get("tool_label") or None,
                    "approval": approval})
    return out


def latest_real_runs(db, task_ids, *, clip: int = 500) -> dict:
    """The newest run of each task that is not a dry run, in one query.

    `B1054`. `GET /api/tasks?include_last_run=true` took each task's newest
    row, so after *Show me what this would do* a step whose last real run
    failed read "Last run: Skipped" (measured by verify-a, and again here).
    `B1043`. And it took it through `ScheduledTask.runs`, a lazy relationship
    ordered by `started_at`: one query per task, loading EVERY run of every
    task — steps JSON and all — to read one. Measured on the route: 20 tasks
    with 50 runs each, 21 statements and 1,001 `TaskRun` rows loaded to serve
    20; 40 × 200, 41 statements and 8,001 rows. This is one statement (per
    500 tasks), and it loads three short columns per task, not rows.
    Ties on `started_at` take the highest id, an arbitrary rule written down,
    where the relationship's order was an arbitrary rule nobody wrote.
    """
    from sqlalchemy import and_, func
    from core.database import TaskRun

    ids = [i for i in dict.fromkeys(task_ids) if i]
    found = {}
    real = real_run_clause(TaskRun)
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        newest = (db.query(TaskRun.task_id.label("task_id"),
                           func.max(TaskRun.started_at).label("at"))
                  .filter(TaskRun.task_id.in_(chunk), real)
                  .group_by(TaskRun.task_id)
                  .subquery())
        rows = (db.query(TaskRun.task_id, TaskRun.status,
                         func.substr(TaskRun.result, 1, clip),
                         func.substr(TaskRun.error, 1, clip))
                .join(newest, and_(TaskRun.task_id == newest.c.task_id,
                                   TaskRun.started_at == newest.c.at))
                .filter(real)
                .order_by(TaskRun.task_id, TaskRun.id.desc())
                .all())
        for task_id, status, result, error in rows:
            found.setdefault(task_id, LastRun(status, result, error))
    return found

# `B1036`. What a task that is not `active` would do if a real run reached it:
# nothing — `_execute_task_locked` records it `skipped` before any executor.
# Keyed by the stored status (`FORBIDDEN.md`: task status values), so the plan
# says it in words. `B1037` reads the same words for a chain that stops there.
NOT_ACTIVE_WORDS = {
    "paused": "it is paused",
    "completed": "it was a one-off and has already run",
}


def not_active_words(task) -> str | None:
    """Why a real run would not start `task`, or `None` if it would."""
    status = getattr(task, "status", None) or "active"
    if status == "active":
        return None
    return NOT_ACTIVE_WORDS.get(status, f"its status is {status}")


def dry_run_declined(task, db=None) -> str | None:
    """Why a dry run would not plan `task`, or `None` if it plans it.

    `B1036`. Two reasons and no third: the task is gone, or its action is one
    the engine would refuse to run for this owner (`ADMIN_ONLY_TASK_ACTIONS`) —
    the same sentence the real run's refusal writes, so a dry run is not a way
    to read an admin-only task's configuration. A paused task is planned.

    `P22-05`. With `db`, a workflow's trigger is asked the same question about
    every step in its document (`admin_only_action_of`), so a workflow is not a
    way to read an admin-only step's command either — declined in the same
    words, nothing paused, nobody told (`B1036`'s ruling, kept for workflows).
    """
    if task is None:
        return "Task no longer active (status=deleted)"
    if (is_admin_only_task_action(task.task_type, task.action)
            and not owner_has_admin_task_privileges(task.owner)):
        from src.task_action_policy import admin_refusal_message
        return admin_refusal_message(task.action)
    if db is not None and (task.task_type or "llm") == "workflow":
        from src.task_action_policy import admin_only_action_of, admin_refusal_message
        found = admin_only_action_of(db, task)
        if found and not owner_has_admin_task_privileges(task.owner):
            return admin_refusal_message(found)
    return None


def shape_run_step(fields: dict, *, max_detail: int = 400) -> dict:
    """One step as a run's step log holds it: long text clipped, `at` stamped.

    `P22-04`. Pulled out of `TaskScheduler._record_run_step` so a chain dry
    run's successors — planned, never recorded — carry steps in exactly the
    shape the head's recorded run does (`Law 7`).
    """
    for key in ("detail", "output"):
        value = fields.get(key)
        if isinstance(value, str) and len(value) > max_detail:
            fields[key] = value[:max_detail].rstrip() + "\u2026"
    fields.setdefault("at", _utcnow().isoformat() + "Z")
    return fields


def chain_dry_run_rows(db, head) -> tuple:
    """The rows a chain dry run from `head` reads, and `validate_graph`'s
    answer about them: `(rows, refusal or None)`.

    `P22-04`. Walked from `head`'s successors with `head.owner`, which is what
    `_advance_chain` asks before it continues from `head` (`_chain_refusal`) —
    so a chain the engine would refuse to continue is refused here, for the
    same reason, and a chain it runs is planned. Every later step's own walk is
    a part of these, so nothing deeper can be refused that these allow.
    """
    starts = list(dict.fromkeys(edge["to"] for edge in task_edges(head)))
    rows = load_chain_rows(db, starts, known={head.id: head})
    refusal = validate_graph(rows, starts=starts, owner=head.owner) if starts else None
    return rows, refusal


def plan_dry_chain(head, rows, *, head_steps, head_declined=None,
                   name_of=None) -> list:
    """Every task reachable from `head`, each once, breadth first, planned.

    `P22-04`, the chain dry run's contract: `{task_id, name, when, depth, steps,
    declined}` per task, the head first (`when` None, depth 0, the steps its
    recorded run holds). `when` is the edge condition from the task's first
    parent in that order — `EDGE_CONDITIONS` order out of each task, so "if it
    works" before "if it fails". A successor's `steps` are `dry_run_lines`,
    the planner the head's run was written by, shaped as a recorded step and
    recorded nowhere: no run row, no history, no notification. `declined` is
    `dry_run_declined`'s sentence (and then no steps), or None — a paused step
    is planned, and its plan says a real run would not start it (`B1036`).
    A successor with no row (deleted) ends that branch, as it does in a run.
    """
    by_id = {row.id: row for row in rows}
    name_of = name_of or (lambda task: task.name)
    out = [{"task_id": head.id, "name": name_of(head), "when": None, "depth": 0,
            "steps": list(head_steps or []), "declined": head_declined}]
    seen = {head.id}
    frontier = [head]
    depth = 0
    while frontier:
        depth += 1
        following = []
        for node in frontier:
            for edge in task_edges(node):
                row = by_id.get(edge["to"])
                if row is None or row.id in seen:
                    continue
                seen.add(row.id)
                following.append(row)
                declined = dry_run_declined(row)
                steps = [] if declined else [
                    shape_run_step({"kind": "dry-run", "detail": line})
                    for line in dry_run_lines(row)]
                out.append({"task_id": row.id, "name": name_of(row),
                            "when": edge["when"], "depth": depth,
                            "steps": steps, "declined": declined})
        frontier = following
    return out


# `P23-05` (COPY-M-13): where a result goes, in words — the stored
# `output_target` is a key (`FORBIDDEN.md` Part 1), never a place a person reads.
_RESULT_PLACES = {"session": "a chat", "email": "your email", "document": "a document",
                  "notification": "a notification, and a chat"}


def result_place(target) -> str:
    """`session` → "a chat"; an MCP tool target by its server and tool."""
    key = str(target or "session")
    if key in _RESULT_PLACES:
        return _RESULT_PLACES[key]
    if key.startswith("mcp__"):
        return "the tool " + key[len("mcp__"):].replace("__", " › ")
    return key


def dry_run_lines(task) -> list:
    """The plan for `task`, headline first. Runs nothing, reads no session.

    `P8-33`'s lines (`dry_run_plan`, which reads a registry and the task's
    columns), then where the result would go, then — `B1036` — whether a real
    run would start it at all. One planner (`Law 7`): `_record_dry_run`
    writes these on the head's run, and `plan_dry_chain` hands the same lines,
    unrecorded, for every step after it (`P22-04`).
    """
    from src.builtin_actions import dry_run_plan

    lines = dry_run_plan(
        task_type=task.task_type,
        action=task.action,
        prompt=task.prompt,
        owner=task.owner,
        model=task.model,
        endpoint_url=task.endpoint_url,
        extra=[f"Result goes to: {result_place(task.output_target)}"],
    )
    why_not = not_active_words(task)
    if why_not:
        lines.append(f"{why_not[:1].upper()}{why_not[1:]}, so a real run would not start it.")
    return [DRY_RUN_HEADLINE, *lines]

# `B1047`. Why an `aborted` run ended, in the words its row carries. Named once
# because three places write them — the stop button (`stop_task`), the
# foreground gate (`stop_background_tasks_for_foreground` and the running-run
# monitor) and the cancel branch that has to keep whichever of the first two
# got there first — and `core/database.py`'s `aborted` entry promises the
# message says which event it was. The gate wrote "Stopped by user" for its own
# pre-emption (`_mark_run_aborted`'s default), so a run nobody stopped told the
# person they had stopped it.
STOPPED_BY_USER = "Stopped by user"
FOREGROUND_TAKEOVER = "Paused because Pantheon became active"
# `B1047`. The row of a run a person started while a chat reply is being
# written, beside `_execute_task`'s "Queued — waiting for a free slot…" and the
# background gate's "Queued — waiting for Pantheon to be idle…".
WAITING_FOR_CHAT = "Queued — waiting for the chat reply in progress to finish…"
WAITING_FOR_IDLE = "Queued — waiting for Pantheon to be idle…"

# `B1060`. How many times in a row one trigger's run may be stopped by the
# foreground gate WHILE RUNNING; the stops before the last put it back in the
# queue, the last one lets it go and says so. Each attempt starts again from the
# beginning — the model calls and whatever the steps did are spent again — so a
# run longer than the person's idle spells would otherwise restart every time
# they look away, for ever. Mistake prevention, not a control (`Law 17`): three
# is "the person came back three times while it ran".
FOREGROUND_STOPS_LIMIT = 3


class _Requeued:
    """`B1060`. What `_execute_task_locked` answers when the foreground gate
    stopped the run while it was running and the run goes back in the queue
    with its trigger. One instance, compared by identity; never stored."""

    __slots__ = ()

    def __repr__(self):  # pragma: no cover - diagnostics
        return "REQUEUED"


REQUEUED = _Requeued()


def _human_ms(seconds: float) -> int:
    return int(round(max(0.0, seconds) * 1000))


# `P22-05`. Which task types say so when a run WORKED — a run that produced
# something a person reads. Housekeeping actions stay quiet on success. It was
# the literal `{"llm", "research"}`, twice (`_notify_run_outcome` and the error
# path's notification); a workflow — the person's own steps, producing their
# result — notifies as a Prompt task does. One tuple, both places (`Law 7`).
NOTIFY_ON_SUCCESS_TASK_TYPES = ("llm", "research", "workflow")

# `P22-05` / `P8-27`. A workflow step runs under its own slot in `_run_state`,
# `"<run id>:<step id>"`, created when the step starts and dropped when it ends
# — so each step's model, step log and trigger are its own, and a run's slot
# keeps the run's. Run ids are uuids and step ids `[A-Za-z0-9_-]`, so the
# separator cannot occur in either. *Test this step* uses `"test:<uuid>"`,
# which names no run row.
NODE_SLOT_SEPARATOR = ":"
TEST_SLOT_PREFIX = "test"


def task_chat_name(task) -> str:
    """The name of the chat a task's run makes when it has none: "[Task]"
    and the task's name — or, for a workflow step (`B1114`), the workflow's
    (`WorkflowNodeTask.chat_name`), since the walker keeps the chat the first
    step makes on the trigger and every later step writes into it. A task row
    has no `chat_name`, so a Prompt task's chat is named as before."""
    return f"[Task] {getattr(task, 'chat_name', None) or task.name}"

# `P22-05`. What the walker says when a trigger has no document to run.
WORKFLOW_DOCUMENT_MISSING = ("This workflow’s steps are missing, so there was "
                             "nothing to run.")
# `P22-05`. A step that the stop button, the foreground gate or the time limit
# ended part-way.
NODE_STOPPED = "Stopped before it finished"

# `P22-11`. What a parked run's row says, and what a run says that was
# switched off while it waited.
TAKEOVER_PARKED = ("Waiting for Pantheon to be idle: it became active while this "
                   "ran, so the step it was on stopped. It goes on from that step once "
                   "Pantheon is idle; the steps that finished are kept.")
SWITCHED_OFF_WHILE_WAITING = "Switched off while it waited"

# `P22-11`. How many deterministic and logic steps of one run run side by side
# — stated once, in `workflow_runs` beside the walker's other limits, where the
# palette (`workflow_effects._limits`) reads it too (`integrate-d`: it was
# stated here and read there, so every palette and every document check raised
# `AttributeError` on the merged tree).
from src.workflow_runs import WORKFLOW_PARALLEL_STEPS  # noqa: E402

# `P22-17`. What became of a step's question. `allow` resumes the step once
# with the consumed approval; the other three take its failure port.
ANSWER_ALLOW = "allow"
ANSWER_DENY = "deny"
ANSWER_LAPSED = "lapsed"
ANSWER_RESTARTED = "restarted"
# The card left the store before its deadline in the process that minted it.
# Until `B1103` an ordinary message typed into its chat retired a waiting card
# (`tool_approvals.retire_for_session`, the residual risk § 5 named); a run's
# question is now `held_by_run`, so what is left is the store's size cap
# (`DEFAULT_MAX_PENDING_APPROVALS`), which drops the oldest card when full.
ANSWER_WITHDRAWN = "withdrawn"

# `B1102`. A plain Prompt task's run that parks on a card keeps ONE waiting
# record in `task_run_nodes` — the walker's record, under this step id — so the
# sweeper (a lapse, a restart), Stop, a switch-off and the answer core read it
# exactly as they read a workflow step's (`Law 14`). Written only when the run
# parks: a run that never asks keeps the shape it always had.
PLAIN_TASK_NODE = "task"
#: The task types whose run can park: a workflow's (`P22-11`) and a plain
#: Prompt task's (`B1102`). A parked run of either holds its task (`B674`).
_PARKING_TASK_TYPES = ("workflow", "llm")


class QuestionRefused(Exception):
    """`B1102`. An answer `TaskScheduler.answer_question` will not take: the
    HTTP status and the sentence. Each door says it in its own shape."""

    def __init__(self, status: int, sentence: str):
        super().__init__(sentence)
        self.status, self.sentence = status, sentence


class StepDone(NamedTuple):
    """One step's end: its `NodeResult`, and the port it chose — a logic
    step's `then` / `otherwise` / `case:<id>`; `None` means the outcome's own
    (`success` / `error`)."""
    result: Any
    port: Any = None


class StepAnswer(NamedTuple):
    """`P22-17`. The answer a parked step resumes with. `exact_approval` is the
    consumed `ExactToolApproval` (Allow, SINGLE_ACTION scope) and travels in
    memory only: a restart in the window between the answer and the resume
    is a lapsed answer, and the step says so. `sentence` is what the step's
    log and the run's say ("Allowed once by joseph at 07:42: send_reply")."""
    node_id: str
    item: Any
    decision: str
    sentence: str = ""
    exact_approval: Any = None


def named_question(parked):
    """`B1111`. A step that parks on a card, its tool named as the step's panel
    names it (`workflow_effects.tool_words`: "Chat: send_message", not
    `mcp__0e311a43__send_message`). The words go in the waiting record as
    `tool_label` — read by the run's log line, the question's notification,
    the waiting list and the answer's sentence — and `tool` keeps the name
    the card seals. Asked once per card, where the walker first catches it
    (`_park_record`, a For-each's item); a question already named passes."""
    from src import workflow_runs as wr
    from src.builtin_actions import TaskWaiting

    if parked.kind != wr.WAITING_APPROVAL or parked.detail.get("tool_label"):
        return parked
    tool = parked.detail.get("tool")
    if not tool:
        return parked
    from src.workflow_effects import tool_words
    label = tool_words(tool) or str(tool)
    return TaskWaiting(f"Waiting for your yes on {label}", kind=parked.kind,
                       **dict(parked.detail, tool_label=label))


class _Walk:
    """One segment of one run's walk: what `_run_workflow`'s parts share."""

    def __init__(self, *, task, db, run_id, wf, graph, state, name, version,
                 started_by, waits_for):
        self.task, self.db, self.run_id = task, db, run_id
        self.wf, self.graph, self.state = wf, graph, state
        self.name, self.version = name, version
        self.started_by, self.waits_for = started_by, waits_for
        self.running = {}          # asyncio.Task → (node, record, slot)
        self.started = set()       # step ids begun or settled in this segment
        self.timers = {}           # Wait step id → (node, record, until)
        self.model_lock = asyncio.Lock()
        self.question_open = False
        self.last_model = None


def _port_word(node: dict, port) -> str:
    """The word a person reads for a port: a Switch case's own label, else the
    port itself."""
    if isinstance(port, str) and port.startswith("case:"):
        case_id = port.split(":", 1)[1]
        for case in (node.get("config") or {}).get("cases") or ():
            if isinstance(case, dict) and str(case.get("id")) == case_id:
                return str(case.get("label") or case_id)
        return case_id
    return str(port)


def node_slot(run_id: str, node_id: str) -> str:
    """The `_run_state` key a workflow step runs under."""
    return f"{run_id}{NODE_SLOT_SEPARATOR}{node_id}"


def run_of_slot(slot):
    """The run a slot belongs to: itself for a run, the run for a step's slot,
    `"test"` for a step test (which no row has)."""
    if isinstance(slot, str) and NODE_SLOT_SEPARATOR in slot:
        return slot.split(NODE_SLOT_SEPARATOR, 1)[0]
    return slot


def _waited_words(seconds: float) -> str:
    """`B1060`. How long a run waited for Pantheon to be idle, for its step log."""
    seconds = max(0, int(round(seconds)))
    if seconds < 1:
        return "under a second"
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {(seconds % 3600) // 60} min"


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
        # `B1047`. Who started the run each handle belongs to (`STARTED_BY`),
        # set and dropped beside `_task_handles`, so the foreground gate can
        # tell a run a person asked for from background work before it stops
        # anything.
        self._task_started_by = {}
        # `B1060`. The background runs the foreground gate may stop: task id →
        # run id, from the moment the run flips to `running` until it ends. A
        # background run that is still QUEUED is not here — it waits for
        # Pantheon to be idle before it takes the model slot, so it holds
        # nothing and there is nothing to stop.
        self._gate_stoppable = {}
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
        # `P22-17`. When this process started: a card minted before it was
        # lost to a restart; one minted since and gone early was withdrawn.
        self._started_at = _utcnow()

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
        """Persist short live progress text for Activity while a run is active.

        `P22-05`. A workflow step's slot (`node_slot`) writes its run's row, so
        a step's progress is the run's live text; a step test's slot names no
        row and writes nothing.
        """
        run_id = run_of_slot(run_id)
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

    def _started_by_map(self) -> dict:
        """`B1047`. `_task_started_by`, created on demand — for the same
        `__new__`-built test schedulers `_runs()` allows for."""
        started = getattr(self, "_task_started_by", None)
        if started is None:
            started = self._task_started_by = {}
        return started

    def _gate_stoppable_map(self) -> dict:
        """`B1060`. `_gate_stoppable`, created on demand, for the same
        `__new__`-built test schedulers."""
        found = getattr(self, "_gate_stoppable", None)
        if found is None:
            found = self._gate_stoppable = {}
        return found

    def _state_for(self, run_id):
        """This run's slot, created on first write."""
        runs = self._runs()
        state = runs.get(run_id)
        if state is None:
            # `P8-29` adds `payload`: what a node RETURNED, as opposed to the
            # sentence about it. `TaskRun.result` is text and always has been,
            # so a node that produced a dict had nowhere to keep it between
            # `_execute_action` and the chain decision. It lives on the run's
            # slot beside the model and the step log because it is a fact about
            # the run, which is what `P8-27` made the slot for — and the slot is
            # dropped when the run ends, so nothing accumulates.
            state = {"model": None, "steps": [], "trigger": None, "payload": None}
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

    def _run_started_by(self, run_id) -> str:
        """`B1047`. Who started this run (`STARTED_BY`). A run with no slot —
        an executor driven directly — is background work, which is what every
        run was before the word existed."""
        state = self._runs().get(run_id)
        return (state or {}).get("started_by") or STARTED_BY_BACKGROUND

    def _run_waits_for(self, run_id) -> str | None:
        """`B1047`. What this run's model work waits for: `"idle"`, `"chat"`, or
        `None` for a run a person forced to start now. Read by
        `_run_agent_loop`'s wait, which is the second of the two."""
        state = self._runs().get(run_id)
        if not state or "waits_for" not in state:
            return "idle"
        return state["waits_for"]

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
        fields = shape_run_step(fields, max_detail=self._MAX_STEP_DETAIL)
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
            # `P22-01`. The claim is taken HERE, in the same synchronous
            # statement that chooses the line to write. It was taken in
            # `_run_chained`, after this function had already written
            # "Continued to X" and handed X to `asyncio.create_task` — so when
            # X was already in flight, the run said it continued and X was
            # dropped by a bare `return` nobody saw. Now the line and the drop
            # are one decision and cannot disagree.
            if not self._claim_chained(chain_id):
                logger.info("Not chaining on %s: %r → task %s is already running",
                            when, task.name, chain_id)
                self._record_chain_outcome(
                    db, run_id, f"Did not continue to {label}: {CHAIN_ALREADY_RUNNING}")
                return
            # `B1037`. A paused (or spent one-off) successor does not run:
            # `_execute_task_locked` records it `skipped` before any executor.
            # This wrote "Continued to X" over that, the same claim `P22-01`
            # made honest for a busy successor. The line says so now. What X
            # itself records — a `skipped` run, and the notification `B112`
            # sends for a skip that leaves a task stopped — is that row's
            # notification-policy call and is left exactly as it was, so X is
            # still handed on.
            why_not = not_active_words(chain_task)
            if why_not:
                logger.info("Not continuing on %s: %r → task %s, %s",
                            when, task.name, chain_id, why_not)
                self._record_chain_outcome(db, run_id, f"Did not continue to {label}: {why_not}")
            else:
                logger.info("Chaining on %s: %r → task %s", when, task.name, chain_id)
                self._record_chain_outcome(db, run_id, f"{lead} {label}")
            # `P8-29`. What this run produced, handed to the step that follows
            # it. A chain was a sequence: `_run_chained` took an id and nothing
            # else, so "summarise this, then email the summary" could not be
            # built — step two had no way to name what step one made. Built
            # here, where the predecessor's row is already loaded, rather than
            # re-read at the far end.
            #
            # `B1047`. And who started the chain: the step a person's Run now
            # leads to is part of what they asked for, so it waits the way that
            # run waited, not the way background work does — otherwise the
            # failure branch of a run somebody is watching waits for them to
            # leave the page.
            asyncio.create_task(self._run_chained(
                chain_id, handoff=self._handoff_from(db, task, run_id, run_status),
                started_by=self._run_started_by(run_id)))
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

    def _handoff_from(self, db, task, run_id: str, run_status: str):
        """The envelope this run hands to its successor, or `None`.

        `P8-29`. Read off the run row that has just been committed, so the
        successor is given what the run actually recorded rather than a second
        copy assembled from locals (`Law 7`). A run with nothing to say hands
        `None`, and a successor given `None` builds a byte-identical message
        list to the one it built before this row — which is every chain that
        exists today (`Law 1`).
        """
        from core.database import TaskRun

        try:
            run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
            text = (run.result if run is not None else None) or ""
            payload = self._runs().get(run_id, {}).get("payload")
        except Exception:
            logger.debug("Could not build the handoff for run %s", run_id,
                         exc_info=True)
            return None
        if not text and not payload:
            # `Law 1`. A predecessor that produced nothing hands on nothing, so
            # a chain that ran ungated before this row still does: an envelope
            # carrying only bookkeeping would arm the tool gate on every chained
            # run in the product while saying nothing the successor can use.
            return None
        return _build_task_handoff(
            task_name=task.name or task.id, task_id=task.id, run_id=run_id,
            status=run_status, result=text, payload=payload,
        )

    def _claim_chained(self, task_id: str) -> bool:
        """Take `task_id`'s `_executing` claim now, or say somebody holds it.

        `P22-01`. Synchronous on purpose, so `_advance_chain` decides whether
        it continued and what its run says about it in one statement. That is
        safe without `_executing_lock`: this runs on the event loop with no
        `await` between the check and the add, and every holder of the lock in
        this file does its whole critical section without an `await` either,
        so no coroutine can be inside one while this runs (`_dispatch_after`
        already discards from the set the same way).

        A scheduler built with `__new__` for a test has no `_executing` until
        something makes one, which is `_runs()`'s allowance for the same tests.
        """
        executing = getattr(self, "_executing", None)
        if executing is None:
            executing = self._executing = set()
        if task_id in executing:
            return False
        executing.add(task_id)
        return True

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

    def _record_dry_run(self, db, task, run_id: str) -> None:
        """Write the plan onto the run row. Runs nothing, changes nothing else.

        `B1036`. `task` may be `None` (deleted between the button and here) or
        one the engine would refuse to run for this owner; either is recorded
        as a `skipped` run whose `error` and `result` say why it was not
        planned (`dry_run_declined`) — no pause, no schedule moved, nobody
        told. Anything else is planned, a paused task included: its plan's
        last line says a real run would not start it (`dry_run_lines`).

        `P8-33`. The status is `skipped` because `core/database.py` already
        defines that as *"deliberately did not run … Not a failure"*, and a
        dry run is the purest case of it. A seventh status would have to be
        taught to `check-run-statuses.py`, `static/js/runStatus.js`,
        `TASK_RUN_NOTIFY` and every consumer of the six, to say a thing the
        sixth already says (`Law 14`).

        **What this deliberately does not touch.** `last_run`, `next_run` and
        `run_count` stay exactly where they were, nothing is delivered,
        nothing is notified, and no chain advances. A dry run that moved the
        schedule would be a side effect on the one path whose entire promise is
        that it has none — and `next_run` moving is precisely how `B675`
        describes a run that left no trace.
        """
        from core.database import TaskRun

        run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
        declined = dry_run_declined(task, db=db)
        if declined is None and (task.task_type or "llm") == "workflow":
            # `P22-05`. A workflow's plan is per step, on step records (`dry`),
            # each step planned by the same `dry_run_plan` a task's is.
            declined = self._record_workflow_dry_run(db, task, run_id, run)
            if declined is None:
                return
        if declined is not None:
            if run is not None:
                run.status = "skipped"
                run.error = declined
                # `B1054`. Led by `DRY_RUN_MARK`, so a declined dry run is a
                # dry run to every reader, and never a task's last run.
                run.result = f"{DRY_RUN_MARK}not planned: {declined}"
                run.finished_at = _utcnow()
                db.commit()
            logger.info("Dry run of task %s (run %s) not planned: %s",
                        getattr(task, "name", None) or run_id, run_id, declined)
            return
        # `Law 15`. The first line is the one a person reads on a card that
        # says `skipped`, and it has to answer "did my thing happen" before it
        # answers anything else — `dry_run_lines` puts the headline first.
        lines = dry_run_lines(task)
        for line in lines:
            self._record_run_step(run_id, kind="dry-run", detail=line)
        if run is None:
            return
        run.status = "skipped"
        run.result = "\n".join(lines)
        run.finished_at = _utcnow()
        self._attach_run_steps(run_id, run)
        db.commit()
        logger.info("Dry run of task '%s' (run %s): planned %d line(s), executed nothing",
                    task.name, run_id, len(lines) - 1)

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

    def _mark_run_aborted(self, task_id: str, run_id: str | None = None,
                          message: str = STOPPED_BY_USER) -> bool:
        """Mark an active run as aborted. Used by stop/cancel paths.

        `B1047`. `message` is why, and it replaces `result` too: an active
        run's `result` is only ever a placeholder ("Queued — waiting for
        Pantheon to be idle…", "Starting…") or a progress line — a run's output
        is written when it finishes — so keeping it left an aborted run saying
        it was still waiting.
        """
        try:
            from core.database import SessionLocal, TaskRun, TASK_RUN_IN_FLIGHT_STATUSES
            db = SessionLocal()
            try:
                q = db.query(TaskRun)
                if run_id:
                    q = q.filter(TaskRun.id == run_id)
                else:
                    # `P22-11`. IN FLIGHT, not only active: Stop ends a run
                    # that is parked, which no coroutine holds to cancel.
                    q = q.filter(
                        TaskRun.task_id == task_id,
                        TaskRun.status.in_(TASK_RUN_IN_FLIGHT_STATUSES),
                    ).order_by(TaskRun.started_at.desc())
                run = q.first()
                if not run or run.status not in TASK_RUN_IN_FLIGHT_STATUSES:
                    return False
                if run.status == "waiting":
                    # Its waiting steps end with the same words, and their
                    # cards are retired, so nothing it asked can be answered.
                    from core.database import ScheduledTask
                    from src import workflow_runs as _wr
                    owner_task = db.query(ScheduledTask).filter(
                        ScheduledTask.id == run.task_id).first()
                    self._retire_cards(db, run.id, owner_task)
                    _wr.end_waiting_records(db, run.id, status="aborted", error=message)
                run.status = "aborted"
                run.error = message
                run.result = message
                run.finished_at = _utcnow()
                db.commit()
                return True
            finally:
                db.close()
        except Exception:
            logger.debug("Task abort marker failed for %s", task_id, exc_info=True)
            return False

    def _task_type_of(self, task_id: str) -> str | None:
        """`B1138`. A task's `task_type`, read fresh (the gate holds no row)."""
        try:
            from core.database import SessionLocal, ScheduledTask
            db = SessionLocal()
            try:
                row = db.query(ScheduledTask.task_type).filter(ScheduledTask.id == task_id).first()
                return (row[0] or "llm") if row else None
            finally:
                db.close()
        except Exception:
            logger.debug("Could not read the type of task %s", task_id, exc_info=True)
            return None

    def _stopped_as(self, run_id: str) -> str | None:
        """Why this run was stopped, if whoever stopped it already said.

        `B1047`. `stop_task` and the foreground gate write the row (with
        `_mark_run_aborted`) and then cancel the run; the cancel lands in
        `_execute_task_locked`, which used to overwrite their words with its
        own guess — "Stopped by user" unless its own monitor had fired. Read in
        a fresh session, because the run's own session may hold the row as it
        loaded it, before the stop was committed.
        """
        try:
            from core.database import SessionLocal, TaskRun
            db = SessionLocal()
            try:
                run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if run is not None and run.status == "aborted" and run.error:
                    return run.error
            finally:
                db.close()
        except Exception:
            logger.debug("Could not read how run %s was stopped", run_id, exc_info=True)
        return None

    def add_notification(self, task_name: str, status: str, task_id: str = None, owner: str = None, body: str = None,
                         review: dict = None):
        """Store a notification about a completed task run. Tagged with the
        task's owner so `pop_notifications` can return only that user's
        notifications and prevent cross-tenant drain. `body` is the result
        text — populated when output_target='notification' so the client can
        show a rich browser Notification, not just a toast.

        `review` (`B1006`) is something the person is asked to answer — the
        scheduled Documents Tidy's list — which the client offers to open
        (`static/js/documentPlanNotice.js`) instead of only toasting."""
        note = {
            "task_name": task_name,
            "status": status,
            "task_id": task_id,
            "owner": owner,
            "body": (body[:500] + "…") if body and len(body) > 500 else body,
            "timestamp": _utcnow().isoformat() + "Z",
        }
        if review:
            note["review"] = review
        self._pending_notifications.append(note)
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
                (getattr(task, "task_type", None) or "llm") not in NOTIFY_ON_SUCCESS_TASK_TYPES:
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

    def _sweep_runs_left_by_a_restart(self) -> None:
        """On startup, mark every run (and workflow step) a previous process
        left in flight as aborted. Moved out of `start` unchanged, so it can be
        called and tested on its own (`P22-07` added the step records)."""
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
                # `P22-11`: ACTIVE, never PARKED — a `waiting` run is held by
                # no process, so a restart leaves it waiting, and it goes on
                # from its records (a card it held lapsed with the old
                # process; the sweeper says so on its failure port).
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
                    # The steps of a run it aborts that were waiting — parked
                    # on a card while another branch ran — wait for nothing now.
                    from src import workflow_runs as _wr
                    for r in stale:
                        _wr.end_waiting_records(
                            db, r.id, status="aborted",
                            error="Server restarted while this run was going")
                    logger.info(f"Cleared {len(stale)} stale task_runs from previous run")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Could not clear stale task_runs on startup: {e}")
        # `P22-07`. The same event for a workflow's step: the run above is
        # aborted, and the step it was on would read "running" in the Runs view
        # for ever. A step record is only ever `running` while its walker is.
        try:
            from core.database import SessionLocal, TaskRunNode
            db = SessionLocal()
            try:
                stuck = db.query(TaskRunNode).filter(TaskRunNode.status == "running").all()
                if stuck:
                    now = _utcnow()
                    for rec in stuck:
                        rec.status = "aborted"
                        rec.error = "Server restarted while this step was running"
                        rec.finished_at = now
                    db.commit()
                    logger.info("Cleared %d workflow step record(s) left running", len(stuck))
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Could not clear stale workflow step records on startup: {e}")

    async def start(self):
        # Re-read the concurrency cap here, not just in __init__: the scheduler
        # is constructed at import/wiring time, so a settings change made after
        # boot would otherwise need a full process restart to take effect.
        # Nothing holds the semaphore yet at this point. `_check_due_tasks`
        # re-reads it every tick as well (`P6-08`); this call is what makes the
        # start-up log line report the cap the first dispatch will actually use.
        self._refresh_concurrency_cap()
        self._sweep_runs_left_by_a_restart()

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
                # `P22-11`. Wake for a parked step's time too, so a Wait until
                # 08:00 goes on at 08:00 rather than up to a minute later.
                due = self._next_resume_at()
                if due is not None:
                    delta = (due - _utcnow()).total_seconds()
                    sleep_for = max(1.0, min(sleep_for, delta))
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
                    to_dispatch.append((
                        task.id,
                        dispatch_hold(task, now=now,
                                      tz_name=_resolve_task_timezone(db, task)),
                    ))
                if foreground_active and due:
                    db.commit()
            for task_id, hold in to_dispatch:
                asyncio.create_task(self._dispatch_after(task_id, hold))
        finally:
            db.close()
        # `P22-11`. Parked workflow runs whose wait is over go on.
        try:
            await self._resume_due_waits()
        except Exception:
            logger.warning("The parked-run sweep failed", exc_info=True)

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

    def _new_queued_run(self, task_id: str) -> str:
        """Write a `queued` run row and answer its id.

        Created BEFORE any wait, so the UI can show that a run is in line behind
        another one or behind the person using Pantheon. `B1060` writes a second
        one when a run the foreground gate stopped goes back in the queue.
        """
        from core.database import SessionLocal, TaskRun
        run_id = str(uuid.uuid4())
        _q_db = SessionLocal()
        try:
            _q_db.add(TaskRun(
                id=run_id,
                task_id=task_id,
                started_at=_utcnow(),
                status="queued",
                result="Queued — waiting for a free slot…",
            ))
            _q_db.commit()
        except Exception:
            logger.exception(f"Failed to create queued run row for task {task_id}")
        finally:
            _q_db.close()
        return run_id

    async def _wait_until_idle(self, task_id: str, run_id: str) -> float:
        """`B1060`. A background run's wait for Pantheon to be idle, while it is
        still `queued` and holds nothing. Answers how long it waited.

        It was inside `_execute_task_locked`, i.e. INSIDE the model slot, so a
        background run waiting for a person to stop using Pantheon held the one
        slot every other run needed — and the foreground gate stopped waiting
        runs for that reason. Stopped, a webhook's or an event's run was gone
        with its payload (`_defer_immediately_due_task` only re-queues a task
        whose `next_run` has passed, which those never have) while its row said
        "Paused". It now waits here, holding nothing, and the gate leaves it be.
        """
        from core.database import SessionLocal, TaskRun
        from src.interactive_gate import wait_for_interactive_quiet

        db = SessionLocal()
        try:
            waiting = db.query(TaskRun).filter(TaskRun.id == run_id).first()
            if waiting is not None and waiting.status == "queued":
                waiting.result = WAITING_FOR_IDLE
                db.commit()
        except Exception:
            logger.debug("Could not mark run %s waiting for idle", run_id, exc_info=True)
        finally:
            db.close()
        started = time.monotonic()
        waited = await wait_for_interactive_quiet(f"scheduled task {task_id}")
        return (time.monotonic() - started) if waited else 0.0

    async def _take_model_slot(self, task_id: str, run_id: str, *,
                               idle_first: bool):
        """Take one permit of the model slot. Answers `(semaphore, seconds
        waited for idle)` — release THAT semaphore, because `_sync_run_slot`
        may replace the attribute while the permit is held.

        `B1060`. With `idle_first` — a background run under the foreground gate
        — Pantheon must be idle before the slot is taken AND still idle once it
        is held: a person who arrived while this run waited for the slot gets
        the slot back at once, and this run waits for idle again, holding
        nothing.
        """
        from src.interactive_gate import has_foreground_activity

        waited = 0.0
        while True:
            if idle_first:
                waited += await self._wait_until_idle(task_id, run_id)
            sem = self._run_semaphore
            await sem.acquire()
            if not idle_first or not has_foreground_activity():
                return sem, waited
            sem.release()

    async def _execute_task(self, task_id: str, *, bypass_model_slot: bool = False,
                            release_executing: bool = True, trigger: dict | None = None,
                            dry: bool = False,
                            started_by: str = STARTED_BY_BACKGROUND,
                            register_handle: bool = True,
                            resume_run_id: str | None = None, answer=None):
        # `P22-11`. `resume_run_id` is a parked (`waiting`) workflow run going
        # on: no new row — the run is the one that parked — and every gate is
        # asked again (paused, admin, B1060's idle wait for background work,
        # the model slot, the time limit, which applies per segment).
        # `answer` (`P22-17`) is what a person said to its question.
        #
        # Create the run record with status="queued" BEFORE waiting on the
        # semaphore so the UI can show that a manually-triggered task is in
        # line behind another. Once we acquire the slot, flip to "running"
        # and hand off to _execute_task_locked.
        #
        # `P22-05`. `register_handle=False` keeps `_task_handles[task_id]` off
        # this asyncio task: a workflow's *Run task* step awaits its target from
        # inside the WORKFLOW's task, and a handle pointing there would let a
        # later `stop_task(target)` cancel the whole workflow.
        current = asyncio.current_task()

        def _hold_handle():
            if current and register_handle:
                self._task_handles[task_id] = current
                self._started_by_map()[task_id] = started_by

        _hold_handle()
        run_id = resume_run_id or self._new_queued_run(task_id)
        resume = resume_run_id is not None
        # `B1060`. Background work waits for Pantheon to be idle BEFORE it takes
        # the model slot. A person's run keeps `B1047`'s chat wait, inside
        # `_execute_task_locked`; a dry run and a forced run wait for nothing.
        gated = not (bypass_model_slot or dry)
        idle_first = gated and started_by != STARTED_BY_PERSON
        takeovers = 0

        try:
            while True:
                waited = 0.0
                # `P8-33`. A dry run makes no model call and touches nothing, so
                # it neither waits for the model slot nor waits for Pantheon to
                # go idle. Queueing a plan behind a real run's semaphore would
                # make the one button that is safe to press the slowest one.
                if dry or bypass_model_slot or not self._task_needs_model_slot(task_id):
                    if idle_first:
                        waited = await self._wait_until_idle(task_id, run_id)
                    outcome = await self._execute_task_locked(
                        task_id,
                        run_id,
                        release_executing=False,
                        gate_foreground=gated,
                        trigger=trigger,
                        dry=dry,
                        started_by=started_by,
                        waited_for_idle=waited,
                        may_requeue=takeovers + 1 < FOREGROUND_STOPS_LIMIT,
                        resume=resume, answer=answer, awaited=not register_handle,
                    )
                else:
                    sem, waited = await self._take_model_slot(
                        task_id, run_id, idle_first=idle_first)
                    try:
                        outcome = await self._execute_task_locked(
                            task_id,
                            run_id,
                            release_executing=False,
                            gate_foreground=True,
                            trigger=trigger,
                            started_by=started_by,
                            waited_for_idle=waited,
                            may_requeue=takeovers + 1 < FOREGROUND_STOPS_LIMIT,
                            resume=resume, answer=answer, awaited=not register_handle,
                        )
                    finally:
                        sem.release()
                if outcome is not REQUEUED:
                    # `P22-04`. The run's id, so a caller that awaited this — a
                    # dry run, below in `run_task_now` — can read back what it
                    # wrote. Every spawned caller ignores it, as it ignored `None`.
                    return run_id
                # `B1060`. The foreground gate stopped this run while it ran,
                # and its row says it will run again. It goes back in the queue
                # with the SAME trigger — the webhook body, the event, the step
                # before it — still holding its `_executing` claim, so no other
                # path can start the task in between.
                #
                # The cancel that stopped it was answered in
                # `_execute_task_locked`, so asyncio is told so — once, for the
                # one cancel that was delivered. Not down to zero: a Stop pressed
                # since is a cancel still pending, and on 3.13+ `uncancel()`
                # reaching zero drops a pending cancel. (Measured on 3.11.15
                # without it: a later `asyncio.timeout` in this task still timed
                # out, so this is correctness for `TaskGroup`/`timeout`
                # bookkeeping, not a behaviour that was seen to break.)
                if current is not None and current.cancelling():
                    current.uncancel()
                if release_executing and task_id not in self._executing:
                    # A Stop pressed between the two attempts. `stop_task` lets
                    # the claim go before anything else, and its cancel can be
                    # absorbed while the stopped attempt tears down its monitor
                    # (`await foreground_monitor` swallows a cancel), so the
                    # claim is the one sure sign. The person's stop is the last
                    # word on the row that promised another attempt.
                    self._restate_stopped_by_user(run_id)
                    return run_id
                takeovers += 1
                _hold_handle()
                run_id = self._new_queued_run(task_id)
                resume, answer = False, None
        except asyncio.CancelledError:
            # If cancellation happens while queued behind the semaphore,
            # _execute_task_locked never runs and cannot update the Activity row.
            # (`B1047`: a stop that already wrote why is kept — this only
            # writes a row nobody has ended.)
            self._mark_run_aborted(task_id, run_id)
            self._defer_immediately_due_task(task_id, delay=timedelta(minutes=15))
            raise
        finally:
            # A run stopped while it waited never reached `_execute_task_locked`,
            # whose `finally` drops the slot; this one does, for that case.
            self._clear_run_state(run_id)
            handle = self._task_handles.get(task_id)
            if handle is current:
                self._task_handles.pop(task_id, None)
                self._started_by_map().pop(task_id, None)
            if release_executing:
                async with self._executing_lock:
                    self._executing.discard(task_id)

    def _restate_stopped_by_user(self, run_id: str) -> None:
        """`B1060`. A run the gate stopped said it would run again; the person
        stopped it before it did. Its `result` says so; its `error` keeps why
        the attempt itself ended."""
        try:
            from core.database import SessionLocal, TaskRun
            db = SessionLocal()
            try:
                run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if run is not None and run.status == "aborted":
                    run.result = STOPPED_BY_USER
                    db.commit()
            finally:
                db.close()
        except Exception:
            logger.debug("Could not restate run %s as stopped", run_id, exc_info=True)

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
        dry: bool = False,
        started_by: str = STARTED_BY_BACKGROUND,
        waited_for_idle: float = 0.0,
        may_requeue: bool = True,
        resume: bool = False,
        answer=None,
        awaited: bool = False,
    ):
        """Run one queued run to its end. Answers `REQUEUED` when the
        foreground gate stopped it while it ran and it goes back in the queue
        (`B1060`), and `None` otherwise.

        `waited_for_idle` is how long `_execute_task` held it in the queue for
        Pantheon to be idle (`B1060`), said in its step log after the cause.
        `may_requeue` is whether a stop by the gate puts it back
        (`FOREGROUND_STOPS_LIMIT`). `awaited` (`B1102`) is a run another run
        awaits — a workflow's *Run task* step (`register_handle=False`) — which
        cannot park on a card of its own: that step reads a finished run.
        """
        from core.database import SessionLocal, ScheduledTask, TaskRun

        db = SessionLocal()
        try:
            task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            if dry:
                # `P8-33`. The dry run ends here, and this `return` is the whole
                # guarantee. Every executor — the eighteen actions, the agent
                # loop, the research pipeline — is below this line, and so is
                # every delivery, notification and chain advance. There is no
                # `dry_run=True` travelling down into anything, because the
                # eighteen actions all take `**kwargs` and would swallow it
                # (measured: 18 of 18), which would make the button labelled
                # "test" the button that sends the email.
                #
                # `B1036`. Above the two early returns now, not below them. A
                # paused task returned at the first ("no longer active") with a
                # `skipped` run and a NOTIFICATION, and planned nothing — so a
                # switched-off draft could not be dry-run at all; an admin-only
                # task of a non-admin owner was refused at the second through
                # `record_admin_refusal`, which PAUSES the task and moves its
                # `last_run`. Both broke the one promise a dry run makes. The
                # admin rule still applies — `_record_dry_run` declines such a
                # task with the same sentence, the only answer that is not a
                # privilege oracle — it just changes nothing and tells nobody.
                self._record_dry_run(db, task, run_id)
                return
            if resume:
                # `P22-11`. A parked run going on. Stopped meanwhile (Stop ends
                # a waiting run) — nothing to resume. Switched off meanwhile —
                # it ends `aborted`, says so, and its cards are retired.
                parked = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if parked is None or parked.status != "waiting":
                    return
                if not task or task.status != "active":
                    self._end_parked_run(db, task, parked, status="aborted",
                                         sentence=SWITCHED_OFF_WHILE_WAITING)
                    return
            if not task or task.status != "active":
                # Task was paused/deleted while queued — record that outcome
                # so the run row doesn't sit as "queued" forever.
                stale = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if stale and stale.status == "queued":
                    stale.status = "skipped"
                    stale.finished_at = _utcnow()
                    stale.error = f"Task no longer active (status={task.status if task else 'deleted'})"
                    # `B1036`. The reason in `result` too: it was left at the
                    # "Queued — waiting for a free slot…" it was created with,
                    # which History shows ahead of `error`.
                    stale.result = stale.error
                    db.commit()
                    # `B112`. The task is paused or gone, so this run is the last
                    # thing that will happen on it and nothing else will say so.
                    # A deleted task has no name and no owner to notify.
                    self._notify_run_outcome(task, "skipped", body=stale.error,
                                             task_id=task_id)
                return

            # `B674`, written once (`workflow_runs.run_in_flight`): one workflow
            # runs once at a time. A new trigger while a run of it is still
            # going — parked on a Wait or a person's yes, or running — is a
            # `skipped` run that says why, never a second run beside it.
            if not resume and (task.task_type or "llm") == "workflow":
                from src import workflow_runs as _wr
                _other = _wr.run_in_flight(db, task_id, exclude=run_id)
                if _other is not None and _other.status != "queued":
                    self._skip_for_in_flight(db, task, run_id, _other)
                    return
            # `B1102`. A plain Prompt task's run parked on a yes holds its task
            # as a parked workflow run does: a trigger while it waits is a
            # `skipped` run that says which run waits and for what — never a
            # second run asking a second question. A RUNNING plain run keeps
            # the `_executing` claim and its deliberate forced run (`Law 1`).
            elif not resume and (task.task_type or "llm") == "llm":
                from src import workflow_runs as _wr
                _parked = _wr.parked_run(db, task_id, exclude=run_id)
                if _parked is not None:
                    self._skip_for_in_flight(db, task, run_id, _parked)
                    return

            # `P22-05`. One question for a task and for a workflow: the task's
            # own action, or any step of its document (`admin_only_action_of`)
            # — asked before any step runs, so no earlier step runs first.
            _admin_action = admin_only_action_of(db, task)
            if (
                _admin_action
                and not owner_has_admin_task_privileges(task.owner)
            ):
                # `skipped`, not `error` — the action never ran, so by the
                # vocabulary in core/database.py this is not a failure. Recorded
                # through the shared helper because the webhook path in
                # routes/task/task_routes.py enforces the same rule and used to
                # record nothing at all.
                _refusal = record_admin_refusal(db, task, run_id=run_id,
                                                action=_admin_action)
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

            # `B1047`. Who started this run decides what it waits for, here and
            # in `_run_agent_loop` (the second wait, for a model call), so both
            # read it off the run's slot. Background work waits for Pantheon to
            # be idle and is stopped when somebody arrives — unchanged. A run a
            # person started waits only while a chat reply is being written,
            # and only if it needs the model; forced ("Start now") waits for
            # nothing. Measured before this: Run now waited for the page it was
            # pressed on to close (the tab's heartbeat alone keeps the idle gate
            # shut), and the page's own polls stopped it within seconds.
            person = started_by == STARTED_BY_PERSON
            slot = self._state_for(run_id)
            slot["started_by"] = started_by
            slot["waits_for"] = ("chat" if gate_foreground else None) if person else "idle"
            if gate_foreground and person:
                from src.interactive_gate import chat_in_progress, wait_for_chat_quiet
                if chat_in_progress() and self._task_needs_model_slot(task_id):
                    waiting = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                    if waiting and waiting.status == "queued":
                        waiting.result = WAITING_FOR_CHAT
                        db.commit()
                    await wait_for_chat_quiet(f"task {task.name}")
            # `B1060`. A background run's wait for Pantheon to be idle was here,
            # inside the model slot. It is `_execute_task`'s now, before the
            # slot is taken (`_wait_until_idle`), so a waiting run holds nothing
            # and the foreground gate has no reason to stop it.

            # Flip the run from queued → running. Reset started_at to the
            # actual execution start so queue wait time is visible from
            # created_at vs started_at if we ever surface that.
            run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
            if run and resume:
                # `P22-11`. The same run, going on: `waiting → running`. It keeps
                # its start time and its step log so far, and says why it is
                # going on.
                run.status = "running"
                run.result = "Resumed…"
                run.finished_at = None
                db.commit()
                try:
                    kept = json.loads(run.steps) if run.steps else []
                except (TypeError, ValueError):
                    kept = []
                slot["steps"] = list(kept) if isinstance(kept, list) else []
                slot["resuming"] = True
                slot["answer"] = answer
                # `B1110`. The answer is said here only when it lets the step
                # run again (Allow): a denial, a lapse or a withdrawn question
                # ends the step, and the step's own end line in this log says
                # it — said here too, and once more by `_apply_resume`, a
                # denied step's run log read the same sentence three times.
                self._record_run_step(run_id, kind="progress", detail=(
                    f"Resumed: {answer.sentence}"
                    if answer is not None and answer.sentence and answer.decision == ANSWER_ALLOW
                    else "Resumed"))
            elif run:
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
            if gate_foreground and not person:
                # `B1060`. From here until it ends, this is a RUNNING background
                # run, the one kind the foreground gate stops.
                self._gate_stoppable_map()[task_id] = run_id

            task_type = task.task_type or "llm"

            from src.builtin_actions import TaskDeferred, TaskNoop, TaskWaiting

            # `P8-23`. What fired this run, recorded before anything it does —
            # so the first line of the step log is the cause and the rest is the
            # effect. The run's slot carries the envelope for the executors.
            if trigger:
                self._state_for(run_id)["trigger"] = trigger
                self._record_run_step(
                    run_id, kind="trigger",
                    detail=_trigger_summary(trigger),
                )
            # `B1060`. A run the queue held for Pantheon to be idle says so, after
            # its cause: "its row says it waited".
            if waited_for_idle > 0:
                self._record_run_step(
                    run_id, kind="progress",
                    detail=(f"Waited {_waited_words(waited_for_idle)} for Pantheon "
                            f"to be idle, then started"),
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
            # `B1047`. Background work only: a run a person started is not
            # stopped because they went on using Pantheon.
            if gate_foreground and not person:
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
                            # `B1138`. Said in the run's slot too, where the
                            # walker reads it (`_is_takeover`): without it a
                            # workflow's interrupted step was ended `aborted`
                            # while the cancel branch parked the run `waiting`
                            # — a run waiting on no step (measured).
                            self._state_for(run_id)["takeover"] = True
                            logger.info("Task '%s' interrupted because Pantheon became active", task.name)
                            if current_task:
                                current_task.cancel()
                            return

                foreground_monitor = asyncio.create_task(_cancel_if_foreground_active())
            try:
                # `P8-32`. This task's own wall-clock ceiling, or no ceiling —
                # which is what every run has had until now. `max_steps` bounds
                # agent-loop ROUNDS on an llm task and nothing bounded an
                # action at all, so a hung action held a scheduler slot until
                # the process restarted. `_bounded` is applied at this one
                # boundary rather than inside three executors (`Law 14`).
                budget = task_timeout_seconds(task)

                async def _bounded(coro, _budget=budget):
                    if not _budget:
                        return await coro
                    return await asyncio.wait_for(coro, timeout=_budget)

                if task_type == "action":
                    node = await _bounded(self._execute_action(task, run_id=run_id))
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
                    # `P8-29`. Keep what the node RETURNED, not only the
                    # sentence about it, so a successor can read a field out of
                    # it instead of parsing English. `P8-24` widened the
                    # contract for exactly this and said so in its own comment;
                    # this is the first consumer.
                    self._state_for(run_id)["payload"] = node.payload
                elif task_type == "research":
                    result = await _bounded(
                        self._execute_research_task(task, db, run_id=run_id))
                    run.status = "success"
                    run.result = result
                elif task_type == "workflow":
                    # `P22-05`. The walker, inside every gate above — paused,
                    # admin, both foreground waits, this task's time limit, the
                    # cancel monitor — and answering in the action branch's
                    # vocabulary, so a run that ends `skipped` goes through the
                    # one `TaskNoop` branch below, and a failure backs off and
                    # takes this task's own failure edge like any task's.
                    node = await _bounded(self._run_workflow(task, db, run_id))
                    signal = node.as_signal()
                    if signal is not None:
                        raise signal
                    result = node.text
                    run.status = "success" if node.ok else "error"
                    run.result = result
                    if node.failed:
                        # `P22-11`. The step (and item) that failed, by name.
                        run.error = (self._state_for(run_id).get("run_error")
                                     or result or "")[:2000]
                    self._state_for(run_id)["payload"] = node.payload
                else:
                    # LLM task — use agent loop for tool access. `B1102`: a
                    # card parks the run (`TaskWaiting`, handled below as a
                    # workflow's is), and a resumed run is answered here.
                    status, result = await _bounded(self._run_plain_prompt(
                        task, db, run_id, resume=resume, answer=answer,
                        may_wait=not awaited))
                    run.status = status
                    run.result = result
                    if status == "error":
                        run.error = result
                # Record which model actually ran (resolved inside the executor).
                if self.run_model(run_id):
                    run.model = self.run_model(run_id)
                self._attach_run_steps(run_id, run)
                # `P22-05`. A workflow delivers per step, each through its own
                # output setting; delivering the run's result again here would
                # send the last step's twice.
                if run.status == "success" and task_type != "workflow":
                    await self._deliver_task_result(task, result, db, model=self.run_model(run_id))
            except asyncio.TimeoutError:
                # `P8-32`. `error`, not `aborted`. `core/database.py`'s own
                # definitions put a user stop, a foreground takeover and a
                # restart under `aborted` and call them "not a failure" —
                # because folding infrastructure events into the error rate
                # corrupts it. A ceiling the OWNER set on THIS task is the
                # opposite: exceeding it is the task failing to do its job on
                # the terms the owner gave it, and it should count, back off
                # and take the failure edge like any other failure. Caught here
                # rather than left to `except Exception` so it cannot be read
                # as "Stopped by user" the way the `CancelledError` branch
                # below would report it.
                budget = task_timeout_seconds(task)
                if not budget:
                    # Not ours. An executor can raise this from a `wait_for` of
                    # its own, and claiming it as "this task's timeout" would
                    # name a limit the task does not have. Let the generic error
                    # path report it as what it is.
                    raise
                msg = (f"Timed out after {_human_gap(budget)} — this task's own "
                       f"timeout. Nothing after that point ran.")
                logger.warning("Task '%s' exceeded its %ss timeout", task.name, budget)
                if task_type == "workflow":
                    # `P22-11`. The time limit is per segment; a run that ran
                    # out of it waits for nothing any more.
                    self._retire_cards(db, run_id, task)
                    from src import workflow_runs as _wr
                    _wr.end_waiting_records(db, run_id, status="error", error=msg)
                run.status = "error"
                run.result = msg
                run.error = msg
                self._record_run_step(run_id, kind="progress", detail=msg)
                self._attach_run_steps(run_id, run)
                result = msg
            except TaskWaiting as parked:
                # `P22-11`. The run PARKS: `waiting`, with what it waits for.
                # Its step records are its state, so nothing here holds it — the
                # coroutine exits, which lets go of the model slot, the
                # foreground monitor, the time limit and the claim. No outcome
                # notification (the run has not ended; a question goes out as
                # its own notification) and no chain advance. A scheduled task
                # gets its next time as normal; an event or webhook task none —
                # a trigger while it waits is a `skipped` run (`B674`).
                logger.info("Task '%s' parked: %s", task.name, parked.sentence)
                run.status = "waiting"
                run.result = parked.sentence
                run.error = None
                run.finished_at = None
                if self.run_model(run_id):
                    run.model = self.run_model(run_id)
                self._attach_run_steps(run_id, run)
                task.last_run = _utcnow()
                task.next_run = self._next_run_after(db, task)
                db.commit()
                return
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
                # `B1047`. Whoever stopped the run wrote why before cancelling
                # it (`stop_task`, the foreground gate); keep their words. This
                # branch's own guess is for the monitor above, which writes
                # nothing first, and for a cancel nobody explained.
                said = self._stopped_as(run_id)
                # `B1138`. The gate leaves a workflow run's row alone and says
                # so in the run's slot instead (`_is_takeover` reads both).
                msg = said or (
                    FOREGROUND_TAKEOVER
                    if foreground_cancel.get("hit") or self._is_takeover(run_id)
                    else STOPPED_BY_USER
                )
                takeover = msg == FOREGROUND_TAKEOVER
                logger.info("Task '%s' %s", task.name, msg)
                # `B1060`. A run the foreground gate stopped goes back in the
                # queue with its trigger, unless the task was switched off or
                # deleted meanwhile, or this trigger has already been stopped
                # `FOREGROUND_STOPS_LIMIT` times — and the row says which. It
                # was `next_run = now + 15 min` for every trigger type, so an
                # event's or a webhook's task came back a quarter of an hour
                # later as a plain run with no payload, and a chained step came
                # back as a run nothing had chained.
                requeue = False
                said = msg
                if takeover and task_type == "workflow":
                    # `P22-11`. A workflow run is PARKED, not re-queued: the
                    # step the takeover stopped is `waiting {kind: idle}` (the
                    # walker wrote it), the finished steps are kept, and only
                    # that step runs again once Pantheon is idle — so a POST
                    # that was already sent is not sent twice. One durable
                    # mechanism; `B1060`'s re-queue stays for every other task.
                    try:
                        db.refresh(task)
                        still_on = task.status == "active"
                    except Exception:
                        still_on = False
                    run_obj = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                    if still_on and run_obj is not None:
                        run_obj.status = "waiting"
                        run_obj.result = TAKEOVER_PARKED
                        run_obj.error = None
                        run_obj.finished_at = None
                        self._attach_run_steps(run_id, run_obj)
                        task.last_run = _utcnow()
                        db.commit()
                        logger.info("Workflow '%s' parked for Pantheon to be idle", task.name)
                        return
                if task_type == "workflow":
                    # Stopped, timed out or switched off: what its steps waited
                    # for will not come.
                    self._retire_cards(db, run_id, task)
                    from src import workflow_runs as _wr
                    _wr.end_waiting_records(db, run_id, status="aborted", error=msg)
                if takeover:
                    try:
                        db.refresh(task)     # switched off while it ran?
                        why_not = (None if task.status == "active"
                                   else not_active_words(task))
                    except Exception:
                        why_not = "the task was deleted"
                    if why_not is None and not may_requeue:
                        why_not = (f"it was stopped {FOREGROUND_STOPS_LIMIT} times "
                                   f"in a row because Pantheon became active")
                    requeue = why_not is None
                    said = (f"{msg}. It will run again, with what started it, once "
                            f"Pantheon is idle." if requeue
                            else f"{msg}. It will not be retried: {why_not}.")
                run_obj = db.query(TaskRun).filter(TaskRun.id == run_id).first()
                if run_obj:
                    if run_obj.status in ("queued", "running") or takeover:
                        # Nothing was produced yet: `result` holds "Starting…"
                        # or a progress line, which would read as still going.
                        # (`B1060`: a takeover's row says what happens next,
                        # over the gate's own placeholder.)
                        run_obj.result = said
                    else:
                        run_obj.result = run_obj.result or msg
                    run_obj.status = "aborted"
                    run_obj.error = msg
                    run_obj.finished_at = _utcnow()
                    # An interrupted run is one of the two people most want the
                    # steps for; the other is the one that errored, below.
                    self._attach_run_steps(run_id, run_obj)
                task.last_run = _utcnow()
                if requeue:
                    # `_execute_task` writes the next queued row and holds the
                    # task's claim throughout; `next_run` is left where it was,
                    # because the run it describes has not happened yet.
                    db.commit()
                    self._notify_run_outcome(task, "aborted", body=said, task_id=task_id)
                    return REQUEUED
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
                # a foreground takeover re-queues this one for when Pantheon is
                # idle (`B1060`). The call is here anyway so the silence is the
                # policy's answer and not this branch forgetting the notify
                # block, which is how it read before.
                self._notify_run_outcome(task, "aborted", body=said, task_id=task_id)
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
            if run.status == "error":
                # `P8-32`. **A run that RETURNED a failure got no backoff at
                # all.** `P15-08` put the ladder in the `except Exception`
                # handler below, so it covered a task that RAISED and not one
                # whose action returned `(text, False)` — which is every
                # built-in email action, which is the exact case `P15-08` was
                # written for: the actions that get an owner soft-banned are
                # the ones that report failure by returning it. `P8-28` fixed
                # the same asymmetry for the failure EDGE and said so in those
                # words; this is the other half of it, and `failure_next_run`
                # is now the one place either shape is answered (`Law 14`).
                plan = failure_next_run(db, task, run_id=run_id)
                task.next_run = plan.next_run
                if plan.note:
                    logger.warning("Task %s: %s", task_id, plan.note)
                    self._record_run_step(run_id, kind="progress", detail=plan.note)
                    self._attach_run_steps(run_id, run)
                if (task.next_run is None and task.schedule == "once"
                        and (task.trigger_type or "schedule") == "schedule"):
                    task.status = "completed"
            elif (task.trigger_type or "schedule") == "schedule":
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
                    and (_t_for_notify.task_type or "llm") in NOTIFY_ON_SUCCESS_TASK_TYPES
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
                    if run_obj.status == "running":
                        # `B1055`. A run that raised before it produced anything
                        # still held "Starting…" (or its last progress line) in
                        # `result` — which History shows ahead of `error`, and
                        # which `_handoff_from` hands to the failure branch, so
                        # "tell me the backup failed" was told `result=Starting…`.
                        # The reason is the result. A run that RETURNED its
                        # output and then failed delivering it (`success` here)
                        # keeps that output.
                        run_obj.result = err_text[:2000]
                    run_obj.status = "error"
                    run_obj.error = err_text[:2000]
                    run_obj.finished_at = _utcnow()
                    self._attach_run_steps(run_id, run_obj)
                    # `P22-11`. A workflow run that failed this way waits for
                    # nothing any more: its waiting steps end with it, and
                    # their cards are retired.
                    _wf_task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
                    if _wf_task is not None and (_wf_task.task_type or "llm") == "workflow":
                        from src import workflow_runs as _wr
                        self._retire_cards(db, run_id, _wf_task)
                        _wr.end_waiting_records(db, run_id, status="error", error=err_text)
                # Advance next_run even on failure so a broken task doesn't
                # busy-loop the scheduler every tick with a stale past date.
                task_obj = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
                if task_obj and (task_obj.trigger_type or "schedule") == "schedule":
                    task_obj.last_run = _utcnow()
                    try:
                        # `P15-08`. Advancing to the next slot is what this line
                        # did and all it did: a task failing against a
                        # rate-limiting provider retried at full cadence, for
                        # ever, and every retry is another request to the thing
                        # that is already refusing us. The schedule is kept —
                        # this only ever pushes the next run LATER — and the
                        # first success clears the ladder, because the count is
                        # read from the run history rather than carried.
                        #
                        # `P8-32` moved the arithmetic into `failure_next_run`
                        # and changed nothing about it for a task with no retry
                        # budget. It is one function now because the ordinary
                        # path needed the same answer and did not have it: a
                        # built-in action that RETURNED a failure got no backoff
                        # at all, which is the half of `P15-08` that was never
                        # wired.
                        plan = failure_next_run(db, task_obj, run_id=run_id)
                        task_obj.next_run = plan.next_run
                        if plan.note:
                            logger.warning("Task %s: %s", task_id, plan.note)
                            self._record_run_step(run_id, kind="progress",
                                                  detail=plan.note)
                            self._attach_run_steps(run_id, run_obj)
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
            stoppable = self._gate_stoppable_map()
            if stoppable.get(task_id) == run_id:
                stoppable.pop(task_id, None)
            handle = self._task_handles.get(task_id)
            if handle is asyncio.current_task():
                self._task_handles.pop(task_id, None)
                self._started_by_map().pop(task_id, None)
            if release_executing:
                async with self._executing_lock:
                    self._executing.discard(task_id)



    # ── `P22-11` / `B674` · a run that waits ──────────────────────────────────

    def _next_run_after(self, db, task):
        """A scheduled task's next time, as a finished run would set it; `None`
        for an event or webhook task (it runs when it is triggered)."""
        if (task.trigger_type or "schedule") != "schedule":
            return None
        return compute_next_run(
            task.schedule, task.scheduled_time, task.scheduled_day, task.scheduled_date,
            after=_utcnow(), cron_expression=task.cron_expression,
            tz_name=_resolve_task_timezone(db, task))

    def _skip_for_in_flight(self, db, task, run_id: str, other) -> str:
        """`B674`. This run did not start because another of the same workflow
        is still going: its row is `skipped` with the sentence that says which
        run and what it waits for. Nobody is notified — the run that waits
        already asked its question — and the task's next time moves on as a
        no-op's would. Answers the sentence."""
        from core.database import TaskRun
        from src import workflow_runs as wr

        tz_name = _resolve_task_timezone(db, task)
        sentence = (wr.parked_sentence(db, other, tz_name=tz_name) if other.status == "waiting"
                    else (f"Did not start: the {wr._clock(other.started_at, tz_name)} run "
                          f"is still running."))
        run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
        if run is not None:
            run.status = "skipped"
            run.result = sentence
            run.error = sentence
            run.finished_at = _utcnow()
        task.next_run = self._next_run_after(db, task)
        db.commit()
        logger.info("Workflow '%s': %s", task.name, sentence)
        return sentence

    def in_flight_sentence(self, task_id: str) -> str | None:
        """`B674`. Why a run of this workflow cannot start now, when a run of it
        is parked — the sentence the webhook's 409 and Run now's say — or
        `None`."""
        from core.database import SessionLocal, ScheduledTask
        from src import workflow_runs as wr

        db = SessionLocal()
        try:
            task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            # `B1102`: a plain Prompt task's parked run holds it the same way.
            if task is None or (task.task_type or "llm") not in _PARKING_TASK_TYPES:
                return None
            parked = wr.parked_run(db, task_id)
            if parked is None:
                return None
            return wr.parked_sentence(db, parked, tz_name=_resolve_task_timezone(db, task))
        finally:
            db.close()

    def _record_parked_skip(self, task_id: str) -> str | None:
        """`B674` for `run_task_now`: a trigger that arrives while this
        workflow's run is parked writes its own `skipped` row (the same
        sentence) and starts nothing. Answers the sentence, or `None` when no
        run of it is parked."""
        from core.database import SessionLocal, ScheduledTask, TaskRun
        from src import workflow_runs as wr

        db = SessionLocal()
        try:
            task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            # `B1102`: a plain Prompt task's parked run holds it the same way.
            if task is None or (task.task_type or "llm") not in _PARKING_TASK_TYPES:
                return None
            parked = wr.parked_run(db, task_id)
            if parked is None:
                return None
            run_id = str(uuid.uuid4())
            db.add(TaskRun(id=run_id, task_id=task_id, started_at=_utcnow(),
                           status="queued", result="Queued — waiting for a free slot…"))
            db.commit()
            return self._skip_for_in_flight(db, task, run_id, parked)
        finally:
            db.close()

    def _retire_cards(self, db, run_id: str, task) -> int:
        """Every card a waiting step of this run holds is retired — consumed as
        a denial, the way a scheduled run's card always was — so a Stop, a
        switch-off or a time limit leaves no card that could still be
        answered. Answers how many."""
        from src import workflow_runs as wr
        from src.tool_approvals import tool_approval_store

        retired = 0
        for rec in wr.waiting_records(db, run_id):
            waiting = wr.waiting_of(rec) or {}
            if waiting.get("kind") != wr.WAITING_APPROVAL or not waiting.get("approval_id"):
                continue
            try:
                tool_approval_store.consume(
                    waiting["approval_id"], decision="deny",
                    owner=getattr(task, "owner", None) if task is not None else None,
                    session_id=waiting.get("session_id") or "")
                retired += 1
            except Exception:
                logger.debug("Could not retire card %s", waiting.get("approval_id"),
                             exc_info=True)
        return retired

    def _end_parked_run(self, db, task, run, *, status: str, sentence: str) -> None:
        """A parked run that will not go on: its cards retired, its waiting
        steps ended with the same words, the run `status` with them."""
        from src import workflow_runs as wr

        self._retire_cards(db, run.id, task)
        wr.end_waiting_records(db, run.id, status="aborted", error=sentence)
        run.status = status
        run.result = sentence
        run.error = sentence
        run.finished_at = _utcnow()
        db.commit()
        if task is not None:
            self._notify_run_outcome(task, status, body=sentence, task_id=task.id)

    async def _claim_for_resume(self, task_id: str) -> bool:
        """Take the task's claim for a resume; `False` while something else
        holds it (a trigger being skipped, say) — try again shortly."""
        async with self._executing_lock:
            if task_id in self._executing:
                return False
            self._executing.add(task_id)
            return True

    def _spawn_resume(self, task_id: str, run_id: str, *, started_by: str, answer=None):
        """Go on with a parked run whose claim is held. Spawned, so whoever
        asked — the answer route, the sweeper — is not held for the run."""
        return asyncio.create_task(self._execute_task(
            task_id, resume_run_id=run_id, started_by=started_by, answer=answer))

    async def resume_workflow_run(self, run_id: str, *, started_by: str = STARTED_BY_BACKGROUND,
                                  answer=None) -> bool:
        """`P22-11` / `P22-17`. Go on with a parked run: every gate asked again,
        on the version it started with, from where it stopped. `False` when
        the run is not parked, or its task's claim is held right now."""
        from core.database import SessionLocal, TaskRun

        if started_by not in STARTED_BY:
            raise ValueError(f"started_by must be one of {STARTED_BY}, not {started_by!r}")
        db = SessionLocal()
        try:
            run = db.query(TaskRun).filter(TaskRun.id == run_id).first()
            if run is None or run.status != "waiting":
                return False
            task_id = run.task_id
        finally:
            db.close()
        if not await self._claim_for_resume(task_id):
            return False
        self._spawn_resume(task_id, run_id, started_by=started_by, answer=answer)
        return True

    async def answer_question(self, *, task_id: str, run_id: str, node_id: str, item,
                              approval_id: str, decision: str, owner, session: str,
                              tool: str, who: str, tz_name: str | None,
                              busy: str) -> tuple:
        """`B1102`. A parked run's question, answered — the ONE core both doors
        call: the workflow's answer route (`P22-17`) and a plain task's
        (`POST /api/tasks/{id}/runs/{run_id}/answer`), each after scoping the run
        to its owner and finding the record that waits on exactly this card
        (`Law 14`). Answers `(outcome, StepAnswer)`; raises `QuestionRefused`.

          * the store must still hold the card for this owner and the session it
            was minted in — otherwise it is not this run's card: a 404, and
            nothing about it is said or consumed (a card the store no longer
            holds lapsed, and is answered so);
          * the task's claim is taken for the resume (`busy` while another
            holds it — "answer again");
          * `consume(..., allow_continuation=False)` — SINGLE_ACTION scope, so
            Allow resumes the run ONCE and the gate re-arms behind the sealed
            action; `approve_task` or `deny` (the door refuses `approve`);
          * the answer, with who and when, and the run goes on as the
            person's (`STARTED_BY_PERSON`). The consumed approval travels in
            memory: a restart in that window is a lapsed answer.

        The seal, the TTL, single use and owner binding are the store's,
        unchanged (`FORBIDDEN.md` Part 2)."""
        from src.interactive_gate import STARTED_BY_PERSON
        from src.tool_approvals import _normalized_owner, tool_approval_store
        from src.workflow_runs import _clock

        pending = tool_approval_store.peek(approval_id)
        if pending is not None and (pending.owner != _normalized_owner(owner)
                                    or pending.session_id != session):
            raise QuestionRefused(404, "No such question.")
        if not await self._claim_for_resume(task_id):
            raise QuestionRefused(409, busy)
        at = _clock(_utcnow(), tz_name)
        lapsed = f"Nobody answered in time — {tool} was not done."
        if pending is None:
            verdict, outcome = StepAnswer(node_id, item, ANSWER_LAPSED, lapsed), "lapsed"
        else:
            exact = tool_approval_store.consume(
                approval_id, decision=decision, owner=owner, session_id=session,
                allow_continuation=False, outcome={})
            if decision == "deny":
                verdict = StepAnswer(node_id, item, ANSWER_DENY,
                                     f"Denied by {who} at {at}: {tool} — it was not done.")
                outcome = "denied"
            elif exact is None:
                verdict, outcome = StepAnswer(node_id, item, ANSWER_LAPSED, lapsed), "lapsed"
            else:
                verdict = StepAnswer(node_id, item, ANSWER_ALLOW,
                                     f"Allowed once by {who} at {at}: {tool}",
                                     exact_approval=exact)
                outcome = "resumed"
        self._spawn_resume(task_id, run_id, started_by=STARTED_BY_PERSON, answer=verdict)
        return outcome, verdict

    async def _resume_due_waits(self) -> int:
        """`P22-11`. The sweeper: every parked run whose wait is over goes on.

          * a Wait whose time has come (`time`);
          * a card the store no longer holds — it lapsed, or Pantheon
            restarted (`approval`; the step says which and takes its failure
            port);
          * a step a takeover stopped, once Pantheon is idle (`idle`);
          * a run whose workflow was switched off (it ends, and says so).
        Resumed as background work, so `B1060`'s wait applies: "at 08:00, or
        as soon after as Pantheon is idle". Answers how many it resumed."""
        from core.database import SessionLocal, ScheduledTask, TaskRun
        from src import workflow_runs as wr
        from src.tool_approvals import tool_approval_store

        try:
            from src.interactive_gate import has_foreground_activity
            busy = has_foreground_activity()
        except Exception:
            busy = False
        due = []
        db = SessionLocal()
        try:
            now = _utcnow()
            for run in db.query(TaskRun).filter(TaskRun.status == "waiting").all():
                if run.task_id in self._executing:
                    continue
                task = db.query(ScheduledTask).filter(ScheduledTask.id == run.task_id).first()
                if task is None or task.status != "active":
                    due.append(run.id)
                    continue
                for rec in wr.waiting_records(db, run.id):
                    waiting = wr.waiting_of(rec) or {}
                    kind = waiting.get("kind")
                    if kind == wr.WAITING_TIME and rec.resume_at is not None \
                            and rec.resume_at <= now:
                        due.append(run.id)
                        break
                    if kind == wr.WAITING_APPROVAL and \
                            tool_approval_store.peek(waiting.get("approval_id")) is None:
                        due.append(run.id)
                        break
                    if kind == wr.WAITING_IDLE and not busy:
                        due.append(run.id)
                        break
        except Exception:
            logger.warning("Could not read the parked workflow runs", exc_info=True)
        finally:
            db.close()
        resumed = 0
        for run_id in dict.fromkeys(due):
            if await self.resume_workflow_run(run_id, started_by=STARTED_BY_BACKGROUND):
                resumed += 1
        return resumed

    def _next_resume_at(self):
        """The earliest time a parked step is due, for `_loop`'s sleep."""
        from core.database import SessionLocal, TaskRunNode

        db = SessionLocal()
        try:
            row = (db.query(TaskRunNode.resume_at)
                   .filter(TaskRunNode.status == "waiting", TaskRunNode.resume_at.isnot(None))
                   .order_by(TaskRunNode.resume_at.asc()).first())
            return row[0] if row else None
        finally:
            db.close()

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
            if task_type == "workflow":
                return self._workflow_needs_model_slot(db, task)
            if task_type != "action":
                return True
            return self._action_needs_model(getattr(task, "action", ""))
        finally:
            db.close()

    def _workflow_needs_model_slot(self, db, task) -> bool:
        """`P22-05`. A workflow waits in the model queue if any step may call a
        model: a Prompt or Research step, a model-backed action, or a Run task
        step (its task may, and it runs inside this workflow's slot). A
        workflow of housekeeping actions does not queue behind a model run, as
        the same chain would not. A document that cannot be read queues, as an
        unknown task does — it fails at once either way."""
        from core.database import Workflow
        from src import workflow_document as wd

        wf = db.query(Workflow).filter(Workflow.task_id == task.id).first()
        try:
            graph = wd.parse_graph(wf.graph) if wf is not None else None
        except wd.DocumentError:
            graph = None
        if graph is None:
            return True
        # `P22-11`. `node_needs_model` replaces "every kind that is not an
        # action" (`SLICE-CD-DESIGN` § 0.9): a workflow of logic, HTTP, MCP and
        # Code steps does not queue behind a model run. A Run task step still
        # does (its task may call a model, inside this workflow's slot) — the
        # rule's own answer says so.
        return any(wd.node_needs_model(node) for node in graph["nodes"])

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
                        # `B1014`: paced (a hosted Miniflux is a third party) and routed.
                        async with httpx.AsyncClient(
                                timeout=10, mounts=paced_http.direct_mounts(_base)) as client:
                            resp = await paced_http.request(
                                "GET", f"{_base}/v1/entries", client=client,
                                authenticated=bool(_headers),
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

    async def _run_plain_prompt(self, task, db, run_id: str, *, resume: bool = False,
                                answer=None, may_wait: bool = True) -> tuple:
        """`B1102`. A plain Prompt task's run: `(status, text)` — `success` and
        its output, or `error` and why. Raises `TaskWaiting` when it parks.

        It waits for a yes exactly as a workflow's Prompt step does, through
        the same parts: `_run_agent_loop` raises `TaskWaiting` on a card when
        the run's slot says `may_wait` (the card then waits
        `workflow_approval_timeout_seconds`, `D-2026-10-02-01` §1);
        `_park_plain_run` keeps the walker's waiting record and asks the person;
        a resume is answered by the walker's own `_approval_verdict` — Allow
        replays the consumed approval ONCE (the loop's `exact_approval`) and
        the run goes on; Deny, a lapse, a restart or a withdrawn card end it
        `error`, saying which. Before, the card was consumed as a denial on the
        spot ("Scheduled task paused safely", which a run another run awaits
        still says — `may_wait=False`)."""
        from types import SimpleNamespace

        from src import workflow_runs as wr
        from src.builtin_actions import TaskWaiting

        slot = self._state_for(run_id)
        rec = self._plain_record(db, run_id)
        if resume:
            waiting = (wr.waiting_of(rec) or {}) if rec is not None and rec.status == "waiting" else {}
            if waiting.get("kind") != wr.WAITING_APPROVAL:
                raise RuntimeError("This run was waiting for nothing it can go on from.")
            verdict = self._approval_verdict(SimpleNamespace(db=db, task=task), rec, waiting, answer)
            if verdict is None:
                # Still open — no answer for it, and the store still holds it:
                # it waits on, and the person was already asked.
                raise TaskWaiting("Waiting for your yes on "
                                  f"{waiting.get('tool_label') or waiting.get('tool') or 'an action'}",
                                  kind=wr.WAITING_APPROVAL)
            if verdict.decision != ANSWER_ALLOW:
                if answer is None:
                    # The sweeper's verdict (a lapse, a restart, a withdrawn
                    # card); a person's answer is already in the log as "Resumed: …".
                    self._record_run_step(run_id, kind="progress", detail=verdict.sentence)
                wr.record_node_end(db, rec, status="error", text=verdict.sentence,
                                   error=verdict.sentence, steps=self.run_steps(run_id),
                                   model=rec.model, owner=task.owner)
                return "error", verdict.sentence
            wr.record_node_resumed(db, rec)
            slot["exact_approval"] = verdict.exact_approval
        slot["may_wait"] = bool(may_wait)
        try:
            result = await self._execute_llm_task(task, db, run_id=run_id)
        except TaskWaiting as parked:
            # `B1111` on `B1102`'s path (`integrate-g`): a plain task's question
            # names its tool as a workflow step's does — in its record, the
            # run's line, the notification and the answer's sentence.
            named = named_question(parked)
            self._park_plain_run(db, task, run_id, named, rec)
            if named is parked:
                raise
            raise named from None
        except BaseException as exc:
            if rec is not None:
                stopped = isinstance(exc, asyncio.CancelledError)
                wr.record_node_end(db, rec, status="aborted" if stopped else "error",
                                   error=NODE_STOPPED if stopped else f"{type(exc).__name__}: {exc}",
                                   steps=self.run_steps(run_id), model=self.run_model(run_id),
                                   owner=task.owner)
            raise
        if rec is not None:
            wr.record_node_end(db, rec, status="success", text=result,
                               steps=self.run_steps(run_id), model=self.run_model(run_id),
                               owner=task.owner)
        return "success", result

    def _plain_record(self, db, run_id: str):
        """`B1102`. The waiting record a plain Prompt task's run keeps once it
        has parked (`PLAIN_TASK_NODE`), or `None`."""
        from core.database import TaskRunNode

        return (db.query(TaskRunNode)
                .filter(TaskRunNode.run_id == run_id, TaskRunNode.node_id == PLAIN_TASK_NODE)
                .order_by(TaskRunNode.seq.desc()).first())

    def _park_plain_run(self, db, task, run_id: str, parked, rec) -> None:
        """`B1102`. A plain Prompt task's run parks: its waiting record (the
        walker's shape, one per run, written on its first park), a line in its
        log, and the question to the person — a notification with the card as
        `review` (`kind: "task_approval"`), sent even with the task's
        notifications off, because a question is not a report on an outcome
        (`SLICE-CD-DESIGN` § 1.5). `_execute_task_locked`'s `TaskWaiting`
        branch then writes the run `waiting` and lets go of its slot."""
        from src import workflow_runs as wr

        detail = dict(parked.detail)
        waiting = {"kind": parked.kind, **detail}
        # The card's deadline, as the walker writes it (`_park_record`): an ISO
        # string the sweeper and the verdict read back with `_parse_iso`.
        until = detail.get("until")
        if isinstance(until, (int, float)):
            waiting["until"] = datetime.fromtimestamp(
                until, tz=timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        if rec is None:
            rec = wr.record_node_start(
                db, run_id=run_id,
                node={"id": PLAIN_TASK_NODE, "kind": "llm", "label": task.name},
                seq=0, input_envelope=self.run_trigger(run_id), workflow_version=None,
                owner=task.owner)
        wr.record_node_waiting(db, rec, waiting=waiting, steps=self.run_steps(run_id),
                               model=self.run_model(run_id))
        self._record_run_step(run_id, kind="progress", detail=parked.sentence)
        if parked.kind != wr.WAITING_APPROVAL:
            return
        card = waiting.get("card") if isinstance(waiting.get("card"), dict) else {}
        tool = (waiting.get("tool_label") or waiting.get("tool")
                or (card.get("action") or {}).get("tool") or "an action")
        self.add_notification(
            task.name, "waiting", task.id, owner=task.owner,
            body=f"“{task.name}” is waiting for your yes: {tool}.",
            review={"kind": "task_approval", "task_id": task.id, "task": task.name,
                    "run_id": run_id, "node_id": PLAIN_TASK_NODE, "item": None,
                    "label": task.name, "since": (wr.waiting_of(rec) or {}).get("since"),
                    "tool_label": waiting.get("tool_label") or None,
                    "approval": card or None})

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
                name=task_chat_name(task),
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
                        session_id, task_chat_name(task), endpoint_url, model,
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
        # `P22-09` / `P22-15`. What a workflow step hands its model beside the
        # trigger — the values its named slots read, a skill it follows — each
        # already wrapped untrusted with the gate armed. On the step's own slot
        # (`P8-27`'s mechanism), inserted after the trigger message.
        _context_msgs = list((self._runs().get(run_id) or {}).get("context_messages") or ())

        # Try using the agent loop for full tool access
        try:
            result = await self._run_agent_loop(
                endpoint_url, model, task, session_id,
                system_prompt=system_prompt, disabled_tools=disabled_tools or None,
                relevant_tools=relevant_tools,
                datetime_context_msg=_dt_msg,
                trigger_context_msg=_trigger_msg,
                run_id=run_id,
                # Only when there is something to add: a plain task's call is
                # the call it always was (an existing stub pins its shape).
                **({"context_msgs": _context_msgs} if _context_msgs else {}),
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
            messages.extend(_context_msgs)
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
                name=task_chat_name(task),
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
                        session_id, task_chat_name(task), endpoint_url, model_name,
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
                              run_id: str | None = None,
                              context_msgs: list | None = None) -> str:
        """Run the full agent loop with tool access, collecting the final text.

        `P22-17`. A workflow step's slot may carry `may_wait` — the step can
        park on a card instead of the card being denied on the spot — and, when
        it resumes after an Allow, the consumed `exact_approval` the loop
        replays first. A plain scheduled Prompt task carries neither and keeps
        "paused safely" exactly as before (`Law 1`).
        """
        from src.agent_loop import stream_agent_loop
        from src.interactive_gate import STARTED_BY_PERSON

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
        # `P22-09` / `P22-15`. A step's named-slot values and a followed skill,
        # each its own untrusted block, after what fired the run.
        for extra in context_msgs or ():
            if isinstance(extra, dict):
                messages.append(extra)
        messages.append({"role": "user", "content": user_content})
        _slot = self._runs().get(run_id) or {}
        _exact_approval = _slot.get("exact_approval")
        _may_wait = bool(_slot.get("may_wait"))
        # `SLICE-CD-DESIGN` § 0.11 (`B1080`, reproduced by `integrate-c`
        # on P22-08). This was `workload="background"` for every run, and the
        # local-model gate (`llm_core._local_model_slot`) holds a background
        # call while there is foreground activity — so a step a person tested,
        # ran or allowed from a notification never reached a model on this
        # machine while their page was open, the page that was waiting for it.
        # The workload follows who started the run (`B1047`'s `started_by`):
        # a person's is foreground, background work stays background.
        _workload = ("foreground" if self._run_started_by(run_id) == STARTED_BY_PERSON
                     else "background")
        _loop_extra = {}
        if _exact_approval is not None:
            _loop_extra["exact_approval"] = _exact_approval
        if _may_wait:
            from src.workflow_runs import workflow_approval_ttl_seconds
            _loop_extra["approval_ttl_seconds"] = workflow_approval_ttl_seconds(task.owner)
            # `B1103`. The card is the run's question: typing into the chat
            # this step writes into does not withdraw it.
            _loop_extra["approval_held_by_run"] = True
        if _slot.get("allowed_tools") is not None:
            # `P22-16`. An AI step limited to its own tools (`wf-effects`' policy).
            from src.tool_policy import ToolPolicy
            _loop_extra["tool_policy"] = ToolPolicy(
                allowed_tools=frozenset(_slot["allowed_tools"]))
        if _slot.get("suppress_skills"):
            _loop_extra["suppress_skills"] = True

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
            # `B1047`. The second wait, before the model call, follows the
            # run's own: background work waits for Pantheon to be idle, a run a
            # person started waits only for a chat reply, a forced one for
            # nothing. It was the idle wait for every run, so a person's Run
            # now — even a forced one — sat here while their tab was open.
            from src.interactive_gate import wait_for_chat_quiet, wait_for_interactive_quiet
            _waits = self._run_waits_for(run_id)
            if _waits == "idle":
                await wait_for_interactive_quiet(f"agent task {task.name}")
            elif _waits == "chat":
                await wait_for_chat_quiet(f"agent task {task.name}")
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
            workload=_workload,
            **_loop_extra,
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
                                # `B899`. Why the card exists, in the card's own
                                # words. `public_payload`'s `description` is
                                # `reason or default_reason()` (`P4-04`), already
                                # derived from the card's own state — so it says
                                # "Untrusted context influenced this run" only
                                # when the run was tainted, and says something
                                # else (a strict-rung confirm, `P7-03`; a
                                # self-escalation the assistant asked for,
                                # `P7-02`) when it was not. Reused here rather
                                # than re-asserting "after untrusted context" for
                                # every card (`Law 7`/`Law 14`), which blamed
                                # untrusted content on cards that never saw any
                                # (`Law 10`).
                                "reason": (approval.get("description") or "").strip(),
                            }
                            if _may_wait:
                                # `P22-17`. A workflow step parks on the card:
                                # it stays pending (its own deadline, above),
                                # the person answers it from a notification,
                                # and Allow resumes this step ONCE. Raised, a
                                # `BaseException`, so `_execute_llm_task`'s
                                # fallback cannot answer around it.
                                from src.builtin_actions import WAIT_KIND_APPROVAL, TaskWaiting
                                raise TaskWaiting(
                                    f"Waiting for your yes on {approval_pause['tool']}",
                                    kind=WAIT_KIND_APPROVAL,
                                    approval_id=approval_pause["approval_id"],
                                    session_id=session_id,
                                    tool=approval_pause["tool"],
                                    reason=approval_pause["reason"],
                                    until=approval.get("expires_at"),
                                    card=approval,
                                )
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
            # The card's own sentence carries whether untrusted content was
            # involved; the fallback (a card with no description) claims nothing
            # about taint, because on a clean-run pause there is nothing to claim.
            detail = approval_pause.get("reason") or (
                "It asked for an action that needs a person to approve it."
            )
            return (
                "Scheduled task paused safely: "
                f"{approval_pause['tool']} needs a person to approve its next "
                f"action. {detail} That action was not executed. Run this task "
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

    # ── `P22-05` · the walker: a workflow is one document, run as one run ────
    #
    # `D-2026-10-01-05` §1. `_execute_task_locked` hands a `task_type="workflow"`
    # trigger here, inside every gate a task has. The walker runs the document's
    # steps through the executors that already exist — `_execute_action`,
    # `_execute_llm_task`, `_execute_research_task`, and `_execute_task` for a
    # Run task step — each as a stand-in (`workflow_document.node_stand_in`) and
    # each under its own slot (`node_slot`), so a step's model, step log and
    # input are its own. Every step is recorded (`task_run_nodes`, `P22-07`);
    # the run's own step log holds what fired it and one line per step. One
    # step at a time, one path: each step leaves by exactly one port, so a step
    # never runs twice in a run (fan-out is `P22-11`'s).

    def _document_context(self, db, task, graph: dict) -> dict:
        """What `validate_document` checks a document against, read fresh:
        the owner's tasks the Run task steps name, the owner's crew members the
        Prompt steps name, whether the owner may run admin-only actions."""
        from core.database import CrewMember, ScheduledTask

        task_ids = {(n.get("config") or {}).get("task_id") for n in graph.get("nodes") or ()}
        task_ids = [i for i in task_ids if isinstance(i, str) and i]
        crew = {(n.get("config") or {}).get("crew_member_id") for n in graph.get("nodes") or ()}
        crew = [i for i in crew if isinstance(i, str) and i]
        owner = task.owner
        tasks_by_id = {}
        if task_ids:
            q = db.query(ScheduledTask).filter(ScheduledTask.id.in_(task_ids))
            tasks_by_id = {row.id: row for row in q.all()}
        crew_ids = set()
        if crew:
            q = db.query(CrewMember.id).filter(CrewMember.id.in_(crew))
            q = q.filter(CrewMember.owner == owner) if owner else q.filter(CrewMember.owner.is_(None))
            crew_ids = {row[0] for row in q.all()}
        # `P22-09`…`P22-18`. What the document is checked against beyond the
        # owner's tasks and crew: integrations, MCP tools, skills, the AI
        # tool choices, the workstation, the For-each cap (`WorkflowResources`,
        # built by `wf-effects`) — read fresh, so the run is checked against
        # what is true now, in the save's words.
        from src import workflow_effects as we
        return {"owner": owner, "tasks_by_id": tasks_by_id, "crew_ids": crew_ids,
                "owner_is_admin": owner_has_admin_task_privileges(owner),
                "own_task_id": task.id,
                "resources": we.workflow_resources(owner)}

    def _load_workflow(self, db, task, version=None):
        """`(workflow row, document, refusal sentence)` — the refusal is the
        same sentence the save was told, or why there is nothing to run.

        `P22-11`. `version` is the one a resumed run started with: a run
        resumes on its own document, not on an edit made while it waited. If
        that version was pruned since, the run cannot go on, and says so."""
        from core.database import Workflow, WorkflowVersion
        from src import workflow_document as wd

        wf = db.query(Workflow).filter(Workflow.task_id == task.id).first()
        if wf is None:
            return None, None, WORKFLOW_DOCUMENT_MISSING
        raw = wf.graph
        if version is not None and version != wf.version:
            kept = (db.query(WorkflowVersion)
                    .filter(WorkflowVersion.workflow_id == wf.id,
                            WorkflowVersion.version == version).first())
            if kept is None:
                return wf, None, (f"This run started on version {version} of the workflow, "
                                  f"which is no longer kept, so it cannot go on.")
            raw = kept.graph
        try:
            graph = wd.parse_graph(raw)
            refusal = wd.validate_document(graph, **self._document_context(db, task, graph))
        except wd.DocumentError as exc:
            return wf, None, exc.refusal.sentence
        return wf, graph, (refusal.sentence if refusal else None)

    def _record_workflow_dry_run(self, db, task, run_id: str, run) -> str | None:
        """`P22-05` / `P22-04`. Plan every step of a workflow; run nothing.

        Breadth first from the first step, each step once, `when` from its
        first parent — wave B's chain dry run's shape, on a document. Each
        step's plan is `dry_run_plan`'s lines (one planner, `Law 7`) on a `dry`
        step record, so a plan of many steps is not cut by the run's 200-line
        step log and is never read as a step's last run. The run's own log is
        the headline and one line per step. Answers why it was not planned —
        the same sentence a save or a real run gets — or `None`.
        """
        from src import workflow_document as wd
        from src import workflow_runs as wr

        wf, graph, refused = self._load_workflow(db, task)
        if refused:
            return refused
        lines = [DRY_RUN_HEADLINE]
        for seq, entry in enumerate(wd.reachable_bfs(graph), start=1):
            node = entry["node"]
            steps, declined = self._plan_workflow_node(db, task, node)
            wr.record_dry_node(db, run_id=run_id, node=node, seq=seq, steps=steps,
                               declined=declined, reached_by=entry["when"],
                               depth=entry["depth"], workflow_version=wf.version)
            how = ("" if entry["when"] is None else
                   " (if the step before works)" if entry["when"] == EDGE_WHEN_SUCCESS
                   else " (if the step before fails)")
            said = declined or next(
                (s["detail"] for s in steps if s.get("detail") != DRY_RUN_HEADLINE), "")
            lines.append(f"Step {seq}, “{node['label']}”{how}: {said}")
        why_not = not_active_words(task)
        if why_not:
            lines.append(f"{why_not[:1].upper()}{why_not[1:]}, so a real run would not start it.")
        for line in lines:
            self._record_run_step(run_id, kind="dry-run", detail=line)
        if run is not None:
            run.status = "skipped"
            run.result = "\n".join(lines)
            run.finished_at = _utcnow()
            self._attach_run_steps(run_id, run)
        db.commit()
        logger.info("Dry run of workflow '%s' (run %s): planned %d step(s), executed nothing",
                    task.name, run_id, len(lines) - 1)
        return None

    def _plan_workflow_node(self, db, task, node: dict) -> tuple:
        """`(steps, declined)` for one step of a workflow dry run."""
        from core.database import ScheduledTask
        from src.builtin_actions import dry_run_plan
        from src import workflow_document as wd

        config = node.get("config") or {}
        kind = node.get("kind")
        if kind == wd.NODE_KIND_RUN_TASK:
            target = db.query(ScheduledTask).filter(
                ScheduledTask.id == config.get("task_id")).first()
            if target is not None and target.owner != task.owner:
                target = None
            declined = dry_run_declined(target, db=db)
            if declined:
                return [], declined
            lines = [f"Would run the task “{target.name}”, as its own run with its "
                     f"own history.", *dry_run_lines(target)[1:]]
        elif kind not in wd.STAND_IN_KINDS:
            # `P22-10`…`P22-18`. A logic, HTTP, MCP, Skill, Code, Wait, Merge or
            # For-each step: the document's own planner (`plan_lines`), which
            # shows `never` slots verbatim and value slots as their references,
            # never as values.
            from src import workflow_effects as we
            lines = list(wd.plan_lines(node, we.workflow_resources(task.owner)))
        else:
            target = config.get("output_target")
            lines = dry_run_plan(
                task_type=kind, action=config.get("action"), prompt=config.get("prompt"),
                owner=task.owner, model=config.get("model"),
                endpoint_url=config.get("endpoint_url"), noun="step",
                extra=[f"Result goes to: "
                       f"{result_place(target) if target else 'only the next step'}"])
        return [shape_run_step({"kind": "dry-run", "detail": line}) for line in lines], None

    async def _run_workflow(self, task, db, run_id: str):
        """Walk the document. Answers a `NodeResult`; raises `TaskWaiting` when
        the run parks (`P22-11`).

        `SLICE-CD-DESIGN` § 1.4. The run's state is its step records
        (`workflow_runs.RunState`, `Law 7`), so a run that parked — on a Wait,
        a person's yes, or a foreground takeover — and a run a restart left
        waiting pick up from the same place: every step whose arrows have
        fired and that has no record is ready; a Merge waits for its inputs.

          * Branches run side by side. Steps that drive a model take a per-run
            lock one at a time; deterministic and logic steps run beside them,
            at most `WORKFLOW_PARALLEL_STEPS` at once. The run holds one
            model-slot permit, so the concurrency cap still applies.
          * One question at a time per run: while a step waits for a yes, the
            run's other model steps do not start, though other branches go on
            (`SLICE-CD-DESIGN` § 6's default; it was also because a session's
            newer card superseded it, `tool_approvals.create`, which a run's
            question — `held_by_run`, `B1103` — no longer is).
          * When nothing can go on and something waits, the run parks: records
            written, `TaskWaiting` raised, and `_execute_task_locked` lets go of
            the model slot, the time limit and the claim.

        How a run ends — one rule, written once (`Law 10`):
          * a branch that ended on an UNHANDLED `error` (no arrow out of its
            failure port) → `error`, naming the step (and item) that failed;
          * every step `skipped` → `skipped`;
          * anything else → `success`. `result` is what the step that finished
            last made.
        """
        from src import workflow_runs as wr
        from src.builtin_actions import NODE_STATUS_ERROR, NodeResult
        from src.event_bus import run_origin

        run_slot = self._state_for(run_id)
        answer = run_slot.pop("answer", None)
        resuming = bool(run_slot.get("resuming"))
        records = [r for r in wr.run_node_records(db, run_id) if not r.dry]
        version = (next((r.workflow_version for r in records
                         if r.workflow_version is not None), None)
                   if resuming else None)
        wf, graph, refused = self._load_workflow(db, task, version=version)
        if not refused and not resuming:
            # `P22-19` (`SLICE-EF-DESIGN` § 1.1). A step the model drafted, or
            # one a file carried, runs only after a person has checked it. The
            # switch refuses first; this holds for a marked document whose
            # trigger is on anyway — written straight to the database, or run
            # with *Run now* — and ends the run before any step starts. The
            # dry run and *Test this step* do not come through here.
            from src import workflow_document as wd
            marks = wd.unchecked_refusal(graph)
            refused = marks.sentence if marks is not None else None
        if refused:
            self._record_run_step(run_id, kind="progress", detail=refused)
            if resuming:
                wr.end_waiting_records(db, run_id, status="error", error=refused)
            return NodeResult(NODE_STATUS_ERROR, payload=refused)
        state = wr.RunState(graph, records, trigger=self.run_trigger(run_id))
        if state.trigger is not None and run_slot.get("trigger") is None:
            run_slot["trigger"] = state.trigger
        w = _Walk(task=task, db=db, run_id=run_id, wf=wf, graph=graph, state=state,
                  name=wf.name or task.name,
                  version=version if version is not None else wf.version,
                  started_by=run_slot.get("started_by") or STARTED_BY_BACKGROUND,
                  waits_for=self._run_waits_for(run_id))
        with run_origin(task.id, w.name, run_id):
            try:
                reruns = self._apply_resume(w, answer)
                for node, rec, verdict in reruns:
                    self._start_step(w, node, rec=rec, answer=verdict)
                while True:
                    self._start_ready(w)
                    if not w.running:
                        if w.timers and self._fire_due_timers(w):
                            continue
                        break
                    timeout = self._seconds_to_next_timer(w)
                    done, _pending = await asyncio.wait(
                        list(w.running), timeout=timeout,
                        return_when=asyncio.FIRST_COMPLETED)
                    for finished in done:
                        self._finish_step(w, finished)
                    self._fire_due_timers(w)
            except asyncio.CancelledError:
                await self._stop_steps(w)
                raise
        if w.last_model:
            self.set_run_model(run_id, w.last_model)
        waiting = state.waiting()
        if waiting:
            raise self._park_signal(w, waiting)
        wr.maybe_prune_node_records(db)
        return self._run_outcome(w)

    # ── the walker's parts ─────────────────────────────────────────────────

    def _node_needs_model(self, node: dict) -> bool:
        """`P22-11`. Does this step drive a model (and so take the run's model
        lock)? `workflow_document.node_needs_model` — the rule's one answer,
        which replaces Slice B's "not an action" test and already reads a
        model-backed action (`MODEL_BACKED_ACTIONS`, `P8-22`), a Run task step
        and the step a For-each repeats (`integrate-d`: the walker restated
        the last two)."""
        from src import workflow_document as wd

        return wd.node_needs_model(node)

    def _start_ready(self, w) -> None:
        """Start every step that is ready, up to the parallel cap. A Wait and a
        Merge finish here, without a coroutine of their own."""
        from src import workflow_document as wd

        progressed = True
        while progressed:
            progressed = False
            for node in w.state.ready():
                if node["id"] in w.started:
                    continue
                kind = node.get("kind")
                if kind == wd.NODE_KIND_WAIT:
                    self._start_wait(w, node)
                    progressed = True
                    continue
                if kind == wd.NODE_KIND_MERGE:
                    self._finish_merge(w, node)
                    progressed = True
                    continue
                if self._node_needs_model(node) and (
                        w.question_open or any(self._node_needs_model(n)
                                               for n, _r, _s in w.running.values())):
                    # One question at a time per run (`SLICE-CD-DESIGN` § 1.5):
                    # a model step starts only when no other model step is in
                    # flight and no card is open. Waiting on the lock is not
                    # enough — a step queued behind one that then parks would
                    # mint its own card in the same chat and supersede it
                    # (`tool_approvals.create`).
                    continue
                if len(w.running) >= WORKFLOW_PARALLEL_STEPS:
                    return
                self._start_step(w, node)
                progressed = True

    def _handed(self, w, node: dict):
        """What a step is handed (`P8-29`, kept — `Law 1`): what fired the run
        for a step the start leads to, else the hand-off of the step whose
        arrow into it fired first — the same envelope a chain hands on,
        wrapped untrusted at the far end."""
        state = w.state
        node_id = node["id"]
        if node_id in state.starts:
            into = state.incoming(node_id)
            if not into or any(e.get("from") == state.start for e in into):
                return state.trigger
        for source in state.arrived_from(node_id):
            if source == state.start:
                return state.trigger
            rec = state.record(source)
            out = state.output_of(source) or {}
            text, data = out.get("text") or "", out.get("data")
            if not (text or data):
                return None
            label = (state.by_id.get(source) or {}).get("label") or source
            return _build_task_handoff(
                task_name=label, task_id=w.task.id, run_id=w.run_id,
                status=rec.status if rec is not None else "success",
                result=text, payload=data)
        return None

    def _start_step(self, w, node: dict, *, rec=None, answer=None) -> None:
        from src import workflow_runs as wr

        node_id = node["id"]
        handed = self._handed(w, node)
        if rec is None:
            rec = wr.record_node_start(
                w.db, run_id=w.run_id, node=node, seq=w.state.next_seq(),
                input_envelope=handed, workflow_version=w.version, owner=w.task.owner)
        else:
            wr.record_node_resumed(w.db, rec)
        w.state.note_record(rec)
        w.started.add(node_id)
        slot = node_slot(w.run_id, node_id)
        self._state_for(slot).update(trigger=handed, started_by=w.started_by,
                                     waits_for=w.waits_for)
        if answer is not None and answer.sentence:
            self._record_run_step(slot, kind="progress", detail=answer.sentence)
        self._set_run_progress(w.run_id, f"{node.get('label') or node_id}…")
        step = asyncio.create_task(self._run_step_guarded(w, node, slot, rec, answer))
        w.running[step] = (node, rec, slot)

    async def _run_step_guarded(self, w, node: dict, slot: str, rec, answer):
        """One step, in a database session of its own (steps run side by side
        and an executor commits), under the run's model lock if it drives a
        model."""
        from core.database import SessionLocal

        step_db = SessionLocal()
        try:
            ctx = w.state.context()
            if self._node_needs_model(node):
                async with w.model_lock:
                    return await self._run_workflow_step(
                        w.task, w.name, node, step_db, slot, deliver=True, ctx=ctx,
                        answer=answer, walk=w, rec=rec)
            return await self._run_workflow_step(
                w.task, w.name, node, step_db, slot, deliver=True, ctx=ctx,
                answer=answer, walk=w, rec=rec)
        finally:
            step_db.close()

    def _finish_step(self, w, finished) -> None:
        """A step's coroutine ended: its record, its line, the arrows it fired
        — or, for a step that parked, its `waiting` record and (for a card)
        the question to the person."""
        from src import workflow_runs as wr
        from src.builtin_actions import (
            NODE_STATUS_DEFERRED, NODE_STATUS_ERROR, NODE_STATUS_SKIPPED,
            NodeResult, TaskDeferred, TaskNoop, TaskWaiting,
        )

        node, rec, slot = w.running.pop(finished)
        steps, model = self.run_steps(slot), self.run_model(slot)
        self._clear_run_state(slot)
        w.last_model = model or w.last_model
        label = node.get("label") or node["id"]
        try:
            done = finished.result()
        except TaskWaiting as parked:
            self._park_record(w, node, rec, parked, steps=steps, model=model)
            return
        except (TaskNoop, TaskDeferred) as signal:
            done = StepDone(NodeResult.from_signal(signal), None)
        except asyncio.CancelledError:
            done = StepDone(NodeResult(NODE_STATUS_ERROR, payload=NODE_STOPPED), None)
        except Exception as exc:
            logger.warning("Workflow '%s' step %r raised", w.name, label, exc_info=True)
            done = StepDone(NodeResult(NODE_STATUS_ERROR,
                                       payload=f"{type(exc).__name__}: {exc}"), None)
        res = done.result
        status, text = res.status, res.text or ""
        if status == NODE_STATUS_DEFERRED:
            status = NODE_STATUS_SKIPPED
            text = f"It asked to wait, so this branch ends here: {text}".rstrip(": ")
        self._end_record(w, node, rec, status=status, text=text,
                         data=None if isinstance(res.payload, str) else res.payload,
                         port=done.port, steps=steps, model=model)

    def _end_record(self, w, node: dict, rec, *, status: str, text: str, data,
                    port, steps=None, model=None) -> None:
        """Finish one step's own record, say so in the run's log, and name the
        arrows it fires. `port` is ALWAYS the outcome port now (`P22-11`): a
        port with no arrow ends that branch, and the Runs view lights only
        arrows that exist."""
        from src import workflow_runs as wr
        from src.builtin_actions import NODE_STATUS_ERROR, NODE_STATUS_SUCCESS

        if port is None:
            port = (EDGE_WHEN_SUCCESS if status == NODE_STATUS_SUCCESS
                    else EDGE_WHEN_ERROR if status == NODE_STATUS_ERROR else None)
        wr.record_node_end(w.db, rec, status=status, text=text, data=data,
                           error=text if status == NODE_STATUS_ERROR else None,
                           steps=steps, model=model, port=port, owner=w.task.owner)
        w.state.note_record(rec)
        w.state.note_live(node["id"], text=text, data=data)
        label = node.get("label") or node["id"]
        self._record_run_step(w.run_id, kind="node", node=node["id"], label=label,
                              status=status, detail=(text.splitlines() or [""])[0])
        for edge in w.state.outgoing(node["id"], port) if port else ():
            target = w.state.by_id.get(edge["to"]) or {}
            lead = ("Continued to" if port == EDGE_WHEN_SUCCESS
                    else "Failed, so continued to" if port == EDGE_WHEN_ERROR
                    else f"Went the “{_port_word(node, port)}” way, to")
            self._record_run_step(w.run_id, kind="progress",
                                  detail=f"{lead} {target.get('label') or edge['to']}")

    def _park_record(self, w, node: dict, rec, parked, *, steps=None, model=None) -> None:
        """A step raised `TaskWaiting`: its record waits, with what for. A card
        opens the run's one question and goes to the person as a
        notification — even with the workflow's notifications off: a
        question is not a report on an outcome (`SLICE-CD-DESIGN` § 1.5)."""
        from src import workflow_runs as wr

        parked = named_question(parked)
        detail = dict(parked.detail)
        waiting = {"kind": parked.kind, **detail}
        until = detail.get("until")
        if isinstance(until, (int, float)):
            waiting["until"] = datetime.fromtimestamp(
                until, tz=timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        resume_at = None
        if parked.kind == wr.WAITING_TIME:
            resume_at = wr._parse_iso(waiting.get("until"))
        wr.record_node_waiting(w.db, rec, waiting=waiting, resume_at=resume_at,
                               steps=steps, model=model)
        w.state.note_record(rec)
        label = node.get("label") or node["id"]
        self._record_run_step(w.run_id, kind="node", node=node["id"], label=label,
                              status="waiting", detail=parked.sentence)
        if parked.kind == wr.WAITING_APPROVAL:
            w.question_open = True
            self._ask_the_person(w, node, rec, waiting)

    def _ask_the_person(self, w, node: dict, rec, waiting: dict) -> None:
        """`P22-17`. The card, in a notification with `review` (`B1006`'s
        key): which workflow, run, step and item, and the card itself."""
        card = waiting.get("card") if isinstance(waiting.get("card"), dict) else {}
        tool = (waiting.get("tool_label") or waiting.get("tool")
                or (card.get("action") or {}).get("tool") or "an action")
        label = node.get("label") or node["id"]
        item = waiting.get("item")
        where = f"“{label}”" + (f", item {int(item) + 1}," if isinstance(item, int) else "")
        # `label`, `workflow` and `since` are what the question's notice says
        # ("“Overnight replies” is waiting for your yes: “Send reply” wants to
        # use send_reply. Waiting since 07:00."), the same three the waiting
        # list carries (`workflow_store.waiting_list`) — `integrate-d`: without
        # them the notice said "A step wants to use …".
        from src import workflow_runs as wr
        since = waiting.get("since") or ((wr.waiting_of(rec) or {}).get("since")
                                         if rec is not None else None)
        self.add_notification(
            w.task.name, "waiting", w.task.id, owner=w.task.owner,
            body=f"{where} is waiting for your yes: {tool}.",
            review={"kind": "workflow_approval", "workflow_id": w.wf.id,
                    "workflow": w.name, "run_id": w.run_id, "node_id": node["id"],
                    "item": item, "label": label, "since": since,
                    "tool_label": waiting.get("tool_label") or None,
                    "approval": card or None})

    def _start_wait(self, w, node: dict) -> None:
        """A Wait step: its record waits until its time (`P22-11`), or is over
        at once when the time has come."""
        from src import workflow_runs as wr
        from src.builtin_actions import NODE_STATUS_ERROR, NODE_STATUS_SUCCESS

        rec = wr.record_node_start(
            w.db, run_id=w.run_id, node=node, seq=w.state.next_seq(),
            input_envelope=self._handed(w, node), workflow_version=w.version,
            owner=w.task.owner)
        w.state.note_record(rec)
        w.started.add(node["id"])
        until, problem = self._wait_until(w, node)
        if problem:
            self._end_record(w, node, rec, status=NODE_STATUS_ERROR, text=problem,
                             data=None, port=None)
            return
        if until <= _utcnow():
            self._end_record(w, node, rec, status=NODE_STATUS_SUCCESS,
                             text=f"Waited until {self._clock_words(w, until)}.",
                             data=self._wait_passes_on(w, node), port=None)
            return
        wr.record_node_waiting(w.db, rec, waiting={
            "kind": wr.WAITING_TIME, "until": until.isoformat() + "Z"}, resume_at=until)
        w.state.note_record(rec)
        w.timers[node["id"]] = (node, rec, until)
        self._record_run_step(w.run_id, kind="node", node=node["id"],
                              label=node.get("label") or node["id"], status="waiting",
                              detail=(f"Waiting until {self._clock_words(w, until)}, or as "
                                      f"soon after as Pantheon is idle"))

    def _wait_passes_on(self, w, node: dict):
        """A Wait makes nothing; it hands on what it was handed — the `data`
        of the step that led to it (or the trigger's) — so "merge, wait, brief
        me" briefs on the merge. Read from the state, so after a restart it is
        the record the first process wrote."""
        for source in w.state.arrived_from(node["id"]):
            if source == w.state.start:
                return (w.state.trigger or {}).get("data") if isinstance(w.state.trigger, dict) else None
            out = w.state.output_of(source)
            if out is not None:
                return out.get("data")
        return None

    def _wait_until(self, w, node: dict) -> tuple:
        """`(until, problem)` — when a Wait is over, as UTC, or why it cannot
        wait. `{mode: "for", minutes}` or `{mode: "until", time: "HH:MM",
        tz}`; the trigger's time zone when `tz` is unset; at most
        `workflow_wait_max_hours`. Every Wait field is the author's (`never`)."""
        from src import workflow_runs as wr

        config = node.get("config") or {}
        mode = config.get("mode") or "for"
        now = _utcnow()
        cap = wr.wait_max_hours()
        if mode == "until":
            raw = str(config.get("time") or "")
            try:
                hour, minute = (int(part) for part in raw.split(":", 1))
                if not (0 <= hour < 24 and 0 <= minute < 60):
                    raise ValueError(raw)
            except ValueError:
                return None, f"“{node.get('label')}” has no time to wait until (HH:MM)."
            tz_name = valid_timezone(config.get("tz")) or _resolve_task_timezone(w.db, w.task)
            try:
                from zoneinfo import ZoneInfo
                zone = ZoneInfo(tz_name) if tz_name else timezone.utc
            except Exception:
                zone = timezone.utc
            local_now = now.replace(tzinfo=timezone.utc).astimezone(zone)
            target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= local_now:
                target = target + timedelta(days=1)
            until = target.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            minutes = config.get("minutes")
            if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes < 0:
                return None, f"“{node.get('label')}” has no number of minutes to wait."
            until = now + timedelta(minutes=float(minutes))
        if until - now > timedelta(hours=cap):
            return None, (f"“{node.get('label')}” would wait longer than {cap} hours, "
                          f"which workflow_wait_max_hours allows.")
        return until, None

    def _clock_words(self, w, when) -> str:
        from src import workflow_runs as wr
        return wr._clock(when, _resolve_task_timezone(w.db, w.task))

    def _fire_due_timers(self, w) -> bool:
        """End every Wait whose time has come. Answers whether any did."""
        from src.builtin_actions import NODE_STATUS_SUCCESS

        now = _utcnow()
        fired = False
        for node_id, (node, rec, until) in list(w.timers.items()):
            if until <= now:
                del w.timers[node_id]
                self._end_record(w, node, rec, status=NODE_STATUS_SUCCESS,
                                 text=f"Waited until {self._clock_words(w, until)}.",
                                 data=self._wait_passes_on(w, node), port=None)
                fired = True
        return fired

    def _seconds_to_next_timer(self, w):
        if not w.timers:
            return None
        soonest = min(until for _n, _r, until in w.timers.values())
        return max(0.05, (soonest - _utcnow()).total_seconds())

    def _finish_merge(self, w, node: dict) -> None:
        """A Merge: `{inputs, missing}` in arrival order, at once."""
        from src import workflow_runs as wr
        from src.builtin_actions import NODE_STATUS_SUCCESS

        rec = wr.record_node_start(
            w.db, run_id=w.run_id, node=node, seq=w.state.next_seq(),
            input_envelope=None, workflow_version=w.version, owner=w.task.owner)
        w.state.note_record(rec)
        w.started.add(node["id"])
        data = w.state.merge_output(node["id"])
        n_in, n_out = len(data["inputs"]), len(data["missing"])
        text = f"{n_in} arrived" + (f"; {n_out} did not: " + ", ".join(
            f"“{(w.state.by_id.get(m['from']) or {}).get('label') or m['from']}” ({m['why']})"
            for m in data["missing"]) if n_out else "") + "."
        self._end_record(w, node, rec, status=NODE_STATUS_SUCCESS, text=text, data=data,
                         port=None)

    def _apply_resume(self, w, answer) -> list:
        """A resumed run: what each waiting record waited for has come, or
        not. Answers the steps to run again — `(node, record, verdict)`.

          * a Wait whose time has come is over; one still ahead waits on;
          * a step a takeover stopped runs again (and only it — finished steps
            are kept, `SLICE-CD-DESIGN` § 1.4);
          * a card: the person's answer (Allow resumes the step ONCE, with the
            consumed approval; Deny takes its failure port); a card the store
            no longer holds lapsed, or Pantheon restarted — the failure port,
            saying which. A card still pending keeps the run's one question
            open."""
        from src import workflow_document as wd
        from src import workflow_runs as wr
        from src.builtin_actions import NODE_STATUS_ERROR

        reruns = []
        now = _utcnow()
        for rec in list(w.state.waiting()):
            if rec.item is not None:
                continue            # an item is its For-each step's business
            node = w.state.by_id.get(rec.node_id)
            waiting = wr.waiting_of(rec) or {}
            kind = waiting.get("kind")
            w.started.add(rec.node_id)
            if node is None:
                wr.end_waiting_records(w.db, w.run_id, status="error",
                                       error="This step is not in the version this run started with.")
                continue
            if kind == wr.WAITING_TIME:
                if node.get("kind") == wd.NODE_KIND_WAIT:
                    w.timers[rec.node_id] = (node, rec, rec.resume_at or now)
                else:
                    reruns.append((node, rec, None))
            elif kind == wr.WAITING_IDLE:
                self._record_run_step(
                    w.run_id, kind="progress",
                    detail=(f"“{node.get('label')}” runs again: Pantheon became active "
                            f"while it ran, so it was stopped and waited"))
                reruns.append((node, rec, None))
            elif kind == wr.WAITING_APPROVAL:
                verdict = self._approval_verdict(w, rec, waiting, answer, now=now)
                if verdict is None:
                    w.question_open = True
                elif verdict.decision == ANSWER_ALLOW or node.get("kind") == wd.NODE_KIND_FOREACH:
                    reruns.append((node, rec, verdict))
                else:
                    # `B1110`. Said once on the run — by `_end_record`'s line
                    # for this step — and once in the step's own log, here.
                    steps = list(json.loads(rec.steps)) if rec.steps else []
                    steps.append(shape_run_step({"kind": "progress", "detail": verdict.sentence}))
                    self._end_record(w, node, rec, status=NODE_STATUS_ERROR,
                                     text=verdict.sentence, data=None, port=None,
                                     steps=steps, model=rec.model)
        self._fire_due_timers(w)
        return reruns

    def _approval_verdict(self, w, rec, waiting: dict, answer, *, now=None):
        """The answer for this waiting card, or `None` while it is still open."""
        from src.tool_approvals import tool_approval_store

        item = waiting.get("item") if isinstance(waiting.get("item"), int) else None
        if (answer is not None and answer.node_id == rec.node_id
                and answer.item == item):
            return answer
        approval_id = waiting.get("approval_id")
        if approval_id and tool_approval_store.peek(approval_id) is not None:
            return None
        from src import workflow_runs as wr
        until = wr._parse_iso(waiting.get("until"))
        tool = waiting.get("tool_label") or waiting.get("tool") or "the action"
        if until is not None and (now or _utcnow()) >= until:
            sentence = (f"Nobody answered by {self._clock_words(w, until)} — {tool} was "
                        f"not done.")
            return StepAnswer(rec.node_id, item, ANSWER_LAPSED, sentence)
        since = wr._parse_iso(waiting.get("since"))
        started = getattr(self, "_started_at", None)
        if since is not None and started is not None and since >= started:
            # Gone early, in this process: not a restart, and not a lapse
            # (`Law 10` — the sentence says which). `B1103`: a message typed
            # into the step's chat no longer does this (the card is
            # `held_by_run`); what still can is the store's size cap, which
            # drops its oldest card when it is full. The sentence says what
            # is known — it left early — and no reason it cannot be sure of.
            return StepAnswer(rec.node_id, item, ANSWER_WITHDRAWN, (
                f"The question was withdrawn before anyone answered, so {tool} was "
                f"not done."))
        return StepAnswer(rec.node_id, item, ANSWER_RESTARTED,
                          f"Pantheon restarted before you answered — {tool} was not done.")

    async def _stop_steps(self, w) -> None:
        """The run was cancelled — Stop, the time limit, or Pantheon becoming
        active. Every step in flight is stopped and its record says so: a
        takeover leaves it `waiting {kind: idle}`, to run again when Pantheon
        is idle (finished steps kept); anything else `aborted`."""
        from src import workflow_runs as wr

        takeover = self._is_takeover(w.run_id)
        for step in list(w.running):
            step.cancel()
        for step in list(w.running):
            try:
                await step
            except BaseException:
                # Each step was just cancelled; how it ended is written below,
                # as its record (`waiting {kind: idle}` or `aborted`).
                pass
        for step, (node, rec, slot) in list(w.running.items()):
            steps, model = self.run_steps(slot), self.run_model(slot)
            self._clear_run_state(slot)
            label = node.get("label") or node["id"]
            if takeover:
                wr.record_node_waiting(w.db, rec, waiting={"kind": wr.WAITING_IDLE},
                                       steps=steps, model=model)
                self._record_run_step(w.run_id, kind="node", node=node["id"], label=label,
                                      status="waiting",
                                      detail="Stopped because Pantheon became active; it "
                                             "runs again once Pantheon is idle")
            else:
                wr.record_node_end(w.db, rec, status="aborted", error=NODE_STOPPED,
                                   steps=steps, model=model, owner=w.task.owner)
                self._record_run_step(w.run_id, kind="node", node=node["id"], label=label,
                                      status="aborted", detail=NODE_STOPPED)
        w.running.clear()

    def _is_takeover(self, run_id: str) -> bool:
        """Was this run stopped because a person started using Pantheon?"""
        if (self._runs().get(run_id) or {}).get("takeover"):
            return True
        return self._stopped_as(run_id) == FOREGROUND_TAKEOVER

    def _park_signal(self, w, waiting) -> BaseException:
        """The run parks: one sentence for its row ("Waiting for your yes on
        “Send reply”" / "Waiting until 08:00" / "Waiting for Pantheon to be
        idle"), a card first."""
        from src import workflow_runs as wr
        from src.builtin_actions import TaskWaiting

        order = {wr.WAITING_APPROVAL: 0, wr.WAITING_TIME: 1, wr.WAITING_IDLE: 2}
        ranked = sorted(waiting, key=lambda r: (order.get((wr.waiting_of(r) or {}).get("kind"), 3),
                                                r.seq or 0))
        first = ranked[0]
        kind = (wr.waiting_of(first) or {}).get("kind") or wr.WAITING_IDLE
        label = first.label or first.node_id
        if kind == wr.WAITING_APPROVAL:
            sentence = f"Waiting for your yes on “{label}”"
        elif kind == wr.WAITING_TIME:
            sentence = f"Waiting until {self._clock_words(w, first.resume_at)}"
        else:
            sentence = "Waiting for Pantheon to be idle"
        return TaskWaiting(sentence, kind=kind)

    def _run_outcome(self, w):
        """`RunState.outcome` as the walker's `NodeResult`. A failed run's
        `error` names the step (and item) that failed — on the run's slot,
        which `_execute_task_locked` writes as the row's `error`."""
        from src.builtin_actions import (
            NODE_STATUS_ERROR, NODE_STATUS_SKIPPED, NODE_STATUS_SUCCESS, NodeResult,
        )

        status, text, failed = w.state.outcome()
        if status is None:
            return NodeResult(NODE_STATUS_ERROR, payload=WORKFLOW_DOCUMENT_MISSING)
        if status == NODE_STATUS_ERROR:
            label = failed.label or failed.node_id
            self._state_for(w.run_id)["run_error"] = (
                f"“{label}” failed: {failed.error or text}")[:2000]
            return NodeResult(NODE_STATUS_ERROR, payload=text or failed.error or "")
        if status == NODE_STATUS_SKIPPED:
            return NodeResult(NODE_STATUS_SKIPPED, payload=text)
        last = w.state.finish_order[-1] if w.state.finish_order else None
        out = w.state.output_of(last) if last else None
        data = (out or {}).get("data")
        return NodeResult(NODE_STATUS_SUCCESS, payload=data if data is not None else text,
                          text=text)

    async def _run_workflow_step(self, task, workflow_name: str, node: dict, db, slot: str, *,
                                 deliver: bool, ctx: dict, answer=None, walk=None, rec=None,
                                 may_wait: bool = True):
        """Run one step of any kind under `slot`. Answers a `StepDone` — the
        step's `NodeResult` and, for a logic step, the port it chose. Raises
        `TaskWaiting` when the step parks (never for a step test,
        `may_wait=False`).

        `ctx` is the pure-JSON context references read (`workflow_refs`). The
        Slice B kinds run as they did (`_run_workflow_node`); what is new is
        that a value a step reads by reference reaches it only through a
        `value` slot — named and carried untrusted for a model step, placed as a
        JSON value for an authored call — never spliced into what it does.
        """
        from src import workflow_document as wd
        from src.builtin_actions import NODE_STATUS_ERROR, NodeResult

        kind = node.get("kind")
        if kind in (wd.NODE_KIND_IF, wd.NODE_KIND_SWITCH):
            from src import workflow_logic as wl
            port = wl.choose_port(node, ctx)
            word = _port_word(node, port)
            text = (f"Went the “{word}” way." if port != wd.PORT_OTHERWISE
                    else "None of its conditions held, so it went the “otherwise” way.")
            self._record_run_step(slot, kind="progress", detail=text)
            return StepDone(NodeResult("success", payload={"port": port}, text=text), port)
        if kind == wd.NODE_KIND_SET:
            from src import workflow_logic as wl
            data, missing = wl.build_set(node, ctx)
            text = "Set " + ", ".join(f"“{k}”" for k in (data or {})) + "."
            if missing:
                text += " Not found, so left empty: " + ", ".join(str(m) for m in missing) + "."
            return StepDone(NodeResult("success", payload=data or {}, text=text), None)
        if kind == wd.NODE_KIND_MERGE:
            data = walk.state.merge_output(node["id"]) if walk is not None else {"inputs": [], "missing": []}
            return StepDone(NodeResult("success", payload=data,
                                       text=f"{len(data['inputs'])} arrived."), None)
        if kind == wd.NODE_KIND_WAIT:
            return StepDone(NodeResult("success", payload=None,
                                       text="A Wait is not tested; in a run it waits."), None)
        if kind == wd.NODE_KIND_FOREACH:
            return await self._run_foreach(task, workflow_name, node, db, slot, ctx=ctx,
                                           answer=answer, walk=walk, deliver=deliver,
                                           may_wait=may_wait)
        if kind in (wd.NODE_KIND_HTTP, wd.NODE_KIND_MCP, wd.NODE_KIND_CODE):
            return await self._run_authored_step(task, node, slot, ctx=ctx, answer=answer,
                                                 may_wait=may_wait)
        if kind in (wd.NODE_KIND_PROMPT, wd.NODE_KIND_SKILL):
            return await self._run_model_step(task, workflow_name, node, db, slot, ctx=ctx,
                                              answer=answer, deliver=deliver, may_wait=may_wait)
        if kind == wd.NODE_KIND_RESEARCH:
            prompt = (node.get("config") or {}).get("prompt") or ""
            if "{{" in prompt:
                # `P22-09`. A Research step's question is a value slot carried
                # inline (`NODE_SLOTS`): it becomes the search, not an order.
                from src import workflow_refs as refs
                prompt, missing = refs.render_text(refs.parse_template(prompt), ctx)
                if missing:
                    return StepDone(NodeResult(NODE_STATUS_ERROR, payload=self._missing_words(
                        node, missing, walk)), None)
                node = dict(node, config=dict(node.get("config") or {}, prompt=prompt))
        res = await self._run_workflow_node(task, workflow_name, node, db, slot, deliver=deliver)
        return StepDone(res, None)

    def _missing_words(self, node: dict, missing, walk=None) -> str:
        """Why a step could not read what it refers to. A record cut past
        `workflow_node_record_max_chars` after a resume is named so."""
        names = ", ".join(str(m) for m in (missing or ()))
        cut = []
        if walk is not None:
            cut = [n for n in walk.state.own if walk.state.truncated(n)]
        tail = (" A step it reads was kept only in part (workflow_node_record_max_chars), "
                "so after a pause its value is not there." if cut else "")
        return f"“{node.get('label')}” refers to something that is not there: {names}.{tail}"

    async def _run_model_step(self, task, workflow_name: str, node: dict, db, slot: str, *,
                              ctx: dict, answer, deliver: bool, may_wait: bool):
        """A Prompt (AI) or Skill step — the steps a model drives, gated exactly
        as today (`D-2026-10-01-05` §4).

          * `P22-09`: a reference in the prompt becomes a named slot —
            "Summarise the issue titled [title]." — and the values travel in
            their own untrusted block (`untrusted_context_message`, the gate
            armed), clipped as a trigger payload is (`clip_field`).
          * `P22-15`: a Skill step follows the skill read at run time, wrapped
            as the skill tester wraps it, with skills not injected again.
          * `P22-16`: `tools` limits what it may call; `answer_fields` asks for
            JSON and checks it after the run.
          * `P22-17`: in a real run it may park on a card (`may_wait`), and an
            Allow comes back as the consumed approval the loop replays once.
        """
        from src import workflow_document as wd
        from src.builtin_actions import NODE_STATUS_ERROR, NODE_STATUS_SUCCESS, NodeResult
        from src.event_bus import TRIGGER_FIELD_MAX_CHARS, TRIGGER_MAX_CHARS, clip_field

        config = dict(node.get("config") or {})
        state = self._state_for(slot)
        extra = list(state.get("context_messages") or ())
        if node.get("kind") == wd.NODE_KIND_SKILL:
            from src import workflow_effects as we
            try:
                messages, line = we.skill_context(task.owner, config.get("skill"))
            except we.StepRefused as refused:
                return StepDone(NodeResult(NODE_STATUS_ERROR, payload=str(
                    getattr(refused, "sentence", None) or refused)), None)
            extra.extend(messages or ())
            state["suppress_skills"] = True
            if line:
                self._record_run_step(slot, kind="progress", detail=line)
        prompt = config.get("prompt") or ""
        if "{{" in prompt:
            from src import workflow_refs as refs
            from src.prompt_security import untrusted_context_message
            prompt, named = refs.render_named_slots(refs.parse_template(prompt), ctx)
            missing = [ref for _slot, ref, value in named if value is refs.MISSING]
            if missing:
                return StepDone(NodeResult(NODE_STATUS_ERROR, payload=self._missing_words(
                    node, missing, None)), None)
            lines = []
            for slot_name, _ref, value in named:
                shown = value if isinstance(value, str) else json.dumps(value, default=str)
                lines.append(f"[{slot_name}] = {clip_field(shown, TRIGGER_FIELD_MAX_CHARS)}")
            body = "\n".join(lines)
            if len(body) > TRIGGER_MAX_CHARS:
                body = body[:TRIGGER_MAX_CHARS].rstrip() + "\n… (truncated)"
            extra.append(untrusted_context_message(
                "values this step was handed", body,
                provenance_origin="external", arm_tool_gate=True))
        fields = config.get("answer_fields") or None
        if fields:
            from src import workflow_effects as we
            prompt = f"{prompt}\n\n{we.answer_instruction(fields)}"
        if config.get("tools") is not None:
            state["allowed_tools"] = list(config.get("tools") or ())
        state["context_messages"] = extra
        state["may_wait"] = bool(may_wait)
        if answer is not None and answer.decision == ANSWER_ALLOW:
            state["exact_approval"] = answer.exact_approval
        as_prompt = {**node, "kind": wd.NODE_KIND_PROMPT, "config": {
            k: v for k, v in config.items()
            if k in wd.NODE_CONFIG_FIELDS[wd.NODE_KIND_PROMPT]}}
        as_prompt["config"]["prompt"] = prompt

        def check_answer(res):
            if not fields or not res.ok:
                return res
            from src import workflow_effects as we
            data, problem = we.parse_answer(res.text, fields)
            if problem:
                return NodeResult(NODE_STATUS_ERROR,
                                  payload=f"The answer was not in the shape asked for: {problem}")
            return NodeResult(NODE_STATUS_SUCCESS, payload=data, text=res.text)

        res = await self._run_workflow_node(task, workflow_name, as_prompt, db, slot,
                                            deliver=deliver, after=check_answer)
        return StepDone(res, None)

    async def _run_foreach(self, task, workflow_name: str, node: dict, db, slot: str, *,
                           ctx: dict, answer, walk, deliver: bool, may_wait: bool):
        """`P22-12`. One step, run for each item of a referenced list, IN ORDER,
        each item with its own record (`item = i`, "Summarise · item 3 of 5")
        and its own slot. The step's own record holds `{items, worked,
        failed}`; any item that failed sends it out by `error`, naming it.
        Over `workflow_foreach_max_items` it is refused with that name — nothing
        is cut silently. A resumed run does not run a finished item again."""
        from src import workflow_refs as refs
        from src import workflow_runs as wr
        from src.builtin_actions import (
            NODE_STATUS_ERROR, NODE_STATUS_SUCCESS, NodeResult, TaskDeferred, TaskNoop,
            TaskWaiting,
        )

        config = node.get("config") or {}
        inner = config.get("step") if isinstance(config.get("step"), dict) else {}
        on_error = "stop" if config.get("on_error") == "stop" else "continue"
        source = config.get("list")
        template = refs.parse_template(source) if isinstance(source, str) else source
        value, missing = refs.render_value(template, ctx)
        label = node.get("label") or node["id"]
        if missing or value is refs.MISSING:
            return StepDone(NodeResult(NODE_STATUS_ERROR, payload=self._missing_words(
                node, missing or [source], walk)), None)
        if not isinstance(value, list):
            return StepDone(NodeResult(NODE_STATUS_ERROR, payload=(
                f"“{label}” was handed {type(value).__name__}, not a list, so there was "
                f"nothing to go through.")), None)
        cap = wr.foreach_max_items(task.owner)
        total = len(value)
        if total > cap:
            return StepDone(NodeResult(NODE_STATUS_ERROR, payload=(
                f"“{label}” was handed {total} items; workflow_foreach_max_items allows "
                f"{cap}. Nothing was run.")), None)
        inner_label = inner.get("label") or label
        done_items = (walk.state.items.get(node["id"]) if walk is not None else None) or {}
        results = []
        for index, item in enumerate(value):
            item_label = f"{inner_label} · item {index + 1} of {total}"
            item_node = {"id": node["id"], "kind": inner.get("kind"), "label": item_label,
                         "config": dict(inner.get("config") or {})}
            prev = done_items.get(index)
            if prev is not None and prev.status in wr.STEP_FINISHED:
                out = wr._loads(prev.output) or {}
                if wr.is_truncated(out):
                    out = {}
                results.append({"index": index, "status": prev.status,
                                "text": (out.get("text") if isinstance(out, dict) else "") or
                                        (prev.error or ""),
                                "data": out.get("data") if isinstance(out, dict) else None})
                if prev.status == NODE_STATUS_ERROR and on_error == "stop":
                    break
                continue
            handed = _build_task_handoff(
                task_name=f"{label} · item {index + 1} of {total}", task_id=task.id,
                run_id=run_of_slot(slot), status="success",
                result=item if isinstance(item, str) else json.dumps(item, default=str),
                payload=None if isinstance(item, str) else item)
            item_answer = None
            if prev is not None and prev.status == "waiting":
                wr.record_node_resumed(walk.db if walk is not None else db, prev)
                rec = prev
                if answer is not None and answer.item == index:
                    item_answer = answer
                    if answer.decision != ANSWER_ALLOW:
                        # `B1110`. The step's log already says the answer: the
                        # resumed step's first line is it (`_start_step`).
                        wr.record_node_end(walk.db if walk is not None else db, rec,
                                           status=NODE_STATUS_ERROR, text=answer.sentence,
                                           error=answer.sentence, port=EDGE_WHEN_ERROR,
                                           owner=task.owner)
                        results.append({"index": index, "status": NODE_STATUS_ERROR,
                                        "text": answer.sentence, "data": None})
                        if on_error == "stop":
                            break
                        continue
            elif walk is not None:
                rec = wr.record_node_start(
                    walk.db, run_id=walk.run_id, node=item_node, seq=walk.state.next_seq(),
                    input_envelope=handed, workflow_version=walk.version,
                    owner=task.owner, item=index, label=item_label)
            else:
                rec = None
            if rec is not None and walk is not None:
                walk.state.note_record(rec)
            item_slot = node_slot(run_of_slot(slot), f"{node['id']}#{index}")
            parent = self._runs().get(slot) or {}
            self._state_for(item_slot).update(
                trigger=handed, started_by=parent.get("started_by") or STARTED_BY_BACKGROUND,
                waits_for=parent.get("waits_for", "idle"))
            item_ctx = dict(ctx)
            item_ctx["item"] = json.loads(json.dumps(item, default=str))
            try:
                done = await self._run_workflow_step(
                    task, workflow_name, item_node, db, item_slot, deliver=deliver,
                    ctx=item_ctx, answer=item_answer, walk=None, may_wait=may_wait)
                res = done.result
            except TaskWaiting as parked:
                parked = named_question(parked)
                steps, model = self.run_steps(item_slot), self.run_model(item_slot)
                self._clear_run_state(item_slot)
                if rec is not None and walk is not None:
                    detail = dict(parked.detail)
                    until = detail.get("until")
                    if isinstance(until, (int, float)):
                        detail["until"] = datetime.fromtimestamp(
                            until, tz=timezone.utc).replace(tzinfo=None).isoformat() + "Z"
                    wr.record_node_waiting(walk.db, rec, waiting={"kind": parked.kind, **detail},
                                           steps=steps, model=model)
                raise TaskWaiting(f"{parked.sentence} (item {index + 1} of {total})",
                                  kind=parked.kind, item=index, **parked.detail)
            except (TaskNoop, TaskDeferred) as signal:
                res = NodeResult.from_signal(signal)
            except Exception as exc:
                res = NodeResult(NODE_STATUS_ERROR, payload=f"{type(exc).__name__}: {exc}")
            steps, model = self.run_steps(item_slot), self.run_model(item_slot)
            self._clear_run_state(item_slot)
            status = res.status if res.status in (NODE_STATUS_SUCCESS, NODE_STATUS_ERROR) else "skipped"
            text = res.text or ""
            data = None if isinstance(res.payload, str) else res.payload
            if rec is not None and walk is not None:
                wr.record_node_end(walk.db, rec, status=status, text=text, data=data,
                                   error=text if status == NODE_STATUS_ERROR else None,
                                   steps=steps, model=model,
                                   port=(EDGE_WHEN_SUCCESS if status == NODE_STATUS_SUCCESS
                                         else EDGE_WHEN_ERROR if status == NODE_STATUS_ERROR
                                         else None),
                                   owner=task.owner)
            self._record_run_step(slot, kind="progress",
                                  detail=f"Item {index + 1} of {total}: {status}")
            results.append({"index": index, "status": status, "text": text, "data": data})
            if status == NODE_STATUS_ERROR and on_error == "stop":
                break
        failed = [r for r in results if r["status"] == NODE_STATUS_ERROR]
        worked = sum(1 for r in results if r["status"] == NODE_STATUS_SUCCESS)
        data = {"items": results, "worked": worked, "failed": len(failed)}
        if failed:
            first = failed[0]
            text = f"Item {first['index'] + 1} of {total} failed: {first['text']}"
            return StepDone(NodeResult(NODE_STATUS_ERROR, payload=data, text=text), None)
        return StepDone(NodeResult(NODE_STATUS_SUCCESS, payload=data,
                                   text=f"{worked} of {total} items worked."), None)

    async def _run_authored_step(self, task, node: dict, slot: str, *, ctx: dict, answer,
                                 may_wait: bool):
        """`P22-17`'s Run half — an HTTP, MCP or Code step: the AUTHOR's
        decision, not a model's (`D-2026-10-01-05` §4).

        `workflow_slots.render_call` builds the call from the step's settings:
        every `never` slot (tool, destination, recipient, URL, host, command)
        copied verbatim as the author typed it — a reference found in one
        refuses the step before anything is dispatched — and outside data only
        in `value` slots, as JSON values. Its security context is
        `authored_call_context` (untainted, no standing approval, the owner's
        rung), and the gate is asked exactly as it is for any call: at the
        default rung the step runs with no card; at a stricter rung the person
        asked to be asked, so it parks on a headless card bound to this run,
        step and item, and an Allow replays exactly the sealed content once.
        The real dispatcher always runs (`execute_tool_block`, through
        `wf-effects`), so the admin gate, the disabled lists, event recording
        and taint observation all apply.
        """
        from src import workflow_document as wd
        from src import workflow_slots as ws
        from src.agent_loop import _resolve_allow_rule_lookup, apply_role_floor, resolve_trust_rung
        from src.builtin_actions import NODE_STATUS_ERROR, NODE_STATUS_SUCCESS, NodeResult, TaskWaiting
        from src.tool_capabilities import authored_call_context

        kind = node.get("kind")
        config = node.get("config") or {}
        run_id = run_of_slot(slot)
        item_part = slot.split(NODE_SLOT_SEPARATOR, 1)[-1] if NODE_SLOT_SEPARATOR in slot else node["id"]
        try:
            if kind == wd.NODE_KIND_CODE:
                # `render_call` fills the inputs (its content is the stdin
                # JSON: values coerced and capped, a reference in the language,
                # the source or the time limit refused before anything runs —
                # `integrate-d`: the walker filled them itself and skipped
                # both). The gate is then asked about the SOURCE, the author's
                # text verbatim, which is exactly what will run and what an
                # Allow seals (`_dispatch_authored` claims against it); the
                # values only ever arrive on stdin.
                rendered = ws.render_call(node, ctx)
                if rendered.missing:
                    return StepDone(NodeResult(NODE_STATUS_ERROR, payload=self._missing_words(
                        node, rendered.missing)), None)
                input_obj = json.loads(rendered.content)
                call = rendered._replace(content=str(config.get("source") or ""), missing=())
            else:
                mcp_schema = None
                if kind == wd.NODE_KIND_MCP:
                    from src import workflow_effects as we
                    resources = we.workflow_resources(task.owner)
                    tool = (getattr(resources, "mcp_tools", None) or {}).get(config.get("tool"))
                    if isinstance(tool, dict):
                        mcp_schema = tool.get("input_schema")
                    else:
                        mcp_schema = getattr(tool, "input_schema", None)
                call = ws.render_call(node, ctx, mcp_schema=mcp_schema)
        except ws.SlotError as refused:
            # Defence in depth: a document written straight to the database
            # with a reference in a `never` slot. Nothing is dispatched.
            sentence = str(getattr(refused, "sentence", None) or refused)
            self._record_run_step(slot, kind="progress", detail=f"Not run: {sentence}")
            return StepDone(NodeResult(NODE_STATUS_ERROR, payload=f"Not run: {sentence}"), None)
        if getattr(call, "missing", None):
            return StepDone(NodeResult(NODE_STATUS_ERROR, payload=self._missing_words(
                node, call.missing)), None)
        rung = apply_role_floor(resolve_trust_rung(), task.owner)
        context = authored_call_context(
            call, rung=rung, run_id=f"{run_id}:{item_part}",
            allow_rule_lookup=_resolve_allow_rule_lookup(task.owner, ""))
        exact = answer.exact_approval if (answer is not None and answer.decision == ANSWER_ALLOW) else None
        if exact is None:
            decision = context.decision_for(call.tool, call.content)
            if not decision.allowed:
                if not may_wait:
                    return StepDone(NodeResult(NODE_STATUS_ERROR, payload=(
                        f"Not tested: {decision.reason} A real run asks you first.")), None)
                raise self._headless_card(task, node, call, context, decision, run_id, item_part)
        else:
            self._record_run_step(slot, kind="progress", detail=answer.sentence)
        outcome = await self._dispatch_authored(
            task, node, call, context, exact,
            code_input=input_obj if kind == wd.NODE_KIND_CODE else None)
        status = getattr(outcome, "status", NODE_STATUS_ERROR)
        status = NODE_STATUS_SUCCESS if status == NODE_STATUS_SUCCESS else NODE_STATUS_ERROR
        text = getattr(outcome, "text", "") or ""
        data = getattr(outcome, "data", None)
        return StepDone(NodeResult(status, payload=data if data is not None else text,
                                   text=text), None)

    async def _dispatch_authored(self, task, node: dict, call, context, exact, *,
                                 code_input=None):
        """The step's executor — `wf-effects`' (`C-E`). HTTP and MCP go through
        the real dispatcher (`execute_tool_block`), which claims a replayed
        approval; Code runs in the person's workstation and claims its sealed
        approval here, against the exact source, before it runs."""
        from src import workflow_document as wd
        from src import workflow_effects as we
        from src.builtin_actions import NODE_STATUS_ERROR

        kind = node.get("kind")
        if kind == wd.NODE_KIND_CODE:
            if exact is not None and not exact.claim(owner=task.owner, session_id="",
                                                     tool_name=call.tool, content=call.content,
                                                     workspace=None):
                return we.StepOutcome(NODE_STATUS_ERROR,
                                      "The approval did not match this step's code, so it "
                                      "was not run.", None, None)
            return await we.run_code_step(node, dict(code_input or {}), owner=task.owner,
                                          timeout=None)
        runner = we.run_http_step if kind == wd.NODE_KIND_HTTP else we.run_mcp_step
        if exact is not None:
            return await runner(call, owner=task.owner, security_context=context,
                                exact_approval=exact)
        return await runner(call, owner=task.owner, security_context=context)

    def _headless_card(self, task, node: dict, call, context, decision, run_id: str,
                       item_part: str):
        """A strict rung asked, so a deterministic step parks on a card bound to
        nobody's chat (`session_id=""`) and to this run, step and item — the
        skill tester's convention, so branches never supersede each other.
        Its deadline is `workflow_approval_timeout_seconds`."""
        from src import workflow_runs as wr
        from src.builtin_actions import TaskWaiting
        from src.tool_approvals import tool_approval_store
        from src.tool_capabilities import capabilities_for_action

        pending = tool_approval_store.create(
            owner=task.owner, session_id="", origin_run_id=f"{run_id}:{item_part}",
            tool_name=call.tool, content=call.content, workspace=None,
            external_untrusted_context_seen=False,
            capabilities=capabilities_for_action(call.tool, call.content),
            gate_decision=decision, taint_trail=context.taint_trail,
            ttl_seconds=wr.workflow_approval_ttl_seconds(task.owner), held_by_run=True)
        card = pending.public_payload(reason=decision.reason)
        return TaskWaiting(
            f"Waiting for your yes on {call.tool}", kind=wr.WAITING_APPROVAL,
            approval_id=pending.approval_id, session_id="", tool=call.tool,
            reason=decision.reason, until=pending.expires_at, card=card,
            headless=True, content=call.content)

    async def _run_workflow_node(self, task, workflow_name: str, node: dict, db,
                                 slot: str, *, deliver: bool, after=None):
        """Run one step under `slot`. Answers a `NodeResult`.

        A Prompt step reads its input only through `trigger_context_message`
        (wrapped untrusted, the gate armed); a Research step does not read it
        (`B671`); an Action step never receives it — its parameters come from
        its own settings only (`P8-29`'s rule, `B806`'s constraint). With
        `deliver`, a step that worked and has an output setting is delivered
        through `_deliver_task_result`, as a task is; a delivery that raises
        makes the step `error`. `after` (`P22-16`) reads the result before it
        is delivered — an AI step's answer checked against its shape.
        """
        from src import workflow_document as wd
        from src.builtin_actions import NODE_STATUS_ERROR, NODE_STATUS_SUCCESS, NodeResult

        kind = node.get("kind")
        if kind == wd.NODE_KIND_RUN_TASK:
            return await self._run_task_node(task, node, slot)
        from src.builtin_actions import TaskWaiting

        stand_in = wd.node_stand_in(task, workflow_name, node)
        try:
            if kind == wd.NODE_KIND_ACTION:
                res = await self._execute_action(stand_in, run_id=slot)
            elif kind == wd.NODE_KIND_RESEARCH:
                text = await self._execute_research_task(stand_in, db, run_id=slot)
                res = NodeResult(NODE_STATUS_SUCCESS, payload=text)
            else:
                text = await self._execute_llm_task(stand_in, db, run_id=slot)
                res = NodeResult(NODE_STATUS_SUCCESS, payload=text)
        except TaskWaiting:
            # `P22-17`. A step that parks on a card keeps the chat it made on
            # the trigger FIRST: the card is sealed to that chat, and the step
            # that resumes after an Allow must run in it, or the seal refuses
            # the replay (as it should — found by the Allow test).
            self._keep_workflow_chat(db, task, stand_in, kind)
            raise
        self._keep_workflow_chat(db, task, stand_in, kind)
        if after is not None:
            res = after(res)
        if deliver and res.ok and stand_in.output_target:
            try:
                await self._deliver_node_result(task, stand_in, res.text, db,
                                                model=self.run_model(slot))
            except Exception as exc:
                return NodeResult(
                    NODE_STATUS_ERROR,
                    payload=(f"It worked, but the result could not be delivered: "
                             f"{type(exc).__name__}: {exc}"))
            self._keep_workflow_chat(db, task, stand_in, kind)
        return res

    def _keep_workflow_chat(self, db, task, stand_in, kind: str) -> None:
        """A Prompt or Action step that made the workflow's chat leaves it on
        the trigger, so the next step writes into the same "[Task] …" chat.
        A Research step's report keeps its own session (`node_stand_in`)."""
        from core.database import ScheduledTask
        from src import workflow_document as wd

        made = getattr(stand_in, "session_id", None)
        if kind == wd.NODE_KIND_RESEARCH or not made or getattr(task, "session_id", None):
            return
        try:
            db.query(ScheduledTask).filter(
                ScheduledTask.id == task.id, ScheduledTask.session_id.is_(None),
            ).update({ScheduledTask.session_id: made}, synchronize_session=False)
            db.commit()
            task.session_id = made
        except Exception:
            logger.debug("Could not keep workflow %s's chat", task.id, exc_info=True)

    async def _deliver_node_result(self, task, stand_in, text: str, db, model=None) -> None:
        """One step's delivery: `_deliver_task_result`, as a task's — and for
        `notification`, which that function leaves to the run's notification,
        the step's own notification with its result, under the trigger's own
        notification switch (a task with notifications off sends none)."""
        if (stand_in.output_target or "") == "notification":
            if getattr(task, "notifications_enabled", True):
                self.add_notification(stand_in.name, "success", task.id,
                                      owner=task.owner, body=text)
            return
        await self._deliver_task_result(stand_in, text, db, model=model)

    async def _run_task_node(self, task, node: dict, slot: str):
        """A Run task step: run the named task, as itself, and read its run.

        The target keeps its own run, its own history, its own delivery and its
        own chain. It is claimed as a chained step is (`_claim_chained`, so a
        busy target is said, not dropped), runs without taking the model slot
        (the workflow already holds one) and without registering its handle (so
        stopping the target cannot cancel the workflow, `register_handle`), and
        is handed this step's input as its own trigger, wrapped untrusted.
        """
        from core.database import SessionLocal, ScheduledTask, TaskRun
        from src.builtin_actions import (
            NODE_STATUS_ERROR, NODE_STATUS_SKIPPED, NODE_STATUS_SUCCESS, NodeResult,
        )
        from src import workflow_document as wd

        target_id = (node.get("config") or {}).get("task_id")
        lookup = SessionLocal()
        try:
            target = lookup.query(ScheduledTask).filter(ScheduledTask.id == target_id).first()
            label = target.name if target is not None else target_id
            usable = (target is not None and target.owner == task.owner
                      and (target.task_type or "llm") != wd.WORKFLOW_TASK_TYPE)
        finally:
            lookup.close()
        if not usable:
            return NodeResult(NODE_STATUS_ERROR,
                              payload="Did not run it: that task is gone, or is not one of yours.")
        if not self._claim_chained(target_id):
            return NodeResult(NODE_STATUS_ERROR,
                              payload=f"Did not run “{label}”: {CHAIN_ALREADY_RUNNING}")
        self._record_run_step(slot, kind="progress", detail=f"Running the task “{label}”")
        target_run = await self._execute_task(
            target_id, bypass_model_slot=True, trigger=self.run_trigger(slot),
            register_handle=False, started_by=self._run_started_by(slot))
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            # The target's run answers a cancel by recording it and returning
            # (its `CancelledError` branch does not re-raise), so a stop or a
            # time limit that landed while it ran arrives here as a return.
            # The workflow was stopped; it does not go on to its next step.
            raise asyncio.CancelledError()
        lookup = SessionLocal()
        try:
            row = lookup.query(TaskRun).filter(TaskRun.id == target_run).first()
            status = row.status if row is not None else None
            said = ((row.result or row.error) if row is not None else None) or ""
        finally:
            lookup.close()
        self._record_run_step(slot, kind="progress",
                              detail=f"“{label}” ended: {status or 'it asked to wait'}")
        if status == "success":
            return NodeResult(NODE_STATUS_SUCCESS, payload=said)
        if status == "skipped" or status is None:
            return NodeResult(NODE_STATUS_SKIPPED,
                              payload=said or f"“{label}” asked to wait, so it did not run now")
        if status == "aborted":
            return NodeResult(NODE_STATUS_ERROR,
                              payload=f"“{label}” was stopped before it finished: {said}".rstrip(": "))
        return NodeResult(NODE_STATUS_ERROR, payload=said or f"“{label}” failed")

    async def test_workflow_node(self, task, workflow_name: str, node: dict, *,
                                 input_envelope=None, timeout=None, graph=None) -> dict:
        """`P22-08` — run ONE step, now, with the input the person chose.

        Under a slot of its own (`test:<uuid>`) that no row has, so it writes
        no run and no step record; it delivers nothing, notifies nobody,
        continues to nothing and — inside `run_origin(test=True)` — wakes no
        task with anything it writes. It takes no model slot and waits for
        nothing (`waits_for` None): it is foreground work, like a chat reply,
        and the person is watching it. A Run task step really runs its task —
        which is why testing one asks first (`needs_test_confirmation`).

        Answers `{status, text, data, steps, model, took_ms, port}`; `status` is
        a node status (`success` / `error` / `skipped` / `deferred`). `P22-10`:
        every kind is tested, and `port` says which way a logic step went —
        references read the input chosen (as `start`) and, for the steps
        before it, their last real records (`graph`, the document it is in).
        A test never parks: a step that would ask for a yes says so instead.
        """
        from core.database import SessionLocal
        from src.builtin_actions import NODE_STATUS_ERROR, NodeResult
        from src.event_bus import run_origin

        slot = f"{TEST_SLOT_PREFIX}{NODE_SLOT_SEPARATOR}{uuid.uuid4()}"
        self._state_for(slot).update(trigger=input_envelope, started_by=STARTED_BY_PERSON,
                                     waits_for=None)
        budget = timeout or task_timeout_seconds(task) or 300
        started = time.monotonic()
        db = SessionLocal()
        try:
            ctx = self._test_context(db, task, graph, node, input_envelope)
            port = None
            with run_origin(task.id, workflow_name, slot, test=True):
                try:
                    done = await asyncio.wait_for(
                        self._run_workflow_step(task, workflow_name, node, db, slot,
                                                deliver=False, ctx=ctx, may_wait=False),
                        timeout=budget)
                    res, port = done.result, done.port
                except asyncio.TimeoutError:
                    res = NodeResult(NODE_STATUS_ERROR,
                                     payload=f"Timed out after {_human_gap(budget)}.")
                except Exception as exc:
                    res = NodeResult(NODE_STATUS_ERROR, payload=f"{type(exc).__name__}: {exc}")
            return {
                "status": res.status,
                "text": res.text,
                "data": None if isinstance(res.payload, str) else res.payload,
                "steps": self.run_steps(slot),
                "model": self.run_model(slot),
                "took_ms": _human_ms(time.monotonic() - started),
                "port": port or (EDGE_WHEN_SUCCESS if res.status == "success"
                                 else EDGE_WHEN_ERROR if res.status == "error" else None),
            }
        finally:
            self._clear_run_state(slot)
            db.close()

    def _test_context(self, db, task, graph, node: dict, input_envelope) -> dict:
        """What a tested step's references read: the chosen input as the start,
        and each other step's newest real record (`last_node_record` — never a
        dry plan)."""
        from src import workflow_runs as wr
        from src.event_bus import trigger_summary

        steps = {}
        for other in (graph or {}).get("nodes") or ():
            if other.get("id") == node.get("id"):
                continue
            rec = wr.last_node_record(db, task.id, other["id"])
            if rec is None or rec.status not in wr.STEP_FINISHED:
                continue
            out = wr._loads(rec.output)
            if not isinstance(out, dict) or wr.is_truncated(out):
                continue
            steps[other["id"]] = {"status": rec.status, "text": out.get("text") or "",
                                  "data": out.get("data")}
        envelope = input_envelope if isinstance(input_envelope, dict) else None
        steps[wr._start_key()] = {"status": "success",
                                  "data": (envelope or {}).get("data"),
                                  "text": trigger_summary(envelope) if envelope else ""}
        return {"steps": json.loads(json.dumps(steps, default=str))}

    async def _run_chained(self, task_id: str, *, handoff: dict | None = None,
                           started_by: str = STARTED_BY_BACKGROUND):
        """Run a chained task whose `_executing` claim is already held.

        `P22-01`. This used to take the claim itself, so an overlapping
        scheduler tick could not double-dispatch the task — and when the claim
        was already held it returned without a word, after `_advance_chain` had
        written "Continued to X". The claim is now taken by `_advance_chain`
        through `_claim_chained` before the line is chosen, and this runs only
        what that decided to run. The double-dispatch guard is the same set, the
        same check and the same release (`_execute_task`'s `finally`).

        `P8-29`. `handoff` is what the step before produced, in the `P8-23`
        envelope — so it arrives at the successor through the one channel a
        trigger payload already travels on, and `trigger_context_message` wraps
        it untrusted the way it wraps a webhook body. `None` is a chain with
        nothing to hand on, which is what every chain did before this row.

        `B1047`. `started_by` is the chain's: a step a person's Run now leads
        to waits as that run did.
        """
        await self._execute_task(task_id, trigger=handoff, started_by=started_by)

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

        `P22-01`. It walked `then_task_id` alone, while `_advance_chain` takes
        both edges, so a failure edge went round all three checks. It now asks
        `validate_graph` — the rule the save routes ask — about the rows a walk
        from here can reach. Nothing refused before is permitted (the success
        path is walked first, with the old checks in the old order); what is new
        is that a failure edge is walked too.
        """
        refusal = validate_graph(
            load_chain_rows(db, [start_id], max_depth=max_depth),
            starts=[start_id], owner=owner, max_depth=max_depth)
        return refusal.reason if refusal is not None else None

    def _has_chain_cycle(self, db, start_id: str, max_depth: int = CHAIN_MAX_DEPTH,
                         owner: str | None = None) -> bool:
        """Kept, with its old name and its old answer.

        `P22-01`, measured 2026-10-01: nothing in the product calls this any
        more — `_advance_chain` reads `_chain_refusal`'s reason — and tests
        do (`grep -rn "_has_chain_cycle(" tests/` for today's count, which is
        not copied here). It stays for them (`Law 1`), the same boolean over
        the same walk.
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
                           trigger: dict | None = None, dry: bool = False,
                           started_by: str = STARTED_BY_BACKGROUND):
        """Manually trigger a task execution.

        `P8-23`. `trigger` is what fired it — the event bus's envelope or the
        webhook's. `None` is a run nobody can name a cause for, which is every
        scheduled run and every button press, and those behave exactly as
        before.

        `P8-33`. `dry` produces a plan and executes nothing. It still takes the
        `_executing` claim, because a dry run and a real run of the same task
        overlapping is the same confusion `B674` is about and a dry run is not
        the place to decide that question.

        `P22-04` (`B803`). A dry run is **awaited** rather than spawned, and
        answers with the id of the run that holds the plan — a `str`, truthy,
        so every caller's `if not started` reads it unchanged; `False` still
        means "already running". The agent's `manage_tasks` asks "what would
        this do" and has to read the answer back in the same turn: a spawned
        dry run answered `True` before the plan existed. Awaiting it costs
        nothing a person waits on — the dry path takes neither the model slot
        nor the wait for Pantheon to go idle (`P8-33`), reaches no executor,
        and has no `await` between its first statement and its plan. A real
        run is spawned and answers `True`, exactly as before.

        `B1047`. `started_by` says who asked (`src.interactive_gate.STARTED_BY`).
        The default is background work — the event bus and the webhook call
        this — and the task route passes `STARTED_BY_PERSON` for its buttons.
        """
        if started_by not in STARTED_BY:
            raise ValueError(f"started_by must be one of {STARTED_BY}, not {started_by!r}")
        if not dry and self._record_parked_skip(task_id) is not None:
            # `B674`. A workflow whose run is parked runs once at a time: this
            # trigger is a `skipped` run that says why, and the caller is told
            # it did not start (the webhook keeps its 409, with those words —
            # `in_flight_sentence`). A dry run plans and touches nothing, so it
            # is not held.
            return False
        if force:
            coro = self._execute_task(
                task_id, bypass_model_slot=True, release_executing=False,
                trigger=trigger, dry=dry, started_by=started_by)
            if dry:
                return await coro
            asyncio.create_task(coro)
            return True
        async with self._executing_lock:
            if task_id in self._executing:
                return False
            self._executing.add(task_id)
        coro = self._execute_task(task_id, trigger=trigger, dry=dry,
                                  started_by=started_by)
        if dry:
            return await coro
        asyncio.create_task(coro)
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

        stopped = self._mark_run_aborted(task_id, message=STOPPED_BY_USER) or stopped
        return stopped

    async def stop_background_tasks_for_foreground(self, *, reason: str = "Pantheon became active") -> int:
        """Cancel all in-process scheduler tasks because the user is active.

        This is intentionally blunt for scheduled/background work: when the
        user opens or uses Pantheon, foreground interaction wins immediately.
        Manual force-runs can be restarted by the user; automatic jobs will be
        deferred by their cancellation path instead of stealing the app.

        `B1047`. Background work only. A run a person started (Run now, Start
        now, and the steps they chain into) is what that person is waiting
        for; the page they are waiting on — its own polls, its heartbeat — was
        stopping it within seconds, and recording it as "Stopped by user"
        (`_mark_run_aborted`'s default), so a run nobody stopped said its owner
        had. What this stops now says what happened: `FOREGROUND_TAKEOVER`.
        The row is written before the cancel lands, and the cancel branch keeps
        it (`_stopped_as`) — except a workflow run's (`B1138`): that one is
        parked, not ended, so its row is left to the cancel branch and the
        takeover is said in the run's slot (`_is_takeover`).

        `B1060`. Running background runs only. A QUEUED one waits for Pantheon
        to be idle before it takes the model slot (`_execute_task`), so it
        holds nothing and is left to wait; stopping it threw away its trigger —
        a webhook's body, an event, the step before it — because nothing could
        put it back. A running one is stopped, and its cancel branch puts it
        back in the queue with its trigger or says it will not be retried.
        """
        async with self._executing_lock:
            task_ids = list(self._executing)
        started_by = self._started_by_map()
        running = self._gate_stoppable_map()
        stopped = 0
        for task_id in task_ids:
            if started_by.get(task_id) == STARTED_BY_PERSON:
                continue
            run_id = running.get(task_id)
            if run_id is None:
                continue
            # `B1138`. Who stopped it is said in the run's own slot, which the
            # walker (`_stop_steps`) and the cancel branch read through
            # `_is_takeover`. Safe to write: a run still in `_gate_stoppable`
            # has not reached the `finally` that drops both, and nothing here
            # awaits.
            self._state_for(run_id)["takeover"] = True
            handle = self._task_handles.get(task_id)
            live = bool(handle and not handle.done())
            if live:
                handle.cancel()
                stopped += 1
            if live and self._task_type_of(task_id) == "workflow":
                # `B1138`. A workflow run is parked `waiting` by its cancel
                # branch (`P22-11`), so the row is left as it is until then:
                # written `aborted` first, as below, it read stopped — to a
                # poll, to Activity — for as long as the cancel took to land
                # (measured by `integrate-e`: `aborted`, then `success` a
                # minute later). If the run cannot park (switched off
                # meanwhile), the cancel branch ends it with these words.
                continue
            if self._mark_run_aborted(task_id, run_id=run_id, message=FOREGROUND_TAKEOVER):
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
