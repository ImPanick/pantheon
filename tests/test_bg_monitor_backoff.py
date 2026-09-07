# SPDX-License-Identifier: AGPL-3.0-or-later
"""A failed background follow-up must not come back in five seconds, forever.

`_loop` polls every 5s and `mark_followed_up` runs only when `_run_followup`
returns True, so a follow-up whose model call 429s used to be retried on every
tick indefinitely -- 720 attempts an hour, each allowed up to 12 model rounds,
each round able to call `web_search`. Unattended. The idempotency was correct;
the pacing did not exist.
"""
import time

import pytest

import src.bg_monitor as bg


@pytest.fixture(autouse=True)
def _clean_backoff_state():
    """`_followup_failures` is module-level and would leak between tests.

    Every test below uses a distinct job id, so today this changes nothing --
    it is here because the *next* test to reuse an id would fail only in a full
    sweep and pass alone, and this project has already paid for that lesson once.
    """
    bg._followup_failures.clear()
    yield
    bg._followup_failures.clear()


def test_a_fresh_job_is_ready_immediately():
    now = time.monotonic()
    assert bg._followup_ready("never-seen", now)


def test_a_failed_job_is_not_retried_on_the_next_tick():
    """The whole bug in one assertion: the next tick is 5 seconds away."""
    now = time.monotonic()
    bg._note_followup_failure("job-a", now)
    assert not bg._followup_ready("job-a", now + bg.POLL_INTERVAL_S), (
        "a failed follow-up was ready again on the very next 5-second tick"
    )


def test_the_delay_grows_with_each_failure():
    now = time.monotonic()
    delays = [bg._note_followup_failure("job-b", now) for _ in range(4)]
    assert delays == sorted(delays), delays
    assert delays[-1] > delays[0] * 3, f"barely escalating: {delays}"


def test_the_delay_is_capped():
    now = time.monotonic()
    for _ in range(30):
        delay = bg._note_followup_failure("job-c", now)
    # Jitter is added on top of the cap by design, so allow for it.
    assert delay <= bg._FOLLOWUP_BACKOFF_MAX_S * 1.25, delay


def test_two_jobs_back_off_independently():
    now = time.monotonic()
    bg._note_followup_failure("job-d", now)
    assert bg._followup_ready("job-e", now), "one job's failure paused an unrelated job"


def test_success_clears_the_backoff():
    now = time.monotonic()
    bg._note_followup_failure("job-f", now)
    bg._clear_followup_failure("job-f")
    assert bg._followup_ready("job-f", now)


def test_it_eventually_gives_up_rather_than_retrying_forever():
    """An unreachable provider must not leave a job retrying until the heat death."""
    now = time.monotonic()
    for _ in range(bg._FOLLOWUP_GIVE_UP_AFTER):
        bg._note_followup_failure("job-g", now)
    assert bg._followup_failures["job-g"][0] >= bg._FOLLOWUP_GIVE_UP_AFTER


def test_the_backoff_has_jitter():
    """Every install recovering from one provider outage at the same instant
    reproduces the outage. Two jobs failing together must not come back together."""
    now = time.monotonic()
    seen = {bg._note_followup_failure(f"jitter-{i}", now) for i in range(12)}
    assert len(seen) > 1, "every first-failure delay was identical"


def test_the_first_delay_is_far_longer_than_a_tick():
    now = time.monotonic()
    delay = bg._note_followup_failure("job-h", now)
    assert delay >= bg.POLL_INTERVAL_S * 4, (
        f"first backoff of {delay:.0f}s is not meaningfully slower than the {bg.POLL_INTERVAL_S}s tick"
    )
