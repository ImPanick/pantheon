# SPDX-License-Identifier: AGPL-3.0-or-later
"""Core search orchestrators: searxng_search_results, comprehensive_web_search, config, cache invalidation."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Set
from urllib.parse import urlparse

from .analytics import (
    NetworkError,
    ParseError,
    RateLimitError,
    error_logger,
    _record_query,
)
from .cache import (
    SEARCH_CACHE_DIR,
    search_cache_index,
    generate_cache_key,
    cleanup_cache,
)
from .query import (
    MAX_CACHE_DURATION,
    _cache_duration_for_query,
    build_enhanced_query,
)
from .ranking import rank_search_results, relevance_report
from .providers import (
    searxng_search_api,
    brave_search,
    duckduckgo_search,
    google_pse_search,
    tavily_search,
    serper_search,
    _get_search_settings,
    _get_provider_key,
    _get_result_count,
)
from .content import (
    fetch_webpage_content,
    extract_key_points,
    get_tldr,
    extract_quotes,
    extract_statistics,
)

logger = logging.getLogger(__name__)

# ========= CONFIG =========
SEARCH_CONFIG: Dict[str, Any] = {
    "primary_provider": "searxng",
}


def _is_secret_key(name: str) -> bool:
    """True for config keys that hold a credential (e.g. ``brave_api_key``)."""
    return name.endswith(("_api_key", "_key", "_token", "_secret"))


def get_search_config() -> Dict[str, Any]:
    """Get current search configuration including active provider info.

    Never returns stored API keys: callers — including the unauthenticated
    ``GET /api/search/config`` route — only need key *presence* via
    ``has_api_key``, not the secret itself (#1661).
    """
    config = SEARCH_CONFIG.copy()
    settings = _get_search_settings()
    provider = settings.get("search_provider", "searxng")
    config["active_provider"] = provider
    config["has_api_key"] = bool(_get_provider_key(provider))
    config["result_count"] = _get_result_count()
    if provider == "searxng":
        from .providers import _get_search_instance
        config["search_url"] = _get_search_instance()
    # Strip any string-valued credential so secrets never reach the response;
    # the boolean has_api_key flag (presence only) is preserved.
    return {
        k: v for k, v in config.items()
        if not (isinstance(v, str) and _is_secret_key(k))
    }


def update_search_config(api_key: str = None, **kwargs):
    """Merge non-secret search config into SEARCH_CONFIG.

    Provider API keys are intentionally NOT cached here. They are read on demand
    from settings/env via ``_get_provider_key`` (e.g. ``brave_search``), so the
    previous ``SEARCH_CONFIG["brave_api_key"] = api_key`` cache was never used
    for search and only leaked the decrypted key through ``get_search_config`` /
    ``GET /api/search/config`` (#1661). ``api_key`` is accepted for backward
    compatibility but no longer stored.
    """
    for k, v in kwargs.items():
        if not _is_secret_key(k):
            SEARCH_CONFIG[k] = v


def _call_provider(provider_name: str, query: str, count: int, time_filter: str = None) -> List[dict]:
    """Call a search provider by name. Returns list of results or empty list."""
    if provider_name == "searxng":
        return searxng_search_api(query, count, time_filter=time_filter)
    elif provider_name == "brave":
        return brave_search(query, count, time_filter)
    elif provider_name == "duckduckgo":
        return duckduckgo_search(query, count, time_filter)
    elif provider_name == "google_pse":
        return google_pse_search(query, count, time_filter)
    elif provider_name == "tavily":
        return tavily_search(query, count, time_filter)
    elif provider_name == "serper":
        return serper_search(query, count, time_filter)
    return []


# If the self-hosted SearXNG instance is up but all enabled engines return
# empty, fall back to the no-key provider so "search X" still works on fresh
# installs. Users can override/disable with `search_fallback_chain`.
_FALLBACK_ORDER = ["duckduckgo"]


# Where each provider actually lives, so a rate limit reported by one feature is
# visible to every other feature that calls the same host. Keying the cooldown by
# provider *name* would let deep research and a plain chat search each keep their
# own idea of whether Brave is angry with us.
_PROVIDER_HOSTS = {
    "brave": "api.search.brave.com",
    "duckduckgo": "html.duckduckgo.com",
    "ddg": "html.duckduckgo.com",
    "google": "www.googleapis.com",
    "google_pse": "www.googleapis.com",
    "tavily": "api.tavily.com",
    "serper": "google.serper.dev",
}


def _note_provider_rate_limited(provider_name: str) -> None:
    """Put a rate-limited provider into cooldown for everyone, not just us."""
    host = _PROVIDER_HOSTS.get((provider_name or "").lower())
    if not host:
        # SearXNG and anything self-hosted: the host is whatever the operator
        # configured, and being polite to your own box is not what this is for.
        return
    try:
        from src.rate_limiter import outbound

        outbound.observe(host, 429, {}, body_hint=f"{provider_name} rate limit")
    except Exception:  # never let politeness break a search
        logger.debug("could not record rate limit for %s", provider_name, exc_info=True)


def _build_provider_chain(primary: str) -> List[str]:
    """Build ordered list: primary first, then configured/default fallbacks."""
    chain = [primary]
    settings = _get_search_settings()
    user_chain = settings.get("search_fallback_chain") or []
    if isinstance(user_chain, str):
        user_chain = [s.strip() for s in user_chain.split(",") if s.strip()]
    fallbacks = user_chain if user_chain else _FALLBACK_ORDER
    for fb in fallbacks:
        if fb and fb != primary and fb not in chain and fb != "disabled":
            chain.append(fb)
    return chain


# ----------------------------------------------------------------------
# The search cache, as one seam both orchestrators use (`Law 7`)
# ----------------------------------------------------------------------
# Measured on `3b40a4e`: `searxng_search_results` was the only reader and
# writer of the search cache and had **no production caller anywhere** — only
# the two package `__init__` re-exports and three test files. Everything a
# person touches goes through `comprehensive_web_search`, which did not touch
# the cache at all, so every web search in the product was a fresh round trip
# while the cache code ran never. With a fake provider at 120 ms: the live path
# cost 1 provider call and ~121 ms on every repeat; the unreachable function
# cost 1 call then 0, and 121 ms then 0.6 ms.
#
# The decision (`Law 1`/`Law 14`): wire it to the path that exists rather than
# remove it. The **content** half of the same pipeline has cached for two hours
# the whole time (`content.py:195`, reached from `comprehensive_web_search`), so
# this extends scaffolding that is already here and already proven on the live
# path; what was missing was the cheap half, which is the half with somebody
# else's provider quota behind it.
#
# `_SEARCH_SWEEP_AGE` is the longest TTL `_cache_duration_for_query` can
# return. It used to be `timedelta(hours=1)` while the write path stamped a
# reference query with 24 hours, and measured, the entry was deleted by the
# next search once its index timestamp was 90 minutes old — one hour was the
# real ceiling and the news/reference split had never had any effect. The
# expiry in the entry's own file is the one source of truth for when it dies.
_SEARCH_SWEEP_AGE = MAX_CACHE_DURATION


def _search_cache_key(query: str, count: int, time_filter) -> str:
    """The cache key, derived in one place.

    `invalidate_search_cache` rebuilt this inline and hardcoded `|10|None`,
    which never matched what the write path stored — the key shape living in two
    functions is exactly how that happened.
    """
    return generate_cache_key(f"{query}|{count}|{time_filter}")


def _read_search_cache(query: str, count: int, time_filter) -> Optional[dict]:
    """A live cache entry for this search, or None.

    Returns ``{"results": [...], "provider": str|None, "age_seconds": float}``.
    `results` is what the provider said, **before ranking**: a cached ordering
    would freeze whatever `rank_search_results` did on the day it was written,
    so ranking runs on every read instead. A corrupt or expired entry is
    removed and reads as a miss — a search must never fail because of its cache.
    """
    cache_key = _search_cache_key(query, count, time_filter)
    cache_file = SEARCH_CACHE_DIR / f"{cache_key}.cache"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cached_data = json.load(f)
        expiry_raw = cached_data.get("expiry")
        expiry = datetime.fromisoformat(expiry_raw) if expiry_raw else None
        if expiry and datetime.now() < expiry:
            results = cached_data.get("data") or []
            if not results:
                raise ValueError("cached entry holds no results")
            written_raw = cached_data.get("timestamp")
            try:
                age = (datetime.now() - datetime.fromisoformat(written_raw)).total_seconds()
            except Exception:
                age = 0.0
            logger.debug("Search cache hit for query: %s", query)
            return {
                "results": results,
                # Absent on entries written before the provider was recorded.
                "provider": cached_data.get("provider"),
                "age_seconds": max(age, 0.0),
            }
    except Exception as e:
        logger.warning(f"Failed to read search cache for {query}: {e}")
    cache_file.unlink(missing_ok=True)
    search_cache_index.pop(cache_key, None)
    return None


def _write_search_cache(query: str, count: int, time_filter, results: List[dict],
                        provider: Optional[str]) -> None:
    """Store a successful search. Never raises into the search path."""
    cache_key = _search_cache_key(query, count, time_filter)
    cache_file = SEARCH_CACHE_DIR / f"{cache_key}.cache"
    try:
        expiry = datetime.now() + _cache_duration_for_query(query)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "expiry": expiry.isoformat(),
                "provider": provider,
                "data": results,
            }, f)
        search_cache_index[cache_key] = datetime.now()
        cleanup_cache(SEARCH_CACHE_DIR, search_cache_index, _SEARCH_SWEEP_AGE)
    except Exception as e:
        logger.warning(f"Failed to write search cache for {query}: {e}")


def _cache_note(age_seconds: float) -> str:
    """How the block says results are not fresh. Short, and with a number.

    The owner's export could not say which provider answered or when; a block
    that silently serves a cached answer would be the same gap again.
    """
    minutes = int(age_seconds // 60)
    if minutes < 1:
        return " (cached, under a minute old)"
    if minutes == 1:
        return " (cached, 1 min old)"
    if minutes < 120:
        return f" (cached, {minutes} min old)"
    return f" (cached, {minutes // 60} h old)"


# ----------------------------------------------------------------------
# Unified search with caching and retry
# ----------------------------------------------------------------------
def searxng_search_results(query: str, count: int = 10, time_filter: str = None) -> list[dict]:
    """Perform a web search using configured provider with caching and retry."""
    settings = _get_search_settings()
    search_provider = settings.get("search_provider", "searxng")
    result_count = _get_result_count()
    # Use configured count if caller used default
    if count == 10:
        count = result_count

    cached = _read_search_cache(query, count, time_filter)
    if cached is not None:
        _record_query(query, True, cache_hit=True, provider=cached["provider"])
        # Ranked on read, not on write: see `_read_search_cache`.
        return rank_search_results(query, cached["results"])

    logger.debug(f"Search cache miss for query: {query}")

    if search_provider == "disabled":
        logger.info("Search is disabled via admin settings")
        return []

    provider_chain = _build_provider_chain(search_provider)

    # The sent query is derived once, here, for every provider in the chain
    # (`Law 7`). It used to be derived inside `_brave_search_impl`, which was
    # its only caller — so the same search went out as two different strings
    # depending on a setting. `query` stays the person's words, because the
    # cache key, the analytics row and the ranking are all about what they asked.
    sent_query = build_enhanced_query(query, time_filter)

    results: List[dict] = []
    answered_by: Optional[str] = None
    for provider_name in provider_chain:
        for attempt in range(2):
            try:
                logger.info(f"Attempting {provider_name} search (attempt {attempt + 1})")
                results = _call_provider(provider_name, sent_query, count, time_filter)
                if results:
                    answered_by = provider_name
                    logger.info(f"{provider_name} search succeeded with {len(results)} results")
                    break
            except RateLimitError as e:
                # A 429 used to be retried here **immediately, with no sleep**,
                # against the provider that had just said stop — and then the
                # chain moved on and did the same to the next one. That turns one
                # provider's rate limit into load on all of them. A rate limit is
                # not a transient error, so do not re-attempt it: record it and
                # fall through to the next provider, which is the whole point of
                # having a chain.
                error_logger.error(f"{provider_name} rate-limited, not retrying: {e}")
                _note_provider_rate_limited(provider_name)
                break
            except (NetworkError, ParseError) as e:
                error_logger.error(f"{provider_name} search error (attempt {attempt + 1}): {e}")
            except Exception as e:
                error_logger.error(f"Unexpected error during {provider_name} search (attempt {attempt + 1}): {e}")
        if results:
            break

    success = bool(results)
    _record_query(query, success, cache_hit=False, provider=answered_by)

    if success:
        _write_search_cache(query, count, time_filter, results, answered_by)
        results = rank_search_results(query, results)
    else:
        logger.error(f"All search providers failed for query: {query}")

    return results


# ----------------------------------------------------------------------
# Cache invalidation
# ----------------------------------------------------------------------
def invalidate_search_cache(query: Optional[str] = None) -> None:
    """Invalidate cached search results. None clears all, otherwise just the given query."""
    if query is None:
        for file in SEARCH_CACHE_DIR.glob("*.cache"):
            try:
                file.unlink(missing_ok=True)
            except Exception as e:
                error_logger.warning(f"Failed to delete cache file {file}: {e}")
        search_cache_index.clear()
        logger.info("All search cache entries have been cleared.")
    else:
        # Match the key the write path stores: both orchestrators replace the
        # caller's default count with the configured _get_result_count()
        # (default 5), so a hardcoded "|10|None" never matched a real entry.
        # The shape is `_search_cache_key`'s now, so it cannot drift again.
        cache_key = _search_cache_key(query, _get_result_count(), None)
        cache_file = SEARCH_CACHE_DIR / f"{cache_key}.cache"
        if cache_file.exists():
            try:
                cache_file.unlink(missing_ok=True)
                search_cache_index.pop(cache_key, None)
                logger.info(f"Cache entry for query '{query}' has been invalidated.")
            except Exception as e:
                error_logger.warning(f"Failed to delete cache file for query '{query}': {e}")
        else:
            logger.info(f"No cache entry found for query '{query}'.")


def _relevance_lines(report: dict) -> str:
    """The match, in words a model can act on and a person can check.

    One line always, plus two when the match is bad — the measured fraction and
    the query words no result mentioned. `Law 5`: the number carries its scope
    ("1 of 9 query terms"), never a bare adjective.
    """
    verdict = report.get("verdict", "none")
    matched = report.get("matched", 0)
    terms = report.get("terms", 0)
    pct = round(report.get("best_coverage", 0.0) * 100)
    head = (
        f"Relevance: {verdict} — the closest result matches "
        f"{matched} of {terms} query terms ({pct}%)."
    )
    lines = [head]
    missing = report.get("missing") or []
    if missing:
        lines.append("No result mentions: " + ", ".join(missing))
    if verdict in ("weak", "none"):
        lines.append(
            "These results do not match the query. Tell the person the search did not "
            "find it rather than answering from general knowledge."
        )
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Comprehensive web search (with advanced filtering)
# ----------------------------------------------------------------------
def comprehensive_web_search(
    query: str,
    max_pages: int = 3,
    max_workers: int = 4,
    time_filter: str = None,
    domain_whitelist: Optional[Set[str]] = None,
    domain_blacklist: Optional[Set[str]] = None,
    content_type: Optional[str] = None,
    language: Optional[str] = None,
    min_content_length: int = 0,
    return_sources: bool = False,
    fetch_content: bool = True,
):
    """Perform comprehensive web search with content fetching and advanced filtering.

    ``fetch_content=False`` returns the search results and the block without
    fetching any page. It is the consumer `SearchService`'s constructor flag
    never had (`Law 13`): that method asked for ten pages, this function
    fetched all ten, and the caller read none of them.
    """
    logger.info(f"Starting comprehensive search for: {query}")
    if time_filter:
        logger.info(f"Applying time filter: {time_filter}")

    settings = _get_search_settings()
    search_provider = settings.get("search_provider", "searxng")
    result_count = _get_result_count()

    if search_provider == "disabled":
        logger.info("Search is disabled via admin settings")
        msg = "Web search is disabled by the administrator."
        return (msg, []) if return_sources else msg

    # Use configured result count (at least max_pages for content fetching)
    fetch_count = max(result_count, max_pages)

    # One derivation of the sent string for the whole chain (`Law 7`), and it is
    # reported in the block below: the owner's 2026-10-09 search could not be
    # diagnosed from its own transcript because nothing recorded either the
    # provider that answered or the string that went out.
    sent_query = build_enhanced_query(query, time_filter)

    # The cache, on the path people actually use. `fetch_count` and
    # `time_filter` are what change the provider's answer, so they are the key
    # with the query; the domain/content-type/language filters and
    # `min_content_length` shape what happens *after* the provider and are not.
    search_results = []
    provider_attempts = {}
    answered_by = None
    provider_note = ""
    cached = _read_search_cache(query, fetch_count, time_filter)
    if cached is not None:
        search_results = cached["results"]
        answered_by = cached["provider"]
        provider_note = _cache_note(cached["age_seconds"])

    provider_chain = _build_provider_chain(search_provider)
    for provider_name in ([] if search_results else provider_chain):
        last_err = None
        empty = False
        for attempt in range(2):
            try:
                search_results = _call_provider(provider_name, sent_query, fetch_count, time_filter)
                if search_results:
                    provider_attempts[provider_name] = f"ok ({len(search_results)})"
                    answered_by = provider_name
                    logger.info(f"Comprehensive search: {provider_name} returned {len(search_results)} results")
                    break
                empty = True
            except Exception as e:
                last_err = e
                logger.warning(f"Comprehensive search: {provider_name} attempt {attempt + 1} failed: {e}")
        if search_results:
            break
        if last_err is not None:
            provider_attempts[provider_name] = f"error: {last_err}"
        elif empty:
            provider_attempts[provider_name] = "empty"

    if not search_results:
        _record_query(query, False, cache_hit=False, provider=None)
        tally = ", ".join(f"{p}:{r}" for p, r in provider_attempts.items()) or "no providers configured"
        any_errors = any(r.startswith("error") for r in provider_attempts.values())
        if any_errors:
            msg = f"Web search failed — all providers errored or returned empty. Tried: {tally}"
        else:
            msg = (
                f"No search results found. Tried: {tally}. "
                "All providers returned empty — possibly a niche query or upstream rate-limiting; "
                "rephrasing or using the browser tool for a specific URL may help."
            )
        logger.warning(msg)
        return (msg, []) if return_sources else msg

    if cached is None:
        _write_search_cache(query, fetch_count, time_filter, search_results, answered_by)

    search_results = rank_search_results(query, search_results)

    # URL filter helper
    def url_passes_filters(url: str) -> bool:
        try:
            netloc = urlparse(url).netloc.lower()
        except Exception:
            return False
        if domain_whitelist is not None and netloc not in domain_whitelist:
            return False
        if domain_blacklist is not None and netloc in domain_blacklist:
            return False
        if content_type:
            ct = content_type.lower()
            if ct == "article":
                if not any(k in url.lower() for k in ("article", "blog", "news", "post")):
                    return False
            elif ct == "forum":
                if not any(k in url.lower() for k in ("forum", "discussion", "thread", "topic")):
                    return False
            elif ct == "academic":
                if not any(k in url.lower() for k in ("pdf", "doi", "scholar", "arxiv", "journal", "research")):
                    return False
        if language:
            lang_pat = language.lower()
            if not (f"/{lang_pat}/" in url.lower() or f"?lang={lang_pat}" in url.lower() or f"&lang={lang_pat}" in url.lower()):
                return False
        return True

    # Filter first, then take the budget. The slice used to run **before** the
    # filter — `search_results[:max_pages]` then `if url_passes_filters(...)` —
    # so a result excluded by `domain_blacklist` / `domain_whitelist` /
    # `content_type` / `language` cost a page instead of yielding to the next
    # result that passes. Measured: five results, `max_pages=3`, one domain
    # blacklisted gave **two** fetched pages with two passing results sitting
    # unread at [4] and [5]. The caller asked for three and the filter it
    # supplied quietly reduced that to two.
    passing_urls = [r["url"] for r in search_results if url_passes_filters(r.get("url", ""))]
    filtered_urls = passing_urls[:max_pages]
    if not passing_urls:
        logger.warning("All URLs filtered out by advanced criteria")
        # The search itself worked; the caller's filters excluded every result.
        _record_query(query, True, cache_hit=cached is not None,
                      provider=None if cached is not None else answered_by)
        msg = "No suitable results after applying filters."
        return (msg, []) if return_sources else msg

    # Build sources list for the frontend (before content fetching)
    _source_list = [
        {"url": r.get("url", ""), "title": r.get("title", "")}
        for r in search_results if r.get("url")
    ]

    # Map each URL to its [i] number in the sources list so fetched content
    # blocks can be labeled with the SAME index the model cites.
    _url_index = {
        r["url"]: i for i, r in enumerate(search_results, 1) if r.get("url")
    }

    # Fetch content in parallel
    fetched_content = []
    # Why a page is missing from FETCHED PAGE CONTENT. `_empty_result`
    # (`content.py:161`) has carried an `error` since it was written and every
    # caller dropped it, so the block said "fetched 3 pages" of five and never
    # which two, or why. The owner's 2026-10-09 search is the case: 3 of 5, and
    # *which* two failed is not recoverable from the export — which is the
    # defect, not a detail of it.
    not_fetched = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(fetch_webpage_content, url, 8, retry_attempt=0): url
            for url in (filtered_urls if fetch_content else [])
        }
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                result = future.result()
                if result["success"] and result["content"] and len(result["content"]) >= min_content_length:
                    # Remember which source this fetch belongs to: redirects
                    # can change result["url"] and completion order is
                    # arbitrary, so the block label cannot be recomputed later.
                    result["source_index"] = _url_index.get(url)
                    fetched_content.append(result)
                else:
                    reason = (result.get("error") or "").strip()
                    if not reason:
                        reason = "no readable text" if result.get("success") else "fetch failed"
                    not_fetched.append((_url_index.get(url), url, reason))
            except Exception as e:
                logger.error(f"Exception while fetching {url}: {str(e)}")
                not_fetched.append((_url_index.get(url), url, f"{type(e).__name__}: {e}"))

    not_fetched.sort(key=lambda row: row[0] or len(search_results) + 1)
    logger.info(f"Successfully fetched content from {len(fetched_content)} pages")

    # Format results
    output_parts = []

    if search_results:
        output_parts.append("```sources")
        for i, result in enumerate(search_results, 1):
            output_parts.append(f"[{i}] {result['title']}")
            output_parts.append(f"    {result['url']}")
            if result.get("age"):
                output_parts.append(f"    {result['age']}")
        output_parts.append("```")
        output_parts.append("")

    # `Law 10` — what the model is handed says how good the match was, in
    # measured terms. The owner's 2026-10-09 search returned five results about
    # a film, a dictionary and a clothing shop; this header said
    # "Searched 5 results, fetched 3 pages" and nothing else, and the model
    # answered from general knowledge rather than saying the search had missed.
    # Measured on the page text where a page was fetched, which is the
    # strongest evidence in the block and was being ignored: a result set with
    # no engine snippets scored as a miss while the content answered the
    # question. See `ranking.relevance_report`.
    relevance = relevance_report(query, search_results, fetched=fetched_content)

    # One analytics row per search, written where every fact about it is known:
    # whether it came from cache, which provider answered and how well the
    # results matched. `_record_query`'s only two call sites used to be inside
    # `searxng_search_results`, which nothing calls, so the counters sat at
    # their defaults however much searching a person did — and the fx6 lane
    # could not say which provider had answered the owner because nobody had
    # ever written it down. `Law 16`: the destination is the operator's own
    # `DATA_DIR`, so this is telemetry and not phoning home.
    # `provider` is recorded only when a provider was actually called: a cache
    # hit is already counted as a hit, and crediting the provider again would
    # make `pantheon_search_provider_answers` count something other than round
    # trips, which is the number an operator watching a quota needs.
    _record_query(query, True, cache_hit=cached is not None,
                  provider=None if cached is not None else answered_by,
                  verdict=relevance.get("verdict"))

    output_parts.append("=" * 70)
    output_parts.append("WEB SEARCH RESULTS AND FETCHED CONTENT")
    output_parts.append(f"Query: {query}")
    output_parts.append(f"Query as sent: {sent_query}")
    if answered_by:
        output_parts.append(f"Provider: {answered_by}{provider_note}")
    if fetch_content:
        output_parts.append(
            f"Searched {len(search_results)} results, fetched {len(fetched_content)} pages")
    else:
        # Not "fetched 0 pages": zero reads as a failure, and the caller asked
        # for none (`Law 10`).
        output_parts.append(
            f"Searched {len(search_results)} results, content fetching disabled")
    for idx, url, reason in not_fetched:
        label = f"[{idx}]" if idx else "[-]"
        output_parts.append(f"Not fetched {label} {url} — {reason}")
    output_parts.append(_relevance_lines(relevance))
    output_parts.append("=" * 70)
    output_parts.append("")

    output_parts.append("SEARCH RESULTS SUMMARY:")
    output_parts.append("-" * 50)
    for i, result in enumerate(search_results, 1):
        output_parts.append(f"\n[{i}] {result['title']}")
        output_parts.append(f"    URL: {result['url']}")
        output_parts.append(f"    Snippet: {result['snippet'][:200]}...")
        if result.get("age"):
            output_parts.append(f"    Age: {result['age']}")

    if fetched_content:
        output_parts.append("\n" + "=" * 70)
        output_parts.append("FETCHED PAGE CONTENT:")
        output_parts.append("-" * 50)

        # Emit blocks in source order, numbered with the same [i] as the
        # sources list, so [CONTENT 2] really is content from source [2].
        # Before this, blocks were numbered 1..N in fetch COMPLETION order,
        # which matched neither the sources list nor each other run to run.
        fetched_content.sort(key=lambda c: c.get("source_index") or len(search_results) + 1)
        for content in fetched_content:
            _idx = content.get("source_index")
            _label = f"[CONTENT {_idx}]" if _idx else "[CONTENT]"
            output_parts.append(f"\n{_label} From: {content['url']}")
            output_parts.append(f"Title: {content['title']}")
            output_parts.append("-" * 30)

            text = content["content"][:3000]
            if len(content["content"]) > 3000:
                text += "... [truncated]"
            output_parts.append(text)

            key_points = extract_key_points(content["content"])
            if key_points:
                output_parts.append("\nKey Points:")
                for pt in key_points[:5]:
                    output_parts.append(f"- {pt}")

            tldr = get_tldr(content["content"])
            if tldr:
                output_parts.append("\nTL;DR:")
                output_parts.append(tldr)

            quotes = extract_quotes(content["content"])
            if quotes:
                output_parts.append("\nImportant Quotes:")
                for q in quotes[:3]:
                    output_parts.append(f"\u201c{q}\u201d")

            stats = extract_statistics(content["content"])
            if stats:
                output_parts.append("\nData / Statistics:")
                for s in stats[:5]:
                    output_parts.append(f"- {s}")

            output_parts.append("")

    output_parts.append("=" * 70)
    output_parts.append("END OF WEB SEARCH RESULTS")
    output_parts.append("=" * 70)

    instructions = (
        "\n\nIMPORTANT INSTRUCTIONS:\n"
        "1. Use the above web search results and fetched content to answer the user's question\n"
        "2. Prioritize information from the FETCHED PAGE CONTENT section as it contains actual page data\n"
        "3. Cross-reference multiple sources when possible\n"
        "4. If the information is time-sensitive, pay attention to the age of the results\n"
        "5. Be explicit if the search results don't contain sufficient information to fully answer the question"
    )
    if relevance["verdict"] in ("weak", "none"):
        # The one case where instruction 5 is not enough: the results are
        # measurably about something else, and the honest answer is to say the
        # search missed. The owner's turn invented raid strategy from five
        # pages about an M. Night Shyamalan film.
        instructions += (
            "\n6. The Relevance line above says these results do not match the query. "
            "Say that the search did not find what was asked for, and name what is missing. "
            "Do not answer from general knowledge as though the results supported it, and "
            "do not describe the irrelevant results as if they were on topic. Offer a "
            "different search instead."
        )
    output_parts.append(instructions)

    result = "\n".join(output_parts)
    return (result, _source_list) if return_sources else result
