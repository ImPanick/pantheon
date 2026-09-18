# SPDX-License-Identifier: AGPL-3.0-or-later
# src/rate_limiter.py
"""Generic in-memory rate limiter — sliding window, keyed by IP."""

import ipaddress
import logging
import os
import threading
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter.

    Usage:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        if not limiter.check(ip):
            raise HTTPException(429, "Too many requests")
    """

    def __init__(self, max_requests: int, window_seconds: int, *,
                 limit_key: str | None = None,
                 window_key: str | None = None):
        self.max_requests = max_requests
        self.window = window_seconds
        # `P12-05b`. The settings keys this limiter re-reads on every check, or
        # `None` for a limiter whose numbers are fixed. Both attributes stay as
        # the BOTTOM layer — `Law 1`, and the existing two-argument constructor
        # keeps working unchanged.
        self.limit_key = limit_key
        self.window_key = window_key
        self._log: Dict[str, List[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = max(window_seconds * 2, 120)

    def effective(self, owner: str | None = None) -> tuple:
        """`(max_requests, window_seconds)` resolved now.

        **role profile -> instance setting -> the constructor's value.**
        Settings-only, with no environment leg: none of these four throttles
        had a `PANTHEON_*` variable before `P12-05b`, so `Law 1` requires
        nothing, and adding four would be four more places the same number can
        be set (`Law 13`).

        `minimum=1` on both, and that floor is the point. `FORBIDDEN.md`
        Part 2 lists the auth rate limiters as a control that never lifts;
        making the number policy is a different act from removing the limiter,
        and a resolver that could return 0 would erase the difference.
        """
        max_requests, window = self.max_requests, self.window
        if self.limit_key or self.window_key:
            from src.settings import resolve_limit
            if self.limit_key:
                max_requests = resolve_limit(
                    self.limit_key, self.max_requests, owner=owner,
                    minimum=1, maximum=100_000)[0]
            if self.window_key:
                window = resolve_limit(
                    self.window_key, self.window, owner=owner,
                    minimum=1, maximum=86_400)[0]
        return max_requests, window

    def check(self, key: str, owner: str | None = None) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.monotonic()
        max_requests, window = self.effective(owner)
        with self._lock:
            self._maybe_cleanup(now, window)
            timestamps = self._log.get(key, [])
            cutoff = now - window
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= max_requests:
                self._log[key] = timestamps
                return False
            timestamps.append(now)
            self._log[key] = timestamps
            return True

    def _maybe_cleanup(self, now: float, window: float | None = None) -> None:
        """Periodically purge stale entries."""
        if window is None:
            window = self.window
        # A window that shrank must shrink the sweep with it, or entries are
        # held past the period anything counts them over.
        interval = max(window * 2, 120)
        if now - self._last_cleanup < min(interval, self._cleanup_interval):
            return
        self._last_cleanup = now
        cutoff = now - window
        stale = [k for k, v in self._log.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._log[k]


# ---------------------------------------------------------------------------
# Outbound politeness
# ---------------------------------------------------------------------------
#
# `RateLimiter` above protects Pantheon from the people who call it. Everything
# below protects Pantheon's *user* from the services Pantheon calls.
#
# This exists because on 2026-08-31 the owner imported a skill from a GitHub URL
# and GitHub soft-banned his IP. Nothing here was throttled: the importer walked
# a repository tree with no pacing, unauthenticated, opening a fresh TLS
# connection per file, identifying itself as `python-httpx`. That request shape
# is what abuse detection is built to catch, and it caught it.
#
# The audit that followed found the same gap everywhere. Two facts stood out:
#   * **Nothing in this codebase read `Retry-After`.** Not one call site. Servers
#     send it to tell you exactly how to stay welcome, and we ignored all of it.
#   * **Nothing had jitter.** Every recurring job fires on an exact boundary, so
#     every Pantheon install in the world hits a provider on the same second.
#
# The shape below is deliberately borrowed from `routes/device_flow.py`, which
# was the only correct outbound throttle in the tree: a `next_poll_at` per key
# and a `slow_down()` that obeys the server's own pacing signal. This keys the
# same idea by destination host instead of by poll session, which is the smallest
# change that makes it apply to everything.
#
# Deliberately NOT here:
#   * No env layer. `H06`/`B20` established that `get_setting` merges defaults on
#     every read, so an env var beneath an instance setting is dead code. Anyone
#     adding one to this module should read those rows first.
#   * No persistence. A restart forgets a cooldown, which is a real gap — filed
#     as `P15-09` rather than papered over here.

import email.utils
import random
from dataclasses import dataclass, field
from typing import Optional, Tuple


class OutboundRateLimited(Exception):
    """A host has told us to stop, and the wait is too long to sit through.

    Carries `retry_after` (seconds) and `host` so a caller can say *when* rather
    than the useless "try again in a bit" the skill importer used to print.
    """

    def __init__(self, host: str, retry_after: float, detail: str = ""):
        self.host = host
        self.retry_after = max(0.0, float(retry_after))
        self.detail = detail
        mins = self.retry_after / 60.0
        when = f"{self.retry_after:.0f} seconds" if self.retry_after < 90 else f"{mins:.0f} minutes"
        super().__init__(
            f"{host} has rate-limited us; not retrying for {when}."
            + (f" ({detail})" if detail else "")
        )


@dataclass
class HostPolicy:
    """How politely to treat one destination.

    `min_interval` is the floor between two requests to the same host, and it is
    the setting that matters most: abuse detection scores request *shape*, not
    just volume, so 64 requests spread over a minute is invisible where 64 in two
    seconds is not.
    """

    min_interval: float = 0.25        # seconds between requests to this host
    max_concurrent: int = 4           # simultaneous requests to this host
    jitter: float = 0.25              # fraction of min_interval, added randomly
    max_wait: float = 30.0            # sit through a cooldown up to this; then raise


# Hosts we know something specific about. Everything else takes the default,
# which is already stricter than "no limit at all" — the previous behaviour.
#
# GitHub's own guidance to API clients is to make requests serially and to wait
# at least one second between them. Unauthenticated api.github.com is 60 requests
# per HOUR, so a tree walk cannot be fast and be allowed; it can only be one or
# the other. With a token the quota is 5,000/hour and the pacing can relax, but
# the abuse detector does not care about your quota, so it never goes below 0.2s.
_HOST_POLICIES = {
    "api.github.com": HostPolicy(min_interval=1.0, max_concurrent=1, max_wait=10.0),
    "raw.githubusercontent.com": HostPolicy(min_interval=0.5, max_concurrent=1, max_wait=10.0),
    "github.com": HostPolicy(min_interval=1.0, max_concurrent=1, max_wait=10.0),
    "huggingface.co": HostPolicy(min_interval=0.5, max_concurrent=2),
    "html.duckduckgo.com": HostPolicy(min_interval=2.0, max_concurrent=1),
    "cdn.jsdelivr.net": HostPolicy(min_interval=0.05, max_concurrent=8),
}

# Applied when the caller says the request is authenticated: the quota is larger,
# so the floor drops — but never to zero, because abuse detection is separate
# from quota and is what actually issues the soft ban.
_AUTHENTICATED_FLOOR = 0.2

# --------------------------------------------------------------------------
# The operator's own machines are not a destination to be polite to (`P15-06`)
# --------------------------------------------------------------------------
#
# `D-2026-09-01-03`, in the owner's words: *"internal comms, LAN to LAN etc is
# totally fine. we arent building fort knox. just an orchestration harness."*
#
# This is not a nicety, it is what makes `P15-06` possible at all. Pacing exists
# because a third party runs abuse detection and will soft-ban a client whose
# request SHAPE looks wrong. A model server on the operator's own box runs none:
# the only thing a 0.25s floor buys there is 0.25s. Routing the local-first
# services through the limiter at the default policy would mean a 5,000-chunk
# RAG index paying 625 × 0.25s — over two and a half minutes of pure sleeping —
# and the first person to profile it would rip the limiter back out, correctly.
#
# So a local host is paced at zero AND STILL OBSERVED. If a local server does
# answer 429, that is a real signal from a real server and the cooldown applies
# exactly as it would to anyone else. What is dropped is the pre-emptive
# politeness, not the response handling.
LOCAL_POLICY = HostPolicy(min_interval=0.0, max_concurrent=32, jitter=0.0, max_wait=30.0)

_LOCAL_NAMES = frozenset({
    "localhost", "host.docker.internal", "gateway.docker.internal",
    # compose service names — inside the network Pantheon ships with
    "pantheon", "searxng", "chromadb", "chroma", "ntfy", "ollama",
})
_LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".localdomain", ".home.arpa")


def host_is_local(host: str) -> bool:
    """Is this address a machine the operator owns? Name and literal only.

    NO DNS. The limiter sits in front of every deliberate outbound call, and a
    resolver call there would add a lookup — and a failure mode — to the hot
    path of every request in the product. A hostname that resolves to a private
    address but is not named like one takes the ordinary policy, which is the
    safe direction to be wrong in: it is paced, not blocked.

    `not ip.is_global` rather than `is_private`, because a tailnet lives in
    100.64.0.0/10 (RFC 6598) which `is_private` reports as False. That mistake
    has been made twice in this codebase already.
    """
    host = (host or "").strip().strip("[]").lower()
    if not host:
        return False
    if host in _LOCAL_NAMES or host.endswith(_LOCAL_SUFFIXES):
        return True
    if "." not in host and ":" not in host:
        # A bare single-label name is a container or LAN name, not a public one.
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False


@dataclass
class _HostState:
    next_allowed_at: float = 0.0      # pacing gate
    blocked_until: float = 0.0        # hard cooldown, from the server's own signal
    consecutive_429: int = 0
    in_flight: int = 0
    last_detail: str = ""
    total_requests: int = 0
    total_waits: float = 0.0


def parse_retry_after(value: Optional[str], *, now: Optional[float] = None) -> Optional[float]:
    """Seconds to wait, from a `Retry-After` header.

    The header is legally either a count of seconds or an HTTP-date, and real
    servers send both. Reading only the integer form — which is the obvious
    implementation — silently ignores every date-form response, which is the
    half that tends to carry the long waits.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(int(raw)))
    except (TypeError, ValueError):
        pass
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        import datetime as _dt
        when = when.replace(tzinfo=_dt.timezone.utc)
    import datetime as _dt
    delta = (when - _dt.datetime.now(_dt.timezone.utc)).total_seconds()
    return max(0.0, delta)


