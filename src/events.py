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
"""
import json
import logging
import re
import threading
import time
from datetime import timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 90

# Prune at most this often per process. Cheap enough to check on every write,
# rare enough that the DELETE is invisible.
_PRUNE_INTERVAL_SECONDS = 24 * 60 * 60
_last_prune = 0.0
_prune_lock = threading.Lock()

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
                owner=owner,
                model=_safe_label(metrics.get("model") or metrics.get("actual_model")),
                endpoint=_safe_label(metrics.get("endpoint_label")),
                input_tokens=_int_or_none(metrics.get("input_tokens")),
                output_tokens=_int_or_none(metrics.get("output_tokens")),
                # duration_ms stays NULL: round latency is not available at this
                # insertion point, and threading it through is `P14-02`.
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


def prune_events(days: Optional[int] = None) -> int:
    """Delete rows older than the retention window. Returns rows removed.

    `days=0` keeps everything, and says so by doing nothing rather than by
    quietly using a default — a retention setting that silently ignores the
    value you gave it is worse than none.
    """
    days = _retention_days() if days is None else days
    if days <= 0:
        return 0
    try:
        from core.database import SessionLocal, Event, utcnow_naive
        cutoff = utcnow_naive() - timedelta(days=days)
        db = SessionLocal()
        try:
            removed = db.query(Event).filter(Event.ts < cutoff).delete(
                synchronize_session=False)
            db.commit()
            if removed:
                logger.info("Pruned %d event(s) older than %d days", removed, days)
            return int(removed or 0)
        finally:
            db.close()
    except Exception as e:
        logger.debug("event prune skipped: %s: %s", type(e).__name__, e)
        return 0


def _maybe_prune() -> None:
    """Time-gated, so the check costs a float compare on the hot path."""
    global _last_prune
    now = time.monotonic()
    if now - _last_prune < _PRUNE_INTERVAL_SECONDS:
        return
    with _prune_lock:
        if time.monotonic() - _last_prune < _PRUNE_INTERVAL_SECONDS:
            return
        _last_prune = time.monotonic()
    prune_events()


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
        from core.database import SessionLocal, Event, utcnow_naive
        cutoff = utcnow_naive() - timedelta(days=max(1, days))
        db = SessionLocal()
        try:
            q = db.query(Event).filter(Event.ts >= cutoff, Event.kind == "llm_round")
            if owner:
                q = q.filter(Event.owner == owner)
            for e in q.all():
                out["rounds"] += 1
                out["input_tokens"] += e.input_tokens or 0
                out["output_tokens"] += e.output_tokens or 0
                if (e.outcome or "ok") != "ok":
                    out["errors"] += 1
                key = e.model or "unknown"
                m = out["by_model"].setdefault(
                    key, {"rounds": 0, "input_tokens": 0, "output_tokens": 0})
                m["rounds"] += 1
                m["input_tokens"] += e.input_tokens or 0
                m["output_tokens"] += e.output_tokens or 0
        finally:
            db.close()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out
