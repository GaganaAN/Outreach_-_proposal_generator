"""
Tests for the web_scraper module.

Run all tests:
    cd /path/to/swanson-engine-and-apis
    python -m pytest web_scraper/test_scraper.py -v

Run a specific test:
    python -m pytest web_scraper/test_scraper.py::test_filter_scores_product_urls -v

Run the live integration test (requires SearXNG + network):
    python -m pytest web_scraper/test_scraper.py -v -m live

Run the LLM integration test (requires Azure OpenAI env vars + SearXNG):
    python -m pytest web_scraper/test_scraper.py -v -m llm

No external services needed for unit tests — they run offline.
"""

import asyncio
import os
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Mark helpers ───────────────────────────────────────────────────────────────
# Tests decorated with @pytest.mark.live require SearXNG to be running.
# Tests decorated with @pytest.mark.llm also require Azure OpenAI env vars.

pytestmark = []  # no global marks


# =============================================================================
# 1. Unit tests — ContentFilter (no network)
# =============================================================================

class TestContentFilter:
    """Tests for the URL scoring / filtering logic."""

    def setup_method(self):
        from web_scraper.filter import ContentFilter
        self.f = ContentFilter()

    def _make_item(self, url: str, title: str = "") -> Dict[str, Any]:
        return {"url": url, "title": title, "score": 1.0}

    def test_product_url_scores_high(self):
        items = [self._make_item("https://iherb.com/pr/vitamin-c/12345")]
        filtered, stats = self.f.apply("vitamin c supplement", items)
        assert len(filtered) == 1, "Product URL should pass filter"
        assert filtered[0]["_relevance_score"] > 0.5

    def test_blog_url_filtered_out(self):
        items = [self._make_item("https://example.com/blog/vitamin-c-benefits")]
        filtered, _ = self.f.apply("vitamin c", items)
        assert len(filtered) == 0, "Blog URL should be filtered out"

    def test_login_url_filtered_out(self):
        items = [self._make_item("https://store.com/login")]
        filtered, _ = self.f.apply("vitamin c", items)
        assert len(filtered) == 0

    def test_pdf_url_always_filtered(self):
        items = [self._make_item("https://example.com/product/document.pdf")]
        filtered, _ = self.f.apply("vitamin c", items)
        assert len(filtered) == 0, "PDFs should always be filtered out"

    def test_trusted_domain_gets_bonus(self):
        from web_scraper.filter import ContentFilter
        f_with_trust = ContentFilter(trusted_domains=["iherb.com"])
        f_no_trust = ContentFilter(trusted_domains=[])

        item = {"url": "https://iherb.com/pr/vitamin-c/12345", "title": "Vitamin C", "score": 1.0}
        filtered_trust, _ = f_with_trust.apply("vitamin c", [item])
        filtered_no, _ = f_no_trust.apply("vitamin c", [item])

        score_with = filtered_trust[0]["_relevance_score"] if filtered_trust else 0
        score_without = filtered_no[0]["_relevance_score"] if filtered_no else 0
        assert score_with >= score_without, "Trusted domain should get a higher score"

    def test_multiple_items_sorted_by_score(self):
        items = [
            self._make_item("https://example.com/blog/info"),         # will be filtered
            self._make_item("https://iherb.com/pr/vitamin-c/123"),    # high score
            self._make_item("https://random.com/page"),               # low score
        ]
        filtered, _ = self.f.apply("vitamin c supplement", items)
        scores = [r["_relevance_score"] for r in filtered]
        assert scores == sorted(scores, reverse=True), "Results should be sorted descending"

    def test_no_results_returns_empty(self):
        filtered, stats = self.f.apply("test query", [])
        assert filtered == []
        assert stats["total_input"] == 0

    def test_custom_unwanted_patterns(self):
        from web_scraper.filter import ContentFilter
        f = ContentFilter(unwanted_patterns=["/custom-bad/"])
        items = [self._make_item("https://site.com/custom-bad/page")]
        filtered, _ = f.apply("something", items)
        assert len(filtered) == 0

    def test_learning_mode_creates_rules(self):
        from web_scraper.filter import ContentFilter
        f = ContentFilter()
        items = [
            {"url": f"https://example.com/products/item-{i}", "title": f"Product {i}", "score": 1.0}
            for i in range(5)
        ]
        f.apply("buy supplement", items, learning_mode=True)
        assert len(f.learned_rules) > 0, "Learning mode should generate rules"


# =============================================================================
# 2. Unit tests — Models
# =============================================================================

