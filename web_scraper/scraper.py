"""
WebScraper — the main entry point.

Orchestrates: search → filter → crawl (concurrent) → return results.

Quick-start
-----------
>>> from web_scraper import WebScraper
>>> import asyncio
>>>
>>> # 1. Plain markdown — no LLM needed
>>> scraper = WebScraper()
>>> output = asyncio.run(scraper.search_and_scrape("Vitamin C 1000mg"))
>>> print(output.results[0].content[:500])
>>>
>>> # 2. Scrape a single URL directly
>>> result = asyncio.run(scraper.scrape_url("https://iherb.com/pr/some-product/12345"))
>>> print(result.content[:500])
>>>
>>> # 3. LLM-structured extraction (requires Azure OpenAI env vars)
>>> schema = {
...     "title":       {"type": "string", "description": "Product name"},
...     "description": {"type": "string", "description": "Full product description"},
...     "price":       {"type": "string", "description": "Price with currency symbol"},
... }
>>> scraper = WebScraper(
...     extraction_schema=schema,
...     extraction_instruction="Extract the product title, description and price.",
... )
>>> output = asyncio.run(scraper.search_and_scrape("Vitamin C 1000mg iherb"))
>>> print(output.results[0].extracted_data)
>>>
>>> # 4. Site-specific search (like the engine does)
>>> output = asyncio.run(
...     scraper.search_and_scrape('site:iherb.com "Vitamin C 1000mg"')
... )
"""

import asyncio
import logging
from asyncio import Semaphore
from typing import Any, Dict, List, Optional, Union

from web_scraper.config import scraper_settings
from web_scraper.crawler import Crawler
from web_scraper.filter import ContentFilter
from web_scraper.models import CrawlResult, ScrapeOutput, SearchError, SearchResult
from web_scraper.searcher import Searcher

logger = logging.getLogger(__name__)


class WebScraper:
    """
    High-level scraper that combines search, URL filtering, and page crawling.

    Parameters
    ----------
    extraction_schema:
        Optional dict of JSON-Schema field definitions.  When provided, the LLM
        is used to extract structured data from each crawled page.
        When omitted, only raw Markdown text is returned.

    extraction_instruction:
        Plain-English instruction given to the LLM when ``extraction_schema``
        is set.  Defaults to a generic extraction prompt.

    max_concurrent_crawls:
        Maximum number of URLs crawled simultaneously.
        Defaults to ``MAX_CONCURRENT_CRAWLS`` env var (3).

    max_retries:
        Retries per URL on failure.  Defaults to ``WEB_SCRAP_MAX_RETRIES`` (2).

    content_filter:
        Custom :class:`~web_scraper.filter.ContentFilter` instance.
        Pass ``None`` to disable URL filtering completely.

    searcher_base_url:
        Override the SearXNG endpoint URL.
    """

    def __init__(
        self,
        extraction_schema: Optional[Dict[str, Any]] = None,
        extraction_instruction: Optional[str] = None,
        max_concurrent_crawls: int = None,
        max_retries: int = None,
        content_filter: Optional[ContentFilter] = None,
        searcher_base_url: str = None,
    ):
        concurrency = max_concurrent_crawls or scraper_settings.MAX_CONCURRENT_CRAWLS
        self._semaphore = Semaphore(concurrency)
        self._crawler = Crawler(
            extraction_schema=extraction_schema,
            extraction_instruction=extraction_instruction,
            max_retries=max_retries,
        )
        # Default: create a filter with generic defaults
        _filter = content_filter if content_filter is not None else ContentFilter()
        self._searcher = Searcher(
            base_url=searcher_base_url,
            content_filter=_filter,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        max_results: int = None,
        max_pages: int = None,
    ) -> Union[List[SearchResult], SearchError]:
        """
        Run a SearXNG search and return ranked :class:`SearchResult` objects.
        No crawling is performed.
        """
        return await self._searcher.search(
            query=query,
            max_results=max_results,
            max_pages=max_pages,
        )

    async def scrape_url(self, url: str) -> CrawlResult:
        """
        Crawl a single URL and return a :class:`CrawlResult`.
        Does not perform a search.
        """
        async with self._semaphore:
            return await self._crawler.crawl(url)

    async def search_and_scrape(
        self,
        query: str,
        max_urls: int = None,
        max_pages: int = None,
    ) -> ScrapeOutput:
        """
        Full pipeline: search → filter → crawl all results concurrently.

        Parameters
        ----------
        query:     Search query (can include ``site:domain.com`` prefixes).
        max_urls:  Cap on how many URLs to actually crawl.
        max_pages: How many SearXNG result pages to fetch.
        """
        max_urls = int(max_urls or scraper_settings.WEB_SEARCH_MAX_RESULTS)
        output = ScrapeOutput(query=query)

        # ── 1. Search ──────────────────────────────────────────────────────────
        search_results = await self._searcher.search(
            query=query,
            max_results=max_urls,
            max_pages=max_pages,
        )

        if isinstance(search_results, SearchError):
            logger.error("Search failed for '%s': %s", query, search_results.error)
            return output

        if not search_results:
            logger.warning("No search results for query: %s", query)
            return output

        # ── 2. Crawl concurrently ──────────────────────────────────────────────
        async def _crawl_one(sr: SearchResult) -> CrawlResult:
            async with self._semaphore:
                result = await self._crawler.crawl(sr.url)
                if not result.metadata.get("title") and sr.title:
                    result.metadata["title"] = sr.title
                result.metadata["search_score"] = sr.score
                return result

        tasks = [_crawl_one(sr) for sr in search_results if sr.url]
        crawl_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, res in enumerate(crawl_results):
            if isinstance(res, Exception):
                url = search_results[i].url if i < len(search_results) else "unknown"
                output.results.append(CrawlResult(url=url, success=False, error=str(res)))
                output.total_failed += 1
            else:
                output.results.append(res)
                if res.success:
                    output.total_success += 1
                else:
                    output.total_failed += 1

        logger.info(
            "search_and_scrape('%s'): %d success, %d failed",
            query, output.total_success, output.total_failed,
        )
        return output

    async def scrape_urls(self, urls: List[str]) -> List[CrawlResult]:
        """
        Crawl a list of URLs concurrently (no search step).
        Useful when you already have the URLs.
        """
        tasks = [self.scrape_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                out.append(CrawlResult(url=urls[i], success=False, error=str(res)))
            else:
                out.append(res)
        return out
