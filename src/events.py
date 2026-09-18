# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write one row per thing that happened, and keep the window finite.

`P14-01`. `core/database.py` stores `message_count`, `total_input_tokens` and
`total_output_tokens` as **running counters on a session row**. So Pantheon
knows what a conversation has cost in total, and cannot say what it cost on
Tuesday, whether one model is cheaper than another, or whether a change helped.
The time dimension was not hard to query — it was discarded at write.

This module is the write. Everything in `P14` reads from what it produces, and
`P12-08` needs it before it can ask an operator to set a limit it cannot show
them consuming.

THREE RULES, EACH ONE A WAY THIS KIND OF CODE USUALLY GOES WRONG.

**1. It must never break a chat.** Measuring is worth exactly nothing if the
thing being measured stops working. `record_llm_round` opens its own session,
swallows everything, and returns a bool nobody has to check — so a missing
table on an old database, a locked file, or a schema drift costs a row of
history and not a person's message. That is also why it does not share the
session `accumulate_token_usage` uses for its counters: a failed commit here
would otherwise roll back the counter update, and the counters worked before
this file existed.

**2. It must not write a credential.** The metrics dict carries `endpoint_label`
(a human name, e.g. "Local llama.cpp") and `endpoint_id`. It must never carry
the endpoint URL, because those can hold credentials in userinfo or query —
`core/log_safety.redact_url` exists for exactly that reason — and this table is
read by usage views and may be carried in a diagnostic bundle. Anything that
looks like a URL is redacted on the way in rather than trusted.

**3. The window is finite by default.** An append-only table with no ceiling is
a defect on somebody's home server, not a feature. `events_retention_days`
ships at 90; `0` means keep everything, and that is a choice someone makes, not
one they inherit. Pruning is time-gated in-process rather than scheduled,
following `rate_limiter.py`'s pattern — this product has no daily job runner and
adding one for a DELETE would be the larger change.

THE STORE IS SQLITE, AND THAT IS A DECISION WITH A MEASUREMENT BEHIND IT
(`P14-06`, `D-2026-09-18-01`).

`DEFERRED.md` D-05 makes the case for TimescaleDB — hypertables, compression,
continuous aggregates — and the decision is *not yet, and not by default*, on
numbers rather than taste. Measured on this schema, this machine, with
`usage_over_time` and `usage_summary` as they ship:

    90 days ×   200 events/day =  18,000 rows ·  11 MB · chart  13 ms
    90 days × 2,000 events/day = 180,000 rows ·  88 MB · chart  87 ms
   365 days × 2,000 events/day = 730,000 rows · 369 MB · chart 195 ms

A year of a **heavy** install draws its chart in under a fifth of a second on
the store that is already here, so a second database earns nothing today, and
`Law 16` is why a hosted one is not even on the table: a metrics backend nobody
linked is *phoning home*, whatever the vendor calls it. `store_status()` below
is what makes "fine until it is not" a reading rather than a feeling — the
decision names the thresholds, and `src/self_checks.py` puts them in front of
the operator instead of waiting for someone to notice.

