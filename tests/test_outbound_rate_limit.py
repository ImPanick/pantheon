# SPDX-License-Identifier: AGPL-3.0-or-later
"""Politeness to other people's servers, proved rather than asserted.

Written on 2026-08-31, the day GitHub soft-banned the owner's IP for importing a
skill. The importer walked a repository tree unauthenticated, at wire speed, one
fresh TLS connection per file, identifying itself as `python-httpx`. Nothing in
the codebase was throttled and — the fact that made it inevitable — **nothing in
the codebase read `Retry-After`**, at any call site.

So these tests are mostly about the response path, not the request path. Pacing
is the easy half. The half that gets you unbanned is hearing "stop" correctly,
including in the two forms that are easy to miss:

  * GitHub's **primary** rate limit is a `403`, not a `429`, and it carries
    `X-RateLimit-Reset` rather than `Retry-After`.
  * A plain `403` that is *not* a rate limit must not be mistaken for one, or a
    permission error silences a host for an hour.
"""
import time

import pytest

from src.rate_limiter import (
    HostPolicy,
    OutboundHostLimiter,
    OutboundRateLimited,
    host_of,
    parse_retry_after,
    parse_reset_header,
)


def _fast(**kw) -> OutboundHostLimiter:
    """A limiter whose numbers are small enough to assert against in a test."""
    pol = HostPolicy(min_interval=kw.pop("min_interval", 0.05), max_concurrent=4,
                     jitter=kw.pop("jitter", 0.0), max_wait=kw.pop("max_wait", 30.0))
    return OutboundHostLimiter({"example.test": pol})


# --------------------------------------------------------------------------
# Reading the server's own instructions
# --------------------------------------------------------------------------

def test_retry_after_reads_the_seconds_form():
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after("0") == 0.0


def test_retry_after_reads_the_http_date_form():
    """The half an obvious implementation drops.

    `Retry-After` is legally either a delta-seconds or an HTTP-date, and real
    servers send both. `int(value)` handles one and silently returns None for
    the other -- and the date form is the one that tends to carry long waits.
    """
    soon = time.time() + 300
    stamp = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(soon))
    got = parse_retry_after(stamp)
    assert got is not None
    assert 240 <= got <= 360, got


def test_retry_after_ignores_nonsense():
    for bad in (None, "", "   ", "soon", "-", "Tuesday"):
        assert parse_retry_after(bad) is None


def test_reset_header_reads_a_future_epoch():
    got = parse_reset_header(str(time.time() + 600))
    assert got is not None and 540 <= got <= 660


def test_reset_header_ignores_the_past_and_the_absurd():
    assert parse_reset_header(str(time.time() - 60)) is None      # already over
    assert parse_reset_header(str(time.time() + 90000)) is None   # >24h, not a real signal
    assert parse_reset_header("not-a-number") is None
    assert parse_reset_header(None) is None


# --------------------------------------------------------------------------
# Pacing
# --------------------------------------------------------------------------

def test_two_calls_to_one_host_are_spaced():
    lim = _fast(min_interval=0.05)
    start = time.monotonic()
    lim.acquire("example.test")
    lim.acquire("example.test")
    lim.acquire("example.test")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.10, f"three calls took {elapsed:.3f}s; the floor is two gaps of 0.05"


def test_the_first_call_to_a_host_is_never_delayed():
    """Pacing must not tax the common case of a single request."""
    lim = _fast(min_interval=5.0)
    start = time.monotonic()
    lim.acquire("example.test")
    assert time.monotonic() - start < 0.5


def test_hosts_do_not_block_each_other():
    lim = _fast(min_interval=5.0)
    start = time.monotonic()
    lim.acquire("a.test")
    lim.acquire("b.test")
    lim.acquire("c.test")
    assert time.monotonic() - start < 0.5, "an unrelated host paid another host's interval"


def _scheduled_gaps(lim, host, n=8):
    """The gaps the limiter *planned*, not the gaps the clock happened to show.

    Timing this with `time.monotonic()` around `acquire` looks equivalent and is
    not: scheduler noise alone makes measured elapsed times differ, so a
    wall-clock version of this test passes with jitter switched off entirely.
    It did, until a mutation run caught it. Read the plan instead.
    """
    gaps = []
    for _ in range(n):
        before = lim._state.get(host)
        before_at = before.next_allowed_at if before else 0.0
        lim._plan(host, authenticated=False)
        gaps.append(lim._state[host].next_allowed_at - before_at)
    return gaps[1:]   # the first has no predecessor to be spaced from


def test_jitter_makes_the_gap_vary():
    """Every install firing on the same boundary is how one outage becomes many."""
    jittered = _scheduled_gaps(OutboundHostLimiter({"j.test": HostPolicy(min_interval=0.02, jitter=1.0)}), "j.test")
    assert len(set(round(g, 9) for g in jittered)) > 1, "no jitter: every planned gap identical"


def test_no_jitter_means_exactly_the_interval():
    """The control for the test above -- proves it can tell the two apart."""
    flat = _scheduled_gaps(OutboundHostLimiter({"j.test": HostPolicy(min_interval=0.02, jitter=0.0)}), "j.test")
    assert len(set(round(g, 9) for g in flat)) == 1, f"gaps drifted without jitter: {flat}"
    assert abs(flat[0] - 0.02) < 1e-9


def test_authenticated_calls_get_a_lower_floor_but_not_zero():
    lim = OutboundHostLimiter({"api.github.com": HostPolicy(min_interval=1.0)})
    assert lim.policy_for("api.github.com").min_interval == 1.0
    authed = lim.policy_for("api.github.com", authenticated=True).min_interval
    assert 0 < authed < 1.0, "a token raises the quota; it does not switch off abuse detection"