def parse_reset_header(value: Optional[str], *, now: Optional[float] = None) -> Optional[float]:
    """Seconds to wait, from an `X-RateLimit-Reset` epoch timestamp.

    GitHub sends this instead of `Retry-After` on a primary rate-limit 403, so a
    client that reads only `Retry-After` learns nothing from the response that
    matters most.
    """
    if not value:
        return None
    try:
        reset_at = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    # Anything in the past, or absurdly far ahead, is not a usable signal.
    delta = reset_at - (now if now is not None else time.time())
    if delta <= 0 or delta > 24 * 3600:
        return None
    return delta


def _first_signal(*values: Optional[float]) -> Optional[float]:
    """First value that is actually present.

    `a or b` is the obvious way to write this and it is wrong here: a server may
    legitimately answer `Retry-After: 0` ("go ahead now"), and `0.0 or None` is
    `None`, so the clearest possible instruction reads as no instruction at all
    and earns a 60-second penalty backoff instead. Explicit `is None` it is.
    """
    for v in values:
        if v is not None:
            return v
    return None


# --------------------------------------------------------------------------
# Persistence (`P15-09`) — and the clock domain is the whole row.
# --------------------------------------------------------------------------
#
# `_HostState.blocked_until` is a `time.monotonic()` reading. Monotonic's origin
# is arbitrary and per-boot; on Linux it counts from boot. Writing that number
# to a file and reading it back in a new process compares it against a DIFFERENT
# origin, and the resulting bug is worse than wrong — it is *selectively* wrong.
#
#   * Restart after a REBOOT and the restored deadline is a large number
#     compared against a monotonic clock that has just started from zero, so
#     every cooldown reads as still active — or, with the subtraction the other
#     way round, as long expired. Either way the answer is unrelated to reality,
#     and a reboot is exactly what a crash-loop produces.
#   * Restart WITHOUT a reboot and monotonic has kept counting, so the naive
#     version appears to work perfectly.
#
# So it passes on the developer's box and fails on the machine that rebooted,
# which is the machine this row is about. The file stores a WALL-CLOCK deadline
# and the conversion happens on both sides.
_PERSIST_VERSION = 1

