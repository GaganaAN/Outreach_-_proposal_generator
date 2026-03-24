"""
web_scraper — standalone, reusable web scraping module.

Public API
----------
WebScraper   — main class (search + crawl)
Searcher     — SearXNG search only
Crawler      — single-URL crawl only
ContentFilter — URL relevance filter

Models
------
ScrapeOutput, CrawlResult, SearchResult, SearchError
"""

from web_scraper.crawler import Crawler
from web_scraper.filter import ContentFilter
from web_scraper.models import CrawlResult, ScrapeOutput, SearchError, SearchResult
from web_scraper.scraper import WebScraper
from web_scraper.searcher import Searcher

__all__ = [
    "WebScraper",
    "Searcher",
    "Crawler",
    "ContentFilter",
    "ScrapeOutput",
    "CrawlResult",
    "SearchResult",
    "SearchError",
]
