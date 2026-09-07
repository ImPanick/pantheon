"""No recurring job fires on an exact boundary (`P15-10`).

Two halves, and the second is the one that lasts.

The first proves the mechanism spreads and never runs a job early. The second is
about the CHECKER: `P15`'s opening audit found that not one recurring job in the
product had jitter, and that state did not arrive through a decision — nobody
chose an exact sixty seconds, it is simply what you write. So the tests that
matter break the guard in specific ways and assert it notices, because fixing
the call sites without leaving something behind guarantees the next loop
somebody adds is bare again.
"""
import ast
import asyncio
import pathlib
import shutil
import subprocess
import sys

import pytest

from src import jitter

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-jitter.py"


def run(cwd=ROOT):
    return subprocess.run([sys.executable, str(cwd / ".pantheon" / "check-jitter.py"),
                           "--quiet"], cwd=cwd, capture_output=True, text=True)


def _varies(values, *, what):
    """A range assertion alone is satisfied by the degenerate value.

    `0 <= v <= FALLBACK` passes when every `v` is `0`, and `3600 <= s <= 3600+N`
    passes when every `s` is exactly `3600` — which is the defect. Three
    mutations survived on precisely that before this existed.
    """
    distinct = {round(v, 6) for v in values}
    assert len(distinct) > 1, f"{what}: every value was identical ({distinct})"
    return distinct


# --------------------------------------------------------------------------
# The mechanism
# --------------------------------------------------------------------------

def test_a_job_is_spread_but_never_runs_early():
    """Positive offsets only. Subtracting would make a cron-driven job fire
    twice in one period, which is a worse failure than the one being fixed."""
    values = [jitter.jittered(60) for _ in range(400)]
    assert all(v >= 60 for v in values), "a job was scheduled EARLY"
    assert all(v <= 66 for v in values)
    assert len(set(values)) > 1, "no spread at all — every install fires together"


def test_the_spread_is_capped_so_a_daily_job_stays_daily():
    """Ten percent of a day is two and a half hours, which stops being jitter
    and starts being a different schedule."""
    day = 86400
    values = [jitter.jittered(day) for _ in range(200)]
    assert max(values) <= day + jitter.MAX_SPREAD_SECONDS


def test_zero_and_negative_intervals_do_not_produce_a_negative_sleep():
    assert jitter.jittered(0) == 0
    assert jitter.jittered(-5) == 0
    assert jitter.spread(0) == 0
    assert jitter.spread(-1) == 0


def test_the_nightly_helper_lands_after_the_hour_never_before():
    """02:00 is the single worst time to pick, because it is the time everyone
    picks. It must still be *after* 02:00 — a nightly job that creeps earlier
    each day walks backwards through the schedule."""
    from datetime import datetime
    now = datetime(2026, 9, 5, 1, 0, 0)
    values = [jitter.next_daily_run(2, now=now) for _ in range(200)]
    assert all(3600 <= s <= 3600 + jitter.MAX_SPREAD_SECONDS for s in values)
    _varies(values, what="the nightly job is still on the exact hour")
    assert max(values) > 3600 + 10, "the spread is too small to break the herd"


def test_the_nightly_helper_rolls_to_tomorrow_when_the_hour_has_passed():
    from datetime import datetime
    now = datetime(2026, 9, 5, 3, 0, 0)
    seconds = jitter.next_daily_run(2, now=now, spread_seconds=0)
    assert seconds == pytest.approx(23 * 3600, abs=1)


def test_sleep_jittered_actually_sleeps_what_it_reports(monkeypatch):
    slept = []

    async def _sleep(d):
        slept.append(d)
    monkeypatch.setattr(asyncio, "sleep", _sleep)
    got = asyncio.run(jitter.sleep_jittered(10))
    assert slept == [got] and got >= 10


# --------------------------------------------------------------------------
# The dispatch spread — scaled to the task's own period
# --------------------------------------------------------------------------

class _Task:
    def __init__(self, cron=None, schedule="cron"):
        self.schedule = schedule
        self.scheduled_time = None
        self.scheduled_day = None
        self.scheduled_date = None
        self.cron_expression = cron
        self.tz_name = None


