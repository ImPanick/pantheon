# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local assertions about state. What is quietly wrong, on your own machine.

`service_health.py` answers *can I reach X* — liveness. This answers *is
something accumulating, or has something quietly stopped* — and the difference
is the whole reason this module exists.

**`H01` is the worked example and the indictment.** Every email the agent
composed since this instance was installed sat staged, unsent and invisible, for
a year — and the mail server was **reachable the entire time**. Liveness said
green. Nothing was down; something had simply stopped finishing, and no surface
counted it. A single number in front of a person would have caught it in the
first week.

So each check here is:

* **local** — reads state this machine already has, never the network (`Law 16`);
* **cheap** — safe to run on a page load;
* **about accumulation or abandonment**, not reachability;
* **specific enough to act on** — a count and a next step, not a colour.

`D-2026-09-01-01` is why this matters more here than telemetry would: the
maintainer is the primary user and therefore the sensor. This is the sensor's
dial. Every check below also gives a reader to something that had none —
`P15-11`'s limiter snapshot, `P15-12`'s per-account mail backoff, `P16-05`'s
degraded embedding lanes.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

OK = "ok"
ATTENTION = "attention"     # working as built, and someone should look
STUCK = "stuck"             # accumulating or abandoned; will not fix itself
UNKNOWN = "unknown"         # the check could not run; say so rather than imply ok


def _check(name: str, title: str, status: str, summary: str,
           *, count: int = 0, action: str = "", **extra: Any) -> Dict[str, Any]:
    return {
        "name": name,
        "title": title,
        "status": status,
        "summary": summary,
        "count": count,
        "action": action,
        **extra,
    }


# ---------------------------------------------------------------------------
# H01 — mail the agent wrote that nobody can see
# ---------------------------------------------------------------------------

