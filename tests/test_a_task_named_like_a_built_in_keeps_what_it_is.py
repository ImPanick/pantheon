# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1495` — a task a person names like a built-in keeps its type, its prompt
and its action through the built-ins' reconcile.

**Measured before this file:** the first loop of `ensure_defaults` took every
row of the owner's named as a built-in is, now or once (*Memory Tidy*, *Tidy
Memory*, …), and set `task_type="action"` and that built-in's `action` on it,
whatever it was — a repair for rows from before `task_type` / `action` were
written. So a Prompt task a person called "Memory Tidy" became a
`consolidate_memory` action on the next boot, and its prompt stopped running;
an action task of theirs by that name had its action swapped.

Now only the stale shape is repaired — a row with no action but that built-in's
and, with no action, no prompt — and a person's task by any name is theirs
(`B1063`). Driven (`Law 20`): the real `ensure_defaults` over a real SQLite file
(`B1063`'s world).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_your_own_housekeeping_task_is_kept import (  # noqa: E402,F401
    OWNER, _reconcile, _rows, world,
)


def _add(factory, **columns):
    from core.database import ScheduledTask
    db = factory()
    db.add(ScheduledTask(**{"owner": OWNER, "status": "active", "trigger_type": "webhook",
                            **columns}))
    db.commit()
    db.close()


def test_a_prompt_task_named_memory_tidy_keeps_its_type_and_prompt(world):
    factory, s, _client, _ran = world
    _add(factory, id="mine", name="Memory Tidy", task_type="llm",
         prompt="Summarise what I learned this week.")
    _reconcile(s)
    _reconcile(s)                                    # and again, as every boot does
    rows = _rows(factory)
    mine = rows["mine"]
    assert (mine.task_type, mine.action, mine.prompt) == (
        "llm", None, "Summarise what I learned this week."), (
        "the person's Prompt task was turned into the housekeeping action")
    # The built-in is its own row beside it.
    assert any(t.action == "consolidate_memory" and t.id != "mine" for t in rows.values())


def test_an_action_task_named_like_a_built_in_keeps_its_own_action(world):
    factory, s, _client, _ran = world
    _add(factory, id="docs", name="Memory Tidy", task_type="action", action="tidy_documents")
    _reconcile(s)
    assert _rows(factory)["docs"].action == "tidy_documents"


def test_a_stale_built_in_with_nothing_of_its_own_is_still_repaired(world):
    """`Law 1`: what the loop is for — a row from before `task_type` and
    `action` were written, under a legacy name, with nothing of its own to run."""
    factory, s, _client, _ran = world
    _add(factory, id="old", name="Tidy Memory", task_type="llm", trigger_type="event")
    _reconcile(s)
    old = _rows(factory)["old"]
    assert (old.task_type, old.action) == ("action", "consolidate_memory")
