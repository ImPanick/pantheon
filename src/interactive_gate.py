# SPDX-License-Identifier: AGPL-3.0-or-later
"""Foreground activity gate for background work.

Background tasks are allowed to run only after normal UI/API traffic has
settled. This keeps scheduled jobs and email pollers from competing with the
user opening Pantheon, Forge, email, documents, notes, or other panels.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
import time


_ACTIVE_REQUESTS = 0
_LAST_ACTIVITY = 0.0
_LAST_BROWSER_ACTIVITY = 0.0
_COND: asyncio.Condition | None = None
_COND_LOOP: asyncio.AbstractEventLoop | None = None

# `B1047`. Who started a task run, which decides what it waits for. Two words
# rather than a boolean whose polarity can be read either way (`Law 10`); the
# scheduler records one on every run and hands it to the steps a run chains
# into, and this module is the only place either word is given a meaning.
#
#   background  a schedule, an event or a webhook, and every step chained from
#               one. Waits until nobody is using Pantheon — no request in the
#               quiet window, no visible tab's heartbeat, no chat reply being
#               written — and is stopped when somebody starts. What this gate
#               was built for, unchanged.
#   person      somebody pressed Run now (or Start now), and every step chained
#               from that. Waits only while a chat reply is being written, and
#               only if it needs the model; the open page, its own polls and
#               the heartbeat never stop it. The person IS the foreground: the
#               page they pressed the button on is not a reason to hold back
#               the thing they just asked for — and measured on the old gate it
#               never ran while that page stayed open, because the tab's
#               heartbeat alone keeps "busy" true (`B1047`).
STARTED_BY_BACKGROUND = "background"
STARTED_BY_PERSON = "person"
STARTED_BY = (STARTED_BY_BACKGROUND, STARTED_BY_PERSON)


def _enabled() -> bool:
    from src.env_flags import env_flag
    return env_flag("BACKGROUND_TASK_FOREGROUND_GATE", True)


def _quiet_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("BACKGROUND_TASK_QUIET_MS", "1500")) / 1000.0)
    except Exception:
        return 1.5


def _max_wait_seconds() -> float:
    """0 means wait indefinitely until the UI is quiet."""
    try:
        return max(0.0, float(os.getenv("BACKGROUND_TASK_MAX_WAIT_SECONDS", "0")))
    except Exception:
        return 0.0


def _browser_active_seconds() -> float:
    """How long a visible Pantheon browser heartbeat blocks background tasks."""
    try:
        return max(0.0, float(os.getenv("BACKGROUND_TASK_BROWSER_ACTIVE_SECONDS", "45")))
    except Exception:
        return 45.0


def _condition() -> asyncio.Condition:
    global _COND, _COND_LOOP
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _COND is None or _COND_LOOP is not loop:
        _COND = asyncio.Condition()
        _COND_LOOP = loop
    return _COND


_PASSIVE_EXACT_PATHS = {
    "/api/activity/heartbeat",
    "/api/client-perf",
    "/api/tasks/notifications",
    "/api/tasks/runs/recent",
    "/api/research/active",
    "/api/email/urgency-state",
    # UI idle poll sibling of urgency-state; must not pre-empt background tasks.
    "/api/email/unread-state",
}

_PASSIVE_PREFIXES = (
    "/api/chat/stream_status",
    "/api/health",
    "/api/prefs",
)


async def maybe_stop_background_tasks_for_heartbeat(stop_background) -> bool:
    """Stop background work for browser activity only when the gate is enabled.

    ``stop_background`` is injected by the application boundary so this policy
    remains independently testable without importing the full FastAPI app.
    """
    if not _enabled():
        return False

    await stop_background(reason="browser heartbeat")
    return True


def should_track_interactive_request(path: str, method: str = "GET") -> bool:
    if not _enabled():
        return False
    if (method or "").upper() == "OPTIONS":
        return False
    if path in _PASSIVE_EXACT_PATHS:
        return False
    if any(path.startswith(prefix) for prefix in _PASSIVE_PREFIXES):
        return False
    return True


def heartbeat_says_idle(body: bytes | str | None) -> bool:
    """`P23-07` (`PERF-M-11`, C-IDLE). Is this heartbeat a tab saying it is
    merely open?

    The page beats every 15 s while it is visible, and until this row every
    beat counted as somebody using Pantheon. With a 45 s window that made a
    tab left open — on a second monitor, over lunch — busy for ever:
    `wait_for_interactive_quiet` has no deadline by default, so the background
    inbox check never looked and every due scheduled run was moved 15 minutes
    on at each tick (`B1094`), all day. Now the interval beat carries
    `{"idle": true}` and is ignored here; a beat from a key, a pointer, a
    scroll, the window's focus or the tab coming forward still counts. A body
    that is anything else — `{}`, an old cached page, not JSON — is a person,
    which is what every beat meant before (`Law 1`).
    """
    if not body:
        return False
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and data.get("idle") is True


async def mark_browser_activity() -> None:
    """Record that an authenticated browser tab is visibly using Pantheon."""
    global _LAST_BROWSER_ACTIVITY
    if not _enabled():
        return
    cond = _condition()
    async with cond:
        _LAST_BROWSER_ACTIVITY = time.monotonic()
        cond.notify_all()


async def on_heartbeat(body: bytes | str | None, stop_background) -> dict:
    """`POST /api/activity/heartbeat`, whole (`app.activity_heartbeat` is this).

    An idle beat is answered and nothing else happens. A person's beat marks
    the browser active and — when the gate is on — stops background work that
    is running, in its own task so the beat answers at once (what the route
    did before `P23-07`, moved here so tests drive the route's own code).
    """
    if heartbeat_says_idle(body):
        return {"ok": True, "idle": True}
    await mark_browser_activity()

    async def _stop_background():
        try:
            await maybe_stop_background_tasks_for_heartbeat(stop_background)
        except Exception:
            import logging
            logging.getLogger("app.foreground_gate").debug(
                "heartbeat task stop failed", exc_info=True)

    asyncio.create_task(_stop_background())
    return {"ok": True}


def _has_recent_browser_activity(now: float | None = None) -> bool:
    ttl = _browser_active_seconds()
    if ttl <= 0 or _LAST_BROWSER_ACTIVITY <= 0:
        return False
    return ((now if now is not None else time.monotonic()) - _LAST_BROWSER_ACTIVITY) < ttl


def has_foreground_activity(now: float | None = None) -> bool:
    """Return True when foreground browser/model work should stop background jobs.

    Passive polling endpoints are excluded by should_track_interactive_request,
    so active/recent request tracking is safe to use here. This matters during
    initial page load: the heartbeat may not have landed yet, but the user is
    already waiting on real UI requests.
    """
    if not _enabled():
        return False
    t = now if now is not None else time.monotonic()
    if _ACTIVE_REQUESTS > 0:
        return True
    if _LAST_ACTIVITY > 0 and (t - _LAST_ACTIVITY) < _quiet_seconds():
        return True
    return _has_recent_browser_activity(t) or _has_active_chat_stream()


def _has_active_chat_stream() -> bool:
    """Best-effort check for foreground model work that outlives HTTP requests.

    Chat/agent streams are detached from the browser SSE so a stream can keep
    running after the request that started it has returned. Background LLM
    tasks must still wait for those runs; otherwise helpers like email
    auto-translate compete with the user's active chat on the same local model.
    """
    try:
        from routes import chat_routes as _chat_routes
        active_streams = getattr(_chat_routes, "_active_streams", {}) or {}
        if active_streams:
            return True
    except Exception:
        pass
    try:
        from src import agent_runs
        runs = getattr(agent_runs, "_RUNS", {}) or {}
        return any(getattr(run, "status", None) == "running" for run in runs.values())
    except Exception:
        return False


@asynccontextmanager
async def track_interactive_request(path: str = "", method: str = ""):
    global _ACTIVE_REQUESTS, _LAST_ACTIVITY
    if not _enabled():
        yield
        return

    cond = _condition()
    async with cond:
        _ACTIVE_REQUESTS += 1
        _LAST_ACTIVITY = time.monotonic()
        cond.notify_all()
    try:
        yield
    finally:
        async with cond:
            _ACTIVE_REQUESTS = max(0, _ACTIVE_REQUESTS - 1)
            _LAST_ACTIVITY = time.monotonic()
            cond.notify_all()


async def wait_for_interactive_quiet(label: str = "") -> bool:
    """Wait until foreground requests have stopped for the configured window.

    Returns True if the caller had to wait at all. The label is intentionally
    only for future logging/debugging so callers can keep their code simple.
    """
    if not _enabled():
        return False

    quiet = _quiet_seconds()
    max_wait = _max_wait_seconds()
    deadline = time.monotonic() + max_wait if max_wait > 0 else None
    cond = _condition()
    waited = False

    while True:
        async with cond:
            now = time.monotonic()
            quiet_remaining = quiet - (now - _LAST_ACTIVITY)
            active_stream = _has_active_chat_stream()
            browser_active = _has_recent_browser_activity(now)
            if _ACTIVE_REQUESTS <= 0 and quiet_remaining <= 0 and not active_stream and not browser_active:
                return waited

            waited = True
            timeout = 0.25 if (_ACTIVE_REQUESTS > 0 or active_stream or browser_active) else min(max(quiet_remaining, 0.05), 0.5)
            if deadline is not None:
                remaining = deadline - now
                if remaining <= 0:
                    return waited
                timeout = min(timeout, remaining)
            await _wait_on(cond, timeout)


async def _wait_on(cond: asyncio.Condition, timeout: float) -> None:
    """Wait for a notify or `timeout` seconds, with `cond` held. Never swallows
    a cancel.

    `B1047`. This was `asyncio.wait_for(cond.wait(), timeout)`. On Python 3.11
    — the venv, CI, and every native install `setup.py` builds — `wait_for`
    returns the inner result when its task is cancelled in the same loop tick
    as the inner wait completes, and drops the cancel. That is exactly how a
    foreground request arrives: `_InteractiveActivityMiddleware` schedules
    `stop_background_tasks_for_foreground` (which cancels the waiting run) and
    then `track_interactive_request` notifies this condition, in one tick.
    Measured on 3.11.15 through the real scheduler: the run was marked aborted,
    its task kept waiting with its claim held, and once the page closed it ran
    and chained. 3.12 rewrote `wait_for` on `asyncio.timeout`; this is that,
    here, so the version does not decide whether a stopped run stays stopped.
    `asyncio.timeout` is 3.11+, the floor CI runs (`src/mcp_scaffold.py`
    already uses it).
    """
    try:
        async with asyncio.timeout(timeout):
            await cond.wait()
    except TimeoutError:
        pass


def chat_in_progress() -> bool:
    """Is a chat reply or an agent turn being written right now?

    `B1047`. What a run a person started waits for — the one kind of
    foreground work a task run would slow down, because both use the model.
    """
    return _enabled() and _has_active_chat_stream()


async def wait_for_chat_quiet(label: str = "") -> bool:
    """Wait until no chat reply or agent turn is being written.

    `B1047`. The wait for a run a person started (`STARTED_BY_PERSON`): a
    person's chat is not slowed by the run, and the run is not held back by the
    page the person pressed Run now on. Request traffic and the tab's heartbeat
    do not count here — `wait_for_interactive_quiet` is the background wait.
    Returns True if it had to wait. Streams do not notify the condition, so it
    looks again every quarter second, as the background wait does for them.
    """
    if not _enabled():
        return False
    cond = _condition()
    waited = False
    while True:
        async with cond:
            if not _has_active_chat_stream():
                return waited
            waited = True
            await _wait_on(cond, 0.25)


# `B1061`. Who an agent's tool call is acting for, so a tool that starts a task
# run (`manage_tasks run`) can say who asked — the same two words as a run
# (`STARTED_BY`). Measured 2026-10-01: `stream_agent_loop` is reached from a
# person's chat turn (`routes/chat_routes.py`), the teacher run inside one
# (`src/teacher_escalation.py`), a skill test a person pressed
# (`routes/skills_routes.py`), the background-job follow-up
# (`src/bg_monitor.py`) and the scheduler's own runs (`src/task_scheduler.py`),
# and only the scheduler passes `workload="background"`. A bearer token's chat
# never reaches `manage_tasks` (`NON_ADMIN_BLOCKED_TOOLS`, `B70`). So the loop's
# `workload` is the answer, bound in each tool call's own task — a copy of the
# loop's context, the way `bind_run_limits` binds the run's caps — so it ends
# with the call. Unbound, it is background: today's answer for every caller.
from contextvars import ContextVar  # noqa: E402

_TOOL_CALL_STARTED_BY: ContextVar[str] = ContextVar(
    "tool_call_started_by", default=STARTED_BY_BACKGROUND)


def bind_tool_call_started_by(workload: str | None) -> None:
    """`B1061`. Called inside a tool call's task with the loop's `workload`."""
    _TOOL_CALL_STARTED_BY.set(
        STARTED_BY_BACKGROUND if (workload or "foreground") == "background" else STARTED_BY_PERSON)


def tool_call_started_by() -> str:
    """`B1061`. `STARTED_BY_PERSON` for a call made in a person's turn,
    `STARTED_BY_BACKGROUND` for a scheduled run's and for any call nothing
    bound."""
    return _TOOL_CALL_STARTED_BY.get()