def agent_email_backlog() -> Dict[str, Any]:
    """Drafts staged for an approval screen that does not exist yet.

    With `agent_email_confirm` on — which is the shipped default, and arrived at
    the fork baseline — `_send_email` does not send. It stages the message with a
    far-future `send_at` the poller never reaches, waiting for an approval UI
    that has never existed. The three endpoints to list, approve and discard
    them have no frontend caller.

    This counts them. It is the cheapest possible fix for a year-long data loss
    and it is the reason this module exists.
    """
    from src.constants import DATA_DIR

    db = os.path.join(DATA_DIR, "scheduled_emails.db")
    if not os.path.exists(db):
        return _check("agent_email_backlog", "Agent email awaiting approval",
                      OK, "No mail database yet.")
    try:
        conn = sqlite3.connect(db)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "scheduled_emails" not in tables:
                return _check("agent_email_backlog", "Agent email awaiting approval",
                              OK, "No staged mail.")
            row = conn.execute(
                "SELECT COUNT(*), MIN(created_at) FROM scheduled_emails WHERE status = ?",
                ("agent_draft",),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        return _check("agent_email_backlog", "Agent email awaiting approval",
                      UNKNOWN, f"Could not read the mail database: {e}")

    count = int((row or [0])[0] or 0)
    if not count:
        return _check("agent_email_backlog", "Agent email awaiting approval",
                      OK, "Nothing staged.")
    oldest = (row or [0, None])[1]
    since = f" The oldest has been waiting since {oldest}." if oldest else ""
    return _check(
        "agent_email_backlog", "Agent email awaiting approval", STUCK,
        f"{count} message{'s' if count != 1 else ''} the assistant wrote are staged and "
        f"will never send on their own.{since}",
        count=count,
        action="Approve or discard them, or turn off agent_email_confirm so mail sends "
               "directly. They are not queued — nothing will deliver them.",
        oldest=oldest,
    )


# ---------------------------------------------------------------------------
# P15 — services we have stopped calling
# ---------------------------------------------------------------------------

def outbound_cooldowns() -> Dict[str, Any]:
    """Hosts the limiter is holding off, and for how long.

    `OutboundHostLimiter.snapshot()` was written for exactly this and had no
    reader (`P15-11`). Without it, a rate-limited provider looks identical to a
    feature that has quietly stopped working.
    """
    try:
        from src.rate_limiter import outbound

        snap = outbound.snapshot()
    except Exception as e:
        return _check("outbound_cooldowns", "Throttled services", UNKNOWN,
                      f"Could not read the outbound limiter: {e}")

    blocked = {h: s for h, s in snap.items() if s.get("blocked_for", 0) > 1}
    if not blocked:
        return _check("outbound_cooldowns", "Throttled services", OK,
                      "Nothing is being held off.")
    worst = max(blocked.items(), key=lambda kv: kv[1]["blocked_for"])
    mins = worst[1]["blocked_for"] / 60.0
    when = f"{worst[1]['blocked_for']:.0f}s" if worst[1]["blocked_for"] < 90 else f"{mins:.0f} min"
    return _check(
        "outbound_cooldowns", "Throttled services", ATTENTION,
        f"{len(blocked)} service{'s' if len(blocked) != 1 else ''} asked us to stop. "
        f"Longest wait: {worst[0]} for another {when}.",
        count=len(blocked),
        action="Nothing to do — Pantheon has stopped calling them, which is what lets the "
               "limit expire. Features that use them will be quiet until it does.",
        hosts={h: round(s["blocked_for"]) for h, s in blocked.items()},
    )


# ---------------------------------------------------------------------------
# P16-05 — retrieval silently degraded
# ---------------------------------------------------------------------------

def embedding_availability() -> Dict[str, Any]:
    """Memory and RAG need an embedding lane. Without one they return nothing.

    They degrade quietly by design — `memory_vector` and `rag_vector` both
    handle zero lanes rather than crashing — which is correct behaviour and
    exactly why it needs saying out loud somewhere.
    """
    try:
        from src.embedding_lanes import fastembed_model_is_cached, model_download_allowed
        from src.embeddings import EmbeddingClient, get_embedding_client

        local_ok = isinstance(get_embedding_client(), EmbeddingClient)
    except Exception:
        local_ok = False
        try:
            from src.embedding_lanes import fastembed_model_is_cached, model_download_allowed
        except Exception as e:
            return _check("embedding_availability", "Memory and knowledge search",
                          UNKNOWN, f"Could not check the embedding lanes: {e}")

    if local_ok or fastembed_model_is_cached():
        return _check("embedding_availability", "Memory and knowledge search", OK,
                      "An embedding lane is available.")
    if model_download_allowed():
        return _check("embedding_availability", "Memory and knowledge search", ATTENTION,
                      "No embedding lane yet; the model will be downloaded on first use.",
                      action="Nothing to do — you have permitted the download.")
    return _check(
        "embedding_availability", "Memory and knowledge search", STUCK,
        "Memory and knowledge search return nothing: there is no embedding lane.",
        action="Point EMBEDDING_URL at a local embedding server (Ollama serves one), or "
               "turn on allow_model_download to fetch the ~90MB model once.",
    )


# ---------------------------------------------------------------------------
# P15-04 — work that gave up
# ---------------------------------------------------------------------------

def abandoned_followups() -> Dict[str, Any]:
    """Background follow-ups that failed enough times to be given up on."""
    try:
        import src.bg_monitor as bg

        now = time.monotonic()
        waiting = {j: e for j, e in bg._followup_failures.items() if e[1] > now}
    except Exception as e:
        return _check("abandoned_followups", "Background follow-ups", UNKNOWN,
                      f"Could not read the follow-up state: {e}")

    if not waiting:
        return _check("abandoned_followups", "Background follow-ups", OK,
                      "Nothing is backing off.")
    worst = max(waiting.values(), key=lambda e: e[0])[0]
    return _check(
        "abandoned_followups", "Background follow-ups", ATTENTION,
        f"{len(waiting)} background job{'s' if len(waiting) != 1 else ''} failed and "
        f"are waiting to retry. The worst has failed {worst} times.",
        count=len(waiting),
        action="Check the logs for the failing job. After 12 failures a job is given up on "
               "so it stops retrying forever.",
    )


CHECKS = (
    agent_email_backlog,
    outbound_cooldowns,
    embedding_availability,
    abandoned_followups,
)

_RANK = {STUCK: 0, ATTENTION: 1, UNKNOWN: 2, OK: 3}


def run_self_checks() -> Dict[str, Any]:
    """Run every check. A check that raises is reported, never swallowed.

    A self-check module that can fail silently is a joke with a long setup, so
    the broad `except` here converts a crash into an `unknown` row with the
    error on it rather than dropping the check from the list.
    """
    results: List[Dict[str, Any]] = []
    for fn in CHECKS:
        try:
            results.append(fn())
        except Exception as e:  # noqa: BLE001 — reported, not swallowed
            logger.warning("self-check %s failed", fn.__name__, exc_info=True)
            results.append(_check(fn.__name__, fn.__name__.replace("_", " ").title(),
                                  UNKNOWN, f"This check itself failed: {e}"))

    results.sort(key=lambda r: (_RANK.get(r["status"], 9), r["name"]))
    worst = results[0]["status"] if results else OK
    return {
        "status": worst,
        "needs_attention": [r for r in results if r["status"] in (STUCK, ATTENTION)],
        "checks": results,
        "checked_at": time.time(),
    }
