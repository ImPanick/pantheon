# src/rate_limiter.py
"""Generic in-memory rate limiter — sliding window, keyed by IP."""

import threading
import time
from typing import Dict, List


class RateLimiter:
    """Sliding-window rate limiter.

    Usage:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        if not limiter.check(ip):
            raise HTTPException(429, "Too many requests")
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._log: Dict[str, List[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = max(window_seconds * 2, 120)

    def check(self, key: str) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.monotonic()
        with self._lock:
            self._maybe_cleanup(now)
            timestamps = self._log.get(key, [])
            cutoff = now - self.window
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self.max_requests:
                self._log[key] = timestamps
                return False
            timestamps.append(now)
            self._log[key] = timestamps
            return True

    def _maybe_cleanup(self, now: float) -> None:
        """Periodically purge stale entries."""
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        cutoff = now - self.window
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


class OutboundHostLimiter:
    """Per-host pacing, concurrency and cooldown for calls we make out.

    Two entry points, one state:

        limiter.acquire(host)                  # sync callers (the skill importer)
        await limiter.acquire_async(host)      # async callers (search, llm_core)

    and one feedback point, which is the part that does the real work:

        limiter.observe(host, status_code, headers)

    `observe` is what turns a server's complaint into silence on our side. Call it
    on every response, not only the failures — a 200 is how a host tells us the
    cooldown is over.
    """

    def __init__(self, policies: Optional[Dict[str, HostPolicy]] = None):
        self._policies = dict(policies if policies is not None else _HOST_POLICIES)
        self._default = HostPolicy()
        self._state: Dict[str, _HostState] = {}
        self._lock = threading.Lock()

    # -- policy -----------------------------------------------------------
    def policy_for(self, host: str, *, authenticated: bool = False) -> HostPolicy:
        pol = self._policies.get((host or "").lower(), self._default)
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

    def acquire(self, host: str, *, authenticated: bool = False) -> float:
        """Block until it is polite to call `host`. Returns seconds waited."""
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
        now = time.monotonic()
        with self._lock:
            st = self._st(key)
            st.consecutive_429 += 1
            cooldown = min(base * (2 ** (st.consecutive_429 - 1)), cap)
            cooldown += random.uniform(0.0, cooldown * 0.2)
            if reason:
                st.last_detail = reason[:200]
            st.blocked_until = max(st.blocked_until, now + cooldown)
            return cooldown

    def succeeded(self, key: str) -> None:
        """It worked. Clear the penalty ladder without forgetting the pacing."""
        with self._lock:
            st = self._st(key)
            st.consecutive_429 = 0
            st.blocked_until = 0.0
            st.last_detail = ""

    def note_failure(self, host: str, cooldown: float = 5.0) -> None:
        """A transport-level failure. Slow down, but do not treat it as a ban."""
        now = time.monotonic()
        with self._lock:
            self._st(host).next_allowed_at = max(self._st(host).next_allowed_at, now + cooldown)

    def blocked_for(self, host: str) -> float:
        """Seconds remaining on a hard cooldown; 0 when the host is callable."""
        with self._lock:
            return max(0.0, self._st(host).blocked_until - time.monotonic())

    def reset(self, host: Optional[str] = None) -> None:
        with self._lock:
            if host is None:
                self._state.clear()
            else:
                self._state.pop(host, None)

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        """What the limiter is doing, for the settings page and for tests."""
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