def test_an_hourly_task_gets_a_useful_spread_and_a_minutely_one_gets_a_small_one():
    """Scaled to the period rather than flat: the herd this breaks is
    hourly-and-slower, while a `* * * * *` task delayed half a minute would
    start skipping periods once its own runtime is added."""
    pytest.importorskip("croniter")
    from datetime import datetime
    from src.task_scheduler import dispatch_hold, DISPATCH_JITTER_CAP_SECONDS

    # `now` is pinned to the moment a due task is actually dispatched — just
    # after its cron boundary — because the hold is 5% of the time until the
    # NEXT run and that period is what varies. Without this the test is flaky by
    # wall clock: an hourly task evaluated at :59 has a one-minute period and a
    # hold under three seconds, which is correct behaviour and fails an
    # assertion about hourly tasks. It went red once in a full sweep at ~:59
    # and passed alone every time, which is how a flaky test earns its place in
    # the ignore pile.
    at_the_boundary = datetime(2026, 9, 7, 10, 0, 1)
    hourly = [dispatch_hold(_Task("0 * * * *"), now=at_the_boundary) for _ in range(200)]
    minutely = [dispatch_hold(_Task("* * * * *"), now=at_the_boundary) for _ in range(200)]
    _varies(hourly, what="hourly tasks all dispatch together")
    _varies(minutely, what="minutely tasks all dispatch together")

    assert max(hourly) > 10, "an hourly task barely moved off the boundary"
    assert max(hourly) <= DISPATCH_JITTER_CAP_SECONDS
    assert max(minutely) <= 3.1, "a minute-cadence task was held long enough to skip"
    assert min(hourly) >= 0 and min(minutely) >= 0


def test_an_underivable_period_still_gets_a_small_spread():
    """A malformed cron, a one-shot, an event task deferred onto `next_run`. A
    few seconds is better than none and is safe against any cadence."""
    from src.task_scheduler import dispatch_hold, DISPATCH_JITTER_FALLBACK_SECONDS
    for task in (_Task("not a cron"), _Task(None, schedule="once"), _Task(None, schedule=None)):
        values = [dispatch_hold(task) for _ in range(50)]
        assert all(0 <= v <= DISPATCH_JITTER_FALLBACK_SECONDS for v in values)
        _varies(values, what="an underivable period got no spread at all")