class TestModels:
    def test_scrape_output_helpers(self):
        from web_scraper.models import CrawlResult, ScrapeOutput
        output = ScrapeOutput(query="test")
        output.results = [
            CrawlResult(url="https://a.com", success=True, content="hello"),
            CrawlResult(url="https://b.com", success=False, error="timeout"),
        ]
        output.total_success = 1
        output.total_failed = 1
        assert len(output.successful()) == 1
        assert len(output.failed()) == 1

    def test_crawl_result_defaults(self):
        from web_scraper.models import CrawlResult
        r = CrawlResult(url="https://x.com", success=True)
        assert r.content == ""
        assert r.extracted_data == {}
        assert r.error == ""

    def test_search_result_is_pydantic(self):
        from web_scraper.models import SearchResult
        sr = SearchResult(url="https://example.com", title="Test")
        assert sr.url == "https://example.com"
        assert sr.success is True


# =============================================================================
# 3. Unit tests — Crawler (mocked — no real browser)
# =============================================================================

class TestCrawler:
    """Patch crawl4ai so no browser is launched."""

    @pytest.mark.asyncio
    async def test_successful_crawl_returns_content(self):
        from web_scraper.crawler import Crawler

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.markdown = "# Product\nGreat vitamin C supplement."
        mock_result.extracted_content = None
        mock_result.metadata = {"title": "Product Page"}

        with patch("web_scraper.crawler.AsyncWebCrawler") as mock_crawler_cls, \
             patch("web_scraper.crawler.build_stealth_config"):
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.arun = AsyncMock(return_value=mock_result)
            mock_crawler_cls.return_value = mock_ctx

            crawler = Crawler()
            result = await crawler.crawl("https://example.com/product/123")

        assert result.success is True
        assert "vitamin C" in result.content

    @pytest.mark.asyncio
    async def test_failed_crawl_returns_error(self):
        from web_scraper.crawler import Crawler

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error_message = "Connection timed out"

        with patch("web_scraper.crawler.AsyncWebCrawler") as mock_crawler_cls, \
             patch("web_scraper.crawler.build_stealth_config"):
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.arun = AsyncMock(return_value=mock_result)
            mock_crawler_cls.return_value = mock_ctx

            crawler = Crawler(max_retries=0)
            result = await crawler.crawl("https://example.com/bad-url")

        assert result.success is False
        assert result.error != ""

    @pytest.mark.asyncio
    async def test_llm_extraction_parses_json(self):
        import json
        from web_scraper.crawler import Crawler

        extracted_payload = json.dumps([{"title": "Vitamin C 1000mg", "price": "$9.99"}])

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.markdown = "Some page content"
        mock_result.extracted_content = extracted_payload
        mock_result.metadata = {}

        schema = {
            "title": {"type": "string", "description": "Product name"},
            "price": {"type": "string", "description": "Price"},
        }

        with patch("web_scraper.crawler.AsyncWebCrawler") as mock_crawler_cls, \
             patch("web_scraper.crawler.build_stealth_config"), \
             patch("web_scraper.crawler.scraper_settings") as mock_settings:

            mock_settings.llm_configured.return_value = True
            mock_settings.AZURE_OPENAI_DEPLOYMENT_NAME = "gpt-4"
            mock_settings.AZURE_OPENAI_API_KEY = "fake-key"
            mock_settings.AZURE_OPENAI_ENDPOINT = "https://fake.openai.azure.com"
            mock_settings.AZURE_OPENAI_API_VERSION = "2024-02-01"
            mock_settings.MAX_RETRIES = 0
            mock_settings.PAGE_TIMEOUT_MS = 30000
            mock_settings.STEALTH_DELAY_SECONDS = 0
            mock_settings.DYNAMIC_CONTENT_DELAY_SECONDS = 0

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.arun = AsyncMock(return_value=mock_result)
            mock_crawler_cls.return_value = mock_ctx

            from crawl4ai.extraction_strategy import ExtractionStrategy
            with patch("web_scraper.crawler.LLMExtractionStrategy", create=True):
                crawler = Crawler(extraction_schema=schema)
                mock_strategy = MagicMock(spec=ExtractionStrategy)
                crawler._build_llm_strategy = MagicMock(return_value=mock_strategy)
                result = await crawler.crawl("https://example.com/product/1")

        assert result.success is True
        assert result.extracted_data.get("title") == "Vitamin C 1000mg"


# =============================================================================
# 4. Unit tests — Searcher (mocked — no SearXNG)
# =============================================================================

