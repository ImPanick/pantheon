# SPDX-License-Identifier: AGPL-3.0-or-later
"""One place that decides when a recurring job actually fires (`P15-10`).

The audit that opened `P15` found this, and the finding is easy to under-read:

    grep -rnE "jitter|random\\.uniform|random\\.randint" src/ routes/ services/ app.py

returned nothing but a comment. Every recurring job in the product fired on an
exact boundary. The seeded email tasks all sat on minute `0`; the nightly skill
audit ran at exactly 02:00 local; the background poll ticked on a round sixty
seconds from process start.

WHY THAT MATTERS EVEN THOUGH EACH ONE IS HARMLESS.

Within one install the limiter (`P15-03`) already paces whatever these jobs
send, so nothing here fixes a local burst. The problem is **across installs**.
Every Pantheon on earth hits the top of the hour at the same instant, so a
shared provider — Gmail, Outlook, a CalDAV host, a model API — sees one spike
per hour rather than a flat rate, and spikes are what abuse detection scores on.
The second, sharper case is an outage: a provider goes down, every client fails
at once, and every client comes back at the same synchronised moment. That is
how a soft failure becomes a hard one, and it is invisible from inside any
single install, which is why it survived until an audit went looking.

SPREAD, NOT DELAY.

Everything below adds a *positive* offset to a nominal time and never subtracts.
A job asked to run hourly still runs hourly; it simply does not run at `:00:00`.
Subtracting would make a job fire early, which for anything driven by a cron
expression means firing twice in one period.

WHAT IS DELIBERATELY NOT JITTERED, AND WHY THAT LIST MATTERS AS MUCH:

  * **The scheduler's own tick.** `TaskScheduler._loop` wakes near the next
    due-time boundary on purpose — a fix for `* * * * *` tasks that used to
    fire up to a minute late. Jittering the dispatcher would put that lateness
    back. The jitter belongs on the individual task, which is where it is.
  * **A manual "Run now".** A person is watching. Spreading load is not worth
    a button that appears not to work.
  * **`llm_core`'s flat connect/read-timeout retries.** They are 0.5s and
    bounded by a small attempt count; spreading half a second across installs
    buys nothing measurable. Its geometric 429 backoff IS jittered, because a
    provider rate-limiting everyone at once is exactly the synchronising event
    described above.
"""
import random
from datetime import datetime, timedelta
from typing import Optional

# Default spread as a fraction of the interval. Ten percent is enough to smear a
# boundary across installs and small enough that a job's cadence still reads as
# the number the operator configured.
DEFAULT_FRACTION = 0.1

# Ceiling on any single spread. A daily job at 10% would be spread over two and
# a half hours, which stops being jitter and starts being a different schedule.
MAX_SPREAD_SECONDS = 300.0


def spread(seconds: float) -> float:
    """A uniform offset in `[0, seconds)`. The primitive everything else uses."""
    seconds = max(0.0, float(seconds))
    if seconds <= 0:
        return 0.0
    return random.uniform(0.0, seconds)


def jittered(interval: float, *, fraction: float = DEFAULT_FRACTION,
             cap: float = MAX_SPREAD_SECONDS) -> float:
    """`interval` plus up to `fraction` of it, capped.

    Returns a float suitable for handing straight to `asyncio.sleep`. Never
    less than `interval`, so a caller's own minimum is preserved.
    """
    interval = max(0.0, float(interval))
    return interval + spread(min(cap, interval * max(0.0, fraction)))


async def sleep_jittered(interval: float, *, fraction: float = DEFAULT_FRACTION,
                         cap: float = MAX_SPREAD_SECONDS) -> float:
    """`await asyncio.sleep(jittered(interval))`. Returns what it slept.

    The one-line form exists so the call site reads as an intention rather than
    as arithmetic, and so a test can find every recurring sleep by name.
    """
    import asyncio
    delay = jittered(interval, fraction=fraction, cap=cap)
    await asyncio.sleep(delay)
    return delay


def next_daily_run(hour: int, minute: int = 0, *,
                   spread_seconds: float = MAX_SPREAD_SECONDS,
                   now: Optional[datetime] = None) -> float:
    """Seconds until the next `hour:minute`, plus a spread.

    For the nightly jobs. `02:00` is the single worst time to pick, because it
    is the time everyone picks — and a nightly job is the one whose spike lands
    when nobody is awake to notice it did.
    """
    now = now or datetime.now()
    nxt = now.replace(hour=int(hour) % 24, minute=int(minute) % 60,
                      second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return max(0.0, (nxt - now).total_seconds()) + spread(spread_seconds)
