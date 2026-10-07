# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-16`): a standing condition is said once per process.

Some lines describe a state, not an event — "IMAP is not configured", "the
local embedding model is not downloaded" — and were logged every time a caller
asked: measured by the perf audit on `9560d50`, 54 SMTP/IMAP warning lines in a
45-minute session with no mail account (two per `/api/email/urgency-state`
poll, once a minute per tab) and `FastEmbed init failed` at ERROR on every page
load (35). The first saying is news; the rest bury it.

`log_once(logger, level, key, message, *args)` says it at `level` the first
time this process sees `key`, at DEBUG after that. `clear(key)` is for when the
condition ends — set up the account, download the model — so that if it comes
back it is news again.
"""
from __future__ import annotations

import logging
import threading

_said: set[str] = set()
_lock = threading.Lock()


def log_once(logger: logging.Logger, level: int, key: str, message: str, *args) -> bool:
    """Log `message` at `level` the first time `key` is seen, else at DEBUG.
    Returns True when this was the first time."""
    with _lock:
        first = key not in _said
        _said.add(key)
    logger.log(level if first else logging.DEBUG, message, *args)
    return first


def clear(key: str) -> None:
    """The condition `key` named is over; say it again if it returns."""
    with _lock:
        _said.discard(key)