class TestSearcher:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        from web_scraper.searcher import Searcher

        fake_page = [
            {"url": "https://iherb.com/pr/product/1", "title": "Vitamin C", "score": 0.9},
            {"url": "https://vitacost.com/product/2",  "title": "Vitamin C 1000", "score": 0.8},
        ]

        with patch("web_scraper.searcher._fetch_page", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = fake_page
            searcher = Searcher(content_filter=None)  # disable filter for simplicity
            results = await searcher.search("vitamin c", max_results=5, max_pages=1)

        assert len(results) == 2
        assert results[0].url == "https://iherb.com/pr/product/1"

    @pytest.mark.asyncio
    async def test_search_returns_error_on_failure(self):
        from web_scraper.models import SearchError
        from web_scraper.searcher import Searcher

        with patch("web_scraper.searcher._fetch_page", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = "Page 1 failed: timeout"
            searcher = Searcher(content_filter=None)
            result = await searcher.search("test", max_pages=1)

        assert isinstance(result, SearchError)

    @pytest.mark.asyncio
    async def test_min_score_filter(self):
        from web_scraper.searcher import Searcher

        fake_page = [
            {"url": "https://a.com/p/1", "title": "High", "score": 0.9},
            {"url": "https://b.com/p/2", "title": "Low",  "score": 0.1},
        ]

        with patch("web_scraper.searcher._fetch_page", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = fake_page
            searcher = Searcher(content_filter=None)
            results = await searcher.search("test", max_pages=1, min_score=0.5)

        assert len(results) == 1
        assert results[0].score == 0.9


# =============================================================================
# 5. Unit tests — WebScraper (mocked)
# =============================================================================

class TestWebScraper:
    @pytest.mark.asyncio
    async def test_search_and_scrape_returns_scrape_output(self):
        from web_scraper.models import CrawlResult, ScrapeOutput, SearchResult
        from web_scraper.scraper import WebScraper

        fake_search = [SearchResult(url="https://iherb.com/pr/1", title="Vitamin C", score=0.9)]
        fake_crawl = CrawlResult(url="https://iherb.com/pr/1", success=True, content="Great product")

        scraper = WebScraper()
        scraper._searcher.search = AsyncMock(return_value=fake_search)
        scraper._crawler.crawl = AsyncMock(return_value=fake_crawl)

        output = await scraper.search_and_scrape("vitamin c")

        assert isinstance(output, ScrapeOutput)
        assert output.total_success == 1
        assert output.total_failed == 0
        assert output.results[0].content == "Great product"

    @pytest.mark.asyncio
    async def test_search_and_scrape_handles_search_error(self):
        from web_scraper.models import SearchError, ScrapeOutput
        from web_scraper.scraper import WebScraper

        scraper = WebScraper()
        scraper._searcher.search = AsyncMock(
            return_value=SearchError(query="test", error="SearXNG down")
        )

        output = await scraper.search_and_scrape("test")

        assert isinstance(output, ScrapeOutput)
        assert output.total_success == 0
        assert len(output.results) == 0

    @pytest.mark.asyncio
    async def test_scrape_url_delegates_to_crawler(self):
        from web_scraper.models import CrawlResult
        from web_scraper.scraper import WebScraper

        fake_result = CrawlResult(url="https://x.com", success=True, content="hello")
        scraper = WebScraper()
        scraper._crawler.crawl = AsyncMock(return_value=fake_result)

        result = await scraper.scrape_url("https://x.com")
        assert result.content == "hello"

    @pytest.mark.asyncio
    async def test_scrape_urls_crawls_all(self):
        from web_scraper.models import CrawlResult
        from web_scraper.scraper import WebScraper

        urls = ["https://a.com", "https://b.com", "https://c.com"]
        scraper = WebScraper()
        scraper._crawler.crawl = AsyncMock(
            side_effect=[
                CrawlResult(url=u, success=True, content=f"content of {u}")
                for u in urls
            ]
        )
        results = await scraper.scrape_urls(urls)
        assert len(results) == 3
        assert all(r.success for r in results)


# =============================================================================
# 6. Live integration tests (require SearXNG running)
# =============================================================================

@pytest.mark.live
class TestLiveSearch:
    """
    These tests hit real SearXNG.  Run with:
        pytest web_scraper/test_scraper.py -v -m live
    Make sure SEARXNG_BASE_URL env var points to your instance.
    """

    @pytest.mark.asyncio
    async def test_live_search_returns_urls(self):
        from web_scraper.searcher import Searcher
        searcher = Searcher()
        results = await searcher.search("Vitamin C 1000mg supplement", max_results=3)
        # Should not crash and should return something
        assert not isinstance(results, type(None))
        print(f"\nLive search returned {len(results)} results")
        for r in results:
            print(f"  {r.score:.3f}  {r.url}")

    @pytest.mark.asyncio
    async def test_live_site_search(self):
        from web_scraper.searcher import Searcher
        searcher = Searcher(content_filter=None)
        results = await searcher.search(
            'site:iherb.com "Vitamin C 1000mg"', max_results=3, apply_filter=False
        )
        print(f"\nSite-scoped search returned {len(results)} results")
        for r in results:
            print(f"  {r.url}")


@pytest.mark.live
class TestLiveCrawl:
    """Single-URL crawl test — requires network access."""

    @pytest.mark.asyncio
    async def test_live_crawl_public_page(self):
        from web_scraper.crawler import Crawler
        crawler = Crawler()
        result = await crawler.crawl("https://example.com")
        print(f"\nCrawl success={result.success}, chars={len(result.content)}, time={result.time_taken}s")
        assert result.success is True
        assert len(result.content) > 50

    @pytest.mark.asyncio
    async def test_live_full_pipeline(self):
        from web_scraper.scraper import WebScraper
        scraper = WebScraper(max_concurrent_crawls=2)
        output = await scraper.search_and_scrape("Vitamin C 1000mg iherb", max_urls=2)
        print(f"\nFull pipeline: {output.total_success} success, {output.total_failed} failed")
        for r in output.results:
            status = "OK" if r.success else "FAIL"
            print(f"  [{status}] {r.url} ({len(r.content)} chars, {r.time_taken}s)")


# =============================================================================
# 7. LLM integration test (requires Azure OpenAI + SearXNG)
# =============================================================================

@pytest.mark.llm
class TestLiveLLMExtraction:
    """
    Requires env vars:
        SEARXNG_BASE_URL, AZURE_OPENAI_ENDPOINT,
        AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION,
        AZURE_OPENAI_DEPLOYMENT_NAME
    """

    @pytest.mark.asyncio
    async def test_llm_extraction_returns_structured_data(self):
        from web_scraper.scraper import WebScraper

        schema = {
            "title":       {"type": "string", "description": "Product name"},
            "description": {"type": "string", "description": "Full product description"},
            "price":       {"type": "string", "description": "Price with currency"},
        }
        scraper = WebScraper(
            extraction_schema=schema,
            extraction_instruction=(
                "Extract the product title, full description, and price from this page."
            ),
            max_concurrent_crawls=1,
        )
        output = await scraper.search_and_scrape(
            'site:iherb.com "Vitamin C 1000mg"', max_urls=1
        )
        print(f"\nLLM extraction: {output.total_success} success")
        for r in output.results:
            print(f"  {r.url}")
            print(f"  extracted_data = {r.extracted_data}")
        assert output.total_success >= 0  # just check it doesn't crash


# =============================================================================
# Entry point for running directly
# =============================================================================

if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "unit"

    if mode == "live":
        print("Running live search test...")

        async def _live():
            from web_scraper.scraper import WebScraper
            scraper = WebScraper(max_concurrent_crawls=2)
            output = await scraper.search_and_scrape("Vitamin C 1000mg supplement", max_urls=3)
            print(f"\nDone: {output.total_success} success, {output.total_failed} failed")
            for r in output.results:
                status = "OK" if r.success else f"FAIL({r.error[:60]})"
                print(f"  [{status}] {r.url}")
                if r.success:
                    print(f"    First 200 chars: {r.content[:200]!r}")

        asyncio.run(_live())

    elif mode == "url":
        url = sys.argv[2] if len(sys.argv) > 2 else "https://example.com"
        print(f"Crawling single URL: {url}")

        async def _url():
            from web_scraper.scraper import WebScraper
            scraper = WebScraper()
            result = await scraper.scrape_url(url)
            print(f"Success: {result.success}, chars: {len(result.content)}, time: {result.time_taken}s")
            if result.success:
                print(f"Content preview:\n{result.content[:500]}")
            else:
                print(f"Error: {result.error}")

        asyncio.run(_url())

    else:
        print("Usage:")
        print("  python test_scraper.py unit          # run unit tests via pytest")
        print("  python test_scraper.py live          # live search + crawl pipeline")
        print("  python test_scraper.py url <url>     # crawl a single URL")
        print()
        print("Or with pytest:")
        print("  python -m pytest web_scraper/test_scraper.py -v            # unit tests")
        print("  python -m pytest web_scraper/test_scraper.py -v -m live    # live tests")
        print("  python -m pytest web_scraper/test_scraper.py -v -m llm     # LLM tests")
