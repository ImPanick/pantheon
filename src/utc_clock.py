# SPDX-License-Identifier: AGPL-3.0-or-later
"""The current time in UTC, naive — what every `DateTime` column stores.

`B2173`. One definition. `core.database.utcnow_naive` is this function,
re-exported, so its many importers keep working; a module that must not pull
`core.database` (and with it SQLAlchemy and the engine) imports it from here.
Fourteen private copies (`_now`, `_utcnow`, `_utcnow_naive`) are folded into it.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """Return naive UTC for existing DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
