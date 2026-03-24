"""
SearXNG-based URL discovery.

Queries a self-hosted SearXNG instance and returns ranked SearchResult
objects.  Multiple result pages are fetched in parallel.

Usage:
    searcher = Searcher(base_url="http://localhost:8080/search")
    results = await searcher.search("Vitamin C 1000mg", max_results=5)
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Union

import httpx

from web_scraper.config import scraper_settings
from web_scraper.filter import ContentFilter
from web_scraper.models import SearchError, SearchResult

logger = logging.getLogger(__name__)


async def _fetch_page(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
    page: int,
    timeout: float,
) -> Union[List[dict], str]:
    """Fetch one page of SearXNG results. Returns raw dicts or an error string."""
    try:
        params = {"q": query, "format": "json", "pageno": page}
        resp = await client.get(base_url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as exc:
        return f"Page {page} failed: {exc}"


class Searcher:
    """
    Async wrapper around SearXNG.

    Parameters
    ----------
    base_url:
        Full URL of the SearXNG /search endpoint.
        Defaults to ``SEARXNG_BASE_URL`` env var.
    content_filter:
        An optional :class:`ContentFilter` instance.  Pass ``None`` to skip
        filtering entirely (useful for unit tests or when you want all raw results).
    """

    def __init__(
        self,
        base_url: str = None,
        content_filter: Optional[ContentFilter] = None,
    ):
        self.base_url = base_url or scraper_settings.SEARXNG_BASE_URL
        self.content_filter = content_filter  # None = no filtering

    async def search(
        self,
        query: str,
        max_results: int = None,
        max_pages: int = None,
        timeout: int = None,
        min_score: float = None,
        apply_filter: bool = True,
    ) -> Union[List[SearchResult], SearchError]:
        """
        Search SearXNG and return a list of :class:`SearchResult` objects.

        Parameters
        ----------
        query:        Search query string.
        max_results:  Maximum number of results to return (after filtering).
        max_pages:    How many SearXNG result pages to fetch (in parallel).
        timeout:      Per-request timeout in seconds.
        min_score:    Drop results whose SearXNG score is below this value.
        apply_filter: Whether to run the URL relevance filter.
        """
        max_results = int(max_results or scraper_settings.WEB_SEARCH_MAX_RESULTS)
        max_pages = int(max_pages or scraper_settings.WEB_SEARCH_MAX_PAGES)
        timeout = float(timeout or scraper_settings.WEB_SEARCH_TIMEOUT)
        min_score = float(min_score if min_score is not None else scraper_settings.WEB_SEARCH_MIN_SCORE)

        # ── Fetch all pages in parallel ────────────────────────────────────────
        raw_results: List[dict] = []
        async with httpx.AsyncClient() as client:
            pages = await asyncio.gather(*[
                _fetch_page(client, self.base_url, query, page, timeout)
                for page in range(1, max_pages + 1)
            ])

        for page_data in pages:
            if isinstance(page_data, str):
                # One page errored — propagate as SearchError
                return SearchError(query=query, error=page_data)
            raw_results.extend(page_data)

        # ── Optional URL relevance filter ──────────────────────────────────────
        if apply_filter and self.content_filter is not None:
            raw_results, stats = self.content_filter.apply(query, raw_results)
            logger.debug("Filter stats: %s", stats)

        # ── Convert to SearchResult objects ────────────────────────────────────
        items: List[SearchResult] = []
        for item in raw_results:
            items.append(SearchResult(
                url=item.get("url", ""),
                title=item.get("title"),
                snippet=item.get("snippet"),
                score=item.get("score"),
                engine=item.get("engine"),
                engines=item.get("engines"),
                published_date=str(item.get("published_date", "")),
                relevance_score=item.get("_relevance_score"),
                extracted_at=datetime.now().isoformat(),
                success=True,
            ))

        # ── Apply score threshold ──────────────────────────────────────────────
        if min_score > 0:
            items = [r for r in items if r.score and r.score >= min_score]

        # ── Cap to max_results ─────────────────────────────────────────────────
        return items[:max_results]
