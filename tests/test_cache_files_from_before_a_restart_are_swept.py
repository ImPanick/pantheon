# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1336` — cache files orphaned by a restart were never swept.

`services/search/cache.cleanup_cache` walked `cache_index`, the in-memory dict,
and both indexes start empty on every boot — so a file written before a
restart was invisible to the sweep for the rest of the process's life, and
`CACHE_MAX_ENTRIES` capped the index rather than the directory. Measured by
the row: five entries written, the index cleared, their expiry aged two days,
twenty further searches — all five still on disk.

The row's `Verify:` is the first two tests, driven through the live search
path (`comprehensive_web_search`, which writes the cache and sweeps) with
`B1162`'s counting provider in a hermetic cache directory. Nothing here
touches the network.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from services.search import cache, core
from tests.test_a_repeated_search_is_not_a_second_round_trip import (  # noqa: F401
    _CountingProvider,
    cached,
)


def _restart():
    """What a new process sees: the files, and an empty index."""
    core.search_cache_index.clear()


def _age(path, *, expiry=None, written=None):
    entry = json.loads(path.read_text())
    if expiry is not None:
        entry["expiry"] = expiry.isoformat()
    if written is not None:
        entry["timestamp"] = written.isoformat()
    path.write_text(json.dumps(entry))


def test_expired_entries_from_before_a_restart_are_gone_after_one_search(cached, monkeypatch):
    """The row's measurement, as a test."""
    _CountingProvider().install(monkeypatch)
    for i in range(5):
        core.comprehensive_web_search(f"python asyncio tutorial {i}", max_pages=1)
    before = sorted(cached.glob("*.cache"))
    assert len(before) == 5

    _restart()
    two_days_ago = datetime.now() - timedelta(days=2)
    for path in before:
        _age(path, expiry=two_days_ago)

    core.comprehensive_web_search("python asyncio tutorial, a later one", max_pages=1)

    left = set(cached.glob("*.cache"))
    assert not left & set(before), f"{len(left & set(before))} expired entries still on disk"
    assert len(left) == 1, "the later search's own entry is the one left"


def test_live_entries_from_before_a_restart_are_kept_and_counted(cached, monkeypatch):
    """Adopted, not deleted: an entry still inside its expiry serves the next
    identical search, and it is in the index the cap counts."""
    rec = _CountingProvider()
    rec.install(monkeypatch)
    core.comprehensive_web_search("python asyncio tutorial", max_pages=1)
    _restart()

    core.comprehensive_web_search("python asyncio tutorial, another", max_pages=1)
    assert len(core.search_cache_index) == 2, "the file from before the restart is indexed"

    core.comprehensive_web_search("python asyncio tutorial", max_pages=1)
    assert rec.count == 2, "the entry from before the restart served the repeat"


def test_a_directory_of_2000_files_settles_at_the_cap(cached, monkeypatch):
    """The row's second `Verify:` — the cap is on the directory."""
    _CountingProvider().install(monkeypatch)
    now = datetime.now()
    for i in range(2000):
        written = now - timedelta(minutes=2000 - i)    # the higher i, the newer
        (cached / f"{i:064x}.cache").write_text(json.dumps({
            "timestamp": written.isoformat(),
            "expiry": (now + timedelta(hours=12)).isoformat(),
            "provider": "searxng",
            "data": [{"title": "t", "url": "https://example.test/", "content": "c"}],
        }))
    _restart()

    core.comprehensive_web_search("python asyncio tutorial", max_pages=1)

    left = {p.stem for p in cached.glob("*.cache")}
    assert len(left) == cache.CACHE_MAX_ENTRIES
    assert f"{1999:064x}" in left and f"{0:064x}" not in left, "the oldest go first"


def test_an_unreadable_orphan_is_swept_but_a_file_being_written_is_not(cached, monkeypatch):
    _CountingProvider().install(monkeypatch)
    import os
    import time

    corrupt = cached / ("a" * 64 + ".cache")
    corrupt.write_text("{not json")
    old = time.time() - 3600
    os.utime(corrupt, (old, old))
    in_progress = cached / ("b" * 64 + ".cache")
    in_progress.write_text('{"timestamp": "')          # another search, mid-write
    _restart()

    core.comprehensive_web_search("python asyncio tutorial", max_pages=1)

    assert not corrupt.exists()
    assert in_progress.exists()
