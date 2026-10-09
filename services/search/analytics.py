# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search analytics, metrics tracking, and exception hierarchy."""

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Dict, Any

from core.constants import DATA_DIR

from .cache import cache_metrics

logger = logging.getLogger(__name__)

# Dedicated error logger — write to the data logs directory (writable on both
# native runs and Docker, where DATA_DIR resolves to the bind-mounted volume).
_log_dir = Path(DATA_DIR) / "logs"
_error_log_path = _log_dir / "search_engine_error.log"
error_logger = logging.getLogger("search_engine_error")
error_logger.propagate = False
try:
    _log_dir.mkdir(parents=True, exist_ok=True)
    _error_handler = logging.FileHandler(_error_log_path, encoding="utf-8")
    _error_handler.setLevel(logging.WARNING)
    _error_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    error_logger.addHandler(_error_handler)
except Exception as _e:
    logging.getLogger(__name__).warning("search_engine_error log handler unavailable: %s", _e)

# Analytics file — also in the writable logs volume.
ANALYTICS_FILE = _log_dir / "search_analytics.json"


# ----------------------------------------------------------------------
# Custom exception hierarchy
# ----------------------------------------------------------------------
class SearchEngineError(Exception):
    """Base class for all search-engine related errors."""


class NetworkError(SearchEngineError):
    """Raised when a network request fails (e.g., timeout, DNS error)."""


class ParseError(SearchEngineError):
    """Raised when HTML or other content cannot be parsed."""


class RateLimitError(SearchEngineError):
    """Raised when the remote service returns a rate-limit (HTTP 429)."""


# ----------------------------------------------------------------------
# Analytics helpers
# ----------------------------------------------------------------------
def _default_analytics() -> Dict[str, Any]:
    return {
        "total_queries": 0,
        "successful_queries": 0,
        "failed_queries": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "query_patterns": {},
        # Which provider answered, and how well the results matched. Added
        # because the fx6-search lane could not say which of six providers had
        # answered the owner's 2026-10-09 search — nothing in the product wrote
        # it down, so the diagnosis had to be inferred from a Bing click id in
        # one result URL. `_load_analytics` merges over these defaults, so a
        # file written before they existed gains them on the next write.
        "providers": {},
        "verdicts": {},
    }


def _load_analytics() -> Dict[str, Any]:
    """Load analytics data from the JSON file, creating defaults if missing."""
    if not ANALYTICS_FILE.exists():
        default = _default_analytics()
        _save_analytics(default)
        return default
    try:
        with open(ANALYTICS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge over defaults so a file written by an older schema (or a
        # partial write) still has every counter — _record_query indexes
        # these keys directly and would otherwise raise KeyError.
        merged = _default_analytics()
        if isinstance(data, dict):
            merged.update(data)
        return merged
    except Exception as e:
        logger.warning(f"Failed to load analytics file: {e}")
        return _default_analytics()


def _save_analytics(data: Dict[str, Any]) -> None:
    """Persist analytics data to the JSON file."""
    try:
        with open(ANALYTICS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write analytics file: {e}")


def _record_query(query: str, success: bool, cache_hit: bool,
                  provider: str = None, verdict: str = None) -> None:
    """Update analytics for a single query execution.

    ``provider`` is the one that answered; ``verdict`` is
    `ranking.relevance_report`'s enum for how well the results matched. Both
    are keyword-with-default so the two existing callers and the two tests that
    drive this function directly are unaffected (`Law 1`).

    Called once per search from both orchestrators in
    `services/search/core.py`. Until `fx7-search2` its only two call sites were
    inside `searxng_search_results`, which has no production caller, so this
    function had never run outside a test.

    **It cannot raise.** It is now on the path a person's search takes, and a
    counter that breaks a search is worse than a counter that stops counting —
    the same reason `_save_analytics` below swallows its own write errors.
    """
    try:
        _record_query_inner(query, success, cache_hit, provider, verdict)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Failed to record search analytics: %s: %s", type(e).__name__, e)


def _record_query_inner(query: str, success: bool, cache_hit: bool,
                        provider: str = None, verdict: str = None) -> None:
    """The body of `_record_query`, so the guard above has something to guard."""
    analytics = _load_analytics()
    analytics["total_queries"] += 1
    if success:
        analytics["successful_queries"] += 1
    else:
        analytics["failed_queries"] += 1

    if cache_hit:
        analytics["cache_hits"] += 1
        cache_metrics["hits"] += 1
    else:
        analytics["cache_misses"] += 1
        cache_metrics["misses"] += 1

    patterns = analytics["query_patterns"]
    entry = patterns.get(query, {"count": 0, "successes": 0})
    entry["count"] += 1
    if success:
        entry["successes"] += 1
    patterns[query] = entry

    if provider:
        providers = analytics.setdefault("providers", {})
        providers[provider] = providers.get(provider, 0) + 1
    if verdict:
        verdicts = analytics.setdefault("verdicts", {})
        verdicts[verdict] = verdicts.get(verdict, 0) + 1

    _save_analytics(analytics)


def get_search_stats() -> Dict[str, Any]:
    """Return aggregated search analytics.

    Read by `src.metrics_export._collect_search`, which is the door this had
    none of until `fx7-search2` (`Law 13`): the numbers exist, nothing asked
    for them, so neither half of the feature had ever looked wrong. The
    scrape carries the **counts only** — `most_common_queries` is a person's
    own search text and stays in the local file.
    """
    analytics = _load_analytics()
    total = analytics.get("total_queries", 0) or 1
    success_rate = analytics.get("successful_queries", 0) / total
    cache_total = analytics.get("cache_hits", 0) + analytics.get("cache_misses", 0) or 1
    cache_hit_rate = analytics.get("cache_hits", 0) / cache_total

    pattern_counter = Counter({
        q: data["count"] for q, data in analytics.get("query_patterns", {}).items()
    })
    most_common = [q for q, _ in pattern_counter.most_common(5)]

    return {
        "most_common_queries": most_common,
        "success_rate": success_rate,
        "cache_hit_rate": cache_hit_rate,
        "total_queries": analytics.get("total_queries", 0),
        "successful_queries": analytics.get("successful_queries", 0),
        "failed_queries": analytics.get("failed_queries", 0),
        "cache_hits": analytics.get("cache_hits", 0),
        "cache_misses": analytics.get("cache_misses", 0),
        "cache_evictions": cache_metrics["evictions"],
        "runtime_cache_hits": cache_metrics["hits"],
        "runtime_cache_misses": cache_metrics["misses"],
        "providers": dict(analytics.get("providers") or {}),
        "verdicts": dict(analytics.get("verdicts") or {}),
    }