**The one thing the measurement did fault was the prune**, and it is fixed here
rather than filed: deleting 550,000 expired rows took **7.3 seconds in one
statement**, on the thread that has just finished a person's chat turn. See
`prune_events`.
"""
import contextvars
import json
import logging
import re
import threading
import time
import uuid
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 90

# `P14-06`. The thresholds the decision named, in the code the decision is about.
#
# Both are row counts, because rows are what retention controls and bytes are
# what they imply: the measurement puts a row at ~506 bytes on disk with this
# schema's three indexes, so 500,000 rows is ~250 MB and a ~130 ms chart, and
# 2,000,000 is ~1 GB and a chart a person waits for. `watch` is "this is bigger
# than the shape it was designed for, look at your retention"; `over` is "the
# decision's own revisit condition has arrived".
#
# They are constants rather than settings on purpose: an operator tuning the
# number at which they are warned is tuning the warning, not the store.
STORE_WATCH_ROWS = 500_000
STORE_OVER_ROWS = 2_000_000
# Measured, not guessed — see the module docstring's table. Used only to turn a
# row count into a size an operator can picture; the real file size is reported
# beside it when the database is one we can stat.
MEASURED_BYTES_PER_ROW = 506

# Prune at most this often per process. Cheap enough to check on every write,
# rare enough that the DELETE is invisible.
_PRUNE_INTERVAL_SECONDS = 24 * 60 * 60
# `P14-06`. How much of one prune a person's turn may pay for.
#
# The prune runs inline, at the tail of `record_event`/`record_llm_round`, which
# is the thread that has just finished someone's chat turn. Measured: one
# `DELETE ... WHERE ts < cutoff` over 550,000 expired rows took **7.3 seconds**.
# Steady state is nothing like that — a day's worth is a couple of thousand rows
# and a few milliseconds — but the states that produce a backlog are ordinary:
# retention lowered from `0`, an install that has been off for a month, a first
# prune on a process that has been up for a day.
#
# So the DELETE is batched and time-boxed. What is left over is not forgotten:
# an unfinished prune rearms the interval gate (`_maybe_prune`) so the next
# write picks it up, and the backlog drains over a handful of turns instead of
# stalling one.
_PRUNE_BATCH_ROWS = 5_000
_PRUNE_BUDGET_SECONDS = 0.5
# None means "never pruned in this process", NOT "pruned at time zero".
#
# This was 0.0, and on Linux `time.monotonic()` counts from BOOT — so
# `now - 0.0 < 86400` is True for the first day of a machine's uptime and the
# gate returned early every time. A container starting on a freshly booted host
# would never prune, silently, and whether it pruned at all depended on how long
# the machine had been up. Exactly the class of default this project keeps
# finding: correct-looking, and load-bearing on something unrelated.
_last_prune: Optional[float] = None
_prune_lock = threading.Lock()
# `P14-06`. True when the last prune stopped on its time budget with expired
# rows still in the table. It defeats the 24-hour gate — an unfinished prune
# that then waits a day is a backlog that never drains — and nothing else reads
# it, so a failed prune (which returns 0 and sets nothing) is unaffected.
_prune_unfinished = False

_URLISH = re.compile(r"[a-z][a-z0-9+.-]*://", re.I)


def _safe_label(value: Any) -> Optional[str]:
    """A label, or nothing. Never a URL, and never something unbounded.

    A caller that hands us an endpoint URL instead of its label is a mistake we
    can absorb rather than store: redact it and keep the host. Silently writing
    `https://user:key@host/v1` into a table the usage views render would be the
    kind of leak nobody finds until it is on a screenshot.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    if not text:
        return None
    if _URLISH.search(text):
        try:
            from core.log_safety import redact_url
            text = redact_url(text) or "<endpoint>"
        except Exception:
            return "<endpoint>"
    return text[:200]


def _retention_days() -> int:
    try:
        from src.settings import get_setting
        value = int(get_setting("events_retention_days", DEFAULT_RETENTION_DAYS))
    except Exception:
        return DEFAULT_RETENTION_DAYS
    return value if value >= 0 else DEFAULT_RETENTION_DAYS


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 2**63 - 1 else None


# Turn clock. Set when a chat request begins, read when the round is recorded.
#
# A ContextVar rather than a parameter because the two ends are far apart —
# `routes/chat_routes.py` at one, `accumulate_token_usage` at the other, with
# the whole agent loop in between — and threading a start time through that
# would touch far more than it measures. ContextVars follow async tasks, so
# concurrent turns do not read each other's clocks.
_turn_started: "contextvars.ContextVar[Optional[float]]" = contextvars.ContextVar(
    "pantheon_turn_started", default=None)


# The run this turn's events belong to (`P4-25`). Set beside the clock, so a
# turn cannot have a duration without an identity or the reverse.
_run_id: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "pantheon_run_id", default=None)


def mark_turn_start() -> None:
    """Start the clock for this turn and give it an identity.

    Safe to call more than once per turn — the first call wins, so a retry
    inside one request neither restarts the clock nor splits the receipt in two.
    """
    if _turn_started.get() is None:
        _turn_started.set(time.monotonic())
        _run_id.set(uuid.uuid4().hex)


def current_run_id() -> Optional[str]:
    return _run_id.get()


def _turn_elapsed_ms() -> Optional[int]:
    started = _turn_started.get()
    if started is None:
        return None
    return max(0, int((time.monotonic() - started) * 1000))


