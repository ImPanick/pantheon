# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P6-08` — the configured concurrency cap has to be the one that governs.

The row's tick was withdrawn on 2026-08-31 because both load-bearing clauses of
its trace were false. `H06` fixed the first (the env leg was unreachable code
from first boot). This is the second: *"re-read on settings change without a
restart"* was not wired. `_refresh_concurrency_cap` had exactly one caller,
inside `start()`, so the number a running scheduler used was the number it
booted with — and it could not have had another caller, because it worked by
REBUILDING `asyncio.Semaphore`, which silently abandons every run already
parked on the old object.

So the test that carries this row is not "a variable was read". It parks real
work on the real semaphore, changes the setting underneath a scheduler that is
already running, and measures how many runs overlap. On the tree as it stood,
the three waiting runs were parked on a semaphore nobody held a reference to
any more and the observed concurrency never moved.
"""
import asyncio
import importlib

import pytest

from src import task_scheduler as TS


@pytest.fixture
def datadir(tmp_path, monkeypatch):
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(TS.TASK_CONCURRENCY_CAP_ENV, raising=False)
    import src.constants, src.settings
    importlib.reload(src.constants)
    importlib.reload(src.settings)
    yield tmp_path
    monkeypatch.delenv("PANTHEON_DATA_DIR", raising=False)
    importlib.reload(src.constants)
    importlib.reload(src.settings)


def _store(**kw):
    import src.settings as S
    S.save_settings(dict(S.DEFAULT_SETTINGS, **kw))
    S._invalidate_caches()


class _Slot:
    """Counts how many runs hold the model slot at once, through the real
    `async with self._run_semaphore` the scheduler dispatches under."""

    def __init__(self, scheduler):
        self.sched = scheduler
        self.live = 0
        self.peak = 0
        self.finished = 0
        self.release = asyncio.Event()

    async def run(self):
        async with self.sched._run_semaphore:
            self.live += 1
            self.peak = max(self.peak, self.live)
            await self.release.wait()
            self.live -= 1
            self.finished += 1

    def start(self, n):
        return [asyncio.create_task(self.run()) for _ in range(n)]


async def _settle():
    """Let every task that can make progress make it."""
    for _ in range(12):
        await asyncio.sleep(0)


# ── the cap governs ──

async def test_the_shipped_default_serialises_model_runs(datadir):
    sched = TS.TaskScheduler(None)
    assert sched._concurrency_cap == 1
    slot = _Slot(sched)
    handles = slot.start(4)
    await _settle()
    assert slot.peak == 1
    slot.release.set()
    await asyncio.gather(*handles)


async def test_a_configured_cap_lets_that_many_overlap(datadir):
    _store(task_concurrency_cap=4)
    sched = TS.TaskScheduler(None)
    assert (sched._concurrency_cap, sched._concurrency_cap_source) == \
        (4, "instance setting")
    slot = _Slot(sched)
    handles = slot.start(6)
    await _settle()
    assert slot.peak == 4
    slot.release.set()
    await asyncio.gather(*handles)


# ── the row: without a restart, and without dropping the queue ──

async def test_raising_the_cap_starts_the_runs_already_queued(datadir):
    """The withdrawn clause, driven. Four runs, cap 1: one holds the slot and
    three are parked. The operator raises the cap; the three parked runs start
    without the one in flight finishing and without a process restart.

    On the old implementation `_refresh_concurrency_cap` built a NEW semaphore,
    so the three waiters were left on an object the scheduler no longer had —
    `peak` stayed at 1 until the first run finished."""
    sched = TS.TaskScheduler(None)
    slot = _Slot(sched)
    handles = slot.start(4)
    await _settle()
    assert (slot.peak, slot.finished) == (1, 0)

    _store(task_concurrency_cap=4)
    assert sched._refresh_concurrency_cap() == 4
    await _settle()

    assert slot.finished == 0, "nothing finished; the queue simply widened"
    assert slot.live == 4
    assert slot.peak == 4
    slot.release.set()
    await asyncio.gather(*handles)


async def test_lowering_the_cap_drains_rather_than_killing_runs(datadir):
    """A permit a run holds is not ours to take back. Lowering acquires the
    surplus, which parks behind the work in flight — no run is interrupted and
    the slot narrows as they finish."""
    _store(task_concurrency_cap=4)
    sched = TS.TaskScheduler(None)
    first = _Slot(sched)
    handles = first.start(4)
    await _settle()
    assert first.peak == 4

    _store(task_concurrency_cap=1)
    assert sched._refresh_concurrency_cap() == 1
    await _settle()
    assert first.live == 4, "a running task must not be evicted by a cap change"

    first.release.set()
    await asyncio.gather(*handles)
    await _settle()

    second = _Slot(sched)
    more = second.start(3)
    await _settle()
    assert second.peak == 1, "the drained slot admits one run at a time"
    second.release.set()
    await asyncio.gather(*more)


async def test_a_cap_that_did_not_change_does_not_disturb_the_slot(datadir):
    sched = TS.TaskScheduler(None)
    slot = _Slot(sched)
    handles = slot.start(2)
    await _settle()
    for _ in range(3):
        assert sched._refresh_concurrency_cap() == 1
    await _settle()
    assert slot.peak == 1, "re-resolving an unchanged cap must add no permits"
    slot.release.set()
    await asyncio.gather(*handles)


# ── the settings-change path is every tick, not one writer ──

async def test_the_dispatch_tick_re_resolves_the_cap(datadir, monkeypatch):
    """`save_settings` has ~20 call sites and `data/settings.json` is also
    hand-edited, so a listener bolted to the admin endpoint is `Law 13`'s
    defect class. `_check_due_tasks` re-resolves before it touches the
    database — asserted by making the database raise and checking the cap moved
    anyway."""
    import core.database

    sched = TS.TaskScheduler(None)
    assert sched._concurrency_cap == 1
    _store(task_concurrency_cap=3)

    def _no_db():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(core.database, "SessionLocal", _no_db)
    with pytest.raises(RuntimeError):
        await sched._check_due_tasks()
    assert sched._concurrency_cap == 3


# ── the layers below, which `H06` made reachable ──

async def test_the_env_var_still_wins_over_the_built_in_default(datadir, monkeypatch):
    monkeypatch.setenv(TS.TASK_CONCURRENCY_CAP_ENV, "5")
    cap, source = TS.resolve_task_concurrency_cap()
    assert (cap, source) == (5, TS.TASK_CONCURRENCY_CAP_ENV)


async def test_a_stored_choice_still_outranks_the_env_var(datadir, monkeypatch):
    monkeypatch.setenv(TS.TASK_CONCURRENCY_CAP_ENV, "5")
    _store(task_concurrency_cap=2)
    assert TS.resolve_task_concurrency_cap() == (2, "instance setting")


async def test_an_absurd_cap_is_clamped_before_it_reaches_the_slot(datadir):
    """Each concurrent run holds a model slot on the inference backend, so an
    unbounded value is a self-inflicted outage on a single-GPU host."""
    _store(task_concurrency_cap=9999)
    sched = TS.TaskScheduler(None)
    assert sched._concurrency_cap == TS.TASK_CONCURRENCY_CAP_MAX
    slot = _Slot(sched)
    handles = slot.start(TS.TASK_CONCURRENCY_CAP_MAX + 4)
    await _settle()
    assert slot.peak == TS.TASK_CONCURRENCY_CAP_MAX
    slot.release.set()
    await asyncio.gather(*handles)