# A restored cooldown is capped. This is not policy about how long a host may
# block us — `observe` will honour a `Retry-After` of any length in-process. It
# is a bound on how much damage a corrupt file or a wall clock that moved can
# do: a stored deadline implying days from now is a broken clock, not a ban.
MAX_RESTORED_COOLDOWN = 24 * 3600

# THERE IS NO WRITE DEBOUNCE, DELIBERATELY.
#
# Adding one is the obvious optimisation and it would reintroduce the exact loss
# this row exists to fix: a penalty set and then a `kill -9` inside the debounce
# window is a penalty that never reached disk, and a crash is the common way
# this process ends when it is being rate limited. The write rate does not need
# it — a projection is only written when it CHANGES, blocks are rare, and the
# steady state on a healthy install is an empty projection that is never
# rewritten at all.


class OutboundHostLimiter:
    """Per-host pacing, concurrency and cooldown for calls we make out.

    Two entry points, one state:

        limiter.acquire(host)                  # sync callers (the skill importer)
        await limiter.acquire_async(host)      # async callers (search, llm_core)

    and one feedback point, which is the part that does the real work:

        limiter.observe(host, status_code, headers)

    `observe` is what turns a server's complaint into silence on our side. Call
    it on every response, not only the failures: a success clears the escalation
    ladder, so the next penalty starts from the base cooldown rather than from
    wherever the last bad run left it.

    IT DOES NOT CLEAR A HARD COOLDOWN, AND THE DIFFERENCE MATTERS (`B36`).

    An earlier version of this docstring said "a 200 is how a host tells us the
    cooldown is over", which the code has never done and should not: a
    `blocked_until` comes from the server's OWN instruction — a `Retry-After`,
    an `X-RateLimit-Reset` — and it expires on its own schedule. A 200 arriving
    while we believe the host is blocked means somebody bypassed `acquire`, and
    letting that erase the block would make the one caller who skips the gate
    able to un-ban the host for everybody else. The ladder is ours to reset; the
    deadline is the server's.

    `succeeded(key)` is the explicit "it worked, drop everything" for the
    `penalise` path, where the failure carried no expiry to wait out.
    """

    def __init__(self, policies: Optional[Dict[str, HostPolicy]] = None):
        self._policies = dict(policies if policies is not None else _HOST_POLICIES)
        self._default = HostPolicy()
        self._state: Dict[str, _HostState] = {}
        self._lock = threading.Lock()
        # `P15-09`. Loaded lazily rather than at startup on purpose: a load call
        # someone has to remember to make is a load call that gets forgotten in
        # one entry point, and the symptom of forgetting it — cooldowns that
        # silently do not apply — is the exact thing this row is fixing.
        self._loaded = False
        self._last_written: Optional[Dict[str, Dict[str, Any]]] = None

    # -- persistence (`P15-09`) -------------------------------------------
    def _state_path(self) -> str:
        """Resolved per call, not captured at import, so a test can move it."""
        from src.constants import OUTBOUND_STATE_FILE
        return OUTBOUND_STATE_FILE

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True                 # set first: a failed load must not retry forever
        try:
            self.load_persisted()
        except Exception as e:
            logger.debug("outbound state not restored: %s: %s", type(e).__name__, e)

    def load_persisted(self) -> int:
        """Restore cooldowns from disk. Returns how many were still live.

        Converts each wall-clock deadline back into this process's monotonic
        frame. Anything already expired is dropped rather than restored as a
        zero-length block, so the file shrinks on its own and a long shutdown
        leaves nothing behind.
        """
        import json
        path = self._state_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            return 0
        if not isinstance(doc, dict) or doc.get("version") != _PERSIST_VERSION:
            return 0
        entries = doc.get("hosts")
        if not isinstance(entries, dict):
            return 0

        wall_now = time.time()
        mono_now = time.monotonic()
        restored = 0
        with self._lock:
            for key, raw in entries.items():
                if not isinstance(key, str) or not isinstance(raw, dict):
                    continue
                try:
                    remaining = float(raw.get("until", 0)) - wall_now
                except (TypeError, ValueError):
                    continue
                if remaining <= 0:
                    continue
                remaining = min(remaining, MAX_RESTORED_COOLDOWN)
                st = self._st(key)
                st.blocked_until = max(st.blocked_until, mono_now + remaining)
                try:
                    # The ladder matters as much as the deadline. A crash-loop
                    # that resets `consecutive_429` re-earns the ban from the
                    # base cooldown every time, which is slower than not
                    # escalating at all.
                    st.consecutive_429 = max(st.consecutive_429, int(raw.get("n", 0) or 0))
                except (TypeError, ValueError):
                    pass
                detail = raw.get("why")
                if isinstance(detail, str) and detail and not st.last_detail:
                    st.last_detail = detail[:200]
                restored += 1
        if restored:
            logger.info("restored %d outbound cooldown(s) from %s", restored, path)
        return restored

    def _projection(self) -> Dict[str, Dict[str, Any]]:
        """The small, boring subset worth keeping. Caller must hold no lock."""
        mono_now = time.monotonic()
        wall_now = time.time()
        with self._lock:
            out: Dict[str, Dict[str, Any]] = {}
            for key, st in self._state.items():
                remaining = st.blocked_until - mono_now
                if remaining <= 0:
                    continue
                entry: Dict[str, Any] = {"until": round(wall_now + remaining, 3)}
                if st.consecutive_429:
                    entry["n"] = st.consecutive_429
                if st.last_detail:
                    entry["why"] = st.last_detail
                out[key] = entry
            return out

    def _persist(self) -> None:
        """Write the projection if it changed. Never holds the lock over I/O.

        Pacing state (`next_allowed_at`) and the per-process counters are
        deliberately absent. Pacing is sub-second and re-earned in one request;
        the counters feed `pantheon_outbound_*`, and carrying them across a
        restart would make a gauge that says "this process" quietly mean
        something else.
        """
        try:
            current = self._projection()
        except Exception:
            return
        # `_last_written` starts as None, which is NOT the same as `{}`: on the
        # first change we must write even when the projection is empty, because
        # a stale file from the previous run may still be on disk saying a host
        # is blocked when it is not.
        if self._last_written is not None and current == self._last_written:
            return
        path = self._state_path()
        if not current and not os.path.exists(path):
            # Nothing is blocked and there is no stale file to correct. An
            # install that has never been rate limited should not have this file
            # at all — creating one to say "nothing" leaves a permanent artefact
            # in the data directory for a state that is the default.
            self._last_written = current
            return
        try:
            from core.atomic_io import atomic_write_json
            atomic_write_json(path, {"version": _PERSIST_VERSION, "hosts": current})
            self._last_written = current
        except Exception as e:
            # A read-only data dir must not break outbound calls. The cooldown
            # still applies in this process; it just will not survive a restart.
            logger.debug("could not persist outbound state to %s: %s: %s",
                         path, type(e).__name__, e)

    # -- policy -----------------------------------------------------------
    def policy_for(self, host: str, *, authenticated: bool = False) -> HostPolicy:
        # An explicit policy wins even for a local name — an operator who wrote
        # one down meant it. Otherwise a local host is not paced (`P15-06`).
        key = (host or "").lower()
        if key not in self._policies and host_is_local(key):
            return LOCAL_POLICY
        pol = self._policies.get(key, self._default)
        if authenticated and pol.min_interval > _AUTHENTICATED_FLOOR:
            return HostPolicy(
                min_interval=_AUTHENTICATED_FLOOR,
                max_concurrent=pol.max_concurrent,
                jitter=pol.jitter,
                max_wait=pol.max_wait,
            )
        return pol

    def _st(self, host: str) -> _HostState:
        st = self._state.get(host)
        if st is None:
            st = _HostState()
            self._state[host] = st
        return st

    # -- the gate ---------------------------------------------------------
    def _plan(self, host: str, *, authenticated: bool) -> Tuple[float, HostPolicy]:
        """Decide how long to wait. Never sleeps while holding the lock."""
        self._ensure_loaded()
        pol = self.policy_for(host, authenticated=authenticated)
        now = time.monotonic()
        with self._lock:
            st = self._st(host)
            if st.blocked_until > now:
                wait = st.blocked_until - now
                if wait > pol.max_wait:
                    raise OutboundRateLimited(host, wait, st.last_detail)
                return wait, pol
            gap = pol.min_interval
            if pol.jitter:
                gap += random.uniform(0.0, pol.min_interval * pol.jitter)
            start_at = max(now, st.next_allowed_at)
            st.next_allowed_at = start_at + gap
            st.total_requests += 1
            wait = max(0.0, start_at - now)
            st.total_waits += wait
            return wait, pol

    def _check_scope(self, host: str) -> None:
        """`P16-16` — refuse an out-of-scope host before pacing it.

        The limiter is the one place every deliberately-paced outbound call
        passes through (`P15`), which makes it the cheapest place to put a
        second layer under the per-caller checks. It is a layer, not the
        boundary: a caller that does not pace is not caught here, which is why
        `url_safety` and `outbound_fetch` check independently.
        """
        try:
            from src.networks import require_host
            require_host(host, what="outbound request")
        except ImportError:
            pass

    def acquire(self, host: str, *, authenticated: bool = False) -> float:
        """Block until it is polite to call `host`. Returns seconds waited."""
        self._check_scope(host)
        waited = 0.0
        while True:
            wait, _pol = self._plan(host, authenticated=authenticated)
            if wait <= 0:
                return waited
            time.sleep(wait)
            waited += wait
            # A cooldown may have been lifted or extended while we slept; a hard
            # block is re-checked, ordinary pacing is not (we already paid it).
            with self._lock:
                if self._st(host).blocked_until <= time.monotonic():
                    return waited

    async def acquire_async(self, host: str, *, authenticated: bool = False) -> float:
        import asyncio

        self._check_scope(host)
        waited = 0.0
        while True:
            wait, _pol = self._plan(host, authenticated=authenticated)
            if wait <= 0:
                return waited
            await asyncio.sleep(wait)
            waited += wait
            with self._lock:
                if self._st(host).blocked_until <= time.monotonic():
                    return waited

    # -- feedback ---------------------------------------------------------
    def observe(self, host: str, status_code: int, headers: Optional[Dict[str, str]] = None,
                *, body_hint: str = "") -> Optional[float]:
        """Feed a response back in. Returns the cooldown imposed, if any.

        Three things count as *stop*, and only reading the first would have
        missed the one that banned us:
          * `429` — the ordinary case, usually with `Retry-After`.
          * `403` whose body mentions a rate or abuse limit — **GitHub's primary
            rate limit is a 403, not a 429**, and it carries `X-RateLimit-Reset`
            rather than `Retry-After`.
          * `X-RateLimit-Remaining: 0` on an otherwise fine response — the one
            signal that lets us stop *before* being told to.
        """
        self._ensure_loaded()
        hdrs = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        low = (body_hint or "").lower()
        cooldown: Optional[float] = None

        looks_limited = status_code == 429 or (
            status_code == 403
            and ("rate limit" in low or "abuse" in low or "secondary rate" in low
                 or hdrs.get("x-ratelimit-remaining") == "0")
        )

        if looks_limited:
            cooldown = _first_signal(
                parse_retry_after(hdrs.get("retry-after")),
                parse_reset_header(hdrs.get("x-ratelimit-reset")),
            )
        elif status_code < 400 and hdrs.get("x-ratelimit-remaining") == "0":
            # Quota spent but this request was served. Coast until the reset
            # rather than spending the next request discovering we are blocked.
            cooldown = parse_reset_header(hdrs.get("x-ratelimit-reset"))

        now = time.monotonic()
        with self._lock:
            st = self._st(host)
            if looks_limited:
                st.consecutive_429 += 1
                if cooldown is None:
                    # No usable signal. Back off geometrically rather than
                    # guessing small — the failure mode we are fixing is a
                    # client that assumed it could retry soon.
                    cooldown = min(60.0 * (2 ** (st.consecutive_429 - 1)), 3600.0)
                st.last_detail = (body_hint or "")[:200]
                st.blocked_until = max(st.blocked_until, now + cooldown)
            elif cooldown is not None:
                st.blocked_until = max(st.blocked_until, now + cooldown)
            elif status_code < 400:
                st.consecutive_429 = 0
                st.last_detail = ""
        self._persist()
        return cooldown

    def penalise(self, key: str, *, base: float = 60.0, cap: float = 1800.0,
                 reason: str = "") -> float:
        """Escalating cooldown for a failure that is not an HTTP response.

        `observe()` reads a status code and headers, which covers everything
        that speaks HTTP. Plenty of what this product calls does not: IMAP and
        SMTP logins, CalDAV, CardDAV. There "stop" arrives as a socket error or
        an auth rejection, and **repeated failing logins are exactly what mail
        providers lock accounts for** — so the protocol without a 429 is the one
        where retrying blindly costs the user the most.

        `key` need not be a hostname. Two accounts on the same provider fail
        independently — one mailbox with a stale password must not silence the
        other — so callers pass an account-scoped key. What the limiter needs is
        a stable name for *the thing that should stop being called*, and a
        hostname is only the common case of that.

        Returns the cooldown imposed.
        """
        self._ensure_loaded()
        now = time.monotonic()
        with self._lock:
            st = self._st(key)
            st.consecutive_429 += 1
            cooldown = min(base * (2 ** (st.consecutive_429 - 1)), cap)
            cooldown += random.uniform(0.0, cooldown * 0.2)
            if reason:
                st.last_detail = reason[:200]
            st.blocked_until = max(st.blocked_until, now + cooldown)
        # Outside the lock: `_persist` takes it again, and this is the write
        # that matters most — a lockout penalty is the one a crash-loop is
        # most likely to interrupt.
        self._persist()
        return cooldown

    def succeeded(self, key: str) -> None:
        """It worked. Clear the penalty ladder without forgetting the pacing."""
        self._ensure_loaded()
        with self._lock:
            st = self._st(key)
            st.consecutive_429 = 0
            st.blocked_until = 0.0
            st.last_detail = ""
        # A clear must reach disk too, or a restart resurrects a penalty the
        # provider has already forgiven — the same defect pointing the other way.
        self._persist()

    def note_failure(self, host: str, cooldown: float = 5.0) -> None:
        """A transport-level failure. Slow down, but do not treat it as a ban."""
        now = time.monotonic()
        with self._lock:
            self._st(host).next_allowed_at = max(self._st(host).next_allowed_at, now + cooldown)

    def blocked_for(self, host: str) -> float:
        """Seconds remaining on a hard cooldown; 0 when the host is callable."""
        self._ensure_loaded()
        with self._lock:
            return max(0.0, self._st(host).blocked_until - time.monotonic())

    def reset(self, host: Optional[str] = None) -> None:
        """Forget a cooldown, on disk as well as in memory.

        A reset that left the file behind would be undone by the next restart,
        which is a surprising way for an operator's "clear this" to not stick.
        `_loaded` is left alone: reloading here would restore what was just
        cleared.
        """
        with self._lock:
            if host is None:
                self._state.clear()
            else:
                self._state.pop(host, None)
        self._loaded = True
        self._persist()

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        """What the limiter is doing, for the settings page and for tests."""
        self._ensure_loaded()
        now = time.monotonic()
        with self._lock:
            return {
                host: {
                    "blocked_for": max(0.0, st.blocked_until - now),
                    "consecutive_429": float(st.consecutive_429),
                    "requests": float(st.total_requests),
                    "seconds_waited": round(st.total_waits, 3),
                }
                for host, st in self._state.items()
            }


# One limiter for the process. Politeness is a property of the destination, not
# of the feature calling it, so a per-feature limiter would let two features
# each stay under the limit and jointly blow through it — which is exactly how
# the importer and the cookbook's GitHub calls could collide today.
outbound = OutboundHostLimiter()


def host_of(url: str) -> str:
    """Hostname for limiter keying. Empty string when there isn't one."""
    from urllib.parse import urlparse

    try:
        return (urlparse(url).hostname or "").lower()
    except (ValueError, AttributeError):
        return ""