# --------------------------------------------------------------------------
# Hearing "stop"
# --------------------------------------------------------------------------

def test_429_with_retry_after_sets_that_cooldown():
    lim = _fast()
    got = lim.observe("example.test", 429, {"Retry-After": "45"})
    assert got == 45.0
    assert 40 < lim.blocked_for("example.test") <= 45


def test_github_style_403_rate_limit_is_recognised():
    """The exact response that banned us. A 403 with a reset header, no 429."""
    lim = _fast()
    reset = str(time.time() + 900)
    got = lim.observe(
        "example.test", 403,
        {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset},
        body_hint="API rate limit exceeded for 1.2.3.4.",
    )
    assert got is not None and got > 600, got
    assert lim.blocked_for("example.test") > 600


def test_a_plain_403_is_not_treated_as_a_rate_limit():
    """A private repo must not silence github.com for an hour."""
    lim = _fast()
    assert lim.observe("example.test", 403, {}, body_hint="Not Found") is None
    assert lim.blocked_for("example.test") == 0


def test_a_404_is_not_a_rate_limit():
    lim = _fast()
    assert lim.observe("example.test", 404, {}) is None
    assert lim.blocked_for("example.test") == 0


def test_exhausted_quota_on_a_successful_response_still_stops_us():
    """The one signal that lets us stop *before* being told to."""
    lim = _fast()
    got = lim.observe("example.test", 200,
                      {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(time.time() + 300)})
    assert got is not None and got > 200
    assert lim.blocked_for("example.test") > 200


def test_no_signal_at_all_backs_off_geometrically():
    """A 429 with no header is the case where guessing small is worst."""
    lim = _fast()
    assert lim.observe("example.test", 429, {}) == 60.0
    assert lim.observe("example.test", 429, {}) == 120.0, "a repeat 429 must cost more"
    assert lim.observe("example.test", 429, {}) == 240.0


def test_success_clears_the_escalation():
    """No `reset()` in here, deliberately.

    An earlier version of this test called `lim.reset(host)` between the 429 and
    the 200 to clear the cooldown -- and `reset()` clears the escalation counter
    too, so the test's own setup did the work the assertion was checking for.
    It passed with the clearing logic deleted. A mutation run caught it.
    """
    lim = _fast()
    assert lim.observe("example.test", 429, {}) == 60.0
    assert lim.observe("example.test", 429, {}) == 120.0
    lim.observe("example.test", 200, {})
    assert lim.observe("example.test", 429, {}) == 60.0, "a 200 did not reset the ladder"


def test_a_long_cooldown_raises_instead_of_sleeping_through_it():
    """Sitting through a ban is not politeness, it is a hung request.

    The cooldown here is deliberately only 3 seconds against a 0.5s ceiling. A
    larger number would read better but would make the *failure* mode a hang
    rather than a failed assertion -- if `max_wait` ever stops being honoured,
    this test must go red in seconds, not occupy a CI worker for a quarter hour.
    """
    lim = _fast(max_wait=0.5)
    lim.observe("example.test", 429, {"Retry-After": "3"})
    started = time.monotonic()
    with pytest.raises(OutboundRateLimited) as caught:
        lim.acquire("example.test")
    assert time.monotonic() - started < 1.0, "it slept instead of raising"
    assert caught.value.host == "example.test"
    assert caught.value.retry_after > 2


def test_the_message_says_when_not_in_a_bit():
    """The old text was 'try again in a bit', which is what made people click again."""
    lim = _fast(max_wait=0.5)
    lim.observe("example.test", 429, {"Retry-After": "900"})
    with pytest.raises(OutboundRateLimited) as caught:
        lim.acquire("example.test")
    assert "minutes" in str(caught.value)
    assert "in a bit" not in str(caught.value)


def test_retry_after_zero_means_now_not_missing():
    """`a or b` gets this wrong and the bug is invisible.

    A server may legitimately answer `Retry-After: 0` -- go ahead now. Written as
    `parse_retry_after(...) or parse_reset_header(...)`, that `0.0` is falsy, the
    signal is read as absent, and the clearest instruction a server can give
    earns the 60-second penalty reserved for servers that said nothing at all.
    """
    lim = _fast()
    got = lim.observe("example.test", 429, {"Retry-After": "0"})
    assert got == 0.0, f"a zero Retry-After was swallowed and became {got}"
    assert lim.blocked_for("example.test") == 0


def test_a_short_cooldown_is_waited_out():
    lim = _fast(max_wait=30.0)
    lim.observe("example.test", 429, {"Retry-After": "0"})
    lim.acquire("example.test")   # must not raise


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------

def test_host_of_extracts_the_key():
    assert host_of("https://api.github.com/repos/a/b/contents?ref=main") == "api.github.com"
    assert host_of("HTTPS://RAW.GithubUserContent.com/x") == "raw.githubusercontent.com"
    assert host_of("not a url") == ""
    assert host_of("") == ""


def test_github_ships_with_a_real_policy():
    """Not a default. The shipped numbers are the fix; a default would be a hope."""
    from src.rate_limiter import outbound

    pol = outbound.policy_for("api.github.com")
    assert pol.min_interval >= 1.0, "GitHub asks for a second between serial requests"
    assert pol.max_concurrent == 1, "GitHub asks for serial requests"


def test_the_limiter_is_shared_process_wide():
    """Per-feature limiters would each stay under the limit and jointly exceed it."""
    from src.rate_limiter import outbound as a
    from src.rate_limiter import outbound as b

    assert a is b
