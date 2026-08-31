"""Always-on monitor that auto-continues the agent when a background job
(see src/bg_jobs.py) finishes.

Reliability is the whole point: completion → agent re-invocation must never
silently no-op. The monitor drains `bg_jobs.pending_followups()` every tick and
only calls `mark_followed_up()` AFTER the agent run succeeds — so a transient
failure is simply retried on the next tick. A timed-out/dead job still produces
a follow-up ("the job failed/timed out"), so the user always hears back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time

from src import bg_jobs
from src.prompt_security import untrusted_context_message

logger = logging.getLogger(__name__)

_monitor_task = None
POLL_INTERVAL_S = 5
# The follow-up agent run is allowed a few rounds to actually continue the task
# (e.g. after `pip install` finishes, run the transcription).
_FOLLOWUP_MAX_ROUNDS = 12

# Per-job backoff after a failed follow-up.
#
# `mark_followed_up` only runs when `_run_followup` returns True, and the except
# below deliberately leaves `followed_up=False` so the work is not lost. That is
# the right call for idempotency and the wrong one for pacing: a follow-up whose
# model call 429s used to be retried **every five seconds, forever**, each
# attempt allowed up to 12 model rounds, each round able to call web_search. One
# rate-limited job could issue 720 attempts an hour, indefinitely, unattended.
#
# The state is in memory rather than on the record because `bg_jobs` has no
# attempt column and a schema change is not what this hour is for; the cost is
# that a restart forgets the backoff, which is the same trade the rest of the
# limiter makes and is filed on `P15-09`.
_FOLLOWUP_BACKOFF_BASE_S = 30.0
_FOLLOWUP_BACKOFF_MAX_S = 1800.0
_FOLLOWUP_GIVE_UP_AFTER = 12
_followup_failures: dict = {}


def _followup_ready(job_id, now: float) -> bool:
    """False while a previously failed job is still serving its backoff."""
    entry = _followup_failures.get(job_id)
    return not entry or now >= entry[1]


def _note_followup_failure(job_id, now: float) -> float:
    """Record a failure and return the delay before this job is tried again."""
    fails = _followup_failures.get(job_id, (0, 0.0))[0] + 1
    delay = min(_FOLLOWUP_BACKOFF_BASE_S * (2 ** (fails - 1)), _FOLLOWUP_BACKOFF_MAX_S)
    # Jitter, because every Pantheon install that hit the same provider outage
    # would otherwise come back at the same instant and reproduce it.
    delay += random.uniform(0, delay * 0.2)
    _followup_failures[job_id] = (fails, now + delay)
    return delay


def _clear_followup_failure(job_id) -> None:
    _followup_failures.pop(job_id, None)


def _background_result_message(rec):
    inject = (
        f"[Background job {rec['id']} finished]\n\n"
        f"{bg_jobs.result_text(rec)}\n\n"
        "Continue the task using this output. Don't repeat work that's already done. "
        "If the task is now complete, give the user the final result."
    )
    return untrusted_context_message("background job output", inject)


async def _drain_agent(sess, messages):
    """Run the agent loop headless against a session. Returns
    (final_prose, tool_events) — tool_events in the same shape the live chat
    saves, so the frontend rebuilds them as standard agent-thread tool cards."""
    from src.agent_loop import stream_agent_loop
    full = ""
    tool_events = []
    round_num = 1
    async for chunk in stream_agent_loop(
        sess.endpoint_url, sess.model, messages,
        headers=getattr(sess, "headers", None),
        context_length=getattr(sess, "context_length", 0) or 0,
        session_id=sess.id,
        max_rounds=_FOLLOWUP_MAX_ROUNDS,
        owner=getattr(sess, "owner", None),
    ):
        if not chunk.startswith("data: "):
            continue
        body = chunk[6:].strip()
        if not body or body == "[DONE]":
            continue
        try:
            d = json.loads(body)
        except (ValueError, TypeError):
            continue
        if not isinstance(d, dict):
            continue
        if "delta" in d:
            delta = d.get("delta")
            if isinstance(delta, str):
                if d.get("thinking"):
                    continue
                full += delta
        elif d.get("type") == "agent_step":
            round_num = d.get("round", round_num)
        elif d.get("type") == "tool_output":
            # Mirror the live chat's tool_event shape (chat_routes / chatRenderer).
            tool_event = {
                "round": round_num,
                "tool": d.get("tool"),
                "command": d.get("command"),
                "output": d.get("output"),
                "exit_code": d.get("exit_code"),
            }
            if isinstance(d.get("ask_user"), dict):
                # Preserve exact-approval cards from a tainted background-job
                # continuation so the user can authorize the sealed action on
                # the next foreground turn instead of losing it headlessly.
                tool_event["ask_user"] = d["ask_user"]
            tool_events.append(tool_event)
    return full, tool_events


async def _run_followup(rec: dict) -> bool:
    """Re-invoke the agent in the job's session with the result. Returns True
    if the follow-up completed (or there's nothing to do) — i.e. it's safe to
    mark followed_up. Returns False to retry on the next tick."""
    from src.ai_interaction import get_session_manager
    from core.models import ChatMessage

    sm = get_session_manager()
    if not sm:
        return False  # not ready yet — retry
    sess = sm.get_session(rec["session_id"])
    if not sess:
        # Session was deleted — nothing to continue. Consider it handled so we
        # don't retry forever.
        logger.info("bg-followup: session %s gone for job %s — skipping", rec.get("session_id"), rec.get("id"))
        return True

    # Don't write into a session that's mid-stream. The followup appends to
    # history + save_sessions(); a concurrent live turn does the same, and with
    # no per-session lock the two interleave (reordered/clobbered messages).
    # Defer — return False so we retry on the next tick once the turn finishes.
    try:
        from src import agent_runs
        if agent_runs.is_active(sess.id):
            logger.info("bg-followup: session %s busy (live turn) — deferring job %s", sess.id, rec.get("id"))
            return False
    except Exception:
        pass

    context = sess.get_context_messages()
    context.append(_background_result_message(rec))

    full, tool_events = await _drain_agent(sess, context)

    # Persist ONLY the assistant continuation so it renders as a normal agent
    # turn — a standard chat bubble plus `tool_events` that the frontend
    # rebuilds into the usual agent-thread tool cards (chatRenderer:1494). The
    # trigger isn't saved as its own message (it'd be an out-of-place bubble);
    # the raw job output is stashed in metadata for traceability instead.
    sm.add_message(sess.id, ChatMessage(
        "assistant", full,
        metadata={
            "tool_events": tool_events,
            "model": sess.model,
            "bg_job_id": rec["id"],
            "bg_result": bg_jobs.result_text(rec)[:4000],
        },
    ))
    sm.save_sessions()
    logger.info("bg-followup: auto-continued session %s for job %s (%d chars, %d tools)",
                sess.id, rec["id"], len(full), len(tool_events))
    return True


async def _loop():
    while True:
        try:
            now = time.monotonic()
            for rec in bg_jobs.pending_followups():
                job_id = rec.get("id")
                if not _followup_ready(job_id, now):
                    continue
                try:
                    if await _run_followup(rec):
                        bg_jobs.mark_followed_up(job_id)
                        _clear_followup_failure(job_id)
                except Exception as e:
                    # Still idempotent — followed_up stays False so the work is
                    # not lost — but the retry now waits. Without this the job
                    # came back in five seconds and kept coming back.
                    delay = _note_followup_failure(job_id, now)
                    fails = _followup_failures.get(job_id, (0, 0.0))[0]
                    if fails >= _FOLLOWUP_GIVE_UP_AFTER:
                        logger.error(
                            "bg-followup failed for %s %d times; giving up and marking it "
                            "followed-up so it stops retrying: %s", job_id, fails, e,
                        )
                        try:
                            bg_jobs.mark_followed_up(job_id)
                        except Exception:
                            logger.warning("could not mark %s followed-up", job_id, exc_info=True)
                        _clear_followup_failure(job_id)
                    else:
                        logger.warning(
                            "bg-followup failed for %s (attempt %d, retrying in %.0fs): %s",
                            job_id, fails, delay, e,
                        )
        except Exception as e:
            logger.warning("bg-monitor tick error: %s", e)
        await asyncio.sleep(POLL_INTERVAL_S)


def start_bg_monitor():
    """Idempotent — start the always-on background-job monitor."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        return _monitor_task
    _monitor_task = asyncio.create_task(_loop())
    logger.info("Background-job monitor started (poll %ds)", POLL_INTERVAL_S)
    return _monitor_task
