# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1505` — a stale built-in is repaired in place by one reconcile, and no
second copy of it is seeded beside it.

**Measured before this file:** `ensure_defaults` runs on a session made with
`autoflush=False` (`core.database.SessionLocal`). Its first loop writes
`task_type="action"` and the built-in's `action` onto a stale row (`B1495`'s
repair), but the two queries after it — `existing_actions` (what is already
there, so not seeded) and `builtin_tasks` (what is deduped and normalised) —
read the database, where the row is still the old shape. So that reconcile
seeded a fresh *Memory Tidy* beside the repaired *Tidy Memory*, and the next
one kept one of the two by score and `db.delete`d the other, with its run
history.

Driven (`Law 20`): the real `ensure_defaults` over a real SQLite file with
`autoflush=False`, as the product's own session is (`B1063`'s world).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_your_own_housekeeping_task_is_kept import (  # noqa: E402,F401
    OWNER, _reconcile, _rows, world,
)


def _stale(factory):
    """A built-in from before `task_type` / `action` were written: legacy
    name, no action, no prompt, and a run of its own."""
    from core.database import ScheduledTask, TaskRun
    db = factory()
    db.add(ScheduledTask(id="old", owner=OWNER, name="Tidy Memory", task_type="llm",
                         status="active", trigger_type="event"))
    db.add(TaskRun(id="old-run", task_id="old", status="success", result="tidied"))
    db.commit()
    db.close()


def _memory_tidies(factory):
    return sorted(
        (t.id, t.name) for t in _rows(factory).values() if t.action == "consolidate_memory"
    )


def test_one_reconcile_repairs_the_stale_row_in_place_and_seeds_no_second(world):
    factory, s, _client, _ran = world
    _stale(factory)
    _reconcile(s)
    assert _memory_tidies(factory) == [("old", "Memory Tidy")], (
        "the reconcile that repaired the stale row also seeded a fresh built-in "
        "beside it — it read the database before its own repair reached it")


def test_the_next_reconcile_keeps_the_repaired_row_and_its_run_history(world):
    from core.database import TaskRun
    factory, s, _client, _ran = world
    _stale(factory)
    _reconcile(s)
    _reconcile(s)                                    # the next boot
    assert _memory_tidies(factory) == [("old", "Memory Tidy")]
    db = factory()
    try:
        assert db.query(TaskRun).filter(TaskRun.id == "old-run").count() == 1, (
            "the repaired built-in's run history was deleted with it")
    finally:
        db.close()
