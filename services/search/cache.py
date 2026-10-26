# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search and content caching with LRU eviction."""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from core.constants import DATA_DIR

logger = logging.getLogger(__name__)

# Cache directories
CACHE_DIR = Path(DATA_DIR) / "cache"
SEARCH_CACHE_DIR = CACHE_DIR / "search"
CONTENT_CACHE_DIR = CACHE_DIR / "content"
CACHE_MAX_ENTRIES = 1000

# Create cache directories. Guarded so an unwritable path (e.g. a read-only
# mount) degrades to no-disk-cache instead of crashing module import.
try:
    SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CONTENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except OSError as _e:
    logger.warning("Search cache directory unavailable (%s); disk cache disabled", _e)

# Track cache size for LRU eviction
search_cache_index: Dict[str, datetime] = {}
content_cache_index: Dict[str, datetime] = {}

# Cache metrics (shared across modules)
cache_metrics = {"hits": 0, "misses": 0, "evictions": 0}


def generate_cache_key(data: str) -> str:
    """Generate a unique cache key using SHA-256 hash."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _orphan_written_at(path: Path, max_age: timedelta, now: datetime) -> Optional[datetime]:
    """`B1336`. When a cache file the index does not know was written, or None
    when it is already dead.

    Read from the file itself, because the file is the one source of truth for
    when an entry dies (`core.py`, `_SEARCH_SWEEP_AGE`): a search entry carries
    its own `expiry`, a content entry only its `timestamp` and dies `max_age`
    after it. A file that cannot be read is dead too — the read path removes a
    corrupt entry the same way.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        written = datetime.fromisoformat(entry["timestamp"]) if entry.get("timestamp") \
            else datetime.fromtimestamp(path.stat().st_mtime)
        expiry = datetime.fromisoformat(entry["expiry"]) if entry.get("expiry") \
            else written + max_age
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        try:
            # Another search's write in progress (the searches run on a thread
            # pool): half a file is not a corrupt one yet. Left for a later
            # sweep, under the time it is being written.
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if now - mtime < timedelta(seconds=60):
                return mtime
        except OSError:
            pass
        logger.debug("Cache file %s unreadable (%s); swept", path.name, e)
        return None
    if now >= expiry or now - written > max_age:
        return None
    return written


def cleanup_cache(cache_dir: Path, cache_index: Dict[str, datetime], max_age: timedelta):
    """Remove expired cache entries and enforce LRU policy.

    `B1336`: over the directory, not only the index. Both indexes live in
    memory and start empty on every boot, so a file written before a restart
    was invisible to this sweep for the rest of the process's life and
    `CACHE_MAX_ENTRIES` capped the index rather than the directory — measured,
    five entries written, the index cleared, their expiry aged two days, and
    after twenty more searches all five were still on disk. A file the index
    does not know is read once (`_orphan_written_at`): dead, it is removed;
    alive, it joins the index under the time it was written, so the cap below
    counts it and the next sweep does not read it again. This adds a sweep and
    removes no behaviour (`Law 1`).
    """
    current_time = datetime.now()
    files_in_dir = {f.name.split(".")[0]: f for f in cache_dir.glob("*.cache")}

    for key, path in list(files_in_dir.items()):
        if key in cache_index:
            continue
        written = _orphan_written_at(path, max_age, current_time)
        if written is None:
            path.unlink(missing_ok=True)
            files_in_dir.pop(key)
            cache_metrics["evictions"] += 1
        else:
            cache_index[key] = written

    to_remove = []
    for key, timestamp in list(cache_index.items()):
        if current_time - timestamp > max_age or key not in files_in_dir:
            to_remove.append(key)
            if key in files_in_dir:
                files_in_dir[key].unlink(missing_ok=True)

    for key in to_remove:
        cache_index.pop(key, None)
        cache_metrics["evictions"] += 1

    if len(cache_index) > CACHE_MAX_ENTRIES:
        sorted_items = sorted(cache_index.items(), key=lambda x: x[1])
        excess_count = len(cache_index) - CACHE_MAX_ENTRIES
        for key, _ in sorted_items[:excess_count]:
            cache_index.pop(key, None)
            cache_file = cache_dir / f"{key}.cache"
            cache_file.unlink(missing_ok=True)
            cache_metrics["evictions"] += 1