def record_event(kind: str, *, name: Optional[str] = None,
                 session_id: Optional[str] = None, owner: Optional[str] = None,
                 duration_ms: Optional[int] = None, outcome: str = "ok",
                 detail: Optional[Dict[str, Any]] = None) -> bool:
    """One row for anything that is not a model round. Never raises.

    `P14-02`. Tool calls, retrievals and approvals all land in the same table as
    `llm_round`, because "what happened at 14:02" should have one place to look
    rather than five — that is the whole reason `P14-01` built a table instead
    of three counters.
    """
    try:
        from core.database import SessionLocal, Event
        db = SessionLocal()
        try:
            db.add(Event(
                kind=kind,
                name=_safe_label(name),
                session_id=session_id,
                run_id=_run_id.get(),
                owner=owner,
                duration_ms=_int_or_none(duration_ms),
                outcome=(outcome or "ok")[:32],
                detail=json.dumps(detail, sort_keys=True, default=str) if detail else None,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.debug("event not recorded: %s: %s", type(e).__name__, e)
        return False
    _maybe_prune()
    return True


def record_llm_round(session_id: str, metrics: Dict[str, Any], *,
                     outcome: str = "ok") -> bool:
    """One row for one model round. Returns True if it landed; never raises.

    The return value exists for tests. Production callers ignore it on purpose —
    there is nothing useful for a chat handler to do about a failed history
    write, and the temptation to log loudly on every failure is how a broken
    disk turns into a hundred megabytes of log.
    """
    try:
        from core.database import SessionLocal, Event, Session as DBSession

        owner = None
        db = SessionLocal()
        try:
            row = db.query(DBSession).filter(DBSession.id == session_id).first()
            owner = getattr(row, "owner", None) if row else None

            extras = {
                k: metrics.get(k) for k in ("endpoint_id", "requested_model")
                if metrics.get(k) is not None
            }
            db.add(Event(
                kind="llm_round",
                session_id=session_id,
                run_id=_run_id.get(),
                owner=owner,
                model=_safe_label(metrics.get("model") or metrics.get("actual_model")),
                endpoint=_safe_label(metrics.get("endpoint_label")),
                input_tokens=_int_or_none(metrics.get("input_tokens")),
                output_tokens=_int_or_none(metrics.get("output_tokens")),
                # `P14-02` fills this. It measures the TURN — from the chat
                # request arriving to the totals being accumulated — so it
                # includes tool calls and retries, not just time in the model.
                # That is the number an operator watching a dashboard cares
                # about, and calling it round latency without saying so would
                # be the kind of quietly-wrong metric that outlives its author.
                duration_ms=_turn_elapsed_ms(),
                outcome=(outcome or "ok")[:32],
                detail=json.dumps(extras, sort_keys=True) if extras else None,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.debug("event not recorded: %s: %s", type(e).__name__, e)
        return False

    _maybe_prune()
    return True


def prune_events(days: Optional[int] = None, *,
                 budget_seconds: float = _PRUNE_BUDGET_SECONDS,
                 batch_rows: int = _PRUNE_BATCH_ROWS) -> int:
    """Delete rows older than the retention window. Returns rows removed.

    `days=0` keeps everything, and says so by doing nothing rather than by
    quietly using a default — a retention setting that silently ignores the
    value you gave it is worse than none.

    **Batched and time-boxed** (`P14-06`). This runs on the thread that has just
    finished a person's chat turn, and one DELETE over a real backlog is not a
    fast statement: 550,000 expired rows measured at 7.3 seconds. It now deletes
    `batch_rows` at a time and stops when the budget is spent, which makes the
    cost of a prune a property of this function rather than of how long the
    machine was switched off.

    `unfinished_prune()` reports whether anything was left; `_maybe_prune` reads
    it and rearms so the next write continues rather than waiting a day. A
    caller that genuinely wants the whole thing in one go — a test, a migration —
    passes `budget_seconds=0`, which means *no budget*, not *no work*.
    """
    global _prune_unfinished
    days = _retention_days() if days is None else days
    if days <= 0:
        return 0
    removed_total = 0
    try:
        from sqlalchemy import select
        from core.database import SessionLocal, Event, utcnow_naive
        cutoff = utcnow_naive() - timedelta(days=days)
        started = time.monotonic()
        db = SessionLocal()
        try:
            while True:
                # Delete by id, in batches. `LIMIT` on a DELETE is not portable
                # (SQLite needs a compile-time option, and this runs on whatever
                # `DATABASE_URL` points at), so the batch is selected first and
                # deleted by primary key.
                ids = [row[0] for row in db.execute(
                    select(Event.id).where(Event.ts < cutoff).limit(max(1, batch_rows))
                ).all()]
                if not ids:
                    _prune_unfinished = False
                    break
                removed = db.query(Event).filter(Event.id.in_(ids)).delete(
                    synchronize_session=False)
                db.commit()
                removed_total += int(removed or 0)
                if budget_seconds and (time.monotonic() - started) >= budget_seconds:
                    # More to go. Say so rather than leaving the caller to
                    # assume the window is now clean — the whole point of a
                    # budget is that it stops early, and a silent early stop is
                    # indistinguishable from a finished job.
                    _prune_unfinished = True
                    logger.info(
                        "Prune budget spent after %d event(s); more remain older "
                        "than %d days and the next write will continue",
                        removed_total, days)
                    break
            if removed_total and not _prune_unfinished:
                logger.info("Pruned %d event(s) older than %d days", removed_total, days)
            return removed_total
        finally:
            db.close()
    except Exception as e:
        logger.debug("event prune skipped: %s: %s", type(e).__name__, e)
        return removed_total


def unfinished_prune() -> bool:
    """True when the last prune stopped on its budget with rows still expired."""
    return _prune_unfinished


def _maybe_prune() -> None:
    """Time-gated, so the check costs a float compare on the hot path."""
    global _last_prune
    now = time.monotonic()
    if (_last_prune is not None and not _prune_unfinished
            and now - _last_prune < _PRUNE_INTERVAL_SECONDS):
        return
    with _prune_lock:
        if (_last_prune is not None and not _prune_unfinished
                and time.monotonic() - _last_prune < _PRUNE_INTERVAL_SECONDS):
            return
        _last_prune = time.monotonic()
    prune_events()


def store_status() -> Dict[str, Any]:
    """How big the store has got, against the size the decision was made at.

    `P14-06` / `D-2026-09-18-01`. The decision is *SQLite stays*, and it was made
    on a measurement — 730,000 rows draws a 30-day chart in 195 ms. A decision
    like that is only honest while somebody can tell where they are against it,
    and nothing in the product could say how big this table had become. This is
    that reading, and `src/self_checks.py` is what puts it in front of a person
    rather than waiting to be asked.

    `pressure` is `ok`, `watch` or `over` against `STORE_WATCH_ROWS` /
    `STORE_OVER_ROWS`. `db_bytes` is the whole database file when the store is a
    file-backed SQLite one — it holds thirty other tables, so it is reported as
    what it is and never as the events table's own size, which is what
    `est_bytes` estimates from the measured per-row cost.

    Never raises: it is read by a health surface, and a diagnostic that can take
    a page down is a diagnostic nobody leaves switched on.
    """
    out: Dict[str, Any] = {
        "rows": 0, "oldest": None, "newest": None,
        "retention_days": _retention_days(),
        "est_bytes": 0, "db_bytes": None,
        "watch_rows": STORE_WATCH_ROWS, "over_rows": STORE_OVER_ROWS,
        "pressure": "ok", "unfinished_prune": _prune_unfinished,
    }
    try:
        import os
        from sqlalchemy import func
        from core.database import SessionLocal, Event, engine, _sqlite_db_path

        db = SessionLocal()
        try:
            rows, oldest, newest = db.query(
                func.count(Event.id), func.min(Event.ts), func.max(Event.ts)).one()
        finally:
            db.close()
        out["rows"] = int(rows or 0)
        out["oldest"] = oldest.isoformat() if oldest else None
        out["newest"] = newest.isoformat() if newest else None
        out["est_bytes"] = out["rows"] * MEASURED_BYTES_PER_ROW
        if out["rows"] >= STORE_OVER_ROWS:
            out["pressure"] = "over"
        elif out["rows"] >= STORE_WATCH_ROWS:
            out["pressure"] = "watch"
        try:
            path = _sqlite_db_path(engine.url)
            if path and os.path.exists(path):
                out["db_bytes"] = os.path.getsize(path)
        except Exception:
            pass
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def usage_over_time(days: int = 30, owner: Optional[str] = None) -> Dict[str, Any]:
    """The question that started `P14` (`P14-05`): what has been used, over time.

    Daily buckets, split by model and by owner, aggregated in SQL. `usage_summary`
    answers *how much in total*; this answers *when*, which is the whole reason
    the events table exists — `Session` already knew the total and had thrown the
    timestamp away.

    **Buckets are UTC days**, because `Event.ts` is naive UTC (`utcnow_naive`) and
    inventing a local timezone here would put the boundary in a different place
    than every other timestamp in the product. The caller renders; the caller
    knows where it is.

    **Empty days are filled in.** A series that simply omits a quiet Tuesday
    draws a line straight from Monday to Wednesday, and a gap that reads as
    continuity is the one way a usage chart actively misleads.
    """
    from datetime import date, timedelta as _td
    out: Dict[str, Any] = {"days": days, "owner": owner, "buckets": [],
                           "models": [], "owners": []}
    try:
        from sqlalchemy import func
        from core.database import SessionLocal, Event, utcnow_naive

        days = max(1, min(int(days), 365))
        out["days"] = days
        start_day = (utcnow_naive() - _td(days=days - 1)).date()
        cutoff = utcnow_naive() - _td(days=days)

        db = SessionLocal()
        try:
            day = func.date(Event.ts)

            def scoped(q):
                q = q.filter(Event.kind == "llm_round", Event.ts >= cutoff)
                return q.filter(Event.owner == owner) if owner else q

            rows = scoped(db.query(
                day, Event.model,
                func.count(Event.id),
                func.coalesce(func.sum(Event.input_tokens), 0),
                func.coalesce(func.sum(Event.output_tokens), 0),
                func.coalesce(func.avg(Event.duration_ms), 0),
            )).group_by(day, Event.model).all()

            per_day: Dict[str, Dict[str, Any]] = {}
            models: Dict[str, Dict[str, int]] = {}
            for d, model, n, in_t, out_t, avg_ms in rows:
                key = str(d)
                name = model or "unknown"
                bucket = per_day.setdefault(key, {"day": key, "rounds": 0,
                                                  "input_tokens": 0,
                                                  "output_tokens": 0,
                                                  "by_model": {}})
                bucket["rounds"] += int(n or 0)
                bucket["input_tokens"] += int(in_t or 0)
                bucket["output_tokens"] += int(out_t or 0)
                bucket["by_model"][name] = int(n or 0)
                m = models.setdefault(name, {"rounds": 0, "input_tokens": 0,
                                             "output_tokens": 0, "avg_ms": 0})
                m["rounds"] += int(n or 0)
                m["input_tokens"] += int(in_t or 0)
                m["output_tokens"] += int(out_t or 0)
                m["avg_ms"] = int(avg_ms or 0)

            # Every day in the window, including the quiet ones.
            for i in range(days):
                key = str(start_day + _td(days=i))
                out["buckets"].append(per_day.get(key, {
                    "day": key, "rounds": 0, "input_tokens": 0,
                    "output_tokens": 0, "by_model": {}}))

            out["models"] = [{"model": k, **v} for k, v in
                             sorted(models.items(),
                                    key=lambda kv: -kv[1]["input_tokens"])]

            owner_rows = (db.query(Event.owner, func.count(Event.id),
                                   func.coalesce(func.sum(Event.input_tokens), 0),
                                   func.coalesce(func.sum(Event.output_tokens), 0))
                            .filter(Event.kind == "llm_round", Event.ts >= cutoff)
                            .group_by(Event.owner).all())
            out["owners"] = [
                {"owner": o or "(unattributed)", "rounds": int(n or 0),
                 "input_tokens": int(i or 0), "output_tokens": int(t2 or 0)}
                for o, n, i, t2 in
                sorted(owner_rows, key=lambda r: -(r[2] or 0))
            ]
        finally:
            db.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def usage_summary(days: int = 30, owner: Optional[str] = None) -> Dict[str, Any]:
    """The question that started the phase: what has this cost, over time.

    Deliberately small. `P14-05` builds the real per-model, per-owner views; this
    is here so `P14-01` ships with a reader rather than a write-only table —
    finished work with no door is the `H` rows, and this phase should not add
    another one.
    """
    out: Dict[str, Any] = {"days": days, "rounds": 0, "input_tokens": 0,
                           "output_tokens": 0, "errors": 0, "by_model": {}}
    try:
        from sqlalchemy import func
        from core.database import SessionLocal, Event, utcnow_naive
        cutoff = utcnow_naive() - timedelta(days=max(1, days))
        db = SessionLocal()
        try:
            # Aggregated in SQL, one row per model, never one per event.
            #
            # The first version of this did `for e in q.all()` — pulling every
            # event in the window into Python to add integers. On a table whose
            # entire design is "this accumulates", that is a memory bomb waiting
            # for a heavy user: 90 days at a few thousand rounds a day is
            # hundreds of thousands of ORM objects to compute six numbers.
            def scoped(q):
                q = q.filter(Event.ts >= cutoff, Event.kind == "llm_round")
                return q.filter(Event.owner == owner) if owner else q

            totals = scoped(db.query(
                func.count(Event.id),
                func.coalesce(func.sum(Event.input_tokens), 0),
                func.coalesce(func.sum(Event.output_tokens), 0),
            )).one()
            out["rounds"] = int(totals[0] or 0)
            out["input_tokens"] = int(totals[1] or 0)
            out["output_tokens"] = int(totals[2] or 0)

            out["errors"] = int(scoped(
                db.query(func.count(Event.id))
            ).filter(func.coalesce(Event.outcome, "ok") != "ok").scalar() or 0)

            rows = scoped(db.query(
                Event.model,
                func.count(Event.id),
                func.coalesce(func.sum(Event.input_tokens), 0),
                func.coalesce(func.sum(Event.output_tokens), 0),
            )).group_by(Event.model).all()
            for model, rounds, in_t, out_t in rows:
                out["by_model"][model or "unknown"] = {
                    "rounds": int(rounds or 0),
                    "input_tokens": int(in_t or 0),
                    "output_tokens": int(out_t or 0),
                }
        finally:
            db.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


# ---------------------------------------------------------------------------
# P4-25 — the receipt
# ---------------------------------------------------------------------------

def record_run_config(*, sampling: Optional[Dict[str, Any]] = None,
                      tools: Optional[Iterable[Any]] = None,
                      fenced: Optional[Iterable[str]] = None,
                      skills: Optional[Iterable[Dict[str, Any]]] = None,
                      session_id: Optional[str] = None,
                      owner: Optional[str] = None) -> bool:
    """The three things a run did that nothing kept (`P4-25`).

    Five of the eight items `P4-25` asks for already persisted, and `P14-02`
    added a sixth and seventh — approvals and tool outcomes. These are the
    remainder: **what sampling parameters were resolved, which tool schemas the
    model was actually shown, and which skills were injected at what
    confidence.** Between them they are most of the reason two runs of "the same
    thing" differ, and none of them was written down anywhere.

    **Tool schemas are stored as names plus a hash, not in full.** The point of
    recording them is to make a CHANGE visible — a tool added, removed, or its
    schema edited between two runs. Full schemas are kilobytes each and dozens
    per turn; a stable hash answers the same question at a hundredth of the size,
    and `P4-28`'s diff reads a changed hash exactly as well as a changed blob.
    """
    payload: Dict[str, Any] = {}
    if sampling:
        # Only the knobs that change an answer. A whole request payload would
        # drag the prompt in with it, and a receipt that contains the
        # conversation is a receipt nobody can share.
        keep = ("temperature", "top_p", "top_k", "max_tokens", "presence_penalty",
                "frequency_penalty", "repetition_penalty", "seed", "stop",
                "reasoning_effort", "num_ctx")
        payload["sampling"] = {k: sampling[k] for k in keep if k in sampling}
    if tools is not None:
        payload["tools"] = _tool_fingerprints(tools)
    if fenced is not None:
        # `P17-12`. **The other tool channel**, and names only — a fenced tool
        # is reached by writing its name in a code fence, so there is no schema
        # to hash and nothing a fingerprint would add. `[]` is meaningful and is
        # written: an empty fenced list says the channel was deliberately shut
        # for this turn (the compact prompt forbids tool syntax in chat), which
        # is a different fact from `None`, meaning nobody looked.
        payload["fenced"] = sorted({str(n) for n in fenced if n})
    if skills is not None:
        payload["skills"] = [
            {"name": str(s.get("name") or "")[:200],
             "confidence": s.get("confidence"),
             "source": s.get("source")}
            for s in skills if isinstance(s, dict)
        ]
    if not payload:
        return False
    return record_event("run_config", session_id=session_id, owner=owner,
                        detail=payload)


def _tool_fingerprints(tools: Iterable[Any]) -> List[Dict[str, str]]:
    """`[{name, sha}]` for the schemas as sent. Order-independent per tool."""
    import hashlib
    out: List[Dict[str, str]] = []
    for tool in tools or []:
        try:
            spec = tool if isinstance(tool, dict) else {"name": str(tool)}
            fn = spec.get("function") if isinstance(spec.get("function"), dict) else spec
            name = str(fn.get("name") or spec.get("name") or "?")[:200]
            blob = json.dumps(spec, sort_keys=True, default=str)
            out.append({"name": name,
                        "sha": hashlib.sha256(blob.encode()).hexdigest()[:16]})
        except Exception:
            continue
    out.sort(key=lambda d: d["name"])
    return out


def receipt(run_id: str) -> Dict[str, Any]:
    """Everything one turn did, assembled from the rows it already wrote.

    Not a new store (`Law 14`): a receipt is a range scan on `run_id`. The
    config row carries what `P4-25` had to add; the rounds, tool calls,
    retrievals and approvals were already being written by `P14-01`/`P14-02`.
    """
    out: Dict[str, Any] = {"run_id": run_id, "config": None, "rounds": [],
                           "tools": [], "retrievals": [], "approvals": [],
                           "replays": [], "totals": {}}
    if not run_id:
        out["error"] = "no run_id"
        return out
    try:
        from core.database import SessionLocal, Event
        db = SessionLocal()
        try:
            rows = (db.query(Event).filter(Event.run_id == run_id)
                      .order_by(Event.ts.asc(), Event.id.asc()).all())
            for e in rows:
                detail = None
                if e.detail:
                    try:
                        detail = json.loads(e.detail)
                    except Exception:
                        detail = {"raw": e.detail}
                item = {"ts": e.ts.isoformat() if e.ts else None,
                        "name": e.name, "outcome": e.outcome,
                        "duration_ms": e.duration_ms, "detail": detail}
                if e.kind == "run_config":
                    # `P17-12`. **Merged, not replaced**, and this was a real
                    # loss. A run writes its config from more than one place —
                    # sampling and schemas from `stream_llm`, skills and the
                    # fenced list from the prompt builder — because each is
                    # resolved somewhere different. Assigning meant the last row
                    # won and every field only the earlier rows carried
                    # vanished from the receipt: a turn that injected skills
                    # *and* sent schemas could show one or the other, never
                    # both, depending purely on which wrote last.
                    #
                    # Later keys still win, so `P17-08`'s supersede — a second
                    # row carrying a tool list the first did not have —
                    # continues to work, and now without taking the first row's
                    # other fields down with it.
                    if isinstance(detail, dict):
                        out["config"] = {**(out["config"] or {}), **detail}
                    elif detail is not None:
                        out["config"] = detail
                elif e.kind == "llm_round":
                    out["rounds"].append({**item, "model": e.model,
                                          "endpoint": e.endpoint,
                                          "input_tokens": e.input_tokens,
                                          "output_tokens": e.output_tokens})
                elif e.kind == "tool_call":
                    out["tools"].append(item)
                elif e.kind == "retrieval":
                    out["retrievals"].append(item)
                elif e.kind == "approval":
                    out["approvals"].append(item)
                elif e.kind == "replay":
                    # `P4-26` writes these and `P4-28` reads them: without this
                    # branch the link back to the original run was recorded and
                    # then dropped on the way out — stored, and unreadable
                    # through the only API that reads receipts.
                    out["replays"].append(item)
                if e.session_id and not out.get("session_id"):
                    out["session_id"] = e.session_id
                if e.owner and not out.get("owner"):
                    out["owner"] = e.owner
            out["totals"] = {
                "rounds": len(out["rounds"]),
                "input_tokens": sum(r.get("input_tokens") or 0 for r in out["rounds"]),
                "output_tokens": sum(r.get("output_tokens") or 0 for r in out["rounds"]),
                "tool_calls": len(out["tools"]),
                "tool_failures": sum(1 for x in out["tools"]
                                     if (x.get("outcome") or "ok") != "ok"),
                "approvals": len(out["approvals"]),
            }
        finally:
            db.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out