def test_the_scheduled_dispatch_path_goes_through_the_hold():
    """`J8`: every test above exercised `dispatch_hold` and `_dispatch_after`
    directly, so replacing the call in `_check_due_tasks` with a bare
    `_execute_task` changed nothing any of them could see. The wiring needs its
    own assertion.

    On the AST because `_check_due_tasks` needs a database and a running
    scheduler to exercise, and because the comment beside the call names both
    functions — a substring search would pass either way.
    """
    tree = ast.parse((ROOT / "src" / "task_scheduler.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_check_due_tasks":
            dispatched = set()
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "create_task":
                    inner = call.args[0] if call.args else None
                    if isinstance(inner, ast.Call):
                        dispatched.add(getattr(inner.func, "attr", None))
            assert dispatched == {"_dispatch_after"}, \
                f"scheduled tasks dispatch via {dispatched or 'nothing'}, bypassing the spread"
            return
    raise AssertionError("_check_due_tasks not found")


def test_the_hold_is_awaited_before_the_task_runs():
    """And `_dispatch_after` must actually sleep it — a hold computed and then
    dropped is the same defect one level in."""
    tree = ast.parse((ROOT / "src" / "task_scheduler.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_dispatch_after":
            names = {getattr(c.func, "attr", None) or getattr(c.func, "id", None)
                     for c in ast.walk(node) if isinstance(c, ast.Call)}
            assert "sleep" in names and "_execute_task" in names
            return
    raise AssertionError("_dispatch_after not found")


def test_the_manual_run_path_is_not_held():
    """A person is watching. Spreading load is not worth a button that appears
    not to work — so the hold is in `_check_due_tasks`'s dispatch, not inside
    `_execute_task`, which is also the "Run now" path.

    Parsed rather than grepped: `_execute_task`'s docstring and the comments
    around it both mention the manual path.
    """
    tree = ast.parse((ROOT / "src" / "task_scheduler.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_execute_task":
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
                    assert name not in ("dispatch_hold", "sleep_jittered", "jittered"), \
                        "the manual Run-now path was given a spread"
            return
    raise AssertionError("_execute_task not found")


# --------------------------------------------------------------------------
# The checker — these break the guard and assert it notices
# --------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    dst = tmp_path / "repo"
    (dst / ".pantheon").mkdir(parents=True)
    (dst / "src").mkdir()
    # The real ALLOWED names files this synthetic tree does not contain, so
    # every entry would read as an orphan here. Strip it: the orphan rule is
    # tested by ADDING one below, which is the direction that matters.
    text = CHECKER.read_text(encoding="utf-8")
    start = text.index("ALLOWED = {")
    end = text.index("\n}\n", start) + len("\n}\n")
    (dst / ".pantheon" / "check-jitter.py").write_text(
        text[:start] + "ALLOWED = {}\n" + text[end:], encoding="utf-8")
    (dst / "app.py").write_text(
        "import asyncio\n"
        "async def fine():\n"
        "    from src.jitter import sleep_jittered\n"
        "    while True:\n"
        "        await sleep_jittered(60)\n",
        encoding="utf-8",
    )
    return dst


def test_the_real_tree_has_no_recurring_job_on_a_boundary():
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr


def test_fixture_baseline_passes(repo):
    """Every mutation below is measured against this passing."""
    r = run(repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_bare_sleep_in_a_forever_loop_fails(repo):
    (repo / "app.py").write_text(
        "import asyncio\n"
        "async def poll():\n"
        "    while True:\n"
        "        await asyncio.sleep(60)\n",
        encoding="utf-8",
    )
    r = run(repo)
    assert r.returncode == 1 and "BOUNDARY" in r.stdout


def test_a_bare_sleep_on_a_MODULE_CONSTANT_fails(repo):
    """`POLL_INTERVAL_S` is the shape this actually took in `bg_monitor`, and a
    check that only looked for numeric literals would have missed it."""
    (repo / "app.py").write_text(
        "import asyncio\n"
        "POLL_INTERVAL_S = 45\n"
        "async def poll():\n"
        "    while True:\n"
        "        await asyncio.sleep(POLL_INTERVAL_S)\n",
        encoding="utf-8",
    )
    r = run(repo)
    assert r.returncode == 1 and "BOUNDARY" in r.stdout


def test_a_while_self_running_loop_counts_too(repo):
    """`TaskScheduler`'s loops are `while self._running:`, not `while True:`."""
    (repo / "app.py").write_text(
        "import asyncio\n"
        "class S:\n"
        "    async def poll(self):\n"
        "        while self._running:\n"
        "            await asyncio.sleep(600)\n",
        encoding="utf-8",
    )
    r = run(repo)
    assert r.returncode == 1 and "BOUNDARY" in r.stdout


def test_a_COMPUTED_sleep_is_left_alone(repo):
    """The scheduler waking near the next due boundary, and a backoff derived
    from a response header, are both deliberate. A rule that could not tell
    those apart would be a rule people route around."""
    (repo / "app.py").write_text(
        "import asyncio\n"
        "async def poll():\n"
        "    while True:\n"
        "        sleep_for = compute()\n"
        "        await asyncio.sleep(sleep_for)\n"
        "        await asyncio.sleep(max(60, next_due()))\n",
        encoding="utf-8",
    )
    r = run(repo)
    assert r.returncode == 0, r.stdout


def test_a_one_shot_sleep_outside_a_loop_is_not_a_recurring_job(repo):
    (repo / "app.py").write_text(
        "import asyncio\n"
        "async def once():\n"
        "    await asyncio.sleep(20)\n",
        encoding="utf-8",
    )
    r = run(repo)
    assert r.returncode == 0, r.stdout


def test_an_allowlist_entry_that_matches_nothing_fails(repo):
    """The orphan rule, which caught five entries this file's own author wrote
    from reading the code rather than from running the check."""
    checker = repo / ".pantheon" / "check-jitter.py"
    text = checker.read_text(encoding="utf-8")
    text = text.replace("ALLOWED = {", 'ALLOWED = {\n    ("nowhere/at_all.py", "gone"): "stale",', 1)
    checker.write_text(text, encoding="utf-8")
    r = run(repo)
    assert r.returncode == 1 and "ORPHAN" in r.stdout


def test_the_allowlist_reasons_are_real_sentences_not_placeholders():
    """An allowlist whose entries say 'see above' is a list of exemptions
    pretending to be a list of decisions."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_check_jitter", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ALLOWED, "an empty allowlist here would be a lie"
    for key, reason in module.ALLOWED.items():
        assert isinstance(reason, str) and len(reason) > 40, f"{key} has no real reason"


# --------------------------------------------------------------------------
# The sites the row named by hand
# --------------------------------------------------------------------------

def test_the_nightly_skill_audit_no_longer_lands_on_the_exact_hour():
    """The row named this one: *the nightly skill audit runs at exactly 02:00
    local*. Parsed, because the comment above the fix says '02:00'."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_skill_audit_nightly_loop":
            calls = {getattr(c.func, "attr", None) or getattr(c.func, "id", None)
                     for c in ast.walk(node) if isinstance(c, ast.Call)}
            assert "next_daily_run" in calls, "still computing an exact wall-clock hour"
            for c in ast.walk(node):
                if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "replace":
                    raise AssertionError("still zeroing minute/second onto the hour")
            return
    raise AssertionError("_skill_audit_nightly_loop not found")


def test_the_browser_unread_poll_re_rolls_each_tick_rather_than_shifting_a_grid():
    """`setInterval` fires on a fixed grid, so jittering only the FIRST delay
    shifts the grid once and then keeps every tick exactly sixty seconds apart
    forever. A self-rescheduling timeout re-rolls, and drift is the point."""
    js = (ROOT / "static" / "js" / "emailInbox.js").read_text(encoding="utf-8")
    body = js[js.index("const _unreadJitter"):][:900]
    assert "setInterval(_refreshUnreadCount" not in js
    assert "Math.random()" in body
    assert "setTimeout" in body
