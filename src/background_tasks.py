# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fire-and-forget tasks that are not collected mid-run.

asyncio keeps only weak references to tasks made with `create_task`, so without
a strong one the garbage collector can collect a task while it runs and the
work silently never finishes. `spawn_tracked` holds the task in
`BACKGROUND_TASKS` until it is done.

`B2175`. `routes/chat_helpers.py` (extraction, auto-naming) and
`src/builtin_mcp.py` (server registration at start-up) each had a same-bodied
`_spawn_bg` with its own set; both use this one now, under their old names.
"""
from __future__ import annotations

import asyncio
from typing import Coroutine

BACKGROUND_TASKS: set[asyncio.Task] = set()


def spawn_tracked(coro: Coroutine) -> asyncio.Task:
    """Schedule a background task and hold a strong reference until it finishes."""
    task = asyncio.create_task(coro)
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    return task
