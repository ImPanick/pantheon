# SPDX-License-Identifier: AGPL-3.0-or-later
# services/search/service.py
"""Search service — clean interface for web search."""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from . import (
    comprehensive_web_search,
    fetch_webpage_content,
    get_search_config,
)

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""
    url: str
    title: str
    snippet: str
    content: Optional[str] = None


@dataclass
class SearchResponse:
    """Response from a search query."""
    query: str
    results: List[SearchResult]
    total: int
    cached: bool = False


class SearchService:
    """
    Web search service.

    Usage:
        service = SearchService()
        result = await service.search("python async patterns")
        for r in result.results:
            print(f"{r.title}: {r.url}")

        body = await service.fetch_content(result.results[0].url)

    **The constructor flag is `fetch_content_enabled`, not `fetch_content`.**
    ``self.fetch_content = fetch_content`` and ``async def fetch_content`` were
    both here, and the instance attribute shadowed the method — so
    ``await service.fetch_content(url)`` raised
    ``TypeError: 'bool' object is not callable`` on every instance and the
    method was unreachable. `Law 10`: one name, one reading. The constructor
    *keyword* keeps its public name; what it is stored as does not collide.
    """

    def __init__(self, default_depth: int = 1, fetch_content: bool = True):
        self.default_depth = default_depth
        # Named so it cannot shadow `fetch_content()` below. `bool()` because a
        # flag whose truth depends on the caller's type is `Law 10` again.
        self.fetch_content_enabled = bool(fetch_content)

    async def search(
        self,
        query: str,
        depth: Optional[int] = None,
        fetch_content: Optional[bool] = None,
    ) -> SearchResponse:
        """
        Search the web.

        Args:
            query: Search query
            depth: Search depth (1=quick, 2=thorough, 3=comprehensive)
            fetch_content: Whether to fetch full page content. ``None`` uses
                the instance's `fetch_content_enabled`.

        Returns:
            SearchResponse with results. ``SearchResult.content`` is None here:
            the rows come from the search's source list. Ask
            `fetch_content(url)` for a page's text.
        """
        depth = depth or self.default_depth
        # This parameter was documented "accepted for API compatibility" and
        # ignored, so the flag had no consumer at all (`Law 13`). It now reaches
        # the search. Measured on `3b40a4e`: `SearchService(default_depth=1)`
        # asked for 10 pages, `comprehensive_web_search` fetched all 10, and
        # this method read none of them — it keeps only the (url, title) source
        # list. A caller that does not want page content no longer pays for it.
        want_content = (self.fetch_content_enabled if fetch_content is None
                        else bool(fetch_content))

        # comprehensive_web_search is synchronous and, with return_sources=True,
        # returns (context_str, [{"url", "title"}, ...]). Run it off the event
        # loop so we don't block it, and use the source list as the result rows.
        _context, raw_results = await asyncio.to_thread(
            comprehensive_web_search,
            query,
            max_pages=10 * depth,
            return_sources=True,
            fetch_content=want_content,
        )

        results = []
        for r in raw_results:
            if not isinstance(r, dict):
                continue
            results.append(SearchResult(
                url=r.get("url", ""),
                title=r.get("title", ""),
                snippet=r.get("snippet", ""),
                content=r.get("content"),
            ))

        return SearchResponse(
            query=query,
            results=results,
            total=len(results),
        )

    async def fetch_content(self, url: str) -> Optional[str]:
        """Fetch a page's readable text, or None when it could not be read.

        Two defects lived in the one line this replaces, and the name collision
        above hid the second:

            return await fetch_webpage_content(url)

        `fetch_webpage_content` (`content.py:182`) is a plain ``def`` returning
        a **dict**, so this raised ``TypeError: object dict can't be used in
        'await' expression`` — measured by calling the unbound method past the
        shadow. It is also blocking, so awaiting it (had it been a coroutine)
        was not the question; running it off the loop is, the same way
        `search()` already runs the orchestrator.

        The failure reason is logged rather than dropped. `_empty_result` has
        carried an ``error`` since it was written and every caller threw it
        away, which is why the owner's *"fetched 3 pages"* of five never said
        which two or why.
        """
        result = await asyncio.to_thread(fetch_webpage_content, url)
        if not isinstance(result, dict):
            logger.warning("fetch_content(%s): fetcher returned %s, not a result",
                           url, type(result).__name__)
            return None
        if not result.get("success"):
            logger.warning("fetch_content(%s) failed: %s", url,
                           result.get("error") or "no reason reported")
            return None
        return result.get("content") or None

    def get_config(self) -> Dict[str, Any]:
        """Get current search configuration."""
        return get_search_config()
